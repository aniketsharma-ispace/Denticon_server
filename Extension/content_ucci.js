console.log("UCCI CONTENT SCRIPT INJECTED");

const clean = (s) => (s || "").trim().replace(/\s+/g, " ");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Some sections of this page (confirmed: Deductibles and Maximums,
// Coordination and Other Benefits) appear to populate slightly later than
// the rest of the DOM — a live scrape immediately on page-open sometimes
// caught them still empty, even though the 27 procedure-category tables
// were reliably present from the very first render. Rather than trust a
// fixed delay, poll until the target table actually has rows (or give up
// after maxWaitMs and return whatever's there, so a genuinely-empty
// section still resolves quickly instead of stalling the whole scrape).
async function waitForRows(selector, { maxWaitMs = 4000, pollMs = 200 } = {}) {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    const table = document.querySelector(selector);
    const rowCount = table?.querySelectorAll("tbody tr").length || 0;
    if (rowCount > 0) return table;
    await sleep(pollMs);
  }
  return document.querySelector(selector);
}

// ══════════════════════════════════════════════════════════════════════════
// SECTION 1: PATIENT INFO
// ══════════════════════════════════════════════════════════════════════════

function scrapePatientInfo() {
  const info = {};

  const nameEl = document.querySelector("#memberName");
  info.patient_name = clean(nameEl?.textContent || "");

  // Label/value table rows: <td class="text-muted text-end">Label</td><td>Value</td>
  // Resilient to this JSF app's id churn — walked by row structure, not id.
  document.querySelectorAll(".member-information table tbody tr").forEach((tr) => {
    const cells = tr.querySelectorAll("td");
    if (cells.length < 2) return;
    const label = clean(cells[0].textContent).replace(/:$/, "");
    const value = clean(cells[1].textContent);
    if (!label) return;

    const key = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
    if (key) info[key] = value;
  });

  // Coverage Effective / medical-condition flag / ACTIVE status sit outside the
  // label/value table on this page, so pull them via text patterns instead.
  const bodyText = document.body.innerText;

  const activeMatch = bodyText.match(/\b(ACTIVE|INACTIVE|TERMINATED)\b/);
  if (activeMatch) info.status = activeMatch[1];

  const coverageMatch = bodyText.match(/Coverage Effective\s*\n?\s*([^\n|]+)/i);
  if (coverageMatch) info.coverage_effective = clean(coverageMatch[1]);

  const conditionMatch = bodyText.match(/Member has a reported medical condition\?\s*\n?\s*(Yes|No)/i);
  if (conditionMatch) info.has_reported_medical_condition = conditionMatch[1];

  // Top search-result panel: Group/ID, Policyholder, network info
  const groupMatch = bodyText.match(/Group\s*\/\s*ID\s*\n?\s*([^\n]+)/i);
  if (groupMatch) info.group_id = clean(groupMatch[1]);

  const policyholderMatch = bodyText.match(/Policyholder\s*\n?\s*([^\n]+)/i);
  if (policyholderMatch) info.policyholder = clean(policyholderMatch[1]);

  const yourNetworkMatch = bodyText.match(/Your Network[^\n]*\n?\s*([^\n]+)/i);
  if (yourNetworkMatch) info.your_network = clean(yourNetworkMatch[1]);

  const groupNetworkMatch = bodyText.match(/Group Network[^\n]*\n?\s*([^\n]+)/i);
  if (groupNetworkMatch) info.group_network = clean(groupNetworkMatch[1]);

  return info;
}

// ══════════════════════════════════════════════════════════════════════════
// SECTION 2: SERVICE HISTORY SNAPSHOT
// Plain <table id="serviceHistoryPanelList">, all rows already in the DOM
// on page load — no pagination needed (confirmed: scrolling triggers no
// network request, and every visible row is a real <tr>).
// ══════════════════════════════════════════════════════════════════════════

function scrapeServiceHistory() {
  const table = document.querySelector("#serviceHistoryPanelList");
  if (!table) return [];

  return [...table.querySelectorAll("tbody tr")].map((tr) => {
    const cells = [...tr.querySelectorAll("td")].map((td) => clean(td.textContent));
    return {
      start: cells[0] || "",
      end: cells[1] || "",
      procedure_code: cells[2] || "",
      tooth: cells[3] || "",
      surface: cells[4] || "",
    };
  });
}

// ══════════════════════════════════════════════════════════════════════════
// SECTION 3: BENEFIT CATEGORY TABLES (Preventive Exams, X-rays, etc.)
//
// All 26 category tables + the 1 Wellness Benefits table are ALREADY fully
// rendered in the DOM on page load (confirmed via fresh-page-load test —
// no clicking/accordion-expansion required), all sharing the same
// (invalid but present) id="benefitDetailAllServiceProceduresList".
//
// Each row is read by CSS class prefix (benefitServiceDetailProcedure-colN
// or the noDisplay placeholder cells used on "Not Covered" merged rows)
// rather than by cell position/colspan — this naturally normalizes both
// row shapes to the same 8 logical fields.
// ══════════════════════════════════════════════════════════════════════════

function parseProcedureRow(tr) {
  const cells = [...tr.querySelectorAll('td[class*="benefitServiceDetailProcedure-"]')];
  const get = (i) => clean(cells[i]?.textContent || "");

  return {
    procedure_code: get(0),
    procedure_name: get(1).replace(/\s*>\s*$/, "").trim(),
    covered: get(2),
    allowance: get(3),
    coverage_or_copay: get(4),
    limitation: get(5),
    applied_to_deductible: get(6),
    applied_to_maximum: get(7),
  };
}

function scrapeBenefitCategories() {
  const tables = [...document.querySelectorAll('table[id="benefitDetailAllServiceProceduresList"]')];

  // Category names, in DOM order, from the "Benefit Details by Procedure"
  // list. Two kinds of decoys share this same class and must be excluded:
  //   1. The hidden print-selection modal's duplicate copy of every label
  //      (caused false matches throughout this investigation).
  //   2. The three "Policy Information" accordion toggles (Deductibles and
  //      Maximums / Coordination and Other Benefits / Wellness Benefits)
  //      that sit just above the real category list and are handled by
  //      their own dedicated scrape functions — including them here shifted
  //      every subsequent category label by 3 positions.
  const NON_CATEGORY_TOGGLES = /^(Deductibles and Maximums|Coordination and Other Benefits|Wellness Benefits)/i;
  const categoryNames = [...document.querySelectorAll("td.benefit-service-details-col-1")]
    .filter((el) => !el.closest('[id*="print" i], [class*="print" i]'))
    .map((el) => clean(el.textContent))
    .filter((text) => !NON_CATEGORY_TOGGLES.test(text));

  const categories = [];
  let categoryIdx = 0;

  tables.forEach((table) => {
    const isWellness = !!table.querySelector(".wellness-alert-background, .alert-warning");
    const rows = [...table.querySelectorAll("tbody tr")].map(parseProcedureRow);

    if (isWellness) {
      categories.push({ category: "Wellness Benefits", procedures: rows });
      return;
    }

    const name = categoryNames[categoryIdx] || `Unknown Category ${categoryIdx + 1}`;
    categoryIdx++;
    categories.push({ category: name, procedures: rows });
  });

  return categories;
}

// ══════════════════════════════════════════════════════════════════════════
// SECTION 4: DEDUCTIBLES AND MAXIMUMS
// ══════════════════════════════════════════════════════════════════════════

async function scrapeDeductiblesAndMaximums() {
  const table = await waitForRows("#benefitPolicyInformationDeductiblesAndMaximums");
  if (!table) return [];

  return [...table.querySelectorAll("tbody tr")].map((tr) => {
    const cells = [...tr.querySelectorAll("td")].map((td) => clean(td.textContent));
    return { benefit: cells[0] || "", coverage: cells[1] || "" };
  });
}

// ══════════════════════════════════════════════════════════════════════════
// SECTION 5: COORDINATION AND OTHER BENEFITS
// (single-column table — plan-level rules/disclaimers)
// ══════════════════════════════════════════════════════════════════════════

async function scrapeCoordinationAndOtherBenefits() {
  const table = await waitForRows("#benefitPolicyCoordinationAndOtherBenefits");
  if (!table) return [];

  return [...table.querySelectorAll("tbody tr")].map((tr) => clean(tr.textContent));
}

// ══════════════════════════════════════════════════════════════════════════
// DOWNLOAD
// ══════════════════════════════════════════════════════════════════════════

function triggerUcciDownload(auditData) {
  const sanitize = (s) =>
    (s || "").trim().replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "").toLowerCase();

  const patientSlug = sanitize(auditData.patient_info?.patient_name) || "patient";
  const filename = `${patientSlug}_ucci.json`;

  const blob = new Blob([JSON.stringify(auditData, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.style.display = "none";
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

async function runUcciAudit() {
  console.log("=== UCCI SCRAPE STARTED ===");

  const auditData = {
    source: "UCCI",
    scraped_at: new Date().toISOString(),
  };

  console.log("Scraping patient info...");
  auditData.patient_info = scrapePatientInfo();

  console.log("Scraping Service History Snapshot...");
  auditData.service_history = scrapeServiceHistory();

  console.log("Scraping benefit category tables (already rendered, no clicks needed)...");
  auditData.benefit_categories = scrapeBenefitCategories();

  console.log("Scraping Deductibles and Maximums...");
  auditData.deductibles_and_maximums = await scrapeDeductiblesAndMaximums();

  console.log("Scraping Coordination and Other Benefits...");
  auditData.coordination_and_other_benefits = await scrapeCoordinationAndOtherBenefits();

  console.log("=== UCCI SCRAPE COMPLETE ===");
  console.log(auditData);

  chrome.storage.local.get("audit_context", (result) => {
    const context = result.audit_context || {};
    context.ucci_data = auditData;
    chrome.storage.local.set({ audit_context: context }, () => {
      console.log("✓ UCCI data stored");
      triggerUcciDownload(auditData);
    });
  });

  return auditData;
}

window.scrapeUcci = runUcciAudit;
console.log("UCCI scraper loaded. Run: scrapeUcci()");

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.command === "START_CRAWL") {
    runUcciAudit()
      .then(() => sendResponse({ success: true }))
      .catch((err) => {
        console.error(err);
        sendResponse({ success: false, error: err.message });
      });
    return true;
  }
});