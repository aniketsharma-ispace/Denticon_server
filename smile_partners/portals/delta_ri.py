"""
Delta Dental of Rhode Island — the portal export (content_DD_RI.js) translated
into the standard Portal contract the audit and the Sabrina prefill read.

The export marks itself with `ddri_data: true` and carries:

    patient          name, subscriber_name, member_id, dob, relationship
    plan_details     employer_group, group_number ("4250 - 0403"),
                     effective_date, termination_date, network_status (the
                     page's Product Name), coverage_type, plan_type
    financials       maximums / deductibles: [{category, total, used, remaining}]
    missing_tooth_clause   "Yes" / "No" / "N/A"
    dependent_age_limit    the plan's notice, as printed
    benefit_coverage.procedures
        [{procedure_code, description, coverage_status (COVERED / NOT COVERED /
          SCRAPE ERROR), coverage_percentage ("100 %"), deductible_applies,
          waiting_period, alternate_benefit, frequency (the matched benefit
          row's Frequency/Limitations), age_limit, history: [{service_date}]}]

Only what the page states is carried over: no team rules are applied here
(none were given for DD RI yet), so anything the page does not state stays
blank for the operator.
"""

from __future__ import annotations

import re
from datetime import datetime


def _clean(value) -> str:
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    return "" if text.upper() in ("N/A", "NA", "--", "-") else text


def _is_ddri_portal(raw) -> bool:
    """The DD RI export: its own `ddri_data` flag."""
    return isinstance(raw, dict) and raw.get("ddri_data") is True


# ── small readers ─────────────────────────────────────────────────────────────

def _money(value) -> str:
    """'$2,000.00' → '$2,000.00'; 'Not Covered' → '$0.00'; unstated → ''."""
    text = _clean(value)
    if not text:
        return ""
    if "not covered" in text.lower():
        return "$0.00"
    m = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)", text)
    if not m:
        return ""
    return f"${float(m.group(1).replace(',', '')):,.2f}"


def _row(rows, *keywords, exclude=()) -> dict:
    """The first financial row whose category names any keyword (and none excluded)."""
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        cat = str(row.get("category") or "").lower()
        if any(k in cat for k in keywords) and not any(x in cat for x in exclude):
            return row
    return {}


def _amounts(row: dict) -> dict:
    return {"total": _money(row.get("total")), "used": _money(row.get("used")),
            "remaining": _money(row.get("remaining"))}


def _pct(value) -> str:
    """'100 %' → '100%'."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", str(value or ""))
    return f"{float(m.group(1)):g}%" if m else ""


_AGE_RE = re.compile(r"(?:under|younger than|through|to|thru|age(?:\s+of)?)\s+(?:the\s+)?(?:age\s+(?:of\s+)?)?(\d{1,2})\b",
                     re.IGNORECASE)


def _age(value) -> str:
    """'under age 19' / 'through age 18' → '19' / '18'; anything else → ''."""
    m = _AGE_RE.search(str(value or ""))
    return m.group(1) if m else ""


def _dates_newest_first(history) -> str:
    """The procedure's latest service date; '—' for none."""
    dates = []
    for entry in history or []:
        when = _clean((entry or {}).get("service_date")) if isinstance(entry, dict) else ""
        if when and when not in dates:
            dates.append(when)

    def key(d):
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(d, fmt)
            except ValueError:
                continue
        return datetime.min

    dates.sort(key=key, reverse=True)
    # The latest visit only: DD RI's history lookup goes back years, and the
    # Fill Form's History box takes the last date of service.
    return dates[0] if dates else "—"


def _yes_no(value) -> str:
    text = _clean(value).lower()
    return "Yes" if text.startswith("y") else "No" if text.startswith("n") else ""


def _waiting(value) -> str:
    """A procedure's waiting period as printed ('6 Months'), '' when none is stated."""
    text = _clean(value)
    if not text or text.lower() in ("none", "no", "0", "no waiting period"):
        return ""
    return text


# ── one procedure ─────────────────────────────────────────────────────────────

def _procedure(record: dict) -> dict | None:
    """One `procedures` record in the contract's shape; None for a failed lookup."""
    code = _clean(record.get("procedure_code")).upper()
    status = _clean(record.get("coverage_status")).upper()
    if not code or status == "SCRAPE ERROR" or not status:
        return None
    if status == "NOT COVERED":
        return {
            "procedure_code": code,
            "description": _clean(record.get("description")),
            "benefit_level": "0%",
            "frequency_limit": "NOT COVERED",
            "age_limit": "",
            "late_date_of_service": _dates_newest_first(record.get("history")),
            "number_of_quads": "",
            "_ddri_deductible_applies": "",
            "_ddri_waiting_period": "",
            "_ddri_alternate_benefit": "",
        }
    # "Once per quadrant every 24 months": the unit (quadrant, tooth, arch) is
    # the Quads / tooth columns' business; the frequency is the count and span.
    frequency = re.sub(r"\s+per\s+(?:quadrant|quad|tooth|arch|site|area)\b", "",
                       _clean(record.get("frequency")), flags=re.IGNORECASE).strip()
    return {
        "procedure_code": code,
        "description": _clean(record.get("description")),
        "benefit_level": _pct(record.get("coverage_percentage")),
        "frequency_limit": frequency,
        # The scraper keeps only the age clause of the frequency text
        # ("under age 19"); the age itself is the number.
        "age_limit": _age(record.get("age_limit")) or _age(frequency),
        "late_date_of_service": _dates_newest_first(record.get("history")),
        "number_of_quads": "",
        "_ddri_deductible_applies": _yes_no(record.get("deductible_applies")),
        "_ddri_waiting_period": _waiting(record.get("waiting_period")),
        "_ddri_alternate_benefit": _clean(record.get("alternate_benefit")),
    }


# ── translation ───────────────────────────────────────────────────────────────

def _normalize_ddri_portal(raw: dict) -> dict:
    """Translate the DD RI export into the standard Portal contract."""
    patient = raw.get("patient") if isinstance(raw.get("patient"), dict) else {}
    plan = raw.get("plan_details") if isinstance(raw.get("plan_details"), dict) else {}
    fin = raw.get("financials") if isinstance(raw.get("financials"), dict) else {}
    maximums = fin.get("maximums") or fin.get("annual_limits") or []
    deductibles = fin.get("deductibles") or []
    ortho_rows = (fin.get("orthodontic") or []) + list(maximums)

    procedures = [p for p in (_procedure(r) for r in
                              ((raw.get("benefit_coverage") or {}).get("procedures") or [])
                              if isinstance(r, dict)) if p]
    procs = {p["procedure_code"]: p for p in procedures}
    failed = sorted(_clean(r.get("procedure_code")).upper()
                    for r in ((raw.get("benefit_coverage") or {}).get("procedures") or [])
                    if isinstance(r, dict) and _clean(r.get("coverage_status")).upper() in ("SCRAPE ERROR", ""))

    relationship = _clean(patient.get("relationship")).title()
    is_self = relationship.lower() in ("", "self", "subscriber", "member")
    annual = _amounts(_row(maximums, "annual", "maximum", exclude=("ortho",)))
    ortho = _amounts(_row(ortho_rows, "ortho"))
    ind_ded = _amounts(_row(deductibles, "individual", exclude=("ortho",)))
    fam_ded = _amounts(_row(deductibles, "family", exclude=("ortho",)))
    no_deductible = (ind_ded["total"] in ("$0.00",) and fam_ded["total"] in ("$0.00", ""))

    group_number = _clean(plan.get("group_number"))
    clause = _clean(raw.get("missing_tooth_clause"))

    # Waiting periods the page states per code (Basic: D2160/D2391, Major: D2740 —
    # the codes the Fill Form's waiting-period rows are read from).
    waiting_codes = {code: p["_ddri_waiting_period"] for code, p in procs.items()
                     if p.get("_ddri_waiting_period")}

    normalized = {
        "_skip_llm": True,
        "_source_insurer": "delta dental ri",
        "carrier_information": {
            "name": "Delta Dental of Rhode Island",
            # The page states neither; left for the operator.
            "address": "",
            "payer_id": "",
        },
        "subscriber_info": {
            "name": _clean(patient.get("subscriber_name")),
            "dob": _clean(patient.get("dob")) if is_self else "—",
            "relation": relationship or "Self",
        },
        "metlife_data": {
            "patient": {
                "name": _clean(patient.get("name")),
                "dob": _clean(patient.get("dob")),
                "relationship": "Self" if is_self else relationship,
            },
            "plan_details": {
                "start_date": _clean(plan.get("effective_date")),
                "end_date": _clean(plan.get("termination_date")),
                "subscriber_id": _clean(patient.get("member_id")),
                "employer_group": _clean(plan.get("employer_group")),
                "group_number": group_number,
                "network": _clean(plan.get("network_status")),
                "plan_type": _clean(plan.get("plan_type")) or _clean(plan.get("network_status")),
            },
            "financials": {
                "annual_max": annual,
                "deductible_ind": ind_ded,
                "deductible_fam": fam_ded,
                "ortho_lifetime": {**ortho, "category": "Orthodontics"},
            },
            "provider_info": {"provider_name": "", "provider_network_status": ""},
            "covered_services": [],
            "provisions": [],
        },
        "benefit_coverage": {"procedures": procedures},
    }
    normalized["_ddri_meta"] = {
        "network_status": _clean(plan.get("network_status")),
        "coverage_type": _clean(plan.get("coverage_type")),
        "missing_tooth": clause if clause in ("Yes", "No") else "",
        "dependent_age_limit": _clean(raw.get("dependent_age_limit")),
        "waiting_period": "Yes" if waiting_codes else "",
        "waiting_codes": waiting_codes,
        # Whether the deductible is taken out of preventive (the cleaning) and
        # diagnostic (the exam) work, as the codes state it.
        "ded_prev": "No" if no_deductible else (procs.get("D1110") or {}).get("_ddri_deductible_applies", ""),
        "ded_diag": "No" if no_deductible else (procs.get("D0120") or {}).get("_ddri_deductible_applies", ""),
        "ortho_max_present": bool(ortho["total"]),
        "deductibles_listed": bool(ind_ded["total"]),
        "ortho_covered": ("Yes" if ortho["total"] not in ("", "$0.00")
                          else "No" if ortho["total"] == "$0.00"
                          or (procs.get("D8080") or {}).get("frequency_limit") == "NOT COVERED"
                          else ""),
        "failed_codes": failed,
    }
    return normalized
