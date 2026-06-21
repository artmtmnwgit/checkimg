"""Domain-level DMCA checks: Lumen Database, Google Transparency, pirate blacklist."""

import asyncio
import logging
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from app.config import get_settings
from app.services.http_json import parse_response_json
from app.services.pirate_blacklist import domain_in_blacklist

logger = logging.getLogger(__name__)
settings = get_settings()

GOOGLE_TR_PAGE = "https://transparencyreport.google.com/copyright/domains/{host}"
LUMEN_SEARCH = "https://lumendatabase.org/notices/search.json"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _timeout() -> float:
    return settings.dmca_external_timeout_sec


async def check_pirate_blacklist(url: str) -> dict[str, Any]:
    host = _host(url)
    listed = domain_in_blacklist(host) or domain_in_blacklist(url)
    return {"listed": listed, "domain": host}


async def check_lumen(url: str, *, terms: list[str] | None = None) -> dict[str, Any]:
    """Search Lumen Database — one term per call by default (domain only)."""
    host = _host(url)
    search_terms = terms if terms is not None else [host]
    result: dict[str, Any] = {
        "found": False,
        "infringing_match": False,
        "notice_count": 0,
        "notices": [],
        "error": None,
        "checked": False,
    }
    seen_ids: set[int] = set()

    try:
        async with httpx.AsyncClient(timeout=_timeout(), headers=BROWSER_HEADERS, follow_redirects=True) as client:
            for term in search_terms:
                try:
                    resp = await client.get(LUMEN_SEARCH, params={"term": term, "sort_by": "date_received desc"})
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    result["error"] = "сервис недоступен из контейнера"
                    logger.warning("Lumen unreachable: %s", exc)
                    return result

                if resp.status_code != 200:
                    result["error"] = f"HTTP {resp.status_code}"
                    continue

                result["checked"] = True
                if resp.text.lstrip().startswith("<"):
                    result["error"] = "сервис недоступен (HTML вместо JSON)"
                    continue

                data = parse_response_json(resp)
                if not isinstance(data, dict):
                    result["error"] = "invalid JSON response"
                    continue

                result["error"] = None
                for notice in data.get("notices") or []:
                    nid = notice.get("id")
                    if nid in seen_ids:
                        continue
                    seen_ids.add(nid)
                    title = notice.get("title") or ""
                    body = notice.get("body") or ""
                    infringing = url in body or host in body or term in body
                    result["notices"].append(
                        {
                            "id": nid,
                            "title": title[:200],
                            "date_received": notice.get("date_received"),
                            "infringing_match": infringing,
                        }
                    )
                    if infringing:
                        result["infringing_match"] = True
                if data.get("meta", {}).get("total_entries", 0) > 0:
                    result["found"] = True
                result["notice_count"] = len(result["notices"])
                if result["infringing_match"]:
                    break
    except httpx.HTTPError as exc:
        logger.warning("Lumen check failed: %s", exc)
        result["error"] = str(exc)

    return result


async def check_google_transparency(domain: str) -> dict[str, Any]:
    host = _host(domain) if "://" in domain else domain.lower().removeprefix("www.")
    result: dict[str, Any] = {
        "domain": host,
        "checked": False,
        "removal_count": None,
        "has_removals": False,
        "error": None,
    }
    page_url = GOOGLE_TR_PAGE.format(host=quote(host))
    try:
        async with httpx.AsyncClient(timeout=_timeout(), headers=BROWSER_HEADERS, follow_redirects=True) as client:
            page = await client.get(page_url)
            if page.status_code == 200:
                result["checked"] = True
                # ponytail: SPA shell — removal counts load client-side only
                result["has_removals"] = False
                result["detail"] = "страница доступна; число удалений — только на сайте Google"
                return result
            result["error"] = f"HTTP {page.status_code}"
    except httpx.HTTPError as exc:
        logger.warning("Google Transparency check failed: %s", exc)
        result["error"] = str(exc)

    return result


async def check_site_domain_dmca(site_url: str) -> dict[str, Any]:
    """Run domain-level checks once per scan (not per image)."""
    host = _host(site_url)
    blacklist, google_tr, lumen = await asyncio.gather(
        check_pirate_blacklist(site_url),
        check_google_transparency(host),
        check_lumen(site_url, terms=[host]),
    )
    return {
        "pirate_blacklist": blacklist,
        "lumen": lumen,
        "google_transparency": google_tr,
    }
