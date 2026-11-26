"""
MetLife's part of Star Dental's Sabrina Fill Form prefill.

sabrina/star_dental/prefill.py does the common work and calls these.
Change MetLife here; other carriers have their own carriers/<carrier>/prefill.py,
and Smile Partners has its own copy of this folder.
"""

# D0120 Preventative / D2160 Basic / D2740 Major %: on Star's Fill Form (Sabrina
# builds the plan name from them) but not in Star's audit list, so read here
# and filled only, never audited. Read from the plan's class percentages, as Smile Partners' spec reads them.
FORM_ONLY_SPEC = [
    {"key": "pct_prev",  "label": "D0120 Preventative", "kind": "pct", "section": "Plan Provisions",
     "portal": 'pct_prev'},
    {"key": "pct_basic", "label": "D2160 Basic",        "kind": "pct", "section": "Plan Provisions",
     "portal": 'pct_basic'},
    {"key": "pct_major", "label": "D2740 Major",        "kind": "pct", "section": "Plan Provisions",
     "portal": 'pct_major'},
]
