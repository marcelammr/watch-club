from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.accounts import utcnow
from app.db import SessionLocal, engine
from app.main import app
from app.models import Club, ClubMember, ClubSchedule, ClubScheduleSeries, ClubShow, User
from app.roles import PERM_SCHEDULES, PERM_TAG, ROLE_SUPPORT, can
from app.schedules import (
    MAX_OCCURRENCES,
    format_episode_compact,
    format_episode_line,
    format_recurrence_line,
    format_schedule_when,
    format_week_line,
    meeting_title,
    local_today,
    occurrence_dates,
    utc_to_local,
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
    assert "club_schedule_series" in inspector.get_table_names()
    cols = {column["name"] for column in inspector.get_columns("club_schedules")}
    assert {
        "club_id",
        "series_id",
        "show_id",
        "starts_at",
        "season_number",
        "episode_number",
        "title",
        "notes",
        "created_by_id",
        "created_at",
    } <= cols
    show_col = next(column for column in inspector.get_columns("club_schedules") if column["name"] == "show_id")
    assert show_col["nullable"] is True
    series_cols = {column["name"] for column in inspector.get_columns("club_schedule_series")}
    assert {"club_id", "interval", "weekday", "time_local", "until_date", "ended_at", "title"} <= series_cols
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
    assert "Cancelar encontro" in page.text
    assert "Definir programa" in page.text or "Alterar programa" in page.text
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


def test_personal_agenda_aggregates_clubs_hides_past_and_filters():
    guest = client.get("/agenda", follow_redirects=False)
    assert guest.status_code == 303
    assert guest.headers["location"] == "/login"

    owner = TestClient(app)
    register_active(owner, "planner_adm", "planner.adm@example.com")
    club_a, _code_a = _create_club(owner, "Clube Planner A")
    club_b, code_b = _create_club(owner, "Clube Planner B")
    show_a = _add_title(owner, club_a, "Black Mirror")
    show_b = _add_title(owner, club_b, "Sherlock")
    owner.post(
        f"/clubs/{club_a}/agendamentos",
        data={"show_id": str(show_a), "date": "2027-08-10", "time": "20:00", "notes": "sala A"},
        follow_redirects=False,
    )
    owner.post(
        f"/clubs/{club_b}/agendamentos",
        data={"show_id": str(show_b), "date": "2027-08-11", "time": "21:00"},
        follow_redirects=False,
    )
    db = SessionLocal()
    try:
        user_id = db.scalar(select(User.id).where(User.username_key == "planner_adm"))
        db.add(
            ClubSchedule(
                club_id=club_a,
                show_id=show_a,
                starts_at=utcnow() - timedelta(days=3),
                notes="já passou",
                created_by_id=user_id,
            )
        )
        db.commit()
    finally:
        db.close()

    page = owner.get("/agenda")
    assert page.status_code == 200
    assert "Hoje" in page.text
    assert "Próximos encontros" in page.text
    assert "planner-week" in page.text
    assert page.text.count('role="listitem"') == 7
    assert "planner-month" not in page.text
    assert "vista=mes" not in page.text
    assert "Depois desta semana" not in page.text
    assert "já passou" not in page.text.split("planner-upcoming", 1)[-1]
    assert "+ Novo agendamento" not in page.text
    assert "Cancelar agendamento" not in page.text
    assert "Todos os clubes" in page.text
    assert "Black Mirror" in page.text
    assert "Sherlock" in page.text
    assert "Clube Planner A" in page.text
    assert "Clube Planner B" in page.text
    assert "Semana anterior" in page.text
    assert "Próxima semana" in page.text

    week_page = owner.get("/agenda", params={"semana": "2027-08-10"})
    assert "9–15 ago 2027" in week_page.text
    assert "20:00" in week_page.text
    assert "21:00" in week_page.text
    assert "Black Mirror" in week_page.text
    assert "Sherlock" in week_page.text
    assert "semana=2027-08-02" in week_page.text
    assert "semana=2027-08-16" in week_page.text

    later_week = owner.get("/agenda", params={"semana": "2027-08-16"})
    assert "16–22 ago 2027" in later_week.text
    assert later_week.text.split("planner-upcoming", 1)[0].count("20:00") == 0

    today_page = owner.get("/agenda")
    assert 'href="/agenda"' in today_page.text or 'href="/agenda?' in today_page.text

    only_a = owner.get("/agenda", params={"clube": str(club_a)})
    assert "Black Mirror" in only_a.text
    assert "Sherlock" not in only_a.text

    outsider = TestClient(app)
    register_active(outsider, "planner_out", "planner.out@example.com")
    empty = outsider.get("/agenda")
    assert empty.status_code == 200
    assert "Nenhum encontro marcado por enquanto." in empty.text
    assert "Black Mirror" not in empty.text

    member = TestClient(app)
    register_active(member, "planner_mem", "planner.mem@example.com")
    member.post("/clubs/join", data={"join_code": code_b, "next": "/"}, follow_redirects=False)
    seen = member.get("/agenda")
    assert "Sherlock" in seen.text
    assert "Black Mirror" not in seen.text
    assert "+ Novo agendamento" not in seen.text
    assert "Todos os clubes" not in seen.text


def test_personal_agenda_week_strip_includes_past_keeps_upcoming_future():
    owner = TestClient(app)
    register_active(owner, "week_full", "week.full@example.com")
    club_a, code_a = _create_club(owner, "Clube Faixa A")
    club_b, _code_b = _create_club(owner, "Clube Faixa B")
    show_a = _add_title(owner, club_a, "Dark")
    show_b = _add_title(owner, club_b, "Severance")
    user_id = _user_id_by_key("week_full")
    db = SessionLocal()
    try:
        db.add(
            ClubSchedule(
                club_id=club_a,
                show_id=show_a,
                title="Noite antiga",
                starts_at=wall_to_utc("2026-10-28", "20:00"),
                notes="passado-a",
                created_by_id=user_id,
            )
        )
        db.add(
            ClubSchedule(
                club_id=club_b,
                show_id=show_b,
                title="Sessão velha",
                starts_at=wall_to_utc("2026-10-29", "21:00"),
                notes="passado-b",
                created_by_id=user_id,
            )
        )
        db.add(
            ClubSchedule(
                club_id=club_a,
                show_id=show_a,
                title="Semana passada",
                starts_at=wall_to_utc("2026-10-21", "19:00"),
                notes="semana-anterior",
                created_by_id=user_id,
            )
        )
        db.add(
            ClubSchedule(
                club_id=club_a,
                show_id=show_a,
                title="Madrugada",
                starts_at=wall_to_utc("2026-11-01", "23:00"),
                notes="fuso-domingo",
                created_by_id=user_id,
            )
        )
        db.commit()
    finally:
        db.close()
    future = owner.post(
        f"/clubs/{club_a}/agendamentos",
        data={"show_id": str(show_a), "title": "Noite nova", "date": "2027-08-10", "time": "20:00"},
        follow_redirects=False,
    )
    assert future.status_code == 303

    week = owner.get("/agenda", params={"semana": "2026-10-28"})
    assert "26 out — 1 nov 2026" in week.text
    strip, upcoming = week.text.split("planner-upcoming", 1)
    assert "Noite antiga" in strip
    assert "Sessão velha" in strip
    assert "20:00" in strip
    assert "21:00" in strip
    assert "is-past" in strip
    assert 'aria-label="Qua 28"' in strip
    assert "Noite antiga" not in upcoming
    assert "Sessão velha" not in upcoming
    assert "passado-a" not in upcoming
    assert "Noite nova" in upcoming
    assert "Semana passada" not in strip
    assert "23:00" in strip
    assert "fuso-domingo" in strip
    local_late = utc_to_local(wall_to_utc("2026-11-01", "23:00"))
    assert local_late.strftime("%Y-%m-%d") == "2026-11-01"
    assert local_late.strftime("%H:%M") == "23:00"

    prev_week = owner.get("/agenda", params={"semana": "2026-10-19"})
    prev_strip, prev_upcoming = prev_week.text.split("planner-upcoming", 1)
    assert "19–25 out 2026" in prev_week.text
    assert "Semana passada" in prev_strip
    assert "19:00" in prev_strip
    assert "Semana passada" not in prev_upcoming
    assert "Noite antiga" not in prev_strip

    next_week = owner.get("/agenda", params={"semana": "2027-08-10"})
    next_strip, next_upcoming = next_week.text.split("planner-upcoming", 1)
    assert "9–15 ago 2027" in next_week.text
    assert "Noite nova" in next_strip
    assert "20:00" in next_strip
    assert "Noite nova" in next_upcoming
    assert "Noite antiga" not in next_strip

    only_a = owner.get("/agenda", params={"semana": "2026-10-28", "clube": str(club_a)})
    only_strip, _only_upcoming = only_a.text.split("planner-upcoming", 1)
    assert "Noite antiga" in only_strip
    assert "Sessão velha" not in only_strip
    assert "passado-b" not in only_a.text

    member = TestClient(app)
    register_active(member, "week_mem", "week.mem@example.com")
    member.post("/clubs/join", data={"join_code": code_a, "next": "/"}, follow_redirects=False)
    member_week = member.get("/agenda", params={"semana": "2026-10-28"})
    assert "Noite antiga" in member_week.text
    assert "Sessão velha" not in member_week.text

    outsider = TestClient(app)
    register_active(outsider, "week_out", "week.out@example.com")
    empty = outsider.get("/agenda", params={"semana": "2026-10-28"})
    assert "Noite antiga" not in empty.text
    assert "Sessão velha" not in empty.text
    assert "Nenhum encontro marcado por enquanto." in empty.text


def _club_schedules(club_id: int) -> list[ClubSchedule]:
    db = SessionLocal()
    try:
        return list(
            db.scalars(
                select(ClubSchedule)
                .where(ClubSchedule.club_id == club_id)
                .order_by(ClubSchedule.starts_at.asc(), ClubSchedule.id.asc())
            ).all()
        )
    finally:
        db.close()


def test_single_meeting_without_program():
    owner = TestClient(app)
    register_active(owner, "meet_empty", "meet.empty@example.com")
    club_id, _code = _create_club(owner, "Clube Sem Programa")
    created = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={"date": "2027-03-15", "time": "20:00"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    items = _club_schedules(club_id)
    assert len(items) == 1
    assert items[0].show_id is None
    assert items[0].series_id is None
    page = owner.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "Programa pendente" in page.text
    agenda = owner.get("/agenda")
    assert "Programa pendente" in agenda.text


def test_weekly_and_biweekly_recurrence_until_and_timezone():
    starts = wall_to_utc("2026-11-03", "20:00")
    assert utc_to_local(starts).weekday() == 1
    assert utc_to_local(starts).strftime("%H:%M") == "20:00"
    next_week = wall_to_utc("2026-11-10", "20:00")
    assert utc_to_local(next_week).weekday() == 1
    late = wall_to_utc("2026-11-01", "23:00")
    assert utc_to_local(late).weekday() == 6
    assert utc_to_local(late).strftime("%Y-%m-%d") == "2026-11-01"

    owner = TestClient(app)
    register_active(owner, "meet_week", "meet.week@example.com")
    club_id, _code = _create_club(owner, "Clube Terças")
    weekly = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={
            "date": "2027-11-02",
            "time": "20:00",
            "repeat": "weekly",
            "until": "2027-11-23",
        },
        follow_redirects=False,
    )
    assert weekly.status_code == 303
    items = _club_schedules(club_id)
    assert len(items) == 4
    locals_ = [utc_to_local(item.starts_at) for item in items]
    assert [item.date().isoformat() for item in locals_] == [
        "2027-11-02",
        "2027-11-09",
        "2027-11-16",
        "2027-11-23",
    ]
    assert all(item.weekday() == 1 for item in locals_)
    assert all(item.strftime("%H:%M") == "20:00" for item in locals_)
    assert all(item.show_id is None for item in items)
    assert items[0].series_id is not None
    assert len({item.series_id for item in items}) == 1
    page = owner.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "Programa pendente" in page.text
    assert "Toda terça-feira às 20:00" in page.text
    agenda = owner.get("/agenda")
    assert agenda.text.count('role="listitem"') == 7
    assert agenda.text.count("20:00") >= 4
    assert agenda.text.count("Programa pendente") >= 4
    assert "Toda terça-feira às 20:00" in agenda.text
    week_page = owner.get("/agenda", params={"semana": "2027-11-02"})
    assert "1–7 nov 2027" in week_page.text
    assert "20:00" in week_page.text

    other = TestClient(app)
    register_active(other, "meet_bi", "meet.bi@example.com")
    club_b, _code_b = _create_club(other, "Clube Quinzenal")
    biweekly = other.post(
        f"/clubs/{club_b}/agendamentos",
        data={
            "date": "2027-11-02",
            "time": "18:00",
            "repeat": "biweekly",
            "until": "2027-11-30",
        },
        follow_redirects=False,
    )
    assert biweekly.status_code == 303
    bi_items = _club_schedules(club_b)
    assert [utc_to_local(item.starts_at).date().isoformat() for item in bi_items] == [
        "2027-11-02",
        "2027-11-16",
        "2027-11-30",
    ]
    db = SessionLocal()
    try:
        series = db.get(ClubScheduleSeries, bi_items[0].series_id)
        assert series.interval == "biweekly"
        assert "A cada 2 semanas" in format_recurrence_line(series)
    finally:
        db.close()


def test_program_per_occurrence_and_permissions():
    owner = TestClient(app)
    register_active(owner, "meet_prog", "meet.prog@example.com")
    club_id, code = _create_club(owner, "Clube Programas")
    show_a = _add_title(owner, club_id, "Interestelar")
    show_b = _add_title(owner, club_id, "Stranger Things")
    owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={
            "show_id": str(show_a),
            "date": "2027-11-02",
            "time": "20:00",
            "repeat": "weekly",
            "until": "2027-11-16",
        },
        follow_redirects=False,
    )
    items = _club_schedules(club_id)
    assert items[0].show_id == show_a
    assert items[1].show_id is None
    assert items[2].show_id is None
    second_id, third_id = items[1].id, items[2].id
    owner.post(
        f"/clubs/{club_id}/agendamentos/{second_id}/programa",
        data={"show_id": str(show_b), "season_number": "1", "episode_number": "2"},
        follow_redirects=False,
    )
    owner.post(
        f"/clubs/{club_id}/agendamentos/{second_id}/programa",
        data={"show_id": str(show_a)},
        follow_redirects=False,
    )
    updated = _club_schedules(club_id)
    assert updated[0].show_id == show_a
    assert updated[1].show_id == show_a
    assert updated[1].season_number is None
    assert updated[2].show_id is None
    page = owner.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "Interestelar" in page.text
    assert "Programa pendente" in page.text
    assert "Alterar programa" in page.text

    member = TestClient(app)
    register_active(member, "meet_prog_mem", "meet.prog.mem@example.com")
    member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    blocked = member.post(
        f"/clubs/{club_id}/agendamentos/{third_id}/programa",
        data={"show_id": str(show_b)},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert _club_schedules(club_id)[2].show_id is None
    member_page = member.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "Definir programa" not in member_page.text
    assert "Alterar programa" not in member_page.text
    outsider = TestClient(app)
    register_active(outsider, "meet_prog_out", "meet.prog.out@example.com")
    empty = outsider.get("/agenda")
    assert "Interestelar" not in empty.text


def test_cancel_one_occurrence_and_end_series_keeps_history():
    owner = TestClient(app)
    register_active(owner, "meet_end", "meet.end@example.com")
    club_id, code = _create_club(owner, "Clube Encerrar")
    today = local_today()
    start = today - timedelta(days=14)
    until = today + timedelta(days=21)
    created = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={
            "date": start.isoformat(),
            "time": "20:00",
            "repeat": "weekly",
            "until": until.isoformat(),
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    items = _club_schedules(club_id)
    assert len(items) >= 4
    future = [item for item in items if item.starts_at >= utcnow()]
    past = [item for item in items if item.starts_at < utcnow()]
    assert past
    assert len(future) >= 2
    cancel_id = future[0].id
    keep_id = future[1].id
    member = TestClient(app)
    register_active(member, "meet_end_mem", "meet.end.mem@example.com")
    member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    blocked = member.post(
        f"/clubs/{club_id}/agendamentos/{cancel_id}/cancelar",
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(ClubSchedule, cancel_id) is not None
    finally:
        db.close()
    owner.post(
        f"/clubs/{club_id}/agendamentos/{cancel_id}/cancelar",
        follow_redirects=False,
    )
    remaining = {item.id for item in _club_schedules(club_id)}
    assert cancel_id not in remaining
    assert keep_id in remaining
    for item in past:
        assert item.id in remaining
    series_id = items[0].series_id
    owner.post(
        f"/clubs/{club_id}/agendamentos/series/{series_id}/encerrar",
        follow_redirects=False,
    )
    after = _club_schedules(club_id)
    assert all(item.starts_at < utcnow() for item in after)
    assert {item.id for item in past} <= {item.id for item in after}
    db = SessionLocal()
    try:
        assert db.get(ClubScheduleSeries, series_id).ended_at is not None
        assert db.get(ClubSchedule, keep_id) is None
    finally:
        db.close()


def test_edit_when_only_this_occurrence_and_validations():
    owner = TestClient(app)
    register_active(owner, "meet_edit", "meet.edit@example.com")
    club_id, _code = _create_club(owner, "Clube Editar")
    owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={
            "date": "2027-11-02",
            "time": "20:00",
            "repeat": "weekly",
            "until": "2027-11-16",
            "notes": "sala",
        },
        follow_redirects=False,
    )
    items = _club_schedules(club_id)
    first_id, second_id = items[0].id, items[1].id
    owner.post(
        f"/clubs/{club_id}/agendamentos/{first_id}",
        data={"date": "2027-11-03", "time": "21:30", "notes": "outro lugar"},
        follow_redirects=False,
    )
    changed = _club_schedules(club_id)
    by_id = {item.id: item for item in changed}
    assert utc_to_local(by_id[first_id].starts_at).strftime("%Y-%m-%d %H:%M") == "2027-11-03 21:30"
    assert by_id[first_id].notes == "outro lugar"
    assert utc_to_local(by_id[second_id].starts_at).strftime("%Y-%m-%d %H:%M") == "2027-11-09 20:00"
    assert by_id[second_id].notes == "sala"

    missing_until = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={"date": "2027-12-01", "time": "20:00", "repeat": "weekly"},
        follow_redirects=False,
    )
    assert missing_until.status_code == 303
    assert "error=" in missing_until.headers["location"]
    before = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={"date": "2027-12-10", "time": "20:00", "repeat": "weekly", "until": "2027-12-01"},
        follow_redirects=False,
    )
    assert "error=" in before.headers["location"]
    too_long = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={"date": "2027-01-05", "time": "20:00", "repeat": "weekly", "until": "2028-01-10"},
        follow_redirects=False,
    )
    assert "error=" in too_long.headers["location"]
    too_many = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={"date": "2027-01-05", "time": "20:00", "repeat": "weekly", "until": "2028-01-04"},
        follow_redirects=False,
    )
    assert "error=" in too_many.headers["location"]
    assert len(occurrence_dates(date(2027, 1, 5), date(2027, 12, 28), 7)) == 52
    assert MAX_OCCURRENCES == 52


def test_legacy_schedule_rows_remain_one_off():
    owner = TestClient(app)
    register_active(owner, "meet_legacy", "meet.legacy@example.com")
    club_id, _code = _create_club(owner, "Clube Legado")
    show_id = _add_title(owner, club_id, "Dark")
    db = SessionLocal()
    try:
        user_id = db.scalar(select(User.id).where(User.username_key == "meet_legacy"))
        db.add(
            ClubSchedule(
                club_id=club_id,
                show_id=show_id,
                starts_at=wall_to_utc("2027-05-01", "20:00"),
                notes="legado",
                created_by_id=user_id,
            )
        )
        db.commit()
    finally:
        db.close()
    items = _club_schedules(club_id)
    assert len(items) == 1
    assert items[0].series_id is None
    assert items[0].show_id == show_id
    page = owner.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "Dark" in page.text
    assert "legado" in page.text
    assert "↻" not in page.text


def test_optional_meeting_title_on_series_and_one_off():
    owner = TestClient(app)
    register_active(owner, "meet_title", "meet.title@example.com")
    club_id, _code = _create_club(owner, "Clube Título")
    created = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={
            "title": "Noite de Cinema",
            "date": "2027-11-02",
            "time": "20:00",
            "repeat": "weekly",
            "until": "2027-11-16",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    db = SessionLocal()
    try:
        rows = list(
            db.scalars(
                select(ClubSchedule)
                .where(ClubSchedule.club_id == club_id)
                .order_by(ClubSchedule.starts_at.asc())
            ).all()
        )
        assert len(rows) == 3
        assert {row.title for row in rows} == {""}
        series = db.get(ClubScheduleSeries, rows[0].series_id)
        assert series.title == "Noite de Cinema"
        for row in rows:
            row.series
            assert meeting_title(row) == "Noite de Cinema"
            assert row.show_id is None
    finally:
        db.close()
    page = owner.get(f"/clubs/{club_id}?aba=agendamentos")
    assert page.text.count("Noite de Cinema") >= 3
    assert "Programa pendente" in page.text
    assert "None" not in page.text
    agenda = owner.get("/agenda", params={"semana": "2027-11-01"})
    assert "Noite de Cinema" in agenda.text
    assert "Programa pendente" in agenda.text

    one = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={"title": "Sessão única", "date": "2027-12-01", "time": "19:00"},
        follow_redirects=False,
    )
    assert one.status_code == 303
    untitled = owner.post(
        f"/clubs/{club_id}/agendamentos",
        data={"date": "2027-12-08", "time": "21:00"},
        follow_redirects=False,
    )
    assert untitled.status_code == 303
    db = SessionLocal()
    try:
        solo = db.scalar(
            select(ClubSchedule).where(
                ClubSchedule.club_id == club_id, ClubSchedule.title == "Sessão única"
            )
        )
        blank = db.scalar(
            select(ClubSchedule)
            .where(ClubSchedule.club_id == club_id, ClubSchedule.series_id.is_(None), ClubSchedule.title == "")
            .order_by(ClubSchedule.id.desc())
        )
        assert solo.series_id is None
        assert meeting_title(solo) == "Sessão única"
        assert meeting_title(blank) == "Encontro"
    finally:
        db.close()
    later = owner.get(f"/clubs/{club_id}?aba=agendamentos")
    assert "Sessão única" in later.text
    assert "Encontro" in later.text
