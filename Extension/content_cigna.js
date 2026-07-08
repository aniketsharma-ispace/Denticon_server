const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
const getVal = (selector) => document.querySelector(`[data-test-id="${selector}"]`)?.innerText?.trim() || "N/A";

// ── Code lists ─────────────────────────────────────────────────────────────
const STATIC_CODES   = ["D0120","D0150","D1110","D4910","D4355","D0274","D0210"];
const SPECIAL_CODES  = ["D1510"];
const AGE_GATED_LIST = ["D1206","D1208","D1351","D8080"];
const AGE_GATED_META = {
    "D1206": { maxAge: 18, label: "Topical Fluoride" },
    "D1208": { maxAge: 18, label: "Topical Fluoride" },
    "D1351": { maxAge: 13, label: "Topical Sealant" },
    "D8080": { maxAge: null, label: "Orthodontics" },
};
const QUADRANT_CODES = { "D1510": "LR" };
const TOOTH_CODES    = { "D1351": "1" };

// ══════════════════════════════════════════════════════════════════════════
// PAGE LOCK
// ══════════════════════════════════════════════════════════════════════════

let _overlay = null;
function lockPage() {
    if (_overlay) return;
    _overlay = document.createElement('div');
    Object.assign(_overlay.style, {
        position:'fixed', top:'0', left:'0', width:'100vw', height:'100vh',
        zIndex:'2147483647', background:'rgba(0,0,0,0.22)', cursor:'not-allowed',
        display:'flex', alignItems:'center', justifyContent:'center', pointerEvents:'all', userSelect:'none',
    });
    _overlay.innerHTML = `
        <div style="background:#fff;border-radius:12px;padding:28px 36px;
            box-shadow:0 4px 32px rgba(0,0,0,0.2);text-align:center;font-family:sans-serif;">
            <div style="font-size:22px;font-weight:700;color:#003087;margin-bottom:8px;">🔄 Cigna Crawl Running…</div>
            <div id="_cigna_status" style="font-size:14px;color:#555;">
                Please wait — do not scroll, click, or navigate.<br>
                The page will unlock automatically when done.
            </div>
        </div>`;
    ['click','mousedown','mouseup','touchstart','touchend','keydown','keyup','scroll','wheel']
        .forEach(e => _overlay.addEventListener(e, ev => ev.stopImmediatePropagation(), true));
    document.body.appendChild(_overlay);
    document.body.style.overflow = 'hidden';
}
function setStatus(msg) {
    const el = document.getElementById('_cigna_status');
    if (el) el.innerHTML = msg;
    console.log('Cigna:', msg);
}
function unlockPage() {
    if (_overlay) { _overlay.remove(); _overlay = null; }
    document.body.style.overflow = '';
}

// ══════════════════════════════════════════════════════════════════════════
// UTILITIES
// ══════════════════════════════════════════════════════════════════════════

function findByText(text, root = document.body) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode()))
        if (node.textContent.trim() === text) return node.parentElement;
    return null;
}
function findByPartialText(text, tags = ['button','a','span','div']) {
    for (const tag of tags) {
        const found = Array.from(document.querySelectorAll(tag))
            .find(el => el.innerText?.trim().includes(text) && el.children.length <= 2);
        if (found) return found;
    }
    return null;
}
async function waitFor(fn, timeout = 8000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { const r = fn(); if (r) return r; await sleep(200); }
    return null;
}
async function angularType(input, text) {
    input.focus();
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    const setVal = v => setter ? setter.call(input, v) : (input.value = v);
    setVal('');
    input.dispatchEvent(new Event('input',  { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await sleep(150);
    for (const char of text) {
        setVal(input.value + char);
        input.dispatchEvent(new Event('input',   { bubbles: true }));
        input.dispatchEvent(new KeyboardEvent('keydown',  { key: char, bubbles: true }));
        input.dispatchEvent(new KeyboardEvent('keypress', { key: char, bubbles: true }));
        input.dispatchEvent(new KeyboardEvent('keyup',    { key: char, bubbles: true }));
        await sleep(80);
    }
}

// ══════════════════════════════════════════════════════════════════════════
// PAGE SCRAPE — static data
// ══════════════════════════════════════════════════════════════════════════

// ── REPLACE parseCignaAmount ───────────────────────────────────────────────
function parseCignaAmount(text) {
    if (!text) return { remaining: "N/A", total: "N/A" };

    const isMet = /met\b/i.test(text);

    // extract all dollar amounts in order
    const amounts = [...text.matchAll(/\$\s*([\d,]+\.?\d*)/g)]
        .map(m => '$' + m[1].replace(/,/g, ''));

    // "Total:" line
    const totalM = text.match(/Total[:\s]+\$([\d,]+\.?\d*)/i);
    const total  = totalM ? '$' + totalM[1].replace(/,/g, '') : (amounts[amounts.length - 1] || "N/A");

    // remaining: if "Met" → $0.00, else first amount before Total
    let remaining;
    if (isMet) {
        remaining = "$0.00";
    } else {
        // first amount that isn't the total amount
        remaining = amounts.find(a => a !== total) || amounts[0] || "N/A";
    }

    return { remaining, total };
}

function scrapePatientDOB() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        if (node.textContent.trim() === 'Date of Birth') {
            const sib = node.parentElement?.nextElementSibling;
            if (sib) { const t = sib.innerText?.trim(); if (/\d{2}\/\d{2}\/\d{4}/.test(t)) return t; }
            const row = node.parentElement?.closest('tr,[class*="row"],li,div');
            if (row) { const m = row.innerText.match(/\d{2}\/\d{2}\/\d{4}/); if (m) return m[0]; }
        }
    }
    const m = document.body.innerText.match(/Date of Birth[\s\S]{0,40}?(\d{2}\/\d{2}\/\d{4})/);
    return m ? m[1] : null;
}

function scrapeCignaFull() {
    const data = {
        source: "Cigna Portal",
        timestamp: new Date().toISOString(),
        summary: {
            patient_id:   document.body.innerText.match(/Patient ID:\s*(.*)/)?.[1]?.trim() || "N/A",
            group_number: document.body.innerText.match(/Group Number:\s*(\d+)/)?.[1] || "N/A",
            group_name:   getVal("account-name") || "N/A",
            plan_type:    getVal("plan-type") || "N/A",
            coverage_dates: {
                from: document.body.innerText.match(/Coverage From:\s*([\d\/]+)/)?.[1] || "N/A",
                to:   document.body.innerText.match(/Coverage To:\s*(.*)/)?.[1]?.trim() || "N/A"
            }
        },
        patient: {
            name:         document.body.innerText.match(/^Name\s+([^\n]+)/m)?.[1]?.trim() || "N/A",
            dob:          scrapePatientDOB() || "N/A",
            gender:       document.body.innerText.match(/Gender\s+([^\n]+)/)?.[1]?.trim() || "N/A",
            relationship: document.body.innerText.match(/Relationship\s+([^\n]+)/)?.[1]?.trim() || "N/A",
        },
        // ── REPLACE financials inside scrapeCignaFull ─────────────────────────────
    financials: (() => {
    // ── Deductible card ───────────────────────────────────────────────
        const dedBox = document.querySelector('.deductible-box') ||
        (() => {
            const h = Array.from(document.querySelectorAll('h2,h3,[class*="title"],[class*="header"]'))
                .find(el => /deductible/i.test(el.innerText) && !/family/i.test(el.innerText));
            return h?.closest('[class*="card"],[class*="box"],[class*="panel"],section,div[class]');
        })();

    // individual deductible sub-section (left column)
        const dedIndText = (() => {
            if (!dedBox) return '';
        // look for the "Individual Calendar Year" sub-section only
            const walker = document.createTreeWalker(dedBox, NodeFilter.SHOW_TEXT, null, false);
            let node, capture = false, lines = [];
            while ((node = walker.nextNode())) {
                const t = node.textContent.trim();
                if (/individual calendar year deductible/i.test(t)) { capture = true; continue; }
                if (capture && /family calendar year/i.test(t)) break;
                if (capture && t) lines.push(t);
            }
            return lines.join('\n');
        })();
        const deductible_ind = parseCignaAmount(dedIndText || dedBox?.innerText || '');

    // ── Benefit Maximums card ─────────────────────────────────────────
        const maxCard = (() => {
            const h = Array.from(document.querySelectorAll('h2,h3,[class*="title"],[class*="header"]'))
                .find(el => /benefit maximums?/i.test(el.innerText));
            return h?.closest('[class*="card"],[class*="box"],[class*="panel"],section,div[class]') ||
               document.querySelector('.oop-box');
        })();

        const maxCardText = maxCard?.innerText || '';

    // split annual vs ortho within the card
        const orthoSplit = maxCardText.search(/\bOrthodontics\b/i);
        const annualText = orthoSplit > -1 ? maxCardText.slice(0, orthoSplit) : maxCardText;
        const orthoText  = orthoSplit > -1 ? maxCardText.slice(orthoSplit)    : '';
        const annual_max     = parseCignaAmount(annualText);
        const ortho_lifetime = parseCignaAmount(orthoText);

        return { annual_max, deductible_ind, ortho_lifetime };
    })(),
        coinsurance: Array.from(document.querySelectorAll('[data-test-id^="table-row-"]')).map(row => ({
            category:     row.querySelector('th')?.innerText?.replace('*', '').trim() || "N/A",
            patient_pays: row.querySelector('td')?.innerText?.trim() || "N/A"
        })),
        frequencies: Array.from(document.querySelectorAll('cigna-freq-age-limit table:first-of-type tbody tr')).map(row => {
            const cells = row.querySelectorAll('td');
            return { procedure: clean(cells[1]?.innerText), limit: clean(cells[2]?.innerText) };
        }).filter(r => r.procedure),
        age_limits: Array.from(document.querySelectorAll('cigna-freq-age-limit table:last-of-type tbody tr')).map(row => {
            const cells = row.querySelectorAll('td');
            if (cells.length < 2) return null;
            return { type: clean(cells[0]?.innerText), age: clean(cells[1]?.innerText), ends: clean(cells[2]?.innerText) };
        }).filter(Boolean),
        notes: {
            missing_tooth: document.body.innerText.includes("Missing Tooth Limitation and Waiting Period does not apply")
                ? "Does not apply" : "Verify",
            ortho_note: getVal("lbl-age-limitations-note") || "N/A"
        },
        procedures: {
            age_gate: {},
            codes_searched: [],
            count: 0,
            results: []
        }
    };
    return data;
}

// ══════════════════════════════════════════════════════════════════════════
// AGE GATE
// ══════════════════════════════════════════════════════════════════════════

function readAgeLimitsFromPage() {
    const result = {};
    document.querySelectorAll('cigna-freq-age-limit table:first-of-type tbody tr').forEach(row => {
        const t = row.innerText || '';
        const m = t.match(/[Ee]xclude after age\s+(\d+)/i);
        if (m) {
            if (/[Ff]luoride/i.test(t)) result.fluoride = parseInt(m[1], 10);
            if (/[Ss]ealant/i.test(t))  result.sealant  = parseInt(m[1], 10);
        }
    });
    document.querySelectorAll('cigna-freq-age-limit table:last-of-type tbody tr').forEach(row => {
        const cells = row.querySelectorAll('td');
        if (/ortho/i.test(cells[0]?.innerText))
            result.ortho = clean(cells[1]?.innerText).toLowerCase() === 'none' ? null : parseInt(cells[1]?.innerText, 10);
    });
    if (!Object.keys(result).length) {
        const b = document.body.innerText;
        const fm = b.match(/[Ff]luoride[\s\S]{0,120}[Ee]xclude after age\s+(\d+)/);
        if (fm) result.fluoride = parseInt(fm[1], 10);
        const sm = b.match(/[Ss]ealant[\s\S]{0,120}[Ee]xclude after age\s+(\d+)/);
        if (sm) result.sealant  = parseInt(sm[1], 10);
        if (/[Oo]rtho Age Limitation[\s\S]{0,80}None/i.test(b)) result.ortho = null;
    }
    console.log('Cigna: Portal age limits:', result);
    return result;
}

function calcAge(dobStr) {
    let dob;
    if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(dobStr)) {
        const [m, d, y] = dobStr.split('/');
        dob = new Date(`${y}-${m.padStart(2,'0')}-${d.padStart(2,'0')}`);
    } else if (/^\d{4}-\d{2}-\d{2}$/.test(dobStr)) {
        dob = new Date(dobStr);
    } else return null;
    const today = new Date();
    let age = today.getFullYear() - dob.getFullYear();
    const mo = today.getMonth() - dob.getMonth();
    if (mo < 0 || (mo === 0 && today.getDate() < dob.getDate())) age--;
    return age;
}

function filterCodesByAge(ageLimits, patientDOB) {
    if (!patientDOB) { console.warn('Cigna: No DOB — including all age-gated codes'); return AGE_GATED_LIST; }
    const age = calcAge(patientDOB);
    if (age === null) { console.warn('Cigna: Cannot parse DOB'); return AGE_GATED_LIST; }
    console.log(`Cigna: Patient age = ${age}`);
    const allowed = [];
    for (const code of AGE_GATED_LIST) {
        const meta = AGE_GATED_META[code];
        let maxAge = meta.maxAge;
        if (code === 'D1206' || code === 'D1208') maxAge = ageLimits.fluoride ?? meta.maxAge;
        else if (code === 'D1351')                 maxAge = ageLimits.sealant  ?? meta.maxAge;
        else if (code === 'D8080') {
            if (ageLimits.ortho === null || ageLimits.ortho === undefined) {
                console.log(`Cigna: ${code} — Ortho limit=None → INCLUDE`); allowed.push(code); continue;
            }
            maxAge = ageLimits.ortho;
        }
        if (maxAge === null || maxAge === undefined || age < maxAge) {
            console.log(`Cigna: ${code} — age ${age} < ${maxAge} → INCLUDE`); allowed.push(code);
        } else {
            console.log(`Cigna: ${code} — age ${age} >= ${maxAge} → EXCLUDE ❌`);
        }
    }
    return allowed;
}

// ══════════════════════════════════════════════════════════════════════════
// ACCORDION HELPERS
// ══════════════════════════════════════════════════════════════════════════

async function ensureAccordionOpen(labelText) {
    const all = Array.from(document.querySelectorAll(
        '[class*="collapsible"],[class*="accordion"],[class*="panel-header"],button,a'
    ));
    const header = all.find(el => el.innerText?.trim().includes(labelText));
    if (header) {
        const open = header.getAttribute('aria-expanded') === 'true' ||
                     header.classList.contains('expanded') || header.classList.contains('open');
        if (!open) { header.click(); await sleep(1500); }
        return true;
    }
    const link = findByText(labelText) || findByPartialText(labelText);
    if (link) { link.click(); await sleep(1500); return true; }
    return false;
}

// ══════════════════════════════════════════════════════════════════════════
// PROCEDURE INPUT HELPERS
// ══════════════════════════════════════════════════════════════════════════

function getProcedureSection() {
    return (
        document.querySelector('[class*="procedure-code-search"],[class*="ProcedureCodeSearch"]') ||
        (() => { const h = findByPartialText("Procedure Code Lookup"); return h?.closest('section,[class*="panel"],[class*="card"],div[class]'); })() ||
        (() => { const b = Array.from(document.querySelectorAll('button')).find(b => b.innerText?.trim() === 'Submit'); return b?.closest('section,[class*="panel"],div[class]'); })()
    );
}

function getAllProcedureInputs() {
    const root = getProcedureSection() || document.body;
    return Array.from(root.querySelectorAll('input[type="text"],input:not([type])')).filter(inp => {
        const ph = (inp.placeholder || '').toLowerCase();
        return !(ph.includes('1-32') || ph.includes('as-ts') || ph.includes('tooth') || ph.includes('51-82'));
    });
}

function findEmptyProcedureInput() {
    const inputs = getAllProcedureInputs();
    for (let i = inputs.length - 1; i >= 0; i--)
        if (!inputs[i].value || inputs[i].value.trim() === '') return inputs[i];
    return null;
}

// ══════════════════════════════════════════════════════════════════════════
// AUTOCOMPLETE
// ══════════════════════════════════════════════════════════════════════════

async function clickAutocompleteSuggestion(codeStr, timeout = 7000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
        const s = (
            Array.from(document.querySelectorAll('mat-option')).find(el => el.innerText?.trim().startsWith(codeStr)) ||
            Array.from(document.querySelectorAll('[role="option"]')).find(el => el.innerText?.trim().startsWith(codeStr)) ||
            Array.from(document.querySelectorAll('[role="listbox"] li')).find(el => el.innerText?.trim().startsWith(codeStr)) ||
            Array.from(document.querySelectorAll('li,[class*="option"],[class*="suggestion"]'))
                .find(el => el.innerText?.trim().startsWith(codeStr) && el.offsetParent !== null)
        );
        if (s) { s.click(); await sleep(700); return true; }
        await sleep(200);
    }
    console.warn(`Cigna: No autocomplete for ${codeStr}`);
    return false;
}

// ══════════════════════════════════════════════════════════════════════════
// QUADRANT SELECTION
// ══════════════════════════════════════════════════════════════════════════

function getRowContainerForInput(inputEl) {
    let el = inputEl.parentElement;
    while (el && el !== document.body) {
        const selects = el.querySelectorAll('select, mat-select');
        const inputsInEl = el.querySelectorAll('input[type="text"],input:not([type])');
        if (selects.length >= 1 && inputsInEl.length <= 3) return el;
        el = el.parentElement;
    }
    return null;
}

async function selectQuadrantForInput(inputEl, quadrantCode, timeout = 9000) {
    console.log(`Cigna: Selecting quadrant "${quadrantCode}" scoped to input row...`);
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
        const row = getRowContainerForInput(inputEl);
        if (!row) { await sleep(300); continue; }
        for (const sel of row.querySelectorAll('select')) {
            const hasQuadrantOptions = Array.from(sel.options).some(o => o.text.toUpperCase().startsWith('LR'));
            if (!hasQuadrantOptions) continue;
            const opt = Array.from(sel.options).find(o => o.text.toUpperCase().startsWith(quadrantCode));
            if (!opt) continue;
            if (sel.value === opt.value) { console.log(`Cigna: Quadrant already set ✓`); return true; }
            sel.value = opt.value;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
            await sleep(500);
            console.log(`Cigna: Native quadrant → "${opt.text}" ✓`);
            return true;
        }
        const matSelects = Array.from(row.querySelectorAll('mat-select'));
        const qSel = matSelects[matSelects.length - 1];
        if (qSel) {
            const cur = qSel.querySelector('.mat-select-value-text')?.innerText?.trim() || '';
            if (cur.toUpperCase().startsWith(quadrantCode)) { console.log(`Cigna: Quadrant already "${cur}" ✓`); return true; }
            qSel.click(); await sleep(700);
            const opt = Array.from(document.querySelectorAll('mat-option,[role="option"]'))
                .find(o => o.innerText?.trim().toUpperCase().startsWith(quadrantCode) && o.offsetParent !== null);
            if (opt) { opt.click(); await sleep(600); console.log(`Cigna: mat-select quadrant → "${opt.innerText?.trim()}" ✓`); return true; }
            document.body.click(); await sleep(400);
        }
        await sleep(300);
    }
    console.warn(`Cigna: Could not select quadrant "${quadrantCode}"`);
    return false;
}

// ══════════════════════════════════════════════════════════════════════════
// ENTER BATCH + SUBMIT
// ══════════════════════════════════════════════════════════════════════════

async function clearExistingCodes() {
    const btn = findByText("Clear all Codes") || findByPartialText("Clear all Codes");
    if (btn) { btn.click(); await sleep(1200); }
}

async function enterBatch(codes) {
    console.log(`Cigna: Entering batch [${codes.join(', ')}]`);
    for (let i = 0; i < codes.length; i++) {
        const code = codes[i];
        const input = await waitFor(() => {
            const inp = findEmptyProcedureInput();
            return (inp && inp.offsetParent !== null) ? inp : null;
        }, 10000);
        if (!input) { console.error(`Cigna: No empty input for ${code}`); continue; }
        setStatus(`Entering code ${i + 1}/${codes.length}: <b>${code}</b>`);
        await angularType(input, code);
        const selected = await clickAutocompleteSuggestion(code, 8000);
        if (!selected) {
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
            await sleep(900);
        } else {
            await sleep(900);
        }
        if (!input.value?.trim()) {
            console.warn(`Cigna: ${code} — input still empty, retrying`);
            await angularType(input, code);
            await clickAutocompleteSuggestion(code, 5000);
            await sleep(900);
        }
        if (QUADRANT_CODES[code]) {
            await waitFor(() => {
                const row = getRowContainerForInput(input);
                if (!row) return false;
                return Array.from(row.querySelectorAll('select')).some(sel =>
                    Array.from(sel.options).some(o => o.text.toUpperCase().startsWith('LR'))
                );
            }, 6000);
            await sleep(400);
            await selectQuadrantForInput(input, QUADRANT_CODES[code], 9000);
        }

        // ── ADD THIS BLOCK ────────────────────────────────────────────
        if (TOOTH_CODES[code]) {
            const toothVal = TOOTH_CODES[code];
            const row = getRowContainerForInput(input);
            if (row) {
                const toothInput = Array.from(row.querySelectorAll('input[type="text"],input:not([type])'))
                    .find(inp => {
                        const ph = (inp.placeholder || '').toLowerCase();
                        return ph.includes('1-32') || ph.includes('as-ts') || ph.includes('tooth');
                    });
                if (toothInput) {
                    await angularType(toothInput, toothVal);
                    await sleep(500);
                    console.log(`Cigna: Tooth set to "${toothVal}" for ${code}`);
                } else {
                    console.warn(`Cigna: Tooth input not found for ${code}`);
                }
            }
        }
        // ── END ADD ───────────────────────────────────────────────────
        if (i < codes.length - 1) {
            await sleep(700);
            const addBtn = (
                findByText("Add Additional Code") ||
                findByPartialText("Add Additional Code", ['button', 'a', 'span']) ||
                Array.from(document.querySelectorAll('button')).find(b => /add.*additional.*code/i.test(b.innerText))
            );
            if (addBtn) {
                addBtn.click();
                const prevCount = getAllProcedureInputs().length;
                await waitFor(() => getAllProcedureInputs().length > prevCount, 6000);
                await sleep(700);
            }
        }
    }
    await sleep(800);
    const submitBtn = findByText("Submit") ||
        Array.from(document.querySelectorAll('button')).find(b => b.innerText?.trim() === 'Submit');
    if (!submitBtn) { console.error("Cigna: Submit not found"); return false; }
    setStatus("Submitting codes… waiting for results");
    submitBtn.click();
    await sleep(6000);
    return true;
}

// ══════════════════════════════════════════════════════════════════════════
// RESULT ROW DISCOVERY
// ══════════════════════════════════════════════════════════════════════════
// Strategy: after Submit, Cigna renders a list of result rows. Each row's
// FIRST child element contains only the D-code and procedure name (no dollar
// amounts, no Maximum/Frequency labels). We find those header-child elements,
// then take their parentElement as the actual row container.
//
// This avoids the old approach of scanning all elements for D-codes (which
// matched the input fields where we just typed the codes).
// ══════════════════════════════════════════════════════════════════════════

function findResultRows() {

    let resultsContainer = null;

    const editBtn = Array.from(document.querySelectorAll('button'))
        .find(b =>
            /Edit Codes/i.test(b.innerText) ||
            /Generate Benefit Reference/i.test(b.innerText)
        );

    if (editBtn) {
        let el = editBtn.parentElement;

        while (el && el !== document.body) {
            if (/\bD\d{4}\b/.test(el.innerText)) {
                resultsContainer = el;
                break;
            }
            el = el.parentElement;
        }
    }

    if (!resultsContainer) {
        resultsContainer = getProcedureSection() || document.body;
    }

    console.log(
        'Cigna: Results container:',
        resultsContainer?.tagName,
        resultsContainer?.className?.slice(0, 80)
    );

    // ─────────────────────────────────────────────
    // Find ALL potential D-code elements
    // ─────────────────────────────────────────────

    const candidates = Array.from(
        resultsContainer.querySelectorAll('*')
    ).filter(el => {

        if (el.tagName === 'INPUT') return false;

        const txt = clean(el.innerText || '');

        return /\bD\d{4}\b/.test(txt);
    });

    console.log(`Cigna: ${candidates.length} D-code candidates`);

    // ─────────────────────────────────────────────
    // Group by likely shared row parent
    // ─────────────────────────────────────────────

    const parentCounts = new Map();

    for (const el of candidates) {

        let row = el;

        // walk upward until a reasonable row container
        for (let i = 0; i < 5; i++) {

            if (!row.parentElement) break;

            row = row.parentElement;

            const txt = clean(row.innerText || '');

            // row should contain ONE D-code
            const matches = txt.match(/\bD\d{4}\b/g) || [];

            if (matches.length === 1) {
                parentCounts.set(
                    row,
                    (parentCounts.get(row) || 0) + 1
                );
            }
        }
    }

    // pick containers appearing most often
    const rows = Array.from(parentCounts.entries())
        .sort((a, b) => b[1] - a[1])
        .map(([row]) => row)
        .filter(row => {

            const txt = clean(row.innerText || '');

            return (
                /\bD\d{4}\b/.test(txt) &&
                txt.length > 20
            );
        });

    // dedupe nested rows
    const finalRows = [];

    for (const row of rows) {

        const alreadyNested = finalRows.some(existing =>
            existing.contains(row) || row.contains(existing)
        );

        if (!alreadyNested) {
            finalRows.push(row);
        }
    }

    console.log(`Cigna: Final rows identified = ${finalRows.length}`);

    return finalRows;
}

// ══════════════════════════════════════════════════════════════════════════
// ROW CHEVRON — shallowest [aria-expanded] inside a row element
// ══════════════════════════════════════════════════════════════════════════

function getRowChevron(rowEl) {
    const all = Array.from(rowEl.querySelectorAll('[aria-expanded]'));
    if (!all.length) return null;
    let best = all[0], minDepth = Infinity;
    for (const el of all) {
        let d = 0, node = el;
        while (node && node !== rowEl) { d++; node = node.parentElement; }
        if (d < minDepth) { minDepth = d; best = el; }
    }
    return best;
}

// ══════════════════════════════════════════════════════════════════════════
// SCRAPE ONE ROW — reads ONLY the given row element's innerText
// Uses landmark headings (Maximum / Frequency / Coinsurance / History**)
// to isolate each data section before extracting values.
// ══════════════════════════════════════════════════════════════════════════

function scrapeOneRow(rowEl) {
    const fullText = rowEl.innerText || '';
    const lines    = fullText.split('\n').map(l => l.trim()).filter(Boolean);

    // ── Procedure code ────────────────────────────────────────────────
    const code = lines.find(l => /^D\d{4}\b/.test(l))?.match(/^(D\d{4})/)?.[1];
    if (!code) return null;

     // ── Description — multiline, stops at first landmark ─────────────
    const codeLineIdx = lines.findIndex(l => /^D\d{4}\b/.test(l));
    const descLines   = [];
    for (let i = codeLineIdx + 1; i < lines.length; i++) {
        const l = lines[i];
        if (/^(History\*{1,2}|Maximum|Frequency|Coinsurance|Quadrant|Alternate benefit|Not a covered service)/i.test(l)) break;
        if (/^\d{4}-\d{2}-\d{2}$/.test(l)) break;
        if (/^D\d{4}\b/.test(l)) break;
        descLines.push(l);
    }
    const description = clean(descLines.join(' ')) || 'N/A';

    // ── Covered status ────────────────────────────────────────────────
    const notCovered = /Not a covered service/i.test(fullText);

    // ── Landmark indices ──────────────────────────────────────────────
    const maxIdx   = lines.findIndex(l => /^Maximum$/i.test(l));
    const freqIdx  = lines.findIndex(l => /^Frequency$/i.test(l));
    const coinsIdx = lines.findIndex(l => /^Coinsurance$/i.test(l));
    const histIdx  = lines.findIndex(l => /^History\*{1,2}$/.test(l));

    function sliceBetween(start, end) {
        if (start === -1) return [];
        const to = (end === -1 || end === undefined) ? lines.length : end;
        return lines.slice(start + 1, to);
    }

    const maxLines   = sliceBetween(maxIdx,   freqIdx  !== -1 ? freqIdx  : coinsIdx !== -1 ? coinsIdx : histIdx);
    const freqLines  = sliceBetween(freqIdx,  coinsIdx !== -1 ? coinsIdx : histIdx  !== -1 ? histIdx  : lines.length);
    const coinsLines = sliceBetween(coinsIdx, histIdx  !== -1 ? histIdx  : lines.length);
    const histLines  = sliceBetween(histIdx,  lines.length);

    // ── Dollar amounts — Maximum section only ─────────────────────────
    const amtRx = /\$\s*([\d][\d\s,]*\.[\d]{2})/g;
    function extractAmounts(lineArr) {
        return [...lineArr.join(' ').matchAll(amtRx)].map(m => '$' + m[1].replace(/\s/g, ''));
    }

    const maxAmounts   = extractAmounts(maxLines);
    const indRemaining = maxAmounts[0] || 'N/A';
    const totalLine    = maxLines.find(l => /^Total[:\s]/i.test(l)) || '';
    const totalAmts    = extractAmounts([totalLine]);
    const maxTotal     = totalAmts[0] || maxAmounts[1] || 'N/A';

    // ── Frequency ─────────────────────────────────────────────────────
    const freqUsedLine  = freqLines.find(l => /\d+\s+of\s+\d+/i.test(l)) || '';
    const freqUsedM     = freqUsedLine.match(/(\d+)\s+of\s+(\d+)/i);
    const freqLimitLine = freqLines.find(l =>
        /^(Once|Twice|Three\s+times|\d+\s*times?)\b/i.test(l) ||
        /per\s+(calendar|benefit|plan)/i.test(l)
    ) || '';

    // ── Coinsurance ───────────────────────────────────────────────────
    const coinsPctLine = coinsLines.find(l => /\d+\s*%/.test(l)) || '';
    const coinsM       = coinsPctLine.match(/(\d+)\s*%/);

    // ── History date ──────────────────────────────────────────────────
    const noHistory    = histLines.some(l => /No history on file/i.test(l));
    const histDateLine = histLines.find(l =>
        /\d{4}-\d{2}-\d{2}/.test(l) || /\d{2}\/\d{2}\/\d{4}/.test(l)
    ) || '';
    const histDateM    = histDateLine.match(/(\d{4}-\d{2}-\d{2}|\d{2}\/\d{2}\/\d{4})/);

    // ── Quadrant & alternate benefit ──────────────────────────────────
    const quadrantLine = lines.find(l => /Quadrant\s*[-–]/i.test(l)) || '';
    const quadrantM    = quadrantLine.match(/Quadrant\s*[-–]\s*([A-Z]{2})/i);
    const altBenefit   = /Alternate benefit may apply/i.test(fullText);

    return {
        procedure_code:         code,
        description:            description,
        covered:                !notCovered,
        benefit_status:         notCovered ? 'Not a covered service' : 'Covered',
        maximum_remaining:      indRemaining,
        maximum_total:          maxTotal,
        frequency_used:         freqUsedM ? `${freqUsedM[1]} of ${freqUsedM[2]}` : 'N/A',
        frequency_limit:        clean(freqLimitLine) || 'N/A',
        coinsurance_member_pct: coinsM    ? `${coinsM[1]}%`             : 'N/A',
        history_date:           noHistory ? 'No history on file'        : (histDateM?.[1] || 'N/A'),
        quadrant:               quadrantM ? quadrantM[1]                : 'N/A',
        alternate_benefit:      altBenefit,
    };
}

// ══════════════════════════════════════════════════════════════════════════
// EXPAND + SCRAPE ALL ROWS — sequential, one row at a time
// ══════════════════════════════════════════════════════════════════════════

async function expandAndScrapeAllRows() {

    setStatus('Waiting for result rows to render…');

    let rows = [];

    const deadline = Date.now() + 15000;

    while (Date.now() < deadline) {

        rows = findResultRows();

        if (rows.length > 0) break;

        console.log('Cigna: No rows yet, waiting…');

        await sleep(1000);
    }

    if (!rows.length) {

        console.warn('Cigna: No result rows found after Submit');

        return [];
    }

    console.log(`Cigna: Processing ${rows.length} rows`);

    const results = [];

    for (let i = 0; i < rows.length; i++) {

        const row = rows[i];

        const codePeek =
            (row.innerText || '').match(/\bD\d{4}\b/)?.[0] ||
            `row${i + 1}`;

        setStatus(
            `Expanding ${codePeek} (${i + 1}/${rows.length})`
        );

        let expanded = false;

        // ─────────────────────────────────────────────
        // STRATEGY 1 — Angular Material
        // ─────────────────────────────────────────────

        const matHeader =
            row.querySelector('mat-expansion-panel-header') ||
            row.closest('mat-expansion-panel')
                ?.querySelector('mat-expansion-panel-header');

        if (matHeader) {

            const isOpen =
                matHeader.getAttribute('aria-expanded') === 'true';

            if (!isOpen) {

                console.log(
                    `Cigna: Clicking mat header for ${codePeek}`
                );

                matHeader.click();

                expanded = true;
            }
        }

        // ─────────────────────────────────────────────
        // STRATEGY 2 — aria-expanded
        // ─────────────────────────────────────────────

        if (!expanded) {

            const expanders = Array.from(
                row.querySelectorAll('[aria-expanded]')
            );

            if (expanders.length) {

                expanders.sort((a, b) => {

                    const ar =
                        b.getBoundingClientRect().right -
                        a.getBoundingClientRect().right;

                    if (Math.abs(ar) > 20) return ar;

                    return (
                        a.getBoundingClientRect().top -
                        b.getBoundingClientRect().top
                    );
                });

                const target = expanders[0];

                const isOpen =
                    target.getAttribute('aria-expanded') === 'true';

                if (!isOpen) {

                    console.log(
                        `Cigna: Clicking aria-expanded node`
                    );

                    target.click();

                    expanded = true;
                }
            }
        }

        // ─────────────────────────────────────────────
        // STRATEGY 3 — rightmost button/icon
        // ─────────────────────────────────────────────

        if (!expanded) {

            const clickables = Array.from(
                row.querySelectorAll(
                    'button, mat-icon, svg, [role="button"]'
                )
            ).filter(el => el.offsetParent !== null);

            clickables.sort((a, b) =>
                b.getBoundingClientRect().right -
                a.getBoundingClientRect().right
            );

            const target = clickables[0];

            if (target) {

                console.log(
                    `Cigna: Fallback chevron click`
                );

                target.click();

                expanded = true;
            }
        }

        // ─────────────────────────────────────────────
        // wait for expansion content
        // ─────────────────────────────────────────────

        await sleep(2000);

        await waitFor(() => {

            const txt = row.innerText || '';

            return (
                txt.includes('Maximum') ||
                txt.includes('Frequency') ||
                txt.includes('Coinsurance') ||
                txt.includes('History')
            );

        }, 7000);

        // ─────────────────────────────────────────────
        // scrape
        // ─────────────────────────────────────────────

        const data = scrapeOneRow(row);

        if (data) {

            results.push(data);

            console.log(
                `Cigna: ✓ scraped ${data.procedure_code}`,
                data
            );

        } else {

            console.warn(
                `Cigna: ✗ failed ${codePeek}`
            );
        }

        await sleep(300);
    }

    console.log(
        `Cigna: Done — ${results.length} rows`
    );

    return results;
}

// ══════════════════════════════════════════════════════════════════════════
// PROCEDURE CODE CRAWL
// ══════════════════════════════════════════════════════════════════════════

async function crawlProcedureCodes(baseData) {
    const ageLimits      = readAgeLimitsFromPage();
    const patientDOB     = baseData.patient.dob !== 'N/A' ? baseData.patient.dob : null;
    const allowedAgeCodes = filterCodesByAge(ageLimits, patientDOB);
    const excludedCodes  = AGE_GATED_LIST.filter(c => !allowedAgeCodes.includes(c));

    baseData.procedures.age_gate = {
        patient_dob:       patientDOB || 'not found',
        portal_age_limits: ageLimits,
        allowed_age_codes: allowedAgeCodes,
        excluded_codes:    excludedCodes,
    };

    const allCodes = [...STATIC_CODES, ...allowedAgeCodes, ...SPECIAL_CODES];
    const batches  = [];
    for (let i = 0; i < allCodes.length; i += 10) batches.push(allCodes.slice(i, i + 10));
    console.log(`Cigna: ${allCodes.length} codes → ${batches.length} batch(es):`, batches);

    await ensureAccordionOpen("Procedure Code Search");
    await sleep(800);

    const allResults = [];

    for (let b = 0; b < batches.length; b++) {
        setStatus(`Batch ${b + 1}/${batches.length} — clearing old codes…`);
        await clearExistingCodes();
        await sleep(800);

        const ok = await enterBatch(batches[b]);
        if (!ok) continue;

        setStatus(`Batch ${b + 1} submitted — locating result rows…`);
        const batchResults = await expandAndScrapeAllRows();

        batchResults.forEach(r => {
            if (!allResults.find(x => x.procedure_code === r.procedure_code)) allResults.push(r);
        });
    }

    baseData.procedures.codes_searched = allResults.map(r => r.procedure_code);
    baseData.procedures.count          = allResults.length;
    baseData.procedures.results        = allResults;
}

// ══════════════════════════════════════════════════════════════════════════
// MAIN ENTRY
// ══════════════════════════════════════════════════════════════════════════

async function runCignaCrawl() {
    if (!chrome.runtime?.id) return null;

    const chevrons = document.querySelectorAll('.collapsible__header[aria-expanded="false"]');
    if (chevrons.length > 0) {
        chevrons.forEach(c => c.click());
        await sleep(2500);
    }

    setStatus('Scraping page data…');
    const fullData = scrapeCignaFull();
    if (!fullData) return null;
    console.log('Cigna: Page data scraped ✓');

    await crawlProcedureCodes(fullData);
    return fullData;
}

// ══════════════════════════════════════════════════════════════════════════
// PASSIVE BACKGROUND SYNC
// ══════════════════════════════════════════════════════════════════════════

function runCignaLoop() {
    if (!chrome.runtime?.id) return;
    const url = window.location.href;
    if (!url.includes('/den/coverage') && !url.includes('dental') && !url.includes('coverage')) return;
    const data = scrapeCignaFull();
    if (!data) return;
    chrome.storage.local.get("audit_context", res => {
        const ctx = res.audit_context || {};
        ctx.cigna_data = data;
        chrome.storage.local.set({ audit_context: ctx });
    });
}
setTimeout(runCignaLoop, 4000);

// ══════════════════════════════════════════════════════════════════════════
// AUTO-DOWNLOAD + MESSAGE LISTENER
// ══════════════════════════════════════════════════════════════════════════

function autoDownloadJSON(data) {
    try {
        const json  = JSON.stringify(data, null, 2);
        const blob  = new Blob([json], { type: 'application/json' });
        const url   = URL.createObjectURL(blob);
        const name  = data.patient?.name || 'patient';
        const date  = new Date().toISOString().slice(0, 10);
        const fname = `cigna_${name.replace(/\s+/g, '_')}_${date}.json`;
        const a     = document.createElement('a');
        a.href      = url;
        a.download  = fname;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1500);
        console.log('Cigna: Auto-downloaded →', fname);
    } catch (e) {
        console.error('Cigna: Auto-download failed', e);
    }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.command === "START_CRAWL") {
        console.log("Cigna: START_CRAWL received");
        lockPage();

        runCignaCrawl().then(fullData => {
            unlockPage();
            if (!fullData) {
                sendResponse({ status: "[!] No data — navigate to the Dental Coverage page first." });
                return;
            }

            autoDownloadJSON(fullData);

            chrome.storage.local.get("audit_context", res => {
                const ctx = res.audit_context || {};
                ctx.cigna_data = fullData;
                chrome.storage.local.set({ audit_context: ctx }, () => {
                    const excl = fullData.procedures.age_gate.excluded_codes || [];
                    sendResponse({
                        status: `[+] Done — ${fullData.procedures.count} codes scraped. ` +
                                `JSON downloaded automatically. ` +
                                `DOB: ${fullData.procedures.age_gate.patient_dob}. ` +
                                `Excluded: ${excl.length ? excl.join(', ') : 'none'}.`
                    });
                });
            });
        }).catch(err => {
            unlockPage();
            console.error("Cigna crawl error:", err);
            sendResponse({ status: "[!] Crawl error: " + err.message });
        });

        return true;
    }
});