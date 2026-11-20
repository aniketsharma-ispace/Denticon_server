// content_ddri.js - DDRI Provider Portal Auditor
const STORAGE_KEYS = {
  AUDIT_CONTEXT: "audit_context",
  PROGRESS: "crawl_progress",
  CURRENT_CARRIER: "current_carrier",
  CACHED_PATIENT_NOTES: "cached_patient_notes",
};

const PROCEDURE_CODES = [
  "D0180",
  "D0120",
  "D0140",
  "D0150",
  "D0210",
  "D0220",
  "D0230",
  "D0240",
  "D0274",
  "D0330",
  "D1510",
  "D1110",
  "D1120",
  "D1206",
  "D1351",
  "D2140",
  "D2331",
  "D2620",
  "D2740",
  "D2950",
  "D2991",
  "D3347",
  "D3310",
  "D3330",
  "D4260",
  "D4341",
  "D4346",
  "D4355",
  "D4381",
  "D4910",
  "D5860",
  "D5110",
  "D5740",
  "D5982",
  "D6194",
  "D6010",
  "D6056",
  "D6065",
  "D6245",
  "D7259",
  "D7140",
  "D7240",
  "D8010",
  "D8080",
  "D8090",
  "D9430",
  "D9110",
  "D9222",
  "D9239",
  "D9310",
  "D9944",

  "D0603",
  "D2160",
  "D2791",
  "D9230",
  "D3331",
  "D3320",
  "D3332",
  "D3346",
  "D3348",
  "D3351",
  "D3353",
  "D3410",
  "D3421",
  "D3430",
  "D4240",
  "D4249",
  "D4261",
  "D4263",
  "D4264",
  "D4266",
  "D4274",
  "D4320",
  "D6100",
  "D7210",
  "D7220",
  "D7230",
  "D7280",
  "D7283",
  "D7285",
  "D7286",
  "D7310",
  "D7311",
  "D7320",
  "D7510",
  "D7511",
  "D7951",
  "D7960",
  "D7963",
  "D7970",
  "D9223",
  "D9243",
  "D9610",
  "D9612",
  "D8020",
  "D8050",
  "D8060",
  "D8070",
  "D2954",
  "D2391",
  "D2392",
  "D2393",
  "D2394",
  "D6740",
  "D3110",
  "D3220",
  "D3240",
  "D4273",
  "D4275",
  "D4277",
  "D4321",
  "D6013",
  "D6057",
  "D7241",
  "D7961",
  "D0367",
  "D0380",
  "D7251",
  "D6104",
  "D7921",
  "D7952",
  "D7956",
  "D1208",
  "D9945",
  "D2150",
  "D2161",
  "D2961",
  "D4267",
  "D5810",
  "D5925",
  "D5511",
  "D6058",
  "D0272",
  "D1330",
  "D1354",
  "D1516",
  "D1575",
  "D2330",
  "D2335",
  "D2929",
  "D2930",
  "D2933",
  "D2934",
  "D2952",
  "D7962",
  "D9244",
  "D9247",
  "D9420",
  "D9920",
  "D0364",
  "D0365",
  "D0366",
  "D0368",
  "D0801",
  "D1352",
  "D3221",
  "D5911",
  "D3425",
  "D7410",
  "D7411",
  "D7450",
  "D7451",
  "D5730",
  "D2920",
  "D6106",
  "D9910",
  "D9911",
  "D0277",
  "D2751",
  "D2931",
  "D5120",
  "D5130",
  "D5140",
  "D5211",
  "D5212",
  "D5750",
  "D5751",
  "D5225",
  "D5226",
  "D5731",
  "D7111",
  "D6061",
  "D0350",
  "D8670",
  "D0160",
  "D6110",
  "D6190",
  "D3120",
  "D2610",
  "D2642",
  "D2750",
  "D5650",
  "D5821",
  "D5912",
  "D9630",
  "D9946",
  "D9947",
  "D4921",
  "D8220",
  "D8680",
  "D5995",
  "D6750",
  "D5899",
  "D2980",
  "D2520",
  "D2194",
  "D5940",
  "D9311",
  "D8040",
  "D9932",
  "D5510",
  "D7950",
  "D7971",
  "D2959",
  "D2332",
  "D9245",
  "D9246",
];

// Exact portal benefit labels whose scope clearly covers these CDT codes.
// Codes without a verified mapping intentionally do not inherit a frequency.
const BENEFIT_SERVICES_BY_CODE = {
  D0120: ["Oral exam"],
  D0140: ["Oral exam"],
  D0150: ["Oral exam"],
  D0180: ["Oral exam"],
  D0210: ["Complete x-ray series or panoramic film"],
  D0220: ["Single x-rays"],
  D0230: ["Single x-rays"],
  D0240: ["Single x-rays"],
  D0272: ["Bitewing x-rays"],
  D0274: ["Bitewing x-rays"],
  D0277: ["Bitewing x-rays"],
  D0330: ["Complete x-ray series or panoramic film"],
  D1110: ["Cleaning"],
  D1120: ["Cleaning"],
  D1206: ["Fluoride treatment"],
  D1208: ["Fluoride treatment"],
  D1351: ["Sealants"],
  D1510: ["Space maintainers"],
  D1516: ["Space maintainers"],
  D9110: [
    "Palliative treatment (minor procedures necessary to relieve acute pain)",
  ],
  D9310: ["Consultation"],
  D2140: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2150: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2160: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2161: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2330: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2331: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2332: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2335: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2391: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2392: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2393: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2394: ["Amalgam (silver) fillings and composite (white) fillings"],
  D2620: [
    "Crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
    "Crowns over natural teeth, build ups, posts and cores",
  ],
  D2642: [
    "Crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
    "Crowns over natural teeth, build ups, posts and cores",
  ],
  D2740: [
    "Crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
    "Crowns over natural teeth, build ups, posts and cores",
  ],
  D2750: [
    "Crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
    "Crowns over natural teeth, build ups, posts and cores",
  ],
  D2751: [
    "Crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
    "Crowns over natural teeth, build ups, posts and cores",
  ],
  D2791: [
    "Crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
    "Crowns over natural teeth, build ups, posts and cores",
  ],
  D2950: [
    "Crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
    "Crowns over natural teeth, build ups, posts and cores",
  ],
  D2952: [
    "Crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
    "Crowns over natural teeth, build ups, posts and cores",
  ],
  D2954: [
    "Crowns and onlays over natural teeth that are not part of a bridge, build ups, posts and cores",
    "Crowns over natural teeth, build ups, posts and cores",
  ],
  D2920: ["Recementing crowns or bridges"],
  D2929: ["Recementing crowns or bridges"],
  D2980: ["Recementing crowns or bridges"],
  D3310: ["Root canal therapy on permanent teeth"],
  D3320: ["Root canal therapy on permanent teeth"],
  D3330: ["Root canal therapy on permanent teeth"],
  D3331: ["Root canal therapy on permanent teeth"],
  D3332: ["Root canal therapy on permanent teeth"],
  D3346: ["Root canal therapy on permanent teeth"],
  D3347: ["Root canal therapy on permanent teeth"],
  D3348: ["Root canal therapy on permanent teeth"],
  D4249: ["Crown lengthening"],
  D4260: ["Osseous (bone) surgery"],
  D4261: ["Osseous (bone) surgery"],
  D4341: ["Root planing and scaling"],
  D4342: ["Root planing and scaling"],
  D4346: ["Gingivectomies"],
  D9243: [
    "General anesthesia or intravenous (I.V.) sedation for certain complex surgical procedures",
  ],
  D4263: ["Guided tissue regeneration and bone replacement graft"],
  D4264: ["Guided tissue regeneration and bone replacement graft"],
  D4266: ["Guided tissue regeneration and bone replacement graft"],
  D4267: ["Guided tissue regeneration and bone replacement graft"],
  D4273: ["Soft tissue grafts"],
  D4274: ["Soft tissue grafts"],
  D4275: ["Soft tissue grafts"],
  D4277: ["Soft tissue grafts"],
  D4910: ["Periodontal maintenance following active therapy"],
  D5110: ["Partial and complete dentures"],
  D5120: ["Partial and complete dentures"],
  D5211: ["Partial and complete dentures"],
  D5212: ["Partial and complete dentures"],
  D5213: ["Partial and complete dentures"],
  D5225: ["Partial and complete dentures"],
  D5226: ["Partial and complete dentures"],
  D5510: ["Repairs to existing partial or complete dentures"],
  D5511: ["Repairs to existing partial or complete dentures"],
  D5730: ["Rebasing or relining of partial or complete dentures"],
  D5731: ["Rebasing or relining of partial or complete dentures"],
  D5750: ["Rebasing or relining of partial or complete dentures"],
  D5751: ["Rebasing or relining of partial or complete dentures"],
  D6065: ["Bridges and crowns over implants"],
  D6750: ["Bridges and crowns over implants"],
  D9944: ["Occlusal guards"],
  D9945: ["Occlusal guards"],
  D9946: ["Occlusal guards"],
  D6010: ["Surgical placement of endosteal implant and abutment"],
  D6057: ["Surgical placement of endosteal implant and abutment"],
};

// The lookup-unavailable response is treated as not covered only for these codes,
// which have been confirmed by the portal screenshot.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clean = (str) =>
  (str || "")
    .replace(/[\n\r\t]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
const NO_FREQUENCY_CODES = new Set([
  "D9110",
  "D9310",
  "D2160",
  "D2391",
  "D4355",
  "D6058",
]);
const ALWAYS_NO_FREQUENCY_CODES = new Set(["D4355", "D6058"]);
const LOOKUP_UNAVAILABLE_UNCOVERED_CODES = new Set(["D4381", "D5899", "D9230"]);

// Logging helper
function logState(state) {
  console.log(`[DDRI][${state}]`);
}

function broadcastState(state, title, message = "", progress = 0) {
  const payload = {
    carrier: "DDRI",
    state: state,
    stage: 0,
    progress: progress,
    title: title,
    message: message,
    timestamp: Date.now(),
  };

  // Storage (Persistent)
  chrome.storage.local.set({ [STORAGE_KEYS.PROGRESS]: payload });

  // Runtime (Live to Popup)
  chrome.runtime
    .sendMessage({ type: "PROGRESS_UPDATE", payload: payload })
    .catch(() => {});
}

async function clearPreviousSession() {
  return new Promise((resolve) => {
    chrome.storage.local.remove(
      [STORAGE_KEYS.AUDIT_CONTEXT, STORAGE_KEYS.PROGRESS, "partial_json"],
      () => {
        resolve();
      },
    );
  });
}

// ------------------------------------------------------------------
// SCRAPING LOGIC
// ------------------------------------------------------------------

function getLabelValue(tableSelector, labelText) {
  const table = document.querySelector(tableSelector);
  if (!table) return "N/A";

  const cells = Array.from(table.querySelectorAll("td, th"));
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

function getPolicyYearValue() {
  const rows = Array.from(document.querySelectorAll(".SubscriberProfile tr"));
  for (const row of rows) {
    if (row.id === "MultipleCalendarYearRow" || row.style.display === "none")
      continue;
    const cells = Array.from(row.querySelectorAll("td"));
    for (let i = 0; i < cells.length - 1; i++) {
      if (/^(calendar|policy) year:?$/i.test(clean(cells[i].textContent))) {
        const value = clean(cells[i + 1].textContent);
        if (value) return value;
      }
    }
  }
  return "N/A";
}

function getEligibilityRow(labelText) {
  const table = document.querySelector("table.Eligibility");
  if (!table) return null;
  const cells = Array.from(table.querySelectorAll("td"));
  for (let i = 0; i < cells.length; i++) {
    if (
      clean(cells[i].textContent).toLowerCase() ===
      clean(labelText).toLowerCase()
    ) {
      return {
        relationship: clean(cells[i + 1]?.textContent),
        dob: clean(cells[i + 2]?.textContent),
        dates: clean(cells[i + 3]?.textContent),
      };
    }
  }
  return null;
}

function collectPatient() {
  const subName = getLabelValue(".SubscriberProfile", "Subscriber Name");
  const memberName = getLabelValue(".SubscriberProfile", "Member Name");
  let elig = getEligibilityRow(memberName);

  if (!elig) {
    const table = document.querySelector("table.Eligibility");
    if (table) {
      const dataRows = Array.from(table.querySelectorAll("tbody tr"));
      if (dataRows.length === 1) {
        const cells = dataRows[0].querySelectorAll("td");
        if (cells.length >= 5) {
          elig = {
            relationship: clean(cells[2].textContent),
            dob: clean(cells[3].textContent),
            dates: clean(cells[4].textContent),
          };
        }
      }
    }
  }

  return {
    name: memberName,
    subscriber_name: subName,
    member_id: getLabelValue(".SubscriberProfile", "Subscriber ID"),
    dob: elig ? elig.dob : "N/A",
    relationship: elig ? elig.relationship : "N/A",
  };
}

// NEW HELPER: fixes the bug where collectPlan() looked up the Eligibility row by *Subscriber*
// Name (e.g. "CHARLES RAPOZA"), but the Eligibility table row lists the covered *Member*
// (e.g. "DONNA RAPOZA", a spouse/dependent) -- so that lookup silently failed and coverage
// dates were always "N/A". This instead finds the Eligibility table by its "Coverage Dates"
// header text (not the fixed 'table.Eligibility' class) and reads the dates directly.
function getEligibilityCoverageDates() {
  const memberName = getLabelValue(".SubscriberProfile", "Member Name");
  const tables = Array.from(document.querySelectorAll("table"));

  for (const table of tables) {
    const headerCells = Array.from(
      table.querySelectorAll("thead th, thead td"),
    );
    if (headerCells.length === 0) continue;
    const headerLabels = headerCells.map((c) =>
      clean(c.textContent).toLowerCase(),
    );
    const dateColIdx = headerLabels.findIndex((t) =>
      t.includes("coverage dates"),
    );
    if (dateColIdx === -1) continue;

    const rows = Array.from(table.querySelectorAll("tbody tr"));
    if (rows.length === 0) continue;

    // Prefer the row matching this specific member (handles family plans with multiple
    // dependents listed in the same table); otherwise fall back to the first data row.
    // Per the task, we deliberately do NOT match by subscriber name here.
    let targetRow = null;
    if (memberName && memberName !== "N/A") {
      targetRow = rows.find((r) =>
        Array.from(r.querySelectorAll("td")).some(
          (c) =>
            clean(c.textContent).toUpperCase() === memberName.toUpperCase(),
        ),
      );
    }
    if (!targetRow) targetRow = rows[0];

    const cells = targetRow.querySelectorAll("td");
    if (cells[dateColIdx]) return clean(cells[dateColIdx].textContent);
  }

  // Legacy fallback in case the header-text lookup above ever fails
  const legacyTable = document.querySelector("table.Eligibility");
  if (legacyTable) {
    const row = legacyTable.querySelector("tbody tr");
    if (row) {
      const cells = row.querySelectorAll("td");
      if (cells.length) return clean(cells[cells.length - 1].textContent);
    }
  }

  return "N/A";
}

function extractPayorId(text) {
  const match = clean(text).match(
    /\b(?:Delta Dental\s+)?(?:payer|payor)\s+ID\b(?:\s+number)?\s*(?:is\s*)?[:#]?\s*([A-Z0-9-]+)\b/i,
  );
  return match ? match[1] : null;
}

async function collectPayorId() {
  const pagePayorId = extractPayorId(document.body?.textContent || "");
  if (pagePayorId) return pagePayorId;

  const contactLinks = Array.from(document.querySelectorAll("a"))
    .filter((link) => /contact dentist support/i.test(clean(link.textContent)))
    .map((link) => {
      try {
        const url = new URL(link.href, location.href);
        return url.origin === location.origin && /^https?:$/.test(url.protocol)
          ? url.href
          : null;
      } catch (error) {
        console.warn(
          "[DDRI] Could not resolve Contact Dentist Support link",
          error,
        );
        return null;
      }
    })
    .filter((url, index, urls) => url && urls.indexOf(url) === index);

  for (const url of contactLinks) {
    try {
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) {
        console.error(
          `[DDRI] Contact Dentist Support request failed: HTTP ${response.status}`,
        );
        continue;
      }

      const page = new DOMParser().parseFromString(
        await response.text(),
        "text/html",
      );
      const payorId = extractPayorId(page.body?.textContent || "");
      if (payorId) return payorId;
    } catch (error) {
      console.error(
        "[DDRI] Could not retrieve Contact Dentist Support page",
        error,
      );
    }
  }

  return "N/A";
}

async function collectPlan() {
  // MODIFIED: was `getEligibilityRow(getLabelValue('.SubscriberProfile', 'Subscriber Name'))?.dates`
  // -- see getEligibilityCoverageDates() above for why that always returned "N/A".
  const dates = getEligibilityCoverageDates();
  let start = "N/A",
    end = "N/A";
  if (dates && dates !== "N/A") {
    if (dates.includes("-")) {
      [start, end] = dates.split("-").map(clean);
    } else {
      // Single date with no range separator (e.g. termination-only entries) -- keep it
      // as the effective date rather than discarding it.
      start = dates;
    }
  }

  return {
    insurance_name: "Delta Dental of Rhode Island",
    insurance_address: collectClaimsAddress(),
    insurance_phone: "N/A",
    payor_id: await collectPayorId(),
    fee_schedule: "N/A",
    employer_group: getLabelValue(".SubscriberProfile", "Group Name"),
    group_number: getLabelValue(".SubscriberProfile", "Group Number"),
    effective_date: start,
    termination_date: end,
    network_status: getLabelValue(".SubscriberProfile", "Product Name"),
    in_network: "N/A",
    benefit_network_scope: collectBenefitNetworkScope(),
    coverage_type: getLabelValue(".SubscriberProfile", "Coverage Type"),
    plan_type: getLabelValue(".SubscriberProfile", "Plan Type"),
    calendar_year: getPolicyYearValue(),
    plan_year_start: collectPlanYearStart(),
    orthodontic_deductible_amount: "N/A",
    orthodontic_deductible_met_amount: "N/A",
    coordination_of_benefits: "N/A",
    preventive_in_yearly_max: collectPreventiveAnnualMaximumTreatment(),
    major_services_paid_on: collectMajorServicesPaidOn(),
    perio_maintenance_after_srp: "N/A",
    d4341_quadrants: "4",
  };
}

function getBenefitsPageText() {
  return clean(
    [
      document.getElementById("benefits")?.textContent,
      document.body?.textContent,
    ]
      .filter(Boolean)
      .join(" "),
  );
}

function collectPlanYearStart() {
  const calendarYear = getPolicyYearValue();
  const monthMatch = String(calendarYear || "").match(
    /\b(\d{1,2})\/\d{1,2}\/\d{4}\b/,
  );
  const month = monthMatch ? Number(monthMatch[1]) : 0;
  return month >= 1 && month <= 12
    ? new Date(2000, month - 1, 1).toLocaleString("en-US", { month: "long" })
    : "N/A";
}

function collectBenefitNetworkScope() {
  const text = getBenefitsPageText();
  return /summary of your benefit coverage for services received within the Delta Dental network/i.test(
    text,
  )
    ? "In Network"
    : "N/A";
}

function collectPreventiveAnnualMaximumTreatment() {
  return "Yes";
}

function collectClaimsAddress() {
  const text = clean(document.querySelector(".ClaimsDisclaimer")?.textContent);
  const match = text.match(
    /Direct your appeal to Appeals,\s*((?:P\.?\s*O\.?\s*Box)\s*[^,]+,\s*[^,]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)/i,
  );
  return match ? clean(match[1]) : "N/A";
}

function collectMajorServicesPaidOn() {
  const benefitDiv = document.getElementById("benefits") || document;
  const paragraphs = Array.from(benefitDiv.querySelectorAll("p, div, li"));
  for (const paragraph of paragraphs) {
    const text = clean(paragraph.textContent);
    if (
      /crowns,\s*bridges,\s*partials and complete dentures are paid when/i.test(
        text,
      ) &&
      /\bseated\b/i.test(text)
    ) {
      return "Seat Date";
    }
  }
  return "N/A";
}

function collectFinancials() {
  const financials = {
    maximums: [],
    deductibles: [],
  };

  // DDRI renders deductible rows in the same main table as maximums and may
  // repeat a simplified deductible total in the OON table. The main table is
  // authoritative because it contains total + used + remaining.
  const maximumKeys = new Set();
  const deductibleByCategory = new Map();

  const categoryKey = (value) =>
    clean(value).replace(/:\s*$/, "").toLowerCase();
  const isDeductible = (value) => /\bdeductible\b/i.test(clean(value));
  const isMissing = (value) => !value || value === "N/A";

  const keepMoreCompleteDeductible = (entry) => {
    const key = categoryKey(entry.category);
    if (!key) return;

    const existing = deductibleByCategory.get(key);
    if (!existing) {
      deductibleByCategory.set(key, entry);
      return;
    }

    // Never replace a real main-table value with the OON fallback's N/A.
    for (const field of ["total", "used", "remaining"]) {
      if (isMissing(existing[field]) && !isMissing(entry[field])) {
        existing[field] = entry[field];
      }
    }
  };

  const maxRows = document.querySelectorAll(
    "tr.DataTableRow, tr.DataTableOddRow",
  );

  for (const row of maxRows) {
    const catCell = row.querySelector(".MaximumsFreqCategory");
    if (!catCell || !row.querySelector(".MaximumsAmount")) continue;

    const category = clean(catCell.textContent).replace(/:\s*$/, "");
    if (!category) continue;

    const entry = {
      category,
      total: clean(row.querySelector(".MaximumsAmount")?.textContent) || "N/A",
      used:
        clean(row.querySelector(".MaximumsAmountUsed")?.textContent) || "N/A",
      remaining:
        clean(row.querySelector(".MaximumsAmountAvailable")?.textContent) ||
        "N/A",
    };

    if (isDeductible(category)) {
      keepMoreCompleteDeductible(entry);
      continue;
    }

    const key = [entry.category, entry.total, entry.used, entry.remaining]
      .map((value) => clean(value).toLowerCase())
      .join("\u0000");
    if (!maximumKeys.has(key)) {
      maximumKeys.add(key);
      financials.maximums.push(entry);
    }
  }

  // OON deductible values are fallback-only. If the main table already gave
  // us Individual/Family deductible values, do not create a duplicate row.
  const oonTables = document.querySelectorAll(".OONTbl table");
  for (const table of oonTables) {
    for (const row of table.querySelectorAll("tr")) {
      const cells = row.querySelectorAll("td");
      if (cells.length < 2) continue;

      const category = clean(cells[0].textContent).replace(/:\s*$/, "");
      if (!category || !isDeductible(category)) continue;
      if (/family deductible/i.test(category)) continue;

      keepMoreCompleteDeductible({
        category,
        total: clean(cells[1].textContent) || "N/A",
        used: "N/A",
        remaining: "N/A",
      });
    }
  }

  financials.deductibles = Array.from(deductibleByCategory.values());
  const individualDeductible = financials.deductibles.find((entry) =>
    /individual deductible/i.test(entry.category),
  );
  const individualAmount = Number(
    String(individualDeductible?.total || "").replace(/[$,\s]/g, ""),
  );
  if (
    individualDeductible &&
    individualAmount === 0 &&
    (!individualDeductible.used || individualDeductible.used === "N/A")
  ) {
    individualDeductible.used = "0.00";
    individualDeductible.remaining = "0.00";
  }

  // Export only the deductibles the portal states. A family deductible the
  // page does not show is NOT derived here: DCA's plan matcher reads this
  // export too (compare_patients.py, FORMAT D) and would take a derived
  // 3x-individual figure for a stated one -- the guess that was removed from
  // the matcher on 2026-07-15 because it rejected correct plans. The Smile
  // Partners DD RI audit applies its 3x rule itself, in
  // smile_partners/sabrina/carriers/delta_dental_ri/portal.py.
  return financials;
}

function collectFrequencies() {
  const freqs = [];
  const rows = document.querySelectorAll("tr.DataTableRow, tr.DataTableOddRow");
  for (const row of rows) {
    const catCell = row.querySelector(".MaximumsFreqCategory");
    const freqAmtCell = row.querySelector(".FrequencyAmount");
    if (catCell && freqAmtCell) {
      freqs.push({
        category: clean(catCell.textContent),
        used_count: clean(freqAmtCell.textContent) || "N/A",
        next_eligible:
          clean(row.querySelector(".FrequenciesNextElig")?.textContent) ||
          "N/A",
      });
    }
  }
  return freqs;
}

function collectProvisions() {
  const provisions = [];
  const benefitDiv = document.getElementById("benefits");
  if (!benefitDiv) return provisions;

  // MODIFIED: broadened from 'p, div.redBackgroundTextAlignedLeft, .Disclaimer' to a generic
  // set of text-bearing block elements (plus '.Disclaimer' on any tag, kept for back-compat)
  // so this keeps working even if DDRI wraps these notices in a differently-named class.
  const blocks = Array.from(
    benefitDiv.querySelectorAll("p, div, li, td, .Disclaimer"),
  );
  const seen = new Set(); // avoid duplicate entries when a parent/child both match identical cleaned text
  for (const block of blocks) {
    const text = clean(block.textContent);
    if (!text || seen.has(text)) continue;

    if (text.includes("missing tooth clause")) {
      seen.add(text);
      provisions.push({
        rule: "Missing Tooth Clause",
        value: getMissingToothClauseValue(text),
      });
    } else if (text.includes("Dependent children")) {
      // MODIFIED: was an exact-sentence match ("Dependent children are covered"). Now
      // matches ANY paragraph mentioning "Dependent children", since other DDRI plans
      // phrase this notice differently.
      seen.add(text);
      provisions.push({ rule: "Dependent Age Limit", value: text });
    } else if (block.classList.contains("Disclaimer")) {
      seen.add(text);
      provisions.push({ rule: "Disclaimer", value: text });
    }
  }
  return provisions;
}

// DDRI describes this benefit in prose. Return the answer required by the audit instead of
// copying that prose into the JSON. For example, "does not include a missing tooth clause"
// becomes "No"; an affirmative clause becomes "Yes".
function getMissingToothClauseValue(text) {
  const normalized = normalizeText(text);
  if (!normalized.includes("missing tooth clause")) return "N/A";
  if (/\b(no|not|does not|doesnt|without|exclude|excluded)\b/.test(normalized))
    return "No";
  if (/\b(yes|include|included|apply|applies|has|have)\b/.test(normalized))
    return "Yes";
  return "N/A";
}

// Return the missing-tooth-clause answer only; do not emit the complete notice.
function collectMissingToothClause() {
  const benefitDiv = document.getElementById("benefits") || document;
  const elements = Array.from(
    benefitDiv.querySelectorAll("p, div, li, td, .Disclaimer"),
  );
  for (const element of elements) {
    const value = getMissingToothClauseValue(clean(element.textContent));
    if (value !== "N/A") return value;
  }
  return "N/A";
}

// NEW HELPER: fallback for `dependent_age_limit` in case the notice ever sits outside
// div#benefits on a differently structured DDRI page. collectProvisions() (searched first,
// see startCrawl()) already covers the normal case.
function collectDependentAgeLimit() {
  const candidates = Array.from(document.querySelectorAll("p, div, li, td"));
  for (const el of candidates) {
    const text = clean(el.textContent);
    if (text.includes("Dependent children")) return text;
  }
  return "N/A";
}

// NEW HELPER: pulls an age-related clause (e.g. "under age 19") out of a Frequency/Limitations
// string. The new benefit table (see collectBenefitCategories()) doesn't have a dedicated "age
// limit" column — age restrictions are expressed inline in that text — so this is used by
// findLimits() inside collectProcedures() to populate each procedure's age_limit.
// Benefit matching uses descriptions, never CDT codes, so new codes can inherit the
// appropriate plan limitation without a code-specific release.
const BENEFIT_MATCH_DEBUG = false;

function normalizeText(text) {
  return clean(text)
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[–—]/g, "-")
    .replace(/\bx[ -]?rays?\b|\bradiographs?\b|\bfilms?\b/g, " xray ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function tokenize(text) {
  return normalizeText(text)
    .split(/\s+/)
    .filter(Boolean)
    .map((token) =>
      token.length > 3 && token.endsWith("ies")
        ? `${token.slice(0, -3)}y`
        : token.length > 3 && token.endsWith("s") && !token.endsWith("ss")
          ? token.slice(0, -1)
          : token,
    );
}

function removeStopWords(tokens) {
  const words = new Set([
    "a",
    "an",
    "and",
    "or",
    "the",
    "of",
    "to",
    "for",
    "with",
    "on",
    "in",
    "by",
    "per",
    "procedure",
    "service",
    "treatment",
    "dental",
    "teeth",
    "tissue",
    "existing",
    "other",
    "related",
    "following",
    "active",
    "natural",
    "permanent",
    "adult",
    "child",
    "children",
  ]);
  return tokens.filter((token) => !words.has(token));
}

// Canonical clinical concepts make equivalent wording comparable while retaining the original
// benefit row as the source of all returned values.
function expandSynonyms(tokens) {
  const aliases = {
    evaluation: "exam",
    examination: "exam",
    exam: "exam",
    oralexam: "exam",
    prophylaxi: "cleaning",
    prophy: "cleaning",
    cleaning: "cleaning",
    fluorid: "fluoride",
    fluoride: "fluoride",
    composite: "filling",
    resin: "filling",
    amalgam: "filling",
    filling: "filling",
    restoration: "filling",
    denture: "denture",
    partial: "denture",
    complete: "denture",
    prosthesi: "denture",
    implant: "implantprosthetic",
    abutment: "implantprosthetic",
    pontic: "implantprosthetic",
    bridge: "implantprosthetic",
    scaling: "periodontaltherapy",
    planing: "periodontaltherapy",
    srp: "periodontaltherapy",
    endodontic: "rootcanal",
    endo: "rootcanal",
    canal: "rootcanal",
    orthodontic: "orthodontic",
    brace: "orthodontic",
    extraction: "extraction",
    extract: "extraction",
    surgery: "extraction",
    anesthesia: "sedation",
    anaesthesia: "sedation",
    sedation: "sedation",
    intravenous: "sedation",
    reline: "reline",
    rebas: "reline",
    repair: "repair",
    gingivectomy: "gingivectomy",
    osseou: "osseous",
    graft: "graft",
    lengthening: "lengthening",
    maintainer: "maintainer",
    maintenance: "maintenance",
    palliative: "palliative",
  };
  return tokens.map((token) => {
    // Periapical and occlusal images are represented by the generic single-image benefit row.
    if (token === "periapical" || token === "occlusal" || token === "single")
      return "singleimage";
    return aliases[token] || token;
  });
}

function getMatchTokens(text) {
  // Resolve multi-word concepts before tokenization, making word order and punctuation harmless.
  const phrases = normalizeText(text)
    .replace(/oral\s+(evaluation|examination|exam)/g, " oralexam ")
    .replace(/root\s+canal/g, " rootcanal ")
    .replace(/root\s+planing/g, " periodontaltherapy ")
    .replace(
      /complete\s+(series|set)\s+(of\s+)?(xray|images?)/g,
      " fullxrayseries ",
    )
    .replace(/panoramic\s+(xray|image)/g, " panoramic fullxrayseries ")
    .replace(/bitewing\s+(xray|image)/g, " bitewing ")
    .replace(/implant\s+(crown|bridge)/g, " implantprosthetic ");
  return expandSynonyms(removeStopWords(tokenize(phrases)));
}

function calculateSimilarity(procedureText, benefitText) {
  const procedureTokens = [...new Set(getMatchTokens(procedureText))];
  const benefitTokens = [...new Set(getMatchTokens(benefitText))];
  if (!procedureTokens.length || !benefitTokens.length) return 0;
  const benefitSet = new Set(benefitTokens);
  const common = procedureTokens.filter((token) => benefitSet.has(token));
  if (!common.length) return 0;
  const procedureCoverage = common.length / procedureTokens.length;
  const benefitCoverage = common.length / benefitTokens.length;
  const jaccard =
    common.length / new Set([...procedureTokens, ...benefitTokens]).size;
  return Number(
    (0.65 * procedureCoverage + 0.25 * benefitCoverage + 0.1 * jaccard).toFixed(
      4,
    ),
  );
}

// Return only an age restriction, not the entire frequency/limitations sentence.
function extractAgeLimit(text) {
  if (!text) return "N/A";
  const source = clean(text);
  const number =
    "(?:\\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|twenty[ -]one|twenty[ -]two|twenty[ -]three|twenty[ -]four|twenty[ -]five|twenty[ -]six)";
  const patterns = [
    new RegExp(
      `\\b(?:dependent\\s+)?children\\s+(?:under|through|to)\\s+(?:the\\s+)?(?:age\\s+(?:of\\s+)?)?${number}\\b`,
      "i",
    ),
    new RegExp(
      `\\bstudents?\\s+(?:through|to|under)\\s+(?:the\\s+)?(?:age\\s+(?:of\\s+)?)?${number}\\b`,
      "i",
    ),
    new RegExp(
      `\\b(?:under|younger\\s+than)\\s+(?:the\\s+)?(?:age\\s+(?:of\\s+)?)?${number}\\b`,
      "i",
    ),
    new RegExp(`\\b(?:through|to)\\s+age\\s+(?:of\\s+)?${number}\\b`, "i"),
    new RegExp(`\\bage\\s+(?:of\\s+)?${number}\\b`, "i"),
    /\bdependent children\b/i,
  ];
  const match = patterns.map((pattern) => source.match(pattern)).find(Boolean);
  return match ? clean(match[0]) : "N/A";
}

function findBestBenefitMatch(
  description,
  benefitCategories,
  threshold = 0.45,
) {
  let best = null;
  for (const category of benefitCategories) {
    for (const service of category.services || []) {
      const similarity = calculateSimilarity(description, service.procedure);
      if (!best || similarity > best.similarity)
        best = { service, category: category.category, similarity };
    }
  }
  return best && best.similarity >= threshold ? best : null;
}

function findBenefitServiceForCode(code, benefitCategories) {
  const labels = BENEFIT_SERVICES_BY_CODE[String(code || "").toUpperCase()];
  if (!labels) return null;
  const expected = new Set(labels.map(normalizeText));
  const matches = [];
  for (const category of benefitCategories || []) {
    for (const service of category.services || []) {
      if (expected.has(normalizeText(service.procedure))) {
        matches.push({ service, category: category.category });
      }
    }
  }
  return matches.length === 1 ? matches[0] : null;
}

function normalizeFrequency(value) {
  const source = clean(value);
  if (!source || /^n\/?a$/i.test(source)) return "N/A";
  if (
    /^(?:as required|frequency not available|no frequency|no limitations?|unlimited|none)$/i.test(
      source,
    )
  ) {
    return "No Frequency";
  }

  const countWords = {
    once: 1,
    one: 1,
    twice: 2,
    two: 2,
    thrice: 3,
    three: 3,
    four: 4,
    five: 5,
    six: 6,
    seven: 7,
    eight: 8,
    nine: 9,
    ten: 10,
  };
  const countPattern =
    "(once|one|twice|two|thrice|three|four|five|six|seven|eight|nine|ten|\\d+)";
  const countOf = (value) =>
    /^\d+$/.test(value) ? Number(value) : countWords[value];

  const lifetime = source.match(
    new RegExp(
      `\\b${countPattern}\\b.*?\\bper\\s+(?:tooth\\s+)?lifetime\\b`,
      "i",
    ),
  );
  if (lifetime) return `${countOf(lifetime[1].toLowerCase())}XLifetime`;

  const interval = source.match(
    new RegExp(
      `\\b${countPattern}\\b(?:\\s+(?:times?|sets?|procedures?))?` +
        `\\s+(?:in|per|every)\\s+(?:(?:site|quadrant|tooth|arch)\\s+)?` +
        `(?:(?:every)\\s+)?(?:(?:calendar|contract|plan|benefit|policy)\\s+)?` +
        `(?:(\\d+)\\s*)?(years?|months?|weeks?|days?)\\b`,
      "i",
    ),
  );
  if (!interval) return source;

  const count = countOf(interval[1].toLowerCase());
  const span = Number(interval[2] || 1);
  const unit = interval[3].toLowerCase().replace(/s$/, "");
  const displayUnit =
    unit === "year"
      ? "Year"
      : unit === "month"
        ? "Months"
        : unit === "week"
          ? "Weeks"
          : "Days";
  return `${count}X${span}${displayUnit}`;
}

function frequencyTextForCode(code, value) {
  const source = clean(value);
  if (code === "D1510") {
    const unilateral = source.match(/\bUnilateral\b.*?(?=\bBilateral\b|$)/i);
    if (unilateral) return unilateral[0];
  } else if (code === "D1516") {
    const bilateral = source.match(/\bBilateral\b.*$/i);
    if (bilateral) return bilateral[0];
  }
  return source;
}

// NEW HELPER (replaces the old `benefitDiv.querySelector('table')`, which grabbed whichever
// table happened to appear FIRST inside #benefits). #benefits actually contains 3 tables in
// order: a small Deductibles table, the hidden Procedure Code Look-up form table, and finally
// the real benefit table -- so the old code was always scraping the wrong (Deductibles) table.
// This instead finds the table by its header text ("Procedure" + "Frequency"/"Limitations"),
// which is stable even if DDRI changes class names or table order.
function findBenefitTable() {
  const container = document.getElementById("benefits") || document;
  const tables = Array.from(container.querySelectorAll("table"));

  // Primary: match on <thead> header text
  for (const table of tables) {
    const headerCells = Array.from(
      table.querySelectorAll("thead th, thead td"),
    );
    if (headerCells.length === 0) continue;
    const headerText = headerCells
      .map((c) => clean(c.textContent).toLowerCase())
      .join(" | ");
    if (
      headerText.includes("procedure") &&
      (headerText.includes("frequency") || headerText.includes("limitation"))
    ) {
      return table;
    }
  }

  // Fallback: some markup variants may not use a <thead> tag at all -- check each table's
  // first row instead.
  for (const table of tables) {
    const firstRow = table.querySelector("tr");
    if (!firstRow) continue;
    const text = clean(firstRow.textContent).toLowerCase();
    if (
      text.includes("procedure") &&
      (text.includes("frequency") || text.includes("limitation"))
    ) {
      return table;
    }
  }

  return null;
}

function collectBenefitCategories() {
  const categories = [];
  const table = findBenefitTable();
  if (!table) return categories;

  let rows = Array.from(table.querySelectorAll("tbody tr"));
  if (rows.length === 0) rows = Array.from(table.querySelectorAll("tr"));

  let currentCat = null;
  for (const row of rows) {
    const cells = Array.from(row.querySelectorAll("td"));
    if (cells.length === 0) continue; // header row (th only) or an empty spacer row

    // MODIFIED: section header rows (DIAGNOSTIC, PREVENTIVE, ...) render as a single cell
    // spanning the full table width via colspan. This structural signal replaces the old
    // hardcoded '.TRhBEN' class check, so it survives markup/class changes.
    const spanningCell = cells.find(
      (c) => parseInt(c.getAttribute("colspan") || "1", 10) > 1,
    );
    if (cells.length === 1 || spanningCell) {
      const text = clean((spanningCell || cells[0]).textContent);
      if (text) {
        currentCat = { category: text, services: [] };
        categories.push(currentCat);
      }
      continue;
    }

    // MODIFIED: data rows are [indicator icon (optional), procedure, covered at, waiting
    // period, frequency/limitations]. Some rows have a leading icon-only cell (prior-auth /
    // pre-treatment indicators) and some don't, so anchor from the END of the row (last 4
    // cells) instead of a fixed index -- this replaces the old '.DataTableRow' class check.
    if (!currentCat || cells.length < 4) continue;

    const n = cells.length;
    const procedure = clean(cells[n - 4].textContent);
    if (!procedure) continue;

    currentCat.services.push({
      procedure: procedure,
      covered_at: clean(cells[n - 3].textContent),
      waiting_period: clean(cells[n - 2].textContent),
      frequency_limitations: clean(cells[n - 1].textContent),
      deductible_applies: Array.from(
        cells[n - 3].querySelectorAll("img[alt]"),
      ).some((image) =>
        /deductible applies/i.test(image.getAttribute("alt") || ""),
      )
        ? "Yes"
        : "No",
    });
  }
  return categories;
}

function collectPlanLevelBenefitAnswers(benefitCategories) {
  const deductibleAnswer = (categoryHint) => {
    const services = (benefitCategories || [])
      .filter((category) =>
        normalizeText(category.category).includes(categoryHint),
      )
      .flatMap((category) => category.services || []);
    if (!services.length) return "N/A";
    const answers = new Set(
      services.map((service) => service.deductible_applies || "N/A"),
    );
    return answers.size === 1 ? answers.values().next().value : "Varies";
  };

  const services = (benefitCategories || []).flatMap(
    (category) => category.services || [],
  );
  const waitingPeriods = services.map((service) =>
    normalizeText(service.waiting_period),
  );
  const hasWaitingPeriod = waitingPeriods.some(
    (value) => value && !["n a", "none", "no"].includes(value),
  );
  const allWaitingPeriodsKnown =
    waitingPeriods.length > 0 &&
    waitingPeriods.every((value) => value && value !== "n a");

  return {
    deductible_applies_to_preventive: deductibleAnswer("preventive"),
    deductible_applies_to_diagnostic: deductibleAnswer("diagnostic"),
    waiting_period: hasWaitingPeriod
      ? "Yes"
      : allWaitingPeriodsKnown
        ? "No"
        : "N/A",
  };
}

function populateOrthodonticDeductibles(plan, financials) {
  const entry = (financials.deductibles || []).find((item) =>
    /orthodontic/i.test(item.category || ""),
  );
  plan.orthodontic_deductible_amount =
    entry?.total && entry.total !== "N/A" ? entry.total : "0";
  plan.orthodontic_deductible_met_amount =
    entry?.used && entry.used !== "N/A" ? entry.used : "0";
}

function collectOrthodonticAgeLimit(benefitCategories) {
  const orthodonticServices = (benefitCategories || [])
    .filter((category) => /orthodont/i.test(category.category || ""))
    .flatMap((category) => category.services || []);
  for (const service of orthodonticServices) {
    const ageLimit = extractAgeLimit(service.frequency_limitations);
    if (ageLimit !== "N/A") return ageLimit;
  }
  return "99";
}

function getHiddenParams() {
  return {
    memberId: document.getElementById("MemberId")?.value || "",
    groupNumber: document.getElementById("GroupNumber")?.value || "",
    divisionNumber: document.getElementById("DivisionNumber")?.value || "",
    effectiveDate:
      document.getElementById("SelectedEffectiveDate")?.value || "",
  };
}

async function fetchProcedure(code, params) {
  const rawCode = code.replace(/^D/i, "");
  const txt = (el) =>
    (el?.textContent || "")
      .replace(/[\n\r\t]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  // Keep the procedure entry schema complete even when DDRI returns an empty table cell.
  // Property order here is the order used in the generated audit JSON.
  const valueOrNA = (el) => txt(el) || "N/A";
  const createStatusProcedure = (description, coverageStatus) => ({
    procedure_code: code,
    description,
    coverage_status: coverageStatus,
    coverage_percentage: "N/A",
    deductible_applies: "N/A",
    waiting_period: "N/A",
    alternate_benefit: "N/A",
    frequency: "N/A",
    age_limit: "N/A",
    history: [],
  });
  const setStatus = (data, status) =>
    Object.defineProperty(data, "_ddriStatus", {
      value: status,
      enumerable: false,
    });

  // This is deliberately text-based rather than class-based: DDRI has changed the
  // markup around this message, but its wording remains the reliable signal.
  const isNotCoveredResponse = (html) => {
    const text = normalizeText(
      new DOMParser().parseFromString(html || "", "text/html").body
        ?.textContent || html,
    );
    return text.includes(
      "the code you entered is not a covered benefit under this patient s contract",
    );
  };
  const isLookupUnavailableResponse = (html) => {
    const text = normalizeText(
      new DOMParser().parseFromString(html || "", "text/html").body
        ?.textContent || html,
    );
    return text.includes(
      "the procedure code look up feature is not available for this procedure code",
    );
  };

  let procData;

  try {
    const response = await fetch("/BenefitsAndClaims/GetProcedureCode", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "x-validation-header": "DDRI",
      },
      body: `Code=${rawCode}`,
    });
    if (!response.ok) {
      console.error(
        `[DDRI] ${code} - SCRAPE ERROR`,
        `Procedure lookup returned HTTP ${response.status}`,
      );
      return setStatus(
        createStatusProcedure("SCRAPE ERROR", "SCRAPE ERROR"),
        "error",
      );
    }

    const html = await response.text();
    if (isNotCoveredResponse(html)) {
      console.debug(`[DDRI] ${code} - NOT COVERED`);
      const data = createStatusProcedure("N/A", "NOT COVERED");
      data.frequency = "NC";
      return setStatus(data, "not-covered");
    }
    if (isLookupUnavailableResponse(html)) {
      const explicitlyUncovered = LOOKUP_UNAVAILABLE_UNCOVERED_CODES.has(code);
      const data = createStatusProcedure(
        explicitlyUncovered ? "N/A" : "LOOKUP UNAVAILABLE",
        explicitlyUncovered ? "NOT COVERED" : "LOOKUP UNAVAILABLE",
      );
      if (explicitlyUncovered) data.coverage_percentage = "0%";
      data.frequency = "NC";
      return setStatus(data, "lookup-unavailable");
    }

    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");
    const table = doc.getElementById("ProcedureCodeSearchResult");

    if (table) {
      const rows = table.querySelectorAll("tr");
      const requestedCode = code.toUpperCase();
      const headerLabels = new Set([
        "covered at",
        "deductible applies",
        "waiting period",
        "alternate benefit may apply",
        "procedure",
        "cdt code",
      ]);
      const isHeaderLabel = (value) => headerLabels.has(normalizeText(value));

      // DDRI can render its header, explanatory, and data rows using the same TD
      // markup. Identify the result by its actual CDT cell before reading positions.
      const dataRow = Array.from(rows).find((row) => {
        const cells = row.querySelectorAll("td");
        if (
          cells.length < 6 ||
          clean(cells[0].textContent).toUpperCase() !== requestedCode
        ) {
          return false;
        }

        // Never allow column labels from a header-like row into the audit JSON.
        return Array.from(cells)
          .slice(1, 6)
          .every((cell) => !isHeaderLabel(clean(cell.textContent)));
      });
      if (dataRow) {
        const cells = dataRow.querySelectorAll("td");
        procData = {
          procedure_code: code,
          description: valueOrNA(cells[1]),
          coverage_status: "COVERED",
          coverage_percentage: valueOrNA(cells[2]),
          deductible_applies: valueOrNA(cells[3]),
          waiting_period: valueOrNA(cells[4]),
          alternate_benefit: valueOrNA(cells[5]),
          frequency: "N/A",
          age_limit: "N/A",
          history: [],
        };
      }
    }
  } catch (e) {
    console.error(`[DDRI] ${code} - SCRAPE ERROR`, e);
    return setStatus(
      createStatusProcedure("SCRAPE ERROR", "SCRAPE ERROR"),
      "error",
    );
  }

  // If the portal returns a successful response but the requested CDT code is not
  // present in the result, treat that as NOT COVERED rather than SCRAPE ERROR.
  // Actual network/server failures above still remain SCRAPE ERROR.
  if (!procData) {
    console.debug(
      `[DDRI] ${code} - NOT COVERED`,
      "Requested CDT code was not present in the portal response",
    );
    return setStatus(
      createStatusProcedure("N/A", "NOT COVERED"),
      "not-covered",
    );
  }

  setStatus(procData, "covered");
  console.debug(`[DDRI] ${code} - COVERED`);

  try {
    const reqBody = `StartDate=7&ProcedureCode=${rawCode}&ToothNumber=&MemberId=${params.memberId}&GroupNumber=${params.groupNumber}&DivisionNumber=${params.divisionNumber}`;
    const response = await fetch("/BenefitsAndClaims/GetToothHistory", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "x-validation-header": "DDRI",
      },
      body: reqBody,
    });
    const html = await response.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");
    const table = doc.querySelector(".ToothHistorySearchResults");

    if (table) {
      const rows = table.querySelectorAll("tbody tr");
      for (const row of rows) {
        const cells = row.querySelectorAll("td");
        if (cells.length >= 5) {
          const svc_date = txt(cells[2]);
          if (
            svc_date &&
            svc_date !== "NA" &&
            svc_date !== "" &&
            svc_date !== "\u00a0"
          ) {
            procData.history.push({
              service_date: svc_date,
              tooth_number: valueOrNA(cells[3]),
              tooth_surface: valueOrNA(cells[4]),
              history_notes: "NA",
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

async function collectProcedures(requestedCodes = null) {
  const resultsByCode = new Map();
  const params = getHiddenParams();

  if (!params.memberId) {
    throw new Error("No MemberId found. Cannot crawl procedures.");
  }

  const BATCH_SIZE = 10;
  // Preserve caller order while preventing accidental duplicate lookups/results. The normal
  // audit always uses PROCEDURE_CODES, which contains the required 50 CDT codes.
  const codes = [...new Set(requestedCodes || PROCEDURE_CODES)];

  const benefitCats = collectBenefitCategories();

  for (let i = 0; i < codes.length; i += BATCH_SIZE) {
    const batch = codes.slice(i, i + BATCH_SIZE);
    const batchNum = Math.floor(i / BATCH_SIZE) + 1;
    const totalBatches = Math.ceil(codes.length / BATCH_SIZE);
    const pct = Math.round((i / codes.length) * 100);

    broadcastState(
      "FETCHING PROCEDURES",
      "Fetching Procedures",
      `Batch ${batchNum} of ${totalBatches}`,
      pct,
    );

    const batchPromises = batch.map(async (code) => {
      try {
        const data = await fetchProcedure(code, params);
        if (data && ALWAYS_NO_FREQUENCY_CODES.has(code)) {
          data.frequency = "Frequency not available";
          data.frequency_details = "Frequency not available";
          data.frequency_source =
            "Default: no frequency stated for this procedure";
        } else if (
          data &&
          NO_FREQUENCY_CODES.has(code) &&
          ["N/A", "N/C"].includes(String(data.frequency || "").toUpperCase())
        ) {
          data.frequency = "Frequency not available";
          data.frequency_details = "Frequency not available";
          data.frequency_source =
            "Default: no frequency stated for this procedure";
        }
        if (data && data._ddriStatus === "covered") {
          const codeMatch = findBenefitServiceForCode(code, benefitCats);
          const match = findBestBenefitMatch(data.description, benefitCats);

          if (codeMatch) {
            const rawFrequency = frequencyTextForCode(
              code,
              codeMatch.service.frequency_limitations,
            );
            const sourceFrequency =
              rawFrequency ||
              (NO_FREQUENCY_CODES.has(code)
                ? "Frequency not available"
                : "N/A");
            data.frequency_details = sourceFrequency;
            data.frequency = normalizeFrequency(sourceFrequency);
            data.age_limit = extractAgeLimit(sourceFrequency);
            data.frequency_source = codeMatch.service.procedure;
            if (
              ["D1510", "D1206", "D1208"].includes(code) &&
              data.age_limit === "N/A"
            ) {
              data.age_limit = "99";
            }
            if (
              ["D4346", "D9243"].includes(code) &&
              codeMatch.service.covered_at
            ) {
              data.coverage_percentage = codeMatch.service.covered_at;
            }
          }

          if (match) {
            // A code with no verified benefit label keeps the age the closest
            // benefit row states, as every export did before the code table
            // existed. DCA's plan matcher reads age_limit (D8080 among others,
            // which has no label); the Sabrina DD RI audit ignores it, since it
            // reads a code's age only beside a frequency_source.
            if (!codeMatch && data.age_limit === "N/A") {
              data.age_limit = extractAgeLimit(
                match.service.frequency_limitations,
              );
            }
            // Keep the procedure lookup authoritative for coverage and waiting period.
            if (!data.waiting_period || data.waiting_period === "N/A") {
              data.waiting_period = match.service.waiting_period || "N/A";
            }
            if (
              (!data.coverage_percentage ||
                data.coverage_percentage === "N/A") &&
              match.service.covered_at
            ) {
              data.coverage_percentage = match.service.covered_at;
            }
            if (BENEFIT_MATCH_DEBUG) {
              console.debug("[DDRI] Benefit match", {
                procedure: data.description,
                matched: match.service.procedure,
                category: match.category,
                similarity: match.similarity,
                frequency: data.frequency,
              });
            }
          } else if (BENEFIT_MATCH_DEBUG) {
            console.debug("[DDRI] No benefit match", {
              procedure: data.description,
            });
          }
          // A covered code with no verified label keeps frequency "N/A" (not
          // on portal). It is deliberately not turned into "Frequency not
          // available", which the audit reads as "No Frequency".
        }

        return data;
      } catch (error) {
        // A defensive final boundary: no unexpected matching/parsing exception may
        // reject Promise.all and prevent the remaining CDT codes from being crawled.
        console.error(`[DDRI] ${code} - SCRAPE ERROR`, error);
        return {
          procedure_code: code,
          description: "SCRAPE ERROR",
          coverage_status: "SCRAPE ERROR",
          coverage_percentage: "N/A",
          deductible_applies: "N/A",
          waiting_period: "N/A",
          alternate_benefit: "N/A",
          frequency: "N/A",
          age_limit: "N/A",
          history: [],
        };
      }
    });

    const batchResults = await Promise.all(batchPromises);
    batchResults.forEach((r) => {
      if (r) resultsByCode.set(r.procedure_code, r);
    });

    if (i + BATCH_SIZE < codes.length) {
      await sleep(150);
    }
  }

  // Keep exactly one record per requested code and return them in the request order even if
  // concurrent batches complete out of order. The fallback protects the final JSON if an
  // unexpected coding error occurs outside fetchProcedure's own error handling.
  const results = codes.map(
    (code) =>
      resultsByCode.get(code) ||
      setStatus(
        {
          procedure_code: code,
          description: "SCRAPE ERROR",
          coverage_status: "SCRAPE ERROR",
          coverage_percentage: "N/A",
          deductible_applies: "N/A",
          waiting_period: "N/A",
          alternate_benefit: "N/A",
          frequency: "N/A",
          age_limit: "N/A",
          history: [],
        },
        "error",
      ),
  );
  const pano = results.find(
    (procedure) => procedure.procedure_code === "D0330",
  );
  const fullSeries = results.find(
    (procedure) => procedure.procedure_code === "D0210",
  );
  if (
    pano &&
    (!Array.isArray(pano.history) || pano.history.length === 0) &&
    fullSeries &&
    Array.isArray(fullSeries.history) &&
    fullSeries.history.length > 0
  ) {
    pano.history = fullSeries.history.map((entry) => ({ ...entry }));
  }
  return results;
}

function generateJSON(auditData) {
  return {
    ...auditData,
    ddri_data: true,
  };
}

function generatePatientNotesJSON(auditData) {
  const getFin = (catLower) => {
    if (!auditData.financials) return "";
    for (const item of auditData.financials.maximums || []) {
      if (item.category.toLowerCase().includes(catLower))
        return item.used || "";
    }
    return "";
  };

  const getHistory = (code) => {
    if (!auditData.benefit_coverage || !auditData.benefit_coverage.procedures)
      return "";
    const proc = auditData.benefit_coverage.procedures.find(
      (p) => p.procedure_code === code,
    );
    if (!proc || !proc.history || proc.history.length === 0) return "";
    const sorted = [...proc.history].sort(
      (a, b) => new Date(b.service_date) - new Date(a.service_date),
    );
    return sorted[0].service_date;
  };

  return {
    appointment_date: "",
    verified_by: "",
    verification_date: new Date().toLocaleDateString(),
    eligibility_status: auditData.patient?.eligibility_status || "",
    carrier: "DDRI",
    primary_or_secondary: "",
    plan_type: auditData.patient?.plan_type || "",
    patient_assigned_to_office: "",

    individual_maximum_used: getFin("annual max"),
    ortho_maximum_used: getFin("orthodontic"),

    history_periodic_exam_d0120: getHistory("D0120"),
    history_comp_exam_d0150: getHistory("D0150"),
    history_prophy_d1110: getHistory("D1110"),
    history_perio_maint_d4910: getHistory("D4910"),
    history_fmd_d4355: getHistory("D4355"),
    history_fluoride_d1206_d1208: getHistory("D1206") || getHistory("D1208"),
    history_xray_d0274: getHistory("D0274"),
    history_xray_d0210: getHistory("D0210"),
  };
}

async function downloadJSON(data, fileSuffix = "ddri_audit") {
  return new Promise((resolve) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const patient =
      data?.patient?.name?.replace(/[^a-z0-9]/gi, "_")?.toLowerCase() ||
      "patient";
    a.download = `${patient}_${fileSuffix}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setTimeout(resolve, 500);
  });
}

function validatePage() {
  return !!document.querySelector(".SubscriberProfile");
}

async function clearPreviousSession(clearCachedNotes = true) {
  const keysToClear = [
    STORAGE_KEYS.PROGRESS,
    STORAGE_KEYS.AUDIT_CONTEXT,
    "crawl_progress",
    "partial_json",
    "audit_context",
  ];
  if (clearCachedNotes) {
    keysToClear.push(STORAGE_KEYS.CACHED_PATIENT_NOTES);
    keysToClear.push("cached_patient_notes");
  }
  const safeKeys = keysToClear.filter(Boolean);
  await new Promise((resolve) =>
    chrome.storage.local.remove(safeKeys, resolve),
  );
}

let isCrawling = false;
let timeoutHandle = null;

function resetCacheTimeout() {
  if (timeoutHandle) clearTimeout(timeoutHandle);
  timeoutHandle = setTimeout(async () => {
    await clearPreviousSession(true);
    console.log("[DDRI] Cache timeout expired. Cleaned up.");
  }, 60000); // 60 seconds
}

async function startCrawl() {
  if (isCrawling) return;
  isCrawling = true;
  try {
    await clearPreviousSession(true);
    logState("STARTING");
    broadcastState("STARTING", "Initializing...");

    const auditData = {};

    logState("COLLECTING PATIENT");
    broadcastState(
      "COLLECTING PATIENT",
      "Collecting Patient Data",
      "Extracting subscriber info...",
      10,
    );
    auditData.patient = collectPatient();

    logState("COLLECTING PLAN");
    broadcastState(
      "COLLECTING PLAN",
      "Collecting Plan Details",
      "Extracting plan limits...",
      20,
    );
    auditData.plan_details = await collectPlan();

    logState("COLLECTING FINANCIALS");
    broadcastState(
      "COLLECTING FINANCIALS",
      "Collecting Financials",
      "Extracting deductibles and maximums...",
      30,
    );
    auditData.financials = collectFinancials();
    populateOrthodonticDeductibles(
      auditData.plan_details,
      auditData.financials,
    );

    logState("COLLECTING BENEFIT CATEGORIES");
    auditData.benefit_categories = collectBenefitCategories();
    Object.assign(
      auditData.plan_details,
      collectPlanLevelBenefitAnswers(auditData.benefit_categories),
    );
    auditData.plan_details.orthodontic_age_limit = collectOrthodonticAgeLimit(
      auditData.benefit_categories,
    );

    // NEW: collectProvisions() was previously defined but never called, so its output
    // never reached the final JSON. Wiring it in here to populate the two new top-level
    // fields requested: missing_tooth_clause and dependent_age_limit.
    logState("COLLECTING PROVISIONS");
    auditData.missing_tooth_clause = collectMissingToothClause();
    const provisions = collectProvisions();
    auditData.dependent_age_limit =
      provisions.find((p) => p.rule === "Dependent Age Limit")?.value ||
      collectDependentAgeLimit();

    logState("FETCHING PROCEDURES");
    auditData.benefit_coverage = { procedures: await collectProcedures() };
    auditData.plan_details.posterior_composite_downgrade =
      auditData.benefit_coverage.procedures.some(
        (procedure) =>
          /^yes\b/i.test(
            String(procedure.alternate_benefit || "").replace(/^\*\s*/, ""),
          ) && /^D239[1-4]$/i.test(procedure.procedure_code),
      )
        ? "Yes"
        : "No";
    const d2740 = auditData.benefit_coverage.procedures.find(
      (p) => p.procedure_code === "D2740",
    );
    auditData.plan_details.porcelain_posterior_downgrade =
      d2740 && d2740.coverage_status === "COVERED"
        ? /^yes\b/i.test(
            String(d2740.alternate_benefit || "").replace(/^\*\s*/, ""),
          )
          ? "Yes"
          : "No"
        : "N/A";
    logState("GENERATING JSON");
    broadcastState("GENERATING JSON", "Preparing Audit", "Generating JSON...");
    const finalJson = generateJSON(auditData);
    const patientNotes = generatePatientNotesJSON(auditData);

    await new Promise((resolve, reject) =>
      chrome.storage.local.set(
        {
          [STORAGE_KEYS.AUDIT_CONTEXT]: finalJson,
          [STORAGE_KEYS.CACHED_PATIENT_NOTES]: patientNotes,
        },
        () => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }
          resolve();
        },
      ),
    );

    broadcastState("DOWNLOADING", "Downloading DD RI Audit...");
    await downloadJSON(finalJson);
    broadcastState("COMPLETE", "Download Complete", "DD RI audit JSON saved.");

    logState("CLEANUP");
    await clearPreviousSession(false); // Keep cached_patient_notes for subsequent manual download
    resetCacheTimeout();
  } catch (err) {
    logState("FAILED");
    broadcastState("FAILED", "Audit Failed", err.message);
    await clearPreviousSession(true);
  } finally {
    isCrawling = false;
  }
}

async function startLightweightCrawl() {
  if (isCrawling) return;
  isCrawling = true;
  try {
    await clearPreviousSession(true);
    logState("STARTING LIGHTWEIGHT");
    broadcastState("STARTING", "Initializing Patient JSON...");

    const auditData = {};

    auditData.patient = collectPatient();
    auditData.plan_details = await collectPlan();
    auditData.financials = collectFinancials();

    // Patient-note generation also performs the complete benefit crawl so every patient
    // receives the same 50-code audit data before the selected note fields are extracted.
    auditData.benefit_coverage = { procedures: await collectProcedures() };

    const patientNotes = generatePatientNotesJSON(auditData);

    broadcastState("DOWNLOADING", "Downloading Patient JSON...");
    await downloadJSON(patientNotes);

    await clearPreviousSession(true);

    broadcastState("COMPLETE", "Download Complete", "Patient JSON Saved");
  } catch (err) {
    broadcastState("FAILED", "Audit Failed", err.message);
    await clearPreviousSession(true);
  } finally {
    isCrawling = false;
  }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (location.hostname !== "www.deltadentalri.com") return;
  if (request.command === "START_CRAWL") {
    startCrawl();
    sendResponse({ status: "ACK" });
    return true;
  } else if (
    request.command === "GENERATE_PATIENT_JSON" ||
    request.command === "DOWNLOAD_JSON"
  ) {
    chrome.storage.local.get(
      [STORAGE_KEYS.CACHED_PATIENT_NOTES],
      async (result) => {
        const cached = result[STORAGE_KEYS.CACHED_PATIENT_NOTES];
        if (cached) {
          broadcastState("DOWNLOADING", "Downloading Patient JSON...");
          await downloadJSON(cached);
          await clearPreviousSession(true);
          if (timeoutHandle) clearTimeout(timeoutHandle);
          broadcastState("COMPLETE", "Download Complete", "Patient JSON Saved");
        } else {
          startLightweightCrawl();
        }
        sendResponse({ status: "ACK" });
      },
    );
    return true;
  }
});

// Initialization: check if we just loaded a page
logState("READY");
