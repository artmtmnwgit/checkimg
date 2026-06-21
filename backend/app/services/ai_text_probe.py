"""Text-grounded AI probes — Perplexity/Copilot style via DuckDuckGo text search.

ponytail: no Playwright in Docker by default; DDG text probe finds pages mentioning the image URL.
Optional Playwright path when playwright is installed and AI_PLAYWRIGHT=1.
"""

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.config import get_settings
from app.services.source_types import DANGER_SITE_TYPES, classify_domain
from app.services.url_clean import clean_http_url

logger = logging.getLogger(__name__)
settings = get_settings()

URL_RE = re.compile(r"https?://[^\s\"'<>\\)]+", re.I)
STOCK_WORDS = re.compile(
    r"(shutterstock|getty\s*images|istock|adobe\s*stock|stock\s*photo|microstock|photobank|фотобанк|depositphotos)",
    re.I,
)


def _text_search_sync(query: str, max_results: int = 8) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    out: list[dict[str, str]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            out.append({"title": item.get("title") or "", "url": item.get("href") or "", "body": item.get("body") or ""})
    return out


def _extract_sources(results: list[dict[str, str]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in results:
        for raw in [row.get("url", ""), *URL_RE.findall(row.get("body", ""))]:
            cleaned = clean_http_url(raw)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            site_type = classify_domain(cleaned)
            sources.append(
                {
                    "url": cleaned,
                    "domain": urlparse(cleaned).netloc.lower().removeprefix("www."),
                    "site_type": site_type,
                    "is_stock": site_type in DANGER_SITE_TYPES,
                }
            )
    return sources[:20]


def _stock_mentions(results: list[dict[str, str]], sources: list[dict[str, Any]]) -> bool:
    if any(s.get("is_stock") for s in sources):
        return True
    blob = " ".join(f"{r.get('title','')} {r.get('body','')}" for r in results)
    return bool(STOCK_WORDS.search(blob))


async def search_text_probe(provider: str, image_url: str) -> dict[str, Any]:
    """Context search about image URL — Perplexity/Copilot substitute."""
    empty: dict[str, Any] = {
        "provider": provider,
        "method": "ddg_text_probe",
        "sources": [],
        "stock_mentions": False,
        "summary": None,
    }
    if not image_url:
        return {**empty, "error": "no url"}

    if provider == "perplexity":
        query = (
            f"Find the original source of this image: {image_url}. "
            "Is it from stock photo sites, news agencies, or social media?"
        )
    else:
        query = (
            f"Find where this image appears online: {image_url}. "
            "Is it copyrighted stock photo or public domain? List URLs."
        )

    try:
        results = await asyncio.to_thread(_text_search_sync, query)
    except Exception as exc:
        logger.warning("%s text probe failed: %s", provider, exc)
        return {**empty, "error": str(exc)}

    sources = _extract_sources(results)
    summary = results[0].get("body", "")[:400] if results else None
    return {
        **empty,
        "sources": sources,
        "stock_mentions": _stock_mentions(results, sources),
        "summary": summary,
        "result_count": len(results),
    }


async def search_perplexity_context(image_url: str) -> dict[str, Any]:
    return await search_text_probe("perplexity", image_url)


async def search_copilot_context(image_url: str) -> dict[str, Any]:
    return await search_text_probe("copilot", image_url)
