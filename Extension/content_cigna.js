// content_cigna.js - V3.0 (Full Portal Auditor)

const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');
const getVal = (selector) => document.querySelector(`[data-test-id="${selector}"]`)?.innerText?.trim() || "N/A";

/**
 * Parses Cigna's amount blocks
 */
function parseCignaAmount(text) {
    if (!text) return { remaining: "N/A", total: "N/A" };
    const parts = text.split('\n').filter(p => p.includes('$'));
    return {
        remaining: clean(parts[0]) || "N/A",
        total: clean(parts[1]?.replace('Total:', '')) || clean(parts[0]) || "N/A"
    };
}

function scrapeCignaFull() {
    if (!window.location.href.includes('/den/coverage')) return null;

    const data = {
        source: "Cigna Portal",
        timestamp: new Date().toISOString(),
        // 1. TOP HEADER SUMMARY
        summary: {
            patient_id: getVal("lbl-eligibility-as-of-date") ? document.body.innerText.match(/Patient ID:\s*(.*)/)?.[1] : "N/A",
            group_number: document.body.innerText.match(/Group Number:\s*(\d+)/)?.[1] || "N/A",
            group_name: getVal("account-name") || "N/A",
            plan_type: getVal("plan-type") || "N/A",
            coverage_dates: {
                from: document.body.innerText.match(/Coverage From:\s*([\d\/]+)/)?.[1] || "N/A",
                to: document.body.innerText.match(/Coverage To:\s*(.*)/)?.[1] || "N/A"
            }
        },
        // 2. FINANCIALS (The Boxes)
        financials: {
            annual_max: parseCignaAmount(document.querySelector('.oop-box')?.innerText),
            deductible_ind: parseCignaAmount(document.querySelector('.deductible-box')?.innerText),
            ortho_lifetime: parseCignaAmount(document.querySelectorAll('.oop-box')[1]?.innerText)
        },
        // 3. COINSURANCE TABLE
        coinsurance: Array.from(document.querySelectorAll('[data-test-id^="table-row-"]')).map(row => ({
            category: row.querySelector('th')?.innerText?.replace('*', '').trim(),
            patient_pays: row.querySelector('td')?.innerText?.trim()
        })),
        // 4. FREQUENCY & LIMITATIONS
        frequencies: Array.from(document.querySelectorAll('cigna-freq-age-limit table:first-of-type tbody tr')).map(row => {
            const cells = row.querySelectorAll('td');
            return {
                procedure: clean(cells[1]?.innerText),
                limit: clean(cells[2]?.innerText)
            };
        }),
        // 5. AGE LIMITATIONS
        age_limits: Array.from(document.querySelectorAll('cigna-freq-age-limit table:last-of-type tbody tr')).map(row => {
            const cells = row.querySelectorAll('td');
            if (cells.length < 2) return null;
            return {
                type: clean(cells[0]?.innerText),
                age: clean(cells[1]?.innerText),
                ends: clean(cells[2]?.innerText)
            };
        }).filter(item => item !== null),
        // 6. NOTES & PROVISIONS
        notes: {
            missing_tooth: document.body.innerText.includes("Missing Tooth Limitation and Waiting Period does not apply") ? "Does not apply" : "Verify",
            ortho_note: getVal("lbl-age-limitations-note")
        }
    };

    return data;
}

async function runCignaCrawl() {
    if (!chrome.runtime?.id) return;

    // Check if the accordions are closed and open them if needed
    const chevrons = document.querySelectorAll('.collapsible__header[aria-expanded="false"]');
    if (chevrons.length > 0) {
        chevrons.forEach(c => c.click());
        await new Promise(r => setTimeout(r, 2000)); // Wait for data to render
    }

    const data = scrapeCignaFull();
    if (!data) return;

    chrome.storage.local.get("audit_context", (result) => {
        let context = result.audit_context || {};
        context.cigna_data = data;
        chrome.storage.local.set({ "audit_context": context });
        console.log("Cigna Full Data Exported.");
    });
}

// Auto-run when the page is stable
setTimeout(runCignaCrawl, 4000);

// Listener for manual popup trigger
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.command === "START_CRAWL") {
        runCignaCrawl();
        sendResponse({ status: "Cigna Comprehensive Scrape Started" });
    }
});