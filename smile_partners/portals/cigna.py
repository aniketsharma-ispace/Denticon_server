"""
Cigna.

Recognizes the export, translates it into the shared contract, and applies the
corrections that only make sense for this carrier.
"""

import re

from .common import (_blank_present_end_date, _display_plan_type, _dollar,
                     _effective_date_month, _format_history_dates,
                     _triple_individual_deductible, clean)


def _cigna_molars_only_sealants(procs):
    """Resolve D1351 only when Cigna explicitly proves a tooth restriction.

    A patient-age exclusion or an overall not-covered response does not answer
    whether the plan is limited to permanent molars. When the website does not
    prove either direction, the PDF question is intentionally left blank.
    """
    p = (procs or {}).get('D1351') or {}
    groups = (
        p.get('_cigna_context_groups')
        or ((p.get('api_details') or {}).get('context_groups') or [])
    )

    molars = {'1', '2', '3', '14', '15', '16', '17', '18', '19', '30', '31', '32'}
    covered_molar = False
    covered_non_molar = False
    tested_non_molar = False

    for group in groups:
        outcome = group.get('outcome') or {}
        group_covered = outcome.get('covered') is True
        for context in group.get('contexts') or []:
            tooth = str(context.get('tooth') or '').upper().strip()
            if not tooth or tooth == 'N/A':
                continue
            if tooth in molars:
                if group_covered:
                    covered_molar = True
            else:
                tested_non_molar = True
                if group_covered:
                    covered_non_molar = True

    if covered_non_molar:
        return 'No'
    if covered_molar and tested_non_molar:
        return 'Yes'
    return ''


def _cigna_same_frequency(procs, *codes):
    """Return Yes only when every requested Cigna procedure has the same real limit."""
    values = []
    for code in codes:
        value = str((procs.get(code) or {}).get('frequency_limit') or '').strip()
        if not value or value.upper() in (
            'N/A', 'NA', 'NOT APPLICABLE', 'NO FREQUENCY',
            'NOT COVERED', 'NC', '-', '—',
        ):
            return '-'
        values.append(re.sub(r'\s+', ' ', value).upper())
    return 'Yes' if len(set(values)) == 1 else 'No'


def _cigna_frequency_is_unavailable(value):
    """True when a covered Cigna code has no usable frequency limit."""
    normalized = re.sub(r'\s+', ' ', str(value or '')).strip().upper()
    return normalized in (
        '', '-', '—', 'N/A', 'NA', 'NONE',
        'NOT APPLICABLE', 'NOT AVAILABLE',
    )


def _cigna_sync_bidirectional_pair(procs, code_a, code_b):
    """Make paired Cigna codes share the best resolved covered benefit.

    Cigna can return one age-specific prophylaxis code as covered and the other
    as not covered for the current patient. The business PDF treats D1110 and
    D1120 as a bidirectional pair, so whichever code has the resolved covered
    plan benefit becomes the display source for both rows.
    """
    candidates = []
    for code in (code_a, code_b):
        proc = (procs or {}).get(code) or {}
        if proc.get('_cigna_covered') is True:
            candidates.append((code, proc))

    if not candidates:
        return

    def score(item):
        _, proc = item
        return (
            1 if not _cigna_frequency_is_unavailable(proc.get('frequency_limit')) else 0,
            1 if str(proc.get('benefit_level') or '').strip() else 0,
            1 if str(proc.get('deductible') or '').strip() else 0,
            1 if str(proc.get('late_date_of_service') or '').strip() else 0,
        )

    source_code, source = max(candidates, key=score)
    copied_fields = (
        'frequency_limit', 'benefit_level', 'deductible', 'age_limit',
        'late_date_of_service', 'number_of_quads', '_cigna_covered',
        '_cigna_lookup_resolved', '_cigna_class_code',
    )

    for code in (code_a, code_b):
        target = (procs or {}).setdefault(code, {'procedure_code': code})
        target_description = target.get('description')
        for field in copied_fields:
            target[field] = source.get(field, '')
        target['_cigna_bidirectional_source'] = source_code
        if target_description:
            target['description'] = target_description


def _cigna_resolve_ortho_age(procs, portal_ortho_age=''):
    """Return blank for uncovered ortho; otherwise explicit age or 99."""
    ortho_codes = ('D8010', 'D8080', 'D8090')
    covered = [
        (procs or {}).get(code) or {}
        for code in ortho_codes
        if ((procs or {}).get(code) or {}).get('_cigna_covered') is True
    ]
    if not covered:
        return ''

    for proc in covered:
        raw_age = str(proc.get('age_limit') or '').strip()
        if raw_age.lower() in ('', '-', '—', 'n/a', 'na', 'none'):
            continue
        match = re.search(
            r'(?:exclude|excluded)\s+after\s+age\s*(\d+)|'
            r'under\s*(\d+)|'
            r'(\d+)\s*[-–]\s*(\d+)|'
            r'\b(\d+)\b',
            raw_age,
            re.IGNORECASE,
        )
        if match:
            values = [group for group in match.groups() if group]
            if values:
                return values[-1]

    portal_age = str(portal_ortho_age or '').strip()
    if portal_age.lower() not in ('', '-', '—', 'n/a', 'na', 'none', '0'):
        return portal_age

    # Business fallback: a covered orthodontic benefit with no age limit means 99.
    return '99'


def _cigna_has_alternate_benefit_phrase(proc):
    """True when Cigna explicitly says an alternate benefit may apply."""
    if not proc:
        return False
    if proc.get('_cigna_alternate_benefit') is True:
        return True
    api_details = proc.get('api_details') or {}
    text = ' '.join(
        str(value or '')
        for value in (
            proc.get('benefit_status'),
            proc.get('frequency_limit'),
            proc.get('description'),
            proc.get('notes'),
            api_details.get('validation_message'),
            api_details.get('notes'),
        )
    )
    return bool(re.search(r'alternate\s+benefits?\s+may\s+apply', text, re.IGNORECASE))


def _is_cigna_portal(raw):
    """Recognize the Cigna extension payload without affecting MetLife JSON."""
    if not isinstance(raw, dict):
        return False
    source = str(raw.get('source', '')).lower()
    return (
        'cigna' in source or
        (
            isinstance(raw.get('procedures'), dict) and
            isinstance(raw.get('procedures', {}).get('results'), list) and
            isinstance(raw.get('coinsurance'), list) and
            isinstance(raw.get('summary'), dict)
        )
    )


def _cigna_plan_pct(member_pct):
    """Convert Cigna member coinsurance into the plan-paid percentage."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', str(member_pct or ''))
    if not m:
        return ''
    paid = max(0.0, min(100.0, 100.0 - float(m.group(1))))
    return f'{paid:g}%'


def _cigna_network_value(record, *keys):
    for key in keys:
        value = record.get(key) if isinstance(record, dict) else None
        if value not in (None, '', 'N/A', 'NA'):
            return str(value).strip()
    return ''


def _cigna_network_matches(record, selected_network):
    """Match a Cigna record to plan_details.network without using OONET."""
    if not isinstance(record, dict):
        return False
    selected_network = selected_network if isinstance(selected_network, dict) else {}
    selected_name = _cigna_network_value(selected_network, 'name', 'networkName')
    selected_id = _cigna_network_value(selected_network, 'id', 'networkId')
    record_name = _cigna_network_value(record, 'networkName', 'network')
    record_id = _cigna_network_value(record, 'networkId', 'network_id')

    if selected_id:
        return record_id.lower() == selected_id.lower()
    if selected_name:
        return record_name.lower() == selected_name.lower()
    return False


def _cigna_matching_records(records, selected_network):
    """Return only records belonging to the portal-selected Cigna network."""
    valid = [record for record in (records or []) if isinstance(record, dict)]
    selected_network = selected_network if isinstance(selected_network, dict) else {}
    if _cigna_network_value(selected_network, 'name', 'networkName', 'id', 'networkId'):
        direct = [
            record for record in valid
            if _cigna_network_matches(record, selected_network)
        ]
        if direct:
            return direct
        # Some Cigna responses omit network fields on the financial records
        # after the portal has already scoped the page to the selected network.
        # Use these generic records only as a fallback, never over an exact
        # network match.
        generic = [
            record for record in valid
            if not _cigna_network_value(
                record, 'networkName', 'network', 'networkId', 'network_id'
            )
        ]
        if generic:
            return generic
        return []
    return valid


def _cigna_primary_record(records, desc_hint='', covers='', selected_network=None):
    """Choose a financial record from the portal-selected Cigna network."""
    candidates = []
    for record in _cigna_matching_records(records, selected_network):
        if desc_hint and not _cigna_financial_desc_matches(record, desc_hint):
            continue
        if covers and covers.upper() != str(record.get('covers', '')).upper():
            continue
        candidates.append(record)
    if not candidates:
        return {}
    def tier_rank(record):
        raw = record.get('tierIndex') or record.get('networkTier') or record.get('tier')
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 999
    return sorted(candidates, key=tier_rank)[0]


def _cigna_class_codes(record):
    return {
        value.strip()
        for value in str(record.get('classCode') or '').split(',')
        if value.strip()
    }


def _cigna_financial_desc_matches(record, desc_hint):
    """Cigna may label plan-year accumulators as Calendar Year or Policy Year."""
    desc = str(record.get('desc') or record.get('description') or '').lower()
    hint = str(desc_hint or '').lower()
    if not hint:
        return True
    if hint in desc:
        return True
    normalized_hint = hint.replace('calendar year', '').replace('policy year', '')
    return all(
        part in desc
        for part in normalized_hint.split()
        if part not in {'individual', 'family'}
    ) and any(
        word in desc
        for word in ('calendar year', 'policy year')
    )


def _cigna_general_annual_record(records, selected_network):
    """
    Select the core dental maximum, excluding ortho/implant-ONLY maxima.

    A maximum is only excluded when it covers nothing but ortho/implant work.
    Testing whether the class description merely MENTIONS them threw away the
    real annual maximum on plans that bundle implants into it — e.g. classDesc
    "Diagnostic and Preventive,Basic Restorative,Major Restorative,Implants",
    which left Yearly Max and Paid to Date with no value at all. A maximum that
    covers any general dental class (1 Diagnostic/Preventive, 2 Basic,
    3 Major) is the general maximum however many other classes ride along.
    """
    def _general(record):
        classes = _cigna_class_codes(record)
        if classes:
            return bool(classes & {'1', '2', '3'})
        # No class codes to go on: fall back to the wording.
        desc = str(record.get('classDesc', '')).lower()
        if not desc:
            return True
        return not all(
            ('ortho' in part or 'implant' in part or 'tmj' in part)
            for part in (p.strip() for p in desc.split(',')) if part
        )

    candidates = [
        record for record in _cigna_matching_records(records, selected_network)
        if 'maximum' in str(record.get('desc', '')).lower()
        and 'lifetime' not in str(record.get('desc', '')).lower()
        and str(record.get('covers', '')).upper() == 'IND'
        and _general(record)
    ]
    if not candidates:
        return {}
    dollar_candidates = [
        record for record in candidates
        if '$' in str(record.get('amount') or '')
    ]
    if dollar_candidates:
        dental_care = next(
            (
                record for record in dollar_candidates
                if 'dental care' in str(record.get('classDesc', '')).lower()
            ),
            None,
        )
        if dental_care:
            return dental_care
        candidates = dollar_candidates
    return next(
        (
            record for record in candidates
            if {'1', '2', '3'}.issubset(_cigna_class_codes(record))
        ),
        max(candidates, key=lambda record: len(_cigna_class_codes(record))),
    )


def _cigna_is_ortho_only(record):
    """True only when a financial record belongs to orthodontics alone (class 4).

    Cigna often bundles orthodontics into the general deductible, e.g.
    classCode "2,3,4,5" / "Basic Restorative,Major Restorative,Orthodontics,TMJ".
    That is the general deductible, not a separate orthodontic one, so a
    record that merely MENTIONS ortho must not be reported as the ortho value.
    """
    classes = _cigna_class_codes(record)
    if classes:
        return classes == {'4'}
    parts = [
        part.strip()
        for part in str(record.get('classDesc', '')).lower().split(',')
        if part.strip()
    ]
    if parts:
        return all('ortho' in part for part in parts)
    return 'ortho' in str(record.get('desc', '')).lower()


def _cigna_ortho_max_record(records, selected_network):
    return next(
        (
            record for record in _cigna_matching_records(records, selected_network)
            if _cigna_is_ortho_only(record)
        ),
        {},
    )


def _cigna_ortho_deductible_record(records, selected_network):
    return next(
        (
            record for record in _cigna_matching_records(records, selected_network)
            if _cigna_is_ortho_only(record)
        ),
        {},
    )


def _cigna_deductible_applicability(raw, selected_network):
    """
    Derive deductible service classes from selected-network records.
    content_cigna.js attaches the parent classCode/classDesc to accumulations.
    """
    supplied = (raw.get('financials') or {}).get('deductible_applicability')
    if isinstance(supplied, dict):
        return supplied

    records = _cigna_matching_records(
        (raw.get('financials') or {}).get('deductible_records'),
        selected_network,
    )
    codes = set()
    descriptions = []
    for record in records:
        codes.update(_cigna_class_codes(record))
        descriptions.append(str(record.get('classDesc') or '').lower())
    desc = ','.join(descriptions)
    return {
        'has_selected_network_deductible': bool(records),
        'class_codes': sorted(codes),
        'class_descriptions': [
            value.strip()
            for value in ','.join(
                str(record.get('classDesc') or '') for record in records
            ).split(',')
            if value.strip()
        ],
        'diagnostic': '1' in codes or 'diagnostic' in desc,
        'preventive': '1' in codes or 'preventive' in desc,
        'basic': '2' in codes or 'basic restorative' in desc,
        'major': '3' in codes or 'major restorative' in desc,
        'orthodontic': '4' in codes or 'orthodont' in desc,
        'periodontal': '6' in codes or 'periodontal' in desc,
        'implants': '9' in codes or 'implant' in desc,
    }


def _cigna_procedure_deductible(class_code, applicability):
    codes = {
        value.strip()
        for value in str(class_code or '').split(',')
        if value.strip() and value.strip().upper() not in ('N/A', 'NA')
    }
    if not codes:
        return ''
    deductible_codes = {
        str(value).strip() for value in applicability.get('class_codes', [])
    }
    if applicability.get('has_selected_network_deductible'):
        return 'YES' if bool(codes & deductible_codes) else 'NO'
    return 'NO'


def _cigna_covered_quadrant_count(api_details):
    """Count resolved covered quadrant contexts; unresolved data stays blank."""
    if str(api_details.get('coverage_scope') or '').lower() not in ('all', 'partial'):
        return ''
    quadrants = set()
    for group in api_details.get('context_groups') or []:
        if (group.get('outcome') or {}).get('covered') is not True:
            continue
        for context in group.get('contexts') or []:
            value = str(context.get('quadrant') or '').upper().strip()
            if value not in ('', 'N/A', 'NA'):
                quadrants.add(value)
    return str(len(quadrants)) if quadrants else ''


def _cigna_waiting_period_values(raw_waiting):
    if not raw_waiting:
        return 'No', '0', ''
    values = raw_waiting if isinstance(raw_waiting, list) else [raw_waiting]
    texts = []
    for value in values:
        if isinstance(value, dict):
            texts.extend(
                str(value.get(key) or '')
                for key in (
                    'summary', 'description', 'desc', 'value',
                    'waitingPeriod', 'waiting_period', 'notes',
                )
            )
        else:
            texts.append(str(value))
    text = clean(' '.join(part for part in texts if part))
    if not text:
        return 'No', '0', ''
    if re.search(r'\bno\s+waiting\b|does\s+not\s+apply|not\s+applicable', text, re.IGNORECASE):
        return 'No', '0', ''
    months = re.findall(r'(\d+)\s*month', text, re.IGNORECASE)
    categories = []
    for needle, label in (
        ('diagnostic', 'Diagnostic'),
        ('preventive', 'Preventive'),
        ('basic', 'Basic'),
        ('major', 'Major'),
        ('orthodont', 'Orthodontic'),
    ):
        if needle in text.lower():
            categories.append(label)
    return 'Yes', (months[-1] if months else ''), ' & '.join(categories)


def _normalize_cigna_portal(raw):
    """
    Translate Cigna's extension payload into the established Portal contract.
    No Denticon insurance/benefit values are introduced here.
    """
    summary = raw.get('summary') or {}
    patient = raw.get('patient') or {}
    plan = raw.get('plan_details') or {}
    network = plan.get('network') or {}
    financials = raw.get('financials') or {}
    notes = raw.get('notes') or {}
    results = (raw.get('procedures') or {}).get('results') or []
    frequency_by_code = {
        str(item.get('procedure_code', '')).upper().strip(): item
        for item in (raw.get('frequencies') or [])
        if item.get('procedure_code')
    }

    maximums = financials.get('maximum_records') or []
    deductibles = financials.get('deductible_records') or []
    annual = _cigna_general_annual_record(maximums, network)
    family_max = _cigna_primary_record(
        maximums, 'Family Calendar Year Maximum', 'FAM', network
    )
    individual_ded = _cigna_primary_record(
        deductibles, 'Individual Calendar Year Deductible', 'IND', network
    )
    family_ded = _cigna_primary_record(
        deductibles, 'Family Calendar Year Deductible', 'FAM', network
    )
    ortho_max = _cigna_ortho_max_record(maximums, network)
    ortho_ded = _cigna_ortho_deductible_record(deductibles, network)
    deductible_applicability = _cigna_deductible_applicability(raw, network)

    normalized_procs = []
    unresolved_codes = []
    for proc in results:
        code = str(proc.get('procedure_code', '')).upper().strip()
        if not code:
            continue
        api_details = proc.get('api_details') or {}
        validation = str(api_details.get('validation_message') or '')
        coverage_scope = str(api_details.get('coverage_scope') or '').lower()
        lookup_failed = (
            bool(api_details.get('lookup_error'))
            or 'lookup failed' in str(proc.get('benefit_status') or '').lower()
        )
        unresolved_context = (
            lookup_failed
            or
            coverage_scope == 'unresolved'
            or (
                bool(api_details.get('context_required'))
                and bool(re.search(r'invalid|missing|required', validation, re.IGNORECASE))
            )
        )
        if unresolved_context and code != 'D5860':
            unresolved_codes.append(code)
        matched_limitations = _cigna_matching_records(
            api_details.get('limitation_records'), network
        )
        matched_coinsurance = _cigna_matching_records(
            api_details.get('coinsurance_records'), network
        )
        matched_limitation = matched_limitations[0] if matched_limitations else {}
        matched_coin = matched_coinsurance[0] if matched_coinsurance else {}
        covered = proc.get('covered')
        freq = str(
            matched_limitation.get('summary')
            or proc.get('frequency_limit')
            or ''
        )
        if unresolved_context:
            # The response is not a valid coverage decision. A tooth/arch/
            # quadrant-specific request or successful API response is required
            # before showing NC.
            covered = None
            freq = ''
        elif covered is False:
            freq = 'NOT COVERED'

        limitation = matched_limitation or api_details.get('limitation') or {}
        age = (
            limitation.get('age_summary')
            or proc.get('age_limitation')
            # The extension's compact export keeps the procedure's own age
            # limit here ("Exclude after age 18") rather than in `limitation`.
            or api_details.get('age_limit')
            or ''
        )
        if str(age).upper() in ('N/A', 'NA', 'NONE'):
            age = ''
        if not age:
            age = (frequency_by_code.get(code) or {}).get('age_limitation') or ''
        if str(age).upper() in ('N/A', 'NA', 'NONE'):
            age = ''
        if not age:
            max_age = str(
                limitation.get('maxAge')
                or limitation.get('maximum_age')
                or ''
            ).strip()
            if max_age not in ('', '0', '999'):
                age = f'Under {max_age}'

        history = (
            _format_history_dates((api_details.get('history_dates') or []))
            or _format_history_dates((api_details.get('service_history') or []))
            or proc.get('history_date')
            or ''
        )
        if unresolved_context:
            history = ''
        elif 'no history' in str(history).lower():
            history = 'NH'

        # Do not infer a D4341 quadrant count from Cigna context probing.
        # Cigna PDF answer is intentionally blank; MetLife is handled later.
        quadrant = '' if code == 'D4341' else _cigna_covered_quadrant_count(api_details)
        if not quadrant:
            quadrant = proc.get('quadrant') if code != 'D4341' else ''
        if str(quadrant).upper() in ('N/A', 'NA', 'NONE', ''):
            quadrant = ''
        class_code = api_details.get('class_code') or proc.get('class_code') or ''
        plan_frequency = frequency_by_code.get(code) or {}
        plan_frequency_records = _cigna_matching_records(
            plan_frequency.get('limitation_records'), network
        )
        plan_frequency_selected = (
            plan_frequency_records[0] if plan_frequency_records else {}
        )

        normalized_procs.append({
            'procedure_code': code,
            'description': proc.get('description') or '',
            'frequency_limit': freq,
            'benefit_level': (
                _cigna_plan_pct(
                    matched_coin.get('amount')
                    or proc.get('coinsurance_member_pct')
                )
                if covered is True else
                'N/A' if covered is False else ''
            ),
            'deductible': _cigna_procedure_deductible(
                class_code, deductible_applicability
            ),
            'age_limit': age,
            'late_date_of_service': history,
            'number_of_quads': quadrant,
            '_cigna_covered': covered,
            '_cigna_coverage_scope': coverage_scope,
            '_cigna_alternate_benefit': proc.get('alternate_benefit'),
            '_cigna_context_groups': api_details.get('context_groups') or [],
            '_cigna_lookup_resolved': not unresolved_context,
            '_cigna_class_code': class_code,
            '_cigna_plan_procedure': plan_frequency.get('procedure') or '',
            '_cigna_plan_frequency': (
                plan_frequency_selected.get('summary')
                or plan_frequency.get('limit')
                or ''
            ),
            '_cigna_plan_age_limit': (
                plan_frequency_selected.get('ageSummary')
                or plan_frequency.get('age_limitation')
                or ''
            ),
            '_cigna_plan_covered': plan_frequency_selected.get('covered'),
        })

    # Some Cigna high-level frequency records (for example D8080) may not be
    # repeated in procedure results. Retain them so the PDF can still show NC
    # or the available limitation without inventing a percentage.
    result_codes = {p['procedure_code'] for p in normalized_procs}
    for code, item in frequency_by_code.items():
        if code in result_codes:
            continue
        records = _cigna_matching_records(
            item.get('limitation_records'), network
        )
        selected = records[0] if records else {}
        covered = selected.get('covered')
        age = item.get('age_limitation') or ''
        if str(age).upper() in ('N/A', 'NA', 'NONE'):
            age = ''
        normalized_procs.append({
            'procedure_code': code,
            'description': item.get('procedure') or '',
            'frequency_limit': (
                'NOT COVERED' if covered is False else item.get('limit') or ''
            ),
            'benefit_level': 'N/A' if covered is False else '',
            'deductible': '',
            'age_limit': age,
            'late_date_of_service': 'NH',
            'number_of_quads': '',
            '_cigna_covered': covered,
            '_cigna_plan_procedure': item.get('procedure') or '',
            '_cigna_plan_frequency': (
                selected.get('summary') or item.get('limit') or ''
            ),
            '_cigna_plan_age_limit': (
                selected.get('ageSummary') or item.get('age_limitation') or ''
            ),
            '_cigna_plan_covered': covered,
        })

    covered_services = []
    seen_categories = set()
    cigna_category_map = {
        'diagnostic and preventive': 'PREVENTIVE',
        'basic restorative': 'RESTORATIVE',
        'major restorative': 'PROSTHODONTICS',
    }
    for item in raw.get('coinsurance') or []:
        if not _cigna_network_matches(item, network):
            continue
        raw_category = str(item.get('category', '')).strip()
        category = next(
            (
                mapped for hint, mapped in cigna_category_map.items()
                if hint in raw_category.lower()
            ),
            raw_category,
        )
        if not category or category.upper() in seen_categories:
            continue
        seen_categories.add(category.upper())
        plan_pct = _cigna_plan_pct(item.get('patient_pays'))
        category_upper = category.upper()
        canonical_category = (
            'PREVENTIVE'
            if 'DIAGNOSTIC' in category_upper or 'PREVENTIVE' in category_upper
            else 'RESTORATIVE'
            if 'BASIC' in category_upper
            else 'PROSTHODONTICS'
            if 'MAJOR' in category_upper
            else category
        )
        covered_services.append({
            'category': canonical_category,
            'services': '',
            'in_network': plan_pct,
            'out_of_network': '',
        })

    coverage = plan.get('current_coverage') or summary.get('coverage_dates') or {}
    normalized = {
        '_skip_llm': True,
        '_source_insurer': 'cigna',
        'carrier_information': {'name': 'Cigna'},
        'subscriber_info': {
            'name': plan.get('subscriber') or patient.get('name') or '',
            'dob': plan.get('subscriber_dob') or patient.get('dob') or '',
            'relation': patient.get('relationship') or '',
        },
        'metlife_data': {
            'patient': {
                'name': patient.get('name') or '',
                'dob': patient.get('dob') or '',
                'relationship': patient.get('relationship') or '',
            },
            'plan_details': {
                'start_date': coverage.get('from') or plan.get('initial_coverage_date') or '',
                # Cigna's "Present" is not an actual patient termination date.
                'end_date': _blank_present_end_date(coverage.get('to')),
                'subscriber_id': summary.get('patient_id') or '',
                'employer_group': summary.get('group_name') or plan.get('account_name') or '',
                'group_number': summary.get('group_number') or plan.get('account_number') or '',
                'network': plan.get('plan_type') or summary.get('plan_type') or '',
                'plan_type': plan.get('plan_type') or summary.get('plan_type') or '',
            },
            'financials': {
                'annual_max': {
                    'total': annual.get('amount') or '',
                    'used': annual.get('met') or '',
                    'remaining': annual.get('remaining') or '',
                },
                'deductible_ind': {
                    'total': individual_ded.get('amount') or '',
                    'used': individual_ded.get('met') or '',
                    'remaining': individual_ded.get('remaining') or '',
                },
                'deductible_fam': {
                    'total': family_ded.get('amount') or '',
                    'used': family_ded.get('met') or '',
                    'remaining': family_ded.get('remaining') or '',
                },
                'ortho_lifetime': {
                    'total': ortho_max.get('amount') or '',
                    'used': ortho_max.get('met') or '',
                    'remaining': ortho_max.get('remaining') or '',
                },
            },
            'provider_info': {
                'provider_name': '',
                'provider_network_status': '',
            },
            'covered_services': covered_services,
            'provisions': [],
        },
        'benefit_coverage': {'procedures': normalized_procs},
    }

    dependent_age = next(
        (
            str(x.get('age'))
            for x in raw.get('age_limits') or []
            if 'dependent' in str(x.get('type', '')).lower()
            and _cigna_network_matches(x, network)
        ),
        '',
    )
    ortho_age = next(
        (
            str(x.get('age'))
            for x in raw.get('age_limits') or []
            if 'ortho' in str(x.get('type', '')).lower()
            and _cigna_network_matches(x, network)
        ),
        '',
    )
    waiting = notes.get('waiting_period')
    missing_tooth = str(notes.get('missing_tooth') or '').strip()
    normalized['_cigna_meta'] = {
        'dependent_age': dependent_age,
        'ortho_age': ortho_age,
        'deductible_applicability': deductible_applicability,
        'missing_tooth': missing_tooth,
        'waiting_period': waiting,
        'family_deductible_present': bool(family_ded),
        'individual_deductible_present': bool(individual_ded),
        'annual_max_present': bool(annual),
        'ortho_max_present': bool(ortho_max),
        'ortho_ded_total': ortho_ded.get('amount') or '',
        'ortho_ded_used': ortho_ded.get('met') or '',
        'network_name': network.get('name') or '',
        'plan_renews': plan.get('plan_renews') or '',
        'unresolved_codes': sorted(set(unresolved_codes)),
        'procedure_result_count': len(results),
    }
    return normalized


def _apply_cigna_output_rules(data, normalized):
    """Apply Cigna-only meanings and mark unavailable portal values with '-'."""
    meta = normalized.get('_cigna_meta') or {}
    deductible_applicability = meta.get('deductible_applicability') or {}
    missing_raw = str(meta.get('missing_tooth') or '').strip()
    missing_text = missing_raw.lower()
    if missing_text in ('', 'n/a', 'na', 'none', '-', '—'):
        missing_tooth = '-'
    elif (
        'does not apply' in missing_text
        or 'not applicable' in missing_text
        or missing_text == 'no'
    ):
        missing_tooth = 'No'
    else:
        # An explicit date/end date or any affirmative clause value means the
        # missing-tooth clause applies.
        missing_tooth = 'Yes'

    waiting_value, waiting_months, applies_to = _cigna_waiting_period_values(
        meta.get('waiting_period')
    )

    data.update({
        'source_insurer': 'cigna',
        'ins_name': '(IN) CIGNA',
        'ins_address': 'PO BOX 188037, Chattanooga, TN 37422',
        'ins_phone': '8002446224',
        'payor_id': '62308',
        # TOTAL/P0010 is the selected Cigna network, not a fee schedule name.
        'fee_schedule': '-',
        'ssn': data.get('member_id') or '-',
        'elig_notes': 'ins: cigna, benefits verified online',
        'plan_type': _display_plan_type(data.get('plan_type')),
        'term_date': '-',
        'plan_year_start': (
            'January'
            if 'CALENDAR' in str(meta.get('plan_renews', '')).upper()
            else _effective_date_month(data.get('eff_date')) or '-'
        ),
        'family_ded': (
            data.get('family_ded', '')
            if meta.get('family_deductible_present')
            else _triple_individual_deductible(data.get('indiv_ded'))
        ),
        'family_ded_paid': (
            data.get('family_ded_paid', '')
            if meta.get('family_deductible_present')
            else data.get('indiv_ded_paid', '')
        ),
        'yearly_max': (
            data.get('yearly_max', '') if meta.get('annual_max_present') else '-'
        ),
        'yearly_rem': (
            data.get('yearly_rem', '') if meta.get('annual_max_present') else '-'
        ),
        'indiv_ded': (
            data.get('indiv_ded', '')
            if meta.get('individual_deductible_present') else '-'
        ),
        'indiv_ded_paid': (
            data.get('indiv_ded_paid', '')
            if meta.get('individual_deductible_present') else '-'
        ),
        'ortho_max': (
            data.get('ortho_max', '')
            if meta.get('ortho_max_present') else '-'
        ),
        'ortho_max_paid': (
            data.get('ortho_max_paid', '')
            if meta.get('ortho_max_present') else '-'
        ),
        'ortho_ded': _dollar(meta.get('ortho_ded_total'), default='-'),
        'ortho_ded_paid': _dollar(meta.get('ortho_ded_used'), default='-'),
        'dep_age_limit': meta.get('dependent_age') or '-',
        'waiting_period': waiting_value or 'No',
        'waiting_period_mo': waiting_months or '0',
        'applies_to': applies_to or '-',
        'missing_tooth': missing_tooth,
        'major_on_prep': '-',
        'or_seat': '-',
        'ded_prev': (
            'Yes' if deductible_applicability.get('preventive') else 'No'
        ),
        'ded_diag': (
            'Yes' if deductible_applicability.get('diagnostic') else 'No'
        ),
        'molars_only_sealants': '',
        'posterior_composite_downgrade': '-',
        'porcelain_posterior_downgrade': '-',
        'd2950_same_day_crown': '-',
        'ortho_payment_frequency': '-',
        'ortho_age_limit_llm': '',
        'd0120_d0150_share_d0140': _cigna_same_frequency(
            data.get('procs') or {}, 'D0120', 'D0150', 'D0140'
        ),
        'd4910_d1110_share_freq': _cigna_same_frequency(
            data.get('procs') or {}, 'D4910', 'D1110'
        ),
        'd4341_number_of_quads': '-',
        'pre_auth': 'Recommended-200',
    })

    procs = data.get('procs') or {}

    # Cigna's plan-level limitation endpoint is authoritative for the general
    # sealant benefit even when the current patient's age-gated procedure lookup
    # returns not covered. Match the named Topical Sealant Application benefit.
    d1351 = procs.get('D1351') or {}
    if (
        str(d1351.get('_cigna_plan_procedure') or '').strip().lower()
        == 'topical sealant application'
        and d1351.get('_cigna_plan_covered') is True
    ):
        d1351.update({
            'frequency_limit': d1351.get('_cigna_plan_frequency') or '',
            'benefit_level': (
                data.get('pct_prev')
                if str(data.get('pct_prev') or '').strip() not in ('', '-', '—')
                else '100%'
            ),
            'deductible': data.get('ded_prev') or '',
            'age_limit': d1351.get('_cigna_plan_age_limit') or '',
            'late_date_of_service': (
                d1351.get('late_date_of_service')
                if str(d1351.get('late_date_of_service') or '').strip()
                not in ('', '-', '—')
                else 'NH'
            ),
            '_cigna_covered': True,
            '_cigna_lookup_resolved': True,
        })

    # Adult and child prophylaxis are a bidirectional display pair.
    _cigna_sync_bidirectional_pair(procs, 'D1110', 'D1120')

    data['ortho_age_limit_llm'] = _cigna_resolve_ortho_age(
        procs, meta.get('ortho_age')
    )
    data['molars_only_sealants'] = _cigna_molars_only_sealants(procs)

    # Business rule: the exact Cigna alternate-benefit phrase means Yes. A
    # successfully resolved response without that phrase means No. Failed or
    # unresolved lookups remain unknown.
    # Posterior composites are judged on D2391 (posterior composite) — NOT
    # D2140, which is amalgam and carries the phrase on almost every plan.
    for code, output_key in (
        ('D2391', 'posterior_composite_downgrade'),
        ('D2740', 'porcelain_posterior_downgrade'),
    ):
        proc = procs.get(code) or {}
        if proc.get('_cigna_covered') is None:
            data[output_key] = '-'
        else:
            data[output_key] = (
                'Yes' if _cigna_has_alternate_benefit_phrase(proc) else 'No'
            )

    # Business truth table:
    # D2950 not covered -> No; D2950 + D2740 covered -> Yes;
    # D2950 covered but D2740 not covered -> No; unresolved -> unknown.
    d2950 = procs.get('D2950') or {}
    d2740 = procs.get('D2740') or {}
    d2950_covered = d2950.get('_cigna_covered')
    d2740_covered = d2740.get('_cigna_covered')
    if d2950_covered is False:
        data['d2950_same_day_crown'] = 'No'
    elif d2950_covered is True and d2740_covered is True:
        data['d2950_same_day_crown'] = 'Yes'
    elif d2950_covered is True and d2740_covered is False:
        data['d2950_same_day_crown'] = 'No'
    else:
        data['d2950_same_day_crown'] = '-'

    # The PDF row represents either D1206 or D1208. Prefer a covered code. The
    # high-level Cigna limitation response supplies a reliable D1208 fallback
    # for older crawl files that did not include D1208 in detailed results.
    d1206 = procs.get('D1206') or {}
    d1208 = procs.get('D1208') or {}
    fluoride = None
    if d1206.get('_cigna_covered') is True:
        fluoride = d1206
    elif d1208.get('_cigna_covered') is True:
        fluoride = dict(d1208)
        if not str(fluoride.get('benefit_level') or '').strip():
            fluoride['benefit_level'] = data.get('pct_prev') or '-'
        if not str(fluoride.get('deductible') or '').strip():
            fluoride['deductible'] = data.get('ded_prev') or '-'
        if not str(fluoride.get('late_date_of_service') or '').strip():
            # Older exports only provide the D1208 limitation, not service
            # history. Display unknown rather than inventing "No History".
            fluoride['late_date_of_service'] = '-'
    elif d1206:
        fluoride = d1206
    elif d1208:
        fluoride = d1208
    if fluoride:
        procs['_CIGNA_FLUORIDE_DISPLAY'] = fluoride

    unresolved_codes = meta.get('unresolved_codes') or []
    if unresolved_codes:
        data['elig_notes'] = (
            f"WARNING: Cigna benefit crawl incomplete - {len(unresolved_codes)} "
            "procedure lookup(s) unresolved. Rerun before finalizing."
        )

    # Cigna's over-denture-complete response is intentionally represented as
    # the requested zero-percent/N/A display, even when no usable lookup row
    # is returned for this code.
    d5860 = procs.setdefault('D5860', {})
    d5860.update({'frequency_limit': 'N/A', 'benefit_level': '0%'})

    if data.get('chair_provider') in ('', '—'):
        data['chair_provider'] = '-'
    if data.get('d4341_number_of_quads') in ('', '—'):
        data['d4341_number_of_quads'] = '-'
    return data