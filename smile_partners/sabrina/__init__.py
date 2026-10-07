"""
Smile Partners — the Sabrina breakdown sheet.

A BPO team working in Sabrina exports a patient insurance-breakdown PDF.
There is nothing to plan-match — Sabrina gives one record, not a list of
candidates — so what they need is a straight field-by-field audit of that
sheet against the insurance portal.

The audit is kept one folder per insurance portal, under `carriers/`. Each
folder holds all of it for its carrier — what the sheet contains (`spec`),
how to read it (`parser`), how to say whether two values agree
(`vocabulary`, `compare`), where each answer is found on the portal
(`portal`), the carrier's own rules (`rules`) and the audit (`audit`). The
uploaded portal export decides which folder runs; the others are never
imported. Reading a carrier's export itself belongs in `portals/`.

`sheet/` only recognizes an uploaded sheet before the portal is known. It
never takes part in an audit.

Comparison philosophy: a value the portal never stated is not a mismatch. It
is reported as `not_in_portal` and left out of the mismatch count, because
inventing a portal value fabricates failures. Only a field both sides state
can ever disagree.
"""

from .sheet import core_fields, is_sabrina_pdf, parse_sabrina_pdf, sabrina_marker_count
from .carriers import CARRIERS, carrier_rules, detect_carrier


def compare_sabrina_to_portal(sabrina_parsed: dict, portal_raw: dict) -> dict:
    """
    Audit an already-parsed sheet with the folder of the carrier whose portal
    export this is. The result names that folder as `carrier`.

    Raises ValueError for an export from a portal with no folder.
    """
    key, rules = carrier_rules(portal_raw)
    result = rules.compare_sabrina_to_portal(sabrina_parsed, portal_raw)
    result["carrier"] = key
    return result


async def audit_sabrina_pdf(pdf_bytes: bytes, portal_raw: dict) -> dict:
    """
    Full path: Sabrina PDF bytes + portal export → comparison payload, run
    entirely by the folder of the carrier whose export this is — it reads the
    sheet with its own parser, too.

    Raises ValueError (→ HTTP 422) when the export is from a portal with no
    folder, or when the upload is not a Sabrina breakdown.
    """
    if not portal_raw:
        raise ValueError("Upload the insurance portal export (JSON or PDF) to compare against.")
    key, rules = carrier_rules(portal_raw)
    result = await rules.audit_sabrina_pdf(pdf_bytes, portal_raw)
    result["carrier"] = key
    return result


__all__ = [
    "CARRIERS",
    "audit_sabrina_pdf",
    "carrier_rules",
    "compare_sabrina_to_portal",
    "core_fields",
    "detect_carrier",
    "is_sabrina_pdf",
    "parse_sabrina_pdf",
    "sabrina_marker_count",
]
