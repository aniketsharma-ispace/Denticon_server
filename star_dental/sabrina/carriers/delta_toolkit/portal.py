"""
Reading the portal side of each field.

Most fields come straight out of the shared breakdown that `portals/` produces.
The ones here need more than a lookup — a maximum that belongs to another
class, a network status stated only as a dropdown, a coordination rule worded
five different ways.
"""

from __future__ import annotations

import re
from .common import _UNLIMITED_MAX
from .vocabulary import _blank, _coalesce_keys, _norm_network, _num_cob, _num_frequency, _num_money
from .rules import (
    _toolkit_d0150_per_provider,
    _toolkit_dependent_age_limit,
    _toolkit_eligibility,
    _toolkit_insurance_phone,
    _toolkit_major_payment_timing,
    _toolkit_meta_value,
    _toolkit_ortho_max_type,
    _toolkit_ortho_payment_timing,
    _toolkit_posterior_crown_downgrade,
    _toolkit_raw_section,
    _toolkit_relationship,
    _toolkit_srp_quads_per_day,
    _toolkit_subscriber_age_limit,
)


# ══════════════════════════════════════════════════════════════════════════════
#  PORTAL SIDE
# ══════════════════════════════════════════════════════════════════════════════

def _portal_normalized(portal_raw: dict, network: str | None = None) -> dict:
    """
    The portal export in the shape the derived readers expect.

    The Toolkit's export carries its own layout, which `portals/delta_toolkit.py`
    translates into the standard contract — patient / plan_details /
    financials / covered_services / provisions under `metlife_data`. The readers
    below look for exactly that, so they run against the translation rather than
    the raw export; without this every derived field reads "not on portal" no
    matter what the portal actually said. `network` is the Delta network the
    sheet records (None for PPO Dentist).
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
            normalized = (_normalize_delta_toolkit_portal(candidate, network)
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


def _portal_breakdown(portal_raw: dict, network: str | None = None) -> dict:
    """
    Normalize the insurance portal export (or parsed carrier PDF) into the
    client's standard breakdown dict via `breakdown._extract`.

    Denticon is intentionally empty — this flow has no Denticon data — and the
    LLM interpreter is skipped because every audited field is a hard portal
    fact. `network` is the Delta network the sheet records (None for PPO).
    """
    from ....breakdown import _extract as _extract_breakdown
    from ....portals.delta_toolkit import _is_dd_toolkit_portal, _normalize_delta_toolkit_portal

    if _is_dd_toolkit_portal(portal_raw):
        payload = _normalize_delta_toolkit_portal(portal_raw, network)
    else:
        payload = dict(portal_raw or {})
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

    The portal does NOT reliably state whether this particular office
    is in or out of network — `provider_info.provider_network_status` was
    scraped by matching the first element whose text is exactly "IN-NETWORK"
    or "OUT-OF-NETWORK", and the plan-details page renders both of those as
    coverage-panel headings, so it reads "In-Network" for every patient. It is
    deliberately not used here.

    What the portal does state is the benefit under each network, per category.
    So the check is whether the network the sheet claims is one this plan pays
    under: a sheet saying "Out" against a plan that pays out of network agrees,
    and a sheet saying "Out" against a plan that only pays in network does not.
    Where the plan pays under both — the common case — either claim is valid and
    this correctly reports agreement.
    """
    if isinstance(portal_raw, dict) and portal_raw.get("_toolkit"):
        fee_network = str((portal_raw.get("_toolkit_meta") or {}).get("fee_schedule_network") or "")
        if fee_network:
            return fee_network

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

    Cigna publishes no such provision — its export carries an empty provisions
    list — and the agreed reading for Cigna is the Standard method, so that is
    returned rather than leaving the row unstated.
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

    if str((portal_raw or {}).get("_source_insurer", "")).lower() == "cigna":
        return "Standard"
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
        if portal_raw.get("_toolkit"):
            percents = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", cells)]
            if percents:
                return max(percents) > 0
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
    """
    if isinstance(portal_raw, dict) and portal_raw.get("_toolkit"):
        toolkit_age = _toolkit_meta_value(portal_raw, "age_limit_ortho")
        if toolkit_age:
            return toolkit_age
        if (portal_raw.get("_toolkit_meta") or {}).get("ortho_covered") is False:
            return "0"
    procs = bd.get("procs", {})
    return _procfield_from_procs(procs, "age_limit", ("D8080", "D8090", "D8010"))


def _portal_ortho_ded(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Orthodontic deductible, or 0 where the plan has no ortho deductible."""
    value = bd.get("ortho_ded")
    if not _blank(value):
        return str(value)
    return None


def _portal_ortho_ded_met(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Amount met against the orthodontic deductible, under the same rule."""
    value = bd.get("ortho_ded_paid")
    if not _blank(value):
        return str(value)
    return None


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

    The portal states it as the category list printed under the Annual maximum —
    "for Diagnostic, Preventive, Restorative, Endodontics, Prosthodontics, Oral
    Surgery, Adjunctive, Implant Services". Preventive appearing in that list
    means it draws down the maximum.

    Captured by the extension as financials.annual_max.applies_to; exports made
    before that was added simply have nothing here, and the row stays unstated
    rather than guessed at.
    """
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}
    financials = ml.get("financials") or {}
    annual = financials.get("annual_max") or {}
    # The scraper records the Annual card's category line — "for Diagnostic,
    # Preventive, Restorative, …" — as `description`; older builds used
    # `applies_to`, so both are accepted.
    applies = (_coalesce_keys(annual, "applies_to", "description")
               if isinstance(annual, dict) else None)
    if _blank(applies):
        return None
    text = str(applies).lower()
    if isinstance(portal_raw, dict) and portal_raw.get("_toolkit"):
        from ....portals.delta_toolkit import annual_max_includes_preventive
        toolkit_answer = annual_max_includes_preventive(text)
        if toolkit_answer:
            return toolkit_answer
    if "preventive" in text or "preventative" in text:
        return "Yes"
    if "all" in text and "except" in text and "prevent" not in text:
        return "Yes"
    return "No"


def _frequencies_shared(freq_a, freq_b) -> str | None:
    """Yes when both codes state the same counted frequency, No when they state different ones."""
    parsed = [_num_frequency(freq_a), _num_frequency(freq_b)]
    if any(f is None or not isinstance(f[0], int) for f in parsed):
        return None
    return "Yes" if parsed[0] == parsed[1] else "No"


# A cleaning sentence that grants periodontal prophylaxes or maintenance on top
# of the cleanings ("Two additional periodontal prophylaxes are payable …",
# "… in addition to periodontal maintenance") states two separate allowances,
# even when the two counts happen to be equal.
_SEPARATE_PERIO_ALLOWANCE_RE = re.compile(
    r"\badditional\s+periodontal\b"
    r"|\bin\s+addition\s+to\s+periodontal\b"
    r"|\bperiodontal\s+(?:maintenance|prophylax\w*)\b[^.]*\bin\s+addition\b",
    re.IGNORECASE,
)


_NAMES_PERIO_MAINTENANCE_RE = re.compile(
    r"\bperiodontal\s+(?:maintenance|prophylax\w*)\b|\bperio\s+maintenance\b|\bD4910\b",
    re.IGNORECASE,
)


def _perio_allowance_is_separate(procs: dict) -> bool:
    prophy = procs.get("D1110") or {}
    perio = procs.get("D4910") or {}
    if not prophy or not perio or any(
        str(p.get("benefit_level") or "").strip().lower() in ("", "not covered")
        for p in (prophy, perio)
    ):
        return False
    sources = " ".join(str(p.get("frequency_source") or "") for p in (prophy, perio))
    return bool(_SEPARATE_PERIO_ALLOWANCE_RE.search(sources))


def _portal_share_frequency(field: dict, bd: dict) -> str | None:
    codes = field.get("shares") or ()
    if len(codes) != 2:
        return None
    procs = bd.get("procs", {})
    if tuple(codes) == ("D1110", "D4910") and _perio_allowance_is_separate(procs):
        return "No"
    shared = _frequencies_shared(*(
        _procfield_from_procs(procs, "frequency_limit", (code,)) for code in codes))
    if shared is None and tuple(codes) == ("D1110", "D4910"):
        return _prophy_perio_shared_from_text(procs)
    return shared


def _prophy_perio_shared_from_text(procs: dict) -> str | None:
    prophy = procs.get("D1110") or {}
    perio = procs.get("D4910") or {}
    if not prophy or not perio:
        return None
    if any(
        str(p.get("benefit_level") or "").strip().lower() in ("", "not covered")
        for p in (prophy, perio)
    ):
        return None
    prophy_freq = _num_frequency(prophy.get("frequency_limit"))
    if prophy_freq is None or not isinstance(prophy_freq[0], int):
        return None
    perio_freq = _num_frequency(perio.get("frequency_limit"))
    if perio_freq is not None and isinstance(perio_freq[0], int):
        return None
    source = str(prophy.get("frequency_source") or "")
    if re.search(r"in\s+addition", source, re.IGNORECASE):
        return "No"
    # A cleaning sentence that never mentions periodontal maintenance says
    # nothing about whether the two share a limit.
    return "Yes" if _NAMES_PERIO_MAINTENANCE_RE.search(source) else None


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
    "_toolkit_eligibility": _toolkit_eligibility,
    "_toolkit_relationship": _toolkit_relationship,
    "_toolkit_major_payment_timing": _toolkit_major_payment_timing,
    "_toolkit_ortho_max_type": _toolkit_ortho_max_type,
    "_toolkit_ortho_payment_timing": _toolkit_ortho_payment_timing,
    "_toolkit_insurance_phone": _toolkit_insurance_phone,
    "_toolkit_dependent_age_limit": _toolkit_dependent_age_limit,
    "_toolkit_subscriber_age_limit": _toolkit_subscriber_age_limit,
    "_toolkit_srp_quads_per_day": _toolkit_srp_quads_per_day,
    "_toolkit_posterior_crown_downgrade": _toolkit_posterior_crown_downgrade,
    "_toolkit_d0150_per_provider": _toolkit_d0150_per_provider,
}


def _portal_value(field: dict, bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Resolve one spec'd field's value on the portal side."""
    src = field.get("portal")
    if src is None:
        return None
    # The Toolkit's member ID lives in member_details.memberAlternateId, not
    # in the shared legacy breakdown shape. Expose it when the source provides
    # it instead of reporting a false evidence gap.
    if src == "member_id" and isinstance(portal_raw, dict) and portal_raw.get("_toolkit"):
        member_id = _toolkit_raw_section(portal_raw, "member_details", "memberAlternateId")
        # Some older fixture/export variants use a lone "N" placeholder rather
        # than a member identifier. Treat it as absent instead of comparing it
        # with a real Sabrina member ID.
        if not _blank(member_id) and str(member_id).strip().upper() != "N":
            return str(member_id).strip()
        return None
    if (
        src == "porcelain_posterior_downgrade"
        and isinstance(portal_raw, dict) and portal_raw.get("_toolkit")
    ):
        return _toolkit_posterior_crown_downgrade(bd, portal_raw, sab_raw)
    if isinstance(src, tuple) and src and src[0] == "code":
        codes = src[1:]
        if isinstance(portal_raw, dict) and portal_raw.get("_toolkit"):
            codes = codes[:1]  # Toolkit comparison is exact CDT-to-CDT only.
        return _pct_from_procs(bd.get("procs", {}), codes)
    if isinstance(src, tuple) and src and src[0] == "codefield":
        codes = src[2:]
        if isinstance(portal_raw, dict) and portal_raw.get("_toolkit"):
            codes = codes[:1]  # no fallback code for Toolkit
        return _procfield_from_procs(bd.get("procs", {}), src[1], codes)
    if src == "_share_frequency":
        return _portal_share_frequency(field, bd)
    if isinstance(src, str) and src in _DERIVED:
        return _DERIVED[src](bd, portal_raw, sab_raw)
    val = bd.get(src) if isinstance(src, str) else None
    return None if _blank(val) else str(val)
