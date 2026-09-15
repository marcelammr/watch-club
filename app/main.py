from datetime import datetime, timezone

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.catalog import (
    add_show_to_club,
    leave_club as remove_club_membership,
    load_show,
    refresh_news,
    require_club_member,
    upsert_show_from_tvmaze,
)
from app.config import BASE_DIR, SECRET_KEY
from app.db import Base, SessionLocal, engine, get_db
from app.models import Club, ClubMember, ClubShow, User
from app.security import hash_password, make_join_code, verify_password
from app.services import tvmaze

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Watch Club", description="Séries assistidas com amigos")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)


def login_required(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Faça login")
    return user


def db_session() -> Session:
    return next(get_db())


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    db = db_session()
    try:
        user = current_user(request, db)
        clubs = _user_clubs(db, user.id) if user else []
        return templates.TemplateResponse(
            request,
            "home.html",
            {"user": user, "clubs": clubs, "error": request.query_params.get("error")},
        )
    finally:
        db.close()


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse(request, "auth.html", {"mode": "register", "error": None})


@app.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    db = db_session()
    try:
        email = email.strip().lower()
        if db.scalar(select(User).where(User.email == email)):
            return templates.TemplateResponse(
                request,
                "auth.html",
                {"mode": "register", "error": "Este e-mail já está cadastrado"},
                status_code=400,
            )
        user = User(name=name.strip(), email=email, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        request.session["user_id"] = user.id
        return RedirectResponse("/", status_code=303)
    finally:
        db.close()


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "auth.html", {"mode": "login", "error": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    db = db_session()
    try:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user or not verify_password(password, user.password_hash):
            return templates.TemplateResponse(
                request,
                "auth.html",
                {"mode": "login", "error": "E-mail ou senha inválidos"},
                status_code=400,
            )
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
            },
        )
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()


@app.post("/conta/perfil")
def update_profile(request: Request, name: str = Form(...), email: str = Form(...)):
    db = db_session()
    try:
        user = login_required(request, db)
        name = name.strip()
        email = email.strip().lower()
        if not name:
            return RedirectResponse("/conta?error=Informe+um+nome+de+usuário", status_code=303)
        taken = db.scalar(select(User).where(User.email == email, User.id != user.id))
        if taken:
            return RedirectResponse("/conta?error=Este+e-mail+já+está+em+uso", status_code=303)
        user.name = name
        user.email = email
        db.commit()
        return RedirectResponse("/conta?ok=Perfil+atualizado", status_code=303)
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
            from urllib.parse import quote

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
        from urllib.parse import quote

        message = remove_club_membership(db, club_id, user.id)
        return RedirectResponse(f"{_safe_next(next, '/conta')}?ok={quote(message)}", status_code=303)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(f"/conta?error={exc.detail}", status_code=303)
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


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}
