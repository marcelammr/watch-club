from __future__ import annotations

import re
import secrets
from pathlib import Path

from fastapi import UploadFile

from app.config import BASE_DIR

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
UPLOAD_DIR = BASE_DIR / "app" / "static" / "uploads" / "clubs"
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
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(12)}{suffix}"
    (UPLOAD_DIR / name).write_bytes(data)
    return name


def cover_image_url(filename: str | None) -> str | None:
    if not filename:
        return None
    return f"/static/uploads/clubs/{filename}"
