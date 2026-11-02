"""
Delta Dental of Missouri, as this sheet needs it.

Translating the portal's export — its frequency wording, its masked dates of
birth, its accumulator table — is about reading the portal, not about this
sheet, so it lives in `portals/delta_mo.py`.

A rule that is genuinely about how *this* sheet records a Delta Dental of
Missouri answer belongs here. The sheet is the one the team fills in for any
Delta plan, so most of these answer the same questions the Delta Dental
folder's rules do, read off this portal's export.
"""

from __future__ import annotations

import re

from .vocabulary import _blank, _norm_network


def _mo_export(portal_raw: dict) -> bool:
    """Whether this is the translated Delta Dental of Missouri export."""
    return str((portal_raw or {}).get("_source_insurer", "")).lower() == "delta dental mo"


def _mo_wrapped_history(sab_fields: dict, benefit_rows: dict | None, portal_norm: dict) -> dict:
    """
    The sheet's fields with every wrapped History cell read in full.

    Where a History cell lists several dates and wraps after a comma, the
    parser keeps the first line as the cell and the whole list as
    `history_wrapped`. The audit compares and shows the whole list, as the
    Delta Dental audit does.
    """
    if not _mo_export(portal_norm) or not isinstance(benefit_rows, dict):
        return sab_fields
    fields = dict(sab_fields)
    for row_key, columns in benefit_rows.items():
        wrapped = (columns or {}).get("history_wrapped")
        if wrapped:
            fields[f"{row_key}__hist"] = wrapped
    return fields


def _mo_procedure(portal_raw: dict, code: str) -> dict | None:
    """One code's translated coverage entry; None where it was not requested."""
    for proc in ((portal_raw or {}).get("benefit_coverage") or {}).get("procedures") or []:
        if isinstance(proc, dict) and str(proc.get("procedure_code", "")).upper() == code:
            return proc
    return None


def _mo_code_override(value, portal_raw: dict, codes: tuple, what: str, sab_raw=None):
    """
    Correct a per-code value for a code the plan does not cover.

    Returns (handled, value), as the Delta Dental folder's override does. A
    code the coverage table does not list has no age limit of its own; the
    sheet records such a code's age as 0 or leaves it blank, and either is
    right: a 0 is compared against 0, and a blank is left with nothing to
    compare.
    """
    if what == "late_date_of_service" and _mo_export(portal_raw):
        return _mo_history_in_window(value, portal_raw, codes, sab_raw)
    if what != "age_limit" or not _mo_export(portal_raw):
        return False, value
    proc = next((p for p in (_mo_procedure(portal_raw, str(c).upper()) for c in codes) if p), None)
    if "not covered" not in str((proc or {}).get("benefit_level") or "").lower():
        return False, value
    return True, (None if _blank(sab_raw) else "0")


_MO_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
# How the sheet writes "no history".
_HISTORY_NONE_WORDS = {"nh", "no history", "none", "n/h", "-", "--", "—", "–"}
_MO_FREQ_SPAN_RE = re.compile(r"^\d+X(\d+)(Year|Month|Day)s?$", re.IGNORECASE)


def _mo_date(text):
    """The first date in `text`, as a date; None where there is none."""
    import datetime
    m = _MO_DATE_RE.search(str(text or ""))
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    year += 2000 if year < 100 else 0
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _mo_history_in_window(value, portal_raw: dict, codes: tuple, sab_raw=None):
    """
    The portal's history, as a sheet reading NH should be held to it.

    The same reading the Delta Dental audit applies. A sheet that lists
    service dates is compared against every date the portal has. A sheet that
    says NH, or leaves the cell blank, is saying no service affects the
    frequency, which is right when every portal date falls outside the
    frequency's window, measured back from the day the portal was read:

        NX1Year      on a calendar-year plan, the current benefit year;
                     otherwise the last 12 months
        NXkYears     the last k years
        NXkMonths    the last k months
        NXkDays      the last k days

    A lifetime limit, no stated frequency or NC keeps every date. Where no
    date counts, the portal side reads "—", the same as the sheet's NH.
    """
    import datetime
    sheet = str(sab_raw or "").strip()
    if sheet and sheet.lower() not in _HISTORY_NONE_WORDS and _MO_DATE_RE.search(sheet):
        return False, value
    proc = next((p for p in (_mo_procedure(portal_raw, str(c).upper()) for c in codes) if p), None)
    span = _MO_FREQ_SPAN_RE.match(str((proc or {}).get("frequency_limit") or "").strip())
    dates = [(m.group(0), _mo_date(m.group(0))) for m in _MO_DATE_RE.finditer(str(value or ""))]
    dates = [(text, d) for text, d in dates if d]
    if not span or not dates:
        return False, value

    meta = (portal_raw or {}).get("_mo_meta") or {}
    today = _mo_date(meta.get("scraped_on")) or datetime.date.today()
    count, unit = int(span.group(1)), span.group(2).lower()

    def _months_back(n):
        y, m = divmod(today.year * 12 + today.month - 1 - n, 12)
        return datetime.date(y, m + 1, min(today.day, 28))

    if unit == "year" and count == 1:
        start = None
        if meta.get("benefit_period_calendar"):
            start = _mo_date(meta.get("benefit_period_start")) or datetime.date(today.year, 1, 1)
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


def _mo_major_paid_on(portal_raw: dict) -> str | None:
    """
    "Are Major Services Paid on Prep or Seat date?"

    The portal does not state it. As for every Delta plan, the sheet records
    "Seat Date" wherever crowns (D2740) are covered and leaves the field blank
    where they are not, so nothing is stated for a plan without crown
    coverage, or for an export without D2740.
    """
    proc = _mo_procedure(portal_raw, "D2740")
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", str((proc or {}).get("benefit_level") or ""))
    if m and float(m.group(1)) > 0:
        return "Seat Date"
    return None


# "Prophylaxis procedures are a benefit following active periodontal therapy
# once a 30 day post-operative period has completed."
_MO_POST_OP_RE = re.compile(r"(\d+)[\s-]*day\s+post[\s-]*operative\s+period", re.IGNORECASE)


def _mo_perio_after_srp(portal_raw: dict) -> str | None:
    """
    "When Is First Perio Maintenance Allowed After SRP?"

    Read from a post-operative period named in D4910's limitation. The
    coverage table usually states none, and the sheet then records "Not
    available in website". An export without D4910 says nothing either way.
    """
    proc = _mo_procedure(portal_raw, "D4910")
    if proc is None:
        return None
    m = _MO_POST_OP_RE.search(str(proc.get("limitation") or ""))
    return f"{m.group(1)} Days" if m else "Not available in website"


def _mo_prev_in_max(portal_raw: dict) -> str | None:
    """
    "Preventative Included in Yearly Max?"

    The export's own figures decide it first: preventive services paid this
    benefit year with nothing used from the maximum mean they do not count
    (No); money used when only preventive services were paid means they do
    (Yes). See `portals/delta_mo._mo_prev_in_max_evidence` — Umar Aamer's plan
    reads MAXAdvantage "No" yet his preventive visits used none of it.

    Otherwise the portal answers it as the MAXAdvantage option: where the plan
    has it, exams, cleanings, x-rays and fluoride do not count toward the
    annual maximum (No); where it does not, they do (Yes).
    """
    meta = (portal_raw or {}).get("_mo_meta") or {}
    if meta.get("prev_in_max_evidence") in ("Yes", "No"):
        return meta["prev_in_max_evidence"]
    return {"Yes": "No", "No": "Yes"}.get(meta.get("is_max_advantage"))


# A fee schedule naming Premier — "GA - DD GP Premier B", "… Prem …" — is
# audited against Premier; a Premier Lite schedule ("DD LITE Pr", "PremLT")
# stays with PPO, as on Delta Dental's own site.
_MO_LITE_FEE_RE = re.compile(r"lite|prem\s*lt\b", re.IGNORECASE)
_MO_PREMIER_FEE_RE = re.compile(r"\bprem", re.IGNORECASE)


def _mo_network_export(portal_raw: dict, sheet_in_network, fee_schedule=None) -> dict:
    """
    The export marked with the network the sheet records.

    Every coverage row states the PPO, Premier and out-of-network percentage
    side by side. A sheet whose In Network reads "Out" is audited against the
    out-of-network ones, an in-network sheet whose fee schedule names Premier
    against Premier, and anything else against PPO.
    """
    if not isinstance(portal_raw, dict):
        return portal_raw
    text = str(fee_schedule or "")
    if _norm_network(sheet_in_network) == "OUT":
        network = "oon"
    elif _MO_PREMIER_FEE_RE.search(text) and not _MO_LITE_FEE_RE.search(text):
        network = "premier"
    else:
        network = "ppo"
    return {**portal_raw, "_mo_network": network}
