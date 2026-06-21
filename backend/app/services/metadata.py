"""EXIF/XMP metadata extraction via Pillow."""

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image as PILImage

from app.services.dmca_api import extract_dmca_protection_id
from app.services.sanitize import clean_text, sanitize_json

logger = logging.getLogger(__name__)


def extract_exif(local_path: str, site_domain: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "raw_metadata": {},
        "copyright_field": None,
        "artist": None,
        "rights": None,
        "description": None,
        "domain_mismatch": False,
        "dmca_protection_id": None,
        "camera_model": None,
    }
    path = Path(local_path)
    if not path.is_file():
        return result

    try:
        with PILImage.open(path) as img:
            exif = img.getexif()
            if exif:
                for tag_id, value in exif.items():
                    key = str(tag_id)
                    try:
                        from PIL.ExifTags import TAGS

                        key = TAGS.get(tag_id, key)
                    except ImportError:
                        pass
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", errors="ignore")
                    result["raw_metadata"][key] = clean_text(str(value), 2000)

            for k, v in (img.info or {}).items():
                result["raw_metadata"][str(k)] = clean_text(str(v), 2000)

            result["raw_metadata"] = sanitize_json(result["raw_metadata"])

            result["copyright_field"] = _first(result["raw_metadata"], "Copyright")
            result["artist"] = _first(result["raw_metadata"], "Artist")
            result["rights"] = _first(result["raw_metadata"], "Rights")
            result["description"] = _first(result["raw_metadata"], "ImageDescription")
            result["camera_model"] = _first(result["raw_metadata"], "Model")

            combined_meta = " ".join(str(v) for v in result["raw_metadata"].values())
            result["dmca_protection_id"] = extract_dmca_protection_id(combined_meta)
            if not result["dmca_protection_id"]:
                for field in (result["copyright_field"], result["rights"], result["description"]):
                    result["dmca_protection_id"] = extract_dmca_protection_id(field or "")
                    if result["dmca_protection_id"]:
                        break

            combined = " ".join(
                filter(None, [result["copyright_field"], result["artist"], result["rights"], result["description"]])
            ).lower()
            if combined and site_domain not in combined:
                foreign_domains = [d for d in _domains_in_text(combined) if site_domain not in d]
                result["domain_mismatch"] = bool(
                    foreign_domains or (combined and site_domain.split(".")[-2] not in combined)
                )
    except Exception as exc:
        logger.debug("EXIF parse failed for %s: %s", local_path, exc)

    return result


def _first(meta: dict[str, Any], key: str) -> str | None:
    for k, v in meta.items():
        if key.lower() in k.lower() and v:
            return clean_text(str(v), 512)
    val = meta.get(key)
    return clean_text(str(val), 512) if val else None


def _domains_in_text(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9-]+\.(?:com|org|net|ru|io|co)", text)
