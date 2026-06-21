"""Self-check for AI search signal derivation and fusion hooks."""

from app.models import RiskLevel
from app.services.ai_search_evidence import _derive_signals, merge_ai_into_fusion
from app.services.search_fusion import aggregate_fusion_risk
from app.services.url_clean import clean_http_url


def _self_check() -> None:
    ai = {
        "gemini": {"source_type": "stock", "copyrighted": True},
        "huggingface": {
            "watermark": {"detected": True, "score": 0.85},
            "ai_generated": {"detected": False, "score": 0.2},
        },
        "perplexity": {"stock_mentions": True, "sources": []},
        "duckduckgo": {"match_count": 12, "matches": [], "stock_hits": []},
    }
    signals = _derive_signals(ai)
    assert signals["stock_photo_confirmed"]
    assert signals["wide_distribution"]

    ai_gen = {
        "huggingface": {"ai_generated": {"detected": True, "score": 0.9}},
        "signals": {"ai_generated": True},
    }
    assert aggregate_fusion_risk({}, {}, {"detected": False}, "x.com", {}, ai_gen) == RiskLevel.AI_GENERATED

    fusion = merge_ai_into_fusion(
        {"google": {}, "yandex": {}, "matches": [], "match_count": 0, "stock_hits": []},
        {
            "duckduckgo": {
                "matches": [{"url": "https://shutterstock.com/x.jpg", "is_stock": True, "engine": "duckduckgo"}],
                "match_count": 1,
                "stock_hits": [{"url": "https://shutterstock.com/x.jpg", "is_stock": True}],
            }
        },
    )
    assert fusion["match_count"] == 1

    assert clean_http_url("https://example.com/a.jpg&amp;quot") == "https://example.com/a.jpg"


if __name__ == "__main__":
    _self_check()
    print("ai search self-check OK")
