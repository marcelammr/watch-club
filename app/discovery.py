from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CatalogCategory, ClubCatalogCategory, ClubContentTag, ContentTag

KIND_FORMAT = "format"
KIND_GENRE = "genre"
KIND_COMMUNITY = "community"
CATEGORY_KINDS = (KIND_FORMAT, KIND_GENRE, KIND_COMMUNITY)
KIND_LABELS = {
    KIND_FORMAT: "Mídia / Formato",
    KIND_GENRE: "Gênero",
    KIND_COMMUNITY: "Comunidade & Cultura",
}

MAX_CATEGORIES = 8
MAX_TAGS = 10
TAG_LABEL_MIN = 2
TAG_LABEL_MAX = 32

_URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)
_SLUG_KEEP = re.compile(r"[^a-z0-9]+")
_MULTI_HYPHEN = re.compile(r"-{2,}")
_ALLOWED_PUNCT = frozenset(" -+/&")

CATALOG: tuple[tuple[str, str, str, int], ...] = (
    ("filmes", "Filmes", KIND_FORMAT, 10),
    ("series", "Séries", KIND_FORMAT, 20),
    ("anime", "Anime", KIND_FORMAT, 30),
    ("animacao", "Animação", KIND_FORMAT, 40),
    ("doramas", "Doramas", KIND_FORMAT, 50),
    ("reality-show", "Reality Show", KIND_FORMAT, 60),
    ("tv", "TV", KIND_FORMAT, 70),
    ("documentarios", "Documentários", KIND_FORMAT, 80),
    ("games", "Games", KIND_FORMAT, 90),
    ("acao", "Ação", KIND_GENRE, 110),
    ("aventura", "Aventura", KIND_GENRE, 120),
    ("comedia", "Comédia", KIND_GENRE, 130),
    ("crime", "Crime", KIND_GENRE, 140),
    ("drama", "Drama", KIND_GENRE, 150),
    ("fantasia", "Fantasia", KIND_GENRE, 160),
    ("ficcao-cientifica", "Ficção científica", KIND_GENRE, 170),
    ("misterio", "Mistério", KIND_GENRE, 180),
    ("romance", "Romance", KIND_GENRE, 190),
    ("suspense", "Suspense", KIND_GENRE, 200),
    ("terror", "Terror", KIND_GENRE, 210),
    ("adaptacoes", "Adaptações", KIND_COMMUNITY, 310),
    ("cultura-pop", "Cultura pop", KIND_COMMUNITY, 320),
    ("fandom", "Fandom", KIND_COMMUNITY, 330),
    ("nostalgia", "Nostalgia", KIND_COMMUNITY, 340),
    ("musica", "Música", KIND_COMMUNITY, 350),
    ("premiacoes", "Premiações", KIND_COMMUNITY, 360),
    ("celebridades", "Celebridades", KIND_COMMUNITY, 370),
    ("teorias", "Teorias", KIND_COMMUNITY, 380),
    ("critica-analise", "Crítica & análise", KIND_COMMUNITY, 390),
    ("colecionismo", "Colecionismo", KIND_COMMUNITY, 400),
)


def collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def tag_label(value: str) -> str:
    return collapse_spaces(value)


def tag_slug(label: str) -> str:
    folded = unicodedata.normalize("NFKD", tag_label(label))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold()
    folded = folded.replace("&", " e ").replace("+", " plus ").replace("/", " ")
    folded = _SLUG_KEEP.sub("-", folded)
    return _MULTI_HYPHEN.sub("-", folded).strip("-")


def _has_control(label: str) -> bool:
    for char in label:
        if char in " \t":
            continue
        if unicodedata.category(char).startswith("C"):
            return True
        if char in "\u200b\u200c\u200d\u2060\ufeff":
            return True
    return False


def _allowed_label_chars(label: str) -> bool:
    for char in label:
        if char in _ALLOWED_PUNCT:
            continue
        category = unicodedata.category(char)
        if category.startswith("L") or category.startswith("N"):
            continue
        return False
    return True


def parse_tag_label(value: str) -> tuple[str | None, str | None]:
    label = tag_label(value)
    if not label:
        return None, None
    if _URL_RE.search(label) or "://" in label:
        return None, "A tag não pode ser um endereço da web."
    if _has_control(label):
        return None, "A tag contém caracteres inválidos."
    if not _allowed_label_chars(label):
        return None, "Use letras, números, espaços e os sinais - + / &."
    if len(label) < TAG_LABEL_MIN:
        return None, f"Cada tag precisa ter pelo menos {TAG_LABEL_MIN} caracteres."
    if len(label) > TAG_LABEL_MAX:
        return None, f"Cada tag pode ter no máximo {TAG_LABEL_MAX} caracteres."
    slug = tag_slug(label)
    if not slug:
        return None, "A tag precisa de letras ou números."
    return label, slug


def grouped_catalog(rows: list[CatalogCategory]) -> list[dict]:
    by_kind: dict[str, list[CatalogCategory]] = {kind: [] for kind in CATEGORY_KINDS}
    for row in rows:
        if row.kind in by_kind:
            by_kind[row.kind].append(row)
    groups = []
    for kind in CATEGORY_KINDS:
        groups.append({"kind": kind, "label": KIND_LABELS[kind], "categories": by_kind[kind]})
    return groups


def load_catalog(db: Session, *, active_only: bool = True) -> list[CatalogCategory]:
    query = select(CatalogCategory).order_by(CatalogCategory.sort_order, CatalogCategory.id)
    if active_only:
        query = query.where(CatalogCategory.is_active.is_(True))
    return list(db.scalars(query))


def club_discovery_state(db: Session, club_id: int) -> dict:
    selected = list(
        db.scalars(
            select(CatalogCategory.slug)
            .join(ClubCatalogCategory, ClubCatalogCategory.category_id == CatalogCategory.id)
            .where(ClubCatalogCategory.club_id == club_id)
        )
    )
    tags = list(
        db.execute(
            select(ContentTag)
            .join(ClubContentTag, ClubContentTag.tag_id == ContentTag.id)
            .where(ClubContentTag.club_id == club_id)
            .order_by(ClubContentTag.id)
        ).scalars()
    )
    return {
        "selected_slugs": set(selected),
        "tags": [{"label": item.label, "slug": item.slug} for item in tags],
    }


def apply_club_discovery(
    db: Session,
    club_id: int,
    category_slugs: list[str] | None,
    tag_labels: list[str] | None,
) -> str | None:
    wanted_slugs: list[str] = []
    seen_cat: set[str] = set()
    for raw in category_slugs or []:
        slug = (raw or "").strip().lower()
        if not slug or slug in seen_cat:
            continue
        seen_cat.add(slug)
        wanted_slugs.append(slug)
    valid_rows = []
    if wanted_slugs:
        valid_rows = list(
            db.scalars(
                select(CatalogCategory).where(
                    CatalogCategory.slug.in_(wanted_slugs),
                    CatalogCategory.is_active.is_(True),
                )
            )
        )
    by_slug = {row.slug: row for row in valid_rows}
    chosen_ids = [by_slug[slug].id for slug in wanted_slugs if slug in by_slug]
    if len(chosen_ids) > MAX_CATEGORIES:
        return f"Escolha no máximo {MAX_CATEGORIES} categorias."

    parsed_tags: list[tuple[str, str]] = []
    seen_tag: set[str] = set()
    for raw in tag_labels or []:
        if not collapse_spaces(raw):
            continue
        label, slug_or_error = parse_tag_label(raw)
        if label is None:
            return slug_or_error
        slug = slug_or_error
        if slug in seen_tag:
            continue
        seen_tag.add(slug)
        parsed_tags.append((label, slug))
    if len(parsed_tags) > MAX_TAGS:
        return f"Use no máximo {MAX_TAGS} tags de conteúdo."

    current_cat = list(db.scalars(select(ClubCatalogCategory).where(ClubCatalogCategory.club_id == club_id)))
    keep_cat = set(chosen_ids)
    for link in current_cat:
        if link.category_id not in keep_cat:
            db.delete(link)
    have_cat = {link.category_id for link in current_cat if link.category_id in keep_cat}
    for category_id in chosen_ids:
        if category_id not in have_cat:
            db.add(ClubCatalogCategory(club_id=club_id, category_id=category_id))

    tag_ids: list[int] = []
    for label, slug in parsed_tags:
        existing = db.scalar(select(ContentTag).where(ContentTag.slug == slug))
        if existing:
            tag_ids.append(existing.id)
            continue
        created = ContentTag(slug=slug, label=label)
        db.add(created)
        db.flush()
        tag_ids.append(created.id)

    current_tags = list(db.scalars(select(ClubContentTag).where(ClubContentTag.club_id == club_id)))
    keep_tags = set(tag_ids)
    for link in current_tags:
        if link.tag_id not in keep_tags:
            db.delete(link)
    have_tags = {link.tag_id for link in current_tags if link.tag_id in keep_tags}
    for tag_id in tag_ids:
        if tag_id not in have_tags:
            db.add(ClubContentTag(club_id=club_id, tag_id=tag_id))
    return None
