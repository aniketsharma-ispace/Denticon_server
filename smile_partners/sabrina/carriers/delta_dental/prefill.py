"""
Delta Dental's part of the Sabrina Fill Form prefill.

smile_partners/sabrina/prefill.py does the common work and calls these.
Change Delta Dental here; other carriers have their own carriers/<carrier>/prefill.py.
"""


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
