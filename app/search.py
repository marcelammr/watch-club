from __future__ import annotations

import asyncio
import re
import unicodedata

from app.services import tmdb, tvmaze

SEARCH_MIN_CHARS = 2
SEARCH_RESULT_LIMIT = 20
_SPACES = re.compile(r"\s+")


class CatalogSearchError(Exception):
    pass


def normalize_search_query(raw: str | None) -> str:
    return _SPACES.sub(" ", (raw or "").strip())


def fold_search_text(raw: str | None) -> str:
    text = normalize_search_query(raw)
    stripped = "".join(
        char for char in unicodedata.normalize("NFKD", text) if unicodedata.category(char) != "Mn"
    )
    return stripped.casefold()


def search_ready(raw: str | None) -> bool:
    return len(fold_search_text(raw)) >= SEARCH_MIN_CHARS


def _rank_tier(name: str | None, query_folded: str) -> int:
    folded = fold_search_text(name)
    if folded == query_folded:
        return 0
    if folded.startswith(query_folded):
        return 1
    if query_folded in folded:
        return 2
    return 3


def rank_search_results(results: list[dict], query: str | None) -> list[dict]:
    folded = fold_search_text(query)
    if not folded:
        return list(results)
    ranked = sorted(
        enumerate(results),
        key=lambda pair: (_rank_tier(pair[1].get("name"), folded), pair[0]),
    )
    return [item for _index, item in ranked]


def _as_tvmaze_hit(item: dict) -> dict:
    tvmaze_id = item.get("tvmaze_id")
    return {
        "provider": "tvmaze",
        "external_id": tvmaze_id,
        "tvmaze_id": tvmaze_id,
        "tmdb_id": None,
        "name": item.get("name"),
        "premiered": item.get("premiered"),
        "kind": item.get("kind") or "serie",
        "image_url": item.get("image_url"),
        "summary": item.get("summary"),
        "status": item.get("status"),
        "genres": item.get("genres") or [],
    }


async def _collect(coro):
    try:
        return await coro, True
    except Exception:
        return [], False


async def search_catalog(query: str) -> list[dict]:
    tvmaze_task = tvmaze.search_shows(query)
    tmdb_enabled = tmdb.configured()
    movie_task = tmdb.search_movies(query) if tmdb_enabled else None
    if movie_task is None:
        (tv_rows, tv_ok), (movie_rows, movie_ok) = await _collect(tvmaze_task), ([], True)
    else:
        (tv_rows, tv_ok), (movie_rows, movie_ok) = await asyncio.gather(
            _collect(tvmaze_task),
            _collect(movie_task),
        )
    if not tv_ok and not movie_ok:
        raise CatalogSearchError
    if not tv_ok and not tmdb_enabled:
        raise CatalogSearchError
    merged = [_as_tvmaze_hit(item) for item in tv_rows] + list(movie_rows)
    return rank_search_results(merged, query)[:SEARCH_RESULT_LIMIT]
