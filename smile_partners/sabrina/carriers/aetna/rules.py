"""
Aetna, as this sheet needs it.

Aetna's export is recognized and translated by `portals/aetna.py`. What is
here is the sheet-specific part:

  * The sheet's In Network field picks which network's benefits the audit
    reads: "Out" reads the export's out_of_network tables, anything else
    reads in_network.
  * OON Benefits is Yes when any Maximums, Deductibles, Co-Insurance or
    Service Level Benefits table is labelled "Out of Network" or "In and Out
    of Network", even if its codes are all Not Covered.
  * The In Network field itself is not checked: the portal does not say
    whether this office is in network for the patient.
"""

from __future__ import annotations

import re

from shared.portals.aetna import (
    _aetna_code_pct,
    _aetna_export,
    _aetna_frequency,
    _aetna_history_dates,
    _aetna_is_medicare_export,
    _aetna_network_view,
    _aetna_remarks,
    _aetna_row,
    _aetna_row_covered,
    _aetna_row_shared_codes,
    _aetna_row_states_nothing,
    _aetna_rows,
    _is_aetna_portal,
)

from .vocabulary import _norm_network


# The tables whose network label decides OON Benefits. A Service Level
# Benefits table labelled Out of Network counts even when every code in it
# is Not Covered.
_OON_TABLES = ("maximums", "deductibles", "co_insurance", "service_level_benefits")


def _aetna_sheet_network(sab_fields: dict) -> str:
    """'out' when the sheet's In Network field says Out, otherwise 'in'."""
    return "out" if _norm_network((sab_fields or {}).get("in_network")) == "OUT" else "in"


def _aetna_portal_for_sheet(portal_raw: dict, sab_fields: dict) -> dict:
    """
    The export with the network the sheet names lifted to the top level, so
    every reader downstream sees only that network's benefits. Anything that
    is not an Aetna export with network buckets passes through unchanged.
    """
    raw = _aetna_export(portal_raw)
    if raw is None:
        return portal_raw
    view = _aetna_network_view(raw, _aetna_sheet_network(sab_fields))
    if raw is portal_raw:
        return view
    # Wrapped by the extension: swap the inner export, keep the wrapper.
    wrapped = dict(portal_raw)
    for key in ("aetna_data", "portal_data"):
        if wrapped.get(key) is raw:
            wrapped[key] = view
    return wrapped


def _aetna_oon_benefits(portal_raw: dict) -> str | None:
    """
    Yes when any Maximums, Deductibles, Co-Insurance or Service Level
    Benefits table is labelled "Out of Network" or "In and Out of Network"
    (even if every code in it is Not Covered); No when they are all
    "In Network" only. None when the export is not Aetna's or has no such
    tables at all.
    """
    raw = _aetna_export(portal_raw)
    if raw is None:
        return None
    seen = False
    for bucket_name in ("in_network", "out_of_network"):
        bucket = raw.get(bucket_name) or {}
        for table in _OON_TABLES:
            for row in bucket.get(table) or []:
                if not isinstance(row, dict):
                    continue
                seen = True
                if str(row.get("source") or "").lower() in ("out", "in_and_out"):
                    return "Yes"
    return "No" if seen else None


def _aetna_in_network_unverifiable(portal_raw: dict) -> bool:
    """
    True for an Aetna export: the portal lists the plan's networks but never
    says whether this office is in one of them, so the sheet's In Network
    field cannot be checked against it.
    """
    if not isinstance(portal_raw, dict):
        return False
    for candidate in (portal_raw, portal_raw.get("aetna_data"),
                      portal_raw.get("portal_data"), portal_raw.get("_raw_export")):
        if isinstance(candidate, dict) and _is_aetna_portal(candidate):
            return True
    return str(portal_raw.get("_source_insurer", "")).lower() == "aetna"


# Business rules (Smile Partners, Aetna):
#   Deductible Applies to Preventative  <- D1110's message
#   Deductible Applies to Diagnostic    <- D0120's message
# Yes only when the message says the deductible applies ("DEDUCTIBLE
# APPLIES"). "DEDUCTIBLE DOES NOT APPLY", or no deductible wording at all,
# means No.
_DED_CLASS_CODE = {
    "ded_prev": "D1110",
    "ded_diag": "D0120",
}


# Are Posterior Composites Downgraded To Amalgam? <- D2391 carries
# "ALTERNATE BENEFITS MAY APPLY".
_COMPOSITE_CODE = "D2391"


def _aetna_deductible_applies(portal_raw: dict, code: str) -> str | None:
    """
    Yes when the code's message says the deductible applies, No otherwise
    (DEDUCTIBLE DOES NOT APPLY, or nothing said). None when the code is not
    on the page.
    """
    row = _aetna_row(portal_raw, code)
    if not row:
        return None
    message = str(row.get("message") or "").lower()
    if re.search(r"deductible\s+(?:does\s+)?not\s+appl", message):
        return "No"
    if re.search(r"deductible\s+(?:does\s+|will\s+)?appl(?:y|ies)", message):
        return "Yes"
    return "No"


def _aetna_is_medicare(raw: dict) -> bool:
    """A Medicare plan: the payer's Description or Comments say Medicare."""
    return _aetna_is_medicare_export(raw)


_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _aetna_contract_year_start(plan_begin) -> str | None:
    """
    The month a Contract Year starts: Plan Begin's month, whatever the day
    (MM/DD/YYYY). 05/01/2021 -> May, 05/30/2021 -> May.
    """
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", str(plan_begin or ""))
    if not m:
        return None
    month = int(m.group(1))
    if not 1 <= month <= 12:
        return None
    return _MONTHS[month - 1]


def _aetna_breakdown_for_sheet(bd: dict, portal_norm: dict) -> dict:
    """
    Answers the sheet reads straight off the breakdown, set from what the
    Aetna page actually states. Only fills what it can prove; a value it
    cannot settle keeps whatever the breakdown already had.
    """
    if _aetna_export(portal_norm) is None:
        return bd
    bd = dict(bd)

    # Plan year: ClaimConnect's Plan Begin is when coverage started (Emma:
    # 09/29/2026), not when the benefit year resets. The Maximums and
    # Deductibles tables say "Calendar Year" when it resets in January.
    messages = " ".join(str(r.get("message") or "")
                        for table in ("maximums", "deductibles")
                        for r in _aetna_rows(portal_norm, table)).lower()
    if "calendar year" in messages:
        bd["plan_year_start"] = "January"
    elif "contract year" in messages:
        # Contract Year: the year starts in Plan Begin's month, as is
        # (05/30/2021 -> May).
        month = _aetna_contract_year_start((_aetna_export(portal_norm) or {}).get("dates", {}).get("plan_begin"))
        if month:
            bd["plan_year_start"] = month

    for key, code in _DED_CLASS_CODE.items():
        answer = _aetna_deductible_applies(portal_norm, code)
        if answer:
            bd[key] = answer

    # A downgrade question can only be answered from a row that says
    # something; a row with nothing but a waiting period leaves it unknown.
    crown = _aetna_row(portal_norm, "D2740")
    if _aetna_row_states_nothing(crown):
        bd["porcelain_posterior_downgrade"] = ""

    composite = _aetna_row(portal_norm, _COMPOSITE_CODE)
    if _aetna_row_states_nothing(composite):
        bd["posterior_composite_downgrade"] = ""
    elif composite:
        bd["posterior_composite_downgrade"] = (
            "Yes" if "alternate benefits may apply" in str(composite.get("message") or "").lower()
            else "No")

    # D0120 Preventative / D2160 Basic / D2740 Major: the percentage on that
    # code's own row (D0120, D2160, D2740), for every plan. The Co-Insurance
    # table's class percentage is used only when the code is not on the page.
    # A code marked Not Covered pays 0%, which is how the sheet writes it.
    for key, code in (("pct_prev", "D0120"), ("pct_basic", "D2160"), ("pct_major", "D2740")):
        row = _aetna_row(portal_norm, code)
        pct = _aetna_code_pct(row)
        if pct:
            bd[key] = pct
        elif row and "not covered" in " ".join(
                str(row.get(k) or "") for k in ("message", "percentage_copay")).lower():
            bd[key] = "0%"

    # Does Missing Tooth Clause Apply? Yes when the Plan Level Remarks say
    # "MISSING TOOTH CLAUSE APPLIES", otherwise No. (The New Plan PDF prints
    # "-" when it is not stated; the sheet always answers Yes or No.)
    bd["missing_tooth"] = "Yes" if "missing tooth clause applies" in _aetna_remarks(portal_norm) else "No"

    # Is there a Waiting Period? Yes when any code carries one (a waiting
    # period column such as "12 months"; extension 10/2026+).
    if any(str(r.get("waiting_period") or "").strip()
           for r in _aetna_rows(portal_norm, "service_level_benefits")):
        bd["waiting_period"] = "Yes"
    return bd


def _aetna_ortho_age(portal_raw: dict) -> str | None:
    """
    The ortho age limit as the page states it ("Maximum Age: 99" -> "99").
    The shared reader blanks 99 for the New Plan PDF; the sheet records it.
    """
    if _aetna_export(portal_raw) is None:
        return None
    for code in ("D8080", "D8090", "D8010"):
        row = _aetna_row(portal_raw, code)
        if not row or not _aetna_row_covered(row):
            continue
        m = re.search(r"(\d{1,3})", str(row.get("age_limit") or ""))
        if m:
            return m.group(1)
    return None


# Codes whose history always counts for each other, whatever the Message
# column says (Smile Partners rule).
_HISTORY_ALWAYS_SHARED = {
    "D1110": ("D1120",),
    "D1120": ("D1110",),
    "D0274": ("D0270", "D0272"),
    "D0272": ("D0270", "D0274"),
    "D0270": ("D0272", "D0274"),
}


def _aetna_history(portal_raw: dict, code: str) -> str | None:
    """
    The code's service history, counting every code it shares a frequency
    with: the ones its Message column lists, plus the fixed pairs (D1110 =
    D1120; D0274 = D0272 = D0270). Dates joined by newlines, or NH when none
    of them was ever paid. None when the code is not on the page or is not
    covered (no history to state).
    """
    row = _aetna_row(portal_raw, code)
    if not row or not _aetna_row_covered(row):
        return None
    related = {code.upper()} | _aetna_row_shared_codes(row) | set(_HISTORY_ALWAYS_SHARED.get(code.upper(), ()))
    dates: list[str] = []
    for other in sorted(related):
        for d in _aetna_history_dates(_aetna_row(portal_raw, other)):
            if d not in dates:
                dates.append(d)
    return "\n".join(dates) if dates else "NH"


def _aetna_not_covered_row(portal_raw: dict, codes) -> dict | None:
    """The first of `codes` whose service row Aetna marks "Not Covered", if any."""
    for code in codes:
        row = _aetna_row(portal_raw, str(code))
        if row:
            said = " ".join(str(row.get(k) or "") for k in ("percentage_copay", "message"))
            return row if re.search(r"not\s+covered", said, re.IGNORECASE) else None
    return None


def _aetna_not_covered_value(portal_raw: dict, codes, what: str, sab_raw=None):
    """
    Age limit and history for a code Aetna marks "Not Covered" (agreed with
    the team, 2026-10-29).

    The page gives such a code "N/A" for both, and the sheet records it as age
    0 and history NH — Jerry Porter's D1206 / D1208 / D1351 / D1510 and his
    ortho codes. Age reads 0 (a blank sheet age is also right, and is left with
    nothing to compare); history reads "—", the same as the sheet's NH.

    Returns (handled, value).
    """
    if _aetna_export(portal_raw) is None or not _aetna_not_covered_row(portal_raw, codes):
        return False, None
    if what == "late_date_of_service":
        return True, "—"
    if what == "age_limit":
        return True, (None if str(sab_raw or "").strip() in ("", "-", "—") else "0")
    return False, None


def _aetna_code_override(field: dict, value, bd: dict, portal_raw: dict,
                         codes: tuple[str, ...], what: str, sab_raw=None):
    """
    Correct a per-code value the way this sheet records it. Returns
    (handled, value), the same contract as the Cigna override.

    Frequency: Aetna words it "2 Units, for 1 Calendar Year"; the sheet writes
    "2X1Year". Rows with no limit or not covered keep the shared reading.

    History: the code's own paid dates plus those of every code it shares a
    frequency with (see _aetna_history).
    """
    if not codes or _aetna_export(portal_raw) is None:
        return False, value
    handled, not_covered = _aetna_not_covered_value(portal_raw, codes, what, sab_raw)
    if handled:
        return True, not_covered
    if what == "late_date_of_service":
        for code in codes:
            if _aetna_row(portal_raw, str(code)):
                history = _aetna_history(portal_raw, str(code))
                return (True, history) if history else (False, value)
        return False, value
    if what != "frequency_limit":
        return False, value
    for code in codes:
        row = _aetna_row(portal_raw, str(code))
        if not row:
            continue
        if _aetna_row_states_nothing(row):
            return True, None          # portal silent on this code
        compact = _aetna_frequency(row.get("frequency"))
        return (True, compact) if compact else (False, value)
    return False, value


_BLANK_AMOUNTS = {"", "-", "\u2014", "\u2013", "n/a", "na", "none"}


def _aetna_field_override(field: dict, value, portal_raw: dict, sab_raw=None):
    """
    Final say on a field's portal-side value:

      * In Network: the portal never says, so it shows what the sheet says
        (In or Out). The sheet's answer is what picks the in- or
        out-of-network benefits.
      * Dollar amounts the portal does not state show as 0, the way the
        sheet writes them, instead of a blank.

    Anything else passes through unchanged.
    """
    if _aetna_export(portal_raw) is None:
        return value
    if field.get("key") == "in_network":
        sheet = _norm_network(sab_raw)
        if sheet == "OUT":
            return "Out"
        if sheet == "IN":
            return "In"
        return value
    if field.get("key") == "group_number":
        # Medicare plans: the sheet's Group Number is the portal's Plan#
        # (000003-GA000081), not its Group# (000003-GA).
        raw = _aetna_export(portal_raw) or {}
        if _aetna_is_medicare(raw):
            plan_no = str((raw.get("payer") or {}).get("plan#")
                          or (raw.get("coverage_details") or {}).get("plan_number") or "").strip()
            if plan_no and plan_no.upper() != "N/A":
                return plan_no
        return value
    # Ortho Coverage / D8090: some plans leave the percentage off the ortho
    # rows and give it in the Co-Insurance table instead ("Major,Ortho 50% /
    # 50%"). Use that when the rows have none and are not Not Covered.
    src = field.get("portal")
    if (isinstance(src, tuple) and src and src[0] == "code"
            and any(str(c).upper().startswith("D80") for c in src[1:])
            and (value is None or str(value).strip() in ("", "-", "\u2014"))):
        rows = [r for r in (_aetna_row(portal_raw, str(c)) for c in src[1:]) if r]
        if rows and not any("not covered" in str(r.get("message") or "").lower() for r in rows):
            for r in _aetna_rows(portal_raw, "co_insurance"):
                if "ortho" in str(r.get("type") or "").lower():
                    m = re.search(r"(\d+)\s*%\s*/\s*(\d+)\s*%", str(r.get("percentage") or ""))
                    if m:
                        return f"{int(m.group(2))}%"
    if field.get("kind") == "money":
        if value is None or str(value).strip().lower() in _BLANK_AMOUNTS:
            return "0"
    return value