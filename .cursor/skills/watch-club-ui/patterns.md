# Padrões de UI do Watch Club

## Chrome, tokens e tipografia

| Área | Onde procurar |
|------|---------------|
| Menubar superior | `app/templates/base.html` (`app-menubar`) e `app/templates/macros/sidebar.html` (`app_menubar_nav`) |
| Menu da sala do clube | `club-nav`, `club_menu_toggle` e `club-side-link` com `is-on` / `is-quiet` |
| Popover de conta | `#account-popover` em `base.html`, com `player_card_sheet` em `macros/player_card.html` |
| Janelas e titlebars | `.wc-window`, `.wc-titlebar`, `.wc-win` e macros `app_window` / `wc_win_controls` |
| Temas | `THEMES` em `app/player.py` e seletores `wc-theme-*` em `app/static/src/input.css` |

- Em `app/static/src/input.css`, reutilize os tokens do tema e os aliases como `--background`, `--foreground`, `--card`, `--popover`, `--primary`, `--muted`, `--border`, `--ring` e `--destructive`. Para cantos, consulte `--radius`, `--wc-radius-window`, `--wc-radius-panel` e `--btn-radius`. Siga o processo de compilação do `AGENTS.md` quando alterar o CSS-fonte.
- Reutilize `--wc-scroll-thumb` e `--wc-scroll-track` nas scrollbars customizadas, inclusive em painéis, popovers, modais e chats com overflow interno.
- Use Work Sans (`font-sans`) no corpo e Fugaz One (`font-display`) no logo e em `page-heading`. Para o chrome pixel, consulte os usos de `font-pixel`, `font-headline` e `font-hero`.
- Confira o menu do clube em torno de 900 px e os ajustes existentes em 720 px. Aproveite esses pontos de quebra onde couberem.

## Inventário de assets

- **Ícones funcionais** em `app/static/icons/pixel/`. Use `px_icon` no Jinja, que chama `pixel_icon`. Consulte `ICON_FILES` e `ICON_ALIASES` em `app/pixel_icons.py` para nomes semânticos e aliases. Os ícones acompanham a cor do contexto via `currentColor`.
- **Objetos Goofy** em `app/static/icons/goofy/`. Os arquivos presentes são `tv.png` e `floppy.png`, disponíveis via `goofy_img`. Para outros objetos, consulte o inventário antes de assumir que há um arquivo correspondente.
- **Chrome retro** implementado principalmente pelas classes CSS e macros de janela acima.
- **Assets próprios** incluem as camadas de avatar em `app/static/avatars/portrait/` e os wallpapers em `app/static/wallpapers/`. Busque também pelos nomes decorativos existentes no inventário de ícones.

## Controles e feedback

- Ação principal e secundária usam `.btn.btn-primary` e `.btn.btn-secondary`. Ações discretas podem usar `.btn.btn-ghost`. Ações destrutivas usam `.btn.btn-danger`, com confirmação específica quando apropriado.
- Ações só de ícone podem usar `.btn.btn-icon` ou `.chrome-ghost` na menubar. Reaproveite a área de toque do chrome e preserve `aria-label` e `:focus-visible`. Use links para atalhos que abrem uma página e botões para ações na interface.
- Use `.muted` em texto auxiliar e estados vazios, com a próxima ação quando ela estiver disponível. Reutilize `.error` e `.ok` ou o feedback existente no fluxo.
- Reutilize os estilos de formulários e os controles nativos de data, hora e seleção. Mantenha rótulos associados aos campos e a indicação de obrigatoriedade.

## Diálogos e popovers

- Reutilize `<dialog>` com `showModal()`: `leave-dialog` e `leave-dialog-actions` para formulários e confirmações compactos, `members-dialog`, `roles-dialog` e `tag-guide-dialog` para listas ou conteúdo mais amplo. Preserve o botão Cancelar e a associação do diálogo ao título com `aria-labelledby`.
- Nos popovers, preserve `hidden`, `aria-expanded` e o fechamento com clique fora e Escape. Confira se o popover cabe no viewport e se `[hidden]` continua efetivo com o estilo aplicado.

## Sala do clube

- Catálogo usa `watch-panel`, `watch-toolbar`, `watch-list`, `watch-row`, `watch-poster` e `watch-add-btn`. Agendamentos usam `schedule-panel`, `schedule-toolbar`, `schedule-card` e `schedule-dialog`.
- Preserve a distinção entre a capa horizontal e o ícone quadrado do clube, além dos dados reais da tag renderizada por `club_tag_chip`.
