from __future__ import annotations

import re
import secrets
from pathlib import Path

from fastapi import UploadFile

from app.config import BASE_DIR

UPLOAD_DIR = BASE_DIR / "app" / "static" / "uploads" / "avatars"
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_MIME = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/octet-stream",
    "",
}
MAX_BYTES = 2 * 1024 * 1024
STORED_NAME = re.compile(r"^[a-f0-9]{24}\.(jpg|jpeg|png|webp|gif)$")


def stored_upload_path(filename: str | None) -> Path | None:
    name = (filename or "").strip()
    if not STORED_NAME.match(name):
        return None
    path = (UPLOAD_DIR / name).resolve()
    if path.parent != UPLOAD_DIR.resolve() or not path.is_file():
        return None
    return path


def _sniff_ext(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _is_svg(data: bytes, filename: str, content_type: str) -> bool:
    name = filename.lower()
    mime = (content_type or "").lower()
    head = data.lstrip()[:256].lower()
    return (
        name.endswith(".svg")
        or "svg" in mime
        or head.startswith(b"<svg")
        or head.startswith(b"<?xml")
        or b"<svg" in head[:120]
    )


def delete_upload(filename: str | None) -> None:
    path = stored_upload_path(filename)
    if path:
        path.unlink(missing_ok=True)


async def save_avatar_photo(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None
    suffix = Path(upload.filename).suffix.lower()
    mime = (upload.content_type or "").split(";")[0].strip().lower()
    if suffix == ".svg" or "svg" in mime:
        return None
    if suffix and suffix not in ALLOWED_EXT:
        return None
    if mime not in ALLOWED_MIME and mime not in {f"image/{ext.lstrip('.')}" for ext in ALLOWED_EXT}:
        return None
    data = await upload.read()
    if not data or len(data) > MAX_BYTES or _is_svg(data, upload.filename, mime):
        return None
    sniffed = _sniff_ext(data)
    if not sniffed:
        return None
    if suffix and suffix != sniffed and not (suffix in {".jpg", ".jpeg"} and sniffed == ".jpg"):
        if suffix != sniffed:
            return None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(12)}{sniffed}"
    (UPLOAD_DIR / name).write_bytes(data)
    return name
