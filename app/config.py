import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def required_secret_key() -> str:
    value = (os.getenv("SECRET_KEY") or "").strip()
    if not value:
        raise RuntimeError("SECRET_KEY é obrigatória. Defina a variável de ambiente antes de iniciar o Watch Club.")
    return value


SECRET_KEY = required_secret_key()


def session_https_only() -> bool:
    return os.getenv("SESSION_HTTPS_ONLY", "false").lower() in {"1", "true", "yes"}


SESSION_HTTPS_ONLY = session_https_only()
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'watch_club.db'}")
# Entertainment headlines stay useful for about an hour; avoid refetching on every click.
NEWS_TTL_SECONDS = 60 * 60
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "watch-club@localhost")
EMAIL_DEV_SHOW_LINK = os.getenv("EMAIL_DEV_SHOW_LINK", "true").lower() in {"1", "true", "yes"}
# Temporary visual showcase for the access/signup polish. Default OFF. Remove before deploy.
WATCH_CLUB_UI_PREVIEW = os.getenv("WATCH_CLUB_UI_PREVIEW", "false").lower() in {"1", "true", "yes"}
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
FACEBOOK_CLIENT_ID = os.getenv("FACEBOOK_CLIENT_ID", "")
FACEBOOK_CLIENT_SECRET = os.getenv("FACEBOOK_CLIENT_SECRET", "")
REGISTRATION_INVITE_REQUIRED = os.getenv("REGISTRATION_INVITE_REQUIRED", "false").lower() in {"1", "true", "yes"}
TMDB_ACCESS_TOKEN = os.getenv("TMDB_ACCESS_TOKEN", "")
AUTH0_DOMAIN = (os.getenv("AUTH0_DOMAIN") or "").strip()
AUTH0_CLIENT_ID = (os.getenv("AUTH0_CLIENT_ID") or "").strip()
AUTH0_CLIENT_SECRET = (os.getenv("AUTH0_CLIENT_SECRET") or "").strip()
AUTH0_CONNECTION = (os.getenv("AUTH0_CONNECTION") or "Username-Password-Authentication").strip()
BIO_MAX = 300


def _auth0_setting(name: str) -> str:
    """Prefer in-memory config (tests), then os.environ after loading the project .env."""
    load_dotenv(BASE_DIR / ".env")
    current = str(globals().get(name) or "").strip()
    if current:
        return current
    return (os.getenv(name) or "").strip()


def auth0_domain() -> str:
    return _auth0_setting("AUTH0_DOMAIN")


def auth0_client_id() -> str:
    return _auth0_setting("AUTH0_CLIENT_ID")


def auth0_client_secret() -> str:
    return _auth0_setting("AUTH0_CLIENT_SECRET")


def auth0_connection() -> str:
    return _auth0_setting("AUTH0_CONNECTION") or "Username-Password-Authentication"


def auth0_enabled() -> bool:
    return bool(auth0_domain() and auth0_client_id() and auth0_client_secret())