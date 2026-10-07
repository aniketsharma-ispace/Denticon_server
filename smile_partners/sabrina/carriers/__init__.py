"""
One folder per insurance portal.

    aetna/  cigna/  delta_dental/  metlife/

Each folder holds the whole audit for its carrier:

    spec.py        what the sheet contains, field by field
    parser.py      reading the sheet out of the PDF
    vocabulary.py  making a stated value comparable
    compare.py     deciding whether two values agree
    portal.py      where each answer is found on the portal
    rules.py       the carrier's own rules
    audit.py       the audit itself

A folder is imported only when the uploaded portal export is that carrier's,
so a change made in one folder cannot alter another carrier's audit. They
began as identical copies, differing only in which carrier's rules each one
calls, and are expected to diverge.

An export from any other portal is refused rather than audited by the
nearest carrier's rules, which would give a confident wrong answer.
"""

from __future__ import annotations

from importlib import import_module


# Folder → how the carrier is named to the user.
CARRIERS = {
    "aetna":        "Aetna",
    "cigna":        "Cigna",
    "delta_dental": "Delta Dental",
    "metlife":      "MetLife",
}


# What a translated export records as its carrier, for a caller holding the
# translation rather than the upload.
_SOURCE_INSURER = {
    "aetna":        "aetna",
    "cigna":        "cigna",
    "delta dental": "delta_dental",
}


# The extension sometimes wraps the export in one of these.
_WRAPPERS = ("cigna_data", "aetna_data", "portal_data")


def _is_metlife(raw: dict) -> bool:
    """MetLife's export: its `metlife_data` block, or a crawl or carrier record naming MetLife."""
    if isinstance(raw.get("metlife_data"), dict):
        return True
    crawl = raw.get("benefit_coverage")
    if isinstance(crawl, dict) and str(crawl.get("source") or "").lower().startswith("metlife"):
        return True
    carrier = raw.get("carrier_information") or raw.get("carrier_info")
    return isinstance(carrier, dict) and "metlife" in str(carrier.get("name") or "").lower()


def _pdf_insurer(raw: dict) -> str:
    """The format /api/parse-pdf read a carrier PDF as ("delta_dental_mo", "guardian", …)."""
    summary = raw.get("summary")
    return str(summary.get("insurer") or "").strip() if isinstance(summary, dict) else ""


def detect_carrier(portal_raw) -> str | None:
    """
    The folder whose rules apply to this portal export, or None.

    Aetna, Cigna and Delta Dental are recognized by the same checks
    `breakdown._extract` uses, so the folder chosen here and the breakdown it
    reads always agree. MetLife's export needs no translation and is known by
    its own blocks. A Delta Dental plan PDF read by /api/parse-pdf is Delta
    Dental's too.
    """
    if not isinstance(portal_raw, dict):
        return None

    translated = _SOURCE_INSURER.get(str(portal_raw.get("_source_insurer") or "").strip().lower())
    if translated:
        return translated

    from ...portals.aetna import _is_aetna_portal
    from ...portals.cigna import _is_cigna_portal
    from ...portals.delta_dental import _is_dd_portal

    candidates = [portal_raw] + [portal_raw[key] for key in _WRAPPERS
                                 if isinstance(portal_raw.get(key), dict)]
    for candidate in candidates:
        if _is_aetna_portal(candidate):
            return "aetna"
        if _is_cigna_portal(candidate):
            return "cigna"
        if _is_dd_portal(candidate):
            return "delta_dental"

    if _is_metlife(portal_raw):
        return "metlife"
    if _pdf_insurer(portal_raw).lower().startswith("delta_dental"):
        return "delta_dental"
    return None


def carrier_rules(portal_raw):
    """
    (folder, module) for this export, importing the folder only now.

    Raises ValueError (→ HTTP 422) for an export from a portal that has no
    folder here.
    """
    key = detect_carrier(portal_raw)
    if key is None:
        seen = _pdf_insurer(portal_raw) if isinstance(portal_raw, dict) else ""
        raise ValueError(
            "The Sabrina audit has no rules for this portal export"
            + (f" (it reads as {seen})" if seen else "")
            + ". Supported portals: " + ", ".join(CARRIERS.values()) + ".")
    return key, import_module(f"{__name__}.{key}")
