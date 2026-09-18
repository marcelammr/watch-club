# Watch Club

App web em FastAPI para gerenciar as séries que você assiste com amigos.

As contas ficam no SQLite (`watch_club.db`). Dá para entrar com **e-mail**, **Gmail** ou **Facebook**. Cadastro por e-mail só libera o login depois da confirmação. Nomes de usuário são únicos; se o desejado estiver ocupado, o site sugere variações. No perfil a foto cartoon fica em **Editar foto de perfil**, e a bio tem até 150 caracteres (como no Instagram).

Depois do login, a página inicial mostra só a saudação e três ações: **Meus Clubes**, **Criar um clube** e **Entrar com código**. Dentro do clube há **Chat** (mensagens no banco) e **Assistindo** (séries, filmes e outros títulos, com status). Quem cria o clube vira administradora e pode definir descrição, regras e capa (cor ou imagem). Clubes abertos podem ser acessados pelo perfil de alguém. Clubes fechados mostram cadeado e só entram com código. No clube aparece a quantidade de participantes; o número abre a lista, o perfil e o status (online, ausente, offline).

## Rodar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Abra http://127.0.0.1:8000

Sem SMTP configurado, o link de ativação aparece na página de verificação (modo local). Com `SMTP_HOST` no `.env`, o link vai por e-mail. Gmail e Facebook precisam de `GOOGLE_CLIENT_ID`/`SECRET` e `FACEBOOK_CLIENT_ID`/`SECRET`, com redirect `http://127.0.0.1:8000/auth/google/callback` e `.../auth/facebook/callback`.

- Criar conta, confirmar o e-mail e montar um clube
- Abrir **Minha conta** para nome de usuário, e-mail, senha e avatar
- Entrar em um clube com o código e sair quando quiser
- Buscar uma série pelo nome e adicionar
- Ver fotos, temporadas e notícias

## API extra

`GET /api/shows/search?q=breaking+bad` — busca na TVMaze sem persistir.  
`GET /api/username?q=marcela` — diz se o nome está livre e sugere alternativas.

## Stack

FastAPI, SQLAlchemy, SQLite, httpx, Jinja2.
