import logging
from pathlib import Path

from app.config import get_settings
from app.database import SessionLocal, engine
from app.migrate import apply_migrations
from app.models import ScanStatus, SiteScan
from app.services.scan_control import ScanCancelled
from app.services.scan_runner import run_scan_pipeline
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(bind=True, max_retries=1, default_retry_delay=60, time_limit=7200, soft_time_limit=7000)
def run_site_scan(self, scan_id: int) -> dict:
    apply_migrations(engine)
    db = SessionLocal()
    try:
        scan = db.get(SiteScan, scan_id)
        if not scan:
            return {"error": "scan not found"}

        scan.status = ScanStatus.IN_PROGRESS
        db.commit()
        logger.info("scan %s started: %s", scan_id, scan.url)

        Path(settings.image_store_dir).mkdir(parents=True, exist_ok=True)
        stats = run_scan_pipeline(db, scan)

        scan = db.get(SiteScan, scan_id)
        if not scan:
            return {"error": "scan not found after pipeline"}

        scan.pages_scanned = stats.get("pages_scanned", 0)
        scan.images_found = stats.get("images_found", 0)
        scan.images_processed = stats.get("images_processed", 0)

        if scan.status == ScanStatus.CANCELLED:
            logger.info("scan %s cancelled by user", scan_id)
            db.commit()
            return {"scan_id": scan_id, "cancelled": True, **stats}

        if stats.get("pages_scanned", 0) == 0:
            scan.status = ScanStatus.FAILED
            scan.error_message = stats.get("error") or "Не удалось загрузить страницы"
            db.commit()
            logger.warning("scan %s failed: no pages fetched", scan_id)
            return {"scan_id": scan_id, "failed": True, **stats}

        scan.status = ScanStatus.DONE
        scan.error_message = None
        db.commit()
        logger.info("scan %s finished: %s", scan_id, stats)
        return {"scan_id": scan_id, **stats}
    except ScanCancelled:
        logger.info("scan %s cancelled", scan_id)
        db.rollback()
        scan = db.get(SiteScan, scan_id)
        if scan and scan.status != ScanStatus.CANCELLED:
            scan.status = ScanStatus.CANCELLED
            db.commit()
        return {"scan_id": scan_id, "cancelled": True}
    except Exception as exc:
        logger.exception("scan %s failed", scan_id)
        db.rollback()
        scan = db.get(SiteScan, scan_id)
        if scan and scan.status not in (ScanStatus.CANCELLED, ScanStatus.PAUSED):
            scan.status = ScanStatus.FAILED
            scan.error_message = str(exc)[:2000]
            db.commit()
        return {"scan_id": scan_id, "failed": True, "error": str(exc)}
    finally:
        db.close()
