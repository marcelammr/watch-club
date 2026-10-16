from __future__ import annotations

import re

import emoji
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.colors import (
    COLOR_MODE_DEFAULT,
    DEFAULT_HEX,
    parse_surface_colors,
    tag_surface_class,
    tag_surface_style,
    valid_hex,
)
from app.models import Club, ClubMember, User

TAG_SLUG_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")
TAG_POSITIONS = ("start", "end", "split")
TAG_POSITION_DEFAULT = "start"
TAG_BG_MIN = 10
TAG_BG_MAX = 35
TAG_BG_DEFAULT = 18
TAG_BORDER_MIN = 30
TAG_BORDER_MAX = 90
TAG_BORDER_DEFAULT = 55
TAG_EMOJI_MAX = 2
_UNSAFE = set("<>&\"'`")


def valid_tag_slug(value: str | None) -> str:
    text = (value or "").strip().upper()
    if TAG_SLUG_RE.match(text):
        return text
    return ""


def parse_tag_emojis(value: str | None) -> list[str] | None:
    text = (value or "").strip()
    if not text:
        return []
    if any(char in _UNSAFE or ord(char) < 32 for char in text):
        return None
    if not emoji.purely_emoji(text):
        return None
    items = emoji.emoji_list(text)
    count = emoji.emoji_count(text)
    if count != len(items) or count < 1 or count > TAG_EMOJI_MAX:
        return None
    if items[0]["match_start"] != 0 or items[-1]["match_end"] != len(text):
        return None
    for current, nxt in zip(items, items[1:]):
        if current["match_end"] != nxt["match_start"]:
            return None
    parsed = [item["emoji"] for item in items]
    if not all(emoji.is_emoji(item) for item in parsed):
        return None
    return parsed


def valid_tag_emoji(value: str | None) -> str:
    parsed = parse_tag_emojis(value)
    if not parsed:
        return ""
    return "".join(parsed)


def valid_tag_position(value: str | None, emoji_count: int) -> str | None:
    text = (value or "").strip().lower() or TAG_POSITION_DEFAULT
    if text not in TAG_POSITIONS:
        return None
    if text == "split" and emoji_count < 2:
        return TAG_POSITION_DEFAULT
    return text


def tag_display_parts(emojis: list[str] | None, slug: str | None, position: str | None) -> dict:
    items = emojis or []
    text = slug or ""
    chosen = valid_tag_position(position, len(items)) or TAG_POSITION_DEFAULT
    if chosen == "end":
        return {"prefix": "", "slug": text, "suffix": "".join(items)}
    if chosen == "split" and len(items) >= 2:
        return {"prefix": items[0], "slug": text, "suffix": items[1]}
    return {"prefix": "".join(items), "slug": text, "suffix": ""}


def parse_intensity(value: str | int | None, minimum: int, maximum: int, default: int) -> int | None:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < minimum or number > maximum:
        return None
    return number


def club_has_tag(club: Club | None) -> bool:
    if not club:
        return False
    return bool(
        club.tag_slug
        and parse_tag_emojis(club.tag_emoji)
        and valid_hex(club.tag_color_1)
    )


def tag_payload(club: Club | None) -> dict | None:
    if not club_has_tag(club):
        return None
    emojis = parse_tag_emojis(club.tag_emoji) or []
    bg = club.tag_bg_intensity if club.tag_bg_intensity is not None else TAG_BG_DEFAULT
    border = club.tag_border_intensity if club.tag_border_intensity is not None else TAG_BORDER_DEFAULT
    position = valid_tag_position(club.tag_emoji_position, len(emojis)) or TAG_POSITION_DEFAULT
    mode = club.tag_color_mode or COLOR_MODE_DEFAULT
    color_1 = valid_hex(club.tag_color_1) or DEFAULT_HEX
    if mode == "gradient":
        surface, error = parse_surface_colors(
            "gradient",
            color_1,
            club.tag_color_2,
            club.tag_gradient_direction,
        )
        if error:
            surface, _error = parse_surface_colors("solid", color_1, None, None)
    else:
        surface, _error = parse_surface_colors("solid", color_1, None, None)
    chosen = surface or {
        "mode": "solid",
        "color_1": color_1,
        "color_2": None,
        "direction": None,
        "angle": "90deg",
    }
    return {
        "slug": club.tag_slug,
        "emoji": "".join(emojis),
        "emojis": emojis,
        "color_mode": chosen["mode"],
        "color_1": chosen["color_1"],
        "color_2": chosen["color_2"],
        "gradient_direction": chosen["direction"],
        "angle": chosen["angle"],
        "surface_class": tag_surface_class(chosen["mode"]),
        "surface_style": tag_surface_style(
            chosen["color_1"],
            chosen["color_2"],
            chosen["angle"],
            bg,
            border,
        ),
        "bg_intensity": bg,
        "border_intensity": border,
        "position": position,
        "parts": tag_display_parts(emojis, club.tag_slug, position),
    }


def apply_club_tag(
    club: Club,
    slug: str | None,
    emoji_value: str | None,
    bg_intensity: str | int | None = None,
    border_intensity: str | int | None = None,
    emoji_position: str | None = None,
    color_mode: str | None = COLOR_MODE_DEFAULT,
    color_1: str | None = DEFAULT_HEX,
    color_2: str | None = None,
    gradient_direction: str | None = None,
) -> str | None:
    cleaned_slug = valid_tag_slug(slug)
    parsed_emojis = parse_tag_emojis(emoji_value)
    if parsed_emojis is None:
        return "Escolha 1 ou 2 emojis válidos para a tag."
    if not cleaned_slug and not parsed_emojis:
        club.tag_slug = ""
        club.tag_emoji = ""
        club.tag_color_mode = COLOR_MODE_DEFAULT
        club.tag_color_1 = DEFAULT_HEX
        club.tag_color_2 = None
        club.tag_gradient_direction = None
        club.tag_bg_intensity = TAG_BG_DEFAULT
        club.tag_border_intensity = TAG_BORDER_DEFAULT
        club.tag_emoji_position = TAG_POSITION_DEFAULT
        return None
    if not cleaned_slug:
        return "A sigla da tag precisa ter de 1 a 4 letras ou números."
    if not parsed_emojis:
        return "Escolha 1 ou 2 emojis válidos para a tag."
    surface, color_error = parse_surface_colors(color_mode, color_1, color_2, gradient_direction)
    if color_error or not surface:
        return color_error or "Escolha uma cor válida."
    chosen_position = valid_tag_position(emoji_position, len(parsed_emojis))
    if not chosen_position:
        return "Escolha a posição dos emojis."
    bg = parse_intensity(bg_intensity, TAG_BG_MIN, TAG_BG_MAX, TAG_BG_DEFAULT)
    if bg is None:
        return "Intensidade do fundo inválida."
    border = parse_intensity(border_intensity, TAG_BORDER_MIN, TAG_BORDER_MAX, TAG_BORDER_DEFAULT)
    if border is None:
        return "Intensidade do contorno inválida."
    club.tag_slug = cleaned_slug
    club.tag_emoji = "".join(parsed_emojis)
    club.tag_color_mode = surface["mode"]
    club.tag_color_1 = surface["color_1"]
    club.tag_color_2 = surface["color_2"]
    club.tag_gradient_direction = surface["direction"]
    club.tag_bg_intensity = bg
    club.tag_border_intensity = border
    club.tag_emoji_position = chosen_position
    return None


def stamp_display_tags(db: Session, users) -> None:
    people = [person for person in users if person]
    tags = display_tags_for(db, people)
    for person in people:
        person.display_tag = tags.get(person.id)


def display_tag_for(db: Session, user: User | None) -> dict | None:
    if not user or not user.displayed_club_id:
        return None
    member = db.scalar(
        select(ClubMember).where(
            ClubMember.club_id == user.displayed_club_id,
            ClubMember.user_id == user.id,
        )
    )
    if not member:
        return None
    club = db.get(Club, user.displayed_club_id)
    return tag_payload(club)


def display_tags_for(db: Session, users: list) -> dict[int, dict]:
    result: dict[int, dict] = {}
    seen: set[int] = set()
    for person in users:
        if not person or person.id in seen:
            continue
        seen.add(person.id)
        tag = display_tag_for(db, person)
        if tag:
            result[person.id] = tag
    return result


def set_displayed_club(db: Session, user: User, club_id_raw: str | int | None) -> None:
    if club_id_raw in (None, "", "0", 0):
        user.displayed_club_id = None
        return
    try:
        club_id = int(club_id_raw)
    except (TypeError, ValueError):
        user.displayed_club_id = None
        return
    allowed = {item["club_id"] for item in selectable_tags(db, user.id)}
    user.displayed_club_id = club_id if club_id in allowed else None


def selectable_tags(db: Session, user_id: int) -> list[dict]:
    tags = []
    for member in db.scalars(select(ClubMember).where(ClubMember.user_id == user_id)):
        club = db.get(Club, member.club_id)
        payload = tag_payload(club)
        if payload and club:
            tags.append({"club_id": club.id, "club_name": club.name, **payload})
    return tags


def clear_displayed_club(db: Session, user_id: int, club_id: int) -> None:
    user = db.get(User, user_id)
    if user and user.displayed_club_id == club_id:
        user.displayed_club_id = None


def clear_tag_preferences(db: Session, club_id: int) -> None:
    for user in db.scalars(select(User).where(User.displayed_club_id == club_id)):
        user.displayed_club_id = None
