"""
MetLife, as this sheet needs it.

MetLife's export already arrives in the shape the shared breakdown reads, and
this sheet records most of MetLife's answers in the ordinary way — so nearly
every field is served by `portal.py` and the general vocabulary.

Anything MetLife-specific belongs here rather than in `portal.py`, so it cannot
reach another carrier. MetLife's side of the portal is `portals/metlife.py`.
"""

from __future__ import annotations

from .vocabulary import _norm_network


def _metlife_benefit_coverage(portal_raw: dict) -> dict | None:
    """The Benefit & Coverage crawl, when this export is MetLife's own."""
    bc = (portal_raw or {}).get("benefit_coverage")
    if not isinstance(bc, dict):
        return None
    # Only the MetLife extension stamps this source; the Cigna, Aetna and Delta
    # translations build a `benefit_coverage` holding procedures alone.
    if not str(bc.get("source", "")).startswith("MetLife Portal"):
        return None
    return bc


def _metlife_provider_network(portal_raw: dict) -> str | None:
    """
    Whether the office is in or out of network, as the portal states it.

    The Benefit & Coverage tab names the selected provider's network in a
    sticker beside the provider dropdown, and the extension (v1.38+) records it
    as `benefit_coverage.provider_network_status`, alongside the procedures it
    priced under that network. That is the office's own status, which the
    coverage rows cannot give: a plan that pays both in and out of network
    agrees with either claim.

    `metlife_data.provider_info` is deliberately not read. Exports from before
    v1.38 filled it from the first "In-Network" heading on the page, which is
    why it said In-Network for nearly every patient. Older exports have no
    `benefit_coverage.provider_network_status`, and so still fall back to the
    coverage rows.

    A crawl during which the provider was switched is not trusted either: its
    procedures were priced under two networks.
    """
    bc = _metlife_benefit_coverage(portal_raw)
    if not bc or bc.get("provider_changed_during_crawl"):
        return None
    verdict = _norm_network(bc.get("provider_network_status"))
    return {"IN": "In", "OUT": "Out"}.get(verdict)
