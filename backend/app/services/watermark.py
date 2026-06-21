"""Simple watermark heuristics — semi-transparent corner overlay + known stock/DMCA types."""

import logging
from pathlib import Path

from PIL import Image as PILImage, ImageStat

logger = logging.getLogger(__name__)

STOCK_WATERMARK_HINTS = ("shutterstock", "getty", "adobe stock", "depositphotos", "dreamstime", "123rf", "alamy")
DMCA_WATERMARK_HINTS = ("dmca", "protected by dmca", "dmca.com")


def detect_watermark(local_path: str) -> dict:
    path = Path(local_path)
    if not path.is_file():
        return {"detected": False, "confidence": 0.0, "details": None, "watermark_type": None}

    path_hint = path.name.lower()
    for hint in STOCK_WATERMARK_HINTS:
        if hint.replace(" ", "") in path_hint or hint in path_hint:
            return {
                "detected": True,
                "confidence": 0.7,
                "details": f"path_hint_{hint.replace(' ', '_')}",
                "watermark_type": hint.replace(" ", "_"),
            }

    try:
        with PILImage.open(path).convert("RGBA") as img:
            w, h = img.size
            if w < 64 or h < 64:
                return {"detected": False, "confidence": 0.0, "details": None, "watermark_type": None}

            corner = img.crop((0, 0, w // 4, h // 4))
            alpha = corner.split()[3]
            hist = alpha.histogram()
            total = sum(hist) or 1
            semi = sum(hist[30:201]) / total

            # ponytail: no OCR — DMCA badge often semi-transparent in corner
            if semi > 0.08:
                wm_type = "generic"
                if semi > 0.12:
                    wm_type = "dmca" if semi > 0.15 else "generic"
                return {
                    "detected": True,
                    "confidence": min(semi * 2, 0.85),
                    "details": "semi_transparent_corner",
                    "watermark_type": wm_type,
                }

            stat = ImageStat.Stat(corner.convert("L"))
            if stat.stddev[0] > 45 and semi > 0.03:
                return {
                    "detected": True,
                    "confidence": 0.55,
                    "details": "high_variance_corner",
                    "watermark_type": "generic",
                }

    except Exception as exc:
        logger.debug("watermark check failed: %s", exc)

    return {"detected": False, "confidence": 0.0, "details": None, "watermark_type": None}
