// content_dentaquest.js — DentaQuest / Sun Life provider portal scraper
//
// Reads the live "Member Details" page on providers.dentaquest.com and builds
// the same audit JSON shape the other portal scrapers (Cigna / MetLife) produce,
// then stores it in chrome.storage.local under audit_context.dentaquest_data.
//
// NOTE: DentaQuest member PDFs are saved as image/vector outlines with no text
// layer, so they cannot be parsed server-side. Scraping the live DOM (which has
// real text) is the reliable path — same approach as the other portals.

const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// ══════════════════════════════════════════════════════════════════════════
// LABEL LOOKUP  (DOM text-node first, then innerText regex fallback)
// ══════════════════════════════════════════════════════════════════════════

function getLabelValue(label) {
    const want = label.toLowerCase().replace(/:$/, '').trim();

    // 1. DOM: find a text node whose text equals the label (with/without colon)
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        const raw = node.textContent.trim();
        const t = raw.toLowerCase().replace(/:$/, '').trim();
        if (t !== want) {
            // Value packed in the same node: "Label: value"
            const inline = raw.match(new RegExp("^" + escapeRe(label) + "\\s*:\\s*(.+)$", "i"));
            if (inline && clean(inline[1])) return clean(inline[1]);
            continue;
        }
        const el = node.parentElement;
        const sib = el?.nextElementSibling;
        if (sib && clean(sib.innerText)) return clean(sib.innerText);
        const pSib = el?.parentElement?.nextElementSibling;
        if (pSib && clean(pSib.innerText)) return clean(pSib.innerText);
    }

    // 2. innerText regex fallback (label then value on same or next line)
    const txt = document.body.innerText || "";
    const m = txt.match(new RegExp(escapeRe(label) + "\\s*:?\\s*\\n?\\s*([^\\n]+)", "i"));
    return m ? clean(m[1]) : "N/A";
}

function escapeRe(s) {
    return s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
}

// ══════════════════════════════════════════════════════════════════════════
// PATIENT INFO
// ══════════════════════════════════════════════════════════════════════════

function scrapePatientInfo() {
    const txt = document.body.innerText || "";

    let name = txt.match(/Member information for\s+([A-Z][A-Za-z .'\-]+)/)?.[1]?.trim();
    if (!name) {
        const lbl = getLabelValue("Name");
        name = lbl !== "N/A" ? lbl : "N/A";
    }

    const level = getLabelValue("Level of coverage");
    // The member IS the patient on these plans (esp. children's Medicaid) → Self.
    const relationship = level !== "N/A" && !/employee only|self|subscriber|member/i.test(level)
        ? level
        : "Self";

    return {
        name:               clean(name),
        dob:                txt.match(/Date of birth\s*:?\s*(\d{1,2}\/\d{1,2}\/\d{4})/i)?.[1] || getLabelValue("Date of birth"),
        age:                getLabelValue("Age"),
        member_id:          txt.match(/ID number\s*:?\s*([A-Za-z0-9]+)/i)?.[1] || getLabelValue("ID number"),
        relationship,
        level_of_coverage:  level
    };
}

// ══════════════════════════════════════════════════════════════════════════
// PLAN DETAILS
// ══════════════════════════════════════════════════════════════════════════

function scrapePlanDetails() {
    const txt = document.body.innerText || "";

    const group_number =
        txt.match(/Plan\/Group number\s*:?\s*([A-Za-z0-9\-]+)/i)?.[1] ||
        getLabelValue("Plan/Group number");

    // Plan name: prefer a value containing a known plan keyword, else the labelled value.
    let plan =
        txt.match(/\bPlan\s*:?\s*\n?\s*([A-Z][^\n]*?(?:Medicaid|Medicare|PPO|HMO|DHMO|EPO|Plan)[^\n]*)/)?.[1] || "";
    if (!plan) {
        const lbl = getLabelValue("Plan");
        plan = (lbl !== "N/A" && !/group number/i.test(lbl)) ? lbl : "";
    }

    return {
        plan_name:         clean(plan) || "N/A",
        group_number:      clean(group_number) || "N/A",
        // matcher reads employer_group OR group_name — provide both via summary + here
        employer_group:    clean(plan) || "N/A",
        network:           getLabelValue("Network"),
        level_of_coverage: getLabelValue("Level of coverage")
    };
}

// ══════════════════════════════════════════════════════════════════════════
// BENEFITS TABLE  ("Common Codes": Procedure | Coinsurance | Waiting period | Frequency | Deductible)
// ══════════════════════════════════════════════════════════════════════════

function scrapeBenefitsTable() {
    const procedures = [];
    const seen = new Set();
    let currentCategory = "";

    const pushRow = (code, coins, waiting, freq, ded, category) => {
        code = (code || "").toUpperCase();
        if (!/^D\d{4}$/.test(code) || seen.has(code)) return;
        seen.add(code);

        // Coinsurance shows "IN: 100% / OON: 100%" — take the in-network %.
        const inPct = coins.match(/IN:?\s*(\d+)\s*%/i)?.[1] || coins.match(/(\d+)\s*%/)?.[1];
        // DentaQuest frequency text rarely carries an age cap, but capture it if present.
        const ageM  = freq.match(/(?:to|up to|under)\s*age\s*(\d+)/i);

        procedures.push({
            procedure_code:  code,
            benefit_level:   inPct ? `${inPct}%` : "N/A",
            age_limit:       ageM ? `0-${ageM[1]}` : "N/A",
            frequency_limit: clean(freq) || "N/A",
            waiting_period:  clean(waiting) || "N/A",
            deductible:      clean(ded) || "N/A",
            category:        category || "N/A"
        });
    };

    // ── Primary: parse the HTML table whose header has Coinsurance + Frequency ──
    let table = null;
    for (const t of document.querySelectorAll("table")) {
        const head = (t.querySelector("thead")?.innerText || t.rows?.[0]?.innerText || "").toLowerCase();
        if (head.includes("coinsurance") && head.includes("frequency")) { table = t; break; }
    }

    if (table) {
        for (const row of table.querySelectorAll("tr")) {
            const cells = Array.from(row.querySelectorAll("td"));
            if (!cells.length) continue;

            const firstTxt = clean(cells[0].innerText);
            const codeMatch = firstTxt.match(/\b(D\d{4})\b/);

            // Category header rows (e.g. "Diagnostic", "Preventive") have no D-code.
            if (!codeMatch) {
                if (firstTxt && !/procedure/i.test(firstTxt) && firstTxt.length < 40) {
                    currentCategory = firstTxt;
                }
                continue;
            }

            // Columns: Procedure | Coinsurance | Waiting period | Frequency | Deductible
            // (the "Procedure" + "Coinsurance" headers render fused, so be lenient).
            const coins   = clean(cells[1]?.innerText);
            const waiting = clean(cells[2]?.innerText);
            const freq    = clean(cells[3]?.innerText);
            const ded     = clean(cells[cells.length - 1]?.innerText);
            pushRow(codeMatch[1], coins, waiting, freq, ded, currentCategory);
        }
    }

    // ── Fallback: regex over innerText (robust if it's not a real <table>) ──
    if (!procedures.length) {
        const txt = document.body.innerText || "";
        const re = /\b(D\d{4})\b[\s\S]{0,40}?IN:?\s*(\d+)\s*%/gi;
        let m;
        while ((m = re.exec(txt))) pushRow(m[1], `IN: ${m[2]}%`, "", "", "", "");
    }

    return procedures;
}

// ══════════════════════════════════════════════════════════════════════════
// BUILD PAYLOAD
// ══════════════════════════════════════════════════════════════════════════

function buildDentaQuestPayload() {
    const plan       = scrapePlanDetails();
    const patient    = scrapePatientInfo();
    const procedures = scrapeBenefitsTable();

    return {
        source:    "DentaQuest Portal - Member Details",
        timestamp: new Date().toISOString(),
        summary: {
            group_name:   plan.plan_name,
            group_number: plan.group_number,
            plan_name:    plan.plan_name,
            insurer:      "dentaquest"
        },
        plan_details: plan,
        patient,
        // DentaQuest Medicaid plans typically have no annual max / deductible.
        financials: {
            annual_max:     { total: "N/A" },
            deductible_ind: { total: "N/A" },
            deductible_fam: { total: "N/A" },
            ortho_lifetime: { total: "N/A" }
        },
        covered_services: [],
        // Self-contained so a single unwrap (dentaquest_data) gives the matcher
        // everything it needs.
        benefit_coverage: {
            source:          "DentaQuest Portal - Benefits Summary",
            procedure_count: procedures.length,
            procedures
        }
    };
}

// ══════════════════════════════════════════════════════════════════════════
// CRAWL + STORE
// ══════════════════════════════════════════════════════════════════════════

function isMemberDetailsPage() {
    const txt = document.body?.innerText || "";
    return /Member information for/i.test(txt) || /Benefits summary/i.test(txt);
}

async function runDentaQuestCrawl() {
    if (!chrome.runtime?.id) return { status: "[!] Extension context lost — refresh the page." };

    const data = buildDentaQuestPayload();

    if (data.summary.group_number === "N/A" && data.benefit_coverage.procedures.length === 0) {
        console.warn("[DentaQuest] No member data found on this page.");
        return { status: "[!] No DentaQuest data found. Open a Member Details page and retry." };
    }

    return new Promise((resolve) => {
        chrome.storage.local.get("audit_context", (res) => {
            const ctx = res.audit_context || {};
            ctx.dentaquest_data = data;
            // Also expose benefit_coverage at the top level for parity with other flows.
            ctx.benefit_coverage = data.benefit_coverage;
            chrome.storage.local.set({ audit_context: ctx }, () => {
                console.log(`[DentaQuest] Saved: group=${data.summary.group_number}, ` +
                            `${data.benefit_coverage.procedures.length} procedures.`);
                resolve({ status: `[+] DentaQuest saved (${data.benefit_coverage.procedures.length} procedures).` });
            });
        });
    });
}

// Auto-run once the page is stable.
setTimeout(() => { if (isMemberDetailsPage()) runDentaQuestCrawl(); }, 4000);

// Passive background re-sync while on a member page.
setInterval(() => {
    if (chrome.runtime?.id && isMemberDetailsPage()) runDentaQuestCrawl();
}, 8000);

// Manual trigger from the popup.
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.command === "START_CRAWL") {
        runDentaQuestCrawl().then(r => sendResponse(r || { status: "DentaQuest scrape done." }));
        return true; // keep the message channel open for the async response
    }
});

console.log("DentaQuest scraper initialized.");
