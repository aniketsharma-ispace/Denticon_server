"""
Delta Dental of Missouri: the Smile Partners audit reads extension 1.67+
single-network exports (11/27). Synthetic data only.

From 1.67 the DD MO pop-up picks PPO / Premier / Non-participating before the
crawl and each coverage row holds that network's figures alone, as
`benefit_pct` / `deductible_applies`, in place of the ppo_ / premier_ / oon_
columns. The audit used to read only those columns, so a 1.67 export came out
with no percentages and no deductible flags.

Run:  python tests/test_ddmo_single_network.py
"""

import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sabrina.smile_partners.carriers.delta_mo import audit
from sabrina.smile_partners.carriers.delta_mo import portal as mo_portal
from sabrina.smile_partners.carriers.delta_mo.rules import _mo_identity_gate
from sabrina.smile_partners.portals.delta_mo import _is_dd_mo_portal, _normalize_dd_mo_portal

# (code, benefit group, PPO %, Premier %, out-of-network %, deductible applies PPO / Premier / OON)
_ROWS = [
    ("D0120", "DIAGNOSTIC & PREVENTIVE", 100, 100, 80, "No", "No", "Yes"),
    ("D2391", "BASIC", 80, 70, 50, "Yes", "Yes", "Yes"),
    ("D2740", "MAJOR", 50, 50, 0, "Yes", "No", "Yes"),
]
_NETWORKS = ("ppo", "premier", "oon")


def _older_export():
    """A three-column export, as extension 1.66 and before produced it."""
    return {
        "carrier": "DELTA_MO",
        "source": "Delta Dental of Missouri provider portal",
        "extracted_at": "2026-11-27T10:00:00Z",
        "member_details": {
            "patient_name": "TEST PATIENT", "dob": "01/02/1980", "relationship": "Self",
            "eligible": "Yes", "group_number": "12345", "group_name": "TEST GROUP",
            "program_type": "PPO", "benefit_cycle": "Calendar Year 01/01",
            "has_ortho": "No",
        },
        "maximum_and_deductible": {
            "individual_regular_annual_maximum": {"amount": 2000, "used": 0, "remaining": 2000},
            "individual_regular_deductible": {"amount": 50, "met": 0, "remaining": 50},
        },
        "coverage_levels": [
            {"code": code, "listed": True, "description": "", "benefit_group": group,
             "frequency": "", "age_limit": "", "other_limitations": "",
             "ppo_pct": ppo, "premier_pct": premier, "oon_pct": oon,
             "ppo_deductible_applies": d_ppo, "premier_deductible_applies": d_prem,
             "oon_deductible_applies": d_oon}
            for code, group, ppo, premier, oon, d_ppo, d_prem, d_oon in _ROWS
        ],
    }


def _export_167(choice, paying=("ppo", "premier", "oon")):
    """The same member as content_DD_MO.js 1.67+ exports it for one network."""
    raw = copy.deepcopy(_older_export())
    for row in raw["coverage_levels"]:
        row["benefit_pct"] = row.pop(f"{choice}_pct")
        row["deductible_applies"] = row.pop(f"{choice}_deductible_applies")
        for net in _NETWORKS:
            row.pop(f"{net}_pct", None)
            row.pop(f"{net}_deductible_applies", None)
    raw["network_choice"] = choice
    raw["selected_network"] = {"ppo": "PPO Dentist", "premier": "Premier Dentist",
                               "oon": "Nonparticipating Dentist"}[choice]
    raw["networks_paying"] = list(paying)
    return raw


def _normalized(raw, sheet_network):
    return _normalize_dd_mo_portal({**raw, "_mo_network": sheet_network})


def _procedures(norm):
    return {p["procedure_code"]: p for p in norm["benefit_coverage"]["procedures"]}


# The sheet's In Network / Fee Schedule that select each network in the audit.
_SHEETS = {"ppo": ("In", ""), "premier": ("In", "GA - DD GP Premier B"), "oon": ("Out", "")}


def _sheet(sheet_network):
    in_network, fee = _SHEETS[sheet_network]
    return {"fields": {"patient_name": "TEST PATIENT", "patient_dob": "01/02/1980",
                       "group_number": "12345", "in_network": in_network},
            "fee_schedule": fee, "eligibility": None, "text": ""}


class SyntheticExportsAreDdMo(unittest.TestCase):
    def test_both_shapes_are_recognised(self):
        self.assertTrue(_is_dd_mo_portal(_older_export()))
        for choice in _NETWORKS:
            self.assertTrue(_is_dd_mo_portal(_export_167(choice)))


class OlderExportsUnchanged(unittest.TestCase):
    """A three-column export is read exactly as before: the sheet's network column."""

    def test_percentage_from_the_sheets_network_column(self):
        for i, net in enumerate(_NETWORKS):
            procs = _procedures(_normalized(_older_export(), net))
            for row in _ROWS:
                self.assertEqual(procs[row[0]]["benefit_level"], f"{row[2 + i]}%", (net, row[0]))

    def test_deductible_flag_stays_the_ppo_column(self):
        # Long-standing behaviour for the older shape, kept as it was.
        for net in _NETWORKS:
            procs = _procedures(_normalized(_older_export(), net))
            for row in _ROWS:
                self.assertEqual(procs[row[0]]["deductible"], row[5], (net, row[0]))

    def test_no_export_network_recorded(self):
        meta = _normalized(_older_export(), "ppo")["_mo_meta"]
        self.assertEqual(meta["export_network"], "")
        self.assertIsNone(meta["networks_paying"])


class SingleNetworkExportsRead(unittest.TestCase):
    """A 1.67+ export: the picked network's figures, the only ones it has."""

    def test_percentages_and_deductible_flags_present(self):
        for i, choice in enumerate(_NETWORKS):
            procs = _procedures(_normalized(_export_167(choice), choice))
            for row in _ROWS:
                self.assertEqual(procs[row[0]]["benefit_level"], f"{row[2 + i]}%", (choice, row[0]))
                self.assertEqual(procs[row[0]]["deductible"], row[5 + i], (choice, row[0]))

    def test_matches_the_older_export_of_the_same_member(self):
        # Every code's percentage, frequency, age and history agree with the
        # three-column export read under the same network.
        for choice in _NETWORKS:
            old = _procedures(_normalized(_older_export(), choice))
            new = _procedures(_normalized(_export_167(choice), choice))
            for code in old:
                for key in ("benefit_level", "frequency_limit", "age_limit",
                            "late_date_of_service", "mo_listed"):
                    self.assertEqual(old[code][key], new[code][key], (choice, code, key))

    def test_out_of_network_column_only_from_an_oon_export(self):
        services = {c["category"]: c for c in
                    _normalized(_export_167("ppo"), "ppo")["metlife_data"]["covered_services"]}
        self.assertEqual(services["BASIC"]["in_network"], "80%")
        self.assertEqual(services["BASIC"]["out_of_network"], "")
        services = {c["category"]: c for c in
                    _normalized(_export_167("oon"), "oon")["metlife_data"]["covered_services"]}
        self.assertEqual(services["BASIC"]["out_of_network"], "50%")

    def test_export_network_recorded(self):
        meta = _normalized(_export_167("premier", paying=("ppo", "premier")), "premier")["_mo_meta"]
        self.assertEqual(meta["export_network"], "premier")
        self.assertEqual(meta["networks_paying"], ["ppo", "premier"])


class OonBenefits(unittest.TestCase):
    """OON Benefits for an in-network export comes from networks_paying."""

    def _answer(self, raw, net):
        return mo_portal._portal_oon_benefits({}, _normalized(raw, net))

    def test_in_network_export_pays_out_of_network(self):
        self.assertEqual(self._answer(_export_167("ppo"), "ppo"), "Yes")
        self.assertEqual(self._answer(_export_167("premier"), "premier"), "Yes")

    def test_in_network_export_does_not_pay_out_of_network(self):
        self.assertEqual(self._answer(_export_167("ppo", paying=("ppo", "premier")), "ppo"), "No")

    def test_oon_and_older_exports_answer_from_their_figures(self):
        self.assertEqual(self._answer(_export_167("oon", paying=("ppo",)), "oon"), "Yes")
        self.assertEqual(self._answer(_older_export(), "ppo"), "Yes")


class IdentityGateNetwork(unittest.TestCase):
    """A 1.67+ export must hold the network the sheet records (as DD Toolkit)."""

    def _gate(self, raw, sheet_network):
        return _mo_identity_gate(_sheet(sheet_network), _normalized(raw, sheet_network))

    def test_matching_network_passes(self):
        for choice in _NETWORKS:
            ok, issues = self._gate(_export_167(choice), choice)
            self.assertTrue(ok, (choice, issues))

    def test_other_network_is_refused_naming_the_popup_choice(self):
        wants = {"ppo": "PPO", "premier": "Premier", "oon": "Non-participating"}
        for choice in _NETWORKS:
            for sheet_network in _NETWORKS:
                if sheet_network == choice:
                    continue
                ok, issues = self._gate(_export_167(choice), sheet_network)
                self.assertFalse(ok, (choice, sheet_network))
                self.assertIn(f"re-export choosing {wants[sheet_network]}", " ".join(issues))

    def test_older_export_has_no_network_check(self):
        for sheet_network in _NETWORKS:
            ok, issues = self._gate(_older_export(), sheet_network)
            self.assertTrue(ok, (sheet_network, issues))


class WholeAudit(unittest.TestCase):
    """Through compare_sabrina_to_portal, the entry point the server calls."""

    def _audit(self, raw, sheet_network):
        result = audit.compare_sabrina_to_portal(_sheet(sheet_network), raw)
        return result, [r for s in result["sections"] for r in s["rows"]]

    def test_matching_export_compares_its_percentages(self):
        result, rows = self._audit(_export_167("premier"), "premier")
        self.assertTrue(result["diagnostics"]["identity"]["valid"])
        stated = {r["portal"] for r in rows if r.get("group") and str(r.get("portal") or "").endswith("%")}
        self.assertIn("70%", stated)            # D2391's Premier figure

    def test_wrong_network_export_compares_nothing(self):
        result, rows = self._audit(_export_167("ppo"), "premier")
        self.assertFalse(result["diagnostics"]["identity"]["valid"])
        self.assertEqual({r["status"] for r in rows}, {"not_comparable"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
