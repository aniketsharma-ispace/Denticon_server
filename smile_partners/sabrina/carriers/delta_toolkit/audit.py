"""
The audit itself.

Parse the sheet, read the portal, compare field by field, and return a
UI-ready result: per-section rows carrying both sides' raw values, a
mismatches-only list, and the counts.
"""

from __future__ import annotations

import re

from .spec import _CRITICAL_KEYS
from .vocabulary import _blank_for, _blank_means_no_limit, _num_date, _num_history
from .parser import _MIN_MARKERS, parse_sabrina_pdf, parse_sabrina_text
from .spec import _SPEC
from .compare import _compare
from .portal import (
    _portal_breakdown,
    _portal_normalized,
    _portal_value,
)
from .rules import (
    _pdf_eligibility,
    _pdf_major_payment_timing,
    _pdf_ortho_coverage,
    _pdf_relationship,
    _toolkit_eligibility,
    _toolkit_identity_gate,
    _toolkit_not_covered_age_agrees,
)


# Public status constants consumed by the API/UI package. Keep the legacy
# lowercase values so existing DD INS clients remain wire-compatible.
STATUS_MATCH = "match"
STATUS_MISMATCH = "mismatch"
STATUS_NOT_IN_PORTAL = "not_in_portal"
STATUS_MISSING_IN_SABRINA = "missing_in_sabrina"
STATUS_NOT_STATED = "not_stated"
STATUS_NOT_COMPARABLE = "not_comparable"


def _age_from_dob(dob) -> int | None:
    """Patient age today, from the date of birth printed on the sheet."""
    normalized = _num_date(dob)
    if not normalized:
        return None
    import datetime
    try:
        born = datetime.datetime.strptime(normalized, "%m/%d/%Y").date()
    except ValueError:
        return None
    today = datetime.date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return age if 0 <= age <= 130 else None


def _is_freq_not_available(value) -> bool:
    return bool(re.fullmatch(r"\s*(?:frequency\s+)?not\s+available\s*", str(value or ""), re.IGNORECASE))


def _toolkit_row_code(field: dict, procs: dict) -> str | None:
    """The CDT code a Toolkit row was read from: its own code, or for a row
    with a fallback, the first of its codes the portal returned."""
    src = field.get("portal")
    if not (isinstance(src, tuple) and src and src[0] in ("code", "codefield")):
        return None
    codes = [str(c).upper() for c in (src[1:] if src[0] == "code" else src[2:])]
    if field.get("toolkit_fallback"):
        for code in codes:
            if code in procs:
                return code
    return codes[0] if codes else None


def compare_sabrina_to_portal(sabrina_parsed: dict, portal_raw: dict) -> dict:
    """
    Audit a parsed Sabrina PDF against the insurance portal export.

    Returns a UI-ready payload: per-section rows, a mismatches-only list, and
    counts. Every row carries both raw values so a reviewer can see exactly
    what each system says.
    """
    sab_fields = sabrina_parsed.get("fields", {})
    bd = _portal_breakdown(portal_raw)
    # Derived readers work off the translated export, not the raw one.
    portal_norm = _portal_normalized(portal_raw)

    if portal_norm.get("_toolkit") and sabrina_parsed.get("text"):
        if not sabrina_parsed.get("toolkit_parse"):
            sabrina_parsed = {**sabrina_parsed, **parse_sabrina_text(sabrina_parsed["text"], toolkit=True)}
        # Toolkit uses the full seven-page Sabrina PDF. The generic Sabrina
        # parser intentionally skips portal_only CDT rows for legacy carrier
        # compatibility, so the Toolkit adapter supplements those rows from
        # the embedded Delta benefit pages without changing legacy behavior.
        from ....portals.delta_toolkit import enrich_toolkit_sabrina_parse
        sabrina_parsed = enrich_toolkit_sabrina_parse(sabrina_parsed)
        sab_fields = sabrina_parsed.get("fields", {})

    toolkit_identity_ok, toolkit_identity_issues = (
        _toolkit_identity_gate(sabrina_parsed, portal_norm)
        if portal_norm.get("_toolkit") else (True, [])
    )

    toolkit_meta = portal_norm.get("_toolkit_meta") if isinstance(portal_norm.get("_toolkit_meta"), dict) else {}
    toolkit_failed = {str(code).upper() for code in (toolkit_meta.get("failed_codes") or [])}
    toolkit_not_in_portal = {str(code).upper() for code in (toolkit_meta.get("codes_not_in_portal") or [])}

    # Some portal rules are stated per age band ("… TO AGE 19, … FOR ADULTS"),
    # so the patient's age decides which one governs. Taken as of today, which
    # is right to within a day or two of the appointment.
    ctx = {"age": _age_from_dob(sab_fields.get("patient_dob"))}

    sections: dict[str, list] = {}
    rows: list[dict] = []

    for field in _SPEC:
        if field.get("toolkit_only") and not portal_norm.get("_toolkit"):
            continue
        key = field["key"]
        # A CDT percentage row anchors its code's group.
        if field["section"] == "Coverage by CDT Code" and not field.get("derived"):
            field.setdefault("group", key)
            field.setdefault("group_label", field["label"])
            field.setdefault("aspect", "pct")
        sab_raw = sab_fields.get(key)
        if portal_norm.get("_toolkit") and key == "eligibility":
            sab_raw = _pdf_eligibility(sabrina_parsed.get("text", ""))
        elif portal_norm.get("_toolkit") and key == "relationship":
            sab_raw = _pdf_relationship(sabrina_parsed.get("text", ""))
        elif portal_norm.get("_toolkit") and key == "major_payment_timing":
            sab_raw = _pdf_major_payment_timing(sabrina_parsed.get("text", ""))
        elif portal_norm.get("_toolkit") and key == "ortho_coverage":
            sab_raw = _pdf_ortho_coverage(sabrina_parsed.get("text", ""))
        # Benefit Details is the canonical source for procedure percentages.
        # The same CDT label can appear in the page-1 coverage summary with a
        # different display token such as "Optional"; never let that summary
        # override the six-column Benefit Details row.
        if (
            field.get("section") == "Coverage by CDT Code"
            and field.get("aspect") == "pct"
        ):
            benefit_row = (sabrina_parsed.get("benefit_rows") or {}).get(key)
            if isinstance(benefit_row, dict) and benefit_row.get("percentage") is not None:
                sab_raw = benefit_row.get("percentage")
        por_raw = _portal_value(field, bd, portal_norm, sab_raw)

        sab_blank = _blank_for(field["kind"], sab_raw)
        por_blank = _blank_for(field["kind"], por_raw)

        # The portal shows a dash (or nothing) in History where a procedure was
        # never performed — the same statement the sheet writes as "NH". When
        # the sheet says NH and the portal cell is empty, read the portal as NH
        # so the pair is compared as a match instead of "not comparable".
        if (
            field["kind"] == "history"
            and por_blank
            and not sab_blank
            and _num_history(sab_raw) == "NONE"
        ):
            por_raw = "NH"
            por_blank = False
        note = ""

        if sab_blank and por_blank:
            status = STATUS_NOT_STATED
            if (
                portal_norm.get("_toolkit")
                and key == "term_date"
                and _toolkit_eligibility({}, portal_norm) == "Yes"
            ):
                status = STATUS_MATCH
                note = "no termination date on either side; the member is active"
        elif por_blank:
            # The portal never stated it → cannot be called a mismatch.
            status = STATUS_NOT_IN_PORTAL
            note = ("no equivalent field in the portal export"
                    if field.get("portal") is None
                    else "portal did not state this value")
        elif sab_blank and _blank_means_no_limit(field["kind"], por_raw):
            status = STATUS_MATCH
            note = "blank on the sheet and no limit on the portal — same thing"
        elif sab_blank:
            status = STATUS_MISSING_IN_SABRINA
            note = "blank on the Sabrina sheet"
        elif field.get("uncomparable"):
            status = STATUS_NOT_COMPARABLE
            note = field["uncomparable"]
        else:
            if (
                portal_norm.get("_toolkit")
                and field["kind"] == "frequency"
                and (_is_freq_not_available(sab_raw) or _is_freq_not_available(por_raw))
            ):
                equal, cmp_note = _is_freq_not_available(sab_raw) and _is_freq_not_available(por_raw), ""
            elif (
                portal_norm.get("_toolkit")
                and field["kind"] == "agelimit"
                and str(por_raw).strip().casefold() == "not covered"
            ):
                equal, cmp_note = _toolkit_not_covered_age_agrees(sab_raw)
            else:
                equal, cmp_note = _compare(field["kind"], sab_raw, por_raw, ctx)
            note = cmp_note
            if equal is None:
                status = STATUS_NOT_COMPARABLE
                note = note or "values are not in a comparable form"
            else:
                status = STATUS_MATCH if equal else STATUS_MISMATCH

        # Toolkit data has a hard retrieval failure signal.  A failed CDT lookup
        # is data-unavailable, never a benefit mismatch.
        if portal_norm.get("_toolkit") and field.get("section") == "Coverage by CDT Code":
            code = _toolkit_row_code(field, bd.get("procs") or {})
            if code in toolkit_failed:
                status = STATUS_NOT_COMPARABLE
                note = f"Toolkit lookup failed for {code}; no source benefit data was retrieved."
            elif code in toolkit_not_in_portal:
                status = STATUS_NOT_COMPARABLE
                note = (f"{code} is not in the Toolkit's procedure code list; "
                        "the portal returned no benefit for it.")
            elif not toolkit_identity_ok:
                status = STATUS_NOT_COMPARABLE
                note = "Identity/network validation failed: " + ", ".join(toolkit_identity_issues)

        if portal_norm.get("_toolkit"):
            if not toolkit_identity_ok:
                # The safety gate applies to every plan/procedure comparison.
                status = STATUS_NOT_COMPARABLE
                note = "Identity/network validation failed: " + ", ".join(toolkit_identity_issues)
            elif por_blank and not sab_blank and field.get("portal") == "_toolkit_srp_quads_per_day":
                # Few Toolkit plans state a same-day quadrant cap. Its absence is
                # no evidence against the sheet, and must not turn a D4341 whose
                # percentage, frequency and history agree into "not comparable".
                status = STATUS_NOT_IN_PORTAL
                note = "the Toolkit states no same-day quadrant cap for D4341"
            elif por_blank and not sab_blank:
                # Toolkit missing data is an evidence gap, not a negative answer.
                status = STATUS_NOT_COMPARABLE
                if field["kind"] == "agelimit" and str(sab_raw).strip().upper() == "NC":
                    note = "Sabrina states NC (no numeric age limit); the Toolkit states no age limit for this code."
                else:
                    note = note or "Toolkit did not expose this value."

        row = {
            "key": key,
            "label": field["label"],
            "section": field["section"],
            "kind": field["kind"],
            # Set for the CDT rows so the UI can show one line per code with a
            # cell per column instead of four separate rows.
            "group": field.get("group"),
            "group_label": field.get("group_label"),
            "aspect": field.get("aspect"),
            "sabrina": None if sab_blank else str(sab_raw).strip(),
            "portal": None if por_blank else str(por_raw).strip(),
            "status": status,
            "critical": key in _CRITICAL_KEYS,
            "note": note,
        }
        if portal_norm.get("_toolkit") and field.get("section") == "Coverage by CDT Code":
            code = _toolkit_row_code(field, bd.get("procs") or {})
            if code:
                proc = (bd.get("procs") or {}).get(code) or {}
                row["source_trace"] = {
                    "cdt_code": code,
                    "percentage": proc.get("benefit_level"),
                    "raw_limitation": proc.get("toolkit_source_limitations") or proc.get("limitations"),
                    "derived_frequency": proc.get("frequency_limit"),
                    "age_limit": proc.get("age_limit"),
                    "history": proc.get("late_date_of_service"),
                    "waiting_period": proc.get("toolkit_waiting_period"),
                    "procedure_path": proc.get("procedure_path"),
                    "retrieval_status": (proc.get("toolkit_status") if proc
                                         else ("FAILED" if code in toolkit_failed
                                               else "NOT_IN_PORTAL_CODE_LIST" if code in toolkit_not_in_portal
                                               else None)),
                    "error": proc.get("toolkit_error") if proc else (
                        f"Toolkit lookup failed for {code}." if code in toolkit_failed
                        else f"{code} is not in the Toolkit's procedure code list." if code in toolkit_not_in_portal
                        else None
                    ),
                }
        rows.append(row)
        sections.setdefault(field["section"], []).append(row)

    def _count(*statuses) -> int:
        return sum(1 for r in rows if r["status"] in statuses)

    mismatches = [r for r in rows if r["status"] == STATUS_MISMATCH]
    # Critical disagreements first, then sheet order.
    mismatches.sort(key=lambda r: (not r["critical"], rows.index(r)))

    matched = _count(STATUS_MATCH)
    compared = matched + len(mismatches)

    return {
        "source": "sabrina",
        "patient": {
            "name": sab_fields.get("patient_name"),
            "dob": sab_fields.get("patient_dob"),
            "member_id": sab_fields.get("member_id"),
            "insurance": sab_fields.get("ins_name"),
        },
        "portal_insurer": bd.get("source_insurer") or (portal_raw or {}).get("summary", {}).get("insurer") or "",
        "summary": {
            "total_fields": len(rows),
            "compared": compared,
            "matches": matched,
            "mismatches": len(mismatches),
            "critical_mismatches": sum(1 for r in mismatches if r["critical"]),
            "not_in_portal": _count(STATUS_NOT_IN_PORTAL),
            "missing_in_sabrina": _count(STATUS_MISSING_IN_SABRINA),
            "not_stated": _count(STATUS_NOT_STATED),
            "not_comparable": _count(STATUS_NOT_COMPARABLE),
            "match_rate": round(matched / compared * 100, 1) if compared else 0.0,
        },
        "mismatches": mismatches,
        "sections": [{"section": name, "rows": rws} for name, rws in sections.items()],
        "diagnostics": {
            "labels_not_found": sabrina_parsed.get("labels_not_found", []),
            "marker_count": sabrina_parsed.get("marker_count"),
            "pdf_line_count": sabrina_parsed.get("line_count"),
            # Delta only: the provider network the per-code rows were read under.
            "portal_network": (((portal_raw or {}).get("tabs") or {}).get("benefits_search_network")
                              if isinstance((portal_raw or {}).get("tabs"), dict) else None),
            "toolkit": {
                "requested_codes": toolkit_meta.get("requested_codes"),
                "successful_codes": toolkit_meta.get("successful_codes"),
                "failed_codes": sorted(toolkit_failed),
                "codes_not_in_portal": sorted(toolkit_not_in_portal),
                "identity_valid": toolkit_identity_ok,
                "identity_issues": toolkit_identity_issues,
            } if portal_norm.get("_toolkit") else None,
        },
    }


async def audit_sabrina_pdf(pdf_bytes: bytes, portal_raw: dict) -> dict:
    """
    Full path: Sabrina PDF bytes + portal export → comparison payload.

    Raises ValueError (→ HTTP 422) when the upload is not a Sabrina breakdown,
    so the caller can tell the user they picked the wrong file.
    """
    parsed = parse_sabrina_pdf(pdf_bytes)

    if parsed["marker_count"] < _MIN_MARKERS:
        raise ValueError(
            "This PDF doesn't look like a Sabrina patient breakdown "
            f"(matched only {parsed['marker_count']} of the expected field "
            "labels). Upload the breakdown PDF downloaded from Sabrina, or use "
            "the Denticon JSON export instead."
        )

    if not portal_raw:
        raise ValueError("Upload the insurance portal export (JSON or PDF) to compare against.")

    return compare_sabrina_to_portal(parsed, portal_raw)
