from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.avatars import DEFAULT_AVATAR
from app.mail import send_password_reset_email, send_verification_email, verification_url
from app.models import EmailToken, User
from app.security import hash_password
from app.usernames import normalize_username, unique_username

TOKEN_HOURS = 48
RESET_MINUTES = 15


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


def issue_reset_code(db: Session, user: User) -> str:
    from secrets import randbelow

    db.execute(delete(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == "reset"))
    code = ""
    for _ in range(30):
        candidate = f"{randbelow(1_000_000):06d}"
        exists = db.scalar(select(EmailToken).where(EmailToken.token == candidate))
        if not exists:
            code = candidate
            break
    if not code:
        raise RuntimeError("Não foi possível gerar um código de recuperação")
    db.add(
        EmailToken(
            user_id=user.id,
            token=code,
            purpose="reset",
            expires_at=utcnow() + timedelta(minutes=RESET_MINUTES),
        )
    )
    db.flush()
    return code


def send_password_reset(db: Session, user: User) -> str:
    code = issue_reset_code(db, user)
    send_password_reset_email(user.email, code)
    return code


def find_valid_reset(db: Session, email: str, code: str) -> EmailToken | None:
    cleaned = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(cleaned) != 6:
        return None
    user = find_user_by_email(db, email)
    if not user:
        return None
    record = db.scalar(
        select(EmailToken).where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == "reset",
            EmailToken.token == cleaned,
        )
    )
    if not record or record.expires_at < utcnow():
        return None
    return record


def send_activation(db: Session, user: User, new_email: str | None = None) -> str:
    purpose = "email_change" if new_email else "activate"
    token = issue_email_token(db, user, purpose=purpose, new_email=new_email)
    url = verification_url(token)
    send_verification_email(new_email or user.email, url)
    return url


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def find_user_by_email(db: Session, email: str, exclude_user_id: int | None = None) -> User | None:
    key = normalize_email(email)
    if not key:
        return None
    query = select(User).where(func.lower(User.email) == key)
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    return db.scalar(query)


def email_taken(db: Session, email: str, exclude_user_id: int | None = None) -> bool:
    if find_user_by_email(db, email, exclude_user_id=exclude_user_id):
        return True
    key = normalize_email(email)
    if not key:
        return False
    query = select(User).where(func.lower(User.pending_email) == key)
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    return db.scalar(query) is not None


def create_user(db: Session, username: str, email: str, password: str, name: str | None = None) -> User:
    key = normalize_username(username)
    display = (name or "").strip()[:80] or key
    user = User(
        name=display,
        username=key,
        username_key=key,
        email=normalize_email(email),
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
    email = normalize_email(profile.get("email") or "")
    if not email:
        raise ValueError("Conta social sem e-mail")
    user = None
    if provider == "google":
        user = db.scalar(select(User).where(User.google_id == provider_id))
    elif provider == "facebook":
        user = db.scalar(select(User).where(User.facebook_id == provider_id))
    if not user:
        user = find_user_by_email(db, email)
    if not user:
        if email_taken(db, email):
            raise ValueError("Este e-mail já está cadastrado")
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
