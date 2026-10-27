---
name: watch-club-ui
description: Guides Watch Club frontend, UI, and UX work so new screens stay beautiful, intuitive, responsive, and consistent with existing Jinja templates, Tailwind tokens, dialogs, and macros. Use when changing templates, CSS, layout, visual hierarchy, empty/error states, modals, accessibility, or any user-facing interface; when the user mentions UI, UX, frontend, CSS, or design; and before redesigning or swapping the frontend stack.
---

# Watch Club UI

Prioritize interfaces that are **bonitas, intuitivas, responsivas e bem acabadas**, reusing existing components and patterns.

Simplicidade significa evitar complexidade desnecessária, não reduzir qualidade visual ou experiência.

Do not do broad redesigns or swap stack/framework unless the user explicitly asks.

After UI/layout changes, verify in the browser (behavior, not just a screenshot). Rebuild CSS with `npm run build:css` when editing [`app/static/src/input.css`](app/static/src/input.css).

For tokens, class names, and file map, see [patterns.md](patterns.md).

## Stack (do not replace)

- Pages: FastAPI + Jinja in `app/templates/`, extend `base.html`.
- Styles: Tailwind tokens in `input.css` → compiled `app/static/style.css`. Add classes in `@layer components`; use existing tokens (`bg-background`, `text-muted-foreground`, `border-border`, `rounded-2xl`, etc.).
- Product chrome is **dark by default** (`html.dark`). Design for dark first; do not invert the theme.
- Type: **Work Sans** (`font-sans`) for UI; **Fugaz One** (`font-display`) only for logo / `page-heading`.
- Portuguese UI (`pt-BR`). Roles on screen: **ADM**, **SUB**, **Membro** — never `admin` / `support` in copy.
- React islands in `frontend/` (login, command palette, color picker, emoji) stay islands. Do not migrate Jinja pages to React, add a design-system package, or introduce CSS-in-JS.

## Reuse before inventing

1. Search templates, `macros/`, and `input.css` for a close pattern.
2. Prefer existing classes (`btn btn-primary|secondary|ghost|danger|icon`, `muted`, `error`, `ok`, `leave-dialog`, `watch-list`, `club-side-link`).
3. Macros: `user_avatar`, `app_sidebar` / `hamburger` / `club_menu_toggle`, `club_tag_chip`, `presence_mark`, emoji/color pickers.
4. New CSS only when no existing class fits. Match radius (`--radius` / 0.875rem, cards `rounded-2xl`), lavender primary `#B892FF`, violet accent `#6C63FF`, cream text `#F7F0FF`, night bg `#1F1B24`.
5. Do not replace club covers with icons, redesign Home, or restyle a QA’d modal unless asked.

## Visual hierarchy

- One clear page heading (`page-heading` / `h1`). Section titles smaller (`text-lg font-semibold`), meta in `.muted`.
- Primary action: `btn btn-primary`. Secondary: `btn-secondary` or `btn-ghost`. Destructive: `btn-danger` + confirm.
- Lists use existing row patterns (`watch-row`, `club-row`, `schedule-card`) — not a new card system.
- Club identity (cover, tag, ADM/SUB name colors) is per-club; do not hardcode extra palettes.

## Layout and responsive

- Logged-in pages live in `app-shell` + sidebar + `top` header. Club room uses `club-shell` / `club-nav` (drawer below ~900px).
- Check **desktop and a ~390px viewport** when layout changes.
- Prefer CSS that already has breakpoints (`min-[901px]`, `720px`) over new ones.
- Touch targets ~40px (`h-10`) for icon buttons in the header/nav.
- Native `date` / `time` / `select` / `textarea` styled like existing inputs. No custom datepicker.

## Modals and overlays

- Small forms/confirms: `<dialog class="leave-dialog">` + `showModal()`. Larger lists (membros, cargos): `members-dialog` / `roles-dialog`.
- Keep the list/page as the hero; open create/edit in a dialog (`+ Novo …`), like titles and schedules.
- Backdrop click and **Cancelar** close. Primary submit on the right (`leave-dialog-actions`).
- Do not stack a second custom overlay system. Escape already closes club nav / popovers — don’t break it.
- Popovers (`account-popover`, `club-switch-popover`): `hidden`, `aria-expanded`, click-outside + Escape.

## Empty, error, feedback

- Empty: short `.muted` copy + the next action (“Crie o primeiro com + Novo agendamento.”).
- Errors: `<p class="error">` (query `error` or form). Success: `.ok` or obvious list update after `303` redirect. No toast library.
- Destructive actions: `confirm()` or a leave-dialog. Copy is specific (“Remover “Nome” deste clube?”).
- Loading: avoid empty flashes; keep the previous pattern (full page render, not skeleton frameworks).

## Accessibility (baseline)

- `lang="pt-BR"` already on `html`. Real `<button>` / `<a>` / `<label>`. Icon-only controls need `aria-label` (and `title` if the rest of the chrome does).
- Decorative SVG: `aria-hidden="true"`. Focus: existing `:focus-visible` ring (`--btn-focus` / `--ring`). Do not `outline: none` without a replacement.
- `dialog` for modals; `aria-labelledby` on the title. `hidden` vs CSS-only hide: `[hidden]` must actually hide (watch `inline-flex` vs `[hidden]`).
- Honor `prefers-reduced-motion` for new motion (buttons already do).
- Don’t ship contrast worse than the current dark theme (muted text stays on `muted-foreground`, not a new gray).

## Copy and interaction

- Short, direct Portuguese. Same vocabulary as nearby screens (Agendamentos, Assistindo, Bate-papo, Configurações).
- Fewer settings. If a member only views, don’t show the create control.
- Forms: labels wrapping fields; optional fields say “Opcional”; `required` on what is required.

## Workflow

1. Identify the closest existing screen (clube, Assistindo, dialog de título, cargos, amigos).
2. Extend that pattern; don’t start from a generic dashboard template.
3. Implement the smallest complete UI: hierarchy, empty/error, modal, responsive.
4. `npm run build:css` if CSS changed.
5. Browser-check the flow and sibling pages that share the same chrome/state.
