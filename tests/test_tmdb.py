import asyncio
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.main import app
from app.models import ClubShow, Episode, Season, Show
from app.services.tmdb import TmdbUnavailable, fetch_movie, image_url, search_movies
from tests.test_app import register_active

client = TestClient(app)


def _http_json(url: str, payload, status: int = 200, text: str | None = None) -> httpx.Response:
    request = httpx.Request("GET", url)
    if text is not None:
        return httpx.Response(status, text=text, request=request)
    return httpx.Response(status, json=payload, request=request)


class _FakeTmdb:
    def __init__(self, status: int = 200, payload=None, fail: str | None = None):
        self.status = status
        self.payload = payload if payload is not None else {"results": []}
        self.fail = fail
        self.requested = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        self.requested.append({"url": str(url), "headers": kwargs.get("headers") or {}, "params": kwargs.get("params") or {}})
        if self.fail == "timeout":
            raise httpx.TimeoutException("timeout")
        if self.fail == "network":
            raise httpx.ConnectError("offline")
        if self.fail == "json":
            return _http_json(url, None, self.status, text="{not-json")
        return _http_json(url, self.payload, self.status)


def _movie_search_hit():
    return {
        "id": 120,
        "title": "O Senhor dos Anéis: A Sociedade do Anel",
        "original_title": "The Lord of the Rings: The Fellowship of the Ring",
        "release_date": "2001-12-19",
        "overview": "Uma jornada.",
        "poster_path": "/lotr.jpg",
        "backdrop_path": "/lotr-wide.jpg",
        "popularity": 99.1,
    }


def _movie_detail(**extra):
    payload = {
        "id": 120,
        "title": "O Senhor dos Anéis: A Sociedade do Anel",
        "original_title": "The Lord of the Rings: The Fellowship of the Ring",
        "overview": "Uma jornada.",
        "release_date": "2001-12-19",
        "poster_path": "/lotr.jpg",
        "backdrop_path": "/lotr-wide.jpg",
        "homepage": "https://www.lordoftherings.net/",
        "status": "Released",
        "imdb_id": "tt0120737",
        "genres": [{"id": 12, "name": "Aventura"}, {"id": 14, "name": "Fantasia"}],
        "external_ids": {"imdb_id": "tt0120737"},
    }
    payload.update(extra)
    return payload


def _parsed_movie(**extra) -> dict:
    from app.services.tmdb import _movie_detail as parse_detail

    return parse_detail(_movie_detail(**extra))


def _create_club(http: TestClient, name: str) -> int:
    created = http.post("/clubs", data={"name": name}, follow_redirects=False)
    return int(created.headers["location"].rsplit("/", 1)[-1])


def test_tmdb_image_url_and_optional_fields():
    assert image_url("/abc.jpg") == "https://image.tmdb.org/t/p/w342/abc.jpg"
    assert image_url("/abc.jpg", "w1280") == "https://image.tmdb.org/t/p/w1280/abc.jpg"
    assert image_url(None) is None
    assert image_url("https://evil.example/x.jpg") is None
    assert image_url("../secret") is None


def test_search_movies_sends_bearer_language_region_and_parses():
    fake = _FakeTmdb(payload={"results": [_movie_search_hit(), {"id": None, "title": "Ignorado"}]})
    with patch("app.services.tmdb.app_config.TMDB_ACCESS_TOKEN", "test-token"):
        with patch("app.services.tmdb.httpx.AsyncClient", return_value=fake):
            rows = asyncio.run(search_movies("Senhor dos Aneis"))
    assert rows[0]["name"] == "O Senhor dos Anéis: A Sociedade do Anel"
    assert rows[0]["kind"] == "filme"
    assert rows[0]["provider"] == "tmdb"
    assert rows[0]["external_id"] == 120
    assert rows[0]["premiered"] == "2001-12-19"
    assert rows[0]["image_url"].endswith("/w342/lotr.jpg")
    request = fake.requested[0]
    assert request["headers"]["Authorization"] == "Bearer test-token"
    assert "test-token" not in str(rows)
    assert request["params"]["language"] == "pt-BR"
    assert request["params"]["region"] == "BR"
    assert request["params"]["include_adult"] == "false"
    assert "/search/movie" in request["url"]


def test_search_movies_without_token_is_empty():
    with patch("app.services.tmdb.app_config.TMDB_ACCESS_TOKEN", ""):
        with patch("app.services.tmdb.httpx.AsyncClient") as mocked:
            rows = asyncio.run(search_movies("Hobbit"))
    assert rows == []
    mocked.assert_not_called()


def test_fetch_movie_parses_details_and_missing_optionals():
    fake = _FakeTmdb(payload=_movie_detail())
    with patch("app.services.tmdb.app_config.TMDB_ACCESS_TOKEN", "test-token"):
        with patch("app.services.tmdb.httpx.AsyncClient", return_value=fake):
            movie = asyncio.run(fetch_movie(120))
    assert movie["tmdb_id"] == 120
    assert movie["imdb_id"] == "tt0120737"
    assert movie["kind"] == "filme"
    assert movie["genres"] == ["Aventura", "Fantasia"]
    assert movie["official_site"] == "https://www.lordoftherings.net/"
    assert movie["image_url"].endswith("/w342/lotr.jpg")
    assert movie["backdrop_url"].endswith("/w1280/lotr-wide.jpg")
    assert fake.requested[0]["params"]["language"] == "pt-BR"
    assert fake.requested[0]["params"]["append_to_response"] == "external_ids"

    empty = _FakeTmdb(
        payload=_movie_detail(
            overview=None,
            homepage="",
            imdb_id=None,
            external_ids={},
            genres=None,
            poster_path=None,
            backdrop_path=None,
            release_date="",
        )
    )
    with patch("app.services.tmdb.app_config.TMDB_ACCESS_TOKEN", "test-token"):
        with patch("app.services.tmdb.httpx.AsyncClient", return_value=empty):
            bare = asyncio.run(fetch_movie(120))
    assert bare["summary"] is None
    assert bare["imdb_id"] is None
    assert bare["official_site"] is None
    assert bare["image_url"] is None
    assert bare["backdrop_url"] is None
    assert bare["genres"] == []
    assert bare["premiered"] is None


def test_tmdb_http_failures():
    for status in (401, 403, 429, 500):
        fake = _FakeTmdb(status=status, payload={"status_message": "nope"})
        with patch("app.services.tmdb.app_config.TMDB_ACCESS_TOKEN", "test-token"):
            with patch("app.services.tmdb.httpx.AsyncClient", return_value=fake):
                try:
                    asyncio.run(search_movies("Hobbit"))
                    raise AssertionError(f"expected failure for {status}")
                except TmdbUnavailable:
                    pass
    for fail in ("timeout", "network", "json"):
        fake = _FakeTmdb(fail=fail)
        with patch("app.services.tmdb.app_config.TMDB_ACCESS_TOKEN", "test-token"):
            with patch("app.services.tmdb.httpx.AsyncClient", return_value=fake):
                try:
                    asyncio.run(search_movies("Hobbit"))
                    raise AssertionError(f"expected failure for {fail}")
                except TmdbUnavailable:
                    pass


def _add_movie(http: TestClient, club_id: int, detail: dict):
    with patch("app.catalog.tmdb.fetch_movie", AsyncMock(return_value=detail)):
        with patch("app.catalog.refresh_news"):
            added = http.post(
                f"/clubs/{club_id}/shows",
                data={"provider": "tmdb", "external_id": str(detail["tmdb_id"]), "kind": "serie"},
                follow_redirects=False,
            )
    assert added.status_code == 303
    return added


def test_add_tmdb_movie_persists_catalog_without_episodes():
    owner = TestClient(app)
    register_active(owner, "tmdb_new", "tmdb.new@example.com")
    club_id = _create_club(owner, "Sala Filme")
    _add_movie(owner, club_id, _parsed_movie(id=20120, imdb_id="tt2012001", external_ids={"imdb_id": "tt2012001"}))
    db = SessionLocal()
    try:
        show = db.scalar(
            select(Show).options(selectinload(Show.seasons), selectinload(Show.episodes)).where(Show.tmdb_id == 20120)
        )
        assert show is not None
        assert show.kind == "filme"
        assert show.imdb_id == "tt2012001"
        assert show.tvmaze_id < 0
        assert show.image_url.endswith("/w342/lotr.jpg")
        assert show.backdrop_url.endswith("/w1280/lotr-wide.jpg")
        assert "Aventura" in show.genres
        assert show.seasons == []
        assert show.episodes == []
        assert db.scalar(select(Season.id).where(Season.show_id == show.id)) is None
        assert db.scalar(select(Episode.id).where(Episode.show_id == show.id)) is None
        show_id = show.id
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert page.status_code == 200
    assert "O Senhor dos Anéis: A Sociedade do Anel" in page.text
    assert "show-episodes" not in page.text
    assert "Atualizar informações" in page.text
    assert "show-refresh" in page.text
    assert f'id="show-menu-{show_id}"' not in page.text
    assert "2001" in page.text
    assert "Aventura" in page.text
    about = owner.get("/sobre")
    assert about.status_code == 200
    assert "This product uses the TMDB API but is not endorsed or certified by TMDB." in about.text
    assert "tmdb-logo" in about.text


def test_tmdb_dedupes_by_tmdb_id_and_second_club():
    owner = TestClient(app)
    register_active(owner, "tmdb_dup", "tmdb.dup@example.com")
    club_a = _create_club(owner, "Sala A")
    club_b = _create_club(owner, "Sala B")
    detail = _parsed_movie(id=20121, imdb_id="tt2012101", external_ids={"imdb_id": "tt2012101"})
    _add_movie(owner, club_a, detail)
    _add_movie(owner, club_a, detail)
    _add_movie(owner, club_b, detail)
    db = SessionLocal()
    try:
        shows = list(db.scalars(select(Show).where(Show.tmdb_id == 20121)))
        assert len(shows) == 1
        links = list(db.scalars(select(ClubShow).where(ClubShow.show_id == shows[0].id)))
        assert {link.club_id for link in links} == {club_a, club_b}
    finally:
        db.close()


def test_tmdb_reuses_imdb_and_skips_conflicting_ids():
    owner = TestClient(app)
    register_active(owner, "tmdb_imdb", "tmdb.imdb@example.com")
    club_id = _create_club(owner, "Sala Imdb Filme")
    db = SessionLocal()
    try:
        leftover = Show(tvmaze_id=-95001, name="Rascunho", kind="outro", imdb_id="tt2012201")
        db.add(leftover)
        db.commit()
        leftover_id = leftover.id
    finally:
        db.close()
    _add_movie(owner, club_id, _parsed_movie(id=20122, imdb_id="tt2012201", external_ids={"imdb_id": "tt2012201"}))
    db = SessionLocal()
    try:
        show = db.get(Show, leftover_id)
        assert show.tmdb_id == 20122
        assert show.kind == "filme"
        assert show.name.startswith("O Senhor dos Anéis")
        assert db.scalar(select(Show.id).where(Show.tmdb_id == 20122)) == leftover_id
    finally:
        db.close()

    other = TestClient(app)
    register_active(other, "tmdb_series", "tmdb.series@example.com")
    series_club = _create_club(other, "Sala Serie Imdb")
    db = SessionLocal()
    try:
        series = Show(tvmaze_id=95002, name="Série Com IMDb", kind="serie", imdb_id="tt2012301")
        db.add(series)
        db.commit()
        series_id = series.id
    finally:
        db.close()
    conflict = _parsed_movie(id=20123, imdb_id="tt2012301", external_ids={"imdb_id": "tt2012301"}, title="Filme Novo")
    with patch("app.catalog.tmdb.fetch_movie", AsyncMock(return_value=conflict)):
        with patch("app.catalog.refresh_news"):
            added = other.post(
                f"/clubs/{series_club}/shows",
                data={"provider": "tmdb", "external_id": "20123"},
                follow_redirects=False,
            )
    assert added.status_code == 303
    db = SessionLocal()
    try:
        series = db.get(Show, series_id)
        movie = db.scalar(select(Show).where(Show.tmdb_id == 20123))
        assert series.tmdb_id is None
        assert series.imdb_id == "tt2012301"
        assert movie is not None
        assert movie.id != series_id
        assert movie.imdb_id is None
        assert movie.kind == "filme"
    finally:
        db.close()


def test_refresh_routes_by_source():
    owner = TestClient(app)
    register_active(owner, "tmdb_refresh", "tmdb.refresh@example.com")
    club_id = _create_club(owner, "Sala Refresh Mix")
    _add_movie(owner, club_id, _parsed_movie(id=20124, imdb_id="tt2012401", external_ids={"imdb_id": "tt2012401"}))
    db = SessionLocal()
    try:
        from app.models import User

        movie_id = db.scalar(select(Show.id).where(Show.tmdb_id == 20124))
        user_id = db.scalar(select(User.id).where(User.username == "tmdb_refresh"))
        manual = Show(tvmaze_id=-95003, name="Manual", kind="serie")
        db.add(manual)
        db.flush()
        db.add(ClubShow(club_id=club_id, show_id=manual.id, added_by_id=user_id, watch_status="watching"))
        db.commit()
        manual_id = manual.id
    finally:
        db.close()
    updated = _parsed_movie(id=20124, imdb_id="tt2012401", external_ids={"imdb_id": "tt2012401"}, overview="Sinopse nova.")
    with patch("app.catalog.tmdb.fetch_movie", AsyncMock(return_value=updated)) as tmdb_fetch:
        with patch("app.catalog.tvmaze.fetch_show_and_seasons") as tv_fetch:
            with patch("app.catalog.refresh_news"):
                movie_refresh = owner.post(f"/clubs/{club_id}/shows/{movie_id}/refresh", follow_redirects=False)
                manual_refresh = owner.post(f"/clubs/{club_id}/shows/{manual_id}/refresh", follow_redirects=False)
    assert movie_refresh.status_code == 303
    assert manual_refresh.status_code == 303
    tmdb_fetch.assert_called_once_with(20124)
    tv_fetch.assert_not_called()
    empty = _parsed_movie(
        id=20124,
        overview=None,
        poster_path=None,
        backdrop_path=None,
        homepage="",
        imdb_id=None,
        external_ids={},
    )
    with patch("app.catalog.tmdb.fetch_movie", AsyncMock(return_value=empty)):
        with patch("app.catalog.refresh_news"):
            owner.post(f"/clubs/{club_id}/shows/{movie_id}/refresh", follow_redirects=False)
    db = SessionLocal()
    try:
        show = db.get(Show, movie_id)
        assert show.summary == "Sinopse nova."
        assert show.imdb_id == "tt2012401"
        assert show.backdrop_url
        assert show.image_url
    finally:
        db.close()


def test_add_show_rejects_untrusted_provider():
    owner = TestClient(app)
    register_active(owner, "tmdb_bad", "tmdb.bad@example.com")
    club_id = _create_club(owner, "Sala Invalida")
    with patch("app.catalog.tmdb.fetch_movie") as fetch:
        blocked = owner.post(
            f"/clubs/{club_id}/shows",
            data={"provider": "evil", "external_id": "120", "image_url": "https://evil.example/x.jpg"},
            follow_redirects=False,
        )
    assert blocked.status_code == 303
    assert "error=" in blocked.headers["location"]
    fetch.assert_not_called()
