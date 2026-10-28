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

# The suites live in tests/ but read fixtures from, and import, the repo root.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import os
import sys

import sabrina_compare as sc

# Windows consoles default to cp1252 and cannot encode the section rules below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE = _ROOT
SABRINA_PDF = os.path.join(BASE, "Material", "Comparison", "Metlife.pdf")
SABRINA_PDF_2 = os.path.join(BASE, "Material", "Comparison", "Metlife - 81986.pdf")
PORTAL_JSON_2 = os.path.join(BASE, "Material", "Comparison",
                             "tudor_piroteala_metlife_audit (1).json")
DD_PORTAL_DIR = os.path.join(BASE, "Material", "Comparison", "DD INS")
SABRINA_PDF_3 = os.path.join(BASE, "Material", "Smile", "Gore1.pdf")
PORTAL_JSON_3 = os.path.join(BASE, "Material", "Smile", "tiffany_gore_metlife_audit.json")
SABRINA_PDF_4 = os.path.join(BASE, "Material", "Smile", "91215.pdf")
PORTAL_JSON_4 = os.path.join(BASE, "Material", "Smile",
                             "amanda_j_wilson_metlife_audit.json")
SABRINA_PDF_5 = os.path.join(BASE, "Material", "Smile", "Matthew Herzwurm.pdf")
PORTAL_JSON_5 = os.path.join(BASE, "Material", "Smile",
                             "cigna_Matthew_Herzwurm_2026-09-15.json")
SABRINA_PDF_6 = os.path.join(BASE, "Material", "Smile", "Aaren.pdf")
SABRINA_PDF_7 = os.path.join(BASE, "Material", "Smile", "Jason.pdf")
SABRINA_PDF_8 = os.path.join(BASE, "Material", "Smile", "Carlos Evans.pdf")
SABRINA_PDF_9 = os.path.join(BASE, "Material", "Smile", "Angela Cao.pdf")
PORTAL_JSON_9 = os.path.join(
    BASE, "Material", "Smile", "angela_cao_Delta_Dental.json")
# A Delta Dental export whose patient is a dependent, not the subscriber.
PORTAL_DEPENDENT = os.path.join(
    BASE, "Material", "Comparison", "DD INS", "daniel_klopp_Delta_Dental 3.json")
SABRINA_PDF_10 = os.path.join(BASE, "Material", "Smile", "Martin S Sas.pdf")
SABRINA_PDF_11 = os.path.join(BASE, "Material", "Smile", "Kate Licina.pdf")
PORTAL_JSON_11 = os.path.join(
    BASE, "Material", "Smile", "kate_s_licina_metlife_audit.json")
PORTAL_JSON_10 = os.path.join(
    BASE, "Material", "Smile", "martin_sas_Delta_Dental.json")
PORTAL_JSON_8 = os.path.join(
    BASE, "Material", "Smile", "carlos_evans_Delta_Dental.json")
PORTAL_JSON_7 = os.path.join(
    BASE, "Material", "Smile",
    "jason_knezevich_smileway_participant_Delta_Dental.json")
PORTAL_JSON_6 = os.path.join(BASE, "Material", "Smile", "aaren_boyd_metlife_audit.json")

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

        # The CDT rows must arrive groupable: one group per code, each carrying
        # its aspect so the UI can render a single line per code.
        cdt = next(s for s in res["sections"] if s["section"] == "Coverage by CDT Code")
        groups = {}
        for row in cdt["rows"]:
            groups.setdefault(row["group"], set()).add(row["aspect"])
        check("[2] one group per CDT code", len(groups), 41)
        check("[2] every CDT row carries group + aspect",
              all(r.get("group") and r.get("aspect") for r in cdt["rows"]), True)
        check("[2] every group has a percentage cell",
              all("pct" in a for a in groups.values()), True)
        check("[2] D0120 groups percentage, frequency and history together",
              groups["d0120"], {"pct", "freq", "hist"})
        check("[2] D1206 groups all four columns",
              groups["d1206"], {"pct", "freq", "age", "hist"})
        check("[2] D3310 has no frequency cell",
              groups["d3310"], {"pct"})
        check("[2] group labels drop the aspect suffix",
              {r["group_label"] for r in cdt["rows"] if r["group"] == "d0120"},
              {"D0120 Periodic Exam"})
        check("[2] non-CDT sections are not grouped",
              any(r.get("group") for s in res["sections"]
                  for r in s["rows"] if s["section"] != "Coverage by CDT Code"), False)

        # One genuine finding, surfaced once the portal's "—" in Late Date Of
        # Service is read as "never performed" rather than as an empty cell:
        # the sheet carries the prophy date on the perio-maintenance row too.
        # The same pattern appears on Amanda Wilson and Aaren Boyd.
        check("[2] the copied perio date is the only disagreement",
              sorted(r["key"] for r in res["mismatches"]), ["d4910__hist"])
        check("[2] D1110 keeps its own date", rows["d1110__hist"]["status"], "match")
        check("[2] and D0120 too", rows["d0120__hist"]["status"], "match")
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
    # a History cell listing two dates wraps after the comma (Mccoy's D1110);
    # `history` keeps the first line for every carrier
    (["2X1Year", "100%", "06/10/2026,", "01/29/2026"],
                                              ("2X1Year", "100%", None, "06/10/2026,")),
]
for cells, want in ROW_CASES:
    got = sc._classify_row_cells(list(cells))
    check(f"row cells {cells}",
          (got["frequency"], got["percentage"], got["age_limit"], got["history"]), want)

# The whole wrapped list is kept beside it, for the Delta audit to read.
check("row cells: a wrapped History list is kept whole",
      sc._classify_row_cells(["2X1Year", "100%", "06/10/2026,", "01/29/2026"])["history_wrapped"],
      "06/10/2026, 01/29/2026")
check("row cells: three dates wrapping twice are kept whole",
      sc._classify_row_cells(["100%", "06/10/2026,", "01/29/2026,", "07/01/2025"])["history_wrapped"],
      "06/10/2026, 01/29/2026, 07/01/2025")
check("row cells: a date after a finished History cell is not part of it",
      sc._classify_row_cells(["1X1Year", "100%", "01/06/2026", "02/02/2026"])["history_wrapped"],
      None)
check("row cells: nothing wrapped, nothing kept",
      sc._classify_row_cells(["2X1Year", "100%", "NH"])["history_wrapped"], None)

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
# Twelve codes, the ones Sabrina generates a history for. D1510 was dropped
# from the list (Oct 2026): the sheet does not carry a history for it.
check("history compared only for the twelve listed codes",
      _by_aspect["hist"],
      ["d0120", "d0140", "d0150", "d0210", "d0274", "d0330", "d1110",
       "d1206", "d1208", "d1351", "d4341", "d4910"])
_cdt_keys = {f["key"] for f in sc._SPEC
             if f["section"] == "Coverage by CDT Code" and not f.get("derived")}
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
from smile_partners.breakdown import _missing_tooth_clause as _mtc
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


# ── In Network must consider BOTH networks, badge first ─────────────────────
#
# The fee-schedule name must never decide it: for MetLife the breakdown always
# reports "METLIFE PPO", which would read as in-network even for a provider the
# portal explicitly marks out-of-network.
_FEE = {"fee_schedule": "METLIFE PPO"}


def _prov(status):
    return {"metlife_data": {"provider_info": {"provider_network_status": status}}}


def _svcs(*rows):
    return {"metlife_data": {"covered_services": list(rows)}}


# In Network is a NETWORK TYPE, checked against what the plan actually pays
# under. The portal cannot say which network THIS office is in — the scraped
# provider badge matches the first "IN-NETWORK"/"OUT-OF-NETWORK" element on the
# page, which is a coverage-panel heading, so it reads In-Network for everyone.
# What the portal does state is the benefit per network, so the check is whether
# the network the sheet claims is one the plan pays under.
_ONLY_IN = _svcs({"category": "PREVENTIVE", "in_network": "100%",
                  "out_of_network": "Not Covered"})
_ONLY_OUT = _svcs({"category": "PREVENTIVE", "in_network": "Not Covered",
                   "out_of_network": "80%"})
_BOTH = _svcs({"category": "PREVENTIVE", "in_network": "100%",
               "out_of_network": "100%"})
_NEITHER = _svcs({"category": "PREVENTIVE", "in_network": "Not Covered",
                  "out_of_network": "Not Covered"})

# The reported case: the sheet says Out, the plan pays out of network -> MATCH.
check("network: sheet 'Out' against a plan paying both networks",
      sc._portal_in_network({}, _BOTH, "Out"), "Out")
check("network: that comparison is a match",
      sc._compare("network", "Out", sc._portal_in_network({}, _BOTH, "Out"))[0], True)
check("network: sheet 'In' against a plan paying both networks",
      sc._portal_in_network({}, _BOTH, "In"), "In")
check("network: sheet 'Out' where only out-of-network pays",
      sc._portal_in_network({}, _ONLY_OUT, "Out"), "Out")

# ...and it still catches a claim the plan does not support.
check("network: sheet 'Out' but the plan pays in-network only -> conflict",
      sc._compare("network", "Out", sc._portal_in_network({}, _ONLY_IN, "Out"))[0], False)
check("network: sheet 'In' but the plan pays out-of-network only -> conflict",
      sc._compare("network", "In", sc._portal_in_network({}, _ONLY_OUT, "In"))[0], False)
check("network: neither network pays -> unanswered",
      sc._portal_in_network({}, _NEITHER, "In"), None)

# The fee-schedule name must never decide it (MetLife always reports "PPO"),
# but with no coverage table at all it is the only signal left.
check("network: sheet silent, plan pays in network",
      sc._portal_in_network({}, _ONLY_IN), "In")
check("network: no coverage table, falls back to the plan wording",
      sc._portal_in_network(_FEE, {"metlife_data": {}}), "In")
check("network: the scraped provider badge is ignored",
      sc._portal_in_network({}, {"metlife_data": {
          "provider_info": {"provider_network_status": "In-Network"},
          "covered_services": [{"category": "PREVENTIVE", "in_network": "Not Covered",
                                "out_of_network": "80%"}]}}, "Out"), "Out")
check("network: nothing stated anywhere",
      sc._portal_in_network({}, {"metlife_data": {}}), None)

# A MetLife export from extension v1.38+ does state the office's own network:
# the Benefit & Coverage tab's provider sticker, recorded with the procedures
# priced under it. That answers the field outright — including the case the
# coverage rows cannot catch, a sheet claiming In for an out-of-network office
# on a plan that pays both ways.
def _ml_crawl(status, changed=False, source="MetLife Portal - Benefit & Coverage Details"):
    raw = dict(_BOTH)
    raw["benefit_coverage"] = {"source": source, "provider_network_status": status,
                               "provider_changed_during_crawl": changed, "procedures": []}
    return raw

check("network: MetLife provider sticker says Out, sheet claims In -> Out",
      sc._portal_in_network({}, _ml_crawl("Out-of-Network"), "In"), "Out")
check("network: that comparison is a conflict",
      sc._compare("network", "In", sc._portal_in_network({}, _ml_crawl("Out-of-Network"), "In"))[0], False)
check("network: MetLife provider sticker says In, sheet claims Out -> In",
      sc._portal_in_network({}, _ml_crawl("In-Network"), "Out"), "In")
check("network: MetLife sticker agrees with the sheet",
      sc._compare("network", "Out", sc._portal_in_network({}, _ml_crawl("Out-of-Network"), "Out"))[0], True)
# Anything less than a clean statement falls back to the coverage rows.
check("network: MetLife sticker unread (N/A) -> coverage rows decide",
      sc._portal_in_network({}, _ml_crawl("N/A"), "In"), "In")
check("network: provider switched mid-crawl -> coverage rows decide",
      sc._portal_in_network({}, _ml_crawl("Out-of-Network", changed=True), "In"), "In")
# Only MetLife's own export carries the statement; another carrier's
# translation that happened to hold the key is not read.
check("network: a non-MetLife benefit_coverage is not read",
      sc._portal_in_network({}, _ml_crawl("Out-of-Network", source=""), "In"), "In")

# Network-type normalization across both vocabularies.
for raw, want in [("In", "IN"), ("Out", "OUT"), ("In-Network", "IN"),
                  ("Out-of-Network", "OUT"), ("Yes", "IN"), ("No", "OUT"),
                  ("METLIFE PPO", "IN"), ("Non-Par", "OUT"), ("", None)]:
    check(f"network normalize {raw!r}", sc._norm_network(raw), want)

check("network: a 0% out-of-network benefit is not coverage",
      sc._network_pays("0% Deductible Applies : No"), False)
check("network: 'Not Covered' is not coverage", sc._network_pays("Not Covered"), False)
check("network: '80%' is coverage", sc._network_pays("80% Deductible Applies : Yes"), True)


# ── every CDT code is one row, with a cell per column ──────────────────────
_cdt_spec = [f for f in sc._SPEC if f["section"] == "Coverage by CDT Code"]
check("all four columns live in one section",
      {f["section"] for f in sc._SPEC if f.get("derived")}, {"Coverage by CDT Code"})
check("every CDT row is tagged with its group",
      all(f.get("group") for f in _cdt_spec if f.get("derived")), True)
check("percentage rows anchor their group",
      all(f.get("aspect") in ("pct", "freq", "age", "hist")
          for f in _cdt_spec if f.get("aspect")), True)


# ══════════════════════════════════════════════════════════════════════════════
#  1e. THIRD REAL EXPORT — an out-of-network office (Material/Smile)
# ══════════════════════════════════════════════════════════════════════════════
#
# This sheet says In Network = "Out" (its fee schedule is "GA General UCR", the
# out-of-network fee basis). The plan pays identically under both networks, so
# the claim is supported and the row must read MATCH — it was reported as a
# MISMATCH against a portal side that always answered "Yes".
#
# The same pairing also carries two genuine data errors, which must still be
# reported: D0330 Pano at 80% against the portal's 100%, and D0140's frequency
# recorded as 2X12Months against the portal's 1 TIME IN 12 MONTHS.

print("── 1e. THIRD REAL EXPORT (Tiffany Gore, out-of-network) ──")
if not (os.path.exists(SABRINA_PDF_3) and os.path.exists(PORTAL_JSON_3)):
    skip("third Sabrina pairing", "Material/Smile files not present")
else:
    import json as _json3
    with open(SABRINA_PDF_3, "rb") as fh:
        parsed3 = sc.parse_sabrina_pdf(fh.read())
    with open(PORTAL_JSON_3, encoding="utf-8") as fh:
        portal3 = _json3.load(fh)

    check("[3] detected as a Sabrina sheet", sc.is_sabrina_pdf(parsed3["text"]), True)
    check("[3] all labels found", parsed3["labels_not_found"], [])
    f3 = parsed3["fields"]
    check("[3] the sheet says the office is out of network", f3["in_network"], "Out")
    check("[3] and that it has OON benefits", f3["oon_benefits"], "Yes")
    check("[3] insurance name carries the plan suffix", f3["ins_name"], "Metlife PDP+")

    res3 = sc.compare_sabrina_to_portal(parsed3, portal3)
    rows3 = {r["key"]: r for s in res3["sections"] for r in s["rows"]}

    check("[3] 'Out' now MATCHES the portal",
          (rows3["in_network"]["portal"], rows3["in_network"]["status"]), ("Out", "match"))
    check("[3] OON benefits match", rows3["oon_benefits"]["status"], "match")
    check("[3] carrier matches despite the plan suffix",
          rows3["ins_name"]["status"], "match")
    check("[3] group number came through this export",
          (rows3["group_number"]["portal"], rows3["group_number"]["status"]),
          ("261127", "match"))

    # The two real errors must survive all the noise reduction.
    check("[3] the genuine mismatches are reported",
          sorted(r["key"] for r in res3["mismatches"]), ["d0140__freq", "d0330"])
    check("[3] D0330 percentage disagreement",
          (rows3["d0330"]["sabrina"], rows3["d0330"]["portal"]), ("80%", "100%"))
    check("[3] D0140 frequency disagreement",
          (rows3["d0140__freq"]["sabrina"], rows3["d0140__freq"]["portal"]),
          ("2X12Months", "1 TIME IN 12 MONTHS"))
    # D0120 states the same 2-per-12-months and DOES match, which is what makes
    # D0140 look like a copied-down value rather than a parsing artefact.
    check("[3] D0120 frequency matches", rows3["d0120__freq"]["status"], "match")
    check("[3] nothing reported blank on the sheet",
          res3["summary"]["missing_in_sabrina"], 0)


# ══════════════════════════════════════════════════════════════════════════════
#  1f. Apt 92763 (Smile Partners / MetLife) — two mapping bugs
# ══════════════════════════════════════════════════════════════════════════════
#
# Reported: the bot took the patient's EFFECTIVE DATE as the plan start month
# (September) for a plan the portal plainly labels CALENDAR YEAR, and it read a
# TMJ lifetime maximum ($1,000) as the orthodontic lifetime max against a sheet
# that correctly said 0. TMJ is a separate class, outside Eligibility &
# Benefits verification.

print("── 1f. APT 92763 MAPPING BUGS ──")

from smile_partners.breakdown import _get_plan_year_start as _pys

_BENEFIT_PERIOD = {
    "rule": "Benefit Period",
    "value": "CALENDAR YEAR Start Date: 01/01/2026 End Date: 12/31/2026",
}

# The Benefit Period provision is authoritative and must win over the
# effective date, which only says when this member joined.
check("plan year: CALENDAR YEAR provision beats a September effective date",
      _pys({}, "09/08/2026", [_BENEFIT_PERIOD]), "January")
check("plan year: an explicit mid-year start date is still honoured",
      _pys({}, "01/01/2026", [{"rule": "Benefit Period",
                               "value": "CONTRACT YEAR Start Date: 09/01/2026 "
                                        "End Date: 08/31/2027"}]), "September")
check("plan year: 'CALENDAR YEAR' with no start date",
      _pys({}, "09/08/2026", [{"rule": "Benefit Period", "value": "CALENDAR YEAR"}]),
      "January")
check("plan year: no provision falls back to the effective date",
      _pys({}, "09/08/2026", []), "September")
check("plan year: the D2740 calendar-year hint still applies",
      _pys({"D2740": {"frequency_limit": "1 TIME IN 1 CALENDAR YEAR"}}, "09/08/2026", []),
      "January")
check("plan year: an unparseable effective date degrades quietly",
      _pys({}, "", []), "\u2014")

# A lifetime maximum belonging to another class is not the ortho maximum.
def _lifetime(category, total, ortho_covered):
    return {"metlife_data": {
        "financials": {"ortho_lifetime": dict(
            {"total": total, "used": "$ 0.00 used to date", "remaining": total},
            **({"category": category} if category is not None else {}))},
        "covered_services": [{
            "category": "ORTHODONTICS",
            "in_network": "50%" if ortho_covered else "Not Covered",
            "out_of_network": "50%" if ortho_covered else "Not Covered"}],
        "provisions": [_BENEFIT_PERIOD],
    }}

_tmj = _lifetime("TMJ", "$ 1000.00 total", ortho_covered=False)
_bd_tmj = sc._portal_breakdown(_tmj)
check("ortho max: the raw breakdown does pick up the TMJ figure",
      _bd_tmj.get("ortho_max"), "1,000.00")
check("ortho max: a TMJ lifetime maximum is not reported as ortho",
      sc._portal_ortho_max(_bd_tmj, _tmj), "0.00")
check("ortho used: guarded the same way",
      sc._portal_ortho_used(_bd_tmj, _tmj), "0.00")
check("ortho max: so a sheet saying 0 matches",
      sc._compare("money", "0", sc._portal_ortho_max(_bd_tmj, _tmj))[0], True)

_real = _lifetime("Orthodontia", "$ 1500.00 total", ortho_covered=True)
_bd_real = sc._portal_breakdown(_real)
check("ortho max: a genuine orthodontic maximum still comes through",
      sc._portal_ortho_max(_bd_real, _real), "1,500.00")
check("ortho max: and matches a sheet stating it",
      sc._compare("money", "1500", sc._portal_ortho_max(_bd_real, _real))[0], True)

_mixed = _lifetime("TMJ", "$ 1000.00 total", ortho_covered=True)
check("ortho max: ortho covered but the card is TMJ -> still not ortho",
      sc._portal_ortho_max(sc._portal_breakdown(_mixed), _mixed), "0.00")

_old = _lifetime(None, "$ 1000.00 total", ortho_covered=False)
check("ortho max: an export with no category, ortho not covered -> guarded",
      sc._portal_ortho_max(sc._portal_breakdown(_old), _old), "0.00")

_no_ortho_row = {"metlife_data": {"financials": {
    "ortho_lifetime": {"total": "$ 2000.00 total", "used": "$ 0.00 used to date"}}}}
check("ortho max: nothing said about orthodontics -> the figure stands",
      sc._portal_ortho_max(sc._portal_breakdown(_no_ortho_row), _no_ortho_row), "2,000.00")

check("ortho: TMJ is recognized as another class",
      sc._lifetime_belongs_elsewhere(_tmj), "TMJ")
check("ortho: Orthodontia is not another class",
      sc._lifetime_belongs_elsewhere(_real), None)
check("ortho coverage: 'Not Covered' both networks",
      sc._ortho_is_covered(_tmj), False)
check("ortho coverage: covered", sc._ortho_is_covered(_real), True)
check("ortho coverage: no orthodontics row at all",
      sc._ortho_is_covered(_no_ortho_row), None)

# Dasian Southern (MetLife, dependent aged 14): Covered Services said "Not
# Covered" for orthodontics, while the plan provision said "Orthodontics is
# covered under this plan" and the Lifetime card was Orthodontics, $2,000. The
# audit took the coverage row and reported the maximum as $0 against a sheet
# correctly saying 2000. The provision is the plan's own statement and decides.
def _with_ortho_provision(raw, value):
    out = {"metlife_data": dict(raw["metlife_data"])}
    out["metlife_data"]["provisions"] = list(raw["metlife_data"].get("provisions", [])) + [
        {"rule": "Orthodontic Coverage", "value": value}]
    return out

_dasian = _with_ortho_provision(
    _lifetime("Orthodontics", "$ 2000.00 total", ortho_covered=False),
    "Orthodontics is covered under this plan Percentage considered at initial ortho placement: 20%")
check("ortho coverage: provision 'is covered' beats a 'Not Covered' row",
      sc._ortho_is_covered(_dasian), True)
check("ortho max: Dasian Southern's $2,000 comes through",
      sc._portal_ortho_max(sc._portal_breakdown(_dasian), _dasian), "2,000.00")
check("ortho max: and matches the sheet's 2000",
      sc._compare("money", "2000", sc._portal_ortho_max(sc._portal_breakdown(_dasian), _dasian))[0], True)

# The provision cuts both ways: "is not covered" still zeroes the maximum, even
# where the coverage row disagrees (Nicole Green's plan states not covered).
_stated_not = _with_ortho_provision(
    _lifetime("Orthodontics", "$ 1000.00 total", ortho_covered=True),
    "Orthodontics is not covered under this plan Percentage considered at initial ortho placement: 0%")
check("ortho coverage: provision 'is not covered' beats a covered row",
      sc._ortho_is_covered(_stated_not), False)
check("ortho max: a plan stating ortho not covered still reports 0",
      sc._portal_ortho_max(sc._portal_breakdown(_stated_not), _stated_not), "0.00")
# A TMJ card is still not ortho, whatever the provision says.
_tmj_covered = _with_ortho_provision(_tmj, "Orthodontics is covered under this plan")
check("ortho max: TMJ card with ortho covered -> still not ortho",
      sc._portal_ortho_max(sc._portal_breakdown(_tmj_covered), _tmj_covered), "0.00")

# Sheila Sokolowski (MetLife, Spouse): the extension found no Subscriber entry
# in the patient dropdown and exported `subscriber_info: null`. The breakdown
# fell back to the PATIENT's name and DOB, so the audit reported her own name
# and birthday as the subscriber's against a sheet correctly naming Brian
# Leiter — a critical DOB mismatch the portal never stated.
from smile_partners.sabrina.carriers.metlife.spec import _SPEC as _ML_SPEC
_ml_field = {f["key"]: f for f in _ML_SPEC}

def _member(name, dob, relationship, sub_info=None):
    return {"metlife_data": {"patient": {"name": name, "dob": dob, "relationship": relationship},
                             "provisions": [_BENEFIT_PERIOD]},
            "subscriber_info": sub_info}

def _sub_values(raw):
    bd = sc._portal_breakdown(raw)
    return (sc._portal_value(_ml_field["subscriber_name"], bd, raw),
            sc._portal_value(_ml_field["subscriber_dob"], bd, raw))

_sheila = _member("Sheila Sokolowski", "08/23/1964", "Spouse")
check("subscriber: the breakdown itself falls back to the patient",
      sc._portal_breakdown(_sheila).get("subscriber_name"), "Sheila Sokolowski")
check("subscriber: spouse with no subscriber captured -> unstated, not her own",
      _sub_values(_sheila), (None, None))
check("subscriber: dependent with no subscriber captured -> unstated",
      _sub_values(_member("Dasian J Southern", "01/26/2012", "Dependent")), (None, None))
check("subscriber: a captured subscriber still comes through",
      _sub_values(_member("Sheila Sokolowski", "08/23/1964", "Spouse",
                          {"name": "Brian Leiter", "dob": "01/14/1963", "relation": "Subscriber"})),
      ("Brian Leiter", "01/14/1963"))
check("subscriber: the patient IS the subscriber -> her own details stand",
      _sub_values(_member("Tudor Piroteala", "05/18/1987", "Subscriber")),
      ("Tudor Piroteala", "05/18/1987"))
check("subscriber: no relationship stated -> fallback kept as before",
      _sub_values(_member("Pat Doe", "01/01/1990", "")), ("Pat Doe", "01/01/1990"))

# Ami N Dhruva (MetLife): seven History cells left blank on the sheet against
# portal dates (D0120 09/11/25, D0210 11/08/22, …) were reported only as
# "blank on the sheet", which does not count, so the audit scored 100%. As for
# Delta Dental since 2026-10-16, a value the portal states and the sheet leaves
# out is a mismatch.
_ami_export = {
    "metlife_data": {"patient": {"name": "Ami N Dhruva", "dob": "07/17/1966",
                                 "relationship": "Subscriber"},
                     "provisions": [_BENEFIT_PERIOD]},
    "benefit_coverage": {"procedures": [
        {"procedure_code": "D0120", "description": "PERIODIC ORAL EVALUATION",
         "frequency_limit": "2 TIMES IN 1 CALENDAR YEAR", "age_limit": "0-99",
         "late_date_of_service": "09/11/25", "benefit_level": "100%"},
        {"procedure_code": "D0220", "description": "INTRAORAL PERIAPICAL FIRST",
         "frequency_limit": "No Limitations", "age_limit": "0-99",
         "late_date_of_service": "—", "benefit_level": "80%"},
    ]},
}
_ami_audit = sc.compare_sabrina_to_portal(
    {"fields": {"d0120": "100%", "d0120__freq": "2X1Year", "d0220": "80%"}, "benefit_rows": {}},
    _ami_export)
_ami_rows = {r["key"]: r for s in _ami_audit["sections"] for r in s["rows"]}
check("metlife blank: History blank on the sheet, portal has a date -> mismatch",
      (_ami_rows["d0120__hist"]["status"], _ami_rows["d0120__hist"]["portal"]),
      ("mismatch", "09/11/25"))
check("metlife blank: counted with the mismatches, not as 'blank'",
      (_ami_audit["summary"]["missing_in_sabrina"],
       any(r["key"] == "d0120__hist" for r in _ami_audit["mismatches"])), (0, True))
check("metlife blank: so the audit is no longer 100%",
      _ami_audit["summary"]["match_rate"] < 100, True)
check("metlife blank: a blank frequency against 'No Limitations' still agrees",
      _ami_rows["d0220__freq"]["status"], "match")


# ══════════════════════════════════════════════════════════════════════════════
#  1g. Apt 91215 — one plan stating two rules
# ══════════════════════════════════════════════════════════════════════════════
#
# Reported: Coordination of Benefits read as a conflict when both sides say the
# same thing in different words — the sheet "Non-Duplicate", the portal
# "Non-duplication of benefits applies." Where a plan genuinely states two
# methods, the most restrictive governs.
#
# The same pairing also has an age-split frequency: D0274 is "2 EVERY 1 CALENDAR
# YEAR(S) FOR PARTICIPANT TO AGE 19, 1 EVERY 1 CALENDAR YEAR(S) FOR ADULTS", and
# the patient is 63, so the adult clause governs and the sheet's 1X1Year is right.

print("── 1g. APT 91215 — TWO RULES ON ONE PLAN ──")

# Same method, different wording, in both directions.
for sab, por in [("Non-Duplicate", "Non-duplication of benefits applies."),
                 ("Non - Duplicate", "Non-duplication of benefits applies."),
                 ("Non-Dup", "Non-Duplication"),
                 ("Standard", "Birthday rule, Regular COB"),
                 ("Carve Out", "Carve-out applies"),
                 ("Maintenance of Benefits", "MOB applies")]:
    check(f"cob {sab!r} vs {por!r}", sc._compare("cob", sab, por)[0], True)

check("cob: the match is explained",
      "worded differently" in sc._compare("cob", "Non-Duplicate",
                                          "Non-duplication of benefits applies.")[1], True)

# Genuinely different methods must still be caught.
check("cob: Standard against Non-Duplication is a real conflict",
      sc._compare("cob", "Standard", "Non-duplication of benefits applies.")[0], False)
check("cob: the conflict names both methods",
      sc._compare("cob", "Standard", "Non-duplication applies")[1],
      "Standard on the sheet, Non-Duplication on the portal")
check("cob: an unrecognized wording is not comparable",
      sc._compare("cob", "Non-Duplicate", "Birthday rule")[0], None)

# Two methods on one plan -> the most restrictive governs.
check("cob: Regular COB + Non-duplication -> Non-Duplication",
      sc._num_cob("Regular COB, Non-duplication of benefits applies."),
      (3, "Non-Duplication"))
check("cob: Standard + carve-out -> Carve Out",
      sc._num_cob("Standard COB and carve-out applies"), (4, "Carve Out"))
check("cob: MOB + non-duplication -> Non-Duplication",
      sc._num_cob("Maintenance of benefits, non-duplication applies"),
      (3, "Non-Duplication"))
check("cob: the order-of-benefits rule is not a method",
      sc._num_cob("Birthday rule"), None)

# Age-split frequency clauses.
_SPLIT = ("2 EVERY 1 CALENDAR YEAR(S) FOR PARTICIPANT TO AGE 19, "
          "1 EVERY 1 CALENDAR YEAR(S) FOR ADULTS")
check("frequency: an adult gets the adult clause",
      sc._num_frequency(_SPLIT, 63), (1, 12))
check("frequency: a child gets the child clause",
      sc._num_frequency(_SPLIT, 12), (2, 12))
check("frequency: with no age, the most restrictive clause governs",
      sc._num_frequency(_SPLIT, None), (1, 12))
check("frequency: the chosen clause is explained",
      sc._frequency_note(_SPLIT, 63), "patient is 63; applied the clause for ages 18-999")
check("frequency: sheet 1X1Year matches for a 63-year-old",
      sc._compare("frequency", "1X1Year", _SPLIT, {"age": 63})[0], True)
check("frequency: sheet 2X1Year matches for a 12-year-old",
      sc._compare("frequency", "2X1Year", _SPLIT, {"age": 12})[0], True)
check("frequency: sheet 2X1Year for a 63-year-old is still a conflict",
      sc._compare("frequency", "2X1Year", _SPLIT, {"age": 63})[0], False)
check("frequency: 'age 19 and over' band",
      sc._clause_age_range("1 EVERY 1 YEAR FOR AGE 19 AND OVER"), (19, 999))
check("frequency: 'to age 14' band",
      sc._clause_age_range("2 EVERY 1 YEAR TO AGE 14"), (0, 14))
check("frequency: an unqualified clause has no band",
      sc._clause_age_range("2 TIMES IN 1 CALENDAR YEAR"), None)

# A trailing condition is not a second clause.
check("frequency: trailing conditions are not treated as clauses",
      sc._num_frequency("1 TIME IN 60 MONTHS, PERMANENT MOLARS ONLY, "
                        "EXCLUDING WISDOM TEETH", 63), (1, 60))
check("frequency: single-clause values are unaffected",
      sc._compare("frequency", "2X1Year", "2 TIMES IN 1 CALENDAR YEAR")[0], True)

check("age: computed from the sheet's date of birth",
      isinstance(sc._age_from_dob("05/14/1963"), int), True)
check("age: a blank date of birth gives no age", sc._age_from_dob(""), None)
check("age: an unparseable date of birth gives no age", sc._age_from_dob("not a date"), None)

# ── the real pairing ────────────────────────────────────────────────────────
if not (os.path.exists(SABRINA_PDF_4) and os.path.exists(PORTAL_JSON_4)):
    skip("Apt 91215 pairing", "Material/Smile files not present")
else:
    import json as _json4
    with open(SABRINA_PDF_4, "rb") as fh:
        parsed4 = sc.parse_sabrina_pdf(fh.read())
    with open(PORTAL_JSON_4, encoding="utf-8") as fh:
        portal4 = _json4.load(fh)

    check("[4] all labels found", parsed4["labels_not_found"], [])
    check("[4] the sheet says Non-Duplicate", parsed4["fields"]["cob"], "Non-Duplicate")
    check("[4] the sheet says 1X1Year for D0274",
          parsed4["benefit_rows"]["d0274"]["frequency"], "1X1Year")

    res4 = sc.compare_sabrina_to_portal(parsed4, portal4)
    rows4 = {r["key"]: r for s in res4["sections"] for r in s["rows"]}
    check("[4] coordination of benefits now matches",
          (rows4["cob"]["portal"], rows4["cob"]["status"]), ("Non-Duplication", "match"))
    check("[4] the age-split bitewing frequency now matches",
          rows4["d0274__freq"]["status"], "match")
    check("[4] and says which clause was applied",
          "patient is" in rows4["d0274__freq"]["note"], True)

    # One genuine error remains: the sheet carries D1110's service date on the
    # D4910 row (03/30/2023) where the portal has 04/14/26.
    check("[4] the genuine history error is still reported",
          sorted(r["key"] for r in res4["mismatches"]), ["d4910__hist"])
    check("[4] D1110's own history matches", rows4["d1110__hist"]["status"], "match")


# ══════════════════════════════════════════════════════════════════════════════
#  1h. CIGNA — the first Cigna pairing
# ══════════════════════════════════════════════════════════════════════════════
#
# A Cigna export is shaped nothing like MetLife's; `new_plan` translates it into
# the shared contract, and the audit runs its derived readers against that
# translation. Before that, every derived field read "not on portal" for every
# Cigna patient. Four separate faults were found on this one pairing:
#
#   · the general annual maximum was discarded because its class description
#     mentions Implants (the exclusion is meant for implant-ONLY maxima), so
#     Yearly Max and Paid to Date had no value at all
#   · "Not Applicable" — Cigna's way of saying a procedure has no frequency
#     limit — sat in the blank-value vocabulary and was thrown away, leaving 13
#     Frequency rows unstated against a sheet that said "No Frequency"
#   · OON Benefits is derivable from the OONET coinsurance rows
#   · the orthodontic deductible is explicitly not a deductible class here, and
#     the ortho age limit is a plan-level statement rather than a D8080 field

print("── 1h. CIGNA PAIRING (Matthew Herzwurm) ──")

# Unit-level: the pieces that were broken, independent of the fixture files.
# This is Cigna's wording, so it is checked against Cigna's own copy of the
# vocabulary — the one a Cigna audit uses.
from smile_partners.sabrina.carriers.cigna import compare as cg_compare, vocabulary as cg_vocab

check("cigna: 'Not Applicable' means no frequency limit",
      cg_vocab._num_frequency("Not Applicable"), ("unlimited",))
check("cigna: and is not treated as a blank for a frequency",
      cg_vocab._blank_for("frequency", "Not Applicable"), False)
check("cigna: it still reads as blank for other kinds",
      cg_vocab._blank_for("money", "Not Applicable"), True)
check("cigna: 'No benefits for this service' is not-covered, not no-limit",
      cg_vocab._num_frequency("No benefits for this service"), ("not covered",))
check("cigna: 'Exclude after age 18' is an upper bound of 18",
      cg_vocab._num_agelimit("Exclude after age 18"), 18)
check("cigna: sheet 18 matches an 'Exclude after age 18' limit",
      cg_compare._compare("agelimit", "18", "Exclude after age 18")[0], True)

# A multi-class annual maximum must survive the ortho/implant exclusion.
from smile_partners.portals.cigna import _cigna_general_annual_record as _annual
_NET = {"id": "P0010", "name": "TOTAL"}
_MIXED = [{"desc": "Individual Calendar Year Maximum", "amount": "$2,000.00",
           "met": "$222.20", "remaining": "$1,777.80", "covers": "IND",
           "networkId": "P0010", "networkName": "TOTAL",
           "classCode": "1,2,3,9",
           "classDesc": "Diagnostic and Preventive,Basic Restorative,"
                        "Major Restorative,Implants"}]
check("cigna: a maximum covering implants alongside general classes is kept",
      _annual(_MIXED, _NET).get("amount"), "$2,000.00")
_ORTHO_ONLY = [{"desc": "Individual Calendar Year Maximum", "amount": "$1,000.00",
                "covers": "IND", "networkId": "P0010", "networkName": "TOTAL",
                "classCode": "4", "classDesc": "Orthodontics"}]
check("cigna: an ortho-only maximum is still excluded",
      _annual(_ORTHO_ONLY, _NET), {})
_TMJ_ONLY = [{"desc": "Individual Calendar Year Maximum", "amount": "$1,000.00",
              "covers": "IND", "networkId": "P0010", "networkName": "TOTAL",
              "classCode": "5", "classDesc": "TMJ"}]
check("cigna: a TMJ-only maximum is excluded too", _annual(_TMJ_ONLY, _NET), {})

# ── the real pairing ───────────────────────────────────────────────────────
if not (os.path.exists(SABRINA_PDF_5) and os.path.exists(PORTAL_JSON_5)):
    skip("Cigna pairing", "Material/Smile Cigna files not present")
else:
    import json as _json5
    with open(SABRINA_PDF_5, "rb") as fh:
        parsed5 = sc.parse_sabrina_pdf(fh.read())
    with open(PORTAL_JSON_5, encoding="utf-8") as fh:
        portal5 = _json5.load(fh)

    check("[5] the sheet parses whole", parsed5["labels_not_found"], [])
    check("[5] it is a Cigna sheet", parsed5["fields"]["ins_name"], "Cigna DPPO")

    check("[5] the export is recognized as Cigna",
          sc._portal_normalized(portal5).get("_source_insurer"), "cigna")
    check("[5] and is translated into the shared contract",
          "metlife_data" in sc._portal_normalized(portal5), True)

    res5 = sc.compare_sabrina_to_portal(parsed5, portal5)
    rows5 = {r["key"]: r for s in res5["sections"] for r in s["rows"]}

    # The financials that had no value at all before.
    check("[5] yearly maximum now compares",
          (rows5["yearly_max"]["portal"], rows5["yearly_max"]["status"]),
          ("2,000.00", "match"))
    check("[5] paid to date now compares",
          (rows5["yearly_max_paid"]["portal"], rows5["yearly_max_paid"]["status"]),
          ("222.20", "match"))
    check("[5] individual deductible matches", rows5["indiv_ded"]["status"], "match")
    check("[5] family deductible matches", rows5["family_ded"]["status"], "match")

    # Derived readers that were dark for every Cigna patient.
    check("[5] coordination of benefits defaults to Standard",
          (rows5["cob"]["portal"], rows5["cob"]["status"]), ("Standard", "match"))
    check("[5] OON benefits derived from the OONET rows",
          (rows5["oon_benefits"]["portal"], rows5["oon_benefits"]["status"]),
          ("Yes", "match"))
    check("[5] preventive-in-maximum from the maximum's class list",
          (rows5["prev_in_max"]["portal"], rows5["prev_in_max"]["status"]),
          ("Yes", "match"))
    check("[5] in network matches", rows5["in_network"]["status"], "match")
    check("[5] ortho deductible is 0 where ortho is not a deductible class",
          (rows5["ortho_ded"]["portal"], rows5["ortho_ded"]["status"]), ("0.00", "match"))
    check("[5] ortho age limit read from the plan's age table",
          rows5["ortho_coverage__age"]["status"], "match")

    # The frequency rows that "Not Applicable" was hiding.
    for key in ("d2391__freq", "d4341__freq", "d9310__freq", "d9110__freq"):
        check(f"[5] {key} compares as no-limit", rows5[key]["status"], "match")

    # Nothing should be reported as blank on the sheet.
    check("[5] nothing reported blank on the sheet",
          res5["summary"]["missing_in_sabrina"], 0)

    # Rule 5 — the three preventive codes the portal calls "not covered" take
    # their limits from Frequency & Limitations and the Preventive percentage.
    for key in ("d1206", "d1208", "d1351"):
        check(f"[5] {key} percentage matches", rows5[key]["status"], "match")
        check(f"[5] {key} frequency matches", rows5[f"{key}__freq"]["status"], "match")
        check(f"[5] {key} age limit matches", rows5[f"{key}__age"]["status"], "match")

    # Rule 6 — D1510 is not covered here, so it is left unstated rather than
    # reported as a 0% conflict against the sheet's 100%.
    for key in ("d1510", "d1510__freq", "d1510__age"):
        check(f"[5] {key} left unstated", rows5[key]["status"], "not_in_portal")

    # D7140 is the one real disagreement left: Cigna's per-code lookup says the
    # member pays 0% (plan 100%) where the sheet records 80%.
    check("[5] D7140 is the only remaining mismatch",
          sorted(r["key"] for r in res5["mismatches"]), ["d7140"])

    # Started at 92.2% before any of this work.
    check_true("[5] match rate", res5["summary"]["match_rate"] >= 99.0,
               f"rate={res5['summary']['match_rate']}")
    check("[5] fields compared", res5["summary"]["compared"], 116)

    # The codes Cigna was never asked about stay honestly unstated until the
    # extension rebuild reaches the team.
    for key in ("d2980", "d5212", "d5899", "d5995"):
        check(f"[5] {key} still unstated (code not requested)",
              rows5[key]["status"], "not_in_portal")


# ══════════════════════════════════════════════════════════════════════════════
#  1i. CIGNA RULES — the seven-point specification
# ══════════════════════════════════════════════════════════════════════════════
#
# Built on a payload reproducing the real Herzwurm export, so these hold even
# when the sample files are not on disk.

print("── 1i. CIGNA RULES ──")


def _cigna_proc(code, covered, member="", freq=""):
    return {"procedure_code": code, "covered": covered,
            "benefit_status": "Covered" if covered else "Not a covered service",
            "coinsurance_member_pct": member, "frequency_limit": freq,
            "history_date": "No history on file"}


def _cigna_payload(**over):
    payload = {
        "source": "Cigna Portal",
        "summary": {"patient_id": "U1", "group_number": "3345921",
                    "group_name": "ACME", "plan_type": "DENTAL PPO"},
        "patient": {"name": "Sample Patient", "dob": "02/16/1995",
                    "relationship": "Subscriber"},
        "plan_details": {"account_name": "ACME", "account_number": "3345921",
                         "plan_type": "DENTAL PPO", "subscriber": "Sample Patient",
                         "network": {"id": "P0010", "name": "TOTAL"}},
        "financials": {
            "maximum_records": [
                {"desc": "Individual Calendar Year Maximum", "amount": "$2,000.00",
                 "met": "$222.20", "remaining": "$1,777.80", "covers": "IND",
                 "networkId": "P0010", "networkName": "TOTAL", "classCode": "1,2,3,9",
                 "classDesc": "Diagnostic and Preventive,Basic Restorative,"
                              "Major Restorative,Implants"}],
            "deductible_records": [],
            "deductible_applicability": {"class_codes": ["2", "3", "5", "9"],
                                         "orthodontic": False},
        },
        "coinsurance": [
            {"network": "TOTAL", "network_id": "P0010",
             "category": "Diagnostic and Preventive", "patient_pays": "0%"},
            {"network": "OONET", "network_id": "OONET",
             "category": "Diagnostic and Preventive", "patient_pays": "0%"},
        ],
        "frequencies": [
            {"network": "TOTAL", "procedure_code": "D1208",
             "procedure": "Topical Fluoride", "age_limitation": "Exclude after age 18",
             "limit": "Once Per Calendar Year"},
            {"network": "TOTAL", "procedure_code": "D1351",
             "procedure": "Topical Sealant Application",
             "age_limitation": "Exclude after age 13",
             "limit": "Once Per 36 Consecutive Months"},
        ],
        "age_limits": [{"network": "TOTAL", "type": "Ortho Age Limitation **",
                        "age": "None"}],
        "notes": {"missing_tooth": "Does not apply"},
        "procedures": {"results": [
            _cigna_proc("D1206", False, "50%", "No benefits for this service"),
            _cigna_proc("D1208", False, "50%", "No benefits for this service"),
            _cigna_proc("D1351", False, "50%", "No benefits for this service"),
            _cigna_proc("D1510", False, "50%", "No benefits for this service"),
            _cigna_proc("D0120", True, "0%", "Twice Per Calendar Year"),
        ]},
    }
    payload.update(over)
    return payload


_CG = _cigna_payload()
_CG_NORM = sc._portal_normalized(_CG)
_CG_BD = sc._portal_breakdown(_CG)


def _cg_portal(key, aspect=None, bd=None, norm=None):
    want = f"{key}__{aspect}" if aspect else key
    field = next(f for f in sc._SPEC if f["key"] == want)
    return sc._portal_value(field, bd or _CG_BD, norm or _CG_NORM, None)


# Rule 1 — the network dropdown offering Out-of-Network is the answer.
check("cigna rule 1: an Out-of-Network option means OON benefits",
      sc._cigna_oon_benefits(_CG_NORM), "Yes")
_no_oon = _cigna_payload(coinsurance=[
    {"network": "TOTAL", "network_id": "P0010",
     "category": "Diagnostic and Preventive", "patient_pays": "0%"}])
check("cigna rule 1: no Out-of-Network option means none",
      sc._cigna_oon_benefits(sc._portal_normalized(_no_oon)), "No")
_oon_zero = _cigna_payload(coinsurance=[
    {"network": "TOTAL", "network_id": "P0010",
     "category": "Diagnostic and Preventive", "patient_pays": "0%"},
    {"network": "OONET", "network_id": "OONET",
     "category": "Diagnostic and Preventive", "patient_pays": "100%"}])
check("cigna rule 1: the option existing decides it, not what it pays",
      sc._cigna_oon_benefits(sc._portal_normalized(_oon_zero)), "Yes")

# Rule 2 — the calendar-year maximum and its remaining amount.
check("cigna rule 2: yearly maximum", _CG_BD.get("yearly_max"), "2,000.00")
check("cigna rule 2: paid to date is total less remaining",
      sc._portal_yearly_max_paid(_CG_BD, _CG_NORM), "222.20")

# Rule 3 — no ortho deductible means 0.
check("cigna rule 3: ortho deductible is 0 when ortho is not a deductible class",
      sc._portal_ortho_ded(_CG_BD, _CG_NORM), "0.00")
check("cigna rule 3: and the met amount likewise",
      sc._portal_ortho_ded_met(_CG_BD, _CG_NORM), "0.00")

# Rule 4 — Preventive named in Benefit Maximums.
check("cigna rule 4: preventive named in the maximum's classes",
      sc._portal_prev_in_max(_CG_BD, _CG_NORM), "Yes")
_no_prev = _cigna_payload()
_no_prev["financials"]["maximum_records"][0]["classDesc"] = \
    "Basic Restorative,Major Restorative"
check("cigna rule 4: and No when it is not",
      sc._portal_prev_in_max(sc._portal_breakdown(_no_prev),
                             sc._portal_normalized(_no_prev)), "No")

# Rule 5 — D1206 / D1208 / D1351 fall back to Frequency & Limitations, with
# the Preventive percentage.
for code in ("d1206", "d1208", "d1351"):
    check(f"cigna rule 5: {code} takes the preventive percentage",
          _cg_portal(code), "100%")
check("cigna rule 5: D1206 borrows the fluoride frequency row",
      _cg_portal("d1206", "freq"), "Once Per Calendar Year")
check("cigna rule 5: D1206 borrows its age limit too",
      _cg_portal("d1206", "age"), "Exclude after age 18")
check("cigna rule 5: D1351 uses its own row",
      _cg_portal("d1351", "freq"), "Once Per 36 Consecutive Months")
check("cigna rule 5: a sheet of 100% / 1X1Year / 18 matches D1206",
      (sc._compare("pct", "100%", _cg_portal("d1206"))[0],
       sc._compare("frequency", "1X1Year", _cg_portal("d1206", "freq"))[0],
       sc._compare("agelimit", "18", _cg_portal("d1206", "age"))[0]),
      (True, True, True))
check("cigna rule 5: a sheet of 100% / 1X36Months / 13 matches D1351",
      (sc._compare("pct", "100%", _cg_portal("d1351"))[0],
       sc._compare("frequency", "1X36Months", _cg_portal("d1351", "freq"))[0],
       sc._compare("agelimit", "13", _cg_portal("d1351", "age"))[0]),
      (True, True, True))

# Rule 6 — D1510 is left unstated when not covered; 99 when no age is given.
check("cigna rule 6: D1510 not covered is left unstated",
      (_cg_portal("d1510"), _cg_portal("d1510", "freq"), _cg_portal("d1510", "age")),
      (None, None, None))
_d1510_covered = _cigna_payload()
_d1510_covered["procedures"]["results"] = [
    _cigna_proc("D1510", True, "0%", "Once Per Lifetime")]
_bd6 = sc._portal_breakdown(_d1510_covered)
_nm6 = sc._portal_normalized(_d1510_covered)
check("cigna rule 6: a covered D1510 reports its percentage",
      _cg_portal("d1510", None, _bd6, _nm6), "100%")
check("cigna rule 6: and its frequency",
      _cg_portal("d1510", "freq", _bd6, _nm6), "Once Per Lifetime")
check("cigna rule 6: an unstated age limit becomes 99",
      _cg_portal("d1510", "age", _bd6, _nm6), "99")

# Cigna's frequency wording, including spelled-out counts and "Consecutive".
for sheet, portal in [("1X36Months", "Once Per 36 Consecutive Months"),
                      ("1X60Months", "Once Per 60 Consecutive Months"),
                      ("2X1Year", "Twice Per Calendar Year"),
                      ("4X1Year", "Four Times Per Calendar Year"),
                      ("3X1Year", "Three Times Per Calendar Year"),
                      ("1XLifetime", "Once Per Lifetime")]:
    check(f"cigna frequency {sheet!r} vs {portal!r}",
          sc._compare("frequency", sheet, portal)[0], True)
check("cigna frequency: a real difference still shows",
      sc._compare("frequency", "2X1Year", "Once Per Calendar Year")[0], False)

# Codes outside the rules are untouched.
check("cigna: an ordinary code keeps its own percentage", _cg_portal("d0120"), "100%")
check("cigna: and its own frequency",
      _cg_portal("d0120", "freq"), "Twice Per Calendar Year")


# ══════════════════════════════════════════════════════════════════════════════
#  1j. METLIFE — Aaren Boyd
# ══════════════════════════════════════════════════════════════════════════════
#
# Reported: D5212 and D2980 never reach the UI although the site covers both.
# They are simply not requested — the scraper asks for 61 codes and neither is
# among them (BATCH_8 restores them). Two audit-side gaps showed up alongside:
#
#   · the Benefit Maximums category line is captured as annual_max.description,
#     but the audit only looked for `applies_to`, so "Preventative Included in
#     Yearly Max?" read as unstated
#   · the portal writes "—" in Late Date Of Service where a procedure has never
#     been performed, which is what the sheet writes as "NH"; treating that as
#     an empty cell left four history rows unstated

print("── 1j. METLIFE PAIRING (Aaren Boyd) ──")

# The Annual card's category line, however the scraper labelled it.
_ANNUAL_DESC = {"metlife_data": {"financials": {"annual_max": {
    "description": "for Diagnostic, Preventive, Restorative, Endodontics, "
                   "Prosthodontics, Oral Surgery, Adjunctive, Implant Services"}}}}
check("metlife: preventive read from annual_max.description",
      sc._portal_prev_in_max({}, _ANNUAL_DESC), "Yes")
_ANNUAL_OLD = {"metlife_data": {"financials": {"annual_max": {
    "applies_to": "Diagnostic, Preventive, Restorative"}}}}
check("metlife: the older applies_to spelling still works",
      sc._portal_prev_in_max({}, _ANNUAL_OLD), "Yes")
_ANNUAL_NO_PREV = {"metlife_data": {"financials": {"annual_max": {
    "description": "for Basic Restorative, Major Restorative"}}}}
check("metlife: and No when preventive is not named",
      sc._portal_prev_in_max({}, _ANNUAL_NO_PREV), "No")

# The portal's dash says "never performed".
check("history: the portal dash means no history", sc._num_history("\u2014"), "NONE")
check("history: sheet NH against the portal dash agrees",
      sc._compare("history", "NH", "\u2014")[0], True)
check("history: a sheet date against the portal dash is a finding",
      sc._compare("history", "02/18/2026", "\u2014")[0], False)
check("history: that finding is explained",
      "no history" in sc._compare("history", "02/18/2026", "\u2014")[1], True)
check("history: the dash is not blank for a history row",
      sc._blank_for("history", "\u2014"), False)
check("history: it is still blank for money",
      sc._blank_for("money", "\u2014"), True)

if not (os.path.exists(SABRINA_PDF_6) and os.path.exists(PORTAL_JSON_6)):
    skip("Aaren Boyd pairing", "Material/Smile files not present")
else:
    import json as _json6
    with open(SABRINA_PDF_6, "rb") as fh:
        parsed6 = sc.parse_sabrina_pdf(fh.read())
    with open(PORTAL_JSON_6, encoding="utf-8") as fh:
        portal6 = _json6.load(fh)

    check("[6] the sheet parses whole", parsed6["labels_not_found"], [])
    check("[6] the sheet records D5212", parsed6["benefit_rows"]["d5212"]["percentage"], "50%")
    check("[6] and D2980", parsed6["benefit_rows"]["d2980"]["percentage"], "50%")

    res6 = sc.compare_sabrina_to_portal(parsed6, portal6)
    rows6 = {r["key"]: r for s in res6["sections"] for r in s["rows"]}

    check("[6] preventive-in-maximum now compares",
          (rows6["prev_in_max"]["portal"], rows6["prev_in_max"]["status"]),
          ("Yes", "match"))
    for key in ("d1206__hist", "d1208__hist", "d1351__hist", "d4341__hist"):
        check(f"[6] {key} agrees (NH against the portal dash)",
              rows6[key]["status"], "match")

    # The same copied perio date as Tudor and Amanda Wilson.
    check("[6] the copied perio date is the only disagreement",
          sorted(r["key"] for r in res6["mismatches"]), ["d4910__hist"])
    check("[6] D1110 keeps its own date", rows6["d1110__hist"]["status"], "match")

    # D5212/D2980 stay unstated until the extension rebuild reaches the team.
    for key in ("d2980", "d5212", "d5899", "d5995"):
        check(f"[6] {key} unstated until the code is requested",
              rows6[key]["status"], "not_in_portal")

    check("[6] nothing reported blank on the sheet",
          res6["summary"]["missing_in_sabrina"], 0)
    check_true("[6] match rate", res6["summary"]["match_rate"] >= 99.0,
               f"rate={res6['summary']['match_rate']}")


# ══════════════════════════════════════════════════════════════════════════════
#  1k. DELTA DENTAL — the first Delta Dental pairing
# ══════════════════════════════════════════════════════════════════════════════
#
# Delta Dental's export is shaped nothing like MetLife's — tabs (overview /
# plan_provisions / benefits_search / treatment_history), eligibility,
# primary_patient — and there was no normalizer for it, so `_extract` fell
# through to the MetLife-shaped generic path and read almost nothing: 120 of
# 128 rows came back "not on portal" with only 5 compared.
#
# `_normalize_dd_portal` translates it into the shared contract. Everything
# below is Delta-Dental-only; no other carrier's path was touched.

print("── 1k. DELTA DENTAL PAIRING (Jason Knezevich) ──")

from smile_partners.portals.delta_dental import (_dd_age_limit, _dd_frequency, _is_dd_portal,
                      _normalize_dd_portal)

# Delta states limits in prose; the sheet uses the compact form.
for prose, compact in [
        ("Benefit is limited to any three oral evaluation procedures within a "
         "calendar year.", "3X1Year"),
        ("Benefit is limited to one problem focused evaluation per provider "
         "within a 12 month period", "1X12Months"),
        ("Benefit is limited to once per quadrant within a 24 month period.", "1X24Months"),
        ("Benefit is limited to two of either D4910 or D4346 within a calendar "
         "year", "2X1Year"),
]:
    check(f"delta frequency {compact}", _dd_frequency(prose), compact)
check("delta frequency: 'Limitations apply' states no countable limit",
      _dd_frequency("Limitations apply"), "")
check("delta frequency: professional determination is the sheet's Pre-D",
      _dd_frequency("Benefit is based on professional determination"), "Pre-D")
# Caleb Phillips' D0150: the "Limitations apply" panel adds a per-provider
# lifetime sentence after the calendar-year limit, and the year limit stands.
check("delta frequency: a later per-provider lifetime sentence does not win",
      _dd_frequency("Benefit is limited to two of any oral evaluation procedure "
                    "within a calendar year This procedure is a benefit once per "
                    "provider per lifetime."), "2X1Year")
check("delta frequency: a lifetime stated before any period still wins",
      _dd_frequency("Benefit is limited to once per lifetime"), "1XLifetime")

# Delta states only that the deductible does NOT apply; a card that is silent
# means it applies, once the export carries the footnote reader's keys at all.
from smile_partners.portals.delta_dental import _dd_deductible_applies
check("delta deductible: footnoted out of the deductible",
      _dd_deductible_applies({"code": "D0120", "applies_to_deductible": "No"}), "No")
check("delta deductible: no footnote on the search means it applies",
      _dd_deductible_applies({"code": "D0120", "applies_to_deductible": ""}), "Yes")
check("delta deductible: an export older than the footnote reader stays unstated",
      _dd_deductible_applies({"code": "D0120"}), "")
# The compact form Delta yields must compare equal to the sheet's wording.
check("delta frequency: 5 year period matches the sheet's 1X5Years",
      sc._compare("frequency",
                  "1X5Years",
                  _dd_frequency("Benefit is limited to one crown procedure per "
                                "tooth within a 5 year period"))[0], True)

check("delta age: 'None' is no restriction", _dd_age_limit("None"), "99")
check("delta age: a child limit names its number",
      _dd_age_limit("Child up to and not including age 14"), "14")
check("delta age: '12 years and older'", _dd_age_limit("12 years and older"), "12")

# History states several dates and is shared across codes.
check("history: two lists sharing a date describe the same treatment",
      sc._compare("history", "02/18/2026, 03/24/2026",
                  "03/24/2026, 08/15/2025")[0], True)
check("history: a single date still compares exactly",
      sc._compare("history", "02/18/2026", "02/18/26")[0], True)
check("history: genuinely different single dates still disagree",
      sc._compare("history", "02/18/2026", "03/24/2026")[0], False)
check("history: NH against a portal dash still agrees",
      sc._compare("history", "NH", "\u2014")[0], True)

if not (os.path.exists(SABRINA_PDF_7) and os.path.exists(PORTAL_JSON_7)):
    skip("Delta Dental pairing", "Material/Smile Delta Dental files not present")
else:
    import json as _json7
    with open(SABRINA_PDF_7, "rb") as fh:
        parsed7 = sc.parse_sabrina_pdf(fh.read())
    with open(PORTAL_JSON_7, encoding="utf-8") as fh:
        portal7 = _json7.load(fh)

    check("[7] the sheet parses whole", parsed7["labels_not_found"], [])
    check("[7] the export is recognized as Delta Dental", _is_dd_portal(portal7), True)
    check("[7] and is translated into the shared contract",
          "metlife_data" in sc._portal_normalized(portal7), True)
    check("[7] the audit sees it as Delta Dental",
          sc._portal_normalized(portal7).get("_source_insurer"), "delta dental")

    res7 = sc.compare_sabrina_to_portal(parsed7, portal7)
    rows7 = {r["key"]: r for s in res7["sections"] for r in s["rows"]}

    # Identity and insurance, none of which was readable before.
    for key in ("patient_name", "patient_dob", "member_id", "group_name",
                "group_number", "ins_address", "payor_id", "eff_date",
                "ins_name", "in_network", "oon_benefits"):
        check(f"[7] {key} compares", rows7[key]["status"], "match")

    # The plan year comes from the maximum's accumulation period, not the
    # member's effective date (which would have said November).
    check("[7] plan year from the accumulation period",
          (rows7["plan_year_start"]["portal"], rows7["plan_year_start"]["status"]),
          ("January", "match"))

    # Financials.
    check("[7] yearly maximum", rows7["yearly_max"]["status"], "match")
    check("[7] paid to date", rows7["yearly_max_paid"]["status"], "match")
    check("[7] an empty deductible table means zero",
          rows7["indiv_ded"]["status"], "match")
    check("[7] ortho maximum from the lifetime record",
          rows7["ortho_max"]["status"], "match")

    # Provisions, in Delta's own wording.
    check("[7] coordination of benefits", rows7["cob"]["status"], "match")
    check("[7] missing tooth clause", rows7["missing_tooth"]["status"], "match")
    check("[7] preventive is NOT in this plan's yearly maximum",
          (rows7["prev_in_max"]["portal"], rows7["prev_in_max"]["status"]),
          ("No", "match"))

    # Category percentages come from the codes the sheet names, not from the
    # category ranges ("Restorative 60% - 80%" would have reported 60%).
    check("[7] basic percentage from the code, not the range",
          (rows7["pct_basic"]["portal"], rows7["pct_basic"]["status"]), ("80%", "match"))
    check("[7] major percentage", rows7["pct_major"]["status"], "match")
    check("[7] preventive percentage", rows7["pct_prev"]["status"], "match")

    # Service dates shared across a limitation set.
    check("[7] the panoramic date reaches the FMX row",
          rows7["d0210__hist"]["status"], "match")
    check("[7] the fluoride dates reach both fluoride codes",
          (rows7["d1206__hist"]["status"], rows7["d1208__hist"]["status"]),
          ("match", "match"))

    check("[7] nothing reported blank on the sheet",
          res7["summary"]["missing_in_sabrina"], 0)
    check("[7] no disagreements", res7["summary"]["mismatches"], 0)
    check_true("[7] fields compared", res7["summary"]["compared"] >= 106,
               f"compared={res7['summary']['compared']}")
    check("[7] match rate", res7["summary"]["match_rate"], 100.0)


# ══════════════════════════════════════════════════════════════════════════════
#  1l. DELTA DENTAL — the Carlos Evans observations
# ══════════════════════════════════════════════════════════════════════════════
#
# A second Delta Dental plan, and one that exercises most of the carrier's
# limitation vocabulary. Everything checked here is stated on the portal; the
# rows Delta genuinely leaves unsaid stay unsaid.

print("── 1l. DELTA DENTAL (Carlos Evans) ──")

from smile_partners.portals.delta_dental import _dd_maximum, _dd_not_covered

# The rest of Delta's limitation wording, each taken verbatim off a card.
for prose, compact in [
        ("Benefit is limited to once per lifetime Limitations apply", "1XLifetime"),
        ("Benefit is limited to once per tooth per lifetime Limitations apply", "1XLifetime"),
        ("For this program, this procedure has no frequency limitation "
         "Limitations apply", "No Frequency"),
        ("Benefit is limited to once per quadrant within two calendar years. "
         "Requires radiographs and periodontal charting.", "1X2Years"),
        ("Benefit is limited to one occlusal guard within 3 calendar years", "1X3Years"),
        ("Benefit is limited to twice per tooth within a 5 year period", "2X5Years"),
        ("Benefit is limited to once within a 5 year period", "1X5Years"),
        ("Benefit is limited to once per date of service", "1X1Day"),
        ("Benefit is limited to once per arch per date of service", "1X1Day"),
        ("Benefit is limited to once within a 12 month period", "1X12Months"),
        ("This procedure is not a benefit of most Delta Dental plans. "
         "The fee is the patient's responsibility.", "NC"),
        ("This procedure code could not be recognized.", "NC"),
        ("Benefit is based on professional determination", "Pre-D"),
        ("Limitations apply", ""),
        ("Benefit is limited by other services performed on same date", ""),
]:
    check(f"delta frequency {compact or 'unstated'!r}", _dd_frequency(prose), compact)

# Delta Dental INS (Anshunette Mccoy) states some limits over a "contract
# period" — the plan's benefit year — which the sheet records as years.
for prose, compact in [
        ("Benefit is limited to two within a contract period", "2X1Year"),
        ("Benefit is limited to once within a contract period", "1X1Year"),
        ("Benefit is limited to four periapical films within a contract period", "4X1Year"),
        ("Benefit is limited to once per tooth within a 3 contract period for "
         "teeth without caries Limitations apply", "1X3Years"),
        ("Benefit is limited to once within two contract periods", "1X2Years"),
]:
    check(f"delta frequency contract period {compact}", _dd_frequency(prose), compact)

# Delta Dental INS (Sierjah Richards) limits D0140 over days.
check("delta frequency: 30 day period -> 1X30Days",
      _dd_frequency("Benefit is limited to one problem focused evaluation within a 30 day period"),
      "1X30Days")
check("delta frequency: the sheet's 1x30Days agrees",
      sc._compare("frequency", "1x30Days",
                  _dd_frequency("Benefit is limited to one problem focused evaluation "
                                "within a 30 day period"))[0], True)
check("delta frequency: a 1 day period -> 1X1Day",
      _dd_frequency("Benefit is limited to once within a 1 day period"), "1X1Day")
check("delta frequency: 'within 30 days of' another service is not a period",
      _dd_frequency("Benefit is limited to once per tooth. Not a benefit within 30 days of "
                    "root canal therapy"), "")

# Delta does not state the two clause answers; the sheet derives them from
# D2740's coverage and D4910's limitation.
from sabrina_compare import _portal_major_paid_on, _portal_perio_after_srp


def _dd_codes(*entries):
    return _normalize_dd_portal({"source": "Delta Dental", "primary_patient": {"name": "X"},
                                 "tabs": {"benefits_search": list(entries)}})


def _dd_entry(code, level, limitation):
    return {"code": code, "benefit_level": level,
            "rows": [{"description": "x", "limitation": limitation}]}


_D4910_30_DAYS = ("Benefit is limited to two of any prophylaxis procedures within a calendar "
                  "year for codes D1110, D1120, D4346, D4355, and D4910. Prophylaxis procedures "
                  "are a benefit following active periodontal therapy once a 30 day "
                  "post-operative period has completed.")

check("delta major paid on: D2740 covered -> Seat Date",
      _portal_major_paid_on({}, _dd_codes(_dd_entry("D2740", "50%", "once per tooth within a 7 year period"))),
      "Seat Date")
check("delta major paid on: D2740 not a benefit -> blank",
      _portal_major_paid_on({}, _dd_codes(_dd_entry(
          "D2740", "N/A", "This procedure is not a benefit of most Delta Dental plans."))),
      None)
check("delta major paid on: D2740 never searched -> blank",
      _portal_major_paid_on({}, _dd_codes(_dd_entry("D0120", "100%", "None"))), None)
check("delta perio after SRP: D4910 names a 30 day post-operative period",
      _portal_perio_after_srp({}, _dd_codes(_dd_entry("D4910", "100%", _D4910_30_DAYS))), "30 Days")
check("delta perio after SRP: the sheet's '30 days' agrees",
      sc._compare("text", "30 days",
                  _portal_perio_after_srp({}, _dd_codes(_dd_entry("D4910", "100%", _D4910_30_DAYS))))[0],
      True)
check("delta perio after SRP: D4910 names no period -> Not available in website",
      _portal_perio_after_srp({}, _dd_codes(_dd_entry(
          "D4910", "100%", "Benefit is limited to two within a calendar year"))),
      "Not available in website")
check("delta perio after SRP: D4910 never searched -> not stated",
      _portal_perio_after_srp({}, _dd_codes(_dd_entry("D0120", "100%", "None"))), None)
# A wrapped History cell is read in full in a Delta audit and nowhere else.
from smile_partners.sabrina.carriers.delta_dental.rules import _dd_wrapped_history

_WRAPPED_SHEET = {
    "fields": {"d1110__hist": "06/10/2026,"},
    "benefit_rows": {"d1110": {"history": "06/10/2026,",
                               "history_wrapped": "06/10/2026, 01/29/2026"}},
}
_D1110_TWO_VISITS = {"code": "D1110", "benefit_level": "100%",
                     "rows": [{"description": "Prophylaxis (cleaning) - adult",
                               "limitation": "Benefit is limited to two within a calendar year",
                               "service_date": "06/10/2026, 01/29/2026"}]}

check("history: a Delta audit reads the wrapped D1110 cell in full",
      _dd_wrapped_history(_WRAPPED_SHEET["fields"], _WRAPPED_SHEET["benefit_rows"],
                          _dd_codes(_D1110_TWO_VISITS))["d1110__hist"],
      "06/10/2026, 01/29/2026")
check("history: a non-Delta audit keeps the first line",
      _dd_wrapped_history(_WRAPPED_SHEET["fields"], _WRAPPED_SHEET["benefit_rows"],
                          {"metlife_data": {}})["d1110__hist"],
      "06/10/2026,")
check("history: the parsed sheet itself is not changed",
      _WRAPPED_SHEET["fields"]["d1110__hist"], "06/10/2026,")
_dd_hist_audit = sc.compare_sabrina_to_portal(
    _WRAPPED_SHEET, {"source": "Delta Dental", "primary_patient": {"name": "X"},
                     "tabs": {"benefits_search": [_D1110_TWO_VISITS]}})
_dd_hist_rows = {r["key"]: r for s in _dd_hist_audit["sections"] for r in s["rows"]}
check("history: the Delta audit shows both D1110 dates on the Sabrina side",
      _dd_hist_rows["d1110__hist"]["sabrina"], "06/10/2026, 01/29/2026")
check("history: and they match the portal exactly",
      (_dd_hist_rows["d1110__hist"]["status"], _dd_hist_rows["d1110__hist"]["note"]), ("match", ""))

# Delta Dental INS (Cristina Gomez): maximums split by network, several
# orthodontic lifetime maximums, and a code Delta does not recognise.
_ALL_TYPES = ["Diagnostic", "Preventive", "Restorative", "Endodontics"]
_PPO = "Delta Dental PPO Dentist"
_PREMIER = "Delta Dental Premier Dentist"
_NON_DELTA = "Non-Delta Dental Dentist (Benefits based on contract allowance)"


def _dd_max(kind, types, networks, amount):
    return {"type": kind, "treatment_types": types, "networks": networks,
            "amount": amount, "used": "$0.00", "remaining": amount}


_GOMEZ_MAXIMUMS = [
    _dd_max("Calendar Individual Maximum Accumulation period for this program (1/1/2026 - 12/31/2026)",
            _ALL_TYPES, [_PREMIER, _NON_DELTA], "$1,500.00"),
    _dd_max("Calendar Individual Maximum Accumulation period for this program (1/1/2026 - 12/31/2026)",
            _ALL_TYPES, [_PPO], "$1,700.00"),
    _dd_max("Lifetime Individual Maximum", ["Adjunctive General Services", "Temporomandibular Joint (TMJ)"],
            [_PPO, _PREMIER, _NON_DELTA], "$500.00"),
    _dd_max("Lifetime Individual Maximum", ["Orthodontics", "Oral & Maxillofacial Surgery"],
            [_PPO, _PREMIER, _NON_DELTA], "$1,500.00"),
    _dd_max("Lifetime Individual Maximum", ["Orthodontics", "Oral & Maxillofacial Surgery"],
            [_PPO, _PREMIER, _NON_DELTA], "$500.00"),
]


def _gomez(network, maximums=_GOMEZ_MAXIMUMS, plan=""):
    tabs = {"overview": {"maximums": maximums}, "benefits_search": []}
    if network:
        tabs["benefits_search_network"] = network
    fin = _normalize_dd_portal({"source": "Delta Dental", "primary_patient": {"name": "X", "plan": plan},
                                "tabs": tabs})["metlife_data"]["financials"]
    return fin["annual_max"]["total"], fin["ortho_lifetime"]["total"]


check("delta annual max: a PPO search takes the PPO-only maximum",
      _gomez(_PPO)[0], "$1,700.00")
check("delta annual max: an out-of-network search takes the Premier / Non-Delta maximum",
      _gomez("Non-Delta Dental Dentist")[0], "$1,500.00")
check("delta annual max: no network recorded keeps the old choice",
      _gomez("")[0], "$1,500.00")
check("delta annual max: an older export without the network uses the plan's (PPO)",
      _gomez("", plan="Delta Dental PPO"), ("$1,700.00", "$1,500.00"))
check("delta ortho lifetime max: the highest naming Orthodontics, not the TMJ one",
      _gomez(_PPO)[1], "$1,500.00")
check("delta ortho lifetime max: no orthodontic maximum keeps the first lifetime one",
      _gomez(_PPO, _GOMEZ_MAXIMUMS[:3])[1], "$500.00")

_D1351_UNRECOGNISED = {"code": "D1351", "benefit_level": "N/A",
                       "rows": [{"description": "This procedure code could not be recognized.",
                                 "limitation": "None", "age_limits": "None"}]}


def _d1351_age(sheet_age):
    audit = sc.compare_sabrina_to_portal(
        {"fields": {"d1351": "0", "d1351__age": sheet_age}, "benefit_rows": {}},
        {"source": "Delta Dental", "primary_patient": {"name": "X"},
         "tabs": {"benefits_search": [_D1351_UNRECOGNISED]}})
    row = {r["key"]: r for s in audit["sections"] for r in s["rows"]}["d1351__age"]
    return row["status"], row["portal"]


check("delta age: a code Delta does not cover is age 0, not 99", _d1351_age("0"), ("match", "0"))
check("delta age: a blank sheet age agrees for a code Delta does not cover",
      _d1351_age(None), ("not_stated", None))
check("delta age: a sheet reading 99 for an uncovered code is a mismatch",
      _d1351_age("99"), ("mismatch", "0"))

# Delta Dental INS (Mohsen Moghaddam): a composite paid only at the amalgam
# benefit is a downgrade, and an age range is recorded by its highest age.
_D2160_COVERED = _dd_entry("D2160", "80%", "Benefit is limited to once per surface, per tooth "
                                           "within a 24 month period Limitations apply")
_D2140_COVERED = _dd_entry("D2140", "80%", "Benefit is limited to once per surface, per tooth "
                                           "within a 24 month period")
_D2391_ALTERNATE = _dd_entry("D2391", "N/A",
                             "When this procedure does not display in Benefit Details, it is not "
                             "a benefit of the member's plan. When amalgam restorations are a "
                             "benefit, the applicable amalgam benefit will be applied.")
_D2391_COVERED = _dd_entry("D2391", "80%", "Benefit is limited to once per surface, per tooth "
                                           "within a 24 month period")


def _downgrade(*entries):
    return sc._portal_breakdown({"source": "Delta Dental", "primary_patient": {"name": "X"},
                                 "tabs": {"benefits_search": list(entries)}}
                                ).get("posterior_composite_downgrade")


check("delta downgrade: D2391 paid at the amalgam benefit -> Yes",
      _downgrade(_D2160_COVERED, _D2140_COVERED, _D2391_ALTERNATE), "Yes")
check("delta downgrade: also when D2140 was not searched",
      _downgrade(_D2160_COVERED, _D2391_ALTERNATE), "Yes")
check("delta downgrade: both covered in their own right -> No",
      _downgrade(_D2160_COVERED, _D2140_COVERED, _D2391_COVERED), "No")

check("delta age: a range is recorded by its highest age", _dd_age_limit("age 6 to 18"), "18")
check("delta age: a hyphenated range too", _dd_age_limit("Ages 6-18"), "18")
check("delta age: the sheet's 18 matches 'age 6 to 18'",
      sc._compare("agelimit", "18", _dd_age_limit("age 6 to 18"))[0], True)
check("delta age: an upper bound alone is unchanged",
      _dd_age_limit("Child up to and not including age 19"), "19")

# Delta Dental INS (Brady Wilson): a per-provider lifetime limit stated before
# the yearly one, and orthodontics Delta does not recognise.
_D9310_TWO_LIMITS = ("Benefit is limited to one occurrence per provider per lifetime Benefit is "
                     "limited to two of any oral evaluation procedure within a calendar year")
check("delta frequency: a yearly limit outranks a lifetime one stated before it",
      _dd_frequency(_D9310_TWO_LIMITS), "2X1Year")
check("delta frequency: and one stated after it (D0150)",
      _dd_frequency("Benefit is limited to two of any oral evaluation procedure within a calendar "
                    "year This procedure is a benefit once per provider per lifetime."), "2X1Year")
# Delta Dental INS (Deion Reid) says "within THE contract period".
check("delta frequency: 'within the contract period' is a year",
      _dd_frequency("Benefit is limited to any two oral evaluation procedures within the "
                    "contract period. Comprehensive evaluations are limited to once per provider."),
      "2X1Year")
check("delta frequency: D0150's lifetime sentence does not override 'the contract period'",
      _dd_frequency("Benefit is limited to any two oral evaluation procedures within the contract "
                    "period. Comprehensive evaluations are limited to once per provider. This "
                    "procedure is a benefit once per provider per lifetime."), "2X1Year")
check("delta frequency: three prophylaxis procedures within the contract period",
      _dd_frequency("Benefit is limited to three of any prophylaxis procedures within the contract "
                    "period for codes D1110, D1120, D4346, D4355, and D4910. Prophylaxis procedures "
                    "are a benefit following active periodontal therapy once a 30 day "
                    "post-operative period has completed."), "3X1Year")
check("delta frequency: a lifetime limit alone is still lifetime",
      _dd_frequency("Benefit is limited to once per quadrant per lifetime"), "1XLifetime")
check("delta frequency: a limit with no period beside a yearly one gives the yearly one",
      _dd_frequency("Comprehensive evaluations are limited to once per provider. Benefit is "
                    "limited to three of any oral evaluation procedure within a calendar year"),
      "3X1Year")


def _ortho_age(sheet_age):
    unrecognised = {"code": "D8080", "benefit_level": "N/A",
                    "rows": [{"description": "This procedure code could not be recognized.",
                              "limitation": "None", "age_limits": "None"}]}
    audit = sc.compare_sabrina_to_portal(
        {"fields": {"ortho_coverage": "0", "ortho_coverage__age": sheet_age}, "benefit_rows": {}},
        {"source": "Delta Dental", "primary_patient": {"name": "X"},
         "tabs": {"benefits_search": [unrecognised]}})
    row = {r["key"]: r for s in audit["sections"] for r in s["rows"]}["ortho_coverage__age"]
    return row["status"], row["portal"]


check("delta ortho age: orthodontics Delta does not cover is age 0", _ortho_age("0"), ("match", "0"))
check("delta ortho age: a blank sheet age agrees", _ortho_age(None), ("not_stated", None))

# Delta Dental INS (appointment 120147, Frances Wilson): the orthodontic
# deductible is a lifetime deductible that also names Diagnostic, beside the
# lifetime maximum covering the same three types.
from smile_partners.sabrina.carriers.delta_dental.compare import _compare as _dd_compare
_GENERAL_TYPES = ["Diagnostic", "Endodontics", "Oral & Maxillofacial Surgery", "Restorative"]
_LIFETIME_ORTHO_DED = {"type": "Lifetime Individual Deductible",
                       "treatment_types": ["Diagnostic", "Orthodontics", "Oral & Maxillofacial Surgery"],
                       "amount": "$50.00", "used": "$0.00", "remaining": "$50.00"}
_CAL_INDIVIDUAL = {"type": "Calendar Individual Deductible Accumulation period for this program",
                   "treatment_types": _GENERAL_TYPES, "amount": "$25.00", "used": "$25.00",
                   "remaining": "$0.00"}


def _ded_bd(deductibles):
    return sc._portal_breakdown({"source": "Delta Dental", "primary_patient": {"name": "X"},
                                 "tabs": {"overview": {"deductibles": deductibles},
                                          "benefits_search": []}})


_bd_120147 = _ded_bd([_CAL_INDIVIDUAL, _LIFETIME_ORTHO_DED])
check("delta ortho deductible: a lifetime deductible naming Orthodontics is the ortho one",
      (_bd_120147.get("ortho_ded"), _bd_120147.get("ortho_ded_paid")), ("50.00", "0.00"))
# Mary Crocker (2026-10-23): only a LIFETIME deductible naming Orthodontics is
# the sheet's Orthodontics Deductible. A calendar one covering Orthodontics and
# Oral Surgery is not recorded there — and is still not the general deductible.
_CAL_ORTHO_DED = {"type": "Calendar Individual Deductible Accumulation period for this program",
                  "treatment_types": ["Orthodontics", "Oral & Maxillofacial Surgery"],
                  "amount": "$50.00", "used": "$0.00", "remaining": "$50.00"}
_bd_crocker = _ded_bd([_CAL_INDIVIDUAL, _CAL_ORTHO_DED])
check("delta ortho deductible: a calendar deductible naming Orthodontics is not the ortho one",
      _bd_crocker.get("ortho_ded"), "0.00")
check("delta ortho deductible: nor is it taken for the general deductible",
      _bd_crocker.get("indiv_ded"), "25.00")
check("delta ortho deductible: a lifetime one beside it is still read",
      _ded_bd([_CAL_INDIVIDUAL, _CAL_ORTHO_DED, _LIFETIME_ORTHO_DED]).get("ortho_ded"), "50.00")
check("delta ortho deductible: the calendar deductible is still the individual one",
      _ded_bd([_LIFETIME_ORTHO_DED, _CAL_INDIVIDUAL]).get("indiv_ded"), "25.00")
check("delta text: the sheet's '30days' is the portal's '30 Days'",
      _dd_compare("text", "30days", "30 Days")[0], True)
check("delta text: different numbers still differ",
      _dd_compare("text", "60days", "30 Days")[0], False)

# Delta Dental INS (James Melear Jr, appointment 113246): the deductible is
# split by provider network, and the sheet records the out-of-network one for
# an out-of-network office — as the percentages already are.
_PPO_PREMIER = ["Delta Dental PPO Dentist", "Delta Dental Premier Dentist"]
_NON_DELTA_ONLY = ["Non-Delta Dental Dentist (Benefits based on contract allowance)"]


def _split_ded(kind, networks, amount):
    return {"type": f"Calendar {kind} Deductible Accumulation period for this program",
            "treatment_types": _GENERAL_TYPES, "networks": networks,
            "amount": amount, "used": "$0.00", "remaining": amount}


_MELEAR_DEDS = [_split_ded("Family", _PPO_PREMIER, "$150.00"),
                _split_ded("Family", _NON_DELTA_ONLY, "$225.00"),
                _split_ded("Individual", _PPO_PREMIER, "$50.00"),
                _split_ded("Individual", _NON_DELTA_ONLY, "$75.00")]


def _melear(network):
    tabs = {"overview": {"deductibles": _MELEAR_DEDS}, "benefits_search": []}
    if network:
        tabs["benefits_search_network"] = network
    bd = sc._portal_breakdown({"source": "Delta Dental",
                               "primary_patient": {"name": "X", "plan": "Delta Dental PPO"},
                               "tabs": tabs})
    return bd.get("indiv_ded"), bd.get("family_ded")


check("delta deductible: an out-of-network search takes the Non-Delta deductibles",
      _melear("Non-Delta Dental Dentist"), ("75.00", "225.00"))
check("delta deductible: a PPO search takes the PPO / Premier deductibles",
      _melear("Delta Dental PPO Dentist"), ("50.00", "150.00"))
check("delta deductible: no network recorded uses the plan's (PPO)",
      _melear(""), ("50.00", "150.00"))

# Brian Jones: the plan lists deductibles for Premier and Non-Delta dentists
# only, so a PPO office has none — not the other networks' $100 / $300.
_PREMIER_NON_DELTA = ["Delta Dental Premier Dentist",
                      "Non-Delta Dental Dentist (Benefits based on contract allowance)"]
_JONES_DEDS = [_split_ded("Family", _PREMIER_NON_DELTA, "$300.00"),
               _split_ded("Individual", _PREMIER_NON_DELTA, "$100.00")]


def _jones(network):
    no_footnote = [dict(_dd_entry(code, "100%", "Benefit is limited to two within a calendar year"),
                        applies_to_deductible="Yes", applies_to_maximum="Yes")
                   for code in ("D0120", "D0220")]
    tabs = {"overview": {"deductibles": _JONES_DEDS}, "benefits_search": no_footnote}
    if network:
        tabs["benefits_search_network"] = network
    bd = sc._portal_breakdown({"source": "Delta Dental",
                               "primary_patient": {"name": "X", "plan": "Delta Dental PPO"},
                               "tabs": tabs})
    return bd.get("indiv_ded"), bd.get("family_ded"), bd.get("ded_prev"), bd.get("ded_diag")


check("delta deductible: no PPO deductible listed -> a PPO office has $0 and No / No",
      _jones("Delta Dental PPO Dentist"), ("0.00", "0.00", "No", "No"))
check("delta deductible: the same plan with no network recorded is read as the plan's PPO",
      _jones(""), ("0.00", "0.00", "No", "No"))
check("delta deductible: a Premier office pays the listed deductible",
      _jones("Delta Dental Premier Dentist")[:2], ("100.00", "300.00"))
check("delta deductible: so does an out-of-network office",
      _jones("Non-Delta Dental Dentist")[:2], ("100.00", "300.00"))
_no_networks = [dict(r, networks=[]) for r in _JONES_DEDS]
check("delta deductible: records that name no network keep the old reading",
      _ded_bd(_no_networks).get("indiv_ded"), "100.00")
check("delta frequency: 'is a benefit once within a 3 year period' (D0150)",
      _dd_frequency("This procedure is a benefit once per provider per lifetime. This procedure "
                    "is a benefit once within a 3 year period and is included as part of the oral "
                    "evaluation limitations of your program"), "1X3Years")
# Delta Dental INS (Kaley Banta, appointment 121581): a $0 deductible applies
# to nothing, so Deductible Applies to Preventative / Diagnostic is "No" even
# where no footnote exempts D0120 / D0220.
_D0120_NO_FOOTNOTE = dict(_dd_entry("D0120", "100%", "Benefit is limited to two within a calendar year"),
                          applies_to_deductible="Yes", applies_to_maximum="Yes")
_D0220_NO_FOOTNOTE = dict(_dd_entry("D0220", "100%", "Benefit is limited to four within a calendar year"),
                          applies_to_deductible="Yes", applies_to_maximum="Yes")


def _ded_applies(deductibles):
    bd = sc._portal_breakdown({"source": "Delta Dental", "primary_patient": {"name": "X"},
                               "tabs": {"overview": {"deductibles": deductibles},
                                        "benefits_search": [_D0120_NO_FOOTNOTE, _D0220_NO_FOOTNOTE]}})
    return bd.get("ded_prev"), bd.get("ded_diag")


check("delta deductible applies: no deductible at all -> No / No", _ded_applies([]), ("No", "No"))
check("delta deductible applies: a stated $0 deductible -> No / No",
      _ded_applies([_split_ded("Individual", _PPO_PREMIER, "$0.00")]), ("No", "No"))
check("delta deductible applies: a real deductible keeps the footnote answer",
      _ded_applies([_split_ded("Individual", _PPO_PREMIER, "$50.00")]), ("Yes", "Yes"))
check("delta deductible applies: no Deductibles table scraped keeps the footnote answer",
      _ded_applies(None), ("Yes", "Yes"))
# History records only the service dates that affect the frequency (agreed
# with the team after Deion Reid: bitewings last taken 01/07/2020 are NH).
from smile_partners.sabrina.carriers.delta_dental.rules import _dd_history_in_window


def _hist(limitation, dates, scraped="2026-10-06T18:29:37.364Z", period_start="1/1/2026",
          calendar=True):
    norm = _dd_codes(_dd_entry("D0274", "100%", limitation))
    norm["_dd_meta"]["scraped_on"] = scraped
    norm["_dd_meta"]["benefit_period_start"] = period_start
    norm["_dd_meta"]["benefit_period_calendar"] = calendar
    return _dd_history_in_window(dates, norm, ("D0274",))


_YEARLY = "Benefit is limited to one within a calendar year"
check("delta history: a date before this benefit year does not count against 1X1Year",
      _hist(_YEARLY, "01/07/2020"), (True, "—"))
check("delta history: only this benefit year's dates count",
      _hist("Benefit is limited to any two oral evaluation procedures within the contract period",
            "01/07/2020, 04/01/2026, 05/10/2018"), (True, "04/01/2026"))
check("delta history: NX5Years keeps the last five years",
      _hist("Benefit is limited to once within a 5 year period", "06/01/2020, 11/01/2021"),
      (True, "11/01/2021"))
check("delta history: NX24Months keeps the last 24 months",
      _hist("Benefit is limited to once per quadrant within a 24 month period",
            "04/21/2026, 03/22/2022, 11/02/2024"), (True, "04/21/2026, 11/02/2024"))
check("delta history: a lifetime limit keeps every date",
      _hist("Benefit is limited to once per tooth per lifetime", "01/07/2010"), (False, "01/07/2010"))
check("delta history: a plan not marked calendar-year, no period printed -> last 12 months",
      _hist(_YEARLY, "11/15/2025, 01/07/2020", period_start="", calendar=False),
      (True, "11/15/2025"))
check("delta history: a sheet NH agrees once the old date drops out",
      _dd_compare("history", "NH", _hist(_YEARLY, "01/07/2020")[1])[0], True)
# Calendar-year plan: the current calendar year. Fiscal-year plan: the last
# 12 months (agreed with the team). Read on 10/06/2026, a 11/15/2025 service
# is last calendar year but within 12 months.
check("delta history: a calendar-year plan counts only this calendar year",
      _hist(_YEARLY, "11/15/2025"), (True, "—"))
check("delta history: a fiscal-year plan counts the last 12 months",
      _hist(_YEARLY, "11/15/2025", period_start="7/1/2026", calendar=False), (True, "11/15/2025"))
check("delta history: a calendar-year plan with no period printed starts at 1 January",
      _hist(_YEARLY, "11/15/2025, 02/03/2026", period_start=""), (True, "02/03/2026"))


def _calendar_flag(kind):
    raw = {"source": "Delta Dental", "primary_patient": {"name": "X"},
           "tabs": {"overview": {"maximums": [
               {"type": f"{kind} Individual Maximum Accumulation period for this program "
                        "(7/1/2026 - 6/30/2027)", "treatment_types": ["Diagnostic"],
                "amount": "$1,000.00", "used": "$0.00", "remaining": "$1,000.00"}]},
                    "benefits_search": []}}
    return _normalize_dd_portal(raw)["_dd_meta"]["benefit_period_calendar"]


check("delta plan year: 'Calendar Individual Maximum' is a calendar-year plan",
      _calendar_flag("Calendar"), True)
check("delta plan year: any other maximum label is not",
      _calendar_flag("Plan Year"), False)

# Delta Dental INS: an in-network office is audited against the Premier
# Benefits Search when the sheet's fee schedule names Premier, and against PPO
# when it is a Premier Lite schedule (agreed with the team, 2026-10-14).
from smile_partners.sabrina.carriers.delta_dental.rules import (_dd_fee_schedule_network,
                                                                _dd_network_export)
for fee, want in [("GA - DD GP Premier B", "premier"),
                  ("CO - DD Prem Reg 2", "premier"),
                  ("#3 MI - DD LITE Pr Reg6", "ppo"),
                  ("#203 MI - DD PremLT Perio", "ppo"),
                  ("MI Delta Premier Lite Perio", "ppo"),
                  ("#99 MI Delta Premier Lite Region 4", "ppo"),
                  ("GA - DeltaDentaRC41", ""),
                  ("GA - General UCR", ""),
                  (None, "")]:
    check(f"delta fee schedule {fee!r} -> {want or 'neither'}", _dd_fee_schedule_network(fee), want)

_THREE_NETWORKS = {
    "source": "Delta Dental", "primary_patient": {"name": "X", "plan": "Delta Dental PPO"},
    "tabs": {
        "overview": {"maximums": [
            _dd_max("Calendar Individual Maximum Accumulation period for this program (1/1/2026 - 12/31/2026)",
                    _ALL_TYPES, [_PPO], "$1,700.00"),
            _dd_max("Calendar Individual Maximum Accumulation period for this program (1/1/2026 - 12/31/2026)",
                    _ALL_TYPES, [_PREMIER, _NON_DELTA], "$1,500.00")]},
        "benefits_search": [_dd_entry("D2160", "80%", "Benefit is limited to once per surface")],
        "benefits_search_network": "Delta Dental PPO Dentist",
        "benefits_search_oon": [_dd_entry("D2160", "50%", "Benefit is limited to once per surface")],
        "benefits_search_oon_network": "Non-Delta Dental Dentist",
        "benefits_search_premier": [_dd_entry("D2160", "70%", "Benefit is limited to once per surface")],
        "benefits_search_premier_network": "Delta Dental Premier Dentist",
    },
}


def _read_under(in_network, fee):
    tabs = _dd_network_export(_THREE_NETWORKS, in_network, fee)["tabs"]
    return tabs["benefits_search_network"], tabs["benefits_search"][0]["benefit_level"]


check("delta network: in-network with a Premier fee schedule reads Premier",
      _read_under("In", "GA - DD GP Premier B"), ("Delta Dental Premier Dentist", "70%"))
check("delta network: in-network with a Premier Lite fee schedule reads PPO",
      _read_under("In", "#203 MI - DD PremLT Perio"), ("Delta Dental PPO Dentist", "80%"))
check("delta network: in-network with any other fee schedule reads PPO",
      _read_under("In", "GA - DeltaDentaRC41"), ("Delta Dental PPO Dentist", "80%"))
check("delta network: out of network reads Non-Delta whatever the fee schedule",
      _read_under("Out", "GA - DD GP Premier B"), ("Non-Delta Dental Dentist", "50%"))
import copy as _copy_premier
_no_premier = _copy_premier.deepcopy(_THREE_NETWORKS)
del _no_premier["tabs"]["benefits_search_premier"]
check("delta network: an export without the Premier search stays with PPO",
      _dd_network_export(_no_premier, "In", "GA - DD GP Premier B")["tabs"]["benefits_search_network"],
      "Delta Dental PPO Dentist")


def _premier_audit(fee):
    audit = sc.compare_sabrina_to_portal(
        {"fields": {"in_network": "In", "d2160": "70%", "yearly_max": "1500"},
         "benefit_rows": {}, "fee_schedule": fee}, _THREE_NETWORKS)
    rows = {r["key"]: r for s in audit["sections"] for r in s["rows"]}
    return rows["d2160"]["portal"], rows["yearly_max"]["portal"], audit["diagnostics"].get("portal_network")


check("delta audit: a Premier sheet reads Premier percentages and the Premier maximum",
      _premier_audit("GA - DD GP Premier B"), ("70%", "1,500.00", "Delta Dental Premier Dentist"))
check("delta audit: a Premier Lite sheet reads PPO",
      _premier_audit("MI Delta Premier Lite Perio"), ("80%", "1,700.00", "Delta Dental PPO Dentist"))
from smile_partners.sabrina.carriers.delta_dental.parser import parse_sabrina_text as _dd_parse_text
_fee_parsed = _dd_parse_text("Group Number \n03668-02571\nFee Schedule \nGA - DD GP Premier B\n"
                             "Insurance Address \nP.O. Box 1809\n")
check("delta sheet: the fee schedule is read",
      _fee_parsed["fee_schedule"], "GA - DD GP Premier B")
check("delta sheet: the fee schedule is kept beside the fields, not among them",
      "fee_schedule" in _fee_parsed["fields"], False)

# Rachel Dent (2026-10-28): the sheet as the PDF extractor gives it. A page
# break cuts "D4910 Perio Maintenance" after "D4910 Perio" (its values stay on
# the first page, "Maintenance" is printed alone under the next page's table
# header), and the composite question wraps over four lines.
_RACHEL_TEXT = "\n".join([
    "Benefit Details", "D2391 Composite ", "Fillings", "1X24Months", "70%",
    "Are Posterior ", "Composites ", "Downgraded To ", "Amalgam?", "No",
    "D2740 Crowns", "1X5Years", "50%",
    "D4381 Arestin", "1X24Months", "70%",
    "D4910 Perio ", "4X1Year", "100%", "NH", "",
    "Benefit Name", "Frequency", "Percentage", "Coverage", "Age ", "Limit", "History",
    "Maintenance", "When Is First Perio ", "Maintenance Allowed ", "After SRP ?", "30 Days",
    "D5110 Dentures", "1X5Years", "50%",
])
_rachel = _dd_parse_text(_RACHEL_TEXT)["fields"]
check("delta sheet: a question wrapped over four lines is read",
      _rachel.get("posterior_composite_downgrade"), "No")
check("delta sheet: a row whose label a page break cut in two is read",
      (_rachel.get("d4910"), _rachel.get("d4910__freq"), _rachel.get("d4910__hist")),
      ("100%", "4X1Year", "NH"))
check("delta sheet: the row before it no longer takes its history",
      _rachel.get("d4381__hist"), None)
check("delta sheet: the question after the page break is still read",
      _rachel.get("perio_maint_after_srp"), "30 Days")
_rachel_whole = _dd_parse_text(_RACHEL_TEXT.replace("D4910 Perio \n", "D4910 Perio Maintenance\n")
                               .replace("History\nMaintenance\n", "History\n"))["fields"]
check("delta sheet: an unbroken label reads the same",
      (_rachel_whole.get("d4910"), _rachel_whole.get("d4910__freq")), ("100%", "4X1Year"))

# Raquel Goshe: the same page break cuts a question, and its remainder runs
# over two lines on the next page.
_raquel = _dd_parse_text("\n".join([
    "Benefit Details", "D4910 Perio Maintenance", "4X1Year", "100%",
    "11/07/2024, 07/03/2024,06/07/2023, 10/21/2022",
    "When Is First Perio ", "30 DAYS", "",
    "Benefit Name", "Frequency", "Percentage", "Coverage", "Age ", "Limit", "History",
    "Maintenance Allowed ", "After SRP ?",
    "D5110 Dentures", "1X5Years", "50%",
]))["fields"]
check("delta sheet: a question a page break cut over two lines is read",
      _raquel.get("perio_maint_after_srp"), "30 DAYS")
check("delta sheet: and the rows around it still read",
      (_raquel.get("d4910__freq"), _raquel.get("d5110")), ("4X1Year", "50%"))

# Andrew Barrs: the Overview tab never loaded, so the export carries no
# maximums, deductibles or benefits overview. Nothing there is $0 or March.
_no_overview_bd = sc._portal_breakdown({
    "source": "Delta Dental",
    "primary_patient": {"name": "X", "plan": "Delta Dental PPO",
                        "static_fields": {"Member eligibility": "03/01/2025 - present"}},
    "tabs": {"overview": {"deductible_applicability": {}}, "benefits_search": []}})
# (the breakdown writes an unstated value as "—", which the audit reads as blank)
check("delta overview missing: the deductibles are unstated, not $0",
      (_no_overview_bd.get("indiv_ded"), _no_overview_bd.get("family_ded")), ("—", "—"))
check("delta overview missing: the plan start month is not guessed from the effective date",
      _no_overview_bd.get("plan_year_start") in (None, "", "—"), True)
_no_ded_table_bd = sc._portal_breakdown({
    "source": "Delta Dental", "primary_patient": {"name": "X", "plan": "Delta Dental PPO"},
    "tabs": {"overview": {"maximums": [_dd_max(
        "Calendar Individual Maximum Accumulation period for this program (1/1/2026 - 12/31/2026)",
        _ALL_TYPES, [_PPO], "$1,000.00")]}, "benefits_search": []}})
check("delta overview read but no Deductibles table: still no deductible ($0)",
      _no_ded_table_bd.get("indiv_ded"), "0.00")
check("delta overview read: the plan start month comes from the maximum's period",
      _no_ded_table_bd.get("plan_year_start"), "January")

# Delta Dental INS (2026-10-16): the user picks the office's network in the
# extension's pop-up, only that network is searched, and the export says which.
from smile_partners.sabrina.carriers.delta_dental.rules import _dd_selected_network


def _picked(selected, level, label):
    return {"source": "Delta Dental", "primary_patient": {"name": "X", "plan": "Delta Dental PPO"},
            "tabs": {"benefits_search": [_dd_entry("D2160", level, "Benefit is limited to once per surface")],
                     "benefits_search_network": label, "benefits_search_selected": selected}}


_PICKED_OON = _picked("oon", "50%", "Non-Delta Dental Dentist")
check("delta pick: the export's choice is read", _dd_selected_network(_PICKED_OON), "oon")
check("delta pick: and through the translation, which keeps the raw export",
      _dd_selected_network({"_raw_export": _PICKED_OON}), "oon")
check("delta pick: an export from before the pop-up has none",
      _dd_selected_network(_THREE_NETWORKS), "")
check("delta pick: anything else is not a choice", _dd_selected_network(_picked("x", "", "")), "")
check("delta pick: the chosen search is used whatever the sheet's In Network says",
      _dd_network_export(_PICKED_OON, "In", "GA - DD GP Premier B")["tabs"]["benefits_search_network"],
      "Non-Delta Dental Dentist")


def _pick_audit(export, sheet):
    audit = sc.compare_sabrina_to_portal({"fields": sheet, "benefit_rows": {}}, export)
    return audit, {r["key"]: r for s in audit["sections"] for r in s["rows"]}


_, _rows_pick = _pick_audit(_PICKED_OON, {"in_network": "In", "d2160": "50%"})
check("delta pick: Out of Network chosen, sheet says In -> mismatch on In Network",
      (_rows_pick["in_network"]["portal"], _rows_pick["in_network"]["status"]), ("Out", "mismatch"))
check("delta pick: the codes are read under the chosen network",
      (_rows_pick["d2160"]["portal"], _rows_pick["d2160"]["status"]), ("50%", "match"))
_, _rows_pick = _pick_audit(_picked("premier", "70%", "Delta Dental Premier Dentist"),
                            {"in_network": "In", "d2160": "70%"})
check("delta pick: Premier chosen is in network",
      (_rows_pick["in_network"]["portal"], _rows_pick["in_network"]["status"]), ("In", "match"))

# A field the sheet leaves blank but the portal states is a mismatch (agreed
# with the team, 2026-10-16) — no longer a separate "blank on the sheet" count.
_blank_audit, _rows_blank = _pick_audit(_picked("ppo", "80%", "Delta Dental PPO Dentist"),
                                        {"in_network": "In"})
check("delta blank: a blank sheet value the portal states is a mismatch",
      (_rows_blank["d2160"]["status"], _rows_blank["d2160"]["portal"]), ("mismatch", "80%"))
check("delta blank: and is counted with the mismatches",
      (_blank_audit["summary"]["missing_in_sabrina"],
       any(r["key"] == "d2160" for r in _blank_audit["mismatches"])), (0, True))
_no_limit = _picked("ppo", "100%", "Delta Dental PPO Dentist")
_no_limit["tabs"]["benefits_search"] = [_dd_entry("D1110", "100%",
                                                  "For this program, this procedure has no frequency limitation")]
_, _rows_no_limit = _pick_audit(_no_limit, {"in_network": "In", "d1110": "100%"})
check("delta blank: a blank frequency against 'no frequency limitation' still agrees",
      _rows_no_limit["d1110__freq"]["status"], "match")


def _hist_vs_sheet(limitation, dates, sheet):
    norm = _dd_codes(_dd_entry("D0140", "100%", limitation))
    norm["_dd_meta"]["scraped_on"] = "2026-10-08T18:34:29.548Z"
    norm["_dd_meta"]["benefit_period_start"] = "1/1/2026"
    norm["_dd_meta"]["benefit_period_calendar"] = True
    value = _dd_history_in_window(dates, norm, ("D0140",), sheet)[1]
    return value, _dd_compare("history", sheet, value)[0]


# A sheet that lists dates is held to every date the portal has (Sandra Low
# Frigerio's D0140; appointment 120901's bitewings back to 2023).
_THIRTY_DAYS = "Benefit is limited to one problem focused evaluation within a 30 day period"
check("delta history: a sheet's date outside the window still matches (Sandra's D0140)",
      _hist_vs_sheet(_THIRTY_DAYS, "08/30/2024", "08/30/2024"), ("08/30/2024", True))
check("delta history: a sheet listing older years matches them (120901's D0274)",
      _hist_vs_sheet(_YEARLY, "08/22/2025, 06/12/2025, 08/16/2024, 10/10/2023",
                     "08/22/2025, 06/12/2025, 08/16/2024, 10/10/2023"),
      ("08/22/2025, 06/12/2025, 08/16/2024, 10/10/2023", True))
check("delta history: a blank sheet is held to the window like NH",
      _hist_vs_sheet(_YEARLY, "01/07/2020", None)[0], "—")
check("delta history: NH with a date inside the window is still a mismatch",
      _hist_vs_sheet(_YEARLY, "05/26/2026", "NH"), ("05/26/2026", False))
check("delta frequency: 'is not a benefit' is still not covered",
      _dd_frequency("This service is not a benefit of most Delta Dental plans."), "NC")

# Only a Delta export gets these answers.
check("major paid on: a non-Delta export is unchanged",
      _portal_major_paid_on({}, {"metlife_data": {}}), None)
check("perio after SRP: a non-Delta export is unchanged",
      _portal_perio_after_srp({}, {"metlife_data": {}}), None)

# The period belongs to the limit that states it. The labial-veneer note names
# twelve months and five years in exclusions that describe other procedures
# before stating the veneer's own limit.
check("delta frequency: the period is read from the limit, not the exclusions",
      _dd_frequency(
          "Labial Veneer benefits are determined by clinical conditions and "
          "subject to professional determination. Pre-Treatment Estimates are "
          "encouraged in advance of treatment being performed. They are not a "
          "benefit within 12 months of a basic restoration being placed on the "
          "same tooth. Replacement of a Labial Veneer is limited to once per "
          "tooth within a 5 year period. Limitations apply"),
      "1X5Years")

# A code is only called not covered where Delta withheld a benefit level too.
check("delta: no benefit level and 'not a benefit' means not covered",
      _dd_not_covered({"benefit_level": "N/A"},
                      {"limitation": "This procedure is not a benefit of most "
                                     "Delta Dental plans."}), True)
check("delta: a covered code whose prose mentions an exclusion is still covered",
      _dd_not_covered({"benefit_level": "60%"},
                      {"limitation": "They are not a benefit within 12 months "
                                     "of a basic restoration."}), False)
# Anshunette Mccoy / Caleb Phillips: D5899 is priced only by report, with no
# benefit level — the sheet's 0% and NC.
_BY_REPORT = ("This procedures requires a narrative report and description of "
              "the services provided to determine possible benefits.")
check("delta: a by-report code with no benefit level is not covered",
      _dd_not_covered({"benefit_level": "N/A"}, {"limitation": _BY_REPORT}), True)
check("delta: a by-report code that states a benefit level keeps it",
      _dd_not_covered({"benefit_level": "50%"}, {"limitation": _BY_REPORT}), False)

# Caleb Phillips: the extension searches every code under the plan's network
# and again under "Non-Delta Dental Dentist", and the sheet's "In Network"
# decides which one the codes are audited against.
import copy as _copy_net


def _dd_card(code, level, limitation):
    return {"code": code, "benefit_level": level, "deductible": "Applies",
            "applies_to_deductible": "", "applies_to_maximum": "",
            "rows": [{"description": code, "limitation": limitation,
                      "service_date": "None", "age_limits": "None",
                      "pre_approval": "None"}]}


_net_in = [
    _dd_card("D0120", "100%", "Benefit is limited to two of any oral evaluation "
                              "procedure within a calendar year"),
    _dd_card("D0150", "100%", "Benefit is limited to two of any oral evaluation "
                              "procedure within a calendar year This procedure "
                              "is a benefit once per provider per lifetime."),
    _dd_card("D5899", "N/A", _BY_REPORT),
]
_net_oon = _copy_net.deepcopy(_net_in)
_net_oon[1]["benefit_level"] = "50%"
_net_export = {
    "source": "Delta Dental",
    "primary_patient": {"name": "CALEB PHILLIPS", "plan": "Delta Dental PPO",
                        "static_fields": {"Member type": "Dependent",
                                          "Date of birth": "11/20/2007"}},
    "tabs": {
        "overview": {"benefits_overview": [
            {"treatment_type": "Diagnostic Oral Exams and X-Rays",
             "contract_benefit_level": "80% - 100%", "non_delta_dental": "50%"}]},
        "benefits_search": _net_in,
        "benefits_search_network": "Delta Dental PPO Dentist",
        "benefits_search_oon": _net_oon,
        "benefits_search_oon_network": "Non-Delta Dental Dentist",
    },
}


def _net_audit(in_network, export=_net_export):
    sheet = {"fields": {"in_network": in_network, "d0150": "50%",
                        "d0150__freq": "2X1Year", "d5899": "0",
                        "d5899__freq": "NC", "ded_prev": "Yes"}}
    res = sc.compare_sabrina_to_portal(sheet, export)
    return res, {r["key"]: r for s in res["sections"] for r in s["rows"]}


_res_out, _rows_out = _net_audit("Out")
check("delta network: an out-of-network sheet reads the non-Delta percentage",
      (_rows_out["d0150"]["portal"], _rows_out["d0150"]["status"]), ("50%", "match"))
check("delta network: and says which network it read",
      _res_out["diagnostics"]["portal_network"], "Non-Delta Dental Dentist")
check("delta network: the plan pays out of network, so 'Out' agrees",
      _rows_out["in_network"]["status"], "match")
check("delta network: D0150's per-provider lifetime does not override the year",
      (_rows_out["d0150__freq"]["portal"], _rows_out["d0150__freq"]["status"]),
      ("2X1Year", "match"))
check("delta network: D5899 by report is not covered",
      (_rows_out["d5899"]["portal"], _rows_out["d5899__freq"]["portal"]),
      ("Not Covered", "NC"))
check("delta network: no deductible footnote on D0120 means it applies",
      (_rows_out["ded_prev"]["portal"], _rows_out["ded_prev"]["status"]), ("Yes", "match"))

_res_in, _rows_in = _net_audit("In")
check("delta network: an in-network sheet keeps the plan network's percentage",
      _rows_in["d0150"]["portal"], "100%")
check("delta network: and says so",
      _res_in["diagnostics"]["portal_network"], "Delta Dental PPO Dentist")

_net_old = _copy_net.deepcopy(_net_export)
del _net_old["tabs"]["benefits_search_oon"]
_res_old, _rows_old = _net_audit("Out", _net_old)
check("delta network: without the second search the plan network still answers",
      _rows_old["d0150"]["portal"], "100%")
check("delta network: the export passed in is not altered",
      _net_export["tabs"]["benefits_search"][1]["benefit_level"], "100%")

# Two annual maximums: a narrow one and the one covering every service.
check("delta: the annual maximum is the one covering all services",
      _dd_maximum([
          {"type": "Calendar Individual Maximum", "amount": "$1,250.00",
           "treatment_types": ["Diagnostic"]},
          {"type": "Calendar Individual Maximum", "amount": "$2,500.00",
           "treatment_types": ["Diagnostic", "Preventive", "Restorative",
                               "Endodontics", "Periodontics"]},
      ], lifetime=False).get("amount"), "$2,500.00")
check("delta: a single annual maximum is still that maximum",
      _dd_maximum([{"type": "Calendar Individual Maximum", "amount": "$1,500.00"}],
                  lifetime=False).get("amount"), "$1,500.00")

# "Pre-D" is a frequency the sheet states, not an empty cell.
check("sheet: Pre-D reads as a frequency",
      sc._compare("frequency", "Pre-D",
                  "Benefit is based on professional determination")[0], True)
check("sheet: Pre-D is not the same as no limit at all",
      sc._compare("frequency", "Pre-D", "No Frequency")[0], False)

if not (os.path.exists(SABRINA_PDF_8) and os.path.exists(PORTAL_JSON_8)):
    skip("Carlos Evans pairing", "Material/Smile Carlos Evans files not present")
else:
    import json as _json8
    with open(SABRINA_PDF_8, "rb") as fh:
        parsed8 = sc.parse_sabrina_pdf(fh.read())
    with open(PORTAL_JSON_8, encoding="utf-8") as fh:
        portal8 = _json8.load(fh)

    check("[8] the sheet parses whole", parsed8["labels_not_found"], [])
    # The Frequency cell for D0220 reads "Pre-D"; it was being dropped as page
    # furniture and the column came through blank.
    check("[8] the sheet's Pre-D cell is read",
          parsed8["benefit_rows"]["d0220"]["frequency"], "Pre-D")

    res8 = sc.compare_sabrina_to_portal(parsed8, portal8)
    rows8 = {r["key"]: r for s in res8["sections"] for r in s["rows"]}

    # The plan carries two annual maximums; the sheet's is the general one.
    check("[8] the yearly maximum covers all services",
          (rows8["yearly_max"]["portal"], rows8["yearly_max"]["status"]),
          ("2,500.00", "match"))
    # Preventive is among the treatment types that maximum covers.
    check("[8] preventive draws down the yearly maximum",
          (rows8["prev_in_max"]["portal"], rows8["prev_in_max"]["status"]),
          ("Yes", "match"))
    # "DPO" is the network, not the carrier.
    check("[8] the carrier is named, not the network", rows8["ins_name"]["status"], "match")
    # Major services are paid for, so posterior crowns are not downgraded.
    check("[8] posterior crowns are not downgraded",
          (rows8["porcelain_posterior_downgrade"]["portal"],
           rows8["porcelain_posterior_downgrade"]["status"]), ("No", "match"))
    # Codes Delta does not pay for read as such rather than as silence.
    for key in ("d4381", "d9230"):
        check(f"[8] {key} is stated as not covered", rows8[key]["status"], "match")
    check("[8] D0220 compares as Pre-D",
          (rows8["d0220__freq"]["portal"], rows8["d0220__freq"]["status"]),
          ("Pre-D", "match"))
    # A sample of the wordings that were previously unreadable.
    for key in ("d1510__freq", "d2160__freq", "d2391__freq", "d4341__freq",
                "d4355__freq", "d9110__freq", "d9944__freq", "d4381__freq"):
        check(f"[8] {key} compares", rows8[key]["status"], "match")

    check("[8] nothing reported blank on the sheet",
          res8["summary"]["missing_in_sabrina"], 0)
    check("[8] no disagreements", res8["summary"]["mismatches"], 0)
    check_true("[8] fields compared", res8["summary"]["compared"] >= 115,
               f"compared={res8['summary']['compared']}")
    check("[8] match rate", res8["summary"]["match_rate"], 100.0)

    # ── what the updated scraper adds ─────────────────────────────────────
    # Five codes the sheet audits were never searched for, and the deductible
    # and maximum footnotes were never read. With both in the export — the
    # shape the updated content script produces — every row the sheet carries
    # can be answered except the two still hidden behind a limitation link.
    import copy as _copy8

    def _dd_row(description, limitation):
        return [{"description": description, "limitation": limitation,
                 "service_date": "None", "age_limits": "None",
                 "pre_approval": "None"}]

    scraped8 = _copy8.deepcopy(portal8)
    for _entry in scraped8["tabs"]["benefits_search"]:
        # Carlos's cards carry footnote 1 alone: the deductible does not come
        # out of the work, and the amount does count against the maximum.
        _entry["applies_to_deductible"] = "No"
        _entry["applies_to_maximum"] = "Yes"
    scraped8["tabs"]["benefits_search"] += [
        {"code": "D2160", "benefit_level": "80%", "deductible": "Applies",
         "applies_to_deductible": "No", "applies_to_maximum": "Yes",
         "rows": _dd_row("Amalgam - three surfaces",
                         "For this program, this procedure has no frequency "
                         "limitation Limitations apply")},
        {"code": "D2980", "benefit_level": "50%", "deductible": "Applies",
         "rows": _dd_row("Crown repair",
                         "Benefit is limited to twice per tooth within a 5 year period")},
        {"code": "D5212", "benefit_level": "50%", "deductible": "Applies",
         "rows": _dd_row("Partial denture - mandibular",
                         "Benefit is limited to once within a 5 year period")},
        {"code": "D5899", "benefit_level": "N/A", "deductible": "Applies",
         "rows": _dd_row("Unspecified removable prosthodontic procedure",
                         "This procedure is not a benefit of most Delta Dental "
                         "plans. The fee is the patient's responsibility.")},
        {"code": "D5995", "benefit_level": "N/A", "deductible": "Applies",
         "rows": _dd_row("Periodontal medicament carrier",
                         "This procedure is not a benefit of most Delta Dental "
                         "plans. The fee is the patient's responsibility.")},
    ]

    res8b = sc.compare_sabrina_to_portal(parsed8, scraped8)
    rows8b = {r["key"]: r for s in res8b["sections"] for r in s["rows"]}

    # The footnote under D0120 and D0220 answers both deductible questions.
    check("[8] the deductible is not taken out of preventive work",
          (rows8b["ded_prev"]["portal"], rows8b["ded_prev"]["status"]), ("No", "match"))
    check("[8] nor out of diagnostic work",
          (rows8b["ded_diag"]["portal"], rows8b["ded_diag"]["status"]), ("No", "match"))
    # Both codes of the pair are paid for, so nothing is downgraded.
    check("[8] posterior composites are not downgraded",
          (rows8b["posterior_composite_downgrade"]["portal"],
           rows8b["posterior_composite_downgrade"]["status"]), ("No", "match"))
    for key in ("d2980__freq", "d5212__freq", "d5899__freq", "d5995__freq"):
        check(f"[8] {key} compares", rows8b[key]["status"], "match")

    check("[8] no disagreements once the export is complete",
          res8b["summary"]["mismatches"], 0)
    check_true("[8] all but the two hidden limitations compare",
               res8b["summary"]["not_in_portal"] <= 2,
               f"not_in_portal={res8b['summary']['not_in_portal']}")

    # And the two that are hidden behind a link compare as soon as the link is
    # opened and the sentence read.
    for _entry in scraped8["tabs"]["benefits_search"]:
        if _entry["code"] in ("D0150", "D9310"):
            _entry["rows"][0]["limitation"] = (
                "Benefit is limited to two of any oral evaluation procedure "
                "within a calendar year")
    res8c = sc.compare_sabrina_to_portal(parsed8, scraped8)
    rows8c = {r["key"]: r for s in res8c["sections"] for r in s["rows"]}
    check("[8] the opened limitation answers D0150",
          (rows8c["d0150__freq"]["portal"], rows8c["d0150__freq"]["status"]),
          ("2X1Year", "match"))
    check("[8] and D9310",
          (rows8c["d9310__freq"]["portal"], rows8c["d9310__freq"]["status"]),
          ("2X1Year", "match"))
    check("[8] nothing is then left unanswered",
          res8c["summary"]["not_in_portal"], 0)
    check("[8] and the whole sheet agrees with the portal",
          (res8c["summary"]["mismatches"], res8c["summary"]["match_rate"]),
          (0, 100.0))


# ══════════════════════════════════════════════════════════════════════════════
#  1m. DELTA DENTAL — dependents, age bands, waiting periods, ortho deductible
# ══════════════════════════════════════════════════════════════════════════════

print("── 1m. DELTA DENTAL (Angela Cao / dependents) ──")

import datetime as _dt

from smile_partners.portals.delta_dental import (_apply_dd_output_rules, _dd_age_ceiling, _dd_best_row,
                      _dd_ortho_only, _dd_waiting_rows)

# ── age bands ─────────────────────────────────────────────────────────────
# Delta states a procedure once per age band. The sheet records the highest,
# and a band with no upper bound outranks every bounded one.
check("age band: a child ceiling is its number",
      _dd_age_ceiling("Child up to and not including age 9"), 9)
check("age band: 'None' has no ceiling",
      _dd_age_ceiling("None"), float("inf"))
check("age band: 'and older' states a floor, so the band has no ceiling",
      _dd_age_ceiling("18 years and older"), float("inf"))

sealant_rows = [{"age_limits": "Child up to and not including age 9"},
                {"age_limits": "Child up to and not including age 16"}]
check("rows: the highest age band governs",
      _dd_best_row(sealant_rows)["age_limits"],
      "Child up to and not including age 16")
check("rows: an unbounded band outranks a bounded one",
      _dd_best_row([{"age_limits": "Child up to and not including age 18",
                     "limitation": "Benefit is limited to two of any bitewing "
                                   "x-ray procedure within a calendar year"},
                    {"age_limits": "18 years and older",
                     "limitation": "Benefit is limited to one of any bitewing "
                                   "x-ray procedure within a calendar year"}]),
      {"age_limits": "18 years and older",
       "limitation": "Benefit is limited to one of any bitewing x-ray "
                     "procedure within a calendar year"})
check("rows: a single row is that row", _dd_best_row([{"age_limits": "None"}]),
      {"age_limits": "None"})

# ── member class ──────────────────────────────────────────────────────────
# Delta also splits a limit by who it covers, saying so at the end of the
# sentence. The sheet always records the subscriber's.
from smile_partners.portals.delta_dental import _dd_member_class
check("member class: the subscriber's row ranks highest",
      _dd_member_class({"limitation": "…rampant caries.For Subscriber and Spouse."}), 1)
check("member class: a dependents-only row ranks lowest",
      _dd_member_class({"limitation": "…rampant caries.For Dependents."}), -1)
check("member class: a row naming no class sits between them",
      _dd_member_class({"limitation": "Benefit is limited to twice within a calendar year"}), 0)
check("rows: the subscriber's limit wins over the dependents' one",
      _dd_best_row([
          {"age_limits": "None",
           "limitation": "Benefit is limited to two of any bitewing x-ray "
                         "procedure within a calendar year.For Dependents."},
          {"age_limits": "None",
           "limitation": "Benefit is limited to one of any bitewing x-ray "
                         "procedure within a calendar year.For Subscriber and Spouse."},
      ])["limitation"].endswith("For Subscriber and Spouse."), True)
check("rows: no rows is no row", _dd_best_row([]), {})

# ── the orthodontic deductible ────────────────────────────────────────────
# Most plans fold orthodontics into the ordinary deductible; only a record
# covering nothing else is a separate orthodontic one.
check("deductible: orthodontics alone is the ortho deductible",
      _dd_ortho_only({"treatment_types": ["Orthodontics"]}), True)
check("deductible: orthodontics with its surgery is still the ortho one",
      _dd_ortho_only({"treatment_types": ["Orthodontics",
                                          "Oral & Maxillofacial Surgery"]}), True)
check("deductible: orthodontics among the general categories is not",
      _dd_ortho_only({"treatment_types": ["Diagnostic", "Restorative",
                                          "Orthodontics", "Periodontics"]}), False)
check("deductible: a record without orthodontics is not",
      _dd_ortho_only({"treatment_types": ["Diagnostic", "Restorative"]}), False)

# ── waiting periods ───────────────────────────────────────────────────────
# Delta lists them with the dates the wait begins and ends; one that has not
# ended yet is a wait the patient is serving.
check("waiting periods: the older export's bare list is read",
      len(_dd_waiting_rows([{"waiting_period_ends": "01/01/2027"}])), 1)
check("waiting periods: the newer export's wrapper is read",
      len(_dd_waiting_rows({"rows": [{"waiting_period_ends": "01/01/2027"}],
                            "note": "x"})), 1)
check("waiting periods: an empty table is no rows", _dd_waiting_rows(None), [])

_today = _dt.date.today()
_ahead = (_today + _dt.timedelta(days=200)).strftime("%m/%d/%Y")
_begun = (_today - _dt.timedelta(days=165)).strftime("%m/%d/%Y")
_past = (_today - _dt.timedelta(days=30)).strftime("%m/%d/%Y")


def _waiting(rows):
    return _apply_dd_output_rules(
        {"waiting_period": "No", "waiting_period_mo": "0", "applies_to": ""},
        {"_dd_meta": {"waiting_period_rows": rows}})


check("waiting period: an end date still ahead is a wait being served",
      _waiting([{"waiting_period_begins": _begun, "waiting_period_ends": _ahead,
                 "treatments_and_procedures": [
                     {"treatment_type": "Restorative D2140, D2150"}]}])["waiting_period"],
      "Yes")
check("waiting period: and it names the work it applies to",
      _waiting([{"waiting_period_begins": _begun, "waiting_period_ends": _ahead,
                 "treatments_and_procedures": [
                     {"treatment_type": "Restorative D2140, D2150"}]}])["applies_to"],
      "Restorative")
check("waiting period: one that has run out is no longer served",
      _waiting([{"waiting_period_begins": _begun,
                 "waiting_period_ends": _past}])["waiting_period"], "No")
check("waiting period: no table at all leaves the shared answer alone",
      _waiting([])["waiting_period"], "No")

# ── a dependent's own details ─────────────────────────────────────────────
# `eligibility` is a page-wide sweep collapsed into one dictionary, so on a
# dependent's page the subscriber's card overwrites the patient's date of
# birth and member ID. The patient's own card is read instead.
if not os.path.exists(PORTAL_DEPENDENT):
    skip("dependent identity", "Material/Comparison/DD INS files not present")
else:
    import json as _json9
    with open(PORTAL_DEPENDENT, encoding="utf-8") as fh:
        dependent = _json9.load(fh)

    # What the page-wide sweep collected — the subscriber's, not the patient's.
    check("[dep] the page-wide sweep holds the subscriber's date of birth",
          dependent["eligibility"]["patient_dob"], "07/31/1956")
    check("[dep] and never names the subscriber",
          dependent["eligibility"]["subscriber_name"], "N/A")

    norm9 = sc._portal_normalized(dependent)
    check("[dep] the patient's own date of birth is read from their card",
          norm9["metlife_data"]["patient"]["dob"], "09/30/1957")
    # Delta numbers a family once and suffixes each member (…01 subscriber,
    # …02 dependent). The sheet's "Member ID#" is the policy number claims go
    # under, which is the subscriber's — Martin Sas's sheet records exactly
    # that for a dependent.
    check("[dep] the policy's member ID is the subscriber's",
          norm9["metlife_data"]["plan_details"]["subscriber_id"], "123487722301")
    check("[dep] the patient is recorded as a dependent",
          norm9["metlife_data"]["patient"]["relationship"], "Dependent")
    # The subscriber is named only on the Family members tab.
    check("[dep] the subscriber is found on the family members tab",
          (norm9["subscriber_info"]["name"], norm9["subscriber_info"]["dob"]),
          ("Pamela Klopp", "07/31/1956"))

# ── the Angela Cao pairing ────────────────────────────────────────────────
if not (os.path.exists(SABRINA_PDF_9) and os.path.exists(PORTAL_JSON_9)):
    skip("Angela Cao pairing", "Material/Smile Angela Cao files not present")
else:
    import json as _json9b
    with open(SABRINA_PDF_9, "rb") as fh:
        parsed9 = sc.parse_sabrina_pdf(fh.read())
    with open(PORTAL_JSON_9, encoding="utf-8") as fh:
        portal9 = _json9b.load(fh)

    check("[9] the sheet parses whole", parsed9["labels_not_found"], [])

    res9 = sc.compare_sabrina_to_portal(parsed9, portal9)
    rows9 = {r["key"]: r for s in res9["sections"] for r in s["rows"]}

    # The sealant is covered to age 9 in one band and 16 in another.
    check("[9] the sealant age is the higher band",
          (rows9["d1351__age"]["portal"], rows9["d1351__age"]["status"]),
          ("16", "match"))
    # Bitewings are once a year for an adult, twice for a child.
    check("[9] the adult bitewing frequency governs",
          (rows9["d0274__freq"]["portal"], rows9["d0274__freq"]["status"]),
          ("1X1Year", "match"))
    # This plan holds a deductible for orthodontics of its own.
    check("[9] the separate orthodontic deductible is read",
          (rows9["ortho_ded"]["portal"], rows9["ortho_ded"]["status"]),
          ("50.00", "match"))
    # …which must not have displaced the general one.
    check("[9] the general deductibles are untouched",
          (rows9["indiv_ded"]["status"], rows9["family_ded"]["status"]),
          ("match", "match"))

    # The waiting period is read from the dates the portal states, so what it
    # should say depends on the day this runs.
    _serving = _dt.date(2027, 7, 14) > _today
    check("[9] the waiting period follows the portal's own end dates",
          rows9["waiting_period"]["portal"], "Yes" if _serving else "No")

    # This sheet recorded the downgraded posterior composite as not covered,
    # where the portal says the amalgam benefit is applied in its place and
    # Martin Sas's sheet records that benefit. The disagreement is the sheet's
    # to settle, and the audit is right to raise it.
    check("[9] the composite recorded as not covered is raised",
          (rows9["d2391"]["sabrina"], rows9["d2391"]["portal"],
           rows9["d2391"]["status"]), ("0", "80%", "mismatch"))
    check("[9] and its frequency with it",
          (rows9["d2391__freq"]["sabrina"], rows9["d2391__freq"]["portal"],
           rows9["d2391__freq"]["status"]), ("NC", "1X24Months", "mismatch"))
    if _serving:
        check("[9] the composite is the only disagreement",
              res9["summary"]["mismatches"], 2)
        check_true("[9] fields compared", res9["summary"]["compared"] >= 115,
                   f"compared={res9['summary']['compared']}")
    check("[9] nothing reported blank on the sheet",
          res9["summary"]["missing_in_sabrina"], 0)


# ══════════════════════════════════════════════════════════════════════════════
#  1n. DELTA DENTAL — a dependent's sheet, and the downgraded composite
# ══════════════════════════════════════════════════════════════════════════════

print("── 1n. DELTA DENTAL (Martin Sas) ──")

from smile_partners.portals.delta_dental import _dd_alternate_benefit

# Delta does not refuse a posterior composite outright — it says the amalgam
# benefit is applied instead, which is a benefit the patient has.
check("alternate benefit: the substitution is recognized",
      _dd_alternate_benefit({"limitation":
          "When this procedure does not display in Benefit Details, it is not "
          "a benefit of the member's plan. When amalgam restorations are a "
          "benefit, the applicable amalgam benefit will be applied."}), True)
check("alternate benefit: a plain refusal is not a substitution",
      _dd_alternate_benefit({"limitation":
          "This procedure is not a benefit of most Delta Dental plans. "
          "The fee is the patient's responsibility."}), False)
check("alternate benefit: an unrecognized code is not a substitution",
      _dd_alternate_benefit({"limitation": "This procedure code could not be "
                                           "recognized."}), False)

if not (os.path.exists(SABRINA_PDF_10) and os.path.exists(PORTAL_JSON_10)):
    skip("Martin Sas pairing", "Material/Smile Martin Sas files not present")
else:
    import json as _json10
    with open(SABRINA_PDF_10, "rb") as fh:
        parsed10 = sc.parse_sabrina_pdf(fh.read())
    with open(PORTAL_JSON_10, encoding="utf-8") as fh:
        portal10 = _json10.load(fh)

    check("[10] the sheet parses whole", parsed10["labels_not_found"], [])

    # The page-wide sweep holds the subscriber's date of birth, as it does on
    # every dependent's page.
    check("[10] the sweep carries the subscriber's date of birth",
          portal10["eligibility"]["patient_dob"], "09/29/1956")

    res10 = sc.compare_sabrina_to_portal(parsed10, portal10)
    rows10 = {r["key"]: r for s in res10["sections"] for r in s["rows"]}

    # The patient is a dependent; his own card holds his date of birth, and
    # the subscriber is named only on the Family members tab.
    check("[10] the patient's own date of birth is compared",
          (rows10["patient_dob"]["portal"], rows10["patient_dob"]["status"]),
          ("10/07/1942", "match"))
    check("[10] the subscriber is named",
          (rows10["subscriber_name"]["portal"], rows10["subscriber_name"]["status"]),
          ("Melany Sas", "match"))
    check("[10] with the subscriber's own date of birth",
          (rows10["subscriber_dob"]["portal"], rows10["subscriber_dob"]["status"]),
          ("09/29/1956", "match"))
    # The sheet records the policy number, which is the subscriber's.
    check("[10] the member ID is the policy's",
          (rows10["member_id"]["portal"], rows10["member_id"]["status"]),
          ("119982604701", "match"))

    # The downgraded composite carries the amalgam benefit the portal names.
    check("[10] D2391 carries the amalgam percentage",
          (rows10["d2391"]["portal"], rows10["d2391"]["status"]), ("80%", "match"))
    check("[10] and the amalgam frequency",
          (rows10["d2391__freq"]["portal"], rows10["d2391__freq"]["status"]),
          ("1X24Months", "match"))

    # Two rows disagree, and both are the sheet's to correct rather than ours.
    check("[10] the payer ID the portal prints is reported",
          (rows10["payor_id"]["sabrina"], rows10["payor_id"]["portal"],
           rows10["payor_id"]["status"]), ("DDGA1", "94276", "mismatch"))
    check("[10] the separate orthodontic deductible is reported",
          (rows10["ortho_ded"]["sabrina"], rows10["ortho_ded"]["portal"],
           rows10["ortho_ded"]["status"]), ("0", "50.00", "mismatch"))

    check("[10] nothing reported blank on the sheet",
          res10["summary"]["missing_in_sabrina"], 0)
    check("[10] the two findings are the only disagreements",
          res10["summary"]["mismatches"], 2)
    check_true("[10] fields compared", res10["summary"]["compared"] >= 115,
               f"compared={res10['summary']['compared']}")


# ══════════════════════════════════════════════════════════════════════════════
#  1o. METLIFE — a code the scrape dropped, and a fourth copied perio date
# ══════════════════════════════════════════════════════════════════════════════
#
# MetLife answers every code the scrape asks for: Tudor and Aaren both came
# back 62 of 62. Kate Licina's came back 66 of 67, losing D0140 out of the
# middle of a chunk — the batch settled while React still had a row to paint.
# The content script now gives an incomplete batch longer and searches on its
# own for anything still missing, and records what never came back.
#
# The audit's part is only to say so honestly: a code the export does not carry
# is a code the portal never stated, and must not be filled in from the sibling
# evaluation codes that do have rows.

print("── 1o. METLIFE (Kate Licina) ──")

if not (os.path.exists(SABRINA_PDF_11) and os.path.exists(PORTAL_JSON_11)):
    skip("Kate Licina pairing", "Material/Smile Kate Licina files not present")
else:
    import json as _json11
    with open(SABRINA_PDF_11, "rb") as fh:
        parsed11 = sc.parse_sabrina_pdf(fh.read())
    with open(PORTAL_JSON_11, encoding="utf-8") as fh:
        portal11 = _json11.load(fh)

    check("[11] the sheet parses whole", parsed11["labels_not_found"], [])

    res11 = sc.compare_sabrina_to_portal(parsed11, portal11)
    rows11 = {r["key"]: r for s in res11["sections"] for r in s["rows"]}

    _codes = {str(p.get("procedure_code") or "").upper()
              for p in (portal11.get("benefit_coverage") or {}).get("procedures") or []}

    # Written to hold both before and after the scrape is repeated with the
    # fixed content script, so re-capturing Kate does not break the suite.
    if "D0140" not in _codes:
        # The export does not carry it, so all three of its columns must say
        # the portal did not state it — never borrowed from D0120 or D0150,
        # which carry rows of their own.
        for key in ("d0140", "d0140__freq", "d0140__hist"):
            check(f"[11] {key} is reported unstated, not filled in",
                  rows11[key]["status"], "not_in_portal")
        check("[11] and the sibling evaluation codes are unaffected",
              (rows11["d0120"]["status"], rows11["d0150"]["status"]),
              ("match", "match"))
    else:
        check("[11] the re-scraped D0140 compares", rows11["d0140"]["status"], "match")

    # A fourth patient whose sheet carries the prophylaxis date on the
    # periodontal-maintenance row, where MetLife records no history at all.
    # Tudor, Amanda Wilson and Aaren Boyd show the same thing.
    check("[11] the perio-maintenance history disagrees with the portal",
          (rows11["d1110"]["status"], rows11["d4910__hist"]["sabrina"],
           rows11["d4910__hist"]["portal"], rows11["d4910__hist"]["status"]),
          ("match", "05/05/2026", "—", "mismatch"))
    check("[11] and it is the prophylaxis date the portal records",
          parsed11["benefit_rows"]["d1110"]["history"], "05/05/2026")

    check("[11] nothing reported blank on the sheet",
          res11["summary"]["missing_in_sabrina"], 0)
    check_true("[11] fields compared", res11["summary"]["compared"] >= 120,
               f"compared={res11['summary']['compared']}")


# ══════════════════════════════════════════════════════════════════════════════
#  1p. DELTA DENTAL OFFICE TOOLKIT — routed to a folder of its own
# ══════════════════════════════════════════════════════════════════════════════
#
# dentalofficetoolkit.com is a different portal from Delta Dental's provider
# site, and content_DD_Toolkit.js exports it in a shape of its own. Until
# 2026-10-22 nothing called `portals/delta_toolkit.py`, so every Toolkit upload
# was refused with "no rules for this portal export". It is now audited by
# `carriers/delta_toolkit/`. Built from an inline export in the shape the
# extension's builders emit, so this section always runs.

print("── 1p. DELTA DENTAL OFFICE TOOLKIT ──")

from smile_partners import sabrina as _sp
from smile_partners.sabrina.carriers import CARRIERS as _CARRIERS, detect_carrier as _detect
from smile_partners.sabrina.carriers.delta_toolkit import portal as _tk_portal
from smile_partners.portals.delta_toolkit import _normalize_delta_toolkit_portal


def _tk_result(code, pct, limits=(), category="Diagnostic"):
    return {"procedureCode": code, "status": "OK", "percentCovered": pct,
            "procedurePath": [{"level": 1, "procedure": category},
                              {"level": 2, "procedure": category},
                              {"level": 3, "procedure": code}],
            "limitations": ([{"level": "procedure", "procedure": code,
                              "exclusionsAndLimitations": list(limits)}] if limits else [])}


def _tk_export(max_description="for Diagnostic, Preventive, Restorative, Endodontics"):
    member = {"patientName": "JANE DOE", "birthdate": "01/15/1985",
              "relationship": "Subscriber", "eligibility": "Eligible",
              "effectiveDate": "01/01/2024", "selected": True}
    return {
        "source": "Delta Dental Office Toolkit", "portal": "www.dentalofficetoolkit.com",
        "selected_network": "PPO Dentist",
        "member_details": {"members": [member], "selectedMember": member},
        "routine_procedures": {"rows": [{"procedureCode": "D0120", "serviceDates": ["03/10/2026"]},
                                        {"procedureCode": "D1110", "serviceDates": []}]},
        "coverages": {
            "coverage_rows": [{"procedure": "Preventive", "percentCovered": 100},
                              {"procedure": "Minor Restorative", "percentCovered": 80},
                              {"procedure": "Major Restorative", "percentCovered": 50},
                              {"procedure": "Orthodontics", "percentCovered": "Not Covered"}],
            "procedure_code_search": {
                "failed_codes": ["D9944"],
                "results": [
                    _tk_result("D0120", 100, ["Oral examinations are payable twice in a calendar year."]),
                    _tk_result("D1110", 100, ["Prophylaxes (cleanings) are payable twice in a calendar year."],
                               "Preventive"),
                    _tk_result("D2160", 80, [], "Minor Restorative"),
                    _tk_result("D2740", 50, ["Crowns are payable once per tooth in a five year period."],
                               "Major Restorative"),
                    _tk_result("D4910", 80, ["Periodontal maintenance is a benefit once a 30 day "
                                             "post-operative period has completed."], "Periodontics"),
                    _tk_result("D8080", "Not Covered", [], "Orthodontics"),
                    {"procedureCode": "D9944", "status": "FAILED", "error": "HTTP 500"},
                ]}},
        "maximums_and_deductibles": {"accumulationPeriodType": "Calendar Year", "rows": [
            {"type": "Maximum", "category": "General", "description": max_description,
             "individual": {"amount": 1500, "used": 250, "remaining": 1250},
             "from": "01/01/2026", "to": "12/31/2026"},
            {"type": "Deductible", "category": "General",
             "description": "Deductible does not apply to Diagnostic and Preventive",
             "individual": {"amount": 50, "used": 0, "remaining": 50},
             "family": {"amount": 150, "used": 0, "remaining": 150}}]},
        "more_information": {"client_benefit_information": {"display_fields": {
            "payorId": "DDPMI", "groupNumber": "12345", "subGroupNumber": "0001",
            "groupName": "ACME CORP"}}},
    }


_tk = _tk_export()
check("Toolkit export is routed to its own folder", _detect(_tk), "delta_toolkit")
check("and so is its translation, which names Delta Dental as its insurer",
      _detect(_normalize_delta_toolkit_portal(_tk)), "delta_toolkit")
check("a Delta Dental provider-site export still goes to delta_dental",
      _detect({"source": "Delta Dental", "primary_patient": {"name": "X"},
               "tabs": {"overview": {}}}), "delta_dental")
check("the Toolkit is named among the supported portals",
      _CARRIERS.get("delta_toolkit"), "Delta Dental Office Toolkit")

_tk_sheet = {"fields": {
    "patient_name": "Jane Doe", "patient_dob": "01/15/1985", "group_number": "12345-0001",
    "payor_id": "DDPMI", "yearly_max": "1500.00", "yearly_max_paid": "250.00",
    "indiv_ded": "50.00", "family_ded": "150.00", "ded_prev": "No",
    "d0120": "100%", "d2160": "80%", "d2740": "50%",
    "major_payment_timing": "Seat Date",
    "d0120__freq": "2X1Year", "d0120__hist": "03/10/2026", "d1110__hist": "NH",
    "d2740__freq": "1X5Years", "ortho_coverage": "0%", "d9944": "100%",
}, "benefit_rows": {}, "labels_not_found": []}
_tk_res = _sp.compare_sabrina_to_portal(_tk_sheet, _tk)
_tk_rows = {r["key"]: r for s in _tk_res["sections"] for r in s["rows"]}

check("the audit is run by delta_toolkit", _tk_res["carrier"], "delta_toolkit")
check("without the Delta page inside the PDF the identity gate holds back every comparison",
      (_tk_res["diagnostics"]["toolkit"]["identity_valid"],
       {r["status"] for s in _tk_res["sections"] for r in s["rows"]} - {"not_comparable"}),
      (False, set()))
check("the sheet's D0120 / D2160 / D2740 rows read their own codes",
      tuple(_tk_rows[k]["portal"] for k in ("d0120", "d2160", "d2740")),
      ("100", "80", "50"))
check("a code whose Toolkit lookup failed is never a mismatch",
      (_tk_rows["d9944"]["status"] != "mismatch", _tk_res["diagnostics"]["toolkit"]["failed_codes"]),
      (True, ["D9944"]))
check("preventive is in the max when the description lists it",
      _tk_rows["prev_in_max"]["portal"], "Yes")
_tk_except = _tk_export("Applies to all services except Preventive and Diagnostic")
check("and not when the description excepts it",
      _tk_portal._portal_prev_in_max({}, _tk_portal._portal_normalized(_tk_except)), "No")


# ══════════════════════════════════════════════════════════════════════════════
#  1q. STAR DENTAL — a Sabrina client with a folder of its own
# ══════════════════════════════════════════════════════════════════════════════
#
# Added 2026-10-22 as a copy of smile_partners/. Its audit must be run by its
# own package, never Smile Partners', so that a fix for one cannot reach the
# other. Reuses the inline Toolkit export from 1p, so this section always runs.

print("── 1q. STAR DENTAL ──")

from fastapi import HTTPException
import main as _main
from star_dental import sabrina as _ns


def _refused(name, capability):
    try:
        _main.resolve_client(name, capability)
    except HTTPException as e:
        return e.status_code
    return None


check("the client is registered for the Sabrina audit",
      _main.resolve_client("Star Dental", "sabrina_audit")[0], "star_dental")
check("and refused for jobs that need a Denticon export",
      tuple(_refused("star_dental", c) for c in ("match", "notes", "new_plan")),
      (400, 400, 400))
check("the server runs its own package",
      _main.client_module(_main.CLIENTS["star_dental"], "sabrina").__name__,
      "star_dental.sabrina")
check("it audits the same portals as Smile Partners",
      _ns.CARRIERS, _CARRIERS)
check("a carrier's rules come from its own folder, not Smile Partners'",
      (_ns.carrier_rules(_tk)[1].__name__, _sp.carrier_rules(_tk)[1].__name__),
      ("star_dental.sabrina.carriers.delta_toolkit",
       "smile_partners.sabrina.carriers.delta_toolkit"))

# Star Dental's field list (its tab of "Updated Sabrina Codes & C Q's Data -
# All Clients.xlsx"): which codes it audits, and which of them carry a
# Frequency, Age Limit or History cell. D4341's age cell is "SRP Quads per day?".
from star_dental.sabrina.carriers.metlife import spec as _ns_spec, parser as _ns_parser
from star_dental.sabrina.carriers.delta_dental import parser as _ns_dd_parser
from star_dental.sabrina.carriers.metlife.portal import _portal_dep_age_limit as _ns_dep_age
from smile_partners.sabrina.carriers.metlife import spec as _sp_spec

_NS_CODES = set(
    "D0120 D1110 D0220 D0230 D0240 D0150 D0140 D1120 D0210 D0330 D0274 D1351 "
    "D1206 D1208 D0367 D1516 D2331 D2140 D2391 D2610 D2642 D4381 D4355 D4346 "
    "D4341 D4910 D2740 D2750 D2950 D5110 D5212 D5511 D5650 D5810 D5821 D5912 "
    "D6010 D6104 D6190 D6056 D6057 D6058 D6240 D6245 D9110 D9222 D9230 D9239 "
    "D9243 D9310 D9612 D9630 D9944 D9946 D9947 D3221 D3310 D3330 D3346 D3348 "
    "D4260 D4921 D7140 D7210 D7230 D7240 D7310 D7953 D8080 D8090 D8220 D8680".split())
_NS_NO_FREQ = set("D3221 D3310 D3330 D3346 D3348 D4260 D4921 D7140 D7210 D7230 "
                  "D7240 D7310 D7953 D8080 D8090 D8220 D8680".split())


def _ns_columns(spec):
    by_key = {f["key"]: f for f in spec}
    out = {}
    for f in spec:
        if f["section"] == "Coverage by CDT Code":
            code = by_key[f.get("row_key", f["key"])]["portal"][1]
            out.setdefault(code, set()).add(f.get("aspect", "pct"))
    return out


_ns_cols = _ns_columns(_ns_spec._SPEC)
check("Star Dental audits exactly the codes on its list", set(_ns_cols), _NS_CODES)
check("each with the columns its list asks for",
      {c: a for c, a in _ns_cols.items()},
      {c: ({"pct"} | (set() if c in _NS_NO_FREQ else {"freq"})
           | ({"age"} if c in {"D1206", "D1208", "D1351", "D4341"} else set())
           | ({"hist"} if c in _ns_spec._HISTORY_CODES else set()))
       for c in _NS_CODES})
check("fields Smile Partners has and Star Dental's list doesn't are gone",
      {k for k in ("pct_prev", "pct_basic", "pct_major", "prev_in_max",
                   "perio_maint_after_srp", "d2160", "d5995") if any(f["key"] == k for f in _ns_spec._SPEC)},
      set())
check("while Smile Partners keeps them",
      all(any(f["key"] == k for f in _sp_spec._SPEC) for k in ("pct_prev", "prev_in_max", "d2160")), True)

_ns_text = "\n".join([
    "Fee Schedule", "GA Delta PPO RC42", "Eligibility Term Date", "Starting Month of Plan Year", "January",
    "D0120 Preventative", "100%", "Dependent Age Limit", "26", "Pre-Authorize over", "300",
    "Benefit Details", "D0120 Periodic Exam", "2X1Year", "100%", "04/09/2026",
    "D0120 and D0140 share freq?", "Yes", "D0230", "1X1Year", "100%",
    "D2140 Amalgam One Surface", "1X24Months", "80%",
    "D4341 Scaling Root Planing", "1X24Months", "80%", "4", "NH",
    "D9944 Occlusal Guard", "1X5Years", "50%", "D9944 Bruxism only?", "Yes",
    "D1510 Space Maintainer", "1X5Years", "100%",
])
_ns_f = _ns_parser.parse_sabrina_text(_ns_text)["fields"]
check("new rows read: a bare code, a code with a description, and the questions",
      tuple(_ns_f[k] for k in ("d0230", "d0230__freq", "d2140", "d0120_d0140_share_freq",
                               "d9944_bruxism_only", "dep_age_limit", "pre_auth", "term_date")),
      ("100%", "1X1Year", "80%", "Yes", "Yes", "26", "300", None))
check("a code is not confused with a question or headline that starts with it",
      tuple(_ns_f[k] for k in ("d0120", "d0120__hist", "d9944", "d4341__age")),
      ("100%", "04/09/2026", "50%", "4"))
check("D1516 reads the template's D1510 Space Maintainer row",
      (_ns_f["d1516"], _ns_f["d1516__freq"]), ("100%", "1X5Years"))
check("Delta Dental still picks its network from the fee schedule",
      _ns_dd_parser.parse_sabrina_text(_ns_text)["fee_schedule"], "GA Delta PPO RC42")
check("a dependent age limit of NAL is unstated, not 'no limit'",
      (_ns_dep_age({"dep_age_limit": "NAL"}, {}), _ns_dep_age({"dep_age_limit": "26"}, {})),
      (None, "26"))


# ══════════════════════════════════════════════════════════════════════════════
#  1r. JEFFERSON — a Sabrina client built from its own field list
# ══════════════════════════════════════════════════════════════════════════════
#
# Added 2026-10-26 as a copy of star_dental/, with the field list replaced by
# the "Jefferson " tab of the codes workbook. Inline data only, so this section
# always runs.

print("── 1r. JEFFERSON ──")

from jefferson import sabrina as _jf
from jefferson.sabrina.carriers.metlife import spec as _jf_spec, parser as _jf_parser
from jefferson.sabrina.carriers.delta_dental import parser as _jf_dd_parser

check("Jefferson is registered for the Sabrina audit",
      _main.resolve_client("Jefferson", "sabrina_audit")[0], "jefferson")
check("and refused for jobs that need a Denticon export",
      tuple(_refused("jefferson", c) for c in ("match", "notes", "new_plan")),
      (400, 400, 400))
check("a carrier's rules come from Jefferson's own folder",
      _jf.carrier_rules(_tk)[1].__name__, "jefferson.sabrina.carriers.delta_toolkit")

_JF_CODES = set(
    "D0120 D1110 D0220 D0230 D0150 D0140 D1120 D0210 D0330 D0274 D1351 D1206 "
    "D1208 D1516 D2331 D2140 D2391 D2610 D2642 D4381 D4355 D4346 D4341 D4910 "
    "D2740 D2750 D2950 D5110 D5212 D5511 D6010 D6104 D6190 D6056 D6057 D6058 "
    "D6240 D6245 D9110 D9222 D9230 D9239 D9243 D9944 D9946 D3221 D3310 D3330 "
    "D3346 D3348 D4921 D7140 D7210 D7230 D7240 D7953 D8080 D8090 D2520 D2194 "
    "D5940 D9311 D8040 D4266 D2920 D9932".split())
_JF_NO_FREQ = set("D3221 D3310 D3330 D3346 D3348 D4921 D7140 D7210 D7230 D7240 "
                  "D7953 D8080 D8090".split())
_JF_HIST = set("D0120 D0140 D0150 D0210 D0220 D0230 D0274 D0330 D1110 D1120 D1206 "
               "D1208 D1351 D2194 D2391 D2520 D2740 D2750 D4266 D4341 D4346 D4381 "
               "D4910 D5110 D5212 D5940 D8040 D9311 D9932".split())

_jf_cols = _ns_columns(_jf_spec._SPEC)
check("Jefferson audits exactly the codes on its list", set(_jf_cols), _JF_CODES)
check("each with the columns its list asks for",
      _jf_cols,
      {c: ({"pct"} | (set() if c in _JF_NO_FREQ else {"freq"})
           | ({"age"} if c in {"D1206", "D1208", "D1351", "D9932", "D4341"} else set())
           | ({"hist"} if c in _JF_HIST else set()))
       for c in _JF_CODES})
check("Star Dental's own rows are not in Jefferson's audit",
      {k for k in ("d0240", "d0367", "d4260", "d9310", "d9612", "d0150_freq_per_provider")
       if any(f["key"] == k for f in _jf_spec._SPEC)},
      set())
check("and Star Dental keeps them",
      all(any(f["key"] == k for f in _ns_spec._SPEC) for k in ("d0240", "d9310", "d0150_freq_per_provider")),
      True)

_jf_text = "\n".join([
    "Fee Schedule", "GA Delta PPO RC42", "Benefit Details",
    "D0220 PAs", "Pre-D", "100%", "01/02/2026",
    "D2520 Inlay Metallic", "1X5Years", "50%", "NH",
    "D9932", "1X1Year", "50%", "18", "NH",
    "D9310", "Yes",
    "D9311", "2X1Year", "80%", "NH",
])
_jf_f = _jf_parser.parse_sabrina_text(_jf_text)["fields"]
check("Jefferson's own rows read: new History cells, a new age cell, D9310's question",
      tuple(_jf_f[k] for k in ("d0220__hist", "d2520", "d2520__freq", "d2520__hist",
                               "d9932__age", "d9310_question", "d9311", "d9311__freq")),
      ("01/02/2026", "50%", "1X5Years", "NH", "18", "Yes", "80%", "2X1Year"))
check("Delta Dental picks its network from the fee schedule",
      _jf_dd_parser.parse_sabrina_text(_jf_text)["fee_schedule"], "GA Delta PPO RC42")


# ══════════════════════════════════════════════════════════════════════════════
#  1s. PARK DENTAL — Star Dental's rules, Park's own field list
# ══════════════════════════════════════════════════════════════════════════════
#
# Added 2026-10-28 as a copy of star_dental/, with the field list replaced by
# the "Park Dental" tab of the codes workbook. That tab ticks 21 codes for
# Frequency but not Coverage %, so those codes compare no percentage. Inline
# data only, so this section always runs.

print("── 1s. PARK DENTAL ──")

import importlib as _importlib
from park_dental import sabrina as _pk

check("Park Dental is registered for the Sabrina audit",
      _main.resolve_client("Park Dental", "sabrina_audit")[0], "park_dental")
check("and refused for jobs that need a Denticon export",
      tuple(_refused("park_dental", c) for c in ("match", "notes", "new_plan")),
      (400, 400, 400))
check("a carrier's rules come from Park Dental's own folder",
      _pk.carrier_rules(_tk)[1].__name__, "park_dental.sabrina.carriers.delta_toolkit")

_PK_CODES = set(
    "D0120 D0140 D0150 D0220 D0210 D0330 D0274 D0364 D1110 D1208 D1351 D1510 "
    "D2331 D2391 D2740 D5110 D2950 D3310 D3330 D4260 D4266 D4341 D4346 D4355 "
    "D4381 D4910 D5510 D5911 D6010 D6058 D6190 D7140 D7220 D7230 D7240 D7280 "
    "D7283 D7310 D7950 D7952 D7953 D7961 D7971 D9110 D9222 D9944 D8080".split())
_PK_NO_PCT = set("D0210 D4346 D4381 D4910 D5110 D5510 D6010 D6190 D7140 D7220 D7230 "
                 "D7240 D7280 D7283 D7310 D7950 D7952 D7953 D7961 D7971 D9222".split())
_PK_NO_FREQ = {"D3310", "D3330", "D4260", "D4266", "D5911", "D8080"}
_PK_HIST = {"D0120", "D0140", "D0150", "D0210", "D0274", "D0330", "D1208", "D4341"}
_PK_EXPECTED = {c: (({"pct"} if c not in _PK_NO_PCT else set())
                    | (set() if c in _PK_NO_FREQ else {"freq"})
                    | ({"age"} if c in {"D1208", "D1351", "D8080"} else set())
                    | ({"hist"} if c in _PK_HIST else set()))
                for c in _PK_CODES}


def _pk_columns(spec):
    """The columns each code is compared on, leaving out a no-percentage %."""
    by_key = {f["key"]: f for f in spec}
    out = {}
    for f in spec:
        if f["section"] != "Coverage by CDT Code":
            continue
        base = by_key[f.get("row_key", f["key"])]
        cols = out.setdefault(base["portal"][1], set())
        if not (f.get("aspect", "pct") == "pct" and base.get("no_percentage")):
            cols.add(f.get("aspect", "pct"))
    return out


for _carrier in ("aetna", "cigna", "delta_dental", "delta_toolkit", "metlife"):
    check(f"{_carrier}: Park audits exactly its codes, each on the columns its list ticks",
          _pk_columns(_importlib.import_module(f"park_dental.sabrina.carriers.{_carrier}.spec")._SPEC),
          _PK_EXPECTED)
check("the upload preview's copy agrees",
      _pk_columns(_importlib.import_module("park_dental.sabrina.sheet.spec")._SPEC), _PK_EXPECTED)
check("Ortho - Age limit is the plan's orthodontic age on every carrier",
      {c: next(f["portal"] for f in _importlib.import_module(f"park_dental.sabrina.carriers.{c}.spec")._SPEC
               if f["key"] == "ortho_coverage__age")
       for c in ("aetna", "cigna", "delta_dental", "delta_toolkit", "metlife")},
      {c: "_ortho_age" for c in ("aetna", "cigna", "delta_dental", "delta_toolkit", "metlife")})

_pk_text = "\n".join([
    "Fee Schedule", "GA Delta PPO RC42", "Ortho Payment Timing", "Yearly", "Benefit Details",
    "Periodic Exam D0120", "2X1Year", "100%", "04/09/2026",
    "D0210 Full-Mouth Xray", "1X5Years", "03/03/2024",
    "D2391 Composite Fillings", "1X24Months", "80%",
    "D2391 Composite Fillings downgraded to Amalgam", "Yes",
    "D3310", "Endodontics", "80%",
    "D4355 Debridement", "1XLifetime", "80%", "D4355 Debridement Share Freq", "No",
    "D4910 Perio Maintenance", "4X1Year", "D4910 Shares frequency with Prophy?", "Yes",
    "D7140_Ora_Surgery", "1X1Day", "D7961_D7962", "1XLifetime",
    "Ortho Coverage", "50%", "19",
])
_PK_READ = ("d0120", "d0120__hist", "d0210__freq", "d0210__hist", "posterior_composite_downgrade",
            "d3310", "d4355", "d4355_share_freq", "d4910__freq", "prophy_perio_share_freq",
            "d7140__freq", "d7961_d7962__freq", "ortho_coverage", "ortho_coverage__age",
            "ortho_payment_timing")
for _carrier in ("metlife", "delta_dental", "delta_toolkit"):
    _pk_f = _importlib.import_module(f"park_dental.sabrina.carriers.{_carrier}.parser").parse_sabrina_text(_pk_text)["fields"]
    check(f"{_carrier}: Park's rows read — a reversed label, History with no %, a wrapped label, the questions",
          tuple(_pk_f.get(k) for k in _PK_READ),
          ("100%", "04/09/2026", "1X5Years", "03/03/2024", "Yes", "80%", "80%", "No", "4X1Year", "Yes",
           "1X1Day", "1XLifetime", "50%", "19", "Yearly"))

_pk_res = _pk.compare_sabrina_to_portal({"fields": {"d0210__freq": "1X5Years", "d4910__freq": "4X1Year"},
                                         "benefit_rows": {}, "labels_not_found": [], "text": ""}, _tk)
_pk_rows = {r["key"] for s in _pk_res["sections"] for r in s["rows"]}
check("a Frequency-only code shows its Frequency and never a percentage",
      ("d0210" in _pk_rows, "d0210__freq" in _pk_rows, "d4910" in _pk_rows, "d4910__freq" in _pk_rows),
      (False, True, False, True))


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