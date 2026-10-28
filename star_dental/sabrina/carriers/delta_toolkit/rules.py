"""
The Delta Dental Office Toolkit's own rules.

Everything here reads something only the Toolkit export, or the Delta
printout attached to a Sabrina sheet, states. `portal.py` and `audit.py`
call these; the generic field readers stay there. RULES.md lists the rules.
"""

from __future__ import annotations

import re
from .vocabulary import _blank, _norm_id, _norm_name, _norm_network, _num_date


def _toolkit_eligibility(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Map Toolkit selected-member eligibility to the sheet's yes/no form."""
    if not isinstance(portal_raw, dict) or not portal_raw.get("_toolkit"):
        return None
    patient = ((portal_raw.get("metlife_data") or {}).get("patient") or {})
    raw = str(patient.get("eligibility") or "").strip().lower()
    if raw in {"active", "eligible", "yes", "y"}:
        return "Yes"
    if raw in {"inactive", "terminated", "ineligible", "no", "n"}:
        return "No"
    return None


def _toolkit_meta_value(portal_raw: dict, key: str) -> str | None:
    if not isinstance(portal_raw, dict) or not portal_raw.get("_toolkit"):
        return None
    meta = portal_raw.get("_toolkit_meta")
    if not isinstance(meta, dict):
        return None
    value = meta.get(key)
    return None if _blank(value) else str(value)


def _toolkit_major_payment_timing(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    return _toolkit_meta_value(portal_raw, "major_payment_timing")


def _toolkit_ortho_max_type(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    return _toolkit_meta_value(portal_raw, "ortho_max_type")


def _toolkit_ortho_payment_timing(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    return _toolkit_meta_value(portal_raw, "ortho_payment_timing")


def _toolkit_raw_section(portal_raw: dict, *path: str):
    if not isinstance(portal_raw, dict) or not portal_raw.get("_toolkit"):
        return None
    node = portal_raw.get("_raw_export")
    for step in path:
        if not isinstance(node, dict):
            return None
        node = node.get(step)
    return node


def _toolkit_insurance_phone(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Claims/inquiry phone as the Toolkit states it; None when the field is null."""
    value = _toolkit_raw_section(
        portal_raw, "more_information", "claim_and_inquiry_mailing_addresses", "phoneNumber")
    if isinstance(value, (dict, list)) or _blank(value):
        return None
    return str(value).strip()


def _toolkit_dependent_age_limit(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Dependent orthodontic age cap from the Toolkit's orthodontic config.

    The Sabrina field is in the Ortho section. `age_limitations.childMaxAgeLimit`
    is the general plan/dependent termination age (often 26), not the
    orthodontic dependent age cap that this row asks to compare.
    """
    configs = _toolkit_raw_section(portal_raw, "ortho_information", "orthoAgeLimitConfig")
    if not isinstance(configs, list):
        return None
    for config in configs:
        if not isinstance(config, dict):
            continue
        networks = {str(x).strip().casefold() for x in (config.get("networks") or [])}
        selected = str((portal_raw.get("_toolkit_meta") or {}).get("selected_network") or "").strip().casefold()
        if networks and selected and selected not in networks:
            continue
        value = config.get("minorMaxAge")
        if value is None:
            value = config.get("dependentMaxAge")
        text = str(value or "").strip()
        if re.fullmatch(r"\d{1,3}", text):
            return text
    return None


def _toolkit_subscriber_age_limit(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Subscriber-specific orthodontic age ceiling from the selected Toolkit network."""
    configs = _toolkit_raw_section(portal_raw, "ortho_information", "orthoAgeLimitConfig")
    if not isinstance(configs, list):
        return None
    selected = str((portal_raw.get("_toolkit_meta") or {}).get("selected_network") or "").strip().casefold()
    for config in configs:
        if not isinstance(config, dict):
            continue
        networks = {str(x).strip().casefold() for x in (config.get("networks") or [])}
        if networks and selected and selected not in networks:
            continue
        value = config.get("subscriberMaxAge")
        if value is None:
            continue
        text = str(value).strip()
        if re.fullmatch(r"\d{1,3}", text):
            return text
    return None


_SRP_SENTENCE_RE = re.compile(
    r"\bD4341\b|scaling\s+and\s+root\s+plan(?:ing|ning)|root\s+plan(?:ing|ning)\s+and\s+scaling",
    re.IGNORECASE,
)


def _strings_in(node):
    stack = [node]
    index = 0
    while index < len(stack):
        item = stack[index]
        index += 1
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _toolkit_srp_quads_per_day(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Extract an explicit per-day quadrant cap from D4341's own Toolkit record.

    A frequency such as "once in 24 months per area" is not a per-day cap and
    must not be reinterpreted as one. Return a value only when D4341's source
    limitation explicitly states a same-day/day quadrant count.
    """
    raw_result = None
    results = _toolkit_raw_section(portal_raw, "coverages", "procedure_code_search", "results")
    if isinstance(results, list):
        raw_result = next((
            row for row in results
            if isinstance(row, dict) and str(row.get("procedureCode") or "").upper() == "D4341"
        ), None)

    sentences: list[str] = []
    if isinstance(raw_result, dict):
        for item in raw_result.get("limitations") or []:
            if not isinstance(item, dict):
                continue
            sentences.extend(str(s) for s in (item.get("exclusionsAndLimitations") or []) if s)
    proc = (bd.get("procs") or {}).get("D4341") or {}
    for sentence in proc.get("toolkit_source_limitations") or []:
        if sentence and sentence not in sentences:
            sentences.append(str(sentence))
    export = portal_raw.get("_raw_export") if isinstance(portal_raw, dict) else None
    for text in _strings_in(export):
        for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)):
            if _SRP_SENTENCE_RE.search(sentence) and sentence not in sentences:
                sentences.append(sentence)

    word_counts = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    caps: set[str] = set()
    for sentence in sentences:
        low = sentence.casefold()
        if not re.search(r"\bquadrants?\b", low):
            continue
        if not re.search(r"same\s+date|per\s+day|per\s+date|same\s+day|date\s+of\s+service", low):
            continue
        match = re.search(
            r"(?:limited\s+to|maximum(?:\s+of)?|no\s+more\s+than|up\s+to)\s+"
            r"(one|two|three|four|five|\d+)\s+quadrants?\b",
            low,
        )
        if not match:
            continue
        raw_count = match.group(1)
        count = int(raw_count) if raw_count.isdigit() else word_counts.get(raw_count)
        if count is not None:
            caps.add(str(count))
    return next(iter(caps)) if len(caps) == 1 else None


_POSTERIOR_CROWNS = r"\bposterior\s+(?:porcelain\s+or\s+resin|porcelain|resin)\s+crowns?\s+are\s+"
_POSTERIOR_CROWNS_NOT_COVERED_RE = re.compile(
    _POSTERIOR_CROWNS + r"not\s+(?:a\s+)?covered(?:\s+(?:services?|benefits?))?\b", re.IGNORECASE)
_POSTERIOR_CROWNS_COVERED_RE = re.compile(
    _POSTERIOR_CROWNS + r"covered\s+(?:services?|benefits?)\b", re.IGNORECASE)


def _toolkit_posterior_crown_downgrade(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    sentences: list[str] = []
    records = _toolkit_raw_section(portal_raw, "exclusions_and_limitations", "records")
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        for sentence in record.get("exclusionsAndLimitations") or []:
            text = str(sentence or "").strip()
            if text and text not in sentences:
                sentences.append(text)
    for proc in (bd.get("procs") or {}).values():
        if not isinstance(proc, dict):
            continue
        for sentence in proc.get("toolkit_source_limitations") or []:
            text = str(sentence or "").strip()
            if text and text not in sentences:
                sentences.append(text)
    if any(_POSTERIOR_CROWNS_NOT_COVERED_RE.search(sentence) for sentence in sentences):
        return "Yes"
    downgrade_found = any(
        re.search(r"porcelain|ceramic|veneer", sentence, re.IGNORECASE)
        and re.search(r"posterior|molar|bicuspid", sentence, re.IGNORECASE)
        and re.search(r"full\s+cast|optioned|alternate|downgrad", sentence, re.IGNORECASE)
        and not re.search(r"\bare\s+covered\s+(?:services|benefits)\b", sentence, re.IGNORECASE)
        for sentence in sentences
    )
    if downgrade_found:
        return "Yes"
    if any(_POSTERIOR_CROWNS_COVERED_RE.search(sentence) for sentence in sentences):
        return "No"
    return None


def _toolkit_relationship(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """Map Toolkit relationship wording to the Sabrina sheet wording."""
    if not isinstance(portal_raw, dict) or not portal_raw.get("_toolkit"):
        return None
    patient = ((portal_raw.get("metlife_data") or {}).get("patient") or {})
    raw = str(patient.get("relationship") or "").strip()
    if not raw:
        return None
    # Sabrina uses "Self" for the subscriber/patient relationship.
    if raw.lower() == "subscriber":
        return "Self"
    return raw


def _toolkit_d0150_per_provider(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    if not isinstance(portal_raw, dict) or not portal_raw.get("_toolkit"):
        return None
    proc = (bd.get("procs") or {}).get("D0150")
    if not proc:
        return None
    from ....portals.delta_toolkit import _frequency_from_text
    for sentence in proc.get("toolkit_source_limitations") or []:
        if re.search(r"\b(?:per|same|each)\s+(?:provider|dentist|office|location|practice)\b", sentence, re.IGNORECASE):
            frequency = _frequency_from_text(sentence)
            if frequency:
                return frequency
    return "Frequency not available"


def _pdf_eligibility(text: str) -> str | None:
    m = re.search(r"Currently\s+Eligible\s*:\s*(Yes|No)\b", text or "", re.IGNORECASE)
    return m.group(1).title() if m else None


def _pdf_delta_patient_name(text: str) -> str | None:
    """
    Patient name as printed on the Delta benefit page embedded in the Sabrina PDF.

    The sheet's own Patient Name is often the short form the office knows
    ("Jane Doe"), while the Delta page carries the name on the plan
    ("Jane Marie Doe"). The Delta page labels it with a colon, which the
    sheet's own layout never does.
    """
    for m in re.finditer(r"Patient\s+Name\s*:[ \t]*([^\n]+)", text or "", re.IGNORECASE):
        name = re.split(r"\s+Client\b", m.group(1), maxsplit=1, flags=re.IGNORECASE)[0].strip()
        if name:
            return name
    return None


def _pdf_relationship(text: str) -> str | None:
    m = re.search(
        r"Relation(?:ship)?\s+to\s+Subscriber\s*:?\s*(Self|Subscriber|Spouse|Dependent|Child)\b",
        text or "",
        re.IGNORECASE,
    )
    if not m:
        m = re.search(r"Relationship\s*:\s*(Self|Subscriber|Spouse|Dependent)\b", text or "", re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1).title()
    if raw.lower() == "subscriber":
        return "Self"
    return "Dependent" if raw.lower() == "child" else raw


def _pdf_major_payment_timing(text: str) -> str | None:
    m = re.search(
        r"Are\s+Major\s+(?:Services\s+)?Paid\s+(?:on|at)\s+Prep\s+or\s+Seat\s+date\?\s*"
        r"(Prep(?:\s+Date)?|Seat(?:\s+Date)?)\b",
        text or "",
        re.IGNORECASE,
    )
    if not m:
        return None
    return "Prep Date" if m.group(1).lower().startswith("prep") else "Seat Date"


def _pdf_srp_quads_per_day(text: str) -> str | None:
    """Read an explicit same-day SRP quadrant cap from the embedded Delta PDF.

    Toolkit JSON sometimes omits this separate clinical-review rule. Use the
    embedded Delta printout only when a sentence specifically identifies
    scaling/root-planing and states a same-date/day quadrant cap.
    """
    normalized = re.sub(r"\s+", " ", text or "")
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    values: set[str] = set()
    for sentence in sentences:
        if not re.search(r"\b(?:D4341\s*[-–]\s*D4342|scaling\s+and\s+root\s+plan(?:ing|ning)|root\s+plan(?:ing|ning)\s+and\s+scaling)\b", sentence, re.IGNORECASE):
            continue
        if not re.search(r"same\s+date|same\s+day|per\s+day|per\s+date|date\s+of\s+service", sentence, re.IGNORECASE):
            continue
        match = re.search(
            r"(?:limited\s+to|maximum(?:\s+of)?|no\s+more\s+than|up\s+to)\s+"
            r"(one|two|three|four|five|\d+)\s+quadrants?\b",
            sentence,
            re.IGNORECASE,
        )
        if match:
            raw_count = match.group(1).lower()
            value = int(raw_count) if raw_count.isdigit() else words.get(raw_count)
            if value is not None:
                values.add(str(value))
    return next(iter(values)) if len(values) == 1 else None


def _pdf_ortho_coverage(text: str) -> str | None:
    m = re.search(r"Ortho\s+Coverage\s+(\d+(?:\.\d+)?%)", text or "", re.IGNORECASE)
    return m.group(1) if m else None


def _pdf_ortho_max_type(text: str) -> str | None:
    m = re.search(r"Ortho\s+Maximum\s+Covered\s+(Lifetime|Annual|Calendar Year)", text or "", re.IGNORECASE)
    return m.group(1).title() if m else None


def _pdf_ortho_payment_timing(text: str) -> str | None:
    m = re.search(r"Ortho\s+Payment\s+Timing\s*[:\-]?\s*([^\n\r]+)", text or "", re.IGNORECASE)
    if not m:
        return None
    value = m.group(1).strip()
    # In the flattened Sabrina text the blank Timing cell is immediately
    # followed by the next CDT row (for this PDF, D8090). Do not misread that
    # row as the timing value.
    if re.match(r"D\d{4}\b", value, re.IGNORECASE):
        return None
    return value or None


_OUT_OF_NETWORK = "Nonparticipating Dentist"


def _toolkit_benefit_network(fields: dict) -> str | None:
    """
    The Delta network whose benefits the sheet records.

    A sheet answering In Network "Out" is filled in for a non-participating
    office, from the Toolkit's Nonparticipating Dentist column. Any other
    answer, or none, is compared with the PPO Dentist column as before.
    """
    return _OUT_OF_NETWORK if _norm_network(fields.get("in_network")) == "OUT" else None


def _toolkit_identity_gate(sabrina_parsed: dict, portal_norm: dict) -> tuple[bool, list[str]]:
    """Validate identity/network before any Toolkit benefit comparison."""
    issues: list[str] = []
    fields = sabrina_parsed.get("fields", {})
    subscriber = portal_norm.get("patient_info") or portal_norm.get("subscriber_info") or {}

    sab_name = _norm_name(fields.get("patient_name"))
    tool_name = _norm_name(subscriber.get("name"))
    name_ok = bool(sab_name and tool_name and sab_name == tool_name)
    if not name_ok and sab_name and tool_name:
        # The sheet may hold a short form ("Jane Doe") of the name the plan
        # has on file ("Jane Marie Doe"). Accept it only when the Delta
        # benefit page inside the same PDF prints exactly the portal's name AND
        # the sheet's name is contained in it — so a different person still fails.
        delta_name = _norm_name(_pdf_delta_patient_name(sabrina_parsed.get("text", "")))
        name_ok = bool(
            delta_name
            and delta_name == tool_name
            and set(sab_name) <= set(tool_name)
        )
    if not name_ok:
        issues.append(f"patient name mismatch ({fields.get('patient_name')!r} vs {subscriber.get('name')!r})")

    sab_dob = _num_date(fields.get("patient_dob"))
    tool_dob = _num_date(subscriber.get("dob"))
    if not sab_dob or not tool_dob or sab_dob != tool_dob:
        issues.append(f"DOB mismatch ({fields.get('patient_dob')!r} vs {subscriber.get('dob')!r})")

    sab_elig = _pdf_eligibility(sabrina_parsed.get("text", ""))
    tool_elig = _toolkit_eligibility({}, portal_norm)
    if not sab_elig or not tool_elig or sab_elig.lower() != tool_elig.lower():
        issues.append(f"eligibility mismatch ({sab_elig!r} vs {tool_elig!r})")

    sab_group = _norm_id(fields.get("group_number"))
    tool_group = _norm_id(subscriber.get("group_number"))
    if not sab_group or not tool_group or sab_group != tool_group:
        issues.append(f"group/client mismatch ({fields.get('group_number')!r} vs {subscriber.get('group_number')!r})")

    tool_network = str(((portal_norm.get("metlife_data") or {}).get("plan_details") or {}).get("network") or "").strip()
    normalized_network = re.sub(r"\s+", " ", tool_network).casefold()
    if normalized_network != "ppo dentist":
        issues.append(f"Toolkit network mismatch ({tool_network!r}); expected PPO Dentist")

    return not issues, issues


def _toolkit_code_looked_up(field: dict, portal_norm: dict, failed: set) -> bool:
    src = field.get("portal")
    if not (isinstance(src, tuple) and len(src) > 1 and src[0] in ("code", "codefield")):
        return False
    code = str(src[1] if src[0] == "code" else src[2]).upper()
    if code in failed:
        return False
    from ....portals.delta_toolkit import _code_list
    requested = _toolkit_raw_section(
        portal_norm, "coverages", "procedure_code_search", "codes_requested")
    return code in set(_code_list(requested))
