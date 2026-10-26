"""
Reading the portal side of each field, for a Delta Dental Office Toolkit export.

Most fields come straight out of the shared breakdown that `portals/` produces.
The ones here need more than a lookup — a maximum that belongs to another
class, a network status confirmed against the coverage rows, a clause answer
the Toolkit only states inside a limitation.

Only a Toolkit export reaches this module, so the only carrier rules it calls
are the Toolkit's own, in `rules.py`.
"""

from __future__ import annotations

import re
from .common import _UNLIMITED_MAX
from .vocabulary import (_blank, _coalesce_keys, _norm_network, _num_cob, _num_money,
                         _num_yesno)
from .rules import (_toolkit_code_override, _toolkit_export, _toolkit_major_paid_on,
                    _toolkit_meta, _toolkit_perio_after_srp, _toolkit_procedure)


# The sheet's three headline rows each name a code — "D0120 Preventative",
# "D2160 Basic", "D2740 Major" — and the Toolkit states a percentage per code.
# Its coverage rows group codes under headings ("Minor Restorative", "Major
# Restorative") that the shared category reading does not tell apart, so the
# code's own answer is the one compared. The fallbacks are the codes Delta
# Dental's own folder uses for the same rows.
_HEADLINE_CODES = (
    ("pct_prev", ("D0120", "D1110", "D0150")),
    ("pct_basic", ("D2160", "D2140", "D2331", "D2391")),
    ("pct_major", ("D2740", "D6750", "D5110")),
)


def _portal_for_sheet(portal_raw: dict, sab_fields: dict, fee_schedule=None) -> dict:
    """
    The portal export as this sheet should read it.

    The Toolkit crawl reads one network only — "PPO Dentist" — so there are no
    other networks' answers for the sheet to choose between.
    """
    return portal_raw


def _breakdown_for_sheet(bd: dict, portal_norm: dict) -> dict:
    """
    The breakdown as this sheet reads it: the headline percentages taken from
    the codes their rows name. A code the Toolkit left "Optional", with no
    sibling to resolve it from, states no percentage and is passed over.
    """
    out = dict(bd)
    for key, codes in _HEADLINE_CODES:
        for code in codes:
            level = str((_toolkit_procedure(portal_norm, code) or {}).get("benefit_level") or "").strip()
            if level and level.upper() not in ("N/A", "NA", "OPTIONAL"):
                out[key] = level
                break
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  PORTAL SIDE
# ══════════════════════════════════════════════════════════════════════════════

def _portal_normalized(portal_raw: dict) -> dict:
    """
    The portal export in the shape the derived readers expect.

    The Toolkit's export carries its own layout, which `portals/delta_toolkit.py`
    translates into the standard contract — patient / plan_details /
    financials / covered_services / provisions under `metlife_data`. The readers
    below look for exactly that, so they run against the translation rather than
    the raw export; without this every derived field reads "not on portal" no
    matter what the portal actually said.
    """
    from ....portals.delta_toolkit import _is_dd_toolkit_portal, _normalize_delta_toolkit_portal

    # The export may arrive bare or wrapped by the extension.
    candidates = [portal_raw]
    if isinstance(portal_raw, dict):
        for key in ("cigna_data", "aetna_data", "portal_data"):
            inner = portal_raw.get(key)
            if isinstance(inner, dict):
                candidates.append(inner)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        try:
            normalized = (_normalize_delta_toolkit_portal(candidate)
                          if _is_dd_toolkit_portal(candidate) else None)
            if normalized is not None:
                # A few answers live in carrier-specific corners of the export
                # that the shared contract has no room for, so keep the
                # original reachable rather than re-deriving it.
                normalized.setdefault("_raw_export", candidate)
                return normalized
        except Exception:      # a malformed export must not sink the audit
            continue
    return portal_raw or {}


def _portal_breakdown(portal_raw: dict) -> dict:
    """
    Normalize the insurance portal export into the client's standard breakdown
    dict via `breakdown._extract`.

    The shared breakdown has no reader for the Toolkit's own layout, so it is
    handed the translation, whose Toolkit-only markers (`_toolkit`,
    `_toolkit_meta`) it already honours.

    Denticon is intentionally empty — this flow has no Denticon data — and the
    LLM interpreter is skipped because every audited field is a hard portal
    fact.
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
    A named field off the first CDT code the portal actually reports.

    The frequency field is exempt from the blank vocabulary: Cigna writes
    "Not Applicable" to mean a procedure carries no frequency limit, which is a
    real statement, while everywhere else that phrase means "nothing here".
    """
    for code in codes:
        proc = (procs or {}).get(code.upper())
        if not proc:
            continue
        value = proc.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        # A frequency of "Not Applicable" and a service date of "—" are both
        # statements, though either reads as a blank anywhere else.
        if field in ("frequency_limit", "late_date_of_service") or not _blank(text):
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


def _portal_in_network(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    The network type, confirmed against what the plan actually pays under.

    The portal does NOT reliably state whether this particular office is in or
    out of network — `provider_info.provider_network_status` is scraped by
    matching the first element whose text is exactly "IN-NETWORK" or
    "OUT-OF-NETWORK", and the plan-details page renders both of those as
    coverage-panel headings, so it reads "In-Network" for every patient. It is
    deliberately not used here.

    What the portal does state is the benefit under each network, per category.
    So the check is whether the network the sheet claims is one this plan pays
    under: a sheet saying "Out" against a plan that pays out of network agrees,
    and a sheet saying "Out" against a plan that only pays in network does not.
    Where the plan pays under both — the common case — either claim is valid and
    this correctly reports agreement.

    The Toolkit always reads the "PPO Dentist" network. That is the network
    whose benefits are shown, not whether this office takes part in it, so it
    settles nothing on its own.
    """
    pays_in, pays_out, stated = _network_coverage(portal_raw)

    if stated:
        claimed = _norm_network(sab_raw)
        if claimed == "OUT":
            return "Out" if pays_out else ("In" if pays_in else None)
        if claimed == "IN":
            return "In" if pays_in else ("Out" if pays_out else None)
        # The sheet says nothing — report whichever network the plan pays under.
        if pays_in:
            return "In"
        if pays_out:
            return "Out"
        return None

    # No coverage table. A named network arrangement (PPO / Premier / HMO) still
    # shows the plan operates in network; nothing else here settles it.
    for cand in (bd.get("network_status"), bd.get("fee_schedule"), bd.get("plan_type")):
        verdict = _norm_network(cand)
        if verdict:
            return "In" if verdict == "IN" else "Out"
    return None


def _network_pays(value) -> bool:
    """Whether a coverage cell states a benefit above 0% for that network."""
    if _blank(value):
        return False
    text = str(value).lower()
    if "not covered" in text or "no coverage" in text:
        return False
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    return bool(m) and float(m.group(1)) > 0


def _portal_yearly_max_paid(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Amount applied to the yearly max. Portals report the REMAINING balance, so
    paid-to-date = total − remaining.
    """
    total = _num_money(bd.get("yearly_max"))
    remaining = _num_money(bd.get("yearly_rem"))
    if total is None or remaining is None:
        return None
    if total >= _UNLIMITED_MAX:      # unlimited max → "used" is not derivable
        return None
    return f"{max(total - remaining, 0.0):.2f}"


def _portal_cob(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Coordination-of-benefits method as stated in the portal's provisions.
    """
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}
    for prov in (ml.get("provisions") or []):
        if not isinstance(prov, dict):
            continue
        if "coordination of benefits" not in str(prov.get("rule", "")).lower():
            continue
        method = _num_cob(prov.get("value"))
        if method:
            return method[1]
        # The provision exists but names no method we recognize — report the
        # raw text rather than silently claiming the portal said nothing.
        return str(prov.get("value", "")).strip() or None

    return None


def _ortho_is_covered(portal_raw: dict) -> bool | None:
    """Whether the portal states orthodontics is covered at all."""
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}
    for row in (ml.get("covered_services") or []):
        if not isinstance(row, dict):
            continue
        if "ORTHODONT" not in str(row.get("category", "")).upper():
            continue
        cells = " ".join(str(row.get(k, "")) for k in
                         ("in_network", "out_of_network", "out_network")).lower()
        if not cells.strip():
            return None
        return "not covered" not in cells
    return None


def _lifetime_belongs_elsewhere(portal_raw: dict) -> str | None:
    """
    The class a non-orthodontic lifetime maximum belongs to, if any.

    MetLife's Lifetime card has a Category selector, and on some plans the only
    lifetime maximum is TMJ — a separate class that this audit does not cover.
    """
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}
    lifetime = (ml.get("financials") or {}).get("ortho_lifetime")
    if not isinstance(lifetime, dict):
        return None
    category = lifetime.get("category")
    if _blank(category):
        return None
    text = str(category).strip()
    return None if re.search(r"orthodont|^ortho\b", text, re.IGNORECASE) else text


def _portal_ortho_age(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Orthodontic age limit.

    The Toolkit states it once for the plan — "orthodontic age limit for this
    patient is covered for age 19", or the PPO Dentist age caps — rather than
    on each orthodontic code, so the plan's answer is taken first.
    """
    procs = bd.get("procs", {})
    codes = ("D8080", "D8090", "D8010")
    value = _procfield_from_procs(procs, "age_limit", codes)
    # Orthodontics the plan does not cover is age 0 (or blank).
    handled, corrected = _toolkit_code_override(value, portal_raw, codes, "age_limit", sab_raw)
    if handled:
        return corrected
    meta = _toolkit_meta(portal_raw)
    if meta.get("ortho_covered") is False:
        return None if _blank(sab_raw) else "0"
    return str(meta.get("age_limit_ortho") or "").strip() or value


def _portal_ortho_ded(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Orthodontic deductible, as the breakdown states it."""
    value = bd.get("ortho_ded")
    return None if _blank(value) else str(value)


def _portal_ortho_ded_met(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Amount met against the orthodontic deductible, as the breakdown states it."""
    value = bd.get("ortho_ded_paid")
    return None if _blank(value) else str(value)


def _portal_ortho_max(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Orthodontic lifetime maximum, guarded against another class's figure.

    Two ways a non-zero maximum here can be wrong: the portal's only lifetime
    maximum belongs to a different class (TMJ), or the plan states orthodontics
    is not covered at all — in which case there is no orthodontic maximum to
    report and the sheet's 0 is correct.
    """
    other = _lifetime_belongs_elsewhere(portal_raw)
    if other:
        return "0.00"
    if _ortho_is_covered(portal_raw) is False:
        return "0.00"
    value = bd.get("ortho_max")
    return None if _blank(value) else str(value)


def _portal_ortho_used(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Ortho amount used, under the same guards as the maximum."""
    if _lifetime_belongs_elsewhere(portal_raw) or _ortho_is_covered(portal_raw) is False:
        return "0.00"
    value = bd.get("ortho_max_paid")
    return None if _blank(value) else str(value)


def _portal_prev_in_max(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Whether preventive services count toward the yearly maximum.

    Read from the General maximum's description, which the Toolkit words
    either as a list ("for Diagnostic, Preventive, Restorative, …") or as an
    exception ("all services except Preventive"). `portals/delta_toolkit.py`
    reads both; a description that names neither leaves the row unstated
    rather than guessed at.
    """
    from ....portals.delta_toolkit import annual_max_includes_preventive

    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}
    annual = (ml.get("financials") or {}).get("annual_max") or {}
    description = annual.get("description") if isinstance(annual, dict) else None
    if _blank(description):
        return None
    return annual_max_includes_preventive(description)


def _portal_oon_benefits(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Whether the plan pays anything out of network.

    Read from the per-category `covered_services` rows, which carry an
    `out_of_network` benefit alongside the in-network one:

        {"category": "PREVENTIVE",
         "in_network":     "100% Deductible Applies : No",
         "out_of_network": "100% Deductible Applies : No"}

    Any category paying more than 0% out of network means the plan has OON
    benefits. Only when no category states an OON benefit at all do we fall
    back to the provision text — and an in-network fee schedule is never taken
    to imply OON coverage.
    """
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}

    services = ml.get("covered_services")
    if isinstance(services, list) and services:
        stated = pays = False
        for row in services:
            if not isinstance(row, dict):
                continue
            raw = _coalesce_keys(row, "out_of_network", "out_network", "oon",
                                 "outofnetwork", "non_par")
            if _blank(raw):
                continue
            stated = True
            text = str(raw).lower()
            if "not covered" in text or "no coverage" in text:
                continue
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if m and float(m.group(1)) > 0:
                pays = True
                break
        if stated:
            return "Yes" if pays else "No"

    blobs = []
    for prov in (ml.get("provisions") or []):
        blobs.append(" ".join(str(v) for v in prov.values()) if isinstance(prov, dict) else str(prov))
    flat = " ".join(blobs).lower()
    if not flat:
        return None
    if "no out-of-network" in flat or "no out of network" in flat:
        return "No"
    if "out-of-network" in flat or "out of network" in flat:
        return "Yes"
    return None


def _portal_eff_date(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Patient effective date, as the breakdown states it."""
    value = bd.get("eff_date")
    return None if _blank(value) else str(value)


def _portal_dep_age_limit(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    The plan's dependent age limit. The breakdown writes "NAL" both when the
    plan has no limit and when the export never mentions one, so it is read as
    unstated rather than as "no limit" — either reading could invent a verdict.
    """
    value = bd.get("dep_age_limit")
    if _blank(value) or str(value).strip().upper() == "NAL":
        return None
    return str(value)


def _portal_major_paid_on(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    Whether major services are paid on the prep or the seat date.

    Toolkit: as its notes state it, else "Seat Date" where D2740 is covered.
    Otherwise taken from the breakdown's prep/seat answers where the portal
    states them.
    """
    if _toolkit_export(portal_raw):
        return _toolkit_major_paid_on(portal_raw)
    if _num_yesno(bd.get("or_seat")) == "YES":
        return "Seat Date"
    if _num_yesno(bd.get("major_on_prep")) == "YES":
        return "Prep Date"
    return None


def _portal_perio_after_srp(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    When the first perio maintenance is allowed after SRP.

    Toolkit: the post-operative period D4910's limitations name.
    """
    if _toolkit_export(portal_raw):
        return _toolkit_perio_after_srp(portal_raw)
    return None


def _portal_d4341_quads(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    D4341 number of quadrants — the figure Sabrina prints in D4341's Age Limit
    column: the breakdown's count when it is a number ("Pre-D" and dashes are
    not).
    """
    value = str(bd.get("d4341_number_of_quads") or "").strip()
    return value if value.isdigit() else None


# Portal values that must be computed rather than read from one breakdown key.
# All three share the (breakdown, raw_portal) signature so `_portal_value` can
# call them uniformly, even where one of the two arguments isn't needed.
_DERIVED = {
    "_cob": _portal_cob,
    "_ortho_max": _portal_ortho_max,
    "_ortho_ded": _portal_ortho_ded,
    "_ortho_age": _portal_ortho_age,
    "_ortho_ded_met": _portal_ortho_ded_met,
    "_ortho_used": _portal_ortho_used,
    "_prev_in_max": _portal_prev_in_max,
    "_in_network": _portal_in_network,
    "_oon_benefits": _portal_oon_benefits,
    "_yearly_max_paid": _portal_yearly_max_paid,
    "_major_paid_on": _portal_major_paid_on,
    "_eff_date": _portal_eff_date,
    "_perio_after_srp": _portal_perio_after_srp,
    "_d4341_quads": _portal_d4341_quads,
    "_dep_age_limit": _portal_dep_age_limit,
}


def _portal_value(field: dict, bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Resolve one spec'd field's value on the portal side."""
    src = field.get("portal")
    if src is None:
        return None
    if isinstance(src, tuple) and src and src[0] == "code":
        return _pct_from_procs(bd.get("procs", {}), src[1:])
    if isinstance(src, tuple) and src and src[0] == "codefield":
        value = _procfield_from_procs(bd.get("procs", {}), src[1], src[2:])
        handled, corrected = _toolkit_code_override(value, portal_raw, src[2:], src[1], sab_raw)
        return corrected if handled else value
    if isinstance(src, str) and src in _DERIVED:
        return _DERIVED[src](bd, portal_raw, sab_raw)
    val = bd.get(src) if isinstance(src, str) else None
    return None if _blank(val) else str(val)