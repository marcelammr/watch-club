from sqlalchemy import select
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.db import SessionLocal
from app.main import app
from app.models import Club, ClubMember, ClubShow, EmailToken, User

client = TestClient(app)


def register_active(
    http: TestClient,
    username: str,
    email: str,
    password: str = "segredo",
    name: str | None = None,
) -> None:
    created = http.post(
        "/register",
        data={
            "name": name or username.replace("_", " ").title(),
            "username": username,
            "email": email,
            "password": password,
        },
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
        data={"name": "Pendente", "username": "pendente", "email": "pendente@example.com", "password": "segredo"},
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


def test_username_api_suggests_when_taken():
    register_active(client, "cinefila_api", "cinefila.api@example.com")
    stranger = TestClient(app)
    response = stranger.get("/api/username", params={"q": "cinefila_api"})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["suggestions"]
    assert "cinefila_api" not in body["suggestions"]
    free = stranger.get("/api/username", params={"q": "nome_livre_xyz"})
    assert free.json()["available"] is True


def test_username_must_be_unique_and_suggests_alternatives():
    register_active(client, "cinefila", "cinefila@example.com")
    other = TestClient(app)
    taken = other.post(
        "/register",
        data={"name": "Outra", "username": "cinefila", "email": "outra@example.com", "password": "segredo"},
    )
    assert taken.status_code == 400
    assert "já está em uso" in taken.text
    assert "cinefila2" in taken.text or "cinefila_tv" in taken.text


def test_update_profile_password_and_avatar():
    other = TestClient(app)
    register_active(other, "ana", "ana@example.com", "antiga")
    profile = other.post(
        "/conta/perfil",
        data={"name": "Ana Clara", "username": "ana", "email": "ana@example.com"},
        follow_redirects=False,
    )
    assert profile.status_code == 303
    account = other.get("/conta")
    assert "Ana Clara" in account.text
    home = other.get("/")
    assert "Olá, Ana Clara" in home.text
    assert "@ana" not in home.text
    public = other.get("/u/ana")
    assert "Ana Clara" in public.text
    assert "@ana" in public.text

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


def test_oauth_buttons_and_unconfigured_provider():
    page = client.get("/login")
    assert "Continuar com Gmail" in page.text
    assert "Continuar com Facebook" in page.text
    google = client.get("/auth/google", follow_redirects=False)
    assert google.status_code == 303
    assert "/login" in google.headers["location"]


def test_bio_and_avatar_editor_hidden():
    person = TestClient(app)
    register_active(person, "bio_user", "bio.user@example.com")
    saved = person.post(
        "/conta/perfil",
        data={"name": "Bio User", "username": "bio_user", "email": "bio.user@example.com", "bio": "Cinéfila de maratona."},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    settings = person.get("/conta")
    assert 'id="open-avatar"' in settings.text
    assert "avatar-modal" in settings.text
    assert "🍿" in settings.text
    assert "Cinéfila de maratona." in settings.text
    public = person.get("/u/bio_user")
    assert public.status_code == 200
    assert "Cinéfila de maratona." in public.text
    assert "Bio User" in public.text
    assert "@bio_user" in public.text


def test_closed_club_is_locked_open_club_can_be_joined():
    owner = TestClient(app)
    register_active(owner, "host", "host@example.com")
    closed = owner.post("/clubs", data={"name": "Sala VIP", "is_closed": "1"}, follow_redirects=False)
    closed_id = int(closed.headers["location"].rsplit("/", 1)[-1])
    opened = owner.post("/clubs", data={"name": "Sala Aberta"}, follow_redirects=False)
    open_id = int(opened.headers["location"].rsplit("/", 1)[-1])

    guest = TestClient(app)
    register_active(guest, "visitante", "visitante@example.com")
    locked = guest.get(f"/clubs/{closed_id}")
    assert locked.status_code == 403
    assert "fechado" in locked.text.lower() or "🔒" in locked.text

    preview = guest.get(f"/clubs/{open_id}")
    assert preview.status_code == 200
    assert "Participar" in preview.text
    joined = guest.post(f"/clubs/{open_id}/entrar", follow_redirects=False)
    assert joined.status_code == 303

    profile = guest.get("/u/host")
    assert "Sala VIP" in profile.text
    assert "🔒" in profile.text
    assert "Sala Aberta" in profile.text


def test_member_count_list_and_presence():
    owner = TestClient(app)
    register_active(owner, "contador", "contador@example.com")
    created = owner.post("/clubs", data={"name": "Contagem"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    page = owner.get(f"/clubs/{club_id}")
    assert "1 participante" in page.text
    people = owner.get(f"/clubs/{club_id}/membros")
    assert people.status_code == 200
    assert "Contador" in people.text
    assert "@contador" not in people.text
    ping = owner.post("/presenca", data={"status": "away"})
    assert ping.status_code == 200
    assert ping.json()["ok"] is True


def test_nickname_cooldown_and_unique():
    from datetime import timedelta

    from app.accounts import utcnow

    person = TestClient(app)
    register_active(person, "nicklock", "nick.lock@example.com", name="Nome Livre")
    blocked = person.post(
        "/conta/perfil",
        data={"name": "Nome Livre", "username": "outro_nick", "email": "nick.lock@example.com"},
    )
    assert blocked.status_code == 400
    assert "14 dias" in blocked.text

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "nick.lock@example.com"))
        user.username_changed_at = utcnow() - timedelta(days=15)
        db.commit()
    finally:
        db.close()
    allowed = person.post(
        "/conta/perfil",
        data={"name": "Nome Livre", "username": "outro_nick", "email": "nick.lock@example.com"},
        follow_redirects=False,
    )
    assert allowed.status_code == 303
    assert "outro_nick" in person.get("/u/outro_nick").text
    assert "Nome Livre" in person.get("/u/outro_nick").text


def test_home_is_a_simple_club_hub():
    person = TestClient(app)
    register_active(person, "hub_user", "hub.user@example.com", name="Marcela")
    home = person.get("/")
    assert "Olá, Marcela!" in home.text
    assert "Meus Clubes" in home.text
    assert "Criar um clube" in home.text
    assert "Entrar com código" in home.text
    assert "Adicionar série" not in home.text
    form = person.get("/clubs/novo")
    assert form.status_code == 200
    assert "Informações e regras" in form.text


def test_club_creator_is_admin_and_member_cannot_change_settings():
    owner = TestClient(app)
    register_active(owner, "admin_club", "admin.club@example.com")
    created = owner.post(
        "/clubs",
        data={
            "name": "Capa Nova",
            "description": "Sobre o grupo",
            "rules": "Sem spoiler",
            "cover_color": "#246b45",
        },
        follow_redirects=False,
    )
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        member = db.scalar(select(ClubMember).where(ClubMember.club_id == club_id))
        assert club.cover_color == "#246b45"
        assert club.description == "Sobre o grupo"
        assert member.is_admin is True
        code = club.join_code
    finally:
        db.close()

    page = owner.get(f"/clubs/{club_id}")
    assert "Configurações" in page.text
    assert "Sobre o grupo" in page.text
    settings_page = owner.get(f"/clubs/{club_id}/config")
    assert "Sem spoiler" in settings_page.text

    guest = TestClient(app)
    register_active(guest, "membro_comum", "membro.comum@example.com")
    guest.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    member_page = guest.get(f"/clubs/{club_id}")
    assert "Configurações" not in member_page.text
    blocked = guest.post(
        f"/clubs/{club_id}/config",
        data={"name": "Hackeado", "description": "", "rules": "", "cover_color": "#7a3048"},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert blocked.headers["location"] == f"/clubs/{club_id}"
    after = owner.get(f"/clubs/{club_id}")
    assert "Capa Nova" in after.text
    assert "Hackeado" not in after.text

    settings = guest.get(f"/clubs/{club_id}/config", follow_redirects=False)
    assert settings.status_code == 303
    admin_try = guest.post(
        f"/clubs/{club_id}/membros/1/admin",
        data={"action": "grant"},
        follow_redirects=False,
    )
    assert admin_try.status_code == 303
    assert admin_try.headers["location"] == f"/clubs/{club_id}"


def test_club_chat_and_watching_are_members_only():
    owner = TestClient(app)
    register_active(owner, "chat_host", "chat.host@example.com")
    created = owner.post("/clubs", data={"name": "Sala Chat", "is_closed": "1"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    default_tab = owner.get(f"/clubs/{club_id}")
    assert "Assistindo agora" in default_tab.text
    assert "Escreva para o clube" not in default_tab.text

    sent = owner.post(f"/clubs/{club_id}/mensagens", data={"body": "Vamos maratonar?"}, follow_redirects=False)
    assert sent.status_code == 303
    chat = owner.get(f"/clubs/{club_id}?aba=chat")
    assert "Vamos maratonar?" in chat.text
    assert "Chat Host" in chat.text or "chat_host" in chat.text.lower() or "chat host" in chat.text.lower()

    added = owner.post(
        f"/clubs/{club_id}/titulos",
        data={"name": "Filme da Casa", "kind": "filme", "image_url": "https://example.com/p.jpg"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    watching = owner.get(f"/clubs/{club_id}")
    assert "Filme da Casa" in watching.text
    assert "Filme" in watching.text
    assert "Assistindo agora" in watching.text
    assert "Ver detalhes" in watching.text

    db = SessionLocal()
    try:
        link = db.scalar(select(ClubShow).where(ClubShow.club_id == club_id))
        show_id = link.show_id
    finally:
        db.close()
    marked = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/status",
        data={"watch_status": "watched"},
        follow_redirects=False,
    )
    assert marked.status_code == 303
    watched = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "Já assistimos" in watched.text
    assert "Filme da Casa" in watched.text

    stranger = TestClient(app)
    register_active(stranger, "fora", "fora.chat@example.com")
    locked = stranger.get(f"/clubs/{club_id}")
    assert locked.status_code == 403
    blocked_msg = stranger.post(f"/clubs/{club_id}/mensagens", data={"body": "oi"}, follow_redirects=False)
    assert blocked_msg.status_code == 303
    assert f"/clubs/{club_id}" in blocked_msg.headers["location"]
    blocked_title = stranger.post(
        f"/clubs/{club_id}/titulos",
        data={"name": "Intruso", "kind": "serie"},
        follow_redirects=False,
    )
    assert blocked_title.status_code == 303


def test_club_ratings_genres_and_admin_remove():
    from unittest.mock import AsyncMock, patch

    from app.models import ClubShowRating, Show

    owner = TestClient(app)
    register_active(owner, "nota_admin", "nota.admin@example.com")
    created = owner.post("/clubs", data={"name": "Sala Notas"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    fake = (
        {
            "tvmaze_id": 169,
            "name": "Breaking Bad",
            "summary": "Um professor de química.",
            "status": "Ended",
            "premiered": "2008-01-20",
            "image_url": "https://example.com/bb.jpg",
            "official_site": None,
            "kind": "serie",
            "genres": ["Drama", "Crime"],
        },
        [],
    )
    with patch("app.catalog.tvmaze.fetch_show_and_seasons", AsyncMock(return_value=fake)):
        with patch("app.catalog.refresh_news"):
            added = owner.post(f"/clubs/{club_id}/shows", data={"tvmaze_id": "169"}, follow_redirects=False)
    assert added.status_code == 303

    page = owner.get(f"/clubs/{club_id}")
    assert "Breaking Bad" in page.text
    assert "Drama" in page.text
    assert "Crime" in page.text
    assert "Ainda sem avaliações" in page.text
    assert "Remover do clube" in page.text

    db = SessionLocal()
    try:
        show = db.scalar(select(Show).where(Show.tvmaze_id == 169))
        show_id = show.id
        assert show.genres and "Drama" in show.genres
    finally:
        db.close()

    rated = owner.post(f"/clubs/{club_id}/shows/{show_id}/avaliar", data={"stars": "5"}, follow_redirects=False)
    assert rated.status_code == 303
    after = owner.get(f"/clubs/{club_id}")
    assert "5,0" in after.text
    assert "1 avaliação" in after.text
    assert "Ainda sem avaliações" not in after.text

    guest = TestClient(app)
    register_active(guest, "nota_membro", "nota.membro@example.com")
    db = SessionLocal()
    try:
        code = db.get(Club, club_id).join_code
    finally:
        db.close()
    guest.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    guest_page = guest.get(f"/clubs/{club_id}")
    assert "Remover do clube" not in guest_page.text
    guest.post(f"/clubs/{club_id}/shows/{show_id}/avaliar", data={"stars": "3"}, follow_redirects=False)
    averaged = owner.get(f"/clubs/{club_id}")
    assert "4,0" in averaged.text
    assert "2 avaliações" in averaged.text

    blocked = guest.post(f"/clubs/{club_id}/shows/{show_id}/remover", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == f"/clubs/{club_id}"
    still = owner.get(f"/clubs/{club_id}")
    assert "Breaking Bad" in still.text

    removed = owner.post(f"/clubs/{club_id}/shows/{show_id}/remover", follow_redirects=False)
    assert removed.status_code == 303
    gone = owner.get(f"/clubs/{club_id}")
    assert "Breaking Bad" not in gone.text
    db = SessionLocal()
    try:
        assert db.get(Show, show_id) is not None
        leftover = db.scalar(
            select(ClubShowRating).where(ClubShowRating.club_id == club_id, ClubShowRating.show_id == show_id)
        )
        assert leftover is None
        assert db.scalar(select(ClubShow).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id)) is None
    finally:
        db.close()

