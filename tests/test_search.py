from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.search import (
    SEARCH_MIN_CHARS,
    fold_search_text,
    normalize_search_query,
    rank_search_results,
    search_ready,
)
from tests.test_app import register_active

client = TestClient(app)


def _item(name: str, tvmaze_id: int = 1, **extra) -> dict:
    row = {
        "tvmaze_id": tvmaze_id,
        "name": name,
        "premiered": "2013-09-29",
        "status": "Ended",
        "image_url": "https://example.com/poster.jpg",
        "summary": "Resumo.",
        "kind": "serie",
    }
    row.update(extra)
    return row


def _club(http: TestClient, username: str, email: str, club_name: str) -> int:
    register_active(http, username, email)
    created = http.post("/clubs", data={"name": club_name}, follow_redirects=False)
    assert created.status_code == 303
    return int(created.headers["location"].rsplit("/", 1)[-1])


def test_normalize_search_query_trims_and_collapses_spaces():
    assert normalize_search_query("   Masters    of   Sex   ") == "Masters of Sex"
    assert normalize_search_query("  ") == ""
    assert normalize_search_query(None) == ""
    assert normalize_search_query("\tMasters\nof\nSex") == "Masters of Sex"


def test_empty_and_short_queries_are_not_ready():
    assert SEARCH_MIN_CHARS == 2
    assert search_ready("") is False
    assert search_ready("   ") is False
    assert search_ready("M") is False
    assert search_ready("é") is False
    assert search_ready("Ma") is True
    assert search_ready("  Ma  ") is True


def test_fold_search_text_is_case_and_accent_insensitive():
    assert fold_search_text("Senhor dos Anéis") == fold_search_text("senhor dos aneis")
    assert fold_search_text("  Senhor   dos   Anéis  ") == "senhor dos aneis"


def test_rank_exact_prefix_contains_and_original_order():
    results = [
        _item("The Master", 10),
        _item("Masters of Sex", 20),
        _item("Old Masters", 30),
        _item("Masters", 40),
        _item("Another Show", 50),
    ]
    ranked = rank_search_results(results, "Masters")
    assert [item["tvmaze_id"] for item in ranked] == [40, 20, 30, 10, 50]


def test_rank_prefix_before_contains():
    results = [_item("Sex and the City", 1), _item("Masters of Sex", 2)]
    ranked = rank_search_results(results, "Masters of")
    assert [item["name"] for item in ranked] == ["Masters of Sex", "Sex and the City"]


def test_rank_case_insensitive():
    results = [_item("breaking bad", 1), _item("Breaking Bad", 2)]
    ranked = rank_search_results(results, "BREAKING BAD")
    assert ranked[0]["tvmaze_id"] == 1
    assert ranked[1]["tvmaze_id"] == 2


def test_rank_accent_insensitive_and_stable():
    results = [
        _item("Outra Obra", 1),
        _item("Senhor dos Anéis", 2),
        _item("Aneis extras", 3),
        _item("Senhor dos Aneis: o retorno", 4),
    ]
    ranked = rank_search_results(results, "Senhor dos Aneis")
    assert [item["tvmaze_id"] for item in ranked] == [2, 4, 1, 3]


def test_rank_does_not_invent_missing_titles():
    results = [_item("MasterChef", 1), _item("The Master", 2)]
    ranked = rank_search_results(results, "Masters")
    assert [item["name"] for item in ranked] == ["MasterChef", "The Master"]
    assert "Masters of Sex" not in [item["name"] for item in ranked]


def test_search_api_requires_login():
    guest = client.get("/api/shows/search", params={"q": "breaking"})
    assert guest.status_code == 401
    assert guest.json()["detail"] == "Faça login"


def test_search_api_normalizes_ranks_and_skips_short_queries():
    member = TestClient(app)
    register_active(member, "busca_api", "busca.api@example.com")
    fake = [
        _item("The Master", 10),
        _item("Masters of Sex", 20),
        _item("Masters", 40),
    ]
    with patch("app.search.tvmaze.search_shows", AsyncMock(return_value=fake)) as mocked:
        short = member.get("/api/shows/search", params={"q": "M"})
        empty = member.get("/api/shows/search", params={"q": "   "})
        spaced = member.get("/api/shows/search", params={"q": "   Masters    of   Sex   "})
    assert short.status_code == 200
    assert short.json() == []
    assert empty.json() == []
    mocked.assert_called_once_with("Masters of Sex")
    names = [item["name"] for item in spaced.json()]
    assert names[0] == "Masters of Sex"


def test_search_api_returns_generic_error_without_traceback():
    member = TestClient(app)
    register_active(member, "busca_erro", "busca.erro@example.com")
    with patch("app.search.tvmaze.search_shows", AsyncMock(side_effect=RuntimeError("boom tvmaze"))):
        response = member.get("/api/shows/search", params={"q": "Masters"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Não foi possível pesquisar agora."
    assert "boom tvmaze" not in response.text
    assert "Traceback" not in response.text


def test_club_search_fallback_and_typeahead_markup():
    owner = TestClient(app)
    club_id = _club(owner, "busca_ui", "busca.ui@example.com", "Sala Busca")
    fake = [_item("Masters of Sex", 169, summary="A" * 240)]
    with patch("app.search.tvmaze.search_shows", AsyncMock(return_value=fake)) as mocked:
        page = owner.get(f"/clubs/{club_id}?aba=assistindo&q=  Masters   of   Sex ")
        short = owner.get(f"/clubs/{club_id}?aba=assistindo&q=M")
        blank = owner.get(f"/clubs/{club_id}?aba=assistindo")
    mocked.assert_called_once_with("Masters of Sex")
    assert page.status_code == 200
    assert 'class="js-title-search"' in page.text
    assert 'data-min-chars="2"' in page.text
    assert "js-title-search-input" in page.text
    assert "js-title-search-results" in page.text
    assert "AbortController" in page.text
    assert "debounceMs = 300" in page.text
    assert "/api/shows/search" in page.text
    assert 'name="tvmaze_id" value="169"' in page.text
    assert 'name="provider" value="tvmaze"' in page.text
    assert 'name="external_id" value="169"' in page.text
    assert "2013 · Série" in page.text
    assert "Adicionar ao clube" in page.text
    assert "Masters of Sex" in page.text
    assert "watch-search" in page.text
    assert short.status_code == 200
    assert "Digite ao menos 2 letras para pesquisar." in short.text
    assert 'name="tvmaze_id" value="169"' not in short.text
    assert "js-title-search" in blank.text
    assert 'name="tvmaze_id" value="' not in blank.text.split("js-title-search-results", 1)[1].split("</ul>", 1)[0]


def test_add_show_from_search_result_still_uses_tvmaze_id():
    from app.db import SessionLocal
    from app.models import Show
    from sqlalchemy import select

    owner = TestClient(app)
    club_id = _club(owner, "busca_add", "busca.add@example.com", "Sala Add")
    catalog = (
        {
            "tvmaze_id": 96001,
            "name": "Breaking Bad",
            "summary": "Um professor de química.",
            "status": "Ended",
            "premiered": "2008-01-20",
            "image_url": "https://example.com/bb.jpg",
            "backdrop_url": "https://example.com/bb-wide.jpg",
            "official_site": None,
            "kind": "serie",
            "genres": ["Drama"],
        },
        [{"number": 1, "name": "Season 1", "episode_count": 1, "premiere_date": "2008-01-20", "end_date": None, "image_url": None}],
        [{"tvmaze_id": 961001, "season_number": 1, "number": 1, "name": "Pilot", "airdate": "2008-01-20", "image_url": "https://example.com/still.jpg"}],
    )
    with patch("app.catalog.tvmaze.fetch_show_and_seasons", AsyncMock(return_value=catalog)):
        with patch("app.catalog.refresh_news"):
            added = owner.post(
                f"/clubs/{club_id}/shows",
                data={"tvmaze_id": "96001", "kind": "serie"},
                follow_redirects=False,
            )
    assert added.status_code == 303
    page = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "Breaking Bad" in page.text
    db = SessionLocal()
    try:
        show = db.scalar(select(Show).where(Show.tvmaze_id == 96001))
        assert show is not None
        assert show.backdrop_url == "https://example.com/bb-wide.jpg"
        assert show.seasons
        assert show.episodes
        assert show.episodes[0].image_url == "https://example.com/still.jpg"
    finally:
        db.close()


def test_unified_search_merges_tvmaze_and_tmdb_and_limits_results():
    from app.search import SEARCH_RESULT_LIMIT, search_catalog

    tv_rows = [_item(f"Show {index}", index, kind="serie") for index in range(1, 15)]
    movie_rows = [
        {
            "provider": "tmdb",
            "external_id": 100 + index,
            "tmdb_id": 100 + index,
            "name": f"Filme {index}",
            "premiered": "2001-12-19",
            "kind": "filme",
            "image_url": "https://image.tmdb.org/t/p/w342/x.jpg",
            "summary": "Filme.",
        }
        for index in range(1, 15)
    ]
    member = TestClient(app)
    register_active(member, "busca_mix", "busca.mix@example.com")
    with patch("app.search.tmdb.configured", return_value=True):
        with patch("app.search.tvmaze.search_shows", AsyncMock(return_value=tv_rows)):
            with patch("app.search.tmdb.search_movies", AsyncMock(return_value=movie_rows)):
                response = member.get("/api/shows/search", params={"q": "Show"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) <= SEARCH_RESULT_LIMIT
    kinds = {item["kind"] for item in body}
    assert "serie" in kinds
    assert "filme" in kinds
    assert any(item.get("provider") == "tmdb" for item in body)
    assert any(item.get("provider") == "tvmaze" for item in body)


def test_unified_search_survives_partial_provider_failure():
    member = TestClient(app)
    register_active(member, "busca_parcial", "busca.parcial@example.com")
    movies = [
        {
            "provider": "tmdb",
            "external_id": 120,
            "tmdb_id": 120,
            "name": "O Senhor dos Anéis: A Sociedade do Anel",
            "premiered": "2001-12-19",
            "kind": "filme",
            "image_url": None,
            "summary": "A jornada.",
        }
    ]
    with patch("app.search.tmdb.configured", return_value=True):
        with patch("app.search.tvmaze.search_shows", AsyncMock(side_effect=RuntimeError("tv down"))):
            with patch("app.search.tmdb.search_movies", AsyncMock(return_value=movies)):
                only_movies = member.get("/api/shows/search", params={"q": "Senhor dos Aneis"})
        with patch("app.search.tvmaze.search_shows", AsyncMock(return_value=[_item("Masters of Sex", 169)])):
            with patch("app.search.tmdb.search_movies", AsyncMock(side_effect=RuntimeError("tmdb down"))):
                only_tv = member.get("/api/shows/search", params={"q": "Masters of"})
        with patch("app.search.tvmaze.search_shows", AsyncMock(side_effect=RuntimeError("tv down"))):
            with patch("app.search.tmdb.search_movies", AsyncMock(side_effect=RuntimeError("tmdb down"))):
                both = member.get("/api/shows/search", params={"q": "Hobbit"})
    assert only_movies.status_code == 200
    assert only_movies.json()[0]["kind"] == "filme"
    assert only_movies.json()[0]["name"].startswith("O Senhor dos Anéis")
    assert only_tv.status_code == 200
    assert only_tv.json()[0]["provider"] == "tvmaze"
    assert both.status_code == 503


def test_unified_search_ranks_folded_movie_title():
    from app.search import rank_search_results

    results = [
        {
            "name": "Outro Filme",
            "kind": "filme",
            "provider": "tmdb",
        },
        {
            "name": "O Senhor dos Anéis: A Sociedade do Anel",
            "kind": "filme",
            "provider": "tmdb",
        },
    ]
    ranked = rank_search_results(results, "Senhor dos Aneis")
    assert ranked[0]["name"] == "O Senhor dos Anéis: A Sociedade do Anel"
