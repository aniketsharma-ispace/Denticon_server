"""
Aetna's part of the Sabrina Fill Form prefill.

sabrina/smile_partners/prefill.py does the common work (the audit's readers,
the grid, formats) and calls these for what only Aetna's export can answer.
Change Aetna here; other carriers have their own carriers/<carrier>/prefill.py.
"""

import re

# A member's relationship as ClaimConnect words it → the form's Relation to Insured.
_RELATIONS = (
    (r"\b(?:self|subscriber|employee|member|insured)\b", "Self"),
    (r"spouse|domestic\s+partner", "Spouse"),
    (r"child|son|daughter|dependent|student", "Dependent"),
)

# Coverage tiers that cover one person only: the patient is then the insured.
# A tier covering several ("Employee and Spouse", "Family") says who is
# covered, not which of them the patient is.
_ONE_PERSON_TIERS = (
    (r"employee|subscriber|individual|self|member", "Self"),
    (r"spouse|domestic\s+partner", "Spouse"),
    (r"child|children|dependent", "Dependent"),
)


def _same_person(a: dict, b: dict) -> bool:
    name = lambda m: re.sub(r"[^A-Z]", "", str((m or {}).get("name") or "").upper())
    dob = lambda m: str((m or {}).get("date_of_birth") or "").strip()
    return bool(name(a)) and name(a) == name(b) and bool(dob(a)) and dob(a) == dob(b)


def _relation(raw: dict) -> tuple[str | None, str | None]:
    """
    (Relation to Insured, where it was read) for the patient, or (None, None).

    BPO data check 11/27: Stephen Shearin, the subscriber's spouse, was filled
    as Self — the old reading took the payer's Coverage tier ("Employee and
    Spouse"), which lists who is covered, as the patient's relationship.
    """
    def word(text):
        return next((v for pattern, v in _RELATIONS if re.search(pattern, str(text or ""), re.I)), None)

    patient = raw.get("patient") or raw.get("patient_information") or {}
    # 1. The member picked on the eligibility page (extension, 11/27).
    found = word((raw.get("selected_member") or {}).get("relationship"))
    if found:
        return found, "selected_member.relationship"
    # 2. The patient's own row in the eligibility member list.
    for member in raw.get("eligibility_members") or []:
        if isinstance(member, dict) and re.sub(r"[^A-Z]", "", str(member.get("name") or "").upper()) \
                == re.sub(r"[^A-Z]", "", str(patient.get("name") or "").upper()) != "":
            found = word(member.get("relationship"))
            if found:
                return found, "eligibility_members.relationship"
    # 3. The patient is the subscriber: same name and date of birth.
    if _same_person(patient, raw.get("subscriber") or {}):
        return "Self", "patient = subscriber"
    # 4. A coverage tier that covers one person only.
    tier = str((raw.get("payer") or {}).get("coverage") or "").strip()
    for pattern, value in _ONE_PERSON_TIERS:
        if re.fullmatch(rf"(?:{pattern})(?:\s+only)?", tier, re.I):
            return value, "payer.coverage"
    return None, None


def _cob(raw: dict) -> str | None:
    """
    COORDINATION OF BENEFITS from the plan remarks ("Standard COB",
    "Non-duplicating COB"), as the form's dropdown option (team rule 11/26,
    RULES.md). The audit's COB reader looks for MetLife-style provisions and
    never finds Aetna's, so it was never filled (BPO data check 11/27).
    """
    from ...prefill import _cob_option
    for remark in raw.get("plan_level_remarks") or []:
        for part in str(remark).split(","):
            if re.search(r"\bCOB\b|coordination\s+of\s+benefits", part, re.I):
                option = _cob_option(part)
                if option:
                    return option
    return None


def form_only(view: dict, values: dict) -> list[dict]:
    """Relation to Insured, COB, Plan Type, Calendar/Fiscal Year, Ortho Maximum Covered."""
    from shared.portals.aetna import _aetna_export, _aetna_is_medicare_export, _aetna_rows

    raw = _aetna_export(view) or {}
    payer = raw.get("payer") or {}
    out = []

    def add(name, value, level, source, label):
        if value:
            out.append({"name": name, "value": value, "level": level,
                        "source": source, "label": label})

    relation, source = _relation(raw)
    add("demographic.relationToInsured", relation, "appointment", source, "Relation to Insured")

    # The spec's own COB reader answers first, if it ever does.
    if not values.get("cob"):
        add("insuranceDetails.coordinationOfBenefits", _cob(raw), "plan",
            "plan_level_remarks", "Coordination of Benefits")

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
