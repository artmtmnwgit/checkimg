"""Self-check for human-readable flag reasons."""

from app.models import RiskLevel
from app.services.copyright_checker import _build_reasons


def _self_check() -> None:
    fusion = {
        "google": {"best_match_url": "https://shutterstock.com/x", "best_site_type": "microstock", "match_count": 1},
        "yandex": {"best_match_url": None, "match_count": 0},
        "stock_hits": [{"url": "https://shutterstock.com/x", "engine": "google"}],
        "match_count": 1,
    }
    reasons = _build_reasons(
        fusion,
        {"copyright_field": "Getty Images"},
        {"detected": True, "details": "semi_transparent_corner"},
        {},
        RiskLevel.DANGER,
    )
    assert any("водяной" in r for r in reasons)
    assert any("Google" in r or "Сток" in r for r in reasons)
    assert any("Copyright" in r for r in reasons)
    assert _build_reasons({}, {}, {}, {}, RiskLevel.SAFE) == []

    dmca_reasons = _build_reasons({}, {}, {}, {"pirate_blacklist": {"listed": True, "domain": "1337x.to"}}, RiskLevel.PIRACY_BLACKLIST)
    assert any("Blacklist" in r or "чёрном списке" in r for r in dmca_reasons)


if __name__ == "__main__":
    _self_check()
    print("copyright reasons self-check OK")
