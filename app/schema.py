from sqlalchemy import inspect, text

from app.avatars import DEFAULT_AVATAR
from app.db import engine
from app.discovery import CATALOG
from app.usernames import normalize_username


def migrate_schema() -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "users" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    alters = []
    if "username" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN username VARCHAR(80)")
    if "username_key" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN username_key VARCHAR(80)")
    if "is_active" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 0")
    if "avatar" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN avatar VARCHAR(40) DEFAULT 'popcorn'")
    if "avatar_type" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN avatar_type VARCHAR(16) DEFAULT 'illustrated'")
    if "avatar_provider" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN avatar_provider VARCHAR(32) DEFAULT 'watchclub'")
    if "avatar_value" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN avatar_value VARCHAR(120) DEFAULT 'popcorn'")
    if "pending_email" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN pending_email VARCHAR(255)")
    if "bio" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN bio VARCHAR(150) DEFAULT ''")
    if "google_id" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN google_id VARCHAR(64)")
    if "facebook_id" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN facebook_id VARCHAR(64)")
    if "last_seen" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN last_seen DATETIME")
    if "presence" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN presence VARCHAR(12) DEFAULT 'offline'")
    if "username_changed_at" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN username_changed_at DATETIME")
    if "presence_pref" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN presence_pref VARCHAR(12) DEFAULT 'auto'")
        alters.append("UPDATE users SET presence_pref = 'auto' WHERE presence_pref IS NULL")
    if "displayed_club_id" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN displayed_club_id INTEGER")
    if "enter_sends" not in columns:
        alters.append("ALTER TABLE users ADD COLUMN enter_sends BOOLEAN DEFAULT 0")
    with engine.begin() as connection:
        for statement in alters:
            connection.execute(text(statement))
        rows = connection.execute(text("SELECT id, name, username, username_key, is_active, avatar FROM users")).mappings()
        used: set[str] = set()
        for row in rows:
            key = row["username_key"] or normalize_username(row["username"] or row["name"] or f"user{row['id']}")
            if not key:
                key = f"user{row['id']}"
            original = key
            n = 2
            while key in used:
                key = f"{original}{n}"[:30]
                n += 1
            used.add(key)
            username = row["username"] or key
            avatar = row["avatar"] or DEFAULT_AVATAR
            is_active = 1 if row["username_key"] is None else int(bool(row["is_active"]))
            connection.execute(
                text(
                    "UPDATE users SET username = :username, username_key = :key, "
                    "is_active = :active, avatar = :avatar WHERE id = :id"
                ),
                {"username": username, "key": key, "active": is_active, "avatar": avatar, "id": row["id"]},
            )
        connection.execute(
            text(
                "UPDATE users SET username_changed_at = created_at "
                "WHERE username_changed_at IS NULL AND created_at IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE users SET avatar_type = 'illustrated' "
                "WHERE avatar_type IS NULL OR avatar_type = ''"
            )
        )
        connection.execute(
            text(
                "UPDATE users SET avatar_provider = 'watchclub' "
                "WHERE avatar_type = 'illustrated' AND (avatar_provider IS NULL OR avatar_provider = '')"
            )
        )
        connection.execute(
            text(
                "UPDATE users SET avatar_value = avatar "
                "WHERE avatar_type = 'illustrated' "
                "AND avatar_provider = 'watchclub' "
                "AND avatar_value = 'popcorn' "
                "AND avatar IS NOT NULL AND avatar != '' AND avatar != 'popcorn'"
            )
        )
        connection.execute(
            text(
                "UPDATE users SET avatar_value = COALESCE(NULLIF(avatar_value, ''), avatar, 'popcorn') "
                "WHERE avatar_value IS NULL OR avatar_value = ''"
            )
        )
    inspector = inspect(engine)
    if "clubs" in inspector.get_table_names():
        club_cols = {column["name"] for column in inspector.get_columns("clubs")}
        club_alters = []
        if "is_closed" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN is_closed BOOLEAN DEFAULT 0")
        if "description" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN description TEXT DEFAULT ''")
        if "rules" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN rules TEXT DEFAULT ''")
        if "cover_color" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN cover_color VARCHAR(7) DEFAULT '#3a2348'")
        if "cover_image" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN cover_image VARCHAR(120)")
        if "icon_image" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN icon_image VARCHAR(120)")
        if "tag_slug" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_slug VARCHAR(4) DEFAULT ''")
        if "tag_emoji" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_emoji VARCHAR(16) DEFAULT ''")
        if "tag_color" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_color VARCHAR(20) DEFAULT ''")
        if "tag_bg_intensity" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_bg_intensity INTEGER DEFAULT 18")
        if "tag_border_intensity" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_border_intensity INTEGER DEFAULT 55")
        if "tag_emoji_position" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_emoji_position VARCHAR(8) DEFAULT 'start'")
        if "tag_color_mode" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_color_mode VARCHAR(8) DEFAULT 'solid'")
        if "tag_color_1" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_color_1 VARCHAR(7) DEFAULT '#B892FF'")
        if "tag_color_2" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_color_2 VARCHAR(7)")
        if "tag_gradient_direction" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN tag_gradient_direction VARCHAR(16)")
        if "admin_name_color" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN admin_name_color VARCHAR(7) DEFAULT '#B892FF'")
        if "sub_name_color" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN sub_name_color VARCHAR(7) DEFAULT '#6C63FF'")
        if "member_limit" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN member_limit INTEGER")
        if "pinned_message_id" not in club_cols:
            club_alters.append("ALTER TABLE clubs ADD COLUMN pinned_message_id INTEGER")
        if club_alters:
            with engine.begin() as connection:
                for statement in club_alters:
                    connection.execute(text(statement))
        inspector.clear_cache()
        club_cols = {column["name"] for column in inspector.get_columns("clubs")}
        with engine.begin() as connection:
            if "tag_bg_intensity" in club_cols:
                connection.execute(text("UPDATE clubs SET tag_bg_intensity = 18 WHERE tag_bg_intensity IS NULL"))
            if "tag_border_intensity" in club_cols:
                connection.execute(text("UPDATE clubs SET tag_border_intensity = 55 WHERE tag_border_intensity IS NULL"))
            if "tag_emoji_position" in club_cols:
                connection.execute(
                    text(
                        "UPDATE clubs SET tag_emoji_position = 'start' "
                        "WHERE tag_emoji_position IS NULL OR tag_emoji_position = ''"
                    )
                )
            if "tag_color_mode" in club_cols:
                connection.execute(
                    text("UPDATE clubs SET tag_color_mode = 'solid' WHERE tag_color_mode IS NULL OR tag_color_mode = ''")
                )
            if "tag_color_1" in club_cols:
                token_hex = {
                    "lavender": "#B892FF",
                    "violet": "#6C63FF",
                    "pink": "#FF5D8F",
                    "blue": "#6EA8FF",
                    "green": "#3DDC84",
                    "orange": "#FF9F5B",
                    "cream": "#F7F0FF",
                    "night": "#C4B8D9",
                }
                for token, hex_value in token_hex.items():
                    connection.execute(
                        text(
                            "UPDATE clubs SET tag_color_1 = :hex "
                            "WHERE lower(tag_color) = :token "
                            "AND (tag_color_1 IS NULL OR tag_color_1 = '' OR tag_color_1 = '#B892FF')"
                        ),
                        {"hex": hex_value, "token": token},
                    )
                connection.execute(
                    text(
                        "UPDATE clubs SET tag_color_1 = '#B892FF' "
                        "WHERE tag_color_1 IS NULL OR tag_color_1 = ''"
                    )
                )
            if "cover_color" in club_cols:
                connection.execute(text("UPDATE clubs SET cover_color = upper(cover_color) WHERE cover_color IS NOT NULL"))
            if "admin_name_color" in club_cols:
                connection.execute(
                    text("UPDATE clubs SET admin_name_color = '#B892FF' WHERE admin_name_color IS NULL OR admin_name_color = ''")
                )
            if "sub_name_color" in club_cols:
                connection.execute(
                    text("UPDATE clubs SET sub_name_color = '#6C63FF' WHERE sub_name_color IS NULL OR sub_name_color = ''")
                )
    inspector = inspect(engine)
    if "notifications" in inspector.get_table_names():
        notice_cols = {column["name"] for column in inspector.get_columns("notifications")}
        if "related_id" not in notice_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE notifications ADD COLUMN related_id INTEGER"))

    member_cols = set()
    if "club_members" in inspector.get_table_names():
        member_cols = {column["name"] for column in inspector.get_columns("club_members")}
        with engine.begin() as connection:
            if "role" not in member_cols:
                connection.execute(text("ALTER TABLE club_members ADD COLUMN role VARCHAR(16) DEFAULT 'member'"))
            if "support_perms" not in member_cols:
                connection.execute(text("ALTER TABLE club_members ADD COLUMN support_perms TEXT DEFAULT ''"))
            if "is_admin" in member_cols:
                connection.execute(
                    text(
                        "UPDATE club_members SET role = 'admin' WHERE is_admin = 1 "
                        "AND (role IS NULL OR role = '' OR role = 'member')"
                    )
                )
                connection.execute(text("ALTER TABLE club_members DROP COLUMN is_admin"))
            elif "role" not in member_cols:
                connection.execute(
                    text(
                        "UPDATE club_members SET role = 'admin' WHERE user_id IN "
                        "(SELECT owner_id FROM clubs WHERE clubs.id = club_members.club_id)"
                    )
                )
            connection.execute(
                text("UPDATE club_members SET role = 'member' WHERE role IS NULL OR role = ''")
            )
            connection.execute(
                text("UPDATE club_members SET support_perms = '' WHERE support_perms IS NULL")
            )
    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_username_key" not in indexes:
        with engine.begin() as connection:
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_key ON users (username_key)"))
    with engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_lower ON users (lower(email))"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_facebook_id ON users (facebook_id)"))
    if "shows" in inspector.get_table_names():
        show_cols = {column["name"] for column in inspector.get_columns("shows")}
        if "kind" not in show_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE shows ADD COLUMN kind VARCHAR(20) DEFAULT 'serie'"))
        if "genres" not in show_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE shows ADD COLUMN genres TEXT"))
        if "backdrop_url" not in show_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE shows ADD COLUMN backdrop_url VARCHAR(500)"))
        if "tmdb_id" not in show_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE shows ADD COLUMN tmdb_id INTEGER"))
        if "imdb_id" not in show_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE shows ADD COLUMN imdb_id VARCHAR(20)"))
        inspector.clear_cache()
        show_indexes = {index["name"] for index in inspector.get_indexes("shows")}
        with engine.begin() as connection:
            if "ix_shows_tmdb_id" not in show_indexes:
                connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_shows_tmdb_id ON shows (tmdb_id)"))
            if "ix_shows_imdb_id" not in show_indexes:
                connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_shows_imdb_id ON shows (imdb_id)"))
    if "episodes" in inspector.get_table_names():
        episode_cols = {column["name"] for column in inspector.get_columns("episodes")}
        if "image_url" not in episode_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE episodes ADD COLUMN image_url VARCHAR(500)"))
    if "club_shows" in inspector.get_table_names():
        link_cols = {column["name"] for column in inspector.get_columns("club_shows")}
        if "watch_status" not in link_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE club_shows ADD COLUMN watch_status VARCHAR(20) DEFAULT 'watching'"))
    _migrate_club_schedules()
    _backfill_series_show_ids()
    _seed_catalog_categories()
    _ensure_user_show_favorites()
    _ensure_club_message_show_id()
    _ensure_direct_message_read_at()


def _migrate_club_schedules() -> None:
    inspector = inspect(engine)
    if "club_schedules" not in inspector.get_table_names():
        return
    cols = {column["name"] for column in inspector.get_columns("club_schedules")}
    with engine.begin() as connection:
        if "series_id" not in cols:
            connection.execute(text("ALTER TABLE club_schedules ADD COLUMN series_id INTEGER"))
        if "title" not in cols:
            connection.execute(text("ALTER TABLE club_schedules ADD COLUMN title VARCHAR(80) DEFAULT ''"))
    inspector.clear_cache()
    if "club_schedule_series" in inspector.get_table_names():
        series_cols = {column["name"] for column in inspector.get_columns("club_schedule_series")}
        if "title" not in series_cols:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE club_schedule_series ADD COLUMN title VARCHAR(80) DEFAULT ''")
                )
    with engine.begin() as connection:
        info = connection.execute(text("PRAGMA table_info(club_schedules)")).fetchall()
        show_info = next((row for row in info if row[1] == "show_id"), None)
        if show_info is None or int(show_info[3] or 0) == 0:
            return
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.execute(
            text(
                """
                CREATE TABLE club_schedules_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    club_id INTEGER NOT NULL,
                    series_id INTEGER,
                    show_id INTEGER,
                    title VARCHAR(80) NOT NULL DEFAULT '',
                    starts_at DATETIME NOT NULL,
                    season_number INTEGER,
                    episode_number INTEGER,
                    notes TEXT NOT NULL DEFAULT '',
                    created_by_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(club_id) REFERENCES clubs (id),
                    FOREIGN KEY(series_id) REFERENCES club_schedule_series (id),
                    FOREIGN KEY(show_id) REFERENCES shows (id),
                    FOREIGN KEY(created_by_id) REFERENCES users (id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO club_schedules_new (
                    id, club_id, series_id, show_id, title, starts_at, season_number,
                    episode_number, notes, created_by_id, created_at
                )
                SELECT
                    id, club_id, series_id, show_id, COALESCE(title, ''), starts_at, season_number,
                    episode_number, notes, created_by_id, created_at
                FROM club_schedules
                """
            )
        )
        connection.execute(text("DROP TABLE club_schedules"))
        connection.execute(text("ALTER TABLE club_schedules_new RENAME TO club_schedules"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_club_schedules_club_id ON club_schedules (club_id)"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_club_schedules_club_starts ON club_schedules (club_id, starts_at)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_club_schedules_series_id ON club_schedules (series_id)")
        )
        connection.execute(text("PRAGMA foreign_keys=ON"))


def _backfill_series_show_ids() -> None:
    inspector = inspect(engine)
    if "club_schedules" not in inspector.get_table_names():
        return
    cols = {column["name"] for column in inspector.get_columns("club_schedules")}
    if "series_id" not in cols or "show_id" not in cols:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE club_schedules
                SET show_id = (
                    SELECT s2.show_id
                    FROM club_schedules AS s2
                    WHERE s2.series_id = club_schedules.series_id
                      AND s2.show_id IS NOT NULL
                    ORDER BY s2.starts_at ASC, s2.id ASC
                    LIMIT 1
                )
                WHERE series_id IS NOT NULL
                  AND show_id IS NULL
                  AND EXISTS (
                    SELECT 1
                    FROM club_schedules AS s2
                    WHERE s2.series_id = club_schedules.series_id
                      AND s2.show_id IS NOT NULL
                  )
                """
            )
        )


def _ensure_direct_message_read_at() -> None:
    inspector = inspect(engine)
    if "direct_messages" not in inspector.get_table_names():
        return
    cols = {column["name"] for column in inspector.get_columns("direct_messages")}
    if "read_at" in cols:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE direct_messages ADD COLUMN read_at DATETIME"))


def _ensure_club_message_show_id() -> None:
    inspector = inspect(engine)
    if "club_messages" not in inspector.get_table_names():
        return
    cols = {column["name"] for column in inspector.get_columns("club_messages")}
    if "show_id" in cols:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE club_messages ADD COLUMN show_id INTEGER"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_club_messages_show_id ON club_messages (show_id)")
        )


def _ensure_user_show_favorites() -> None:
    inspector = inspect(engine)
    if "user_show_favorites" in inspector.get_table_names():
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE user_show_favorites (
                    id INTEGER NOT NULL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    show_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users (id),
                    FOREIGN KEY(show_id) REFERENCES shows (id),
                    UNIQUE (user_id, show_id)
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_show_favorites_user_id "
                "ON user_show_favorites (user_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_show_favorites_show_id "
                "ON user_show_favorites (show_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_show_favorites_user_created "
                "ON user_show_favorites (user_id, created_at)"
            )
        )


def _seed_catalog_categories() -> None:
    inspector = inspect(engine)
    if "catalog_categories" not in inspector.get_table_names():
        return
    with engine.begin() as connection:
        for slug, name, kind, sort_order in CATALOG:
            connection.execute(
                text(
                    "INSERT INTO catalog_categories (slug, name, kind, sort_order, is_active) "
                    "VALUES (:slug, :name, :kind, :sort_order, 1) "
                    "ON CONFLICT(slug) DO UPDATE SET "
                    "name = excluded.name, kind = excluded.kind, sort_order = excluded.sort_order"
                ),
                {"slug": slug, "name": name, "kind": kind, "sort_order": sort_order},
            )

