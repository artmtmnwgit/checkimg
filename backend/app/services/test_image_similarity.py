"""Self-check for image similarity."""

from PIL import Image, ImageDraw

from app.services.image_similarity import compare_images


def _self_check() -> None:
    a = Image.new("RGB", (400, 300), color=(120, 80, 200))
    b = Image.new("RGB", (400, 300), color=(120, 80, 200))
    c = Image.new("RGB", (400, 300), color=(120, 80, 200))
    ImageDraw.Draw(c).rectangle((50, 50, 350, 250), fill=(10, 200, 50))

    exact = compare_images(a, b)
    assert exact["match_kind"] == "exact"
    assert exact["similarity_score"] >= 0.9

    diff = compare_images(a, c)
    assert diff["similarity_score"] < exact["similarity_score"]
    assert diff["match_kind"] != "exact"


if __name__ == "__main__":
    _self_check()
    print("image_similarity self-check OK")
