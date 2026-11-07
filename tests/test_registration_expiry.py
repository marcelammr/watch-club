from datetime import timedelta
from urllib.parse import unquote

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.accounts import utcnow
from app.auth0_oidc import Auth0Identity
from app.db import SessionLocal
from app.main import app
from app.models import Notification, RegistrationRequest, User
from app.notifications import TYPE_REGISTRATION_REQUEST
from app.registrations import (
    EXPIRED_DECISION_MESSAGE,
    REGISTRATION_PENDING_DAYS,
    STATUS_APPROVED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_REJECTED,
    effective_registration_status,
    expire_registration_if_needed,
    is_registration_overdue,
    registration_expires_at,
)
from tests.test_admin_registrations import _grant_site_admin, _onboard
from tests.test_app import register_active
from tests.test_auth0 import _enable_auth0, _start_callback


def _age_request(request_id: int, age: timedelta) -> None:
    db = SessionLocal()
    try:
        item = db.get(RegistrationRequest, request_id)
        item.created_at = utcnow() - age
        db.commit()
    finally:
        db.close()


def _request_for_email(email: str) -> tuple[int, int]:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        item = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        return item.id, user.id
    finally:
        db.close()


def test_registration_deadline_helpers_use_naive_utc():
    created = utcnow()
    assert registration_expires_at(created) == created + timedelta(days=REGISTRATION_PENDING_DAYS)
    pending = RegistrationRequest(
        user_id=1,
        status=STATUS_PENDING,
        created_at=created - timedelta(days=6, hours=23),
    )
    assert is_registration_overdue(pending) is False
    assert effective_registration_status(pending) == STATUS_PENDING
    exact = RegistrationRequest(
        user_id=1,
        status=STATUS_PENDING,
        created_at=created - timedelta(days=7),
    )
    assert is_registration_overdue(exact) is True
    assert effective_registration_status(exact) == STATUS_EXPIRED
    late = RegistrationRequest(
        user_id=1,
        status=STATUS_PENDING,
        created_at=created - timedelta(days=7, seconds=1),
    )
    assert is_registration_overdue(late) is True
    approved = RegistrationRequest(
        user_id=1,
        status=STATUS_APPROVED,
        created_at=created - timedelta(days=30),
    )
    rejected = RegistrationRequest(
        user_id=1,
        status=STATUS_REJECTED,
        created_at=created - timedelta(days=30),
    )
    assert is_registration_overdue(approved) is False
    assert effective_registration_status(approved) == STATUS_APPROVED
    assert is_registration_overdue(rejected) is False
    assert effective_registration_status(rejected) == STATUS_REJECTED


def test_pending_under_seven_days_can_still_be_approved(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "exp_ok_admin", "exp.ok.admin@example.com")
    _grant_site_admin("exp.ok.admin@example.com")
    _onboard(TestClient(app), "auth0|exp-ok", "exp.ok.user@example.com", "Exp Ok", "exp_ok_user")
    request_id, _user_id = _request_for_email("exp.ok.user@example.com")
    _age_request(request_id, timedelta(days=6, hours=23))
    approved = admin.post(f"/admin/cadastros/{request_id}/aprovar", follow_redirects=False)
    assert approved.status_code == 303
    assert "aprovada" in unquote(approved.headers["location"])
    db = SessionLocal()
    try:
        row = db.get(RegistrationRequest, request_id)
        user = db.get(User, row.user_id)
        assert row.status == STATUS_APPROVED
        assert user.is_active is True
    finally:
        db.close()


def test_expired_request_cannot_be_approved_or_rejected(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "exp_block_admin", "exp.block.admin@example.com")
    _grant_site_admin("exp.block.admin@example.com")
    _onboard(TestClient(app), "auth0|exp-block", "exp.block.user@example.com", "Exp Block", "exp_block_user")
    request_id, user_id = _request_for_email("exp.block.user@example.com")
    _age_request(request_id, timedelta(days=7))
    sent = []
    monkeypatch.setattr("app.mail._send_email", lambda *args: sent.append(args))
    db = SessionLocal()
    try:
        before_notes = db.scalar(select(func.count()).select_from(Notification).where(
            Notification.type == TYPE_REGISTRATION_REQUEST
        ))
        auth0_sub = db.get(User, user_id).auth0_sub
    finally:
        db.close()
    approved = admin.post(f"/admin/cadastros/{request_id}/aprovar", follow_redirects=False)
    assert approved.status_code == 303
    assert approved.headers["location"].startswith(f"/admin/cadastros/{request_id}")
    assert EXPIRED_DECISION_MESSAGE in unquote(approved.headers["location"])
    page = admin.get(approved.headers["location"])
    assert page.status_code == 200
    assert "Expirada" in page.text
    assert EXPIRED_DECISION_MESSAGE in page.text
    assert "Aprovar" not in page.text
    assert "Recusar" not in page.text
    db = SessionLocal()
    try:
        row = db.get(RegistrationRequest, request_id)
        user = db.get(User, row.user_id)
        assert row.status == STATUS_EXPIRED
        assert row.decided_by_user_id is None
        assert row.decided_at is not None
        assert user.is_active is False
        assert user.auth0_sub == auth0_sub
        after_notes = db.scalar(select(func.count()).select_from(Notification).where(
            Notification.type == TYPE_REGISTRATION_REQUEST
        ))
        assert after_notes == before_notes
    finally:
        db.close()
    assert sent == []
    _onboard(TestClient(app), "auth0|exp-rej", "exp.rej.user@example.com", "Exp Rej", "exp_rej_user")
    other_id, other_user_id = _request_for_email("exp.rej.user@example.com")
    _age_request(other_id, timedelta(days=7, seconds=1))
    rejected = admin.post(f"/admin/cadastros/{other_id}/recusar", follow_redirects=False)
    assert rejected.status_code == 303
    assert EXPIRED_DECISION_MESSAGE in unquote(rejected.headers["location"])
    db = SessionLocal()
    try:
        row = db.get(RegistrationRequest, other_id)
        assert row.status == STATUS_EXPIRED
        assert db.get(User, other_user_id).is_active is False
    finally:
        db.close()
    assert sent == []


def test_old_approved_and_rejected_do_not_expire():
    created = utcnow() - timedelta(days=40)
    db = SessionLocal()
    try:
        approved = RegistrationRequest(user_id=1, status=STATUS_APPROVED, created_at=created)
        rejected = RegistrationRequest(user_id=1, status=STATUS_REJECTED, created_at=created)
        expire_registration_if_needed(db, approved)
        expire_registration_if_needed(db, rejected)
        assert approved.status == STATUS_APPROVED
        assert rejected.status == STATUS_REJECTED
    finally:
        db.close()


def test_awaiting_refresh_and_login_go_to_expired(monkeypatch):
    _enable_auth0(monkeypatch)
    waiting = TestClient(app)
    created = _onboard(waiting, "auth0|exp-wait", "exp.wait@example.com", "Exp Wait", "exp_wait_user")
    assert created.headers["location"] == "/auth/aguardando"
    request_id, user_id = _request_for_email("exp.wait@example.com")
    _age_request(request_id, timedelta(days=7, minutes=1))
    refreshed = waiting.get("/auth/aguardando", follow_redirects=False)
    assert refreshed.status_code == 303
    assert refreshed.headers["location"] == "/auth/expirada"
    page = waiting.get("/auth/expirada")
    assert page.status_code == 200
    assert "Solicitação expirada" in page.text
    assert "não foi analisado em 7 dias" in page.text
    assert 'href="/auth/logout"' in page.text
    assert "Aguardar" not in page.text
    profile = waiting.get("/auth/completar-perfil", follow_redirects=False)
    assert profile.headers["location"] == "/auth/expirada"
    callback = _start_callback(
        waiting,
        Auth0Identity(sub="auth0|exp-wait", email="exp.wait@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/auth/expirada"
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(RegistrationRequest).where(RegistrationRequest.user_id == user_id)))
        assert len(rows) == 1
        assert rows[0].status == STATUS_EXPIRED
        notes = list(
            db.scalars(
                select(Notification).where(
                    Notification.type == TYPE_REGISTRATION_REQUEST,
                    Notification.related_id == request_id,
                )
            )
        )
        assert len(notes) == len({note.user_id for note in notes})
    finally:
        db.close()


def test_admin_list_hides_overdue_and_old_notice_opens_expired_detail(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "exp_list_admin", "exp.list.admin@example.com")
    _grant_site_admin("exp.list.admin@example.com")
    _onboard(TestClient(app), "auth0|exp-list", "exp.list.user@example.com", "Exp List", "exp_list_user")
    _onboard(TestClient(app), "auth0|exp-fresh", "exp.fresh.user@example.com", "Exp Fresh", "exp_fresh_user")
    stale_id, _stale_user_id = _request_for_email("exp.list.user@example.com")
    fresh_id, _fresh_user_id = _request_for_email("exp.fresh.user@example.com")
    _age_request(stale_id, timedelta(days=8))
    db = SessionLocal()
    try:
        admin_id = db.scalar(select(User.id).where(User.email == "exp.list.admin@example.com"))
        note = db.scalar(
            select(Notification).where(
                Notification.type == TYPE_REGISTRATION_REQUEST,
                Notification.related_id == stale_id,
                Notification.user_id == admin_id,
            )
        )
        note_id = note.id
        before_notes = db.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.type == TYPE_REGISTRATION_REQUEST,
                Notification.related_id == stale_id,
            )
        )
    finally:
        db.close()
    listing = admin.get("/admin/cadastros")
    assert listing.status_code == 200
    assert f'href="/admin/cadastros/{fresh_id}"' in listing.text
    assert f'href="/admin/cadastros/{stale_id}"' not in listing.text
    opened = admin.get(f"/notificacoes/{note_id}", follow_redirects=False)
    assert opened.headers["location"] == f"/admin/cadastros/{stale_id}"
    detail = admin.get(opened.headers["location"])
    assert detail.status_code == 200
    assert "Expirada" in detail.text
    assert "Aprovar" not in detail.text
    assert "Recusar" not in detail.text
    db = SessionLocal()
    try:
        assert db.get(RegistrationRequest, stale_id).status == STATUS_EXPIRED
        after_notes = db.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.type == TYPE_REGISTRATION_REQUEST,
                Notification.related_id == stale_id,
            )
        )
        assert after_notes == before_notes
        assert db.get(RegistrationRequest, fresh_id).status == STATUS_PENDING
    finally:
        db.close()
