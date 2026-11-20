import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from smile_partners.sabrina.carriers import carrier_rules, detect_carrier
from smile_partners.sabrina.carriers.delta_dental_ri import compare_sabrina_to_portal
from smile_partners.sabrina.carriers.delta_dental_ri.compare import _compare
from smile_partners.sabrina.carriers.delta_dental_ri.portal import (
    portal_value,
    procedure_value,
)
from smile_partners.sabrina.carriers.delta_dental_ri.vocabulary import (
    _num_agelimit,
    _num_frequency,
)
from smile_partners.portals.delta_dental_ri import (
    _is_ddri_portal,
    _normalize_ddri_portal,
)
from smile_partners.breakdown import _extract


def _portal():
    return {
        "ddri_data": True,
        "patient": {
            "name": "QURRAM FAROOQI",
            "subscriber_name": "QURRAM FAROOQI",
            "member_id": "0003268280",
            "dob": "03/22/1997",
            "relationship": "Subscriber",
        },
        "plan_details": {
            "employer_group": "CFG- STANDARD PLAN- FT",
            "group_number": "5673 - 0101",
            "effective_date": "11/01/2025",
            "network_status": "Delta Dental PPO Plus PremierTM",
            "preventive_in_yearly_max": "Yes",
            "major_services_paid_on": "Seat Date",
        },
        "financials": {
            "maximums": [{"category": "Annual Maximum", "total": "$1,000", "used": "$100"}],
            "deductibles": [
                {"category": "Individual Deductible", "total": "$50", "used": "$20"},
                {"category": "Family Deductible", "total": "$150", "used": "$40"},
            ],
        },
        "benefit_coverage": {
            "procedures": [
                {
                    "procedure_code": "D0120",
                    "coverage_status": "COVERED",
                    "coverage_percentage": "100 %",
                    "frequency": "Twice per calendar year",
                    "waiting_period": "None",
                    "deductible_applies": "No",
                    "history": [],
                },
                {
                    "procedure_code": "D2391",
                    "coverage_status": "COVERED",
                    "coverage_percentage": "80 %",
                    "frequency": "N/A",
                    "age_limit": "N/A",
                    "alternate_benefit": "* Yes",
                    "history": [],
                },
                {
                    "procedure_code": "D2160",
                    "coverage_status": "COVERED",
                    "coverage_percentage": "80%",
                    "frequency": "N/A",
                    "age_limit": "N/A",
                    "history": [],
                },
                {
                    "procedure_code": "D9230",
                    "coverage_status": "NOT COVERED",
                    "coverage_percentage": "N/A",
                    "history": [],
                },
            ],
        },
        "benefit_categories": [
            {"category": "PREVENTIVE", "services": [
                {
                    "procedure": "Cleaning",
                    "deductible_applies": "No",
                    "waiting_period": "None",
                    "frequency_limitations": "Twice per calendar year",
                },
            ]},
            {"category": "DIAGNOSTIC", "services": [
                {
                    "procedure": "Oral exam",
                    "deductible_applies": "No",
                    "waiting_period": "None",
                    "frequency_limitations": "Twice per calendar year",
                },
            ]},
        ],
        "missing_tooth_clause": "No",
    }


class DeltaDentalRiSabrinaTests(unittest.TestCase):
    def test_ddri_marker_selects_its_own_model(self):
        portal = _portal()
        self.assertEqual(detect_carrier(portal), "delta_dental_ri")
        key, module = carrier_rules(portal)
        self.assertEqual(key, "delta_dental_ri")
        self.assertEqual(module.__name__, "smile_partners.sabrina.carriers.delta_dental_ri")

    def test_normalizer_exposes_shared_shape_and_preserves_source(self):
        portal = _portal()
        normalized = _normalize_ddri_portal(portal)
        self.assertTrue(_is_ddri_portal(portal))
        self.assertTrue(_is_ddri_portal({"portal_data": portal}))
        self.assertFalse(_is_ddri_portal({"source": "Delta Dental", "tabs": {}}))
        self.assertEqual(normalized["_source_insurer"], "delta dental of rhode island")
        self.assertIs(normalized["_raw_export"], portal)
        self.assertEqual(normalized["patient"]["name"], "QURRAM FAROOQI")
        self.assertEqual(normalized["metlife_data"]["financials"]["annual_max"]["total"], "1,000.00")
        breakdown = _extract(portal, {})
        self.assertEqual(breakdown["patient_name"], "QURRAM FAROOQI")
        self.assertEqual(breakdown["yearly_max"], "1,000.00")
        procedure = next(
            p for p in normalized["benefit_coverage"]["procedures"]
            if p["procedure_code"] == "D0120"
        )
        self.assertEqual(procedure["frequency_limit"], "Twice per calendar year")

    def test_maps_ddri_fields_and_network_rule(self):
        portal = _portal()
        self.assertEqual(portal_value({"portal": "_in_network"}, portal), "In")
        portal["plan_details"]["network_status"] = "Delta Dental Premier"
        self.assertEqual(portal_value({"portal": "_in_network"}, portal), "In")
        portal["plan_details"]["network_status"] = "Dental Access Product"
        self.assertEqual(portal_value({"portal": "_in_network"}, portal), "Out")
        portal["plan_details"]["network_status"] = "Delta Dental PPO Plus PremierTM"
        self.assertIsNone(portal_value({"portal": "_oon_benefits"}, portal))
        portal["plan_details"]["posterior_composite_downgrade"] = "No"
        self.assertEqual(portal_value({"portal": "_cob"}, portal), "Standard")
        self.assertEqual(portal_value({"portal": "_d4341_quads"}, portal), "4")
        self.assertEqual(portal_value({"portal": "yearly_max"}, portal), "1,000.00")
        self.assertEqual(portal_value({"portal": "indiv_ded_paid"}, portal), "20.00")
        self.assertEqual(portal_value({"portal": "posterior_composite_downgrade"}, portal), "Yes")
        self.assertEqual(portal_value({"portal": ("code", "D9230")}, portal), "0%")
        self.assertEqual(
            portal_value({"portal": ("codefield", "frequency_limit", "D0120")}, portal),
            "2X1Year",
        )

    def test_ddri_frequency_and_age_phrasing_normalizes_without_hiding_differences(self):
        equivalent_frequency_pairs = [
            ("1X36Months", "Replacement limited to once every 36 months"),
            ("1X60Months", "Replacement limited to once every 60 months"),
            ("1X60Months", "Once per site every 60 months"),
            ("1X36Months", "Once per quadrant every 36 months"),
            ("1X24Months", "Once per quadrant every 24 months"),
            ("2X1Year", "Two sets per calendar year"),
            ("Frequency not available", "As required"),
            (
                "1X24Months",
                "For children under age 16, once every 24 months on unrestored permanent bicuspids and molars",
            ),
        ]
        for sabrina, portal in equivalent_frequency_pairs:
            with self.subTest(sabrina=sabrina, portal=portal):
                self.assertEqual(_num_frequency(sabrina), _num_frequency(portal))
                self.assertEqual(_compare("frequency", sabrina, portal)[0], True)

        self.assertEqual(_num_agelimit("16"), _num_agelimit("children under age 16"))
        self.assertEqual(_compare("agelimit", "16", "children under age 16")[0], True)

        # "Frequency not available" is an uncapped benefit in Sabrina, while
        # the portal's once-per-site limit is a real restriction.
        self.assertEqual(
            _compare(
                "frequency",
                "Frequency not available",
                "Once per site every 60 months",
            )[0],
            False,
        )

    def test_code_mappings_recover_verified_benefits_without_cross_code_fallback(self):
        portal = _portal()
        portal["benefit_coverage"]["procedures"].extend([
            {
                "procedure_code": "D2950",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D5212",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D4910",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D6058",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D6065",
                "coverage_status": "COVERED",
                "frequency": "Once every 12 months",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D2980",
                "coverage_status": "COVERED",
                "frequency": "Once per site every 60 months",
                "age_limit": "Under age 18",
            },
            {
                "procedure_code": "D1206",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D4341",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D4342",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D1510",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D1516",
                "coverage_status": "COVERED",
                "frequency": "1XLifetime",
                "frequency_details": (
                    "Unilateral space maintainers once per lifetime for lost "
                    "deciduous (baby) teeth. Bilateral space maintainers once "
                    "every 60 months for lost deciduous (baby) teeth"
                ),
                "frequency_source": "Space maintainers",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D2740",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "frequency_details": "N/A",
                "frequency_source": "Crowns and onlays over natural teeth",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D9944",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D9110",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D9310",
                "coverage_status": "COVERED",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D6750",
                "coverage_status": "COVERED",
                "coverage_percentage": "50%",
                "frequency": "N/A",
                "age_limit": "N/A",
            },
            {
                "procedure_code": "D9243",
                "coverage_status": "COVERED",
                "coverage_percentage": "0%",
            },
            {
                "procedure_code": "D4346",
                "coverage_status": "COVERED",
                "coverage_percentage": "100%",
            },
            {
                "procedure_code": "D0210",
                "coverage_status": "COVERED",
                "history": [{"service_date": "09/10/2026"}],
            },
            {
                "procedure_code": "D0330",
                "coverage_status": "COVERED",
                "history": [],
            },
        ])
        portal["benefit_categories"].append({
            "category": "RESTORATIVE",
            "services": [
                {
                    "procedure": "Amalgam (silver) fillings and composite (white) fillings",
                    "covered_at": "80%",
                    "frequency_limitations": "",
                },
                {
                    "procedure": (
                        "Crowns and onlays over natural teeth that are not part "
                        "of a bridge, build ups, posts and cores"
                    ),
                    "frequency_limitations": "Replacement limited to once every 60 months",
                },
                {
                    "procedure": "Partial and complete dentures",
                    "frequency_limitations": "Replacement limited to once every 60 months",
                },
                {
                    "procedure": "Periodontal maintenance following active therapy",
                    "frequency_limitations": (
                        "Once every 3 months; if alternating with routine cleanings, "
                        "there should be 3 months between a cleaning and the next maintenance procedure"
                    ),
                },
                {
                    "procedure": "Bridges and crowns over implants",
                    "frequency_limitations": "Replacement limited to once every 60 months",
                },
                {
                    "procedure": "Fluoride treatment",
                    "frequency_limitations": "For children under age 19 twice per calendar year",
                },
                {
                    "procedure": "Root planing and scaling",
                    "frequency_limitations": "Once per quadrant every 24 months",
                },
                {
                    "procedure": "Space maintainers",
                    "frequency_limitations": (
                        "Unilateral space maintainers once per lifetime for lost "
                        "deciduous (baby) teeth. Bilateral space maintainers once "
                        "every 60 months for lost deciduous (baby) teeth"
                    ),
                },
                {
                    "procedure": "Occlusal guards",
                    "frequency_limitations": "Replacement limited to once every 36 months",
                },
                {
                    "procedure": "Surgical placement of endosteal implant and abutment",
                    "frequency_limitations": "Replacement limited to once every 60 months",
                },
                {
                    "procedure": "Consultation",
                    "frequency_limitations": "",
                },
                {
                    "procedure": "Palliative treatment (minor procedures necessary to relieve acute pain)",
                    "frequency_limitations": "",
                },
                {
                    "procedure": "Gingivectomies",
                    "covered_at": "80%",
                    "frequency_limitations": "Once per site every 36 months",
                },
                {
                    "procedure": "General anesthesia or intravenous (I.V.) sedation for certain complex surgical procedures",
                    "covered_at": "80%",
                    "frequency_limitations": "None",
                },
            ],
        })

        self.assertEqual(procedure_value(portal, "D2950", "frequency_limit"), "1X60Months")
        self.assertEqual(procedure_value(portal, "D5212", "frequency_limit"), "1X60Months")
        self.assertEqual(procedure_value(portal, "D4910", "frequency_limit"), "1X3Months")
        self.assertIsNone(procedure_value(portal, "D6058", "frequency_limit"))
        self.assertEqual(procedure_value(portal, "D1206", "frequency_limit"), "2X1Year")
        self.assertEqual(procedure_value(portal, "D2160", "frequency_limit"), "No Frequency")
        self.assertEqual(procedure_value(portal, "D2391", "frequency_limit"), "No Frequency")
        for code in ("D2160", "D2391"):
            self.assertTrue(
                _compare(
                    "frequency",
                    "Frequency not available",
                    procedure_value(portal, code, "frequency_limit"),
                )[0],
                code,
            )
        self.assertEqual(procedure_value(portal, "D1206", "age_limit"), "19")
        self.assertEqual(procedure_value(portal, "D1510", "age_limit"), "99")
        self.assertEqual(procedure_value(portal, "D4341", "frequency_limit"), "1X24Months")
        self.assertEqual(procedure_value(portal, "D4342", "frequency_limit"), "1X24Months")
        self.assertEqual(procedure_value(portal, "D4346", "frequency_limit"), "1X36Months")
        self.assertEqual(procedure_value(portal, "D1510", "frequency_limit"), "1XLifetime")
        self.assertEqual(procedure_value(portal, "D1516", "frequency_limit"), "1X60Months")
        # The extension maps D6010 to this implant row (BENEFIT_SERVICES_BY_CODE),
        # so the server's fallback must read the same row.
        self.assertEqual(procedure_value(portal, "D6010", "frequency_limit"), "1X60Months")
        self.assertEqual(procedure_value(portal, "D2740", "frequency_limit"), "1X60Months")
        self.assertEqual(procedure_value(portal, "D9944", "frequency_limit"), "1X36Months")
        self.assertEqual(procedure_value(portal, "D9243", "frequency_limit"), "No Frequency")
        self.assertEqual(procedure_value(portal, "D9110", "frequency_limit"), "No Frequency")
        self.assertEqual(procedure_value(portal, "D9310", "frequency_limit"), "No Frequency")
        self.assertEqual(procedure_value(portal, "D6750", "frequency_limit"), "1X60Months")
        self.assertEqual(procedure_value(portal, "D6750", "coverage_percentage"), "50%")
        self.assertEqual(
            portal_value({"portal": ("code", "D9243", "D9223", "D9222")}, portal),
            "80%",
        )
        self.assertEqual(portal_value({"portal": ("code", "D4346")}, portal), "80%")
        self.assertEqual(
            portal_value({"portal": ("codefield", "history", "D0330")}, portal),
            "09/10/2026",
        )
        self.assertIsNone(procedure_value(portal, "D2980", "frequency_limit"))
        self.assertIsNone(procedure_value(portal, "D2980", "age_limit"))
        self.assertEqual(portal_value({"portal": "_d4341_quads"}, portal), "4")

        parsed = {"fields": {"d4910__freq": "1X3Years"}}
        result = compare_sabrina_to_portal(parsed, portal)
        d4910 = next(
            row for section in result["sections"] for row in section["rows"]
            if row["key"] == "d4910__freq"
        )
        self.assertEqual(d4910["portal"], "1X3Months")
        self.assertEqual(d4910["status"], "mismatch")

        parsed = {
            "fields": {
                "d1510__freq": "1XLifetime",
                "d9110__freq": "Frequency not available",
                "d9310__freq": "Frequency not available",
                "d2980__freq": "Frequency not available",
                "d4355__freq": "Frequency not available",
                "d6750__freq": "1X60Months",
            }
        }
        result = compare_sabrina_to_portal(parsed, portal)
        rows = {
            row["key"]: row
            for section in result["sections"]
            for row in section["rows"]
        }
        for key in (
            "d1510__freq", "d9110__freq", "d9310__freq", "d6750__freq",
        ):
            with self.subTest(key=key):
                self.assertEqual(rows[key]["status"], "match")
        for key in ("d2980__freq", "d4355__freq"):
            with self.subTest(key=key):
                self.assertEqual(rows[key]["status"], "not_in_portal")
                self.assertIsNone(rows[key]["portal"])

    def test_not_covered_code_lookup_maps_frequency_to_nc_only_for_explicit_status(self):
        portal = _portal()
        portal["benefit_coverage"]["procedures"].extend([
            {
                "procedure_code": "D6010",
                "coverage_status": "NOT COVERED",
                "coverage_percentage": "N/A",
                "frequency": "NC",
            },
            {
                "procedure_code": "D6100",
                "coverage_status": "NOT COVERED",
                "coverage_percentage": "N/A",
                "frequency": "N/A",
            },
            {
                "procedure_code": "D6057",
                "coverage_status": "SCRAPE ERROR",
                "coverage_percentage": "N/A",
                "frequency": "N/A",
            },
            {
                "procedure_code": "D6058",
                "coverage_status": "COVERED",
                "coverage_percentage": "50%",
                "frequency": "N/A",
            },
            {
                "procedure_code": "D5899",
                "coverage_status": "LOOKUP UNAVAILABLE",
                "coverage_percentage": "N/A",
                "frequency": "NC",
            },
            {
                "procedure_code": "D4381",
                "coverage_status": "LOOKUP UNAVAILABLE",
                "coverage_percentage": "N/A",
            },
            {
                "procedure_code": "D9230",
                "coverage_status": "LOOKUP UNAVAILABLE",
                "coverage_percentage": "N/A",
            },
        ])
        self.assertEqual(procedure_value(portal, "D6010", "frequency_limit"), "NC")
        self.assertEqual(procedure_value(portal, "D5899", "frequency_limit"), "NC")
        for code in ("D4381", "D5899", "D9230"):
            self.assertEqual(portal_value({"portal": ("code", code)}, portal), "0%")
        self.assertIsNone(procedure_value(portal, "D6100", "frequency_limit"))
        self.assertIsNone(procedure_value(portal, "D6057", "frequency_limit"))
        self.assertEqual(
            _compare(
                "frequency",
                "NC",
                procedure_value(portal, "D6010", "frequency_limit"),
            )[0],
            True,
        )
        self.assertIsNone(procedure_value(portal, "D6058", "frequency_limit"))

    def test_ddri_orthodontic_and_family_defaults_use_available_values(self):
        portal = _portal()
        portal["financials"]["deductibles"] = [
            item for item in portal["financials"]["deductibles"]
            if item["category"] != "Family Deductible"
        ]
        # No family row: the derived family deductible's met mirrors the
        # individual's ($20), as the extension's own derivation did.
        self.assertEqual(portal_value({"portal": "family_ded_paid"}, portal), "20.00")
        self.assertEqual(portal_value({"portal": "_ortho_ded"}, portal), "0")
        self.assertEqual(portal_value({"portal": "_ortho_ded_met"}, portal), "0")
        self.assertEqual(portal_value({"portal": "_ortho_age"}, portal), "99")
        self.assertEqual(portal_value({"portal": "_prev_in_max"}, portal), "Yes")
        portal["plan_details"]["preventive_in_yearly_max"] = "No"
        self.assertEqual(portal_value({"portal": "_prev_in_max"}, portal), "Yes")
        self.assertEqual(portal_value({"portal": "family_ded"}, portal), "150.00")
        portal["financials"]["deductibles"].append({
            "category": "Family Deductible",
            "total": "$0.00",
            "used": "$0.00",
        })
        self.assertEqual(portal_value({"portal": "family_ded"}, portal), "150.00")
        self.assertEqual(portal_value({"portal": "family_ded_paid"}, portal), "20.00")
        result = compare_sabrina_to_portal(
            {"fields": {"family_ded": "150"}},
            portal,
        )
        family_row = next(
            row for section in result["sections"] for row in section["rows"]
            if row["key"] == "family_ded"
        )
        self.assertEqual(family_row["portal"], "150.00")
        self.assertEqual(family_row["status"], "match")

        portal["plan_details"]["orthodontic_deductible_amount"] = "$100.00"
        portal["plan_details"]["orthodontic_deductible_met_amount"] = "$25.00"
        portal["plan_details"]["orthodontic_age_limit"] = "Under age 18"
        self.assertEqual(portal_value({"portal": "_ortho_ded"}, portal), "$100.00")
        self.assertEqual(portal_value({"portal": "_ortho_ded_met"}, portal), "$25.00")
        self.assertEqual(portal_value({"portal": "_ortho_age"}, portal), "Under age 18")
        family_entry = next(
            item for item in portal["financials"]["deductibles"]
            if item["category"] == "Family Deductible"
        )
        family_entry.update({"total": "$200.00", "used": "$15.00"})
        self.assertEqual(portal_value({"portal": "family_ded"}, portal), "200.00")
        self.assertEqual(portal_value({"portal": "family_ded_paid"}, portal), "15.00")

    def test_missing_oon_data_is_reviewed_in_comparison(self):
        portal = _portal()
        parsed = {
            "fields": {
                "patient_name": "Qurram Farooqi",
                "in_network": "In",
                "oon_benefits": "Yes",
                "cob": "Standard",
                "yearly_max": "1000",
                "indiv_ded": "50",
            },
            "labels_not_found": [],
            "marker_count": 20,
            "line_count": 100,
        }
        result = compare_sabrina_to_portal(parsed, portal)
        rows = {
            row["key"]: row
            for section in result["sections"]
            for row in section["rows"]
        }
        self.assertEqual(rows["in_network"]["status"], "match")
        self.assertEqual(rows["oon_benefits"]["status"], "not_in_portal")
        self.assertIsNone(rows["oon_benefits"]["portal"])
        self.assertEqual(rows["cob"]["status"], "match")
        self.assertEqual(rows["yearly_max"]["status"], "match")
        self.assertEqual(rows["indiv_ded"]["status"], "match")
        self.assertNotIn(rows["oon_benefits"], result["mismatches"])
        self.assertEqual(result["summary"]["not_in_portal"], 1)
        self.assertEqual(
            result["summary"]["not_stated"],
            sum(row["status"] == "not_stated" for row in rows.values()),
        )

    def test_oon_remains_unavailable_even_if_legacy_national_search_data_exists(self):
        portal = _portal()
        field = {"portal": "_oon_benefits"}
        self.assertIsNone(portal_value(field, portal))

        portal["national_search"] = {"identity_verified": True, "oon_benefits": "Yes"}
        self.assertIsNone(portal_value(field, portal))

        parsed = {
            "fields": {"oon_benefits": "Yes"},
            "labels_not_found": [],
            "marker_count": 20,
            "line_count": 100,
        }
        result = compare_sabrina_to_portal(parsed, portal)
        oon_row = next(
            row for section in result["sections"] for row in section["rows"]
            if row["key"] == "oon_benefits"
        )
        self.assertEqual(oon_row["status"], "not_in_portal")
        self.assertIsNone(oon_row["portal"])

    def test_stated_family_deductible_is_never_replaced(self):
        # The fixture states Family $150 / met $40 beside Individual $50 / met $20.
        portal = _portal()
        portal["financials"]["deductibles"][1].update({"total": "$100", "used": "$40"})
        self.assertEqual(portal_value({"portal": "family_ded"}, portal), "100.00")
        self.assertEqual(portal_value({"portal": "family_ded_paid"}, portal), "40.00")

    def test_no_deductible_rows_leave_family_deductible_unstated(self):
        # The extension once wrote "Family Deductible 0.00" for a page with no
        # deductible rows at all; nothing is derived without an individual amount.
        portal = _portal()
        portal["financials"]["deductibles"] = []
        self.assertIsNone(portal_value({"portal": "family_ded"}, portal))
        self.assertEqual(portal_value({"portal": "family_ded_paid"}, portal), "0")

    def test_implant_codes_read_their_benefit_row(self):
        # D6010 and D6057 share one benefit row; its frequency is used when the
        # export carries no frequency of its own for the code.
        portal = _portal()
        portal["benefit_categories"].append({
            "category": "IMPLANTS",
            "services": [{
                "procedure": "Surgical placement of endosteal implant and abutment",
                "covered_at": "50%",
                "deductible_applies": "Yes",
                "waiting_period": "None",
                "frequency_limitations": "Once per tooth every 5 years",
            }],
        })
        for code in ("D6010", "D6057"):
            self.assertEqual(procedure_value(portal, code, "frequency_limit"), "1X5Year")

    def test_fill_form_prefill_refuses_ddri_with_a_422_error(self):
        # Sabrina prefill reads carriers through _portal_breakdown; DD RI must
        # refuse with a ValueError (HTTP 422), not an AttributeError (HTTP 500).
        from smile_partners.sabrina import prefill
        with self.assertRaisesRegex(ValueError, "Rhode Island"):
            prefill.portal_values(_portal(), "In")


if __name__ == "__main__":
    unittest.main()
