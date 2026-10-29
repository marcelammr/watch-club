from __future__ import annotations

import httpx

from app import config as app_config
from app.services.tvmaze import _parse_imdb_id

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
POSTER_SIZE = "w342"
BACKDROP_SIZE = "w1280"
TIMEOUT = 20.0


class TmdbUnavailable(Exception):
    pass


def configured() -> bool:
    return bool((app_config.TMDB_ACCESS_TOKEN or "").strip())


def image_url(path: object, size: str = POSTER_SIZE) -> str | None:
    if not isinstance(path, str):
        return None
    text = path.strip()
    if not text.startswith("/") or ".." in text:
        return None
    return f"{TMDB_IMAGE_BASE}/{size}{text}"[:500]


def _token() -> str:
    return (app_config.TMDB_ACCESS_TOKEN or "").strip()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
    }


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _text(value: object, limit: int = 500) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:limit] if text else None


def _movie_hit(item: dict) -> dict | None:
    tmdb_id = _optional_int(item.get("id"))
    name = _text(item.get("title") or item.get("original_title"), 255)
    if tmdb_id is None or not name:
        return None
    premiered = _text(item.get("release_date"), 20)
    return {
        "provider": "tmdb",
        "external_id": tmdb_id,
        "tmdb_id": tmdb_id,
        "tvmaze_id": None,
        "name": name,
        "premiered": premiered,
        "kind": "filme",
        "image_url": image_url(item.get("poster_path"), POSTER_SIZE),
        "summary": _text(item.get("overview"), 4000),
    }


def _movie_detail(payload: dict) -> dict:
    tmdb_id = _optional_int(payload.get("id"))
    name = _text(payload.get("title") or payload.get("original_title"), 255)
    if tmdb_id is None or not name:
        raise TmdbUnavailable("Filme inválido")
    externals = payload.get("external_ids") if isinstance(payload.get("external_ids"), dict) else {}
    imdb_id = _parse_imdb_id(payload.get("imdb_id")) or _parse_imdb_id(externals.get("imdb_id"))
    genres = []
    for item in payload.get("genres") or []:
        if isinstance(item, dict) and _text(item.get("name"), 80):
            genres.append(_text(item.get("name"), 80))
    return {
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "name": name,
        "kind": "filme",
        "summary": _text(payload.get("overview"), 4000),
        "premiered": _text(payload.get("release_date"), 20),
        "image_url": image_url(payload.get("poster_path"), POSTER_SIZE),
        "backdrop_url": image_url(payload.get("backdrop_path"), BACKDROP_SIZE),
        "official_site": _text(payload.get("homepage"), 500),
        "genres": genres,
        "status": _text(payload.get("status"), 40),
    }


async def _get(path: str, params: dict | None = None) -> dict | list:
    if not configured():
        raise TmdbUnavailable("TMDB não configurado")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{TMDB_API}{path}", headers=_headers(), params=params or {})
    except httpx.TimeoutException as exc:
        raise TmdbUnavailable("timeout") from exc
    except httpx.HTTPError as exc:
        raise TmdbUnavailable("rede") from exc
    if response.status_code in {401, 403, 404, 429} or response.status_code >= 500:
        raise TmdbUnavailable(f"http {response.status_code}")
    if response.status_code >= 400:
        raise TmdbUnavailable(f"http {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise TmdbUnavailable("json") from exc


async def search_movies(query: str) -> list[dict]:
    if not configured():
        return []
    payload = await _get(
        "/search/movie",
        {
            "query": query,
            "language": "pt-BR",
            "region": "BR",
            "include_adult": "false",
        },
    )
    if not isinstance(payload, dict):
        raise TmdbUnavailable("json")
    results = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        hit = _movie_hit(item)
        if hit:
            results.append(hit)
    return results


async def fetch_movie(tmdb_id: int) -> dict:
    payload = await _get(
        f"/movie/{tmdb_id}",
        {
            "language": "pt-BR",
            "append_to_response": "external_ids",
        },
    )
    if not isinstance(payload, dict):
        raise TmdbUnavailable("json")
    return _movie_detail(payload)
