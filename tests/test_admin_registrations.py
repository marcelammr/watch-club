from sqlalchemy import inspect, select
from fastapi.testclient import TestClient

from app.auth0_oidc import Auth0Identity
from app.db import SessionLocal, engine
from app.main import app
from app.models import RegistrationRequest, User
from app.registrations import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED
from app.schema import migrate_schema
from tests.test_app import register_active
from tests.test_auth0 import _assert_auth0_tenant_logout, _enable_auth0, _start_callback


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
    from sqlalchemy import text

    with engine.connect() as connection:
        index_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'ix_registration_requests_one_pending'")
        ).scalar()
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
    pending = _onboard(
        TestClient(app),
        "auth0|admin-target",
        "admin.target@example.com",
        "Alvo Admin",
        "alvo_admin",
    )
    assert pending.headers["location"] == "/auth/aguardando"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "admin.target@example.com"))
        item = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        request_id = item.id
        assert user.is_active is False
    finally:
        db.close()
    approve = http.post(f"/admin/cadastros/{request_id}/aprovar", follow_redirects=False)
    assert approve.status_code == 303
    assert approve.headers["location"].startswith("/")
    reject = http.post(f"/admin/cadastros/{request_id}/recusar", follow_redirects=False)
    assert reject.status_code == 303
    db = SessionLocal()
    try:
        item = db.get(RegistrationRequest, request_id)
        user = db.get(User, item.user_id)
        assert item.status == STATUS_PENDING
        assert user.is_active is False
    finally:
        db.close()


def test_pending_user_cannot_access_admin(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _onboard(http, "auth0|pend-admin", "pend.admin@example.com", "Pend Admin", "pend_admin")
    page = http.get("/admin", follow_redirects=False)
    assert page.status_code == 303
    assert "/login" in page.headers["location"]


def test_site_admin_sees_pending_and_not_legacy_or_active(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "site_admin_ok", "site.admin.ok@example.com")
    _grant_site_admin("site.admin.ok@example.com")
    home = admin.get("/")
    assert 'aria-label="Administração"' in home.text
    hub = admin.get("/admin")
    assert hub.status_code == 200
    assert "Cadastros" in hub.text
    register_active(TestClient(app), "legado_oculto", "legado.oculto@example.com")
    db = SessionLocal()
    try:
        legado = db.scalar(select(User).where(User.email == "legado.oculto@example.com"))
        legado.is_active = False
        db.commit()
    finally:
        db.close()
    linked = TestClient(app)
    register_active(linked, "auth0_ativo_cad", "auth0.ativo.cad@example.com")
    linked.post("/logout", follow_redirects=False)
    callback = _start_callback(
        linked,
        Auth0Identity(sub="auth0|ativo-cad", email="auth0.ativo.cad@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/"
    _onboard(TestClient(app), "auth0|azi-eq", "azi.eq@example.com", "Azi Eq", "azi_eq")
    listing = admin.get("/admin/cadastros")
    assert listing.status_code == 200
    assert "Azi Eq" in listing.text
    assert "@azi_eq" in listing.text
    assert "azi.eq@example.com" in listing.text
    assert "auth0|azi-eq" not in listing.text
    assert "password_hash" not in listing.text
    assert "legado.oculto@example.com" not in listing.text
    assert "auth0.ativo.cad@example.com" not in listing.text


def test_etapa3_backfill_is_idempotent(monkeypatch):
    _enable_auth0(monkeypatch)
    db = SessionLocal()
    try:
        user = User(
            name="Azi Backfill",
            username="azi_backfill",
            username_key="azi_backfill",
            email="azi.backfill@example.com",
            password_hash="",
            is_active=False,
            auth0_sub="auth0|azi-backfill",
            is_site_admin=False,
        )
        db.add(user)
        db.commit()
        user_id = user.id
        created_at = user.created_at
    finally:
        db.close()
    migrate_schema()
    migrate_schema()
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        assert user.name == "Azi Backfill"
        assert user.username_key == "azi_backfill"
        assert user.email == "azi.backfill@example.com"
        assert user.auth0_sub == "auth0|azi-backfill"
        assert user.is_active is False
        rows = list(db.scalars(select(RegistrationRequest).where(RegistrationRequest.user_id == user_id)))
        assert len(rows) == 1
        assert rows[0].status == STATUS_PENDING
        if created_at is not None:
            assert rows[0].created_at == created_at
        assert db.scalar(select(User).where(User.email == "azi.backfill@example.com")).id == user_id
    finally:
        db.close()


def test_approve_and_reject_require_admin_and_are_atomic(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "decider", "decider@example.com")
    _grant_site_admin("decider@example.com")
    other = TestClient(app)
    _onboard(other, "auth0|decide-1", "decide.one@example.com", "Decide Um", "decide_um")
    _onboard(TestClient(app), "auth0|decide-2", "decide.two@example.com", "Decide Dois", "decide_dois")
    db = SessionLocal()
    try:
        first_user = db.scalar(select(User).where(User.email == "decide.one@example.com"))
        second_user = db.scalar(select(User).where(User.email == "decide.two@example.com"))
        first = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == first_user.id))
        second = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == second_user.id))
        first_id = first.id
        second_id = second.id
        admin_id = db.scalar(select(User.id).where(User.email == "decider@example.com"))
    finally:
        db.close()
    detail = admin.get(f"/admin/cadastros/{first_id}")
    assert detail.status_code == 200
    assert "Decide Um" in detail.text
    assert "decide.one@example.com" in detail.text
    assert "Pendente" in detail.text
    assert "Aprovar" in detail.text
    assert "Recusar" in detail.text
    assert 'name="decision_note"' not in detail.text
    approved = admin.post(f"/admin/cadastros/{first_id}/aprovar", follow_redirects=False)
    assert approved.status_code == 303
    again = admin.post(f"/admin/cadastros/{first_id}/aprovar", follow_redirects=False)
    assert again.status_code == 303
    reject_approved = admin.post(f"/admin/cadastros/{first_id}/recusar", follow_redirects=False)
    assert reject_approved.status_code == 303
    db = SessionLocal()
    try:
        item = db.get(RegistrationRequest, first_id)
        user = db.get(User, item.user_id)
        assert item.status == STATUS_APPROVED
        assert user.is_active is True
        assert item.decided_by_user_id == admin_id
        assert item.decided_at is not None
        assert item.decision_note is None
    finally:
        db.close()
    authed = TestClient(app)
    callback = _start_callback(
        authed,
        Auth0Identity(sub="auth0|decide-1", email="decide.one@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/"
    landed = authed.get("/")
    assert 'aria-label="Configurações"' in landed.text
    assert "Aguardando aprovação" not in landed.text
    rejected = admin.post(f"/admin/cadastros/{second_id}/recusar", follow_redirects=False)
    assert rejected.status_code == 303
    again_reject = admin.post(f"/admin/cadastros/{second_id}/recusar", follow_redirects=False)
    assert again_reject.status_code == 303
    approve_rejected = admin.post(f"/admin/cadastros/{second_id}/aprovar", follow_redirects=False)
    assert approve_rejected.status_code == 303
    db = SessionLocal()
    try:
        item = db.get(RegistrationRequest, second_id)
        user = db.get(User, item.user_id)
        assert item.status == STATUS_REJECTED
        assert user.is_active is False
        assert item.decided_by_user_id == admin_id
    finally:
        db.close()
    refused = TestClient(app)
    callback = _start_callback(
        refused,
        Auth0Identity(sub="auth0|decide-2", email="decide.two@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/auth/nao-aprovado"
    page = refused.get("/auth/nao-aprovado")
    assert page.status_code == 200
    assert "Solicitação não aprovada" in page.text
    assert 'href="/auth/logout"' in page.text
    home = refused.get("/")
    assert 'aria-label="Configurações"' not in home.text
    onboard = refused.get("/auth/completar-perfil", follow_redirects=False)
    assert onboard.headers["location"] == "/auth/nao-aprovado"


def test_aguardando_refresh_after_approval_enters_home(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "refresh_admin", "refresh.admin@example.com")
    _grant_site_admin("refresh.admin@example.com")
    waiting = TestClient(app)
    _onboard(waiting, "auth0|refresh-1", "refresh.one@example.com", "Refresh One", "refresh_one")
    page = waiting.get("/auth/aguardando")
    assert "Aguardando aprovação" in page.text
    db = SessionLocal()
    try:
        item = db.scalar(
            select(RegistrationRequest).where(
                RegistrationRequest.user_id == select(User.id).where(User.email == "refresh.one@example.com").scalar_subquery()
            )
        )
        request_id = item.id
    finally:
        db.close()
    admin.post(f"/admin/cadastros/{request_id}/aprovar", follow_redirects=False)
    refreshed = waiting.get("/auth/aguardando", follow_redirects=False)
    assert refreshed.status_code == 303
    assert refreshed.headers["location"] == "/"
    home = waiting.get("/")
    assert 'aria-label="Configurações"' in home.text


def test_onboarding_creates_user_and_request_together(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    created = _onboard(http, "auth0|txn-1", "txn.one@example.com", "Txn One", "txn_one")
    assert created.headers["location"] == "/auth/aguardando"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.auth0_sub == "auth0|txn-1"))
        requests = list(db.scalars(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id)))
        assert user.is_active is False
        assert len(requests) == 1
        assert requests[0].status == STATUS_PENDING
    finally:
        db.close()
    left = http.get("/auth/logout", follow_redirects=False)
    _assert_auth0_tenant_logout(left)


def test_approval_sends_email_after_commit(monkeypatch):
    _enable_auth0(monkeypatch)
    monkeypatch.setattr("app.mail.APP_BASE_URL", "https://watch.example")
    admin = TestClient(app)
    register_active(admin, "mail_admin", "mail.admin@example.com")
    _grant_site_admin("mail.admin@example.com")
    _onboard(TestClient(app), "auth0|mail-ok", "mail.ok@example.com", "Mail Ok", "mail_ok")
    sent = []

    def capture(to_email, subject, body):
        sent.append((to_email, subject, body))

    monkeypatch.setattr("app.mail._send_email", capture)
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "mail.ok@example.com"))
        item = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        request_id = item.id
    finally:
        db.close()
    approved = admin.post(f"/admin/cadastros/{request_id}/aprovar", follow_redirects=False)
    assert approved.status_code == 303
    assert len(sent) == 1
    assert sent[0][0] == "mail.ok@example.com"
    assert sent[0][1] == "Seu acesso ao Watch Club foi aprovado"
    assert "Mail Ok" in sent[0][2]
    assert "https://watch.example/auth/login" in sent[0][2]
    admin.post(f"/admin/cadastros/{request_id}/aprovar", follow_redirects=False)
    assert len(sent) == 1
    db = SessionLocal()
    try:
        item = db.get(RegistrationRequest, request_id)
        user = db.get(User, item.user_id)
        assert item.status == STATUS_APPROVED
        assert user.is_active is True
    finally:
        db.close()


def test_rejection_sends_email_after_commit_without_review_link(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "mail_rej_admin", "mail.rej.admin@example.com")
    _grant_site_admin("mail.rej.admin@example.com")
    _onboard(TestClient(app), "auth0|mail-no", "mail.no@example.com", "Mail No", "mail_no")
    sent = []
    monkeypatch.setattr("app.mail._send_email", lambda *args: sent.append(args))
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "mail.no@example.com"))
        item = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        request_id = item.id
    finally:
        db.close()
    rejected = admin.post(f"/admin/cadastros/{request_id}/recusar", follow_redirects=False)
    assert rejected.status_code == 303
    assert len(sent) == 1
    assert sent[0][0] == "mail.no@example.com"
    assert sent[0][1] == "Sobre sua solicitação de acesso ao Watch Club"
    assert "Mail No" in sent[0][2]
    assert "não foi aprovada neste momento" in sent[0][2]
    assert "/auth/login" not in sent[0][2]
    admin.post(f"/admin/cadastros/{request_id}/recusar", follow_redirects=False)
    assert len(sent) == 1


def test_mail_failure_after_approve_keeps_decision(monkeypatch):
    from app.mail import MailDeliveryError

    _enable_auth0(monkeypatch)
    monkeypatch.setattr(
        "app.registrations.send_registration_approved_email",
        lambda *args, **kwargs: (_ for _ in ()).throw(MailDeliveryError("smtp")),
    )
    admin = TestClient(app)
    register_active(admin, "mail_fail_admin", "mail.fail.admin@example.com")
    _grant_site_admin("mail.fail.admin@example.com")
    _onboard(TestClient(app), "auth0|mail-fail", "mail.fail.user@example.com", "Mail Fail", "mail_fail_user")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "mail.fail.user@example.com"))
        item = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        request_id = item.id
        user_id = user.id
    finally:
        db.close()
    approved = admin.post(f"/admin/cadastros/{request_id}/aprovar", follow_redirects=False)
    assert approved.status_code == 303
    db = SessionLocal()
    try:
        item = db.get(RegistrationRequest, request_id)
        user = db.get(User, user_id)
        assert item.status == STATUS_APPROVED
        assert user.is_active is True
    finally:
        db.close()


def test_unauthorized_approve_does_not_send_email(monkeypatch):
    _enable_auth0(monkeypatch)
    common = TestClient(app)
    register_active(common, "mail_noadmin", "mail.noadmin@example.com")
    _onboard(TestClient(app), "auth0|mail-skip", "mail.skip@example.com", "Mail Skip", "mail_skip")
    sent = []
    monkeypatch.setattr("app.mail._send_email", lambda *args: sent.append(args))
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "mail.skip@example.com"))
        item = db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id))
        request_id = item.id
    finally:
        db.close()
    common.post(f"/admin/cadastros/{request_id}/aprovar", follow_redirects=False)
    assert sent == []


def test_legacy_login_still_works_with_admin_schema(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "legado_ok", "legado.ok@example.com")
    http.post("/logout", follow_redirects=False)
    login = http.post(
        "/login",
        data={"email": "legado.ok@example.com", "password": "segredo"},
        follow_redirects=False,
    )
    assert login.headers["location"] == "/"
    assert http.get("/register").status_code == 200
    google = http.get("/auth/google", follow_redirects=False)
    assert google.status_code == 303
