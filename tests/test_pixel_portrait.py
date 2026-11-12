import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import inspect, select

from app.avatars import avatar_kind, avatar_url
from app.db import SessionLocal, engine
from app.main import app
from app.models import User

from app.pixel_portrait import (
    BODY,
    DEFAULTS,
    HEAD,
    LAYER_ICONS,
    LAYER_ORDER,
    LAYERS,
    OUTPUT_SIZE,
    PORTRAIT_DIR,
    SCALE,
    SIZE,
    THUMB_SIZE,
    catalog,
    compose_image,
    ensure_assets,
    parse_config,
    save_composed,
    thumb_image,
)
from tests.test_app import PNG_1X1, register_active


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        db.expunge(user)
        return user
    finally:
        db.close()


def test_portrait_schema_and_invalid_layers():
    cols = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "avatar_portrait" in cols
    assert parse_config({"base": "nope", "eyes": "dot"}) is None
    assert parse_config("<script>") is None
    assert parse_config(DEFAULTS)["hair"] == "short"


def test_legacy_upload_and_illustrated_keep_working_via_helper():
    fox = SimpleNamespace(
        avatar="fox",
        avatar_type="illustrated",
        avatar_provider="watchclub",
        avatar_value="fox",
        avatar_style="original",
        avatar_pixel=None,
        avatar_pixel_status="none",
        avatar_portrait=None,
    )
    assert avatar_kind(fox) == "illustrated"
    assert avatar_url(fox) == "/static/avatars/fox.svg"

    person = TestClient(app)
    register_active(person, "port_up", "port.up@example.com")
    photo = person.post(
        "/conta/avatar/foto",
        files={"photo": ("face.png", PNG_1X1, "image/png")},
        follow_redirects=False,
    )
    assert photo.status_code == 303
    stored = _user("port.up@example.com")
    assert stored.avatar_type == "upload"
    assert avatar_kind(stored) == "upload"
    assert "/static/uploads/avatars/" in avatar_url(stored)
    page = person.get("/conta")
    assert "/static/uploads/avatars/" in page.text
    assert 'data-kind="upload"' in page.text


def test_create_edit_and_switch_portrait_and_upload():
    owner = TestClient(app)
    other = TestClient(app)
    register_active(owner, "port_me", "port.me@example.com")
    register_active(other, "port_you", "port.you@example.com")

    created = owner.post(
        "/conta/avatar/personagem",
        data={"base": "tan", "face": "blush", "eyes": "wide", "hair": "bangs", "clothes": "hoodie", "acc": "glasses"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    first = _user("port.me@example.com")
    assert first.avatar_type == "pixel"
    config = json.loads(first.avatar_portrait)
    assert config["hair"] == "bangs"
    assert config["acc"] == "glasses"
    first_file = first.avatar_value
    assert avatar_url(first).endswith(first_file)
    account = owner.get("/conta")
    assert "Editar personagem" in account.text
    bangs = account.text.split('value="bangs"', 1)[1].split("</label>", 1)[0]
    assert "checked" in bangs
    assert 'data-kind="pixel"' in account.text
    profile = owner.get("/u/port_me")
    assert "/static/uploads/avatars/" in profile.text
    assert 'data-kind="pixel"' in profile.text

    edited = owner.post(
        "/conta/avatar/personagem",
        data={"base": "tan", "face": "blush", "eyes": "wide", "hair": "bun", "clothes": "hoodie", "acc": "glasses"},
        follow_redirects=False,
    )
    assert edited.status_code == 303
    second = _user("port.me@example.com")
    assert json.loads(second.avatar_portrait)["hair"] == "bun"
    assert second.avatar_value != first_file

    invalid = owner.post(
        "/conta/avatar/personagem",
        data={"base": "tan", "face": "blush", "eyes": "wide", "hair": "../etc", "clothes": "hoodie", "acc": "glasses"},
        follow_redirects=False,
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]
    still = _user("port.me@example.com")
    assert json.loads(still.avatar_portrait)["hair"] == "bun"

    hijack = other.post(
        "/conta/avatar/personagem",
        data={"base": "cool", "face": "none", "eyes": "dot", "hair": "short", "clothes": "tee", "acc": "none"},
        follow_redirects=False,
    )
    assert hijack.status_code == 303
    victim = _user("port.me@example.com")
    assert json.loads(victim.avatar_portrait)["hair"] == "bun"
    other_user = _user("port.you@example.com")
    assert other_user.avatar_type == "pixel"
    assert json.loads(other_user.avatar_portrait)["base"] == "cool"

    to_photo = owner.post(
        "/conta/avatar/foto",
        files={"photo": ("face.png", PNG_1X1, "image/png")},
        follow_redirects=False,
    )
    assert to_photo.status_code == 303
    uploaded = _user("port.me@example.com")
    assert uploaded.avatar_type == "upload"
    assert json.loads(uploaded.avatar_portrait)["hair"] == "bun"
    back = owner.post(
        "/conta/avatar/personagem",
        data={"base": "olive", "face": "sparkle", "eyes": "lash", "hair": "wavy", "clothes": "dress", "acc": "star"},
        follow_redirects=False,
    )
    assert back.status_code == 303
    restored = _user("port.me@example.com")
    assert restored.avatar_type == "pixel"
    assert json.loads(restored.avatar_portrait)["clothes"] == "dress"
    composed = compose_image(parse_config(restored.avatar_portrait))
    assert composed.size == (OUTPUT_SIZE, OUTPUT_SIZE)
    assert save_composed(DEFAULTS).endswith(".png")
    account = owner.get("/conta")
    assert "portrait-stage" in account.text
    assert "portrait-creator" in account.text
    assert "portrait-gallery" in account.text
    assert 'aria-label="Franja"' in account.text
    assert "/static/avatars/portrait/thumbs/hair/bun.png" in account.text
    css = owner.get("/static/style.css").text.replace(" ", "")
    assert "transform:scale(6)" in css
    assert ".portrait-gallery{overflow:auto" in css or "overflow:auto" in css
    home = owner.get("/")
    assert 'data-kind="pixel"' in home.text


def test_portrait_layers_share_canvas_and_leave_face_open():
    ensure_assets()
    assert LAYER_ORDER == ("base", "clothes", "face", "eyes", "hair", "acc")
    assert OUTPUT_SIZE == SIZE * SCALE
    assert (BODY[2] - BODY[0]) > (HEAD[2] - HEAD[0])
    for layer, _label, options in LAYERS:
        for option, _name in options:
            img = Image.open(PORTRAIT_DIR / layer / f"{option}.png")
            assert img.size == (SIZE, SIZE)
    hair = Image.open(PORTRAIT_DIR / "hair" / "short.png")
    eyes = Image.open(PORTRAIT_DIR / "eyes" / "dot.png")
    assert eyes.getpixel((13, 12))[3] > 0
    assert hair.getpixel((13, 12))[3] == 0
    composed = compose_image(DEFAULTS)
    assert composed.size == (OUTPUT_SIZE, OUTPUT_SIZE)
    assert composed.getpixel((13 * SCALE, 12 * SCALE))[3] > 0


def test_portrait_creator_uses_visual_gallery_and_contextual_thumbs():
    ensure_assets()
    assert set(LAYER_ICONS) == {key for key, _label, _options in LAYERS}
    groups = {group["id"]: group for group in catalog()}
    assert groups["hair"]["icon"] == "hair"
    bangs = next(option for option in groups["hair"]["options"] if option["id"] == "bangs")
    assert bangs["url"] == "/static/avatars/portrait/hair/bangs.png"
    assert bangs["thumb"] == "/static/avatars/portrait/thumbs/hair/bangs.png"
    layer = Image.open(PORTRAIT_DIR / "hair" / "bangs.png")
    thumb = Image.open(PORTRAIT_DIR / "thumbs" / "hair" / "bangs.png")
    assert layer.size == (SIZE, SIZE)
    assert thumb.size == (THUMB_SIZE, THUMB_SIZE)
    eyes_thumb = thumb_image("eyes", "dot")
    assert eyes_thumb.size == (THUMB_SIZE, THUMB_SIZE)
    assert eyes_thumb.getpixel((15 * (THUMB_SIZE // SIZE), 10 * (THUMB_SIZE // SIZE)))[3] > 0
    owner = TestClient(app)
    register_active(owner, "port_ui", "port.ui@example.com")
    owner.post(
        "/conta/avatar/personagem",
        data={"base": "tan", "face": "none", "eyes": "wide", "hair": "bangs", "clothes": "tee", "acc": "none"},
        follow_redirects=False,
    )
    page = owner.get("/conta")
    assert 'role="tablist"' in page.text
    assert 'data-cat="base"' in page.text
    assert 'data-cat="hair"' in page.text
    assert 'id="portrait-gallery-hair"' in page.text
    assert "hidden" in page.text.split('id="portrait-gallery-hair"', 1)[1][:160]
    assert "portrait-option" not in page.text
    assert 'aria-label="Clara"' in page.text
    assert 'aria-label="Franja"' in page.text
    bangs_html = page.text.split('value="bangs"', 1)[1].split("</label>", 1)[0]
    assert "checked" in bangs_html
    assert "/static/avatars/portrait/thumbs/hair/bangs.png" in bangs_html
    css = owner.get("/static/style.css").text.replace(" ", "")
    assert "portrait-gallery[hidden]" in css
    assert "minmax(72px,1fr)" in css or "minmax(72px, 1fr)" in css
