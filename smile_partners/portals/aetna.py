"""
Aetna / ClaimConnect.

Recognizes the export, translates it into the shared contract, and applies the
corrections that only make sense for this carrier.
"""

# Aetna's page is read by the shared reader (shared/portals/aetna.py), the
# same one every client uses. Its names are re-exported here so existing
# imports (breakdown.py, sabrina/carriers) keep working unchanged. Only Smile
# Partners' own New Plan output rules live in this file.
import re

from .common import (_display_plan_type, _dollar, _effective_date_month,
                     _triple_individual_deductible, clean)
from shared.portals.aetna import (  # noqa: F401  (re-exported)
    _aetna_network_label,
    _AETNA_BUCKET_KEYS,
    _aetna_has_network_buckets,
    _AETNA_FREQ_PART_RE,
    _aetna_repair_service_row,
    _aetna_network_view,
    _is_aetna_portal,
    _aetna_plan_pct,
    _aetna_money_value,
    _aetna_money_used,
    _aetna_financial_record,
    _aetna_is_medicare_export,
    _AETNA_COVERAGE_WORDS,
    _aetna_repair_amount_row,
    _aetna_annual_maximum,
    _aetna_procedure_covered,
    _aetna_age_limit,
    _aetna_history,
    _aetna_dependent_age,
    _aetna_missing_tooth,
    _aetna_waiting_period,
    _aetna_shared_codes,
    _aetna_share_question,
    _aetna_has_alternate_benefit,
    _normalize_aetna_portal,
)


def _apply_aetna_output_rules(data, normalized):
    """Apply only Aetna-specific meanings after the shared extraction path."""
    meta = normalized.get('_aetna_meta') or {}
    remarks = meta.get('remarks') or []
    waiting_value, waiting_months, waiting_applies = _aetna_waiting_period(remarks)

    has_any_deductible = bool(
        meta.get('individual_deductible_present')
        or meta.get('family_deductible_present')
        or meta.get('has_positive_deductible')
    )

    if has_any_deductible:
        individual_ded = data.get('indiv_ded') or '-'
        individual_paid = data.get('indiv_ded_paid') or '-'
        family_ded = (
            data.get('family_ded')
            if meta.get('family_deductible_present')
            else _triple_individual_deductible(individual_ded)
        )
        family_paid = (
            data.get('family_ded_paid')
            if meta.get('family_deductible_present') else '-'
        )
        ded_prev = ded_diag = '-'
    else:
        individual_ded = individual_paid = '0.00'
        family_ded = family_paid = '0.00'
        ded_prev = ded_diag = 'No'

    plan_begin_month = _effective_date_month(meta.get('plan_begin'))
    data.update({
        'source_insurer': 'aetna',
        # These are modal-editable defaults. They reflect the selected
        # in-network Aetna portal context until an operator overrides them.
        'ins_name': '(IN) Aetna',
        # Medicare: the claim address the page states. Every other plan (and
        # an older export that did not capture it): Aetna's usual address.
        'ins_address': meta.get('claim_address') or 'PO Box 14094, Lexington, KY 40512',
        'ins_phone': '8004517715',
        'payor_id': '60054',
        'fee_schedule': meta.get('network_type') or '-',
        'network_status': 'IN',
        'ssn': data.get('member_id') or '-',
        'elig_notes': 'ins: aetna, benefits verified online',
        'plan_type': _display_plan_type(data.get('plan_type')),
        'term_date': '-',
        'plan_year_start': plan_begin_month or _effective_date_month(data.get('eff_date')) or '-',
        'yearly_max': data.get('yearly_max') if meta.get('annual_max_present') else '0.00',
        'yearly_rem': data.get('yearly_rem') if meta.get('annual_max_present') else '0.00',
        'indiv_ded': individual_ded,
        'indiv_ded_paid': individual_paid,
        'family_ded': family_ded,
        'family_ded_paid': family_paid,
        'ded_prev': ded_prev,
        'ded_diag': ded_diag,
        'waiting_period': waiting_value,
        'waiting_period_mo': waiting_months,
        'applies_to': waiting_applies,
        'major_on_prep': 'No',
        'or_seat': 'Yes',
        'missing_tooth': _aetna_missing_tooth(remarks),
        'pre_auth': '350',
        'dep_age_limit': meta.get('dependent_age') or 'NAL',
        'ortho_ded': _dollar(meta.get('ortho_ded_total'), default='0.00'),
        'ortho_ded_paid': _dollar(meta.get('ortho_ded_used'), default='0.00'),
        'ortho_max': data.get('ortho_max') if meta.get('ortho_max_present') else '0.00',
        'ortho_max_paid': data.get('ortho_max_paid') if meta.get('ortho_max_present') else '0.00',
        'ortho_payment_frequency': '-',
        'd4341_number_of_quads': '-',
    })

    procs = data.get('procs') or {}
    data['d0120_d0150_share_d0140'] = _aetna_share_question(
        procs,
        source_codes=('D0120', 'D0150'),
        target_codes=('D0140',),
    )
    data['d4910_d1110_share_freq'] = _aetna_share_question(
        procs,
        source_codes=('D4910',),
        target_codes=('D1110',),
    )

    # Aetna business rule: keep the permanent-molars question blank.  Do not
    # infer it from tooth ranges, age limits, or frequency wording.
    data['molars_only_sealants'] = ''

    # Posterior composite/amalgam answer is Yes when either D2140 or D2331
    # explicitly carries the alternate-benefit phrase.
    d2140 = procs.get('D2140') or {}
    d2331 = procs.get('D2331') or {}
    if d2140 or d2331:
        data['posterior_composite_downgrade'] = (
            'Yes'
            if _aetna_has_alternate_benefit(d2140) or _aetna_has_alternate_benefit(d2331)
            else 'No'
        )
    else:
        data['posterior_composite_downgrade'] = '-'

    # Posterior crown answer is controlled only by D2740's explicit
    # alternate-benefit phrase.
    d2740 = procs.get('D2740') or {}
    data['porcelain_posterior_downgrade'] = (
        'Yes' if _aetna_has_alternate_benefit(d2740) else ('No' if d2740 else '-')
    )

    d2950 = procs.get('D2950') or {}
    d2740 = procs.get('D2740') or {}
    d2950_covered = d2950.get('_aetna_covered')
    d2740_covered = d2740.get('_aetna_covered')
    if d2950_covered is False:
        data['d2950_same_day_crown'] = 'No'
    elif d2950_covered is True and d2740_covered is True:
        data['d2950_same_day_crown'] = 'Yes'
    elif d2950_covered is True and d2740_covered is False:
        data['d2950_same_day_crown'] = 'No'
    else:
        data['d2950_same_day_crown'] = '-'

    # The template historically grouped D1206 and D1208 into one fluoride
    # row. Do not claim a result for an unqueried code. Select the available
    # Aetna row and let the table label name only the code(s) actually present.
    d1206 = procs.get('D1206') or {}
    d1208 = procs.get('D1208') or {}
    fluoride = None
    if d1206.get('_aetna_covered') is True:
        fluoride = d1206
    elif d1208.get('_aetna_covered') is True:
        fluoride = d1208
    elif d1206:
        fluoride = d1206
    elif d1208:
        fluoride = d1208
    if fluoride:
        procs['_AETNA_FLUORIDE_DISPLAY'] = fluoride

    ortho_age = ''
    for code in ('D8010', 'D8080', 'D8090'):
        proc = procs.get(code) or {}
        if proc.get('_aetna_covered') is not True:
            continue
        raw_age = str(proc.get('age_limit') or '').strip()
        if raw_age.lower() in ('', '-', '—', 'n/a', 'na', 'none', '99', '999'):
            proc['age_limit'] = ''
            continue
        ortho_age = raw_age
        break
    data['ortho_age_limit_llm'] = ortho_age

    if data.get('chair_provider') in ('', '—'):
        data['chair_provider'] = '-'
    return data
