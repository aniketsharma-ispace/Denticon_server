"""
Delta Dental.

Recognizes the provider-portal export, translates it into the shared contract,
and applies the corrections that only make sense for this carrier.
"""

import re
from datetime import datetime

from .common import _blank_present_end_date, _dollar


# ═══════════════════════════════════════════════════════════════════════════════
#  DELTA DENTAL — provider portal export
# ═══════════════════════════════════════════════════════════════════════════════
#
# Delta Dental publishes a tabbed export (overview / plan_provisions /
# benefits_search / treatment_history) with its own vocabulary. Everything the
# breakdown sheet audits is in there; it simply has to be translated into the
# contract the rest of the pipeline speaks. Nothing here touches another
# carrier's path.

_DD_WORD_COUNTS = {
    'once': 1, 'twice': 2, 'thrice': 3, 'one': 1, 'two': 2, 'three': 3,
    'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
}


# "Benefit is limited to any three oral evaluation procedures within a calendar
# year" / "limited to once per quadrant within a 24 month period" / "limited to
# either one (D0210) … or (D0330) … within a 3 year period".
_DD_FREQ_RE = re.compile(
    r'limited to\s+(?:either\s+)?(?:any\s+)?'
    r'(once|twice|thrice|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b'
    r'.*?within\s+a\s+(?:(\d+)[\s-]*)?(calendar\s+year|month|year)',
    re.IGNORECASE | re.DOTALL)


def _is_dd_portal(raw):
    """Recognize the Delta Dental provider-portal export."""
    if not isinstance(raw, dict):
        return False
    source = str(raw.get('source', '')).lower()
    tabs = raw.get('tabs')
    if not isinstance(tabs, dict):
        return False
    return 'delta dental' in source or bool(
        raw.get('primary_patient') and ('overview' in tabs or 'benefits_search' in tabs))


# How many times, out of "limited to (either) (any) <count>".
_DD_COUNT_RE = re.compile(
    r'limited to\s+(?:either\s+)?(?:any\s+)?'
    r'(once|twice|thrice|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b',
    re.IGNORECASE)


# Over what period: "within a calendar year", "within a 5 year period",
# "within two calendar years", "within a 24 month period", "within 3 calendar
# years". The count may be a digit or a word, and may be absent — "within a
# calendar year" is one year.
#
# Some programmes say "contract period" instead: "limited to two within a
# contract period", "once per tooth within a 3 contract period". A contract
# period is the plan's benefit year — the accumulation period printed on the
# annual maximum — so it counts as a year, which is how the sheet records it
# (2X1Year, 1X3Years).
#
# A few limits run over days: "limited to one problem focused evaluation
# within a 30 day period" (1X30Days). Only "N day period" is read as one — a
# bare "within 30 days of …" elsewhere in the prose is a condition on some
# other service, not this code's limit.
#
# The article varies by programme: "within a contract period" and "within the
# contract period" (Deion Reid) are the same benefit year.
_DD_PERIOD_RE = re.compile(
    r'within\s+(?:a\s+|an\s+|the\s+)?'
    r'(?:(one|two|three|four|five|six|seven|eight|nine|ten|\d+)[\s-]+)?'
    r'(?:calendar\s+|consecutive\s+)?(year|month|day(?=s?\s+period)|contract\s+period)s?',
    re.IGNORECASE)


# The two ways Delta says a procedure is not payable, plus the answer it gives
# for a code its own catalogue does not carry.
_DD_NOT_COVERED_RE = re.compile(
    r'not a benefit|could not be recognized|not a covered benefit',
    re.IGNORECASE)


def _dd_frequency(limitation):
    """
    Delta Dental's limitation prose as the compact form the sheet uses.

    "limited to any three … within a calendar year"          -> 3X1Year
    "limited to once per quadrant within a 24 month period"  -> 1X24Months
    "limited to once per quadrant within two calendar years" -> 1X2Years
    "limited to one occlusal guard within 3 calendar years"  -> 1X3Years
    "limited to two within a contract period"                -> 2X1Year
    "limited to one problem focused evaluation within a 30 day period" -> 1X30Days
    "limited to once per lifetime"                           -> 1XLifetime
    "limited to once per date of service"                    -> 1X1Day
    "this procedure has no frequency limitation"             -> No Frequency
    "benefit is based on professional determination"         -> Pre-D
    "not a benefit of most Delta Dental plans"               -> NC

    A bare "Limitations apply" is the portal keeping the real sentence behind a
    link rather than stating a limit, and yields nothing rather than a guess.

    Where the prose states several limits, each "limited to …" sentence is read
    on its own, and a limit over a period outranks a lifetime one: D9310's
    "limited to one occurrence per provider per lifetime" beside "limited to
    two of any oral evaluation procedure within a calendar year" is 2X1Year.
    """
    text = re.sub(r'\s+', ' ', str(limitation or '')).strip()
    if not text:
        return ''
    low = text.lower()

    if 'no frequency limitation' in low:
        return 'No Frequency'

    starts = [m.start() for m in _DD_COUNT_RE.finditer(text)]
    if len(starts) > 1:
        limits = [_dd_frequency(text[a:b]) for a, b in zip(starts, starts[1:] + [len(text)])]
        limits = [f for f in limits if f]
        periodic = [f for f in limits if not f.endswith('Lifetime')]
        if periodic:
            return periodic[0]
        if limits:
            return limits[0]

    match = _DD_COUNT_RE.search(text)
    word = match.group(1).lower() if match else ''
    count = (int(word) if word.isdigit() else _DD_WORD_COUNTS.get(word, 0)) if word else 0
    if not count:
        # No limit was stated, so the prose is free to be read for the two
        # things Delta says instead. A stated limit outranks both: the labial
        # veneer note, for one, says pre-treatment estimates are not a benefit
        # in the middle of describing a procedure that is limited to once per
        # tooth in five years.
        if _DD_NOT_COVERED_RE.search(low):
            return 'NC'
        if 'professional determination' in low:
            # A benefit decided case by case; the sheet writes "Pre-D".
            return 'Pre-D'
        return ''

    # Everything that qualifies the limit follows the count, and only that
    # tail is read: the sentences before it describe other procedures and
    # carry periods of their own.
    tail = text[match.end():]

    # "per lifetime" is a limit over the whole of the member's life and
    # overrides any period that follows it. A lifetime mentioned only after the
    # period belongs to a later sentence — the "Limitations apply" panel adds
    # "This procedure is a benefit once per provider per lifetime." beneath
    # D0150's "two of any oral evaluation procedure within a calendar year" —
    # and the period stands.
    period = _DD_PERIOD_RE.search(tail)
    lifetime = re.search(r'\blifetime\b', tail, re.IGNORECASE)
    if lifetime and (not period or lifetime.start() < period.start()):
        return f'{count}XLifetime'

    if period:
        span_word = (period.group(1) or '').lower()
        if not span_word:
            span = 1
        elif span_word.isdigit():
            span = int(span_word)
        else:
            span = _DD_WORD_COUNTS.get(span_word, 0)
        if not span:
            return ''
        unit = period.group(2).lower()
        if unit == 'month':
            return f'{count}X{span}Months'
        if unit == 'day':
            return f'{count}X{span}Day' if span == 1 else f'{count}X{span}Days'
        return f'{count}X{span}Year' if span == 1 else f'{count}X{span}Years'

    # "once per date of service" is a limit of one a day.
    if re.search(r'per\s+(?:date of service|day|visit)', tail, re.IGNORECASE):
        return f'{count}X1Day'
    return ''


# An age range: "age 6 to 18", "ages 6 - 18", "6 through 18".
_DD_AGE_RANGE_RE = re.compile(
    r'(\d{1,3})\s*(?:to|through|thru|-|–)\s*(?:age\s*)?(\d{1,3})\b', re.IGNORECASE)


def _dd_age_limit(text):
    """
    Delta Dental's age wording as a bound the audit can compare.

    "None" is no age restriction; "Child up to and not including age 14" and
    "12 years and older" both name the number the sheet records. A range —
    "age 6 to 18" — is recorded by its highest age, 18.
    """
    raw = str(text or '').strip()
    if not raw or raw.lower() == 'n/a':
        return ''
    # Delta Dental writes "None" where there is no age restriction, which the
    # breakdown sheet records as 99.
    if raw.lower() == 'none':
        return '99'
    span = _DD_AGE_RANGE_RE.search(raw)
    if span:
        return str(max(int(span.group(1)), int(span.group(2))))
    m = re.search(r'age\s+(\d{1,3})', raw, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'(\d{1,3})\s*years?\s+and\s+(?:older|over|up)', raw, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'(\d{1,3})', raw)
    return m.group(1) if m else ''


def _dd_not_covered(entry, row):
    """
    Whether Delta states this procedure is not payable under the plan.

    Two wordings mean it: "This procedure is not a benefit of most Delta Dental
    plans. The fee is the patient's responsibility.", and — for a code the
    plan's own catalogue does not carry — "This procedure code could not be
    recognized." Either comes with no benefit level, which is what separates
    them from a covered code whose limitation merely mentions an exclusion.

    A by-report code with no benefit level is a third: "This procedures requires
    a narrative report and description of the services provided to determine
    possible benefits." Nothing is payable as stated, and the sheet records it
    as 0% and "NC". It is matched here, behind the benefit-level check, rather
    than in the shared pattern, so a by-report code that does carry a
    percentage keeps it.
    """
    level = str((entry or {}).get('benefit_level') or '').strip().upper()
    if level not in ('', 'N/A', 'NA'):
        return False
    text = f"{(row or {}).get('limitation') or ''} {(row or {}).get('description') or ''}"
    return bool(_DD_NOT_COVERED_RE.search(text) or _DD_BY_REPORT_RE.search(text))


# Delta's wording for a code it prices only once a narrative is sent.
_DD_BY_REPORT_RE = re.compile(r'requires?\s+a\s+narrative\s+report', re.IGNORECASE)


# Delta answers a posterior composite with the amalgam benefit rather than
# with a refusal: "…it is not a benefit of the member's plan. When amalgam
# restorations are a benefit, the applicable amalgam benefit will be applied."
_DD_ALTERNATE_RE = re.compile(
    r'\b(amalgam|applicable)\b[^.]*\bbenefit will be applied', re.IGNORECASE)


# The code whose benefit is applied in place of each downgraded one.
_DD_ALTERNATE_FOR = {
    'D2391': ('D2140',),
    'D2392': ('D2150', 'D2140'),
    'D2393': ('D2160', 'D2140'),
    'D2394': ('D2161', 'D2160', 'D2140'),
}


def _dd_alternate_benefit(row):
    """Whether Delta is substituting another procedure's benefit for this one."""
    return bool(_DD_ALTERNATE_RE.search(str((row or {}).get('limitation') or '')))


def _dd_footnote(entry, which):
    """
    One of the footnotes Delta prints beneath a procedure-code card.

    The card carries superscript markers next to "Contract benefit level
    percentage covered by Delta Dental", and the page foots them out as
    "1 Amount does not apply to deductible" / "2 Amount does not apply to
    maximum". The scraper resolves the markers and publishes the answer as
    `applies_to_deductible` / `applies_to_maximum`; an export made before that
    was added carries neither, and the field stays unstated rather than
    guessed at.
    """
    value = (entry or {}).get(f'applies_to_{which}')
    text = str(value or '').strip().lower()
    if text in ('yes', 'applies', 'true'):
        return 'Yes'
    if text in ('no', 'does not apply', 'false'):
        return 'No'
    return ''


def _dd_deductible_applies(entry):
    """
    Whether the deductible comes out of this code's work, as the BPO reads it.

    Delta states only the exception — "Amount does not apply to deductible"
    footed against the card — so a card that says nothing means the deductible
    applies. The scraper leaves `applies_to_deductible` empty when no footnote
    list rendered for the search, which Delta does only when no card in it
    carried a marker; that silence is therefore a "Yes". An export without the
    key at all predates the footnote reader and stays unstated.
    """
    stated = _dd_footnote(entry, 'deductible')
    if stated:
        return stated
    if isinstance(entry, dict) and 'applies_to_deductible' in entry:
        return 'Yes'
    return ''


def _dd_waiting_rows(waiting):
    """
    The waiting-period rows, whichever shape the export carries.

    Older builds publish the tab as a bare list of rows; newer ones wrap it as
    {"rows": [...], "note": ...} so an empty table can say why it is empty.
    """
    if isinstance(waiting, dict):
        rows = waiting.get('rows')
    else:
        rows = waiting
    return [r for r in (rows or []) if isinstance(r, dict)]


def _dd_date(text):
    """A date Delta printed, as a date object; None where it printed none."""
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', str(text or ''))
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day).date()
    except ValueError:
        return None


def _dd_age_ceiling(text):
    """
    How high the age band reaches, for choosing between a code's rows.

    Delta lists a procedure once per age band — "Child up to and not including
    age 9" beside "Child up to and not including age 16", or an adult band
    "18 years and older" beside a child one. The sheet records the highest
    band, so a band with no upper bound ranks above every bounded one.
    """
    raw = str(text or '').strip()
    if not raw or raw.lower() in ('none', 'n/a'):
        return float('inf')
    span = _DD_AGE_RANGE_RE.search(raw)
    if span:
        return max(int(span.group(1)), int(span.group(2)))
    m = re.search(r'up to(?:\s+and\s+not\s+including)?\s+age\s+(\d{1,3})', raw, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'(?:through|to)\s+age\s+(\d{1,3})', raw, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # "18 years and older" and "12 years and older" state a floor, not a
    # ceiling — the band runs to the end of the member's life.
    if re.search(r'\d{1,3}\s*years?\s+and\s+(?:older|over|up)', raw, re.IGNORECASE):
        return float('inf')
    m = re.search(r'age\s+(\d{1,3})', raw, re.IGNORECASE)
    return int(m.group(1)) if m else float('inf')


def _dd_member_class(row):
    """
    Which members a row's limit is written for, as a rank.

    Delta splits a limit by member class and says so at the end of the
    sentence — "…rampant caries.For Dependents." beside the same sentence
    ending "…For Subscriber and Spouse." The breakdown sheet always records
    the subscriber's, so that row ranks highest and a dependents-only row
    lowest; a row that names no class sits between them and is used wherever
    no class is stated at all.
    """
    text = f"{(row or {}).get('limitation') or ''} {(row or {}).get('description') or ''}".lower()
    if re.search(r'for\s+subscriber', text):
        return 1
    if re.search(r'for\s+dependent', text):
        return -1
    return 0


def _dd_best_row(rows):
    """
    The row of a code that governs, where Delta states more than one.

    Rows are split either by member class or by age band. The subscriber's row
    wins outright; between rows of the same class the highest age band wins,
    which is the band an adult subscriber falls in and the one the breakdown
    sheet records.
    """
    usable = [r for r in (rows or []) if isinstance(r, dict)]
    if not usable:
        return {}
    return max(usable, key=lambda r: (_dd_member_class(r),
                                      _dd_age_ceiling(r.get('age_limits'))))


def _dd_subscriber_card(raw, patient, member_type):
    """
    The card holding the subscriber's own details.

    Where the patient is the subscriber that is the patient's card. Where the
    patient is a dependent the subscriber is named on the Family members tab,
    under its "Subscriber" heading, and is the only place the portal states
    them — the page-wide field scrape leaves `subscriber_name` as "N/A".
    """
    if 'subscriber' in str(member_type or '').lower():
        return patient
    for card in ((raw.get('tabs') or {}).get('family_members') or []):
        if not isinstance(card, dict):
            continue
        if 'subscriber' in _dd_static(card, 'Member type').lower():
            return card
    return {}


def _dd_ortho_only(record):
    """
    Whether a deductible record stands for orthodontics alone.

    Most plans fold orthodontics into the ordinary deductible, listing it
    beside Restorative, Endodontics and the rest — that record is the general
    one and mentioning orthodontics does not make it otherwise. A separate
    orthodontic deductible covers nothing else: "Orthodontics" on its own, or
    with the surgical work that goes with it.
    """
    types = [str(t).lower() for t in ((record or {}).get('treatment_types') or [])]
    if not any('orthodont' in t for t in types):
        return False
    return all('orthodont' in t or 'maxillofacial' in t for t in types)


def _dd_static(patient, *labels):
    """A labelled value out of the portal's static field block."""
    fields = patient.get('static_fields') if isinstance(patient, dict) else None
    if not isinstance(fields, dict):
        return ''
    lowered = {str(k).strip().lower(): v for k, v in fields.items()}
    for label in labels:
        value = lowered.get(label.strip().lower())
        if value not in (None, '', 'N/A'):
            return str(value).strip()
    return ''


def _dd_money(value):
    """Delta Dental prints money already formatted; keep it as stated."""
    text = str(value or '').strip()
    return text if text and text.upper() != 'N/A' else ''


def _dd_network_kind(label):
    """Which provider network a Delta label names: ppo, premier, non-delta, …"""
    low = str(label or '').lower()
    if re.search(r'non[-\s]?delta', low):
        return 'non-delta'
    for kind in ('ppo', 'premier', 'dpo', 'dhmo', 'hmo', 'epo'):
        if re.search(rf'\b{kind}\b', low):
            return kind
    return ''


def _dd_for_network(records, network):
    """
    The records that apply to the network being audited.

    Delta may split a maximum by provider network — $1,700 for "Delta Dental
    PPO Dentist" beside $1,500 for "Delta Dental Premier Dentist" and
    "Non-Delta Dental Dentist" — and the sheet records the one for the network
    Benefits Search was answered under. Where the network is unknown, or no
    record names it, every record stays in play.
    """
    kind = _dd_network_kind(network)
    if not kind:
        return records
    matching = [r for r in records
                if any(_dd_network_kind(n) == kind for n in (r.get('networks') or []))]
    return matching or records


def _dd_amount(value):
    """A printed dollar amount as a number, for choosing between records."""
    m = re.search(r'\d[\d,]*(?:\.\d+)?', str(value or ''))
    return float(m.group(0).replace(',', '')) if m else 0.0


def _dd_maximum(maximums, *, lifetime, network=''):
    """
    The annual or lifetime maximum record.

    Delta Dental labels them "Calendar Individual Maximum …" and "Lifetime
    Individual Maximum", each naming the treatment types it covers — which is
    also what answers whether preventive draws the annual maximum down.

    A plan may carry more than one annual maximum: a narrow one covering a
    single category (Diagnostic, $1,250) beside the general one covering every
    service the plan pays for (eleven categories, $2,500). The sheet's "Yearly
    Max" is the general one, so the record naming the most treatment types
    wins; where there is only one maximum this is simply that maximum. Where
    the maximum is split by provider network, only the network being audited
    is considered (`_dd_for_network`).

    The lifetime maximum the sheet records is the orthodontic one. A plan may
    list several — TMJ $500, and Orthodontics $1,500 beside another
    Orthodontics $500 — and the sheet takes the highest of those naming
    Orthodontics. A plan whose lifetime maximums name no orthodontics gives
    its first lifetime maximum, as before.
    """
    candidates = []
    for record in maximums or []:
        if not isinstance(record, dict):
            continue
        kind = str(record.get('type', '')).lower()
        if lifetime and 'lifetime' in kind:
            candidates.append(record)
        if not lifetime and 'lifetime' not in kind and 'maximum' in kind:
            candidates.append(record)
    if not candidates:
        return {}
    if lifetime:
        ortho = [r for r in candidates
                 if any('orthodont' in str(t).lower() for t in (r.get('treatment_types') or []))]
        if not ortho:
            return candidates[0]
        return max(_dd_for_network(ortho, network), key=lambda r: _dd_amount(r.get('amount')))
    return max(_dd_for_network(candidates, network),
               key=lambda r: len(r.get('treatment_types') or []))


def _normalize_dd_portal(raw):
    """
    Translate the Delta Dental export into the established Portal contract.

    No Denticon values are introduced here; every field comes from the export.
    """
    tabs = raw.get('tabs') or {}
    overview = tabs.get('overview') or {}
    patient = raw.get('primary_patient') or {}
    eligibility = raw.get('eligibility') or {}

    # ── identity ───────────────────────────────────────────────────────────
    # The portal appends programme tags to the name ("… SmileWay participant").
    name = re.sub(r'\s+smileway\s+participant\s*$', '',
                  str(patient.get('name') or ''), flags=re.IGNORECASE).strip()
    # The patient's own card is read first. `eligibility` is a page-wide sweep
    # of every label/value pair, collapsed into one dictionary, so on a
    # dependent's page — which also shows the subscriber's card — the last
    # "Date of birth" on the page wins and the patient would inherit the
    # subscriber's. The card belongs to one member and cannot be confused.
    def _member_field(label, fallback_key):
        from_card = _dd_static(patient, label)
        if from_card:
            return from_card
        value = eligibility.get(fallback_key)
        return '' if value in (None, '', 'N/A') else str(value).strip()

    dob = _member_field('Date of birth', 'patient_dob')
    member_type = _dd_static(patient, 'Member type') or 'Subscriber'
    group_number = _member_field('Group number', 'group_number')

    # A dependent's subscriber is named only on the Family members tab.
    subscriber_card = _dd_subscriber_card(raw, patient, member_type)

    # Delta numbers a family once and gives each member a suffix — …01 for the
    # subscriber, …02 for a dependent. The sheet's "Member ID#" is the policy
    # number claims are filed under, which is the subscriber's; for a
    # subscriber that is their own card, so this is the same number either way.
    member_id = (_dd_static(subscriber_card, 'Member ID')
                 or _member_field('Member ID', 'member_id'))
    subscriber_name = re.sub(r'\s+smileway\s+participant\s*$', '',
                             str(subscriber_card.get('name') or ''),
                             flags=re.IGNORECASE).strip()
    subscriber_dob = _dd_static(subscriber_card, 'Date of birth')
    if not subscriber_name:
        value = eligibility.get('subscriber_name')
        subscriber_name = '' if value in (None, '', 'N/A') else str(value).strip()
    if not subscriber_dob:
        value = eligibility.get('subscriber_dob')
        subscriber_dob = '' if value in (None, '', 'N/A') else str(value).strip()

    # "Member eligibility: 11/01/2024 - present"
    coverage = _dd_static(patient, 'Member eligibility')
    start_date = end_date = ''
    if coverage:
        parts = [p.strip() for p in re.split(r'\s*-\s*', coverage, maxsplit=1)]
        start_date = parts[0] if parts else ''
        end_date = _blank_present_end_date(parts[1]) if len(parts) > 1 else ''

    # ── claims address and payer id ────────────────────────────────────────
    address_lines = [str(x).strip() for x in (overview.get('claims_mailing_address') or [])]
    payer_id = ''
    address_parts = []
    for line in address_lines:
        m = re.search(r'payer\s*id\s*:?\s*(\S+)', line, re.IGNORECASE)
        if m:
            payer_id = m.group(1).strip()
            continue
        if line and 'delta dental' not in line.lower():
            address_parts.append(line)

    # ── maximums and deductibles ───────────────────────────────────────────
    maximums = overview.get('maximums') or []
    # The network Benefits Search was answered under — the plan's own, or
    # "Non-Delta Dental Dentist" for an out-of-network office — also decides
    # which maximum applies where Delta splits them by network. An export made
    # before the network was recorded was searched under the plan's own
    # network ("Delta Dental PPO" → PPO), which is what the extension's
    # in-network pass still chooses.
    network = str(tabs.get('benefits_search_network') or patient.get('plan') or '')
    annual = _dd_maximum(maximums, lifetime=False, network=network)
    lifetime = _dd_maximum(maximums, lifetime=True, network=network)

    # The treatment types the annual maximum covers answer "Preventative
    # Included in Yearly Max?" the same way MetLife's Annual card does.
    annual_types = ', '.join(str(t) for t in (annual.get('treatment_types') or []))

    # A procedure-code card may foot out an exception to that list — "Amount
    # does not apply to maximum" against D0120 — which overrides the category
    # line for preventive services. Absent that footnote the category line
    # stands, which is the portal's own statement either way.
    _search = tabs.get('benefits_search') or []
    _by_code = {str(e.get('code') or '').upper(): e for e in _search if isinstance(e, dict)}
    if _dd_footnote(_by_code.get('D0120'), 'maximum') == 'No':
        annual_types = ', '.join(
            t for t in (str(x) for x in (annual.get('treatment_types') or []))
            if 'preventive' not in t.lower() and 'preventative' not in t.lower())

    deductibles = overview.get('deductibles') or []

    def _as_amounts(record):
        return {'total': _dd_money(record.get('amount')),
                'used': _dd_money(record.get('used')),
                'remaining': _dd_money(record.get('remaining'))}

    def _deductible(kind):
        # A plan may carry a separate orthodontic deductible, listed as another
        # "Calendar Individual Deductible" naming Orthodontics among its
        # treatment types. It is not the deductible the general work draws on,
        # so it is passed over here and read on its own below.
        for record in deductibles:
            if not isinstance(record, dict) or _dd_ortho_only(record):
                continue
            if kind in str(record.get('type', '')).lower():
                return _as_amounts(record)
        # An empty deductible table is the portal stating there is none.
        if not deductibles:
            return {'total': '$0.00', 'used': '$0.00', 'remaining': '$0.00'}
        return {'total': '', 'used': '', 'remaining': ''}

    def _ortho_deductible():
        individual = [r for r in deductibles
                      if isinstance(r, dict) and _dd_ortho_only(r)
                      and 'individual' in str(r.get('type', '')).lower()]
        either = individual or [r for r in deductibles
                                if isinstance(r, dict) and _dd_ortho_only(r)]
        return _as_amounts(either[0]) if either else {}

    # ── category coverage, in and out of network ───────────────────────────
    covered_services = []
    for row in overview.get('benefits_overview') or []:
        if not isinstance(row, dict):
            continue
        treatment = str(row.get('treatment_type') or '').strip()
        if not treatment:
            continue
        covered_services.append({
            'category': treatment.upper(),
            'in_network': str(row.get('contract_benefit_level') or '').strip(),
            'out_of_network': str(row.get('non_delta_dental') or '').strip(),
            'services': treatment,
        })

    # ── provisions ─────────────────────────────────────────────────────────
    provisions = []
    for row in tabs.get('plan_provisions') or []:
        if not isinstance(row, dict) or not row.get('provision_name'):
            continue
        rule = str(row.get('provision_name'))
        value = str(row.get('description') or '')
        lowered = rule.lower()

        # Published under the name the shared contract looks for.
        if lowered.startswith('cob'):
            rule = 'Coordination of Benefits Rule'

        # Delta states the missing-tooth position in its own words; translated
        # into the sentence the shared parser reads, keeping the original after
        # it so nothing is lost.
        if 'missing tooth' in lowered:
            included = re.search(r'\bare included\b|\bis included\b', value, re.IGNORECASE)
            excluded = re.search(r'\bnot included\b|\bare excluded\b|\bnot covered\b',
                                 value, re.IGNORECASE)
            if included and not excluded:
                value = ('Are plan benefits available for teeth lost prior to '
                         'effective date: Yes. ' + value)
            elif excluded:
                value = ('Are plan benefits available for teeth lost prior to '
                         'effective date: No. ' + value)

        provisions.append({'rule': rule, 'value': value})

    # The accumulation period is printed on the annual maximum itself —
    # "Calendar Individual Maximum Accumulation period for this program
    # (1/1/2026 - 12/31/2026)" — and is the only statement of when the plan
    # year turns over. Published as a Benefit Period provision so the shared
    # reader prefers it over the member's effective date, which is merely when
    # this member joined.
    period = re.search(r'\((\d{1,2}/\d{1,2}/\d{2,4})\s*-\s*(\d{1,2}/\d{1,2}/\d{2,4})\)',
                       str(annual.get('type') or ''))
    if period:
        kind = 'CALENDAR YEAR' if 'calendar' in str(annual.get('type') or '').lower() else 'PLAN YEAR'
        provisions.append({
            'rule': 'Benefit Period',
            'value': f'{kind} Start Date: {period.group(1)} End Date: {period.group(2)}',
        })

    # ── service history, shared across codes ───────────────────────────────
    # A Delta limitation covers a set of codes and names them: "Limitation may
    # also apply to: D0210". A service date recorded against one of them counts
    # against the whole set, which is why the sheet shows the panoramic date on
    # the FMX row and the fluoride dates on both fluoride codes. The dates are
    # therefore pooled per code before being published.
    history_by_code = {}
    for entry in (tabs.get('treatment_history') or {}).get('procedures') or []:
        if not isinstance(entry, dict) or not entry.get('code'):
            continue
        owner = str(entry['code']).upper().strip()
        for row in entry.get('rows') or []:
            if not isinstance(row, dict):
                continue
            dates = [d for d in re.findall(r'\d{1,2}/\d{1,2}/\d{2,4}',
                                           str(row.get('service_date') or ''))]
            if not dates:
                continue
            shared = {owner}
            also = str(row.get('limitation_may_also_apply_to') or '')
            shared.update(re.findall(r'\bD\d{4}\b', also.upper()))
            for code in shared:
                history_by_code.setdefault(code, [])
                for date in dates:
                    if date not in history_by_code[code]:
                        history_by_code[code].append(date)

    # ── per-code benefits ──────────────────────────────────────────────────
    procedures = []
    for entry in tabs.get('benefits_search') or []:
        if not isinstance(entry, dict) or not entry.get('code'):
            continue
        # Where Delta states a code once per age band, the highest band is
        # the one the sheet records; the service dates belong to the code
        # whichever band they were recorded under, so they come from them all.
        row = _dd_best_row(entry.get('rows')) or {}
        code = str(entry.get('code')).upper().strip()
        own = []
        for r in (entry.get('rows') or []):
            if not isinstance(r, dict):
                continue
            for d in re.findall(r'\d{1,2}/\d{1,2}/\d{2,4}',
                                str(r.get('service_date') or '')):
                # Delta repeats a code's history under every age band it
                # states, so the same date arrives once per row.
                if d not in own:
                    own.append(d)
        pooled = list(own)
        for date in history_by_code.get(code, []):
            if date not in pooled:
                pooled.append(date)
        service_date = ', '.join(pooled)
        # A code the plan does not pay for is stated as such rather than left
        # blank: the sheet records those as 0% and "NC", and a blank would read
        # as the portal never having mentioned the code at all. A code whose
        # benefit is merely substituted is not one of them — the patient has a
        # benefit, stated against another code, and it is filled in below.
        not_covered = _dd_not_covered(entry, row) and not _dd_alternate_benefit(row)
        procedures.append({
            'procedure_code': str(entry.get('code')).upper().strip(),
            'description': str(row.get('description') or ''),
            'benefit_level': ('Not Covered' if not_covered
                              else str(entry.get('benefit_level') or '').strip()),
            'frequency_limit': ('NC' if not_covered
                                else _dd_frequency(row.get('limitation'))),
            'age_limit': _dd_age_limit(row.get('age_limits')),
            # "None" is the portal stating the procedure has never been
            # performed — the dash the rest of the pipeline reads as such.
            'late_date_of_service': ('\u2014' if service_date.lower() in ('none', '')
                                     else service_date),
            'deductible': str(entry.get('deductible') or ''),
            'limitation': str(row.get('limitation') or ''),
            # Paid only at another code's benefit — D2391 "is not a benefit of
            # the member's plan … the applicable amalgam benefit will be
            # applied". The downgrade question reads this.
            'alternate_benefit': _dd_alternate_benefit(row),
        })

    # A downgraded procedure carries the benefit of the code it is downgraded
    # to — the portal says so outright — so that benefit is filled in once
    # every code has been read and the substitute can be looked up.
    by_code = {p['procedure_code']: p for p in procedures}
    for entry in tabs.get('benefits_search') or []:
        if not isinstance(entry, dict) or not entry.get('code'):
            continue
        code = str(entry['code']).upper().strip()
        record = by_code.get(code)
        if not record or not _dd_alternate_benefit(_dd_best_row(entry.get('rows'))):
            continue
        for substitute in _DD_ALTERNATE_FOR.get(code, ()):
            source = by_code.get(substitute)
            level = str((source or {}).get('benefit_level') or '').strip()
            if not source or not level or level.upper() in ('N/A', 'NA'):
                continue
            record['benefit_level'] = level
            record['frequency_limit'] = source.get('frequency_limit') or ''
            record['alternate_benefit_from'] = substitute
            break

    plan_name = str(patient.get('plan') or 'Delta Dental').strip()

    return {
        '_skip_llm': True,
        '_source_insurer': 'delta dental',
        'carrier_information': {
            # The plan label names the carrier on most programmes ("Delta
            # Dental PPO") but on some is only the network code ("DPO"), which
            # is not a carrier name at all — the sheet says "Delta Dental GA".
            'name': (plan_name if 'delta' in plan_name.lower() else 'Delta Dental'),
            'payer_id': payer_id,
            'address': ', '.join(address_parts),
        },
        'subscriber_info': {
            'name': subscriber_name,
            'dob': subscriber_dob,
            'relation': member_type,
        },
        'metlife_data': {
            'patient': {'name': name, 'dob': dob, 'relationship': member_type},
            'plan_details': {
                'start_date': start_date,
                'end_date': end_date,
                'subscriber_id': member_id,
                'employer_group': str(patient.get('group') or eligibility.get('group_name') or ''),
                'group_number': group_number,
                'network': plan_name,
                'plan_type': plan_name,
            },
            'financials': {
                'annual_max': {
                    'total': _dd_money(annual.get('amount')),
                    'used': _dd_money(annual.get('used')),
                    'remaining': _dd_money(annual.get('remaining')),
                    'description': annual_types,
                },
                'deductible_ind': _deductible('individual'),
                'deductible_fam': _deductible('family'),
                'ortho_lifetime': {
                    'total': _dd_money(lifetime.get('amount')),
                    'used': _dd_money(lifetime.get('used')),
                    'remaining': _dd_money(lifetime.get('remaining')),
                    'category': ', '.join(str(t) for t in (lifetime.get('treatment_types') or [])),
                },
            },
            'provider_info': {'provider_name': '', 'provider_network_status': ''},
            'covered_services': covered_services,
            'provisions': provisions,
        },
        'benefit_coverage': {'procedures': procedures},
        '_dd_meta': {
            'annual_treatment_types': annual.get('treatment_types') or [],
            'lifetime_treatment_types': lifetime.get('treatment_types') or [],
            'deductible_applicability': overview.get('deductible_applicability') or {},
            'ded_applies_preventative': _dd_deductible_applies(_by_code.get('D0120')),
            'ded_applies_diagnostic': _dd_deductible_applies(_by_code.get('D0220')),
            'ortho_deductible': _ortho_deductible(),
            'waiting_period_rows': _dd_waiting_rows(tabs.get('waiting_periods')),
            'claims_address_lines': address_lines,
            'procedure_count': len(procedures),
        },
    }


def _apply_dd_output_rules(data, normalized):
    """
    Delta Dental corrections applied after the shared extraction.

    The sheet's Preventative / Basic / Major rows name procedure codes (D0120,
    D2160, D2740), and Delta publishes an exact percentage per code. The
    category table gives ranges instead — "Restorative 60% - 80%" — from which
    the shared extraction takes the lower end and reports 60% where the code
    itself says 80%. The per-code value is the accurate one.
    """
    procedures = {
        str(p.get('procedure_code', '')).upper(): p
        for p in ((normalized.get('benefit_coverage') or {}).get('procedures') or [])
    }

    def _level(*codes):
        for code in codes:
            level = str((procedures.get(code) or {}).get('benefit_level') or '').strip()
            if level and level.upper() not in ('N/A', 'NA'):
                return level
        return ''

    for key, codes in (
        ('pct_prev', ('D0120', 'D1110', 'D0150')),
        ('pct_basic', ('D2160', 'D2140', 'D2331', 'D2391')),
        ('pct_major', ('D2740', 'D6750', 'D5110')),
    ):
        level = _level(*codes)
        if level:
            data[key] = level

    def _covered(code):
        """Three-valued: covered, not covered, or never stated."""
        record = procedures.get(code)
        if record is None:
            return None
        level = str(record.get('benefit_level') or '').strip()
        if not level or level.upper() in ('N/A', 'NA'):
            return None
        return 'not covered' not in level.lower()

    # Delta does not carry an Alternate Benefits provision; it answers the two
    # downgrade questions through the codes themselves. A posterior composite
    # is downgraded to its amalgam equivalent exactly when the plan pays for
    # one of the pair and not the other, so both codes have to be stated
    # before the question can be answered at all.
    #
    # A composite Delta pays only at the amalgam benefit is not a benefit of
    # the plan in its own right — it is exactly the downgrade being asked
    # about — even though its percentage is filled in from the amalgam code.
    def _paid_as_itself(code):
        if (procedures.get(code) or {}).get('alternate_benefit'):
            return False
        return _covered(code)

    amalgam, composite = _paid_as_itself('D2160'), _paid_as_itself('D2391')
    if amalgam is not None and composite is not None:
        data['posterior_composite_downgrade'] = 'No' if (amalgam and composite) else 'Yes'

    # A posterior crown is not downgraded where major services are paid for.
    # Where they are not, the portal says nothing about a downgrade and the
    # sheet is left blank, so nothing is published either.
    if _covered('D2740') is True:
        data['porcelain_posterior_downgrade'] = 'No'

    # Whether the deductible is taken out of preventive and diagnostic work is
    # footed out under the D0120 and D0220 cards.
    meta = normalized.get('_dd_meta') or {}
    for key, source in (('ded_prev', 'ded_applies_preventative'),
                        ('ded_diag', 'ded_applies_diagnostic')):
        answer = meta.get(source)
        if answer:
            data[key] = answer

    # A plan may hold a deductible for orthodontics alone, separate from the
    # one the general work draws on. Where there is none the shared default of
    # zero already says so.
    ortho_ded = meta.get('ortho_deductible') or {}
    if ortho_ded.get('total'):
        data['ortho_ded'] = _dollar(ortho_ded.get('total'), default='0.00')
        data['ortho_ded_paid'] = _dollar(ortho_ded.get('used'), default='0.00')

    # Delta gives waiting periods a tab of their own, one row per group of
    # procedures with the dates the wait begins and ends. A row whose end date
    # is still ahead is a wait the patient is serving; where every row has run
    # out there is no wait left to serve. An absent table says nothing, and the
    # shared default stands.
    rows = meta.get('waiting_period_rows') or []
    periods = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ends = _dd_date(row.get('waiting_period_ends'))
        if not ends:
            continue
        begins = _dd_date(row.get('waiting_period_begins'))
        categories = []
        for item in row.get('treatments_and_procedures') or []:
            if not isinstance(item, dict):
                continue
            # "Restorative D2140, D2150, …" — the category, then its codes.
            label = re.split(r'\s+D\d{4}', str(item.get('treatment_type') or ''))[0].strip()
            if label and label not in categories:
                categories.append(label)
        periods.append((ends, begins, categories))

    if periods:
        today = datetime.now().date()
        outstanding = [p for p in periods if p[0] > today]
        data['waiting_period'] = 'Yes' if outstanding else 'No'
        if outstanding:
            # The longest of the waits still running is the one that governs.
            ends, begins, _ = max(outstanding, key=lambda p: p[0])
            if begins:
                months = round((ends - begins).days / 30.44)
                data['waiting_period_mo'] = str(months)
            applies = []
            for _, _, categories in outstanding:
                for label in categories:
                    if label not in applies:
                        applies.append(label)
            if applies:
                # The cell holds a line; naming nine categories shrinks it out
                # of legibility, so the rest are counted instead of listed.
                data['applies_to'] = (', '.join(applies) if len(applies) <= 3 else
                                      ', '.join(applies[:3]) + f' +{len(applies) - 3} more')
        else:
            data['waiting_period_mo'] = '0'
    return data
