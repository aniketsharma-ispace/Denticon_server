"""
United Concordia's own rules, for the Sabrina audit.

UCCI states almost everything the sheet asks per code, in the Procedure
Allowance lookups the extension exports and `portals/ucci.py` translates. A
few answers are the same for every UCCI plan and are team rules here. The
page does not show when perio maintenance may follow SRP, so that row reads
"not on portal".
"""

from __future__ import annotations

from .vocabulary import _norm_network


# Team rules (Mad, 11/05): UCCI's answer for every plan.
_UCCI_STANDARD = {
    # Major services are paid on the seat date.
    "major_paid_on": "Seat Date",
    # The number Sabrina prints in D4341's Age Limit column.
    "d4341_quads": "4",
    # UCCI plans pay out-of-network dentists too.
    "oon_benefits": "Yes",
}


def _ucci_standard_answer(portal_raw, key: str) -> str | None:
    """UCCI's fixed answer for `key`, for a UCCI export only."""
    if not (_ucci_meta(portal_raw) or _ucci_export(portal_raw)):
        return None
    return _UCCI_STANDARD.get(key)


def _ucci_export(portal_raw) -> dict | None:
    """The UCCI export itself, whether handed the upload or its translation."""
    from ....portals.ucci import _is_ucci_portal

    if not isinstance(portal_raw, dict):
        return None
    for candidate in (portal_raw.get("_raw_export"), portal_raw):
        if _is_ucci_portal(candidate):
            return candidate
    return None


def _ucci_meta(portal_raw) -> dict:
    """What the translation recorded beside the shared contract."""
    meta = portal_raw.get("_ucci_meta") if isinstance(portal_raw, dict) else None
    return meta if isinstance(meta, dict) else {}


def _ucci_network_for_sheet(sheet_in_network) -> str:
    """
    The network the sheet claims: Out when its In Network says Out, in network
    otherwise. UCCI's page states the figures of ONE network, the one of the
    dentist the session is logged in as, so this only decides whether the
    export can be compared (see `_portal_in_network`).
    """
    return "out" if _norm_network(sheet_in_network) == "OUT" else "in"