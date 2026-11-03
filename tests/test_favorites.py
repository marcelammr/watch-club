from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app.db import SessionLocal, engine
from app.main import app
from app.models import Club, ClubMember, ClubMessage, ClubSchedule, ClubShow, FeedNews, Show, User, UserShowFavorite
from app.roles import PERM_TITLES, ROLE_SUPPORT
from app.search import search_catalog
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


def _add_show(name: str, tvmaze_id: int, image: str | None = "https://example.com/p.jpg") -> int:
    db = SessionLocal()
    try:
        show = Show(tvmaze_id=tvmaze_id, name=name, kind="serie", image_url=image)
        db.add(show)
        db.commit()
        db.refresh(show)
        return show.id
    finally:
        db.close()


def test_user_show_favorites_schema_exists():
    inspector = inspect(engine)
    assert "user_show_favorites" in inspector.get_table_names()
    cols = {column["name"] for column in inspector.get_columns("user_show_favorites")}
    assert {"user_id", "show_id", "created_at"} <= cols


def test_favorite_toggle_belongs_to_user_and_does_not_duplicate():
    owner = TestClient(app)
    other = TestClient(app)
    register_active(owner, "fav_own", "fav.own@example.com")
    register_active(other, "fav_oth", "fav.oth@example.com")
    show_id = _add_show("Staged", -96001)
    owner_id = _user_id("fav_own")
    other_id = _user_id("fav_oth")

    added = owner.post(f"/shows/{show_id}/favorito", data={"next": f"/shows/{show_id}"}, follow_redirects=False)
    assert added.status_code == 303
    again = owner.post(f"/shows/{show_id}/favorito", data={"next": f"/shows/{show_id}"}, follow_redirects=False)
    assert again.status_code == 303
    restored = owner.post(f"/shows/{show_id}/favorito", data={"next": f"/shows/{show_id}"}, follow_redirects=False)
    assert restored.status_code == 303

    db = SessionLocal()
    try:
        mine = list(db.scalars(select(UserShowFavorite).where(UserShowFavorite.user_id == owner_id)))
        theirs = list(db.scalars(select(UserShowFavorite).where(UserShowFavorite.user_id == other_id)))
        assert len(mine) == 1
        assert mine[0].show_id == show_id
        assert theirs == []
        count = db.scalar(select(func.count()).select_from(UserShowFavorite).where(UserShowFavorite.show_id == show_id))
        assert count == 1
    finally:
        db.close()

    page = owner.get(f"/shows/{show_id}")
    assert page.status_code == 200
    assert 'aria-pressed="true"' in page.text
    assert "search_catalog" not in page.text


def test_favorite_is_independent_from_club_catalog():
    owner = TestClient(app)
    register_active(owner, "fav_club", "fav.club@example.com")
    club_id = _create_club(owner, "Clube Fav")
    user_id = _user_id("fav_club")
    show_id = _add_show("Good Omens", -96002)

    owner.post(f"/shows/{show_id}/favorito", follow_redirects=False)
    db = SessionLocal()
    try:
        links = list(db.scalars(select(ClubShow).where(ClubShow.club_id == club_id)))
        assert links == []
        db.add(ClubShow(club_id=club_id, show_id=show_id, added_by_id=user_id))
        db.commit()
    finally:
        db.close()

    other = _add_show("Rivals", -96003)
    db = SessionLocal()
    try:
        db.add(ClubShow(club_id=club_id, show_id=other, added_by_id=user_id))
        db.commit()
        favs = list(db.scalars(select(UserShowFavorite.show_id).where(UserShowFavorite.user_id == user_id)))
        assert favs == [show_id]
        assert other not in favs
    finally:
        db.close()


def _favorites_parts(html: str) -> tuple[str, str]:
    return html.split('id="favorites-dialog"', 1)


def _clubs_parts(html: str) -> tuple[str, str]:
    return html.split('id="profile-clubs-dialog"', 1)


def test_profile_shows_own_and_other_favorites_without_editing_others():
    owner = TestClient(app)
    guest = TestClient(app)
    register_active(owner, "fav_prof", "fav.prof@example.com")
    register_active(guest, "fav_view", "fav.view@example.com")
    show_id = _add_show("Sherlock", -96004)
    owner.post(f"/shows/{show_id}/favorito", follow_redirects=False)

    mine = owner.get("/u/fav_prof")
    assert mine.status_code == 200
    assert "Programas favoritos" in mine.text
    assert "Sherlock" in mine.text
    assert 'href="/shows/' in mine.text
    assert "Buscar para favoritar" in mine.text
    assert f'action="/shows/{show_id}/favorito"' not in mine.text.split("favorites-dialog", 1)[0]

    theirs = guest.get("/u/fav_prof")
    assert "Sherlock" in theirs.text
    assert "Buscar para favoritar" not in theirs.text
    assert f'action="/shows/{show_id}/favorito"' not in theirs.text
    assert "Programas favoritos" in theirs.text


def test_few_favorites_do_not_show_more_indicator():
    owner = TestClient(app)
    register_active(owner, "fav_few", "fav.few@example.com")
    ids = [_add_show(f"Curta {n}", -96120 - n) for n in range(4)]
    for show_id in ids:
        owner.post(f"/shows/{show_id}/favorito", follow_redirects=False)
    page = owner.get("/u/fav_few")
    preview, dialog = _favorites_parts(page.text)
    assert page.status_code == 200
    assert "profile-more" not in preview
    row = preview.split("profile-posters", 1)[-1]
    assert "+1" not in row
    assert row.count('class="profile-poster"') == 4
    for show_id in ids:
        assert preview.count(f'href="/shows/{show_id}"') == 1
        assert dialog.count(f'href="/shows/{show_id}"') == 1
    assert 'js-open-favorites' in preview
    assert 'aria-controls="favorites-dialog"' in preview


def test_favorite_preview_caps_and_shows_more_indicator():
    owner = TestClient(app)
    guest = TestClient(app)
    register_active(owner, "fav_many", "fav.many@example.com")
    register_active(guest, "fav_many_view", "fav.many.view@example.com")
    ids = [_add_show(f"Obra {n}", -96100 - n) for n in range(8)]
    for show_id in ids:
        owner.post(f"/shows/{show_id}/favorito", follow_redirects=False)
    page = owner.get("/u/fav_many")
    assert page.status_code == 200
    preview, dialog = _favorites_parts(page.text)
    newest_first = list(reversed(ids))
    visible = newest_first[:5]
    hidden = newest_first[5:]
    row = preview.split("profile-posters", 1)[1]
    assert row.count('class="profile-poster"') == 5
    assert "+3" in row
    assert 'aria-label="Ver mais 3 favoritos"' in row
    for show_id in visible:
        assert row.count(f'href="/shows/{show_id}"') == 1
    for show_id in hidden:
        assert f'href="/shows/{show_id}"' not in row
    for show_id in ids:
        assert dialog.count(f'href="/shows/{show_id}"') == 1
    assert dialog.count('class="profile-poster"') == 8
    assert "js-fav-search" in dialog
    for n, show_id in enumerate(ids):
        assert f'aria-label="Obra {n}"' in dialog
        assert f'href="/shows/{show_id}"' in dialog

    theirs = guest.get("/u/fav_many")
    other_preview, other_dialog = _favorites_parts(theirs.text)
    assert "+3" in other_preview.split("profile-posters", 1)[1]
    assert "js-fav-search" not in other_dialog
    assert "Buscar para favoritar" not in other_dialog
    assert 'action="/favoritos"' not in other_dialog
    assert "fav-btn" not in other_dialog
    for show_id in ids:
        assert other_dialog.count(f'href="/shows/{show_id}"') == 1
        assert f'action="/shows/{show_id}/favorito"' not in other_dialog


def test_few_clubs_do_not_show_more_indicator():
    host = TestClient(app)
    register_active(host, "club_few", "club.few@example.com")
    ids = [_create_club(host, f"Sala Pouca {n}") for n in range(3)]
    db = SessionLocal()
    try:
        club = db.get(Club, ids[0])
        club.icon_image = "aaaaaaaaaaaaaaaaaaaaaa01.png"
        club.cover_image = "bbbbbbbbbbbbbbbbbbbbbb02.png"
        db.commit()
    finally:
        db.close()
    page = host.get("/u/club_few")
    preview, dialog = _clubs_parts(page.text)
    row = preview.split('class="profile-clubs"', 1)[1]
    assert "profile-more" not in row
    assert row.count("profile-club-mark") == 3
    for club_id in ids:
        assert row.count(f'href="/clubs/{club_id}"') == 1
        assert dialog.count(f'href="/clubs/{club_id}"') == 2
    assert dialog.count("club-row") == 3
    assert "/static/uploads/club-icons/aaaaaaaaaaaaaaaaaaaaaa01.png" in row
    assert "/static/uploads/clubs/bbbbbbbbbbbbbbbbbbbbbb02.png" not in page.text
    assert 'js-open-clubs' in preview
    assert 'aria-controls="profile-clubs-dialog"' in preview


def test_profile_clubs_use_person_memberships_and_cap_preview():
    host = TestClient(app)
    guest = TestClient(app)
    register_active(host, "club_host", "club.host@example.com")
    register_active(guest, "club_guest", "club.guest@example.com")
    ids = [_create_club(host, f"Clube Extra {n}") for n in range(8)]
    guest_club = _create_club(guest, "Só do visitante")

    with patch("app.search.search_catalog", AsyncMock(side_effect=AssertionError("busca externa"))):
        page = guest.get("/u/club_host")
        mine = host.get("/u/club_host")
    assert page.status_code == 200
    preview, dialog = _clubs_parts(page.text)
    row = preview.split('class="profile-clubs"', 1)[1]
    assert row.count("profile-club-mark") == 5
    assert "+3" in row
    assert 'aria-label="Ver mais 3 clubes"' in row
    assert "js-open-clubs" in row
    assert 'aria-controls="profile-clubs-dialog"' in row
    visible_ids = [club_id for club_id in ids if f'href="/clubs/{club_id}"' in row]
    hidden_ids = [club_id for club_id in ids if club_id not in visible_ids]
    assert len(visible_ids) == 5
    assert len(hidden_ids) == 3
    for club_id in hidden_ids:
        assert f'href="/clubs/{club_id}"' not in row
    for club_id in ids:
        assert dialog.count(f'href="/clubs/{club_id}"') == 2
    assert dialog.count("club-row") == 8
    for n in range(8):
        assert f"Clube Extra {n}" in dialog
    assert "Só do visitante" not in page.text
    assert guest_club
    assert "Sair do clube" not in dialog
    assert "Configurações do clube" not in dialog
    assert f'action="/clubs/{ids[0]}/membros' not in dialog
    assert "cover_image_url" not in page.text
    assert "/static/uploads/clubs/" not in preview.split('class="profile-clubs"', 1)[1]
    own_dialog = _clubs_parts(mine.text)[1].split("<script>", 1)[0]
    assert "js-fav-search" not in own_dialog
    assert 'action="/favoritos"' not in own_dialog
    assert "Buscar clube" not in own_dialog


def test_closed_club_stays_visible_but_not_enterable_from_profile():
    host = TestClient(app)
    guest = TestClient(app)
    buddy = TestClient(app)
    register_active(host, "priv_host", "priv.host@example.com")
    register_active(guest, "priv_guest", "priv.guest@example.com")
    register_active(buddy, "priv_buddy", "priv.buddy@example.com")
    closed = host.post("/clubs", data={"name": "Sala Secreta", "is_closed": "1"}, follow_redirects=False)
    closed_id = int(closed.headers["location"].rsplit("/", 1)[-1])
    open_id = _create_club(host, "Sala Aberta")
    buddy_id = _user_id("priv_buddy")
    db = SessionLocal()
    try:
        db.add(ClubMember(club_id=closed_id, user_id=buddy_id, role="member"))
        db.commit()
    finally:
        db.close()

    page = guest.get("/u/priv_host")
    preview, dialog = _clubs_parts(page.text)
    assert "Sala Secreta" in page.text
    assert "🔒" in page.text
    assert f'href="/clubs/{closed_id}"' not in preview
    assert f'href="/clubs/{closed_id}"' not in dialog
    assert f'href="/clubs/{open_id}"' in preview
    assert "Pedir para entrar" in dialog
    assert "Sair do clube" not in dialog
    locked = guest.get(f"/clubs/{closed_id}")
    assert locked.status_code == 403
    assert "Este clube é fechado" in locked.text

    allowed = buddy.get("/u/priv_host")
    allowed_preview, allowed_dialog = _clubs_parts(allowed.text)
    assert f'href="/clubs/{closed_id}"' in allowed_preview
    assert f'href="/clubs/{closed_id}"' in allowed_dialog
    inside = buddy.get(f"/clubs/{closed_id}")
    assert inside.status_code == 200
    host_page = host.get(f"/clubs/{closed_id}")
    assert host_page.status_code == 200


def test_catalog_favorite_reuses_existing_show_without_club_link():
    owner = TestClient(app)
    register_active(owner, "fav_can", "fav.can@example.com")
    club_id = _create_club(owner, "Clube Canônico")
    show_id = _add_show("Staged Canônico", -96069)
    user_id = _user_id("fav_can")

    async def fake_upsert(db, tvmaze_id):
        return db.get(Show, show_id)

    with patch("app.catalog.upsert_show_from_tvmaze", fake_upsert):
        added = owner.post(
            "/favoritos",
            data={"provider": "tvmaze", "external_id": "96069", "next": "/u/fav_can"},
            follow_redirects=False,
        )
    assert added.status_code == 303
    db = SessionLocal()
    try:
        shows = list(db.scalars(select(Show).where(Show.tvmaze_id == -96069)))
        assert len(shows) == 1
        assert shows[0].id == show_id
        fav = db.scalar(select(UserShowFavorite).where(UserShowFavorite.user_id == user_id))
        assert fav.show_id == show_id
        links = list(db.scalars(select(ClubShow).where(ClubShow.show_id == show_id)))
        assert links == []
        assert club_id
    finally:
        db.close()


def test_profile_render_does_not_call_external_search():
    owner = TestClient(app)
    guest = TestClient(app)
    register_active(owner, "fav_perf", "fav.perf@example.com")
    register_active(guest, "fav_perf_view", "fav.perf.view@example.com")
    show_id = _add_show("Masters of Sex", -96005)
    owner.post(f"/shows/{show_id}/favorito", follow_redirects=False)
    with patch("app.search.search_catalog", AsyncMock(side_effect=AssertionError("busca externa"))):
        page = owner.get("/u/fav_perf")
        other = guest.get("/u/fav_perf")
    assert page.status_code == 200
    assert "Masters of Sex" in page.text
    assert "favorites-dialog" in page.text
    assert "Masters of Sex" in other.text
    assert search_catalog is not None


def test_news_favorites_filter_uses_real_favorites():
    owner = TestClient(app)
    register_active(owner, "fav_news", "fav.news@example.com")
    show_id = _add_show("Alpha Zeta", -96006)
    db = SessionLocal()
    try:
        db.add(
            FeedNews(
                title="Alpha Zeta ganha trailer",
                url="https://example.com/alpha-zeta",
                source="O Globo",
                published_at="2026-10-22",
                feed_kind="filmes-series",
                fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.add(
            FeedNews(
                title="Outra série qualquer",
                url="https://example.com/other-fav",
                source="O Globo",
                published_at="2026-10-21",
                feed_kind="filmes-series",
                fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()
    finally:
        db.close()

    empty = owner.get("/noticias?tipo=favoritos")
    assert "Favorite programas no seu perfil" in empty.text
    assert "Alpha Zeta ganha trailer" not in empty.text

    owner.post(f"/shows/{show_id}/favorito", follow_redirects=False)
    filled = owner.get("/noticias?tipo=favoritos")
    assert "Alpha Zeta ganha trailer" in filled.text
    assert "Outra série qualquer" not in filled.text
    assert "ainda está sendo preparada" not in filled.text


def _join_code(club_id: int) -> str:
    db = SessionLocal()
    try:
        return db.get(Club, club_id).join_code
    finally:
        db.close()


def _search_hit():
    return {
        "provider": "tvmaze",
        "external_id": 97011,
        "tvmaze_id": 97011,
        "tmdb_id": None,
        "name": "Maisy Run",
        "premiered": "2024-01-01",
        "kind": "serie",
        "image_url": "https://example.com/maisy.jpg",
        "summary": "Uma série.",
        "status": "Running",
        "genres": [],
    }


def test_search_add_vs_indicate_follows_title_permission():
    owner = TestClient(app)
    member = TestClient(app)
    helper = TestClient(app)
    register_active(owner, "ind_adm", "ind.adm@example.com")
    register_active(member, "ind_mem", "ind.mem@example.com")
    register_active(helper, "ind_sub", "ind.sub@example.com")
    club_id = _create_club(owner, "Sala Indicar")
    code = _join_code(club_id)
    member.post("/clubs/join", data={"join_code": code}, follow_redirects=False)
    helper.post("/clubs/join", data={"join_code": code}, follow_redirects=False)
    helper_id = _user_id("ind_sub")
    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": ROLE_SUPPORT, "support_perm": [PERM_TITLES]},
        follow_redirects=False,
    )
    fake = [_search_hit()]
    with (
        patch("app.search.tmdb.configured", return_value=False),
        patch("app.search.tvmaze.search_shows", AsyncMock(return_value=fake)),
    ):
        admin_page = owner.get(f"/clubs/{club_id}?aba=assistindo&q=Maisy")
        sub_page = helper.get(f"/clubs/{club_id}?aba=assistindo&q=Maisy")
        mem_page = member.get(f"/clubs/{club_id}?aba=assistindo&q=Maisy")
    admin_results = admin_page.text.split("js-title-search-results", 1)[1].split("</ul>", 1)[0]
    sub_results = sub_page.text.split("js-title-search-results", 1)[1].split("</ul>", 1)[0]
    assert "Adicionar ao clube" in admin_results
    assert "Indicar ao clube" not in admin_results
    assert 'data-can-titles="1"' in admin_page.text
    assert "Adicionar ao clube" in sub_results
    assert "Indicar ao clube" not in sub_results
    assert "Indicar ao clube" in mem_page.text
    mem_results = mem_page.text.split("js-title-search-results", 1)[1].split("</ul>", 1)[0]
    assert "Indicar ao clube" in mem_results
    assert "Adicionar ao clube" not in mem_results
    assert 'data-can-titles="0"' in mem_page.text
    assert "fav-btn" in mem_page.text
    blocked = member.post(
        f"/clubs/{club_id}/shows",
        data={"provider": "tvmaze", "external_id": "97011"},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert blocked.headers["location"] == f"/clubs/{club_id}"


def test_favorite_from_club_search_does_not_add_show_to_club():
    owner = TestClient(app)
    register_active(owner, "ind_fav", "ind.fav@example.com")
    club_id = _create_club(owner, "Sala Fav Busca")
    user_id = _user_id("ind_fav")
    show_id = _add_show("Maisy Run", 97012)

    async def fake_upsert(db, tvmaze_id):
        return db.get(Show, show_id)

    with patch("app.catalog.upsert_show_from_tvmaze", fake_upsert):
        added = owner.post(
            "/favoritos",
            data={
                "provider": "tvmaze",
                "external_id": "97012",
                "next": f"/clubs/{club_id}?aba=assistindo",
            },
            follow_redirects=False,
        )
    assert added.status_code == 303
    db = SessionLocal()
    try:
        fav = db.scalar(select(UserShowFavorite).where(UserShowFavorite.user_id == user_id, UserShowFavorite.show_id == show_id))
        assert fav is not None
        assert db.scalar(select(ClubShow).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id)) is None
    finally:
        db.close()
    owner.post(f"/shows/{show_id}/favorito", follow_redirects=False)
    db = SessionLocal()
    try:
        assert db.scalar(select(UserShowFavorite).where(UserShowFavorite.user_id == user_id, UserShowFavorite.show_id == show_id)) is None
    finally:
        db.close()


def test_indicate_posts_chat_and_does_not_join_club_or_favorite():
    owner = TestClient(app)
    member = TestClient(app)
    register_active(owner, "ind_chat", "ind.chat@example.com")
    register_active(member, "ind_sug", "ind.sug@example.com", name="Marcela")
    club_id = _create_club(owner, "Sala Chat Ind")
    member.post("/clubs/join", data={"join_code": _join_code(club_id)}, follow_redirects=False)
    show_id = _add_show("Maisy Run", 97013)
    user_id = _user_id("ind_sug")

    async def fake_upsert(db, tvmaze_id):
        return db.get(Show, show_id)

    with patch("app.catalog.upsert_show_from_tvmaze", fake_upsert):
        posted = member.post(
            f"/clubs/{club_id}/indicar",
            data={"provider": "tvmaze", "external_id": "97013", "next": f"/clubs/{club_id}?aba=chat"},
            follow_redirects=False,
        )
    assert posted.status_code == 303
    assert posted.headers["location"] == f"/clubs/{club_id}?aba=chat"
    db = SessionLocal()
    try:
        message = db.scalar(select(ClubMessage).where(ClubMessage.club_id == club_id))
        assert message is not None
        assert message.user_id == user_id
        assert message.show_id == show_id
        assert message.body == "Marcela indicou:"
        assert "Maisy Run" not in message.body
        assert "para os próximos encontros" not in message.body
        assert db.scalar(select(ClubShow).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id)) is None
        assert db.scalar(select(UserShowFavorite).where(UserShowFavorite.user_id == user_id)) is None
        assert db.scalar(select(func.count()).select_from(ClubSchedule).where(ClubSchedule.club_id == club_id)) == 0
    finally:
        db.close()
    chat = member.get(f"/clubs/{club_id}?aba=chat")
    assert "Marcela indicou:" in chat.text
    assert "Marcela indicou Maisy Run" not in chat.text
    assert "para os próximos encontros" not in chat.text
    assert "Ver programa" in chat.text
    assert f'href="/clubs/{club_id}/shows/{show_id}"' in chat.text


def test_own_profile_keeps_favorite_search_and_other_profile_has_no_edit():
    owner = TestClient(app)
    guest = TestClient(app)
    register_active(owner, "ind_prof", "ind.prof@example.com")
    register_active(guest, "ind_see", "ind.see@example.com")
    mine = owner.get("/u/ind_prof")
    assert "js-fav-search" in mine.text
    assert "/api/shows/search" in mine.text
    assert "/favoritos" in mine.text
    theirs = guest.get("/u/ind_prof")
    assert "js-fav-search-input" not in theirs.text
    assert "Buscar para favoritar" not in theirs.text
    assert 'action="/favoritos"' not in theirs.text


def test_club_message_show_id_schema_exists():
    inspector = inspect(engine)
    cols = {column["name"] for column in inspector.get_columns("club_messages")}
    assert "show_id" in cols
