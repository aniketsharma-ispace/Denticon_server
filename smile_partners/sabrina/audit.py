"""
The audit itself.

Parse the sheet, read the portal, compare field by field, and return a
UI-ready result: per-section rows carrying both sides' raw values, a
mismatches-only list, and the counts.
"""

from __future__ import annotations

from .spec import _CRITICAL_KEYS
from .vocabulary import _blank_for, _blank_means_no_limit, _num_date
from .parser import _MIN_MARKERS, parse_sabrina_pdf
from .spec import _SPEC
from .compare import _compare
from .portal import (_breakdown_for_sheet, _portal_breakdown, _portal_for_sheet,
                     _portal_normalized, _portal_value)


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

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


def compare_sabrina_to_portal(sabrina_parsed: dict, portal_raw: dict) -> dict:
    """
    Audit a parsed Sabrina PDF against the insurance portal export.

    Returns a UI-ready payload: per-section rows, a mismatches-only list, and
    counts. Every row carries both raw values so a reviewer can see exactly
    what each system says.
    """
    sab_fields = sabrina_parsed.get("fields", {})
    # Pick what the sheet should be read against (Aetna: the network its
    # In Network field names). Other carriers pass through unchanged.
    portal_raw = _portal_for_sheet(portal_raw, sab_fields)
    bd = _portal_breakdown(portal_raw)
    # Derived readers work off the translated export, not the raw one.
    portal_norm = _portal_normalized(portal_raw)
    bd = _breakdown_for_sheet(bd, portal_norm)

    # Some portal rules are stated per age band ("… TO AGE 19, … FOR ADULTS"),
    # so the patient's age decides which one governs. Taken as of today, which
    # is right to within a day or two of the appointment.
    ctx = {"age": _age_from_dob(sab_fields.get("patient_dob"))}

    sections: dict[str, list] = {}
    rows: list[dict] = []

    for field in _SPEC:
        key = field["key"]
        # A CDT percentage row anchors its code's group.
        if field["section"] == "Coverage by CDT Code" and not field.get("derived"):
            field.setdefault("group", key)
            field.setdefault("group_label", field["label"])
            field.setdefault("aspect", "pct")
        sab_raw = sab_fields.get(key)
        por_raw = _portal_value(field, bd, portal_norm, sab_raw)

        sab_blank = _blank_for(field["kind"], sab_raw)
        por_blank = _blank_for(field["kind"], por_raw)
        note = ""

        if sab_blank and por_blank:
            status = STATUS_NOT_STATED
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
            equal, cmp_note = _compare(field["kind"], sab_raw, por_raw, ctx)
            note = cmp_note
            if equal is None:
                status = STATUS_NOT_COMPARABLE
                note = note or "values are not in a comparable form"
            else:
                status = STATUS_MATCH if equal else STATUS_MISMATCH

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
            "not_stated": _count(STATUS_NOT_STATED, STATUS_NOT_COMPARABLE),
            "match_rate": round(matched / compared * 100, 1) if compared else 0.0,
        },
        "mismatches": mismatches,
        "sections": [{"section": name, "rows": rws} for name, rws in sections.items()],
        "diagnostics": {
            "labels_not_found": sabrina_parsed.get("labels_not_found", []),
            "marker_count": sabrina_parsed.get("marker_count"),
            "pdf_line_count": sabrina_parsed.get("line_count"),
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