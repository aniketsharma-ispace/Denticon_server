// content_ddri.js - DDRI Provider Portal Auditor

const STORAGE_KEYS = {
    AUDIT_CONTEXT: "audit_context",
    PROGRESS: "crawl_progress",
    CURRENT_CARRIER: "current_carrier",
    CACHED_PATIENT_NOTES: "cached_patient_notes"
};

const PROCEDURE_CODES = [
    "D0180", "D0120", "D0140", "D0150", "D0210", "D0220", "D0230", "D0240", "D0274", "D0330",
    "D1510", "D1110", "D1120", "D1206", "D1351", "D2140", "D2331", "D2620", "D2740", "D2950",
    "D2991", "D3347", "D3310", "D3330", "D4260", "D4341", "D4355", "D4381", "D4910", "D5860",
    "D5110", "D5740", "D5982", "D6194", "D6010", "D6056", "D6065", "D6245", "D7259", "D7140",
    "D7240", "D8010", "D8080", "D8090", "D9430", "D9110", "D9222", "D9239", "D9310", "D9944"
];

// Used only when the procedure-code lookup explicitly reports that a CDT is not
// covered. The lookup response remains the authority for coverage status.


const sleep = ms => new Promise(r => setTimeout(r, ms));
const clean = str => (str || "").replace(/[\n\r\t]/g, " ").replace(/\s+/g, " ").trim();

// Logging helper
function logState(state) {
    console.log(`[DDRI][${state}]`);
}

function broadcastState(state, title, message = "", progress = 0) {
    const payload = {
        carrier: "DDRI",
        state: state,
        stage: 0,
        progress: progress,
        title: title,
        message: message,
        timestamp: Date.now()
    };
    
    // Storage (Persistent)
    chrome.storage.local.set({ [STORAGE_KEYS.PROGRESS]: payload });
    
    // Runtime (Live to Popup)
    chrome.runtime.sendMessage({ type: "PROGRESS_UPDATE", payload: payload }).catch(() => {});
}

async function clearPreviousSession() {
    return new Promise(resolve => {
        chrome.storage.local.remove([STORAGE_KEYS.AUDIT_CONTEXT, STORAGE_KEYS.PROGRESS, "partial_json"], () => {
            resolve();
        });
    });
}

// ------------------------------------------------------------------
// SCRAPING LOGIC
// ------------------------------------------------------------------

function getLabelValue(tableSelector, labelText) {
    const table = document.querySelector(tableSelector);
    if (!table) return "N/A";
    
    const cells = Array.from(table.querySelectorAll('td, th'));
    for (let i = 0; i < cells.length; i++) {
        const text = clean(cells[i].textContent);
        if (text === labelText || text === labelText + ":") {
            for (let j = i + 1; j < cells.length; j++) {
                const val = clean(cells[j].textContent);
                if (val !== "") return val;
            }
        }
    }
    return "N/A";
}

function getEligibilityRow(labelText) {
    const table = document.querySelector('table.Eligibility');
    if (!table) return null;
    const cells = Array.from(table.querySelectorAll('td'));
    for (let i = 0; i < cells.length; i++) {
        if (clean(cells[i].textContent) === labelText) {
            return {
                relationship: clean(cells[i + 1]?.textContent),
                dob: clean(cells[i + 2]?.textContent),
                dates: clean(cells[i + 3]?.textContent)
            };
        }
    }
    return null;
}

function collectPatient() {
    const subName = getLabelValue('.SubscriberProfile', 'Subscriber Name');
    let elig = getEligibilityRow(subName);
    
    if (!elig) {
        const table = document.querySelector('table.Eligibility');
        if (table) {
            const firstDataRow = table.querySelector('tbody tr');
            if (firstDataRow) {
                const cells = firstDataRow.querySelectorAll('td');
                if (cells.length >= 5) {
                    elig = {
                        relationship: clean(cells[2].textContent),
                        dob: clean(cells[3].textContent),
                        dates: clean(cells[4].textContent)
                    };
                }
            }
        }
    }
    
    return {
        name: getLabelValue('.SubscriberProfile', 'Member Name'),
        subscriber_name: subName,
        member_id: getLabelValue('.SubscriberProfile', 'Subscriber ID'),
        dob: elig ? elig.dob : "N/A",
        relationship: elig ? elig.relationship : "N/A"
    };
}

// NEW HELPER: fixes the bug where collectPlan() looked up the Eligibility row by *Subscriber*
// Name (e.g. "CHARLES RAPOZA"), but the Eligibility table row lists the covered *Member*
// (e.g. "DONNA RAPOZA", a spouse/dependent) -- so that lookup silently failed and coverage
// dates were always "N/A". This instead finds the Eligibility table by its "Coverage Dates"
// header text (not the fixed 'table.Eligibility' class) and reads the dates directly.
function getEligibilityCoverageDates() {
    const memberName = getLabelValue('.SubscriberProfile', 'Member Name');
    const tables = Array.from(document.querySelectorAll('table'));

    for (const table of tables) {
        const headerCells = Array.from(table.querySelectorAll('thead th, thead td'));
        if (headerCells.length === 0) continue;
        const headerLabels = headerCells.map(c => clean(c.textContent).toLowerCase());
        const dateColIdx = headerLabels.findIndex(t => t.includes('coverage dates'));
        if (dateColIdx === -1) continue;

        const rows = Array.from(table.querySelectorAll('tbody tr'));
        if (rows.length === 0) continue;

        // Prefer the row matching this specific member (handles family plans with multiple
        // dependents listed in the same table); otherwise fall back to the first data row.
        // Per the task, we deliberately do NOT match by subscriber name here.
        let targetRow = null;
        if (memberName && memberName !== 'N/A') {
            targetRow = rows.find(r => Array.from(r.querySelectorAll('td'))
                .some(c => clean(c.textContent).toUpperCase() === memberName.toUpperCase()));
        }
        if (!targetRow) targetRow = rows[0];

        const cells = targetRow.querySelectorAll('td');
        if (cells[dateColIdx]) return clean(cells[dateColIdx].textContent);
    }

    // Legacy fallback in case the header-text lookup above ever fails
    const legacyTable = document.querySelector('table.Eligibility');
    if (legacyTable) {
        const row = legacyTable.querySelector('tbody tr');
        if (row) {
            const cells = row.querySelectorAll('td');
            if (cells.length) return clean(cells[cells.length - 1].textContent);
        }
    }

    return "N/A";
}

function collectPlan() {
    // MODIFIED: was `getEligibilityRow(getLabelValue('.SubscriberProfile', 'Subscriber Name'))?.dates`
    // -- see getEligibilityCoverageDates() above for why that always returned "N/A".
    const dates = getEligibilityCoverageDates();
    let start = "N/A", end = "N/A";
    if (dates && dates !== "N/A") {
        if (dates.includes('-')) {
            [start, end] = dates.split('-').map(clean);
        } else {
            // Single date with no range separator (e.g. termination-only entries) -- keep it
            // as the effective date rather than discarding it.
            start = dates;
        }
    }

    return {
        employer_group: getLabelValue('.SubscriberProfile', 'Group Name'),
        group_number: getLabelValue('.SubscriberProfile', 'Group Number'),
        effective_date: start,
        termination_date: end,
        network_status: getLabelValue('.SubscriberProfile', 'Product Name'),
        coverage_type: getLabelValue('.SubscriberProfile', 'Coverage Type'),
        plan_type: getLabelValue('.SubscriberProfile', 'Plan Type')
    };
}

function collectFinancials() {
    const financials = {
        maximums: [],
        deductibles: []
    };

    // DDRI renders deductible rows in the same main table as maximums and may
    // repeat a simplified deductible total in the OON table. The main table is
    // authoritative because it contains total + used + remaining.
    const maximumKeys = new Set();
    const deductibleByCategory = new Map();

    const categoryKey = value => clean(value).replace(/:\s*$/, '').toLowerCase();
    const isDeductible = value => /\bdeductible\b/i.test(clean(value));
    const isMissing = value => !value || value === "N/A";

    const keepMoreCompleteDeductible = (entry) => {
        const key = categoryKey(entry.category);
        if (!key) return;

        const existing = deductibleByCategory.get(key);
        if (!existing) {
            deductibleByCategory.set(key, entry);
            return;
        }

        // Never replace a real main-table value with the OON fallback's N/A.
        for (const field of ["total", "used", "remaining"]) {
            if (isMissing(existing[field]) && !isMissing(entry[field])) {
                existing[field] = entry[field];
            }
        }
    };

    const maxRows = document.querySelectorAll('tr.DataTableRow, tr.DataTableOddRow');

    for (const row of maxRows) {
        const catCell = row.querySelector('.MaximumsFreqCategory');
        if (!catCell || !row.querySelector('.MaximumsAmount')) continue;

        const category = clean(catCell.textContent).replace(/:\s*$/, '');
        if (!category) continue;

        const entry = {
            category,
            total: clean(row.querySelector('.MaximumsAmount')?.textContent) || "N/A",
            used: clean(row.querySelector('.MaximumsAmountUsed')?.textContent) || "N/A",
            remaining: clean(row.querySelector('.MaximumsAmountAvailable')?.textContent) || "N/A"
        };

        if (isDeductible(category)) {
            keepMoreCompleteDeductible(entry);
            continue;
        }

        const key = [entry.category, entry.total, entry.used, entry.remaining]
            .map(value => clean(value).toLowerCase())
            .join('\u0000');
        if (!maximumKeys.has(key)) {
            maximumKeys.add(key);
            financials.maximums.push(entry);
        }
    }

    // OON deductible values are fallback-only. If the main table already gave
    // us Individual/Family deductible values, do not create a duplicate row.
    const oonTables = document.querySelectorAll('.OONTbl table');
    for (const table of oonTables) {
        for (const row of table.querySelectorAll('tr')) {
            const cells = row.querySelectorAll('td');
            if (cells.length < 2) continue;

            const category = clean(cells[0].textContent).replace(/:\s*$/, '');
            if (!category || !isDeductible(category)) continue;

            keepMoreCompleteDeductible({
                category,
                total: clean(cells[1].textContent) || "N/A",
                used: "N/A",
                remaining: "N/A"
            });
        }
    }

    financials.deductibles = Array.from(deductibleByCategory.values());
    return financials;
}

function collectFrequencies() {
    const freqs = [];
    const rows = document.querySelectorAll('tr.DataTableRow, tr.DataTableOddRow');
    for (const row of rows) {
        const catCell = row.querySelector('.MaximumsFreqCategory');
        const freqAmtCell = row.querySelector('.FrequencyAmount');
        if (catCell && freqAmtCell) {
            freqs.push({
                category: clean(catCell.textContent),
                used_count: clean(freqAmtCell.textContent) || "N/A",
                next_eligible: clean(row.querySelector('.FrequenciesNextElig')?.textContent) || "N/A"
            });
        }
    }
    return freqs;
}

function collectProvisions() {
    const provisions = [];
    const benefitDiv = document.getElementById('benefits');
    if (!benefitDiv) return provisions;

    // MODIFIED: broadened from 'p, div.redBackgroundTextAlignedLeft, .Disclaimer' to a generic
    // set of text-bearing block elements (plus '.Disclaimer' on any tag, kept for back-compat)
    // so this keeps working even if DDRI wraps these notices in a differently-named class.
    const blocks = Array.from(benefitDiv.querySelectorAll('p, div, li, td, .Disclaimer'));
    const seen = new Set(); // avoid duplicate entries when a parent/child both match identical cleaned text
    for (const block of blocks) {
        const text = clean(block.textContent);
        if (!text || seen.has(text)) continue;

        if (text.includes("missing tooth clause")) {
            seen.add(text);
            provisions.push({ rule: "Missing Tooth Clause", value: getMissingToothClauseValue(text) });
        } else if (text.includes("Dependent children")) {
            // MODIFIED: was an exact-sentence match ("Dependent children are covered"). Now
            // matches ANY paragraph mentioning "Dependent children", since other DDRI plans
            // phrase this notice differently.
            seen.add(text);
            provisions.push({ rule: "Dependent Age Limit", value: text });
        } else if (block.classList.contains('Disclaimer')) {
            seen.add(text);
            provisions.push({ rule: "Disclaimer", value: text });
        }
    }
    return provisions;
}

// DDRI describes this benefit in prose. Return the answer required by the audit instead of
// copying that prose into the JSON. For example, "does not include a missing tooth clause"
// becomes "No"; an affirmative clause becomes "Yes".
function getMissingToothClauseValue(text) {
    const normalized = normalizeText(text);
    if (!normalized.includes('missing tooth clause')) return 'N/A';
    if (/\b(no|not|does not|doesnt|without|exclude|excluded)\b/.test(normalized)) return 'No';
    if (/\b(yes|include|included|apply|applies|has|have)\b/.test(normalized)) return 'Yes';
    return 'N/A';
}

// Return the missing-tooth-clause answer only; do not emit the complete notice.
function collectMissingToothClause() {
    const benefitDiv = document.getElementById('benefits') || document;
    const elements = Array.from(benefitDiv.querySelectorAll('p, div, li, td, .Disclaimer'));
    for (const element of elements) {
        const value = getMissingToothClauseValue(clean(element.textContent));
        if (value !== 'N/A') return value;
    }
    return 'N/A';
}

// NEW HELPER: fallback for `dependent_age_limit` in case the notice ever sits outside
// div#benefits on a differently structured DDRI page. collectProvisions() (searched first,
// see startCrawl()) already covers the normal case.
function collectDependentAgeLimit() {
    const candidates = Array.from(document.querySelectorAll('p, div, li, td'));
    for (const el of candidates) {
        const text = clean(el.textContent);
        if (text.includes("Dependent children")) return text;
    }
    return "N/A";
}

// NEW HELPER: pulls an age-related clause (e.g. "under age 19") out of a Frequency/Limitations
// string. The new benefit table (see collectBenefitCategories()) doesn't have a dedicated "age
// limit" column — age restrictions are expressed inline in that text — so this is used by
// findLimits() inside collectProcedures() to populate each procedure's age_limit.
// Benefit matching uses descriptions, never CDT codes, so new codes can inherit the
// appropriate plan limitation without a code-specific release.
const BENEFIT_MATCH_DEBUG = false;

function normalizeText(text) {
    return clean(text).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/[–—]/g, '-').replace(/\bx[ -]?rays?\b|\bradiographs?\b|\bfilms?\b/g, ' xray ')
        .replace(/[^a-z0-9]+/g, ' ').trim();
}

function tokenize(text) {
    return normalizeText(text).split(/\s+/).filter(Boolean).map(token =>
        token.length > 3 && token.endsWith('ies') ? `${token.slice(0, -3)}y` :
        (token.length > 3 && token.endsWith('s') && !token.endsWith('ss') ? token.slice(0, -1) : token));
}

function removeStopWords(tokens) {
    const words = new Set(['a', 'an', 'and', 'or', 'the', 'of', 'to', 'for', 'with', 'on', 'in', 'by', 'per',
        'procedure', 'service', 'treatment', 'dental', 'teeth', 'tissue', 'existing', 'other', 'related',
        'following', 'active', 'natural', 'permanent', 'adult', 'child', 'children']);
    return tokens.filter(token => !words.has(token));
}

// Canonical clinical concepts make equivalent wording comparable while retaining the original
// benefit row as the source of all returned values.
function expandSynonyms(tokens) {
    const aliases = {
        evaluation: 'exam', examination: 'exam', exam: 'exam', oralexam: 'exam',
        prophylaxi: 'cleaning', prophy: 'cleaning', cleaning: 'cleaning', fluorid: 'fluoride', fluoride: 'fluoride',
        composite: 'filling', resin: 'filling', amalgam: 'filling', filling: 'filling', restoration: 'filling',
        denture: 'denture', partial: 'denture', complete: 'denture', prosthesi: 'denture',
        implant: 'implantprosthetic', abutment: 'implantprosthetic', pontic: 'implantprosthetic', bridge: 'implantprosthetic',
        scaling: 'periodontaltherapy', planing: 'periodontaltherapy', srp: 'periodontaltherapy',
        endodontic: 'rootcanal', endo: 'rootcanal', canal: 'rootcanal', orthodontic: 'orthodontic', brace: 'orthodontic',
        extraction: 'extraction', extract: 'extraction', surgery: 'extraction', anesthesia: 'sedation',
        anaesthesia: 'sedation', sedation: 'sedation', intravenous: 'sedation', reline: 'reline', rebas: 'reline',
        repair: 'repair', gingivectomy: 'gingivectomy', osseou: 'osseous', graft: 'graft', lengthening: 'lengthening',
        maintainer: 'maintainer', maintenance: 'maintenance', palliative: 'palliative'
    };
    return tokens.map(token => {
        // Periapical and occlusal images are represented by the generic single-image benefit row.
        if (token === 'periapical' || token === 'occlusal' || token === 'single') return 'singleimage';
        return aliases[token] || token;
    });
}

function getMatchTokens(text) {
    // Resolve multi-word concepts before tokenization, making word order and punctuation harmless.
    const phrases = normalizeText(text)
        .replace(/oral\s+(evaluation|examination|exam)/g, ' oralexam ')
        .replace(/root\s+canal/g, ' rootcanal ').replace(/root\s+planing/g, ' periodontaltherapy ')
        .replace(/complete\s+(series|set)\s+(of\s+)?(xray|images?)/g, ' fullxrayseries ')
        .replace(/panoramic\s+(xray|image)/g, ' panoramic fullxrayseries ')
        .replace(/bitewing\s+(xray|image)/g, ' bitewing ')
        .replace(/implant\s+(crown|bridge)/g, ' implantprosthetic ');
    return expandSynonyms(removeStopWords(tokenize(phrases)));
}

function calculateSimilarity(procedureText, benefitText) {
    const procedureTokens = [...new Set(getMatchTokens(procedureText))];
    const benefitTokens = [...new Set(getMatchTokens(benefitText))];
    if (!procedureTokens.length || !benefitTokens.length) return 0;
    const benefitSet = new Set(benefitTokens);
    const common = procedureTokens.filter(token => benefitSet.has(token));
    if (!common.length) return 0;
    const procedureCoverage = common.length / procedureTokens.length;
    const benefitCoverage = common.length / benefitTokens.length;
    const jaccard = common.length / new Set([...procedureTokens, ...benefitTokens]).size;
    return Number((0.65 * procedureCoverage + 0.25 * benefitCoverage + 0.10 * jaccard).toFixed(4));
}

// Return only an age restriction, not the entire frequency/limitations sentence.
function extractAgeLimit(text) {
    if (!text) return 'N/A';
    const source = clean(text);
    const number = '(?:\\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|twenty[ -]one|twenty[ -]two|twenty[ -]three|twenty[ -]four|twenty[ -]five|twenty[ -]six)';
    const patterns = [
        new RegExp(`\\b(?:dependent\\s+)?children\\s+(?:under|through|to)\\s+(?:the\\s+)?(?:age\\s+(?:of\\s+)?)?${number}\\b`, 'i'),
        new RegExp(`\\bstudents?\\s+(?:through|to|under)\\s+(?:the\\s+)?(?:age\\s+(?:of\\s+)?)?${number}\\b`, 'i'),
        new RegExp(`\\b(?:under|younger\\s+than)\\s+(?:the\\s+)?(?:age\\s+(?:of\\s+)?)?${number}\\b`, 'i'),
        new RegExp(`\\b(?:through|to)\\s+age\\s+(?:of\\s+)?${number}\\b`, 'i'),
        new RegExp(`\\bage\\s+(?:of\\s+)?${number}\\b`, 'i'), /\bdependent children\b/i
    ];
    const match = patterns.map(pattern => source.match(pattern)).find(Boolean);
    return match ? clean(match[0]) : 'N/A';
}

function findBestBenefitMatch(description, benefitCategories, threshold = 0.45) {
    let best = null;
    for (const category of benefitCategories) {
        for (const service of category.services || []) {
            const similarity = calculateSimilarity(description, service.procedure);
            if (!best || similarity > best.similarity) best = { service, category: category.category, similarity };
        }
    }
    return best && best.similarity >= threshold ? best : null;
}

// NEW HELPER (replaces the old `benefitDiv.querySelector('table')`, which grabbed whichever
// table happened to appear FIRST inside #benefits). #benefits actually contains 3 tables in
// order: a small Deductibles table, the hidden Procedure Code Look-up form table, and finally
// the real benefit table -- so the old code was always scraping the wrong (Deductibles) table.
// This instead finds the table by its header text ("Procedure" + "Frequency"/"Limitations"),
// which is stable even if DDRI changes class names or table order.
function findBenefitTable() {
    const container = document.getElementById('benefits') || document;
    const tables = Array.from(container.querySelectorAll('table'));

    // Primary: match on <thead> header text
    for (const table of tables) {
        const headerCells = Array.from(table.querySelectorAll('thead th, thead td'));
        if (headerCells.length === 0) continue;
        const headerText = headerCells.map(c => clean(c.textContent).toLowerCase()).join(' | ');
        if (headerText.includes('procedure') && (headerText.includes('frequency') || headerText.includes('limitation'))) {
            return table;
        }
    }

    // Fallback: some markup variants may not use a <thead> tag at all -- check each table's
    // first row instead.
    for (const table of tables) {
        const firstRow = table.querySelector('tr');
        if (!firstRow) continue;
        const text = clean(firstRow.textContent).toLowerCase();
        if (text.includes('procedure') && (text.includes('frequency') || text.includes('limitation'))) {
            return table;
        }
    }

    return null;
}

function collectBenefitCategories() {
    const categories = [];
    const table = findBenefitTable();
    if (!table) return categories;

    let rows = Array.from(table.querySelectorAll('tbody tr'));
    if (rows.length === 0) rows = Array.from(table.querySelectorAll('tr'));

    let currentCat = null;
    for (const row of rows) {
        const cells = Array.from(row.querySelectorAll('td'));
        if (cells.length === 0) continue; // header row (th only) or an empty spacer row

        // MODIFIED: section header rows (DIAGNOSTIC, PREVENTIVE, ...) render as a single cell
        // spanning the full table width via colspan. This structural signal replaces the old
        // hardcoded '.TRhBEN' class check, so it survives markup/class changes.
        const spanningCell = cells.find(c => parseInt(c.getAttribute('colspan') || '1', 10) > 1);
        if (cells.length === 1 || spanningCell) {
            const text = clean((spanningCell || cells[0]).textContent);
            if (text) {
                currentCat = { category: text, services: [] };
                categories.push(currentCat);
            }
            continue;
        }

        // MODIFIED: data rows are [indicator icon (optional), procedure, covered at, waiting
        // period, frequency/limitations]. Some rows have a leading icon-only cell (prior-auth /
        // pre-treatment indicators) and some don't, so anchor from the END of the row (last 4
        // cells) instead of a fixed index -- this replaces the old '.DataTableRow' class check.
        if (!currentCat || cells.length < 4) continue;

        const n = cells.length;
        const procedure = clean(cells[n - 4].textContent);
        if (!procedure) continue;

        currentCat.services.push({
            procedure: procedure,
            covered_at: clean(cells[n - 3].textContent),
            waiting_period: clean(cells[n - 2].textContent),
            frequency_limitations: clean(cells[n - 1].textContent)
        });
    }
    return categories;
}

function getHiddenParams() {
    return {
        memberId: document.getElementById('MemberId')?.value || "",
        groupNumber: document.getElementById('GroupNumber')?.value || "",
        divisionNumber: document.getElementById('DivisionNumber')?.value || "",
        effectiveDate: document.getElementById('SelectedEffectiveDate')?.value || ""
    };
}

async function fetchProcedure(code, params) {
    const rawCode = code.replace(/^D/i, '');
    const txt = el => (el?.textContent || '').replace(/[\n\r\t]/g, ' ').replace(/\s+/g, ' ').trim();
    // Keep the procedure entry schema complete even when DDRI returns an empty table cell.
    // Property order here is the order used in the generated audit JSON.
    const valueOrNA = el => txt(el) || 'N/A';
    const createStatusProcedure = (description, coverageStatus) => ({
        procedure_code: code,
        description,
        coverage_status: coverageStatus,
        coverage_percentage: "N/A",
        deductible_applies: "N/A",
        waiting_period: "N/A",
        alternate_benefit: "N/A",
        frequency: "N/A",
        age_limit: "N/A",
        history: []
    });
    const setStatus = (data, status) => Object.defineProperty(data, '_ddriStatus', {
        value: status,
        enumerable: false
    });

    // This is deliberately text-based rather than class-based: DDRI has changed the
    // markup around this message, but its wording remains the reliable signal.
    const isNotCoveredResponse = html => {
        const text = normalizeText(new DOMParser().parseFromString(html || '', 'text/html').body?.textContent || html);
        return text.includes('not a covered benefit') ||
            text.includes('not covered benefit') ||
            text.includes('not a covered benefit under this patient s contract') ||
            text.includes('not covered under this patient s contract') ||
            text.includes('not covered');
    };

    let procData;
    
    try {
        const response = await fetch('/BenefitsAndClaims/GetProcedureCode', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest',
                'x-validation-header': 'DDRI'
            },
            body: `Code=${rawCode}`
        });
        if (!response.ok) {
            console.error(`[DDRI] ${code} - SCRAPE ERROR`, `Procedure lookup returned HTTP ${response.status}`);
            return setStatus(createStatusProcedure("SCRAPE ERROR", "SCRAPE ERROR"), 'error');
        }

        const html = await response.text();
        if (isNotCoveredResponse(html)) {
            console.debug(`[DDRI] ${code} - NOT COVERED`);
            return setStatus(createStatusProcedure("N/A", "NOT COVERED"), 'not-covered');
        }

        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const table = doc.getElementById('ProcedureCodeSearchResult');
        
        if (table) {
            const rows = table.querySelectorAll('tr');
            const requestedCode = code.toUpperCase();
            const headerLabels = new Set([
                'covered at', 'deductible applies', 'waiting period',
                'alternate benefit may apply', 'procedure', 'cdt code'
            ]);
            const isHeaderLabel = value => headerLabels.has(normalizeText(value));

            // DDRI can render its header, explanatory, and data rows using the same TD
            // markup. Identify the result by its actual CDT cell before reading positions.
            const dataRow = Array.from(rows).find(row => {
                const cells = row.querySelectorAll('td');
                if (cells.length < 6 || clean(cells[0].textContent).toUpperCase() !== requestedCode) {
                    return false;
                }

                // Never allow column labels from a header-like row into the audit JSON.
                return Array.from(cells).slice(1, 6)
                    .every(cell => !isHeaderLabel(clean(cell.textContent)));
            });
            if (dataRow) {
                const cells = dataRow.querySelectorAll('td');
                procData = {
                    procedure_code: code,
                    description: valueOrNA(cells[1]),
                    coverage_status: "COVERED",
                    coverage_percentage: valueOrNA(cells[2]),
                    deductible_applies: valueOrNA(cells[3]),
                    waiting_period: valueOrNA(cells[4]),
                    alternate_benefit: valueOrNA(cells[5]),
                    frequency: "N/A",
                    age_limit: "N/A",
                    history: []
                };
            }
        }
    } catch (e) {
        console.error(`[DDRI] ${code} - SCRAPE ERROR`, e);
        return setStatus(createStatusProcedure("SCRAPE ERROR", "SCRAPE ERROR"), 'error');
    }

    // If the portal returns a successful response but the requested CDT code is not
    // present in the result, treat that as NOT COVERED rather than SCRAPE ERROR.
    // Actual network/server failures above still remain SCRAPE ERROR.
    if (!procData) {
        console.debug(`[DDRI] ${code} - NOT COVERED`, 'Requested CDT code was not present in the portal response');
        return setStatus(
            createStatusProcedure("N/A", "NOT COVERED"),
            'not-covered'
        );
    }

    setStatus(procData, 'covered');
    console.debug(`[DDRI] ${code} - COVERED`);

    try {
        const reqBody = `StartDate=7&ProcedureCode=${rawCode}&ToothNumber=&MemberId=${params.memberId}&GroupNumber=${params.groupNumber}&DivisionNumber=${params.divisionNumber}`;
        const response = await fetch('/BenefitsAndClaims/GetToothHistory', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest',
                'x-validation-header': 'DDRI'
            },
            body: reqBody
        });
        const html = await response.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const table = doc.querySelector('.ToothHistorySearchResults');
        
        if (table) {
            const rows = table.querySelectorAll('tbody tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 5) {
                    const svc_date = txt(cells[2]);
                    if (svc_date && svc_date !== 'NA' && svc_date !== '' && svc_date !== '\u00a0') {
                        procData.history.push({
                            service_date: svc_date,
                            tooth_number: valueOrNA(cells[3]),
                            tooth_surface: valueOrNA(cells[4]),
                            history_notes: "NA"
                        });
                    }
                }
            }
        }
    } catch (e) {
        console.error(`Error fetching history for ${code}:`, e);
    }

    return procData;
}

async function collectProcedures(requestedCodes = null) {
    const resultsByCode = new Map();
    const params = getHiddenParams();
    
    if (!params.memberId) {
        throw new Error("No MemberId found. Cannot crawl procedures.");
    }

    const BATCH_SIZE = 10;
    // Preserve caller order while preventing accidental duplicate lookups/results. The normal
    // audit always uses PROCEDURE_CODES, which contains the required 50 CDT codes.
    const codes = [...new Set(requestedCodes || PROCEDURE_CODES)];
    
    const benefitCats = collectBenefitCategories();

    for (let i = 0; i < codes.length; i += BATCH_SIZE) {
        const batch = codes.slice(i, i + BATCH_SIZE);
        const batchNum = Math.floor(i / BATCH_SIZE) + 1;
        const totalBatches = Math.ceil(codes.length / BATCH_SIZE);
        const pct = Math.round((i/codes.length)*100);
        
        broadcastState("FETCHING PROCEDURES", "Fetching Procedures", `Batch ${batchNum} of ${totalBatches}`, pct);
        
        const batchPromises = batch.map(async (code) => {
            try {
                const data = await fetchProcedure(code, params);
                if (data && data._ddriStatus === 'covered') {
                // Every fetched description is compared with every benefit-table service. No CDT
                // code or sample-plan-specific branching is used here.
                const match = findBestBenefitMatch(data.description, benefitCats);
                if (match) {
                    data.frequency = match.service.frequency_limitations || 'N/A';
                    data.age_limit = extractAgeLimit(match.service.frequency_limitations);

                    // These values already exist in the procedure response. Keep that response
                    // authoritative unless it is absent, then inherit the matched plan value.
                    if (!data.waiting_period || data.waiting_period === 'N/A') {
                        data.waiting_period = match.service.waiting_period || 'N/A';
                    }
                    if ((!data.coverage_percentage || data.coverage_percentage === 'N/A') && match.service.covered_at) {
                        data.coverage_percentage = match.service.covered_at;
                    }
                    if (BENEFIT_MATCH_DEBUG) {
                        console.debug('[DDRI] Benefit match', {
                            procedure: data.description,
                            matched: match.service.procedure,
                            category: match.category,
                            similarity: match.similarity,
                            frequency: data.frequency
                        });
                    }
                } else if (BENEFIT_MATCH_DEBUG) {
                    console.debug('[DDRI] No benefit match', { procedure: data.description });
                }
                }
                return data;
            } catch (error) {
                // A defensive final boundary: no unexpected matching/parsing exception may
                // reject Promise.all and prevent the remaining CDT codes from being crawled.
                console.error(`[DDRI] ${code} - SCRAPE ERROR`, error);
                return {
                    procedure_code: code,
                    description: "SCRAPE ERROR",
                    coverage_status: "SCRAPE ERROR",
                    coverage_percentage: "N/A",
                    deductible_applies: "N/A",
                    waiting_period: "N/A",
                    alternate_benefit: "N/A",
                    frequency: "N/A",
                    age_limit: "N/A",
                    history: []
                };
            }
        });

        const batchResults = await Promise.all(batchPromises);
        batchResults.forEach(r => { if (r) resultsByCode.set(r.procedure_code, r); });
        
        if (i + BATCH_SIZE < codes.length) {
            await sleep(150);
        }
    }
    
    // Keep exactly one record per requested code and return them in the request order even if
    // concurrent batches complete out of order. The fallback protects the final JSON if an
    // unexpected coding error occurs outside fetchProcedure's own error handling.
    return codes.map(code => resultsByCode.get(code) || setStatus({
        procedure_code: code,
        description: "SCRAPE ERROR",
        coverage_status: "SCRAPE ERROR",
        coverage_percentage: "N/A",
        deductible_applies: "N/A",
        waiting_period: "N/A",
        alternate_benefit: "N/A",
        frequency: "N/A",
        age_limit: "N/A",
        history: []
    }, 'error'));
}

function generateJSON(auditData) {
    return {
        ...auditData,
        ddri_data: true
    };
}

function generatePatientNotesJSON(auditData) {
    const getFin = (catLower) => {
        if (!auditData.financials) return "";
        for (const item of (auditData.financials.maximums || [])) {
            if (item.category.toLowerCase().includes(catLower)) return item.used || "";
        }
        return "";
    };

    const getHistory = (code) => {
        if (!auditData.benefit_coverage || !auditData.benefit_coverage.procedures) return "";
        const proc = auditData.benefit_coverage.procedures.find(p => p.procedure_code === code);
        if (!proc || !proc.history || proc.history.length === 0) return "";
        const sorted = [...proc.history].sort((a, b) => new Date(b.service_date) - new Date(a.service_date));
        return sorted[0].service_date;
    };

    return {
        "appointment_date": "",
        "verified_by": "",
        "verification_date": new Date().toLocaleDateString(),
        "eligibility_status": auditData.patient?.eligibility_status || "",
        "carrier": "DDRI",
        "primary_or_secondary": "",
        "plan_type": auditData.patient?.plan_type || "",
        "patient_assigned_to_office": "",

        "individual_maximum_used": getFin("annual max"),
        "ortho_maximum_used": getFin("orthodontic"),

        "history_periodic_exam_d0120": getHistory("D0120"),
        "history_comp_exam_d0150": getHistory("D0150"),
        "history_prophy_d1110": getHistory("D1110"),
        "history_perio_maint_d4910": getHistory("D4910"),
        "history_fmd_d4355": getHistory("D4355"),
        "history_fluoride_d1206_d1208": getHistory("D1206") || getHistory("D1208"),
        "history_xray_d0274": getHistory("D0274"),
        "history_xray_d0210": getHistory("D0210")
    };
}

async function downloadJSON(data) {
    return new Promise(resolve => {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const patient = data?.patient?.name?.replace(/[^a-z0-9]/gi, "_")?.toLowerCase() || "patient";
        a.download = `${patient}_ddri_audit.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        setTimeout(resolve, 500);
    });
}

function validatePage() {
    return !!document.querySelector('.SubscriberProfile');
}

async function clearPreviousSession(clearCachedNotes = true) {
    const keysToClear = [STORAGE_KEYS.PROGRESS, STORAGE_KEYS.AUDIT_CONTEXT, 'crawl_progress', 'partial_json', 'audit_context'];
    if (clearCachedNotes) {
        keysToClear.push(STORAGE_KEYS.CACHED_PATIENT_NOTES);
        keysToClear.push('cached_patient_notes');
    }
    const safeKeys = keysToClear.filter(Boolean);
    await new Promise(resolve => chrome.storage.local.remove(safeKeys, resolve));
}

let isCrawling = false;
let timeoutHandle = null;

function resetCacheTimeout() {
    if (timeoutHandle) clearTimeout(timeoutHandle);
    timeoutHandle = setTimeout(async () => {
        await clearPreviousSession(true);
        console.log("[DDRI] Cache timeout expired. Cleaned up.");
    }, 60000); // 60 seconds
}

async function startCrawl() {
    if (isCrawling) return;
    isCrawling = true;
    try {
        await clearPreviousSession(true);
        logState("STARTING");
        broadcastState("STARTING", "Initializing...");
        
        const auditData = {};
        
        logState("COLLECTING PATIENT");
        broadcastState("COLLECTING PATIENT", "Collecting Patient Data", "Extracting subscriber info...", 10);
        auditData.patient = collectPatient();
        
        logState("COLLECTING PLAN");
        broadcastState("COLLECTING PLAN", "Collecting Plan Details", "Extracting plan limits...", 20);
        auditData.plan_details = collectPlan();
        
        logState("COLLECTING FINANCIALS");
        broadcastState("COLLECTING FINANCIALS", "Collecting Financials", "Extracting deductibles and maximums...", 30);
        auditData.financials = collectFinancials();
        
        logState("COLLECTING BENEFIT CATEGORIES");
        auditData.benefit_categories = collectBenefitCategories();

        // NEW: collectProvisions() was previously defined but never called, so its output
        // never reached the final JSON. Wiring it in here to populate the two new top-level
        // fields requested: missing_tooth_clause and dependent_age_limit.
        logState("COLLECTING PROVISIONS");
        auditData.missing_tooth_clause = collectMissingToothClause();
        const provisions = collectProvisions();
        auditData.dependent_age_limit = provisions.find(p => p.rule === "Dependent Age Limit")?.value || collectDependentAgeLimit();

        logState("FETCHING PROCEDURES");
        auditData.benefit_coverage = { procedures: await collectProcedures() };
        
        logState("GENERATING JSON");
        broadcastState("GENERATING JSON", "Preparing Audit", "Generating JSON...");
        const finalJson = generateJSON(auditData);
        const patientNotes = generatePatientNotesJSON(auditData);
        
        await new Promise(resolve => chrome.storage.local.set({ 
            [STORAGE_KEYS.AUDIT_CONTEXT]: finalJson,
            [STORAGE_KEYS.CACHED_PATIENT_NOTES]: patientNotes 
        }, resolve));
        
        logState("INITIATING DOWNLOAD");
        broadcastState("DOWNLOADING", "Downloading Audit JSON...");
        await downloadJSON(finalJson);
        
        logState("CLEANUP");
        await clearPreviousSession(false); // Keep cached_patient_notes for subsequent manual download
        resetCacheTimeout();
        
        logState("COMPLETE");
        broadcastState("COMPLETE", "Download Complete", "Audit Saved Successfully");
        
    } catch (err) {
        logState("FAILED");
        broadcastState("FAILED", "Audit Failed", err.message);
        await clearPreviousSession(true);
    } finally {
        isCrawling = false;
    }
}

async function startLightweightCrawl() {
    if (isCrawling) return;
    isCrawling = true;
    try {
        await clearPreviousSession(true);
        logState("STARTING LIGHTWEIGHT");
        broadcastState("STARTING", "Initializing Patient JSON...");
        
        const auditData = {};
        
        auditData.patient = collectPatient();
        auditData.plan_details = collectPlan();
        auditData.financials = collectFinancials();
        
        // Patient-note generation also performs the complete benefit crawl so every patient
        // receives the same 50-code audit data before the selected note fields are extracted.
        auditData.benefit_coverage = { procedures: await collectProcedures() };
        
        const patientNotes = generatePatientNotesJSON(auditData);
        
        broadcastState("DOWNLOADING", "Downloading Patient JSON...");
        await downloadJSON(patientNotes);
        
        await clearPreviousSession(true);
        
        broadcastState("COMPLETE", "Download Complete", "Patient JSON Saved");
    } catch (err) {
        broadcastState("FAILED", "Audit Failed", err.message);
        await clearPreviousSession(true);
    } finally {
        isCrawling = false;
    }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.command === "START_CRAWL") {
        startCrawl();
        sendResponse({ status: "ACK" });
        return true;
    } else if (request.command === "GENERATE_PATIENT_JSON" || request.command === "DOWNLOAD_JSON") {
        chrome.storage.local.get([STORAGE_KEYS.CACHED_PATIENT_NOTES], async (result) => {
            const cached = result[STORAGE_KEYS.CACHED_PATIENT_NOTES];
            if (cached) {
                broadcastState("DOWNLOADING", "Downloading Patient JSON...");
                await downloadJSON(cached);
                await clearPreviousSession(true);
                if (timeoutHandle) clearTimeout(timeoutHandle);
                broadcastState("COMPLETE", "Download Complete", "Patient JSON Saved");
            } else {
                startLightweightCrawl();
            }
            sendResponse({ status: "ACK" });
        });
        return true;
    }
});

// Initialization: check if we just loaded a page
logState("READY");
