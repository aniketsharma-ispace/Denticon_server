"""
United Concordia (unitedconcordia.com, "My Patients' Benefits").

Recognizes the export `Extension/content_ucci.js` downloads, translates it into
the shared contract, and restates UCCI's own wording ("2 Per 12 Months",
"1 Per Tooth ~ Per 5 Years", "Under 19 Years Of Age") in the forms the rest of
the system compares.

The export is one record per CDT code under `procedures`, read from the
portal's Procedure Allowance lookup (+ related procedure lookup info):

    details          Covered, Allowance, Coverage % or Copay $ (one entry per
                     line), Limitations (one entry per line), Applies to
                     Deductible / Maximum, Cost Share
    related_groups   the codes that share each limitation ("Related procedures
                     when 2 Per 12 Months applies"), with "More…" expanded
    history          the lookup's Procedure Service History: the code's own
                     rows and those of its related procedures
    policy_details   Additional Policy Details, D8080 only (the ortho age)

plus `patient_info`, `deductibles_and_maximums`, `financial_accumulators` and
`coordination_and_other_benefits` read off the benefits page itself.
"""

import re
from datetime import date

from .common import clean


def _is_ucci_portal(raw):
    """The UCCI extension export: its source, and its per-code lookups."""
    if not isinstance(raw, dict):
        return False
    return (
        str(raw.get('source') or '').strip().upper() == 'UCCI'
        and isinstance(raw.get('procedures'), dict)
    )


# ── Limitation lines ─────────────────────────────────────────────────────────
#
# UCCI prints each limitation on its own line, with qualifiers after "~":
#     "2 Per 12 Months"
#     "1 Per Tooth ~ Per 5 Years"
#     "1 Per 6 Months ~ Under 14 Years Of Age"
#     "2 Per Calendar Year ~ All Members To Any Age"
#     "1 Per Tooth ~ Per Lifetime ~ Age 18 And Older"
# and lines that are not a frequency at all:
#     "In Network", "No Coverage Due to Age Limitation", "Age 5 And Older",
#     "Permanent Teeth", "No Alternate Benefit", "--"
# A same-day cap ("4 Per Day") is a frequency, but only the governing one when
# the code states nothing else.

_PERIOD_RE = re.compile(
    r'\bper\s+(?:(?P<life>lifetime)'
    r'|(?:calendar|benefit|plan|contract)\s+(?:year|period)'
    r'|(?P<n>\d+)\s+(?P<unit>month|year)s?'
    r'|(?P<day>day))\b',
    re.IGNORECASE,
)
_NO_LIMIT_RE = re.compile(r'\bno\s+frequency\s+limitation\b', re.IGNORECASE)


def _frequency_of_line(line):
    """(sheet form, is a per-day cap) for one limitation line, or None."""
    text = clean(line)
    m = re.match(r'(\d+)\s+per\b', text, re.IGNORECASE)
    if not m:
        return None
    count = int(m.group(1))
    period = _PERIOD_RE.search(text)
    if not period:
        return None
    if period.group('life'):
        return f'{count}XLifetime', False
    if period.group('day'):
        return f'{count}X1Day', True
    if period.group('n'):
        unit = 'Months' if period.group('unit').lower() == 'month' else 'Years'
        return f'{count}X{period.group("n")}{unit}', False
    return f'{count}X1Year', False


def _age_band(line):
    """(low, high) of an age qualifier on a line, or None. Under 14 → (0, 14)."""
    text = clean(line).lower()
    m = re.search(r'\bunder\s+(\d{1,3})\s+years?\s+of\s+age\b', text) or \
        re.search(r'\bunder\s+age\s+(\d{1,3})\b', text) or \
        re.search(r'\bto\s+age\s+(\d{1,3})\b', text)
    if m:
        return 0, int(m.group(1))
    m = re.search(r'\bage\s+(\d{1,3})\s+and\s+(?:older|over)\b', text)
    if m:
        return int(m.group(1)), 999
    return None


def _in_band(age, band):
    """Whether the patient falls in a band. "Under 14" excludes 14 itself."""
    low, high = band
    if high == 999:
        return age >= low
    return low <= age < high


_UNDER_AGE_RE = re.compile(r'\bunder\s+(?:age\s+)?(\d{1,3})(?:\s+years?\s+of\s+age)?\b', re.IGNORECASE)


def _age_limit(lines):
    """
    The age limit the sheet records for the code. "Under N" is the last age
    still covered, N - 1 (team rule, 11/09): "Under 19 Years Of Age" → 0-18.
    "Age 18 And Older" → 18-99.

    A limitation can name more than one age, per tooth:
    "Under 11 Years Of Age ~ Permanent 1st Molars ~ Under 16 Years Of Age ~
    Permanent 2nd Molars". The highest one is the code's age limit (team
    rule, 11/05; the rule the other carriers follow too), so that is 0-15.
    """
    highest = None
    for line in lines:
        for m in _UNDER_AGE_RE.finditer(clean(line)):
            age = int(m.group(1))
            highest = age if highest is None else max(highest, age)
    if highest is not None:
        return f'0-{max(highest - 1, 0)}'
    for line in lines:
        band = _age_band(line)
        if band:
            low, high = band
            return f'{low}-{99 if high == 999 else high}'
    return ''


def _norm_limitation(text):
    return re.sub(r'\s+', ' ', clean(text)).strip().lower()


def _own_group_limitation(code, record, candidates):
    """
    Of several frequency lines, the one that is this code's own: the line whose
    Related Procedures group lists this code alone. A code also sits in other
    codes' groups (D0180 is in D0120's "2 Per 12 Months" group), and that
    borrowed limit is printed on its page too. Team rule (Saisanath, 11/03):
    decide from the related codes; with nothing to decide by, the first.
    """
    groups = record.get('related_groups') or []
    for line, _freq in candidates:
        wanted = _norm_limitation(line)
        for group in groups:
            if _norm_limitation(group.get('limitation')) != wanted:
                continue
            codes = {clean(c.get('code')).upper() for c in group.get('codes') or []
                     if isinstance(c, dict)}
            if codes == {code}:
                return line
    return None


def _choose_frequency(code, record, lines, age):
    """
    (frequency, why, the limitation line it came from) for the code. Team rules, in order:
      1. Lines split by age (Under 19 / Age 19 And Older): the SUBSCRIBER's band
         (team rule, 11/05), which is the adult one. `age` is the subscriber's;
         without it, the open-ended "And Older" line.
      2. Several lines otherwise: the one the related codes confirm as its own.
      3. Nothing to decide by: the first.
    """
    candidates = []
    for line in lines:
        parsed = _frequency_of_line(line)
        if parsed:
            candidates.append((line, parsed))
    if not candidates:
        if any(_NO_LIMIT_RE.search(clean(line)) for line in lines):
            return 'No Frequency', '', None
        return '', '', None

    non_daily = [(line, p) for line, p in candidates if not p[1]]
    if non_daily:
        candidates = non_daily

    if len(candidates) > 1 and any(_age_band(line) for line, _p in candidates):
        if age is not None:
            banded = [(line, p) for line, p in candidates
                      if _age_band(line) and _in_band(age, _age_band(line))]
            why = f'subscriber is {age}'
        else:
            banded = [(line, p) for line, p in candidates
                      if _age_band(line) and _age_band(line)[1] == 999]
            why = 'subscriber age unknown; the adult line'
        if banded:
            line, parsed = banded[0]
            return parsed[0], f'{why}; used "{clean(line)}"', line

    if len(candidates) > 1:
        own = _own_group_limitation(code, record, candidates)
        if own:
            parsed = next(p for line, p in candidates if line == own)
            return parsed[0], f'own limitation per related procedures: "{clean(own)}"', own
        return (candidates[0][1][0],
                f'several limitations; used the first: "{clean(candidates[0][0])}"',
                candidates[0][0])

    return candidates[0][1][0], '', candidates[0][0]


# ── Money and plan level ─────────────────────────────────────────────────────

def _money(value):
    m = re.search(r'-?\d[\d,]*(?:\.\d+)?', str(value if value is not None else ''))
    return float(m.group(0).replace(',', '')) if m else None


def _amount(number):
    return f'{number:.2f}' if number is not None else ''


_UNLIMITED = 99999.0


def _parse_dm_row(row):
    """One Deductibles and Maximums row → (benefit, amount, period, tags)."""
    benefit = clean(row.get('benefit')).lower()
    coverage = clean(row.get('coverage'))
    parts = [clean(p) for p in coverage.split('~')]
    head = parts[0] if parts else ''
    tags = [p.lower() for p in parts[1:] if p]
    if head.lower() in ('none', ''):
        return benefit, None, '', tags
    amount = _money(head)
    period = head.lower()
    return benefit, amount, period, tags


def _network_tag(tags):
    for tag in tags:
        if 'out of network' in tag:
            return 'out'
        if 'in network' in tag:
            return 'in'
    return None


def _plan_amounts(raw, network):
    """
    {annual_max, ortho_max, indiv_ded, family_ded, calendar_year} from the
    Deductibles and Maximums table. "None" is no deductible (0) or no maximum
    (unlimited). Rows tagged "~ … related" (Ortho, Accident, Implant) are
    special-purpose maximums, not the yearly one. A row tagged with the other
    network does not apply.
    """
    out = {'annual_max': None, 'ortho_max': None, 'indiv_ded': None,
           'family_ded': None, 'calendar_year': False}
    annual_candidates = []
    for row in raw.get('deductibles_and_maximums') or []:
        if not isinstance(row, dict):
            continue
        benefit, amount, period, tags = _parse_dm_row(row)
        tag_net = _network_tag(tags)
        if tag_net and tag_net != network:
            continue
        if 'calendar year' in period:
            out['calendar_year'] = True
        related = [t for t in tags if 'related' in t]
        if 'deductible' in benefit and not related:
            value = 0.0 if amount is None else amount
            if 'family' in benefit:
                out['family_ded'] = value
            elif 'individual' in benefit:
                out['indiv_ded'] = value
        elif 'maximum' in benefit and 'individual' in benefit:
            if any('ortho' in t for t in related):
                out['ortho_max'] = amount
            elif not related:
                annual_candidates.append((tag_net is not None, amount))
    if annual_candidates:
        # A row naming this network beats a plain one.
        annual_candidates.sort(key=lambda c: not c[0])
        amount = annual_candidates[0][1]
        out['annual_max'] = _UNLIMITED if amount is None else amount
    return out


def _accumulator_used(raw, kind, who=None, ortho=False):
    """
    Amount applied this benefit period, from the sidebar cards:

        PROGRAM DOLLAR DED   FAMILY      $50.00 Applied   $150.00 Total
                             INDIVIDUAL  $50.00 Applied    $50.00 Total
        PROGRAM DOLLAR MAX   INDIVIDUAL  $98.90 Applied  $1,500.00 Total

        LIFETIME SVC DOLLAR MAX   Orthodontics   $1,250.00 Applied

    `kind` is "ded" or "max", `who` "individual" or "family". A card that
    says "No deductible/maximum applied to the current benefit period" is 0.
    With no such card nothing is stated. Ortho lines are kept apart: an ortho
    amount is never the yearly one, and the other way round. A service maximum
    ("SVC DOLLAR MAX" for implants and the like) is never the yearly one.
    """
    for block in raw.get('financial_accumulators') or []:
        if not isinstance(block, dict):
            continue
        card = clean(block.get('type')).lower()
        if kind not in card:
            continue
        entries = [e for e in block.get('entries') or [] if isinstance(e, dict)]
        is_ortho_card = 'ortho' in card
        service_card = bool(re.search(r'\bsvc\b|\bservice\b', card))
        for entry in entries:
            label = clean(entry.get('label')).lower()
            entry_ortho = is_ortho_card or 'ortho' in label
            if entry_ortho != ortho:
                continue
            if service_card and not entry_ortho:
                continue
            if who and who not in label:
                continue
            amount = _money(entry.get('applied'))
            if amount is not None:
                return amount
        if not ortho and re.search(r'\bno\s+(?:deductible|maximum)\s+applied\b',
                                   clean(block.get('raw_text')).lower()):
            return 0.0
    return None


def _split_group(group_id):
    """'INTEGRATION INNOVATION INC DBA I3 405 / 926769405' → (name, number)."""
    text = clean(group_id)
    if ' / ' in text:
        name, number = text.rsplit(' / ', 1)
        return clean(name), clean(number)
    return text, ''


def _eff_date(coverage_effective):
    m = re.search(r'\d{2}/\d{2}/\d{4}', clean(coverage_effective))
    return m.group(0) if m else ''


def _age_on(dob, scraped_at):
    """Age from a MM/DD/YYYY date of birth on the day of the scrape."""
    m = re.match(r'(\d{2})/(\d{2})/(\d{4})', clean(dob))
    if not m:
        return None
    born = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    s = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(scraped_at or ''))
    on = date(int(s.group(1)), int(s.group(2)), int(s.group(3))) if s else date.today()
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def _patient_age(info, scraped_at):
    """The age the portal prints, else the age from the DOB on the day of the scrape."""
    m = re.match(r'\s*(\d{1,3})\s*$', str(info.get('age') or ''))
    if m:
        return int(m.group(1))
    return _age_on(info.get('dob'), scraped_at)


def _subscriber_age(info, scraped_at):
    """
    The subscriber's age: the patient's own when the patient is the
    subscriber, else from the subscriber DOB the Select Member list gives.
    """
    if clean(info.get('relationship')).lower() in ('self', 'subscriber', 'member'):
        return _patient_age(info, scraped_at)
    return _age_on(info.get('subscriber_dob'), scraped_at)


def _coordination_text(raw):
    return [clean(x) for x in raw.get('coordination_and_other_benefits') or [] if clean(x)]


def _missing_tooth(raw):
    for line in _coordination_text(raw):
        low = line.lower()
        if 'missing tooth' in low:
            if re.search(r'will\s+not\s+apply|does\s+not\s+apply|not\s+applicable', low):
                return 'No'
            if re.search(r'will\s+apply|applies', low):
                return 'Yes'
    return ''


def _waiting_period(raw):
    """
    Coordination and Other Benefits lists every provision the plan applies;
    a waiting period would be one of them. None listed is No.
    """
    lines = _coordination_text(raw)
    if not lines:
        return ''
    for line in lines:
        low = line.lower()
        if 'waiting' in low:
            return 'No' if re.search(r'will\s+not\s+apply|does\s+not\s+apply|\bnone\b', low) else 'Yes'
    return 'No'


def _cob(raw):
    """The coordination method, worded so the shared COB reader recognizes it."""
    for line in _coordination_text(raw):
        low = line.lower()
        if 'cob primary determination' in low or 'calculation method' in low:
            if 'non-dup' in low or 'nonduplication' in low or 'non duplication' in low:
                return 'Non-Duplication'
            if 'maintenance of benefits' in low:
                return 'Maintenance of Benefits'
            if 'carve' in low:
                return 'Carve Out'
            if 'standard' in low:
                return 'Standard'
    return ''


def _ortho_policy(record):
    """
    (age limit, payment timing) from D8080's Additional Policy Details
    (team rule, 11/05):

    - Age: the "Canceled Enrollment Benefits Cease" row.
      "Dependent ~ Age 19 And Older ~ Ortho related" → 19;
      "All Members To Any Age ~ Ortho related" → 99 (no age limit).
    - Timing: the "Reimbursement Method" row. Quarterly or monthly payments
      win over the lump sum UCCI allows for small amounts
      ("25% Initial Pay ~ Quarterly Payments ~ Lump Sum $1,000 Or Less" →
      Quarterly); a plain "Lump Sum" is the sheet's One Time.
    """
    age, timing = '', ''
    for row in (record or {}).get('policy_details') or []:
        if not isinstance(row, dict):
            continue
        kind = clean(row.get('type')).lower()
        desc = clean(row.get('description'))
        low = desc.lower()
        if 'ortho' not in low:
            continue
        if 'canceled enrollment' in kind and not age:
            m = re.search(r'age\s+(\d{1,3})\s+and\s+older', low)
            if m:
                age = m.group(1)
            elif re.search(r'to\s+any\s+age', low):
                age = '99'
        if 'reimbursement method' in kind and not timing:
            if 'quarterly' in low:
                timing = 'Quarterly'
            elif 'monthly' in low:
                timing = 'Monthly'
            elif 'lump sum' in low:
                timing = 'One Time'
    return age, timing


def _limitations(record):
    details = record.get('details') if isinstance(record.get('details'), dict) else {}
    lines = details.get('limitations')
    if isinstance(lines, str):
        lines = [lines]
    return [clean(x) for x in lines or [] if clean(x)]


def _coverage_lines(details):
    lines = details.get('coverage_lines')
    if isinstance(lines, list) and lines:
        return [clean(x) for x in lines if clean(x)]
    first = clean(details.get('coverage_or_copay'))
    return [first] if first else []


def _plan_pct(details):
    """
    The code's own percentage: the first coverage line that is not a
    "~ … related" one (ortho/accident percentages print beneath it).
    """
    for line in _coverage_lines(details):
        if 'related' in line.lower():
            continue
        m = re.match(r'(\d+(?:\.\d+)?)\s*%', line)
        if m:
            return f'{float(m.group(1)):g}%'
    return ''


def _own_group_codes(code, record, line):
    """
    The codes that share this code's own frequency: the Related Procedures
    group of the limitation its frequency came from, plus the code itself.
    """
    codes = {code}
    if not line:
        return codes
    wanted = _norm_limitation(line)
    for group in record.get('related_groups') or []:
        limitation = _norm_limitation(group.get('limitation'))
        if limitation and (limitation == wanted or limitation in wanted or wanted in limitation):
            codes |= {clean(c.get('code')).upper() for c in group.get('codes') or []
                      if isinstance(c, dict) and clean(c.get('code'))}
    return codes


def _history(record, allowed):
    """
    The dates in the lookup's service history of the codes that share this
    code's own frequency, newest first (team rule, 11/05). The lookup lists
    every related procedure that decides eligibility; only the own frequency
    group counts: D0150 takes D0120's exams (both 2 Per 12 Months), but a
    sealant does not take the fillings on the same teeth. No date is NH.
    """
    dates = []
    for row in record.get('history') or []:
        if not isinstance(row, dict):
            continue
        if clean(row.get('procedure_code')).upper() not in allowed:
            continue
        if re.match(r'\d{2}/\d{2}/\d{4}$', clean(row.get('date'))):
            dates.append(clean(row.get('date')))
    unique = list(dict.fromkeys(dates))
    unique.sort(key=lambda d: (d[6:10], d[0:2], d[3:5]), reverse=True)
    return ', '.join(unique) if unique else 'NH'


_AGE_EXCLUDED_RE = re.compile(r'no\s+coverage\s+due\s+to\s+age', re.IGNORECASE)


def _ucci_procedure(code, record, age):
    """One `procedures` record in the contract's procedure shape."""
    if record.get('error') or not isinstance(record.get('details'), dict):
        return None
    details = record['details']
    lines = _limitations(record)
    covered = clean(details.get('covered')).lower()
    # A code the plan does not cover at all can print one "Not Covered" cell
    # across the whole row instead of Covered: No.
    if covered.startswith('not covered'):
        covered = 'no'
    age_excluded = covered == 'no' and any(_AGE_EXCLUDED_RE.search(line) for line in lines)

    if covered == 'yes':
        pct = _plan_pct(details)
        if not pct and not any('$' in line for line in _coverage_lines(details)):
            # Covered, but no percentage (and no copay) in "Coverage % or
            # Copay $": the plan pays 0% (team rule, 11/05: D9243 on Kelly's
            # plan, sheet 0).
            pct = '0%'
    elif age_excluded:
        # UCCI prints 0% for a patient past the code's age limit; the plan's
        # own percentage for the code is not on the page, so it is not stated.
        pct = ''
    elif covered == 'no':
        pct = '0%'
    else:
        pct = ''

    if covered == 'no' and not age_excluded:
        frequency, why, line = 'NOT COVERED', '', None
    else:
        frequency, why, line = _choose_frequency(code, record, lines, age)
        if not frequency and covered == 'yes':
            # No frequency among the limitations ("--", or only a qualifier
            # such as "Permanent Teeth"): the sheet's "Frequency not
            # available" (team rule, 11/05: D0140, D2740, D2950, D9310 on
            # Kelly's plan).
            frequency = 'Frequency not available'
    allowed = _own_group_codes(code, record, line)

    return {
        'procedure_code': code,
        'description': clean(record.get('procedure_name')),
        'frequency_limit': frequency,
        'benefit_level': pct,
        # No age clause on a covered code is no age limit, the sheet's 99
        # (D1206 / D1208 on Kelly's plan, 11/05).
        'age_limit': _age_limit(lines) or ('0-99' if covered == 'yes' else ''),
        'late_date_of_service': _history(record, allowed),
        'number_of_quads': '',
        '_ucci_frequency_basis': why,
        '_ucci_age_excluded': age_excluded,
        '_ucci_applies_to_deductible': clean(details.get('applies_to_deductible')),
        '_ucci_applies_to_maximum': clean(details.get('applies_to_maximum')),
        '_ucci_limitations': lines,
        '_ucci_history_codes': sorted(allowed),
    }


def _alternate_benefit(record):
    """
    Whether the code is downgraded: 'Yes' where its limitations state an
    alternate benefit, 'No' where they say "No Alternate Benefit" or say
    nothing about one (team rule, 11/05: UCCI prints the alternate benefit on
    the code it applies to). '' when the code's lookup gave nothing.
    """
    lines = _limitations(record or {})
    if not isinstance((record or {}).get('details'), dict):
        return ''
    for line in lines:
        low = line.lower()
        if 'no alternate benefit' in low:
            return 'No'
        if 'alternate benefit' in low:
            return 'Yes'
    return 'No'


def _yes_no(value):
    text = clean(value).lower()
    return 'Yes' if text == 'yes' else 'No' if text == 'no' else ''


# ── Translation ──────────────────────────────────────────────────────────────

def _normalize_ucci_portal(raw):
    """Translate the UCCI export into the existing Portal contract."""
    network = 'out' if raw.get('_ucci_network') == 'out' else 'in'
    info = raw.get('patient_info') if isinstance(raw.get('patient_info'), dict) else {}
    records = {clean(k).upper(): v for k, v in (raw.get('procedures') or {}).items()
               if isinstance(v, dict)}
    age = _patient_age(info, raw.get('scraped_at'))

    sub_age = _subscriber_age(info, raw.get('scraped_at'))
    procedures = []
    for code, record in records.items():
        proc = _ucci_procedure(code, record, sub_age)
        if proc:
            procedures.append(proc)
    procs = {p['procedure_code']: p for p in procedures}

    relationship = clean(info.get('relationship')).title()
    is_self = relationship.lower() in ('self', 'subscriber', 'member')
    group_name, group_number = _split_group(info.get('group_id'))
    amounts = _plan_amounts(raw, network)
    ind_ded_used = _accumulator_used(raw, 'ded', 'individual')
    fam_ded_used = _accumulator_used(raw, 'ded', 'family')
    max_used = _accumulator_used(raw, 'max', 'individual')
    ortho_used = _accumulator_used(raw, 'max', ortho=True)
    if ortho_used is None and raw.get('financial_accumulators'):
        # The sidebar shows an Orthodontics line (LIFETIME SVC DOLLAR MAX) only
        # once something has been applied to it; read with no such line, nothing
        # has been (Riley Butler, 11/05: no card, sheet 0).
        ortho_used = 0.0

    ortho_age, ortho_timing = _ortho_policy(records.get('D8080'))

    def applies(code):
        return _yes_no((procs.get(code) or {}).get('_ucci_applies_to_deductible'))

    no_deductible = (amounts['indiv_ded'] == 0 and amounts['family_ded'] in (0, None))

    normalized = {
        '_skip_llm': True,
        '_source_insurer': 'united concordia',
        'carrier_information': {
            'name': 'United Concordia',
            'address': clean(info.get('claims_address')),
            'payer_id': clean(info.get('payor_id')),
        },
        'subscriber_info': {
            'name': clean(info.get('subscriber_name') or info.get('policyholder')),
            'dob': clean(info.get('subscriber_dob')) or ('-' if not is_self else clean(info.get('dob'))),
            'relation': relationship,
        },
        'metlife_data': {
            'patient': {
                'name': clean(info.get('patient_name')),
                'dob': clean(info.get('dob')),
                'relationship': 'Self' if is_self else relationship,
            },
            'plan_details': {
                'start_date': _eff_date(info.get('coverage_effective')),
                'end_date': '',
                'subscriber_id': clean(info.get('member_id')),
                'employer_group': group_name,
                'group_number': group_number,
                'network': clean(info.get('your_network')),
                'plan_type': clean(info.get('group_network')),
            },
            'financials': {
                'annual_max': {
                    'total': _amount(amounts['annual_max']),
                    'used': _amount(max_used),
                    'remaining': '',
                },
                'deductible_ind': {'total': _amount(amounts['indiv_ded']),
                                   'used': _amount(ind_ded_used), 'remaining': ''},
                'deductible_fam': {'total': _amount(amounts['family_ded']),
                                   'used': _amount(fam_ded_used), 'remaining': ''},
                'ortho_lifetime': {'total': _amount(amounts['ortho_max']),
                                   'used': _amount(ortho_used), 'remaining': ''},
            },
            'provider_info': {'provider_name': '', 'provider_network_status': ''},
            'covered_services': [],
            'provisions': [],
        },
        'benefit_coverage': {'procedures': procedures},
    }
    normalized['_ucci_meta'] = {
        'network': network,
        'network_status': clean(info.get('network_status')),
        'patient_age': age,
        'subscriber_age': sub_age,
        'plan_year_start': 'January' if amounts['calendar_year'] else '',
        'missing_tooth': _missing_tooth(raw),
        'waiting_period': _waiting_period(raw),
        'cob': _cob(raw),
        # Preventive = the cleaning, diagnostic = the exam; a plan with no
        # deductible applies none to either.
        'ded_prev': 'No' if no_deductible else applies('D1110'),
        'ded_diag': 'No' if no_deductible else applies('D0120'),
        # The exam's "Applies to Maximum" is whether preventive counts toward
        # the yearly maximum.
        'prev_in_max': _yes_no((procs.get('D0120') or {}).get('_ucci_applies_to_maximum')),
        'posterior_composite_downgrade': _alternate_benefit(records.get('D2391')),
        # Not compared for UCCI (team rule, 11/05): always left blank.
        'porcelain_posterior_downgrade': '',
        'ortho_age_limit': ortho_age,
        'ortho_payment_timing': ortho_timing,
        'ortho_max_present': amounts['ortho_max'] is not None,
        'deductibles_listed': amounts['indiv_ded'] is not None,
        # Ortho is a benefit of the plan when the Deductibles and Maximums list
        # an ortho maximum, even where D8080 reads Covered No for a patient past
        # the ortho age (team rule, 11/05: the sheet still records the plan's
        # ortho maximum and age). Not covered only when D8080 says so and the
        # plan lists no ortho maximum.
        'ortho_covered': ('Yes' if amounts['ortho_max'] is not None else
                          _yes_no((records.get('D8080') or {}).get('details', {}).get('covered')
                                  if isinstance((records.get('D8080') or {}).get('details'), dict) else '')),
        'failed_codes': sorted(code for code, r in records.items()
                               if r.get('error') or not isinstance(r.get('details'), dict)),
        'age_excluded_codes': sorted(code for code, p in procs.items() if p['_ucci_age_excluded']),
        'frequency_basis': {code: p['_ucci_frequency_basis'] for code, p in procs.items()
                            if p['_ucci_frequency_basis']},
        'scrape_duration_ms': raw.get('scrape_duration_ms'),
    }
    return normalized