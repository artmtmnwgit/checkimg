from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models import SiteScan, User
from app.schemas.scan_options import ScanOptions
from app.schemas.user import ScanHistoryItem, ScanHistoryResponse, UserSettingsResponse
from app.services.scan_options import options_to_json, public_scan_options, scan_options_defaults, scan_options_summary, user_settings_from_db

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/settings", response_model=UserSettingsResponse)
def get_settings(user: User = Depends(get_current_user)):
    defaults, _, keys_configured = scan_options_defaults()
    settings = user_settings_from_db(user.settings, defaults)
    return UserSettingsResponse(settings=settings, keys_configured=keys_configured)


@router.put("/settings", response_model=UserSettingsResponse)
def save_settings(
    body: ScanOptions,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user.settings = options_to_json(body)
    db.commit()
    db.refresh(user)
    _, _, keys_configured = scan_options_defaults()
    return UserSettingsResponse(settings=body, keys_configured=keys_configured)


@router.get("/scans", response_model=ScanHistoryResponse)
def list_scans(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    total = db.query(func.count(SiteScan.id)).filter(SiteScan.user_id == user.id).scalar() or 0
    rows = (
        db.query(SiteScan)
        .filter(SiteScan.user_id == user.id)
        .order_by(desc(SiteScan.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    return ScanHistoryResponse(
        items=[
            ScanHistoryItem(
                token=s.token,
                url=s.url,
                status=s.status,
                depth=s.depth,
                pages_scanned=s.pages_scanned,
                images_found=s.images_found,
                images_processed=s.images_processed,
                created_at=s.created_at,
                options_summary=scan_options_summary(s.scan_options),
                scan_options=public_scan_options(s.scan_options),
                share_enabled=s.share_enabled,
            )
            for s in rows
        ],
        total=total,
    )
