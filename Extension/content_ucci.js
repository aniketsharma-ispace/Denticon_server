console.log("UCCI CONTENT SCRIPT INJECTED");

const clean = (s) => (s || "").trim().replace(/\s+/g, " ");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Some sections of this page (confirmed: Deductibles and Maximums,
// Coordination and Other Benefits) appear to populate slightly later than
// the rest of the DOM � a live scrape immediately on page-open sometimes
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

// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// SECTION 1: PATIENT INFO
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�

function scrapePatientInfo() {
  const info = {};

  const nameEl = document.querySelector("#memberName");
  info.patient_name = clean(nameEl?.textContent || "");

  // Label/value table rows: <td class="text-muted text-end">Label</td><td>Value</td>
  // Resilient to this JSF app's id churn � walked by row structure, not id.
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

  // Claims address (a few lines under "Claims Address") and payor ID(s).
  // With no software vendor picked the Payor ID cell says "Select software
  // vendor", which is not an ID.
  // The address ends with its state and ZIP, however the page breaks the lines
  // ("DENTAL CLAIMS / P.O. BOX 69421 / HARRISBURG, PA 17106").
  const claimsMatch = bodyText.match(
    /Claims Address\s*([\s\S]{5,150}?\b[A-Z]{2},?\s+\d{5}(?:-\d{4})?)\b/
  );
  if (claimsMatch) {
    info.claims_address = claimsMatch[1]
      .split(/\n+/)
      .map(clean)
      .filter(Boolean)
      .join(", ");
  }
  const payorMatch = bodyText.match(/Payor ID\s*\n?\s*([^\n]+)/i);
  if (payorMatch && !/select software vendor/i.test(payorMatch[1])) {
    info.payor_id = clean(payorMatch[1]);
  }

  // Dentist network badge next to "Your Network" ("In-Network Dentist" /
  // "Out-of-Network Dentist"). This reflects the provider the portal session
  // is logged in as, NOT the patient -- coverage percentages change with it.
  const badgeMatch = bodyText.match(/\b(In-Network|Out-of-Network)\s*Dentist\b/i);
  if (badgeMatch) {
    info.network_status = /^in/i.test(badgeMatch[1]) ? "In" : "Out";
  }

  return info;
}

// Subscriber (policyholder) DOB.
// The top panel only shows the policyholder's NAME. Their DOB lives in the
// "Select Member" dropdown, which lists every member on the policy as
// name + status + DOB. We read that list, match the policyholder by name,
// and take that member's DOB. We only ever open/close the toggle; we never
// click a member item, because that would switch the selected patient.

const UCCI_DATE_RE = /\b(\d{2}\/\d{2}\/\d{4})\b/;

function normalizeUcciName(name) {
  return (name || "")
    .toUpperCase()
    .replace(/[^A-Z\s]/g, " ")
    .split(/\s+/)
    .filter((t) => t.length > 1) // drop middle initials ("R.")
    .join(" ");
}

function ucciNamesMatch(a, b) {
  const na = normalizeUcciName(a);
  const nb = normalizeUcciName(b);
  if (!na || !nb) return false;
  if (na === nb) return true;
  // Loose fallback: same first and last token
  const ta = na.split(" ");
  const tb = nb.split(" ");
  return ta[0] === tb[0] && ta[ta.length - 1] === tb[tb.length - 1];
}

function findMemberDropdownToggle() {
  return [...document.querySelectorAll("button, a, [role='button']")].find((el) =>
    /select\s+member/i.test(el.textContent || "")
  );
}

function findMemberDropdownMenu(toggle) {
  const scope = toggle.closest(".dropdown, .btn-group") || toggle.parentElement;
  return (
    scope?.querySelector(".dropdown-menu, [role='menu'], ul") ||
    (toggle.getAttribute("aria-controls") &&
      document.getElementById(toggle.getAttribute("aria-controls"))) ||
    null
  );
}

function parseMemberDropdownItems(menu) {
  if (!menu) return [];
  let items = [...menu.querySelectorAll(".dropdown-item, [role='menuitem'], li, a")];
  // Keep only the innermost elements that actually contain a date
  items = items.filter(
    (el) =>
      UCCI_DATE_RE.test(el.textContent || "") &&
      ![...el.children].some((c) => UCCI_DATE_RE.test(c.textContent || "") &&
        c.matches(".dropdown-item, [role='menuitem'], li, a"))
  );

  const seen = new Set();
  return items
    .map((el) => {
      const text = clean(el.textContent);
      const dob = (text.match(UCCI_DATE_RE) || [])[1] || "";
      const name = clean(
        text
          .replace(UCCI_DATE_RE, "")
          .replace(/\b(ACTIVE|INACTIVE|TERMINATED)\b/gi, "")
          .replace(/[✓✔]/g, "")
      );
      const statusMatch = text.match(/\b(ACTIVE|INACTIVE|TERMINATED)\b/i);
      return { name, dob, status: statusMatch ? statusMatch[1].toUpperCase() : "" };
    })
    .filter((m) => {
      const key = `${m.name}|${m.dob}`;
      if (!m.name || !m.dob || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

async function scrapeSubscriberFromMemberDropdown(patientInfo = {}) {
  const result = {
    subscriber_name: patientInfo.policyholder || "",
    subscriber_dob: "",
    subscriber_dob_source: "",
    policy_members: [],
  };

  const toggle = findMemberDropdownToggle();
  if (!toggle) {
    console.warn("[UCCI] Select Member dropdown not found");
  } else {
    let menu = findMemberDropdownMenu(toggle);
    let members = parseMemberDropdownItems(menu);
    let openedByUs = false;

    // Menu items are often in the DOM even while closed; only open if not
    if (members.length === 0) {
      toggle.click();
      openedByUs = true;
      const start = Date.now();
      while (Date.now() - start < 3000 && members.length === 0) {
        await sleep(200);
        menu = findMemberDropdownMenu(toggle);
        members = parseMemberDropdownItems(menu);
      }
    }

    if (openedByUs) {
      toggle.click(); // close it again, never click an item
      await sleep(150);
    }

    result.policy_members = members;
    console.log(`[UCCI] Member dropdown: ${members.length} member(s)`, members);

    const match = members.find((m) => ucciNamesMatch(m.name, result.subscriber_name));
    if (match) {
      result.subscriber_dob = match.dob;
      result.subscriber_dob_source = "member_dropdown";
    }
  }

  // Fallback: patient IS the subscriber
  if (!result.subscriber_dob && /^self$/i.test(patientInfo.relationship || "")) {
    result.subscriber_dob = patientInfo.dob || "";
    result.subscriber_dob_source = result.subscriber_dob ? "patient_self" : "";
  }

  if (!result.subscriber_dob) {
    console.warn(
      `[UCCI] Could not find DOB for policyholder "${result.subscriber_name}" in member dropdown`
    );
  }

  return result;
}

// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// SECTION 2: SERVICE HISTORY SNAPSHOT
// Plain <table id="serviceHistoryPanelList">, all rows already in the DOM
// on page load � no pagination needed (confirmed: scrolling triggers no
// network request, and every visible row is a real <tr>).
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�

const SERVICE_HISTORY_TABLE_SELECTOR = "#serviceHistoryPanelList";

const CDT_CODES = [
  "0120", "0180", "0140", "0150", "0274", "0210", "0330", "0220",
  "0364", "0431", "1110", "1120", "1206", "1351", "1510", "2391",
  "2740", "2950", "2962", "6750", "5110", "9110", "9222", "9230",
  "9243", "9310", "9944", "4341", "4355", "4346", "4910", "4381",
  "4260", "4249", "3310", "3330", "7140", "7210", "7240", "7953",
  "6010", "6056", "0272", "0270",
  // Sabrina template codes missing above
  "1208", "2160", "2980", "5212", "5899", "5995", "6057", "6058", "8090", "8080"
];

function parseServiceHistoryRows(root = document) {
  if (!root) return [];

  const table = root.matches?.(SERVICE_HISTORY_TABLE_SELECTOR)
    ? root
    : root.querySelector?.(SERVICE_HISTORY_TABLE_SELECTOR);
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

function getTargetProcedureCodes() {
  return [...new Set(CDT_CODES.map(normalizeProcedureCode).filter(Boolean))];
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



function mapServiceHistoryFromSnapshot(rawRows) {
  const rowsByCode = new Map();

  for (const row of rawRows || []) {
    if (!row || typeof row !== "object") continue;

    const code = normalizeProcedureCode(row.procedure_code);
    const date = clean(row.start);

    if (!code || !date || !parseUcciDate(date)) continue;

    if (!rowsByCode.has(code)) {
      rowsByCode.set(code, new Set());
    }

    rowsByCode.get(code).add(date);
  }

  return getTargetProcedureCodes().map((code) => ({
    procedure_code: code,
    dates: sortDatesNewestFirst([...(rowsByCode.get(code) || new Set())]),
  }));
}

// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// LEGACY SERVICE-HISTORY SEARCH IMPLEMENTATION - RETAINED FOR ROLLBACK
// Disabled because the complete history is now extracted in one pass.
// Do not delete unless the new implementation has been fully validated.
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// const SERVICE_HISTORY_SELECTORS = {
//   form: "#serviceHistoryPanelOptionInput",
//   procInput: '[id="serviceHistoryPanelOptionInput:serviceHistoryInputProc"]',
//   toothInput: '[id="serviceHistoryPanelOptionInput:serviceHistoryInputTooth"]',
//   filterButton: '[id="serviceHistoryPanelOptionInput:buttonServiceHistoryFilter"]',
//   clearButton: '[id="serviceHistoryPanelOptionInput:j_id_gv"]',
//   container: "#serviceHistoryPanelContainer",
//   table: "#serviceHistoryPanelList",
//   loader: '[id="serviceHistoryPanelOptionInput:ajaxLoaderImage"]',
// };

// function getUniqueProcedureCodes(rows) {
//   return [
//     ...new Set(
//       rows
//         .map((row) => normalizeProcedureCode(row.procedure_code))
//         .filter(Boolean)
//     ),
//   ];
// }

// function getServiceHistorySearchValue(code) {
//   const normalized = normalizeProcedureCode(code);
//   return normalized ? normalized.replace(/^D/, "") : "";
// }

// function getServiceHistorySignature(root = document) {
//   return parseServiceHistoryRows(root)
//     .map((row) => [row.start, row.end, row.procedure_code, row.tooth, row.surface].join("|"))
//     .join("~");
// }
// 
// function setNativeInputValue(input, value) {
//   const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
//   if (setter) setter.call(input, value);
//   else input.value = value;
//   input.dispatchEvent(new Event("input", { bubbles: true }));
//   input.dispatchEvent(new Event("change", { bubbles: true }));
// }
// 
// function pressEnterOnInput(input) {
//   ["keydown", "keypress", "keyup"].forEach((type) => {
//     input.dispatchEvent(
//       new KeyboardEvent(type, {
//         bubbles: true,
//         cancelable: true,
//         key: "Enter",
//         code: "Enter",
//         keyCode: 13,
//         which: 13,
//       })
//     );
//   });
// }
// 
// function isServiceHistoryLoading() {
//   const loader = document.querySelector(SERVICE_HISTORY_SELECTORS.loader);
//   return !!loader && getComputedStyle(loader).display !== "none";
// }
// 
// async function waitForServiceHistoryUpdate(
//   previousSignature,
//   { maxWaitMs = 12000, pollMs = 150 } = {}
// ) {
//   const start = Date.now();
//   const originalContainer = document.querySelector(SERVICE_HISTORY_SELECTORS.container);
//   let mutationCount = 0;
//   let loaderWasVisible = isServiceHistoryLoading();
//   const observerRoot = originalContainer?.parentElement || document.body;
//   const observer = new MutationObserver(() => {
//     mutationCount++;
//   });
// 
//   observer.observe(observerRoot, { childList: true, subtree: true, characterData: true });
// 
//   try {
//     while (Date.now() - start < maxWaitMs) {
//       const container = document.querySelector(SERVICE_HISTORY_SELECTORS.container);
//       const signature = getServiceHistorySignature(document);
//       const replaced = !!originalContainer && !!container && container !== originalContainer;
//       const changed = signature !== previousSignature;
//       const loading = isServiceHistoryLoading();
//       if (loading) loaderWasVisible = true;
//       const settled = !loading;
//       const loaderCompleted = loaderWasVisible && settled;
//       const mutationSettledLongEnough = mutationCount > 0 && settled && Date.now() - start > 1000;
// 
//       if ((changed || replaced || loaderCompleted || mutationSettledLongEnough) && settled) {
//         await sleep(150);
//         return parseServiceHistoryRows(document);
//       }
// 
//       await sleep(pollMs);
//     }
//   } finally {
//     observer.disconnect();
//   }
// 
//   throw new Error("Timed out waiting for service-history results");
// }
// 
// function getLiveViewState() {
//   return document.querySelector('input[name="javax.faces.ViewState"]')?.value || "";
// }
// 
// function updateLiveViewState(newViewState) {
//   if (!newViewState) return;
//   document.querySelectorAll('input[name="javax.faces.ViewState"]').forEach((input) => {
//     input.value = newViewState;
//   });
// }
// 
// function buildUrlEncodedBody(formData) {
//   const params = new URLSearchParams();
//   for (const [key, value] of formData.entries()) {
//     params.append(key, value);
//   }
//   return params;
// }
// 
// function parseServiceHistoryAjaxResponse(xmlText) {
//   const xml = new DOMParser().parseFromString(xmlText, "text/xml");
//   if (xml.querySelector("parsererror")) {
//     throw new Error("Invalid JSF partial-response XML");
//   }
// 
//   const updates = [...xml.querySelectorAll("update")];
//   const viewStateUpdate = updates.find((node) =>
//     (node.getAttribute("id") || "").includes("javax.faces.ViewState")
//   );
//   if (viewStateUpdate) updateLiveViewState(clean(viewStateUpdate.textContent));
// 
//   const update = updates.find(
//     (node) => node.getAttribute("id") === "serviceHistoryPanelContainer"
//   );
//   if (!update) {
//     throw new Error("serviceHistoryPanelContainer update missing");
//   }
// 
//   const wrapper = document.createElement("div");
//   wrapper.innerHTML = update.textContent || "";
//   const table = wrapper.querySelector(SERVICE_HISTORY_SELECTORS.table);
//   return parseServiceHistoryRows(table);
// }
// 
// async function directFetchServiceHistoryCode(code) {
//   const form = document.getElementById("serviceHistoryPanelOptionInput");
//   const searchValue = getServiceHistorySearchValue(code);
//   const viewState = getLiveViewState();
//   if (!form || !searchValue || !viewState) {
//     throw new Error("Service-history form, procedure code, or ViewState is missing");
//   }
// 
//   const formData = new FormData(form);
//   formData.set("serviceHistoryPanelOptionInput:serviceHistoryInputProc", searchValue);
//   formData.set("serviceHistoryPanelOptionInput:serviceHistoryInputTooth", "");
//   formData.set("serviceHistoryPanelOptionInput_SUBMIT", "1");
//   formData.set("javax.faces.ViewState", viewState);
//   formData.set("javax.faces.behavior.event", "action");
//   formData.set("javax.faces.partial.event", "click");
//   formData.set("javax.faces.source", "serviceHistoryPanelOptionInput:buttonServiceHistoryFilter");
//   formData.set("javax.faces.partial.ajax", "true");
//   formData.set("javax.faces.partial.execute", "@all");
//   formData.set(
//     "javax.faces.partial.render",
//     "serviceHistoryPanelContainer serviceHistoryModalForm serviceHistoryPanelContainer"
//   );
//   formData.set("serviceHistoryPanelOptionInput", "serviceHistoryPanelOptionInput");
// 
//   const action = new URL(form.getAttribute("action") || location.href, location.href).href;
// 
//   const response = await fetch(action, {
//     method: "POST",
//     headers: {
//       "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
//       "Faces-Request": "partial/ajax",
//     },
//     credentials: "include",
//     body: buildUrlEncodedBody(formData),
//   });
// 
//   if (!response.ok) throw new Error(`Service-history fetch failed: HTTP ${response.status}`);
// 
//   return parseServiceHistoryAjaxResponse(await response.text());
// }
// 
// async function liveButtonSearchServiceHistoryCode(code) {
//   const normalized = normalizeProcedureCode(code);
//   const searchValue = getServiceHistorySearchValue(normalized);
//   if (!normalized || !searchValue) return [];
// 
//   const input = document.querySelector(SERVICE_HISTORY_SELECTORS.procInput);
//   const toothInput = document.querySelector(SERVICE_HISTORY_SELECTORS.toothInput);
//   const button = document.querySelector(SERVICE_HISTORY_SELECTORS.filterButton);
//   const previousSignature = getServiceHistorySignature(document);
// 
//   if (input && button) {
//     input.focus();
//     if (toothInput) setNativeInputValue(toothInput, "");
//     setNativeInputValue(input, searchValue);
//     pressEnterOnInput(input);
//     button.click();
//     return waitForServiceHistoryUpdate(previousSignature);
//   }
// 
//   throw new Error("Service-history input or filter button not found");
// }
// 
// async function searchServiceHistoryCode(code) {
//   return liveButtonSearchServiceHistoryCode(code);
// }
// 
// function collectSortedUniqueDates(rows) {
//   return sortDatesNewestFirst([...new Set(rows.map((row) => clean(row.start)).filter(Boolean))]);
// }
// 
// function getRawFallbackDates(rawRows, code) {
//   return collectSortedUniqueDates(
//     rawRows.filter((row) => normalizeProcedureCode(row.procedure_code) === code)
//   );
// }
// 
// async function scrapeMappedServiceHistory(rawRows) {
//   const uniqueCodes = getTargetProcedureCodes();
//   console.log(`[UCCI] Captured ${rawRows.length} raw history rows`);
//   console.log(`[UCCI] Target service-history codes: ${uniqueCodes.length}`);
// 
//   const mappedRows = [];
//   let usedVisibleSearch = false;
// 
//   for (let i = 0; i < uniqueCodes.length; i++) {
//     const code = uniqueCodes[i];
//     const searchValue = getServiceHistorySearchValue(code);
//     console.log(`[UCCI] Searching ${code} as ${searchValue} (${i + 1}/${uniqueCodes.length})`);
// 
//     try {
//       const rows = await searchServiceHistoryCode(code);
//       let dates = collectSortedUniqueDates(rows);
//       if (!dates.length) {
//         const fallbackDates = getRawFallbackDates(rawRows, code);
//         if (fallbackDates.length) {
//           console.warn(`[UCCI] ${code} AJAX response had no dates; using raw fallback dates`);
//           dates = fallbackDates;
//         }
//       }
// 
//       console.log(`[UCCI] ${code} AJAX response returned ${rows.length} rows and ${dates.length} dates`);
//       mappedRows.push({ procedure_code: code, dates });
//     } catch (error) {
//       console.warn(`[UCCI] Live Enter/button search failed for ${code}, retrying with direct AJAX:`, error);
// 
//       try {
//         const rows = await directFetchServiceHistoryCode(code);
//         const dates = collectSortedUniqueDates(rows);
//         console.log(`[UCCI] ${code} direct AJAX retry returned ${rows.length} rows and ${dates.length} dates`);
//         mappedRows.push({ procedure_code: code, dates });
//       } catch (retryError) {
//         const dates = getRawFallbackDates(rawRows, code);
//         console.warn(`[UCCI] Both searches failed for ${code}; using raw fallback dates:`, retryError);
//         mappedRows.push({ procedure_code: code, dates });
//       }
//     }
//     usedVisibleSearch = true;
//   }
// 
//   if (usedVisibleSearch) await clearServiceHistorySearch();
//   return mappedRows;
// }
// 
// async function clearServiceHistorySearch() {
//   const input = document.querySelector(SERVICE_HISTORY_SELECTORS.procInput);
//   const toothInput = document.querySelector(SERVICE_HISTORY_SELECTORS.toothInput);
//   const clearButton = document.querySelector(SERVICE_HISTORY_SELECTORS.clearButton);
//   if (!input || !clearButton) return;
// 
//   const previousSignature = getServiceHistorySignature(document);
// 
//   try {
//     setNativeInputValue(input, "");
//     if (toothInput) setNativeInputValue(toothInput, "");
//     clearButton.click();
//     await waitForServiceHistoryUpdate(previousSignature, { maxWaitMs: 12000 });
//     console.log("[UCCI] Restored unfiltered service history");
//   } catch (error) {
//     console.warn("[UCCI] Could not restore unfiltered service history:", error);
//   }
// }
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// END LEGACY SERVICE-HISTORY SEARCH IMPLEMENTATION
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�

// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// SECTION 3: BENEFIT CATEGORY TABLES (Preventive Exams, X-rays, etc.)
//
// All 26 category tables + the 1 Wellness Benefits table are ALREADY fully
// rendered in the DOM on page load (confirmed via fresh-page-load test �
// no clicking/accordion-expansion required), all sharing the same
// (invalid but present) id="benefitDetailAllServiceProceduresList".
//
// Each row is read by CSS class prefix (benefitServiceDetailProcedure-colN
// or the noDisplay placeholder cells used on "Not Covered" merged rows)
// rather than by cell position/colspan � this naturally normalizes both
// row shapes to the same 8 logical fields.
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�

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
  //      their own dedicated scrape functions � including them here shifted
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

// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// SECTION 4: DEDUCTIBLES AND MAXIMUMS
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�

async function scrapeDeductiblesAndMaximums() {
  const table = await waitForRows("#benefitPolicyInformationDeductiblesAndMaximums");
  if (!table) return [];

  return [...table.querySelectorAll("tbody tr")].map((tr) => {
    const cells = [...tr.querySelectorAll("td")].map((td) => clean(td.textContent));
    return { benefit: cells[0] || "", coverage: cells[1] || "" };
  });
}

// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// SECTION 5: COORDINATION AND OTHER BENEFITS
// (single-column table � plan-level rules/disclaimers)
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�

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

// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// DOWNLOAD
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�

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
  console.log(`�S Downloaded: ${filename}`);
}

// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�
// MAIN
// �"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"��"�

// ===========================================================================
// SECTION 6: PROCEDURE LOOKUP (direct JSF AJAX POSTs, no UI clicks)
// Replays the "Procedure Allowance + related procedure lookup info" request
// for each target code and parses the partial-response HTML. The page on
// screen is never touched. Each response carries a new ViewState that the
// next request must use, so lookups run strictly one after another.
// All form/button ids are read from the live page or the latest response,
// never hardcoded, because JSF j_id_* ids can change between sessions.
// ===========================================================================

const UCCI_ENDPOINT = "/tuctpi/subscriber.xhtml";
const UCCI_DATE_ONLY_RE = /^\d{2}\/\d{2}\/\d{4}$/;
let ucciViewState = null;

function getCurrentViewState() {
  return (
    ucciViewState ??
    document.querySelector('input[name="javax.faces.ViewState"]')?.value ??
    ""
  );
}

function setCurrentViewState(value) {
  if (!value) return;
  ucciViewState = value; // keep raw: the server's value ends in "\n"
  document
    .querySelectorAll('input[name="javax.faces.ViewState"]')
    .forEach((input) => (input.value = value));
}

// Pulls execute/render out of a JSF onclick, e.g.
// jsf.ajax.request('x',event,{execute:'@form ',render:'navigationPanel ',...})
function parseJsfOnclick(el) {
  const s = el?.getAttribute("onclick") || "";
  const exec = s.match(/execute:\\?'([^'\\]*)/);
  const rend = s.match(/render:\\?'([^'\\]*)/);
  return {
    execute: exec ? exec[1].trim() : null,
    render: rend ? rend[1].trim() : null,
  };
}

function parsePartialResponse(xmlText) {
  const xml = new DOMParser().parseFromString(xmlText, "text/xml");
  if (xml.querySelector("parsererror")) throw new Error("Invalid JSF partial-response XML");
  if (xml.querySelector("redirect")) throw new Error("JSF redirect (session expired?)");
  const err = xml.querySelector("error");
  if (err) throw new Error(`JSF error: ${clean(err.textContent)}`);

  const updates = {};
  xml.querySelectorAll("update").forEach((u) => {
    const id = u.getAttribute("id") || "";
    if (id.includes("javax.faces.ViewState")) setCurrentViewState(u.textContent);
    else updates[id] = new DOMParser().parseFromString(u.textContent, "text/html");
  });
  return updates;
}

// Request timing, per kind, so a slow scrape shows where the time goes.
let ucciRequestStats = {};

function recordRequest(kind, ms, bytes) {
  const s = (ucciRequestStats[kind] ||= { count: 0, total_ms: 0, total_kb: 0 });
  s.count += 1;
  s.total_ms += ms;
  s.total_kb += bytes / 1024;
}

function summarizeRequestStats() {
  const out = {};
  for (const [kind, s] of Object.entries(ucciRequestStats)) {
    out[kind] = {
      count: s.count,
      total_ms: Math.round(s.total_ms),
      avg_ms: Math.round(s.total_ms / s.count),
      avg_kb: Math.round((s.total_kb / s.count) * 10) / 10,
    };
  }
  return out;
}

async function jsfPost({ form, sourceId, execute, render, kind = "other" }) {
  const startedAt = performance.now();
  const formId = form.id;
  // JSF defaults: no execute -> @this (the source component)
  const exec = (execute || "@this")
    .split(/\s+/)
    .filter(Boolean)
    .map((t) => (t === "@form" ? formId : t === "@this" ? sourceId : t))
    .join(" ");

  const params = new URLSearchParams();
  form.querySelectorAll("input[name]").forEach((input) => {
    if (["button", "submit", "image", "reset"].includes(input.type)) return;
    if (input.name === "javax.faces.ViewState") return;
    params.append(input.name, input.value);
  });
  params.set("javax.faces.ViewState", getCurrentViewState());
  params.set("javax.faces.behavior.event", "action");
  params.set("javax.faces.partial.event", "click");
  params.set("javax.faces.source", sourceId);
  params.set("javax.faces.partial.ajax", "true");
  params.set("javax.faces.partial.execute", exec);
  params.set("javax.faces.partial.render", render || "@all");
  params.set(formId, formId);

  const res = await fetch(UCCI_ENDPOINT, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
      "Faces-Request": "partial/ajax",
    },
    body: params,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const text = await res.text();
  recordRequest(kind, performance.now() - startedAt, text.length);
  return parsePartialResponse(text);
}

// --- parsers for one lookup result ---------------------------------------

function cellLines(td) {
  if (!td) return [];
  const copy = td.cloneNode(true);
  copy.querySelectorAll("br").forEach((br) => br.replaceWith("\n"));
  return copy.textContent.split(/\n|\|/).map(clean).filter(Boolean);
}

function parseProcedureDetails(doc) {
  const row = doc.querySelector("#procedureDetailInfoTable1 tbody tr");
  if (!row) return null;
  const tds = row.querySelectorAll("td");
  if (tds.length < 6) return { covered: clean(row.textContent), raw_text: clean(row.textContent) };
  return {
    covered: clean(tds[0].textContent),
    allowance: cellLines(tds[1])[0] || "",
    allowance_lines: cellLines(tds[1]),
    coverage_or_copay: cellLines(tds[2])[0] || "",
    coverage_lines: cellLines(tds[2]), // e.g. ["100%", "100% In network ~ Accident Related"]
    limitations: cellLines(tds[3]), // every limitation kept separately
    applies_to_deductible: clean(tds[4].textContent),
    applies_to_maximum: clean(tds[5].textContent),
    cost_share: cellLines(doc.querySelector("#procedureDetailInfoTable2 td")).join(" "),
  };
}

const GROUP_SEL = '[id$=":relatedProcedureGrouping"]';
const relatedGroupCache = new Map(); // "limitation|visible codes" -> full code list

function parseGroup(g) {
  const headingNode = [...g.childNodes].find(
    (n) => n.nodeType === Node.TEXT_NODE && clean(n.textContent)
  );
  const heading = clean(headingNode?.textContent || "");
  const limitation = (heading.match(/when\s+(.+?)\s+applies/i) || [])[1] || heading;
  const codes = [...g.querySelectorAll("table a")]
    .map((a) => clean(a.textContent).match(/^(D\d{4})\s*-\s*(.*?)\s*>?$/))
    .filter(Boolean)
    .map((m) => ({ code: m[1], name: m[2] }));
  return { limitation, heading, codes };
}

function parseRelatedGroupsIndexed(root) {
  return [...root.querySelectorAll(GROUP_SEL)].map((el) => ({
    idx: (el.id.match(/:(\d+):relatedProcedureGrouping$/) || [])[1] || el.id,
    group: parseGroup(el),
    hasMore: findMoreLinks(el).length > 0,
  }));
}

function groupKey(g) {
  return `${g.limitation}|${g.codes.map((c) => c.code).join(",")}`;
}

function findMoreLinks(root) {
  const scope = root.matches?.(GROUP_SEL) ? [root] : [...root.querySelectorAll(GROUP_SEL)];
  return scope.flatMap((g) => [...g.querySelectorAll("a")]).filter(
    (a) => !a.closest("table") && /\bmore\b/i.test(a.textContent)
  );
}

function parseHistoryRows(rows) {
  return rows
    .map((cells) => cells.map((c) => clean(c.textContent)))
    .filter((t) => UCCI_DATE_ONLY_RE.test(t[0] || ""));
}

function parseProcedureHistory(doc) {
  const rows = [...doc.querySelectorAll("#procedureServiceHistoryPanelList tbody tr")].map(
    (tr) => [...tr.querySelectorAll("td")]
  );
  return parseHistoryRows(rows).map((t) => ({
    date: t[0], procedure_code: t[1] || "", tooth: t[2] || "", surface: t[3] || "",
  }));
}

// The lookup response also contains the patient's FULL service history
// (the Service History modal), so we take it once from the first response.
function parseFullServiceHistory(doc) {
  const table = doc.querySelector('[id="serviceHistoryModalForm:serviceHistoryPanelList"]');
  if (!table) return [];
  const rows = [...table.querySelectorAll("tbody tr")].map((tr) => [...tr.querySelectorAll("td")]);
  return parseHistoryRows(rows).map((t) => ({
    start: t[0], end: t[1] || "", procedure_code: t[2] || "", tooth: t[3] || "", surface: t[4] || "",
  }));
}

function parsePolicyDetails(doc) {
  return [...doc.querySelectorAll("#policyDetails tbody tr")]
    .map((tr) => [...tr.querySelectorAll("td")].map((td) => clean(td.textContent)))
    .filter((t) => t[0])
    .map((t) => ({ type: t[0], description: t[1] || "" }));
}

// --- one lookup ----------------------------------------------------------

async function expandRelatedProcedures(panelDoc, useCache = true) {
  let root = panelDoc.querySelector("#proc-related-procedures");
  if (!root) return { groups: [], root: null };

  // Groups like "1 Per 5 Years ~ Per Same Group" (100+ codes) show up on many
  // lookups. Expand each one once per scrape and reuse it after that.
  const initial = parseRelatedGroupsIndexed(root);
  const fromCache = new Map();
  const needMore = new Set();
  for (const { idx, group, hasMore } of initial) {
    if (!hasMore) continue;
    const cached = useCache ? relatedGroupCache.get(groupKey(group)) : null;
    if (cached) fromCache.set(idx, cached);
    else needMore.add(idx);
  }

  const clicked = new Set();
  for (let i = 0; i < 10 && needMore.size; i++) {
    const more = findMoreLinks(root).find((a) => {
      const idx = (a.closest(GROUP_SEL)?.id.match(/:(\d+):relatedProcedureGrouping$/) || [])[1];
      return needMore.has(idx) && !clicked.has(a.id);
    });
    if (!more) break;
    clicked.add(more.id);
    const { execute, render } = parseJsfOnclick(more);
    const updates = await jsfPost({
      kind: "more",
      form: more.closest("form"),
      sourceId: more.id,
      execute,
      render: render || "proc-related-procedures",
    });
    const next = Object.values(updates)[0]?.querySelector("#proc-related-procedures");
    if (!next) break;
    root = next;
  }

  const groups = parseRelatedGroupsIndexed(root).map(({ idx, group, hasMore }) => {
    if (fromCache.has(idx)) return { ...group, codes: fromCache.get(idx) };
    const before = initial.find((x) => x.idx === idx);
    if (before && needMore.has(idx) && !hasMore) {
      relatedGroupCache.set(groupKey(before.group), group.codes);
    }
    return group;
  });
  return { groups, root };
}

// Some plans (military pay grades) list a code once per pay-grade group:
//   D7140  Yes  $92.78  70%  Pay Grades E1 thru E4 | More...
//   D7140  Yes  $92.78  60%  All Other Pay Grades | More...
// Lookup opens only the first row, and a code without related procedures
// offers no way to the others. The page's own benefit tables hold every row
// (Search By only shows/hides them), so they are read straight from the page
// once, while it shows the benefits view. Choosing the row is the server's
// job (portals/ucci.py).
let ucciBenefitRows = {};

function readBenefitTableRows() {
  const rows = {};
  document.querySelectorAll("tr").forEach((tr) => {
    const cells = [...tr.cells];
    if (cells.length < 8) return; // "Not Covered" rows span the columns
    const code = clean(cells[0].textContent);
    if (!/^D\d{4}$/.test(code)) return;
    const limitations = clean(cells[5].textContent)
      .replace(/\|?\s*More\.{2,3}\s*$/i, "")
      .split("|")
      .map(clean)
      .filter(Boolean);
    (rows[code] ||= []).push({
      covered: clean(cells[2].textContent),
      allowance: clean(cells[3].textContent),
      coverage_or_copay: clean(cells[4].textContent),
      limitations,
      applies_to_deductible: clean(cells[6].textContent),
      applies_to_maximum: clean(cells[7].textContent),
    });
  });
  return rows;
}

// Every row of a code listed more than once. The table cuts the limitation
// short ("| More..."), so each row keeps its own pay-grade line and takes
// the rest (the frequency) from the code's lookup.
function variantsFromTable(code, lookupDetails) {
  const rows = ucciBenefitRows[code] || [];
  if (rows.length < 2) return null;
  const isGrade = (line) => /pay\s+grade/i.test(line);
  const shared = (lookupDetails?.limitations || []).filter((line) => !isGrade(line));
  return rows.map((row) => ({
    source: "benefit_table",
    details: {
      ...row,
      coverage_lines: [row.coverage_or_copay],
      limitations: [...row.limitations.filter(isGrade), ...shared],
    },
  }));
}

async function lookupProcedure(code, lastDoc, light = false) {
  const form =
    lastDoc?.querySelector("#procedureDetailsInput") ||
    document.getElementById("procedureDetailsInput");
  if (!form) throw new Error("Procedure lookup form not found");
  const button = form.querySelector("button, input[type=submit]");
  const codeInput = form.querySelector('input[type="text"]');
  if (!button || !codeInput) throw new Error("Lookup button/input not found");

  codeInput.value = code; // only on our copy when lastDoc is used
  const { execute, render } = parseJsfOnclick(button);
  const updates = await jsfPost({
    kind: light ? "lookup" : "lookup_full",
    form,
    sourceId: button.id,
    execute: execute || "@form",
    // light: ask only for the procedure panel (~a fraction of navigationPanel).
    // The full panel is fetched once, for the form, Back link and full history.
    render: light ? "benefitProcedurePanel" : render || "navigationPanel",
  });

  const doc =
    updates.navigationPanel || updates.benefitProcedurePanel || Object.values(updates)[0];
  const panel = doc?.querySelector("#benefitProcedurePanel");
  if (!panel) {
    const msg = clean(doc?.querySelector("#errorContainer")?.textContent || "");
    return { doc, data: { procedure_code: code, error: msg || "No procedure panel in response" } };
  }

  const title = clean(panel.querySelector("h2")?.textContent || "");
  const returnedCode = (title.match(/^(D\d{4})/) || [])[1] || "";
  if (returnedCode && returnedCode !== code) {
    const e = new Error(`Response was for ${returnedCode}, expected ${code}`);
    e.mismatch = true;
    throw e;
  }
  const history = parseProcedureHistory(doc);
  const own = history.filter((h) => h.procedure_code === code).map((h) => h.date);
  const shared = history.filter((h) => h.procedure_code !== code).map((h) => h.date);

  const details = parseProcedureDetails(doc);
  const { groups: related_groups, root: relatedRoot } = await expandRelatedProcedures(doc);
  // Codes with one row per pay grade: every row is in the page's benefit
  // tables (read once at the start), so no extra requests are needed.
  const variants = variantsFromTable(code, details);

  return {
    doc,
    data: {
      procedure_code: code,
      procedure_name: title.replace(/^D\d{4}:\s*/, ""),
      details,
      ...(variants ? { variants } : {}),
      related_groups,
      history,
      own_dates: sortDatesNewestFirst([...new Set(own)]),
      shared_dates: sortDatesNewestFirst([...new Set(shared)]),
      // Age limits are already in the limitations; only ortho needs this
      ...(code === "D8080" ? { policy_details: parsePolicyDetails(doc) } : {}),
    },
  };
}

async function returnToBenefitsView(doc) {
  const back = [...doc.querySelectorAll("a")].find((a) =>
    /back to benefits view/i.test(a.textContent)
  );
  if (!back) return;
  const { execute } = parseJsfOnclick(back);
  // We only need the server to reset its state, not the re-rendered
  // benefits summary, so ask for no HTML back (only the new ViewState).
  await jsfPost({ kind: "back", form: back.closest("form"), sourceId: back.id, execute, render: "@none" });
}

async function scrapeProcedureLookups(codes, onProgress) {
  relatedGroupCache.clear();
  ucciRequestStats = {};
  const procedures = {};
  let fullHistory = null;
  let lastDoc = null;

  for (const [i, code] of codes.entries()) {
    onProgress?.(i + 1, codes.length, code);
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        let { doc, data } = await lookupProcedure(code, lastDoc, Boolean(lastDoc));
        if (data.error && lastDoc) {
          // light response didn't work for this code, retry with the full panel
          ({ doc, data } = await lookupProcedure(code, lastDoc, false));
        }
        procedures[code] = data;
        if (doc?.querySelector("#procedureDetailsInput")) lastDoc = doc;
        if (!fullHistory && doc) fullHistory = parseFullServiceHistory(doc);
        // Reset the server back to the benefits view before the next code.
        // Without this, some lookups return an empty history for their own
        // code depending on what was looked up before (confirmed: D1110
        // after D0431 -> []; D1110 on its own -> 2 rows).
        if (doc) {
          try {
            await returnToBenefitsView(lastDoc || doc);
          } catch (err) {
            console.warn(`[UCCI] ${code}: Back to Benefits View failed:`, err.message);
          }
        }
        console.log(`[UCCI] ${code}: ${data.error ? "ERROR " + data.error : "ok"}`);
        break;
      } catch (err) {
        console.warn(`[UCCI] ${code} attempt ${attempt} failed:`, err.message);
        procedures[code] = { procedure_code: code, error: err.message };
        if (/redirect|session/i.test(err.message)) return { procedures, full_service_history: fullHistory || [], aborted: true };
        if (!err.mismatch) break; // only retry wrong-code responses
        await sleep(600);
      }
    }
  }


  return { procedures, full_service_history: fullHistory || [] };
}

// Small status box, bottom-right of the portal page. Purely visual: it does
// not take clicks (pointer-events: none) and hides itself after finishing.
function showUcciStatus(text, state = "running") {
  let box = document.getElementById("ucci-scrape-status");
  if (!box) {
    box = document.createElement("div");
    box.id = "ucci-scrape-status";
    box.style.cssText =
      "position:fixed;right:16px;bottom:16px;z-index:2147483647;padding:10px 14px;" +
      "border-radius:8px;font:13px/1.4 system-ui,sans-serif;color:#fff;" +
      "box-shadow:0 4px 12px rgba(0,0,0,.3);max-width:340px;pointer-events:none";
    document.body.appendChild(box);
  }
  box.style.background =
    state === "error" ? "#b42318" : state === "done" ? "#067647" : "#1f3a8a";
  box.textContent = `UCCI scrape: ${text}`;
  clearTimeout(box._hideTimer);
  if (state !== "running") box._hideTimer = setTimeout(() => box.remove(), 10000);
}

// The page sections (Deductibles and Maximums, Coordination) only exist on
// the benefits view. If the user left the page on a procedure they looked up
// themselves, go back first (11/10: Jessica's scrape came back without them).
async function ensureBenefitsView() {
  const visibleBack = () =>
    [...document.querySelectorAll("a, button")].find(
      (el) => /back to benefits view/i.test(el.textContent || "") && el.offsetParent !== null
    );
  const back = visibleBack();
  if (!back) return;
  showUcciStatus("returning to the benefits view...");
  back.click();
  const start = Date.now();
  while (Date.now() - start < 10000) {
    await sleep(250);
    if (!visibleBack() && /Deductibles and Maximums/i.test(document.body.innerText || "")) return;
  }
  console.warn("[UCCI] Benefits view did not come back after 10 s");
}

async function runUcciAudit() {
  const root = document.documentElement;
  if (root.dataset.ucciScrapeRunning === "1") {
    console.warn("[UCCI] Scrape already running, ignoring this trigger");
    showUcciStatus("already running, wait for it to finish");
    return null;
  }
  root.dataset.ucciScrapeRunning = "1";
  try {
    return await runUcciAuditInner();
  } catch (err) {
    console.error("[UCCI] Scrape failed:", err);
    showUcciStatus(`failed: ${err.message}`, "error");
    throw err;
  } finally {
    delete root.dataset.ucciScrapeRunning;
  }
}

async function runUcciAuditInner() {
  console.log("=== UCCI SCRAPE STARTED ===");
  const startedAt = performance.now();
  showUcciStatus("started, reading patient info...");
  await ensureBenefitsView();
  ucciBenefitRows = readBenefitTableRows();
  console.log(`[UCCI] Benefit table rows read for ${Object.keys(ucciBenefitRows).length} codes`);

  const auditData = {
    source: "UCCI",
    scraped_at: new Date().toISOString(),
  };

  console.log("Scraping patient info...");
  auditData.patient_info = scrapePatientInfo();

  console.log("Scraping subscriber DOB from Select Member dropdown...");
  Object.assign(
    auditData.patient_info,
    await scrapeSubscriberFromMemberDropdown(auditData.patient_info)
  );

  // Page sections first, while the screen still shows the benefits view
  console.log("Scraping Deductibles and Maximums...");
  showUcciStatus("reading deductibles, maximums and COB...");
  auditData.deductibles_and_maximums = await scrapeDeductiblesAndMaximums();

  console.log("Scraping financial accumulators...");
  auditData.financial_accumulators = scrapeFinancialAccumulators();

  console.log("Scraping Coordination and Other Benefits...");
  auditData.coordination_and_other_benefits = await scrapeCoordinationAndOtherBenefits();

  const codes = getTargetProcedureCodes();
  console.log(`Running procedure lookups for ${codes.length} codes...`);
  const { procedures, full_service_history } = await scrapeProcedureLookups(
    codes,
    (n, total, code) => showUcciStatus(`looking up ${code} (${n}/${total})`)
  );
  auditData.procedures = procedures;
  auditData.full_service_history = full_service_history;
  auditData.request_stats = summarizeRequestStats();
  console.table(auditData.request_stats);

  // Old shape kept so patient_notes.py's UCCI history lookup keeps working:
  // own dates only; shared/related dates live under procedures[code].
  auditData.service_history = codes.map((code) => ({
    procedure_code: code,
    dates: procedures[code]?.own_dates || [],
  }));

  auditData.scrape_duration_ms = Math.round(performance.now() - startedAt);
  console.log(`=== UCCI SCRAPE COMPLETE (${auditData.scrape_duration_ms} ms) ===`);
  console.log(auditData);

  chrome.storage.local.get("audit_context", (result) => {
    const context = result.audit_context || {};
    context.ucci_data = auditData;
    chrome.storage.local.set({ audit_context: context }, () => {
      console.log("UCCI data stored");
      triggerUcciDownload(auditData);
      const secs = Math.round(auditData.scrape_duration_ms / 1000);
      const errs = Object.values(auditData.procedures).filter((p) => p.error).length;
      showUcciStatus(
        `done: ${codes.length} codes in ${secs}s` + (errs ? `, ${errs} with errors` : "") + ", downloading",
        errs ? "error" : "done"
      );
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