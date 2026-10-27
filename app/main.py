from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.accounts import (
    create_user,
    email_taken,
    find_user_by_email,
    find_valid_reset,
    login_or_create_oauth,
    normalize_email,
    send_activation,
    send_password_reset,
    utcnow,
)
from app.avatar_uploads import delete_upload, save_avatar_photo
from app.avatars import (
    AVATARS,
    avatar_initials,
    avatar_url,
    illustrated_catalogs,
    parse_illustrated_choice,
    set_illustrated_avatar,
    set_upload_avatar,
    valid_avatar,
)
from app.catalog import (
    CONTENT_KINDS,
    add_club_member,
    add_manual_title,
    add_show_to_club,
    accept_join_request,
    admin_count,
    apply_member_role,
    club_membership,
    club_messages,
    create_join_request,
    club_rating_stats,
    fill_missing_genres,
    is_club_admin,
    leave_club as remove_club_membership,
    load_show,
    parse_genres,
    parse_member_limit,
    list_join_requests,
    pending_join_request,
    post_club_message,
    refresh_news,
    reject_join_request,
    requested_club_ids,
    remove_show_from_club,
    require_club_admin,
    require_club_perm,
    require_club_member,
    set_club_show_rating,
    set_watch_status,
    support_count,
    upsert_show_from_tvmaze,
    valid_kind,
    valid_stars,
)
from app.club_tags import (
    TAG_BG_DEFAULT,
    TAG_BG_MAX,
    TAG_BG_MIN,
    TAG_BORDER_DEFAULT,
    TAG_BORDER_MAX,
    TAG_BORDER_MIN,
    TAG_POSITION_DEFAULT,
    apply_club_tag,
    clear_tag_preferences,
    club_has_tag,
    selectable_tags,
    set_displayed_club,
    stamp_display_tags,
    tag_payload,
)
from app.colors import COLOR_PRESETS, DEFAULT_HEX, GRADIENT_DIRECTIONS, valid_hex
from app.club_icons import club_icon_initials, club_icon_url, delete_club_icon, save_club_icon
from app.discovery import (
    KIND_LABELS,
    MAX_CATEGORIES,
    MAX_TAGS,
    TAG_LABEL_MAX,
    apply_club_discovery,
    club_discovery_state,
    grouped_catalog,
    load_catalog,
)
from app.covers import COVER_COLORS, COVER_PRESETS, cover_image_url, save_cover_image, valid_cover_color
from app.markup import format_chat
from app import config as app_config
from app.config import BASE_DIR, BIO_MAX, EMAIL_DEV_SHOW_LINK, SECRET_KEY
from app.db import Base, close_exclusive_session, engine, exclusive_write_session, get_db
from app.invites import (
    MSG_OAUTH_CLOSED,
    MSG_USED,
    InviteSignupBlocked,
    lookup_invite,
    mark_invite_used,
)
from app.mail import MAIL_ERROR_MESSAGE, MailDeliveryError
from app.friends import (
    accept_invite,
    can_view_thread,
    decline_invite,
    dm_thread,
    find_active_user,
    friend_id_set,
    has_dm_history,
    incoming_invites,
    list_friends,
    person_href,
    post_dm,
    relation_status,
    send_invite,
    unfriend,
)
from app.models import AccountInvite, Club, ClubMember, ClubShow, EmailToken, User
from app.oauth import (
    facebook_authorize_url,
    facebook_enabled,
    fetch_facebook_profile,
    fetch_google_profile,
    google_authorize_url,
    google_enabled,
    new_state,
)
from app.presence import LABELS as PRESENCE_LABELS
from app.presence import mark_logout, presence_of, touch_presence
from app.roles import (
    MAX_ADMINS,
    MAX_SUPPORT,
    PERM_JOINS,
    PERM_PROGRESS,
    PERM_SCHEDULES,
    PERM_TAG,
    PERM_TITLES,
    ROLE_ADMIN,
    ROLE_LABELS,
    ROLE_MEMBER,
    ROLE_SUPPORT,
    SUPPORT_PERM_LABELS,
    SUPPORT_PERMS,
    can,
    member_role,
    parse_support_perms,
)
from app.progress import mark_episode_watched, pick_season, progress_snapshot, unmark_episode
from app.schedules import (
    cancel_schedule,
    create_schedule,
    format_episode_line,
    format_schedule_when,
    format_week_line,
    list_upcoming_schedules,
    list_week_schedules,
)
from app.schema import migrate_schema
from app.security import hash_password, make_join_code, verify_password
from app.services import tvmaze
from app.usernames import (
    NICKNAME_DAYS,
    USERNAME_RE,
    nickname_can_change,
    nickname_unlock_at,
    normalize_username,
    suggest_usernames,
    taken_keys,
    username_taken,
)

Base.metadata.create_all(bind=engine)
migrate_schema()
(BASE_DIR / "app" / "static" / "avatars").mkdir(parents=True, exist_ok=True)
for _avatar in AVATARS:
    (BASE_DIR / "app" / "static" / "avatars" / f"{_avatar['id']}.svg").write_text(_avatar["svg"], encoding="utf-8")


app = FastAPI(title="Watch Club", description="Séries assistidas com amigos")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.globals["presence_of"] = presence_of
templates.env.globals["presence_label"] = lambda user: PRESENCE_LABELS[presence_of(user)]
templates.env.globals["avatar_initials"] = avatar_initials
templates.env.globals["avatar_url"] = avatar_url
templates.env.globals["google_enabled"] = google_enabled
templates.env.globals["facebook_enabled"] = facebook_enabled
templates.env.globals["BIO_MAX"] = BIO_MAX
templates.env.globals["COVER_COLORS"] = COVER_COLORS
templates.env.globals["COVER_PRESETS"] = COVER_PRESETS
templates.env.globals["cover_image_url"] = cover_image_url
templates.env.globals["club_icon_url"] = club_icon_url
templates.env.globals["club_icon_initials"] = club_icon_initials
templates.env.globals["MAX_CATEGORIES"] = MAX_CATEGORIES
templates.env.globals["MAX_TAGS"] = MAX_TAGS
templates.env.globals["TAG_LABEL_MAX"] = TAG_LABEL_MAX
templates.env.globals["KIND_LABELS"] = KIND_LABELS
templates.env.globals["CONTENT_KINDS"] = CONTENT_KINDS
templates.env.globals["person_href"] = person_href
templates.env.globals["COLOR_PRESETS"] = COLOR_PRESETS
templates.env.globals["DEFAULT_HEX"] = DEFAULT_HEX
templates.env.globals["GRADIENT_DIRECTIONS"] = GRADIENT_DIRECTIONS
templates.env.globals["TAG_BG_MIN"] = TAG_BG_MIN
templates.env.globals["TAG_BG_MAX"] = TAG_BG_MAX
templates.env.globals["TAG_BG_DEFAULT"] = TAG_BG_DEFAULT
templates.env.globals["TAG_BORDER_MIN"] = TAG_BORDER_MIN
templates.env.globals["TAG_BORDER_MAX"] = TAG_BORDER_MAX
templates.env.globals["TAG_BORDER_DEFAULT"] = TAG_BORDER_DEFAULT
templates.env.globals["TAG_POSITION_DEFAULT"] = TAG_POSITION_DEFAULT
templates.env.globals["SUPPORT_PERMS"] = SUPPORT_PERMS
templates.env.globals["SUPPORT_PERM_LABELS"] = SUPPORT_PERM_LABELS
templates.env.globals["ROLE_LABELS"] = ROLE_LABELS
templates.env.globals["MAX_ADMINS"] = MAX_ADMINS
templates.env.globals["MAX_SUPPORT"] = MAX_SUPPORT
templates.env.globals["member_role"] = member_role
templates.env.globals["parse_support_perms"] = parse_support_perms
templates.env.filters["when"] = lambda value: value.strftime("%d/%m/%Y %H:%M") if value else ""
templates.env.filters["schedule_when"] = format_schedule_when
templates.env.globals["schedule_episode_line"] = lambda item: format_episode_line(
    item.season_number, item.episode_number
)
templates.env.globals["schedule_week_line"] = format_week_line
templates.env.filters["genres"] = parse_genres
templates.env.filters["avg_pt"] = lambda value: f"{value:.1f}".replace(".", ",") if value is not None else ""
templates.env.filters["chat_format"] = format_chat


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user and not user.is_active:
        request.session.clear()
        return None
    if user:
        stamp_display_tags(db, [user])
    return user


def login_required(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Faça login")
    return user


def db_session() -> Session:
    return next(get_db())


def _safe_next(path: str | None, fallback: str = "/") -> str:
    if path and path.startswith("/") and not path.startswith("//"):
        return path
    return fallback


def _is_member(db: Session, club_id: int, user_id: int) -> bool:
    return (
        db.scalar(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id))
        is not None
    )


MEMBER_GROUP_LABELS = (
    (ROLE_ADMIN, "ADMINISTRADORES"),
    (ROLE_SUPPORT, "SUBADMINISTRADORES"),
    (ROLE_MEMBER, "MEMBROS"),
)
PROFILE_ROLE_LABELS = {
    ROLE_ADMIN: "Administrador",
    ROLE_SUPPORT: "Subadministrador",
    ROLE_MEMBER: "Membro",
}


def grouped_club_members(members) -> list[dict]:
    buckets = {ROLE_ADMIN: [], ROLE_SUPPORT: [], ROLE_MEMBER: []}
    for item in members:
        buckets[member_role(item)].append(item)
    for items in buckets.values():
        items.sort(key=lambda item: (item.user.name or "").lower())
    return [
        {"role": role, "label": label, "members": buckets[role]}
        for role, label in MEMBER_GROUP_LABELS
        if buckets[role]
    ]


def _club_profile_context(db: Session, viewer: User, person: User, raw_club_id: str | None):
    if not raw_club_id:
        return None, None, None
    try:
        club_id = int(raw_club_id)
    except (TypeError, ValueError):
        return None, None, None
    club = db.get(Club, club_id)
    if not club:
        return None, None, None
    viewer_member = club_membership(db, club_id, viewer.id)
    person_member = club_membership(db, club_id, person.id)
    if not viewer_member or not person_member:
        return None, None, None
    role = member_role(person_member)
    return club, role, PROFILE_ROLE_LABELS[role]


def _load_club(db: Session, club_id: int) -> Club | None:
    return db.scalar(
        select(Club)
        .options(
            selectinload(Club.members).selectinload(ClubMember.user),
            selectinload(Club.shows).selectinload(ClubShow.show),
        )
        .where(Club.id == club_id)
    )


def _account_extras(user: User) -> dict:
    now = utcnow()
    locked = not nickname_can_change(user.username_changed_at, now)
    unlock = nickname_unlock_at(user.username_changed_at)
    return {
        "nickname_locked": locked,
        "nickname_unlock": unlock.strftime("%d/%m/%Y") if locked and unlock else None,
        "nickname_days": NICKNAME_DAYS,
    }


SETTINGS_SECTIONS = ("geral", "aparencia", "descoberta", "tag", "cargos", "membros")


def _settings_section(raw: str | None) -> str:
    text = (raw or "").strip().lstrip("#").lower()
    return text if text in SETTINGS_SECTIONS else "geral"


def _config_href(club_id: int, section: str = "geral", *, ok: str | None = None, error: str | None = None) -> str:
    chosen = _settings_section(section)
    query = []
    if ok:
        query.append(f"ok={quote(ok)}")
    if error:
        query.append(f"error={quote(error)}")
    path = f"/clubs/{club_id}/config"
    if query:
        path += "?" + "&".join(query)
    return f"{path}#{chosen}"


def _club_settings_context(db: Session, request: Request, user: User, club: Club, **extra):
    loaded = _load_club(db, club.id) or club
    members = sorted(loaded.members, key=lambda item: item.user.name.lower())
    stamp_display_tags(db, [item.user for item in members])
    payload = {
        "user": user,
        "club": loaded,
        "members": members,
        "member_total": len(loaded.members),
        "admin_total": admin_count(db, loaded.id),
        "support_total": support_count(db, loaded.id),
        "friend_ids": friend_id_set(db, user.id),
        "error": extra.get("error", request.query_params.get("error")),
        "ok": extra.get("ok", request.query_params.get("ok")),
        "mode": extra.get("mode", "edit"),
        "can_tag": extra.get("can_tag", True),
        "tag": extra.get("tag", tag_payload(loaded)),
        "settings_section": extra.get("settings_section"),
        "discovery_groups": extra.get("discovery_groups"),
        "discovery_selected": extra.get("discovery_selected"),
        "discovery_tags": extra.get("discovery_tags"),
    }
    if payload["discovery_groups"] is None and extra.get("mode", "edit") == "edit":
        state = club_discovery_state(db, loaded.id)
        payload["discovery_groups"] = grouped_catalog(load_catalog(db))
        payload["discovery_selected"] = extra.get("discovery_selected", state["selected_slugs"])
        payload["discovery_tags"] = extra.get("discovery_tags", state["tags"])
    payload.update(extra)
    payload["club"] = loaded
    payload["members"] = members
    payload["tag"] = extra.get("tag", tag_payload(loaded))
    return payload


def _club_caps(db: Session, club_id: int, user_id: int) -> dict:
    member = club_membership(db, club_id, user_id)
    return {
        "club_member": member,
        "is_admin": member_role(member) == ROLE_ADMIN,
        "can_tag": can(member, PERM_TAG),
        "can_joins": can(member, PERM_JOINS),
        "can_titles": can(member, PERM_TITLES),
        "can_schedules": can(member, PERM_SCHEDULES),
        "can_progress": can(member, PERM_PROGRESS),
    }


def _club_tab(aba: str | None) -> str:
    if aba == "chat":
        return "chat"
    if aba == "agendamentos":
        return "agendamentos"
    return "assistindo"


def _save_club_tag(
    db: Session,
    club: Club,
    slug: str,
    emoji: str,
    bg_intensity: str | int | None = None,
    border_intensity: str | int | None = None,
    emoji_position: str | None = None,
    color_mode: str | None = None,
    color_1: str | None = None,
    color_2: str | None = None,
    gradient_direction: str | None = None,
) -> str | None:
    had_tag = club_has_tag(club)
    error = apply_club_tag(
        club,
        slug,
        emoji,
        bg_intensity,
        border_intensity,
        emoji_position,
        color_mode,
        color_1,
        color_2,
        gradient_direction,
    )
    if error:
        return error
    if had_tag and not club_has_tag(club):
        clear_tag_preferences(db, club.id)
    return None


def _user_clubs(db: Session, user_id: int) -> list[Club]:
    return list(
        db.scalars(
            select(Club)
            .join(ClubMember)
            .where(ClubMember.user_id == user_id)
            .options(selectinload(Club.members), selectinload(Club.shows))
        ).unique()
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    db = db_session()
    try:
        user = current_user(request, db)
        clubs = _user_clubs(db, user.id) if user else []
        return templates.TemplateResponse(
            request,
            "home.html",
            {"user": user, "clubs": clubs, "error": request.query_params.get("error"), "ok": request.query_params.get("ok")},
        )
    finally:
        db.close()


@app.get("/clubes", response_class=HTMLResponse)
def clubs_index(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        return templates.TemplateResponse(
            request,
            "clubs_list.html",
            {"user": user, "clubs": _user_clubs(db, user.id)},
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return _auth_page(request, "register", request.query_params.get("error") or "", status_code=200)


def _auth_page(request: Request, mode: str, error: str, status_code: int = 400, suggestions=None, form=None):
    return templates.TemplateResponse(
        request,
        "auth.html",
        {
            "mode": mode,
            "error": error,
            "ok": "",
            "suggestions": suggestions or [],
            "form": form or {},
            "dev_code": None,
            "invite_required": app_config.REGISTRATION_INVITE_REQUIRED,
        },
        status_code=status_code,
    )


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    invite_code: str = Form(""),
):
    db = db_session()
    try:
        email = normalize_email(email)
        display = name.strip()[:80]
        form = {"name": display, "username": username, "email": email, "invite_code": invite_code}
        key = normalize_username(username)
        if not display:
            return _auth_page(request, "register", "Informe um nome.", form=form)
        if not USERNAME_RE.match(key):
            return _auth_page(
                request,
                "register",
                "O nickname precisa ter 3 a 30 caracteres (letras, números ou _).",
                form=form,
            )
        if username_taken(db, key):
            return _auth_page(
                request,
                "register",
                "Esse nickname já está em uso. Que tal um destes?",
                suggestions=suggest_usernames(key, taken_keys(db)),
                form=form,
            )
        if email_taken(db, email):
            return _auth_page(request, "register", "Este e-mail já está cadastrado", form=form)
        if not app_config.REGISTRATION_INVITE_REQUIRED:
            try:
                user = create_user(db, username, email, password, name=display)
                verify_url = send_activation(db, user)
                db.commit()
            except MailDeliveryError:
                db.rollback()
                return _auth_page(request, "register", MAIL_ERROR_MESSAGE, form=form)
            if EMAIL_DEV_SHOW_LINK:
                request.session["verify_link"] = verify_url
            return RedirectResponse("/verificar-email", status_code=303)

        write = exclusive_write_session(db)
        try:
            _invite, invite_error = lookup_invite(write, invite_code)
            if invite_error:
                return _auth_page(request, "register", invite_error, form=form)
            user = create_user(write, username, email, password, name=display)
            if not mark_invite_used(write, _invite, user.id):
                write.rollback()
                return _auth_page(request, "register", MSG_USED, form=form)
            verify_url = send_activation(write, user)
            write.commit()
        except MailDeliveryError:
            write.rollback()
            return _auth_page(request, "register", MAIL_ERROR_MESSAGE, form=form)
        except Exception:
            write.rollback()
            raise
        finally:
            close_exclusive_session(write)
        if EMAIL_DEV_SHOW_LINK:
            request.session["verify_link"] = verify_url
        return RedirectResponse("/verificar-email", status_code=303)
    finally:
        db.close()


@app.get("/verificar-email", response_class=HTMLResponse)
def verify_email_page(request: Request, token: str | None = None):
    db = db_session()
    try:
        if token:
            record = db.scalar(select(EmailToken).where(EmailToken.token == token))
            if not record or record.expires_at < utcnow() or record.purpose == "reset":
                return templates.TemplateResponse(
                    request,
                    "verify.html",
                    {"user": None, "error": "Link inválido ou expirado. Peça um novo e-mail.", "ok": None, "verify_link": None},
                    status_code=400,
                )
            user = db.get(User, record.user_id)
            if record.purpose == "email_change" and record.new_email:
                taken = email_taken(db, record.new_email or "", exclude_user_id=user.id)
                if taken:
                    db.delete(record)
                    db.commit()
                    return templates.TemplateResponse(
                        request,
                        "verify.html",
                        {"user": None, "error": "Este e-mail já pertence a outra conta.", "ok": None, "verify_link": None},
                        status_code=400,
                    )
                user.email = record.new_email
                user.pending_email = None
            user.is_active = True
            db.delete(record)
            db.commit()
            request.session["user_id"] = user.id
            request.session.pop("verify_link", None)
            return RedirectResponse("/?ok=Conta+ativada", status_code=303)
        return templates.TemplateResponse(
            request,
            "verify.html",
            {
                "user": current_user(request, db),
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
                "verify_link": request.session.get("verify_link") if EMAIL_DEV_SHOW_LINK else None,
            },
        )
    finally:
        db.close()


@app.post("/verificar-email/reenviar")
def resend_verification(request: Request, email: str = Form(...)):
    db = db_session()
    try:
        user = find_user_by_email(db, email)
        if user and not user.is_active:
            try:
                verify_url = send_activation(db, user)
                db.commit()
            except MailDeliveryError:
                db.rollback()
                return RedirectResponse("/verificar-email?error=" + quote(MAIL_ERROR_MESSAGE), status_code=303)
            if EMAIL_DEV_SHOW_LINK:
                request.session["verify_link"] = verify_url
        return RedirectResponse("/verificar-email?ok=Se+o+e-mail+existir,+enviamos+um+novo+link", status_code=303)
    finally:
        db.close()


def _reset_page(request: Request, mode: str, error: str = "", ok: str = "", form=None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "auth.html",
        {
            "mode": mode,
            "error": error,
            "ok": ok,
            "suggestions": [],
            "form": form or {},
            "dev_code": request.session.get("reset_code") if EMAIL_DEV_SHOW_LINK else None,
        },
        status_code=status_code,
    )


@app.get("/recuperar-senha", response_class=HTMLResponse)
def forgot_password_form(request: Request):
    return _reset_page(
        request,
        "forgot",
        error=request.query_params.get("error") or "",
        ok=request.query_params.get("ok") or "",
        form={"email": request.session.get("reset_email") or ""},
    )


@app.post("/recuperar-senha")
def forgot_password(request: Request, email: str = Form(...)):
    db = db_session()
    try:
        address = normalize_email(email)
        user = find_user_by_email(db, address)
        request.session["reset_email"] = address
        request.session.pop("reset_code", None)
        if user:
            try:
                code = send_password_reset(db, user)
                db.commit()
            except MailDeliveryError:
                db.rollback()
                return _reset_page(
                    request,
                    "forgot",
                    error=MAIL_ERROR_MESSAGE,
                    form={"email": address},
                    status_code=400,
                )
            if EMAIL_DEV_SHOW_LINK:
                request.session["reset_code"] = code
        return RedirectResponse("/recuperar-senha/codigo", status_code=303)
    finally:
        db.close()


@app.get("/recuperar-senha/codigo", response_class=HTMLResponse)
def reset_code_form(request: Request):
    email = request.session.get("reset_email")
    if not email:
        return RedirectResponse("/recuperar-senha", status_code=303)
    return _reset_page(
        request,
        "reset",
        error=request.query_params.get("error") or "",
        ok=request.query_params.get("ok") or "",
        form={"email": email},
    )


@app.post("/recuperar-senha/codigo")
def reset_password(
    request: Request,
    code: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    db = db_session()
    try:
        email = request.session.get("reset_email") or ""
        if not email:
            return RedirectResponse("/recuperar-senha", status_code=303)
        if len(new_password) < 4:
            return _reset_page(
                request,
                "reset",
                error="A nova senha precisa ter pelo menos 4 caracteres.",
                form={"email": email},
                status_code=400,
            )
        if new_password != confirm_password:
            return _reset_page(
                request,
                "reset",
                error="A confirmação da senha não confere.",
                form={"email": email},
                status_code=400,
            )
        record = find_valid_reset(db, email, code)
        if not record:
            return _reset_page(
                request,
                "reset",
                error="Código inválido ou expirado. Peça um novo código.",
                form={"email": email},
                status_code=400,
            )
        user = db.get(User, record.user_id)
        if not user:
            return _reset_page(
                request,
                "reset",
                error="Código inválido ou expirado. Peça um novo código.",
                form={"email": email},
                status_code=400,
            )
        user.password_hash = hash_password(new_password)
        user.is_active = True
        db.delete(record)
        request.session.pop("reset_email", None)
        request.session.pop("reset_code", None)
        request.session["user_id"] = user.id
        touch_presence(user, "online")
        db.commit()
        return RedirectResponse("/?ok=Senha+redefinida", status_code=303)
    finally:
        db.close()


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return _auth_page(request, "login", request.query_params.get("error") or "", status_code=200)


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    db = db_session()
    try:
        user = find_user_by_email(db, email)
        if not user or not user.password_hash or not verify_password(password, user.password_hash):
            return _auth_page(request, "login", "E-mail ou senha inválidos", form={"email": email})
        if not user.is_active:
            try:
                verify_url = send_activation(db, user)
                db.commit()
            except MailDeliveryError:
                db.rollback()
                return _auth_page(request, "login", MAIL_ERROR_MESSAGE, form={"email": email})
            if EMAIL_DEV_SHOW_LINK:
                request.session["verify_link"] = verify_url
            return RedirectResponse("/verificar-email?error=Ative+sua+conta+pelo+e-mail", status_code=303)
        request.session["user_id"] = user.id
        touch_presence(user, "online")
        db.commit()
        return RedirectResponse("/", status_code=303)
    finally:
        db.close()


@app.post("/logout")
def logout(request: Request):
    db = db_session()
    try:
        user = current_user(request, db)
        if user:
            mark_logout(user)
            db.commit()
    finally:
        db.close()
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/auth/{provider}")
def oauth_start(request: Request, provider: str):
    if provider == "google":
        if not google_enabled():
            return RedirectResponse("/login?error=Configure+GOOGLE_CLIENT_ID+e+SECRET+no+.env", status_code=303)
        state = new_state()
        request.session["oauth_state"] = state
        request.session["oauth_provider"] = "google"
        return RedirectResponse(google_authorize_url(state), status_code=303)
    if provider == "facebook":
        if not facebook_enabled():
            return RedirectResponse("/login?error=Configure+FACEBOOK_CLIENT_ID+e+SECRET+no+.env", status_code=303)
        state = new_state()
        request.session["oauth_state"] = state
        request.session["oauth_provider"] = "facebook"
        return RedirectResponse(facebook_authorize_url(state), status_code=303)
    return RedirectResponse("/login?error=Provedor+inválido", status_code=303)


@app.get("/auth/{provider}/callback")
def oauth_callback(request: Request, provider: str, code: str | None = None, state: str | None = None):
    if not code or state != request.session.get("oauth_state") or provider != request.session.get("oauth_provider"):
        return RedirectResponse("/login?error=Login+social+cancelado+ou+inválido", status_code=303)
    db = db_session()
    try:
        try:
            profile = fetch_google_profile(code) if provider == "google" else fetch_facebook_profile(code)
            user = login_or_create_oauth(db, profile)
            touch_presence(user, "online")
            db.commit()
        except InviteSignupBlocked:
            return RedirectResponse("/register?error=" + quote(MSG_OAUTH_CLOSED), status_code=303)
        except Exception:
            return RedirectResponse("/login?error=Não+foi+possível+entrar+com+essa+conta", status_code=303)
        request.session.pop("oauth_state", None)
        request.session.pop("oauth_provider", None)
        request.session["user_id"] = user.id
        return RedirectResponse("/", status_code=303)
    finally:
        db.close()


@app.get("/clubs/novo", response_class=HTMLResponse)
def new_club_form(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        return templates.TemplateResponse(
            request,
            "club_form.html",
            {"user": user, "club": None, "error": None, "mode": "create"},
        )
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/clubs")
async def create_club(
    request: Request,
    name: str = Form(...),
    is_closed: str | None = Form(None),
    description: str = Form(""),
    rules: str = Form(""),
    cover_color: str = Form("#3a2348"),
    cover_file: UploadFile | None = File(None),
    icon_file: UploadFile | None = File(None),
):
    db = db_session()
    try:
        user = login_required(request, db)
        image_name = await save_cover_image(cover_file)
        icon_name = await save_club_icon(icon_file)
        club = Club(
            name=name.strip(),
            join_code=make_join_code(),
            owner_id=user.id,
            is_closed=bool(is_closed),
            description=description.strip(),
            rules=rules.strip(),
            cover_color=valid_cover_color(cover_color),
            cover_image=image_name,
            icon_image=icon_name,
        )
        db.add(club)
        db.flush()
        db.add(ClubMember(club_id=club.id, user_id=user.id, role=ROLE_ADMIN, support_perms=""))
        db.commit()
        return RedirectResponse(f"/clubs/{club.id}", status_code=303)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.get("/conta", response_class=HTMLResponse)
def account(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        return templates.TemplateResponse(
            request,
            "account.html",
            {
                "user": user,
                "clubs": _user_clubs(db, user.id),
                "tag_choices": selectable_tags(db, user.id),
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
                "suggestions": [],
                "avatar_groups": illustrated_catalogs(),
                **_account_extras(user),
            },
        )
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/conta/perfil")
def update_profile(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    bio: str = Form(""),
    name: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        key = normalize_username(username)
        display = name.strip()[:80]
        email = normalize_email(email)
        clubs = _user_clubs(db, user.id)
        groups = illustrated_catalogs()

        def account_error(message: str, suggestions=None):
            return templates.TemplateResponse(
                request,
                "account.html",
                {
                    "user": user,
                    "clubs": clubs,
                    "tag_choices": selectable_tags(db, user.id),
                    "error": message,
                    "ok": None,
                    "suggestions": suggestions or [],
                    "avatar_groups": groups,
                    **_account_extras(user),
                },
                status_code=400,
            )

        if not display:
            return account_error("Informe um nome.")
        if not USERNAME_RE.match(key):
            return account_error("O nickname precisa ter 3 a 30 caracteres (letras, números ou _).")
        nick_changed = key != user.username_key
        if nick_changed:
            if not nickname_can_change(user.username_changed_at, utcnow()):
                unlock = nickname_unlock_at(user.username_changed_at)
                when = unlock.strftime("%d/%m/%Y") if unlock else ""
                return account_error(f"O nickname só pode ser alterado a cada {NICKNAME_DAYS} dias. Tente de novo em {when}.")
            if username_taken(db, key, exclude_user_id=user.id):
                return account_error(
                    "Esse nickname já está em uso. Sugestões:",
                    suggest_usernames(key, taken_keys(db) - {user.username_key}),
                )
        if email_taken(db, email, exclude_user_id=user.id):
            return account_error("Este e-mail já está em uso")
        user.name = display
        if nick_changed:
            user.username = key
            user.username_key = key
            user.username_changed_at = utcnow()
        user.bio = (bio or "")[:BIO_MAX]
        if email != user.email:
            user.pending_email = email
            try:
                verify_url = send_activation(db, user, new_email=email)
                db.commit()
            except MailDeliveryError:
                db.rollback()
                return account_error(MAIL_ERROR_MESSAGE)
            if EMAIL_DEV_SHOW_LINK:
                request.session["verify_link"] = verify_url
            return RedirectResponse(
                "/verificar-email?ok=Confirme+o+novo+e-mail+para+concluir+a+troca",
                status_code=303,
            )
        db.commit()
        return RedirectResponse("/conta?ok=Perfil+atualizado", status_code=303)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/conta/avatar")
def update_avatar(
    request: Request,
    choice: str = Form(""),
    provider: str = Form(""),
    value: str = Form(""),
    avatar: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        parsed = parse_illustrated_choice(choice, provider, value)
        if not parsed and avatar:
            parsed = parse_illustrated_choice(f"watchclub:{valid_avatar(avatar)}")
        if not parsed:
            return RedirectResponse("/conta?error=Escolha+um+avatar+valido", status_code=303)
        if user.avatar_type == "upload":
            delete_upload(user.avatar_value)
        set_illustrated_avatar(user, parsed[0], parsed[1])
        db.commit()
        return RedirectResponse("/conta?ok=Foto+de+perfil+atualizada", status_code=303)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/conta/avatar/foto")
async def update_avatar_photo(request: Request, photo: UploadFile | None = File(None)):
    db = db_session()
    try:
        user = login_required(request, db)
        filename = await save_avatar_photo(photo)
        if not filename:
            return RedirectResponse("/conta?error=Envie+uma+imagem+JPG,+PNG,+WEBP+ou+GIF", status_code=303)
        if user.avatar_type == "upload":
            delete_upload(user.avatar_value)
        set_upload_avatar(user, filename)
        db.commit()
        return RedirectResponse("/conta?ok=Foto+de+perfil+atualizada", status_code=303)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/conta/senha")
def update_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    db = db_session()
    try:
        user = login_required(request, db)
        has_password = bool(user.password_hash)
        if has_password and not verify_password(current_password, user.password_hash):
            return RedirectResponse("/conta?error=Senha+atual+incorreta", status_code=303)
        if len(new_password) < 4:
            return RedirectResponse("/conta?error=A+nova+senha+precisa+ter+pelo+menos+4+caracteres", status_code=303)
        if new_password != confirm_password:
            return RedirectResponse("/conta?error=A+confirmação+da+senha+não+confere", status_code=303)
        user.password_hash = hash_password(new_password)
        db.commit()
        return RedirectResponse("/conta?ok=Senha+alterada", status_code=303)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/clubs/join")
def join_club(request: Request, join_code: str = Form(...), next: str = Form("/")):
    db = db_session()
    next_url = _safe_next(next)
    try:
        user = login_required(request, db)
        club = db.scalar(select(Club).where(Club.join_code == join_code.strip().upper()))
        if not club:
            sep = "&" if "?" in next_url else "?"
            return RedirectResponse(f"{next_url}{sep}error=Código+inválido", status_code=303)
        if club_membership(db, club.id, user.id):
            if next_url.startswith("/conta"):
                return RedirectResponse(
                    f"/conta?ok={quote('Você já participa do clube ' + club.name)}",
                    status_code=303,
                )
            return RedirectResponse(f"/clubs/{club.id}", status_code=303)
        if club.is_closed:
            create_join_request(db, club, user.id)
            db.commit()
            return RedirectResponse(
                f"/clubs/{club.id}?ok={quote('Pedido enviado')}",
                status_code=303,
            )
        add_club_member(db, club.id, user.id, clear_request=True)
        if next_url.startswith("/conta"):
            return RedirectResponse(
                f"/conta?ok={quote('Você entrou no clube ' + club.name)}",
                status_code=303,
            )
        return RedirectResponse(f"/clubs/{club.id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        sep = "&" if "?" in next_url else "?"
        return RedirectResponse(f"{next_url}{sep}error={quote(str(exc.detail))}", status_code=303)
    finally:
        db.close()


@app.post("/clubs/{club_id}/leave")
def leave_club_route(request: Request, club_id: int, next: str = Form("/conta")):
    db = db_session()
    try:
        user = login_required(request, db)
        message = remove_club_membership(db, club_id, user.id)
        dest = _safe_next(next, "/conta")
        sep = "&" if "?" in dest else "?"
        return RedirectResponse(f"{dest}{sep}ok={quote(message)}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(f"/conta?error={quote(str(exc.detail))}", status_code=303)
    finally:
        db.close()


@app.post("/clubs/{club_id}/entrar")
def join_open_club(request: Request, club_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        club = db.get(Club, club_id)
        if not club:
            raise HTTPException(status_code=404, detail="Clube não encontrado")
        if club.is_closed:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        if not _is_member(db, club.id, user.id):
            add_club_member(db, club.id, user.id)
        return RedirectResponse(f"/clubs/{club.id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(f"/clubs/{club_id}?error={quote(str(exc.detail))}", status_code=303)
        raise
    finally:
        db.close()


@app.get("/clubs/{club_id}", response_class=HTMLResponse)
async def club_detail(
    request: Request,
    club_id: int,
    q: str | None = Query(None),
    aba: str | None = Query(None),
    lista: str | None = Query(None),
):
    db = db_session()
    try:
        user = login_required(request, db)
        club = _load_club(db, club_id)
        if not club:
            raise HTTPException(status_code=404, detail="Clube não encontrado")
        member = _is_member(db, club.id, user.id)
        if not member and club.is_closed:
            return templates.TemplateResponse(
                request,
                "club_locked.html",
                {
                    "user": user,
                    "club": club,
                    "join_pending": pending_join_request(db, club.id, user.id) is not None,
                    "ok": request.query_params.get("ok"),
                    "error": request.query_params.get("error"),
                },
                status_code=403,
            )
        if not member:
            return templates.TemplateResponse(
                request,
                "club_preview.html",
                {"user": user, "club": club},
            )
        tab = _club_tab(aba)
        results = await tvmaze.search_shows(q) if tab == "assistindo" and q else []
        watching = [link for link in club.shows if (link.watch_status or "watching") != "watched"]
        watched = [link for link in club.shows if link.watch_status == "watched"]
        schedules = list_upcoming_schedules(db, club.id) if tab == "agendamentos" else []
        week_schedules = list_week_schedules(db, club.id) if tab == "assistindo" else []
        if tab == "assistindo":
            await fill_missing_genres(db, [link.show for link in club.shows])
            db.commit()
        ratings = club_rating_stats(db, club.id, user.id)
        caps = _club_caps(db, club.id, user.id)
        progress_by_show = {}
        if tab == "assistindo":
            progress_by_show = {
                link.show_id: progress_snapshot(db, club.id, link.show_id) for link in club.shows
            }
        members = list(club.members)
        messages = club_messages(db, club.id) if tab == "chat" else []
        stamp_display_tags(db, [item.user for item in members] + [item.user for item in messages])
        online_count = sum(1 for item in members if presence_of(item.user) == "online")
        join_requests = list_join_requests(db, club.id) if caps["can_joins"] and club.is_closed else []
        return templates.TemplateResponse(
            request,
            "club.html",
            {
                "user": user,
                "club": club,
                "query": q or "",
                "results": results,
                "is_member": True,
                "tab": tab,
                "watch_list": "finalizados" if lista == "finalizados" else "assistindo",
                "messages": messages,
                "watching": watching,
                "watched": watched,
                "schedules": schedules,
                "week_schedules": week_schedules,
                "progress_by_show": progress_by_show,
                "ratings": ratings,
                "friend_ids": friend_id_set(db, user.id),
                "online_count": online_count,
                "join_requests": join_requests,
                "members_by_user": {item.user_id: item for item in members},
                "member_groups": grouped_club_members(members),
                "user_clubs": sorted(_user_clubs(db, user.id), key=lambda item: (item.name or "").casefold()),
                "error": request.query_params.get("error"),
                **caps,
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.get("/clubs/{club_id}/membros", response_class=HTMLResponse)
def club_members(request: Request, club_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_member(db, club_id, user.id)
        club = _load_club(db, club_id)
        members = sorted(club.members, key=lambda item: item.user.name.lower())
        stamp_display_tags(db, [item.user for item in members])
        return templates.TemplateResponse(
            request,
            "members.html",
            {
                "user": user,
                "club": club,
                "members": members,
                "member_groups": grouped_club_members(members),
                "admin_total": admin_count(db, club.id),
                "friend_ids": friend_id_set(db, user.id),
                "error": request.query_params.get("error"),
                **_club_caps(db, club.id, user.id),
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.get("/clubs/{club_id}/config", response_class=HTMLResponse)
def club_settings(request: Request, club_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_admin(db, club_id, user.id)
        return templates.TemplateResponse(
            request,
            "club_form.html",
            _club_settings_context(db, request, user, club, mode="edit", can_tag=True),
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/config")
async def update_club_settings(
    request: Request,
    club_id: int,
    name: str = Form(...),
    is_closed: str | None = Form(None),
    description: str = Form(""),
    rules: str = Form(""),
    cover_color: str = Form("#3a2348"),
    cover_file: UploadFile | None = File(None),
    clear_cover: str | None = Form(None),
    icon_file: UploadFile | None = File(None),
    admin_name_color: str = Form("#B892FF"),
    sub_name_color: str = Form("#6C63FF"),
    member_limit: str = Form(""),
    settings_section: str = Form("geral"),
):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_admin(db, club_id, user.id)
        admin_hex = valid_hex(admin_name_color)
        sub_hex = valid_hex(sub_name_color)
        limit_value, limit_error = parse_member_limit(member_limit)
        error = None
        if not admin_hex or not sub_hex:
            error = "Escolha cores válidas para ADM e SUB."
        elif limit_error:
            error = limit_error
        if error:
            return templates.TemplateResponse(
                request,
                "club_form.html",
                _club_settings_context(
                    db,
                    request,
                    user,
                    club,
                    mode="edit",
                    can_tag=True,
                    error=error,
                    ok=None,
                    settings_section=_settings_section(settings_section),
                ),
                status_code=400,
            )
        image_name = await save_cover_image(cover_file)
        icon_name = await save_club_icon(icon_file)
        club.name = name.strip()
        club.is_closed = bool(is_closed)
        club.description = description.strip()
        club.rules = rules.strip()
        club.cover_color = valid_cover_color(cover_color)
        club.admin_name_color = admin_hex
        club.sub_name_color = sub_hex
        club.member_limit = limit_value
        if image_name:
            club.cover_image = image_name
        elif clear_cover:
            club.cover_image = None
        if icon_name:
            club.icon_image = icon_name
        db.commit()
        return RedirectResponse(
            _config_href(club_id, settings_section, ok="Configurações salvas"),
            status_code=303,
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/icon/remover")
def remove_club_icon_image(request: Request, club_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_admin(db, club_id, user.id)
        old_name = club.icon_image
        club.icon_image = None
        db.commit()
        delete_club_icon(old_name)
        return Response(status_code=204)
    except HTTPException:
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/descoberta")
async def update_club_discovery(request: Request, club_id: int):
    form = await request.form()
    category_slug = [str(value) for value in form.getlist("category_slug")]
    content_tag = [str(value) for value in form.getlist("content_tag")]
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_admin(db, club_id, user.id)
        error = apply_club_discovery(db, club.id, category_slug, content_tag)
        if error:
            state = club_discovery_state(db, club.id)
            selected = {slug.strip().lower() for slug in category_slug if slug and slug.strip()}
            tags = [{"label": item, "slug": ""} for item in content_tag if (item or "").strip()]
            return templates.TemplateResponse(
                request,
                "club_form.html",
                _club_settings_context(
                    db,
                    request,
                    user,
                    club,
                    mode="edit",
                    can_tag=True,
                    error=error,
                    ok=None,
                    settings_section="descoberta",
                    discovery_selected=selected or state["selected_slugs"],
                    discovery_tags=tags or state["tags"],
                ),
                status_code=400,
            )
        db.commit()
        return RedirectResponse(
            _config_href(club_id, "descoberta", ok="Descoberta atualizada"),
            status_code=303,
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.get("/clubs/{club_id}/tag", response_class=HTMLResponse)
def club_tag_page(request: Request, club_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_perm(db, club_id, user.id, PERM_TAG)
        return templates.TemplateResponse(
            request,
            "club_form.html",
            {
                "user": user,
                "club": club,
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
                "mode": "tag",
                "can_tag": True,
                "tag": tag_payload(club),
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/tag")
def update_club_tag(
    request: Request,
    club_id: int,
    tag_slug: str = Form(""),
    tag_emoji: str = Form(""),
    tag_color_mode: str = Form("solid"),
    tag_color_1: str = Form("#B892FF"),
    tag_color_2: str = Form(""),
    tag_gradient_direction: str = Form(""),
    tag_bg_intensity: str = Form(""),
    tag_border_intensity: str = Form(""),
    tag_emoji_position: str = Form("start"),
    clear_tag: str | None = Form(None),
):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_perm(db, club_id, user.id, PERM_TAG)
        if clear_tag:
            error = _save_club_tag(db, club, "", "")
        else:
            error = _save_club_tag(
                db,
                club,
                tag_slug,
                tag_emoji,
                tag_bg_intensity,
                tag_border_intensity,
                tag_emoji_position,
                tag_color_mode,
                tag_color_1,
                tag_color_2,
                tag_gradient_direction,
            )
        if error:
            tag_state = tag_payload(club) or {
                "slug": (tag_slug or "").strip().upper(),
                "emoji": tag_emoji,
                "color_mode": tag_color_mode,
                "color_1": tag_color_1,
                "color_2": tag_color_2,
                "gradient_direction": tag_gradient_direction,
                "bg_intensity": tag_bg_intensity or TAG_BG_DEFAULT,
                "border_intensity": tag_border_intensity or TAG_BORDER_DEFAULT,
                "position": tag_emoji_position or TAG_POSITION_DEFAULT,
            }
            if is_club_admin(db, club_id, user.id):
                return templates.TemplateResponse(
                    request,
                    "club_form.html",
                    _club_settings_context(
                        db,
                        request,
                        user,
                        club,
                        mode="edit",
                        can_tag=True,
                        error=error,
                        ok=None,
                        tag=tag_state,
                        settings_section="tag",
                    ),
                    status_code=400,
                )
            return templates.TemplateResponse(
                request,
                "club_form.html",
                {
                    "user": user,
                    "club": club,
                    "error": error,
                    "ok": None,
                    "mode": "tag",
                    "can_tag": True,
                    "tag": tag_state,
                },
                status_code=400,
            )
        db.commit()
        if is_club_admin(db, club_id, user.id):
            dest = _config_href(club_id, "tag", ok="Tag atualizada")
        else:
            dest = f"/clubs/{club_id}/tag?ok={quote('Tag atualizada')}"
        return RedirectResponse(dest, status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/conta/tag")
def update_displayed_tag(request: Request, displayed_club_id: str = Form("0")):
    db = db_session()
    try:
        user = login_required(request, db)
        set_displayed_club(db, user, displayed_club_id)
        db.commit()
        return RedirectResponse("/conta?ok=Tag+exibida+atualizada", status_code=303)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/clubs/{club_id}/membros/{member_user_id}/papel")
def set_club_member_role(
    request: Request,
    club_id: int,
    member_user_id: int,
    role: str = Form(...),
    support_perm: list[str] = Form(default=[]),
):
    db = db_session()
    try:
        user = login_required(request, db)
        apply_member_role(db, club_id, user.id, member_user_id, role, support_perm)
        return RedirectResponse(_config_href(club_id, "cargos", ok="Cargo atualizado"), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(_config_href(club_id, "cargos", error=str(exc.detail)), status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/membros/{member_user_id}/admin")
def set_club_admin(request: Request, club_id: int, member_user_id: int, action: str = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        wanted = ROLE_ADMIN if action == "grant" else ROLE_MEMBER
        apply_member_role(db, club_id, user.id, member_user_id, wanted)
        return RedirectResponse(_config_href(club_id, "cargos", ok="Cargo atualizado"), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(_config_href(club_id, "cargos", error=str(exc.detail)), status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/mensagens")
def create_club_message(request: Request, club_id: int, body: str = Form("")):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_member(db, club_id, user.id)
        post_club_message(db, club_id, user.id, body)
        return RedirectResponse(f"/clubs/{club_id}?aba=chat", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(
                f"/clubs/{club_id}?aba=chat&error={quote(str(exc.detail))}",
                status_code=303,
            )
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/shows")
async def add_show(
    request: Request,
    club_id: int,
    tvmaze_id: int = Form(...),
    kind: str = Form("serie"),
):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_member(db, club_id, user.id)
        show = await add_show_to_club(db, club, tvmaze_id, user.id, valid_kind(kind))
        return RedirectResponse(f"/clubs/{club_id}?aba=assistindo", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/agendamentos")
def add_club_schedule(
    request: Request,
    club_id: int,
    show_id: int = Form(...),
    date: str = Form(...),
    time: str = Form(...),
    season_number: str = Form(""),
    episode_number: str = Form(""),
    notes: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_perm(db, club_id, user.id, PERM_SCHEDULES)
        create_schedule(
            db,
            club_id,
            user.id,
            show_id,
            date,
            time,
            season_number,
            episode_number,
            notes,
        )
        return RedirectResponse(f"/clubs/{club_id}?aba=agendamentos", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}?aba=agendamentos", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(
                f"/clubs/{club_id}?aba=agendamentos&error={quote(str(exc.detail))}",
                status_code=303,
            )
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/agendamentos/{schedule_id}/cancelar")
def cancel_club_schedule(request: Request, club_id: int, schedule_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_perm(db, club_id, user.id, PERM_SCHEDULES)
        cancel_schedule(db, club_id, schedule_id)
        return RedirectResponse(f"/clubs/{club_id}?aba=agendamentos", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}?aba=agendamentos", status_code=303)
        if exc.status_code in {400, 404}:
            return RedirectResponse(
                f"/clubs/{club_id}?aba=agendamentos&error={quote(str(exc.detail))}",
                status_code=303,
            )
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/titulos")
def add_title(
    request: Request,
    club_id: int,
    name: str = Form(...),
    kind: str = Form("serie"),
    image_url: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_member(db, club_id, user.id)
        add_manual_title(db, club, user.id, name, kind, image_url)
        return RedirectResponse(f"/clubs/{club_id}?aba=assistindo&lista=assistindo", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(
                f"/clubs/{club_id}?aba=assistindo&lista=assistindo&error={quote(str(exc.detail))}",
                status_code=303,
            )
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/shows/{show_id}/status")
def update_watch_status(request: Request, club_id: int, show_id: int, watch_status: str = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_member(db, club_id, user.id)
        set_watch_status(db, club_id, show_id, watch_status)
        lista = "finalizados" if watch_status == "watched" else "assistindo"
        return RedirectResponse(f"/clubs/{club_id}?aba=assistindo&lista={lista}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/shows/{show_id}/avaliar")
def rate_club_show(request: Request, club_id: int, show_id: int, stars: str = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_member(db, club_id, user.id)
        set_club_show_rating(db, club_id, show_id, user.id, valid_stars(stars))
        return RedirectResponse(f"/clubs/{club_id}?aba=assistindo", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/shows/{show_id}/remover")
def remove_club_title(request: Request, club_id: int, show_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_perm(db, club_id, user.id, PERM_TITLES)
        remove_show_from_club(db, club_id, show_id)
        return RedirectResponse(f"/clubs/{club_id}?aba=assistindo", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.get("/clubs/{club_id}/shows/{show_id}", response_class=HTMLResponse)
def show_detail(request: Request, club_id: int, show_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_member(db, club_id, user.id)
        show = load_show(db, show_id)
        seasons = sorted(show.seasons, key=lambda s: s.number)
        caps = _club_caps(db, club_id, user.id)
        snapshot = progress_snapshot(db, club_id, show.id)
        selected_season, season_episodes = pick_season(snapshot["groups"], request.query_params.get("t"))
        ratings = club_rating_stats(db, club_id, user.id)
        return templates.TemplateResponse(
            request,
            "show.html",
            {
                "user": user,
                "club_id": club_id,
                "show": show,
                "seasons": seasons,
                "progress": snapshot,
                "selected_season": selected_season,
                "season_episodes": season_episodes,
                "rating": ratings.get(show.id, {"average": None, "count": 0, "mine": None, "filled": 0}),
                "error": request.query_params.get("error"),
                **caps,
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


def _episode_progress_redirect(
    club_id: int,
    show_id: int,
    temporada: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    params = []
    text = (temporada or "").strip()
    if text.isdigit():
        params.append(f"t={text}")
    if error:
        params.append(f"error={quote(error)}")
    query = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(f"/clubs/{club_id}/shows/{show_id}{query}#episodios", status_code=303)


@app.post("/clubs/{club_id}/shows/{show_id}/episodios/{episode_id}/visto")
def mark_show_episode(
    request: Request,
    club_id: int,
    show_id: int,
    episode_id: int,
    t: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_perm(db, club_id, user.id, PERM_PROGRESS)
        mark_episode_watched(db, club_id, show_id, episode_id, marked_by_id=user.id)
        return _episode_progress_redirect(club_id, show_id, t)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        if exc.status_code == 400:
            return _episode_progress_redirect(club_id, show_id, t, str(exc.detail))
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/shows/{show_id}/episodios/{episode_id}/desmarcar")
def unmark_show_episode(
    request: Request,
    club_id: int,
    show_id: int,
    episode_id: int,
    t: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_perm(db, club_id, user.id, PERM_PROGRESS)
        unmark_episode(db, club_id, show_id, episode_id)
        return _episode_progress_redirect(club_id, show_id, t)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        if exc.status_code == 400:
            return _episode_progress_redirect(club_id, show_id, t, str(exc.detail))
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/shows/{show_id}/refresh")
async def refresh_show(request: Request, club_id: int, show_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_member(db, club_id, user.id)
        show = load_show(db, show_id)
        if show.tvmaze_id > 0:
            await upsert_show_from_tvmaze(db, show.tvmaze_id)
            refresh_news(db, show, force=True)
            db.commit()
        return RedirectResponse(f"/clubs/{club_id}/shows/{show_id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.get("/api/command")
def api_command(request: Request):
    db = db_session()
    try:
        user = current_user(request, db)
        if not user:
            return {
                "groups": [
                    {
                        "heading": "Navegação",
                        "items": [
                            {"label": "Início", "href": "/"},
                            {"label": "Entrar", "href": "/login"},
                            {"label": "Criar conta", "href": "/register"},
                        ],
                    }
                ]
            }
        groups = [
            {
                "heading": "Navegação",
                "items": [
                    {"label": "Início", "href": "/"},
                    {"label": "Meus Clubes", "href": "/clubes"},
                    {"label": "Configurações", "href": "/conta"},
                    {"label": "Criar um clube", "href": "/clubs/novo"},
                    {"label": "Meu perfil", "href": f"/u/{user.username}"},
                    {"label": "Amigos", "href": "/amigos"},
                ],
            }
        ]
        clubs = _user_clubs(db, user.id)
        if clubs:
            groups.append(
                {
                    "heading": "Clubes",
                    "items": [{"label": club.name, "href": f"/clubs/{club.id}"} for club in clubs],
                }
            )
        return {"groups": groups}
    finally:
        db.close()


@app.get("/api/shows/search")
async def api_search(q: str = Query(..., min_length=1)):
    return await tvmaze.search_shows(q)


@app.get("/api/username")
def api_username(request: Request, q: str = Query(..., min_length=1)):
    db = db_session()
    try:
        user = current_user(request, db)
        key = normalize_username(q)
        exclude = user.id if user else None
        available = bool(USERNAME_RE.match(key)) and not username_taken(db, key, exclude_user_id=exclude)
        occupied = taken_keys(db)
        if user:
            occupied.discard(user.username_key)
        return {
            "username": key,
            "available": available,
            "suggestions": [] if available else suggest_usernames(key or q, occupied),
        }
    finally:
        db.close()


def _friend_redirect(exc: HTTPException, fallback: str):
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    if exc.status_code in {400, 403}:
        return RedirectResponse(f"{fallback}?error={quote(exc.detail)}", status_code=303)
    raise exc


@app.get("/amigos", response_class=HTMLResponse)
def friends_page(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        friends = list_friends(db, user.id)
        incoming = incoming_invites(db, user.id)
        stamp_display_tags(db, friends + incoming)
        return templates.TemplateResponse(
            request,
            "friends.html",
            {
                "user": user,
                "friends": friends,
                "incoming": incoming,
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/amigos/{username}/convidar")
def friend_invite(request: Request, username: str, next: str = Form("/amigos")):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        send_invite(db, user.id, person.id)
        return RedirectResponse(_safe_next(next, f"/u/{person.username}") + "?ok=Pedido+enviado", status_code=303)
    except HTTPException as exc:
        return _friend_redirect(exc, _safe_next(next, "/amigos"))
    finally:
        db.close()


@app.post("/amigos/{username}/aceitar")
def friend_accept(request: Request, username: str, next: str = Form("/amigos")):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        accept_invite(db, user.id, person.id)
        return RedirectResponse(_safe_next(next, "/amigos") + "?ok=Vocês+são+amigos", status_code=303)
    except HTTPException as exc:
        return _friend_redirect(exc, _safe_next(next, "/amigos"))
    finally:
        db.close()


@app.post("/amigos/{username}/recusar")
def friend_decline(request: Request, username: str, next: str = Form("/amigos")):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        decline_invite(db, user.id, person.id)
        return RedirectResponse(_safe_next(next, "/amigos") + "?ok=Pedido+recusado", status_code=303)
    except HTTPException as exc:
        return _friend_redirect(exc, _safe_next(next, "/amigos"))
    finally:
        db.close()


@app.post("/amigos/{username}/desfazer")
def friend_unfriend(request: Request, username: str, next: str = Form("/amigos")):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        unfriend(db, user.id, person.id)
        return RedirectResponse(_safe_next(next, "/amigos") + "?ok=Amizade+desfeita", status_code=303)
    except HTTPException as exc:
        return _friend_redirect(exc, _safe_next(next, "/amigos"))
    finally:
        db.close()


@app.get("/mensagens/{username}", response_class=HTMLResponse)
def direct_chat(request: Request, username: str):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        if person.id == user.id:
            return RedirectResponse(f"/u/{user.username}", status_code=303)
        if not can_view_thread(db, user.id, person.id):
            return RedirectResponse(f"/u/{person.username}", status_code=303)
        are_friends = relation_status(db, user.id, person.id) == "friends"
        messages = dm_thread(db, user.id, person.id)
        stamp_display_tags(db, [person] + [item.sender for item in messages])
        return templates.TemplateResponse(
            request,
            "direct_chat.html",
            {
                "user": user,
                "person": person,
                "messages": messages,
                "are_friends": are_friends,
                "error": request.query_params.get("error"),
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/mensagens/{username}")
def send_direct_message(request: Request, username: str, body: str = Form("")):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        post_dm(db, user.id, person.id, body)
        return RedirectResponse(f"/mensagens/{person.username}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        person = find_active_user(db, username)
        nick = person.username if person else username
        if exc.status_code == 403:
            if person and can_view_thread(db, user.id, person.id):
                return RedirectResponse(
                    f"/mensagens/{nick}?error={quote(exc.detail)}",
                    status_code=303,
                )
            return RedirectResponse(f"/u/{nick}", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(f"/mensagens/{nick}?error={quote(exc.detail)}", status_code=303)
        raise
    finally:
        db.close()


def _profile_ok_message(ok: str | None, relation: str) -> str | None:
    text = (ok or "").strip()
    if not text:
        return None
    if text in {"Pedido enviado", "Vocês são amigos"}:
        return None
    return text


@app.get("/u/{username}", response_class=HTMLResponse)
def public_profile(request: Request, username: str):
    db = db_session()
    try:
        viewer = login_required(request, db)
        key = normalize_username(username)
        person = db.scalar(select(User).where(User.username_key == key, User.is_active.is_(True)))
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        clubs = _user_clubs(db, person.id)
        mine = {club.id for club in _user_clubs(db, viewer.id)}
        relation = relation_status(db, viewer.id, person.id)
        stamp_display_tags(db, [person])
        context_club, context_role, context_role_label = _club_profile_context(
            db, viewer, person, request.query_params.get("clube")
        )
        return templates.TemplateResponse(
            request,
            "profile.html",
            {
                "user": viewer,
                "person": person,
                "clubs": clubs,
                "mine": mine,
                "requested_ids": requested_club_ids(db, viewer.id),
                "status": presence_of(person),
                "status_label": PRESENCE_LABELS[presence_of(person)],
                "relation": relation,
                "has_history": has_dm_history(db, viewer.id, person.id),
                "context_club": context_club,
                "context_club_tag": tag_payload(context_club) if context_club else None,
                "context_role": context_role,
                "context_role_label": context_role_label,
                "error": request.query_params.get("error"),
                "ok": _profile_ok_message(request.query_params.get("ok"), relation),
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/solicitar")
def request_club_join(request: Request, club_id: int, next: str = Form("")):
    db = db_session()
    dest = _safe_next(next, f"/clubs/{club_id}")
    try:
        user = login_required(request, db)
        club = db.get(Club, club_id)
        if not club:
            raise HTTPException(status_code=404, detail="Clube não encontrado")
        create_join_request(db, club, user.id)
        db.commit()
        sep = "&" if "?" in dest else "?"
        return RedirectResponse(f"{dest}{sep}ok={quote('Pedido enviado')}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 400:
            sep = "&" if "?" in dest else "?"
            return RedirectResponse(f"{dest}{sep}error={quote(str(exc.detail))}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/solicitacoes/{user_id}/aceitar")
def accept_club_join(request: Request, club_id: int, user_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        accept_join_request(db, club_id, user_id, user.id)
        return RedirectResponse(f"/clubs/{club_id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(f"/clubs/{club_id}?error={quote(str(exc.detail))}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/solicitacoes/{user_id}/recusar")
def reject_club_join(request: Request, club_id: int, user_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        reject_join_request(db, club_id, user_id, user.id)
        db.commit()
        return RedirectResponse(f"/clubs/{club_id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/presenca")
def ping_presence(request: Request, status: str = Form("online"), prefer: str = Form("")):
    db = db_session()
    try:
        user = current_user(request, db)
        if not user:
            return {"ok": False}
        chosen = status if status in PRESENCE_LABELS else "online"
        touch_presence(user, chosen, prefer=prefer in {"1", "true", "yes"})
        db.commit()
        shown = presence_of(user)
        return {"ok": True, "status": shown, "status_label": PRESENCE_LABELS[shown]}
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}
