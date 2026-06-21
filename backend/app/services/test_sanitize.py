from app.services.sanitize import clean_text, sanitize_json


def _self_check() -> None:
    assert "\x00" not in clean_text("a\u0000b")
    meta = sanitize_json({"771": "\u0000", "dpi": "300"})
    assert meta["771"] == ""
    assert meta["dpi"] == "300"


if __name__ == "__main__":
    _self_check()
    print("sanitize self-check OK")
