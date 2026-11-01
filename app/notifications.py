from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts import utcnow
from app.club_tags import stamp_display_tags
from app.db import SessionLocal
from app.models import Club, ClubJoinRequest, ClubMember, Notification, User
from app.roles import PERM_JOINS, can

TYPE_JOIN_REQUEST = "join_request"
TYPE_JOIN_ACCEPTED = "join_request_accepted"
JOIN_STATE_PENDING = "pending"
JOIN_STATE_JOINED = "joined"
JOIN_STATE_RESOLVED = "resolved"
DEFAULT_LIST_LIMIT = 50
HEADER_PREVIEW_LIMIT = 5
JOIN_MISSING_DETAIL = "Solicitação não encontrada"
JOIN_ALREADY_RESOLVED = "Solicitação já resolvida"
NOTICE_POLL_SECONDS = 25


def notify_join_request(db: Session, club_id: int, actor_user_id: int, request_id: int) -> list[Notification]:
    members = list(db.scalars(select(ClubMember).where(ClubMember.club_id == club_id)))
    created: list[Notification] = []
    now = utcnow()
    for member in members:
        if member.user_id == actor_user_id:
            continue
        if not can(member, PERM_JOINS):
            continue
        item = Notification(
            user_id=member.user_id,
            type=TYPE_JOIN_REQUEST,
            club_id=club_id,
            actor_user_id=actor_user_id,
            related_id=request_id,
            created_at=now,
        )
        db.add(item)
        created.append(item)
    if created:
        db.flush()
    return created


def notify_join_accepted(db: Session, club_id: int, requester_id: int, actor_id: int) -> Notification:
    item = Notification(
        user_id=requester_id,
        type=TYPE_JOIN_ACCEPTED,
        club_id=club_id,
        actor_user_id=actor_id,
        related_id=None,
        created_at=utcnow(),
    )
    db.add(item)
    db.flush()
    return item


def unread_count(db: Session, user_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )


def list_notifications(db: Session, user_id: int, limit: int = DEFAULT_LIST_LIMIT) -> list[Notification]:
    if limit < 1:
        limit = DEFAULT_LIST_LIMIT
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
        )
    )


def mark_read(db: Session, user_id: int, notification_id: int) -> Notification | None:
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != user_id:
        return None
    if item.read_at is None:
        item.read_at = utcnow()
    return item


def mark_all_read(db: Session, user_id: int) -> int:
    items = list(
        db.scalars(
            select(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
    )
    if not items:
        return 0
    now = utcnow()
    for item in items:
        item.read_at = now
    return len(items)


def join_subject_id(notification: Notification) -> int:
    if notification.type == TYPE_JOIN_ACCEPTED:
        return notification.user_id
    return notification.actor_user_id


def _same_join_event(notification: Notification, pending: ClubJoinRequest | None) -> bool:
    if pending is None:
        return False
    if pending.club_id != notification.club_id or pending.user_id != notification.actor_user_id:
        return False
    if notification.related_id and pending.id != notification.related_id:
        return False
    if notification.created_at and pending.created_at and pending.created_at > notification.created_at + timedelta(seconds=5):
        return False
    return True


def _live_join_request(db: Session, notification: Notification) -> ClubJoinRequest | None:
    if notification.type != TYPE_JOIN_REQUEST:
        return None
    if notification.related_id:
        return db.get(ClubJoinRequest, notification.related_id)
    return db.scalar(
        select(ClubJoinRequest).where(
            ClubJoinRequest.club_id == notification.club_id,
            ClubJoinRequest.user_id == notification.actor_user_id,
        )
    )


def join_request_state(db: Session, notification: Notification) -> str:
    if notification.type == TYPE_JOIN_REQUEST:
        pending = _live_join_request(db, notification)
        if _same_join_event(notification, pending):
            return JOIN_STATE_PENDING
    member = db.scalar(
        select(ClubMember).where(
            ClubMember.club_id == notification.club_id,
            ClubMember.user_id == join_subject_id(notification),
        )
    )
    if member is not None:
        return JOIN_STATE_JOINED
    return JOIN_STATE_RESOLVED


def unread_badge(count: int) -> str:
    if count <= 0:
        return ""
    if count > 9:
        return "9+"
    return str(count)


def format_notification_when(value: datetime | None) -> str:
    if value is None:
        return ""
    seconds = int((utcnow() - value).total_seconds())
    if seconds < 45:
        return "agora"
    if seconds < 3600:
        minutes = max(1, seconds // 60)
        return f"há {minutes} min"
    if seconds < 86400:
        hours = max(1, seconds // 3600)
        return f"há {hours} h"
    if seconds < 172800:
        return "ontem"
    return value.strftime("%d/%m/%Y")


def mark_own_join_notifications_read(
    db: Session, user_id: int, club_id: int, actor_user_id: int, related_id: int | None = None
) -> None:
    now = utcnow()
    filters = [
        Notification.user_id == user_id,
        Notification.type == TYPE_JOIN_REQUEST,
        Notification.club_id == club_id,
        Notification.actor_user_id == actor_user_id,
        Notification.read_at.is_(None),
    ]
    if related_id:
        filters.append(Notification.related_id == related_id)
    items = list(db.scalars(select(Notification).where(*filters)))
    for item in items:
        item.read_at = now


def notification_cards(db: Session, user_id: int, limit: int = DEFAULT_LIST_LIMIT) -> list[dict]:
    rows = list_notifications(db, user_id, limit)
    if not rows:
        return []
    actor_ids = {item.actor_user_id for item in rows}
    club_ids = {item.club_id for item in rows}
    actors = {user.id: user for user in db.scalars(select(User).where(User.id.in_(actor_ids)))}
    clubs = {club.id: club for club in db.scalars(select(Club).where(Club.id.in_(club_ids)))}
    stamp_display_tags(db, list(actors.values()))
    mine = {
        member.club_id: member
        for member in db.scalars(
            select(ClubMember).where(ClubMember.user_id == user_id, ClubMember.club_id.in_(club_ids))
        )
    }
    related_ids = {item.related_id for item in rows if item.type == TYPE_JOIN_REQUEST and item.related_id}
    live_by_id: dict[int, ClubJoinRequest] = {}
    if related_ids:
        live_by_id = {
            row.id: row
            for row in db.scalars(select(ClubJoinRequest).where(ClubJoinRequest.id.in_(related_ids)))
        }
    pair_ids = {
        (item.club_id, item.actor_user_id)
        for item in rows
        if item.type == TYPE_JOIN_REQUEST and not item.related_id
    }
    live_by_pair: dict[tuple[int, int], ClubJoinRequest] = {}
    if pair_ids:
        club_ids_pending = {club_id for club_id, _user_id in pair_ids}
        user_ids_pending = {user_id for _club_id, user_id in pair_ids}
        for row in db.scalars(
            select(ClubJoinRequest).where(
                ClubJoinRequest.club_id.in_(club_ids_pending),
                ClubJoinRequest.user_id.in_(user_ids_pending),
            )
        ):
            if (row.club_id, row.user_id) in pair_ids:
                live_by_pair[(row.club_id, row.user_id)] = row
    subject_ids = {join_subject_id(item) for item in rows}
    joined = {
        (club_id, user_id)
        for club_id, user_id in db.execute(
            select(ClubMember.club_id, ClubMember.user_id).where(
                ClubMember.club_id.in_(club_ids),
                ClubMember.user_id.in_(subject_ids),
            )
        )
    }
    cards = []
    for item in rows:
        pending = live_by_id.get(item.related_id) if item.related_id else live_by_pair.get((item.club_id, item.actor_user_id))
        if item.type == TYPE_JOIN_REQUEST and _same_join_event(item, pending):
            state = JOIN_STATE_PENDING
        elif (item.club_id, join_subject_id(item)) in joined:
            state = JOIN_STATE_JOINED
        else:
            state = JOIN_STATE_RESOLVED
        can_manage = item.type == TYPE_JOIN_REQUEST and can(mine.get(item.club_id), PERM_JOINS)
        cards.append(
            {
                "notification": item,
                "actor": actors.get(item.actor_user_id),
                "club": clubs.get(item.club_id),
                "state": state,
                "can_manage": can_manage,
                "unread": item.read_at is None,
            }
        )
    return cards


def unread_label(count: int) -> str:
    if count == 1:
        return "Notificações, 1 não lida"
    if count > 1:
        return f"Notificações, {count} não lidas"
    return "Notificações"


def header_snapshot(db: Session, user_id: int) -> dict:
    count = unread_count(db, user_id)
    return {
        "unread": count,
        "badge": unread_badge(count),
        "label": unread_label(count),
        "cards": notification_cards(db, user_id, HEADER_PREVIEW_LIMIT),
    }


def header_notification_context(request: Request) -> dict:
    empty = {
        "notification_unread": 0,
        "notification_badge": "",
        "header_notifications": [],
    }
    user_id = request.session.get("user_id") if request.session else None
    if not user_id:
        return empty
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user or not user.is_active:
            return empty
        count = unread_count(db, user.id)
        return {
            "notification_unread": count,
            "notification_badge": unread_badge(count),
            "header_notifications": notification_cards(db, user.id, HEADER_PREVIEW_LIMIT),
        }
    finally:
        db.close()

