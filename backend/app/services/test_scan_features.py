from app.api import deps
from app.api.routes import scan as scan_routes
from app.services.scan_options import scan_options_summary


def _self_check() -> None:
    assert scan_options_summary(None) == "стандарт (.env)"
    s = scan_options_summary(
        {
            "google_search": True,
            "yandex_search": False,
            "match_verify": False,
            "dmca_checks": True,
            "dmca_lumen_per_image": False,
            "ai_search": False,
            "duckduckgo": False,
            "huggingface": False,
            "gemini": False,
            "tineye": False,
            "perplexity": False,
            "copilot": False,
            "min_file_size_kb": 100,
            "min_image_width": 64,
            "min_image_height": 64,
        }
    )
    assert "быстрый" in s
    assert "Google" in s
    assert "фильтр" in s
    assert hasattr(scan_routes, "delete_scan")
    assert hasattr(scan_routes, "enable_share")
    assert hasattr(deps, "get_controllable_scan")


if __name__ == "__main__":
    _self_check()
    print("scan_features self-check OK")
