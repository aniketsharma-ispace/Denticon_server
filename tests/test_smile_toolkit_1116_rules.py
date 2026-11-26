"""Smile DD Toolkit 11/16: Group Name compared with spaces ignored (as Star).

No customer data: the audit runs on a parsed sheet and a minimal export.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sabrina.smile_partners.carriers.delta_toolkit import audit, rules


@pytest.mark.parametrize("sheet, portal, expected", [
    ("Smith Hosp itality , LLC", "Smith Hospitality, LLC", True),
    ("SMITH HOSPITALITY LLC", "Smith Hospitality, LLC", True),
    ("Smith Hospitality", "Smith Holdings", False),
    ("", "", False),
])
def test_same_text_ignoring_spaces(sheet, portal, expected) -> None:
    assert rules._same_text_ignoring_spaces(sheet, portal) is expected


def _group_row(sheet_group: str, portal_group: str, monkeypatch) -> dict:
    # Pass the identity gate and read the Group Name straight from the export,
    # so the row shows the comparison alone.
    monkeypatch.setattr(audit, "_toolkit_identity_gate", lambda *a, **k: (True, []))
    monkeypatch.setattr(audit, "_portal_normalized", lambda raw, network=None: {"_toolkit": True, "_toolkit_meta": {}})
    monkeypatch.setattr(audit, "_portal_breakdown", lambda raw, network=None: {})
    real_value = audit._portal_value
    monkeypatch.setattr(audit, "_portal_value",
                        lambda field, bd, norm, sab=None: portal_group if field["key"] == "group_name"
                        else real_value(field, bd, norm, sab))
    result = audit.compare_sabrina_to_portal({"fields": {"group_name": sheet_group}}, {})
    return next(r for s in result["sections"] for r in s["rows"] if r["key"] == "group_name")


def test_group_name_spaced_differently_matches(monkeypatch) -> None:
    row = _group_row("Smith Hosp itality , LLC", "Smith Hospitality, LLC", monkeypatch)
    assert row["status"] == "match"
    assert row["note"] == "same name, spaced differently"


def test_a_different_group_name_still_mismatches(monkeypatch) -> None:
    assert _group_row("Smith Hospitality", "Smith Holdings", monkeypatch)["status"] == "mismatch"
