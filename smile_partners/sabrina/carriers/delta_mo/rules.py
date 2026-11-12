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

    The sheet is held to the day it was verified [11/10, team rule]: a portal
    date after the sheet's Verification Date (typically the appointment
    itself) did not exist when the sheet was filled, so it is dropped, and
    the window is measured back from that day.
    """
    import datetime
    meta = (portal_raw or {}).get("_mo_meta") or {}
    verified = _mo_date(meta.get("verified_on"))
    dates = [(m.group(0), _mo_date(m.group(0))) for m in _MO_DATE_RE.finditer(str(value or ""))]
    dates = [(text, d) for text, d in dates if d]
    later = bool(verified) and any(d > verified for _, d in dates)
    if later:
        dates = [(text, d) for text, d in dates if d <= verified]

    def _as_of_verification():
        return (True, ", ".join(text for text, _ in dates) or "—") if later else (False, value)

    sheet = str(sab_raw or "").strip()
    if sheet and sheet.lower() not in _HISTORY_NONE_WORDS and _MO_DATE_RE.search(sheet):
        return _as_of_verification()
    start = _mo_window_start(portal_raw, codes)
    if not start or not dates:
        return _as_of_verification()

    kept = [text for text, d in dates if d >= start]
    return True, (", ".join(kept) if kept else "—")


def _mo_window_start(portal_raw: dict, codes: tuple):
    """
    The first day of the code's frequency window, measured back from the
    sheet's as-of day (see `_mo_history_in_window`); None where the code states
    no windowed frequency (a lifetime limit, none, NC).
    """
    import datetime
    meta = (portal_raw or {}).get("_mo_meta") or {}
    proc = next((p for p in (_mo_procedure(portal_raw, str(c).upper()) for c in codes) if p), None)
    span = _MO_FREQ_SPAN_RE.match(str((proc or {}).get("frequency_limit") or "").strip())
    if not span:
        return None

    today = _mo_date(meta.get("verified_on")) or _mo_date(meta.get("scraped_on")) or datetime.date.today()
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
    return start


def _mo_history_skipped(sab_raw, por_raw, portal_raw: dict, codes: tuple) -> list[str]:
    """
    Portal visits a sheet that lists dates should have listed but left out
    [11/12, Koushik: Oladele Famakinwa D1208].

    `por_raw` is the portal's history as of the sheet's day (see
    `_mo_history_in_window`), pairs included. The sheet records the latest
    visits, so it leaves one out where the portal has a visit after the latest
    date it lists (Oladele: 10/10/2025 against the portal's 05/01/2026), or,
    where it lists several dates, a visit inside the frequency window it does
    not list (Tammy Swank's D1110: 10/19/2026 and 10/07/2025 against 10/19/2026
    and 04/15/2026 this year). A sheet listing one date records the last visit
    only, which is right (Tia Hoehne's D1208, 11/10). Older visits it does not
    list are fine.
    """
    if not _mo_export(portal_raw):
        return []
    sheet = {d for d in (_mo_date(m.group(0)) for m in _MO_DATE_RE.finditer(str(sab_raw or ""))) if d}
    portal = {}
    for m in _MO_DATE_RE.finditer(str(por_raw or "")):
        d = _mo_date(m.group(0))
        if d:
            portal[d] = m.group(0)
    if not sheet or not portal:
        return []
    latest = max(sheet)
    start = _mo_window_start(portal_raw, codes) if len(sheet) > 1 else None
    skipped = [d for d in portal if d not in sheet and (d > latest or (start and d >= start))]
    return [portal[d] for d in sorted(skipped, reverse=True)]


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

    The team records the member's MAXAdvantage option as it stands: Yes where
    the portal reads Yes, No where it reads No (11/10, team rule, Mahesh).
    This replaced reading it from the year's paid claims and inverting the
    option (11/02), which gave David Olea, Maryjoe Amaihe, Tammy Swank and
    Avery Warren the wrong answer.
    """
    meta = (portal_raw or {}).get("_mo_meta") or {}
    answer = meta.get("is_max_advantage")
    return answer if answer in ("Yes", "No") else None


# A fee schedule naming Premier — "GA - DD GP Premier B", "… Prem …" — is
# audited against Premier; a Premier Lite schedule ("DD LITE Pr", "PremLT")
# stays with PPO, as on Delta Dental's own site.
_MO_LITE_FEE_RE = re.compile(r"lite|prem\s*lt\b", re.IGNORECASE)
_MO_PREMIER_FEE_RE = re.compile(r"\bprem", re.IGNORECASE)
# The office's own fees, as an out-of-network office bills: "GA General UCR".
_MO_UCR_FEE_RE = re.compile(r"\bUCR\b", re.IGNORECASE)

_MO_NETWORK_NAMES = {"ppo": "PPO", "premier": "Premier", "oon": "Out of Network"}


def _mo_sheet_network(sheet_in_network, fee_schedule=None) -> tuple[str, str, str]:
    """
    The network whose benefits the sheet records, why, and any contradiction
    on the sheet itself (ported from DD Toolkit, 11/03–11/04 reviews):

    1. A fee schedule naming Premier (not Premier Lite) → Premier, even where
       In Network says Out; such a sheet contradicts itself.
    2. In Network "Out", or a UCR fee schedule → out of network. A UCR fee
       schedule on a sheet that says In is a contradiction too.
    3. Anything else → PPO.
    """
    text = str(fee_schedule or "").strip()
    in_network = _norm_network(sheet_in_network)
    if _MO_PREMIER_FEE_RE.search(text) and not _MO_LITE_FEE_RE.search(text):
        conflict = ("the sheet says In Network: Out, but its Fee Schedule names Premier"
                    if in_network == "OUT" else "")
        return "premier", f"sheet Fee Schedule: {text}", conflict
    ucr = bool(_MO_UCR_FEE_RE.search(text))
    if in_network == "OUT" or ucr:
        reasons = (["sheet In Network: Out"] if in_network == "OUT" else []) + (
            [f"sheet Fee Schedule: {text}"] if ucr else [])
        conflict = ("the sheet says In Network: In, but its Fee Schedule is UCR"
                    if ucr and in_network == "IN" else "")
        return "oon", ", ".join(reasons), conflict
    return "ppo", "", ""


def _mo_network_export(portal_raw: dict, sheet_in_network, fee_schedule=None) -> dict:
    """
    The export marked with the network the sheet records.

    Every coverage row states the PPO, Premier and out-of-network percentage
    side by side; `_mo_sheet_network` picks the column. The reason and any
    contradiction ride along for the In Network row and the audit's legend.
    """
    if not isinstance(portal_raw, dict):
        return portal_raw
    network, reason, conflict = _mo_sheet_network(sheet_in_network, fee_schedule)
    return {**portal_raw, "_mo_network": network,
            "_mo_network_reason": reason, "_mo_network_conflict": conflict}


def _mo_in_network_conflict(portal_raw: dict, sab_raw) -> tuple[str, str] | None:
    """
    (portal value, note) for the In Network row of a sheet that contradicts
    itself; None otherwise. The benefits were compared under the network its
    Fee Schedule names, so its In Network answer is flagged against it.
    """
    conflict = (portal_raw or {}).get("_mo_network_conflict")
    if not conflict or _blank(sab_raw):
        return None
    network = (portal_raw or {}).get("_mo_network") or "ppo"
    shown = "Out" if network == "oon" else "In"
    return shown, f"{conflict}; benefits compared under {_MO_NETWORK_NAMES.get(network, network)}"


# ══════════════════════════════════════════════════════════════════════════════
#  IDENTITY (ported from DD Toolkit, 11/11)
# ══════════════════════════════════════════════════════════════════════════════

def _mo_patient(portal_raw: dict) -> dict:
    """The translated export's patient record."""
    return (((portal_raw or {}).get("metlife_data") or {}).get("patient") or {})


def _mo_eligibility(portal_raw: dict) -> str | None:
    """The member record's Eligible Yes/No."""
    if not _mo_export(portal_raw):
        return None
    answer = _mo_patient(portal_raw).get("eligibility")
    return answer if answer in ("Yes", "No") else None


def _mo_relationship(portal_raw: dict) -> str | None:
    """The member record's relationship to the subscriber, as the sheet words it."""
    if not _mo_export(portal_raw):
        return None
    raw = str(_mo_patient(portal_raw).get("relationship") or "").strip()
    if not raw:
        return None
    return "Self" if raw.lower() == "subscriber" else raw.title()


# Dependents the sheet may name either by their own relationship or as a
# plain "Dependent".
_MO_DEPENDENTS = {"spouse", "child", "dependent", "domestic partner", "partner", "student"}


def _mo_relationship_agrees(sheet, portal) -> tuple[bool | None, str]:
    """
    Whether the sheet's Relation to Subscriber agrees with the portal's.

    The same word agrees. The sheet's "Dependent" covers any member who is not
    the subscriber (Anna Hayes is the subscriber's spouse; Tia Hoehne his
    child), and a portal "Dependent" any relationship but Self. Self against
    a dependent, or Spouse against Child, disagree.
    """
    a, b = str(sheet or "").strip().lower(), str(portal or "").strip().lower()
    if not a or not b:
        return None, ""
    if a == b:
        return True, ""
    if "dependent" in (a, b) and {a, b} <= _MO_DEPENDENTS:
        return True, "a dependent either way"
    if a in _MO_DEPENDENTS | {"self"} and b in _MO_DEPENDENTS | {"self"}:
        return False, ""
    return None, ""


def _mo_identity_gate(sabrina_parsed: dict, portal_raw: dict) -> tuple[bool, list[str]]:
    """
    Whether the sheet and the export are the same member, before anything else
    is compared (ported from DD Toolkit).

    Patient name, date of birth and group number must be stated on both sides
    and agree. The portal must state eligibility, and where the sheet's title
    states it too ("Patient Eligible"), the two must agree. Names agree as the
    Patient Name row has them agree (an extra given name, initials, spacing
    and apostrophes aside). The date of birth on the portal has its year
    filled in from the member's age on the day the portal was read.

    There is no network check: the export states the PPO, Premier and
    out-of-network figures side by side, and the sheet picks among them.
    """
    from .compare import _compare
    from .vocabulary import _norm_id, _num_date

    issues: list[str] = []
    fields = sabrina_parsed.get("fields") or {}
    patient = _mo_patient(portal_raw)
    group = ((((portal_raw or {}).get("metlife_data") or {}).get("plan_details") or {})
             .get("group_number"))

    sab_name, por_name = fields.get("patient_name"), patient.get("name")
    if _blank(sab_name) or _blank(por_name) or _compare("name", sab_name, por_name)[0] is not True:
        issues.append(f"patient name mismatch ({sab_name!r} vs {por_name!r})")

    sab_dob, por_dob = _num_date(fields.get("patient_dob")), _num_date(patient.get("dob"))
    if not sab_dob or not por_dob or sab_dob != por_dob:
        issues.append(f"DOB mismatch ({fields.get('patient_dob')!r} vs {patient.get('dob')!r})")

    sab_elig, por_elig = sabrina_parsed.get("eligibility"), _mo_eligibility(portal_raw)
    if not por_elig or (sab_elig and sab_elig != por_elig):
        issues.append(f"eligibility mismatch ({sab_elig!r} vs {por_elig!r})")

    sab_group, por_group = _norm_id(fields.get("group_number")), _norm_id(group)
    if not sab_group or not por_group or sab_group != por_group:
        issues.append(f"group number mismatch ({fields.get('group_number')!r} vs {group!r})")

    return not issues, issues
