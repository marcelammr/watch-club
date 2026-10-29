from __future__ import annotations

import asyncio
import re

import httpx

_IMDB_ID = re.compile(r"^tt\d{7,12}$")

TVMAZE = "https://api.tvmaze.com"


def _kind(type_name: str | None) -> str:
    text = (type_name or "").lower()
    if "anim" in text:
        return "animacao"
    if "movie" in text or "film" in text:
        return "filme"
    if any(token in text for token in ("talk", "reality", "variety", "award", "news", "game")):
        return "programa"
    return "serie"


def _image(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("original", "medium"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return None


def _parse_imdb_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().casefold()
    if not _IMDB_ID.match(text):
        return None
    return text[:20]


def _imdb_from_show(payload: dict) -> str | None:
    externals = payload.get("externals")
    if not isinstance(externals, dict):
        return None
    return _parse_imdb_id(externals.get("imdb"))


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = (
        value.replace("<p>", "")
        .replace("</p>", "\n")
        .replace("<b>", "")
        .replace("</b>", "")
        .replace("<i>", "")
        .replace("</i>", "")
    )
    return " ".join(text.split())


async def search_shows(query: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{TVMAZE}/search/shows", params={"q": query})
        response.raise_for_status()
        results = []
        for item in response.json():
            show = item.get("show") or {}
            results.append(
                {
                    "tvmaze_id": show.get("id"),
                    "name": show.get("name"),
                    "premiered": show.get("premiered"),
                    "status": show.get("status"),
                    "image_url": _image(show.get("image")),
                    "summary": _strip_html(show.get("summary")),
            "kind": _kind(show.get("type")),
                    "genres": [item for item in (show.get("genres") or []) if item],
                }
            )
        return results


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_episodes(payload: list | None) -> list[dict]:
    episodes = []
    for item in payload or []:
        tvmaze_id = _optional_int(item.get("id"))
        if tvmaze_id is None:
            continue
        airdate = (item.get("airdate") or "").strip() or None
        episodes.append(
            {
                "tvmaze_id": tvmaze_id,
                "season_number": _optional_int(item.get("season")) or 0,
                "number": _optional_int(item.get("number")),
                "name": (item.get("name") or "").strip()[:255],
                "airdate": airdate[:20] if airdate else None,
                "image_url": _image(item.get("image")),
            }
        )
    return episodes


def _pick_backdrop(payload) -> str | None:
    if not isinstance(payload, list):
        return None
    best_url = None
    best_size = (-1, -1)
    for item in payload:
        if not isinstance(item, dict) or item.get("type") != "background":
            continue
        resolutions = item.get("resolutions")
        if not isinstance(resolutions, dict):
            continue
        chosen = resolutions.get("original")
        if not isinstance(chosen, dict):
            chosen = resolutions.get("medium")
        if not isinstance(chosen, dict):
            continue
        url = chosen.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        size = (_optional_int(chosen.get("width")) or 0, _optional_int(chosen.get("height")) or 0)
        if best_url is None or size > best_size:
            best_url = url.strip()[:500]
            best_size = size
    return best_url


async def fetch_show_and_seasons(tvmaze_id: int) -> tuple[dict, list[dict], list[dict]]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        show_resp, seasons_resp, episodes_resp = await asyncio.gather(
            client.get(f"{TVMAZE}/shows/{tvmaze_id}"),
            client.get(f"{TVMAZE}/shows/{tvmaze_id}/seasons"),
            client.get(f"{TVMAZE}/shows/{tvmaze_id}/episodes"),
        )
        show_resp.raise_for_status()
        seasons_resp.raise_for_status()
        episodes_resp.raise_for_status()
        show = show_resp.json()
        show_data = {
            "tvmaze_id": show["id"],
            "name": show["name"],
            "summary": _strip_html(show.get("summary")),
            "status": show.get("status"),
            "premiered": show.get("premiered"),
            "image_url": _image(show.get("image")),
            "official_site": show.get("officialSite"),
            "kind": _kind(show.get("type")),
            "genres": [item for item in (show.get("genres") or []) if item],
            "backdrop_url": None,
            "imdb_id": _imdb_from_show(show),
        }
        seasons = []
        for season in seasons_resp.json():
            seasons.append(
                {
                    "number": season.get("number") or 0,
                    "name": season.get("name"),
                    "episode_count": season.get("episodeOrder"),
                    "premiere_date": season.get("premiereDate"),
                    "end_date": season.get("endDate"),
                    "image_url": _image(season.get("image")),
                }
            )
        try:
            images_resp = await client.get(f"{TVMAZE}/shows/{tvmaze_id}/images")
            images_resp.raise_for_status()
            show_data["backdrop_url"] = _pick_backdrop(images_resp.json())
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            print(f"[watch-club] TVMaze images indisponível para {tvmaze_id}: {exc.__class__.__name__}")
        return show_data, seasons, _parse_episodes(episodes_resp.json())


async def fetch_show_genres(tvmaze_id: int) -> list[str]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{TVMAZE}/shows/{tvmaze_id}")
        response.raise_for_status()
        show = response.json()
        return [item for item in (show.get("genres") or []) if item]
