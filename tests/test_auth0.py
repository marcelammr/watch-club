from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.auth0_oidc import Auth0Identity, identity_from_claims
from app.db import SessionLocal, engine
from app.main import app
from app.models import User
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
    assert "access_token" not in pending


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
    assert "client_secret" not in location


def test_auth0_callback_rejects_bad_state(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    http.get("/auth/login", follow_redirects=False)
    failed = http.get("/callback?code=abc&state=errado", follow_redirects=False)
    assert failed.status_code == 303
    assert "/login" in failed.headers["location"]


def test_auth0_callback_unlinked_does_not_create_or_match_email(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_mail", "auth0.mail@example.com")
    http.post("/logout", follow_redirects=False)
    started = http.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    identity = Auth0Identity(
        sub="auth0|unlinked-1",
        email="auth0.mail@example.com",
        email_verified=True,
    )
    with patch("app.main.redeem_callback", return_value=identity):
        callback = http.get(f"/callback?code=fake&state={state}", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/auth/pendente"
    pending = http.get("/auth/pendente")
    assert pending.status_code == 200
    assert "ainda não está vinculada" in pending.text
    assert "auth0.mail@example.com" in pending.text
    assert "etapa 1" in pending.text
    assert "sim" in pending.text
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).where(User.email == "auth0.mail@example.com")))
        assert len(users) == 1
        assert users[0].auth0_sub is None
        assert db.scalar(select(User).where(User.auth0_sub == "auth0|unlinked-1")) is None
        count = db.scalar(select(User).where(User.username_key == "auth0_mail"))
        assert count is not None
    finally:
        db.close()


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


def test_auth0_logout_redirects_to_tenant(monkeypatch):
    _enable_auth0(monkeypatch)
    http = TestClient(app)
    register_active(http, "auth0_out", "auth0.out@example.com")
    left = http.get("/auth/logout", follow_redirects=False)
    assert left.status_code == 303
    location = left.headers["location"]
    parsed = urlparse(location)
    assert parsed.netloc == "tenant.example.auth0.com"
    assert parsed.path == "/v2/logout"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["test-client-id"]
    assert query["returnTo"] == ["http://127.0.0.1:8000/"]
    home = http.get("/")
    assert 'aria-label="Configurações"' not in home.text
