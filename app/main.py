import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Mount

from app.accounts import (
    auth0_followup_path,
    complete_auth0_onboarding,
    create_user,
    email_taken,
    find_user_by_auth0_sub,
    find_user_by_email,
    is_profile_draft_ready,
    parse_profile_draft,
    resolve_auth0_login_user_id,
    find_valid_reset,
    login_or_create_oauth,
    normalize_email,
    send_activation,
    send_password_reset,
    suggested_auth0_name,
    suggested_auth0_username,
    utcnow,
)
from app.auth0_oidc import (
    Auth0Error,
    auth0_enabled,
    authorize_url as auth0_authorize_url,
    logout_url as auth0_logout_url,
    merge_pending_payload,
    pending_identity,
    pkce_pair,
    redeem_callback,
)
from app.avatar_uploads import MAX_BYTES as AVATAR_MAX_BYTES
from app.avatar_uploads import delete_upload, save_avatar_photo, stored_upload_path
from app.pixel_art import (
    PRESET_CHOICES,
    PixelArtError,
    STYLE_ORIGINAL,
    attach_preset,
    generate_derivative,
    normalize_style,
    preview_bytes,
    require_style,
)
from app.avatars import (
    AVATARS,
    avatar_initials,
    avatar_original_url,
    avatar_url,
    illustrated_catalogs,
    parse_illustrated_choice,
    set_illustrated_avatar,
    set_upload_avatar,
    valid_avatar,
)
from app.chat_time import chat_clock, chat_day_key, chat_day_label
from app.catalog import (
    CONTENT_KINDS,
    HOME_NEWS_LIMIT,
    NEWS_FAVORITES_TIPO,
    NEWS_FEED_FILTERS,
    NEWS_FEED_KIND_MAP,
    NEWS_PAGE_LIMIT,
    profile_club_preview,
    profile_favorite_preview,
    add_club_member,
    add_manual_title,
    annotate_search_results,
    add_show_to_club,
    add_tmdb_movie_to_club,
    accept_join_request,
    admin_count,
    apply_member_role,
    club_membership,
    club_messages,
    create_join_request,
    club_rating_stats,
    ensure_catalog_show,
    favorite_catalog_result,
    favorite_show_ids,
    favorite_show_names,
    fill_missing_genres,
    is_club_admin,
    is_show_favorite,
    leave_club as remove_club_membership,
    load_show,
    parse_genres,
    premiere_year,
    parse_member_limit,
    program_catalog_for_shows,
    list_join_requests,
    compose_news_layout,
    pack_news_rest,
    delete_club_message,
    list_feed_news,
    load_pinned_message,
    list_user_favorites,
    pick_home_news,
    pending_join_request,
    pin_club_message,
    post_club_message,
    unpin_club_message,
    refresh_feed_news,
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
    suggest_show_to_club,
    toggle_show_favorite,
    can_refresh_catalog,
    show_source,
    upsert_show_from_tmdb,
    upsert_show_from_tvmaze,
    valid_kind,
    valid_stars,
)
from app.navigation import back_href_for
from app.notifications import (
    DEFAULT_LIST_LIMIT,
    HEADER_PREVIEW_LIMIT,
    JOIN_ALREADY_RESOLVED,
    JOIN_MISSING_DETAIL,
    NOTICE_POLL_SECONDS,
    format_notification_when,
    header_notification_context,
    header_snapshot,
    clear_notifications,
    mark_all_read,
    mark_own_join_notifications_read,
    mark_read,
    notification_cards,
    notification_destination,
    unread_badge,
    unread_count,
    unread_label,
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
from app.club_icons import (
    club_icon_initials,
    club_icon_original_url,
    club_icon_url,
    delete_club_icon,
    save_club_icon,
    stored_icon_path,
)
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
from app.covers import (
    COVER_COLORS,
    COVER_PRESETS,
    cover_image_url,
    cover_original_url,
    delete_cover_image,
    save_cover_image,
    stored_cover_path,
    valid_cover_color,
)
from app.markup import format_chat, pin_preview
from app.pixel_emoji import pack_available as joi3_pack_available
from app.pixel_emoji import picker_catalog as joi3_catalog
from app.pixel_emoji import render_tokens
from app import config as app_config
from app.config import BASE_DIR, BIO_MAX, EMAIL_DEV_SHOW_LINK, SECRET_KEY, SESSION_HTTPS_ONLY, uploads_dir
from app.dev_preview import register_ui_preview_routes
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
    delete_dm,
    dm_thread,
    find_active_user,
    friend_id_set,
    has_dm_history,
    incoming_invites,
    list_dm_conversations,
    list_friends,
    mark_dm_read,
    person_href,
    post_dm,
    relation_status,
    send_invite,
    unfriend,
)
from app.models import AccountInvite, Club, ClubMember, ClubShow, EmailToken, Suggestion, User
from app.player import (
    DEFAULT_THEME,
    DEFAULT_WALLPAPER,
    PROFILE_STATUS_MAX,
    THEMES,
    WALLPAPERS,
    clean_profile_status,
    energy_hearts,
    player_progress,
    player_stats,
    profile_tab,
    require_theme,
    require_wallpaper,
    theme_of,
    wallpaper_catalog,
    wallpaper_class,
    wallpaper_of,
    wallpaper_spec,
    wallpaper_src,
    wallpaper_style,
)
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
from app.registrations import (
    EXPIRED_DECISION_MESSAGE,
    REVIEW_ALREADY_DECIDED_MESSAGE,
    REVIEW_APPROVED,
    REVIEW_LABELS,
    REVIEW_MESSAGE_MAX,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    STATUS_EXPIRED,
    STATUS_LABELS,
    approve_registration,
    approve_registration_review,
    create_registration_review,
    get_registration,
    get_registration_review,
    list_pending_registrations,
    list_pending_reviews,
    reject_registration,
    reject_registration_review,
    require_site_admin,
)
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
    can_moderate_club_chat,
    member_role,
    parse_support_perms,
)
from app.progress import mark_episode_watched, pick_season, progress_snapshot, unmark_episode
from app.schedules import (
    cancel_schedule,
    create_schedule,
    end_schedule_series,
    format_clock,
    format_episode_line,
    format_recurrence_line,
    format_schedule_detail,
    format_schedule_when,
    format_week_line,
    group_schedules_by_day,
    list_member_upcoming_schedules,
    list_member_week_schedules,
    list_upcoming_schedules,
    next_meetings_by_show,
    local_today,
    monday_of,
    format_week_span,
    meeting_title,
    parse_iso_date,
    parse_meeting_title,
    parse_optional_show_id,
    program_title,
    set_schedule_program,
    update_schedule_when,
    utc_to_local,
    week_planner_days,
)
from app.search import (
    SEARCH_MIN_CHARS,
    CatalogSearchError,
    normalize_search_query,
    search_catalog,
    search_ready,
)
from app.schema import migrate_schema
from app.security import hash_password, make_join_code, verify_password
from app.suggestions import (
    DESCRIPTION_MAX,
    STATUS_LABELS as SUGGESTION_STATUS_LABELS,
    STATUSES as SUGGESTION_STATUSES,
    TITLE_MAX,
    archive_suggestion,
    create_suggestion,
    list_admin_suggestions,
    list_own_suggestions,
    set_suggestion_status,
)
from app.moderation import (
    AccountRestricted,
    ORIGIN_ADMIN,
    SURFACE_PUBLIC_NAME,
    SURFACE_PUBLIC_TEXT,
    apply_violation,
    counting_violation_count,
    enforce_image,
    enforce_text,
    is_restricted,
    restriction_kind,
    restriction_path_allowed,
    reverse_event,
    user_moderation_history,
)
from app.blocks import (
    are_blocked,
    block_user,
    ids_blocked_by,
    list_blocked_users,
    unblock_user,
)
from app.reports import (
    APPEAL_KEPT,
    APPEAL_REASON_LABELS,
    APPEAL_REASONS,
    APPEAL_REMOVED,
    EXPLANATION_MAX,
    EXPLANATION_MIN,
    MAX_REPORT_ATTACHMENTS,
    MAX_REPORT_MESSAGES,
    OWN_STATUS_LABELS,
    PENALTY_ACTION_LABELS,
    REPORT_NOTE_MAX,
    REPORT_NOTE_MIN,
    REASON_LABELS,
    REASONS,
    TARGET_CLUB_MESSAGE,
    TARGET_DM,
    TARGET_LABELS,
    USER_OUTCOME_LABELS,
    can_view_report_attachment,
    chronological_message_snapshots,
    create_appeal,
    create_report,
    get_appeal,
    get_case,
    get_report_attachment,
    list_appeals,
    list_cases,
    list_own_reports,
    load_snapshot,
    locate_club_member_for_report,
    locate_member_club,
    locate_user_for_report,
    own_report_counts,
    parse_id_list,
    preview_report,
    remove_reported_content,
    resolve_case,
    save_appeal_image,
    save_report_evidence_image,
    stored_appeal_path,
    stored_report_evidence_path,
)
from app.services.news import FEED_KIND_LABELS, format_news_when, format_news_when_short
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
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
)


@app.exception_handler(AccountRestricted)
async def account_restricted_handler(request: Request, _exc: AccountRestricted):
    if request.headers.get("x-watchclub-pref") == "1" or request.headers.get("x-watchclub-notice") == "1":
        return JSONResponse({"ok": False, "error": "conta restrita"}, status_code=403)
    return RedirectResponse("/conta-restrita", status_code=303)


def mount_static_files(application: FastAPI) -> None:
    application.router.routes = [
        route
        for route in application.router.routes
        if not (isinstance(route, Mount) and route.path in {"/static", "/static/uploads"})
    ]
    uploads_root = uploads_dir()
    uploads_root.mkdir(parents=True, exist_ok=True)
    application.mount("/static/uploads", StaticFiles(directory=str(uploads_root)), name="uploads")
    application.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


mount_static_files(app)
templates = Jinja2Templates(
    directory=str(BASE_DIR / "app" / "templates"),
    context_processors=[header_notification_context],
)
_STYLE_CSS = BASE_DIR / "app" / "static" / "style.css"


def stylesheet_href() -> str:
    try:
        stamp = int(_STYLE_CSS.stat().st_mtime)
    except OSError:
        stamp = 0
    return f"/static/style.css?v={stamp}"
templates.env.globals["presence_of"] = presence_of
templates.env.globals["presence_label"] = lambda user: PRESENCE_LABELS[presence_of(user)]
templates.env.globals["avatar_initials"] = avatar_initials
templates.env.globals["avatar_url"] = avatar_url
templates.env.globals["avatar_original_url"] = avatar_original_url
templates.env.globals["cover_original_url"] = cover_original_url
templates.env.globals["club_icon_original_url"] = club_icon_original_url
templates.env.globals["google_enabled"] = google_enabled
templates.env.globals["facebook_enabled"] = facebook_enabled
templates.env.globals["BIO_MAX"] = BIO_MAX
templates.env.globals["COVER_COLORS"] = COVER_COLORS
templates.env.globals["COVER_PRESETS"] = COVER_PRESETS
templates.env.globals["cover_image_url"] = cover_image_url
templates.env.globals["club_icon_url"] = club_icon_url
templates.env.globals["club_icon_initials"] = club_icon_initials
templates.env.globals["PRESET_CHOICES"] = PRESET_CHOICES
templates.env.globals["MAX_CATEGORIES"] = MAX_CATEGORIES
templates.env.globals["MAX_TAGS"] = MAX_TAGS
templates.env.globals["TAG_LABEL_MAX"] = TAG_LABEL_MAX
templates.env.globals["KIND_LABELS"] = KIND_LABELS
templates.env.globals["CONTENT_KINDS"] = CONTENT_KINDS
templates.env.globals["NEWS_FEED_FILTERS"] = NEWS_FEED_FILTERS
templates.env.globals["FEED_KIND_LABELS"] = FEED_KIND_LABELS
templates.env.globals["can_refresh_catalog"] = can_refresh_catalog
templates.env.globals["show_source"] = show_source
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
templates.env.filters["schedule_detail"] = format_schedule_detail
templates.env.filters["schedule_clock"] = format_clock
templates.env.filters["schedule_date"] = lambda value: utc_to_local(value).date().isoformat() if value else ""
templates.env.globals["schedule_episode_line"] = lambda item: format_episode_line(
    item.season_number, item.episode_number
)
templates.env.globals["schedule_week_line"] = format_week_line
templates.env.globals["schedule_program_title"] = program_title
templates.env.globals["schedule_meeting_title"] = meeting_title
templates.env.globals["schedule_recurrence_line"] = format_recurrence_line
templates.env.filters["genres"] = parse_genres
templates.env.filters["premiere_year"] = premiere_year
templates.env.filters["avg_pt"] = lambda value: f"{value:.1f}".replace(".", ",") if value is not None else ""
templates.env.filters["news_when"] = format_news_when
templates.env.filters["news_when_short"] = format_news_when_short
templates.env.globals["stylesheet_href"] = stylesheet_href
templates.env.globals["back_href_for"] = back_href_for
templates.env.globals["NOTICE_POLL_SECONDS"] = NOTICE_POLL_SECONDS
templates.env.filters["notice_when"] = format_notification_when
templates.env.filters["chat_format"] = format_chat
templates.env.filters["pin_preview"] = pin_preview
templates.env.filters["pixel_emoji"] = render_tokens
templates.env.globals["joi3_emoji_catalog"] = joi3_catalog
templates.env.globals["joi3_emoji_available"] = joi3_pack_available
templates.env.globals["wallpaper_class"] = wallpaper_class
templates.env.globals["wallpaper_style"] = wallpaper_style
templates.env.globals["wallpaper_spec"] = wallpaper_spec
templates.env.globals["wallpaper_src"] = wallpaper_src
templates.env.filters["chat_clock"] = chat_clock
templates.env.filters["chat_day_key"] = chat_day_key
templates.env.filters["chat_day_label"] = chat_day_label


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
    if is_restricted(user) and not restriction_path_allowed(request.url.path):
        raise AccountRestricted()
    return user


def db_session() -> Session:
    return next(get_db())


def _safe_next(path: str | None, fallback: str = "/") -> str:
    if path and path.startswith("/") and not path.startswith("//"):
        return path
    return fallback


def _join_return_path(path: str | None, club_id: int) -> str:
    return _safe_next(path, f"/clubs/{club_id}")


def _notice_fetch(request: Request) -> bool:
    return request.headers.get("x-watchclub-notice") == "1"


def _bell_html(request: Request, unread: int, cards: list) -> str:
    return templates.get_template("partials/bell_popover_inner.html").render(
        request=request,
        notification_unread=unread,
        header_notifications=cards,
        current_path=request.url.path,
    )


def _inbox_html(request: Request, unread: int, cards: list) -> str:
    return templates.get_template("partials/notice_inbox_inner.html").render(
        request=request,
        notification_unread=unread,
        inbox_notifications=cards,
        current_path=request.url.path,
    )


def _notice_payload(request: Request, db: Session, user_id: int, extra: dict | None = None, full: bool = False) -> dict:
    if str(request.query_params.get("todas") or "") == "1":
        full = True
    if full:
        count = unread_count(db, user_id)
        cards = notification_cards(db, user_id, DEFAULT_LIST_LIMIT)
        payload = {
            "ok": True,
            "unread": count,
            "badge": unread_badge(count),
            "label": unread_label(count),
            "html": _bell_html(request, count, cards[:HEADER_PREVIEW_LIMIT]),
            "inbox_html": _inbox_html(request, count, cards),
        }
    else:
        snap = header_snapshot(db, user_id)
        payload = {
            "ok": True,
            "unread": snap["unread"],
            "badge": snap["badge"],
            "label": snap["label"],
            "html": _bell_html(request, snap["unread"], snap["cards"]),
        }
    if extra:
        payload.update(extra)
    return payload


def _redirect_with_query(path: str, key: str, message: str) -> RedirectResponse:
    sep = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{sep}{key}={quote(message)}", status_code=303)


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
        "can_moderate_chat": can_moderate_club_chat(member),
    }


def _club_tab(aba: str | None) -> str:
    if aba == "chat":
        return "chat"
    if aba == "agendamentos":
        return "agendamentos"
    if aba == "denuncias":
        return "denuncias"
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


def _member_club_nav(db: Session, user_id: int) -> list[Club]:
    clubs = list(
        db.scalars(select(Club).join(ClubMember).where(ClubMember.user_id == user_id)).unique()
    )
    return sorted(clubs, key=lambda item: (item.name or "").casefold())


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    db = db_session()
    try:
        user = current_user(request, db)
        clubs = _user_clubs(db, user.id) if user else []
        home_news = []
        if user:
            refresh_feed_news(db)
            home_news = pick_home_news(list_feed_news(db, limit=NEWS_PAGE_LIMIT), HOME_NEWS_LIMIT)
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "user": user,
                "clubs": clubs,
                "home_news": home_news,
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
            },
        )
    finally:
        db.close()


@app.get("/noticias", response_class=HTMLResponse)
def news_page(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        query = (request.query_params.get("q") or "").strip()
        tipo = (request.query_params.get("tipo") or "").strip()
        if tipo not in NEWS_FEED_KIND_MAP and tipo not in {"", NEWS_FAVORITES_TIPO}:
            tipo = ""
        refresh_feed_news(db)
        fav_names = favorite_show_names(db, user.id) if tipo == NEWS_FAVORITES_TIPO else None
        items = list_feed_news(
            db,
            query=query,
            tipo=tipo,
            limit=NEWS_PAGE_LIMIT,
            favorite_names=fav_names,
        )
        featured, secondary, rest = compose_news_layout(items)
        rest_cells = pack_news_rest(rest)
        return templates.TemplateResponse(
            request,
            "news.html",
            {
                "user": user,
                "query": query,
                "tipo": tipo,
                "featured": featured,
                "secondary": secondary,
                "rest": rest,
                "rest_cells": rest_cells,
                "has_news": bool(items),
                "has_favorites": bool(fav_names) if tipo == NEWS_FAVORITES_TIPO else False,
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.get("/agenda", response_class=HTMLResponse)
def personal_agenda(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        clubs = _user_clubs(db, user.id)
        club_ids = {club.id for club in clubs}
        raw_club = (request.query_params.get("clube") or "").strip()
        club_id = int(raw_club) if raw_club.isdigit() else None
        if club_id not in club_ids:
            club_id = None
        today = local_today()
        now = utcnow()
        week_start = monday_of(parse_iso_date(request.query_params.get("semana")) or today)
        items = list_member_upcoming_schedules(db, user.id, club_id)
        week_items = list_member_week_schedules(db, user.id, week_start, club_id)
        days = week_planner_days(week_start, week_items, today)
        return templates.TemplateResponse(
            request,
            "agenda.html",
            {
                "user": user,
                "clubs": clubs,
                "club_id": club_id,
                "groups": group_schedules_by_day(items, today),
                "upcoming": items,
                "next_item": items[0] if items else None,
                "days": days,
                "week_label": format_week_span(week_start),
                "week_iso": week_start.isoformat(),
                "prev_week": (week_start - timedelta(days=7)).isoformat(),
                "next_week": (week_start + timedelta(days=7)).isoformat(),
                "today": today,
                "now": now,
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.get("/clubes", response_class=HTMLResponse)
def clubs_index(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        query = (request.query_params.get("q") or "").strip()
        clubs = _user_clubs(db, user.id)
        if query:
            needle = query.casefold()
            clubs = [club for club in clubs if needle in club.name.casefold()]
        return templates.TemplateResponse(
            request,
            "clubs_list.html",
            {
                "user": user,
                "clubs": clubs,
                "query": query,
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


def _legacy_auth_to_auth0(request: Request, *, signup: bool = False) -> RedirectResponse | None:
    if not auth0_enabled():
        return None
    return _start_auth0(request, signup=signup)


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    closed = _legacy_auth_to_auth0(request, signup=True)
    if closed:
        return closed
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
    closed = _legacy_auth_to_auth0(request, signup=True)
    if closed:
        return closed
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
            request.session.pop("auth_provider", None)
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
    closed = _legacy_auth_to_auth0(request)
    if closed:
        return closed
    return _reset_page(
        request,
        "forgot",
        error=request.query_params.get("error") or "",
        ok=request.query_params.get("ok") or "",
        form={"email": request.session.get("reset_email") or ""},
    )


@app.post("/recuperar-senha")
def forgot_password(request: Request, email: str = Form(...)):
    closed = _legacy_auth_to_auth0(request)
    if closed:
        return closed
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
    closed = _legacy_auth_to_auth0(request)
    if closed:
        return closed
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
    closed = _legacy_auth_to_auth0(request)
    if closed:
        return closed
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
        request.session.pop("auth_provider", None)
        request.session["user_id"] = user.id
        touch_presence(user, "online")
        db.commit()
        return RedirectResponse("/?ok=Senha+redefinida", status_code=303)
    finally:
        db.close()


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    closed = _legacy_auth_to_auth0(request)
    if closed:
        return closed
    return _auth_page(request, "login", request.query_params.get("error") or "", status_code=200)


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    closed = _legacy_auth_to_auth0(request)
    if closed:
        return closed
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
        request.session.pop("auth_provider", None)
        request.session["user_id"] = user.id
        touch_presence(user, "online")
        db.commit()
        return RedirectResponse("/", status_code=303)
    finally:
        db.close()


def _end_watch_club_session(request: Request) -> None:
    db = db_session()
    try:
        user = current_user(request, db)
        if user:
            mark_logout(user)
            db.commit()
    finally:
        db.close()
    request.session.clear()


@app.post("/logout")
def logout(request: Request):
    auth0_session = request.session.get("auth_provider") == "auth0"
    _end_watch_club_session(request)
    if auth0_session and auth0_enabled():
        try:
            return RedirectResponse(auth0_logout_url(), status_code=303)
        except Auth0Error:
            pass
    return RedirectResponse("/", status_code=303)


def _clear_auth0_handshake(request: Request) -> None:
    request.session.pop("auth0_state", None)
    request.session.pop("auth0_nonce", None)
    request.session.pop("auth0_verifier", None)
    request.session.pop("auth0_silent", None)


def _start_auth0(request: Request, *, signup: bool = False, silent: bool = False) -> RedirectResponse:
    if not auth0_enabled():
        return RedirectResponse(
            "/login?error=Configure+AUTH0_DOMAIN,+AUTH0_CLIENT_ID+e+AUTH0_CLIENT_SECRET+no+.env",
            status_code=303,
        )
    from secrets import token_urlsafe

    state = token_urlsafe(24)
    nonce = token_urlsafe(24)
    verifier, challenge = pkce_pair()
    request.session["auth0_state"] = state
    request.session["auth0_nonce"] = nonce
    request.session["auth0_verifier"] = verifier
    if silent:
        request.session["auth0_silent"] = True
    else:
        request.session.pop("auth0_silent", None)
    try:
        return RedirectResponse(
            auth0_authorize_url(state, nonce, challenge, signup=signup, silent=silent),
            status_code=303,
        )
    except Auth0Error:
        _clear_auth0_handshake(request)
        return RedirectResponse(
            "/?error=" + quote("Não foi possível iniciar o login Auth0"),
            status_code=303,
        )


def _auth0_pending_payload(request: Request) -> dict:
    payload = request.session.get("auth0_pending")
    return payload if isinstance(payload, dict) else {}


def _auth0_profile_ready(request: Request) -> bool:
    return is_profile_draft_ready(_auth0_pending_payload(request))


def _auth0_destination(db, user, identity, request: Request) -> str:
    destination = auth0_followup_path(
        db,
        user,
        email=identity.email,
        email_verified=identity.email_verified,
        profile_ready=_auth0_profile_ready(request),
    )
    db.commit()
    return destination


def _login_auth0_user(request: Request, db, user) -> RedirectResponse:
    request.session.pop("auth0_pending", None)
    request.session["auth_provider"] = "auth0"
    request.session["user_id"] = user.id
    touch_presence(user, "online")
    db.commit()
    return RedirectResponse("/", status_code=303)


def _awaiting_auth0_user(request: Request) -> RedirectResponse:
    request.session.pop("user_id", None)
    request.session["auth_provider"] = "auth0"
    return RedirectResponse("/auth/aguardando", status_code=303)


def _expired_auth0_user(request: Request) -> RedirectResponse:
    request.session.pop("user_id", None)
    request.session["auth_provider"] = "auth0"
    return RedirectResponse("/auth/expirada", status_code=303)


def _complete_auth0_from_draft(request: Request, db, identity):
    payload = _auth0_pending_payload(request)
    return complete_auth0_onboarding(
        db,
        sub=identity.sub,
        email=identity.email,
        email_verified=identity.email_verified,
        name=str(payload.get("profile_name") or ""),
        username=str(payload.get("profile_username") or ""),
    )


@app.get("/auth/login")
def auth0_login_start(request: Request):
    return _start_auth0(request, signup=False)


@app.get("/auth/signup")
def auth0_signup_start(request: Request):
    return _start_auth0(request, signup=True)


@app.get("/callback")
def auth0_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    silent = bool(request.session.get("auth0_silent"))
    if error or not code:
        _clear_auth0_handshake(request)
        if silent and error in {"login_required", "interaction_required", "consent_required"}:
            return _start_auth0(request, signup=False, silent=False)
        return RedirectResponse("/login?error=Login+Auth0+cancelado+ou+inválido", status_code=303)
    expected_state = request.session.get("auth0_state")
    nonce = request.session.get("auth0_nonce")
    verifier = request.session.get("auth0_verifier")
    if not expected_state or not nonce or not verifier or state != expected_state:
        _clear_auth0_handshake(request)
        return RedirectResponse("/login?error=Login+Auth0+cancelado+ou+inválido", status_code=303)
    db = db_session()
    try:
        try:
            identity = redeem_callback(code, verifier, nonce)
        except Exception:
            _clear_auth0_handshake(request)
            return RedirectResponse("/login?error=Não+foi+possível+validar+o+retorno+do+Auth0", status_code=303)
        _clear_auth0_handshake(request)
        request.session.pop("user_id", None)
        request.session["auth0_pending"] = merge_pending_payload(_auth0_pending_payload(request), identity)
        request.session["auth_provider"] = "auth0"
        user_id = resolve_auth0_login_user_id(
            db,
            sub=identity.sub,
            email=identity.email,
            email_verified=identity.email_verified,
        )
        user = db.get(User, user_id) if user_id else None
        if user and user.is_active:
            return _login_auth0_user(request, db, user)
        if not user and identity.email_verified and _auth0_profile_ready(request):
            outcome, created_id, error_text, suggestions = _complete_auth0_from_draft(request, db, identity)
            created = db.get(User, created_id) if created_id else None
            if outcome == "active" and created:
                return _login_auth0_user(request, db, created)
            if outcome == "awaiting":
                return _awaiting_auth0_user(request)
            if outcome == "expired":
                return _expired_auth0_user(request)
            if outcome == "form_error":
                request.session["auth0_profile_error"] = error_text
                request.session["auth0_profile_suggestions"] = suggestions
                return RedirectResponse("/auth/completar-perfil", status_code=303)
        return RedirectResponse(_auth0_destination(db, user, identity, request), status_code=303)
    finally:
        db.close()


def _auth0_pending_identity(request: Request):
    return pending_identity(request.session.get("auth0_pending"))


def _auth0_gate_page(request: Request, template: str, identity, extra: dict | None = None, status_code: int = 200):
    context = {"user": None, "identity": identity, "signup_step": ""}
    if extra:
        context.update(extra)
    return templates.TemplateResponse(request, template, context, status_code=status_code)


@app.get("/auth/pendente", response_class=HTMLResponse)
def auth0_pending_page(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        destination = _auth0_destination(db, user, identity, request)
        if destination == "/auth/pendente":
            destination = "/auth/verificar-email"
        return RedirectResponse(destination, status_code=303)
    finally:
        db.close()


@app.get("/auth/verificar-email", response_class=HTMLResponse)
def auth0_verify_email_page(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        destination = _auth0_destination(db, user, identity, request)
        if destination != "/auth/verificar-email":
            return RedirectResponse(destination, status_code=303)
        return _auth0_gate_page(
            request,
            "auth0_verify_email.html",
            identity,
            {"signup_step": "verificacao"},
        )
    finally:
        db.close()


@app.get("/auth/verificar-email/continuar")
def auth0_verify_email_continue(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    return _start_auth0(request, signup=False, silent=True)


@app.get("/auth/completar-perfil", response_class=HTMLResponse)
def auth0_complete_profile_form(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        destination = _auth0_destination(db, user, identity, request)
        if destination != "/auth/completar-perfil":
            return RedirectResponse(destination, status_code=303)
        payload = _auth0_pending_payload(request)
        draft_name = str(payload.get("profile_name") or "").strip()
        draft_username = str(payload.get("profile_username") or "").strip()
        suggested_name = draft_name or suggested_auth0_name(
            email=identity.email,
            name=identity.name,
            nickname=identity.nickname,
        )
        suggested_username = draft_username or suggested_auth0_username(
            db, suggested_name or identity.email or "cinefilo"
        )
        error = request.session.pop("auth0_profile_error", None) or request.query_params.get("error") or ""
        suggestions = request.session.pop("auth0_profile_suggestions", None) or []
        return _auth0_gate_page(
            request,
            "auth0_onboard.html",
            identity,
            {
                "error": error,
                "suggestions": suggestions,
                "form": {"name": suggested_name, "username": suggested_username},
                "signup_step": "perfil",
            },
        )
    finally:
        db.close()


@app.post("/auth/completar-perfil")
def auth0_complete_profile(request: Request, name: str = Form(""), username: str = Form("")):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        existing = find_user_by_auth0_sub(db, identity.sub)
        if existing:
            destination = _auth0_destination(db, existing, identity, request)
            if existing.is_active:
                return _login_auth0_user(request, db, existing)
            request.session.pop("user_id", None)
            return RedirectResponse(destination, status_code=303)
        if find_user_by_email(db, identity.email or "") and identity.email_verified is not True:
            request.session.pop("user_id", None)
            return RedirectResponse("/auth/verificar-email", status_code=303)
        display, key, profile_error = parse_profile_draft(name, username)
        form = {"name": display, "username": key}
        if profile_error:
            return _auth0_gate_page(
                request,
                "auth0_onboard.html",
                identity,
                {"error": profile_error, "suggestions": [], "form": form, "signup_step": "perfil"},
                status_code=400,
            )
        if username_taken(db, key):
            return _auth0_gate_page(
                request,
                "auth0_onboard.html",
                identity,
                {
                    "error": "Esse @ já está em uso. Que tal um destes?",
                    "suggestions": suggest_usernames(key, taken_keys(db)),
                    "form": form,
                    "signup_step": "perfil",
                },
                status_code=400,
            )
        payload = _auth0_pending_payload(request)
        payload["profile_name"] = display
        payload["profile_username"] = key
        request.session["auth0_pending"] = payload
        request.session["auth_provider"] = "auth0"
        request.session.pop("user_id", None)
        if identity.email_verified is not True:
            return RedirectResponse("/auth/verificar-email", status_code=303)
        outcome, user_id, error, suggestions = complete_auth0_onboarding(
            db,
            sub=identity.sub,
            email=identity.email,
            email_verified=identity.email_verified,
            name=display,
            username=key,
        )
        user = db.get(User, user_id) if user_id else None
        if outcome == "active" and user:
            return _login_auth0_user(request, db, user)
        if outcome == "awaiting":
            return _awaiting_auth0_user(request)
        if outcome == "expired":
            return _expired_auth0_user(request)
        if outcome == "unverified":
            return RedirectResponse("/auth/verificar-email", status_code=303)
        return _auth0_gate_page(
            request,
            "auth0_onboard.html",
            identity,
            {"error": error, "suggestions": suggestions, "form": form, "signup_step": "perfil"},
            status_code=400,
        )
    finally:
        db.close()


@app.get("/auth/aguardando", response_class=HTMLResponse)
def auth0_awaiting_page(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        destination = _auth0_destination(db, user, identity, request)
        if destination == "/" and user and user.is_active and (user.auth0_sub or "").strip() == identity.sub:
            return _login_auth0_user(request, db, user)
        if destination != "/auth/aguardando":
            return RedirectResponse(destination, status_code=303)
        request.session.pop("user_id", None)
        return _auth0_gate_page(
            request,
            "auth0_awaiting.html",
            identity,
            {"profile": user, "signup_step": "aprovacao"},
        )
    finally:
        db.close()


@app.get("/auth/nao-aprovado", response_class=HTMLResponse)
def auth0_rejected_page(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        destination = _auth0_destination(db, user, identity, request)
        if destination != "/auth/nao-aprovado":
            return RedirectResponse(destination, status_code=303)
        request.session.pop("user_id", None)
        return _auth0_gate_page(request, "auth0_rejected.html", identity, {"profile": user})
    finally:
        db.close()


def _review_followup_redirect(status: str | None) -> str:
    if status == REVIEW_PENDING:
        return "/auth/revisao-solicitada"
    if status == REVIEW_REJECTED:
        return "/auth/revisao-nao-aprovada"
    if status == REVIEW_APPROVED:
        return "/"
    return "/auth/nao-aprovado"


@app.get("/auth/revisao", response_class=HTMLResponse)
def auth0_review_form(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        destination = _auth0_destination(db, user, identity, request)
        if destination not in {"/auth/nao-aprovado", "/auth/revisao"}:
            return RedirectResponse(destination, status_code=303)
        request.session.pop("user_id", None)
        return _auth0_gate_page(
            request,
            "auth0_review_form.html",
            identity,
            {
                "error": request.query_params.get("error"),
                "message": "",
                "message_max": REVIEW_MESSAGE_MAX,
                "profile": user,
            },
        )
    finally:
        db.close()


@app.post("/auth/revisao")
def auth0_review_submit(request: Request, message: str = Form("")):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        if not user:
            return RedirectResponse(_auth0_destination(db, user, identity, request), status_code=303)
        try:
            status, _review_id = create_registration_review(db, user.id, message)
        except HTTPException as exc:
            if exc.status_code == 400:
                return RedirectResponse("/auth/revisao?error=" + quote(str(exc.detail)), status_code=303)
            raise
        if status is None:
            return RedirectResponse(_auth0_destination(db, user, identity, request), status_code=303)
        return RedirectResponse(_review_followup_redirect(status), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 400:
            return RedirectResponse("/auth/revisao?error=" + quote(str(exc.detail)), status_code=303)
        raise
    finally:
        db.close()


@app.get("/auth/revisao-solicitada", response_class=HTMLResponse)
def auth0_review_awaiting_page(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        destination = _auth0_destination(db, user, identity, request)
        if destination != "/auth/revisao-solicitada":
            return RedirectResponse(destination, status_code=303)
        request.session.pop("user_id", None)
        return _auth0_gate_page(request, "auth0_review_awaiting.html", identity, {"profile": user})
    finally:
        db.close()


@app.get("/auth/revisao-nao-aprovada", response_class=HTMLResponse)
def auth0_review_rejected_page(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        destination = _auth0_destination(db, user, identity, request)
        if destination != "/auth/revisao-nao-aprovada":
            return RedirectResponse(destination, status_code=303)
        request.session.pop("user_id", None)
        return _auth0_gate_page(request, "auth0_review_rejected.html", identity, {"profile": user})
    finally:
        db.close()


@app.get("/auth/expirada", response_class=HTMLResponse)
def auth0_expired_page(request: Request):
    identity = _auth0_pending_identity(request)
    if not identity:
        return RedirectResponse("/login?error=Não+há+identidade+Auth0+pendente", status_code=303)
    db = db_session()
    try:
        user = find_user_by_auth0_sub(db, identity.sub)
        destination = _auth0_destination(db, user, identity, request)
        if destination != "/auth/expirada":
            return RedirectResponse(destination, status_code=303)
        request.session.pop("user_id", None)
        return _auth0_gate_page(request, "auth0_expired.html", identity, {"profile": user})
    finally:
        db.close()


def _admin_http_redirect(exc: HTTPException, fallback: str = "/"):
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    if exc.status_code == 403:
        return RedirectResponse("/?error=" + quote("Acesso restrito à administração"), status_code=303)
    if exc.status_code == 404:
        return RedirectResponse("/admin/cadastros?error=" + quote(str(exc.detail)), status_code=303)
    if exc.status_code == 400:
        return RedirectResponse(f"{fallback}?error=" + quote(str(exc.detail)), status_code=303)
    raise exc


@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request):
    return admin_registrations(request)


@app.get("/admin/cadastros", response_class=HTMLResponse)
def admin_registrations(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        require_site_admin(user)
        aba = request.query_params.get("aba") or "pendentes"
        if aba not in {"pendentes", "revisoes"}:
            aba = "pendentes"
        pending = list_pending_registrations(db)
        reviews = list_pending_reviews(db) if aba == "revisoes" else []
        db.commit()
        return templates.TemplateResponse(
            request,
            "admin_registrations.html",
            {
                "user": user,
                "pending": pending,
                "reviews": reviews,
                "aba": aba,
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
            },
        )
    except HTTPException as exc:
        return _admin_http_redirect(exc)
    finally:
        db.close()


@app.get("/admin/cadastros/{request_id}", response_class=HTMLResponse)
def admin_registration_detail(request: Request, request_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_site_admin(user)
        item = get_registration(db, request_id)
        if not item or not item.user:
            raise HTTPException(status_code=404, detail="Solicitação não encontrada")
        db.commit()
        return templates.TemplateResponse(
            request,
            "admin_registration_detail.html",
            {
                "user": user,
                "item": item,
                "person": item.user,
                "status_label": STATUS_LABELS.get(item.status, item.status),
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
            },
        )
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/cadastros")
    finally:
        db.close()


@app.post("/admin/cadastros/{request_id}/aprovar")
def admin_registration_approve(request: Request, request_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_site_admin(user)
        status = approve_registration(db, request_id, user.id)
        if status == STATUS_EXPIRED:
            return RedirectResponse(
                f"/admin/cadastros/{request_id}?error=" + quote(EXPIRED_DECISION_MESSAGE),
                status_code=303,
            )
        return RedirectResponse("/admin/cadastros?ok=" + quote("Solicitação aprovada."), status_code=303)
    except HTTPException as exc:
        return _admin_http_redirect(exc, f"/admin/cadastros/{request_id}")
    finally:
        db.close()


@app.post("/admin/cadastros/{request_id}/recusar")
def admin_registration_reject(request: Request, request_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_site_admin(user)
        status = reject_registration(db, request_id, user.id)
        if status == STATUS_EXPIRED:
            return RedirectResponse(
                f"/admin/cadastros/{request_id}?error=" + quote(EXPIRED_DECISION_MESSAGE),
                status_code=303,
            )
        return RedirectResponse("/admin/cadastros?ok=" + quote("Solicitação recusada."), status_code=303)
    except HTTPException as exc:
        return _admin_http_redirect(exc, f"/admin/cadastros/{request_id}")
    finally:
        db.close()


@app.get("/admin/cadastros/revisoes/{review_id}", response_class=HTMLResponse)
def admin_registration_review_detail(request: Request, review_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_site_admin(user)
        item = get_registration_review(db, review_id)
        if not item or not item.user or not item.request:
            raise HTTPException(status_code=404, detail="Revisão não encontrada")
        return templates.TemplateResponse(
            request,
            "admin_registration_review_detail.html",
            {
                "user": user,
                "item": item,
                "person": item.user,
                "status_label": REVIEW_LABELS.get(item.status, item.status),
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
            },
        )
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/cadastros?aba=revisoes")
    finally:
        db.close()


@app.post("/admin/cadastros/revisoes/{review_id}/aprovar-acesso")
def admin_registration_review_approve(request: Request, review_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_site_admin(user)
        status, applied = approve_registration_review(db, review_id, user.id)
        if not applied:
            return RedirectResponse(
                f"/admin/cadastros/revisoes/{review_id}?error=" + quote(REVIEW_ALREADY_DECIDED_MESSAGE),
                status_code=303,
            )
        return RedirectResponse(
            "/admin/cadastros?aba=revisoes&ok=" + quote("Acesso aprovado após revisão."),
            status_code=303,
        )
    except HTTPException as exc:
        return _admin_http_redirect(exc, f"/admin/cadastros/revisoes/{review_id}")
    finally:
        db.close()


@app.post("/admin/cadastros/revisoes/{review_id}/manter-recusa")
def admin_registration_review_reject(request: Request, review_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        require_site_admin(user)
        status, applied = reject_registration_review(db, review_id, user.id)
        if not applied:
            return RedirectResponse(
                f"/admin/cadastros/revisoes/{review_id}?error=" + quote(REVIEW_ALREADY_DECIDED_MESSAGE),
                status_code=303,
            )
        return RedirectResponse(
            "/admin/cadastros?aba=revisoes&ok=" + quote("Recusa mantida."),
            status_code=303,
        )
    except HTTPException as exc:
        return _admin_http_redirect(exc, f"/admin/cadastros/revisoes/{review_id}")
    finally:
        db.close()


@app.get("/auth/logout")
def auth0_logout(request: Request):
    _end_watch_club_session(request)
    if auth0_enabled():
        try:
            return RedirectResponse(auth0_logout_url(), status_code=303)
        except Auth0Error:
            pass
    return RedirectResponse("/", status_code=303)


@app.get("/auth/{provider}")
def oauth_start(request: Request, provider: str):
    if provider in {"google", "facebook"}:
        closed = _legacy_auth_to_auth0(request)
        if closed:
            return closed
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
    if provider in {"google", "facebook"}:
        closed = _legacy_auth_to_auth0(request)
        if closed:
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_provider", None)
            return closed
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
        request.session.pop("auth_provider", None)
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
            {"user": user, "club": None, "error": request.query_params.get("error"), "mode": "create"},
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
    cover_preset: str = Form(""),
    icon_preset: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        club_name = name.strip()
        club_description = description.strip()
        club_rules = rules.strip()
        enforce_text(db, user, club_name, surface=SURFACE_PUBLIC_NAME, origin="club")
        enforce_text(db, user, club_description, surface=SURFACE_PUBLIC_TEXT, origin="club")
        enforce_text(db, user, club_rules, surface=SURFACE_PUBLIC_TEXT, origin="club")
        image_name = await save_cover_image(cover_file)
        icon_name = await save_club_icon(icon_file)
        for stored_name, locator, origin in (
            (image_name, stored_cover_path, "club_cover"),
            (icon_name, stored_icon_path, "club_icon"),
        ):
            path = locator(stored_name) if stored_name else None
            if path:
                enforce_image(db, user, path.read_bytes(), mime="image/*", origin=origin)
        cover_pixel, cover_style = attach_preset(
            image_name, stored_cover_path, uploads_dir() / "clubs", cover_preset
        )
        icon_pixel, icon_style = attach_preset(
            icon_name, stored_icon_path, uploads_dir() / "club-icons", icon_preset
        )
        club = Club(
            name=club_name,
            join_code=make_join_code(),
            owner_id=user.id,
            is_closed=bool(is_closed),
            description=club_description,
            rules=club_rules,
            cover_color=valid_cover_color(cover_color),
            cover_image=image_name,
            cover_style=cover_style,
            cover_pixel=cover_pixel,
            icon_image=icon_name,
            icon_style=icon_style,
            icon_pixel=icon_pixel,
        )
        db.add(club)
        db.flush()
        db.add(ClubMember(club_id=club.id, user_id=user.id, role=ROLE_ADMIN, support_perms=""))
        db.commit()
        return RedirectResponse(f"/clubs/{club.id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse("/clubs/novo?error=" + quote(str(exc.detail)), status_code=303)
        raise
    finally:
        db.close()


@app.get("/sobre", response_class=HTMLResponse)
def about_page(request: Request):
    db = db_session()
    try:
        user = current_user(request, db)
        if user:
            return RedirectResponse("/conta#sobre", status_code=303)
        return templates.TemplateResponse(
            request,
            "about.html",
            {"user": None},
        )
    finally:
        db.close()


@app.get("/regras", response_class=HTMLResponse)
def community_rules_page(request: Request):
    db = db_session()
    try:
        user = current_user(request, db)
        if user and is_restricted(user):
            return templates.TemplateResponse(request, "community_rules.html", {"user": user})
        return templates.TemplateResponse(
            request,
            "community_rules.html",
            {"user": user},
        )
    finally:
        db.close()


@app.get("/seguranca", response_class=HTMLResponse)
def safety_hub(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        events = [
            item
            for item in user_moderation_history(db, user.id)
            if item.counts and item.action in {"warn", "suspend", "ban"}
        ]
        reports = list_own_reports(db, user.id)
        return templates.TemplateResponse(
            request,
            "safety.html",
            {
                "user": user,
                "reports": reports,
                "report_counts": {item.id: own_report_counts(item) for item in reports},
                "blocked_users": list_blocked_users(db, user.id),
                "events": events,
                "reason_labels": REASON_LABELS,
                "target_labels": TARGET_LABELS,
                "status_labels": OWN_STATUS_LABELS,
                "action_labels": PENALTY_ACTION_LABELS,
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
            },
        )
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


def _session_user_ids(request: Request) -> list[int]:
    try:
        return parse_id_list(request.session.get("report_user_ids") or [])
    except HTTPException:
        return []


@app.get("/seguranca/denunciar/usuario", response_class=HTMLResponse)
def safety_pick_user(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        selected_ids = _session_user_ids(request)
        selected = [db.get(User, item) for item in selected_ids]
        selected = [item for item in selected if item and item.is_active]
        return templates.TemplateResponse(
            request,
            "safety_pick_user.html",
            {
                "user": user,
                "friends": list_friends(db, user.id),
                "selected": selected,
                "error": request.query_params.get("error"),
            },
        )
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/seguranca/denunciar/usuario")
def safety_start_user_report(
    request: Request,
    username: str = Form(""),
    action: str = Form("add"),
    user_id: int = Form(0),
):
    db = db_session()
    try:
        user = login_required(request, db)
        ids = _session_user_ids(request)
        if action == "remove":
            ids = [item for item in ids if item != user_id]
            request.session["report_user_ids"] = ids
            return RedirectResponse("/seguranca/denunciar/usuario", status_code=303)
        if action == "continue":
            if not ids:
                raise HTTPException(status_code=400, detail="Adicione pelo menos uma conta")
            qs = "&".join(f"envolvidos={item}" for item in ids)
            request.session.pop("report_user_ids", None)
            return RedirectResponse(
                f"/denunciar?tipo=user&id={ids[0]}&{qs}&next={quote('/seguranca')}",
                status_code=303,
            )
        person = locate_user_for_report(db, user, username)
        if person.id not in ids:
            ids.append(person.id)
        request.session["report_user_ids"] = ids
        return RedirectResponse("/seguranca/denunciar/usuario", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(
            "/seguranca/denunciar/usuario?error=" + quote(str(exc.detail)),
            status_code=303,
        )
    finally:
        db.close()


@app.get("/seguranca/denunciar/clube", response_class=HTMLResponse)
def safety_pick_club(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        return templates.TemplateResponse(
            request,
            "safety_pick_club.html",
            {
                "user": user,
                "clubs": _member_club_nav(db, user.id),
                "error": request.query_params.get("error"),
            },
        )
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/seguranca/denunciar/clube")
def safety_start_club_report(request: Request, club_id: int = Form(0)):
    db = db_session()
    try:
        user = login_required(request, db)
        club = locate_member_club(db, user, club_id)
        return RedirectResponse(
            f"/denunciar?tipo=club&id={club.id}&club_scope={club.id}&next={quote('/seguranca')}",
            status_code=303,
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(
            "/seguranca/denunciar/clube?error=" + quote(str(exc.detail)),
            status_code=303,
        )
    finally:
        db.close()


@app.post("/clubs/{club_id}/denuncias/membro")
def club_start_member_report(
    request: Request,
    club_id: int,
    member_user_id: int = Form(0),
    member_user_ids: list[str] = Form(default=[]),
):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_member(db, club_id, user.id)
        ids = parse_id_list(member_user_ids or ([member_user_id] if member_user_id else []))
        if not ids:
            raise HTTPException(status_code=400, detail="Selecione pelo menos um membro")
        people = [locate_club_member_for_report(db, user, club, item) for item in ids]
        dest = quote(f"/clubs/{club.id}?aba=denuncias")
        qs = "&".join(f"envolvidos={item.id}" for item in people)
        return RedirectResponse(
            f"/denunciar?tipo=user&id={people[0].id}&{qs}&club_scope={club.id}&next={dest}",
            status_code=303,
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        return RedirectResponse(
            f"/clubs/{club_id}?aba=denuncias&error={quote(str(exc.detail))}",
            status_code=303,
        )
    finally:
        db.close()


@app.get("/conta-restrita", response_class=HTMLResponse)
def restricted_account_page(request: Request):
    db = db_session()
    try:
        user_id = request.session.get("user_id")
        user = db.get(User, user_id) if user_id else None
        if user is None or not user.is_active:
            return RedirectResponse("/login", status_code=303)
        kind = restriction_kind(user)
        if not kind:
            return RedirectResponse("/", status_code=303)
        events = [item for item in user_moderation_history(db, user.id) if item.counts and item.reversed_at is None]
        return templates.TemplateResponse(
            request,
            "account_restricted.html",
            {
                "user": user,
                "kind": kind,
                "events": events,
                "warning_count": counting_violation_count(db, user.id),
            },
        )
    finally:
        db.close()


def _suggestion_page(request: Request, db, user, **extra):
    return templates.TemplateResponse(
        request,
        "suggestions.html",
        {
            "user": user,
            "items": list_own_suggestions(db, user.id),
            "status_labels": SUGGESTION_STATUS_LABELS,
            "title_max": TITLE_MAX,
            "description_max": DESCRIPTION_MAX,
            "error": extra.get("error") or request.query_params.get("error"),
            "ok": extra.get("ok") or request.query_params.get("ok"),
        },
    )


@app.get("/sugestoes", response_class=HTMLResponse)
def suggestions_page(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        return _suggestion_page(request, db, user)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/sugestoes")
def create_suggestion_route(request: Request, title: str = Form(""), description: str = Form("")):
    db = db_session()
    try:
        user = login_required(request, db)
        create_suggestion(db, user, title, description)
        return RedirectResponse("/sugestoes?ok=" + quote("Sugestão enviada"), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse("/sugestoes?error=" + quote(str(exc.detail)), status_code=303)
        raise
    finally:
        db.close()


@app.get("/admin/sugestoes", response_class=HTMLResponse)
def admin_suggestions_page(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        require_site_admin(user)
        archived = (request.query_params.get("aba") or "") == "arquivadas"
        raw_open = (request.query_params.get("sugestao") or "").strip()
        open_id = int(raw_open) if raw_open.isdigit() else None
        if open_id:
            target = db.get(Suggestion, open_id)
            if target and target.is_archived and not archived:
                return RedirectResponse(f"/admin/sugestoes?aba=arquivadas&sugestao={open_id}", status_code=303)
            if target and not target.is_archived and archived:
                return RedirectResponse(f"/admin/sugestoes?sugestao={open_id}", status_code=303)
        return templates.TemplateResponse(
            request,
            "admin_suggestions.html",
            {
                "user": user,
                "items": list_admin_suggestions(db, archived=archived),
                "archived": archived,
                "open_id": open_id,
                "status_labels": SUGGESTION_STATUS_LABELS,
                "statuses": [(key, SUGGESTION_STATUS_LABELS[key]) for key in SUGGESTION_STATUSES],
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
            },
        )
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/sugestoes")
    finally:
        db.close()


@app.post("/admin/sugestoes/{suggestion_id}/status")
def admin_suggestion_status(request: Request, suggestion_id: int, status: str = Form(""), next: str = Form("")):
    db = db_session()
    try:
        user = login_required(request, db)
        set_suggestion_status(db, user, suggestion_id, status)
        dest = _safe_next(next, f"/admin/sugestoes?sugestao={suggestion_id}")
        join = "&" if "?" in dest else "?"
        return RedirectResponse(dest + join + "ok=" + quote("Status atualizado"), status_code=303)
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/sugestoes")
    finally:
        db.close()


@app.post("/admin/sugestoes/{suggestion_id}/arquivar")
def admin_suggestion_archive(request: Request, suggestion_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        archive_suggestion(db, user, suggestion_id)
        return RedirectResponse("/admin/sugestoes?ok=" + quote("Sugestão arquivada"), status_code=303)
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/sugestoes")
    finally:
        db.close()


def _admin_reports_page(request: Request, db, user, **extra):
    aba = extra.get("aba") or request.query_params.get("aba") or "pendentes"
    if aba not in {"pendentes", "resolvidas", "contestacoes"}:
        aba = "pendentes"
    open_id = extra.get("open_id")
    if open_id is None:
        raw = (request.query_params.get("caso") or request.query_params.get("contestacao") or "").strip()
        open_id = int(raw) if raw.isdigit() else None
    if aba == "contestacoes":
        items = list_appeals(db, pending=True)
        done = list_appeals(db, pending=False)
        cases = []
    else:
        items = []
        done = []
        cases = list_cases(db, resolved=aba == "resolvidas")
    histories = {}
    message_snaps = {}
    for case in cases:
        people_ids = [row.user_id for row in (case.involved_users or [])]
        if case.reported_user_id:
            people_ids.append(case.reported_user_id)
        for user_id in people_ids:
            if user_id and user_id not in histories:
                histories[user_id] = user_moderation_history(db, user_id)
        message_snaps[case.id] = chronological_message_snapshots(case)
    return templates.TemplateResponse(
        request,
        "admin_reports.html",
        {
            "user": user,
            "aba": aba,
            "cases": cases,
            "appeals": items if aba == "contestacoes" else [],
            "closed_appeals": done if aba == "contestacoes" else [],
            "open_id": open_id,
            "reason_labels": REASON_LABELS,
            "target_labels": TARGET_LABELS,
            "histories": histories,
            "snapshots": {case.id: load_snapshot(case.snapshot_json) for case in cases},
            "message_snaps": message_snaps,
            "outcome_labels": USER_OUTCOME_LABELS,
            "error": extra.get("error") or request.query_params.get("error"),
            "ok": extra.get("ok") or request.query_params.get("ok"),
        },
    )


@app.get("/admin/denuncias", response_class=HTMLResponse)
def admin_reports(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        require_site_admin(user)
        return _admin_reports_page(request, db, user)
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/denuncias")
    finally:
        db.close()


def _admin_case_action(request: Request, case_id: int, action: str, hours: str = ""):
    db = db_session()
    try:
        admin = login_required(request, db)
        require_site_admin(admin)
        case = get_case(db, case_id)
        if case.status != "pending":
            raise HTTPException(status_code=400, detail="Esta denúncia já foi resolvida")
        person = case.reported_user
        if action == "ignorar":
            resolve_case(db, case, admin, "ignored")
        elif action == "remover":
            remove_reported_content(db, case)
            resolve_case(db, case, admin, "removed")
        elif action == "advertir":
            if person is None:
                raise HTTPException(status_code=400, detail="Não há usuário para advertir")
            apply_violation(
                db,
                person,
                category=case.reason,
                origin=ORIGIN_ADMIN,
                evidence=case.snapshot_json,
                counts=True,
                case_id=case.id,
                actor_id=admin.id,
            )
            resolve_case(db, case, admin, "warned")
        elif action == "suspender":
            if person is None:
                raise HTTPException(status_code=400, detail="Não há usuário para suspender")
            mapping = {"24": 24, "168": 168, "720": 720, "0": 0}
            if hours not in mapping:
                raise HTTPException(status_code=400, detail="Prazo de suspensão inválido")
            apply_violation(
                db,
                person,
                category=case.reason,
                origin=ORIGIN_ADMIN,
                evidence=case.snapshot_json,
                counts=True,
                case_id=case.id,
                actor_id=admin.id,
                suspend_hours=mapping[hours],
            )
            resolve_case(db, case, admin, "banned" if hours == "0" else "suspended")
        else:
            raise HTTPException(status_code=400, detail="Ação inválida")
        db.commit()
        return RedirectResponse("/admin/denuncias?ok=" + quote("Denúncia atualizada"), status_code=303)
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/denuncias")
    finally:
        db.close()


@app.post("/admin/denuncias/{case_id}/ignorar")
def admin_report_ignore(request: Request, case_id: int):
    return _admin_case_action(request, case_id, "ignorar")


@app.post("/admin/denuncias/{case_id}/remover")
def admin_report_remove(request: Request, case_id: int):
    return _admin_case_action(request, case_id, "remover")


@app.post("/admin/denuncias/{case_id}/advertir")
def admin_report_warn(request: Request, case_id: int):
    return _admin_case_action(request, case_id, "advertir")


@app.post("/admin/denuncias/{case_id}/suspender")
def admin_report_suspend(request: Request, case_id: int, hours: str = Form("24")):
    return _admin_case_action(request, case_id, "suspender", hours)


def _admin_case_user_action(request: Request, case_id: int, user_id: int, action: str, hours: str = ""):
    db = db_session()
    try:
        admin = login_required(request, db)
        require_site_admin(admin)
        case = get_case(db, case_id)
        if case.status != "pending":
            raise HTTPException(status_code=400, detail="Esta denúncia já foi resolvida")
        person = db.get(User, user_id)
        involved_ids = {row.user_id for row in (case.involved_users or [])}
        if case.reported_user_id:
            involved_ids.add(case.reported_user_id)
        if person is None or user_id not in involved_ids:
            raise HTTPException(status_code=400, detail="Este usuário não está neste caso")
        row = next((item for item in (case.involved_users or []) if item.user_id == user_id), None)
        evidence = case.snapshot_json
        if action == "nada":
            if row:
                row.outcome = "none"
        elif action == "advertir":
            apply_violation(
                db,
                person,
                category=case.reason,
                origin=ORIGIN_ADMIN,
                evidence=evidence,
                counts=True,
                case_id=case.id,
                actor_id=admin.id,
            )
            if row:
                row.outcome = "warned"
        elif action in {"suspender", "banir"}:
            mapping = {"24": 24, "168": 168, "720": 720, "0": 0}
            chosen = "0" if action == "banir" else hours
            if chosen not in mapping:
                raise HTTPException(status_code=400, detail="Prazo de suspensão inválido")
            apply_violation(
                db,
                person,
                category=case.reason,
                origin=ORIGIN_ADMIN,
                evidence=evidence,
                counts=True,
                case_id=case.id,
                actor_id=admin.id,
                suspend_hours=mapping[chosen],
            )
            if row:
                row.outcome = "banned" if chosen == "0" else "suspended"
        else:
            raise HTTPException(status_code=400, detail="Ação inválida")
        case.updated_at = utcnow()
        db.commit()
        return RedirectResponse(
            f"/admin/denuncias?caso={case.id}&ok=" + quote("Decisão registrada para este usuário"),
            status_code=303,
        )
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/denuncias")
    finally:
        db.close()


@app.post("/admin/denuncias/{case_id}/envolvidos/{user_id}/nada")
def admin_report_user_none(request: Request, case_id: int, user_id: int):
    return _admin_case_user_action(request, case_id, user_id, "nada")


@app.post("/admin/denuncias/{case_id}/envolvidos/{user_id}/advertir")
def admin_report_user_warn(request: Request, case_id: int, user_id: int):
    return _admin_case_user_action(request, case_id, user_id, "advertir")


@app.post("/admin/denuncias/{case_id}/envolvidos/{user_id}/suspender")
def admin_report_user_suspend(request: Request, case_id: int, user_id: int, hours: str = Form("")):
    return _admin_case_user_action(request, case_id, user_id, "suspender", hours)


@app.post("/admin/denuncias/{case_id}/envolvidos/{user_id}/banir")
def admin_report_user_ban(request: Request, case_id: int, user_id: int):
    return _admin_case_user_action(request, case_id, user_id, "banir")


@app.post("/admin/contestacoes/{appeal_id}/manter")
def admin_appeal_keep(request: Request, appeal_id: int):
    db = db_session()
    try:
        admin = login_required(request, db)
        require_site_admin(admin)
        appeal = get_appeal(db, appeal_id)
        if appeal.status != "pending":
            raise HTTPException(status_code=400, detail="Esta contestação já foi decidida")
        from app.accounts import utcnow as now_utc

        appeal.status = APPEAL_KEPT
        appeal.decided_at = now_utc()
        appeal.decided_by_id = admin.id
        db.commit()
        return RedirectResponse(
            "/admin/denuncias?aba=contestacoes&ok=" + quote("Penalidade mantida"),
            status_code=303,
        )
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/denuncias?aba=contestacoes")
    finally:
        db.close()


@app.post("/admin/contestacoes/{appeal_id}/remover")
def admin_appeal_remove(request: Request, appeal_id: int):
    db = db_session()
    try:
        admin = login_required(request, db)
        require_site_admin(admin)
        appeal = get_appeal(db, appeal_id)
        if appeal.status != "pending":
            raise HTTPException(status_code=400, detail="Esta contestação já foi decidida")
        reverse_event(db, appeal.event, admin)
        from app.accounts import utcnow as now_utc

        appeal.status = APPEAL_REMOVED
        appeal.decided_at = now_utc()
        appeal.decided_by_id = admin.id
        db.commit()
        return RedirectResponse(
            "/admin/denuncias?aba=contestacoes&ok=" + quote("Penalidade removida"),
            status_code=303,
        )
    except HTTPException as exc:
        return _admin_http_redirect(exc, "/admin/denuncias?aba=contestacoes")
    finally:
        db.close()


def _report_query(tipo: str, alvo: int, dest: str, extra: dict | None = None) -> str:
    parts = [f"tipo={quote(tipo)}", f"id={alvo}", f"next={quote(dest)}"]
    extra = extra or {}
    for user_id in extra.get("user_ids") or []:
        parts.append(f"envolvidos={user_id}")
    for message_id in extra.get("message_ids") or []:
        parts.append(f"mensagens={message_id}")
    if extra.get("club_scope_id"):
        parts.append(f"club_scope={extra['club_scope_id']}")
    if extra.get("error"):
        parts.append(f"error={quote(str(extra['error']))}")
    return "/denunciar?" + "&".join(parts)


@app.get("/denunciar", response_class=HTMLResponse)
def report_form(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        target_type = (request.query_params.get("tipo") or "").strip()
        raw_id = (request.query_params.get("id") or "").strip()
        target_id = int(raw_id) if raw_id.isdigit() else 0
        extra_ids = parse_id_list(list(request.query_params.getlist("envolvidos")))
        message_ids = parse_id_list(list(request.query_params.getlist("mensagens")))
        club_scope = request.query_params.get("club_scope") or ""
        club_scope_id = int(club_scope) if club_scope.isdigit() else 0
        if target_type not in TARGET_LABELS or not target_id:
            raise HTTPException(status_code=400, detail="Conteúdo inválido para denúncia")
        next_url = _safe_next(request.query_params.get("next"), "/")
        preview = preview_report(
            db,
            user,
            target_type=target_type,
            target_id=target_id,
            extra_user_ids=extra_ids,
            message_ids=message_ids,
            club_scope_id=club_scope_id or None,
        )
        return templates.TemplateResponse(
            request,
            "report_form.html",
            {
                "user": user,
                "target_type": preview["target_type"],
                "target_id": preview["target_id"],
                "target_label": preview["target_label"],
                "people": preview["people"],
                "locked_ids": preview["locked_ids"],
                "messages": preview["messages"],
                "message_ids": preview["message_ids"],
                "club": preview["club"],
                "club_scope_id": preview["club_scope_id"] or 0,
                "reasons": [(key, REASON_LABELS[key]) for key in REASONS],
                "next": next_url,
                "note_min": REPORT_NOTE_MIN,
                "note_max": REPORT_NOTE_MAX,
                "max_files": MAX_REPORT_ATTACHMENTS,
                "error": request.query_params.get("error"),
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse("/?error=" + quote(str(exc.detail)), status_code=303)
    finally:
        db.close()


@app.post("/denunciar/envolvido")
def report_add_involved(request: Request, username: str = Form(""), tipo: str = Form(""), alvo: int = Form(0), next: str = Form("/"), club_scope: int = Form(0), user_ids: list[str] = Form(default=[]), message_ids: list[str] = Form(default=[])):
    db = db_session()
    dest = _safe_next(next, "/")
    extras = {
        "user_ids": parse_id_list(user_ids),
        "message_ids": parse_id_list(message_ids),
        "club_scope_id": club_scope or None,
    }
    try:
        user = login_required(request, db)
        if club_scope:
            club = locate_member_club(db, user, club_scope)
            person = locate_club_member_for_report(db, user, club, locate_user_for_report(db, user, username).id)
        else:
            person = locate_user_for_report(db, user, username)
        if person.id not in extras["user_ids"]:
            extras["user_ids"].append(person.id)
        return RedirectResponse(_report_query(tipo, alvo, dest, extras), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        extras["error"] = exc.detail
        return RedirectResponse(_report_query(tipo, alvo, dest, extras), status_code=303)
    finally:
        db.close()


@app.post("/denunciar/mensagens")
def report_start_club_messages(
    request: Request,
    club_id: int = Form(0),
    message_ids: list[str] = Form(default=[]),
    next_url: str = Form(""),
):
    db = db_session()
    dest = _safe_next(next_url, f"/clubs/{club_id}?aba=chat")
    try:
        user = login_required(request, db)
        ids = parse_id_list(message_ids)
        if not ids:
            raise HTTPException(status_code=400, detail="Selecione pelo menos uma mensagem")
        if len(ids) > MAX_REPORT_MESSAGES:
            raise HTTPException(status_code=400, detail=f"Selecione no máximo {MAX_REPORT_MESSAGES} mensagens")
        from app.reports import collect_club_messages

        rows = collect_club_messages(db, user, ids)
        primary = next((item.id for item in rows if item.user_id != user.id), 0)
        if not primary:
            raise HTTPException(status_code=400, detail="Selecione ao menos uma mensagem de outra pessoa")
        extras = {"message_ids": [item.id for item in rows], "club_scope_id": club_id}
        return RedirectResponse(_report_query(TARGET_CLUB_MESSAGE, primary, dest, extras), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(dest + ("&" if "?" in dest else "?") + "error=" + quote(str(exc.detail)), status_code=303)
    finally:
        db.close()


@app.post("/denunciar/mensagens-dm")
def report_start_dm_messages(
    request: Request,
    username: str = Form(""),
    message_ids: list[str] = Form(default=[]),
    next_url: str = Form(""),
):
    db = db_session()
    dest = _safe_next(next_url, f"/mensagens/{username}")
    try:
        user = login_required(request, db)
        ids = parse_id_list(message_ids)
        if not ids:
            raise HTTPException(status_code=400, detail="Selecione pelo menos uma mensagem")
        from app.reports import collect_direct_messages

        rows = collect_direct_messages(db, user, ids)
        primary = next((item.id for item in rows if item.sender_id != user.id), 0)
        if not primary:
            raise HTTPException(status_code=400, detail="Selecione ao menos uma mensagem de outra pessoa")
        extras = {"message_ids": [item.id for item in rows]}
        return RedirectResponse(_report_query(TARGET_DM, primary, dest, extras), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(dest + ("&" if "?" in dest else "?") + "error=" + quote(str(exc.detail)), status_code=303)
    finally:
        db.close()


@app.post("/denunciar")
async def submit_report(request: Request):
    form = await request.form()
    tipo = str(form.get("tipo") or "")
    reason = str(form.get("reason") or "")
    explanation = str(form.get("explanation") or "")
    next = str(form.get("next") or "/")
    raw_alvo = str(form.get("alvo") or "0")
    alvo = int(raw_alvo) if raw_alvo.isdigit() else 0
    raw_scope = str(form.get("club_scope") or "0")
    club_scope = int(raw_scope) if raw_scope.isdigit() else 0
    db = db_session()
    dest = _safe_next(next, "/")
    extras = {"user_ids": [], "message_ids": [], "club_scope_id": club_scope or None}
    try:
        extras["user_ids"] = parse_id_list(list(form.getlist("user_ids")))
        extras["message_ids"] = parse_id_list(list(form.getlist("message_ids")))
        user = login_required(request, db)
        uploads = [
            item
            for item in form.getlist("evidence")
            if item is not None and getattr(item, "filename", None)
        ]
        if len(uploads) > MAX_REPORT_ATTACHMENTS:
            raise HTTPException(status_code=400, detail=f"Envie no máximo {MAX_REPORT_ATTACHMENTS} prints")
        names = [await save_report_evidence_image(item) for item in uploads]
        row = create_report(
            db,
            user,
            target_type=tipo,
            target_id=alvo,
            reason=reason,
            explanation=explanation,
            extra_user_ids=extras["user_ids"],
            message_ids=extras["message_ids"],
            attachment_names=names,
            club_scope_id=club_scope or None,
        )
        case = get_case(db, row.case_id)
        usernames = []
        for item in case.involved_users or []:
            if item.user:
                usernames.append(item.user.username)
        if not usernames and case.reported_user:
            usernames.append(case.reported_user.username)
        qs = "&".join(f"user={quote(name)}" for name in usernames)
        return RedirectResponse(f"/denunciar/ok?{qs}&next={quote(dest)}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        extras["error"] = exc.detail
        return RedirectResponse(_report_query(tipo, alvo, dest, extras), status_code=303)
    finally:
        db.close()


@app.get("/denunciar/ok", response_class=HTMLResponse)
def report_thanks(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        names = [item.strip() for item in request.query_params.getlist("user") if item.strip()]
        people = []
        for name in names:
            person = find_active_user(db, name)
            if person and person.id != user.id:
                people.append(person)
        return templates.TemplateResponse(
            request,
            "report_thanks.html",
            {
                "user": user,
                "block_username": names[0] if names else "",
                "block_people": people,
                "next": _safe_next(request.query_params.get("next"), "/"),
            },
        )
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.get("/denuncias/anexos/{attachment_id}")
def report_attachment(request: Request, attachment_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        item = get_report_attachment(db, attachment_id)
        if not can_view_report_attachment(user, item):
            raise HTTPException(status_code=404, detail="Anexo não encontrado")
        path = stored_report_evidence_path(item.filename)
        if path is None:
            raise HTTPException(status_code=404, detail="Anexo não encontrado")
        suffix = path.suffix.lower()
        media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
        return Response(path.read_bytes(), media_type=media.get(suffix, "application/octet-stream"))
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/u/{username}/bloquear")
def block_person(request: Request, username: str, next: str = Form("")):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        block_user(db, user.id, person.id)
        dest = _safe_next(next, f"/u/{person.username}")
        sep = "&" if "?" in dest else "?"
        return RedirectResponse(f"{dest}{sep}ok={quote('Usuário bloqueado')}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(f"/u/{username}?error={quote(str(exc.detail))}", status_code=303)
    finally:
        db.close()


@app.post("/conta/bloqueios/{username}/remover")
def unblock_person(request: Request, username: str, next: str = Form("")):
    db = db_session()
    dest = _safe_next(next, "/conta")
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        unblock_user(db, user.id, person.id)
        sep = "&" if "?" in dest else "?"
        return RedirectResponse(f"{dest}{sep}ok=" + quote("Usuário desbloqueado"), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(f"{dest}?error={quote(str(exc.detail))}" if "?" not in dest else f"{dest}&error={quote(str(exc.detail))}", status_code=303)
    finally:
        db.close()


@app.get("/contestacoes/{event_id}", response_class=HTMLResponse)
def appeal_form(request: Request, event_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        from app.models import ModerationEvent

        event = db.get(ModerationEvent, event_id)
        if event is None or event.user_id != user.id:
            raise HTTPException(status_code=404, detail="Penalidade não encontrada")
        return templates.TemplateResponse(
            request,
            "appeal_form.html",
            {
                "user": user,
                "event": event,
                "reasons": [(key, APPEAL_REASON_LABELS[key]) for key in APPEAL_REASONS],
                "explanation_min": EXPLANATION_MIN,
                "explanation_max": EXPLANATION_MAX,
                "error": request.query_params.get("error"),
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse("/?error=" + quote(str(exc.detail)), status_code=303)
    finally:
        db.close()


@app.post("/contestacoes/{event_id}")
async def submit_appeal(
    request: Request,
    event_id: int,
    reason: str = Form(""),
    explanation: str = Form(""),
    evidence: UploadFile | None = File(None),
):
    db = db_session()
    try:
        user = login_required(request, db)
        from app.models import ModerationEvent

        event = db.get(ModerationEvent, event_id)
        if event is None or event.user_id != user.id:
            raise HTTPException(status_code=404, detail="Penalidade não encontrada")
        filename = await save_appeal_image(evidence)
        create_appeal(db, user, event, reason=reason, explanation=explanation, filename=filename)
        dest = "/conta-restrita" if is_restricted(user) else "/conta"
        return RedirectResponse(dest + "?ok=" + quote("Solicitação de revisão enviada"), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(
            f"/contestacoes/{event_id}?error={quote(str(exc.detail))}",
            status_code=303,
        )
    finally:
        db.close()


@app.get("/contestacoes/{appeal_id}/anexo/{filename}")
def appeal_attachment(request: Request, appeal_id: int, filename: str):
    db = db_session()
    try:
        user = login_required(request, db)
        appeal = get_appeal(db, appeal_id)
        if user.id != appeal.user_id and not user.is_site_admin:
            raise HTTPException(status_code=403, detail="Acesso negado")
        if not any(item.filename == filename for item in appeal.attachments):
            raise HTTPException(status_code=404, detail="Anexo não encontrado")
        path = stored_appeal_path(filename)
        if path is None:
            raise HTTPException(status_code=404, detail="Anexo não encontrado")
        return Response(path.read_bytes(), media_type="image/jpeg")
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
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
                "blocked_users": list_blocked_users(db, user.id),
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
                    "blocked_users": list_blocked_users(db, user.id),
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
        try:
            enforce_text(db, user, display, surface=SURFACE_PUBLIC_NAME, origin="profile")
            enforce_text(db, user, key, surface=SURFACE_PUBLIC_NAME, origin="profile")
            enforce_text(db, user, (bio or "")[:BIO_MAX], surface=SURFACE_PUBLIC_TEXT, origin="profile")
        except HTTPException as exc:
            if exc.status_code == 400:
                return account_error(str(exc.detail))
            raise
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
async def update_avatar_photo(
    request: Request,
    photo: UploadFile | None = File(None),
    preset: str = Form("original"),
):
    db = db_session()
    try:
        user = login_required(request, db)
        filename = await save_avatar_photo(photo)
        if not filename:
            return RedirectResponse("/conta?error=Envie+uma+imagem+JPG,+PNG,+WEBP+ou+GIF", status_code=303)
        path = stored_upload_path(filename)
        if path:
            enforce_image(db, user, path.read_bytes(), mime="image/*", origin="avatar")
        if user.avatar_type == "upload":
            delete_upload(user.avatar_value)
        set_upload_avatar(user, filename)
        chosen = normalize_style(preset)
        pixel_name, style = attach_preset(
            filename, stored_upload_path, uploads_dir() / "avatars", chosen
        )
        user.avatar_style = style
        user.avatar_pixel = pixel_name
        user.avatar_pixel_status = "ready" if pixel_name else ("none" if style == STYLE_ORIGINAL else "failed")
        db.commit()
        return RedirectResponse("/conta?ok=Foto+de+perfil+atualizada", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse("/conta?error=" + quote(str(exc.detail)), status_code=303)
        raise
    finally:
        db.close()


@app.post("/conta/avatar/estilo")
def update_avatar_style(request: Request, style: str = Form("")):
    db = db_session()
    try:
        user = login_required(request, db)
        try:
            chosen = require_style(style)
        except PixelArtError as exc:
            return RedirectResponse("/conta?error=" + quote(str(exc)), status_code=303)
        if user.avatar_type != "upload":
            return RedirectResponse(
                "/conta?error=" + quote("A estilização vale para fotos enviadas. Envie uma foto primeiro."),
                status_code=303,
            )
        source = stored_upload_path(user.avatar_value)
        if source is None:
            user.avatar_pixel_status = "none"
            db.commit()
            return RedirectResponse(
                "/conta?error=" + quote("A estilização vale para fotos enviadas. Envie uma foto primeiro."),
                status_code=303,
            )
        if user.avatar_pixel:
            delete_upload(user.avatar_pixel)
            user.avatar_pixel = None
        if chosen == STYLE_ORIGINAL:
            user.avatar_style = STYLE_ORIGINAL
            user.avatar_pixel_status = "none"
            db.commit()
            return RedirectResponse("/conta?ok=" + quote("Estilo original salvo"), status_code=303)
        try:
            dest_name = f"{secrets.token_hex(12)}.png"
            generate_derivative(source, source.parent / dest_name, preset=chosen)
        except PixelArtError as exc:
            user.avatar_style = STYLE_ORIGINAL
            user.avatar_pixel_status = "failed"
            db.commit()
            return RedirectResponse("/conta?error=" + quote(str(exc)), status_code=303)
        user.avatar_pixel = dest_name
        user.avatar_pixel_status = "ready"
        user.avatar_style = chosen
        db.commit()
        return RedirectResponse("/conta?ok=" + quote("Estilo da imagem salvo"), status_code=303)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/imagens/previsualizar")
async def preview_image_style(
    request: Request,
    photo: UploadFile | None = File(None),
    preset: str = Form("original"),
):
    db = db_session()
    try:
        login_required(request, db)
        if not photo or not photo.filename:
            raise HTTPException(status_code=400, detail="Envie uma imagem.")
        data = await photo.read()
        if not data or len(data) > AVATAR_MAX_BYTES:
            raise HTTPException(status_code=400, detail="Imagem inválida ou grande demais.")
        try:
            rendered = preview_bytes(data, preset)
        except PixelArtError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=rendered,
            media_type="image/png",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
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
        search_query = normalize_search_query(q)
        results = []
        search_too_short = False
        search_failed = False
        if tab == "assistindo" and search_query:
            if search_ready(search_query):
                try:
                    results = annotate_search_results(
                        db, user.id, await search_catalog(search_query)
                    )
                except CatalogSearchError:
                    search_failed = True
            else:
                search_too_short = True
        watching = [link for link in club.shows if (link.watch_status or "watching") != "watched"]
        watched = [link for link in club.shows if link.watch_status == "watched"]
        upcoming_schedules = (
            list_upcoming_schedules(db, club.id) if tab in {"agendamentos", "assistindo"} else []
        )
        schedules = upcoming_schedules if tab == "agendamentos" else []
        planner_days = []
        week_label = ""
        week_iso = ""
        prev_week = ""
        next_week = ""
        now = utcnow()
        if tab == "agendamentos":
            today = local_today()
            week_start = monday_of(parse_iso_date(request.query_params.get("semana")) or today)
            week_items = list_member_week_schedules(db, user.id, week_start, club.id)
            planner_days = week_planner_days(week_start, week_items, today)
            week_label = format_week_span(week_start)
            week_iso = week_start.isoformat()
            prev_week = (week_start - timedelta(days=7)).isoformat()
            next_week = (week_start + timedelta(days=7)).isoformat()
        next_club_schedule = upcoming_schedules[0] if tab == "assistindo" and upcoming_schedules else None
        next_meeting_by_show = next_meetings_by_show(upcoming_schedules) if tab == "assistindo" else {}
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
        pinned_message = load_pinned_message(db, club) if tab == "chat" else None
        report_select_ids = []
        if tab == "chat":
            try:
                report_select_ids = parse_id_list(list(request.query_params.getlist("selecionar")))
            except HTTPException:
                report_select_ids = []
        stamp_users = [item.user for item in members] + [item.user for item in messages]
        if pinned_message and pinned_message.user:
            stamp_users.append(pinned_message.user)
        stamp_display_tags(db, stamp_users)
        online_count = sum(1 for item in members if presence_of(item.user) == "online")
        join_requests = list_join_requests(db, club.id) if caps["can_joins"] and club.is_closed else []
        program_catalog = (
            program_catalog_for_shows(db, [link.show_id for link in club.shows])
            if tab == "agendamentos" and caps["can_schedules"]
            else {}
        )
        return templates.TemplateResponse(
            request,
            "club.html",
            {
                "user": user,
                "club": club,
                "query": search_query,
                "results": results,
                "search_too_short": search_too_short,
                "search_failed": search_failed,
                "search_min_chars": SEARCH_MIN_CHARS,
                "is_member": True,
                "tab": tab,
                "watch_list": "finalizados" if lista == "finalizados" else "assistindo",
                "messages": messages,
                "report_select_ids": report_select_ids,
                "max_report_messages": MAX_REPORT_MESSAGES,
                "blocked_user_ids": ids_blocked_by(db, user.id) if tab == "chat" else set(),
                "pinned_message": pinned_message,
                "watching": watching,
                "watched": watched,
                "schedules": schedules,
                "planner_days": planner_days,
                "week_label": week_label,
                "week_iso": week_iso,
                "prev_week": prev_week,
                "next_week": next_week,
                "now": now,
                "next_club_schedule": next_club_schedule,
                "next_meeting_by_show": next_meeting_by_show,
                "progress_by_show": progress_by_show,
                "ratings": ratings,
                "favorite_ids": favorite_show_ids(db, user.id) if tab == "assistindo" else set(),
                "friend_ids": friend_id_set(db, user.id),
                "online_count": online_count,
                "join_requests": join_requests,
                "program_catalog": program_catalog,
                "members_by_user": {item.user_id: item for item in members},
                "member_groups": grouped_club_members(members),
                "user_clubs": _member_club_nav(db, user.id),
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
    cover_preset: str = Form(""),
    icon_preset: str = Form(""),
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
        enforce_text(db, user, name.strip(), surface=SURFACE_PUBLIC_NAME, origin="club")
        enforce_text(db, user, description.strip(), surface=SURFACE_PUBLIC_TEXT, origin="club")
        enforce_text(db, user, rules.strip(), surface=SURFACE_PUBLIC_TEXT, origin="club")
        image_name = await save_cover_image(cover_file)
        icon_name = await save_club_icon(icon_file)
        for stored_name, locator, origin in (
            (image_name, stored_cover_path, "club_cover"),
            (icon_name, stored_icon_path, "club_icon"),
        ):
            path = locator(stored_name) if stored_name else None
            if path:
                enforce_image(db, user, path.read_bytes(), mime="image/*", origin=origin)
        club.name = name.strip()
        club.is_closed = bool(is_closed)
        club.description = description.strip()
        club.rules = rules.strip()
        club.cover_color = valid_cover_color(cover_color)
        club.admin_name_color = admin_hex
        club.sub_name_color = sub_hex
        club.member_limit = limit_value
        if image_name:
            delete_cover_image(club.cover_image)
            delete_cover_image(club.cover_pixel)
            cover_pixel, cover_style = attach_preset(
                image_name, stored_cover_path, uploads_dir() / "clubs", cover_preset
            )
            club.cover_image = image_name
            club.cover_style = cover_style
            club.cover_pixel = cover_pixel
        elif clear_cover:
            delete_cover_image(club.cover_image)
            delete_cover_image(club.cover_pixel)
            club.cover_image = None
            club.cover_pixel = None
            club.cover_style = STYLE_ORIGINAL
        elif club.cover_image and cover_preset:
            delete_cover_image(club.cover_pixel)
            cover_pixel, cover_style = attach_preset(
                club.cover_image, stored_cover_path, uploads_dir() / "clubs", cover_preset
            )
            club.cover_style = cover_style
            club.cover_pixel = cover_pixel
        if icon_name:
            delete_club_icon(club.icon_image)
            delete_club_icon(club.icon_pixel)
            icon_pixel, icon_style = attach_preset(
                icon_name, stored_icon_path, uploads_dir() / "club-icons", icon_preset
            )
            club.icon_image = icon_name
            club.icon_style = icon_style
            club.icon_pixel = icon_pixel
        elif club.icon_image and icon_preset:
            delete_club_icon(club.icon_pixel)
            icon_pixel, icon_style = attach_preset(
                club.icon_image, stored_icon_path, uploads_dir() / "club-icons", icon_preset
            )
            club.icon_style = icon_style
            club.icon_pixel = icon_pixel
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
        old_pixel = club.icon_pixel
        club.icon_image = None
        club.icon_pixel = None
        club.icon_style = STYLE_ORIGINAL
        db.commit()
        delete_club_icon(old_name)
        delete_club_icon(old_pixel)
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


@app.post("/conta/conversas")
def update_chat_preference(request: Request, enter_sends: str = Form("")):
    ajax = request.headers.get("x-watchclub-pref") == "1"

    def fail(status: int, message: str, location: str = "/login"):
        if ajax:
            return JSONResponse({"ok": False, "error": message}, status_code=status)
        if status == 401:
            return RedirectResponse(location, status_code=303)
        return RedirectResponse(f"/conta?error={quote(message)}", status_code=303)

    db = db_session()
    try:
        user = login_required(request, db)
        if enter_sends not in {"", "0", "1"}:
            return fail(400, "Valor inválido")
        user.enter_sends = enter_sends == "1"
        db.commit()
        if ajax:
            return JSONResponse({"ok": True, "enter_sends": bool(user.enter_sends)})
        return RedirectResponse("/conta?ok=Preferência+de+conversas+atualizada", status_code=303)
    except HTTPException:
        return fail(401, "Faça login")
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


@app.post("/clubs/{club_id}/mensagens/{message_id}/apagar")
def remove_club_message(request: Request, club_id: int, message_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        delete_club_message(db, club_id, user.id, message_id)
        return RedirectResponse(f"/clubs/{club_id}?aba=chat", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}?aba=chat", status_code=303)
        if exc.status_code == 404:
            return RedirectResponse(
                f"/clubs/{club_id}?aba=chat&error={quote(str(exc.detail))}",
                status_code=303,
            )
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/mensagens/{message_id}/fixar")
def pin_existing_club_message(request: Request, club_id: int, message_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        pin_club_message(db, club_id, user.id, message_id)
        return RedirectResponse(f"/clubs/{club_id}?aba=chat", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}?aba=chat", status_code=303)
        if exc.status_code == 404:
            return RedirectResponse(
                f"/clubs/{club_id}?aba=chat&error={quote(str(exc.detail))}",
                status_code=303,
            )
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/mensagem-fixa/desafixar")
def unpin_existing_club_message(request: Request, club_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        unpin_club_message(db, club_id, user.id)
        return RedirectResponse(f"/clubs/{club_id}?aba=chat", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}?aba=chat", status_code=303)
        raise
    finally:
        db.close()


def _positive_id(raw: object) -> int | None:
    try:
        value = int(str(raw or "").strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


@app.post("/clubs/{club_id}/shows")
async def add_show(
    request: Request,
    club_id: int,
    provider: str = Form(""),
    external_id: str = Form(""),
    tvmaze_id: str = Form(""),
    kind: str = Form("serie"),
):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_perm(db, club_id, user.id, PERM_TITLES)
        source = (provider or "").strip().lower()
        chosen_id = _positive_id(external_id)
        if not source:
            source = "tvmaze"
            chosen_id = chosen_id or _positive_id(tvmaze_id)
        if source not in {"tvmaze", "tmdb"} or chosen_id is None:
            raise HTTPException(status_code=400, detail="Obra inválida")
        if source == "tmdb":
            await add_tmdb_movie_to_club(db, club, chosen_id, user.id)
        else:
            await add_show_to_club(db, club, chosen_id, user.id, valid_kind(kind))
        return RedirectResponse(f"/clubs/{club_id}?aba=assistindo", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(
                f"/clubs/{club_id}?aba=assistindo&error={quote(str(exc.detail))}",
                status_code=303,
            )
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/indicar")
async def indicate_show(
    request: Request,
    club_id: int,
    provider: str = Form(""),
    external_id: str = Form(""),
    tvmaze_id: str = Form(""),
    kind: str = Form("serie"),
    next: str = Form(""),
):
    db = db_session()
    dest = _safe_next(next, f"/clubs/{club_id}?aba=chat")
    try:
        user = login_required(request, db)
        require_club_member(db, club_id, user.id)
        source = (provider or "").strip().lower()
        chosen_id = _positive_id(external_id)
        if not source:
            source = "tvmaze"
            chosen_id = chosen_id or _positive_id(tvmaze_id)
        if source not in {"tvmaze", "tmdb"} or chosen_id is None:
            raise HTTPException(status_code=400, detail="Obra inválida")
        show = await ensure_catalog_show(db, source, chosen_id, valid_kind(kind))
        suggest_show_to_club(db, club_id, user, show)
        return RedirectResponse(dest, status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        if exc.status_code == 400:
            sep = "&" if "?" in dest else "?"
            return RedirectResponse(f"{dest}{sep}error={quote(str(exc.detail))}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/agendamentos")
def add_club_schedule(
    request: Request,
    club_id: int,
    date: str = Form(...),
    time: str = Form(...),
    show_id: str = Form(""),
    season_number: str = Form(""),
    episode_number: str = Form(""),
    notes: str = Form(""),
    repeat: str = Form("none"),
    until: str = Form(""),
    title: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_perm(db, club_id, user.id, PERM_SCHEDULES)
        create_schedule(
            db,
            club_id,
            user.id,
            parse_optional_show_id(show_id),
            date,
            time,
            season_number,
            episode_number,
            notes,
            repeat,
            until,
            parse_meeting_title(title),
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


def _schedule_write_redirect(request: Request, club_id: int, action) -> RedirectResponse:
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_perm(db, club_id, user.id, PERM_SCHEDULES)
        action(db, user)
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


@app.post("/clubs/{club_id}/agendamentos/{schedule_id}/cancelar")
def cancel_club_schedule(request: Request, club_id: int, schedule_id: int):
    return _schedule_write_redirect(
        request, club_id, lambda db, _user: cancel_schedule(db, club_id, schedule_id)
    )


@app.post("/clubs/{club_id}/agendamentos/{schedule_id}/programa")
def set_club_schedule_program(
    request: Request,
    club_id: int,
    schedule_id: int,
    show_id: str = Form(""),
    season_number: str = Form(""),
    episode_number: str = Form(""),
    scope: str = Form("this"),
):
    return _schedule_write_redirect(
        request,
        club_id,
        lambda db, _user: set_schedule_program(
            db,
            club_id,
            schedule_id,
            parse_optional_show_id(show_id),
            season_number,
            episode_number,
            scope,
        ),
    )


@app.post("/clubs/{club_id}/agendamentos/series/{series_id}/encerrar")
def end_club_schedule_series(request: Request, club_id: int, series_id: int):
    return _schedule_write_redirect(
        request, club_id, lambda db, _user: end_schedule_series(db, club_id, series_id)
    )


@app.post("/clubs/{club_id}/agendamentos/{schedule_id}")
def edit_club_schedule(
    request: Request,
    club_id: int,
    schedule_id: int,
    date: str = Form(...),
    time: str = Form(...),
    notes: str = Form(""),
):
    return _schedule_write_redirect(
        request,
        club_id,
        lambda db, _user: update_schedule_when(db, club_id, schedule_id, date, time, notes),
    )


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


def _rating_redirect(club_id: int, show_id: int, voltar: str, lista: str, temporada: str) -> RedirectResponse:
    if voltar == "obra":
        text = (temporada or "").strip()
        if text.isdigit():
            return RedirectResponse(
                f"/clubs/{club_id}/shows/{show_id}?t={text}#episodios",
                status_code=303,
            )
        return RedirectResponse(f"/clubs/{club_id}/shows/{show_id}", status_code=303)
    watch_list = "finalizados" if lista == "finalizados" else "assistindo"
    return RedirectResponse(
        f"/clubs/{club_id}?aba=assistindo&lista={watch_list}",
        status_code=303,
    )


@app.post("/clubs/{club_id}/shows/{show_id}/avaliar")
def rate_club_show(
    request: Request,
    club_id: int,
    show_id: int,
    stars: str = Form(...),
    lista: str = Form(""),
    voltar: str = Form(""),
    t: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_member(db, club_id, user.id)
        set_club_show_rating(db, club_id, show_id, user.id, valid_stars(stars))
        return _rating_redirect(club_id, show_id, voltar, lista, t)
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


@app.get("/shows/{show_id}", response_class=HTMLResponse)
def catalog_show(request: Request, show_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        show = load_show(db, show_id)
        return templates.TemplateResponse(
            request,
            "catalog_show.html",
            {
                "user": user,
                "show": show,
                "is_favorite": is_show_favorite(db, user.id, show.id),
                "error": request.query_params.get("error"),
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/shows/{show_id}/favorito")
def toggle_favorite(request: Request, show_id: int, next: str = Form("")):
    db = db_session()
    dest = _safe_next(next, f"/shows/{show_id}")
    try:
        user = login_required(request, db)
        toggle_show_favorite(db, user.id, show_id)
        return RedirectResponse(dest, status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 404:
            return RedirectResponse(f"{dest}?error={quote(str(exc.detail))}" if "?" not in dest else dest, status_code=303)
        raise
    finally:
        db.close()


@app.post("/favoritos")
async def add_favorite(
    request: Request,
    provider: str = Form(""),
    external_id: str = Form(""),
    tvmaze_id: str = Form(""),
    kind: str = Form("serie"),
    next: str = Form(""),
):
    db = db_session()
    dest = _safe_next(next, "/")
    try:
        user = login_required(request, db)
        source = (provider or "").strip().lower()
        chosen_id = _positive_id(external_id)
        if not source:
            source = "tvmaze"
            chosen_id = chosen_id or _positive_id(tvmaze_id)
        if source not in {"tvmaze", "tmdb"} or chosen_id is None:
            raise HTTPException(status_code=400, detail="Obra inválida")
        show = await favorite_catalog_result(db, user.id, source, chosen_id, valid_kind(kind))
        return RedirectResponse(_safe_next(next, f"/shows/{show.id}"), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 400:
            sep = "&" if "?" in dest else "?"
            return RedirectResponse(f"{dest}{sep}error={quote(str(exc.detail))}", status_code=303)
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
                "is_favorite": is_show_favorite(db, user.id, show.id),
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
        source = show_source(show)
        if source == "tvmaze":
            await upsert_show_from_tvmaze(db, show.tvmaze_id)
            refresh_news(db, show, force=True)
            db.commit()
        elif source == "tmdb":
            await upsert_show_from_tmdb(db, show.tmdb_id)
            refresh_news(db, show, force=True)
            db.commit()
        return RedirectResponse(f"/clubs/{club_id}/shows/{show_id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 400:
            return RedirectResponse(
                f"/clubs/{club_id}/shows/{show_id}?error={quote(str(exc.detail))}",
                status_code=303,
            )
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
                            {"label": "Entrar", "href": "/auth/login"},
                            {"label": "Criar conta", "href": "/auth/signup"},
                        ],
                    }
                ]
            }
        groups = [
            {
                "heading": "Navegação",
                "items": [
                    {"label": "Início", "href": "/"},
                    {"label": "Agenda", "href": "/agenda"},
                    {"label": "Meus Clubes", "href": "/clubes"},
                    {"label": "Configurações", "href": "/conta"},
                    {"label": "Caixinha de sugestão", "href": "/sugestoes"},
                    {"label": "Segurança e denúncias", "href": "/seguranca"},
                    {"label": "Regras da comunidade", "href": "/regras"},
                    {"label": "Criar um clube", "href": "/clubs/novo"},
                    {"label": "Meu perfil", "href": f"/u/{user.username}"},
                    {"label": "Amigos", "href": "/amigos"},
                    {"label": "Conversas", "href": "/mensagens"},
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
async def api_search(request: Request, q: str = Query("")):
    db = db_session()
    try:
        user = login_required(request, db)
        query = normalize_search_query(q)
        if not search_ready(query):
            return []
        try:
            return annotate_search_results(db, user.id, await search_catalog(query))
        except CatalogSearchError:
            raise HTTPException(status_code=503, detail="Não foi possível pesquisar agora.")
    except HTTPException as exc:
        if exc.status_code == 401:
            raise
        raise
    finally:
        db.close()


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


def _dm_peer_context(db, user, person):
    if person is None:
        return [], []
    mine = select(ClubMember.club_id).where(ClubMember.user_id == user.id)
    shared_clubs = list(
        db.scalars(
            select(Club)
            .join(ClubMember, ClubMember.club_id == Club.id)
            .where(ClubMember.user_id == person.id, ClubMember.club_id.in_(mine))
            .order_by(Club.name)
            .limit(6)
        ).unique()
    )
    favorites = list_user_favorites(db, person.id)[:4]
    return shared_clubs, favorites


def _conversations_response(request: Request, db, user, person=None):
    conversations = list_dm_conversations(db, user.id)
    people = [row.person for row in conversations]
    messages = []
    are_friends = False
    blocked_peer = False
    shared_clubs = []
    peer_favorites = []
    if person is not None:
        mark_dm_read(db, user.id, person.id)
        are_friends = relation_status(db, user.id, person.id) == "friends"
        blocked_peer = are_blocked(db, user.id, person.id)
        messages = dm_thread(db, user.id, person.id)
        people = people + [person] + [item.sender for item in messages]
        shared_clubs, peer_favorites = _dm_peer_context(db, user, person)
    stamp_display_tags(db, people)
    report_select_ids = []
    if person is not None:
        try:
            report_select_ids = parse_id_list(list(request.query_params.getlist("selecionar")))
        except HTTPException:
            report_select_ids = []
    return templates.TemplateResponse(
        request,
        "direct_chat.html",
        {
            "user": user,
            "person": person,
            "messages": messages,
            "are_friends": are_friends,
            "blocked_peer": blocked_peer,
            "conversations": conversations,
            "shared_clubs": shared_clubs,
            "peer_favorites": peer_favorites,
            "report_select_ids": report_select_ids,
            "max_report_messages": MAX_REPORT_MESSAGES,
            "error": request.query_params.get("error"),
        },
    )


@app.get("/mensagens", response_class=HTMLResponse)
def conversations_home(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        return _conversations_response(request, db, user)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
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
        return _conversations_response(request, db, user, person)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/mensagens/{username}/{message_id}/apagar")
def remove_direct_message(request: Request, username: str, message_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if not person:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        if person.id == user.id:
            return RedirectResponse(f"/u/{user.username}", status_code=303)
        delete_dm(db, user.id, person.id, message_id)
        return RedirectResponse(f"/mensagens/{person.username}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        person = find_active_user(db, username)
        nick = person.username if person else username
        if exc.status_code == 403:
            if person and can_view_thread(db, user.id, person.id):
                return RedirectResponse(f"/mensagens/{nick}", status_code=303)
            return RedirectResponse(f"/u/{nick}", status_code=303)
        if exc.status_code == 404:
            if person and can_view_thread(db, user.id, person.id):
                return RedirectResponse(f"/mensagens/{nick}", status_code=303)
            return RedirectResponse(f"/u/{nick}" if person else "/mensagens", status_code=303)
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


@app.post("/u/{username}/status")
def update_profile_status(request: Request, username: str, status: str = Form(""), next: str = Form("")):
    db = db_session()
    dest = _safe_next(next, f"/u/{username}")
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if person is None:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        if person.id != user.id:
            raise HTTPException(status_code=403, detail="Você só pode editar o próprio status")
        text = clean_profile_status(status)
        if text:
            enforce_text(db, user, text, surface=SURFACE_PUBLIC_TEXT, origin="profile")
        user.profile_status = text
        db.commit()
        return RedirectResponse(dest.split("?")[0] + "?aba=perfil&ok=" + quote("Status atualizado"), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/u/{username}?error={quote(str(exc.detail))}", status_code=303)
        return RedirectResponse(f"/u/{username}?aba=perfil&error={quote(str(exc.detail))}", status_code=303)
    finally:
        db.close()


@app.post("/u/{username}/tema")
def update_profile_theme(request: Request, username: str, theme: str = Form(""), next: str = Form("")):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if person is None:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        if person.id != user.id:
            raise HTTPException(status_code=403, detail="Você só pode alterar o próprio tema")
        user.theme_key = require_theme(theme)
        db.commit()
        return RedirectResponse(f"/u/{user.username}?aba=aparencia&ok=" + quote("Tema salvo"), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(f"/u/{username}?aba=aparencia&error={quote(str(exc.detail))}", status_code=303)
    finally:
        db.close()


@app.post("/u/{username}/aparencia")
def update_profile_look(
    request: Request,
    username: str,
    theme: str = Form(""),
    wallpaper: str = Form(""),
):
    db = db_session()
    try:
        user = login_required(request, db)
        person = find_active_user(db, username)
        if person is None:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        if person.id != user.id:
            raise HTTPException(status_code=403, detail="Você só pode alterar a própria aparência")
        user.theme_key = require_theme(theme)
        user.wallpaper_key = require_wallpaper(wallpaper)
        db.commit()
        return RedirectResponse(f"/u/{user.username}?aba=aparencia&ok=" + quote("Aparência salva"), status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(f"/u/{username}?aba=aparencia&error={quote(str(exc.detail))}", status_code=303)
    finally:
        db.close()


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
        club_preview, club_more = profile_club_preview(clubs)
        mine = {club.id for club in _user_clubs(db, viewer.id)}
        favorites = list_user_favorites(db, person.id)
        favorite_preview, favorite_more = profile_favorite_preview(favorites)
        relation = relation_status(db, viewer.id, person.id)
        viewer_blocks = ids_blocked_by(db, viewer.id)
        stamp_display_tags(db, [person])
        context_club, context_role, context_role_label = _club_profile_context(
            db, viewer, person, request.query_params.get("clube")
        )
        own = viewer.id == person.id
        tab = profile_tab(request.query_params.get("aba"), own=own)
        progress = player_progress(person.created_at)
        return templates.TemplateResponse(
            request,
            "profile.html",
            {
                "user": viewer,
                "person": person,
                "clubs": clubs,
                "club_preview": club_preview,
                "club_more": club_more,
                "favorites": favorites,
                "favorite_preview": favorite_preview,
                "favorite_more": favorite_more,
                "is_own_profile": own,
                "search_min_chars": SEARCH_MIN_CHARS,
                "mine": mine,
                "requested_ids": requested_club_ids(db, viewer.id),
                "status": presence_of(person),
                "status_label": PRESENCE_LABELS[presence_of(person)],
                "relation": relation,
                "blocked_by_me": person.id in viewer_blocks,
                "has_history": has_dm_history(db, viewer.id, person.id),
                "context_club": context_club,
                "context_club_tag": tag_payload(context_club) if context_club else None,
                "context_role": context_role,
                "context_role_label": context_role_label,
                "tab": tab,
                "player": progress,
                "energy": energy_hearts(person.last_seen),
                "energy_max": 5,
                "stats": player_stats(
                    db, person, club_count=len(clubs), favorite_count=len(favorites)
                ),
                "visitor_theme": theme_of(viewer),
                "visitor_wallpaper": wallpaper_of(viewer),
                "profile_theme": theme_of(person),
                "profile_wallpaper": wallpaper_of(person),
                "themes": THEMES,
                "wallpapers": wallpaper_catalog(),
                "default_theme": DEFAULT_THEME,
                "default_wallpaper": DEFAULT_WALLPAPER,
                "status_max": PROFILE_STATUS_MAX,
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


def _join_action_error(request: Request, db: Session, user, dest: str, exc: HTTPException):
    fetch = _notice_fetch(request)
    if exc.status_code == 401:
        if fetch:
            return JSONResponse({"ok": False, "error": "Faça login"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    if fetch:
        payload = {"ok": False, "error": str(exc.detail)}
        if user:
            payload.update(
                _notice_payload(
                    request, db, user.id, extra={"ok": False, "error": str(exc.detail)}, full=True
                )
            )
            payload["ok"] = False
        status = 200 if exc.status_code == 404 and exc.detail == JOIN_MISSING_DETAIL else exc.status_code
        if exc.status_code == 404 and exc.detail == JOIN_MISSING_DETAIL:
            payload["error"] = JOIN_ALREADY_RESOLVED
            payload["ok"] = True
            payload["resolved"] = True
            status = 200
        return JSONResponse(payload, status_code=status)
    if exc.status_code == 400:
        return _redirect_with_query(dest, "error", str(exc.detail))
    if exc.status_code == 404 and exc.detail == JOIN_MISSING_DETAIL:
        return _redirect_with_query(dest, "error", JOIN_ALREADY_RESOLVED)
    raise exc


@app.post("/clubs/{club_id}/solicitacoes/{user_id}/aceitar")
def accept_club_join(request: Request, club_id: int, user_id: int, next: str = Form("")):
    db = db_session()
    dest = _join_return_path(next, club_id)
    user = None
    try:
        user = login_required(request, db)
        related_id = accept_join_request(db, club_id, user_id, user.id)
        mark_own_join_notifications_read(db, user.id, club_id, user_id, related_id)
        db.commit()
        if _notice_fetch(request):
            return JSONResponse(_notice_payload(request, db, user.id, full=True))
        return RedirectResponse(dest, status_code=303)
    except HTTPException as exc:
        return _join_action_error(request, db, user, dest, exc)
    finally:
        db.close()


@app.post("/clubs/{club_id}/solicitacoes/{user_id}/recusar")
def reject_club_join(request: Request, club_id: int, user_id: int, next: str = Form("")):
    db = db_session()
    dest = _join_return_path(next, club_id)
    user = None
    try:
        user = login_required(request, db)
        related_id = reject_join_request(db, club_id, user_id, user.id)
        mark_own_join_notifications_read(db, user.id, club_id, user_id, related_id)
        db.commit()
        if _notice_fetch(request):
            return JSONResponse(_notice_payload(request, db, user.id, full=True))
        return RedirectResponse(dest, status_code=303)
    except HTTPException as exc:
        return _join_action_error(request, db, user, dest, exc)
    finally:
        db.close()


@app.get("/notificacoes", response_class=HTMLResponse)
def notifications_page(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        return templates.TemplateResponse(
            request,
            "notifications.html",
            {
                "user": user,
                "notifications": notification_cards(db, user.id),
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


@app.get("/notificacoes/sininho")
def notifications_bell(request: Request):
    db = db_session()
    try:
        user = login_required(request, db)
        return JSONResponse(_notice_payload(request, db, user.id))
    except HTTPException as exc:
        if exc.status_code == 401:
            return JSONResponse({"ok": False, "error": "Faça login"}, status_code=401)
        raise
    finally:
        db.close()


@app.post("/notificacoes/limpar")
def clear_user_notifications(request: Request, next: str = Form("/notificacoes")):
    db = db_session()
    dest = _safe_next(next, "/notificacoes")
    try:
        user = login_required(request, db)
        clear_notifications(db, user.id)
        db.commit()
        if _notice_fetch(request):
            return JSONResponse(_notice_payload(request, db, user.id, full=True))
        return RedirectResponse(dest, status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            if _notice_fetch(request):
                return JSONResponse({"ok": False, "error": "Faça login"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/notificacoes/lidas")
def mark_notifications_read(request: Request, next: str = Form("/notificacoes")):
    db = db_session()
    dest = _safe_next(next, "/notificacoes")
    try:
        user = login_required(request, db)
        mark_all_read(db, user.id)
        db.commit()
        if _notice_fetch(request):
            return JSONResponse(_notice_payload(request, db, user.id, full=True))
        return RedirectResponse(dest, status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            if _notice_fetch(request):
                return JSONResponse({"ok": False, "error": "Faça login"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.get("/notificacoes/{notification_id}")
def open_notification(request: Request, notification_id: int):
    db = db_session()
    try:
        user = login_required(request, db)
        item = mark_read(db, user.id, notification_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Notificação não encontrada")
        db.commit()
        dest = notification_destination(item)
        if item.club_id:
            club = db.get(Club, item.club_id)
            dest = f"/clubs/{item.club_id}" if club else "/notificacoes"
        return RedirectResponse(dest, status_code=303)
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


register_ui_preview_routes(app, templates)
