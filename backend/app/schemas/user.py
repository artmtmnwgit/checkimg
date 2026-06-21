from datetime import datetime

from pydantic import BaseModel

from app.models import ScanStatus
from app.schemas.scan_options import KeysConfigured, ScanOptions


class UserSettingsResponse(BaseModel):
    settings: ScanOptions
    keys_configured: KeysConfigured


class ScanHistoryItem(BaseModel):
    id: int
    url: str
    status: ScanStatus
    depth: int
    pages_scanned: int
    images_found: int
    images_processed: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ScanHistoryResponse(BaseModel):
    items: list[ScanHistoryItem]
    total: int
