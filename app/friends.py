from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.accounts import utcnow
from app.models import DirectMessage, Friendship, User
from app.usernames import normalize_username

PENDING = "pending"
ACCEPTED = "accepted"


def pair_ids(user_a: int, user_b: int) -> tuple[int, int]:
    return (min(user_a, user_b), max(user_a, user_b))


def other_id(row: Friendship, user_id: int) -> int:
    return row.user_high_id if row.user_low_id == user_id else row.user_low_id


def find_active_user(db: Session, username: str) -> User | None:
    key = normalize_username(username)
    if not key:
        return None
    return db.scalar(select(User).where(User.username_key == key, User.is_active.is_(True)))


def friendship_between(db: Session, user_a: int, user_b: int) -> Friendship | None:
    if user_a == user_b:
        return None
    low, high = pair_ids(user_a, user_b)
    return db.scalar(
        select(Friendship).where(Friendship.user_low_id == low, Friendship.user_high_id == high)
    )


def relation_status(db: Session, viewer_id: int, other_id_value: int) -> str:
    if viewer_id == other_id_value:
        return "self"
    row = friendship_between(db, viewer_id, other_id_value)
    if not row:
        return "none"
    if row.status == ACCEPTED:
        return "friends"
    if row.requested_by_id == viewer_id:
        return "outgoing"
    return "incoming"


def friend_id_set(db: Session, user_id: int) -> set[int]:
    rows = db.scalars(
        select(Friendship).where(
            Friendship.status == ACCEPTED,
            or_(Friendship.user_low_id == user_id, Friendship.user_high_id == user_id),
        )
    )
    return {other_id(row, user_id) for row in rows}


def person_href(viewer_id: int, person: User, friend_ids: set[int]) -> str:
    if person.id != viewer_id and person.id in friend_ids:
        return f"/mensagens/{person.username}"
    return f"/u/{person.username}"


def _users_by_ids(db: Session, ids: list[int]) -> list[User]:
    if not ids:
        return []
    people = list(db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))))
    people.sort(key=lambda item: (item.name or "").lower())
    return people


def list_friends(db: Session, user_id: int) -> list[User]:
    return _users_by_ids(db, list(friend_id_set(db, user_id)))


SEARCH_MIN = 2
SEARCH_LIMIT = 20


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%")


def relations_for(db: Session, viewer_id: int, people: list[User]) -> dict[int, str]:
    result = {person.id: "self" if person.id == viewer_id else "none" for person in people}
    others = [person.id for person in people if person.id != viewer_id]
    if not others:
        return result
    clauses = []
    for other in others:
        low, high = pair_ids(viewer_id, other)
        clauses.append(and_(Friendship.user_low_id == low, Friendship.user_high_id == high))
    rows = list(db.scalars(select(Friendship).where(or_(*clauses))))
    for row in rows:
        other = other_id(row, viewer_id)
        if row.status == ACCEPTED:
            result[other] = "friends"
        elif row.requested_by_id == viewer_id:
            result[other] = "outgoing"
        else:
            result[other] = "incoming"
    return result


def search_people(db: Session, viewer: User, query: str, limit: int = SEARCH_LIMIT) -> list[dict]:
    from app.accounts import utcnow
    from app.blocks import blocked_pair_ids

    raw = (query or "").strip().lstrip("@")
    if len(raw) < SEARCH_MIN:
        return []
    blocked = blocked_pair_ids(db, viewer.id)
    pattern = f"%{_escape_like(raw)}%"
    now = utcnow()
    filters = [
        User.is_active.is_(True),
        User.banned_at.is_(None),
        or_(User.suspended_until.is_(None), User.suspended_until <= now),
        or_(User.username_key.ilike(pattern, escape="\\"), User.name.ilike(pattern, escape="\\")),
    ]
    if blocked:
        filters.append(User.id.notin_(blocked))
    people = list(
        db.scalars(
            select(User)
            .where(*filters)
            .order_by(
                case((User.id == viewer.id, 0), else_=1),
                User.name.asc(),
            )
            .limit(limit)
        )
    )
    relations = relations_for(db, viewer.id, people)
    return [{"person": person, "relation": relations[person.id]} for person in people]


def incoming_invites(db: Session, user_id: int) -> list[User]:
    rows = db.scalars(
        select(Friendship).where(
            Friendship.status == PENDING,
            Friendship.requested_by_id != user_id,
            or_(Friendship.user_low_id == user_id, Friendship.user_high_id == user_id),
        )
    )
    return _users_by_ids(db, [other_id(row, user_id) for row in rows])


def send_invite(db: Session, from_id: int, to_id: int) -> Friendship:
    if from_id == to_id:
        raise HTTPException(status_code=400, detail="Você não pode adicionar a si mesmo")
    from app.blocks import BLOCKED_FRIEND, assert_not_blocked

    assert_not_blocked(db, from_id, to_id, BLOCKED_FRIEND)
    row = friendship_between(db, from_id, to_id)
    if row is None:
        low, high = pair_ids(from_id, to_id)
        row = Friendship(
            user_low_id=low,
            user_high_id=high,
            requested_by_id=from_id,
            status=PENDING,
        )
        db.add(row)
        db.flush()
        from app.notifications import notify_friend_request

        notify_friend_request(db, from_id, to_id, row.id)
        db.commit()
        return row
    if row.status == ACCEPTED:
        raise HTTPException(status_code=400, detail="Vocês já são amigos")
    if row.requested_by_id == from_id:
        raise HTTPException(status_code=400, detail="Pedido de amizade já enviado")
    row.status = ACCEPTED
    db.commit()
    return row


def accept_invite(db: Session, viewer_id: int, other: int) -> None:
    from app.blocks import BLOCKED_FRIEND, assert_not_blocked

    assert_not_blocked(db, viewer_id, other, BLOCKED_FRIEND)
    row = friendship_between(db, viewer_id, other)
    if not row or row.status != PENDING or row.requested_by_id == viewer_id:
        raise HTTPException(status_code=400, detail="Não há pedido para aceitar")
    row.status = ACCEPTED
    db.commit()


def decline_invite(db: Session, viewer_id: int, other: int) -> None:
    row = friendship_between(db, viewer_id, other)
    if not row or row.status != PENDING:
        raise HTTPException(status_code=400, detail="Não há pedido para recusar")
    db.delete(row)
    db.commit()


def unfriend(db: Session, viewer_id: int, other: int) -> None:
    row = friendship_between(db, viewer_id, other)
    if not row or row.status != ACCEPTED:
        raise HTTPException(status_code=400, detail="Vocês não são amigos")
    db.delete(row)
    db.commit()


def _pair_filter(viewer_id: int, other: int):
    return or_(
        and_(DirectMessage.sender_id == viewer_id, DirectMessage.recipient_id == other),
        and_(DirectMessage.sender_id == other, DirectMessage.recipient_id == viewer_id),
    )


def has_dm_history(db: Session, viewer_id: int, other: int) -> bool:
    if viewer_id == other:
        return False
    return (
        db.scalar(select(DirectMessage.id).where(_pair_filter(viewer_id, other)).limit(1)) is not None
    )


def can_view_thread(db: Session, viewer_id: int, other: int) -> bool:
    if viewer_id == other:
        return False
    if relation_status(db, viewer_id, other) == "friends":
        return True
    return has_dm_history(db, viewer_id, other)


def dm_thread(db: Session, viewer_id: int, other: int, limit: int = 80) -> list[DirectMessage]:
    if viewer_id == other:
        return []
    items = list(
        db.scalars(
            select(DirectMessage)
            .options(selectinload(DirectMessage.sender))
            .where(_pair_filter(viewer_id, other))
            .order_by(DirectMessage.id.desc())
            .limit(limit)
        )
    )
    items.reverse()
    return items


@dataclass
class DmInboxRow:
    person: User
    last: DirectMessage
    unread: int
    preview: str


def _preview_text(body: str, mine: bool) -> str:
    text = " ".join((body or "").split())
    if len(text) > 72:
        text = text[:71].rstrip() + "…"
    return f"Você: {text}" if mine else text


def unread_dm_count(db: Session, user_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(DirectMessage)
            .where(DirectMessage.recipient_id == user_id, DirectMessage.read_at.is_(None))
        )
        or 0
    )


def unread_dm_badge(count: int) -> str:
    if count <= 0:
        return ""
    if count > 9:
        return "9+"
    return str(count)


def mark_dm_read(db: Session, viewer_id: int, other: int) -> None:
    if viewer_id == other:
        return
    now = utcnow()
    items = list(
        db.scalars(
            select(DirectMessage).where(
                DirectMessage.sender_id == other,
                DirectMessage.recipient_id == viewer_id,
                DirectMessage.read_at.is_(None),
            )
        )
    )
    if not items:
        return
    for item in items:
        item.read_at = now
    db.commit()


def list_dm_conversations(db: Session, user_id: int) -> list[DmInboxRow]:
    other_id_expr = case(
        (DirectMessage.sender_id == user_id, DirectMessage.recipient_id),
        else_=DirectMessage.sender_id,
    )
    latest = (
        select(
            other_id_expr.label("other_id"),
            func.max(DirectMessage.id).label("last_id"),
        )
        .where(or_(DirectMessage.sender_id == user_id, DirectMessage.recipient_id == user_id))
        .group_by(other_id_expr)
        .subquery()
    )
    rows = db.execute(
        select(DirectMessage, User)
        .join(latest, DirectMessage.id == latest.c.last_id)
        .join(User, User.id == latest.c.other_id)
        .where(User.is_active.is_(True))
        .order_by(DirectMessage.created_at.desc(), DirectMessage.id.desc())
    ).all()
    unread_rows = db.execute(
        select(DirectMessage.sender_id, func.count())
        .where(DirectMessage.recipient_id == user_id, DirectMessage.read_at.is_(None))
        .group_by(DirectMessage.sender_id)
    ).all()
    unread_map = {sender_id: int(count) for sender_id, count in unread_rows}
    inbox: list[DmInboxRow] = []
    for message, person in rows:
        mine = message.sender_id == user_id
        inbox.append(
            DmInboxRow(
                person=person,
                last=message,
                unread=unread_map.get(person.id, 0),
                preview=_preview_text(message.body, mine),
            )
        )
    return inbox


def delete_dm(db: Session, viewer_id: int, other_id: int, message_id: int) -> None:
    if viewer_id == other_id:
        raise HTTPException(status_code=400, detail="Mensagem inválida")
    message = db.get(DirectMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada")
    in_thread = (
        (message.sender_id == viewer_id and message.recipient_id == other_id)
        or (message.sender_id == other_id and message.recipient_id == viewer_id)
    )
    if not in_thread:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada")
    if message.sender_id != viewer_id:
        raise HTTPException(status_code=403, detail="Você só pode apagar as suas mensagens")
    db.delete(message)
    db.commit()


def post_dm(db: Session, sender_id: int, recipient_id: int, body: str) -> DirectMessage:
    if sender_id == recipient_id:
        raise HTTPException(status_code=400, detail="Não é possível enviar mensagem para si mesmo")
    from app.blocks import BLOCKED_DM, assert_no_blocked_mention, assert_not_blocked
    from app.moderation import SURFACE_CHAT, enforce_text
    from app.models import User as AccountUser

    assert_not_blocked(db, sender_id, recipient_id, BLOCKED_DM)
    if relation_status(db, sender_id, recipient_id) != "friends":
        raise HTTPException(status_code=403, detail="Só amigos podem enviar mensagens")
    text = (body or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Escreva uma mensagem")
    assert_no_blocked_mention(db, sender_id, text)
    sender = db.get(AccountUser, sender_id)
    if sender is not None:
        enforce_text(db, sender, text, surface=SURFACE_CHAT, origin="dm")
    message = DirectMessage(sender_id=sender_id, recipient_id=recipient_id, body=text[:2000])
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
