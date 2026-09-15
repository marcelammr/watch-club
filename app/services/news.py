from __future__ import annotations

from urllib.parse import urlencode

import feedparser

NEWS_FEED = "https://news.google.com/rss/search"


def fetch_show_news(show_name: str, limit: int = 8) -> list[dict]:
    query = f'"{show_name}" série OR series OR TV'
    url = f"{NEWS_FEED}?{urlencode({'q': query, 'hl': 'pt-BR', 'gl': 'BR', 'ceid': 'BR:pt-419'})}"
    parsed = feedparser.parse(url)
    items = []
    for entry in parsed.entries[:limit]:
        source = entry.get("source")
        source_title = source.get("title") if isinstance(source, dict) else None
        items.append(
            {
                "title": entry.get("title", "Sem título"),
                "url": entry.get("link", ""),
                "source": source_title,
                "published_at": entry.get("published"),
            }
        )
    return [item for item in items if item["url"]]
