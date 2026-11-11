from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from markupsafe import Markup, escape

# Historical JOI3 tokens stay valid forever: :joi3-N:
TOKEN_RE = re.compile(r":joi3-(\d+):")
# Packs use the same shape with a distinct slug: :pixelmojis-12:
PACK_TOKEN_RE = re.compile(r":([a-z][a-z0-9]{1,16})-(\d+):")
EMOJI_ID_RE = re.compile(r"(\d+)$")
EMOJI_ROOT = Path(__file__).resolve().parent / "static" / "emojis"

# Register packs here. Do not auto-import random folders.
# picker=True means the pack appears in the emoji window.
# Tokens stay namespaced (`:joi3-25:` vs `:pixelmojis-25:`). Messages keep the original token.
PACKS = {
    "joi3": {
        "id": "joi3",
        "label": "JOI3",
        "dir": EMOJI_ROOT / "joi3" / "32",
        "catalog": EMOJI_ROOT / "joi3" / "catalog.json",
        "src": "/static/emojis/joi3/32/Emojis_32x32_{id}.png",
        "file": "Emojis_32x32_{id}.png",
        "picker": True,
    },
    "pixelmojis": {
        "id": "pixelmojis",
        "label": "Pixelmojis",
        "dir": EMOJI_ROOT / "pixelmojis",
        "catalog": EMOJI_ROOT / "pixelmojis" / "catalog.json",
        "src": "/static/emojis/pixelmojis/pixelmojis{id}.png",
        "file": "pixelmojis{id}.png",
        "picker": True,
    },
}


def pack_spec(slug: str) -> dict | None:
    return PACKS.get((slug or "").strip().lower())


def item_for(emoji_id: int, slug: str = "joi3") -> dict:
    spec = pack_spec(slug)
    if spec is None:
        return {
            "id": emoji_id,
            "pack": slug,
            "token": f":{slug}-{emoji_id}:",
            "src": "",
        }
    return {
        "id": emoji_id,
        "pack": spec["id"],
        "token": f":{spec['id']}-{emoji_id}:",
        "src": spec["src"].format(id=int(emoji_id)),
    }


def sprite_path(emoji_id: int, slug: str = "joi3") -> Path | None:
    spec = pack_spec(slug)
    if spec is None:
        return None
    return spec["dir"] / spec["file"].format(id=int(emoji_id))


def sprite_exists(emoji_id: int, slug: str = "joi3") -> bool:
    path = sprite_path(emoji_id, slug)
    return bool(path and path.is_file())


def _scan_pack(spec: dict) -> list[dict]:
    items = []
    folder = spec["dir"]
    if not folder.is_dir():
        return items
    prefix, _, suffix = spec["file"].partition("{id}")
    for path in folder.glob(f"{prefix}*{suffix}"):
        match = EMOJI_ID_RE.search(path.stem)
        if not match:
            continue
        items.append(item_for(int(match.group(1)), spec["id"]))
    items.sort(key=lambda row: int(row["id"]))
    return items


@lru_cache(maxsize=8)
def catalog_for(slug: str = "joi3") -> dict:
    spec = pack_spec(slug)
    if spec is None:
        return {"pack": slug, "count": 0, "items": []}
    path = spec.get("catalog")
    if path and Path(path).is_file():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                items = []
                for raw in data["items"]:
                    if not isinstance(raw, dict):
                        continue
                    try:
                        emoji_id = int(raw.get("id"))
                    except (TypeError, ValueError):
                        continue
                    if not sprite_exists(emoji_id, spec["id"]):
                        continue
                    items.append(item_for(emoji_id, spec["id"]))
                return {"pack": spec["label"], "id": spec["id"], "count": len(items), "items": items}
        except json.JSONDecodeError:
            pass
    items = _scan_pack(spec)
    return {"pack": spec["label"], "id": spec["id"], "count": len(items), "items": items}


@lru_cache(maxsize=1)
def catalog() -> dict:
    """JOI3 catalog (legacy shape used by templates and tests)."""
    data = catalog_for("joi3")
    return {"pack": "JOI3", "count": data["count"], "items": data["items"]}


def _file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def picker_catalog() -> dict:
    """Picker payload. Exact binary duplicates across packs are listed once (JOI3 wins)."""
    packs = []
    items = []
    seen_hashes: set[str] = set()
    for slug, spec in PACKS.items():
        if not spec.get("picker", True):
            continue
        pack = catalog_for(slug)
        visible = []
        for raw in pack.get("items", []):
            try:
                emoji_id = int(raw["id"])
            except (KeyError, TypeError, ValueError):
                continue
            path = sprite_path(emoji_id, spec["id"])
            if not path or not path.is_file():
                continue
            digest = _file_hash(path)
            if digest and digest in seen_hashes:
                continue
            if digest:
                seen_hashes.add(digest)
            visible.append(item_for(emoji_id, spec["id"]))
        packs.append({"id": spec["id"], "label": spec["label"], "count": len(visible)})
        items.extend(visible)
    return {"pack": "JOI3", "packs": packs, "count": len(items), "items": items}


def available_ids(slug: str = "joi3") -> set[int]:
    return {int(item["id"]) for item in catalog_for(slug).get("items", [])}


def pack_available(slug: str = "joi3") -> bool:
    return bool(available_ids(slug))


def img_markup(emoji_id: int, extra_class: str = "", slug: str = "joi3") -> str:
    if pack_spec(slug) is None or not sprite_exists(emoji_id, slug):
        return escape(f":{slug}-{emoji_id}:")
    cls = "px-emoji" + (f" {extra_class}" if extra_class else "")
    src = escape(item_for(emoji_id, slug)["src"])
    return (
        f'<img class="{cls}" src="{src}" alt="" width="16" height="16" '
        f'data-pack="{escape(slug)}" data-joi3="{emoji_id}" draggable="false">'
    )


def render_tokens(text: str) -> Markup:
    if not text:
        return Markup("")
    return Markup(inject_into_escaped(str(escape(text))))


def inject_into_escaped(escaped: str) -> str:
    def replace(match: re.Match[str]) -> str:
        slug = match.group(1)
        emoji_id = int(match.group(2))
        if pack_spec(slug) is None:
            return match.group(0)
        return img_markup(emoji_id, slug=slug)

    return PACK_TOKEN_RE.sub(replace, escaped)


def split_units(value: str | None) -> list[str] | None:
    text = value or ""
    units: list[str] = []
    index = 0
    while index < len(text):
        match = PACK_TOKEN_RE.match(text, index)
        if match:
            units.append(match.group(0))
            index = match.end()
            continue
        return None
    return units
