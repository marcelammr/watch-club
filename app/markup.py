from __future__ import annotations

import html
import re

from markupsafe import Markup

from app.pixel_emoji import inject_into_escaped

SPOILER_RE = re.compile(r"\|\|(.+?)\|\|", re.DOTALL)
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", re.DOTALL)


def pin_preview(text: str | None, limit: int = 140) -> str:
    raw = SPOILER_RE.sub(r"\1", text or "")
    raw = BOLD_RE.sub(r"\1", raw)
    raw = ITALIC_RE.sub(r"\1", raw)
    compact = " ".join(raw.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def format_chat(text: str | None) -> Markup:
    if not text:
        return Markup("")
    escaped = html.escape(text)

    def spoiler(match: re.Match[str]) -> str:
        inner = match.group(1)
        return (
            '<button type="button" class="chat-spoiler" aria-expanded="false">'
            '<span class="visually-hidden">Spoiler. Clique para revelar.</span>'
            f"{inner}</button>"
        )

    formatted = SPOILER_RE.sub(spoiler, escaped)
    formatted = BOLD_RE.sub(r"<strong>\1</strong>", formatted)
    formatted = ITALIC_RE.sub(r"<em>\1</em>", formatted)
    formatted = inject_into_escaped(formatted)
    return Markup(formatted)
