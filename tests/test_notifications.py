from sqlalchemy import inspect, select
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models import ClubJoinRequest, ClubMember, Notification, User
from app.notifications import (
    JOIN_STATE_JOINED,
    JOIN_STATE_PENDING,
    JOIN_STATE_RESOLVED,
    TYPE_JOIN_ACCEPTED,
    TYPE_JOIN_REQUEST,
    join_request_state,
    list_notifications,
    mark_all_read,
    mark_read,
    unread_count,
)
from app.roles import PERM_JOINS, PERM_TAG
from tests.test_app import register_active

client = TestClient(app)


def _create_closed_club(http: TestClient, name: str) -> tuple[int, str]:
    created = http.post("/clubs", data={"name": name, "is_closed": "1"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        from app.models import Club

        code = db.get(Club, club_id).join_code
    finally:
        db.close()
    return club_id, code


def _user_id(key: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(User.id).where(User.username_key == key))
    finally:
        db.close()


def _request_and_accept(member: TestClient, owner: TestClient, club_id: int, code: str, username_key: str) -> None:
    asked = member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    assert asked.status_code == 303
    accepted = owner.post(
        f"/clubs/{club_id}/solicitacoes/{_user_id(username_key)}/aceitar",
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert "error=" not in accepted.headers["location"]


def _join_notes(club_id: int, actor_id: int) -> list[Notification]:
    db = SessionLocal()
    try:
        return list(
            db.scalars(
                select(Notification).where(
                    Notification.club_id == club_id,
                    Notification.actor_user_id == actor_id,
                    Notification.type == TYPE_JOIN_REQUEST,
                )
            )
        )
    finally:
        db.close()


def test_notifications_table_exists():
    inspector = inspect(engine)
    assert "notifications" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("notifications")}
    assert columns == {
        "id",
        "user_id",
        "type",
        "club_id",
        "actor_user_id",
        "related_id",
        "created_at",
        "read_at",
    }
    index_cols = {tuple(index["column_names"]) for index in inspector.get_indexes("notifications")}
    assert ("user_id", "created_at") in index_cols
    assert ("user_id", "read_at") in index_cols


def test_new_join_request_notifies_eligible_admins_and_subs_only():
    owner = TestClient(app)
    register_active(owner, "ntf_host", "ntf.host@example.com")
    club_id, code = _create_closed_club(owner, "Sala Aviso")

    coadmin = TestClient(app)
    register_active(coadmin, "ntf_adm2", "ntf.adm2@example.com")
    _request_and_accept(coadmin, owner, club_id, code, "ntf_adm2")
    owner.post(
        f"/clubs/{club_id}/membros/{_user_id('ntf_adm2')}/papel",
        data={"role": "admin"},
        follow_redirects=False,
    )

    helper = TestClient(app)
    register_active(helper, "ntf_sub", "ntf.sub@example.com")
    _request_and_accept(helper, owner, club_id, code, "ntf_sub")
    owner.post(
        f"/clubs/{club_id}/membros/{_user_id('ntf_sub')}/papel",
        data={"role": "support", "support_perm": [PERM_JOINS]},
        follow_redirects=False,
    )

    tagged = TestClient(app)
    register_active(tagged, "ntf_tag", "ntf.tag@example.com")
    _request_and_accept(tagged, owner, club_id, code, "ntf_tag")
    owner.post(
        f"/clubs/{club_id}/membros/{_user_id('ntf_tag')}/papel",
        data={"role": "support", "support_perm": [PERM_TAG]},
        follow_redirects=False,
    )

    member = TestClient(app)
    register_active(member, "ntf_mem", "ntf.mem@example.com")
    _request_and_accept(member, owner, club_id, code, "ntf_mem")

    waiting = TestClient(app)
    register_active(waiting, "ntf_wait", "ntf.wait@example.com")
    asked = waiting.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    assert asked.status_code == 303

    wait_id = _user_id("ntf_wait")
    notes = _join_notes(club_id, wait_id)
    recipients = {item.user_id for item in notes}
    assert recipients == {
        _user_id("ntf_host"),
        _user_id("ntf_adm2"),
        _user_id("ntf_sub"),
    }
    assert wait_id not in recipients
    assert _user_id("ntf_tag") not in recipients
    assert _user_id("ntf_mem") not in recipients
    assert all(item.read_at is None for item in notes)
    assert all(item.type == TYPE_JOIN_REQUEST for item in notes)


def test_duplicate_join_request_does_not_create_notifications():
    owner = TestClient(app)
    register_active(owner, "ntf_dup_h", "ntf.dup.h@example.com")
    club_id, _code = _create_closed_club(owner, "Sala Dup")
    guest = TestClient(app)
    register_active(guest, "ntf_dup_g", "ntf.dup.g@example.com")
    first = guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    assert first.status_code == 303
    guest_id = _user_id("ntf_dup_g")
    before = len(_join_notes(club_id, guest_id))
    assert before >= 1
    second = guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    assert second.status_code == 303
    db = SessionLocal()
    try:
        requests = list(
            db.scalars(
                select(ClubJoinRequest).where(
                    ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == guest_id
                )
            )
        )
        notes = list(
            db.scalars(
                select(Notification).where(
                    Notification.club_id == club_id, Notification.actor_user_id == guest_id
                )
            )
        )
    finally:
        db.close()
    assert len(requests) == 1
    assert len(notes) == before


def test_reject_then_new_request_creates_new_notifications():
    owner = TestClient(app)
    register_active(owner, "ntf_rej_h", "ntf.rej.h@example.com")
    club_id, _code = _create_closed_club(owner, "Sala Recusa")
    guest = TestClient(app)
    register_active(guest, "ntf_rej_g", "ntf.rej.g@example.com")
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    guest_id = _user_id("ntf_rej_g")
    first_ids = {item.id for item in _join_notes(club_id, guest_id)}
    assert first_ids
    refused = owner.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/recusar", follow_redirects=False)
    assert refused.status_code == 303
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    second = _join_notes(club_id, guest_id)
    assert len(second) == len(first_ids) * 2
    assert first_ids < {item.id for item in second}


def test_unread_list_and_mark_read_are_scoped_to_owner():
    owner = TestClient(app)
    register_active(owner, "ntf_rd_h", "ntf.rd.h@example.com")
    club_id, _code = _create_closed_club(owner, "Sala Leitura")
    first = TestClient(app)
    register_active(first, "ntf_rd_a", "ntf.rd.a@example.com")
    first.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    second = TestClient(app)
    register_active(second, "ntf_rd_b", "ntf.rd.b@example.com")
    second.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)

    other = TestClient(app)
    register_active(other, "ntf_rd_o", "ntf.rd.o@example.com")
    other_club, _ = _create_closed_club(other, "Outro Clube")
    stray = TestClient(app)
    register_active(stray, "ntf_rd_s", "ntf.rd.s@example.com")
    stray.post(f"/clubs/{other_club}/solicitar", data={"next": f"/clubs/{other_club}"}, follow_redirects=False)

    host_id = _user_id("ntf_rd_h")
    other_id = _user_id("ntf_rd_o")
    db = SessionLocal()
    try:
        assert unread_count(db, host_id) == 2
        assert unread_count(db, other_id) == 1
        listed = list_notifications(db, host_id)
        assert [item.user_id for item in listed] == [host_id, host_id]
        assert listed[0].actor_user_id == _user_id("ntf_rd_b")
        assert listed[1].actor_user_id == _user_id("ntf_rd_a")
        other_note = db.scalar(select(Notification).where(Notification.user_id == other_id))
        assert mark_read(db, host_id, other_note.id) is None
        db.commit()
        db.refresh(other_note)
        assert other_note.read_at is None
        assert unread_count(db, other_id) == 1

        mine = listed[0]
        assert mark_read(db, host_id, mine.id) is not None
        db.commit()
        assert unread_count(db, host_id) == 1
        assert unread_count(db, other_id) == 1

        changed = mark_all_read(db, host_id)
        db.commit()
        assert changed == 1
        assert unread_count(db, host_id) == 0
        assert unread_count(db, other_id) == 1
    finally:
        db.close()


def test_join_request_state_follows_real_request_not_notification():
    owner = TestClient(app)
    register_active(owner, "ntf_st_h", "ntf.st.h@example.com")
    club_id, _code = _create_closed_club(owner, "Sala Estado")
    guest = TestClient(app)
    register_active(guest, "ntf_st_g", "ntf.st.g@example.com")
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    guest_id = _user_id("ntf_st_g")
    host_id = _user_id("ntf_st_h")

    db = SessionLocal()
    try:
        note = db.scalar(
            select(Notification).where(Notification.user_id == host_id, Notification.actor_user_id == guest_id)
        )
        assert join_request_state(db, note) == JOIN_STATE_PENDING
        unread_before = unread_count(db, host_id)
        created_at = note.created_at
        note_id = note.id
    finally:
        db.close()

    refused = owner.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/recusar", follow_redirects=False)
    assert refused.status_code == 303
    db = SessionLocal()
    try:
        note = db.get(Notification, note_id)
        assert note.created_at == created_at
        assert note.read_at is not None
        assert unread_count(db, host_id) == unread_before - 1
        assert join_request_state(db, note) == JOIN_STATE_RESOLVED
    finally:
        db.close()

    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    accepted = owner.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/aceitar", follow_redirects=False)
    assert accepted.status_code == 303
    db = SessionLocal()
    try:
        old = db.get(Notification, note_id)
        assert join_request_state(db, old) == JOIN_STATE_JOINED
        latest = db.scalar(
            select(Notification)
            .where(Notification.user_id == host_id, Notification.actor_user_id == guest_id)
            .order_by(Notification.id.desc())
        )
        assert latest.id != note_id
        assert join_request_state(db, latest) == JOIN_STATE_JOINED
        assert latest.read_at is not None
    finally:
        db.close()


def _popover(html: str) -> str:
    return html.split('id="bell-popover"', 1)[1].split('id="account-popover"', 1)[0]


def test_bell_badge_and_popover_are_scoped_to_the_viewer():
    owner = TestClient(app)
    register_active(owner, "ui_host", "ui.host@example.com")
    empty = owner.get("/")
    assert empty.status_code == 200
    assert 'class="bell-btn bell-link"' in empty.text
    assert 'href="/notificacoes"' in empty.text
    assert 'class="bell-btn js-bell-toggle"' in empty.text
    assert 'id="bell-popover"' in empty.text
    assert 'id="notice-inbox"' in empty.text
    assert 'aria-labelledby="notice-inbox-title"' in empty.text
    assert 'js-notice-inbox-open' in empty.text
    assert 'class="bell-badge"' not in empty.text
    assert 'title="Notificações" disabled' not in empty.text
    assert "Limpar notificações" not in _popover(empty.text)

    club_id, _code = _create_closed_club(owner, "Sala Sino")
    guest = TestClient(app)
    register_active(guest, "ui_wait", "ui.wait@example.com")
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)

    other = TestClient(app)
    register_active(other, "ui_other", "ui.other@example.com")
    other_club, _ = _create_closed_club(other, "Sala Alheia")
    stray = TestClient(app)
    register_active(stray, "ui_stray", "ui.stray@example.com")
    stray.post(f"/clubs/{other_club}/solicitar", data={"next": f"/clubs/{other_club}"}, follow_redirects=False)

    home = owner.get("/")
    assert 'class="bell-badge"' in home.text
    assert ">1<" in home.text.split("bell-badge", 1)[1][:40]
    popover = _popover(home.text)
    assert "ui_wait" not in popover
    assert "Quer entrar" in popover or "quer entrar" in popover
    assert "Sala Sino" in popover
    assert "Sala Alheia" not in popover
    assert "Aceitar" in popover
    assert "Recusar" in popover
    assert "Ver todas as notificações" in popover
    assert 'class="bell-popover-all js-notice-inbox-open"' in popover
    assert 'href="/notificacoes"' in popover

    outsider = other.get("/")
    other_pop = _popover(outsider.text)
    assert "Sala Sino" not in other_pop
    assert "Sala Alheia" in other_pop
    assert 'class="bell-badge"' not in guest.get("/").text


def test_notifications_page_login_and_actions():
    anon = TestClient(app)
    locked = anon.get("/notificacoes", follow_redirects=False)
    assert locked.status_code == 303
    assert locked.headers["location"].startswith("/login")

    owner = TestClient(app)
    register_active(owner, "pg_host", "pg.host@example.com")
    club_id, code = _create_closed_club(owner, "Sala Pagina")
    helper = TestClient(app)
    register_active(helper, "pg_sub", "pg.sub@example.com")
    _request_and_accept(helper, owner, club_id, code, "pg_sub")
    owner.post(
        f"/clubs/{club_id}/membros/{_user_id('pg_sub')}/papel",
        data={"role": "support", "support_perm": [PERM_JOINS]},
        follow_redirects=False,
    )
    member = TestClient(app)
    register_active(member, "pg_mem", "pg.mem@example.com")
    _request_and_accept(member, owner, club_id, code, "pg_mem")
    waiting = TestClient(app)
    register_active(waiting, "pg_wait", "pg.wait@example.com")
    waiting.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)

    page = owner.get("/notificacoes")
    assert page.status_code == 200
    assert "pg_wait" in page.text or "Pg Wait" in page.text
    assert "Aceitar" in page.text
    assert "Sala Pagina" in page.text
    assert "Sala Alheia" not in page.text

    sub_page = helper.get("/notificacoes")
    assert "Aceitar" in sub_page.text
    mem_page = member.get("/notificacoes")
    mem_main = mem_page.text.split("<main>", 1)[1].split("</main>", 1)[0]
    assert "foi aceito" in mem_main
    assert "Aceitar" not in mem_main

    owner.post(
        f"/clubs/{club_id}/membros/{_user_id('pg_sub')}/papel",
        data={"role": "support", "support_perm": [PERM_TAG]},
        follow_redirects=False,
    )
    lost = helper.get("/notificacoes")
    assert "quer entrar" in lost.text
    assert "Aceitar" not in lost.text
    wait_id = _user_id("pg_wait")
    blocked = helper.post(
        f"/clubs/{club_id}/solicitacoes/{wait_id}/aceitar",
        data={"next": "/notificacoes"},
        follow_redirects=False,
    )
    assert blocked.status_code == 403

    member_try = member.post(
        f"/clubs/{club_id}/solicitacoes/{wait_id}/aceitar",
        data={"next": "/notificacoes"},
        follow_redirects=False,
    )
    assert member_try.status_code == 403


def test_notification_accept_reject_resolved_and_safe_next():
    owner = TestClient(app)
    register_active(owner, "ac_host", "ac.host@example.com")
    club_id, code = _create_closed_club(owner, "Sala Acao")
    coadmin = TestClient(app)
    register_active(coadmin, "ac_adm2", "ac.adm2@example.com")
    _request_and_accept(coadmin, owner, club_id, code, "ac_adm2")
    owner.post(
        f"/clubs/{club_id}/membros/{_user_id('ac_adm2')}/papel",
        data={"role": "admin"},
        follow_redirects=False,
    )

    guest = TestClient(app)
    register_active(guest, "ac_wait", "ac.wait@example.com")
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    wait_id = _user_id("ac_wait")
    note_id = _join_notes(club_id, wait_id)[0].id

    opened = owner.get(f"/notificacoes/{note_id}", follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == f"/clubs/{club_id}"
    db = SessionLocal()
    try:
        assert db.get(Notification, note_id).read_at is not None
    finally:
        db.close()

    other_id = [item.id for item in _join_notes(club_id, wait_id) if item.user_id == _user_id("ac_adm2")][0]
    stolen = owner.get(f"/notificacoes/{other_id}", follow_redirects=False)
    assert stolen.status_code == 404
    db = SessionLocal()
    try:
        assert db.get(Notification, other_id).read_at is None
    finally:
        db.close()

    marked = coadmin.post("/notificacoes/lidas", data={"next": "/notificacoes"}, follow_redirects=False)
    assert marked.status_code == 303
    db = SessionLocal()
    try:
        leftover = db.scalar(
            select(Notification).where(Notification.user_id == _user_id("ac_host"), Notification.read_at.is_(None))
        )
        assert leftover is None or leftover.actor_user_id != wait_id
        co_unread = unread_count(db, _user_id("ac_adm2"))
        host_unread = unread_count(db, _user_id("ac_host"))
    finally:
        db.close()
    assert co_unread == 0
    assert host_unread == 0

    guest2 = TestClient(app)
    register_active(guest2, "ac_g2", "ac.g2@example.com")
    guest2.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    g2 = _user_id("ac_g2")
    accepted = owner.post(
        f"/clubs/{club_id}/solicitacoes/{g2}/aceitar",
        data={"next": "/notificacoes"},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/notificacoes"
    assert guest2.get(f"/clubs/{club_id}").status_code == 200
    second_view = coadmin.get("/notificacoes")
    assert "Entrada aprovada" in second_view.text
    assert f"/solicitacoes/{g2}/aceitar" not in second_view.text

    guest3 = TestClient(app)
    register_active(guest3, "ac_g3", "ac.g3@example.com")
    guest3.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    g3 = _user_id("ac_g3")
    refused = owner.post(
        f"/clubs/{club_id}/solicitacoes/{g3}/recusar",
        data={"next": "/notificacoes"},
        follow_redirects=False,
    )
    assert refused.status_code == 303
    assert refused.headers["location"] == "/notificacoes"
    assert guest3.get(f"/clubs/{club_id}").status_code == 403
    resolved = coadmin.get("/notificacoes")
    assert "Solicitação resolvida" in resolved.text
    assert f"/solicitacoes/{g3}/aceitar" not in resolved.text

    race = coadmin.post(
        f"/clubs/{club_id}/solicitacoes/{g3}/recusar",
        data={"next": "/notificacoes"},
        follow_redirects=False,
    )
    assert race.status_code == 303
    assert "Solicita%C3%A7%C3%A3o%20j%C3%A1%20resolvida" in race.headers["location"] or "resolvida" in race.headers["location"]

    evil = owner.post(
        f"/clubs/{club_id}/solicitacoes/{g2}/aceitar",
        data={"next": "https://evil.example"},
        follow_redirects=False,
    )
    assert evil.status_code == 303
    assert evil.headers["location"].startswith(f"/clubs/{club_id}")
    assert "evil" not in evil.headers["location"]


def test_old_join_notification_does_not_reuse_later_request():
    owner = TestClient(app)
    register_active(owner, "id_host", "id.host@example.com")
    club_id, _code = _create_closed_club(owner, "Sala Identidade")
    guest = TestClient(app)
    register_active(guest, "id_guest", "id.guest@example.com")
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    guest_id = _user_id("id_guest")
    host_id = _user_id("id_host")
    db = SessionLocal()
    try:
        first = db.scalar(
            select(Notification).where(
                Notification.user_id == host_id,
                Notification.actor_user_id == guest_id,
                Notification.type == TYPE_JOIN_REQUEST,
            )
        )
        first_id = first.id
        first_related = first.related_id
        assert first_related
        assert join_request_state(db, first) == JOIN_STATE_PENDING
    finally:
        db.close()
    owner.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/recusar", follow_redirects=False)
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    db = SessionLocal()
    try:
        old = db.get(Notification, first_id)
        newest = db.scalar(
            select(Notification)
            .where(
                Notification.user_id == host_id,
                Notification.actor_user_id == guest_id,
                Notification.type == TYPE_JOIN_REQUEST,
            )
            .order_by(Notification.id.desc())
        )
        assert newest.id != first_id
        assert newest.related_id
        assert join_request_state(db, old) == JOIN_STATE_RESOLVED
        assert join_request_state(db, newest) == JOIN_STATE_PENDING
        assert first_related
        if newest.related_id == first_related:
            assert newest.created_at > old.created_at
    finally:
        db.close()
    page = owner.get("/notificacoes")
    main = page.text.split("<main>", 1)[1].split("</main>", 1)[0]
    assert main.count("Aceitar") == 1
    assert "Solicitação resolvida" in main


def test_accepting_notifies_requester_once():
    owner = TestClient(app)
    register_active(owner, "ap_host", "ap.host@example.com")
    club_id, _code = _create_closed_club(owner, "Sala Aprovado")
    guest = TestClient(app)
    register_active(guest, "ap_guest", "ap.guest@example.com")
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    guest_id = _user_id("ap_guest")
    accepted = owner.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/aceitar", follow_redirects=False)
    assert accepted.status_code == 303
    db = SessionLocal()
    try:
        notes = list(
            db.scalars(
                select(Notification).where(
                    Notification.user_id == guest_id, Notification.type == TYPE_JOIN_ACCEPTED
                )
            )
        )
        assert len(notes) == 1
        assert notes[0].club_id == club_id
        assert unread_count(db, guest_id) >= 1
        note_id = notes[0].id
    finally:
        db.close()
    again = owner.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/aceitar", follow_redirects=False)
    assert again.status_code == 303
    db = SessionLocal()
    try:
        total = list(
            db.scalars(
                select(Notification).where(
                    Notification.user_id == guest_id, Notification.type == TYPE_JOIN_ACCEPTED
                )
            )
        )
        assert len(total) == 1
    finally:
        db.close()
    inbox = guest.get("/notificacoes")
    assert "foi aceito" in inbox.text
    assert "Aceitar" not in inbox.text
    opened = guest.get(f"/notificacoes/{note_id}", follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == f"/clubs/{club_id}"
    assert guest.get(f"/clubs/{club_id}").status_code == 200


def test_full_club_does_not_notify_acceptance():
    owner = TestClient(app)
    register_active(owner, "full_h", "full.h@example.com")
    club_id, _code = _create_closed_club(owner, "Sala Cheia")
    owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Sala Cheia",
            "description": "",
            "rules": "",
            "cover_color": "#3A2348",
            "is_closed": "1",
            "admin_name_color": "#FF5D8F",
            "sub_name_color": "#3DDC84",
            "member_limit": "1",
        },
        follow_redirects=False,
    )
    guest = TestClient(app)
    register_active(guest, "full_g", "full.g@example.com")
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    guest_id = _user_id("full_g")
    blocked = owner.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/aceitar", follow_redirects=False)
    assert blocked.status_code == 303
    assert "lotado" in blocked.headers["location"]
    db = SessionLocal()
    try:
        assert (
            list(
                db.scalars(
                    select(Notification).where(
                        Notification.user_id == guest_id, Notification.type == TYPE_JOIN_ACCEPTED
                    )
                )
            )
            == []
        )
    finally:
        db.close()


def test_bell_endpoint_and_popover_fetch_accept():
    owner = TestClient(app)
    register_active(owner, "ft_host", "ft.host@example.com")
    locked = TestClient(app).get("/notificacoes/sininho")
    assert locked.status_code == 401
    assert TestClient(app).get("/notificacoes/sininho?todas=1").status_code == 401
    empty = owner.get("/notificacoes/sininho")
    assert empty.status_code == 200
    body = empty.json()
    assert body["ok"] is True
    assert body["unread"] == 0
    assert body["badge"] == ""
    assert set(body) <= {"ok", "unread", "badge", "label", "html"}
    assert "inbox_html" not in body
    assert "Nenhuma notificação por enquanto." in body["html"]
    empty_all = owner.get("/notificacoes/sininho?todas=1").json()
    assert "inbox_html" in empty_all
    assert "Nenhuma notificação por enquanto." in empty_all["inbox_html"]
    assert empty_all["unread"] == 0

    other = TestClient(app)
    register_active(other, "ft_other", "ft.other@example.com")
    other_club, _ = _create_closed_club(other, "Outro Sino")
    stray = TestClient(app)
    register_active(stray, "ft_stray", "ft.stray@example.com")
    stray.post(f"/clubs/{other_club}/solicitar", data={"next": "/"}, follow_redirects=False)

    club_id, _code = _create_closed_club(owner, "Sala Fetch")
    guest = TestClient(app)
    register_active(guest, "ft_guest", "ft.guest@example.com")
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    guest_id = _user_id("ft_guest")
    mine = owner.get("/notificacoes/sininho").json()
    assert mine["unread"] == 1
    assert "Sala Fetch" in mine["html"]
    assert "Outro Sino" not in mine["html"]
    assert "Aceitar" in mine["html"]
    pending_inbox = owner.get("/notificacoes/sininho?todas=1").json()
    assert "Aceitar" in pending_inbox["inbox_html"]
    assert "Sala Fetch" in pending_inbox["inbox_html"]
    assert "Outro Sino" not in pending_inbox["inbox_html"]
    assert 'id="notice-inbox-title"' in pending_inbox["inbox_html"]

    member = TestClient(app)
    register_active(member, "ft_mem", "ft.mem@example.com")
    denied = member.post(
        f"/clubs/{club_id}/solicitacoes/{guest_id}/aceitar",
        data={"next": "/"},
        headers={"x-watchclub-notice": "1"},
        follow_redirects=False,
    )
    assert denied.status_code == 403

    accepted = owner.post(
        f"/clubs/{club_id}/solicitacoes/{guest_id}/aceitar",
        data={"next": "/"},
        headers={"x-watchclub-notice": "1"},
        follow_redirects=False,
    )
    assert accepted.status_code == 200
    payload = accepted.json()
    assert payload["ok"] is True
    assert "Aceitar" not in payload["html"]
    assert "inbox_html" in payload
    assert "Aceitar" not in payload["inbox_html"]
    assert "Entrada aprovada" in payload["inbox_html"]
    inbox = owner.get("/notificacoes/sininho?todas=1").json()
    assert "Sala Fetch" in inbox["inbox_html"]
    assert "Outro Sino" not in inbox["inbox_html"]
    assert "js-notice-action" in mine["html"]
    guest_box = guest.get("/notificacoes/sininho?todas=1").json()
    assert "foi aceito" in guest_box["inbox_html"]
    assert "Aceitar" not in guest_box["inbox_html"]
    assert guest.get(f"/clubs/{club_id}").status_code == 200
    db = SessionLocal()
    try:
        assert db.scalar(
            select(Notification.id).where(
                Notification.user_id == guest_id, Notification.type == TYPE_JOIN_ACCEPTED
            )
        )
    finally:
        db.close()


def test_user_clears_only_own_notifications_and_keeps_related_entities():
    owner = TestClient(app)
    other = TestClient(app)
    guest = TestClient(app)
    register_active(owner, "clr_host", "clr.host@example.com")
    register_active(other, "clr_other", "clr.other@example.com")
    register_active(guest, "clr_guest", "clr.guest@example.com")
    club_id, _code = _create_closed_club(owner, "Sala Limpar")
    other_club, _ = _create_closed_club(other, "Sala Alheia Limpar")
    guest.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    stray = TestClient(app)
    register_active(stray, "clr_stray", "clr.stray@example.com")
    stray.post(f"/clubs/{other_club}/solicitar", data={"next": f"/clubs/{other_club}"}, follow_redirects=False)

    host_id = _user_id("clr_host")
    other_id = _user_id("clr_other")
    guest_id = _user_id("clr_guest")
    filled = owner.get("/")
    assert "Limpar notificações" in _popover(filled.text)
    assert 'class="bell-badge"' in filled.text

    locked = TestClient(app).post("/notificacoes/limpar", follow_redirects=False)
    assert locked.status_code == 303
    assert locked.headers["location"].startswith("/login")

    cleared = owner.post(
        "/notificacoes/limpar",
        data={"next": "/", "user_id": str(other_id)},
        follow_redirects=False,
    )
    assert cleared.status_code == 303
    assert cleared.headers["location"] == "/"
    after = owner.get("/")
    assert "Nenhuma notificação por enquanto." in _popover(after.text)
    assert "Limpar notificações" not in _popover(after.text)
    assert 'class="bell-badge"' not in after.text

    db = SessionLocal()
    try:
        assert unread_count(db, host_id) == 0
        assert list_notifications(db, host_id) == []
        assert unread_count(db, other_id) == 1
        assert (
            db.scalar(
                select(ClubJoinRequest).where(
                    ClubJoinRequest.user_id == guest_id, ClubJoinRequest.club_id == club_id
                )
            )
            is not None
        )
        assert (
            db.scalar(select(ClubMember).where(ClubMember.user_id == guest_id, ClubMember.club_id == club_id))
            is None
        )
    finally:
        db.close()

    accepted = owner.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/aceitar", follow_redirects=False)
    assert accepted.status_code == 303
    owner.post("/notificacoes/limpar", data={"next": "/notificacoes"}, follow_redirects=False)
    db = SessionLocal()
    try:
        assert (
            db.scalar(select(ClubMember).where(ClubMember.user_id == guest_id, ClubMember.club_id == club_id))
            is not None
        )
        assert db.scalar(
            select(Notification.id).where(
                Notification.user_id == guest_id, Notification.type == TYPE_JOIN_ACCEPTED
            )
        )
        assert list_notifications(db, host_id) == []
    finally:
        db.close()
    empty_page = owner.get("/notificacoes")
    assert "Nenhuma notificação por enquanto." in empty_page.text
    assert "Limpar notificações" not in empty_page.text

