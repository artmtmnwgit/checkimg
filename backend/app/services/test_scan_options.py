"""Self-check for scan option resolution."""
from app.schemas.scan_options import ScanOptions
from app.services.scan_options import (
    EffectiveScanOptions,
    ScanSecrets,
    public_scan_options,
    scan_options_defaults,
)


def main() -> None:
    defaults, presets, keys_cfg = scan_options_defaults()
    assert presets["fast"].yandex_search is False
    assert presets["fast"].ai_search is False
    assert defaults.yandex_search is True

    fast = EffectiveScanOptions.from_model(presets["fast"])
    assert not fast.duckduckgo

    partial = ScanOptions(google_search=True, ai_search=False, gemini_api_key="test-key")
    eff = EffectiveScanOptions.from_model(partial)
    assert eff.google_search and not eff.ai_search

    secrets = ScanSecrets.for_scan(None)
    assert isinstance(secrets.gemini_api_key, str)

    stripped = public_scan_options(partial.model_dump())
    assert "gemini_api_key" not in (stripped or {})

    print("scan options self-check OK")


if __name__ == "__main__":
    main()
