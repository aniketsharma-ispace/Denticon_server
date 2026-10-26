from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smile_partners.sabrina.carriers.delta_toolkit import portal, rules
from smile_partners.sabrina.carriers.delta_toolkit.spec import CORE_FIELD_KEYS, _SPEC

BY_KEY = {f["key"]: f for f in _SPEC}


def _toolkit(**raw_export) -> dict:
    return {"_toolkit": True, "_raw_export": raw_export}


def _bd(code: str, *sentences: str) -> dict:
    return {"procs": {code: {"toolkit_source_limitations": list(sentences)}}}


def test_srp_quads_row_reads_d4341_age_cell_against_the_toolkit_cap() -> None:
    row = BY_KEY["d4341__age"]
    assert (row["portal"], row["kind"], row["label"]) == (
        "_toolkit_srp_quads_per_day", "text", "D4341 Scaling Root Planing · Quads")


@pytest.mark.parametrize("sentence, expected", [
    ("Service D4341-D4342 scaling and root planning is limited to two quadrants benefited "
     "on the same date of service/same member.", "2"),
    ("Root planing and scaling is payable once per quadrant in 24 consecutive months.", None),
])
def test_srp_quads_portal_value_is_only_a_stated_same_day_cap(sentence: str, expected) -> None:
    assert portal._portal_value(BY_KEY["d4341__age"], _bd("D4341", sentence), _toolkit(), None) == expected


def test_srp_quads_portal_value_is_not_read_from_a_non_toolkit_export() -> None:
    sentence = "Scaling and root planing is limited to two quadrants on the same date of service."
    assert rules._toolkit_srp_quads_per_day(_bd("D4341", sentence), {}, None) is None


def test_perio_after_srp_row_is_a_sheet_label() -> None:
    row = BY_KEY["perio_maint_after_srp"]
    assert (row["portal"], row["kind"], row["section"]) == ("_toolkit_perio_after_srp", "text", "Clauses")
    assert "perio_maint_after_srp" in CORE_FIELD_KEYS


@pytest.mark.parametrize("sentence, expected", [
    ("Periodontal maintenance is a benefit once a 30 day post-operative period has completed.", "30 Days"),
    ("Prophylaxis procedures are a benefit following active periodontal therapy once a "
     "90-day post-operative period has completed.", "90 Days"),
    ("Periodontal maintenance is payable twice per calendar year.", None),
    ("Implant restorations are a benefit once a 30 day post-operative period has completed.", None),
])
def test_perio_after_srp_is_only_a_stated_post_operative_period(sentence: str, expected) -> None:
    assert portal._portal_value(BY_KEY["perio_maint_after_srp"], _bd("D4910", sentence), _toolkit(), None) == expected


def test_perio_after_srp_is_blank_when_d4910_was_not_looked_up() -> None:
    assert rules._toolkit_perio_after_srp({"procs": {}}, _toolkit(), None) is None


def test_perio_after_srp_is_not_read_from_a_non_toolkit_export() -> None:
    sentence = "Periodontal maintenance is a benefit once a 30 day post-operative period has completed."
    assert rules._toolkit_perio_after_srp(_bd("D4910", sentence), {}, None) is None
