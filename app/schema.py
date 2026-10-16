from sqlalchemy import inspect, text

from app.avatars import DEFAULT_AVATAR
from app.db import engine
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
    if "club_shows" in inspector.get_table_names():
        link_cols = {column["name"] for column in inspector.get_columns("club_shows")}
        if "watch_status" not in link_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE club_shows ADD COLUMN watch_status VARCHAR(20) DEFAULT 'watching'"))
