from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.accounts import utcnow
from app.db import close_exclusive_session, exclusive_write_session
from app.mail import MailDeliveryError, send_registration_approved_email, send_registration_rejected_email
from app.models import RegistrationRequest, User

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_LABELS = {
    STATUS_PENDING: "Pendente",
    STATUS_APPROVED: "Aprovada",
    STATUS_REJECTED: "Recusada",
}


def is_site_admin(user: User | None) -> bool:
    return bool(user and user.is_active and getattr(user, "is_site_admin", False))


def require_site_admin(user: User) -> User:
    if not is_site_admin(user):
        raise HTTPException(status_code=403, detail="Acesso restrito à administração")
    return user


def latest_registration_for_user(db: Session, user_id: int) -> RegistrationRequest | None:
    return db.scalar(
        select(RegistrationRequest)
        .where(RegistrationRequest.user_id == user_id)
        .order_by(RegistrationRequest.created_at.desc(), RegistrationRequest.id.desc())
    )


def registration_status_for_user(db: Session, user_id: int) -> str | None:
    request = latest_registration_for_user(db, user_id)
    return request.status if request else None


def ensure_pending_registration(db: Session, user_id: int, *, created_at=None) -> RegistrationRequest:
    existing = db.scalar(
        select(RegistrationRequest).where(
            RegistrationRequest.user_id == user_id,
            RegistrationRequest.status == STATUS_PENDING,
        )
    )
    if existing:
        return existing
    request = RegistrationRequest(
        user_id=user_id,
        status=STATUS_PENDING,
        created_at=created_at or utcnow(),
        decided_at=None,
        decided_by_user_id=None,
        decision_note=None,
    )
    db.add(request)
    db.flush()
    return request


def list_pending_registrations(db: Session) -> list[RegistrationRequest]:
    return list(
        db.scalars(
            select(RegistrationRequest)
            .options(selectinload(RegistrationRequest.user))
            .where(RegistrationRequest.status == STATUS_PENDING)
            .order_by(RegistrationRequest.created_at.asc(), RegistrationRequest.id.asc())
        )
    )


def get_registration(db: Session, request_id: int) -> RegistrationRequest | None:
    return db.scalar(
        select(RegistrationRequest)
        .options(selectinload(RegistrationRequest.user))
        .where(RegistrationRequest.id == request_id)
    )


def _deliver_registration_decision_email(kind: str, email: str, name: str) -> None:
    if not (email or "").strip():
        return
    try:
        if kind == STATUS_APPROVED:
            send_registration_approved_email(email, name)
        elif kind == STATUS_REJECTED:
            send_registration_rejected_email(email, name)
    except MailDeliveryError:
        print(f"[watch-club] decisão {kind} persistida, mas o e-mail para {email} não foi enviado")


def _load_pending_for_decision(write: Session, request_id: int, actor_id: int) -> tuple[RegistrationRequest, User]:
    actor = write.get(User, actor_id)
    if not is_site_admin(actor):
        raise HTTPException(status_code=403, detail="Acesso restrito à administração")
    request = write.get(RegistrationRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    return request, actor


def approve_registration(source: Session, request_id: int, actor_id: int) -> RegistrationRequest:
    notify = None
    result = None
    write = exclusive_write_session(source)
    try:
        request, actor = _load_pending_for_decision(write, request_id, actor_id)
        user = write.get(User, request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Solicitação não encontrada")
        if request.status == STATUS_APPROVED:
            if not user.is_active:
                user.is_active = True
                write.commit()
            result = request
        elif request.status != STATUS_PENDING:
            raise HTTPException(status_code=400, detail="Esta solicitação já foi decidida.")
        else:
            notify = (STATUS_APPROVED, user.email, user.name)
            request.status = STATUS_APPROVED
            request.decided_at = utcnow()
            request.decided_by_user_id = actor.id
            user.is_active = True
            write.commit()
            result = request
    except IntegrityError:
        write.rollback()
        request = write.get(RegistrationRequest, request_id)
        if request and request.status == STATUS_APPROVED:
            user = write.get(User, request.user_id)
            if user and not user.is_active:
                user.is_active = True
                write.commit()
            result = request
        else:
            raise HTTPException(status_code=400, detail="Não foi possível aprovar a solicitação.")
    except HTTPException:
        write.rollback()
        raise
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)
    if notify:
        _deliver_registration_decision_email(*notify)
    return result


def reject_registration(source: Session, request_id: int, actor_id: int) -> RegistrationRequest:
    notify = None
    result = None
    write = exclusive_write_session(source)
    try:
        request, actor = _load_pending_for_decision(write, request_id, actor_id)
        user = write.get(User, request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Solicitação não encontrada")
        if request.status == STATUS_REJECTED:
            result = request
        elif request.status != STATUS_PENDING:
            raise HTTPException(status_code=400, detail="Esta solicitação já foi decidida.")
        else:
            notify = (STATUS_REJECTED, user.email, user.name)
            request.status = STATUS_REJECTED
            request.decided_at = utcnow()
            request.decided_by_user_id = actor.id
            user.is_active = False
            write.commit()
            result = request
    except IntegrityError:
        write.rollback()
        request = write.get(RegistrationRequest, request_id)
        if request and request.status == STATUS_REJECTED:
            result = request
        else:
            raise HTTPException(status_code=400, detail="Não foi possível recusar a solicitação.")
    except HTTPException:
        write.rollback()
        raise
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)
    if notify:
        _deliver_registration_decision_email(*notify)
    return result
