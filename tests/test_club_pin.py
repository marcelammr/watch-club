from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.db import SessionLocal, engine
from app.main import app
from app.markup import pin_preview
from app.models import Club, ClubMember, ClubMessage, User
from app.roles import ROLE_SUPPORT
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


def _last_message_id(club_id: int, body: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(
            select(ClubMessage.id)
            .where(ClubMessage.club_id == club_id, ClubMessage.body == body)
            .order_by(ClubMessage.id.desc())
        )
    finally:
        db.close()


def test_pin_preview_strips_markup_and_truncates():
    assert pin_preview("oi **clube**") == "oi clube"
    long = "a" * 200
    preview = pin_preview(long, limit=20)
    assert preview.endswith("…")
    assert len(preview) == 20


def test_club_pin_permissions_replace_and_clear():
    inspector = inspect(engine)
    club_cols = {column["name"] for column in inspector.get_columns("clubs")}
    assert "pinned_message_id" in club_cols

    owner = TestClient(app)
    member = TestClient(app)
    helper = TestClient(app)
    stranger = TestClient(app)
    register_active(owner, "pin_adm", "pin.adm@example.com")
    register_active(member, "pin_mem", "pin.mem@example.com")
    register_active(helper, "pin_sub", "pin.sub@example.com")
    register_active(stranger, "pin_out", "pin.out@example.com")
    club_id, code = _create_club(owner, "Clube Pin")
    other_id, _ = _create_club(owner, "Outro Pin")
    member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    helper.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    helper_id = _user_id("pin.sub@example.com")
    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": ROLE_SUPPORT, "support_perm": ["manage_tag"]},
        follow_redirects=False,
    )

    empty = owner.get(f"/clubs/{club_id}?aba=chat")
    assert empty.status_code == 200
    assert "chat-pin-bar" not in empty.text
    assert "Mensagem fixada" not in empty.text

    owner.post(f"/clubs/{club_id}/mensagens", data={"body": "primeiro aviso"}, follow_redirects=False)
    owner.post(f"/clubs/{club_id}/mensagens", data={"body": "segundo aviso"}, follow_redirects=False)
    first_id = _last_message_id(club_id, "primeiro aviso")
    second_id = _last_message_id(club_id, "segundo aviso")
    other_msg = owner.post(f"/clubs/{other_id}/mensagens", data={"body": "de outro clube"}, follow_redirects=False)
    assert other_msg.status_code == 303
    other_message_id = _last_message_id(other_id, "de outro clube")

    chat_before = owner.get(f"/clubs/{club_id}?aba=chat")
    assert "Fixar mensagem" in chat_before.text
    assert f'id="msg-{first_id}"' in chat_before.text
    member_chat = member.get(f"/clubs/{club_id}?aba=chat")
    assert "Fixar mensagem" not in member_chat.text
    assert "Desafixar" not in member_chat.text

    denied_member = member.post(
        f"/clubs/{club_id}/mensagens/{first_id}/fixar",
        follow_redirects=False,
    )
    assert denied_member.status_code == 303
    assert denied_member.headers["location"] == f"/clubs/{club_id}?aba=chat"
    denied_sub = helper.post(
        f"/clubs/{club_id}/mensagens/{first_id}/fixar",
        follow_redirects=False,
    )
    assert denied_sub.status_code == 303
    outsider = stranger.post(
        f"/clubs/{club_id}/mensagens/{first_id}/fixar",
        follow_redirects=False,
    )
    assert outsider.status_code == 303
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.pinned_message_id is None
        assert db.get(ClubMember, db.scalar(select(ClubMember.id).where(ClubMember.club_id == club_id, ClubMember.user_id == helper_id))).role == ROLE_SUPPORT
    finally:
        db.close()

    foreign = owner.post(
        f"/clubs/{club_id}/mensagens/{other_message_id}/fixar",
        follow_redirects=False,
    )
    assert foreign.status_code == 303
    assert "error=" in foreign.headers["location"]

    pinned = owner.post(
        f"/clubs/{club_id}/mensagens/{first_id}/fixar",
        follow_redirects=False,
    )
    assert pinned.status_code == 303
    assert pinned.headers["location"] == f"/clubs/{club_id}?aba=chat"
    shown = member.get(f"/clubs/{club_id}?aba=chat")
    assert "chat-pin-bar" in shown.text
    assert "Mensagem fixada" in shown.text
    assert "primeiro aviso" in shown.text
    assert f'href="#msg-{first_id}"' in shown.text
    assert "Fixar mensagem" not in shown.text
    db = SessionLocal()
    try:
        assert db.get(Club, club_id).pinned_message_id == first_id
    finally:
        db.close()

    replaced = owner.post(
        f"/clubs/{club_id}/mensagens/{second_id}/fixar",
        follow_redirects=False,
    )
    assert replaced.status_code == 303
    after = owner.get(f"/clubs/{club_id}?aba=chat")
    assert after.text.count("chat-pin-bar") == 1
    assert f'href="#msg-{second_id}"' in after.text
    assert "segundo aviso" in after.text.split("chat-pin-bar", 1)[1].split("chat-log", 1)[0]
    db = SessionLocal()
    try:
        assert db.get(Club, club_id).pinned_message_id == second_id
    finally:
        db.close()

    denied_unpin = member.post(
        f"/clubs/{club_id}/mensagem-fixa/desafixar",
        follow_redirects=False,
    )
    assert denied_unpin.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(Club, club_id).pinned_message_id == second_id
    finally:
        db.close()

    unpinned = owner.post(
        f"/clubs/{club_id}/mensagem-fixa/desafixar",
        follow_redirects=False,
    )
    assert unpinned.status_code == 303
    cleared = owner.get(f"/clubs/{club_id}?aba=chat")
    assert "chat-pin-bar" not in cleared.text
    assert "segundo aviso" in cleared.text
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.pinned_message_id is None
        leftover = db.scalar(select(ClubMessage).where(ClubMessage.id == second_id))
        assert leftover is not None
        assert leftover.body == "segundo aviso"
    finally:
        db.close()

    owner.post(f"/clubs/{club_id}/mensagens/{first_id}/fixar", follow_redirects=False)
    db = SessionLocal()
    try:
        db.delete(db.get(ClubMessage, first_id))
        db.commit()
    finally:
        db.close()
    stale = owner.get(f"/clubs/{club_id}?aba=chat")
    assert stale.status_code == 200
    assert "chat-pin-bar" not in stale.text
    db = SessionLocal()
    try:
        assert db.get(Club, club_id).pinned_message_id is None
    finally:
        db.close()
