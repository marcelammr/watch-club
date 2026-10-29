from sqlalchemy import func, select
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.club_icons import stored_icon_path
from app.db import SessionLocal
from app.main import app
from app.models import Club, ClubJoinRequest, ClubMember, ClubShow, EmailToken, User
from app.roles import PERM_TAG, ROLE_SUPPORT

client = TestClient(app)


def star_button_values(html: str) -> list[str]:
    chunk = html.split('class="star-picker"', 1)[1].split("</div>", 1)[0]
    values = []
    token = 'aria-label="Avaliar com '
    start = 0
    while True:
        index = chunk.find(token, start)
        if index < 0:
            break
        values.append(chunk[index + len(token)])
        start = index + len(token)
    return values


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


def test_logged_in_shell_and_clubes_page():
    member = TestClient(app)
    register_active(member, "nav_user", "nav.user@example.com")
    created = member.post("/clubs", data={"name": "Clube Nav"}, follow_redirects=False)
    assert created.status_code == 303
    home = member.get("/")
    assert home.status_code == 200
    assert "app-sidebar" in home.text
    assert "Watch Club" in home.text
    assert ">WC<" not in home.text
    assert 'aria-label="Início"' in home.text
    assert 'aria-label="Meus Clubes"' in home.text
    assert 'aria-label="Amigos"' in home.text
    assert 'aria-label="Configurações"' in home.text
    assert 'aria-label="Sobre"' in home.text
    assert 'href="/conta"' in home.text
    assert 'href="/sobre"' in home.text
    assert 'aria-label="Notificações"' in home.text
    assert 'href="/amigos"' in home.text
    assert 'id="open-clubs"' in home.text
    assert 'id="account-popover"' in home.text
    assert "Editar perfil" in home.text
    assert 'action="/logout"' in home.text
    assert "Sair da sessão" in home.text.split('id="account-popover"', 1)[-1]
    clubs = member.get("/clubes")
    assert clubs.status_code == 200
    assert "Clube Nav" in clubs.text
    assert "Meus Clubes" in clubs.text
    account = member.get("/conta")
    assert "Sair da sessão" in account.text
    guest_home = client.get("/")
    assert "app-sidebar" not in guest_home.text


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_command_api_guest_and_member():
    guest = client.get("/api/command")
    assert guest.status_code == 200
    labels = [item["label"] for group in guest.json()["groups"] for item in group["items"]]
    assert "Entrar" in labels
    assert "Criar conta" in labels

    member = TestClient(app)
    register_active(member, "cmdk_user", "cmdk@example.com")
    created = member.post("/clubs", data={"name": "Clube Command"}, follow_redirects=False)
    assert created.status_code == 303
    menu = member.get("/api/command")
    body = menu.json()
    headings = [group["heading"] for group in body["groups"]]
    assert "Navegação" in headings
    assert "Clubes" in headings
    club_names = [item["label"] for group in body["groups"] if group["heading"] == "Clubes" for item in group["items"]]
    assert "Clube Command" in club_names


def test_search_api_uses_tvmaze():
    from unittest.mock import AsyncMock

    member = TestClient(app)
    register_active(member, "busca_tvmaze", "busca.tvmaze@example.com")
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
    with patch("app.search.tvmaze.search_shows", AsyncMock(return_value=fake)):
        guest = client.get("/api/shows/search", params={"q": "breaking"})
        response = member.get("/api/shows/search", params={"q": "breaking"})
    assert guest.status_code == 401
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


def test_email_must_be_unique_even_with_different_case():
    register_active(client, "email_dona", "unica@example.com")
    other = TestClient(app)
    taken = other.post(
        "/register",
        data={
            "name": "Outra Pessoa",
            "username": "email_outra",
            "email": "Unica@Example.com",
            "password": "segredo",
        },
    )
    assert taken.status_code == 400
    assert "e-mail já está cadastrado" in taken.text.lower()


def test_oauth_reuses_existing_email_instead_of_creating():
    from app.accounts import login_or_create_oauth
    from app.db import SessionLocal

    register_active(client, "oauth_mail", "oauth.unica@example.com")
    db = SessionLocal()
    try:
        first = login_or_create_oauth(
            db,
            {
                "provider": "google",
                "provider_id": "google-oauth-1",
                "email": "OAuth.Unica@example.com",
                "name": "Outra Marcela",
            },
        )
        db.commit()
        user_id = first.id
        username = first.username
        second = login_or_create_oauth(
            db,
            {
                "provider": "google",
                "provider_id": "google-oauth-1",
                "email": "oauth.unica@example.com",
                "name": "Marcela Nova",
            },
        )
        db.commit()
        assert second.id == user_id
        assert username == "oauth_mail"
        count = len(db.scalars(select(User).where(User.email == "oauth.unica@example.com")).all())
        assert count == 1
    finally:
        db.close()


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
    assert "@ana" in home.text
    assert "Editar perfil" in home.text
    public = other.get("/u/ana")
    assert "Ana Clara" in public.text
    assert "@ana" in public.text

    avatar = other.post("/conta/avatar", data={"avatar": "fox"}, follow_redirects=False)
    assert avatar.status_code == 303
    account_html = other.get("/conta").text
    assert 'src="/static/avatars/fox.svg"' in account_html
    assert 'data-slot="avatar-badge"' in account_html
    assert 'data-user-avatar' in other.get("/").text

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


def test_password_reset_sends_code_and_updates_password():
    member = TestClient(app)
    register_active(member, "reset_user", "reset@example.com", "antiga")
    member.post("/logout")

    login_page = client.get("/login")
    assert "Esqueceu a senha?" in login_page.text
    assert "/recuperar-senha" in login_page.text

    asked = member.post("/recuperar-senha", data={"email": "reset@example.com"}, follow_redirects=False)
    assert asked.status_code == 303
    assert asked.headers["location"] == "/recuperar-senha/codigo"

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "reset@example.com"))
        token = db.scalar(select(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == "reset"))
        assert token is not None
        code = token.token
    finally:
        db.close()

    unknown = TestClient(app)
    ghost = unknown.post("/recuperar-senha", data={"email": "naoexiste@example.com"}, follow_redirects=False)
    assert ghost.status_code == 303

    bad = member.post(
        "/recuperar-senha/codigo",
        data={"code": "000000", "new_password": "nova123", "confirm_password": "nova123"},
        follow_redirects=False,
    )
    assert bad.status_code == 400

    changed = member.post(
        "/recuperar-senha/codigo",
        data={"code": code, "new_password": "nova123", "confirm_password": "nova123"},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert changed.headers["location"].startswith("/")

    member.post("/logout")
    old = member.post("/login", data={"email": "reset@example.com", "password": "antiga"}, follow_redirects=False)
    assert old.status_code == 400
    fresh = TestClient(app)
    ok_login = fresh.post("/login", data={"email": "reset@example.com", "password": "nova123"}, follow_redirects=False)
    assert ok_login.status_code == 303
    assert ok_login.headers["location"] == "/"


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
    assert 'aria-label="Adicionar emoji"' in settings.text
    assert "js-emoji-picker" in settings.text
    assert "js-emoji-panel" in settings.text
    assert 'id="photo-crop-dialog"' in settings.text
    assert "Usar esta foto" in settings.text
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
    assert "Pedir para entrar" in locked.text
    assert "código de convite" not in locked.text.lower()
    assert "aprovadas pela administração" in locked.text.lower()

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
    assert 'class="home-btn"' in page.text
    assert 'href="/"' in page.text
    assert "js-club-nav-toggle" in page.text
    assert 'aria-controls="club-nav"' in page.text
    assert 'aria-controls="app-sidebar"' not in page.text
    assert 'aria-label="Voltar"' not in page.text
    assert 'class="crumb"' not in page.text
    assert "1 membro" in page.text
    assert page.text.find("1 membro") < page.text.find("Bate-papo")
    assert "club-people" not in page.text
    assert 'id="members-dialog"' in page.text
    assert "js-copy-code" in page.text
    assert "Código copiado!" in page.text
    assert 'id="leave-dialog"' in page.text
    copy_idx = page.text.find("js-copy-code")
    leave_idx = page.text.find("js-leave-open")
    name_idx = page.text.find("<h1>")
    assert name_idx != -1 and copy_idx != -1 and leave_idx != -1
    assert name_idx < copy_idx < leave_idx
    people = owner.get(f"/clubs/{club_id}/membros")
    assert people.status_code == 200
    assert "Contador" in people.text
    ping = owner.post("/presenca", data={"status": "away"})
    assert ping.status_code == 200
    assert ping.json()["ok"] is True
    away_page = owner.get(f"/clubs/{club_id}/membros")
    assert 'class="presence-moon"' in away_page.text
    assert 'aria-label="Ausente"' in away_page.text


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
    assert 'id="cover-crop-dialog"' in form.text
    assert 'id="icon-crop-dialog"' in form.text
    assert "/static/js/cover-crop.js" in form.text
    assert "/static/js/icon-crop.js" in form.text
    assert 'class="js-cover-file"' in form.text
    assert 'class="js-icon-file"' in form.text
    assert "Ícone do clube" in form.text
    assert "Capa do clube" in form.text
    assert 'id="icon-remove-dialog"' not in form.text
    assert "js-icon-remove-open" not in form.text


TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def test_club_cover_image_upload_and_type_limit():
    owner = TestClient(app)
    register_active(owner, "cover_img", "cover.img@example.com")
    created = owner.post(
        "/clubs",
        data={"name": "Capa Foto", "description": "", "rules": "", "cover_color": "#3A2348"},
        files={"cover_file": ("cover.png", TINY_PNG, "image/png")},
        follow_redirects=False,
    )
    assert created.status_code == 303
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.cover_image
        assert club.cover_image.endswith(".png")
        image_name = club.cover_image
    finally:
        db.close()
    room = owner.get(f"/clubs/{club_id}")
    assert f"/static/uploads/clubs/{image_name}" in room.text
    settings = owner.get(f"/clubs/{club_id}/config")
    assert 'id="cover-crop-dialog"' in settings.text
    assert "/static/js/cover-crop.js" in settings.text
    assert 'id="photo-crop-dialog"' not in settings.text

    rejected = owner.post(
        "/clubs",
        data={"name": "Capa Ruim", "description": "", "rules": "", "cover_color": "#3A2348"},
        files={"cover_file": ("notes.txt", b"hello", "text/plain")},
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    bad_id = int(rejected.headers["location"].rsplit("/", 1)[-1])
    oversized = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Capa Foto",
            "description": "",
            "rules": "",
            "cover_color": "#3A2348",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "settings_section": "aparencia",
        },
        files={"cover_file": ("cover.png", b"x" * (2 * 1024 * 1024 + 8), "image/png")},
        follow_redirects=False,
    )
    assert oversized.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(Club, bad_id).cover_image is None
        assert db.get(Club, club_id).cover_image == image_name
    finally:
        db.close()


TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def test_club_icon_image_optional_upload_and_independence():
    from app.club_icons import club_icon_initials

    assert club_icon_initials("") == "?"
    assert club_icon_initials("Watch") == "WA"
    assert club_icon_initials("Watch Club") == "WC"

    owner = TestClient(app)
    register_active(owner, "icon_img", "icon.img@example.com")
    created = owner.post(
        "/clubs",
        data={"name": "Icone Vazio", "description": "", "rules": "", "cover_color": "#3A2348"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    empty_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        empty = db.get(Club, empty_id)
        assert empty.icon_image is None
        assert empty.cover_image is None
    finally:
        db.close()

    both = owner.post(
        "/clubs",
        data={"name": "Icone Foto", "description": "", "rules": "", "cover_color": "#246B45"},
        files={
            "icon_file": ("icon.png", TINY_PNG, "image/png"),
            "cover_file": ("cover.png", TINY_PNG, "image/png"),
        },
        follow_redirects=False,
    )
    assert both.status_code == 303
    club_id = int(both.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.icon_image and club.icon_image.endswith(".png")
        assert club.cover_image and club.cover_image.endswith(".png")
        assert club.icon_image != club.cover_image
        icon_name = club.icon_image
        cover_name = club.cover_image
        code = club.join_code
    finally:
        db.close()
    room = owner.get(f"/clubs/{club_id}")
    assert f"/static/uploads/clubs/{cover_name}" in room.text
    assert f"/static/uploads/club-icons/{icon_name}" in room.text
    assert "club-mark" in room.text
    empty_room = owner.get(f"/clubs/{empty_id}")
    assert "club-icon-fallback" in empty_room.text
    assert "IV" in empty_room.text
    settings = owner.get(f"/clubs/{club_id}/config")
    assert f"/static/uploads/club-icons/{icon_name}" in settings.text
    assert 'name="icon_file"' in settings.text
    assert 'name="clear_icon"' not in settings.text
    assert "js-icon-remove-open" in settings.text
    assert 'id="icon-remove-dialog"' in settings.text
    assert "btn-danger js-icon-remove-confirm" in settings.text

    swapped = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Icone Foto",
            "description": "",
            "rules": "",
            "cover_color": "#246B45",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "settings_section": "aparencia",
        },
        files={"icon_file": ("icon2.png", TINY_PNG, "image/png")},
        follow_redirects=False,
    )
    assert swapped.status_code == 303
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.icon_image != icon_name
        assert club.cover_image == cover_name
        icon_name = club.icon_image
    finally:
        db.close()

    gif = owner.post(
        "/clubs",
        data={"name": "Icone Gif", "description": "", "rules": "", "cover_color": "#3A2348"},
        files={"icon_file": ("icon.gif", TINY_GIF, "image/gif")},
        follow_redirects=False,
    )
    assert gif.status_code == 303
    gif_id = int(gif.headers["location"].rsplit("/", 1)[-1])
    bad_type = owner.post(
        "/clubs",
        data={"name": "Icone Txt", "description": "", "rules": "", "cover_color": "#3A2348"},
        files={"icon_file": ("notes.txt", b"hello", "text/plain")},
        follow_redirects=False,
    )
    assert bad_type.status_code == 303
    bad_id = int(bad_type.headers["location"].rsplit("/", 1)[-1])
    oversized = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Icone Foto",
            "description": "",
            "rules": "",
            "cover_color": "#246B45",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "settings_section": "aparencia",
        },
        files={"icon_file": ("icon.png", b"x" * (2 * 1024 * 1024 + 8), "image/png")},
        follow_redirects=False,
    )
    assert oversized.status_code == 303
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        kept_name = club.name
        kept_description = club.description
        kept_rules = club.rules
        kept_cover_color = club.cover_color
        icon_name = club.icon_image
        cover_name = club.cover_image
    finally:
        db.close()
    assert stored_icon_path(icon_name) is not None
    ignored_clear = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Icone Foto",
            "description": "",
            "rules": "",
            "cover_color": "#246B45",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "clear_icon": "1",
            "settings_section": "aparencia",
        },
        follow_redirects=False,
    )
    assert ignored_clear.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(Club, club_id).icon_image == icon_name
    finally:
        db.close()
    cleared = owner.post(f"/clubs/{club_id}/icon/remover", follow_redirects=False)
    assert cleared.status_code == 204
    empty_clear = owner.post(f"/clubs/{empty_id}/icon/remover", follow_redirects=False)
    assert empty_clear.status_code == 204
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert db.get(Club, gif_id).icon_image is None
        assert db.get(Club, bad_id).icon_image is None
        assert club.icon_image is None
        assert club.cover_image == cover_name
        assert club.name == kept_name
        assert club.description == kept_description
        assert club.rules == kept_rules
        assert club.cover_color == kept_cover_color
        assert db.get(Club, empty_id).icon_image is None
    finally:
        db.close()
    assert stored_icon_path(icon_name) is None
    after_clear = owner.get(f"/clubs/{club_id}/config")
    remove_open = after_clear.text.split("js-icon-remove-open", 1)[1].split(">", 1)[0]
    assert "hidden" in remove_open

    restored = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Icone Foto",
            "description": "",
            "rules": "",
            "cover_color": "#246B45",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "settings_section": "aparencia",
        },
        files={"icon_file": ("icon3.png", TINY_PNG, "image/png")},
        follow_redirects=False,
    )
    assert restored.status_code == 303
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        icon_name = club.icon_image
        cover_name = club.cover_image
        assert icon_name
    finally:
        db.close()

    guest = TestClient(app)
    register_active(guest, "icon_membro", "icon.membro@example.com")
    guest.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    blocked = guest.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Hackeado",
            "description": "",
            "rules": "",
            "cover_color": "#7A3048",
            "settings_section": "aparencia",
        },
        files={"icon_file": ("icon.png", TINY_PNG, "image/png")},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert blocked.headers["location"] == f"/clubs/{club_id}"
    member_remove = guest.post(f"/clubs/{club_id}/icon/remover", follow_redirects=False)
    assert member_remove.status_code == 403

    helper = TestClient(app)
    register_active(helper, "icon_sub", "icon.sub@example.com")
    helper.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    db = SessionLocal()
    try:
        helper_id = db.scalar(select(User.id).where(User.username_key == "icon_sub"))
    finally:
        db.close()
    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": ROLE_SUPPORT, "support_perm": [PERM_TAG]},
        follow_redirects=False,
    )
    sub_remove = helper.post(f"/clubs/{club_id}/icon/remover", follow_redirects=False)
    assert sub_remove.status_code == 403
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.icon_image == icon_name
        assert club.cover_image == cover_name
        assert club.name == "Icone Foto"
    finally:
        db.close()


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
        assert club.cover_color == "#246B45"
        assert club.description == "Sobre o grupo"
        assert member.role == "admin"
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
    assert f"/clubs/{club_id}/config" not in member_page.text
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
    assert "Assistindo" in default_tab.text
    assert "Finalizados" in default_tab.text
    assert "Buscar na TVMaze" not in default_tab.text
    assert "Pesquisar série, filme, animação..." in default_tab.text
    assert 'aria-label="Adicionar manualmente"' in default_tab.text
    assert "Nenhum título por aqui ainda." in default_tab.text
    assert "Escreva para o clube" not in default_tab.text

    sent = owner.post(f"/clubs/{club_id}/mensagens", data={"body": "Vamos maratonar?"}, follow_redirects=False)
    assert sent.status_code == 303
    chat = owner.get(f"/clubs/{club_id}?aba=chat")
    assert "Vamos maratonar?" in chat.text
    assert "Chat Host" in chat.text or "chat_host" in chat.text.lower() or "chat host" in chat.text.lower()
    assert "js-chat-input" in chat.text
    assert 'aria-label="Emoji"' in chat.text
    assert "js-emoji-picker" in chat.text
    assert "js-emoji-panel" in chat.text
    assert 'aria-label="Spoiler"' in chat.text
    assert 'aria-label="Atualizar"' in chat.text
    assert "Atualizar" not in chat.text.split("chat-form")[-1]
    formatted = owner.post(
        f"/clubs/{club_id}/mensagens",
        data={"body": "**negrito** *italico* ||spoiler|| <script>x</script>"},
        follow_redirects=False,
    )
    assert formatted.status_code == 303
    rich = owner.get(f"/clubs/{club_id}?aba=chat")
    assert "<strong>negrito</strong>" in rich.text
    assert "<em>italico</em>" in rich.text
    assert 'class="chat-spoiler"' in rich.text
    assert "<script>x</script>" not in rich.text
    assert "&lt;script&gt;x&lt;/script&gt;" in rich.text

    added = owner.post(
        f"/clubs/{club_id}/titulos",
        data={"name": "Filme da Casa", "kind": "filme", "image_url": "https://example.com/p.jpg"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    watching = owner.get(f"/clubs/{club_id}")
    assert "Filme da Casa" in watching.text
    assert "Filme" in watching.text
    assert "Marcar como finalizado" in watching.text
    assert "watch-title" in watching.text
    assert "Ver detalhes" not in watching.text

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
    assert marked.headers["location"] == f"/clubs/{club_id}?aba=assistindo&lista=finalizados"
    watched = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=finalizados")
    assert "Já assistimos" in watched.text
    assert "Filme da Casa" in watched.text
    assert "Voltar para Assistindo" in watched.text
    empty_watching = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=xyz")
    assert "Filme da Casa" not in empty_watching.text
    assert "Nenhum título por aqui ainda." in empty_watching.text
    restored = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/status",
        data={"watch_status": "watching"},
        follow_redirects=False,
    )
    assert restored.status_code == 303
    assert restored.headers["location"] == f"/clubs/{club_id}?aba=assistindo&lista=assistindo"

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
    assert "Ainda sem avaliações" not in page.text
    assert "Sua avaliação:" not in page.text
    assert "star-read" not in page.text
    assert page.text.count("star-btn") == 5
    assert star_button_values(page.text) == ["1", "2", "3", "4", "5"]
    assert "Média do clube: sem avaliações" in page.text
    assert "Remover do clube" in page.text

    db = SessionLocal()
    try:
        show = db.scalar(select(Show).where(Show.tvmaze_id == 169))
        show_id = show.id
        assert show.genres and "Drama" in show.genres
    finally:
        db.close()

    rated = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/avaliar",
        data={"stars": "5", "lista": "assistindo"},
        follow_redirects=False,
    )
    assert rated.status_code == 303
    assert rated.headers["location"] == f"/clubs/{club_id}?aba=assistindo&lista=assistindo"
    after = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=assistindo")
    assert "5,0" in after.text
    assert "Média do clube: 5,0 de 5" in after.text
    assert "1 avaliação" not in after.text
    assert "Sua avaliação:" not in after.text
    assert after.text.count('aria-pressed="true"') == 1
    assert after.text.count("star-btn is-on") == 5

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
    averaged = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "Média do clube: 4,0 de 5" in averaged.text
    assert averaged.text.count("star-btn is-on") == 5
    guest_view = guest.get(f"/clubs/{club_id}?aba=assistindo")
    assert "Média do clube: 4,0 de 5" in guest_view.text
    assert guest_view.text.count("star-btn is-on") == 3
    changed = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/avaliar",
        data={"stars": "5"},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert changed.headers["location"] == f"/clubs/{club_id}?aba=assistindo&lista=assistindo"
    owner.post(
        f"/clubs/{club_id}/shows/{show_id}/avaliar",
        data={"stars": "4", "lista": "assistindo"},
        follow_redirects=False,
    )
    updated = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "Média do clube: 3,5 de 5" in updated.text
    assert updated.text.count("star-btn is-on") == 4
    unsafe = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/avaliar",
        data={"stars": "4", "lista": "https://example.com"},
        follow_redirects=False,
    )
    assert unsafe.headers["location"] == f"/clubs/{club_id}?aba=assistindo&lista=assistindo"

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


def test_rating_from_finalizados_stays_on_finalizados():
    owner = TestClient(app)
    register_active(owner, "nota_lista", "nota.lista@example.com")
    created = owner.post("/clubs", data={"name": "Sala Lista Nota"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    added = owner.post(
        f"/clubs/{club_id}/titulos",
        data={"name": "Obra Finalizada", "kind": "serie"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    db = SessionLocal()
    try:
        show_id = db.scalar(select(ClubShow.show_id).where(ClubShow.club_id == club_id).order_by(ClubShow.id.desc()))
        assert show_id
    finally:
        db.close()
    owner.post(
        f"/clubs/{club_id}/shows/{show_id}/status",
        data={"watch_status": "watched"},
        follow_redirects=False,
    )
    finished = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=finalizados")
    assert "Obra Finalizada" in finished.text
    assert 'name="lista" value="finalizados"' in finished.text
    assert "Sua avaliação:" not in finished.text
    rated = owner.post(
        f"/clubs/{club_id}/shows/{show_id}/avaliar",
        data={"stars": "4", "lista": "finalizados"},
        follow_redirects=False,
    )
    assert rated.status_code == 303
    assert rated.headers["location"] == f"/clubs/{club_id}?aba=assistindo&lista=finalizados"
    after = owner.get(rated.headers["location"])
    assert "Obra Finalizada" in after.text
    assert "Voltar para Assistindo" in after.text
    assert "Média do clube: 4,0 de 5" in after.text
    assert after.text.count("star-btn") == 5
    assert star_button_values(after.text) == ["1", "2", "3", "4", "5"]
    watching = owner.get(f"/clubs/{club_id}?aba=assistindo&lista=assistindo")
    assert "Obra Finalizada" not in watching.text


def test_friends_private_chat_history_and_auth():
    from app.models import DirectMessage

    host = TestClient(app)
    register_active(host, "amizade_a", "amizade.a@example.com", name="Amizade A")
    created = host.post("/clubs", data={"name": "Clube Amigos"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        code = db.get(Club, club_id).join_code
    finally:
        db.close()

    guest = TestClient(app)
    register_active(guest, "amizade_b", "amizade.b@example.com", name="Amizade B")
    guest.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)

    self_invite = host.post("/amigos/amizade_a/convidar", data={"next": "/amigos"}, follow_redirects=False)
    assert self_invite.status_code == 303
    assert "error=" in self_invite.headers["location"]

    before = guest.post("/mensagens/amizade_a", data={"body": "cedo demais"}, follow_redirects=False)
    assert before.status_code == 303
    assert "/u/amizade_a" in before.headers["location"]
    blocked_get = guest.get("/mensagens/amizade_a", follow_redirects=False)
    assert blocked_get.status_code == 303
    assert blocked_get.headers["location"] == "/u/amizade_a"

    invited = host.post("/amigos/amizade_b/convidar", data={"next": "/u/amizade_b"}, follow_redirects=False)
    assert invited.status_code == 303
    pending = host.get("/u/amizade_b?ok=Pedido+enviado")
    assert pending.text.count("Pedido enviado") == 1
    assert "Cancelar pedido" in pending.text
    assert "Vocês são amigos" not in pending.text
    assert "Desfazer amizade" not in pending.text
    again = host.post("/amigos/amizade_b/convidar", data={"next": "/u/amizade_b"}, follow_redirects=False)
    assert "error=" in again.headers["location"]

    amigos = guest.get("/amigos")
    assert "Amizade A" in amigos.text
    assert "Aceitar" in amigos.text
    assert "Solicitações de amizade" in amigos.text
    assert "Seus amigos" in amigos.text
    accepted = guest.post("/amigos/amizade_a/aceitar", data={"next": "/amigos"}, follow_redirects=False)
    assert accepted.status_code == 303
    stale = host.get("/u/amizade_b?ok=Pedido+enviado")
    assert "Pedido enviado" not in stale.text
    assert "Vocês são amigos" in stale.text
    assert "Conversar" in stale.text
    assert "Desfazer amizade" in stale.text
    assert "Cancelar pedido" not in stale.text
    other_side = guest.get("/u/amizade_a")
    assert "Vocês são amigos" in other_side.text
    assert "Conversar" in other_side.text

    sent = host.post("/mensagens/amizade_b", data={"body": "segredo-do-par"}, follow_redirects=False)
    assert sent.status_code == 303
    assert sent.headers["location"] == "/mensagens/amizade_b"
    thread = host.get("/mensagens/amizade_b")
    assert "segredo-do-par" in thread.text
    assert 'action="/mensagens/amizade_b"' in thread.text
    same = guest.get("/mensagens/amizade_a")
    assert "segredo-do-par" in same.text

    friends_page = host.get("/amigos")
    assert "Conversar" in friends_page.text
    assert 'href="/mensagens/amizade_b"' in friends_page.text

    chat = host.get(f"/clubs/{club_id}?aba=chat")
    assert f"/u/amizade_b?clube={club_id}" in chat.text
    assert "/mensagens/amizade_b" not in chat.text
    people = host.get(f"/clubs/{club_id}/membros")
    assert f"/u/amizade_b?clube={club_id}" in people.text
    assert "/mensagens/amizade_b" not in people.text

    undone = host.post("/amigos/amizade_b/desfazer", data={"next": "/amigos"}, follow_redirects=False)
    assert undone.status_code == 303
    history = host.get("/mensagens/amizade_b")
    assert "segredo-do-par" in history.text
    assert "não são mais amigos" in history.text.lower()
    assert 'action="/mensagens/amizade_b"' not in history.text
    blocked_again = host.post("/mensagens/amizade_b", data={"body": "depois do corte"}, follow_redirects=False)
    assert blocked_again.status_code == 303
    after_unfriend = host.get("/mensagens/amizade_b")
    assert "depois do corte" not in after_unfriend.text
    assert "segredo-do-par" in after_unfriend.text

    chat_after = host.get(f"/clubs/{club_id}?aba=chat")
    assert "/mensagens/amizade_b" not in chat_after.text
    assert "/u/amizade_b" in chat_after.text
    people_after = host.get(f"/clubs/{club_id}/membros")
    assert "/mensagens/amizade_b" not in people_after.text
    assert "/u/amizade_b" in people_after.text

    host.post("/amigos/amizade_b/convidar", data={"next": "/amigos"}, follow_redirects=False)
    guest.post("/amigos/amizade_a/aceitar", data={"next": "/amigos"}, follow_redirects=False)
    restored = host.get("/mensagens/amizade_b")
    assert "segredo-do-par" in restored.text
    assert 'action="/mensagens/amizade_b"' in restored.text
    db = SessionLocal()
    try:
        count = len(list(db.scalars(select(DirectMessage).where(DirectMessage.body == "segredo-do-par"))))
        assert count == 1
    finally:
        db.close()

    stranger = TestClient(app)
    register_active(stranger, "amizade_c", "amizade.c@example.com", name="Amizade C")
    peek = stranger.get("/mensagens/amizade_a", follow_redirects=False)
    assert peek.status_code == 303
    assert peek.headers["location"] == "/u/amizade_a"
    profile = stranger.get("/u/amizade_a")
    assert "segredo-do-par" not in profile.text
    stranger.post("/amigos/amizade_a/convidar", data={"next": "/amigos"}, follow_redirects=False)
    host.post("/amigos/amizade_c/aceitar", data={"next": "/amigos"}, follow_redirects=False)
    other_thread = stranger.get("/mensagens/amizade_a")
    assert "segredo-do-par" not in other_thread.text
    assert "Nenhuma mensagem ainda" in other_thread.text


def test_back_button_only_when_logged_in():
    member = TestClient(app)
    register_active(member, "volta_user", "volta.user@example.com")
    home = member.get("/")
    assert 'aria-label="Voltar"' not in home.text
    assert 'class="back-btn js-back"' not in home.text
    assert "js-sidebar-toggle" in home.text
    assert "Início" in home.text
    conta = member.get("/conta")
    assert 'aria-label="Voltar"' not in conta.text
    from_home = member.get("/conta", headers={"Referer": "http://testserver/"})
    assert 'aria-label="Voltar"' in from_home.text
    assert 'class="back-btn" href="/"' in from_home.text
    assert "history.back" not in from_home.text
    external = member.get("/conta", headers={"Referer": "https://evil.example/phish"})
    assert "evil.example" not in external.text
    assert 'class="back-btn" href="/"' in external.text
    guest = TestClient(app)
    home_guest = guest.get("/")
    assert 'aria-label="Voltar"' not in home_guest.text


def test_manual_presence_survives_heartbeat():
    from datetime import timedelta

    from app.accounts import utcnow
    from app.presence import AWAY_SECONDS, ONLINE_SECONDS, presence_of

    member = TestClient(app)
    register_active(member, "pref_user", "pref.user@example.com")
    away = member.post("/presenca", data={"status": "away", "prefer": "1"})
    assert away.json()["status"] == "away"
    ping = member.post("/presenca", data={"status": "online"})
    assert ping.json()["status"] == "away"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username_key == "pref_user"))
        assert user.presence_pref == "away"
        user.last_seen = utcnow() - timedelta(seconds=AWAY_SECONDS + 30)
        db.commit()
        db.refresh(user)
        assert presence_of(user) == "offline"
        user.presence_pref = "online"
        user.last_seen = utcnow()
        db.commit()
        db.refresh(user)
        assert presence_of(user) == "online"
        user.last_seen = utcnow() - timedelta(seconds=ONLINE_SECONDS + 30)
        db.commit()
        db.refresh(user)
        assert presence_of(user) == "offline"
        user.presence_pref = "offline"
        user.last_seen = utcnow()
        db.commit()
        db.refresh(user)
        assert presence_of(user) == "offline"
    finally:
        db.close()
    still = member.post("/presenca", data={"status": "online"})
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username_key == "pref_user"))
        assert user.presence_pref == "offline"
        assert presence_of(user) == "offline"
    finally:
        db.close()
    assert still.json()["status"] == "offline"


def test_closed_club_join_requests_and_code():
    owner = TestClient(app)
    register_active(owner, "pedido_host", "pedido.host@example.com", name="Pedido Host")
    created = owner.post("/clubs", data={"name": "Sala Pedido", "is_closed": "1"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        code = db.get(Club, club_id).join_code
    finally:
        db.close()

    member = TestClient(app)
    register_active(member, "pedido_membro", "pedido.membro@example.com", name="Pedido Membro")
    asked_member = member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    assert asked_member.status_code == 303
    assert "Pedido" in asked_member.headers["location"]
    waiting_page = member.get(f"/clubs/{club_id}")
    assert waiting_page.status_code == 403
    db = SessionLocal()
    try:
        member_user = db.scalar(select(User).where(User.username_key == "pedido_membro"))
        member_id = member_user.id
        pending_member = db.scalar(
            select(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == member_id)
        )
        assert pending_member is not None
        assert db.scalar(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == member_id)) is None
        assert db.scalar(select(func.count()).select_from(ClubMember).where(ClubMember.club_id == club_id)) == 1
    finally:
        db.close()
    owner.post(f"/clubs/{club_id}/solicitacoes/{member_id}/aceitar", follow_redirects=False)
    inside = member.get(f"/clubs/{club_id}")
    assert inside.status_code == 200
    assert "Solicitações" not in inside.text
    assert f'href="/u/pedido_host?clube={club_id}"' in inside.text

    waiting = TestClient(app)
    register_active(waiting, "pedido_guest", "pedido.guest@example.com", name="Pedido Guest")
    asked = waiting.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    assert asked.status_code == 303
    locked = waiting.get(f"/clubs/{club_id}")
    assert locked.status_code == 403
    assert "Pedido enviado" in locked.text

    db = SessionLocal()
    try:
        guest = db.scalar(select(User).where(User.username_key == "pedido_guest"))
        guest_id = guest.id
        pending = db.scalar(
            select(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == guest_id)
        )
        assert pending is not None
    finally:
        db.close()

    blocked = member.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/aceitar", follow_redirects=False)
    assert blocked.status_code == 403
    accepted = owner.post(f"/clubs/{club_id}/solicitacoes/{guest_id}/aceitar", follow_redirects=False)
    assert accepted.status_code == 303
    joined = waiting.get(f"/clubs/{club_id}")
    assert joined.status_code == 200

    other = TestClient(app)
    register_active(other, "pedido_recusa", "pedido.recusa@example.com", name="Pedido Recusa")
    other.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    db = SessionLocal()
    try:
        recusado = db.scalar(select(User).where(User.username_key == "pedido_recusa"))
        recusado_id = recusado.id
    finally:
        db.close()
    owner_page = owner.get(f"/clubs/{club_id}")
    assert "Solicitações" in owner_page.text
    assert "Pedido Recusa" in owner_page.text
    refused = owner.post(f"/clubs/{club_id}/solicitacoes/{recusado_id}/recusar", follow_redirects=False)
    assert refused.status_code == 303
    still_out = other.get(f"/clubs/{club_id}")
    assert still_out.status_code == 403
    instant = TestClient(app)
    register_active(instant, "pedido_codigo", "pedido.codigo@example.com")
    joined_code = instant.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    assert joined_code.status_code == 303
    assert joined_code.headers["location"].startswith(f"/clubs/{club_id}")
    assert "Pedido" in joined_code.headers["location"]
    still_locked = instant.get(f"/clubs/{club_id}")
    assert still_locked.status_code == 403
    db = SessionLocal()
    try:
        instant_id = db.scalar(select(User.id).where(User.username_key == "pedido_codigo"))
        assert db.scalar(select(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == instant_id))
        assert db.scalar(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == instant_id)) is None
        first_id = db.scalar(select(ClubJoinRequest.id).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == instant_id))
    finally:
        db.close()
    again = instant.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    assert again.status_code == 303
    db = SessionLocal()
    try:
        dupes = list(
            db.scalars(select(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == instant_id))
        )
        assert len(dupes) == 1
        assert dupes[0].id == first_id
    finally:
        db.close()


def test_leave_confirmation_ui_does_not_block_post():
    owner = TestClient(app)
    register_active(owner, "sai_host", "sai.host@example.com")
    created = owner.post("/clubs", data={"name": "Sala Saida"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    room = owner.get(f"/clubs/{club_id}")
    assert "js-leave-open" in room.text
    assert 'id="leave-dialog"' in room.text
    assert 'action="/clubs/%s/leave"' % club_id in room.text
    account = owner.get("/conta")
    assert "js-leave-open" in account.text
    assert 'id="leave-dialog"' in account.text
    assert f'data-leave-action="/clubs/{club_id}/leave"' in account.text
    assert 'type="submit">Sair do clube</button>' not in room.text.split("leave-dialog")[0]


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def test_avatar_registry_upload_and_fallback():
    from types import SimpleNamespace

    from app.avatars import avatar_url, parse_illustrated_choice

    fox = SimpleNamespace(avatar="fox", avatar_type="illustrated", avatar_provider="watchclub", avatar_value="fox")
    assert avatar_url(fox) == "/static/avatars/fox.svg"
    popcorn = SimpleNamespace(avatar="popcorn", avatar_type="illustrated", avatar_provider="watchclub", avatar_value="popcorn")
    assert avatar_url(popcorn) == "/static/avatars/popcorn.svg"
    tyger = SimpleNamespace(avatar="popcorn", avatar_type="illustrated", avatar_provider="tyger", avatar_value="TrIggy")
    assert avatar_url(tyger) == "/static/avatars/tyger/TrIggy.svg"
    invalid_provider = SimpleNamespace(avatar="fox", avatar_type="illustrated", avatar_provider="unknown", avatar_value="TrIggy")
    assert avatar_url(invalid_provider) == "/static/avatars/fox.svg"
    invalid_value = SimpleNamespace(avatar="popcorn", avatar_type="illustrated", avatar_provider="tyger", avatar_value="https://evil.example/x.svg")
    assert avatar_url(invalid_value) == "/static/avatars/popcorn.svg"
    missing_file = SimpleNamespace(avatar="popcorn", avatar_type="illustrated", avatar_provider="tyger", avatar_value="TrMissing")
    assert avatar_url(missing_file) == "/static/avatars/popcorn.svg"
    assert parse_illustrated_choice("https://evil.example/x.svg") is None
    assert parse_illustrated_choice("tyger:https://evil.example/x.svg") is None
    assert parse_illustrated_choice("tyger:/etc/passwd") is None
    assert parse_illustrated_choice("tyger:TrIggy") == ("tyger", "TrIggy")

    person = TestClient(app)
    register_active(person, "avatar_sys", "avatar.sys@example.com")
    account = person.get("/conta")
    assert 'src="/static/avatars/popcorn.svg"' in account.text
    assert 'data-presence="' in account.text
    assert "Enviar foto" in account.text
    assert "Escolher avatar" in account.text
    assert "Escolha seu avatar" in account.text
    assert 'id="photo-crop-dialog"' in account.text
    assert 'value="tyger:TrIggy"' in account.text
    assert "Buscar na TVMaze" not in account.text

    legacy = person.post("/conta/avatar", data={"avatar": "fox"}, follow_redirects=False)
    assert legacy.status_code == 303
    fox_page = person.get("/conta")
    assert 'src="/static/avatars/fox.svg"' in fox_page.text
    assert 'data-slot="avatar-badge"' in fox_page.text
    home = person.get("/")
    assert 'src="/static/avatars/fox.svg"' in home.text
    profile = person.get("/u/avatar_sys")
    assert 'src="/static/avatars/fox.svg"' in profile.text

    blocked = person.post(
        "/conta/avatar",
        data={"choice": "tyger:https://evil.example/hack.svg"},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    still_fox = person.get("/conta")
    assert "evil.example" not in still_fox.text
    assert 'src="/static/avatars/fox.svg"' in still_fox.text

    invalid = person.post(
        "/conta/avatar",
        data={"choice": "nope:TrIggy"},
        follow_redirects=False,
    )
    assert invalid.status_code == 303
    assert 'src="/static/avatars/fox.svg"' in person.get("/conta").text

    illustrated = person.post("/conta/avatar", data={"choice": "tyger:TrIggy"}, follow_redirects=False)
    assert illustrated.status_code == 303
    tyger_page = person.get("/conta")
    assert 'src="/static/avatars/tyger/TrIggy.svg"' in tyger_page.text
    assert 'src="/static/avatars/fox.svg"' not in tyger_page.text.split("avatar-modal")[0]
    assert 'data-presence="' in tyger_page.text

    svg_upload = person.post(
        "/conta/avatar/foto",
        files={"photo": ("face.svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/svg+xml")},
        follow_redirects=False,
    )
    assert svg_upload.status_code == 303
    assert 'src="/static/avatars/tyger/TrIggy.svg"' in person.get("/conta").text

    photo = person.post(
        "/conta/avatar/foto",
        files={"photo": ("face.png", PNG_1X1, "image/png")},
        follow_redirects=False,
    )
    assert photo.status_code == 303
    photo_page = person.get("/conta")
    assert "/static/uploads/avatars/" in photo_page.text
    assert photo_page.text.count(".png") >= 1
    assert 'src="/static/avatars/tyger/TrIggy.svg"' not in photo_page.text.split("avatar-modal")[0]
    friends = person.get("/amigos")
    assert "/static/uploads/avatars/" in friends.text

    back = person.post("/conta/avatar", data={"choice": "watchclub:popcorn"}, follow_redirects=False)
    assert back.status_code == 303
    restored = person.get("/conta")
    assert 'src="/static/avatars/popcorn.svg"' in restored.text
    assert "/static/uploads/avatars/" not in restored.text.split("avatar-modal")[0]


def test_club_switcher_lists_membership_only():
    owner = TestClient(app)
    register_active(owner, "switch_own", "switch.own@example.com")
    first = owner.post("/clubs", data={"name": "Clube Alfa"}, follow_redirects=False)
    alfa_id = int(first.headers["location"].rsplit("/", 1)[-1])
    second = owner.post("/clubs", data={"name": "Clube Beta"}, follow_redirects=False)
    beta_id = int(second.headers["location"].rsplit("/", 1)[-1])

    stranger = TestClient(app)
    register_active(stranger, "switch_out", "switch.out@example.com")
    secret = stranger.post("/clubs", data={"name": "Clube Secreto"}, follow_redirects=False)
    secret_id = int(secret.headers["location"].rsplit("/", 1)[-1])

    db = SessionLocal()
    try:
        owner_id = db.scalar(select(User.id).where(User.username_key == "switch_own"))
        before = db.scalar(select(func.count()).select_from(ClubMember).where(ClubMember.user_id == owner_id))
    finally:
        db.close()

    page = owner.get(f"/clubs/{alfa_id}")
    assert page.status_code == 200
    assert "Trocar clube" in page.text
    assert "js-club-switch-toggle" in page.text
    assert "Seus clubes" in page.text
    assert "Ver todos os clubes" in page.text
    assert 'href="/clubes"' in page.text
    assert "js-leave-open" in page.text
    popover = page.text.split('id="club-switch-popover"', 1)[1].split("</div>", 2)[0]
    assert "Clube Alfa" in popover
    assert "Clube Beta" in popover
    assert "Clube Secreto" not in popover
    assert f'href="/clubs/{beta_id}"' in popover
    assert f'href="/clubs/{alfa_id}"' not in popover
    assert f'href="/clubs/{secret_id}"' not in popover
    assert 'aria-current="page"' in popover
    assert "club-mark" in popover
    assert "CA" in popover
    assert "CB" in popover

    other = owner.get(f"/clubs/{beta_id}")
    other_popover = other.text.split('id="club-switch-popover"', 1)[1].split("</div>", 2)[0]
    assert f'href="/clubs/{alfa_id}"' in other_popover
    assert f'href="/clubs/{beta_id}"' not in other_popover

    db = SessionLocal()
    try:
        after = db.scalar(select(func.count()).select_from(ClubMember).where(ClubMember.user_id == owner_id))
        assert after == before == 2
        member_ids = set(
            db.scalars(select(ClubMember.club_id).where(ClubMember.user_id == owner_id))
        )
        assert member_ids == {alfa_id, beta_id}
    finally:
        db.close()

    lonely = TestClient(app)
    register_active(lonely, "switch_one", "switch.one@example.com")
    only = lonely.post("/clubs", data={"name": "Clube Unico"}, follow_redirects=False)
    only_id = int(only.headers["location"].rsplit("/", 1)[-1])
    solo = lonely.get(f"/clubs/{only_id}")
    assert "Trocar clube" in solo.text
    solo_popover = solo.text.split('id="club-switch-popover"', 1)[1].split("</div>", 2)[0]
    assert "Clube Unico" in solo_popover
    assert 'aria-current="page"' in solo_popover
    assert f'href="/clubs/{only_id}"' not in solo_popover
    assert "Ver todos os clubes" in solo.text

    preview = lonely.get(f"/clubs/{alfa_id}")
    assert preview.status_code == 200
    assert "Trocar clube" not in preview.text
    assert "Participar" in preview.text

