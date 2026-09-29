"""
Helpers every portal reader needs.

Small, carrier-neutral conversions — money, dates, plan labels — kept here so a
carrier module never has to reach back into the PDF builder for them.
"""

import re
from datetime import datetime


def _dollar(raw, default='—'):
    if not raw or raw == '—':
        return default
    m = re.search(r'\$?\s*([\d,]+\.?\d*)', str(raw))
    if m:
        try:
            return f"{float(m.group(1).replace(',', '')):,.2f}"
        except ValueError:
            pass
    return default


def _effective_date_month(value):
    """Return the plan effective-date month, without inventing a date."""
    raw = str(value or '').strip()
    for pattern in ('%m/%d/%Y', '%Y-%m-%d', '%m-%d-%Y'):
        try:
            return datetime.strptime(raw, pattern).strftime('%B')
        except ValueError:
            pass
    return ''


def _blank_present_end_date(value):
    """Display a blank term date when the plan is active / has no term date."""
    raw = str(value or '').strip()
    text = re.sub(r'\s+', ' ', raw).lower()
    if not text:
        return ''
    if text in (
        '-', '—', 'n/a', 'na', 'none', 'null',
        'present', 'current', 'active', 'ongoing', 'current plan',
        'not available', 'not applicable',
    ):
        return ''
    if re.search(r'\b(present|ongoing|active|current\s+plan)\b', text):
        return ''
    return raw


def _display_plan_type(value, default='-'):
    """Extract just PPO/HMO/INDEMNITY from plan text like 'Dental PPO'."""
    raw = clean(value)
    if not raw or raw == '—':
        return default
    upper = raw.upper()
    for label in ('PPO', 'HMO', 'INDEMNITY'):
        if re.search(rf'\b{label}\b', upper):
            return label
    return upper


def _triple_individual_deductible(value, default='-'):
    """Business fallback when a family deductible is not returned by the portal."""
    match = re.search(r'([\d,.]+)', str(value or ''))
    if not match:
        return default
    return f"{float(match.group(1).replace(',', '')) * 3:,.2f}"


def _format_history_dates(value):
    """Return all history dates as wrapped PDF text instead of only latest."""
    values = []
    if isinstance(value, list):
        candidates = value
    elif value in (None, ''):
        candidates = []
    else:
        candidates = [value]

    for item in candidates:
        if isinstance(item, dict):
            raw = item.get('date') or item.get('serviceDate') or item.get('service_date') or ''
        else:
            raw = str(item or '')
        raw = raw.strip()
        if not raw:
            continue
        if 'no history' in raw.lower():
            return 'NH'
        m1 = re.search(r'(\d{4})-(\d{2})-(\d{2})', raw)
        m2 = re.search(r'(\d{2})/(\d{2})/(\d{2})$', raw)
        m3 = re.search(r'(\d{2})/(\d{2})/(\d{4})$', raw)
        if m1:
            normalized = f"{m1.group(2)}/{m1.group(3)}/{m1.group(1)}"
        elif m2:
            normalized = f"{m2.group(1)}/{m2.group(2)}/20{m2.group(3)}"
        elif m3:
            normalized = raw
        else:
            normalized = raw
        if normalized not in values:
            values.append(normalized)
    return '\n'.join(values)


def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()
