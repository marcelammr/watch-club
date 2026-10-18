from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app.db import SessionLocal, engine
from app.discovery import CATALOG, CATEGORY_KINDS, MAX_CATEGORIES, MAX_TAGS, parse_tag_label, tag_slug
from app.main import app
from app.models import CatalogCategory, Club, ClubCatalogCategory, ClubContentTag, ContentTag, User
from app.roles import PERM_TAG, ROLE_SUPPORT
from app.schema import migrate_schema
from tests.test_app import TINY_PNG, register_active
from tests.test_roles import _create_club

client = TestClient(app)


def test_discovery_schema_and_seed():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "catalog_categories",
        "club_catalog_categories",
        "content_tags",
        "club_content_tags",
    } <= tables
    cat_cols = {column["name"] for column in inspector.get_columns("catalog_categories")}
    assert {"id", "slug", "name", "kind", "sort_order", "is_active"} <= cat_cols
    tag_cols = {column["name"] for column in inspector.get_columns("content_tags")}
    assert {"id", "slug", "label"} <= tag_cols
    def unique_pairs(table: str) -> list[tuple[str, ...]]:
        pairs = [tuple(item.get("column_names") or ()) for item in inspector.get_unique_constraints(table)]
        pairs.extend(
            tuple(item.get("column_names") or ())
            for item in inspector.get_indexes(table)
            if item.get("unique")
        )
        return pairs

    assert any(set(cols) >= {"club_id", "category_id"} for cols in unique_pairs("club_catalog_categories"))
    assert any(set(cols) >= {"club_id", "tag_id"} for cols in unique_pairs("club_content_tags"))
    assert any("slug" in cols for cols in unique_pairs("catalog_categories") + unique_pairs("content_tags"))
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(CatalogCategory).order_by(CatalogCategory.sort_order)))
        assert len(rows) == 30
        assert len(CATALOG) == 30
        assert {row.kind for row in rows} == set(CATEGORY_KINDS)
        assert {row.slug for row in rows} == {item[0] for item in CATALOG}
        assert "clubs" in inspector.get_table_names()
        club_cols = {column["name"] for column in inspector.get_columns("clubs")}
        assert "content_tags" not in club_cols
        assert "catalog_categories" not in club_cols
    finally:
        db.close()
    migrate_schema()
    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(CatalogCategory)) == 30
    finally:
        db.close()


def test_tag_normalization_rules():
    label, slug = parse_tag_label("  Survival   Horror  ")
    assert label == "Survival Horror"
    assert slug == tag_slug("SURVIVAL HORROR") == "survival-horror"
    label_accent, slug_accent = parse_tag_label("Ficção científica")
    assert label_accent == "Ficção científica"
    assert slug_accent == "ficcao-cientifica"
    plus, plus_slug = parse_tag_label("LGBTQ+")
    assert plus == "LGBTQ+"
    assert plus_slug == "lgbtq-plus"
    slash, slash_slug = parse_tag_label("anos 80/90")
    assert slash == "anos 80/90"
    assert slash_slug == "anos-80-90"
    amp, amp_slug = parse_tag_label("filmes & séries")
    assert amp == "filmes & séries"
    assert amp_slug == "filmes-e-series"
    bad, err = parse_tag_label("x")
    assert bad is None and err
    long = "a" * 33
    assert parse_tag_label(long)[0] is None
    assert parse_tag_label("https://spam.example")[0] is None
    assert parse_tag_label("ok @spam")[0] is None


def test_club_discovery_save_limits_permissions_and_independence():
    owner = TestClient(app)
    register_active(owner, "disc_adm", "disc.adm@example.com")
    club_id, code = _create_club(owner, "Clube Descoberta")
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.tag_slug == ""
        assert db.scalar(select(ClubCatalogCategory).where(ClubCatalogCategory.club_id == club_id)) is None
        assert db.scalar(select(ClubContentTag).where(ClubContentTag.club_id == club_id)) is None
        kept_description = club.description
        kept_cover = club.cover_image
        kept_icon = club.icon_image
        kept_tag = club.tag_slug
    finally:
        db.close()
    create_page = owner.get("/clubs/novo")
    assert "Descoberta" not in create_page.text
    assert 'name="category_slug"' not in create_page.text

    empty = owner.post(f"/clubs/{club_id}/descoberta", data={}, follow_redirects=False)
    assert empty.status_code == 303
    assert empty.headers["location"].endswith("#descoberta")

    saved = owner.post(
        f"/clubs/{club_id}/descoberta",
        data={
            "category_slug": ["filmes", "terror", "fandom", "nao-existe"],
            "content_tag": ["Survival Horror", "Marvel"],
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    db = SessionLocal()
    try:
        slugs = set(
            db.scalars(
                select(CatalogCategory.slug)
                .join(ClubCatalogCategory, ClubCatalogCategory.category_id == CatalogCategory.id)
                .where(ClubCatalogCategory.club_id == club_id)
            )
        )
        assert slugs == {"filmes", "terror", "fandom"}
        tags = list(
            db.scalars(
                select(ContentTag)
                .join(ClubContentTag, ClubContentTag.tag_id == ContentTag.id)
                .where(ClubContentTag.club_id == club_id)
            )
        )
        assert {item.label for item in tags} == {"Survival Horror", "Marvel"}
        horror_id = db.scalar(select(ContentTag.id).where(ContentTag.slug == "survival-horror"))
        club = db.get(Club, club_id)
        assert club.description == kept_description
        assert club.cover_image == kept_cover
        assert club.icon_image == kept_icon
        assert club.tag_slug == kept_tag
    finally:
        db.close()

    page = owner.get(f"/clubs/{club_id}/config")
    assert "Descoberta" in page.text
    assert "value=\"filmes\"" in page.text
    assert "Survival Horror" in page.text

    over_cats = owner.post(
        f"/clubs/{club_id}/descoberta",
        data={"category_slug": [item[0] for item in CATALOG[: MAX_CATEGORIES + 1]]},
        follow_redirects=False,
    )
    assert over_cats.status_code == 400
    db = SessionLocal()
    try:
        count = db.scalar(
            select(func.count())
            .select_from(ClubCatalogCategory)
            .where(ClubCatalogCategory.club_id == club_id)
        )
        assert count == 3
    finally:
        db.close()

    over_tags = owner.post(
        f"/clubs/{club_id}/descoberta",
        data={"content_tag": [f"tag{n:02d}" for n in range(MAX_TAGS + 1)]},
        follow_redirects=False,
    )
    assert over_tags.status_code == 400

    other = TestClient(app)
    register_active(other, "disc_adm2", "disc.adm2@example.com")
    other_id, _code = _create_club(other, "Outro Descoberta")
    reused = other.post(
        f"/clubs/{other_id}/descoberta",
        data={"content_tag": "survival horror"},
        follow_redirects=False,
    )
    assert reused.status_code == 303
    db = SessionLocal()
    try:
        tags = list(db.scalars(select(ContentTag).where(ContentTag.slug == "survival-horror")))
        assert len(tags) == 1
        assert tags[0].label == "Survival Horror"
        assert tags[0].id == horror_id
        links = list(db.scalars(select(ClubContentTag).where(ClubContentTag.tag_id == horror_id)))
        assert {link.club_id for link in links} == {club_id, other_id}
    finally:
        db.close()

    dup = owner.post(
        f"/clubs/{club_id}/descoberta",
        data={"content_tag": ["Survival Horror", "SURVIVAL HORROR", "cinema nacional"]},
        follow_redirects=False,
    )
    assert dup.status_code == 303
    db = SessionLocal()
    try:
        club_tags = list(
            db.scalars(
                select(ContentTag.slug)
                .join(ClubContentTag, ClubContentTag.tag_id == ContentTag.id)
                .where(ClubContentTag.club_id == club_id)
            )
        )
        assert club_tags.count("survival-horror") == 1
        assert "cinema-nacional" in club_tags
        assert len(club_tags) == 2
    finally:
        db.close()

    owner.post(
        f"/clubs/{club_id}/descoberta",
        data={"content_tag": "LGBTQ+", "category_slug": "filmes"},
        follow_redirects=False,
    )
    owner.post(
        f"/clubs/{club_id}/descoberta",
        data={"content_tag": "anos 80/90"},
        follow_redirects=False,
    )
    owner.post(
        f"/clubs/{club_id}/descoberta",
        data={"content_tag": "filmes & séries"},
        follow_redirects=False,
    )
    db = SessionLocal()
    try:
        slugs = set(
            db.scalars(
                select(ContentTag.slug)
                .join(ClubContentTag, ClubContentTag.tag_id == ContentTag.id)
                .where(ClubContentTag.club_id == club_id)
            )
        )
        assert slugs == {"filmes-e-series"}
    finally:
        db.close()

    too_short = owner.post(
        f"/clubs/{club_id}/descoberta",
        data={"content_tag": "a"},
        follow_redirects=False,
    )
    assert too_short.status_code == 400

    uploaded = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Clube Descoberta",
            "description": "Texto da descricao",
            "rules": "",
            "cover_color": "#246B45",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "settings_section": "aparencia",
        },
        files={
            "icon_file": ("icon.png", TINY_PNG, "image/png"),
            "cover_file": ("cover.png", TINY_PNG, "image/png"),
        },
        follow_redirects=False,
    )
    assert uploaded.status_code == 303
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        icon_name = club.icon_image
        cover_name = club.cover_image
        assert icon_name and cover_name
    finally:
        db.close()
    tagged = owner.post(
        f"/clubs/{club_id}/tag",
        data={"tag_slug": "DISC", "tag_emoji": "🍿", "tag_color_mode": "solid", "tag_color_1": "#B892FF"},
        follow_redirects=False,
    )
    assert tagged.status_code == 303
    config_keep = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Clube Descoberta",
            "description": "Texto da descricao",
            "rules": "",
            "cover_color": "#246B45",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "settings_section": "geral",
        },
        follow_redirects=False,
    )
    assert config_keep.status_code == 303
    db = SessionLocal()
    try:
        before = len(list(db.scalars(select(ClubCatalogCategory).where(ClubCatalogCategory.club_id == club_id))))
        club = db.get(Club, club_id)
        assert club.tag_slug == "DISC"
        assert club.icon_image == icon_name
        assert club.cover_image == cover_name
        assert club.description == "Texto da descricao"
    finally:
        db.close()
    tag_again = owner.post(
        f"/clubs/{club_id}/tag",
        data={"tag_slug": "DISC", "tag_emoji": "🍿", "tag_color_mode": "solid", "tag_color_1": "#B892FF"},
        follow_redirects=False,
    )
    assert tag_again.status_code == 303
    db = SessionLocal()
    try:
        after = len(list(db.scalars(select(ClubCatalogCategory).where(ClubCatalogCategory.club_id == club_id))))
        club = db.get(Club, club_id)
        assert after == before
        assert club.tag_slug == "DISC"
        assert club.icon_image == icon_name
        assert club.cover_image == cover_name
        assert club.description == "Texto da descricao"
    finally:
        db.close()

    member = TestClient(app)
    register_active(member, "disc_mem", "disc.mem@example.com")
    member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    blocked_member = member.post(
        f"/clubs/{club_id}/descoberta",
        data={"category_slug": "drama"},
        follow_redirects=False,
    )
    assert blocked_member.status_code == 303
    assert blocked_member.headers["location"] == f"/clubs/{club_id}"

    helper = TestClient(app)
    register_active(helper, "disc_sub", "disc.sub@example.com")
    helper.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    db = SessionLocal()
    try:
        helper_id = db.scalar(select(User.id).where(User.username_key == "disc_sub"))
        before_slugs = set(
            db.scalars(
                select(CatalogCategory.slug)
                .join(ClubCatalogCategory, ClubCatalogCategory.category_id == CatalogCategory.id)
                .where(ClubCatalogCategory.club_id == club_id)
            )
        )
    finally:
        db.close()
    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": ROLE_SUPPORT, "support_perm": [PERM_TAG]},
        follow_redirects=False,
    )
    blocked_sub = helper.post(
        f"/clubs/{club_id}/descoberta",
        data={"category_slug": "drama", "content_tag": "hack"},
        follow_redirects=False,
    )
    assert blocked_sub.status_code == 303
    assert blocked_sub.headers["location"] == f"/clubs/{club_id}"
    db = SessionLocal()
    try:
        slugs = set(
            db.scalars(
                select(CatalogCategory.slug)
                .join(ClubCatalogCategory, ClubCatalogCategory.category_id == CatalogCategory.id)
                .where(ClubCatalogCategory.club_id == club_id)
            )
        )
        assert slugs == before_slugs
        club = db.get(Club, club_id)
        assert club.tag_slug == "DISC"
        assert club.icon_image == icon_name
        assert club.cover_image == cover_name
    finally:
        db.close()


def test_discovery_tag_input_feedback_copy():
    owner = TestClient(app)
    register_active(owner, "disc_fb", "disc.fb@example.com")
    club_id, _code = _create_club(owner, "Feedback Tags")
    page = owner.get(f"/clubs/{club_id}/config")
    assert page.status_code == 200
    assert 'id="discovery-tag-error"' in page.text
    assert 'aria-invalid="false"' in page.text
    assert "js-discovery-tag-control" in page.text
    assert "discovery-tag-compose" in page.text
    assert "js-discovery-tag-clear" in page.text
    assert 'aria-label="Limpar tag"' in page.text
    assert "setAttribute(\"hidden\"" in page.text
    assert "removeAttribute(\"aria-describedby\")" in page.text
    assert "js-discovery-tag-remove" in page.text
    assert "js-discovery-tag-add" in page.text
    assert "clearAttempt" in page.text
    assert "Esta tag já foi adicionada ao clube." in page.text
    assert "A tag deve ter pelo menos 2 caracteres." in page.text
    assert "A tag pode ter no máximo 32 caracteres." in page.text
    assert "Esta tag contém caracteres não permitidos." in page.text
    assert "Links não podem ser usados como tags." in page.text
    assert "Você pode adicionar até 10 tags." in page.text
    assert "window.alert" not in page.text
    assert "alert(" not in page.text.split("js-discovery-form")[-1]
    assert 'role="alert"' in page.text
    assert "slugKey(" in page.text
