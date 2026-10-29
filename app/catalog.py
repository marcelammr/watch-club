from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import NEWS_TTL_SECONDS
from app.club_tags import clear_displayed_club, clear_tag_preferences
from app.models import (
    Club,
    ClubJoinRequest,
    ClubMember,
    ClubMessage,
    ClubShow,
    ClubShowRating,
    Episode,
    NewsItem,
    Season,
    Show,
)
from app.db import close_exclusive_session, exclusive_write_session
from app.roles import (
    MAX_ADMINS,
    MAX_SUPPORT,
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_SUPPORT,
    ROLES,
    can,
    dump_support_perms,
    member_role,
    set_member_role,
)
from app.services import news as news_service
from app.services import tmdb, tvmaze
from app.services.tmdb import TmdbUnavailable

CONTENT_KINDS = {
    "serie": "Série",
    "filme": "Filme",
    "animacao": "Animação",
    "programa": "Programa",
    "outro": "Outro",
}
WATCHING = "watching"
WATCHED = "watched"
SOURCE_TVMAZE = "tvmaze"
SOURCE_TMDB = "tmdb"
SOURCE_MANUAL = "manual"


def show_source(show: Show) -> str:
    if show.tvmaze_id > 0:
        return SOURCE_TVMAZE
    if show.tmdb_id:
        return SOURCE_TMDB
    return SOURCE_MANUAL


def can_refresh_catalog(show: Show) -> bool:
    return show_source(show) in {SOURCE_TVMAZE, SOURCE_TMDB}


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
    return member_role(member) == ROLE_ADMIN


def require_club_admin(db: Session, club_id: int, user_id: int) -> Club:
    club = require_club_member(db, club_id, user_id)
    if not is_club_admin(db, club_id, user_id):
        raise HTTPException(status_code=403, detail="Apenas administradores podem fazer isso")
    return club


def require_club_perm(db: Session, club_id: int, user_id: int, perm: str) -> Club:
    club = require_club_member(db, club_id, user_id)
    member = club_membership(db, club_id, user_id)
    if not can(member, perm):
        raise HTTPException(status_code=403, detail="Você não tem permissão para isso")
    return club


def _count_members(db: Session, club_id: int) -> int:
    return db.scalar(select(func.count()).select_from(ClubMember).where(ClubMember.club_id == club_id)) or 0


def _count_role(db: Session, club_id: int, role: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ClubMember)
            .where(ClubMember.club_id == club_id, ClubMember.role == role)
        )
        or 0
    )


def admin_count(db: Session, club_id: int) -> int:
    return _count_role(db, club_id, ROLE_ADMIN)


def support_count(db: Session, club_id: int) -> int:
    return _count_role(db, club_id, ROLE_SUPPORT)


def parse_member_limit(raw: str | None) -> tuple[int | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, None
    if not text.isdigit() or int(text) < 1:
        return None, "O limite de membros precisa ser um número inteiro a partir de 1. Deixe vazio para ilimitado."
    return int(text), None


def _ensure_club_member(db: Session, club_id: int, user_id: int) -> ClubMember:
    existing = club_membership(db, club_id, user_id)
    if existing:
        return existing
    club = db.get(Club, club_id)
    if not club:
        raise HTTPException(status_code=404, detail="Clube não encontrado")
    if club.member_limit is not None and _count_members(db, club_id) >= club.member_limit:
        raise HTTPException(status_code=400, detail="Este clube está lotado")
    member = ClubMember(club_id=club_id, user_id=user_id, role=ROLE_MEMBER, support_perms="")
    db.add(member)
    db.flush()
    return member


def add_club_member(source: Session, club_id: int, user_id: int, *, clear_request: bool = False) -> None:
    write = exclusive_write_session(source)
    try:
        _ensure_club_member(write, club_id, user_id)
        if clear_request:
            clear_join_request(write, club_id, user_id)
        write.commit()
    except IntegrityError:
        write.rollback()
        if not club_membership(write, club_id, user_id):
            raise HTTPException(status_code=400, detail="Não foi possível entrar no clube")
        if clear_request:
            clear_join_request(write, club_id, user_id)
            write.commit()
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)


def apply_member_role(
    source: Session,
    club_id: int,
    actor_id: int,
    target_user_id: int,
    wanted: str,
    support_perm: list[str] | None = None,
) -> None:
    write = exclusive_write_session(source)
    try:
        require_club_admin(write, club_id, actor_id)
        club = write.get(Club, club_id)
        target = club_membership(write, club_id, target_user_id)
        if not club or not target:
            raise HTTPException(status_code=404, detail="Membro não encontrado")
        wanted = (wanted or "").strip().lower()
        if wanted not in ROLES:
            raise HTTPException(status_code=400, detail="Cargo inválido")
        current = member_role(target)
        if club.owner_id == target_user_id and wanted != ROLE_ADMIN:
            raise HTTPException(status_code=400, detail="O dono do clube não pode ser rebaixado")
        if wanted != ROLE_ADMIN and current == ROLE_ADMIN and admin_count(write, club_id) <= 1:
            raise HTTPException(status_code=400, detail="O clube precisa de pelo menos um administrador")
        if wanted == ROLE_ADMIN and current != ROLE_ADMIN and admin_count(write, club_id) >= MAX_ADMINS:
            raise HTTPException(status_code=400, detail="O clube já tem o máximo de 3 ADM")
        if wanted == ROLE_SUPPORT and current != ROLE_SUPPORT and support_count(write, club_id) >= MAX_SUPPORT:
            raise HTTPException(status_code=400, detail="O clube já tem o máximo de 7 SUB")
        set_member_role(target, wanted)
        if wanted == ROLE_SUPPORT:
            perms = support_perm if isinstance(support_perm, list) else [support_perm] if support_perm else []
            target.support_perms = dump_support_perms(perms)
        write.commit()
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)


def pending_join_request(db: Session, club_id: int, user_id: int) -> ClubJoinRequest | None:
    return db.scalar(
        select(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == user_id)
    )


def list_join_requests(db: Session, club_id: int) -> list[ClubJoinRequest]:
    return list(
        db.scalars(
            select(ClubJoinRequest)
            .options(selectinload(ClubJoinRequest.user))
            .where(ClubJoinRequest.club_id == club_id)
            .order_by(ClubJoinRequest.created_at)
        )
    )


def requested_club_ids(db: Session, user_id: int) -> set[int]:
    return set(db.scalars(select(ClubJoinRequest.club_id).where(ClubJoinRequest.user_id == user_id)))


def clear_join_request(db: Session, club_id: int, user_id: int) -> None:
    request = pending_join_request(db, club_id, user_id)
    if request:
        db.delete(request)


def create_join_request(db: Session, club: Club, user_id: int) -> ClubJoinRequest:
    if not club.is_closed:
        raise HTTPException(status_code=400, detail="Este clube é aberto")
    if club_membership(db, club.id, user_id):
        raise HTTPException(status_code=400, detail="Você já participa deste clube")
    existing = pending_join_request(db, club.id, user_id)
    if existing:
        return existing
    request = ClubJoinRequest(club_id=club.id, user_id=user_id)
    db.add(request)
    db.flush()
    return request


def accept_join_request(db: Session, club_id: int, user_id: int, actor_id: int) -> None:
    from app.roles import PERM_JOINS

    require_club_perm(db, club_id, actor_id, PERM_JOINS)
    write = exclusive_write_session(db)
    try:
        require_club_perm(write, club_id, actor_id, PERM_JOINS)
        request = pending_join_request(write, club_id, user_id)
        if not request:
            raise HTTPException(status_code=404, detail="Solicitação não encontrada")
        _ensure_club_member(write, club_id, user_id)
        write.delete(request)
        write.commit()
    except IntegrityError:
        write.rollback()
        request = pending_join_request(write, club_id, user_id)
        if club_membership(write, club_id, user_id) and request:
            write.delete(request)
            write.commit()
        elif not club_membership(write, club_id, user_id):
            raise HTTPException(status_code=400, detail="Não foi possível aceitar a solicitação")
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)


def reject_join_request(db: Session, club_id: int, user_id: int, actor_id: int) -> None:
    from app.roles import PERM_JOINS

    require_club_perm(db, club_id, actor_id, PERM_JOINS)
    request = pending_join_request(db, club_id, user_id)
    if not request:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    db.delete(request)


def leave_club(db: Session, club_id: int, user_id: int) -> str:
    club = require_club_member(db, club_id, user_id)
    member = club_membership(db, club_id, user_id)
    others = list(
        db.scalars(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id != user_id))
    )
    club_name = club.name
    was_admin = member_role(member) == ROLE_ADMIN
    clear_displayed_club(db, user_id, club_id)
    db.delete(member)
    if not others:
        db.execute(delete(ClubShowRating).where(ClubShowRating.club_id == club_id))
        db.execute(delete(ClubMessage).where(ClubMessage.club_id == club_id))
        db.execute(delete(ClubShow).where(ClubShow.club_id == club_id))
        db.execute(delete(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id))
        clear_tag_preferences(db, club_id)
        db.delete(club)
        db.commit()
        return f"Você saiu e o clube “{club_name}” foi encerrado."
    remaining_admins = [item for item in others if member_role(item) == ROLE_ADMIN]
    if was_admin and not remaining_admins:
        others[0].role = ROLE_ADMIN
        others[0].support_perms = ""
        remaining_admins = [others[0]]
    if club.owner_id == user_id:
        club.owner_id = remaining_admins[0].user_id if remaining_admins else others[0].user_id
    db.commit()
    return f"Você saiu do clube “{club_name}”."


def _apply_catalog_fields(db: Session, show: Show, show_data: dict) -> None:
    keep_if_empty = {
        "backdrop_url",
        "imdb_id",
        "tmdb_id",
        "image_url",
        "official_site",
        "summary",
        "premiered",
        "status",
    }
    for key, value in show_data.items():
        if key in {"tvmaze_id"}:
            continue
        if key == "genres":
            if value:
                show.genres = encode_genres(value)
            continue
        if key in keep_if_empty:
            if not value:
                continue
            if key in {"imdb_id", "tmdb_id"}:
                owner_id = db.scalar(select(Show.id).where(getattr(Show, key) == value))
                if owner_id is not None and owner_id != show.id:
                    print(
                        f"[watch-club] {key} {value} já pertence à obra {owner_id}; "
                        "identificador não foi alterado"
                    )
                    continue
            setattr(show, key, value)
            continue
        setattr(show, key, value)


async def upsert_show_from_tvmaze(db: Session, tvmaze_id: int) -> Show:
    show_data, seasons_data, episodes_data = await tvmaze.fetch_show_and_seasons(tvmaze_id)
    show = db.scalar(
        select(Show)
        .options(selectinload(Show.seasons), selectinload(Show.episodes))
        .where(Show.tvmaze_id == tvmaze_id)
    )
    if not show:
        show = Show(tvmaze_id=tvmaze_id)
        db.add(show)
    _apply_catalog_fields(db, show, show_data)
    db.flush()

    existing = {season.number: season for season in show.seasons}
    for payload in seasons_data:
        season = existing.get(payload["number"])
        if not season:
            season = Season(show_id=show.id, number=payload["number"])
            db.add(season)
            existing[payload["number"]] = season
        season.name = payload["name"]
        season.episode_count = payload["episode_count"]
        season.premiere_date = payload["premiere_date"]
        season.end_date = payload["end_date"]
        season.image_url = payload["image_url"]
    db.flush()

    existing_episodes = {episode.tvmaze_id: episode for episode in show.episodes}
    for payload in episodes_data:
        episode = existing_episodes.get(payload["tvmaze_id"])
        if not episode:
            episode = Episode(show_id=show.id, tvmaze_id=payload["tvmaze_id"])
            db.add(episode)
            existing_episodes[payload["tvmaze_id"]] = episode
        season = existing.get(payload["season_number"])
        episode.season_id = season.id if season is not None else None
        episode.season_number = payload["season_number"]
        episode.number = payload["number"]
        episode.name = payload["name"]
        episode.airdate = payload["airdate"]
        if payload.get("image_url"):
            episode.image_url = payload["image_url"]
    db.flush()
    return show


def _find_show_by_tmdb(db: Session, tmdb_id: int) -> Show | None:
    return db.scalar(
        select(Show)
        .options(selectinload(Show.seasons), selectinload(Show.episodes))
        .where(Show.tmdb_id == tmdb_id)
    )


def _find_show_by_imdb(db: Session, imdb_id: str) -> Show | None:
    return db.scalar(
        select(Show)
        .options(selectinload(Show.seasons), selectinload(Show.episodes))
        .where(Show.imdb_id == imdb_id)
    )


async def upsert_show_from_tmdb(db: Session, tmdb_id: int) -> Show:
    if tmdb_id <= 0:
        raise HTTPException(status_code=400, detail="Filme inválido")
    try:
        show_data = await tmdb.fetch_movie(tmdb_id)
    except TmdbUnavailable:
        raise HTTPException(status_code=400, detail="Não foi possível adicionar este filme agora.")
    show = _find_show_by_tmdb(db, tmdb_id)
    imdb_id = show_data.get("imdb_id")
    if show is None and imdb_id:
        by_imdb = _find_show_by_imdb(db, imdb_id)
        if by_imdb is not None:
            if by_imdb.tmdb_id and by_imdb.tmdb_id != tmdb_id:
                print(
                    f"[watch-club] IMDb {imdb_id} já ligado à obra {by_imdb.id} "
                    f"(tmdb_id={by_imdb.tmdb_id}); reusando sem alterar IDs"
                )
                show = by_imdb
            elif by_imdb.tvmaze_id > 0:
                print(
                    f"[watch-club] IMDb {imdb_id} já pertence à obra TVMaze {by_imdb.id}; "
                    "filme TMDB será criado sem copiar o IMDb"
                )
                show_data = dict(show_data)
                show_data["imdb_id"] = None
            else:
                show = by_imdb
    if show is None:
        show = Show(tvmaze_id=allocate_local_tvmaze_id(db), kind="filme")
        db.add(show)
    show.kind = "filme"
    _apply_catalog_fields(db, show, show_data)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = _find_show_by_tmdb(db, tmdb_id)
        if existing is None:
            raise HTTPException(status_code=400, detail="Não foi possível adicionar este filme agora.")
        show = existing
        _apply_catalog_fields(db, show, show_data)
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


def _link_show_to_club(db: Session, club: Club, show: Show, user_id: int) -> Show:
    link = db.scalar(select(ClubShow).where(ClubShow.club_id == club.id, ClubShow.show_id == show.id))
    if not link:
        db.add(ClubShow(club_id=club.id, show_id=show.id, added_by_id=user_id, watch_status=WATCHING))
    try:
        refresh_news(db, show)
    except Exception as exc:
        print(f"[watch-club] notícias indisponíveis para obra {show.id}: {exc.__class__.__name__}")
    db.commit()
    db.refresh(show)
    return show


async def add_show_to_club(db: Session, club: Club, tvmaze_id: int, user_id: int, kind: str | None = None) -> Show:
    show = await upsert_show_from_tvmaze(db, tvmaze_id)
    if kind:
        show.kind = valid_kind(kind)
    return _link_show_to_club(db, club, show, user_id)


async def add_tmdb_movie_to_club(db: Session, club: Club, tmdb_id: int, user_id: int) -> Show:
    show = await upsert_show_from_tmdb(db, tmdb_id)
    show.kind = "filme"
    return _link_show_to_club(db, club, show, user_id)


def add_manual_title(db: Session, club: Club, user_id: int, name: str, kind: str, image_url: str | None) -> Show:
    title = name.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Informe o nome do título")
    show = Show(
        tvmaze_id=allocate_local_tvmaze_id(db),
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


def allocate_local_tvmaze_id(db: Session) -> int:
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


def premiere_year(raw: str | None) -> str:
    text = (raw or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        if 1800 <= year <= 2100:
            return text[:4]
    return ""


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
        .options(selectinload(Show.seasons), selectinload(Show.episodes), selectinload(Show.news))
        .where(Show.id == show_id)
    )
    if not show:
        raise HTTPException(status_code=404, detail="Série não encontrada")
    return show
