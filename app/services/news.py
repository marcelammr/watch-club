from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import feedparser

_MONTHS_PT = (
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
)


def format_news_when(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    parsed = None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if parsed.month < 1 or parsed.month > 12:
        return ""
    return f"{parsed.day} {_MONTHS_PT[parsed.month - 1]} {parsed.year}"


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
