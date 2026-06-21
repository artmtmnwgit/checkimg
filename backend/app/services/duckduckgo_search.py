"""DuckDuckGo search — text fallback when image API is rate-limited."""

import asyncio
import logging
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import get_settings
from app.services.source_types import DANGER_SITE_TYPES, classify_domain
from app.services.url_clean import clean_http_url

logger = logging.getLogger(__name__)
settings = get_settings()

_ddg_lock = threading.Lock()
URL_RE = re.compile(r"https?://[^\s\"'<>\\)]+", re.I)


def _match(url: str, title: str | None = None) -> dict[str, Any] | None:
    cleaned = clean_http_url(url)
    if not cleaned:
        return None
    site_type = classify_domain(cleaned)
    return {
        "url": cleaned,
        "title": title,
        "domain": urlparse(cleaned).netloc.lower().removeprefix("www."),
        "site_type": site_type,
        "engine": "duckduckgo",
        "is_stock": site_type in DANGER_SITE_TYPES,
    }


def _text_search(query: str, max_results: int) -> list[dict[str, Any]]:
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    matches: list[dict[str, Any]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            href = item.get("href") or ""
            title = item.get("title")
            body = item.get("body") or ""
            for raw in [href, *URL_RE.findall(body)]:
                row = _match(raw, title)
                if row:
                    matches.append(row)
    return matches


def _images_search(query: str, max_results: int) -> list[dict[str, Any]]:
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    matches: list[dict[str, Any]] = []
    with DDGS() as ddgs:
        for item in ddgs.images(keywords=query, max_results=max_results):
            url = item.get("image") or item.get("url") or item.get("thumbnail")
            if not url:
                continue
            row = _match(url, item.get("title"))
            if row:
                matches.append(row)
    return matches


def _search_sync(image_url: str, max_results: int = 8) -> tuple[list[dict[str, Any]], str | None]:
    """Returns (matches, method_or_error)."""
    parsed = urlparse(image_url)
    host = parsed.netloc
    path = parsed.path
    name = Path(path).name
    queries = [
        f'"{image_url}"',
        f"{host} {name}".strip() if name else host,
    ]
    last_err: str | None = None

    with _ddg_lock:
        for query in queries:
            try:
                raw = _images_search(query, max_results)
                if raw:
                    return raw, "images"
            except Exception as exc:
                logger.debug("DDG images failed (%s): %s", query[:40], exc)
                last_err = str(exc)

        for query in queries:
            try:
                raw = _text_search(query, max_results)
                if raw:
                    return raw, "text"
            except Exception as exc:
                logger.debug("DDG text failed (%s): %s", query[:40], exc)
                last_err = str(exc)

        return [], last_err or "no results"


async def search_duckduckgo_images(image_url: str, cache: dict | None = None) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "engine": "duckduckgo",
        "matches": [],
        "match_count": 0,
        "best_match_url": None,
        "best_site_type": None,
        "stock_hits": [],
    }
    if not image_url:
        return {**empty, "error": "no url"}

    if cache is not None and image_url in cache:
        return cache[image_url]

    try:
        raw, meta = await asyncio.to_thread(_search_sync, image_url)
    except Exception as exc:
        logger.warning("DuckDuckGo failed: %s", exc)
        result = {**empty, "error": str(exc)}
        if cache is not None:
            cache[image_url] = result
        return result

    seen: set[str] = set()
    matches: list[dict[str, Any]] = []
    for m in raw:
        u = m.get("url", "")
        if u not in seen:
            seen.add(u)
            matches.append(m)

    stock = [m for m in matches if m.get("is_stock")]
    best = stock[0] if stock else (matches[0] if matches else None)
    result = {
        **empty,
        "matches": matches[:30],
        "match_count": len(matches),
        "best_match_url": best.get("url") if best else None,
        "best_site_type": best.get("site_type") if best else None,
        "stock_hits": stock,
        "method": meta if meta in ("images", "text") else None,
    }
    if meta not in ("images", "text") and not matches:
        result["error"] = meta

    if cache is not None:
        cache[image_url] = result
    return result
