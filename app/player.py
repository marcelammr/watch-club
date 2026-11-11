from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts import utcnow
from app.friends import friend_id_set
from app.models import ClubMember, User, UserShowFavorite

DEFAULT_THEME = "watchclub"
DEFAULT_WALLPAPER = "grid"
PROFILE_STATUS_MAX = 80
DAYS_PER_LEVEL = 30
MAX_LEVEL = 99
ENERGY_MAX = 5
WALLPAPER_ROOT = Path(__file__).resolve().parent / "static" / "wallpapers"
THEMES = {
    "watchclub": "Watch Club",
    "bubblegum": "Bubblegum",
    "dreamy": "Dreamy",
    "matcha": "Matcha",
    "cyber": "Cyber",
    "campfire": "Campfire Songs",
    "piece": "A Piece of a Dream",
    "mocha": "Smoky Mocha",
    "nightclub": "Night Clubs",
    "cherries": "Fizzy Cherries",
    "cotton": "Cotton Candy Skies",
    "castle": "Castle in the Sky",
    "muddy": "Muddy Waters",
    "lagoon": "Lagoon",
    "frost": "Deep Frost",
    "lemon": "Lemon Tape",
    "brick": "Red Brick",
    "pine": "Pine Cabinet",
    "lime": "Arcade Lime",
    "bluebird": "Bluebird",
    "voltage": "Hot Signal",
    "peach": "Peach Soda",
}

def _image_paper(label: str, file: str, thumb: str) -> dict:
    return {
        "label": label,
        "kind": "image",
        "file": file,
        "thumb": thumb,
        "css_class": "wc-paper-asset",
        "size": "cover",
        "repeat": "no-repeat",
        "position": "center",
    }


# kind: css (class pattern) | image (local raster/SVG file).
# Image specs stay hidden until the file exists under static/wallpapers/.
WALLPAPER_SPECS = {
    "grid": {"label": "Grid", "kind": "css", "css_class": "wc-paper-grid"},
    "stars": {"label": "Stars", "kind": "css", "css_class": "wc-paper-stars"},
    "sky": {"label": "Dreamy Sky", "kind": "css", "css_class": "wc-paper-sky"},
    "desktop": {"label": "Desktop", "kind": "css", "css_class": "wc-paper-desktop"},
    "night": {"label": "Night", "kind": "css", "css_class": "wc-paper-night"},
    "checker": {"label": "Checker", "kind": "css", "css_class": "wc-paper-checker"},
    "doodles": {"label": "Watch Doodles", "kind": "css", "css_class": "wc-paper-doodles"},
    "azure-cove": _image_paper("Azure Cove", "azure-cove.png", "azure-cove.jpg"),
    "sunset-mirror": _image_paper("Sunset Mirror", "sunset-mirror.png", "sunset-mirror.jpg"),
    "moonlit-sea": _image_paper("Moonlit Sea", "moonlit-sea.png", "moonlit-sea.jpg"),
    "sea-stacks": _image_paper("Sea Stacks", "sea-stacks.png", "sea-stacks.jpg"),
    "teal-city": _image_paper("Teal City", "teal-city.png", "teal-city.jpg"),
    "candy-city": _image_paper("Candy City", "candy-city.png", "candy-city.jpg"),
    "golden-clouds": _image_paper("Golden Clouds", "golden-clouds.png", "golden-clouds.jpg"),
    "dusk-skyline": _image_paper("Dusk Skyline", "dusk-skyline.png", "dusk-skyline.jpg"),
    "sunflower-field": _image_paper("Sunflower Field", "sunflower-field.png", "sunflower-field.jpg"),
    "lilac-peaks": _image_paper("Lilac Peaks", "lilac-peaks.png", "lilac-peaks.jpg"),
}
PROFILE_TABS = ("perfil", "favoritos", "clubes", "aparencia")


def wallpaper_spec(key: str | None) -> dict | None:
    return WALLPAPER_SPECS.get((key or "").strip().lower())


def wallpaper_file_path(spec: dict) -> Path | None:
    name = spec.get("file")
    if not name:
        return None
    return WALLPAPER_ROOT / name


def wallpaper_available(spec: dict) -> bool:
    if spec.get("enabled") is False:
        return False
    if spec.get("kind") == "image":
        path = wallpaper_file_path(spec)
        return bool(path and path.is_file())
    return True


def wallpaper_catalog() -> dict[str, str]:
    return {key: spec["label"] for key, spec in WALLPAPER_SPECS.items() if wallpaper_available(spec)}


WALLPAPERS = wallpaper_catalog()


def wallpaper_src(spec: dict) -> str:
    name = spec.get("file") or ""
    return f"/static/wallpapers/{name}"


def wallpaper_thumb_src(spec: dict) -> str:
    thumb = spec.get("thumb")
    if thumb:
        return f"/static/wallpapers/thumbs/{thumb}"
    return wallpaper_src(spec)


def wallpaper_class(key: str | None) -> str:
    resolved = normalize_wallpaper(key)
    spec = WALLPAPER_SPECS[resolved]
    if spec.get("kind") == "image" and wallpaper_available(spec):
        return f"wc-paper-asset wc-paper-{resolved}"
    return spec.get("css_class") or f"wc-paper-{DEFAULT_WALLPAPER}"


def wallpaper_style(key: str | None) -> str:
    spec = wallpaper_spec(key)
    if not spec or spec.get("kind") != "image" or not wallpaper_available(spec):
        return ""
    src = wallpaper_src(spec)
    size = spec.get("size") or "cover"
    repeat = spec.get("repeat") or "no-repeat"
    position = spec.get("position") or "center"
    thumb = wallpaper_thumb_src(spec)
    return (
        f"--wc-wallpaper-src:url('{src}');"
        f"--wc-wallpaper-thumb:url('{thumb}');"
        f"--wc-wallpaper-size:{size};"
        f"--wc-wallpaper-repeat:{repeat};"
        f"--wc-wallpaper-position:{position};"
    )


def normalize_theme(value: str | None) -> str:
    key = (value or "").strip().lower()
    return key if key in THEMES else DEFAULT_THEME


def require_theme(value: str | None) -> str:
    key = (value or "").strip().lower()
    if key not in THEMES:
        raise HTTPException(status_code=400, detail="Tema inválido")
    return key


def theme_of(user: User | None) -> str:
    if user is None:
        return DEFAULT_THEME
    return normalize_theme(getattr(user, "theme_key", None))


def normalize_wallpaper(value: str | None) -> str:
    key = (value or "").strip().lower()
    spec = wallpaper_spec(key)
    if spec and wallpaper_available(spec):
        return key
    return DEFAULT_WALLPAPER


def require_wallpaper(value: str | None) -> str:
    key = (value or "").strip().lower()
    spec = wallpaper_spec(key)
    if not spec or not wallpaper_available(spec):
        raise HTTPException(status_code=400, detail="Fundo inválido")
    return key


def wallpaper_of(user: User | None) -> str:
    if user is None:
        return DEFAULT_WALLPAPER
    return normalize_wallpaper(getattr(user, "wallpaper_key", None))


def player_progress(created_at: datetime | None, *, now: datetime | None = None) -> dict:
    moment = now or utcnow()
    start = created_at or moment
    days = max(0, (moment - start).days)
    level = min(MAX_LEVEL, 1 + days // DAYS_PER_LEVEL)
    if level >= MAX_LEVEL:
        into = DAYS_PER_LEVEL
        percent = 100
    else:
        into = days % DAYS_PER_LEVEL
        percent = int(round(100 * into / DAYS_PER_LEVEL))
    return {
        "level": level,
        "percent": percent,
        "into_days": into,
        "span_days": DAYS_PER_LEVEL,
        "max_level": MAX_LEVEL,
    }


def energy_hearts(last_seen: datetime | None, *, now: datetime | None = None) -> int:
    if last_seen is None:
        return 0
    moment = now or utcnow()
    days = max(0.0, (moment - last_seen).total_seconds() / 86400)
    if days <= 1:
        return 5
    if days <= 3:
        return 4
    if days <= 7:
        return 3
    if days <= 14:
        return 2
    if days <= 30:
        return 1
    return 0


def clean_profile_status(value: str | None) -> str:
    text = " ".join((value or "").split())
    if len(text) > PROFILE_STATUS_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"O status pode ter no máximo {PROFILE_STATUS_MAX} caracteres.",
        )
    return text


def profile_tab(aba: str | None, *, own: bool) -> str:
    key = (aba or "").strip().lower()
    if key == "aparencia" and not own:
        return "perfil"
    if key in PROFILE_TABS:
        return key
    return "perfil"


def player_stats(db: Session, person: User, *, club_count: int, favorite_count: int) -> dict:
    year = person.created_at.year if person.created_at else utcnow().year
    return {
        "clubs": club_count,
        "friends": len(friend_id_set(db, person.id)),
        "favorites": favorite_count,
        "member_since": year,
    }


def player_card_payload(db: Session, user: User) -> dict:
    clubs = db.scalar(select(func.count()).select_from(ClubMember).where(ClubMember.user_id == user.id)) or 0
    favorites = (
        db.scalar(select(func.count()).select_from(UserShowFavorite).where(UserShowFavorite.user_id == user.id))
        or 0
    )
    progress = player_progress(user.created_at)
    return {
        "level": progress["level"],
        "percent": progress["percent"],
        "energy": energy_hearts(user.last_seen),
        "energy_max": ENERGY_MAX,
        "status": (user.profile_status or "").strip(),
        "stats": player_stats(db, user, club_count=int(clubs), favorite_count=int(favorites)),
        "theme": theme_of(user),
        "wallpaper": wallpaper_of(user),
    }
