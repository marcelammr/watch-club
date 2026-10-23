from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AccountInvite

STATUS_AVAILABLE = "available"
STATUS_USED = "used"
STATUS_REVOKED = "revoked"

MSG_INVALID = "Este convite não é válido."
MSG_USED = "Este convite já foi utilizado."
MSG_REVOKED = "Este convite não está mais disponível."
MSG_OAUTH_CLOSED = "Novas contas precisam de um convite. Cadastre-se com o código que você recebeu."

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CROCKFORD_SET = frozenset(CROCKFORD)
AMBIGUOUS = str.maketrans({"I": "1", "L": "1", "O": "0"})
CODE_BYTES = 8
CODE_LENGTH = 13
PREFIX = "WC"


class InviteSignupBlocked(ValueError):
    """OAuth tried to create a user while registration requires an invite."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def encode_crockford(data: bytes) -> str:
    value = int.from_bytes(data, "big")
    chars = (len(data) * 8 + 4) // 5
    out: list[str] = []
    for _ in range(chars):
        out.append(CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


def generate_canonical_code() -> str:
    from secrets import token_bytes

    return encode_crockford(token_bytes(CODE_BYTES))


def normalize_invite_code(raw: str | None) -> str:
    text = (raw or "").strip().upper().replace(" ", "").replace("-", "")
    if len(text) == CODE_LENGTH + len(PREFIX) and text.startswith(PREFIX):
        text = text[len(PREFIX) :]
    return text.translate(AMBIGUOUS)


def format_invite_code(canonical: str) -> str:
    chunks = [canonical[i : i + 4] for i in range(0, len(canonical), 4)]
    return f"{PREFIX}-" + "-".join(chunks)


def is_canonical_code(code: str) -> bool:
    return len(code) == CODE_LENGTH and all(char in CROCKFORD_SET for char in code)


def invite_error(invite: AccountInvite | None) -> str | None:
    if invite is None:
        return MSG_INVALID
    if invite.status == STATUS_USED:
        return MSG_USED
    if invite.status == STATUS_REVOKED:
        return MSG_REVOKED
    if invite.status != STATUS_AVAILABLE:
        return MSG_INVALID
    return None


def lookup_invite(db: Session, raw: str | None) -> tuple[AccountInvite | None, str | None]:
    canonical = normalize_invite_code(raw)
    if not is_canonical_code(canonical):
        return None, MSG_INVALID
    invite = db.scalar(select(AccountInvite).where(AccountInvite.code == canonical))
    error = invite_error(invite)
    if error:
        return invite, error
    return invite, None


def mark_invite_used(db: Session, invite: AccountInvite, user_id: int) -> bool:
    result = db.execute(
        update(AccountInvite)
        .where(AccountInvite.id == invite.id, AccountInvite.status == STATUS_AVAILABLE)
        .values(status=STATUS_USED, used_at=utcnow(), used_by_user_id=user_id)
    )
    db.flush()
    return result.rowcount == 1


def create_invite(db: Session) -> AccountInvite:
    for _ in range(16):
        code = generate_canonical_code()
        exists = db.scalar(select(AccountInvite.id).where(AccountInvite.code == code))
        if exists:
            continue
        invite = AccountInvite(code=code, status=STATUS_AVAILABLE)
        db.add(invite)
        db.flush()
        return invite
    raise RuntimeError("Não foi possível gerar um convite único")


def revoke_invite(db: Session, raw: str | None) -> tuple[bool, str]:
    canonical = normalize_invite_code(raw)
    if not is_canonical_code(canonical):
        return False, "Convite inexistente."
    invite = db.scalar(select(AccountInvite).where(AccountInvite.code == canonical))
    if invite is None:
        return False, "Convite inexistente."
    if invite.status == STATUS_USED:
        return False, "Este convite já foi utilizado."
    if invite.status == STATUS_REVOKED:
        return False, "Este convite já está revogado."
    invite.status = STATUS_REVOKED
    invite.revoked_at = utcnow()
    db.flush()
    return True, f"Convite {format_invite_code(invite.code)} revogado."


def _cmd_generate() -> int:
    db = SessionLocal()
    try:
        invite = create_invite(db)
        db.commit()
        print(format_invite_code(invite.code))
        return 0
    finally:
        db.close()


def _cmd_list() -> int:
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(AccountInvite).order_by(AccountInvite.id.desc())))
        if not rows:
            print("Nenhum convite.")
            return 0
        print(f"{'código':<22} {'status':<10} {'criado':<20} {'usado':<20} user_id")
        for row in rows:
            created = row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "-"
            used = row.used_at.strftime("%Y-%m-%d %H:%M") if row.used_at else "-"
            user = str(row.used_by_user_id) if row.used_by_user_id else "-"
            print(f"{format_invite_code(row.code):<22} {row.status:<10} {created:<20} {used:<20} {user}")
        return 0
    finally:
        db.close()


def _cmd_revoke(code: str) -> int:
    db = SessionLocal()
    try:
        ok, message = revoke_invite(db, code)
        if ok:
            db.commit()
        else:
            db.rollback()
        print(message)
        return 0 if ok else 1
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.invites", description="Convites de cadastro do Watch Club")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="Cria um convite e imprime o código")
    sub.add_parser("list", help="Lista convites e estados")
    revoke = sub.add_parser("revoke", help="Invalida um convite ainda disponível")
    revoke.add_argument("code")
    args = parser.parse_args(argv)
    if args.command == "generate":
        return _cmd_generate()
    if args.command == "list":
        return _cmd_list()
    return _cmd_revoke(args.code)


if __name__ == "__main__":
    sys.exit(main())
