"""Clean scraped URLs — strip glued labels like 'Instagram:' from paths."""

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Labels scraped from adjacent SERP text (incl. Turkish İ)
GLUED_LABEL_RE = re.compile(
    r"(?:Instagram|İnstagram|Instagrarn|Facebook|Twitter|Youtube|YouTube|"
    r"Telegram|LinkedIn|Pinterest|TikTok|WhatsApp|VKontakte|VK)[:.]?$",
    re.I,
)

TRAILING_JUNK_RE = re.compile(
    r"(?:&(?:amp;)?(?:quot|#39|lt|gt|apos);?|&quot;|&#39;)+$",
    re.I,
)

HTTP_URL_RE = re.compile(
    r"https?://"
    r"(?:www\.)?"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
    r"(?::\d+)?"
    r"(?:/[^\s\"'<>\\]*)?"
    r"(?:\?[^\s\"'<>\\#]*)?",
    re.I,
)


def _strip_trailing_junk(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = TRAILING_JUNK_RE.sub("", text)
    return text


def _strip_labels(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = GLUED_LABEL_RE.sub("", text)
        text = text.rstrip("/.,;:)\\")
    return text


def clean_http_url(raw: str) -> str | None:
    """Return a normalized http(s) URL or None if unparseable."""
    if not raw:
        return None
    raw = _strip_trailing_junk(raw.strip().strip("'\""))
    m = HTTP_URL_RE.match(raw) or HTTP_URL_RE.search(raw)
    if not m:
        return None

    url = _strip_trailing_junk(_strip_labels(m.group(0)))
    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        return None

    path = _strip_labels(parsed.path)
    query = _strip_labels(parsed.query) if parsed.query else ""
    # drop empty query pairs broken by cleanup
    if query:
        pairs = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if k]
        query = urlencode(pairs) if pairs else ""

    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    clean = urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))
    return clean if clean.startswith("http") else None


def canonical_page_url(url: str) -> str:
    """Normalize page URL for dedup: lower host, homepage slash, no trailing slash elsewhere."""
    cleaned = clean_http_url(url) or url.strip()
    parsed = urlparse(cleaned)
    if not parsed.netloc:
        return cleaned
    path = (parsed.path or "").rstrip("/") or "/"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def is_self_image_match(source_url: str, match_url: str) -> bool:
    """True when reverse-search hit is the same asset we submitted (Yandex often returns the source URL)."""
    src = clean_http_url(source_url)
    dst = clean_http_url(match_url)
    if not src or not dst:
        return False
    if src == dst:
        return True
    sp, mp = urlparse(src), urlparse(dst)
    host = lambda p: p.netloc.lower().removeprefix("www.")
    if host(sp) != host(mp):
        return False
    # ponytail: same filename on same host — Bitrix resize_cache vs /upload/iblock/…/file.png
    name = sp.path.rsplit("/", 1)[-1].lower()
    if not name or name != mp.path.rsplit("/", 1)[-1].lower():
        return False
    return name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"))
