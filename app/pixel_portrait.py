from __future__ import annotations

import json
import secrets
from pathlib import Path

from PIL import Image

from app.config import BASE_DIR, uploads_dir

SIZE = 32
SCALE = 4
OUTPUT_SIZE = SIZE * SCALE
THUMB_SCALE = 2
THUMB_SIZE = SIZE * THUMB_SCALE
VERSION = 1
# Shared bust on a 32×32 grid (placeholders, not Pixel Portrait Creator).
# Head 12×12 at (10,7)–(21,18); neck (14,19)–(17,20); torso 16×11 at (8,21)–(23,31).
HEAD = (10, 7, 21, 18)
NECK = (14, 19, 17, 20)
BODY = (8, 21, 23, 31)
TYPE_PIXEL = "pixel"
PROVIDER_PORTRAIT = "portrait"
PORTRAIT_DIR = BASE_DIR / "app" / "static" / "avatars" / "portrait"

# Original Watch Club pixel layers (not extracted from Pixel Portrait Creator).
LAYERS = (
    (
        "base",
        "Base",
        (
            ("peach", "Clara"),
            ("tan", "Média"),
            ("brown", "Escura"),
            ("olive", "Oliva"),
            ("rose", "Rosa"),
            ("cool", "Fria"),
        ),
    ),
    (
        "face",
        "Rosto",
        (
            ("none", "Nenhum"),
            ("blush", "Blush"),
            ("freckles", "Sardas"),
            ("sparkle", "Brilho"),
        ),
    ),
    (
        "eyes",
        "Olhos",
        (
            ("dot", "Pontos"),
            ("wide", "Grandes"),
            ("sleepy", "Sonolentos"),
            ("lash", "Cílios"),
        ),
    ),
    (
        "hair",
        "Cabelo",
        (
            ("none", "Nenhum"),
            ("short", "Curto"),
            ("bangs", "Franja"),
            ("ponytail", "Rabo"),
            ("wavy", "Ondulado"),
            ("bun", "Coque"),
        ),
    ),
    (
        "clothes",
        "Roupa",
        (
            ("tee", "Camiseta"),
            ("hoodie", "Moletom"),
            ("vest", "Colete"),
            ("dress", "Vestido"),
            ("jacket", "Jaqueta"),
        ),
    ),
    (
        "acc",
        "Acessórios",
        (
            ("none", "Nenhum"),
            ("glasses", "Óculos"),
            ("bow", "Laço"),
            ("phones", "Fone"),
            ("star", "Estrela"),
        ),
    ),
)

LAYER_IDS = {key: {item[0] for item in options} for key, _label, options in LAYERS}
LAYER_ORDER = ("base", "clothes", "face", "eyes", "hair", "acc")
LAYER_ICONS = {
    "base": "user",
    "face": "sparkle",
    "eyes": "smile",
    "hair": "hair",
    "clothes": "image",
    "acc": "star",
}
# Neutral context for option thumbs. Swap only the category being shown.
THUMB_CONTEXT = {
    "base": "peach",
    "face": "none",
    "eyes": "dot",
    "hair": "none",
    "clothes": "tee",
    "acc": "none",
}
THUMB_LAYERS = {
    "base": ("base",),
    "face": ("base", "face"),
    "eyes": ("base", "eyes"),
    "hair": ("base", "eyes", "hair"),
    "clothes": ("base", "clothes"),
    "acc": ("base", "eyes", "acc"),
}
DEFAULTS = {
    "v": VERSION,
    "base": "peach",
    "face": "none",
    "eyes": "dot",
    "hair": "short",
    "clothes": "tee",
    "acc": "none",
}

SKINS = {
    "peach": (242, 201, 176, 255),
    "tan": (214, 162, 118, 255),
    "brown": (138, 90, 58, 255),
    "olive": (176, 148, 98, 255),
    "rose": (232, 168, 176, 255),
    "cool": (198, 186, 198, 255),
}
LINE = (43, 34, 53, 255)
WHITE = (255, 255, 255, 255)
HAIR = {
    "none": None,
    "short": (62, 42, 78, 255),
    "bangs": (46, 32, 64, 255),
    "ponytail": (118, 62, 42, 255),
    "wavy": (88, 48, 120, 255),
    "bun": (36, 28, 48, 255),
}
CLOTHES = {
    "tee": (184, 146, 255, 255),
    "hoodie": (108, 99, 255, 255),
    "vest": (61, 220, 132, 255),
    "dress": (255, 93, 143, 255),
    "jacket": (61, 148, 220, 255),
}


def _blank() -> Image.Image:
    return Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))


def _px(img: Image.Image, cells, color) -> None:
    put = img.putpixel
    for x, y in cells:
        if 0 <= x < SIZE and 0 <= y < SIZE:
            put((x, y), color)


def _rect(img: Image.Image, x0, y0, x1, y1, color) -> None:
    cells = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    _px(img, cells, color)


def _ellipse(img: Image.Image, cx, cy, rx, ry, color) -> None:
    cells = []
    for y in range(cy - ry, cy + ry + 1):
        for x in range(cx - rx, cx + rx + 1):
            if ((x - cx) / max(rx, 0.5)) ** 2 + ((y - cy) / max(ry, 0.5)) ** 2 <= 1.05:
                cells.append((x, y))
    _px(img, cells, color)


def _layer_path(layer: str, option: str) -> Path:
    return PORTRAIT_DIR / layer / f"{option}.png"


def _draw_base(option: str) -> Image.Image:
    img = _blank()
    skin = SKINS[option]
    shadow = tuple(max(0, c - 28) if i < 3 else 255 for i, c in enumerate(skin))
    hx0, hy0, hx1, hy1 = HEAD
    _rect(img, hx0, hy0, hx1, hy1, skin)
    _px(img, [(hx0, hy0), (hx1, hy0), (hx0, hy1), (hx1, hy1)], skin)
    nx0, ny0, nx1, ny1 = NECK
    _rect(img, nx0, ny0, nx1, ny1, skin)
    bx0, by0, bx1, by1 = BODY
    _rect(img, bx0, by0, bx1, by1, skin)
    _rect(img, bx0, by1 - 1, bx0 + 3, by1, shadow)
    _rect(img, bx1 - 3, by1 - 1, bx1, by1, shadow)
    return img


def _draw_face(option: str) -> Image.Image:
    img = _blank()
    if option == "none":
        return img
    if option == "blush":
        _px(img, [(12, 15), (13, 15), (18, 15), (19, 15)], (255, 140, 160, 220))
    elif option == "freckles":
        _px(img, [(12, 16), (14, 15), (17, 15), (19, 16)], (150, 86, 64, 255))
    elif option == "sparkle":
        _px(img, [(11, 8), (20, 9)], (255, 236, 140, 255))
    return img


def _draw_eyes(option: str) -> Image.Image:
    img = _blank()
    if option == "dot":
        _px(img, [(13, 12), (18, 12)], LINE)
        _px(img, [(13, 11), (18, 11)], WHITE)
    elif option == "wide":
        _rect(img, 12, 11, 14, 13, WHITE)
        _rect(img, 17, 11, 19, 13, WHITE)
        _px(img, [(13, 12), (18, 12)], LINE)
    elif option == "sleepy":
        _px(img, [(12, 12), (13, 12), (14, 12), (17, 12), (18, 12), (19, 12)], LINE)
    elif option == "lash":
        _px(img, [(13, 12), (18, 12)], LINE)
        _px(img, [(12, 11), (14, 11), (17, 11), (19, 11)], LINE)
        _px(img, [(13, 11), (18, 11)], WHITE)
    _px(img, [(14, 16), (15, 17), (16, 16), (17, 16)], LINE)
    return img


def _draw_hair(option: str) -> Image.Image:
    img = _blank()
    color = HAIR.get(option)
    if not color:
        return img
    _rect(img, 9, 5, 22, 8, color)
    _rect(img, 9, 7, 10, 14, color)
    _rect(img, 21, 7, 22, 14, color)
    if option == "bangs":
        _rect(img, 11, 8, 20, 10, color)
    if option == "ponytail":
        _rect(img, 22, 10, 25, 18, color)
        _rect(img, 23, 18, 25, 24, color)
    if option == "wavy":
        _rect(img, 7, 12, 9, 20, color)
        _rect(img, 22, 12, 24, 20, color)
    if option == "bun":
        _rect(img, 13, 3, 18, 6, color)
    if option == "short":
        _rect(img, 10, 5, 21, 7, color)
    return img


def _draw_clothes(option: str) -> Image.Image:
    img = _blank()
    color = CLOTHES[option]
    dark = tuple(max(0, c - 40) if i < 3 else 255 for i, c in enumerate(color))
    bx0, by0, bx1, by1 = BODY
    _rect(img, bx0, by0, bx1, by1, color)
    if option == "hoodie":
        _rect(img, bx0 - 1, by0, bx1 + 1, by0 + 2, color)
        _rect(img, 13, 20, 18, 22, dark)
    elif option == "vest":
        _rect(img, bx0, by0, bx0 + 2, by1, dark)
        _rect(img, bx1 - 2, by0, bx1, by1, dark)
    elif option == "dress":
        _rect(img, bx0 - 1, by0 + 3, bx1 + 1, by1, color)
    elif option == "jacket":
        _rect(img, bx0 - 1, by0, bx0 + 1, by1, dark)
        _rect(img, bx1 - 1, by0, bx1 + 1, by1, dark)
    _px(img, [(bx0, by0), (bx1, by0)], LINE)
    return img


def _draw_acc(option: str) -> Image.Image:
    img = _blank()
    if option == "none":
        return img
    if option == "glasses":
        _px(img, [(12, 12), (13, 12), (14, 12), (17, 12), (18, 12), (19, 12), (15, 12), (16, 12)], LINE)
    elif option == "bow":
        _px(img, [(14, 5), (15, 6), (16, 5), (17, 6), (18, 5)], (255, 93, 143, 255))
    elif option == "phones":
        _rect(img, 8, 10, 9, 15, (48, 40, 64, 255))
        _rect(img, 22, 10, 23, 15, (48, 40, 64, 255))
        _rect(img, 9, 8, 22, 9, (48, 40, 64, 255))
    elif option == "star":
        _px(img, [(9, 6), (8, 7), (9, 7), (10, 7), (9, 8)], (255, 214, 90, 255))
    return img


_DRAWERS = {
    "base": _draw_base,
    "face": _draw_face,
    "eyes": _draw_eyes,
    "hair": _draw_hair,
    "clothes": _draw_clothes,
    "acc": _draw_acc,
}


def ensure_assets() -> None:
    PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
    for layer, _label, options in LAYERS:
        folder = PORTRAIT_DIR / layer
        thumbs = PORTRAIT_DIR / "thumbs" / layer
        folder.mkdir(parents=True, exist_ok=True)
        thumbs.mkdir(parents=True, exist_ok=True)
        drawer = _DRAWERS[layer]
        for option, _name in options:
            drawer(option).save(folder / f"{option}.png", format="PNG")
    for layer, _label, options in LAYERS:
        thumbs = PORTRAIT_DIR / "thumbs" / layer
        for option, _name in options:
            thumb_image(layer, option).save(thumbs / f"{option}.png", format="PNG")


def layer_url(layer: str, option: str) -> str:
    return f"/static/avatars/portrait/{layer}/{option}.png"


def thumb_url(layer: str, option: str) -> str:
    return f"/static/avatars/portrait/thumbs/{layer}/{option}.png"


def catalog() -> list[dict]:
    ensure_assets()
    groups = []
    for key, label, options in LAYERS:
        groups.append(
            {
                "id": key,
                "label": label,
                "icon": LAYER_ICONS.get(key, "window"),
                "options": [
                    {
                        "id": option,
                        "label": name,
                        "url": layer_url(key, option),
                        "thumb": thumb_url(key, option),
                    }
                    for option, name in options
                ],
            }
        )
    return groups


def default_config() -> dict:
    return dict(DEFAULTS)


def parse_config(raw) -> dict | None:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    chosen = {"v": VERSION}
    for key in LAYER_ORDER:
        value = str(raw.get(key) or DEFAULTS[key]).strip().lower()
        if value not in LAYER_IDS[key]:
            return None
        chosen[key] = value
    return chosen


def config_from_user(user) -> dict:
    parsed = parse_config(getattr(user, "avatar_portrait", None))
    if parsed:
        return parsed
    return default_config()


def _fit_layer(part: Image.Image) -> Image.Image:
    """Keep the shared 32×32 origin. Never scale a layer by itself."""
    layer = _blank()
    src = part.convert("RGBA")
    cropped = src.crop((0, 0, min(src.size[0], SIZE), min(src.size[1], SIZE)))
    layer.paste(cropped, (0, 0))
    return layer


def _compose_layers(config: dict, layers: tuple[str, ...]) -> Image.Image:
    canvas = _blank()
    for layer in layers:
        path = _layer_path(layer, config[layer])
        canvas.alpha_composite(_fit_layer(Image.open(path)))
    return canvas


def compose_image(config: dict) -> Image.Image:
    ensure_assets()
    return _compose_layers(config, LAYER_ORDER).resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.NEAREST)


def thumb_image(layer: str, option: str) -> Image.Image:
    config = dict(THUMB_CONTEXT)
    config[layer] = option
    stack = THUMB_LAYERS.get(layer) or (layer,)
    return _compose_layers(config, stack).resize((THUMB_SIZE, THUMB_SIZE), Image.NEAREST)


def save_composed(config: dict) -> str:
    image = compose_image(config)
    filename = f"{secrets.token_hex(12)}.png"
    dest_dir = uploads_dir() / "avatars"
    dest_dir.mkdir(parents=True, exist_ok=True)
    image.save(dest_dir / filename, format="PNG")
    return filename


def preview_urls(config: dict) -> list[dict]:
    ensure_assets()
    return [{"layer": layer, "url": layer_url(layer, config[layer])} for layer in LAYER_ORDER]
