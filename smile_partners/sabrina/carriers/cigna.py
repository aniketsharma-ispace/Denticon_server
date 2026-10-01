"""
Cigna, as this sheet needs it.

Corrections that apply only when the portal export is Cigna's and only to the
way this sheet records the answer. Cigna's export is translated by
`portals/cigna.py`; what is left here is the sheet-specific part.
"""

from __future__ import annotations

import re
from ..vocabulary import _blank, _coalesce_keys, _num_pct


# Cigna reports these three as "not covered" on the per-code lookup even
# though the plan covers them: the real limits live in Frequency & Limitations
# and the percentage is the plan's Preventive percentage. D1206 has no row of
# its own — Cigna states one fluoride limit, on the D1208 "Topical Fluoride"
# row — so the codes are searched in order.
_CIGNA_FL_CODES = {
    "D1206": ("D1206", "D1208"),
    "D1208": ("D1208", "D1206"),
    "D1351": ("D1351",),
}


# D1510 is handled the other way: not covered means there is nothing to
# compare, so the row is left unstated rather than reported as 0%.
_CIGNA_BLANK_WHEN_NOT_COVERED = {"D1510"}


def _cigna_procedure_not_covered(bd: dict, codes: tuple[str, ...]) -> bool:
    """Whether the portal's per-code lookup reported no benefit for the code."""
    procs = bd.get("procs") or {}
    for code in codes:
        proc = procs.get(str(code).upper())
        if not proc:
            continue
        level = str(proc.get("benefit_level", "")).strip().upper()
        freq = str(proc.get("frequency_limit", "")).lower()
        if level in ("", "N/A", "NA"):
            return "not covered" in freq or "no benefits" in freq
        return False
    return False


def _cigna_fl_row(portal_raw: dict, codes: tuple[str, ...]) -> dict | None:
    """The Frequency & Limitations row for the first of these codes."""
    raw = _cigna_export(portal_raw)
    if not raw:
        return None
    rows = raw.get("frequencies") or []
    for code in codes:
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("procedure_code", "")).strip().upper() == str(code).upper():
                return row
    return None


def _cigna_preventive_pct(portal_raw: dict) -> str | None:
    """The plan's in-network Preventive percentage, as the plan pays it."""
    raw = _cigna_export(portal_raw)
    if not raw:
        return None
    for row in raw.get("coinsurance") or []:
        if not isinstance(row, dict):
            continue
        category = str(row.get("category", "")).lower()
        if "preventive" not in category and "preventative" not in category:
            continue
        network = str(_coalesce_keys(row, "network", "network_id") or "").upper()
        if "OON" in network:                      # in-network percentage
            continue
        member = _num_pct(row.get("patient_pays"))
        if member is None:
            continue
        plan = 100 - member
        return f"{plan:g}%"
    return None


def _cigna_code_override(field: dict, value, bd: dict, portal_raw: dict,
                         codes: tuple[str, ...], what: str):
    """
    Correct a per-code value Cigna reports as not covered.

    Returns (handled, value). `what` is "pct" or the procedure field being
    read, so the same rule can answer the percentage, frequency and age rows of
    one code consistently.
    """
    if not _cigna_export(portal_raw) or not codes:
        return False, value
    primary = str(codes[0]).upper()

    if primary in _CIGNA_BLANK_WHEN_NOT_COVERED:
        if _cigna_procedure_not_covered(bd, codes):
            return True, None             # nothing to compare
        if what == "age_limit" and _blank(value):
            return True, "99"             # covered, but no age stated
        return False, value

    if primary not in _CIGNA_FL_CODES:
        return False, value
    if not _cigna_procedure_not_covered(bd, codes):
        return False, value

    lookup = _CIGNA_FL_CODES[primary]
    if what == "pct":
        return True, _cigna_preventive_pct(portal_raw)

    row = _cigna_fl_row(portal_raw, lookup)
    if not row:
        return True, None
    if what == "frequency_limit":
        return True, row.get("limit") or None
    if what == "age_limit":
        return True, row.get("age_limitation") or None
    return False, value


# Cigna standard values — answers that are the same on every Cigna plan and
# that the portal does not state per patient. Agreed with the business team;
# the sheet is audited against these rather than left as "not on portal".
_CIGNA_STANDARD_ANSWERS = {
    "major_paid_on": "Seat Date",            # Are Major Services Paid on Prep or Seat date?
    "perio_maint_after_srp": "Next Day",     # When Is First Perio Maintenance Allowed After SRP?
    "d4341_quads": "4",                      # D4341 Scaling Root Planing — number of quads
}


def _cigna_standard_answer(portal_raw: dict, key: str) -> str | None:
    """The Cigna standard answer for `key`, or None when the export isn't Cigna's."""
    if not _cigna_export(portal_raw):
        return None
    return _CIGNA_STANDARD_ANSWERS.get(key)


def _cigna_initial_coverage_date(portal_raw: dict) -> str | None:
    """
    Cigna's Initial Coverage Date, which is what the sheet's Patient Eff Date
    records (business rule) — not the Current Coverage "from" date.
    """
    raw = _cigna_export(portal_raw)
    if not raw:
        return None
    value = (raw.get("plan_details") or {}).get("initial_coverage_date")
    return None if _blank(value) else str(value).strip()


def _cigna_export(portal_raw: dict) -> dict | None:
    """The original Cigna export, when this portal came from Cigna."""
    if str((portal_raw or {}).get("_source_insurer", "")).lower() != "cigna":
        return None
    raw = (portal_raw or {}).get("_raw_export")
    return raw if isinstance(raw, dict) else None


def _cigna_annual_max_classes(portal_raw: dict) -> str:
    """
    Class description of Cigna's general annual maximum.

    Cigna names the service classes the maximum applies to on the record
    itself — "Diagnostic and Preventive,Basic Restorative,Major Restorative,
    Implants" — which is the same statement MetLife prints under the Annual
    card and answers whether preventive draws the maximum down.
    """
    raw = _cigna_export(portal_raw)
    if not raw:
        return ""
    from ...portals.cigna import _cigna_general_annual_record
    records = ((raw.get("financials") or {}).get("maximum_records")) or []
    network = (raw.get("plan_details") or {}).get("network") or {}
    try:
        record = _cigna_general_annual_record(records, network) or {}
    except Exception:
        return ""
    return str(record.get("classDesc") or "")


# Keys the extension may use for the Plan View network dropdown's options.
_CIGNA_NETWORK_OPTION_KEYS = ("network_options", "available_networks", "networks")


def _cigna_network_options(raw: dict) -> list[str] | None:
    """
    The option labels of Cigna's "Plan View" network dropdown
    (e.g. ["ADVANTAGE", "TOTAL", "Out-of-Network"]), or None when the export
    does not carry them.
    """
    for holder in (raw, raw.get("plan_details") or {}):
        for key in _CIGNA_NETWORK_OPTION_KEYS:
            options = holder.get(key)
            if not isinstance(options, list):
                continue
            labels = []
            for option in options:
                if isinstance(option, dict):
                    option = _coalesce_keys(option, "label", "name", "dropdown_label", "id")
                if not _blank(option):
                    labels.append(str(option).strip())
            return labels
    return None


def _is_oon_label(value) -> bool:
    text = str(value or "").upper().replace("-", " ")
    return "OUT OF NETWORK" in text or "OONET" in text or text.strip() == "OON"


_CIGNA_OON_NOTE_RE = re.compile(r"\bin\s+and\s+out[\s-]+of[\s-]+network\b", re.IGNORECASE)


def _cigna_oon_benefits(portal_raw: dict) -> str | None:
    """
    Whether the plan has out-of-network benefits.

    Business rule: the plan has OON benefits when Cigna's "Plan View" network
    dropdown offers an "Out-of-Network" option.

      1. Dropdown options exported → Yes if one is Out-of-Network, else No.
      2. Older exports without the options: coinsurance rows tagged for an
         out-of-network affiliation also prove the option exists → Yes.
      3. Otherwise, Cigna's plan note about accumulators shared "between in
         and out of network" (printed on plans that pay OON) → Yes.
      4. Nothing conclusive → None (not stated), never a guessed "No".
    """
    raw = _cigna_export(portal_raw)
    if not raw:
        return None

    options = _cigna_network_options(raw)
    if options:
        return "Yes" if any(_is_oon_label(option) for option in options) else "No"

    for row in raw.get("coinsurance") or []:
        if isinstance(row, dict) and _is_oon_label(
                _coalesce_keys(row, "network", "network_id")):
            return "Yes"

    plan_notes = (raw.get("notes") or {}).get("plan_notes") or []
    if any(_CIGNA_OON_NOTE_RE.search(str(note)) for note in plan_notes):
        return "Yes"
    return None


def _cigna_ortho_deductible(portal_raw: dict) -> str | None:
    """
    Cigna's SEPARATE orthodontic deductible, for the sheet's Orthodontics
    Deductible Amount / Met Amount rows.

    Only a deductible record for orthodontics alone (class 4) is a separate
    ortho deductible. Ortho being one of the classes the general deductible
    applies to (classCode "2,3,4,5") is not one, and the sheet records 0.

    portal.py reaches this only when portals/cigna.py found no ortho-only
    record, so an export that carries deductible records answers 0.00.
    """
    raw = _cigna_export(portal_raw)
    if not raw:
        return None
    records = (raw.get("financials") or {}).get("deductible_records")
    if not isinstance(records, list):
        return None                 # no deductible data at all → not stated

    from ...portals.cigna import _cigna_ortho_deductible_record
    network = (raw.get("plan_details") or {}).get("network") or {}
    if _cigna_ortho_deductible_record(records, network):
        return None                 # a real ortho deductible exists; bd has it
    return "0.00"