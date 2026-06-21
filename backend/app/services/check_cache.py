"""Reuse image check evidence by content hash + scan options (Redis + per-scan memory)."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import redis

from app.config import get_settings
from app.services.metadata import extract_exif
from app.services.scan_options import SCAN_TOGGLES, EffectiveScanOptions

logger = logging.getLogger(__name__)
_PREFIX = "checkimg:ev:"


def options_fingerprint(opts: EffectiveScanOptions) -> str:
    parts = tuple(getattr(opts, k) for k in SCAN_TOGGLES)
    return hashlib.sha256(repr(parts).encode()).hexdigest()[:16]


def _cache_key(file_hash: str, opts: EffectiveScanOptions) -> str:
    return f"{_PREFIX}{file_hash}:{options_fingerprint(opts)}"


def _scan_mem_key(file_hash: str, opts: EffectiveScanOptions) -> str:
    return f"{file_hash}:{options_fingerprint(opts)}"


def _redis():
    return redis.from_url(get_settings().redis_url, decode_responses=True)


def _prepare_for_storage(bundle: dict[str, Any]) -> dict[str, Any]:
    dmca = dict(bundle.get("dmca") or {})
    dmca.pop("site_signals", None)
    return {
        "fusion": bundle.get("fusion") or {},
        "exif": bundle.get("exif") or {},
        "wm": bundle.get("wm") or {},
        "dmca": dmca,
        "ai": bundle.get("ai") or {},
    }


def get_in_scan_cache(ctx: dict, file_hash: str, opts: EffectiveScanOptions) -> dict[str, Any] | None:
    if not file_hash:
        return None
    return ctx["caches"].setdefault("evidence_hash", {}).get(_scan_mem_key(file_hash, opts))


def set_in_scan_cache(ctx: dict, file_hash: str, opts: EffectiveScanOptions, bundle: dict[str, Any]) -> None:
    if not file_hash:
        return
    ctx["caches"].setdefault("evidence_hash", {})[_scan_mem_key(file_hash, opts)] = _prepare_for_storage(bundle)


def get_cached_evidence(file_hash: str, opts: EffectiveScanOptions) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.check_cache_enabled or not file_hash:
        return None
    try:
        raw = _redis().get(_cache_key(file_hash, opts))
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("check cache get: %s", exc)
        return None


def set_cached_evidence(file_hash: str, opts: EffectiveScanOptions, bundle: dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.check_cache_enabled or not file_hash:
        return
    payload = _prepare_for_storage(bundle)
    try:
        _redis().setex(
            _cache_key(file_hash, opts),
            settings.check_cache_ttl_sec,
            json.dumps(payload, default=str),
        )
    except Exception as exc:
        logger.debug("check cache set: %s", exc)


def unpack_cached_bundle(
    bundle: dict[str, Any],
    local_path: str,
    site_domain: str,
    site_signals: dict | None,
) -> tuple[dict, dict, dict, dict, dict]:
    # ponytail: re-read EXIF locally (cheap); network evidence comes from cache
    exif = extract_exif(local_path, site_domain)
    dmca = dict(bundle.get("dmca") or {})
    if site_signals:
        dmca["site_signals"] = site_signals
    return (
        bundle.get("fusion") or {},
        exif,
        bundle.get("wm") or {},
        dmca,
        bundle.get("ai") or {},
    )


def _self_check() -> None:
    opts = EffectiveScanOptions(
        google_search=True,
        yandex_search=False,
        match_verify=False,
        dmca_checks=True,
        dmca_lumen_per_image=False,
        ai_search=False,
        duckduckgo=False,
        huggingface=False,
        gemini=False,
        tineye=False,
        perplexity=False,
        copilot=False,
    )
    fp = options_fingerprint(opts)
    assert len(fp) == 16
    stored = _prepare_for_storage({"dmca": {"site_signals": {"x": 1}, "lumen": {}}, "fusion": {}})
    assert "site_signals" not in stored["dmca"]


if __name__ == "__main__":
    _self_check()
    print("check_cache self-check OK")
