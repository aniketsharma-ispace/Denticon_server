"""
Recognizing an uploaded sheet, before the portal is known.

The server checks a Sabrina PDF the moment it is uploaded — is it a Sabrina
breakdown, whose is it, how many fields could be read — and at that point no
portal export has been chosen, so no carrier's folder can be asked. This is a
carrier-neutral copy of the sheet reader for that check alone.

It never takes part in an audit: each carrier's folder reads the sheet again
with its own `parser.py`. A parsing fix for an audit belongs there, not here.
"""

from .spec import core_fields
from .parser import is_sabrina_pdf, parse_sabrina_pdf, sabrina_marker_count

__all__ = [
    "core_fields",
    "is_sabrina_pdf",
    "parse_sabrina_pdf",
    "sabrina_marker_count",
]
