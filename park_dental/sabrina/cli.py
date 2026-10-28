"""
Command line, for tuning the parser against a real sheet.
"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from shared.pdf_extractor import _extract_text
from .carriers import CARRIERS, carrier_rules


# ══════════════════════════════════════════════════════════════════════════════
#  CLI — tune the parser against a real Sabrina PDF
#
#    python sabrina_compare.py breakdown.pdf                 → what was parsed
#    python sabrina_compare.py breakdown.pdf portal.json     → full comparison
#    python sabrina_compare.py breakdown.pdf --text          → raw PDF text
#
#  With a portal export, the sheet is read and audited by that carrier's
#  folder, exactly as the server does; without one, by `sheet/`.
# ══════════════════════════════════════════════════════════════════════════════

def _cli() -> int:
    # Windows consoles default to cp1252, which cannot encode the box-drawing
    # characters below; force UTF-8 so the dump never dies on its own output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if not args:
        print(__doc__)
        print("usage: python sabrina_compare.py <sabrina.pdf> [portal.json] [--text]")
        return 2

    with open(args[0], "rb") as fh:
        pdf_bytes = fh.read()

    if "--text" in flags:
        print(_extract_text(pdf_bytes))
        return 0

    portal_raw = None
    folder = f"{__package__}.sheet"
    if len(args) > 1:
        with open(args[1], "r", encoding="utf-8") as fh:
            portal_raw = json.load(fh)
        key, rules = carrier_rules(portal_raw)
        folder = rules.__name__
        print(f"\nPortal export is {CARRIERS[key]}'s → read and audited by carriers/{key}/")

    parser = import_module(f"{folder}.parser")
    spec = import_module(f"{folder}.spec")
    vocabulary = import_module(f"{folder}.vocabulary")

    parsed = parser.parse_sabrina_pdf(pdf_bytes)

    print(f"\nSabrina markers matched : {parsed['marker_count']}/{len(parser._MARKERS)}"
          f"  → detected as Sabrina: {parsed['marker_count'] >= parser._MIN_MARKERS}")
    print(f"Lines of text           : {parsed['line_count']}\n")

    found = {k: v for k, v in parsed["fields"].items() if not vocabulary._blank(v)}
    print(f"── PARSED {len(found)}/{len(spec._SPEC)} FIELDS ─────────────────────────")
    for field in spec._SPEC:
        val = parsed["fields"].get(field["key"])
        mark = "  " if not vocabulary._blank(val) else "??"
        print(f"{mark} {field['label'][:44]:<46} {'' if vocabulary._blank(val) else val}")

    if parsed["labels_not_found"]:
        print(f"\n── LABELS NOT ON THE SHEET ({len(parsed['labels_not_found'])}) ──")
        print("   " + "\n   ".join(parsed["labels_not_found"]))

    if portal_raw is not None:
        result = import_module(f"{folder}.audit").compare_sabrina_to_portal(parsed, portal_raw)
        s = result["summary"]
        print(f"\n── COMPARISON ────────────────────────────────────────────")
        print(f"   compared {s['compared']}   matches {s['matches']}   "
              f"MISMATCHES {s['mismatches']} ({s['critical_mismatches']} critical)   "
              f"portal-silent {s['not_in_portal']}")
        for r in result["mismatches"]:
            flag = "!!" if r["critical"] else "  "
            print(f"{flag} {r['label'][:38]:<40} sabrina={r['sabrina']!r:<22} portal={r['portal']!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
