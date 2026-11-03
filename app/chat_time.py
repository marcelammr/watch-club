from __future__ import annotations

from datetime import datetime

from app.accounts import utcnow
from app.schedules import utc_to_local

MONTHS_LONG = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def chat_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return utc_to_local(value)


def chat_day_key(value: datetime | None) -> str:
    local = chat_local(value)
    if local is None:
        return ""
    return local.date().isoformat()


def chat_clock(value: datetime | None) -> str:
    local = chat_local(value)
    if local is None:
        return ""
    return local.strftime("%H:%M")


def chat_day_label(value: datetime | None, now: datetime | None = None) -> str:
    local = chat_local(value)
    if local is None:
        return ""
    today = utc_to_local(now or utcnow()).date()
    day = local.date()
    delta = (today - day).days
    if delta == 0:
        return "Hoje"
    if delta == 1:
        return "Ontem"
    return f"{day.day} de {MONTHS_LONG[day.month - 1]} de {day.year}"
