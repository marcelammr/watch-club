from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.accounts import utcnow
from app.models import ClubSchedule, ClubShow

CLUB_TZ = ZoneInfo("America/Sao_Paulo")
WEEKDAYS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
NOTES_MAX = 200


def parse_optional_int(raw: str | None, label: str) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{label} inválido.") from None
    if value < 1 or value > 999:
        raise HTTPException(status_code=400, detail=f"{label} inválido.")
    return value


def wall_to_utc(date_value: str, time_value: str) -> datetime:
    text = f"{(date_value or '').strip()} {(time_value or '').strip()}"
    local = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            local = datetime.strptime(text, fmt).replace(tzinfo=CLUB_TZ)
            break
        except ValueError:
            continue
    if local is None:
        raise HTTPException(status_code=400, detail="Informe uma data e um horário válidos.")
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def utc_to_local(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc).astimezone(CLUB_TZ)


def format_schedule_when(value: datetime | None) -> str:
    if not value:
        return ""
    local = utc_to_local(value)
    return f"{WEEKDAYS[local.weekday()]} · {local.strftime('%H:%M')}"


def format_episode_line(season_number: int | None, episode_number: int | None) -> str:
    parts: list[str] = []
    if season_number is not None:
        parts.append(f"Temporada {season_number}")
    if episode_number is not None:
        parts.append(f"Episódio {episode_number}")
    return " · ".join(parts)


def format_episode_compact(season_number: int | None, episode_number: int | None) -> str:
    if season_number is not None and episode_number is not None:
        return f"T{season_number} E{episode_number}"
    if season_number is not None:
        return f"T{season_number}"
    if episode_number is not None:
        return f"E{episode_number}"
    return ""


def format_week_line(item: ClubSchedule) -> str:
    line = f"{format_schedule_when(item.starts_at)} — {item.show.name}"
    compact = format_episode_compact(item.season_number, item.episode_number)
    if compact:
        return f"{line} · {compact}"
    return line


def week_range_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    local = utc_to_local(now or utcnow())
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    next_monday = monday + timedelta(days=7)
    return (
        monday.astimezone(timezone.utc).replace(tzinfo=None),
        next_monday.astimezone(timezone.utc).replace(tzinfo=None),
    )


def list_upcoming_schedules(db: Session, club_id: int) -> list[ClubSchedule]:
    return list(
        db.scalars(
            select(ClubSchedule)
            .options(selectinload(ClubSchedule.show))
            .where(ClubSchedule.club_id == club_id, ClubSchedule.starts_at >= utcnow())
            .order_by(ClubSchedule.starts_at.asc(), ClubSchedule.id.asc())
        ).all()
    )


def list_week_schedules(db: Session, club_id: int) -> list[ClubSchedule]:
    now = utcnow()
    _week_start, week_end = week_range_utc(now)
    return list(
        db.scalars(
            select(ClubSchedule)
            .options(selectinload(ClubSchedule.show))
            .where(
                ClubSchedule.club_id == club_id,
                ClubSchedule.starts_at >= now,
                ClubSchedule.starts_at < week_end,
            )
            .order_by(ClubSchedule.starts_at.asc(), ClubSchedule.id.asc())
        ).all()
    )


def cancel_schedule(db: Session, club_id: int, schedule_id: int) -> None:
    item = db.scalar(
        select(ClubSchedule).where(ClubSchedule.id == schedule_id, ClubSchedule.club_id == club_id)
    )
    if not item:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    db.delete(item)
    db.commit()


def create_schedule(
    db: Session,
    club_id: int,
    user_id: int,
    show_id: int,
    date_value: str,
    time_value: str,
    season_raw: str | None = None,
    episode_raw: str | None = None,
    notes: str | None = None,
) -> ClubSchedule:
    link = db.scalar(select(ClubShow.id).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id))
    if not link:
        raise HTTPException(status_code=400, detail="Escolha um título deste clube.")
    item = ClubSchedule(
        club_id=club_id,
        show_id=show_id,
        starts_at=wall_to_utc(date_value, time_value),
        season_number=parse_optional_int(season_raw, "Temporada"),
        episode_number=parse_optional_int(episode_raw, "Episódio"),
        notes=(notes or "").strip()[:NOTES_MAX],
        created_by_id=user_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
