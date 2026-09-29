"""
The Smile Partners breakdown sheet, as a field list.

This is the shape of the sheet itself — every field it carries, in the order it
carries them, and which of the four columns each CDT row has. A different
vendor's sheet would be a different file like this one; everything else in this
package works off whatever the spec declares.
"""

from __future__ import annotations


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
    {"key": "in_network",   "label": "In Network",   "kind": "network", "section": "Insurance", "portal": "_in_network",
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
    {"key": "cob",            "label": "Coordination Of Benefits",   "kind": "cob",   "section": "Plan Provisions", "portal": "_cob",
     "aliases": ["Coordination of Benefits", "COB"]},

    {"key": "pct_prev",  "label": "D0120 Preventative", "kind": "pct", "section": "Plan Provisions", "portal": "pct_prev",
     "aliases": ["Preventative %", "Preventive"]},
    {"key": "pct_basic", "label": "D2160 Basic",        "kind": "pct", "section": "Plan Provisions", "portal": "pct_basic",
     "aliases": ["Basic %", "Basic"]},
    {"key": "pct_major", "label": "D2740 Major",        "kind": "pct", "section": "Plan Provisions", "portal": "pct_major",
     "aliases": ["Major %", "Major"]},

    # ── Orthodontics ─────────────────────────────────────────────────────────
    {"key": "ortho_max",      "label": "Ortho Maximum$",                       "kind": "money", "section": "Orthodontics", "portal": "_ortho_max",
     "aliases": ["Ortho Max", "Orthodontic Maximum", "Ortho Lifetime Maximum"]},
    {"key": "ortho_max_paid", "label": "Orthodontics Used Amount $",            "kind": "money", "section": "Orthodontics", "portal": "_ortho_used",
     "aliases": ["Ortho Used", "Orthodontics Used Amount"]},
    {"key": "ortho_ded",      "label": "Orthodontics Deductible Amount$",       "kind": "money", "section": "Orthodontics", "portal": "_ortho_ded",
     "aliases": ["Ortho Deductible", "Orthodontics Deductible Amount"]},
    {"key": "ortho_ded_paid", "label": "Orthodontics Deductible Met Amount $",  "kind": "money", "section": "Orthodontics", "portal": "_ortho_ded_met",
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
    # Cigna states one fluoride age limit, on its "Topical Fluoride" (D1208)
    # row, and it governs the varnish too — so D1208 stands in when D1206
    # carries no age of its own.
    {"key": "d1206", "label": "D1206 Fluoride Varnish", "kind": "pct", "section": "Coverage by CDT Code", "portal": ("code", "D1206", "D1208")},
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


_BENEFIT_ASPECTS = (
    ("freq", "Frequency", "frequency", "frequency_limit"),
    ("age",  "Age Limit", "agelimit",  "age_limit"),
    ("hist", "History",   "history",   "late_date_of_service"),
)


# All four columns of a code belong to ONE row in the UI, so the generated
# rows live in the same section as their percentage and carry the grouping tags
# the renderer needs.
_ASPECT_SECTION = "Coverage by CDT Code"


# Which codes actually carry each column, per the MetLife observations.
#
# Age Limit and History are only meaningful for a handful of procedures, and
# Frequency is not expected for a few. Generating rows for the rest produced ~70
# "blank on the sheet" flags that were nothing of the kind — the sheet is right
# to leave those cells empty. Note D4341 is in the history list but NOT the age
# list: Sabrina puts the quadrant count in its Age Limit column, not an age.
_AGE_LIMIT_CODES = {"D1206", "D1208", "D1351", "D1510", "D8080"}


_HISTORY_CODES = {
    "D0120", "D0140", "D0150", "D0210", "D0274", "D0330", "D1110",
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
            # The orthodontic age limit is a plan-level statement, not a
            # per-procedure one, so that row reads it from the plan instead.
            portal_source = ("codefield", portal_field) + codes
            if suffix == "age" and primary == "D8080":
                portal_source = "_ortho_age"
            out.append({
                "key":     f'{field["key"]}__{suffix}',
                "label":   f'{field["label"]} · {title}',
                "kind":    kind,
                "section": _ASPECT_SECTION,
                "portal":  portal_source,
                "derived": True,
                "row_key": field["key"],
                "aspect":  suffix,
                "group":   field["key"],
                "group_label": field["label"],
            })
    return out


# The fields actually printed as labels on the sheet, excluding the generated
# Frequency / Age Limit / History rows. This is what "fields read" means to a
# user looking at the upload box — counting the generated rows there makes a
# perfectly good parse look half-broken, since most CDT rows legitimately have
# no age limit or service history.
_SPEC += _build_aspect_spec()


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
