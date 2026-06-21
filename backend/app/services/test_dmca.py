"""Self-check for DMCA helpers."""

from app.services.dmca_api import extract_dmca_protection_id
from app.services.dmca_crawl import extract_dmca_page_signals
from app.services.pirate_blacklist import domain_in_blacklist


def _self_check() -> None:
    assert extract_dmca_protection_id("DMCA Protected ID: ABCD-1234-EF00-5678") == "ABCD-1234-EF00-5678"
    assert domain_in_blacklist("https://1337x.to/page") is True
    assert domain_in_blacklist("https://example.com") is False

    html = """
    <html><head>
      <meta name="copyright" content="© Example Corp">
      <meta name="dmca-protection-id" content="AAAA-BBBB-CCCC">
    </head>
    <footer>Protected by DMCA.com · All rights reserved</footer>
    <a href="https://www.dmca.com/Protection/Status.aspx?ID=AAAA-BBBB-CCCC-DDDD">DMCA</a>
    </html>
    """
    sig = extract_dmca_page_signals(html, "https://example.com")
    assert sig["has_dmca_badge"] or sig["dmca_links"]
    assert any("DMCA" in h for h in sig["footer_text_hits"])


if __name__ == "__main__":
    _self_check()
    print("dmca self-check OK")
