"""
SABRINA PDF ↔ INSURANCE PORTAL COMPARISON
═══════════════════════════════════════════════════════════════════════════════

Some BPO teams do not use Denticon — they work in Sabrina, and export a patient
insurance-breakdown PDF from it. For those teams there is nothing to "plan
match" (Sabrina gives ONE record, not a list of candidate plans), so the whole
ranked-plan flow in `compare_patients.py` does not apply.

What they need instead is a straight field-by-field audit:

    Sabrina PDF field   vs   the same field on the insurance portal
    → tell me which ones DON'T agree.

This module is that audit, and it is intentionally self-contained so the
Denticon path is untouched. It is only ever invoked when a **Sabrina PDF** is
uploaded in place of a Denticon JSON export (see `is_sabrina_pdf`).

Portal side
-----------
The portal value for every field is taken from `new_plan._extract()`, which is
already the project's richest portal→breakdown normalizer (it handles MetLife,
Cigna, Aetna and the PDF-parser output). We call it with an empty Denticon
payload and `_skip_llm`, because every field compared here is a hard portal
fact — no LLM interpretation is needed or wanted in an audit.

Comparison philosophy (consistent with `compare_patients.py`)
------------------------------------------------------------
A value the portal never stated is NOT a mismatch. It is reported as
`not_in_portal` and excluded from the mismatch count, because inventing a
portal value fabricates failures. Only fields where BOTH sides state something
can ever be a `mismatch`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys

from pdf_extractor import _extract_text

log = logging.getLogger(__name__)

# Set SABRINA_DEBUG=1 to log every label the parser could not locate in the PDF.
_DEBUG = os.environ.get("SABRINA_DEBUG", "").strip() not in ("", "0", "false", "False")

# Denticon's "unlimited maximum" convention, mirrored from compare_patients.py
# so an "Unlimited" yearly max on one side matches $99,999 on the other.
_UNLIMITED_MAX = 99999.0

# Values that mean "this field was left blank", on either side.
_BLANKS = {
    "", "-", "--", "---", "—", "–", "n/a", "na", "n.a.", "none", "null",
    "nil", "tbd", "?", "??", "not applicable", "not listed", "not stated",
    "not available", "unknown", "blank", "no data", "pending",
}


# ══════════════════════════════════════════════════════════════════════════════
#  FIELD SPEC — the audit sheet, in Sabrina's own order
# ══════════════════════════════════════════════════════════════════════════════
#
# Each entry:
#   key      internal id (unique — this is what the UI keys rows on)
#   label    the label as it is printed on the Sabrina PDF
#   kind     how to normalize/compare  → money | pct | yesno | date | month
#                                        name  | id  | text  | address
#   section  UI grouping
#   portal   where the portal value comes from:
#              str      → key in the new_plan._extract() breakdown dict
#              ('code', 'D0120', 'D0150', …)
#                       → coverage % for the first CDT code the portal states
#              None     → the portal export has no equivalent field; the row is
#                         shown for manual review but can never be a mismatch
#   after    disambiguates a label that appears more than once on the sheet
#            ("Date of Birth", "Paid to Date($)") — take the first occurrence
#            AFTER this anchor label
#   aliases  other spellings seen in the wild for the same label
#
_SPEC: list[dict] = [

    # ── Patient / Subscriber ─────────────────────────────────────────────────
    {"key": "patient_name",    "label": "Patient Name",    "kind": "name", "section": "Patient / Subscriber", "portal": "patient_name"},
    {"key": "patient_dob",     "label": "Date of Birth",   "kind": "date", "section": "Patient / Subscriber", "portal": "patient_dob",
     "after": "Patient Name"},
    {"key": "member_id",       "label": "Member ID#",      "kind": "id",   "section": "Patient / Subscriber", "portal": "member_id",
     "aliases": ["Member ID", "Member Id #", "Subscriber ID", "Member/Subscriber ID"]},
    {"key": "subscriber_name", "label": "Subscriber Name", "kind": "name", "section": "Patient / Subscriber", "portal": "subscriber_name"},
    {"key": "subscriber_dob",  "label": "Date of Birth",   "kind": "date", "section": "Patient / Subscriber", "portal": "subscriber_dob",
     "after": "Subscriber Name"},

    # ── Insurance ────────────────────────────────────────────────────────────
    # Compared on the CARRIER, not the whole string: the sheet names the plan
    # ("Metlife PDP+") while the portal names the payer and its claims address
    # ("(IN) MetLife(TX)- PO Box 981282- 79998"). Same insurer, so same value.
    {"key": "ins_name",     "label": "Insurance Name",    "kind": "carrier", "section": "Insurance", "portal": "ins_name",
     "aliases": ["Insurance Carrier", "Carrier Name"]},
    {"key": "group_name",   "label": "Group Name",        "kind": "text",    "section": "Insurance", "portal": "group_name",
     "aliases": ["Employer Group", "Employer Name"]},
    {"key": "group_number", "label": "Group Number",      "kind": "id",      "section": "Insurance", "portal": "group_number",
     "aliases": ["Group #", "Group No", "Group Num"]},
    {"key": "ins_address",  "label": "Insurance Address",  "kind": "address", "section": "Insurance", "portal": "ins_address",
     "aliases": ["Carrier Address", "Claims Address"]},
    {"key": "payor_id",     "label": "Payor ID",           "kind": "id",      "section": "Insurance", "portal": "payor_id",
     "aliases": ["Payer ID", "Payor Id", "Payer Id"]},

    # In-network status: the portal states it as a network/fee-schedule string
    # ("PPO", "Premier", "Non-Par", "In Network"), so it is normalized to YES/NO
    # by `_portal_in_network` rather than read straight off a field.
    {"key": "in_network",   "label": "In Network",   "kind": "yesno", "section": "Insurance", "portal": "_in_network",
     "aliases": ["In-Network", "In Network?", "Participating"]},
    {"key": "oon_benefits", "label": "OON Benefits", "kind": "yesno", "section": "Insurance", "portal": "_oon_benefits",
     "aliases": ["OON Benefit", "Out of Network Benefits", "Out-of-Network Benefits"]},

    {"key": "eff_date",        "label": "Patient Eff Date",            "kind": "date",  "section": "Insurance", "portal": "eff_date",
     "aliases": ["Patient Effective Date", "Eff Date", "Effective Date"]},
    {"key": "plan_year_start", "label": "Starting Month of Plan Year",  "kind": "month", "section": "Insurance", "portal": "plan_year_start",
     "aliases": ["Plan Year Start", "Benefit Year Start"]},

    # ── Maximums & deductibles ───────────────────────────────────────────────
    {"key": "yearly_max",       "label": "Yearly Max($)",           "kind": "money", "section": "Maximums & Deductibles", "portal": "yearly_max",
     "aliases": ["Yearly Maximum", "Annual Maximum", "Yearly Max"]},
    {"key": "yearly_max_paid",  "label": "Paid to Date($)",          "kind": "money", "section": "Maximums & Deductibles", "portal": "_yearly_max_paid",
     "after": "Yearly Max($)", "aliases": ["Paid to Date", "Used to Date", "Amount Used"]},
    {"key": "indiv_ded",        "label": "Individual Deductible($)", "kind": "money", "section": "Maximums & Deductibles", "portal": "indiv_ded",
     "aliases": ["Individual Deductible"]},
    {"key": "indiv_ded_paid",   "label": "Paid to Date($)",          "kind": "money", "section": "Maximums & Deductibles", "portal": "indiv_ded_paid",
     "after": "Individual Deductible($)", "aliases": ["Paid to Date", "Deductible Met"]},
    {"key": "family_ded",       "label": "Family Deductible($)",     "kind": "money", "section": "Maximums & Deductibles", "portal": "family_ded",
     "aliases": ["Family Deductible"]},
    {"key": "family_ded_paid",  "label": "Paid to Date($)",          "kind": "money", "section": "Maximums & Deductibles", "portal": "family_ded_paid",
     "after": "Family Deductible($)", "aliases": ["Paid to Date", "Deductible Met"]},

    {"key": "ded_prev", "label": "Deductible Applies to Preventative", "kind": "yesno", "section": "Maximums & Deductibles", "portal": "ded_prev",
     "aliases": ["Deductible Applies to Preventive"]},
    {"key": "ded_diag", "label": "Deductible Applies to Diagnostic",   "kind": "yesno", "section": "Maximums & Deductibles", "portal": "ded_diag"},

    # ── Plan provisions ──────────────────────────────────────────────────────
    {"key": "waiting_period", "label": "Is there a Waiting Period",  "kind": "yesno", "section": "Plan Provisions", "portal": "waiting_period",
     "aliases": ["Waiting Period", "Is there a Waiting Period?"]},
    {"key": "cob",            "label": "Coordination Of Benefits",   "kind": "text",  "section": "Plan Provisions", "portal": "_cob",
     "aliases": ["Coordination of Benefits", "COB"]},

    {"key": "pct_prev",  "label": "D0120 Preventative", "kind": "pct", "section": "Plan Provisions", "portal": "pct_prev",
     "aliases": ["Preventative %", "Preventive"]},
    {"key": "pct_basic", "label": "D2160 Basic",        "kind": "pct", "section": "Plan Provisions", "portal": "pct_basic",
     "aliases": ["Basic %", "Basic"]},
    {"key": "pct_major", "label": "D2740 Major",        "kind": "pct", "section": "Plan Provisions", "portal": "pct_major",
     "aliases": ["Major %", "Major"]},

    # ── Orthodontics ─────────────────────────────────────────────────────────
    {"key": "ortho_max",      "label": "Ortho Maximum$",                       "kind": "money", "section": "Orthodontics", "portal": "ortho_max",
     "aliases": ["Ortho Max", "Orthodontic Maximum", "Ortho Lifetime Maximum"]},
    {"key": "ortho_max_paid", "label": "Orthodontics Used Amount $",            "kind": "money", "section": "Orthodontics", "portal": "ortho_max_paid",
     "aliases": ["Ortho Used", "Orthodontics Used Amount"]},
    {"key": "ortho_ded",      "label": "Orthodontics Deductible Amount$",       "kind": "money", "section": "Orthodontics", "portal": "ortho_ded",
     "aliases": ["Ortho Deductible", "Orthodontics Deductible Amount"]},
    {"key": "ortho_ded_paid", "label": "Orthodontics Deductible Met Amount $",  "kind": "money", "section": "Orthodontics", "portal": "ortho_ded_paid",
     "aliases": ["Ortho Deductible Met", "Orthodontics Deductible Met Amount"]},

    # ── Clauses ──────────────────────────────────────────────────────────────
    {"key": "missing_tooth",  "label": "Does Missing Tooth Clause Apply?",     "kind": "yesno", "section": "Clauses", "portal": "missing_tooth",
     "aliases": ["Missing Tooth Clause", "Does Missing Tooth Clause Apply"]},
    {"key": "prev_in_max",    "label": "Preventative Included in Yearly Max?", "kind": "yesno", "section": "Clauses", "portal": "_prev_in_max",
     "aliases": ["Preventive Included in Yearly Max", "Preventative Included in Yearly Max"]},

    # OBS 4/5 — the two alternate-benefit questions. The portal states both in a
    # single "Alternate Benefits" provision and `new_plan` already splits them
    # into these two answers, so the sheet's Yes/No compares directly.
    {"key": "posterior_composite_downgrade",
     "label": "Are Posterior Composites Downgraded To Amalgam?", "kind": "yesno",
     "section": "Clauses", "portal": "posterior_composite_downgrade",
     "aliases": ["Are Posterior Composites Downgraded to Amalgam",
                 "Posterior Composites Downgraded To Amalgam"]},
    {"key": "porcelain_posterior_downgrade",
     "label": "Are Posterior Crowns Downgraded?", "kind": "yesno",
     "section": "Clauses", "portal": "porcelain_posterior_downgrade",
     "aliases": ["Are Posterior Crowns Downgraded",
                 "Are Porcelain Crowns Downgraded"]},

    # ── Coverage by CDT code ─────────────────────────────────────────────────
    # Each row compares a coverage percentage. Where Sabrina's label names one
    # code but the portal commonly reports the sibling code, extra codes are
    # listed as fallbacks and the first one the portal states is used.
    {"key": "d0220", "label": "D0220 Pas",             "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D0220", "D0230")},
    {"key": "d0120", "label": "D0120 Periodic Exam",   "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D0120")},
    {"key": "d0140", "label": "D0140 Limited Exam",    "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D0140")},
    {"key": "d0150", "label": "D0150 Diagnostic Exam", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D0150"),
     "aliases": ["D0150 Diagnostic Exam Comp"]},
    {"key": "d0210", "label": "D0210 FMX",             "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D0210")},
    {"key": "d0330", "label": "D0330 Pano",            "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D0330")},
    {"key": "d0274", "label": "D0274 Bitewings",       "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D0274", "D0272")},

    {"key": "d1110", "label": "D1110 Adult Prophy",     "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D1110")},
    {"key": "d1206", "label": "D1206 Fluoride Varnish", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D1206")},
    {"key": "d1208", "label": "D1208 Fluoride",         "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D1208", "D1206")},
    {"key": "d1351", "label": "D1351 Sealants",         "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D1351")},
    {"key": "d1510", "label": "D1510 Space Maintainer", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D1510")},

    {"key": "d2160", "label": "D2160 Amalgam Fillings",   "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D2160", "D2140")},
    {"key": "d2391", "label": "D2391 Composite Fillings", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D2391", "D2331")},
    {"key": "d2740", "label": "D2740 Crowns",             "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D2740")},
    {"key": "d2950", "label": "D2950 Core Buildups",      "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D2950")},
    {"key": "d2980", "label": "D2980 Crown Repair",       "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D2980")},

    {"key": "d3310", "label": "D3310 Endodontics", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D3310")},

    {"key": "d4260", "label": "D4260 Osseous Surgery",        "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D4260")},
    {"key": "d4341", "label": "D4341 Scaling Root Planing",   "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D4341")},
    {"key": "d4346", "label": "D4346 Gingival Inflammation",  "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D4346")},
    {"key": "d4355", "label": "D4355 Full Mouth Debridement", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D4355")},
    {"key": "d4381", "label": "D4381 Arestin",                "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D4381")},
    {"key": "d4910", "label": "D4910 Perio Maintenance",      "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D4910")},

    {"key": "d5110", "label": "D5110 Dentures",           "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D5110")},
    {"key": "d5212", "label": "D5212 Partial Dentures",   "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D5212", "D5213")},
    {"key": "d5899", "label": "D5899 Prosth Removable",   "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D5899")},

    {"key": "d6010", "label": "D6010 Implants", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D6010", "D6194")},
    {"key": "d6750", "label": "D6750 Bridges",  "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D6750", "D6245")},

    {"key": "d7140", "label": "D7140 Simple Ext",    "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D7140")},
    {"key": "d7210", "label": "D7210 Surgical Ext",  "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D7210", "D7240")},

    {"key": "d9110", "label": "D9110 Palliative Exam", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D9110")},
    {"key": "d9230", "label": "D9230 Nitrous",         "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D9230")},
    {"key": "d9243", "label": "D9243 Anesthesia",      "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D9243", "D9223", "D9222")},
    {"key": "d9944", "label": "D9944 Occlusal Guard",  "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D9944")},

    {"key": "ortho_coverage", "label": "Ortho Coverage", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D8080", "D8090", "D8010"),
     "aliases": ["Orthodontic Coverage", "Ortho %"]},
    {"key": "d8090", "label": "D8090", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D8090")},
    {"key": "d5995", "label": "D5995", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D5995")},
    {"key": "d6057", "label": "D6057", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D6057", "D6056")},
    {"key": "d6058", "label": "D6058", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D6058", "D6065")},
    {"key": "d9310", "label": "D9310", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D9310")},
]

# ══════════════════════════════════════════════════════════════════════════════
#  BENEFIT DETAILS — the other three columns of each CDT row
# ══════════════════════════════════════════════════════════════════════════════
#
# Every Benefit Details row states four comparable things, and the portal's
# procedure records carry a counterpart for each:
#
#     Sabrina column   portal field              example pair
#     ─────────────────────────────────────────────────────────────────────────
#     Frequency        frequency_limit           2X1Year / 2 TIMES IN 1 CALENDAR YEAR
#     Percentage       benefit_level             100%    / 100%
#     Age Limit        age_limit                 14      / 0-14
#     History          late_date_of_service      05/11/2026 / 05/11/26
#
# The Percentage rows are declared explicitly above; these three are generated
# per CDT code so the two lists cannot drift apart. They are flagged `derived`
# because they are read from the row's cells rather than from a label of their
# own — nothing in the label matcher should ever look for them.

_BENEFIT_ASPECTS = (
    ("freq", "Frequency", "frequency", "frequency_limit"),
    ("age",  "Age Limit", "agelimit",  "age_limit"),
    ("hist", "History",   "history",   "late_date_of_service"),
)

_ASPECT_SECTION = "Coverage Detail — Frequency / Age / History"

# Which codes actually carry each column, per the MetLife observations.
#
# Age Limit and History are only meaningful for a handful of procedures, and
# Frequency is not expected for a few. Generating rows for the rest produced ~70
# "blank on the sheet" flags that were nothing of the kind — the sheet is right
# to leave those cells empty. Note D4341 is in the history list but NOT the age
# list: Sabrina puts the quadrant count in its Age Limit column, not an age.
_AGE_LIMIT_CODES = {"D1206", "D1208", "D1351", "D1510", "D8080"}
_HISTORY_CODES = {
    "D0120", "D0140", "D0210", "D0274", "D0330", "D1110",
    "D1206", "D1208", "D1351", "D1510", "D4341", "D4910",
}
_NO_FREQUENCY_CODES = {"D3310", "D7140", "D7210", "D9230", "D9243", "D8080", "D8090"}


def _aspect_applies(aspect: str, code: str) -> bool:
    if aspect == "age":
        return code in _AGE_LIMIT_CODES
    if aspect == "hist":
        return code in _HISTORY_CODES
    return code not in _NO_FREQUENCY_CODES        # frequency


def _build_aspect_spec() -> list[dict]:
    out = []
    for field in _SPEC:
        if field["section"] != "Coverage by CDT Code":
            continue
        src = field.get("portal")
        if not (isinstance(src, tuple) and src and src[0] == "code"):
            continue
        codes = src[1:]
        primary = codes[0].upper()
        for suffix, title, kind, portal_field in _BENEFIT_ASPECTS:
            if not _aspect_applies(suffix, primary):
                continue
            out.append({
                "key":     f'{field["key"]}__{suffix}',
                "label":   f'{field["label"]} · {title}',
                "kind":    kind,
                "section": _ASPECT_SECTION,
                "portal":  ("codefield", portal_field) + codes,
                "derived": True,
                "row_key": field["key"],
                "aspect":  suffix,
            })
    return out


_SPEC += _build_aspect_spec()


# The fields actually printed as labels on the sheet, excluding the generated
# Frequency / Age Limit / History rows. This is what "fields read" means to a
# user looking at the upload box — counting the generated rows there makes a
# perfectly good parse look half-broken, since most CDT rows legitimately have
# no age limit or service history.
CORE_FIELD_KEYS = tuple(f["key"] for f in _SPEC if not f.get("derived"))


def core_fields(fields: dict) -> dict:
    """Only the values read from a label of their own."""
    return {k: v for k, v in (fields or {}).items() if k in set(CORE_FIELD_KEYS)}


# Fields that drive a claim's financial outcome — surfaced first in the UI and
# counted separately so a reviewer sees the expensive disagreements immediately.
_CRITICAL_KEYS = {
    "member_id", "group_number", "payor_id", "patient_dob", "subscriber_dob",
    "yearly_max", "yearly_max_paid", "indiv_ded", "indiv_ded_paid",
    "family_ded", "ortho_max", "ortho_max_paid",
    "pct_prev", "pct_basic", "pct_major", "in_network", "eff_date",
}


# ══════════════════════════════════════════════════════════════════════════════
#  LABEL MATCHING
# ══════════════════════════════════════════════════════════════════════════════

def _norm_label(s: str) -> str:
    """
    Canonical form of a label for matching: lowercase, punctuation and the
    decorative $ / # / (…) markers dropped, whitespace collapsed.

        "Yearly Max($)"                  → "yearly max"
        "Orthodontics Deductible Amount$" → "orthodontics deductible amount"
        "Does Missing Tooth Clause Apply?"→ "does missing tooth clause apply"
    """
    s = (s or "").replace(" ", " ")
    s = re.sub(r"[$#()\[\]:?.,*]", " ", s.lower())
    s = s.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


# Every label/alias in the spec — used so a value hunt never swallows the NEXT
# field's label as if it were this field's value.
_ALL_LABELS: set[str] = set()
for _f in _SPEC:
    if _f.get("derived"):
        continue          # read from a row's cells, never from a label
    _ALL_LABELS.add(_norm_label(_f["label"]))
    for _a in _f.get("aliases", ()):
        _ALL_LABELS.add(_norm_label(_a))

# Labels and headers that Sabrina prints but this audit does not compare. They
# are NOT values, so they both stop a value from running on and can never be
# picked up as one. Taken from a real export — the sheet's own field set.
_OTHER_SHEET_LABELS = {_norm_label(s) for s in (
    # Demographics / office block
    "Office Name", "Provider Name", "Preferred Provider Name", "Chair Provider Name",
    "Provider Speciality", "Provider Specialty", "Appointment Date",
    "Relation to Subscriber", "SSN#", "Patient ID",
    # Insurance block
    "Insurance Plan Name", "Fee Schedule", "Insurance Phone",
    "Eligibility Term Date", "Patient Term Date", "Eligibility Notes",
    "PPO / Indemnity / HMO Plan?",
    # Coverage block
    "Applies To", "Period", "Ortho Maximum Covered", "Ortho Payment Timing",
    "Are Major Services Paid on Prep or Seat date?", "Pre-Authorize over",
    "Dependent Age Limit",
    # Benefit Details question rows that this audit does not compare
    "When Is First Perio Maintenance Allowed After SRP ?",
    # Section + table headers
    "Demographics", "Office Information", "Patient/Subscriber Information",
    "Insurance Information", "Coverage", "Benefit Details", "Benefit Name",
    "Frequency", "Percentage", "Age Limit", "History", "Insurance Plan Breakdown",
    "Verification Date",
)}

# Generic section words from other sheet variants, kept for tolerance.
_NON_VALUES = _ALL_LABELS | _OTHER_SHEET_LABELS | {
    "patient information", "subscriber information", "benefits",
    "general benefit details", "plan information", "eligibility", "maximums",
    "deductibles", "orthodontics", "exams", "diagnostic", "preventive",
    "preventative", "basic restorative", "major restorative", "endodontics",
    "periodontics", "prosthodontics", "implant", "oral surgery", "adjunctive",
    "notes", "code", "description", "coverage %", "sabrina",
}
# NOTE: "yes"/"no" are deliberately NOT listed — they are the legitimate value
# of every Y/N field on the sheet, not headers.

# Every label on the sheet, compared or not — the set that stops a value.
# Indexed by first word so scanning a line for "does a label start here?" only
# tests the handful of plausible candidates.
_STOP_LABELS = _ALL_LABELS | _OTHER_SHEET_LABELS
_LABELS_BY_FIRST: dict[str, list[str]] = {}
for _lbl in _STOP_LABELS:
    if _lbl:
        _LABELS_BY_FIRST.setdefault(_lbl.split()[0], []).append(_lbl)

_SEP_RE = re.compile(r"^\s*[:\-–—=>|]+\s*")
_TRIM = " \t:-–—=|"

# A Benefit Details "Frequency" cell — "2X1Year", "1X12Months", "1XLifetime",
# "No Frequency", "NC". These sit between a CDT label and its Percentage cell
# and must be stepped over when the field being read is a coverage percentage.
_FREQ_RE = re.compile(
    r"^(?:\d+\s*x\s*\d*\s*(?:year|month|lifetime|day|week|visit)s?"
    r"|no\s+frequency|nc|n/c)$",
    re.IGNORECASE,
)


def _split_lines(text: str) -> list[str]:
    """PDF text → trimmed, non-empty lines (order preserved)."""
    out = []
    for raw in (text or "").replace(" ", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if line:
            out.append(line)
    return out


def _reflow_wrapped(lines: list[str]) -> list[str]:
    """
    Re-join text the PDF extractor split in the middle of a cell.

    Sabrina's table cells wrap, so one cell can arrive as two lines:

        D0220 PAs / "No" / "Frequency" / 100%      ← "No Frequency" wrapped
        Benefit Name / Frequency / ... / "Age" / "Limit"

    A fragment is identified by the fact that joining it to its predecessor
    produces something already known — one of the sheet's labels, or a
    Frequency phrase. Without this, the stray fragment "Frequency" collides
    with the table's own "Frequency" column header and is read as the next
    label, which ends the value hunt and leaves the whole row blank.

    Only a first piece that is NOT itself a complete label may absorb a
    follower, so two genuinely separate labels are never fused.
    """
    out = list(lines)
    for _ in range(3):                      # a cell can wrap more than once
        merged: list[str] = []
        i = 0
        changed = False
        while i < len(out):
            joined = None
            if _norm_label(out[i]) not in _STOP_LABELS:
                for take in (3, 2):         # longest wrap first
                    if i + take > len(out):
                        continue
                    cand = " ".join(out[i:i + take])
                    if _norm_label(cand) in _STOP_LABELS or _FREQ_RE.match(cand.strip()):
                        joined = (cand, take)
                        break
            if joined:
                merged.append(joined[0])
                i += joined[1]
                changed = True
            else:
                merged.append(out[i])
                i += 1
        out = merged
        if not changed:
            break
    return out


# Page furniture that sits directly after the last table row.
_BOILERPLATE_RE = re.compile(
    r"^\s*(?:©|\(c\))|all rights reserved|verification date", re.IGNORECASE)


def _looks_like_value(candidate: str) -> bool:
    """A string is usable as a value unless it is a label, header or boilerplate."""
    if _BOILERPLATE_RE.search(candidate):
        return False
    n = _norm_label(candidate)
    return bool(n) and n not in _NON_VALUES


def _label_span(words: list[str], i: int, target: str) -> int:
    """
    How many words at `words[i:]` the label `target` occupies — 0 if it doesn't
    start there.

    Matched LONGEST-first so decoration that normalizes away ("$", "$:", "#")
    is consumed as part of the printed label; otherwise
    "Orthodontics Deductible Met Amount $: $0.00" would yield "$: $0.00".
    """
    n_target_words = len(target.split())
    max_take = min(len(words) - i, n_target_words + 3)
    for take in range(max_take, 0, -1):
        if _norm_label(" ".join(words[i:i + take])) == target:
            return take
    return 0


def _any_label_at(words: list[str], i: int) -> bool:
    """Whether ANY known label begins at words[i] — the stop signal for a value."""
    norm = _norm_label(words[i])
    if not norm:
        return False
    for lbl in _LABELS_BY_FIRST.get(norm.split()[0], ()):
        if _label_span(words, i, lbl):
            return True
    return False


def _refine_inline(kind: str, inline: str) -> str | None:
    """
    Validate an inline (same-line) value against the kind of cell expected.

    Returns None when the text clearly isn't that cell — a percentage field
    sitting next to a Frequency cell, or leftover label wording — so the caller
    falls through to the following lines instead of storing something wrong.
    """
    if kind != "pct":
        return inline
    # Whole string first, so multi-word statements survive intact ("Not Covered"
    # is a stated 0% benefit; splitting it into words loses that).
    if not _FREQ_RE.match(inline) and _num_pct(inline) is not None:
        return inline
    # Otherwise this is a flattened row carrying several cells at once — take
    # the first token that reads as a percentage, stepping over Frequency cells.
    for token in inline.split():
        if _FREQ_RE.match(token):
            continue
        if _num_pct(token) is not None:
            return token
    return None


def _pick_cell(kind: str, cands: list[tuple[int, str]]) -> tuple[int, str] | None:
    """
    Choose this field's value from the cells that follow its label.

    A Benefit Details row is printed one cell per line with empty cells left
    out, so a coverage percentage can be preceded by a Frequency cell and
    followed by Age Limit and History cells:

        D0120 Periodic Exam / 2X1Year / 100% / 01/28/2026
        D3310 Endodontics   / 80%
        D5899 Prosth Removable / NC / 0

    A percentage field therefore steps over Frequency cells and takes the first
    cell that actually reads as a percentage. Multi-line free text (an address
    wrapped across lines) is joined instead. Everything else takes the first cell.
    """
    if not cands:
        return None

    if kind == "pct":
        for m, cand in cands:
            if _FREQ_RE.match(cand):
                continue                      # Frequency column — not the percentage
            if _num_pct(cand) is not None:
                return m, cand
        return None

    if kind in ("address", "text"):
        # Sabrina wraps long values ("P O BOX 981282 , , EL PASO," / "TX - 79998")
        # across lines; a stop-label already ended the candidate list.
        joined = " ".join(c for _, c in cands).strip()
        return (cands[-1][0], joined) if joined else None

    return cands[0]


# Sabrina writes "NH" (no history) where a procedure has never been performed.
_HISTORY_NONE = {"nh", "no history", "none", "n/h"}


def _classify_row_cells(cells: list[str]) -> dict[str, str | None]:
    """
    Split one Benefit Details row's cells into its columns.

    Empty cells are omitted by the extractor, so position alone cannot say which
    column a cell belongs to — each is identified by its shape instead, in
    column order:

        Frequency   before the percentage, matching the frequency vocabulary
        Percentage  the first cell that reads as a percentage
        Age Limit   a bare 1-3 digit number after the percentage
        History     a date, or "NH", after the percentage

    A cell after the percentage that is none of these (the Coverage column, page
    furniture) is ignored rather than guessed at.
    """
    freq = pct = age = hist = None
    for cell in cells:
        s = cell.strip()
        if pct is None:
            if freq is None and _FREQ_RE.match(s):
                freq = s
            elif _num_pct(s) is not None:
                pct = s
            continue
        if hist is None and (_num_date(s) is not None or s.lower() in _HISTORY_NONE):
            hist = s
        elif age is None and re.fullmatch(r"\d{1,3}", s):
            age = s
    return {"frequency": freq, "percentage": pct, "age_limit": age, "history": hist}


def _capture_benefit_rows(lines: list[str]) -> dict[str, dict]:
    """
    Read the Frequency / Age Limit / History cells for every CDT row.

    Runs as its own pass: the percentage is already resolved by the main field
    loop, and re-finding each label here keeps that verified path untouched.
    """
    rows: dict[str, dict] = {}
    for field in _SPEC:
        if field.get("derived") or field["section"] != "Coverage by CDT Code":
            continue
        targets = sorted(
            [_norm_label(field["label"])] +
            [_norm_label(a) for a in field.get("aliases", ())],
            key=lambda t: -len(t.split()))

        at = None
        for target in targets:
            for i, line in enumerate(lines):
                words = line.split()
                if any(_label_span(words, p, target) for p in range(len(words))):
                    at = i
                    break
            if at is not None:
                break
        if at is None:
            continue

        cells = []
        for m in range(at + 1, min(at + 8, len(lines))):
            if _any_label_at(lines[m].split(), 0) or not _looks_like_value(lines[m]):
                break
            cells.append(lines[m])
        rows[field["key"]] = _classify_row_cells(cells)
    return rows


def _anchor_line(lines: list[str], anchor: str) -> int:
    """First line on which the anchor label appears (at any column)."""
    norm = _norm_label(anchor)
    for i, line in enumerate(lines):
        words = line.split()
        for p in range(len(words)):
            if _label_span(words, p, norm):
                return i
    return 0


def _find_value(lines: list[str], field: dict, cursor: dict[int, int]
                ) -> tuple[str | None, int | None]:
    """
    Locate one field's value on the sheet.

    A label on a form PDF is followed by its value either on the SAME line — the
    grid row flattened by the text extractor, possibly with further columns
    after it — or on the NEXT line (label printed above its value). Both are
    tried, in that order.

    Matching is done at WORD level, not line level, because one flattened line
    routinely carries several fields:

        Individual Deductible($) $50.00 Paid to Date($) $50.00

    `cursor` remembers how far into each line has already been claimed, so the
    second field on a line still finds its own value and no value is read twice.
    `after` anchors a label that appears repeatedly ("Date of Birth",
    "Paid to Date($)") to the first occurrence following its section anchor.
    """
    # Longest label first: where one label is a prefix of another the more
    # specific wins, so "D0150 Diagnostic Exam Comp" is not matched as
    # "D0150 Diagnostic Exam" with a leftover "Comp" read as the value.
    targets = [_norm_label(field["label"])]
    targets += [_norm_label(a) for a in field.get("aliases", ())]
    targets.sort(key=lambda t: -len(t.split()))

    start_line = _anchor_line(lines, field["after"]) if field.get("after") else 0
    blank_at: int | None = None

    for target in targets:
        for i in range(start_line, len(lines)):
            words = lines[i].split()
            for p in range(cursor.get(i, 0), len(words)):
                span = _label_span(words, p, target)
                if not span:
                    continue

                # (a) value on the label's own line, up to the next label
                j = p + span
                k = j
                while k < len(words) and not _any_label_at(words, k):
                    k += 1
                inline = _SEP_RE.sub("", " ".join(words[j:k])).strip(_TRIM)
                if inline and _looks_like_value(inline):
                    refined = _refine_inline(field["kind"], inline)
                    if refined is not None:
                        cursor[i] = k
                        return refined, i
                    # Not the cell we're after (e.g. a Frequency cell, or label
                    # text the label pattern didn't cover) → try the next lines.

                # The label is used up either way — don't rematch it.
                cursor[i] = j

                # (b) value on the following line(s) — label-above-value layout,
                # which is how Sabrina prints both the demographics blocks and
                # the Benefit Details table (one cell per line, empty cells
                # omitted entirely).
                cands: list[tuple[int, str]] = []
                for m in range(i + 1, min(i + 8, len(lines))):
                    if cursor.get(m):
                        continue
                    cand = _SEP_RE.sub("", lines[m]).strip(_TRIM)
                    if not cand:
                        continue
                    if not _looks_like_value(cand) or _any_label_at(lines[m].split(), 0):
                        break          # next label reached — no more cells for this field
                    cands.append((m, cand))

                picked = _pick_cell(field["kind"], cands)
                if picked is not None:
                    m, value = picked
                    for idx, _ in cands:
                        cursor[idx] = len(lines[idx].split())   # consume skipped cells too
                        if idx == m:
                            break
                    return value, m

                blank_at = i
                break
            else:
                continue
            break  # label found on line i; stop scanning further lines

    return None, blank_at


# ══════════════════════════════════════════════════════════════════════════════
#  SABRINA PDF DETECTION
# ══════════════════════════════════════════════════════════════════════════════

# Labels that are distinctive to the Sabrina breakdown sheet. Generic dental
# words are deliberately excluded — they appear on carrier PDFs too.
_MARKERS = [
    "oon benefits",
    "starting month of plan year",
    "deductible applies to preventative",
    "deductible applies to diagnostic",
    "is there a waiting period",
    "does missing tooth clause apply",
    "preventative included in yearly max",
    "orthodontics deductible met amount",
    "orthodontics used amount",
    "coordination of benefits",
    "patient eff date",
    "member id",
    "payor id",
    "ortho maximum",
    "yearly max",
]

_MIN_MARKERS = 4


def is_sabrina_pdf(text: str) -> bool:
    """
    True when the PDF text looks like a Sabrina patient-breakdown export.

    Deliberately label-based rather than branding-based: the export does not
    reliably print the word "Sabrina", but its field sheet is unmistakable.
    """
    return sabrina_marker_count(text) >= _MIN_MARKERS


def sabrina_marker_count(text: str) -> int:
    """How many Sabrina marker labels the text contains (for diagnostics)."""
    flat = _norm_label(" ".join(_split_lines(text)))
    return sum(1 for m in _MARKERS if m in flat)


# ══════════════════════════════════════════════════════════════════════════════
#  PARSE: SABRINA PDF → {field key: raw string}
# ══════════════════════════════════════════════════════════════════════════════

def parse_sabrina_text(text: str) -> dict:
    """Pull every spec'd field out of already-extracted Sabrina PDF text."""
    lines = _reflow_wrapped(_split_lines(text))

    values: dict[str, str | None] = {}
    cursor: dict[int, int] = {}     # line index → words already claimed
    missing_labels: list[str] = []

    for field in _SPEC:
        if field.get("derived"):
            continue                     # filled in from the row pass below
        value, idx = _find_value(lines, field, cursor)
        values[field["key"]] = value
        if idx is None:
            missing_labels.append(field["label"])

    # Frequency / Age Limit / History for each CDT row.
    benefit_rows = _capture_benefit_rows(lines)
    for row_key, columns in benefit_rows.items():
        values[f"{row_key}__freq"] = columns["frequency"]
        values[f"{row_key}__age"] = columns["age_limit"]
        values[f"{row_key}__hist"] = columns["history"]
    for field in _SPEC:
        if field.get("derived"):
            values.setdefault(field["key"], None)

    if _DEBUG and missing_labels:
        log.warning("Sabrina labels not found in PDF (%d): %s",
                    len(missing_labels), ", ".join(missing_labels))

    return {
        "fields": values,
        "benefit_rows": benefit_rows,
        "labels_not_found": missing_labels,
        "line_count": len(lines),
    }


def parse_sabrina_pdf(pdf_bytes: bytes) -> dict:
    """Read a Sabrina PDF and return its parsed fields (+ the raw text)."""
    text = _extract_text(pdf_bytes)

    if len(text.strip()) < 100:
        raise ValueError(
            "This PDF has no readable text layer (it appears to be scanned or "
            "image-based), so it can't be parsed. Re-download the breakdown "
            "from Sabrina as a text PDF rather than a scan."
        )

    parsed = parse_sabrina_text(text)
    parsed["text"] = text
    parsed["marker_count"] = sabrina_marker_count(text)
    return parsed


# ══════════════════════════════════════════════════════════════════════════════
#  VALUE NORMALIZERS
# ══════════════════════════════════════════════════════════════════════════════

def _blank(v) -> bool:
    return v is None or str(v).strip().lower() in _BLANKS


def _num_money(v) -> float | None:
    if _blank(v):
        return None
    s = str(v)
    if "unlimited" in s.lower() or "no max" in s.lower():
        return _UNLIMITED_MAX
    m = re.search(r"-?[\d,]*\.?\d+", s.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _num_pct(v) -> float | None:
    """
    Coverage percentage. Handles '80%', '80', 'Not Covered' → 0,
    and a bare fraction ('0.8') which some exports use.
    """
    if _blank(v):
        return None
    s = str(v).strip().lower()
    if "not covered" in s or s in ("nc", "not a covered benefit", "excluded"):
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    if m:
        return float(m.group(1))
    m = re.search(r"^(\d+(?:\.\d+)?)$", s)
    if m:
        val = float(m.group(1))
        # A bare "0.8" means 80% — a coverage level is never 0.8%.
        return val * 100 if 0 < val <= 1 else val
    # "Covered" with no number states coverage but not the level → not comparable
    return None


# Sabrina states network status as the bare word "In" / "Out".
_YES = {"y", "yes", "true", "t", "x", "✓", "applies", "covered", "included",
        "in", "in network", "in-network", "par", "participating", "available"}
_NO = {"n", "no", "false", "f", "does not apply", "not applicable", "excluded",
       "not covered", "out", "oon", "out of network", "out-of-network",
       "non-par", "nonpar", "not included", "not available"}


def _num_yesno(v) -> str | None:
    if _blank(v):
        return None
    s = re.sub(r"[.\s]+$", "", str(v).strip().lower())
    if s in _YES:
        return "YES"
    if s in _NO:
        return "NO"
    # Leading token wins for values like "Yes - 12 months" / "No (waived)"
    head = re.split(r"[ ,;(\-–—/]", s, 1)[0]
    if head in _YES:
        return "YES"
    if head in _NO:
        return "NO"
    return None


_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y-%m-%d",
                 "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y",
                 "%d %b %Y", "%d %B %Y", "%m/%Y", "%m%d%Y")


def _num_date(v) -> str | None:
    """Normalize to MM/DD/YYYY so 1/8/2026, 01/08/26 and Jan 08, 2026 agree."""
    if _blank(v):
        return None
    import datetime
    s = str(v).strip()
    m = re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}"
                  r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}", s)
    if m:
        s = m.group(0).replace(".", "")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return None


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _num_month(v) -> int | None:
    """
    Plan-year start month → 1-12. Accepts 'January', 'Jan', '1', '01/2026',
    and a full date (whose month is what matters here).
    """
    if _blank(v):
        return None
    s = str(v).strip().lower()
    for name, num in _MONTHS.items():
        if s.startswith(name):
            return num
    m = re.match(r"^(\d{1,2})\b", s)
    if m:
        num = int(m.group(1))
        return num if 1 <= num <= 12 else None
    return None


# Three or more repeated mask characters — enough to distinguish a masked
# identifier from a real one that merely contains an X.
_MASK_RE = re.compile(r"(?:X{3,}|\*{3,}|•{3,}|#{3,})", re.IGNORECASE)


def _visible_part(value: str) -> tuple[str, str] | None:
    """
    For a partially masked identifier, what the mask leaves readable:
    ("suffix", "6200") for "XXXXXXX6200", ("prefix", "8339") for "8339XXXXX".

    None when nothing can be aligned — masked in the middle, or masked end to
    end. Masks do not preserve length ("XXXXXXX6200" is 11 characters for a
    9-character id), so the visible run is compared, not the position.
    """
    m = _MASK_RE.search(value)
    if not m:
        return None
    before, after = value[:m.start()], value[m.end():]
    if before and after:
        return None                      # masked in the middle
    if after:
        return "suffix", after
    if before:
        return "prefix", before
    return None                          # nothing visible at all


# Frequency, as the two systems say it:
#   Sabrina  "2X1Year"  "1X60Months"  "1XLifetime"  "No Frequency"  "NC"
#   portal   "2 TIMES IN 1 CALENDAR YEAR"  "1 TIME IN 60 MONTHS"
#            "ONCE PER LIFETIME"  "No Limitations"  "*NOT COVERED"
# Both reduce to (how many, per how many months). A year is normalized to 12
# months so "1X1Year" and "1 TIME IN 1 CALENDAR YEAR" agree; the portal often
# appends conditions ("…, PERMANENT MOLARS ONLY") which are ignored.
_FREQ_UNLIMITED = ("unlimited",)
_FREQ_NOT_COVERED = ("not covered",)

_FREQ_COMPACT_RE = re.compile(
    r"^(\d+)\s*x\s*(\d*)\s*(year|month|week|day|visit)s?$", re.IGNORECASE)
_FREQ_PROSE_RE = re.compile(
    r"^(?:(\d+)|once|twice)\s*(?:times?)?\s*(?:in|per|every)\s*(\d*)\s*"
    r"(?:calendar\s*|contract\s*|plan\s*|benefit\s*)?(year|month|week|day)s?",
    re.IGNORECASE)


def _num_frequency(v) -> tuple | None:
    if _blank(v):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip().lower().lstrip("*")
    if "not covered" in s or s in ("nc", "n/c"):
        return _FREQ_NOT_COVERED
    if "no limitation" in s or "no frequency" in s or "unlimited" in s:
        return _FREQ_UNLIMITED
    if "lifetime" in s:
        m = re.match(r"(\d+)\s*x", s)
        return (int(m.group(1)) if m else 1, "lifetime")
    m = _FREQ_COMPACT_RE.match(s)
    if not m:
        m = _FREQ_PROSE_RE.match(s)
        if m:
            count = int(m.group(1)) if m.group(1) else (2 if s.startswith("twice") else 1)
            span = int(m.group(2) or 1)
            unit = m.group(3).lower()
            return (count, span * 12 if unit == "year" else span)
        return None
    count = int(m.group(1))
    span = int(m.group(2) or 1)
    unit = m.group(3).lower()
    return (count, span * 12 if unit == "year" else span)


def _num_agelimit(v) -> int | None:
    """
    Upper age bound. Sabrina states a single number ("14"); the portal states a
    range ("0-14"), so both reduce to the ceiling.
    """
    if _blank(v):
        return None
    s = str(v).strip()
    m = re.fullmatch(r"\s*(\d{1,3})\s*[-–]\s*(\d{1,3})\s*", s)
    if m:
        return int(m.group(2))
    m = re.fullmatch(r"\s*(\d{1,3})\s*", s)
    if m:
        return int(m.group(1))
    if re.search(r"\d{1,3}\s*(?:and\s*(?:up|over|older)|\+)", s, re.IGNORECASE):
        return 99
    if "no age limit" in s.lower() or "none" in s.lower():
        return 99
    return None


def _agelimit_lower(v) -> int | None:
    """Lower bound of a portal age range; None when it states only a ceiling."""
    m = re.fullmatch(r"\s*(\d{1,3})\s*[-–]\s*(\d{1,3})\s*", str(v or ""))
    return int(m.group(1)) if m else None


def _blank_means_no_limit(kind: str, portal_value) -> bool:
    """
    Whether an EMPTY Frequency / Age Limit cell agrees with the portal.

    Sabrina leaves these cells blank to say "no limit", which is exactly what
    the portal says as "No Limitations" or as the full 0-99 age span. Counting
    those blanks as gaps buries the real findings under ~30 rows of noise.

    A blank is only agreement when the portal states no limit either. A real
    restriction the sheet failed to record — "1 TIME IN 1 CALENDAR YEAR", or an
    age range with a floor such as 14-99 — stays reported.
    """
    if kind == "frequency":
        return _num_frequency(portal_value) == _FREQ_UNLIMITED
    if kind == "agelimit":
        ceiling = _num_agelimit(portal_value)
        return (ceiling is not None and ceiling >= 99
                and _agelimit_lower(portal_value) in (0, None))
    return False


def _num_history(v) -> str | None:
    """Last date of service, or the sentinel NONE for Sabrina's "NH"."""
    if _blank(v):
        return None
    if str(v).strip().lower() in _HISTORY_NONE:
        return "NONE"
    return _num_date(v)


def _norm_id(v) -> str | None:
    """IDs compare on alphanumerics only — '12345-01' vs '1234501'."""
    if _blank(v):
        return None
    s = re.sub(r"[^A-Z0-9]", "", str(v).upper())
    return s or None


def _norm_text(v) -> str | None:
    if _blank(v):
        return None
    s = re.sub(r"[^A-Z0-9 ]", " ", str(v).upper())
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


# Carrier brands, so "Metlife PDP+" and "(IN) MetLife(TX)- PO Box 981282- 79998"
# are recognized as the same insurer. Longest first so "united concordia" wins
# over "concordia" and "delta dental" over "delta".
_CARRIER_BRANDS = (
    "united concordia", "delta dental", "blue cross", "blue shield",
    "mutual of omaha", "physicians mutual", "sun life", "guardian",
    "metlife", "cigna", "aetna", "dentaquest", "ameritas", "principal",
    "humana", "anthem", "careington", "solstice", "dominion", "liberty",
    "geha", "tricare", "unum", "lincoln", "dnoa", "concordia", "renaissance",
    "assurant", "premera", "regence", "wellpoint",
)


def _carrier_brand(v) -> str | None:
    """The carrier brand named in a value, if any."""
    if _blank(v):
        return None
    s = re.sub(r"[^a-z ]", " ", str(v).lower())
    s = re.sub(r"\s+", " ", s)
    for brand in _CARRIER_BRANDS:
        if brand in s:
            return brand
    return None


_NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV", "MD", "DDS", "DMD"}


def _norm_name(v) -> tuple[str, ...] | None:
    """
    Name → sorted significant tokens, so 'LAST, FIRST' (Sabrina/Denticon style)
    and 'First Last' (portal style) compare equal. Middle initials and
    generational suffixes are dropped: they differ between systems constantly
    and are never the point of an audit.
    """
    if _blank(v):
        return None
    s = re.sub(r"[^A-Z ,]", " ", str(v).upper()).replace(",", " ")
    tokens = [t for t in s.split() if len(t) > 1 and t not in _NAME_SUFFIXES]
    return tuple(sorted(tokens)) or None


def _addr_tokens(v) -> set[str] | None:
    """Address → token set, with the usual postal abbreviations unified."""
    if _blank(v):
        return None
    s = _norm_text(v) or ""
    repl = {
        "POBOX": "PO BOX", "P O BOX": "PO BOX",
        "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "DRIVE": "DR",
        "SUITE": "STE", "BOULEVARD": "BLVD", "NORTH": "N", "SOUTH": "S",
        "EAST": "E", "WEST": "W",
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    tokens = {t for t in s.split() if t}
    return tokens or None


# ══════════════════════════════════════════════════════════════════════════════
#  COMPARISON
# ══════════════════════════════════════════════════════════════════════════════

_MONEY_TOLERANCE = 0.01   # cents — "$2000" vs "$2,000.00"
_PCT_TOLERANCE = 0.01
_ADDR_OVERLAP = 0.7       # share of the smaller token set that must match


def _compare(kind: str, sab, por) -> tuple[bool | None, str]:
    """
    Compare one field.

    Returns (equal, note). `equal is None` means "not comparable" — either side
    was blank, or the values are stated in a form we can't reduce to a common
    unit. Not-comparable never counts as a mismatch.
    """
    if kind == "money":
        a, b = _num_money(sab), _num_money(por)
        if a is None or b is None:
            return None, ""
        return abs(a - b) <= _MONEY_TOLERANCE, ""

    if kind == "pct":
        a, b = _num_pct(sab), _num_pct(por)
        if a is None or b is None:
            return None, ""
        return abs(a - b) <= _PCT_TOLERANCE, ""

    if kind == "yesno":
        a, b = _num_yesno(sab), _num_yesno(por)
        if a is None or b is None:
            return None, ""
        return a == b, ""

    if kind == "date":
        a, b = _num_date(sab), _num_date(por)
        if a is None or b is None:
            return None, ""
        return a == b, ""

    if kind == "month":
        a, b = _num_month(sab), _num_month(por)
        if a is None or b is None:
            return None, ""
        return a == b, ""

    if kind == "frequency":
        a, b = _num_frequency(sab), _num_frequency(por)
        if a is None or b is None:
            return None, ""
        if a == b:
            return True, ""
        # "1X60Months" and "1X5Years" are the same limit stated two ways; the
        # canonical form already reconciles those, so a difference here is real.
        return False, ""

    if kind == "agelimit":
        a, b = _num_agelimit(sab), _num_agelimit(por)
        if a is None or b is None:
            return None, ""
        if a == b:
            return True, ""
        # 99 and above is "no real cap" on both sides.
        if a >= 99 and b >= 99:
            return True, "both state no effective age cap"
        return False, ""

    if kind == "history":
        a, b = _num_history(sab), _num_history(por)
        if a is None or b is None:
            return None, ""
        if a == b:
            return True, ""
        if a == "NONE":
            return False, "Sabrina shows no history but the portal has a service date"
        if b == "NONE":
            return False, "portal shows no history but Sabrina has a service date"
        return False, ""

    if kind == "id":
        a, b = _norm_id(sab), _norm_id(por)
        if a is None or b is None:
            return None, ""
        if a == b:
            return True, ""

        # Portals routinely mask identifiers ("XXXXXXX6200"). Such a value can
        # never equal the real one, so comparing it literally manufactures a
        # mismatch on every patient. Compare only what the mask actually shows.
        for masked, plain, who in ((b, a, "portal"), (a, b, "Sabrina")):
            if not _MASK_RE.search(masked):
                continue
            visible = _visible_part(masked)
            if visible is None:
                return None, f"{who} value is fully masked — not comparable"
            side, text = visible
            agrees = plain.endswith(text) if side == "suffix" else plain.startswith(text)
            return agrees, (
                f"{who} value is masked; the {len(text)} visible characters agree"
                if agrees else
                f"{who} value is masked and its visible characters differ"
            )

        # Group numbers/payor IDs are often padded or suffixed by one system.
        da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
        if da and db and da.lstrip("0") == db.lstrip("0"):
            return True, "digits match; formatting differs"
        return False, ""

    if kind == "carrier":
        # Same insurer is the same value, however each system decorates it.
        ba, bb = _carrier_brand(sab), _carrier_brand(por)
        if ba and bb:
            if ba == bb:
                same = _norm_text(sab) == _norm_text(por)
                return True, "" if same else "same carrier, stated differently"
            return False, f"different carriers ({ba} vs {bb})"
        # Neither side names a brand we know — fall back to plain text rules.
        return _compare("text", sab, por)

    if kind == "name":
        a, b = _norm_name(sab), _norm_name(por)
        if a is None or b is None:
            return None, ""
        if a == b:
            return True, ""
        # One system holding only first+last while the other adds a middle name
        # is a formatting difference, not a data conflict.
        sa, sb = set(a), set(b)
        if sa and sb and (sa <= sb or sb <= sa):
            return True, "name subset; one system stores an extra given name"
        return False, ""

    if kind == "address":
        a, b = _addr_tokens(sab), _addr_tokens(por)
        if a is None or b is None:
            return None, ""
        overlap = len(a & b) / min(len(a), len(b))
        if overlap >= _ADDR_OVERLAP:
            return True, "" if overlap == 1 else "same address, different formatting"
        return False, ""

    # plain text
    a, b = _norm_text(sab), _norm_text(por)
    if a is None or b is None:
        return None, ""
    if a == b:
        return True, ""
    # Carrier/group names get abbreviated ("DELTA DENTAL OF WI" vs "DELTA
    # DENTAL WISCONSIN") — treat containment as agreement.
    if a in b or b in a:
        return True, "one value is an abbreviation of the other"
    return False, ""


# ══════════════════════════════════════════════════════════════════════════════
#  PORTAL SIDE
# ══════════════════════════════════════════════════════════════════════════════

def _portal_breakdown(portal_raw: dict) -> dict:
    """
    Normalize the insurance portal export (or parsed carrier PDF) into the
    project's standard breakdown dict via `new_plan._extract`.

    Denticon is intentionally empty — this flow has no Denticon data — and the
    LLM interpreter is skipped because every audited field is a hard portal
    fact.
    """
    from new_plan import _extract as _extract_breakdown

    payload = dict(portal_raw or {})
    payload["_skip_llm"] = True
    return _extract_breakdown(payload, {})


def _pct_from_procs(procs: dict, codes: tuple[str, ...]) -> str | None:
    """Coverage % for the first CDT code the portal actually reports."""
    for code in codes:
        proc = (procs or {}).get(code.upper())
        if not proc:
            continue
        level = proc.get("benefit_level") or proc.get("coverage") or proc.get("plan_pays")
        if not _blank(level):
            return str(level)
        # An explicit "not covered" frequency IS a stated 0% benefit.
        if "not covered" in str(proc.get("frequency_limit", "")).lower():
            return "0%"
    return None


def _procfield_from_procs(procs: dict, field: str, codes: tuple[str, ...]) -> str | None:
    """A named field off the first CDT code the portal actually reports."""
    for code in codes:
        proc = (procs or {}).get(code.upper())
        if not proc:
            continue
        value = proc.get(field)
        if not _blank(value):
            return str(value)
    return None


def _portal_in_network(bd: dict, portal_raw: dict) -> str | None:
    """
    Derive In-Network YES/NO from whatever the portal states — the breakdown's
    network_status / fee_schedule / plan_type, else the raw provider block.
    """
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}
    provider = ml.get("provider_info", {}) if isinstance(ml.get("provider_info"), dict) else {}
    for cand in (bd.get("network_status"), bd.get("fee_schedule"),
                 provider.get("provider_network_status"), bd.get("plan_type")):
        if _blank(cand):
            continue
        s = str(cand).lower()
        if "non-par" in s or "nonpar" in s or "out of network" in s or "out-of-network" in s:
            return "No"
        if ("ppo" in s or "premier" in s or "in network" in s or "in-network" in s
                or "par" in s or "hmo" in s or "epo" in s):
            return "Yes"
    return None


def _portal_yearly_max_paid(bd: dict, portal_raw: dict) -> str | None:
    """
    Amount applied to the yearly max. Portals report the REMAINING balance, so
    paid-to-date = total − remaining.
    """
    total = _num_money(bd.get("yearly_max"))
    remaining = _num_money(bd.get("yearly_rem"))
    if total is None or remaining is None:
        return None
    if total >= _UNLIMITED_MAX:      # unlimited max → "used" is not derivable
        return None
    return f"{max(total - remaining, 0.0):.2f}"


# How a plan coordinates with other coverage. MetLife states it in a provision
# ("… any other dental plan: Birthday rule, Regular COB") mixing the order-of-
# benefits rule with the COB method; only the method is comparable, so the
# recognized methods are mapped to the wording Sabrina uses.
_COB_METHODS = (
    ("non-duplication", "Non-Duplication"),
    ("nonduplication",  "Non-Duplication"),
    ("non duplication", "Non-Duplication"),
    ("maintenance of benefits", "Maintenance of Benefits"),
    ("carve out",  "Carve Out"),
    ("carve-out",  "Carve Out"),
    ("regular cob", "Standard"),
    ("standard cob", "Standard"),
    ("traditional", "Standard"),
    ("full cob",   "Standard"),
)


def _coalesce_keys(obj: dict, *keys):
    """First key present on `obj` with a non-blank value."""
    for key in keys:
        if key in obj and not _blank(obj[key]):
            return obj[key]
    return None


def _portal_cob(bd: dict, portal_raw: dict) -> str | None:
    """Coordination-of-benefits method as stated in the portal's provisions."""
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}
    for prov in (ml.get("provisions") or []):
        if not isinstance(prov, dict):
            continue
        if "coordination of benefits" not in str(prov.get("rule", "")).lower():
            continue
        value = str(prov.get("value", "")).lower()
        for needle, method in _COB_METHODS:
            if needle in value:
                return method
        # The provision exists but names no method we recognize — report the
        # raw text rather than silently claiming the portal said nothing.
        return str(prov.get("value", "")).strip() or None
    return None


def _portal_prev_in_max(bd: dict, portal_raw: dict) -> str | None:
    """
    Whether preventive services count toward the yearly maximum.

    The portal states it as the category list printed under the Annual maximum —
    "for Diagnostic, Preventive, Restorative, Endodontics, Prosthodontics, Oral
    Surgery, Adjunctive, Implant Services". Preventive appearing in that list
    means it draws down the maximum.

    Captured by the extension as financials.annual_max.applies_to; exports made
    before that was added simply have nothing here, and the row stays unstated
    rather than guessed at.
    """
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}
    financials = ml.get("financials") or {}
    annual = financials.get("annual_max") or {}
    applies = annual.get("applies_to") if isinstance(annual, dict) else None
    if _blank(applies):
        return None
    text = str(applies).lower()
    return "Yes" if ("preventive" in text or "preventative" in text) else "No"


def _portal_oon_benefits(bd: dict, portal_raw: dict) -> str | None:
    """
    Whether the plan pays anything out of network.

    Read from the per-category `covered_services` rows, which carry an
    `out_of_network` benefit alongside the in-network one:

        {"category": "PREVENTIVE",
         "in_network":     "100% Deductible Applies : No",
         "out_of_network": "100% Deductible Applies : No"}

    Any category paying more than 0% out of network means the plan has OON
    benefits. Only when no category states an OON benefit at all do we fall
    back to the provision text — and an in-network fee schedule is never taken
    to imply OON coverage.
    """
    ml = (portal_raw or {}).get("metlife_data") or portal_raw or {}

    services = ml.get("covered_services")
    if isinstance(services, list) and services:
        stated = pays = False
        for row in services:
            if not isinstance(row, dict):
                continue
            raw = _coalesce_keys(row, "out_of_network", "out_network", "oon",
                                 "outofnetwork", "non_par")
            if _blank(raw):
                continue
            stated = True
            text = str(raw).lower()
            if "not covered" in text or "no coverage" in text:
                continue
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if m and float(m.group(1)) > 0:
                pays = True
                break
        if stated:
            return "Yes" if pays else "No"

    blobs = []
    for prov in (ml.get("provisions") or []):
        blobs.append(" ".join(str(v) for v in prov.values()) if isinstance(prov, dict) else str(prov))
    flat = " ".join(blobs).lower()
    if not flat:
        return None
    if "no out-of-network" in flat or "no out of network" in flat:
        return "No"
    if "out-of-network" in flat or "out of network" in flat:
        return "Yes"
    return None


# Portal values that must be computed rather than read from one breakdown key.
# All three share the (breakdown, raw_portal) signature so `_portal_value` can
# call them uniformly, even where one of the two arguments isn't needed.
_DERIVED = {
    "_cob": _portal_cob,
    "_prev_in_max": _portal_prev_in_max,
    "_in_network": _portal_in_network,
    "_oon_benefits": _portal_oon_benefits,
    "_yearly_max_paid": _portal_yearly_max_paid,
}


def _portal_value(field: dict, bd: dict, portal_raw: dict) -> str | None:
    """Resolve one spec'd field's value on the portal side."""
    src = field.get("portal")
    if src is None:
        return None
    if isinstance(src, tuple) and src and src[0] == "code":
        return _pct_from_procs(bd.get("procs", {}), src[1:])
    if isinstance(src, tuple) and src and src[0] == "codefield":
        return _procfield_from_procs(bd.get("procs", {}), src[1], src[2:])
    if isinstance(src, str) and src in _DERIVED:
        return _DERIVED[src](bd, portal_raw)
    val = bd.get(src) if isinstance(src, str) else None
    return None if _blank(val) else str(val)


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

STATUS_MATCH = "match"
STATUS_MISMATCH = "mismatch"
STATUS_NOT_IN_PORTAL = "not_in_portal"
STATUS_MISSING_IN_SABRINA = "missing_in_sabrina"
STATUS_NOT_STATED = "not_stated"
STATUS_NOT_COMPARABLE = "not_comparable"


def compare_sabrina_to_portal(sabrina_parsed: dict, portal_raw: dict) -> dict:
    """
    Audit a parsed Sabrina PDF against the insurance portal export.

    Returns a UI-ready payload: per-section rows, a mismatches-only list, and
    counts. Every row carries both raw values so a reviewer can see exactly
    what each system says.
    """
    sab_fields = sabrina_parsed.get("fields", {})
    bd = _portal_breakdown(portal_raw)

    sections: dict[str, list] = {}
    rows: list[dict] = []

    for field in _SPEC:
        key = field["key"]
        sab_raw = sab_fields.get(key)
        por_raw = _portal_value(field, bd, portal_raw)

        sab_blank = _blank(sab_raw)
        por_blank = _blank(por_raw)
        note = ""

        if sab_blank and por_blank:
            status = STATUS_NOT_STATED
        elif por_blank:
            # The portal never stated it → cannot be called a mismatch.
            status = STATUS_NOT_IN_PORTAL
            note = ("no equivalent field in the portal export"
                    if field.get("portal") is None
                    else "portal did not state this value")
        elif sab_blank and _blank_means_no_limit(field["kind"], por_raw):
            status = STATUS_MATCH
            note = "blank on the sheet and no limit on the portal — same thing"
        elif sab_blank:
            status = STATUS_MISSING_IN_SABRINA
            note = "blank on the Sabrina sheet"
        elif field.get("uncomparable"):
            status = STATUS_NOT_COMPARABLE
            note = field["uncomparable"]
        else:
            equal, cmp_note = _compare(field["kind"], sab_raw, por_raw)
            note = cmp_note
            if equal is None:
                status = STATUS_NOT_COMPARABLE
                note = note or "values are not in a comparable form"
            else:
                status = STATUS_MATCH if equal else STATUS_MISMATCH

        row = {
            "key": key,
            "label": field["label"],
            "section": field["section"],
            "kind": field["kind"],
            "sabrina": None if sab_blank else str(sab_raw).strip(),
            "portal": None if por_blank else str(por_raw).strip(),
            "status": status,
            "critical": key in _CRITICAL_KEYS,
            "note": note,
        }
        rows.append(row)
        sections.setdefault(field["section"], []).append(row)

    def _count(*statuses) -> int:
        return sum(1 for r in rows if r["status"] in statuses)

    mismatches = [r for r in rows if r["status"] == STATUS_MISMATCH]
    # Critical disagreements first, then sheet order.
    mismatches.sort(key=lambda r: (not r["critical"], rows.index(r)))

    matched = _count(STATUS_MATCH)
    compared = matched + len(mismatches)

    return {
        "source": "sabrina",
        "patient": {
            "name": sab_fields.get("patient_name"),
            "dob": sab_fields.get("patient_dob"),
            "member_id": sab_fields.get("member_id"),
            "insurance": sab_fields.get("ins_name"),
        },
        "portal_insurer": bd.get("source_insurer") or (portal_raw or {}).get("summary", {}).get("insurer") or "",
        "summary": {
            "total_fields": len(rows),
            "compared": compared,
            "matches": matched,
            "mismatches": len(mismatches),
            "critical_mismatches": sum(1 for r in mismatches if r["critical"]),
            "not_in_portal": _count(STATUS_NOT_IN_PORTAL),
            "missing_in_sabrina": _count(STATUS_MISSING_IN_SABRINA),
            "not_stated": _count(STATUS_NOT_STATED, STATUS_NOT_COMPARABLE),
            "match_rate": round(matched / compared * 100, 1) if compared else 0.0,
        },
        "mismatches": mismatches,
        "sections": [{"section": name, "rows": rws} for name, rws in sections.items()],
        "diagnostics": {
            "labels_not_found": sabrina_parsed.get("labels_not_found", []),
            "marker_count": sabrina_parsed.get("marker_count"),
            "pdf_line_count": sabrina_parsed.get("line_count"),
        },
    }


async def audit_sabrina_pdf(pdf_bytes: bytes, portal_raw: dict) -> dict:
    """
    Full path: Sabrina PDF bytes + portal export → comparison payload.

    Raises ValueError (→ HTTP 422) when the upload is not a Sabrina breakdown,
    so the caller can tell the user they picked the wrong file.
    """
    parsed = parse_sabrina_pdf(pdf_bytes)

    if parsed["marker_count"] < _MIN_MARKERS:
        raise ValueError(
            "This PDF doesn't look like a Sabrina patient breakdown "
            f"(matched only {parsed['marker_count']} of the expected field "
            "labels). Upload the breakdown PDF downloaded from Sabrina, or use "
            "the Denticon JSON export instead."
        )

    if not portal_raw:
        raise ValueError("Upload the insurance portal export (JSON or PDF) to compare against.")

    return compare_sabrina_to_portal(parsed, portal_raw)


# ══════════════════════════════════════════════════════════════════════════════
#  CLI — tune the parser against a real Sabrina PDF
#
#    python sabrina_compare.py breakdown.pdf                 → what was parsed
#    python sabrina_compare.py breakdown.pdf portal.json     → full comparison
#    python sabrina_compare.py breakdown.pdf --text          → raw PDF text
# ══════════════════════════════════════════════════════════════════════════════

def _cli() -> int:
    # Windows consoles default to cp1252, which cannot encode the box-drawing
    # characters below; force UTF-8 so the dump never dies on its own output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if not args:
        print(__doc__)
        print("usage: python sabrina_compare.py <sabrina.pdf> [portal.json] [--text]")
        return 2

    with open(args[0], "rb") as fh:
        pdf_bytes = fh.read()

    if "--text" in flags:
        print(_extract_text(pdf_bytes))
        return 0

    parsed = parse_sabrina_pdf(pdf_bytes)

    print(f"\nSabrina markers matched : {parsed['marker_count']}/{len(_MARKERS)}"
          f"  → detected as Sabrina: {parsed['marker_count'] >= _MIN_MARKERS}")
    print(f"Lines of text           : {parsed['line_count']}\n")

    found = {k: v for k, v in parsed["fields"].items() if not _blank(v)}
    print(f"── PARSED {len(found)}/{len(_SPEC)} FIELDS ─────────────────────────")
    for field in _SPEC:
        val = parsed["fields"].get(field["key"])
        mark = "  " if not _blank(val) else "??"
        print(f"{mark} {field['label'][:44]:<46} {'' if _blank(val) else val}")

    if parsed["labels_not_found"]:
        print(f"\n── LABELS NOT ON THE SHEET ({len(parsed['labels_not_found'])}) ──")
        print("   " + "\n   ".join(parsed["labels_not_found"]))

    if len(args) > 1:
        with open(args[1], "r", encoding="utf-8") as fh:
            portal_raw = json.load(fh)
        result = compare_sabrina_to_portal(parsed, portal_raw)
        s = result["summary"]
        print(f"\n── COMPARISON ────────────────────────────────────────────")
        print(f"   compared {s['compared']}   matches {s['matches']}   "
              f"MISMATCHES {s['mismatches']} ({s['critical_mismatches']} critical)   "
              f"portal-silent {s['not_in_portal']}")
        for r in result["mismatches"]:
            flag = "!!" if r["critical"] else "  "
            print(f"{flag} {r['label'][:38]:<40} sabrina={r['sabrina']!r:<22} portal={r['portal']!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
