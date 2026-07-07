// const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');
// const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// async function waitForElement(selector, timeout = 8000) {
//     const deadline = Date.now() + timeout;
//     while (Date.now() < deadline) {
//         const el = document.querySelector(selector);
//         if (el) return el;
//         await sleep(400);
//     }
//     return null;
// }

// function findByText(text, root = document.body) {
//     const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
//     let node;
//     while ((node = walker.nextNode())) {
//         if (node.textContent.trim() === text) return node.parentElement;
//     }
//     return null;
// }

// // Like findByText but matches a regex against the whole trimmed text node —
// // needed for things like "as of MM/DD/YYYY" or "Enter 4-digit CDT code"
// // where the exact string can vary slightly.
// function findByRegex(regex, root = document.body) {
//     const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
//     let node;
//     while ((node = walker.nextNode())) {
//         if (regex.test(node.textContent.trim())) return node.parentElement;
//     }
//     return null;
// }

// // Guardian's CDT input doesn't pick up state changes from a plain
// // native-setter + input/change dispatch (confirmed via console testing —
// // the DOM value updates but the app's internal "search criteria" state
// // doesn't). It needs the full keydown -> keypress -> insertText -> keyup
// // sequence per character, i.e. something close to real typing.
// function simulateTyping(input, text) {
//     input.focus();
//     input.value = "";
//     input.dispatchEvent(new Event("input", { bubbles: true }));

//     for (const ch of text) {
//         const code = "Digit" + ch;
//         const keyCode = ch.charCodeAt(0);
//         input.dispatchEvent(new KeyboardEvent("keydown", { key: ch, code, keyCode, which: keyCode, bubbles: true }));
//         input.dispatchEvent(new KeyboardEvent("keypress", { key: ch, code, keyCode, which: keyCode, bubbles: true }));
//         document.execCommand("insertText", false, ch);
//         input.dispatchEvent(new KeyboardEvent("keyup", { key: ch, code, keyCode, which: keyCode, bubbles: true }));
//     }
// }

// // 42 codes, searched ONE AT A TIME — Guardian's "Search coverage by CDT
// // code" box only accepts a single 4-digit code per search (no comma-
// // batching like MetLife), so there's no BATCH_X chunking here.
// const CDT_CODES = [
//     ["Periodic Exam", "0120"],
//     ["Perio Consult", "0180"],
//     ["Limited Exam", "0140"],
//     ["Comprehensive Exam", "0150"],
//     ["Bitewings", "0274"],
//     ["Full Mouth X-Ray", "0210"],
//     ["Panoramic X-Ray", "0330"],
//     ["PA X-Ray", "0220"],
//     ["Cone Beam", "0364"],
//     ["Oral Cancer Screening", "0431"],
//     ["Prophylaxis Adult", "1110"],
//     ["Prophylaxis Child", "1120"],
//     ["Fluoride", "1206"],
//     ["Sealants", "1351"],
//     ["Space Maintainer", "1510"],
//     ["Composite Filling", "2391"],
//     ["Porcelain Crown", "2740"],
//     ["Build-Up", "2950"],
//     ["Veneers", "2962"],
//     ["Bridge", "6750"],
//     ["Dentures", "5110"],
//     ["Palliative Treatment", "9110"],
//     ["General Anesthesia", "9222"],
//     ["Nitrous Oxide", "9230"],
//     ["General Sedation / IV Sedation", "9243"],
//     ["Consultation", "9310"],
//     ["Occlusal Guard", "9944"],
//     ["Scaling & Root Planing", "4341"],
//     ["Full Mouth Debridement", "4355"],
//     ["Gingivitis Treatment", "4346"],
//     ["Periodontal Maintenance", "4910"],
//     ["Arestin", "4381"],
//     ["Osseous Surgery", "4260"],
//     ["Crown Lengthening", "4249"],
//     ["Root Canal Anterior", "3310"],
//     ["Root Canal Molar", "3330"],
//     ["Simple Extraction", "7140"],
//     ["Surgical Extraction", "7210"],
//     ["Impacted Extraction", "7240"],
//     ["Bone Graft with Extraction", "7953"],
//     ["Implant", "6010"],
//     ["Implant Abutment", "6056"]
// ];


// // ══════════════════════════════════════════════════════════════════════════
// // PATIENT HEADER / PLAN INFO
// // ══════════════════════════════════════════════════════════════════════════

// function scrapePatientHeader() {
//     const heading = Array.from(document.querySelectorAll("h1,h2,h3"))
//         .find(h => /dental eligibility/i.test(h.textContent || ""));
//     const name = heading ? clean(heading.textContent).replace(/dental eligibility/i, "").trim() : "N/A";

//     const asOfMatch = (document.body.innerText || "").match(/as of\s*([\d\/]+)/i);
//     return {
//         name,
//         as_of_date: asOfMatch ? asOfMatch[1] : "N/A"
//     };
// }

// function getLabelValue(labelText) {
//     const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
//     let node;
//     while ((node = walker.nextNode())) {
//         if (node.textContent.trim() !== labelText) continue;
//         const labelEl = node.parentElement;
//         const sib = labelEl.nextElementSibling;
//         if (sib?.innerText?.trim()) return clean(sib.innerText);
//         const parentSib = labelEl.parentElement?.nextElementSibling;
//         if (parentSib?.innerText?.trim()) return clean(parentSib.innerText);
//         return "N/A";
//     }
//     return "N/A";
// }

// function scrapePlanInfo() {
//     return {
//         benefit_period: getLabelValue("Benefit period"),
//         date_of_birth: getLabelValue("Date of birth"),
//         dependent_age_limit: getLabelValue("Dependent age limit"),
//         student_age_limit: getLabelValue("Student age limit"),
//         group_name: getLabelValue("Group name"),
//         group_number: getLabelValue("Group number"),
//         orthodontics_age_limit: getLabelValue("Orthodontics age limit")
//     };
// }

// function scrapePlanBullets() {
//     const items = Array.from(document.querySelectorAll("li"));
//     const planNameEl = items.find(li => /the patient'?s plan is/i.test(li.textContent || ""));
//     const oonEl = items.find(li => /out of network benefits/i.test(li.textContent || ""));
//     return {
//         plan_name: planNameEl
//             ? clean(planNameEl.textContent).replace(/^the patient'?s plan is\s*/i, "").replace(/\.$/, "")
//             : "N/A",
//         out_of_network_note: oonEl ? clean(oonEl.textContent) : "N/A"
//     };
// }


// // ══════════════════════════════════════════════════════════════════════════
// // GENERIC TABLE HELPERS (used for Effective Dates / Deductibles / Maximums /
// // CDT result table — all four render as real <table> elements on Guardian)
// // ══════════════════════════════════════════════════════════════════════════

// function findTableByHeaderText(requiredHeaders, root = document) {
//     const tables = Array.from(root.querySelectorAll("table"));
//     for (const table of tables) {
//         const headerText = Array.from(table.querySelectorAll("th")).map(th => clean(th.innerText).toLowerCase());
//         const allFound = requiredHeaders.every(req => headerText.some(h => h.includes(req.toLowerCase())));
//         if (allFound) return table;
//     }
//     return null;
// }

// // The "Plan options" table (full static list of every service) uses the
// // EXACT same column headers (Service / Network / Category / Coinsurance /
// // Message / Last Visit) as the small dynamic result that appears under
// // "Search coverage by CDT code". A document-wide header search can't tell
// // them apart, so we scope to the CDT section specifically: walk up from
// // the input until we find the smallest ancestor whose text includes
// // "search coverage by cdt code" but does NOT yet also include "plan
// // options" (which would mean we climbed too far and now also wrap the
// // unrelated static table).
// function getCdtSectionContainer() {
//     const input = findCdtInput();
//     if (!input) return null;
//     let el = input;
//     let lastGood = null;
//     for (let i = 0; i < 15 && el; i++) {
//         const text = (el.textContent || "").toLowerCase();
//         const hasCdtSection = text.includes("search coverage by cdt code");
//         const hasPlanOptions = text.includes("plan options");
//         if (hasCdtSection && !hasPlanOptions) {
//             lastGood = el;
//         } else if (hasCdtSection && hasPlanOptions) {
//             break; // this ancestor now also wraps Plan options — too broad
//         }
//         el = el.parentElement;
//     }
//     return lastGood || input.closest("section,[class*='accordion'],[class*='panel']") || input.parentElement;
// }

// function tableToObjects(table) {
//     if (!table) return [];
//     const headers = Array.from(table.querySelectorAll("th")).map(th => clean(th.innerText).toLowerCase());
//     let rows = Array.from(table.querySelectorAll("tbody tr"));
//     if (!rows.length) rows = Array.from(table.querySelectorAll("tr")).filter(tr => tr.querySelectorAll("td").length);
//     return rows.map(row => {
//         const cells = Array.from(row.querySelectorAll("td")).map(td => clean(td.innerText));
//         const obj = {};
//         headers.forEach((h, i) => { if (h) obj[h] = cells[i] ?? ""; });
//         return obj;
//     });
// }

// function scrapeEffectiveDates() {
//     const table = findTableByHeaderText(["name", "prev"]) || findTableByHeaderText(["name", "relation"]);
//     return tableToObjects(table);
// }

// function scrapeDeductibles() {
//     const table = findTableByHeaderText(["coverage", "deductible"]);
//     return tableToObjects(table);
// }

// function scrapePlanMaximums() {
//     const table = findTableByHeaderText(["coverage", "yearly plan limit"]) ||
//         findTableByHeaderText(["coverage", "network", "yearly"]);
//     return tableToObjects(table);
// }


// // ══════════════════════════════════════════════════════════════════════════
// // EXPAND ACCORDIONS (Deductibles / Plan Allowance / MaxRollover / CDT search
// // / Plan options are collapsed by default — there's an "Expand all" link)
// // ══════════════════════════════════════════════════════════════════════════

// async function expandAllSections() {
//     const expandBtn = document.querySelector("button.expand-collapse-all-link") ||
//         Array.from(document.querySelectorAll("a,button,span"))
//             .find(el => clean(el.textContent).toLowerCase() === "expand all");
//     if (expandBtn) {
//         expandBtn.click();
//         await sleep(800);
//     }
// }

// async function ensureCdtSectionExpanded() {
//     let input = findCdtInput();
//     if (input) return input;

//     await expandAllSections();
//     input = findCdtInput();
//     if (input) return input;

//     const header = findByRegex(/search coverage by cdt code/i);
//     const toggle = header && (header.closest("button,a,[role='button'],h1,h2,h3,h4,div") || header);
//     if (toggle) {
//         toggle.click();
//         await sleep(500);
//     }
//     return findCdtInput();
// }


// // ══════════════════════════════════════════════════════════════════════════
// // CDT CODE INPUT / SEARCH BUTTON / RESULTS
// // ══════════════════════════════════════════════════════════════════════════

// function findCdtInput() {
//     let input = document.getElementById("cdtInput");
//     if (input) return input;

//     input = document.querySelector("input[placeholder*='CDT' i]") ||
//         document.querySelector("input[aria-label*='CDT' i]") ||
//         document.querySelector("input[name*='cdt' i]") ||
//         document.querySelector("input[id*='cdt' i]");
//     if (input) return input;

//     const labelEl = findByRegex(/enter\s*4-?digit\s*cdt\s*code/i);
//     if (labelEl) {
//         const container = labelEl.closest("div,section,fieldset") || labelEl.parentElement;
//         input = container && container.querySelector("input");
//         if (input) return input;
//     }
//     return findInputNearSearchButton();
// }

// // The little "X" icon inside the CDT input that clears its value — found
// // via its distinctive SVG path data rather than a generated class name.
// function findClearButton() {
//     const xPath = document.querySelector('path[d*="242.72 256l100.07-100.07"]');
//     if (!xPath) return null;
//     return xPath.closest("button") || xPath.closest("[role='button']") || xPath.closest("svg") || xPath;
// }

// function findInputNearSearchButton() {
//     const btn = Array.from(document.querySelectorAll("button")).find(b => clean(b.textContent) === "Search");
//     if (!btn) return null;
//     let parent = btn.parentElement;
//     for (let i = 0; i < 5; i++) {
//         if (!parent) break;
//         const input = parent.querySelector("input[type='text'],input:not([type])");
//         if (input) return input;
//         parent = parent.parentElement;
//     }
//     return null;
// }

// function findSearchButton() {
//     return document.getElementById("cdt-search-button") ||
//         Array.from(document.querySelectorAll("button")).find(b => clean(b.textContent) === "Search" && !b.disabled) ||
//         null;
// }

// function isLoadingModalVisible() {
//     const el = findByRegex(/please wait while your request is being processed/i);
//     if (!el) return false;
//     const r = el.getBoundingClientRect();
//     return r.width > 0 && r.height > 0;
// }

// function getResultsRawText() {
//     const container = getCdtSectionContainer() || document;
//     const table = findTableByHeaderText(["service", "coinsurance"], container);
//     return table ? clean(table.innerText) : "";
// }

// function scrapeCdtResultTable(code) {
//     const container = getCdtSectionContainer() || document;
//     const table = findTableByHeaderText(["service", "coinsurance"], container);
//     const rows = tableToObjects(table);
//     return rows.map(r => ({
//         cdt_code: "D" + code,
//         service: r["service"] || "N/A",
//         network: r["network"] || "N/A",
//         category: r["category"] || "N/A",
//         coinsurance: r["coinsurance"] || "N/A",
//         message: r["message"] || "N/A",
//         last_visit: r["last visit"] || "N/A"
//     }));
// }


// // ══════════════════════════════════════════════════════════════════════════
// // LOW-LEVEL: run ONE code, click Search, wait, scrape
// // ══════════════════════════════════════════════════════════════════════════

// async function runOneCode(code) {
//     const input = findCdtInput();
//     console.log(`[Debug] D${code} — input found:`, !!input);
//     if (!input) return [];

//     simulateTyping(input, code);
//     await sleep(1000);
//     console.log(`[Debug] D${code} — value after simulateTyping:`, JSON.stringify(input.value));

//     const searchBtn = findSearchButton();
//     console.log(`[Debug] D${code} — searchBtn found:`, !!searchBtn, 'disabled:', searchBtn && searchBtn.disabled);
//     if (!searchBtn) return [];

//     const prevRaw = getResultsRawText();
//     console.log(`[Debug] D${code} — value right before click:`, JSON.stringify(input.value), '| prevRaw length:', prevRaw.length);
//     document.getElementById("cdt-search-button").click();
//     console.log(`[Debug] D${code} — clicked search`);

//     const deadline = Date.now() + 12000;
//     let timedOut = true;
//     while (Date.now() < deadline) {
//         const loading = isLoadingModalVisible();
//         const currentRaw = getResultsRawText();
//         if (!loading && currentRaw && currentRaw !== prevRaw) { timedOut = false; break; }
//         await sleep(300);
//     }
//     console.log(`[Debug] D${code} — wait loop result:`, timedOut ? 'TIMED OUT' : 'results changed');
//     await sleep(500);

//     const errorEl = findByRegex(/please enter any search criteria/i);
//     console.log(`[Debug] D${code} — error banner visible:`, !!errorEl && errorEl.getBoundingClientRect().width > 0);

//     const scraped = scrapeCdtResultTable(code);
//     console.log(`[Debug] D${code} — scraped rows:`, scraped.length);
//     return scraped;
// }


// // ══════════════════════════════════════════════════════════════════════════
// // BUILD PLAN OVERVIEW PAYLOAD
// // ══════════════════════════════════════════════════════════════════════════

// function buildPlanOverviewPayload() {
//     return {
//         source: "Guardian Portal - Plan Overview",
//         timestamp: new Date().toISOString(),
//         patient_header: scrapePatientHeader(),
//         plan_info: scrapePlanInfo(),
//         plan_bullets: scrapePlanBullets(),
//         effective_dates: scrapeEffectiveDates(),
//         deductibles: scrapeDeductibles(),
//         plan_maximums: scrapePlanMaximums()
//     };
// }


// // ══════════════════════════════════════════════════════════════════════════
// // CRAWL — PLAN OVERVIEW
// // ══════════════════════════════════════════════════════════════════════════

// async function crawlPlanOverview() {
//     await expandAllSections();
//     const data = buildPlanOverviewPayload();

//     return new Promise((resolve) => {
//         chrome.storage.local.get("audit_context", (res) => {
//             const ctx = res.audit_context || {};
//             ctx.guardian_data = data;
//             chrome.storage.local.set({ audit_context: ctx }, () => {
//                 const got = data.effective_dates.length > 0;
//                 resolve({ status: got ? `[+] Plan Overview saved (${data.effective_dates.length} coverage row(s)).` : `[!] Saved but effective dates table not found — stay on the eligibility page and retry.` });
//             });
//         });
//     });
// }


// // ══════════════════════════════════════════════════════════════════════════
// // CRAWL — BENEFIT & COVERAGE (search coverage by CDT code, one code at a time)
// // ══════════════════════════════════════════════════════════════════════════

// async function crawlBenefitCoverage(extraCodes = "") {
//     const input = await ensureCdtSectionExpanded();
//     if (!input) {
//         return { status: "[!] CDT code input not found — open 'Search coverage by CDT code' manually and retry." };
//     }

//     const extraList = extraCodes
//         ? extraCodes.split(",").map(c => c.trim().toUpperCase().replace(/^D/, "")).filter(Boolean)
//         : [];

//     const allCodes = [...new Set([...CDT_CODES.map(c => c[1]), ...extraList])];

//     const allResults = [];
//     for (let i = 0; i < allCodes.length; i++) {
//         const code = allCodes[i];
//         console.log(`[Audit] CDT ${i + 1}/${allCodes.length}: D${code}`);
//         try {
//             const rows = await runOneCode(code);
//             if (rows.length) {
//                 allResults.push(...rows);
//             } else {
//                 allResults.push({ cdt_code: "D" + code, error: "No table rows found" });
//             }
//         } catch (e) {
//             console.error(`[Audit] D${code} failed:`, e);
//             allResults.push({ cdt_code: "D" + code, error: String(e.message || e) });
//         }
//         await sleep(500);
//     }

//     return new Promise((resolve) => {
//         chrome.storage.local.get("audit_context", (res) => {
//             const ctx = res.audit_context || {};
//             ctx.benefit_coverage = {
//                 source: "Guardian Portal - Search Coverage by CDT Code",
//                 timestamp: new Date().toISOString(),
//                 codes_searched: allCodes.map(c => "D" + c),
//                 extra_codes: extraList.map(c => "D" + c),
//                 result_count: allResults.length,
//                 results: allResults
//             };
//             chrome.storage.local.set({ audit_context: ctx }, () => {
//                 resolve({ status: `[+] Scraped ${allResults.length} row(s) across ${allCodes.length} code(s).` });
//             });
//         });
//     });
// }


// // ══════════════════════════════════════════════════════════════════════════
// // DOWNLOAD HELPER
// // ══════════════════════════════════════════════════════════════════════════

// function downloadAuditJSON() {
//     chrome.storage.local.get("audit_context", (res) => {
//         const data = res.audit_context || {};
//         const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
//         const url = URL.createObjectURL(blob);
//         const a = document.createElement("a");
//         a.href = url;
//         const patient = data?.guardian_data?.patient_header?.name
//             ?.replace(/[^a-z0-9]/gi, "_")?.toLowerCase() || "patient";
//         a.download = `${patient}_guardian_audit.json`;
//         document.body.appendChild(a);
//         a.click();
//         a.remove();
//         URL.revokeObjectURL(url);
//     });
// }


// // ══════════════════════════════════════════════════════════════════════════
// // MESSAGE LISTENER
// // ══════════════════════════════════════════════════════════════════════════

// chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

//     if (request.command === "START_CRAWL") {
//         (async () => {
//             await crawlPlanOverview();
//             const res = await crawlBenefitCoverage("");
//             downloadAuditJSON();
//             sendResponse({ status: res.status + " JSON downloaded." });
//         })();
//         return true;
//     }

//     if (request.command === "CRAWL_PLAN_OVERVIEW") {
//         crawlPlanOverview().then(sendResponse).catch(() => sendResponse({ status: "[!] Error." }));
//         return true;
//     }

//     if (request.command === "CRAWL_BENEFIT_COVERAGE") {
//         crawlBenefitCoverage(request.extraCodes || "").then(sendResponse).catch(() => sendResponse({ status: "[!] Error." }));
//         return true;
//     }
// });
const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function waitForElement(selector, timeout = 8000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
        const el = document.querySelector(selector);
        if (el) return el;
        await sleep(400);
    }
    return null;
}

function findByText(text, root = document.body) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        if (node.textContent.trim() === text) return node.parentElement;
    }
    return null;
}

function findByRegex(regex, root = document.body) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        if (regex.test(node.textContent.trim())) return node.parentElement;
    }
    return null;
}

// Real backspace key events — confirmed via console testing to be the
// only thing that actually clears Guardian's internal tracked value.
// Clicking the site's own "X" clear button via .click() does NOT work
// (tested directly: value stayed unchanged), and a plain value="" reset
// doesn't register with the framework either — only genuine keyboard
// events do, matching what typing itself requires.
function simulateBackspaceClear(input, count) {
    for (let i = 0; i < count; i++) {
        input.dispatchEvent(new KeyboardEvent("keydown", { key: "Backspace", code: "Backspace", keyCode: 8, which: 8, bubbles: true }));
        document.execCommand("delete", false);
        input.dispatchEvent(new KeyboardEvent("keyup", { key: "Backspace", code: "Backspace", keyCode: 8, which: 8, bubbles: true }));
    }
}

// ROOT CAUSE (confirmed via testing): Guardian's controlled input doesn't
// reliably clear via input.value="", select()+delete, or clicking its own
// "X" button programmatically — only real backspace key events register
// with the framework's internally-tracked state. Same story as typing
// itself, which needs keydown -> keypress -> insertText -> keyup per
// character rather than a plain value assignment.
async function simulateTyping(input, text) {
    input.focus();

    if (input.value) {
        simulateBackspaceClear(input, input.value.length);
        await sleep(200);
    }

    for (const ch of text) {
        const code = "Digit" + ch;
        const keyCode = ch.charCodeAt(0);
        input.dispatchEvent(new KeyboardEvent("keydown", { key: ch, code, keyCode, which: keyCode, bubbles: true }));
        input.dispatchEvent(new KeyboardEvent("keypress", { key: ch, code, keyCode, which: keyCode, bubbles: true }));
        document.execCommand("insertText", false, ch);
        input.dispatchEvent(new KeyboardEvent("keyup", { key: ch, code, keyCode, which: keyCode, bubbles: true }));
    }

    console.log(`[Audit] cleared+typed "${text}" — input.value now:`, JSON.stringify(input.value));
}

const CDT_CODES = [
    ["Periodic Exam", "0120"],
    ["Perio Consult", "0180"],
    ["Limited Exam", "0140"],
    ["Comprehensive Exam", "0150"],
    ["Bitewings", "0274"],
    ["Full Mouth X-Ray", "0210"],
    ["Panoramic X-Ray", "0330"],
    ["PA X-Ray", "0220"],
    ["Cone Beam", "0364"],
    ["Oral Cancer Screening", "0431"],
    ["Prophylaxis Adult", "1110"],
    ["Prophylaxis Child", "1120"],
    ["Fluoride", "1206"],
    ["Sealants", "1351"],
    ["Space Maintainer", "1510"],
    ["Composite Filling", "2391"],
    ["Porcelain Crown", "2740"],
    ["Build-Up", "2950"],
    ["Veneers", "2962"],
    ["Bridge", "6750"],
    ["Dentures", "5110"],
    ["Palliative Treatment", "9110"],
    ["General Anesthesia", "9222"],
    ["Nitrous Oxide", "9230"],
    ["General Sedation / IV Sedation", "9243"],
    ["Consultation", "9310"],
    ["Occlusal Guard", "9944"],
    ["Scaling & Root Planing", "4341"],
    ["Full Mouth Debridement", "4355"],
    ["Gingivitis Treatment", "4346"],
    ["Periodontal Maintenance", "4910"],
    ["Arestin", "4381"],
    ["Osseous Surgery", "4260"],
    ["Crown Lengthening", "4249"],
    ["Root Canal Anterior", "3310"],
    ["Root Canal Molar", "3330"],
    ["Simple Extraction", "7140"],
    ["Surgical Extraction", "7210"],
    ["Impacted Extraction", "7240"],
    ["Bone Graft with Extraction", "7953"],
    ["Implant", "6010"],
    ["Implant Abutment", "6056"]
];


// ══════════════════════════════════════════════════════════════════════════
// PATIENT HEADER / PLAN INFO
// ══════════════════════════════════════════════════════════════════════════

function scrapePatientHeader() {
    const heading = Array.from(document.querySelectorAll("h1,h2,h3"))
        .find(h => /dental eligibility/i.test(h.textContent || ""));
    const name = heading ? clean(heading.textContent).replace(/dental eligibility/i, "").trim() : "N/A";

    const asOfMatch = (document.body.innerText || "").match(/as of\s*([\d\/]+)/i);
    return {
        name,
        as_of_date: asOfMatch ? asOfMatch[1] : "N/A"
    };
}

function getLabelValue(labelText) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        if (node.textContent.trim() !== labelText) continue;
        const labelEl = node.parentElement;
        const sib = labelEl.nextElementSibling;
        if (sib?.innerText?.trim()) return clean(sib.innerText);
        const parentSib = labelEl.parentElement?.nextElementSibling;
        if (parentSib?.innerText?.trim()) return clean(parentSib.innerText);
        return "N/A";
    }
    return "N/A";
}

function scrapePlanInfo() {
    return {
        benefit_period: getLabelValue("Benefit period"),
        date_of_birth: getLabelValue("Date of birth"),
        dependent_age_limit: getLabelValue("Dependent age limit"),
        student_age_limit: getLabelValue("Student age limit"),
        group_name: getLabelValue("Group name"),
        group_number: getLabelValue("Group number"),
        orthodontics_age_limit: getLabelValue("Orthodontics age limit")
    };
}

function scrapePlanBullets() {
    const items = Array.from(document.querySelectorAll("li"));
    const planNameEl = items.find(li => /the patient'?s plan is/i.test(li.textContent || ""));
    const oonEl = items.find(li => /out of network benefits/i.test(li.textContent || ""));
    return {
        plan_name: planNameEl
            ? clean(planNameEl.textContent).replace(/^the patient'?s plan is\s*/i, "").replace(/\.$/, "")
            : "N/A",
        out_of_network_note: oonEl ? clean(oonEl.textContent) : "N/A"
    };
}


// ══════════════════════════════════════════════════════════════════════════
// GENERIC TABLE HELPERS (Effective Dates / Deductibles / Maximums)
// ══════════════════════════════════════════════════════════════════════════

function findTableByHeaderText(requiredHeaders, root = document) {
    const tables = Array.from(root.querySelectorAll("table"));
    for (const table of tables) {
        const headerText = Array.from(table.querySelectorAll("th")).map(th => clean(th.innerText).toLowerCase());
        const allFound = requiredHeaders.every(req => headerText.some(h => h.includes(req.toLowerCase())));
        if (allFound) return table;
    }
    return null;
}

function tableToObjects(table) {
    if (!table) return [];
    const headers = Array.from(table.querySelectorAll("th")).map(th => clean(th.innerText).toLowerCase());
    let rows = Array.from(table.querySelectorAll("tbody tr"));
    if (!rows.length) rows = Array.from(table.querySelectorAll("tr")).filter(tr => tr.querySelectorAll("td").length);
    return rows.map(row => {
        const cells = Array.from(row.querySelectorAll("td")).map(td => clean(td.innerText));
        const obj = {};
        headers.forEach((h, i) => { if (h) obj[h] = cells[i] ?? ""; });
        return obj;
    });
}

function scrapeEffectiveDates() {
    const table = findTableByHeaderText(["name", "prev"]) || findTableByHeaderText(["name", "relation"]);
    return tableToObjects(table);
}

function scrapeDeductibles() {
    const table = findTableByHeaderText(["coverage", "deductible"]);
    return tableToObjects(table);
}

function scrapePlanMaximums() {
    const table = findTableByHeaderText(["coverage", "yearly plan limit"]) ||
        findTableByHeaderText(["coverage", "network", "yearly"]);
    return tableToObjects(table);
}


// ══════════════════════════════════════════════════════════════════════════
// EXPAND ACCORDIONS
// ══════════════════════════════════════════════════════════════════════════

async function expandAllSections() {
    const expandBtn = document.querySelector("button.expand-collapse-all-link") ||
        Array.from(document.querySelectorAll("a,button,span"))
            .find(el => clean(el.textContent).toLowerCase() === "expand all");
    if (expandBtn) {
        expandBtn.click();
        await sleep(800);
    }
}

async function ensureCdtSectionExpanded() {
    let input = findCdtInput();
    if (input) return input;

    await expandAllSections();
    input = findCdtInput();
    if (input) return input;

    const header = findByRegex(/search coverage by cdt code/i);
    const toggle = header && (header.closest("button,a,[role='button'],h1,h2,h3,h4,div") || header);
    if (toggle) {
        toggle.click();
        await sleep(500);
    }
    return findCdtInput();
}


// ══════════════════════════════════════════════════════════════════════════
// CDT CODE INPUT / SEARCH BUTTON / RESULTS
// ══════════════════════════════════════════════════════════════════════════

function findCdtInput() {
    let input = document.getElementById("cdtInput");
    if (input) return input;

    input = document.querySelector("input[placeholder*='CDT' i]") ||
        document.querySelector("input[aria-label*='CDT' i]") ||
        document.querySelector("input[name*='cdt' i]") ||
        document.querySelector("input[id*='cdt' i]");
    if (input) return input;

    const labelEl = findByRegex(/enter\s*4-?digit\s*cdt\s*code/i);
    if (labelEl) {
        const container = labelEl.closest("div,section,fieldset") || labelEl.parentElement;
        input = container && container.querySelector("input");
        if (input) return input;
    }
    return findInputNearSearchButton();
}

function findInputNearSearchButton() {
    const btn = Array.from(document.querySelectorAll("button")).find(b => clean(b.textContent) === "Search");
    if (!btn) return null;
    let parent = btn.parentElement;
    for (let i = 0; i < 5; i++) {
        if (!parent) break;
        const input = parent.querySelector("input[type='text'],input:not([type])");
        if (input) return input;
        parent = parent.parentElement;
    }
    return null;
}

function findSearchButton() {
    return document.getElementById("cdt-search-button") ||
        Array.from(document.querySelectorAll("button")).find(b => clean(b.textContent) === "Search" && !b.disabled) ||
        null;
}

// Plain .click() on this button doesn't work — confirmed via testing that
// NO network request fires regardless of which JS-dispatched event
// sequence is used. Site's anti-bot layer appears to specifically ignore
// non-trusted (isTrusted: false) clicks on actions that hit its backend.
// This relays through background.js, which uses the Chrome DevTools
// Protocol (chrome.debugger) to inject a genuinely trusted click at the
// button's screen coordinates — indistinguishable from a real click.
function sendTrustedClick(el) {
    const rect = el.getBoundingClientRect();
    return new Promise((resolve) => {
        chrome.runtime.sendMessage({
            command: "TRUSTED_CLICK",
            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
        }, (response) => resolve(response || { success: false, error: "No response from background" }));
    });
}

function isLoadingModalVisible() {
    const el = findByRegex(/please wait while your request is being processed/i);
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
}

// The static "Plan options" table (full list, ~23 rows) shares identical
// column headers with the small dynamic CDT-search result (1-3 rows).
// Rather than guess at DOM containers, pick whichever matching table has
// the fewest rows, capped at maxRows — so the big static table never gets
// mistaken for a real search result.
function findCdtResultTable(maxRows = 5) {
    const tables = Array.from(document.querySelectorAll("table"));
    let best = null, bestCount = Infinity;
    for (const table of tables) {
        const headerText = Array.from(table.querySelectorAll("th")).map(th => clean(th.innerText).toLowerCase());
        const isMatch = ["service", "coinsurance"].every(req => headerText.some(h => h.includes(req)));
        if (!isMatch) continue;
        const rowCount = table.querySelectorAll("tbody tr").length || table.querySelectorAll("tr").length;
        if (rowCount > 0 && rowCount <= maxRows && rowCount < bestCount) {
            best = table;
            bestCount = rowCount;
        }
    }
    return best;
}

function getResultsRawText() {
    const table = findCdtResultTable();
    return table ? clean(table.innerText) : "";
}

function scrapeCdtResultTable(code) {
    const table = findCdtResultTable();
    const rows = tableToObjects(table);
    return rows.map(r => ({
        cdt_code: "D" + code,
        service: r["service"] || "N/A",
        network: r["network"] || "N/A",
        category: r["category"] || "N/A",
        coinsurance: r["coinsurance"] || "N/A",
        message: r["message"] || "N/A",
        last_visit: r["last visit"] || "N/A"
    }));
}


// ══════════════════════════════════════════════════════════════════════════
// LOW-LEVEL: run ONE code, click Search, wait, scrape
// ══════════════════════════════════════════════════════════════════════════

async function runOneCode(code) {
    const input = findCdtInput();
    if (!input) return [];

    await simulateTyping(input, code);
    await sleep(300);
    console.log(`[Audit] D${code} — value after typing:`, JSON.stringify(input.value));

    const searchBtn = findSearchButton();
    if (!searchBtn) return [];

    const prevRaw = getResultsRawText();
    const clickResult = await sendTrustedClick(searchBtn);
    if (!clickResult.success) {
        console.error(`[Audit] D${code} — trusted click failed:`, clickResult.error);
        return [];
    }

    const deadline = Date.now() + 12000;
    while (Date.now() < deadline) {
        const loading = isLoadingModalVisible();
        const currentRaw = getResultsRawText();
        if (!loading && currentRaw && currentRaw !== prevRaw) break;
        await sleep(300);
    }
    await sleep(500);

    return scrapeCdtResultTable(code);
}


// ══════════════════════════════════════════════════════════════════════════
// BUILD PLAN OVERVIEW PAYLOAD
// ══════════════════════════════════════════════════════════════════════════

function buildPlanOverviewPayload() {
    return {
        source: "Guardian Portal - Plan Overview",
        timestamp: new Date().toISOString(),
        patient_header: scrapePatientHeader(),
        plan_info: scrapePlanInfo(),
        plan_bullets: scrapePlanBullets(),
        effective_dates: scrapeEffectiveDates(),
        deductibles: scrapeDeductibles(),
        plan_maximums: scrapePlanMaximums()
    };
}


// ══════════════════════════════════════════════════════════════════════════
// CRAWL — PLAN OVERVIEW
// ══════════════════════════════════════════════════════════════════════════

async function crawlPlanOverview() {
    await expandAllSections();
    const data = buildPlanOverviewPayload();

    return new Promise((resolve) => {
        chrome.storage.local.get("audit_context", (res) => {
            const ctx = res.audit_context || {};
            ctx.guardian_data = data;
            chrome.storage.local.set({ audit_context: ctx }, () => {
                const got = data.effective_dates.length > 0;
                resolve({ status: got ? `[+] Plan Overview saved (${data.effective_dates.length} coverage row(s)).` : `[!] Saved but effective dates table not found — stay on the eligibility page and retry.` });
            });
        });
    });
}


// ══════════════════════════════════════════════════════════════════════════
// CRAWL — BENEFIT & COVERAGE (search coverage by CDT code, one code at a time)
// ══════════════════════════════════════════════════════════════════════════

async function crawlBenefitCoverage(extraCodes = "") {
    const extraList = extraCodes
        ? extraCodes.split(",").map(c => c.trim().toUpperCase().replace(/^D/, "")).filter(Boolean)
        : [];
    const allCodes = [...new Set([...CDT_CODES.map(c => c[1]), ...extraList])];

    const input = await ensureCdtSectionExpanded();
    if (!input) {
        return { status: "[!] CDT code input not found — open 'Search coverage by CDT code' manually and retry." };
    }
    await sleep(1500); // let the section fully settle before the first search

    const allResults = [];
    for (let i = 0; i < allCodes.length; i++) {
        const code = allCodes[i];
        console.log(`[Audit] CDT ${i + 1}/${allCodes.length}: D${code}`);
        try {
            let rows = await runOneCode(code);
            if (!rows.length) {
                console.warn(`[Audit] D${code} — no rows on first attempt, retrying once...`);
                await sleep(800);
                rows = await runOneCode(code);
            }
            allResults.push(...(rows.length ? rows : [{ cdt_code: "D" + code, error: "No table rows found (after retry)" }]));
        } catch (e) {
            console.error(`[Audit] D${code} failed:`, e);
            allResults.push({ cdt_code: "D" + code, error: String(e.message || e) });
        }
        await sleep(60000); // 60s between codes — paced well below Incapsula's rate-limit threshold
    }

    return new Promise((resolve) => {
        chrome.storage.local.get("audit_context", (res) => {
            const ctx = res.audit_context || {};
            ctx.benefit_coverage = {
                source: "Guardian Portal - Search Coverage by CDT Code",
                timestamp: new Date().toISOString(),
                codes_searched: allCodes.map(c => "D" + c),
                extra_codes: extraList.map(c => "D" + c),
                result_count: allResults.length,
                results: allResults
            };
            chrome.storage.local.set({ audit_context: ctx }, () => {
                resolve({ status: `[+] Scraped ${allResults.length} row(s) across ${allCodes.length} code(s).` });
            });
        });
    });
}


// ══════════════════════════════════════════════════════════════════════════
// DOWNLOAD HELPER
// ══════════════════════════════════════════════════════════════════════════

function downloadAuditJSON() {
    chrome.storage.local.get("audit_context", (res) => {
        const data = res.audit_context || {};
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const patient = data?.guardian_data?.patient_header?.name
            ?.replace(/[^a-z0-9]/gi, "_")?.toLowerCase() || "patient";
        a.download = `${patient}_guardian_audit.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    });
}


// ══════════════════════════════════════════════════════════════════════════
// MESSAGE LISTENER
// ══════════════════════════════════════════════════════════════════════════

function detachDebugger() {
    chrome.runtime.sendMessage({ command: "DETACH_DEBUGGER" }, () => { /* best-effort cleanup */ });
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

    if (request.command === "START_CRAWL") {
        (async () => {
            await crawlPlanOverview();
            const res = await crawlBenefitCoverage("");
            downloadAuditJSON();
            detachDebugger();
            sendResponse({ status: res.status + " JSON downloaded." });
        })();
        return true;
    }

    if (request.command === "CRAWL_PLAN_OVERVIEW") {
        crawlPlanOverview().then(sendResponse).catch(() => sendResponse({ status: "[!] Error." }));
        return true;
    }

    if (request.command === "CRAWL_BENEFIT_COVERAGE") {
        crawlBenefitCoverage(request.extraCodes || "")
            .then((res) => { detachDebugger(); sendResponse(res); })
            .catch(() => { detachDebugger(); sendResponse({ status: "[!] Error." }); });
        return true;
    }
});