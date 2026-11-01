from datetime import datetime, timezone

import feedparser
from sqlalchemy import select, update
from fastapi.testclient import TestClient

from app.catalog import compose_news_layout, pack_news_rest, pick_home_news, refresh_feed_news
from app.db import SessionLocal
from app.main import app
from app.models import ClubShow, FeedNews, NewsItem, Show, User
from app.services.news import diversify_news, html_meta_image, inflate_http_body
from app.services import news as news_service
from tests.test_app import register_active

client = TestClient(app)


def _create_club(http: TestClient, name: str) -> int:
    created = http.post("/clubs", data={"name": name}, follow_redirects=False)
    return int(created.headers["location"].rsplit("/", 1)[-1])


def _user_id(key: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(User.id).where(User.username_key == key))
    finally:
        db.close()


def _seed_club_story(
    club_id: int,
    user_id: int,
    tvmaze_id: int,
    name: str,
    kind: str,
    title: str,
    url: str,
) -> None:
    db = SessionLocal()
    try:
        show = Show(tvmaze_id=tvmaze_id, name=name, kind=kind, image_url="https://example.com/poster.jpg")
        db.add(show)
        db.flush()
        db.add(ClubShow(club_id=club_id, show_id=show.id, added_by_id=user_id))
        db.add(NewsItem(show_id=show.id, title=title, url=url, source="Clube", published_at="2026-10-30"))
        db.commit()
    finally:
        db.close()


def _seed_feed(title: str, url: str, source: str, published_at: str, feed_kind: str, image_url: str | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(
            FeedNews(
                title=title,
                url=url,
                source=source,
                published_at=published_at,
                image_url=image_url,
                feed_kind=feed_kind,
                fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()
    finally:
        db.close()


def test_news_page_requires_login_and_uses_general_feed():
    locked = TestClient(app).get("/noticias", follow_redirects=False)
    assert locked.status_code == 303
    assert locked.headers["location"].startswith("/login")

    owner = TestClient(app)
    register_active(owner, "news_host", "news.host@example.com")
    club_id = _create_club(owner, "Sala News")
    _seed_club_story(
        club_id,
        _user_id("news_host"),
        193001,
        "Obra Destaque",
        "serie",
        "Notícia só do clube",
        "https://example.com/club-only",
    )
    _seed_feed(
        "Nova temporada ganha trailer",
        "https://example.com/news-a",
        "O Globo",
        "Mon, 26 Oct 2026 08:42:22 GMT",
        "filmes-series",
        "https://example.com/a.jpg",
    )
    _seed_feed(
        "Filme chega ao streaming",
        "https://example.com/news-b",
        "AdoroCinema",
        "2026-10-20",
        "filmes-series",
    )
    _seed_feed(
        "Anime anuncia filme",
        "https://example.com/news-c",
        "Crunchyroll",
        "2026-10-18",
        "anime",
    )
    _seed_feed(
        "Programa de TV renovado",
        "https://example.com/news-d",
        "TV Guide",
        "2026-10-10",
        "tv",
    )

    other = TestClient(app)
    register_active(other, "news_other", "news.other@example.com")

    page = owner.get("/noticias")
    assert page.status_code == 200
    assert "Nova temporada ganha trailer" in page.text
    assert "https://example.com/news-a" in page.text
    assert "O Globo" in page.text
    assert "26 out 2026" in page.text
    assert "GMT" not in page.text
    assert "Notícia só do clube" not in page.text
    assert 'class="news-feature"' in page.text
    assert 'class="news-side"' in page.text
    assert 'id="news-q"' in page.text
    assert "Filmes e Séries" in page.text
    assert "Meus favoritos" in page.text
    assert 'src="https://example.com/a.jpg"' in page.text
    assert "news-side-item is-text" in page.text
    assert "Filme chega ao streaming" in page.text

    home = owner.get("/")
    assert "Últimas notícias" in home.text
    assert "Nova temporada ganha trailer" in home.text
    assert 'class="home-news-card"' in home.text
    assert "home-news-media" in home.text
    assert 'src="https://example.com/a.jpg"' in home.text
    assert "home-section-mark" in home.text
    assert "home-news-meta" in home.text
    assert "26 out" in home.text
    assert 'href="/noticias"' in home.text
    assert "Notícia só do clube" not in home.text


def test_news_search_and_kind_filters():
    owner = TestClient(app)
    register_active(owner, "news_flt", "news.flt@example.com")
    _seed_feed("Trailer da série Alpha", "https://example.com/alpha", "O Globo", "2026-10-22", "filmes-series")
    _seed_feed("Anime Beta no cinema", "https://example.com/beta", "Crunchyroll", "2026-10-21", "anime")
    _seed_feed("TV Gamma estreia quadro", "https://example.com/gamma", "TV Guide", "2026-10-20", "tv")

    found = owner.get("/noticias?q=Alpha")
    assert "Trailer da série Alpha" in found.text
    assert "Anime Beta no cinema" not in found.text
    assert 'value="Alpha"' in found.text

    anime = owner.get("/noticias?tipo=anime")
    assert "Anime Beta no cinema" in anime.text
    assert "Trailer da série Alpha" not in anime.text
    assert "TV Gamma estreia quadro" not in anime.text

    movies = owner.get("/noticias?tipo=filmes-series")
    assert "Trailer da série Alpha" in movies.text
    assert "Anime Beta no cinema" not in movies.text

    tv = owner.get("/noticias?tipo=tv")
    assert "TV Gamma estreia quadro" in tv.text
    assert "Trailer da série Alpha" not in tv.text

    empty = owner.get("/noticias?q=xyzzy")
    assert "Nenhuma notícia encontrada" in empty.text
    assert "Trailer da série Alpha" not in empty.text

    fav = owner.get("/noticias?tipo=favoritos")
    assert "Meus favoritos" in fav.text
    assert "ainda está sendo preparada" in fav.text
    assert "Trailer da série Alpha" not in fav.text


def test_diversify_news_avoids_same_work_and_duplicates():
    items = [
        {
            "title": "The Boys ganha nova temporada",
            "url": "https://example.com/1",
            "source": "Omelete",
            "published_at": "2026-10-30",
            "feed_kind": "filmes-series",
        },
        {
            "title": "The Boys anuncia elenco extra",
            "url": "https://example.com/2",
            "source": "Omelete",
            "published_at": "2026-10-29",
            "feed_kind": "filmes-series",
        },
        {
            "title": "The Boys ganha nova temporada",
            "url": "https://example.com/1b",
            "source": "UOL",
            "published_at": "2026-10-30",
            "feed_kind": "filmes-series",
        },
        {
            "title": "Anime da temporada ganha trailer",
            "url": "https://example.com/3",
            "source": "Crunchyroll",
            "published_at": "2026-10-28",
            "feed_kind": "anime",
        },
        {
            "title": "Talk show estreia quadro novo",
            "url": "https://example.com/4",
            "source": "TV Guide",
            "published_at": "2026-10-27",
            "feed_kind": "tv",
        },
    ]
    picked = diversify_news(items, 4)
    titles = [item["title"] for item in picked]
    assert titles.count("The Boys ganha nova temporada") == 1
    assert titles[0] == "The Boys ganha nova temporada"
    assert "Anime da temporada ganha trailer" in titles
    assert "Talk show estreia quadro novo" in titles
    assert titles[1] != "The Boys anuncia elenco extra"


def test_rss_and_html_images_are_extracted():
    rss = {
        "media_content": {"url": "https://cdn.example/story.jpg", "medium": "image"},
        "summary": "<a href='https://example.com/a'>texto</a>",
    }
    assert news_service._entry_image(rss) == "https://cdn.example/story.jpg"
    thumb = {"media_thumbnail": {"url": "https://cdn.example/thumb.jpg"}}
    assert news_service._entry_image(thumb) == "https://cdn.example/thumb.jpg"
    enclosure = {"enclosures": {"url": "https://cdn.example/enc.png", "type": "image/png"}}
    assert news_service._entry_image(enclosure) == "https://cdn.example/enc.png"

    html = """
    <meta property="og:title" content="Matéria">
    <meta property="og:image" content="https://img.example/cover.webp">
    """
    assert html_meta_image(html) == "https://img.example/cover.webp"
    google_logo = '<meta property="og:image" content="https://lh3.googleusercontent.com/J6_coFbogxhRI9iM864NL_liGXvsQp2AupsKei7z0cNNfDvGUmWUy20nuUhkREQyrpY4bEeIBuc=s0-w300">'
    assert html_meta_image(google_logo) is None
    assert news_service._entry_image({"summary": "<a href='https://news.google.com/x'>sem foto</a>"}) is None

    ld = '{"@type":"NewsArticle","image":"https://cdn.example/ld.jpg"}'
    assert html_meta_image(f'<script type="application/ld+json">{ld}</script>') == "https://cdn.example/ld.jpg"
    gz = inflate_http_body(
        __import__("gzip").compress(b'<meta property="og:image" content="https://cdn.example/gz.jpg">'),
        "gzip",
    )
    assert html_meta_image(gz.decode()) == "https://cdn.example/gz.jpg"


def test_feed_cache_skips_refetch_until_ttl_expires(monkeypatch):
    calls = []

    def fake_fetch(limit=36, resolve_images=True):
        calls.append("fetch")
        return [
            {
                "title": "Série nova ganha trailer",
                "url": "https://example.com/fresh-cache",
                "source": "Omelete",
                "published_at": "2026-10-31",
                "image_url": "https://example.com/fresh.jpg",
                "feed_kind": "filmes-series",
            }
        ]

    monkeypatch.setattr(news_service, "fetch_general_news", fake_fetch)
    _seed_feed(
        "Matéria antiga sem foto",
        "https://example.com/old-cache",
        "UOL",
        "2026-10-01",
        "tv",
    )
    db = SessionLocal()
    try:
        refresh_feed_news(db)
        assert calls == []
        db.execute(update(FeedNews).values(fetched_at=datetime(2020, 1, 1)))
        db.commit()
        refresh_feed_news(db)
    finally:
        db.close()
    assert calls == ["fetch"]
    db = SessionLocal()
    try:
        urls = [row.url for row in db.scalars(select(FeedNews))]
    finally:
        db.close()
    assert urls == ["https://example.com/fresh-cache"]


def test_failed_source_does_not_drop_remaining_feed(monkeypatch):
    def load(url: str):
        if "anime" in url:
            raise TimeoutError("fonte lenta")
        feed = feedparser.FeedParserDict()
        marker = abs(hash(url)) % 99999
        feed.entries = [
            feedparser.FeedParserDict(
                {
                    "title": f"Filme ganha trailer {marker} na Netflix",
                    "link": f"https://example.com/story-{marker}",
                    "source": {"title": "Omelete"},
                    "published": "2026-10-30",
                    "media_content": [{"url": "https://cdn.example/a.jpg", "medium": "image"}],
                }
            )
        ]
        return feed

    monkeypatch.setattr(news_service, "_load_rss", load)
    monkeypatch.setattr(news_service, "_attach_article_images", lambda items: None)
    items = news_service.real_fetch_general_news(limit=12)
    assert items
    assert all(item["feed_kind"] != "anime" for item in items)
    assert len({item["url"] for item in items}) == len(items)


def test_collect_topic_swallows_source_errors(monkeypatch):
    def boom(_url):
        raise TimeoutError("timeout")

    monkeypatch.setattr(news_service, "_load_rss", boom)
    assert news_service._collect_topic(("tv", "novela")) == []


def test_home_news_prefers_images_without_dropping_variety():
    items = [
        {"title": "The Boys ganha nova temporada", "url": "https://example.com/1", "source": "Omelete", "published_at": "2026-10-30", "feed_kind": "filmes-series"},
        {"title": "Filme Alpha chega ao streaming", "url": "https://example.com/2", "source": "UOL", "published_at": "2026-10-29", "image_url": "https://cdn.example/2.jpg", "feed_kind": "filmes-series"},
        {"title": "Anime da temporada ganha trailer", "url": "https://example.com/3", "source": "Crunchyroll", "published_at": "2026-10-28", "image_url": "https://cdn.example/3.jpg", "feed_kind": "anime"},
        {"title": "Talk show estreia quadro novo", "url": "https://example.com/4", "source": "TV Guide", "published_at": "2026-10-27", "feed_kind": "tv"},
    ]
    picked = pick_home_news(items, 3)
    assert [item["url"] for item in picked] == [
        "https://example.com/2",
        "https://example.com/3",
        "https://example.com/1",
    ]
    featured, secondary, rest = compose_news_layout(items)
    assert featured["url"] == "https://example.com/2"
    assert [item["url"] for item in secondary] == ["https://example.com/1", "https://example.com/3", "https://example.com/4"]
    assert rest == []


def _urls_from_cells(cells: list[dict]) -> list[str]:
    urls = []
    for cell in cells:
        urls.extend(item["url"] for item in cell["entries"])
    return urls


def test_pack_news_rest_groups_nearby_text_and_keeps_every_item():
    items = [
        {"title": "Texto um da série", "url": "https://example.com/t1"},
        {"title": "Foto um", "url": "https://example.com/f1", "image_url": "https://cdn.example/1.jpg"},
        {"title": "Foto dois", "url": "https://example.com/f2", "image_url": "https://cdn.example/2.jpg"},
        {"title": "Texto dois da série", "url": "https://example.com/t2"},
        {"title": "Foto três", "url": "https://example.com/f3", "image_url": "https://cdn.example/3.jpg"},
    ]
    cells = pack_news_rest(items)
    assert _urls_from_cells(cells) == [
        "https://example.com/t1",
        "https://example.com/t2",
        "https://example.com/f1",
        "https://example.com/f2",
        "https://example.com/f3",
    ]
    assert len(_urls_from_cells(cells)) == len(set(_urls_from_cells(cells)))
    briefs = [cell for cell in cells if cell["kind"] == "briefs"]
    assert len(briefs) == 1
    assert [item["url"] for item in briefs[0]["entries"]] == [
        "https://example.com/t1",
        "https://example.com/t2",
    ]
    assert not briefs[0].get("wide")
    assert all(cell["kind"] == "image" for cell in cells if cell["kind"] != "briefs")


def test_pack_news_rest_groups_texts_across_images_and_caps_at_three():
    photos = [
        {"title": f"Foto {index}", "url": f"https://example.com/f{index}", "image_url": f"https://cdn.example/{index}.jpg"}
        for index in range(1, 9)
    ]
    texts = [
        {"title": "Texto um da série", "url": "https://example.com/t1"},
        {"title": "Texto dois da série", "url": "https://example.com/t2"},
        {"title": "Texto três da série", "url": "https://example.com/t3"},
        {"title": "Texto quatro da série", "url": "https://example.com/t4"},
        {"title": "Texto cinco da série", "url": "https://example.com/t5"},
    ]
    items = [texts[0], *photos[:7], texts[1], photos[7], texts[2], texts[3], texts[4]]
    cells = pack_news_rest(items)
    assert _urls_from_cells(cells) == [
        "https://example.com/t1",
        "https://example.com/t2",
        "https://example.com/t3",
        *[photo["url"] for photo in photos[:7]],
        photos[7]["url"],
        "https://example.com/t4",
        "https://example.com/t5",
    ]
    assert len(_urls_from_cells(cells)) == len(items)
    assert len(_urls_from_cells(cells)) == len(set(_urls_from_cells(cells)))
    briefs = [cell["entries"] for cell in cells if cell["kind"] == "briefs"]
    assert [item["url"] for item in briefs[0]] == [
        "https://example.com/t1",
        "https://example.com/t2",
        "https://example.com/t3",
    ]
    assert [item["url"] for item in briefs[1]] == [
        "https://example.com/t4",
        "https://example.com/t5",
    ]


def test_pack_news_rest_keeps_singleton_text_compact():
    items = [
        {"title": "Só texto da série", "url": "https://example.com/solo"},
        {"title": "Foto um", "url": "https://example.com/f1", "image_url": "https://cdn.example/1.jpg"},
        {"title": "Foto dois", "url": "https://example.com/f2", "image_url": "https://cdn.example/2.jpg"},
        {"title": "Foto três", "url": "https://example.com/f3", "image_url": "https://cdn.example/3.jpg"},
    ]
    cells = pack_news_rest(items)
    assert _urls_from_cells(cells) == [item["url"] for item in items]
    assert cells[0]["kind"] == "briefs"
    assert not cells[0].get("wide")
    assert len(cells[0]["entries"]) == 1


def test_news_text_variant_and_image_priority_in_pages():
    owner = TestClient(app)
    register_active(owner, "news_layout", "news.layout@example.com")
    _seed_feed("Texto recente sem foto da série", "https://example.com/text-lead", "Omelete", "2026-10-31", "filmes-series")
    _seed_feed(
        "Destaque com imagem da série",
        "https://example.com/photo-lead",
        "AdoroCinema",
        "2026-10-30",
        "filmes-series",
        "https://example.com/photo.jpg",
    )
    _seed_feed("Anime com cartaz", "https://example.com/anime-photo", "Crunchyroll", "2026-10-29", "anime", "https://example.com/anime.jpg")
    _seed_feed("Talk show sem cartaz", "https://example.com/tv-text", "TV Guide", "2026-10-28", "tv")
    for idx in range(5):
        _seed_feed(
            f"Extra textual {idx} da série",
            f"https://example.com/extra-{idx}",
            f"Fonte {idx}",
            f"2026-10-2{idx}",
            "tv",
        )

    page = owner.get("/noticias")
    feature_at = page.text.find("news-feature")
    photo_at = page.text.find("Destaque com imagem da série")
    text_at = page.text.find("Texto recente sem foto da série")
    assert feature_at != -1
    assert photo_at != -1 and photo_at > feature_at
    assert 'src="https://example.com/photo.jpg"' in page.text
    assert "news-card is-text" in page.text
    assert "news-briefs" in page.text
    assert "is-wide" not in page.text
    assert 'is-text"><span class="news-card-media"' not in page.text
    assert "Texto recente sem foto da série" in page.text

    home = owner.get("/")
    home_photo = home.text.find("Destaque com imagem da série")
    home_anime = home.text.find("Anime com cartaz")
    home_text = home.text.find("Texto recente sem foto da série")
    assert home_photo != -1
    assert home_anime != -1
    assert home_text != -1
    assert home_photo < home_text
    assert home_anime < home_text
    assert 'src="https://example.com/photo.jpg"' in home.text
    assert "home-news-card is-text" in home.text
    fav = owner.get("/noticias?tipo=favoritos")
    assert "Meus favoritos" in fav.text
    assert "ainda está sendo preparada" in fav.text
    found = owner.get("/noticias?q=Destaque")
    assert "Destaque com imagem da série" in found.text
    assert "Anime com cartaz" not in found.text
