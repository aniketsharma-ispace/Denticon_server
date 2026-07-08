// content_ddri.js - DDRI Provider Portal Auditor

const PROCEDURE_CODES = [
    "D0120", "D0180", "D0140", "D0150", "D0274", "D0210", "D0330",
    "D0220", "D0364", "D0431", "D1110", "D1120", "D1206", "D1351",
    "D1510", "D2391", "D2740", "D2950", "D2962", "D6750", "D5110",
    "D9110", "D9222", "D9230", "D9243", "D9310", "D9944", "D4341",
    "D4355", "D4346", "D4910", "D4381", "D4260", "D4249", "D3310",
    "D3330", "D7140", "D7210", "D7240", "D7953", "D6010", "D6056"
];

const sleep = ms => new Promise(r => setTimeout(r, ms));
const clean = str => (str || "").replace(/[\n\r\t]/g, " ").replace(/\s+/g, " ").trim();

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

function scrapePatient() {
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

function scrapePlanDetails() {
    const dates = getEligibilityRow(getLabelValue('.SubscriberProfile', 'Subscriber Name'))?.dates || "N/A";
    let start = "N/A", end = "N/A";
    if (dates.includes('-')) {
        [start, end] = dates.split('-').map(clean);
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

function scrapeFinancials() {
    const financials = {
        maximums: [],
        deductibles: [],
        annual_max: { total: "N/A", used: "N/A", remaining: "N/A" },
        deductible_ind: { total: "N/A", used: "N/A", remaining: "N/A" },
        deductible_fam: { total: "N/A", used: "N/A", remaining: "N/A" },
        ortho_lifetime: { total: "N/A", used: "N/A", remaining: "N/A" },
        ortho_deductible: { total: "None", used: "None", remaining: "None" }
    };

    // 1. Parse the Maximums Table (has used/remaining)
    const maxRows = document.querySelectorAll('tr.DataTableRow, tr.DataTableOddRow');
    for (const row of maxRows) {
        const catCell = row.querySelector('.MaximumsFreqCategory');
        // Only include rows with .MaximumsAmount
        if (catCell && row.querySelector('.MaximumsAmount')) {
            const category = clean(catCell.textContent);
            const total = clean(row.querySelector('.MaximumsAmount')?.textContent);
            const used = clean(row.querySelector('.MaximumsAmountUsed')?.textContent);
            const remaining = clean(row.querySelector('.MaximumsAmountAvailable')?.textContent);
            
            if (category) {
                const entry = { category, total: total || "N/A", used: used || "N/A", remaining: remaining || "N/A" };
                
                const catLower = category.toLowerCase();
                if (catLower.includes('annual max')) financials.annual_max = entry;
                else if (catLower.includes('individual deductible')) financials.deductible_ind = entry;
                else if (catLower.includes('family deductible')) financials.deductible_fam = entry;
                else if (catLower.includes('orthodontic lifetime')) financials.ortho_lifetime = entry;
                else financials.maximums.push(entry);
            }
        }
    }

    // 2. Parse the Deductibles OONTbl table (basic amounts)
    const oonTables = document.querySelectorAll('.OONTbl table');
    for (const table of oonTables) {
        const rows = table.querySelectorAll('tr');
        for (const row of rows) {
            const cells = row.querySelectorAll('td');
            if (cells.length >= 2) {
                const category = clean(cells[0].textContent).replace(/:$/, '');
                const amount = clean(cells[1].textContent);
                if (category && amount) {
                    // Fallbacks for top-level keys
                    const catLower = category.toLowerCase();
                    if (catLower.includes('individual deductible')) {
                        if (financials.deductible_ind.total === "N/A") {
                            financials.deductible_ind = { category, total: amount, used: "N/A", remaining: "N/A" };
                        }
                    } else if (catLower.includes('family deductible')) {
                        if (financials.deductible_fam.total === "N/A") {
                            financials.deductible_fam = { category, total: amount, used: "N/A", remaining: "N/A" };
                        }
                    } else {
                        financials.deductibles.push({ category, amount });
                    }
                }
            }
        }
    }

    return financials;
}

function scrapeFrequencies() {
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

function scrapeProvisions() {
    const provisions = [];
    const benefitDiv = document.getElementById('benefits');
    if (!benefitDiv) return provisions;

    const blocks = Array.from(benefitDiv.querySelectorAll('p, div.redBackgroundTextAlignedLeft, .Disclaimer'));
    for (const block of blocks) {
        const text = clean(block.textContent);
        if (text.includes("missing tooth clause")) {
            provisions.push({ rule: "Missing Tooth Clause", value: text });
        } else if (text.includes("Dependent children are covered")) {
            provisions.push({ rule: "Dependent Age Limit", value: text });
        } else if (block.classList.contains('Disclaimer')) {
            provisions.push({ rule: "Disclaimer", value: text });
        }
    }
    return provisions;
}

function scrapeBenefitCategories() {
    const categories = [];
    const benefitDiv = document.getElementById('benefits');
    if (!benefitDiv) return categories;

    const table = benefitDiv.querySelector('table');
    if (!table) return categories;

    let currentCat = null;
    const rows = Array.from(table.querySelectorAll('tr'));
    
    for (const row of rows) {
        if (row.classList.contains('TRhBEN')) {
            currentCat = {
                category: clean(row.textContent),
                services: []
            };
            categories.push(currentCat);
        } else if (row.classList.contains('DataTableRow') || row.classList.contains('DataTableOddRow')) {
            if (!currentCat) continue;
            const cells = row.querySelectorAll('td');
            if (cells.length >= 5) {
                currentCat.services.push({
                    name: clean(cells[1].textContent),
                    coverage: clean(cells[2].textContent).replace('Deductible Applies', '').trim(),
                    deductible_applies: cells[2].innerHTML.includes('ICON_DeductibleSM.png') ? "Yes" : "No",
                    age_limit: clean(cells[3].textContent),
                    frequency: clean(cells[4].textContent)
                });
            }
        }
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
    let procData = null;
    // Helper: DOMParser docs don't support innerText, must use textContent
    const txt = el => (el?.textContent || '').replace(/[\n\r\t]/g, ' ').replace(/\s+/g, ' ').trim();
    
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
        const html = await response.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const table = doc.getElementById('ProcedureCodeSearchResult');
        
        if (table) {
            const rows = table.querySelectorAll('tr');
            if (rows.length >= 2) {
                const cells = rows[1].querySelectorAll('td');
                if (cells.length >= 6) {
                    procData = {
                        procedure_code: code,
                        description: txt(cells[1]),
                        coverage_percentage: txt(cells[2]),
                        deductible_applies: txt(cells[3]),
                        waiting_period: txt(cells[4]),
                        alternate_benefit: txt(cells[5]),
                        frequency: "N/A",
                        age_limit: "N/A",
                        history: []
                    };
                }
            }
        }
    } catch (e) {
        console.error(`Error fetching coverage for ${code}:`, e);
    }

    if (!procData) return null;

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
                            tooth_number: txt(cells[3]),
                            tooth_surface: txt(cells[4]),
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

function showProgressOverlay(text) {
    let overlay = document.getElementById('ddri-audit-progress');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'ddri-audit-progress';
        overlay.style.cssText = `
            position: fixed; top: 20px; right: 20px; z-index: 999999;
            background: rgba(0,0,0,0.85); color: white; padding: 15px 25px;
            border-radius: 8px; font-family: sans-serif; font-size: 16px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.5); min-width: 280px; text-align: center;
            font-weight: bold;
        `;
        document.body.appendChild(overlay);
    }
    overlay.textContent = text;
}

function hideProgressOverlay() {
    const overlay = document.getElementById('ddri-audit-progress');
    if (overlay) overlay.remove();
}

async function crawlProcedures() {
    const params = getHiddenParams();
    const results = [];
    
    if (!params.memberId) {
        console.warn("No MemberId found. Cannot crawl procedures.");
        return results;
    }

    const BATCH_SIZE = 10;
    const codes = PROCEDURE_CODES;
    
    const benefitCats = scrapeBenefitCategories();
    const findLimits = (keywords) => {
        for (const cat of benefitCats) {
            for (const svc of cat.services) {
                const s = svc.name.toLowerCase();
                if (keywords.some(kw => s.includes(kw))) {
                    return { freq: svc.frequency, age: svc.age_limit };
                }
            }
        }
        return { freq: "N/A", age: "N/A" };
    };

    for (let i = 0; i < codes.length; i += BATCH_SIZE) {
        const batch = codes.slice(i, i + BATCH_SIZE);
        const batchNum = Math.floor(i / BATCH_SIZE) + 1;
        const totalBatches = Math.ceil(codes.length / BATCH_SIZE);
        const progressText = `[Audit] Fetching procedures batch ${batchNum} of ${totalBatches}...`;
        console.log(progressText);
        showProgressOverlay(`Auditing Procedures: ${Math.round((i/codes.length)*100)}%\nFetching batch ${batchNum} of ${totalBatches}...`);
        
        const batchPromises = batch.map(async (code) => {
            const data = await fetchProcedure(code, params);
            if (data) {
                let limits = { freq: "N/A", age: "N/A" };
                if (code === "D0120" || code === "D0150" || code === "D0180") limits = findLimits(['oral exam']);
                else if (code === "D1110" || code === "D1120" || code === "D4910") limits = findLimits(['cleaning', 'periodontal maintenance']);
                else if (code === "D1206") limits = findLimits(['fluoride']);
                else if (code === "D1351") limits = findLimits(['sealant']);
                else if (code === "D1510") limits = findLimits(['space maintainer']);
                else if (code === "D2391" || code === "D2140") limits = findLimits(['amalgam', 'composite']);
                else if (code === "D2740") limits = findLimits(['crowns over natural teeth']);
                else if (code === "D8080" || code.startsWith("D8")) limits = findLimits(['orthodontic', 'braces']);
                
                data.frequency = limits.freq;
                data.age_limit = limits.age;
            }
            return data;
        });

        const batchResults = await Promise.all(batchPromises);
        batchResults.forEach(r => { if (r) results.push(r); });
        
        if (i + BATCH_SIZE < codes.length) {
            await sleep(150);
        }
    }
    
    return results;
}

function buildPayload() {
    return {
        carrier: "DDRI",
        patient: scrapePatient(),
        plan_details: scrapePlanDetails(),
        financials: scrapeFinancials(),
        plan_provisions: scrapeProvisions(),
        frequency_status: scrapeFrequencies(),
        benefit_categories: scrapeBenefitCategories()
    };
}

setInterval(() => {
    if (!chrome.runtime?.id) return;
    if (!document.querySelector('.SubscriberProfile')) return;

    const data = buildPayload();
    chrome.storage.local.get("audit_context", (res) => {
        const ctx = res.audit_context || {};
        const merged = { ...ctx, ...data, ddri_data: true }; 
        chrome.storage.local.set({ audit_context: merged });
    });
}, 5000);

function downloadAuditJSON() {
    chrome.storage.local.get("audit_context", (res) => {
        const data = res.audit_context || {};
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
    });
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.command === "START_CRAWL") {
        if (!document.querySelector('.SubscriberProfile')) {
            sendResponse({ status: "Please navigate to the ViewPatientBenefits page first." });
            return true;
        }

        (async () => {
            const data = buildPayload();
            const procedures = await crawlProcedures();
            
            const audit_payload = {
                ...data,
                ddri_data: true,
                benefit_coverage: { procedures: procedures }
            };

            chrome.storage.local.get("audit_context", (res) => {
                let ctx = res.audit_context || {};
                ctx = { ...ctx, ...audit_payload };
                chrome.storage.local.set({ audit_context: ctx }, () => {
                    downloadAuditJSON();
                    showProgressOverlay("Crawl Complete! JSON Downloaded.");
                    setTimeout(hideProgressOverlay, 4000);
                    sendResponse({ status: "[+] DDRI JSON downloaded." });
                });
            });
        })();
        return true;
    }
});
