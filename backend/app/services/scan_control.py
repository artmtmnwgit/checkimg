"""Pause / stop signals polled from DB by the worker."""

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ScanStatus, SiteScan


class ScanCancelled(Exception):
    pass


def get_status(db: Session, scan_id: int) -> ScanStatus:
    db.expire_all()
    return db.execute(select(SiteScan.status).where(SiteScan.id == scan_id)).scalar_one()


def check_control(db: Session, scan_id: int) -> None:
    """Block while paused; raise ScanCancelled if user stopped the scan."""
    while True:
        status = get_status(db, scan_id)
        if status == ScanStatus.CANCELLED:
            raise ScanCancelled()
        if status != ScanStatus.PAUSED:
            return
        db.commit()
        time.sleep(0.4)
