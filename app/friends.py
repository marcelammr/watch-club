from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

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


def post_dm(db: Session, sender_id: int, recipient_id: int, body: str) -> DirectMessage:
    if sender_id == recipient_id:
        raise HTTPException(status_code=400, detail="Não é possível enviar mensagem para si mesmo")
    if relation_status(db, sender_id, recipient_id) != "friends":
        raise HTTPException(status_code=403, detail="Só amigos podem enviar mensagens")
    text = (body or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Escreva uma mensagem")
    message = DirectMessage(sender_id=sender_id, recipient_id=recipient_id, body=text[:2000])
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
