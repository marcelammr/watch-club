from __future__ import annotations

from app.models import ClubMember

ROLE_ADMIN = "admin"
ROLE_SUPPORT = "support"
ROLE_MEMBER = "member"
ROLES = {ROLE_ADMIN, ROLE_SUPPORT, ROLE_MEMBER}
MAX_ADMINS = 3
MAX_SUPPORT = 7
ROLE_LABELS = {
    ROLE_ADMIN: "ADM",
    ROLE_SUPPORT: "SUB",
    ROLE_MEMBER: "Membro",
}

PERM_TAG = "manage_tag"
PERM_JOINS = "manage_join_requests"
PERM_TITLES = "manage_titles"
SUPPORT_PERMS = (PERM_TAG, PERM_JOINS, PERM_TITLES)
SUPPORT_PERM_LABELS = {
    PERM_TAG: "Gerenciar tag do clube",
    PERM_JOINS: "Gerenciar solicitações de entrada",
    PERM_TITLES: "Gerenciar títulos",
}


def member_role(member: ClubMember | None) -> str:
    role = (getattr(member, "role", None) or ROLE_MEMBER).strip().lower()
    return role if role in ROLES else ROLE_MEMBER


def parse_support_perms(raw: str | None) -> list[str]:
    seen: list[str] = []
    for part in (raw or "").split(","):
        key = part.strip()
        if key in SUPPORT_PERMS and key not in seen:
            seen.append(key)
    return seen


def dump_support_perms(keys) -> str:
    wanted = set(keys)
    return ",".join(key for key in SUPPORT_PERMS if key in wanted)


def perms_of(member: ClubMember | None) -> set[str]:
    role = member_role(member)
    if role == ROLE_ADMIN:
        return set(SUPPORT_PERMS)
    if role == ROLE_SUPPORT:
        return set(parse_support_perms(getattr(member, "support_perms", None)))
    return set()


def can(member: ClubMember | None, perm: str) -> bool:
    if perm not in SUPPORT_PERMS:
        return member_role(member) == ROLE_ADMIN
    return perm in perms_of(member)


def set_member_role(member: ClubMember, role: str) -> None:
    if role not in ROLES:
        role = ROLE_MEMBER
    member.role = role
    if role != ROLE_SUPPORT:
        member.support_perms = ""


def roles_by_user(members: list[ClubMember]) -> dict[int, str]:
    return {item.user_id: member_role(item) for item in members}
