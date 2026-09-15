from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.config import NEWS_TTL_SECONDS
from app.models import Club, ClubMember, ClubShow, NewsItem, Season, Show
from app.services import news as news_service
from app.services import tvmaze


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


def leave_club(db: Session, club_id: int, user_id: int) -> str:
    club = require_club_member(db, club_id, user_id)
    member = db.scalar(
        select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id)
    )
    others = list(
        db.scalars(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id != user_id))
    )
    club_name = club.name
    db.delete(member)
    if not others:
        db.execute(delete(ClubShow).where(ClubShow.club_id == club_id))
        db.delete(club)
        db.commit()
        return f"Você saiu e o clube “{club_name}” foi encerrado."
    if club.owner_id == user_id:
        club.owner_id = others[0].user_id
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


async def add_show_to_club(db: Session, club: Club, tvmaze_id: int, user_id: int) -> Show:
    show = await upsert_show_from_tvmaze(db, tvmaze_id)
    link = db.scalar(select(ClubShow).where(ClubShow.club_id == club.id, ClubShow.show_id == show.id))
    if not link:
        db.add(ClubShow(club_id=club.id, show_id=show.id, added_by_id=user_id))
    refresh_news(db, show)
    db.commit()
    db.refresh(show)
    return show


def load_show(db: Session, show_id: int) -> Show:
    show = db.scalar(
        select(Show)
        .options(selectinload(Show.seasons), selectinload(Show.news))
        .where(Show.id == show_id)
    )
    if not show:
        raise HTTPException(status_code=404, detail="Série não encontrada")
    return show
