from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.accounts import utcnow
from app.auth0_oidc import Auth0Identity
from app.db import SessionLocal
from app.main import app
from app.models import RegistrationRequest, User
from app.registrations import (
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
from tests.test_admin_registrations import _onboard
from tests.test_auth0 import _enable_auth0, _start_callback


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


def test_new_signup_does_not_wait_on_expiry_window(monkeypatch):
    _enable_auth0(monkeypatch)
    created = _onboard(TestClient(app), "auth0|exp-ok", "exp.ok.user@example.com", "Exp Ok", "exp_ok_user")
    assert created.headers["location"] == "/"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "exp.ok.user@example.com"))
        assert user.is_active is True
        assert db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id)) is None
    finally:
        db.close()


def test_historical_expired_request_still_auto_activates(monkeypatch):
    _enable_auth0(monkeypatch)
    db = SessionLocal()
    try:
        user = User(
            name="Exp Hist",
            username="exp_hist",
            username_key="exp_hist",
            email="exp.hist@example.com",
            password_hash="",
            is_active=False,
            auth0_sub="auth0|exp-hist",
        )
        db.add(user)
        db.flush()
        request = RegistrationRequest(
            user_id=user.id,
            status=STATUS_PENDING,
            created_at=utcnow() - timedelta(days=30),
        )
        db.add(request)
        db.commit()
        user_id = user.id
        request_id = request.id
    finally:
        db.close()
    db = SessionLocal()
    try:
        item = expire_registration_if_needed(db, db.get(RegistrationRequest, request_id))
        db.commit()
        assert item.status == STATUS_EXPIRED
    finally:
        db.close()
    http = TestClient(app)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|exp-hist", email="exp.hist@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/"
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        assert user.is_active is True
        assert db.get(RegistrationRequest, request_id) is not None
    finally:
        db.close()
    expired_page = http.get("/auth/expirada", follow_redirects=False)
    assert expired_page.status_code == 303
    assert expired_page.headers["location"] == "/"
