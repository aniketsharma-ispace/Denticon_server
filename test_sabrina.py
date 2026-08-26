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

# Windows consoles default to cp1252 and cannot encode the section rules below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE = os.path.dirname(os.path.abspath(__file__))
SABRINA_PDF = os.path.join(BASE, "Material", "Comparison", "Metlife.pdf")
SABRINA_PDF_2 = os.path.join(BASE, "Material", "Comparison", "Metlife - 81986.pdf")
PORTAL_JSON_2 = os.path.join(BASE, "Material", "Comparison",
                             "tudor_piroteala_metlife_audit (1).json")
DD_PORTAL_DIR = os.path.join(BASE, "Material", "Comparison", "DD INS")

_passed = _failed = _skipped = 0

# The spec also carries generated Frequency / Age Limit / History rows for every
# CDT code (flagged `derived`, read from a row's cells rather than a label of
# their own). The per-field expectations below cover the label-parsed core; the
# generated rows are asserted separately in section 1c.
CORE_KEYS = [f["key"] for f in sc._SPEC if not f.get("derived")]


def core_only(fields):
    return {k: v for k, v in fields.items() if k in CORE_KEYS}


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
    "posterior_composite_downgrade": "No",
    "porcelain_posterior_downgrade": "Yes",
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
    check("field spec covers exactly the audited set",
          len(core_only(fields)), len(EXPECTED_FIELDS))
    for key, want in EXPECTED_FIELDS.items():
        check(f"field {key}", fields.get(key), want)

    read = sum(1 for v in core_only(fields).values() if not sc._blank(v))
    check("every core field read (none blank)", read, len(EXPECTED_FIELDS))

    # All four Benefit Details columns, as printed on Jack's sheet.
    ROWS_1 = {
        "d0120": ("2X1Year", "100%", None, "01/28/2026"),
        "d0220": ("No Frequency", "100%", None, None),
        "d1206": ("2X1Year", "100%", "19", "NH"),
        "d1351": ("1X36Months", "100%", "99", "NH"),
        "d1510": ("No Frequency", "100%", "99", None),
        "d2740": ("1X5Years", "50%", None, None),
        "d3310": (None, "80%", None, None),           # row has no frequency cell
        "d4341": ("No Frequency", "80%", "4", "NH"),   # the "4" is quadrants
        "d4355": ("1XLifetime", "80%", None, None),
        "d4910": ("4X1Year", "80%", None, "01/29/2026"),
        "d5899": ("NC", "0", None, None),
        "d9944": ("1X24Months", "50%", None, None),
        "ortho_coverage": (None, "50%", "19", None),
        "d9310": ("2X1Year", "80%", None, None),
    }
    for key, want in ROWS_1.items():
        row = parsed["benefit_rows"].get(key, {})
        check(f"benefit row {key}",
              (row.get("frequency"), row.get("percentage"),
               row.get("age_limit"), row.get("history")), want)


# ══════════════════════════════════════════════════════════════════════════════
#  1b. SECOND REAL EXPORT — wrapped table cells + a masked portal id
# ══════════════════════════════════════════════════════════════════════════════
#
# This export (Tudor Piroteala, MetLife) wraps cell text across lines, so the
# Frequency cell "No Frequency" arrives as "No" + "Frequency". The stray
# fragment collides with the table's own "Frequency" column header, and before
# _reflow_wrapped() it ended the value hunt and left 8 rows blank:
#   D0220, D1510, D4260, D4341, D4381, D9110, D9944, D9310
# The portal states 100% for every one of them, so each blank surfaced in the UI
# as "BLANK IN SABRINA" against a real portal value.

EXPECTED_2 = {
    "patient_name": "Tudor Piroteala", "patient_dob": "05/18/1987",
    "member_id": "833926200", "subscriber_name": "Tudor Piroteala",
    "subscriber_dob": "05/18/1987",
    "ins_name": "Metlife", "group_name": "NOVELIS CORPORATION",
    "group_number": "303836", "payor_id": "65978",
    "ins_address": "P O BOX 981282 , , EL PASO, TX - 79998",   # wraps 2 lines
    "in_network": "In", "oon_benefits": "Yes",
    "eff_date": "01/01/2024", "plan_year_start": "January",
    "yearly_max": "2500", "yearly_max_paid": "138.00",
    "indiv_ded": "0", "indiv_ded_paid": "0",
    "family_ded": "0", "family_ded_paid": "0",
    "ded_prev": "No", "ded_diag": "No",
    "waiting_period": "No", "cob": "Standard",
    "pct_prev": "100%", "pct_basic": "100%", "pct_major": "100%",
    "ortho_max": "2000", "ortho_max_paid": "543.20",
    "ortho_ded": "0", "ortho_ded_paid": "0",
    "missing_tooth": "No", "prev_in_max": "Yes",
    "posterior_composite_downgrade": "Yes",   # sheet answers the two
    "porcelain_posterior_downgrade": "No",    # alternate-benefit questions
    # The eight rows whose Frequency cell wrapped — each must be the
    # Percentage, never the wrapped fragment and never the Age Limit.
    "d0220": "100%",   # "No" + "Frequency" / 100%
    "d1510": "100%",   # "No" + "Frequency" / 100% / 14   <- not the age 14
    "d4260": "100%",
    "d4341": "100%",   # "No" + "Frequency" / 100% / 4 / NH
    "d4381": "100%",
    "d9110": "100%",
    "d9944": "100%",
    "d9310": "100%",
    # ...and the rest of the sheet
    "d0120": "100%", "d0140": "100%", "d0150": "100%", "d0210": "100%",
    "d0330": "100%", "d0274": "100%", "d1110": "100%", "d1206": "100%",
    "d1208": "100%", "d1351": "100%", "d2160": "100%", "d2391": "100%",
    "d2740": "100%", "d2950": "100%", "d2980": "80%", "d3310": "100%",
    "d4346": "100%", "d4355": "100%", "d4910": "100%", "d5110": "80%",
    "d5212": "80%", "d5899": "0", "d6010": "80%", "d6750": "80%",
    "d7140": "100%", "d7210": "100%", "d9230": "0", "d9243": "100%",
    "ortho_coverage": "80%", "d8090": "80%", "d5995": "0",
    "d6057": "80%", "d6058": "80%",
}

print("── 1b. SECOND REAL EXPORT (Tudor Piroteala / MetLife) ──")
if not os.path.exists(SABRINA_PDF_2):
    skip("second Sabrina PDF parse", f"{SABRINA_PDF_2} not present")
    parsed2 = None
else:
    with open(SABRINA_PDF_2, "rb") as fh:
        parsed2 = sc.parse_sabrina_pdf(fh.read())
    check("detected as a Sabrina sheet", sc.is_sabrina_pdf(parsed2["text"]), True)
    check("all spec'd labels found", parsed2["labels_not_found"], [])
    f2 = parsed2["fields"]
    check("spec fully covered by expectations", len(core_only(f2)), len(EXPECTED_2))
    for key, want in EXPECTED_2.items():
        check(f"[2] field {key}", f2.get(key), want)
    check("[2] no core field left blank",
          sum(1 for v in core_only(f2).values() if not sc._blank(v)), len(EXPECTED_2))

    # Against this patient's real portal export the sheet agrees completely —
    # the two mismatches the UI first reported were both artefacts:
    #   · Member ID#  — the portal masks it ("XXXXXXX6200")
    #   · Missing Tooth Clause — the congenital answer was read as the general one
    if not os.path.exists(PORTAL_JSON_2):
        skip("[2] comparison against real portal export", "portal JSON not present")
    else:
        import json as _json
        with open(PORTAL_JSON_2, encoding="utf-8") as fh:
            portal2 = _json.load(fh)
        res = sc.compare_sabrina_to_portal(parsed2, portal2)
        rows = {r["key"]: r for sec in res["sections"] for r in sec["rows"]}
        check("[2] masked portal member id is not a mismatch",
              rows["member_id"]["status"], "match")
        check("[2] masked member id is explained",
              "masked" in rows["member_id"]["note"], True)
        check("[2] missing tooth clause reads the general answer",
              (rows["missing_tooth"]["portal"], rows["missing_tooth"]["status"]),
              ("No", "match"))
        for key in ("d0220", "d1510", "d4260", "d4341", "d4381",
                    "d9110", "d9944", "d9310"):
            check(f"[2] wrapped-frequency row {key} compares",
                  rows[key]["status"], "match")
        # Coordination Of Benefits and OON Benefits are stated in this export,
        # just not as plain fields — the first in a provision, the second in the
        # per-category covered_services rows. Both must be compared, not
        # written off as "not on portal".
        check("[2] coordination of benefits is read from the provisions",
              (rows["cob"]["portal"], rows["cob"]["status"]), ("Standard", "match"))
        check("[2] OON benefits derived from covered_services",
              (rows["oon_benefits"]["portal"], rows["oon_benefits"]["status"]),
              ("Yes", "match"))

        # These genuinely are absent from this export and must stay reported as
        # such rather than guessed at:
        #   Group Number  — captured only by extension builds after 2026-07-29
        #   the deductibles — the portal itself reports "N/A"
        #   D2980/D5212/D5899/D5995 — codes no batch requested before BATCH_8
        for key in ("group_number", "indiv_ded", "family_ded",
                    "d2980", "d5212", "d5899", "d5995"):
            check(f"[2] {key} honestly reported as absent",
                  rows[key]["status"], "not_in_portal")

        check("[2] whole sheet agrees with the portal",
              res["summary"]["mismatches"], 0)
        # Nothing is reported blank any more. The three rows that used to be
        # (D1110 age, D3310 frequency, D9230 frequency) are columns MetLife does
        # not supply for those codes, so they are no longer generated at all.
        check("[2] nothing reported blank on the sheet",
              sorted(r["key"] for sec in res["sections"] for r in sec["rows"]
                     if r["status"] == "missing_in_sabrina"), [])

        # The two alternate-benefit questions now compare.
        check("[2] posterior composites question compares",
              (rows["posterior_composite_downgrade"]["portal"],
               rows["posterior_composite_downgrade"]["status"]), ("Yes", "match"))
        check("[2] posterior crowns question compares",
              (rows["porcelain_posterior_downgrade"]["portal"],
               rows["porcelain_posterior_downgrade"]["status"]), ("No", "match"))

        # Same carrier stated two ways is not a mismatch.
        check("[2] insurance name matches on the carrier",
              rows["ins_name"]["status"], "match")


# ══════════════════════════════════════════════════════════════════════════════
#  1c. BENEFIT DETAILS — Frequency, Percentage, Age Limit, History
# ══════════════════════════════════════════════════════════════════════════════
#
# All four columns of every CDT row are compared, not just the percentage. The
# two systems word them completely differently:
#
#     Frequency   2X1Year      vs  2 TIMES IN 1 CALENDAR YEAR
#                 1XLifetime   vs  ONCE PER LIFETIME
#                 No Frequency vs  No Limitations
#                 NC           vs  *NOT COVERED
#     Age Limit   14           vs  0-14   (sheet gives one number, portal a range)
#     History     05/11/2026   vs  05/11/26

print("── 1c. BENEFIT DETAILS COLUMNS ──")

# Cell classification: empty cells are omitted, so each is identified by shape.
ROW_CASES = [
    # cells as printed                     -> frequency, percentage, age, history
    (["No Frequency", "100%"],                ("No Frequency", "100%", None, None)),
    (["2X1Year", "100%", "01/28/2026"],       ("2X1Year", "100%", None, "01/28/2026")),
    (["2X1Year", "100%", "19", "NH"],         ("2X1Year", "100%", "19", "NH")),
    (["No Frequency", "100%", "99"],          ("No Frequency", "100%", "99", None)),
    (["1XLifetime", "80%"],                   ("1XLifetime", "80%", None, None)),
    (["NC", "0"],                             ("NC", "0", None, None)),
    (["100%"],                                (None, "100%", None, None)),
    (["0"],                                   (None, "0", None, None)),
    (["50%", "19"],                           (None, "50%", "19", None)),
    # page furniture after the final row must never be taken for a cell
    (["No Frequency", "100%", "© 2026 iSpace, Inc."],
                                              ("No Frequency", "100%", None, None)),
]
for cells, want in ROW_CASES:
    got = sc._classify_row_cells(list(cells))
    check(f"row cells {cells}",
          (got["frequency"], got["percentage"], got["age_limit"], got["history"]), want)

# Frequency equivalence across the two vocabularies.
FREQ_PAIRS = [
    ("2X1Year",      "2 TIMES IN 1 CALENDAR YEAR",  True),
    ("1X1Year",      "1 TIME IN 1 CALENDAR YEAR",   True),
    ("4X1Year",      "4 TIMES IN 1 CALENDAR YEAR",  True),
    ("1X60Months",   "1 TIME IN 60 MONTHS",         True),
    ("1X84Months",   "1 TIME IN 84 MONTHS",         True),
    ("1XLifetime",   "ONCE PER LIFETIME",           True),
    ("No Frequency", "No Limitations",              True),
    ("NC",           "*NOT COVERED",                True),
    # conditions the portal appends are not part of the limit
    ("1X60Months",   "1 TIME IN 60 MONTHS, PERMANENT MOLARS ONLY", True),
    # 5 years and 60 months are the same limit stated two ways
    ("1X5Years",     "1 TIME IN 60 MONTHS",         True),
    # genuine differences must still surface
    ("2X1Year",      "1 TIME IN 1 CALENDAR YEAR",   False),
    ("1X60Months",   "1 TIME IN 36 MONTHS",         False),
    ("No Frequency", "2 TIMES IN 1 CALENDAR YEAR",  False),
    ("1XLifetime",   "No Limitations",              False),
]
for sab, por, want in FREQ_PAIRS:
    check(f"frequency {sab!r} vs {por!r}", sc._compare("frequency", sab, por)[0], want)

# Age limit: a single number against a range, compared on the ceiling.
for sab, por, want in [("14", "0-14", True), ("99", "0-99", True),
                       ("19", "0-19", True), ("14", "0-19", False),
                       ("99", "14-99", True), ("13", "0-14", False)]:
    check(f"age limit {sab!r} vs {por!r}", sc._compare("agelimit", sab, por)[0], want)

# History: the portal abbreviates the year; "NH" means never performed.
check("history 05/11/2026 vs 05/11/26",
      sc._compare("history", "05/11/2026", "05/11/26")[0], True)
check("history differing dates",
      sc._compare("history", "05/11/2026", "01/28/26")[0], False)
check("history NH against a real service date",
      sc._compare("history", "NH", "05/11/26")[0], False)
check("history NH mismatch is explained",
      "no history" in sc._compare("history", "NH", "05/11/26")[1], True)
check("history against a silent portal is not comparable",
      sc._compare("history", "05/11/2026", "")[0], None)

# An empty Frequency/Age cell asserts "no limit" — agreement, not a gap.
check("blank frequency agrees with 'No Limitations'",
      sc._blank_means_no_limit("frequency", "No Limitations"), True)
check("blank frequency does NOT excuse a real limit",
      sc._blank_means_no_limit("frequency", "1 TIME IN 1 CALENDAR YEAR"), False)
check("blank frequency does NOT excuse *NOT COVERED",
      sc._blank_means_no_limit("frequency", "*NOT COVERED"), False)
check("blank age agrees with the full 0-99 span",
      sc._blank_means_no_limit("agelimit", "0-99"), True)
check("blank age does NOT excuse an age floor (14-99)",
      sc._blank_means_no_limit("agelimit", "14-99"), False)
check("blank age does NOT excuse a real ceiling (0-14)",
      sc._blank_means_no_limit("agelimit", "0-14"), False)

# Only the codes MetLife actually supplies each column for are compared.
# Anything else produced "blank on the sheet" flags for cells the sheet is right
# to leave empty.
_derived = [f for f in sc._SPEC if f.get("derived")]
_by_aspect = {a: sorted(f["row_key"] for f in _derived if f["aspect"] == a)
              for a in ("freq", "age", "hist")}

check("age limit compared only for D1206/D1208/D1351/D1510/D8080",
      _by_aspect["age"], ["d1206", "d1208", "d1351", "d1510", "ortho_coverage"])
check("history compared only for the twelve listed codes",
      _by_aspect["hist"],
      ["d0120", "d0140", "d0210", "d0274", "d0330", "d1110",
       "d1206", "d1208", "d1351", "d1510", "d4341", "d4910"])
_cdt_keys = {f["key"] for f in sc._SPEC if f["section"] == "Coverage by CDT Code"}
check("frequency skipped for D3310/D7140/D7210/D9230/D9243/D8080/D8090",
      sorted(_cdt_keys - set(_by_aspect["freq"])),
      ["d3310", "d7140", "d7210", "d8090", "d9230", "d9243", "ortho_coverage"])
# D4341 carries history but NOT an age limit — its Age Limit column holds the
# quadrant count, which has no portal counterpart.
check("D4341 has a history row", "d4341" in _by_aspect["hist"], True)
check("D4341 has no age row", "d4341" in _by_aspect["age"], False)
check("generated rows stay out of the label matcher",
      any(sc._norm_label(f["label"]) in sc._ALL_LABELS for f in _derived), False)


# ══════════════════════════════════════════════════════════════════════════════
#  1d. MetLife observations (Material/JSON Requirment.pdf)
# ══════════════════════════════════════════════════════════════════════════════

print("── 1d. METLIFE OBSERVATIONS ──")

# OBS: the sheet names the plan, the portal names the payer + claims address.
# Same insurer, so the same value.
check("carrier: 'Metlife PDP+' vs the portal's payer string",
      sc._compare("carrier", "Metlife PDP+",
                  "(IN) MetLife(TX)- PO Box 981282- 79998")[0], True)
check("carrier: the match is explained",
      "same carrier" in sc._compare("carrier", "Metlife PDP+",
                                    "(IN) MetLife(TX)- PO Box 981282- 79998")[1], True)
check("carrier: a genuinely different insurer is caught",
      sc._compare("carrier", "Metlife PDP+", "Cigna Dental PPO")[0], False)
check("carrier: Delta Dental variants agree",
      sc._compare("carrier", "Delta Dental PPO", "DELTA DENTAL OF WISCONSIN")[0], True)
check("carrier: United Concordia is not confused with Concordia Plan Services",
      sc._carrier_brand("United Concordia Dental"), "united concordia")
check("carrier: unknown brands fall back to text rules",
      sc._compare("carrier", "Acme Dental Trust", "Acme Dental Trust")[0], True)

# OBS: the missing-tooth answer is INVERTED and taken from the FIRST sentence.
from new_plan import _missing_tooth_clause as _mtc
_BOTH = ("Are plan benefits available for teeth lost prior to effective date: {} "
         "Are plan benefits available for congenital teeth lost prior to "
         "effective date: {}")
check("missing tooth: first sentence Yes -> clause does NOT apply",
      _mtc(_BOTH.format("Yes", "Yes")), "No")
check("missing tooth: first sentence No -> clause DOES apply",
      _mtc(_BOTH.format("No", "Yes")), "Yes")
check("missing tooth: the congenital answer never decides it",
      _mtc(_BOTH.format("Yes", "No")), "No")

# OBS: preventive counts toward the yearly maximum when the maximum's category
# list names it.
def _annual(applies_to):
    return {"metlife_data": {"financials": {"annual_max": {"applies_to": applies_to}}}}

check("yearly max: category list naming Preventive -> Yes",
      sc._portal_prev_in_max({}, _annual(
          "Diagnostic, Preventive, Restorative, Endodontics, Prosthodontics, "
          "Oral Surgery, Adjunctive, Implant Services")), "Yes")
check("yearly max: category list without Preventive -> No",
      sc._portal_prev_in_max({}, _annual(
          "Restorative, Endodontics, Prosthodontics, Oral Surgery")), "No")
check("yearly max: an export that never captured the list stays silent",
      sc._portal_prev_in_max({}, {"metlife_data": {"financials": {"annual_max": {}}}}), None)
check("yearly max: 'N/A' is treated as not captured",
      sc._portal_prev_in_max({}, _annual("N/A")), None)

# OBS: both alternate-benefit questions are compared fields now.
_keys = {f["key"] for f in sc._SPEC}
check("posterior composites question is a compared field",
      "posterior_composite_downgrade" in _keys, True)
check("posterior crowns question is a compared field",
      "porcelain_posterior_downgrade" in _keys, True)
check("neither question is still listed as non-compared furniture",
      any(sc._norm_label(lbl) in sc._OTHER_SHEET_LABELS for lbl in
          ("Are Posterior Composites Downgraded To Amalgam?",
           "Are Posterior Crowns Downgraded?")), False)


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

# Masked portal identifiers ("XXXXXXX6200") cannot be compared literally.
check("id: masked portal value with agreeing visible digits",
      sc._compare("id", "833926200", "XXXXXXX6200")[0], True)
check("id: masked portal value with differing visible digits",
      sc._compare("id", "833926200", "XXXXXXX9999")[0], False)
check("id: fully masked value is not comparable",
      sc._compare("id", "833926200", "XXXXXXXXX")[0], None)
check("id: leading-visible mask", sc._compare("id", "833926200", "8339XXXXX")[0], True)
check("id: a real X in an id is not treated as a mask",
      sc._compare("id", "X12345", "X12345")[0], True)

# Coordination of benefits: the method is what compares, not the order rule.
_COB_PROV = {"metlife_data": {"provisions": [
    {"rule": "Coordination of Benefits Rule",
     "value": "Coordination of Benefits with any other dental plan: Birthday rule, Regular COB"}]}}
check("cob: 'Regular COB' reads as Standard",
      sc._portal_cob({}, _COB_PROV), "Standard")
check("cob: non-duplication is distinguished",
      sc._portal_cob({}, {"metlife_data": {"provisions": [
          {"rule": "Coordination of Benefits Rule",
           "value": "Non-Duplication of benefits applies"}]}}), "Non-Duplication")
check("cob: silent portal stays silent", sc._portal_cob({}, {"metlife_data": {}}), None)

# OON benefits come from the per-category out_of_network column.
check("oon: a category paying out of network means Yes",
      sc._portal_oon_benefits({}, {"metlife_data": {"covered_services": [
          {"category": "PREVENTIVE", "in_network": "100%", "out_of_network": "100%"}]}}), "Yes")
check("oon: every category not covered means No",
      sc._portal_oon_benefits({}, {"metlife_data": {"covered_services": [
          {"category": "PREVENTIVE", "in_network": "100%", "out_of_network": "Not Covered"},
          {"category": "MAJOR", "in_network": "50%", "out_of_network": "Not Covered"}]}}), "No")
check("oon: no out_of_network column at all stays silent",
      sc._portal_oon_benefits({}, {"metlife_data": {"covered_services": [
          {"category": "PREVENTIVE", "in_network": "100%"}]}}), None)

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
            assert out["summary"]["total_fields"] == len(sc._SPEC)
            ok += 1
        check(f"Delta Dental portal exports normalize without error ({ok} files)",
              ok, len(dd_files))


print(f"\n{_passed + _failed} checks: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
