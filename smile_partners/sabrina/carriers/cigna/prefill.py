"""
Cigna's part of the Sabrina Fill Form prefill.

smile_partners/sabrina/prefill.py does the common work and calls these.
Change Cigna here; other carriers have their own carriers/<carrier>/prefill.py.
"""

import re


def scrape_network(portal_raw: dict) -> str | None:
    """
    The network the crawl ran under. Cigna's network is picked on the portal
    (Plan View dropdown) before scraping, so the scrape holds that one only:
    TOTAL / ADVANTAGE / ... are "In", Out-of-Network (OONET) is "Out".
    """
    from .portal import _portal_normalized
    from .rules import _cigna_in_network
    return _cigna_in_network(_portal_normalized(portal_raw))


def form_only(view: dict, values: dict) -> list[dict]:
    """
    Relation to Insured, Plan Type, Calendar/Fiscal Year and Ortho Maximum
    Covered, from the Patient and Plan Detail and Benefit Maximums cards
    (business rules, 11/2026).
    """
    from .rules import _cigna_export
    from ....portals.cigna import _cigna_class_codes, _cigna_matching_records

    raw = _cigna_export(view) or {}
    plan = raw.get("plan_details") or {}
    out = []

    def add(name, value, level, source, label):
        if value:
            out.append({"name": name, "value": value, "level": level,
                        "source": source, "label": label})

    # Relation to Insured — the patient card's Relationship ("Self", "Spouse",
    # "Child"); BPO feedback 11/25: it was never filled for Cigna.
    relationship = str((raw.get("patient") or {}).get("relationship") or "").lower()
    relation = None
    if re.search(r"self|subscriber|employee|member|insured", relationship):
        relation = "Self"
    elif re.search(r"spouse|domestic partner|husband|wife", relationship):
        relation = "Spouse"
    elif re.search(r"child|son|daughter|dependent|student", relationship):
        relation = "Dependent"
    add("demographic.relationToInsured", relation, "appointment",
        "patient.relationship", "Relation to Insured")

    # Plan Type — "DENTAL PPO" / "Preferred Provider Organization-..." -> PPO,
    # "DENTAL INDEMNITY" -> Indemnity.
    plan_type = str(plan.get("plan_type") or (raw.get("summary") or {}).get("plan_type") or "")
    kind = None
    if re.search(r"\bPPO\b|preferred provider", plan_type, re.IGNORECASE):
        kind = "PPO"
    elif re.search(r"indemnity", plan_type, re.IGNORECASE):
        kind = "Indemnity"
    add("insuranceDetails.planType", kind, "plan", "plan_details.plan_type", "Plan Type")

    # Calendar / Fiscal — Plan Renews: "Every Calendar Year" is Calendar; any
    # other plan year ("Every Policy Year", "Plan Year", ...) is Fiscal.
    renews = str(plan.get("plan_renews") or "").lower()
    cal = None
    if "calendar" in renews:
        cal = "Calendar"
    elif "year" in renews:
        cal = "Fiscal"
    add("insuranceDetails.calendarorfiscal", cal, "plan", "plan_details.plan_renews",
        "Calendar/Fiscal Year")

    # Ortho Maximum Covered — Benefit Maximums card:
    #   Orthodontics listed under the yearly maximum (with Basic, Major, ...) -> Yearly;
    #   Orthodontics in its own section with a Lifetime maximum            -> Lifetime.
    network = raw.get("selected_network") or plan.get("network") or {}
    records = _cigna_matching_records(
        (raw.get("financials") or {}).get("maximum_records") or [], network)

    def has_ortho(record):
        return ("4" in _cigna_class_codes(record)
                or "ortho" in str(record.get("classDesc") or "").lower())

    def is_lifetime(record):
        return (str(record.get("planPeriodCode") or "").upper() == "LFT"
                or "lifetime" in str(record.get("desc") or "").lower())

    covered = None
    ortho_records = [r for r in records if isinstance(r, dict) and has_ortho(r)]
    if any(not is_lifetime(r) for r in ortho_records):
        covered = "Yearly"
    elif ortho_records:
        covered = "Lifetime"
    add("benefitsInfo.orthoMaximumCovered", covered, "appointment",
        "financials.maximum_records", "Ortho Maximum Covered")
    return out