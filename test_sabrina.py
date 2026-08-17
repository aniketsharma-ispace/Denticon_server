"""
REGRESSION TESTS — SABRINA PDF ↔ PORTAL FIELD AUDIT
═══════════════════════════════════════════════════════════════════════════════

Run:  venv\\Scripts\\python.exe test_sabrina.py

Checks, in order:
  1. Every one of the 74 audited fields is read correctly out of a real Sabrina
     export (Material/Comparison/Metlife.pdf — patient Jack Oung, MetLife).
  2. Detection: a Sabrina sheet is recognized, a carrier PDF is not.
  3. Value normalization and the comparison rules (formatting differences must
     not be reported as data conflicts).
  4. The comparison runs against a real portal export without crashing.

Tests whose input file is absent SKIP rather than fail, matching
test_regression.py, so the suite stays runnable on a fresh checkout.
"""

import os
import sys

import sabrina_compare as sc

BASE = os.path.dirname(os.path.abspath(__file__))
SABRINA_PDF = os.path.join(BASE, "Material", "Comparison", "Metlife.pdf")
DD_PORTAL_DIR = os.path.join(BASE, "Material", "Comparison", "DD INS")

_passed = _failed = _skipped = 0


def check(name, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
    else:
        _failed += 1
        print(f"  [FAIL] {name}\n         got  {got!r}\n         want {want!r}")


def check_true(name, cond, detail=""):
    check(name, bool(cond) if not detail else (bool(cond), detail), True if not detail else (True, detail))


def skip(name, why):
    global _skipped
    _skipped += 1
    print(f"  [SKIP] {name} — {why}")


# ══════════════════════════════════════════════════════════════════════════════
#  1. REAL SABRINA EXPORT — every field, transcribed from the PDF itself
# ══════════════════════════════════════════════════════════════════════════════
#
# Layout notes this pins down (all three were wrong in the first draft):
#   · Demographics/Coverage blocks print the label ABOVE its value.
#   · "Paid to Date($)" appears three times — each belongs to the metric it
#     follows (yearly max, individual deductible, family deductible).
#   · Benefit Details is a 6-column table (Benefit Name | Frequency |
#     Percentage | Coverage | Age Limit | History) flattened to one cell per
#     line with EMPTY CELLS OMITTED, so a percentage may be preceded by a
#     Frequency cell and followed by Age Limit / History cells.

EXPECTED_FIELDS = {
    # Patient / Subscriber
    "patient_name":     "Jack Oung",
    "patient_dob":      "08/01/1994",
    "member_id":        "861783",
    "subscriber_name":  "Jack Oung",
    "subscriber_dob":   "08/01/1994",
    # Insurance
    "ins_name":         "Metlife",
    "group_name":       "CARDINAL HEALTH, INC.",
    "group_number":     "84999",
    "ins_address":      "P O BOX 981282 , , EL PASO, TX - 79998",   # wraps 2 lines
    "payor_id":         "65978",
    "in_network":       "In",                                        # not "Yes"
    "oon_benefits":     "Yes",
    "eff_date":         "01/01/2020",
    "plan_year_start":  "January",
    # Maximums & deductibles
    "yearly_max":       "2000",
    "yearly_max_paid":  "1065.50",
    "indiv_ded":        "50",
    "indiv_ded_paid":   "50",
    "family_ded":       "100",
    "family_ded_paid":  "50",
    "ded_prev":         "No",
    "ded_diag":         "No",
    # Plan provisions
    "waiting_period":   "No",
    "cob":              "Standard",
    "pct_prev":         "100%",
    "pct_basic":        "80%",
    "pct_major":        "50%",
    # Orthodontics
    "ortho_max":        "1500",
    "ortho_max_paid":   "0",
    "ortho_ded":        "0",
    "ortho_ded_paid":   "0",
    # Clauses
    "missing_tooth":    "No",
    "prev_in_max":      "Yes",
    # Coverage by CDT code — the Percentage column, never Frequency/Age/History
    "d0220": "100%",   # row: D0220 PAs / No Frequency / 100%
    "d0120": "100%",   # row: D0120 Periodic Exam / 2X1Year / 100% / 01/28/2026
    "d0140": "100%",
    "d0150": "100%",   # sheet label is "D0150 Diagnostic Exam Comp"
    "d0210": "100%",
    "d0330": "100%",
    "d0274": "100%",
    "d1110": "100%",
    "d1206": "100%",   # row also carries Age Limit 19 + History NH
    "d1208": "100%",
    "d1351": "100%",
    "d1510": "100%",
    "d2160": "80%",
    "d2391": "80%",
    "d2740": "50%",
    "d2950": "50%",
    "d2980": "80%",
    "d3310": "80%",    # row has NO frequency cell
    "d4260": "50%",
    "d4341": "80%",
    "d4346": "100%",
    "d4355": "80%",    # frequency "1XLifetime"
    "d4381": "80%",
    "d4910": "80%",
    "d5110": "50%",
    "d5212": "50%",
    "d5899": "0",      # row: D5899 Prosth Removable / NC / 0
    "d6010": "50%",
    "d6750": "50%",
    "d7140": "80%",
    "d7210": "80%",
    "d9110": "100%",
    "d9230": "0",      # percentage is a bare 0
    "d9243": "50%",
    "d9944": "50%",
    "ortho_coverage": "50%",   # row also carries Age Limit 19
    "d8090": "50%",
    "d5995": "0",      # row: D5995 / NC / 0
    "d6057": "50%",
    "d6058": "50%",
    "d9310": "80%",
}

print("── 1. REAL SABRINA EXPORT (Jack Oung / MetLife) ──")
if not os.path.exists(SABRINA_PDF):
    skip("real Sabrina PDF parse", f"{SABRINA_PDF} not present")
    parsed = None
else:
    with open(SABRINA_PDF, "rb") as fh:
        parsed = sc.parse_sabrina_pdf(fh.read())

    check("detected as a Sabrina sheet", sc.is_sabrina_pdf(parsed["text"]), True)
    check("all spec'd labels found on the sheet", parsed["labels_not_found"], [])

    fields = parsed["fields"]
    check("field spec covers exactly the audited set", len(fields), len(EXPECTED_FIELDS))
    for key, want in EXPECTED_FIELDS.items():
        check(f"field {key}", fields.get(key), want)

    read = sum(1 for v in fields.values() if not sc._blank(v))
    check("every field read (none blank)", read, len(EXPECTED_FIELDS))


# ══════════════════════════════════════════════════════════════════════════════
#  2. DETECTION
# ══════════════════════════════════════════════════════════════════════════════

print("── 2. DETECTION ──")
check("carrier PDF text is not taken for Sabrina",
      sc.is_sabrina_pdf(
          "Delta Dental of Wisconsin\nEligibility and Accumulations\n"
          "Annual Maximum $1500.00 Deductible $50.00\n"
          "Preventive History - Last Date of Service\n"), False)
check("empty text is not Sabrina", sc.is_sabrina_pdf(""), False)


# ══════════════════════════════════════════════════════════════════════════════
#  3. NORMALIZATION + COMPARISON RULES
# ══════════════════════════════════════════════════════════════════════════════

print("── 3. NORMALIZATION & COMPARISON ──")

# Sabrina prints bare numbers; portals print "$ 2,000.00 total".
check("money: bare 2000 vs '$ 2,000.00 total'",
      sc._compare("money", "2000", "$ 2,000.00 total")[0], True)
check("money: 1065.50 vs 1065.5", sc._compare("money", "1065.50", "1065.5")[0], True)
check("money: real difference is caught",
      sc._compare("money", "1500", "2000")[0], False)
check("money: Unlimited matches the 99999 convention",
      sc._compare("money", "Unlimited", "99999")[0], True)

check("pct: '80%' vs '80'", sc._compare("pct", "80%", "80")[0], True)
check("pct: bare 0 vs 'Not Covered'", sc._compare("pct", "0", "Not Covered")[0], True)
check("pct: 'Covered' alone is not comparable",
      sc._compare("pct", "100%", "Covered")[0], None)
check("pct: real difference is caught", sc._compare("pct", "90%", "100%")[0], False)

check("yesno: Sabrina 'In' means in-network",
      sc._compare("yesno", "In", "Yes")[0], True)
check("yesno: 'Out' means not in-network",
      sc._compare("yesno", "Out", "No")[0], True)
check("yesno: In vs No is a real conflict",
      sc._compare("yesno", "In", "No")[0], False)
check("yesno: N/A is not comparable", sc._compare("yesno", "N/A", "Yes")[0], None)

check("date: 01/01/2020 vs Jan 01, 2020",
      sc._compare("date", "01/01/2020", "Jan 01, 2020")[0], True)
check("date: real difference is caught",
      sc._compare("date", "01/01/2020", "01/01/2024")[0], False)
check("month: 'January' vs '01/2026'", sc._compare("month", "January", "01/2026")[0], True)

check("id: '84999' vs '084999' is formatting only",
      sc._compare("id", "84999", "084999")[0], True)
check("id: different ids are caught", sc._compare("id", "84999", "85000")[0], False)

check("name: 'Jack Oung' vs 'OUNG, JACK'",
      sc._compare("name", "Jack Oung", "OUNG, JACK")[0], True)
check("name: middle name on one side only",
      sc._compare("name", "Jack A Oung", "Jack Oung")[0], True)
check("name: different people are caught",
      sc._compare("name", "Jack Oung", "Jane Smith")[0], False)

check("address: Sabrina's spacing vs the portal's",
      sc._compare("address", "P O BOX 981282 , , EL PASO, TX - 79998",
                  "PO Box 981282, El Paso, TX 79998")[0], True)
check("address: a different PO box is caught",
      sc._compare("address", "P O BOX 981282 , , EL PASO, TX - 79998",
                  "PO Box 14079, Lexington, KY 40512")[0], False)

check("text: 'Metlife' vs '(IN) MetLife(TX)- PO Box 981282- 79998'",
      sc._compare("text", "Metlife", "(IN) MetLife(TX)- PO Box 981282- 79998")[0], True)

# A value the portal never stated must never be reported as a mismatch.
check("portal silence is not a mismatch", sc._compare("money", "2000", "")[0], None)
check("portal silence is not a mismatch (pct)", sc._compare("pct", "80%", None)[0], None)


# ══════════════════════════════════════════════════════════════════════════════
#  4. FULL COMPARISON AGAINST A REAL PORTAL EXPORT
# ══════════════════════════════════════════════════════════════════════════════

print("── 4. COMPARISON END-TO-END ──")
if parsed is None:
    skip("comparison end-to-end", "Sabrina PDF not present")
else:
    # Self-consistency: comparing the sheet against a portal payload built from
    # its own values must yield zero mismatches.
    f = parsed["fields"]
    mirror = {
        "metlife_data": {
            "patient": {"name": f["patient_name"], "dob": f["patient_dob"],
                        "relationship": "Subscriber"},
            "plan_details": {"subscriber_id": f["member_id"],
                             "employer_group": f["group_name"],
                             "group_number": f["group_number"],
                             "start_date": f["eff_date"], "network": "PPO"},
            "financials": {
                "annual_max":     {"total": f["yearly_max"],
                                   "remaining": str(float(f["yearly_max"]) - float(f["yearly_max_paid"]))},
                "deductible_ind": {"total": f["indiv_ded"],  "used": f["indiv_ded_paid"]},
                "deductible_fam": {"total": f["family_ded"], "used": f["family_ded_paid"]},
                "ortho_lifetime": {"total": f["ortho_max"],  "used": f["ortho_max_paid"]},
            },
            "covered_services": [], "provisions": [],
        },
        "benefit_coverage": {"procedures": [
            {"procedure_code": code, "benefit_level": f[key]}
            for key, code in [("d0120", "D0120"), ("d0140", "D0140"), ("d0150", "D0150"),
                              ("d0210", "D0210"), ("d0330", "D0330"), ("d0274", "D0274"),
                              ("d1110", "D1110"), ("d1206", "D1206"), ("d1208", "D1208"),
                              ("d1351", "D1351"), ("d1510", "D1510"), ("d2160", "D2160"),
                              ("d2391", "D2391"), ("d2740", "D2740"), ("d2950", "D2950"),
                              ("d3310", "D3310"), ("d4260", "D4260"), ("d4341", "D4341"),
                              ("d4910", "D4910"), ("d5110", "D5110"), ("d6010", "D6010"),
                              ("d7140", "D7140"), ("d9310", "D9310")]
        ]},
        "carrier_information": {"name": "MetLife", "payer_id": f["payor_id"]},
    }
    result = sc.compare_sabrina_to_portal(parsed, mirror)
    s = result["summary"]
    check("mirrored portal → zero mismatches", s["mismatches"], 0)
    check_true("mirrored portal → fields actually compared", s["compared"] >= 25,
               f"compared={s['compared']}")
    check("patient block is populated", result["patient"]["name"], "Jack Oung")
    check("every row carries a status",
          all(r["status"] for sec in result["sections"] for r in sec["rows"]), True)

    # Seed two disagreements and confirm exactly those are reported.
    import copy
    tampered = copy.deepcopy(mirror)
    tampered["metlife_data"]["financials"]["annual_max"]["total"] = "2500"
    for proc in tampered["benefit_coverage"]["procedures"]:
        if proc["procedure_code"] == "D2740":
            proc["benefit_level"] = "70%"
    res2 = sc.compare_sabrina_to_portal(parsed, tampered)
    keys = {r["key"] for r in res2["mismatches"]}
    check("seeded disagreements are the only mismatches",
          keys, {"yearly_max", "yearly_max_paid", "pct_major", "d2740"})
    check("yearly max flagged as critical",
          next(r["critical"] for r in res2["mismatches"] if r["key"] == "yearly_max"), True)

# Real portal exports of a different shape must not crash the portal normalizer.
if not os.path.isdir(DD_PORTAL_DIR):
    skip("real Delta Dental portal export smoke test", "DD INS folder not present")
elif parsed is None:
    skip("real Delta Dental portal export smoke test", "Sabrina PDF not present")
else:
    import glob
    import json
    dd_files = [p for p in glob.glob(os.path.join(DD_PORTAL_DIR, "*.json"))
                if "DeepAudit" not in os.path.basename(p)]
    if not dd_files:
        skip("real Delta Dental portal export smoke test", "no portal JSON found")
    else:
        ok = 0
        for path in dd_files:
            with open(path, encoding="utf-8") as fh:
                portal = json.load(fh)
            out = sc.compare_sabrina_to_portal(parsed, portal)
            assert out["summary"]["total_fields"] == len(EXPECTED_FIELDS)
            ok += 1
        check(f"Delta Dental portal exports normalize without error ({ok} files)",
              ok, len(dd_files))


print(f"\n{_passed + _failed} checks: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
