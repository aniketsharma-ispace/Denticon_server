"""
Turning a stated value into something comparable.

Both sides say the same thing in different words — "2X1Year" against "2 TIMES
IN 1 CALENDAR YEAR", "$1,500.00" against "1500". Each reader here reduces one
kind of value to a canonical form, and returns None when the value states
nothing at all, which is what keeps a silence from being read as a
disagreement.
"""

from __future__ import annotations

import re
from .common import _BLANKS, _UNLIMITED_MAX


# Sabrina writes "NH" (no history) where a procedure has never been performed.
_HISTORY_NONE = {"nh", "no history", "none", "n/h"}


# ══════════════════════════════════════════════════════════════════════════════
#  VALUE NORMALIZERS
# ══════════════════════════════════════════════════════════════════════════════

def _blank(v) -> bool:
    return v is None or str(v).strip().lower() in _BLANKS


def _blank_for(kind: str, v) -> bool:
    """
    Blankness, judged for the kind of field being read.

    "Not Applicable" means "nothing here" for most fields but is a real
    statement for a frequency — Cigna writes it where a procedure carries no
    frequency limit, which is what the sheet calls "No Frequency".
    """
    if kind == "frequency" and v is not None:
        if str(v).strip().lower() in _FREQ_NO_LIMIT_WORDS:
            return False
    if kind == "history" and v is not None:
        # "NH" and the portal's dash both say "never performed".
        text = str(v).strip()
        if text.lower() in _HISTORY_NONE or text in _HISTORY_DASHES:
            return False
    return _blank(v)


def _num_money(v) -> float | None:
    if _blank(v):
        return None
    s = str(v)
    if "unlimited" in s.lower() or "no max" in s.lower():
        return _UNLIMITED_MAX
    m = re.search(r"-?[\d,]*\.?\d+", s.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _num_pct(v) -> float | None:
    """
    Coverage percentage. Handles '80%', '80', 'Not Covered' → 0,
    and a bare fraction ('0.8') which some exports use.
    """
    if _blank(v):
        return None
    s = str(v).strip().lower()
    if "not covered" in s or s in ("nc", "not a covered benefit", "excluded"):
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    if m:
        return float(m.group(1))
    m = re.search(r"^(\d+(?:\.\d+)?)$", s)
    if m:
        val = float(m.group(1))
        # A bare "0.8" means 80% — a coverage level is never 0.8%.
        return val * 100 if 0 < val <= 1 else val
    # "Covered" with no number states coverage but not the level → not comparable
    return None


# Sabrina states network status as the bare word "In" / "Out".
_YES = {"y", "yes", "true", "t", "x", "✓", "applies", "covered", "included",
        "in", "in network", "in-network", "par", "participating", "available"}


_NO = {"n", "no", "false", "f", "does not apply", "not applicable", "excluded",
       "not covered", "out", "oon", "out of network", "out-of-network",
       "non-par", "nonpar", "not included", "not available"}


def _num_yesno(v) -> str | None:
    if _blank(v):
        return None
    s = re.sub(r"[.\s]+$", "", str(v).strip().lower())
    if s in _YES:
        return "YES"
    if s in _NO:
        return "NO"
    # Leading token wins for values like "Yes - 12 months" / "No (waived)"
    head = re.split(r"[ ,;(\-–—/]", s, 1)[0]
    if head in _YES:
        return "YES"
    if head in _NO:
        return "NO"
    return None


_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y-%m-%d",
                 "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y",
                 "%d %b %Y", "%d %B %Y", "%m/%Y", "%m%d%Y")


def _num_date(v) -> str | None:
    """Normalize to MM/DD/YYYY so 1/8/2026, 01/08/26 and Jan 08, 2026 agree."""
    if _blank(v):
        return None
    import datetime
    s = str(v).strip()
    m = re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}"
                  r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}", s)
    if m:
        s = m.group(0).replace(".", "")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return None


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _num_month(v) -> int | None:
    """
    Plan-year start month → 1-12. Accepts 'January', 'Jan', '1', '01/2026',
    and a full date (whose month is what matters here).
    """
    if _blank(v):
        return None
    s = str(v).strip().lower()
    for name, num in _MONTHS.items():
        if s.startswith(name):
            return num
    m = re.match(r"^(\d{1,2})\b", s)
    if m:
        num = int(m.group(1))
        return num if 1 <= num <= 12 else None
    return None


# Three or more repeated mask characters — enough to distinguish a masked
# identifier from a real one that merely contains an X.
_MASK_RE = re.compile(r"(?:X{3,}|\*{3,}|•{3,}|#{3,})", re.IGNORECASE)


def _visible_part(value: str) -> tuple[str, str] | None:
    """
    For a partially masked identifier, what the mask leaves readable:
    ("suffix", "6200") for "XXXXXXX6200", ("prefix", "8339") for "8339XXXXX".

    None when nothing can be aligned — masked in the middle, or masked end to
    end. Masks do not preserve length ("XXXXXXX6200" is 11 characters for a
    9-character id), so the visible run is compared, not the position.
    """
    m = _MASK_RE.search(value)
    if not m:
        return None
    before, after = value[:m.start()], value[m.end():]
    if before and after:
        return None                      # masked in the middle
    if after:
        return "suffix", after
    if before:
        return "prefix", before
    return None                          # nothing visible at all


# Frequency, as the two systems say it:
#   Sabrina  "2X1Year"  "1X60Months"  "1XLifetime"  "No Frequency"  "NC"
#   portal   "2 TIMES IN 1 CALENDAR YEAR"  "1 TIME IN 60 MONTHS"
#            "ONCE PER LIFETIME"  "No Limitations"  "*NOT COVERED"
# Both reduce to (how many, per how many months). A year is normalized to 12
# months so "1X1Year" and "1 TIME IN 1 CALENDAR YEAR" agree; the portal often
# appends conditions ("…, PERMANENT MOLARS ONLY") which are ignored.
_FREQ_UNLIMITED = ("unlimited",)


_FREQ_NOT_COVERED = ("not covered",)


# Neither a cap nor an absence of one: the benefit is decided case by case on
# the evidence submitted. The sheet writes "Pre-D"; Delta Dental states it as
# "Benefit is based on professional determination".
_FREQ_PREDETERMINATION = ("predetermination",)


_FREQ_COMPACT_RE = re.compile(
    r"^(\d+)\s*x\s*(\d*)\s*(year|month|week|day|visit)s?$", re.IGNORECASE)


# Cigna spells small counts out ("Twice Per Calendar Year", "Four Times Per
# Calendar Year") as often as it uses digits.
_FREQ_WORD_COUNTS = {
    "once": 1, "twice": 2, "thrice": 3, "one": 1, "two": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


_FREQ_PROSE_RE = re.compile(
    r"^(?:(\d+)|once|twice|thrice|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*(?:times?)?\s*(?:in|per|every)\s*(\d*)\s*"
    r"(?:calendar\s*|contract\s*|plan\s*|benefit\s*|consecutive\s*|"
    r"rolling\s*|successive\s*)*(year|month|week|day)s?",
    re.IGNORECASE)


# A frequency can carry more than one clause, split by who it applies to:
#   "2 EVERY 1 CALENDAR YEAR(S) FOR PARTICIPANT TO AGE 19,
#    1 EVERY 1 CALENDAR YEAR(S) FOR ADULTS"
# Each clause begins with its own count, which is what separates them from the
# trailing conditions the portal also appends ("…, PERMANENT MOLARS ONLY").
_FREQ_CLAUSE_SPLIT = re.compile(r",\s*(?=(?:\d+|once|twice)\b)", re.IGNORECASE)


def _clause_age_range(clause: str) -> tuple[int, int] | None:
    """The age band a frequency clause applies to, or None if unqualified."""
    s = clause.lower()
    m = re.search(r"(?:to|thru|through|under|up to)\s+age\s+(\d{1,3})", s)
    if m:
        return 0, int(m.group(1))
    m = re.search(r"age\s+(\d{1,3})\s*(?:and\s*(?:over|older|above)|\+)", s)
    if m:
        return int(m.group(1)), 999
    m = re.search(r"(?:over|above)\s+age\s+(\d{1,3})", s)
    if m:
        return int(m.group(1)) + 1, 999
    m = re.search(r"exclude[sd]?\s+after\s+age\s+(\d{1,3})", s)
    if m:
        return 0, int(m.group(1))
    if re.search(r"\badults?\b", s):
        return 18, 999
    if re.search(r"\b(?:child|children|dependent children)\b", s):
        return 0, 18
    return None


def _select_frequency_clause(value: str, age: int | None) -> tuple[str, str]:
    """
    Pick the clause that governs, returning (clause, why).

    With the patient's age known the matching band wins, and the narrowest band
    wins when several match. Without an age the most restrictive clause governs
    — fewest visits allowed — which is the safe reading of a plan stating more
    than one rule.
    """
    clauses = [c.strip() for c in _FREQ_CLAUSE_SPLIT.split(str(value)) if c.strip()]
    if len(clauses) < 2:
        return str(value), ""

    banded = [(c, _clause_age_range(c)) for c in clauses]

    if age is not None:
        hits = [(c, band) for c, band in banded
                if band and band[0] <= age <= band[1]]
        if hits:
            clause, band = min(hits, key=lambda cb: cb[1][1] - cb[1][0])
            return clause, f"patient is {age}; applied the clause for ages {band[0]}-{band[1]}"
        unqualified = [c for c, band in banded if band is None]
        if unqualified:
            return unqualified[0], ""

    rated = []
    for clause, _band in banded:
        parsed = _parse_single_frequency(clause)
        if parsed and len(parsed) == 2 and isinstance(parsed[0], int):
            count, span = parsed
            months = 1 if span == "lifetime" else max(int(span), 1)
            rated.append((count / months, clause))
    if rated:
        clause = min(rated)[1]
        return clause, "plan states several limits; applied the most restrictive"
    return clauses[0], ""


# Wordings that state "there is no frequency limit". These have to be tested
# before the blank check, because "Not Applicable" — how Cigna words exactly
# this — also appears in the blank-value vocabulary used everywhere else.
_FREQ_NO_LIMIT_WORDS = {
    "not applicable", "n/a", "na", "no frequency", "no limitation",
    "no limitations", "unlimited", "none",
    "frequency not available",          # Sabrina's newer wording of "No Frequency"
}


def _num_frequency(v, age: int | None = None) -> tuple | None:
    if v is not None and str(v).strip().lower() in _FREQ_NO_LIMIT_WORDS:
        return _FREQ_UNLIMITED
    if _blank(v):
        return None
    chosen, _why = _select_frequency_clause(str(v), age)
    return _parse_single_frequency(chosen)


def _frequency_note(v, age: int | None = None) -> str:
    """Why a particular clause was chosen, for the reviewer."""
    if _blank(v):
        return ""
    return _select_frequency_clause(str(v), age)[1]


def _parse_single_frequency(v) -> tuple | None:
    if _blank(v):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip().lower().lstrip("*")
    # Cigna words this "No benefits for this service"; the normalizer usually
    # shortens it to "NOT COVERED", but accept both so either can be compared.
    if ("not covered" in s or "no benefits" in s or "not a covered" in s
            or s in ("nc", "n/c")):
        return _FREQ_NOT_COVERED
    # "Not Applicable" is how Cigna states a procedure with no frequency
    # limit; the sheet writes "No Frequency" for the same thing.
    if ("no limitation" in s or "no frequency" in s or "unlimited" in s
            or "frequency not available" in s
            or s in ("not applicable", "n/a", "na")):
        return _FREQ_UNLIMITED
    # A benefit decided case by case rather than capped — the sheet's "Pre-D"
    # against the portal's "Benefit is based on professional determination".
    if ("professional determination" in s or "predetermination" in s
            or re.fullmatch(r"pre[\s-]?d", s)):
        return _FREQ_PREDETERMINATION
    if "lifetime" in s:
        m = re.match(r"(\d+)\s*x", s)
        return (int(m.group(1)) if m else 1, "lifetime")
    m = _FREQ_COMPACT_RE.match(s)
    if not m:
        m = _FREQ_PROSE_RE.match(s)
        if m:
            if m.group(1):
                count = int(m.group(1))
            else:
                word = s.split()[0]
                count = _FREQ_WORD_COUNTS.get(word, 1)
            span = int(m.group(2) or 1)
            unit = m.group(3).lower()
            return (count, span * 12 if unit == "year" else span)
        return None
    count = int(m.group(1))
    span = int(m.group(2) or 1)
    unit = m.group(3).lower()
    return (count, span * 12 if unit == "year" else span)


def _num_agelimit(v) -> int | None:
    """
    Upper age bound. Sabrina states a single number ("14"); the portal states a
    range ("0-14"), so both reduce to the ceiling.
    """
    if _blank(v):
        return None
    s = str(v).strip()
    m = re.fullmatch(r"\s*(\d{1,3})\s*[-–]\s*(\d{1,3})\s*", s)
    if m:
        return int(m.group(2))
    m = re.fullmatch(r"\s*(\d{1,3})\s*", s)
    if m:
        return int(m.group(1))
    # Cigna: "Exclude after age 18" is an upper bound of 18.
    m = re.search(r"exclude[sd]?\s+after\s+age\s+(\d{1,3})", s, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if re.search(r"\d{1,3}\s*(?:and\s*(?:up|over|older)|\+)", s, re.IGNORECASE):
        return 99
    if "no age limit" in s.lower() or "none" in s.lower():
        return 99
    return None


def _agelimit_lower(v) -> int | None:
    """Lower bound of a portal age range; None when it states only a ceiling."""
    m = re.fullmatch(r"\s*(\d{1,3})\s*[-–]\s*(\d{1,3})\s*", str(v or ""))
    return int(m.group(1)) if m else None


def _blank_means_no_limit(kind: str, portal_value) -> bool:
    """
    Whether an EMPTY Frequency / Age Limit cell agrees with the portal.

    Sabrina leaves these cells blank to say "no limit", which is exactly what
    the portal says as "No Limitations" or as the full 0-99 age span. Counting
    those blanks as gaps buries the real findings under ~30 rows of noise.

    A blank is only agreement when the portal states no limit either. A real
    restriction the sheet failed to record — "1 TIME IN 1 CALENDAR YEAR", or an
    age range with a floor such as 14-99 — stays reported.
    """
    if kind == "frequency":
        return _num_frequency(portal_value) == _FREQ_UNLIMITED
    if kind == "agelimit":
        ceiling = _num_agelimit(portal_value)
        return (ceiling is not None and ceiling >= 99
                and _agelimit_lower(portal_value) in (0, None))
    if kind == "history":
        # An empty History cell says "never performed", which is exactly what
        # the portal's "NH" / "No history on file" says.
        return _num_history(portal_value) == "NONE"
    return False


# The portal prints a dash in Late Date Of Service where a procedure has never
# been performed — the same statement the sheet writes as "NH". It is only a
# placeholder elsewhere, so it is read that way here and nowhere else.
_HISTORY_DASHES = {"-", "--", "---", "\u2014", "\u2013"}


def _history_dates(v) -> frozenset | None:
    """
    Every service date a history value states.

    A portal may list several ("03/24/2026, 08/15/2025") where the sheet lists
    an overlapping set, so the comparison works on sets rather than on one date.
    An empty set is the positive statement "never performed"; None means nothing
    was stated at all.
    """
    if v is None:
        return None
    text = str(v).strip()
    if not text:
        return None
    if text.lower() in _HISTORY_NONE or text in _HISTORY_DASHES:
        return frozenset()
    found = re.findall(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text)
    dates = {d for d in (_num_date(x) for x in found) if d}
    return frozenset(dates) if dates else None


def _num_history(v) -> str | None:
    """Last date of service, or the sentinel NONE for "NH" and the portal dash."""
    if v is not None:
        text = str(v).strip()
        if text.lower() in _HISTORY_NONE or text in _HISTORY_DASHES:
            return "NONE"
    if _blank(v):
        return None
    return _num_date(v)


def _norm_network(v) -> str | None:
    """A network type — IN or OUT — from either system's wording."""
    if _blank(v):
        return None
    s = re.sub(r"\s+", " ", str(v).strip().lower())
    if ("out of network" in s or "out-of-network" in s or "oon" in s
            or "non-par" in s or "nonpar" in s or s == "out"):
        return "OUT"
    if ("in network" in s or "in-network" in s or s in ("in", "par")
            or "participating" in s or "ppo" in s or "premier" in s
            or "hmo" in s or "epo" in s):
        return "IN"
    return {"YES": "IN", "NO": "OUT"}.get(_num_yesno(v))


def _norm_id(v) -> str | None:
    """IDs compare on alphanumerics only — '12345-01' vs '1234501'."""
    if _blank(v):
        return None
    s = re.sub(r"[^A-Z0-9]", "", str(v).upper())
    return s or None


def _norm_text(v) -> str | None:
    if _blank(v):
        return None
    s = re.sub(r"[^A-Z0-9 ]", " ", str(v).upper())
    # A number run into its unit is the same answer: the sheet's "30days" is
    # the portal's "30 Days" (When Is First Perio Maintenance Allowed After SRP).
    s = re.sub(r"(\d)([A-Z])", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


# Carrier brands, so "Metlife PDP+" and "(IN) MetLife(TX)- PO Box 981282- 79998"
# are recognized as the same insurer. Longest first so "united concordia" wins
# over "concordia" and "delta dental" over "delta".
_CARRIER_BRANDS = (
    "united concordia", "delta dental", "blue cross", "blue shield",
    "mutual of omaha", "physicians mutual", "sun life", "guardian",
    "metlife", "cigna", "aetna", "dentaquest", "ameritas", "principal",
    "humana", "anthem", "careington", "solstice", "dominion", "liberty",
    "geha", "tricare", "unum", "lincoln", "dnoa", "concordia", "renaissance",
    "assurant", "premera", "regence", "wellpoint",
)


def _carrier_brand(v) -> str | None:
    """The carrier brand named in a value, if any."""
    if _blank(v):
        return None
    s = re.sub(r"[^a-z ]", " ", str(v).lower())
    s = re.sub(r"\s+", " ", s)
    for brand in _CARRIER_BRANDS:
        if brand in s:
            return brand
    return None


_NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV", "MD", "DDS", "DMD"}


def _norm_name(v) -> tuple[str, ...] | None:
    """
    Name → sorted significant tokens, so 'LAST, FIRST' (Sabrina/Denticon style)
    and 'First Last' (portal style) compare equal. Middle initials and
    generational suffixes are dropped: they differ between systems constantly
    and are never the point of an audit.
    """
    if _blank(v):
        return None
    s = re.sub(r"[^A-Z ,]", " ", str(v).upper()).replace(",", " ")
    tokens = [t for t in s.split() if len(t) > 1 and t not in _NAME_SUFFIXES]
    return tuple(sorted(tokens)) or None


def _addr_tokens(v) -> set[str] | None:
    """Address → token set, with the usual postal abbreviations unified."""
    if _blank(v):
        return None
    s = _norm_text(v) or ""
    repl = {
        "POBOX": "PO BOX", "P O BOX": "PO BOX",
        "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "DRIVE": "DR",
        "SUITE": "STE", "BOULEVARD": "BLVD", "NORTH": "N", "SOUTH": "S",
        "EAST": "E", "WEST": "W",
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    tokens = {t for t in s.split() if t}
    return tokens or None


def _coalesce_keys(obj: dict, *keys):
    """First key present on `obj` with a non-blank value."""
    for key in keys:
        if key in obj and not _blank(obj[key]):
            return obj[key]
    return None


# How a plan coordinates with other coverage.
#
# The two systems word the same method differently — the sheet says
# "Non-Duplicate", the portal says "Non-duplication of benefits applies" — so
# both sides are reduced to a method before comparing. MetLife also mixes the
# order-of-benefits rule into the same sentence ("Birthday rule, Non-duplication
# of benefits applies."); only the method is comparable, and "Birthday rule" is
# not one.
#
# Ranked least to most restrictive. Where a plan states more than one method the
# MOST RESTRICTIVE governs, because that is the one that actually limits payment.
_COB_METHODS = (
    ("Standard", 1, ("regular cob", "standard cob", "traditional cob",
                     "full cob", "traditional", "standard")),
    ("Maintenance of Benefits", 2, ("maintenance of benefits", "mob")),
    ("Non-Duplication", 3, ("non-duplication", "nonduplication", "non duplication",
                            "non-duplicate", "nonduplicate", "non duplicate",
                            "non-dup", "non dup")),
    ("Carve Out", 4, ("carve out", "carve-out", "carveout")),
)


def _num_cob(v) -> tuple[int, str] | None:
    """
    The coordination method a value names, as (restrictiveness, label).

    None when nothing recognizable is named, so an unfamiliar wording is
    reported as not comparable rather than quietly passed or failed.
    """
    if _blank(v):
        return None
    s = re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", str(v).lower()))
    best = None
    for label, rank, needles in _COB_METHODS:
        if any(needle in s for needle in needles):
            if best is None or rank > best[0]:
                best = (rank, label)
    return best