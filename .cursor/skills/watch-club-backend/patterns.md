# Watch Club backend patterns

## Modules

| Module | Owns |
|--------|------|
| `app/main.py` | FastAPI app, session cookie, HTML routes, `_club_caps`, redirects |
| `app/models.py` | SQLAlchemy tables |
| `app/schema.py` | Additive `ALTER` / index / seed for existing DBs |
| `app/db.py` | engine, `SessionLocal`, `get_db`, `exclusive_write_session` |
| `app/roles.py` | `ROLE_*`, `SUPPORT_PERMS`, `can`, `parse_support_perms` |
| `app/catalog.py` | clubs, members, joins, titles, `require_club_*` |
| `app/accounts.py` | users, `utcnow`, email tokens |
| `app/schedules.py` | club watch schedules |
| `app/invites.py` | registration invites |
| `app/security.py` | password hash, join codes |
| `app/config.py` | env |

Tests: `tests/test_app.py`, `test_roles.py`, `test_schedules.py`, `test_invites.py`, `test_mail.py`, `test_discovery.py`. `conftest.py` forces `SMTP_HOST=""` and a throwaway SQLite file.

## Handler shape

```python
db = db_session()
try:
    user = login_required(request, db)
    require_club_perm(db, club_id, user.id, PERM_SCHEDULES)
    create_schedule(...)  # commits inside
    return RedirectResponse(f"/clubs/{club_id}?aba=agendamentos", status_code=303)
except HTTPException as exc:
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    if exc.status_code == 403:
        return RedirectResponse(f"/clubs/{club_id}", status_code=303)
    if exc.status_code == 400:
        return RedirectResponse(f"/clubs/{club_id}?aba=...&error={quote(str(exc.detail))}", status_code=303)
    raise
finally:
    db.close()
```

## Permissions

`PERM_TAG`, `PERM_JOINS`, `PERM_TITLES`, `PERM_SCHEDULES` in `SUPPORT_PERMS`. New SUB capability = new constant in that tuple (cargos checkboxes iterate it). `_club_caps` exposes `can_*` to templates.

## Exclusive write

Use for inserts that must not double-apply under SQLite concurrent tabs (join, invite, role/limit). Pattern: open write session → mutate → `commit` → `IntegrityError` rollback + check existing row.

## Time

Store UTC naive `DateTime`. Club-facing clocks that need a zone (schedules) convert with `zoneinfo` (`America/Sao_Paulo`) at the edge, not a per-user TZ table.
