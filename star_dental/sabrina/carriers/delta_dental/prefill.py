"""
Delta Dental's part of Star Dental's Sabrina Fill Form prefill.

star_dental/sabrina/prefill.py does the common work and calls these.
Change Delta Dental here; other carriers have their own carriers/<carrier>/prefill.py,
and Smile Partners has its own copy of this folder.
"""

# D0120 Preventative / D2160 Basic / D2740 Major %: on Star's Fill Form (Sabrina
# builds the plan name from them) but not in Star's audit list, so read here
# and filled only, never audited. Read from the plan's class percentages, as Smile Partners' spec reads them.
FORM_ONLY_SPEC = [
    {"key": "pct_prev",  "label": "D0120 Preventative", "kind": "pct", "section": "Plan Provisions",
     "portal": 'pct_prev'},
    {"key": "pct_basic", "label": "D2160 Basic",        "kind": "pct", "section": "Plan Provisions",
     "portal": 'pct_basic'},
    {"key": "pct_major", "label": "D2740 Major",        "kind": "pct", "section": "Plan Provisions",
     "portal": 'pct_major'},
]


def scrape_network(portal_raw: dict) -> str | None:
    """
    The network the crawl ran under. Since 10/16 the extension's pop-up picks
    PPO, Premier or Out of Network before the procedure-code search, and only
    that network is searched (`tabs.benefits_search_selected`): PPO and
    Premier are "In", Out of Network is "Out". None for an export made before
    the pop-up, which the user's IN OR OON pick reads as before.
    """
    from .rules import _dd_selected_network
    return {"ppo": "In", "premier": "In", "oon": "Out"}.get(_dd_selected_network(portal_raw))
