from __future__ import annotations

from collections import defaultdict

from app.config import BASE_DIR


def _svg(bg: str, drawing: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img">
  <rect width="128" height="128" rx="36" fill="{bg}"/>
  {drawing}
</svg>
'''


def _eyes(cx: int, cy: int, r: int = 6) -> str:
    return (
        f'<circle cx="{cx - 12}" cy="{cy}" r="{r}" fill="#2b2235"/>'
        f'<circle cx="{cx + 12}" cy="{cy}" r="{r}" fill="#2b2235"/>'
        f'<circle cx="{cx - 10}" cy="{cy - 2}" r="2" fill="#fff"/>'
        f'<circle cx="{cx + 14}" cy="{cy - 2}" r="2" fill="#fff"/>'
    )


def _smile(cx: int, cy: int) -> str:
    return (
        f'<path d="M{cx - 10} {cy} Q{cx} {cy + 10} {cx + 10} {cy}" '
        'stroke="#2b2235" stroke-width="3" fill="none" stroke-linecap="round"/>'
    )


AVATARS = [
    {"id": "fox", "label": "Raposa", "category": "Animais", "svg": _svg("#f3b36a",
        '<polygon points="22,76 40,22 58,70" fill="#e07a3d"/><polygon points="70,70 88,22 106,76" fill="#e07a3d"/><circle cx="64" cy="78" r="34" fill="#ffd29a"/><circle cx="48" cy="92" r="7" fill="#ff9aa2"/><circle cx="80" cy="92" r="7" fill="#ff9aa2"/>' + _eyes(64, 74) + _smile(64, 90))},
    {"id": "cat", "label": "Gato", "category": "Animais", "svg": _svg("#d7c4ef",
        '<polygon points="26,70 40,20 58,62" fill="#6b5a86"/><polygon points="70,62 88,20 102,70" fill="#6b5a86"/><circle cx="64" cy="78" r="34" fill="#f4e9ff"/>' + _eyes(64, 74, 5) + _smile(64, 90) + '<path d="M38 82 L24 76 M38 88 L22 88 M38 94 L24 98" stroke="#2b2235" stroke-width="3" fill="none"/><path d="M90 82 L104 76 M90 88 L106 88 M90 94 L104 98" stroke="#2b2235" stroke-width="3" fill="none"/>')},
    {"id": "owl", "label": "Coruja", "category": "Animais", "svg": _svg("#8fbf7a",
        '<ellipse cx="64" cy="80" rx="36" ry="34" fill="#f4f0c8"/><circle cx="48" cy="70" r="16" fill="#fff"/><circle cx="80" cy="70" r="16" fill="#fff"/><circle cx="48" cy="70" r="7" fill="#2b2235"/><circle cx="80" cy="70" r="7" fill="#2b2235"/><circle cx="50" cy="68" r="2" fill="#fff"/><circle cx="82" cy="68" r="2" fill="#fff"/><polygon points="64,80 52,96 76,96" fill="#e8a44a"/>')},
    {"id": "panda", "label": "Panda", "category": "Animais", "svg": _svg("#eadfce",
        '<circle cx="36" cy="38" r="16" fill="#2b2235"/><circle cx="92" cy="38" r="16" fill="#2b2235"/><circle cx="64" cy="76" r="36" fill="#fff"/><ellipse cx="48" cy="72" rx="12" ry="14" fill="#2b2235"/><ellipse cx="80" cy="72" rx="12" ry="14" fill="#2b2235"/><circle cx="50" cy="72" r="5" fill="#fff"/><circle cx="82" cy="72" r="5" fill="#fff"/>' + _smile(64, 92))},
    {"id": "whale", "label": "Baleia", "category": "Animais", "svg": _svg("#7ec8e3",
        '<ellipse cx="60" cy="74" rx="42" ry="26" fill="#3d7ea6"/><circle cx="42" cy="70" r="6" fill="#fff"/><circle cx="42" cy="70" r="3" fill="#1c3147"/><circle cx="44" cy="68" r="1.5" fill="#fff"/><path d="M96 70 Q120 44 114 82 Q104 72 96 76" fill="#3d7ea6"/><path d="M48 82 Q58 90 70 82" stroke="#1c3147" stroke-width="3" fill="none" stroke-linecap="round"/><circle cx="78" cy="60" r="6" fill="#d6f1ff"/>')},
    {"id": "bunny", "label": "Coelho", "category": "Animais", "svg": _svg("#f7cfdc",
        '<ellipse cx="46" cy="34" rx="10" ry="28" fill="#fff"/><ellipse cx="82" cy="34" rx="10" ry="28" fill="#fff"/><ellipse cx="46" cy="36" rx="5" ry="18" fill="#f7a8bd"/><ellipse cx="82" cy="36" rx="5" ry="18" fill="#f7a8bd"/><circle cx="64" cy="80" r="32" fill="#fff"/><circle cx="50" cy="92" r="6" fill="#f7a8bd"/><circle cx="78" cy="92" r="6" fill="#f7a8bd"/>' + _eyes(64, 78, 5) + _smile(64, 94))},
    {"id": "cactus", "label": "Cacto", "category": "Plantas", "svg": _svg("#f3e0b0",
        '<rect x="54" y="36" width="20" height="64" rx="10" fill="#3fa66a"/><rect x="30" y="58" width="28" height="12" rx="6" fill="#3fa66a"/><rect x="70" y="50" width="28" height="12" rx="6" fill="#3fa66a"/><circle cx="64" cy="44" r="4" fill="#e85d75"/><circle cx="60" cy="68" r="3" fill="#2b2235"/><circle cx="68" cy="68" r="3" fill="#2b2235"/>' + _smile(64, 78))},
    {"id": "sunflower", "label": "Girassol", "category": "Plantas", "svg": _svg("#8ecf8a",
        '<circle cx="64" cy="64" r="22" fill="#f2c14e"/><circle cx="64" cy="64" r="12" fill="#6b3f1d"/><g fill="#f6d36b"><circle cx="64" cy="32" r="10"/><circle cx="64" cy="96" r="10"/><circle cx="32" cy="64" r="10"/><circle cx="96" cy="64" r="10"/><circle cx="40" cy="40" r="9"/><circle cx="88" cy="40" r="9"/><circle cx="40" cy="88" r="9"/><circle cx="88" cy="88" r="9"/></g>')},
    {"id": "mushroom", "label": "Cogumelo", "category": "Plantas", "svg": _svg("#f4d7c5",
        '<path d="M24 70 Q64 18 104 70 Z" fill="#e85d75"/><rect x="52" y="68" width="24" height="34" rx="10" fill="#f8efe6"/><circle cx="48" cy="52" r="7" fill="#fff"/><circle cx="72" cy="44" r="6" fill="#fff"/><circle cx="58" cy="82" r="3" fill="#2b2235"/><circle cx="70" cy="82" r="3" fill="#2b2235"/>')},
    {"id": "leaf", "label": "Folha", "category": "Plantas", "svg": _svg("#c5e8c2",
        '<path d="M28 96 Q36 28 96 24 Q92 92 28 96 Z" fill="#2f8f5b"/><path d="M40 88 Q64 56 88 36" stroke="#d7f5de" stroke-width="4" fill="none"/>')},
    {"id": "tulip", "label": "Tulipa", "category": "Plantas", "svg": _svg("#fde2ef",
        '<rect x="60" y="70" width="8" height="36" fill="#3fa66a"/><path d="M40 78 Q64 20 88 78 Q64 64 40 78 Z" fill="#e85d75"/><path d="M52 70 Q64 42 76 70" fill="#ff8fab"/>')},
    {"id": "sprout", "label": "Broto", "category": "Plantas", "svg": _svg("#e7f4c8",
        '<rect x="61" y="70" width="6" height="30" fill="#5aa35a"/><ellipse cx="46" cy="62" rx="18" ry="12" fill="#7fbf57"/><ellipse cx="82" cy="54" rx="18" ry="12" fill="#98d16b"/>')},
    {"id": "mountain", "label": "Montanha", "category": "Paisagens", "svg": _svg("#9fd4f0",
        '<circle cx="96" cy="36" r="14" fill="#ffe08a"/><polygon points="8,108 48,40 84,108" fill="#6b7c8a"/><polygon points="44,108 88,32 124,108" fill="#4d646f"/><polygon points="78,52 88,32 96,48" fill="#f7f3ea"/>')},
    {"id": "sunset", "label": "Pôr do sol", "category": "Paisagens", "svg": _svg("#f6b26b",
        '<circle cx="64" cy="58" r="22" fill="#ff6b4a"/><rect x="0" y="86" width="128" height="42" fill="#2b6a8a"/><path d="M0 86 Q32 70 64 86 Q96 102 128 86 L128 108 L0 108 Z" fill="#1f4e68"/>')},
    {"id": "moon", "label": "Lua", "category": "Paisagens", "svg": _svg("#2c2a4a",
        '<circle cx="72" cy="60" r="28" fill="#f3e3b8"/><circle cx="86" cy="50" r="22" fill="#2c2a4a"/><circle cx="28" cy="32" r="3" fill="#fff"/><circle cx="40" cy="92" r="2" fill="#fff"/><circle cx="104" cy="96" r="3" fill="#fff"/>')},
    {"id": "island", "label": "Ilha", "category": "Paisagens", "svg": _svg("#7ec8e3",
        '<ellipse cx="64" cy="92" rx="40" ry="14" fill="#e8d5a3"/><rect x="60" y="48" width="8" height="44" fill="#8a5a2b"/><path d="M64 28 Q92 48 64 52 Q36 48 64 28" fill="#3fa66a"/>')},
    {"id": "forest", "label": "Floresta", "category": "Paisagens", "svg": _svg("#b7e3c0",
        '<polygon points="24,100 44,40 64,100" fill="#2f8f5b"/><polygon points="48,100 76,28 104,100" fill="#246b45"/><rect x="70" y="88" width="10" height="18" fill="#6b3f1d"/>')},
    {"id": "stars", "label": "Céu estrelado", "category": "Paisagens", "svg": _svg("#1d1b33",
        '<polygon points="64,24 70,48 96,48 76,64 84,88 64,74 44,88 52,64 32,48 58,48" fill="#f2c14e"/><circle cx="24" cy="32" r="3" fill="#fff"/><circle cx="108" cy="40" r="2" fill="#fff"/><circle cx="96" cy="96" r="3" fill="#fff"/>')},
    {"id": "popcorn", "label": "Pipoca", "category": "Cinema", "svg": _svg("#f4c27a",
        '<path d="M36 56 L40 108 L88 108 L92 56 Z" fill="#e85d75"/><path d="M40 56 L44 108 L52 108 L50 56 Z" fill="#fff6ea"/><path d="M60 56 L62 108 L70 108 L70 56 Z" fill="#fff6ea"/><circle cx="46" cy="44" r="12" fill="#fff6ea"/><circle cx="64" cy="36" r="14" fill="#fff"/><circle cx="84" cy="46" r="12" fill="#fff6ea"/>')},
    {"id": "clapper", "label": "Claquete", "category": "Cinema", "svg": _svg("#d9d3c5",
        '<rect x="24" y="48" width="80" height="52" rx="6" fill="#2b2235"/><rect x="24" y="32" width="80" height="20" fill="#f4e9d8"/><rect x="28" y="32" width="14" height="20" fill="#2b2235"/><rect x="56" y="32" width="14" height="20" fill="#2b2235"/><rect x="84" y="32" width="14" height="20" fill="#2b2235"/>')},
    {"id": "ticket", "label": "Ingresso", "category": "Cinema", "svg": _svg("#f6c1d0",
        '<path d="M24 44 H92 A12 12 0 0 0 92 68 A12 12 0 0 0 92 92 H24 A12 12 0 0 0 24 68 A12 12 0 0 0 24 44 Z" fill="#fff6ea"/><circle cx="92" cy="68" r="8" fill="#f6c1d0"/><circle cx="24" cy="68" r="8" fill="#f6c1d0"/><rect x="40" y="56" width="36" height="8" rx="2" fill="#e85d75"/>')},
    {"id": "camera", "label": "Câmera", "category": "Cinema", "svg": _svg("#c9c2e8",
        '<rect x="22" y="44" width="84" height="52" rx="12" fill="#3a3358"/><circle cx="64" cy="70" r="18" fill="#d7c4ef"/><circle cx="64" cy="70" r="10" fill="#1b1728"/><rect x="78" y="36" width="18" height="12" rx="3" fill="#3a3358"/>')},
    {"id": "film", "label": "Rolo de filme", "category": "Cinema", "svg": _svg("#efd8b2",
        '<rect x="28" y="28" width="72" height="72" rx="8" fill="#2b2235"/><circle cx="48" cy="48" r="8" fill="#efd8b2"/><circle cx="80" cy="48" r="8" fill="#efd8b2"/><circle cx="48" cy="80" r="8" fill="#efd8b2"/><circle cx="80" cy="80" r="8" fill="#efd8b2"/><rect x="58" y="28" width="12" height="72" fill="#efd8b2"/>')},
    {"id": "star", "label": "Estrela de cinema", "category": "Cinema", "svg": _svg("#f0d48a",
        '<polygon points="64,20 74,50 106,50 80,70 90,102 64,82 38,102 48,70 22,50 54,50" fill="#fff6d8"/><circle cx="64" cy="64" r="10" fill="#e8a44a"/>')},
]

AVATAR_IDS = {item["id"] for item in AVATARS}
DEFAULT_AVATAR = "popcorn"
TYPE_ILLUSTRATED = "illustrated"
TYPE_UPLOAD = "upload"
PROVIDER_WATCHCLUB = "watchclub"
PROVIDER_TYGER = "tyger"
STATIC_AVATARS = BASE_DIR / "app" / "static" / "avatars"
UPLOAD_AVATARS = BASE_DIR / "app" / "static" / "uploads" / "avatars"
FALLBACK_URL = f"/static/avatars/{DEFAULT_AVATAR}.svg"

TYGER_AVATARS = [
    {"id": "TrAlex", "label": "Alex"},
    {"id": "TrCathy", "label": "Cathy"},
    {"id": "TrChad", "label": "Chad"},
    {"id": "TrChelsea", "label": "Chelsea"},
    {"id": "TrEnrique", "label": "Enrique"},
    {"id": "TrEric", "label": "Eric"},
    {"id": "TrFelix", "label": "Felix"},
    {"id": "TrFranklin", "label": "Franklin"},
    {"id": "TrHarry", "label": "Harry"},
    {"id": "TrHelen", "label": "Helen"},
    {"id": "TrIggy", "label": "Iggy"},
    {"id": "TrImran", "label": "Imran"},
    {"id": "TrMaria", "label": "Maria"},
    {"id": "TrNancy", "label": "Nancy"},
    {"id": "TrRachel", "label": "Rachel"},
    {"id": "TrSamantha", "label": "Samantha"},
    {"id": "TrShamila", "label": "Shamila"},
    {"id": "TrSophia", "label": "Sophia"},
    {"id": "TrStu", "label": "Stu"},
    {"id": "TrTorsten", "label": "Torsten"},
]
TYGER_IDS = {item["id"] for item in TYGER_AVATARS}

ILLUSTRATED_IDS = {
    PROVIDER_WATCHCLUB: AVATAR_IDS,
    PROVIDER_TYGER: TYGER_IDS,
}


def avatars_by_category() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in AVATARS:
        grouped[item["category"]].append(item)
    return grouped


def avatar_initials(name: str | None) -> str:
    parts = [part for part in (name or "").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def valid_avatar(avatar_id: str | None) -> str:
    if avatar_id in AVATAR_IDS:
        return avatar_id
    return DEFAULT_AVATAR


def _looks_like_url(value: str) -> bool:
    lowered = value.strip().lower()
    return "://" in lowered or lowered.startswith("/") or ".." in lowered or "\\" in value


def illustrated_url(provider: str | None, value: str | None) -> str | None:
    provider_id = (provider or "").strip().lower()
    avatar_id = (value or "").strip()
    if not provider_id or not avatar_id or _looks_like_url(avatar_id) or _looks_like_url(provider_id):
        return None
    allowed = ILLUSTRATED_IDS.get(provider_id)
    if not allowed or avatar_id not in allowed:
        return None
    if provider_id == PROVIDER_WATCHCLUB:
        path = STATIC_AVATARS / f"{avatar_id}.svg"
        url = f"/static/avatars/{avatar_id}.svg"
    elif provider_id == PROVIDER_TYGER:
        path = STATIC_AVATARS / "tyger" / f"{avatar_id}.svg"
        url = f"/static/avatars/tyger/{avatar_id}.svg"
    else:
        return None
    if not path.is_file():
        return None
    return url


def upload_url(filename: str | None) -> str | None:
    from app.avatar_uploads import stored_upload_path

    path = stored_upload_path(filename)
    if not path:
        return None
    return f"/static/uploads/avatars/{path.name}"


def avatar_url(person) -> str:
    kind = (getattr(person, "avatar_type", None) or TYPE_ILLUSTRATED).strip().lower()
    if kind == TYPE_UPLOAD:
        url = upload_url(getattr(person, "avatar_value", None))
        if url:
            return url
    provider = getattr(person, "avatar_provider", None) or PROVIDER_WATCHCLUB
    value = getattr(person, "avatar_value", None) or getattr(person, "avatar", None) or DEFAULT_AVATAR
    url = illustrated_url(provider, value)
    if url:
        return url
    legacy = getattr(person, "avatar", None)
    return illustrated_url(PROVIDER_WATCHCLUB, legacy) or FALLBACK_URL


def illustrated_catalogs() -> list[dict]:
    catalogs: list[dict] = []
    for category, icons in avatars_by_category().items():
        catalogs.append(
            {
                "provider": PROVIDER_WATCHCLUB,
                "heading": category,
                "icons": [
                    {"id": item["id"], "label": item["label"], "url": f"/static/avatars/{item['id']}.svg"}
                    for item in icons
                ],
            }
        )
    catalogs.append(
        {
            "provider": PROVIDER_TYGER,
            "heading": "Ilustrados",
            "icons": [
                {"id": item["id"], "label": item["label"], "url": f"/static/avatars/tyger/{item['id']}.svg"}
                for item in TYGER_AVATARS
            ],
        }
    )
    return catalogs


def parse_illustrated_choice(choice: str | None, provider: str | None = None, value: str | None = None) -> tuple[str, str] | None:
    raw = (choice or "").strip()
    if raw:
        if _looks_like_url(raw) or raw.count(":") != 1:
            return None
        provider_id, avatar_id = raw.split(":", 1)
    else:
        provider_id = (provider or "").strip()
        avatar_id = (value or "").strip()
    if illustrated_url(provider_id, avatar_id):
        return provider_id.strip().lower(), avatar_id.strip()
    return None


def set_illustrated_avatar(user, provider: str, value: str) -> bool:
    if not illustrated_url(provider, value):
        return False
    user.avatar_type = TYPE_ILLUSTRATED
    user.avatar_provider = provider
    user.avatar_value = value
    if provider == PROVIDER_WATCHCLUB:
        user.avatar = value
    return True


def set_upload_avatar(user, filename: str) -> None:
    user.avatar_type = TYPE_UPLOAD
    user.avatar_provider = ""
    user.avatar_value = filename
