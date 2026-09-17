from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.avatars import DEFAULT_AVATAR
from app.mail import send_verification_email, verification_url
from app.models import EmailToken, User
from app.security import hash_password
from app.usernames import normalize_username

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


def create_user(db: Session, username: str, email: str, password: str) -> User:
    key = normalize_username(username)
    user = User(
        name=username.strip(),
        username=key,
        username_key=key,
        email=email,
        password_hash=hash_password(password),
        is_active=False,
        avatar=DEFAULT_AVATAR,
    )
    db.add(user)
    db.flush()
    return user
