"""Extract image URLs from HTML — lazyload, picture, CSS, JSON-LD."""

import json
import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.services.image_filters import is_raster_too_small, parse_dimensions_from_url
from app.services.url_clean import clean_http_url

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif", ".jxl"}
MIN_DIMENSION = 32

# attrs that commonly hold real image URL when src is a placeholder
URL_ATTRS = (
    "src",
    "href",
    "poster",
    "content",
    "data-src",
    "data-lazy-src",
    "data-lazy",
    "data-original",
    "data-url",
    "data-image",
    "data-img",
    "data-bg",
    "data-background",
    "data-background-image",
    "data-thumb",
    "data-thumbnail",
    "data-full",
    "data-full-src",
    "data-large",
    "data-large_image",
    "data-large-image",
    "data-zoom",
    "data-zoom-image",
    "data-hi-res",
    "data-retina",
    "data-src-retina",
    "data-lazy",
    "data-lazyload",
    "data-orig",
    "data-original-src",
    "data-splide-lazy",
)

SRCSET_ATTRS = ("srcset", "data-srcset", "data-lazy-srcset", "data-original-set", "imagesrcset")

BG_IMAGE_RE = re.compile(
    r"(?:background(?:-image)?|border-image-source|list-style-image|content)\s*:\s*[^;]*?url\(['\"]?([^'\")\\]+)['\"]?\)",
    re.I,
)
IMAGE_SET_RE = re.compile(r"url\(['\"]?([^'\")\\]+)['\"]?\)", re.I)
MEDIA_PATH_RE = re.compile(r"/(?:uploads|media|images?|img|photos?|wp-content|assets|static|files)/", re.I)
PLACEHOLDER_RE = re.compile(
    r"(placeholder|spacer|blank|pixel|1x1|transparent|loading\.gif|lazy\.svg|data:image)",
    re.I,
)
# ponytail: broad URL harvest from inline JSON/scripts — may pick noise; filtered by _is_image_candidate
SCRIPT_URL_RE = re.compile(
    r'https?://[^\s"\'<>\\]+\.(?:jpe?g|png|webp|bmp|gif|avif)(?:\?[^\s"\'<>\\]*)?',
    re.I,
)


def _normalize_url(base: str, raw: str) -> str | None:
    raw = (raw or "").strip().strip("'\"")
    if not raw or raw.startswith("data:") or raw.startswith("blob:") or raw.startswith("#"):
        return None
    if raw.startswith("//"):
        raw = "https:" + raw
    if raw.startswith("http://") or raw.startswith("https://"):
        return clean_http_url(raw)
    joined = urljoin(base, raw)
    if joined.startswith("http"):
        return clean_http_url(joined) or joined
    return joined


def _is_placeholder(url: str) -> bool:
    if PLACEHOLDER_RE.search(url):
        return True
    path = urlparse(url).path.lower()
    # tiny tracking pixels often .gif 1x1
    if path.endswith(".gif") and any(x in path for x in ("pixel", "spacer", "blank", "track")):
        return True
    return False


def _is_image_candidate(url: str) -> bool:
    if _is_placeholder(url):
        return False
    parsed = urlparse(url)
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return True
    q = parsed.query.lower()
    if any(h in q for h in ("format=webp", "format=jpg", "format=jpeg", "format=png", "type=image", "fm=webp", "f=webp")):
        return True
    if MEDIA_PATH_RE.search(path):
        return True
    # CDN resize paths: /w_800/ or /crop/
    if re.search(r"/(?:w|h|width|height)_\d+", path):
        return True
    return False


def _parse_srcset(value: str, base: str) -> list[str]:
    urls: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        url_part = part.split()[0]
        url = _normalize_url(base, url_part)
        if url:
            urls.append(url)
    return urls


def _skip_tiny(width: str, height: str, *, min_w: int = MIN_DIMENSION, min_h: int = MIN_DIMENSION) -> bool:
    try:
        w, h = int(str(width).replace("px", "")), int(str(height).replace("px", ""))
        if min_w <= 0 and min_h <= 0:
            return False
        mw = min_w if min_w > 0 else 0
        mh = min_h if min_h > 0 else 0
        if mw and mh:
            return w < mw or h < mh
        if mw:
            return w < mw
        return h < mh
    except (TypeError, ValueError):
        return False


def _add(
    found: set[str],
    base: str,
    raw: str | None,
    *,
    skip_tiny: bool = False,
    w: str = "",
    h: str = "",
    min_w: int = MIN_DIMENSION,
    min_h: int = MIN_DIMENSION,
) -> None:
    if not raw:
        return
    url = _normalize_url(base, raw)
    if not url or not _is_image_candidate(url):
        return
    if skip_tiny and _skip_tiny(w, h, min_w=min_w, min_h=min_h):
        return
    url_dims = parse_dimensions_from_url(url)
    if url_dims and is_raster_too_small(url_dims[0], url_dims[1], min_w=min_w, min_h=min_h):
        return
    if (min_w > 0 or min_h > 0) and url.lower().split("?", 1)[0].endswith(".svg"):
        if not url_dims or is_raster_too_small(url_dims[0], url_dims[1], min_w=min_w, min_h=min_h):
            return
    found.add(url)


def _add_srcset(
    found: set[str],
    base: str,
    value: str | None,
    *,
    min_w: int = MIN_DIMENSION,
    min_h: int = MIN_DIMENSION,
) -> None:
    if not value:
        return
    for url in _parse_srcset(value, base):
        if not _is_image_candidate(url):
            continue
        url_dims = parse_dimensions_from_url(url)
        if url_dims and is_raster_too_small(url_dims[0], url_dims[1], min_w=min_w, min_h=min_h):
            continue
        found.add(url)


def _collect_from_node(
    found: set[str],
    base: str,
    node,
    *,
    min_w: int = MIN_DIMENSION,
    min_h: int = MIN_DIMENSION,
) -> None:
    attrs = node.attributes or {}
    tag = node.tag.lower() if node.tag else ""

    w, h = attrs.get("width", ""), attrs.get("height", "")

    if tag == "img":
        for attr in URL_ATTRS:
            if attr in attrs:
                _add(found, base, attrs[attr], skip_tiny=True, w=w, h=h, min_w=min_w, min_h=min_h)
        for attr in SRCSET_ATTRS:
            _add_srcset(found, base, attrs.get(attr), min_w=min_w, min_h=min_h)

    elif tag == "source":
        _add(found, base, attrs.get("src"), min_w=min_w, min_h=min_h)
        _add_srcset(found, base, attrs.get("srcset"), min_w=min_w, min_h=min_h)

    elif tag == "video":
        _add(found, base, attrs.get("poster"))

    elif tag == "link":
        rel = (attrs.get("rel") or "").lower()
        as_type = (attrs.get("as") or "").lower()
        if as_type == "image" or "image_src" in rel or "preload" in rel and as_type == "image":
            _add(found, base, attrs.get("href"))

    elif tag == "meta":
        prop = (attrs.get("property") or attrs.get("name") or "").lower()
        if prop in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"):
            _add(found, base, attrs.get("content"))

    elif tag == "input" and (attrs.get("type") or "").lower() == "image":
        _add(found, base, attrs.get("src"))

    elif tag == "a":
        # lightbox / full-size links
        if any(k in attrs for k in ("data-lightbox", "data-fancybox", "data-gallery")):
            _add(found, base, attrs.get("href"))

    # any element: data-* and style background
    for attr, val in attrs.items():
        if not val:
            continue
        if attr.startswith("data-") and attr not in SRCSET_ATTRS:
            if "srcset" in attr or "set" in attr:
                _add_srcset(found, base, val, min_w=min_w, min_h=min_h)
            elif any(k in attr for k in ("src", "img", "image", "photo", "thumb", "bg", "url", "lazy", "zoom", "large")):
                _add(found, base, val, min_w=min_w, min_h=min_h)
        if attr == "style":
            for match in BG_IMAGE_RE.finditer(val):
                _add(found, base, match.group(1))


def _extract_from_css(css: str, base: str, found: set[str]) -> None:
    for match in BG_IMAGE_RE.finditer(css):
        _add(found, base, match.group(1))
    for match in IMAGE_SET_RE.finditer(css):
        url = match.group(1)
        if _is_image_candidate(url) or "." in url:
            _add(found, base, url)


def _extract_json_ld_images(obj, found: set[str], base: str) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in ("image", "thumbnailUrl", "contentUrl", "url") and isinstance(val, str):
                _add(found, base, val)
            elif key == "image" and isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        _add(found, base, item)
                    elif isinstance(item, dict):
                        _add(found, base, item.get("url") or item.get("contentUrl"))
            else:
                _extract_json_ld_images(val, found, base)
    elif isinstance(obj, list):
        for item in obj:
            _extract_json_ld_images(item, found, base)


def extract_stylesheet_urls(html: str, base_url: str) -> list[str]:
    tree = HTMLParser(html)
    urls: set[str] = set()
    for node in tree.css("link[rel]"):
        rel = (node.attributes.get("rel") or "").lower()
        if "stylesheet" not in rel:
            continue
        href = _normalize_url(base_url, node.attributes.get("href"))
        if href:
            urls.add(href)
    return sorted(urls)


def _node_str(node, attr: str) -> str:
    val = getattr(node, attr, "") or ""
    return val() if callable(val) else str(val)


def _extract_noscript_images(
    html_fragment: str,
    base_url: str,
    found: set[str],
    *,
    min_w: int = MIN_DIMENSION,
    min_h: int = MIN_DIMENSION,
) -> None:
    """Parse <noscript> inner HTML without re-entering noscript (avoids recursion)."""
    tree = HTMLParser(html_fragment)
    for node in tree.css("img, source"):
        _collect_from_node(found, base_url, node, min_w=min_w, min_h=min_h)


def extract_image_urls(
    html: str,
    base_url: str,
    extra_css: list[str] | None = None,
    *,
    min_image_width: int = MIN_DIMENSION,
    min_image_height: int = MIN_DIMENSION,
) -> list[str]:
    min_w, min_h = min_image_width, min_image_height
    tree = HTMLParser(html)
    found: set[str] = set()

    for node in tree.css("img, source, picture source, video, link, meta, input, a"):
        _collect_from_node(found, base_url, node, min_w=min_w, min_h=min_h)

    # background-image on div/section/etc.
    for node in tree.css("[style]"):
        _collect_from_node(found, base_url, node, min_w=min_w, min_h=min_h)

    # lazyload on non-img elements (div data-bg, span data-background, etc.)
    for node in tree.css("[data-src], [data-srcset], [data-lazy-src], [data-original], [data-bg], [data-background]"):
        if (node.tag or "").lower() not in ("img", "source"):
            _collect_from_node(found, base_url, node, min_w=min_w, min_h=min_h)

    # picture wraps source — also walk picture containers
    for node in tree.css("picture"):
        for child in node.iter():
            _collect_from_node(found, base_url, child, min_w=min_w, min_h=min_h)

    # lazyload fallbacks: real <img> often duplicated inside <noscript>
    for node in tree.css("noscript"):
        inner = _node_str(node, "html") or _node_str(node, "text")
        if inner:
            _extract_noscript_images(inner, base_url, found, min_w=min_w, min_h=min_h)

    for node in tree.css("style"):
        css = _node_str(node, "text") or _node_str(node, "html")
        _extract_from_css(css, base_url, found)

    for css in extra_css or []:
        _extract_from_css(css, base_url, found)

    for node in tree.css('script[type="application/ld+json"]'):
        raw = (_node_str(node, "text") or _node_str(node, "html")).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            _extract_json_ld_images(data, found, base_url)
        except json.JSONDecodeError:
            pass

    # ponytail: last-resort regex for URLs embedded in inline scripts (Nuxt/Vue hydration)
    for node in tree.css("script"):
        if node.attributes.get("type") == "application/ld+json":
            continue
        text = _node_str(node, "text")
        if len(text) > 500_000:
            continue
        for match in SCRIPT_URL_RE.finditer(text):
            _add(found, base_url, match.group(0))

    return sorted(found)


def extract_page_links(html: str, base_url: str, same_domain: str) -> set[str]:
    tree = HTMLParser(html)
    links: set[str] = set()
    for node in tree.css("a[href]"):
        href = _normalize_url(base_url, node.attributes.get("href", ""))
        if not href:
            continue
        parsed = urlparse(href)
        if parsed.netloc == same_domain and parsed.scheme in ("http", "https", ""):
            links.add(href.split("#")[0])
    return links


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()
