from app.services.url_clean import canonical_page_url, clean_http_url, is_self_image_match


def _self_check() -> None:
    assert clean_http_url("https://www.facebook.com/chantalekabeministriesInstagram:") == (
        "https://facebook.com/chantalekabeministries"
    )
    assert clean_http_url("https://twitter.com/cerentheacemi?s=20İnstagram:") == (
        "https://twitter.com/cerentheacemi?s=20"
    )
    assert clean_http_url("https://example.com/photo.jpg") == "https://example.com/photo.jpg"
    assert clean_http_url(
        "https://image.shutterstock.com/image-photo/chef-260nw-605801360.jpg&amp;quot"
    ) == "https://image.shutterstock.com/image-photo/chef-260nw-605801360.jpg"
    assert clean_http_url("not a url") is None

    assert canonical_page_url("https://www.englishnanny.org") == "https://englishnanny.org/"
    assert canonical_page_url("https://englishnanny.org/") == "https://englishnanny.org/"
    assert canonical_page_url("https://englishnanny.org/about/") == "https://englishnanny.org/about"

    url = "https://englishnanny.ru/upload/resize_cache/iblock/004/knyifo2njimokdfqsu47x34sb4ptxvku/315_315_2/ruslanaruslana.png"
    assert is_self_image_match(url, url)
    assert is_self_image_match(url, "https://www.englishnanny.ru/upload/resize_cache/iblock/004/knyifo2njimokdfqsu47x34sb4ptxvku/315_315_2/ruslanaruslana.png")
    assert is_self_image_match(
        url,
        "https://englishnanny.ru/upload/iblock/004/ruslanaruslana.png",
    )
    assert not is_self_image_match(url, "https://other.com/ruslanaruslana.png")


if __name__ == "__main__":
    _self_check()
    print("url_clean self-check OK")
