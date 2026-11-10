from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.accounts import utcnow
from app.avatar_uploads import ALLOWED_EXT, ALLOWED_MIME, _is_svg, _sniff_ext
from app.config import BASE_DIR, uploads_dir
from app.models import (
    Appeal,
    AppealAttachment,
    Club,
    ClubMessage,
    DirectMessage,
    ModerationEvent,
    Report,
    ReportAttachment,
    ReportCase,
    ReportCaseMessage,
    ReportCaseUser,
    User,
)

TARGET_CLUB_MESSAGE = "club_message"
TARGET_DM = "dm"
TARGET_USER = "user"
TARGET_CLUB = "club"
TARGET_IMAGE = "image"
TARGET_AUTO = "auto"

STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"
APPEAL_PENDING = "pending"
APPEAL_KEPT = "kept"
APPEAL_REMOVED = "removed"

REASON_LABELS = {
    "harassment": "Assédio ou perseguição",
    "hate": "Discurso de ódio/discriminação",
    "sexual": "Conteúdo sexual inadequado",
    "minors": "Conteúdo envolvendo menores",
    "violence": "Violência/ameaça",
    "extremism": "Extremismo",
    "spam": "Spam",
    "profile": "Perfil/clube impróprio",
    "other": "Outro",
}
REASONS = tuple(REASON_LABELS)
TARGET_LABELS = {
    TARGET_CLUB_MESSAGE: "Mensagem do clube",
    TARGET_DM: "Mensagem privada",
    TARGET_USER: "Perfil",
    TARGET_CLUB: "Clube",
    TARGET_IMAGE: "Imagem",
    TARGET_AUTO: "Detecção automática",
}
APPEAL_REASON_LABELS = {
    "context": "Conteúdo interpretado fora de contexto",
    "auto_error": "Acredito que a detecção automática errou",
    "other": "Outro",
}
APPEAL_REASONS = tuple(APPEAL_REASON_LABELS)
EXPLANATION_MIN = 30
EXPLANATION_MAX = 1000
REPORT_NOTE_MIN = 30
REPORT_NOTE_MAX = 2000
MAX_REPORT_MESSAGES = 20
MAX_REPORT_ATTACHMENTS = 5
REPORT_ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
STORED_NAME = re.compile(r"^[a-f0-9]{24}\.(jpg|jpeg|png|webp|gif)$")
SOURCE_PRIMARY = "primary"
SOURCE_MESSAGE = "message"
SOURCE_ADDED = "added"
OUTCOME_PENDING = "pending"
OUTCOME_NONE = "none"
OUTCOME_WARNED = "warned"
OUTCOME_SUSPENDED = "suspended"
OUTCOME_BANNED = "banned"
USER_OUTCOME_LABELS = {
    OUTCOME_PENDING: "Pendente",
    OUTCOME_NONE: "Sem violação",
    OUTCOME_WARNED: "Avisado",
    OUTCOME_SUSPENDED: "Suspenso",
    OUTCOME_BANNED: "Banido",
}


def _appeals_dir() -> Path:
    path = uploads_dir() / "appeals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _evidence_dir() -> Path:
    uploads = uploads_dir().resolve()
    public_static = (BASE_DIR / "app" / "static").resolve()
    try:
        uploads.relative_to(public_static)
        path = BASE_DIR / "var" / "report-evidence"
    except ValueError:
        path = uploads.parent / "report-evidence"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stored_appeal_path(filename: str | None) -> Path | None:
    name = (filename or "").strip()
    if not STORED_NAME.match(name):
        return None
    dest = _appeals_dir()
    path = (dest / name).resolve()
    if path.parent != dest.resolve() or not path.is_file():
        return None
    return path


def stored_report_evidence_path(filename: str | None) -> Path | None:
    name = (filename or "").strip()
    if not STORED_NAME.match(name):
        return None
    dest = _evidence_dir()
    path = (dest / name).resolve()
    if path.parent != dest.resolve() or not path.is_file():
        return None
    return path


async def save_appeal_image(upload: UploadFile | None) -> str | None:
    return await _save_private_image(upload, _appeals_dir(), max_bytes=2 * 1024 * 1024)


async def save_report_evidence_image(upload: UploadFile | None) -> str:
    name = await _save_private_image(upload, _evidence_dir(), max_bytes=REPORT_ATTACHMENT_MAX_BYTES)
    if not name:
        raise HTTPException(status_code=400, detail="Envie apenas imagens JPG, PNG, WEBP ou GIF de até 5 MB")
    return name


async def _save_private_image(upload: UploadFile | None, dest_dir: Path, *, max_bytes: int) -> str | None:
    if not upload or not upload.filename:
        return None
    raw_name = Path(upload.filename).name.replace("\\", "/").split("/")[-1]
    suffix = Path(raw_name).suffix.lower()
    mime = (upload.content_type or "").split(";")[0].strip().lower()
    if suffix == ".svg" or "svg" in mime:
        return None
    if suffix and suffix not in ALLOWED_EXT:
        return None
    if mime not in ALLOWED_MIME and mime not in {f"image/{ext.lstrip('.')}" for ext in ALLOWED_EXT}:
        return None
    data = await upload.read()
    if not data or len(data) > max_bytes or _is_svg(data, raw_name, mime):
        return None
    sniffed = _sniff_ext(data)
    if not sniffed:
        return None
    if suffix and suffix != sniffed and not (suffix in {".jpg", ".jpeg"} and sniffed == ".jpg"):
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(12)}{sniffed}"
    dest = dest_dir / name
    dest.write_bytes(data)
    return name


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def load_snapshot(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_id_list(values: list[str] | list[int] | str | None) -> list[int]:
    if values is None:
        return []
    if isinstance(values, (int, str)):
        values = [values]
    found: list[int] = []
    seen: set[int] = set()
    for item in values:
        text = str(item or "").replace(",", " ")
        for chunk in text.split():
            if not chunk.isdigit():
                raise HTTPException(status_code=400, detail="Identificador inválido")
            value = int(chunk)
            if value <= 0 or value in seen:
                continue
            seen.add(value)
            found.append(value)
    return found


def _snapshot_club_message(message: ClubMessage) -> dict:
    return {
        "body": message.body,
        "author_id": message.user_id,
        "author_username": message.user.username if message.user else "",
        "author_name": message.user.name if message.user else "",
        "club_id": message.club_id,
        "created_at": message.created_at.isoformat() if message.created_at else "",
        "removed_at": message.removed_at.isoformat() if message.removed_at else "",
        "kind": TARGET_CLUB_MESSAGE,
        "has_show": bool(message.show_id),
    }


def _snapshot_dm(message: DirectMessage) -> dict:
    return {
        "body": message.body,
        "author_id": message.sender_id,
        "author_username": message.sender.username if message.sender else "",
        "author_name": message.sender.name if message.sender else "",
        "recipient_id": message.recipient_id,
        "created_at": message.created_at.isoformat() if message.created_at else "",
        "kind": TARGET_DM,
    }


def _snapshot_user(person: User) -> dict:
    return {
        "name": person.name,
        "username": person.username,
        "bio": person.bio or "",
        "avatar": person.avatar_value or person.avatar,
    }


def _snapshot_club(club: Club) -> dict:
    return {
        "name": club.name,
        "description": club.description or "",
        "rules": club.rules or "",
        "cover_image": club.cover_image or "",
        "icon_image": club.icon_image or "",
    }


def resolve_target(
    db: Session,
    reporter: User,
    target_type: str,
    target_id: int,
) -> tuple[int | None, int, dict]:
    if target_type == TARGET_CLUB_MESSAGE:
        message = db.scalar(
            select(ClubMessage).options(selectinload(ClubMessage.user)).where(ClubMessage.id == target_id)
        )
        if message is None:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")
        _require_club_member(db, reporter, message.club_id)
        if message.user_id == reporter.id:
            raise HTTPException(status_code=400, detail="Você não pode denunciar o próprio conteúdo")
        return message.user_id, message.id, _snapshot_club_message(message)
    if target_type == TARGET_DM:
        message = db.scalar(
            select(DirectMessage).options(selectinload(DirectMessage.sender)).where(DirectMessage.id == target_id)
        )
        if message is None:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")
        in_thread = reporter.id in {message.sender_id, message.recipient_id}
        if not in_thread:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")
        if message.sender_id == reporter.id:
            raise HTTPException(status_code=400, detail="Você não pode denunciar o próprio conteúdo")
        return message.sender_id, message.id, _snapshot_dm(message)
    if target_type == TARGET_USER:
        person = db.get(User, target_id)
        if person is None or not person.is_active:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        if person.id == reporter.id:
            raise HTTPException(status_code=400, detail="Você não pode denunciar a si mesmo")
        return person.id, person.id, _snapshot_user(person)
    if target_type == TARGET_CLUB:
        club = db.get(Club, target_id)
        if club is None:
            raise HTTPException(status_code=404, detail="Clube não encontrado")
        return club.owner_id, club.id, _snapshot_club(club)
    if target_type == TARGET_IMAGE:
        person = db.get(User, target_id)
        if person is None or not person.is_active:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        if person.id == reporter.id:
            raise HTTPException(status_code=400, detail="Você não pode denunciar o próprio conteúdo")
        snap = _snapshot_user(person)
        snap["kind"] = "avatar"
        return person.id, person.id, snap
    raise HTTPException(status_code=400, detail="Tipo de denúncia inválido")


def _require_club_member(db: Session, reporter: User, club_id: int) -> None:
    from app.catalog import club_membership

    if club_membership(db, club_id, reporter.id) is None:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada")


def collect_club_messages(db: Session, reporter: User, message_ids: list[int]) -> list[ClubMessage]:
    ids = parse_id_list(message_ids)
    if not ids:
        return []
    if len(ids) > MAX_REPORT_MESSAGES:
        raise HTTPException(status_code=400, detail=f"Selecione no máximo {MAX_REPORT_MESSAGES} mensagens")
    rows = list(
        db.scalars(
            select(ClubMessage).options(selectinload(ClubMessage.user)).where(ClubMessage.id.in_(ids))
        )
    )
    by_id = {item.id: item for item in rows}
    collected: list[ClubMessage] = []
    clubs: set[int] = set()
    for message_id in ids:
        message = by_id.get(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")
        clubs.add(message.club_id)
        collected.append(message)
    if len(clubs) != 1:
        raise HTTPException(status_code=400, detail="As mensagens precisam ser do mesmo clube")
    _require_club_member(db, reporter, next(iter(clubs)))
    return collected


def collect_direct_messages(db: Session, reporter: User, message_ids: list[int]) -> list[DirectMessage]:
    ids = parse_id_list(message_ids)
    if not ids:
        return []
    if len(ids) > MAX_REPORT_MESSAGES:
        raise HTTPException(status_code=400, detail=f"Selecione no máximo {MAX_REPORT_MESSAGES} mensagens")
    rows = list(
        db.scalars(
            select(DirectMessage).options(selectinload(DirectMessage.sender)).where(DirectMessage.id.in_(ids))
        )
    )
    by_id = {item.id: item for item in rows}
    collected: list[DirectMessage] = []
    threads: set[tuple[int, int]] = set()
    for message_id in ids:
        message = by_id.get(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")
        if reporter.id not in {message.sender_id, message.recipient_id}:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")
        pair = tuple(sorted((message.sender_id, message.recipient_id)))
        threads.add(pair)
        collected.append(message)
    if len(threads) != 1:
        raise HTTPException(status_code=400, detail="As mensagens precisam ser da mesma conversa")
    return collected


def load_involved_users(
    db: Session,
    reporter: User,
    user_ids: list[int],
    *,
    club: Club | None = None,
) -> list[User]:
    ids = parse_id_list(user_ids)
    people: list[User] = []
    seen: set[int] = set()
    for user_id in ids:
        if user_id in seen:
            continue
        seen.add(user_id)
        if user_id == reporter.id:
            raise HTTPException(status_code=400, detail="Você não pode denunciar a si mesmo")
        if club is not None:
            people.append(locate_club_member_for_report(db, reporter, club, user_id))
            continue
        person = db.get(User, user_id)
        if person is None or not person.is_active:
            raise HTTPException(status_code=400, detail="Usuário não encontrado")
        people.append(person)
    return people


def pending_case(db: Session, target_key: str) -> ReportCase | None:
    return db.scalar(
        select(ReportCase)
        .options(selectinload(ReportCase.involved_users), selectinload(ReportCase.messages))
        .where(ReportCase.target_key == target_key, ReportCase.status == STATUS_PENDING)
    )


def _situation_key(
    target_type: str,
    target_id: int,
    *,
    user_ids: list[int],
    message_keys: list[str],
) -> str:
    users = sorted(set(user_ids))
    messages = sorted(set(message_keys))
    simple_message = target_type in {TARGET_CLUB_MESSAGE, TARGET_DM} and len(messages) <= 1
    simple_user = target_type in {TARGET_USER, TARGET_IMAGE} and not messages and len(users) <= 1
    simple_club = target_type == TARGET_CLUB and not messages and not users
    if simple_message or simple_user or simple_club or target_type == TARGET_AUTO:
        return f"{target_type}:{target_id}"
    payload = f"{target_type}:{target_id}|u:{','.join(str(item) for item in users)}|m:{','.join(messages)}"
    return "sit:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def _add_involved(db: Session, case: ReportCase, person: User, *, source: str, locked: bool) -> None:
    existing = next((row for row in case.involved_users if row.user_id == person.id), None)
    if existing:
        if locked:
            existing.locked = True
        if source == SOURCE_MESSAGE and existing.source != SOURCE_PRIMARY:
            existing.source = SOURCE_MESSAGE
        return
    row = ReportCaseUser(
        case_id=case.id,
        user_id=person.id,
        source=source,
        locked=locked,
        outcome=OUTCOME_PENDING,
        snapshot_json=_dump(_snapshot_user(person)),
        created_at=utcnow(),
    )
    db.add(row)
    case.involved_users.append(row)


def _add_message_evidence(db: Session, case: ReportCase, *, kind: str, source_id: int, author_id: int | None, snapshot: dict) -> None:
    already = any(row.kind == kind and row.source_id == source_id for row in case.messages)
    if already:
        return
    row = ReportCaseMessage(
        case_id=case.id,
        kind=kind,
        source_id=source_id,
        author_id=author_id,
        snapshot_json=_dump(snapshot),
        created_at=utcnow(),
    )
    db.add(row)
    case.messages.append(row)


def create_report(
    db: Session,
    reporter: User,
    *,
    target_type: str,
    target_id: int,
    reason: str,
    explanation: str = "",
    extra_user_ids: list[int] | None = None,
    message_ids: list[int] | None = None,
    attachment_names: list[str] | None = None,
    club_member_ids: list[int] | None = None,
    club_scope_id: int | None = None,
) -> Report:
    if target_type not in TARGET_LABELS or target_type == TARGET_AUTO:
        raise HTTPException(status_code=400, detail="Tipo de denúncia inválido")
    if reason not in REASONS:
        raise HTTPException(status_code=400, detail="Motivo inválido")
    note = (explanation or "").strip()
    if len(note) < REPORT_NOTE_MIN:
        raise HTTPException(
            status_code=400,
            detail=f"Explique o que aconteceu com pelo menos {REPORT_NOTE_MIN} caracteres.",
        )
    if len(note) > REPORT_NOTE_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"A explicação pode ter no máximo {REPORT_NOTE_MAX} caracteres.",
        )
    names = [item for item in (attachment_names or []) if item]
    if len(names) > MAX_REPORT_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"Envie no máximo {MAX_REPORT_ATTACHMENTS} prints")

    club_messages: list[ClubMessage] = []
    direct_messages: list[DirectMessage] = []
    if target_type == TARGET_CLUB_MESSAGE:
        ids = parse_id_list(message_ids) or [target_id]
        if target_id and target_id not in ids:
            ids = [target_id, *ids]
        club_messages = collect_club_messages(db, reporter, ids)
        if not any(item.user_id != reporter.id for item in club_messages):
            raise HTTPException(status_code=400, detail="Selecione ao menos uma mensagem de outra pessoa")
        target_id = next(item.id for item in club_messages if item.user_id != reporter.id)
    elif target_type == TARGET_DM:
        ids = parse_id_list(message_ids) or [target_id]
        if target_id and target_id not in ids:
            ids = [target_id, *ids]
        direct_messages = collect_direct_messages(db, reporter, ids)
        if not any(item.sender_id != reporter.id for item in direct_messages):
            raise HTTPException(status_code=400, detail="Selecione ao menos uma mensagem de outra pessoa")
        target_id = next(item.id for item in direct_messages if item.sender_id != reporter.id)

    reported_user_id, object_id, snapshot = resolve_target(db, reporter, target_type, target_id)
    club = db.get(Club, object_id) if target_type == TARGET_CLUB else None
    if target_type == TARGET_CLUB_MESSAGE and club_messages:
        club = db.get(Club, club_messages[0].club_id)

    extras: list[User] = []
    member_club = club
    if club_scope_id:
        member_club = locate_member_club(db, reporter, club_scope_id)
    if target_type == TARGET_CLUB:
        extras = load_involved_users(db, reporter, extra_user_ids or club_member_ids or [], club=member_club)
    elif extra_user_ids:
        extras = load_involved_users(
            db,
            reporter,
            extra_user_ids,
            club=member_club if member_club is not None else None,
        )
    if club_member_ids and target_type != TARGET_CLUB:
        extras.extend(load_involved_users(db, reporter, club_member_ids, club=member_club))

    authors: list[User] = []
    message_keys: list[str] = []
    for message in club_messages:
        message_keys.append(f"{TARGET_CLUB_MESSAGE}:{message.id}")
        if message.user and message.user_id != reporter.id:
            authors.append(message.user)
    for message in direct_messages:
        message_keys.append(f"{TARGET_DM}:{message.id}")
        if message.sender and message.sender_id != reporter.id:
            authors.append(message.sender)

    involved: list[tuple[User, str, bool]] = []
    seen_users: set[int] = set()

    def _queue(person: User | None, source: str, locked: bool) -> None:
        if person is None or person.id == reporter.id or person.id in seen_users:
            return
        seen_users.add(person.id)
        involved.append((person, source, locked))

    for author in authors:
        _queue(author, SOURCE_MESSAGE, True)
    if reported_user_id and target_type in {TARGET_USER, TARGET_IMAGE}:
        person = db.get(User, reported_user_id)
        _queue(person, SOURCE_PRIMARY, True)
    for extra in extras:
        _queue(extra, SOURCE_ADDED, False)

    target_key = _situation_key(
        target_type,
        object_id,
        user_ids=[person.id for person, _, _ in involved],
        message_keys=message_keys,
    )
    case = pending_case(db, target_key)
    if case is None:
        case = ReportCase(
            target_type=target_type,
            target_key=target_key,
            target_id=object_id,
            reported_user_id=(involved[0][0].id if involved else (None if target_type == TARGET_CLUB else reported_user_id)),
            reason=reason,
            status=STATUS_PENDING,
            snapshot_json=_dump(snapshot),
            report_count=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(case)
        db.flush()
    existing = db.scalar(select(Report).where(Report.case_id == case.id, Report.reporter_id == reporter.id))
    if existing:
        raise HTTPException(status_code=400, detail="Você já denunciou este conteúdo")

    for person, source, locked in involved:
        _add_involved(db, case, person, source=source, locked=locked)
    for message in club_messages:
        _add_message_evidence(
            db,
            case,
            kind=TARGET_CLUB_MESSAGE,
            source_id=message.id,
            author_id=message.user_id,
            snapshot=_snapshot_club_message(message),
        )
    for message in direct_messages:
        _add_message_evidence(
            db,
            case,
            kind=TARGET_DM,
            source_id=message.id,
            author_id=message.sender_id,
            snapshot=_snapshot_dm(message),
        )
    if not club_messages and not direct_messages and target_type in {TARGET_CLUB_MESSAGE, TARGET_DM}:
        _add_message_evidence(
            db,
            case,
            kind=target_type,
            source_id=object_id,
            author_id=reported_user_id,
            snapshot=snapshot,
        )
        if reported_user_id:
            person = db.get(User, reported_user_id)
            if person:
                _add_involved(db, case, person, source=SOURCE_MESSAGE, locked=True)

    row = Report(
        case_id=case.id,
        reporter_id=reporter.id,
        reason=reason,
        explanation=note,
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    for filename in names:
        db.add(
            ReportAttachment(
                report_id=row.id,
                case_id=case.id,
                filename=filename,
                created_at=utcnow(),
            )
        )
    case.report_count = int(case.report_count or 0) + 1
    case.updated_at = utcnow()
    if involved and not case.reported_user_id:
        case.reported_user_id = involved[0][0].id
    db.commit()
    db.refresh(row)
    return row


def preview_report(
    db: Session,
    reporter: User,
    *,
    target_type: str,
    target_id: int,
    extra_user_ids: list[int] | None = None,
    message_ids: list[int] | None = None,
    club_scope_id: int | None = None,
) -> dict:
    if target_type not in TARGET_LABELS or target_type == TARGET_AUTO:
        raise HTTPException(status_code=400, detail="Tipo de denúncia inválido")
    club_messages: list[ClubMessage] = []
    direct_messages: list[DirectMessage] = []
    primary_id = target_id
    if target_type == TARGET_CLUB_MESSAGE:
        ids = parse_id_list(message_ids) or [target_id]
        if target_id and target_id not in ids:
            ids = [target_id, *ids]
        club_messages = collect_club_messages(db, reporter, ids)
        primary_id = next((item.id for item in club_messages if item.user_id != reporter.id), ids[0])
    elif target_type == TARGET_DM:
        ids = parse_id_list(message_ids) or [target_id]
        if target_id and target_id not in ids:
            ids = [target_id, *ids]
        direct_messages = collect_direct_messages(db, reporter, ids)
        primary_id = next((item.id for item in direct_messages if item.sender_id != reporter.id), ids[0])
    reported_user_id, object_id, snapshot = resolve_target(db, reporter, target_type, primary_id)
    club = db.get(Club, object_id) if target_type == TARGET_CLUB else None
    if club_messages:
        club = db.get(Club, club_messages[0].club_id)
    member_club = club
    if club_scope_id:
        member_club = locate_member_club(db, reporter, club_scope_id)
    extras = load_involved_users(db, reporter, extra_user_ids or [], club=member_club)
    people: list[dict] = []
    seen: set[int] = set()

    def _add(person: User | None, locked: bool) -> None:
        if person is None or person.id == reporter.id or person.id in seen:
            return
        seen.add(person.id)
        people.append({"user": person, "locked": locked})

    for message in club_messages:
        _add(message.user, True)
    for message in direct_messages:
        _add(message.sender, True)
    if reported_user_id and target_type in {TARGET_USER, TARGET_IMAGE}:
        _add(db.get(User, reported_user_id), True)
    for extra in extras:
        _add(extra, False)
    message_snaps = [_snapshot_club_message(item) for item in club_messages] + [_snapshot_dm(item) for item in direct_messages]
    message_snaps.sort(key=lambda item: (item.get("created_at") or "", item.get("author_id") or 0))
    return {
        "target_type": target_type,
        "target_id": object_id,
        "target_label": TARGET_LABELS[target_type],
        "snapshot": snapshot,
        "people": people,
        "messages": message_snaps,
        "club": club,
        "club_scope_id": member_club.id if member_club is not None else None,
        "message_ids": [item.id for item in club_messages] or [item.id for item in direct_messages],
        "user_ids": [item["user"].id for item in people],
        "locked_ids": [item["user"].id for item in people if item["locked"]],
    }


OWN_STATUS_LABELS = {
    STATUS_PENDING: "Em análise",
    STATUS_RESOLVED: "Encerrada",
}
PENALTY_ACTION_LABELS = {
    "warn": "Aviso",
    "suspend": "Suspensão",
    "ban": "Banimento",
}


def list_own_reports(db: Session, reporter_id: int) -> list[Report]:
    return list(
        db.scalars(
            select(Report)
            .options(
                selectinload(Report.case).selectinload(ReportCase.involved_users),
                selectinload(Report.case).selectinload(ReportCase.messages),
                selectinload(Report.attachments),
            )
            .where(Report.reporter_id == reporter_id)
            .order_by(Report.created_at.desc(), Report.id.desc())
        )
    )


def own_report_counts(report: Report) -> dict[str, int]:
    case = report.case
    users = len(case.involved_users) if case and case.involved_users else (1 if case and case.reported_user_id else 0)
    messages = len(case.messages) if case and case.messages else (
        1 if case and case.target_type in {TARGET_CLUB_MESSAGE, TARGET_DM} else 0
    )
    return {
        "users": users,
        "messages": messages,
        "attachments": len(report.attachments or []),
    }


def locate_user_for_report(db: Session, reporter: User, username: str) -> User:
    from app.friends import find_active_user

    person = find_active_user(db, (username or "").lstrip("@"))
    if person is None:
        raise HTTPException(status_code=400, detail="Usuário não encontrado")
    if person.id == reporter.id:
        raise HTTPException(status_code=400, detail="Você não pode denunciar a si mesmo")
    return person


def locate_member_club(db: Session, reporter: User, club_id: int) -> Club:
    from app.catalog import club_membership

    club = db.get(Club, club_id)
    if club is None:
        raise HTTPException(status_code=400, detail="Clube não encontrado")
    if club_membership(db, club.id, reporter.id) is None:
        raise HTTPException(status_code=400, detail="Você só pode denunciar clubes de que participa por esta central")
    return club


def locate_club_member_for_report(db: Session, reporter: User, club: Club, member_user_id: int) -> User:
    from app.catalog import club_membership

    if member_user_id == reporter.id:
        raise HTTPException(status_code=400, detail="Você não pode denunciar a si mesmo")
    member = club_membership(db, club.id, member_user_id)
    if member is None:
        raise HTTPException(status_code=400, detail="Esta pessoa não é membro deste clube")
    person = db.get(User, member_user_id)
    if person is None or not person.is_active:
        raise HTTPException(status_code=400, detail="Usuário não encontrado")
    return person


def _case_options():
    return (
        selectinload(ReportCase.reported_user),
        selectinload(ReportCase.reports).selectinload(Report.reporter),
        selectinload(ReportCase.reports).selectinload(Report.attachments),
        selectinload(ReportCase.involved_users).selectinload(ReportCaseUser.user),
        selectinload(ReportCase.messages),
    )


def list_cases(db: Session, *, resolved: bool) -> list[ReportCase]:
    status = STATUS_RESOLVED if resolved else STATUS_PENDING
    return list(
        db.scalars(
            select(ReportCase)
            .options(*_case_options())
            .where(ReportCase.status == status)
            .order_by(ReportCase.updated_at.desc(), ReportCase.id.desc())
        )
    )


def get_case(db: Session, case_id: int) -> ReportCase:
    case = db.scalar(select(ReportCase).options(*_case_options()).where(ReportCase.id == case_id))
    if case is None:
        raise HTTPException(status_code=404, detail="Denúncia não encontrada")
    return case


def case_people(case: ReportCase) -> list[ReportCaseUser | User]:
    if case.involved_users:
        return list(case.involved_users)
    if case.reported_user:
        return [case.reported_user]
    return []


def chronological_message_snapshots(case: ReportCase) -> list[dict]:
    rows: list[dict] = []
    for item in case.messages or []:
        snap = load_snapshot(item.snapshot_json)
        snap["kind"] = item.kind
        snap["source_id"] = item.source_id
        rows.append(snap)
    if not rows:
        snap = load_snapshot(case.snapshot_json)
        if snap.get("body") and case.target_type in {TARGET_CLUB_MESSAGE, TARGET_DM}:
            snap["kind"] = case.target_type
            rows.append(snap)
    rows.sort(key=lambda item: (item.get("created_at") or "", item.get("source_id") or 0))
    return rows


def elevate_automatic_event(db: Session, user: User, event: ModerationEvent) -> ReportCase:
    key = f"auto:{event.id}"
    existing = pending_case(db, key)
    if existing:
        event.case_id = existing.id
        return existing
    case = ReportCase(
        target_type=TARGET_AUTO,
        target_key=key,
        target_id=event.id,
        reported_user_id=user.id,
        reason=event.category if event.category in REASONS else "other",
        status=STATUS_PENDING,
        snapshot_json=_dump(
            {
                "origin": event.origin,
                "category": event.category,
                "action": event.action,
                "evidence": event.evidence,
                "automatic": True,
            }
        ),
        report_count=0,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(case)
    db.flush()
    _add_involved(db, case, user, source=SOURCE_PRIMARY, locked=True)
    event.case_id = case.id
    return case


def resolve_case(db: Session, case: ReportCase, admin: User, resolution: str) -> None:
    case.status = STATUS_RESOLVED
    case.resolution = resolution
    case.resolved_at = utcnow()
    case.resolved_by_id = admin.id
    case.updated_at = utcnow()


def remove_reported_content(db: Session, case: ReportCase) -> None:
    message_rows = list(case.messages or [])
    if not message_rows and case.target_type in {TARGET_CLUB_MESSAGE, TARGET_DM} and case.target_id:
        message_rows = [
            ReportCaseMessage(kind=case.target_type, source_id=case.target_id, snapshot_json=case.snapshot_json)
        ]
    for item in message_rows:
        if item.kind == TARGET_CLUB_MESSAGE and item.source_id:
            message = db.get(ClubMessage, item.source_id)
            if message and message.removed_at is None:
                message.removed_at = utcnow()
        elif item.kind == TARGET_DM and item.source_id:
            message = db.get(DirectMessage, item.source_id)
            if message is not None:
                message.body = ""


def case_user_row(case: ReportCase, user_id: int) -> ReportCaseUser | None:
    return next((row for row in (case.involved_users or []) if row.user_id == user_id), None)


def get_report_attachment(db: Session, attachment_id: int) -> ReportAttachment:
    item = db.scalar(
        select(ReportAttachment)
        .options(selectinload(ReportAttachment.report))
        .where(ReportAttachment.id == attachment_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")
    return item


def can_view_report_attachment(user: User, item: ReportAttachment) -> bool:
    if user.is_site_admin:
        return True
    return bool(item.report and item.report.reporter_id == user.id)


def create_appeal(
    db: Session,
    user: User,
    event: ModerationEvent,
    *,
    reason: str,
    explanation: str,
    filename: str | None = None,
) -> Appeal:
    if event.user_id != user.id:
        raise HTTPException(status_code=404, detail="Penalidade não encontrada")
    if event.reversed_at is not None:
        raise HTTPException(status_code=400, detail="Esta penalidade já foi revertida")
    if event.action not in {"warn", "suspend", "ban"}:
        raise HTTPException(status_code=400, detail="Esta ocorrência não pode ser contestada")
    if reason not in APPEAL_REASONS:
        raise HTTPException(status_code=400, detail="Motivo inválido")
    text = (explanation or "").strip()
    if len(text) < EXPLANATION_MIN or len(text) > EXPLANATION_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"A explicação precisa ter entre {EXPLANATION_MIN} e {EXPLANATION_MAX} caracteres.",
        )
    already = db.scalar(select(Appeal.id).where(Appeal.event_id == event.id))
    if already:
        raise HTTPException(status_code=400, detail="Você já solicitou revisão desta penalidade")
    appeal = Appeal(
        event_id=event.id,
        user_id=user.id,
        reason=reason,
        explanation=text,
        status=APPEAL_PENDING,
        created_at=utcnow(),
    )
    db.add(appeal)
    db.flush()
    if filename:
        db.add(AppealAttachment(appeal_id=appeal.id, filename=filename, created_at=utcnow()))
    db.commit()
    db.refresh(appeal)
    return appeal


def list_appeals(db: Session, *, pending: bool) -> list[Appeal]:
    query = (
        select(Appeal)
        .options(selectinload(Appeal.user), selectinload(Appeal.event), selectinload(Appeal.attachments))
        .order_by(Appeal.created_at.desc(), Appeal.id.desc())
    )
    if pending:
        query = query.where(Appeal.status == APPEAL_PENDING)
    else:
        query = query.where(Appeal.status != APPEAL_PENDING)
    return list(db.scalars(query))


def get_appeal(db: Session, appeal_id: int) -> Appeal:
    appeal = db.scalar(
        select(Appeal)
        .options(selectinload(Appeal.user), selectinload(Appeal.event), selectinload(Appeal.attachments))
        .where(Appeal.id == appeal_id)
    )
    if appeal is None:
        raise HTTPException(status_code=404, detail="Contestação não encontrada")
    return appeal
