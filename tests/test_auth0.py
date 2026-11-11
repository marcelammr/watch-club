from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.accounts import create_user, suggested_auth0_name, suggested_auth0_username
from app.auth0_oidc import Auth0Identity, identity_from_claims, merge_pending_payload
from app.db import SessionLocal, engine
from app.main import app
from app.models import Club, Notification, RegistrationRequest, User
from app.notifications import TYPE_REGISTRATION_REQUEST, unread_count
from app.schema import migrate_schema
from tests.test_app import register_active


def _enable_auth0(monkeypatch):
    monkeypatch.setattr("app.config.AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setattr("app.config.AUTH0_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.config.AUTH0_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr("app.config.APP_BASE_URL", "http://127.0.0.1:8000")


def test_auth0_sub_column_and_unique_index():
    inspector = inspect(engine)
    user_cols = {column["name"] for column in inspector.get_columns("users")}
    assert "auth0_sub" in user_cols
    assert "google_id" in user_cols
    assert "facebook_id" in user_cols
    auth0_indexes = [
        index
        for index in inspector.get_indexes("users")
        if "auth0_sub" in (index.get("column_names") or [])
    ]
    assert auth0_indexes
    assert any(index.get("unique") for index in auth0_indexes)


def test_identity_from_claims_reads_sub_email_and_verified():
    identity = identity_from_claims(
        {
            "sub": "auth0|abc123",
            "email": "Person@Example.COM",
            "email_verified": True,
        }
    )
    assert identity.sub == "auth0|abc123"
    assert identity.email == "person@example.com"
    assert identity.email_verified is True
    pending = identity.pending_payload()
    assert pending["email_verified"] is True
    assert pending["name"] == ""
    assert pending["nickname"] == ""
    assert "access_token" not in pending
    named = identity_from_claims(
        {
            "sub": "auth0|named",
            "email": "named@example.com",
            "email_verified": True,
            "name": "  Luna  Teste  ",
            "nickname": "luna_auth",
        }
    )
    assert named.name == "Luna Teste"
    assert named.nickname == "luna_auth"
    assert named.pending_payload()["name"] == "Luna Teste"
    ignored = identity_from_claims(
        {"sub": "auth0|mail-name", "email": "a@b.c", "name": "a@b.c", "nickname": 123}
    )
    assert ignored.name is None
    assert ignored.nickname is None
    assert identity_from_claims({"sub": "auth0|x", "email": "a@b.c"}).email_verified is False
    assert identity_from_claims({"sub": "auth0|x", "email": "a@b.c", "email_verified": None}).email_verified is False
    assert identity_from_claims({"sub": "auth0|x", "email": "a@b.c", "email_verified": "true"}).email_verified is False
    assert identity_from_claims({"sub": "auth0|x", "email": "a@b.c", "email_verified": False}).email_verified is False


def test_auth0_login_requires_config():
    page = TestClient(app).get("/auth/login", follow_redirects=False)
    assert page.status_code == 303
    assert "/login" in page.headers["location"]


def test_auth0_login_redirects_to_authorize(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    started = http.get("/auth/login", follow_redirects=False)
    assert started.status_code == 303
    location = started.headers["location"]
    parsed = urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "tenant.example.auth0.com"
    assert parsed.path == "/authorize"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/callback"]
    assert query["response_type"] == ["code"]
    assert "openid" in query["scope"][0]
    assert "email" in query["scope"][0]
    assert query["connection"] == ["Username-Password-Authentication"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"]
    assert query["nonce"]
    assert query["code_challenge"]
    assert "screen_hint" not in query
    assert "client_secret" not in location


def test_auth0_signup_redirects_with_screen_hint(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    started = http.get("/auth/signup", follow_redirects=False)
    assert started.status_code == 303
    location = started.headers["location"]
    query = parse_qs(urlparse(location).query)
    assert query["screen_hint"] == ["signup"]
    assert query["connection"] == ["Username-Password-Authentication"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"]
    assert query["nonce"]
    assert query["code_challenge"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/callback"]
    assert "client_secret" not in location


def test_auth0_signup_unlinked_callback_does_not_create_user(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    before = SessionLocal()
    try:
        count_before = len(list(before.scalars(select(User))))
    finally:
        before.close()
    started = http.get("/auth/signup", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    identity = Auth0Identity(
        sub="auth0|signup-unlinked",
        email="new.signup@example.com",
        email_verified=True,
    )
    with patch("app.main.redeem_callback", return_value=identity):
        callback = http.get(f"/callback?code=fake&state={state}", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/auth/completar-perfil"
    pending = http.get("/auth/completar-perfil")
    assert pending.status_code == 200
    assert "Complete seu perfil" in pending.text
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User)))
        assert len(users) == count_before
        assert db.scalar(select(User).where(User.email == "new.signup@example.com")) is None
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|signup-unlinked")) is None
    finally:
        db.close()


def _assert_auth0_authorize(response, *, signup=False):
    assert response.status_code == 303
    parsed = urlparse(response.headers["location"])
    assert parsed.scheme == "https"
    assert parsed.netloc == "tenant.example.auth0.com"
    assert parsed.path == "/authorize"
    query = parse_qs(parsed.query)
    if signup:
        assert query.get("screen_hint") == ["signup"]
    else:
        assert "screen_hint" not in query
    assert "client_secret" not in response.headers["location"]


def test_legacy_auth_routes_still_exist():
    http = TestClient(app)
    assert http.get("/login").status_code == 200
    assert http.get("/register").status_code == 200
    assert http.get("/recuperar-senha").status_code == 200
    google = http.get("/auth/google", follow_redirects=False)
    assert google.status_code == 303


def test_legacy_public_auth_redirects_to_auth0_when_configured(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _assert_auth0_authorize(http.get("/login", follow_redirects=False))
    login_page = http.get("/login", follow_redirects=False)
    assert "E-mail ou senha" not in (login_page.text or "")
    assert 'name="password"' not in (login_page.text or "")
    _assert_auth0_authorize(http.get("/register", follow_redirects=False), signup=True)
    register_page = http.get("/register", follow_redirects=False)
    assert "Cadastre-se" not in (register_page.text or "")
    _assert_auth0_authorize(
        http.post(
            "/login",
            data={"email": "bypass@example.com", "password": "segredo"},
            follow_redirects=False,
        )
    )
    created = http.post(
        "/register",
        data={
            "name": "Bypass Auth",
            "username": "bypass_auth0",
            "email": "bypass.auth0@example.com",
            "password": "segredo",
        },
        follow_redirects=False,
    )
    _assert_auth0_authorize(created, signup=True)
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.email == "bypass.auth0@example.com")) is None
        assert db.scalar(select(User).where(User.username_key == "bypass_auth0")) is None
    finally:
        db.close()
    _assert_auth0_authorize(http.get("/auth/google", follow_redirects=False))
    _assert_auth0_authorize(http.get("/auth/facebook", follow_redirects=False))
    google_cb = http.get("/auth/google/callback?code=fake&state=x", follow_redirects=False)
    _assert_auth0_authorize(google_cb)
    facebook_cb = http.get("/auth/facebook/callback?code=fake&state=x", follow_redirects=False)
    _assert_auth0_authorize(facebook_cb)
    _assert_auth0_authorize(http.get("/recuperar-senha", follow_redirects=False))
    reset = http.post(
        "/recuperar-senha/codigo",
        data={"code": "000000", "new_password": "nova", "confirm_password": "nova"},
        follow_redirects=False,
    )
    _assert_auth0_authorize(reset)
    started = http.get("/auth/login", follow_redirects=False)
    _assert_auth0_authorize(started)
    signup = http.get("/auth/signup", follow_redirects=False)
    _assert_auth0_authorize(signup, signup=True)


def test_legacy_oauth_callback_does_not_create_user_when_auth0_configured(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    profile = {
        "provider": "google",
        "provider_id": "google-bypass-1",
        "email": "google.bypass@example.com",
        "name": "Google Bypass",
    }
    with patch("app.main.fetch_google_profile", return_value=profile):
        with patch("app.main.login_or_create_oauth") as create:
            response = http.get(
                "/auth/google/callback?code=fake&state=oauth-state",
                follow_redirects=False,
            )
    _assert_auth0_authorize(response)
    create.assert_not_called()
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.email == "google.bypass@example.com")) is None
    finally:
        db.close()


def test_auth0_callback_rejects_bad_state(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    http.get("/auth/login", follow_redirects=False)
    failed = http.get("/callback?code=abc&state=errado", follow_redirects=False)
    assert failed.status_code == 303
    assert "/login" in failed.headers["location"]


def _start_callback(http: TestClient, identity: Auth0Identity):
    started = http.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    with patch("app.main.redeem_callback", return_value=identity):
        return http.get(f"/callback?code=fake&state={state}", follow_redirects=False)


def test_auth0_verified_email_links_existing_user_same_id(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_mail", "auth0.mail@example.com")
    created = http.post("/clubs", data={"name": "Clube Vínculo"}, follow_redirects=False)
    assert created.status_code == 303
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "auth0.mail@example.com"))
        club = db.scalar(select(Club).where(Club.name == "Clube Vínculo"))
        user_id = user.id
        club_id = club.id
        password_hash = user.password_hash
        user.google_id = "google-auth0-mail-keep"
        user.facebook_id = "facebook-auth0-mail-keep"
        db.commit()
        user_count = len(list(db.scalars(select(User))))
    finally:
        db.close()
    http.post("/logout", follow_redirects=False)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|link-1", email="  Auth0.Mail@Example.COM ", email_verified=True),
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/"
    home = http.get("/")
    assert 'aria-label="Configurações"' in home.text
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).where(User.email == "auth0.mail@example.com")))
        assert len(users) == 1
        user = users[0]
        assert user.id == user_id
        assert user.auth0_sub == "auth0|link-1"
        assert user.password_hash == password_hash
        assert user.google_id == "google-auth0-mail-keep"
        assert user.facebook_id == "facebook-auth0-mail-keep"
        assert len(list(db.scalars(select(User)))) == user_count
        club = db.get(Club, club_id)
        assert club.owner_id == user_id
    finally:
        db.close()


def test_auth0_unverified_email_does_not_link(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_unv", "auth0.unv@example.com")
    http.post("/logout", follow_redirects=False)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|unverified-1", email="auth0.unv@example.com", email_verified=False),
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/auth/verificar-email"
    profile = http.get("/auth/completar-perfil", follow_redirects=False)
    assert profile.headers["location"] == "/auth/verificar-email"
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "auth0.unv@example.com"))
        assert user.auth0_sub is None
    finally:
        db.close()


def test_auth0_missing_email_verified_does_not_link(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_none", "auth0.none@example.com")
    http.post("/logout", follow_redirects=False)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|none-1", email="auth0.none@example.com", email_verified=False),
    )
    identity = identity_from_claims({"sub": "auth0|none-1", "email": "auth0.none@example.com"})
    assert identity.email_verified is False
    assert callback.headers["location"] == "/auth/verificar-email"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "auth0.none@example.com"))
        assert user.auth0_sub is None
    finally:
        db.close()


def test_auth0_email_already_bound_to_other_sub_is_not_overwritten(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_taken", "auth0.taken@example.com")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "auth0.taken@example.com"))
        user.auth0_sub = "auth0|already-1"
        db.commit()
    finally:
        db.close()
    http.post("/logout", follow_redirects=False)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|intruder-1", email="auth0.taken@example.com", email_verified=True),
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/auth/completar-perfil"
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "auth0.taken@example.com"))
        assert user.auth0_sub == "auth0|already-1"
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|intruder-1")) is None
    finally:
        db.close()


def test_auth0_sub_already_on_other_user_is_not_reassigned(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    other = TestClient(app)
    register_active(http, "auth0_owner", "auth0.owner@example.com")
    register_active(other, "auth0_guest", "auth0.guest@example.com")
    db = SessionLocal()
    try:
        owner = db.scalar(select(User).where(User.email == "auth0.owner@example.com"))
        guest = db.scalar(select(User).where(User.email == "auth0.guest@example.com"))
        owner.auth0_sub = "auth0|owned-1"
        owner_id = owner.id
        guest_id = guest.id
        db.commit()
    finally:
        db.close()
    http.post("/logout", follow_redirects=False)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|owned-1", email="auth0.guest@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/"
    db = SessionLocal()
    try:
        owner = db.get(User, owner_id)
        guest = db.get(User, guest_id)
        assert owner.auth0_sub == "auth0|owned-1"
        assert guest.auth0_sub is None
    finally:
        db.close()


def test_auth0_integrity_error_on_link_does_not_bind_wrong_user(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    other = TestClient(app)
    register_active(http, "auth0_race_a", "auth0.race.a@example.com")
    register_active(other, "auth0_race_b", "auth0.race.b@example.com")
    db = SessionLocal()
    try:
        owner = db.scalar(select(User).where(User.email == "auth0.race.a@example.com"))
        guest = db.scalar(select(User).where(User.email == "auth0.race.b@example.com"))
        owner.auth0_sub = "auth0|race-1"
        owner_id = owner.id
        guest_id = guest.id
        db.commit()
    finally:
        db.close()
    http.post("/logout", follow_redirects=False)

    from app import accounts as accounts_mod

    real_find = accounts_mod.find_user_by_auth0_sub
    calls = {"n": 0}

    def find_skip_first(db, sub):
        calls["n"] += 1
        if calls["n"] <= 2:
            return None
        return real_find(db, sub)

    monkeypatch.setattr(accounts_mod, "find_user_by_auth0_sub", find_skip_first)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|race-1", email="auth0.race.b@example.com", email_verified=True),
    )
    assert callback.status_code == 303
    db = SessionLocal()
    try:
        owner = db.get(User, owner_id)
        guest = db.get(User, guest_id)
        assert owner.auth0_sub == "auth0|race-1"
        assert guest.auth0_sub is None
    finally:
        db.close()
    assert callback.headers["location"] == "/"
    settings = http.get("/conta")
    assert "auth0_race_a" in settings.text or "auth0.race.a@example.com" in settings.text


def test_auth0_callback_linked_sub_logs_in_without_email_match(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    other = TestClient(app)
    register_active(http, "auth0_linked", "auth0.linked@example.com")
    register_active(other, "auth0_other", "auth0.other@example.com")
    db = SessionLocal()
    try:
        linked = db.scalar(select(User).where(User.email == "auth0.linked@example.com"))
        stranger = db.scalar(select(User).where(User.email == "auth0.other@example.com"))
        linked.auth0_sub = "auth0|linked-1"
        linked_id = linked.id
        stranger_id = stranger.id
        db.commit()
    finally:
        db.close()
    http.post("/logout", follow_redirects=False)
    started = http.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    identity = Auth0Identity(
        sub="auth0|linked-1",
        email="auth0.other@example.com",
        email_verified=True,
    )
    with patch("app.main.redeem_callback", return_value=identity):
        callback = http.get(f"/callback?code=fake&state={state}", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/"
    home = http.get("/")
    assert home.status_code == 200
    assert 'aria-label="Configurações"' in home.text
    db = SessionLocal()
    try:
        linked = db.get(User, linked_id)
        stranger = db.get(User, stranger_id)
        assert linked.auth0_sub == "auth0|linked-1"
        assert stranger.auth0_sub is None
        assert stranger.email == "auth0.other@example.com"
    finally:
        db.close()


def test_google_facebook_login_routes_still_work():
    page = TestClient(app).get("/login")
    assert "Continuar com Gmail" in page.text
    assert "Continuar com Facebook" in page.text
    google = TestClient(app).get("/auth/google", follow_redirects=False)
    assert google.status_code == 303
    assert "/login" in google.headers["location"]


def _assert_auth0_tenant_logout(response):
    assert response.status_code == 303
    parsed = urlparse(response.headers["location"])
    assert parsed.scheme == "https"
    assert parsed.netloc == "tenant.example.auth0.com"
    assert parsed.path == "/v2/logout"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["test-client-id"]
    assert query["returnTo"] == ["http://127.0.0.1:8000/"]
    assert "client_secret" not in response.headers["location"]


def test_auth0_logout_redirects_to_tenant(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_out", "auth0.out@example.com")
    left = http.get("/auth/logout", follow_redirects=False)
    _assert_auth0_tenant_logout(left)
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text


def test_auth0_login_marks_session_and_sair_uses_auth0_logout(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_flag", "auth0.flag@example.com")
    http.post("/logout", follow_redirects=False)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|flag-1", email="auth0.flag@example.com", email_verified=True),
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/"
    home = http.get("/")
    assert 'aria-label="Configurações"' in home.text
    assert 'action="/logout"' in home.text
    left = http.post("/logout", follow_redirects=False)
    _assert_auth0_tenant_logout(left)
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "auth0.flag@example.com"))
        assert user.presence == "offline"
        assert user.last_seen is not None
        assert user.auth0_sub == "auth0|flag-1"
    finally:
        db.close()
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text
    pending = http.get("/auth/pendente", follow_redirects=False)
    assert pending.status_code == 303
    assert "/login" in pending.headers["location"]


def test_legacy_logout_stays_local_even_with_auth0_sub(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_legacy", "auth0.legacy@example.com")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "auth0.legacy@example.com"))
        user.auth0_sub = "auth0|legacy-session-1"
        db.commit()
    finally:
        db.close()
    left = http.post("/logout", follow_redirects=False)
    assert left.status_code == 303
    assert left.headers["location"] == "/"
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text
    login = http.post(
        "/login",
        data={"email": "auth0.legacy@example.com", "password": "segredo"},
        follow_redirects=False,
    )
    _assert_auth0_authorize(login)
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text


def test_dual_credential_user_logout_follows_current_session(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_dual", "auth0.dual@example.com")
    http.post("/logout", follow_redirects=False)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|dual-1", email="auth0.dual@example.com", email_verified=True),
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/"
    auth0_left = http.post("/logout", follow_redirects=False)
    _assert_auth0_tenant_logout(auth0_left)
    login = http.post(
        "/login",
        data={"email": "auth0.dual@example.com", "password": "segredo"},
        follow_redirects=False,
    )
    _assert_auth0_authorize(login)


def test_auth0_pending_can_abandon_identity_via_auth0_logout(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|pending-out", email="auth0.pending.out@example.com", email_verified=False),
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/auth/completar-perfil"
    pending = http.get("/auth/completar-perfil")
    assert pending.status_code == 200
    assert 'href="/auth/logout"' in pending.text
    left = http.get("/auth/logout", follow_redirects=False)
    _assert_auth0_tenant_logout(left)
    gone = http.get("/auth/pendente", follow_redirects=False)
    assert gone.status_code == 303
    assert "/login" in gone.headers["location"]
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|pending-out")) is None
    finally:
        db.close()


def _onboard_identity(**kwargs):
    data = {
        "sub": "auth0|new-1",
        "email": "auth0.new@example.com",
        "email_verified": True,
        "name": "Luna Nova",
        "nickname": "lunanova",
    }
    data.update(kwargs)
    return Auth0Identity(**data)


def test_auth0_verified_new_identity_opens_complete_profile(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    callback = _start_callback(http, _onboard_identity())
    assert callback.status_code == 303
    assert callback.headers["location"] == "/auth/completar-perfil"
    page = http.get("/auth/completar-perfil")
    assert page.status_code == 200
    assert "Complete seu perfil" in page.text
    assert "Conta" in page.text
    assert "Perfil" in page.text
    assert "Verificação" in page.text
    assert "Aprovação" not in page.text
    assert "Escolha como você aparece no Watch Club." in page.text
    assert "Continuar" in page.text
    assert 'name="name"' in page.text
    assert 'name="username"' in page.text
    assert "Luna Nova" in page.text
    assert "luna_nova" in page.text
    assert "auth0.new@example.com" in page.text
    assert 'name="email"' not in page.text
    assert 'name="sub"' not in page.text
    assert 'href="/auth/logout"' in page.text
    assert "Criar conta" not in page.text.split("<h1>", 1)[-1].split("</form>", 1)[0]
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|new-1")) is None
    finally:
        db.close()


def test_auth0_unverified_cannot_create_user_via_onboarding(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|unv-create", email="auth0.unv.create@example.com", email_verified=False),
    )
    assert callback.headers["location"] == "/auth/completar-perfil"
    created = http.post(
        "/auth/completar-perfil",
        data={"name": "Não Deve", "username": "nao_deve", "email": "hack@example.com", "sub": "auth0|hack"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/auth/verificar-email"
    verify = http.get("/auth/verificar-email")
    assert verify.status_code == 200
    assert "Conta" in verify.text
    assert "Perfil" in verify.text
    assert "Verificação" in verify.text
    assert "Aprovação" not in verify.text
    assert "Aguardando aprovação" not in verify.text
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|unv-create")) is None
        assert db.scalar(select(User).where(User.email == "auth0.unv.create@example.com")) is None
    finally:
        db.close()


def test_auth0_onboarding_name_can_repeat_username_cannot(monkeypatch):
    _enable_auth0(monkeypatch)
    register_active(TestClient(app), "nome_igual", "auth0.nome.igual@example.com", name="Nome Compartilhado")
    http = TestClient(app)
    _start_callback(http, _onboard_identity(sub="auth0|repeat-name", email="auth0.repeat@example.com"))
    page = http.get("/auth/completar-perfil")
    assert "Complete seu perfil" in page.text
    taken = http.post(
        "/auth/completar-perfil",
        data={"name": "Nome Compartilhado", "username": "nome_igual"},
        follow_redirects=False,
    )
    assert taken.status_code == 400
    assert "já está em uso" in taken.text
    created = http.post(
        "/auth/completar-perfil",
        data={"name": "Nome Compartilhado", "username": "auth0_repeat"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/"
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).where(User.name == "Nome Compartilhado")))
        assert len(users) == 2
        newbie = db.scalar(select(User).where(User.auth0_sub == "auth0|repeat-name"))
        assert newbie.username_key == "auth0_repeat"
        assert newbie.is_active is True
    finally:
        db.close()


def test_auth0_username_suggestion_uses_available_variation(monkeypatch):
    _enable_auth0(monkeypatch)
    register_active(TestClient(app), "lunanova", "auth0.luna.taken@example.com")
    db = SessionLocal()
    try:
        suggested = suggested_auth0_username(db, "lunanova")
    finally:
        db.close()
    assert suggested != "lunanova"
    assert suggested.startswith("lunanova")
    http = TestClient(app)
    _start_callback(
        http,
        _onboard_identity(
            sub="auth0|suggest-1",
            email="auth0.suggest@example.com",
            name=None,
            nickname="lunanova",
        ),
    )
    page = http.get("/auth/completar-perfil")
    assert f'value="{suggested}"' in page.text or suggested in page.text
    assert suggested_auth0_name(email="pessoa.nova@example.com") == "pessoa nova"
    assert suggested_auth0_name(email="x@y.com", name="Maria Clara") == "Maria Clara"


def test_auth0_complete_profile_creates_one_active_user(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(
        http,
        _onboard_identity(sub="auth0|create-1", email="auth0.create@example.com", name="Ana Auth"),
    )
    forged = http.post(
        "/auth/completar-perfil",
        data={
            "name": "Ana Auth",
            "username": "ana_auth",
            "email": "forged@example.com",
            "sub": "auth0|forged",
            "email_verified": "true",
            "password": "nao-usar",
        },
        follow_redirects=False,
    )
    assert forged.status_code == 303
    assert forged.headers["location"] == "/"
    home = http.get("/")
    assert "Ana Auth" in home.text or 'aria-label="Configurações"' in home.text
    conta = http.get("/conta", follow_redirects=False)
    assert conta.status_code == 200
    clubes = http.get("/clubes", follow_redirects=False)
    assert clubes.status_code == 200
    again = http.get("/auth/completar-perfil", follow_redirects=False)
    assert again.status_code == 303
    assert again.headers["location"] == "/"
    waiting = http.get("/auth/aguardando", follow_redirects=False)
    assert waiting.status_code == 303
    assert waiting.headers["location"] == "/"
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).where(User.auth0_sub == "auth0|create-1")))
        assert len(users) == 1
        user = users[0]
        assert user.email == "auth0.create@example.com"
        assert user.name == "Ana Auth"
        assert user.username_key == "ana_auth"
        assert user.password_hash == ""
        assert user.is_active is True
        assert user.is_site_admin is False
        assert user.username_changed_at is None
        requests = list(db.scalars(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id)))
        assert requests == []
    finally:
        db.close()
    migrate_schema()
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.auth0_sub == "auth0|create-1"))
        assert user.username_changed_at is None
    finally:
        db.close()
    duplicate = http.post(
        "/auth/completar-perfil",
        data={"name": "Ana Auth", "username": "ana_auth_2"},
        follow_redirects=False,
    )
    assert duplicate.status_code == 303
    assert duplicate.headers["location"] == "/"
    db = SessionLocal()
    try:
        assert len(list(db.scalars(select(User).where(User.email == "auth0.create@example.com")))) == 1
        assert len(list(db.scalars(select(User).where(User.auth0_sub == "auth0|create-1")))) == 1
    finally:
        db.close()


def test_auth0_relogin_same_sub_goes_home(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(http, _onboard_identity(sub="auth0|relogin-1", email="auth0.relogin@example.com"))
    http.post("/auth/completar-perfil", data={"name": "Relogin", "username": "auth0_relogin"}, follow_redirects=False)
    left = http.get("/auth/logout", follow_redirects=False)
    _assert_auth0_tenant_logout(left)
    callback = _start_callback(http, _onboard_identity(sub="auth0|relogin-1", email="auth0.relogin@example.com"))
    assert callback.headers["location"] == "/"
    home = http.get("/")
    assert home.status_code == 200
    assert 'aria-label="Configurações"' in home.text
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).where(User.auth0_sub == "auth0|relogin-1")))
        assert len(users) == 1
        assert users[0].is_active is True
    finally:
        db.close()


def test_auth0_onboarding_logout_ends_auth0_session(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(http, _onboard_identity(sub="auth0|onboard-out", email="auth0.onboard.out@example.com"))
    page = http.get("/auth/completar-perfil")
    assert 'href="/auth/logout"' in page.text
    left = http.get("/auth/logout", follow_redirects=False)
    _assert_auth0_tenant_logout(left)
    gone = http.get("/auth/completar-perfil", follow_redirects=False)
    assert gone.status_code == 303
    assert "/login" in gone.headers["location"]


def test_auth0_onboard_integrity_error_does_not_duplicate(monkeypatch):
    _enable_auth0(monkeypatch)
    register_active(TestClient(app), "auth0_race_nick", "auth0.race.nick@example.com")
    http = TestClient(app)
    _start_callback(http, _onboard_identity(sub="auth0|int-1", email="auth0.int@example.com"))
    monkeypatch.setattr("app.accounts.username_taken", lambda *args, **kwargs: False)

    def boom(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("users.username_key"))

    monkeypatch.setattr("app.accounts.create_auth0_user", boom)
    failed = http.post(
        "/auth/completar-perfil",
        data={"name": "Corrida", "username": "auth0_race_nick"},
        follow_redirects=False,
    )
    assert failed.status_code == 400
    assert "já está em uso" in failed.text or "Não foi possível" in failed.text
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|int-1")) is None
        assert len(list(db.scalars(select(User).where(User.username_key == "auth0_race_nick")))) == 1
    finally:
        db.close()


def test_auth0_onboard_does_not_duplicate_existing_email(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(http, _onboard_identity(sub="auth0|keep-mail", email="auth0.keep.mail@example.com"))
    page = http.get("/auth/completar-perfil")
    assert page.status_code == 200
    register_active(TestClient(app), "auth0_mail_keep", "auth0.keep.mail@example.com")
    created = http.post(
        "/auth/completar-perfil",
        data={"name": "Outra Pessoa", "username": "outra_pessoa_auth0"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/"
    home = http.get("/")
    assert 'aria-label="Configurações"' in home.text
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).where(User.email == "auth0.keep.mail@example.com")))
        assert len(users) == 1
        assert users[0].auth0_sub == "auth0|keep-mail"
        assert users[0].is_active is True
        assert users[0].username_key == "auth0_mail_keep"
        assert db.scalar(select(User).where(User.username_key == "outra_pessoa_auth0")) is None
    finally:
        db.close()


def test_legacy_inactive_user_is_not_treated_as_auth0_awaiting(monkeypatch):
    _enable_auth0(monkeypatch)
    db = SessionLocal()
    try:
        create_user(
            db,
            "legado_inativo",
            "legado.inativo@example.com",
            "segredo",
            name="Legado Inativo",
        )
        db.commit()
    finally:
        db.close()
    other = TestClient(app)
    callback = _start_callback(
        other,
        Auth0Identity(sub="auth0|legado-inativo", email="legado.inativo@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/auth/completar-perfil"
    posted = other.post(
        "/auth/completar-perfil",
        data={"name": "Legado Inativo", "username": "legado_inativo_auth"},
        follow_redirects=False,
    )
    assert posted.status_code == 400
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "legado.inativo@example.com"))
        assert user.auth0_sub is None
        assert user.is_active is False
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|legado-inativo")) is None
    finally:
        db.close()


def test_migrate_schema_backfills_legacy_username_changed_at_only():
    register_active(TestClient(app), "auth0_bf_legacy", "auth0.bf.legacy@example.com")
    db = SessionLocal()
    try:
        legacy = db.scalar(select(User).where(User.email == "auth0.bf.legacy@example.com"))
        legacy.username_changed_at = None
        legacy.auth0_sub = None
        auth0_user = User(
            name="Auth0 Null",
            username="auth0_null_cd",
            username_key="auth0_null_cd",
            email="auth0.null.cd@example.com",
            password_hash="",
            is_active=False,
            auth0_sub="auth0|null-cd",
            username_changed_at=None,
        )
        db.add(auth0_user)
        db.commit()
        legacy_id = legacy.id
        auth0_id = auth0_user.id
    finally:
        db.close()
    migrate_schema()
    db = SessionLocal()
    try:
        legacy = db.get(User, legacy_id)
        auth0_user = db.get(User, auth0_id)
        assert legacy.username_changed_at is not None
        assert auth0_user.username_changed_at is None
    finally:
        db.close()


def _grant_site_admin(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        user.is_site_admin = True
        db.commit()
    finally:
        db.close()


def test_merge_pending_payload_keeps_draft_only_for_same_sub():
    first = Auth0Identity(sub="auth0|same", email="a@example.com", email_verified=False)
    payload = merge_pending_payload(None, first)
    payload["profile_name"] = "Azi"
    payload["profile_username"] = "azi_crow"
    same = merge_pending_payload(
        payload,
        Auth0Identity(sub="auth0|same", email="a@example.com", email_verified=True),
    )
    assert same["profile_name"] == "Azi"
    assert same["profile_username"] == "azi_crow"
    assert same["email_verified"] is True
    other = merge_pending_payload(
        payload,
        Auth0Identity(sub="auth0|other", email="b@example.com", email_verified=False),
    )
    assert other["profile_name"] == ""
    assert other["profile_username"] == ""
    assert other["sub"] == "auth0|other"


def test_unverified_new_identity_opens_profile_without_creating_user(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|journey-1", email="journey.one@example.com", email_verified=False, name="Azi"),
    )
    assert callback.headers["location"] == "/auth/completar-perfil"
    page = http.get("/auth/completar-perfil")
    assert page.status_code == 200
    assert "Complete seu perfil" in page.text
    assert "journey.one@example.com" in page.text
    assert "Conta" in page.text and "Perfil" in page.text
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|journey-1")) is None
        assert db.scalar(select(User).where(User.email == "journey.one@example.com")) is None
    finally:
        db.close()


def test_unverified_profile_draft_goes_to_verification_without_user_or_notice(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "journey_admin", "journey.admin@example.com")
    _grant_site_admin("journey.admin@example.com")
    http = TestClient(app)
    _start_callback(
        http,
        Auth0Identity(sub="auth0|journey-2", email="journey.two@example.com", email_verified=False),
    )
    saved = http.post(
        "/auth/completar-perfil",
        data={"name": "Azi", "username": "azi_flow"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/auth/verificar-email"
    page = http.get("/auth/verificar-email")
    assert page.status_code == 200
    assert "Verifique seu e-mail" in page.text
    assert "journey.two@example.com" in page.text
    assert "Confira a pasta de spam ou lixo eletrônico." in page.text
    assert ">Continuar<" in page.text
    assert "Já verifiquei meu e-mail — Continuar" not in page.text
    assert 'href="/auth/verificar-email/continuar"' in page.text
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|journey-2")) is None
        admin_id = db.scalar(select(User.id).where(User.email == "journey.admin@example.com"))
        notes = list(
            db.scalars(
                select(Notification).where(
                    Notification.user_id == admin_id,
                    Notification.type == TYPE_REGISTRATION_REQUEST,
                )
            )
        )
        assert notes == []
    finally:
        db.close()


def test_same_sub_callback_keeps_profile_draft(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(
        http,
        Auth0Identity(sub="auth0|draft-keep", email="draft.keep@example.com", email_verified=False),
    )
    http.post(
        "/auth/completar-perfil",
        data={"name": "Azi Keep", "username": "azi_keep"},
        follow_redirects=False,
    )
    again = _start_callback(
        http,
        Auth0Identity(sub="auth0|draft-keep", email="draft.keep@example.com", email_verified=False),
    )
    assert again.headers["location"] == "/auth/verificar-email"
    verify = http.get("/auth/verificar-email")
    assert verify.status_code == 200


def test_other_sub_callback_does_not_inherit_profile_draft(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(
        http,
        Auth0Identity(sub="auth0|draft-a", email="draft.a@example.com", email_verified=False),
    )
    http.post(
        "/auth/completar-perfil",
        data={"name": "Pessoa A", "username": "pessoa_a_draft"},
        follow_redirects=False,
    )
    switched = _start_callback(
        http,
        Auth0Identity(sub="auth0|draft-b", email="draft.b@example.com", email_verified=False, name="Outro"),
    )
    assert switched.headers["location"] == "/auth/completar-perfil"
    page = http.get("/auth/completar-perfil")
    assert "pessoa_a_draft" not in page.text
    assert "Pessoa A" not in page.text


def test_continue_unverified_returns_to_verification(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(
        http,
        Auth0Identity(sub="auth0|still-unv", email="still.unv@example.com", email_verified=False),
    )
    http.post(
        "/auth/completar-perfil",
        data={"name": "Ainda", "username": "ainda_unv"},
        follow_redirects=False,
    )
    started = http.get("/auth/verificar-email/continuar", follow_redirects=False)
    assert started.status_code == 303
    location = started.headers["location"]
    query = parse_qs(urlparse(location).query)
    assert query["prompt"] == ["none"]
    assert "screen_hint" not in query
    state = query["state"][0]
    with patch("app.main.redeem_callback", return_value=Auth0Identity(
        sub="auth0|still-unv", email="still.unv@example.com", email_verified=False
    )):
        callback = http.get(f"/callback?code=fake&state={state}", follow_redirects=False)
    assert callback.headers["location"] == "/auth/verificar-email"
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|still-unv")) is None
    finally:
        db.close()


def test_silent_auth_error_falls_back_to_interactive_login(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(
        http,
        Auth0Identity(sub="auth0|silent-fb", email="silent.fb@example.com", email_verified=False),
    )
    http.post(
        "/auth/completar-perfil",
        data={"name": "Silent", "username": "silent_fb"},
        follow_redirects=False,
    )
    started = http.get("/auth/verificar-email/continuar", follow_redirects=False)
    query = parse_qs(urlparse(started.headers["location"]).query)
    fallback = http.get(
        f"/callback?error=login_required&state={query['state'][0]}",
        follow_redirects=False,
    )
    assert fallback.status_code == 303
    retry = parse_qs(urlparse(fallback.headers["location"]).query)
    assert "prompt" not in retry
    assert retry["client_id"] == ["test-client-id"]


def test_continue_verified_activates_user_without_admin_notice(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "flow_site_a", "flow.site.a@example.com")
    _grant_site_admin("flow.site.a@example.com")
    admin_b = TestClient(app)
    register_active(admin_b, "flow_site_b", "flow.site.b@example.com")
    _grant_site_admin("flow.site.b@example.com")
    http = TestClient(app)
    _start_callback(
        http,
        Auth0Identity(sub="auth0|flow-ok", email="flow.ok@example.com", email_verified=False),
    )
    http.post(
        "/auth/completar-perfil",
        data={"name": "Azi", "username": "azi_ok"},
        follow_redirects=False,
    )
    started = http.get("/auth/verificar-email/continuar", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    with patch("app.main.redeem_callback", return_value=Auth0Identity(
        sub="auth0|flow-ok", email="flow.ok@example.com", email_verified=True
    )):
        callback = http.get(f"/callback?code=fake&state={state}", follow_redirects=False)
    assert callback.headers["location"] == "/"
    home = http.get("/")
    assert home.status_code == 200
    assert "Aguardando aprovação" not in home.text
    assert "Aprovação" not in home.text
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.auth0_sub == "auth0|flow-ok"))
        assert user is not None
        assert user.is_active is True
        assert user.name == "Azi"
        assert user.username_key == "azi_ok"
        requests = list(db.scalars(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id)))
        assert requests == []
        notes = list(
            db.scalars(
                select(Notification).where(
                    Notification.type == TYPE_REGISTRATION_REQUEST,
                    Notification.actor_user_id == user.id,
                )
            )
        )
        assert notes == []
        assert unread_count(db, db.scalar(select(User.id).where(User.email == "flow.site.a@example.com"))) == 0
    finally:
        db.close()
    repeated = _start_callback(
        http,
        Auth0Identity(sub="auth0|flow-ok", email="flow.ok@example.com", email_verified=True),
    )
    assert repeated.headers["location"] == "/"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.auth0_sub == "auth0|flow-ok"))
        requests = list(db.scalars(select(RegistrationRequest).where(RegistrationRequest.user_id == user.id)))
        assert requests == []
        notes = list(
            db.scalars(
                select(Notification).where(
                    Notification.type == TYPE_REGISTRATION_REQUEST,
                    Notification.actor_user_id == user.id,
                )
            )
        )
        assert notes == []
    finally:
        db.close()


def test_username_taken_during_verification_returns_to_profile(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(
        http,
        Auth0Identity(sub="auth0|taken-wait", email="taken.wait@example.com", email_verified=False),
    )
    http.post(
        "/auth/completar-perfil",
        data={"name": "Espera", "username": "espera_nick"},
        follow_redirects=False,
    )
    register_active(TestClient(app), "espera_nick", "espera.nick@example.com")
    started = http.get("/auth/verificar-email/continuar", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    with patch("app.main.redeem_callback", return_value=Auth0Identity(
        sub="auth0|taken-wait", email="taken.wait@example.com", email_verified=True
    )):
        callback = http.get(f"/callback?code=fake&state={state}", follow_redirects=False)
    assert callback.headers["location"] == "/auth/completar-perfil"
    page = http.get("/auth/completar-perfil")
    assert page.status_code == 200
    assert "já está em uso" in page.text
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|taken-wait")) is None
        assert db.scalar(select(User).where(User.email == "taken.wait@example.com")) is None
    finally:
        db.close()


def test_legacy_unverified_then_verified_auto_links_same_id(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "legado_flow", "legado.flow@example.com")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "legado.flow@example.com"))
        user_id = user.id
        assert user.auth0_sub is None
    finally:
        db.close()
    http.post("/logout", follow_redirects=False)
    first = _start_callback(
        http,
        Auth0Identity(sub="auth0|legado-flow", email="legado.flow@example.com", email_verified=False),
    )
    assert first.headers["location"] == "/auth/verificar-email"
    profile = http.get("/auth/completar-perfil", follow_redirects=False)
    assert profile.headers["location"] == "/auth/verificar-email"
    started = http.get("/auth/verificar-email/continuar", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    with patch("app.main.redeem_callback", return_value=Auth0Identity(
        sub="auth0|legado-flow", email="legado.flow@example.com", email_verified=True
    )):
        callback = http.get(f"/callback?code=fake&state={state}", follow_redirects=False)
    assert callback.headers["location"] == "/"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "legado.flow@example.com"))
        assert user.id == user_id
        assert user.auth0_sub == "auth0|legado-flow"
        assert db.scalar(select(RegistrationRequest).where(RegistrationRequest.user_id == user_id)) is None
        assert (
            db.scalar(
                select(Notification).where(
                    Notification.actor_user_id == user_id,
                    Notification.type == TYPE_REGISTRATION_REQUEST,
                )
            )
            is None
        )
    finally:
        db.close()


def test_auth0_pendente_redirects_into_new_verification_flow(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    _start_callback(
        http,
        Auth0Identity(sub="auth0|alias-pend", email="alias.pend@example.com", email_verified=False),
    )
    http.post(
        "/auth/completar-perfil",
        data={"name": "Alias", "username": "alias_pend"},
        follow_redirects=False,
    )
    aliased = http.get("/auth/pendente", follow_redirects=False)
    assert aliased.status_code == 303
    assert aliased.headers["location"] == "/auth/verificar-email"


def test_historical_pending_request_auto_activates_without_admin(monkeypatch):
    _enable_auth0(monkeypatch)
    db = SessionLocal()
    try:
        user = User(
            name="Hist Pendente",
            username="hist_pend",
            username_key="hist_pend",
            email="hist.pend@example.com",
            password_hash="",
            is_active=False,
            auth0_sub="auth0|hist-pend",
        )
        db.add(user)
        db.flush()
        db.add(RegistrationRequest(user_id=user.id, status="pending"))
        db.commit()
        user_id = user.id
    finally:
        db.close()
    http = TestClient(app)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|hist-pend", email="hist.pend@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/"
    landed = http.get("/")
    assert landed.status_code == 200
    assert 'aria-label="Configurações"' in landed.text
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        assert user.is_active is True
        assert user.id == user_id
        assert user.auth0_sub == "auth0|hist-pend"
    finally:
        db.close()


def test_banned_and_historically_rejected_stay_blocked(monkeypatch):
    _enable_auth0(monkeypatch)
    from app.accounts import utcnow
    from app.registrations import STATUS_REJECTED

    db = SessionLocal()
    try:
        banned = User(
            name="Banido",
            username="ban_auto",
            username_key="ban_auto",
            email="ban.auto@example.com",
            password_hash="",
            is_active=False,
            auth0_sub="auth0|ban-auto",
            banned_at=utcnow(),
        )
        rejected = User(
            name="Recusado",
            username="rej_auto",
            username_key="rej_auto",
            email="rej.auto@example.com",
            password_hash="",
            is_active=False,
            auth0_sub="auth0|rej-auto",
        )
        db.add(banned)
        db.add(rejected)
        db.flush()
        db.add(RegistrationRequest(user_id=rejected.id, status=STATUS_REJECTED))
        db.commit()
        banned_id = banned.id
        rejected_id = rejected.id
    finally:
        db.close()
    banned_http = TestClient(app)
    banned_cb = _start_callback(
        banned_http,
        Auth0Identity(sub="auth0|ban-auto", email="ban.auto@example.com", email_verified=True),
    )
    assert banned_cb.headers["location"] != "/"
    rejected_http = TestClient(app)
    rejected_cb = _start_callback(
        rejected_http,
        Auth0Identity(sub="auth0|rej-auto", email="rej.auto@example.com", email_verified=True),
    )
    assert rejected_cb.headers["location"] == "/auth/nao-aprovado"
    db = SessionLocal()
    try:
        assert db.get(User, banned_id).is_active is False
        assert db.get(User, rejected_id).is_active is False
    finally:
        db.close()
