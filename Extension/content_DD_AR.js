// content_delta_dental_ar.js - Delta Dental AR (Smile/Provider Portal) Scraper

const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// CDT codes — same set as content_delta_dental.js, split into batches of 10
// Portal only allows 5 codes per search, so each batch is further split below
const BATCH_1 = ["D0120", "D0180", "D0140", "D0150", "D0274", "D0210", "D0330", "D0220", "D0364", "D0431"];
const BATCH_2 = ["D1110", "D1120", "D1206", "D1351", "D1510", "D2391", "D2740", "D2950", "D2962", "D6750"];
const BATCH_3 = ["D5110", "D9110", "D9222", "D9230", "D9243", "D9310", "D9944", "D4341", "D4355", "D4346"];
const BATCH_4 = ["D4910", "D4381", "D4260", "D4249", "D3310", "D3330", "D7140", "D7210", "D7240", "D7953"];
const BATCH_5 = ["D6010", "D6056"];

const MAX_PER_SEARCH = 5; // portal hard limit

console.log("Delta Dental AR scraper initialized");

// ══════════════════════════════════════════════════════════════════════════
// STATE DETECTION — this script is shared across NJ/MA/WA/AR (and any other
// state on the same Smile/Provider Portal platform). Every hostname follows
// the same pattern: deltadental<state>.com (e.g. deltadentalma.com,
// deltadentalnj.com). Extract the 2-letter code from the CURRENT page's own
// hostname rather than hardcoding one state, so the same script produces the
// correct filename/source label on whichever site it's actually running on.
// ══════════════════════════════════════════════════════════════════════════

function getStateCode() {
    const m = window.location.hostname.match(/deltadental([a-z]{2})\.com/i);
    if (m) return m[1].toUpperCase();
    console.warn(`[DeltaDentalState] Could not detect state code from hostname "${window.location.hostname}" — falling back to "XX".`);
    return "XX";
}

const STATE_CODE = getStateCode();
console.log(`Delta Dental scraper running on state: ${STATE_CODE}`);

// ══════════════════════════════════════════════════════════════════════════
// SECTION 1: PATIENT INFO
// ══════════════════════════════════════════════════════════════════════════

function scrapePatientInfo() {
    const info = {};

    // Page title: "Benefits for [Name]"
    document.querySelectorAll('h1, h2, h3').forEach(el => {
        const m = clean(el.innerText).match(/Benefits for (.+)/i);
        if (m && !info.patient_name) info.patient_name = m[1].trim();
    });

    // ── Left panel: div[data-js="providerPatientSubscriptionDetails"] ──
    // Each row: .cpbResultsRow → .cpbDetailLabel1 (label) + .cpbDetailResult1 (value)
    const leftPanel = document.querySelector('[data-js="providerPatientSubscriptionDetails"]');
    if (leftPanel) {
        leftPanel.querySelectorAll('.cpbResultsRow').forEach(row => {
            const label = clean(row.querySelector('.cpbDetailLabel1')?.innerText || '').replace(/:$/, '').toLowerCase();
            const valueEl = row.querySelector('.cpbDetailResult1');
            if (!label || !valueEl) return;
            const value = clean(valueEl.innerText);

            if (label.includes('request date'))                             info.request_date = value;
            else if (label.includes('subscriber name'))                     info.subscriber_name = value;
            else if (label.includes('subscriber #') || label === 'subscriber number') info.subscriber_number = value;
            else if (label.includes('date of birth')) {
                // Value contains date + optional "Age: 58" span
                const ageMatch = value.match(/Age:\s*(\d+)/);
                if (ageMatch) {
                    info.age = ageMatch[1];
                    info.date_of_birth = value.replace(/\s*Age:\s*\d+/, '').trim();
                } else {
                    info.date_of_birth = value;
                }
            }
            else if (label.includes('coverage is'))                        info.coverage_status = value;
            else if (label.includes('effective date'))                      info.effective_date = value;
            else if (label.includes('eligible through'))                    info.eligible_through = value;
            else if (label.includes('coverage level'))                      info.coverage_level = value;
            else if (label.includes('payment level'))                       info.payment_level = value;
            else if (label.includes('cob coverage type'))                   info.cob_coverage_type = value;
            else if (label.includes('plan type'))                           info.plan_type = value;
            else if (label.includes('group #') || label === 'group number') info.group_number = value;
            else if (label.includes('group name'))                          info.group_name = value;
            else if (label.includes('claim submit'))                        info.claim_submit_time_limit_days = value;
        });
    }

    // ── Right panel: div[data-js="patientBenefitDeductibles"] ──
    // Rows: .cpbResultsRowRight3 → .cpbDetailLabel + .cpbDetailResult / .cpbDetailResultRight
    const rightPanel = document.querySelector('[data-js="patientBenefitDeductibles"]');
    if (rightPanel) {
        rightPanel.querySelectorAll('.cpbResultsRowRight3').forEach(row => {
            const labelEl = row.querySelector('.cpbDetailLabel');
            const valueEl = row.querySelector('.cpbDetailResultRight, .cpbDetailResult');
            if (!labelEl || !valueEl) return;
            const label = clean(labelEl.innerText).replace(/:$/, '').toLowerCase();
            const value = clean(valueEl.innerText);

            if (label.includes('benefit period'))             info.benefit_period = value;
            else if (label.includes('annual maximum'))        info.individual_annual_maximum = value;
            else if (label.includes('deductible'))            info.individual_deductible = value;
            else if (label.includes('dependent eligibility')) info.dependent_eligibility = value;
            else if (label.includes('student eligibility'))   info.student_eligibility = value;
        });
    }

    return info;
}

// ══════════════════════════════════════════════════════════════════════════
// SECTION 2: ELIGIBLE BENEFITS
// ══════════════════════════════════════════════════════════════════════════

function scrapeEligibleBenefits() {
    const categories = [];

    document.querySelectorAll('.eligible-benefits-category').forEach(catEl => {
        const categoryName = clean(
            catEl.querySelector('.eligible-benefits-category-name')?.innerText ||
            catEl.querySelector('h3')?.innerText ||
            "Unknown"
        );

        const rows = [];
        catEl.querySelectorAll('.rowResults').forEach(rowEl => {
            const cells = rowEl.querySelectorAll('.cell');
            if (cells.length < 4) return;

            const benefit_class = clean(
                cells[0].querySelector('.benefitClassName')?.innerText ||
                cells[0].innerText
            );

            // % Plan Pays — first cell after benefit class
            const plan_pays = clean(cells[1]?.innerText) || "N/A";

            // Deductible
            const deductible = clean(cells[2]?.innerText) || "N/A";

            // Waiting Period
            const waiting_period = clean(cells[3]?.innerText) || "N/A";

            // Services and Usage — join multiple <span> lines with newlines
            let services_and_usage = "N/A";
            if (cells[4]) {
                const lines = [];
                cells[4].querySelectorAll('span[data-bind*="$data"], span').forEach(span => {
                    const t = clean(span.innerText);
                    if (t) lines.push(t);
                });
                if (lines.length > 0) {
                    services_and_usage = lines.join('\n');
                } else {
                    services_and_usage = clean(cells[4].innerText) || "N/A";
                }
            }

            if (benefit_class) {
                rows.push({ benefit_class, plan_pays, deductible, waiting_period, services_and_usage });
            }
        });

        if (rows.length > 0) {
            categories.push({ category: categoryName, rows });
        }
    });

    return categories;
}

// ══════════════════════════════════════════════════════════════════════════
// SECTION 3: PROCEDURE CODE LOOKUP
// ══════════════════════════════════════════════════════════════════════════

async function clearProcedureChips() {
    const closeButtons = document.querySelectorAll(
        '[data-js="procedure-lookup-control"] .chip .close, ' +
        '[data-js="procedure-lookup-control"] .chip i'
    );
    for (const btn of Array.from(closeButtons)) {
        btn.click();
        await sleep(150);
    }
    await sleep(200);
}

async function addProcedureChip(code) {
    const input = document.querySelector('[data-test-id="proceduresCodeInput"]');
    if (!input) return false;

    input.focus();
    input.value = code;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await sleep(150);

    // Press Enter to commit the chip (Knockout listens on keydown/keyup)
    for (const type of ['keydown', 'keypress', 'keyup']) {
        input.dispatchEvent(new KeyboardEvent(type, {
            key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
        }));
    }
    await sleep(250);
    return true;
}

function parseProcedurePane(paneEl) {
    const code = clean(paneEl.id || paneEl.querySelector('.procedureCode')?.innerText || "");
    if (!code) return null;

    // Error states — Knockout sets display:none on hidden divs
const isVisible = el => {
    if (!el) return false;
    const s = window.getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden';
};    if (isVisible(paneEl.querySelector('[data-test-id="ErrorNotCovered"]')))
        return { code, status: "Not covered under plan" };
    if (isVisible(paneEl.querySelector('[data-test-id="ErrorNotFound"]')))
        return { code, status: "No procedure code found" };
    if (isVisible(paneEl.querySelector('[data-test-id="ErrorInvalid"]')))
        return { code, status: "Invalid procedure code" };
    if (isVisible(paneEl.querySelector('[data-test-id="ProviderNotSupported"]')))
        return { code, status: "Not supported for out-of-state providers" };

    const bg = paneEl.querySelector('.procedureCodeBackground');
    if (!bg) return { code, status: "No data" };

    const cols = bg.querySelectorAll('.colHeader');
    if (cols.length < 4) return { code, status: "No data" };

    // ── Column 0: Benefit class + Description ──
    const col0Divs = Array.from(cols[0].querySelectorAll('div'));
    const benefit_class  = clean(col0Divs[0]?.innerText || "");
    const description    = clean(col0Divs[1]?.innerText || "");

    // Optional tooth type (only visible if set)
 const toothTypeEl = cols[0].querySelector('[data-bind*="ToothType"]');
const tooth_type = isVisible(toothTypeEl)
    ? clean(toothTypeEl.innerText).replace(/^Tooth Type:\s*/i, '')
    : null;
    // ── Column 1: Coverage details ──
    // innerText naturally excludes display:none elements
const col1Text = cols[1].innerText;

const coverage_type = clean(cols[1].querySelector('.font-weight-bold, b, strong')?.innerText || "");

// BUG-001: Target the Plan Pays element directly to avoid capturing
const planPaysEl = Array.from(cols[1].querySelectorAll('div, span')).find(el =>
    isVisible(el) && /^\s*Plan Pays\s+/i.test(el.innerText)
);
const planPaysMatch = planPaysEl
    ? clean(planPaysEl.innerText).match(/Plan Pays\s+(.+)/i)
    : col1Text.match(/Plan Pays\s+([^\n]+)/i);
const plan_pays = planPaysMatch ? clean(planPaysMatch[1]) : "N/A";

    // Deductible — visible div containing "Deductible"
    const deductible_el = Array.from(cols[1].querySelectorAll('div')).find(d =>
        /deductible/i.test(d.innerText) && d.style.display !== 'none'
    );
    const deductible = deductible_el ? clean(deductible_el.innerText) : "N/A";

    // Frequency + Remaining — last visible non-header line
    // Spans inside the frequency div
const freqDiv = Array.from(cols[1].querySelectorAll('div')).find(d =>
    isVisible(d) &&
    /\bper\b|time limits|remaining/i.test(d.innerText) &&
    !/plan pays|allowed amount|deductible/i.test(d.innerText)
);
const frequency = freqDiv ? clean(freqDiv.innerText) : "N/A";

// ── Column 2: Variations ──
const variationsSeen = new Set();
const variations = [];
Array.from(cols[2].querySelectorAll('div')).forEach(d => {
    if (!isVisible(d)) return;                          // BUG-008
    if (d.querySelector('div')) return;                 // skip non-leaf
    const t = clean(d.innerText);
    if (!t || /^Variations$/i.test(t)) return;
    if (variationsSeen.has(t)) return;                  // BUG-003 dedupe
    variationsSeen.add(t);
    variations.push(t);
});

    // ── Column 3: Treatment History ──
const histSeen = new Set();
const histLines = [];
Array.from(cols[3].querySelectorAll('div')).forEach(d => {
    if (!isVisible(d)) return;                          // BUG-008
    if (d.querySelector('div')) return;                 // skip non-leaf
    const t = clean(d.innerText);
    if (!t || /^Treatment History$/i.test(t)) return;
    if (histSeen.has(t)) return;                        // BUG-005 dedupe
    histSeen.add(t);
    histLines.push(t);
});
const treatment_history = histLines.length > 0 ? histLines.join('; ') : "N/A";

    const result = {
        code,
        benefit_class,
        description,
        coverage_type,
        plan_pays,
        deductible,
        frequency,
        variations: variations.length > 0 ? variations : ["N/A"],
        treatment_history,
    };
    if (tooth_type) result.tooth_type = tooth_type;
    return result;
}

async function searchProcedureBatch(codes) {
    await clearProcedureChips();

    for (const code of codes) {
        const ok = await addProcedureChip(code);
        if (!ok) {
            console.warn(`AR: could not add chip for ${code}`);
            return [];
        }
    }

    const submitBtn = document.querySelector(
        '[data-test-id="ProcedureLookupButton"], [data-js="submit"]'
    );
    if (!submitBtn) {
        console.warn("AR: submit button not found");
        return [];
    }
    submitBtn.click();

    // Wait for results (~500ms per code + 2s base)
    await sleep(2000 + codes.length * 500);

    const resultsContainer = document.querySelector('[data-js="procedure-lookup-results-display"]');
    if (!resultsContainer) return [];

    const results = [];
    resultsContainer.querySelectorAll('.tab-pane').forEach(pane => {
        const parsed = parseProcedurePane(pane);
        if (parsed) results.push(parsed);
    });
    return results;
}

async function scrapeAllProcedureCodes() {
    const allCodes = [...BATCH_1, ...BATCH_2, ...BATCH_3, ...BATCH_4, ...BATCH_5];

    // Split into sub-batches of MAX_PER_SEARCH
    const batches = [];
    for (let i = 0; i < allCodes.length; i += MAX_PER_SEARCH) {
        batches.push(allCodes.slice(i, i + MAX_PER_SEARCH));
    }

    const allResults = [];
    for (let i = 0; i < batches.length; i++) {
        console.log(`AR Procedure lookup ${i + 1}/${batches.length}: ${batches[i].join(', ')}`);
        const batchResults = await searchProcedureBatch(batches[i]);
        allResults.push(...batchResults);
        if (i < batches.length - 1) await sleep(1000);
    }

    console.log(`AR Procedure lookup complete: ${allResults.length} codes`);
    return allResults;
}

// ══════════════════════════════════════════════════════════════════════════
// DOWNLOAD
// ══════════════════════════════════════════════════════════════════════════

function triggerDownload(auditData) {
    const sanitize = s => (s || "").trim().replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "").toLowerCase();
    // Prefer the actual PATIENT's name (scraped from the page's own "Benefits
    // for <name>" heading) over the subscriber's name — they're often
    // different people (e.g. a dependent child's benefits looked up under a
    // parent's account), and the file should be named for whoever the
    // benefits actually belong to, not just whoever the account holder is.
    const patient = sanitize(
        auditData.patient_info?.patient_name ||
        auditData.patient_info?.subscriber_name ||
        auditData.patient_info?.subscriber_number ||
        "patient"
    ) || "patient";
    // Filename now reflects whichever state this script actually ran on
    // (STATE_CODE detected from the page's own hostname), instead of always
    // hardcoding "AR" regardless of the real site.
    const filename = `${patient}_Delta_Dental_${STATE_CODE}.json`;

    const blob = new Blob([JSON.stringify(auditData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(url);
    document.body.removeChild(a);
    console.log(`✓ Downloaded: ${filename}`);
}

// ══════════════════════════════════════════════════════════════════════════
// MAIN
// ══════════════════════════════════════════════════════════════════════════

async function runAudit() {
    console.log(`=== Delta Dental ${STATE_CODE} Scraper Starting ===`);

    const auditData = {
        // "source" now reflects the detected state too, not a hardcoded "AR"
        // label regardless of which of the 4 sites this actually ran on.
        source: `Delta Dental ${STATE_CODE}`,
        state_code: STATE_CODE,
        scraped_at: new Date().toISOString(),
    };

    console.log("Scraping patient info...");
    auditData.patient_info = scrapePatientInfo();

    console.log("Scraping procedure code lookup...");
    auditData.procedure_lookup = await scrapeAllProcedureCodes();

    console.log("Scraping eligible benefits...");
    auditData.eligible_benefits = scrapeEligibleBenefits();

    console.log(`=== Delta Dental ${STATE_CODE} Scraper Complete ===`);
    console.log("Audit data:", auditData);

    chrome.storage.local.get("audit_context", (result) => {
        let context = result.audit_context || {};
        // Storage key is now per-state too (delta_dental_ma_data,
        // delta_dental_nj_data, etc.) instead of always
        // "delta_dental_ar_data" regardless of which state actually ran —
        // avoids one state's data silently overwriting another's key if a
        // user has multiple patient records queued across states.
        context[`delta_dental_${STATE_CODE.toLowerCase()}_data`] = auditData;
        chrome.storage.local.set({ audit_context: context }, () => {
            console.log(`✓ Delta Dental ${STATE_CODE} data stored`);
            triggerDownload(auditData);
        });
    });

    return auditData;
}

// ══════════════════════════════════════════════════════════════════════════
// MESSAGE LISTENER
// ══════════════════════════════════════════════════════════════════════════

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.command === "START_CRAWL") {
        sendResponse({ status: "started" });
        runAudit().catch(err => console.error(`Delta Dental ${STATE_CODE} scraper error:`, err));
    }
    return true;
});