"""Classify match domains for fusion risk scoring."""

from urllib.parse import urlparse

SiteType = str  # photobank | microstock | social | marketplace | news | other

PHOTOBANK = (
    "lori.ru",
    "lori-images.com",
    "pressfoto.ru",
    "f1online.app",
    "f1online.de",
    "imagesource.com",
    "westend61.de",
    "imagebroker.com",
    "legion-media.com",
    "photobank.ru",
    "fotobank.ru",
)

MICROSTOCK = (
    "shutterstock.com",
    "gettyimages.com",
    "istockphoto.com",
    "stock.adobe.com",
    "adobe.com",
    "dreamstime.com",
    "alamy.com",
    "123rf.com",
    "depositphotos.com",
    "bigstockphoto.com",
    "canstockphoto.com",
)

SOCIAL = (
    "vk.com",
    "vk.ru",
    "ok.ru",
    "pinterest.com",
    "pinterest.ru",
    "t.me",
    "telegram.me",
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
)

MARKETPLACE = (
    "wildberries.ru",
    "ozon.ru",
    "market.yandex.ru",
    "aliexpress.ru",
    "lamoda.ru",
)

NEWS = (
    "ria.ru",
    "tass.ru",
    "rbc.ru",
    "lenta.ru",
    "gazeta.ru",
    "kommersant.ru",
    "interfax.ru",
    "bbc.com",
    "cnn.com",
    "reuters.com",
)

DANGER_SITE_TYPES = frozenset({"photobank", "microstock"})
WARNING_SITE_TYPES = frozenset({"social", "news", "marketplace"})


def classify_domain(url: str) -> SiteType:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if not host:
        return "other"

    def _hit(items: tuple[str, ...]) -> bool:
        return any(h == host or host.endswith("." + h) for h in items)

    if _hit(PHOTOBANK):
        return "photobank"
    if _hit(MICROSTOCK):
        return "microstock"
    if _hit(SOCIAL):
        return "social"
    if _hit(MARKETPLACE):
        return "marketplace"
    if _hit(NEWS):
        return "news"
    return "other"


def is_stock_or_photobank(url: str) -> bool:
    return classify_domain(url) in DANGER_SITE_TYPES
