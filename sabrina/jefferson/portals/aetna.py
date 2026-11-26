"""
Aetna / ClaimConnect.

Recognizes the export, translates it into the shared contract, and applies the
corrections that only make sense for this carrier.
"""

import re

from .common import (_display_plan_type, _dollar, _effective_date_month,
                     _triple_individual_deductible, clean)


def _aetna_network_label(value):
    """Return a readable ClaimConnect network/fee-schedule label."""
    raw = clean(value)
    if not raw or raw.upper() in ('N/A', 'NA', 'NONE'):
        return ''
    return re.sub(r'\s*,\s*', ', ', raw)


# The extension splits every benefit table by network:
#   raw["in_network"]     = In Network tables + In and Out of Network tables
#   raw["out_of_network"] = Out of Network tables + In and Out of Network tables
# each holding maximums / deductibles / co_insurance / service_level_benefits.
# Older exports had those four lists flat at the top level, with every
# network mixed together.
_AETNA_BUCKET_KEYS = ('maximums', 'deductibles', 'co_insurance', 'service_level_benefits')


def _aetna_has_network_buckets(raw):
    """True for an export from the extension that splits tables by network."""
    return (
        isinstance(raw, dict)
        and isinstance(raw.get('in_network'), dict)
        and isinstance(raw.get('out_of_network'), dict)
    )


def _aetna_network_view(raw, network='in'):
    """
    The export with one network's tables at the top level.

    Everything below reads the four flat lists, so this lifts the chosen
    bucket up to where they expect it. `network` is "in" or "out"; anything
    else reads as "in". An old flat export passes through unchanged.
    """
    if not _aetna_has_network_buckets(raw):
        return raw
    network = 'out' if str(network or '').strip().lower() == 'out' else 'in'
    bucket = raw['out_of_network'] if network == 'out' else raw['in_network']
    view = dict(raw)
    for key in _AETNA_BUCKET_KEYS:
        view[key] = list(bucket.get(key) or [])
    view['_aetna_network'] = network
    return view


def _is_aetna_portal(raw):
    """Recognize the ClaimConnect/Aetna payload without affecting other carriers."""
    if not isinstance(raw, dict):
        return False

    source = str(raw.get('source') or '').lower()
    payer = raw.get('payer') if isinstance(raw.get('payer'), dict) else {}
    coverage = (
        raw.get('coverage_details')
        if isinstance(raw.get('coverage_details'), dict)
        else {}
    )
    payer_name = ' '.join(
        str(value or '')
        for value in (
            payer.get('name'),
            coverage.get('payer'),
        )
    ).lower()

    return (
        'aetna' in payer_name
        or ('claimconnect' in source and _aetna_has_network_buckets(raw))
        or (
            'claimconnect' in source
            and isinstance(raw.get('service_level_benefits'), list)
            and isinstance(raw.get('co_insurance'), list)
            and isinstance(raw.get('maximums'), list)
        )
    )


def _aetna_plan_pct(value):
    """Convert ClaimConnect's patient/plan split into the plan-paid percentage."""
    values = re.findall(r'(\d+(?:\.\d+)?)\s*%', str(value or ''))
    if not values:
        return ''
    paid = values[1] if len(values) > 1 else values[0]
    try:
        return f'{float(paid):g}%'
    except ValueError:
        return f'{paid}%'


def _aetna_money_value(value):
    match = re.search(r'([\d,]+(?:\.\d+)?)', str(value or ''))
    if not match:
        return None
    try:
        return float(match.group(1).replace(',', ''))
    except ValueError:
        return None


def _aetna_money_used(total, remaining):
    """Return total minus remaining, preserving unknown values as blank."""
    total_value = _aetna_money_value(total)
    remaining_value = _aetna_money_value(remaining)
    if total_value is None or remaining_value is None:
        return ''
    return f'{max(0.0, total_value - remaining_value):,.2f}'


def _aetna_financial_record(records, type_hint='', coverage=''):
    """Select an Aetna maximum/deductible row by type and coverage."""
    candidates = [item for item in (records or []) if isinstance(item, dict)]
    if type_hint:
        candidates = [
            item for item in candidates
            if type_hint.lower() in str(item.get('type') or '').lower()
        ]
    if coverage:
        candidates = [
            item for item in candidates
            if coverage.lower() in str(item.get('coverage') or '').lower()
        ]
    return candidates[0] if candidates else {}


def _aetna_procedure_covered(item):
    """Resolve Aetna coverage only from the explicit ClaimConnect row."""
    if not isinstance(item, dict):
        return None
    text = ' '.join(
        str(item.get(key) or '')
        for key in ('message', 'frequency', 'percentage_copay')
    )
    if re.search(r'\bnot\s+covered\b', text, re.IGNORECASE):
        return False
    if _aetna_plan_pct(item.get('percentage_copay')):
        return True
    return None


def _aetna_age_limit(value):
    raw = clean(value)
    if raw.upper() in ('', 'N/A', 'NA', 'NONE'):
        return ''
    match = re.search(r'(?:maximum\s+age|under)\s*:?\s*(\d+)', raw, re.IGNORECASE)
    return match.group(1) if match else raw


def _aetna_history(value, covered):
    """Extract paid service dates; a covered row without a paid date is NH."""
    if covered is not True:
        return ''
    raw = clean(value)
    dates = re.findall(
        r'(?:last\s+paid\s+date\s*:\s*)?(\d{2}/\d{2}/(?:\d{2}|\d{4}))',
        raw,
        re.IGNORECASE,
    )
    if dates:
        return '\n'.join(dict.fromkeys(dates))
    if raw.upper() in ('', 'N/A', 'NA', 'NONE') or 'remaining' in raw.lower():
        return 'NH'
    if 'no history' in raw.lower():
        return 'NH'
    return raw


def _aetna_dependent_age(remarks):
    """Return the greater child/student dependent-age limit from Aetna remarks.

    ClaimConnect may return two limits in one sentence, for example
    ``CHLD TO 19 OR 25 IF FT STUDENT``.  The business PDF keeps the greater
    supported age so the child/student continuation limit is not lost.
    """
    text = ' '.join(str(value or '') for value in (remarks or []))
    candidates = []

    # Read every age from clauses that explicitly discuss a child, dependent,
    # or student.  Restrict to one/two-digit values so plan years are ignored.
    for clause in re.split(r'[,;]', text):
        if not re.search(r'\b(?:CHLD|CHILD(?:REN)?|DEPENDENT|STUDENT)\b', clause, re.IGNORECASE):
            continue
        for value in re.findall(r'(?<!\d)(\d{1,2})(?!\d)', clause):
            age = int(value)
            if 0 < age < 99:
                candidates.append(age)

    # Fallback for uncommon formatting where the relevant text is not cleanly
    # comma/semicolon separated.
    if not candidates:
        for pattern in (
            r'\bCHLD\s+TO\s+(\d{1,2})',
            r'\bCHILD(?:REN)?\s+(?:TO|THROUGH|UNTIL)\s+(\d{1,2})',
            r'\bDEPENDENT\s+AGE\s+(?:LIMIT\s*)?:?\s*(\d{1,2})',
            r'\b(?:FT\s+)?STUDENT(?:\s+TO|\s+THROUGH|\s+UNTIL|\s+AGE)?\s*:?[ ]*(\d{1,2})',
            r'\b(\d{1,2})\s+IF\s+(?:FT|FULL[- ]?TIME)\s+STUDENT',
        ):
            candidates.extend(
                int(match)
                for match in re.findall(pattern, text, re.IGNORECASE)
                if 0 < int(match) < 99
            )

    return str(max(candidates)) if candidates else ''


def _aetna_missing_tooth(remarks):
    text = ' '.join(str(value or '') for value in (remarks or [])).lower()
    if 'missing tooth clause does not apply' in text:
        return 'No'
    if 'missing tooth clause applies' in text:
        return 'Yes'
    return '-'


def _aetna_waiting_period(remarks):
    text = ' '.join(str(value or '') for value in (remarks or []))
    lower = text.lower()
    if 'no waiting period' in lower:
        return 'No', '0', '-'
    months = re.findall(r'(\d+)\s*months?', lower)
    if not months or 'waiting' not in lower:
        return 'No', '0', ''
    categories = []
    for needle, label in (
        ('prevent', 'Preventive'),
        ('diagnostic', 'Diagnostic'),
        ('basic', 'Basic'),
        ('major', 'Major'),
        ('ortho', 'Orthodontic'),
    ):
        if needle in lower:
            categories.append(label)
    return 'Yes', months[-1], ' & '.join(categories) or '-'


def _aetna_shared_codes(proc):
    """Return only ADA codes explicitly listed in an Aetna share-frequency field."""
    return {
        token.upper()
        for token in re.findall(
            r'D\d{4}',
            str((proc or {}).get('_aetna_shares_frequency_with') or ''),
            re.IGNORECASE,
        )
    }


def _aetna_share_question(procs, source_codes, target_codes):
    """Answer an Aetna sharing question from ``shares_frequency_with`` only.

    The relationship is accepted in either direction because ClaimConnect may
    list the companion code on only one of the returned rows.  Equal frequency
    text by itself is intentionally not treated as proof of a shared counter.
    """
    sources = tuple(str(code).upper() for code in source_codes)
    targets = tuple(str(code).upper() for code in target_codes)

    source_rows = [((procs or {}).get(code) or {}) for code in sources]
    target_rows = [((procs or {}).get(code) or {}) for code in targets]

    # Preserve the prior unknown result when required rows are absent or not
    # covered; otherwise decide Yes/No exclusively from the explicit column.
    if not source_rows or not target_rows:
        return '-'
    if any(row.get('_aetna_covered') is not True for row in source_rows + target_rows):
        return '-'

    target_set = set(targets)
    source_set = set(sources)
    if any(_aetna_shared_codes(row) & target_set for row in source_rows):
        return 'Yes'
    if any(_aetna_shared_codes(row) & source_set for row in target_rows):
        return 'Yes'
    return 'No'


def _aetna_has_alternate_benefit(proc):
    text = ' '.join(
        str((proc or {}).get(key) or '')
        for key in (
            'frequency_limit', 'description', '_aetna_message',
            '_aetna_shares_frequency_with',
        )
    )
    return bool(re.search(r'alternate\s+benefits?\s+may\s+apply', text, re.IGNORECASE))


def _normalize_aetna_portal(raw):
    """Translate the ClaimConnect payload into the existing Portal contract."""
    # Read one network's tables. In network unless the caller already picked
    # (the Sabrina audit picks from the sheet's In Network field).
    raw = _aetna_network_view(raw, raw.get('_aetna_network') or 'in')
    patient = raw.get('patient') if isinstance(raw.get('patient'), dict) else {}
    selected = (
        raw.get('selected_member')
        if isinstance(raw.get('selected_member'), dict)
        else {}
    )
    patient_info = (
        raw.get('patient_information')
        if isinstance(raw.get('patient_information'), dict)
        else {}
    )
    subscriber = (
        raw.get('subscriber')
        if isinstance(raw.get('subscriber'), dict)
        else {}
    )
    payer = raw.get('payer') if isinstance(raw.get('payer'), dict) else {}
    coverage = (
        raw.get('coverage_details')
        if isinstance(raw.get('coverage_details'), dict)
        else {}
    )
    dates = raw.get('dates') if isinstance(raw.get('dates'), dict) else {}
    remarks = raw.get('plan_level_remarks') or []
    maximums = raw.get('maximums') or []
    deductibles = raw.get('deductibles') or []

    patient_name = (
        selected.get('name')
        or patient_info.get('name')
        or patient.get('name')
        or ''
    )
    patient_dob = (
        selected.get('date_of_birth')
        or patient_info.get('date_of_birth')
        or patient.get('date_of_birth')
        or ''
    )
    relationship = (
        selected.get('relationship')
        or patient_info.get('relationship')
        or patient.get('relationship')
        or ''
    )
    if not relationship:
        for member in raw.get('eligibility_members') or []:
            if not isinstance(member, dict):
                continue
            if clean(member.get('name')).lower() == clean(patient_name).lower():
                relationship = member.get('relationship') or ''
                break
    if not relationship and clean(patient_name).lower() == clean(subscriber.get('name')).lower():
        relationship = 'Self'

    member_id = (
        patient.get('member_id_or_ssn')
        or patient_info.get('member_id_or_ssn')
        or subscriber.get('member_id_or_ssn')
        or ''
    )

    subscriber_name = subscriber.get('name') or ''
    subscriber_dob = ''
    if subscriber_name and clean(subscriber_name).lower() == clean(patient_name).lower():
        subscriber_dob = patient_dob
    else:
        for member in raw.get('eligibility_members') or []:
            if not isinstance(member, dict):
                continue
            if (
                clean(member.get('name')).lower() == clean(subscriber_name).lower()
                or str(member.get('relationship') or '').lower() in ('self', 'subscriber')
            ):
                subscriber_dob = member.get('date_of_birth') or ''
                if subscriber_dob:
                    break

    annual = _aetna_financial_record(maximums, 'dental', 'individual')
    ortho_max = _aetna_financial_record(maximums, 'ortho', 'individual')
    individual_ded = _aetna_financial_record(deductibles, '', 'individual')
    family_ded = _aetna_financial_record(deductibles, '', 'family')
    ortho_ded = _aetna_financial_record(deductibles, 'ortho', 'individual')

    has_positive_deductible = any(
        (_aetna_money_value(item.get('amount')) or 0) > 0
        for item in deductibles
        if isinstance(item, dict)
    )

    normalized_procs = []
    for item in raw.get('service_level_benefits') or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get('procedure_code') or '').upper().strip()
        if not code:
            continue
        covered = _aetna_procedure_covered(item)
        frequency = clean(item.get('frequency'))
        normalized_frequency = frequency.upper()
        if re.search(r'\b999\s+CALENDAR\s+YEARS?\b', frequency, re.IGNORECASE):
            frequency = 'NO FREQUENCY'
        elif covered is True and normalized_frequency in (
            '', '-', '—', 'N/A', 'NA', 'NONE',
            'NOT APPLICABLE', 'NOT AVAILABLE',
        ):
            # A covered Aetna service without an applicable portal limit is
            # still covered; the PDF should say "No Frequency", not N/A.
            frequency = 'NO FREQUENCY'
        if covered is False:
            frequency = 'NOT COVERED'
        normalized_procs.append({
            'procedure_code': code,
            'description': '',
            'frequency_limit': frequency,
            'benefit_level': (
                _aetna_plan_pct(item.get('percentage_copay'))
                if covered is True else
                'N/A' if covered is False else ''
            ),
            'deductible': 'NO' if not has_positive_deductible and covered is True else '',
            'age_limit': _aetna_age_limit(item.get('age_limit')),
            'late_date_of_service': _aetna_history(item.get('history'), covered),
            'number_of_quads': '',
            '_aetna_covered': covered,
            '_aetna_shares_frequency_with': item.get('shares_frequency_with') or '',
            '_aetna_message': item.get('message') or '',
        })

    category_map = {
        'preventative': 'PREVENTIVE',
        'preventive': 'PREVENTIVE',
        'basic': 'RESTORATIVE',
        'major': 'PROSTHODONTICS',
        'ortho': 'ORTHODONTICS',
    }
    covered_services = []
    for item in raw.get('co_insurance') or []:
        if not isinstance(item, dict):
            continue
        raw_type = clean(item.get('type')).lower()
        category = next(
            (mapped for hint, mapped in category_map.items() if hint in raw_type),
            clean(item.get('type')),
        )
        paid = _aetna_plan_pct(item.get('percentage'))
        if category and paid:
            covered_services.append({
                'category': category,
                'services': '',
                'in_network': paid,
                'out_of_network': '',
            })

    normalized = {
        '_skip_llm': True,
        '_source_insurer': 'aetna',
        'carrier_information': {'name': payer.get('name') or 'Aetna Dental Plans'},
        'subscriber_info': {
            'name': subscriber_name,
            # The shared extractor falls back to the patient's DOB when this
            # value is blank. For a dependent, preserve an unavailable
            # subscriber DOB explicitly instead of copying the child's DOB.
            'dob': subscriber_dob or ('-' if relationship.lower() not in ('self', 'subscriber') else patient_dob),
            'relation': relationship,
        },
        'metlife_data': {
            'patient': {
                'name': patient_name,
                'dob': patient_dob,
                'relationship': relationship,
            },
            'plan_details': {
                'start_date': dates.get('eligibility_begin') or '',
                'end_date': '',
                'subscriber_id': member_id,
                'employer_group': coverage.get('group_name') or payer.get('group_name') or '',
                'group_number': coverage.get('group_number') or payer.get('group#') or '',
                'network': payer.get('plan_type') or payer.get('description') or '',
                'plan_type': payer.get('plan_type') or '',
            },
            'financials': {
                'annual_max': {
                    'total': annual.get('amount') or '',
                    'used': _aetna_money_used(annual.get('amount'), annual.get('remaining')),
                    'remaining': annual.get('remaining') or '',
                },
                'deductible_ind': {
                    'total': individual_ded.get('amount') or '',
                    'used': _aetna_money_used(
                        individual_ded.get('amount'), individual_ded.get('remaining')
                    ),
                    'remaining': individual_ded.get('remaining') or '',
                },
                'deductible_fam': {
                    'total': family_ded.get('amount') or '',
                    'used': _aetna_money_used(
                        family_ded.get('amount'), family_ded.get('remaining')
                    ),
                    'remaining': family_ded.get('remaining') or '',
                },
                'ortho_lifetime': {
                    'total': ortho_max.get('amount') or '',
                    'used': _aetna_money_used(
                        ortho_max.get('amount'), ortho_max.get('remaining')
                    ),
                    'remaining': ortho_max.get('remaining') or '',
                },
            },
            'provider_info': {
                'provider_name': '',
                'provider_network_status': (
                    coverage.get('network_type') or payer.get('network_type') or ''
                ),
            },
            'covered_services': covered_services,
            'provisions': [],
        },
        'benefit_coverage': {'procedures': normalized_procs},
    }
    normalized['_aetna_meta'] = {
        'remarks': remarks,
        'plan_begin': dates.get('plan_begin') or '',
        'network_type': _aetna_network_label(
            coverage.get('network_type') or payer.get('network_type') or ''
        ),
        'annual_max_present': bool(annual),
        'individual_deductible_present': bool(individual_ded),
        'family_deductible_present': bool(family_ded),
        'has_positive_deductible': has_positive_deductible,
        'ortho_max_present': bool(ortho_max),
        'ortho_ded_total': ortho_ded.get('amount') or '',
        'ortho_ded_used': _aetna_money_used(
            ortho_ded.get('amount'), ortho_ded.get('remaining')
        ),
        'dependent_age': _aetna_dependent_age(remarks),
    }
    return normalized


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
        'ins_address': 'PO Box 14094, Lexington, KY 40512',
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