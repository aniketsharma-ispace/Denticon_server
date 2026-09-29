"""
The insurance breakdown, field by field.

Takes a portal export and a Denticon export and produces the flat record every
downstream view reads — identity, maximums, deductibles, provisions and a row
per procedure code. Carrier-specific reading is done first, by the modules in
`portals/`; what is left here is the part that is the same whichever carrier
the export came from, expressed in the fields this client uses.
"""

import json
import re
from datetime import datetime, timedelta, timezone

import requests

from .portals.common import (_blank_present_end_date, _display_plan_type, _dollar,
                             _effective_date_month, _format_history_dates,
                             _triple_individual_deductible, clean)
from .portals.aetna import (_apply_aetna_output_rules, _is_aetna_portal,
                            _normalize_aetna_portal)
from .portals.cigna import (_apply_cigna_output_rules, _cigna_frequency_is_unavailable,
                            _is_cigna_portal, _normalize_cigna_portal)
from .portals.delta_dental import (_apply_dd_output_rules, _is_dd_portal,
                                   _normalize_dd_portal)
from .portals.metlife import _extract_metlife_ortho_age_limit


# ═══════════════════════════════════════════════════════════════════════════════
#  LLM PROVISION INTERPRETER  (formerly interpret_provisions.py)
# ═══════════════════════════════════════════════════════════════════════════════

OLLAMA_URL          = "http://localhost:11434/api/generate"


OLLAMA_MODEL        = "llama3.2"


OLLAMA_TIMEOUT      = 60


_LLM_DEFAULT_ANSWERS = {
    "molars_only_sealants":          "—",
    "posterior_composite_downgrade": "—",
    "porcelain_posterior_downgrade": "—",
    "d2950_same_day_crown":          "—",
    "ortho_payment_frequency":       "—",
    "ortho_age_limit":               "—",
}


_LLM_QUESTIONS_PROMPT = """
You are a dental insurance benefits analyst. Read the plan provisions below
and answer each question. Respond ONLY with a valid JSON object — no explanation,
no markdown fences, just raw JSON.

Use "Yes" / "No" for boolean questions, a short string for free-text, "—" if not present.

Questions:
1. "molars_only_sealants"           — For D1351 Sealants, are they limited to permanent molars only?
2. "posterior_composite_downgrade"  — Does the plan downgrade posterior composite fillings to amalgam?
3. "porcelain_posterior_downgrade"  — Does the plan downgrade porcelain/veneer crowns on posterior teeth to full cast?
4. "d2950_same_day_crown"           — Does the plan allow D2950 (build-up) same day as a crown? Answer Yes/No/Not stated.
5. "ortho_payment_frequency"        — What is the orthodontic payment frequency? (e.g. "End of quarter")
6. "ortho_age_limit"                — Maximum age for orthodontic coverage for a child/adolescent?

PLAN DATA:
{context}

Respond with ONLY a JSON object.
"""


def _llm_build_context(portal_raw: dict) -> str:
    """Extract provisions + key procedure notes into a plain-text context string."""
    lines  = []
    ml     = portal_raw.get("metlife_data") or portal_raw
    procs  = (portal_raw.get("benefit_coverage") or {}).get("procedures", [])

    provisions = ml.get("provisions", [])
    if provisions:
        lines.append("=== PLAN PROVISIONS ===")
        for p in provisions:
            r = p.get("rule", "").strip()
            v = p.get("value", "").strip()
            if r and v:
                lines.append(f"  [{r}]: {v}")

    interesting = {"D1351","D2331","D2332","D2740","D2950",
                   "D0120","D0150","D0140","D1110","D4910","D8080","D8090"}
    proc_lines = []
    for p in procs:
        code = p.get("procedure_code","").upper()
        if code in interesting:
            proc_lines.append(
                f"  {code}: freq='{p.get('frequency_limit','')}' "
                f"desc='{p.get('description','')}'"
            )
    if proc_lines:
        lines.append("\n=== KEY PROCEDURE NOTES ===")
        lines.extend(proc_lines)

    return "\n".join(lines)


def _llm_call_ollama(prompt: str):
    payload = {
        "model": OLLAMA_MODEL, "prompt": prompt,
        "stream": False, "format": "json",
        "options": {"temperature": 0.0, "num_predict": 512},
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)
    except requests.exceptions.ConnectionError:
        print("[LLM] ⚠ Ollama not reachable")
        return None
    except Exception as e:
        print(f"[LLM] ⚠ Ollama error: {e}")
        return None


def _llm_normalize(raw: dict) -> dict:
    result = dict(_LLM_DEFAULT_ANSWERS)
    for k in _LLM_DEFAULT_ANSWERS:
        v = raw.get(k)
        if v is not None:
            result[k] = str(v).strip()
    for k in ["molars_only_sealants","posterior_composite_downgrade",
              "porcelain_posterior_downgrade"]:
        v = result[k].lower()
        if v in ("true","1","yes"): result[k] = "Yes"
        elif v in ("false","0","no"): result[k] = "No"
    return result


def _interpret_provisions(portal_raw: dict) -> dict:
    """
    Call LLM to answer interpretive questions from plan provisions.
    Returns a flat dict. Never raises — falls back to defaults on error.
    """
    context = _llm_build_context(portal_raw)
    if not context.strip():
        return dict(_LLM_DEFAULT_ANSWERS)

    prompt = _LLM_QUESTIONS_PROMPT.format(context=context)

    raw = _llm_call_ollama(prompt)

    if raw is None:
        print("[LLM] ⚠ All LLM calls failed — using defaults")
        return dict(_LLM_DEFAULT_ANSWERS)

    answers = _llm_normalize(raw)
    print("[LLM] ✓", json.dumps(answers, indent=2))
    return answers


# ═══════════════════════════════════════════════════════════════════════════════
#  RULE-BASED DETERMINISTIC INTERPRETER
# ═══════════════════════════════════════════════════════════════════════════════

def _rule_based_interp(portal_raw: dict, procs_map: dict) -> dict:
    """
    Parse note-row answers deterministically from provisions + procedure data.
    Returns a partial dict; '—' means "couldn't determine, let LLM try".
    """
    ml         = portal_raw.get('metlife_data') or portal_raw
    provisions = ml.get('provisions', []) if isinstance(ml, dict) else []
    bc_procs   = (portal_raw.get('benefit_coverage') or {}).get('procedures', [])

    proc_by_code = {p.get('procedure_code','').upper(): p for p in bc_procs}

    answers = dict(_LLM_DEFAULT_ANSWERS)

    # ── 1. Molars only for sealants (D1351) — SEE FIX #2 below ───────────────
    # (Moved to _rule_based_molars_only which is called from _extract)

    # ── 2. Posterior composite / porcelain downgrade — SEE FIX #4 below ──────
    # (Moved to dedicated parsers called from _extract)

    for p in provisions:
        rule  = str(p.get('rule',  '')).lower()
        value = str(p.get('value', '')).lower()

        # ── 3. D4910 + D1110 share frequency ──────────────────────────────────
        if 'cleaning' in rule or 'periodontal maintenance' in rule:
            if 'combines' in value or 'combined' in value:
                answers['d4910_d1110_share_freq'] = 'Yes'
            elif 'does not combine' in value or 'separate' in value:
                answers['d4910_d1110_share_freq'] = 'No'

        # ── 4. Ortho payment frequency ────────────────────────────────────────
        if 'ortho payment' in rule or 'payment method' in rule:
            v = p.get('value', '').strip()
            if v:
                answers['ortho_payment_frequency'] = v

        # ── 5. Ortho age limit ────────────────────────────────────────────────
        if 'maximum age for orthodontic' in rule or ('ortho' in rule and 'age' in rule):
            m = re.search(r'child\s*:\s*(\d+)', value, re.IGNORECASE)
            if m:
                answers['ortho_age_limit'] = m.group(1)

    # ── 6. D0120/D0150 share with D0140 ──────────────────────────────────────
    freqs = {
        c: proc_by_code.get(c, {}).get('frequency_limit', '')
        for c in ('D0120', 'D0150', 'D0140')
    }
    if all(freqs.values()) and len(set(
        re.sub(r'\s+', ' ', f).upper() for f in freqs.values()
    )) == 1:
        answers['d0120_d0150_share_d0140'] = 'Yes'

    return answers


# ═══════════════════════════════════════════════════════════════════════════════
#  FIX #2 — Molars-only sealants: purely frequency-string based
# ═══════════════════════════════════════════════════════════════════════════════

def _rule_molars_only_sealants(procs_map: dict) -> str:
    """Resolve the permanent-molars question only from explicit website text."""
    p = procs_map.get('D1351')
    if not p:
        return ''

    freq_upper = str(p.get('frequency_limit', '')).upper().strip()
    if not freq_upper:
        return ''

    has_permanent = 'PERMANENT' in freq_upper
    has_molar = 'MOLAR' in freq_upper
    has_non_molar = any(
        word in freq_upper
        for word in ('PREMOLAR', 'BICUSPID', 'PRIMARY', 'ALL TEETH', 'ANY TOOTH')
    )

    if has_permanent and has_molar and not has_non_molar:
        return 'Yes'
    if has_non_molar:
        return 'No'
    return ''


# ═══════════════════════════════════════════════════════════════════════════════
#  FIX #3 — D2950 same day as crown: check D2740 coverage
# ═══════════════════════════════════════════════════════════════════════════════

def _rule_d2950_same_day_crown(procs_map: dict) -> str:
    """
    Return 'Yes' if D2740 exists in the plan AND is not marked as 'Not Covered'.
    Return 'No' if D2740 is explicitly not covered.
    Return '—' if D2740 is absent.
    """
    p = procs_map.get('D2740')
    if not p:
        return '—'

    freq_upper  = str(p.get('frequency_limit', '')).upper()
    level_upper = str(p.get('benefit_level',   '')).upper()

    if 'NOT COVERED' in freq_upper or level_upper in ('N/A', 'NOT COVERED', '0%', '0'):
        return 'No'

    # D2740 is present and covered → build-up same day is allowed
    return 'Yes'


# ═══════════════════════════════════════════════════════════════════════════════
#  FIX #4 — Alternate-benefit downgrade rules: parse provision sentences
# ═══════════════════════════════════════════════════════════════════════════════

def _rule_alternate_benefit_downgrades(provisions: list) -> dict:
    """
    Scan every provision whose rule contains 'alternate benefit' (case-insensitive).
    Parse the value text for the two canonical sentences:

      "amalgam filling for composite fillings performed on molar teeth: Yes/No"
      "full cast restoration for porcelain or veneer materials on molar teeth: Yes/No"
      "full cast restoration for porcelain or veneer crowns on bicuspid teeth: Yes/No"

    A downgrade applies ('Yes') when EITHER molars OR bicuspids sentence is 'Yes'.
    Returns dict with keys:
        'posterior_composite_downgrade'  → 'Yes' | 'No' | '—'
        'porcelain_posterior_downgrade'  → 'Yes' | 'No' | '—'
    """
    composite_answer  = '—'
    porcelain_answer  = '—'

    for p in provisions:
        rule  = str(p.get('rule',  '')).lower()
        value = str(p.get('value', ''))

        if 'alternate benefit' not in rule and 'alternate benefits' not in rule:
            continue

        # ── Composite → amalgam on molars ────────────────────────────────────
        # Sentence: "...amalgam filling for composite fillings performed on molar teeth: Yes/No"
        m = re.search(
            r'amalgam\s+filling\s+for\s+composite\s+fillings\s+performed\s+on\s+molar\s+teeth\s*:\s*(yes|no)',
            value,
            re.IGNORECASE,
        )
        if m:
            composite_answer = 'Yes' if m.group(1).lower() == 'yes' else 'No'

        # ── Porcelain/veneer → full cast on molars ────────────────────────────
        # Sentence: "...full cast restoration for porcelain or veneer materials on molar teeth: Yes/No"
        m_molar = re.search(
            r'full\s+cast\s+restoration\s+for\s+porcelain\s+or\s+veneer\s+(?:materials|crowns)\s+on\s+molar\s+teeth\s*:\s*(yes|no)',
            value,
            re.IGNORECASE,
        )
        # Sentence: "...full cast restoration for porcelain or veneer crowns on bicuspid teeth: Yes/No"
        m_bicuspid = re.search(
            r'full\s+cast\s+restoration\s+for\s+porcelain\s+or\s+veneer\s+(?:materials|crowns)\s+on\s+bicuspid\s+teeth\s*:\s*(yes|no)',
            value,
            re.IGNORECASE,
        )

        molar_yes    = m_molar    and m_molar.group(1).lower()    == 'yes'
        bicuspid_yes = m_bicuspid and m_bicuspid.group(1).lower() == 'yes'

        # If either molar or bicuspid sentence was found, resolve the answer
        if m_molar or m_bicuspid:
            porcelain_answer = 'Yes' if (molar_yes or bicuspid_yes) else 'No'

    return {
        'posterior_composite_downgrade': composite_answer,
        'porcelain_posterior_downgrade': porcelain_answer,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  BUG-FIXED HELPERS  (waiting period, applies_to, pre_auth)
# ═══════════════════════════════════════════════════════════════════════════════

_CARRIER_PRE_AUTH = {
    'metlife': 'Recommended-300',
    'cigna':   'Recommended-300',
    'delta':   'Recommended-300',
}


def _clean_phone(phone):
    return re.sub(r'[\s\-()]', '', str(phone or ''))


def _parse_waiting_period(provisions: list, notes: dict):
    """
    Returns (waiting_period, waiting_period_months, applies_to).
    """
    for p in (provisions or []):
        rule  = str(p.get('rule',  '')).lower()
        value = str(p.get('value', ''))
        if 'waiting period' not in rule:
            continue

        v = value.lower()

        if v.count('no waiting period') >= 2:
            return 'No', '0', '—'

        if 'no waiting period' in v:
            return 'No', '0', '—'

        applies_parts, months_found = [], '—'
        for cat in ['basic', 'major', 'preventive', 'preventative', 'orthodontic']:
            m = re.search(rf'{cat}[^.;]*?(\d+)\s*month', v, re.IGNORECASE)
            if m:
                applies_parts.append(cat.title())
                months_found = m.group(1)

        if applies_parts:
            return 'Yes', months_found, ' & '.join(applies_parts)

        if 'no waiting' in v:
            return 'No', '0', '—'

    waiting_raw = str(notes.get('waiting', '')).strip().lower()
    if waiting_raw in ('no', 'n', '0', 'false'):
        return 'No', '0', '—'
    if waiting_raw in ('yes', 'y', '1', 'true'):
        return 'Yes', '—', '—'

    return 'No', '0', ''


def _parse_pre_auth(notes: dict, notes_str: str, carrier_name: str) -> str:
    carrier_lower = str(carrier_name).lower()
    for key, val in _CARRIER_PRE_AUTH.items():
        if key in carrier_lower:
            return val

    m = re.search(
        r'PRE-D\s+MANDATORY\s*(?:\(Y/N\))?\s*:?\s*([YyNn]|yes|no|\$[\d,]+|\d+)',
        notes_str,
        re.IGNORECASE,
    )
    if m:
        v = m.group(1).strip().lower()
        if v in ('y', 'yes'): return 'Yes'
        if v in ('n', 'no'):  return 'No'
        return m.group(1).strip()

    return '—'


# ═══════════════════════════════════════════════════════════════════════════════
#  UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def _g(obj, *keys, default='—'):
    if not isinstance(obj, dict):
        return default
    for k in keys:
        v = obj.get(k)
        if v not in (None, '', [], {}):
            return str(v).strip()
        norm = k.lower().replace('_','').replace(' ','').replace('-','')
        for okey, oval in obj.items():
            ck = okey.lower().replace('_','').replace(' ','').replace('-','')
            if ck == norm and oval not in (None, '', [], {}):
                return str(oval).strip()
    return default


def _covered_pct(services, *category_hints):
    # Respect caller priority (for example RESTORATIVE before DIAGNOSTIC).
    for hint in category_hints:
        for svc in services:
            cat = svc.get('category', '').upper()
            if hint not in cat:
                continue
            m = re.search(r'(\d+%)', svc.get('in_network', ''))
            if m:
                return m.group(1)
    return '—'


def _build_insurance_address(carrier):
    if not isinstance(carrier, dict):
        return '—'
    addr1    = carrier.get('address') or ''
    city     = carrier.get('city') or ''
    state    = carrier.get('state') or ''
    zipc     = carrier.get('zip') or carrier.get('zip_code') or ''
    combined = carrier.get('city_state_zip') or carrier.get('cityStateZip') or ''
    if combined and not city:
        city_state_zip = combined.strip()
    else:
        city_state_zip = ", ".join(x for x in [city, state] if x)
        if zipc:
            city_state_zip += f" {zipc}"
    final = ", ".join(x for x in [addr1, city_state_zip] if x.strip())
    return final or '—'


def _get_plan_year_start(procs, eff_date, provisions=None):
    """
    Month the plan/benefit year starts.

    The portal states this outright in its "Benefit Period" provision —
    "CALENDAR YEAR Start Date: 01/01/2026 End Date: 12/31/2026" — so that is
    read first, and it is the only authoritative source.

    The patient's effective date is a poor proxy and is now a last resort: for a
    calendar-year plan whose member joined mid-year it reported the join month
    (an effective date in September became "September" for a plan the portal
    plainly labels CALENDAR YEAR).
    """
    for prov in provisions or []:
        if not isinstance(prov, dict):
            continue
        if 'benefit period' not in str(prov.get('rule', '')).lower():
            continue
        value = str(prov.get('value', ''))
        m = re.search(r'start\s*date\s*:?\s*(\d{1,2})\s*/\s*\d{1,2}\s*/\s*\d{2,4}',
                      value, re.IGNORECASE)
        if m:
            month = int(m.group(1))
            if 1 <= month <= 12:
                return datetime(2000, month, 1).strftime('%B')
        if 'calendar year' in value.lower():
            return 'January'

    # Indirect hint: a D2740 frequency counted per calendar year.
    d2740 = procs.get('D2740', {})
    freq = str(d2740.get('frequency_limit', '')).upper()
    if 'CALENDAR YEAR' in freq:
        return 'January'

    try:
        return datetime.strptime(eff_date, '%m/%d/%Y').strftime('%B')
    except Exception:
        return '—'


def _yes_no_from_basis(text, target):
    t = re.sub(r'\s+', ' ', str(text).lower()).strip()
    if 'completion date' in t:
        return 'Yes' if target == 'seat' else 'No'
    if 'prep date' in t:
        return 'Yes' if target == 'prep' else 'No'
    return '—'


def _missing_tooth_clause(text):
    t = re.sub(r'\s+', ' ', str(text).lower()).strip()
    # The provision answers TWO questions — the general case and a separate
    # congenital-teeth case:
    #   "…benefits available for teeth lost prior to effective date: Yes
    #    …benefits available for congenital teeth lost prior to effective date: No"
    # The clause status is the GENERAL answer, so read the text before the
    # congenital sentence. Scanning the whole string finds whichever pattern is
    # tested first and reports a plan that DOES cover teeth lost before the
    # effective date (clause does not apply) as though the clause applied.
    general = t.split('congenital')[0] if 'congenital' in t else t
    for scope in (general, t):
        if 'lost prior to effective date: no' in scope:  return 'Yes'
        if 'lost prior to effective date: yes' in scope: return 'No'
    return '—'


def _extract_basis_of_payment(provisions):
    for p in provisions:
        if 'basis of payment' in str(p.get('rule', '')).lower():
            return p.get('value', '')
    return ''


def _extract_missing_tooth_text(provisions):
    for p in provisions:
        if 'missing tooth' in str(p.get('rule', '')).lower():
            return p.get('value', '')
    return ''


def _extract_dependent_age_limit(provisions):
    """Read the non-orthodontic dependent age limit from Portal provisions."""
    for p in provisions or []:
        rule = str(p.get('rule', '')).lower()
        if 'maximum child age' not in rule and 'maximum age' not in rule:
            continue
        if 'orthodont' in rule:
            continue
        m = re.search(r'(?:child\s*:?\s*)?(\d+)', str(p.get('value', '')), re.IGNORECASE)
        if m:
            return m.group(1)
    return 'NAL'


def _procedure_benefit_pct(procs, *codes):
    """Return the first usable numeric benefit percentage from representative codes."""
    for code in codes:
        proc = (procs or {}).get(code) or {}
        value = str(proc.get('benefit_level') or '').strip()
        if value.upper() in ('', '-', '—', 'N/A', 'NA', 'NC', 'NOT COVERED'):
            continue
        m = re.search(r'(\d+(?:\.\d+)?)\s*%', value)
        if m:
            try:
                return f"{float(m.group(1)):g}%"
            except ValueError:
                return f"{m.group(1)}%"
    return ''


def _covered_pct_max(services, *category_hints):
    """Return the highest plan-paid percentage in the first matching category."""
    for hint in category_hints:
        for svc in services or []:
            if hint not in str(svc.get('category', '')).upper():
                continue
            values = [float(v) for v in re.findall(r'(\d+(?:\.\d+)?)\s*%', str(svc.get('in_network', '')))]
            if values:
                return f"{max(values):g}%"
    return ''


def _deductible_applies(services, *category_hints):
    """Return Yes/No from Portal covered_services.in_network text."""
    for svc in services or []:
        cat = str(svc.get('category', '')).upper()
        if not any(h in cat for h in category_hints):
            continue
        text = str(svc.get('in_network', ''))
        m = re.search(r'Deductible\s+Applies\s*:\s*(Yes|No)', text, re.IGNORECASE)
        if m:
            return m.group(1).title()
        if re.search(r'Deductible\s+Not\s+Applies', text, re.IGNORECASE):
            return 'No'
    return '—'


def _number_of_quads_d4341(procs):
    """Read D4341 quadrant count from Portal procedure data only."""
    p = procs.get('D4341', {})
    if not p:
        return '—'

    for key in (
        'number_of_quads', 'number_of_quadrants', 'quadrants',
        'quad_limit', 'quadrant_limit', 'quads_allowed',
    ):
        value = p.get(key)
        if value not in (None, '', '—'):
            m = re.search(r'\d+', str(value))
            return m.group(0) if m else str(value).strip()

    searchable = ' '.join(str(p.get(k, '')) for k in (
        'frequency_limit', 'description', 'limitations', 'notes',
    ))
    for pattern in (
        r'(\d+)\s*(?:QUADS?|QUADRANTS?)\s+ALLOWED',
        r'(?:LIMIT(?:ED)?\s+TO\s+)?(\d+)\s*(?:QUADS?|QUADRANTS?)',
        r'(?:QUADS?|QUADRANTS?)\s*[:=-]?\s*(\d+)',
    ):
        m = re.search(pattern, searchable, re.IGNORECASE)
        if m:
            return m.group(1)
    return '—'


# ═══════════════════════════════════════════════════════════════════════════════
#  FIX #1 — Family Deductible logic
# ═══════════════════════════════════════════════════════════════════════════════

def _family_deductible_v2(fam_total_raw: str, indiv_total_raw: str, relationship: str) -> str:
    """
    Show exactly what the portal shows:
      1. If the plan provides a family deductible total → use it as-is (always).
      2. If blank/missing → derive as 3 × individual deductible.
    """
    # Case 1: plan has a value — just reflect it
    fam_dollar = _dollar(fam_total_raw, default='')
    if fam_dollar and fam_dollar != '—':
        return fam_dollar

    # Case 2: no family value in plan — business fallback is 3 × individual.
    m = re.search(r'([\d,.]+)', str(indiv_total_raw))
    if not m:
        return _dollar(indiv_total_raw, default='—')

    indiv_val = float(m.group(1).replace(',', ''))
    return f"{indiv_val * 3:,.2f}"


def _zero_money(val):
    if val in ['—', '', None, 'N/A']:
        return '0.00'
    return val


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

RELATION_MAP = {
    'child':      'Dependent',
    'dependent':  'Dependent',
    'self':       'Self',
    'subscriber': 'Self',
    'spouse':     'Spouse',
    'employee':   'Self',
    'other':      'Other',
}


def _extract(portal_raw, denticon_raw):
    """Return a flat dict of all values needed to render the PDF."""

    if _is_aetna_portal(portal_raw):
        normalized = _normalize_aetna_portal(portal_raw)
        return _apply_aetna_output_rules(
            _extract(normalized, denticon_raw),
            normalized,
        )

    if _is_cigna_portal(portal_raw):
        normalized = _normalize_cigna_portal(portal_raw)
        return _apply_cigna_output_rules(
            _extract(normalized, denticon_raw),
            normalized,
        )

    if _is_dd_portal(portal_raw):
        normalized = _normalize_dd_portal(portal_raw)
        return _apply_dd_output_rules(
            _extract(normalized, denticon_raw),
            normalized,
        )

    carrier = (
        portal_raw.get('carrier_information') or
        portal_raw.get('carrier_info') or {}
    )

    # All non-office PDF data comes exclusively from Portal JSON.
    ml = portal_raw.get('metlife_data') or portal_raw
    bc = portal_raw.get('benefit_coverage') or {}

    dent       = denticon_raw.get('denticon_data') or denticon_raw
    dent_hdr   = dent.get('header', {})
    dent_pt    = dent.get('patient', {})
    dent_pi    = dent.get('primary_insurance', {}) if isinstance(dent.get('primary_insurance', {}), dict) else {}

    ml_pat      = ml.get('patient', {})       if isinstance(ml.get('patient', {}),       dict) else {}
    ml_pln      = ml.get('plan_details', {})  if isinstance(ml.get('plan_details', {}),  dict) else {}
    ml_fin      = ml.get('financials', {})    if isinstance(ml.get('financials', {}),    dict) else {}
    ml_provider = ml.get('provider_info', {}) if isinstance(ml.get('provider_info', {}), dict) else {}

    svcs       = ml.get('covered_services', [])
    provisions = ml.get('provisions', [])

    basis_payment_text = clean(_extract_basis_of_payment(provisions))
    missing_tooth_text = clean(_extract_missing_tooth_text(provisions))

    if not isinstance(svcs, list):
        svcs = []

    interp = (
        dict(_LLM_DEFAULT_ANSWERS)
        if portal_raw.get('_skip_llm')
        else _interpret_provisions(portal_raw)
    )

    waiting_period, waiting_period_mo, applies_to = _parse_waiting_period(provisions, {})

    # ── Derived values ──────────────────────────────────────────────────────

    carrier_name = (
        _g(carrier,      'name',            default='') or
        _g(ml_provider,  'provider_name',   default='') or
        ('MetLife' if portal_raw.get('metlife_data') else '') or
        '—'
    )

    is_metlife = 'METLIFE' in carrier_name.upper()

    pre_auth_val = _parse_pre_auth({}, '', carrier_name)

    # Build procedure-code → details map
    procs = {}
    for p in bc.get('procedures', []):
        code = p.get('procedure_code', '').upper().strip()
        if code:
            procs[code] = p

    # Apply deterministic provision parsing before any LLM fallback. This keeps
    # explicit portal facts (for example MetLife ortho payment method and
    # cleaning/perio-maintenance shared frequency) correct even when Ollama is
    # unavailable.
    rule_interp = _rule_based_interp(portal_raw, procs)
    for key, value in rule_interp.items():
        if str(value or '').strip().lower() not in ('', '-', '—', 'n/a', 'na', 'none'):
            interp[key] = value

    def _format_name(raw):
        if not raw or raw == '—':
            return '—'
        suffixes = ['DMD', 'DDS', 'MD', 'DO', 'PHD', 'RDH']
        parts = raw.strip().split()
        parts = [p for p in parts if p.upper().rstrip('.') not in suffixes]
        cleaned = ' '.join(parts).strip()
        if ',' in cleaned:
            last, *rest = cleaned.split(',')
            first_parts = ' '.join(rest).strip().split()
            first = first_parts[0].capitalize() if first_parts else ''
            last  = last.strip().capitalize()
            return f'{first} {last}'.strip()
        return ' '.join(p.capitalize() for p in cleaned.split())

    def _same_frequency(code1, code2):
        p1 = procs.get(code1, {})
        p2 = procs.get(code2, {})
        f1 = str(p1.get('frequency_limit', '')).strip().upper()
        f2 = str(p2.get('frequency_limit', '')).strip().upper()
        if not f1 or not f2:
            return 'No'
        return 'Yes' if f1 == f2 else 'No'

    d4910_d1110_same_freq        = _same_frequency('D4910', 'D1110')
    d0120_d0140_same             = _same_frequency('D0120', 'D0140')
    d0150_d0140_same             = _same_frequency('D0150', 'D0140')
    d0120_d0150_share_with_d0140 = (
        'Yes' if (d0120_d0140_same == 'Yes' and d0150_d0140_same == 'Yes') else 'No'
    )

    # For MetLife, explicit plan provisions take precedence over coincidentally
    # equal/unequal display strings when they state that counters are combined.
    if is_metlife:
        explicit_4910 = str(rule_interp.get('d4910_d1110_share_freq') or '').strip()
        if explicit_4910 in ('Yes', 'No'):
            d4910_d1110_same_freq = explicit_4910
        explicit_exam = str(rule_interp.get('d0120_d0150_share_d0140') or '').strip()
        if explicit_exam in ('Yes', 'No'):
            d0120_d0150_share_with_d0140 = explicit_exam

    ann  = ml_fin.get('annual_max',     {})
    dind = ml_fin.get('deductible_ind', {})
    dfam = ml_fin.get('deductible_fam', {})
    orth = ml_fin.get('ortho_lifetime', {})

    if is_metlife:
        # Business rule: MetLife Member ID / SSN are the Denticon subscriber ID.
        # Do not use the masked Portal subscriber_id when Denticon has the real value.
        member_id = (
            _g(
                dent_pi,
                'sub_id', 'subscriber_id', 'subscriberId', 'member_id', 'memberId', 'ssn',
                default='',
            )
            or _g(ml_pln, 'subscriber_id', default='')
            or '—'
        )
    else:
        member_id = (
            _g(ml_pln, 'subscriber_id', default='') or
            '—'
        )

    sub_info = portal_raw.get('subscriber_info') or {}

    subscriber_name = _format_name(
        sub_info.get('name', '') or _g(ml_pat, 'name', default='')
    )

    subscriber_dob = (
        sub_info.get('dob', '') or
        _g(ml_pat, 'dob', default='') or
        '—'
    )       

    raw_rel = (
        _g(ml_pat,   'relationship',           default='') or
        _g(sub_info, 'relation', 'relationship', default='')
    )
    relationship = RELATION_MAP.get(raw_rel.strip().lower(), raw_rel or '—')

    office_name = (
        _g(dent_pt,  'home_office',  default='') or
        _g(dent_hdr, 'office_name',  default='') or
        '—'
    )

    provider_name = _format_name(
        _g(dent_pt,  'provider',      default='') or
        _g(dent_hdr, 'provider_name', default='')
    )

    # Do not assume that the hygienist is the chair provider.
    chair_provider = _format_name(
        _g(dent_pt, 'chair_provider', default='—')
    )
    provider_speciality = (
        _g(dent_hdr, 'provider_speciality', 'speciality', 'specialty', default='') or
        'Dentist'
    )
    appointment_date = datetime.now(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime('%m/%d/%Y %I:%M %p')

    # Portal-only group number lookup. Support the common schema variants at
    # both plan and MetLife payload levels without falling back to Denticon.
    group_number = (
        _g(
            ml_pln,
            'group_number', 'group_num', 'group_id', 'group_no',
            'employer_group_number', 'contract_number',
            default='',
        ) or
        _g(
            ml,
            'group_number', 'group_num', 'group_id', 'group_no',
            'employer_group_number', 'contract_number',
            default='',
        ) or
        _g(
            portal_raw,
            'group_number', 'group_num', 'group_id', 'group_no',
            'employer_group_number', 'contract_number',
            default='',
        ) or
        '—'
    )

    carrier_phone = _g(carrier, 'phone', default='')

    # ── FIX #2: Molars-only sealants — deterministic from D1351 frequency ──
    molars_only = _rule_molars_only_sealants(procs)
    if molars_only == '—':
        molars_only = interp.get('molars_only_sealants', '—')

    # ── FIX #3: D2950 same day as crown — check D2740 coverage ────────────
    d2950_same_day = _rule_d2950_same_day_crown(procs)
    if d2950_same_day == '—':
        d2950_same_day = interp.get('d2950_same_day_crown', '—')

    # ── FIX #4: Alternate-benefit downgrades — parse provision sentences ───
    downgrade_answers = _rule_alternate_benefit_downgrades(provisions)
    posterior_composite = downgrade_answers['posterior_composite_downgrade']
    porcelain_posterior = downgrade_answers['porcelain_posterior_downgrade']
    # Fall back to LLM only if rule-based couldn't determine
    if posterior_composite == '—':
        posterior_composite = interp.get('posterior_composite_downgrade', '—')
    if porcelain_posterior == '—':
        porcelain_posterior = interp.get('porcelain_posterior_downgrade', '—')

    # ── FIX #1: Family deductible ──────────────────────────────────────────
    family_ded_val = _family_deductible_v2(
        fam_total_raw   = _g(dfam, 'total', default=''),
        indiv_total_raw = _g(dind, 'total', default=''),
        relationship    = relationship,
    )

    # MetLife top category percentages should represent the actual category
    # benefit, not the first number in mixed text such as "50%-80%".
    if is_metlife:
        pct_prev = (
            _procedure_benefit_pct(procs, 'D1110', 'D1120', 'D1206', 'D1351')
            or _covered_pct_max(svcs, 'PREVENTIVE')
            or _covered_pct(svcs, 'PREVENTIVE')
        )
        pct_basic = (
            _procedure_benefit_pct(procs, 'D2140', 'D2331', 'D4341', 'D3310')
            or _covered_pct_max(svcs, 'RESTORATIVE')
            or _covered_pct(svcs, 'RESTORATIVE', 'DIAGNOSTIC')
        )
        pct_major = (
            _procedure_benefit_pct(procs, 'D2740', 'D5110', 'D6010')
            or _covered_pct_max(svcs, 'PROSTHODONTICS', 'IMPLANT')
            or _covered_pct(svcs, 'PROSTHODONTICS', 'IMPLANT')
        )
        metlife_ortho_age = _extract_metlife_ortho_age_limit(provisions)
    else:
        pct_prev = _covered_pct(svcs, 'PREVENTIVE')
        pct_basic = _covered_pct(svcs, 'RESTORATIVE', 'DIAGNOSTIC')
        pct_major = _covered_pct(svcs, 'PROSTHODONTICS', 'IMPLANT')
        metlife_ortho_age = ''

    return {
        'source_insurer': 'metlife' if is_metlife else '',

        # Patient / Subscriber
        'patient_name':    _g(ml_pat, 'name'),
        'patient_dob':     _g(ml_pat, 'dob'),
        'relationship':    relationship,
        'member_id':       member_id,
        'subscriber_name': subscriber_name,
        'subscriber_dob':  subscriber_dob,
        'ssn':             member_id,

        # Office
        'office_name':         office_name,
        'provider_name':       provider_name,
        'chair_provider':      chair_provider,
        'provider_speciality': provider_speciality,
        'appointment_date':    appointment_date,

        # Insurance
        'ins_name': (
            '(IN) MetLife(TX)- PO Box 981282- 79998'
            if is_metlife else (carrier_name if carrier_name else '—')
        ),
        'group_name': (
            _g(ml_pln, 'employer_group')
        ),
        'group_number': group_number,
        'fee_schedule': (
            'METLIFE PPO'
            if is_metlife
            else _g(ml_provider, 'provider_network_status')
        ),
        'ins_address': (
            'PO Box 981282, El Paso, TX 79998'
            if is_metlife
            else (_build_insurance_address(carrier) or '—')
        ),
        'ins_phone': (
            _clean_phone(carrier_phone)
            if carrier_phone
            else ('8776383379' if is_metlife else '—')
        ),
        'network_status': (
            ''
        ),
        'eff_date':  _g(ml_pln, 'start_date'),
        'term_date': _blank_present_end_date(_g(ml_pln, 'end_date')),
        'payor_id': (
            _g(carrier, 'payer_id', default='') or
            ('65978' if is_metlife else '—')
        ),
        'plan_type': (
            'PPO'
            if is_metlife
            else _display_plan_type(
                _g(ml_pln, 'plan_type', default='')
                or _g(ml_pln, 'network', default='')
            )
        ),
        'plan_year_start': _get_plan_year_start(procs, _g(ml_pln, 'start_date'), provisions),
        'elig_notes': (
            'ins: metlife, benefits verified online'
            if (is_metlife or 'PDP' in str(_g(ml_pln, 'network')).upper())
            else '—'
        ),

        # Coverage
        'yearly_max':      _dollar(_g(ann,  'total')),
        'yearly_rem':      _dollar(_g(ann,  'remaining')),
        'indiv_ded':       _dollar(_g(dind, 'total')),
        'indiv_ded_paid':  _zero_money(_dollar(_g(dind, 'used'))),
        'family_ded':      family_ded_val,          # ← FIX #1
        'family_ded_paid': _zero_money(_dollar(_g(dfam, 'used'))),
        'ded_prev':        _deductible_applies(svcs, 'PREVENTIVE'),
        'ded_diag':        _deductible_applies(svcs, 'DIAGNOSTIC'),

        'waiting_period':    waiting_period,
        'waiting_period_mo': waiting_period_mo,
        'applies_to':        applies_to,

        'major_on_prep': _yes_no_from_basis(basis_payment_text, 'prep'),
        'or_seat':       _yes_no_from_basis(basis_payment_text, 'seat'),
        'missing_tooth': _missing_tooth_clause(missing_tooth_text),
        'pre_auth':      pre_auth_val,

        'dep_age_limit': _extract_dependent_age_limit(provisions),
        'ortho_ded':      '0.00',
        'ortho_ded_paid': '0.00',
        'ortho_max':      _dollar(_g(orth, 'total')),
        'ortho_max_paid': _dollar(_g(orth, 'used')),

        # Benefit percentages
        'pct_prev':  pct_prev,
        'pct_basic': pct_basic,
        'pct_major': pct_major,

        # Deterministic / LLM-interpreted fields
        'molars_only_sealants':          molars_only,          # FIX #2
        'posterior_composite_downgrade': posterior_composite,  # FIX #4
        'porcelain_posterior_downgrade': porcelain_posterior,  # FIX #4
        'd2950_same_day_crown':          d2950_same_day,       # FIX #3
        'd0120_d0150_share_d0140':       d0120_d0150_share_with_d0140,
        'd4910_d1110_share_freq':        d4910_d1110_same_freq,
        # Do not infer a quadrant count from procedure text.  The approved
        # operational answer for MetLife is Pre-D.
        'd4341_number_of_quads':          'Pre-D' if is_metlife else _number_of_quads_d4341(procs),
        'ortho_payment_frequency':       interp.get('ortho_payment_frequency', '—'),
        'ortho_age_limit_llm':           (
            metlife_ortho_age if is_metlife else interp.get('ortho_age_limit', '—')
        ),

        'procs': procs,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SHARED OUTPUT DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════

_FINANCIAL_OUTPUT_KEYS = (
    'yearly_max', 'yearly_rem',
    'indiv_ded', 'indiv_ded_paid',
    'family_ded', 'family_ded_paid',
    'ortho_ded', 'ortho_ded_paid',
    'ortho_max', 'ortho_max_paid',
)


def _finalize_shared_output(data):
    """Apply carrier-independent display rules immediately before rendering."""
    data = data or {}

    for key in _FINANCIAL_OUTPUT_KEYS:
        value = str(data.get(key) or '').strip()
        if value.lower() in ('', '-', '—', 'n/a', 'na', 'none'):
            data[key] = '0.00'
            continue
        match = re.search(r'\$?\s*([\d,]+(?:\.\d+)?)', value)
        if match:
            try:
                data[key] = f"{float(match.group(1).replace(',', '')):,.2f}"
            except ValueError:
                data[key] = value.replace('$', '')
        else:
            data[key] = value.replace('$', '')

    phone = str(data.get('ins_phone') or '').strip()
    if phone not in ('', '-', '—'):
        digits = re.sub(r'\D', '', phone)
        data['ins_phone'] = digits or phone

    relationship = str(data.get('relationship') or '').strip()
    if relationship.lower() in ('self', 'subscriber', 'employee'):
        data['relationship'] = 'Self'

    # All carriers: an active/unknown term date is intentionally blank.
    data['term_date'] = _blank_present_end_date(data.get('term_date'))

    if str(data.get('waiting_period') or '').strip().lower() in (
        '', '-', '—', 'n/a', 'na', 'none'
    ):
        data['waiting_period'] = 'No'
        data['waiting_period_mo'] = '0'
        data['applies_to'] = ''
    elif str(data.get('waiting_period')).strip().lower() == 'no':
        data['waiting_period'] = 'No'
        if str(data.get('waiting_period_mo') or '').strip().lower() in (
            '', '-', '—', 'n/a', 'na', 'none'
        ):
            data['waiting_period_mo'] = '0'

    dep_age_raw = str(data.get('dep_age_limit') or '').strip()
    dep_age_normalized = dep_age_raw.lower()
    dep_age_number = re.search(r'\b(\d+)\b', dep_age_raw)
    if (
        dep_age_normalized in (
            '', '-', '—', 'n/a', 'na', 'none', 'null',
            'not available', 'not applicable'
        )
        or (dep_age_number and dep_age_number.group(1) in ('99', '999'))
    ):
        # Shared business rule for every carrier: no real dependent-age
        # limit (including sentinel 99/999) is displayed as NAL.
        data['dep_age_limit'] = 'NAL'

    if str(data.get('molars_only_sealants') or '').strip().lower() in (
        '-', '—', 'n/a', 'na', 'none'
    ):
        data['molars_only_sealants'] = ''

    ortho_age_raw = str(data.get('ortho_age_limit_llm') or '').strip()
    ortho_age_text = ortho_age_raw.lower()
    if data.get('source_insurer') == 'metlife':
        # MetLife output must contain only the numeric age (e.g. 26), with
        # descriptive text such as "End Of Month" removed.
        ages = [int(x) for x in re.findall(r'\b(\d{1,3})\b', ortho_age_raw)]
        data['ortho_age_limit_llm'] = str(max(ages)) if ages else ''
    elif ortho_age_text in ('-', '—', 'n/a', 'na', 'none'):
        data['ortho_age_limit_llm'] = ''
    elif data.get('source_insurer') != 'cigna' and ortho_age_text in ('99', '999'):
        data['ortho_age_limit_llm'] = ''

    data['appointment_date'] = datetime.now(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime('%m/%d/%Y %I:%M %p')

    pre_auth = str(data.get('pre_auth') or '').replace('$', '')
    data['pre_auth'] = pre_auth or '-'
    return data
