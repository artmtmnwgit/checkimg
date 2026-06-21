"""Site-level DMCA signal collection during crawl."""

import asyncio
import logging
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from app.services.dmca_crawl import (
    dmca_extra_paths,
    extract_dmca_page_signals,
    merge_dmca_signals,
    parse_robots_humans,
)
from app.services.sanitize import sanitize_json

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=6)


async def _fetch_text(session: aiohttp.ClientSession, url: str, limit: int = 300_000) -> tuple[str, str | None]:
    try:
        async with session.get(url, timeout=_FETCH_TIMEOUT) as resp:
            if resp.status != 200:
                return url, None
            if url.endswith(".ico"):
                return url, None
            raw = await resp.content.read(limit)
            return url, raw.decode(errors="ignore")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return url, None


async def crawl_site_dmca_signals(session: aiohttp.ClientSession, root_url: str) -> dict[str, Any]:
    """Collect DMCA signals from homepage, policy pages, robots/humans.txt."""
    acc: dict[str, Any] = {
        "footer_text_hits": [],
        "meta_tags": [],
        "dmca_links": [],
        "copyright_notices": [],
        "has_dmca_badge": False,
        "policy_pages": [],
        "robots": None,
        "humans": None,
        "favicon_url": None,
    }

    parsed = urlparse(root_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    paths = [root_url] + [
        u for u in dmca_extra_paths(root_url) if u.rstrip("/") != root_url.rstrip("/") and not u.endswith(".ico")
    ]
    results = await asyncio.gather(*[_fetch_text(session, u) for u in paths])

    root_html: str | None = None
    for path_url, text in results:
        if not text:
            continue
        if path_url.rstrip("/") == root_url.rstrip("/"):
            root_html = text
            merge_dmca_signals(acc, extract_dmca_page_signals(text, path_url))
        elif path_url.endswith("robots.txt"):
            acc["robots"] = parse_robots_humans(text, "robots")
        elif path_url.endswith("humans.txt"):
            acc["humans"] = parse_robots_humans(text, "humans")
        elif len(text) > 200:
            sig = extract_dmca_page_signals(text, path_url)
            merge_dmca_signals(acc, sig)
            acc["policy_pages"].append({"url": path_url, "signals": sig})

    if not acc["favicon_url"] and root_html:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(root_html)
        for node in tree.css("link[rel*='icon']"):
            href = node.attributes.get("href")
            if href:
                acc["favicon_url"] = urljoin(base, href)
                break

    return sanitize_json(acc)
