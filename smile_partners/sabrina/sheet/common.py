"""
Shared plumbing for the Smile Partners audit.
"""

from __future__ import annotations

import logging
import os


log = logging.getLogger(__name__)


# Set SABRINA_DEBUG=1 to log every label the parser could not locate in the PDF.
_DEBUG = os.environ.get("SABRINA_DEBUG", "").strip() not in ("", "0", "false", "False")


# Denticon's "unlimited maximum" convention, mirrored from compare_patients.py
# so an "Unlimited" yearly max on one side matches $99,999 on the other.
_UNLIMITED_MAX = 99999.0


# Values that mean "this field was left blank", on either side.
_BLANKS = {
    "", "-", "--", "---", "—", "–", "n/a", "na", "n.a.", "none", "null",
    "nil", "tbd", "?", "??", "not applicable", "not listed", "not stated",
    "not available", "unknown", "blank", "no data", "pending",
}
