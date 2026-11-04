from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from secrets import token_urlsafe
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from app import config as app_config

AUTH0_SCOPES = "openid profile email"
AUTH0_DATABASE_CONNECTION = "Username-Password-Authentication"


class Auth0Error(Exception):
    """Falha no handshake OIDC com o Auth0."""


def _claim_profile_text(value: object, *, max_len: int = 80) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text or "@" in text:
        return None
    return text[:max_len]


@dataclass(frozen=True)
class Auth0Identity:
    sub: str
    email: str | None
    email_verified: bool
    name: str | None = None
    nickname: str | None = None

    def pending_payload(self) -> dict:
        return {
            "sub": self.sub,
            "email": self.email or "",
            "email_verified": self.email_verified,
            "name": self.name or "",
            "nickname": self.nickname or "",
        }


def auth0_enabled() -> bool:
    return app_config.auth0_enabled()


def auth0_host() -> str:
    raw = app_config.auth0_domain()
    return raw.replace("https://", "").replace("http://", "").rstrip("/")


def auth0_issuer() -> str:
    host = auth0_host()
    if not host:
        return ""
    return f"https://{host}/"


def auth0_callback_url() -> str:
    return f"{app_config.APP_BASE_URL.rstrip('/')}/callback"


def auth0_connection() -> str:
    return app_config.auth0_connection() or AUTH0_DATABASE_CONNECTION


def claim_email_verified(value: object) -> bool:
    return value is True


def identity_from_claims(claims: dict) -> Auth0Identity:
    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise Auth0Error("O Auth0 não enviou o identificador sub.")
    email_raw = claims.get("email")
    email = str(email_raw).strip().lower() if email_raw else None
    if email == "":
        email = None
    return Auth0Identity(
        sub=sub,
        email=email,
        email_verified=claim_email_verified(claims.get("email_verified")),
        name=_claim_profile_text(claims.get("name")),
        nickname=_claim_profile_text(claims.get("nickname")),
    )


def pending_identity(payload: dict | None) -> Auth0Identity | None:
    if not payload or not isinstance(payload, dict):
        return None
    sub = str(payload.get("sub") or "").strip()
    if not sub:
        return None
    email_raw = str(payload.get("email") or "").strip().lower()
    return Auth0Identity(
        sub=sub,
        email=email_raw or None,
        email_verified=claim_email_verified(payload.get("email_verified")),
        name=_claim_profile_text(payload.get("name")),
        nickname=_claim_profile_text(payload.get("nickname")),
    )


def authorize_url(state: str, nonce: str, code_challenge: str, *, signup: bool = False) -> str:
    if not auth0_enabled():
        raise Auth0Error("Auth0 não está configurado.")
    params = {
        "response_type": "code",
        "client_id": app_config.auth0_client_id(),
        "redirect_uri": auth0_callback_url(),
        "scope": AUTH0_SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "connection": auth0_connection(),
    }
    if signup:
        params["screen_hint"] = "signup"
    return f"https://{auth0_host()}/authorize?{urlencode(params)}"


def logout_url() -> str:
    if not auth0_enabled():
        raise Auth0Error("Auth0 não está configurado.")
    params = {
        "client_id": app_config.auth0_client_id(),
        "returnTo": app_config.APP_BASE_URL.rstrip("/") + "/",
    }
    return f"https://{auth0_host()}/v2/logout?{urlencode(params)}"


def pkce_pair() -> tuple[str, str]:
    verifier = token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def fetch_jwks() -> dict:
    url = f"https://{auth0_host()}/.well-known/jwks.json"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(url)
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or "keys" not in data:
        raise Auth0Error("JWKS do Auth0 inválido.")
    return data


def exchange_code(code: str, code_verifier: str) -> str:
    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            f"https://{auth0_host()}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": app_config.auth0_client_id(),
                "client_secret": app_config.auth0_client_secret(),
                "code": code,
                "redirect_uri": auth0_callback_url(),
                "code_verifier": code_verifier,
            },
        )
        response.raise_for_status()
    payload = response.json()
    id_token = payload.get("id_token")
    if not id_token or not isinstance(id_token, str):
        raise Auth0Error("O Auth0 não devolveu um id_token.")
    return id_token


def parse_id_token(id_token: str, nonce: str) -> Auth0Identity:
    key_set = KeySet.import_key_set(fetch_jwks())
    token = jwt.decode(id_token, key_set, algorithms=["RS256"])
    JWTClaimsRegistry(
        leeway=60,
        iss={"essential": True, "value": auth0_issuer()},
        aud={"essential": True, "values": [app_config.auth0_client_id()]},
        exp={"essential": True},
        nonce={"essential": True, "value": nonce},
    ).validate(token.claims)
    return identity_from_claims(dict(token.claims))


def redeem_callback(code: str, code_verifier: str, nonce: str) -> Auth0Identity:
    id_token = exchange_code(code, code_verifier)
    return parse_id_token(id_token, nonce)
