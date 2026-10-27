---
name: watch-club-backend
description: Guides Watch Club backend work so FastAPI routes, SQLAlchemy models, SQLite sessions, auth, and club permissions stay clear, safe, and consistent with existing modules. Use when changing app/*.py, models, schema migrations, sessions/transactions, login, roles, club membership, tests, or any server-side behavior; when the user mentions backend, API, banco, permissões, or rotas; and before adding a new service layer, ORM, queue, or database.
---

# Watch Club backend

Prioritize code that is **clear, secure, easy to maintain**, and consistent with current patterns.

Simplicidade significa evitar complexidade desnecessária, não reduzir qualidade, segurança ou organização.

Não introduza novas tecnologias, frameworks ou camadas arquiteturais sem uma necessidade concreta.

Reuse existing modules before adding files. Do not broad-refactor `main.py`, extract a repository layer, or switch SQLite/SQLAlchemy/FastAPI unless the user asks. Preserve existing rows; schema changes must be additive and compatible.

For module map and handler shape, see [patterns.md](patterns.md).

## Stack (do not replace)

- FastAPI HTML app: form POST + `RedirectResponse` 303, Jinja GET. Not a JSON API by default.
- SQLAlchemy 2 (`Mapped` / `mapped_column`) on SQLite (`DATABASE_URL`). `autoflush=False`.
- Auth: Starlette `SessionMiddleware` cookie; `current_user` / `login_required` in `app/main.py`.
- Domain lives in focused modules (`catalog`, `accounts`, `roles`, `schedules`, `invites`, …). Routes in `main.py` stay thin: session, authz, call module, redirect.

## Data and migrations

- Models only in [`app/models.py`](app/models.py). Startup: `Base.metadata.create_all` then [`migrate_schema()`](app/schema.py).
- New table: add the model (create_all covers fresh DBs). New column on an existing table: `ALTER TABLE … ADD COLUMN` in `migrate_schema` with a safe default. Never DROP/rename casually.
- Unique membership is `(club_id, user_id)` — keep `UniqueConstraint`; do not “fix” races by removing it.
- Datetimes: naive UTC via `utcnow()` (`datetime.now(timezone.utc).replace(tzinfo=None)`). Compare naive to naive.
- Prefer FK to existing rows (`Show`, `Club`) over duplicated copies of names/images.

## Sessions and atomicity

- Request handler: `db = db_session()` → `try` / `except HTTPException` / `finally: db.close()`.
- One request, one logical write. `commit()` in the domain function that owns the mutation, after invariants hold.
- SQLite writes that can race (join, invite consume, role change, member limit): `exclusive_write_session` + `BEGIN IMMEDIATE`, `IntegrityError` → rollback and re-read, `close_exclusive_session` in `finally`. Do not `BEGIN IMMEDIATE` on the request session after it already did SELECTs.
- Do not leave a partial commit (e.g. user saved, invite not consumed). Catch operational errors (`MailDeliveryError`, `IntegrityError`) at the boundary, rollback, friendly 400/redirect — no 500 for expected failures.

## Auth and permissions

- Gate members with `require_club_member`; ADM-only with `require_club_admin`; feature with `require_club_perm(db, club_id, user_id, PERM_*)`.
- Club roles: `admin` / `support` / `member` in DB; UI labels ADM / SUB / Membro. Caps: `MAX_ADMINS`, `MAX_SUPPORT`.
- SUB allowlist: add a key to `SUPPORT_PERMS` + `SUPPORT_PERM_LABELS` in [`app/roles.py`](app/roles.py). ADM gets every key; SUB only the CSV in `support_perms`; `parse_support_perms` ignores unknown. Do not invent a second permission system.
- Unknown `can(perm)` is ADM-only. Check the perm that matches the action, not “is_admin” when a SUB perm exists.
- HTML 401 → `/login`; 403 → back to the club; 400 → same page `?error=` with `quote(detail)`.

## Routes

- Keep URL style: `/clubs/{id}/…` Portuguese path segments already used (`agendamentos`, `titulos`, `solicitacoes`).
- Validate with existing helpers (`valid_kind`, `valid_hex`, `valid_tag_slug`, …). Raise `HTTPException` with a Portuguese `detail`.
- Load related rows with `selectinload` (`_load_club` pattern). Don’t silently change default club tabs (`aba`).
- Config in [`app/config.py`](app/config.py) env vars. Tests must not leak `.env` (see `conftest.py`).

## Tests

- `tests/test_*.py` + FastAPI `TestClient`. Reuse `register_active` from `test_app.py`.
- Cover: happy path, 403 for the wrong role, 400 for bad input, uniqueness/races if you touch exclusive writes, schema columns if you migrate.
- Run `.venv/bin/pytest` for the files you changed (full suite when the change is cross-cutting).

## Workflow

1. Find the closest module and route pair; extend them.
2. Model/migration first if data changes, then domain function, then thin route, then tests.
3. Re-read permission and transaction paths — especially `commit` / `exclusive_write_session`.
4. Do not add Redis, Celery, Alembic, Postgres, or a service/repository folder “for later”.
