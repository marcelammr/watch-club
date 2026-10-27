---
name: watch-club-qa
description: Guides Watch Club testing and QA so coverage stays proportional to risk—pytest for backend, auth, permissions, and data; focused behavior checks for UI; short manual QA only when humans must validate. Use after implementing features or fixes, when writing tests, when a bug needs a regression, or when the user asks for QA, testes, pytest, or a test plan.
---

# Watch Club QA

Test in a way that is **efficient and proportional** to the change.

Simplicidade significa testar de maneira eficiente e proporcional, não reduzir confiabilidade.

Preserve current pytest patterns. Não introduza ferramentas ou frameworks de teste novos sem necessidade concreta.

For file map and assertion habits, see [patterns.md](patterns.md).

## What to automate

**Must have pytest** when the change touches:

- Models, `migrate_schema`, unique constraints, exclusive writes
- Auth, invites, mail, OAuth, session
- Roles / `SUPPORT_PERMS` / `require_club_perm`
- Redirects, 400/403, data that must not persist on failure

Typical cases: happy path, forbidden role, bad input, and the invariant that made the feature exist (invite not consumed, past schedule hidden, last ADM stays).

**UI / CSS / copy:** assert the behaviors that can break (tab isolation, button present only with perm, empty copy, `error=` redirect, form POST 303). Do not snapshot layouts or assert every class/color.

**Skip:** pixel-perfect CSS, hover states, “looks aligned”, scenarios already covered in another test file.

## After an implementation

1. Run the **relevant** files first: `.venv/bin/pytest tests/test_<area>.py -q`
2. If the change is cross-cutting (auth, schema, roles, `main.py` tab parsing) or those files pass and the PR is ready, run **`.venv/bin/pytest -q`**
3. Propose **short manual QA** only for flows a human (or the browser) must feel: dialog open/close, crop, responsive nav, visual hierarchy. A handful of steps, not a matrix.

Do not dump a huge manual checklist that repeats pytest. If pytest already proves ADM creates and member cannot POST, manual QA is “open the dialog, submit once, list updates” — not every role again.

## Writing tests

- FastAPI `TestClient`, `follow_redirects=False`, unique `username` / email per test.
- Reuse `register_active` from [`tests/test_app.py`](tests/test_app.py). Club helpers: copy `_create_club` / `_user_id_by_key` from `test_roles.py` or `test_schedules.py` rather than a new fixture framework.
- Assert status + `Location`, then HTML substrings that name the behavior, then DB with `SessionLocal` when persistence matters.
- Schema: `inspect(engine)` for tables/columns after migrations.
- Env: `conftest.py` already blanks SMTP and uses `tests/test.sqlite`. `monkeypatch` app flags (`REGISTRATION_INVITE_REQUIRED`) **after** import; don’t rely on `.env`.
- New file `tests/test_<feature>.py` when the domain is new; otherwise add to the existing file.

## Bugs found in QA

Add a regression test when the failure is repeatable in HTTP/DB/HTML (SMTP 550, invite leftover, `[hidden]` vs `inline-flex`, wrong `aba` falling through). Skip a test for a one-off visual niggle you already fixed by CSS.

## Manual / browser QA

- Exercise the changed flow end to end; check sibling pages that share state.
- Desktop + a narrow viewport when layout changed.
- Empty, error, and permission-off states if the code has them and pytest did not already render those strings.

## Do not

- Playwright/Cypress/factory-boy/pytest-django as a new default
- Snapshot testing of full `style.css`
- Testing private helpers that are already covered via the route
- Expanding QA into features that did not change
