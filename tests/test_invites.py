from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.accounts import login_or_create_oauth
from app.db import SessionLocal, engine
from app.invites import (
    CODE_BYTES,
    CODE_LENGTH,
    MSG_INVALID,
    MSG_REVOKED,
    MSG_USED,
    STATUS_AVAILABLE,
    STATUS_REVOKED,
    STATUS_USED,
    InviteSignupBlocked,
    create_invite,
    format_invite_code,
    generate_canonical_code,
    main as invites_main,
    normalize_invite_code,
    revoke_invite,
)
from app.main import app
from app.models import AccountInvite, Club, EmailToken, User
from app.security import make_join_code
from tests.test_app import register_active

client = TestClient(app)


def _closed(monkeypatch):
    monkeypatch.setattr("app.config.REGISTRATION_INVITE_REQUIRED", True)


def _issue_invite() -> str:
    db = SessionLocal()
    try:
        invite = create_invite(db)
        db.commit()
        return format_invite_code(invite.code)
    finally:
        db.close()


def test_account_invites_table_and_code_entropy():
    inspector = inspect(engine)
    assert "account_invites" in inspector.get_table_names()
    cols = {column["name"] for column in inspector.get_columns("account_invites")}
    assert {
        "id",
        "code",
        "status",
        "created_at",
        "used_at",
        "used_by_user_id",
        "revoked_at",
    } <= cols
    code = generate_canonical_code()
    assert len(code) == CODE_LENGTH
    assert CODE_BYTES * 8 >= 64
    assert format_invite_code(code).startswith("WC-")
    assert normalize_invite_code(format_invite_code(code).lower()) == code
    assert make_join_code() != format_invite_code(code)
    assert len(make_join_code()) == 8


def test_open_signup_does_not_require_invite():
    page = client.get("/register")
    assert page.status_code == 200
    assert "invite_required" in page.text
    pending = TestClient(app)
    created = pending.post(
        "/register",
        data={"name": "Aberto", "username": "aberto_inv", "email": "aberto.inv@example.com", "password": "segredo"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/verificar-email"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "aberto.inv@example.com"))
        assert user is not None
        assert user.is_active is False
        assert db.scalar(select(EmailToken).where(EmailToken.user_id == user.id)) is not None
    finally:
        db.close()


def test_closed_signup_requires_invite_and_messages(monkeypatch):
    _closed(monkeypatch)
    page = TestClient(app).get("/register")
    assert 'name="invite_code"' in page.text
    assert '"invite_required": true' in page.text

    blank = TestClient(app).post(
        "/register",
        data={"name": "Sem", "username": "sem_convite", "email": "sem.convite@example.com", "password": "segredo"},
        follow_redirects=False,
    )
    assert blank.status_code == 400
    assert MSG_INVALID in blank.text

    missing = TestClient(app).post(
        "/register",
        data={
            "name": "Sem",
            "username": "sem_convite2",
            "email": "sem.convite2@example.com",
            "password": "segredo",
            "invite_code": "WC-ZZZZ-ZZZZ-ZZZZ-Z",
        },
    )
    assert missing.status_code == 400
    assert MSG_INVALID in missing.text

    db = SessionLocal()
    try:
        invite = create_invite(db)
        db.commit()
        display = format_invite_code(invite.code)
        ok, _msg = revoke_invite(db, display)
        assert ok
        db.commit()
    finally:
        db.close()
    revoked = TestClient(app).post(
        "/register",
        data={
            "name": "Rev",
            "username": "rev_convite",
            "email": "rev.convite@example.com",
            "password": "segredo",
            "invite_code": display,
        },
    )
    assert revoked.status_code == 400
    assert MSG_REVOKED in revoked.text


def test_valid_invite_creates_inactive_user_and_cannot_be_reused(monkeypatch):
    _closed(monkeypatch)
    code = _issue_invite()
    http = TestClient(app)
    created = http.post(
        "/register",
        data={
            "name": "Convite Ok",
            "username": "convite_ok",
            "email": "convite.ok@example.com",
            "password": "segredo",
            "invite_code": code.lower().replace("-", " "),
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/verificar-email"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "convite.ok@example.com"))
        assert user is not None
        assert user.is_active is False
        token = db.scalar(select(EmailToken).where(EmailToken.user_id == user.id))
        assert token is not None
        invite = db.scalar(select(AccountInvite).where(AccountInvite.used_by_user_id == user.id))
        assert invite is not None
        assert invite.status == STATUS_USED
    finally:
        db.close()
    blocked = http.post(
        "/login",
        data={"email": "convite.ok@example.com", "password": "segredo"},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert "/verificar-email" in blocked.headers["location"]
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "convite.ok@example.com"))
        token = db.scalar(select(EmailToken).where(EmailToken.user_id == user.id))
        raw = token.token
    finally:
        db.close()
    verified = http.get(f"/verificar-email?token={raw}", follow_redirects=False)
    assert verified.status_code == 303
    second = TestClient(app).post(
        "/register",
        data={
            "name": "Outro",
            "username": "convite_dois",
            "email": "convite.dois@example.com",
            "password": "segredo",
            "invite_code": code,
        },
    )
    assert second.status_code == 400
    assert MSG_USED in second.text


def test_failed_register_does_not_consume_invite(monkeypatch):
    register_active(client, "taken_inv", "taken.inv@example.com")
    _closed(monkeypatch)
    code = _issue_invite()
    failed = TestClient(app).post(
        "/register",
        data={
            "name": "Cópia",
            "username": "taken_inv",
            "email": "outro.taken@example.com",
            "password": "segredo",
            "invite_code": code,
        },
    )
    assert failed.status_code == 400
    assert "já está em uso" in failed.text
    assert code in failed.text
    db = SessionLocal()
    try:
        invite = db.scalar(select(AccountInvite).where(AccountInvite.code == normalize_invite_code(code)))
        assert invite.status == STATUS_AVAILABLE
        assert invite.used_by_user_id is None
    finally:
        db.close()


def test_oauth_existing_user_still_works_when_closed(monkeypatch):
    register_active(client, "oauth_keep", "oauth.keep@example.com")
    _closed(monkeypatch)
    db = SessionLocal()
    try:
        user = login_or_create_oauth(
            db,
            {
                "provider": "google",
                "provider_id": "google-keep-1",
                "email": "oauth.keep@example.com",
                "name": "Keep",
            },
        )
        db.commit()
        assert user.username == "oauth_keep"
    finally:
        db.close()


def test_oauth_new_user_blocked_when_closed(monkeypatch):
    _closed(monkeypatch)
    db = SessionLocal()
    try:
        try:
            login_or_create_oauth(
                db,
                {
                    "provider": "google",
                    "provider_id": "google-new-blocked",
                    "email": "oauth.new.blocked@example.com",
                    "name": "Nova Pessoa",
                },
            )
            raise AssertionError("expected InviteSignupBlocked")
        except InviteSignupBlocked:
            db.rollback()
        assert db.scalar(select(User).where(User.email == "oauth.new.blocked@example.com")) is None
    finally:
        db.close()


def test_login_keeps_oauth_buttons_when_closed(monkeypatch):
    _closed(monkeypatch)
    page = TestClient(app).get("/login")
    assert "Continuar com Gmail" in page.text
    assert "Continuar com Facebook" in page.text


def test_invite_race_allows_only_one_account(monkeypatch):
    _closed(monkeypatch)
    code = _issue_invite()

    def try_register(index: int):
        http = TestClient(app)
        return http.post(
            "/register",
            data={
                "name": f"Race {index}",
                "username": f"race_inv_{index}",
                "email": f"race.inv{index}@example.com",
                "password": "segredo",
                "invite_code": code,
            },
            follow_redirects=False,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_register, [1, 2]))
    statuses = sorted(item.status_code for item in results)
    assert statuses == [303, 400]
    assert any(MSG_USED in item.text or MSG_INVALID in item.text for item in results if item.status_code == 400)
    db = SessionLocal()
    try:
        users = list(
            db.scalars(select(User).where(User.email.in_(["race.inv1@example.com", "race.inv2@example.com"])))
        )
        assert len(users) == 1
        invite = db.scalar(select(AccountInvite).where(AccountInvite.code == normalize_invite_code(code)))
        assert invite.status == STATUS_USED
        assert invite.used_by_user_id == users[0].id
    finally:
        db.close()


def test_invites_cli_generate_list_revoke(capsys):
    assert invites_main(["generate"]) == 0
    display = capsys.readouterr().out.strip()
    assert display.startswith("WC-")
    assert invites_main(["list"]) == 0
    listed = capsys.readouterr().out
    assert display in listed
    assert STATUS_AVAILABLE in listed
    assert invites_main(["revoke", display]) == 0
    assert "revogado" in capsys.readouterr().out.lower()
    db = SessionLocal()
    try:
        invite = db.scalar(select(AccountInvite).where(AccountInvite.code == normalize_invite_code(display)))
        assert invite.status == STATUS_REVOKED
    finally:
        db.close()
    assert invites_main(["revoke", display]) == 1
    assert "já está revogado" in capsys.readouterr().out
    assert invites_main(["revoke", "WC-NOPE-NOPE-NOPE-N"]) == 1
    assert "inexistente" in capsys.readouterr().out


def test_club_join_code_unchanged_with_invites():
    owner = TestClient(app)
    register_active(owner, "join_keep", "join.keep@example.com")
    created = owner.post("/clubs", data={"name": "Clube Join"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.join_code
        assert len(club.join_code) == 8
        assert club.join_code == club.join_code.upper()
    finally:
        db.close()
