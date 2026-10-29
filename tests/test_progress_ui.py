from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.catalog import WATCHED, WATCHING, encode_genres, premiere_year
from app.db import SessionLocal
from app.main import app
from app.models import ClubEpisodeWatch, ClubMember, ClubShow, ClubWatchRound, Episode, NewsItem, User
from app.services.news import format_news_when
from app.roles import PERM_PROGRESS, PERM_SCHEDULES, PERM_TAG, ROLE_MEMBER, ROLE_SUPPORT
from tests.test_app import register_active, star_button_values
from tests.test_progress import _create_club, _seed_title, _user_id_by_key

client = TestClient(app)


def _join(http: TestClient, code: str) -> None:
    http.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)


def _club_code(club_id: int) -> str:
    db = SessionLocal()
    try:
        from app.models import Club

        return db.get(Club, club_id).join_code
    finally:
        db.close()


def _set_role(owner: TestClient, club_id: int, user_id: int, perms: list[str]) -> None:
    owner.post(
        f"/clubs/{club_id}/membros/{user_id}/papel",
        data={"role": "support", "support_perm": perms},
        follow_redirects=False,
    )


def test_admin_marks_and_unmarks_episode_on_open_round():
    owner = TestClient(app)
    register_active(owner, "pui_adm", "pui.adm@example.com")
    club_id = _create_club(owner, "Sala UI ADM")
    user_id = _user_id_by_key("pui_adm")
    show_id, episode_ids = _seed_title(
        club_id,
        user_id,
        82001,
        "Obra UI",
        [(1, 1, "Pilot"), (1, 2, "Cat's in the Bag")],
    )
    page = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "0 de 2 episódios assistidos" in page.text
    assert "Próximo: T1 E1 — Pilot" in page.text
    assert "watch-title" in page.text
    assert f'href="/clubs/{club_id}/shows/{show_id}"' in page.text
    assert "js-action-menu-toggle" in page.text
    assert "Marcar como finalizado" in page.text
    assert "Ver detalhes" not in page.text
    assert "Ver episódios" not in page.text

    marked = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/episodios/{episode_ids[0]}/visto",
        follow_redirects=False,
    )
    assert marked.status_code == 303
    assert marked.headers["location"].endswith(f"/shows/{show_id}#episodios") or "#episodios" in marked.headers["location"]

    db = SessionLocal()
    try:
        round_row = db.scalar(
            select(ClubWatchRound).where(ClubWatchRound.club_id == club_id, ClubWatchRound.show_id == show_id)
        )
        assert round_row.number == 1
        assert round_row.completed_at is None
        watch = db.scalar(select(ClubEpisodeWatch).where(ClubEpisodeWatch.episode_id == episode_ids[0]))
        assert watch.round_id == round_row.id
        assert watch.marked_by_id == user_id
        link = db.scalar(select(ClubShow).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id))
        assert link.watch_status == WATCHING
    finally:
        db.close()

    detail = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert "1 de 2 episódios assistidos" in detail.text
    assert "Próximo: T1 E2 —" in detail.text
    assert "Cat" in detail.text and "in the Bag" in detail.text
    assert "desmarcar" in detail.text
    assert f"/episodios/{episode_ids[0]}/desmarcar" in detail.text

    watching = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "1 de 2 episódios assistidos" in watching.text
    assert "Próximo: T1 E2 —" in watching.text

    unmarked = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/episodios/{episode_ids[0]}/desmarcar",
        follow_redirects=False,
    )
    assert unmarked.status_code == 303
    assert "t=" in unmarked.headers["location"] or unmarked.headers["location"].endswith("#episodios")
    db = SessionLocal()
    try:
        assert db.scalar(select(ClubEpisodeWatch.id).where(ClubEpisodeWatch.episode_id == episode_ids[0])) is None
        assert db.scalar(select(ClubWatchRound).where(ClubWatchRound.show_id == show_id)).number == 1
    finally:
        db.close()
    restored = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert "0 de 2 episódios assistidos" in restored.text
    assert "Marcar como assistido" in restored.text
    assert "episode-eye" in restored.text


def test_support_progress_perm_and_member_readonly():
    owner = TestClient(app)
    register_active(owner, "pui_owner", "pui.owner@example.com")
    club_id = _create_club(owner, "Sala UI Perms")
    code = _club_code(club_id)
    user_id = _user_id_by_key("pui_owner")
    show_id, episode_ids = _seed_title(club_id, user_id, 82002, "Obra Perms", [(1, 1, "Pilot"), (1, 2, "Next")])

    helper = TestClient(app)
    register_active(helper, "pui_sub", "pui.sub@example.com")
    _join(helper, code)
    helper_id = _user_id_by_key("pui_sub")
    _set_role(owner, club_id, helper_id, [PERM_TAG, PERM_SCHEDULES])
    settings = owner.get(f"/clubs/{club_id}/config")
    assert "Gerenciar progresso" in settings.text
    assert "Gerenciar agendamentos" in settings.text

    denied = helper.post(
        f"/clubs/{club_id}/shows/{show_id}/episodios/{episode_ids[0]}/visto",
        follow_redirects=False,
    )
    assert denied.status_code == 303
    db = SessionLocal()
    try:
        assert db.scalar(select(ClubEpisodeWatch.id).where(ClubEpisodeWatch.episode_id == episode_ids[0])) is None
        member = db.scalar(select(ClubMember).where(ClubMember.user_id == helper_id, ClubMember.club_id == club_id))
        assert member.role == ROLE_SUPPORT
    finally:
        db.close()

    _set_role(owner, club_id, helper_id, [PERM_PROGRESS])
    granted = helper.post(
        f"/clubs/{club_id}/shows/{show_id}/episodios/{episode_ids[0]}/visto",
        follow_redirects=False,
    )
    assert granted.status_code == 303
    db = SessionLocal()
    try:
        assert db.scalar(select(ClubEpisodeWatch.episode_id).where(ClubEpisodeWatch.episode_id == episode_ids[0]))
    finally:
        db.close()
    helper.post(
        f"/clubs/{club_id}/shows/{show_id}/episodios/{episode_ids[0]}/desmarcar",
        follow_redirects=False,
    )

    member = TestClient(app)
    register_active(member, "pui_mem", "pui.mem@example.com")
    _join(member, code)
    blocked = member.post(
        f"/clubs/{club_id}/shows/{show_id}/episodios/{episode_ids[0]}/visto",
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    db = SessionLocal()
    try:
        assert db.scalar(select(ClubEpisodeWatch.id).where(ClubEpisodeWatch.episode_id == episode_ids[0])) is None
        role = db.scalar(
            select(ClubMember.role).where(ClubMember.club_id == club_id, ClubMember.user_id == _user_id_by_key("pui_mem"))
        )
        assert role == ROLE_MEMBER
    finally:
        db.close()

    view = member.get(f"/clubs/{club_id}/shows/{show_id}")
    assert "Atualizar informações" in view.text
    assert "show-refresh" in view.text
    assert "0 de 2 episódios assistidos" in view.text
    assert "Próximo: T1 E1 — Pilot" in view.text
    assert f"/episodios/{episode_ids[0]}/visto" not in view.text
    assert "episode-eye is-static" in view.text
    assert "Marcar como assistido" not in view.text
    assert 'type="submit"' not in view.text.split("episode-card", 1)[-1]
    list_page = member.get(f"/clubs/{club_id}?aba=assistindo")
    assert "0 de 2 episódios assistidos" in list_page.text


def test_outsider_cannot_mark_progress():
    owner = TestClient(app)
    register_active(owner, "pui_host", "pui.host@example.com")
    club_id = _create_club(owner, "Sala Fechada")
    user_id = _user_id_by_key("pui_host")
    show_id, episode_ids = _seed_title(club_id, user_id, 82003, "Obra Host", [(1, 1, "Pilot")])
    stranger = TestClient(app)
    register_active(stranger, "pui_out", "pui.out@example.com")
    blocked = stranger.post(
        f"/clubs/{club_id}/shows/{show_id}/episodios/{episode_ids[0]}/visto",
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(ClubEpisodeWatch).where(ClubEpisodeWatch.episode_id == episode_ids[0])) == 0
    finally:
        db.close()


def test_complete_progress_keeps_watch_status_and_skips_specials():
    owner = TestClient(app)
    register_active(owner, "pui_done", "pui.done@example.com")
    club_id = _create_club(owner, "Sala Completo")
    user_id = _user_id_by_key("pui_done")
    show_id, episode_ids = _seed_title(
        club_id,
        user_id,
        82004,
        "Obra Completa",
        [(0, 1, "Special Night"), (1, None, "Unaired Cut"), (1, 1, "Pilot"), (1, 2, "Second")],
    )
    special_id, _unaired, first_id, second_id = episode_ids
    page = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "0 de 2 episódios assistidos" in page.text
    assert "Special Night" not in page.text
    assert "Unaired Cut" not in page.text
    detail = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert "Special Night" not in detail.text
    assert "E1" in detail.text
    assert "Pilot" in detail.text

    owner.post(f"/clubs/{club_id}/shows/{show_id}/episodios/{first_id}/visto", follow_redirects=False)
    owner.post(f"/clubs/{club_id}/shows/{show_id}/episodios/{second_id}/visto", follow_redirects=False)
    done = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "2 de 2 episódios assistidos" in done.text
    assert "Todos os episódios disponíveis foram assistidos." in done.text
    assert "Obra Completa" in done.text
    finished = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=finalizados")
    assert "Obra Completa" not in finished.text
    db = SessionLocal()
    try:
        link = db.scalar(select(ClubShow).where(ClubShow.show_id == show_id, ClubShow.club_id == club_id))
        assert link.watch_status == WATCHING
        assert db.scalar(select(ClubEpisodeWatch.id).where(ClubEpisodeWatch.episode_id == special_id)) is None
        link.watch_status = WATCHED
        db.commit()
    finally:
        db.close()
    watching_list = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=assistindo")
    assert "Obra Completa" not in watching_list.text
    listed = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=finalizados")
    assert "Obra Completa" in listed.text
    assert "2 de 2 episódios assistidos" in listed.text


def test_manual_title_empty_episode_state():
    owner = TestClient(app)
    register_active(owner, "pui_manual", "pui.manual@example.com")
    club_id = _create_club(owner, "Sala Manual UI")
    added = owner.post(
        f"/clubs/{club_id}/titulos",
        data={"name": "Título Sem Catálogo UI", "kind": "filme"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    db = SessionLocal()
    try:
        show_id = db.scalar(select(ClubShow.show_id).where(ClubShow.club_id == club_id).order_by(ClubShow.id.desc()))
    finally:
        db.close()
    list_page = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "episódios assistidos" not in list_page.text
    assert "Ver episódios" not in list_page.text
    detail = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert "show-episodes" not in detail.text
    assert "Não há informações de episódios disponíveis para este título." not in detail.text
    assert "Atualizar informações" not in detail.text
    assert f"/shows/{show_id}/refresh" not in detail.text
    assert "Voltar ao clube" not in detail.text
    assert detail.status_code == 200
    assert "show-hero-backdrop" not in detail.text
    assert "watch-tag" not in detail.text
    assert "Filme" not in detail.text
    assert "estreia " not in detail.text


def test_season_selector_filters_and_preserves_after_mark():
    owner = TestClient(app)
    register_active(owner, "pui_season", "pui.season@example.com")
    club_id = _create_club(owner, "Sala Temporadas")
    user_id = _user_id_by_key("pui_season")
    show_id, episode_ids = _seed_title(
        club_id,
        user_id,
        82007,
        "Obra Temporadas",
        [(1, 1, "Pilot Season"), (1, 2, "Still T1"), (2, 1, "Season Two Start")],
    )
    _t1, _t1b, t2 = episode_ids
    first = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    first_list = first.text.split("episode-list", 1)[1]
    assert "Pilot Season" in first_list
    assert "Still T1" in first_list
    assert "Season Two Start" not in first_list
    assert "Temporada 1" in first.text
    assert "Temporada 2" in first.text
    second = owner.get(f"/clubs/{club_id}/shows/{show_id}?t=2")
    second_list = second.text.split("episode-list", 1)[1]
    assert "Season Two Start" in second_list
    assert "Pilot Season" not in second_list
    assert "Still T1" not in second_list
    marked = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/episodios/{t2}/visto",
        data={"t": "2"},
        follow_redirects=False,
    )
    assert marked.status_code == 303
    assert "t=2" in marked.headers["location"]
    assert "#episodios" in marked.headers["location"]
    after = owner.get(f"/clubs/{club_id}/shows/{show_id}?t=2")
    after_list = after.text.split("episode-list", 1)[1]
    assert "Season Two Start" in after_list
    assert "Pilot Season" not in after_list
    invalid = owner.get(f"/clubs/{club_id}/shows/{show_id}?t=99")
    invalid_list = invalid.text.split("episode-list", 1)[1]
    assert "Pilot Season" in invalid_list
    assert "Season Two Start" not in invalid_list


def test_unsynced_seasons_prompt_refresh_not_manual():
    from app.models import Season, Show

    owner = TestClient(app)
    register_active(owner, "pui_old", "pui.old@example.com")
    club_id = _create_club(owner, "Sala Antiga")
    user_id = _user_id_by_key("pui_old")
    db = SessionLocal()
    try:
        show = Show(tvmaze_id=82008, name="Série Antiga", kind="serie")
        db.add(show)
        db.flush()
        db.add(ClubShow(club_id=club_id, show_id=show.id, added_by_id=user_id, watch_status=WATCHING))
        db.add(Season(show_id=show.id, number=1, name="Season 1", episode_count=8))
        db.commit()
        show_id = show.id
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert "Os episódios deste título ainda não foram sincronizados." in page.text
    assert "Atualizar informações" in page.text
    assert "show-refresh" in page.text
    assert f"/shows/{show_id}/refresh" in page.text
    assert f'id="show-menu-{show_id}"' not in page.text
    assert "episode-list" not in page.text
    assert "Voltar ao clube" not in page.text


def test_show_page_rating_matches_cards_and_stays_on_show():
    owner = TestClient(app)
    register_active(owner, "pui_nota", "pui.nota@example.com")
    club_id = _create_club(owner, "Sala Nota Obra")
    user_id = _user_id_by_key("pui_nota")
    show_id, _episode_ids = _seed_title(
        club_id,
        user_id,
        82009,
        "Obra Nota",
        [(1, 1, "Pilot"), (2, 1, "Season Two Start")],
    )
    empty = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert "Sua avaliação:" not in empty.text
    assert "Ainda sem avaliações" not in empty.text
    assert "star-read" not in empty.text
    assert empty.text.count("star-btn") == 5
    assert star_button_values(empty.text) == ["1", "2", "3", "4", "5"]
    assert "Média do clube: sem avaliações" in empty.text
    assert 'name="voltar" value="obra"' in empty.text
    guest = TestClient(app)
    register_active(guest, "pui_nota_b", "pui.nota.b@example.com")
    guest.post("/clubs/join", data={"join_code": _club_code(club_id), "next": "/"}, follow_redirects=False)
    guest.post(
        f"/clubs/{club_id}/shows/{show_id}/avaliar",
        data={"stars": "2", "voltar": "obra"},
        follow_redirects=False,
    )
    rated = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/avaliar",
        data={"stars": "5", "voltar": "obra", "t": "2"},
        follow_redirects=False,
    )
    assert rated.status_code == 303
    assert rated.headers["location"] == f"/clubs/{club_id}/shows/{show_id}?t=2#episodios"
    page = owner.get(f"/clubs/{club_id}/shows/{show_id}?t=2")
    assert "Sua avaliação:" not in page.text
    assert "Média do clube: 3,5 de 5" in page.text
    assert page.text.count("star-btn is-on") == 5
    assert page.text.count('aria-pressed="true"') == 1
    guest_page = guest.get(f"/clubs/{club_id}/shows/{show_id}")
    assert "Média do clube: 3,5 de 5" in guest_page.text
    assert guest_page.text.count("star-btn is-on") == 2
    unsafe_t = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/avaliar",
        data={"stars": "5", "voltar": "obra", "t": "../episodios"},
        follow_redirects=False,
    )
    assert unsafe_t.headers["location"] == f"/clubs/{club_id}/shows/{show_id}"
    from_list = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/avaliar",
        data={"stars": "5", "lista": "assistindo"},
        follow_redirects=False,
    )
    assert from_list.headers["location"] == f"/clubs/{club_id}?aba=assistindo&lista=assistindo"


def test_overflow_menu_keeps_status_and_remove_actions():
    owner = TestClient(app)
    register_active(owner, "pui_menu", "pui.menu@example.com")
    club_id = _create_club(owner, "Sala Menu")
    added = owner.post(
        f"/clubs/{club_id}/titulos",
        data={"name": "Obra Menu", "kind": "serie"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    db = SessionLocal()
    try:
        show_id = db.scalar(select(ClubShow.show_id).where(ClubShow.club_id == club_id).order_by(ClubShow.id.desc()))
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "js-action-menu" in page.text
    assert "Marcar como finalizado" in page.text
    assert "Remover do clube" in page.text
    watching = page.text.split('id="watch-menu-' + str(show_id) + '"', 1)[-1].split("</article>", 1)[0]
    assert f'action="/clubs/{club_id}/shows/{show_id}/remover" method="post"' in watching
    assert 'data-title="Obra Menu"' in watching
    assert "type=\"button\"" in watching
    assert "confirm('Remover \\u201c' + this.form.dataset.title + '\\u201d deste clube?')" in watching
    assert "this.form.requestSubmit()" in watching
    assert "data-confirm=" not in watching
    status_form = watching.split("/remover", 1)[0]
    assert "confirm(" not in status_form
    assert "Marcar como finalizado" in status_form
    marked = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/status",
        data={"watch_status": "watched"},
        follow_redirects=False,
    )
    assert marked.status_code == 303
    finished = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=finalizados")
    assert "Obra Menu" in finished.text
    assert "Voltar para Assistindo" in finished.text
    finished_menu = finished.text.split('id="watch-menu-' + str(show_id) + '"', 1)[-1].split("</article>", 1)[0]
    assert "Voltar para Assistindo" in finished_menu
    assert "confirm('Remover \\u201c' + this.form.dataset.title + '\\u201d deste clube?')" in finished_menu
    assert "this.form.requestSubmit()" in finished_menu
    assert "confirm(" not in finished_menu.split("/remover", 1)[0]
    member = TestClient(app)
    register_active(member, "pui_menu_mem", "pui.menu.mem@example.com")
    member.post("/clubs/join", data={"join_code": _club_code(club_id), "next": "/"}, follow_redirects=False)
    guest_page = member.get(f"/clubs/{club_id}?aba=assistindo&lista=finalizados")
    assert "Remover do clube" not in guest_page.text
    blocked = member.post(f"/clubs/{club_id}/shows/{show_id}/remover", follow_redirects=False)
    assert blocked.status_code == 303
    db = SessionLocal()
    try:
        assert db.scalar(select(ClubShow).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id))
    finally:
        db.close()


def test_news_when_formats_valid_dates_and_ignores_invalid():
    assert format_news_when("Mon, 26 Oct 2026 08:42:22 GMT") == "26 out 2026"
    assert format_news_when("2013-09-29") == "29 set 2013"
    assert format_news_when(None) == ""
    assert format_news_when("") == ""
    assert format_news_when("amanhã") == ""
    assert format_news_when("not-a-date") == ""


def test_show_page_episode_grid_preview_and_news_layout():
    from app.models import Show

    owner = TestClient(app)
    register_active(owner, "pui_grid", "pui.grid@example.com")
    club_id = _create_club(owner, "Sala Grid")
    user_id = _user_id_by_key("pui_grid")
    episodes = [(1, n, f"Episódio {n}") for n in range(1, 13)]
    episodes.append((2, 1, "Só na T2"))
    show_id, episode_ids = _seed_title(club_id, user_id, 82010, "Obra Grid", episodes)
    db = SessionLocal()
    try:
        show = db.get(Show, show_id)
        show.summary = "Uma sinopse longa o bastante para ocupar a coluna de leitura."
        db.add(
            NewsItem(
                show_id=show_id,
                title="Nova temporada ganha data de estreia",
                url="https://example.com/noticia-1",
                source="IMDb",
                published_at="Mon, 26 Oct 2026 08:42:22 GMT",
            )
        )
        db.add(
            NewsItem(
                show_id=show_id,
                title="Sem data válida",
                url="https://example.com/noticia-2",
                source="Veja",
                published_at="xyz",
            )
        )
        db.add(
            NewsItem(
                show_id=show_id,
                title="Terceira nota",
                url="https://example.com/noticia-3",
                source="O Globo",
                published_at=None,
            )
        )
        db.add(
            NewsItem(
                show_id=show_id,
                title="Quarta nota extra",
                url="https://example.com/noticia-4",
                source="Exame",
                published_at="2026-05-15",
            )
        )
        first = db.scalar(
            select(Episode).where(Episode.show_id == show_id, Episode.season_number == 1, Episode.number == 1)
        )
        first.airdate = "2013-09-29"
        db.commit()
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert page.status_code == 200
    assert 'href="/static/style.css?v=' in page.text
    assert "Sinopse" in page.text
    assert "Uma sinopse longa o bastante" in page.text
    assert "show-hero-backdrop" not in page.text
    assert "watch-tag" not in page.text
    assert " · estreia " not in page.text
    assert ">Série<" not in page.text
    assert "Sua avaliação:" not in page.text
    assert "star-read" not in page.text
    assert 'class="episode-list episode-grid"' in page.text
    assert page.text.count("<article class=\"episode-card") == 12
    assert page.text.count("episode-card is-extra") == 7
    assert "episode-more" in page.text
    assert "7 restantes" in page.text
    assert "Só na T2" not in page.text.split("episode-list", 1)[1]
    assert "Episódio 12" in page.text
    assert "E1: Episódio 1" in page.text
    assert "29 set 2013" in page.text
    assert "Marcar como assistido" in page.text
    assert "https://example.com/noticia-1" in page.text
    assert "26 out 2026" in page.text
    assert "GMT" not in page.text
    assert "xyz" not in page.text
    assert "15 mai 2026" in page.text
    assert "Ver mais notícias" in page.text
    assert page.text.count("show-news-item is-extra") == 1
    season_two = owner.get(f"/clubs/{club_id}/shows/{show_id}?t=2")
    t2 = season_two.text.split("episode-list", 1)[1]
    assert "Só na T2" in t2
    assert "Episódio 1" not in t2
    assert "episode-more" not in t2
    ten_id, _ids = _seed_title(
        club_id,
        user_id,
        82011,
        "Obra Dez",
        [(1, n, f"Dez {n}") for n in range(1, 11)],
    )
    ten = owner.get(f"/clubs/{club_id}/shows/{ten_id}")
    assert ten.text.count("<article class=\"episode-card") == 10
    assert ten.text.count("episode-card is-extra") == 5
    assert "5 restantes" in ten.text
    five_id, _ids = _seed_title(
        club_id,
        user_id,
        82012,
        "Obra Cinco",
        [(1, n, f"Cinco {n}") for n in range(1, 6)],
    )
    five = owner.get(f"/clubs/{club_id}/shows/{five_id}")
    assert five.text.count("<article class=\"episode-card") == 5
    assert "episode-card is-extra" not in five.text
    assert "episode-more" not in five.text


def test_premiere_year_reads_iso_and_ignores_invalid():
    assert premiere_year("2013-09-29") == "2013"
    assert premiere_year("1999") == "1999"
    assert premiere_year(None) == ""
    assert premiere_year("") == ""
    assert premiere_year("amanhã") == ""
    assert premiere_year("13") == ""
    assert premiere_year("0001-01-01") == ""


def test_show_hero_uses_backdrop_year_and_plain_genres():
    from app.models import Show

    owner = TestClient(app)
    register_active(owner, "pui_hero", "pui.hero@example.com")
    club_id = _create_club(owner, "Sala Hero")
    user_id = _user_id_by_key("pui_hero")
    show_id, _episode_ids = _seed_title(
        club_id,
        user_id,
        82013,
        "Obra Hero",
        [(1, 1, "Pilot")],
    )
    db = SessionLocal()
    try:
        show = db.get(Show, show_id)
        show.summary = "Sinopse da obra no hero."
        show.premiered = "2013-09-29"
        show.genres = encode_genres(["Drama", "Romance", "História"])
        show.backdrop_url = "https://example.com/hero-bg.jpg"
        show.image_url = "https://example.com/poster.jpg"
        db.commit()
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert page.status_code == 200
    assert 'class="show-hero-backdrop"' in page.text
    assert "https://example.com/hero-bg.jpg" in page.text
    assert "show-poster" not in page.text
    assert "https://example.com/poster.jpg" not in page.text
    assert ">2013<" in page.text
    assert "2013-09-29" not in page.text
    assert "29 de setembro" not in page.text
    assert "Drama · Romance · História" in page.text
    assert "watch-tag" not in page.text
    assert " · estreia " not in page.text
    assert ">Série<" not in page.text
    assert "Sinopse da obra no hero." in page.text
    assert page.text.count("star-btn") == 5
    assert "episode-list" in page.text
    assert "Pilot" in page.text
    assert "Marcar como assistido" in page.text


def test_show_hero_without_backdrop_keeps_poster_and_survives_missing_premiere():
    from app.models import Show

    owner = TestClient(app)
    register_active(owner, "pui_nobg", "pui.nobg@example.com")
    club_id = _create_club(owner, "Sala Sem Fundo")
    user_id = _user_id_by_key("pui_nobg")
    show_id, _episode_ids = _seed_title(
        club_id,
        user_id,
        82014,
        "Obra Sem Fundo",
        [(1, 1, "Pilot")],
    )
    db = SessionLocal()
    try:
        show = db.get(Show, show_id)
        show.premiered = "não é data"
        show.genres = encode_genres(["Drama"])
        show.image_url = "https://example.com/only-poster.jpg"
        show.backdrop_url = None
        db.commit()
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}/shows/{show_id}")
    assert page.status_code == 200
    assert "show-hero-backdrop" not in page.text
    assert 'class="show-poster"' in page.text
    assert "https://example.com/only-poster.jpg" in page.text
    assert ">2013<" not in page.text
    assert "não é data" not in page.text
    assert "Drama" in page.text
    assert "watch-tag" not in page.text
    assert page.text.count("star-btn") == 5


def test_show_back_link_keeps_club_origin_after_inpage_requests():
    owner = TestClient(app)
    register_active(owner, "pui_back", "pui.back@example.com")
    club_id = _create_club(owner, "Sala Voltar")
    user_id = _user_id_by_key("pui_back")
    show_id, episode_ids = _seed_title(
        club_id,
        user_id,
        82015,
        "Obra Voltar",
        [(1, 1, "Pilot"), (2, 1, "T2")],
    )
    origin = f"/clubs/{club_id}?aba=assistindo"
    show_path = f"/clubs/{club_id}/shows/{show_id}"
    first = owner.get(show_path, headers={"Referer": f"http://testserver{origin}"})
    assert f'class="back-btn" href="{origin}"' in first.text
    season = owner.get(f"{show_path}?t=2", headers={"Referer": f"http://testserver{show_path}"})
    assert f'class="back-btn" href="{origin}"' in season.text
    owner.post(
        f"{show_path}/avaliar",
        data={"stars": "4", "voltar": "obra", "t": "2"},
        headers={"Referer": f"http://testserver{show_path}?t=2"},
        follow_redirects=False,
    )
    after_rate = owner.get(f"{show_path}?t=2", headers={"Referer": f"http://testserver{show_path}?t=2"})
    assert f'class="back-btn" href="{origin}"' in after_rate.text
    owner.post(
        f"{show_path}/episodios/{episode_ids[0]}/visto",
        data={"t": "1"},
        headers={"Referer": f"http://testserver{show_path}"},
        follow_redirects=False,
    )
    after_mark = owner.get(show_path, headers={"Referer": f"http://testserver{show_path}#episodios"})
    assert f'class="back-btn" href="{origin}"' in after_mark.text
    poisoned = owner.get(show_path, headers={"Referer": "https://evil.example/phish"})
    assert f'class="back-btn" href="{origin}"' in poisoned.text
    assert "evil.example" not in poisoned.text


