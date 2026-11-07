from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text

from app.accounts import utcnow
from app.auth0_oidc import Auth0Identity
from app.db import SessionLocal, engine
from app.main import app
from app.models import Notification, RegistrationRequest, RegistrationReview, User
from app.notifications import TYPE_REGISTRATION_REQUEST, TYPE_REGISTRATION_REVIEW
from app.registrations import (
    REVIEW_APPROVED,
    REVIEW_MESSAGE_MAX,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    STATUS_EXPIRED,
    STATUS_REJECTED,
)
from app.schema import migrate_schema
from tests.test_admin_registrations import _grant_site_admin, _onboard
from tests.test_app import register_active
from tests.test_auth0 import _enable_auth0, _start_callback
from tests.test_registration_expiry import _age_request, _request_for_email


def _reject_latest(admin: TestClient, email: str) -> int:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        item = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        request_id = item.id
    finally:
        db.close()
    refused = admin.post(f"/admin/cadastros/{request_id}/recusar", follow_redirects=False)
    assert refused.status_code == 303
    return request_id


def _review_for_email(email: str) -> tuple[int | None, int, int]:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        request = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        review = db.scalar(
            select(RegistrationReview).where(RegistrationReview.registration_request_id == request.id)
        )
        return (review.id if review else None), request.id, user.id
    finally:
        db.close()


def test_review_schema_and_unique_indexes():
    migrate_schema()
    inspector = inspect(engine)
    assert "registration_reviews" in inspector.get_table_names()
    cols = {column["name"] for column in inspector.get_columns("registration_reviews")}
    assert {
        "id",
        "registration_request_id",
        "user_id",
        "message",
        "status",
        "created_at",
        "decided_at",
        "decided_by_user_id",
    } <= cols
    with engine.connect() as connection:
        review_index = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'ix_registration_reviews_request_id'")
        ).scalar()
        notice_index = connection.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE name = 'ix_notifications_one_registration_review_per_admin'"
            )
        ).scalar()
    assert review_index
    assert "registration_request_id" in review_index
    assert notice_index
    assert "registration_review" in notice_index


def test_rejected_can_request_review_once(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "rev_ok_admin", "rev.ok.admin@example.com")
    _grant_site_admin("rev.ok.admin@example.com")
    person = TestClient(app)
    _onboard(person, "auth0|rev-ok", "rev.ok.user@example.com", "Azi Review", "azi_review")
    pending_page = person.get("/auth/aguardando")
    assert "Solicitar revisão" not in pending_page.text
    _reject_latest(admin, "rev.ok.user@example.com")
    refused = person.get("/auth/nao-aprovado")
    assert refused.status_code == 200
    assert "Solicitação não aprovada" in refused.text
    assert "Solicitar revisão" in refused.text
    form = person.get("/auth/revisao")
    assert form.status_code == 200
    assert "Solicitar revisão" in form.text
    empty = person.post("/auth/revisao", data={"message": "   "}, follow_redirects=False)
    assert empty.status_code == 303
    assert "error=" in empty.headers["location"]
    too_long = person.post("/auth/revisao", data={"message": "x" * (REVIEW_MESSAGE_MAX + 1)}, follow_redirects=False)
    assert too_long.status_code == 303
    assert "error=" in too_long.headers["location"]
    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(RegistrationReview)) == 0
    finally:
        db.close()
    created = person.post(
        "/auth/revisao",
        data={"message": "  Gostaria de uma nova análise.  ", "user_id": "999", "registration_request_id": "999"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/auth/revisao-solicitada"
    again = person.post("/auth/revisao", data={"message": "segunda tentativa"}, follow_redirects=False)
    assert again.status_code == 303
    assert again.headers["location"] == "/auth/revisao-solicitada"
    waiting = person.get("/auth/revisao-solicitada")
    assert waiting.status_code == 200
    assert "Revisão solicitada" in waiting.text
    assert "Solicitar revisão" not in waiting.text
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "rev.ok.user@example.com"))
        request = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        reviews = list(db.scalars(select(RegistrationReview).where(RegistrationReview.user_id == user.id)))
        assert len(reviews) == 1
        assert reviews[0].message == "Gostaria de uma nova análise."
        assert reviews[0].status == REVIEW_PENDING
        assert request.status == STATUS_REJECTED
        assert user.is_active is False
    finally:
        db.close()
    callback = _start_callback(
        person,
        Auth0Identity(sub="auth0|rev-ok", email="rev.ok.user@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/auth/revisao-solicitada"


def test_expired_and_foreign_identity_cannot_create_review(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "rev_exp_admin", "rev.exp.admin@example.com")
    _grant_site_admin("rev.exp.admin@example.com")
    expired = TestClient(app)
    _onboard(expired, "auth0|rev-exp", "rev.exp.user@example.com", "Exp Review", "exp_review")
    request_id, _user_id = _request_for_email("rev.exp.user@example.com")
    _age_request(request_id, timedelta(days=8))
    expired_page = expired.get("/auth/expirada")
    assert expired_page.status_code == 200
    assert "Solicitar revisão" not in expired_page.text
    form = expired.get("/auth/revisao", follow_redirects=False)
    assert form.headers["location"] == "/auth/expirada"
    posted = expired.post("/auth/revisao", data={"message": "quero revisão"}, follow_redirects=False)
    assert posted.headers["location"] == "/auth/expirada"
    db = SessionLocal()
    try:
        assert db.scalar(select(RegistrationReview).where(RegistrationReview.registration_request_id == request_id)) is None
        assert db.get(RegistrationRequest, request_id).status == STATUS_EXPIRED
    finally:
        db.close()
    other = TestClient(app)
    posted_other = other.post("/auth/revisao", data={"message": "intruso"}, follow_redirects=False)
    assert "/login" in posted_other.headers["location"]


def test_review_notifies_site_admins_only_and_opens_detail(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "rev_bell_admin", "rev.bell.admin@example.com")
    _grant_site_admin("rev.bell.admin@example.com")
    extra = TestClient(app)
    register_active(extra, "rev_bell_two", "rev.bell.two@example.com")
    _grant_site_admin("rev.bell.two@example.com")
    club_owner = TestClient(app)
    register_active(club_owner, "rev_club_adm", "rev.club.adm@example.com")
    created = club_owner.post("/clubs", data={"name": "Clube Review"}, follow_redirects=False)
    assert created.status_code == 303
    person = TestClient(app)
    _onboard(person, "auth0|rev-bell", "rev.bell.user@example.com", "Azi", "azi_crow_rev")
    _reject_latest(admin, "rev.bell.user@example.com")
    person.post("/auth/revisao", data={"message": "Peço uma nova análise."}, follow_redirects=False)
    person.post("/auth/revisao", data={"message": "Peço uma nova análise."}, follow_redirects=False)
    _start_callback(person, Auth0Identity(sub="auth0|rev-bell", email="rev.bell.user@example.com", email_verified=True))
    review_id, request_id, user_id = _review_for_email("rev.bell.user@example.com")
    db = SessionLocal()
    try:
        notes = list(
            db.scalars(
                select(Notification).where(
                    Notification.type == TYPE_REGISTRATION_REVIEW,
                    Notification.related_id == review_id,
                )
            )
        )
        recipients = {note.user_id for note in notes}
        admin_ids = set(
            db.scalars(select(User.id).where(User.email.in_(["rev.bell.admin@example.com", "rev.bell.two@example.com"])))
        )
        club_id = db.scalar(select(User.id).where(User.email == "rev.club.adm@example.com"))
        originals = list(
            db.scalars(
                select(Notification).where(
                    Notification.type == TYPE_REGISTRATION_REQUEST,
                    Notification.related_id == request_id,
                )
            )
        )
        assert admin_ids <= recipients
        for admin_id in admin_ids:
            assert sum(1 for note in notes if note.user_id == admin_id) == 1
        assert club_id not in recipients
        assert all(user.is_site_admin for user in db.scalars(select(User).where(User.id.in_(recipients))))
        assert originals
        inbox = admin.get("/")
        assert "solicitou revisão da solicitação de cadastro" in inbox.text
        note_id = db.scalar(
            select(Notification.id).where(
                Notification.type == TYPE_REGISTRATION_REVIEW,
                Notification.related_id == review_id,
                Notification.user_id == select(User.id)
                .where(User.email == "rev.bell.admin@example.com")
                .scalar_subquery(),
            )
        )
    finally:
        db.close()
    listing = admin.get("/admin/cadastros?aba=revisoes")
    assert listing.status_code == 200
    assert "Azi" in listing.text
    assert f'href="/admin/cadastros/revisoes/{review_id}"' in listing.text
    opened = admin.get(f"/notificacoes/{note_id}", follow_redirects=False)
    assert opened.headers["location"] == f"/admin/cadastros/revisoes/{review_id}"
    detail = admin.get(opened.headers["location"])
    assert "Azi" in detail.text
    assert "@azi_crow_rev" in detail.text
    assert "Peço uma nova análise." in detail.text
    assert "Aprovar acesso" in detail.text
    assert "Manter recusa" in detail.text


def test_review_approved_activates_same_user(monkeypatch):
    _enable_auth0(monkeypatch)
    sent = []
    monkeypatch.setattr("app.mail._send_email", lambda *args: sent.append(args))
    admin = TestClient(app)
    register_active(admin, "rev_yes_admin", "rev.yes.admin@example.com")
    _grant_site_admin("rev.yes.admin@example.com")
    person = TestClient(app)
    _onboard(person, "auth0|rev-yes", "rev.yes.user@example.com", "Yes Review", "yes_review")
    _reject_latest(admin, "rev.yes.user@example.com")
    person.post("/auth/revisao", data={"message": "Reconsidere, por favor."}, follow_redirects=False)
    review_id, request_id, user_id = _review_for_email("rev.yes.user@example.com")
    approved = admin.post(f"/admin/cadastros/revisoes/{review_id}/aprovar-acesso", follow_redirects=False)
    assert approved.status_code == 303
    again = admin.post(f"/admin/cadastros/revisoes/{review_id}/aprovar-acesso", follow_redirects=False)
    assert again.status_code == 303
    assert "já foi analisada" in unquote(again.headers["location"])
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        request = db.get(RegistrationRequest, request_id)
        review = db.get(RegistrationReview, review_id)
        assert user.id == user_id
        assert user.is_active is True
        assert user.auth0_sub == "auth0|rev-yes"
        assert request.status == STATUS_REJECTED
        assert review.status == REVIEW_APPROVED
        admin_id = db.scalar(select(User.id).where(User.email == "rev.yes.admin@example.com"))
        note_id = db.scalar(
            select(Notification.id).where(
                Notification.type == TYPE_REGISTRATION_REVIEW,
                Notification.related_id == review_id,
                Notification.user_id == admin_id,
            )
        )
    finally:
        db.close()
    review_mails = [item for item in sent if item[1].startswith("Sua revisão") or item[1].startswith("Sobre sua revisão")]
    assert len(review_mails) == 1
    assert "foi aprovado" in review_mails[0][2]
    callback = _start_callback(
        person,
        Auth0Identity(sub="auth0|rev-yes", email="rev.yes.user@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/"
    home = person.get("/")
    assert 'aria-label="Configurações"' in home.text
    listing = admin.get("/admin/cadastros?aba=revisoes")
    assert f'href="/admin/cadastros/revisoes/{review_id}"' not in listing.text
    detail = admin.get(f"/admin/cadastros/revisoes/{review_id}")
    assert "Aprovada" in detail.text
    assert "Aprovar acesso" not in detail.text
    assert "Manter recusa" not in detail.text
    opened = admin.get(f"/notificacoes/{note_id}", follow_redirects=False)
    assert opened.headers["location"] == f"/admin/cadastros/revisoes/{review_id}"


def test_review_rejected_blocks_second_review(monkeypatch):
    _enable_auth0(monkeypatch)
    sent = []
    monkeypatch.setattr("app.mail._send_email", lambda *args: sent.append(args))
    admin = TestClient(app)
    register_active(admin, "rev_no_admin", "rev.no.admin@example.com")
    _grant_site_admin("rev.no.admin@example.com")
    person = TestClient(app)
    _onboard(person, "auth0|rev-no", "rev.no.user@example.com", "No Review", "no_review")
    _reject_latest(admin, "rev.no.user@example.com")
    person.post("/auth/revisao", data={"message": "Ainda quero entrar."}, follow_redirects=False)
    review_id, request_id, user_id = _review_for_email("rev.no.user@example.com")
    kept = admin.post(f"/admin/cadastros/revisoes/{review_id}/manter-recusa", follow_redirects=False)
    assert kept.status_code == 303
    again = admin.post(f"/admin/cadastros/revisoes/{review_id}/aprovar-acesso", follow_redirects=False)
    assert "já foi analisada" in unquote(again.headers["location"])
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        request = db.get(RegistrationRequest, request_id)
        review = db.get(RegistrationReview, review_id)
        assert user.is_active is False
        assert request.status == STATUS_REJECTED
        assert review.status == REVIEW_REJECTED
        assert db.scalar(select(func.count()).select_from(RegistrationReview).where(RegistrationReview.user_id == user_id)) == 1
    finally:
        db.close()
    assert any("continua não aprovado" in item[2] for item in sent)
    assert all("poderá solicitar uma revisão" not in item[2] for item in sent if "revisão foi analisada" in item[2])
    page = person.get("/auth/revisao-nao-aprovada")
    assert page.status_code == 200
    assert "Revisão não aprovada" in page.text
    assert "Solicitar revisão" not in page.text
    retry = person.get("/auth/revisao", follow_redirects=False)
    assert retry.headers["location"] == "/auth/revisao-nao-aprovada"
    retry_post = person.post("/auth/revisao", data={"message": "outra"}, follow_redirects=False)
    assert retry_post.headers["location"] == "/auth/revisao-nao-aprovada"
    callback = _start_callback(
        person,
        Auth0Identity(sub="auth0|rev-no", email="rev.no.user@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/auth/revisao-nao-aprovada"


def test_two_admins_first_decision_wins(monkeypatch):
    _enable_auth0(monkeypatch)
    sent = []
    monkeypatch.setattr("app.mail._send_email", lambda *args: sent.append(args))
    first = TestClient(app)
    register_active(first, "rev_race_a", "rev.race.a@example.com")
    _grant_site_admin("rev.race.a@example.com")
    second = TestClient(app)
    register_active(second, "rev_race_b", "rev.race.b@example.com")
    _grant_site_admin("rev.race.b@example.com")
    person = TestClient(app)
    _onboard(person, "auth0|rev-race", "rev.race.user@example.com", "Race Review", "race_review")
    _reject_latest(first, "rev.race.user@example.com")
    person.post("/auth/revisao", data={"message": "Corrida de decisão."}, follow_redirects=False)
    review_id, request_id, user_id = _review_for_email("rev.race.user@example.com")

    def decide(client_and_action):
        client, action = client_and_action
        return client.post(f"/admin/cadastros/revisoes/{review_id}/{action}", follow_redirects=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, [(first, "aprovar-acesso"), (second, "manter-recusa")]))
    assert all(item.status_code == 303 for item in results)
    db = SessionLocal()
    try:
        review = db.get(RegistrationReview, review_id)
        user = db.get(User, user_id)
        request = db.get(RegistrationRequest, request_id)
        assert review.status in {REVIEW_APPROVED, REVIEW_REJECTED}
        assert request.status == STATUS_REJECTED
        if review.status == REVIEW_APPROVED:
            assert user.is_active is True
        else:
            assert user.is_active is False
    finally:
        db.close()
    review_mails = [item for item in sent if item[1].startswith("Sua revisão") or item[1].startswith("Sobre sua revisão")]
    assert len(review_mails) == 1


def test_review_smtp_failure_keeps_decision(monkeypatch):
    from app.mail import MailDeliveryError

    _enable_auth0(monkeypatch)
    monkeypatch.setattr(
        "app.registrations.send_registration_review_approved_email",
        lambda *args, **kwargs: (_ for _ in ()).throw(MailDeliveryError("smtp")),
    )
    admin = TestClient(app)
    register_active(admin, "rev_smtp_admin", "rev.smtp.admin@example.com")
    _grant_site_admin("rev.smtp.admin@example.com")
    person = TestClient(app)
    _onboard(person, "auth0|rev-smtp", "rev.smtp.user@example.com", "Smtp Review", "smtp_review")
    _reject_latest(admin, "rev.smtp.user@example.com")
    person.post("/auth/revisao", data={"message": "Falha de SMTP."}, follow_redirects=False)
    review_id, _request_id, user_id = _review_for_email("rev.smtp.user@example.com")
    approved = admin.post(f"/admin/cadastros/revisoes/{review_id}/aprovar-acesso", follow_redirects=False)
    assert approved.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(RegistrationReview, review_id).status == REVIEW_APPROVED
        assert db.get(User, user_id).is_active is True
    finally:
        db.close()


def test_lazy_expiration_and_autolink_still_work_with_reviews(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "rev_keep_admin", "rev.keep.admin@example.com")
    _grant_site_admin("rev.keep.admin@example.com")
    waiting = TestClient(app)
    _onboard(waiting, "auth0|rev-keep", "rev.keep.user@example.com", "Keep Review", "keep_review")
    request_id, user_id = _request_for_email("rev.keep.user@example.com")
    _age_request(request_id, timedelta(days=7))
    refreshed = waiting.get("/auth/aguardando", follow_redirects=False)
    assert refreshed.headers["location"] == "/auth/expirada"
    db = SessionLocal()
    try:
        assert db.get(RegistrationRequest, request_id).status == STATUS_EXPIRED
        assert db.scalar(select(RegistrationReview).where(RegistrationReview.user_id == user_id)) is None
    finally:
        db.close()
    legacy = TestClient(app)
    register_active(legacy, "rev_legado", "rev.legado@example.com")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "rev.legado@example.com"))
        user_id = user.id
        assert user.auth0_sub is None
    finally:
        db.close()
    legacy.post("/logout", follow_redirects=False)
    first = _start_callback(
        legacy,
        Auth0Identity(sub="auth0|rev-legado", email="rev.legado@example.com", email_verified=False),
    )
    assert first.headers["location"] == "/auth/verificar-email"
    started = legacy.get("/auth/verificar-email/continuar", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    with patch(
        "app.main.redeem_callback",
        return_value=Auth0Identity(sub="auth0|rev-legado", email="rev.legado@example.com", email_verified=True),
    ):
        callback = legacy.get(f"/callback?code=fake&state={state}", follow_redirects=False)
    assert callback.headers["location"] == "/"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "rev.legado@example.com"))
        assert user.id == user_id
        assert user.auth0_sub == "auth0|rev-legado"
        assert db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user_id)) is None
        assert db.scalar(select(RegistrationReview).where(RegistrationReview.user_id == user_id)) is None
    finally:
        db.close()
