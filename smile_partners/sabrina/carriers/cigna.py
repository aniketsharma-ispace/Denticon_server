"""
Cigna, as this sheet needs it.

Corrections that apply only when the portal export is Cigna's and only to the
way this sheet records the answer. Cigna's export is translated by
`portals/cigna.py`; what is left here is the sheet-specific part.
"""

from __future__ import annotations

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


def _cigna_oon_benefits(portal_raw: dict) -> str | None:
    """
    Whether the plan has out-of-network benefits.

    Cigna answers this with the network affiliation dropdown: a plan that
    offers "Out-of-Network" alongside its in-network option has OON benefits,
    and one that does not, does not. The export carries that as a set of
    coinsurance rows tagged OONET, so the presence of any such row is the
    dropdown option — the percentages on those rows are a separate question and
    do not decide it.
    """
    raw = _cigna_export(portal_raw)
    if not raw:
        return None
    rows = raw.get("coinsurance") or []
    if not rows:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        network = " ".join(str(_coalesce_keys(row, "network", "network_id") or "")
                           for _ in (0,)).upper()
        if "OON" in network or "OUT-OF-NETWORK" in network or "OUT OF NETWORK" in network:
            return "Yes"
    return "No"


def _cigna_ortho_deductible(portal_raw: dict) -> str | None:
    """
    Cigna's orthodontic deductible.

    The export states which classes carry a deductible at all; when
    orthodontics is not among them there is no ortho deductible, so the
    sheet's 0 is right and the row should compare rather than read as unstated.
    """
    raw = _cigna_export(portal_raw)
    if not raw:
        return None
    applicability = (raw.get("financials") or {}).get("deductible_applicability")
    if not isinstance(applicability, dict):
        return None
    if applicability.get("orthodontic") is False:
        return "0.00"
    codes = applicability.get("class_codes")
    descriptions = " ".join(str(d) for d in (applicability.get("class_descriptions") or []))
    if isinstance(codes, list) and codes and "4" not in [str(c) for c in codes] \
            and "ortho" not in descriptions.lower():
        return "0.00"
    return None
