"""
Delta Dental Office Toolkit's part of the Sabrina Fill Form prefill.

smile_partners/sabrina/prefill.py does the common work and calls these.
Change the Toolkit here; other carriers have their own carriers/<carrier>/prefill.py.
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
