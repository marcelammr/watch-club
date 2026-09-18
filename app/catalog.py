from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.config import NEWS_TTL_SECONDS
from app.models import Club, ClubMember, ClubMessage, ClubShow, ClubShowRating, NewsItem, Season, Show
from app.services import news as news_service
from app.services import tvmaze

CONTENT_KINDS = {
    "serie": "Série",
    "filme": "Filme",
    "animacao": "Animação",
    "programa": "Programa",
    "outro": "Outro",
}
WATCHING = "watching"
WATCHED = "watched"


def valid_kind(value: str | None) -> str:
    if value in CONTENT_KINDS:
        return value
    return "serie"


def kind_from_tvmaze(type_name: str | None) -> str:
    text = (type_name or "").lower()
    if "anim" in text:
        return "animacao"
    if "movie" in text or "film" in text:
        return "filme"
    if any(token in text for token in ("talk", "reality", "variety", "award", "news", "game")):
        return "programa"
    return "serie"


def require_club_member(db: Session, club_id: int, user_id: int) -> Club:
    club = db.get(Club, club_id)
    if not club:
        raise HTTPException(status_code=404, detail="Clube não encontrado")
    member = db.scalar(
        select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id)
    )
    if not member:
        raise HTTPException(status_code=403, detail="Você não faz parte deste clube")
    return club


def club_membership(db: Session, club_id: int, user_id: int) -> ClubMember | None:
    return db.scalar(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id))


def is_club_admin(db: Session, club_id: int, user_id: int) -> bool:
    member = club_membership(db, club_id, user_id)
    return bool(member and member.is_admin)


def require_club_admin(db: Session, club_id: int, user_id: int) -> Club:
    club = require_club_member(db, club_id, user_id)
    if not is_club_admin(db, club_id, user_id):
        raise HTTPException(status_code=403, detail="Apenas administradores podem fazer isso")
    return club


def admin_count(db: Session, club_id: int) -> int:
    return len(list(db.scalars(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.is_admin.is_(True)))))


def leave_club(db: Session, club_id: int, user_id: int) -> str:
    club = require_club_member(db, club_id, user_id)
    member = club_membership(db, club_id, user_id)
    others = list(
        db.scalars(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id != user_id))
    )
    club_name = club.name
    was_admin = bool(member.is_admin)
    db.delete(member)
    if not others:
        db.execute(delete(ClubShowRating).where(ClubShowRating.club_id == club_id))
        db.execute(delete(ClubMessage).where(ClubMessage.club_id == club_id))
        db.execute(delete(ClubShow).where(ClubShow.club_id == club_id))
        db.delete(club)
        db.commit()
        return f"Você saiu e o clube “{club_name}” foi encerrado."
    remaining_admins = [item for item in others if item.is_admin]
    if was_admin and not remaining_admins:
        others[0].is_admin = True
        remaining_admins = [others[0]]
    if club.owner_id == user_id:
        club.owner_id = remaining_admins[0].user_id if remaining_admins else others[0].user_id
    db.commit()
    return f"Você saiu do clube “{club_name}”."


async def upsert_show_from_tvmaze(db: Session, tvmaze_id: int) -> Show:
    show_data, seasons_data = await tvmaze.fetch_show_and_seasons(tvmaze_id)
    show = db.scalar(
        select(Show).options(selectinload(Show.seasons)).where(Show.tvmaze_id == tvmaze_id)
    )
    if not show:
        show = Show(tvmaze_id=tvmaze_id)
        db.add(show)
    for key, value in show_data.items():
        if key == "genres":
            show.genres = encode_genres(value)
        else:
            setattr(show, key, value)
    db.flush()

    existing = {season.number: season for season in show.seasons}
    for payload in seasons_data:
        season = existing.get(payload["number"])
        if not season:
            season = Season(show_id=show.id, number=payload["number"])
            db.add(season)
        season.name = payload["name"]
        season.episode_count = payload["episode_count"]
        season.premiere_date = payload["premiere_date"]
        season.end_date = payload["end_date"]
        season.image_url = payload["image_url"]
    db.flush()
    return show


def refresh_news(db: Session, show: Show, force: bool = False) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if (
        not force
        and show.news_fetched_at
        and now - show.news_fetched_at < timedelta(seconds=NEWS_TTL_SECONDS)
    ):
        return
    items = news_service.fetch_show_news(show.name)
    db.execute(delete(NewsItem).where(NewsItem.show_id == show.id))
    for item in items:
        db.add(NewsItem(show_id=show.id, **item))
    show.news_fetched_at = now


async def add_show_to_club(db: Session, club: Club, tvmaze_id: int, user_id: int, kind: str | None = None) -> Show:
    show = await upsert_show_from_tvmaze(db, tvmaze_id)
    if kind:
        show.kind = valid_kind(kind)
    link = db.scalar(select(ClubShow).where(ClubShow.club_id == club.id, ClubShow.show_id == show.id))
    if not link:
        db.add(ClubShow(club_id=club.id, show_id=show.id, added_by_id=user_id, watch_status=WATCHING))
    refresh_news(db, show)
    db.commit()
    db.refresh(show)
    return show


def add_manual_title(db: Session, club: Club, user_id: int, name: str, kind: str, image_url: str | None) -> Show:
    title = name.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Informe o nome do título")
    show = Show(
        tvmaze_id=_manual_tvmaze_id(db),
        name=title[:255],
        kind=valid_kind(kind),
        image_url=(image_url or "").strip() or None,
        summary=None,
        status=None,
        genres=None,
    )
    db.add(show)
    db.flush()
    db.add(ClubShow(club_id=club.id, show_id=show.id, added_by_id=user_id, watch_status=WATCHING))
    db.commit()
    db.refresh(show)
    return show


def _manual_tvmaze_id(db: Session) -> int:
    for _ in range(12):
        candidate = -secrets.randbelow(2_000_000_000) - 1
        if db.scalar(select(Show.id).where(Show.tvmaze_id == candidate)) is None:
            return candidate
    raise HTTPException(status_code=500, detail="Não foi possível salvar o título")


def set_watch_status(db: Session, club_id: int, show_id: int, status: str) -> ClubShow:
    link = db.scalar(select(ClubShow).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id))
    if not link:
        raise HTTPException(status_code=404, detail="Título não encontrado neste clube")
    link.watch_status = WATCHED if status == WATCHED else WATCHING
    db.commit()
    return link


def club_messages(db: Session, club_id: int, limit: int = 80) -> list[ClubMessage]:
    items = list(
        db.scalars(
            select(ClubMessage)
            .options(selectinload(ClubMessage.user))
            .where(ClubMessage.club_id == club_id)
            .order_by(ClubMessage.id.desc())
            .limit(limit)
        )
    )
    items.reverse()
    return items


def post_club_message(db: Session, club_id: int, user_id: int, body: str) -> ClubMessage:
    text = (body or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Escreva uma mensagem")
    message = ClubMessage(club_id=club_id, user_id=user_id, body=text[:2000])
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def encode_genres(values: list[str] | None) -> str:
    names = [str(item).strip() for item in (values or []) if str(item).strip()]
    return json.dumps(names, ensure_ascii=False)


def parse_genres(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def valid_stars(value: int | str) -> int:
    try:
        stars = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Avaliação inválida")
    if stars < 0 or stars > 5:
        raise HTTPException(status_code=400, detail="Avaliação inválida")
    return stars


def set_club_show_rating(db: Session, club_id: int, show_id: int, user_id: int, stars: int) -> ClubShowRating:
    link = db.scalar(select(ClubShow).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id))
    if not link:
        raise HTTPException(status_code=404, detail="Título não encontrado neste clube")
    rating = db.scalar(
        select(ClubShowRating).where(
            ClubShowRating.club_id == club_id,
            ClubShowRating.show_id == show_id,
            ClubShowRating.user_id == user_id,
        )
    )
    if rating:
        rating.stars = stars
    else:
        rating = ClubShowRating(club_id=club_id, show_id=show_id, user_id=user_id, stars=stars)
        db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating


def club_rating_stats(db: Session, club_id: int, user_id: int) -> dict[int, dict]:
    rows = list(db.scalars(select(ClubShowRating).where(ClubShowRating.club_id == club_id)))
    grouped: dict[int, dict] = {}
    for row in rows:
        bucket = grouped.setdefault(row.show_id, {"sum": 0, "count": 0, "mine": None})
        bucket["sum"] += row.stars
        bucket["count"] += 1
        if row.user_id == user_id:
            bucket["mine"] = row.stars
    stats = {}
    for show_id, bucket in grouped.items():
        avg = bucket["sum"] / bucket["count"] if bucket["count"] else None
        stats[show_id] = {
            "average": avg,
            "count": bucket["count"],
            "mine": bucket["mine"],
            "filled": int(round(avg)) if avg is not None else 0,
        }
    return stats


def rating_view(stats: dict[int, dict], show_id: int) -> dict:
    return stats.get(show_id, {"average": None, "count": 0, "mine": None, "filled": 0})


def remove_show_from_club(db: Session, club_id: int, show_id: int) -> None:
    link = db.scalar(select(ClubShow).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id))
    if not link:
        raise HTTPException(status_code=404, detail="Título não encontrado neste clube")
    db.execute(
        delete(ClubShowRating).where(ClubShowRating.club_id == club_id, ClubShowRating.show_id == show_id)
    )
    db.delete(link)
    db.commit()


async def fill_missing_genres(db: Session, shows: list[Show]) -> None:
    missing = [show for show in shows if show.tvmaze_id > 0 and show.genres is None]
    if not missing:
        return
    results = await asyncio.gather(
        *[tvmaze.fetch_show_genres(show.tvmaze_id) for show in missing],
        return_exceptions=True,
    )
    for show, result in zip(missing, results):
        if isinstance(result, Exception):
            continue
        show.genres = encode_genres(result)


def load_show(db: Session, show_id: int) -> Show:
    show = db.scalar(
        select(Show)
        .options(selectinload(Show.seasons), selectinload(Show.news))
        .where(Show.id == show_id)
    )
    if not show:
        raise HTTPException(status_code=404, detail="Série não encontrada")
    return show
