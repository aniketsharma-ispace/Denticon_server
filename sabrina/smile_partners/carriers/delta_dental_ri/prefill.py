"""
Delta Dental of Rhode Island's part of the Sabrina Fill Form prefill.

sabrina/smile_partners/prefill.py does the common work (through portal.py's
_portal_value, the same resolver the audit uses) and calls these for what only
DD RI's export can answer. Other carriers have their own carriers/<carrier>/prefill.py.
"""

# The codes each Fill Form waiting-period row is read from, first stated wins.
# D2140 / D2331 stand in for Basic when the crawl did not look up D2160 / D2391.
_DDRI_WAITING_CODES = (
    ("Basic", ("D2160", "D2391", "D2140", "D2331")),
    ("Major", ("D2740",)),
)


def waiting_periods(view: dict) -> list[dict]:
    """DD RI states a waiting period per code ('6 Months'); one row each for Basic and Major."""
    from ...prefill import _waiting_period
    from .portal import _procedure

    rows = []
    for applies_to, codes in _DDRI_WAITING_CODES:
        for code in codes:
            found = _waiting_period((_procedure(view or {}, code) or {}).get("waiting_period"))
            if found:
                rows.append({"applies_to": applies_to, "period": found[0], "unit": found[1],
                             "source": code})
                break
    return rows
