"""
Cigna's part of Star Dental's Sabrina Fill Form prefill.

sabrina/star_dental/prefill.py does the common work and calls these.
Change Cigna here; other carriers have their own carriers/<carrier>/prefill.py,
and Smile Partners has its own copy of this folder.
"""

# D0120 Preventative / D2160 Basic / D2740 Major %: on Star's Fill Form (Sabrina
# builds the plan name from them) but not in Star's audit list, so read here
# and filled only, never audited. Read from the exact code's %; a Not Covered code gives 0.
FORM_ONLY_SPEC = [
    {"key": "pct_prev",  "label": "D0120 Preventative", "kind": "pct", "section": "Plan Provisions",
     "portal": ("code", "D0120")},
    {"key": "pct_basic", "label": "D2160 Basic",        "kind": "pct", "section": "Plan Provisions",
     "portal": ("code", "D2160")},
    {"key": "pct_major", "label": "D2740 Major",        "kind": "pct", "section": "Plan Provisions",
     "portal": ("code", "D2740")},
]


def scrape_network(portal_raw: dict) -> str | None:
    """
    The network the crawl ran under. Cigna's network is picked on the portal
    (Plan View dropdown) before scraping, so the scrape holds that one only:
    TOTAL / ADVANTAGE / ... are "In", Out-of-Network (OONET) is "Out".
    """
    from .portal import _portal_normalized
    from .rules import _cigna_in_network
    return _cigna_in_network(_portal_normalized(portal_raw))
