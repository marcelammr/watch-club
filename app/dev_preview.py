"""TEMPORARY visual showcase for the access/signup polish.

Enable only in local development with WATCH_CLUB_UI_PREVIEW=true and
SESSION_HTTPS_ONLY=false. Renders real templates with in-memory fakes.
Does not write to the database, send mail, create notifications, or call Auth0.

Remove or keep disabled before deploy.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from app.accounts import utcnow
from app.config import SESSION_HTTPS_ONLY, WATCH_CLUB_UI_PREVIEW
from app.registrations import REVIEW_LABELS, REVIEW_PENDING, STATUS_LABELS, STATUS_PENDING


def ui_preview_enabled() -> bool:
    from app import config as app_config

    flag = bool(getattr(app_config, "WATCH_CLUB_UI_PREVIEW", WATCH_CLUB_UI_PREVIEW))
    https_only = bool(getattr(app_config, "SESSION_HTTPS_ONLY", SESSION_HTTPS_ONLY))
    return flag and not https_only


def _require_preview() -> None:
    if not ui_preview_enabled():
        raise HTTPException(status_code=404)


def _person(**extra):
    data = {
        "id": 0,
        "name": "Azi",
        "username": "azi_crow",
        "email": "azi@example.com",
        "avatar": "popcorn",
        "avatar_type": "illustrated",
        "avatar_provider": "watchclub",
        "avatar_value": "popcorn",
        "presence": "offline",
        "presence_pref": "offline",
        "last_seen": None,
        "enter_sends": True,
        "is_active": True,
        "is_site_admin": True,
        "display_tag": None,
        "auth0_sub": "auth0|preview",
    }
    data.update(extra)
    return SimpleNamespace(**data)


def _identity(*, verified=True):
    return SimpleNamespace(email="azi@example.com", email_verified=verified, sub="auth0|preview")


def _request_row(status=STATUS_PENDING):
    now = utcnow()
    person = _person(is_site_admin=False, is_active=False)
    admin = _person(name="Marcela", username="marcela")
    return SimpleNamespace(
        id=1,
        status=status,
        created_at=now,
        decided_at=now if status != STATUS_PENDING else None,
        decided_by=admin if status != STATUS_PENDING else None,
        user=person,
    )


def _review_row(status=REVIEW_PENDING):
    request = _request_row("rejected")
    return SimpleNamespace(
        id=1,
        status=status,
        created_at=utcnow(),
        message="Gostaria de uma nova análise. Assisto séries em grupo há anos e quero participar do Watch Club.",
        user=request.user,
        request=request,
    )


def register_ui_preview_routes(app, templates) -> None:
    @app.get("/dev/acesso", response_class=HTMLResponse)
    def preview_index(request: Request):
        _require_preview()
        return templates.TemplateResponse(
            request,
            "dev_access.html",
            {"user": None, "screens": PREVIEW_SCREENS},
        )

    @app.get("/dev/acesso/{slug}", response_class=HTMLResponse)
    def preview_screen(request: Request, slug: str):
        _require_preview()
        screen = PREVIEW_PAGES.get(slug)
        if not screen:
            raise HTTPException(status_code=404)
        context = {"user": None, "ui_preview": True, **screen["context"]()}
        if screen.get("admin"):
            context["user"] = _person()
        return templates.TemplateResponse(request, screen["template"], context)


PREVIEW_SCREENS = [
    ("perfil", "Completar perfil"),
    ("verificacao", "Verificar e-mail"),
    ("aguardando", "Aguardando aprovação"),
    ("nao-aprovado", "Solicitação não aprovada"),
    ("revisao", "Solicitar revisão"),
    ("revisao-solicitada", "Revisão solicitada"),
    ("revisao-nao-aprovada", "Revisão não aprovada"),
    ("expirada", "Solicitação expirada"),
    ("cadastros", "Administração · Pendentes"),
    ("revisoes", "Administração · Revisões"),
    ("cadastro-detalhe", "Detalhe do cadastro"),
    ("revisao-detalhe", "Detalhe da revisão"),
]


PREVIEW_PAGES = {
    "perfil": {
        "template": "auth0_onboard.html",
        "context": lambda: {
            "identity": _identity(),
            "signup_step": "perfil",
            "error": "",
            "suggestions": ["azi_crow", "azi.crow", "azi_club"],
            "form": {"name": "Azi", "username": "azi_crow"},
        },
    },
    "verificacao": {
        "template": "auth0_verify_email.html",
        "context": lambda: {"identity": _identity(verified=False), "signup_step": "verificacao"},
    },
    "aguardando": {
        "template": "auth0_awaiting.html",
        "context": lambda: {
            "identity": _identity(),
            "signup_step": "aprovacao",
            "profile": _person(is_active=False, is_site_admin=False),
        },
    },
    "nao-aprovado": {
        "template": "auth0_rejected.html",
        "context": lambda: {
            "identity": _identity(),
            "profile": _person(is_active=False, is_site_admin=False),
        },
    },
    "revisao": {
        "template": "auth0_review_form.html",
        "context": lambda: {
            "identity": _identity(),
            "error": "",
            "message": "",
            "message_max": 500,
        },
    },
    "revisao-solicitada": {
        "template": "auth0_review_awaiting.html",
        "context": lambda: {
            "identity": _identity(),
            "profile": _person(is_active=False, is_site_admin=False),
        },
    },
    "revisao-nao-aprovada": {
        "template": "auth0_review_rejected.html",
        "context": lambda: {
            "identity": _identity(),
            "profile": _person(is_active=False, is_site_admin=False),
        },
    },
    "expirada": {
        "template": "auth0_expired.html",
        "context": lambda: {
            "identity": _identity(),
            "profile": _person(is_active=False, is_site_admin=False),
        },
    },
    "cadastros": {
        "admin": True,
        "template": "admin_registrations.html",
        "context": lambda: {
            "aba": "pendentes",
            "pending": [_request_row()],
            "reviews": [],
            "error": None,
            "ok": None,
        },
    },
    "revisoes": {
        "admin": True,
        "template": "admin_registrations.html",
        "context": lambda: {
            "aba": "revisoes",
            "pending": [],
            "reviews": [_review_row()],
            "error": None,
            "ok": None,
        },
    },
    "cadastro-detalhe": {
        "admin": True,
        "template": "admin_registration_detail.html",
        "context": lambda: {
            "item": _request_row(),
            "person": _person(is_active=False, is_site_admin=False),
            "status_label": STATUS_LABELS[STATUS_PENDING],
            "error": None,
            "ok": None,
        },
    },
    "revisao-detalhe": {
        "admin": True,
        "template": "admin_registration_review_detail.html",
        "context": lambda: {
            "item": _review_row(),
            "person": _person(is_active=False, is_site_admin=False),
            "status_label": REVIEW_LABELS[REVIEW_PENDING],
            "error": None,
            "ok": None,
        },
    },
}
