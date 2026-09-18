from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.accounts import create_user, login_or_create_oauth, send_activation, utcnow
from app.avatars import AVATARS, avatars_by_category, valid_avatar
from app.catalog import (
    CONTENT_KINDS,
    add_manual_title,
    add_show_to_club,
    admin_count,
    club_membership,
    club_messages,
    club_rating_stats,
    fill_missing_genres,
    is_club_admin,
    leave_club as remove_club_membership,
    load_show,
    parse_genres,
    post_club_message,
    refresh_news,
    remove_show_from_club,
    require_club_admin,
    require_club_member,
    set_club_show_rating,
    set_watch_status,
    upsert_show_from_tvmaze,
    valid_kind,
    valid_stars,
)
from app.covers import COVER_COLORS, cover_image_url, save_cover_image, valid_cover_color
from app.config import BASE_DIR, BIO_MAX, EMAIL_DEV_SHOW_LINK, SECRET_KEY
from app.db import Base, engine, get_db
from app.models import Club, ClubMember, ClubShow, EmailToken, User
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
from app.presence import presence_of, touch_presence
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
templates.env.globals["google_enabled"] = google_enabled
templates.env.globals["facebook_enabled"] = facebook_enabled
templates.env.globals["BIO_MAX"] = BIO_MAX
templates.env.globals["COVER_COLORS"] = COVER_COLORS
templates.env.globals["cover_image_url"] = cover_image_url
templates.env.globals["CONTENT_KINDS"] = CONTENT_KINDS
templates.env.filters["when"] = lambda value: value.strftime("%d/%m/%Y %H:%M") if value else ""
templates.env.filters["genres"] = parse_genres
templates.env.filters["avg_pt"] = lambda value: f"{value:.1f}".replace(".", ",") if value is not None else ""


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user and not user.is_active:
        request.session.clear()
        return None
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


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse(
        request,
        "auth.html",
        {"mode": "register", "error": None, "suggestions": [], "form": {}},
    )


def _auth_page(request: Request, mode: str, error: str, status_code: int = 400, suggestions=None, form=None):
    return templates.TemplateResponse(
        request,
        "auth.html",
        {"mode": mode, "error": error, "suggestions": suggestions or [], "form": form or {}},
        status_code=status_code,
    )


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
):
    db = db_session()
    try:
        email = email.strip().lower()
        display = name.strip()[:80]
        form = {"name": display, "username": username, "email": email}
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
        if db.scalar(select(User).where(User.email == email)):
            return _auth_page(request, "register", "Este e-mail já está cadastrado", form=form)
        user = create_user(db, username, email, password, name=display)
        verify_url = send_activation(db, user)
        db.commit()
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
            if not record or record.expires_at < utcnow():
                return templates.TemplateResponse(
                    request,
                    "verify.html",
                    {"user": None, "error": "Link inválido ou expirado. Peça um novo e-mail.", "ok": None, "verify_link": None},
                    status_code=400,
                )
            user = db.get(User, record.user_id)
            if record.purpose == "email_change" and record.new_email:
                taken = db.scalar(select(User).where(User.email == record.new_email, User.id != user.id))
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
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user and not user.is_active:
            verify_url = send_activation(db, user)
            db.commit()
            if EMAIL_DEV_SHOW_LINK:
                request.session["verify_link"] = verify_url
        return RedirectResponse("/verificar-email?ok=Se+o+e-mail+existir,+enviamos+um+novo+link", status_code=303)
    finally:
        db.close()


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return _auth_page(request, "login", request.query_params.get("error") or "", status_code=200)


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    db = db_session()
    try:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user or not user.password_hash or not verify_password(password, user.password_hash):
            return _auth_page(request, "login", "E-mail ou senha inválidos", form={"email": email})
        if not user.is_active:
            verify_url = send_activation(db, user)
            db.commit()
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
            touch_presence(user, "offline")
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
):
    db = db_session()
    try:
        user = login_required(request, db)
        image_name = await save_cover_image(cover_file)
        club = Club(
            name=name.strip(),
            join_code=make_join_code(),
            owner_id=user.id,
            is_closed=bool(is_closed),
            description=description.strip(),
            rules=rules.strip(),
            cover_color=valid_cover_color(cover_color),
            cover_image=image_name,
        )
        db.add(club)
        db.flush()
        db.add(ClubMember(club_id=club.id, user_id=user.id, is_admin=True))
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
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
                "suggestions": [],
                "avatar_groups": avatars_by_category(),
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
        email = email.strip().lower()
        clubs = _user_clubs(db, user.id)
        groups = avatars_by_category()

        def account_error(message: str, suggestions=None):
            return templates.TemplateResponse(
                request,
                "account.html",
                {
                    "user": user,
                    "clubs": clubs,
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
        taken = db.scalar(select(User).where(User.email == email, User.id != user.id))
        if taken:
            return account_error("Este e-mail já está em uso")
        user.name = display
        if nick_changed:
            user.username = key
            user.username_key = key
            user.username_changed_at = utcnow()
        user.bio = (bio or "")[:BIO_MAX]
        if email != user.email:
            user.pending_email = email
            verify_url = send_activation(db, user, new_email=email)
            db.commit()
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
def update_avatar(request: Request, avatar: str = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        user.avatar = valid_avatar(avatar)
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
        existing = db.scalar(
            select(ClubMember).where(ClubMember.club_id == club.id, ClubMember.user_id == user.id)
        )
        if not existing:
            db.add(ClubMember(club_id=club.id, user_id=user.id, is_admin=False))
            db.commit()
        if next_url.startswith("/conta"):
            return RedirectResponse(
                f"/conta?ok={quote('Você entrou no clube ' + club.name)}",
                status_code=303,
            )
        return RedirectResponse(f"/clubs/{club.id}", status_code=303)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
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
            db.add(ClubMember(club_id=club.id, user_id=user.id, is_admin=False))
            db.commit()
        return RedirectResponse(f"/clubs/{club.id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.get("/clubs/{club_id}", response_class=HTMLResponse)
async def club_detail(request: Request, club_id: int, q: str | None = Query(None), aba: str | None = Query(None)):
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
                {"user": user, "club": club},
                status_code=403,
            )
        if not member:
            return templates.TemplateResponse(
                request,
                "club_preview.html",
                {"user": user, "club": club},
            )
        results = await tvmaze.search_shows(q) if q else []
        tab = "chat" if aba == "chat" else "assistindo"
        watching = [link for link in club.shows if (link.watch_status or "watching") != "watched"]
        watched = [link for link in club.shows if link.watch_status == "watched"]
        if tab == "assistindo":
            await fill_missing_genres(db, [link.show for link in club.shows])
            db.commit()
        ratings = club_rating_stats(db, club.id, user.id)
        return templates.TemplateResponse(
            request,
            "club.html",
            {
                "user": user,
                "club": club,
                "query": q or "",
                "results": results,
                "is_member": True,
                "is_admin": is_club_admin(db, club.id, user.id),
                "tab": tab,
                "messages": club_messages(db, club.id) if tab == "chat" else [],
                "watching": watching,
                "watched": watched,
                "ratings": ratings,
                "error": request.query_params.get("error"),
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
        return templates.TemplateResponse(
            request,
            "members.html",
            {
                "user": user,
                "club": club,
                "members": members,
                "is_admin": is_club_admin(db, club.id, user.id),
                "admin_total": admin_count(db, club.id),
                "error": request.query_params.get("error"),
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
            {"user": user, "club": club, "error": None, "mode": "edit"},
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
):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_admin(db, club_id, user.id)
        image_name = await save_cover_image(cover_file)
        club.name = name.strip()
        club.is_closed = bool(is_closed)
        club.description = description.strip()
        club.rules = rules.strip()
        club.cover_color = valid_cover_color(cover_color)
        if image_name:
            club.cover_image = image_name
        elif clear_cover:
            club.cover_image = None
        db.commit()
        return RedirectResponse(f"/clubs/{club_id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/membros/{member_user_id}/admin")
def set_club_admin(request: Request, club_id: int, member_user_id: int, action: str = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_admin(db, club_id, user.id)
        target = club_membership(db, club_id, member_user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Membro não encontrado")
        if action == "grant":
            target.is_admin = True
        elif action == "revoke":
            if target.is_admin and admin_count(db, club_id) <= 1:
                return RedirectResponse(
                    f"/clubs/{club_id}/membros?error=O+clube+precisa+de+pelo+menos+um+administrador",
                    status_code=303,
                )
            target.is_admin = False
        db.commit()
        return RedirectResponse(f"/clubs/{club_id}/membros", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            return RedirectResponse(f"/clubs/{club_id}", status_code=303)
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


@app.post("/clubs/{club_id}/shows/{show_id}/status")
def update_watch_status(request: Request, club_id: int, show_id: int, watch_status: str = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        require_club_member(db, club_id, user.id)
        set_watch_status(db, club_id, show_id, watch_status)
        return RedirectResponse(f"/clubs/{club_id}?aba=assistindo", status_code=303)
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
        require_club_admin(db, club_id, user.id)
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
        return templates.TemplateResponse(
            request,
            "show.html",
            {"user": user, "club_id": club_id, "show": show, "seasons": seasons},
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
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
        return templates.TemplateResponse(
            request,
            "profile.html",
            {
                "user": viewer,
                "person": person,
                "clubs": clubs,
                "mine": mine,
                "status": presence_of(person),
                "status_label": PRESENCE_LABELS[presence_of(person)],
            },
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/presenca")
def ping_presence(request: Request, status: str = Form("online")):
    db = db_session()
    try:
        user = current_user(request, db)
        if not user:
            return {"ok": False}
        touch_presence(user, status if status in {"online", "away", "offline"} else "online")
        db.commit()
        return {"ok": True, "status": presence_of(user)}
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}
