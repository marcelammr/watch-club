from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import utcnow
from app.models import ClubEpisodeWatch, ClubShow, ClubWatchRound, Episode

_OPEN_ROUND = ClubWatchRound.completed_at.is_(None)


def _require_club_show(db: Session, club_id: int, show_id: int) -> None:
    link = db.scalar(select(ClubShow.id).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id))
    if not link:
        raise HTTPException(status_code=400, detail="Escolha um título deste clube.")


def _open_round(db: Session, club_id: int, show_id: int) -> ClubWatchRound | None:
    return db.scalar(
        select(ClubWatchRound).where(
            ClubWatchRound.club_id == club_id,
            ClubWatchRound.show_id == show_id,
            _OPEN_ROUND,
        )
    )


def get_open_round(db: Session, club_id: int, show_id: int) -> ClubWatchRound | None:
    return _open_round(db, club_id, show_id)


def get_or_create_open_round(db: Session, club_id: int, show_id: int) -> ClubWatchRound:
    _require_club_show(db, club_id, show_id)
    existing = _open_round(db, club_id, show_id)
    if existing:
        return existing
    next_number = db.scalar(
        select(func.max(ClubWatchRound.number)).where(
            ClubWatchRound.club_id == club_id,
            ClubWatchRound.show_id == show_id,
        )
    )
    round_row = ClubWatchRound(
        club_id=club_id,
        show_id=show_id,
        number=(next_number or 0) + 1,
        started_at=utcnow(),
        completed_at=None,
    )
    db.add(round_row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _open_round(db, club_id, show_id)
        if existing:
            return existing
        raise
    db.refresh(round_row)
    return round_row


def _episode_for_show(db: Session, show_id: int, episode_id: int) -> Episode:
    episode = db.get(Episode, episode_id)
    if not episode or episode.show_id != show_id:
        raise HTTPException(status_code=400, detail="Episódio não pertence a este título.")
    return episode


def _watch_row(db: Session, round_id: int, episode_id: int) -> ClubEpisodeWatch | None:
    return db.scalar(
        select(ClubEpisodeWatch).where(
            ClubEpisodeWatch.round_id == round_id,
            ClubEpisodeWatch.episode_id == episode_id,
        )
    )


def mark_episode_watched(
    db: Session,
    club_id: int,
    show_id: int,
    episode_id: int,
    marked_by_id: int | None = None,
) -> ClubEpisodeWatch:
    _episode_for_show(db, show_id, episode_id)
    round_row = get_or_create_open_round(db, club_id, show_id)
    existing = _watch_row(db, round_row.id, episode_id)
    if existing:
        return existing
    watch = ClubEpisodeWatch(
        round_id=round_row.id,
        episode_id=episode_id,
        watched_at=utcnow(),
        marked_by_id=marked_by_id,
    )
    db.add(watch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _watch_row(db, round_row.id, episode_id)
        if existing:
            return existing
        raise
    db.refresh(watch)
    return watch


def unmark_episode(db: Session, club_id: int, show_id: int, episode_id: int) -> None:
    round_row = _open_round(db, club_id, show_id)
    if not round_row:
        return
    watch = _watch_row(db, round_row.id, episode_id)
    if not watch:
        return
    db.delete(watch)
    db.commit()


def watched_episode_ids(db: Session, club_id: int, show_id: int) -> set[int]:
    round_row = _open_round(db, club_id, show_id)
    if not round_row:
        return set()
    return set(
        db.scalars(
            select(ClubEpisodeWatch.episode_id).where(ClubEpisodeWatch.round_id == round_row.id)
        ).all()
    )


def _catalog_episodes(db: Session, show_id: int) -> list[Episode]:
    return list(
        db.scalars(
            select(Episode)
            .where(Episode.show_id == show_id)
            .order_by(Episode.season_number.asc(), Episode.number.asc(), Episode.id.asc())
        ).all()
    )


def is_regular_episode(episode: Episode) -> bool:
    return episode.season_number >= 1 and episode.number is not None


def next_episode(db: Session, club_id: int, show_id: int) -> Episode | None:
    watched = watched_episode_ids(db, club_id, show_id)
    for episode in _catalog_episodes(db, show_id):
        if not is_regular_episode(episode):
            continue
        if episode.id not in watched:
            return episode
    return None


def progress_snapshot(db: Session, club_id: int, show_id: int) -> dict:
    catalog = _catalog_episodes(db, show_id)
    regular = [episode for episode in catalog if is_regular_episode(episode)]
    watched_ids = watched_episode_ids(db, club_id, show_id)
    watched_count = sum(1 for episode in regular if episode.id in watched_ids)
    upcoming = next((episode for episode in regular if episode.id not in watched_ids), None)
    groups: list[tuple[int, list[Episode]]] = []
    for episode in regular:
        if not groups or groups[-1][0] != episode.season_number:
            groups.append((episode.season_number, [episode]))
        else:
            groups[-1][1].append(episode)
    return {
        "total": len(regular),
        "watched_count": watched_count,
        "next": upcoming,
        "next_label": format_next_episode(upcoming),
        "complete": bool(regular) and upcoming is None,
        "has_regular": bool(regular),
        "watched_ids": watched_ids,
        "groups": groups,
    }


def pick_season(groups: list[tuple[int, list]], raw: str | None) -> tuple[int | None, list]:
    numbers = [number for number, _episodes in groups]
    if not numbers:
        return None, []
    try:
        chosen = int((raw or "").strip())
    except (TypeError, ValueError):
        chosen = numbers[0]
    else:
        if chosen not in numbers:
            chosen = numbers[0]
    episodes = next(items for number, items in groups if number == chosen)
    return chosen, episodes


def format_next_episode(episode: Episode | None) -> str:
    if not episode:
        return ""
    name = (episode.name or "").strip()
    label = f"T{episode.season_number} E{episode.number}"
    return f"{label} — {name}" if name else label
