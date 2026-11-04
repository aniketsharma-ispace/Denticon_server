"""
Guardian's own rules, for the Sabrina audit.

Guardian states most of what the sheet asks per patient, in the Dental
Eligibility data the extension exports and `portals/guardian.py` translates.
A few answers are the same on every Guardian eligibility page and printed as
static copy, which the extension leaves out of the export; those are Guardian's
standard values here.
"""

from __future__ import annotations

from .vocabulary import _norm_network


_GUARDIAN_STANDARD = {
    # "Guardian applies Standard COB guidelines." — the page's Coordination of
    # Benefits paragraph.
    "cob": "Standard",
    # "Multi-visit procedures are paid on the preparation date." — the page's
    # footnote legend.
    "major_paid_on": "Prep Date",
    # Team rule (2026-11-04): Guardian's answer unless the page says otherwise.
    # The eligibility page states neither (Titus Jackson's and Keith Cline's
    # sheets both answer Yes).
    "prev_in_max": "Yes",
    "porcelain_posterior_downgrade": "Yes",
}


def _guardian_export(portal_raw) -> dict | None:
    """The Guardian export itself, whether handed the upload or its translation."""
    from ....portals.guardian import _is_guardian_portal

    if not isinstance(portal_raw, dict):
        return None
    for candidate in (portal_raw.get("_raw_export"), portal_raw):
        if _is_guardian_portal(candidate):
            return candidate
    return None


def _guardian_meta(portal_raw) -> dict:
    """What the translation recorded beside the shared contract."""
    meta = portal_raw.get("_guardian_meta") if isinstance(portal_raw, dict) else None
    return meta if isinstance(meta, dict) else {}


def _guardian_standard_answer(portal_raw, key: str) -> str | None:
    """Guardian's fixed answer for `key`, for a Guardian export only."""
    if not (_guardian_meta(portal_raw) or _guardian_export(portal_raw)):
        return None
    return _GUARDIAN_STANDARD.get(key)


def _guardian_network_for_sheet(sheet_in_network) -> str:
    """
    The network whose percentages the sheet records: Out when its In Network
    says Out, in network otherwise. Guardian states both on every Plan Options
    row (90% / 100% preventive), so reading the other one would report every
    coverage row as a mismatch.
    """
    return "out" if _norm_network(sheet_in_network) == "OUT" else "in"
