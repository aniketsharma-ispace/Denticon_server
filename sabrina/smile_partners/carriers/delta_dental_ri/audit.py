"""Run the Sabrina-vs-DD RI audit and assemble the UI response."""

from __future__ import annotations

from .compare import _compare
from .parser import _MIN_MARKERS, parse_sabrina_pdf
from .portal import portal_value
from .rules import ddri_export
from .spec import _CRITICAL_KEYS, _SPEC
from .vocabulary import _blank_for, _blank_means_no_limit

STATUS_MATCH = "match"
STATUS_MISMATCH = "mismatch"
STATUS_NOT_IN_PORTAL = "not_in_portal"
STATUS_MISSING_IN_SABRINA = "missing_in_sabrina"
STATUS_NOT_STATED = "not_stated"
STATUS_NOT_COMPARABLE = "not_comparable"


def compare_sabrina_to_portal(sabrina_parsed: dict, portal_raw: dict) -> dict:
    """Compare parsed Sabrina fields against the DD RI extension export."""
    sab_fields = sabrina_parsed.get("fields") or {}
    sections: dict[str, list] = {}
    rows: list[dict] = []

    for field in _SPEC:
        key = field["key"]
        sab_raw = sab_fields.get(key)
        por_raw = portal_value(field, portal_raw)
        sab_blank = _blank_for(field["kind"], sab_raw)
        por_blank = _blank_for(field["kind"], por_raw)
        note = ""

        if sab_blank and por_blank:
            status = STATUS_NOT_STATED
        elif por_blank:
            status = STATUS_NOT_IN_PORTAL
            note = ("no equivalent field in the portal export"
                    if field.get("portal") is None
                    else "portal did not state this value")
        elif sab_blank and _blank_means_no_limit(field["kind"], por_raw):
            status = STATUS_MATCH
            note = "blank on the sheet and no limit on the portal — same thing"
        elif sab_blank:
            status = STATUS_MISMATCH
            note = "blank on the Sabrina sheet, but the portal states it"
        elif field.get("uncomparable"):
            status = STATUS_NOT_COMPARABLE
            note = field["uncomparable"]
        else:
            equal, note = _compare(field["kind"], sab_raw, por_raw)
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

    def count(*statuses):
        return sum(row["status"] in statuses for row in rows)

    mismatches = [row for row in rows if row["status"] == STATUS_MISMATCH]
    mismatches.sort(key=lambda row: (not row["critical"], rows.index(row)))
    matched = count(STATUS_MATCH)
    compared = matched + len(mismatches)
    ddri_raw = ddri_export(portal_raw)
    return {
        "source": "sabrina",
        "carrier": "delta_dental_ri",
        "patient": {
            "name": sab_fields.get("patient_name"),
            "dob": sab_fields.get("patient_dob"),
            "member_id": sab_fields.get("member_id"),
            "insurance": sab_fields.get("ins_name"),
        },
        "portal_insurer": "Delta Dental of Rhode Island",
        "summary": {
            "total_fields": len(rows),
            "compared": compared,
            "matches": matched,
            "mismatches": len(mismatches),
            "critical_mismatches": sum(row["critical"] for row in mismatches),
            "not_in_portal": count(STATUS_NOT_IN_PORTAL),
            "missing_in_sabrina": count(STATUS_MISSING_IN_SABRINA),
            "not_stated": count(STATUS_NOT_STATED),
            "not_comparable": count(STATUS_NOT_COMPARABLE),
            "match_rate": round(matched / compared * 100, 1) if compared else 0.0,
        },
        "mismatches": mismatches,
        "sections": [{"section": name, "rows": section_rows}
                     for name, section_rows in sections.items()],
        "diagnostics": {
            "labels_not_found": sabrina_parsed.get("labels_not_found", []),
            "marker_count": sabrina_parsed.get("marker_count"),
            "pdf_line_count": sabrina_parsed.get("line_count"),
            "network_status": portal_value(
                {"portal": "_in_network"}, portal_raw
            ),
            "network_product": (ddri_raw.get("plan_details") or {}).get("network_status"),
        },
    }


async def audit_sabrina_pdf(pdf_bytes: bytes, portal_raw: dict) -> dict:
    """Parse Sabrina PDF, validate it, and compare it with a DD RI export."""
    if not portal_raw:
        raise ValueError("Upload the insurance portal export (JSON) to compare against.")
    parsed = parse_sabrina_pdf(pdf_bytes)
    if parsed["marker_count"] < _MIN_MARKERS:
        raise ValueError(
            "This PDF doesn't look like a Sabrina patient breakdown "
            f"(matched only {parsed['marker_count']} of the expected field labels)."
        )
    return compare_sabrina_to_portal(parsed, portal_raw)
