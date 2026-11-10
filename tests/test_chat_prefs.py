from datetime import timedelta
import re

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.accounts import utcnow
from app.chat_time import chat_clock, chat_day_key
from app.db import SessionLocal, engine
from app.main import app
from app.models import ClubMessage, User
from app.schedules import utc_to_local, wall_to_utc
from tests.test_app import register_active


def test_enter_sends_defaults_on_and_persists_per_user():
    inspector = inspect(engine)
    user_cols = {column["name"] for column in inspector.get_columns("users")}
    assert "enter_sends" in user_cols

    host = TestClient(app)
    other = TestClient(app)
    register_active(host, "enter_host", "enter.host@example.com")
    register_active(other, "enter_other", "enter.other@example.com")

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "enter.host@example.com"))
        peer = db.scalar(select(User).where(User.email == "enter.other@example.com"))
        assert user.enter_sends is True
        assert peer.enter_sends is True
    finally:
        db.close()

    settings = host.get("/conta")
    assert settings.status_code == 200
    assert "Enviar mensagens com Enter" in settings.text
    assert 'role="switch"' in settings.text
    assert "js-enter-sends" in settings.text
    assert ">Salvar<" not in settings.text.split("<h2>Conversas</h2>", 1)[1].split("<h2>Tag exibida</h2>", 1)[0]
    assert 'data-enter-sends="1"' in settings.text
    assert 'class="btn btn-secondary"' in settings.text
    assert "Salvar perfil" in settings.text

    created = host.post("/clubs", data={"name": "Clube Enter"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    chat = host.get(f"/clubs/{club_id}?aba=chat")
    assert 'data-enter-sends="1"' in chat.text
    assert "/static/js/chat-composer.js" in chat.text

    ignored = host.post(
        "/conta/conversas",
        data={"enter_sends": "maybe", "user_id": "999"},
        headers={"x-watchclub-pref": "1"},
    )
    assert ignored.status_code == 400
    assert ignored.json()["ok"] is False
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "enter.host@example.com"))
        assert user.enter_sends is True
    finally:
        db.close()

    saved = host.post(
        "/conta/conversas",
        data={"enter_sends": "0"},
        headers={"x-watchclub-pref": "1"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"ok": True, "enter_sends": False}

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "enter.host@example.com"))
        peer = db.scalar(select(User).where(User.email == "enter.other@example.com"))
        assert bool(user.enter_sends) is False
        assert peer.enter_sends is True
        host_id = user.id
    finally:
        db.close()

    after = host.get("/conta")
    assert 'data-enter-sends="0"' in after.text
    assert 'name="enter_sends"' in after.text
    assert 'aria-checked="false"' in after.text.split('name="enter_sends"', 1)[1][:120]
    chat_on = host.get(f"/clubs/{club_id}?aba=chat")
    assert 'data-enter-sends="0"' in chat_on.text

    inbox = host.get("/mensagens")
    assert 'data-enter-sends="0"' in inbox.text
    assert "/static/js/chat-composer.js" in inbox.text

    other_view = other.get("/conta")
    assert 'data-enter-sends="1"' in other_view.text
    db = SessionLocal()
    try:
        peer = db.scalar(select(User).where(User.email == "enter.other@example.com"))
        assert peer.enter_sends is True
        assert db.get(User, host_id).enter_sends is False
    finally:
        db.close()

    off = host.post(
        "/conta/conversas",
        data={"enter_sends": "1"},
        headers={"x-watchclub-pref": "1"},
    )
    assert off.status_code == 200
    assert off.json()["enter_sends"] is True
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "enter.host@example.com"))
        assert user.enter_sends is True
    finally:
        db.close()
    assert 'data-enter-sends="1"' in host.get("/conta").text


def test_club_chat_uses_shared_day_separators():
    owner = TestClient(app)
    register_active(owner, "club_when", "club.when@example.com")
    created = owner.post("/clubs", data={"name": "Clube Datas"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "club.when@example.com"))
        user_id = user.id
        today_local = utc_to_local(utcnow()).date()
        old_at = wall_to_utc("2026-09-15", "15:06")
        yesterday_at = wall_to_utc((today_local - timedelta(days=1)).isoformat(), "08:06")
        today_first = wall_to_utc(today_local.isoformat(), "13:28")
        today_second = wall_to_utc(today_local.isoformat(), "13:40")
        db.add_all(
            [
                ClubMessage(club_id=club_id, user_id=user_id, body="club-antiga", created_at=old_at),
                ClubMessage(club_id=club_id, user_id=user_id, body="club-ontem", created_at=yesterday_at),
                ClubMessage(club_id=club_id, user_id=user_id, body="club-hoje-1", created_at=today_first),
                ClubMessage(club_id=club_id, user_id=user_id, body="club-hoje-2", created_at=today_second),
            ]
        )
        db.commit()
    finally:
        db.close()

    chat = owner.get(f"/clubs/{club_id}?aba=chat")
    assert chat.status_code == 200
    history = chat.text.split('class="chat-log"', 1)[1]
    days = re.findall(r'data-day="([^"]+)"', history)
    assert days == ["2026-09-15", chat_day_key(yesterday_at), chat_day_key(today_first)]
    assert history.count('class="chat-day-mark"') == 3
    assert "15 de setembro de 2026" in history
    assert ">Ontem<" in history
    assert ">Hoje<" in history
    assert history.index("club-antiga") < history.index("club-ontem") < history.index("club-hoje-1")
    assert chat_clock(old_at) in history
    assert chat_clock(today_first) in history
    assert "15:06" in history
    assert "13:28" in history
    assert "15/09/2026 15:06" not in history
    assert "js-chat-day-float" in chat.text
    assert "/static/js/chat-composer.js" in chat.text
