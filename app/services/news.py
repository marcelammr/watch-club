from __future__ import annotations

import gzip
import http.client
import json
import re
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import quote, urlencode, urljoin

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

NEWS_FEED = "https://news.google.com/rss/search"

TOPIC_QUERIES = (
    (
        "filmes-series",
        'filme OR série OR series streaming (trailer OR estreia OR temporada OR elenco) when:14d',
    ),
    (
        "filmes-series",
        'Netflix OR "Prime Video" OR Disney+ OR Max OR HBO (série OR filme OR temporada) when:14d',
    ),
    (
        "anime",
        'anime OR "filme anime" OR "temporada anime" (estreia OR trailer OR temporada) when:14d',
    ),
    (
        "tv",
        '"programa de TV" OR "reality show" OR "talk show" OR novela (estreia OR renovação OR elenco) when:14d',
    ),
)

_KEEP_WORDS = (
    "série",
    "serie",
    "filme",
    "filmes",
    "anime",
    "temporada",
    "trailer",
    "elenco",
    "estreia",
    "streaming",
    "netflix",
    "hbo",
    "disney",
    "cancel",
    "renov",
    "episódio",
    "episodio",
    "cinema",
    "novela",
    "reality",
    "sitcom",
    "drama",
    "hollywood",
    "oscar",
    "emmy",
    "mangá",
    "manga",
    "animação",
    "animacao",
    "série",
    "season",
    "renewed",
    "premiere",
)

_SKIP_WORDS = (
    "eleição",
    "eleicoes",
    "bolsa de valores",
    "cotação do dólar",
    "copa do mundo de futebol",
    "campeonato brasileiro",
    "futebol",
    "grêmio",
    "gremio",
    "vasco",
    "atacante",
)

FEED_KIND_LABELS = {
    "anime": "Anime",
    "filmes-series": "Filmes e Séries",
    "tv": "TV",
}


def parse_news_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed = None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if parsed.month < 1 or parsed.month > 12:
        return None
    return parsed


def format_news_when(value: str | None) -> str:
    parsed = parse_news_datetime(value)
    if parsed is None:
        return ""
    return f"{parsed.day} {_MONTHS_PT[parsed.month - 1]} {parsed.year}"


def format_news_when_short(value: str | None) -> str:
    parsed = parse_news_datetime(value)
    if parsed is None:
        return ""
    stamp = f"{parsed.day} {_MONTHS_PT[parsed.month - 1]}"
    current_year = datetime.now(timezone.utc).year
    if parsed.year != current_year:
        return f"{stamp} {parsed.year}"
    return stamp


def news_title_key(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"\s+[-–|]\s+.*$", "", text)
    text = re.sub(r"[^a-z0-9à-ú\s]", " ", text)
    return " ".join(text.split()[:8])


def news_text_norm(text: str) -> str:
    blob = (text or "").lower()
    blob = re.sub(r"[^a-z0-9à-ú\s]", " ", blob)
    return " ".join(blob.split())


def favorite_name_needles(names: list[str], min_len: int = 4) -> list[str]:
    needles: list[str] = []
    seen: set[str] = set()
    for raw in names:
        text = (raw or "").strip()
        if not text:
            continue
        variants = [text]
        stripped = re.sub(r"\s*[\(\[]\d{4}[\)\]]\s*", " ", text).strip()
        if stripped and stripped not in variants:
            variants.append(stripped)
        headed = stripped
        if ":" in stripped:
            headed = stripped.split(":", 1)[0].strip()
        elif " – " in stripped:
            headed = stripped.split(" – ", 1)[0].strip()
        elif " - " in stripped:
            headed = stripped.split(" - ", 1)[0].strip()
        if headed and headed not in variants:
            variants.append(headed)
        for item in variants:
            needle = news_text_norm(item)
            if len(needle) < min_len or needle in seen:
                continue
            seen.add(needle)
            needles.append(needle)
    return needles


def news_matches_favorite_needles(title: str, needles: list[str]) -> bool:
    hay = news_text_norm(title)
    if not hay:
        return False
    return any(re.search(rf"(^|\s){re.escape(needle)}(\s|$)", hay) for needle in needles)


def news_work_key(title: str) -> str:
    raw = title or ""
    if ":" in raw:
        headed = news_title_key(raw.split(":", 1)[0])
        if headed:
            return headed
    return " ".join(news_title_key(raw).split()[:2])


def _field(item, name: str):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
_GENERIC_NEWS_MARKERS = (
    "gnews/logo",
    "J6_coFbogxhRI9iM864NL",
    "google_news_192",
)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
_OG_IMAGE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\']',
    re.I,
)


def _looks_image(url: str) -> bool:
    lowered = url.lower().split("?", 1)[0]
    return lowered.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")) or "image" in lowered


def _as_dicts(value) -> list[dict]:
    if not value:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _usable_image_url(url: str | None) -> str | None:
    text = unescape((url or "").strip())
    if not text or not text.startswith(("http://", "https://")):
        return None
    lowered = text.lower()
    if "favicon" in lowered or lowered.endswith(".ico") or "apple-touch-icon" in lowered:
        return None
    if any(marker in text for marker in _GENERIC_NEWS_MARKERS):
        return None
    return text


def _entry_image(entry) -> str | None:
    for media in _as_dicts(entry.get("media_content")):
        url = media.get("url")
        medium = (media.get("medium") or "").lower()
        if url and (not medium or medium == "image") and (_looks_image(url) or medium == "image"):
            found = _usable_image_url(url)
            if found:
                return found
    for media in _as_dicts(entry.get("media_thumbnail")):
        found = _usable_image_url(media.get("url"))
        if found:
            return found
    for enc in _as_dicts(entry.get("enclosures")) + _as_dicts(entry.get("links")):
        href = enc.get("href") or enc.get("url") or ""
        typ = (enc.get("type") or "").lower()
        rel = (enc.get("rel") or "").lower()
        if href and (typ.startswith("image") or rel == "enclosure" and _looks_image(href) or _looks_image(href)):
            found = _usable_image_url(href)
            if found:
                return found
    summary = entry.get("summary") or entry.get("description") or ""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, re.I)
    if match:
        return _usable_image_url(match.group(1))
    return None


_LINK_IMAGE_RE = re.compile(
    r'<link[^>]+rel=["\']image_src["\'][^>]*href=["\']([^"\']+)["\']',
    re.I,
)
_ITEMPROP_IMAGE_RE = re.compile(
    r'<meta[^>]+itemprop=["\']image["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
_LD_IMAGE_RE = re.compile(
    r'"image"\s*:\s*(?:"(https?://[^"]+)"|\{\s*"url"\s*:\s*"(https?://[^"]+)")',
    re.I,
)


def _absolutize(url: str, base_url: str = "") -> str:
    raw = unescape(url.strip())
    if raw.startswith("//"):
        return "https:" + raw
    if raw.startswith("/") and base_url:
        return urljoin(base_url, raw)
    return raw


def html_meta_image(html: str, base_url: str = "") -> str | None:
    if not html:
        return None
    candidates: list[str] = []
    for pattern in (_OG_IMAGE_RE, _OG_IMAGE_RE_ALT, _ITEMPROP_IMAGE_RE, _LINK_IMAGE_RE):
        for match in pattern.finditer(html):
            candidates.append(match.group(1))
    for match in _LD_IMAGE_RE.finditer(html):
        candidates.append(match.group(1) or match.group(2))
    for raw in candidates:
        found = _usable_image_url(_absolutize(raw, base_url))
        if found:
            return found
    return None


def inflate_http_body(raw: bytes, content_encoding: str | None = None) -> bytes:
    if not raw:
        return raw
    encoding = (content_encoding or "").lower()
    if encoding == "gzip" or raw.startswith(b"\x1f\x8b"):
        try:
            return gzip.decompress(raw)
        except (gzip.BadGzipFile, OSError, EOFError):
            return raw
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return raw
    return raw


def _http_get(url: str, timeout: int = 6) -> tuple[str, str]:
    request = urllib.request.Request(url, headers=_HTTP_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        try:
            raw = response.read(1_500_000)
        except http.client.IncompleteRead as exc:
            raw = exc.partial or b""
        raw = inflate_http_body(raw, response.headers.get("Content-Encoding"))
        charset = response.headers.get_content_charset() or "utf-8"
        return response.geturl(), raw.decode(charset, "ignore")[:900_000]


def _decode_google_news_url(article_url: str) -> str | None:
    if "news.google.com" not in (article_url or ""):
        return article_url
    try:
        _, html = _http_get(article_url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, http.client.HTTPException):
        return None
    art_id = re.search(r'data-n-a-id="([^"]+)"', html)
    timestamp = re.search(r'data-n-a-ts="([^"]+)"', html)
    signature = re.search(r'data-n-a-sg="([^"]+)"', html)
    if not (art_id and timestamp and signature):
        return None
    payload = [[
        [
            "Fbv4je",
            json.dumps(
                [
                    "garturlreq",
                    [
                        ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                        "X",
                        "X",
                        1,
                        [1, 1, 1],
                        1,
                        1,
                        None,
                        0,
                        0,
                        None,
                        0,
                    ],
                    art_id.group(1),
                    int(timestamp.group(1)),
                    signature.group(1),
                ]
            ),
            "generic",
        ]
    ]]
    body = ("f.req=" + quote(json.dumps(payload))).encode()
    request = urllib.request.Request(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je",
        data=body,
        headers={**_HTTP_HEADERS, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            text = response.read().decode("utf-8", "ignore").lstrip()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, http.client.HTTPException):
        return None
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[-1]
    try:
        outer = json.loads(text)
        inner = json.loads(outer[0][2])
    except (json.JSONDecodeError, IndexError, TypeError, KeyError):
        return None
    if not isinstance(inner, list) or len(inner) < 2 or inner[0] != "garturlres":
        return None
    resolved = inner[1]
    if isinstance(resolved, str) and resolved.startswith("http") and "news.google.com" not in resolved:
        return resolved
    return None


def resolve_article_image(article_url: str, rss_image: str | None = None) -> str | None:
    found = _usable_image_url(rss_image)
    if found:
        return found
    publisher = article_url
    if "news.google.com" in (article_url or ""):
        publisher = _decode_google_news_url(article_url) or ""
    if not publisher:
        return None
    try:
        final_url, html = _http_get(publisher)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, http.client.HTTPException):
        return None
    return html_meta_image(html, final_url)


def _attach_article_images(items: list[dict]) -> None:
    pending = [item for item in items if item.get("url") and not item.get("image_url")]
    if not pending:
        return

    def fill(item: dict) -> None:
        item["image_url"] = resolve_article_image(item["url"], item.get("image_url"))

    workers = min(8, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fill, pending))


def _entry_source(entry) -> str | None:
    source = entry.get("source")
    if isinstance(source, dict):
        title = source.get("title")
        if title:
            return title
    return None


def _is_entertainment(title: str, source: str | None) -> bool:
    blob = f"{title} {source or ''}".lower()
    if any(word in blob for word in _SKIP_WORDS):
        return False
    return any(word in blob for word in _KEEP_WORDS)


def _parse_entry(entry, feed_kind: str, require_entertainment: bool = True) -> dict | None:
    title = (entry.get("title") or "Sem título").strip()
    url = (entry.get("link") or "").strip()
    if not url:
        return None
    source = _entry_source(entry)
    blob = f"{title} {source or ''}".lower()
    if any(word in blob for word in _SKIP_WORDS):
        return None
    if require_entertainment and not _is_entertainment(title, source):
        return None
    return {
        "title": title,
        "url": url,
        "source": source,
        "published_at": entry.get("published"),
        "image_url": _entry_image(entry),
        "feed_kind": feed_kind,
    }


def diversify_news(items: list, limit: int) -> list:
    ranked = sorted(
        items,
        key=lambda item: parse_news_datetime(_field(item, "published_at")) or datetime.min,
        reverse=True,
    )
    picked: list = []
    skipped: list = []
    seen_keys: set[str] = set()
    seen_urls: set[str] = set()
    source_count: dict[str, int] = {}

    def accept(item) -> bool:
        url = (_field(item, "url") or "").strip()
        title = _field(item, "title") or ""
        key = news_title_key(title)
        work = news_work_key(title)
        source = (_field(item, "source") or "").lower()
        if not url or url in seen_urls or (key and key in seen_keys):
            return False
        if source and source_count.get(source, 0) >= 4:
            return False
        if picked and news_work_key(_field(picked[-1], "title") or "") == work and work:
            return False
        kind = _field(item, "feed_kind") or ""
        kind_run = 0
        for prev in reversed(picked):
            if (_field(prev, "feed_kind") or "") == kind:
                kind_run += 1
            else:
                break
        if kind_run >= 2:
            return False
        picked.append(item)
        seen_urls.add(url)
        if key:
            seen_keys.add(key)
        if source:
            source_count[source] = source_count.get(source, 0) + 1
        return True

    for item in ranked:
        if len(picked) >= limit:
            return picked
        if not accept(item):
            skipped.append(item)

    for item in skipped:
        if len(picked) >= limit:
            break
        url = (_field(item, "url") or "").strip()
        key = news_title_key(_field(item, "title") or "")
        if not url or url in seen_urls or (key and key in seen_keys):
            continue
        picked.append(item)
        seen_urls.add(url)
        if key:
            seen_keys.add(key)
    return picked[:limit]


def fetch_show_news(show_name: str, limit: int = 8) -> list[dict]:
    query = f'"{show_name}" série OR series OR TV'
    url = f"{NEWS_FEED}?{urlencode({'q': query, 'hl': 'pt-BR', 'gl': 'BR', 'ceid': 'BR:pt-419'})}"
    parsed = feedparser.parse(url)
    items = []
    for entry in parsed.entries[:limit]:
        source = _entry_source(entry)
        items.append(
            {
                "title": entry.get("title", "Sem título"),
                "url": entry.get("link", ""),
                "source": source,
                "published_at": entry.get("published"),
            }
        )
    return [item for item in items if item["url"]]


def _load_rss(url: str):
    try:
        request = urllib.request.Request(url, headers=_HTTP_HEADERS)
        with urllib.request.urlopen(request, timeout=6) as response:
            raw = response.read(800_000)
        return feedparser.parse(raw)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, http.client.HTTPException):
        return feedparser.parse(b"")


def _collect_topic(pair: tuple[str, str], require_entertainment: bool = True) -> list[dict]:
    feed_kind, query = pair
    url = f"{NEWS_FEED}?{urlencode({'q': query, 'hl': 'pt-BR', 'gl': 'BR', 'ceid': 'BR:pt-419'})}"
    try:
        parsed = _load_rss(url)
    except Exception:
        return []
    items: list[dict] = []
    for entry in parsed.entries[:12]:
        item = _parse_entry(entry, feed_kind, require_entertainment=require_entertainment)
        if item is None:
            continue
        items.append(item)
    return items


def fetch_named_show_news(names: list[str], limit_each: int = 8) -> list[dict]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in names[:6]:
        name = (raw or "").strip()
        if len(name) < 4 or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        query = f'"{name}" (série OR series OR temporada OR season OR trailer) when:14d'
        pairs.append(("filmes-series", query))
    if not pairs:
        return []

    def collect_safe(pair: tuple[str, str]) -> list[dict]:
        try:
            return _collect_topic(pair, require_entertainment=False)[:limit_each]
        except Exception:
            return []

    collected: list[dict] = []
    seen_urls: set[str] = set()
    with ThreadPoolExecutor(max_workers=max(1, len(pairs))) as pool:
        batches = list(pool.map(collect_safe, pairs))
    for batch in batches:
        for item in batch:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            collected.append(item)
    return collected


def fetch_general_news(limit: int = 36, resolve_images: bool = True) -> list[dict]:
    collected: list[dict] = []
    seen_urls: set[str] = set()
    def collect_safe(pair: tuple[str, str]) -> list[dict]:
        try:
            return _collect_topic(pair)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=len(TOPIC_QUERIES)) as pool:
        batches = list(pool.map(collect_safe, TOPIC_QUERIES))
    for batch in batches:
        for item in batch:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            collected.append(item)
    picked = diversify_news(collected, limit)
    if resolve_images:
        _attach_article_images(picked)
    return picked
