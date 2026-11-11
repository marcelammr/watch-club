from fastapi.testclient import TestClient

from app.club_tags import parse_tag_emojis
from app.main import app
from app.markup import format_chat
from app.pixel_emoji import (
    PACKS,
    PACK_TOKEN_RE,
    TOKEN_RE,
    catalog,
    catalog_for,
    is_sticker_message,
    pack_available,
    picker_catalog,
    render_tokens,
    sprite_exists,
)
from tests.test_app import register_active
from tests.test_pixel_art import _png


def test_catalog_and_tokens_render_when_pack_present():
    data = catalog()
    assert data["pack"] == "JOI3"
    if not pack_available():
        html = str(render_tokens("oi :joi3-1:"))
        assert ":joi3-1:" in html
        return
    assert data["count"] >= 1
    first = data["items"][0]
    assert TOKEN_RE.fullmatch(first["token"])
    assert sprite_exists(int(first["id"]))
    html = str(format_chat("oi :joi3-" + str(first["id"]) + ": **x**"))
    assert "<img class=\"px-emoji\"" in html
    assert "<strong>x</strong>" in html
    assert str(format_chat("oi 😇")) == "oi 😇"
    missing = str(render_tokens(":joi3-99999:"))
    assert ":joi3-99999:" in missing
    assert "<img" not in missing


def test_historical_unicode_and_mixed_tag_parse():
    assert parse_tag_emojis("😇😈") == ["😇", "😈"]
    assert parse_tag_emojis("MC") is None
    if not pack_available():
        return
    first = catalog()["items"][0]
    token = first["token"]
    assert parse_tag_emojis(token) == [token]
    assert parse_tag_emojis(token + "😇") == [token, "😇"]
    assert parse_tag_emojis(token + token + token) is None
    assert parse_tag_emojis(":joi3-99999:") is None


def test_picker_catalog_and_club_presets_on_settings():
    owner = TestClient(app)
    register_active(owner, "joi3_own", "joi3.own@example.com")
    home = owner.get("/")
    assert home.status_code == 200
    assert 'id="joi3-emoji-catalog"' in home.text
    assert 'class="appearance-btn"' in home.text
    created = owner.post(
        "/clubs",
        data={"name": "Emoji Clube", "description": "", "rules": "", "cover_color": "#3A2348"},
        follow_redirects=False,
    )
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    page = owner.get(f"/clubs/{club_id}/config")
    assert "Estilo do ícone" in page.text
    assert "Estilo da capa" in page.text
    assert 'name="icon_preset"' in page.text
    assert 'name="cover_preset"' in page.text
    chat = owner.get(f"/clubs/{club_id}?aba=chat")
    assert chat.status_code == 200
    assert "js-emoji-grid-host" in chat.text
    assert "js-emoji-close" in chat.text
    assert 'aria-label="Emojis"' in chat.text or "Emojis" in chat.text
    assert "js-emoji-toggle" in chat.text
    assert ":joi3-" in (catalog()["items"][0]["token"] if catalog()["items"] else ":joi3-1:")
    profile = owner.get("/u/joi3_own")
    assert 'data-shape="portrait"' in profile.text
    header = owner.get("/")
    assert header.text.count('data-shape="circle"') >= 1


def test_missing_pack_does_not_destroy_chat(monkeypatch):
    monkeypatch.setattr("app.pixel_emoji.sprite_exists", lambda *_args, **_kwargs: False)
    html = str(format_chat("histórico 🍿 e :joi3-12:"))
    assert "🍿" in html
    assert ":joi3-12:" in html
    assert "<img" not in html


def test_club_member_cannot_change_icon_preset():
    owner = TestClient(app)
    member = TestClient(app)
    register_active(owner, "joi3_adm", "joi3.adm@example.com")
    register_active(member, "joi3_mem", "joi3.mem@example.com")
    created = owner.post(
        "/clubs",
        data={"name": "Preset Gate", "description": "", "rules": "", "cover_color": "#3A2348", "icon_preset": "cga"},
        files={"icon_file": ("icon.png", _png(48), "image/png")},
        follow_redirects=False,
    )
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    from app.db import SessionLocal
    from app.models import Club, ClubMember, User
    from sqlalchemy import select

    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        user = db.scalar(select(User).where(User.username == "joi3_mem"))
        db.add(ClubMember(club_id=club.id, user_id=user.id, role="member", support_perms=""))
        original_style = club.icon_style
        db.commit()
    finally:
        db.close()
    blocked = member.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Preset Gate",
            "description": "",
            "rules": "",
            "cover_color": "#3A2348",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "icon_preset": "pico8",
        },
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.icon_style == original_style
    finally:
        db.close()


def test_pack_registry_keeps_joi3_namespace_and_future_slots():
    assert "joi3" in PACKS
    assert PACKS["joi3"]["picker"] is True
    assert PACKS["joi3"]["label"] == "Emojis"
    assert PACKS["joyquest"]["picker"] is True
    assert PACKS["joyquest"]["label"] == "Reações"
    assert PACKS["social"]["picker"] is True
    assert PACKS["social"]["label"] == "Social"
    assert "pixelmojis" in PACKS
    assert PACKS["pixelmojis"]["picker"] is True
    assert PACKS["pixelmojis"]["tab"] == "emojis"
    data = picker_catalog()
    assert data["pack"] == "JOI3"
    picker_ids = {pack["id"] for pack in data["packs"]}
    assert "emojis" in picker_ids
    assert "reactions" in picker_ids
    assert "social" in picker_ids
    assert "pixelmojis" not in picker_ids
    assert "joi3" not in picker_ids
    unknown = str(render_tokens("oi :packb-25:"))
    assert ":packb-25:" in unknown
    assert "<img" not in unknown
    assert PACK_TOKEN_RE.fullmatch(":joi3-12:")
    assert PACK_TOKEN_RE.fullmatch(":packb-25:")
    assert PACK_TOKEN_RE.fullmatch(":pixelmojis-12:")
    assert PACK_TOKEN_RE.fullmatch(":joyquest-3:")
    assert PACK_TOKEN_RE.fullmatch(":social-8:")
    if catalog()["items"]:
        assert catalog()["items"][0]["token"].startswith(":joi3-")
    traversal = str(render_tokens(":../secret-1:"))
    assert "<img" not in traversal


def test_emoji_picker_is_reused_and_sits_above_page():
    owner = TestClient(app)
    register_active(owner, "pick_own", "pick.own@example.com")
    other = TestClient(app)
    register_active(other, "pick_pal", "pick.pal@example.com")
    created = owner.post(
        "/clubs",
        data={"name": "Picker Club", "description": "", "rules": "", "cover_color": "#3A2348"},
        follow_redirects=False,
    )
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    chat = owner.get(f"/clubs/{club_id}?aba=chat")
    assert chat.status_code == 200
    assert "js-emoji-panel" in chat.text
    assert "js-emoji-toggle" in chat.text
    assert "emoji-panel" in chat.text
    css = owner.get("/static/style.css").text
    compact = css.replace(" ", "")
    assert "z-index:80" in compact or "z-index: 80" in css
    assert "999999" not in css
    assert "image-rendering:pixelated" in compact
    assert ".chat-body.is-sticker" in css or ".chat-body.is-sticker" in compact
    settings = owner.get(f"/clubs/{club_id}/config")
    assert "js-emoji-picker" in settings.text
    assert "Escolher emoji da tag" in settings.text or "emoji da tag" in settings.text.lower()
    owner.post("/amigos/pick_pal/convidar", data={"next": "/amigos"}, follow_redirects=False)
    other.post("/amigos/pick_own/aceitar", data={"next": "/amigos"}, follow_redirects=False)
    dm = owner.get("/mensagens/pick_pal")
    assert dm.status_code == 200
    assert "js-emoji-picker" in dm.text
    home = owner.get("/")
    assert "nav-icon-px" in home.text
    assert "wc-px" in home.text
    assert 'viewBox="0 0 32 32"' in home.text


def test_pixelmojis_pack_renders_and_stays_namespaced():
    picker = picker_catalog()
    packs = {pack["id"]: pack for pack in picker["packs"]}
    assert "pixelmojis" not in packs
    assert packs["emojis"]["count"] >= 1
    if not pack_available("pixelmojis"):
        html = str(render_tokens("oi :pixelmojis-1:"))
        assert ":pixelmojis-1:" in html
        return
    px = catalog_for("pixelmojis")
    assert px["count"] >= 1
    first = px["items"][0]
    assert first["token"].startswith(":pixelmojis-")
    assert first["src"].startswith("/static/emojis/pixelmojis/")
    assert "../" not in first["src"]
    assert sprite_exists(int(first["id"]), "pixelmojis")
    html = str(format_chat("oi " + first["token"]))
    assert "<img class=\"px-emoji\"" in html
    assert 'data-pack="pixelmojis"' in html
    assert first["src"] in html
    missing = str(render_tokens(":pixelmojis-99999:"))
    assert ":pixelmojis-99999:" in missing
    assert "<img" not in missing
    tokens = [item["token"] for item in picker["items"]]
    assert len(tokens) == len(set(tokens))
    assert any(item["pack"] == "pixelmojis" for item in picker["items"])
    joi_tokens = [item["token"] for item in picker["items"] if item["pack"] == "joi3"]
    assert joi_tokens


def test_picker_lists_pack_switcher_when_multiple_packs_exist():
    owner = TestClient(app)
    register_active(owner, "pxmoji_own", "pxmoji.own@example.com")
    created = owner.post(
        "/clubs",
        data={"name": "Pack Club", "description": "", "rules": "", "cover_color": "#3A2348"},
        follow_redirects=False,
    )
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    chat = owner.get(f"/clubs/{club_id}?aba=chat")
    assert "js-emoji-packs" in chat.text
    catalog = owner.get("/")
    assert ":joyquest-" in catalog.text
    assert ":social-" in catalog.text
    assert '"id": "reactions"' in catalog.text or '"id":"reactions"' in catalog.text
    assert '"id": "social"' in catalog.text or '"id":"social"' in catalog.text
    assert '"id": "emojis"' in catalog.text or '"id":"emojis"' in catalog.text
    picker = picker_catalog()
    labels = {pack["id"]: pack["label"] for pack in picker["packs"]}
    assert labels["emojis"] == "Emojis"
    assert labels["reactions"] == "Reações"
    assert labels["social"] == "Social"
    look = owner.get("/u/pxmoji_own?aba=aparencia")
    assert "look-swatch" in look.text
    assert "js-look-preview" in look.text
    assert look.text.count("data-theme-pick=") == 22


def test_joyquest_and_social_tokens_render_with_stable_namespaces():
    picker = picker_catalog()
    packs = {pack["id"]: pack for pack in picker["packs"]}
    assert packs["reactions"]["count"] >= 1
    assert packs["social"]["count"] >= 1
    assert packs["emojis"]["count"] >= 1
    jq = catalog_for("joyquest")["items"][0]
    so = catalog_for("social")["items"][0]
    assert jq["token"].startswith(":joyquest-")
    assert jq["src"].startswith("/static/emojis/joyquest/")
    assert so["token"].startswith(":social-")
    assert so["src"].startswith("/static/emojis/social/")
    mixed = str(format_chat(f"oi {jq['token']} {so['token']} :joi3-1:"))
    assert jq["src"] in mixed
    assert so["src"] in mixed
    assert mixed.count("<img class=\"px-emoji\"") >= 2
    missing = str(render_tokens(":joyquest-99999: :social-99999:"))
    assert ":joyquest-99999:" in missing
    assert ":social-99999:" in missing
    assert "<img" not in missing


def test_sticker_message_detects_emoji_only_bodies():
    assert is_sticker_message("😺") is True
    assert is_sticker_message("Oi 😺 tudo bem?") is False
    assert is_sticker_message(":joi3-1:") is True
    assert is_sticker_message("oi :joi3-1:") is False
    assert is_sticker_message(":joi3-1::pixelmojis-2:") is True
    assert is_sticker_message("") is False
    assert is_sticker_message("   ") is False
