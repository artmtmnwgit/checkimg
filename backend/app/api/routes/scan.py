from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import CopyrightCheck, Image, Page, RiskLevel, ScanStatus, SiteScan
from app.schemas.scan import (
    ExcludeImageRequest,
    ScanCreateRequest,
    ScanCreateResponse,
    ScanResultsResponse,
    ScanStatusResponse,
)
from app.schemas.scan_options import ScanOptionsDefaultsResponse
from app.services.scan_options import options_to_json, public_scan_options, scan_options_defaults
from app.services.tagging import render_tagged_image
from app.tasks.scan_tasks import run_site_scan

router = APIRouter(prefix="/api", tags=["scan"])


@router.get("/scan/options-defaults", response_model=ScanOptionsDefaultsResponse)
def get_scan_options_defaults():
    defaults, presets, keys_configured = scan_options_defaults()
    return ScanOptionsDefaultsResponse(
        defaults=defaults, presets=presets, keys_configured=keys_configured
    )


@router.post("/scan", response_model=ScanCreateResponse)
def create_scan(body: ScanCreateRequest, db: Session = Depends(get_db)):
    scan = SiteScan(
        url=str(body.url),
        depth=body.depth,
        status=ScanStatus.PENDING,
        scan_options=options_to_json(body.options),
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    run_site_scan.delay(scan.id)
    return ScanCreateResponse(id=scan.id, status=scan.status, url=scan.url, depth=scan.depth)


def _active_scan_status(status: ScanStatus) -> bool:
    return status in (ScanStatus.IN_PROGRESS, ScanStatus.PAUSED)


@router.post("/scan/{scan_id}/pause")
def pause_scan(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(SiteScan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    if scan.status != ScanStatus.IN_PROGRESS:
        raise HTTPException(409, "Scan is not running")
    scan.status = ScanStatus.PAUSED
    db.commit()
    return {"ok": True, "status": scan.status}


@router.post("/scan/{scan_id}/resume")
def resume_scan(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(SiteScan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    if scan.status != ScanStatus.PAUSED:
        raise HTTPException(409, "Scan is not paused")
    scan.status = ScanStatus.IN_PROGRESS
    db.commit()
    return {"ok": True, "status": scan.status}


@router.post("/scan/{scan_id}/stop")
def stop_scan(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(SiteScan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    if not _active_scan_status(scan.status):
        raise HTTPException(409, "Scan is not active")
    scan.status = ScanStatus.CANCELLED
    db.commit()
    return {"ok": True, "status": scan.status}


@router.get("/scan/{scan_id}", response_model=ScanStatusResponse)
def get_scan_status(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(SiteScan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")

    if scan.status == ScanStatus.DONE:
        progress = 100.0 if scan.images_found > 0 else (100.0 if scan.pages_scanned > 0 else 0.0)
    elif scan.status == ScanStatus.FAILED:
        progress = 0.0
    elif scan.status in (ScanStatus.IN_PROGRESS, ScanStatus.PAUSED):
        if scan.images_found > 0:
            progress = round(100.0 * scan.images_processed / scan.images_found, 1)
        elif scan.pages_scanned > 0:
            progress = round(min(15.0, scan.pages_scanned * 5), 1)
        else:
            progress = 0.0
    elif scan.status == ScanStatus.CANCELLED and scan.images_found > 0:
        progress = round(100.0 * scan.images_processed / scan.images_found, 1)
    else:
        progress = 0.0

    return ScanStatusResponse(
        id=scan.id,
        url=scan.url,
        status=scan.status,
        depth=scan.depth,
        scan_options=public_scan_options(scan.scan_options),
        pages_scanned=scan.pages_scanned,
        images_found=scan.images_found,
        images_processed=scan.images_processed,
        progress_pct=progress,
        error_message=scan.error_message,
        created_at=scan.created_at,
    )


@router.get("/scan/{scan_id}/results", response_model=ScanResultsResponse)
def get_scan_results(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(SiteScan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")

    pages = (
        db.query(Page)
        .options(
            joinedload(Page.images).joinedload(Image.copyright_check),
            joinedload(Page.images).joinedload(Image.exif_data),
        )
        .filter(Page.scan_id == scan_id)
        .all()
    )

    summary = {level.value: 0 for level in RiskLevel}
    for page in pages:
        for img in page.images:
            if not img.copyright_check or img.copyright_check.excluded:
                continue
            summary[img.copyright_check.risk_level.value] += 1

    return ScanResultsResponse(
        scan_id=scan.id,
        url=scan.url,
        status=scan.status,
        pages=pages,
        summary=summary,
    )


@router.get("/preview/{scan_id}/{image_id}")
def get_preview(scan_id: int, image_id: int, format: str = "image", db: Session = Depends(get_db)):
    image = (
        db.query(Image)
        .join(Page)
        .options(joinedload(Image.copyright_check))
        .filter(Image.id == image_id, Page.scan_id == scan_id)
        .first()
    )
    if not image:
        raise HTTPException(404, "Image not found")

    risk = image.copyright_check.risk_level if image.copyright_check else None

    if format == "html":
        color = {
            "safe": "#22c55e",
            "warning": "#eab308",
            "suspect": "#f97316",
            "danger": "#ef4444",
            "dmca_protected": "#3b82f6",
            "dmca_violation": "#dc2626",
            "piracy_blacklist": "#7f1d1d",
            "ai_generated": "#a855f7",
            None: "#94a3b8",
        }.get(risk.value if risk else None, "#94a3b8")
        evidence = (image.copyright_check.source_evidence or {}) if image.copyright_check else {}
        snippet = f"""
        <div class="checkimg-wrapper" data-risk="{risk.value if risk else 'pending'}"
             style="border:5px solid {color};display:inline-block;position:relative">
          <img src="{image.src_url}" alt="{image.alt_text or ''}" />
          <div class="checkimg-tooltip" style="display:none;padding:8px;background:#111;color:#fff">
            <pre>{evidence}</pre>
          </div>
        </div>
        """
        return HTMLResponse(snippet)

    if not image.local_path:
        raise HTTPException(404, "Image file not available")
    if not risk:
        return Response(content=Path(image.local_path).read_bytes(), media_type="image/jpeg")
    data = render_tagged_image(image.local_path, risk)
    return Response(content=data, media_type="image/jpeg")


@router.post("/scan/{scan_id}/report")
def create_report(scan_id: int, db: Session = Depends(get_db)):
    try:
        pdf = generate_scan_report(db, scan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="scan-{scan_id}-report.pdf"'},
    )


@router.post("/scan/{scan_id}/images/{image_id}/exclude")
def exclude_image(
    scan_id: int,
    image_id: int,
    body: ExcludeImageRequest,
    db: Session = Depends(get_db),
):
    check = (
        db.query(CopyrightCheck)
        .join(Image)
        .join(Page)
        .filter(Image.id == image_id, Page.scan_id == scan_id)
        .first()
    )
    if not check:
        raise HTTPException(404, "Copyright check not found")
    check.excluded = True
    check.exclusion_reason = body.reason
    db.commit()
    return {"ok": True, "image_id": image_id}
