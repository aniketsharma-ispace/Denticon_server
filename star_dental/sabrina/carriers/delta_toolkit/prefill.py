"""
Delta Dental Office Toolkit's part of Star Dental's Sabrina Fill Form prefill.

star_dental/sabrina/prefill.py does the common work and calls these.
Change the Toolkit here; other carriers have their own carriers/<carrier>/prefill.py,
and Smile Partners has its own copy of this folder.
"""

import re

# Out-of-network names the Toolkit uses: "Nonparticipating Dentist", and on
# Medicare Advantage plans "Non-PPO Dentist" (extension 1.58).
_OUT_OF_NETWORK_RE = re.compile(r"\bnon[\s-]?(?:participating|par|ppo)\b", re.IGNORECASE)


def scrape_network(portal_raw: dict) -> str | None:
    """
    The network the crawl ran under. Since extension 1.53 the pop-up picks PPO,
    Premier or Non-participating Dentist before the crawl, and the export holds
    that network's benefits only (`selected_network`): PPO and Premier Dentist
    are "In", Nonparticipating Dentist is "Out". None for an older export that
    holds every network, which the user's IN OR OON pick reads as before.
    """
    from .portal import _portal_normalized
    meta = _portal_normalized(portal_raw).get("_toolkit_meta") or {}
    network = str(meta.get("export_network") or "").strip()
    if not network:
        return None
    if _OUT_OF_NETWORK_RE.search(network):
        return "Out"
    if re.search(r"\b(?:ppo|premier)\b", network, re.IGNORECASE):
        return "In"
    return None


# D0120 Preventative / D2160 Basic / D2740 Major %: on Star's Fill Form (Sabrina
# builds the plan name from them) but not in Star's audit list, so read here
# and filled only, never audited. Read from the exact code's %; a Not Covered
# code gives 0.
FORM_ONLY_SPEC = [
    {"key": "pct_prev",  "label": "D0120 Preventative", "kind": "pct", "section": "Plan Provisions",
     "portal": ("code", "D0120")},
    {"key": "pct_basic", "label": "D2160 Basic",        "kind": "pct", "section": "Plan Provisions",
     "portal": ("code", "D2160")},
    {"key": "pct_major", "label": "D2740 Major",        "kind": "pct", "section": "Plan Provisions",
     "portal": ("code", "D2740")},
]
