from sqlalchemy import select
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.db import SessionLocal
from app.main import app
from app.models import Club, EmailToken, User

client = TestClient(app)


def register_active(http: TestClient, username: str, email: str, password: str = "segredo") -> None:
    created = http.post(
        "/register",
        data={"username": username, "email": email, "password": password},
        follow_redirects=False,
    )
    assert created.status_code == 303
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        token = db.scalar(select(EmailToken).where(EmailToken.user_id == user.id))
        assert token is not None
        raw = token.token
    finally:
        db.close()
    verified = http.get(f"/verificar-email?token={raw}", follow_redirects=False)
    assert verified.status_code == 303


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_search_api_uses_tvmaze():
    fake = [
        {
            "tvmaze_id": 169,
            "name": "Breaking Bad",
            "premiered": "2008-01-20",
            "status": "Ended",
            "image_url": "https://example.com/bb.jpg",
            "summary": "Um professor de química.",
        }
    ]
    with patch("app.main.tvmaze.search_shows", return_value=fake):
        response = client.get("/api/shows/search", params={"q": "breaking"})
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Breaking Bad"


def test_register_requires_email_before_login():
    pending = TestClient(app)
    pending.post(
        "/register",
        data={"username": "pendente", "email": "pendente@example.com", "password": "segredo"},
    )
    blocked = pending.post(
        "/login",
        data={"email": "pendente@example.com", "password": "segredo"},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert "/verificar-email" in blocked.headers["location"]


def test_register_and_create_club():
    email = "amigos@example.com"
    register_active(client, "marcela", email)
    response = client.post("/clubs", data={"name": "Noite de série"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/clubs/")


def test_username_must_be_unique_and_suggests_alternatives():
    register_active(client, "cinefila", "cinefila@example.com")
    other = TestClient(app)
    taken = other.post(
        "/register",
        data={"username": "cinefila", "email": "outra@example.com", "password": "segredo"},
    )
    assert taken.status_code == 400
    assert "já está em uso" in taken.text
    assert "cinefila2" in taken.text or "cinefila_tv" in taken.text


def test_update_profile_password_and_avatar():
    other = TestClient(app)
    register_active(other, "ana", "ana@example.com", "antiga")
    profile = other.post(
        "/conta/perfil",
        data={"username": "ana_clara", "email": "ana@example.com"},
        follow_redirects=False,
    )
    assert profile.status_code == 303
    account = other.get("/conta")
    assert "ana_clara" in account.text

    avatar = other.post("/conta/avatar", data={"avatar": "fox"}, follow_redirects=False)
    assert avatar.status_code == 303
    assert 'src="/static/avatars/fox.svg"' in other.get("/conta").text

    password = other.post(
        "/conta/senha",
        data={
            "current_password": "antiga",
            "new_password": "nova123",
            "confirm_password": "nova123",
        },
        follow_redirects=False,
    )
    assert password.status_code == 303
    other.post("/logout")
    login = other.post(
        "/login",
        data={"email": "ana@example.com", "password": "nova123"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/"


def test_join_and_leave_club():
    owner = TestClient(app)
    register_active(owner, "dono", "dono@example.com")
    created = owner.post("/clubs", data={"name": "Clube Extra"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        code = db.get(Club, club_id).join_code
    finally:
        db.close()

    guest = TestClient(app)
    register_active(guest, "convidada", "guest@example.com")
    joined = guest.post("/clubs/join", data={"join_code": code, "next": "/conta"}, follow_redirects=False)
    assert joined.status_code == 303
    assert "/conta" in joined.headers["location"]
    account = guest.get("/conta")
    assert "Clube Extra" in account.text

    left = guest.post(f"/clubs/{club_id}/leave", data={"next": "/conta"}, follow_redirects=False)
    assert left.status_code == 303
    after = guest.get("/conta")
    assert "Clube Extra" not in after.text
    still = owner.get(f"/clubs/{club_id}")
    assert still.status_code == 200
    assert "Clube Extra" in still.text
