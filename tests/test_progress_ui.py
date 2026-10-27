from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.catalog import WATCHED, WATCHING
from app.db import SessionLocal
from app.main import app
from app.models import ClubEpisodeWatch, ClubMember, ClubShow, ClubWatchRound, User
from app.roles import PERM_PROGRESS, PERM_SCHEDULES, PERM_TAG, ROLE_MEMBER, ROLE_SUPPORT
from tests.test_app import register_active
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
    assert "0 de 2 episódios assistidos" in view.text
    assert "Próximo: T1 E1 — Pilot" in view.text
    assert f"/episodios/{episode_ids[0]}/visto" not in view.text
    assert "episode-toggle is-static" in view.text
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
    assert "Não há informações de episódios disponíveis para este título." in detail.text
    assert "Atualizar informações" not in detail.text
    assert f"/shows/{show_id}/refresh" not in detail.text
    assert "Voltar ao clube" not in detail.text
    assert detail.status_code == 200


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
    assert f"/shows/{show_id}/refresh" in page.text
    assert "episode-list" not in page.text
    assert "Voltar ao clube" not in page.text


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
    assert f'/shows/{show_id}/remover" method="post" role="none" data-confirm="Remover “Obra Menu” deste clube?"' in page.text
    assert f'/shows/{show_id}/remover" method="post" role="none" onsubmit=' not in page.text
    marked = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/status",
        data={"watch_status": "watched"},
        follow_redirects=False,
    )
    assert marked.status_code == 303
    finished = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=finalizados")
    assert "Obra Menu" in finished.text
    assert "Voltar para Assistindo" in finished.text
    assert f'/shows/{show_id}/remover" method="post" role="none" data-confirm="Remover “Obra Menu” deste clube?"' in finished.text
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

