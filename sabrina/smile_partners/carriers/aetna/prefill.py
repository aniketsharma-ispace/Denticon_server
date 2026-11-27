"""
Aetna's part of the Sabrina Fill Form prefill.

sabrina/smile_partners/prefill.py does the common work (the audit's readers,
the grid, formats) and calls these for what only Aetna's export can answer.
Change Aetna here; other carriers have their own carriers/<carrier>/prefill.py.
"""

import re


def form_only(view: dict, values: dict) -> list[dict]:
    """Relation to Insured, Plan Type, Calendar/Fiscal Year, Ortho Maximum Covered."""
    from shared.portals.aetna import _aetna_export, _aetna_is_medicare_export, _aetna_rows

    raw = _aetna_export(view) or {}
    payer = raw.get("payer") or {}
    out = []

    def add(name, value, level, source, label):
        if value:
            out.append({"name": name, "value": value, "level": level,
                        "source": source, "label": label})

    # Relation to Insured — the payer's Coverage ("Employee", "Spouse", "Child").
    coverage = str(payer.get("coverage") or "").lower()
    relation = None
    if re.search(r"employee|subscriber|self|member", coverage):
        relation = "Self"
    elif re.search(r"spouse|domestic partner", coverage):
        relation = "Spouse"
    elif re.search(r"child|son|daughter|dependent|student", coverage):
        relation = "Dependent"
    add("demographic.relationToInsured", relation, "appointment",
        "payer.coverage", "Relation to Insured")

    # Plan Type — Medicare first: a Medicare plan can also call itself PPO.
    plan_type = str(payer.get("plan_type") or "")
    kind = None
    if _aetna_is_medicare_export(raw):
        kind = "Medicare"
    elif re.search(r"\bPPO\b|preferred provider", plan_type, re.IGNORECASE):
        kind = "PPO"
    elif re.search(r"indemnity", plan_type, re.IGNORECASE):
        kind = "Indemnity"
    add("insuranceDetails.planType", kind, "plan", "payer.plan_type", "Plan Type")

    # Calendar / Fiscal — the Maximums / Deductibles messages ("Calendar Year"),
    # else a plan year that starts in another month is a fiscal one.
    messages = " ".join(str(r.get("message") or "") for table in ("maximums", "deductibles")
                        for r in _aetna_rows(view, table)).lower()
    cal = None
    if "calendar" in messages:
        cal = "Calendar"
    elif values.get("plan_year_start") and values["plan_year_start"] != "January":
        cal = "Fiscal"
    add("insuranceDetails.calendarorfiscal", cal, "plan", "maximums.message", "Calendar/Fiscal Year")

    # Ortho Maximum Covered — the Orthodontics maximum's message. No ortho row,
    # no answer (whether that should still read Lifetime is not confirmed).
    ortho = next((r for r in _aetna_rows(view, "maximums")
                  if "ortho" in str(r.get("type") or "").lower()), None)
    if ortho:
        msg = str(ortho.get("message") or "").lower()
        covered = ("Lifetime" if "lifetime" in msg
                   else "Yearly" if re.search(r"calendar|benefit year|plan year|year", msg) else None)
        add("benefitsInfo.orthoMaximumCovered", covered, "appointment",
            "maximums[Orthodontics].message", "Ortho Maximum Covered")
    return out


def waiting_periods(view: dict) -> list[dict]:
    """Aetna states a waiting period per code in the Service Level table."""
    from shared.portals.aetna import _aetna_row
    from ...prefill import _WAITING_CODES, _waiting_period

    rows = []
    for applies_to, codes in _WAITING_CODES:
        for code in codes:
            found = _waiting_period((_aetna_row(view, code) or {}).get("waiting_period"))
            if found:
                rows.append({"applies_to": applies_to, "period": found[0], "unit": found[1],
                             "source": code})
                break
    return rows


# The scrape holds both networks' tables, so IN OR OON already set on the
# Sabrina form wins over the operator's crawl-time pick (no refusal).
SCRAPE_HOLDS_BOTH_NETWORKS = True


def scrape_network(portal_raw: dict) -> str | None:
    """
    "In" / "Out" as the operator picked on the patient's benefits page while
    crawling (extension 1.66+), so the fill sets IN OR OON by itself. None for
    older crawls or "Decide in Sabrina": the user picks on the form, as before.
    """
    if not isinstance(portal_raw, dict):
        return None
    for candidate in (portal_raw, portal_raw.get("aetna_data"), portal_raw.get("portal_data")):
        if isinstance(candidate, dict):
            choice = str(candidate.get("network_choice") or "").strip().title()
            if choice in ("In", "Out"):
                return choice
    return None
