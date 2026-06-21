"""Yandex Images reverse search by URL."""

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.source_types import DANGER_SITE_TYPES, classify_domain
from app.services.url_clean import clean_http_url

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BUY_PATTERN = re.compile(
    r"(купить\s+фото|купить\s+изображение|stock\s*photo|shutterstock|getty\s*images|"
    r"лицензи|photobank|фотобанк|скачать\s+за)",
    re.I,
)
URL_RE = re.compile(
    r"https?://(?:www\.)?[a-z0-9][-a-z0-9.]*(?::\d+)?(?:/[^\s\"'<>\\]*)?(?:\?[^\s\"'<>\\#]*)?",
    re.I,
)
ORIGIN_URL_RE = re.compile(r'"origin"\s*:\s*\{\s*"url"\s*:\s*"(https?://[^"]+)"')
TITLE_SNIP_RE = re.compile(r'"snippet"\s*:\s*\{\s*"text"\s*:\s*"([^"]{5,200})"')


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _add_match(matches: list[dict[str, Any]], url: str, title: str | None = None) -> None:
    cleaned = clean_http_url(url)
    if not cleaned:
        return
    site_type = classify_domain(cleaned)
    matches.append(
        {
            "url": cleaned,
            "title": title,
            "domain": _domain(cleaned),
            "site_type": site_type,
            "engine": "yandex",
            "is_stock": site_type in DANGER_SITE_TYPES,
        }
    )


def _dedupe_matches(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for m in raw:
        url = m.get("url") or ""
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        out.append(m)
    return out


def _parse_yandex_html(html: str) -> tuple[list[dict[str, Any]], str | None]:
    matches: list[dict[str, Any]] = []
    snippet: str | None = None

    for m in ORIGIN_URL_RE.finditer(html):
        url = m.group(1).encode().decode("unicode_escape")
        _add_match(matches, url)

    for m in TITLE_SNIP_RE.finditer(html):
        text = m.group(1).encode().decode("unicode_escape")
        if not snippet:
            snippet = text

    # ponytail: generic URL harvest from SERP JSON blobs embedded in page
    for block in re.findall(r'"items"\s*:\s*(\[[\s\S]{0,80000}?\])', html):
        try:
            items = json.loads(block)
        except json.JSONDecodeError:
            continue
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            url = (item.get("origin") or {}).get("url") or item.get("url") or ""
            title = (item.get("snippet") or {}).get("text") or item.get("title") or ""
            if url.startswith("http"):
                _add_match(matches, url, title)
                if title and not snippet:
                    snippet = title

    if len(matches) < 3:
        for url in URL_RE.findall(html):
            url = url.rstrip("\\,")
            if "yandex." in url or "yastatic." in url:
                continue
            if not any(url.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
                if classify_domain(clean_http_url(url) or url) == "other":
                    continue
            _add_match(matches, url)

    return _dedupe_matches(matches), snippet


def _empty_result(error: str | None = None) -> dict[str, Any]:
    return {
        "engine": "yandex",
        "matches": [],
        "match_count": 0,
        "best_match_url": None,
        "best_site_type": None,
        "text_snippet": None,
        "stock_hits": [],
        "buy_pattern": False,
        "error": error,
    }


async def search_yandex(image_url: str) -> dict[str, Any]:
    """Search Yandex Images by image URL."""
    search_url = "https://yandex.ru/images/search"
    params = {"rpt": "imageview", "url": image_url}

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, headers=BROWSER_HEADERS) as client:
            resp = await client.get(search_url, params=params)
            if resp.status_code != 200:
                return _empty_result(f"HTTP {resp.status_code}")

            html = resp.text
            matches, snippet = _parse_yandex_html(html)
            buy_pattern = bool(BUY_PATTERN.search(html) or (snippet and BUY_PATTERN.search(snippet)))

            stock_hits = [m for m in matches if m.get("is_stock")]
            best = stock_hits[0] if stock_hits else (matches[0] if matches else None)

            return {
                "engine": "yandex",
                "matches": matches[:30],
                "match_count": len(matches),
                "best_match_url": best.get("url") if best else None,
                "best_site_type": best.get("site_type") if best else None,
                "text_snippet": snippet,
                "stock_hits": stock_hits,
                "buy_pattern": buy_pattern,
                "search_page": str(resp.url),
                "error": None,
            }
    except httpx.HTTPError as exc:
        logger.warning("Yandex search failed: %s", exc)
        return _empty_result(str(exc))
