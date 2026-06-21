"""Fusion risk scoring from multi-engine search + EXIF + watermark + DMCA + AI."""

from app.models import RiskLevel
from app.services.source_types import DANGER_SITE_TYPES, WARNING_SITE_TYPES


def _has_engine_match(fusion: dict) -> bool:
    google = fusion.get("google") or {}
    yandex = fusion.get("yandex") or {}
    if google.get("best_match_url") or yandex.get("best_match_url"):
        return True
    return bool(fusion.get("stock_hits"))


def _has_exact_stock(fusion: dict) -> bool:
    google = fusion.get("google") or {}
    yandex = fusion.get("yandex") or {}
    if google.get("best_site_type") in DANGER_SITE_TYPES and google.get("best_match_kind") == "exact":
        return True
    if yandex.get("best_site_type") in DANGER_SITE_TYPES and yandex.get("best_match_kind") == "exact":
        return True
    return any(m.get("match_kind") == "exact" for m in fusion.get("stock_hits") or [])


def _has_similar_stock(fusion: dict) -> bool:
    google = fusion.get("google") or {}
    yandex = fusion.get("yandex") or {}
    if google.get("best_site_type") in DANGER_SITE_TYPES and google.get("best_match_kind") == "similar":
        return True
    if yandex.get("best_site_type") in DANGER_SITE_TYPES and yandex.get("best_match_kind") == "similar":
        return True
    return any(m.get("match_kind") == "similar" for m in fusion.get("stock_hits") or [])


def _has_unverified_stock(fusion: dict) -> bool:
    if _has_exact_stock(fusion) or _has_similar_stock(fusion):
        return False
    google = fusion.get("google") or {}
    yandex = fusion.get("yandex") or {}
    if google.get("best_site_type") in DANGER_SITE_TYPES and google.get("best_match_url"):
        return True
    if yandex.get("best_site_type") in DANGER_SITE_TYPES and yandex.get("best_match_url"):
        return True
    return bool(fusion.get("stock_hits"))


STOCK_WATERMARK_TYPES = frozenset(
    {"shutterstock", "getty", "adobe_stock", "depositphotos", "dreamstime", "123rf", "alamy"}
)


def _watermark_risk(watermark: dict) -> RiskLevel | None:
    if not watermark.get("detected"):
        return None
    conf = float(watermark.get("confidence") or 0)
    wm_type = watermark.get("watermark_type") or ""
    if wm_type in STOCK_WATERMARK_TYPES:
        return RiskLevel.DANGER
    if conf >= 0.75:
        return RiskLevel.DANGER
    return RiskLevel.WARNING


def _ai_generated(ai: dict) -> bool:
    signals = ai.get("signals") or {}
    if signals.get("ai_generated"):
        return True
    hf = ai.get("huggingface") or {}
    return bool((hf.get("ai_generated") or {}).get("detected"))


def _ai_perplexity_stock(ai: dict) -> bool:
    return bool((ai.get("perplexity") or {}).get("stock_mentions"))


def _ai_multi_stock_confirmed(ai: dict) -> bool:
    return bool((ai.get("signals") or {}).get("stock_photo_confirmed"))


def _ai_gemini_stock(ai: dict) -> bool:
    gemini = ai.get("gemini") or {}
    return gemini.get("source_type") in ("stock", "microstock") or bool(gemini.get("copyrighted"))


def _ai_ddg_wide(ai: dict) -> bool:
    return bool((ai.get("signals") or {}).get("wide_distribution"))


def aggregate_fusion_risk(
    fusion: dict,
    exif: dict,
    watermark: dict,
    site_domain: str,
    dmca: dict | None = None,
    ai: dict | None = None,
) -> RiskLevel:
    dmca = dmca or {}
    ai = ai or {}
    google = fusion.get("google") or {}
    yandex = fusion.get("yandex") or {}
    match_count = fusion.get("match_count", 0)
    exact_count = fusion.get("exact_match_count", 0) or google.get("exact_count", 0) + yandex.get("exact_count", 0)

    if dmca.get("pirate_blacklist", {}).get("listed"):
        return RiskLevel.PIRACY_BLACKLIST
    if dmca.get("lumen", {}).get("infringing_match"):
        return RiskLevel.DMCA_VIOLATION

    protection = dmca.get("protection_id") or {}
    if protection.get("verified") or watermark.get("watermark_type") == "dmca":
        return RiskLevel.DMCA_PROTECTED
    if exif.get("dmca_protection_id") and protection.get("id"):
        return RiskLevel.DMCA_PROTECTED

    if _ai_generated(ai):
        return RiskLevel.AI_GENERATED

    if _ai_perplexity_stock(ai) or _ai_multi_stock_confirmed(ai):
        return RiskLevel.DANGER

    wm_risk = _watermark_risk(watermark)
    if wm_risk == RiskLevel.DANGER:
        return RiskLevel.DANGER

    if yandex.get("buy_pattern"):
        if _has_exact_stock(fusion) or _has_engine_match(fusion):
            return RiskLevel.DANGER
        return RiskLevel.WARNING

    on_exact_stock = _has_exact_stock(fusion)
    on_similar_stock = _has_similar_stock(fusion)
    on_unverified_stock = _has_unverified_stock(fusion) and not on_exact_stock and not on_similar_stock

    if exif.get("copyright_field") and exif.get("domain_mismatch"):
        return RiskLevel.DANGER if on_exact_stock else RiskLevel.SUSPECT

    if on_exact_stock:
        return RiskLevel.SUSPECT

    if wm_risk == RiskLevel.WARNING:
        return RiskLevel.WARNING

    if on_similar_stock:
        return RiskLevel.WARNING

    if on_unverified_stock:
        return RiskLevel.WARNING

    if yandex.get("best_site_type") in WARNING_SITE_TYPES:
        return RiskLevel.WARNING
    if google.get("best_site_type") in WARNING_SITE_TYPES:
        return RiskLevel.WARNING
    if yandex.get("match_count", 0) >= 10:
        return RiskLevel.WARNING
    if match_count > 0 or exact_count > 0:
        return RiskLevel.WARNING
    if dmca.get("google_transparency", {}).get("has_removals"):
        return RiskLevel.WARNING
    if dmca.get("lumen", {}).get("found"):
        return RiskLevel.WARNING
    if exif.get("domain_mismatch"):
        return RiskLevel.WARNING

    if _ai_gemini_stock(ai):
        return RiskLevel.WARNING

    if _ai_ddg_wide(ai):
        return RiskLevel.WARNING

    return RiskLevel.SAFE
