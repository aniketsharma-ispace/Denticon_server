"""
The Park Dental breakdown sheet, as a field list.

The list is the Park Dental checklist ("Park Dental" tab of the codes
workbook): 47 CDT rows (D7961_D7962 is one row naming two codes), 5 yes/no
confirmations, the orthodontic coverage, age limit and payment timing, and 28
plan-level rows, plus the patient/subscriber identity block that the Toolkit
identity gate reads. Nothing else in this
package knows what the sheet contains; it works off whatever the spec declares.

Each entry carries:
  key      internal id (unique; the UI keys rows on it)
  label    the label as printed on the sheet
  kind     how to normalize/compare: money, pct, yesno, date, month, name, id,
           text, address, carrier, network, cob, agelimit
  section  UI grouping
  portal   where the portal value comes from: a str is a key in the breakdown
           dict or a reader registered in portal._DERIVED; ("code", "D0120") is
           the coverage percentage of that exact CDT code; None means the
           portal export has no equivalent and the row can never be a mismatch
  after    disambiguates a label that repeats on the sheet
  aliases  other spellings of the same label
  shares   for the share-frequency confirmations, the two CDT codes compared

Every CDT row also yields Frequency, Age Limit and History rows, generated for
the codes the checklist ticks for that column. A value the Toolkit does not state
is never a mismatch.
"""

from __future__ import annotations


_CDT = "Coverage by CDT Code"

_CDT_ROWS = (
    (30, 'D0120', 'd0120', 'D0120 Periodic Exam', ('Periodic Exam D0120',)),
    (31, 'D0140', 'd0140', 'D0140 Limited Exam', ()),
    (32, 'D0150', 'd0150', 'D0150 Diagnostic Exam', ('D0150 Diagnostic Exam Comp', 'D0150 Comprehensive Exam')),
    (33, 'D0220', 'd0220', 'D0220 Pas', ()),
    (34, 'D0210', 'd0210', 'D0210 FMX', ('D0210 Full-Mouth Xray',)),
    (35, 'D0330', 'd0330', 'D0330 Pano', ('D0330 Panoramic Xray',)),
    (36, 'D0274', 'd0274', 'D0274 Bitewings', ('Diagnostic: XraysBitewings', 'D0274 Xray_Bitewings')),
    (37, 'D0364', 'd0364', 'D0364', ()),
    (38, 'D1110', 'd1110', 'D1110 Adult Prophy', ('D1110 Prophy',)),
    (39, 'D1208', 'd1208', 'D1208 Fluoride', ()),
    (40, 'D1351', 'd1351', 'D1351 Sealants', ()),
    (41, 'D1510', 'd1510', 'D1510 Space Maintainer', ()),
    (42, 'D2331', 'd2331', 'D2331', ()),
    (43, 'D2391', 'd2391', 'D2391 Composite Fillings', ()),
    (45, 'D2740', 'd2740', 'D2740 Crowns', ()),
    (46, 'D5110', 'd5110', 'D5110 Dentures', ()),
    (47, 'D2950', 'd2950', 'D2950 Core Buildups', ('D2950 Core Build Up',)),
    (48, 'D3310', 'd3310', 'D3310 Endodontics', ()),
    (49, 'D3330', 'd3330', 'D3330', ()),
    (50, 'D4260', 'd4260', 'D4260 Osseous Surgery', ('D4260 Perio',)),
    (51, 'D4266', 'd4266', 'D4266', ()),
    (52, 'D4341', 'd4341', 'D4341 Scaling Root Planing', ()),
    (53, 'D4346', 'd4346', 'D4346 Gingival Inflammation', ('D4346 Gingival Therapy',)),
    (55, 'D4355', 'd4355', 'D4355 Full Mouth Debridement', ('D4355 Debridement',)),
    (57, 'D4381', 'd4381', 'D4381 Arestin', ()),
    (58, 'D4910', 'd4910', 'D4910 Perio Maintenance', ('Perio Maintenance D4910 %',)),
    (60, 'D5510', 'd5510', 'D5510', ()),
    (61, 'D5911', 'd5911', 'D5911', ()),
    (62, 'D6010', 'd6010', 'D6010 Implants', ()),
    (63, 'D6058', 'd6058', 'D6058', ()),
    (64, 'D6190', 'd6190', 'D6190', ('Implant 6190',)),
    (65, 'D7140', 'd7140', 'D7140 Simple Ext', ('D7140_Ora_Surgery',)),
    (66, 'D7220', 'd7220', 'D7220', ()),
    (67, 'D7230', 'd7230', 'D7230', ()),
    (68, 'D7240', 'd7240', 'D7240', ()),
    (69, 'D7280', 'd7280', 'D7280', ()),
    (70, 'D7283', 'd7283', 'D7283', ()),
    (71, 'D7310', 'd7310', 'D7310', ()),
    (72, 'D7950', 'd7950', 'D7950', ()),
    (73, 'D7952', 'd7952', 'D7952', ()),
    (74, 'D7953', 'd7953', 'D7953', ()),
    (75, ('D7961', 'D7962'), 'd7961_d7962', 'D7961_D7962', ('D7961', 'D7962')),
    (76, 'D7971', 'd7971', 'D7971', ()),
    (77, 'D9110', 'd9110', 'D9110 Palliative Exam', ('D9110 Adjunct Palliative Exam',)),
    (79, 'D9222', 'd9222', 'D9222', ()),
    (80, 'D9944', 'd9944', 'D9944 Occlusal Guard', ('Adjunct Nightguards D9944', 'Nightguards D9944', 'Night Guards D9944', 'Night Guard D9944')),
    (81, 'D8080', 'ortho_coverage', 'Ortho Coverage', ('Orthodontic Coverage', 'Ortho %')),
)

_SPEC: list[dict] = [
    {"key": "patient_name",    "label": "Patient Name",    "kind": "name", "section": "Patient / Subscriber", "portal": "patient_name"},
    {"key": "patient_dob",     "label": "Date of Birth",   "kind": "date", "section": "Patient / Subscriber", "portal": "patient_dob",
     "after": "Patient Name"},
    {"key": "member_id",       "label": "Member ID#",      "kind": "id",   "section": "Patient / Subscriber", "portal": "member_id",
     "aliases": ["Member ID", "Member Id #", "Subscriber ID", "Member/Subscriber ID"]},
    {"key": "subscriber_name", "label": "Subscriber Name", "kind": "name", "section": "Patient / Subscriber", "portal": "subscriber_name"},
    {"key": "subscriber_dob",  "label": "Date of Birth",   "kind": "date", "section": "Patient / Subscriber", "portal": "subscriber_dob",
     "after": "Subscriber Name"},
    {"key": "eligibility", "label": "Eligibility", "kind": "yesno",
     "section": "Patient / Subscriber", "portal": "_toolkit_eligibility",
     "portal_only": True, "toolkit_only": True},
    {"key": "relationship", "label": "Relationship", "kind": "text",
     "section": "Patient / Subscriber", "portal": "_toolkit_relationship",
     "portal_only": True, "toolkit_only": True},

    {"key": "ins_name",     "label": "Insurance Name",    "kind": "carrier", "section": "Insurance", "portal": "ins_name",
     "aliases": ["Insurance Carrier", "Carrier Name"]},
    {"key": "group_name",   "label": "Group Name",        "kind": "text",    "section": "Insurance", "portal": "group_name",
     "aliases": ["Employer Group", "Employer Name"]},
    {"key": "group_number", "label": "Group Number",      "kind": "id",      "section": "Insurance", "portal": "group_number",
     "aliases": ["Group #", "Group No", "Group Num"]},
    {"key": "fee_schedule", "label": "Fee Schedule",      "kind": "text",    "section": "Insurance", "portal": None},
    {"key": "ins_address",  "label": "Insurance Address",  "kind": "address", "section": "Insurance", "portal": "ins_address",
     "aliases": ["Carrier Address", "Claims Address"]},
    {"key": "ins_phone",    "label": "Insurance Phone",    "kind": "id",      "section": "Insurance", "portal": "_toolkit_insurance_phone"},
    {"key": "payor_id",     "label": "Payor ID",           "kind": "payer_id", "section": "Insurance", "portal": "payor_id",
     "aliases": ["Payer ID", "Payor Id", "Payer Id"]},
    {"key": "in_network",   "label": "In Network",   "kind": "network", "section": "Insurance", "portal": "_in_network",
     "aliases": ["In-Network", "In Network?", "Participating"]},
    {"key": "eff_date",        "label": "Patient Eff Date",            "kind": "date",  "section": "Insurance", "portal": "eff_date",
     "aliases": ["Patient Effective Date", "Eff Date", "Effective Date"]},
    {"key": "term_date",       "label": "Eligibility Term Date",       "kind": "date",  "section": "Insurance", "portal": None,
     "aliases": ["Patient Term Date"]},
    {"key": "oon_benefits", "label": "OON Benefits", "kind": "yesno", "section": "Insurance", "portal": "_oon_benefits",
     "aliases": ["OON Benefit", "Out of Network Benefits", "Out-of-Network Benefits"]},
    {"key": "plan_year_start", "label": "Starting Month of Plan Year",  "kind": "month", "section": "Insurance", "portal": "plan_year_start",
     "aliases": ["Plan Year Start", "Benefit Year Start"]},

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

    {"key": "waiting_period", "label": "Is there a Waiting Period",  "kind": "yesno", "section": "Plan Provisions", "portal": "waiting_period",
     "aliases": ["Waiting Period", "Is there a Waiting Period?"]},
    {"key": "major_payment_timing",
     "label": "Are Major Services Paid on Prep or Seat date?", "kind": "text",
     "section": "Plan Provisions", "portal": "_toolkit_major_payment_timing",
     "portal_only": True, "toolkit_only": True},
    {"key": "cob",            "label": "Coordination Of Benefits",   "kind": "cob",   "section": "Plan Provisions", "portal": "_cob",
     "aliases": ["Is Coordination of Benefits Nonduplication", "Coordination of Benefits", "COB"]},

    {"key": "ortho_max",      "label": "Ortho Maximum$",                       "kind": "money", "section": "Orthodontics", "portal": "_ortho_max",
     "aliases": ["Ortho Max", "Orthodontic Maximum", "Ortho Lifetime Maximum"]},
    {"key": "ortho_max_paid", "label": "Orthodontics Used Amount $",            "kind": "money", "section": "Orthodontics", "portal": "_ortho_used",
     "aliases": ["Ortho Used", "Orthodontics Used Amount"]},
    {"key": "ortho_ded",      "label": "Orthodontics Deductible Amount$",       "kind": "money", "section": "Orthodontics", "portal": "_ortho_ded",
     "aliases": ["Ortho Deductible", "Orthodontics Deductible Amount"]},
    {"key": "ortho_ded_paid", "label": "Orthodontics Deductible Met Amount $",  "kind": "money", "section": "Orthodontics", "portal": "_ortho_ded_met",
     "aliases": ["Ortho Deductible Met", "Orthodontics Deductible Met Amount"]},
    # How the plan pays orthodontics ("Yearly"). Shown for review only.
    {"key": "ortho_payment_timing", "label": "Ortho Payment Timing", "kind": "text",
     "section": "Orthodontics", "portal": None},

    {"key": "missing_tooth",  "label": "Does Missing Tooth Clause Apply?",     "kind": "yesno", "section": "Clauses", "portal": "missing_tooth",
     "aliases": ["Missing Tooth Clause", "Does Missing Tooth Clause Apply"]},
    {"key": "posterior_composite_downgrade",
     "label": "Are Posterior Composites Downgraded To Amalgam?", "kind": "yesno",
     "section": "Clauses", "portal": "posterior_composite_downgrade",
     "aliases": ["Posterior composite downgrade?",
                 "Are Posterior Composites Downgraded to Amalgam",
                 "Posterior Composites Downgraded To Amalgam",
                 "D2391 Composite Fillings downgraded to Amalgam"]},

    {"key": "prophy_perio_share_freq", "label": "Prophy and Perio maintenance share freq?", "kind": "yesno",
     "section": "Confirmations", "portal": "_share_frequency", "shares": ("D1110", "D4910"),
     "toolkit_only": True,
     "aliases": ["D4910 Shares frequency with Prophy?"]},
    {"key": "d4346_share_freq", "label": "D4346 Gingival Therapy - Share Freq?", "kind": "yesno",
     "section": "Confirmations", "portal": None},
    {"key": "d4355_share_freq", "label": "D4355 Debridement Share Freq", "kind": "yesno",
     "section": "Confirmations", "portal": None},
    {"key": "d9110_share_freq", "label": "D9110 share freq with / other exams?", "kind": "yesno",
     "section": "Confirmations", "portal": None},
]

for _sl, _code, _key, _label, _aliases in _CDT_ROWS:
    # A row may name two codes ("D7961_D7962"); the first the portal states wins.
    _codes = (_code,) if isinstance(_code, str) else tuple(_code)
    _entry = {"key": _key, "label": _label, "kind": "pct", "section": _CDT,
              "portal": ("code",) + _codes, "sl_no": _sl}
    if _aliases:
        _entry["aliases"] = list(_aliases)
    _SPEC.append(_entry)


_BENEFIT_ASPECTS = (
    ("freq", "Frequency", "frequency", "frequency_limit"),
    ("age",  "Age Limit", "agelimit",  "age_limit"),
    ("hist", "History",   "history",   "late_date_of_service"),
)

_ASPECT_SECTION = _CDT

_AGE_LIMIT_CODES = {"D1208", "D1351", "D8080"}


_HISTORY_CODES = {
    "D0120", "D0140", "D0150", "D0210", "D0274", "D0330", "D1208", "D4341",
}


_NO_FREQUENCY_CODES = {"D3310", "D3330", "D4260", "D4266", "D5911", "D8080"}


# Codes Park Dental's list ticks for Frequency but not Coverage %. Their row is
# still read off the sheet, but the percentage is never compared: the field is
# marked `no_percentage` below and the audit leaves it out.
_NO_PERCENTAGE_CODES = {
    "D0210", "D4346", "D4381", "D4910", "D5110", "D5510", "D6010", "D6190",
    "D7140", "D7220", "D7230", "D7240", "D7280", "D7283", "D7310", "D7950",
    "D7952", "D7953", "D7961", "D7971", "D9222",
}


def _aspect_applies(aspect: str, code: str) -> bool:
    if aspect == "age":
        return code in _AGE_LIMIT_CODES
    if aspect == "hist":
        return code in _HISTORY_CODES
    return code not in _NO_FREQUENCY_CODES


def _build_aspect_spec() -> list[dict]:
    out = []
    for field in _SPEC:
        if field["section"] != _CDT:
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
                "portal_only": field.get("portal_only", False),
                "toolkit_only": field.get("toolkit_only", False),
                "row_key": field["key"],
                "aspect":  suffix,
                "group":   field["key"],
                "group_label": field["label"],
            })
    return out


_SPEC += _build_aspect_spec()


for _field in _SPEC:
    _src = _field.get("portal")
    if (not _field.get("derived") and isinstance(_src, tuple) and _src and _src[0] == "code"
            and _src[1].upper() in _NO_PERCENTAGE_CODES):
        _field["no_percentage"] = True


CHECKLIST_CODES = tuple(c for _sl, code, _key, _label, _aliases in _CDT_ROWS
                        for c in ((code,) if isinstance(code, str) else code))


CORE_FIELD_KEYS = tuple(f["key"] for f in _SPEC if not f.get("derived") and not f.get("portal_only"))


def core_fields(fields: dict) -> dict:
    """Only the values read from a label of their own."""
    return {k: v for k, v in (fields or {}).items() if k in set(CORE_FIELD_KEYS)}


_CRITICAL_KEYS = {
    "member_id", "group_number", "payor_id", "patient_dob", "subscriber_dob",
    "yearly_max", "yearly_max_paid", "indiv_ded", "indiv_ded_paid",
    "family_ded", "ortho_max", "ortho_max_paid", "in_network", "eff_date",
    "term_date", "d0120", "d2391", "d2740",
}
