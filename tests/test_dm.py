from datetime import timedelta
from pathlib import Path
import re
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.accounts import utcnow
from app.chat_time import chat_clock, chat_day_key
from app.db import SessionLocal, engine
from app.main import app
from app.friends import unread_dm_count
from app.models import DirectMessage, User
from app.schedules import utc_to_local, wall_to_utc
from tests.test_app import register_active

CSS = Path(__file__).resolve().parents[1] / "app" / "static" / "src" / "input.css"


def _ids(*emails: str) -> dict[str, int]:
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(User).where(User.email.in_(emails))))
        return {row.email: row.id for row in rows}
    finally:
        db.close()


def _befriend(a: TestClient, b: TestClient, a_name: str, b_name: str) -> None:
    invited = a.post(f"/amigos/{b_name}/convidar", data={"next": "/amigos"}, follow_redirects=False)
    assert invited.status_code == 303
    accepted = b.post(f"/amigos/{a_name}/aceitar", data={"next": "/amigos"}, follow_redirects=False)
    assert accepted.status_code == 303


def test_direct_message_schema_is_additive():
    inspector = inspect(engine)
    cols = {column["name"] for column in inspector.get_columns("direct_messages")}
    assert {"id", "sender_id", "recipient_id", "body", "created_at", "read_at"} <= cols
    indexes = {index["name"] for index in inspector.get_indexes("direct_messages")}
    assert "ix_dm_pair" in indexes


def test_conversations_require_login():
    guest = TestClient(app)
    listed = guest.get("/mensagens", follow_redirects=False)
    assert listed.status_code == 303
    assert listed.headers["location"] == "/login"


def test_dm_pair_history_unread_list_and_permissions():
    host = TestClient(app)
    guest = TestClient(app)
    other = TestClient(app)
    register_active(host, "dm_host", "dm.host@example.com", name="Host DM")
    register_active(guest, "dm_guest", "dm.guest@example.com", name="Guest DM")
    register_active(other, "dm_other", "dm.other@example.com", name="Other DM")

    own = host.get("/u/dm_host")
    assert own.status_code == 200
    assert ">Mensagem<" not in own.text
    assert 'href="/mensagens/dm_host"' not in own.text

    stranger_profile = other.get("/u/dm_host")
    assert ">Mensagem<" not in stranger_profile.text
    assert 'href="/mensagens/dm_host"' not in stranger_profile.text

    blocked = other.post("/mensagens/dm_host", data={"body": "oi estranho"}, follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/u/dm_host"
    peek = other.get("/mensagens/dm_host", follow_redirects=False)
    assert peek.status_code == 303
    assert peek.headers["location"] == "/u/dm_host"

    empty_list = host.get("/mensagens")
    assert empty_list.status_code == 200
    assert "Conversas" in empty_list.text
    assert "Nenhuma conversa ainda" in empty_list.text
    assert "tvmaze" not in empty_list.text.lower()
    assert "themoviedb" not in empty_list.text.lower()

    opened = host.get("/mensagens/dm_guest", follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == "/u/dm_guest"

    _befriend(host, guest, "dm_host", "dm_guest")
    _befriend(host, other, "dm_host", "dm_other")

    allowed = host.get("/u/dm_guest")
    assert ">Mensagem<" in allowed.text
    assert 'href="/mensagens/dm_guest"' in allowed.text

    still_empty = host.get("/mensagens")
    assert "Guest DM" not in still_empty.text
    assert "Nenhuma conversa ainda" in still_empty.text

    blank = host.post("/mensagens/dm_guest", data={"body": "   "}, follow_redirects=False)
    assert blank.status_code == 303
    assert "error=" in blank.headers["location"]
    db = SessionLocal()
    try:
        assert db.scalar(select(DirectMessage).where(DirectMessage.body == "   ")) is None
        assert db.scalar(select(DirectMessage).where(DirectMessage.body == "")) is None
    finally:
        db.close()

    first = host.post("/mensagens/dm_guest", data={"body": "vamos assistir hoje?"}, follow_redirects=False)
    assert first.status_code == 303
    assert first.headers["location"] == "/mensagens/dm_guest"
    reply = guest.post("/mensagens/dm_host", data={"body": "beleza, depois te mando"}, follow_redirects=False)
    assert reply.status_code == 303
    later = host.post("/mensagens/dm_other", data={"body": "oi lucas"}, follow_redirects=False)
    assert later.status_code == 303

    ids = _ids("dm.host@example.com", "dm.guest@example.com", "dm.other@example.com")
    db = SessionLocal()
    try:
        pair = list(
            db.scalars(
                select(DirectMessage).where(
                    DirectMessage.body.in_(["vamos assistir hoje?", "beleza, depois te mando"])
                )
            )
        )
        assert len(pair) == 2
        people = {(item.sender_id, item.recipient_id) for item in pair}
        assert people == {
            (ids["dm.host@example.com"], ids["dm.guest@example.com"]),
            (ids["dm.guest@example.com"], ids["dm.host@example.com"]),
        }
        unread_for_host = list(
            db.scalars(
                select(DirectMessage).where(
                    DirectMessage.recipient_id == ids["dm.host@example.com"],
                    DirectMessage.read_at.is_(None),
                )
            )
        )
        assert [item.body for item in unread_for_host] == ["beleza, depois te mando"]
        sent_by_host = list(
            db.scalars(
                select(DirectMessage).where(
                    DirectMessage.sender_id == ids["dm.host@example.com"],
                    DirectMessage.body == "vamos assistir hoje?",
                )
            )
        )
        assert sent_by_host[0].read_at is None
    finally:
        db.close()

    inbox = host.get("/mensagens")
    assert inbox.status_code == 200
    assert inbox.text.index("Other DM") < inbox.text.index("Guest DM")
    assert "Você: oi lucas" in inbox.text
    assert "beleza, depois te mando" in inbox.text
    assert "dm-unread-dot" in inbox.text
    assert inbox.text.count("dm-unread-dot") == 1

    thread = host.get("/mensagens/dm_guest")
    assert thread.status_code == 200
    assert "vamos assistir hoje?" in thread.text
    guest.post("/presenca", data={"status": "away", "prefer": "1"})
    away_thread = host.get("/mensagens/dm_guest")
    head_html = away_thread.text.split('class="dm-head"', 1)[1].split("</header>", 1)[0]
    avatar_html, _, copy_html = head_html.partition("dm-head-copy")
    assert "Ausente" in copy_html
    assert "presence-moon" not in copy_html
    assert 'class="dot"' not in copy_html
    assert 'data-presence="away"' in avatar_html
    assert "presence-moon" in avatar_html
    assert "beleza, depois te mando" in thread.text
    history = thread.text.split('class="chat-log"', 1)[1]
    assert history.index("vamos assistir hoje?") < history.index("beleza, depois te mando")
    assert "is-mine" in thread.text
    assert 'action="/mensagens/dm_guest"' in thread.text
    assert "Ver perfil" in thread.text
    assert 'href="/u/dm_guest"' in thread.text
    assert "Buscar" in thread.text
    assert "dm-peer" in thread.text
    assert "Nenhuma API" not in thread.text

    after_read = host.get("/mensagens")
    assert "dm-unread-dot" not in after_read.text
    db = SessionLocal()
    try:
        leftover = db.scalar(
            select(DirectMessage).where(
                DirectMessage.recipient_id == ids["dm.host@example.com"],
                DirectMessage.read_at.is_(None),
            )
        )
        assert leftover is None
        still_unread_for_guest = db.scalar(
            select(DirectMessage).where(
                DirectMessage.recipient_id == ids["dm.guest@example.com"],
                DirectMessage.read_at.is_(None),
                DirectMessage.body == "vamos assistir hoje?",
            )
        )
        assert still_unread_for_guest is not None
    finally:
        db.close()

    same = guest.get("/mensagens/dm_host")
    assert "vamos assistir hoje?" in same.text
    guest_inbox = guest.get("/mensagens")
    assert guest_inbox.text.count('href="/mensagens/dm_host"') == 1
    assert guest_inbox.text.count("dm-inbox-row") == 1
    assert "Other DM" not in guest_inbox.text

    outsider = other.get("/mensagens/dm_guest", follow_redirects=False)
    assert outsider.status_code == 303
    assert outsider.headers["location"] == "/u/dm_guest"
    sneak = other.post("/mensagens/dm_guest", data={"body": "intruso"}, follow_redirects=False)
    assert sneak.status_code == 303
    assert sneak.headers["location"] == "/u/dm_guest"
    db = SessionLocal()
    try:
        assert db.scalar(select(DirectMessage).where(DirectMessage.body == "intruso")) is None
    finally:
        db.close()


def test_dm_pages_do_not_call_external_catalog():
    member = TestClient(app)
    register_active(member, "dm_local", "dm.local@example.com")
    with (
        patch("app.services.tvmaze.search_shows") as tvmaze,
        patch("app.services.tmdb.search_movies") as tmdb,
        patch("app.services.news.fetch_general_news") as news,
    ):
        page = member.get("/mensagens")
        thread_miss = member.get("/mensagens/dm_local", follow_redirects=False)
    assert page.status_code == 200
    assert "dm-shell" in page.text
    assert thread_miss.status_code == 303
    tvmaze.assert_not_called()
    tmdb.assert_not_called()
    news.assert_not_called()


def test_dm_day_separators_and_clock():
    host = TestClient(app)
    guest = TestClient(app)
    register_active(host, "dm_when_a", "dm.when.a@example.com", name="When A")
    register_active(guest, "dm_when_b", "dm.when.b@example.com", name="When B")
    _befriend(host, guest, "dm_when_a", "dm_when_b")
    ids = _ids("dm.when.a@example.com", "dm.when.b@example.com")
    sender = ids["dm.when.a@example.com"]
    recipient = ids["dm.when.b@example.com"]
    now = utcnow()
    today_local = utc_to_local(now).date()
    old_at = wall_to_utc("2026-09-15", "15:06")
    yesterday_at = wall_to_utc((today_local - timedelta(days=1)).isoformat(), "08:06")
    today_first = wall_to_utc(today_local.isoformat(), "21:14")
    today_second = wall_to_utc(today_local.isoformat(), "21:20")
    db = SessionLocal()
    try:
        db.add_all(
            [
                DirectMessage(sender_id=sender, recipient_id=recipient, body="msg-antiga", created_at=old_at),
                DirectMessage(sender_id=sender, recipient_id=recipient, body="msg-ontem", created_at=yesterday_at),
                DirectMessage(sender_id=sender, recipient_id=recipient, body="msg-hoje-1", created_at=today_first),
                DirectMessage(sender_id=sender, recipient_id=recipient, body="msg-hoje-2", created_at=today_second),
            ]
        )
        db.commit()
    finally:
        db.close()

    thread = host.get("/mensagens/dm_when_b")
    assert thread.status_code == 200
    history = thread.text.split('class="chat-log"', 1)[1]
    days = re.findall(r'data-day="([^"]+)"', history)
    assert days == ["2026-09-15", chat_day_key(yesterday_at), chat_day_key(today_first)]
    assert history.count('class="chat-day-mark"') == 3
    assert history.count("15 de setembro de 2026") == 1
    assert history.count(">Ontem<") == 1
    assert history.count(">Hoje<") == 1
    assert history.index("15 de setembro de 2026") < history.index(">Ontem<") < history.index(">Hoje<")
    assert history.index("msg-antiga") < history.index("msg-ontem") < history.index("msg-hoje-1") < history.index(
        "msg-hoje-2"
    )
    assert chat_clock(old_at) in history
    assert "15:06" in history
    assert "08:06" in history
    assert "21:14" in history
    assert "21:20" in history
    assert "15/09/2026 15:06" not in history
    assert history.count(">Hoje<") == 1
    assert "chat-day-float" in thread.text


def test_dm_sender_deletes_own_message_and_updates_preview_unread():
    host = TestClient(app)
    guest = TestClient(app)
    outsider = TestClient(app)
    register_active(host, "dm_del_a", "dm.del.a@example.com", name="Del A")
    register_active(guest, "dm_del_b", "dm.del.b@example.com", name="Del B")
    register_active(outsider, "dm_del_c", "dm.del.c@example.com", name="Del C")
    _befriend(host, guest, "dm_del_a", "dm_del_b")
    host.post("/mensagens/dm_del_b", data={"body": "msg-a"}, follow_redirects=False)
    host.post("/mensagens/dm_del_b", data={"body": "msg-b"}, follow_redirects=False)
    last = host.post("/mensagens/dm_del_b", data={"body": "msg-c"}, follow_redirects=False)
    assert last.status_code == 303
    ids = _ids("dm.del.a@example.com", "dm.del.b@example.com", "dm.del.c@example.com")
    db = SessionLocal()
    try:
        rows = list(
            db.scalars(
                select(DirectMessage)
                .where(DirectMessage.sender_id == ids["dm.del.a@example.com"])
                .order_by(DirectMessage.id)
            )
        )
        a_id, b_id, c_id = [row.id for row in rows]
        assert unread_dm_count(db, ids["dm.del.b@example.com"]) == 3
    finally:
        db.close()

    inbox = host.get("/mensagens")
    assert "Você: msg-c" in inbox.text
    thread = host.get("/mensagens/dm_del_b")
    assert f'action="/mensagens/dm_del_b/{c_id}/apagar"' in thread.text
    assert "js-confirm-delete" in thread.text
    assert "Tem certeza que deseja apagar esta mensagem?" not in thread.text

    stolen = guest.post(f"/mensagens/dm_del_a/{c_id}/apagar", follow_redirects=False)
    assert stolen.status_code == 303
    assert stolen.headers["location"] == "/mensagens/dm_del_a"
    db = SessionLocal()
    try:
        assert db.get(DirectMessage, c_id) is not None
    finally:
        db.close()

    sneak = outsider.post(f"/mensagens/dm_del_b/{c_id}/apagar", follow_redirects=False)
    assert sneak.status_code == 303
    assert sneak.headers["location"] == "/u/dm_del_b"
    db = SessionLocal()
    try:
        assert db.get(DirectMessage, c_id) is not None
    finally:
        db.close()

    deleted = host.post(f"/mensagens/dm_del_b/{c_id}/apagar", follow_redirects=False)
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/mensagens/dm_del_b"
    after = host.get("/mensagens/dm_del_b")
    assert "msg-c" not in after.text
    assert "msg-b" in after.text
    assert "Mensagem apagada" not in after.text
    inbox = host.get("/mensagens")
    assert "Você: msg-b" in inbox.text
    assert "Você: msg-c" not in inbox.text
    db = SessionLocal()
    try:
        assert db.get(DirectMessage, c_id) is None
        assert unread_dm_count(db, ids["dm.del.b@example.com"]) == 2
    finally:
        db.close()
    guest_thread = guest.get("/mensagens/dm_del_a")
    assert f'action="/mensagens/dm_del_a/{b_id}/apagar"' not in guest_thread.text
    assert "msg-c" not in guest_thread.text

    host.post(f"/mensagens/dm_del_b/{b_id}/apagar", follow_redirects=False)
    host.post(f"/mensagens/dm_del_b/{a_id}/apagar", follow_redirects=False)
    empty = host.get("/mensagens")
    assert "Del B" not in empty.text
    assert "Nenhuma conversa ainda" in empty.text
    db = SessionLocal()
    try:
        leftover = list(
            db.scalars(
                select(DirectMessage).where(
                    DirectMessage.sender_id == ids["dm.del.a@example.com"],
                    DirectMessage.recipient_id == ids["dm.del.b@example.com"],
                )
            )
        )
        assert leftover == []
        assert unread_dm_count(db, ids["dm.del.b@example.com"]) == 0
    finally:
        db.close()
    back = host.post("/mensagens/dm_del_b", data={"body": "voltou"}, follow_redirects=False)
    assert back.status_code == 303
    listed = host.get("/mensagens")
    assert "Você: voltou" in listed.text


def test_dm_delete_only_message_of_day_drops_separator():
    host = TestClient(app)
    guest = TestClient(app)
    register_active(host, "dm_day_a", "dm.day.a@example.com")
    register_active(guest, "dm_day_b", "dm.day.b@example.com")
    _befriend(host, guest, "dm_day_a", "dm_day_b")
    ids = _ids("dm.day.a@example.com", "dm.day.b@example.com")
    sender = ids["dm.day.a@example.com"]
    recipient = ids["dm.day.b@example.com"]
    now = utcnow()
    today_local = utc_to_local(now).date()
    old_at = wall_to_utc("2026-09-15", "15:06")
    yesterday_at = wall_to_utc((today_local - timedelta(days=1)).isoformat(), "08:06")
    db = SessionLocal()
    try:
        db.add_all(
            [
                DirectMessage(sender_id=sender, recipient_id=recipient, body="keep-old", created_at=old_at),
                DirectMessage(sender_id=sender, recipient_id=recipient, body="only-yesterday", created_at=yesterday_at),
            ]
        )
        db.commit()
        yesterday_id = db.scalar(
            select(DirectMessage.id).where(DirectMessage.body == "only-yesterday").order_by(DirectMessage.id.desc())
        )
    finally:
        db.close()
    before = host.get("/mensagens/dm_day_b")
    history = before.text.split('class="chat-log"', 1)[1]
    assert ">Ontem<" in history
    host.post(f"/mensagens/dm_day_b/{yesterday_id}/apagar", follow_redirects=False)
    after = host.get("/mensagens/dm_day_b")
    history = after.text.split('class="chat-log"', 1)[1]
    assert "only-yesterday" not in history
    assert ">Ontem<" not in history
    assert "keep-old" in history
    assert "15 de setembro de 2026" in history
    assert history.count('class="chat-day-mark"') == 1


def test_dm_layout_uses_global_scale_breakpoints():
    css = CSS.read_text(encoding="utf-8")
    assert ".dm-shell" in css
    assert "max-width: 720px" in css
    assert ".dm-shell.is-thread .dm-inbox" in css
    assert "var(--ui-main)" in css
    assert "tvmaze" not in css.lower()
    assert "themoviedb" not in css.lower()
