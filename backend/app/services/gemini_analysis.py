"""Google Gemini multimodal image analysis (free tier via API key)."""

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.services.http_json import parse_response_json

logger = logging.getLogger(__name__)
settings = get_settings()

PROMPT = (
    "Analyze this image. Determine if it is likely copyrighted (stock photo, professional photography, "
    "news image). Check for watermarks, logos, text. Identify the probable source type: "
    "stock, microstock, social, news, ai_generated, public_domain, other. "
    "Reply in JSON with keys: source_type, copyrighted (bool), watermark_mentioned (bool), reasoning (string)."
)

SOURCE_MAP = {
    "stock": "stock",
    "microstock": "microstock",
    "stock photo": "stock",
    "shutterstock": "microstock",
    "getty": "microstock",
    "ai-generated": "ai_generated",
    "ai generated": "ai_generated",
    "public domain": "public_domain",
}


def _guess_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")


def _parse_gemini_text(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {"raw": text[:2000]}
    try:
        import json

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start : end + 1])
            out.update(data)
    except Exception:
        pass

    low = text.lower()
    if "source_type" not in out:
        for key, val in SOURCE_MAP.items():
            if key in low:
                out["source_type"] = val
                break
        else:
            out["source_type"] = "other"
    if "copyrighted" not in out:
        out["copyrighted"] = any(w in low for w in ("copyright", "stock photo", "licensed", "watermark"))
    if "watermark_mentioned" not in out:
        out["watermark_mentioned"] = "watermark" in low or "shutterstock" in low or "getty" in low
    if "reasoning" not in out:
        out["reasoning"] = text[:500]
    return out


async def analyze_gemini(
    local_path: str, image_url: str = "", *, api_key: str | None = None
) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "provider": "gemini",
        "source_type": None,
        "copyrighted": False,
        "watermark_mentioned": False,
        "reasoning": None,
    }
    key = (api_key or settings.gemini_api_key or "").strip()
    if not key:
        return {**empty, "error": "no gemini_api_key"}

    parts: list[dict[str, Any]] = [{"text": PROMPT}]
    if image_url:
        parts[0]["text"] += f"\nImage URL context: {image_url}"

    if local_path and Path(local_path).is_file():
        data = Path(local_path).read_bytes()
        if len(data) > 4_000_000:
            return {**empty, "error": "image too large for gemini"}
        parts.append(
            {"inline_data": {"mime_type": _guess_mime(local_path), "data": base64.b64encode(data).decode("ascii")}}
        )
    elif not image_url:
        return {**empty, "error": "no image"}

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={key}"
    )
    try:
        async with httpx.AsyncClient(timeout=settings.ai_search_timeout_sec) as client:
            resp = await client.post(url, json={"contents": [{"parts": parts}]})
            if resp.status_code != 200:
                return {**empty, "error": f"HTTP {resp.status_code}"}
            payload = parse_response_json(resp) or {}
            candidates = payload.get("candidates") or []
            if not candidates:
                return {**empty, "error": "empty response"}
            parts_out = (candidates[0].get("content") or {}).get("parts") or []
            text = parts_out[0].get("text", "") if parts_out else ""
            parsed = _parse_gemini_text(text)
            return {**empty, **parsed, "error": None}
    except httpx.HTTPError as exc:
        logger.warning("Gemini failed: %s", exc)
        return {**empty, "error": str(exc)}
