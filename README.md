# Watch Club

App web em FastAPI para gerenciar as séries que você assiste com amigos.

Você cria um **clube**, compartilha o código, busca a série pelo nome e o backend busca na [TVMaze](https://www.tvmaze.com/api) o pôster, o resumo e as temporadas. Notícias vêm de um RSS do Google News (sem API key).

## Rodar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Abra http://127.0.0.1:8000

- Criar conta e um clube
- Buscar uma série pelo nome e adicionar
- Ver fotos, temporadas e notícias
- Atualizar os dados remotos quando quiser

## API extra

`GET /api/shows/search?q=breaking+bad` — busca na TVMaze sem persistir.

## Stack

FastAPI, SQLAlchemy, SQLite, httpx, Jinja2.
