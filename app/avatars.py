from __future__ import annotations

from collections import defaultdict


def _svg(bg: str, drawing: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img">
  <rect width="128" height="128" rx="36" fill="{bg}"/>
  {drawing}
</svg>
'''


AVATARS = [
    {"id": "fox", "label": "Raposa", "category": "Animais", "svg": _svg("#f3b36a",
        '<polygon points="24,78 40,28 56,78" fill="#e07a3d"/><polygon points="72,78 88,28 104,78" fill="#e07a3d"/><circle cx="64" cy="78" r="32" fill="#ffd29a"/><circle cx="54" cy="76" r="5" fill="#3a2418"/><circle cx="74" cy="76" r="5" fill="#3a2418"/><ellipse cx="64" cy="92" rx="10" ry="6" fill="#e07a3d"/>')},
    {"id": "cat", "label": "Gato", "category": "Animais", "svg": _svg("#d7c4ef",
        '<polygon points="28,70 40,26 58,62" fill="#6b5a86"/><polygon points="70,62 88,26 100,70" fill="#6b5a86"/><circle cx="64" cy="76" r="34" fill="#f4e9ff"/><circle cx="52" cy="74" r="5" fill="#2b2235"/><circle cx="76" cy="74" r="5" fill="#2b2235"/><path d="M40 82 L28 78 M40 86 L26 86 M40 90 L28 94" stroke="#2b2235" stroke-width="3" fill="none"/><path d="M88 82 L100 78 M88 86 L102 86 M88 90 L100 94" stroke="#2b2235" stroke-width="3" fill="none"/>')},
    {"id": "owl", "label": "Coruja", "category": "Animais", "svg": _svg("#8fbf7a",
        '<ellipse cx="64" cy="78" rx="36" ry="34" fill="#f4f0c8"/><circle cx="48" cy="70" r="16" fill="#fff"/><circle cx="80" cy="70" r="16" fill="#fff"/><circle cx="48" cy="70" r="7" fill="#2b2235"/><circle cx="80" cy="70" r="7" fill="#2b2235"/><polygon points="64,78 54,92 74,92" fill="#e8a44a"/>')},
    {"id": "panda", "label": "Panda", "category": "Animais", "svg": _svg("#eadfce",
        '<circle cx="36" cy="40" r="16" fill="#2b2235"/><circle cx="92" cy="40" r="16" fill="#2b2235"/><circle cx="64" cy="74" r="36" fill="#fff"/><ellipse cx="48" cy="72" rx="12" ry="14" fill="#2b2235"/><ellipse cx="80" cy="72" rx="12" ry="14" fill="#2b2235"/><circle cx="50" cy="72" r="5" fill="#fff"/><circle cx="82" cy="72" r="5" fill="#fff"/>')},
    {"id": "whale", "label": "Baleia", "category": "Animais", "svg": _svg("#7ec8e3",
        '<ellipse cx="60" cy="72" rx="40" ry="24" fill="#3d7ea6"/><circle cx="42" cy="68" r="5" fill="#fff"/><circle cx="42" cy="68" r="2" fill="#1c3147"/><path d="M96 68 Q118 48 112 78 Q104 70 96 74" fill="#3d7ea6"/><circle cx="78" cy="58" r="6" fill="#d6f1ff"/>')},
    {"id": "bunny", "label": "Coelho", "category": "Animais", "svg": _svg("#f7cfdc",
        '<ellipse cx="46" cy="36" rx="10" ry="28" fill="#fff"/><ellipse cx="82" cy="36" rx="10" ry="28" fill="#fff"/><ellipse cx="46" cy="38" rx="5" ry="18" fill="#f7a8bd"/><ellipse cx="82" cy="38" rx="5" ry="18" fill="#f7a8bd"/><circle cx="64" cy="80" r="30" fill="#fff"/><circle cx="54" cy="78" r="4" fill="#3a2418"/><circle cx="74" cy="78" r="4" fill="#3a2418"/><ellipse cx="64" cy="90" rx="6" ry="4" fill="#f7a8bd"/>')},
    {"id": "cactus", "label": "Cacto", "category": "Plantas", "svg": _svg("#f3e0b0",
        '<rect x="54" y="36" width="20" height="64" rx="10" fill="#3fa66a"/><rect x="30" y="58" width="28" height="12" rx="6" fill="#3fa66a"/><rect x="70" y="50" width="28" height="12" rx="6" fill="#3fa66a"/><circle cx="64" cy="44" r="4" fill="#e85d75"/>')},
    {"id": "sunflower", "label": "Girassol", "category": "Plantas", "svg": _svg("#8ecf8a",
        '<circle cx="64" cy="64" r="22" fill="#f2c14e"/><circle cx="64" cy="64" r="12" fill="#6b3f1d"/><g fill="#f6d36b"><circle cx="64" cy="32" r="10"/><circle cx="64" cy="96" r="10"/><circle cx="32" cy="64" r="10"/><circle cx="96" cy="64" r="10"/><circle cx="40" cy="40" r="9"/><circle cx="88" cy="40" r="9"/><circle cx="40" cy="88" r="9"/><circle cx="88" cy="88" r="9"/></g>')},
    {"id": "mushroom", "label": "Cogumelo", "category": "Plantas", "svg": _svg("#f4d7c5",
        '<path d="M24 70 Q64 18 104 70 Z" fill="#e85d75"/><rect x="52" y="68" width="24" height="34" rx="10" fill="#f8efe6"/><circle cx="48" cy="52" r="7" fill="#fff"/><circle cx="72" cy="44" r="6" fill="#fff"/>')},
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


def avatars_by_category() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in AVATARS:
        grouped[item["category"]].append(item)
    return grouped


def valid_avatar(avatar_id: str | None) -> str:
    if avatar_id in AVATAR_IDS:
        return avatar_id
    return DEFAULT_AVATAR
