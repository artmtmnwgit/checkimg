"""Verify DMCA.com Protection IDs via badge status page or API key."""

import logging
import re
from typing import Any

import httpx

from app.config import get_settings
from app.services.http_json import parse_response_json

logger = logging.getLogger(__name__)
settings = get_settings()

DMCA_ID_RE = re.compile(
    r"(?:DMCA\s*(?:Protected\s*)?(?:ID|Badge|Protection)?\s*[:#]?\s*)?"
    r"([A-F0-9]{4,8}(?:-[A-F0-9]{4,8}){2,3})",
    re.I,
)
DMCA_STATUS_URL = "https://www.dmca.com/Protection/Status.aspx"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def extract_dmca_protection_id(text: str) -> str | None:
    if not text:
        return None
    m = DMCA_ID_RE.search(text)
    return m.group(1).upper() if m else None


async def verify_protection_id(protection_id: str, *, dmca_api_key: str | None = None) -> dict[str, Any]:
    """Verify DMCA.com protection badge ID."""
    pid = protection_id.strip().upper()
    result: dict[str, Any] = {
        "id": pid,
        "verified": False,
        "source": "dmca.com",
        "status_url": f"{DMCA_STATUS_URL}?ID={pid}",
        "error": None,
    }

    api_key = (dmca_api_key or settings.dmca_api_key or "").strip()

    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    settings.dmca_api_url,
                    params={"key": api_key, "id": pid},
                )
                if resp.status_code == 200:
                    data = parse_response_json(resp) or {}
                    result["verified"] = bool(data.get("valid") or data.get("status") == "protected")
                    result["api_response"] = data
                    return result
                result["error"] = f"API HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            logger.warning("DMCA API failed: %s", exc)
            result["error"] = str(exc)

    # ponytail: scrape public status page when no API key
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=BROWSER_HEADERS, follow_redirects=True) as client:
            resp = await client.get(DMCA_STATUS_URL, params={"ID": pid})
            if resp.status_code == 200:
                text = resp.text.lower()
                result["verified"] = any(
                    kw in text for kw in ("protected", "valid", "active protection", "dmca.com protection")
                ) and "invalid" not in text[:2000]
            else:
                result["error"] = f"HTTP {resp.status_code}"
    except httpx.HTTPError as exc:
        logger.warning("DMCA status page failed: %s", exc)
        result["error"] = str(exc)

    return result
