from sqlalchemy import inspect, select, text
from fastapi.testclient import TestClient

from app.auth0_oidc import Auth0Identity
from app.db import SessionLocal, engine
from app.main import app
from app.models import Notification, RegistrationRequest, User
from app.notifications import TYPE_REGISTRATION_REQUEST, unread_count
from app.registrations import STATUS_PENDING
from app.schema import migrate_schema
from tests.test_app import register_active
from tests.test_auth0 import _enable_auth0, _start_callback


def _grant_site_admin(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        user.is_site_admin = True
        db.commit()
    finally:
        db.close()


def _onboard(http: TestClient, sub: str, email: str, name: str, username: str):
    _start_callback(
        http,
        Auth0Identity(sub=sub, email=email, email_verified=True, name=name),
    )
    return http.post(
        "/auth/completar-perfil",
        data={"name": name, "username": username},
        follow_redirects=False,
    )


def test_is_site_admin_defaults_false_and_schema_exists():
    inspector = inspect(engine)
    user_cols = {column["name"] for column in inspector.get_columns("users")}
    assert "is_site_admin" in user_cols
    assert "registration_requests" in inspector.get_table_names()
    request_cols = {column["name"] for column in inspector.get_columns("registration_requests")}
    assert {
        "id",
        "user_id",
        "status",
        "created_at",
        "decided_at",
        "decided_by_user_id",
        "decision_note",
    } <= request_cols
    notice_cols = {column["name"]: column for column in inspector.get_columns("notifications")}
    assert notice_cols["club_id"]["nullable"] is True
    with engine.connect() as connection:
        index_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'ix_registration_requests_one_pending'")
        ).scalar()
        notice_index = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'ix_notifications_one_registration_per_admin'")
        ).scalar()
    assert notice_index
    assert "registration_request" in notice_index
    assert index_sql
    assert "pending" in index_sql.lower()
    http = TestClient(app)
    register_active(http, "site_flag", "site.flag@example.com")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "site.flag@example.com"))
        assert user.is_site_admin is False
    finally:
        db.close()
    home = http.get("/")
    assert 'aria-label="Administração"' not in home.text


def test_common_user_cannot_access_admin(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "admin_denied", "admin.denied@example.com")
    page = http.get("/admin", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/")
    cadastros = http.get("/admin/cadastros", follow_redirects=False)
    assert cadastros.status_code == 303
    created = _onboard(
        TestClient(app),
        "auth0|admin-target",
        "admin.target@example.com",
        "Alvo Admin",
        "alvo_admin",
    )
    assert created.headers["location"] == "/"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "admin.target@example.com"))
        item = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        assert user.is_active is True
        assert item is None
        request_id = 1
    finally:
        db.close()
    approve = http.post(f"/admin/cadastros/{request_id}/aprovar", follow_redirects=False)
    assert approve.status_code == 303
    assert approve.headers["location"].startswith("/")
    reject = http.post(f"/admin/cadastros/{request_id}/recusar", follow_redirects=False)
    assert reject.status_code == 303
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "admin.target@example.com"))
        assert user.is_active is True
        assert db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id)) is None
    finally:
        db.close()


def test_site_admin_cadastros_is_retired_and_new_users_skip_queue(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "site_admin_ok", "site.admin.ok@example.com")
    _grant_site_admin("site.admin.ok@example.com")
    home = admin.get("/")
    assert 'aria-label="Administração"' in home.text
    hub = admin.get("/admin", follow_redirects=False)
    assert hub.status_code == 303
    assert hub.headers["location"] == "/admin/sugestoes"
    listing = admin.get("/admin/sugestoes")
    assert listing.status_code == 200
    assert "Cadastros" not in listing.text
    assert "Sugestões" in listing.text
    assert "Denúncias" in listing.text
    created = _onboard(TestClient(app), "auth0|azi-eq", "azi.eq@example.com", "Azi Eq", "azi_eq")
    assert created.headers["location"] == "/"
    cadastros = admin.get("/admin/cadastros", follow_redirects=False)
    assert cadastros.status_code == 303
    assert cadastros.headers["location"] == "/admin/sugestoes"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "azi.eq@example.com"))
        assert user.is_active is True
        assert db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id)) is None
        notes = list(
            db.scalars(
                select(Notification).where(
                    Notification.type == TYPE_REGISTRATION_REQUEST,
                    Notification.actor_user_id == user.id,
                )
            )
        )
        assert notes == []
        admin_id = db.scalar(select(User.id).where(User.email == "site.admin.ok@example.com"))
        assert unread_count(db, admin_id) == 0
    finally:
        db.close()
    approve = admin.post("/admin/cadastros/99/aprovar", follow_redirects=False)
    assert approve.status_code == 303
    assert approve.headers["location"] == "/admin/sugestoes"


def test_schema_keeps_historical_registration_rows_without_backfill(monkeypatch):
    _enable_auth0(monkeypatch)
    db = SessionLocal()
    try:
        leftover = User(
            name="Azi Backfill",
            username="azi_backfill",
            username_key="azi_backfill",
            email="azi.backfill@example.com",
            password_hash="",
            is_active=False,
            auth0_sub="auth0|azi-backfill",
            is_site_admin=False,
        )
        historic = User(
            name="Histórico",
            username="azi_hist",
            username_key="azi_hist",
            email="azi.hist@example.com",
            password_hash="",
            is_active=False,
            auth0_sub="auth0|azi-hist",
        )
        db.add(leftover)
        db.add(historic)
        db.flush()
        row = RegistrationRequest(user_id=historic.id, status=STATUS_PENDING)
        db.add(row)
        db.commit()
        leftover_id = leftover.id
        historic_id = historic.id
        historic_request_id = row.id
    finally:
        db.close()
    migrate_schema()
    migrate_schema()
    db = SessionLocal()
    try:
        leftover = db.get(User, leftover_id)
        historic = db.get(User, historic_id)
        assert leftover.is_active is False
        assert list(db.scalars(select(RegistrationRequest).where(RegistrationRequest.user_id == leftover_id))) == []
        kept = db.get(RegistrationRequest, historic_request_id)
        assert kept is not None
        assert kept.user_id == historic.id
        assert kept.status == STATUS_PENDING
        assert historic.id == historic_id
    finally:
        db.close()


def test_retired_approve_does_not_send_email_or_alter_active_user(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "mail_admin", "mail.admin@example.com")
    _grant_site_admin("mail.admin@example.com")
    created = _onboard(TestClient(app), "auth0|mail-skip", "mail.skip@example.com", "Mail Skip", "mail_skip")
    assert created.headers["location"] == "/"
    sent = []
    monkeypatch.setattr("app.mail._send_email", lambda *args: sent.append(args))
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "mail.skip@example.com"))
        user_id = user.id
    finally:
        db.close()
    admin.post("/admin/cadastros/1/aprovar", follow_redirects=False)
    admin.post("/admin/cadastros/1/recusar", follow_redirects=False)
    assert sent == []
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        assert user.is_active is True
    finally:
        db.close()


def test_legacy_login_is_closed_when_auth0_is_configured(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "legado_ok", "legado.ok@example.com")
    http.post("/logout", follow_redirects=False)
    login = http.post(
        "/login",
        data={"email": "legado.ok@example.com", "password": "segredo"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert "tenant.example.auth0.com" in login.headers["location"]
    assert "/authorize" in login.headers["location"]
    register = http.get("/register", follow_redirects=False)
    assert register.status_code == 303
    assert "screen_hint=signup" in register.headers["location"]
    google = http.get("/auth/google", follow_redirects=False)
    assert google.status_code == 303
    assert "accounts.google.com" not in google.headers["location"]
    assert "tenant.example.auth0.com" in google.headers["location"]


def test_historical_registration_notice_does_not_badge_admin(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "bell_admin", "bell.admin@example.com")
    _grant_site_admin("bell.admin@example.com")
    db = SessionLocal()
    try:
        admin_id = db.scalar(select(User.id).where(User.email == "bell.admin@example.com"))
        db.add(
            Notification(
                user_id=admin_id,
                type=TYPE_REGISTRATION_REQUEST,
                club_id=None,
                actor_user_id=admin_id,
                related_id=1,
            )
        )
        db.commit()
        assert unread_count(db, admin_id) == 0
    finally:
        db.close()
    page = admin.get("/")
    assert "Cadastros" not in page.text
