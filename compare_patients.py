import json
import re
import logging
import asyncio
import httpx
from difflib import SequenceMatcher

# ──────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────
OLLAMA_URL     = "http://127.0.0.1:11434/api/generate"
MODEL           = "qwen2.5:7b"
NUM_CTX         = 6144
REQUEST_TIMEOUT = 180
MAX_RETRIES     = 2
RETRY_DELAY     = 3

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# AI API CALLER
# ──────────────────────────────────────────────────────────────────
# Limit concurrent LLM requests to prevent overwhelming Ollama
OLLAMA_SEMAPHORE = asyncio.Semaphore(2)

# Shared HTTP client — reuses the TCP connection pool across all Ollama calls
# instead of opening/closing a new connection for every request.
_HTTP_CLIENT: httpx.AsyncClient | None = None

async def _get_http_client() -> httpx.AsyncClient:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
        _HTTP_CLIENT = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    return _HTTP_CLIENT


async def close_http_client() -> None:
    """Close the shared HTTP client and its connection pool (called on app shutdown)."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is not None and not _HTTP_CLIENT.is_closed:
        await _HTTP_CLIENT.aclose()
    _HTTP_CLIENT = None


async def ask_ollama(prompt: str, temperature: float = 0.0) -> dict:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"num_ctx": NUM_CTX, "temperature": temperature}
    }

    async with OLLAMA_SEMAPHORE:
        client = await _get_http_client()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                res = await client.post(OLLAMA_URL, json=payload)
                res.raise_for_status()
                raw = res.json().get("response", "")
                log.debug(f"Raw Ollama response: {raw[:500]}")
                clean = re.sub(r"```json|```", "", raw).strip()
                start, end = clean.find("{"), clean.rfind("}") + 1
                if start == -1 or end == 0:
                    raise ValueError("No JSON object found in response")
                return json.loads(clean[start:end])
            except Exception as e:
                log.warning(f"Ollama error on attempt {attempt}: {e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
        return {}


# ──────────────────────────────────────────────────────────────────
# HELPER: Safe number parse
# ──────────────────────────────────────────────────────────────────
def _num(val) -> float | None:
    """Convert a value like '$50.00', '80%', '1,750' to a float. Returns None on failure."""
    if val is None:
        return None
    try:
        return float(str(val).replace("$", "").replace("%", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _dollar(text) -> float | None:
    """First dollar amount in a string like '$2,000 Per Calendar Year' → 2000.0."""
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", str(text or ""))
    return float(m.group(1).replace(",", "")) if m else None


# ──────────────────────────────────────────────────────────────────
# PHASE 1A-C: PYTHON-NATIVE EXTRACTION FROM UCCI PORTAL JSON
# ──────────────────────────────────────────────────────────────────
def _extract_ucci_portal_fields(raw: dict) -> dict:
    """
    FORMAT C — UCCI / United Concordia portal scraper output:
      {
        "patient_info": {"group_id": "EMPLOYER NAME / 925015000",
                          "relationship": "CHILD", "your_network": "..."},
        "deductibles_and_maximums": [{"benefit": "Individual Maximum",
                                       "coverage": "$2,000 Per Calendar Year"}, ...],
        "benefit_categories": [{"category": "...", "procedures": [
            {"procedure_code": "D0120", "coverage_or_copay": "100%",
             "limitation": "3 Per Calendar Year | ..."}]}]
      }
    """
    out = {}
    pi = raw.get("patient_info", {})

    # group_id: "ROUND ROCK INDEPENDENT SCHOOL DISTRICT / 925015000"
    gid = str(pi.get("group_id", "") or "")
    if "/" in gid:
        gname, gnum = gid.rsplit("/", 1)
        out["group_name"]   = gname.strip() or None
        out["group_number"] = gnum.strip() or None
    else:
        out["group_name"], out["group_number"] = gid.strip() or None, None

    rel = str(pi.get("relationship", "") or "").lower()
    out["has_dependents"] = rel not in ("", "self", "subscriber", "policyholder") if rel else None

    # Patient is out-of-network: the portal displays OON percentages, while
    # Denticon plan records store in-network values → percentages not comparable.
    portal_oon = "no network" in str(pi.get("your_network", "")).lower()

    # ── FINANCIALS from deductibles_and_maximums ──
    out["individual_deductible"] = None
    out["family_deductible"]     = None
    out["individual_annual_max"] = None
    out["ortho_lifetime_max"]    = None
    for row in raw.get("deductibles_and_maximums", []):
        b  = str(row.get("benefit", "")).lower()
        c  = str(row.get("coverage", ""))
        cl = c.lower().strip()
        val = _dollar(c)
        if "individual deductible" in b:
            # UCCI shows "None" when the plan has no deductible → 0
            out["individual_deductible"] = 0.0 if cl == "none" else val
        elif "family deductible" in b:
            out["family_deductible"] = 0.0 if cl == "none" else val
        elif "individual maximum" in b:
            if "accident" in cl or "implant" in cl:
                continue                      # unrelated special maximums
            if "ortho" in cl:
                out["ortho_lifetime_max"] = val
            elif cl == "none":
                # No annual maximum; Denticon convention records this as 99999
                out["individual_annual_max"] = 99999.0
            elif val is not None:
                out["individual_annual_max"] = val

    # ── PROCEDURES index from benefit_categories ──
    procs: dict[str, dict] = {}
    for cat in raw.get("benefit_categories", []):
        for p in cat.get("procedures", []):
            code = str(p.get("procedure_code", "")).upper().strip()
            if code and code not in procs:
                procs[code] = p

    def _pct(code: str) -> float | None:
        p = procs.get(code)
        if not p or portal_oon:
            return None
        lim = str(p.get("limitation", "")).lower()
        # Patient-specific age gating: the PLAN covers this, but THIS patient
        # aged out. Denticon stores plan-level pct, so skip instead of using 0%.
        if "no coverage due to age limitation" in lim:
            return None
        return _num(p.get("coverage_or_copay"))

    def _age(code: str) -> float | None:
        p = procs.get(code)
        if not p:
            return None
        lim = str(p.get("limitation", ""))
        if "no coverage due to age limitation" in lim.lower():
            # Patient aged out — the row reflects THIS patient's eligibility,
            # not reliable plan-level data. Only ortho ("Age 19 And Older ~
            # Ortho related") reliably states the plan's own age limit there.
            if code.startswith("D8"):
                m = re.search(r"age\s+(\d+)\s+and\s+older", lim, re.IGNORECASE)
                if m:
                    return float(m.group(1))
            return None
        m = re.search(r"under\s+(\d+)\s+years?\s+of\s+age", lim, re.IGNORECASE)
        return float(m.group(1)) if m else None

    def _first_pct(*codes: str) -> float | None:
        for c in codes:
            v = _pct(c)
            if v is not None:
                return v
        return None

    def _first_age(*codes: str) -> float | None:
        for c in codes:
            v = _age(c)
            if v is not None:
                return v
        return None

    out["preventative_D0120_pct"] = _first_pct("D0120", "D0150")
    out["basic_D2331_D2140_pct"]  = _first_pct("D2331", "D2140")
    out["major_D2740_pct"]        = _pct("D2740")
    out["fluoride_D1206_pct"]     = _first_pct("D1206", "D1208")
    out["fluoride_D1206_age"]     = _first_age("D1206", "D1208")
    out["sealants_D1351_pct"]     = _pct("D1351")
    out["sealants_D1351_age"]     = _age("D1351")
    out["space_maint_1510_pct"]   = _pct("D1510")
    out["space_maint_1510_age"]   = _age("D1510")
    out["ortho_D8080_pct"]        = _pct("D8080")
    out["ortho_D8080_age"]        = _age("D8080")

    # Auxiliary differentiator codes (see extract_denticon_plan_fields):
    # help separate duplicate Denticon records of the same plan.
    out["veneer_D2962_pct"]   = _pct("D2962")
    out["curodont_D2991_pct"] = _pct("D2991")
    out["surg_ext_D7210_pct"] = _pct("D7210")

    return out


# ──────────────────────────────────────────────────────────────────
# PHASE 1A: PYTHON-NATIVE EXTRACTION FROM PORTAL DATA
# ──────────────────────────────────────────────────────────────────
def extract_portal_fields(portal_raw: dict) -> dict:
    """
    Extracts required comparison fields from the insurance portal JSON.

    Supports TWO portal data structures:

    FORMAT A (actual scraper output — preferred):
      {
        "metlife_data": {
          "financials": {
            "annual_max":     {"total": "$ 2000.00 total"},
            "deductible_ind": {"total": "$ 50.00 total"},
            "ortho_lifetime": {"total": "$ 3500.00 total"}
          },
          "plan_details": {"employer_group": "CITY OF RACINE"},
          "patient": {"relationship": "Dependent"}
        },
        "benefit_coverage": {
          "procedures": [
            {"procedure_code": "D1206", "benefit_level": "100%", "age_limit": "0-14", ...}
          ]
        }
      }

    FORMAT B (legacy Cigna/old format):
      { "cigna_data": { "coinsurance": [...], "frequencies": [...], "age_limits": [...] } }
    """
    out = {}

    # Unwrap metlife/cigna/anthem/dentaquest/ucci top-level wrapper
    portal = (portal_raw.get("metlife_data") or
              portal_raw.get("cigna_data") or
              portal_raw.get("anthem_data") or
              portal_raw.get("dentaquest_data") or
              portal_raw.get("ucci_data") or
              portal_raw)

    # ── Detect FORMAT C: UCCI / United Concordia scraper output ──
    # Identified by its distinctive top-level sections.
    if isinstance(portal, dict) and portal.get("patient_info") and (
            portal.get("benefit_categories") or portal.get("deductibles_and_maximums")):
        return _extract_ucci_portal_fields(portal)

    # ── Detect FORMAT A: benefit_coverage.procedures ──
    # benefit_coverage may live inside the unwrapped portal (DentaQuest) or at
    # the top level (PDF-parser output / older exports).
    benefit_cov = portal.get("benefit_coverage") or portal_raw.get("benefit_coverage", {})
    procedures  = benefit_cov.get("procedures", [])

    financials   = portal.get("financials", {})
    plan_details = portal.get("plan_details", {})
    patient      = portal.get("patient", {})
    summary      = portal.get("summary", {})

    # ── GROUP ──
    out["group_number"] = (
        plan_details.get("group_number") or
        plan_details.get("group_no") or
        summary.get("group_number")
    )
    out["group_name"] = (
        plan_details.get("employer_group") or
        plan_details.get("group_name") or
        plan_details.get("employer") or
        summary.get("group_name")
    )

    # ── FINANCIALS ──
    def _fin(key: str) -> float | None:
        obj = financials.get(key, {})
        if isinstance(obj, dict):
            # Handles "$ 2000.00 total" or "$2,000.00" style strings
            raw = obj.get("total") or obj.get("remaining") or ""
        else:
            raw = str(obj)
        # Extract the first dollar amount from the string
        m = re.search(r'\$?\s*([\d,]+\.?\d*)', str(raw))
        return float(m.group(1).replace(',', '')) if m else None

    def _first_fin(*keys: str) -> float | None:
        for k in keys:
            v = _fin(k)
            if v is not None:
                return v
        return None

    out["individual_deductible"] = _first_fin("deductible_ind", "individual_deductible")
    out["family_deductible"]     = _first_fin("deductible_fam", "family_deductible")
    out["individual_annual_max"] = _first_fin("annual_max", "individual_annual_max")
    out["ortho_lifetime_max"]    = _first_fin("ortho_lifetime", "ortho_lifetime_max")

    # ── OVERRIDE ORTHO LIFETIME MAX IF EXPLICITLY NOT COVERED ──
    covered_services = portal.get("covered_services", [])
    for cs in covered_services:
        if str(cs.get("category", "")).strip().upper() == "ORTHODONTICS":
            if "not covered" in str(cs.get("in_network", "")).lower():
                out["ortho_lifetime_max"] = 0.0
                break

    # ── FORMAT A: build coverage from procedures[] ──
    if procedures:

        # Build an O(1) lookup index — avoids repeated O(n) scans for each CDT code.
        _proc_index: dict[str, dict] = {}
        for _p in procedures:
            _code = str(_p.get("procedure_code", "")).upper().strip()
            if _code and _code not in _proc_index:
                _proc_index[_code] = _p

        def _proc(code: str) -> dict | None:
            """Return the procedure dict for a given CDT code (O(1) lookup)."""
            return _proc_index.get(code.upper())

        def _proc_pct(code: str) -> float | None:
            """Return plan coverage % from benefit_level field (e.g. '100%' → 100.0)."""
            p = _proc(code)
            return _num(p.get("benefit_level")) if p else None

        def _proc_age(code: str) -> float | None:
            """
            Return the UPPER age bound from age_limit field.
            e.g. '0-14' → 14.0, '0-99' → None (no real cap).
            """
            p = _proc(code)
            if not p:
                return None
            age_str = str(p.get("age_limit", "")).strip()
            m = re.search(r"(\d+)\s*$", age_str)
            if m:
                upper = int(m.group(1))
                return None if upper >= 99 else float(upper)
            return None

        def _first_pct(*codes: str) -> float | None:
            for c in codes:
                v = _proc_pct(c)
                if v is not None:
                    return v
            return None

        def _first_age(*codes: str) -> float | None:
            for c in codes:
                v = _proc_age(c)
                if v is not None:
                    return v
            return None

        # Preventative — D0120 is the primary reference
        pct_prev = _first_pct("D0120", "D0150")
        out["preventative_D0120_pct"] = pct_prev

        # Basic Restorative — D2331 (composite) then D2140 (amalgam)
        out["basic_D2331_D2140_pct"] = _first_pct("D2331", "D2140")

        # Major — D2740 (crown)
        out["major_D2740_pct"] = _proc_pct("D2740")

        # Fluoride — D1206 (varnish) then D1208.
        # NOTE: no inheritance from the preventive pct — a value the portal
        # never stated must not be compared (it fabricates mismatches).
        out["fluoride_D1206_pct"] = _first_pct("D1206", "D1208")
        out["fluoride_D1206_age"] = _first_age("D1206", "D1208")

        # Sealants — D1351
        out["sealants_D1351_pct"] = _proc_pct("D1351")
        out["sealants_D1351_age"] = _proc_age("D1351")

        # Space Maintainer — D1510
        out["space_maint_1510_pct"] = _proc_pct("D1510")
        out["space_maint_1510_age"] = _proc_age("D1510")

        # Orthodontics — D8080
        out["ortho_D8080_pct"] = _proc_pct("D8080")
        out["ortho_D8080_age"] = _proc_age("D8080")

        p_8080 = _proc("D8080")
        if p_8080 and "not covered" in str(p_8080.get("frequency_limit", "")).lower():
            out["ortho_lifetime_max"] = 0.0
            out["ortho_D8080_pct"] = 0.0

    else:
        # ── FORMAT B FALLBACK: old coinsurance[]/frequencies[]/age_limits[] ──
        coinsurance = portal.get("coinsurance", [])
        frequencies = portal.get("frequencies", [])
        age_limits  = portal.get("age_limits", [])

        def _find_pct(kws: list[str]) -> float | None:
            for item in coinsurance:
                cat = item.get("category", "").lower()
                if any(kw.lower() in cat for kw in kws):
                    pp = _num(item.get("patient_pays", ""))
                    # Guard: patient_pays must be a percentage (0-100), not a dollar amount.
                    if pp is not None and 0 <= pp <= 100:
                        return 100 - pp
            return None

        def _find_age(kws: list[str]) -> float | None:
            for item in age_limits:
                t = item.get("type", "").lower()
                if any(kw.lower() in t for kw in kws):
                    v = item.get("age", "")
                    return None if str(v).lower() in ("none", "no limitations", "") else _num(v)
            for item in frequencies:
                proc = item.get("procedure", "").lower()
                if any(kw.lower() in proc for kw in kws):
                    m = re.search(r"(?:after|to)\s+age\s+(\d+)", item.get("limit", ""), re.IGNORECASE)
                    if m:
                        return float(m.group(1))
            return None

        # Only the categories the portal actually states. Fluoride, sealants
        # and space maintainer have NO category of their own in this format —
        # do NOT inherit the preventive pct for them (a fabricated portal
        # value creates false mismatches against real Denticon data).
        out["preventative_D0120_pct"] = _find_pct(["diagnostic", "preventive", "preventative"])
        out["basic_D2331_D2140_pct"]  = _find_pct(["basic restorative", "basic"])
        out["major_D2740_pct"]        = _find_pct(["major restorative", "major", "prosthodontics"])
        out["fluoride_D1206_pct"]     = None
        out["fluoride_D1206_age"]     = _find_age(["fluoride"])
        out["sealants_D1351_pct"]     = None
        out["sealants_D1351_age"]     = _find_age(["sealant"])
        out["space_maint_1510_pct"]   = None
        out["space_maint_1510_age"]   = _find_age(["space maintainer", "space maint"])
        out["ortho_D8080_pct"]        = _find_pct(["orthodontics", "ortho"])
        out["ortho_D8080_age"]        = _find_age(["ortho"])

    # ── DEPENDENT DETECTION ──
    rel = patient.get("relationship", "").lower()
    out["has_dependents"] = rel not in ("", "self", "subscriber") if rel else None

    # NOTE: no family-deductible inference. When the portal doesn't list a
    # family deductible we leave it None so the comparison SKIPS the field —
    # a fabricated value (e.g. 3× individual) contradicts the real plan-level
    # value stored in Denticon and falsely fails six-field validation.

    return out



# ──────────────────────────────────────────────────────────────────
# PHASE 1B: PYTHON-NATIVE EXTRACTION FROM DENTICON PLAN
# ──────────────────────────────────────────────────────────────────
def extract_denticon_plan_fields(plan: dict) -> dict:
    """
    Extracts comparison fields from one Denticon plan.

    PRIORITY ORDER:
      1. Coverage table (structured rows — most reliable)
         - Deductible/Max rows  → financials
         - Code rows (D1510, etc.) → pct + embedded age
         - Category name rows (Preventive, Restorative, etc.) → pct
      2. Benefits notes (regex fallback for anything not in coverage table)
    """
    notes    = plan.get("benefits", {}).get("notes", "")
    coverage = plan.get("coverage", [])
    details  = plan.get("plan_details", {})
    out      = {}

    # Build O(1) indexes for coverage table lookups — avoids repeated O(n) scans.
    # Index 1: lowercase category → row  (for keyword searches)
    _cov_by_cat: list[tuple[str, dict]] = [
        (str(row.get("category", "")).lower(), row) for row in coverage
    ]
    # Index 2: upper-stripped category → row  (for exact code lookups)
    _cov_exact: dict[str, dict] = {}
    _cov_prefix: list[tuple[str, dict]] = []   # (upper_cat, row) for starts-with
    for _row in coverage:
        _cat_u = str(_row.get("category", "")).upper().strip()
        if _cat_u not in _cov_exact:
            _cov_exact[_cat_u] = _row
        _cov_prefix.append((_cat_u, _row))

    # ── HELPER: find a coverage row by category keywords ──
    def _cov(keywords: list[str], field: str = "coverage_pct") -> str | None:
        for cat_lower, row in _cov_by_cat:
            if any(kw.lower() in cat_lower for kw in keywords):
                val = row.get(field, "N/A")
                return None if val in ("N/A", "", None) else val
        return None

    # ── HELPER: find a coverage row by EXACT code prefix (e.g. "D1510") ──
    # The scraper produces duplicate rows: one is the clean short row,
    # the other is the verbose "D1510 YES 100 Once per Lifetime 16 0" row.
    # We prefer the clean short row whose category == code exactly.
    def _code_row(code: str) -> dict | None:
        code_u = code.upper()
        # First pass: exact match (O(1))
        if code_u in _cov_exact:
            return _cov_exact[code_u]
        # Second pass: starts-with match (handles "D1510 YES 100 ..." style)
        for cat_u, row in _cov_prefix:
            if cat_u.startswith(code_u + " "):
                return row
        return None

    # ── HELPER: extract age from the verbose category string "D1510 YES 100 Once per Lifetime 16 0" ──
    # Fields: CODE  DED_WAIVED  PCT  LIMITATION  AGE  ?
    def _code_age(code: str) -> float | None:
        code_u = code.upper()
        for cat_u, row in _cov_prefix:
            if cat_u.startswith(code_u + " "):
                parts = cat_u.split()
                # parts[4] is the age field (0-indexed)
                if len(parts) >= 5:
                    age_val = parts[4]
                    if age_val not in ("0", "99", "N/A", "NC", "NAL"):
                        return _num(age_val)
        return None

    # ─────────────────────────────────────────────
    # 1. GROUP
    # ─────────────────────────────────────────────
    grp_m = re.search(r"GROUP\s*#\s*:\s*(\S+)", notes, re.IGNORECASE)
    emp_m = re.search(r"EMPLOYER\s*:\s*([^\n_]+)", notes, re.IGNORECASE)
    out["group_number"] = grp_m.group(1).strip() if grp_m else (
        details.get("Group #") or details.get("Group No.")
    )
    raw_name = emp_m.group(1).strip() if emp_m else (
        details.get("Employer Name") or details.get("Employer") or ""
    )
    raw_name = re.split(r"GROUP\s*#|WHAT\s+FEE|NETWORK|\n|_", raw_name, maxsplit=1)[0].strip()
    out["group_name"] = raw_name or None

    # Fallback: newer notes templates omit the GROUP #/EMPLOYER lines
    # entirely, but the plan-search table embedded in benefits.full_text has
    # a row per plan:  "<plan_id> <group_number> <fee#> <carrier + employer>
    # <created date> <user> [<modified date> <user>]"
    if not out["group_number"] or not out["group_name"]:
        pid = str(plan.get("ins_plan_id", "")).strip()
        ft  = str(plan.get("benefits", {}).get("full_text", "") or "")
        row_m = re.search(
            rf"(?<![\d/]){re.escape(pid)}\s+0*(\d+)\S*\s+(.*?)\d{{2}}/\d{{2}}/\d{{4}}",
            ft,
        ) if pid and ft else None
        if row_m:
            if not out["group_number"]:
                out["group_number"] = row_m.group(1)
            if not out["group_name"]:
                # carrier + employer blob (e.g. "1360 (IN) Cigna PPO CT
                # TEACHERS' RETIREMENT BOARD") — the fuzzy group-name
                # comparison handles the extra tokens via containment.
                blob = re.sub(r"\s+", " ", row_m.group(2)).strip()
                out["group_name"] = blob or None

    # ─────────────────────────────────────────────
    # 2. FINANCIALS — NOTES ARE PRIMARY (plan-specific)
    #                 COVERAGE TABLE IS FALLBACK (live eligibility, shared across all plans)
    # ─────────────────────────────────────────────
    # IMPORTANT: All Denticon plans for the same patient share the same live coverage
    # table (fetched from the insurer in real time). The plan NOTES contain the values
    # recorded when each individual plan was set up — these are plan-specific and are
    # the correct source for differentiating between plans (e.g., $1500 vs $2000 max).
    #
    # Coverage table rows (used only as fallback):
    #   {"category":"Deductible","ded_waived":"$50.00","coverage_pct":"$50.00","limitation":"$150.00"}
    #   {"category":"Annual Max","ded_waived":"$2,000.00",...,"limitation":"$99,999.00"}
    #   {"category":"Ortho","ded_waived":"$3,500.00",...}

    # Notes fallback for financials
    def _nnum(pat: str) -> float | None:
        m = re.search(pat, notes, re.IGNORECASE)
        return _num(m.group(1)) if m else None

    # Coverage table fallback
    ded_row   = _cov(["deductible"], "ded_waived")
    ded_fam   = _cov(["deductible"], "limitation")
    max_row   = _cov(["annual max"], "ded_waived")
    ortho_row = _cov(["ortho"],      "ded_waived")

    # ── NOTES FIRST → coverage table second ──
    out["individual_deductible"] = _nnum(r"DEDUCTIBLE\s*\$\s*:\s*([^\s_]+)") or _num(ded_row)
    out["family_deductible"]     = _num(ded_fam)   # family ded only available in coverage table
    out["individual_annual_max"] = _nnum(r"MAXIMUM\s*\$\s*:\s*([^\s_]+)")    or _num(max_row)
    out["ortho_lifetime_max"]    = _nnum(r"LIFETIME MAX\s*:\s*([^\s_]+)")     or _num(ortho_row)


    # ─────────────────────────────────────────────
    # 3. DEPENDENT DETECTION — from coverage table
    # ─────────────────────────────────────────────
    rel_row = _cov(["patient rel", "rel. to sub", "relationship"], "ded_waived")
    if rel_row:
        out["has_dependents"] = rel_row.strip().lower() not in ("self", "subscriber", "")
    else:
        out["has_dependents"] = None

    # ─────────────────────────────────────────────
    # 4. COVERAGE PERCENTAGES
    # ─────────────────────────────────────────────

    # ── Preventative D0120 ──
    # Try specific code row first, then category row. The code row can be a
    # junk template row ("D0120 - Periodic Exam" with all N/A values) — fall
    # through to the category row whenever it yields no number.
    d0120_row = _code_row("D0120")
    out["preventative_D0120_pct"] = _num(d0120_row.get("coverage_pct")) if d0120_row else None
    if out["preventative_D0120_pct"] is None:
        cov_prev = _cov(["diagnostic (d0120)", "diagnostic exam periodic", "preventive prophy"])
        out["preventative_D0120_pct"] = _num(cov_prev) or (
            _nnum(r"PREVENTATIVE\s*%\s*:\s*(\d+)") or _nnum(r"PREVENTIVE\s*%\s*:\s*(\d+)")
        )

    # ── Basic / Restorative D2331, D2140 ──
    # In coverage table these show as "Restorative Fillings"
    cov_basic = _cov(["restorative fillings", "restorative"])
    out["basic_D2331_D2140_pct"] = _num(cov_basic) or (
        _nnum(r"BASIC\s*%\s*:\s*(\d+)") or _nnum(r"FILLS\s*:\s*(\d+)%")
    )

    # ── Major / Prosthodontics D2740 ──
    # Coverage table: "Restorative Crowns"
    cov_major = _cov(["restorative crowns"])
    out["major_D2740_pct"] = _num(cov_major) or _nnum(r"MAJOR\s*%\s*:\s*(\d+)")

    # ── Fluoride D1206 ──
    # Coverage table: "Preventive Fluoride"
    cov_fl = _cov(["preventive fluoride", "fluoride"])
    out["fluoride_D1206_pct"] = _num(cov_fl) or _nnum(r"FLOURIDE\s+D1206\s*%\s*:\s*(\d+)")
    if out["fluoride_D1206_pct"] is None:
        # If it's under preventive, inherit preventive pct
        out["fluoride_D1206_pct"] = out["preventative_D0120_pct"]

    # Age: notes first (most explicit), then code-row embedded age
    fl_age_m = re.search(
        r"(?:AGE\s+LIMIT\s+FOR\s+FLOURIDE|FLUORIDE\s+AGE\s+LIMIT)\s*:?\s*(\d+)",
        notes, re.IGNORECASE
    )
    out["fluoride_D1206_age"] = _num(fl_age_m.group(1)) if fl_age_m else _code_age("D1206")

    # ── Sealants D1351 ──
    # Coverage table: "Preventive Sealant"
    cov_seal = _cov(["preventive sealant", "sealant"])
    out["sealants_D1351_pct"] = _num(cov_seal)
    if out["sealants_D1351_pct"] is None:
        out["sealants_D1351_pct"] = _nnum(r"SEALANTS\s+D1351[^\n]*?(\d+)%") or out["preventative_D0120_pct"]

    # Age: look for explicit age limit patterns in notes
    seal_age_m = re.search(
        r"SEALANTS[^\n]*?(?:1[xX](\d+)\s*[Yy]ears|[Aa]ge\s*[Ll]imit\s*:?\s*(\d+))",
        notes, re.IGNORECASE
    )
    if seal_age_m:
        out["sealants_D1351_age"] = _num(seal_age_m.group(1) or seal_age_m.group(2))
    else:
        out["sealants_D1351_age"] = _code_age("D1351")

    # ── Space Maintainer D1510 ──
    # Coverage table: exact code row "D1510" is very reliable here; fall
    # through to the category row / notes when it yields no number.
    d1510_row = _code_row("D1510")
    out["space_maint_1510_pct"] = _num(d1510_row.get("coverage_pct")) if d1510_row else None
    if out["space_maint_1510_pct"] is None:
        cov_space = _cov(["space maint", "space maintainer"])
        out["space_maint_1510_pct"] = _num(cov_space) or _nnum(r"SPACE\s+MAINT[^\n]*(\d+)%")
    out["space_maint_1510_age"] = _code_age("D1510")
    if out["space_maint_1510_age"] is None:
        sm_notes_m = re.search(
            r"SPACE\s+MAINT[^\n]*?(?:1[xX](\d+)\s*[Yy]ears|AGE\s+LIMIT\s*:?\s*(\d+))",
            notes, re.IGNORECASE
        )
        if sm_notes_m:
            out["space_maint_1510_age"] = _num(sm_notes_m.group(1) or sm_notes_m.group(2))

    # ── Auxiliary differentiator codes ──
    # These separate duplicate records of the same plan: stale records lack
    # these rows (or record them 0/"see plan notes"), current ones hold real
    # values that the portal can confirm.
    for _key, _code in (("veneer_D2962_pct", "D2962"),
                        ("curodont_D2991_pct", "D2991"),
                        ("surg_ext_D7210_pct", "D7210")):
        _row = _code_row(_code)
        out[_key] = _num(_row.get("coverage_pct")) if _row else None
    if out["curodont_D2991_pct"] is None:
        out["curodont_D2991_pct"] = _num(_cov(["restorative curodont", "curodont"]))

    # ── Orthodontics D8080 ──
    # Coverage table: "Orthodontics Child" (D8080 is the child ortho code)
    cov_ortho = _cov(["orthodontics child", "orthodontics"])
    out["ortho_D8080_pct"] = _num(cov_ortho)
    if out["ortho_D8080_pct"] is None:
        out["ortho_D8080_pct"] = _nnum(r"ORTHO\s*:\s*(\d+)%") or _nnum(r"Ortho\s+Coverage\s*%\s*:\s*(\d+)")

    # Age: explicit ortho age limit. Newer templates write "AGE LIMIT : UNDER 19".
    ortho_age_m = re.search(
        r"(?:Ortho\s+Age\s+Limit|ORTHO[^\n]*AGE\s+LIMIT)\s*:?\s*(?:UNDER\s+)?(\d+|NAL|NC)",
        notes, re.IGNORECASE
    )
    if ortho_age_m:
        raw_age = ortho_age_m.group(1).upper()
        out["ortho_D8080_age"] = None if raw_age in ("NAL", "NC") else _num(raw_age)
    else:
        out["ortho_D8080_age"] = None

    # ── Clean up NC/NAL string values ──
    for k, v in out.items():
        if isinstance(v, str) and v.upper() in ("NAL", "NC", "N/A", ""):
            out[k] = None

    return out





# ──────────────────────────────────────────────────────────────────
# HELPER: Detect out-of-network / out-of-benefit Denticon plans
# ──────────────────────────────────────────────────────────────────
# These patterns match ONLY when the label value is explicitly "Out".
# Broad phrases like "Out of Network" on their own are intentionally avoided
# because in-network notes also contain that substring
# (e.g. "In / Out of Network: In", "NETWORK BENEFITS (IN/OUT) :In").
_OUT_NETWORK_PATTERNS = [
    # Format A — "In / Out of Network: Out"
    re.compile(r"In\s*/\s*Out\s+of\s+Network\s*:\s*Out\b", re.IGNORECASE),
    # Format B — "NETWORK BENEFITS (IN/OUT) :Out"  ← confirmed real-data format
    re.compile(r"NETWORK\s+BENEFITS\s*\(IN\s*/\s*OUT\)\s*:\s*Out\b", re.IGNORECASE),
    # "Out of Benefit" / "Out-of-Benefit"
    re.compile(r"\bOut[- ]of[- ]Benefit\b", re.IGNORECASE),
]

# Corresponding in-network guards — either label confirms the plan IS in-network.
_IN_NETWORK_GUARDS = [
    re.compile(r"In\s*/\s*Out\s+of\s+Network\s*:\s*In\b",           re.IGNORECASE),
    re.compile(r"NETWORK\s+BENEFITS\s*\(IN\s*/\s*OUT\)\s*:\s*In\b", re.IGNORECASE),
]


def _is_out_of_network_plan(plan: dict) -> bool:
    """
    Returns True when the Denticon plan is flagged as Out-of-Network
    or Out-of-Benefit — meaning portal (in-network) data cannot be
    compared against it and the plan should be skipped entirely.

    Checks (in priority order):
      1. plan_details values  — carrier name sometimes starts with "(OUT)"
      2. benefits.notes text  — contains the explicit in/out label
      3. benefits.full_text   — same check on the verbose full text

    The two recognised label formats in Denticon notes are:
      • "In / Out of Network: Out"
      • "NETWORK BENEFITS (IN/OUT) :Out"   ← primary real-data format
    """
    # 1. plan_details: look for "(OUT)" prefix in any value (e.g. carrier name)
    plan_details = plan.get("plan_details", {})
    for v in plan_details.values():
        if isinstance(v, str) and v.upper().startswith("(OUT)"):
            return True

    # 2 & 3. Search notes and full_text independently.
    #        The in-network guard is applied per-text so that a guard match
    #        in notes doesn't accidentally suppress a check of full_text.
    benefits   = plan.get("benefits", {})
    notes_text = str(benefits.get("notes",     "") or "")
    full_text  = str(benefits.get("full_text", "") or "")

    for text in (notes_text, full_text):
        if not text:
            continue
        # Fast guard: if either in-network label appears in this text block,
        # the plan is explicitly In-Network — no need to check further.
        if any(g.search(text) for g in _IN_NETWORK_GUARDS):
            continue
        # Check for out-of-network / out-of-benefit labels.
        if any(pat.search(text) for pat in _OUT_NETWORK_PATTERNS):
            return True

    return False


# ──────────────────────────────────────────────────────────────────
# PHASE 2: SIX-FIELD VALIDATION + COVERAGE SCORING
# ──────────────────────────────────────────────────────────────────
# Required audit fields, per spec:
#
#   SIX-FIELD VALIDATION (plan identity — these decide whether the portal
#   plan and the Denticon record are the SAME plan):
#     1. Group Number            2. Group Name
#     3. Individual Deductible   4. Family Deductible
#     5. Individual Annual Max   6. Ortho Lifetime Max
#
#   COVERAGE PERCENTAGES:
#     Preventative D0120 | Basic/Restorative D2331+D2140 | Major D2740
#     Fluoride D1206 | Sealants D1351 | Space Maintainer D1510 | Ortho D8080
#
#   AGE LIMITS (required for): Fluoride, Sealants, Space Maintainer, Ortho

_SIX_FIELD_WEIGHTS = {
    "group_number":          20,   # strongest single plan identifier
    "group_name":            10,   # fuzzy-matched (formatting varies)
    "individual_deductible": 10,
    "family_deductible":     10,
    "individual_annual_max": 10,
    "ortho_lifetime_max":    10,
}
_COVERAGE_PCT_WEIGHTS = {
    "preventative_D0120_pct": 5,
    "basic_D2331_D2140_pct":  5,
    "major_D2740_pct":        5,
    "fluoride_D1206_pct":     5,
    "sealants_D1351_pct":     5,
    "space_maint_1510_pct":   5,
    "ortho_D8080_pct":        5,
}
_AGE_LIMIT_WEIGHTS = {
    "fluoride_D1206_age":   3,
    "sealants_D1351_age":   3,
    "space_maint_1510_age": 3,
    "ortho_D8080_age":      3,
}
# Auxiliary codes — not part of the audit spec, but they separate duplicate
# Denticon records of the same plan: stale records lack these coverage rows.
# Only scored when the portal provides them (currently UCCI/FORMAT C does).
_AUX_WEIGHTS = {
    "veneer_D2962_pct":   2,
    "curodont_D2991_pct": 2,
    "surg_ext_D7210_pct": 2,
}

# Credit granted when the portal has a value but the Denticon record has
# none: missing data is weaker evidence than a contradicting value.
_MISSING_CREDIT = 0.4


# Tolerance for numeric comparisons (±2% of the portal value).
# Handles minor rounding differences between portal and Denticon records.
_NUMERIC_TOLERANCE = 0.02


def _values_match(pval, dval) -> bool:
    """
    Returns True when two extracted field values are considered equal.
    - Floats: match within ±2% of the portal value (avoids false mismatches
      from rounding, e.g. 1999.0 vs 2000.0).
    - Everything else: exact equality.
    """
    if pval is None or dval is None:
        return pval == dval
    if isinstance(pval, float) and isinstance(dval, (int, float)):
        if pval == 0:
            return dval == 0
        return abs(pval - float(dval)) / abs(pval) <= _NUMERIC_TOLERANCE
    return pval == dval


def _digits(val) -> str:
    """Only the digits of a value — normalises group numbers for comparison."""
    return re.sub(r"\D", "", str(val or ""))


def _group_numbers_match(pnum, dnum) -> bool:
    """Digits-only comparison; suffix match tolerates prefixes/subgroup
    padding (e.g. '0925015000' vs '925015000')."""
    pg, dg = _digits(pnum), _digits(dnum)
    return bool(pg and dg) and (pg == dg or pg.endswith(dg) or dg.endswith(pg))


def _group_name_ratio(pname, dname) -> float:
    """
    0.0-1.0 similarity between group names. Containment counts as a full
    match ('CITY OF RACINE' inside 'CITY OF RACINE WI GROUP').
    """
    pn = re.sub(r"\s+", " ", str(pname or "")).strip().lower()
    dn = re.sub(r"\s+", " ", str(dname or "")).strip().lower()
    if not pn or not dn:
        return 0.0
    if pn in dn or dn in pn:
        return 1.0
    return SequenceMatcher(None, pn, dn).ratio()


def _python_score(portal: dict, denticon: dict) -> dict:
    """
    Deterministic field-by-field validation per the audit spec.

    Every field where the PORTAL has a value is checked (portal is the
    source of truth; portal-null fields are skipped entirely):
      - match            → full weight
      - denticon missing → _MISSING_CREDIT × weight (missing ≠ contradiction)
      - mismatch         → 0 points, recorded

    Numeric comparisons use a ±2% tolerance so rounding differences
    (e.g. 1999.0 vs 2000.0) don't create false mismatches.

    Returns:
      {
        "score":                  0-100, normalised to the fields checked,
        "mismatches":             ["field: portal=X vs denticon=Y", ...],
        "six_field_mismatches":   [field, ...]  (subset of the six identity fields),
        "six_field_summary":      {"passed": n, "failed": n, "missing": n, "checked": n},
        "validation":             {field: {"portal", "denticon", "status", "tier"}},
      }
    """
    earned, total = 0.0, 0.0
    mismatches: list[str] = []
    six_failed: list[str] = []
    validation: dict[str, dict] = {}

    def _record(field, pval, dval, status, weight, credit, tier):
        nonlocal earned, total
        validation[field] = {"portal": pval, "denticon": dval,
                             "status": status, "tier": tier}
        if status == "not_checked":
            return
        total  += weight
        earned += credit * weight
        if status == "mismatch":
            mismatches.append(f"{field}: portal={pval} vs denticon={dval}")
            if tier == "six_field":
                six_failed.append(field)

    def _status(pval, dval) -> tuple[str, float]:
        if pval is None:
            return "not_checked", 0.0
        if dval is None:
            return "denticon_missing", _MISSING_CREDIT
        if _values_match(pval, dval):
            return "match", 1.0
        return "mismatch", 0.0

    # ── 1. SIX-FIELD VALIDATION ─────────────────────────────
    # Group Number
    pnum, dnum = portal.get("group_number"), denticon.get("group_number")
    if not _digits(pnum):
        st, cr = "not_checked", 0.0
    elif not _digits(dnum):
        st, cr = "denticon_missing", _MISSING_CREDIT
    elif _group_numbers_match(pnum, dnum):
        st, cr = "match", 1.0
    else:
        st, cr = "mismatch", 0.0
    _record("group_number", pnum, dnum, st, _SIX_FIELD_WEIGHTS["group_number"], cr, "six_field")

    # Group Name — fuzzy: formatting/abbreviation differences shouldn't
    # disqualify a plan, but a clearly different employer should.
    pname, dname = portal.get("group_name"), denticon.get("group_name")
    if not str(pname or "").strip():
        st, cr = "not_checked", 0.0
    elif not str(dname or "").strip():
        st, cr = "denticon_missing", _MISSING_CREDIT
    else:
        ratio = _group_name_ratio(pname, dname)
        if ratio >= 0.75:
            st, cr = "match", 1.0
        elif ratio >= 0.50:
            st, cr = "partial", 0.5      # likely same employer, abbreviated
        else:
            st, cr = "mismatch", 0.0
    _record("group_name", pname, dname, st, _SIX_FIELD_WEIGHTS["group_name"], cr, "six_field")

    # Deductibles & maximums
    for field in ("individual_deductible", "family_deductible",
                  "individual_annual_max", "ortho_lifetime_max"):
        pval, dval = portal.get(field), denticon.get(field)
        st, cr = _status(pval, dval)
        _record(field, pval, dval, st, _SIX_FIELD_WEIGHTS[field], cr, "six_field")

    # ── 2. COVERAGE PERCENTAGES ─────────────────────────────
    for field, weight in _COVERAGE_PCT_WEIGHTS.items():
        pval, dval = portal.get(field), denticon.get(field)
        st, cr = _status(pval, dval)
        _record(field, pval, dval, st, weight, cr, "coverage_pct")

    # ── 3. AGE LIMITS ───────────────────────────────────────
    for field, weight in _AGE_LIMIT_WEIGHTS.items():
        pval, dval = portal.get(field), denticon.get(field)
        st, cr = _status(pval, dval)
        _record(field, pval, dval, st, weight, cr, "age_limit")

    # ── 4. AUXILIARY DIFFERENTIATORS ────────────────────────
    for field, weight in _AUX_WEIGHTS.items():
        pval, dval = portal.get(field), denticon.get(field)
        st, cr = _status(pval, dval)
        _record(field, pval, dval, st, weight, cr, "auxiliary")

    six_statuses = [v["status"] for f, v in validation.items() if v["tier"] == "six_field"]
    six_summary = {
        "passed":  sum(1 for s in six_statuses if s in ("match", "partial")),
        "failed":  len(six_failed),
        "missing": sum(1 for s in six_statuses if s == "denticon_missing"),
        "checked": sum(1 for s in six_statuses if s != "not_checked"),
    }

    return {
        "score":                round(earned / total * 100) if total else 0,
        "mismatches":           mismatches,
        "six_field_mismatches": six_failed,
        "six_field_summary":    six_summary,
        "validation":           validation,
    }


async def compare_plans(plan_id: str, portal_sim: dict, denticon_sim: dict) -> dict:
    """
    Phase 2 comparison:
    - Deterministic six-field validation + coverage/age scoring.
    - AI is consulted only for genuinely ambiguous scores (50-79%).
    """
    result_s   = _python_score(portal_sim, denticon_sim)
    score      = result_s["score"]
    mismatches = result_s["mismatches"]
    six_failed = result_s["six_field_mismatches"]

    base = {
        "confidence_score":         score,
        "mismatches":               mismatches,
        "matching_id":              plan_id,
        "six_field_validation":     result_s["six_field_summary"],
        "six_field_mismatches":     six_failed,
        "six_field_mismatch_count": len(six_failed),
        "field_validation":         result_s["validation"],
    }

    # ── Hard rule: ANY six-field mismatch = not the same plan ──
    # The six identity fields (group number/name, deductibles, annual max,
    # ortho lifetime max) define the plan; a contradiction in any of them
    # is a deterministic rejection — no AI needed.
    if six_failed:
        return {**base, "match_found": False,
                "reason": (f"Six-field validation FAILED — mismatched field(s): "
                           f"{', '.join(six_failed)} (score {score}%).")}

    # ── Fast path: clear match or clear rejection ──
    summary = result_s["six_field_summary"]
    if score >= 80:
        return {**base, "match_found": True,
                "reason": (f"Six-field validation passed "
                           f"({summary['passed']}/{summary['checked']} identity fields), "
                           f"score {score}%.")}
    if score < 50:
        return {**base, "match_found": False,
                "reason": (f"Score {score}% — too many coverage fields differ "
                           f"or are missing from the Denticon record.")}

    # ── Ambiguous zone (50-79%, no six-field failures): ask AI ──
    # Typically a sparse Denticon record or coverage-percentage disagreements.
    log.info(f"Plan {plan_id}: ambiguous score {score}%, escalating to AI.")

    six_context      = ", ".join(_SIX_FIELD_WEIGHTS)
    coverage_context = ", ".join(_COVERAGE_PCT_WEIGHTS)
    age_context      = ", ".join(_AGE_LIMIT_WEIGHTS)

    prompt = f"""You are an expert dental insurance auditor. Your task is to decide if a portal plan and a Denticon plan refer to the SAME insurance plan.

SIX IDENTITY FIELDS (a mismatch here strongly indicates a different plan):
{six_context}

COVERAGE PERCENTAGE FIELDS (minor differences may be acceptable):
{coverage_context}

AGE LIMIT FIELDS (minor differences may be acceptable):
{age_context}

SOURCE OF TRUTH (Portal data scraped live from the insurer):
{json.dumps(portal_sim, indent=2)}

CANDIDATE DENTICON PLAN (ID: {plan_id}, data entered when the plan was set up):
{json.dumps(denticon_sim, indent=2)}

Python pre-scoring already found these mismatches: {mismatches}
Python confidence score: {score}%

Decision rules:
1. If a portal value is null, IGNORE that field entirely — do not treat it as a mismatch.
2. If a denticon value is null but portal has a real value, treat as a MISMATCH.
3. For numeric fields (deductibles, maximums, percentages), allow ±2% tolerance for rounding.
4. group_number/group_name: ignore if portal value is null.
5. Focus your reasoning on CRITICAL fields first.

Respond ONLY with valid JSON (no prose, no markdown):
{{"match_found": true/false, "confidence_score": 0-100, "mismatches": [], "reason": "one sentence"}}"""

    result = await ask_ollama(prompt, temperature=0.0)
    result.setdefault("match_found", score >= 65)
    result.setdefault("confidence_score", score)
    result.setdefault("mismatches", mismatches)
    result.setdefault("reason", f"AI adjudicated ambiguous case (python_score={score}%).")
    # Deterministic validation detail always comes from the Python pass,
    # regardless of what the AI returned (the AI may adjust confidence_score).
    for k, v in base.items():
        if k != "confidence_score":
            result[k] = v

    # The AI only adjudicates match_found/confidence — its mismatch lists
    # hallucinate (e.g. reporting merely-missing fields as contradictions),
    # so the mismatch list stays the deterministic Python one (set above).
    return result



# ──────────────────────────────────────────────────────────────────
# TIE-BREAK HELPERS — differentiate duplicate plan records
# ──────────────────────────────────────────────────────────────────
# Offices often keep several records of the SAME insurance plan (created by
# different verifiers over the years). Their benefit values are identical, so
# scoring ties. Two patient-independent signals break the tie:
#   1. carrier record match — the patient block's primary_insurance.carrier_name
#      names the carrier record this patient is attached to in Denticon.
#   2. recency — newest Created (then Modified) date from the plan-search table
#      embedded in benefits.full_text.

def _parse_mdY(date_str: str) -> tuple:
    """'03/05/2026' → (2026, 3, 5); unparseable → (0, 0, 0)."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(date_str or ""))
    return (int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else (0, 0, 0)


def _plan_record_meta(plan: dict, patient_carrier: str) -> tuple[bool, tuple, tuple]:
    """
    Returns (carrier_matches, created_date, modified_date) for one Denticon plan,
    parsed from the plan-search table in benefits.full_text. Row format:
      "74400 777777018 1274 UCCI FEDVIP PID 54771 FEDVIP HIGH OPTION
       01/01/2025 ISPACEGA22937 01/30/2026 MEDSMANSURI2937"
    """
    pid = str(plan.get("ins_plan_id", "")).strip()
    ft  = str(plan.get("benefits", {}).get("full_text", "") or "")
    m = re.search(
        rf"(?<![\d/]){re.escape(pid)}\s+[\d/]+\s+\d+\s+(.*?)"      # carrier + employer text
        rf"(\d{{2}}/\d{{2}}/\d{{4}})\s+\S+"                        # created date + user
        rf"(?:\s+(\d{{2}}/\d{{2}}/\d{{4}}))?",                     # modified date (optional)
        ft,
    ) if pid and ft else None
    if not m:
        return False, (0, 0, 0), (0, 0, 0)
    row_text = re.sub(r"\s+", " ", m.group(1)).upper()
    carrier_ok = bool(patient_carrier) and patient_carrier in row_text
    return carrier_ok, _parse_mdY(m.group(2)), _parse_mdY(m.group(3) or "")


def _normalize_carrier(name) -> str:
    """Patient carrier name, truncation dots stripped, for substring matching."""
    s = re.sub(r"\s+", " ", str(name or "")).upper().strip()
    return s.rstrip(". ").strip()


# ──────────────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ──────────────────────────────────────────────────────────────────
async def match_insurance_plan(portal_raw: dict, denticon_wrapper: dict) -> dict:
    """
    Main function called by FastAPI.
    1. Extracts structured fields from the portal JSON (Python-native).
    2. For each Denticon plan, extracts structured fields (Python-native regex).
    3. Sends both to the AI for a clean, fast comparison.
    Returns the best matching plan result.
    """

    # ── Step 1: Extract Portal Fields ──
    log.info("\n═══ STEP 1: Extracting portal fields ═══")
    portal_sim = extract_portal_fields(portal_raw)
    log.info(f"Portal structured data:\n{json.dumps(portal_sim, indent=2)}\n")

    # ── Step 2: Get Denticon Plans ──
    denticon_data = denticon_wrapper.get("denticon_data", denticon_wrapper)
    plans = denticon_data.get("plans", []) if isinstance(denticon_data, dict) else denticon_data

    if not plans:
        return {"match_found": False, "matching_id": None,
                "reason": "Denticon plan list is empty.", "confidence_score": 0}

    log.info(f"Found {len(plans)} Denticon plans to evaluate.\n")

    # ── Tie-break metadata: which carrier record is the patient attached to? ──
    patient_carrier = _normalize_carrier(
        (denticon_data.get("primary_insurance", {}) or {}).get("carrier_name", "")
        if isinstance(denticon_data, dict) else ""
    )
    plan_meta = {
        str(p.get("ins_plan_id", "?")): _plan_record_meta(p, patient_carrier)
        for p in plans
    }

    # ── Step 3: Evaluate ALL Plans concurrently, collect results ──
    async def process_plan(p):
        plan_id = str(p.get("ins_plan_id", "?"))
        log.info(f"\n--- Evaluating Plan ID: {plan_id} ---")

        # ── Early exit: skip Out-of-Network / Out-of-Benefit plans ──
        # Portal data is always in-network; comparing it against an out-of-network
        # Denticon plan will never produce a valid match.
        if _is_out_of_network_plan(p):
            log.info(
                f"Plan {plan_id}: flagged as Out-of-Network or Out-of-Benefit — skipping."
            )
            return None

        denticon_sim = extract_denticon_plan_fields(p)
        log.info(f"Denticon extracted:\n{json.dumps(denticon_sim, indent=2)}")

        # Skip plans where extraction failed entirely
        if not denticon_sim.get("group_number") and denticon_sim.get("individual_deductible") is None:
            log.warning(f"Plan {plan_id}: insufficient extracted data, skipping.")
            return None

        result = await compare_plans(plan_id, portal_sim, denticon_sim)
        return result

    tasks = [process_plan(p) for p in plans]
    # return_exceptions=True so one malformed plan can't abort the whole batch.
    completed_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results = []
    for result in completed_results:
        if isinstance(result, Exception):
            log.warning(f"Skipping a plan that failed to evaluate: {result!r}")
            continue
        if result is None:
            continue


        confidence     = result.get("confidence_score", 0)
        is_match       = result.get("match_found", False)
        critical_count = result.get("six_field_mismatch_count", 0)

        log.info(
            f"Plan {result.get('matching_id')}: match={is_match}, confidence={confidence}%, "
            f"six_field_mismatches={critical_count}, "
            f"mismatches={result.get('mismatches', [])}"
        )
        all_results.append((confidence, critical_count, result))

    if not all_results:
        return {"match_found": False, "matching_id": None,
                "reason": "No viable Denticon plans to evaluate.", "confidence_score": 0,
                "all_plans_ranked": []}

    # ── Step 4: Rank — six-field passes first, then fewer six-field
    # mismatches, then higher score. Equal scores (duplicate plan records)
    # are broken by: the carrier record the patient is attached to, then
    # the newest Created / Modified dates. ──
    def _rank_key(x):
        conf, crit, r = x
        carrier_ok, created, modified = plan_meta.get(
            str(r.get("matching_id")), (False, (0, 0, 0), (0, 0, 0))
        )
        # Plans that PASSED six-field validation always outrank rejected ones,
        # even when a rejected plan happens to score higher overall.
        return (0 if r.get("match_found") else 1, crit, -conf,
                0 if carrier_ok else 1,
                tuple(-v for v in created), tuple(-v for v in modified))

    all_results.sort(key=_rank_key)

    # Build the ranked summary list for the UI (all plans).
    # "critical_mismatches" = failures among the SIX identity fields
    # (group number/name, deductibles, annual max, ortho lifetime max).
    all_plans_ranked = [
        {
            "plan_id":              r.get("matching_id"),
            "confidence_score":     conf,
            "critical_mismatches":  crit,
            "six_field_validation": r.get("six_field_validation"),
            "mismatches":           r.get("mismatches", []),
            "match_found":          r.get("match_found", False),
        }
        for conf, crit, r in all_results
    ]

    best_confidence, best_critical, best_result = all_results[0]
    best_result["all_plans_ranked"] = all_plans_ranked

    # ── Step 5: Detect TIES at the top score ──
    # If multiple plans share the exact same top confidence score, flag it as a
    # tie so the UI can warn the user to review manually.
    tied = [
        {"plan_id": r.get("matching_id"), "confidence_score": conf, "critical_mismatches": crit}
        for conf, crit, r in all_results
        if (r.get("match_found", False), crit, conf)
           == (best_result.get("match_found", False), best_critical, best_confidence)
    ]
    # Only report a tie when the tie-break signals (carrier record, dates)
    # ALSO tie — otherwise the ranking above already picked a winner.
    if len(tied) > 1 and _rank_key(all_results[0]) == _rank_key(all_results[1]):
        log.warning(
            f"\n⚠️  TIE detected — {len(tied)} plans share {best_confidence}% confidence: "
            + ", ".join(str(t["plan_id"]) for t in tied)
        )
        best_result["tie"]        = True
        best_result["tied_plans"] = tied
        best_result["match_found"] = False
        best_result["all_plans_ranked"] = all_plans_ranked
        return best_result

    if best_result.get("match_found") and best_critical == 0:
        log.info(f"\n✅ BEST MATCH → Plan {best_result.get('matching_id')} "
                 f"(confidence={best_confidence}%, critical_mismatches={best_critical})")
        return best_result

    # No clean match — return best as "closest" with match_found=False
    log.warning(f"\n❌ No high-confidence match. Best was plan "
                f"{best_result.get('matching_id')} at {best_confidence}% "
                f"with {best_critical} critical mismatch(es).")
    best_result["match_found"]         = False
    best_result["closest_plan_id"]     = best_result.get("matching_id")
    best_result["closest_confidence"]  = best_confidence
    best_result["closest_mismatches"]  = best_result.get("mismatches", [])
    return best_result