"""
Deciding whether two values agree.

One function per kind of value, each returning True, False, or None where the
two cannot be compared at all. A blank is never silently treated as agreement
unless the other side positively states there is no limit.
"""

from __future__ import annotations

import re
from .vocabulary import (
    _MASK_RE,
    _addr_tokens,
    _carrier_brand,
    _frequency_note,
    _history_dates,
    _norm_id,
    _norm_name,
    _norm_network,
    _norm_text,
    _num_agelimit,
    _num_cob,
    _num_date,
    _num_frequency,
    _num_money,
    _num_month,
    _num_pct,
    _num_yesno,
    _visible_part,
)


# ══════════════════════════════════════════════════════════════════════════════
#  COMPARISON
# ══════════════════════════════════════════════════════════════════════════════

_MONEY_TOLERANCE = 0.01   # cents — "$2000" vs "$2,000.00"


_PCT_TOLERANCE = 0.01


_ADDR_OVERLAP = 0.7       # share of the smaller token set that must match


def _compare(kind: str, sab, por, ctx: dict | None = None) -> tuple[bool | None, str]:
    """
    Compare one field.

    Returns (equal, note). `equal is None` means "not comparable" — either side
    was blank, or the values are stated in a form we can't reduce to a common
    unit. Not-comparable never counts as a mismatch.
    """
    if kind == "money":
        a, b = _num_money(sab), _num_money(por)
        if a is None or b is None:
            return None, ""
        return abs(a - b) <= _MONEY_TOLERANCE, ""

    if kind == "pct":
        a, b = _num_pct(sab), _num_pct(por)
        if a is None or b is None:
            return None, ""
        return abs(a - b) <= _PCT_TOLERANCE, ""

    if kind == "yesno":
        a, b = _num_yesno(sab), _num_yesno(por)
        if a is None or b is None:
            return None, ""
        return a == b, ""

    if kind == "date":
        a, b = _num_date(sab), _num_date(por)
        if a is None or b is None:
            return None, ""
        return a == b, ""

    if kind == "month":
        a, b = _num_month(sab), _num_month(por)
        if a is None or b is None:
            return None, ""
        return a == b, ""

    if kind == "frequency":
        age = (ctx or {}).get("age")
        a, b = _num_frequency(sab, age), _num_frequency(por, age)
        if a is None or b is None:
            return None, ""
        note = _frequency_note(por, age) or _frequency_note(sab, age)
        if a == b:
            return True, note
        # "1X60Months" and "1X5Years" are the same limit stated two ways; the
        # canonical form already reconciles those, so a difference here is real.
        return False, note

    if kind == "cob":
        a, b = _num_cob(sab), _num_cob(por)
        if a is None or b is None:
            return None, "coordination method not recognized on one side"
        if a[0] == b[0]:
            same_words = _norm_text(sab) == _norm_text(por)
            return True, "" if same_words else f"both state {a[1]}, worded differently"
        return False, f"{a[1]} on the sheet, {b[1]} on the portal"

    if kind == "agelimit":
        a, b = _num_agelimit(sab), _num_agelimit(por)
        if a is None or b is None:
            return None, ""
        if a == b:
            return True, ""
        # 99 and above is "no real cap" on both sides.
        if a >= 99 and b >= 99:
            return True, "both state no effective age cap"
        return False, ""

    if kind == "history":
        a, b = _history_dates(sab), _history_dates(por)
        if a is None or b is None:
            return None, ""
        if a == b:
            return True, ""
        if not a:
            return False, "Sabrina shows no history but the portal has a service date"
        if not b:
            return False, "portal shows no history but Sabrina has a service date"
        if a & b:
            # Both describe the same treatment; one simply lists more of it.
            missing = sorted(b - a) or sorted(a - b)
            return True, f"service dates overlap; also on one side: {', '.join(missing)}"
        return False, ""

    if kind == "id":
        a, b = _norm_id(sab), _norm_id(por)
        if a is None or b is None:
            return None, ""
        if a == b:
            return True, ""

        # Portals routinely mask identifiers ("XXXXXXX6200"). Such a value can
        # never equal the real one, so comparing it literally manufactures a
        # mismatch on every patient. Compare only what the mask actually shows.
        for masked, plain, who in ((b, a, "portal"), (a, b, "Sabrina")):
            if not _MASK_RE.search(masked):
                continue
            visible = _visible_part(masked)
            if visible is None:
                return None, f"{who} value is fully masked — not comparable"
            side, text = visible
            agrees = plain.endswith(text) if side == "suffix" else plain.startswith(text)
            return agrees, (
                f"{who} value is masked; the {len(text)} visible characters agree"
                if agrees else
                f"{who} value is masked and its visible characters differ"
            )

        # Group numbers/payor IDs are often padded or suffixed by one system.
        da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
        if da and db and da.lstrip("0") == db.lstrip("0"):
            return True, "digits match; formatting differs"
        return False, ""

    if kind == "network":
        a, b = _norm_network(sab), _norm_network(por)
        if a is None or b is None:
            return None, ""
        return a == b, ""

    if kind == "carrier":
        # Same insurer is the same value, however each system decorates it.
        ba, bb = _carrier_brand(sab), _carrier_brand(por)
        if ba and bb:
            if ba == bb:
                same = _norm_text(sab) == _norm_text(por)
                return True, "" if same else "same carrier, stated differently"
            return False, f"different carriers ({ba} vs {bb})"
        # Neither side names a brand we know — fall back to plain text rules.
        return _compare("text", sab, por)

    if kind == "name":
        a, b = _norm_name(sab), _norm_name(por)
        if a is None or b is None:
            return None, ""
        if a == b:
            return True, ""
        # One system holding only first+last while the other adds a middle name
        # is a formatting difference, not a data conflict.
        sa, sb = set(a), set(b)
        if sa and sb and (sa <= sb or sb <= sa):
            return True, "name subset; one system stores an extra given name"
        return False, ""

    if kind == "address":
        a, b = _addr_tokens(sab), _addr_tokens(por)
        if a is None or b is None:
            return None, ""
        overlap = len(a & b) / min(len(a), len(b))
        if overlap >= _ADDR_OVERLAP:
            return True, "" if overlap == 1 else "same address, different formatting"
        return False, ""

    # plain text
    a, b = _norm_text(sab), _norm_text(por)
    if a is None or b is None:
        return None, ""
    if a == b:
        return True, ""
    # Carrier/group names get abbreviated ("DELTA DENTAL OF WI" vs "DELTA
    # DENTAL WISCONSIN") — treat containment as agreement.
    if a in b or b in a:
        return True, "one value is an abbreviation of the other"
    return False, ""
