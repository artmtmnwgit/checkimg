import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base

# ponytail: JSON on SQLite, JSONB on Postgres — same API, no dialect branching in app code
JsonType = JSON().with_variant(JSONB, "postgresql")


class ScanStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    DONE = "done"
    FAILED = "failed"


class PageStatus(str, enum.Enum):
    PENDING = "pending"
    SCANNED = "scanned"
    FAILED = "failed"


class RiskLevel(str, enum.Enum):
    SAFE = "safe"
    WARNING = "warning"
    SUSPECT = "suspect"
    DANGER = "danger"
    DMCA_PROTECTED = "dmca_protected"
    DMCA_VIOLATION = "dmca_violation"
    PIRACY_BLACKLIST = "piracy_blacklist"
    AI_GENERATED = "ai_generated"


class SiteScan(Base):
    __tablename__ = "site_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status", native_enum=False),
        default=ScanStatus.PENDING,
        nullable=False,
    )
    pages_scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    images_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    images_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    dmca_site_data: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    scan_options: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    pages: Mapped[list["Page"]] = relationship(back_populates="scan", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("site_scans.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[PageStatus] = mapped_column(
        Enum(PageStatus, name="page_status", native_enum=False),
        default=PageStatus.PENDING,
        nullable=False,
    )

    scan: Mapped["SiteScan"] = relationship(back_populates="pages")
    images: Mapped[list["Image"]] = relationship(back_populates="page", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("scan_id", "url", name="uq_page_scan_url"),)


class Image(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    src_url: Mapped[str] = mapped_column(String(4096), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    page: Mapped["Page"] = relationship(back_populates="images")
    copyright_check: Mapped["CopyrightCheck | None"] = relationship(
        back_populates="image", uselist=False, cascade="all, delete-orphan"
    )
    exif_data: Mapped["ExifData | None"] = relationship(
        back_populates="image", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("page_id", "src_url", name="uq_image_page_src"),)


class CopyrightCheck(Base):
    __tablename__ = "copyright_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level", native_enum=False),
        default=RiskLevel.SAFE,
        nullable=False,
    )
    source_evidence: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    dmca_evidence: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    excluded: Mapped[bool] = mapped_column(default=False, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    image: Mapped["Image"] = relationship(back_populates="copyright_check")


class ExifData(Base):
    __tablename__ = "exif_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    copyright_field: Mapped[str | None] = mapped_column(String(512), nullable=True)
    artist: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rights: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain_mismatch: Mapped[bool] = mapped_column(default=False, nullable=False)

    image: Mapped["Image"] = relationship(back_populates="exif_data")
