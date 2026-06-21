"""Crawl + per-image copyright check pipeline with pause/stop."""

import asyncio
import hashlib
import logging
from collections import deque
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import aiohttp
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import CopyrightCheck, Image, Page, PageStatus, RiskLevel, SiteScan
from app.services.scan_options import EffectiveScanOptions, ScanSecrets
from app.services.dmca_crawl import extract_dmca_page_signals, merge_dmca_signals
from app.services.dmca_domain import check_site_domain_dmca
from app.services.dmca_site_crawl import crawl_site_dmca_signals
from app.services.html_parser import (
    domain_of,
    extract_image_urls,
    extract_page_links,
    extract_stylesheet_urls,
)
from app.services.scan_control import check_control
from app.services.sanitize import sanitize_json

logger = logging.getLogger(__name__)
settings = get_settings()

IMAGE_CONTENT_PREFIX = "image/"
IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF", b"GIF8", b"BM")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


def _timeout() -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(
        total=settings.crawl_timeout_sec,
        connect=settings.crawl_connect_timeout_sec,
        sock_read=settings.crawl_timeout_sec,
    )


def _url_variants(url: str) -> list[str]:
    """Generate URL variants to try when the first fetch fails."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return [url]

    host = parsed.netloc
    bare = host[4:] if host.startswith("www.") else host
    hosts = dict.fromkeys([host, bare, f"www.{bare}"])
    path = parsed.path or "/"
    paths: dict[str, None] = {path: None}
    if path == "/":
        paths[""] = None  # https://host without trailing slash
    else:
        paths[path.rstrip("/") + "/"] = None

    out: list[str] = []
    for h in hosts:
        for p in paths:
            out.append(urlunparse((parsed.scheme, h, p, "", parsed.query, "")))
    # try alternate scheme once
    alt = "http" if parsed.scheme == "https" else "https"
    out.append(urlunparse((alt, host, path, "", parsed.query, "")))
    return list(dict.fromkeys(out))


async def _read_limited(resp: aiohttp.ClientResponse, limit: int) -> bytes | None:
    buf = bytearray()
    async for chunk in resp.content.iter_chunked(32_768):
        buf.extend(chunk)
        if len(buf) > limit:
            return None
    return bytes(buf)


def _looks_like_html(text: str) -> bool:
    head = text[:4000].lower()
    return "<html" in head or "<!doctype" in head


async def _fetch_text_once(
    session: aiohttp.ClientSession, url: str
) -> tuple[str | None, int | None, str | None]:
    try:
        async with session.get(url, timeout=_timeout(), allow_redirects=True) as resp:
            status = resp.status
            final_url = str(resp.url)
            raw = await _read_limited(resp, 2_000_000)
            if not raw or len(raw) < 100:
                return None, status, final_url
            text = raw.decode(errors="ignore")
            # ponytail: some sites (e.g. Bitrix CMS) return 500 with a full HTML page
            if status not in (200, 201) and not _looks_like_html(text):
                return None, status, final_url
            ctype = resp.headers.get("Content-Type", "").lower()
            if ctype and "html" not in ctype and "text" not in ctype and "xml" not in ctype:
                if not _looks_like_html(text):
                    return None, status, final_url
            if status not in (200, 201):
                logger.info("using HTML body despite HTTP %s for %s", status, url)
            return text, status, final_url
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.debug("fetch error %s: %s", url, exc)
        return None, None, None


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> tuple[str | None, str]:
    last_status: int | None = None
    for variant in _url_variants(url):
        html, status, final_url = await _fetch_text_once(session, variant)
        last_status = status
        if html:
            resolved = final_url or variant
            if variant != url:
                logger.info("fetch ok via variant %s (requested %s)", variant, url)
            if domain_of(resolved) != domain_of(variant):
                logger.warning("cross-domain redirect %s → %s", variant, resolved)
            return html, resolved
    logger.warning("fetch failed for %s (last HTTP %s)", url, last_status)
    return None, url


async def _fetch_css_batch(session: aiohttp.ClientSession, html: str, page_url: str) -> list[str]:
    urls = extract_stylesheet_urls(html, page_url)[: settings.crawl_max_stylesheets]
    if not urls:
        return []
    results = await asyncio.gather(*[_fetch_text_once(session, u) for u in urls], return_exceptions=True)
    return [r[0] for r in results if isinstance(r, tuple) and r[0]]


async def _download_image(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
    dest: Path,
) -> tuple[str, str | None]:
    async with sem:
        try:
            async with session.get(url, timeout=_timeout(), allow_redirects=True) as resp:
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


def _insert_image(
    scan_id: int,
    page_id: int,
    img_url: str,
    local: Path,
    file_hash: str,
) -> int:
    db = SessionLocal()
    try:
        check_control(db, scan_id)
        image = Image(
            page_id=page_id,
            src_url=img_url,
            file_hash=file_hash,
            local_path=str(local),
        )
        db.add(image)
        db.execute(
            update(SiteScan)
            .where(SiteScan.id == scan_id)
            .values(images_found=SiteScan.images_found + 1)
        )
        db.commit()
        db.refresh(image)
        return image.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _persist_check(
    scan_id: int,
    image_id: int,
    fusion: dict,
    exif: dict,
    wm: dict,
    dmca: dict,
    ai: dict,
) -> None:
    db = SessionLocal()
    try:
        scan = db.get(SiteScan, scan_id)
        image = db.get(Image, image_id)
        if not scan or not image:
            return
        persist_copyright_check(db, scan, image, fusion, exif, wm, dmca, ai)
        db.execute(
            update(SiteScan)
            .where(SiteScan.id == scan_id)
            .values(images_processed=SiteScan.images_processed + 1)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _check_one_image(
    scan_id: int,
    page_id: int,
    img_url: str,
    local: Path,
    file_hash: str,
    ctx: dict,
    check_sem: asyncio.Semaphore,
) -> None:
    """Insert immediately, then check — each DB op uses its own session."""
    image_id = await asyncio.to_thread(
        _insert_image, scan_id, page_id, img_url, local, file_hash
    )

    async with check_sem:
        try:
            fusion, exif, wm, dmca, ai = await gather_external_evidence(
                img_url,
                str(local),
                ctx["site_domain"],
                ctx["site_domain_dmca"],
                ctx["site_signals"],
                ctx["caches"],
                ctx["opts"],
                ctx["secrets"],
            )
        except Exception as exc:
            logger.exception("check failed for %s: %s", img_url, exc)
            await asyncio.to_thread(_fallback_check, image_id, str(exc))
            await asyncio.to_thread(_increment_processed, scan_id)
            return

    try:
        await asyncio.to_thread(
            _persist_check, scan_id, image_id, fusion, exif, wm, dmca, ai
        )
    except Exception as exc:
        logger.exception("persist failed for %s: %s", img_url, exc)
        await asyncio.to_thread(_fallback_check, image_id, str(exc))
        await asyncio.to_thread(_increment_processed, scan_id)


def _increment_processed(scan_id: int) -> None:
    db = SessionLocal()
    try:
        db.execute(
            update(SiteScan)
            .where(SiteScan.id == scan_id)
            .values(images_processed=SiteScan.images_processed + 1)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _fallback_check(image_id: int, error: str) -> None:
    db = SessionLocal()
    try:
        image = db.get(Image, image_id)
        if image and not image.copyright_check:
            db.add(
                CopyrightCheck(
                    image_id=image.id,
                    risk_level=RiskLevel.SAFE,
                    source_evidence=sanitize_json({"reasons": [], "check_error": error[:500]}),
                    dmca_evidence=None,
                )
            )
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _sync_scan_stats(db: Session, scan: SiteScan, pages_scanned: int) -> None:
    scan.pages_scanned = pages_scanned
    db.commit()
    db.refresh(scan)


async def _crawl_pipeline(db: Session, scan: SiteScan) -> dict:
    root = str(scan.url).strip()
    site_domain = domain_of(root)
    max_depth = scan.depth
    seen_pages: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(root, 0)])
    pages_scanned = 0
    pages_failed = 0
    seen_images: set[str] = set()
    fetch_errors: list[str] = []

    sem = asyncio.Semaphore(settings.crawl_concurrency)
    opts = EffectiveScanOptions.for_scan(scan)
    secrets = ScanSecrets.for_scan(scan)

    async with aiohttp.ClientSession(headers=BROWSER_HEADERS) as session:
        check_sem = asyncio.Semaphore(settings.check_concurrency)
        caches: dict = {"lumen_url": {}, "protection_id": {}, "ddg_url": {}}
        site_domain_dmca: dict = {}

        try:
            if opts.dmca_checks:
                dmca_data, site_domain_dmca = await asyncio.gather(
                    crawl_site_dmca_signals(session, root),
                    check_site_domain_dmca(root),
                )
            else:
                dmca_data = await crawl_site_dmca_signals(session, root)
            dmca_data["domain_checks"] = site_domain_dmca
            scan.dmca_site_data = sanitize_json(dmca_data)
            db.commit()
            logger.info("scan %s: DMCA site signals collected", scan.id)
        except Exception as exc:
            logger.warning("scan %s: DMCA crawl failed: %s", scan.id, exc)
            scan.dmca_site_data = scan.dmca_site_data or {}

        ctx = {
            "site_domain": site_domain,
            "site_domain_dmca": site_domain_dmca,
            "site_signals": scan.dmca_site_data,
            "caches": caches,
            "opts": opts,
            "secrets": secrets,
        }

        while queue and pages_scanned < settings.crawl_max_pages:
            await asyncio.to_thread(check_control, db, scan.id)

            url, depth = queue.popleft()
            if url in seen_pages:
                continue
            seen_pages.add(url)

            logger.info("scan %s: page %s (depth %s)", scan.id, url, depth)
            html, fetched_url = await _fetch_text(session, url)
            css_chunks = await _fetch_css_batch(session, html, fetched_url) if html else []

            page = Page(scan_id=scan.id, url=url, status=PageStatus.PENDING)
            db.add(page)
            db.flush()

            if not html:
                page.status = PageStatus.FAILED
                pages_failed += 1
                fetch_errors.append(url)
                db.commit()
                continue

            if url == root and domain_of(fetched_url) != site_domain:
                page.status = PageStatus.FAILED
                pages_failed += 1
                fetch_errors.append(
                    f"{url} перенаправляет на {fetched_url} — укажите целевой URL напрямую"
                )
                db.commit()
                continue

            page.status = PageStatus.SCANNED
            pages_scanned += 1
            await asyncio.to_thread(_sync_scan_stats, db, scan, pages_scanned)

            base_url = fetched_url
            page_dmca = extract_dmca_page_signals(html, base_url)
            if scan.dmca_site_data:
                scan.dmca_site_data = sanitize_json(merge_dmca_signals(scan.dmca_site_data, page_dmca))
            img_urls = extract_image_urls(html, base_url, extra_css=css_chunks)
            img_urls = [u for u in img_urls if u not in seen_images][: settings.crawl_max_images_per_page]

            jobs: list[tuple[str, Path]] = []
            for img_url in img_urls:
                ext = Path(urlparse(img_url).path).suffix.lower()
                if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif"}:
                    ext = ".jpg"
                local = Path(settings.image_store_dir) / str(scan.id) / f"{hash(img_url) & 0xFFFFFFFF:08x}{ext}"
                jobs.append((img_url, local))

            if jobs:
                check_tasks: list[asyncio.Task] = []
                tasks = [asyncio.create_task(_download_image(session, sem, u, p)) for u, p in jobs]
                for coro in asyncio.as_completed(tasks):
                    await asyncio.to_thread(check_control, db, scan.id)
                    item = await coro
                    if isinstance(item, Exception):
                        continue
                    img_url, file_hash = item
                    if not file_hash or img_url in seen_images:
                        continue
                    seen_images.add(img_url)
                    local = next(p for u, p in jobs if u == img_url)
                    check_tasks.append(
                        asyncio.create_task(
                            _check_one_image(
                                scan.id, page.id, img_url, local, file_hash, ctx, check_sem
                            )
                        )
                    )
                if check_tasks:
                    await asyncio.gather(*check_tasks, return_exceptions=True)

            if depth < max_depth:
                for link in extract_page_links(html, base_url, site_domain):
                    if link not in seen_pages:
                        queue.append((link, depth + 1))

    error: str | None = None
    if pages_scanned == 0:
        error = (
            "Не удалось загрузить ни одной страницы. "
            "Сайт может блокировать боты или быть временно недоступен."
        )
        if fetch_errors:
            error += f" URL: {fetch_errors[0]}"

    db.expire(scan)
    fresh = db.get(SiteScan, scan.id)
    return {
        "pages_scanned": pages_scanned,
        "pages_failed": pages_failed,
        "images_found": fresh.images_found if fresh else 0,
        "images_processed": fresh.images_processed if fresh else 0,
        "error": error,
    }


def run_scan_pipeline(db: Session, scan: SiteScan) -> dict:
    return asyncio.run(_crawl_pipeline(db, scan))
