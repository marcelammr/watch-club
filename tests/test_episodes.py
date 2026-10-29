import asyncio
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.db import SessionLocal, engine
from app.main import app
from app.models import ClubShow, Episode, Season, Show
from app.services.tvmaze import _parse_episodes, _pick_backdrop, fetch_show_and_seasons
from tests.test_app import register_active

client = TestClient(app)

def _show_data(tvmaze_id: int, name: str = "Breaking Bad") -> dict:
    return {
        "tvmaze_id": tvmaze_id,
        "name": name,
        "summary": "Um professor de química.",
        "status": "Ended",
        "premiered": "2008-01-20",
        "image_url": "https://example.com/bb.jpg",
        "official_site": None,
        "kind": "serie",
        "genres": ["Drama"],
    }

SEASONS = [
    {
        "number": 1,
        "name": "Season 1",
        "episode_count": 7,
        "premiere_date": "2008-01-20",
        "end_date": "2008-03-09",
        "image_url": None,
    }
]


def _create_club(http: TestClient, name: str) -> int:
    created = http.post("/clubs", data={"name": name}, follow_redirects=False)
    return int(created.headers["location"].rsplit("/", 1)[-1])


def _add_tvmaze_show(http: TestClient, club_id: int, fake: tuple) -> None:
    tvmaze_id = fake[0]["tvmaze_id"]
    with patch("app.catalog.tvmaze.fetch_show_and_seasons", AsyncMock(return_value=fake)):
        with patch("app.catalog.refresh_news"):
            added = http.post(
                f"/clubs/{club_id}/shows",
                data={"tvmaze_id": str(tvmaze_id)},
                follow_redirects=False,
            )
    assert added.status_code == 303


def test_episode_schema_is_catalog_only():
    inspector = inspect(engine)
    assert "episodes" in inspector.get_table_names()
    cols = {column["name"] for column in inspector.get_columns("episodes")}
    assert {
        "id",
        "show_id",
        "season_id",
        "tvmaze_id",
        "season_number",
        "number",
        "name",
        "airdate",
        "image_url",
    } <= cols
    show_cols = {column["name"] for column in inspector.get_columns("shows")}
    assert "backdrop_url" in show_cols
    assert "club_id" not in cols
    assert "watched" not in cols
    assert "watch_status" not in cols


def test_parse_episodes_skips_missing_ids_and_keeps_null_numbers():
    parsed = _parse_episodes(
        [
            {"id": None, "season": 1, "number": 1, "name": "Sem id"},
            {"id": 10, "season": None, "number": None, "name": "  Special  ", "airdate": ""},
            {"id": "11", "season": "1", "number": "1", "name": "Pilot", "airdate": "2008-01-20"},
        ]
    )
    assert parsed == [
        {
            "tvmaze_id": 10,
            "season_number": 0,
            "number": None,
            "name": "Special",
            "airdate": None,
            "image_url": None,
        },
        {
            "tvmaze_id": 11,
            "season_number": 1,
            "number": 1,
            "name": "Pilot",
            "airdate": "2008-01-20",
            "image_url": None,
        },
    ]


def test_upsert_persists_episodes_linked_to_show_and_season():
    owner = TestClient(app)
    register_active(owner, "ep_admin", "ep.admin@example.com")
    club_id = _create_club(owner, "Sala Episodios")
    episodes = [
        {
            "tvmaze_id": 1001,
            "season_number": 1,
            "number": 1,
            "name": "Pilot",
            "airdate": "2008-01-20",
        },
        {
            "tvmaze_id": 1002,
            "season_number": 0,
            "number": None,
            "name": "Unaired special",
            "airdate": None,
        },
        {
            "tvmaze_id": 1003,
            "season_number": 9,
            "number": 1,
            "name": "Orphan season",
            "airdate": "2010-01-01",
        },
    ]
    _add_tvmaze_show(owner, club_id, (_show_data(91001), SEASONS, episodes))

    db = SessionLocal()
    try:
        show = db.scalar(select(Show).where(Show.tvmaze_id == 91001))
        season = db.scalar(select(Season).where(Season.show_id == show.id, Season.number == 1))
        rows = db.scalars(select(Episode).where(Episode.show_id == show.id).order_by(Episode.tvmaze_id)).all()
        assert len(rows) == 3
        pilot = rows[0]
        assert pilot.tvmaze_id == 1001
        assert pilot.season_id == season.id
        assert pilot.season_number == 1
        assert pilot.number == 1
        assert pilot.name == "Pilot"
        assert pilot.airdate == "2008-01-20"
        special = rows[1]
        assert special.number is None
        assert special.season_number == 0
        assert special.season_id is None
        orphan = rows[2]
        assert orphan.season_number == 9
        assert orphan.season_id is None
        assert orphan.number == 1
    finally:
        db.close()


def test_episode_upsert_is_idempotent_and_keeps_vanished_rows():
    owner = TestClient(app)
    register_active(owner, "ep_refresh", "ep.refresh@example.com")
    club_id = _create_club(owner, "Sala Refresh")
    first = [
        {"tvmaze_id": 2001, "season_number": 1, "number": 1, "name": "Pilot", "airdate": "2008-01-20"},
        {"tvmaze_id": 2002, "season_number": 1, "number": 2, "name": "Cat's in the Bag...", "airdate": "2008-01-27"},
    ]
    payload = _show_data(91002, "Better Call Saul")
    _add_tvmaze_show(owner, club_id, (payload, SEASONS, first))

    db = SessionLocal()
    try:
        show_id = db.scalar(select(Show.id).where(Show.tvmaze_id == 91002))
        first_ids = db.scalars(select(Episode.id).where(Episode.show_id == show_id).order_by(Episode.tvmaze_id)).all()
    finally:
        db.close()

    updated = [
        {"tvmaze_id": 2001, "season_number": 1, "number": 1, "name": "Pilot (updated)", "airdate": "2008-01-21"},
    ]
    with patch("app.catalog.tvmaze.fetch_show_and_seasons", AsyncMock(return_value=(payload, SEASONS, updated))):
        with patch("app.catalog.refresh_news"):
            refreshed = owner.post(f"/clubs/{club_id}/shows/{show_id}/refresh", follow_redirects=False)
    assert refreshed.status_code == 303

    db = SessionLocal()
    try:
        rows = db.scalars(select(Episode).where(Episode.show_id == show_id).order_by(Episode.tvmaze_id)).all()
        assert [row.id for row in rows] == first_ids
        assert rows[0].name == "Pilot (updated)"
        assert rows[0].airdate == "2008-01-21"
        assert rows[1].name == "Cat's in the Bag..."
        assert len(rows) == 2
    finally:
        db.close()


def test_manual_title_has_no_episode_catalog():
    owner = TestClient(app)
    register_active(owner, "ep_manual", "ep.manual@example.com")
    club_id = _create_club(owner, "Sala Manual")
    added = owner.post(
        f"/clubs/{club_id}/titulos",
        data={"name": "Título Manual Sem Catálogo", "kind": "filme"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    db = SessionLocal()
    try:
        show = db.scalar(
            select(Show)
            .join(ClubShow)
            .where(ClubShow.club_id == club_id, Show.name == "Título Manual Sem Catálogo")
        )
        assert show.tvmaze_id < 0
        count = db.scalar(select(Episode.id).where(Episode.show_id == show.id))
        assert count is None
    finally:
        db.close()


def test_refresh_skips_episode_fetch_for_manual_titles():
    owner = TestClient(app)
    register_active(owner, "ep_manual_refresh", "ep.manual.refresh@example.com")
    club_id = _create_club(owner, "Sala Manual Refresh")
    owner.post(
        f"/clubs/{club_id}/titulos",
        data={"name": "Sessão Extra Sem Catálogo", "kind": "serie"},
        follow_redirects=False,
    )
    db = SessionLocal()
    try:
        show_id = db.scalar(
            select(Show.id)
            .join(ClubShow)
            .where(ClubShow.club_id == club_id, Show.name == "Sessão Extra Sem Catálogo")
        )
    finally:
        db.close()
    with patch("app.catalog.tvmaze.fetch_show_and_seasons") as fetch:
        refreshed = owner.post(f"/clubs/{club_id}/shows/{show_id}/refresh", follow_redirects=False)
    assert refreshed.status_code == 303
    fetch.assert_not_called()
    db = SessionLocal()
    try:
        assert db.scalar(select(Episode.id).where(Episode.show_id == show_id)) is None
        assert db.get(Show, show_id).backdrop_url is None
    finally:
        db.close()


def test_parse_episodes_reads_original_then_medium_image():
    parsed = _parse_episodes(
        [
            {
                "id": 1,
                "season": 1,
                "number": 1,
                "name": "Pilot",
                "image": {
                    "medium": "https://example.com/med.jpg",
                    "original": "https://example.com/orig.jpg",
                },
            },
            {
                "id": 2,
                "season": 1,
                "number": 2,
                "name": "Só medium",
                "image": {"medium": "https://example.com/only-med.jpg", "original": None},
            },
            {"id": 3, "season": 1, "number": 3, "name": "Sem imagem", "image": None},
        ]
    )
    assert parsed[0]["image_url"] == "https://example.com/orig.jpg"
    assert parsed[1]["image_url"] == "https://example.com/only-med.jpg"
    assert parsed[2]["image_url"] is None


def test_pick_backdrop_prefers_widest_background_and_ignores_other_types():
    chosen = _pick_backdrop(
        [
            {"type": "poster", "resolutions": {"original": {"url": "https://example.com/poster.jpg", "width": 2000, "height": 3000}}},
            {"type": "banner", "resolutions": {"original": {"url": "https://example.com/banner.jpg", "width": 1500, "height": 500}}},
            {"type": "background", "resolutions": {"original": {"url": "https://example.com/bg-small.jpg", "width": 534, "height": 300}}},
            {"type": "background", "resolutions": {"original": {"url": "https://example.com/bg-wide.jpg", "width": 1920, "height": 1080}}},
            {"type": "typography", "resolutions": {"original": {"url": "https://example.com/logo.png", "width": 800, "height": 200}}},
            {"type": "background", "resolutions": {"original": {"url": "", "width": 3840, "height": 2160}}},
            {"type": "background", "resolutions": None},
            "broken",
        ]
    )
    assert chosen == "https://example.com/bg-wide.jpg"
    assert _pick_backdrop([]) is None
    assert _pick_backdrop(None) is None
    assert _pick_backdrop({"type": "background"}) is None


def _http_json(url: str, payload, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", url))


class _FakeTVmaze:
    def __init__(self, images=None, images_status: int = 200, fail_images: bool = False):
        self.images = images if images is not None else []
        self.images_status = images_status
        self.fail_images = fail_images
        self.requested = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        self.requested.append(str(url))
        if str(url).endswith("/images"):
            if self.fail_images:
                raise httpx.ConnectError("offline")
            return _http_json(url, self.images, self.images_status)
        if str(url).endswith("/seasons"):
            return _http_json(url, [])
        if str(url).endswith("/episodes"):
            return _http_json(
                url,
                [
                    {
                        "id": 77,
                        "season": 1,
                        "number": 1,
                        "name": "Pilot",
                        "airdate": "2008-01-20",
                        "image": {"original": "https://example.com/ep.jpg"},
                    }
                ],
            )
        return _http_json(
            url,
            {
                "id": 169,
                "name": "Breaking Bad",
                "summary": None,
                "status": "Ended",
                "premiered": "2008-01-20",
                "image": {"original": "https://example.com/poster.jpg"},
                "officialSite": None,
                "type": "Scripted",
                "genres": ["Drama"],
            },
        )


def test_fetch_show_picks_backdrop_and_survives_images_failure():
    ok_client = _FakeTVmaze(
        images=[
            {"type": "background", "resolutions": {"original": {"url": "https://example.com/bg.jpg", "width": 1280, "height": 720}}},
        ]
    )
    with patch("app.services.tvmaze.httpx.AsyncClient", return_value=ok_client):
        show, _seasons, episodes = asyncio.run(fetch_show_and_seasons(169))
    assert show["backdrop_url"] == "https://example.com/bg.jpg"
    assert episodes[0]["image_url"] == "https://example.com/ep.jpg"
    assert any(url.endswith("/images") for url in ok_client.requested)

    failed = _FakeTVmaze(fail_images=True)
    with patch("app.services.tvmaze.httpx.AsyncClient", return_value=failed):
        show, _seasons, episodes = asyncio.run(fetch_show_and_seasons(169))
    assert show["name"] == "Breaking Bad"
    assert show["backdrop_url"] is None
    assert episodes[0]["name"] == "Pilot"


def test_new_tvmaze_title_stores_backdrop_and_episode_image():
    owner = TestClient(app)
    register_active(owner, "img_new", "img.new@example.com")
    club_id = _create_club(owner, "Sala Imagens Nova")
    payload = _show_data(93001)
    payload["backdrop_url"] = "https://example.com/hero.jpg"
    episodes = [
        {
            "tvmaze_id": 3001,
            "season_number": 1,
            "number": 1,
            "name": "Pilot",
            "airdate": "2008-01-20",
            "image_url": "https://example.com/still.jpg",
        },
        {
            "tvmaze_id": 3002,
            "season_number": 1,
            "number": 2,
            "name": "Sem still",
            "airdate": "2008-01-27",
            "image_url": None,
        },
    ]
    _add_tvmaze_show(owner, club_id, (payload, SEASONS, episodes))
    db = SessionLocal()
    try:
        show = db.scalar(select(Show).where(Show.tvmaze_id == 93001))
        assert show.backdrop_url == "https://example.com/hero.jpg"
        rows = db.scalars(select(Episode).where(Episode.show_id == show.id).order_by(Episode.tvmaze_id)).all()
        assert rows[0].image_url == "https://example.com/still.jpg"
        assert rows[1].image_url is None
    finally:
        db.close()


def test_refresh_fills_images_and_keeps_them_when_payload_has_none():
    owner = TestClient(app)
    register_active(owner, "img_keep", "img.keep@example.com")
    club_id = _create_club(owner, "Sala Imagens Keep")
    payload = _show_data(93002)
    first = [
        {"tvmaze_id": 4001, "season_number": 1, "number": 1, "name": "Pilot", "airdate": "2008-01-20"},
    ]
    _add_tvmaze_show(owner, club_id, (payload, SEASONS, first))
    db = SessionLocal()
    try:
        show = db.scalar(select(Show).where(Show.tvmaze_id == 93002))
        show_id = show.id
        assert show.backdrop_url is None
        assert db.scalar(select(Episode).where(Episode.tvmaze_id == 4001)).image_url is None
    finally:
        db.close()
    before = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert "show-hero-backdrop" not in before.text

    filled = dict(payload)
    filled["backdrop_url"] = "https://example.com/keep-hero.jpg"
    with patch(
        "app.catalog.tvmaze.fetch_show_and_seasons",
        AsyncMock(
            return_value=(
                filled,
                SEASONS,
                [
                    {
                        "tvmaze_id": 4001,
                        "season_number": 1,
                        "number": 1,
                        "name": "Pilot",
                        "airdate": "2008-01-20",
                        "image_url": "https://example.com/keep-still.jpg",
                    }
                ],
            )
        ),
    ):
        with patch("app.catalog.refresh_news"):
            assert owner.post(f"/clubs/{club_id}/shows/{show_id}/refresh", follow_redirects=False).status_code == 303

    empty = dict(payload)
    empty["backdrop_url"] = None
    with patch(
        "app.catalog.tvmaze.fetch_show_and_seasons",
        AsyncMock(
            return_value=(
                empty,
                SEASONS,
                [
                    {
                        "tvmaze_id": 4001,
                        "season_number": 1,
                        "number": 1,
                        "name": "Pilot",
                        "airdate": "2008-01-20",
                        "image_url": None,
                    }
                ],
            )
        ),
    ):
        with patch("app.catalog.refresh_news"):
            assert owner.post(f"/clubs/{club_id}/shows/{show_id}/refresh", follow_redirects=False).status_code == 303

    db = SessionLocal()
    try:
        show = db.get(Show, show_id)
        episode = db.scalar(select(Episode).where(Episode.tvmaze_id == 4001))
        assert show.backdrop_url == "https://example.com/keep-hero.jpg"
        assert episode.image_url == "https://example.com/keep-still.jpg"
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert 'class="show-hero-backdrop"' in page.text
    assert "https://example.com/keep-hero.jpg" in page.text
