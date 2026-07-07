const clean = (s) => (s || "").trim().replace(/\s+/g, " ");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const PROCEDURE_CODES = [
    "D1110", "D4910", "D4355", "D1206", "D1208",
    "D0274", "D0210", "D0120", "D0150", "D2331",
    "D2140", "D2740", "D1351", "D1510", "D8080",
];

const CODE_DESCRIPTIONS = {
    D1110: "PROPHYLAXIS- ADULT",
    D4910: "PERIODONTAL MAINTENANCE",
    D4355: "FULL MOUTH DEBRIDEMENT",
    D1206: "TOPICAL FLUORIDE-VARNISH",
    D1208: "TOPICAL APPLICATION-FLUORIDE",
    D0274: "BITEWINGS-FOUR IMAGES",
    D0210: "INTRAORAL-SERIES OF RADIOGRAPHS",
    D0120: "PERIODIC ORAL EVAL ESTABL PAT",
    D0150: "COMPREHENSIVE ORAL EVALUATION",
    D2331: "TWO SURFACE COMPOSITE ANTERIOR",
    D2140: "ONE SURFACE AMALGAM",
    D2740: "CROWN PORCELAIN/CERAMIC",
    D1351: "SEALANT - PER TOOTH",
    D1510: "SPACE MAINTAIN FIXED-UNILATER",
    D8080: "COMPREHENSIVE ORTHO - ADOLESCENT",
};

function setReactInputValue(input, value) {
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    nativeSetter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter", keyCode: 13 }));
    input.dispatchEvent(new Event("blur", { bubbles: true }));
}

function findLookupButton() {
    const labels = ["lookup", "search", "go", "find"];
    for (const label of labels) {
        const match = Array.from(document.querySelectorAll("button, input[type='button'], input[type='submit']")).find((el) => {
            const text = clean(el.innerText || el.value || "").toLowerCase();
            return text === label && !el.disabled;
        });
        if (match) return match;
    }
    return document.querySelector("button[type='submit'], input[type='submit']") || null;
}

function findCodeInput() {
    const selectors = [
        "input[placeholder*='rocedure']",
        "input[placeholder*='ode']",
        "input[aria-label*='rocedure']",
        "input[aria-label*='ode']",
        "input[name*='procedure']",
        "input[name*='code']",
        "input[type='text']",
        "input:not([type])",
    ];

    for (const selector of selectors) {
        const el = document.querySelector(selector);
        if (el) return el;
    }

    const btn = findLookupButton();
    if (!btn) return null;
    let parent = btn.parentElement;
    for (let i = 0; i < 6; i++) {
        if (!parent) break;
        const inp = parent.querySelector("input[type='text'], input:not([type])");
        if (inp) return inp;
        parent = parent.parentElement;
    }
    return null;
}

async function waitForResult(timeout = 12000) {
    const deadline = Date.now() + timeout;
    let lastText = "";
    while (Date.now() < deadline) {
        const panel = document.querySelector("#procedureBenefitResults, .procedure-benefits, [data-testid='procedure-results']");
        const text = clean(panel?.innerText || document.body.innerText);
        if (panel && text && text.length > 20 && text !== lastText) return true;
        if (/no results|no benefit|not available|not found/i.test(text)) return true;
        lastText = text;
        await sleep(400);
    }
    return false;
}

function getLabelValue(labelText) {
    const allEls = document.querySelectorAll("td, th, dt, label, span, div, p, b, strong");
    for (const el of allEls) {
        if (clean(el.innerText).toLowerCase() === labelText.toLowerCase()) {
            const row = el.closest("tr");
            if (row) {
                const cells = row.querySelectorAll("td");
                if (cells.length >= 2) return clean(cells[cells.length - 1].innerText);
            }
            const next = el.nextElementSibling;
            if (next && clean(next.innerText)) return clean(next.innerText);
            const parentNext = el.parentElement?.nextElementSibling;
            if (parentNext && clean(parentNext.innerText)) return clean(parentNext.innerText);
        }
    }
    return "N/A";
}

function getLabelValuePartial(partial) {
    const allEls = document.querySelectorAll("td, th, b, strong, label, span");
    for (const el of allEls) {
        const txt = clean(el.innerText);
        if (txt.toLowerCase().includes(partial.toLowerCase())) {
            const row = el.closest("tr");
            if (row) {
                const cells = row.querySelectorAll("td");
                if (cells.length >= 2) return clean(cells[cells.length - 1].innerText);
            }
            const next = el.nextElementSibling;
            if (next && clean(next.innerText)) return clean(next.innerText);
        }
    }
    return "N/A";
}

function scrapePatientAndPlan() {
    const dobRaw = getLabelValue("Patient date of birth:");
    return {
        patient: {
            name: getLabelValue("Subscriber name:"),
            dob: dobRaw.replace(/Age:\s*\d+/i, "").trim() || "N/A",
            gender: getLabelValue("Gender:") || "N/A",
            relationship: getLabelValue("Relationship:") || "Subscriber",
        },
        plan_details: {
            subscriber_id: getLabelValue("Subscriber #:"),
            network: getLabelValue("Plan type:"),
            employer_group: getLabelValue("Group name:"),
            start_date: getLabelValue("Effective date:"),
            end_date: getLabelValue("Eligible through:") || "N/A",
            address: getLabelValue("Address:") || "N/A",
            claim_limit_days: getLabelValue("Claim submit time limit (days):"),
        },
    };
}

function scrapeFinancials() {
    const indivRaw = getLabelValuePartial("Individual annual maximum");
    const indivDeductRaw = getLabelValuePartial("Individual deductible");
    const orthoRaw = getLabelValuePartial("Orthodontic Lifetime Maximum");
    const orthoTotal = orthoRaw.match(/\$([\d,]+\.?\d*)/)?.[0] || "N/A";

    const annualTotal = indivRaw.match(/\$([\d,]+\.?\d*)\s*max/i) ? "$" + indivRaw.match(/\$([\d,]+\.?\d*)\s*max/i)[1] : "N/A";
    const annualUsed = indivRaw.match(/\$([\d,]+\.?\d*)\s*used/i) ? "$" + indivRaw.match(/\$([\d,]+\.?\d*)\s*used/i)[1] : "N/A";
    const annualRemaining = indivRaw.match(/\$([\d,]+\.?\d*)\s*remain/i) ? "$" + indivRaw.match(/\$([\d,]+\.?\d*)\s*remain/i)[1] : "N/A";

    const dedTotal = indivDeductRaw.match(/\$([\d,]+\.?\d*)\s*per year/i) ? "$" + indivDeductRaw.match(/\$([\d,]+\.?\d*)\s*per year/i)[1] : "N/A";
    const dedRemaining = indivDeductRaw.match(/\$([\d,]+\.?\d*)\s*remains/i) ? "$" + indivDeductRaw.match(/\$([\d,]+\.?\d*)\s*remains/i)[1] : "N/A";
    const dedUsed = dedTotal !== "N/A" && dedRemaining !== "N/A"
        ? `$${(parseFloat(dedTotal.replace(/[$,]/g, "")) - parseFloat(dedRemaining.replace(/[$,]/g, ""))).toFixed(2)} paid to date`
        : "N/A";

    return {
        annual_max: {
            total: annualTotal !== "N/A" ? `${annualTotal} total` : "N/A",
            used: annualUsed !== "N/A" ? `${annualUsed} used to date` : "N/A",
            remaining: annualRemaining !== "N/A" ? `${annualRemaining} remaining` : "N/A",
        },
        deductible_ind: {
            total: dedTotal !== "N/A" ? `${dedTotal} total` : "N/A",
            used: dedUsed,
            remaining: dedRemaining !== "N/A" ? `${dedRemaining} remaining` : "N/A",
        },
        ortho_lifetime: {
            total: orthoTotal,
            used: "N/A",
            remaining: "N/A",
        },
    };
}

function scrapeCoveredServices() {
    const services = [];
    document.querySelectorAll("table tr").forEach((row) => {
        const cells = row.querySelectorAll("td, th");
        if (cells.length >= 3) {
            services.push({
                category: clean(cells[0].innerText),
                in_network: clean(cells[1].innerText),
                out_of_network: clean(cells[2].innerText),
            });
        }
    });
    return services;
}

function scrapeWaitingPeriods() {
    return {
        preventive: getLabelValuePartial("Preventive Waiting Period"),
        basic: getLabelValuePartial("Basic Waiting Period"),
        major: getLabelValuePartial("Major Waiting Period"),
        orthodontics: getLabelValuePartial("Orthodontic Waiting Period"),
    };
}

function scrapeLimitations() {
    return {
        exams: getLabelValuePartial("Exam"),
        cleanings: getLabelValuePartial("Cleaning"),
        xrays: getLabelValuePartial("X-Ray"),
        crowns: getLabelValuePartial("Crown"),
    };
}

function scrapeOrthoDetails() {
    return {
        coverage: getLabelValuePartial("Orthodontic Coverage"),
        age_limit: getLabelValuePartial("Orthodontic Age Limit"),
        lifetime_maximum: getLabelValuePartial("Orthodontic Lifetime Maximum"),
    };
}

function scrapePlanProvisions() {
    return {
        missing_tooth_clause: getLabelValuePartial("Missing Tooth Clause"),
        replacement_rule: getLabelValuePartial("Replacement Rule"),
        coordination_of_benefits: getLabelValuePartial("Coordination of Benefits"),
        downgrades: getLabelValuePartial("Downgrade"),
        alternate_benefit_clause: getLabelValuePartial("Alternate Benefit"),
        claim_address: getLabelValuePartial("Claims Address"),
        customer_service_phone: getLabelValuePartial("Customer Service"),
    };
}

function scrapeResultBlock(code) {
    const resultContainer = document.querySelector("#procedureBenefitResults, .procedure-benefits, [data-testid='procedure-results']") || document.body;
    const allText = resultContainer.innerText || "";
    const tableRows = [];

    resultContainer.querySelectorAll("table tr, tbody tr").forEach((row) => {
        const cells = row.querySelectorAll("td, th");
        if (cells.length >= 2) {
            const label = clean(cells[0].innerText);
            const value = clean(cells[cells.length - 1].innerText);
            if (label && value && label !== value) tableRows.push({ label, value });
        }
    });

    const fromTable = (regex) => tableRows.find((row) => regex.test(row.label))?.value || "N/A";

    const benefit_level = allText.match(/(?:covered at|benefit[:\s]+|plan pays[:\s]+)\s*([\d]+%)/i)?.[1]
        || allText.match(/([\d]+%)\s*(?:covered|of[a-z ]+fee|of[a-z ]+allowable)/i)?.[1]
        || fromTable(/benefit|covered|plan pays/i);

    const patient_responsibility = allText.match(/[Pp]atient\s*[Rr]esponsibility[:\s]+([\d%$][^\n]+)/i)?.[1]?.trim()
        || fromTable(/patient.?resp/i);

    const network_fee = allText.match(/[Aa]llowable[:\s]+(\$[\d,]+\.?\d*)/i)?.[1]?.trim()
        || allText.match(/[Ff]ee[:\s]+(\$[\d,]+\.?\d*)/i)?.[1]?.trim()
        || fromTable(/fee|allowable/i);

    const deductibleRaw = allText.match(/[Dd]eductible[:\s]+([^\n]{2,40})/i)?.[1]?.trim() || fromTable(/deductible/i);
    const deductible = /yes|applies|true/i.test(deductibleRaw) ? "YES"
        : /no|does not|false|n\/a/i.test(deductibleRaw) ? "NO"
        : deductibleRaw || "N/A";

    const frequency_limit = allText.match(/[Ff]requency[:\s]+([^\n]{3,120})/i)?.[1]?.trim()
        || allText.match(/[Ll]imitation[:\s]+([^\n]{3,120})/i)?.[1]?.trim()
        || fromTable(/frequency|limitation|limit/i);

    const age_limit = allText.match(/[Aa]ge\s*(?:[Ll]imit|[Rr]estriction)[:\s]+([^\n]{2,40})/i)?.[1]?.trim()
        || allText.match(/(?:through age|up to age|under age)\s*([\d]+)/i)?.[1]?.trim()
        || fromTable(/age/i)
        || "N/A";

    const last_date_of_service = allText.match(/[Ll]ast\s*[Dd]ate[:\s]+([^\n]{2,40})/i)?.[1]?.trim()
        || allText.match(/[Ll]ast\s*[Ss]ervice[:\s]+([^\n]{2,40})/i)?.[1]?.trim()
        || allText.match(/[Dd]ate\s*[Oo]f\s*[Ss]ervice[:\s]+([^\n]{2,40})/i)?.[1]?.trim()
        || fromTable(/last.?date|date.?service/i);

    return {
        procedure_code: code,
        description: CODE_DESCRIPTIONS[code] || "N/A",
        benefit_level: benefit_level || "N/A",
        patient_responsibility: patient_responsibility || "N/A",
        network_fee: network_fee || "$0.00",
        deductible,
        frequency_limit: frequency_limit || "N/A",
        age_limit: age_limit || "N/A",
        last_date_of_service: last_date_of_service || "—",
    };
}

async function runProcedureCodeLookups(baseCodes = PROCEDURE_CODES, extraCodes = []) {
    const results = [];
    const errors = [];
    const allCodes = [...new Set([...baseCodes, ...extraCodes])];
    const codeInput = findCodeInput();
    const lookupBtn = findLookupButton();

    if (!codeInput) {
        const msg = "[DeltaDental] ERROR: Cannot find the procedure code input field.";
        console.error(msg);
        return { results, errors: [msg] };
    }
    if (!lookupBtn) {
        const msg = "[DeltaDental] ERROR: Cannot find the Lookup / Search button.";
        console.error(msg);
        return { results, errors: [msg] };
    }

    console.log(`[DeltaDental] Starting lookup for ${allCodes.length} codes...`);

    for (let i = 0; i < allCodes.length; i++) {
        const code = allCodes[i];
        console.log(`[DeltaDental] [${i + 1}/${allCodes.length}] Looking up ${code}...`);

        try {
            codeInput.focus();
            setReactInputValue(codeInput, "");
            await sleep(250);
            setReactInputValue(codeInput, code);
            await sleep(350);
            lookupBtn.click();

            const loaded = await waitForResult();
            if (!loaded) {
                throw new Error("Lookup timeout");
            }

            await sleep(800);
            const result = scrapeResultBlock(code);
            if (!results.some((item) => item.procedure_code === result.procedure_code)) {
                results.push(result);
            }
        } catch (err) {
            console.error(`[DeltaDental] ${code}`, err.stack || err.message);
            errors.push({ code, error: err.message, time: new Date().toISOString() });
            results.push({
                procedure_code: code,
                description: CODE_DESCRIPTIONS[code] || "N/A",
                benefit_level: "N/A",
                patient_responsibility: "N/A",
                network_fee: "$0.00",
                deductible: "N/A",
                frequency_limit: "N/A",
                age_limit: "N/A",
                last_date_of_service: "—",
                error: err.message,
            });
        }

        await sleep(600);
    }

    return { results, errors };
}

function buildPayload(procedureResults, errors, extraCodes = []) {
    const { patient, plan_details } = scrapePatientAndPlan();
    const financials = scrapeFinancials();
    const covered_services = scrapeCoveredServices();
    const waiting_periods = scrapeWaitingPeriods();
    const limitations = scrapeLimitations();
    const ortho_details = scrapeOrthoDetails();
    const provisions = scrapePlanProvisions();
    const timestamp = new Date().toISOString();
    const allCodes = [...PROCEDURE_CODES, ...extraCodes];

    return {
        benefit_coverage: {
            source: "Delta Dental Portal - Benefit & Coverage Details",
            timestamp,
            codes_searched: allCodes,
            extra_codes: extraCodes,
            procedure_count: allCodes.length,
            procedures: procedureResults,
            ...(errors.length ? { errors } : {}),
        },
        delta_dental_data: {
            source: "Delta Dental Portal - Plan Overview",
            timestamp,
            patient,
            plan_details,
            financials,
            covered_services,
            waiting_periods,
            limitations,
            ortho_details,
            missing_tooth_clause: provisions.missing_tooth_clause,
            replacement_rule: provisions.replacement_rule,
            coordination_of_benefits: provisions.coordination_of_benefits,
            downgrades: provisions.downgrades,
            alternate_benefit_clause: provisions.alternate_benefit_clause,
            claim_address: provisions.claim_address,
            customer_service_phone: provisions.customer_service_phone,
        },
    };
}

function downloadJSON(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "delta_dental_audit.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

function savePayload(payload) {
    chrome.storage.local.set({
        patient: payload.delta_dental_data.patient,
        procedures: payload.benefit_coverage.procedures,
        delta_dental_audit: payload,
    }, () => {
        if (chrome.runtime.lastError) {
            console.error("Storage error:", chrome.runtime.lastError.message);
            return;
        }
        const safeName = (payload.delta_dental_data.patient.name || "patient")
            .replace(/[^a-z0-9]/gi, "_")
            .toLowerCase();
        downloadJSON(payload, `${safeName}_delta_dental_audit.json`);
    });
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.command === "START_CRAWL") {
        (async () => {
            try {
                console.log("[DeltaDental] Starting full crawl");
                const extraCodes = (request.extraCodes || "")
                    .split(",")
                    .map((code) => code.trim().toUpperCase())
                    .filter(Boolean);

                const { results, errors } = await runProcedureCodeLookups(PROCEDURE_CODES, extraCodes);
                const payload = buildPayload(results, errors, extraCodes);
                savePayload(payload);
                sendResponse({
                    status: `[+] Done. Patient: ${payload.delta_dental_data.patient.name}. Procedures: ${results.length} scraped. JSON downloaded.`,
                });
            } catch (err) {
                console.error("[DeltaDental] Fatal error:", err);
                sendResponse({ status: `[!] Fatal error: ${err.message}` });
            }
        })();
        return true;
    }

    if (request.command === "LOOKUP_PROCEDURES") {
        (async () => {
            try {
                const extraCodes = (request.extraCodes || "")
                    .split(",")
                    .map((code) => code.trim().toUpperCase())
                    .filter(Boolean);
                const { results, errors } = await runProcedureCodeLookups(PROCEDURE_CODES, extraCodes);
                const payload = buildPayload(results, errors, extraCodes);
                savePayload(payload);
                sendResponse({ status: `[+] ${results.length} procedures scraped. JSON downloaded.` });
            } catch (err) {
                sendResponse({ status: `[!] Error: ${err.message}` });
            }
        })();
        return true;
    }

    if (request.command === "SCRAPE_PATIENT") {
        try {
            const { patient, plan_details } = scrapePatientAndPlan();
            const financials = scrapeFinancials();
            const covered_services = scrapeCoveredServices();
            const payload = {
                benefit_coverage: null,
                delta_dental_data: {
                    source: "Delta Dental Portal - Plan Overview",
                    timestamp: new Date().toISOString(),
                    patient,
                    plan_details,
                    financials,
                    covered_services,
                    provisions: [],
                },
            };
            savePayload(payload);
            sendResponse({ status: `[+] Patient saved: ${patient.name} | Network: ${plan_details.network}` });
        } catch (err) {
            sendResponse({ status: `[!] Error: ${err.message}` });
        }
        return true;
    }

    return true;
});