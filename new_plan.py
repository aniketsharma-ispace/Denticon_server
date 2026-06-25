"""
new_plan.py
-----------
Generates an "Insurance Plan Breakdown – (New Plan)" PDF from the
Portal JSON (metlife_data / benefit_coverage) and the Denticon JSON.

Includes:
  - LLM-based provision interpretation (Ollama, Claude fallback)
  - Bug fixes: waiting period, applies_to, pre_auth

Usage:
    from new_plan import generate_new_plan_pdf
    pdf_bytes = generate_new_plan_pdf(portal_raw: dict, denticon_raw: dict)
"""

import io
import re
import json
import logging
import requests
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.utils import simpleSplit
from reportlab.platypus import Table, TableStyle

log = logging.getLogger(__name__)

# ─── Page geometry ─────────────────────────────────────────────────────────────
W, H     = letter          # 612 × 792 pt
MARGIN   = 36
CW       = W - 2 * MARGIN  # 540 pt content width
FOOTER_Y = 22

# ─── Colour palette ────────────────────────────────────────────────────────────
TEAL        = colors.HexColor('#0d6e8a')
TEAL_DARK   = colors.HexColor('#094e65')
TEAL_LIGHT  = colors.HexColor('#e6f4f9')
GOLD        = colors.HexColor('#c8a800')
GOLD_BG     = colors.HexColor('#fffce6')
GOLD_TXT    = colors.HexColor('#7a6000')
WHITE       = colors.white
GREY        = colors.HexColor('#6b7280')
GREY_LIGHT  = colors.HexColor('#f4f9fb')
DARK        = colors.HexColor('#1a2030')
BORDER      = colors.HexColor('#9ab8c8')
AMBER       = colors.HexColor('#92400e')


# ═══════════════════════════════════════════════════════════════════════════════
#  LLM PROVISION INTERPRETER  (formerly interpret_provisions.py)
# ═══════════════════════════════════════════════════════════════════════════════

OLLAMA_URL          = "http://localhost:11434/api/generate"
OLLAMA_MODEL        = "llama3.2"
OLLAMA_TIMEOUT      = 60
USE_CLAUDE_FALLBACK = False
CLAUDE_MODEL        = "claude-sonnet-4-20250514"

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
        log.warning("[LLM] Ollama not reachable")
        return None
    except Exception as e:
        log.warning(f"[LLM] Ollama error: {e}")
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
        log.warning("[LLM] All LLM calls failed — using defaults")
        return dict(_LLM_DEFAULT_ANSWERS)

    answers = _llm_normalize(raw)
    log.info("[LLM] answers: %s", json.dumps(answers, indent=2))
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
    """
    Return 'Yes' only when D1351 frequency explicitly says 'PERMANENT MOLARS ONLY'.
    Return 'No' if the code exists but says something else (e.g. premolars, primary).
    Return '—' if D1351 is not in the plan at all.
    """
    p = procs_map.get('D1351')
    if not p:
        return '—'

    freq_upper = str(p.get('frequency_limit', '')).upper().strip()
    if not freq_upper:
        return '—'

    # Must contain "PERMANENT" AND "MOLAR" and must NOT mention premolar/bicuspid
    has_permanent = 'PERMANENT' in freq_upper
    has_molar     = 'MOLAR' in freq_upper
    has_premolar  = 'PREMOLAR' in freq_upper or 'BICUSPID' in freq_upper or 'PRIMARY' in freq_upper

    if has_permanent and has_molar and not has_premolar:
        return 'Yes'
    else:
        return 'No'


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
    'metlife': 'Recommended-$300',
    'cigna':   'Recommended-$300',
    'delta':   'Recommended-$300',
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

    return '—', '—', '—'


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


def _dollar(raw, default='—'):
    if not raw or raw == '—':
        return default
    m = re.search(r'\$?\s*([\d,]+\.?\d*)', str(raw))
    if m:
        try:
            return f"${float(m.group(1).replace(',', '')):,.2f}"
        except ValueError:
            pass
    return default


def _parse_notes(s):
    result = {}
    if not s:
        return result
    patterns = {
        'group_number':  r'GROUP\s*#\s*:?\s*(\S+)',
        'dep_age_limit': r'DEPENDENT\s+AGE\s+LIMIT\s*:?\s*(\d+)',
        'ded_prev':      r'APPLY\s+TO\s+PREVENTATIVE\s*(?:\(Y/N\))?\s*:?\s*(\w+)',
        'waiting':       r'WAITING\s+PERIOD\s*(?:\(Y/N\))?\s*:?\s*(\w+)',
        'plan_type':     r'PPO/HMO/INDEMNITY\s*:?\s*(\w+)',
        'fee_schedule':  r'WHAT\s+FEE\s+SCHEDULE\s*:?\s*([A-Z0-9/() ]+)',
        'cal_year':      r'CALENDAR\s+YEAR\s*:?\s*(\d{4})',
        'employer':      r'EMPLOYER\s*:?\s*([A-Z ]+?)(?:\s{2,}|\n|GROUP)',
        'prev_pct':      r'PREVENTATIVE\s*%\s*:?\s*(\d+%)',
        'basic_pct':     r'BASIC\s*%\s*:?\s*(\d+%)',
        'major_pct':     r'MAJOR\s*%\s*:?\s*(\d+%)',
        'missing_tooth': r'MISSING\s+TOOTH\s+CLAUSE?\s*(?:\(Y/N\))?\s*:?\s*(\w+)',
        'pre_auth':      r'PRE-D\s+MANDATORY\s*(?:\(Y/N\))?\s*:?\s*(\w+)',
    }
    for k, pat in patterns.items():
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            result[k] = m.group(1).strip()
    return result


def _covered_pct(services, *category_hints):
    for svc in services:
        cat = svc.get('category', '').upper()
        if any(h in cat for h in category_hints):
            m = re.search(r'(\d+%)', svc.get('in_network', ''))
            if m:
                return m.group(1)
    return '—'


def _format_frequency(freq):
    if not freq or freq == '—':
        return '—'
    f = str(freq).upper().strip()
    if 'NO LIMIT' in f:      return 'No Frequency'
    if 'NO FREQUENCY' in f:  return 'No Frequency'
    if 'NOT COVERED' in f:   return 'NC'
    if 'NOT AVAILABLE' in f: return 'NOT AVAILABLE'
    if f in ['PRE-D', 'PRE D']: return 'Pre-D'
    m = re.search(
        r'(\d+)\s*TIME\S*\s*IN\s*(\d+)\s*(?:CALENDAR\s+)?(MONTH|YEAR|DAY)S?',
        f,
        re.IGNORECASE
    )
    if m:
        count    = m.group(1)
        duration = m.group(2)
        unit     = m.group(3).title()
        if int(duration) != 1:
            unit += 's'
        return f'{count}X{duration} {unit}'
    if 'LIFETIME' in f: return '1XLifetime'
    if 'PROVIDER' in f: return '1XProvider'
    return freq


def _format_person_name(name):
    if not name or name == '—':
        return '—'
    name = str(name).strip()
    if ',' in name:
        last, first = [x.strip() for x in name.split(',', 1)]
        return f"{first.title()} {last.title()}"
    return name.title()


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


def _get_plan_year_start(procs, eff_date):
    d2740 = procs.get('D2740', {})
    freq = str(d2740.get('frequency_limit', '')).upper()
    if 'CALENDAR YEAR' in freq:
        return 'January'
    try:
        return datetime.strptime(eff_date, '%m/%d/%Y').strftime('%B')
    except (ValueError, TypeError):
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
    if 'lost prior to effective date: no' in t:  return 'Yes'
    if 'lost prior to effective date: yes' in t: return 'No'
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


# ═══════════════════════════════════════════════════════════════════════════════
#  FIX #1 — Family Deductible logic
# ═══════════════════════════════════════════════════════════════════════════════

def _family_deductible_v2(fam_total_raw: str, indiv_total_raw: str, relationship: str) -> str:
    """
    Show exactly what the portal shows:
      1. If the plan provides a family deductible total → use it as-is (always).
      2. If blank/missing → derive:
           - Dependent/Spouse : 3 × individual
           - Subscriber       : individual value
    """
    # Case 1: plan has a value — just reflect it
    fam_dollar = _dollar(fam_total_raw, default='')
    if fam_dollar and fam_dollar != '—':
        return fam_dollar

    # Case 2: no family value in plan — derive from individual
    rel_lower     = str(relationship).strip().lower()
    is_subscriber = rel_lower in ('subscriber', 'self', 'employee')

    m = re.search(r'([\d,.]+)', str(indiv_total_raw))
    if not m:
        return _dollar(indiv_total_raw, default='—')

    indiv_val = float(m.group(1).replace(',', ''))
    if is_subscriber:
        return f"${indiv_val:,.2f}"
    else:
        return f"${indiv_val * 3:,.2f}"


def _zero_money(val):
    if val in ['—', '', None, 'N/A']:
        return '$0.00'
    return val


def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

RELATION_MAP = {
    'child':      'Dependent',
    'dependent':  'Dependent',
    'self':       'Subscriber',
    'subscriber': 'Subscriber',
    'spouse':     'Spouse',
    'employee':   'Subscriber',
    'other':      'Other',
}


def _extract(portal_raw, denticon_raw):
    """Return a flat dict of all values needed to render the PDF."""

    carrier = (
        portal_raw.get('carrier_information') or
        portal_raw.get('carrier_info') or {}
    )

    ml = portal_raw.get('metlife_data') or {}
    if not ml:
        ml = portal_raw
    bc = portal_raw.get('benefit_coverage') or denticon_raw.get('benefit_coverage') or {}

    if not ml and 'patient' in portal_raw and 'financials' in portal_raw:
        ml = portal_raw
    if not ml:
        ml = denticon_raw.get('metlife_data', {})
    if not bc:
        bc = denticon_raw.get('benefit_coverage', {})

    dent       = denticon_raw.get('denticon_data') or denticon_raw
    dent_hdr   = dent.get('header', {})
    dent_ins   = dent_hdr.get('insurance_summary', {})
    dent_fin   = dent_hdr.get('financials', {})
    dent_plans = dent.get('plans', [])

    dent_pt = dent.get('patient', {})
    dent_pi = dent.get('primary_insurance', {})
    dent_rp = dent.get('responsible_party', {})

    notes_str = ((dent_plans[0].get('benefits') or {}).get('notes', '')
                 if dent_plans else '')
    notes = _parse_notes(notes_str)

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

    interp = _interpret_provisions(portal_raw)

    waiting_period, waiting_period_mo, applies_to = _parse_waiting_period(provisions, notes)

    # ── Derived values ──────────────────────────────────────────────────────

    carrier_name = (
        _g(carrier,      'name',            default='') or
        _g(dent_ins,     'provider',        default='') or
        _g(ml_provider,  'provider_name',   default='') or
        dent_pi.get('carrier_name', '').replace('(IN) ', '').replace('(OUT) ', '').strip() or
        '—'
    )

    is_metlife = 'METLIFE' in carrier_name.upper()

    pre_auth_val = _parse_pre_auth(notes, notes_str, carrier_name)

    # Build procedure-code → details map
    procs = {}
    for p in bc.get('procedures', []):
        code = p.get('procedure_code', '').upper().strip()
        if code:
            procs[code] = p

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

    ann  = ml_fin.get('annual_max',     {})
    dind = ml_fin.get('deductible_ind', {})
    dfam = ml_fin.get('deductible_fam', {})
    orth = ml_fin.get('ortho_lifetime', {})

    member_id = (
        _g(dent_pi,  'sub_id',        default='') or
        _g(dent_ins, 'header_sub_id', default='') or
        _g(dent_ins, 'member_id',     default='') or
        _g(dent_ins, 'subscriber_id', default='') or
        '—'
    )

    sub_info = portal_raw.get('subscriber_info') or {}

    subscriber_name = _format_name(
        sub_info.get('name', '') or
        _g(dent_pi, 'subscriber_name', default='') or
        _g(dent_fin, 'responsible', default='')
    )

    subscriber_dob = (
        sub_info.get('dob', '') or
        _g(dent_rp,  'dob',    default='') or
        _g(dent_fin, 'rp_dob', default='') or
        '—'
    )       

    raw_rel = (
        _g(ml_pat,   'relationship',           default='') or
        _g(dent_pi,  'relation_to_subscriber', default='')
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

    chair_provider      = '-'
    provider_speciality = (
        _g(dent_hdr, 'provider_speciality', 'speciality', 'specialty', default='') or
        'Dentist'
    )
    appointment_date = datetime.today().strftime('%m/%d/%Y')

    group_number = (
        _g(dent_pi, 'group_num', default='') or
        notes.get('group_number', '—')
    )

    carrier_phone = (
        _g(carrier,  'phone',         default='') or
        _g(dent_pi,  'carrier_phone', default='') or
        _g(dent_ins, 'phone',         default='') or
        ''
    )

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

    return {
        # Patient / Subscriber
        'patient_name':    _g(ml_pat, 'name') or _g(dent_pt, 'name', default='—'),
        'patient_dob':     _g(ml_pat, 'dob')  or _g(dent_pt, 'dob',  default='—'),
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
            _g(ml_pln, 'employer_group', default='') or
            notes.get('employer', '—')
        ),
        'group_number': group_number,
        'fee_schedule': (
            'Metlife PPO'
            if is_metlife
            else _g(ml_provider, 'provider_network_status')
        ),
        'ins_address': (
            'PO Box 981282, El Paso, TX 79998'
            if is_metlife
            else (_build_insurance_address(carrier) or '—')
        ),
        'ins_phone': (_clean_phone(carrier_phone) if carrier_phone else '—'),
        'network_status': (
            'IN'  if 'in-network'     in str(_g(ml_provider, 'provider_network_status')).lower() else
            'OUT' if 'out-of-network' in str(_g(ml_provider, 'provider_network_status')).lower() else
            '—'
        ),
        'eff_date':  _g(ml_pln, 'start_date'),
        'term_date': _g(ml_pln, 'end_date'),
        'payor_id': (
            _g(carrier, 'payer_id', default='') or
            ('65978' if is_metlife else '—')
        ),
        'plan_type': (
            'PPO'
            if ('PDP' in str(_g(ml_pln, 'network')).upper() or 'PPO' in carrier_name.upper())
            else notes.get('plan_type', '—')
        ),
        'plan_year_start': _get_plan_year_start(procs, _g(ml_pln, 'start_date')),
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
        'ded_prev':        notes.get('ded_prev', '—'),
        'ded_diag':        _zero_money('—'),

        'waiting_period':    waiting_period,
        'waiting_period_mo': waiting_period_mo,
        'applies_to':        applies_to,

        'major_on_prep': _yes_no_from_basis(basis_payment_text, 'prep'),
        'or_seat':       _yes_no_from_basis(basis_payment_text, 'seat'),
        'missing_tooth': _missing_tooth_clause(missing_tooth_text),
        'pre_auth':      pre_auth_val,

        'dep_age_limit': notes.get('dep_age_limit', '—'),
        'ortho_ded':      '$0.00',
        'ortho_ded_paid': '$0.00',
        'ortho_max':      _dollar(_g(orth, 'total')),
        'ortho_max_paid': _dollar(_g(orth, 'used')),

        # Benefit percentages
        'pct_prev':  _covered_pct(svcs, 'PREVENTIVE')                or notes.get('prev_pct',  '—'),
        'pct_basic': _covered_pct(svcs, 'RESTORATIVE', 'DIAGNOSTIC') or notes.get('basic_pct', '—'),
        'pct_major': _covered_pct(svcs, 'PROSTHODONTICS', 'IMPLANT') or notes.get('major_pct', '—'),

        # Deterministic / LLM-interpreted fields
        'molars_only_sealants':          molars_only,          # FIX #2
        'posterior_composite_downgrade': posterior_composite,  # FIX #4
        'porcelain_posterior_downgrade': porcelain_posterior,  # FIX #4
        'd2950_same_day_crown':          d2950_same_day,       # FIX #3
        'd0120_d0150_share_d0140':       d0120_d0150_share_with_d0140,
        'd4910_d1110_share_freq':        d4910_d1110_same_freq,
        'ortho_payment_frequency':       interp.get('ortho_payment_frequency', '—'),
        'ortho_age_limit_llm':           interp.get('ortho_age_limit',         '—'),

        'procs': procs,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  CANVAS DRAWING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _filled_rect(c, x, y, w, h, fill, stroke_color=None, lw=0.5):
    c.setFillColor(fill)
    if stroke_color:
        c.setStrokeColor(stroke_color)
        c.setLineWidth(lw)
        c.rect(x, H - y - h, w, h, fill=1, stroke=1)
    else:
        c.rect(x, H - y - h, w, h, fill=1, stroke=0)


def _stroke_rect(c, x, y, w, h, stroke_color=BORDER, lw=0.5):
    c.setStrokeColor(stroke_color)
    c.setLineWidth(lw)
    c.rect(x, H - y - h, w, h, fill=0, stroke=1)


def _txt(c, x, y, text, font='Helvetica', size=8, color=DARK):
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawString(x, H - y, text)


def _rtxt(c, x, y, text, font='Helvetica', size=8, color=DARK):
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawRightString(x, H - y, text)


def _hline(c, x1, y, x2, color=BORDER, lw=0.5):
    c.setStrokeColor(color)
    c.setLineWidth(lw)
    c.line(x1, H - y, x2, H - y)


def _sec_bar(c, x, y, w, h, label, font_size=9):
    _filled_rect(c, x, y, w, h, fill=TEAL_LIGHT, stroke_color=BORDER)
    _txt(c, x + 6, y + h - 4, label, 'Helvetica-Bold', font_size, TEAL_DARK)


def _lv(c, x, y, label, value, lsz=7, vsz=8.5, vcolor=TEAL, gap=14):
    _txt(c, x, y, label, 'Helvetica', lsz, GREY)
    _txt(c, x, y + gap, value or '—', 'Helvetica-Bold', vsz, vcolor)


def _footer(c, page_num, total_pages):
    _hline(c, MARGIN, H - FOOTER_Y + 4, W - MARGIN, color=BORDER)
    yr = datetime.now().year
    c.setFont('Helvetica', 7)
    c.setFillColor(GREY)
    c.drawString(MARGIN, FOOTER_Y, datetime.now().strftime('%m-%d-%Y'))
    c.drawCentredString(W / 2, FOOTER_Y, f'© {yr} iSpace, Inc. All Rights Reserved.')
    c.drawRightString(W - MARGIN, FOOTER_Y, f'{page_num} of {total_pages}')


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE 1
# ═══════════════════════════════════════════════════════════════════════════════

def _page1(c, d, total_pages):
    y = 0

    BAR = 34
    _filled_rect(c, 0, y, W, BAR, fill=TEAL)
    _txt(c, MARGIN,       y + 23, 'Insurance Plan Breakdown', 'Helvetica-Bold', 14, WHITE)
    _txt(c, MARGIN + 193, y + 23, '- (New Plan)', 'Helvetica', 12, colors.HexColor('#90e8a0'))
    _rtxt(c, W - MARGIN,  y + 23, 'Powered By iSpace', 'Helvetica-Oblique', 8.5, colors.HexColor('#c0e8f5'))
    y += BAR + 3

    DISC_H = 34
    _filled_rect(c, MARGIN, y, CW, DISC_H, fill=GOLD_BG, stroke_color=GOLD)
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(GOLD_TXT)
    c.drawString(MARGIN + 5, H - y - 14, 'Disclaimer:')
    disc = ('The applicability of the deductible to Diagnostic and Preventive services '
            'is recorded based on the insurance plan, while for Basic and Major services, '
            'it is set to "Yes" by default.')
    lines = simpleSplit(disc, 'Helvetica', 7.5, CW - 75)
    c.setFont('Helvetica', 7.5)
    c.setFillColor(GOLD_TXT)
    ly = H - y - 14
    for ln in lines[:2]:
        c.drawString(MARGIN + 72, ly, ln)
        ly -= 10
    y += DISC_H + 5

    HALF  = (CW - 8) / 2
    BOX_H = 140

    _filled_rect(c, MARGIN, y, HALF, BOX_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _filled_rect(c, MARGIN, y, HALF, 15,    fill=TEAL)
    _txt(c, MARGIN + 5, y + 11, 'Office Information', 'Helvetica-Bold', 8.5, WHITE)
    _lv(c, MARGIN + 5, y + 22,  'Office Name',              d['office_name'])
    _lv(c, MARGIN + 5, y + 46,  'Preferred Provider Name',  d['provider_name'])
    _lv(c, MARGIN + 5, y + 70,  'Chair Provider Name',      d['chair_provider'])
    _lv(c, MARGIN + 5, y + 94,  'Provider Speciality',      d['provider_speciality'])
    _lv(c, MARGIN + 5, y + 118, 'Appointment Date',         d['appointment_date'])

    px = MARGIN + HALF + 8
    _filled_rect(c, px, y, HALF, BOX_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _filled_rect(c, px, y, HALF, 15,    fill=TEAL)
    _txt(c, px + 5, y + 11, 'Patient / Subscriber Information', 'Helvetica-Bold', 8.5, WHITE)

    HC = HALF / 2
    _lv(c, px + 5,      y + 22, 'Patient Name',           d['patient_name'])
    _lv(c, px + HC + 3, y + 22, 'Date of Birth',          d['patient_dob'])
    _lv(c, px + 5,      y + 46, 'Member ID#',             d['member_id'])
    _lv(c, px + HC + 3, y + 46, 'Relation to Subscriber', d['relationship'])
    _lv(c, px + 5,      y + 70, 'Subscriber Name',        d['subscriber_name'])
    _lv(c, px + HC + 3, y + 70, 'Date of Birth',          d['subscriber_dob'])
    _lv(c, px + 5,      y + 94, 'SSN#',                   d['member_id'])
    y += BOX_H + 5

    INS_BOX_H = 175

    _filled_rect(c, MARGIN, y, CW, INS_BOX_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _sec_bar(c, MARGIN, y, CW, 16, 'Insurance Information')

    T3 = CW / 3

    r1 = y + 34
    _lv(c, MARGIN + 10,          r1, 'Insurance Name',   d['ins_name'],    lsz=7, vsz=9, gap=14)
    _lv(c, MARGIN + T3 + 10,     r1, 'Group Name',       d['group_name'],  lsz=7, vsz=9, gap=14)
    _lv(c, MARGIN + (T3*2) + 10, r1, 'Group Number',     d['group_number'],lsz=7, vsz=9, gap=14)
    _hline(c, MARGIN, y + 72, W - MARGIN, lw=0.35)

    r2 = y + 92
    _lv(c, MARGIN + 10,          r2, 'Fee Schedule',       d['fee_schedule'], lsz=7, vsz=9,   gap=14)
    _lv(c, MARGIN + T3 + 10,     r2, 'Insurance Address',  d['ins_address'],  lsz=7, vsz=8.5, gap=14)
    _lv(c, MARGIN + (T3*2) + 10, r2, 'Insurance Phone',    d['ins_phone'],    lsz=7, vsz=9,   gap=14)
    _hline(c, MARGIN, y + 126, W - MARGIN, lw=0.35)

    r3 = y + 146
    _lv(c, MARGIN + 10,          r3, 'Provider Network Status', d['network_status'], lsz=7, vsz=9, gap=14)
    _lv(c, MARGIN + T3 + 10,     r3, 'Patient Eff Date',        d['eff_date'],        lsz=7, vsz=9, gap=14)
    _lv(c, MARGIN + (T3*2) + 10, r3, 'Patient Term Date',       d['term_date'],       lsz=7, vsz=9, gap=14)

    y += INS_BOX_H

    ROW_H = 44
    _filled_rect(c, MARGIN, y, CW, ROW_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _hline(c, MARGIN, y + 1, W - MARGIN, color=BORDER, lw=0.3)
    _lv(c, MARGIN + 12,          y + 14, 'PPO / Indemnity / HMO Plan?', d['plan_type'],       lsz=7, vsz=9, gap=16)
    _lv(c, MARGIN + T3 + 12,     y + 14, 'Starting Month of Plan Year', d['plan_year_start'], lsz=7, vsz=9, gap=16)
    _lv(c, MARGIN + (T3*2) + 12, y + 14, 'Payor ID',                   d['payor_id'],        lsz=7, vsz=9, gap=16)

    y += ROW_H

    EN_H = 24
    _filled_rect(c, MARGIN, y, CW, EN_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _txt(c, MARGIN + 5,  y + 8, 'Eligibility Notes:', 'Helvetica',      7.5, GREY)
    _txt(c, MARGIN + 68, y + 8, d['elig_notes'],       'Helvetica-Bold', 8,   TEAL)
    y += EN_H + 5

    cov_pairs = [
        ('Yearly Maximum',                     d['yearly_max'],
         'Remaining',                          d['yearly_rem']),
        ('Individual Deductible',              d['indiv_ded'],
         'Paid to Date (Ind.)',                d['indiv_ded_paid']),
        ('Family Deductible',                  d['family_ded'],
         'Paid to Date (Fam.)',                d['family_ded_paid']),
        ('Deductible Applies to Preventative', d['ded_prev'],
         'Deductible Applies to Diagnostic',   d['ded_diag']),
        ('Is there a Waiting Period',          d['waiting_period'],
         'Period',                             d['waiting_period_mo']),
        ('Applies to',                         d['applies_to'],
         '',                                   ''),
        ('Are Major Services Paid on Prep',    d['major_on_prep'],
         'Or Seat',                            d['or_seat']),
        ('Does Missing Tooth Clause Apply?',   d['missing_tooth'],
         'Pre-Authorize over',                 d['pre_auth']),
        ('Dependent Age Limit',                d['dep_age_limit'],
         '',                                   ''),
        ('Orthodontics Deductible',            d['ortho_ded'],
         'Paid to date',                       d['ortho_ded_paid']),
        ('Ortho Max',                          d['ortho_max'],
         'Paid to date',                       d['ortho_max_paid']),
    ]

    COV_H = 15 + len(cov_pairs) * 22 + 6
    _filled_rect(c, MARGIN, y, CW, COV_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _sec_bar(c, MARGIN, y, CW, 15, 'Coverage')

    HALF_CW = CW / 2
    cv_y = y + 22
    for l1, v1, l2, v2 in cov_pairs:
        _lv(c, MARGIN + 5,           cv_y, l1, v1, vsz=8, gap=11)
        if l2:
            _lv(c, MARGIN + HALF_CW + 5, cv_y, l2, v2, vsz=8, gap=11)
        cv_y += 22

    _footer(c, 1, total_pages)


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE 2+ — General Benefit Details table
# ═══════════════════════════════════════════════════════════════════════════════

_BENEFIT_ROWS = [
    ('EXAMS',                                        None,    'cat'),
    ('Perio Consult (D0180)',                         'D0180', 'data'),
    ('Periodic Exam (D0120)',                         'D0120', 'data'),
    ('Limited Exam (D0140)',                          'D0140', 'data'),
    ('Comprehensive Exam (D0150)',                    'D0150', 'data'),
    ('Do D0120,D0150 Share a frequency with D0140?',  None,    'note'),

    ('DIAGNOSTIC',                                    None,    'cat'),
    ('Full Mouth Xray (D0210)',                       'D0210', 'data'),
    ('PA (D0220)',                                    'D0220', 'data'),
    ('PA Addtn (D0230)',                              'D0230', 'data'),
    ('Intraoral - Occlusal Image (D0240)',            'D0240', 'data'),
    ('Bitewings (D0274)',                             'D0274', 'data'),
    ('Panoramic Xray (D0330)',                        'D0330', 'data'),

    ('PREVENTATIVE',                                  None,    'cat'),
    ('Space Maintainer (D1510)',                      'D1510', 'data'),
    ('Prophylaxis (D1110)',                           'D1110', 'data'),
    ('Prophylaxis Child (D1120)',                     'D1120', 'data'),
    ('Fluoride (D1206)',                              'D1206', 'data'),
    ('Sealants (D1351)',                              'D1351', 'data'),
    ('Permanent Un-restored Molars only?',             None,    'note'),

    ('BASIC RESTORATIVE',                             None,    'cat'),
    ('Amalgam (D2140)',                               'D2140', 'data'),
    ('Composite Filling (D2331)',                     'D2331', 'data'),
    ('Restorative Onlay/Inlay (D2620)',               'D2620', 'data'),
    ('Posterior composites downgraded to amalgam?',    None,    'note'),

    ('MAJOR RESTORATIVE',                             None,    'cat'),
    ('Porcelain Crown (D2740)',                       'D2740', 'data'),
    ('Porcelain crowns downgraded on posterior teeth', None,    'note'),
    ('Build up (D2950)',                              'D2950', 'data'),
    ('Can D2950 be done same day as crown?',           None,    'note'),
    ('D2991',                                         'D2991', 'data'),

    ('ENDODONTICS',                                   None,    'cat'),
    ('Retreatment of previous root canal therapy - premolar (D3347)', 'D3347', 'data'),
    ('Endo (D3310)',                                  'D3310', 'data'),
    ('Root Canal (D3330)',                            'D3330', 'data'),

    ('PERIODONTICS',                                  None,    'cat'),
    ('Osseous Surgery (D4260)',                       'D4260', 'data'),
    ('Scaling & Root Planning (D4341)',               'D4341', 'data'),
    ('Full Mouth Debridement (D4355)',                'D4355', 'data'),
    ('Arestin (D4381)',                               'D4381', 'data'),
    ('Perio Maintenance (D4910)',                     'D4910', 'data'),
    ('Do D4910 and D1110 share a frequency?',         None,    'note'),

    ('REMOVABLE PROSTHO',                             None,    'cat'),
    ('Over Denture Complete (D5860)',                 'D5860', 'data'),
    ('Dentures (D5110)',                              'D5110', 'data'),
    ('Reline maxillary partial denture (direct) (D5740)', 'D5740', 'data'),
    ('Surgical stent (D5982)',                        'D5982', 'data'),

    ('IMPLANT',                                       None,    'cat'),
    ('Implant (D6194)',                               'D6194', 'data'),
    ('Implant Body (D6010)',                          'D6010', 'data'),
    ('Implant Abutment (D6056)',                      'D6056', 'data'),
    ('Implant Crown (D6065) Y/N',                     'D6065', 'data'),

    ('FIXED PROSTHO',                                 None,    'cat'),
    ('Pontic - porcelain/ceramic (D6245)',            'D6245', 'data'),

    ('ORAL SURGERY',                                  None,    'cat'),
    ('Nerve dissection (D7259)',                      'D7259', 'data'),
    ('Simple Extraction (D7140)',                     'D7140', 'data'),
    ('Impacted Extraction (D7240)',                   'D7240', 'data'),

    ('ORTHODONTICS',                                  None,    'cat'),
    ('Ortho (D8010)',                                 'D8010', 'data'),
    ('Ortho (D8080)',                                 'D8080', 'data'),
    ('Payment Frequency',                             None,    'note'),
    ('Ortho Age Limit',                               None,    'note'),
    ('Ortho (D8090)',                                 'D8090', 'data'),

    ('ADJUNCTIVE',                                    None,    'cat'),
    ('Office visit for observation (D9430)',          'D9430', 'data'),
    ('Palliative (D9110)',                            'D9110', 'data'),
    ('Gen Anesthesia (D9222)',                        'D9222', 'data'),
    ('sedation/analgesia (D9239)',                    'D9239', 'data'),
    ('Consult (D9310)',                               'D9310', 'data'),
    ('Occlusal Guard (D9944)',                        'D9944', 'data'),
]

_NOTE_DATA_MAP = {
    'Do D0120,D0150 Share a frequency with D0140?': 'd0120_d0150_share_d0140',
    'Permanent Un-restored Molars only?':           'molars_only_sealants',
    'Posterior composites downgraded to amalgam?':  'posterior_composite_downgrade',
    'Can D2950 be done same day as crown?':          'd2950_same_day_crown',
    'Porcelain crowns downgraded on posterior teeth':'porcelain_posterior_downgrade',
    'Do D4910 and D1110 share a frequency?':        'd4910_d1110_share_freq',
    'Payment Frequency':                            'ortho_payment_frequency',
    'Ortho Age Limit':                              'ortho_age_limit_llm',
}


def _build_benefit_table(d):
    procs  = d['procs']
    col_w  = [195, 100, 62, 53, 58, 72]

    header_row = [
        'General Benefit Details',
        'Frequency', 'Percentage', 'Deductible', 'Age Limit\nUnder', 'History',
    ]
    rows   = [header_row]
    xstyle = []
    HISTORY_CODES = {
        'D0120', 'D0140', 'D0274', 'D0150',
        'D0330', 'D0210', 'D1110', 'D1206',
        'D1351', 'D4355', 'D4910'
    }
    for label, pct in [('Preventative', d['pct_prev']),
                        ('Basic',        d['pct_basic']),
                        ('Major',        d['pct_major'])]:
        ri = len(rows)
        rows.append([label, '', pct, '', '', ''])
        xstyle += [
            ('BACKGROUND', (0, ri), (-1, ri), colors.HexColor('#f0f8fd')),
            ('FONTNAME',   (0, ri), (0,  ri), 'Helvetica-Bold'),
            ('TEXTCOLOR',  (2, ri), (2,  ri), TEAL_DARK),
        ]

    alt = True
    for label, code, rtype in _BENEFIT_ROWS:
        ri = len(rows)
        if rtype == 'cat':
            rows.append([label, '', '', '', '', ''])
            xstyle += [
                ('BACKGROUND', (0, ri), (-1, ri), colors.HexColor('#c8e8f4')),
                ('FONTNAME',   (0, ri), (-1, ri), 'Helvetica-Bold'),
                ('TEXTCOLOR',  (0, ri), (-1, ri), TEAL_DARK),
                ('FONTSIZE',   (0, ri), (-1, ri), 7.5),
                ('SPAN',       (0, ri), (-1, ri)),
            ]

        elif rtype == 'note':
            data_key = _NOTE_DATA_MAP.get(label, '')
            note_val = d.get(data_key, '—') if data_key else '—'

            rows.append([label, note_val, '', '', '', ''])
            xstyle += [
                ('BACKGROUND', (0, ri), (-1, ri), colors.HexColor('#f8fcfe')),
                ('TEXTCOLOR',  (0, ri), (0,  ri), GREY),
                ('TEXTCOLOR',  (1, ri), (1,  ri), TEAL_DARK),
                ('FONTSIZE',   (0, ri), (-1, ri), 7),
                ('FONTNAME',   (0, ri), (0,  ri), 'Helvetica-Oblique'),
                ('FONTNAME',   (1, ri), (1,  ri), 'Helvetica-Bold'),
            ]

        else:  # 'data'
            if code and code in procs:
                p = procs[code]
                freq_raw = str(p.get('frequency_limit', '')).upper()
                is_not_covered = (
                    'NOT COVERED' in freq_raw
                    or str(p.get('benefit_level', '')).upper() == 'N/A'
                )

                if is_not_covered:
                    freq = 'NC'
                    pct  = '0%'
                    deductible = 'N/A'
                    age  = ''
                    hist = ''
                else:
                    freq = _format_frequency(p.get('frequency_limit', '—'))
                    pct  = p.get('benefit_level', '—')

                    raw_deductible = str(p.get('deductible', '')).strip().upper()
                    deductible = raw_deductible if raw_deductible in ['YES', 'NO'] else ''

                    AGE_LIMIT_CODES = {'D1206', 'D1351', 'D1510', 'D8010', 'D8090'}
                    raw_age = str(p.get('age_limit', '')).strip()
                    if code in AGE_LIMIT_CODES:
                        m = re.search(r'(\d+)\s*[-–]\s*(\d+)', raw_age)
                        if m:
                            age = m.group(2)
                        else:
                            m2 = re.search(r'under\s*(\d+)', raw_age, re.IGNORECASE)
                            age = m2.group(1) if m2 else raw_age
                    else:
                        age = ''

                    if code in HISTORY_CODES:
                        hist_raw = p.get('late_date_of_service', 'NH') or 'NH'
                        hist_str = str(hist_raw).strip()
                        m1 = re.search(r'(\d{4})-(\d{2})-(\d{2})', hist_str)
                        m2 = re.search(r'(\d{2})/(\d{2})/(\d{2})$', hist_str)
                        m3 = re.search(r'(\d{2})/(\d{2})/(\d{4})$', hist_str)
                        if m1:
                            hist = f"{m1.group(2)}/{m1.group(3)}/{m1.group(1)}"
                        elif m2:
                            hist = f"{m2.group(1)}/{m2.group(2)}/20{m2.group(3)}"
                        elif m3:
                            hist = hist_str
                        else:
                            hist = hist_str
                        if hist == '—':
                            hist = 'NH'
                    else:
                        hist = ''

                hist_color = DARK
            else:
                freq = pct = deductible = age = hist = ''
                hist_color = GREY

            rows.append([label, freq, pct, deductible, age, hist])
            bg = colors.HexColor('#f8fcfe') if alt else WHITE
            xstyle += [
                ('BACKGROUND', (0, ri), (-1, ri), bg),
                ('TEXTCOLOR',  (5, ri), (5,  ri), hist_color),
            ]
            alt = not alt

    base = [
        ('BACKGROUND',    (0, 0), (-1, 0),  TEAL),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  WHITE),
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0),  8.5),
        ('ALIGN',         (1, 0), (-1, 0),  'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 1), (-1, -1), 7.5),
        ('ALIGN',         (1, 1), (-1, -1), 'CENTER'),
        ('ALIGN',         (0, 1), (0, -1),  'LEFT'),
        ('TEXTCOLOR',     (1, 1), (-1, -1), TEAL),
        ('TEXTCOLOR',     (0, 1), (0, -1),  DARK),
        ('GRID',          (0, 0), (-1, -1), 0.4, BORDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEADING',       (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
    ]

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(base + xstyle))
    return tbl


def _draw_page2_header(c, page_num, total_pages):
    _filled_rect(c, 0, 0, W, 30, fill=TEAL)
    _txt(c, MARGIN,      22, 'General Benefit Details', 'Helvetica-Bold', 11, WHITE)
    _rtxt(c, W - MARGIN, 22, 'Powered By iSpace',       'Helvetica-Oblique', 8, colors.HexColor('#c0e8f5'))
    _footer(c, page_num, total_pages)


def _page2(c, d, start_page, total_pages):
    tbl = _build_benefit_table(d)
    top_margin = 36
    bot_margin = 95
    avail_h    = H - top_margin - bot_margin

    w, h = tbl.wrapOn(c, CW, avail_h)

    if h <= avail_h:
        _draw_page2_header(c, start_page, total_pages)
        tbl.drawOn(c, MARGIN, H - top_margin - h)
    else:
        tbl.repeatRows = 1
        frags = tbl.split(CW, avail_h)
        for i, frag in enumerate(frags):
            if i > 0:
                c.showPage()
            _draw_page2_header(c, start_page + i, total_pages)
            fw, fh = frag.wrapOn(c, CW, avail_h)
            frag.drawOn(c, MARGIN, H - top_margin - fh)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def generate_new_plan_pdf(
    portal_raw:   dict,
    denticon_raw: dict,
    ins_override: dict | None = None,
) -> bytes:
    """
    Build and return PDF bytes for an Insurance Plan Breakdown.

    Parameters
    ----------
    portal_raw   : full Portal JSON (contains metlife_data, benefit_coverage …)
    denticon_raw : full Denticon JSON (contains denticon_data, and/or benefit_coverage)
    ins_override : optional dict from the UI modal:
                     'insName'      → overrides ins_name  (Insurance Name on PDF)
                     'feeSchedule'  → overrides fee_schedule
                     'relationship' → overrides Relation to Subscriber
    """
    log.info("Generating New Plan PDF...")

    data = _extract(portal_raw, denticon_raw)

    # ── Apply UI modal overrides — these always win over auto-extracted values ──
    if ins_override:
        ins_name = (ins_override.get('insName') or '').strip()
        fee_sch  = (ins_override.get('feeSchedule') or '').strip()
        rel      = (ins_override.get('relationship') or '').strip()

        if ins_name:
            data['ins_name'] = ins_name
            log.info(f"[override] ins_name     → {ins_name}")

        if fee_sch:
            data['fee_schedule'] = fee_sch
            log.info(f"[override] fee_schedule → {fee_sch}")

        if rel:
            data['relationship'] = rel
            # Recalculate family ded with the corrected relationship
            data['family_ded'] = _family_deductible_v2(
                fam_total_raw   = data.get('family_ded',  ''),
                indiv_total_raw = data.get('indiv_ded',   ''),
                relationship    = rel,
            )
            log.info(f"[override] relationship → {rel}")

    if log.isEnabledFor(logging.DEBUG):
        log.debug("FINAL DATA (after overrides):")
        for k, v in data.items():
            if k != 'procs':
                log.debug("  %s: %s", k, v)

    buf = io.BytesIO()
    c   = canvas.Canvas(buf, pagesize=letter)

    _tbl     = _build_benefit_table(data)
    avail    = H - 72
    _, tbl_h = _tbl.wrapOn(c, CW, avail)
    extra_pages = max(1, int(tbl_h // avail) + (1 if tbl_h % avail else 0))
    total_pages = 1 + extra_pages

    _page1(c, data, total_pages)
    c.showPage()
    _page2(c, data, start_page=2, total_pages=total_pages)

    c.save()
    return buf.getvalue()