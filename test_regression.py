"""
Regression suite for the plan-comparison engine (compare_patients.py).

Run after EVERY change to the matching logic:
    python test_regression.py

Each verified real-world case gets added here so later fixes can't silently
break earlier ones. Real-data cases are skipped (not failed) when their JSON
files are missing from Material/Comparison.
"""
import asyncio
import json
import logging
import os
import sys

logging.disable(logging.CRITICAL)

from compare_patients import (
    compare_plans,
    extract_denticon_plan_fields,
    extract_portal_fields,
    match_insurance_plan,
)

HERE = os.path.dirname(os.path.abspath(__file__))
COMPARISON_DIR = os.path.join(HERE, "Material", "Comparison")

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
_results: list[tuple[str, str, str]] = []


def report(name: str, status: str, detail: str = ""):
    _results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


# ──────────────────────────────────────────────────────────────────
# SYNTHETIC CASE 1: six-field validation decisions (compare_plans)
# ──────────────────────────────────────────────────────────────────
SYNTH_PORTAL = {
    "group_number": "925015000", "group_name": "ROUND ROCK INDEPENDENT SCHOOL DISTRICT",
    "individual_deductible": 50.0, "family_deductible": 150.0,
    "individual_annual_max": 2000.0, "ortho_lifetime_max": 3500.0,
    "preventative_D0120_pct": 100.0, "basic_D2331_D2140_pct": 80.0,
    "major_D2740_pct": 50.0,
    "fluoride_D1206_pct": 100.0, "fluoride_D1206_age": 14.0,
    "sealants_D1351_pct": 100.0, "sealants_D1351_age": 14.0,
    "space_maint_1510_pct": 100.0, "space_maint_1510_age": 16.0,
    "ortho_D8080_pct": 50.0, "ortho_D8080_age": 19.0,
}


async def case_six_field_decisions():
    # Same plan, abbreviated group name → must MATCH
    r = await compare_plans("A", SYNTH_PORTAL, dict(SYNTH_PORTAL, group_name="ROUND ROCK ISD"))
    ok = r["match_found"] and r["six_field_mismatch_count"] == 0
    report("six-field: same plan w/ abbreviated group name matches", PASS if ok else FAIL, r["reason"])

    # Different group number → deterministic REJECT (no AI)
    r = await compare_plans("B", SYNTH_PORTAL, dict(SYNTH_PORTAL, group_number="111222333"))
    ok = not r["match_found"] and "group_number" in r["six_field_mismatches"]
    report("six-field: wrong group number rejected", PASS if ok else FAIL, r["reason"])

    # Different annual max → deterministic REJECT
    r = await compare_plans("C", SYNTH_PORTAL, dict(SYNTH_PORTAL, individual_annual_max=1500.0))
    ok = not r["match_found"] and "individual_annual_max" in r["six_field_mismatches"]
    report("six-field: wrong annual max rejected", PASS if ok else FAIL, r["reason"])

    # Value within ±2% tolerance → must MATCH
    r = await compare_plans("E", SYNTH_PORTAL, dict(SYNTH_PORTAL, individual_annual_max=2001.0))
    ok = r["match_found"] and r["six_field_mismatch_count"] == 0
    report("six-field: 2001 vs 2000 rounding tolerated", PASS if ok else FAIL, r["reason"])

    # Portal reports base group only, Denticon stores GROUP-SUBGROUP → must MATCH
    # (Shelton/Delta case: portal '3250' vs denticon '3250-1001')
    r = await compare_plans("F", dict(SYNTH_PORTAL, group_number="3250"),
                            dict(SYNTH_PORTAL, group_number="3250-1001"))
    ok = r["match_found"] and r["six_field_mismatch_count"] == 0
    report("six-field: base group matches GROUP-SUBGROUP record", PASS if ok else FAIL, r["reason"])

    # But two DIFFERENT sub-groups of the same employer → deterministic REJECT
    r = await compare_plans("G", dict(SYNTH_PORTAL, group_number="3250-2002"),
                            dict(SYNTH_PORTAL, group_number="3250-1001"))
    ok = not r["match_found"] and "group_number" in r["six_field_mismatches"]
    report("six-field: different sub-groups rejected", PASS if ok else FAIL, r["reason"])


# ──────────────────────────────────────────────────────────────────
# SYNTHETIC CASE 2: FORMAT A end-to-end with duplicate records
# ──────────────────────────────────────────────────────────────────
def _metlife_portal():
    return {"metlife_data": {
        "financials": {"annual_max": {"total": "$ 2000.00 total"},
                       "deductible_ind": {"total": "$ 50.00 total"},
                       "ortho_lifetime": {"total": "$ 3500.00 total"}},
        "plan_details": {"employer_group": "CITY OF RACINE", "group_number": "305111"},
        "patient": {"relationship": "Self"}},
        "benefit_coverage": {"procedures": [
            {"procedure_code": "D0120", "benefit_level": "100%"},
            {"procedure_code": "D2140", "benefit_level": "80%"},
            {"procedure_code": "D2740", "benefit_level": "50%"},
            {"procedure_code": "D1206", "benefit_level": "100%", "age_limit": "0-14"},
            {"procedure_code": "D1351", "benefit_level": "100%", "age_limit": "0-14"},
            {"procedure_code": "D1510", "benefit_level": "100%", "age_limit": "0-16"},
            {"procedure_code": "D8080", "benefit_level": "50%", "age_limit": "0-19"}]}}


def _metlife_plan(pid, grp, mx, created="01/01/2024"):
    notes = (f"EMPLOYER: CITY OF RACINE GROUP # : {grp} "
             f"DEDUCTIBLE $ : 50 MAXIMUM $ : {mx} LIFETIME MAX : 3500")
    ft = f"{pid} {grp} 1274 METLIFE PID 111 CITY OF RACINE {created} USERX"
    return {"ins_plan_id": pid, "plan_details": {},
            "benefits": {"notes": notes, "full_text": ft},
            "coverage": [
                {"category": "D0120", "coverage_pct": "100"},
                {"category": "Restorative Fillings", "coverage_pct": "80"},
                {"category": "Restorative Crowns", "coverage_pct": "50"},
                {"category": "Preventive Fluoride", "coverage_pct": "100"},
                {"category": "Preventive Sealant", "coverage_pct": "100"},
                {"category": "D1510", "coverage_pct": "100"},
                {"category": "D1510 YES 100 Once per Lifetime 16 0", "coverage_pct": "100"},
                {"category": "Orthodontics Child", "coverage_pct": "50"},
                {"category": "Deductible", "ded_waived": "$50.00", "limitation": "$150.00"},
            ]}


async def case_metlife_duplicates():
    wrapper = {"denticon_data": {
        "primary_insurance": {"carrier_name": "METLIFE"},
        "plans": [
            _metlife_plan("1001", "305111", "2000", "01/01/2023"),  # correct, older dup
            _metlife_plan("1002", "305111", "2000", "06/15/2025"),  # correct, newest dup
            _metlife_plan("1003", "999999", "2000"),                # wrong group number
            _metlife_plan("1004", "305111", "1500"),                # wrong annual max
        ]}}
    r = await match_insurance_plan(_metlife_portal(), wrapper)
    ok = r.get("matching_id") == "1002" and r.get("match_found") is True and not r.get("tie")
    report("FORMAT A: newest duplicate wins, wrong plans rejected",
           PASS if ok else FAIL,
           f"picked={r.get('matching_id')} match={r.get('match_found')} tie={r.get('tie', False)}")


# ──────────────────────────────────────────────────────────────────
# SYNTHETIC CASE 3: extraction rules that were fixed
# ──────────────────────────────────────────────────────────────────
def case_extraction_rules():
    # 3a. No fabricated family deductible (was: 3x individual)
    portal = extract_portal_fields({"metlife_data": {
        "financials": {"deductible_ind": {"total": "$ 50.00 total"}},
        "plan_details": {}, "patient": {"relationship": "Self"}}})
    ok = portal.get("family_deductible") is None
    report("extraction: family deductible NOT fabricated from individual",
           PASS if ok else FAIL, f"family_deductible={portal.get('family_deductible')}")

    # 3b. FORMAT B must not inherit preventive pct into fluoride/sealants/space
    portal = extract_portal_fields({
        "summary": {"group_number": "123", "group_name": "TEST GROUP"},
        "financials": {}, "patient": {},
        "coinsurance": [{"category": "Diagnostic and Preventive", "patient_pays": "0%"}],
        "frequencies": [], "age_limits": []})
    ok = (portal.get("preventative_D0120_pct") == 100.0
          and portal.get("fluoride_D1206_pct") is None
          and portal.get("sealants_D1351_pct") is None
          and portal.get("space_maint_1510_pct") is None)
    report("extraction: FORMAT B does not fabricate fluoride/sealant/space pct",
           PASS if ok else FAIL,
           f"prev={portal.get('preventative_D0120_pct')} fl={portal.get('fluoride_D1206_pct')}")

    # 3c. Group number/name fallback from full_text plan-search row
    plan = {"ins_plan_id": "24299",
            "plan_details": {},
            "benefits": {
                "notes": "Plan Notes Verified by: X Last Update: 01/28/2026 In / Out of Network: In-Network",
                "full_text": "24299 3339901 1360 (IN) Cigna PPO CT TEACHERS' RETIREMENT BOARD "
                             "01/07/2025 ISPACEGA22693 06/26/2026 ISPACE712693"},
            "coverage": []}
    d = extract_denticon_plan_fields(plan)
    ok = d.get("group_number") == "3339901" and "TEACHERS" in str(d.get("group_name", ""))
    report("extraction: group number/name fall back to full_text plan row",
           PASS if ok else FAIL,
           f"group_number={d.get('group_number')} group_name={d.get('group_name')}")

    # 3d. Junk N/A code row must not shadow the real category row
    plan = {"ins_plan_id": "1", "plan_details": {},
            "benefits": {"notes": "", "full_text": ""},
            "coverage": [
                {"category": "D0120 - Periodic Exam", "ded_waived": "N/A",
                 "coverage_pct": "N/A", "limitation": "N/A"},
                {"category": "Diagnostic (d0120)", "ded_waived": "Yes",
                 "coverage_pct": "100", "limitation": "Twice per Benefit Year"}]}
    d = extract_denticon_plan_fields(plan)
    ok = d.get("preventative_D0120_pct") == 100.0
    report("extraction: N/A junk row falls through to category row",
           PASS if ok else FAIL, f"preventative={d.get('preventative_D0120_pct')}")


# ──────────────────────────────────────────────────────────────────
# REAL-DATA CASES — add one entry per verified audit result.
# (portal_file, denticon_file, expected_plan_id, expect_match)
# ──────────────────────────────────────────────────────────────────
REAL_CASES = [
    ("Gilligan-Megrue, Kathleen (Cigna)",
     "cigna_Kathleen_Gilligan-megrue_2026-07-15 (2).json",
     "Denticon_DeepAudit_Gilligan-Megrue, Kathleen_1784105277586.json",
     "24299", True),
    ("Carranza, Daniel (Guardian PDF, collapsed accordions)",
     "carranza.pdf",
     "Denticon_DeepAudit_Carranza, Miguel_1784115052290.json",
     "29531", True),
    # Guardian, 6 duplicate records: correct one is NOT the newest-created —
    # ZELIS-fee-schedule records must be demoted and the newest-MODIFIED
    # Guardian-PPO record (re-verified 2026) wins.
    ("Golab, Daniel (Guardian PDF, ZELIS decoys + modified-date tie-break)",
     "golab.pdf",
     "Denticon_DeepAudit_Golab, Daniel_1784115000287.json",
     "18139", True),
    # Guardian, 2 duplicates: 84275 is newer-created but empty/never touched;
    # 83207 is the actively maintained record (modified 05/18/2026) and wins
    # via the modified-before-created recency order.
    ("Andreu, Cesar (Guardian PDF, maintained record beats empty newer one)",
     "andreau.pdf",
     "Denticon_DeepAudit_Andreu, Cesar_1784115143350.json",
     "83207", True),
    # Delta Dental MO PDF: 3 sibling EMERSON records share group 21330100, each
    # with an "ID#: NNNNN\n<employer>" Employer detail. The portal group number
    # carries an "MO" prefix (MO21330100) that must still match the digits, and
    # 56926 — the only sibling with no conflicting benefit fields — must win
    # confidently over 53062/72932, which differ on ortho %/deductible/max.
    ("Farris, Drew (Delta MO PDF, ID#-prefixed siblings + MO-prefixed group)",
     "Member Benefits_999500000001616_DREW FARRIS_Full-1.pdf",
     "Denticon_DeepAudit_FARRIS, DREW Drew_1784616645849.json",
     "56926", True),
    # MetLife: correct plan (32209) has a sparse Denticon record. Its Employer
    # detail is "ID#: 27420\nLEANDER INDEPENDENT SCHOOL DIS" — the group name
    # must be read as the employer, not the "ID#:" line. With group name matched
    # and no conflicting fields, it must win (confident) over the same-employer
    # plan 29611, which is correctly rejected on an annual-max mismatch.
    ("Johnson, Alexander (MetLife, ID#-prefixed employer + sparse record)",
     "alexander_johnson_metlife_audit (1).json",
     "Denticon_DeepAudit_Johnson, Alexander_1784659164331.json",
     "32209", True),
    # Delta Dental WI PDF: orthodontics % must be read from the coverage line
    # ("Orthodontics(8010) 50%") instead of the old hardcoded 0%, otherwise the
    # portal falsely reports ortho_D8080_pct=0 and mismatches the Denticon 50%.
    ("Wakefield, Kyle (Delta WI PDF, orthodontics % extraction)",
     "Kyle.pdf",
     "Denticon_DeepAudit_Wakefield, Kyle Kyle_1784616647482.json",
     "30829", True),
    # Delta Dental MI, 2 duplicate records sharing group '3250-1001' while the
    # PDF reports base group '3250': sub-group-aware group matching must pass
    # six-field, then the newest-MODIFIED record (21272, re-verified 03/2026)
    # beats the stale 2022 record (8750).
    ("Shelton, Kenneth (Delta PDF, group/sub-group + modified-date tie-break)",
     "Patient Name_ KENNETH SHELTON Group_Sub Group_ 3250-1001 Relationship_ Subscriber.pdf",
     "Denticon_DeepAudit_Shelton, Kenneth Ken_1784193820818.json",
     "21272", True),
    # UCCI cases verified 2026-07-15 (files were removed from Material/Comparison;
    # restore them to re-enable):
    ("Sellars, Emma (UCCI)",
     "ucci/emma_sellars_ucci.json",
     "ucci/Denticon_DeepAudit_Sellars, Emma Emma_1784015110273.json",
     "22272", True),
    ("Jorns, Gavriel (UCCI)",
     "ucci/gavriel_r_jorns_ucci.json",
     "ucci/Denticon_DeepAudit_Jorns, Gavriel_1784015309916.json",
     "22272", True),
    # Delta Dental RI (FORMAT D). Single-plan sanity case.
    ("Chou Vang (Delta RI, single plan)",
     "DD RI/chou_vang_ddri_audit.json",
     "DD RI/Denticon Chou Vang DD RI.json",
     "8449", True),
    # Greg & Lily share the SAME two duplicate records (9893 $2,000 max /
    # 8282 $1,500 max) under group 7800-0750. The portal's $2,000 annual max
    # rejects 8282, so 9893 wins uniquely — this only works once FORMAT D
    # financials are parsed from the nested-list structure.
    ("Greg Parascandolo (Delta RI, annual-max disambiguates duplicates)",
     "DD RI/greg_parascandolo_ddri_audit.json",
     "DD RI/Denticon Greg DD RI.json",
     "9893", True),
    ("Lily Beaudry (Delta RI, annual-max disambiguates duplicates)",
     "DD RI/lily_beaudry_ddri_audit.json",
     "DD RI/Denticon Lily DD RI.json",
     "9893", True),
    # James Caldwell: 69454 & 74239 tie on every field EXCEPT the family
    # deductible ($100 vs $150), which lives only in the structured benefits
    # dict. Reading it there rejects 74239 (portal fam ded = $100) so 69454
    # wins uniquely.
    ("James Caldwell (Delta RI, family-deductible disambiguates duplicates)",
     "DD RI/james_caldwell_ddri_audit.json",
     "DD RI/Denticon James Caldwell DD RI.json",
     "69454", True),
]


async def case_real_data():
    for name, pfile, dfile, expected_id, expect_match in REAL_CASES:
        ppath = os.path.join(COMPARISON_DIR, pfile)
        dpath = os.path.join(COMPARISON_DIR, dfile)
        if not (os.path.exists(ppath) and os.path.exists(dpath)):
            report(f"real: {name}", SKIP, "files not present")
            continue
        if ppath.lower().endswith(".pdf"):
            from pdf_extractor import parse_insurance_pdf
            with open(ppath, "rb") as f:
                portal = await parse_insurance_pdf(f.read())
        else:
            with open(ppath, encoding="utf-8") as f:
                portal = json.load(f)
        with open(dpath, encoding="utf-8") as f:
            denticon = json.load(f)
        r = await match_insurance_plan(portal, denticon)
        ok = (str(r.get("matching_id")) == expected_id
              and bool(r.get("match_found")) == expect_match)
        report(f"real: {name} expects plan {expected_id}",
               PASS if ok else FAIL,
               f"picked={r.get('matching_id')} match={r.get('match_found')} "
               f"conf={r.get('confidence_score')} tie={r.get('tie', False)}")


def case_no_fabricated_portal_values():
    """File-independent guard against the fabrication bug class: a PDF parser
    must NEVER invent a coverage % or dollar amount for data that isn't in the
    text. Feed each Delta parser a minimal export that lacks the major/ortho
    and financials sections; those fields must come out missing, never a made-up
    default (which silently creates false mismatches during comparison)."""
    from pdf_extractor import _parse_delta_dental_wi, _parse_delta_dental_toolkit

    # WI: coverage line present for Preventive/Basic, "None" for Major, and NO
    # Orthodontics line at all. Major must be 0% (explicit None), ortho missing.
    wi_text = (
        "Group Name: TEST EMPLOYER\nGroup Number: 12345\n"
        "Preventive(0120) 100% Basic Restor(2140) 80% Major Restor(2750) None\n"
    )
    wi = _parse_delta_dental_wi(wi_text)
    wp = extract_portal_fields(wi)
    ok_wi = (wp["major_D2740_pct"] == 0.0          # explicit "None" -> 0
             and wp["ortho_D8080_pct"] is None       # absent -> missing, not 50
             and wp["basic_D2331_D2140_pct"] == 80.0)
    report("no-fabrication: WI absent ortho stays missing (not 50%)",
           PASS if ok_wi else FAIL,
           f"major={wp['major_D2740_pct']} ortho={wp['ortho_D8080_pct']} basic={wp['basic_D2331_D2140_pct']}")

    # Toolkit: only a few coverage rows, NO maximums/deductibles blocks and NO
    # major/ortho categories. Those must be missing, not fabricated.
    tk_text = (
        "Patient Name: TEST PATIENT\nRelationship: Subscriber\n"
        "Group/Sub Group: 7200-0001\n"
        "Procedure Category\n%Covered\nDiagnostic\n100\nPreventive\n100\nSealants\n80\n"
    )
    tk = _parse_delta_dental_toolkit(tk_text)
    tp = extract_portal_fields(tk)
    ok_tk = (tp["group_number"] == "7200-0001"       # combined footer parsed
             and tp["major_D2740_pct"] is None          # absent -> missing, not 50
             and tp["ortho_D8080_pct"] is None           # absent -> missing, not 50
             and tp["individual_annual_max"] is None     # absent -> missing, not $0
             and tp["sealants_D1351_pct"] == 80.0)
    report("no-fabrication: toolkit absent major/ortho/max stay missing",
           PASS if ok_tk else FAIL,
           f"grp={tp['group_number']} major={tp['major_D2740_pct']} ortho={tp['ortho_D8080_pct']} "
           f"annmax={tp['individual_annual_max']} sealants={tp['sealants_D1351_pct']}")


async def case_wi_none_not_fabricated():
    """Delta WI PDF: 'Major Restor(2750) None' must extract as 0% (not covered),
    NOT the fabricated 50% default. On Stohr/Brynn this false 50% used to bury
    the correct plan family (291434 among identical siblings) below unrelated
    plans; with the fix 291434 lands in the top-scoring, match_found group.
    NOTE: the 5 siblings 283982/289637/290120/291434/295756 are byte-identical
    in coverage, so the exact winner is a genuine tie — we assert 291434 is IN
    the confident top group, not that it is THE pick."""
    from pdf_extractor import parse_insurance_pdf
    ppath = os.path.join(COMPARISON_DIR, "Julie.pdf")
    dpath = os.path.join(COMPARISON_DIR, "Denticon_DeepAudit_Stohr, Brynn_1784621804769.json")
    if not (os.path.exists(ppath) and os.path.exists(dpath)):
        report("wi: 'None' major not fabricated as 50% (Stohr)", SKIP, "files not present")
        return
    with open(ppath, "rb") as f:
        portal = await parse_insurance_pdf(f.read())
    major = extract_portal_fields(portal).get("major_D2740_pct")
    with open(dpath, encoding="utf-8") as f:
        denticon = json.load(f)
    r = await match_insurance_plan(portal, denticon)
    top = max((p["confidence_score"] for p in r.get("all_plans_ranked", [])), default=0)
    target = next((p for p in r.get("all_plans_ranked", [])
                   if str(p["plan_id"]) == "291434"), None)
    ok = (major == 0.0 and target is not None
          and target["confidence_score"] == top and target["match_found"])
    report("wi: 'None' major=0 (not fabricated 50) + 291434 in top group",
           PASS if ok else FAIL,
           f"portal_major={major} 291434_conf={target and target['confidence_score']} top={top}")


def case_ddri_extraction():
    """Delta Dental RI (FORMAT D): financials live in nested lists and each
    procedure carries `coverage_percentage` (not `benefit_level`). Verify the
    extractor reads them, maps 'Not Covered' ortho to 0, and never fabricates."""
    ddri = {
        "ddri_data": True,
        "plan_details": {"group_number": "7800 - 0750",
                         "employer_group": "UNION UNAP COMPREHENSIVE"},
        "financials": {
            "maximums":     [{"category": "Maximum Lifetime Cap", "total": "Unlimited"}],
            "deductibles":  [{"category": "Individual Deductible", "total": "$0.00"},
                             {"category": "Family Deductible",     "total": "$0.00"}],
            "annual_limits":[{"category": "Annual Maximum",        "total": "$2,000.00"}],
            "orthodontic":  [{"category": "Elective Orthodontic Lifetime Maximum",
                              "total": "$1,500.00"}],
        },
        "benefit_coverage": {"procedures": [
            {"procedure_code": "D0120", "coverage_percentage": "100 %"},
            {"procedure_code": "D2391", "coverage_percentage": "100 %"},
            {"procedure_code": "D2740", "coverage_percentage": "100 %"},
        ]},
        "patient": {"relationship": "Child"},
    }
    p = extract_portal_fields(ddri)
    ok = (p["group_number"] == "7800 - 0750"
          and p["individual_deductible"] == 0.0
          and p["family_deductible"] == 0.0
          and p["individual_annual_max"] == 2000.0
          and p["ortho_lifetime_max"] == 1500.0
          and p["preventative_D0120_pct"] == 100.0
          and p["basic_D2331_D2140_pct"] == 100.0
          and p["major_D2740_pct"] == 100.0)
    report("ddri: FORMAT D financials + percentages extracted",
           PASS if ok else FAIL,
           f"annmax={p['individual_annual_max']} famded={p['family_deductible']} "
           f"ortho={p['ortho_lifetime_max']} basic={p['basic_D2331_D2140_pct']}")

    # 'Not Covered' ortho -> 0.0 (explicit no-coverage, not None/fabricated)
    ddri2 = json.loads(json.dumps(ddri))
    ddri2["financials"]["orthodontic"] = [
        {"category": "Elective Orthodontic Lifetime Maximum", "total": "Not Covered"}]
    p2 = extract_portal_fields(ddri2)
    report("ddri: ortho 'Not Covered' -> 0",
           PASS if p2["ortho_lifetime_max"] == 0.0 else FAIL,
           f"ortho={p2['ortho_lifetime_max']}")


def case_denticon_benefits_and_spacemaint():
    """Denticon side: DD RI plans keep plan-specific financials in a structured
    `benefits` dict (the family deductible lives ONLY there) and list coverage
    on one physical notes line. Two fixes covered:
      1. family_deductible falls back to benefits['family_deductible'].
      2. 'SPACE MAINT ... %:100%' is parsed non-greedily — a greedy '(\\d+)%'
         used to skip this field and capture a later 0%."""
    plan = {"ins_plan_id": "74239", "plan_details": {},
            "benefits": {
                "notes": ("Plan Notes Last Update: 05/18/2026 "
                          "SPACE MAINT D1510-D01525 %:100% FREQ: 1x :1XLifetime "
                          "AGE LIMIT : BASIC %:80% MAJOR %:0%"),
                "individual_deductible":     "$50.00",
                "family_deductible":         "$150.00",
                "individual_maximum":        "$2,000.00",
                "individual_ortho_maximum":  "$2,000.00"},
            "coverage": []}
    d = extract_denticon_plan_fields(plan)
    ok = (d["family_deductible"] == 150.0
          and d["individual_deductible"] == 50.0
          and d["individual_annual_max"] == 2000.0
          and d["ortho_lifetime_max"] == 2000.0
          and d["space_maint_1510_pct"] == 100.0)
    report("ddri: benefits-dict family ded + non-greedy space-maint %",
           PASS if ok else FAIL,
           f"famded={d['family_deductible']} indded={d['individual_deductible']} "
           f"annmax={d['individual_annual_max']} spacemaint={d['space_maint_1510_pct']}")


async def case_ddri_carina_tie():
    """Carina Snow (DD RI): 4 plans share group 4250-0403. 9756/8224 ($1,500
    annual max) are rejected against the portal's $2,000, leaving 9727 & 9757,
    which are byte-identical duplicates → a genuine tie, both in the confident
    top group (undecidable from the JSON alone)."""
    base = os.path.join(COMPARISON_DIR, "DD RI")
    ppath = os.path.join(base, "carina_snow_ddri_audit.json")
    dpath = os.path.join(base, "Denticon Carina Snow DD RI.json")
    if not (os.path.exists(ppath) and os.path.exists(dpath)):
        report("ddri: Carina duplicate-pair tie (9727/9757)", SKIP, "files not present")
        return
    with open(ppath, encoding="utf-8") as f:
        portal = json.load(f)
    with open(dpath, encoding="utf-8") as f:
        denticon = json.load(f)
    r = await match_insurance_plan(portal, denticon)
    ranked = {str(p["plan_id"]): p for p in r.get("all_plans_ranked", [])}
    ok = (bool(r.get("tie"))
          and ranked.get("9727", {}).get("match_found")
          and ranked.get("9757", {}).get("match_found")
          and not ranked.get("9756", {}).get("match_found")
          and not ranked.get("8224", {}).get("match_found"))
    report("ddri: Carina duplicate-pair tie (9727/9757)", PASS if ok else FAIL,
           f"tie={r.get('tie')} picked={r.get('matching_id')}")


async def main():
    await case_six_field_decisions()
    await case_metlife_duplicates()
    case_extraction_rules()
    case_no_fabricated_portal_values()
    case_ddri_extraction()
    case_denticon_benefits_and_spacemaint()
    await case_ddri_carina_tie()
    await case_real_data()
    await case_wi_none_not_fabricated()

    print()
    fails = [n for n, s, _ in _results if s == FAIL]
    skips = [n for n, s, _ in _results if s == SKIP]
    print(f"{len(_results)} checks: {len(_results) - len(fails) - len(skips)} passed, "
          f"{len(fails)} failed, {len(skips)} skipped")
    if fails:
        print("FAILED:")
        for n in fails:
            print(f"  - {n}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
