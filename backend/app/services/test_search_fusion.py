"""Self-check for fusion risk and match verification tiers."""

from app.models import RiskLevel
from app.services.search_fusion import aggregate_fusion_risk


def _self_check() -> None:
    exact_fusion = {
        "google": {
            "best_match_url": "https://lori.ru/y",
            "best_site_type": "photobank",
            "best_match_kind": "exact",
            "match_count": 1,
            "exact_count": 1,
        },
        "yandex": {"match_count": 0},
        "match_count": 1,
        "exact_match_count": 1,
        "stock_hits": [{"url": "https://lori.ru/y", "engine": "yandex", "match_kind": "exact"}],
    }
    assert aggregate_fusion_risk(exact_fusion, {}, {"detected": False}, "example.com") == RiskLevel.SUSPECT

    similar_fusion = {
        "google": {
            "best_match_url": "https://shutterstock.com/x",
            "best_site_type": "microstock",
            "best_match_kind": "similar",
            "similar_count": 1,
        },
        "yandex": {"match_count": 0},
        "match_count": 1,
        "similar_match_count": 1,
        "stock_hits": [],
    }
    assert aggregate_fusion_risk(similar_fusion, {}, {"detected": False}, "example.com") == RiskLevel.WARNING

    unverified_fusion = {
        "google": {"best_match_url": "https://getty.com/x", "best_site_type": "microstock", "match_count": 1},
        "yandex": {"match_count": 0},
        "match_count": 1,
        "stock_hits": [{"url": "https://getty.com/x", "engine": "google"}],
    }
    assert aggregate_fusion_risk(unverified_fusion, {}, {"detected": False}, "example.com") == RiskLevel.WARNING

    ai_ddg = {
        "duckduckgo": {"match_count": 15},
        "signals": {"wide_distribution": True},
    }
    assert aggregate_fusion_risk({}, {}, {"detected": False}, "example.com", {}, ai_ddg) == RiskLevel.WARNING

    ai_stock = {
        "gemini": {"source_type": "stock", "copyrighted": True},
        "huggingface": {"watermark": {"detected": True, "score": 0.9}},
        "perplexity": {"stock_mentions": True},
        "signals": {"stock_photo_confirmed": True},
    }
    assert aggregate_fusion_risk({}, {}, {"detected": False}, "example.com", {}, ai_stock) == RiskLevel.DANGER


if __name__ == "__main__":
    _self_check()
    print("fusion self-check OK")
