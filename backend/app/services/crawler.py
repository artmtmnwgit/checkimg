"""Async site crawler — parallel downloads, live progress, hard limits."""

import asyncio
import hashlib
import logging
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Image, Page, PageStatus, SiteScan
from app.services.html_parser import (
    domain_of,
    extract_image_urls,
    extract_page_links,
    extract_stylesheet_urls,
)

logger = logging.getLogger(__name__)
settings = get_settings()

IMAGE_CONTENT_PREFIX = "image/"
IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF", b"GIF8", b"BM")


def _timeout() -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(
        total=settings.crawl_timeout_sec,
        connect=settings.crawl_connect_timeout_sec,
        sock_read=settings.crawl_timeout_sec,
    )


async def _read_limited(resp: aiohttp.ClientResponse, limit: int) -> bytes | None:
    buf = bytearray()
    async for chunk in resp.content.iter_chunked(32_768):
        buf.extend(chunk)
        if len(buf) > limit:
            return None
    return bytes(buf)


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(url, timeout=_timeout()) as resp:
            if resp.status != 200:
                return None
            raw = await _read_limited(resp, 2_000_000)
            if not raw:
                return None
            return raw.decode(errors="ignore")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.debug("fetch failed: %s", url)
        return None


async def _fetch_css_batch(session: aiohttp.ClientSession, html: str, page_url: str) -> list[str]:
    urls = extract_stylesheet_urls(html, page_url)[: settings.crawl_max_stylesheets]
    if not urls:
        return []

    async def one(css_url: str) -> str | None:
        return await _fetch_text(session, css_url)

    results = await asyncio.gather(*[one(u) for u in urls], return_exceptions=True)
    return [r for r in results if isinstance(r, str) and r]


async def _fetch_page_html(session: aiohttp.ClientSession, url: str) -> tuple[str | None, list[str]]:
    html = await _fetch_text(session, url)
    if not html:
        return None, []
    css_chunks = await _fetch_css_batch(session, html, url)
    return html, css_chunks


async def _download_image(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
    dest: Path,
) -> tuple[str, str | None]:
    async with sem:
        try:
            async with session.get(url, timeout=_timeout()) as resp:
                if resp.status != 200:
                    return url, None
                data = await _read_limited(resp, settings.crawl_max_image_bytes)
                if not data or len(data) < 80:
                    return url, None
                ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if ctype and not ctype.startswith(IMAGE_CONTENT_PREFIX):
                    if not data[:12].startswith(IMAGE_MAGIC):
                        return url, None
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                return url, hashlib.sha256(data).hexdigest()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return url, None


def _flush_scan_progress(db: Session, scan: SiteScan, pages: int, images: int) -> None:
    scan.pages_scanned = pages
    scan.images_found = images
    db.commit()
    db.refresh(scan)


async def _crawl_async(db: Session, scan: SiteScan) -> dict:
    root = str(scan.url).rstrip("/")
    site_domain = domain_of(root)
    max_depth = scan.depth
    seen_pages: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(root, 0)])

    pages_scanned = 0
    images_found = 0
    seen_images: set[str] = set()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    sem = asyncio.Semaphore(settings.crawl_concurrency)

    async with aiohttp.ClientSession(headers=headers) as session:
        while queue and pages_scanned < settings.crawl_max_pages:
            url, depth = queue.popleft()
            if url in seen_pages:
                continue
            seen_pages.add(url)

            logger.info("scan %s: fetching page %s (depth %s)", scan.id, url, depth)
            html, css_chunks = await _fetch_page_html(session, url)

            page = Page(scan_id=scan.id, url=url, status=PageStatus.PENDING)
            db.add(page)
            db.flush()

            if not html:
                page.status = PageStatus.FAILED
                db.commit()
                continue

            page.status = PageStatus.SCANNED
            pages_scanned += 1

            img_urls = extract_image_urls(html, url, extra_css=css_chunks)
            img_urls = [u for u in img_urls if u not in seen_images][: settings.crawl_max_images_per_page]

            download_jobs: list[tuple[str, Path]] = []
            for img_url in img_urls:
                ext = Path(urlparse(img_url).path).suffix.lower()
                if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif"}:
                    ext = ".jpg"
                local = Path(settings.image_store_dir) / str(scan.id) / f"{hash(img_url) & 0xFFFFFFFF:08x}{ext}"
                download_jobs.append((img_url, local))

            if download_jobs:
                results = await asyncio.gather(
                    *[_download_image(session, sem, u, p) for u, p in download_jobs],
                    return_exceptions=True,
                )
                for item in results:
                    if isinstance(item, Exception):
                        continue
                    img_url, file_hash = item
                    if not file_hash:
                        continue
                    seen_images.add(img_url)
                    local = next(p for u, p in download_jobs if u == img_url)
                    db.add(
                        Image(
                            page_id=page.id,
                            src_url=img_url,
                            file_hash=file_hash,
                            local_path=str(local),
                        )
                    )
                    images_found += 1

            db.commit()
            _flush_scan_progress(db, scan, pages_scanned, images_found)
            logger.info(
                "scan %s: page done — %s pages, %s images",
                scan.id,
                pages_scanned,
                images_found,
            )

            if depth < max_depth:
                for link in extract_page_links(html, url, site_domain):
                    if link not in seen_pages:
                        queue.append((link, depth + 1))

    return {"pages_scanned": pages_scanned, "images_found": images_found}


def crawl_site(db: Session, scan: SiteScan) -> dict:
    return asyncio.run(_crawl_async(db, scan))
