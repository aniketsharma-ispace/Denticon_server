"""
Reading the portal side of each field, for a Guardian export.

Most fields come straight out of the shared breakdown that `portals/` produces.
The ones here need more than a lookup — a subscriber Guardian's page does not
name, a network the sheet picks, answers Guardian prints as static copy.

Only a Guardian export reaches this module, so the only carrier rules it calls
are Guardian's own, in `rules.py`.
"""

from __future__ import annotations

import re
from .common import _UNLIMITED_MAX
from .vocabulary import _blank, _coalesce_keys, _norm_network, _num_money
from .rules import (
    _guardian_export,
    _guardian_meta,
    _guardian_network_for_sheet,
    _guardian_standard_answer,
)


def _portal_for_sheet(portal_raw: dict, sab_fields: dict) -> dict:
    """
    The export as this sheet reads it: under the network its In Network
    names, since Guardian states an in- and an out-of-network percentage for
    every service.
    """
    export = _guardian_export(portal_raw)
    if export is None:
        return portal_raw
    return dict(export, _guardian_network=_guardian_network_for_sheet(sab_fields.get("in_network")))


def _breakdown_for_sheet(bd: dict, portal_norm: dict) -> dict:
    """
    The breakdown with the answers Guardian states its own way.

    The shared extraction reads these from provisions Guardian's export does
    not have (a "Benefit Period" provision, a waiting-period sentence, an
    "Alternate Benefits" paragraph), so they come from what the translation
    read off the Guardian page instead. Diagnostic services — exams and
    x-rays — sit in Guardian's Preventive category, so the deductible answer
    for Diagnostic is Preventive's. A posterior-crown downgrade the page does
    not mention is Guardian's standard answer.
    """
    meta = _guardian_meta(portal_norm)
    if not meta:
        return bd
    bd = dict(bd)
    for key in ("plan_year_start", "waiting_period", "missing_tooth",
                "posterior_composite_downgrade", "porcelain_posterior_downgrade"):
        bd[key] = meta.get(key) or None
    if not bd["porcelain_posterior_downgrade"]:
        bd["porcelain_posterior_downgrade"] = _guardian_standard_answer(
            portal_norm, "porcelain_posterior_downgrade")
    waived = meta.get("prev_deductible_waived")
    applies = None if waived is None else ("No" if waived else "Yes")
    bd["ded_prev"] = bd["ded_diag"] = applies
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
    """
    The portal export in the shape the derived readers expect.

    Guardian's export carries its own layout, which `portals/guardian.py`
    translates into the standard contract — patient / plan_details /
    financials / covered_services / provisions under `metlife_data`. The readers
    below look for exactly that, so they run against the translation rather than
    the raw export.
    """
    from ....portals.guardian import _normalize_guardian_portal

    export = _guardian_export(portal_raw)
    if export is None:
        return portal_raw or {}
    try:
        normalized = _normalize_guardian_portal(export)
    except Exception:      # a malformed export must not sink the audit
        return portal_raw or {}
    normalized.setdefault("_raw_export", export)
    return normalized


def _portal_breakdown(portal_raw: dict) -> dict:
    """
    Normalize the Guardian export into the client's standard breakdown dict via
    `breakdown._extract`.

    `breakdown._extract` has no Guardian branch (Smile Partners has no New Plan
    PDF to feed), so the translation is made here and handed over in the
    shared contract. Denticon is intentionally empty and the LLM interpreter is
    skipped: every audited field is a hard portal fact.
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
        level = proc.get("benefit_level") or proc.get("coverage") or proc.get("plan_pays")
        if not _blank(level):
            return str(level)
        # An explicit "not covered" frequency IS a stated 0% benefit.
        if "not covered" in str(proc.get("frequency_limit", "")).lower():
            return "0%"
    return None


def _procfield_from_procs(procs: dict, field: str, codes: tuple[str, ...]) -> str | None:
    """
    A named field off the first CDT code the portal actually states it for.

    A sibling code stands in only when the first one leaves the field empty —
    the way the sheet's fallback codes are meant (D1206 → D1208).
    """
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


def _network_coverage(portal_raw: dict) -> tuple[bool, bool, bool]:
    """(pays in network, pays out of network, stated at all) per the coverage rows."""
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}
    pays_in = pays_out = stated = False
    services = ml.get("covered_services")
    if isinstance(services, list):
        for row in services:
            if not isinstance(row, dict):
                continue
            in_net = _coalesce_keys(row, "in_network", "in_net", "par")
            out_net = _coalesce_keys(row, "out_of_network", "out_network", "oon",
                                     "outofnetwork", "non_par")
            if not _blank(in_net) or not _blank(out_net):
                stated = True
            if _network_pays(in_net):
                pays_in = True
            if _network_pays(out_net):
                pays_out = True
    return pays_in, pays_out, stated


def _network_pays(value) -> bool:
    """Whether a coverage cell states a benefit above 0% for that network."""
    if _blank(value):
        return False
    text = str(value).lower()
    if "not covered" in text or "no coverage" in text:
        return False
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    return bool(m) and float(m.group(1)) > 0


def _portal_in_network(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Whether the network the sheet claims is one this plan pays under.

    Guardian's eligibility page does not say whether this office is in network
    — it states the plan's benefit under each network, per service. A sheet
    saying "In" agrees with a plan that pays in network, "Out" with one that
    pays out of network.
    """
    pays_in, pays_out, stated = _network_coverage(portal_raw)
    if not stated:
        return None
    claimed = _norm_network(sab_raw)
    if claimed == "OUT":
        return "Out" if pays_out else ("In" if pays_in else None)
    if claimed == "IN":
        return "In" if pays_in else ("Out" if pays_out else None)
    if pays_in:
        return "In"
    return "Out" if pays_out else None


def _portal_oon_benefits(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Whether any service pays above 0% out of network."""
    _pays_in, pays_out, stated = _network_coverage(portal_raw)
    if not stated:
        return None
    return "Yes" if pays_out else "No"


def _portal_subscriber_name(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Subscriber name. Guardian's eligibility page names only the patient, so it
    is known only when the patient is the subscriber — never the patient's own
    name standing in for a parent's.
    """
    sub = (portal_raw or {}).get("subscriber_info") or {}
    return None if _blank(sub.get("name")) else bd.get("subscriber_name")


def _portal_subscriber_dob(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Subscriber date of birth, under the same guard as the name."""
    sub = (portal_raw or {}).get("subscriber_info") or {}
    if _blank(sub.get("name")):
        return None
    value = sub.get("dob")
    return None if _blank(value) else str(value)


def _portal_yearly_max_paid(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Amount applied to the yearly max: total − remaining, which Guardian also
    states outright as the year's met-to-date.
    """
    total = _num_money(bd.get("yearly_max"))
    remaining = _num_money(bd.get("yearly_rem"))
    if total is None or remaining is None:
        return None
    if total >= _UNLIMITED_MAX:      # unlimited max → "used" is not derivable
        return None
    return f"{max(total - remaining, 0.0):.2f}"


def _portal_cob(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Coordination of benefits: Guardian's page states Standard for every plan."""
    return _guardian_standard_answer(portal_raw, "cob")


def _portal_eff_date(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Patient effective date: the Preventive date under "Effective dates of
    coverage" (the earliest category's when Preventive has none).
    """
    value = bd.get("eff_date")
    return None if _blank(value) else str(value)


def _ortho_not_covered(portal_raw: dict) -> bool:
    return _guardian_meta(portal_raw).get("ortho_not_covered") is True


def _portal_ortho_max(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Orthodontic maximum; 0 where Guardian states orthodontics is Not Covered."""
    if _ortho_not_covered(portal_raw):
        return "0.00"
    value = bd.get("ortho_max")
    return None if _blank(value) else str(value)


def _portal_ortho_used(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Ortho amount used, under the same rule as the maximum."""
    if _ortho_not_covered(portal_raw):
        return "0.00"
    if not _guardian_meta(portal_raw).get("ortho_max_present"):
        return None
    value = bd.get("ortho_max_paid")
    return None if _blank(value) else str(value)


def _no_ortho_deductible(portal_raw: dict) -> bool:
    """
    Whether the page shows there is no orthodontic deductible: orthodontics
    Not Covered, or an orthodontic maximum alongside a Deductibles table that
    lists only dental deductibles — the sheet records either as 0.
    """
    if _ortho_not_covered(portal_raw):
        return True
    meta = _guardian_meta(portal_raw)
    return bool(meta.get("ortho_max_present") and meta.get("deductibles_listed")
                and not meta.get("ortho_deductible_listed"))


def _portal_ortho_ded(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Orthodontic deductible: 0 where the page shows there is none (above).
    Guardian lists no amount of its own for one, so otherwise the page says
    nothing.
    """
    return "0.00" if _no_ortho_deductible(portal_raw) else None


def _portal_ortho_ded_met(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Amount met against the orthodontic deductible, under the same rule."""
    return "0.00" if _no_ortho_deductible(portal_raw) else None


def _portal_ortho_age(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Orthodontic age limit: Guardian's ortho age limit, or 0 where orthodontics
    is Not Covered — the sheet's 0 for a plan with no orthodontic benefit.
    """
    if _ortho_not_covered(portal_raw):
        return "0"
    age = _guardian_meta(portal_raw).get("ortho_age_limit")
    return age or None


def _portal_major_paid_on(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Guardian pays multi-visit procedures on the preparation date."""
    return _guardian_standard_answer(portal_raw, "major_paid_on")


def _portal_d4341_quads(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    D4341 number of quadrants — the figure Sabrina prints in D4341's Age Limit
    column. Read only where the portal states a count; Guardian's "once per
    quadrant in any 24 consecutive month period" is a frequency, not one.
    """
    value = str(bd.get("d4341_number_of_quads") or "").strip()
    return value if value.isdigit() else None


def _portal_prev_in_max(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Whether preventive services count toward the yearly maximum: No where the
    page says they do not, otherwise Guardian's standard Yes.
    """
    return (_guardian_meta(portal_raw).get("prev_in_max")
            or _guardian_standard_answer(portal_raw, "prev_in_max"))


# Portal values that must be computed rather than read from one breakdown key.
# All share the (breakdown, raw_portal, sheet value) signature so
# `_portal_value` can call them uniformly. "_perio_after_srp" is absent on
# purpose: Guardian's page does not state it, so that row reads "not on portal".
_DERIVED = {
    "_prev_in_max": _portal_prev_in_max,
    "_subscriber_name": _portal_subscriber_name,
    "_subscriber_dob": _portal_subscriber_dob,
    "_cob": _portal_cob,
    "_ortho_max": _portal_ortho_max,
    "_ortho_ded": _portal_ortho_ded,
    "_ortho_age": _portal_ortho_age,
    "_ortho_ded_met": _portal_ortho_ded_met,
    "_ortho_used": _portal_ortho_used,
    "_in_network": _portal_in_network,
    "_oon_benefits": _portal_oon_benefits,
    "_yearly_max_paid": _portal_yearly_max_paid,
    "_major_paid_on": _portal_major_paid_on,
    "_eff_date": _portal_eff_date,
    "_d4341_quads": _portal_d4341_quads,
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
