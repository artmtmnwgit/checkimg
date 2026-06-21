from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.models import RiskLevel, ScanStatus


from app.schemas.scan_options import ScanOptions


class ScanCreateRequest(BaseModel):
    url: HttpUrl
    depth: int = Field(default=3, ge=1, le=10)
    options: ScanOptions | None = None


class ScanCreateResponse(BaseModel):
    token: str
    status: ScanStatus
    url: str
    depth: int


class ScanStatusResponse(BaseModel):
    token: str
    url: str
    status: ScanStatus
    depth: int
    depth_reached: int = 0
    share_enabled: bool = False
    scan_options: dict[str, Any] | None = None
    pages_scanned: int
    images_found: int
    images_processed: int
    progress_pct: float
    error_message: str | None
    created_at: datetime


class ExifDataOut(BaseModel):
    copyright_field: str | None
    artist: str | None
    rights: str | None
    description: str | None
    domain_mismatch: bool

    model_config = {"from_attributes": True}


class CopyrightCheckOut(BaseModel):
    risk_level: RiskLevel
    source_evidence: dict[str, Any] | None
    dmca_evidence: dict[str, Any] | None = None
    excluded: bool
    exclusion_reason: str | None

    model_config = {"from_attributes": True}


class ImageResultOut(BaseModel):
    id: int
    src_url: str
    alt_text: str | None
    file_hash: str | None
    width: int | None
    height: int | None
    copyright_check: CopyrightCheckOut | None
    exif_data: ExifDataOut | None

    model_config = {"from_attributes": True}


class PageResultOut(BaseModel):
    id: int
    url: str
    images: list[ImageResultOut]

    model_config = {"from_attributes": True}


class ScanResultsResponse(BaseModel):
    scan_token: str
    url: str
    status: ScanStatus
    pages: list[PageResultOut]
    summary: dict[str, int]


class ExcludeImageRequest(BaseModel):
    reason: str | None = None


class ShareScanResponse(BaseModel):
    share_enabled: bool
    share_url: str
