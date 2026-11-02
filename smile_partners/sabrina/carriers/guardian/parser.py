"""
Reading the sheet.

The PDF is a flattened two-column grid, so a field is found by its label rather
than by position: the label's words are matched across the extracted text and
the value is whatever follows it, up to the next label.
"""

from __future__ import annotations

import re
from shared.pdf_extractor import _extract_text
from .spec import _SPEC
from .common import _DEBUG, log
from .vocabulary import _HISTORY_NONE, _num_date, _num_pct


# ══════════════════════════════════════════════════════════════════════════════
#  LABEL MATCHING
# ══════════════════════════════════════════════════════════════════════════════

def _norm_label(s: str) -> str:
    """
    Canonical form of a label for matching: lowercase, punctuation and the
    decorative $ / # / (…) markers dropped, whitespace collapsed.

        "Yearly Max($)"                  → "yearly max"
        "Orthodontics Deductible Amount$" → "orthodontics deductible amount"
        "Does Missing Tooth Clause Apply?"→ "does missing tooth clause apply"
    """
    s = (s or "").replace(" ", " ")
    s = re.sub(r"[$#()\[\]:?.,*]", " ", s.lower())
    s = s.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


# Labels and headers that Sabrina prints but this audit does not compare. They
# are NOT values, so they both stop a value from running on and can never be
# picked up as one. Taken from a real export — the sheet's own field set.
# Every label/alias in the spec — used so a value hunt never swallows the NEXT
# field's label as if it were this field's value.
_ALL_LABELS: set[str] = set()
for _f in _SPEC:
    if _f.get("derived"):
        continue          # read from a row's cells, never from a label
    _ALL_LABELS.add(_norm_label(_f["label"]))
    for _a in _f.get("aliases", ()):
        _ALL_LABELS.add(_norm_label(_a))


_OTHER_SHEET_LABELS = {_norm_label(s) for s in (
    # Demographics / office block
    "Office Name", "Provider Name", "Preferred Provider Name", "Chair Provider Name",
    "Provider Speciality", "Provider Specialty", "Appointment Date",
    "Relation to Subscriber", "SSN#", "Patient ID",
    # Insurance block
    "Insurance Plan Name", "Fee Schedule", "Insurance Phone",
    "Eligibility Term Date", "Patient Term Date", "Eligibility Notes",
    "PPO / Indemnity / HMO Plan?",
    # Coverage block
    "Applies To", "Period", "Ortho Maximum Covered", "Ortho Payment Timing",
    "Pre-Authorize over",
    "Dependent Age Limit",
    # Section + table headers
    "Demographics", "Office Information", "Patient/Subscriber Information",
    "Insurance Information", "Coverage", "Benefit Details", "Benefit Name",
    "Frequency", "Percentage", "Age Limit", "History", "Insurance Plan Breakdown",
    "Verification Date",
)}


# Generic section words from other sheet variants, kept for tolerance.
_NON_VALUES = _ALL_LABELS | _OTHER_SHEET_LABELS | {
    "patient information", "subscriber information", "benefits",
    "general benefit details", "plan information", "eligibility", "maximums",
    "deductibles", "orthodontics", "exams", "diagnostic", "preventive",
    "preventative", "basic restorative", "major restorative", "endodontics",
    "periodontics", "prosthodontics", "implant", "oral surgery", "adjunctive",
    "notes", "code", "description", "coverage %", "sabrina",
}


# NOTE: "yes"/"no" are deliberately NOT listed — they are the legitimate value
# of every Y/N field on the sheet, not headers.

# Every label on the sheet, compared or not — the set that stops a value.
# Indexed by first word so scanning a line for "does a label start here?" only
# tests the handful of plausible candidates.
_STOP_LABELS = _ALL_LABELS | _OTHER_SHEET_LABELS


_LABELS_BY_FIRST: dict[str, list[str]] = {}
for _lbl in _STOP_LABELS:
    if _lbl:
        _LABELS_BY_FIRST.setdefault(_lbl.split()[0], []).append(_lbl)


_SEP_RE = re.compile(r"^\s*[:\-–—=>|]+\s*")


_TRIM = " \t:-–—=|"


# A Benefit Details "Frequency" cell — "2X1Year", "1X12Months", "1XLifetime",
# "No Frequency", "Frequency not available", "NC", "Pre-D". These sit between a CDT label and its
# Percentage cell and must be stepped over when the field being read is a
# coverage percentage.
_FREQ_RE = re.compile(
    r"^(?:\d+\s*x\s*\d*\s*(?:year|month|lifetime|day|week|visit)s?"
    r"|no\s+frequency|frequency\s+not\s+available|nc|n/c|pre[\s-]?d(?:etermination)?)$",
    re.IGNORECASE,
)


def _split_lines(text: str) -> list[str]:
    """PDF text → trimmed, non-empty lines (order preserved)."""
    out = []
    for raw in (text or "").replace(" ", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if line:
            out.append(line)
    return out


def _reflow_wrapped(lines: list[str]) -> list[str]:
    """
    Re-join text the PDF extractor split in the middle of a cell.

    Sabrina's table cells wrap, so one cell can arrive as two lines:

        D0220 PAs / "No" / "Frequency" / 100%      ← "No Frequency" wrapped
        Benefit Name / Frequency / ... / "Age" / "Limit"

    A fragment is identified by the fact that joining it to its predecessor
    produces something already known — one of the sheet's labels, or a
    Frequency phrase. Without this, the stray fragment "Frequency" collides
    with the table's own "Frequency" column header and is read as the next
    label, which ends the value hunt and leaves the whole row blank.

    Only a first piece that is NOT itself a complete label may absorb a
    follower, so two genuinely separate labels are never fused.
    """
    out = list(lines)
    for _ in range(3):                      # a cell can wrap more than once
        merged: list[str] = []
        i = 0
        changed = False
        while i < len(out):
            joined = None
            if _norm_label(out[i]) not in _STOP_LABELS:
                for take in (3, 2):         # longest wrap first
                    if i + take > len(out):
                        continue
                    cand = " ".join(out[i:i + take])
                    if _norm_label(cand) in _STOP_LABELS or _FREQ_RE.match(cand.strip()):
                        joined = (cand, take)
                        break
            if joined:
                merged.append(joined[0])
                i += joined[1]
                changed = True
            else:
                merged.append(out[i])
                i += 1
        out = merged
        if not changed:
            break
    return out


# Page furniture that sits directly after the last table row.
_BOILERPLATE_RE = re.compile(
    r"^\s*(?:©|\(c\))|all rights reserved|verification date", re.IGNORECASE)


def _is_stop_line(line: str) -> bool:
    """
    Whether a line ends the cells of the field being read: a label, a header,
    or page furniture.

    A Frequency cell is never one, even though "Frequency not available"
    begins with the word "Frequency" — the table's own column header. Without
    this exception every row with that cell stops reading at it and the
    percentage after it is lost.
    """
    if _FREQ_RE.match(line.strip()):
        return False
    return not _looks_like_value(line) or _any_label_at(line.split(), 0)


def _looks_like_value(candidate: str) -> bool:
    """A string is usable as a value unless it is a label, header or boilerplate."""
    if _BOILERPLATE_RE.search(candidate):
        return False
    n = _norm_label(candidate)
    return bool(n) and n not in _NON_VALUES


def _label_span(words: list[str], i: int, target: str) -> int:
    """
    How many words at `words[i:]` the label `target` occupies — 0 if it doesn't
    start there.

    Matched LONGEST-first so decoration that normalizes away ("$", "$:", "#")
    is consumed as part of the printed label; otherwise
    "Orthodontics Deductible Met Amount $: $0.00" would yield "$: $0.00".
    """
    n_target_words = len(target.split())
    max_take = min(len(words) - i, n_target_words + 3)
    for take in range(max_take, 0, -1):
        if _norm_label(" ".join(words[i:i + take])) == target:
            return take
    return 0


def _any_label_at(words: list[str], i: int) -> bool:
    """Whether ANY known label begins at words[i] — the stop signal for a value."""
    norm = _norm_label(words[i])
    if not norm:
        return False
    for lbl in _LABELS_BY_FIRST.get(norm.split()[0], ()):
        if _label_span(words, i, lbl):
            return True
    return False


def _refine_inline(kind: str, inline: str) -> str | None:
    """
    Validate an inline (same-line) value against the kind of cell expected.

    Returns None when the text clearly isn't that cell — a percentage field
    sitting next to a Frequency cell, or leftover label wording — so the caller
    falls through to the following lines instead of storing something wrong.
    """
    if kind != "pct":
        return inline
    # Whole string first, so multi-word statements survive intact ("Not Covered"
    # is a stated 0% benefit; splitting it into words loses that).
    if not _FREQ_RE.match(inline) and _num_pct(inline) is not None:
        return inline
    # Otherwise this is a flattened row carrying several cells at once — take
    # the first token that reads as a percentage, stepping over Frequency cells.
    for token in inline.split():
        if _FREQ_RE.match(token):
            continue
        if _num_pct(token) is not None:
            return token
    return None


def _pick_cell(kind: str, cands: list[tuple[int, str]]) -> tuple[int, str] | None:
    """
    Choose this field's value from the cells that follow its label.

    A Benefit Details row is printed one cell per line with empty cells left
    out, so a coverage percentage can be preceded by a Frequency cell and
    followed by Age Limit and History cells:

        D0120 Periodic Exam / 2X1Year / 100% / 01/28/2026
        D3310 Endodontics   / 80%
        D5899 Prosth Removable / NC / 0

    A percentage field therefore steps over Frequency cells and takes the first
    cell that actually reads as a percentage. Multi-line free text (an address
    wrapped across lines) is joined instead. Everything else takes the first cell.
    """
    if not cands:
        return None

    if kind == "pct":
        for m, cand in cands:
            if _FREQ_RE.match(cand):
                continue                      # Frequency column — not the percentage
            if _num_pct(cand) is not None:
                return m, cand
        return None

    if kind in ("address", "text"):
        # Sabrina wraps long values ("P O BOX 981282 , , EL PASO," / "TX - 79998")
        # across lines; a stop-label already ended the candidate list.
        joined = " ".join(c for _, c in cands).strip()
        return (cands[-1][0], joined) if joined else None

    return cands[0]


def _classify_row_cells(cells: list[str]) -> dict[str, str | None]:
    """
    Split one Benefit Details row's cells into its columns.

    Empty cells are omitted by the extractor, so position alone cannot say which
    column a cell belongs to — each is identified by its shape instead, in
    column order:

        Frequency   before the percentage, matching the frequency vocabulary
        Percentage  the first cell that reads as a percentage
        Age Limit   a bare 1-3 digit number after the percentage
        History     a date, or "NH", after the percentage

    A cell after the percentage that is none of these (the Coverage column, page
    furniture) is ignored rather than guessed at.

    A History cell listing several dates wraps after a comma — "06/10/2026,"
    then "01/29/2026". `history` stays the first line, as it always has been;
    the whole list is kept beside it as `history_wrapped`, which only a Delta
    Dental audit reads (see `carriers/delta_dental/rules.py`).
    """
    freq = pct = age = hist = wrapped = None
    for cell in cells:
        s = cell.strip()
        if pct is None:
            if freq is None and _FREQ_RE.match(s):
                freq = s
            elif _num_pct(s) is not None:
                pct = s
            continue
        if hist is None and (_num_date(s) is not None or s.lower() in _HISTORY_NONE):
            hist = s
        elif (hist is not None and (wrapped or hist).endswith(",")
              and _num_date(s) is not None):
            wrapped = f"{wrapped or hist} {s}"
        elif age is None and re.fullmatch(r"\d{1,3}", s):
            age = s
    return {"frequency": freq, "percentage": pct, "age_limit": age, "history": hist,
            "history_wrapped": wrapped}


def _capture_benefit_rows(lines: list[str]) -> dict[str, dict]:
    """
    Read the Frequency / Age Limit / History cells for every CDT row.

    Runs as its own pass: the percentage is already resolved by the main field
    loop, and re-finding each label here keeps that verified path untouched.
    """
    rows: dict[str, dict] = {}
    for field in _SPEC:
        if field.get("derived") or field["section"] != "Coverage by CDT Code":
            continue
        targets = sorted(
            [_norm_label(field["label"])] +
            [_norm_label(a) for a in field.get("aliases", ())],
            key=lambda t: -len(t.split()))

        at = None
        for target in targets:
            for i, line in enumerate(lines):
                words = line.split()
                if any(_label_span(words, p, target) for p in range(len(words))):
                    at = i
                    break
            if at is not None:
                break
        if at is None:
            continue

        cells = []
        for m in range(at + 1, min(at + 8, len(lines))):
            if _is_stop_line(lines[m]):
                break
            cells.append(lines[m])
        rows[field["key"]] = _classify_row_cells(cells)
    return rows


def _anchor_line(lines: list[str], anchor: str) -> int:
    """First line on which the anchor label appears (at any column)."""
    norm = _norm_label(anchor)
    for i, line in enumerate(lines):
        words = line.split()
        for p in range(len(words)):
            if _label_span(words, p, norm):
                return i
    return 0


def _find_value(lines: list[str], field: dict, cursor: dict[int, int]
                ) -> tuple[str | None, int | None]:
    """
    Locate one field's value on the sheet.

    A label on a form PDF is followed by its value either on the SAME line — the
    grid row flattened by the text extractor, possibly with further columns
    after it — or on the NEXT line (label printed above its value). Both are
    tried, in that order.

    Matching is done at WORD level, not line level, because one flattened line
    routinely carries several fields:

        Individual Deductible($) $50.00 Paid to Date($) $50.00

    `cursor` remembers how far into each line has already been claimed, so the
    second field on a line still finds its own value and no value is read twice.
    `after` anchors a label that appears repeatedly ("Date of Birth",
    "Paid to Date($)") to the first occurrence following its section anchor.
    """
    # Longest label first: where one label is a prefix of another the more
    # specific wins, so "D0150 Diagnostic Exam Comp" is not matched as
    # "D0150 Diagnostic Exam" with a leftover "Comp" read as the value.
    targets = [_norm_label(field["label"])]
    targets += [_norm_label(a) for a in field.get("aliases", ())]
    targets.sort(key=lambda t: -len(t.split()))

    start_line = _anchor_line(lines, field["after"]) if field.get("after") else 0
    blank_at: int | None = None

    for target in targets:
        for i in range(start_line, len(lines)):
            words = lines[i].split()
            for p in range(cursor.get(i, 0), len(words)):
                span = _label_span(words, p, target)
                if not span:
                    continue

                # (a) value on the label's own line, up to the next label
                j = p + span
                k = j
                while k < len(words) and not _any_label_at(words, k):
                    k += 1
                inline = _SEP_RE.sub("", " ".join(words[j:k])).strip(_TRIM)
                if inline and _looks_like_value(inline):
                    refined = _refine_inline(field["kind"], inline)
                    if refined is not None:
                        cursor[i] = k
                        return refined, i
                    # Not the cell we're after (e.g. a Frequency cell, or label
                    # text the label pattern didn't cover) → try the next lines.

                # The label is used up either way — don't rematch it.
                cursor[i] = j

                # (b) value on the following line(s) — label-above-value layout,
                # which is how Sabrina prints both the demographics blocks and
                # the Benefit Details table (one cell per line, empty cells
                # omitted entirely).
                cands: list[tuple[int, str]] = []
                for m in range(i + 1, min(i + 8, len(lines))):
                    if cursor.get(m):
                        continue
                    cand = _SEP_RE.sub("", lines[m]).strip(_TRIM)
                    if not cand:
                        continue
                    if _is_stop_line(cand):
                        break          # next label reached — no more cells for this field
                    cands.append((m, cand))

                picked = _pick_cell(field["kind"], cands)
                if picked is not None:
                    m, value = picked
                    for idx, _ in cands:
                        cursor[idx] = len(lines[idx].split())   # consume skipped cells too
                        if idx == m:
                            break
                    return value, m

                blank_at = i
                break
            else:
                continue
            break  # label found on line i; stop scanning further lines

    return None, blank_at


# ══════════════════════════════════════════════════════════════════════════════
#  SABRINA PDF DETECTION
# ══════════════════════════════════════════════════════════════════════════════

# Labels that are distinctive to the Sabrina breakdown sheet. Generic dental
# words are deliberately excluded — they appear on carrier PDFs too.
_MARKERS = [
    "oon benefits",
    "starting month of plan year",
    "deductible applies to preventative",
    "deductible applies to diagnostic",
    "is there a waiting period",
    "does missing tooth clause apply",
    "preventative included in yearly max",
    "orthodontics deductible met amount",
    "orthodontics used amount",
    "coordination of benefits",
    "patient eff date",
    "member id",
    "payor id",
    "ortho maximum",
    "yearly max",
]


_MIN_MARKERS = 4


def is_sabrina_pdf(text: str) -> bool:
    """
    True when the PDF text looks like a Sabrina patient-breakdown export.

    Deliberately label-based rather than branding-based: the export does not
    reliably print the word "Sabrina", but its field sheet is unmistakable.
    """
    return sabrina_marker_count(text) >= _MIN_MARKERS


def sabrina_marker_count(text: str) -> int:
    """How many Sabrina marker labels the text contains (for diagnostics)."""
    flat = _norm_label(" ".join(_split_lines(text)))
    return sum(1 for m in _MARKERS if m in flat)


# ══════════════════════════════════════════════════════════════════════════════
#  PARSE: SABRINA PDF → {field key: raw string}
# ══════════════════════════════════════════════════════════════════════════════

def parse_sabrina_text(text: str) -> dict:
    """Pull every spec'd field out of already-extracted Sabrina PDF text."""
    lines = _reflow_wrapped(_split_lines(text))

    values: dict[str, str | None] = {}
    cursor: dict[int, int] = {}     # line index → words already claimed
    missing_labels: list[str] = []

    for field in _SPEC:
        if field.get("derived"):
            continue                     # filled in from the row pass below
        value, idx = _find_value(lines, field, cursor)
        values[field["key"]] = value
        if idx is None:
            missing_labels.append(field["label"])

    # Frequency / Age Limit / History for each CDT row.
    benefit_rows = _capture_benefit_rows(lines)
    for row_key, columns in benefit_rows.items():
        values[f"{row_key}__freq"] = columns["frequency"]
        values[f"{row_key}__age"] = columns["age_limit"]
        values[f"{row_key}__hist"] = columns["history"]
    for field in _SPEC:
        if field.get("derived"):
            values.setdefault(field["key"], None)

    if _DEBUG and missing_labels:
        log.warning("Sabrina labels not found in PDF (%d): %s",
                    len(missing_labels), ", ".join(missing_labels))

    return {
        "fields": values,
        "benefit_rows": benefit_rows,
        "labels_not_found": missing_labels,
        "line_count": len(lines),
    }


def parse_sabrina_pdf(pdf_bytes: bytes) -> dict:
    """Read a Sabrina PDF and return its parsed fields (+ the raw text)."""
    text = _extract_text(pdf_bytes)

    if len(text.strip()) < 100:
        raise ValueError(
            "This PDF has no readable text layer (it appears to be scanned or "
            "image-based), so it can't be parsed. Re-download the breakdown "
            "from Sabrina as a text PDF rather than a scan."
        )

    parsed = parse_sabrina_text(text)
    parsed["text"] = text
    parsed["marker_count"] = sabrina_marker_count(text)
    return parsed