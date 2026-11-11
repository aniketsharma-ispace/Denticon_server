"""
Delta Dental of Missouri.

Recognizes the export of the Delta Dental of Missouri provider portal
(providers.deltadentalmo.com, scraped by the extension's content_DD_MO.js),
translates it into the shared contract, and applies the corrections that only
make sense for this portal.

It is a different portal from Delta Dental's own provider site (`delta_dental.py`)
and from the Office Toolkit (`delta_toolkit.py`), with an export of its own
shape, so it has a module of its own. The portal also serves plans of other
Delta companies (a "Delta Dental South Carolina" plan is read here too), so the
plan's own insurer name is kept as the carrier.
"""

import re
from datetime import date, datetime

from .common import _blank_present_end_date, _dollar


# ═══════════════════════════════════════════════════════════════════════════════
#  DELTA DENTAL OF MISSOURI — provider portal export
# ═══════════════════════════════════════════════════════════════════════════════
#
# The export is already structured: member_details, maximum_and_deductible,
# coverage_levels (one row per requested CDT code, with the PPO / Premier /
# out-of-network percentage, frequency and age limit the portal's coverage
# table prints) and patient_history. Everything the breakdown sheet audits is
# in there; it only has to be put into the contract the rest of the pipeline
# speaks. Nothing here touches another carrier's path.

# The networks a coverage row states a percentage for.
_MO_NETWORK_PCT = {'ppo': 'ppo_pct', 'premier': 'premier_pct', 'oon': 'oon_pct'}

# Codes whose service dates count against each other. The portal files a date
# under the one code that was billed; the team records it against each code of
# the pair (11/10, team rule, Mahesh): an exam history is D0120's and D0150's,
# a full-mouth series is panoramic history and the reverse, and varnish is
# fluoride history and the reverse.
_MO_DEFAULT_SHARED = (
    ('D0120', 'D0150'),
    ('D0210', 'D0330'),
    ('D1206', 'D1208'),
)

# One-way: a perio maintenance visit is prophy history and SRP on one to three
# teeth (D4342) is D4341 history, but the sheets keep D4910 to its own dates
# (NH on Anna's, David's, Evan's, Tammy's and Tia's with D1110 dates on the
# portal), so a prophy is not perio maintenance history.
_MO_HISTORY_ALSO_FROM = {
    'D1110': ('D4910',),
    'D4341': ('D4342',),
}

# A limitation that names another code as sharing it ("also applies to
# D0330", "shared with D1208", "combined with D0150") links the two as well.
_MO_SHARED_LIMIT_RE = re.compile(
    r'(?:also\s+appl(?:y|ies)\s+to|shared?\s+(?:limit\w*\s+|frequency\s+)?with|combined\s+with)'
    r'\s*:?\s*(?P<codes>D\d{4}(?:\s*(?:,|/|&|and|or)\s*D\d{4})*)',
    re.IGNORECASE)


def _mo_shared_history_groups(coverage_levels):
    """Each code's history group: itself, its team pair, and any code a limitation says it shares with."""
    groups = {}

    def _link(code, other):
        merged = groups.get(code, {code}) | groups.get(other, {other})
        for member in merged:
            groups[member] = merged

    for code, other in _MO_DEFAULT_SHARED:
        _link(code, other)
    for row in coverage_levels or []:
        if not isinstance(row, dict) or not row.get('code'):
            continue
        code = str(row['code']).upper().strip()
        for m in _MO_SHARED_LIMIT_RE.finditer(str(row.get('other_limitations') or '')):
            for other in re.findall(r'D\d{4}', m.group('codes'), re.IGNORECASE):
                _link(code, other.upper())
    return groups

# The orthodontic codes, which carry the plan's orthodontic age rather than one
# of their own.
_MO_ORTHO_CODES = ('D8010', 'D8070', 'D8080', 'D8090')


_MO_PAYER_ID = '43090'
_MO_CLAIMS_ADDRESS = 'PO Box 8690, Saint Louis, MO 63126'


def _is_missouri_insurer(insurer):
    return bool(re.search(r'\bmissouri\b|\(mo\)', str(insurer or ''), re.IGNORECASE))


def _is_dd_mo_portal(raw):
    """Recognize the Delta Dental of Missouri provider-portal export."""
    if not isinstance(raw, dict) or not isinstance(raw.get('coverage_levels'), list):
        return False
    return (str(raw.get('carrier') or '').upper() == 'DELTA_MO'
            or 'delta dental of missouri' in str(raw.get('source') or '').lower())


# "2 per Calendar Year", "4 per Benefit Year", "1 per Lifetime",
# "1 every 60 Months from the last date of service of the same treatment",
# "1 every 2 Years", "1 per 6 Months", "1 per Day".
_MO_FREQ_RE = re.compile(
    r'^\s*(\d+)\s+(?:per|every|in)\s+(?:(\d+)\s+)?'
    r'(lifetime|calendar\s+year|benefit\s+year|plan\s+year|contract\s+year|year|month|day|visit)s?\b',
    re.IGNORECASE)


def _mo_frequency(text):
    """
    The portal's frequency as the compact form the sheet uses.

    "2 per Calendar Year"                         -> 2X1Year
    "1 every 60 Months from the last date …"      -> 1X60Months
    "1 every 2 Years"                             -> 1X2Years
    "1 per Lifetime"                              -> 1XLifetime
    "1 per Day"                                   -> 1X1Day
    no frequency in the coverage table            -> No Frequency

    A wording the pattern does not know is passed through as stated rather
    than guessed at, so the audit reports it as not comparable.
    """
    raw = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not raw:
        return 'No Frequency'
    m = _MO_FREQ_RE.match(raw)
    if not m:
        return raw
    count, span, unit = int(m.group(1)), int(m.group(2) or 1), m.group(3).lower()
    if unit == 'lifetime':
        return f'{count}XLifetime'
    if unit in ('day', 'visit'):
        return f'{count}X{span}Day' if span == 1 else f'{count}X{span}Days'
    if unit == 'month':
        return f'{count}X{span}Months'
    return f'{count}X{span}Year' if span == 1 else f'{count}X{span}Years'


def _mo_age_limit(text):
    """
    The portal's age limit as a range the audit can compare.

    "0 to 18" is a ceiling of 18; "14+" is a floor, recorded as 14-99 so a
    floor is never read as "no age limit". A code the coverage table states
    without an age limit has none, which the sheet records as 99.
    """
    raw = str(text or '').strip()
    if not raw:
        return '99'
    m = re.fullmatch(r'(\d{1,3})\s*(?:to|-|–|through)\s*(\d{1,3})', raw, re.IGNORECASE)
    if m:
        return f'{m.group(1)}-{m.group(2)}'
    m = re.fullmatch(r'(\d{1,3})\s*\+', raw)
    if m:
        return f'{m.group(1)}-99'
    return raw


def _mo_ortho_age(text):
    """
    The plan's orthodontic age ("No age limit.", "Dependents through age 18.")
    as the number the sheet records against D8080; 99 is no limit.
    """
    raw = str(text or '').strip()
    if not raw:
        return ''
    if re.search(r'no\s+age\s+limit', raw, re.IGNORECASE):
        return '99'
    m = re.search(r'(\d{1,3})', raw)
    return m.group(1) if m else ''


def _mo_as_of(raw):
    """The day the portal was read, from the export's timestamp."""
    try:
        return datetime.fromisoformat(str(raw.get('extracted_at') or '').replace('Z', '+00:00')).date()
    except ValueError:
        return date.today()


def _mo_dob(dob, age, as_of):
    """
    The member's date of birth.

    The portal masks the year ("08/17/XXXX") but states the member's age, so
    the year is the one that gives that age on the day the portal was read.
    """
    text = str(dob or '').strip()
    if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}', text):
        return text
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/X{2,4}', text, re.IGNORECASE)
    if not m or not isinstance(age, int):
        return ''
    month, day = int(m.group(1)), int(m.group(2))
    year = as_of.year - age - (1 if (month, day) > (as_of.month, as_of.day) else 0)
    return f'{month:02d}/{day:02d}/{year}'


def _mo_money(value):
    """An accumulator amount as the breakdown prints money."""
    if value is None or value == '':
        return ''
    if isinstance(value, str) and value.strip().lower() == 'unlimited':
        return '$99,999.00'
    try:
        return f'${float(value):,.2f}'
    except (TypeError, ValueError):
        return ''


def _mo_accumulator_table(value):
    """
    The export's maximum_and_deductible, as the named accumulators.

    Exports made before content_DD_MO.js named them list the portal's rows
    instead — {"plan_type": "Individual", "sub_type": "Deductible",
    "category": "Regular", "ppo": {"max", "met", "remaining", "note"}, …} —
    and are read into the same names, PPO network first as the newer exports
    are.
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return {}
    names = {
        ('individual', 'deductible', 'regular'): ('individual_regular_deductible', 'met'),
        ('family', 'deductible', 'regular'): ('family_regular_deductible', 'met'),
        ('individual', 'maximum', 'regular'): ('individual_regular_annual_maximum', 'used'),
        ('individual', 'maximum', 'orthodontic'): ('individual_orthodontic_lifetime_maximum', 'used'),
        ('individual', 'deductible', 'orthodontic'): ('individual_orthodontic_deductible', 'met'),
    }
    table = {}
    for row in value:
        if not isinstance(row, dict):
            continue
        key = tuple(str(row.get(k) or '').strip().lower() for k in ('plan_type', 'sub_type', 'category'))
        name, used_key = names.get(key, (None, None))
        if not name or name in table:
            continue
        ppo = row.get('ppo') if isinstance(row.get('ppo'), dict) else {}
        shared = str(ppo.get('note') or '').strip().upper() == 'SHARED'
        table[name] = {'amount': 'SHARED' if shared else ppo.get('max'),
                       used_key: ppo.get('met') or 0, 'remaining': ppo.get('remaining')}
    # The rows are every accumulator the plan has, so a plan without a family
    # deductible row has none.
    table.setdefault('family_regular_deductible', {'amount': None, 'met': None, 'remaining': None})
    return table


def _mo_accumulator(record, used_key):
    """
    (stated, {'total', 'used', 'remaining'}) for one accumulator of the export.

    Exports made before content_DD_MO.js added `amount` state only what was
    used and what remains, which still give the total. "SHARED" is an
    accumulator the portal keeps no amount for.
    """
    if not isinstance(record, dict):
        return False, {'total': '', 'used': '', 'remaining': ''}
    amount, used, remaining = record.get('amount'), record.get(used_key), record.get('remaining')
    if isinstance(amount, str) and amount.strip().upper() == 'SHARED':
        return False, {'total': '', 'used': '', 'remaining': ''}
    if 'amount' not in record and isinstance(used, (int, float)) and isinstance(remaining, (int, float)):
        amount = used + remaining
    if amount is None and remaining is None:
        return False, {'total': '', 'used': '', 'remaining': ''}
    return True, {'total': _mo_money(amount), 'used': _mo_money(used or 0),
                  'remaining': _mo_money(remaining)}


def _mo_yes_no(value):
    text = str(value or '').strip().lower()
    if text in ('yes', 'y'):
        return 'Yes'
    if text in ('no', 'n'):
        return 'No'
    return ''


def _normalize_dd_mo_portal(raw):
    """
    Translate the Delta Dental of Missouri export into the established Portal
    contract.

    `_mo_network` — "ppo" (the default), "premier" or "oon" — names the network
    whose percentages are read; the audit sets it from the sheet's In Network
    and fee schedule. No Denticon values are introduced here.
    """
    member = raw.get('member_details') or {}
    accumulators = _mo_accumulator_table(raw.get('maximum_and_deductible'))
    network = str(raw.get('_mo_network') or 'ppo').lower()
    pct_key = _MO_NETWORK_PCT.get(network, 'ppo_pct')
    as_of = _mo_as_of(raw)

    # ── identity ───────────────────────────────────────────────────────────
    relationship = str(member.get('relationship') or '').strip()
    name = str(member.get('patient_name') or '').strip()
    dob = _mo_dob(member.get('dob'), member.get('age'), as_of)

    # The subscriber is the family member the portal lists as Self. The portal
    # states no date of birth for anyone but the member being read.
    family = [m for m in (member.get('family_members') or []) if isinstance(m, dict)]
    subscriber = next((m for m in family if str(m.get('relationship') or '').lower() == 'self'), None)
    if relationship.lower() == 'self':
        subscriber_name, subscriber_dob = name, dob
    else:
        subscriber_name = str((subscriber or {}).get('patient_name') or '').strip()
        subscriber_dob = ''

    # ── maximums and deductibles (the PPO network's, as the export states them) ─
    max_stated, annual = _mo_accumulator(accumulators.get('individual_regular_annual_maximum'), 'used')
    ind_stated, deductible_ind = _mo_accumulator(accumulators.get('individual_regular_deductible'), 'met')
    fam_stated, deductible_fam = _mo_accumulator(accumulators.get('family_regular_deductible'), 'met')
    _, ortho_max = _mo_accumulator(accumulators.get('individual_orthodontic_lifetime_maximum'), 'used')
    ortho_ded_stated, ortho_ded = _mo_accumulator(accumulators.get('individual_orthodontic_deductible'), 'met')

    # The accumulator table lists every maximum and deductible the plan has, so
    # a table stating the annual maximum but no deductible is the portal saying
    # there is none (Umar Aamer: $2,000 maximum, no deductible rows).
    zero = {'total': '$0.00', 'used': '$0.00', 'remaining': '$0.00'}
    if max_stated and not ind_stated:
        deductible_ind = dict(zero)
    if max_stated and not fam_stated and 'family_regular_deductible' in accumulators:
        deductible_fam = dict(zero)

    # The export carries the PPO network's accumulators only. They are the
    # plan's own: the portal's out-of-network column states the same figures
    # (David Olea's capture), and the team reads them for an out-of-network
    # sheet too (11/10, Evan Hopf).

    # A plan with orthodontics whose table has no orthodontic maximum or
    # deductible for this member has none: 0 (11/10, team rule, Mahesh).
    zero_used = {'total': '$0.00', 'used': '$0.00', 'remaining': '$0.00'}
    if not str(ortho_max.get('total') or '').strip():
        ortho_max = dict(zero_used)
    if not ortho_ded_stated:
        ortho_ded_stated, ortho_ded = True, {'total': '$0.00', 'met': '$0.00', 'remaining': '$0.00',
                                             'used': '$0.00'}

    # ── service history, shared across codes ───────────────────────────────
    history_by_code = {}
    for row in raw.get('patient_history') or []:
        if not isinstance(row, dict) or not row.get('code'):
            continue
        code = str(row['code']).upper().strip()
        when = str(row.get('date_of_service') or '').strip()
        if when:
            history_by_code.setdefault(code, [])
            if when not in history_by_code[code]:
                history_by_code[code].append(when)

    shared_groups = _mo_shared_history_groups(raw.get('coverage_levels'))

    def _history(code):
        codes = sorted(set(shared_groups.get(code, {code})) | set(_MO_HISTORY_ALSO_FROM.get(code, ())))
        dates = []
        for c in codes:
            for when in history_by_code.get(c, []):
                if when not in dates:
                    dates.append(when)
        # Newest first, as the portal and the sheet both list them.
        dates.sort(key=lambda d: datetime.strptime(d, '%m/%d/%Y') if re.fullmatch(r'\d{2}/\d{2}/\d{4}', d) else datetime.min,
                   reverse=True)
        return ', '.join(dates) if dates else '—'

    # ── per-code benefits ──────────────────────────────────────────────────
    ortho_age = _mo_ortho_age(member.get('ortho_age'))
    has_ortho = _mo_yes_no(member.get('has_ortho'))
    procedures = []
    categories = {}
    for row in raw.get('coverage_levels') or []:
        if not isinstance(row, dict) or not row.get('code'):
            continue
        code = str(row['code']).upper().strip()
        if not row.get('listed') and code in _MO_ORTHO_CODES and has_ortho == 'Yes':
            # The plan covers orthodontics but the coverage table leaves the
            # codes out for this member (an adult past the plan's ortho age,
            # Anna Hayes). The plan's ortho age still stands, and the member
            # is covered at 0%, as for any code the table leaves out
            # [11/11, user decision: Gaye Stewart-Tooson, Tammy Swank].
            procedures.append({
                'procedure_code': code,
                'description': '',
                'benefit_level': '0%',
                'frequency_limit': '',
                'age_limit': ortho_age,
                'late_date_of_service': _history(code),
                'deductible': '',
                'limitation': '',
                'mo_listed': False,
            })
            continue
        if not row.get('listed'):
            # The coverage table lists every procedure the plan pays for, so a
            # requested code it does not list is one the plan does not cover —
            # the sheet records those as 0% and NC.
            procedures.append({
                'procedure_code': code,
                'description': '',
                'benefit_level': 'Not Covered',
                'frequency_limit': 'NC',
                'age_limit': '',
                'late_date_of_service': _history(code),
                'deductible': '',
                'limitation': '',
                'mo_listed': False,
            })
            continue

        pct = row.get(pct_key)
        level = f'{pct:g}%' if isinstance(pct, (int, float)) else ''
        age = ortho_age if code in _MO_ORTHO_CODES and ortho_age else _mo_age_limit(row.get('age_limit'))
        procedures.append({
            'procedure_code': code,
            'description': str(row.get('description') or ''),
            'benefit_level': level,
            'frequency_limit': _mo_frequency(row.get('frequency')),
            'age_limit': age,
            'late_date_of_service': _history(code),
            'deductible': str(row.get('ppo_deductible_applies') or ''),
            'limitation': str(row.get('other_limitations') or ''),
            'mo_listed': True,
        })

        # One coverage line per benefit group, paying the most that group pays
        # in and out of network — what the network questions are answered from.
        group = str(row.get('benefit_group') or '').strip().upper()
        if group:
            best = categories.setdefault(group, {'in': None, 'out': None})
            for side, value in (('in', pct), ('out', row.get('oon_pct'))):
                if isinstance(value, (int, float)) and (best[side] is None or value > best[side]):
                    best[side] = value

    covered_services = [{
        'category': group,
        'in_network': '' if best['in'] is None else f"{best['in']:g}%",
        'out_of_network': '' if best['out'] is None else f"{best['out']:g}%",
        'services': group.title(),
    } for group, best in categories.items()]

    # ── provisions ─────────────────────────────────────────────────────────
    provisions = []
    if member.get('cob_type'):
        provisions.append({'rule': 'Coordination of Benefits Rule', 'value': str(member['cob_type'])})

    # "Calendar Year 01/01" — the benefit year and the day it turns over.
    cycle = str(member.get('benefit_cycle') or '')
    turn = re.search(r'(\d{1,2})/(\d{1,2})', cycle)
    period_start = ''
    if turn:
        month, day = int(turn.group(1)), int(turn.group(2))
        start_year = as_of.year if (month, day) <= (as_of.month, as_of.day) else as_of.year - 1
        period_start = f'{month:02d}/{day:02d}/{start_year}'
        kind = 'CALENDAR YEAR' if 'calendar' in cycle.lower() else 'PLAN YEAR'
        provisions.append({'rule': 'Benefit Period', 'value': f'{kind} Start Date: {period_start}'})

    waiting = _mo_yes_no(member.get('waiting_period'))
    if waiting == 'No':
        provisions.append({'rule': 'Waiting Period', 'value': 'No waiting period'})

    # The portal's "Existing Tooth Clause: Yes" is the clause applying: a tooth
    # lost before the effective date is not replaced.
    clause = _mo_yes_no(member.get('existing_tooth_clause'))
    if clause:
        provisions.append({
            'rule': 'Missing Tooth Clause',
            'value': ('Are plan benefits available for teeth lost prior to effective date: '
                      + ('No.' if clause == 'Yes' else 'Yes.')),
        })

    insurer = str(member.get('insurer') or '').strip() or 'Delta Dental of Missouri'
    by_code = {p['procedure_code']: p for p in procedures}

    return {
        '_skip_llm': True,
        '_source_insurer': 'delta dental mo',
        'carrier_information': {
            'name': insurer,
            # The portal states neither the payer ID nor a claims address; the
            # team records Delta Dental of Missouri's (11/10, team rule,
            # Mahesh). The payer ID is the same for the other Delta companies
            # this portal serves (Tammy Swank's South Carolina plan), whose
            # claims address is their own and stays unstated.
            'payer_id': _MO_PAYER_ID,
            'address': _MO_CLAIMS_ADDRESS if _is_missouri_insurer(insurer) else '',
        },
        'subscriber_info': {
            'name': subscriber_name,
            'dob': subscriber_dob,
            'relation': relationship or 'Self',
        },
        'metlife_data': {
            'patient': {'name': name, 'dob': dob, 'relationship': relationship},
            'plan_details': {
                'start_date': str(member.get('effective_date') or ''),
                'end_date': _blank_present_end_date(member.get('termination_date')),
                'subscriber_id': str(member.get('subscriber_id') or ''),
                'employer_group': str(member.get('group_name') or ''),
                'group_number': str(member.get('group_number') or ''),
                'network': str(member.get('program_type') or ''),
                'plan_type': str(member.get('program_type') or ''),
            },
            'financials': {
                'annual_max': dict(annual),
                'deductible_ind': deductible_ind,
                'deductible_fam': deductible_fam,
                'ortho_lifetime': {**ortho_max, 'category': 'Orthodontics'},
            },
            'provider_info': {'provider_name': '', 'provider_network_status': ''},
            'covered_services': covered_services,
            'provisions': provisions,
        },
        'benefit_coverage': {'procedures': procedures},
        '_mo_meta': {
            'network': network,
            'scraped_on': as_of.strftime('%m/%d/%Y'),
            # When the benefit year began, and whether it is a calendar year —
            # the window a service date has to fall in to count against a
            # frequency.
            'benefit_period_start': period_start,
            'benefit_period_calendar': 'calendar' in cycle.lower(),
            'waiting_period': waiting,
            'missing_tooth': clause,
            'is_max_advantage': _mo_yes_no(member.get('is_max_advantage')),
            'has_ortho': _mo_yes_no(member.get('has_ortho')),
            'ded_applies_preventative': (by_code.get('D0120') or {}).get('deductible', ''),
            'ded_applies_diagnostic': (by_code.get('D0220') or {}).get('deductible', ''),
            'deductible_zero': (deductible_ind.get('total') == '$0.00'
                                and deductible_fam.get('total') in ('$0.00', '')),
            'ortho_deductible': ortho_ded if ortho_ded_stated else {},
        },
    }


def _apply_dd_mo_output_rules(data, normalized):
    """
    Delta Dental of Missouri corrections applied after the shared extraction.

    The sheet's Preventative / Basic / Major rows name procedure codes (D0120,
    D2160, D2740), and the portal states an exact percentage per code, so the
    per-code value is used rather than the shared category reading.
    """
    procedures = {
        str(p.get('procedure_code', '')).upper(): p
        for p in ((normalized.get('benefit_coverage') or {}).get('procedures') or [])
    }

    def _level(*codes):
        for code in codes:
            level = str((procedures.get(code) or {}).get('benefit_level') or '').strip()
            if level:
                return level
        return ''

    for key, codes in (
        ('pct_prev', ('D0120', 'D1110', 'D0150')),
        ('pct_basic', ('D2160', 'D2140', 'D2331', 'D2391')),
        ('pct_major', ('D2740', 'D6750', 'D5110')),
    ):
        level = _level(*codes)
        if level:
            data[key] = '0%' if level == 'Not Covered' else level

    def _covered(code):
        """Three-valued: covered, not covered, or never stated."""
        record = procedures.get(code)
        if record is None or not str(record.get('benefit_level') or '').strip():
            return None
        m = re.search(r'(\d+(?:\.\d+)?)\s*%', str(record['benefit_level']))
        return bool(m) and float(m.group(1)) > 0

    def _limitation(code):
        return re.sub(r'\s+', ' ', str((procedures.get(code) or {}).get('limitation') or '')).strip()

    # The portal has no Alternate Benefits provision; the two downgrade
    # questions are answered from the codes' own limitations (11/10, team
    # rule, Mahesh). A posterior composite is downgraded where D2391 reads
    # "Covered as amalgam on molars", and not otherwise. A posterior crown is
    # downgraded where D2740 states any limitation, and not where it states
    # none. A code the plan does not cover (Christine White's preventive-only
    # plan) has nothing to downgrade, so the question is left unanswered.
    if _covered('D2391') is True:
        data['posterior_composite_downgrade'] = (
            'Yes' if re.search(r'covered\s+as\s+(?:an\s+)?amalgam', _limitation('D2391'), re.IGNORECASE)
            else 'No')
    elif _covered('D2391') is False and _covered('D2160') is True:
        # Only the amalgam is paid: a composite is paid as one.
        data['posterior_composite_downgrade'] = 'Yes'
    if _covered('D2740') is True:
        data['porcelain_posterior_downgrade'] = 'Yes' if _limitation('D2740') else 'No'

    meta = normalized.get('_mo_meta') or {}

    # Whether the deductible is taken out of preventive and diagnostic work is
    # stated per code: "Yes", "No", or "NA" where no deductible applies.
    for key, source in (('ded_prev', 'ded_applies_preventative'),
                        ('ded_diag', 'ded_applies_diagnostic')):
        answer = str(meta.get(source) or '').strip().lower()
        if answer == 'yes':
            data[key] = 'Yes'
        elif answer in ('no', 'na', 'n/a'):
            data[key] = 'No'
    # A plan with no deductible takes none out of anything.
    if meta.get('deductible_zero'):
        data['ded_prev'] = 'No'
        data['ded_diag'] = 'No'

    ortho_ded = meta.get('ortho_deductible') or {}
    if ortho_ded.get('total'):
        data['ortho_ded'] = _dollar(ortho_ded.get('total'), default='0.00')
        data['ortho_ded_paid'] = _dollar(ortho_ded.get('used'), default='0.00')

    # A plan without orthodontic coverage has no orthodontic maximum or
    # deductible in any network.
    if meta.get('has_ortho') == 'No':
        for key in ('ortho_max', 'ortho_max_paid', 'ortho_ded', 'ortho_ded_paid'):
            data[key] = '0.00'

    # An export that does not state the family deductible (made before
    # content_DD_MO.js read it) leaves it unstated, rather than the shared
    # extraction's three times the individual one.
    financials = ((normalized.get('metlife_data') or {}).get('financials') or {})
    if not str((financials.get('deductible_fam') or {}).get('total') or '').strip():
        data['family_ded'] = '—'
        data['family_ded_paid'] = '—'

    if meta.get('waiting_period') == 'Yes':
        data['waiting_period'] = 'Yes'
        data['waiting_period_mo'] = '—'
    elif meta.get('waiting_period') == 'No':
        data['waiting_period'] = 'No'
        data['waiting_period_mo'] = '0'

    if meta.get('missing_tooth'):
        data['missing_tooth'] = meta['missing_tooth']

    # The portal states a date of birth for the member being read only. The
    # shared extraction would give a dependent's subscriber the dependent's own.
    subscriber = normalized.get('subscriber_info') or {}
    if not str(subscriber.get('dob') or '').strip():
        data['subscriber_dob'] = '—'
    # A dependent read without the family list (Tia Hoehne) has no subscriber
    # named in the export; the shared extraction would name the patient.
    if (str(subscriber.get('relation') or '').strip().lower() not in ('', 'self')
            and not str(subscriber.get('name') or '').strip()):
        data['subscriber_name'] = '—'

    # "Periodontal Scaling And Root Planing - Four Or More Teeth Per Quadrant"
    # is the sheet's 4 quadrants (11/10, team rule, Mahesh).
    d4341 = str((procedures.get('D4341') or {}).get('description') or '')
    if re.search(r'four\s+or\s+more\s+teeth\s+per\s+quadrant', d4341, re.IGNORECASE):
        data['d4341_number_of_quads'] = '4'
    return data
