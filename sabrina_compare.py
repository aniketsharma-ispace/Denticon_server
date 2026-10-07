"""
Kept so that `import sabrina_compare` keeps working.

The audit lives in `smile_partners/sabrina/`, one folder per insurance portal
under `carriers/`. Every name this module used to define is still here:

  * `compare_sabrina_to_portal` and `audit_sabrina_pdf` run the folder of the
    carrier whose export they are given, exactly as the server does, and
    refuse an export from any other portal;
  * the `_portal_*` readers, which take an export too, also run that
    carrier's folder — falling back to MetLife's, the export already in the
    shared shape, when handed a fragment no folder recognizes;
  * Cigna's own rules come from `carriers/cigna/rules.py`;
  * everything else — reading the sheet, the vocabulary, comparing two values
    — comes from `carriers/metlife/`. The folders are identical there today;
    import `smile_partners.sabrina.carriers.<carrier>.<module>` to test
    another carrier's copy.
"""

# flake8: noqa: F401

from importlib import import_module

from smile_partners.sabrina import audit_sabrina_pdf, compare_sabrina_to_portal
from smile_partners.sabrina.carriers import detect_carrier
from smile_partners.sabrina.carriers.metlife.common import (
    _BLANKS,
    _DEBUG,
    _UNLIMITED_MAX,
    log,
)
from smile_partners.sabrina.carriers.metlife.spec import (
    CORE_FIELD_KEYS,
    _AGE_LIMIT_CODES,
    _ASPECT_SECTION,
    _BENEFIT_ASPECTS,
    _CRITICAL_KEYS,
    _HISTORY_CODES,
    _NO_FREQUENCY_CODES,
    _SPEC,
    _aspect_applies,
    _build_aspect_spec,
    core_fields,
)
from smile_partners.sabrina.carriers.metlife.vocabulary import (
    _CARRIER_BRANDS,
    _COB_METHODS,
    _DATE_FORMATS,
    _FREQ_CLAUSE_SPLIT,
    _FREQ_COMPACT_RE,
    _FREQ_NOT_COVERED,
    _FREQ_NO_LIMIT_WORDS,
    _FREQ_PREDETERMINATION,
    _FREQ_PROSE_RE,
    _FREQ_UNLIMITED,
    _FREQ_WORD_COUNTS,
    _HISTORY_DASHES,
    _HISTORY_NONE,
    _MASK_RE,
    _MONTHS,
    _NAME_SUFFIXES,
    _NO,
    _YES,
    _addr_tokens,
    _agelimit_lower,
    _blank,
    _blank_for,
    _blank_means_no_limit,
    _carrier_brand,
    _clause_age_range,
    _coalesce_keys,
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
    _num_history,
    _num_money,
    _num_month,
    _num_pct,
    _num_yesno,
    _parse_single_frequency,
    _select_frequency_clause,
    _visible_part,
)
from smile_partners.sabrina.carriers.metlife.parser import (
    _ALL_LABELS,
    _BOILERPLATE_RE,
    _FREQ_RE,
    _LABELS_BY_FIRST,
    _MARKERS,
    _MIN_MARKERS,
    _NON_VALUES,
    _OTHER_SHEET_LABELS,
    _SEP_RE,
    _STOP_LABELS,
    _TRIM,
    _anchor_line,
    _any_label_at,
    _capture_benefit_rows,
    _classify_row_cells,
    _find_value,
    _label_span,
    _looks_like_value,
    _norm_label,
    _pick_cell,
    _refine_inline,
    _reflow_wrapped,
    _split_lines,
    is_sabrina_pdf,
    parse_sabrina_pdf,
    parse_sabrina_text,
    sabrina_marker_count,
)
from smile_partners.sabrina.carriers.metlife.compare import (
    _ADDR_OVERLAP,
    _MONEY_TOLERANCE,
    _PCT_TOLERANCE,
    _compare,
)
from smile_partners.sabrina.carriers.cigna.rules import (
    _CIGNA_BLANK_WHEN_NOT_COVERED,
    _CIGNA_FL_CODES,
    _cigna_annual_max_classes,
    _cigna_code_override,
    _cigna_export,
    _cigna_fl_row,
    _cigna_oon_benefits,
    _cigna_ortho_deductible,
    _cigna_preventive_pct,
    _cigna_procedure_not_covered,
)
from smile_partners.sabrina.carriers.metlife.portal import (
    _DERIVED as _METLIFE_DERIVED,
    _network_pays,
    _pct_from_procs,
    _procfield_from_procs,
)
from smile_partners.sabrina.carriers.metlife.audit import (
    STATUS_MATCH,
    STATUS_MISMATCH,
    STATUS_MISSING_IN_SABRINA,
    STATUS_NOT_COMPARABLE,
    STATUS_NOT_IN_PORTAL,
    STATUS_NOT_STATED,
    _age_from_dob,
)
from smile_partners.sabrina.cli import (
    _cli,
)


def _on_portal(name: str, at: int):
    """`name` from `portal.py` of the folder whose export is positional argument `at`."""
    def run(*args, **kwargs):
        portal_raw = args[at] if len(args) > at else kwargs.get("portal_raw")
        folder = detect_carrier(portal_raw) or "metlife"
        portal = import_module(f"smile_partners.sabrina.carriers.{folder}.portal")
        return getattr(portal, name)(*args, **kwargs)
    run.__name__ = name
    return run


_portal_breakdown = _on_portal("_portal_breakdown", 0)
_portal_normalized = _on_portal("_portal_normalized", 0)
_network_coverage = _on_portal("_network_coverage", 0)
_ortho_is_covered = _on_portal("_ortho_is_covered", 0)
_lifetime_belongs_elsewhere = _on_portal("_lifetime_belongs_elsewhere", 0)
_portal_value = _on_portal("_portal_value", 2)

_portal_cob = _on_portal("_portal_cob", 1)
_portal_d4341_quads = _on_portal("_portal_d4341_quads", 1)
_portal_eff_date = _on_portal("_portal_eff_date", 1)
_portal_in_network = _on_portal("_portal_in_network", 1)
_portal_major_paid_on = _on_portal("_portal_major_paid_on", 1)
_portal_oon_benefits = _on_portal("_portal_oon_benefits", 1)
_portal_ortho_age = _on_portal("_portal_ortho_age", 1)
_portal_ortho_ded = _on_portal("_portal_ortho_ded", 1)
_portal_ortho_ded_met = _on_portal("_portal_ortho_ded_met", 1)
_portal_ortho_max = _on_portal("_portal_ortho_max", 1)
_portal_ortho_used = _on_portal("_portal_ortho_used", 1)
_portal_perio_after_srp = _on_portal("_portal_perio_after_srp", 1)
_portal_prev_in_max = _on_portal("_portal_prev_in_max", 1)
_portal_yearly_max_paid = _on_portal("_portal_yearly_max_paid", 1)

_DERIVED = {key: globals()[fn.__name__] for key, fn in _METLIFE_DERIVED.items()}
