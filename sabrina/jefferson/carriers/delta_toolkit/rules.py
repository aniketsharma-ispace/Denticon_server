"""
Delta Dental Office Toolkit, as this sheet needs it.

Reading the Toolkit export — its limitation prose, its accumulators, its
coverage rows — is done once, in `portals/delta_toolkit.py`. A rule that is
genuinely about how *this* sheet records a Toolkit answer belongs here.

The sheet is the same one the team fills in for any Delta Dental plan, so the
rules began as Delta Dental's own (`carriers/delta_dental/rules.py`). What the
Toolkit states outright is read from its translation instead of being inferred.
"""

from __future__ import annotations

import re

from .vocabulary import _blank


def _toolkit_export(portal_raw: dict) -> bool:
    """Whether this is the translated Toolkit export."""
    return bool((portal_raw or {}).get("_toolkit"))


def _toolkit_meta(portal_raw: dict) -> dict:
    """The answers the Toolkit translation keeps beside the shared contract."""
    meta = (portal_raw or {}).get("_toolkit_meta")
    return meta if isinstance(meta, dict) else {}


def _toolkit_wrapped_history(sab_fields: dict, benefit_rows: dict | None, portal_norm: dict) -> dict:
    """
    The sheet's fields with every wrapped History cell read in full.

    Where a History cell lists several dates and wraps after a comma, the
    parser keeps the first line as the cell and the whole list as
    `history_wrapped`. A Delta sheet is compared on the whole list — Mccoy's
    D1110 "06/10/2026, 01/29/2026" rather than "06/10/2026,".
    """
    if not _toolkit_export(portal_norm) or not isinstance(benefit_rows, dict):
        return sab_fields
    fields = dict(sab_fields)
    for row_key, columns in benefit_rows.items():
        wrapped = (columns or {}).get("history_wrapped")
        if wrapped:
            fields[f"{row_key}__hist"] = wrapped
    return fields


def _toolkit_procedure(portal_raw: dict, code: str) -> dict | None:
    """One code's translated procedure-code search; None where it was not searched."""
    for proc in ((portal_raw or {}).get("benefit_coverage") or {}).get("procedures") or []:
        if isinstance(proc, dict) and str(proc.get("procedure_code", "")).upper() == code:
            return proc
    return None


def _toolkit_code_override(value, portal_raw: dict, codes: tuple, what: str, sab_raw=None):
    """
    Correct a per-code value for how the sheet records it.

    Returns (handled, value). The sheet records the age of a code the plan does
    not cover as 0 or leaves it blank, and either is right: a 0 is compared
    against 0, and a blank is left with nothing to compare.
    """
    if what == "late_date_of_service" and _toolkit_export(portal_raw):
        return _toolkit_history_in_window(value, portal_raw, codes, sab_raw)
    if what != "age_limit" or not _toolkit_export(portal_raw):
        return False, value
    proc = next((p for p in (_toolkit_procedure(portal_raw, str(c).upper()) for c in codes) if p), None)
    level = str((proc or {}).get("benefit_level") or "").lower()
    if "not covered" not in level:
        return False, value
    return True, (None if _blank(sab_raw) else "0")


_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
# How the sheet writes "no history".
_HISTORY_NONE_WORDS = {"nh", "no history", "none", "n/h", "-", "--", "—", "–"}
_FREQ_SPAN_RE = re.compile(r"^\d+X(\d+)(Year|Month|Day)s?$", re.IGNORECASE)


def _toolkit_date(text):
    """The first date in `text`, as a date; None where there is none."""
    import datetime
    m = _DATE_RE.search(str(text or ""))
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


def _toolkit_benefit_period(portal_raw: dict):
    """
    (calendar year?, start of the current benefit period) as the Toolkit states
    them: the Maximums and Deductibles accumulation period type, and the date
    the General maximum's accumulator runs from.
    """
    raw = (portal_raw or {}).get("_raw_export") or {}
    section = raw.get("maximums_and_deductibles") or {}
    calendar = str(section.get("accumulationPeriodType") or "").strip().lower() == "calendar year"
    general = next((row for row in section.get("rows") or []
                    if isinstance(row, dict)
                    and str(row.get("type") or "").lower() == "maximum"
                    and str(row.get("category") or "").lower() == "general"), {})
    return calendar, _toolkit_date(general.get("from"))


def _toolkit_history_in_window(value, portal_raw: dict, codes: tuple, sab_raw=None):
    """
    The portal's History, as a sheet reading NH should be held to it.

    A sheet that lists service dates is compared against the portal's date as
    it stands — the team writes down whichever dates they judge relevant.

    A sheet that says NH, or leaves the cell blank, is saying no service
    affects the frequency. That is right when the portal's date falls outside
    the frequency's window, measured back from today:

        NX1Year      on a calendar-year plan, the current calendar year (from
                     the General maximum's accumulator start); on any other
                     plan, the last 12 months
        NXkYears     the last k years
        NXkMonths    the last k months
        NXkDays      the last k days

    A lifetime limit, Not Covered or no stated frequency keeps the date. Where
    no date counts, the portal side reads "—", the same as the sheet's NH.
    """
    import datetime
    sheet = str(sab_raw or "").strip()
    if sheet and sheet.lower() not in _HISTORY_NONE_WORDS and _DATE_RE.search(sheet):
        return False, value
    proc = next((p for p in (_toolkit_procedure(portal_raw, str(c).upper()) for c in codes) if p), None)
    span = _FREQ_SPAN_RE.match(str((proc or {}).get("frequency_limit") or "").strip())
    dates = [(m.group(0), _toolkit_date(m.group(0))) for m in _DATE_RE.finditer(str(value or ""))]
    dates = [(text, d) for text, d in dates if d]
    if not span or not dates:
        return False, value

    today = datetime.date.today()
    count, unit = int(span.group(1)), span.group(2).lower()

    def _months_back(n):
        y, m = divmod(today.year * 12 + today.month - 1 - n, 12)
        return datetime.date(y, m + 1, min(today.day, 28))

    if unit == "year" and count == 1:
        calendar, period_start = _toolkit_benefit_period(portal_raw)
        start = (period_start or datetime.date(today.year, 1, 1)) if calendar else None
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


def _toolkit_major_paid_on(portal_raw: dict) -> str | None:
    """
    "Are Major Services Paid on Prep or Seat date?"

    The Toolkit can state it in its Maximums and Deductibles notes ("…seat/
    delivery date…"), and that answer is taken as stated. Where it says
    nothing the sheet follows the Delta convention: "Seat Date" wherever crowns
    (D2740) are covered, and blank where they are not or were never searched.
    """
    stated = str(_toolkit_meta(portal_raw).get("major_payment_timing") or "").strip()
    if stated:
        return stated
    proc = _toolkit_procedure(portal_raw, "D2740")
    level = str((proc or {}).get("benefit_level") or "").strip().lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?", level)
    if m and float(m.group(1)) > 0 and "not covered" not in level:
        return "Seat Date"
    return None


# "Prophylaxis procedures are a benefit following active periodontal therapy
# once a 30 day post-operative period has completed."
_POST_OP_RE = re.compile(r"(\d+)[\s-]*day\s+post[\s-]*operative\s+period", re.IGNORECASE)


def _toolkit_perio_after_srp(portal_raw: dict) -> str | None:
    """
    "When Is First Perio Maintenance Allowed After SRP?"

    Stated as a post-operative period after active periodontal therapy, in
    D4910's own limitation or in a plan limitation that names periodontal
    maintenance. Where neither names one the sheet records "Not available in
    website". An export in which D4910 was never searched says nothing.
    """
    proc = _toolkit_procedure(portal_raw, "D4910")
    if proc is None:
        return None
    sentences = [str(proc.get("limitation") or "")]
    sentences += [str(s) for s in proc.get("toolkit_source_limitations") or []]
    for sentence in sentences:
        m = _POST_OP_RE.search(sentence)
        if m:
            return f"{m.group(1)} Days"
    return "Not available in website"
