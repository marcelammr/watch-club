from urllib.parse import urlparse

from fastapi import Request


def internal_href(raw: str | None, allowed_netloc: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"}:
            return ""
        if parsed.netloc.lower() != (allowed_netloc or "").lower():
            return ""
    elif not text.startswith("/") or text.startswith("//"):
        return ""
    path = parsed.path or "/"
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return ""
    if ".." in path.split("/"):
        return ""
    return path + (f"?{parsed.query}" if parsed.query else "")


def href_path(href: str) -> str:
    return href.split("?", 1)[0]


def back_href_for(request: Request) -> str:
    current = request.url.path
    if current == "/":
        return ""
    netloc = request.url.netloc
    incoming = internal_href(request.headers.get("referer"), netloc)
    stored = dict(request.session.get("nav_return") or {})
    if incoming and href_path(incoming) != current:
        stored[current] = incoming
        request.session["nav_return"] = stored
    href = internal_href(stored.get(current, ""), netloc)
    return href if href and href_path(href) != current else ""
