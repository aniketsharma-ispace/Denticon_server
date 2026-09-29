"""
new_plan.py
-----------
Generates an "Insurance Plan Breakdown – (New Plan)" PDF from the
MetLife, Cigna, or Aetna Portal JSON and the Denticon JSON.

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
import requests
from xml.sax.saxutils import escape
from datetime import datetime, timedelta, timezone

from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import simpleSplit
from reportlab.platypus import Paragraph, Table, TableStyle

# ─── Page geometry ─────────────────────────────────────────────────────────────
W, H     = letter          # 612 × 792 pt

# ═══════════════════════════════════════════════════════════════════════════════
#  PORTAL READERS
#
#  Each carrier's export is recognized and translated by its own module under
#  `portals/`. They are imported here, rather than defined here, so that this
#  file is the Breakdown PDF builder and nothing else — and so the audit can
#  use the same readers without going through the PDF.
# ═══════════════════════════════════════════════════════════════════════════════

from .portals.common import _format_history_dates, clean
from .portals.aetna import _is_aetna_portal
from .portals.cigna import _cigna_frequency_is_unavailable, _is_cigna_portal
from .breakdown import (  # noqa: F401  (re-exported)
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    OLLAMA_URL,
    RELATION_MAP,
    _CARRIER_PRE_AUTH,
    _FINANCIAL_OUTPUT_KEYS,
    _LLM_DEFAULT_ANSWERS,
    _LLM_QUESTIONS_PROMPT,
    _build_insurance_address,
    _clean_phone,
    _covered_pct,
    _covered_pct_max,
    _deductible_applies,
    _extract,
    _extract_basis_of_payment,
    _extract_dependent_age_limit,
    _extract_missing_tooth_text,
    _family_deductible_v2,
    _finalize_shared_output,
    _g,
    _get_plan_year_start,
    _interpret_provisions,
    _llm_build_context,
    _llm_call_ollama,
    _llm_normalize,
    _missing_tooth_clause,
    _number_of_quads_d4341,
    _parse_pre_auth,
    _parse_waiting_period,
    _procedure_benefit_pct,
    _rule_alternate_benefit_downgrades,
    _rule_based_interp,
    _rule_d2950_same_day_crown,
    _rule_molars_only_sealants,
    _yes_no_from_basis,
    _zero_money,
)

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


USE_CLAUDE_FALLBACK = False
CLAUDE_MODEL        = "claude-sonnet-4-20250514"






























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




def _format_frequency(freq, compact=False):
    if not freq or freq == '—':
        return '—'
    f = str(freq).upper().strip()
    f = re.sub(r'\s+', ' ', f)
    if f in ('N/A', 'NA', 'NOT APPLICABLE'):
        return 'N/A'
    if 'NO LIMIT' in f:      return 'NO FREQUENCY' if compact else 'No Frequency'
    if 'NO FREQUENCY' in f:  return 'NO FREQUENCY' if compact else 'No Frequency'
    if 'NOT COVERED' in f:   return 'NC'
    if 'NOT AVAILABLE' in f: return 'NOT AVAILABLE'
    if f in ['PRE-D', 'PRE D']: return 'Pre-D'

    # ClaimConnect/Aetna phrases limits as, for example:
    #   "2 Units, for 1 Calendar Year ..."
    #   "1 Visit, per 24 Months ..."
    # Preserve the leading unit/visit count before the generic "per N"
    # parser sees only the duration and incorrectly reduces 2X1 to 1X1.
    m = re.search(
        r'\b(\d+)\s*(?:UNITS?|VISITS?|TIMES?|SERVICES?)\s*,?\s*'
        r'(?:FOR|IN|PER|EVERY)\s+(\d+)\s*'
        r'(?:CONSECUTIVE\s+|CALENDAR\s+|POLICY\s+)?'
        r'(MONTH|YEAR|DAY)S?\b',
        f,
        re.IGNORECASE,
    )
    if m:
        count = m.group(1)
        duration = m.group(2)
        unit = m.group(3).upper()
        if int(duration) != 1:
            unit += 'S'
        return f'{count}X{duration}{unit}' if compact else f'{count}X{duration} {unit.title()}'

    m = re.search(r'\b(?:EVERY|PER)\s+(\d+)\s*(?:CALENDAR\s+|POLICY\s+)?(MONTH|YEAR|DAY)S?\b', f, re.IGNORECASE)
    if m:
        duration = m.group(1)
        unit = m.group(2).upper()
        if int(duration) != 1:
            unit += 'S'
        return f'1X{duration}{unit}' if compact else f'1X{duration} {unit.title()}'
    m = re.search(r'\b(\d+)\s*X\s*(\d+)\s*(MONTH|YEAR|DAY)S?\b', f, re.IGNORECASE)
    if m:
        count = m.group(1)
        duration = m.group(2)
        unit = m.group(3).upper()
        if int(duration) != 1:
            unit += 'S'
        return f'{count}X{duration}{unit}' if compact else f'{count}X{duration} {unit.title()}'
    m = re.search(r'\b(\d+)\s*X\s*LIFETIME\b', f, re.IGNORECASE)
    if m:
        return f'{m.group(1)}XLIFETIME' if compact else f"{m.group(1)}XLifetime"
    word_counts = {
        'ONCE': '1',
        'ONE': '1',
        'TWICE': '2',
        'TWO': '2',
        'THRICE': '3',
        'THREE': '3',
        'FOUR': '4',
    }
    word_pattern = '|'.join(word_counts)
    m = re.search(
        rf'\b({word_pattern})\b\s*(?:TIME\S*)?\s*(?:IN|PER|EVERY)?\s*(\d+)?\s*(?:CONSECUTIVE\s+|CALENDAR\s+|POLICY\s+)?(MONTH|YEAR|DAY)S?',
        f,
        re.IGNORECASE
    )
    if m:
        count = word_counts[m.group(1).upper()]
        duration = m.group(2) or '1'
        unit = m.group(3).upper()
        if int(duration) != 1:
            unit += 'S'
        return f'{count}X{duration}{unit}' if compact else f'{count}X{duration} {unit.title()}'
    m = re.search(
        r'(\d+)\s*(?:TIME\S*|X)?\s*(?:IN|PER|EVERY)\s*(\d+)\s*(?:CALENDAR\s+|POLICY\s+)?(MONTH|YEAR|DAY)S?',
        f,
        re.IGNORECASE
    )
    if m:
        count    = m.group(1)
        duration = m.group(2)
        unit     = m.group(3).upper()
        if int(duration) != 1:
            unit += 'S'
        return f'{count}X{duration}{unit}' if compact else f'{count}X{duration} {unit.title()}'
    m = re.search(
        r'(\d+)\s*(?:TIME\S*|X|PER)?\s*(?:IN|PER|EVERY)?\s*(?:ONE|1)?\s*(?:CALENDAR\s+|POLICY\s+)?(MONTH|YEAR|DAY)S?',
        f,
        re.IGNORECASE
    )
    if m:
        return (
            f"{m.group(1)}X1{m.group(2).upper()}"
            if compact else f"{m.group(1)}X1 {m.group(2).title()}"
        )
    m = re.search(
        r'(\d+)\s*(?:TIME\S*|X)?\s*(?:IN|PER|EVERY)\s*(\d+)\s*(MONTH|YEAR|DAY)S?',
        f,
        re.IGNORECASE
    )
    if m:
        count = m.group(1)
        duration = m.group(2)
        unit = m.group(3).upper()
        if int(duration) != 1:
            unit += 'S'
        return f'{count}X{duration}{unit}' if compact else f'{count}X{duration} {unit.title()}'
    m = re.search(r'(\d+)\s*(?:TIME\S*|X)?\s*(?:IN|PER|EVERY)?\s*LIFETIME', f)
    if m or 'LIFETIME' in f:
        return f"{m.group(1) if m else '1'}XLIFETIME" if compact else f"{m.group(1) if m else '1'}XLifetime"
    if 'PROVIDER' in f:
        return '1XPROVIDER' if compact else '1XProvider'
    return f if compact else freq


def _format_person_name(name):
    if not name or name == '—':
        return '—'
    name = str(name).strip()
    if ',' in name:
        last, first = [x.strip() for x in name.split(',', 1)]
        return f"{first.title()} {last.title()}"
    return name.title()










































































































































































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


def _fit_text_lines(text, font, size, max_width, max_lines=1):
    """Wrap text to a bounded width, including strings with no spaces."""
    text = clean(text)
    if not text:
        return [''], size
    if not max_width:
        return [text], size
    if stringWidth(text, font, size) <= max_width:
        return [text], size

    # Keep compact values on one line when a small font adjustment is enough.
    for fitted_size in (size - 0.5, size - 1, size - 1.5, max(6, size - 2)):
        if stringWidth(text, font, fitted_size) <= max_width:
            return [text], fitted_size

    words = text.split()
    lines, current = [], ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if stringWidth(candidate, font, size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ''
        # Split an oversized token so it cannot escape the box.
        while word and stringWidth(word, font, size) > max_width:
            cut = len(word)
            while cut > 1 and stringWidth(word[:cut], font, size) > max_width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and stringWidth(last + '…', font, size) > max_width:
            last = last[:-1]
        lines[-1] = (last.rstrip() + '…') if last else '…'
    return lines or ['—'], size


def _bounded_txt(c, x, y, text, max_width, font='Helvetica', size=8,
                 color=DARK, max_lines=1, leading=None):
    lines, fitted_size = _fit_text_lines(
        text, font, size, max_width, max_lines=max_lines
    )
    leading = leading or fitted_size + 1
    for i, line in enumerate(lines):
        _txt(c, x, y + (i * leading), line, font, fitted_size, color)


def _lv(c, x, y, label, value, lsz=7, vsz=8.5, vcolor=TEAL, gap=14,
        max_width=None, max_lines=1):
    _txt(c, x, y, label, 'Helvetica', lsz, GREY)
    _bounded_txt(
        c, x, y + gap, value if value is not None else '—', max_width,
        'Helvetica-Bold', vsz, vcolor, max_lines=max_lines,
        leading=max(7, vsz + 1),
    )


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
    office_value_w = HALF - 10
    _lv(c, MARGIN + 5, y + 22,  'Office Name',             d['office_name'],         max_width=office_value_w)
    _lv(c, MARGIN + 5, y + 46,  'Preferred Provider Name', d['provider_name'],       max_width=office_value_w)
    _lv(c, MARGIN + 5, y + 70,  'Chair Provider Name',     d['chair_provider'],      max_width=office_value_w)
    _lv(c, MARGIN + 5, y + 94,  'Provider Speciality',     d['provider_speciality'], max_width=office_value_w)
    _lv(c, MARGIN + 5, y + 118, 'Appointment Date',        d['appointment_date'],    max_width=office_value_w)

    px = MARGIN + HALF + 8
    _filled_rect(c, px, y, HALF, BOX_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _filled_rect(c, px, y, HALF, 15,    fill=TEAL)
    _txt(c, px + 5, y + 11, 'Patient / Subscriber Information', 'Helvetica-Bold', 8.5, WHITE)

    HC = HALF / 2
    patient_value_w = HC - 10
    _lv(c, px + 5,      y + 22, 'Patient Name',           d['patient_name'],    max_width=patient_value_w)
    _lv(c, px + HC + 3, y + 22, 'Date of Birth',          d['patient_dob'],     max_width=patient_value_w)
    _lv(c, px + 5,      y + 46, 'Member ID#',             d['member_id'],       max_width=patient_value_w)
    _lv(c, px + HC + 3, y + 46, 'Relation to Subscriber', d['relationship'],    max_width=patient_value_w)
    _lv(c, px + 5,      y + 70, 'Subscriber Name',        d['subscriber_name'], max_width=patient_value_w)
    _lv(c, px + HC + 3, y + 70, 'Date of Birth',          d['subscriber_dob'],  max_width=patient_value_w)
    _lv(c, px + 5,      y + 94, 'SSN#',                   d['ssn'],             max_width=patient_value_w)
    y += BOX_H + 5

    INS_BOX_H = 175

    _filled_rect(c, MARGIN, y, CW, INS_BOX_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _sec_bar(c, MARGIN, y, CW, 16, 'Insurance Information')

    T3 = CW / 3

    r1 = y + 34
    insurance_value_w = T3 - 20
    _lv(c, MARGIN + 10,          r1, 'Insurance Name', d['ins_name'],     lsz=7, vsz=9, gap=14, max_width=insurance_value_w, max_lines=2)
    _lv(c, MARGIN + T3 + 10,     r1, 'Group Name',     d['group_name'],   lsz=7, vsz=9, gap=14, max_width=insurance_value_w, max_lines=2)
    _lv(c, MARGIN + (T3*2) + 10, r1, 'Group Number',   d['group_number'], lsz=7, vsz=9, gap=14, max_width=insurance_value_w, max_lines=2)
    _hline(c, MARGIN, y + 72, W - MARGIN, lw=0.35)

    r2 = y + 92
    _lv(c, MARGIN + 10,          r2, 'Fee Schedule',      d['fee_schedule'], lsz=7, vsz=9,   gap=14, max_width=insurance_value_w, max_lines=2)
    _lv(c, MARGIN + T3 + 10,     r2, 'Insurance Address', d['ins_address'],  lsz=7, vsz=8.5, gap=14, max_width=insurance_value_w, max_lines=2)
    _lv(c, MARGIN + (T3*2) + 10, r2, 'Insurance Phone',   d['ins_phone'],    lsz=7, vsz=9,   gap=14, max_width=insurance_value_w, max_lines=2)
    _hline(c, MARGIN, y + 126, W - MARGIN, lw=0.35)

    r3 = y + 146
    _lv(c, MARGIN + 10,          r3, 'Provider Network Status', d['network_status'], lsz=7, vsz=9, gap=14, max_width=insurance_value_w)
    _lv(c, MARGIN + T3 + 10,     r3, 'Patient Eff Date',        d['eff_date'],        lsz=7, vsz=9, gap=14, max_width=insurance_value_w)
    _lv(c, MARGIN + (T3*2) + 10, r3, 'Patient Term Date',       d['term_date'],       lsz=7, vsz=9, gap=14, max_width=insurance_value_w)

    y += INS_BOX_H

    ROW_H = 44
    _filled_rect(c, MARGIN, y, CW, ROW_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _hline(c, MARGIN, y + 1, W - MARGIN, color=BORDER, lw=0.3)
    _lv(c, MARGIN + 12,          y + 14, 'PPO / Indemnity / HMO Plan?', d['plan_type'],       lsz=7, vsz=9, gap=16, max_width=T3 - 24)
    _lv(c, MARGIN + T3 + 12,     y + 14, 'Starting Month of Plan Year', d['plan_year_start'], lsz=7, vsz=9, gap=16, max_width=T3 - 24)
    _lv(c, MARGIN + (T3*2) + 12, y + 14, 'Payor ID',                    d['payor_id'],         lsz=7, vsz=9, gap=16, max_width=T3 - 24)

    y += ROW_H

    EN_H = 24
    _filled_rect(c, MARGIN, y, CW, EN_H, fill=GREY_LIGHT, stroke_color=BORDER)
    _txt(c, MARGIN + 5,  y + 8, 'Eligibility Notes:', 'Helvetica',      7.5, GREY)
    _bounded_txt(c, MARGIN + 68, y + 8, d['elig_notes'], CW - 75,
                 'Helvetica-Bold', 8, TEAL, max_lines=2, leading=9)
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
        _lv(c, MARGIN + 5, cv_y, l1, v1, vsz=8, gap=11,
            max_width=HALF_CW - 12)
        if l2:
            _lv(c, MARGIN + HALF_CW + 5, cv_y, l2, v2, vsz=8, gap=11,
                max_width=HALF_CW - 12)
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
    ('Full Mouth X-Ray (D0210)',                      'D0210', 'data'),
    ('PA (D0220)',                                    'D0220', 'data'),
    ('PA Additional (D0230)',                         'D0230', 'data'),
    ('Intraoral - Occlusal Image (D0240)',            'D0240', 'data'),
    ('Bitewings (D0274)',                             'D0274', 'data'),
    ('Panoramic X-Ray (D0330)',                       'D0330', 'data'),

    ('PREVENTIVE',                                    None,    'cat'),
    ('Space Maintainer (D1510)',                      'D1510', 'data'),
    ('Prophylaxis (D1110)',                           'D1110', 'data'),
    ('Prophylaxis Child (D1120)',                     'D1120', 'data'),
    ('Fluoride (D1206, D1208)',                       'D1206', 'data'),
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
    ('Number of quads for the code D4341',             None,    'note'),
    ('Full Mouth Debridement (D4355)',                'D4355', 'data'),
    ('Arestin (D4381)',                               'D4381', 'data'),
    ('Perio Maintenance (D4910)',                     'D4910', 'data'),
    ('Do D4910 and D1110 share a frequency?',         None,    'note'),

    ('REMOVABLE PROSTHODONTICS',                      None,    'cat'),
    ('Over Denture Complete (D5860)',                 'D5860', 'data'),
    ('Dentures (D5110)',                              'D5110', 'data'),
    ('Reline maxillary partial denture (direct) (D5740)', 'D5740', 'data'),
    ('Surgical stent (D5982)',                        'D5982', 'data'),

    ('IMPLANT',                                       None,    'cat'),
    ('Implant (D6194)',                               'D6194', 'data'),
    ('Implant Body (D6010)',                          'D6010', 'data'),
    ('Implant Abutment (D6056)',                      'D6056', 'data'),
    ('Implant Crown (D6065) Y/N',                     'D6065', 'data'),

    ('FIXED PROSTHODONTICS',                          None,    'cat'),
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
    ('General Anesthesia (D9222)',                    'D9222', 'data'),
    ('Sedation/Analgesia (D9239)',                    'D9239', 'data'),
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
    'Number of quads for the code D4341':            'd4341_number_of_quads',
    'Payment Frequency':                            'ortho_payment_frequency',
    'Ortho Age Limit':                              'ortho_age_limit_llm',
}


def _table_text(value, width, align='CENTER', color=TEAL, bold=False,
                italic=False, size=7.3):
    """Create a wrapping table cell that cannot paint over adjacent columns."""
    font = (
        'Helvetica-BoldOblique' if bold and italic else
        'Helvetica-Bold' if bold else
        'Helvetica-Oblique' if italic else
        'Helvetica'
    )
    style = ParagraphStyle(
        name=f'bounded-{font}-{align}-{size}',
        fontName=font,
        fontSize=size,
        leading=size + 1.2,
        textColor=color,
        alignment={'LEFT': 0, 'CENTER': 1, 'RIGHT': 2}.get(align, 1),
        wordWrap='CJK',  # also wraps IDs/URLs/other unbroken strings
        splitLongWords=True,
        allowWidows=0,
        allowOrphans=0,
        spaceBefore=0,
        spaceAfter=0,
    )
    safe = escape(str('—' if value is None else value)).replace('\n', '<br/>')
    return Paragraph(safe, style)


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
        'D0180', 'D0120', 'D0140', 'D0150', 'D1351', 'D0274', 'D0210',
        'D0330', 'D1110', 'D1120', 'D1206', 'D1208', 'D4355', 'D4910'
    }
    ORTHO_AGE_CODES = {'D8010', 'D8080', 'D8090'}
    for label, pct in [('Preventive', d['pct_prev']),
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

            rows.append([
                _table_text(label, col_w[0] - 8, 'LEFT', GREY, italic=True, size=7),
                _table_text(note_val, col_w[1] - 8, 'CENTER', TEAL_DARK, bold=True, size=7),
                '', '', '', '',
            ])
            xstyle += [
                ('BACKGROUND', (0, ri), (-1, ri), colors.HexColor('#f8fcfe')),
                ('TEXTCOLOR',  (0, ri), (0,  ri), GREY),
                ('TEXTCOLOR',  (1, ri), (1,  ri), TEAL_DARK),
                ('FONTSIZE',   (0, ri), (-1, ri), 7),
                ('FONTNAME',   (0, ri), (0,  ri), 'Helvetica-Oblique'),
                ('FONTNAME',   (1, ri), (1,  ri), 'Helvetica-Bold'),
            ]

        else:  # 'data'
            p = {}
            display_proc = None
            display_label = label
            display_code = code
            if label == 'Fluoride (D1206, D1208)':
                if d.get('source_insurer') == 'cigna':
                    display_proc = procs.get('_CIGNA_FLUORIDE_DISPLAY')
                elif d.get('source_insurer') == 'aetna':
                    display_proc = procs.get('_AETNA_FLUORIDE_DISPLAY')
                    has_d1206 = bool(procs.get('D1206'))
                    has_d1208 = bool(procs.get('D1208'))
                    if has_d1206 and not has_d1208:
                        display_label = 'Fluoride (D1206)'
                        display_code = 'D1206'
                    elif has_d1208 and not has_d1206:
                        display_label = 'Fluoride (D1208)'
                        display_code = 'D1208'
                    elif has_d1206 and has_d1208:
                        display_label = 'Fluoride (D1206, D1208)'

            if display_code and (display_code in procs or display_proc):
                p = display_proc or procs[display_code]
                freq_raw = str(p.get('frequency_limit', '')).upper()
                is_not_covered = (
                    'NOT COVERED' in freq_raw
                    or str(p.get('benefit_level', '')).upper() == 'N/A'
                )
                is_unresolved_cigna = (
                    d.get('source_insurer') == 'cigna'
                    and display_code != 'D5860'
                    and p.get('_cigna_covered') is None
                )

                blank_cigna_d1510 = (
                    d.get('source_insurer') == 'cigna'
                    and display_code == 'D1510'
                    and (p.get('_cigna_covered') is False or is_not_covered)
                )

                if blank_cigna_d1510:
                    # Cigna business rule: an explicitly not-covered D1510 row
                    # keeps its label but leaves Frequency, Percentage,
                    # Deductible, Age Limit, and History completely blank.
                    freq = pct = deductible = age = hist = ''
                elif is_unresolved_cigna:
                    freq = pct = deductible = age = '-'
                    hist = '-' if display_code in HISTORY_CODES else ''
                elif is_not_covered:
                    freq = 'NC'
                    pct  = '0%'
                    deductible = 'N/A'
                    age  = ''
                    hist = ''
                else:
                    raw_frequency = p.get('frequency_limit', '—')
                    freq = _format_frequency(
                        raw_frequency,
                        compact=(
                            d.get('source_insurer') == 'cigna'
                            and display_code != 'D1351'
                        ),
                    )
                    if (
                        d.get('source_insurer') == 'cigna'
                        and _cigna_frequency_is_unavailable(raw_frequency)
                    ):
                        freq = 'No Frequency'
                    pct  = p.get('benefit_level', '—')

                    raw_deductible = str(p.get('deductible', '')).strip().upper()
                    deductible = raw_deductible if raw_deductible in ['YES', 'NO'] else ''

                    AGE_LIMIT_CODES = {'D1206', 'D1208', 'D1351', 'D1510', 'D8010', 'D8080', 'D8090'}
                    raw_age = str(p.get('age_limit', '')).strip()
                    if display_code in AGE_LIMIT_CODES or d.get('source_insurer') == 'cigna':
                        m = re.search(r'(\d+)\s*[-–]\s*(\d+)', raw_age)
                        if m:
                            age = m.group(2)
                        else:
                            m2 = re.search(r'under\s*(\d+)', raw_age, re.IGNORECASE)
                            m3 = re.search(
                                r'(?:exclude|excluded)\s+after\s+age\s*(\d+)',
                                raw_age,
                                re.IGNORECASE,
                            )
                            age = (
                                m2.group(1) if m2 else
                                m3.group(1) if m3 else
                                raw_age
                            )
                        if (
                            d.get('source_insurer') == 'cigna'
                            and display_code in ORTHO_AGE_CODES
                            and p.get('_cigna_covered') is True
                            and str(age).strip().lower() in ('', '-', '—', 'n/a', 'na', 'none')
                        ):
                            age = str(d.get('ortho_age_limit_llm') or '').strip()
                        elif (
                            d.get('source_insurer') != 'cigna'
                            and display_code in ORTHO_AGE_CODES
                            and str(age).strip() in ('99', '999')
                        ):
                            age = ''
                    else:
                        age = ''

                    if display_code in HISTORY_CODES:
                        hist_raw = p.get('late_date_of_service', 'NH')
                        if not hist_raw:
                            hist_raw = (
                                'NH'
                            )
                        hist = _format_history_dates(hist_raw) or str(hist_raw).strip()
                        if hist == '—':
                            hist = 'NH'
                    else:
                        hist = ''

                if d.get('source_insurer') == 'cigna' and not blank_cigna_d1510:
                    if str(freq).strip() in ('', '—'):
                        freq = '-'
                    if str(pct).strip() in ('', '—'):
                        pct = '-'
                    if str(deductible).strip() in ('', '—'):
                        deductible = '-'
                    if str(age).strip() in ('', '—'):
                        age = '' if display_code in ORTHO_AGE_CODES else '-'
                    if display_code in HISTORY_CODES and str(hist).strip() in ('', '—'):
                        hist = 'NH' if display_code in HISTORY_CODES else '-'
                    elif display_code not in HISTORY_CODES:
                        hist = ''

                hist_color = DARK
            else:
                if d.get('source_insurer') == 'cigna':
                    freq = pct = deductible = age = '-'
                    hist = 'NH' if display_code in HISTORY_CODES else ''
                else:
                    freq = pct = deductible = age = hist = ''
                hist_color = GREY

            if d.get('source_insurer') == 'cigna' and display_code in ORTHO_AGE_CODES:
                proc_covered = (p.get('_cigna_covered') if display_code and display_code in procs else None)
                if proc_covered is False:
                    age = ''
                elif proc_covered is True and str(age).strip().lower() in (
                    '', '-', '—', 'n/a', 'na', 'none'
                ):
                    age = str(d.get('ortho_age_limit_llm') or '').strip()
                elif proc_covered is None:
                    age = ''

            rows.append([
                _table_text(display_label, col_w[0] - 8, 'LEFT',   DARK),
                _table_text(freq,       col_w[1] - 8, 'CENTER', TEAL),
                _table_text(pct,        col_w[2] - 8, 'CENTER', TEAL),
                _table_text(deductible, col_w[3] - 8, 'CENTER', TEAL),
                _table_text(age,        col_w[4] - 8, 'CENTER', TEAL),
                _table_text(hist,       col_w[5] - 8, 'CENTER', hist_color),
            ])
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
    ins_override: dict = None,
) -> bytes:
    """
    Build and return PDF bytes for an Insurance Plan Breakdown.

    Parameters
    ----------
    portal_raw   : full Portal JSON (contains metlife_data, benefit_coverage …)
    denticon_raw : Denticon JSON used only for the Office Information block
    ins_override : optional dict from the UI modal:
                     'insName'      → overrides ins_name  (Insurance Name on PDF)
                     'feeSchedule'  → overrides fee_schedule
                     'relationship' → overrides Relation to Subscriber
                     'providerNetworkStatus' / 'provider_network_status'
                                    → overrides Provider Network Status (PPO/IN/OUT)
    """
    print("PDF FUNCTION STARTED")

    data = _extract(portal_raw, denticon_raw)

    # ── Apply UI modal overrides — these always win over auto-extracted values ──
    if ins_override:
        ins_name = (ins_override.get('insName') or '').strip()
        fee_sch  = (ins_override.get('feeSchedule') or '').strip()
        rel      = (ins_override.get('relationship') or '').strip()
        provider_network_status = (
            ins_override.get('providerNetworkStatus')
            or ins_override.get('provider_network_status')
            or ''
        ).strip()

        if ins_name:
            data['ins_name'] = ins_name
            print(f"[override] ins_name     → {ins_name}")

        if fee_sch:
            data['fee_schedule'] = fee_sch
            print(f"[override] fee_schedule → {fee_sch}")

        if rel:
            data['relationship'] = rel
            # Cigna must reflect only a family accumulator explicitly returned
            # by the selected network.
            if data.get('source_insurer') != 'cigna':
                data['family_ded'] = _family_deductible_v2(
                    fam_total_raw   = data.get('family_ded',  ''),
                    indiv_total_raw = data.get('indiv_ded',   ''),
                    relationship    = rel,
                )
            print(f"[override] relationship → {rel}")

        if provider_network_status:
            normalized_status = provider_network_status.upper()
            if normalized_status in ('PPO', 'IN', 'OUT'):
                data['network_status'] = normalized_status
            else:
                data['network_status'] = provider_network_status
            print(f"[override] provider network status → {data['network_status']}")

    data = _finalize_shared_output(data)

    print("FINAL DATA (after overrides):")
    for k, v in data.items():
        if k != 'procs':
            print(f"  {k}: {v}")

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


# ═══════════════════════════════════════════════════════════════════════════════
#  DOWNLOAD FILENAME HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_pdf_filename(value: str, fallback: str = 'Insurance_Plan.pdf') -> str:
    """Return a safe, basename-only ASCII PDF filename."""
    raw = str(value or '').strip().replace('\\', '/').split('/')[-1]
    if not raw:
        raw = fallback

    stem = re.sub(r'(?i)\.pdf$', '', raw).strip()
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', stem)
    stem = re.sub(r'_+', '_', stem).strip('._-')
    if not stem:
        stem = re.sub(r'(?i)\.pdf$', '', fallback).strip() or 'Insurance_Plan'
    return f'{stem[:180]}.pdf'


def _filename_patient_name(portal_raw: dict) -> str:
    """Find the patient name across raw Aetna, Cigna, MetLife and parsed payloads."""
    raw = portal_raw if isinstance(portal_raw, dict) else {}
    candidates = []

    def add(container, *keys):
        cur = container
        for key in keys:
            if not isinstance(cur, dict):
                return
            cur = cur.get(key)
        if cur not in (None, '', [], {}):
            candidates.append(str(cur).strip())

    add(raw, 'selected_member', 'name')
    add(raw, 'patient_information', 'name')
    add(raw, 'patient', 'name')
    add(raw, 'metlife_data', 'patient', 'name')
    add(raw, 'cigna_data', 'patient', 'name')
    add(raw, 'cigna_data', 'patient_info', 'name')
    add(raw, 'dentaquest_data', 'patient', 'name')
    add(raw, 'delta_data', 'patient', 'name')
    add(raw, 'subscriber_info', 'name')

    for value in candidates:
        if value and value not in ('-', '—', 'N/A', 'NA'):
            return value
    return 'Patient'


def _filename_carrier_name(portal_raw: dict) -> str:
    """Resolve a concise carrier label for the download filename."""
    raw = portal_raw if isinstance(portal_raw, dict) else {}
    source = str(raw.get('source') or '').lower()
    payer = raw.get('payer') if isinstance(raw.get('payer'), dict) else {}
    carrier = raw.get('carrier_information') if isinstance(raw.get('carrier_information'), dict) else {}
    names = ' '.join(str(v or '') for v in (
        source,
        payer.get('name'),
        carrier.get('name'),
        (raw.get('coverage_details') or {}).get('payer') if isinstance(raw.get('coverage_details'), dict) else '',
    )).lower()

    if _is_aetna_portal(raw) or 'aetna' in names:
        return 'Aetna'
    if _is_cigna_portal(raw) or 'cigna' in names or isinstance(raw.get('cigna_data'), dict):
        return 'Cigna'
    if 'metlife' in names or isinstance(raw.get('metlife_data'), dict):
        return 'MetLife'
    if 'dentaquest' in names or isinstance(raw.get('dentaquest_data'), dict):
        return 'DentaQuest'
    if 'delta' in names or isinstance(raw.get('delta_data'), dict):
        return 'Delta_Dental'
    if 'guardian' in names:
        return 'Guardian'

    explicit = payer.get('name') or carrier.get('name') or 'Insurance'
    return re.sub(r'\b(?:dental\s+plans?|insurance)\b', '', str(explicit), flags=re.I).strip() or 'Insurance'


def build_new_plan_pdf_filename(
    portal_raw: dict,
    download_filename: str = None,
) -> str:
    """Build the browser download name, unless an optional safe override is supplied."""
    if str(download_filename or '').strip():
        return _safe_pdf_filename(download_filename)

    patient = _filename_patient_name(portal_raw)
    carrier = _filename_carrier_name(portal_raw)
    run_date = datetime.now(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime('%Y-%m-%d')
    return _safe_pdf_filename(
        f'{patient}_{carrier}_Insurance_Plan_{run_date}.pdf'
    )


def generate_new_plan_pdf_with_filename(
    portal_raw: dict,
    denticon_raw: dict,
    ins_override: dict = None,
    download_filename: str = None,
):
    """Return ``(pdf_bytes, filename)`` without changing the original PDF API."""
    pdf_bytes = generate_new_plan_pdf(
        portal_raw,
        denticon_raw,
        ins_override=ins_override,
    )
    filename = build_new_plan_pdf_filename(
        portal_raw,
        download_filename=download_filename,
    )
    return pdf_bytes, filename
