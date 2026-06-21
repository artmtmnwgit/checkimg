from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models import ScanStatus
from app.schemas.scan_options import KeysConfigured, ScanOptions


class UserSettingsResponse(BaseModel):
    settings: ScanOptions
    keys_configured: KeysConfigured


class ScanHistoryItem(BaseModel):
    token: str
    url: str
    status: ScanStatus
    depth: int
    pages_scanned: int
    images_found: int
    images_processed: int
    created_at: datetime
    options_summary: str = ""
    scan_options: dict[str, Any] | None = None
    share_enabled: bool = False


class ScanHistoryResponse(BaseModel):
    items: list[ScanHistoryItem]
    total: int
