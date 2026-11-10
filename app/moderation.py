from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts import utcnow
from app.models import ModerationEvent, User

PUBLISH_BLOCKED = "Este conteúdo não pode ser publicado porque viola as regras de segurança do Watch Club."
SURFACE_PUBLIC_NAME = "public_name"
SURFACE_PUBLIC_TEXT = "public_text"
SURFACE_CHAT = "chat"
SURFACE_IMAGE = "image"

ACTION_BLOCK = "block"
ACTION_WARN = "warn"
ACTION_SUSPEND = "suspend"
ACTION_BAN = "ban"

ORIGIN_AUTO = "automatic"
ORIGIN_ADMIN = "admin"

CATEGORIES_IMMEDIATE_BAN = frozenset({"csam", "minor_sexual"})
CATEGORIES_IMMEDIATE_SUSPEND = frozenset(
    {"extremist", "hate", "threat", "criminal", "graphic_violence", "public_porn"}
)

RESTRICTED_PATHS = frozenset({"/conta-restrita", "/regras", "/logout"})


class AccountRestricted(Exception):
    """Logged-in user cannot use the app until the restriction lifts or an appeal is decided."""


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    category: str = ""
    counts: bool = False
    immediate: bool = False
    confidence: str = "none"


class ModerationProvider(Protocol):
    def moderate_text(self, text: str, *, surface: str) -> Verdict: ...

    def moderate_image(self, data: bytes, *, mime: str, surface: str) -> Verdict: ...


class AllowAllProvider:
    """Local default until a real text/image classifier is configured.

    Does not guess from word lists. Ambiguous or contextual content is never
    auto-punished here.
    """

    def moderate_text(self, text: str, *, surface: str) -> Verdict:
        return Verdict(allowed=True)

    def moderate_image(self, data: bytes, *, mime: str, surface: str) -> Verdict:
        return Verdict(allowed=True)


_provider: ModerationProvider = AllowAllProvider()


def get_provider() -> ModerationProvider:
    return _provider


def set_provider(provider: ModerationProvider | None) -> None:
    global _provider
    _provider = provider or AllowAllProvider()


def is_restricted(user: User) -> bool:
    if getattr(user, "banned_at", None):
        return True
    until = getattr(user, "suspended_until", None)
    return bool(until and until > utcnow())


def restriction_kind(user: User) -> str | None:
    if getattr(user, "banned_at", None):
        return "banned"
    until = getattr(user, "suspended_until", None)
    if until and until > utcnow():
        return "suspended"
    return None


def restriction_path_allowed(path: str) -> bool:
    if path in RESTRICTED_PATHS:
        return True
    return path.startswith("/contestacoes")


def counting_violation_count(db: Session, user_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ModerationEvent)
            .where(
                ModerationEvent.user_id == user_id,
                ModerationEvent.counts.is_(True),
                ModerationEvent.reversed_at.is_(None),
                ModerationEvent.action.in_((ACTION_WARN, ACTION_SUSPEND, ACTION_BAN)),
            )
        )
        or 0
    )


def user_moderation_history(db: Session, user_id: int) -> list[ModerationEvent]:
    return list(
        db.scalars(
            select(ModerationEvent)
            .where(ModerationEvent.user_id == user_id)
            .order_by(ModerationEvent.created_at.desc(), ModerationEvent.id.desc())
        )
    )


def _feedback_for_action(action: str, warning_number: int | None) -> str:
    if action == ACTION_WARN and warning_number == 1:
        return f"{PUBLISH_BLOCKED} Aviso 1 de 3."
    if action == ACTION_WARN and warning_number == 2:
        return f"{PUBLISH_BLOCKED} Aviso 2 de 3."
    if action == ACTION_WARN and warning_number == 3:
        return (
            f"{PUBLISH_BLOCKED} Aviso 3 de 3 — último aviso. "
            "Uma nova violação resultará na suspensão da sua conta por 30 dias."
        )
    if action == ACTION_SUSPEND:
        return f"{PUBLISH_BLOCKED} Sua conta foi suspensa por 30 dias."
    if action == ACTION_BAN:
        return f"{PUBLISH_BLOCKED} Sua conta foi banida permanentemente."
    return PUBLISH_BLOCKED


def apply_violation(
    db: Session,
    user: User,
    *,
    category: str,
    origin: str,
    evidence: str,
    counts: bool,
    automatic: bool = False,
    immediate: bool = False,
    case_id: int | None = None,
    actor_id: int | None = None,
    suspend_hours: int | None = None,
) -> tuple[ModerationEvent, str]:
    action = ACTION_BLOCK
    warning_number = None
    sets_progression = False
    if counts:
        n = counting_violation_count(db, user.id)
        if immediate and category in CATEGORIES_IMMEDIATE_BAN:
            action = ACTION_BAN
            user.banned_at = utcnow()
        elif immediate and category in CATEGORIES_IMMEDIATE_SUSPEND:
            action = ACTION_SUSPEND
            hours = suspend_hours if suspend_hours is not None else 24 * 30
            user.suspended_until = utcnow() + timedelta(hours=hours)
            if hours >= 24 * 30:
                user.had_progression_suspend = True
                sets_progression = True
        elif suspend_hours is not None:
            if suspend_hours <= 0:
                action = ACTION_BAN
                user.banned_at = utcnow()
            else:
                action = ACTION_SUSPEND
                user.suspended_until = utcnow() + timedelta(hours=suspend_hours)
        elif n <= 0:
            action = ACTION_WARN
            warning_number = 1
        elif n == 1:
            action = ACTION_WARN
            warning_number = 2
        elif n == 2:
            action = ACTION_WARN
            warning_number = 3
        elif not user.had_progression_suspend:
            action = ACTION_SUSPEND
            user.suspended_until = utcnow() + timedelta(days=30)
            user.had_progression_suspend = True
            sets_progression = True
        else:
            action = ACTION_BAN
            user.banned_at = utcnow()
    event = ModerationEvent(
        user_id=user.id,
        category=category,
        origin=origin,
        action=action,
        evidence=(evidence or "")[:8000],
        warning_number=warning_number,
        counts=bool(counts),
        automatic=bool(automatic),
        immediate=bool(immediate),
        sets_progression_suspend=sets_progression,
        case_id=case_id,
        actor_id=actor_id,
        created_at=utcnow(),
    )
    db.add(event)
    db.flush()
    if counts and (immediate or action in {ACTION_SUSPEND, ACTION_BAN} or warning_number == 3):
        from app.reports import elevate_automatic_event

        elevate_automatic_event(db, user, event)
    return event, _feedback_for_action(action, warning_number)


def reverse_event(db: Session, event: ModerationEvent, admin: User) -> None:
    if event.reversed_at is not None:
        raise HTTPException(status_code=400, detail="Esta penalidade já foi revertida")
    event.reversed_at = utcnow()
    event.reversed_by_id = admin.id
    user = db.get(User, event.user_id)
    if user is None:
        return
    if event.sets_progression_suspend:
        user.had_progression_suspend = False
    still_banned = db.scalar(
        select(ModerationEvent.id).where(
            ModerationEvent.user_id == user.id,
            ModerationEvent.action == ACTION_BAN,
            ModerationEvent.reversed_at.is_(None),
            ModerationEvent.id != event.id,
        )
    )
    if event.action == ACTION_BAN and not still_banned:
        user.banned_at = None
    still_suspended = db.scalar(
        select(ModerationEvent.id).where(
            ModerationEvent.user_id == user.id,
            ModerationEvent.action == ACTION_SUSPEND,
            ModerationEvent.reversed_at.is_(None),
            ModerationEvent.id != event.id,
        )
    )
    if event.action == ACTION_SUSPEND and not still_suspended:
        user.suspended_until = None


def enforce_text(db: Session, user: User, text: str, *, surface: str, origin: str) -> None:
    verdict = get_provider().moderate_text(text or "", surface=surface)
    if verdict.allowed:
        return
    event, message = apply_violation(
        db,
        user,
        category=verdict.category or "policy",
        origin=origin,
        evidence=text[:2000],
        counts=verdict.counts,
        automatic=True,
        immediate=verdict.immediate,
    )
    db.commit()
    raise HTTPException(status_code=400, detail=message)


def enforce_image(db: Session, user: User, data: bytes, *, mime: str, origin: str) -> None:
    verdict = get_provider().moderate_image(data or b"", mime=mime or "", surface=SURFACE_IMAGE)
    if verdict.allowed:
        return
    _event, message = apply_violation(
        db,
        user,
        category=verdict.category or "policy",
        origin=origin,
        evidence="[imagem]",
        counts=verdict.counts,
        automatic=True,
        immediate=verdict.immediate,
    )
    db.commit()
    raise HTTPException(status_code=400, detail=message)
