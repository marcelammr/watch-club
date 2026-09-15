from __future__ import annotations

import asyncio

import httpx

TVMAZE = "https://api.tvmaze.com"


def _image(payload: dict | None) -> str | None:
    if not payload:
        return None
    return payload.get("original") or payload.get("medium")


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
                }
            )
        return results


async def fetch_show_and_seasons(tvmaze_id: int) -> tuple[dict, list[dict]]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        show_resp, seasons_resp = await asyncio.gather(
            client.get(f"{TVMAZE}/shows/{tvmaze_id}"),
            client.get(f"{TVMAZE}/shows/{tvmaze_id}/seasons"),
        )
        show_resp.raise_for_status()
        seasons_resp.raise_for_status()
        show = show_resp.json()
        show_data = {
            "tvmaze_id": show["id"],
            "name": show["name"],
            "summary": _strip_html(show.get("summary")),
            "status": show.get("status"),
            "premiered": show.get("premiered"),
            "image_url": _image(show.get("image")),
            "official_site": show.get("officialSite"),
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
        return show_data, seasons
