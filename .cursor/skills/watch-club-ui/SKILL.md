---
name: watch-club-ui
description: Orienta mudanças de interface no Watch Club, incluindo templates Jinja, CSS, composição, temas, responsividade, acessibilidade e validação visual.
---

# Watch Club UI

Siga as regras permanentes do [AGENTS.md da raiz](../../../AGENTS.md), que prevalecem em caso de divergência. Consulte [patterns.md](patterns.md) para localizar componentes e padrões existentes.

## Referência e escopo

- Trate a referência visual aprovada como alvo. Quando também houver um screenshot atual, use-o para identificar o que precisa ser corrigido e compare o resultado com a referência.
- Preserve áreas aprovadas fora do escopo. Um refinamento localizado pede mudanças localizadas. Confira as páginas que compartilham o chrome, o CSS ou a macro afetada.
- Inspecione o resultado no navegador e confira o fluxo, a composição e a responsividade em desktop e viewport estreita. Testes de comportamento complementam a inspeção visual.

## Composição

- A linguagem do Watch Club é **retro/Y2K + kawaii + pixel art**. Construa essa identidade com composição, tipografia, pixel art, objetos, bordas, sombras curtas, cantos suaves quando apropriado, pequenos relevos, microinterações e sobreposições decorativas. Use referências de desktop retro sem replicar literalmente o Windows 95.
- Expresse kawaii no desenho, nas proporções e nos detalhes, com liberdade de cor. Use formas suaves ou quadradas conforme a composição, inclusive em interfaces com pixel art.
- Organize conteúdo relacionado dentro de uma superfície principal quando a referência seguir essa hierarquia. Use seções, espaçamento, títulos e divisores para estruturar a leitura. Evite um card grande por seção e superfícies com muito espaço vazio para pouco conteúdo.
- Quando a referência usar sobreposição, deixe o objeto atravessar parte da borda, da titlebar ou do divisor. Use posicionamento, offsets, overflow visível e camadas conforme necessário. Um ícone inteiramente dentro do canto da titlebar continua sendo um ícone de cabeçalho. Reserve o efeito para pontos de destaque e preserve a leitura, os controles e a largura do viewport.

## Temas e navegação

- A interface tem vários temas. Use os tokens `--wc-*` e aliases existentes para propriedades que acompanham o tema ativo, incluindo superfícies, texto, bordas, sombras e estados. Lavanda, Lagoon e outras paletas pertencem aos seus respectivos temas.
- A menubar superior é a navegação global. Mantenha as ações pessoais no perfil e no popover de conta. O `club_menu_toggle` é válido em telas estreitas para abrir a navegação local da sala do clube.
- A direção do `#account-popover` é **crachá + pequena janela retro + ações pessoais**. Use `player_card_sheet` e `wc-badge` como ponto de partida e mantenha o Player Card RPG fora do popover. Preserve LV, EXP e energia na página de perfil público.

## Ícones, objetos e ações

- Use **ícones funcionais** para ações e navegação. Use **ícones de seção** com discrição quando ajudarem a reconhecer a hierarquia. Reserve **objetos decorativos** mais expressivos, como claquete, TV/CRT, crachá, disquete ou sparkles, para pontos em que contribuam para a composição. Evite decorar cada título.
- Antes de criar um SVG, procure um asset adequado no inventário atual. Escolha pela adequação à referência e ao contexto. Confira [patterns.md](patterns.md) para localizar os ícones e objetos existentes.
- Diferencie a ação principal ou secundária, a ação destrutiva com a confirmação apropriada, a ação só de ícone e o atalho visual para uma área. Use as variantes existentes. A ação só de ícone precisa de área clicável adequada, nome acessível e foco visível. Reserve uma caixa permanente para situações em que ela ajude a leitura do controle.
