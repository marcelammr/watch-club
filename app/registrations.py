from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.accounts import utcnow
from app.db import close_exclusive_session, exclusive_write_session
from app.mail import (
    MailDeliveryError,
    send_registration_approved_email,
    send_registration_rejected_email,
    send_registration_review_approved_email,
    send_registration_review_rejected_email,
)
from app.models import RegistrationRequest, RegistrationReview, User

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
STATUS_LABELS = {
    STATUS_PENDING: "Pendente",
    STATUS_APPROVED: "Aprovada",
    STATUS_REJECTED: "Recusada",
    STATUS_EXPIRED: "Expirada",
}
REGISTRATION_PENDING_DAYS = 7
EXPIRED_DECISION_MESSAGE = "Esta solicitação expirou e não pode mais ser aprovada/recusada."
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_LABELS = {
    REVIEW_PENDING: "Pendente",
    REVIEW_APPROVED: "Aprovada",
    REVIEW_REJECTED: "Recusada",
}
REVIEW_MESSAGE_MAX = 500
REVIEW_EMPTY_MESSAGE = "Escreva uma justificativa curta para solicitar a revisão."
REVIEW_TOO_LONG_MESSAGE = "A justificativa deve ter no máximo 500 caracteres."
REVIEW_ALREADY_DECIDED_MESSAGE = "Esta revisão já foi analisada."


def is_site_admin(user: User | None) -> bool:
    return bool(user and user.is_active and getattr(user, "is_site_admin", False))


def require_site_admin(user: User) -> User:
    if not is_site_admin(user):
        raise HTTPException(status_code=403, detail="Acesso restrito à administração")
    return user


def registration_expires_at(created_at: datetime | None) -> datetime | None:
    if created_at is None:
        return None
    return created_at + timedelta(days=REGISTRATION_PENDING_DAYS)


def is_registration_overdue(request: RegistrationRequest | None, now: datetime | None = None) -> bool:
    if request is None or request.status != STATUS_PENDING or request.created_at is None:
        return False
    moment = now or utcnow()
    return moment >= registration_expires_at(request.created_at)


def effective_registration_status(request: RegistrationRequest | None, now: datetime | None = None) -> str | None:
    if request is None:
        return None
    if is_registration_overdue(request, now):
        return STATUS_EXPIRED
    return request.status


def expire_registration_if_needed(db: Session, request: RegistrationRequest | None) -> RegistrationRequest | None:
    if request is None:
        return None
    if request.status == STATUS_EXPIRED:
        return request
    if not is_registration_overdue(request):
        return request
    request.status = STATUS_EXPIRED
    request.decided_at = utcnow()
    request.decided_by_user_id = None
    db.flush()
    return request


def expire_overdue_pending(db: Session) -> int:
    cutoff = utcnow() - timedelta(days=REGISTRATION_PENDING_DAYS)
    overdue = list(
        db.scalars(
            select(RegistrationRequest).where(
                RegistrationRequest.status == STATUS_PENDING,
                RegistrationRequest.created_at <= cutoff,
            )
        )
    )
    now = utcnow()
    for item in overdue:
        item.status = STATUS_EXPIRED
        item.decided_at = now
        item.decided_by_user_id = None
    if overdue:
        db.flush()
    return len(overdue)


def latest_registration_for_user(db: Session, user_id: int) -> RegistrationRequest | None:
    return db.scalar(
        select(RegistrationRequest)
        .where(RegistrationRequest.user_id == user_id)
        .order_by(RegistrationRequest.created_at.desc(), RegistrationRequest.id.desc())
    )


def registration_status_for_user(db: Session, user_id: int) -> str | None:
    request = expire_registration_if_needed(db, latest_registration_for_user(db, user_id))
    return request.status if request else None


def ensure_pending_registration(db: Session, user_id: int, *, created_at=None) -> RegistrationRequest:
    latest = expire_registration_if_needed(db, latest_registration_for_user(db, user_id))
    if latest:
        return latest
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
    from app.notifications import notify_registration_request

    notify_registration_request(db, user_id, request.id)
    return request


def list_pending_registrations(db: Session) -> list[RegistrationRequest]:
    expire_overdue_pending(db)
    cutoff = utcnow() - timedelta(days=REGISTRATION_PENDING_DAYS)
    return list(
        db.scalars(
            select(RegistrationRequest)
            .options(selectinload(RegistrationRequest.user))
            .where(
                RegistrationRequest.status == STATUS_PENDING,
                RegistrationRequest.created_at > cutoff,
            )
            .order_by(RegistrationRequest.created_at.asc(), RegistrationRequest.id.asc())
        )
    )


def get_registration(db: Session, request_id: int) -> RegistrationRequest | None:
    request = db.scalar(
        select(RegistrationRequest)
        .options(selectinload(RegistrationRequest.user))
        .where(RegistrationRequest.id == request_id)
    )
    return expire_registration_if_needed(db, request)


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


def approve_registration(source: Session, request_id: int, actor_id: int) -> str:
    notify = None
    status = None
    write = exclusive_write_session(source)
    try:
        request, actor = _load_pending_for_decision(write, request_id, actor_id)
        user = write.get(User, request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Solicitação não encontrada")
        expire_registration_if_needed(write, request)
        if request.status == STATUS_APPROVED:
            if not user.is_active:
                user.is_active = True
                write.commit()
            status = request.status
        elif request.status == STATUS_EXPIRED:
            write.commit()
            status = request.status
        elif request.status != STATUS_PENDING:
            raise HTTPException(status_code=400, detail="Esta solicitação já foi decidida.")
        else:
            notify = (STATUS_APPROVED, user.email, user.name)
            request.status = STATUS_APPROVED
            request.decided_at = utcnow()
            request.decided_by_user_id = actor.id
            user.is_active = True
            write.commit()
            status = request.status
    except IntegrityError:
        write.rollback()
        request = write.get(RegistrationRequest, request_id)
        if request and request.status == STATUS_APPROVED:
            user = write.get(User, request.user_id)
            if user and not user.is_active:
                user.is_active = True
                write.commit()
            status = request.status
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
    return status


def reject_registration(source: Session, request_id: int, actor_id: int) -> str:
    notify = None
    status = None
    write = exclusive_write_session(source)
    try:
        request, actor = _load_pending_for_decision(write, request_id, actor_id)
        user = write.get(User, request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Solicitação não encontrada")
        expire_registration_if_needed(write, request)
        if request.status == STATUS_REJECTED:
            status = request.status
        elif request.status == STATUS_EXPIRED:
            write.commit()
            status = request.status
        elif request.status != STATUS_PENDING:
            raise HTTPException(status_code=400, detail="Esta solicitação já foi decidida.")
        else:
            notify = (STATUS_REJECTED, user.email, user.name)
            request.status = STATUS_REJECTED
            request.decided_at = utcnow()
            request.decided_by_user_id = actor.id
            user.is_active = False
            write.commit()
            status = request.status
    except IntegrityError:
        write.rollback()
        request = write.get(RegistrationRequest, request_id)
        if request and request.status == STATUS_REJECTED:
            status = request.status
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
    return status


def registration_followup_path(db: Session, user: User) -> str:
    if user.is_active:
        return "/"
    request = expire_registration_if_needed(db, latest_registration_for_user(db, user.id))
    if request is None:
        return "/auth/aguardando"
    if request.status == STATUS_EXPIRED:
        return "/auth/expirada"
    if request.status == STATUS_REJECTED:
        review = review_for_registration(db, request.id)
        if review is None:
            return "/auth/nao-aprovado"
        if review.status == REVIEW_PENDING:
            return "/auth/revisao-solicitada"
        if review.status == REVIEW_REJECTED:
            return "/auth/revisao-nao-aprovada"
        if review.status == REVIEW_APPROVED:
            return "/"
        return "/auth/nao-aprovado"
    return "/auth/aguardando"


def review_for_registration(db: Session, request_id: int) -> RegistrationReview | None:
    return db.scalar(
        select(RegistrationReview).where(RegistrationReview.registration_request_id == request_id)
    )


def normalize_review_message(raw: str | None) -> str:
    return (raw or "").strip()


def list_pending_reviews(db: Session) -> list[RegistrationReview]:
    return list(
        db.scalars(
            select(RegistrationReview)
            .options(
                selectinload(RegistrationReview.user),
                selectinload(RegistrationReview.request).selectinload(RegistrationRequest.user),
            )
            .where(RegistrationReview.status == REVIEW_PENDING)
            .order_by(RegistrationReview.created_at.asc(), RegistrationReview.id.asc())
        )
    )


def get_registration_review(db: Session, review_id: int) -> RegistrationReview | None:
    return db.scalar(
        select(RegistrationReview)
        .options(
            selectinload(RegistrationReview.user),
            selectinload(RegistrationReview.decided_by),
            selectinload(RegistrationReview.request).selectinload(RegistrationRequest.user),
            selectinload(RegistrationReview.request).selectinload(RegistrationRequest.decided_by),
        )
        .where(RegistrationReview.id == review_id)
    )


def _deliver_review_decision_email(kind: str, email: str, name: str) -> None:
    if not (email or "").strip():
        return
    try:
        if kind == REVIEW_APPROVED:
            send_registration_review_approved_email(email, name)
        elif kind == REVIEW_REJECTED:
            send_registration_review_rejected_email(email, name)
    except MailDeliveryError:
        print(f"[watch-club] decisão da revisão {kind} persistida, mas o e-mail para {email} não foi enviado")


def create_registration_review(source: Session, user_id: int, message: str) -> tuple[str | None, int | None]:
    text = normalize_review_message(message)
    if not text:
        raise HTTPException(status_code=400, detail=REVIEW_EMPTY_MESSAGE)
    if len(text) > REVIEW_MESSAGE_MAX:
        raise HTTPException(status_code=400, detail=REVIEW_TOO_LONG_MESSAGE)
    status = None
    review_id = None
    write = exclusive_write_session(source)
    try:
        request = expire_registration_if_needed(write, latest_registration_for_user(write, user_id))
        if request is None or request.status != STATUS_REJECTED:
            write.commit()
        else:
            existing = review_for_registration(write, request.id)
            if existing:
                status = existing.status
                review_id = existing.id
            else:
                review = RegistrationReview(
                    registration_request_id=request.id,
                    user_id=user_id,
                    message=text,
                    status=REVIEW_PENDING,
                    created_at=utcnow(),
                    decided_at=None,
                    decided_by_user_id=None,
                )
                write.add(review)
                write.flush()
                from app.notifications import notify_registration_review

                notify_registration_review(write, user_id, review.id)
                write.commit()
                status = review.status
                review_id = review.id
    except IntegrityError:
        write.rollback()
        request = expire_registration_if_needed(write, latest_registration_for_user(write, user_id))
        existing = review_for_registration(write, request.id) if request else None
        if existing:
            status = existing.status
            review_id = existing.id
        write.commit()
    except HTTPException:
        write.rollback()
        raise
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)
    return status, review_id


def _load_review_for_decision(write: Session, review_id: int, actor_id: int) -> tuple[RegistrationReview, User]:
    actor = write.get(User, actor_id)
    if not is_site_admin(actor):
        raise HTTPException(status_code=403, detail="Acesso restrito à administração")
    review = write.get(RegistrationReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Revisão não encontrada")
    return review, actor


def approve_registration_review(source: Session, review_id: int, actor_id: int) -> tuple[str, bool]:
    notify = None
    status = None
    applied = False
    write = exclusive_write_session(source)
    try:
        review, actor = _load_review_for_decision(write, review_id, actor_id)
        user = write.get(User, review.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Revisão não encontrada")
        if review.status == REVIEW_APPROVED:
            if not user.is_active:
                user.is_active = True
                write.commit()
            status = review.status
        elif review.status != REVIEW_PENDING:
            status = review.status
        else:
            notify = (REVIEW_APPROVED, user.email, user.name)
            review.status = REVIEW_APPROVED
            review.decided_at = utcnow()
            review.decided_by_user_id = actor.id
            user.is_active = True
            write.commit()
            status = review.status
            applied = True
    except IntegrityError:
        write.rollback()
        review = write.get(RegistrationReview, review_id)
        if review and review.status == REVIEW_APPROVED:
            user = write.get(User, review.user_id)
            if user and not user.is_active:
                user.is_active = True
                write.commit()
            status = review.status
        else:
            raise HTTPException(status_code=400, detail="Não foi possível aprovar a revisão.")
    except HTTPException:
        write.rollback()
        raise
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)
    if notify:
        _deliver_review_decision_email(*notify)
    return status, applied


def reject_registration_review(source: Session, review_id: int, actor_id: int) -> tuple[str, bool]:
    notify = None
    status = None
    applied = False
    write = exclusive_write_session(source)
    try:
        review, actor = _load_review_for_decision(write, review_id, actor_id)
        user = write.get(User, review.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Revisão não encontrada")
        if review.status == REVIEW_REJECTED:
            status = review.status
        elif review.status != REVIEW_PENDING:
            status = review.status
        else:
            notify = (REVIEW_REJECTED, user.email, user.name)
            review.status = REVIEW_REJECTED
            review.decided_at = utcnow()
            review.decided_by_user_id = actor.id
            user.is_active = False
            write.commit()
            status = review.status
            applied = True
    except IntegrityError:
        write.rollback()
        review = write.get(RegistrationReview, review_id)
        if review and review.status == REVIEW_REJECTED:
            status = review.status
        else:
            raise HTTPException(status_code=400, detail="Não foi possível recusar a revisão.")
    except HTTPException:
        write.rollback()
        raise
    except Exception:
        write.rollback()
        raise
    finally:
        close_exclusive_session(write)
    if notify:
        _deliver_review_decision_email(*notify)
    return status, applied

