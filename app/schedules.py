from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.accounts import utcnow
from app.models import ClubMember, ClubSchedule, ClubScheduleSeries, ClubShow

CLUB_TZ = ZoneInfo("America/Sao_Paulo")
WEEKDAYS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
WEEKDAYS_LONG = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")
WEEKDAYS_FEIRA = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MONTHS_SHORT = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
NOTES_MAX = 200
TITLE_MAX = 80
MEETING_FALLBACK = "Encontro"
REPEAT_NONE = "none"
REPEAT_WEEKLY = "weekly"
REPEAT_BIWEEKLY = "biweekly"
REPEAT_CHOICES = (REPEAT_NONE, REPEAT_WEEKLY, REPEAT_BIWEEKLY)
REPEAT_STEPS = {REPEAT_WEEKLY: 7, REPEAT_BIWEEKLY: 14}
MAX_OCCURRENCES = 52
MAX_SPAN_DAYS = 366
PROGRAM_PENDING = "Programa não definido"


def parse_meeting_title(raw: str | None) -> str:
    return (raw or "").strip()[:TITLE_MAX]


def parse_optional_show_id(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        raise HTTPException(status_code=400, detail="Escolha um título deste clube.") from None
    if value < 1:
        return None
    return value


def parse_repeat(raw: str | None) -> str:
    value = (raw or REPEAT_NONE).strip().lower()
    if value not in REPEAT_CHOICES:
        raise HTTPException(status_code=400, detail="Escolha uma repetição válida.")
    return value


def resolve_club_show(
    db: Session, club_id: int, show_id: int | None
) -> int | None:
    if show_id is None:
        return None
    link = db.scalar(select(ClubShow.id).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id))
    if not link:
        raise HTTPException(status_code=400, detail="Escolha um título deste clube.")
    return show_id


def occurrence_dates(start: date, until: date, step_days: int) -> list[date]:
    if until < start:
        raise HTTPException(
            status_code=400,
            detail="A data final precisa ser igual ou posterior à data inicial.",
        )
    if (until - start).days > MAX_SPAN_DAYS:
        raise HTTPException(
            status_code=400,
            detail="A recorrência pode durar no máximo um ano.",
        )
    days: list[date] = []
    current = start
    while current <= until:
        days.append(current)
        if len(days) > MAX_OCCURRENCES:
            raise HTTPException(
                status_code=400,
                detail="Essa recorrência geraria muitos encontros. Escolha uma data final mais próxima.",
            )
        current += timedelta(days=step_days)
    return days


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


def format_schedule_detail(value: datetime | None) -> str:
    if not value:
        return ""
    local = utc_to_local(value)
    return f"{WEEKDAYS_LONG[local.weekday()]}, {local.day} {MONTHS_SHORT[local.month - 1]} · {local.strftime('%H:%M')}"


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


def program_title(item: ClubSchedule) -> str:
    if item.show_id and item.show is not None:
        return item.show.name
    return PROGRAM_PENDING


def meeting_title(item: ClubSchedule, fallback: str = MEETING_FALLBACK) -> str:
    if item.series is not None:
        series_title = (item.series.title or "").strip()
        if series_title:
            return series_title
    own = (item.title or "").strip()
    return own or fallback


def format_recurrence_line(series: ClubScheduleSeries | None) -> str:
    if not series:
        return ""
    day = WEEKDAYS_FEIRA[series.weekday]
    clock = series.time_local
    if series.interval == REPEAT_WEEKLY:
        prefix = "Todo" if series.weekday >= 5 else "Toda"
        return f"{prefix} {day} às {clock}"
    if series.interval == REPEAT_BIWEEKLY:
        return f"A cada 2 semanas, {day} às {clock}"
    return ""


def format_week_line(item: ClubSchedule) -> str:
    heading = meeting_title(item, fallback="")
    program = program_title(item)
    label = f"{heading} · {program}" if heading and heading != program else program
    line = f"{format_schedule_when(item.starts_at)} — {label}"
    compact = format_episode_compact(item.season_number, item.episode_number)
    if compact and item.show_id:
        return f"{line} · {compact}"
    return line


def format_week_span(week_start: date) -> str:
    week_end = week_start + timedelta(days=6)
    start_month = MONTHS_SHORT[week_start.month - 1]
    end_month = MONTHS_SHORT[week_end.month - 1]
    if week_start.month == week_end.month and week_start.year == week_end.year:
        return f"{week_start.day}–{week_end.day} {start_month} {week_start.year}"
    if week_start.year == week_end.year:
        return f"{week_start.day} {start_month} — {week_end.day} {end_month} {week_end.year}"
    return f"{week_start.day} {start_month} {week_start.year} — {week_end.day} {end_month} {week_end.year}"


def week_range_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    local = utc_to_local(now or utcnow())
    return local_week_bounds_utc(monday_of(local.date()))


def local_week_bounds_utc(week_start: date) -> tuple[datetime, datetime]:
    start_local = datetime(week_start.year, week_start.month, week_start.day, tzinfo=CLUB_TZ)
    end_local = start_local + timedelta(days=7)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


def list_upcoming_schedules(db: Session, club_id: int) -> list[ClubSchedule]:
    return list(
        db.scalars(
            select(ClubSchedule)
            .options(selectinload(ClubSchedule.show), selectinload(ClubSchedule.series))
            .where(ClubSchedule.club_id == club_id, ClubSchedule.starts_at >= utcnow())
            .order_by(ClubSchedule.starts_at.asc(), ClubSchedule.id.asc())
        ).all()
    )


def next_meetings_by_show(items: list[ClubSchedule]) -> dict[int, ClubSchedule]:
    nearest: dict[int, ClubSchedule] = {}
    for item in items:
        if item.show_id and item.show_id not in nearest:
            nearest[item.show_id] = item
    return nearest


def list_week_schedules(db: Session, club_id: int) -> list[ClubSchedule]:
    now = utcnow()
    _week_start, week_end = week_range_utc(now)
    return list(
        db.scalars(
            select(ClubSchedule)
            .options(selectinload(ClubSchedule.show), selectinload(ClubSchedule.series))
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


def local_today() -> date:
    return utc_to_local(utcnow()).date()


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_planner_days(
    week_start: date, items: list[ClubSchedule], today: date | None = None
) -> list[dict]:
    today = today or local_today()
    events_by_day: dict[date, list[ClubSchedule]] = {}
    for item in items:
        day = utc_to_local(item.starts_at).date()
        events_by_day.setdefault(day, []).append(item)
    days = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        days.append(
            {
                "iso": day.isoformat(),
                "num": day.day,
                "weekday": WEEKDAYS[offset],
                "is_today": day == today,
                "events": events_by_day.get(day, []),
            }
        )
    return days


def parse_iso_date(raw: str | None) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def format_clock(value: datetime | None) -> str:
    if not value:
        return ""
    return utc_to_local(value).strftime("%H:%M")


def format_day_heading(day: date, today: date | None = None) -> str:
    today = today or local_today()
    if day == today:
        return "Hoje"
    if day == today + timedelta(days=1):
        return "Amanhã"
    return f"{WEEKDAYS_LONG[day.weekday()]}, {day.day} {MONTHS_SHORT[day.month - 1]}"


def list_member_week_schedules(
    db: Session, user_id: int, week_start: date, club_id: int | None = None
) -> list[ClubSchedule]:
    start_utc, end_utc = local_week_bounds_utc(week_start)
    query = (
        select(ClubSchedule)
        .join(ClubMember, ClubMember.club_id == ClubSchedule.club_id)
        .where(
            ClubMember.user_id == user_id,
            ClubSchedule.starts_at >= start_utc,
            ClubSchedule.starts_at < end_utc,
        )
        .options(
            selectinload(ClubSchedule.show),
            selectinload(ClubSchedule.club),
            selectinload(ClubSchedule.series),
        )
        .order_by(ClubSchedule.starts_at.asc(), ClubSchedule.id.asc())
    )
    if club_id is not None:
        query = query.where(ClubSchedule.club_id == club_id)
    return list(db.scalars(query).unique().all())


def list_member_upcoming_schedules(
    db: Session, user_id: int, club_id: int | None = None
) -> list[ClubSchedule]:
    query = (
        select(ClubSchedule)
        .join(ClubMember, ClubMember.club_id == ClubSchedule.club_id)
        .where(ClubMember.user_id == user_id, ClubSchedule.starts_at >= utcnow())
        .options(
            selectinload(ClubSchedule.show),
            selectinload(ClubSchedule.club),
            selectinload(ClubSchedule.series),
        )
        .order_by(ClubSchedule.starts_at.asc(), ClubSchedule.id.asc())
    )
    if club_id is not None:
        query = query.where(ClubSchedule.club_id == club_id)
    return list(db.scalars(query).unique().all())


def group_schedules_by_day(
    items: list[ClubSchedule], today: date | None = None
) -> list[dict]:
    today = today or local_today()
    buckets: dict[date, list[ClubSchedule]] = {}
    order: list[date] = []
    for item in items:
        day = utc_to_local(item.starts_at).date()
        if day not in buckets:
            buckets[day] = []
            order.append(day)
        buckets[day].append(item)
    return [
        {
            "date": day,
            "iso": day.isoformat(),
            "heading": format_day_heading(day, today),
            "is_today": day == today,
            "is_tomorrow": day == today + timedelta(days=1),
            "events": buckets[day],
        }
        for day in order
    ]


def _get_schedule(db: Session, club_id: int, schedule_id: int) -> ClubSchedule:
    item = db.scalar(
        select(ClubSchedule)
        .options(selectinload(ClubSchedule.show), selectinload(ClubSchedule.series))
        .where(ClubSchedule.id == schedule_id, ClubSchedule.club_id == club_id)
    )
    if not item:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    return item


def create_schedule(
    db: Session,
    club_id: int,
    user_id: int,
    show_id: int | None,
    date_value: str,
    time_value: str,
    season_raw: str | None = None,
    episode_raw: str | None = None,
    notes: str | None = None,
    repeat: str | None = None,
    until_value: str | None = None,
    title: str | None = None,
) -> ClubSchedule:
    resolved_show = resolve_club_show(db, club_id, show_id)
    start_local = utc_to_local(wall_to_utc(date_value, time_value))
    start_day = start_local.date()
    time_local = start_local.strftime("%H:%M")
    season_number = parse_optional_int(season_raw, "Temporada")
    episode_number = parse_optional_int(episode_raw, "Episódio")
    note_text = (notes or "").strip()[:NOTES_MAX]
    title_text = parse_meeting_title(title)
    repeat_value = parse_repeat(repeat)
    series = None
    days = [start_day]
    if repeat_value != REPEAT_NONE:
        until_day = parse_iso_date(until_value)
        if until_day is None:
            raise HTTPException(status_code=400, detail="Informe até quando a recorrência se repete.")
        days = occurrence_dates(start_day, until_day, REPEAT_STEPS[repeat_value])
        series = ClubScheduleSeries(
            club_id=club_id,
            created_by_id=user_id,
            interval=repeat_value,
            weekday=start_day.weekday(),
            time_local=time_local,
            until_date=until_day,
            title=title_text,
        )
        db.add(series)
        db.flush()
    first: ClubSchedule | None = None
    for index, day in enumerate(days):
        item = ClubSchedule(
            club_id=club_id,
            series_id=series.id if series else None,
            show_id=resolved_show,
            title="" if series else title_text,
            starts_at=wall_to_utc(day.isoformat(), time_local),
            season_number=season_number if index == 0 else None,
            episode_number=episode_number if index == 0 else None,
            notes=note_text,
            created_by_id=user_id,
        )
        db.add(item)
        if first is None:
            first = item
    db.commit()
    db.refresh(first)
    return first


def set_schedule_program(
    db: Session,
    club_id: int,
    schedule_id: int,
    show_id: int | None,
    season_raw: str | None = None,
    episode_raw: str | None = None,
) -> ClubSchedule:
    item = _get_schedule(db, club_id, schedule_id)
    item.show_id = resolve_club_show(db, club_id, show_id)
    if item.show_id is None:
        item.season_number = None
        item.episode_number = None
    else:
        item.season_number = parse_optional_int(season_raw, "Temporada")
        item.episode_number = parse_optional_int(episode_raw, "Episódio")
    db.commit()
    db.refresh(item)
    return item


def update_schedule_when(
    db: Session,
    club_id: int,
    schedule_id: int,
    date_value: str,
    time_value: str,
    notes: str | None = None,
) -> ClubSchedule:
    item = _get_schedule(db, club_id, schedule_id)
    item.starts_at = wall_to_utc(date_value, time_value)
    if notes is not None:
        item.notes = notes.strip()[:NOTES_MAX]
    db.commit()
    db.refresh(item)
    return item


def end_schedule_series(db: Session, club_id: int, series_id: int) -> None:
    series = db.scalar(
        select(ClubScheduleSeries).where(
            ClubScheduleSeries.id == series_id, ClubScheduleSeries.club_id == club_id
        )
    )
    if not series:
        raise HTTPException(status_code=404, detail="Recorrência não encontrada")
    now = utcnow()
    future = list(
        db.scalars(
            select(ClubSchedule).where(
                ClubSchedule.series_id == series.id,
                ClubSchedule.starts_at >= now,
            )
        ).all()
    )
    for item in future:
        db.delete(item)
    series.ended_at = now
    db.commit()
