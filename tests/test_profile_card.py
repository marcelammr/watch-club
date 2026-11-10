from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.accounts import utcnow
from app.db import SessionLocal
from app.main import app
from app.models import User
from app.player import (
    DEFAULT_THEME,
    DAYS_PER_LEVEL,
    PROFILE_STATUS_MAX,
    energy_hearts,
    player_progress,
    require_theme,
    theme_of,
)
from tests.test_app import register_active
from tests.test_suggestions import _user_id


def test_level_is_deterministic_from_account_age():
    now = utcnow()
    fresh = player_progress(now, now=now)
    assert fresh["level"] == 1
    assert fresh["percent"] == 0
    mid = player_progress(now - timedelta(days=DAYS_PER_LEVEL + 15), now=now)
    assert mid["level"] == 2
    assert mid["percent"] == 50
    old = player_progress(now - timedelta(days=DAYS_PER_LEVEL * 120), now=now)
    assert old["level"] == 99
    assert old["percent"] == 100


def test_energy_uses_last_seen_only():
    now = utcnow()
    assert energy_hearts(None, now=now) == 0
    assert energy_hearts(now, now=now) == 5
    assert energy_hearts(now - timedelta(days=2), now=now) == 4
    assert energy_hearts(now - timedelta(days=40), now=now) == 0


def test_own_and_other_profile_open_with_real_stats():
    owner = TestClient(app)
    guest = TestClient(app)
    register_active(owner, "pcard_own", "pcard.own@example.com", name="Carta Dona")
    register_active(guest, "pcard_guest", "pcard.guest@example.com")
    created = owner.post("/clubs", data={"name": "Clube Carta"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    guest.post("/clubs/join", data={"join_code": _join_code(club_id), "next": "/"}, follow_redirects=False)
    own = owner.get("/u/pcard_own")
    assert own.status_code == 200
    assert "Player Card" in own.text
    assert "Perfil" in own.text
    assert "Carta Dona" in own.text
    assert "@pcard_own" in own.text
    assert "Clubes" in own.text
    assert "Amigos" in own.text
    assert "Favoritos" in own.text
    assert "Membro desde" in own.text
    assert "Aparência" in own.text
    other = guest.get("/u/pcard_own")
    assert other.status_code == 200
    assert "Adicionar amigo" in other.text
    assert "Denunciar" in other.text
    assert "Bloquear usuário" in other.text
    assert "Aparência" not in other.text.split("wc-tabs", 1)[1].split("player-card", 1)[0]


def _join_code(club_id: int) -> str:
    from app.models import Club

    db = SessionLocal()
    try:
        return db.get(Club, club_id).join_code
    finally:
        db.close()


def test_status_optional_limit_and_owner_only():
    owner = TestClient(app)
    guest = TestClient(app)
    register_active(owner, "stat_own", "stat.own@example.com")
    register_active(guest, "stat_guest", "stat.guest@example.com")
    blank = owner.post("/u/stat_own/status", data={"status": ""}, follow_redirects=False)
    assert blank.status_code == 303
    page = owner.get("/u/stat_own")
    assert "Sem status ainda" in page.text
    ok = owner.post(
        "/u/stat_own/status",
        data={"status": "tentando terminar 6 séries ao mesmo tempo"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    shown = owner.get("/u/stat_own")
    assert "tentando terminar 6 séries ao mesmo tempo" in shown.text
    too_long = owner.post(
        "/u/stat_own/status",
        data={"status": "x" * (PROFILE_STATUS_MAX + 1)},
        follow_redirects=False,
    )
    assert "error=" in too_long.headers["location"]
    stolen = guest.post(
        "/u/stat_own/status",
        data={"status": "hack"},
        follow_redirects=False,
    )
    assert stolen.status_code == 303
    assert "error=" in stolen.headers["location"] or stolen.headers["location"].startswith("/u/stat_own")
    after = owner.get("/u/stat_own")
    assert "hack" not in after.text
    xss = owner.post(
        "/u/stat_own/status",
        data={"status": '<script>alert(1)</script>'},
        follow_redirects=False,
    )
    assert xss.status_code == 303
    escaped = owner.get("/u/stat_own")
    assert "<script>alert(1)</script>" not in escaped.text
    assert "&lt;script&gt;" in escaped.text or "alert(1)" not in escaped.text


def test_themes_persist_and_stay_scoped():
    owner = TestClient(app)
    guest = TestClient(app)
    register_active(owner, "theme_own", "theme.own@example.com")
    register_active(guest, "theme_guest", "theme.guest@example.com")
    page = owner.get("/u/theme_own")
    assert 'data-theme="watchclub"' in page.text
    assert "profile-lab wc-theme-watchclub" in page.text
    for key in ("watchclub", "bubblegum", "cyber", "dreamy"):
        saved = owner.post("/u/theme_own/tema", data={"theme": key}, follow_redirects=False)
        assert saved.status_code == 303
        mine = owner.get("/u/theme_own?aba=aparencia")
        assert f"theme-preview wc-theme-{key}" in mine.text
        assert f'theme-preview wc-theme-{key} is-on' in mine.text or f'wc-theme-{key} is-on' in mine.text
        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.email == "theme.own@example.com"))
            assert theme_of(user) == key
        finally:
            db.close()
    bad = owner.post("/u/theme_own/tema", data={"theme": "rainbow-hacks"}, follow_redirects=False)
    assert "error=" in bad.headers["location"]
    owner.post("/u/theme_own/tema", data={"theme": "bubblegum"}, follow_redirects=False)
    visited = guest.get("/u/theme_own")
    assert 'data-theme="bubblegum"' in visited.text
    assert "profile-head wc-theme-bubblegum" in visited.text
    assert "profile-lab wc-theme-watchclub" in visited.text
    assert "profile-lab wc-theme-bubblegum" not in visited.text
    stolen = guest.post("/u/theme_own/tema", data={"theme": "cyber"}, follow_redirects=False)
    assert stolen.status_code == 303
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "theme.own@example.com"))
        assert theme_of(user) == "bubblegum"
        guest_user = db.scalar(select(User).where(User.email == "theme.guest@example.com"))
        assert theme_of(guest_user) == DEFAULT_THEME
    finally:
        db.close()


def test_invalid_theme_helper_rejects():
    try:
        require_theme("nope")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("expected rejection")


def test_player_card_popover_keeps_account_actions():
    person = TestClient(app)
    register_active(person, "pcard_menu", "pcard.menu@example.com")
    home = person.get("/")
    popover = home.text.split('id="account-popover"', 1)[1]
    assert "Player Card" in popover
    assert 'href="/u/pcard_menu"' in popover
    assert "Ver perfil" in popover
    assert "Editar perfil" in popover
    assert 'href="/conta"' in popover
    assert "Sair da sessão" in popover
    assert "js-status-toggle" in popover
    assert "HP" in popover
    assert "LV." in popover
    assert "html" in home.text and "wc-theme-watchclub" in home.text


def test_friendship_from_profile_still_works():
    owner = TestClient(app)
    guest = TestClient(app)
    register_active(owner, "pf_own", "pf.own@example.com")
    register_active(guest, "pf_guest", "pf.guest@example.com")
    sent = guest.post(
        "/amigos/pf_own/convidar",
        data={"next": "/u/pf_own"},
        follow_redirects=False,
    )
    assert sent.status_code == 303
    page = guest.get("/u/pf_own")
    assert "Pedido enviado" in page.text
    accepted = owner.post(
        "/amigos/pf_guest/aceitar",
        data={"next": "/u/pf_guest"},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    friends = owner.get("/u/pf_guest")
    assert "Vocês são amigos" in friends.text
    stats = owner.get("/u/pf_own")
    assert "<dt>Amigos</dt><dd>01</dd>" in stats.text


def test_profile_tabs_and_safety_routes_untouched():
    person = TestClient(app)
    register_active(person, "ptab_a", "ptab.a@example.com")
    page = person.get("/u/ptab_a?aba=favoritos")
    assert "Programas favoritos" in page.text
    clubs = person.get("/u/ptab_a?aba=clubes")
    assert "Meus clubes" in clubs.text
    look = person.get("/u/ptab_a?aba=aparencia")
    assert "Aparência" in look.text
    hub = person.get("/seguranca")
    assert hub.status_code == 200
    admin = person.get("/admin/denuncias", follow_redirects=False)
    assert admin.status_code == 303
    home = person.get("/")
    assert "Player Profile" not in home.text
    assert _user_id("ptab.a@example.com")
