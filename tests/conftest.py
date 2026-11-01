import os
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("REGISTRATION_INVITE_REQUIRED", "false")
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""
_db = Path(__file__).resolve().parent / "test.sqlite"
if _db.exists():
    _db.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"

import pytest


@pytest.fixture(autouse=True)
def _no_live_news_fetch(monkeypatch):
    from app.services import news as news_service

    news_service.real_fetch_general_news = news_service.fetch_general_news
    monkeypatch.setattr(news_service, "fetch_general_news", lambda limit=36: [])
