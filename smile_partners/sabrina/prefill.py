"""
Smile Partners — prefilling Sabrina's Fill Form from a portal export.

The audit already works out, field by field, what the portal says in the
sheet's own words (`carriers/<carrier>/portal.py`). Prefill asks the same
question and skips the comparison: every value the portal states is sent to
the extension with the Fill Form field it belongs in. Every rule fixed for
the audit therefore applies here too, and the two cannot drift apart.

    audit:    portal value  vs  Sabrina sheet value  → match / mismatch
    prefill:  portal value  →   Sabrina Fill Form field

What this module adds is only the last step:

  * FORM_FIELDS maps a spec key to the Fill Form input's `name`.
  * `_form_value` rewrites a value the way the form expects it (1250.00, not
    "1,250.00"; 11/11/2026, not 11/11/26; NC for Not Covered).
  * Each field is tagged `plan` or `appointment`. An existing plan already
    carries the plan-level fields, so the extension fills only appointment
    fields there (met amounts, max used, history dates).

The network the user picked on the form (IN OR OON) decides which benefits
are read, exactly as the sheet's In Network field does for the audit.

Fields the user decides are never filled: In or Out, fee schedule, payer name
and ID (type-to-search, returned as hints), eligibility, mode of verification
and notes. Demographic values are returned as `checks` for the extension to
compare against the page, never to overwrite it.
"""

from __future__ import annotations

import re
from importlib import import_module

from .carriers import carrier_rules


# ══════════════════════════════════════════════════════════════════════════════
#  SPEC KEY → FILL FORM FIELD
# ══════════════════════════════════════════════════════════════════════════════
#
# Field names as Smile Partners' Fill Form names them (read off the live form,
# 11/2026). The benefits grid is not listed here: its inputs are named
# `<GUID>_<CODE>_<column>`, so they are built from the code (`_grid_target`).
#
# level: "plan" fields come with an existing plan; "appointment" fields change
# every visit and are filled for both existing and new plans.

FORM_FIELDS: dict[str, tuple[str, str]] = {
    # ── Insurance details (plan) ─────────────────────────────────────────────
    "plan_year_start": ("insuranceDetails.planMonth",                       "plan"),
    "group_name":      ("insuranceDetails.groupName",                       "plan"),
    "group_number":    ("insuranceDetails.groupNumber",                     "plan"),
    "ded_prev":        ("insuranceDetails.individualDeductibleAppliesPrev", "plan"),
    "ded_diag":        ("insuranceDetails.individualDeductibleAppliesDiag", "plan"),
    "oon_benefits":    ("insuranceDetails.planHasOonBenefits",              "plan"),
    "cob":             ("insuranceDetails.coordinationOfBenefits",          "plan"),
    "indiv_ded":       ("insuranceDetails.individualDeductible",            "plan"),
    "family_ded":      ("insuranceDetails.familyDeductible",                "plan"),
    "yearly_max":      ("insuranceDetails.yearlyMaxAmount",                 "plan"),
    "pct_prev":        ("insuranceDetails.preventive",                      "plan"),
    "pct_basic":       ("insuranceDetails.basic",                           "plan"),
    "pct_major":       ("insuranceDetails.major",                           "plan"),
    "waiting_period":  ("insuranceDetails.waitingPeriodFlag",               "plan"),

    # ── Benefit info (appointment) ───────────────────────────────────────────
    "eff_date":        ("benefitsInfo.effectiveDate",                       "appointment"),
    "indiv_ded_paid":  ("benefitsInfo.individualMetAmount",                 "appointment"),
    "family_ded_paid": ("benefitsInfo.familyMetAmount",                     "appointment"),
    "yearly_max_paid": ("benefitsInfo.yearlyMaxUsed",                       "appointment"),
    "ortho_max":       ("benefitsInfo.orthoMaximumAmount",                  "appointment"),
    "ortho_max_paid":  ("benefitsInfo.orthoUsedAmount",                     "appointment"),
    "ortho_ded":       ("benefitsInfo.orthoDedAmount",                      "appointment"),
    "ortho_ded_paid":  ("benefitsInfo.orthoDedMetAmount",                   "appointment"),
}

# The yes/no questions inside the benefits grid (`<GUID>_<question>_covered`).
GRID_QUESTIONS: dict[str, str] = {
    "missing_tooth":                 "DoesMissingToothClauseApply?",
    "prev_in_max":                   "PreventativeIncludedinYearlymax?",
    "major_paid_on":                 "AreMajorServicesPaidonPreporSeatdate?",
    # The Toolkit's spec names the same question major_payment_timing.
    "major_payment_timing":          "AreMajorServicesPaidonPreporSeatdate?",
    "posterior_composite_downgrade": "ArePosteriorCompositesDowngradedToAmalgam?",
    "porcelain_posterior_downgrade": "ArePosteriorCrownsDowngraded?",
    "perio_maint_after_srp":         "WhenIsFirstPerioMaintenanceAllowedAfterSRP?",
}

# Spec aspect → grid column. D4341's "age" row is its quad count, which the
# Fill Form keeps in a column of its own.
_GRID_COLUMN = {"pct": "percentage", "freq": "frequency", "age": "ageLimit", "hist": "history"}

# Read for the extension to check against the page, never filled.
_CHECK_KEYS = ("member_id", "patient_name", "patient_dob", "subscriber_name", "subscriber_dob")

# Shown to the user for the type-to-search fields the extension cannot pick.
_HINT_KEYS = {
    "ins_name":    "PMS Payer Name",
    "payor_id":    "INS E-Claim Payer ID",
    "ins_address": "Insurance address",
}

_NETWORKS = {"in": "In", "out": "Out", "oon": "Out"}

NETWORK_NEEDED = "Choose In or Out of network on the Fill Form first."


def _carrier_vocabulary(portal_raw: dict):
    """The carrier folder's own vocabulary module, or None for the sheet's."""
    try:
        _key, rules = carrier_rules(portal_raw)
        return import_module(f"{rules.__name__}.vocabulary")
    except Exception:
        return None


def carrier_prefill(portal_raw: dict):
    """
    The carrier folder's own prefill module (carriers/<carrier>/prefill.py), or
    None when it has none. Each carrier keeps its Fill Form extras there, so
    people working on different carriers never edit the same file:

      form_only(view, values) -> [field, …]   Relation, Plan Type, … (optional)
                                              values["_raw"] is the export as sent.
                                              An item with "question" goes to the
                                              grid questions, one with "code" and
                                              "column" to the grid; the rest are
                                              plain fields.
      FORM_ONLY_SPEC          [spec row, …]   rows read exactly like the audit's
                                              spec rows but filled only, never
                                              audited: Fill Form cells the sheet
                                              doesn't print (optional)
      waiting_periods(view)   -> [row, …]     Basic / Major rows    (optional)
      adjust_grid(grid)       -> grid         carrier-only grid rules (optional)
      scrape_network(raw)     -> "In"/"Out"   the network the scrape was taken
                                              for, when the portal scrapes one
                                              network only (Cigna)   (optional)
      form_frequency(value)   -> str | None   a grid Frequency in the carrier's
                                              own words ("1X60Months" for MetLife's
                                              "1 TIME IN 60 MONTHS"); None falls
                                              back to the shared reading (optional)
    """
    try:
        _key, rules = carrier_rules(portal_raw)
    except Exception:
        return None
    name = f"{rules.__name__}.prefill"
    try:
        return import_module(name)
    except ModuleNotFoundError as e:
        if e.name == name:          # the carrier simply has no prefill file
            return None
        raise


def _hook(module, name):
    fn = getattr(module, name, None) if module else None
    return fn if callable(fn) else None


def scrape_network(portal_raw: dict) -> str | None:
    """
    "In" / "Out" when the scrape was taken for one network only (Cigna), else
    None — the scrape holds both and the user's IN OR OON pick decides.
    """
    reader = _hook(carrier_prefill(portal_raw), "scrape_network")
    if not reader:
        return None
    try:
        found = reader(portal_raw)
    except Exception:
        return None
    return found if found in ("In", "Out") else None


# ══════════════════════════════════════════════════════════════════════════════
#  PORTAL SIDE — the audit's own readers
# ══════════════════════════════════════════════════════════════════════════════

def portal_values(portal_raw: dict, network: str) -> tuple[str, dict, list[dict]]:
    """
    (carrier, {spec key: portal value}, spec) for one network.

    Runs the carrier folder's portal side exactly as the audit does, with
    the network standing in for the sheet's In Network answer. Raises
    ValueError for an export from a portal with no folder, or a bad network.
    """
    net = _NETWORKS.get(str(network or "").strip().lower())
    if not net:
        raise ValueError(NETWORK_NEEDED)

    key, rules = carrier_rules(portal_raw)
    portal = import_module(f"{rules.__name__}.portal")
    spec = import_module(f"{rules.__name__}.spec")._SPEC
    # Fill Form cells the sheet doesn't print: read the same way, never audited.
    extra = getattr(carrier_prefill(portal_raw), "FORM_ONLY_SPEC", None) or []
    spec = list(spec) + [f for f in extra if f["key"] not in {s["key"] for s in spec}]

    # The audit's In Network answer, as the sheet would state it.
    sheet = {"in_network": net}
    for_sheet = getattr(portal, "_portal_for_sheet", None)
    raw = for_sheet(portal_raw, sheet) if for_sheet else portal_raw
    bd = portal._portal_breakdown(raw)
    norm = portal._portal_normalized(raw)
    bd_for_sheet = getattr(portal, "_breakdown_for_sheet", None)
    if bd_for_sheet:
        bd = bd_for_sheet(bd, norm)

    values = {}
    for field in spec:
        try:
            value = portal._portal_value(field, bd, norm, sheet.get(field["key"]))
        except Exception:          # one unreadable field must not sink the rest
            value = None
        if value is not None and str(value).strip() != "":
            values[field["key"]] = str(value).strip()
    # The network-specific view and the export as sent, for the form-only readers below.
    values["_view"] = norm
    values["_raw"] = raw
    return key, values, spec


# ══════════════════════════════════════════════════════════════════════════════
#  FORM-ONLY FIELDS — on the Fill Form but not on the Sabrina sheet
# ══════════════════════════════════════════════════════════════════════════════
#
# The audit never needed these (the sheet doesn't print them), so each carrier
# reads them in its own folder: carriers/<carrier>/prefill.py, form_only().
# A carrier without one simply leaves them to the user.

# ══════════════════════════════════════════════════════════════════════════════
#  WAITING PERIODS — the Period / Months-Years / Applies To rows
# ══════════════════════════════════════════════════════════════════════════════
#
# Only Basic and Major get a waiting period row (business team, 11/2026), each
# read off a representative code; the first code that states one is used.
# Each carrier reads them in carriers/<carrier>/prefill.py, waiting_periods().

_WAITING_CODES = (
    ("Basic", ("D2160", "D2391")),     # amalgam filling, else composite
    ("Major", ("D2740",)),             # crown
)


def _waiting_period(text) -> tuple[str, str] | None:
    """'6 months' → ('6', 'Months'), '1 year' → ('1', 'Years'); None when not stated."""
    m = re.search(r"(\d+)\s*(month|year)", str(text or ""), re.IGNORECASE)
    if not m:
        return None
    return m.group(1), "Months" if m.group(2).lower() == "month" else "Years"


# ══════════════════════════════════════════════════════════════════════════════
#  FORM SIDE — writing a value the way the Fill Form takes it
# ══════════════════════════════════════════════════════════════════════════════

MONEY_CAP = 99999


def _money(value) -> str | None:
    """
    '$1,250.00' → '1250', '$154.37' → '154.37'.

    Sabrina refuses commas and a '.00' on whole amounts (a plan with 50.00 /
    150.00 / 2000.00 would not save), so whole amounts go as plain numbers;
    real cents are kept rather than rounded away.
    """
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value))
    if not m:
        return None
    amount = round(float(m.group(0).replace(",", "")), 2)
    # Portals write "no maximum" as 9999999.99; Sabrina takes 99999 at most
    # (BPO feedback, 11/2026).
    amount = min(amount, MONEY_CAP)
    return str(int(amount)) if amount.is_integer() else f"{amount:.2f}"


def _not_covered(value) -> bool:
    return re.sub(r"[^a-z]", "", str(value).lower()) in ("notcovered", "nc")


def _pct_number(value) -> str | None:
    """'80%' → '80' for the Insurance Details number inputs; Not Covered → '0'."""
    if _not_covered(value):
        return "0"
    m = re.search(r"\d+(?:\.\d+)?", str(value))
    if not m:
        return None
    n = float(m.group(0))
    return str(int(n)) if n.is_integer() else str(n)


def _pct_option(value) -> str | None:
    """'80%' → '80%', '0%' → '0': the grid's Percentage options."""
    n = _pct_number(value)
    if n is None:
        return None
    return "0" if float(n) == 0 else f"{n}%"


def _date(value) -> str | None:
    """'11/11/26' or '2026-11-11' → '11/11/2026'."""
    text = str(value).strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", text)
    if m:
        year = m.group(3)
        if len(year) == 2:
            year = "20" + year
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{year}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(2)}/{m.group(3)}/{m.group(1)}"
    return None


def _history(value) -> str | None:
    """One or more service dates, or NH. A dash means nothing to fill."""
    text = str(value).strip()
    if text.upper() in ("NH", "NO HISTORY"):
        return "NH"
    dates = [_date(d) for d in re.split(r"[,;]\s*", text)]
    dates = [d for d in dates if d]
    return ", ".join(dates) if dates else None


_FREQ_WORDS = {
    "NOT COVERED": "NC",
    "NO FREQUENCY": "No Frequency",
    "FREQUENCY NOT AVAILABLE": "No Frequency",
}


def _frequency(value, vocab=None) -> str | None:
    """
    The portal's frequency as the form's option: '2X1Year', 'NC', 'No Frequency'.

    Aetna's reader already speaks the form's words; Cigna's states its own
    ("Twice Per Calendar Year", "Once Per 36 Consecutive Months"), read here by
    the audit's frequency parser — the carrier's own vocabulary module when
    given (Cigna's knows its quirks, e.g. "Once Per Life time"), else the sheet's.
    """
    text = str(value).strip()
    if not text or text in ("—", "-"):
        return None
    if text.upper() in _FREQ_WORDS:
        return _FREQ_WORDS[text.upper()]
    span = re.fullmatch(r"(\d+)X(\d+)(Year|Month|Day)s?", text, re.IGNORECASE)
    if span:
        # "1 Unit, per 999 Months" is the portal's way of saying once per
        # lifetime (BPO feedback, 11/25: D4355 → 1xLifetime).
        months = int(span.group(2)) * {"year": 12, "month": 1, "day": 1 / 30}[span.group(3).lower()]
        return f"{span.group(1)}XLifetime" if months >= 999 else text
    if vocab is None:
        from .sheet import vocabulary as vocab
    _num_frequency = vocab._num_frequency
    _FREQ_NOT_COVERED, _FREQ_UNLIMITED, _FREQ_PREDETERMINATION = (
        vocab._FREQ_NOT_COVERED, vocab._FREQ_UNLIMITED, vocab._FREQ_PREDETERMINATION)
    try:
        parsed = _num_frequency(text)
    except Exception:
        parsed = None
    if parsed == _FREQ_NOT_COVERED:
        return "NC"
    if parsed == _FREQ_UNLIMITED:
        return "No Frequency"
    if parsed == _FREQ_PREDETERMINATION:
        return "Pre-D"
    if parsed and len(parsed) == 2 and isinstance(parsed[0], int):
        count, span = parsed
        if span == "lifetime":
            return f"{count}XLifetime"
        span = int(span)
        return f"{count}X{span // 12}Year" if span % 12 == 0 else f"{count}X{span}Month"
    return text


def _age_limit(value) -> str | None:
    """An age-limit input: '14'. Cigna states it as 'Exclude after age 18'."""
    text = str(value).strip()
    if re.fullmatch(r"\d+|STR|Pre-D", text):
        return text
    m = re.search(r"(?:exclude[sd]?\s+after|to|thru|through|under|up\s+to)\s+age\s+(\d{1,3})",
                  text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.fullmatch(r"\s*\d{1,3}\s*[-–]\s*(\d{1,3})\s*", text)
    return m.group(1) if m else None


def _yesno(value) -> str | None:
    text = str(value).strip().lower()
    if text in ("yes", "y", "true"):
        return "Yes"
    if text in ("no", "n", "false"):
        return "No"
    return None


# COORDINATION OF BENEFITS is a dropdown: the portal's wording → its option.
# A plain "always the primary plan" / standard rule is Standard (user, 11/26).
_COB_OPTIONS = (
    (r"non[\s-]*dup", "Non-Duplicate"),
    (r"carve[\s-]*out", "Carve-Out Clause"),
    (r"maintenance\s+of\s+benefits|\bMOB\b", "Maintenance of Benefits"),
    (r"up\s*to\s+the\s+allowable|allowable", "Upto the Allowable"),
    (r"traditional", "Traditional"),
    (r"standard|primary", "Standard"),
)


def _cob_option(value) -> str | None:
    text = str(value or "").strip()
    for pattern, option in _COB_OPTIONS:
        if re.search(pattern, text, re.IGNORECASE):
            return option
    return None


def _form_value(spec_key: str, kind: str, aspect: str | None, value, vocab=None) -> str | None:
    """A portal value rewritten for its Fill Form input, or None to leave it empty."""
    if aspect == "hist":
        return _history(value)
    if aspect == "freq":
        return _frequency(value, vocab)
    if aspect == "age":
        return _age_limit(value)
    if aspect == "pct":
        return _pct_option(value)
    if kind == "money":
        return _money(value)
    if kind == "pct":
        return _pct_number(value)
    if kind == "date":
        return _date(value)
    if kind in ("yesno", "network"):
        return _yesno(value)
    if spec_key == "cob":
        return _cob_option(value)
    text = str(value).strip()
    return text or None


def _grid_target(field: dict, by_key: dict) -> tuple[str, str] | None:
    """('D0120', 'frequency') for a benefits-grid field, or None."""
    if field.get("section") != "Coverage by CDT Code":
        return None
    parent = by_key.get(field.get("row_key") or field["key"]) or field
    src = parent.get("portal")
    if not (isinstance(src, tuple) and len(src) > 1 and src[0] == "code"):
        return None
    code = str(src[1]).upper()
    aspect = field.get("aspect") or "pct"
    if aspect == "age" and code == "D4341":
        return code, "quads"
    column = _GRID_COLUMN.get(aspect)
    return (code, column) if column else None


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def build_prefill(portal_raw: dict, network: str) -> dict:
    """
    What the extension fills on Sabrina's Fill Form for this portal export.

    {
      "carrier": "aetna",
      "network": "In",
      "fields": [                       # plain inputs and dropdowns
        {"name": "insuranceDetails.yearlyMaxAmount", "value": "1250.00",
         "level": "plan", "source": "yearly_max"}, …],
      "grid": [                         # one entry per cell of the benefits grid
        {"code": "D0120", "column": "frequency", "value": "2X1Year",
         "level": "plan", "source": "d0120__freq"}, …],
      "questions": [                    # yes/no rows inside the grid
        {"question": "DoesMissingToothClauseApply?", "value": "Yes", …}, …],
      "checks": {"member_id": "W503349657", …},   # compare with the page, don't fill
      "hints":  {"INS E-Claim Payer ID": "60054", …},
    }

    Raises ValueError (→ HTTP 422) for an unsupported portal or no network.
    """
    # A scrape taken for one network (Cigna; Delta Dental and the Toolkit with
    # the network picked before the crawl) brings its own IN OR OON.
    scraped = scrape_network(portal_raw)
    picked = _NETWORKS.get(str(network or "").strip().lower())
    if scraped:
        if picked and picked != scraped:
            words = {"In": "in-network", "Out": "out-of-network"}
            raise ValueError(
                f"This portal scrape was taken for {words[scraped]} benefits only, but IN OR OON "
                f"on the form says {picked}. Change IN OR OON to {scraped}, or scrape the portal "
                f"again with an {words[picked]} option picked.")
        network = scraped
    carrier, values, spec = portal_values(portal_raw, network)
    by_key = {f["key"]: f for f in spec}
    net = _NETWORKS[str(network).strip().lower()]
    vocab = _carrier_vocabulary(portal_raw)
    hooks = carrier_prefill(portal_raw)
    freq_reader = _hook(hooks, "form_frequency")

    fields, grid, questions = [], [], []

    for field in spec:
        key = field["key"]
        if key not in values:
            continue
        raw = values[key]

        if key in FORM_FIELDS:
            name, level = FORM_FIELDS[key]
            value = _form_value(key, field["kind"], None, raw)
            if value is not None:
                fields.append({"name": name, "value": value, "level": level,
                               "source": key, "label": field["label"]})
            continue

        if key in GRID_QUESTIONS:
            value = _yesno(raw) if field["kind"] == "yesno" else str(raw).strip()
            if value:
                questions.append({"question": GRID_QUESTIONS[key], "value": value,
                                  "level": "plan", "source": key, "label": field["label"]})
            continue

        target = _grid_target(field, by_key)
        if target:
            code, column = target
            aspect = "pct" if column == "percentage" else field.get("aspect")
            value = None
            if column == "frequency" and freq_reader:
                try:
                    value = freq_reader(raw)
                except Exception:      # the shared reading below still applies
                    value = None
            if value is None:
                value = _form_value(key, field["kind"], aspect, raw, vocab)
            if value is not None:
                grid.append({"code": code, "column": column, "value": value,
                             # History changes every visit; the rest is the plan's.
                             "level": "appointment" if column == "history" else "plan",
                             "source": key, "label": field["label"]})

    grid += _no_history(spec, by_key, grid)
    grid = _not_covered_ages(spec, by_key, grid)
    fields += _met_flags(values)
    grid_hook = _hook(hooks, "adjust_grid")
    if grid_hook:
        grid = grid_hook(grid)
    reader = _hook(hooks, "form_only")
    if reader:
        try:
            extras = reader(values.get("_view") or {}, values) or []
        except Exception:          # a form-only extra must never sink the fill
            extras = []
        for item in extras:
            if item.get("question"):
                questions.append(item)
            elif item.get("code") and item.get("column"):
                grid.append(item)
            else:
                fields.append(item)

    waiting = []
    wp_reader = _hook(hooks, "waiting_periods")
    if wp_reader:
        try:
            waiting = wp_reader(values.get("_view") or {})
        except Exception:          # never sink the fill
            waiting = []
    if waiting:
        # Rows only make sense under "Is there a waiting period = Yes".
        fields = [f for f in fields if f["name"] != "insuranceDetails.waitingPeriodFlag"]
        fields.append({"name": "insuranceDetails.waitingPeriodFlag", "value": "Yes", "level": "plan",
                       "source": "waiting_periods", "label": "Is there a waiting period"})

    checks = {k: values[k] for k in _CHECK_KEYS if k in values}
    hints = {label: values[k] for k, label in _HINT_KEYS.items() if k in values}
    # "Is there a waiting period" answered (Yes with rows, or No): nothing left.
    wait_flag = next((f["value"] for f in fields if f["name"] == "insuranceDetails.waitingPeriodFlag"), None)
    wait_done = bool(waiting) or str(wait_flag or "").strip().lower() == "no"
    # The payer name / ID are offered as "Pick yourself" hints: not again below.
    payer_hinted = "PMS Payer Name" in hints or "INS E-Claim Payer ID" in hints

    return {
        "carrier": carrier,
        "network": net,
        # True: the portal states the network (Cigna) — the extension sets IN OR OON.
        "network_from_scrape": bool(scraped),
        "fields": fields,
        "grid": grid,
        "questions": questions,
        "waiting_periods": waiting,       # [{applies_to, period, unit, source}], plan level
        "checks": checks,
        "hints": hints,
        "left_for_user": [
            *([] if scraped else ["IN OR OON"]), "INS Fee Schedule",
            *([] if payer_hinted else ["PMS Payer Name / INS E-Claim Payer ID"]),
            *([] if wait_done else ["Waiting period details (Period / Applies To)"]),
            "Eligibility", "Mode of verification", "Eligibility notes",
        ],
    }


def _no_history(spec: list, by_key: dict, grid: list) -> list[dict]:
    """
    History "NH" for a code the portal answered but gave no service date for,
    including a Not Covered code (BPO feedback, 11/2026: never leave history
    blank then). A code the scrape has nothing for at all stays blank, so the
    panel lists it to check.
    """
    answered = {g["code"] for g in grid if g["column"] != "history"}
    has_history = {g["code"] for g in grid if g["column"] == "history"}
    out = []
    for field in spec:
        target = _grid_target(field, by_key)
        if not target or target[1] != "history":
            continue
        code = target[0]
        if code in answered and code not in has_history:
            has_history.add(code)
            out.append({"code": code, "column": "history", "value": "NH", "level": "appointment",
                        "source": field["key"], "label": field["label"]})
    return out


def _not_covered_ages(spec: list, by_key: dict, grid: list) -> list[dict]:
    """
    Age Limit "0" on every age cell whose code is Not Covered (frequency NC),
    replacing any age the portal printed for it (BPO feedback, 11/25: "update
    age 0 whenever a code is not covered"). Only the age cells the client's
    spec has (D1206, D1208, D1351, D1510, Ortho); D4341's age is Quads.
    """
    not_covered = {g["code"] for g in grid if g["column"] == "frequency" and g["value"] == "NC"}
    if not not_covered:
        return grid
    out = [g for g in grid if not (g["column"] == "ageLimit" and g["code"] in not_covered)]
    done = set()
    for field in spec:
        target = _grid_target(field, by_key)
        if not target or target[1] != "ageLimit" or target[0] not in not_covered or target[0] in done:
            continue
        done.add(target[0])
        out.append({"code": target[0], "column": "ageLimit", "value": "0", "level": "plan",
                    "source": field["key"], "label": field["label"]})
    return out


def _met_flags(values: dict) -> list[dict]:
    """
    INDIVIDUAL / FAMILY DEDUCTIBLE MET?, from the deductible and the amount
    met. Only when the plan has a deductible: whether a $0 deductible counts
    as met is the business team's call, so it is left to the user.
    """
    out = []
    for ded_key, paid_key, name, label in (
            ("indiv_ded", "indiv_ded_paid", "benefitsInfo.individualDeductibleMet",
             "Individual Deductible Met?"),
            ("family_ded", "family_ded_paid", "benefitsInfo.familyDeductibleMet",
             "Family Deductible Met?")):
        ded, paid = _money(values.get(ded_key) or ""), _money(values.get(paid_key) or "")
        if ded is None or paid is None or float(ded) <= 0:
            continue
        out.append({"name": name, "value": "Yes" if float(paid) >= float(ded) else "No",
                    "level": "appointment", "source": f"{ded_key}+{paid_key}", "label": label})
    return out


def member_key(portal_raw: dict) -> tuple[str | None, str | None]:
    """(member ID, patient DOB) the portal states, for matching a stored scrape to a form."""
    from shared.scrape_store import norm_dob
    try:
        _carrier, values, _spec = portal_values(portal_raw, "In")
    except ValueError:
        return None, None
    # norm_dob, not _date: a DOB is in the past, so '02/03/90' is 1990, not 2090.
    # The DOB now decides between family members on one member ID, so the
    # century must be right.
    dob = values.get("patient_dob")
    return values.get("member_id"), norm_dob(dob) or dob