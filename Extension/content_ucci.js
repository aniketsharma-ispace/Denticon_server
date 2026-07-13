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

const SERVICE_HISTORY_SELECTORS = {
  form: "#serviceHistoryPanelOptionInput",
  procInput: '[id="serviceHistoryPanelOptionInput:serviceHistoryInputProc"]',
  toothInput: '[id="serviceHistoryPanelOptionInput:serviceHistoryInputTooth"]',
  filterButton: '[id="serviceHistoryPanelOptionInput:buttonServiceHistoryFilter"]',
  clearButton: '[id="serviceHistoryPanelOptionInput:j_id_gv"]',
  container: "#serviceHistoryPanelContainer",
  table: "#serviceHistoryPanelList",
  loader: '[id="serviceHistoryPanelOptionInput:ajaxLoaderImage"]',
};

const CDT_CODES = [
  "0120", "0180", "0140", "0150", "0274", "0210", "0330", "0220",
  "0364", "0431", "1110", "1120", "1206", "1351", "1510", "2391",
  "2740", "2950", "2962", "6750", "5110", "9110", "9222", "9230",
  "9243", "9310", "9944", "4341", "4355", "4346", "4910", "4381",
  "4260", "4249", "3310", "3330", "7140", "7210", "7240", "7953",
  "6010", "6056", "0272",
];

function parseServiceHistoryRows(root = document) {
  if (!root) return [];

  const table = root.matches?.(SERVICE_HISTORY_SELECTORS.table)
    ? root
    : root.querySelector?.(SERVICE_HISTORY_SELECTORS.table);
  if (!table) return [];

  return [...table.querySelectorAll("tbody tr")]
    .map((tr) => {
      const cells = [...tr.querySelectorAll("td")].map((td) => clean(td.textContent));
      return {
        start: cells[0] || "",
        end: cells[1] || "",
        procedure_code: cells[2] || "",
        tooth: cells[3] || "",
        surface: cells[4] || "",
      };
    })
    .filter((row) => row.start || row.end || row.procedure_code || row.tooth || row.surface);
}

function scrapeServiceHistorySnapshot() {
  return parseServiceHistoryRows(document);
}

function scrapeServiceHistory() {
  return scrapeServiceHistorySnapshot();
}

function normalizeProcedureCode(code) {
  const value = clean(code).toUpperCase();
  if (!value) return "";
  if (/^\d{4}$/.test(value)) return `D${value}`;
  if (/^D\d{4}$/.test(value)) return value;
  return "";
}

function getUniqueProcedureCodes(rows) {
  return [
    ...new Set(
      rows
        .map((row) => normalizeProcedureCode(row.procedure_code))
        .filter(Boolean)
    ),
  ];
}

function getTargetProcedureCodes() {
  return [...new Set(CDT_CODES.map(normalizeProcedureCode).filter(Boolean))];
}

function getServiceHistorySearchValue(code) {
  const normalized = normalizeProcedureCode(code);
  return normalized ? normalized.replace(/^D/, "") : "";
}

function parseUcciDate(dateString) {
  const match = clean(dateString).match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!match) return null;
  const month = Number(match[1]);
  const day = Number(match[2]);
  const year = Number(match[3]);
  const date = new Date(year, month - 1, day);
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }
  return date;
}

function sortDatesNewestFirst(dates) {
  return [...dates].sort((a, b) => {
    const dateA = parseUcciDate(a);
    const dateB = parseUcciDate(b);
    if (dateA && dateB) return dateB - dateA;
    if (dateA) return -1;
    if (dateB) return 1;
    return a.localeCompare(b);
  });
}

function getServiceHistorySignature(root = document) {
  return parseServiceHistoryRows(root)
    .map((row) => [row.start, row.end, row.procedure_code, row.tooth, row.surface].join("|"))
    .join("~");
}

function setNativeInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (setter) setter.call(input, value);
  else input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function pressEnterOnInput(input) {
  ["keydown", "keypress", "keyup"].forEach((type) => {
    input.dispatchEvent(
      new KeyboardEvent(type, {
        bubbles: true,
        cancelable: true,
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
      })
    );
  });
}

function isServiceHistoryLoading() {
  const loader = document.querySelector(SERVICE_HISTORY_SELECTORS.loader);
  return !!loader && getComputedStyle(loader).display !== "none";
}

async function waitForServiceHistoryUpdate(
  previousSignature,
  { maxWaitMs = 12000, pollMs = 150 } = {}
) {
  const start = Date.now();
  const originalContainer = document.querySelector(SERVICE_HISTORY_SELECTORS.container);
  let mutationCount = 0;
  let loaderWasVisible = isServiceHistoryLoading();
  const observerRoot = originalContainer?.parentElement || document.body;
  const observer = new MutationObserver(() => {
    mutationCount++;
  });

  observer.observe(observerRoot, { childList: true, subtree: true, characterData: true });

  try {
    while (Date.now() - start < maxWaitMs) {
      const container = document.querySelector(SERVICE_HISTORY_SELECTORS.container);
      const signature = getServiceHistorySignature(document);
      const replaced = !!originalContainer && !!container && container !== originalContainer;
      const changed = signature !== previousSignature;
      const loading = isServiceHistoryLoading();
      if (loading) loaderWasVisible = true;
      const settled = !loading;
      const loaderCompleted = loaderWasVisible && settled;
      const mutationSettledLongEnough = mutationCount > 0 && settled && Date.now() - start > 1000;

      if ((changed || replaced || loaderCompleted || mutationSettledLongEnough) && settled) {
        await sleep(150);
        return parseServiceHistoryRows(document);
      }

      await sleep(pollMs);
    }
  } finally {
    observer.disconnect();
  }

  throw new Error("Timed out waiting for service-history results");
}

function getLiveViewState() {
  return document.querySelector('input[name="javax.faces.ViewState"]')?.value || "";
}

function updateLiveViewState(newViewState) {
  if (!newViewState) return;
  document.querySelectorAll('input[name="javax.faces.ViewState"]').forEach((input) => {
    input.value = newViewState;
  });
}

function buildUrlEncodedBody(formData) {
  const params = new URLSearchParams();
  for (const [key, value] of formData.entries()) {
    params.append(key, value);
  }
  return params;
}

function parseServiceHistoryAjaxResponse(xmlText) {
  const xml = new DOMParser().parseFromString(xmlText, "text/xml");
  if (xml.querySelector("parsererror")) {
    throw new Error("Invalid JSF partial-response XML");
  }

  const updates = [...xml.querySelectorAll("update")];
  const viewStateUpdate = updates.find((node) =>
    (node.getAttribute("id") || "").includes("javax.faces.ViewState")
  );
  if (viewStateUpdate) updateLiveViewState(clean(viewStateUpdate.textContent));

  const update = updates.find(
    (node) => node.getAttribute("id") === "serviceHistoryPanelContainer"
  );
  if (!update) {
    throw new Error("serviceHistoryPanelContainer update missing");
  }

  const wrapper = document.createElement("div");
  wrapper.innerHTML = update.textContent || "";
  const table = wrapper.querySelector(SERVICE_HISTORY_SELECTORS.table);
  return parseServiceHistoryRows(table);
}

async function directFetchServiceHistoryCode(code) {
  const form = document.getElementById("serviceHistoryPanelOptionInput");
  const searchValue = getServiceHistorySearchValue(code);
  const viewState = getLiveViewState();
  if (!form || !searchValue || !viewState) {
    throw new Error("Service-history form, procedure code, or ViewState is missing");
  }

  const formData = new FormData(form);
  formData.set("serviceHistoryPanelOptionInput:serviceHistoryInputProc", searchValue);
  formData.set("serviceHistoryPanelOptionInput:serviceHistoryInputTooth", "");
  formData.set("serviceHistoryPanelOptionInput_SUBMIT", "1");
  formData.set("javax.faces.ViewState", viewState);
  formData.set("javax.faces.behavior.event", "action");
  formData.set("javax.faces.partial.event", "click");
  formData.set("javax.faces.source", "serviceHistoryPanelOptionInput:buttonServiceHistoryFilter");
  formData.set("javax.faces.partial.ajax", "true");
  formData.set("javax.faces.partial.execute", "@all");
  formData.set(
    "javax.faces.partial.render",
    "serviceHistoryPanelContainer serviceHistoryModalForm serviceHistoryPanelContainer"
  );
  formData.set("serviceHistoryPanelOptionInput", "serviceHistoryPanelOptionInput");

  const action = new URL(form.getAttribute("action") || location.href, location.href).href;

  const response = await fetch(action, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
      "Faces-Request": "partial/ajax",
    },
    credentials: "include",
    body: buildUrlEncodedBody(formData),
  });

  if (!response.ok) throw new Error(`Service-history fetch failed: HTTP ${response.status}`);

  return parseServiceHistoryAjaxResponse(await response.text());
}

async function liveButtonSearchServiceHistoryCode(code) {
  const normalized = normalizeProcedureCode(code);
  const searchValue = getServiceHistorySearchValue(normalized);
  if (!normalized || !searchValue) return [];

  const input = document.querySelector(SERVICE_HISTORY_SELECTORS.procInput);
  const toothInput = document.querySelector(SERVICE_HISTORY_SELECTORS.toothInput);
  const button = document.querySelector(SERVICE_HISTORY_SELECTORS.filterButton);
  const previousSignature = getServiceHistorySignature(document);

  if (input && button) {
    input.focus();
    if (toothInput) setNativeInputValue(toothInput, "");
    setNativeInputValue(input, searchValue);
    pressEnterOnInput(input);
    button.click();
    return waitForServiceHistoryUpdate(previousSignature);
  }

  throw new Error("Service-history input or filter button not found");
}

async function searchServiceHistoryCode(code) {
  return liveButtonSearchServiceHistoryCode(code);
}

function collectSortedUniqueDates(rows) {
  return sortDatesNewestFirst([...new Set(rows.map((row) => clean(row.start)).filter(Boolean))]);
}

function getRawFallbackDates(rawRows, code) {
  return collectSortedUniqueDates(
    rawRows.filter((row) => normalizeProcedureCode(row.procedure_code) === code)
  );
}

async function scrapeMappedServiceHistory(rawRows) {
  const uniqueCodes = getTargetProcedureCodes();
  console.log(`[UCCI] Captured ${rawRows.length} raw history rows`);
  console.log(`[UCCI] Target service-history codes: ${uniqueCodes.length}`);

  const mappedRows = [];
  let usedVisibleSearch = false;

  for (let i = 0; i < uniqueCodes.length; i++) {
    const code = uniqueCodes[i];
    const searchValue = getServiceHistorySearchValue(code);
    console.log(`[UCCI] Searching ${code} as ${searchValue} (${i + 1}/${uniqueCodes.length})`);

    try {
      const rows = await searchServiceHistoryCode(code);
      let dates = collectSortedUniqueDates(rows);
      if (!dates.length) {
        const fallbackDates = getRawFallbackDates(rawRows, code);
        if (fallbackDates.length) {
          console.warn(`[UCCI] ${code} AJAX response had no dates; using raw fallback dates`);
          dates = fallbackDates;
        }
      }

      console.log(`[UCCI] ${code} AJAX response returned ${rows.length} rows and ${dates.length} dates`);
      mappedRows.push({ procedure_code: code, dates });
    } catch (error) {
      console.warn(`[UCCI] Live Enter/button search failed for ${code}, retrying with direct AJAX:`, error);

      try {
        const rows = await directFetchServiceHistoryCode(code);
        const dates = collectSortedUniqueDates(rows);
        console.log(`[UCCI] ${code} direct AJAX retry returned ${rows.length} rows and ${dates.length} dates`);
        mappedRows.push({ procedure_code: code, dates });
      } catch (retryError) {
        const dates = getRawFallbackDates(rawRows, code);
        console.warn(`[UCCI] Both searches failed for ${code}; using raw fallback dates:`, retryError);
        mappedRows.push({ procedure_code: code, dates });
      }
    }
    usedVisibleSearch = true;
  }

  if (usedVisibleSearch) await clearServiceHistorySearch();
  return mappedRows;
}

async function clearServiceHistorySearch() {
  const input = document.querySelector(SERVICE_HISTORY_SELECTORS.procInput);
  const toothInput = document.querySelector(SERVICE_HISTORY_SELECTORS.toothInput);
  const clearButton = document.querySelector(SERVICE_HISTORY_SELECTORS.clearButton);
  if (!input || !clearButton) return;

  const previousSignature = getServiceHistorySignature(document);

  try {
    setNativeInputValue(input, "");
    if (toothInput) setNativeInputValue(toothInput, "");
    clearButton.click();
    await waitForServiceHistoryUpdate(previousSignature, { maxWaitMs: 12000 });
    console.log("[UCCI] Restored unfiltered service history");
  } catch (error) {
    console.warn("[UCCI] Could not restore unfiltered service history:", error);
  }
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

const FINANCIAL_MONEY_RE = /\$[\d,]+(?:\.\d{2})?/;
const FINANCIAL_PERIOD_RE = /(\d{2}\/\d{2}\/\d{4})\s*-\s*(\d{2}\/\d{2}\/\d{4})/;

function getVisibleFinancialText(element) {
  if (!element) return "";

  const clone = element.cloneNode(true);
  clone
    .querySelectorAll(
      'script, style, .modal, .modal-body, .modal-content, .popover, .visually-hidden, [hidden], [aria-hidden="true"]'
    )
    .forEach((node) => node.remove());

  return clean(clone.textContent || "");
}

function parseMoney(text) {
  return clean(text).match(FINANCIAL_MONEY_RE)?.[0] || "";
}

function parsePeriod(text) {
  const match = clean(text).match(FINANCIAL_PERIOD_RE);
  if (!match) return { period: "", period_start: "", period_end: "" };
  return {
    period: `${match[1]} - ${match[2]}`,
    period_start: match[1],
    period_end: match[2],
  };
}

function financialKeyFromLabel(label) {
  return clean(label)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function parseExtraFinancialFields(text) {
  const extra = {};
  const known = /^(applied|total|remaining|period|start|end|percentage)$/i;
  const fieldRe = /([A-Za-z][A-Za-z0-9 /_-]{1,40})\s*:\s*([^:]+?)(?=\s+[A-Za-z][A-Za-z0-9 /_-]{1,40}\s*:|$)/g;
  let match;

  while ((match = fieldRe.exec(text))) {
    const label = clean(match[1]);
    const value = clean(match[2]);
    const key = financialKeyFromLabel(label);
    if (!key || !value || known.test(label)) continue;
    extra[key] = value;
  }

  return extra;
}

function isFinancialModalContent(element) {
  return !!element?.closest(".modal, .modal-body, .modal-content, .popover");
}

function queryFinancialElement(root, selector) {
  return [...root.querySelectorAll(selector)].find((el) => !isFinancialModalContent(el)) || null;
}

function queryFinancialElements(root, selector) {
  return [...root.querySelectorAll(selector)].filter((el) => !isFinancialModalContent(el));
}

function isFinancialEntryBody(body) {
  const text = getVisibleFinancialText(body);
  return !!(
    queryFinancialElement(body, ".accum-heading, .accum-rem, .progress, .progress-bar") ||
    /\b(Applied|Remaining|Total)\b/i.test(text)
  );
}

function extractFinancialLabel(body, rawText) {
  const heading = queryFinancialElements(body, ".accum-heading.fw-bold, .accum-heading")
    .map((el) => getVisibleFinancialText(el))
    .find(Boolean);
  if (heading) return heading;

  const period = parsePeriod(rawText).period;
  const beforePeriod = period ? rawText.split(period)[0] : rawText.split(FINANCIAL_MONEY_RE)[0];
  return clean(beforePeriod.replace(/\b(Applied|Total|Remaining)\b/gi, ""));
}

function extractFinancialTotal(body, rawText, applied, remaining) {
  const elements = [...body.querySelectorAll("*")].filter(
    (el) => !el.closest(".modal, .progress, .accum-rem, .accum-rem-adv")
  );

  for (let i = 0; i < elements.length; i++) {
    if (!/\bTotal\b/i.test(getVisibleFinancialText(elements[i]))) continue;

    for (let j = i + 1; j < Math.min(elements.length, i + 6); j++) {
      const money = parseMoney(getVisibleFinancialText(elements[j]));
      if (money && money !== applied && money !== remaining) return money;
    }
  }

  const afterTotal = rawText.match(new RegExp(`\\bTotal\\b\\s*(${FINANCIAL_MONEY_RE.source})`, "i"));
  if (afterTotal) return afterTotal[1];

  const monies = [...rawText.matchAll(new RegExp(FINANCIAL_MONEY_RE.source, "g"))].map((match) => match[0]);
  return monies.find((money) => money !== applied && money !== remaining) || "";
}

function extractFinancialNote(body, entry) {
  const clone = body.cloneNode(true);
  clone
    .querySelectorAll(
      '.modal, .progress, .accum-rem, .accum-rem-adv, .visually-hidden, script, style, [hidden], [aria-hidden="true"]'
    )
    .forEach((node) => node.remove());

  let text = clean(clone.textContent || "");
  [
    entry.label,
    entry.period,
    entry.applied,
    entry.total,
    entry.remaining,
    entry.warning,
    "Applied",
    "Total",
    "Remaining",
  ].filter(Boolean).forEach((value) => {
    text = clean(text.replaceAll(value, " "));
  });

  return clean(text.replace(/^\*\s*/, "").replace(/\s*\*\s*/g, " "));
}

function parseFinancialEntry(body) {
  const rawText = getVisibleFinancialText(body);
  const periodInfo = parsePeriod(rawText);
  const applied = rawText.match(new RegExp(`(${FINANCIAL_MONEY_RE.source})\\s*Applied`, "i"))?.[1] || "";
  const remaining = parseMoney(queryFinancialElement(body, ".accum-rem")?.textContent || "") ||
    rawText.match(new RegExp(`(${FINANCIAL_MONEY_RE.source})\\s*\\*?\\s*Remaining`, "i"))?.[1] ||
    "";
  const progressValue = queryFinancialElement(body, ".progress-bar")?.getAttribute("aria-valuenow");
  const percentage = progressValue !== null && progressValue !== undefined && progressValue !== "" ? Number(progressValue) : null;
  const warning = getVisibleFinancialText(queryFinancialElement(body, ".accum-rem-adv"));

  const entry = {
    label: extractFinancialLabel(body, rawText),
    period: periodInfo.period,
    period_start: periodInfo.period_start,
    period_end: periodInfo.period_end,
    applied,
    total: "",
    remaining,
    percentage_used: Number.isFinite(percentage) ? percentage : null,
    note: "",
    warning,
    extra_fields: parseExtraFinancialFields(rawText),
    raw_text: rawText,
  };

  entry.total = extractFinancialTotal(body, rawText, entry.applied, entry.remaining);
  entry.note = extractFinancialNote(body, entry);

  return entry;
}

function parseFinancialCard(card) {
  const type = getVisibleFinancialText(
    card.querySelector(":scope > .card-header strong") ||
    card.querySelector(":scope > .card-header .card-title") ||
    card.querySelector(":scope > .card-header")
  );
  const rawText = getVisibleFinancialText(card);
  const bodies = [...card.querySelectorAll(":scope > .card-body")];
  const entries = bodies.filter(isFinancialEntryBody).map(parseFinancialEntry);
  const messageBodies = bodies
    .filter((body) => !isFinancialEntryBody(body))
    .map(getVisibleFinancialText)
    .filter(Boolean);
  const message = entries.length ? "" : clean(messageBodies.join(" "));

  return {
    type,
    status: entries.length ? "available" : message ? "message_only" : "empty",
    message,
    raw_text: rawText,
    entries,
  };
}

function scrapeFinancialAccumulators() {
  const results = [];
  const seen = new Set();
  const containers = [...document.querySelectorAll(".accums")];
  let cardCount = 0;

  console.log(`[UCCI] Financial accumulator containers found: ${containers.length}`);

  containers.forEach((accums) => {
    const cards = [...accums.querySelectorAll(":scope > .card")];
    cardCount += cards.length;

    cards.forEach((card) => {
      try {
        const parsed = parseFinancialCard(card);
        const signature = JSON.stringify(parsed);
        if (seen.has(signature)) return;
        seen.add(signature);
        results.push(parsed);

        if (parsed.status === "available") {
          console.log(`[UCCI] Parsed ${parsed.type || "unknown financial card"} with ${parsed.entries.length} entries`);
        } else if (parsed.status === "message_only") {
          console.log(`[UCCI] Parsed ${parsed.type || "unknown financial card"} as message-only`);
        }
      } catch (error) {
        console.warn("[UCCI] Failed to parse financial accumulator card:", error);
      }
    });
  });

  console.log(`[UCCI] Financial cards found: ${cardCount}`);
  return results;
}

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
  const rawServiceHistory = scrapeServiceHistorySnapshot();

  console.log("Scraping mapped Service History by procedure search...");
  auditData.service_history = await scrapeMappedServiceHistory(rawServiceHistory);

  console.log("Scraping benefit category tables (already rendered, no clicks needed)...");
  auditData.benefit_categories = scrapeBenefitCategories();

  console.log("Scraping Deductibles and Maximums...");
  auditData.deductibles_and_maximums = await scrapeDeductiblesAndMaximums();

  console.log("Scraping financial accumulators...");
  auditData.financial_accumulators = scrapeFinancialAccumulators();

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
