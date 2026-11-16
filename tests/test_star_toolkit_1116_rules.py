"""Star DD Toolkit 11/16 rules (see RULES.md [11/16]): no customer data.

1. Claims dated on or after the sheet's verification date are not held
   against the sheet.
2. Ortho age: a "Birth Day" config age N equals a sheet N-1; a subscriber 0
   agrees with children-only ortho.
3. Group Name is compared with spaces ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from star_dental.sabrina.carriers.delta_toolkit import rules


# ── 1. Verification date ────────────────────────────────────────────────────

def test_verification_date_from_the_embedded_delta_page() -> None:
    text = "Appointment Date \n10/20/2026 12:30 PM\n...\nVerification Date: 10/27/2026 16:58:56\n"
    assert rules._pdf_verification_date(text) == "10/27/2026"


def test_verification_date_from_the_information_available_sentence() -> None:
    text = "Eligibility and Benefits are based on information available on 10/12/2026 . This is"
    assert rules._pdf_verification_date(text) == "10/12/2026"


def test_verification_date_falls_back_to_the_appointment_date() -> None:
    # A sheet verified by ticket fax has no embedded Delta page.
    text = "Appointment Date \n10/27/2026 07:00 AM\nPatient/Subscriber Information"
    assert rules._pdf_verification_date(text) == "10/27/2026"
    assert rules._pdf_verification_date("no dates here") is None


def _export(routine=None, results=None) -> dict:
    return {
        "routine_procedures": {"rows": routine or []},
        "coverages": {"procedure_code_search": {"results": results or []}},
    }


def test_claims_on_or_after_the_verification_date() -> None:
    export = _export(
        routine=[{"procedureCode": "D0120", "serviceDates": ["10/26/2026", "10/12/2026", "04/30/2026"]}],
        results=[{"procedureCode": "D0272", "utilization_history": ["10/27/2026"]},
                 {"procedureCode": "D0210", "utilization_history": ["03/23/2023"]}],
    )
    assert rules._toolkit_claims_since(export, "10/12/2026") == ["10/27/2026", "10/26/2026", "10/12/2026"]
    assert rules._toolkit_claims_since(export, "10/28/2026") == []
    assert rules._toolkit_claims_since(export, None) == []


def test_history_drops_dates_on_or_after_the_verification_date() -> None:
    assert rules._history_before("10/26/2026, 10/12/2026", "10/12/2026") == ("NH", ["10/26/2026", "10/12/2026"])
    assert rules._history_before("10/27/2026, 04/30/2026", "10/27/2026") == ("04/30/2026", ["10/27/2026"])
    assert rules._history_before("03/23/2023", "10/27/2026") == ("03/23/2023", [])
    assert rules._history_before("NH", "10/27/2026") == ("NH", [])
    # A late date the sheet already lists stays.
    assert rules._history_before("10/27/2026, 04/30/2026", "10/27/2026", keep=["10/27/2026"]) == (
        "10/27/2026, 04/30/2026", [])


# ── 2. Ortho age ────────────────────────────────────────────────────────────

def _ortho(subscriber, minor, rule="Birth Day") -> dict:
    # The normalized export, as the audit passes it.
    return {"_toolkit": True, "_toolkit_meta": {"selected_network": "PPO Dentist"},
            "_raw_export": {"ortho_information": {"orthoAgeLimitConfig": [{
                "networks": ["PPO Dentist"], "subscriberMaxAge": subscriber, "minorMaxAge": minor,
                "subscriberRule": rule, "minorRule": rule,
            }]}}}


@pytest.mark.parametrize("key, sheet, portal, expected", [
    ("dependent_age_limit", "18", "19", True),     # "covered for age 18 and under"
    ("dependent_age_limit", "17", "19", False),
    ("subscriber_age_limit", "0", "19", True),     # adults are not covered
    ("subscriber_age_limit", "00", "19", True),
    ("subscriber_age_limit", "0", "99", False),    # adults are covered
    ("subscriber_age_limit", "18", "19", True),
])
def test_ortho_age_agrees(key, sheet, portal, expected) -> None:
    assert bool(rules._toolkit_ortho_age_agrees(key, sheet, portal, _ortho(19, 19))) is expected


def test_ortho_age_tolerance_needs_the_birth_day_rule() -> None:
    export = _ortho(0, 20, rule="Banding Date Continues Treatment")
    assert not rules._toolkit_ortho_age_agrees("dependent_age_limit", "19", "20", export)


# ── 3. Group Name ───────────────────────────────────────────────────────────

def test_group_name_spaced_differently() -> None:
    assert rules._same_text_ignoring_spaces("Smith Hosp itality , LLC", "Smith Hospitality, LLC")
    assert not rules._same_text_ignoring_spaces("Smith Hospitality", "Smith Holdings")
