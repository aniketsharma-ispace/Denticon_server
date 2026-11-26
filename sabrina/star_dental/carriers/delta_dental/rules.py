"""
Delta Dental, as this sheet needs it.

Delta's export needs a great deal of translation — its limitation prose, its
age bands, its footnotes — but all of that is about reading the portal, not
about this sheet, so it lives in `portals/delta_dental.py` where every vendor
can use it.

A rule that is genuinely about how *this* sheet records a Delta answer belongs
here.
"""

from __future__ import annotations

import re

from .vocabulary import _blank, _norm_network


def _dd_export(portal_raw: dict) -> bool:
    """Whether this is the translated Delta Dental export."""
    return str((portal_raw or {}).get("_source_insurer", "")).lower() == "delta dental"


def _dd_wrapped_history(sab_fields: dict, benefit_rows: dict | None, portal_norm: dict) -> dict:
    """
    The sheet's fields with every wrapped History cell read in full, for a
    Delta Dental audit.

    Where a History cell lists several dates and wraps after a comma, the
    parser keeps the first line as the cell and the whole list as
    `history_wrapped`. A Delta audit compares and shows the whole list —
    Mccoy's D1110 "06/10/2026, 01/29/2026" rather than "06/10/2026,". Every
    other carrier's audit keeps the first line, as before.
    """
    if not _dd_export(portal_norm) or not isinstance(benefit_rows, dict):
        return sab_fields
    fields = dict(sab_fields)
    for row_key, columns in benefit_rows.items():
        wrapped = (columns or {}).get("history_wrapped")
        if wrapped:
            fields[f"{row_key}__hist"] = wrapped
    return fields


def _dd_procedure(portal_raw: dict, code: str) -> dict | None:
    """One code's translated Benefits Search entry; None where it was not searched."""
    for proc in ((portal_raw or {}).get("benefit_coverage") or {}).get("procedures") or []:
        if isinstance(proc, dict) and str(proc.get("procedure_code", "")).upper() == code:
            return proc
    return None


def _dd_code_override(value, portal_raw: dict, codes: tuple, what: str, sab_raw=None):
    """
    Correct a per-code value for a code Delta does not cover.

    Returns (handled, value), as `_cigna_code_override` does. Delta prints
    "None" in the Age limits column of a code it does not pay for, which reads
    as no age restriction (99). The sheet records such a code's age as 0 or
    leaves it blank, and either is right: a 0 is compared against 0, and a
    blank is left with nothing to compare.
    """
    if what == "late_date_of_service" and _dd_export(portal_raw):
        return _dd_history_in_window(value, portal_raw, codes, sab_raw)
    if what != "age_limit" or not _dd_export(portal_raw):
        return False, value
    proc = next((p for p in (_dd_procedure(portal_raw, str(c).upper()) for c in codes) if p), None)
    level = str((proc or {}).get("benefit_level") or "").lower()
    if "not covered" not in level:
        return False, value
    return True, (None if _blank(sab_raw) else "0")


_DD_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
# How the sheet writes "no history".
_HISTORY_NONE_WORDS = {"nh", "no history", "none", "n/h", "-", "--", "—", "–"}
_DD_FREQ_SPAN_RE = re.compile(r"^\d+X(\d+)(Year|Month|Day)s?$", re.IGNORECASE)


def _dd_date(text):
    """The first date in `text`, as a date; None where there is none."""
    import datetime
    m = _DD_DATE_RE.search(str(text or ""))
    if not m:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(text or ""))
        if not m:
            return None
        year, month, day = (int(g) for g in m.groups())
    else:
        month, day, year = (int(g) for g in m.groups())
        year += 2000 if year < 100 else 0
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _dd_history_in_window(value, portal_raw: dict, codes: tuple, sab_raw=None):
    """
    The portal's History, as a sheet reading NH should be held to it.

    A sheet that lists service dates is compared against every date the
    portal has — the team writes down whichever dates they judge relevant,
    old ones included (Sandra Low Frigerio's D0140 08/30/2024 on a 30-day
    limit; appointment 120901's bitewings back to 10/10/2023). Those pass
    through untouched.

    A sheet that says NH, or leaves the cell blank, is saying no service
    affects the frequency. That is right when every portal date falls outside
    the frequency's window — Deion Reid's bitewings, last taken 01/07/2020,
    against 1X1Year. The window is measured back from the day the portal was
    read:

        NX1Year      on a calendar-year plan, the current calendar year
                     (from the maximum's accumulation period, e.g.
                     1/1/2026); on a fiscal-year plan, the last 12 months
        NXkYears     the last k years
        NXkMonths    the last k months
        NXkDays      the last k days

    A lifetime limit, Pre-D, NC or no stated frequency keeps every date. Where
    no date counts, the portal side reads "—", the same as the sheet's NH.
    """
    import datetime
    sheet = str(sab_raw or "").strip()
    if sheet and sheet.lower() not in _HISTORY_NONE_WORDS and _DD_DATE_RE.search(sheet):
        return False, value
    proc = next((p for p in (_dd_procedure(portal_raw, str(c).upper()) for c in codes) if p), None)
    span = _DD_FREQ_SPAN_RE.match(str((proc or {}).get("frequency_limit") or "").strip())
    dates = [(m.group(0), _dd_date(m.group(0))) for m in _DD_DATE_RE.finditer(str(value or ""))]
    dates = [(text, d) for text, d in dates if d]
    if not span or not dates:
        return False, value

    meta = (portal_raw or {}).get("_dd_meta") or {}
    today = _dd_date(meta.get("scraped_on")) or datetime.date.today()
    count, unit = int(span.group(1)), span.group(2).lower()

    def _months_back(n):
        y, m = divmod(today.year * 12 + today.month - 1 - n, 12)
        return datetime.date(y, m + 1, min(today.day, 28))

    if unit == "year" and count == 1:
        # A calendar-year plan counts the current calendar year; a fiscal-year
        # (or any other) plan counts the last 12 months (agreed with the team).
        start = None
        if meta.get("benefit_period_calendar"):
            start = _dd_date(meta.get("benefit_period_start")) or datetime.date(today.year, 1, 1)
        if not start or start > today:
            start = _months_back(12)
    elif unit == "year":
        start = _months_back(12 * count)
    elif unit == "month":
        start = _months_back(count)
    else:
        start = today - datetime.timedelta(days=count)

    kept = [text for text, d in dates if d >= start]
    return True, (", ".join(kept) if kept else "—")


def _dd_major_paid_on(portal_raw: dict) -> str | None:
    """
    "Are Major Services Paid on Prep or Seat date?"

    Delta does not state it. The sheet records "Seat Date" wherever crowns
    (D2740) are covered and leaves the field blank where they are not, so
    nothing is stated for a plan without crown coverage, or for an export in
    which D2740 was never searched.
    """
    proc = _dd_procedure(portal_raw, "D2740")
    level = str((proc or {}).get("benefit_level") or "").strip().lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", level)
    if m and float(m.group(1)) > 0 and "not covered" not in level:
        return "Seat Date"
    return None


def _dd_pays(proc: dict | None) -> bool:
    """Whether Delta pays anything for a translated procedure."""
    level = str((proc or {}).get("benefit_level") or "").lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", level)
    return bool(m) and float(m.group(1)) > 0 and "not covered" not in level


def _dd_downgraded(proc: dict | None) -> bool:
    """
    Whether Delta pays this code only at another code's benefit.

    For a posterior composite Delta says "it is not a benefit of the member's
    plan. When amalgam restorations are a benefit, the applicable amalgam
    benefit will be applied." The translation fills in the amalgam's benefit
    (D2391 at D2140's 80%) for the readers that want the substitution. Star
    Dental's sheet records the composite itself as Delta states it — NC, 0 —
    and answers the substitution on "Posterior composite downgrade?" instead,
    so this sheet reads such a code as not covered.
    """
    return bool((proc or {}).get("alternate_benefit_from"))


def _dd_shares_frequency(portal_raw: dict, code_a: str, code_b: str) -> str | None:
    """
    Whether two codes draw on one frequency limit, as Delta's prose says.

    Delta states a shared limit in one of two ways: one code's limitation names
    the other ("either one (D0210) intraoral complete series, or (D0330)
    panoramic radiographic image"; "two of any prophylaxis procedures … for
    codes D1110, D1120, D4346, D4355, and D4910"), or both codes carry the same
    pooled sentence ("two of any oral evaluation procedure within a calendar
    year"). Limits stated separately are not shared. A code Delta does not pay
    for, or that states no limit, settles nothing.
    """
    a, b = _dd_procedure(portal_raw, code_a), _dd_procedure(portal_raw, code_b)
    if not (_dd_pays(a) and _dd_pays(b)):
        return None
    text_a = re.sub(r"\s+", " ", str(a.get("limitation") or "")).strip()
    text_b = re.sub(r"\s+", " ", str(b.get("limitation") or "")).strip()
    if not text_a or not text_b:
        return None
    if re.search(rf"\b{code_b}\b", text_a) or re.search(rf"\b{code_a}\b", text_b):
        return "Yes"
    if text_a.lower() == text_b.lower() and re.search(r"\b(?:any|either)\b", text_a, re.IGNORECASE):
        return "Yes"
    return "No"


_DD_COUNT_WORDS = {"once": 1, "twice": 2, "one": 1, "two": 2, "three": 3, "four": 4}


# "This procedure is a benefit once per provider per lifetime." The count is
# the one nearest "per provider": the scraper may join that sentence to the
# one before it without a full stop ("… within a calendar year This procedure
# is a benefit once per provider …"), and the earlier count is not this limit.
_DD_PER_PROVIDER_RE = re.compile(
    r"(?:limited to|is a benefit)\s+(once|twice|one|two|three|four|\d+)\b"
    r"(?:(?!limited to|is a benefit)[^.])*?\bper\s+(?:provider|dentist|office|location)\b",
    re.IGNORECASE)


def _dd_d0150_per_provider(portal_raw: dict) -> str | None:
    """
    "D0150 freq per provider?" — the sheet's "1XProvider".

    Delta adds the per-provider limit to D0150's limitation: "Benefit is
    limited to two of any oral evaluation procedure within a calendar year
    This procedure is a benefit once per provider per lifetime." Where it says
    nothing of the kind, nothing is stated.
    """
    proc = _dd_procedure(portal_raw, "D0150")
    m = _DD_PER_PROVIDER_RE.search(str((proc or {}).get("limitation") or ""))
    if not m:
        return None
    word = m.group(1).lower()
    count = int(word) if word.isdigit() else _DD_COUNT_WORDS[word]
    return f"{count}XProvider"


def _dd_provision(portal_raw: dict, name: str) -> str:
    """A plan provision's text, by the start of its name; "" where there is none."""
    ml = (portal_raw or {}).get("metlife_data") or {}
    for prov in ml.get("provisions") or []:
        if isinstance(prov, dict) and str(prov.get("rule") or "").lower().startswith(name.lower()):
            return re.sub(r"\s+", " ", str(prov.get("value") or "")).strip()
    return ""


def _dd_ortho_age_limit(portal_raw: dict, adult: bool, sab_raw=None) -> str | None:
    """
    The orthodontic age ceiling — Star Dental's "Subscriber Age Limit?" for an
    adult, "Dependent Age Limit?" for a child — with 99 meaning none.

    Delta states it in the "Orthodontic Age Limit" provision ("Child and adult
    ;no age limit", "Child to age 19") and, for a child, sometimes as an age
    band on D8080. Where that class's orthodontics is not covered at all (no
    D8090 benefit for an adult) there is no age to state, and the sheet's 0 is
    compared as with any code Delta does not pay for. Where the provision is
    only the portal's "Click here for age limits." link, the limit sits behind
    it and nothing is stated.
    """
    proc = _dd_procedure(portal_raw, "D8090" if adult else "D8080")
    text = _dd_provision(portal_raw, "Orthodontic Age Limit").lower()
    not_covered = (proc is not None and not _dd_pays(proc)) or "not a covered benefit" in text
    if not_covered:
        return None if _blank(sab_raw) else "0"
    if "no age limit" in text and (not adult or "adult" in text or "child" not in text):
        return "99"
    m = re.search(r"\bage\s*(\d{1,2})\b", text)
    if m and (not adult or "adult" in text):
        return m.group(1)
    if not adult:
        band = str((proc or {}).get("age_limit") or "").strip()
        if band.isdigit() and int(band) < 99:
            return band
    return None


def _dd_member_id(bd: dict, portal_raw: dict, sab_raw=None) -> str | None:
    """
    The member ID, as this sheet records it.

    Delta numbers a family once and suffixes each member — …001 for the
    subscriber, …002 for a spouse. The translation reports the subscriber's,
    the number the policy is filed under; a Star Dental sheet for a dependent
    may record the patient's own instead. Both identify the patient's coverage,
    so whichever of the two the sheet names is reported, and the subscriber's
    otherwise.
    """
    subscriber = None if _blank(bd.get("member_id")) else str(bd.get("member_id")).strip()
    raw = (portal_raw or {}).get("_raw_export") or {}
    fields = (raw.get("primary_patient") or {}).get("static_fields") or {}
    own = next((str(v).strip() for k, v in fields.items()
                if str(k).strip().lower() == "member id" and not _blank(v)), None)
    sheet = re.sub(r"\D", "", str(sab_raw or ""))
    for candidate in (own, subscriber):
        if candidate and sheet and re.sub(r"\D", "", candidate) == sheet:
            return candidate
    return subscriber or own


def _dd_general_ortho_deductible(bd: dict, portal_raw: dict) -> tuple[str, str] | None:
    """
    The orthodontic deductible and amount met, where the plan has no separate
    orthodontic deductible.

    Delta lists the treatment types each deductible applies to. Where the
    ordinary individual deductible names Orthodontics among them, orthodontic
    work draws on that same deductible, and the sheet records it as the
    orthodontic deductible. A separate orthodontic deductible, which the
    translation reads on its own, stands.
    """
    if ((portal_raw or {}).get("_dd_meta") or {}).get("ortho_deductible"):
        return None
    if not (_dd_pays(_dd_procedure(portal_raw, "D8080")) or _dd_pays(_dd_procedure(portal_raw, "D8090"))):
        return None
    raw = (portal_raw or {}).get("_raw_export") or {}
    overview = (raw.get("tabs") or {}).get("overview") or {}
    for record in overview.get("deductibles") or []:
        if not isinstance(record, dict) or "individual" not in str(record.get("type") or "").lower():
            continue
        if any("orthodont" in str(t).lower() for t in record.get("treatment_types") or []):
            total, used = bd.get("indiv_ded"), bd.get("indiv_ded_paid")
            return None if _blank(total) else (str(total), "" if _blank(used) else str(used))
    return None


def _dd_member_active(portal_raw: dict) -> bool:
    """Whether the patient's coverage runs to the present ("08/09/2021 - present")."""
    raw = (portal_raw or {}).get("_raw_export") or {}
    fields = (raw.get("primary_patient") or {}).get("static_fields") or {}
    eligibility = next((str(v) for k, v in fields.items()
                        if str(k).strip().lower() == "member eligibility"), "")
    return bool(re.search(r"-\s*present\s*$", eligibility, re.IGNORECASE))


# "Prophylaxis procedures are a benefit following active periodontal therapy
# once a 30 day post-operative period has completed."
_DD_POST_OP_RE = re.compile(r"(\d+)[\s-]*day\s+post[\s-]*operative\s+period", re.IGNORECASE)


def _dd_perio_after_srp(portal_raw: dict) -> str | None:
    """
    "When Is First Perio Maintenance Allowed After SRP?"

    Delta states it in D4910's limitation as a post-operative period after
    active periodontal therapy. Where D4910's limitation names no such period
    the sheet records "Not available in website". An export in which D4910
    was never searched says nothing either way.
    """
    proc = _dd_procedure(portal_raw, "D4910")
    if proc is None:
        return None
    m = _DD_POST_OP_RE.search(str(proc.get("limitation") or ""))
    return f"{m.group(1)} Days" if m else "Not available in website"


# A Premier Lite fee schedule is written many ways — "Premier Lite", "#3 MI -
# DD LITE Pr Reg6", "#203 MI - DD PremLT Perio" — and is audited against PPO.
_DD_LITE_FEE_RE = re.compile(r"lite|prem\s*lt\b", re.IGNORECASE)
# Any other fee schedule naming Premier — "GA - DD GP Premier B", "… Prem …" —
# is audited against Premier.
_DD_PREMIER_FEE_RE = re.compile(r"\bprem", re.IGNORECASE)


def _dd_selected_network(portal_raw: dict) -> str:
    """
    The network the user picked in the extension's pop-up before the
    procedure-code search — "ppo", "premier" or "oon" — or "" for an export
    made before the pop-up, or where the pick could not be applied. Read from
    the raw export or from its translation, which keeps the raw one.
    """
    raw = (portal_raw or {}).get("_raw_export") or portal_raw or {}
    tabs = raw.get("tabs") if isinstance(raw, dict) else None
    value = str((tabs or {}).get("benefits_search_selected") or "").strip().lower()
    return value if value in ("ppo", "premier", "oon") else ""


def _dd_fee_schedule_network(fee_schedule) -> str:
    """
    The Delta network a sheet's fee schedule names: "premier", "ppo" for a
    Premier Lite schedule, or "" where it names neither (agreed with the team).
    Lite is checked first, since "PremLT" and "Premier Lite" also say Prem.
    """
    text = str(fee_schedule or "")
    if _DD_LITE_FEE_RE.search(text):
        return "ppo"
    if _DD_PREMIER_FEE_RE.search(text):
        return "premier"
    return ""


def _dd_network_export(portal_raw: dict, sheet_in_network, fee_schedule=None) -> dict:
    """
    The export with Benefits Search answered for the network the sheet records.

    Benefits Search states one network at a time, and the extension searches
    every code three times: `benefits_search` for the plan's own network,
    `benefits_search_oon` for "Non-Delta Dental Dentist" and
    `benefits_search_premier` for "Delta Dental Premier Dentist".

    - A sheet whose In Network reads "Out" is audited against the non-Delta
      answers — D0150 at 50% rather than 100%.
    - An in-network sheet whose fee schedule names Premier ("GA - DD GP
      Premier B") is audited against the Premier answers. A Premier Lite
      schedule ("DD LITE Pr", "PremLT") stays with PPO.

    Anything else — an in-network PPO sheet, an export from before a search
    was added, a search that did not run — leaves the export as it is.
    """
    if not isinstance(portal_raw, dict):
        return portal_raw
    tabs = portal_raw.get("tabs")
    if not isinstance(tabs, dict):
        return portal_raw

    # The user chose the office's network in the extension's pop-up, and only
    # that network was searched — `benefits_search` already is the answer.
    if _dd_selected_network(portal_raw):
        return portal_raw

    if _norm_network(sheet_in_network) == "OUT":
        answers, label = tabs.get("benefits_search_oon"), tabs.get("benefits_search_oon_network")
        default = "Non-Delta Dental Dentist"
    elif _dd_fee_schedule_network(fee_schedule) == "premier":
        answers, label = tabs.get("benefits_search_premier"), tabs.get("benefits_search_premier_network")
        default = "Delta Dental Premier Dentist"
    else:
        return portal_raw

    if not isinstance(answers, list) or not answers:
        return portal_raw
    chosen = dict(tabs)
    chosen["benefits_search"] = answers
    chosen["benefits_search_network"] = label or default
    return {**portal_raw, "tabs": chosen}
