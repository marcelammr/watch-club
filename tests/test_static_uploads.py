from fastapi.testclient import TestClient

from app.config import BASE_DIR, DEFAULT_UPLOADS_DIR, uploads_dir
from app.main import app, mount_static_files

client = TestClient(app)


def test_configured_uploads_outside_static_are_served(tmp_path, monkeypatch):
    persistent = tmp_path / "data" / "uploads"
    clubs = persistent / "clubs"
    clubs.mkdir(parents=True)
    payload = b"outside-static-cover"
    clubs.joinpath("8ae100d4efe5a63b80c55f39.jpg").write_bytes(payload)
    monkeypatch.setenv("WATCH_CLUB_UPLOADS_DIR", str(persistent))
    assert uploads_dir() == persistent
    assert BASE_DIR / "app" / "static" not in persistent.parents
    try:
        mount_static_files(app)
        served = client.get("/static/uploads/clubs/8ae100d4efe5a63b80c55f39.jpg")
        assert served.status_code == 200
        assert served.content == payload
        css = client.get("/static/style.css")
        assert css.status_code == 200
        assert "css" in (css.headers.get("content-type") or "").lower()
        fonts = client.get("/static/js/cover-crop.js")
        assert fonts.status_code == 200
    finally:
        monkeypatch.delenv("WATCH_CLUB_UPLOADS_DIR", raising=False)
        mount_static_files(app)


def test_default_uploads_dir_still_served_under_static_uploads(tmp_path):
    dest = DEFAULT_UPLOADS_DIR / "clubs"
    dest.mkdir(parents=True, exist_ok=True)
    name = "aaaaaaaaaaaaaaaaaaaaaa01.png"
    path = dest / name
    payload = b"default-dir-cover"
    path.write_bytes(payload)
    try:
        served = client.get(f"/static/uploads/clubs/{name}")
        assert served.status_code == 200
        assert served.content == payload
        css = client.get("/static/style.css")
        assert css.status_code == 200
    finally:
        path.unlink(missing_ok=True)


def test_uploads_mount_does_not_hide_regular_static_assets():
    css = client.get("/static/style.css")
    assert css.status_code == 200
    svg = client.get("/static/avatars/popcorn.svg")
    assert svg.status_code == 200
    missing = client.get("/static/uploads/clubs/does-not-exist.jpg")
    assert missing.status_code == 404
