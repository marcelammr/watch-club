from __future__ import annotations

from datetime import timedelta

from app.accounts import utcnow
from app.models import User

ONLINE_SECONDS = 90
AWAY_SECONDS = 10 * 60
LABELS = {"online": "Online", "away": "Ausente", "offline": "Offline"}
PREFS = {"auto", "online", "away", "offline"}


def presence_pref_of(user: User | None) -> str:
    if not user:
        return "auto"
    pref = (getattr(user, "presence_pref", None) or "auto").lower()
    return pref if pref in PREFS else "auto"


def presence_of(user: User | None) -> str:
    if not user:
        return "offline"
    pref = presence_pref_of(user)
    if pref == "offline":
        return "offline"
    if not user.last_seen:
        return "offline"
    age = (utcnow() - user.last_seen).total_seconds()
    if pref == "away":
        return "away" if age <= AWAY_SECONDS else "offline"
    if pref == "online":
        return "online" if age <= ONLINE_SECONDS else "offline"
    stored = (user.presence or "").lower()
    if stored == "offline" and age > ONLINE_SECONDS:
        return "offline"
    if age <= ONLINE_SECONDS:
        return "away" if stored == "away" else "online"
    if age <= AWAY_SECONDS:
        return "away"
    return "offline"


def touch_presence(user: User, status: str | None = None, *, prefer: bool = False) -> None:
    now = utcnow()
    user.last_seen = now
    if prefer and status in LABELS:
        user.presence_pref = status
        user.presence = status
        return
    if presence_pref_of(user) != "auto":
        return
    if status in LABELS:
        user.presence = status
    elif not user.presence:
        user.presence = "online"


def mark_logout(user: User) -> None:
    now = utcnow()
    if presence_pref_of(user) == "auto":
        user.last_seen = now
        user.presence = "offline"
        return
    user.last_seen = now - timedelta(seconds=AWAY_SECONDS + 1)
