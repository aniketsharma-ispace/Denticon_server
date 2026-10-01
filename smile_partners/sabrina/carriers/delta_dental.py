"""
Delta Dental, as this sheet needs it.

Delta's export needs a great deal of translation — its limitation prose, its
age bands, its footnotes — but all of that is about reading the portal, not
about this sheet, so it lives in `portals/delta_dental.py` where every vendor
can use it.

A rule that is genuinely about how *this* sheet records a Delta answer belongs
here.
"""

from __future__ import annotations

from ..vocabulary import _norm_network


def _dd_network_export(portal_raw: dict, sheet_in_network) -> dict:
    """
    The export with Benefits Search answered for the network the sheet records.

    Benefits Search states one network at a time, and the extension searches
    every code under both: `benefits_search` for the plan's own network and
    `benefits_search_oon` for "Non-Delta Dental Dentist". The sheet's "In
    Network" field says which one this office is, so a sheet reading "Out" is
    audited against the non-Delta answers — D0150 at 50% rather than 100%.

    Anything else — a sheet reading "In" or nothing, an export from before the
    second search, a search that did not run — leaves the export as it is.
    """
    if not isinstance(portal_raw, dict) or _norm_network(sheet_in_network) != "OUT":
        return portal_raw
    tabs = portal_raw.get("tabs")
    if not isinstance(tabs, dict):
        return portal_raw
    oon = tabs.get("benefits_search_oon")
    if not isinstance(oon, list) or not oon:
        return portal_raw
    chosen = dict(tabs)
    chosen["benefits_search"] = oon
    chosen["benefits_search_network"] = tabs.get("benefits_search_oon_network") or "Non-Delta Dental Dentist"
    return {**portal_raw, "tabs": chosen}
