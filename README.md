# Watch Club

App web em FastAPI para gerenciar as séries que você assiste com amigos.

As contas ficam no SQLite (`watch_club.db`). Dá para entrar com **e-mail**, **Gmail** ou **Facebook**. Cadastro por e-mail só libera o login depois da confirmação. Nomes de usuário são únicos; se o desejado estiver ocupado, o site sugere variações. No perfil a foto cartoon fica em **Editar foto de perfil**, e a bio tem até 150 caracteres (como no Instagram).

Depois do login, a página inicial mostra só a saudação e três ações: **Meus Clubes**, **Criar um clube** e **Entrar com código**. Dentro do clube há **Chat** (mensagens no banco) e **Assistindo** (séries, filmes e outros títulos, com status). Quem cria o clube vira administradora e pode definir descrição, regras e capa (cor ou imagem). Clubes abertos podem ser acessados pelo perfil de alguém ou pelo código do clube, que entra direto. Clubes fechados mostram cadeado: o código só localiza o clube e a entrada vira pedido para a administração (ADM ou SUB com permissão de solicitações) aprovar. No clube aparece a quantidade de participantes; o número abre a lista, o perfil e o status (online, ausente, offline).

## Rodar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
npm run build
cp .env.example .env
uvicorn app.main:app --reload
```

O CSS é gerado com **Tailwind 3.4**. O palete de comandos (shadcn `Command`) abre com **⌘K** ou **Ctrl+K**. Em desenvolvimento, use `npm run watch:css` e `npm run watch:js` em outros terminais.

Abra http://127.0.0.1:8000

Sem SMTP configurado, o link de ativação aparece na página de verificação (modo local). Com `SMTP_HOST` no `.env`, o link vai por e-mail. Gmail e Facebook precisam de `GOOGLE_CLIENT_ID`/`SECRET` e `FACEBOOK_CLIENT_ID`/`SECRET`, com redirect `http://127.0.0.1:8000/auth/google/callback` e `.../auth/facebook/callback`.

Para testes fechados, `REGISTRATION_INVITE_REQUIRED=true` no `.env` exige um convite de uso único no cadastro. Contas OAuth novas também ficam bloqueadas; quem já tem conta continua entrando. Gere, liste e revogue convites no servidor:

```bash
python -m app.invites generate
python -m app.invites list
python -m app.invites revoke WC-XXXX-XXXX-XXXX-X
```

Com a variável em `false` (padrão), o cadastro volta a ser público sem remover os convites já emitidos.

- Criar conta, confirmar o e-mail e montar um clube
- Abrir **Minha conta** para nome de usuário, e-mail, senha e avatar
- Entrar em um clube aberto com o código (fechado: o código envia um pedido) e sair quando quiser
- Buscar uma série pelo nome e adicionar
- Ver fotos, temporadas e notícias

## API extra

`GET /api/shows/search?q=breaking+bad` — busca na TVMaze sem persistir.  
`GET /api/username?q=marcela` — diz se o nome está livre e sugere alternativas.

## Stack

FastAPI, SQLAlchemy, SQLite, httpx, Jinja2, Tailwind CSS 3.4.
