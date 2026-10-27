# Watch Club UI patterns

## Files

| Area | Where |
|------|--------|
| Tokens + components | `app/static/src/input.css` |
| Compiled CSS | `app/static/style.css` (`npm run build:css`) |
| Tailwind theme | `tailwind.config.js` |
| Shell | `app/templates/base.html` |
| Pages | `app/templates/*.html` |
| Macros | `app/templates/macros/` (`avatar`, `sidebar`, `club_tag`, `presence`, `emoji`, `color_picker`) |
| React islands | `frontend/` (login, command palette, color picker, emoji) |

## Dark palette (default)

- Night bg `#1F1B24`, card `#26222C`, cream text `#F7F0FF`
- Lavender primary `#B892FF`, violet `#6C63FF`, rose `#FF5D8F`
- Radius `--radius: 0.875rem`; buttons use `--btn-radius`
- Light `:root` tokens exist; product `html` is `class="dark"`

## Buttons

Always pair `.btn` with a variant:

- `btn btn-primary` — main action (lavender)
- `btn btn-secondary` — next action
- `btn btn-ghost` — cancel / quiet
- `btn btn-danger` — destructive
- `btn btn-icon` — square icon control

Header icon buttons: `home-btn`, `back-btn`, `bell-btn`, `sidebar-toggle` (40×40, transparent).

## Type and feedback

- Logo / top title: `font-display` (Fugaz One)
- Body: `font-sans` (Work Sans)
- Helper: `.muted` · error: `.error` · success: `.ok`

## Dialogs

- Compact: `leave-dialog` + `leave-dialog-actions` (sair do clube, adicionar título, novo agendamento)
- Wide/scroll: `members-dialog`, `roles-dialog`, `tag-guide-dialog`
- Native `<dialog>`, `showModal()`, backdrop `rgba(10, 8, 14, 0.55)`
- JS pattern: open buttons `js-*-open`, cancel `js-*-cancel`, close if `event.target === dialog`

## Club room

- Nav: `club-side-link` / `is-on` / `is-quiet`
- Catalog: `watch-panel`, `watch-toolbar`, `watch-list`, `watch-row`, `watch-poster` (2:3), `watch-add-btn`
- Schedules: `schedule-panel`, `schedule-toolbar`, `schedule-card`, `schedule-dialog`
- Cover crop **16:10**; club icon **1:1**. Do not swap covers for icons.

## Breakpoints already in CSS

- Club mobile bar / nav: `min-[901px]`
- Some denser layouts: `720px` / `721px`

Reuse these before adding another breakpoint.

## Forms

`label` wraps the control. Inputs in `header`/`main` already get full-width bordered fields. Prefer `type="date"` / `type="time"` / `select` over custom widgets.
