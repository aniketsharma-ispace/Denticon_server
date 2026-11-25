"""
Delta Dental of Rhode Island's part of the Sabrina Fill Form prefill.

smile_partners/sabrina/prefill.py does the common work and calls these.
Change DD RI here; other carriers have their own carriers/<carrier>/prefill.py.
"""

# DD RI's crawl looks up D2140 / D2331 rather than the sheet's D2160 / D2391,
# so those stand in for Basic.
_DDRI_WAITING_CODES = (
    ("Basic", ("D2160", "D2391", "D2140", "D2331")),
    ("Major", ("D2740",)),
)


def waiting_periods(view: dict) -> list[dict]:
    """DD RI states a waiting period per code ('6 Months'); one row each for Basic and Major."""
    from ...prefill import _waiting_period

    stated = ((view or {}).get("_ddri_meta") or {}).get("waiting_codes") or {}
    rows = []
    for applies_to, codes in _DDRI_WAITING_CODES:
        for code in codes:
            found = _waiting_period(stated.get(code))
            if found:
                rows.append({"applies_to": applies_to, "period": found[0], "unit": found[1],
                             "source": code})
                break
    return rows
