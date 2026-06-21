"""Hugging Face Inference API — watermark + AI-generated detection."""

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.services.watermark import detect_watermark

logger = logging.getLogger(__name__)
settings = get_settings()

WATERMARK_MODEL = "Luke27/watermark-detection"
AI_MODEL = "umm-maybe/AI-image-detector"
# ponytail: api-inference.huggingface.co has no DNS in many Docker setups — use router
HF_URL = "https://router.huggingface.co/hf-inference/models/{model}"


def _score_label(result: Any, positive: str) -> float:
    if isinstance(result, list) and result:
        if isinstance(result[0], list):
            result = result[0]
        if isinstance(result[0], dict):
            for item in result:
                label = str(item.get("label", "")).lower()
                if positive in label or label in ("1", "true", "watermark", "fake", "ai"):
                    return float(item.get("score", 0))
            return float(result[0].get("score", 0))
    if isinstance(result, dict):
        return float(result.get("score", result.get("watermark", 0)))
    return 0.0


def _local_fallback(local_path: str) -> dict[str, Any]:
    wm = detect_watermark(local_path)
    return {
        "watermark": {
            "detected": bool(wm.get("detected")),
            "score": round(float(wm.get("confidence") or 0), 4),
            "model": "local_heuristic",
            "source": "local",
        },
        "ai_generated": {
            "detected": False,
            "score": 0.0,
            "model": AI_MODEL,
            "skipped": True,
            "reason": "no HF token — задайте HUGGINGFACE_API_TOKEN",
        },
    }


async def _infer(model: str, image_bytes: bytes, token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=settings.ai_search_timeout_sec) as client:
            resp = await client.post(HF_URL.format(model=model), headers=headers, content=image_bytes)
            if resp.status_code == 503:
                return {"error": "model loading"}
            if resp.status_code == 401:
                return {"error": "invalid HF token"}
            resp.raise_for_status()
            return {"raw": resp.json()}
    except httpx.HTTPError as exc:
        return {"error": str(exc)}


async def analyze_huggingface(local_path: str, *, api_token: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "watermark": {"detected": False, "score": 0.0, "model": WATERMARK_MODEL},
        "ai_generated": {"detected": False, "score": 0.0, "model": AI_MODEL},
    }
    if not local_path or not Path(local_path).is_file():
        return {**out, "error": "no image"}

    token = (api_token or settings.huggingface_api_token or "").strip()
    if not token:
        return _local_fallback(local_path)

    data = Path(local_path).read_bytes()
    if len(data) > 5_000_000:
        return {**out, "error": "image too large"}

    wm_res, ai_res = await asyncio.gather(
        _infer(WATERMARK_MODEL, data, token),
        _infer(AI_MODEL, data, token),
    )

    if wm_res.get("error"):
        out["watermark"]["error"] = wm_res["error"]
        local = detect_watermark(local_path)
        if local.get("detected"):
            out["watermark"]["detected"] = True
            out["watermark"]["score"] = round(float(local.get("confidence") or 0), 4)
            out["watermark"]["source"] = "local_fallback"
    else:
        score = _score_label(wm_res.get("raw"), "watermark")
        out["watermark"]["score"] = round(score, 4)
        out["watermark"]["detected"] = score >= settings.hf_watermark_threshold

    if ai_res.get("error"):
        out["ai_generated"]["error"] = ai_res["error"]
    else:
        score = _score_label(ai_res.get("raw"), "ai")
        out["ai_generated"]["score"] = round(score, 4)
        out["ai_generated"]["detected"] = score >= settings.hf_ai_generated_threshold

    return out
