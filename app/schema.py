from sqlalchemy import inspect, text

from app.avatars import DEFAULT_AVATAR
from app.db import engine
from app.usernames import normalize_username


def migrate_schema() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
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
    inspector = inspect(engine)
    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_username_key" not in indexes:
        with engine.begin() as connection:
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_key ON users (username_key)"))
