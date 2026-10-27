# Watch Club test patterns

## Layout

| File | Covers |
|------|--------|
| `tests/conftest.py` | `SECRET_KEY`, open signup, SMTP off, disposable SQLite |
| `pytest.ini` | `pythonpath = .` |
| `tests/test_app.py` | shell, auth, clubs, chat, catalog, friends, presence; **`register_active`** |
| `tests/test_roles.py` | cargos, SUB perms, caps, join lock |
| `tests/test_schedules.py` | agendamentos |
| `tests/test_invites.py` | account invites / closed registration |
| `tests/test_mail.py` | SMTP failures, no 500, rollback |
| `tests/test_discovery.py` | categories/tags |
| `tests/test_markup.py` | chat format / XSS escape |

Run: `.venv/bin/pytest tests/test_schedules.py -q` then `.venv/bin/pytest -q`.

## HTTP

```python
owner = TestClient(app)
register_active(owner, "unique_user", "unique@example.com")
created = owner.post("/clubs", data={"name": "Sala"}, follow_redirects=False)
assert created.status_code == 303
club_id = int(created.headers["location"].rsplit("/", 1)[-1])
page = owner.get(f"/clubs/{club_id}?aba=agendamentos")
assert "Próximos agendamentos" in page.text
assert "watch-search" not in page.text
```

Forbidden POST: still 303, then assert the row was **not** inserted.

## DB

```python
db = SessionLocal()
try:
    row = db.scalar(select(ClubSchedule).where(ClubSchedule.club_id == club_id))
    assert row is None
finally:
    db.close()
```

## Unit vs request

Pure functions (`can`, `wall_to_utc`, `parse_support_perms`, markup) can be tested without HTTP. Permissions that affect a route still need a request-level 403/hidden-control test.

## Isolation

One shared `test.sqlite` per pytest process (`conftest` unlinks once at import). Use distinct usernames. Don’t assume empty tables. Don’t start the live uvicorn DB for pytest.
