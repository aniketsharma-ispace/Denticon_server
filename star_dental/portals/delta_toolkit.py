"""
Delta Dental Office Toolkit export adapter.

The Office Toolkit JSON is not the same export shape as the older Delta Dental
provider-portal JSON.  This module translates Toolkit's member/benefit/search
records into the canonical portal contract consumed by the existing Sabrina
comparison engine.

All derived values here are deterministic.  In particular, frequency and age
limits are taken from explicit source limitation wording; they are never
inferred from a procedure category or from another CDT code.
"""

from __future__ import annotations

import datetime
import re
from typing import Any


_WORD_COUNTS = {
    "once": 1,
    "twice": 2,
    "thrice": 3,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


# Only these code/phrase pairs may turn a source sentence into a frequency.
# This deliberately avoids category inheritance.  A sentence is usable only
# when the code is named directly or the phrase below explicitly identifies the
# procedure represented by that code.
_FREQUENCY_PHRASES: dict[str, tuple[str, ...]] = {
    "D0120": ("oral examinations",),
    "D0140": ("oral examinations",),
    "D0150": ("oral examinations",),
    "D0180": ("oral examinations",),
    "D0210": ("full mouth x-rays", "panorex"),
    "D0330": ("panorex",),
    "D0272": ("bitewing x-rays",),
    "D0274": ("bitewing x-rays",),
    "D1110": ("prophylaxes (cleanings)", "prophylaxes", "cleanings"),
    "D1120": ("prophylaxes (cleanings)", "prophylaxes", "cleanings"),
    "D1206": ("fluoride treatments",),
    "D1208": ("fluoride treatments",),
    "D1351": ("sealants",),
    "D1510": ("space maintainers",),
    "D2140": ("amalgam and composite resin restorations",),
    "D2160": ("amalgam and composite resin restorations",),
    "D2331": ("amalgam and composite resin restorations",),
    "D2391": ("amalgam and composite resin restorations",),
    "D2740": ("cast restorations", "crowns", "onlays"),
    "D2950": ("cast restorations", "cores", "substructures"),
    "D4355": ("full mouth debridement",),
    "D4341": ("root planing and scaling",),
    "D4910": ("periodontal prophylaxes", "periodontal maintenance"),
    "D5110": ("full and partial dentures", "dentures"),
    "D5212": ("full and partial dentures", "partial dentures"),
    "D5213": ("full and partial dentures", "partial dentures"),
    "D6750": ("bridgework",),
    "D6245": ("bridgework",),
    "D6010": ("implants",),
    "D9944": ("occlusal guard",),   # matches "occlusal guard" and "occlusal guards"
}


_OON_PARTICIPATION_RE = re.compile(
    r"non[\s-]?participating(?:\s+dentist)?"
    r"|does\s+not\s+participate\s+in\s+any\s+of\s+[\w' ]{0,40}?programs",
    re.IGNORECASE,
)

_NO_DEDUCTIBLE_RE = re.compile(
    r"\bthere\s+is\s+no\s+deductible\s+(?:for|on|under)\s+this\s+(?:contract|plan)\b",
    re.IGNORECASE,
)

_PREVENTIVE_TERMS_RE = re.compile(
    r"\bprevent(?:ive|ative)\b"
    r"|\bprophy\w*"
    r"|\bcleanings?\b"
    r"|\bfluoride\b"
    r"|\bsealants?\b"
    r"|\bspace\s+maint\w*"
    r"|\bx-?rays?\b"
    r"|\bradiographs?\b"
    r"|\bbitewings?\b"
    r"|\bpanorex\b|\bpanoramic\b"
    r"|\bD1\d{3}\b"
    r"|\bD02\d{2}\b|\bD0330\b",
    re.IGNORECASE,
)

_DIAGNOSTIC_TERMS_RE = re.compile(
    r"\bdiagnostic\b|\boral\s+exam\w*|\bexams?\b|\bevaluations?\b"
    r"|\bD01\d{2}\b|\bD9110\b",
    re.IGNORECASE,
)

_XRAY_TERMS_RE = re.compile(
    r"\bx-?rays?\b|\bradiographs?\b|\bbitewings?\b|\bpanorex\b|\bpanoramic\b"
    r"|\bD02\d{2}\b|\bD0330\b",
    re.IGNORECASE,
)

_SEALANT_TERMS_RE = re.compile(r"\bsealants?\b|\bD1351\b", re.IGNORECASE)

_ORTHO_TERMS_RE = re.compile(r"\borthodontic\w*|\bD8\d{3}\b", re.IGNORECASE)

_DEDUCTIBLE_NOT_APPLY_RE = re.compile(
    r"\b(?:does|do|will)\s+not\s+apply\s+(?:to|for|on)\b(?P<rest>.*)",
    re.IGNORECASE | re.DOTALL,
)

_EXCEPT_RE = re.compile(r"\b(?:except|excluding|excludes)\b", re.IGNORECASE)


def mentions_preventive(text: Any) -> bool:
    return bool(_PREVENTIVE_TERMS_RE.search(_text(text)))


def annual_max_includes_preventive(description: Any) -> str | None:
    text = _text(description)
    if not text:
        return None
    parts = _EXCEPT_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        if mentions_preventive(parts[1]):
            return "No"
        if re.search(r"\bprevent(?:ive|ative)\b", parts[0], re.IGNORECASE) or re.search(r"\ball\b", parts[0], re.IGNORECASE):
            return "Yes"
        return "No"
    return "Yes" if re.search(r"\bprevent(?:ive|ative)\b|\ball\b", text, re.IGNORECASE) else None


def deductible_exempt_text(description: Any) -> str | None:
    text = _text(description)
    if not text:
        return None
    m = _DEDUCTIBLE_NOT_APPLY_RE.search(text)
    if m:
        return m.group("rest")
    parts = _EXCEPT_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        return parts[1]
    return None


def deductible_exempts_category(exempt_text: str | None, category: str) -> bool:
    if not exempt_text:
        return False
    cat = _text(category).lower()
    if cat.startswith("diagnostic"):
        pattern = _DIAGNOSTIC_TERMS_RE
    elif cat.startswith("preventive"):
        pattern = _PREVENTIVE_TERMS_RE
    elif cat.startswith(("bitewing", "all other radiographs")):
        pattern = _XRAY_TERMS_RE
    elif cat.startswith("sealant"):
        pattern = _SEALANT_TERMS_RE
    elif cat.startswith("orthodontic"):
        pattern = _ORTHO_TERMS_RE
    else:
        return False
    return bool(pattern.search(exempt_text))


_ORTHO_TIMING_NOTE_RE = re.compile(
    r"^\s*(monthly|quarterly|semi-?annual(?:ly)?|annual(?:ly)?|lump[\s-]?sum|one[\s-]?time)"
    r"\s+payments?\s*:?\s*$",
    re.IGNORECASE,
)


_AGE_PHRASES: dict[str, tuple[str, ...]] = {
    "D1206": ("fluoride treatments",),
    "D1208": ("fluoride treatments",),
    "D1351": ("sealants",),
    "D1510": ("space maintainers",),
}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _code_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        pieces = [str(item) for item in value if item is not None]
    else:
        pieces = [str(value)]
    out: list[str] = []
    for piece in pieces:
        for token in re.split(r"[\s,;|]+", piece):
            token = token.strip().upper()
            if token and token not in out:
                out.append(token)
    return out


_NOT_IN_PORTAL_KIND = "NOT_IN_PORTAL_CODE_LIST"


def _is_not_in_portal_result(result: dict[str, Any]) -> bool:
    return (
        _text(result.get("failure_kind")).upper() == _NOT_IN_PORTAL_KIND
        or _text(result.get("status")).casefold() == "not in portal code list"
    )


def _is_failed_result(result: dict[str, Any]) -> bool:
    return _text(result.get("status")).upper() == "FAILED"


def _money(value: Any) -> str:
    if value in (None, "", "N/A", "NA"):
        return ""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return _text(value)


def _flatten_limitations(result: dict[str, Any]) -> list[str]:
    """Return every raw limitation sentence carried by one code lookup."""
    out: list[str] = []
    for item in result.get("limitations") or []:
        if not isinstance(item, dict):
            continue
        for sentence in item.get("exclusionsAndLimitations") or []:
            sentence = _text(sentence)
            if sentence and sentence not in out:
                out.append(sentence)
    for key in ("applicable_limitations", "frequency"):
        values = result.get(key)
        if isinstance(values, str):
            values = [values]
        for sentence in values or []:
            if not isinstance(sentence, str):
                continue
            sentence = _text(sentence)
            if sentence and sentence not in out:
                out.append(sentence)
    return out


def _all_source_limitations(raw: dict[str, Any]) -> list[str]:
    """Flatten the plan-level Exclusions And Limitations section."""
    out: list[str] = []
    section = raw.get("exclusions_and_limitations") or {}
    for record in section.get("records") or []:
        if not isinstance(record, dict):
            continue
        for sentence in record.get("exclusionsAndLimitations") or []:
            sentence = _text(sentence)
            if sentence and sentence not in out:
                out.append(sentence)
    return out


def _phrase_applies(code: str, sentence: str) -> bool:
    """Whether a limitation sentence explicitly governs the exact CDT code."""
    text = sentence.lower()
    if re.search(rf"\b{re.escape(code.lower())}\b", text):
        return True
    # "Full mouth x-rays (which include bitewing x-rays) ..." is about full
    # mouth x-rays; the aside must not hand its five-year limit to bitewings.
    text = re.sub(r"\(\s*which\s+include[^)]*\)", " ", text)
    if code == "D4910" and "in addition to periodontal" in text:
        return False
    return any(phrase in text for phrase in _FREQUENCY_PHRASES.get(code, ()))


def _age_phrase_applies(code: str, sentence: str) -> bool:
    text = sentence.lower()
    if re.search(rf"\b{re.escape(code.lower())}\b", text):
        return True
    return any(phrase in text for phrase in _AGE_PHRASES.get(code, ()))


def _frequency_from_text(text: str) -> str | None:
    """Convert explicit Toolkit prose into the canonical frequency string."""
    text = _text(text)
    if not text:
        return None

    low = text.lower()
    if "lifetime" in low and re.search(r"\bonce\b", low):
        return "1XLifetime"

    # Prefer frequency words over bare numbers so an age statement such as
    # "age 15 and under" can never be mistaken for a five-year count.
    count_match = re.search(
        r"\b(once|twice|thrice|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        low,
    )
    if not count_match:
        count_match = re.search(
            r"(?:payable|limited\s+to)[^.]{0,80}?\b(\d+)\s+times?\b",
            low,
        )
    if not count_match:
        # "...payable up to age 19 with no time limitation" is the portal's way
        # of saying there is no frequency limit; the sheet writes "No Frequency".
        if re.search(r"\bno\s+(?:time\s+|frequency\s+)?(?:limitation|limit)s?\b|\bno\s+frequency\b", low):
            return "No Frequency"
        return None

    word = count_match.group(1)
    count = int(word) if word.isdigit() else _WORD_COUNTS.get(word)
    if not count:
        return None

    tail = low[count_match.end():]
    number = r"(one|two|three|four|five|six|seven|eight|nine|ten|\d+)"

    month = re.search(
        rf"(?:in|within)\s+(?:any\s+)?(?:a\s+|an\s+)?(?:period\s+of\s+)?{number}\s*(?:-| )?(?:consecutive\s+)?months?\b",
        tail,
    )
    if not month:
        month = re.search(
            rf"per\s+(?:tooth|area|quadrant|quadrants)\s+per\s+{number}\s*(?:-| )?(?:consecutive\s+)?months?\b",
            tail,
        )
    if month:
        span_raw = month.group(1).lower()
        span = int(span_raw) if span_raw.isdigit() else _WORD_COUNTS.get(span_raw)
        if span:
            return f"{count}X{span}Months"

    year = re.search(
        rf"(?:in|within)\s+(?:any\s+)?(?:a\s+|an\s+)?(?:period\s+of\s+)?{number}\s*(?:-| )?(?:consecutive\s+)?years?\b",
        tail,
    )
    if not year:
        year = re.search(
            rf"per\s+(?:tooth|area|quadrant|quadrants)\s+per\s+{number}\s*(?:-| )?(?:consecutive\s+)?years?\b",
            tail,
        )
    if year:
        span_raw = year.group(1).lower()
        span = int(span_raw) if span_raw.isdigit() else _WORD_COUNTS.get(span_raw)
        if span:
            return f"{count}X{span}Year" if span == 1 else f"{count}X{span}Years"

    # Plans word their accumulation period differently — "calendar year",
    # "benefit year", "benefit period", "plan year" — and for every one of them
    # the limit is a count per that one-year period.
    period = r"(?:calendar|benefit|plan|contract)\s+(?:year|period)"
    if re.search(rf"per\s+{period}\b", tail) or re.search(rf"(?:in|within)\s+(?:a|an|any|each)\s+{period}\b", tail):
        return f"{count}X1Year"

    if re.search(r"per\s+(?:date of service|day)\b", tail):
        return f"{count}X1Day"

    return None


def _frequency_scope(text: str) -> str | None:
    low = text.lower()
    if "per quadrant" in low:
        return "quadrant"
    if "per tooth" in low:
        return "tooth"
    if "per area" in low:
        return "area"
    return None


def _derive_frequency(code: str, limitations: list[str]) -> tuple[str, str | None, str | None]:
    """
    Return (frequency, exact limitation used, optional scope).

    `Frequency not available` is intentional and is the only fallback for a
    successful code with no explicit applicable frequency sentence.
    """
    for sentence in limitations:
        if not _phrase_applies(code, sentence):
            continue
        frequency = _frequency_from_text(sentence)
        if frequency:
            return frequency, sentence, _frequency_scope(sentence)
    return "Frequency not available", None, None


_AGE_LIMIT_RE = re.compile(r"age\s+(\d{1,3})\s+and\s+under|up\s+to\s+age\s+(\d{1,3})", re.IGNORECASE)


def _derive_age(code: str, limitations: list[str]) -> tuple[str, str | None]:
    """Derive the age limit for a CDT code from its Toolkit limitation prose.

    A single sentence can state several ages, e.g. D1351:
    "Sealants are payable for the first permanent molars for age 8 and under;
    second permanent molars for age 13 and under."  Whenever the sentence(s)
    governing the code carry more than one age, the MAXIMUM is the limit, so
    that example yields 13 (not the first-listed 8).
    """
    best_age: int | None = None
    best_sentence: str | None = None
    for sentence in limitations:
        if not _age_phrase_applies(code, sentence):
            continue
        for m in _AGE_LIMIT_RE.finditer(sentence):
            age = int(m.group(1) or m.group(2))
            if best_age is None or age > best_age:
                best_age, best_sentence = age, sentence
    if best_age is None:
        return "", None
    return str(best_age), best_sentence


def _procedure_description(path: list[dict[str, Any]], code: str) -> str:
    if path:
        # Level 2 is the useful human-readable CDT family; level 3 is the code.
        for item in reversed(path[:-1]):
            value = _text(item.get("procedure"))
            if value:
                return value
    return code


# The Toolkit comparison can receive the full seven-page Sabrina PDF.  Some CDT
# rows that are represented in the fixed comparison set are not present in the
# first three-page Sabrina table, but are present later in the embedded Delta
# benefit pages.  Those rows must be recovered for the Toolkit path only; no
# legacy carrier parser is changed.
_TOOLKIT_PDF_FREQ_PHRASES: dict[str, tuple[str, ...]] = {
    "D1120": ("prophylaxes (cleanings)", "prophylaxes", "cleanings"),
    "D2140": ("amalgam and composite resin restorations",),
    "D2331": ("amalgam and composite resin restorations",),
}
_TOOLKIT_PDF_COVERAGE_RE = re.compile(
    r"^(?:not\s+covered|optional|nc|\d+(?:\.\d+)?%)$", re.IGNORECASE
)
_TOOLKIT_PDF_CODE_RE = re.compile(r"^D\d{4}$", re.IGNORECASE)
_TOOLKIT_PDF_HEADINGS = {
    "preventive", "bitewing radiographs", "all other radiographs", "sealants",
    "minor restorative", "major restorative", "endodontics", "periodontics",
    "simple extractions", "other oral surgery", "other basic services",
    "prosthodontics", "implants", "orthodontic services",
}
_TOOLKIT_PDF_LIMITATION_RE = re.compile(r"^\s*[•*-]\s*(.+)$")


def _toolkit_pdf_lines(text: str) -> list[str]:
    """Normalize the text layer just enough for embedded Delta table rows."""
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in str(text or "").splitlines()
        if line and line.strip()
    ]


def _toolkit_pdf_code_rows(text: str) -> dict[str, dict[str, Any]]:
    """Read explicit CDT rows from all pages of the supplied Sabrina PDF.

    This is deliberately row-based: a CDT code is accepted only when it is a
    row label in the PDF.  We never create a code from a prose mention.
    """
    lines = _toolkit_pdf_lines(text)
    rows: dict[str, dict[str, Any]] = {}
    current_section = ""

    for i, line in enumerate(lines):
        normalized = re.sub(r"[^A-Za-z ]", "", line).strip().lower()
        if normalized in _TOOLKIT_PDF_HEADINGS:
            current_section = normalized
            continue

        # The extractor normally puts the CDT code on its own line, but accept
        # "D1234 Description ..." too for PDFs whose table is flattened.
        match = re.match(r"^\s*(D\d{4})(?:\s+(.*?))?\s*$", line, re.IGNORECASE)
        if not match:
            continue
        code = match.group(1).upper()
        tail = (match.group(2) or "").strip()

        cells: list[str] = []
        if tail:
            cells.append(tail)
        for candidate in lines[i + 1:i + 7]:
            if _TOOLKIT_PDF_CODE_RE.fullmatch(candidate):
                break
            if re.match(r"^D\d{4}\b", candidate, re.IGNORECASE):
                break
            if candidate.lower() in _TOOLKIT_PDF_HEADINGS:
                break
            if _TOOLKIT_PDF_LIMITATION_RE.match(candidate):
                break
            cells.append(candidate)

        coverage = ""
        for cell in cells:
            clean = cell.strip()
            if _TOOLKIT_PDF_COVERAGE_RE.fullmatch(clean):
                coverage = clean
                break

        if not coverage:
            # A row may be flattened into a single string like
            # "D2740 Crown Optional N/A".
            m = re.search(r"\b(not\s+covered|optional|nc|\d+(?:\.\d+)?%)\b", tail, re.IGNORECASE)
            if m:
                coverage = m.group(1)

        if coverage:
            rows.setdefault(code, {
                "percentage": coverage,
                "frequency": None,
                "frequency_source": None,
                "section": current_section,
            })

    return rows


def _toolkit_pdf_limitation_blocks(text: str) -> dict[str, list[str]]:
    """Collect limitation bullets under their explicit embedded-Delta section."""
    lines = _toolkit_pdf_lines(text)
    blocks: dict[str, list[str]] = {}
    current_section = ""
    for line in lines:
        normalized = re.sub(r"[^A-Za-z ]", "", line).strip().lower()
        if normalized in _TOOLKIT_PDF_HEADINGS:
            current_section = normalized
            blocks.setdefault(current_section, [])
            continue
        m = _TOOLKIT_PDF_LIMITATION_RE.match(line)
        if m and current_section:
            sentence = re.sub(r"\s+", " ", m.group(1)).strip()
            if sentence and sentence not in blocks[current_section]:
                blocks[current_section].append(sentence)
    return blocks


def _toolkit_pdf_frequency(code: str, section: str, limitations: list[str], coverage: str) -> tuple[str, str | None]:
    """Resolve only an explicit source phrase; otherwise record no frequency."""
    if re.search(r"(?:not\s+covered|^nc$)", coverage or "", re.IGNORECASE):
        return "Not Covered", None

    phrases = _TOOLKIT_PDF_FREQ_PHRASES.get(code, ())
    for sentence in limitations:
        low = sentence.lower()
        if any(phrase in low for phrase in phrases):
            # Reuse the deterministic Toolkit prose converter, which is based
            # on the sentence itself rather than a neighboring CDT code.
            frequency = _frequency_from_text(sentence)
            if frequency:
                return frequency, sentence

    # The embedded Delta pages have no per-row frequency column.  For a code
    # that is explicitly present but has no source frequency phrase, surface
    # the same canonical "not available" value used by the Toolkit adapter.
    return "Frequency not available", None


def enrich_toolkit_sabrina_parse(parsed: dict) -> dict:
    """Add later-page CDT rows to a Sabrina parse for Toolkit comparisons only.

    The base Sabrina parser intentionally ignores `portal_only` rows for legacy
    compatibility.  The Toolkit path needs to inspect the entire seven-page
    PDF, so this adapter supplements only values that were not already parsed.
    """
    if not isinstance(parsed, dict) or not parsed.get("text"):
        return parsed

    text = parsed.get("text", "")
    code_rows = _toolkit_pdf_code_rows(text)
    limitation_blocks = _toolkit_pdf_limitation_blocks(text)

    fields = dict(parsed.get("fields") or {})
    benefit_rows = {
        str(k): dict(v) for k, v in (parsed.get("benefit_rows") or {}).items() if isinstance(v, dict)
    }

    for code, row in code_rows.items():
        key = code.lower()
        # Preserve the primary Sabrina Benefit Details value when the same CDT
        # appears earlier in the document (e.g. D2740 = 50% on page 2).
        if fields.get(key) in (None, ""):
            fields[key] = row["percentage"]

        existing = benefit_rows.get(key, {})
        frequency = existing.get("frequency")
        frequency_source = existing.get("frequency_source")
        if not frequency:
            section = row.get("section") or ""
            frequency, frequency_source = _toolkit_pdf_frequency(
                code, section, limitation_blocks.get(section, []), row.get("percentage", "")
            )

        # Only fill what the current spec actually consumes.  Extra age/history
        # columns remain absent unless the primary Sabrina parser already found
        # them, so we do not manufacture history from the embedded Delta PDF.
        benefit_rows[key] = {
            "frequency": frequency,
            "percentage": existing.get("percentage") or row["percentage"],
            "age_limit": existing.get("age_limit"),
            "history": existing.get("history"),
            **({"frequency_source": frequency_source} if frequency_source else {}),
        }
        # The comparison loop reads derived columns from `fields`, not only
        # from the row cache. Populate the Toolkit-only CDT frequency value
        # here so `Dxxxx__freq` is no longer reported as blank.
        if fields.get(f"{key}__freq") in (None, ""):
            fields[f"{key}__freq"] = frequency
        if existing.get("age_limit") is not None and fields.get(f"{key}__age") in (None, ""):
            fields[f"{key}__age"] = existing.get("age_limit")
        if existing.get("history") is not None and fields.get(f"{key}__hist") in (None, ""):
            fields[f"{key}__hist"] = existing.get("history")

    return {
        **parsed,
        "fields": fields,
        "benefit_rows": benefit_rows,
        "toolkit_pdf_enriched": True,
    }


def _coverage_level(result: dict[str, Any]) -> str:
    value = result.get("percentCovered")
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _note_fields(notes: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for note in notes or []:
        m = re.match(r"\s*([A-Za-z][A-Za-z /&-]{1,40}?)\s*:\s*(.+?)\s*$", str(note or ""))
        if m:
            out.setdefault(m.group(1).strip().lower(), m.group(2).strip())
    return out


def _payor_id_from_site(raw: Any) -> str:
    blob = " ".join(_walk_strings(raw)).lower()
    if "deltadentalmi.com" in blob:
        return "DDPMI"
    if "deltadentalin.com" in blob:
        return "DDPIN"
    if re.search(r"deltadental[a-z]*\.com", blob):
        return "DDPOH"
    return ""


def _no_deductible_stated(raw: dict[str, Any]) -> bool:
    """True when the source explicitly says the contract has no deductible."""
    for section in ("maximums_and_deductibles", "ortho_information", "routine_procedures", "coverages"):
        for text in _walk_strings(raw.get(section)):
            if _NO_DEDUCTIBLE_RE.search(text):
                return True
    return False


def _ortho_payment_timing_from_notes(ortho_info: dict[str, Any]) -> str:
    """Read an explicit "<Frequency> payment:" heading from the ortho notes.

    A separate "Payment frequency: Monthly" line is intentionally not used: it
    is a different statement from the quarterly/monthly payment heading that
    the Sabrina Ortho Payment Timing field mirrors.
    """
    for note in (ortho_info or {}).get("notes") or []:
        m = _ORTHO_TIMING_NOTE_RE.match(_text(note))
        if m:
            word = m.group(1).lower()
            return re.sub(r"[\s-]+", " ", word).title().replace("Semi Annual", "Semi-Annual")
    return ""


def _ortho_age_from_sentence(raw: dict[str, Any]) -> str:
    pattern = re.compile(
        r"orthodontic\s+age\s+limit\s+for\s+this\s+patient\s+is\s+covered\s+for\s+age\s+(\d{1,3})",
        re.IGNORECASE,
    )
    for section in ("ortho_information", "more_information", "coverages", "maximums_and_deductibles"):
        for text in _walk_strings(raw.get(section)):
            m = pattern.search(text)
            if m:
                return m.group(1)
    return ""


def _percent_text(value: Any) -> str:
    text = _text(value)
    return f"{text}%" if re.fullmatch(r"\d+(?:\.\d+)?", text) else text


def _latest_service_date(value: Any) -> str | None:
    """Normalize actual Toolkit service-history dates, when present."""
    dates: list[str] = []
    if isinstance(value, str):
        dates = re.findall(r"\d{1,2}/\d{1,2}/\d{2,4}", value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                item = item.get("date") or item.get("serviceDate") or item.get("service_date")
            if item:
                dates.extend(re.findall(r"\d{1,2}/\d{1,2}/\d{2,4}", str(item)))
    if not dates:
        return None

    def key(raw: str) -> tuple[int, int, int]:
        parts = [int(x) for x in raw.split("/")]
        year = parts[2] + (2000 if parts[2] < 100 else 0)
        return year, parts[0], parts[1]

    return max(dates, key=key)


def _history_for_code(code: str, result: dict[str, Any], routine_by_code: dict[str, dict[str, Any]]) -> str | None:
    """Service history for exactly this CDT code, or None when the source says nothing.

    History is never inherited from another code.  A routine-procedure row for
    this exact code with no service dates is an explicit "no history" (NH); a
    code with no row at all is simply not stated by the portal.
    """
    direct = (
        _latest_service_date(result.get("serviceDates"))
        or _latest_service_date(result.get("utilization_history"))
    )
    if direct:
        return direct
    routine = routine_by_code.get(code.upper())
    if routine is None:
        if (
            _text(result.get("history_status")).upper() == "NO_HISTORY_ON_FILE"
            and result.get("utilization_source_present") is not False
        ):
            return "NH"
        return None
    routine_date = _latest_service_date(routine.get("serviceDates"))
    if routine_date:
        return routine_date
    detail = _text(routine.get("statusDetail"))
    if re.search(r"service dates? of", detail, re.IGNORECASE):
        detail_date = _latest_service_date(detail)
        if detail_date:
            return detail_date
    return "NH"


def _share_frequency(procedures: list[dict[str, Any]]) -> None:
    """Adult and child prophylaxis share one frequency sentence (when both are covered).

    Service history is deliberately NOT shared: a date recorded for one CDT
    code says nothing about another code that happens to share a limitation.
    """
    by_code = {p["procedure_code"]: p for p in procedures}
    adult, child = by_code.get("D1110"), by_code.get("D1120")
    if adult and child:
        # Only share when BOTH codes are covered.  If the plan says a child
        # prophylaxis is not covered, the adult frequency must not leak onto it.
        if any(str(p.get("benefit_level") or "").strip().lower() == "not covered" for p in (adult, child)):
            return
        donor = adult if adult["frequency_source"] else child if child["frequency_source"] else None
        if donor:
            for target in (adult, child):
                target["frequency_limit"] = donor["frequency_limit"]
                target["frequency_source"] = donor["frequency_source"]
                target["frequency_scope"] = donor["frequency_scope"]


def _inherit_perio_maintenance_frequency(procedures: list[dict[str, Any]]) -> None:
    by_code = {p["procedure_code"]: p for p in procedures}
    perio, prophy = by_code.get("D4910"), by_code.get("D1110")
    if not perio or not prophy:
        return
    if str(perio.get("frequency_limit") or "").strip().lower() != "frequency not available":
        return
    if str(perio.get("benefit_level") or "").strip().lower() == "not covered":
        return
    donor = str(prophy.get("frequency_limit") or "").strip()
    if not donor or donor.lower() in ("frequency not available", "not covered"):
        return
    if "in addition to periodontal" in str(prophy.get("frequency_source") or "").lower():
        return
    perio["frequency_limit"] = donor
    perio["frequency_source"] = prophy.get("frequency_source") or ""
    perio["frequency_scope"] = prophy.get("frequency_scope") or ""
    perio["frequency_inherited_from"] = "D1110"


_CHECKLIST_CODES: frozenset[str] | None = None


def _checklist_codes() -> frozenset[str]:
    global _CHECKLIST_CODES
    if _CHECKLIST_CODES is None:
        codes: set[str] = set()
        try:
            from ..sabrina.spec import _SPEC
        except Exception:
            _SPEC = []
        for field in _SPEC:
            src = field.get("portal") if isinstance(field, dict) else None
            if not (isinstance(src, tuple) and src):
                continue
            if src[0] == "code":
                codes.update(str(c).upper() for c in src[1:] if isinstance(c, str))
            elif src[0] == "codefield":
                codes.update(str(c).upper() for c in src[2:] if isinstance(c, str))
        _CHECKLIST_CODES = frozenset(codes)
    return _CHECKLIST_CODES


def _procedure_root_category(proc: dict[str, Any]) -> str:
    path = [item for item in (proc.get("procedure_path") or []) if isinstance(item, dict)]
    for item in path:
        if item.get("level") == 1:
            return _text(item.get("procedure")).casefold()
    if len(path) > 1 and not any("level" in item for item in path):
        return _text(path[0].get("procedure")).casefold()
    return ""


def _resolve_optional_coverage(
    procedures: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
) -> None:
    """Resolve Toolkit "Optional" procedure coverage from the same CDT category.

    Delta Toolkit can return ``Optional`` for an individual CDT lookup even when
    the surrounding category has a normal benefit percentage.  For comparison
    purposes, an Optional code inherits the percentage of another code in the
    same level-1 CDT category.  We prefer an explicitly numeric sibling value;
    the category-level coverage row is only a final fallback.

    This is Toolkit-specific normalization.  It does not import or call any
    other carrier implementation.
    """
    if not procedures:
        return

    numeric_re = re.compile(r"^\s*\d+(?:\.\d+)?%?\s*$")
    by_category: dict[str, list[dict[str, Any]]] = {}
    for proc in procedures:
        category = _procedure_root_category(proc)
        if category:
            by_category.setdefault(category, []).append(proc)

    category_coverage: dict[str, str] = {}
    for row in coverage_rows:
        if not isinstance(row, dict):
            continue
        category = _text(row.get("procedure")).casefold()
        value = _coverage_level(row)
        if category and value and numeric_re.fullmatch(value):
            category_coverage.setdefault(category, value)

    for proc in procedures:
        current = _text(proc.get("benefit_level"))
        if current.casefold() != "optional":
            continue

        code = str(proc.get("procedure_code") or "").upper()
        category = _procedure_root_category(proc)
        checklist = _checklist_codes()
        siblings = [
            candidate for candidate in by_category.get(category, [])
            if candidate is not proc and str(candidate.get("procedure_code") or "").upper() != code
            and (not checklist or str(candidate.get("procedure_code") or "").upper() in checklist)
        ]

        donor = next(
            (candidate for candidate in siblings
             if candidate.get("original_benefit_level") != "Optional"
             and numeric_re.fullmatch(_text(candidate.get("benefit_level")))),
            None,
        )

        inherited = _text(donor.get("benefit_level")) if donor else category_coverage.get(category, "")
        if inherited:
            proc["benefit_level"] = inherited
            proc["coverage_source"] = (
                f"same-category:{donor.get('procedure_code')}"
                if donor else
                f"category:{category}"
            )
            proc["original_benefit_level"] = "Optional"


def _waiting_is_active(rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    active: list[str] = []
    for row in rows:
        waiting = row.get("waitingPeriod") or {}
        if not isinstance(waiting, dict):
            waiting = {"duration": waiting}
        duration = _text(waiting.get("duration"))
        satisfied = waiting.get("waitingPeriodSatisfied") is True
        met_date = _latest_service_date(row.get("waitingPeriodMetDate"))
        if met_date:
            month, day, year = (int(x) for x in met_date.split("/"))
            year += 2000 if year < 100 else 0
            pending = datetime.date(year, month, day) > datetime.date.today()
        else:
            span = re.search(r"(\d+)\s*(day|month|year)s?", duration, re.IGNORECASE)
            pending = bool(span and int(span.group(1)) > 0 and not satisfied)
        if pending:
            label = _text(row.get("procedure") or row.get("procedureCode"))
            if label:
                active.append(label)
    return bool(active), active


def _is_dd_toolkit_portal(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    source = _text(raw.get("source")).lower()
    portal = _text(raw.get("portal")).lower()
    member = raw.get("member_details")
    search = (raw.get("coverages") or {}).get("procedure_code_search")
    return (
        "delta dental office toolkit" in source
        or "dentalofficetoolkit.com" in portal
        or isinstance(member, dict) and isinstance(search, dict)
        and "procedure_code_search" in (raw.get("coverages") or {})
    )


_ORTHO_CAP_KEYS = ("subscriberMaxAge", "spouseMaxAge", "minorMaxAge", "studentMaxAge", "irsMaxAge")


def _plan_ortho_age_cap(config: dict[str, Any]) -> str:
    """Return the highest positive age cap defined for the plan.

    Zero/empty values in relationship-specific fields are treated as unset;
    they must not mask a valid cap for another category (e.g. minorMaxAge=19).
    """
    caps: list[int] = []
    for key in _ORTHO_CAP_KEYS:
        value = config.get(key)
        if isinstance(value, bool) or value in (None, ""):
            continue
        try:
            age = int(value)
        except (TypeError, ValueError):
            continue
        if age > 0:
            caps.append(age)
    return str(max(caps)) if caps else ""


def _normalize_delta_toolkit_portal(raw: dict[str, Any]) -> dict[str, Any]:
    """Translate the Toolkit extraction into the canonical Portal contract."""
    selected = ((raw.get("member_details") or {}).get("selectedMember") or {})
    client = ((raw.get("more_information") or {}).get("client_benefit_information") or {})
    display = client.get("display_fields") or {}
    cob = ((raw.get("more_information") or {}).get("cob_information") or {})
    maximums = (raw.get("maximums_and_deductibles") or {}).get("rows") or []
    ortho_info = raw.get("ortho_information") or {}
    search = (raw.get("coverages") or {}).get("procedure_code_search") or {}
    results = [r for r in (search.get("results") or []) if isinstance(r, dict)]
    failed = set(_code_list(search.get("failed_codes")))
    not_in_portal = set(_code_list(search.get("codes_not_in_portal")))
    requested_code_list = _code_list(search.get("codes_requested"))
    result_by_code = {str(r.get("procedureCode") or "").upper(): r for r in results}
    for _code, _result in result_by_code.items():
        if not _code:
            continue
        if _is_not_in_portal_result(_result):
            not_in_portal.add(_code)
        elif _is_failed_result(_result):
            failed.add(_code)
    failed -= not_in_portal
    unavailable = failed | not_in_portal
    crawl = raw.get("crawl_statistics") or {}

    # The structured display field is the canonical payor ID for this portal.
    # Keep the contradictory source note/claim payor in metadata instead of
    # silently choosing it or creating a mismatch.
    client_notes = _note_fields(client.get("notes"))
    payor_id = (
        _text(display.get("payorId"))
        or _text(display.get("payor_plan_id"))
        or _text(display.get("plan"))
        or _payor_id_from_site(raw)
    )
    group_number = _text(display.get("groupNumber")) or client_notes.get("group number", "")
    sub_group = _text(display.get("subGroupNumber")) or client_notes.get("sub group number", "")
    combined_group = _text(display.get("clientNumber")) or "-".join(x for x in (group_number, sub_group) if x)
    group_name = (
        _text(display.get("groupName"))
        or client_notes.get("group name", "")
        or _text(display.get("subGroupName"))
        or _text(display.get("clientName"))
    )
    claim_address = ((raw.get("more_information") or {}).get("claim_and_inquiry_mailing_addresses") or {}).get("claimMailingAddress") or {}
    members = [m for m in ((raw.get("member_details") or {}).get("members") or []) if isinstance(m, dict)]
    if _text(selected.get("relationship")).lower() == "subscriber":
        subscriber = selected
    else:
        subscriber = next((m for m in members if _text(m.get("relationship")).lower() == "subscriber"), {})

    general_max = next((r for r in maximums if str(r.get("category", "")).lower() == "general"), {})
    ortho_max = next((r for r in maximums if str(r.get("category", "")).lower() == "orthodontic"), {})
    general_ded = next((r for r in maximums if str(r.get("type", "")).lower() == "deductible" and
                        str(r.get("category", "")).lower() == "general"), {})

    annual = general_max.get("individual") or {}
    ortho_individual = ortho_max.get("individual") or {}
    ded_individual = general_ded.get("individual") or {}
    ded_family = general_ded.get("family") or {}
    annual_description = _text(general_max.get("description"))
    ded_description = _text(general_ded.get("description") or general_ded.get("name"))

    no_deductible = not general_ded and _no_deductible_stated(raw)
    if no_deductible:
        ded_individual = {"amount": 0, "used": 0, "remaining": 0}
        ded_family = {"amount": 0, "used": 0, "remaining": 0}
        ded_description = "There is no deductible for this contract"

    major_payment_timing = ""
    maximum_notes = [_text(x) for x in ((raw.get("maximums_and_deductibles") or {}).get("notes") or [])]
    if _text(ortho_info.get("crowns_bridges_dentures_payment_note")):
        maximum_notes.append(_text(ortho_info.get("crowns_bridges_dentures_payment_note")))
    for note in maximum_notes:
        low = note.lower()
        if "seat/delivery date" in low or "seat date" in low:
            major_payment_timing = "Seat Date"
            break
        if "prep date" in low or "prep" in low and "date" in low:
            major_payment_timing = "Prep Date"
            break

    plan_year = "January" if str(raw.get("maximums_and_deductibles", {}).get("accumulationPeriodType", "")).lower() == "calendar year" else ""
    benefit_period = ""
    if general_max.get("from") or general_max.get("to"):
        benefit_period = (
            f"CALENDAR YEAR Start Date: {_text(general_max.get('from'))} "
            f"End Date: {_text(general_max.get('to'))}"
        ).strip()

    all_limits = _all_source_limitations(raw)
    limitation_records_present = bool(
        (raw.get("exclusions_and_limitations") or {}).get("records")
    )
    routine_by_code = {
        str(row.get("procedureCode") or "").upper(): row
        for row in ((raw.get("routine_procedures") or {}).get("rows") or [])
        if isinstance(row, dict) and row.get("procedureCode")
    }

    procedures: list[dict[str, Any]] = []
    for code, result in result_by_code.items():
        if code in unavailable:
            continue
        direct_limits = _flatten_limitations(result)
        # Use the exact result's limitations first, but allow an explicitly
        # applicable plan-level limitation such as periodontal prophylaxis to
        # supply D4910's frequency when the code lookup itself carries only the
        # Periodontics record.
        limitations = list(direct_limits)
        for sentence in all_limits:
            if _phrase_applies(code, sentence) and sentence not in limitations:
                limitations.append(sentence)

        frequency, frequency_source, frequency_scope = _derive_frequency(code, limitations)
        age_limit, age_source = _derive_age(code, limitations)
        waiting = result.get("waitingPeriod") or {}
        direct_history = _history_for_code(code, result, routine_by_code)
        status = _text(result.get("status")).upper() or "OK"
        path = result.get("procedurePath") or []
        # A code the Toolkit itself reports as Not Covered has no frequency.
        # Plan-level prose can still name it (e.g. "Prophylaxes ... payable
        # three times per calendar year ... A child prophylaxis or full mouth
        # debridement is not a covered benefit"), so a frequency derived from
        # that sentence must never be attached to a Not Covered code.
        if _coverage_level(result).lower() == "not covered" or status == "NOT COVERED":
            frequency, frequency_source, frequency_scope = "Not Covered", None, None

        procedures.append({
            "procedure_code": code,
            "description": _procedure_description(path, code),
            "benefit_level": _coverage_level(result),
            "frequency_limit": frequency,
            "frequency_source": frequency_source or "",
            "frequency_scope": frequency_scope or "",
            "age_limit": age_limit,
            "age_limit_source": age_source or "",
            "late_date_of_service": direct_history or "",
            "deductible": "",
            "limitation": " ".join(direct_limits),
            "limitations": direct_limits,
            "procedure_path": path,
            "toolkit_status": status,
            "toolkit_http_status": result.get("httpStatus"),
            "toolkit_error": result.get("error"),
            "toolkit_waiting_period": waiting,
            "toolkit_waiting_period_met_date": result.get("waitingPeriodMetDate"),
            "toolkit_service_dates": [],
            "toolkit_source_limitations": limitations,
            "toolkit_history_status": _text(result.get("history_status")),
            "toolkit_age_limits": list(result.get("age_limits") or []),
            "toolkit_related_limitations": list(result.get("related_limitations") or []),
            "toolkit_raw": result,
        })

    coverage_row_list = [
        r for r in ((raw.get("coverages") or {}).get("coverage_rows") or []) if isinstance(r, dict)
    ]
    _resolve_optional_coverage(procedures, coverage_row_list)

    _share_frequency(procedures)
    _inherit_perio_maintenance_frequency(procedures)

    coverage_notes_text = " ".join(_text(x) for x in ((raw.get("coverages") or {}).get("notes") or []))
    oon_stated = bool(
        _OON_PARTICIPATION_RE.search(coverage_notes_text)
        and re.search(r"may be responsible for more than the percentage indicated", coverage_notes_text, re.IGNORECASE)
    )

    def _is_zero(value: Any) -> bool:
        try:
            return value is not None and float(value) == 0.0
        except (TypeError, ValueError):
            return False

    deductible_is_zero = _is_zero(ded_individual.get("amount")) and (
        ded_family.get("amount") is None or _is_zero(ded_family.get("amount"))
    )
    ded_lower = ded_description.lower()
    ded_exempt = deductible_exempt_text(ded_description)

    covered_services: list[dict[str, Any]] = []
    for row in coverage_row_list:
        category = _text(row.get("procedure"))
        pct = _percent_text(_coverage_level(row))
        if not pct:
            continue
        cat_lower = category.lower()
        if deductible_is_zero:
            deductible_applies = "No"
        elif deductible_exempts_category(ded_exempt, category):
            deductible_applies = "No"
        else:
            deductible_applies = "Yes"
        entry = {
            "category": category.upper(),
            "in_network": f"{pct} Deductible Applies : {deductible_applies}",
        }
        if oon_stated:
            entry["out_of_network"] = f"{pct} Deductible Applies : {deductible_applies}"
        covered_services.append(entry)

    ortho_pct = next(
        (_coverage_level(r) for r in coverage_row_list if _text(r.get("procedure")).lower().startswith("orthodontic")),
        "",
    )
    ortho_covered: bool | None
    if not ortho_pct:
        ortho_covered = None
    elif ortho_pct.lower() == "not covered" or _is_zero(ortho_pct):
        ortho_covered = False
    else:
        ortho_covered = True

    ortho_age = _ortho_age_from_sentence(raw)
    if not ortho_age:
        for config in ortho_info.get("orthoAgeLimitConfig") or []:
            if not isinstance(config, dict):
                continue
            networks = {str(x).strip().lower() for x in (config.get("networks") or [])}
            if "ppo dentist" in networks:
                ortho_age = _plan_ortho_age_cap(config)
                break
    if not ortho_age and re.fullmatch(r"\d{1,3}", _text(ortho_info.get("ortho_age_limit_under"))):
        ortho_age = _text(ortho_info.get("ortho_age_limit_under"))

    def _limitation_present(pattern: str) -> bool:
        return any(re.search(pattern, sentence, re.IGNORECASE) for sentence in all_limits)

    provisions: list[dict[str, str]] = []
    if benefit_period:
        provisions.append({"rule": "Benefit Period", "value": benefit_period})
    if general_max.get("description"):
        provisions.append({"rule": "Annual Maximum", "value": annual_description})
    if ded_description:
        provisions.append({"rule": "Deductible", "value": ded_description})

    if limitation_records_present:
        composites_covered = _limitation_present(r"posterior composite resin restorations are covered services")
        provisions.append({
            "rule": "Alternate Benefit",
            "value": "amalgam filling for composite fillings performed on molar teeth: "
                     + ("No" if composites_covered else "Yes"),
        })
        replaces_missing = _limitation_present(
            r"payment will be made to replace a tooth that has been missing prior to the effective date of coverage"
        )
        provisions.append({
            "rule": "Missing Tooth Clause",
            "value": "benefits available for teeth lost prior to effective date: "
                     + ("Yes" if replaces_missing else "No"),
        })

    crown_downgrade = next(
        (
            sentence
            for proc in procedures if proc["procedure_code"] == "D2740"
            for sentence in proc["toolkit_source_limitations"]
            if re.search(r"porcelain|ceramic|veneer", sentence, re.IGNORECASE)
            and re.search(r"posterior|molar|bicuspid", sentence, re.IGNORECASE)
            and re.search(r"full cast|optioned|alternate|downgrad", sentence, re.IGNORECASE)
        ),
        "",
    )
    if crown_downgrade:
        provisions.append({
            "rule": "Alternate Benefit Crowns",
            "value": "full cast restoration for porcelain or veneer materials on molar teeth: Yes",
        })

    cob_method = _text(cob.get("cobConfig", {}).get("paymentOptionType")) or _note_fields(cob.get("notes")).get("payment option type", "")
    if cob_method:
        provisions.append({"rule": "Coordination of Benefits", "value": cob_method})

    active_wait, active_categories = _waiting_is_active(results)
    if active_wait:
        provisions.append({
            "rule": "Waiting Period",
            "value": "Active waiting period: " + ", ".join(active_categories),
        })
    else:
        provisions.append({
            "rule": "Waiting Period",
            "value": "No waiting period currently outstanding for the selected member.",
        })

    ortho_payment = ((ortho_info.get("orthoPaymentSchedule") or {}).get("paymentFrequencyType") or {})
    ortho_payment_timing = _text(ortho_payment.get("value")) if isinstance(ortho_payment, dict) else ""
    if not ortho_payment_timing:
        ortho_payment_timing = _ortho_payment_timing_from_notes(ortho_info)
    if ortho_covered is False:
        ortho_payment_timing = ""
    if ortho_payment_timing:
        provisions.append({"rule": "Ortho Payment Frequency", "value": ortho_payment_timing})

    ortho_max_type = "Lifetime" if ortho_max.get("isLifetime") is True and ortho_covered is not False else ""
    ortho_ded_stated = ortho_covered is False or no_deductible or (
        "deductible does not apply" in ded_lower and "orthodontic" in ded_lower
    )
    deductible_fam = (
        {
            "total": _money(ded_family.get("amount")),
            "used": _money(ded_family.get("used")),
            "remaining": _money(ded_family.get("remaining")),
        }
        if ded_family.get("amount") is not None
        else {}
    )
    patient_info = {
        "name": _text(selected.get("patientName")),
        "dob": _text(selected.get("birthdate")),
        "relation": _text(selected.get("relationship")),
        "group_number": combined_group,
    }

    return {
        "_skip_llm": True,
        "_source_insurer": "delta dental",
        "_toolkit": True,
        "_toolkit_meta": {
            "selected_network": _text(raw.get("selected_network")),
            "requested_codes": int(
                crawl.get("requested_codes")
                or len(requested_code_list)
                or search.get("count")
                or len(set(result_by_code) | unavailable)
            ),
            "successful_codes": int(
                crawl.get("successful_codes")
                or search.get("successful_count")
                or len([c for c in result_by_code if c and c not in unavailable])
            ),
            "failed_codes": sorted(failed),
            "codes_not_in_portal": sorted(not_in_portal),
            "requested_code_list": requested_code_list,
            "crawl_status": _text(crawl.get("status")),
            "extraction_scope": _text(crawl.get("extraction_scope")),
            "payor_id_from_display": payor_id,
            "payor_id_from_notes": client_notes.get("payor id", ""),
            "group_number": group_number,
            "sub_group_number": sub_group,
            "combined_group_number": combined_group,
            "member_id_available": False,
            "family_deductible_available": ded_family.get("amount") is not None,
            "family_deductible_paid_available": ded_family.get("used") is not None,
            "ortho_deductible_available": ortho_ded_stated,
            "ortho_deductible_paid_available": ortho_ded_stated,
            "ortho_covered": ortho_covered,
            "oon_stated": oon_stated,
            "age_limit_ortho": ortho_age,
            "major_payment_timing": major_payment_timing,
            "ortho_max_type": ortho_max_type,
            "ortho_payment_timing": ortho_payment_timing,
            "no_deductible": no_deductible,
            "claim_payor_id": _text(((raw.get("more_information") or {}).get("claim_and_inquiry_mailing_addresses") or {}).get("payorId")),
            "group_name": group_name,
            "source_limitations": all_limits,
        },
        "carrier_information": {
            "name": "Delta Dental",
            "payer_id": payor_id,
            "address": _text(claim_address.get("street")),
            "city_state_zip": _text(claim_address.get("city_state_zip")),
        },
        "subscriber_info": {
            "name": _text(subscriber.get("patientName")),
            "dob": _text(subscriber.get("birthdate")),
            "relation": _text(subscriber.get("relationship")),
        },
        "patient_info": patient_info,
        "metlife_data": {
            "patient": {
                "name": _text(selected.get("patientName")),
                "dob": _text(selected.get("birthdate")),
                "relationship": _text(selected.get("relationship")),
                "eligibility": _text(selected.get("eligibility")),
            },
            "plan_details": {
                "start_date": _text(selected.get("effectiveDate")),
                "end_date": "",
                "subscriber_id": "",
                "employer_group": group_name,
                "group_number": combined_group,
                "network": _text(raw.get("selected_network")),
                "plan_type": _text(display.get("product")),
            },
            "financials": {
                "annual_max": {
                    "total": _money(annual.get("amount")),
                    "used": _money(annual.get("used")),
                    "remaining": _money(annual.get("remaining")),
                    "description": annual_description,
                },
                "deductible_ind": {
                    "total": _money(ded_individual.get("amount")),
                    "used": _money(ded_individual.get("used")),
                    "remaining": _money(ded_individual.get("remaining")),
                },
                "deductible_fam": deductible_fam,
                "ortho_lifetime": {
                    "total": _money(ortho_individual.get("amount")),
                    "used": _money(ortho_individual.get("used")),
                    "remaining": _money(ortho_individual.get("remaining")),
                    "category": "Orthodontic",
                },
            },
            "provider_info": {
                "provider_name": "",
                "provider_network_status": _text(raw.get("selected_network")),
            },
            "covered_services": covered_services,
            "provisions": provisions,
        },
        "benefit_coverage": {"procedures": procedures},
        "_dd_meta": {"toolkit": True},
    }
