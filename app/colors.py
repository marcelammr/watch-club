from __future__ import annotations

import re

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
DEFAULT_HEX = "#B892FF"
COLOR_MODES = ("solid", "gradient")
COLOR_MODE_DEFAULT = "solid"
GRADIENT_DIRECTIONS = ("right", "down-right", "down", "up-right")
GRADIENT_ANGLES = {
    "right": "90deg",
    "down-right": "135deg",
    "down": "180deg",
    "up-right": "45deg",
}
COLOR_PRESETS = (
    {"token": "lavender", "hex": "#B892FF", "label": "Lavanda"},
    {"token": "violet", "hex": "#6C63FF", "label": "Violeta"},
    {"token": "pink", "hex": "#FF5D8F", "label": "Rosa"},
    {"token": "blue", "hex": "#6EA8FF", "label": "Azul"},
    {"token": "green", "hex": "#3DDC84", "label": "Verde"},
    {"token": "orange", "hex": "#FF9F5B", "label": "Laranja"},
    {"token": "cream", "hex": "#F7F0FF", "label": "Creme"},
    {"token": "night", "hex": "#C4B8D9", "label": "Noite"},
)
TOKEN_TO_HEX = {item["token"]: item["hex"] for item in COLOR_PRESETS}


def valid_hex(value: str | None) -> str | None:
    text = (value or "").strip()
    if HEX_RE.fullmatch(text):
        return text.upper()
    return None


def hex_from_legacy_token(value: str | None) -> str:
    token = (value or "").strip().lower()
    return TOKEN_TO_HEX.get(token, DEFAULT_HEX)


def valid_color_mode(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if text in COLOR_MODES:
        return text
    return None


def valid_gradient_direction(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if text in GRADIENT_DIRECTIONS:
        return text
    return None


def parse_surface_colors(
    mode_value: str | None,
    color_1: str | None,
    color_2: str | None,
    direction: str | None,
) -> tuple[dict | None, str | None]:
    mode = valid_color_mode(mode_value)
    if not mode:
        return None, "Escolha se a cor é sólida ou em degradê."
    first = valid_hex(color_1)
    if not first:
        return None, "Escolha uma cor válida."
    if mode == "solid":
        return {
            "mode": "solid",
            "color_1": first,
            "color_2": None,
            "direction": None,
            "angle": GRADIENT_ANGLES["right"],
        }, None
    second = valid_hex(color_2)
    if not second:
        return None, "Escolha as duas cores do degradê."
    chosen_dir = valid_gradient_direction(direction)
    if not chosen_dir:
        return None, "Escolha a direção do degradê."
    return {
        "mode": "gradient",
        "color_1": first,
        "color_2": second,
        "direction": chosen_dir,
        "angle": GRADIENT_ANGLES[chosen_dir],
    }, None


def tag_surface_style(
    color_1: str,
    color_2: str | None,
    angle: str | None,
    bg_intensity: int,
    border_intensity: int,
) -> str:
    first = valid_hex(color_1) or DEFAULT_HEX
    second = valid_hex(color_2) or first
    chosen_angle = angle if angle in GRADIENT_ANGLES.values() else GRADIENT_ANGLES["right"]
    return (
        f"--tag-c1: {first}; --tag-c2: {second}; --tag-angle: {chosen_angle}; "
        f"--tag-bg-intensity: {bg_intensity}; --tag-border-intensity: {border_intensity};"
    )


def tag_surface_class(mode: str | None) -> str:
    return "is-gradient" if mode == "gradient" else ""
