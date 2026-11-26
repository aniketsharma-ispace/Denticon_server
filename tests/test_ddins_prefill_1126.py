"""DDINS prefill (QA sheet 11/25, decisions 11/26): synthetic data only."""

from sabrina.smile_partners import prefill as sp
from sabrina.smile_partners.carriers.delta_dental import prefill as dd


def _raw(plan="Delta Dental PPO", limitation="three evaluations within a calendar year", rows=None):
    return {"primary_patient": {"plan": plan},
            "tabs": {"benefits_search": {"D0120": {"limitations": [limitation]}},
                     "waiting_periods": {"rows": rows or []}}}


def test_plan_type_ppo_only():
    assert dd.form_only({}, {"_raw": _raw()})[0]["value"] == "PPO"
    names = [f["name"] for f in dd.form_only({}, {"_raw": _raw(plan="Delta Dental Premier")})]
    assert "insuranceDetails.planType" not in names


def test_calendar_or_fiscal_from_limitations():
    assert dd._calendar_or_fiscal(_raw()) == "Calendar"
    assert dd._calendar_or_fiscal(_raw(limitation="twice per contract year")) == "Fiscal"
    assert dd._calendar_or_fiscal(_raw(limitation="twice per 12 months")) is None


def test_waiting_period_recorded_even_when_ended():
    rows = [{"waiting_period_begins": "12/01/2025", "waiting_period_ends": "08/31/2026",
             "treatments_and_procedures": [
                 {"treatment_type": "Restorative D2542, D2740, D2750", "procedure_codes": ""},
                 {"treatment_type": "Endodontics D3310", "procedure_codes": ""}]}]
    out = dd.waiting_periods({"_raw_export": _raw(rows=rows)})
    assert out == [{"applies_to": "Major", "period": "9", "unit": "Months",
                    "source": "waiting_periods (D2740)"}]


def test_months_between():
    assert dd._months_between("01/01/2026", "12/31/2026") == 12
    assert dd._months_between("12/01/2025", "05/31/2026") == 6
    assert dd._months_between("", "05/31/2026") is None


def test_not_covered_add_codes_blank_percentage():
    grid = [{"code": "D5995", "column": "percentage", "value": "0"},
            {"code": "D5995", "column": "frequency", "value": "NC"},
            {"code": "D8090", "column": "percentage", "value": "0"},
            {"code": "D6057", "column": "percentage", "value": "50%"},
            {"code": "D4381", "column": "percentage", "value": "0"}]
    kept = {(g["code"], g["column"]) for g in dd.adjust_grid(grid)}
    assert kept == {("D5995", "frequency"), ("D6057", "percentage"), ("D4381", "percentage")}


def test_cob_options():
    assert sp._cob_option("AARP Dental Insurance Plan is always considered the primary plan.") == "Standard"
    assert sp._cob_option("Non-duplication of benefits applies.") == "Non-Duplicate"
    assert sp._cob_option("Standard") == "Standard"
    assert sp._cob_option("Carve-out") == "Carve-Out Clause"
    assert sp._cob_option("Birthday rule") is None
