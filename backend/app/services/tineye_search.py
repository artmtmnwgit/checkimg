"""TinEye reverse image search — optional, shows first-seen dates."""

import logging
import re
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from app.config import get_settings
from app.services.source_types import DANGER_SITE_TYPES, classify_domain
from app.services.url_clean import clean_http_url

logger = logging.getLogger(__name__)
settings = get_settings()

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

MATCH_LINK_RE = re.compile(r'href="(https?://[^"]+)"[^>]*class="[^"]*match[^"]*"', re.I)
BACKLINK_RE = re.compile(r'data-backlink="(https?://[^"]+)"', re.I)
FIRST_SEEN_RE = re.compile(r"First\s+crawl(?:ed)?[^0-9]*(\d{4}-\d{2}-\d{2})", re.I)
URL_IN_HTML_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)


def _match(url: str, first_seen: str | None = None) -> dict[str, Any] | None:
    cleaned = clean_http_url(url)
    if not cleaned:
        return None
    site_type = classify_domain(cleaned)
    return {
        "url": cleaned,
        "domain": urlparse(cleaned).netloc.lower().removeprefix("www."),
        "site_type": site_type,
        "engine": "tineye",
        "is_stock": site_type in DANGER_SITE_TYPES,
        "first_seen": first_seen,
    }


def _dedupe(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for m in matches:
        u = m.get("url", "")
        if u and u not in seen:
            seen.add(u)
            out.append(m)
    return out


def _parse_tineye_html(html: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for pat in (BACKLINK_RE, MATCH_LINK_RE):
        for m in pat.finditer(html):
            row = _match(m.group(1))
            if row:
                matches.append(row)

    if not matches:
        for raw in URL_IN_HTML_RE.findall(html):
            if "tineye.com" in raw:
                continue
            row = _match(raw)
            if row:
                matches.append(row)

    dates = FIRST_SEEN_RE.findall(html)
    if dates and matches:
        matches[0]["first_seen"] = dates[0]

    return _dedupe(matches)


async def search_tineye(
    image_url: str,
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> dict[str, Any]:
    """Public TinEye search by URL (no API key) or REST API when configured."""
    empty: dict[str, Any] = {
        "engine": "tineye",
        "matches": [],
        "match_count": 0,
        "best_match_url": None,
        "best_site_type": None,
        "stock_hits": [],
        "earliest_match": None,
    }
    if not image_url:
        return {**empty, "error": "no url"}

    key = (api_key or settings.tineye_api_key or "").strip()
    secret = (api_secret or settings.tineye_api_secret or "").strip()

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=settings.ai_search_timeout_sec, headers=BROWSER_HEADERS) as client:
            if key and secret:
                resp = await client.get(
                    "https://api.tineye.com/rest/search/",
                    params={"url": image_url},
                    auth=(key, secret),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for item in (data.get("results") or {}).get("matches") or []:
                        backlink = item.get("backlinks") or []
                        url = backlink[0].get("backlink") if backlink else None
                        if url:
                            row = _match(url, item.get("first_seen"))
                            if row:
                                empty["matches"].append(row)
                else:
                    return {**empty, "error": f"api HTTP {resp.status_code}"}
            else:
                resp = await client.get(f"https://tineye.com/search?url={quote(image_url, safe='')}")
                if resp.status_code != 200:
                    return {**empty, "error": f"HTTP {resp.status_code}"}
                empty["matches"] = _parse_tineye_html(resp.text)
    except httpx.HTTPError as exc:
        logger.warning("TinEye failed: %s", exc)
        return {**empty, "error": str(exc)}

    stock = [m for m in empty["matches"] if m.get("is_stock")]
    best = stock[0] if stock else (empty["matches"][0] if empty["matches"] else None)
    dated = [m for m in empty["matches"] if m.get("first_seen")]
    dated.sort(key=lambda x: x.get("first_seen") or "9999")
    return {
        **empty,
        "matches": empty["matches"][:30],
        "match_count": len(empty["matches"]),
        "best_match_url": best.get("url") if best else None,
        "best_site_type": best.get("site_type") if best else None,
        "stock_hits": stock,
        "earliest_match": dated[0] if dated else None,
    }
