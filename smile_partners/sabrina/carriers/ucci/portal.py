"""
Reading the portal side of each field, for a United Concordia export.

Most fields come straight out of the shared breakdown that `portals/` produces.
The ones here need more than a lookup: the network the session was scraped
under, payor IDs the page lists several of, answers UCCI states per code
(deductible, maximum, alternate benefit) rather than as plan provisions.

Only a UCCI export reaches this module, so the only carrier rules it calls are
UCCI's own, in `rules.py`.
"""

from __future__ import annotations

import re
from .common import _UNLIMITED_MAX
from .vocabulary import _blank, _norm_id, _num_money
from .rules import _ucci_export, _ucci_meta, _ucci_network_for_sheet, _ucci_standard_answer


def _portal_for_sheet(portal_raw: dict, sab_fields: dict) -> dict:
    """The export, told which network the sheet claims."""
    export = _ucci_export(portal_raw)
    if export is None:
        return portal_raw
    return dict(export, _ucci_network=_ucci_network_for_sheet(sab_fields.get("in_network")))


def _breakdown_for_sheet(bd: dict, portal_norm: dict) -> dict:
    """
    The breakdown with the answers UCCI states its own way.

    The shared extraction reads these from plan provisions UCCI's export does
    not have; the translation read them off the page and the code lookups
    instead (portals/ucci.py).
    """
    meta = _ucci_meta(portal_norm)
    if not meta:
        return bd
    bd = dict(bd)
    for key in ("plan_year_start", "missing_tooth", "waiting_period", "ded_prev", "ded_diag",
                "posterior_composite_downgrade", "porcelain_posterior_downgrade"):
        bd[key] = meta.get(key) or None
    # The shared breakdown fills an unstated amount met with 0.00; with no
    # deductible read off the page there is nothing it was met against.
    for total, paid in (("indiv_ded", "indiv_ded_paid"), ("family_ded", "family_ded_paid")):
        if _blank(bd.get(total)):
            bd[paid] = None
    return bd


# ══════════════════════════════════════════════════════════════════════════════
#  PORTAL SIDE
# ══════════════════════════════════════════════════════════════════════════════

def _portal_normalized(portal_raw: dict) -> dict:
    """The export translated into the standard contract (portals/ucci.py)."""
    from ....portals.ucci import _normalize_ucci_portal

    export = _ucci_export(portal_raw)
    if export is None:
        return portal_raw or {}
    try:
        normalized = _normalize_ucci_portal(export)
    except Exception:      # a malformed export must not sink the audit
        return portal_raw or {}
    normalized.setdefault("_raw_export", export)
    return normalized


def _portal_breakdown(portal_raw: dict) -> dict:
    """
    The client's standard breakdown dict via `breakdown._extract`, fed the
    translation (it has no UCCI branch of its own). Every audited field is a
    hard portal fact, so the LLM interpreter is skipped.
    """
    from ....breakdown import _extract as _extract_breakdown

    payload = dict(_portal_normalized(portal_raw))
    payload["_skip_llm"] = True
    return _extract_breakdown(payload, {})


def _pct_from_procs(procs: dict, codes: tuple[str, ...]) -> str | None:
    """Coverage % for the first CDT code the portal actually reports."""
    for code in codes:
        proc = (procs or {}).get(code.upper())
        if not proc:
            continue
        level = proc.get("benefit_level")
        if not _blank(level):
            return str(level)
        if "not covered" in str(proc.get("frequency_limit", "")).lower():
            return "0%"
    return None


def _procfield_from_procs(procs: dict, field: str, codes: tuple[str, ...]) -> str | None:
    """A named field off the first CDT code the portal states it for."""
    for code in codes:
        proc = (procs or {}).get(code.upper())
        if not proc:
            continue
        value = proc.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text and not _blank(text):
            return text
    return None


def _portal_in_network(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    The network badge of the dentist the session was logged in as
    ("In-Network Dentist" / "Out-of-Network Dentist"). Every percentage on the
    page is that network's.
    """
    value = _ucci_meta(portal_raw).get("network_status")
    return value or None


def _network_conflict(portal_raw: dict, sab_fields: dict) -> str:
    """
    A note when the sheet and the scrape are of different networks: the
    percentages and maximums then belong to different fee schedules and are
    not comparable, only the In Network row itself is.
    """
    from .vocabulary import _norm_network

    scraped = _norm_network(_ucci_meta(portal_raw).get("network_status"))
    sheet = _norm_network(sab_fields.get("in_network"))
    if scraped and sheet and scraped != sheet:
        word = {"IN": "in-network", "OUT": "out-of-network"}
        return (f"portal was read as an {word[scraped]} dentist, the sheet is "
                f"{word[sheet]}; rescrape from the sheet's office to compare")
    return ""


def _portal_subscriber_name(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """The policyholder the page names."""
    value = ((portal_raw or {}).get("subscriber_info") or {}).get("name")
    return None if _blank(value) else str(value)


def _portal_subscriber_dob(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """The policyholder's DOB, read from the Select Member list by the extension."""
    value = ((portal_raw or {}).get("subscriber_info") or {}).get("dob")
    return None if _blank(value) else str(value)


def _portal_payor_id(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    UCCI lists every payer ID that reaches it ("89070, 99994, or CX007"). The
    sheet records one; it agrees when it is one of them.
    """
    listed = str((((portal_raw or {}).get("carrier_information") or {}).get("payer_id")) or "")
    ids = [i for i in (_norm_id(x) for x in re.split(r",|\bor\b|/|;", listed)) if i]
    if not ids:
        return None
    sheet = _norm_id(sab_raw)
    if sheet and sheet in ids:
        return str(sab_raw).strip()
    return listed.strip()


def _portal_yearly_max_paid(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Amount applied to the yearly max this benefit period, from the sidebar."""
    fin = (((portal_raw or {}).get("metlife_data") or {}).get("financials") or {}).get("annual_max") or {}
    used = _num_money(fin.get("used"))
    if used is None:
        return None
    total = _num_money(bd.get("yearly_max"))
    if total is not None and total >= _UNLIMITED_MAX and used == 0:
        return "0.00"
    return f"{used:.2f}"


def _portal_cob(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    return _ucci_meta(portal_raw).get("cob") or None


def _portal_eff_date(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    value = bd.get("eff_date")
    return None if _blank(value) else str(value)


def _ortho_not_covered(portal_raw: dict) -> bool:
    return _ucci_meta(portal_raw).get("ortho_covered") == "No"


def _portal_ortho_max(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Orthodontic lifetime maximum; 0 where D8080 is not covered."""
    if _ortho_not_covered(portal_raw):
        return "0.00"
    value = bd.get("ortho_max")
    return None if _blank(value) else str(value)


def _portal_ortho_used(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Ortho amount used: an ortho card in the sidebar if there is one, 0 where
    ortho is not covered, otherwise not stated.
    """
    if _ortho_not_covered(portal_raw):
        return "0.00"
    fin = (((portal_raw or {}).get("metlife_data") or {}).get("financials") or {}).get("ortho_lifetime") or {}
    used = _num_money(fin.get("used"))
    return None if used is None else f"{used:.2f}"


def _no_ortho_deductible(portal_raw: dict) -> bool:
    """
    No orthodontic deductible: ortho not covered, or an ortho maximum beside a
    deductible table that lists no ortho deductible.
    """
    if _ortho_not_covered(portal_raw):
        return True
    meta = _ucci_meta(portal_raw)
    return bool(meta.get("ortho_max_present") and meta.get("deductibles_listed"))


def _portal_ortho_ded(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    return "0.00" if _no_ortho_deductible(portal_raw) else None


def _portal_ortho_ded_met(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    return "0.00" if _no_ortho_deductible(portal_raw) else None


def _portal_ortho_age(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    D8080's Additional Policy Details: "Dependent ~ Age 19 And Older ~ Ortho
    related" under Benefits Cease is an ortho age of 19. 0 where ortho is not
    covered.
    """
    if _ortho_not_covered(portal_raw):
        return "0"
    return _ucci_meta(portal_raw).get("ortho_age_limit") or None


def _portal_ortho_payment(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """D8080's Reimbursement Method: One Time (lump sum), Quarterly or Monthly."""
    if _ortho_not_covered(portal_raw):
        return None
    return _ucci_meta(portal_raw).get("ortho_payment_timing") or None


def _portal_prev_in_max(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """D0120's own "Applies to Maximum"."""
    return _ucci_meta(portal_raw).get("prev_in_max") or None


def _portal_d4341_quads(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """D4341 quadrants: 4 for every UCCI plan (team rule, 11/05)."""
    return _ucci_standard_answer(portal_raw, "d4341_quads")


def _portal_oon_benefits(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Does the plan have OON benefits: Yes for every UCCI plan (team rule, 11/05)."""
    return _ucci_standard_answer(portal_raw, "oon_benefits")


def _portal_major_paid_on(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Major services are paid on the seat date for every UCCI plan (team rule, 11/05)."""
    return _ucci_standard_answer(portal_raw, "major_paid_on")


# Portal values that must be computed rather than read from one breakdown key.
# "_perio_after_srp" is absent on purpose: UCCI's page does not state it, so
# that row reads "not on portal".
_DERIVED = {
    "_prev_in_max": _portal_prev_in_max,
    "_subscriber_name": _portal_subscriber_name,
    "_subscriber_dob": _portal_subscriber_dob,
    "_payor_id": _portal_payor_id,
    "_cob": _portal_cob,
    "_ortho_max": _portal_ortho_max,
    "_ortho_ded": _portal_ortho_ded,
    "_ortho_age": _portal_ortho_age,
    "_ortho_ded_met": _portal_ortho_ded_met,
    "_ortho_used": _portal_ortho_used,
    "_ortho_payment": _portal_ortho_payment,
    "_in_network": _portal_in_network,
    "_yearly_max_paid": _portal_yearly_max_paid,
    "_eff_date": _portal_eff_date,
    "_d4341_quads": _portal_d4341_quads,
    "_major_paid_on": _portal_major_paid_on,
    "_oon_benefits": _portal_oon_benefits,
}


def _portal_value(field: dict, bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Resolve one spec'd field's value on the portal side."""
    src = field.get("portal")
    if src is None:
        return None
    if isinstance(src, tuple) and src and src[0] == "code":
        return _pct_from_procs(bd.get("procs", {}), src[1:])
    if isinstance(src, tuple) and src and src[0] == "codefield":
        return _procfield_from_procs(bd.get("procs", {}), src[1], src[2:])
    if isinstance(src, str) and src in _DERIVED:
        return _DERIVED[src](bd, portal_raw, sab_raw)
    val = bd.get(src) if isinstance(src, str) else None
    return None if _blank(val) else str(val)