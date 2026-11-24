# Watch Club — regras para agentes

Regras permanentes de produto e interface. Decisões de uma tarefa pontual não entram aqui.

Quando este arquivo e um skill antigo divergirem no chrome visual (menubar global, vários temas), siga os templates, o CSS e este arquivo.

## Onde isso vive

- App: FastAPI + Jinja (`app/templates/`, `app/main.py`) e SQLAlchemy/SQLite. Rotas HTML com POST e redirect 303. Não transformar o app numa API JSON, nem trocar o banco, o ORM ou o framework.
- Estilo: editar `app/static/src/input.css` (`@layer components`). Compilar com `npm run build:css` para `app/static/style.css`. Tailwind 3.4 (`tailwind.config.js`). Não tratar o CSS compilado como fonte.
- Ilhas React em `frontend/` (paleta de comandos, login, color picker, emoji). Não migrar páginas Jinja para React nem criar outro design system.
- Temas e fundos: catálogo `THEMES` e `WALLPAPER_SPECS` em `app/player.py`. O `<html>` sai com `dark`, `wc-theme-{{ visitor_theme }}` (padrão `watchclub`) e a classe de wallpaper.
- Ícones funcionais: `px_icon` / `pixel_icon` (`app/templates/macros/pixel.html`, `app/pixel_icons.py`) lendo `app/static/icons/pixel/`. O preenchimento vira `currentColor`.
- Janelas: classes `.wc-window`, `.wc-titlebar`, `.wc-win` e macros `app_window` / `wc_win_controls`. Não há um pack de skin Windows vendido no repositório.
- Objetos Goofy já no repo: só `app/static/icons/goofy/tv.png` e `floppy.png`, via `goofy_img`.
- Tags: macro `club_tag_chip` em `app/templates/macros/club_tag.html`.
- Navegação global: `app-menubar` / `app_menubar_nav` em `app/templates/base.html` e `macros/sidebar.html` (Início, Clubes, Agenda, Notícias, Amigos). O menu do clube (`club-nav`, `club_menu_toggle`) é local da sala do clube.
- Popover de conta: `#account-popover` + `player_card_sheet` (crachá `wc-badge`).
- Copy em pt-BR. Papéis na tela: **ADM**, **SUB**, **Membro**.

Skills em `.cursor/skills/` cobrem backend, UI e QA. Use-os para o formato de rota, teste e componente. A paleta única e a sidebar global descritas no skill de UI estão desatualizadas.

## 1. Filosofia do produto

Watch Club é uma agenda social leve para assistir séries, filmes e outros programas com amigos.

Priorizar simplicidade, clareza, interface intuitiva, baixa fricção e evitar duplicar funcionalidades.

**A Home apresenta; páginas especializadas aprofundam.**

Configurações da Conta (`/conta`) tratam da pessoa/conta. Clubes e outras entidades ficam nas áreas que já existem (sala do clube e as configurações do clube).

## 2. Preservação de áreas aprovadas

Não redesenhar nem refatorar uma área já aprovada se a tarefa não pedir isso.

Antes de alterar um componente compartilhado (`base.html`, macros, `input.css`, ícones usados em várias telas), ver o impacto nas outras páginas.

Não ampliar o escopo em silêncio. Um refinamento visual não autoriza mudar regras de negócio, autenticação, autorização, banco, rotas, modelos, dados sociais nem comportamento funcional alheio.

## 3. Referências visuais

Uma imagem de referência aprovada é o **alvo visual**, não só inspiração.

Se também houver screenshot do estado atual, a referência é o destino e o screenshot é o que precisa ser corrigido. Comparar os dois antes de declarar a tarefa concluída.

Testes passando não fecham uma tarefa visual cujo resultado ainda está claramente distante da referência.

## 4. Design do Watch Club

Linguagem: **retro/Y2K + kawaii + pixel art**, sem clonar o Windows 95.

- Página limpa e organizada.
- Painéis agrupam informação (`.wc-window` / superfícies existentes).
- Janelas flutuantes servem a ações e escolhas.
- O retro/pixel aparece na tipografia, nos objetos, nas bordas, nas sombras, nos detalhes e na interação.

Fontes já no projeto: Work Sans (`font-sans`) no corpo; Fugaz One (`font-display`) em logo e `page-heading`; Jersey 15, Pixelify Sans e Hero (`font-pixel`, `font-headline`, `font-hero`) no chrome pixel. Não trocar a família tipográfica por uma sans genérica.

“Minimalista” não é remover identidade, trocar componentes estilizados por links crus, esconder controles necessários nem cair numa UI genérica.

“Pixel” não exige que todo componente seja quadrado. Cantos suaves já existem (`--radius`, `--wc-radius-window`, `--wc-radius-panel`, `--btn-radius`). Use-os quando fizer sentido.

## 5. Temas

Há vários temas (`wc-theme-*` em `app/player.py` e `input.css`). Rosa, lilás, azul Lagoon ou a paleta do tema `watchclub` não são a cor fixa do produto.

Preferir tokens que já acompanham o tema: `--wc-*` e os aliases `--background`, `--foreground`, `--card`, `--popover`, `--primary`, `--muted`, `--border`, `--ring`, `--destructive`. Isso vale para fundos, superfícies, texto, bordas, sombras, estados, botões, scrollbars e highlights.

Cores fixas ficam na definição de cada tema. Fora dali, evitar hex solto quando a propriedade deve mudar com o tema. Assets estruturais devem funcionar nos temas existentes.

Fundos (`wc-paper-*` e wallpapers em `app/static/wallpapers/`) são outra escolha do usuário. Não os confundir com o tema.

## 6. Scrollbars

Scrollbar estilizada acompanha o tema ativo: página, painéis, popovers, modais, chats e qualquer overflow.

O projeto já faz isso em `html` e em `*::-webkit-scrollbar` com `--wc-scroll-thumb` e `--wc-scroll-track`. Reutilizar esses tokens. Não deixar a scrollbar nativa cinza numa superfície tematizada.

## 7. Assets e packs

Antes de criar um SVG ou ícone, procurar em `app/static/icons/pixel/`, `ICON_FILES` / `ICON_ALIASES`, `app/static/icons/goofy/`, `app/static/avatars/` e `app/static/wallpapers/`.

### Pixelarticons

Preferência para ícones funcionais pequenos: voltar, informação, navegação, mensagens, segurança, editar, sair, ações utilitárias.

No repo eles já estão em `app/static/icons/pixel/` e entram por nome semântico (`px_icon('back')`, `nav-home`, `ui-edit`, …). O comentário da macro chama o conjunto de pack Streamline; tratar essa pasta como o inventário funcional. Não adicionar um segundo pacote de ícones.

### Retro Desktop UI Kit

Referência para janelas, titlebars, controles, inputs, botões, bordas, estado pressionado e relevos pequenos. A implementação é CSS e macros (`.wc-win`, `.wc-titlebar`, `wc_win_controls`, `app_window`), não uma pasta de skin.

Não copiar uma skin inteira nem transformar o Watch Club em Windows clássico.

### Goofy Retro Tech

Usar com moderação para objetos tecnológicos retro maiores, quando combinarem com a referência: TV, computador, disquete, monitor, câmera.

Hoje só `tv` e `floppy` estão vendidos, e só na conta. Não usar um asset só porque pertence ao pack. Se destoar, procurar outro.

### Assets próprios

Criar só quando não houver equivalente, quando uma referência aprovada exigir um desenho específico, ou quando for identidade própria do Watch Club (por exemplo camadas de avatar em `app/static/avatars/portrait/`).

Não gerar SVG genérico que duplique o que já existe. Há fallbacks desenhados em `pixel_icons.py` para nomes sem arquivo; não multiplicá-los.

## 8. Ícone funcional ≠ objeto decorativo

- **Ícone funcional:** pequeno, claro, de ação (`ui-*`, `nav-*`, `px_icon`).
- **Ícone de seção:** discreto, só quando ajuda a reconhecer a hierarquia.
- **Objeto decorativo:** mais expressivo e raro (`decor-clapper`, `decor-computer`, `decor-sparkle`, `kawaii-*`, `goofy_img`).

Não pendurar um enfeite em cada título.

## 9. Quebra visual / overlap

Objetos decorativos podem sair um pouco do container quando a referência faz isso: cruzar uma titlebar, cobrir uma borda, interromper uma linha, ficar alguns pixels para fora, com leve assimetria.

Implementar com `position`, `overflow: visible`, offsets, `transform` e `z-index`. Colocar um ícone no canto interno do cabeçalho não é “quebrar a borda”.

Overlap cria personalidade, não ruído. Decoração não pode gerar scroll horizontal nem cobrir um controle.

## 10. Botões e ações

Nem toda ação é um retângulo pesado. Distinguir botão de ação (`.btn.btn-primary` / `.btn-secondary`), destrutivo (`.btn-danger`), ação só de ícone (`.btn.btn-icon` ou `.chrome-ghost` na menubar) e atalho visual.

Ação só de ícone mantém área clicável, `aria-label` e foco visível; a caixa não precisa continuar desenhada.

Preferir borda coerente com o tema, canto suave, sombra curta, hover delicado e pressão pequena. Evitar sombra grande e caixa pesada sem necessidade.

## 11. Objetos kawaii

O kawaii vem do desenho, das proporções, dos detalhes, do relevo, da composição, das microinterações e da pixel art. Não depende de rosa, coração ou sticker em tudo.

## 12. Densidade e containers

Evitar card dentro de card quando o conteúdo cabe numa superfície principal com seções internas.

Não abrir uma caixa grande para pouco conteúdo. Configurações ficam compactas e hierarquizadas.

## 13. Navbar

A navegação global é a menubar (`app-menubar`). Não reintroduzir sidebar, drawer ou hamburger globais sem pedido explícito.

O toggle `club_menu_toggle` abre o menu **da sala do clube** em viewport estreita. Isso não é navegação global e não deve ser copiado para o app inteiro.

Ações pessoais ficam no perfil e no popover de conta, não numa segunda navegação.

## 14. Perfil e popovers

Popovers (`account-popover`, `bell-popover`, troca de clube) são compactos, cabem no viewport e fecham com clique fora e Escape.

No popover de conta, manter **crachá + janela retro pequena + ações pessoais** (`wc-badge` / `player_card_sheet`). Não voltar ao Player Card RPG nesse popover.

Não reintroduzir no popover, sem pedido: LV, EXP, energia, classes, stats de RPG.

A página de perfil (`profile.html`) ainda mostra LV, EXP e energia. Não apagar isso por causa desta regra, e não copiar esses stats de volta para o popover.

## 15. Tags

Tags são dados reais. Renderizar com `club_tag_chip` (slug, emojis e cores vindos do registro). Não trocar a tag por uma imagem decorativa nem fixar nome, emoji ou cor para imitar um screenshot.

## 16. Responsividade e acessibilidade

Toda mudança visual considera desktop, viewport estreita (o clube muda por volta de 900px; há ajustes em 720px), foco por teclado, contraste, área clicável e `prefers-reduced-motion` quando houver animação.

`lang="pt-BR"` já está no `html`. Controle só de ícone precisa de `aria-label`. SVG decorativo fica `aria-hidden`. Não remover o anel `:focus-visible` sem substituto.

## 17. CSS e componentes existentes

Antes de criar CSS ou componente:

1. tokens existentes (`--wc-*` e aliases do Tailwind);
2. utilities e classes já usadas (`.btn*`, `.muted`, `.error`, `.ok`, `.leave-dialog`, `.chrome-ghost`);
3. macro compartilhada;
4. asset existente;
5. só então algo novo.

Não criar um design system paralelo.

## 18. Testes e validação

Suíte: `.venv/bin/pytest -q` (config em `pytest.ini`, `pythonpath = .`). Primeiro o arquivo da área: `.venv/bin/pytest tests/test_<area>.py -q`. Suíte completa quando a mudança atravessa auth, schema, papéis ou várias rotas.

Em 23 nov 2026 a coleta era de **378 testes**. Esse número não é meta fixa; conferir de novo com `--collect-only` ou com a suíte.

Depois de alterar: testes relevantes; suíte completa se o escopo justificar; inspeção visual no browser quando a mudança for de UI. Teste verde não substitui olhar a tela numa tarefa de design.

Pytest cobre comportamento (rota, permissão, HTML, persistência). Não snapshot de layout nem framework novo de teste.

## 19. Servidor local

No shell desta máquina, `watchclub` entra no repositório, ativa `.venv` e sobe `uvicorn app.main:app --reload` em http://127.0.0.1:8000.

É um atalho local, não um script do repo. Não criar outro comando equivalente. O `README.md` continua descrevendo venv, `npm run build` e uvicorn para quem não tem a função.

CSS e JS em desenvolvimento: `npm run watch:css` e `npm run watch:js`.

## 20. Regra de conclusão

Antes de declarar uma tarefa visual concluída:

- a referência fornecida foi respeitada?
- o que já existia foi reutilizado?
- os temas continuam válidos?
- surgiu duplicação?
- algo saiu do escopo?
- a interface ficou coerente, não só funcional?
- comportamento e testes relevantes foram validados?

Se um requisito visual explícito ainda estiver claramente ausente, não tratar a tarefa como fechada. Corrigir dentro do escopo ou relatar o bloqueio.
