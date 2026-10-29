from __future__ import annotations

import re
import unicodedata

SEARCH_MIN_CHARS = 2
_SPACES = re.compile(r"\s+")


def normalize_search_query(raw: str | None) -> str:
    return _SPACES.sub(" ", (raw or "").strip())


def fold_search_text(raw: str | None) -> str:
    text = normalize_search_query(raw)
    stripped = "".join(
        char for char in unicodedata.normalize("NFKD", text) if unicodedata.category(char) != "Mn"
    )
    return stripped.casefold()


def search_ready(raw: str | None) -> bool:
    return len(fold_search_text(raw)) >= SEARCH_MIN_CHARS


def _rank_tier(name: str | None, query_folded: str) -> int:
    folded = fold_search_text(name)
    if folded == query_folded:
        return 0
    if folded.startswith(query_folded):
        return 1
    if query_folded in folded:
        return 2
    return 3


def rank_search_results(results: list[dict], query: str | None) -> list[dict]:
    folded = fold_search_text(query)
    if not folded:
        return list(results)
    return sorted(results, key=lambda item: _rank_tier(item.get("name"), folded))
