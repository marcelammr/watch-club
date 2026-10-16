from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app.club_tags import (
    apply_club_tag,
    parse_tag_emojis,
    tag_display_parts,
    valid_tag_position,
    valid_tag_slug,
)
from app.colors import parse_surface_colors, valid_hex
from app.db import SessionLocal, engine
from app.main import app
from app.models import Club, ClubJoinRequest, ClubMember, User
from app.roles import (
    MAX_ADMINS,
    MAX_SUPPORT,
    PERM_JOINS,
    PERM_TAG,
    PERM_TITLES,
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_SUPPORT,
    can,
    dump_support_perms,
    parse_support_perms,
)
from tests.test_app import register_active

client = TestClient(app)
EMOJI = "🍿"


def test_schema_dropped_is_admin_and_added_role():
    inspector = inspect(engine)
    member_cols = {column["name"] for column in inspector.get_columns("club_members")}
    user_cols = {column["name"] for column in inspector.get_columns("users")}
    club_cols = {column["name"] for column in inspector.get_columns("clubs")}
    assert "is_admin" not in member_cols
    assert "role" in member_cols
    assert "support_perms" in member_cols
    assert "displayed_club_id" in user_cols
    assert {
        "tag_slug",
        "tag_emoji",
        "tag_color",
        "tag_color_mode",
        "tag_color_1",
        "tag_color_2",
        "tag_gradient_direction",
        "tag_bg_intensity",
        "tag_border_intensity",
        "tag_emoji_position",
        "admin_name_color",
        "sub_name_color",
        "member_limit",
    } <= club_cols


def test_support_perms_allowlist_ignores_unknown():
    parsed = parse_support_perms("manage_tag,hack,manage_titles,manage_tag,not_a_perm")
    assert parsed == [PERM_TAG, PERM_TITLES]
    assert dump_support_perms(["hack", PERM_JOINS, PERM_TAG]) == f"{PERM_TAG},{PERM_JOINS}"


def test_can_uses_role_and_allowlist():
    admin = ClubMember(role=ROLE_ADMIN, support_perms="")
    support = ClubMember(role=ROLE_SUPPORT, support_perms=PERM_TAG)
    member = ClubMember(role=ROLE_MEMBER, support_perms=f"{PERM_TAG},{PERM_TITLES}")
    assert can(admin, PERM_JOINS) is True
    assert can(support, PERM_TAG) is True
    assert can(support, PERM_TITLES) is False
    assert can(member, PERM_TAG) is False


def test_tag_validations_reject_unsafe_values():
    assert valid_tag_slug("wc12") == "WC12"
    assert valid_tag_slug("toolong") == ""
    assert valid_tag_slug("w c") == ""
    assert valid_hex("#b892ff") == "#B892FF"
    assert valid_hex("red") is None
    assert valid_hex("rgb(1,2,3)") is None
    assert valid_hex("var(--x)") is None
    assert valid_hex("url(x)") is None
    assert valid_hex("linear-gradient(red,blue)") is None
    assert parse_surface_colors("solid", "#6c63ff", "#FF5D8F", "right") == (
        {
            "mode": "solid",
            "color_1": "#6C63FF",
            "color_2": None,
            "direction": None,
            "angle": "90deg",
        },
        None,
    )
    assert parse_tag_emojis("😇😈") == ["😇", "😈"]
    assert parse_tag_emojis("👍🏽") == ["👍🏽"]
    assert parse_tag_emojis("🇧🇷") == ["🇧🇷"]
    assert parse_tag_emojis("1️⃣") == ["1️⃣"]
    assert parse_tag_emojis("👨‍👩‍👧‍👦") == ["👨‍👩‍👧‍👦"]
    assert parse_tag_emojis("😇😈🌙") is None
    assert parse_tag_emojis("MC") is None
    assert parse_tag_emojis("★") is None
    assert parse_tag_emojis("<script>") is None
    club = Club(name="X", join_code="ABCDEFGH", owner_id=1)
    assert apply_club_tag(club, "WC", EMOJI, color_1="not-a-color") == "Escolha uma cor válida."
    assert apply_club_tag(club, "WC", EMOJI, 5, 55) == "Intensidade do fundo inválida."
    assert apply_club_tag(club, "WC", EMOJI, 18, 91) == "Intensidade do contorno inválida."
    assert apply_club_tag(club, "WC", "😇😈", 18, 55) is None
    assert club.tag_emoji == "😇😈"
    assert club.tag_bg_intensity == 18
    assert club.tag_border_intensity == 55
    assert club.tag_emoji_position == "start"
    assert club.tag_color_1 == "#B892FF"
    assert club.tag_color_mode == "solid"
    assert valid_tag_position("split", 1) == "start"
    assert valid_tag_position("split", 2) == "split"
    assert valid_tag_position("side", 2) is None
    assert tag_display_parts(["😇", "😈"], "MC", "start") == {"prefix": "😇😈", "slug": "MC", "suffix": ""}
    assert tag_display_parts(["😇", "😈"], "MC", "end") == {"prefix": "", "slug": "MC", "suffix": "😇😈"}
    assert tag_display_parts(["😇", "😈"], "MC", "split") == {"prefix": "😇", "slug": "MC", "suffix": "😈"}
    assert tag_display_parts(["😇"], "MC", "split") == {"prefix": "😇", "slug": "MC", "suffix": ""}
    assert apply_club_tag(club, "WC", "😇😈", 18, 55, "split") is None
    assert club.tag_emoji_position == "split"
    assert apply_club_tag(club, "WC", "😇", 18, 55, "split") is None
    assert club.tag_emoji_position == "start"
    assert apply_club_tag(club, "WC", "😇😈", 18, 55, "nope") == "Escolha a posição dos emojis."
    assert (
        apply_club_tag(
            club,
            "WC",
            "😇😈",
            18,
            55,
            "split",
            "gradient",
            "#B892FF",
            "#FF5D8F",
            "right",
        )
        is None
    )
    assert club.tag_color_mode == "gradient"
    assert club.tag_color_1 == "#B892FF"
    assert club.tag_color_2 == "#FF5D8F"
    assert club.tag_gradient_direction == "right"
    assert apply_club_tag(club, "WC", "😇😈", 18, 55, "start", "gradient", "#B892FF", "", "right") == (
        "Escolha as duas cores do degradê."
    )


def _create_club(http: TestClient, name: str, closed: bool = False) -> tuple[int, str]:
    data = {"name": name}
    if closed:
        data["is_closed"] = "1"
    created = http.post("/clubs", data=data, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        code = db.get(Club, club_id).join_code
    finally:
        db.close()
    return club_id, code


def _user_id_by_key(key: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(User.id).where(User.username_key == key))
    finally:
        db.close()


def _request_and_accept(member: TestClient, owner: TestClient, club_id: int, code: str, username_key: str) -> None:
    asked = member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    assert asked.status_code == 303
    accepted = owner.post(
        f"/clubs/{club_id}/solicitacoes/{_user_id_by_key(username_key)}/aceitar",
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert "lotado" not in accepted.headers["location"]
    assert "error=" not in accepted.headers["location"]


def test_admin_sets_support_perms_and_support_cannot_edit_roles():
    owner = TestClient(app)
    register_active(owner, "papel_adm", "papel.adm@example.com")
    club_id, code = _create_club(owner, "Sala Papel")
    helper = TestClient(app)
    register_active(helper, "papel_sup", "papel.sup@example.com")
    helper.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    db = SessionLocal()
    try:
        helper_id = db.scalar(select(User.id).where(User.username_key == "papel_sup"))
    finally:
        db.close()

    granted = owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": "support", "support_perm": [PERM_TAG, PERM_JOINS, "hack_perm"]},
        follow_redirects=False,
    )
    assert granted.status_code == 303
    assert granted.headers["location"].endswith("#cargos")
    db = SessionLocal()
    try:
        target = db.scalar(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == helper_id))
        assert target.role == ROLE_SUPPORT
        assert parse_support_perms(target.support_perms) == [PERM_TAG, PERM_JOINS]
    finally:
        db.close()

    stolen = helper.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": "admin", "support_perm": [PERM_TITLES]},
        follow_redirects=False,
    )
    assert stolen.status_code == 303
    assert stolen.headers["location"] == f"/clubs/{club_id}"
    other = TestClient(app)
    register_active(other, "papel_mem", "papel.mem@example.com")
    other.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    db = SessionLocal()
    try:
        other_id = db.scalar(select(User.id).where(User.username_key == "papel_mem"))
        owner_id = db.scalar(select(User.id).where(User.username_key == "papel_adm"))
    finally:
        db.close()
    others_role = helper.post(
        f"/clubs/{club_id}/membros/{other_id}/papel",
        data={"role": "support"},
        follow_redirects=False,
    )
    assert others_role.status_code == 303
    assert others_role.headers["location"] == f"/clubs/{club_id}"
    config = helper.get(f"/clubs/{club_id}/config", follow_redirects=False)
    assert config.status_code == 303
    titles_blocked = helper.post(f"/clubs/{club_id}/shows/1/remover", follow_redirects=False)
    assert titles_blocked.status_code == 303
    assert titles_blocked.headers["location"] == f"/clubs/{club_id}"
    tag_page = helper.get(f"/clubs/{club_id}/tag")
    assert tag_page.status_code == 200
    assert "js-club-settings" in tag_page.text
    assert "is-tag-only" in tag_page.text
    assert "settings-overlay" in tag_page.text
    assert "Fundo do clube" not in tag_page.text
    assert "Cargos e permissões" not in tag_page.text
    assert 'name="admin_name_color"' not in tag_page.text
    assert 'name="member_limit"' not in tag_page.text
    assert 'name="is_closed"' not in tag_page.text
    assert 'data-section="geral"' not in tag_page.text
    assert 'data-section="tag"' in tag_page.text
    assert "Ver orientações" in tag_page.text
    assert "Como funcionam as tags?" in tag_page.text
    assert "Posição dos emojis" in tag_page.text
    assert "Personalizar cor" in tag_page.text
    assert 'name="tag_color_1"' in tag_page.text
    assert 'name="tag_color_mode"' in tag_page.text
    assert "Sólida" in tag_page.text
    assert "Degradê" in tag_page.text
    assert "club-tag-violet" not in tag_page.text
    assert "tag-swatch-lavender" not in tag_page.text
    assert 'name="tag_emoji_position"' in tag_page.text
    assert "Separados" in tag_page.text
    assert 'id="tag-guide-dialog"' in tag_page.text
    assert "open" not in tag_page.text.split('id="tag-guide-dialog"', 1)[1].split(">", 1)[0]
    assert "A tag aparece no perfil de quem escolher exibi-la" not in tag_page.text
    saved = helper.post(
        f"/clubs/{club_id}/tag",
        data={
            "tag_slug": "WC",
            "tag_emoji": "😇😈",
            "tag_color_mode": "solid",
            "tag_color_1": "#6C63FF",
            "tag_emoji_position": "split",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"].startswith(f"/clubs/{club_id}/tag")
    room = helper.get(f"/clubs/{club_id}")
    assert "Tag do clube" in room.text
    assert f"/clubs/{club_id}/config" not in room.text
    assert "club-person-name is-support" in room.text
    assert "SUBADMINISTRADORES" in room.text
    assert ">SUB<" not in room.text
    profile = helper.get("/u/papel_sup")
    assert ">SUB<" not in profile.text
    assert "Subadministrador" not in profile.text
    displayed = helper.post("/conta/tag", data={"displayed_club_id": str(club_id)}, follow_redirects=False)
    assert displayed.status_code == 303
    public = owner.get("/u/papel_sup")
    assert "WC" in public.text
    assert "--tag-c1: #6C63FF" in public.text
    assert "club-tag-emojis" in public.text
    assert "club-tag-slug" in public.text
    assert ">ADM<" not in public.text
    friends_page = owner.get("/amigos")
    assert ">SUB<" not in friends_page.text


def test_last_admin_cannot_be_removed_and_owner_succession_uses_role():
    owner = TestClient(app)
    register_active(owner, "last_adm", "last.adm@example.com")
    club_id, code = _create_club(owner, "Ultimo Adm")
    db = SessionLocal()
    try:
        owner_id = db.scalar(select(User.id).where(User.username_key == "last_adm"))
    finally:
        db.close()
    blocked = owner.post(
        f"/clubs/{club_id}/membros/{owner_id}/papel",
        data={"role": "member"},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert "rebaixado" in blocked.headers["location"]
    guest = TestClient(app)
    register_active(guest, "last_mem", "last.mem@example.com")
    guest.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    left = owner.post(f"/clubs/{club_id}/leave", data={"next": "/conta"}, follow_redirects=False)
    assert left.status_code == 303
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        remaining = db.scalar(select(ClubMember).where(ClubMember.club_id == club_id))
        assert remaining.role == ROLE_ADMIN
        assert club.owner_id == remaining.user_id
    finally:
        db.close()


def test_support_join_requests_and_member_cannot_manage_tag():
    owner = TestClient(app)
    register_active(owner, "tag_host", "tag.host@example.com")
    club_id, code = _create_club(owner, "Tag Fechada", closed=True)
    helper = TestClient(app)
    register_active(helper, "tag_sup", "tag.sup@example.com")
    _request_and_accept(helper, owner, club_id, code, "tag_sup")
    member = TestClient(app)
    register_active(member, "tag_mem", "tag.mem@example.com")
    _request_and_accept(member, owner, club_id, code, "tag_mem")
    db = SessionLocal()
    try:
        helper_id = db.scalar(select(User.id).where(User.username_key == "tag_sup"))
    finally:
        db.close()
    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": "support", "support_perm": [PERM_JOINS]},
        follow_redirects=False,
    )
    no_perm = TestClient(app)
    register_active(no_perm, "tag_noperm", "tag.noperm@example.com")
    _request_and_accept(no_perm, owner, club_id, code, "tag_noperm")
    owner.post(
        f"/clubs/{club_id}/membros/{_user_id_by_key('tag_noperm')}/papel",
        data={"role": "support", "support_perm": [PERM_TAG]},
        follow_redirects=False,
    )
    waiting = TestClient(app)
    register_active(waiting, "tag_wait", "tag.wait@example.com")
    waiting.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    db = SessionLocal()
    try:
        wait_id = db.scalar(select(User.id).where(User.username_key == "tag_wait"))
    finally:
        db.close()
    member_try = member.post(f"/clubs/{club_id}/solicitacoes/{wait_id}/aceitar", follow_redirects=False)
    assert member_try.status_code == 403
    support_try = no_perm.post(f"/clubs/{club_id}/solicitacoes/{wait_id}/aceitar", follow_redirects=False)
    assert support_try.status_code == 403
    accepted = helper.post(f"/clubs/{club_id}/solicitacoes/{wait_id}/aceitar", follow_redirects=False)
    assert accepted.status_code == 303
    joined = waiting.get(f"/clubs/{club_id}")
    assert joined.status_code == 200
    blocked_tag = member.get(f"/clubs/{club_id}/tag", follow_redirects=False)
    assert blocked_tag.status_code == 303
    owner_tag = owner.post(
        f"/clubs/{club_id}/tag",
        data={"tag_slug": "OK", "tag_emoji": EMOJI, "tag_color_mode": "solid", "tag_color_1": "#3DDC84"},
        follow_redirects=False,
    )
    assert owner_tag.status_code == 303
    assert owner_tag.headers["location"].endswith("#tag")
    member_pick = member.post("/conta/tag", data={"displayed_club_id": str(club_id)}, follow_redirects=False)
    assert member_pick.status_code == 303
    seen = helper.get("/u/tag_mem")
    assert "--tag-c1: #3DDC84" in seen.text
    assert ">ADM<" not in seen.text
    assert ">SUB<" not in seen.text


def test_admin_and_support_caps_and_owner_stays_admin():
    owner = TestClient(app)
    register_active(owner, "cap_own", "cap.own@example.com")
    club_id, code = _create_club(owner, "Teto Cargos")
    helpers = []
    for index in range(4):
        http = TestClient(app)
        register_active(http, f"cap_h{index}", f"cap.h{index}@example.com")
        http.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
        helpers.append(http)
    db = SessionLocal()
    try:
        ids = list(db.scalars(select(User.id).where(User.username_key.in_([f"cap_h{i}" for i in range(4)]))))
        owner_id = db.scalar(select(User.id).where(User.username_key == "cap_own"))
    finally:
        db.close()
    ids = sorted(ids)
    for user_id in ids[:2]:
        granted = owner.post(
            f"/clubs/{club_id}/membros/{user_id}/papel",
            data={"role": "admin"},
            follow_redirects=False,
        )
        assert granted.status_code == 303
        assert "error=" not in granted.headers["location"]
    blocked = owner.post(
        f"/clubs/{club_id}/membros/{ids[2]}/papel",
        data={"role": "admin"},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert "3%20ADM" in blocked.headers["location"]
    owner_down = owner.post(
        f"/clubs/{club_id}/membros/{owner_id}/papel",
        data={"role": "member"},
        follow_redirects=False,
    )
    assert "rebaixado" in owner_down.headers["location"]
    db = SessionLocal()
    try:
        owner_member = db.scalar(
            select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == owner_id)
        )
        assert owner_member.role == ROLE_ADMIN
        assert admin_count_value(db, club_id) == MAX_ADMINS
    finally:
        db.close()


def admin_count_value(db, club_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(ClubMember).where(ClubMember.club_id == club_id, ClubMember.role == ROLE_ADMIN)
    )


def test_support_cap_is_seven():
    owner = TestClient(app)
    register_active(owner, "sub_own", "sub.own@example.com")
    club_id, code = _create_club(owner, "Teto Sub")
    ids = []
    for index in range(MAX_SUPPORT + 1):
        http = TestClient(app)
        register_active(http, f"sub_h{index}", f"sub.h{index}@example.com")
        http.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
        db = SessionLocal()
        try:
            ids.append(db.scalar(select(User.id).where(User.username_key == f"sub_h{index}")))
        finally:
            db.close()
    for user_id in ids[:MAX_SUPPORT]:
        granted = owner.post(
            f"/clubs/{club_id}/membros/{user_id}/papel",
            data={"role": "support", "support_perm": [PERM_TAG]},
            follow_redirects=False,
        )
        assert "error=" not in granted.headers["location"]
    blocked = owner.post(
        f"/clubs/{club_id}/membros/{ids[-1]}/papel",
        data={"role": "support", "support_perm": [PERM_TAG]},
        follow_redirects=False,
    )
    assert "7%20SUB" in blocked.headers["location"]


def test_member_limit_blocks_join_and_accept_without_kicking():
    owner = TestClient(app)
    register_active(owner, "lim_own", "lim.own@example.com")
    club_id, code = _create_club(owner, "Lotacao", closed=True)
    saved = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Lotacao",
            "description": "",
            "rules": "",
            "cover_color": "#3A2348",
            "is_closed": "1",
            "admin_name_color": "#FF5D8F",
            "sub_name_color": "#3DDC84",
            "member_limit": "1",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    settings = owner.get(f"/clubs/{club_id}/config")
    assert 'name="admin_name_color"' in settings.text
    assert 'name="sub_name_color"' in settings.text
    assert "Gerenciar cargos" in settings.text
    assert ">SUB<" in settings.text
    guest = TestClient(app)
    register_active(guest, "lim_g", "lim.g@example.com")
    joined = guest.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    assert joined.status_code == 303
    assert joined.headers["location"].startswith(f"/clubs/{club_id}")
    assert "lotado" not in joined.headers["location"]
    waiting = TestClient(app)
    register_active(waiting, "lim_w", "lim.w@example.com")
    waiting.post(f"/clubs/{club_id}/solicitar", data={"next": f"/clubs/{club_id}"}, follow_redirects=False)
    db = SessionLocal()
    try:
        wait_id = db.scalar(select(User.id).where(User.username_key == "lim_w"))
        helper_id = db.scalar(select(User.id).where(User.username_key == "lim_g"))
        club = db.get(Club, club_id)
        assert club.member_limit == 1
        assert club.admin_name_color == "#FF5D8F"
        assert club.sub_name_color == "#3DDC84"
        assert db.scalar(select(func.count()).select_from(ClubMember).where(ClubMember.club_id == club_id)) == 1
        assert db.scalar(select(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == helper_id))
        assert db.scalar(select(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == wait_id))
    finally:
        db.close()
    accepted = owner.post(f"/clubs/{club_id}/solicitacoes/{wait_id}/aceitar", follow_redirects=False)
    assert accepted.status_code == 303
    assert "lotado" in accepted.headers["location"]
    db = SessionLocal()
    try:
        assert db.scalar(select(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.user_id == wait_id))
    finally:
        db.close()
    owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Lotacao",
            "description": "",
            "rules": "",
            "cover_color": "#3A2348",
            "is_closed": "1",
            "admin_name_color": "#FF5D8F",
            "sub_name_color": "#3DDC84",
            "member_limit": "3",
        },
        follow_redirects=False,
    )
    owner.post(f"/clubs/{club_id}/solicitacoes/{helper_id}/aceitar", follow_redirects=False)
    owner.post(f"/clubs/{club_id}/solicitacoes/{wait_id}/aceitar", follow_redirects=False)
    owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Lotacao",
            "description": "",
            "rules": "",
            "cover_color": "#3A2348",
            "is_closed": "1",
            "admin_name_color": "#FF5D8F",
            "sub_name_color": "#3DDC84",
            "member_limit": "1",
        },
        follow_redirects=False,
    )
    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(ClubMember).where(ClubMember.club_id == club_id)) == 3
        assert db.get(Club, club_id).member_limit == 1
    finally:
        db.close()
    room = owner.get(f"/clubs/{club_id}")
    assert "--club-admin-color: #FF5D8F" in room.text
    assert "--club-sub-color: #3DDC84" in room.text
    profile = owner.get("/u/lim_own")
    assert "--club-admin-color" not in profile.text
    assert ">ADM<" not in profile.text
    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": "support", "support_perm": [PERM_JOINS]},
        follow_redirects=False,
    )


def test_last_open_seat_serializes_with_immediate_lock():
    owner = TestClient(app)
    register_active(owner, "race_own", "race.own@example.com")
    club_id, code = _create_club(owner, "Corrida")
    owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Corrida",
            "description": "",
            "rules": "",
            "cover_color": "#3A2348",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "member_limit": "2",
        },
        follow_redirects=False,
    )
    clients = []
    for index in range(2):
        http = TestClient(app)
        register_active(http, f"race_u{index}", f"race.u{index}@example.com")
        clients.append(http)

    def try_join(http: TestClient):
        return http.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_join, clients))
    db = SessionLocal()
    try:
        total = db.scalar(select(func.count()).select_from(ClubMember).where(ClubMember.club_id == club_id))
        assert total == 2
    finally:
        db.close()
    locations = [item.headers["location"] for item in results]
    assert any("lotado" in location for location in locations)
    assert any("/clubs/" in location and "error=" not in location for location in locations)


def test_club_settings_shell_sections_and_create_stays_linear():
    owner = TestClient(app)
    register_active(owner, "shell_own", "shell.own@example.com")
    create_page = owner.get("/clubs/novo")
    assert "settings-overlay-root" not in create_page.text
    assert "Cargos e permissões" not in create_page.text
    assert "novas entradas precisam de aprovação" in create_page.text
    assert "só entra com código" not in create_page.text
    club_id, _code = _create_club(owner, "Shell Club")
    settings = owner.get(f"/clubs/{club_id}/config")
    assert settings.status_code == 200
    assert "settings-overlay" in settings.text
    assert "settings-overlay-root" in settings.text
    assert "settings-close" in settings.text
    assert "js-club-settings" in settings.text
    assert "js-settings-link" in settings.text
    assert "Personalização" in settings.text
    assert "Gerenciamento" in settings.text
    assert "Voltar ao clube" in settings.text
    assert settings.text.count('class="club-settings-link js-settings-link"') == 5
    assert "Cargos e permissões" in settings.text
    assert 'data-section="tag"' in settings.text
    assert "Cor dos administradores" in settings.text
    assert "Cor dos subadministradores" in settings.text
    assert "id=\"admin-color-dialog\"" in settings.text
    assert "js-role-color-draft" in settings.text
    assert "Sem limite" in settings.text
    assert "Limitar a" in settings.text
    assert "Fundo do clube" in settings.text
    assert "Tag do clube" in settings.text
    assert 'name="cover_color"' in settings.text
    assert 'name="is_closed"' in settings.text
    assert "novas entradas precisam de aprovação" in settings.text
    assert 'name="member_limit"' in settings.text
    roles_open = settings.text.split('id="roles-dialog"', 1)[1].split(">", 1)[0]
    assert "open" not in roles_open
    saved_members = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Shell Club",
            "description": "",
            "rules": "",
            "cover_color": "#3A2348",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "member_limit": "12",
            "settings_section": "membros",
        },
        follow_redirects=False,
    )
    assert saved_members.headers["location"].endswith("#membros")
    saved_look = owner.post(
        f"/clubs/{club_id}/config",
        data={
            "name": "Shell Club",
            "description": "",
            "rules": "",
            "cover_color": "#246B45",
            "admin_name_color": "#B892FF",
            "sub_name_color": "#6C63FF",
            "member_limit": "12",
            "settings_section": "aparencia",
        },
        follow_redirects=False,
    )
    assert saved_look.headers["location"].endswith("#aparencia")
    db = SessionLocal()
    try:
        club = db.get(Club, club_id)
        assert club.cover_color == "#246B45"
        assert club.member_limit == 12
        assert not club.is_closed
    finally:
        db.close()


def test_club_chat_profile_context_and_grouped_members():
    owner = TestClient(app)
    register_active(owner, "id_adm", "id.adm@example.com", name="Ana Adm")
    club_id, code = _create_club(owner, "Identidade")
    other_id, _other_code = _create_club(owner, "Outro Clube")
    helper = TestClient(app)
    register_active(helper, "id_sup", "id.sup@example.com", name="Bia Sub")
    member = TestClient(app)
    register_active(member, "id_mem", "id.mem@example.com", name="Caio Mem")
    helper.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    db = SessionLocal()
    try:
        helper_id = db.scalar(select(User.id).where(User.username_key == "id_sup"))
    finally:
        db.close()
    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": "support", "support_perm": [PERM_TAG]},
        follow_redirects=False,
    )
    sent = helper.post(f"/clubs/{club_id}/mensagens", data={"body": "oi do chat"}, follow_redirects=False)
    assert sent.status_code == 303
    room = owner.get(f"/clubs/{club_id}?aba=chat")
    chat = room.text.split('class="chat-log"', 1)[1].split('class="chat-form"', 1)[0]
    assert "oi do chat" in chat
    assert "club-role" not in chat
    assert ">ADM<" not in chat
    assert ">SUB<" not in chat
    assert "@id_sup" not in chat
    assert "@id_adm" not in chat
    assert "club-person-name is-support" in chat
    assert f'/u/id_sup?clube={club_id}' in chat
    assert "ADMINISTRADORES — 1" in room.text
    assert "SUBADMINISTRADORES — 1" in room.text
    assert "MEMBROS — 1" in room.text
    assert ">SUB<" not in room.text
    settings = owner.get(f"/clubs/{club_id}/config")
    assert ">ADM<" in settings.text
    assert ">SUB<" in settings.text

    people = owner.get(f"/clubs/{club_id}/membros")
    assert "ADMINISTRADORES — 1" in people.text
    assert "SUBADMINISTRADORES — 1" in people.text
    assert "MEMBROS — 1" in people.text
    assert "club-role" not in people.text
    assert f'/u/id_mem?clube={club_id}' in people.text

    solo = owner.get(f"/clubs/{other_id}/membros")
    assert "ADMINISTRADORES — 1" in solo.text
    assert "SUBADMINISTRADORES" not in solo.text
    assert "MEMBROS —" not in solo.text

    global_profile = owner.get("/u/id_sup")
    assert "profile-club-context" not in global_profile.text
    assert ">SUB<" not in global_profile.text

    contextual = owner.get(f"/u/id_sup?clube={club_id}")
    assert "profile-club-context" in contextual.text
    assert "Identidade" in contextual.text
    assert 'class="profile-club-context-role">Subadministrador</span>' in contextual.text

    member_ctx = owner.get(f"/u/id_mem?clube={club_id}")
    assert 'class="profile-club-context-role">Membro</span>' in member_ctx.text

    outsider = TestClient(app)
    register_active(outsider, "id_out", "id.out@example.com")
    leaked = outsider.get(f"/u/id_sup?clube={club_id}")
    assert leaked.status_code == 200
    assert "Subadministrador" not in leaked.text
    assert "profile-club-context" not in leaked.text

    wrong_club = owner.get(f"/u/id_sup?clube={other_id}")
    assert "Subadministrador" not in wrong_club.text
    assert "profile-club-context" not in wrong_club.text
    bogus = owner.get("/u/id_sup?clube=abc")
    assert "profile-club-context" not in bogus.text
    missing = owner.get("/u/id_sup?clube=999999")
    assert "profile-club-context" not in missing.text
