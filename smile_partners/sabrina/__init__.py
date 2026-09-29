"""
Smile Partners — the Sabrina breakdown sheet.

A BPO team working in Sabrina exports a patient insurance-breakdown PDF.
There is nothing to plan-match — Sabrina gives one record, not a list of
candidates — so what they need is a straight field-by-field audit of that
sheet against the insurance portal.

The sheet is this vendor's; the portals behind it are not. Reading a
carrier's export belongs in `portals/`, which every vendor shares. What lives
here is the sheet: what it contains (`spec`), how to read it (`parser`), how
to say whether two values agree (`vocabulary`, `compare`), where each answer
is found on the portal (`portal`), and the handful of rules that apply only
to one carrier *and* to the way this sheet records it (`carriers/`).

Comparison philosophy: a value the portal never stated is not a mismatch. It
is reported as `not_in_portal` and left out of the mismatch count, because
inventing a portal value fabricates failures. Only a field both sides state
can ever disagree.
"""

from .spec import core_fields
from .parser import is_sabrina_pdf, parse_sabrina_pdf, sabrina_marker_count
from .audit import (
    STATUS_MATCH,
    STATUS_MISMATCH,
    STATUS_MISSING_IN_SABRINA,
    STATUS_NOT_COMPARABLE,
    STATUS_NOT_IN_PORTAL,
    STATUS_NOT_STATED,
    audit_sabrina_pdf,
    compare_sabrina_to_portal,
)

__all__ = [
    "STATUS_MATCH",
    "STATUS_MISMATCH",
    "STATUS_MISSING_IN_SABRINA",
    "STATUS_NOT_COMPARABLE",
    "STATUS_NOT_IN_PORTAL",
    "STATUS_NOT_STATED",
    "audit_sabrina_pdf",
    "compare_sabrina_to_portal",
    "core_fields",
    "is_sabrina_pdf",
    "parse_sabrina_pdf",
    "sabrina_marker_count",
]
