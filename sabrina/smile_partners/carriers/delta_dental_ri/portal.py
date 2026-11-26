"""Map the DD RI extension JSON to Sabrina's field and procedure values."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .rules import coordination_of_benefits, ddri_export, network_status, oon_benefits
from .vocabulary import _blank


_BENEFIT_SERVICES_BY_CODE = {
    "D0120": ("oral exam",),
    "D0140": ("oral exam",),
    "D0150": ("oral exam",),
    "D0180": ("oral exam",),
    "D0210": ("complete x-ray series or panoramic film",),
    "D0220": ("single x-rays",),
    "D0230": ("single x-rays",),
    "D0240": ("single x-rays",),
    "D0272": ("bitewing x-rays",),
    "D0274": ("bitewing x-rays",),
    "D0277": ("bitewing x-rays",),
    "D0330": ("complete x-ray series or panoramic film",),
    "D1110": ("cleaning",),
    "D1120": ("cleaning",),
    "D1206": ("fluoride treatment",),
    "D1208": ("fluoride treatment",),
    "D1351": ("sealants",),
    "D1510": ("space maintainers",),
    "D1516": ("space maintainers",),
    "D9110": ("palliative treatment (minor procedures necessary to relieve acute pain)",),
    "D9310": ("consultation",),
    "D4341": ("root planing and scaling",),
    "D4342": ("root planing and scaling",),
    "D4346": ("gingivectomies",),
    "D9243": (
        "general anesthesia or intravenous (i v) sedation for certain complex surgical procedures",
    ),
    **{
        code: ("amalgam (silver) fillings and composite (white) fillings",)
        for code in (
            "D2140", "D2150", "D2160", "D2161", "D2330", "D2331",
            "D2332", "D2335", "D2391", "D2392", "D2393", "D2394",
        )
    },
 
    **{
         code: (
          "crowns over natural teeth, build ups, posts and cores",
          "crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
              )
    for code in (
        "D2620", "D2642", "D2740", "D2750", "D2751", "D2791",
        "D2950", "D2952", "D2954",
    )
},

    "D6010": ("surgical placement of endosteal implant and abutment",),
    "D6057": ("surgical placement of endosteal implant and abutment",),
    "D2920": ("recementing crowns or bridges",),
    "D2929": ("recementing crowns or bridges",),
    "D2980": ("recementing crowns or bridges",),
    **{
        code: ("root canal therapy on permanent teeth",)
        for code in (
            "D3310", "D3320", "D3330", "D3331", "D3332",
            "D3346", "D3347", "D3348",
        )
    },
    "D4249": ("crown lengthening",),
    "D4260": ("osseous (bone) surgery",),
    "D4261": ("osseous (bone) surgery",),
    **{
        code: ("guided tissue regeneration and bone replacement graft",)
        for code in ("D4263", "D4264", "D4266", "D4267")
    },
    **{
        code: ("soft tissue grafts",)
        for code in ("D4273", "D4274", "D4275", "D4277")
    },
    "D4910": ("periodontal maintenance following active therapy",),
    **{
        code: ("partial and complete dentures",)
        for code in ("D5110", "D5120", "D5211", "D5212", "D5213", "D5225", "D5226")
    },
    "D5510": ("repairs to existing partial or complete dentures",),
    "D5511": ("repairs to existing partial or complete dentures",),
    **{
        code: ("rebasing or relining of partial or complete dentures",)
        for code in ("D5730", "D5731", "D5750", "D5751")
    },
    "D6065": ("bridges and crowns over implants",),
    "D6750": ("bridges and crowns over implants",),
    "D9944": ("occlusal guards",),
    "D9945": ("occlusal guards",),
    "D9946": ("occlusal guards",),
}

_FREQUENCY_COUNTS = {
    "once": 1, "one": 1, "twice": 2, "two": 2, "thrice": 3,
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
}
_NO_FREQUENCY_CODES = {"D9110", "D9310", "D2160", "D2391", "D4355", "D6058"}
_UNAVAILABLE_FREQUENCY_CODES = {"D4355", "D6058"}
_LOOKUP_UNAVAILABLE_UNCOVERED_CODES = {"D4381", "D5899", "D9230"}


def _normalized(raw: dict) -> dict:
    from ...portals.delta_dental_ri import _normalize_ddri_portal
    return _normalize_ddri_portal(raw)


def _plan(raw: dict) -> dict:
    return _normalized(raw).get("plan_details") or {}


def _patient(raw: dict) -> dict:
    return _normalized(raw).get("patient") or {}


def _procedures(raw: dict) -> list[dict]:
    coverage = _normalized(raw).get("benefit_coverage") or {}
    procedures = coverage.get("procedures") or []
    return [p for p in procedures if isinstance(p, dict)]


def _procedure(raw: dict, code: str) -> dict | None:
    target = str(code).upper()
    return next(
        (p for p in _procedures(raw)
         if str(p.get("procedure_code") or "").upper() == target),
        None,
    )


def _financial_entry(raw: dict, collection: str, *terms: str) -> dict | None:
    financials = _normalized(raw).get("financials") or {}
    for entry in financials.get(collection) or []:
        if not isinstance(entry, dict):
            continue
        category = str(entry.get("category") or "").lower()
        if all(term.lower() in category for term in terms):
            return entry
    return None


def _family_deductible_default(raw: dict):
    individual = _value(_financial_entry(raw, "deductibles", "individual"), "total")
    if individual is None:
        return None
    amount = re.sub(r"[$,\s]", "", str(individual))
    try:
        return f"{Decimal(amount) * 3:.2f}"
    except InvalidOperation:
        return None


def _family_deductible_derived(raw: dict) -> bool:
    """
    Whether the family deductible is this audit's 3x-individual figure rather
    than one the portal states: the individual amount is stated and the family
    one is missing or zero.

    The extension used to write the derived row into the export itself; it now
    exports only what the page shows (DCA's plan matcher reads the same file),
    so the rule lives here, in the Smile Partners DD RI audit only.
    """
    family = _value(_financial_entry(raw, "deductibles", "family"), "total")
    individual = _value(_financial_entry(raw, "deductibles", "individual"), "total")
    if individual is None:
        return False
    try:
        family_amount = Decimal(re.sub(r"[$,\s]", "", str(family))) if family is not None else Decimal(0)
    except InvalidOperation:
        return False
    return family_amount == 0


def _family_deductible_total(raw: dict):
    if _family_deductible_derived(raw):
        return _family_deductible_default(raw)
    return _value(_financial_entry(raw, "deductibles", "family"), "total")


def _family_deductible_paid(raw: dict):
    """Met toward the family deductible; a derived one mirrors the individual's met."""
    collection = "individual" if _family_deductible_derived(raw) else "family"
    return _value(_financial_entry(raw, "deductibles", collection), "used") or "0"


def _value(obj: dict | None, key: str):
    if not isinstance(obj, dict):
        return None
    value = obj.get(key)
    return None if _blank(value) else value


def _frequency_display(value) -> str | None:
    if value is not None and str(value).strip().lower() == "none":
        return "No Frequency"
    if _blank(value):
        return None
    source = re.sub(r"\s+", " ", str(value)).strip()
    if source.lower() in {
        "as required", "frequency not available", "no frequency",
        "no limitation", "no limitations", "unlimited",
    }:
        return "No Frequency"
    if source.upper() in {"NC", "N/C"} or source.lower() in {"not covered", "not a covered benefit"}:
     return "Not Covered"

    count_pattern = r"(once|one|twice|two|thrice|three|four|five|six|seven|eight|nine|ten|\d+)"
    lifetime = re.search(
        rf"\b{count_pattern}\b.*?\blifetime\b",
        source,
        re.IGNORECASE,
    )
    if lifetime:
        token = lifetime.group(1).lower()
        count = int(token) if token.isdigit() else _FREQUENCY_COUNTS[token]
        return f"{count}XLifetime"

    interval = re.search(
        rf"\b{count_pattern}\b(?:\s+(?:times?|sets?|procedures?))?"
        r"\s+(?:in|per|every)\s+(?:(?:site|quadrant|tooth|arch)\s+)?"
        r"(?:(?:every)\s+)?(?:(?:calendar|contract|plan|benefit|policy)\s+)?"
        r"(?:(\d+)\s*)?(years?|months?|weeks?|days?)\b",
        source,
        re.IGNORECASE,
    )
    if not interval:
        return source

    token = interval.group(1).lower()
    count = int(token) if token.isdigit() else _FREQUENCY_COUNTS[token]
    span = int(interval.group(2) or 1)
    unit = interval.group(3).lower().rstrip("s")
    display_unit = {"year": "Year", "month": "Months", "week": "Weeks", "day": "Days"}[unit]
    return f"{count}X{span}{display_unit}"


def _frequency_text_for_code(code: str, value) -> str:
    source = re.sub(r"\s+", " ", str(value or "")).strip()
    if code == "D1510":
        match = re.search(r"\bUnilateral\b.*?(?=\bBilateral\b|$)", source, re.IGNORECASE)
        if match:
            return match.group(0)
    elif code == "D1516":
        match = re.search(r"\bBilateral\b.*$", source, re.IGNORECASE)
        if match:
            return match.group(0)
    return source


def _normalized_benefit_label(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _benefit_service(raw: dict, code: str) -> dict | None:
    labels = _BENEFIT_SERVICES_BY_CODE.get(str(code).upper())
    if not labels:
        return None
    expected = {_normalized_benefit_label(label) for label in labels}
    matches = [
        service
        for category in (ddri_export(raw).get("benefit_categories") or [])
        if isinstance(category, dict)
        for service in (category.get("services") or [])
        if isinstance(service, dict)
        and _normalized_benefit_label(service.get("procedure")) in expected
    ]
    return matches[0] if len(matches) == 1 else None


def _age_from_limit_text(value) -> str | None:
    if _blank(value):
        return None
    match = re.search(
        r"\b(?:(?:for\s+)?children\s+)?(?:under|through|to)\s+(?:the\s+)?(?:age\s+(?:of\s+)?)?(\d{1,3})\b",
        str(value),
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _calendar_start(raw: dict) -> str | None:
    plan = _plan(raw)
    explicit = _value(plan, "plan_year_start")
    if explicit:
        return str(explicit)
    calendar = str(plan.get("calendar_year") or "")
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/\d{4}\b", calendar)
    if match:
        month = int(match.group(1))
        if 1 <= month <= 12:
            import calendar as calendar_module
            return calendar_module.month_name[month]
    return None


def _history_value(procedure: dict | None):
    if not procedure:
        return None
    history = procedure.get("history")
    if not isinstance(history, list):
        return _value(procedure, "history")
    dates = [
        str(row.get("service_date")).strip()
        for row in history
        if isinstance(row, dict) and not _blank(row.get("service_date"))
    ]
    return ", ".join(dict.fromkeys(dates)) if dates else "NH"


def _waiting_period(raw: dict) -> str | None:
    procedures = _procedures(raw)
    values = [
        str(p.get("waiting_period") or "").strip()
        for p in procedures
        if not _blank(p.get("waiting_period"))
    ]
    if not values:
        return _value(_plan(raw), "waiting_period")
    return "Yes" if any(v.lower() not in {"none", "no", "0", "n/a", "na"} for v in values) else "No"


def _deductible_applies(raw: dict, category_term: str) -> str | None:
    plan_value = _value(_plan(raw), f"deductible_applies_to_{category_term}")
    if plan_value:
        return str(plan_value)
    categories = ddri_export(raw).get("benefit_categories") or []
    answers = set()
    for category in categories:
        if not isinstance(category, dict) or category_term not in str(category.get("category") or "").lower():
            continue
        for service in category.get("services") or []:
            if isinstance(service, dict) and not _blank(service.get("deductible_applies")):
                answers.add(str(service["deductible_applies"]))
    if len(answers) == 1:
        return answers.pop()
    if answers:
        return "Varies"
    return None


def _procedure_percentage(raw: dict, codes: tuple[str, ...]) -> str | None:
    for code in codes:
        if code.upper() in {"D4346", "D9243"}:
            service = _benefit_service(raw, code)
            table_percentage = _value(service, "covered_at")
            if table_percentage:
                return str(table_percentage)
        procedure = _procedure(raw, code)
        if not procedure:
            continue
        status = str(procedure.get("coverage_status") or "").strip().lower()
        percentage = _value(procedure, "coverage_percentage")
        if percentage:
            return str(percentage)
        if "not covered" in status or (
            code.upper() in _LOOKUP_UNAVAILABLE_UNCOVERED_CODES
            and status == "lookup unavailable"
        ):
            return "0%"
    return None


def _is_not_covered(procedure: dict | None) -> bool:
    if not procedure:
        return False
    status = str(procedure.get("coverage_status") or "").strip().casefold()
    return status in {"not covered", "not-covered"}

def _is_covered(procedure: dict | None) -> bool:
    return str((procedure or {}).get("coverage_status") or "").strip().casefold() == "covered"
def _procedure_field(raw: dict, field: str, codes: tuple[str, ...]):
    field_aliases = {
        "frequency_limit": "frequency",
        "late_date_of_service": "history",
    }
    ddri_field = field_aliases.get(field, field)
    if not codes:
        return None

    code = codes[0].upper()
    procedure = _procedure(raw, code)
    if ddri_field == "frequency":
        if code in _UNAVAILABLE_FREQUENCY_CODES:
            return None
        service = _benefit_service(raw, code)
        if code in {"D1510", "D1516"} and service:
            return _frequency_display(
                _frequency_text_for_code(code, service.get("frequency_limitations"))
            )
        status = str(_value(procedure, "coverage_status") or "").strip().casefold()
        if (status in {"not covered", "not-covered", "lookup unavailable"}
                and str(_value(procedure, "frequency") or "").strip().upper() in {"NC", "N/C"}):
            return "NC"
        if procedure and _value(procedure, "frequency_source"):
            details = _value(procedure, "frequency_details")
            if details:
                frequency = _frequency_display(_frequency_text_for_code(code, details))
                if frequency:
                    return frequency
            frequency = _frequency_display(_value(procedure, "frequency"))
            if frequency:
                return frequency
        if not service:
            return "No Frequency" if code in _NO_FREQUENCY_CODES else None
        frequency = _frequency_display(service.get("frequency_limitations"))
        if frequency or code not in _NO_FREQUENCY_CODES:
            return frequency
        return "No Frequency"

    if ddri_field == "age_limit":
        if procedure and _value(procedure, "frequency_source"):
            value = _value(procedure, "age_limit")
            if value:
                return value
        service = _benefit_service(raw, code)
        age = _age_from_limit_text(service.get("frequency_limitations")) if service else None
        return age or ("99" if code == "D1510" else None)

    if ddri_field == "history":
        history = _history_value(procedure)
        if code == "D0330" and history in {None, "NH"}:
            return _history_value(_procedure(raw, "D0210"))
        return history
    if not procedure:
        return None
    return _value(procedure, ddri_field)


def _field_value(field: dict, raw: dict):
    source = field.get("portal")
    if source is None:
        return None

    if isinstance(source, tuple) and source:
        if source[0] == "code":
            return _procedure_percentage(raw, tuple(source[1:]))
        if source[0] == "codefield":
            value = _procedure_field(raw, source[1], tuple(source[2:]))
            if (value is None and source[1] in {"frequency_limit", "frequency"}
                    and source[2].upper() in _NO_FREQUENCY_CODES
                    and _is_covered(_procedure(raw, source[2]))):
                return "No Frequency"
            return value

    plan = _plan(raw)
    patient = _patient(raw)
    if source == "_in_network":
        return network_status(raw)
    if source == "_oon_benefits":
        return oon_benefits(raw)
    if source == "_cob":
        return coordination_of_benefits(raw)
    if source == "_eff_date":
        return _value(plan, "effective_date")
    if source == "_yearly_max_paid":
        return _value(_financial_entry(raw, "maximums", "annual", "maximum"), "used")
    if source == "_ortho_max":
        return _value(_financial_entry(raw, "maximums", "orthodont"), "total")
    if source == "_ortho_used":
        return _value(_financial_entry(raw, "maximums", "orthodont"), "used")
    if source in {"_ortho_ded", "_ortho_ded_met"}:
        key = "orthodontic_deductible_amount" if source == "_ortho_ded" else "orthodontic_deductible_met_amount"
        value = _value(plan, key)
        if value:
            return value
        entry = _financial_entry(raw, "deductibles", "orthodontic")
        entry_value = _value(entry, "total" if source == "_ortho_ded" else "used")
        return entry_value or "0"
    if source == "_prev_in_max":
        return "Yes"
    if source == "_major_paid_on":
        return _value(plan, "major_services_paid_on")
    if source == "_perio_after_srp":
        return _value(plan, "perio_maintenance_after_srp")
    if source == "_d4341_quads":
        return _value(plan, "d4341_quadrants") or "4"
    if source == "_ortho_age":
        return _value(plan, "orthodontic_age_limit") or "99"
    if source == "ins_name":
        return _value(plan, "insurance_name") or "Delta Dental of Rhode Island"
    if source == "patient_name":
        return _value(patient, "name")
    if source == "patient_dob":
        return _value(patient, "dob")
    if source == "member_id":
        return _value(patient, "member_id")
    if source == "subscriber_name":
        return _value(patient, "subscriber_name") or _value(patient, "name")
    if source == "subscriber_dob":
        explicit = _value(patient, "subscriber_dob")
        if explicit:
            return explicit
        subscriber = str(patient.get("subscriber_name") or "").strip().casefold()
        member = str(patient.get("name") or "").strip().casefold()
        relationship = str(patient.get("relationship") or "").strip().casefold()
        return _value(patient, "dob") if (
            relationship in {"self", "subscriber"} or (subscriber and subscriber == member)
        ) else None
    if source == "group_name":
        return _value(plan, "employer_group")
    if source == "group_number":
        return _value(plan, "group_number")
    if source == "ins_address":
        return _value(plan, "insurance_address")
    if source == "payor_id":
        return _value(plan, "payor_id")
    if source == "plan_year_start":
        return _calendar_start(raw)
    if source == "yearly_max":
        return _value(_financial_entry(raw, "maximums", "annual", "maximum"), "total")
    if source == "indiv_ded":
        return _value(_financial_entry(raw, "deductibles", "individual"), "total")
    if source == "indiv_ded_paid":
        return _value(_financial_entry(raw, "deductibles", "individual"), "used")
    if source == "family_ded":
        return _family_deductible_total(raw)
    if source == "family_ded_paid":
        return _family_deductible_paid(raw)
    if source == "ded_prev":
        return _deductible_applies(raw, "preventive")
    if source == "ded_diag":
        return _deductible_applies(raw, "diagnostic")
    if source == "waiting_period":
        return _waiting_period(raw)
    if source == "pct_prev":
        return _procedure_percentage(raw, ("D0120",))
    if source == "pct_basic":
        return _procedure_percentage(raw, ("D2160",))
    if source == "pct_major":
        return _procedure_percentage(raw, ("D2740",))
    if source == "missing_tooth":
        return _value(ddri_export(raw), "missing_tooth_clause")
    if source == "posterior_composite_downgrade":
        procedures = _procedures(raw)
        if any(
            str(procedure.get("procedure_code") or "").upper() in {"D2391", "D2392", "D2393", "D2394"}
            and str(procedure.get("alternate_benefit") or "").strip().lstrip("* ").casefold().startswith("yes")
            for procedure in procedures
        ):
            return "Yes"
        return _value(plan, source)
    if source == "porcelain_posterior_downgrade":
        return _value(plan, source)
    return None


def portal_value(field: dict, portal_raw: dict):
    """Resolve the DD RI value corresponding to a Sabrina field spec."""
    return _field_value(field, portal_raw)


def procedure_value(portal_raw: dict, code: str, field: str):
    """Public procedure lookup for tests and diagnostics."""
    return _procedure_field(portal_raw, field, (code,))


# ── Sabrina Fill Form prefill (sabrina/prefill.py) ──────────────────────────
# The prefill reads a carrier through _portal_breakdown / _portal_normalized /
# _portal_value, the other folders' interface. DD RI resolves every field
# straight off the export (portal_value), so these hand the prefill that same
# resolver: the Fill Form gets exactly the values the audit compares.

def _portal_breakdown(portal_raw: dict) -> dict:
    """No shared breakdown: DD RI answers each field from the export itself."""
    return {}


def _portal_normalized(portal_raw: dict) -> dict:
    """The export as uploaded; `portal_value` translates it where it needs to."""
    return portal_raw or {}


def _portal_value(field: dict, bd: dict, portal_raw: dict, sab_raw=None):
    """One spec'd field's value, as the audit reads it."""
    return _field_value(field, portal_raw)
