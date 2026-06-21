"""Self-check for lazyload-aware image extraction."""

from app.services.html_parser import extract_image_urls, extract_stylesheet_urls

HTML = """
<html><head>
  <link rel="stylesheet" href="/theme.css">
  <meta property="og:image" content="https://cdn.example.com/og-share.jpg">
  <script type="application/ld+json">{"image":"https://cdn.example.com/schema-photo.webp"}</script>
</head><body>
  <img src="/photo.jpg" width="200" height="100">
  <img src="/icon.png" width="16" height="16">
  <img src="data:image/gif;base64,R0lGODlh" data-src="/lazy-real.jpg" width="400" height="300">
  <img src="/placeholder.gif" data-srcset="/lazy-1x.webp 1x, /lazy-2x.webp 2x">
  <picture>
    <source srcset="/pic.avif" type="image/avif">
    <source srcset="/pic.webp" type="image/webp">
    <img src="/pic-fallback.jpg" alt="">
  </picture>
  <noscript><img src="/noscript-only.jpeg"></noscript>
  <div style="background-image: url('/bg.png')"></div>
  <video poster="/video-cover.jpg"></video>
  <img src="/uploads/2024/photo-no-ext" width="800" height="600">
</body></html>
"""

LAZY_HTML = """
<img class="lazyload" src="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%3E%3C/svg%3E"
     data-src="https://site.com/wp-content/uploads/hero.jpg"
     data-srcset="https://site.com/wp-content/uploads/hero-300.jpg 300w,
                  https://site.com/wp-content/uploads/hero-600.jpg 600w">
"""


def _self_check() -> None:
    urls = extract_image_urls(HTML, "https://example.com")
    expected = [
        "https://example.com/photo.jpg",
        "https://example.com/lazy-real.jpg",
        "https://example.com/lazy-1x.webp",
        "https://example.com/lazy-2x.webp",
        "https://example.com/pic.avif",
        "https://example.com/pic.webp",
        "https://example.com/pic-fallback.jpg",
        "https://example.com/noscript-only.jpeg",
        "https://example.com/bg.png",
        "https://example.com/video-cover.jpg",
        "https://example.com/uploads/2024/photo-no-ext",
        "https://cdn.example.com/og-share.jpg",
        "https://cdn.example.com/schema-photo.webp",
    ]
    for u in expected:
        assert u in urls, f"missing {u}, got {urls}"

    assert not any("icon.png" in u for u in urls)
    assert not any(u.startswith("data:") for u in urls)

    lazy = extract_image_urls(LAZY_HTML, "https://site.com")
    assert "https://site.com/wp-content/uploads/hero.jpg" in lazy
    assert "https://site.com/wp-content/uploads/hero-600.jpg" in lazy

    sheets = extract_stylesheet_urls(HTML, "https://example.com")
    assert "https://example.com/theme.css" in sheets


if __name__ == "__main__":
    _self_check()
    print("html_parser self-check OK")
