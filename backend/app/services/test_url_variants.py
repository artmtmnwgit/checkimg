"""URL variant + HTML detection self-check."""

from app.services.scan_runner import _looks_like_html, _url_variants


def _self_check() -> None:
    v = _url_variants("https://englishnanny.org/")
    assert "https://englishnanny.org/" in v
    assert "https://www.englishnanny.org/" in v
    assert "https://englishnanny.org" in v
    assert _looks_like_html("<!DOCTYPE html><html><body>x</body></html>")
    assert not _looks_like_html('{"error": true}')


if __name__ == "__main__":
    _self_check()
    print("url variants self-check OK")
