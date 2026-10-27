from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.db import SessionLocal, engine
from app.main import app
from app.models import ClubShow, Episode, Season, Show
from app.services.tvmaze import _parse_episodes
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
    } <= cols
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
        },
        {
            "tvmaze_id": 11,
            "season_number": 1,
            "number": 1,
            "name": "Pilot",
            "airdate": "2008-01-20",
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
    finally:
        db.close()
