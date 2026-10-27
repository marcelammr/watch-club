from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app.catalog import WATCHED, WATCHING
from app.db import SessionLocal, engine
from app.main import app
from app.models import Club, ClubEpisodeWatch, ClubShow, ClubWatchRound, Episode, Show, User
from app.progress import (
    get_or_create_open_round,
    mark_episode_watched,
    next_episode,
    unmark_episode,
    watched_episode_ids,
)
from tests.test_app import register_active

client = TestClient(app)


def _create_club(http: TestClient, name: str) -> int:
    created = http.post("/clubs", data={"name": name}, follow_redirects=False)
    return int(created.headers["location"].rsplit("/", 1)[-1])


def _user_id_by_key(key: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(User.id).where(User.username_key == key))
    finally:
        db.close()


def _seed_title(
    club_id: int,
    user_id: int,
    tvmaze_id: int,
    name: str,
    episodes: list[tuple[int, int | None, str]],
    watch_status: str = WATCHING,
) -> tuple[int, list[int]]:
    db = SessionLocal()
    try:
        show = Show(tvmaze_id=tvmaze_id, name=name, kind="serie")
        db.add(show)
        db.flush()
        db.add(
            ClubShow(
                club_id=club_id,
                show_id=show.id,
                added_by_id=user_id,
                watch_status=watch_status,
            )
        )
        episode_ids = []
        for index, (season_number, number, title) in enumerate(episodes, start=1):
            episode = Episode(
                show_id=show.id,
                tvmaze_id=tvmaze_id * 100 + index,
                season_number=season_number,
                number=number,
                name=title,
            )
            db.add(episode)
            db.flush()
            episode_ids.append(episode.id)
        db.commit()
        return show.id, episode_ids
    finally:
        db.close()


def test_progress_schema_is_club_scoped():
    inspector = inspect(engine)
    assert "club_watch_rounds" in inspector.get_table_names()
    assert "club_episode_watches" in inspector.get_table_names()
    round_cols = {column["name"] for column in inspector.get_columns("club_watch_rounds")}
    watch_cols = {column["name"] for column in inspector.get_columns("club_episode_watches")}
    assert {"club_id", "show_id", "number", "started_at", "completed_at"} <= round_cols
    assert {"round_id", "episode_id", "watched_at", "marked_by_id"} <= watch_cols
    episode_cols = {column["name"] for column in inspector.get_columns("episodes")}
    assert "round_id" not in episode_cols
    assert "watched_at" not in episode_cols


def test_get_or_create_round_one_is_idempotent():
    owner = TestClient(app)
    register_active(owner, "prog_round", "prog.round@example.com")
    club_id = _create_club(owner, "Sala Round")
    user_id = _user_id_by_key("prog_round")
    show_id, _ = _seed_title(club_id, user_id, 81001, "Obra Round", [(1, 1, "Pilot")])

    db = SessionLocal()
    try:
        first = get_or_create_open_round(db, club_id, show_id)
        second = get_or_create_open_round(db, club_id, show_id)
        assert first.id == second.id
        assert first.number == 1
        assert first.completed_at is None
        count = db.scalar(
            select(func.count()).select_from(ClubWatchRound).where(
                ClubWatchRound.club_id == club_id,
                ClubWatchRound.show_id == show_id,
            )
        )
        assert count == 1
    finally:
        db.close()


def test_mark_unmark_and_idempotent_watch():
    owner = TestClient(app)
    register_active(owner, "prog_mark", "prog.mark@example.com")
    club_id = _create_club(owner, "Sala Mark")
    user_id = _user_id_by_key("prog_mark")
    show_id, episode_ids = _seed_title(club_id, user_id, 81002, "Obra Mark", [(1, 1, "Pilot")])
    episode_id = episode_ids[0]

    db = SessionLocal()
    try:
        first = mark_episode_watched(db, club_id, show_id, episode_id, marked_by_id=user_id)
        second = mark_episode_watched(db, club_id, show_id, episode_id, marked_by_id=user_id)
        assert first.id == second.id
        assert first.marked_by_id == user_id
        assert watched_episode_ids(db, club_id, show_id) == {episode_id}
        watches = db.scalars(
            select(ClubEpisodeWatch).where(ClubEpisodeWatch.round_id == first.round_id)
        ).all()
        assert len(watches) == 1
        unmark_episode(db, club_id, show_id, episode_id)
        assert watched_episode_ids(db, club_id, show_id) == set()
        remaining = db.scalar(
            select(func.count()).select_from(ClubEpisodeWatch).where(ClubEpisodeWatch.round_id == first.round_id)
        )
        assert remaining == 0
    finally:
        db.close()


def test_progress_is_isolated_by_club_and_show():
    owner = TestClient(app)
    register_active(owner, "prog_iso_a", "prog.iso.a@example.com")
    club_a = _create_club(owner, "Sala Iso A")
    user_a = _user_id_by_key("prog_iso_a")
    other = TestClient(app)
    register_active(other, "prog_iso_b", "prog.iso.b@example.com")
    club_b = _create_club(other, "Sala Iso B")
    user_b = _user_id_by_key("prog_iso_b")

    show_id, episode_ids = _seed_title(club_a, user_a, 81003, "Obra Compartilhada", [(1, 1, "Pilot"), (1, 2, "Next")])
    db = SessionLocal()
    try:
        db.add(ClubShow(club_id=club_b, show_id=show_id, added_by_id=user_b, watch_status=WATCHING))
        other_show = Show(tvmaze_id=81004, name="Outra Obra", kind="serie")
        db.add(other_show)
        db.flush()
        other_show_id = other_show.id
        db.add(ClubShow(club_id=club_a, show_id=other_show_id, added_by_id=user_a, watch_status=WATCHING))
        extra = Episode(
            show_id=other_show_id,
            tvmaze_id=8100401,
            season_number=1,
            number=1,
            name="Outro Pilot",
        )
        db.add(extra)
        db.commit()
        extra_id = extra.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        mark_episode_watched(db, club_a, show_id, episode_ids[0], marked_by_id=user_a)
        assert watched_episode_ids(db, club_a, show_id) == {episode_ids[0]}
        assert watched_episode_ids(db, club_b, show_id) == set()
        assert watched_episode_ids(db, club_a, other_show_id) == set()
        assert next_episode(db, club_b, show_id).id == episode_ids[0]
        assert next_episode(db, club_a, other_show_id).id == extra_id
        assert next_episode(db, club_a, show_id).id == episode_ids[1]
    finally:
        db.close()


def test_next_episode_order_skips_specials_and_returns_none_when_done():
    owner = TestClient(app)
    register_active(owner, "prog_next", "prog.next@example.com")
    club_id = _create_club(owner, "Sala Next")
    user_id = _user_id_by_key("prog_next")
    show_id, episode_ids = _seed_title(
        club_id,
        user_id,
        81005,
        "Obra Next",
        [
            (2, 1, "T2E1"),
            (0, 1, "Special"),
            (1, None, "Unaired"),
            (1, 2, "T1E2"),
            (1, 1, "T1E1"),
        ],
    )
    t2e1, special, unaired, t1e2, t1e1 = episode_ids

    db = SessionLocal()
    try:
        first = next_episode(db, club_id, show_id)
        assert first.id == t1e1
        mark_episode_watched(db, club_id, show_id, t1e1)
        assert next_episode(db, club_id, show_id).id == t1e2
        mark_episode_watched(db, club_id, show_id, t1e2)
        assert next_episode(db, club_id, show_id).id == t2e1
        mark_episode_watched(db, club_id, show_id, t2e1)
        assert next_episode(db, club_id, show_id) is None
        assert special not in watched_episode_ids(db, club_id, show_id)
        assert unaired not in watched_episode_ids(db, club_id, show_id)
        mark_episode_watched(db, club_id, show_id, special)
        assert next_episode(db, club_id, show_id) is None
    finally:
        db.close()


def test_existing_watch_status_stays_untouched():
    owner = TestClient(app)
    register_active(owner, "prog_status", "prog.status@example.com")
    club_id = _create_club(owner, "Sala Status")
    user_id = _user_id_by_key("prog_status")
    show_id, episode_ids = _seed_title(
        club_id,
        user_id,
        81006,
        "Obra Finalizada",
        [(1, 1, "Pilot")],
        watch_status=WATCHED,
    )
    db = SessionLocal()
    try:
        get_or_create_open_round(db, club_id, show_id)
        mark_episode_watched(db, club_id, show_id, episode_ids[0], marked_by_id=user_id)
        link = db.scalar(select(ClubShow).where(ClubShow.club_id == club_id, ClubShow.show_id == show_id))
        assert link.watch_status == WATCHED
        assert db.scalar(select(func.count()).select_from(ClubWatchRound).where(ClubWatchRound.show_id == show_id)) == 1
        assert watched_episode_ids(db, club_id, show_id) == {episode_ids[0]}
        club = db.get(Club, club_id)
        assert club is not None
    finally:
        db.close()
