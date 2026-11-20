"""
Delta Dental of Rhode Island provider portal.

Recognizes the DD RI extension export and translates it into the shared
Smile Partners portal contract. Source-specific data is retained under
``_raw_export`` so carrier audits can access fields the shared contract does
not represent.
"""

from __future__ import annotations

import re
from typing import Any

from .common import _blank_present_end_date, _dollar


_BLANKS = {"", "n/a", "na", "not available", "unknown", "none", "null"}


def _is_ddri_portal(raw: Any) -> bool:
    """Whether a payload is a DD RI extension export, optionally wrapped."""
    if not isinstance(raw, dict):
        return False
    if raw.get("ddri_data") is True:
        return True
    wrapped = raw.get("portal_data")
    return isinstance(wrapped, dict) and wrapped.get("ddri_data") is True


def _raw_export(raw: dict) -> dict:
    """Unwrap only the known portal_data envelope."""
    normalized = raw.get("_raw_export")
    if raw.get("_ddri") is True and isinstance(normalized, dict):
        return normalized
    if raw.get("ddri_data") is True:
        return raw
    wrapped = raw.get("portal_data")
    return wrapped if isinstance(wrapped, dict) and wrapped.get("ddri_data") is True else {}


def _text(value) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return "" if text.lower() in _BLANKS else text


def _procedure_rows(raw: dict) -> list[dict]:
    coverage = raw.get("benefit_coverage") or {}
    rows = coverage.get("procedures") or []
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = _text(row.get("procedure_code")).upper()
        if not code:
            continue
        history = row.get("history")
        history_dates = []
        if isinstance(history, list):
            history_dates = [
                _text(item.get("service_date"))
                for item in history
                if isinstance(item, dict) and _text(item.get("service_date"))
            ]
        elif _text(history):
            history_dates = [_text(history)]

        percentage = _text(row.get("coverage_percentage"))
        status = _text(row.get("coverage_status")).upper()
        normalized.append({
            **row,
            "procedure_code": code,
            "benefit_level": percentage or ("0%" if "NOT COVERED" in status else ""),
            "frequency_limit": _text(row.get("frequency")),
            "age_limit": _text(row.get("age_limit")),
            "late_date_of_service": ", ".join(dict.fromkeys(history_dates)) or "NH",
        })
    return normalized


def _maximum(financials: dict, *terms: str) -> dict:
    for row in financials.get("maximums") or []:
        if not isinstance(row, dict):
            continue
        category = _text(row.get("category")).lower()
        if all(term in category for term in terms):
            return row
    return {}


def _deductible(financials: dict, *terms: str) -> dict:
    for row in financials.get("deductibles") or []:
        if not isinstance(row, dict):
            continue
        category = _text(row.get("category")).lower()
        if all(term in category for term in terms):
            return row
    return {}


def _normalized_categories(raw: dict) -> list[dict]:
    output = []
    for category in raw.get("benefit_categories") or []:
        if not isinstance(category, dict):
            continue
        name = _text(category.get("category"))
        services = []
        for service in category.get("services") or []:
            if not isinstance(service, dict):
                continue
            services.append({
                "name": _text(service.get("procedure")),
                "coverage": _text(service.get("covered_at")),
                "deductible_applies": _text(service.get("deductible_applies")),
                "waiting_period": _text(service.get("waiting_period")),
                "frequency": _text(service.get("frequency_limitations")),
            })
        if name:
            output.append({"category": name, "services": services})
    return output


def _normalize_ddri_portal(raw: dict) -> dict:
    """
    Translate a DD RI extension export into the shared portal contract.

    The normalization is additive: the original extension object remains
    available as ``_raw_export`` and no unavailable values are inferred.
    """
    source = _raw_export(raw)
    if not source:
        return {}

    patient = source.get("patient") or {}
    plan = source.get("plan_details") or {}
    financials = source.get("financials") or {}
    maxima = financials.get("maximums") or []
    procedures = _procedure_rows(source)

    annual_max = _maximum(financials, "annual", "maximum")
    if not annual_max:
        annual_max = _maximum(financials, "yearly", "maximum")
    ortho_max = _maximum(financials, "orthodont")
    individual_ded = _deductible(financials, "individual")
    family_ded = _deductible(financials, "family")

    normalized_patient = {
        **patient,
        "name": _text(patient.get("name")),
        "dob": _text(patient.get("dob")),
        "relationship": _text(patient.get("relationship")),
    }
    normalized_plan = {
        **plan,
        "start_date": _text(plan.get("effective_date")),
        "end_date": _blank_present_end_date(_text(plan.get("termination_date"))),
        "subscriber_id": _text(patient.get("member_id")),
        "employer_group": _text(plan.get("employer_group")),
        "group_number": _text(plan.get("group_number")),
        "network": _text(plan.get("network_status")),
        "plan_type": _text(plan.get("plan_type")) or _text(plan.get("network_status")),
    }
    normalized_financials = {
        "annual_max": {
            "total": _dollar(annual_max.get("total"), default=""),
            "used": _dollar(annual_max.get("used"), default=""),
            "remaining": _dollar(annual_max.get("remaining"), default=""),
            "description": "",
        },
        "deductible_ind": {
            "total": _dollar(individual_ded.get("total"), default=""),
            "used": _dollar(individual_ded.get("used"), default=""),
            "remaining": _dollar(individual_ded.get("remaining"), default=""),
        },
        "deductible_fam": {
            "total": _dollar(family_ded.get("total"), default=""),
            "used": _dollar(family_ded.get("used"), default=""),
            "remaining": _dollar(family_ded.get("remaining"), default=""),
        },
        "ortho_lifetime": {
            "total": _dollar(ortho_max.get("total"), default=""),
            "used": _dollar(ortho_max.get("used"), default=""),
            "remaining": _dollar(ortho_max.get("remaining"), default=""),
        },
        "maximum_records": maxima,
        "deductible_records": financials.get("deductibles") or [],
    }
    normalized_financials["maximums"] = [
        {
            **row,
            "total": _dollar(row.get("total"), default=""),
            "used": _dollar(row.get("used"), default=""),
            "remaining": _dollar(row.get("remaining"), default=""),
        }
        for row in maxima if isinstance(row, dict)
    ]
    normalized_financials["deductibles"] = [
        {
            **row,
            "total": _dollar(row.get("total"), default=""),
            "used": _dollar(row.get("used"), default=""),
            "remaining": _dollar(row.get("remaining"), default=""),
        }
        for row in financials.get("deductibles") or [] if isinstance(row, dict)
    ]

    return {
        "_skip_llm": True,
        "_source_insurer": "delta dental of rhode island",
        "_ddri": True,
        "ddri_data": True,
        "_raw_export": source,
        "carrier_information": {"name": "Delta Dental of Rhode Island"},
        "patient": normalized_patient,
        "plan_details": normalized_plan,
        "financials": normalized_financials,
        "subscriber_info": {
            "name": _text(patient.get("subscriber_name")) or normalized_patient["name"],
            "dob": _text(patient.get("subscriber_dob")),
            "relation": normalized_patient["relationship"],
        },
        "metlife_data": {
            "patient": normalized_patient,
            "plan_details": normalized_plan,
            "financials": normalized_financials,
            "covered_services": [
                {
                    "category": category["category"],
                    "services": "; ".join(service["name"] for service in category["services"]),
                    "in_network": ", ".join(
                        dict.fromkeys(service["coverage"] for service in category["services"]
                                      if service["coverage"])
                    ),
                    "out_of_network": "",
                }
                for category in _normalized_categories(source)
            ],
            "provisions": [
                {"rule": "Missing Tooth Clause", "value": _text(source.get("missing_tooth_clause"))},
                {"rule": "Dependent Age Limit", "value": _text(source.get("dependent_age_limit"))},
            ],
        },
        "benefit_coverage": {
            **(source.get("benefit_coverage") or {}),
            "procedures": procedures,
        },
        "_normalized_categories": _normalized_categories(source),
    }


__all__ = ["_is_ddri_portal", "_normalize_ddri_portal"]
