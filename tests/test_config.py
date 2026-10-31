import pytest

from app.config import required_secret_key, session_https_only


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
