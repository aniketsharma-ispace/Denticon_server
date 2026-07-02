import fitz  # PyMuPDF
import re
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────

def _money(val: str | None) -> str | None:
    """Convert '$99,999.99' or 'None' → '$ 99999.99' or None."""
    if not val or val.strip().lower() == "none":
        return None
    cleaned = val.replace(",", "").replace("$", "").strip()
    try:
        return f"$ {float(cleaned):.2f}"
    except ValueError:
        return None


def _table_value(text: str, label: str) -> str | None:
    """
    Extract the first dollar-amount or 'None' from a maximums/deductibles table row.
    Matches lines like:  Annual Maximums $99,999.99 None None
    """
    pattern = rf"{re.escape(label)}\s+(\$[\d,]+\.\d+|None)"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _benefit_level(text: str, service_re: str) -> str | None:
    """
    Extract the PPO benefit % for a service from the Benefit Levels table.
    Matches lines like:  Sealants(1351) 100% No None No None No
    """
    m = re.search(rf"{service_re}\s+([0-9]+%|None)\s+(?:Yes|No)", text, re.IGNORECASE)
    if m:
        v = m.group(1).strip()
        return None if v.lower() == "none" else v
    return None


def _age_range(text: str, keyword_re: str) -> str | None:
    """
    Extract an age range like '0-18' or '14-99' from the Frequency/Age section.
    Handles 'Ages 0-18', 'Ages 0-13', 'Ages 14 and up'.
    """
    # Range: Ages 0-18
    m = re.search(rf"{keyword_re}[^\n]*?Ages?\s+(\d+)\s*[-–]\s*(\d+)", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # Open ended: Ages 14 and up
    m = re.search(rf"{keyword_re}[^\n]*?Ages?\s+(\d+)\s+and\s+up", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-99"
    return None


# ──────────────────────────────────────────────────────────────────
# SHARED: TEXT EXTRACTION
# ──────────────────────────────────────────────────────────────────

def _extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF's pages. Shared by every parser."""
    log.info("Extracting text from PDF...")
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(page.get_text() + "\n" for page in doc)
        doc.close()
    except Exception as e:
        log.error(f"Failed to read PDF: {e}")
        raise ValueError(f"Failed to read PDF: {e}")

    log.info(f"Extracted {len(text)} characters from PDF.")
    return text


# ──────────────────────────────────────────────────────────────────
# FORMAT DETECTION
# ──────────────────────────────────────────────────────────────────

def detect_format(text: str) -> str:
    """
    Identify which insurer produced this PDF based on its content.
    Returns a parser key: 'guardian', 'delta_dental', or 'unknown'.
    Add new insurers here as their parsers are written.
    """
    t = text.lower()

    if "guardiananytime" in t or "dentalguard" in t or "guardian plan" in t:
        return "guardian"

    if "delta dental" in t or "deltadental" in t:
        return "delta_dental"

    # DentaQuest exports its member page as image/vector outlines with no text
    # layer, so it can't be parsed here — recognise it to give a clear message.
    if "dentaquest" in t:
        return "dentaquest"

    # Heuristic fallback for Delta's older layout (colon labels + table headers)
    if re.search(r"Group Name:", text) and re.search(r"Annual Maximums", text):
        return "delta_dental"

    return "unknown"


# ──────────────────────────────────────────────────────────────────
# DISPATCHER — public entry point
# ──────────────────────────────────────────────────────────────────

async def parse_insurance_pdf(pdf_bytes: bytes) -> dict:
    """
    Parse any supported insurance benefit PDF into the common structured schema.
    Auto-detects the insurer, then dispatches to the matching parser.
    """
    text = _extract_text(pdf_bytes)
    fmt = detect_format(text)
    log.info(f"Detected insurance format: '{fmt}'")

    # An image-only / scanned PDF yields almost no extractable text. Older
    # DentaQuest exports are image/vector outlines that land here — the message
    # points the user at the browser extension as the reliable fallback.
    if len(text.strip()) < 100:
        raise ValueError(
            "This PDF has no readable text layer (it appears to be scanned or "
            "image-based), so it can't be parsed. Use a text-based PDF export, "
            "or capture the data with the browser extension."
        )

    parser = _PARSER_REGISTRY.get(fmt)
    if parser is None:
        raise ValueError(
            "Unrecognized insurance PDF format — only Delta Dental, Guardian, and "
            "DentaQuest PDFs are supported."
        )

    result = parser(text)
    result.setdefault("summary", {})["insurer"] = fmt
    return result


# Backwards-compatible wrapper (kept so existing imports keep working).
async def parse_delta_dental_pdf(pdf_bytes: bytes) -> dict:
    return _parse_delta_dental(_extract_text(pdf_bytes))


# ──────────────────────────────────────────────────────────────────
# PARSER: DELTA DENTAL
# ──────────────────────────────────────────────────────────────────

def _parse_delta_dental(text: str) -> dict:
    """
    Parse a Delta Dental benefit verification PDF into structured JSON.
    Uses pure regex — no AI, runs in milliseconds.
    """
    # ── 1. Group Info ──────────────────────────────────────────────
    group_name, group_number = "", ""

    m = re.search(r"Group Name:\s*(.+)", text)
    if m:
        group_name = m.group(1).strip()

    m = re.search(r"Group Number:\s*([\w\-]+)", text)
    if m:
        raw = m.group(1).strip()
        # Strip trailing -00000 padding  e.g. 08319-001-00000-00000 → 08319-001
        parts = raw.split("-")
        while len(parts) > 2 and parts[-1] == "00000":
            parts.pop()
        group_number = "-".join(parts)

    # ── 2. Financials ─────────────────────────────────────────────
    annual_max     = _money(_table_value(text, "Annual Maximums"))
    annual_ded     = _money(_table_value(text, "Annual Deductibles"))
    fam_ded        = _money(_table_value(text, "Annual Family Deductibles"))
    ortho_lifetime = _money(_table_value(text, "Ortho Lifetime Maximums"))
    ortho_ded      = _money(_table_value(text, "Ortho Annual Deductibles"))

    # Individual deductible: prefer Annual Deductibles, fall back to Ortho Annual Deductibles
    ind_ded = annual_ded or ortho_ded or "$ 0.00"

    # ── 3. Benefit Levels ─────────────────────────────────────────
    diag_pct    = _benefit_level(text, r"Diagnostic\(\d+\)")
    prev_pct    = _benefit_level(text, r"Preventive\(\d+\)")
    sealant_pct = _benefit_level(text, r"Sealants\(\d+\)")
    basic_pct   = _benefit_level(text, r"Basic\s+Restor\(\d+\)")
    major_pct   = _benefit_level(text, r"Major\s+Restor\(\d+\)")
    ortho_pct   = _benefit_level(text, r"Orthodontics\(\d+\)")

    d0120_pct = diag_pct or prev_pct or "100%"   # Periodic exam / diagnostic
    d1206_pct = prev_pct or "100%"               # Fluoride = preventive
    d1351_pct = sealant_pct or "100%"            # Sealants
    d1510_pct = prev_pct or "100%"               # Space maintainers = preventive
    d2331_pct = basic_pct or "80%"               # Resin composite
    d2140_pct = basic_pct or "80%"               # Amalgam
    d2740_pct = major_pct or "50%"               # Crown
    d8080_pct = ortho_pct or "50%"               # Orthodontics

    # ── 4. Age Limits ─────────────────────────────────────────────
    sealant_age  = _age_range(text, "Sealants")
    fluoride_age = _age_range(text, r"Fluoride\s+Varnish") or _age_range(text, "Fluoride")

    ortho_age = None
    m = re.search(r"Dependent Orthodontic Age:\s*(\d+)", text)
    if m:
        ortho_age = f"0-{m.group(1)}"
    if not ortho_age:
        m = re.search(r"Child Coverage Age:\s*(\d+)", text)
        if m:
            ortho_age = f"0-{m.group(1)}"

    space_maint_age = None
    m = re.search(r"Child Coverage Age:\s*(\d+)", text)
    if m:
        space_maint_age = f"0-{m.group(1)}"

    # ── 5. Patient Relationship ───────────────────────────────────
    relationship = "Self"

    # ── 6. Assemble Result ────────────────────────────────────────
    result = {
        "summary": {
            "group_name":   group_name,
            "group_number": group_number
        },
        "financials": {
            "individual_deductible": {"total": ind_ded},
            "family_deductible":     {"total": fam_ded or "$ 0.00"},
            "annual_max":            {"total": annual_max or "$ 0.00"},
            "ortho_lifetime":        {"total": ortho_lifetime or "$ 0.00"}
        },
        "patient": {
            "relationship": relationship
        },
        "benefit_coverage": {
            "procedures": [
                {"procedure_code": "D0120", "benefit_level": d0120_pct, "age_limit": "0-99"},
                {"procedure_code": "D1206", "benefit_level": d1206_pct, "age_limit": fluoride_age or "0-18"},
                {"procedure_code": "D1351", "benefit_level": d1351_pct, "age_limit": sealant_age or "0-18"},
                {"procedure_code": "D1510", "benefit_level": d1510_pct, "age_limit": space_maint_age or "0-14"},
                {"procedure_code": "D2331", "benefit_level": d2331_pct},
                {"procedure_code": "D2140", "benefit_level": d2140_pct},
                {"procedure_code": "D2740", "benefit_level": d2740_pct},
                {"procedure_code": "D8080", "benefit_level": d8080_pct, "age_limit": ortho_age or "0-26"}
            ]
        }
    }

    if not group_name and not group_number:
        raise ValueError("Could not extract plan info — PDF format may not be supported.")

    log.info(f"Parsed PDF: group='{group_name}', number='{group_number}', annual_max={annual_max}")
    return result


# ──────────────────────────────────────────────────────────────────
# PARSER: GUARDIAN  (guardiananytime.com eligibility export)
# ──────────────────────────────────────────────────────────────────
#
# Guardian's layout is very different from Delta's:
#   • Field labels sit on their own line; the value follows on the NEXT line(s)
#       Group name
#       MENTAL HEALTH
#       MANAGEMENT
#       Group number
#       00806735
#   • Benefit % shows as a doubled category + two percentages per service row,
#     which PyMuPDF emits split across lines. Stripping whitespace reassembles
#     it into a clean signature, e.g.  "PreventivePreventive100%100%".
#   • Plan-level coinsurance is keyed off the service Category
#     (Preventive=100%, Basic=80%, Major=50%), so we read the category %s
#     and map each CDT code to its category.

def _lines_between(lines: list[str], start_label: str, end_label: str) -> str:
    """Join the non-empty lines that sit between two labels (exclusive)."""
    capturing, out = False, []
    for ln in lines:
        s = ln.strip()
        if not capturing:
            if s.lower() == start_label.lower():
                capturing = True
            continue
        if s.lower() == end_label.lower():
            break
        if s:
            out.append(s)
    return " ".join(out).strip()


def _line_after(lines: list[str], label: str) -> str | None:
    """Return the first non-empty line after the given label line."""
    for i, ln in enumerate(lines):
        if ln.strip().lower() == label.lower():
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
    return None


def _parse_guardian(text: str) -> dict:
    """Parse a Guardian (DentalGuard) eligibility PDF into the common schema."""
    lines   = text.splitlines()
    flat    = re.sub(r"\s+", " ", text)          # newlines → single spaces
    nospace = re.sub(r"\s+", "", text)           # all whitespace removed

    # ── 1. Group info ──────────────────────────────────────────────
    group_name = _lines_between(lines, "Group name", "Group number")
    group_number = ""
    raw_num = _line_after(lines, "Group number")
    if raw_num:
        m = re.match(r"[\w\-]+", raw_num)
        group_number = m.group(0) if m else raw_num.strip()

    plan_name = ""
    m = re.search(r"plan is ([A-Z0-9][A-Z0-9 /&\-]+?)\.", flat)
    if m:
        plan_name = m.group(1).strip()

    # ── 2. Financials ─────────────────────────────────────────────
    ind_ded = None
    m = re.search(r"Individual\s+Dental\s+Out of\s+network\s+(\$[\d,]+\.\d{2})", flat)
    if m:
        ind_ded = _money(m.group(1))

    # Annual max = first pair of adjacent dollar amounts (yearly limit + remaining).
    # The deductible block has "Yes" between its amounts, so it won't match here.
    annual_max = None
    m = re.search(r"network\s+(\$[\d,]+\.\d{2})\s+\$[\d,]+\.\d{2}", flat)
    if m:
        annual_max = _money(m.group(1))

    # ── 3. Coinsurance by category ────────────────────────────────
    # In the de-whitespaced text each service row reads e.g. "BasicBasic80%80%".
    def _cat_pct(category: str) -> str | None:
        mm = re.search(category + category + r"(\d+)%", nospace)
        return mm.group(1) if mm else None

    prev_pct  = _cat_pct("Preventive")
    basic_pct = _cat_pct("Basic")
    major_pct = _cat_pct("Major")
    ortho_pct = _cat_pct("Ortho")
    ortho_not_covered = bool(re.search(r"OrthodonticsNotCovered", nospace))

    def _pct(val: str | None, default: str) -> str:
        return f"{val}%" if val else default

    # ── 4. Age limits (from the message column) ───────────────────
    def _age(pattern: str) -> str | None:
        mm = re.search(pattern, flat, re.IGNORECASE)
        return mm.group(1) if mm else None

    fluoride_age = _age(r"Fluoride \(D1206[^)]*\)[^.]*?up to age (\d+)")
    sealant_age  = _age(r"Sealant \(D1351\)[^.]*?up to age (\d+)")
    space_age    = _age(r"Space maintainers[^.]*?under the age of (\d+)")

    # ── 5. Patient relationship ───────────────────────────────────
    relationship = "Self"

    # ── 6. Build procedures (same schema/codes as Delta) ──────────
    procedures = [
        {"procedure_code": "D0120", "benefit_level": _pct(prev_pct, "100%"), "age_limit": "0-99"},
        {"procedure_code": "D1206", "benefit_level": _pct(prev_pct, "100%"),
         "age_limit": f"0-{fluoride_age}" if fluoride_age else "0-14"},
        {"procedure_code": "D1351", "benefit_level": _pct(prev_pct, "100%"),
         "age_limit": f"0-{sealant_age}" if sealant_age else "0-16"},
        {"procedure_code": "D1510", "benefit_level": _pct(prev_pct, "100%"),
         "age_limit": f"0-{space_age}" if space_age else "0-16"},
        {"procedure_code": "D2331", "benefit_level": _pct(basic_pct, "80%")},
        {"procedure_code": "D2140", "benefit_level": _pct(basic_pct, "80%")},
        {"procedure_code": "D2740", "benefit_level": _pct(major_pct, "50%")},
    ]
    if ortho_not_covered:
        procedures.append({"procedure_code": "D8080", "benefit_level": "0%",
                           "age_limit": "0-26", "frequency_limit": "Not Covered"})
    else:
        procedures.append({"procedure_code": "D8080", "benefit_level": _pct(ortho_pct, "50%"),
                           "age_limit": "0-26"})

    result = {
        "summary": {
            "group_name":   group_name,
            "group_number": group_number,
            "plan_name":    plan_name,
        },
        "financials": {
            # Family deductible isn't given as a dollar amount (Guardian shows
            # "3 per family") — leave at 0 so the downstream 3x rule applies.
            "individual_deductible": {"total": ind_ded or "$ 0.00"},
            "family_deductible":     {"total": "$ 0.00"},
            "annual_max":            {"total": annual_max or "$ 0.00"},
            # Ortho is Not Covered on this plan → no lifetime max.
            "ortho_lifetime":        {"total": "$ 0.00"},
        },
        "patient": {
            "relationship": relationship,
        },
        "benefit_coverage": {
            "procedures": procedures,
        },
    }

    if not group_name and not group_number:
        raise ValueError("Could not extract plan info — Guardian PDF layout may have changed.")

    log.info(f"Parsed Guardian PDF: group='{group_name}', number='{group_number}', "
             f"annual_max={annual_max}, prev={prev_pct}, basic={basic_pct}, major={major_pct}")
    return result


# ──────────────────────────────────────────────────────────────────
# PARSER: DENTAQUEST  (providers.dentaquest.com "Member Details" export)
# ──────────────────────────────────────────────────────────────────
#
# The DentaQuest member-details page, printed/saved as a PDF, DOES carry a full
# text layer (unlike the older image-only exports). Its layout is line-oriented:
#   • Labels sit on their own line; the value follows on the next line, e.g.
#       Plan/Group number:
#       972599
#     (some labels — "Level of coverage: Employee + Child" — are inline instead)
#   • "Benefits at a glance" gives the financials as compact strings:
#       Deductible:  →  $50.0 Individual / $150.0 Family
#       Maximum:     →  $2000.0 Individual annual
#       Orthodontia max.:  →  $1000.0 Individual lifetime
#   • The "Benefits summary" table lists every CDT code as a block:
#       D0120
#       IN: 100% / OON:
#       80%                    ← OON% wraps onto its own line
#       01-01-2024             ← waiting-period-satisfied date
#       One of (...) per 6Month(s) Per patient, .   ← frequency (may wrap)
#       N/A                    ← deductible column
#
# The output mirrors content_dentaquest.js exactly so a PDF-sourced DentaQuest
# and a portal-scraped one are indistinguishable to the matcher.

# Lines in the benefits table that are structural noise, never a category header.
_DQ_NOISE = {
    "procedurecoinsurance", "waiting period", "satisfied", "frequency",
    "deductible", "feedback", "member details", "network", "common codes",
    "benefits summary", "in and out of", "office",
}


def _dq_label(lines: list[str], label: str) -> str | None:
    """
    Value for a 'Label:' field — inline ('Label: value') or on the next
    non-empty line. Case-insensitive; the first match wins.

    The trailing colon is required so we match the real 'Main information'
    fields (e.g. 'Plan:') and not the colon-less column headers of the
    dependents table (e.g. a bare 'Plan').
    """
    want = label.lower().rstrip(":").strip() + ":"
    for i, ln in enumerate(lines):
        s = ln.strip()
        # Inline: "Label: value"
        m = re.match(rf"{re.escape(label)}\s*:\s*(.+)$", s, re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip()
        # Standalone "Label:" line → value is the next non-empty line
        if s.lower() == want:
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
    return None


def _dq_procedures(lines: list[str]) -> list[dict]:
    """Walk the Benefits-summary table and pull one record per CDT code."""
    procedures: list[dict] = []
    seen: set[str] = set()
    category = ""
    code_re = re.compile(r"^D\d{4}$")
    date_re = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    n = len(lines)
    i = 0

    while i < n:
        s = lines[i].strip()

        # A benefit row = a bare CDT code whose next non-empty line starts "IN:".
        # (Codes in the claims-history table are followed by a description, so
        # this check cleanly skips them.)
        if code_re.match(s):
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and lines[j].strip().upper().startswith("IN:"):
                code = s
                coins = lines[j].strip()
                k = j + 1
                # OON% often wraps onto the following line ("IN: 100% / OON:" \n "80%")
                if "OON:" in coins.upper() and not re.search(r"OON:\s*\d+%", coins, re.I):
                    while k < n and not lines[k].strip():
                        k += 1
                    if k < n:
                        coins += " " + lines[k].strip()
                        k += 1
                in_m  = re.search(r"IN:\s*(\d+)%",  coins, re.I)
                oon_m = re.search(r"OON:\s*(\d+)%", coins, re.I)

                # Waiting-period-satisfied date (optional)
                waiting = "N/A"
                while k < n and not lines[k].strip():
                    k += 1
                if k < n and date_re.match(lines[k].strip()):
                    waiting = lines[k].strip()
                    k += 1

                # Frequency text, until the deductible column marker
                freq_parts, ded = [], "N/A"
                while k < n:
                    t = lines[k].strip()
                    if not t:
                        k += 1
                        continue
                    if t == "N/A":
                        ded = "N/A"
                        k += 1
                        break
                    if t.lower().startswith("in and out of"):
                        ded = "In and Out of Network"
                        k += 1
                        if k < n and lines[k].strip().lower() == "network":
                            k += 1
                        break
                    # Safety: a new row started without an explicit deductible cell
                    if code_re.match(t) or t.upper().startswith("IN:"):
                        break
                    freq_parts.append(t)
                    k += 1

                if code not in seen:
                    seen.add(code)
                    freq = " ".join(freq_parts).strip()
                    age_m = re.search(r"(?:up to|under|to)\s*age\s*(\d+)", freq, re.I)
                    procedures.append({
                        "procedure_code":    code,
                        "benefit_level":     f"{in_m.group(1)}%" if in_m else "N/A",
                        "oon_benefit_level": f"{oon_m.group(1)}%" if oon_m else "N/A",
                        "age_limit":         f"0-{age_m.group(1)}" if age_m else "N/A",
                        "frequency_limit":   freq or "N/A",
                        "waiting_period":    waiting,
                        "deductible":        ded,
                        "category":          category or "N/A",
                    })
                i = k
                continue

        # Otherwise: track the most recent category header (a short, all-letters
        # line that isn't structural noise) to tag the codes that follow it.
        if 1 < len(s) < 40 and re.fullmatch(r"[A-Za-z][A-Za-z /&\-]+", s) \
                and s.lower() not in _DQ_NOISE:
            category = s
        i += 1

    return procedures


def _parse_dentaquest(text: str) -> dict:
    """Parse a DentaQuest (Sun Life) 'Member Details' PDF into the common schema."""
    lines = text.splitlines()

    # ── 1. Patient ─────────────────────────────────────────────────
    name = None
    m = re.search(r"Member information for\s+([A-Z][A-Za-z .'\-]+)", text)
    if m:
        name = m.group(1).strip()
    name = name or _dq_label(lines, "Name")

    level = _dq_label(lines, "Level of coverage") or "N/A"
    # On these plans the member being viewed IS the patient; treat an
    # employee-only/self level as "Self", otherwise carry the level through
    # (matches content_dentaquest.js so has-dependents detection agrees).
    relationship = (level if level != "N/A"
                    and not re.search(r"employee only|self|subscriber|member", level, re.I)
                    else "Self")

    patient = {
        "name":              name or "N/A",
        "dob":               _dq_label(lines, "Date of birth") or "N/A",
        "age":               _dq_label(lines, "Age") or "N/A",
        "member_id":         _dq_label(lines, "ID number") or "N/A",
        "relationship":      relationship,
        "level_of_coverage": level,
    }

    # ── 2. Plan details ────────────────────────────────────────────
    plan_name    = _dq_label(lines, "Plan") or "N/A"
    group_number = _dq_label(lines, "Plan/Group number") or _dq_label(lines, "Group number") or "N/A"
    if group_number != "N/A":
        gm = re.match(r"[\w\-]+", group_number)
        group_number = gm.group(0) if gm else group_number
    network = _dq_label(lines, "Network") or "N/A"

    plan_details = {
        "plan_name":         plan_name,
        "group_number":      group_number,
        "employer_group":    plan_name,   # matcher reads employer_group OR group_name
        "network":           network,
        "level_of_coverage": level,
    }

    # ── 3. Financials ("Benefits at a glance") ─────────────────────
    ind_ded = fam_ded = annual_max = ortho_life = None
    ded_line = _dq_label(lines, "Deductible")
    if ded_line:
        dms = re.findall(r"\$[\d,]+\.?\d*", ded_line)
        if dms:
            ind_ded = _money(dms[0])
        if len(dms) > 1:
            fam_ded = _money(dms[1])
    max_line = _dq_label(lines, "Maximum")
    if max_line:
        mm = re.search(r"\$[\d,]+\.?\d*", max_line)
        if mm:
            annual_max = _money(mm.group(0))
    ortho_line = _dq_label(lines, "Orthodontia max.") or _dq_label(lines, "Orthodontia max")
    if ortho_line:
        om = re.search(r"\$[\d,]+\.?\d*", ortho_line)
        if om:
            ortho_life = _money(om.group(0))

    financials = {
        "annual_max":     {"total": annual_max or "$ 0.00"},
        "deductible_ind": {"total": ind_ded or "$ 0.00"},
        "deductible_fam": {"total": fam_ded or "$ 0.00"},
        "ortho_lifetime": {"total": ortho_life or "$ 0.00"},
    }

    # ── 4. Benefits summary (per-code coverage) ────────────────────
    procedures = _dq_procedures(lines)

    result = {
        "source": "DentaQuest PDF - Member Details",
        "summary": {
            "group_name":   plan_name,
            "group_number": group_number,
            "plan_name":    plan_name,
        },
        "plan_details": plan_details,
        "patient":      patient,
        "financials":   financials,
        "covered_services": [],
        "benefit_coverage": {
            "source":          "DentaQuest PDF - Benefits Summary",
            "procedure_count": len(procedures),
            "procedures":      procedures,
        },
    }

    if group_number in (None, "N/A") and not procedures:
        raise ValueError("Could not extract plan info — DentaQuest PDF layout may have changed.")

    log.info(f"Parsed DentaQuest PDF: group='{group_number}', plan='{plan_name}', "
             f"ind_ded={ind_ded}, annual_max={annual_max}, ortho={ortho_life}, "
             f"{len(procedures)} procedures")
    return result


# ──────────────────────────────────────────────────────────────────
# PARSER REGISTRY — format key → parser fn (built once at import time)
# ──────────────────────────────────────────────────────────────────
_PARSER_REGISTRY = {
    "delta_dental": _parse_delta_dental,
    "guardian":     _parse_guardian,
    "dentaquest":   _parse_dentaquest,
}
