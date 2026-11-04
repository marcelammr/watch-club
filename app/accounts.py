from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.avatars import DEFAULT_AVATAR
from app.db import close_exclusive_session, exclusive_write_session
from app.mail import send_password_reset_email, send_verification_email, verification_url
from app.models import EmailToken, User
from app.security import hash_password
from app.usernames import USERNAME_RE, normalize_username, suggest_usernames, taken_keys, unique_username, username_taken

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


def find_user_by_auth0_sub(db: Session, sub: str | None) -> User | None:
    key = (sub or "").strip()
    if not key:
        return None
    return db.scalar(select(User).where(User.auth0_sub == key))


def resolve_auth0_login_user_id(
    source: Session,
    *,
    sub: str,
    email: str | None,
    email_verified: bool,
) -> int | None:
    """Map an Auth0 identity to an existing Watch Club user without creating one.

    Known auth0_sub wins. Otherwise a verified email may attach the sub to the
    matching account when that row has no auth0_sub yet.
    """
    known = find_user_by_auth0_sub(source, sub)
    if known:
        return known.id
    if email_verified is not True:
        return None
    address = normalize_email(email or "")
    if not address:
        return None
    write = exclusive_write_session(source)
    try:
        known = find_user_by_auth0_sub(write, sub)
        if known:
            return known.id
        candidate = find_user_by_email(write, address)
        if candidate is None:
            return None
        bound = (candidate.auth0_sub or "").strip()
        if bound:
            return None
        if not candidate.is_active:
            return None
        candidate.auth0_sub = sub.strip()
        write.commit()
        return candidate.id
    except IntegrityError:
        write.rollback()
        known = find_user_by_auth0_sub(write, sub)
        return known.id if known else None
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)


def _clean_profile_name(value: str | None) -> str:
    text = " ".join((value or "").split()).strip()
    if not text or "@" in text:
        return ""
    return text[:80]


def suggested_auth0_name(*, email: str | None, name: str | None = None, nickname: str | None = None) -> str:
    for candidate in (name, nickname):
        cleaned = _clean_profile_name(candidate)
        if cleaned:
            return cleaned
    local = normalize_email(email or "").split("@")[0]
    friendly = " ".join(local.replace(".", " ").replace("_", " ").replace("-", " ").replace("+", " ").split())
    return friendly[:80] if friendly else "Membro"


def suggested_auth0_username(db: Session, seed: str) -> str:
    return unique_username(db, seed)


def auth0_followup_path(db: Session, user: User | None, *, email: str | None, email_verified: bool) -> str:
    if user and user.is_active:
        return "/"
    if user:
        from app.registrations import STATUS_REJECTED, registration_status_for_user

        if registration_status_for_user(db, user.id) == STATUS_REJECTED:
            return "/auth/nao-aprovado"
        return "/auth/aguardando"
    if email_verified is True and normalize_email(email or ""):
        return "/auth/completar-perfil"
    return "/auth/pendente"


def create_auth0_user(db: Session, *, sub: str, email: str, name: str, username: str) -> User:
    key = normalize_username(username)
    display = (name or "").strip()[:80] or key
    user = User(
        name=display,
        username=key,
        username_key=key,
        email=normalize_email(email),
        password_hash="",
        is_active=False,
        auth0_sub=sub.strip(),
        avatar=DEFAULT_AVATAR,
        avatar_type="illustrated",
        avatar_provider="watchclub",
        avatar_value=DEFAULT_AVATAR,
        bio="",
        presence="offline",
        presence_pref="auto",
        username_changed_at=None,
    )
    db.add(user)
    db.flush()
    return user


def complete_auth0_onboarding(
    source: Session,
    *,
    sub: str,
    email: str | None,
    email_verified: bool,
    name: str,
    username: str,
) -> tuple[str, int | None, str, list[str]]:
    if email_verified is not True:
        return "unverified", None, "Confirme seu e-mail no Auth0 antes de continuar.", []
    address = normalize_email(email or "")
    if not address:
        return "unverified", None, "O Auth0 não enviou um e-mail verificado.", []
    display = (name or "").strip()[:80]
    if not display:
        return "form_error", None, "Informe um nome.", []
    key = normalize_username(username)
    if not USERNAME_RE.match(key):
        return "form_error", None, "O @ precisa ter 3 a 30 caracteres (letras, números ou _).", []

    write = exclusive_write_session(source)
    try:
        known = find_user_by_auth0_sub(write, sub)
        if known:
            if known.is_active:
                return "active", known.id, "", []
            from app.registrations import ensure_pending_registration

            ensure_pending_registration(write, known.id)
            write.commit()
            return "awaiting", known.id, "", []
        candidate = find_user_by_email(write, address)
        if candidate is not None:
            bound = (candidate.auth0_sub or "").strip()
            if bound:
                return "form_error", None, "Este e-mail já está cadastrado.", []
            if candidate.is_active:
                candidate.auth0_sub = sub.strip()
                write.commit()
                return "active", candidate.id, "", []
            return "form_error", None, "Este e-mail já está cadastrado.", []
        if email_taken(write, address):
            return "form_error", None, "Este e-mail já está cadastrado.", []
        if username_taken(write, key):
            return (
                "form_error",
                None,
                "Esse @ já está em uso. Que tal um destes?",
                suggest_usernames(key, taken_keys(write)),
            )
        user = create_auth0_user(write, sub=sub.strip(), email=address, name=display, username=key)
        from app.registrations import ensure_pending_registration

        ensure_pending_registration(write, user.id)
        write.commit()
        return "awaiting", user.id, "", []
    except IntegrityError:
        write.rollback()
        known = find_user_by_auth0_sub(write, sub)
        if known:
            if known.is_active:
                return "active", known.id, "", []
            from app.registrations import ensure_pending_registration

            ensure_pending_registration(write, known.id)
            write.commit()
            return "awaiting", known.id, "", []
        if username_taken(write, key):
            return (
                "form_error",
                None,
                "Esse @ já está em uso. Que tal um destes?",
                suggest_usernames(key, taken_keys(write)),
            )
        if email_taken(write, address):
            return "form_error", None, "Este e-mail já está cadastrado.", []
        return "form_error", None, "Não foi possível completar o perfil. Tente de novo.", []
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)


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
        avatar_type="illustrated",
        avatar_provider="watchclub",
        avatar_value=DEFAULT_AVATAR,
        bio="",
        presence="offline",
        presence_pref="auto",
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
        from app import config
        from app.invites import InviteSignupBlocked

        if config.REGISTRATION_INVITE_REQUIRED:
            raise InviteSignupBlocked()
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
            avatar_type="illustrated",
            avatar_provider="watchclub",
            avatar_value=DEFAULT_AVATAR,
            bio="",
            presence="offline",
            presence_pref="auto",
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
