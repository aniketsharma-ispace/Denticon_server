"""
Aetna (ClaimConnect)'s part of Star Dental's Sabrina Fill Form prefill.

sabrina/star_dental/prefill.py does the common work and calls these.
Change Aetna (ClaimConnect) here; other carriers have their own carriers/<carrier>/prefill.py,
and Smile Partners has its own copy of this folder.

form_only answers what Star's audit list has no Aetna reader for, from the
export's own wording (BPO data check 11/27, Stephen Shearin): Relation to
Subscriber, Coordination of Benefits, the three "share freq?" questions and
Ortho Maximum Covered. Filled only, never audited.
"""

import re

# D0120 Preventative / D2160 Basic / D2740 Major %: on Star's Fill Form (Sabrina
# builds the plan name from them) but not in Star's audit list, so read here
# and filled only, never audited. Read from the plan's class percentages, as Smile Partners' spec reads them.
FORM_ONLY_SPEC = [
    {"key": "pct_prev",  "label": "D0120 Preventative", "kind": "pct", "section": "Plan Provisions",
     "portal": 'pct_prev'},
    {"key": "pct_basic", "label": "D2160 Basic",        "kind": "pct", "section": "Plan Provisions",
     "portal": 'pct_basic'},
    {"key": "pct_major", "label": "D2740 Major",        "kind": "pct", "section": "Plan Provisions",
     "portal": 'pct_major'},
]

# A member's relationship as ClaimConnect words it → Relation to Subscriber.
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

# Star's "share freq?" questions → the two codes whose Service Level rows say
# whether they share a frequency ("Shares frequency with D0330,…").
_SHARED = (
    ("D0120andD0140sharefreq?",             "D0120", "D0140", "D0120 and D0140 share freq?"),
    ("FMXandPanosharefreq?",                "D0210", "D0330", "FMX and Pano share freq?"),
    ("ProphyandPeriomaintenancesharefreq?", "D1110", "D4910", "Prophy and Perio maintenance share freq?"),
)


def _export(values: dict) -> dict:
    raw = values.get("_raw") or {}
    for key in ("aetna_data", "portal_data"):
        if isinstance(raw.get(key), dict) and raw[key].get("in_network"):
            return raw[key]
    return raw


def _name(member) -> str:
    return re.sub(r"[^A-Z]", "", str((member or {}).get("name") or "").upper())


def _relation(raw: dict) -> tuple[str | None, str | None]:
    """(Relation to Subscriber, where it was read) for the patient, or (None, None)."""
    def word(text):
        return next((v for pattern, v in _RELATIONS if re.search(pattern, str(text or ""), re.I)), None)

    patient = raw.get("patient") or raw.get("patient_information") or {}
    # 1. The member picked on the eligibility page.
    found = word((raw.get("selected_member") or {}).get("relationship"))
    if found:
        return found, "selected_member.relationship"
    # 2. The patient's own row in the eligibility member list.
    for member in raw.get("eligibility_members") or []:
        if isinstance(member, dict) and _name(member) and _name(member) == _name(patient):
            found = word(member.get("relationship"))
            if found:
                return found, "eligibility_members.relationship"
    # 3. The patient is the subscriber: same name and date of birth.
    subscriber = raw.get("subscriber") or {}
    dob = lambda m: str((m or {}).get("date_of_birth") or "").strip()
    if _name(patient) and _name(patient) == _name(subscriber) and dob(patient) and dob(patient) == dob(subscriber):
        return "Self", "patient = subscriber"
    # 4. A coverage tier that covers one person only.
    tier = str((raw.get("payer") or {}).get("coverage") or "").strip()
    for pattern, value in _ONE_PERSON_TIERS:
        if re.fullmatch(rf"(?:{pattern})(?:\s+only)?", tier, re.I):
            return value, "payer.coverage"
    return None, None


def _cob(raw: dict) -> str | None:
    """COB from the plan remarks ("Standard COB", "Non-duplicating COB")."""
    from ...prefill import _cob_option
    for remark in raw.get("plan_level_remarks") or []:
        for part in str(remark).split(","):
            if re.search(r"\bCOB\b|coordination\s+of\s+benefits", part, re.I):
                option = _cob_option(part)
                if option:
                    return option
    return None


def _service_rows(raw: dict) -> dict:
    """The Service Level rows by code: in-network first, else out-of-network."""
    rows = {}
    for table in ("out_of_network", "in_network"):
        for row in (raw.get(table) or {}).get("service_level_benefits") or []:
            if isinstance(row, dict) and row.get("procedure_code"):
                rows[str(row["procedure_code"]).upper()] = row
    return rows


def _shares_with(row: dict) -> set[str]:
    """The codes a row says it shares its frequency with — nothing else it mentions."""
    text = str(row.get("shares_frequency_with") or "")
    if not text.strip():
        m = re.search(r"shares\s+frequency\s+with\s+([^.;]*)", str(row.get("message") or ""), re.I)
        text = m.group(1) if m else ""
    return set(re.findall(r"\bD\d{4}\b", text.upper()))


def _share_answer(rows: dict, a: str, b: str) -> str | None:
    """Yes when either code's row names the other, No when both rows are listed and neither does."""
    if a not in rows or b not in rows:
        return None
    return "Yes" if b in _shares_with(rows[a]) or a in _shares_with(rows[b]) else "No"


def form_only(view: dict, values: dict) -> list[dict]:
    """Relation to Subscriber, COB, the share-freq questions, Ortho Maximum Covered."""
    raw = _export(values)
    out = []

    relation, source = _relation(raw)
    if relation:
        out.append({"name": "demographic.relationToInsured", "value": relation, "level": "appointment",
                    "source": source, "label": "Relation to Subscriber"})

    # Star's sheet: "Is Coordination of Benefits Nonduplication". The spec's
    # own reader answers first, if it ever does for Aetna.
    if not values.get("cob"):
        cob = _cob(raw)
        if cob:
            out.append({"name": "insuranceDetails.coordinationOfBenefits", "value": cob, "level": "plan",
                        "source": "plan_level_remarks", "label": "Coordination of Benefits"})

    rows = _service_rows(raw)
    # An export that states no shared frequency anywhere is silent, not "No".
    if not any(_shares_with(row) for row in rows.values()):
        rows = {}
    for question, a, b, label in _SHARED:
        answer = _share_answer(rows, a, b)
        if answer:
            out.append({"question": question, "value": answer, "level": "plan",
                        "source": f"service_level_benefits[{a},{b}].shares_frequency_with", "label": label})

    # Ortho Maximum Covered — a row of Star's Orthodontics grid: the
    # Orthodontics maximum's message ("Lifetime", "Calendar Year").
    for row in (raw.get("in_network") or {}).get("maximums") or []:
        if isinstance(row, dict) and "ortho" in str(row.get("type") or "").lower():
            msg = str(row.get("message") or "").lower()
            covered = ("Lifetime" if "lifetime" in msg
                       else "Yearly" if re.search(r"calendar|benefit year|plan year|year", msg) else None)
            if covered:
                out.append({"question": "OrthoMaximumCovered", "value": covered, "level": "appointment",
                            "source": "maximums[Orthodontics].message", "label": "Ortho Maximum Covered"})
            break
    return out
