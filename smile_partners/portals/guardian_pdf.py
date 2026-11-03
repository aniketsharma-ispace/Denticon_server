"""
Guardian's Dental Eligibility page, saved from the browser as a PDF.

It is the same page `Extension/content_guardian.js` reads, so it is read here
into the same shape the extension downloads — plan_information, deductibles,
plan_allowance, plan_options, procedure_codes — and audited by
`sabrina/carriers/guardian/` exactly like the extension's JSON.

The printout is laid out as tables whose text extracts out of order (sticky
column headers, cells wrapping mid-word: "In-" / "Netwo" / "rk"), so every
cell is placed by its position under its column header, never by text order.

The per-code records are derived from the Plan Options rows by a port of the
extension's own derivation (`deriveLocalProcedureRecord` and what it calls in
content_guardian.js), so a printout and the extension's JSON of the same
patient give the same records. Keep the two in step: a rule changed there
belongs here too. The printout has no CDT code search, so the codes that need
one (D1510, D2980, D4260, D7140, D7210, D9944) are left out and read "not on
portal".
"""

import re
from datetime import date, datetime

from .common import clean


# ══════════════════════════════════════════════════════════════════════════════
#  READING THE PRINTOUT
# ══════════════════════════════════════════════════════════════════════════════

_FURNITURE_TOP = 30       # browser header: print time, page title
_FURNITURE_BOTTOM = 40    # browser footer: URL, "3/12"
_COLUMN_SLACK = 6         # a cell may start a little left of its header


def _is_guardian_eligibility_text(text):
    """Whether a PDF's text is Guardian's Dental Eligibility page."""
    t = clean(text).lower()
    return ('guardian' in t and 'dental eligibility' in t
            and 'plan options' in t and 'benefit period' in t)


def _document_lines(doc):
    """
    Every text line of the printout as (y, x0, x1, text, page), with y running
    on across pages so a table continuing onto the next page stays in order.
    """
    lines = []
    offset = 0.0
    for pno, page in enumerate(doc):
        height = page.rect.height
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', []):
                text = clean(' '.join(span['text'] for span in line['spans']))
                x0, y0, x1, _y1 = line['bbox']
                if not text or y0 < _FURNITURE_TOP or y0 > height - _FURNITURE_BOTTOM:
                    continue
                lines.append((offset + y0, x0, x1, text, pno))
        offset += height
    lines.sort(key=lambda ln: (round(ln[0], 1), ln[1]))
    return lines


def _document_words(doc):
    """Every word as (y, x0, text), on the same running y as the lines."""
    words = []
    offset = 0.0
    for page in doc:
        for x0, y0, _x1, _y1, text, *_ in page.get_text('words'):
            words.append((offset + y0, x0, text))
        offset += page.rect.height
    return words


def _first(lines, pattern, after=-1.0):
    """The first line below `after` whose text matches."""
    regex = re.compile(pattern, re.IGNORECASE)
    return next((ln for ln in lines if ln[0] > after and regex.search(ln[3])), None)


def _value_below(lines, label):
    """
    The value printed under a label ("Benefit period" / "January 01 to
    December 31"): the next line starting at the label's x.
    """
    head = next((ln for ln in lines if ln[3].lower() == label.lower()), None)
    if head is None:
        return ''
    below = [ln for ln in lines
             if 0 < ln[0] - head[0] <= 40 and abs(ln[1] - head[1]) <= 5]
    return below[0][3] if below else ''


def _columns_from_words(words, labels, y_from, y_to):
    """
    The x where each header starts, matching `labels` left to right among the
    header words between y_from and y_to (a label may repeat: two
    "Remaining" columns under Plan maximums).
    """
    band = sorted((w for w in words if y_from <= w[0] <= y_to), key=lambda w: w[1])
    columns = []
    i = 0
    for _y, x0, text in band:
        if i < len(labels) and text.lower().startswith(labels[i][1].lower()):
            if not columns or x0 - columns[-1][1] > 5:
                columns.append((labels[i][0], x0))
                i += 1
    return columns


def _column_of(x0, columns):
    """The column a cell starting at x0 sits under."""
    name = None
    for col, start in columns:
        if x0 >= start - _COLUMN_SLACK:
            name = col
    return name


def _cells(lines, gap=25.0):
    """Lines of one column split into cells wherever a gap opens up."""
    cells = []
    for ln in lines:
        if cells and ln[0] - cells[-1][-1][0] <= gap:
            cells[-1].append(ln)
        else:
            cells.append([ln])
    return cells


def _join_words(parts):
    """Wrapped lines joined: a word cut mid-way rejoins, others get a space."""
    out = ''
    for part in parts:
        if not out:
            out = part
        elif re.search(r'[A-Za-z/]$', out) and re.match(r'[a-z/]', part):
            out += part
        elif out.endswith('/') or part.startswith('/'):
            out += part
        else:
            out += ' ' + part
    return out


def _join_prose(parts):
    """Wrapped prose joined; a line ending in a hyphenated word continues it."""
    out = ''
    for part in parts:
        if not out:
            out = part
        elif re.search(r'\S-$', out):
            out += part
        else:
            out += ' ' + part
    return out


def _table_rows(lines, columns, anchor, y_from, y_to):
    """
    Rows of a small table (Deductibles, Plan maximums): one per cell of the
    anchor column, every other cell joining the row its middle falls in. A
    cell printed once for two rows (Coverage "Individual Dental") lands in the
    first; `_fill_down` carries it on.
    """
    body = [ln for ln in lines if y_from < ln[0] < y_to]
    by_col = {}
    for ln in body:
        by_col.setdefault(_column_of(ln[1], columns), []).append(ln)
    anchors = _cells(by_col.get(anchor, []))
    rows = []
    for i, cell in enumerate(anchors):
        bottom = anchors[i + 1][0][0] - 12 if i + 1 < len(anchors) else y_to
        rows.append(({anchor: ' '.join(c[3] for c in cell)}, cell[0][0] - 12, bottom))
    for col, col_lines in by_col.items():
        if col in (anchor, None):
            continue
        for cell in _cells(col_lines):
            middle = (cell[0][0] + cell[-1][0]) / 2
            row = next((r for r, top, bottom in rows if top <= middle < bottom), None)
            if row is not None:
                row.setdefault(col, ' '.join(c[3] for c in cell))
    return [r for r, _top, _bottom in rows]


def _fill_down(rows, col):
    current = None
    for r in rows:
        if r.get(col):
            current = r[col]
        elif current:
            r[col] = current


def _money_text(value):
    m = re.search(r'-?\$?\s*([\d,]+(?:\.\d+)?)', str(value or ''))
    return float(m.group(1).replace(',', '')) if m else None


def _read_plan_information(lines):
    title = _first(lines, r'dental eligibility$')
    as_of = _first(lines, r'^as of\s+\d')
    plan = _first(lines, r"the patient['’]?s plan is")
    oon = _first(lines, r'out of network benefits')
    tooth = _first(lines, r'missing tooth exclusion applies\s*:')
    applies = None
    if tooth:
        answer = tooth[3].split(':', 1)[1].strip().lower()
        applies = True if answer.startswith('y') else False if answer.startswith('n') else None
    return {
        'patient_name': re.sub(r'\s*dental eligibility$', '', title[3], flags=re.I) if title else '',
        'as_of': re.sub(r'^as of\s+', '', as_of[3], flags=re.I) if as_of else '',
        'plan_information': {
            'benefit_period': _value_below(lines, 'Benefit period'),
            'date_of_birth': _value_below(lines, 'Date of birth'),
            'dependent_age_limit': _value_below(lines, 'Dependent age limit') or None,
            'student_age_limit': _value_below(lines, 'Student age limit') or None,
            'orthodontics_age_limit': _value_below(lines, 'Orthodontics age limit') or None,
            'group_name': _value_below(lines, 'Group name'),
            'group_number': _value_below(lines, 'Group number'),
            'plan_type': (re.sub(r"^.*the patient['’]?s plan is\s*", '', plan[3], flags=re.I).rstrip('.')
                          if plan else None),
            'missing_tooth_exclusion_applies': applies,
            'out_of_network_note': re.sub(r'^\W+\s*', '', oon[3]) if oon else None,
        },
    }


_EFFECTIVE_CATEGORIES = (
    ('Prev', 'Preventive'), ('Basic', 'Basic'), ('Perio', 'Periodontics'),
    ('Major', 'Major'), ('Ortho', 'Orthodontics'), ('TMJ', 'TMJ'),
    ('Endo', 'Endodontics'), ('Oral', 'Oral Surgery'),
)


def _read_effective_dates(doc, lines):
    """
    The patient's row of "Effective dates of coverage": relationship, and a
    date per service category. Dates sit a little left of their headers, so
    each goes to the nearest header. "Prev" prints run into "Relationship",
    so its position is searched for inside that word.
    """
    heading = _first(lines, r'^effective dates of coverage')
    name = _first(lines, r'^name$', heading[0] if heading else -1)
    stop = _first(lines, r'^deductibles$', name[0] if name else -1)
    if not (heading and name and stop):
        return '', []
    page = doc[name[4]]
    page_top = name[0] - _page_y(doc, name)
    headers = []
    for label, category in _EFFECTIVE_CATEGORIES:
        for rect in page.search_for(label):
            if abs(page_top + rect.y0 - name[0]) <= 14:
                headers.append((rect.x0, category))
                break
    relation_x = next((rect.x0 for rect in page.search_for('Relation')
                       if abs(page_top + rect.y0 - name[0]) <= 14), None)
    body = [ln for ln in lines if name[0] + 10 < ln[0] < stop[0]]
    relationship = ''
    dates = {}
    for y, x0, _x1, text, _pno in body:
        if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{2,4}', text) and headers:
            category = min(headers, key=lambda h: abs(h[0] - x0))[1]
            dates.setdefault(category, text)
        elif relation_x is not None and abs(x0 - relation_x) <= 12 and not relationship:
            relationship = text
    return relationship, [{'service_category': cat, 'effective_date': dates[cat]}
                          for _label, cat in _EFFECTIVE_CATEGORIES if cat in dates]


def _page_y(doc, line):
    """A line's y on its own page."""
    return line[0] - sum(doc[i].rect.height for i in range(line[4]))


def _read_deductibles(lines, words):
    heading = _first(lines, r'^deductibles$')
    stop = _first(lines, r'^plan maximums$', heading[0] if heading else -1)
    if not (heading and stop):
        return []
    columns = _columns_from_words(words, [
        ('coverage', 'Coverage'), ('network', 'Network'), ('deductible', 'Deductible'),
        ('waived', 'Waived'), ('remaining', 'Remaining')], heading[0] + 5, heading[0] + 130)
    header_bottom = max((w[0] for w in words if heading[0] + 5 < w[0] < heading[0] + 130
                         and w[2].lower().startswith(('deductible', 'preventive'))), default=heading[0])
    rows = _table_rows(lines, columns, 'network', header_bottom + 5, stop[0])
    _fill_down(rows, 'coverage')
    out = []
    for r in rows:
        total, remaining = r.get('deductible', ''), r.get('remaining', '')
        met = ''
        if _money_text(total) is not None and _money_text(remaining) is not None:
            met_value = _money_text(total) - _money_text(remaining)
            met = (f'${met_value:.2f}' if '$' in total
                   else str(int(met_value)) if met_value == int(met_value) else str(met_value))
        out.append({
            'coverage': r.get('coverage'), 'network': r.get('network'), 'deductible': total or None,
            'met_to_date': met or None, 'waived_for_preventive': r.get('waived'),
            'remaining_deductible': remaining or None,
        })
    return out


def _read_plan_allowance(lines, words):
    heading = _first(lines, r'^plan maximums$')
    stop = _first(lines, r'^plan options$', heading[0] if heading else -1)
    if not (heading and stop):
        return []
    columns = _columns_from_words(words, [
        ('coverage', 'Coverage'), ('network', 'Network'), ('yearly', 'Yearly'),
        ('remaining_individual', 'Remaining'), ('lifetime', 'Lifetime'),
        ('remaining_lifetime', 'Remaining')], heading[0] + 5, heading[0] + 130)
    header_bottom = max((w[0] for w in words if heading[0] + 5 < w[0] < heading[0] + 130
                         and w[2].lower().startswith('maximum')), default=heading[0])
    rows = _table_rows(lines, columns, 'network', header_bottom + 5, stop[0])
    _fill_down(rows, 'coverage')
    out = []
    for r in rows:
        limit, remaining = r.get('yearly'), r.get('remaining_individual')
        met = (f'${_money_text(limit) - _money_text(remaining):,.2f}'
               if _money_text(limit) is not None and _money_text(remaining) is not None else None)
        out.append({
            'coverage': r.get('coverage'), 'network': r.get('network'),
            'yearly_plan_limit': limit, 'year_met_to_date': met,
            'remaining_individual_maximum': remaining,
            'lifetime_plan_limit': r.get('lifetime'),
            'remaining_lifetime_maximum': r.get('remaining_lifetime'),
        })
    return out


# The services Guardian lists under Plan options, as the extension knows them.
# A printed name that wraps ("Cleanings/P" / "rophylaxis") is matched to these
# with its spaces taken out.
_KNOWN_SERVICES = (
    'Cleanings/Prophylaxis', 'Exams/Oral Evaluations', 'Fluoride',
    'Palliative Emergency Treatment', 'Sealants', 'X-Rays', 'Anesthesia',
    'Consultations', 'Endodontics', 'Fillings', 'Oral Surgery',
    'Periodontal Maintenance', 'Periodontics', 'Bridge/Denture',
    'Crown/Inlay/Onlay', 'Implants', 'Repair/Reline/Rebase', 'Orthodontics',
    'Other Basic', 'Other Major', 'Other Preventive', 'TMJ', 'Cosmetic',
)
_SERVICE_BY_KEY = {re.sub(r'\s+', '', s).lower(): s for s in _KNOWN_SERVICES}

# Where the Plan options table ends.
_TABLE_END = (r'^coordination of benefits', r'^\*dates are not always',
              r'^please note that these are general')

# Last Visit cells wrap mid-word in a narrow column, so they are rejoined
# without spaces and these labels given back their spacing.
_LAST_VISIT_SPACING = (
    ('Perioscaling&rootplaning', 'Perio scaling & root planing'),
    ('DateNotFound', 'Date Not Found'),
)


def _last_visit_text(parts):
    text = ''.join(p.replace(' ', '') for p in parts)
    for squeezed, spaced in _LAST_VISIT_SPACING:
        text = re.sub(re.escape(squeezed), spaced, text, flags=re.IGNORECASE)
    text = re.sub(r'\s*:\s*', ': ', text)
    text = re.sub(r'\s*;\s*', '; ', text).strip()
    return text.rstrip(';').strip()


def _read_plan_options(lines, words):
    heading = _first(lines, r'^plan options$')
    if not heading:
        return []
    header = next((w for w in sorted(words) if w[0] > heading[0] and w[2] == 'Service'), None)
    if header is None:
        return []
    columns = _columns_from_words(words, [
        ('service', 'Service'), ('network', 'Network'), ('category', 'Category'),
        ('coinsurance', 'Coinsurance'), ('message', 'Message'), ('last_visit', 'Last')],
        header[0] - 2, header[0] + 2)
    if len(columns) < 6:
        return []
    message_x = dict(columns)['message']
    header_texts = {'service', 'network', 'category', 'last visit*', 'coinsurance message**'}

    end = next((ln[0] for ln in lines if ln[0] > header[0]
                and any(re.search(p, ln[3], re.IGNORECASE) for p in _TABLE_END)), float('inf'))
    body = [ln for ln in lines if header[0] < ln[0] < end
            and re.sub(r'\s+', ' ', ln[3]).lower() not in header_texts]

    # A row starts with its service name; the name may wrap over a few lines.
    starts = []
    for ln in body:
        if _column_of(ln[1], columns) != 'service':
            continue
        if starts and ln[0] - starts[-1]['lines'][-1][0] <= 20:
            starts[-1]['lines'].append(ln)
        else:
            starts.append({'y': ln[0], 'lines': [ln]})
    rows = []
    for i, start in enumerate(starts):
        bottom = starts[i + 1]['y'] - 2 if i + 1 < len(starts) else end
        cells = {col: [] for col, _x in columns}
        for ln in body:
            col = _column_of(ln[1], columns)
            if col and col != 'service' and start['y'] - 2 <= ln[0] < bottom:
                cells[col].append(ln)
        printed = _join_words(ln[3] for ln in start['lines'])
        service = _SERVICE_BY_KEY.get(re.sub(r'\s+', '', printed).lower(), printed)

        networks = [''.join(c[3] for c in cell) for cell in _cells(cells['network'])]
        categories = [''.join(c[3] for c in cell) for cell in _cells(cells['category'])]
        amounts = re.findall(r'\d+(?:\.\d+)?\s*%', ' '.join(c[3] for c in cells['coinsurance']))
        coinsurance = [{'network': networks[k] if k < len(networks) else None,
                        'amount': amounts[k] if k < len(amounts) else None}
                       for k in range(max(len(networks), len(amounts)))]

        messages, current = [], []
        for ln in cells['message']:
            if ln[1] < message_x + 4 and current:
                messages.append(_join_prose(current))
                current = []
            current.append(re.sub(r'^[•●▪·]\s*', '', ln[3]))
        if current:
            messages.append(_join_prose(current))

        last_visit = _last_visit_text([c[3] for c in cells['last_visit']]) if cells['last_visit'] else None
        rows.append({
            'service': service,
            'category': categories[0] if categories else None,
            'coinsurance': coinsurance,
            'message': messages,
            'last_visit_date': last_visit or None,
            'ehb_plan_indicator': None,
        })
    return rows


def read_guardian_eligibility_pdf(pdf_bytes):
    """
    The printout as the Guardian export the extension would download, or None
    when the PDF is not Guardian's Dental Eligibility page.
    """
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    text = '\n'.join(page.get_text() for page in doc)
    if not _is_guardian_eligibility_text(text):
        return None
    lines = _document_lines(doc)
    words = _document_words(doc)

    head = _read_plan_information(lines)
    relationship, effective = _read_effective_dates(doc, lines)
    deductibles = _read_deductibles(lines, words)
    plan_options = _read_plan_options(lines, words)
    if not plan_options:
        return None

    # Guardian's Deductibles table states the preventive waiver per network;
    # it belongs with the Preventive effective date, where the extension's
    # export carries it.
    for row in effective:
        if row['service_category'] == 'Preventive':
            for d in deductibles:
                if 'individual' in clean(d.get('coverage')).lower():
                    side = 'out' if re.search(r'\bout\b', clean(d.get('network')).lower()) else 'in'
                    row[f'{side}_network_deductible_waived'] = d.get('waived_for_preventive')

    as_of = _date(head['as_of'])
    export = {
        'source': 'Guardian',
        'scraped_at': f'{as_of.isoformat()}T00:00:00.000Z' if as_of else None,
        'patient_name': head['patient_name'] or None,
        'relation_to_member': relationship or None,
        'plan_information': head['plan_information'],
        'effective_dates_of_coverage': effective,
        'deductibles': deductibles,
        'plan_allowance': _read_plan_allowance(lines, words),
        'plan_options': plan_options,
        # Shown by the web page's upload box, and a marker of where the export
        # came from.
        'summary': {'insurer': 'Guardian (eligibility PDF)'},
        'source_document': 'Guardian Dental Eligibility PDF',
    }
    age = _patient_age(head['plan_information'].get('date_of_birth'), as_of)
    export['procedure_codes'] = [
        derive_procedure_record(export, code, age) for code in ALL_CODES if code not in CDT_SEARCH_CODES
    ]
    return export


def _date(value):
    for fmt in ('%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(clean(value), fmt).date()
        except ValueError:
            pass
    return None


def _patient_age(dob, reference):
    born = _date(dob)
    if not born:
        return None
    ref = reference or date.today()
    age = ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))
    return age if age >= 0 else None


# ══════════════════════════════════════════════════════════════════════════════
#  PER-CODE DERIVATION — a port of content_guardian.js
# ══════════════════════════════════════════════════════════════════════════════
#
# Function by function the same as the extension's (named in each docstring),
# so the same Plan Options rows give the same record either way. Fields the
# audit never reads (conditional exclusions, deductible waivers) are left out.

DEFAULT_FREQUENCY = 'Frequency not available'
DERIVED_LOOKUP = 'Derived from Guardian Plan Options'

ALL_CODES = (
    'D0120', 'D0180', 'D0140', 'D0150', 'D0274', 'D0210', 'D0330', 'D0220', 'D0230', 'D0240',
    'D1110', 'D1120', 'D1206', 'D1351', 'D1510', 'D2140', 'D2331', 'D2620', 'D2740', 'D2950',
    'D3310', 'D3330', 'D3347', 'D4260', 'D4341', 'D4355', 'D4381', 'D4910', 'D5110', 'D7953',
    'D5740', 'D6010', 'D6056', 'D6065', 'D6194', 'D6245', 'D7140', 'D7240', 'D7210', 'D6750',
    'D7259', 'D8010', 'D8080', 'D8090', 'D9110', 'D9222', 'D9230', 'D9243', 'D9310', 'D4346',
    'D9944', 'D0364', 'D0431', 'D2391', 'D2962', 'D4249', 'D5860', 'D9430', 'D9239',
    'D1208', 'D1516', 'D2160', 'D2980', 'D5212', 'D5899', 'D5995', 'D6057', 'D6058',
)
CDT_SEARCH_CODES = frozenset({'D1510', 'D2980', 'D4260', 'D7140', 'D7210', 'D9944'})

PROCEDURE_SERVICE_MAP = {
    'D0120': 'Exams/Oral Evaluations', 'D0180': 'Exams/Oral Evaluations', 'D0140': 'Palliative Emergency Treatment',
    'D0150': 'Exams/Oral Evaluations', 'D0274': 'X-Rays', 'D0210': 'X-Rays', 'D0330': 'X-Rays',
    'D0220': 'X-Rays', 'D0230': 'X-Rays', 'D0240': 'X-Rays', 'D1110': 'Cleanings/Prophylaxis',
    'D1120': 'Cleanings/Prophylaxis', 'D1206': 'Fluoride', 'D1351': 'Sealants', 'D1510': 'Other Preventive',
    'D2140': 'Fillings', 'D2331': 'Fillings', 'D2620': 'Crown/Inlay/Onlay', 'D2740': 'Crown/Inlay/Onlay',
    'D2950': 'Crown/Inlay/Onlay', 'D3310': 'Endodontics', 'D3330': 'Endodontics', 'D3347': 'Endodontics',
    'D4260': 'Periodontics', 'D4341': 'Periodontics', 'D4355': 'Periodontics', 'D4381': 'Other Basic',
    'D4910': 'Periodontal Maintenance', 'D5110': 'Bridge/Denture', 'D7953': 'Oral Surgery',
    'D5740': 'Repair/Reline/Rebase', 'D6010': 'Implants', 'D6056': 'Implants', 'D6065': 'Implants',
    'D6194': 'Implants', 'D6245': 'Bridge/Denture', 'D7140': 'Oral Surgery', 'D7240': 'Oral Surgery',
    'D7210': 'Oral Surgery', 'D6750': 'Bridge/Denture', 'D7259': 'Oral Surgery', 'D8010': 'Orthodontics',
    'D8080': 'Orthodontics', 'D8090': 'Orthodontics', 'D9110': 'Palliative Emergency Treatment',
    'D9222': 'Anesthesia', 'D9230': 'Anesthesia', 'D9243': 'Anesthesia', 'D9310': 'Consultations',
    'D4346': 'Periodontics', 'D9944': 'Other Basic', 'D0364': 'X-Rays', 'D0431': 'Other Basic',
    'D2391': 'Fillings', 'D2962': 'Crown/Inlay/Onlay', 'D4249': 'Periodontics', 'D5860': 'Bridge/Denture',
    'D9430': 'Exams/Oral Evaluations', 'D9239': 'Anesthesia',
    'D1208': 'Fluoride', 'D1516': 'Other Preventive', 'D2160': 'Fillings',
    'D5212': 'Bridge/Denture', 'D6057': 'Implants', 'D6058': 'Implants',
}
_DEDICATED_SERVICE_OVERRIDES = {'D9944': 'Other Basic'}

_KNOWN_CATEGORIES = ('Preventive', 'Basic', 'Periodontics', 'Major', 'Orthodontics',
                     'TMJ', 'Endodontics', 'Oral Surgery', 'Cosmetic')

_CODE_RE = re.compile(r'\bD\d{4}\b', re.I)
_CODE_RANGE_RE = re.compile(r'\b(D\d{4})\s*-\s*(D\d{4})\b', re.I)
_COVERED_RE = re.compile(
    r'\b(?:is|are)\s+covered\b|\bcovered\b|\blimited\s+to\b|\ballowed\s+as\b'
    r'|\bbenefit\s+is\s+allowable\b|\breceive\s+the\s+(?:alternate\s+)?benefit\s+of\b', re.I)
_NOT_COVERED_RE = re.compile(r'\b(?:not\s+covered|not\s+a\s+covered\s+benefit|no\s+coverage)\b', re.I)
_CONTINUATION_PREFIX_RE = re.compile(
    r'^(?:covered\b|limited\b|subject\b|when\b|if\b|provided\b|requires?\b|frequency\b|age\b'
    r'|up\s+to\b|under\s+age\b|only\b|considered\b|otherwise\b|and\s+is\b|and\s+are\b)', re.I)
_CONDITIONAL_RE = re.compile(
    r'\b(?:when|if|unless|subject\s+to|provided(?:\s+that)?|only\s+when|only\s+if'
    r'|on\s+the\s+same\s+day\s+as|same\s+day\s+as)\b', re.I)
_BOILERPLATE_RE = re.compile(
    r',?\s*subject\s+to\s+all\s+other\s+(?:plan\s+)?(?:provisions|limitations)'
    r'(?:\s+and\s+(?:plan\s+)?(?:provisions|limitations))?', re.I)
_CATEGORY_STATEMENT_RE = re.compile(
    r'\b(?:covered\s+under|under)\s+(?:the\s+)?(?:Preventive|Basic|Periodontics|Major|Orthodontics'
    r'|TMJ|Endodontics|Oral\s+Surgery|Cosmetic)\s+(?:service\s+)?category\b', re.I)
_CATEGORY_CAPTURE_RE = re.compile(
    r'\b(?:covered\s+under|under)\s+(?:the\s+)?(Preventive|Basic|Periodontics|Major|Orthodontics'
    r'|TMJ|Endodontics|Oral\s+Surgery|Cosmetic)\s+(?:service\s+)?category\b', re.I)

_FREQ_PERIOD = r'\d+[\s-]+(?:consecutive\s+)?(?:calendar\s+)?(?:months|month|years|year)\b(?:\s+period)?'
_FREQ_COUNT = r'(?:once|twice|three|four|five|one|two|\d+)'
_FREQ_WINDOW = (rf'(?:(?:in|within|during|over|every)\s+(?:(?:any|a|the)\s+)?{_FREQ_PERIOD}'
                r'|in\s+a\s+calendar\s+year\b|(?:per|each)\s+calendar\s+year\b)')
_FREQUENCY_PATTERNS = [re.compile(p, re.I) for p in (
    rf'\b{_FREQ_COUNT}\s+times?\s+per\s+[^.;,]+?\s+per\s+lifetime\b',
    rf'\b{_FREQ_COUNT}\s+per\s+[^.;,]+?\s+{_FREQ_WINDOW}',
    rf'\b{_FREQ_COUNT}\s+per\s+[^.;,]+?\s+per\s+lifetime\b',
    rf'\b{_FREQ_COUNT}\s+(?:{_FREQ_WINDOW}|per\s+lifetime)',
    rf'\b{_FREQ_COUNT}\s+per\s+{_FREQ_PERIOD}',
    rf'\b{_FREQ_COUNT}\s+per\s+lifetime\b',
)]
_AGE_RE = re.compile(
    r'\b(?:up\s+to\s+age\s+\d+|under\s+(?:the\s+)?age\s+(?:of\s+)?\d+'
    r'|age\s+\d+\s+(?:and\s+over|and\s+older|or\s+older|and\s+under|through\s+\d+))\b', re.I)

_FILLING_CODES = frozenset({
    'D2140', 'D2145', 'D2150', 'D2160', 'D2161', 'D2330', 'D2331', 'D2332', 'D2335',
    'D2391', 'D2392', 'D2393', 'D2394',
})


def _norm(value):
    """normalizeEvidenceText"""
    return re.sub(r'\s+', ' ', str(value or '').replace(' ', ' ')).strip()


def _expand_codes(text):
    """expandCodesInText"""
    t = _norm(text).upper()
    codes = {c.upper() for c in _CODE_RE.findall(t)}
    for m in _CODE_RANGE_RE.finditer(t):
        lo, hi = int(m.group(1)[1:]), int(m.group(2)[1:])
        if hi < lo or hi - lo > 1000:
            continue
        codes.update(f'D{n:04d}' for n in range(lo, hi + 1))
    return codes


def _primary_codes(text):
    """extractPrimaryCodes"""
    t = _norm(text).upper()
    primary = set()
    for m in re.finditer(r'\(([^)]*\bD\d{4}\b[^)]*)\)', t):
        group = m.group(0)
        if re.search(r'\bconsisting\s+of\s+(?:cdt\s+)?codes?\s+D\d{4}\s*-\s*D\d{4}\b', group, re.I):
            continue
        primary |= _expand_codes(group)
    if primary:
        return primary
    verb = re.search(r'\b(?:IS|ARE|WAS|WERE)\b', t)
    return _expand_codes(t[:verb.start()] if verb else t)


def _evidence_blocks(messages):
    """buildEvidenceBlocks"""
    blocks = []
    for raw in messages or []:
        sentences = [s.strip() for s in re.split(r'(?<=[.;])\s+', _norm(raw)) if s.strip()] if _norm(raw) else []
        inherited = set()
        for sentence in sentences:
            all_codes = _expand_codes(sentence)
            primary = _primary_codes(sentence)
            if not primary and inherited and _CONTINUATION_PREFIX_RE.search(sentence):
                primary = set(inherited)
            blocks.append({'text': sentence, 'codes': primary})
            if primary and all_codes:
                inherited = set(primary)
            elif not all_codes and not _CONTINUATION_PREFIX_RE.search(sentence):
                inherited = set()
    return blocks


def _conditional(text):
    """hasConditionalLanguage"""
    return bool(_CONDITIONAL_RE.search(_norm(text)))


def _conditional_negative(text):
    """isConditionalNegativeClause"""
    t = _norm(text)
    return bool(_NOT_COVERED_RE.search(t)) and _conditional(t)


def _universal(text):
    """isUniversalServiceClause"""
    t = _BOILERPLATE_RE.sub('', _norm(text)).strip()
    if not t or _expand_codes(t):
        return False
    if not _COVERED_RE.search(t) and not _NOT_COVERED_RE.search(t):
        return False
    if _conditional(t):
        return False
    if re.match(r'(?:replacement|limited|considered|subject|provided|after|following|unless)\b', t, re.I):
        return False
    return True


def _applies(block, code):
    """blockAppliesToCode"""
    if code in block['codes']:
        return True
    return not block['codes'] and _universal(block['text'])


def _literal_mention(text, code):
    """isLiteralCodeMention (its variable-width lookbehind written out)"""
    t = _norm(text).upper()
    for m in re.finditer(re.escape(code.upper()), t):
        i, j = m.start(), m.end()
        if i > 0 and (re.match(r'\w', t[i - 1]) or t[i - 1] == '-'):
            continue
        if j < len(t) and re.match(r'\w', t[j]):
            continue
        if re.match(r'\s*-\s*D\d{4}', t[j:]):
            continue
        if re.search(r'D\d{4}\s*-\s*$', t[:i]):
            continue
        return True
    return False


def _listed_benefit(text):
    """isListedBenefitClause"""
    return bool(re.match(
        r'(?:single\s+crowns?|space\s+maintainers?|prefabricated\s+crowns?|maintenance\s+and\s+repair\b'
        r'|endodontic\s+therapy|periodontal\s+scaling|full\s+mouth\s+debridement|occlusal\s+guard'
        r'|implant\s+procedures?)\b', _norm(text), re.I))


def _code_listing(text):
    """isCodeListingClause"""
    return bool(re.match(r'includes\s+codes?\s*:', _norm(text), re.I))


def _frequency_from_text(text):
    """extractFrequencyFromText"""
    t = re.sub(r',\s+per\s+', ' per ', _norm(text), flags=re.I)
    t = re.sub(r',\s+(?=in\s+(?:any|a)\s+\d)', ' ', t, flags=re.I)
    for pattern in _FREQUENCY_PATTERNS:
        m = pattern.search(t)
        if m:
            return m.group(0).strip()
    return None


def _filling_frequency(text):
    """extractFillingFrequency"""
    t = re.sub(r',\s+per\s+', ' per ', _norm(text), flags=re.I)
    child = re.search(r'(once\s+per\s+tooth\s+surface\s+in\s+any\s+\d+\s+months?)\s+for\s+covered\s+persons'
                      r'\s+up\s+to\s+age\s+(\d+)', t, re.I)
    adult = re.search(r'(once\s+per\s+tooth\s+surface\s+in\s+any\s+\d+\s+months?)\s+for\s+all\s+other'
                      r'\s+covered\s+persons', t, re.I)
    if not child and not adult:
        return None
    return {'child': _frequency_from_text(child.group(1)) if child else None,
            'adult': _frequency_from_text(adult.group(1)) if adult else None,
            'child_age': int(child.group(2)) if child else None}


def _code_specific_frequency(messages, code):
    """extractCodeSpecificFrequency"""
    for block in _evidence_blocks(messages):
        if code in block['codes']:
            frequency = _frequency_from_text(block['text'])
            if frequency:
                return frequency
    return None


def _frequency(messages, code, age):
    """extractFrequency"""
    blocks = _evidence_blocks(messages)
    if code in _FILLING_CODES:
        for block in blocks:
            if not _applies(block, code):
                continue
            branches = _filling_frequency(block['text'])
            if not branches:
                continue
            child_max = branches['child_age'] if branches['child_age'] is not None else 19
            if age is not None and age > child_max and branches['adult']:
                return branches['adult']
            if age is not None and age <= child_max and branches['child']:
                return branches['child']
            if branches['child']:
                return branches['child']
    for block in blocks:
        if not _applies(block, code):
            continue
        frequency = _frequency_from_text(block['text'])
        if frequency:
            return frequency
    return DEFAULT_FREQUENCY


def _age_limit(messages, code, age):
    """extractAgeLimit"""
    blocks = _evidence_blocks(messages)
    if code in _FILLING_CODES and age is not None:
        branch = next((b for b in (_filling_frequency(x['text']) for x in blocks if _applies(x, code)) if b), None)
        if branch:
            child_max = branch['child_age'] if branch['child_age'] is not None else 19
            return None if age > child_max else f'up to age {child_max}'
    applicable = [b for b in blocks if _applies(b, code)]
    age_blocks = [b for b in applicable if _AGE_RE.search(_norm(b['text']))]
    if not age_blocks:
        return None
    age_free_positive = any(
        not _AGE_RE.search(_norm(b['text'])) and not _conditional_negative(b['text'])
        and (_COVERED_RE.search(b['text']) or _listed_benefit(b['text']))
        for b in applicable)
    child_qualification = any(
        re.search(r'\bchildren?\s+under\s+age\b', _norm(b['text']), re.I)
        and re.search(r'\bwhen\s+performed\b', _norm(b['text']), re.I)
        for b in age_blocks)
    if age_free_positive and child_qualification:
        return None
    return _AGE_RE.search(_norm(age_blocks[0]['text'])).group(0).strip()


def _age_eligible(age_limit, code, age):
    """evaluateAgeEligibility"""
    if not age_limit or age is None or code in _FILLING_CODES:
        return None
    t = _norm(age_limit).lower()
    m = re.fullmatch(r'under\s+(?:the\s+)?age\s+(?:of\s+)?(\d+)', t)
    if m:
        return age < int(m.group(1))
    m = re.fullmatch(r'age\s+(\d+)\s+(?:and\s+over|and\s+older|or\s+older)', t)
    if m:
        return age >= int(m.group(1))
    m = re.fullmatch(r'age\s+(\d+)\s+and\s+under', t)
    if m:
        return age <= int(m.group(1))
    m = re.fullmatch(r'up\s+to\s+age\s+(\d+)', t)
    if m:
        limit = int(m.group(1))
        return True if age < limit else False if age > limit else None
    return None


def _row_category(service):
    """inferCategoryFromRowName"""
    return {'other preventive': 'Preventive', 'other basic': 'Basic',
            'other major': 'Major'}.get(_norm(service).lower())


def _category_override(messages, code, base):
    """extractCategoryOverride"""
    for block in _evidence_blocks(messages):
        if not _applies(block, code):
            continue
        m = _CATEGORY_CAPTURE_RE.search(_norm(block['text']))
        if m:
            return next((c for c in _KNOWN_CATEGORIES if c.lower() == m.group(1).lower()), m.group(1))
    return base


_BASIS_PRIORITY = {'code-specific': 3, 'code-range': 2, 'service-level': 1}


def _derive_coverage(messages, code):
    """deriveCoverage"""
    positive = negative = False
    positive_basis = negative_basis = None
    for block in _evidence_blocks(messages):
        if not _applies(block, code):
            continue
        text = block['text']
        is_negative = bool(_NOT_COVERED_RE.search(text)) and not _conditional_negative(text)
        is_positive = not is_negative and bool(
            _COVERED_RE.search(text) or _listed_benefit(text) or _code_listing(text))
        if not (is_negative or is_positive):
            continue
        basis = (('code-specific' if _literal_mention(text, code) else 'code-range')
                 if code in block['codes'] else 'service-level')
        if is_negative:
            negative = True
            if _BASIS_PRIORITY[basis] > _BASIS_PRIORITY.get(negative_basis, 0):
                negative_basis = basis
        else:
            positive = True
            if _BASIS_PRIORITY[basis] > _BASIS_PRIORITY.get(positive_basis, 0):
                positive_basis = basis
    if negative:
        return {'covered': False, 'coverage_status': 'Not Covered', 'coverage_basis': negative_basis}
    if positive:
        return {'covered': True, 'coverage_status': 'Covered', 'coverage_basis': positive_basis}
    return {'covered': None, 'coverage_status': 'Not Determined', 'coverage_basis': None}


_BITEWING_CODES = {f'D{n:04d}' for n in range(270, 278)}


def _code_last_visit(raw_value, code):
    """extractCodeSpecificLastVisit"""
    raw = _norm(raw_value)
    if not raw:
        return None
    if not re.search(r'[;:]', raw):
        return raw
    if code in _BITEWING_CODES:
        m = re.search(r'(?:^|;)\s*Bitewings\s*:\s*([^;]+)', raw, re.I)
        return _norm(m.group(1)) if m else None
    if code in ('D0210', 'D0330'):
        m = re.search(r'(?:^|;)\s*FullMouth/panoramic\s*:\s*([^;]+)', raw, re.I)
        return _norm(m.group(1)) if m else None
    if code in ('D4341', 'D4342'):
        m = re.search(r'(?:^|;)\s*Perio\s+scaling\s+&\s+root\s+planing\s*:\s*(UR-[^;]+)\s*;\s*(UL-[^;]+)'
                      r'\s*;\s*(LL-[^;]+)\s*;\s*(LR-[^;]+)(?:;|$)', raw, re.I)
        if not m:
            return None
        entries = [_norm(g) for g in m.groups()]
        values = [re.sub(r'^[A-Z]{2}-', '', e, flags=re.I) for e in entries]
        if all(re.fullmatch(r'date\s+not\s+found', v, re.I) for v in values):
            return 'Date Not Found'
        return ';'.join(entries)
    return None


def _amount_stated(c):
    return isinstance(c, dict) and c.get('amount') is not None and str(c.get('amount')).strip() != ''


def _copy_coinsurance(items):
    return [{'network': (c or {}).get('network'), 'amount': (c or {}).get('amount')} for c in items or []]


def _other_row_coinsurance(row, category, all_rows):
    """inferOtherRowCoinsurance"""
    if not category or not isinstance(all_rows, list):
        return []
    if _row_category(row.get('service')) != category:
        return []
    sibling = next((r for r in all_rows if r is not row and r.get('category') == category
                    and isinstance(r.get('coinsurance'), list) and r['coinsurance']), None)
    return _copy_coinsurance(sibling['coinsurance']) if sibling else []


def _category_coinsurance(all_rows, category):
    """coinsuranceForCategory"""
    if not category or not isinstance(all_rows, list):
        return None
    wanted = _norm(category).lower()
    sibling = next((r for r in all_rows if _norm(r.get('category')).lower() == wanted
                    and isinstance(r.get('coinsurance'), list)
                    and any(_amount_stated(c) for c in r['coinsurance'])), None)
    return _copy_coinsurance(sibling['coinsurance']) if sibling else None


def _row_score(row, code):
    """rowCodeEvidenceScore"""
    messages = row.get('message') if isinstance(row.get('message'), list) else []
    states_category = any(_CATEGORY_STATEMENT_RE.search(_norm(m)) for m in messages)
    explicit = positive = negative = direct = False
    for message in messages:
        for block in _evidence_blocks([message]):
            if code not in block['codes']:
                continue
            text = block['text']
            direct = True
            if states_category and _code_listing(text):
                explicit = positive = True
            if _CATEGORY_STATEMENT_RE.search(text):
                explicit = True
            if _NOT_COVERED_RE.search(text) and not _conditional_negative(text):
                negative = True
            elif _NOT_COVERED_RE.search(text) and _conditional_negative(text):
                direct = False
            elif _COVERED_RE.search(text) or _listed_benefit(text):
                positive = True
    if explicit and positive:
        return 400
    if explicit and negative:
        return 380
    if explicit:
        return 360
    if positive:
        return 300
    if negative:
        return 200
    return 100 if direct else 0


def _governing_row(rows, code):
    """resolveGoverningRow"""
    dedicated = _DEDICATED_SERVICE_OVERRIDES.get(code)
    if dedicated:
        row = next((r for r in rows if _norm(r.get('service')).lower() == dedicated.lower()
                    and isinstance(r.get('message'), list)
                    and any(_literal_mention(m, code) for m in r['message'])), None)
        if row:
            return row
    scored = [(score, i, r) for i, r in enumerate(rows) for score in [_row_score(r, code)] if score > 0]
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]
    fallback = PROCEDURE_SERVICE_MAP.get(code)
    return next((r for r in rows if r.get('service') == fallback), None) if fallback else None


def _record_from_row(code, row, age, all_rows, ortho_age_limit):
    """buildProcedureRecordFromPlanOption"""
    messages = row.get('message') if isinstance(row.get('message'), list) else []
    exclusion_messages = ([m for r in all_rows for m in (r.get('message') if isinstance(r.get('message'), list) else [])]
                          if isinstance(all_rows, list) else messages)
    derived = _derive_coverage(messages, code)
    row_category = _row_category(row.get('service'))
    if code == 'D9944' and row_category == 'Basic':
        category = 'Basic'
    else:
        category = _category_override(messages, code, row.get('category'))
        if category is None:
            category = row_category
    raw_last = _norm(row.get('last_visit_date'))
    has_benefits = any(_amount_stated(c) for c in row.get('coinsurance') or [])
    service_row = bool(row.get('service') and row.get('category') and has_benefits)
    effective = derived
    if derived['covered'] is None and service_row:
        effective = {'covered': True, 'coverage_status': 'Covered', 'coverage_basis': 'service-level'}

    age_limit = _age_limit(messages, code, age)
    ortho = ortho_age_limit if isinstance(ortho_age_limit, int) else (
        int(ortho_age_limit) if re.fullmatch(r'\s*\d+\s*', str(ortho_age_limit or '')) else None)
    if (_norm(row.get('service')).lower() == 'orthodontics' and code in ('D8010', 'D8080', 'D8090')
            and ortho is not None and ortho < 99):
        age_limit = f'up to age {ortho}'
    eligible = _age_eligible(age_limit, code, age) if effective['covered'] is True else None
    covered = False if eligible is False else effective['covered']
    not_covered = covered is False
    undetermined = covered is None

    frequency = DEFAULT_FREQUENCY if effective['covered'] is False else _frequency(messages, code, age)
    if frequency == DEFAULT_FREQUENCY and effective['covered'] is not False:
        frequency = _code_specific_frequency(exclusion_messages, code) or frequency

    coinsurance = _copy_coinsurance(row.get('coinsurance')) if isinstance(row.get('coinsurance'), list) else []
    if not coinsurance and not not_covered and not undetermined:
        coinsurance = _other_row_coinsurance(row, category, all_rows)
    if not_covered or undetermined:
        coinsurance = []
    if (not not_covered and not undetermined and row.get('category') and category
            and _norm(category).lower() != _norm(row.get('category')).lower()):
        moved = _category_coinsurance(all_rows, category)
        if moved:
            coinsurance = moved

    last_visit = _code_last_visit(raw_last, code)
    if last_visit is None:
        last_visit = raw_last if raw_last and not re.search(r'[;:]', raw_last) else None

    return {
        'code': code,
        'covered': covered,
        'coverage_status': 'Not Covered' if eligible is False else effective['coverage_status'],
        'coverage_basis': effective['coverage_basis'],
        'dental_service_category': None if undetermined else category,
        'dental_service': row.get('service') or PROCEDURE_SERVICE_MAP.get(code),
        'frequency': frequency,
        'age_limit': age_limit,
        'age_eligible': eligible,
        'coinsurance': coinsurance,
        'last_visit_date': None if undetermined else last_visit,
        'message': messages,
        'lookup_status': DERIVED_LOOKUP,
    }


def derive_procedure_record(result, code, age):
    """deriveLocalProcedureRecord: one CDT record from the Plan Options rows."""
    rows = result.get('plan_options') if isinstance(result.get('plan_options'), list) else []
    row = _governing_row(rows, code)
    if row is None:
        return {
            'code': code, 'covered': None, 'coverage_status': 'Not Determined', 'coverage_basis': None,
            'dental_service_category': None, 'dental_service': PROCEDURE_SERVICE_MAP.get(code),
            'frequency': DEFAULT_FREQUENCY, 'age_limit': None, 'age_eligible': None, 'coinsurance': [],
            'last_visit_date': None, 'message': [], 'lookup_status': 'No matching Guardian Plan Options row',
        }
    return _record_from_row(code, row, age, rows,
                            (result.get('plan_information') or {}).get('orthodontics_age_limit'))
