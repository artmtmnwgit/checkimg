"""Extract DMCA / copyright signals from HTML pages, robots.txt, humans.txt."""

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

DMCA_FOOTER_PATTERNS = re.compile(
    r"(DMCA|Protected by DMCA\.com|Copyright\s*©|All rights reserved|"
    r"Digital Millennium Copyright Act|dmca\.com|DMCA Protection)",
    re.I,
)
DMCA_LINK_RE = re.compile(r"https?://(?:www\.)?dmca\.com[^\s\"'<>]*", re.I)
DMCA_META_NAMES = frozenset(
    {
        "copyright",
        "rights",
        "dmca",
        "dmca-protection-id",
        "protection-id",
        "dc.rights",
        "dcterms.rights",
    }
)
DMCA_PAGE_PATHS = ("/dmca/", "/dmca", "/copyright/", "/copyright", "/dmca-policy/", "/terms/dmca/")


def extract_dmca_page_signals(html: str, base_url: str) -> dict[str, Any]:
    """Parse footer, meta tags, and DMCA-related links from a single HTML page."""
    tree = HTMLParser(html)
    signals: dict[str, Any] = {
        "footer_text_hits": [],
        "meta_tags": [],
        "dmca_links": [],
        "has_dmca_badge": False,
        "copyright_notices": [],
    }

    footer_text = " ".join(
        (node.text(separator=" ") or "").strip()
        for node in tree.css("footer, [role='contentinfo'], .footer, #footer")
    )
    if not footer_text.strip():
        # ponytail: fallback to last 3000 chars of body when no footer tag
        body = tree.css_first("body")
        footer_text = (body.text(separator=" ") or "")[-3000:] if body else ""

    for m in DMCA_FOOTER_PATTERNS.finditer(footer_text):
        hit = m.group(0).strip()
        if hit not in signals["footer_text_hits"]:
            signals["footer_text_hits"].append(hit)

    for node in tree.css("meta"):
        attrs = node.attributes or {}
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        content = (attrs.get("content") or "").strip()
        if not content:
            continue
        if name in DMCA_META_NAMES or "dmca" in name or "copyright" in name:
            signals["meta_tags"].append({"name": name, "content": content[:500]})
        if "copyright" in name:
            signals["copyright_notices"].append(content[:300])

    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        if "dmca" in href.lower() or DMCA_LINK_RE.search(href):
            full = urljoin(base_url, href)
            if full not in signals["dmca_links"]:
                signals["dmca_links"].append(full)

    # badge images/scripts
    for node in tree.css("img[src*='dmca'], script[src*='dmca'], iframe[src*='dmca']"):
        signals["has_dmca_badge"] = True

    for m in DMCA_LINK_RE.finditer(html):
        url = m.group(0).rstrip("\\',\"")
        if url not in signals["dmca_links"]:
            signals["dmca_links"].append(url)

    return signals


def merge_dmca_signals(acc: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    """Merge page-level signals into scan accumulator."""
    for key in ("footer_text_hits", "meta_tags", "dmca_links", "copyright_notices"):
        for item in page.get(key) or []:
            if item not in acc.setdefault(key, []):
                acc[key].append(item)
    if page.get("has_dmca_badge"):
        acc["has_dmca_badge"] = True
    return acc


def parse_robots_humans(text: str, kind: str) -> dict[str, Any]:
    """Extract copyright / owner hints from robots.txt or humans.txt."""
    out: dict[str, Any] = {"kind": kind, "owner_hints": [], "dmca_mentions": []}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if any(k in lower for k in ("copyright", "owner", "contact", "dmca", "rights")):
            out["owner_hints"].append(line[:300])
        if "dmca" in lower:
            out["dmca_mentions"].append(line[:300])
    return out


def dmca_extra_paths(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    paths = [urljoin(root, p) for p in DMCA_PAGE_PATHS]
    paths.append(urljoin(root, "/robots.txt"))
    paths.append(urljoin(root, "/humans.txt"))
    paths.append(urljoin(root, "/favicon.ico"))
    return list(dict.fromkeys(paths))
