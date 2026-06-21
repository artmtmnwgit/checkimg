"""Image dimension hints from URLs and SVG bytes — for crawl filters."""

import re
from urllib.parse import urlparse

# Bitrix: /resize_cache/.../80_80_2/file.png
BITRIX_RESIZE_RE = re.compile(r"/(\d+)_(\d+)_\d+/", re.I)
# thumb-60x60.jpg, image_60x60.webp
WXH_RE = re.compile(r"[-_](\d{2,4})x(\d{2,4})(?:\.|[-_/])", re.I)
SVG_WH_RE = re.compile(r'\bwidth\s*=\s*["\']?(\d+)', re.I)
SVG_H_RE = re.compile(r'\bheight\s*=\s*["\']?(\d+)', re.I)
SVG_VIEWBOX_RE = re.compile(r'\bviewBox\s*=\s*["\']?\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)', re.I)


def parse_dimensions_from_url(url: str) -> tuple[int, int] | None:
    path = urlparse(url).path
    m = BITRIX_RESIZE_RE.search(path)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = WXH_RE.search(path)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def parse_svg_dimensions(data: bytes) -> tuple[int, int] | None:
    head = data[:12_000].decode("utf-8", errors="ignore")
    if "<svg" not in head.lower():
        return None
    wm, hm = SVG_WH_RE.search(head), SVG_H_RE.search(head)
    if wm and hm:
        return int(wm.group(1)), int(hm.group(1))
    vb = SVG_VIEWBOX_RE.search(head)
    if vb:
        return int(float(vb.group(1))), int(float(vb.group(2)))
    return None


def is_raster_too_small(
    w: int,
    h: int,
    *,
    min_w: int,
    min_h: int,
) -> bool:
    if min_w <= 0 and min_h <= 0:
        return False
    if min_w > 0 and w < min_w:
        return True
    if min_h > 0 and h < min_h:
        return True
    return False


def passes_dimension_filter(
    *,
    min_w: int,
    min_h: int,
    url: str = "",
    pixel_w: int | None = None,
    pixel_h: int | None = None,
    file_bytes: bytes | None = None,
) -> bool:
    """True if image passes min width/height (unknown size allowed only for raster without filter)."""
    if min_w <= 0 and min_h <= 0:
        return True

    if pixel_w is not None and pixel_h is not None:
        return not is_raster_too_small(pixel_w, pixel_h, min_w=min_w, min_h=min_h)

    if url:
        from_url = parse_dimensions_from_url(url)
        if from_url and is_raster_too_small(from_url[0], from_url[1], min_w=min_w, min_h=min_h):
            return False

    if file_bytes:
        low = url.lower()
        if low.endswith(".svg") or file_bytes.lstrip()[:100].lower().startswith((b"<?xml", b"<svg")):
            svg = parse_svg_dimensions(file_bytes)
            if not svg:
                return False
            return not is_raster_too_small(svg[0], svg[1], min_w=min_w, min_h=min_h)

    return True
