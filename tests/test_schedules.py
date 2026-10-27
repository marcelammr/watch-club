from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.accounts import utcnow
from app.db import SessionLocal, engine
from app.main import app
from app.models import Club, ClubMember, ClubSchedule, ClubShow, User
from app.roles import PERM_SCHEDULES, PERM_TAG, ROLE_SUPPORT, can
from app.schedules import (
    format_episode_compact,
    format_episode_line,
    format_schedule_when,
    format_week_line,
    wall_to_utc,
    week_range_utc,
)
from tests.test_app import register_active

client = TestClient(app)


def _create_club(http: TestClient, name: str) -> tuple[int, str]:
    created = http.post("/clubs", data={"name": name}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        code = db.get(Club, club_id).join_code
    finally:
        db.close()
    return club_id, code


def _user_id_by_key(key: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(User.id).where(User.username_key == key))
    finally:
        db.close()


def _add_title(http: TestClient, club_id: int, name: str) -> int:
    added = http.post(
        f"/clubs/{club_id}/titulos",
        data={"name": name, "kind": "serie"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    db = SessionLocal()
    try:
        return db.scalar(select(ClubShow.show_id).where(ClubShow.club_id == club_id).order_by(ClubShow.id.desc()))
    finally:
        db.close()


def test_schedule_schema_and_wall_clock():
    inspector = inspect(engine)
    assert "club_schedules" in inspector.get_table_names()
    cols = {column["name"] for column in inspector.get_columns("club_schedules")}
    assert {
        "club_id",
        "show_id",
        "starts_at",
        "season_number",
        "episode_number",
        "notes",
        "created_by_id",
        "created_at",
    } <= cols
    starts = wall_to_utc("2026-11-02", "19:00")
    assert starts.strftime("%Y-%m-%d %H:%M") == "2026-11-02 22:00"
    assert format_schedule_when(starts) == "Seg · 19:00"
    assert format_episode_line(2, 3) == "Temporada 2 · Episódio 3"
    assert format_episode_line(None, 2) == "Episódio 2"
    assert format_episode_compact(2, 3) == "T2 E3"
    admin = ClubMember(role="admin", support_perms="")
    support = ClubMember(role=ROLE_SUPPORT, support_perms=PERM_SCHEDULES)
    member = ClubMember(role="member", support_perms=PERM_SCHEDULES)
    assert can(admin, PERM_SCHEDULES) is True
    assert can(support, PERM_SCHEDULES) is True
    assert can(member, PERM_SCHEDULES) is False


def test_admin_creates_schedule_and_member_can_view():
    owner = TestClient(app)
    register_active(owner, "agenda_adm", "agenda.adm@example.com")
    club_id, code = _create_club(owner, "Clube Agenda")
    show_id = _add_title(owner, club_id, "Black Mirror")
    created = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={
            "show_id": str(show_id),
            "date": "2027-03-15",
            "time": "19:00",
            "season_number": "2",
            "episode_number": "3",
            "notes": "Sala da Ana",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == f"/clubs/{club_id}?aba=agendamentos"

    member = TestClient(app)
    register_active(member, "agenda_mem", "agenda.mem@example.com")
    member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    page = member.get(f"/clubs/{club_id}?aba=agendamentos")
    assert page.status_code == 200
    assert "Próximos agendamentos" in page.text
    assert "Black Mirror" in page.text
    assert "Temporada 2 · Episódio 3" in page.text
    assert "Sala da Ana" in page.text
    assert "+ Novo agendamento" not in page.text
    assert "Cancelar agendamento" not in page.text
    assert 'id="add-schedule-dialog"' not in page.text
    assert "watch-search" not in page.text

    blocked = member.post(
        f"/clubs/{club_id}/agendamentos",
        data={"show_id": str(show_id), "date": "2027-03-16", "time": "21:00"},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    db = SessionLocal()
    try:
        assert db.scalar(select(ClubSchedule).where(ClubSchedule.club_id == club_id)).notes == "Sala da Ana"
        assert db.scalar(select(ClubSchedule.id).where(ClubSchedule.notes == "")) is None
    finally:
        db.close()


def test_support_needs_manage_schedules_to_create():
    owner = TestClient(app)
    register_active(owner, "agenda_owner", "agenda.owner@example.com")
    club_id, code = _create_club(owner, "Clube SUB Agenda")
    show_id = _add_title(owner, club_id, "Sherlock")
    helper = TestClient(app)
    register_active(helper, "agenda_sub", "agenda.sub@example.com")
    helper.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    helper_id = _user_id_by_key("agenda_sub")

    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": "support", "support_perm": [PERM_TAG]},
        follow_redirects=False,
    )
    denied = helper.post(
        f"/clubs/{club_id}/agendamentos",
        data={"show_id": str(show_id), "date": "2027-04-02", "time": "21:00"},
        follow_redirects=False,
    )
    assert denied.status_code == 303
    db = SessionLocal()
    try:
        assert db.scalar(select(ClubSchedule.id).where(ClubSchedule.club_id == club_id)) is None
    finally:
        db.close()

    owner.post(
        f"/clubs/{club_id}/membros/{helper_id}/papel",
        data={"role": "support", "support_perm": [PERM_SCHEDULES]},
        follow_redirects=False,
    )
    granted = helper.post(
        f"/clubs/{club_id}/agendamentos",
        data={
            "show_id": str(show_id),
            "date": "2027-04-02",
            "time": "21:00",
            "episode_number": "2",
        },
        follow_redirects=False,
    )
    assert granted.status_code == 303
    page = helper.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "+ Novo agendamento" in page.text
    assert "Cancelar agendamento" in page.text
    assert "Sherlock" in page.text
    assert "Episódio 2" in page.text
    settings = owner.get(f"/clubs/{club_id}/config")
    assert "Gerenciar agendamentos" in settings.text


def test_schedule_requires_club_show_and_hides_past():
    owner = TestClient(app)
    register_active(owner, "agenda_past", "agenda.past@example.com")
    club_id, _code = _create_club(owner, "Clube Passado")
    show_id = _add_title(owner, club_id, "Dark")
    missing = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={"show_id": "999999", "date": "2027-05-01", "time": "20:00"},
        follow_redirects=False,
    )
    assert missing.status_code == 303
    assert "error=" in missing.headers["location"]
    db = SessionLocal()
    try:
        user_id = db.scalar(select(User.id).where(User.username_key == "agenda_past"))
        db.add(
            ClubSchedule(
                club_id=club_id,
                show_id=show_id,
                starts_at=utcnow() - timedelta(days=2),
                notes="já foi",
                created_by_id=user_id,
            )
        )
        db.commit()
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "já foi" not in page.text
    assert "Nenhum agendamento próximo." in page.text
    assistindo = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "Próximos agendamentos" not in assistindo.text
    assert "Programação da semana" not in assistindo.text
    assert "watch-search" in assistindo.text


def test_admin_cancels_schedule_and_member_cannot():
    owner = TestClient(app)
    register_active(owner, "agenda_cancel_adm", "agenda.cancel.adm@example.com")
    club_id, code = _create_club(owner, "Clube Cancelar")
    show_id = _add_title(owner, club_id, "Black Mirror")
    owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={"show_id": str(show_id), "date": "2027-06-01", "time": "19:00"},
        follow_redirects=False,
    )
    db = SessionLocal()
    try:
        schedule_id = db.scalar(select(ClubSchedule.id).where(ClubSchedule.club_id == club_id))
    finally:
        db.close()
    member = TestClient(app)
    register_active(member, "agenda_cancel_mem", "agenda.cancel.mem@example.com")
    member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    blocked = member.post(
        f"/clubs/{club_id}/agendamentos/{schedule_id}/cancelar",
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(ClubSchedule, schedule_id) is not None
    finally:
        db.close()
    cancelled = owner.post(
        f"/clubs/{club_id}/agendamentos/{schedule_id}/cancelar",
        follow_redirects=False,
    )
    assert cancelled.status_code == 303
    assert cancelled.headers["location"] == f"/clubs/{club_id}?aba=agendamentos"
    db = SessionLocal()
    try:
        assert db.get(ClubSchedule, schedule_id) is None
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "Nenhum agendamento próximo." in page.text
    assert "schedule-card" not in page.text


def test_week_preview_shows_only_current_week():
    owner = TestClient(app)
    register_active(owner, "agenda_week", "agenda.week@example.com")
    club_id, _code = _create_club(owner, "Clube Semana")
    this_show = _add_title(owner, club_id, "Black Mirror")
    next_show = _add_title(owner, club_id, "Sherlock")
    now = utcnow()
    _start, week_end = week_range_utc(now)
    this_week_at = now + timedelta(hours=1)
    if this_week_at >= week_end:
        this_week_at = now
    next_week_at = week_end + timedelta(hours=12)
    db = SessionLocal()
    try:
        user_id = db.scalar(select(User.id).where(User.username_key == "agenda_week"))
        this_item = ClubSchedule(
            club_id=club_id,
            show_id=this_show,
            starts_at=this_week_at,
            season_number=2,
            episode_number=3,
            created_by_id=user_id,
        )
        db.add(this_item)
        db.add(
            ClubSchedule(
                club_id=club_id,
                show_id=next_show,
                starts_at=next_week_at,
                season_number=1,
                episode_number=2,
                created_by_id=user_id,
            )
        )
        db.commit()
        db.refresh(this_item)
        this_item.show
        expected = format_week_line(this_item)
    finally:
        db.close()
    assistindo = owner.get(f"/clubs/{club_id}?aba=assistindo")
    assert "Programação da semana" in assistindo.text
    assert expected in assistindo.text
    assert "Ver agenda completa" in assistindo.text
    assert f"/clubs/{club_id}?aba=agendamentos" in assistindo.text
    assert "Sherlock" not in assistindo.text.split("watch-tabs", 1)[0]
    assert "Cancelar agendamento" not in assistindo.text
    chat = owner.get(f"/clubs/{club_id}?aba=chat")
    assert "Programação da semana" not in chat.text
    agenda = owner.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "Black Mirror" in agenda.text
    assert "Sherlock" in agenda.text
