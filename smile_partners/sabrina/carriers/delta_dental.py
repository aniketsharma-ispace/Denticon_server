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

import re

from ..vocabulary import _norm_network


def _dd_export(portal_raw: dict) -> bool:
    """Whether this is the translated Delta Dental export."""
    return str((portal_raw or {}).get("_source_insurer", "")).lower() == "delta dental"


def _dd_wrapped_history(sab_fields: dict, benefit_rows: dict | None, portal_norm: dict) -> dict:
    """
    The sheet's fields with every wrapped History cell read in full, for a
    Delta Dental audit.

    Where a History cell lists several dates and wraps after a comma, the
    parser keeps the first line as the cell and the whole list as
    `history_wrapped`. A Delta audit compares and shows the whole list —
    Mccoy's D1110 "06/10/2026, 01/29/2026" rather than "06/10/2026,". Every
    other carrier's audit keeps the first line, as before.
    """
    if not _dd_export(portal_norm) or not isinstance(benefit_rows, dict):
        return sab_fields
    fields = dict(sab_fields)
    for row_key, columns in benefit_rows.items():
        wrapped = (columns or {}).get("history_wrapped")
        if wrapped:
            fields[f"{row_key}__hist"] = wrapped
    return fields


def _dd_procedure(portal_raw: dict, code: str) -> dict | None:
    """One code's translated Benefits Search entry; None where it was not searched."""
    for proc in ((portal_raw or {}).get("benefit_coverage") or {}).get("procedures") or []:
        if isinstance(proc, dict) and str(proc.get("procedure_code", "")).upper() == code:
            return proc
    return None


def _dd_major_paid_on(portal_raw: dict) -> str | None:
    """
    "Are Major Services Paid on Prep or Seat date?"

    Delta does not state it. The sheet records "Seat Date" wherever crowns
    (D2740) are covered and leaves the field blank where they are not, so
    nothing is stated for a plan without crown coverage, or for an export in
    which D2740 was never searched.
    """
    proc = _dd_procedure(portal_raw, "D2740")
    level = str((proc or {}).get("benefit_level") or "").strip().lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", level)
    if m and float(m.group(1)) > 0 and "not covered" not in level:
        return "Seat Date"
    return None


# "Prophylaxis procedures are a benefit following active periodontal therapy
# once a 30 day post-operative period has completed."
_DD_POST_OP_RE = re.compile(r"(\d+)[\s-]*day\s+post[\s-]*operative\s+period", re.IGNORECASE)


def _dd_perio_after_srp(portal_raw: dict) -> str | None:
    """
    "When Is First Perio Maintenance Allowed After SRP?"

    Delta states it in D4910's limitation as a post-operative period after
    active periodontal therapy. Where D4910's limitation names no such period
    the sheet records "Not available in website". An export in which D4910
    was never searched says nothing either way.
    """
    proc = _dd_procedure(portal_raw, "D4910")
    if proc is None:
        return None
    m = _DD_POST_OP_RE.search(str(proc.get("limitation") or ""))
    return f"{m.group(1)} Days" if m else "Not available in website"


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
