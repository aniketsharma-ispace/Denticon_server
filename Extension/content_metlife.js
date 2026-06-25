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

function setReactInputValue(input, value) {
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeSetter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
}

// 61 codes across 7 batches — chunked into groups of 10 at runtime (site hard limit)
const BATCH_1 = ["D1110", "D4910", "D4355", "D1206", "D1208", "D0274", "D0210", "D0120", "D0150"];
const BATCH_2 = ["D2331", "D2140", "D2740", "D1351", "D1510", "D8080", "D0180", "D0140", "D0240"];
const BATCH_3 = ["D0330", "D0220", "D0230", "D0364", "D0431", "D1120", "D2991", "D2950", "D2620"];
const BATCH_4 = ["D2962", "D6750", "D5110", "D9110", "D9222", "D9243", "D9310", "D9944", "D4341"];
const BATCH_5 = ["D4346", "D4381", "D4260", "D4249", "D3310", "D3330", "D7140", "D7210", "D7240"];
const BATCH_6 = ["D7953", "D6010", "D6056", "D2332", "D6245", "D5860", "D5740", "D5982", "D9430"];
const BATCH_7 = ["D9239", "D3347", "D7259", "D6065", "D6194", "D8010", "D8090", "D9230"];

async function scrapeSubscriberFromDropdown() {
    try {
        // Click the patient name h3 to open dropdown
        const h3 = document.querySelector("h3.patient-name");
        if (!h3) {
            console.warn("[Audit] h3.patient-name not found — skipping");
            return null;
        }

        h3.click();
        await sleep(1200);

        // Find the li containing the Subscriber relation span
        let subscriberEntry = null;
        const spans = document.querySelectorAll(".dropdown-patient-relation");
        for (const span of spans) {
            if (span.innerText.trim() === "Subscriber") {
                subscriberEntry = span.closest("li");
                break;
            }
        }

        if (!subscriberEntry) {
            console.warn("[Audit] Subscriber li not found — closing dropdown");
            document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
            await sleep(400);
            return null;
        }

        // Parse the 3 lines: name / relation / "48 | DOB: 05/18/1978 | Male"
        const lines = subscriberEntry.innerText.split("\n").map(l => l.trim()).filter(Boolean);
        const name     = lines[0] || "N/A";
        const relation = lines[1] || "Subscriber";
        const detail   = lines[2] || "";
        const age      = detail.match(/^(\d+)/)?.[1] || "N/A";
        const dob      = detail.match(/DOB:\s*([\d\/]+)/)?.[1] || "N/A";
        const gender   = detail.match(/\|\s*(Male|Female)/i)?.[1]?.trim() || "N/A";

        // Close dropdown without switching patient
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        await sleep(600);

        const result = { name, relation, age, dob, gender };
        console.log("[Audit] Subscriber scraped:", result);
        return result;

    } catch (err) {
        console.error("[Audit] scrapeSubscriberFromDropdown error (non-fatal):", err);
        return null;
    }
}

// ══════════════════════════════════════════════════════════════════════════
// PATIENT INFO
// ══════════════════════════════════════════════════════════════════════════

function scrapePatientInfo() {
    const name = document.querySelector(".patient-name")?.innerText?.trim() ||
        document.querySelector("[class*='patient'] [class*='name']")?.innerText?.trim() || "N/A";
    const cardText = document.querySelector(".card-details, [class*='card-detail'], [class*='member-info']")?.innerText || "";
    return {
        name,
        dob: cardText.match(/DOB:\s*(\d{2}\/\d{2}\/\d{4})/)?.[1] || "N/A",
        relationship: cardText.match(/^([^\|]+)/)?.[1]?.trim() || "N/A",
        gender: cardText.match(/\|\s*(Male|Female)\s*/i)?.[1]?.trim() || "N/A"
    };
}


// ══════════════════════════════════════════════════════════════════════════
// PLAN DETAILS
// ══════════════════════════════════════════════════════════════════════════

function scrapePlanDetails() {
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
        }
        return "N/A";
    }
    return {
        start_date: getLabelValue("Start Date"),
        end_date: getLabelValue("End Date"),
        subscriber_id: getLabelValue("Subscriber SSN or ID"),
        employer_group: getLabelValue("Employer / Group #"),
        network: getLabelValue("Network"),
        address: getLabelValue("Address")
    };
}

function scrapeProviderInfo() {
    const networkBadge = Array.from(document.querySelectorAll("*")).find(el =>
        /^(in-network|out-of-network)$/i.test((el.innerText || "").trim())
    );

    return {
        provider_network_status: networkBadge ? (networkBadge.innerText || "").trim() : "N/A"
    };
}
// ══════════════════════════════════════════════════════════════════════════
// FINANCIALS
// ══════════════════════════════════════════════════════════════════════════

function findCardByLabel(labelText) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        if (node.textContent.trim() !== labelText) continue;
        let el = node.parentElement;
        for (let i = 0; i < 5; i++) {  // was 8 — reduce to avoid bleeding into sibling cards
            if (!el) break;
            const dollars = (el.innerText || "").match(/\$\s*[\d,]+/g) || [];
            const text = el.innerText || "";
            // Stop if we've absorbed text from a SIBLING card label (Annual/Lifetime/Individual)
            const siblingLabels = ["Annual", "Lifetime", "Individual", "Family"].filter(l => l !== labelText);
            if (siblingLabels.some(l => text.includes(l)) && dollars.length >= 2) break;
            if (dollars.length >= 2) return el;
            el = el.parentElement;
        }
    }
    return null;
}

function parseCardAmounts(container) {
    if (!container) return { remaining: "N/A", used: "N/A", total: "N/A" };
    const text = container.innerText || "";
    return {
        remaining: text.match(/\$\s*[\d,]+\.?\d*\s*remaining/i)?.[0]?.replace(/\s+/g, ' ').trim() || "N/A",
        used: text.match(/\$\s*[\d,]+\.?\d*\s*(?:used|paid)\s*to\s*date/i)?.[0]?.replace(/\s+/g, ' ').trim() || "N/A",
        total: text.match(/\$\s*[\d,]+\.?\d*\s*total/i)?.[0]?.replace(/\s+/g, ' ').trim() || "N/A"
    };
}

function scrapeFinancials() {
    const annualCard = findCardByLabel("Annual");
 
    // ── Lifetime: check for "no lifetime" message first ──
    const lifetimeCard = findCardByLabel("Lifetime");
    let ortho_lifetime;
 
    if (!lifetimeCard) {
        ortho_lifetime = { remaining: "0.0", used: "0.0", total: "0.0" };
    } else {
        const lifetimeText = lifetimeCard.innerText || "";
        if (/no lifetime benefit maximum/i.test(lifetimeText)) {
            ortho_lifetime = { remaining: "0.0", used: "0.0", total: "0.0" };
        } else {
            ortho_lifetime = parseCardAmounts(lifetimeCard);
        }
    }
        // ── Family deductible (may not exist for all plans) ──
    const famCard = findCardByLabel("Family");
    const deductible_fam = famCard
        ? parseCardAmounts(famCard)
        : { remaining: "N/A", used: "N/A", total: "N/A" };

    return {
        annual_max:     parseCardAmounts(annualCard),
        ortho_lifetime,
        deductible_ind: parseCardAmounts(findCardByLabel("Individual")),
        deductible_fam,                                                   // ← NEW
    };
}


// ══════════════════════════════════════════════════════════════════════════
// COVERED SERVICES
// ══════════════════════════════════════════════════════════════════════════

function scrapeCoveredServices() {
    const heading = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6"))
        .find(h => h.textContent.trim() === "Covered Services") || findByText("Covered Services");
    let table = null;
    if (heading) {
        const section = heading.closest("section,[class*='section']") || heading.parentElement;
        table = section?.querySelector("table") || heading.parentElement?.nextElementSibling?.querySelector("table");
    }
    if (!table) table = Array.from(document.querySelectorAll("table")).find(t => t.innerText.includes("Procedure Category"));
    if (!table) return [];

    return Array.from(table.querySelectorAll("tr")).slice(1).map(row => {
        const cells = row.querySelectorAll("td");
        if (cells.length < 2) return null;
        const categoryName = cells[0].querySelector("strong,b")?.innerText?.trim() || cells[0].innerText.split('\n')[0].trim();
        return {
            category: categoryName,
            services: clean(cells[0].innerText).replace(categoryName, "").trim() || "N/A",
            in_network: clean(cells[1]?.innerText) || "N/A",
            out_of_network: clean(cells[2]?.innerText) || "N/A"
        };
    }).filter(r => r && r.category);
}


// ══════════════════════════════════════════════════════════════════════════
// PLAN PROVISIONS
// ══════════════════════════════════════════════════════════════════════════

function scrapeProvisions() {
    // ── 1. Try heading-anchored search (existing logic) ──────────────────
    const heading = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6"))
        .find(h => h.textContent.trim().includes("Plan Provisions"))
        || findByText("Plan Provisions");

    let section = null;
    if (heading) {
        let el = heading.nextElementSibling;
        while (el) {
            if ((el.innerText || "").trim().length > 50) { section = el; break; }
            el = el.nextElementSibling;
        }
        if (!section)
            section = heading.closest("[class*='provision'],section") || heading.parentElement;
    }
    if (!section) section = document.querySelector("[class*='provision'],[class*='Provision']");

    // ── 2. If we have a section, try to parse its table ──────────────────
    if (section) {
        const tableRows = section.querySelectorAll("table tr, tbody tr");
        if (tableRows.length) {
            const results = Array.from(tableRows).map(tr => {
                const c = tr.querySelectorAll("td");
                if (c.length < 2) return null;
                return { rule: clean(c[0]?.innerText), value: clean(c[1]?.innerText) };
            }).filter(r => r && r.rule && r.value);
            if (results.length) return results;
        }
    }

    // ── 3. Fallback: scan ALL tables on page for a provisions-like table ──
    //    Identified by known first-column labels from MetLife's Plan Provisions table
    const PROVISION_ANCHORS = [
        "Coverage is selected for",
        "Basis of payment",
        "Waiting Period",
        "Maximum child age",
        "Coordination of Benefits Rule",
        "Alternate Benefits",
        "Orthodontic Coverage",
        "Ortho payment method",
        "Cleanings and Periodontal Maintenance"
    ];

    for (const table of document.querySelectorAll("table")) {
        const rows = Array.from(table.querySelectorAll("tr"));
        const cellTexts = rows.flatMap(r =>
            Array.from(r.querySelectorAll("td")).map(td => clean(td.innerText))
        );
        const matchCount = PROVISION_ANCHORS.filter(a =>
            cellTexts.some(t => t.includes(a))
        ).length;

        if (matchCount >= 3) {
            // This is the provisions table — parse all rows
            return rows.map(tr => {
                const cells = tr.querySelectorAll("td");
                if (cells.length < 2) return null;
                return {
                    rule: clean(cells[0]?.innerText),
                    value: clean(cells[1]?.innerText)
                };
            }).filter(r => r && r.rule && r.value);
        }
    }

    // ── 4. Last-resort: bold-label pairs inside heading's parent ─────────
    if (section) {
        const dts = section.querySelectorAll("dt");
        if (dts.length) return Array.from(dts).map(dt => ({
            rule: clean(dt.innerText),
            value: clean(dt.nextElementSibling?.innerText)
        })).filter(r => r.rule);

        const boldEls = section.querySelectorAll("strong,b,[class*='label'],[class*='key']");
        if (boldEls.length >= 3) {
            const results = Array.from(boldEls).map(el => ({
                rule: clean(el.innerText),
                value: clean((el.parentElement?.innerText || "").replace(el.innerText, "").trim())
                    || clean(el.nextElementSibling?.innerText) || "N/A"
            })).filter(r => r.rule && r.value && r.rule !== r.value);
            if (results.length >= 3) return results;
        }
    }

    return [];
}


// ══════════════════════════════════════════════════════════════════════════
// BUILD PLAN OVERVIEW PAYLOAD
// ══════════════════════════════════════════════════════════════════════════

function buildPlanOverviewPayload() {
    return {
        source: "MetLife Portal - Plan Overview",
        timestamp: new Date().toISOString(),
        patient: scrapePatientInfo(),
        plan_details: scrapePlanDetails(),
        provider_info: scrapeProviderInfo(),  // now just { provider_network_status }
        financials: scrapeFinancials(),
        covered_services: scrapeCoveredServices(),
        provisions: scrapeProvisions()
    };
}


// ══════════════════════════════════════════════════════════════════════════
// CRAWL — PLAN OVERVIEW
// ══════════════════════════════════════════════════════════════════════════

async function crawlPlanOverview() {
    const tabEl = findByText("Plan Overview");
    if (tabEl) { tabEl.click(); await sleep(2500); }
    
    const data = buildPlanOverviewPayload();

    return new Promise((resolve) => {
        chrome.storage.local.set({ audit_context: { metlife_data: data } }, () => {
            const got = Object.values(data.financials).some(f => Object.values(f).some(v => v !== "N/A"));
            resolve({ status: got ? `[+] Plan Overview saved (${data.provisions.length} provisions).` : `[!] Saved but financials N/A — stay on Plan Overview and retry.` });
        });
    });
}


// ══════════════════════════════════════════════════════════════════════════
// LOW-LEVEL: run one batch of codes, click Search, scrape table
// ══════════════════════════════════════════════════════════════════════════

async function runOneBatch(codes) {
    let codeInput = document.querySelector("input[placeholder*='rocedure']") ||
        document.querySelector("input[placeholder*='ode']") ||
        document.querySelector("input[aria-label*='rocedure']") ||
        findInputNearSearchButton();
    if (!codeInput) codeInput = await waitForElement("input[type='text']:not([readonly])", 6000);
    if (!codeInput) return [];

    const resetBtn = Array.from(document.querySelectorAll("button")).find(b => b.textContent.trim() === "Reset");
    if (resetBtn) { resetBtn.click(); await sleep(800); }

    codeInput.focus();
    setReactInputValue(codeInput, "");
    await sleep(200);
    setReactInputValue(codeInput, codes.join(","));
    await sleep(400);

    const searchBtn = Array.from(document.querySelectorAll("button")).find(b => b.textContent.trim() === "Search" && !b.disabled);
    if (!searchBtn) return [];

    searchBtn.click();
    await sleep(2500);

    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
        const text = document.body.innerText || "";
        if (codes.some(code => text.includes(code))) break;
        await sleep(500);
    }

    await sleep(1200);
    return scrapeProcedureTable();
}


// ══════════════════════════════════════════════════════════════════════════
// CRAWL — BENEFIT & COVERAGE  (all batches merged, chunked by 10)
// ══════════════════════════════════════════════════════════════════════════

async function crawlBenefitCoverage(extraCodes = "") {
    const tabEl = findByText("Benefit & Coverage Details");
    if (tabEl) { tabEl.click(); await sleep(2500); }

    // Scrape subscriber — non-fatal, cannot block procedure scraping
    let subscriberInfo = null;
    try {
        subscriberInfo = await scrapeSubscriberFromDropdown();
        console.log("[Audit] Subscriber info:", subscriberInfo);
    } catch (e) {
        console.error("[Audit] Subscriber scrape failed (non-fatal):", e);
    }

    // Save subscriber immediately before batches start
    if (subscriberInfo) {
        await new Promise(resolve => {
            chrome.storage.local.get("audit_context", (res) => {
                const ctx = res.audit_context || {};
                ctx.subscriber_info = subscriberInfo;
                chrome.storage.local.set({ audit_context: ctx }, resolve);
            });
        });
    }

    const extraList = extraCodes
        ? extraCodes.split(",").map(c => c.trim().toUpperCase()).filter(Boolean)
        : [];

    const allCodes = [...new Set([
        ...BATCH_1, ...BATCH_2, ...BATCH_3,
        ...BATCH_4, ...BATCH_5, ...BATCH_6,
        ...BATCH_7, ...extraList
    ])];

    const CHUNK_SIZE = 10;
    const chunks = [];
    for (let i = 0; i < allCodes.length; i += CHUNK_SIZE) {
        chunks.push(allCodes.slice(i, i + CHUNK_SIZE));
    }

    const seen = new Set();
    const allProcedures = [];

    for (let i = 0; i < chunks.length; i++) {
        console.log(`[Audit] Chunk ${i + 1}/${chunks.length}: ${chunks[i].join(",")}`);
        try {
            const batchResults = await runOneBatch(chunks[i]);
            for (const proc of batchResults) {
                if (!seen.has(proc.procedure_code)) {
                    seen.add(proc.procedure_code);
                    allProcedures.push(proc);
                }
            }
        } catch (e) {
            console.error(`[Audit] Chunk ${i + 1} failed:`, e);
        }
        if (i < chunks.length - 1) await sleep(1000);
    }

    return new Promise((resolve) => {
        chrome.storage.local.get("audit_context", (res) => {
            const ctx = res.audit_context || {};
            ctx.subscriber_info = subscriberInfo;
            ctx.benefit_coverage = {
                source: "MetLife Portal - Benefit & Coverage Details",
                timestamp: new Date().toISOString(),
                codes_searched: allCodes,
                extra_codes: extraList,
                procedure_count: allProcedures.length,
                procedures: allProcedures
            };
            chrome.storage.local.set({ audit_context: ctx }, () => {
                resolve({ status: `[+] Scraped ${allProcedures.length} procedures across ${chunks.length} chunk(s).` });
            });
        });
    });
}


// ══════════════════════════════════════════════════════════════════════════
// TABLE & INPUT HELPERS
// ══════════════════════════════════════════════════════════════════════════

function scrapeProcedureTable() {
    const rows = document.querySelectorAll("table tbody tr");
    if (!rows.length) return [];
    return Array.from(rows).map(row => {
        const cells = row.querySelectorAll("td");
        if (cells.length < 4) return null;
        return {
            procedure_code: clean(cells[0]?.innerText),
            description: clean(cells[1]?.innerText),
            frequency_limit: clean(cells[2]?.innerText),
            age_limit: clean(cells[3]?.innerText),
            late_date_of_service: clean(cells[4]?.innerText) || "—",
            deductible: clean(cells[5]?.innerText) || "N/A",
            network_fee: clean(cells[6]?.innerText) || "N/A",
            benefit_level: clean(cells[7]?.innerText) || "N/A",
            patient_responsibility: clean(cells[8]?.innerText) || "N/A"
        };
    }).filter(r => r && r.procedure_code);
}

function findInputNearSearchButton() {
    const btn = Array.from(document.querySelectorAll("button")).find(b => b.textContent.trim() === "Search");
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


// ══════════════════════════════════════════════════════════════════════════
// PASSIVE BACKGROUND SYNC
// ══════════════════════════════════════════════════════════════════════════

setInterval(() => {
    if (!chrome.runtime?.id) return;
    if (!(document.body?.innerText || "").includes("Benefit Maximums")) return;
    const data = buildPlanOverviewPayload();
    chrome.storage.local.get("audit_context", (res) => {
        const ctx = res.audit_context || {};
        ctx.metlife_data = data;
        chrome.storage.local.set({ audit_context: ctx });
    });
}, 5000);


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
        const patient = data?.metlife_data?.patient?.name
            ?.replace(/[^a-z0-9]/gi, "_")?.toLowerCase() || "patient";
        a.download = `${patient}_metlife_audit.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    });
}


// ══════════════════════════════════════════════════════════════════════════
// MESSAGE LISTENER
// ══════════════════════════════════════════════════════════════════════════

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

    if (request.command === "START_CRAWL") {
        (async () => {
            await crawlPlanOverview();
            const res = await crawlBenefitCoverage("");
            downloadAuditJSON();
            sendResponse({ status: res.status + " JSON downloaded." });
        })();
        return true;
    }

    if (request.command === "CRAWL_PLAN_OVERVIEW") {
        crawlPlanOverview().then(sendResponse).catch(() => sendResponse({ status: "[!] Error." }));
        return true;
    }

    if (request.command === "CRAWL_BENEFIT_COVERAGE") {
        crawlBenefitCoverage(request.extraCodes || "").then(sendResponse).catch(() => sendResponse({ status: "[!] Error." }));
        return true;
    }
});