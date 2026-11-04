"""
Guardian (guardiananytime.com).

Recognizes the export `Extension/content_guardian.js` downloads, translates it
into the shared contract, and reads Guardian's own wording — prose frequencies,
age clauses, per-network coinsurance, "Date Not Found" — into the forms the
rest of the system compares.

The export is the page's Dental Eligibility VOB (`plan_information`,
`deductibles`, `plan_allowance`, `plan_options`, …) plus one record per CDT
code in `procedure_codes`, which the extension derives from the Plan Options
rows. Those records are taken as the extension wrote them; this module only
restates their wording.
"""

import re

from .common import clean


# Facts the eligibility page prints as static copy rather than per patient (the
# claim-mailing footer), so the extension leaves them out of the export.
_GUARDIAN_CLAIM_ADDRESS = {
    'address': 'PO Box 981572',
    'city': 'El Paso',
    'state': 'TX',
    'zip': '79998',
}
_GUARDIAN_PAYER_ID = '64246'


def _is_guardian_portal(raw):
    """The Guardian extension export: its source, and its Plan Options rows."""
    if not isinstance(raw, dict):
        return False
    return (
        str(raw.get('source') or '').strip().lower() == 'guardian'
        and isinstance(raw.get('plan_options'), list)
    )


# ── Networks ─────────────────────────────────────────────────────────────────
#
# Guardian names the in-network side after the plan's network ("DG Preferred")
# or plainly ("In-Network"); the other side is always some "Out-Network".

def _guardian_is_out_network(name):
    text = str(name or '').lower()
    return bool(re.search(r'\bout\b|out-|non[\s-]?par', text))


def _guardian_on_network(items, network, key='network'):
    """The entries of a per-network list that belong to the chosen network."""
    want_out = network == 'out'
    return [
        item for item in items or []
        if isinstance(item, dict) and _guardian_is_out_network(item.get(key)) == want_out
    ]


def _guardian_pct(amount):
    """'100%', '100' or 100 → '100%'."""
    m = re.search(r'(\d+(?:\.\d+)?)', str(amount if amount is not None else ''))
    return f'{float(m.group(1)):g}%' if m else ''


def _guardian_coinsurance(coinsurance, network):
    """The plan-paid percentage for one network, or ''."""
    for item in _guardian_on_network(coinsurance, network):
        pct = _guardian_pct(item.get('amount'))
        if pct:
            return pct
    return ''


def _guardian_category_coinsurance(raw, category, network):
    """The percentage of the first Plan Options row in that category, or ''."""
    wanted = clean(category).lower()
    for row in raw.get('plan_options') or [] if wanted else []:
        if isinstance(row, dict) and clean(row.get('category')).lower() == wanted:
            pct = _guardian_coinsurance(row.get('coinsurance'), network)
            if pct:
                return pct
    return ''


# ── Frequency ────────────────────────────────────────────────────────────────
#
# Guardian states a limit in prose, and the extension keeps the clause:
#     "twice in any 12 consecutive month period"
#     "once per tooth surface in any 12 months"
#     "once, per denture, in any 24-month period"
#     "once per tooth per lifetime"
# Each is restated in the sheet's own form (2X12Months, 1XLifetime) so the
# comparison reads one wording on both sides.

_GUARDIAN_NO_FREQUENCY = 'frequency not available'

_GUARDIAN_COUNTS = {
    'once': 1, 'twice': 2, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
    'five': 5, 'six': 6,
}
_GUARDIAN_COUNT = r'(once|twice|one|two|three|four|five|six|\d+)'


def _guardian_count(word):
    word = word.lower()
    return int(word) if word.isdigit() else _GUARDIAN_COUNTS[word]


def _guardian_frequency(text):
    """
    A Guardian frequency clause in the sheet's compact form, '' when there is
    none, or the clause unchanged when its shape is not one recognized here.

    "Frequency not available" is the extension saying no Plan Options sentence
    states a limit for the code. That is silence, not a statement that there
    is no limit, so it reads as unstated.
    """
    raw = clean(text)
    if not raw or raw.lower() == _GUARDIAN_NO_FREQUENCY:
        return ''
    s = re.sub(r'\s+', ' ', raw.lower().replace(',', ' '))

    m = re.match(_GUARDIAN_COUNT + r'\b.*?\bper\s+lifetime\b', s)
    if m:
        return f'{_guardian_count(m.group(1))}XLifetime'

    m = re.match(
        _GUARDIAN_COUNT + r'\b.*?\b(?:in|within|during|over|every)\s+(?:any\s+|a\s+|the\s+)?'
        r'(\d+)[\s-]+(?:consecutive\s+)?(?:calendar\s+)?(month|year)s?\b', s)
    if m:
        unit = 'Months' if m.group(3) == 'month' else 'Years'
        return f'{_guardian_count(m.group(1))}X{m.group(2)}{unit}'

    m = re.match(_GUARDIAN_COUNT + r'\b.*?\b(?:in\s+a|per|each)\s+calendar\s+year\b', s)
    if m:
        return f'{_guardian_count(m.group(1))}X1Year'

    m = re.match(_GUARDIAN_COUNT + r'\s+per\s+(\d+)\s+(month|year)s?\b', s)
    if m:
        unit = 'Months' if m.group(3) == 'month' else 'Years'
        return f'{_guardian_count(m.group(1))}X{m.group(2)}{unit}'

    return raw


# "Replacement of a denture or bridge is covered when it is at least 5 years
# old" is how Guardian states the frequency of prosthetics and crowns. The
# extension reads no frequency from it (the sentence is conditional), so it is
# read here. A sentence naming this code wins; otherwise one naming no code
# applies to the whole row. "Replacement of a post and core (D2952, …)" never
# lends its limit to a crown.
_GUARDIAN_REPLACEMENT_RE = re.compile(
    r'\breplacement\s+of\b(?P<subject>[^.]*?)\bis\s+covered\s+when\s+it\s+is\s+at\s+least\s+'
    r'(?P<years>\d+)\s+years?\s+old', re.IGNORECASE)


def _guardian_replacement_frequency(messages, code):
    row_wide = ''
    for message in messages or []:
        for m in _GUARDIAN_REPLACEMENT_RE.finditer(str(message)):
            named = set(re.findall(r'\bD\d{4}\b', m.group('subject').upper()))
            if code.upper() in named:
                return f"1X{m.group('years')}Years"
            if not named and not row_wide:
                row_wide = f"1X{m.group('years')}Years"
    return row_wide


# ── Age limit ────────────────────────────────────────────────────────────────

def _guardian_age_limit(text):
    """
    Guardian's age clause as a range: "up to age 19" / "under the age of 16"
    → 0-19 / 0-16 (the sheet records the number Guardian states), "age 12 and
    over" → 12-99.
    """
    s = clean(text).lower()
    if not s:
        return ''
    m = re.search(r'age\s+(\d{1,3})\s+(?:through|to|-)\s+(\d{1,3})', s)
    if m:
        return f'{m.group(1)}-{m.group(2)}'
    m = re.search(r'age\s+(\d{1,3})\s+(?:and|or)\s+(?:over|older)', s)
    if m:
        return f'{m.group(1)}-99'
    m = re.search(r'(?:up\s+to|under|through)\s+(?:the\s+)?age\s+(?:of\s+)?(\d{1,3})', s)
    if m:
        return f'0-{m.group(1)}'
    m = re.search(r'age\s+(\d{1,3})\s+and\s+under', s)
    if m:
        return f'0-{m.group(1)}'
    return ''


# ── Service history ──────────────────────────────────────────────────────────

def _guardian_history(value):
    """
    The last visit as the sheet writes it. Guardian prints "Date Not Found"
    for a service it has no record of — the sheet's NH. A quadrant list
    ("UR-03/01/2025;UL-Date Not Found;…") gives the dates it has.
    """
    text = clean(value)
    if not text:
        return ''
    dates = re.findall(r'\d{1,2}/\d{1,2}/\d{2,4}', text)
    if dates:
        return ', '.join(dict.fromkeys(dates))
    if re.search(r'date\s+not\s+found', text, re.IGNORECASE):
        return 'NH'
    return text


# ── Plan level ───────────────────────────────────────────────────────────────

def _guardian_money(value):
    m = re.search(r'-?\d[\d,]*(?:\.\d+)?', str(value if value is not None else ''))
    return float(m.group(0).replace(',', '')) if m else None


def _guardian_amount(value):
    number = _guardian_money(value)
    return f'{number:.2f}' if number is not None else ''


def _guardian_family_count(value):
    """Guardian states a family deductible as a head count: "3 per family"."""
    m = re.match(r'\s*(\d+)\s+per\s+family', str(value or ''), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _guardian_family_deductible(family, individual):
    """
    (total, met) of the family deductible in dollars.

    "3 per family" means the family is done once three members have each met
    the individual deductible, so the dollar figures are that count times the
    individual amount, and what is met is the count already reached. A family
    deductible stated in dollars is taken as it is.
    """
    total_count = _guardian_family_count(family.get('deductible'))
    if total_count is None:
        return _guardian_amount(family.get('deductible')), _guardian_amount(family.get('met_to_date'))
    each = _guardian_money(individual.get('deductible'))
    if each is None:
        return '', ''
    met = _guardian_money(family.get('met_to_date'))
    if met is None:
        remaining = _guardian_money(family.get('remaining_deductible'))
        met = total_count - remaining if remaining is not None else None
    return (f'{total_count * each:.2f}',
            f'{max(min(met, total_count), 0) * each:.2f}' if met is not None else '')


_GUARDIAN_MONTHS = (
    'january', 'february', 'march', 'april', 'may', 'june', 'july',
    'august', 'september', 'october', 'november', 'december',
)


def _guardian_plan_year_start(benefit_period):
    """
    The month the benefit period starts. The page prints it as
    "January 01 to December 31"; the extension joins the API's two dates with
    " - ", so a numeric start (01/01, 01/01/2026, 2026-01-01) is read too.
    """
    text = clean(benefit_period).lower()
    if not text:
        return ''
    start = re.split(r'\s+(?:-|to)\s+', text)[0]
    for month in _GUARDIAN_MONTHS:
        if start.startswith(month[:3]):
            return month.title()
    m = re.match(r'(\d{4})-(\d{1,2})-\d{1,2}', start) or re.match(r'()(\d{1,2})/\d{1,2}', start)
    if not m:
        m = re.match(r'()(\d{2})\d{2}(?:\d{4})?$', start)
    if m and 1 <= int(m.group(2)) <= 12:
        return _GUARDIAN_MONTHS[int(m.group(2)) - 1].title()
    return ''


def _guardian_category_dates(raw):
    """{category: effective date} from "Effective dates of coverage"."""
    out = {}
    for row in raw.get('effective_dates_of_coverage') or []:
        if isinstance(row, dict) and clean(row.get('service_category')) and clean(row.get('effective_date')):
            out[clean(row.get('service_category'))] = clean(row.get('effective_date'))
    return out


def _guardian_date_key(value):
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2,4})$', clean(value))
    if not m:
        return None
    year = int(m.group(3))
    year += 2000 if year < 100 else 0
    return year, int(m.group(1)), int(m.group(2))


def _guardian_waiting_period(raw):
    """
    ('Yes'|'No'|'', categories) — whether any service category starts later
    than Preventive does. Guardian shows a waiting period as a later effective
    date for that category; with every category starting together there is
    none.
    """
    dates = _guardian_category_dates(raw)
    keys = {cat: _guardian_date_key(date) for cat, date in dates.items()}
    keys = {cat: key for cat, key in keys.items() if key}
    if not keys:
        return '', []
    first = keys.get('Preventive') or min(keys.values())
    later = [cat for cat, key in keys.items() if key > first]
    return ('Yes' if later else 'No'), later


def _guardian_eff_date(raw):
    """The patient's effective date: Preventive's, else the earliest category's."""
    dates = _guardian_category_dates(raw)
    if dates.get('Preventive'):
        return dates['Preventive']
    keyed = [(key, date) for date in dates.values() for key in [_guardian_date_key(date)] if key]
    return min(keyed)[1] if keyed else ''


def _guardian_deductible_waived(raw, category, network):
    """Whether Guardian waives the deductible for a category on that network."""
    field = 'out_network_deductible_waived' if network == 'out' else 'in_network_deductible_waived'
    for row in raw.get('effective_dates_of_coverage') or []:
        if isinstance(row, dict) and clean(row.get('service_category')).lower() == category.lower():
            value = clean(row.get(field)).lower()
            if value in ('yes', 'y', 'true'):
                return True
            if value in ('no', 'n', 'false'):
                return False
    return None


def _guardian_preventive_waived(raw, network):
    """
    Whether the deductible is waived for preventive services on that network:
    the Deductibles table's own "Waived for preventive?" for the individual
    deductible, else the Preventive category's flag.
    """
    for row in _guardian_on_network(raw.get('deductibles'), network):
        if 'individual' in clean(row.get('coverage')).lower():
            value = clean(row.get('waived_for_preventive')).lower()
            if value in ('yes', 'y', 'true'):
                return True
            if value in ('no', 'n', 'false'):
                return False
    return _guardian_deductible_waived(raw, 'Preventive', network)


def _guardian_row(raw, service):
    """The Plan Options row of that name."""
    for row in raw.get('plan_options') or []:
        if isinstance(row, dict) and clean(row.get('service')).lower() == clean(service).lower():
            return row
    return None


def _guardian_ortho_not_covered(raw):
    """Whether the Orthodontics row says only "Not Covered"."""
    row = _guardian_row(raw, 'Orthodontics')
    if not row:
        return None
    text = ' '.join(str(m) for m in row.get('message') or []).lower()
    if re.search(r'\bnot\s+covered\b', text) and not row.get('coinsurance'):
        return True
    return False if row.get('coinsurance') else None


def _guardian_alternate_benefit(raw, service, subject_re):
    """'Yes' when that row states an alternate benefit for the subject, else ''."""
    row = _guardian_row(raw, service)
    for message in (row or {}).get('message') or []:
        text = str(message)
        if re.search(r'alternate\s+benefit', text, re.IGNORECASE) and re.search(subject_re, text, re.IGNORECASE):
            return 'Yes'
    return ''


def _guardian_composite_downgrade(raw):
    """
    Whether posterior composites are paid as amalgam: Yes where the Fillings
    row gives them the alternate benefit of an amalgam; No where it covers
    them without one ("… (D2330-D2335, D2391-D2394) are covered on all teeth
    with no surface restriction"); '' when the row says nothing about them.
    """
    if _guardian_alternate_benefit(raw, 'Fillings', r'posterior|D239[1-4]'):
        return 'Yes'
    row = _guardian_row(raw, 'Fillings')
    for message in (row or {}).get('message') or []:
        text = str(message)
        if (re.search(r'D239[1-4]|posterior', text, re.IGNORECASE)
                and re.search(r'\bcovered\b', text, re.IGNORECASE)
                and not re.search(r'\bnot\s+covered\b', text, re.IGNORECASE)):
            return 'No'
    return ''


# "Preventive services do not count toward the annual maximum" and the like.
# Guardian states it only when preventive is kept out of the maximum.
_GUARDIAN_PREVENTIVE_OUTSIDE_MAX_RE = re.compile(
    r'preventive[^.]*\b(?:do(?:es)?\s+not|don.t|not|never)\b[^.]*'
    r'\b(?:count|apply|applied|reduce|deduct\w*|accumulate)\b[^.]*\bmaximum'
    r'|maximum[^.]*\b(?:excludes?|does\s+not\s+include)\b[^.]*\bpreventive', re.IGNORECASE)


def _guardian_preventive_outside_max(raw):
    """'No' when the page says preventive does not count toward the maximum, else ''."""
    texts = [str(m) for row in raw.get('plan_options') or [] if isinstance(row, dict)
             for m in row.get('message') or []]
    texts.append(str((raw.get('plan_information') or {}).get('out_of_network_note') or ''))
    return 'No' if any(_GUARDIAN_PREVENTIVE_OUTSIDE_MAX_RE.search(t) for t in texts) else ''


def _guardian_patient_age(raw):
    """The patient's age on the day the page was read."""
    from .guardian_pdf import _date, _patient_age

    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(raw.get('scraped_at') or ''))
    reference = _date(f'{m.group(2)}/{m.group(3)}/{m.group(1)}') if m else None
    return _patient_age((raw.get('plan_information') or {}).get('date_of_birth'), reference)


# ── Translation ──────────────────────────────────────────────────────────────

# Codes Guardian's main page usually cannot answer for (team rule,
# 2026-11-02): the extension looks each up in the page's "Search coverage by
# CDT code" box, and that answer counts. Without one — a printout, or a search
# the user skipped — a main-page row that names the code in a statement of its
# own counts too (2026-11-04: "D2980-D2983 … are covered under Major",
# "Includes codes: … D4260"). A record the extension derived for one of them
# by its usual service mapping states nothing.
_GUARDIAN_CDT_SEARCH_CODES = frozenset({'D1510', 'D2980', 'D4260', 'D7140', 'D7210', 'D9944'})
_GUARDIAN_CDT_SEARCH_LOOKUP = 'Guardian CDT code search'


def _guardian_cdt_unsearched(record):
    """Whether this is a search-only code without a search or named-code answer."""
    from .guardian_pdf import NAMED_LOOKUP

    return (clean(record.get('code')).upper() in _GUARDIAN_CDT_SEARCH_CODES
            and clean(record.get('lookup_status')) not in (_GUARDIAN_CDT_SEARCH_LOOKUP, NAMED_LOOKUP))


def _guardian_records(raw):
    """
    The export's per-code records, with each search-only code the search did
    not answer taken from the main page where a row names it.
    """
    from .guardian_pdf import derive_named_code_record

    records = {}
    for record in raw.get('procedure_codes') or []:
        if isinstance(record, dict) and clean(record.get('code')):
            records.setdefault(clean(record.get('code')).upper(), record)
    searched = {code for code, r in records.items()
                if clean(r.get('lookup_status')) == _GUARDIAN_CDT_SEARCH_LOOKUP}
    age = _guardian_patient_age(raw)
    for code in sorted(_GUARDIAN_CDT_SEARCH_CODES - searched):
        named = derive_named_code_record(raw, code, age)
        if named:
            records[code] = named
    return list(records.values())


_GUARDIAN_CATEGORY_CONTRACT = {
    'preventive': 'PREVENTIVE',
    'basic': 'RESTORATIVE',
    'major': 'PROSTHODONTICS',
    'periodontics': 'PERIODONTICS',
    'endodontics': 'ENDODONTICS',
    'oral surgery': 'ORAL SURGERY',
    'orthodontics': 'ORTHODONTICS',
}


def _guardian_procedure(record, raw, network):
    """One `procedure_codes` record in the contract's procedure shape."""
    code = clean(record.get('code')).upper()
    covered = None if _guardian_cdt_unsearched(record) else record.get('covered')
    # A searched code's own row is the search answer, not a Plan Options row.
    search = record.get('cdt_search') if isinstance(record.get('cdt_search'), dict) else {}
    row = search.get('row') or _guardian_row(raw, record.get('dental_service')) or {}

    # A code Guardian covers only from some age ("Adult prophylaxis (D1110) is
    # covered age 12 and over") is marked not covered for a younger patient,
    # and the extension then drops its coinsurance. The plan's percentage for
    # the code is still its row's.
    age_only = covered is False and record.get('age_eligible') is False
    if covered is True:
        pct = _guardian_coinsurance(record.get('coinsurance'), network)
    elif age_only:
        # An "Other …" row prints no percentage; its code pays its category's.
        pct = (_guardian_coinsurance(row.get('coinsurance'), network)
               or _guardian_category_coinsurance(raw, record.get('dental_service_category'), network))
    elif covered is False:
        pct = '0%'
    else:
        pct = ''

    if covered is False and not age_only:
        frequency = 'NOT COVERED'
    elif covered is None:
        frequency = ''
    else:
        frequency = (_guardian_frequency(record.get('frequency'))
                     or _guardian_replacement_frequency(record.get('message'), code))

    return {
        'procedure_code': code,
        'description': clean(record.get('dental_service')),
        'frequency_limit': frequency,
        'benefit_level': pct,
        'age_limit': _guardian_age_limit(record.get('age_limit')) if covered is not None else '',
        'late_date_of_service': _guardian_history(record.get('last_visit_date')) if covered is not None else '',
        'number_of_quads': '',
        '_guardian_covered': covered,
        '_guardian_age_excluded': age_only,
        '_guardian_lookup': clean(record.get('lookup_status')),
    }


def _normalize_guardian_portal(raw):
    """Translate the Guardian export into the existing Portal contract."""
    # In network unless the caller already picked (the Sabrina audit picks
    # from the sheet's In Network field).
    network = 'out' if raw.get('_guardian_network') == 'out' else 'in'
    info = raw.get('plan_information') if isinstance(raw.get('plan_information'), dict) else {}

    relationship = clean(raw.get('relation_to_member'))
    patient_name = clean(raw.get('patient_name'))
    patient_dob = clean(info.get('date_of_birth'))
    is_self = relationship.lower() in ('self', 'member', 'employee', 'subscriber')

    deductibles = _guardian_on_network(raw.get('deductibles'), network)
    individual = next((d for d in deductibles if 'individual' in clean(d.get('coverage')).lower()), {})
    family = next((d for d in deductibles if 'family' in clean(d.get('coverage')).lower()), {})
    family_total, family_met = _guardian_family_deductible(family, individual)

    allowance = _guardian_on_network(raw.get('plan_allowance'), network)
    dental = next((a for a in allowance if 'ortho' not in clean(a.get('coverage')).lower()), {})
    ortho = next((a for a in allowance if 'ortho' in clean(a.get('coverage')).lower()), {})

    records = _guardian_records(raw)
    procedures = [_guardian_procedure(record, raw, network) for record in records]

    covered_services = []
    seen = set()
    for row in raw.get('plan_options') or []:
        if not isinstance(row, dict):
            continue
        category = clean(row.get('category'))
        contract = _GUARDIAN_CATEGORY_CONTRACT.get(category.lower())
        if not contract or contract in seen:
            continue
        in_pct = _guardian_coinsurance(row.get('coinsurance'), 'in')
        out_pct = _guardian_coinsurance(row.get('coinsurance'), 'out')
        if not (in_pct or out_pct):
            continue
        seen.add(contract)
        waived = (_guardian_preventive_waived(raw, network) if contract == 'PREVENTIVE'
                  else _guardian_deductible_waived(raw, category, network))
        applies = '' if waived is None else f" Deductible Applies : {'No' if waived else 'Yes'}"
        covered_services.append({
            'category': contract,
            'services': clean(row.get('service')),
            'in_network': (in_pct + (applies if network == 'in' else '')).strip(),
            'out_of_network': (out_pct + (applies if network == 'out' else '')).strip(),
        })

    waiting, waiting_categories = _guardian_waiting_period(raw)
    ortho_not_covered = _guardian_ortho_not_covered(raw)

    normalized = {
        '_skip_llm': True,
        '_source_insurer': 'guardian',
        'carrier_information': dict(_GUARDIAN_CLAIM_ADDRESS, name='Guardian', payer_id=_GUARDIAN_PAYER_ID),
        'subscriber_info': {
            # Guardian's eligibility page names only the patient, so the
            # subscriber is known only when that is the patient.
            'name': patient_name if is_self else '',
            'dob': patient_dob if is_self else '-',
            'relation': relationship,
        },
        'metlife_data': {
            'patient': {
                'name': patient_name,
                'dob': patient_dob,
                'relationship': 'Self' if is_self else relationship,
            },
            'plan_details': {
                'start_date': _guardian_eff_date(raw),
                'end_date': '',
                'subscriber_id': '',
                'employer_group': clean(info.get('group_name')),
                'group_number': clean(info.get('group_number')),
                'network': clean(info.get('plan_type')),
                'plan_type': clean(info.get('plan_type')),
            },
            'financials': {
                'annual_max': {
                    'total': _guardian_amount(dental.get('yearly_plan_limit')),
                    'used': _guardian_amount(dental.get('year_met_to_date')),
                    'remaining': _guardian_amount(dental.get('remaining_individual_maximum')),
                },
                'deductible_ind': {
                    'total': _guardian_amount(individual.get('deductible')),
                    'used': _guardian_amount(individual.get('met_to_date')),
                    'remaining': _guardian_amount(individual.get('remaining_deductible')),
                },
                'deductible_fam': {'total': family_total, 'used': family_met, 'remaining': ''},
                'ortho_lifetime': {
                    'total': _guardian_amount(ortho.get('lifetime_plan_limit') or ortho.get('yearly_plan_limit')),
                    'used': _guardian_amount(ortho.get('lifetime_met_to_date') or ortho.get('year_met_to_date')),
                    'remaining': _guardian_amount(ortho.get('remaining_lifetime_maximum')),
                },
            },
            'provider_info': {'provider_name': '', 'provider_network_status': ''},
            'covered_services': covered_services,
            'provisions': [],
        },
        'benefit_coverage': {'procedures': procedures},
    }
    normalized['_guardian_meta'] = {
        'network': network,
        'plan_year_start': _guardian_plan_year_start(info.get('benefit_period')),
        'waiting_period': waiting,
        'waiting_categories': waiting_categories,
        'missing_tooth': {True: 'Yes', False: 'No'}.get(info.get('missing_tooth_exclusion_applies'), ''),
        'oon_note': clean(info.get('out_of_network_note')),
        'ortho_not_covered': ortho_not_covered,
        'ortho_age_limit': clean(info.get('orthodontics_age_limit')),
        'ortho_max_present': bool(ortho),
        'posterior_composite_downgrade': _guardian_composite_downgrade(raw),
        # What the page states; with nothing stated the audit uses Guardian's
        # standard answer (carriers/guardian/rules.py).
        'porcelain_posterior_downgrade': _guardian_alternate_benefit(
            raw, 'Crown/Inlay/Onlay', r'posterior|porcelain|molar'),
        'prev_in_max': _guardian_preventive_outside_max(raw),
        'prev_deductible_waived': _guardian_preventive_waived(raw, network),
        'codes_without_row': [
            clean(r.get('code')) for r in records
            if clean(r.get('lookup_status')).lower().startswith('no matching')
        ],
        # Search-only codes with neither a search answer nor a main-page row
        # naming them: their rows read "not on portal".
        'cdt_search_missing': sorted(
            code for code in _GUARDIAN_CDT_SEARCH_CODES
            if not any(clean(r.get('code')).upper() == code and not _guardian_cdt_unsearched(r)
                       for r in records)),
    }
    return normalized
