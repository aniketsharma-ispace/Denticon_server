"""
Helpers shared by every insurer reader. Copied unchanged from the client
portals/common.py files, where they are identical in every client.
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


def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()
