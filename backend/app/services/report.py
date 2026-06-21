"""PDF risk report generation."""

import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session, joinedload

from app.models import Image, Page, RiskLevel, SiteScan


def generate_scan_report(db: Session, scan_id: int) -> bytes:
    scan = db.get(SiteScan, scan_id)
    if not scan:
        raise ValueError("Scan not found")

    pages = (
        db.query(Page)
        .options(joinedload(Page.images).joinedload(Image.copyright_check))
        .filter(Page.scan_id == scan_id)
        .all()
    )

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 2 * cm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, y, "Copyright Scan Report")
    y -= 1 * cm
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y, f"URL: {scan.url}")
    y -= 0.5 * cm
    c.drawString(2 * cm, y, f"Generated: {datetime.utcnow().isoformat()}Z")
    y -= 1 * cm

    counts = {level: 0 for level in RiskLevel}
    for page in pages:
        for img in page.images:
            if img.copyright_check and not img.copyright_check.excluded:
                counts[img.copyright_check.risk_level] += 1

    summary_parts = [f"{level.value}: {counts[level]}" for level in RiskLevel if counts[level]]
    c.drawString(2 * cm, y, "  ".join(summary_parts) or "No results")
    y -= 1.5 * cm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, "Flagged images")
    y -= 0.8 * cm
    c.setFont("Helvetica", 9)

    for page in pages:
        for img in page.images:
            check = img.copyright_check
            if not check or check.risk_level == RiskLevel.SAFE or check.excluded:
                continue
            line = f"[{check.risk_level.value}] {img.src_url[:90]}"
            if y < 2 * cm:
                c.showPage()
                y = height - 2 * cm
                c.setFont("Helvetica", 9)
            c.drawString(2 * cm, y, line)
            y -= 0.45 * cm

    c.save()
    return buf.getvalue()
