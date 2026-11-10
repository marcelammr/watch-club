from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts import utcnow
from app.friends import friend_id_set
from app.models import ClubMember, User, UserShowFavorite

DEFAULT_THEME = "watchclub"
PROFILE_STATUS_MAX = 80
DAYS_PER_LEVEL = 30
MAX_LEVEL = 99
ENERGY_MAX = 5
THEMES = {
    "watchclub": "Watch Club",
    "bubblegum": "Bubblegum",
    "cyber": "Cyber",
    "dreamy": "Dreamy",
}
PROFILE_TABS = ("perfil", "favoritos", "clubes", "aparencia")


def normalize_theme(value: str | None) -> str:
    key = (value or "").strip().lower()
    return key if key in THEMES else DEFAULT_THEME


def require_theme(value: str | None) -> str:
    key = (value or "").strip().lower()
    if key not in THEMES:
        raise HTTPException(status_code=400, detail="Tema inválido")
    return key


def theme_of(user: User | None) -> str:
    if user is None:
        return DEFAULT_THEME
    return normalize_theme(getattr(user, "theme_key", None))


def player_progress(created_at: datetime | None, *, now: datetime | None = None) -> dict:
    moment = now or utcnow()
    start = created_at or moment
    days = max(0, (moment - start).days)
    level = min(MAX_LEVEL, 1 + days // DAYS_PER_LEVEL)
    if level >= MAX_LEVEL:
        into = DAYS_PER_LEVEL
        percent = 100
    else:
        into = days % DAYS_PER_LEVEL
        percent = int(round(100 * into / DAYS_PER_LEVEL))
    return {
        "level": level,
        "percent": percent,
        "into_days": into,
        "span_days": DAYS_PER_LEVEL,
        "max_level": MAX_LEVEL,
    }


def energy_hearts(last_seen: datetime | None, *, now: datetime | None = None) -> int:
    if last_seen is None:
        return 0
    moment = now or utcnow()
    days = max(0.0, (moment - last_seen).total_seconds() / 86400)
    if days <= 1:
        return 5
    if days <= 3:
        return 4
    if days <= 7:
        return 3
    if days <= 14:
        return 2
    if days <= 30:
        return 1
    return 0


def clean_profile_status(value: str | None) -> str:
    text = " ".join((value or "").split())
    if len(text) > PROFILE_STATUS_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"O status pode ter no máximo {PROFILE_STATUS_MAX} caracteres.",
        )
    return text


def profile_tab(aba: str | None, *, own: bool) -> str:
    key = (aba or "").strip().lower()
    if key == "aparencia" and not own:
        return "perfil"
    if key in PROFILE_TABS:
        return key
    return "perfil"


def player_stats(db: Session, person: User, *, club_count: int, favorite_count: int) -> dict:
    year = person.created_at.year if person.created_at else utcnow().year
    return {
        "clubs": club_count,
        "friends": len(friend_id_set(db, person.id)),
        "favorites": favorite_count,
        "member_since": year,
    }


def player_card_payload(db: Session, user: User) -> dict:
    clubs = db.scalar(select(func.count()).select_from(ClubMember).where(ClubMember.user_id == user.id)) or 0
    favorites = (
        db.scalar(select(func.count()).select_from(UserShowFavorite).where(UserShowFavorite.user_id == user.id))
        or 0
    )
    progress = player_progress(user.created_at)
    return {
        "level": progress["level"],
        "percent": progress["percent"],
        "energy": energy_hearts(user.last_seen),
        "energy_max": ENERGY_MAX,
        "status": (user.profile_status or "").strip(),
        "stats": player_stats(db, user, club_count=int(clubs), favorite_count=int(favorites)),
        "theme": theme_of(user),
    }
