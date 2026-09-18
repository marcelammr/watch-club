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
        if club_alters:
            with engine.begin() as connection:
                for statement in club_alters:
                    connection.execute(text(statement))
    member_cols = set()
    if "club_members" in inspector.get_table_names():
        member_cols = {column["name"] for column in inspector.get_columns("club_members")}
        if "is_admin" not in member_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE club_members ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
                connection.execute(
                    text(
                        "UPDATE club_members SET is_admin = 1 WHERE user_id IN "
                        "(SELECT owner_id FROM clubs WHERE clubs.id = club_members.club_id)"
                    )
                )
    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_username_key" not in indexes:
        with engine.begin() as connection:
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_key ON users (username_key)"))
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
