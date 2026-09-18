from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.avatars import DEFAULT_AVATAR
from app.mail import send_verification_email, verification_url
from app.models import EmailToken, User
from app.security import hash_password
from app.usernames import normalize_username, unique_username

TOKEN_HOURS = 48


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def issue_email_token(db: Session, user: User, purpose: str = "activate", new_email: str | None = None) -> str:
    from secrets import token_urlsafe

    db.execute(delete(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == purpose))
    token = token_urlsafe(32)
    db.add(
        EmailToken(
            user_id=user.id,
            token=token,
            purpose=purpose,
            new_email=new_email,
            expires_at=utcnow() + timedelta(hours=TOKEN_HOURS),
        )
    )
    db.flush()
    return token


def send_activation(db: Session, user: User, new_email: str | None = None) -> str:
    purpose = "email_change" if new_email else "activate"
    token = issue_email_token(db, user, purpose=purpose, new_email=new_email)
    url = verification_url(token)
    send_verification_email(new_email or user.email, url)
    return url


def create_user(db: Session, username: str, email: str, password: str, name: str | None = None) -> User:
    key = normalize_username(username)
    display = (name or "").strip()[:80] or key
    user = User(
        name=display,
        username=key,
        username_key=key,
        email=email,
        password_hash=hash_password(password),
        is_active=False,
        avatar=DEFAULT_AVATAR,
        bio="",
        presence="offline",
        username_changed_at=utcnow(),
    )
    db.add(user)
    db.flush()
    return user


def login_or_create_oauth(db: Session, profile: dict) -> User:
    provider = profile["provider"]
    provider_id = profile["provider_id"]
    email = profile["email"]
    user = None
    if provider == "google":
        user = db.scalar(select(User).where(User.google_id == provider_id))
    elif provider == "facebook":
        user = db.scalar(select(User).where(User.facebook_id == provider_id))
    if not user:
        user = db.scalar(select(User).where(User.email == email))
    if not user:
        username = unique_username(db, profile.get("name") or email.split("@")[0])
        user = User(
            name=(profile.get("name") or username)[:80],
            username=username,
            username_key=username,
            email=email,
            password_hash="",
            is_active=True,
            avatar=DEFAULT_AVATAR,
            bio="",
            presence="offline",
            username_changed_at=utcnow(),
        )
        db.add(user)
        db.flush()
    if provider == "google":
        user.google_id = provider_id
    else:
        user.facebook_id = provider_id
    user.is_active = True
    if not user.email:
        user.email = email
    db.flush()
    return user
