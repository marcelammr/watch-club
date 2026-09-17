from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")


def normalize_username(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    folded = folded.strip().lower().replace(" ", "_")
    folded = re.sub(r"[^a-z0-9_]+", "_", folded)
    folded = re.sub(r"_+", "_", folded).strip("_")
    return folded[:30]


def username_taken(db: Session, username_key: str, exclude_user_id: int | None = None) -> bool:
    query = select(User).where(User.username_key == username_key)
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    return db.scalar(query) is not None


def taken_keys(db: Session) -> set[str]:
    return set(db.scalars(select(User.username_key)).all())


def suggest_usernames(desired: str, occupied: set[str], limit: int = 6) -> list[str]:
    base = normalize_username(desired) or "cinefilo"
    suffixes = [
        "2",
        "3",
        "4",
        "_tv",
        "_watch",
        "_club",
        "cine",
        "_pop",
        "2026",
        "_series",
    ]
    suggestions: list[str] = []
    seen = {base}
    for suffix in suffixes:
        candidate = (base + suffix)[:30]
        if candidate in seen or candidate in occupied or not USERNAME_RE.match(candidate):
            continue
        suggestions.append(candidate)
        seen.add(candidate)
        if len(suggestions) >= limit:
            break
    n = 5
    while len(suggestions) < limit and n < 80:
        candidate = f"{base}{n}"[:30]
        n += 1
        if candidate in seen or candidate in occupied:
            continue
        suggestions.append(candidate)
        seen.add(candidate)
    return suggestions
