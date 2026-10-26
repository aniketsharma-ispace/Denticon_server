"""
Aetna (ClaimConnect), read once for every client.

shared/portals/aetna.py

Everything here is about Aetna's page and the extension's JSON, never about a
client's business rules:
  * which tables are in network / out of network, and the network view
  * repairing rows crawled by older extensions (shifted columns)
  * maximums ("DENTAL" or "Annual Maximum"), deductibles, co-insurance
  * per-code coverage, Not Covered, rows that state nothing
  * frequency wordings (units / visits, years / months / days, lifetime)
  * history paid dates and "Shares frequency with" lists
  * Medicare plans and their claim address
  * translating the export into the Portal contract (_normalize_aetna_portal)

A client keeps only its own rules (which code answers which question, how its
sheet words things) in its own folder, and reads Aetna through this module.
When Aetna's layout changes, fix it here once and every client gets it.
"""

from __future__ import annotations

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


_AETNA_FREQ_PART_RE = re.compile(
    r'(Frequency|History|Age Limitation):\s*(.*?)(?=\s*(?:Frequency|History|Age Limitation):|$)',
    re.IGNORECASE | re.DOTALL)


def _aetna_repair_service_row(item):
    """
    A plan whose service table has an extra column (a waiting period such as
    "12 months") was crawled by an older extension that read columns by
    position: the Frequency & Limitations text landed in `message` and the
    real message was lost. Move Frequency / History / Age Limitation back to
    their own fields. Rows read correctly pass through unchanged.
    """
    if not isinstance(item, dict):
        return item
    blank = lambda v: str(v or '').strip().upper() in ('', 'N/A')
    message = str(item.get('message') or '')
    if not (blank(item.get('frequency')) and blank(item.get('history')) and blank(item.get('age_limit'))):
        return item
    parts = {m.group(1).lower(): m.group(2).strip() for m in _AETNA_FREQ_PART_RE.finditer(message)}
    if not parts:
        return item
    rest = _AETNA_FREQ_PART_RE.sub('', message).strip()
    return {
        **item,
        'frequency': parts.get('frequency') or 'N/A',
        'history': parts.get('history') or 'N/A',
        'age_limit': parts.get('age limitation') or 'N/A',
        'message': rest,
    }


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
    view['service_level_benefits'] = [_aetna_repair_service_row(r) for r in view['service_level_benefits']]
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


def _aetna_is_medicare_export(raw):
    """A Medicare plan: the payer's Description, Comments or Name say Medicare."""
    if not isinstance(raw, dict):
        return False
    payer = raw.get('payer') if isinstance(raw.get('payer'), dict) else {}
    text = ' '.join(str(payer.get(k) or '') for k in ('description', 'comments', 'name', 'plan_type'))
    return 'medicare' in text.lower()


_AETNA_COVERAGE_WORDS = ('individual', 'family', 'employee', 'spouse', 'child', 'single')


def _aetna_repair_amount_row(item):
    """
    Some plans print their Deductibles table without a Type column
    (Coverage | Amount | Remaining | Message). An extension that read the
    first cell as the type left every value one column to the left:
    type="Individual", coverage="$0.00", amount="$0.00", remaining="Calendar
    Year". Put such a row back in the right columns.
    """
    if not isinstance(item, dict):
        return item
    type_text = str(item.get('type') or '').strip().lower()
    coverage_text = str(item.get('coverage') or '').strip()
    if (any(word in type_text for word in _AETNA_COVERAGE_WORDS)
            and re.match(r'^\$?\s*[\d,]+(?:\.\d+)?$', coverage_text)):
        return {
            **item,
            'type': 'Dental',
            'coverage': item.get('type'),
            'amount': item.get('coverage'),
            'remaining': item.get('amount'),
            'message': item.get('remaining') or item.get('message') or '',
        }
    return item


def _aetna_annual_maximum(maximums):
    """
    The plan's yearly maximum. Most plans call the row "DENTAL"; some call it
    "Annual Maximum". Any individual maximum that is not orthodontic counts.
    """
    record = _aetna_financial_record(maximums, 'dental', 'individual')
    if record:
        return record
    for item in maximums or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get('type') or '').lower()
        if 'ortho' in kind:
            continue
        if 'individual' in str(item.get('coverage') or '').lower() or not item.get('coverage'):
            return item
    return {}


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
    maximums = [_aetna_repair_amount_row(r) for r in raw.get('maximums') or []]
    deductibles = [_aetna_repair_amount_row(r) for r in raw.get('deductibles') or []]

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
    # Read by the extension from the subscriber's own Plan Benefits page when
    # the patient is a dependent (extension 10/2026+).
    subscriber_dob = clean(subscriber.get('date_of_birth') or '')
    if subscriber_dob:
        pass
    elif subscriber_name and clean(subscriber_name).lower() == clean(patient_name).lower():
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

    annual = _aetna_annual_maximum(maximums)
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
    claim = raw.get('claim_address') if isinstance(raw.get('claim_address'), dict) else {}
    normalized['_aetna_meta'] = {
        'remarks': remarks,
        # Medicare plans send claims to their own address, read from the
        # page's Provider Information > Claim Address (extension 10/2026+).
        'claim_address': clean(claim.get('address') or '') if _aetna_is_medicare_export(raw) else '',
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


# ── Page-reading helpers used by the Sabrina audit ──────────────────────────

def _aetna_export(portal_raw: dict) -> dict | None:
    """The raw Aetna export with network buckets, bare or wrapped."""
    if not isinstance(portal_raw, dict):
        return None
    for candidate in (portal_raw, portal_raw.get("aetna_data"),
                      portal_raw.get("portal_data"), portal_raw.get("_raw_export")):
        if (isinstance(candidate, dict) and _is_aetna_portal(candidate)
                and _aetna_has_network_buckets(candidate)):
            return candidate
    return None


def _aetna_rows(portal_raw: dict, table: str) -> list:
    """One table's rows for the network being audited (already lifted to the top)."""
    if not isinstance(portal_raw, dict):
        return []
    for candidate in (portal_raw.get("_raw_export"), portal_raw):
        if isinstance(candidate, dict) and isinstance(candidate.get(table), list):
            return [r for r in candidate[table] if isinstance(r, dict)]
    return []


def _aetna_row(portal_raw: dict, code: str) -> dict | None:
    """The service row for one code, in the network being audited."""
    for row in _aetna_rows(portal_raw, "service_level_benefits"):
        if str(row.get("procedure_code") or "").strip().upper() == code.upper():
            return row
    return None


def _aetna_row_covered(row: dict) -> bool:
    return bool(re.search(r"\d+\s*%", str(row.get("percentage_copay") or ""))) and \
        "not covered" not in str(row.get("message") or "").lower()


def _aetna_row_states_nothing(row: dict | None) -> bool:
    """
    A row that names the code but states no benefit: no percentage, no
    frequency, no message (only, say, a waiting period of "12 months"). The
    portal is silent on that code, so nothing about it can be compared.
    """
    if not row:
        return False
    blank = lambda v: str(v or "").strip().upper() in ("", "N/A")
    said = " ".join(str(row.get(k) or "") for k in ("percentage_copay", "message", "frequency"))
    if re.search(r"not\s+covered", said, re.IGNORECASE):
        return False                   # "Not Covered" is a statement
    return (not re.search(r"\d+\s*%", str(row.get("percentage_copay") or ""))
            and blank(row.get("frequency"))
            and blank(row.get("message")))


def _aetna_remarks(portal_raw: dict) -> str:
    """The Plan Level Remarks, lower-cased, as one string."""
    return " ".join(str(r or "") for r in (_aetna_export(portal_raw) or {}).get("plan_level_remarks") or []).lower()


def _aetna_code_pct(row: dict | None) -> str | None:
    """What the plan pays for a covered code ("0% / 100% $0.00" -> "100%")."""
    if not row or not _aetna_row_covered(row):
        return None
    m = re.search(r"(\d+)\s*%\s*/\s*(\d+)\s*%", str(row.get("percentage_copay") or ""))
    return f"{int(m.group(2))}%" if m else None


# "2 Units, for 1 Calendar Year PER FULL MOUTH."  -> 2X1Year
# "1 Unit, per 60 Months TOOTH NUMBER 01 TO 32." -> 1X60Months
# "3 Visits, for 1 Calendar Year DENTAL ..."      -> 3X1Year
# "1 Unit, for 999 Calendar Years PER FULL MOUTH." -> 1XLifetime
# "1 Unit Lifetime per Tooth."                     -> 1XLifetime
# "1 Unit, per 150 Days PER FULL MOUTH."            -> 1X150Days
# "2 Units, for 1 Service Year PER FULL MOUTH."     -> 2X1Year
_AETNA_FREQ_RE = re.compile(
    r"(\d+)\s*(?:units?|visits?|times?)\s*,?\s*(?:(?:for|per|in|every)\s+(\d+)\s*)?"
    r"(?:calendar\s+|contract\s+|benefit\s+|plan\s+|service\s+|policy\s+)?(year|month|day)s?",
    re.IGNORECASE)


# "1 Unit Lifetime per Tooth." / "1 Unit Lifetime." -> 1XLifetime
_AETNA_LIFETIME_RE = re.compile(
    r"(\d+)\s*(?:units?|visits?|times?)\s*,?\s*(?:(?:for|per|in)\s+)?(?:a\s+|the\s+)?lifetime",
    re.IGNORECASE)


def _aetna_frequency(text: str) -> str | None:
    """Aetna's frequency wording in the sheet's compact form, or None."""
    life = _AETNA_LIFETIME_RE.search(str(text or ""))
    if life:
        return f"{int(life.group(1))}XLifetime"
    m = _AETNA_FREQ_RE.search(str(text or ""))
    if not m:
        return None
    # "2 Units Calendar Year." states no span: once per (one) year.
    count, span, unit = int(m.group(1)), int(m.group(2) or 1), m.group(3).lower()
    if unit == "year" and span >= 99:
        return f"{count}XLifetime"
    if unit == "day":
        return f"{count}X{span}Days"
    return f"{count}X{span}Year" if unit == "year" else f"{count}X{span}Months"


_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))\b")


def _aetna_row_shared_codes(row: dict) -> set[str]:
    """
    The codes in a row's "Shares frequency with ..." list. Ranges such as
    D2510-D2794 are expanded; words such as DEDUCTIBLE DOES NOT APPLY are
    ignored.
    """
    text = " ".join(str(row.get(k) or "") for k in ("shares_frequency_with", "message"))
    m = re.search(r"shares?\s+frequenc(?:y|ies)\s+with\s*(.*)", text, re.IGNORECASE)
    listed = m.group(1) if m else str(row.get("shares_frequency_with") or "")
    codes: set[str] = set()
    for a, b in re.findall(r"\b(D\d{4})(?:\s*-\s*(D\d{4}))?\b", listed, re.IGNORECASE):
        if b:
            lo, hi = sorted((int(a[1:]), int(b[1:])))
            if hi - lo <= 500:
                codes.update(f"D{n:04d}" for n in range(lo, hi + 1))
                continue
        codes.add(a.upper())
    return codes


def _aetna_history_dates(row: dict) -> list[str]:
    """Every paid date in a row's History line ("Last paid date: 02/12/26")."""
    return _DATE_RE.findall(str((row or {}).get("history") or ""))