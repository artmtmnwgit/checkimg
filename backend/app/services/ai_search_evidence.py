"""Parallel AI search orchestration (1.2.7) + signal derivation."""

import asyncio
import logging
from typing import Any

from app.config import get_settings
from app.services.ai_text_probe import search_copilot_context, search_perplexity_context
from app.services.scan_options import EffectiveScanOptions, ScanSecrets
from app.services.duckduckgo_search import search_duckduckgo_images
from app.services.gemini_analysis import analyze_gemini
from app.services.huggingface_analysis import analyze_huggingface
from app.services.tineye_search import search_tineye

logger = logging.getLogger(__name__)
settings = get_settings()


def _derive_signals(evidence: dict[str, Any]) -> dict[str, Any]:
    gemini = evidence.get("gemini") or {}
    hf = evidence.get("huggingface") or {}
    ddg = evidence.get("duckduckgo") or {}
    perplexity = evidence.get("perplexity") or {}
    copilot = evidence.get("copilot") or {}
    tineye = evidence.get("tineye") or {}

    gemini_stock = gemini.get("source_type") in ("stock", "microstock") or gemini.get("copyrighted")
    hf_wm = (hf.get("watermark") or {}).get("detected")
    hf_ai = (hf.get("ai_generated") or {}).get("detected")
    stock_hits = sum(
        1
        for key in ("tineye", "duckduckgo")
        for m in (evidence.get(key) or {}).get("stock_hits") or []
    )

    stock_confirmations = sum(
        [
            bool(gemini_stock),
            bool(hf_wm),
            bool(perplexity.get("stock_mentions")),
            bool(copilot.get("stock_mentions")),
            stock_hits > 0,
        ]
    )

    return {
        "stock_photo_confirmed": stock_confirmations >= 2 or bool(perplexity.get("stock_mentions")),
        "ai_generated": bool(hf_ai) or gemini.get("source_type") == "ai_generated",
        "wide_distribution": ddg.get("match_count", 0) > 10,
        "gemini_stock": bool(gemini_stock),
        "stock_confirmations": stock_confirmations,
        "tineye_earliest": (tineye.get("earliest_match") or {}).get("url"),
    }


async def gather_ai_search_evidence(
    image_url: str,
    local_path: str,
    caches: dict | None = None,
    opts: EffectiveScanOptions | None = None,
    secrets: ScanSecrets | None = None,
) -> dict[str, Any]:
    """Run enabled AI providers in parallel; never raises."""
    opts = opts or EffectiveScanOptions.from_settings()
    secrets = secrets or ScanSecrets.from_settings()
    if not opts.ai_search:
        return {}

    caches = caches or {}
    ddg_cache = caches.setdefault("ddg_url", {})

    tasks: list[Any] = []
    keys: list[str] = []

    def _add(key: str, coro):
        tasks.append(coro)
        keys.append(key)

    if opts.tineye:
        _add(
            "tineye",
            search_tineye(
                image_url,
                api_key=secrets.tineye_api_key,
                api_secret=secrets.tineye_api_secret,
            ),
        )
    if opts.duckduckgo:
        _add("duckduckgo", search_duckduckgo_images(image_url, ddg_cache))
    if opts.gemini:
        _add("gemini", analyze_gemini(local_path, image_url, api_key=secrets.gemini_api_key))
    if opts.huggingface:
        _add("huggingface", analyze_huggingface(local_path, api_token=secrets.huggingface_api_token))
    if opts.perplexity:
        _add("perplexity", search_perplexity_context(image_url))
    if opts.copilot:
        _add("copilot", search_copilot_context(image_url))

    if not tasks:
        return {}

    results = await asyncio.gather(*tasks, return_exceptions=True)
    evidence: dict[str, Any] = {}
    for key, res in zip(keys, results):
        if isinstance(res, Exception):
            logger.warning("ai search %s failed: %s", key, res)
            evidence[key] = {"error": str(res)}
        else:
            evidence[key] = res

    evidence["signals"] = _derive_signals(evidence)
    return evidence


def merge_ai_into_fusion(fusion: dict, ai: dict) -> dict:
    """Attach TinEye/DDG matches to fusion summary for verify + scoring."""
    if not ai:
        return fusion

    extra: list[dict] = []
    for key in ("tineye", "duckduckgo"):
        block = ai.get(key) or {}
        fusion[key] = block
        extra.extend(block.get("matches") or [])

    if not extra:
        return fusion

    seen = {m.get("url") for m in fusion.get("matches") or [] if m.get("url")}
    merged = list(fusion.get("matches") or [])
    for m in extra:
        u = m.get("url")
        if u and u not in seen:
            seen.add(u)
            merged.append(m)

    stock = [m for m in merged if m.get("is_stock")]
    fusion["matches"] = merged
    fusion["match_count"] = len(merged)
    fusion["stock_hits"] = stock
    return fusion
