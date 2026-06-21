"""Self-check for image dimension filters."""
from app.services.image_filters import parse_dimensions_from_url, parse_svg_dimensions, passes_dimension_filter


def main() -> None:
    assert parse_dimensions_from_url(
        "https://x.org/upload/resize_cache/iblock/a/80_80_2/icon.png"
    ) == (80, 80)
    assert parse_dimensions_from_url("https://x.org/thumb-60x60.jpg") == (60, 60)

    svg = b'<svg width="60" height="60" xmlns="http://www.w3.org/2000/svg"></svg>'
    assert parse_svg_dimensions(svg) == (60, 60)

    assert not passes_dimension_filter(min_w=100, min_h=100, url="https://x.org/a/80_80_2/x.png")
    assert not passes_dimension_filter(min_w=100, min_h=100, file_bytes=svg)
    assert passes_dimension_filter(
        min_w=100,
        min_h=100,
        url="https://x.org/photo.jpg",
        pixel_w=200,
        pixel_h=150,
    )

    print("image_filters self-check OK")


if __name__ == "__main__":
    main()
