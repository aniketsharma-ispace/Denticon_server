"""
Aetna, as this sheet needs it.

Aetna's export is recognized and translated by `portals/aetna.py`. What is
here is the sheet-specific part:

  * The sheet's In Network field picks which network's benefits the audit
    reads: "Out" reads the export's out_of_network tables, anything else
    reads in_network.
  * OON Benefits is Yes when any Maximums, Deductibles or Co-Insurance table
    is labelled "Out of Network" or "In and Out of Network".
  * The In Network field itself is not checked: the portal does not say
    whether this office is in network for the patient.
"""

from __future__ import annotations

import re

from ..vocabulary import _norm_network


# The tables whose network label decides OON Benefits. Service Level
# Benefits do not count.
_OON_TABLES = ("maximums", "deductibles", "co_insurance")


def _aetna_export(portal_raw: dict) -> dict | None:
    """The raw Aetna export with network buckets, bare or wrapped."""
    from ...portals.aetna import _aetna_has_network_buckets, _is_aetna_portal

    if not isinstance(portal_raw, dict):
        return None
    for candidate in (portal_raw, portal_raw.get("aetna_data"),
                      portal_raw.get("portal_data"), portal_raw.get("_raw_export")):
        if (isinstance(candidate, dict) and _is_aetna_portal(candidate)
                and _aetna_has_network_buckets(candidate)):
            return candidate
    return None


def _aetna_sheet_network(sab_fields: dict) -> str:
    """'out' when the sheet's In Network field says Out, otherwise 'in'."""
    return "out" if _norm_network((sab_fields or {}).get("in_network")) == "OUT" else "in"


def _aetna_portal_for_sheet(portal_raw: dict, sab_fields: dict) -> dict:
    """
    The export with the network the sheet names lifted to the top level, so
    every reader downstream sees only that network's benefits. Anything that
    is not an Aetna export with network buckets passes through unchanged.
    """
    from ...portals.aetna import _aetna_network_view

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
    Yes when any Maximums, Deductibles or Co-Insurance table is labelled
    "Out of Network" or "In and Out of Network"; No when they are all
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
    from ...portals.aetna import _is_aetna_portal

    if not isinstance(portal_raw, dict):
        return False
    for candidate in (portal_raw, portal_raw.get("aetna_data"),
                      portal_raw.get("portal_data"), portal_raw.get("_raw_export")):
        if isinstance(candidate, dict) and _is_aetna_portal(candidate):
            return True
    return str(portal_raw.get("_source_insurer", "")).lower() == "aetna"


def _aetna_rows(portal_raw: dict, table: str) -> list:
    """One table's rows for the network being audited (already lifted to the top)."""
    if not isinstance(portal_raw, dict):
        return []
    for candidate in (portal_raw.get("_raw_export"), portal_raw):
        if isinstance(candidate, dict) and isinstance(candidate.get(table), list):
            return [r for r in candidate[table] if isinstance(r, dict)]
    return []


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


def _aetna_row(portal_raw: dict, code: str) -> dict | None:
    """The service row for one code, in the network being audited."""
    for row in _aetna_rows(portal_raw, "service_level_benefits"):
        if str(row.get("procedure_code") or "").strip().upper() == code.upper():
            return row
    return None


def _aetna_row_covered(row: dict) -> bool:
    return bool(re.search(r"\d+\s*%", str(row.get("percentage_copay") or ""))) and \
        "not covered" not in str(row.get("message") or "").lower()


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
    for table in ("maximums", "deductibles"):
        if any("calendar year" in str(r.get("message") or "").lower()
               for r in _aetna_rows(portal_norm, table)):
            bd["plan_year_start"] = "January"
            break

    for key, code in _DED_CLASS_CODE.items():
        answer = _aetna_deductible_applies(portal_norm, code)
        if answer:
            bd[key] = answer

    composite = _aetna_row(portal_norm, _COMPOSITE_CODE)
    if composite:
        bd["posterior_composite_downgrade"] = (
            "Yes" if "alternate benefits may apply" in str(composite.get("message") or "").lower()
            else "No")

    # Does Missing Tooth Clause Apply? Yes when the Plan Level Remarks say
    # "MISSING TOOTH CLAUSE APPLIES", otherwise No. (The New Plan PDF prints
    # "-" when it is not stated; the sheet always answers Yes or No.)
    remarks = " ".join(str(r or "") for r in (_aetna_export(portal_norm) or {}).get("plan_level_remarks") or []).lower()
    bd["missing_tooth"] = "Yes" if "missing tooth clause applies" in remarks else "No"
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


# "2 Units, for 1 Calendar Year PER FULL MOUTH."  -> 2X1Year
# "1 Unit, per 60 Months TOOTH NUMBER 01 TO 32." -> 1X60Months
# "3 Visits, for 1 Calendar Year DENTAL ..."      -> 3X1Year
# "1 Unit, for 999 Calendar Years PER FULL MOUTH." -> 1XLifetime
_AETNA_FREQ_RE = re.compile(
    r"(\d+)\s*(?:units?|visits?|times?)?\s*,?\s*(?:for|per|in|every)\s+(\d+)\s*"
    r"(?:calendar\s+|contract\s+|benefit\s+|plan\s+)?(year|month)s?",
    re.IGNORECASE)


def _aetna_frequency(text: str) -> str | None:
    """Aetna's frequency wording in the sheet's compact form, or None."""
    m = _AETNA_FREQ_RE.search(str(text or ""))
    if not m:
        return None
    count, span, unit = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if unit == "year" and span >= 99:
        return f"{count}XLifetime"
    return f"{count}X{span}Year" if unit == "year" else f"{count}X{span}Months"


# Codes whose history always counts for each other, whatever the Message
# column says (Smile Partners rule).
_HISTORY_ALWAYS_SHARED = {
    "D1110": ("D1120",),
    "D1120": ("D1110",),
    "D0274": ("D0270", "D0272"),
    "D0272": ("D0270", "D0274"),
    "D0270": ("D0272", "D0274"),
}

_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))\b")


def _aetna_shared_codes(row: dict) -> set[str]:
    """
    The codes in a row's "Shares frequency with ..." list. Ranges such as
    D2510-D2794 are expanded; words such as DEDUCTIBLE DOES NOT APPLY are
    ignored.
    """
    text = " ".join(str(row.get(k) or "") for k in ("shares_frequency_with", "message"))
    m = re.search(r"shares\s+frequency\s+with\s*(.*)", text, re.IGNORECASE)
    listed = m.group(1) if m else str(row.get("shares_frequency_with") or "")
    codes: set[str] = set()
    for a, b in re.findall(r"\b(D\d{4})(?:\s*-\s*(D\d{4}))?\b", listed, re.IGNORECASE):
        if b:
            lo, hi = sorted((int(a[1:]), int(b[1:])))
            if hi - lo <= 500:
                codes.update(f"D{n:04d}" for n in range(lo, hi + 1))
                continue
        codes.add(a.upper())
    return codes


def _aetna_history_dates(row: dict) -> list[str]:
    """Every paid date in a row's History line ("Last paid date: 02/12/26")."""
    return _DATE_RE.findall(str((row or {}).get("history") or ""))


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
    related = {code.upper()} | _aetna_shared_codes(row) | set(_HISTORY_ALWAYS_SHARED.get(code.upper(), ()))
    dates: list[str] = []
    for other in sorted(related):
        for d in _aetna_history_dates(_aetna_row(portal_raw, other)):
            if d not in dates:
                dates.append(d)
    return "\n".join(dates) if dates else "NH"


def _aetna_code_override(field: dict, value, bd: dict, portal_raw: dict,
                         codes: tuple[str, ...], what: str):
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
        compact = _aetna_frequency(row.get("frequency"))
        return (True, compact) if compact else (False, value)
    return False, value