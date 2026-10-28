"""
The audit itself.

Parse the sheet, read the portal, compare field by field, and return a
UI-ready result: per-section rows carrying both sides' raw values, a
mismatches-only list, and the counts.
"""

from __future__ import annotations

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
    _pdf_ortho_max_type,
    _pdf_ortho_payment_timing,
    _pdf_relationship,
    _pdf_srp_quads_per_day,
    _toolkit_benefit_network,
    _toolkit_code_looked_up,
    _toolkit_eligibility,
    _toolkit_identity_gate,
)


# Public status constants consumed by the API/UI package. Keep the legacy
# lowercase values so existing DD INS clients remain wire-compatible.
STATUS_MATCH = "match"
STATUS_MISMATCH = "mismatch"
STATUS_NOT_IN_PORTAL = "not_in_portal"
STATUS_MISSING_IN_SABRINA = "missing_in_sabrina"
STATUS_NOT_STATED = "not_stated"
STATUS_NOT_COMPARABLE = "not_comparable"

_NO_BENEFIT_WORDS = {
    "0", "0%", "nc", "n/c", "not covered", "not a covered benefit",
    "no frequency", "none",
}

# Rows read from the Maximums and Deductibles table, whose figures can differ
# from one network to another.
_NETWORK_AMOUNT_KEYS = {
    "yearly_max", "yearly_max_paid", "indiv_ded", "indiv_ded_paid",
    "family_ded", "family_ded_paid", "ortho_max", "ortho_max_paid",
    "ortho_ded", "ortho_ded_paid",
}


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


def compare_sabrina_to_portal(sabrina_parsed: dict, portal_raw: dict) -> dict:
    """
    Audit a parsed Sabrina PDF against the insurance portal export.

    Returns a UI-ready payload: per-section rows, a mismatches-only list, and
    counts. Every row carries both raw values so a reviewer can see exactly
    what each system says.
    """
    sab_fields = sabrina_parsed.get("fields", {})
    # The sheet's In Network answer decides which network's benefits it is
    # compared with: an out-of-network sheet records the Nonparticipating
    # Dentist figures, not the PPO ones.
    network = _toolkit_benefit_network(sab_fields)
    bd = _portal_breakdown(portal_raw, network)
    # Derived readers work off the translated export, not the raw one.
    portal_norm = _portal_normalized(portal_raw, network)

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
    ctx = {
        "age": _age_from_dob(sab_fields.get("patient_dob")),
        "toolkit": bool(portal_norm.get("_toolkit")),
    }

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
        elif portal_norm.get("_toolkit") and key == "ortho_max_type":
            sab_raw = _pdf_ortho_max_type(sabrina_parsed.get("text", ""))
        elif portal_norm.get("_toolkit") and key == "ortho_payment_timing":
            sab_raw = _pdf_ortho_payment_timing(sabrina_parsed.get("text", ""))
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
        if toolkit_meta.get("accumulators_unavailable") and key in _NETWORK_AMOUNT_KEYS:
            # The export holds the PPO table alone, and the sheet records another
            # network's maximums, which can differ (PPO $1,500 against a
            # Nonparticipating Dentist $1,000 on one plan).
            por_raw = None
        source_note = ""
        if (
            portal_norm.get("_toolkit")
            and key == "srp_quads_per_day"
            and (por_raw is None or not str(por_raw).strip())
        ):
            embedded_cap = _pdf_srp_quads_per_day(sabrina_parsed.get("text", ""))
            if embedded_cap is not None:
                por_raw = embedded_cap
                source_note = (
                    "Value sourced from the embedded Delta benefit printout; "
                    "the Toolkit JSON does not contain this same-day SRP cap."
                )

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
        note = source_note

        forced_match = None
        if (
            portal_norm.get("_toolkit")
            and key == "subscriber_age_limit"
            and por_blank
            and not sab_blank
            and str(sab_raw).strip() in {"0", "00"}
        ):
            forced_match = "sheet records 0 (no subscriber age limit) and the portal states none"

        if sab_blank and por_blank:
            status = STATUS_NOT_STATED
            if (
                portal_norm.get("_toolkit")
                and field.get("section") == "Coverage by CDT Code"
                and field.get("aspect") == "pct"
                and _toolkit_code_looked_up(field, portal_norm, toolkit_failed | toolkit_not_in_portal)
            ):
                status = STATUS_MATCH
                note = "blank on the sheet and not available on the portal"
            elif (
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
        elif (
            portal_norm.get("_toolkit")
            and field["kind"] == "frequency"
            and str(por_raw or "").strip().casefold() in {"not covered", "not a covered benefit", "nc", "n/c"}
        ):
            if str(sab_raw or "").strip().casefold() in _NO_BENEFIT_WORDS:
                status = STATUS_MATCH
                note = "both sides state no benefit for this procedure"
            else:
                status = STATUS_NOT_COMPARABLE
                note = "portal says the procedure is not covered; a frequency limit is not applicable"
        else:
            equal, cmp_note = _compare(field["kind"], sab_raw, por_raw, ctx)
            note = cmp_note or source_note
            if equal is None:
                status = STATUS_NOT_COMPARABLE
                note = note or "values are not in a comparable form"
            else:
                status = STATUS_MATCH if equal else STATUS_MISMATCH

        # Toolkit data has a hard retrieval failure signal.  A failed CDT lookup
        # is data-unavailable, never a benefit mismatch.
        if portal_norm.get("_toolkit") and field.get("section") == "Coverage by CDT Code":
            code_src = field.get("portal")
            code = None
            if isinstance(code_src, tuple) and code_src and code_src[0] in ("code", "codefield"):
                code = str(code_src[1] if code_src[0] == "code" else code_src[2]).upper()
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
            elif forced_match:
                status = STATUS_MATCH
                note = forced_match
            elif (
                por_blank and not sab_blank and key in _NETWORK_AMOUNT_KEYS
                and toolkit_meta.get("accumulators_unavailable")
            ):
                status = STATUS_NOT_COMPARABLE
                note = ("This export carries only the PPO maximums and deductibles; re-export with "
                        f"extension 1.45+ to compare the {toolkit_meta.get('benefit_network')} figures.")
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
        if source_note:
            row["evidence_source"] = (
                "embedded Delta benefit printout; same-day SRP cap absent from Toolkit JSON"
            )
        if portal_norm.get("_toolkit") and field.get("section") == "Coverage by CDT Code":
            code_src = field.get("portal")
            if isinstance(code_src, tuple) and code_src:
                code = str(code_src[1] if code_src[0] == "code" else code_src[2]).upper()
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
                "benefit_network": toolkit_meta.get("benefit_network") or "PPO Dentist",
                "accumulators_unavailable": bool(toolkit_meta.get("accumulators_unavailable")),
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
