"""Visual similarity — dHash + histogram; separates exact copies from lookalikes."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

HASH_SIZE = 8  # 64-bit dHash


def _dhash(img: Image.Image) -> int:
    gray = ImageOps.grayscale(img.resize((HASH_SIZE + 1, HASH_SIZE), Image.Resampling.LANCZOS))
    pixels = list(gray.getdata())
    bits = 0
    for row in range(HASH_SIZE):
        for col in range(HASH_SIZE):
            left = pixels[row * (HASH_SIZE + 1) + col]
            right = pixels[row * (HASH_SIZE + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _hist_corr(a: Image.Image, b: Image.Image) -> float:
    ha = a.convert("L").resize((256, 256), Image.Resampling.BILINEAR).histogram()
    hb = b.convert("L").resize((256, 256), Image.Resampling.BILINEAR).histogram()
    sum_a = sum(ha) or 1
    sum_b = sum(hb) or 1
    na = [h / sum_a for h in ha]
    nb = [h / sum_b for h in hb]
    mean_a = sum(na) / len(na)
    mean_b = sum(nb) / len(nb)
    num = sum((na[i] - mean_a) * (nb[i] - mean_b) for i in range(len(na)))
    den_a = sum((x - mean_a) ** 2 for x in na) ** 0.5
    den_b = sum((x - mean_b) ** 2 for x in nb) ** 0.5
    if den_a == 0 or den_b == 0:
        return 0.0
    return max(0.0, min(1.0, num / (den_a * den_b)))


def compare_images(local: Image.Image, remote: Image.Image) -> dict[str, Any]:
    local_p = ImageOps.exif_transpose(local.convert("RGB"))
    remote_p = ImageOps.exif_transpose(remote.convert("RGB"))

    dist = _hamming(_dhash(local_p), _dhash(remote_p))
    phash_score = 1.0 - dist / (HASH_SIZE * HASH_SIZE)
    hist_score = _hist_corr(local_p, remote_p)
    score = round(0.65 * phash_score + 0.35 * hist_score, 3)

    if dist <= 5 or score >= 0.92:
        kind = "exact"
    elif dist <= 14 or score >= 0.72:
        kind = "similar"
    else:
        kind = "weak"

    return {
        "similarity_score": score,
        "match_kind": kind,
        "phash_distance": dist,
        "phash_score": round(phash_score, 3),
        "histogram_score": round(hist_score, 3),
    }


def compare_image_bytes(local_path: str, remote_bytes: bytes) -> dict[str, Any] | None:
    path = Path(local_path)
    if not path.is_file() or len(remote_bytes) < 100:
        return None
    try:
        with Image.open(path) as local_img:
            with Image.open(io.BytesIO(remote_bytes)) as remote_img:
                return compare_images(local_img, remote_img)
    except Exception as exc:
        logger.debug("compare failed: %s", exc)
        return None
