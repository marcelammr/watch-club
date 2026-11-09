import pytest

from app.config import (
    BASE_DIR,
    DEFAULT_UPLOADS_DIR,
    auth0_enabled,
    required_secret_key,
    session_https_only,
    uploads_dir,
)


def test_required_secret_key_accepts_configured_value(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-from-suite")
    assert required_secret_key() == "test-secret-from-suite"


def test_required_secret_key_rejects_missing(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY é obrigatória"):
        required_secret_key()


def test_required_secret_key_rejects_blank(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "   ")
    with pytest.raises(RuntimeError, match="SECRET_KEY é obrigatória"):
        required_secret_key()


def test_session_https_only_defaults_to_false(monkeypatch):
    monkeypatch.delenv("SESSION_HTTPS_ONLY", raising=False)
    assert session_https_only() is False


def test_session_https_only_true_values(monkeypatch):
    monkeypatch.setenv("SESSION_HTTPS_ONLY", "true")
    assert session_https_only() is True


def test_session_https_only_false_values(monkeypatch):
    monkeypatch.setenv("SESSION_HTTPS_ONLY", "false")
    assert session_https_only() is False


def test_uploads_dir_defaults_to_app_static_uploads(monkeypatch):
    monkeypatch.delenv("WATCH_CLUB_UPLOADS_DIR", raising=False)
    assert uploads_dir() == DEFAULT_UPLOADS_DIR
    assert uploads_dir() == BASE_DIR / "app" / "static" / "uploads"


def test_uploads_dir_uses_env_path(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCH_CLUB_UPLOADS_DIR", str(tmp_path / "persistent" / "uploads"))
    assert uploads_dir() == tmp_path / "persistent" / "uploads"


def test_auth0_enabled_requires_domain_and_credentials(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "")
    monkeypatch.setenv("AUTH0_CLIENT_SECRET", "")
    monkeypatch.setattr("app.config.AUTH0_DOMAIN", "")
    monkeypatch.setattr("app.config.AUTH0_CLIENT_ID", "id")
    monkeypatch.setattr("app.config.AUTH0_CLIENT_SECRET", "secret")
    assert auth0_enabled() is False
    monkeypatch.setattr("app.config.AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setattr("app.config.AUTH0_CLIENT_ID", "")
    assert auth0_enabled() is False
    monkeypatch.setattr("app.config.AUTH0_CLIENT_ID", "id")
    monkeypatch.setattr("app.config.AUTH0_CLIENT_SECRET", "secret")
    assert auth0_enabled() is True
