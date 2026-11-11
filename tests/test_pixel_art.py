import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import inspect, select

from app.avatars import avatar_url
from app.covers import cover_image_url, cover_original_url, stored_cover_path
from app.club_icons import club_icon_original_url, club_icon_url, stored_icon_path
from app.db import SessionLocal, engine
from app.main import app
from app.models import Club, ClubMember, User
from app.pixel_art import (
    PRESETS,
    PixelArtError,
    PixelArtProvider,
    STYLE_CGA,
    STYLE_FAITHFUL,
    STYLE_GAMEBOY,
    STYLE_ORIGINAL,
    STYLE_PICO8,
    STYLE_1BIT,
    generate_derivative,
    get_provider,
    normalize_style,
    preview_bytes,
    render_preset,
    require_style,
)
from tests.test_app import PNG_1X1, TINY_PNG, register_active


def _png(size=48) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", (size, size), (210, 90, 130))
    image.putpixel((2, 2), (40, 90, 200))
    image.putpixel((20, 18), (250, 220, 80))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _png_file(name="face.png"):
    return {"photo": (name, _png(), "image/png")}


def test_style_helpers_and_local_render(tmp_path):
    assert normalize_style(None) == "original"
    assert normalize_style("pixel") == "faithful"
    assert require_style("pico8") == "pico8"
    try:
        require_style("oil-paint")
    except PixelArtError:
        pass
    else:
        raise AssertionError("expected invalid style")
    source = tmp_path / "in.png"
    source.write_bytes(_png())
    data = get_provider().generate(source)
    assert data.startswith(b"\x89PNG")
    dest = tmp_path / "out.png"
    generate_derivative(source, dest, preset=STYLE_FAITHFUL)
    assert dest.is_file()
    assert dest.read_bytes() != source.read_bytes()


def test_generate_derivative_never_writes_without_bytes(tmp_path):
    class EmptyProvider(PixelArtProvider):
        def generate(self, source: Path) -> bytes:
            return b""

    source = tmp_path / "in.png"
    source.write_bytes(_png())
    dest = tmp_path / "out.png"
    try:
        generate_derivative(source, dest, provider=EmptyProvider())
    except PixelArtError:
        assert not dest.exists()
    else:
        raise AssertionError("empty output must fail")


def test_presets_emit_valid_png_and_keep_source(tmp_path):
    source = tmp_path / "photo.png"
    original = _png(64)
    source.write_bytes(original)
    for preset in (STYLE_FAITHFUL, STYLE_PICO8, STYLE_GAMEBOY, STYLE_1BIT, STYLE_CGA):
        dest = tmp_path / f"{preset}.png"
        generate_derivative(source, dest, preset=preset)
        assert dest.is_file()
        assert dest.read_bytes().startswith(b"\x89PNG")
        Image.open(dest).verify()
        assert source.read_bytes() == original
    try:
        generate_derivative(source, tmp_path / "bad.png", preset="glitch")
    except PixelArtError:
        pass
    else:
        raise AssertionError("invalid preset must fail")
    try:
        render_preset(b"not-an-image", STYLE_FAITHFUL)
    except PixelArtError:
        pass
    else:
        raise AssertionError("invalid file must fail")


def test_preview_does_not_write_and_get_does_not_generate(tmp_path, monkeypatch):
    person = TestClient(app)
    register_active(person, "px_prev", "px.prev@example.com")
    uploads = Path("app/static/uploads/avatars")
    before = {path.name for path in uploads.glob("*")} if uploads.exists() else set()
    preview = person.post(
        "/imagens/previsualizar",
        data={"preset": "pico8"},
        files=_png_file(),
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")
    after = {path.name for path in uploads.glob("*")} if uploads.exists() else set()
    assert after == before
    missing = person.get("/imagens/previsualizar")
    assert missing.status_code == 405
    bad = person.post(
        "/imagens/previsualizar",
        data={"preset": "oil"},
        files=_png_file(),
    )
    assert bad.status_code == 400
    guest = TestClient(app)
    stolen = guest.post(
        "/imagens/previsualizar",
        data={"preset": "pico8"},
        files=_png_file(),
        follow_redirects=False,
    )
    assert stolen.status_code in (303, 401)

    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("generation must not run on GET")

    monkeypatch.setattr("app.main.generate_derivative", boom)
    assert person.get("/").status_code == 200
    assert person.get("/conta").status_code == 200
    assert person.get("/u/px_prev").status_code == 200
    assert calls["n"] == 0


def test_avatar_style_persists_and_keeps_original():
    person = TestClient(app)
    register_active(person, "px_own", "px.own@example.com")
    account = person.get("/conta")
    assert "Estilo da imagem" in account.text
    assert "Original" in account.text
    assert "Faithful" in account.text
    assert "PICO-8" in account.text
    assert "/static/js/image-style.js" in account.text
    bad = person.post("/conta/avatar/estilo", data={"style": "glitch"}, follow_redirects=False)
    assert bad.status_code == 303
    assert "error=" in bad.headers["location"]
    photo = person.post("/conta/avatar/foto", files=_png_file(), data={"preset": "pico8"}, follow_redirects=False)
    assert photo.status_code == 303
    db = SessionLocal()
    try:
        host = db.query(User).filter(User.username == "px_own").one()
        original = host.avatar_value
        pixel = host.avatar_pixel
        assert host.avatar_style == "pico8"
        assert host.avatar_pixel_status == "ready"
        assert original
        assert pixel
        assert original != pixel
        original_bytes = Path("app/static/uploads/avatars", original).read_bytes()
        pixel_bytes = Path("app/static/uploads/avatars", pixel).read_bytes()
        assert original_bytes.startswith(b"\x89PNG")
        assert pixel_bytes.startswith(b"\x89PNG")
        assert original_bytes != pixel_bytes
        assert avatar_url(host).endswith(pixel)
    finally:
        db.close()
    switched = person.post("/conta/avatar/estilo", data={"style": "gameboy"}, follow_redirects=False)
    assert switched.status_code == 303
    db = SessionLocal()
    try:
        host = db.query(User).filter(User.username == "px_own").one()
        assert host.avatar_value == original
        assert host.avatar_style == "gameboy"
        assert host.avatar_pixel != pixel
        assert Path("app/static/uploads/avatars", original).is_file()
    finally:
        db.close()
    restored = person.post("/conta/avatar/estilo", data={"style": "original"}, follow_redirects=False)
    assert restored.status_code == 303
    db = SessionLocal()
    try:
        host = db.query(User).filter(User.username == "px_own").one()
        assert host.avatar_style == "original"
        assert host.avatar_pixel is None
        assert Path("app/static/uploads/avatars", original).is_file()
        assert avatar_url(host).endswith(original)
        host.avatar_style = "pico8"
        host.avatar_pixel = "missing.png"
        host.avatar_pixel_status = "ready"
        assert avatar_url(host).endswith(original)
    finally:
        db.close()
    guest = TestClient(app)
    register_active(guest, "px_guest", "px.guest@example.com")
    stolen = guest.post("/conta/avatar/foto", files=_png_file(), data={"preset": "cga"}, follow_redirects=False)
    assert stolen.status_code == 303
    db = SessionLocal()
    try:
        host = db.query(User).filter(User.username == "px_own").one()
        guest_row = db.query(User).filter(User.username == "px_guest").one()
        assert host.avatar_style == "original"
        assert guest_row.avatar_style == "cga"
        assert guest_row.id != host.id
        host.is_site_admin = True
        db.commit()
    finally:
        db.close()
    admin = person.get("/admin/cadastros", follow_redirects=False)
    assert admin.status_code == 303
    assert admin.headers["location"] == "/admin/sugestoes"
    home2 = person.get("/")
    assert "Meus Clubes" in home2.text
    assert 'href="/clubes"' in home2.text
    assert "wc-win-min" not in home2.text


def test_failed_processing_keeps_original(monkeypatch):
    person = TestClient(app)
    register_active(person, "px_fail", "px.fail@example.com")
    person.post("/conta/avatar/foto", files=_png_file(), data={"preset": "original"}, follow_redirects=False)

    def boom(*_args, **_kwargs):
        raise PixelArtError("falhou")

    monkeypatch.setattr("app.main.generate_derivative", boom)
    failed = person.post("/conta/avatar/estilo", data={"style": "pico8"}, follow_redirects=False)
    assert failed.status_code == 303
    assert "error=" in failed.headers["location"]
    db = SessionLocal()
    try:
        host = db.query(User).filter(User.username == "px_fail").one()
        assert host.avatar_style == "original"
        assert Path("app/static/uploads/avatars", host.avatar_value).is_file()
    finally:
        db.close()


def test_club_cover_and_icon_presets_respect_permissions():
    owner = TestClient(app)
    register_active(owner, "px_club", "px.club@example.com")
    created = owner.post(
        "/clubs",
        data={"name": "Pixel Clube", "description": "", "rules": "", "cover_color": "#3A2348", "cover_preset": "cga", "icon_preset": "gameboy"},
        files={
            "cover_file": ("cover.png", _png(64), "image/png"),
            "icon_file": ("icon.png", _png(48), "image/png"),
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.cover_style == "cga"
        assert club.icon_style == "gameboy"
        assert club.cover_image != club.cover_pixel
        assert club.icon_image != club.icon_pixel
        assert stored_cover_path(club.cover_image)
        assert stored_cover_path(club.cover_pixel)
        assert stored_icon_path(club.icon_image)
        assert stored_icon_path(club.icon_pixel)
        assert cover_image_url(club).endswith(club.cover_pixel)
        assert club_icon_url(club).endswith(club.icon_pixel)
        assert cover_original_url(club).endswith(club.cover_image)
        assert club_icon_original_url(club).endswith(club.icon_image)
        original_cover = club.cover_image
        original_icon = club.icon_image
        cover_pixel = club.cover_pixel
        icon_pixel = club.icon_pixel
    finally:
        db.close()
    member = TestClient(app)
    register_active(member, "px_mem", "px.mem@example.com")
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        user = db.scalar(select(User).where(User.username == "px_mem"))
        db.add(ClubMember(club_id=club.id, user_id=user.id, role="member", support_perms=""))
        db.commit()
    finally:
        db.close()
    blocked = member.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Pixel Clube",
            "description": "",
            "rules": "",
            "cover_color": "#3A2348",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "cover_preset": "pico8",
        },
        files={"cover_file": ("cover.png", _png(64), "image/png")},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.cover_image == original_cover
        assert club.cover_style == "cga"
    finally:
        db.close()
    config = owner.get(f"/clubs/{club_id}/config")
    assert config.status_code == 200
    assert f'data-original-url="/static/uploads/club-icons/{original_icon}"' in config.text
    assert f'data-original-url="/static/uploads/clubs/{original_cover}"' in config.text
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.icon_image == original_icon
        assert club.cover_image == original_cover
        assert club.icon_pixel == icon_pixel
        assert club.cover_pixel == cover_pixel
        assert club.icon_style == "gameboy"
        assert club.cover_style == "cga"
    finally:
        db.close()


def test_club_config_exposes_image_studio_for_icon_and_cover():
    owner = TestClient(app)
    register_active(owner, "px_studio", "px.studio@example.com")
    created = owner.post(
        "/clubs",
        data={"name": "Estúdio Clube", "description": "", "rules": "", "cover_color": "#3A2348"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    page = owner.get(f"/clubs/{club_id}/config")
    assert page.status_code == 200
    assert "Estúdio do ícone" in page.text
    assert "Estúdio da capa" in page.text
    assert "js-icon-file-pick" in page.text
    assert "js-cover-file-pick" in page.text
    assert 'name="icon_file"' in page.text
    assert 'name="cover_file"' in page.text
    for label in ("Original", "Faithful", "PICO-8", "Game Boy", "1-bit", "CGA"):
        assert label in page.text
    assert "Estilo do ícone" in page.text
    assert "Estilo da capa" in page.text
    assert page.text.count("js-style-choice") >= 12
    account = owner.get("/conta")
    assert account.status_code == 200
    assert 'name="displayed_club_id"' in account.text
    assert "Nenhuma" in account.text
    clubes = owner.get("/clubes")
    assert "Pesquisar" in clubes.text
    assert "Entrar com código" in clubes.text
    assert 'href="/noticias"' in clubes.text


def test_pixel_art_schema_and_gets_never_generate():
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "theme_key" in columns
    assert "wallpaper_key" in columns
    assert "avatar_style" in columns
    assert "avatar_pixel" in columns
    assert "avatar_pixel_status" in columns
    club_cols = {column["name"] for column in inspect(engine).get_columns("clubs")}
    assert "cover_style" in club_cols
    assert "cover_pixel" in club_cols
    assert "icon_style" in club_cols
    assert "icon_pixel" in club_cols
    assert set(PRESETS) == {"original", "faithful", "pico8", "gameboy", "1bit", "cga"}
    preview = preview_bytes(TINY_PNG, STYLE_ORIGINAL)
    assert preview.startswith(b"\x89PNG")
    assert PNG_1X1.startswith(b"\x89PNG")
