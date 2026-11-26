"""
Delta Dental Office Toolkit's part of the Sabrina Fill Form prefill.

sabrina/smile_partners/prefill.py does the common work and calls these.
Change the Toolkit here; other carriers have their own carriers/<carrier>/prefill.py.
"""

import re

# Out-of-network names the Toolkit uses: "Nonparticipating Dentist", and on
# Medicare Advantage plans "Non-PPO Dentist" (extension 1.58).
_OUT_OF_NETWORK_RE = re.compile(r"\bnon[\s-]?(?:participating|par|ppo)\b", re.IGNORECASE)


def scrape_network(portal_raw: dict) -> str | None:
    """
    The network the crawl ran under. Since extension 1.53 the pop-up picks PPO,
    Premier or Non-participating Dentist before the crawl, and the export holds
    that network's benefits only (`selected_network`): PPO and Premier Dentist
    are "In", Nonparticipating Dentist is "Out". None for an older export that
    holds every network, which the user's IN OR OON pick reads as before.
    """
    from .portal import _portal_normalized
    meta = _portal_normalized(portal_raw).get("_toolkit_meta") or {}
    network = str(meta.get("export_network") or "").strip()
    if not network:
        return None
    if _OUT_OF_NETWORK_RE.search(network):
        return "Out"
    if re.search(r"\b(?:ppo|premier)\b", network, re.IGNORECASE):
        return "In"
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  FILL FORM CELLS THE SHEET DOESN'T PRINT (11/25 review)
# ══════════════════════════════════════════════════════════════════════════════
#
# Read exactly like the audit's spec rows (same readers, same rules), but only
# filled: the Sabrina sheet has no such cell, so the audit never sees them.

_GRID = "Coverage by CDT Code"


def _cell(key, row_key, label, aspect, portal, **extra):
    return {"key": key, "label": label, "kind": {"age": "agelimit", "freq": "frequency"}[aspect],
            "section": _GRID, "portal": portal, "derived": True, "row_key": row_key,
            "aspect": aspect, **extra}


FORM_ONLY_SPEC = [
    # PREVENTIVE(D0120)% / BASIC(D2160)% / MAJOR(D2740)%: the exact code's %;
    # a Not Covered code gives 0 (RULES.md, plan-level % rows).
    {"key": "pct_prev",  "label": "Preventive (D0120)%", "kind": "pct", "section": "Insurance",
     "portal": ("code", "D0120")},
    {"key": "pct_basic", "label": "Basic (D2160)%",      "kind": "pct", "section": "Insurance",
     "portal": ("code", "D2160")},
    {"key": "pct_major", "label": "Major (D2740)%",      "kind": "pct", "section": "Insurance",
     "portal": ("code", "D2740")},
    # D4381 Arestin: on the form, not on the sheet.
    {"key": "d4381", "label": "D4381 Arestin", "kind": "pct", "section": _GRID,
     "portal": ("code", "D4381")},
    _cell("d4381__freq", "d4381", "D4381 Arestin · Frequency", "freq",
          ("codefield", "frequency_limit", "D4381")),
    # The sheet prints no Frequency for D4260 and no Age Limit for D1510; the form has both.
    _cell("d4260__freq", "d4260", "D4260 Osseous Surgery · Frequency", "freq",
          ("codefield", "frequency_limit", "D4260")),
    _cell("d1510__age", "d1510", "D1510 Space Maintainer · Age Limit", "age",
          ("codefield", "age_limit", "D1510", "D1516"), toolkit_fallback=True),
    # Ortho Coverage's Age Limit: the audit's ortho age reader (orthoAgeLimitConfig).
    _cell("ortho_coverage__age", "ortho_coverage", "Ortho Coverage · Age Limit", "age", "_ortho_age"),
]


# The Toolkit's ortho payment frequency → the form's Ortho Payment Timing option.
_ORTHO_TIMING = {
    "monthly": "Monthly", "quarterly": "Quarterly",
    "semi-annual": "Semi Yearly", "semiannual": "Semi Yearly", "semi annual": "Semi Yearly",
    "semi yearly": "Semi Yearly", "semi-yearly": "Semi Yearly",
    "annual": "Yearly", "annually": "Yearly", "yearly": "Yearly",
    "one time": "One Time", "lump sum": "One Time",
}


def form_only(view: dict, values: dict) -> list[dict]:
    """
    Plan Type, Calendar/Fiscal Year, Ortho Maximum Covered and Ortho Payment
    Timing, from the Toolkit export itself (11/25).
    """
    raw = values.get("_raw") or {}
    out = []

    def add(name, value, level, source, label):
        if value:
            out.append({"name": name, "value": value, "level": level,
                        "source": source, "label": label})

    # Plan Type — Client Benefit Information's product, e.g. "Delta Dental PPO
    # (Point-of-Service)" → PPO. Other products are left to the user.
    more = raw.get("more_information") or {}
    product = str(((more.get("client_benefit_information") or {}).get("display_fields") or {})
                  .get("product") or "")
    if re.search(r"\bPPO\b", product, re.IGNORECASE):
        add("insuranceDetails.planType", "PPO", "plan",
            "client_benefit_information.product", "Plan Type")

    # Calendar / Fiscal — Maximums and Deductibles' accumulation period:
    # "Calendar Year" is Calendar; any other year (Contract, Benefit, Plan) is Fiscal.
    period = str((raw.get("maximums_and_deductibles") or {}).get("accumulationPeriodType") or "").lower()
    cal = "Calendar" if "calendar" in period else ("Fiscal" if "year" in period else None)
    add("insuranceDetails.calendarorfiscal", cal, "plan",
        "maximums_and_deductibles.accumulationPeriodType", "Calendar/Fiscal Year")

    # Ortho Maximum Covered — the Orthodontic maximum row: lifetime → Lifetime,
    # otherwise Yearly.
    rows = (raw.get("maximums_and_deductibles") or {}).get("rows") or []
    ortho = [r for r in rows if isinstance(r, dict)
             and str(r.get("type") or "").lower() == "maximum"
             and "ortho" in str(r.get("category") or "").lower()]
    if ortho:
        lifetime = str(ortho[0].get("isLifetime")).strip().lower() == "true"
        add("benefitsInfo.orthoMaximumCovered", "Lifetime" if lifetime else "Yearly",
            "appointment", "maximums_and_deductibles.rows", "Ortho Maximum Covered")

    # Ortho Payment Timing — the ortho payment schedule's frequency, only when
    # the plan covers ortho (the schedule is printed even when it doesn't).
    covered = values.get("ortho_coverage")
    if covered and not re.search(r"not\s*covered|^0+%?$", str(covered), re.IGNORECASE):
        sched = (raw.get("ortho_information") or {}).get("orthoPaymentSchedule") or {}
        freq = str((sched.get("paymentFrequencyType") or {}).get("value") or "").strip().lower()
        timing = _ORTHO_TIMING.get(freq)
        if timing:
            out.append({"question": "OrthoPaymentTiming", "value": timing, "level": "plan",
                        "source": "ortho_information.orthoPaymentSchedule",
                        "label": "Ortho Payment Timing"})
    return out
