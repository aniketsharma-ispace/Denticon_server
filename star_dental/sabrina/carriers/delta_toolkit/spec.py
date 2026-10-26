"""
The Star breakdown sheet, as a field list.

The list is the Star checklist (112 rows): 72 unique CDT codes, 8 yes/no
confirmations, 2 age limits and 29 plan-level rows, plus the patient/subscriber
identity block that the Toolkit identity gate reads. Nothing else in this
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
    (1, 'D0120', 'd0120', 'D0120 Periodic Exam', ()),
    (2, 'D1110', 'd1110', 'D1110 Adult Prophy', ()),
    (3, 'D0220', 'd0220', 'D0220 Pas', ()),
    (4, 'D0230', 'd0230', 'D0230', ()),
    (5, 'D0240', 'd0240', 'D0240', ()),
    (6, 'D0150', 'd0150', 'D0150 Diagnostic Exam', ('D0150 Diagnostic Exam Comp',)),
    (8, 'D0140', 'd0140', 'D0140 Limited Exam', ()),
    (11, 'D1120', 'd1120', 'D1120', ()),
    (12, 'D0210', 'd0210', 'D0210 FMX', ()),
    (13, 'D0330', 'd0330', 'D0330 Pano', ()),
    (15, 'D0274', 'd0274', 'D0274 Bitewings', ('Diagnostic: XraysBitewings',)),
    (16, 'D1351', 'd1351', 'D1351 Sealants', ()),
    (17, 'D1206', 'd1206', 'D1206 Fluoride Varnish', ()),
    (18, 'D1208', 'd1208', 'D1208 Fluoride', ()),
    (19, 'D0367', 'd0367', 'D0367', ()),
    (20, 'D1516', 'd1516', 'D1516 Space Maintainer', ()),
    (21, 'D2331', 'd2331', 'D2331', ()),
    (22, 'D2140', 'd2140', 'D2140', ()),
    (23, 'D2391', 'd2391', 'D2391 Composite Fillings', ()),
    (25, 'D2610', 'd2610', 'D2610', ()),
    (26, 'D2642', 'd2642', 'D2642', ()),
    (27, 'D4381', 'd4381', 'D4381 Arestin', ()),
    (28, 'D4355', 'd4355', 'D4355 Full Mouth Debridement', ()),
    (29, 'D4346', 'd4346', 'D4346 Gingival Inflammation', ()),
    (30, 'D4341', 'd4341', 'D4341 Scaling Root Planing', ()),
    (32, 'D4910', 'd4910', 'D4910 Perio Maintenance', ('Perio Maintenance D4910 %',)),
    (34, 'D2740', 'd2740', 'D2740 Crowns', ()),
    (36, 'D2750', 'd2750', 'D2750 Restorative Crowns', ()),
    (37, 'D2950', 'd2950', 'D2950 Core Buildups', ()),
    (38, 'D5110', 'd5110', 'D5110 Dentures', ()),
    (39, 'D5212', 'd5212', 'D5212 Partial Dentures', ()),
    (40, 'D5511', 'd5511', 'D5511', ()),
    (41, 'D5650', 'd5650', 'D5650', ()),
    (42, 'D5810', 'd5810', 'D5810', ()),
    (43, 'D5821', 'd5821', 'D5821', ()),
    (44, 'D5912', 'd5912', 'D5912 facial moulage (complete)', ()),
    (45, 'D6010', 'd6010', 'D6010 Implants', ()),
    # Sabrina's own table drops the leading D for these implant rows.
    (46, 'D6104', 'd6104', 'D6104', ('Implant Crown 6104',)),
    (47, 'D6190', 'd6190', 'D6190', ('Implant 6190',)),
    (48, 'D6056', 'd6056', 'D6056', ()),
    (49, 'D6057', 'd6057', 'D6057', ()),
    (50, 'D6058', 'd6058', 'D6058', ()),
    (51, 'D6240', 'd6240', 'D6240', ()),
    (52, 'D6245', 'd6245', 'D6245', ()),
    (53, 'D9110', 'd9110', 'D9110 Palliative Exam', ()),
    (54, 'D9222', 'd9222', 'D9222', ()),
    (55, 'D9230', 'd9230', 'D9230 Nitrous', ()),
    (56, 'D9239', 'd9239', 'D9239', ()),
    (57, 'D9243', 'd9243', 'D9243 Anesthesia', ()),
    (58, 'D9310', 'd9310', 'D9310', ()),
    (59, 'D9612', 'd9612', 'D9612', ()),
    (60, 'D9630', 'd9630', 'D9630 Adjunct', ()),
    (61, 'D9944', 'd9944', 'D9944 Occlusal Guard', (
        'Adjunct Nightguards D9944', 'Nightguards D9944',
        'Night Guards D9944', 'Night Guard D9944',
    )),
    (63, 'D9946', 'd9946', 'D9946', ()),
    (64, 'D9947', 'd9947', 'D9947', ()),
    (65, 'D3221', 'd3221', 'D3221', ()),
    (66, 'D3310', 'd3310', 'D3310 Endodontics', ()),
    (67, 'D3330', 'd3330', 'D3330', ()),
    (68, 'D3346', 'd3346', 'D3346 retreatment of previous root canal', ()),
    (69, 'D3348', 'd3348', 'D3348 retreatment of previous root canal', ()),
    (70, 'D4260', 'd4260', 'D4260 Osseous Surgery', ()),
    (71, 'D4921', 'd4921', 'D4921 gingival irrigation - per quadrant', ()),
    (72, 'D7140', 'd7140', 'D7140 Simple Ext', ()),
    (73, 'D7210', 'd7210', 'D7210 Surgical Ext', ()),
    (74, 'D7230', 'd7230', 'D7230', ()),
    (75, 'D7240', 'd7240', 'D7240', ()),
    (76, 'D7310', 'd7310', 'D7310', ()),
    (77, 'D7953', 'd7953', 'D7953', ()),
    (78, 'D8080', 'ortho_coverage', 'Ortho Coverage', ('Orthodontic Coverage', 'Ortho %')),
    (79, 'D8090', 'd8090', 'D8090', ()),
    (80, 'D8220', 'd8220', 'D8220 fixed appliance therapy', ()),
    (81, 'D8680', 'd8680', 'D8680', ()),
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
    {"key": "preauth_over", "label": "PreAuthorize Over $", "kind": "money", "section": "Plan Provisions", "portal": None,
     "aliases": ["Pre-Authorize over", "Pre-Authorize Over $", "PreAuthorize Over"]},
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

    {"key": "missing_tooth",  "label": "Does Missing Tooth Clause Apply?",     "kind": "yesno", "section": "Clauses", "portal": "missing_tooth",
     "aliases": ["Missing Tooth Clause", "Does Missing Tooth Clause Apply"]},
    {"key": "posterior_composite_downgrade",
     "label": "Are Posterior Composites Downgraded To Amalgam?", "kind": "yesno",
     "section": "Clauses", "portal": "posterior_composite_downgrade",
     "aliases": ["Posterior composite downgrade?",
                 "Are Posterior Composites Downgraded to Amalgam",
                 "Posterior Composites Downgraded To Amalgam"]},
    {"key": "porcelain_posterior_downgrade",
     "label": "Are Posterior Crowns Downgraded?", "kind": "yesno",
     "section": "Clauses", "portal": "porcelain_posterior_downgrade",
     "aliases": ["Crown Downgrade based on material?",
                 "Are Posterior Crowns Downgraded",
                 "Are Porcelain Crowns Downgraded"]},

    {"key": "d0150_fee_per_provider", "label": "D0150 freq per provider?", "kind": "frequency",
     "section": "Confirmations", "portal": "_toolkit_d0150_per_provider",
     "aliases": ["D0150 fee per provider?"]},
    {"key": "d0120_d0140_share_freq", "label": "D0120 and D0140 share freq?", "kind": "yesno",
     "section": "Confirmations", "portal": "_share_frequency", "shares": ("D0120", "D0140"),
     "toolkit_only": True},
    {"key": "fmx_pano_share_freq", "label": "FMX and Pano share freq?", "kind": "yesno",
     "section": "Confirmations", "portal": "_share_frequency", "shares": ("D0210", "D0330"),
     "toolkit_only": True},
    {"key": "srp_quads_per_day", "label": "SRP Quads per day?", "kind": "text",
     "section": "Confirmations", "portal": "_toolkit_srp_quads_per_day", "toolkit_only": True},
    {"key": "prophy_perio_share_freq", "label": "Prophy and Perio maintenance share freq?", "kind": "yesno",
     "section": "Confirmations", "portal": "_share_frequency", "shares": ("D1110", "D4910"),
     "toolkit_only": True},
    {"key": "d9944_bruxism_only", "label": "D9944 Bruxism only?", "kind": "yesno",
     "section": "Confirmations", "portal": None},

    {"key": "subscriber_age_limit", "label": "Subscriber Age Limit", "kind": "agelimit",
     "section": "Age Limits", "portal": "_toolkit_subscriber_age_limit", "toolkit_only": True,
     "aliases": ["Subscriber Age Limit?"]},
    {"key": "dependent_age_limit", "label": "Dependent Age Limit", "kind": "agelimit",
     "section": "Age Limits", "portal": "_toolkit_dependent_age_limit",
     "aliases": ["Dependent Age Limit?"]},
]

for _sl, _code, _key, _label, _aliases in _CDT_ROWS:
    _entry = {"key": _key, "label": _label, "kind": "pct", "section": _CDT,
              "portal": ("code", _code), "sl_no": _sl}
    if _aliases:
        _entry["aliases"] = list(_aliases)
    _SPEC.append(_entry)


_BENEFIT_ASPECTS = (
    ("freq", "Frequency", "frequency", "frequency_limit"),
    ("age",  "Age Limit", "agelimit",  "age_limit"),
    ("hist", "History",   "history",   "late_date_of_service"),
)

_ASPECT_SECTION = _CDT

_AGE_LIMIT_CODES = {"D1206", "D1208", "D1351"}

_HISTORY_CODES = {
    "D0120", "D0140", "D0150", "D0210", "D0274", "D0330", "D1110", "D1206",
    "D1208", "D1351", "D4341", "D4910",
}

_NO_FREQUENCY_CODES = {
    "D3221", "D3310", "D3330", "D3346", "D3348", "D4260", "D4921", "D7140",
    "D7210", "D7230", "D7240", "D7310", "D7953", "D8080", "D8090", "D8220",
    "D8680",
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
            out.append({
                "key":     f'{field["key"]}__{suffix}',
                "label":   f'{field["label"]} · {title}',
                "kind":    kind,
                "section": _ASPECT_SECTION,
                "portal":  ("codefield", portal_field) + codes,
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


CHECKLIST_CODES = tuple(code for _sl, code, _key, _label, _aliases in _CDT_ROWS)


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
