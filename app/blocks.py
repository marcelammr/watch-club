from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.accounts import utcnow
from app.friends import friendship_between
from app.models import Friendship, User, UserBlock
from app.usernames import normalize_username

MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_]{3,30})\b")

BLOCKED_DM = "Você não pode enviar mensagens privadas para este usuário enquanto o bloqueio existir."
BLOCKED_FRIEND = "Não é possível enviar pedido de amizade enquanto o bloqueio existir."
BLOCKED_MENTION = "Você não pode mencionar ou responder diretamente um usuário bloqueado."


def are_blocked(db: Session, user_a: int, user_b: int) -> bool:
    if user_a == user_b:
        return False
    return (
        db.scalar(
            select(UserBlock.id).where(
                or_(
                    (UserBlock.blocker_id == user_a) & (UserBlock.blocked_id == user_b),
                    (UserBlock.blocker_id == user_b) & (UserBlock.blocked_id == user_a),
                )
            )
        )
        is not None
    )


def ids_blocked_by(db: Session, blocker_id: int) -> set[int]:
    return set(db.scalars(select(UserBlock.blocked_id).where(UserBlock.blocker_id == blocker_id)))


def blocked_pair_ids(db: Session, user_id: int) -> set[int]:
    rows = db.execute(
        select(UserBlock.blocker_id, UserBlock.blocked_id).where(
            or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
    )
    ids: set[int] = set()
    for blocker_id, blocked_id in rows:
        ids.add(blocked_id if blocker_id == user_id else blocker_id)
    return ids


def block_row(db: Session, blocker_id: int, blocked_id: int) -> UserBlock | None:
    return db.scalar(
        select(UserBlock).where(UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id)
    )


def list_blocked_users(db: Session, blocker_id: int) -> list[User]:
    rows = list(
        db.scalars(
            select(UserBlock)
            .options(selectinload(UserBlock.blocked))
            .where(UserBlock.blocker_id == blocker_id)
            .order_by(UserBlock.created_at.desc())
        )
    )
    return [row.blocked for row in rows if row.blocked]


def block_user(db: Session, blocker_id: int, blocked_id: int) -> UserBlock:
    if blocker_id == blocked_id:
        raise HTTPException(status_code=400, detail="Você não pode bloquear a si mesmo")
    existing = block_row(db, blocker_id, blocked_id)
    if existing:
        return existing
    row = UserBlock(blocker_id=blocker_id, blocked_id=blocked_id, created_at=utcnow())
    db.add(row)
    friendship = friendship_between(db, blocker_id, blocked_id)
    if friendship is not None:
        db.delete(friendship)
    db.commit()
    db.refresh(row)
    return row


def unblock_user(db: Session, blocker_id: int, blocked_id: int) -> None:
    row = block_row(db, blocker_id, blocked_id)
    if row is None:
        raise HTTPException(status_code=400, detail="Este usuário não está bloqueado")
    db.delete(row)
    db.commit()


def assert_not_blocked(db: Session, user_a: int, user_b: int, detail: str) -> None:
    if are_blocked(db, user_a, user_b):
        raise HTTPException(status_code=403, detail=detail)


def mentioned_usernames(text: str) -> set[str]:
    return {normalize_username(match) for match in MENTION_RE.findall(text or "") if match}


def assert_no_blocked_mention(db: Session, actor_id: int, text: str) -> None:
    keys = mentioned_usernames(text)
    if not keys:
        return
    people = list(db.scalars(select(User).where(User.username_key.in_(keys))))
    for person in people:
        if are_blocked(db, actor_id, person.id):
            raise HTTPException(status_code=400, detail=BLOCKED_MENTION)
