"""Orchestrate copyright + DMCA checks and persist results."""

import asyncio
import logging
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CopyrightCheck, ExifData, Image, RiskLevel, SiteScan
from app.services.ai_search_evidence import gather_ai_search_evidence, merge_ai_into_fusion
from app.services.dmca_api import extract_dmca_protection_id, verify_protection_id
from app.services.dmca_domain import check_lumen
from app.services.match_verify import verify_fusion_matches
from app.services.metadata import extract_exif
from app.services.reverse_image_search import multi_engine_reverse_search
from app.services.scan_control import check_control
from app.services.scan_options import EffectiveScanOptions, ScanSecrets
from app.services.search_fusion import aggregate_fusion_risk
from app.services.sanitize import sanitize_json
from app.services.source_types import DANGER_SITE_TYPES, WARNING_SITE_TYPES
from app.services.url_clean import clean_http_url
from app.services.watermark import detect_watermark

settings = get_settings()
logger = logging.getLogger(__name__)

SITE_TYPE_RU = {
    "photobank": "фотобанк",
    "microstock": "микросток",
    "social": "соцсеть",
    "marketplace": "маркетплейс",
    "news": "новости",
    "other": "другой источник",
}

RISK_RU = {
    RiskLevel.DMCA_VIOLATION: "DMCA: URL в базе Lumen (infringing)",
    RiskLevel.PIRACY_BLACKLIST: "Домен в чёрном списке пиратских сайтов",
    RiskLevel.DMCA_PROTECTED: "Изображение защищено DMCA.com",
    RiskLevel.SUSPECT: "Подозрение на нарушение (сток/EXIF без ватермарки)",
    RiskLevel.AI_GENERATED: "Изображение вероятно сгенерировано нейросетью",
}

MATCH_KIND_RU = {
    "exact": "точная копия",
    "similar": "визуально похожее",
    "unverified": "не проверено визуально",
    "weak": "слабое сходство",
}


def _match_label(engine: dict) -> str:
    kind = engine.get("best_match_kind") or "unverified"
    score = engine.get("best_similarity_score")
    label = MATCH_KIND_RU.get(kind, kind)
    if score is not None:
        return f"{label} ({int(score * 100)}%)"
    return label

_EMPTY_FUSION = {"google": {}, "yandex": {}, "match_count": 0, "stock_hits": []}


def _reason_url(raw: str | None) -> str:
    if not raw:
        return ""
    return clean_http_url(raw) or raw


def _build_reasons(
    fusion: dict,
    exif: dict,
    watermark: dict,
    dmca: dict,
    risk: RiskLevel,
    ai: dict | None = None,
) -> list[str]:
    if risk == RiskLevel.SAFE:
        return []

    reasons: list[str] = []
    if risk in RISK_RU:
        reasons.append(RISK_RU[risk])

    google = fusion.get("google") or {}
    yandex = fusion.get("yandex") or {}

    if dmca.get("lumen", {}).get("infringing_match"):
        notices = dmca["lumen"].get("notices") or []
        if notices:
            reasons.append(f"Lumen Database: notice #{notices[0].get('id')}")

    if dmca.get("pirate_blacklist", {}).get("listed"):
        reasons.append(f"Blacklist: {dmca['pirate_blacklist'].get('domain', '')}")

    protection = dmca.get("protection_id") or {}
    if protection.get("verified"):
        reasons.append(f"DMCA Protection ID подтверждён: {protection.get('id')}")
    elif exif.get("dmca_protection_id"):
        reasons.append(f"EXIF DMCA ID (не подтверждён): {exif['dmca_protection_id']}")

    gt = dmca.get("google_transparency") or {}
    if gt.get("has_removals"):
        reasons.append(f"Google Transparency: {gt.get('removal_count', '?')} удалений по домену")

    if watermark.get("detected"):
        wm_type = watermark.get("watermark_type") or watermark.get("details") or "overlay"
        conf = watermark.get("confidence")
        conf_txt = f", уверенность {int(conf * 100)}%" if conf else ""
        reasons.append(f"Эвристика водяного знака ({wm_type}{conf_txt}) — не совпадение в Google/Яндекс")

    if yandex.get("buy_pattern"):
        snip = yandex.get("text_snippet") or "паттерн «Купить…»"
        if not google.get("best_match_url") and not yandex.get("best_match_url"):
            reasons.append(f"Яндекс: текст стока в выдаче (без URL совпадения) — {snip[:120]}")
        else:
            reasons.append(f"Яндекс: признак стока — {snip[:120]}")

    y_type = yandex.get("best_site_type")
    if y_type in DANGER_SITE_TYPES and yandex.get("best_match_url"):
        label = SITE_TYPE_RU.get(y_type, y_type)
        reasons.append(f"Яндекс: {label} ({_match_label(yandex)}) — {_reason_url(yandex.get('best_match_url'))}")

    g_type = google.get("best_site_type")
    if g_type in DANGER_SITE_TYPES and google.get("best_match_url"):
        label = SITE_TYPE_RU.get(g_type, g_type)
        title = google.get("title") or ""
        reasons.append(
            f"Google: {label} ({_match_label(google)}) — {_reason_url(google.get('best_match_url'))}"
            + (f" ({title})" if title else "")
        )

    for hit in (fusion.get("stock_hits") or [])[:2]:
        engine = hit.get("engine", "")
        kind = hit.get("match_kind") or "unverified"
        kind_ru = MATCH_KIND_RU.get(kind, kind)
        reasons.append(f"Сток [{engine}, {kind_ru}]: {_reason_url(hit.get('url'))}")

    if exif.get("copyright_field"):
        reasons.append(f"EXIF Copyright: {exif['copyright_field']}")
    if exif.get("artist"):
        reasons.append(f"EXIF Artist: {exif['artist']}")
    if exif.get("rights"):
        reasons.append(f"EXIF Rights: {exif['rights']}")
    if exif.get("domain_mismatch"):
        reasons.append("Метаданные не совпадают с доменом сайта")

    if risk == RiskLevel.WARNING:
        if y_type in WARNING_SITE_TYPES and yandex.get("best_match_url"):
            label = SITE_TYPE_RU.get(y_type, y_type)
            reasons.append(f"Яндекс: {_match_label(yandex)} ({label}) — {_reason_url(yandex.get('best_match_url'))}")
        if yandex.get("similar_count") and not yandex.get("exact_count"):
            reasons.append("Яндекс: только похожие изображения, точной копии не подтверждено")
        if google.get("similar_count") and not google.get("exact_count") and google.get("best_match_url"):
            reasons.append("Google: только похожие изображения, точной копии не подтверждено")
        if yandex.get("match_count", 0) >= 10:
            reasons.append(f"Яндекс: широкое распространение ({yandex['match_count']} совпадений)")
        if google.get("match_count", 0) and len(reasons) <= 2:
            reasons.append(f"Google: найдены похожие изображения ({google['match_count']})")

    site_sig = dmca.get("site_signals") or {}
    if site_sig.get("has_dmca_badge"):
        reasons.append("На сайте обнаружен DMCA-badge")
    for hit in (site_sig.get("footer_text_hits") or [])[:2]:
        reasons.append(f"Футер: {hit}")

    ai = ai or {}
    signals = ai.get("signals") or {}
    gemini = ai.get("gemini") or {}
    hf = ai.get("huggingface") or {}
    tineye = ai.get("tineye") or {}
    ddg = ai.get("duckduckgo") or {}

    if signals.get("ai_generated"):
        score = (hf.get("ai_generated") or {}).get("score")
        txt = f" ({int(score * 100)}%)" if score else ""
        reasons.append(f"AI-generated (Hugging Face{txt})")
    if gemini.get("source_type") in ("stock", "microstock") or gemini.get("copyrighted"):
        reasons.append(f"Gemini: вероятно сток — {gemini.get('reasoning', '')[:120]}")
    if (hf.get("watermark") or {}).get("detected"):
        reasons.append("Hugging Face: обнаружен водяной знак")
    if (ai.get("perplexity") or {}).get("stock_mentions"):
        reasons.append("Perplexity: упоминание стоковых источников")
    if (ai.get("copilot") or {}).get("stock_mentions"):
        reasons.append("Copilot/Bing: упоминание стоковых источников")
    if ddg.get("match_count", 0) > 10:
        reasons.append(f"DuckDuckGo: широкое распространение ({ddg['match_count']} копий)")
    earliest = tineye.get("earliest_match")
    if earliest and earliest.get("url"):
        date = earliest.get("first_seen") or "?"
        reasons.append(f"TinEye: ранняя индексация ({date}) — {_reason_url(earliest.get('url'))}")

    return reasons


def _risk_drivers(
    fusion: dict,
    exif: dict,
    watermark: dict,
    dmca: dict,
    risk: RiskLevel,
    ai: dict | None = None,
) -> list[str]:
    """Short labels for UI — why risk without Google/Yandex URL."""
    drivers: list[str] = []
    google = fusion.get("google") or {}
    yandex = fusion.get("yandex") or {}

    if watermark.get("detected"):
        drivers.append("watermark_heuristic")
    if yandex.get("buy_pattern") and not yandex.get("best_match_url"):
        drivers.append("yandex_text_only")
    if exif.get("domain_mismatch"):
        drivers.append("exif_mismatch")
    if exif.get("copyright_field"):
        drivers.append("exif_copyright")
    if dmca.get("pirate_blacklist", {}).get("listed"):
        drivers.append("pirate_blacklist")
    if dmca.get("lumen", {}).get("infringing_match"):
        drivers.append("lumen")
    if google.get("best_match_url") or yandex.get("best_match_url"):
        drivers.append("reverse_search")
    ai = ai or {}
    if (ai.get("signals") or {}).get("ai_generated"):
        drivers.append("ai_generated")
    if (ai.get("signals") or {}).get("stock_photo_confirmed"):
        drivers.append("ai_stock")
    elif risk not in (RiskLevel.SAFE,) and not drivers:
        drivers.append("other")
    return drivers


async def _build_dmca_evidence(
    image_url: str,
    exif: dict,
    site_domain_dmca: dict,
    site_signals: dict | None,
    caches: dict,
    opts: EffectiveScanOptions,
    secrets: ScanSecrets,
) -> dict:
    dmca = dict(site_domain_dmca)

    if opts.dmca_lumen_per_image and image_url:
        lumen_cache = caches.setdefault("lumen_url", {})
        if image_url not in lumen_cache:
            try:
                lumen_cache[image_url] = await check_lumen(image_url, terms=[image_url])
            except Exception as exc:
                logger.warning("per-image lumen failed: %s", exc)
                lumen_cache[image_url] = {"error": str(exc)}
        dmca["lumen"] = lumen_cache[image_url]

    protection_id = exif.get("dmca_protection_id")
    if not protection_id and site_signals:
        for meta in site_signals.get("meta_tags") or []:
            protection_id = extract_dmca_protection_id(meta.get("content") or "")
            if protection_id:
                break

    if protection_id:
        pid_cache = caches.setdefault("protection_id", {})
        if protection_id not in pid_cache:
            try:
                pid_cache[protection_id] = await verify_protection_id(
                    protection_id, dmca_api_key=secrets.dmca_api_key
                )
            except Exception as exc:
                pid_cache[protection_id] = {"id": protection_id, "verified": False, "error": str(exc)}
        dmca["protection_id"] = pid_cache[protection_id]
    else:
        dmca["protection_id"] = {"id": None, "verified": False}

    if site_signals:
        dmca["site_signals"] = site_signals
    return dmca


def _compact_ai_evidence(ai: dict) -> dict:
    """Trim large match lists for JSON storage."""
    if not ai:
        return {}
    out = dict(ai)
    for key in ("tineye", "duckduckgo"):
        block = out.get(key)
        if isinstance(block, dict) and block.get("matches"):
            block = dict(block)
            block["matches"] = block["matches"][:10]
            out[key] = block
    for key in ("perplexity", "copilot"):
        block = out.get(key)
        if isinstance(block, dict) and block.get("sources"):
            block = dict(block)
            block["sources"] = block["sources"][:10]
            out[key] = block
    return out


async def gather_external_evidence(
    image_url: str,
    local_path: str,
    site_domain: str,
    site_domain_dmca: dict,
    site_signals: dict | None,
    caches: dict,
    opts: EffectiveScanOptions | None = None,
    secrets: ScanSecrets | None = None,
) -> tuple[dict, dict, dict, dict, dict]:
    """Network + CPU checks — no DB. Safe to run in parallel."""
    opts = opts or EffectiveScanOptions.from_settings()
    secrets = secrets or ScanSecrets.from_settings()
    exif_result = extract_exif(local_path, site_domain) if local_path else {}
    watermark_result = detect_watermark(local_path) if local_path else {"detected": False}

    async def _fusion() -> dict:
        if not image_url or not (opts.google_search or opts.yandex_search):
            return _EMPTY_FUSION
        try:
            raw = await multi_engine_reverse_search(image_url, opts, serpapi_key=secrets.serpapi_key)
            if local_path and opts.match_verify:
                return await verify_fusion_matches(local_path, raw, opts, image_url)
            return raw
        except Exception as exc:
            logger.warning("reverse search failed for %s: %s", image_url, exc)
            return {**_EMPTY_FUSION, "error": str(exc)}

    async def _dmca() -> dict:
        if not opts.dmca_checks:
            return {}
        try:
            return await _build_dmca_evidence(
                image_url, exif_result, site_domain_dmca, site_signals, caches, opts, secrets
            )
        except Exception as exc:
            logger.warning("DMCA evidence failed for %s: %s", image_url, exc)
            return {"error": str(exc)}

    async def _ai() -> dict:
        if not opts.ai_search:
            return {}
        try:
            return await gather_ai_search_evidence(image_url, local_path, caches, opts, secrets)
        except Exception as exc:
            logger.warning("AI search failed for %s: %s", image_url, exc)
            return {"error": str(exc)}

    fusion, dmca_evidence, ai_evidence = await asyncio.gather(_fusion(), _dmca(), _ai())
    fusion = merge_ai_into_fusion(fusion, ai_evidence)
    return fusion, exif_result, watermark_result, dmca_evidence, ai_evidence


def persist_copyright_check(
    db: Session,
    scan: SiteScan,
    image: Image,
    fusion: dict,
    exif_result: dict,
    watermark_result: dict,
    dmca_evidence: dict,
    ai_search_evidence: dict | None = None,
) -> CopyrightCheck:
    check_control(db, scan.id)
    site_domain = urlparse(str(scan.url)).netloc.lower()
    ai_search_evidence = ai_search_evidence or {}

    risk = aggregate_fusion_risk(
        fusion, exif_result, watermark_result, site_domain, dmca_evidence, ai_search_evidence
    )
    reasons = _build_reasons(fusion, exif_result, watermark_result, dmca_evidence, risk, ai_search_evidence)
    drivers = _risk_drivers(fusion, exif_result, watermark_result, dmca_evidence, risk, ai_search_evidence)

    google = fusion.get("google") or {}
    yandex = fusion.get("yandex") or {}
    evidence = sanitize_json({
        "reasons": reasons,
        "risk_drivers": drivers,
        "has_search_match": bool(google.get("best_match_url") or yandex.get("best_match_url")),
        "google": {
            "best_match_url": google.get("best_match_url"),
            "title": google.get("title"),
            "site_type": google.get("best_site_type"),
            "match_count": google.get("match_count", 0),
            "stock_hits": google.get("stock_hits", []),
            "best_match_kind": google.get("best_match_kind"),
            "best_similarity_score": google.get("best_similarity_score"),
            "exact_count": google.get("exact_count", 0),
            "similar_count": google.get("similar_count", 0),
        },
        "yandex": {
            "best_match_url": yandex.get("best_match_url"),
            "site_type": yandex.get("best_site_type"),
            "text_snippet": yandex.get("text_snippet"),
            "match_count": yandex.get("match_count", 0),
            "buy_pattern": yandex.get("buy_pattern", False),
            "stock_hits": yandex.get("stock_hits", []),
            "best_match_kind": yandex.get("best_match_kind"),
            "best_similarity_score": yandex.get("best_similarity_score"),
            "exact_count": yandex.get("exact_count", 0),
            "similar_count": yandex.get("similar_count", 0),
        },
        "match_verify": {
            "exact": fusion.get("exact_match_count", 0),
            "similar": fusion.get("similar_match_count", 0),
            "weak_filtered": fusion.get("weak_match_count", 0),
        },
        "watermark": watermark_result,
        "exif_summary": {
            "copyright": exif_result.get("copyright_field"),
            "artist": exif_result.get("artist"),
            "rights": exif_result.get("rights"),
            "domain_mismatch": exif_result.get("domain_mismatch"),
            "dmca_protection_id": exif_result.get("dmca_protection_id"),
            "camera_model": exif_result.get("camera_model"),
        },
        "ai_search_evidence": sanitize_json(_compact_ai_evidence(ai_search_evidence)),
        "ai_analysis": sanitize_json((ai_search_evidence.get("gemini") or {})),
    })
    dmca_evidence = sanitize_json(dmca_evidence)

    if image.exif_data:
        exif_row = image.exif_data
        exif_row.raw_metadata = sanitize_json(exif_result.get("raw_metadata"))
        exif_row.copyright_field = exif_result.get("copyright_field")
        exif_row.artist = exif_result.get("artist")
        exif_row.rights = exif_result.get("rights")
        exif_row.description = exif_result.get("description")
        exif_row.domain_mismatch = exif_result.get("domain_mismatch", False)
    else:
        db.add(
            ExifData(
                image_id=image.id,
                raw_metadata=sanitize_json(exif_result.get("raw_metadata")),
                copyright_field=exif_result.get("copyright_field"),
                artist=exif_result.get("artist"),
                rights=exif_result.get("rights"),
                description=exif_result.get("description"),
                domain_mismatch=exif_result.get("domain_mismatch", False),
            )
        )

    if image.copyright_check:
        check = image.copyright_check
        check.risk_level = risk
        check.source_evidence = evidence
        check.dmca_evidence = dmca_evidence
    else:
        check = CopyrightCheck(
            image_id=image.id,
            risk_level=risk,
            source_evidence=evidence,
            dmca_evidence=dmca_evidence,
        )
        db.add(check)

    db.commit()
    db.refresh(check)
    return check


def check_image_copyright(db: Session, scan: SiteScan, image: Image) -> CopyrightCheck:
    """Sync entry point — scan pipeline prefers gather + persist."""
    site_domain = urlparse(str(scan.url)).netloc.lower()
    site_data = scan.dmca_site_data or {}
    site_domain_dmca = site_data.get("domain_checks") or {}
    site_signals = site_data if site_data else None
    caches: dict = {}
    opts = EffectiveScanOptions.for_scan(scan)
    secrets = ScanSecrets.for_scan(scan)

    fusion, exif, wm, dmca, ai = asyncio.run(
        gather_external_evidence(
            image.src_url or "",
            image.local_path or "",
            site_domain,
            site_domain_dmca,
            site_signals,
            caches,
            opts,
            secrets,
        )
    )
    return persist_copyright_check(db, scan, image, fusion, exif, wm, dmca, ai)
