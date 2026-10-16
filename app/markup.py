from __future__ import annotations

import html
import re

from markupsafe import Markup

SPOILER_RE = re.compile(r"\|\|(.+?)\|\|", re.DOTALL)
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", re.DOTALL)


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
    return Markup(formatted)
