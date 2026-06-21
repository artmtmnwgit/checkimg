"""Multi-engine reverse image search — Google + Yandex in parallel."""

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.services.http_json import parse_response_json
from app.services.scan_options import EffectiveScanOptions
from app.services.source_types import DANGER_SITE_TYPES, classify_domain
from app.services.url_clean import clean_http_url
from app.services.yandex_search import search_yandex

logger = logging.getLogger(__name__)
settings = get_settings()

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _match(url: str, title: str | None, engine: str) -> dict[str, Any] | None:
    cleaned = clean_http_url(url)
    if not cleaned:
        return None
    site_type = classify_domain(cleaned)
    return {
        "url": cleaned,
        "title": title,
        "domain": urlparse(cleaned).netloc,
        "site_type": site_type,
        "engine": engine,
        "is_stock": site_type in DANGER_SITE_TYPES,
    }


def _dedupe(all_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for m in all_matches:
        u = m.get("url", "")
        if u and u not in seen:
            seen.add(u)
            out.append(m)
    return out


async def search_google_lens(image_url: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8.0, headers=BROWSER_HEADERS) as client:
            resp = await client.get("https://lens.google.com/uploadbyurl", params={"url": image_url})
            if resp.status_code != 200:
                return _google_result(matches, error=f"HTTP {resp.status_code}")
            text = resp.text
            for token in ('"link":"', '"url":"', '"thumbnailUrl":"'):
                start = 0
                while True:
                    idx = text.find(token, start)
                    if idx == -1:
                        break
                    idx += len(token)
                    end = text.find('"', idx)
                    if end == -1:
                        break
                    link = text[idx:end].encode().decode("unicode_escape")
                    if link.startswith("http") and "google." not in link:
                        m = _match(link, None, "google_lens")
                        if m:
                            matches.append(m)
                    start = end + 1
    except httpx.HTTPError as exc:
        logger.warning("Google Lens failed: %s", exc)
        return _google_result(matches, error=str(exc))

    return _google_result(_dedupe(matches))


async def search_google_serpapi(image_url: str, *, serpapi_key: str | None = None) -> dict[str, Any]:
    key = (serpapi_key or settings.serpapi_key or "").strip()
    if not key:
        return _google_result([], error="no serpapi key")
    matches: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://serpapi.com/search.json",
                params={"engine": "google_lens", "url": image_url, "api_key": key},
            )
            resp.raise_for_status()
            payload = parse_response_json(resp) or {}
            for item in payload.get("visual_matches", []) or []:
                link = item.get("link") or item.get("source")
                if link and link.startswith("http"):
                    m = _match(link, item.get("title"), "serpapi")
                    if m:
                        matches.append(m)
    except httpx.HTTPError as exc:
        logger.warning("SerpAPI failed: %s", exc)
        return _google_result(matches, error=str(exc))
    except Exception as exc:
        logger.warning("SerpAPI parse failed: %s", exc)
        return _google_result(matches, error=str(exc))
    return _google_result(_dedupe(matches))


def _google_result(matches: list[dict[str, Any]], error: str | None = None) -> dict[str, Any]:
    stock = [m for m in matches if m.get("is_stock")]
    best = stock[0] if stock else (matches[0] if matches else None)
    return {
        "engine": "google",
        "matches": matches[:30],
        "match_count": len(matches),
        "best_match_url": best.get("url") if best else None,
        "title": best.get("title") if best else None,
        "best_site_type": best.get("site_type") if best else None,
        "stock_hits": stock,
        "error": error,
    }


async def _search_google(image_url: str, *, serpapi_key: str | None = None) -> dict[str, Any]:
    key = (serpapi_key or settings.serpapi_key or "").strip()
    if settings.reverse_search_provider == "serpapi" and key:
        result = await search_google_serpapi(image_url, serpapi_key=key)
        if result["match_count"]:
            return result
    result = await search_google_lens(image_url)
    if not result["match_count"] and key:
        serp = await search_google_serpapi(image_url, serpapi_key=key)
        if serp["match_count"]:
            return serp
    return result


async def multi_engine_reverse_search(
    image_url: str,
    opts: EffectiveScanOptions | None = None,
    *,
    serpapi_key: str | None = None,
) -> dict[str, Any]:
    """Parallel Google + Yandex search with fused summary."""
    opts = opts or EffectiveScanOptions.from_settings()
    tasks: list[tuple[str, Any]] = []
    if opts.google_search:
        tasks.append(("google", _search_google(image_url, serpapi_key=serpapi_key)))
    if opts.yandex_search:
        tasks.append(("yandex", search_yandex(image_url)))

    google: dict[str, Any] = _google_result([])
    yandex: dict[str, Any] = {
        "engine": "yandex",
        "matches": [],
        "match_count": 0,
        "best_match_url": None,
        "best_site_type": None,
        "text_snippet": None,
        "stock_hits": [],
        "buy_pattern": False,
        "error": "disabled" if not opts.yandex_search else None,
    }

    if not tasks:
        return {
            "google": {**google, "error": "disabled"},
            "yandex": yandex,
            "matches": [],
            "match_count": 0,
            "stock_hits": [],
            "reverse_search": {"google": google, "yandex": yandex, "match_count": 0},
        }

    results = await asyncio.gather(*(t[1] for t in tasks), return_exceptions=True)

    for (engine, _), res in zip(tasks, results):
        if isinstance(res, Exception):
            logger.warning("engine search error: %s", res)
            continue
        if engine == "google":
            google = res
        else:
            yandex = res

    all_matches = _dedupe((google.get("matches") or []) + (yandex.get("matches") or []))
    stock_hits = [m for m in all_matches if m.get("is_stock")]

    return {
        "google": google,
        "yandex": yandex,
        "matches": all_matches,
        "match_count": len(all_matches),
        "stock_hits": stock_hits,
        # legacy alias for old frontend paths
        "reverse_search": {"google": google, "yandex": yandex, "match_count": len(all_matches)},
    }


# backward-compatible alias
async def reverse_image_search(image_url: str) -> dict[str, Any]:
    return await multi_engine_reverse_search(image_url)
