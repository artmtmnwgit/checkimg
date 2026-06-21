"""Static blacklist of known piracy / warez / illegal streaming domains."""

from urllib.parse import urlparse

# ponytail: curated seed list; extend via env file later if needed
PIRATE_DOMAINS: frozenset[str] = frozenset(
    {
        "1337x.to",
        "thepiratebay.org",
        "piratebay.org",
        "rutor.info",
        "nnmclub.to",
        "kinozal.tv",
        "lostfilm.tv",
        "rezka.ag",
        "hdrezka.ag",
        "seasonvar.ru",
        "lordfilm.lu",
        "filmix.ac",
        "b-ok.org",
        "z-lib.org",
        "libgen.is",
        "libgen.rs",
        "sci-hub.se",
        "sci-hub.st",
        "mp3party.net",
        "flvto.biz",
        "savefrom.net",
        "fmovies.to",
        "123movies.la",
        "putlocker.vip",
        "watchserieshd.tv",
        "couchtuner.eu",
        "kissasian.sh",
        "animeflv.net",
        "nyaa.si",
        "rutracker.org",
        "rutracker.net",
        "fast-torrent.club",
        "torrindex.net",
    }
)


def domain_in_blacklist(url_or_domain: str) -> bool:
    raw = url_or_domain.strip().lower()
    if "://" in raw:
        host = urlparse(raw).netloc.lower()
    else:
        host = raw.split("/")[0]
    host = host.removeprefix("www.")
    if host in PIRATE_DOMAINS:
        return True
    # subdomain match: cdn.thepiratebay.org
    parts = host.split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in PIRATE_DOMAINS:
            return True
    return False
