"""
MetLife's part of the Sabrina Fill Form prefill.

sabrina/smile_partners/prefill.py does the common work (the audit's readers,
the grid, formats) and calls these for what only MetLife's export can answer.
Change MetLife here; other carriers have their own carriers/<carrier>/prefill.py.

Written from the BPO team's QA of MetLife fills (AI Automation QA.xlsx, 11/25).
"""

from __future__ import annotations

import re

# "1 TIME IN 60 MONTHS", "2 TIMES IN 1 CALENDAR YEAR", "1 TIME IN 5 FISCAL YEARS"
_LIMIT_RE = re.compile(
    r"^\s*(?:(\d+)|(once|twice|one|two|three|four))\s*(?:times?)?\s*(?:in|per|every)\s*(\d*)\s*"
    r"(?:calendar\s*|fiscal\s*|contract\s*|plan\s*|benefit\s*|consecutive\s*)*(year|month)s?\b",
    re.IGNORECASE)
_COUNT_WORDS = {"once": 1, "one": 1, "twice": 2, "two": 2, "three": 3, "four": 4}


def form_frequency(value) -> str | None:
    """
    A grid Frequency in the unit MetLife states it in, as Sabrina writes it:
    "1 TIME IN 60 MONTHS" → "1X60Months", "2 TIMES IN 1 CALENDAR YEAR" →
    "2X1Year", "1 TIME IN 5 FISCAL YEARS" → "1X5Years".

    The shared reading turns 60 months into 1X5Year; the BPO team fills what
    the website says (QA 11/25: D0210, D0330, D1206, D1351, D2160, D4341, …).
    The panel still picks the years option when a form has no months one.
    None for Not Covered, No Limitations, Once per Lifetime and anything else,
    which the shared reading handles.
    """
    from .vocabulary import _select_frequency_clause
    clause = _select_frequency_clause(str(value or ""), None)[0]
    m = _LIMIT_RE.match(clause)
    if not m:
        return None
    count = int(m.group(1)) if m.group(1) else _COUNT_WORDS[m.group(2).lower()]
    span = int(m.group(3) or 1)
    unit = m.group(4).lower()
    if unit == "month" and span >= 999:
        return f"{count}XLifetime"
    return f"{count}X{span}{'Year' if unit == 'year' else 'Month'}{'s' if span != 1 else ''}"


# Plan Overview › patient Relationship → the form's Relation to Insured.
_RELATION = (
    (r"subscriber|self|employee|member", "Self"),
    (r"spouse|domestic\s+partner", "Spouse"),
    (r"child|son|daughter|dependent|student", "Dependent"),
)

# Plan Provisions › Ortho payment method ("Monthly Repetitive", "End of quarter")
# → the form's Ortho Payment Timing option. Semi-annual before annual.
_ORTHO_TIMING = (
    (r"month", "Monthly"),
    (r"quarter", "Quarterly"),
    (r"semi[\s-]?(?:annual|year)", "Semi Yearly"),
    (r"annual|year", "Yearly"),
    (r"one\s*time|lump", "One Time"),
)


def _first(table, text):
    return next((value for pattern, value in table if re.search(pattern, text, re.IGNORECASE)), None)


def form_only(view: dict, values: dict) -> list[dict]:
    """Relation to Insured, Plan Type, Calendar/Fiscal Year, Ortho Maximum Covered, Ortho Payment Timing."""
    from .portal import _ortho_is_covered
    from ...prefill import _money

    raw = values.get("_raw") or {}
    ml = raw.get("metlife_data") or raw
    out = []

    def add(name, value, level, source, label):
        if value:
            out.append({"name": name, "value": value, "level": level,
                        "source": source, "label": label})

    # Relation to Insured — the patient's Relationship ("Subscriber", "Spouse", …).
    relation = _first(_RELATION, str((ml.get("patient") or {}).get("relationship") or ""))
    add("demographic.relationToInsured", relation, "appointment",
        "patient.relationship", "Relation to Insured")

    # Plan Type — MetLife's PDP network (Preferred Dentist Program, "PDP PLUS")
    # is its PPO. Any other network is left to the user.
    network = str((ml.get("plan_details") or {}).get("network") or "")
    if re.search(r"\bPDP\b|\bPPO\b", network, re.IGNORECASE):
        add("insuranceDetails.planType", "PPO", "plan", "plan_details.network", "Plan Type")

    provisions = {str(p.get("rule") or "").strip().lower(): str(p.get("value") or "")
                  for p in (ml.get("provisions") or []) if isinstance(p, dict)}

    # Calendar / Fiscal — Plan Provisions › Benefit Period: "CALENDAR YEAR Start
    # Date: …" or "FISCAL YEAR Start Date: 07/01/2026 …".
    period = provisions.get("benefit period", "").lower()
    cal = ("Calendar" if "calendar" in period
           else "Fiscal" if re.search(r"fiscal|plan\s+year|benefit\s+year|contract\s+year", period)
           else None)
    add("insuranceDetails.calendarorfiscal", cal, "plan",
        "provisions.Benefit Period", "Calendar/Fiscal Year")

    if _ortho_is_covered(raw) is True:
        # Ortho Maximum Covered — MetLife's orthodontic maximum is its Lifetime card.
        ortho_max = _money(values.get("ortho_max") or "")
        if ortho_max is not None and float(ortho_max) > 0:
            add("benefitsInfo.orthoMaximumCovered", "Lifetime", "appointment",
                "financials.ortho_lifetime", "Ortho Maximum Covered")
        # Ortho Payment Timing — a question row in the benefits grid.
        timing = _first(_ORTHO_TIMING, provisions.get("ortho payment method", ""))
        if timing:
            out.append({"question": "OrthoPaymentTiming", "value": timing, "level": "plan",
                        "source": "provisions.Ortho payment method",
                        "label": "Ortho Payment Timing"})
    return out
