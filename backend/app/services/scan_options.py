"""Resolve effective check options + API keys for a scan."""

from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.models import SiteScan
from app.schemas.scan_options import SCAN_API_KEYS, SCAN_TOGGLES, KeysConfigured, ScanOptions


@dataclass(frozen=True)
class EffectiveScanOptions:
    google_search: bool
    yandex_search: bool
    match_verify: bool
    dmca_checks: bool
    dmca_lumen_per_image: bool
    ai_search: bool
    duckduckgo: bool
    huggingface: bool
    gemini: bool
    tineye: bool
    perplexity: bool
    copilot: bool

    @classmethod
    def from_settings(cls) -> "EffectiveScanOptions":
        s = get_settings()
        return cls(
            google_search=True,
            yandex_search=s.yandex_search_enabled,
            match_verify=s.match_verify_enabled,
            dmca_checks=s.dmca_checks_enabled,
            dmca_lumen_per_image=s.dmca_lumen_per_image,
            ai_search=s.ai_search_enabled,
            duckduckgo=s.duckduckgo_search_enabled,
            huggingface=s.huggingface_enabled,
            gemini=bool(s.gemini_api_key),
            tineye=s.tineye_enabled,
            perplexity=s.perplexity_enabled,
            copilot=s.copilot_enabled,
        )

    @classmethod
    def from_model(cls, model: ScanOptions) -> "EffectiveScanOptions":
        data = model.model_dump(include=set(SCAN_TOGGLES))
        return cls(**data)

    @classmethod
    def for_scan(cls, scan: SiteScan | None) -> "EffectiveScanOptions":
        raw = getattr(scan, "scan_options", None) if scan else None
        if raw:
            return cls.from_model(ScanOptions.model_validate(raw))
        return cls.from_settings()


@dataclass(frozen=True)
class ScanSecrets:
    gemini_api_key: str
    huggingface_api_token: str
    tineye_api_key: str
    tineye_api_secret: str
    dmca_api_key: str
    serpapi_key: str

    @classmethod
    def from_settings(cls) -> "ScanSecrets":
        s = get_settings()
        return cls(
            gemini_api_key=s.gemini_api_key,
            huggingface_api_token=s.huggingface_api_token,
            tineye_api_key=s.tineye_api_key,
            tineye_api_secret=s.tineye_api_secret,
            dmca_api_key=s.dmca_api_key,
            serpapi_key=s.serpapi_key,
        )

    @classmethod
    def for_scan(cls, scan: SiteScan | None) -> "ScanSecrets":
        base = cls.from_settings()
        if not scan or not scan.scan_options:
            return base
        opts = ScanOptions.model_validate(scan.scan_options)

        def pick(scan_val: str, env_val: str) -> str:
            return scan_val.strip() if scan_val and scan_val.strip() else env_val

        return cls(
            gemini_api_key=pick(opts.gemini_api_key, base.gemini_api_key),
            huggingface_api_token=pick(opts.huggingface_api_token, base.huggingface_api_token),
            tineye_api_key=pick(opts.tineye_api_key, base.tineye_api_key),
            tineye_api_secret=pick(opts.tineye_api_secret, base.tineye_api_secret),
            dmca_api_key=pick(opts.dmca_api_key, base.dmca_api_key),
            serpapi_key=pick(opts.serpapi_key, base.serpapi_key),
        )


def keys_configured_from_env() -> KeysConfigured:
    s = get_settings()
    return KeysConfigured(
        gemini=bool(s.gemini_api_key),
        huggingface=bool(s.huggingface_api_token),
        tineye=bool(s.tineye_api_key and s.tineye_api_secret),
        dmca=bool(s.dmca_api_key),
        serpapi=bool(s.serpapi_key),
    )


def scan_options_defaults() -> tuple[ScanOptions, dict[str, ScanOptions], KeysConfigured]:
    eff = EffectiveScanOptions.from_settings()
    defaults = ScanOptions(**eff.__dict__)
    fast = ScanOptions(
        google_search=True,
        yandex_search=False,
        match_verify=False,
        dmca_checks=True,
        dmca_lumen_per_image=False,
        ai_search=False,
        duckduckgo=False,
        huggingface=False,
        gemini=False,
        tineye=False,
        perplexity=False,
        copilot=False,
    )
    return defaults, {"full": defaults, "fast": fast}, keys_configured_from_env()


def options_to_json(opts: ScanOptions | None) -> dict[str, Any] | None:
    return opts.model_dump() if opts else None


def public_scan_options(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip API keys before sending scan_options to the client."""
    if not raw:
        return None
    return {k: v for k, v in raw.items() if k not in SCAN_API_KEYS}
