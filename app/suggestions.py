from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.accounts import utcnow
from app.models import Suggestion, User
from app.notifications import notify_suggestion
from app.registrations import require_site_admin

STATUS_SENT = "sent"
STATUS_REVIEWING = "reviewing"
STATUS_DONE = "done"
STATUSES = (STATUS_SENT, STATUS_REVIEWING, STATUS_DONE)
STATUS_LABELS = {
    STATUS_SENT: "Enviada",
    STATUS_REVIEWING: "Em análise",
    STATUS_DONE: "Concluída",
}
TITLE_MAX = 80
DESCRIPTION_MAX = 800


def status_label(status: str | None) -> str:
    return STATUS_LABELS.get((status or "").strip(), STATUS_LABELS[STATUS_SENT])


def _clean(value: str | None) -> str:
    return (value or "").strip()


def parse_suggestion_fields(title: str | None, description: str | None) -> tuple[str, str]:
    heading = _clean(title)
    body = _clean(description)
    if not heading:
        raise HTTPException(status_code=400, detail="Escreva um título para a sugestão")
    if len(heading) > TITLE_MAX:
        raise HTTPException(status_code=400, detail=f"O título pode ter no máximo {TITLE_MAX} caracteres")
    if not body:
        raise HTTPException(status_code=400, detail="Escreva a descrição da sugestão")
    if len(body) > DESCRIPTION_MAX:
        raise HTTPException(status_code=400, detail=f"A descrição pode ter no máximo {DESCRIPTION_MAX} caracteres")
    return heading, body


def create_suggestion(db: Session, user: User, title: str | None, description: str | None) -> Suggestion:
    heading, body = parse_suggestion_fields(title, description)
    now = utcnow()
    item = Suggestion(
        user_id=user.id,
        title=heading,
        description=body,
        status=STATUS_SENT,
        is_archived=False,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    notify_suggestion(db, user.id, item.id)
    db.commit()
    db.refresh(item)
    return item


def list_own_suggestions(db: Session, user_id: int) -> list[Suggestion]:
    return list(
        db.scalars(
            select(Suggestion)
            .where(Suggestion.user_id == user_id)
            .order_by(Suggestion.created_at.desc(), Suggestion.id.desc())
        )
    )


def list_admin_suggestions(db: Session, *, archived: bool = False) -> list[Suggestion]:
    return list(
        db.scalars(
            select(Suggestion)
            .options(selectinload(Suggestion.user))
            .where(Suggestion.is_archived.is_(archived))
            .order_by(Suggestion.created_at.desc(), Suggestion.id.desc())
        )
    )


def get_suggestion(db: Session, suggestion_id: int) -> Suggestion:
    item = db.get(Suggestion, suggestion_id)
    if not item:
        raise HTTPException(status_code=404, detail="Sugestão não encontrada")
    return item


def set_suggestion_status(db: Session, actor: User, suggestion_id: int, status: str | None) -> Suggestion:
    require_site_admin(actor)
    wanted = _clean(status)
    if wanted not in STATUSES:
        raise HTTPException(status_code=400, detail="Escolha um status válido")
    item = get_suggestion(db, suggestion_id)
    item.status = wanted
    item.updated_at = utcnow()
    db.commit()
    return item


def archive_suggestion(db: Session, actor: User, suggestion_id: int) -> Suggestion:
    require_site_admin(actor)
    item = get_suggestion(db, suggestion_id)
    item.is_archived = True
    item.updated_at = utcnow()
    db.commit()
    return item
