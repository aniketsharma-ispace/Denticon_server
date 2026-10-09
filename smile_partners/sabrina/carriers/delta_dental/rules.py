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


def _dd_network_export(portal_raw: dict, sheet_in_network) -> dict:
    """
    The export with Benefits Search answered for the network the sheet records.

    Benefits Search states one network at a time, and the extension searches
    every code under both: `benefits_search` for the plan's own network and
    `benefits_search_oon` for "Non-Delta Dental Dentist". The sheet's "In
    Network" field says which one this office is, so a sheet reading "Out" is
    audited against the non-Delta answers — D0150 at 50% rather than 100%.

    Anything else — a sheet reading "In" or nothing, an export from before the
    second search, a search that did not run — leaves the export as it is.
    """
    if not isinstance(portal_raw, dict) or _norm_network(sheet_in_network) != "OUT":
        return portal_raw
    tabs = portal_raw.get("tabs")
    if not isinstance(tabs, dict):
        return portal_raw
    oon = tabs.get("benefits_search_oon")
    if not isinstance(oon, list) or not oon:
        return portal_raw
    chosen = dict(tabs)
    chosen["benefits_search"] = oon
    chosen["benefits_search_network"] = tabs.get("benefits_search_oon_network") or "Non-Delta Dental Dentist"
    return {**portal_raw, "tabs": chosen}
