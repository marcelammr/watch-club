from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from markupsafe import Markup, escape

ICON_ROOT = Path(__file__).resolve().parent / "static" / "icons" / "pixel"
# Semantic name → local SVG. Missing files fall back to the drawn 16×16 family.
ICON_FILES = {
    "home": "home.svg",
    "calendar": "calendar.svg",
    "news": "news.svg",
    "clubs": "folder.svg",
    "folder": "folder.svg",
    "friends": "friends.svg",
    "messages": "messages.svg",
    "admin": "admin.svg",
    "settings": "settings.svg",
    "mailbox": "mailbox.svg",
    "shield": "shield.svg",
    "info": "info.svg",
    "search": "search.svg",
    "back": "back.svg",
    "palette": "palette.svg",
    "bell": "bell.svg",
    "envelope": "envelope.svg",
    "heart": "heart.svg",
    "star": "star.svg",
    "pencil": "pencil.svg",
    "trash": "trash.svg",
    "menu": "menu.svg",
    "tv": "tv.svg",
    "moon": "moon.svg",
    "sparkle": "sparkle.svg",
    "window": "window.svg",
    "clock": "clock.svg",
    "user": "user.svg",
    "image": "image.svg",
    "upload": "upload.svg",
    "save": "save.svg",
    "alert": "alert.svg",
    "smile": "smile.svg",
    "face": "smile.svg",
    "emoji": "smile.svg",
    "edit": "pencil.svg",
    "delete": "trash.svg",
    "bin": "bin.svg",
    "profile": "user.svg",
    "group": "group.svg",
    "check": "check.svg",
    "left": "arrow-left.svg",
    "right": "arrow-right.svg",
    "arrow-left": "arrow-left.svg",
    "arrow-right": "arrow-right.svg",
}

_FILL_RE = re.compile(r'fill="#(?:[0-9a-fA-F]{3,8})"', re.I)
_CLIP_RE = re.compile(r"clip\d+_\d+_\d+")
_SVG_OPEN_RE = re.compile(r"<svg\b([^>]*)>", re.I)


def icon_path(name: str) -> Path | None:
    filename = ICON_FILES.get((name or "").strip().lower())
    if not filename:
        return None
    path = ICON_ROOT / filename
    return path if path.is_file() else None


def mapped_icon_names() -> list[str]:
    return sorted({name for name, file in ICON_FILES.items() if (ICON_ROOT / file).is_file()})


@lru_cache(maxsize=64)
def _load_svg(name: str) -> str | None:
    path = icon_path(name)
    if path is None:
        return None
    raw = path.read_text(encoding="utf-8")
    raw = _CLIP_RE.sub(f"clip-{name}", raw)
    raw = _FILL_RE.sub('fill="currentColor"', raw)
    raw = raw.replace("fill='#000001'", 'fill="currentColor"')

    def inject(match: re.Match[str]) -> str:
        attrs = match.group(1)
        if "class=" not in attrs:
            attrs += ' class="wc-px"'
        elif "wc-px" not in attrs:
            attrs = attrs.replace('class="', 'class="wc-px ', 1)
        if 'width=' in attrs:
            attrs = re.sub(r'\swidth="[^"]*"', ' width="16"', attrs)
        else:
            attrs += ' width="16"'
        if 'height=' in attrs:
            attrs = re.sub(r'\sheight="[^"]*"', ' height="16"', attrs)
        else:
            attrs += ' height="16"'
        if "aria-hidden" not in attrs:
            attrs += ' aria-hidden="true"'
        if "focusable" not in attrs:
            attrs += ' focusable="false"'
        return f"<svg{attrs}>"

    return _SVG_OPEN_RE.sub(inject, raw, count=1)


def pixel_icon(name: str = "window") -> Markup:
    svg = _load_svg((name or "window").strip().lower())
    if svg:
        return Markup(svg)
    return Markup(_FALLBACK.get(name, _FALLBACK["window"]))


_FALLBACK = {
    "heart": '<svg class="wc-px" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><rect x="3" y="2" width="4" height="2"/><rect x="9" y="2" width="4" height="2"/><rect x="2" y="4" width="12" height="3"/><rect x="3" y="7" width="10" height="2"/><rect x="5" y="9" width="6" height="2"/><rect x="7" y="11" width="2" height="3"/></svg>',
    "plus": '<svg class="wc-px" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><rect x="7" y="2" width="2" height="12"/><rect x="2" y="7" width="12" height="2"/></svg>',
    "more": '<svg class="wc-px" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><rect x="2" y="6" width="3" height="3"/><rect x="7" y="6" width="3" height="3"/><rect x="12" y="6" width="3" height="3"/></svg>',
    "close": '<svg class="wc-px" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><rect x="3" y="3" width="3" height="2"/><rect x="10" y="3" width="3" height="2"/><rect x="5" y="5" width="2" height="2"/><rect x="9" y="5" width="2" height="2"/><rect x="7" y="7" width="2" height="2"/><rect x="5" y="9" width="2" height="2"/><rect x="9" y="9" width="2" height="2"/><rect x="3" y="11" width="3" height="2"/><rect x="10" y="11" width="3" height="2"/></svg>',
    "face": '<svg class="wc-px" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><rect x="5" y="1" width="6" height="2"/><rect x="3" y="3" width="10" height="2"/><rect x="2" y="5" width="12" height="6"/><rect x="4" y="11" width="8" height="2"/><rect x="5" y="13" width="6" height="1"/></svg>',
    "popcorn": '<svg class="wc-px" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><rect x="4" y="1" width="2" height="2"/><rect x="7" y="0" width="2" height="2"/><rect x="10" y="1" width="2" height="2"/><rect x="3" y="5" width="10" height="10"/></svg>',
    "flower": '<svg class="wc-px" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><rect x="7" y="1" width="2" height="3"/><rect x="2" y="6" width="3" height="3"/><rect x="11" y="6" width="3" height="3"/><rect x="7" y="11" width="2" height="3"/><rect x="6" y="5" width="4" height="5"/></svg>',
    "window": '<svg class="wc-px" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><rect x="1" y="3" width="14" height="11"/><rect x="1" y="3" width="14" height="3" fill="#fff" opacity=".45"/></svg>',
    "hair": '<svg class="wc-px" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><rect x="4" y="1" width="8" height="2"/><rect x="3" y="3" width="10" height="3"/><rect x="2" y="6" width="3" height="5"/><rect x="11" y="6" width="3" height="5"/></svg>',
}
