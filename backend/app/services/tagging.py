"""Generate tagged image previews with risk-colored borders."""

import io
from pathlib import Path

from PIL import Image, ImageDraw

from app.models import RiskLevel

BORDER_COLORS = {
    RiskLevel.SAFE: (34, 197, 94),
    RiskLevel.WARNING: (234, 179, 8),
    RiskLevel.SUSPECT: (249, 115, 22),
    RiskLevel.DANGER: (239, 68, 68),
    RiskLevel.DMCA_PROTECTED: (59, 130, 246),
    RiskLevel.DMCA_VIOLATION: (220, 38, 38),
    RiskLevel.PIRACY_BLACKLIST: (127, 29, 29),
    RiskLevel.AI_GENERATED: (168, 85, 247),
}


def render_tagged_image(local_path: str, risk_level: RiskLevel, border: int = 5) -> bytes:
    path = Path(local_path)
    if not path.is_file():
        raise FileNotFoundError(local_path)

    with Image.open(path).convert("RGB") as img:
        color = BORDER_COLORS.get(risk_level, BORDER_COLORS[RiskLevel.SAFE])
        w, h = img.size
        out = Image.new("RGB", (w + 2 * border, h + 2 * border), color)
        out.paste(img, (border, border))

        draw = ImageDraw.Draw(out)
        label = risk_level.value.upper()
        draw.rectangle([0, 0, min(120, w), 24], fill=color)
        draw.text((4, 4), label, fill=(255, 255, 255))

        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
