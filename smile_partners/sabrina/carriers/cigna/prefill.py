"""
Cigna's part of the Sabrina Fill Form prefill.

smile_partners/sabrina/prefill.py does the common work and calls these.
Change Cigna here; other carriers have their own carriers/<carrier>/prefill.py.
"""


def scrape_network(portal_raw: dict) -> str | None:
    """
    The network the crawl ran under. Cigna's network is picked on the portal
    (Plan View dropdown) before scraping, so the scrape holds that one only:
    TOTAL / ADVANTAGE / ... are "In", Out-of-Network (OONET) is "Out".
    """
    from .portal import _portal_normalized
    from .rules import _cigna_in_network
    return _cigna_in_network(_portal_normalized(portal_raw))
