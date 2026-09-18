from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

from app.config import (
    APP_BASE_URL,
    FACEBOOK_CLIENT_ID,
    FACEBOOK_CLIENT_SECRET,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
)

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v3/userinfo"
FACEBOOK_AUTH = "https://www.facebook.com/v21.0/dialog/oauth"
FACEBOOK_TOKEN = "https://graph.facebook.com/v21.0/oauth/access_token"
FACEBOOK_ME = "https://graph.facebook.com/v21.0/me"


def google_enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def facebook_enabled() -> bool:
    return bool(FACEBOOK_CLIENT_ID and FACEBOOK_CLIENT_SECRET)


def _redirect(provider: str) -> str:
    return f"{APP_BASE_URL.rstrip('/')}/auth/{provider}/callback"


def new_state() -> str:
    return secrets.token_urlsafe(24)


def google_authorize_url(state: str) -> str:
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect("google"),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH}?{urlencode(params)}"


def facebook_authorize_url(state: str) -> str:
    params = {
        "client_id": FACEBOOK_CLIENT_ID,
        "redirect_uri": _redirect("facebook"),
        "state": state,
        "scope": "email,public_profile",
    }
    return f"{FACEBOOK_AUTH}?{urlencode(params)}"


def fetch_google_profile(code: str) -> dict:
    with httpx.Client(timeout=20.0) as client:
        token = client.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": _redirect("google"),
                "grant_type": "authorization_code",
            },
        )
        token.raise_for_status()
        access = token.json().get("access_token")
        info = client.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"})
        info.raise_for_status()
    data = info.json()
    email = (data.get("email") or "").lower()
    if not email:
        raise ValueError("A conta Google não enviou e-mail")
    return {
        "provider": "google",
        "provider_id": data.get("sub"),
        "email": email,
        "name": data.get("name") or email.split("@")[0],
    }


def fetch_facebook_profile(code: str) -> dict:
    with httpx.Client(timeout=20.0) as client:
        token = client.get(
            FACEBOOK_TOKEN,
            params={
                "client_id": FACEBOOK_CLIENT_ID,
                "client_secret": FACEBOOK_CLIENT_SECRET,
                "redirect_uri": _redirect("facebook"),
                "code": code,
            },
        )
        token.raise_for_status()
        access = token.json().get("access_token")
        me = client.get(FACEBOOK_ME, params={"fields": "id,name,email", "access_token": access})
        me.raise_for_status()
    data = me.json()
    email = (data.get("email") or "").lower()
    if not email:
        raise ValueError("A conta do Facebook precisa liberar o e-mail")
    return {
        "provider": "facebook",
        "provider_id": str(data.get("id")),
        "email": email,
        "name": data.get("name") or email.split("@")[0],
    }
