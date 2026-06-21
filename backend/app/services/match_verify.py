"""Verify reverse-search hits by downloading and comparing pixels."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.services.scan_options import EffectiveScanOptions
from app.services.image_similarity import compare_image_bytes

logger = logging.getLogger(__name__)
settings = get_settings()

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}


def _looks_like_image_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in IMAGE_EXT) or "/image" in path or "format=" in url.lower()


async def _fetch_image_bytes(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        resp = await client.get(url, timeout=settings.match_verify_timeout_sec)
        if resp.status_code != 200:
            return None
        data = resp.content
        if len(data) < 200 or len(data) > settings.match_verify_max_bytes:
            return None
        ctype = resp.headers.get("content-type", "").lower()
        if ctype and "image" not in ctype and "octet-stream" not in ctype:
            return None
        return data
    except httpx.HTTPError:
        return None


async def _score_one(
    client: httpx.AsyncClient,
    local_path: str,
    match: dict[str, Any],
) -> dict[str, Any]:
    out = dict(match)
    url = match.get("url") or ""
    out["match_kind"] = "unverified"
    out["similarity_score"] = None
    out["verify_note"] = None

    if not url or not _looks_like_image_url(url):
        out["verify_note"] = "page_url_not_image"
        return out

    data = await _fetch_image_bytes(client, url)
    if not data:
        out["verify_note"] = "preview_unavailable"
        return out

    cmp = compare_image_bytes(local_path, data)
    if not cmp:
        out["verify_note"] = "compare_failed"
        return out

    out.update(cmp)
    return out


def _pick_best(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = sorted(
        matches,
        key=lambda m: (
            {"exact": 3, "similar": 2, "unverified": 1, "weak": 0}.get(m.get("match_kind", ""), 0),
            m.get("similarity_score") or 0,
        ),
        reverse=True,
    )
    return ranked[0] if ranked else None


def _apply_engine_result(eng: dict[str, Any], scored: list[dict[str, Any]]) -> dict[str, Any]:
    if not eng:
        return eng
    by_url = {m.get("url"): m for m in scored if m.get("url")}
    new_matches = []
    for m in eng.get("matches") or []:
        u = m.get("url")
        merged = by_url.get(u, {**m, "match_kind": "unverified"})
        if merged.get("match_kind") != "weak":
            new_matches.append(merged)
    eng = dict(eng)
    eng["matches"] = new_matches

    best = _pick_best(new_matches)
    if best:
        eng["best_match_url"] = best.get("url")
        eng["best_site_type"] = best.get("site_type")
        eng["title"] = best.get("title")
        eng["best_match_kind"] = best.get("match_kind")
        eng["best_similarity_score"] = best.get("similarity_score")
    else:
        eng["best_match_url"] = None
        eng["best_match_kind"] = None
        eng["best_similarity_score"] = None

    eng["exact_count"] = sum(1 for m in new_matches if m.get("match_kind") == "exact")
    eng["similar_count"] = sum(1 for m in new_matches if m.get("match_kind") == "similar")
    return eng


async def verify_fusion_matches(
    local_path: str,
    fusion: dict[str, Any],
    opts: EffectiveScanOptions | None = None,
) -> dict[str, Any]:
    """Annotate fusion with visual similarity; filter weak lookalikes."""
    opts = opts or EffectiveScanOptions.from_settings()
    if not opts.match_verify or not local_path:
        return fusion

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for eng_key in ("google", "yandex"):
        eng = fusion.get(eng_key) or {}
        for m in (eng.get("matches") or [])[: settings.match_verify_top_n]:
            u = m.get("url")
            if u and u not in seen:
                seen.add(u)
                candidates.append(m)

    if not candidates:
        return fusion

    sem = asyncio.Semaphore(settings.match_verify_concurrency)

    async def _run(m: dict) -> dict:
        async with sem:
            async with httpx.AsyncClient(follow_redirects=True, headers=BROWSER_HEADERS) as client:
                return await _score_one(client, local_path, m)

    scored = list(await asyncio.gather(*[_run(m) for m in candidates]))
    by_url = {m["url"]: m for m in scored if m.get("url")}

    fusion = dict(fusion)
    fusion["google"] = _apply_engine_result(fusion.get("google") or {}, scored)
    fusion["yandex"] = _apply_engine_result(fusion.get("yandex") or {}, scored)

    all_strong = [m for m in scored if m.get("match_kind") in ("exact", "similar")]
    fusion["exact_match_count"] = sum(1 for m in scored if m.get("match_kind") == "exact")
    fusion["similar_match_count"] = sum(1 for m in scored if m.get("match_kind") == "similar")
    fusion["weak_match_count"] = sum(1 for m in scored if m.get("match_kind") == "weak")
    fusion["match_count"] = len(all_strong) + sum(
        1 for m in scored if m.get("match_kind") == "unverified"
    )
    fusion["stock_hits"] = [
        by_url[m["url"]]
        for m in (fusion.get("stock_hits") or [])
        if m.get("url") in by_url and by_url[m["url"]].get("match_kind") != "weak"
    ]
    fusion["best_verified"] = _pick_best(all_strong)
    return fusion
