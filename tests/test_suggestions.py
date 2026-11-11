from urllib.parse import unquote

from sqlalchemy import inspect, select
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models import Notification, Suggestion, User
from app.notifications import TYPE_SUGGESTION, notification_cards, notification_destination, unread_count
from app.suggestions import DESCRIPTION_MAX, STATUS_DONE, STATUS_REVIEWING, STATUS_SENT, TITLE_MAX
from tests.test_app import register_active


def _grant_site_admin(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        user.is_site_admin = True
        db.commit()
    finally:
        db.close()


def _suggestions_board(html: str) -> str:
    marker = 'aria-label="Filas de sugestões"'
    if marker not in html:
        return html
    return html.split(marker, 1)[1]


def _user_id(email: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(User.id).where(User.email == email))
    finally:
        db.close()


def test_suggestions_schema_exists():
    tables = inspect(engine).get_table_names()
    assert "suggestions" in tables
    cols = {column["name"] for column in inspect(engine).get_columns("suggestions")}
    assert {
        "id",
        "user_id",
        "title",
        "description",
        "status",
        "is_archived",
        "created_at",
        "updated_at",
    } <= cols


def test_guest_cannot_open_suggestion_box():
    guest = TestClient(app)
    page = guest.get("/sugestoes", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/login"
    posted = guest.post(
        "/sugestoes",
        data={"title": "Ideia", "description": "Texto"},
        follow_redirects=False,
    )
    assert posted.status_code == 303
    assert posted.headers["location"] == "/login"


def test_member_can_open_and_submit_suggestion():
    person = TestClient(app)
    register_active(person, "sug_ok", "sug.ok@example.com")
    page = person.get("/sugestoes")
    assert page.status_code == 200
    assert "Caixinha de sugestão" in page.text
    assert "Minhas sugestões" in page.text
    assert 'aria-label="Caixinha de sugestão"' in page.text
    assert "Você ainda não enviou sugestões." in page.text
    created = person.post(
        "/sugestoes",
        data={"title": "Filtro na agenda", "description": "Queria filtrar por clube."},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"].startswith("/sugestoes")
    listed = person.get(created.headers["location"])
    assert "Filtro na agenda" in listed.text
    assert "Queria filtrar por clube." in listed.text
    assert "Enviada" in listed.text
    assert "Sugestão enviada" in listed.text
    db = SessionLocal()
    try:
        item = db.scalar(select(Suggestion).where(Suggestion.title == "Filtro na agenda"))
        assert item is not None
        assert item.user_id == _user_id("sug.ok@example.com")
        assert item.status == STATUS_SENT
        assert item.is_archived is False
        assert item.description == "Queria filtrar por clube."
    finally:
        db.close()


def test_suggestion_title_and_description_are_required_and_limited():
    person = TestClient(app)
    register_active(person, "sug_val", "sug.val@example.com")
    blank_title = person.post(
        "/sugestoes",
        data={"title": "   ", "description": "Texto ok"},
        follow_redirects=False,
    )
    assert blank_title.status_code == 303
    assert "título" in unquote(blank_title.headers["location"]).lower()
    blank_body = person.post(
        "/sugestoes",
        data={"title": "Título ok", "description": "  "},
        follow_redirects=False,
    )
    assert blank_body.status_code == 303
    assert "descrição" in unquote(blank_body.headers["location"]).lower()
    long_title = person.post(
        "/sugestoes",
        data={"title": "A" * (TITLE_MAX + 1), "description": "Texto ok"},
        follow_redirects=False,
    )
    assert long_title.status_code == 303
    assert str(TITLE_MAX) in long_title.headers["location"]
    long_body = person.post(
        "/sugestoes",
        data={"title": "Título ok", "description": "B" * (DESCRIPTION_MAX + 1)},
        follow_redirects=False,
    )
    assert long_body.status_code == 303
    assert str(DESCRIPTION_MAX) in long_body.headers["location"]
    db = SessionLocal()
    try:
        count = db.scalar(
            select(Suggestion.id).where(Suggestion.user_id == _user_id("sug.val@example.com"))
        )
        assert count is None
    finally:
        db.close()


def test_member_does_not_see_another_users_suggestion():
    author = TestClient(app)
    other = TestClient(app)
    register_active(author, "sug_a", "sug.a@example.com")
    register_active(other, "sug_b", "sug.b@example.com")
    author.post(
        "/sugestoes",
        data={"title": "Segredo da A", "description": "Só a autora vê."},
        follow_redirects=False,
    )
    page = other.get("/sugestoes")
    assert "Segredo da A" not in page.text
    assert "Só a autora vê." not in page.text


def test_common_user_cannot_manage_suggestions():
    person = TestClient(app)
    register_active(person, "sug_noadmin", "sug.noadmin@example.com")
    person.post(
        "/sugestoes",
        data={"title": "Ideia comum", "description": "Não deve gerenciar."},
        follow_redirects=False,
    )
    listing = person.get("/admin/sugestoes", follow_redirects=False)
    assert listing.status_code == 303
    assert listing.headers["location"].startswith("/")
    db = SessionLocal()
    try:
        item_id = db.scalar(select(Suggestion.id).where(Suggestion.title == "Ideia comum"))
    finally:
        db.close()
    status = person.post(
        f"/admin/sugestoes/{item_id}/status",
        data={"status": STATUS_DONE},
        follow_redirects=False,
    )
    archive = person.post(f"/admin/sugestoes/{item_id}/arquivar", follow_redirects=False)
    assert status.status_code == 303
    assert archive.status_code == 303
    db = SessionLocal()
    try:
        item = db.get(Suggestion, item_id)
        assert item.status == STATUS_SENT
        assert item.is_archived is False
    finally:
        db.close()


def test_admin_lists_updates_status_and_archives_without_deleting():
    author = TestClient(app)
    admin = TestClient(app)
    register_active(author, "sug_author", "sug.author@example.com")
    register_active(admin, "sug_admin", "sug.admin@example.com")
    _grant_site_admin("sug.admin@example.com")
    author.post(
        "/sugestoes",
        data={"title": "Modo compacto", "description": "Uma lista mais curta."},
        follow_redirects=False,
    )
    hub = admin.get("/admin")
    assert hub.status_code == 200
    assert 'href="/admin/sugestoes"' in hub.text
    assert "Áreas restritas do Watch Club" not in hub.text
    listing = admin.get("/admin/sugestoes")
    assert listing.status_code == 200
    assert 'href="/admin/cadastros"' not in listing.text
    assert 'href="/admin/sugestoes"' in listing.text
    assert 'href="/admin/denuncias"' in listing.text
    assert "Recebidas" in listing.text
    assert "Arquivadas" in listing.text
    assert "Modo compacto" in listing.text
    assert "@sug_author" in listing.text
    summary = listing.text.split("suggestion-panel", 1)[0]
    assert "Modo compacto" in summary
    assert "Uma lista mais curta." not in summary
    assert "Uma lista mais curta." in listing.text.split("suggestion-panel", 1)[1]
    db = SessionLocal()
    try:
        item_id = db.scalar(select(Suggestion.id).where(Suggestion.title == "Modo compacto"))
    finally:
        db.close()
    updated = admin.post(
        f"/admin/sugestoes/{item_id}/status",
        data={"status": STATUS_REVIEWING},
        follow_redirects=False,
    )
    assert updated.status_code == 303
    reviewing = admin.get("/admin/sugestoes")
    assert "Em análise" in reviewing.text
    done = admin.post(
        f"/admin/sugestoes/{item_id}/status",
        data={"status": STATUS_DONE},
        follow_redirects=False,
    )
    assert done.status_code == 303
    archived = admin.post(f"/admin/sugestoes/{item_id}/arquivar", follow_redirects=False)
    assert archived.status_code == 303
    main_list = admin.get("/admin/sugestoes")
    assert "Modo compacto" not in _suggestions_board(main_list.text)
    stored = admin.get("/admin/sugestoes?aba=arquivadas")
    assert "Modo compacto" in stored.text
    assert "Concluída" in stored.text
    author_page = author.get("/sugestoes")
    assert "Modo compacto" in author_page.text
    assert "Concluída" in author_page.text
    db = SessionLocal()
    try:
        item = db.get(Suggestion, item_id)
        assert item is not None
        assert item.status == STATUS_DONE
        assert item.is_archived is True
    finally:
        db.close()


def test_suggestion_html_is_escaped():
    person = TestClient(app)
    register_active(person, "sug_xss", "sug.xss@example.com")
    person.post(
        "/sugestoes",
        data={"title": "<b>Negrito</b>", "description": "<script>alert(1)</script>"},
        follow_redirects=False,
    )
    page = person.get("/sugestoes")
    assert "<b>Negrito</b>" not in page.text
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;b&gt;Negrito&lt;/b&gt;" in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_suggestion_notifies_active_site_admins_only():
    author = TestClient(app)
    admin_a = TestClient(app)
    admin_b = TestClient(app)
    idle = TestClient(app)
    common = TestClient(app)
    register_active(author, "sug_bell_a", "sug.bell.a@example.com")
    register_active(admin_a, "sug_bell_adm1", "sug.bell.adm1@example.com")
    register_active(admin_b, "sug_bell_adm2", "sug.bell.adm2@example.com")
    register_active(idle, "sug_bell_idle", "sug.bell.idle@example.com")
    register_active(common, "sug_bell_mem", "sug.bell.mem@example.com")
    _grant_site_admin("sug.bell.adm1@example.com")
    _grant_site_admin("sug.bell.adm2@example.com")
    db = SessionLocal()
    try:
        idle_user = db.scalar(select(User).where(User.email == "sug.bell.idle@example.com"))
        idle_user.is_site_admin = True
        idle_user.is_active = False
        db.commit()
    finally:
        db.close()
    created = author.post(
        "/sugestoes",
        data={"title": "Adicionar enquetes nos clubes", "description": "Uma enquete simples."},
        follow_redirects=False,
    )
    assert created.status_code == 303
    db = SessionLocal()
    try:
        item = db.scalar(select(Suggestion).where(Suggestion.title == "Adicionar enquetes nos clubes"))
        notes = list(
            db.scalars(
                select(Notification).where(
                    Notification.type == TYPE_SUGGESTION,
                    Notification.related_id == item.id,
                )
            )
        )
        recipients = {note.user_id for note in notes}
        assert {_user_id("sug.bell.adm1@example.com"), _user_id("sug.bell.adm2@example.com")} <= recipients
        assert _user_id("sug.bell.a@example.com") not in recipients
        assert _user_id("sug.bell.mem@example.com") not in recipients
        assert _user_id("sug.bell.idle@example.com") not in recipients
        assert all(note.actor_user_id == item.user_id for note in notes)
        dest = notification_destination(notes[0])
        assert dest == f"/admin/sugestoes?sugestao={item.id}"
        assert unread_count(db, _user_id("sug.bell.adm1@example.com")) >= 1
        assert unread_count(db, _user_id("sug.bell.mem@example.com")) == 0
        cards = notification_cards(db, _user_id("sug.bell.adm1@example.com"))
        titles = [card["notification"].type for card in cards]
        assert TYPE_SUGGESTION in titles
        suggestion_card = next(card for card in cards if card["notification"].type == TYPE_SUGGESTION)
        assert suggestion_card["actor"].username == "sug_bell_a"
        assert suggestion_card["suggestion"].title == "Adicionar enquetes nos clubes"
        admin_a_id = _user_id("sug.bell.adm1@example.com")
        note_id = next(note.id for note in notes if note.user_id == admin_a_id)
        item_id = item.id
    finally:
        db.close()
    inbox = admin_a.get("/notificacoes")
    assert "Nova sugestão recebida" in inbox.text
    assert "@sug_bell_a enviou uma sugestão: “Adicionar enquetes nos clubes”" in inbox.text
    opened = admin_a.get(f"/notificacoes/{note_id}", follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == f"/admin/sugestoes?sugestao={item_id}"
    landed = admin_a.get(opened.headers["location"])
    assert landed.status_code == 200
    assert f'id="sugestao-{item_id}"' in landed.text
    assert "open" in landed.text.split(f'id="sugestao-{item_id}"', 1)[1][:80]
    common_inbox = common.get("/notificacoes")
    assert "Nova sugestão recebida" not in common_inbox.text


def test_admin_tabs_keep_received_and_archived_apart():
    author = TestClient(app)
    admin = TestClient(app)
    register_active(author, "sug_tabs_a", "sug.tabs.a@example.com")
    register_active(admin, "sug_tabs_adm", "sug.tabs.adm@example.com")
    _grant_site_admin("sug.tabs.adm@example.com")
    author.post(
        "/sugestoes",
        data={"title": "Recebida visível", "description": "Deve ficar em recebidas."},
        follow_redirects=False,
    )
    author.post(
        "/sugestoes",
        data={"title": "Vai arquivar", "description": "Deve sair da lista principal."},
        follow_redirects=False,
    )
    db = SessionLocal()
    try:
        archive_id = db.scalar(select(Suggestion.id).where(Suggestion.title == "Vai arquivar"))
    finally:
        db.close()
    admin.post(f"/admin/sugestoes/{archive_id}/arquivar", follow_redirects=False)
    received = admin.get("/admin/sugestoes")
    archived = admin.get("/admin/sugestoes?aba=arquivadas")
    received_board = _suggestions_board(received.text)
    archived_board = _suggestions_board(archived.text)
    assert "Recebida visível" in received_board
    assert "Vai arquivar" not in received_board
    assert "Vai arquivar" in archived_board
    assert "Recebida visível" not in archived_board
    cadastros = admin.get("/admin/cadastros", follow_redirects=False)
    assert cadastros.status_code == 303
    assert cadastros.headers["location"] == "/admin/sugestoes"
