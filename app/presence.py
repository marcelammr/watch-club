from __future__ import annotations

from datetime import datetime

from app.accounts import utcnow
from app.models import User

ONLINE_SECONDS = 90
AWAY_SECONDS = 10 * 60
LABELS = {"online": "Online", "away": "Ausente", "offline": "Offline"}


def presence_of(user: User | None) -> str:
    if not user or not user.last_seen:
        return "offline"
    age = (utcnow() - user.last_seen).total_seconds()
    stored = (user.presence or "").lower()
    if stored == "offline" and age > ONLINE_SECONDS:
        return "offline"
    if age <= ONLINE_SECONDS:
        return "away" if stored == "away" else "online"
    if age <= AWAY_SECONDS:
        return "away"
    return "offline"


def touch_presence(user: User, status: str | None = None) -> None:
    now = utcnow()
    user.last_seen = now
    if status in {"online", "away", "offline"}:
        user.presence = status
    elif not user.presence:
        user.presence = "online"
