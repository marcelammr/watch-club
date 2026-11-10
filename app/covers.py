from __future__ import annotations

import re
import secrets
from pathlib import Path

from fastapi import UploadFile

from app.config import uploads_dir

COVER_COLORS = [
    "#3A2348",
    "#2B6A8A",
    "#6B3F1D",
    "#7A3048",
    "#246B45",
    "#4D3A78",
    "#8A5A2B",
    "#1D1B33",
]
COVER_PRESETS = tuple({"hex": color, "label": color} for color in COVER_COLORS)
DEFAULT_COVER = COVER_COLORS[0]
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
STORED_NAME = re.compile(r"^[a-f0-9]{24}\.(jpg|jpeg|png|webp|gif)$")
def _upload_dir() -> Path:
    return uploads_dir() / "clubs"


def stored_cover_path(filename: str | None) -> Path | None:
    name = (filename or "").strip()
    if not STORED_NAME.match(name):
        return None
    dest = _upload_dir()
    path = (dest / name).resolve()
    if path.parent != dest.resolve() or not path.is_file():
        return None
    return path
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_BYTES = 2 * 1024 * 1024


def valid_cover_color(value: str | None) -> str:
    if value and HEX.fullmatch(value.strip()):
        return value.strip().upper()
    return DEFAULT_COVER


async def save_cover_image(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_EXT:
        return None
    data = await upload.read()
    if not data or len(data) > MAX_BYTES:
        return None
    dest = _upload_dir()
    dest.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(12)}{suffix}"
    (dest / name).write_bytes(data)
    return name


def cover_image_url(filename: str | None) -> str | None:
    if not filename:
        return None
    return f"/static/uploads/clubs/{filename}"
