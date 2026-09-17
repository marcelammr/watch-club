# Watch Club

App web em FastAPI para gerenciar as séries que você assiste com amigos.

As contas ficam no SQLite (`watch_club.db`). O cadastro só libera o login depois da **confirmação de e-mail**. Nomes de usuário são únicos; se o desejado estiver ocupado, o site sugere variações. No perfil dá para escolher uma foto cartoon (animais, plantas, paisagens e cinema).

## Rodar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Abra http://127.0.0.1:8000

Sem SMTP configurado, o link de ativação aparece na página de verificação (modo local). Com `SMTP_HOST` no `.env`, o link vai por e-mail.

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
