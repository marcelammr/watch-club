from datetime import timedelta
import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.accounts import utcnow
from app.chat_time import chat_day_key
from app.db import SessionLocal
from app.main import app
from app.models import Club, ClubMember, ClubMessage, User
from app.roles import ROLE_SUPPORT
from app.schedules import utc_to_local, wall_to_utc
from tests.test_app import register_active


def _create_club(http: TestClient, name: str) -> tuple[int, str]:
    created = http.post("/clubs", data={"name": name}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        code = db.get(Club, club_id).join_code
    finally:
        db.close()
    return club_id, code


def _user_id(email: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(User.id).where(User.email == email))
    finally:
        db.close()


def _message_id(club_id: int, body: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(
            select(ClubMessage.id)
            .where(ClubMessage.club_id == club_id, ClubMessage.body == body)
            .order_by(ClubMessage.id.desc())
        )
    finally:
        db.close()


def _join(member: TestClient, code: str) -> None:
    member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)


def test_club_members_delete_own_messages_and_cannot_delete_others():
    owner = TestClient(app)
    member = TestClient(app)
    stranger = TestClient(app)
    register_active(owner, "del_adm", "del.adm@example.com")
    register_active(member, "del_mem", "del.mem@example.com")
    register_active(stranger, "del_out", "del.out@example.com")
    club_id, code = _create_club(owner, "Clube Apagar")
    other_id, _ = _create_club(owner, "Outro Apagar")
    _join(member, code)
    owner.post(f"/clubs/{club_id}/mensagens", data={"body": "aviso do adm"}, follow_redirects=False)
    member.post(f"/clubs/{club_id}/mensagens", data={"body": "fala do membro"}, follow_redirects=False)
    own_id = _message_id(club_id, "fala do membro")
    adm_id = _message_id(club_id, "aviso do adm")

    chat = member.get(f"/clubs/{club_id}?aba=chat")
    assert f'action="/clubs/{club_id}/mensagens/{own_id}/apagar"' in chat.text
    assert f'action="/clubs/{club_id}/mensagens/{adm_id}/apagar"' not in chat.text
    assert "Tem certeza que deseja apagar esta mensagem?" in chat.text

    blocked = member.post(f"/clubs/{club_id}/mensagens/{adm_id}/apagar", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == f"/clubs/{club_id}?aba=chat"
    db = SessionLocal()
    try:
        assert db.get(ClubMessage, adm_id) is not None
    finally:
        db.close()

    outsider = stranger.post(f"/clubs/{club_id}/mensagens/{own_id}/apagar", follow_redirects=False)
    assert outsider.status_code == 303
    assert outsider.headers["location"] in {f"/clubs/{club_id}", f"/clubs/{club_id}?aba=chat"}
    db = SessionLocal()
    try:
        assert db.get(ClubMessage, own_id) is not None
    finally:
        db.close()

    crossed = member.post(f"/clubs/{other_id}/mensagens/{own_id}/apagar", follow_redirects=False)
    assert crossed.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(ClubMessage, own_id) is not None
        assert db.get(ClubMessage, own_id).club_id == club_id
    finally:
        db.close()

    deleted = member.post(f"/clubs/{club_id}/mensagens/{own_id}/apagar", follow_redirects=False)
    assert deleted.status_code == 303
    assert deleted.headers["location"] == f"/clubs/{club_id}?aba=chat"
    after = member.get(f"/clubs/{club_id}?aba=chat")
    assert "fala do membro" not in after.text
    assert "aviso do adm" in after.text
    assert "Mensagem apagada" not in after.text
    db = SessionLocal()
    try:
        assert db.get(ClubMessage, own_id) is None
        assert db.get(ClubMessage, adm_id) is not None
    finally:
        db.close()


def test_club_admin_and_support_can_delete_others_messages():
    owner = TestClient(app)
    helper = TestClient(app)
    member = TestClient(app)
    register_active(owner, "mod_adm", "mod.adm@example.com")
    register_active(helper, "mod_sub", "mod.sub@example.com")
    register_active(member, "mod_mem", "mod.mem@example.com")
    club_id, code = _create_club(owner, "Clube Moderar")
    _join(helper, code)
    _join(member, code)
    helper_id = _user_id("mod.sub@example.com")
    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": ROLE_SUPPORT},
        follow_redirects=False,
    )
    member.post(f"/clubs/{club_id}/mensagens", data={"body": "alvo da moderação"}, follow_redirects=False)
    target_id = _message_id(club_id, "alvo da moderação")
    db = SessionLocal()
    try:
        role = db.scalar(select(ClubMember.role).where(ClubMember.user_id == helper_id, ClubMember.club_id == club_id))
        assert role == ROLE_SUPPORT
    finally:
        db.close()

    sub_chat = helper.get(f"/clubs/{club_id}?aba=chat")
    assert f'action="/clubs/{club_id}/mensagens/{target_id}/apagar"' in sub_chat.text
    adm_chat = owner.get(f"/clubs/{club_id}?aba=chat")
    assert f'action="/clubs/{club_id}/mensagens/{target_id}/apagar"' in adm_chat.text

    removed = helper.post(f"/clubs/{club_id}/mensagens/{target_id}/apagar", follow_redirects=False)
    assert removed.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(ClubMessage, target_id) is None
    finally:
        db.close()

    member.post(f"/clubs/{club_id}/mensagens", data={"body": "segundo alvo"}, follow_redirects=False)
    second_id = _message_id(club_id, "segundo alvo")
    owner.post(f"/clubs/{club_id}/mensagens/{second_id}/apagar", follow_redirects=False)
    chat = member.get(f"/clubs/{club_id}?aba=chat")
    assert "segundo alvo" not in chat.text
    assert "alvo da moderação" not in chat.text


def test_deleting_pinned_message_clears_pin_and_keeps_other_pins():
    owner = TestClient(app)
    member = TestClient(app)
    register_active(owner, "pin_del", "pin.del@example.com")
    register_active(member, "pin_del_m", "pin.del.m@example.com")
    club_id, code = _create_club(owner, "Clube Pin Del")
    _join(member, code)
    owner.post(f"/clubs/{club_id}/mensagens", data={"body": "fica fixada"}, follow_redirects=False)
    owner.post(f"/clubs/{club_id}/mensagens", data={"body": "pode apagar"}, follow_redirects=False)
    pinned_id = _message_id(club_id, "fica fixada")
    other_id = _message_id(club_id, "pode apagar")
    owner.post(f"/clubs/{club_id}/mensagens/{pinned_id}/fixar", follow_redirects=False)
    db = SessionLocal()
    try:
        assert db.get(Club, club_id).pinned_message_id == pinned_id
    finally:
        db.close()

    owner.post(f"/clubs/{club_id}/mensagens/{other_id}/apagar", follow_redirects=False)
    db = SessionLocal()
    try:
        assert db.get(Club, club_id).pinned_message_id == pinned_id
        assert db.get(ClubMessage, pinned_id) is not None
        assert db.get(ClubMessage, other_id) is None
    finally:
        db.close()
    still = owner.get(f"/clubs/{club_id}?aba=chat")
    assert "Mensagem fixada" in still.text
    assert "fica fixada" in still.text
    assert "pode apagar" not in still.text

    owner.post(f"/clubs/{club_id}/mensagens/{pinned_id}/apagar", follow_redirects=False)
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.pinned_message_id is None
        assert db.get(ClubMessage, pinned_id) is None
    finally:
        db.close()
    after = owner.get(f"/clubs/{club_id}?aba=chat")
    assert after.status_code == 200
    assert "Mensagem fixada" not in after.text
    assert "chat-pin-bar" not in after.text
    assert "fica fixada" not in after.text


def test_club_delete_only_message_of_day_drops_separator():
    owner = TestClient(app)
    register_active(owner, "day_del", "day.del@example.com")
    club_id, _code = _create_club(owner, "Clube Datas Del")
    user_id = _user_id("day.del@example.com")
    now = utcnow()
    today_local = utc_to_local(now).date()
    old_at = wall_to_utc("2026-09-15", "15:06")
    yesterday_at = wall_to_utc((today_local - timedelta(days=1)).isoformat(), "08:06")
    db = SessionLocal()
    try:
        db.add_all(
            [
                ClubMessage(club_id=club_id, user_id=user_id, body="keep-old", created_at=old_at),
                ClubMessage(club_id=club_id, user_id=user_id, body="only-yesterday", created_at=yesterday_at),
            ]
        )
        db.commit()
        yesterday_id = db.scalar(
            select(ClubMessage.id).where(ClubMessage.body == "only-yesterday").order_by(ClubMessage.id.desc())
        )
    finally:
        db.close()
    before = owner.get(f"/clubs/{club_id}?aba=chat")
    history = before.text.split('class="chat-log"', 1)[1]
    assert ">Ontem<" in history
    assert chat_day_key(yesterday_at) in re.findall(r'data-day="([^"]+)"', history)
    owner.post(f"/clubs/{club_id}/mensagens/{yesterday_id}/apagar", follow_redirects=False)
    after = owner.get(f"/clubs/{club_id}?aba=chat")
    history = after.text.split('class="chat-log"', 1)[1]
    assert "only-yesterday" not in history
    assert ">Ontem<" not in history
    assert "keep-old" in history
    assert "15 de setembro de 2026" in history
    assert history.count('class="chat-day-mark"') == 1
