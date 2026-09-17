from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.accounts import create_user, send_activation, utcnow
from app.avatars import AVATARS, avatars_by_category, valid_avatar
from app.catalog import (
    add_show_to_club,
    leave_club as remove_club_membership,
    load_show,
    refresh_news,
    require_club_member,
    upsert_show_from_tvmaze,
)
from app.config import BASE_DIR, EMAIL_DEV_SHOW_LINK, SECRET_KEY
from app.db import Base, engine, get_db
from app.models import Club, ClubMember, ClubShow, EmailToken, User
from app.schema import migrate_schema
from app.security import hash_password, make_join_code, verify_password
from app.services import tvmaze
from app.usernames import USERNAME_RE, normalize_username, suggest_usernames, taken_keys, username_taken

Base.metadata.create_all(bind=engine)
migrate_schema()
(BASE_DIR / "app" / "static" / "avatars").mkdir(parents=True, exist_ok=True)
for _avatar in AVATARS:
    (BASE_DIR / "app" / "static" / "avatars" / f"{_avatar['id']}.svg").write_text(_avatar["svg"], encoding="utf-8")


app = FastAPI(title="Watch Club", description="Séries assistidas com amigos")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


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
):
    db = db_session()
    try:
        email = email.strip().lower()
        form = {"username": username, "email": email}
        key = normalize_username(username)
        if not USERNAME_RE.match(key):
            return _auth_page(
                request,
                "register",
                "O nome de usuário precisa ter 3 a 30 caracteres (letras, números ou _).",
                form=form,
            )
        if username_taken(db, key):
            return _auth_page(
                request,
                "register",
                "Esse nome de usuário já está em uso. Que tal um destes?",
                suggestions=suggest_usernames(key, taken_keys(db)),
                form=form,
            )
        if db.scalar(select(User).where(User.email == email)):
            return _auth_page(request, "register", "Este e-mail já está cadastrado", form=form)
        user = create_user(db, username, email, password)
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
    return _auth_page(request, "login", "", status_code=200)


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    db = db_session()
    try:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user or not verify_password(password, user.password_hash):
            return _auth_page(request, "login", "E-mail ou senha inválidos", form={"email": email})
        if not user.is_active:
            verify_url = send_activation(db, user)
            db.commit()
            if EMAIL_DEV_SHOW_LINK:
                request.session["verify_link"] = verify_url
            return RedirectResponse("/verificar-email?error=Ative+sua+conta+pelo+e-mail", status_code=303)
        request.session["user_id"] = user.id
        return RedirectResponse("/", status_code=303)
    finally:
        db.close()


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.post("/clubs")
def create_club(request: Request, name: str = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        club = Club(name=name.strip(), join_code=make_join_code(), owner_id=user.id)
        db.add(club)
        db.flush()
        db.add(ClubMember(club_id=club.id, user_id=user.id))
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
            },
        )
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/conta/perfil")
def update_profile(request: Request, username: str = Form(...), email: str = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        key = normalize_username(username)
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
                },
                status_code=400,
            )

        if not USERNAME_RE.match(key):
            return account_error("O nome de usuário precisa ter 3 a 30 caracteres (letras, números ou _).")
        if username_taken(db, key, exclude_user_id=user.id):
            return account_error(
                "Esse nome de usuário já está em uso. Sugestões:",
                suggest_usernames(key, taken_keys(db) - {user.username_key}),
            )
        taken = db.scalar(select(User).where(User.email == email, User.id != user.id))
        if taken:
            return account_error("Este e-mail já está em uso")
        user.username = key
        user.username_key = key
        user.name = username.strip()
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
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    db = db_session()
    try:
        user = login_required(request, db)
        if not verify_password(current_password, user.password_hash):
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
            db.add(ClubMember(club_id=club.id, user_id=user.id))
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


@app.get("/clubs/{club_id}", response_class=HTMLResponse)
async def club_detail(request: Request, club_id: int, q: str | None = Query(None)):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_member(db, club_id, user.id)
        club = db.scalar(
            select(Club)
            .options(
                selectinload(Club.members).selectinload(ClubMember.user),
                selectinload(Club.shows).selectinload(ClubShow.show),
            )
            .where(Club.id == club_id)
        )
        results = await tvmaze.search_shows(q) if q else []
        return templates.TemplateResponse(
            request,
            "club.html",
            {"user": user, "club": club, "query": q or "", "results": results},
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    finally:
        db.close()


@app.post("/clubs/{club_id}/shows")
async def add_show(request: Request, club_id: int, tvmaze_id: int = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        club = require_club_member(db, club_id, user.id)
        show = await add_show_to_club(db, club, tvmaze_id, user.id)
        return RedirectResponse(f"/clubs/{club_id}/shows/{show.id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
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


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}
