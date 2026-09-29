"""
MetLife.

MetLife has no normalizer of its own: its export is already in the shape the
shared extraction reads, so it *is* the default path through
`breakdown._extract`, selected by the `is_metlife` flag rather than by a
`_is_metlife_portal` check. Only the pieces that are MetLife's alone live here;
the rest of MetLife's handling is those `is_metlife` branches.
"""

import re


def _extract_metlife_ortho_age_limit(provisions):
    """Return only the numeric MetLife child/student orthodontic age limit."""
    candidates = []
    for p in provisions or []:
        rule = str(p.get('rule', '')).lower()
        if 'orthodont' not in rule or 'age' not in rule:
            continue
        value = str(p.get('value', ''))
        # Prefer Child/Student values and ignore employee/spouse no-age-limit text.
        for m in re.finditer(r'(?:child|student)\s*:?\s*(\d+)', value, re.IGNORECASE):
            candidates.append(int(m.group(1)))
        if not candidates:
            candidates.extend(int(x) for x in re.findall(r'\b(\d{1,3})\b', value))
    if not candidates:
        return ''
    # Child/student provisions can expose two limits; business rule keeps the greater one.
    return str(max(candidates))
