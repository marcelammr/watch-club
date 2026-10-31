import pytest

from app.config import required_secret_key


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
