from fastapi.testclient import TestClient
from sqlalchemy import select

from app.accounts import utcnow
from app.db import SessionLocal
from app.main import app
from app.models import Club, User
from tests.test_app import register_active
from tests.test_dm import _befriend


def _join_code(club_id: int) -> str:
    db = SessionLocal()
    try:
        return db.get(Club, club_id).join_code
    finally:
        db.close()


def test_friends_search_name_username_relations_and_privacy():
    a = TestClient(app)
    b = TestClient(app)
    c = TestClient(app)
    d = TestClient(app)
    register_active(a, "seek_a", "seek.a@example.com", name="Ana Busca")
    register_active(b, "seek_b", "seek.b@example.com", name="Bia Outroclube")
    register_active(c, "seek_c", "seek.c@example.com", name="Caio Pendente")
    register_active(d, "seek_d", "seek.d@example.com", name="Duda Incoming")

    club_a = a.post("/clubs", data={"name": "Clube A Busca"}, follow_redirects=False)
    club_b = b.post("/clubs", data={"name": "Clube B Secreto"}, follow_redirects=False)
    a_id = int(club_a.headers["location"].rsplit("/", 1)[-1])
    b_id = int(club_b.headers["location"].rsplit("/", 1)[-1])
    assert _join_code(a_id) != _join_code(b_id)

    by_name = a.get("/amigos?q=Bia", follow_redirects=False)
    assert by_name.status_code == 200
    assert "Encontrar pessoas" in by_name.text
    assert "Bia Outroclube" in by_name.text
    assert "@seek_b" in by_name.text
    assert "Adicionar" in by_name.text
    assert "Ver perfil" in by_name.text
    assert "seek.b@example.com" not in by_name.text
    assert "Clube B Secreto" not in by_name.text

    by_user = a.get("/amigos?q=@seek_b", follow_redirects=False)
    assert "Bia Outroclube" in by_user.text
    partial = a.get("/amigos?q=seek_", follow_redirects=False)
    assert "@seek_b" in partial.text
    self_hit = a.get("/amigos?q=@seek_a", follow_redirects=False)
    assert '<span class="muted">Você</span>' in self_hit.text

    invited = a.post("/amigos/seek_c/convidar", data={"next": "/amigos"}, follow_redirects=False)
    assert invited.status_code == 303
    outgoing = a.get("/amigos?q=Caio", follow_redirects=False)
    assert "Solicitação enviada" in outgoing.text
    assert "Adicionar" not in outgoing.text.split("Caio Pendente", 1)[1][:800]

    d.post("/amigos/seek_a/convidar", data={"next": "/amigos"}, follow_redirects=False)
    incoming = a.get("/amigos?q=Duda", follow_redirects=False)
    assert "Aceitar" in incoming.text

    _befriend(a, b, "seek_a", "seek_b")
    friends = a.get("/amigos?q=Bia", follow_redirects=False)
    assert '<span class="muted">Amigos</span>' in friends.text
    assert ">Adicionar<" not in friends.text.split("Bia Outroclube", 1)[1][:800]

    a.post("/u/seek_c/bloquear", data={"next": "/u/seek_c"}, follow_redirects=False)
    blocked = a.get("/amigos?q=@seek_c", follow_redirects=False)
    assert blocked.status_code == 200
    blocked_section = blocked.text.split("Encontrar pessoas", 1)[1].split("Solicitações de amizade", 1)[0]
    assert "Caio Pendente" not in blocked_section
    reverse = c.get("/amigos?q=@seek_a", follow_redirects=False)
    assert reverse.status_code == 200
    reverse_section = reverse.text.split("Encontrar pessoas", 1)[1].split("Solicitações de amizade", 1)[0]
    assert "Ninguém encontrado." in reverse_section
    assert "Ana Busca" not in reverse_section.split("<ul class=\"people\">", 1)[-1]

    too_short = a.get("/amigos?q=a", follow_redirects=False)
    assert "pelo menos 2 caracteres" in too_short.text


def test_friends_search_hides_banned_and_does_not_query_external():
    target = TestClient(app)
    seeker = TestClient(app)
    register_active(target, "seek_ban", "seek.ban@example.com", name="Banido Busca")
    register_active(seeker, "seek_ok", "seek.ok@example.com")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "seek.ban@example.com"))
        user.banned_at = utcnow()
        db.commit()
    finally:
        db.close()
    page = seeker.get("/amigos?q=Banido", follow_redirects=False)
    assert "Banido Busca" not in page.text
    assert "seek.ban@example.com" not in page.text
