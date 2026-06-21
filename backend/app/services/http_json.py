"""Safe JSON parsing for external HTTP responses."""

from __future__ import annotations

import json
from typing import Any

import httpx


def parse_response_json(resp: httpx.Response) -> Any | None:
    text = (resp.text or "").strip()
    if not text:
        return None
    # Google/Lumen anti-XSSI prefix
    if text.startswith(")]}'"):
        text = text[4:].lstrip()
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
