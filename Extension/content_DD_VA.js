console.log("DD_VA CONTENT SCRIPT INJECTED");

const CDT_CODES = [
  "0120","0180","0140","0150","0274","0210","0330","0220",
  "0364","0431","1110","1120","1206","1351","1510","2391",
  "2740","2950","2962","6750","5110","9110","9222","9230",
  "9243","9310","9944","4341","4355","4346","4910","4381",
  "4260","4249","3310","3330","7140","7210","7240","7953",
  "6010","6056"
];

async function getJson(url, options = {}) {
  const res = await fetch(url, {
    credentials: "include",
    ...options
  });

  return await res.json();
}

function getMemberId() {
  return location.pathname.split("/").pop();
}

function scrapeBenefitsPage() {
  const text = document.body.innerText;

  return {
    patientName: text.match(/Name:\s*(.+)/)?.[1]?.trim(),
    relationship: text.match(/Relationship:\s*(.+)/)?.[1]?.trim(),
    groupName: text.match(/Group Name:\s*(.+)/)?.[1]?.trim(),
    groupNumber: text.match(/Group Number:\s*(.+)/)?.[1]?.trim(),
    benefitPlanName: text.match(/Benefit Plan Name:\s*(.+)/)?.[1]?.trim(),
    coverage: text.match(/Coverage:\s*(.+)/)?.[1]?.trim(),
    product: text.match(/Product:\s*(.+)/)?.[1]?.trim(),
    effectiveDate: text.match(/Effective Date:\s*(.+)/)?.[1]?.trim(),
    status: text.match(/Status:\s*(.+)/)?.[1]?.trim()
  };
}

async function getAccumulators(memberId, benefitPlanId) {
  return getJson(
    `/provider/api/provider-experience/member/accumulators?benefitPlanId=${benefitPlanId}&memberHccId=${memberId}`,
    {
      headers: getAuthHeaders()
    }
  );
}

async function getCommonProcedures(memberId, benefitPlanId) {
  return getJson(
    `/provider/api/provider-experience/member/commonProcedures?benefitPlanId=${benefitPlanId}&memberHccId=${memberId}&networkId=In%20Network%20PPO`
  );
}

async function getNetworks(benefitPlanId) {

  return getJson(
    `/provider/api/provider-experience/benefitPlans/benefitPlanNetworks?benefitPlanHccId=${benefitPlanId}`,
    {
      headers: getAuthHeaders()
    }
  );
}

async function getCoverage(memberId, benefitPlanId, code) {

  return getJson(
    `/provider/api/provider-experience/benefitPlans/procedureSearch` +
    `?procedureCode=D${code}` +
    `&benefitPlanId=${benefitPlanId}` +
    `&memberHccId=${memberId}`,
    {
      headers: getAuthHeaders()
    }
  );
}

function getAuthHeaders() {
  return {
    "Authorization": sessionStorage.getItem("provider_token") ||
sessionStorage.getItem("provider_accesstoken") ||
localStorage.getItem("provider_token") ||
localStorage.getItem("provider_accesstoken"),
    "transactionId": crypto.randomUUID(),
    "healthCareCompanyId": "1",
    "subcompanyId": "1"
  };
}


function scrapeHistoryTablePage() {

  return [...document.querySelectorAll("mat-row")]
    .map(row => {

      const c =
        [...row.querySelectorAll("mat-cell")]
          .map(x => x.innerText.trim());

      return {
        dateOfService: c[0] || "",
        code: c[1] || "",
        procedure: c[2] || "",
        tooth: c[3] || "",
        surface: c[4] || "",
        area: c[5] || ""
      };
    });
}

function getPaginatorNextButton() {
  return document.querySelector(
    'button.mat-paginator-navigation-next, button[aria-label="Next page"]'
  );
}

async function scrapeHistoryTable() {
  const seen = new Set();
  const allRows = [];

  let guard = 0;
  let lastPageSignature = null;

  while (guard < 50) {
    guard++;

    const pageRows = scrapeHistoryTablePage();
    const pageSignature = JSON.stringify(pageRows);

    // Safety valve: if clicking "next" didn't actually change the table
    // (e.g. we're stuck on the last page and the button wasn't truly
    // disabled), stop instead of looping forever.
    if (pageSignature === lastPageSignature) break;
    lastPageSignature = pageSignature;

    for (const row of pageRows) {
      const key = `${row.dateOfService}|${row.code}|${row.tooth}|${row.surface}|${row.area}`;
      if (!seen.has(key)) {
        seen.add(key);
        allRows.push(row);
      }
    }

    const nextBtn = getPaginatorNextButton();
    if (!nextBtn || nextBtn.disabled || nextBtn.getAttribute("aria-disabled") === "true") break;

    nextBtn.click();
    await new Promise(r => setTimeout(r, 1500));
  }

  return allRows;
}

function scrapeLimitationsTable() {

  return [...document.querySelectorAll("table tr")]
    .slice(1)
    .map(r => {

      const c =
        [...r.querySelectorAll("td,th")]
          .map(x => x.innerText.trim());

      return {
        type: c[2] || "",
        allowed: c[3] || "",
        ageLimit: c[4] || "",
        nextAvailable: c[5] || "",
        remaining: c[6] || ""
      };
    });
}
async function clickTab(prefix) {

  window.onbeforeunload = null;

  const tab =
    document.querySelector(`a[aria-label^="${prefix}"]`);

  if (!tab)
    throw new Error(`Tab not found: ${prefix}`);

  tab.click();

  await new Promise(r => setTimeout(r, 2500));
}
async function scrapePatient() {

  const memberId = getMemberId();

  const benefitPlanUrl =
    performance.getEntriesByType("resource")
      .map(r => r.name)
      .find(u =>
        u.includes("/benefitPlans?") &&
        u.includes(memberId)
      );

  console.log("Benefit URL:", benefitPlanUrl);

  const benefitPlanId =
    new URL(benefitPlanUrl)
      .searchParams
      .get("benefitPlanId");

  // BENEFITS TAB
  const benefitPlan = scrapeBenefitsPage();

  // LIMITATIONS TAB
  await clickTab("limitations");
  const limitations = scrapeLimitationsTable();

  // HISTORY TAB
  await clickTab("history");
  await new Promise(r => setTimeout(r, 4000));
  const history = await scrapeHistoryTable();

  // BACKGROUND API DATA
  const accumulators =
    await getAccumulators(memberId, benefitPlanId);

  const networkData =
    await getNetworks(benefitPlanId);

  const commonProcedures = {};

  for (const tier of networkData.tiers) {

  try {

    commonProcedures[tier.networkTierName] =
      await getJson(
        `/provider/api/provider-experience/member/commonProcedures` +
        `?benefitPlanId=${benefitPlanId}` +
        `&memberHccId=${memberId}` +
        `&networkId=${encodeURIComponent(tier.networkTierName)}`,
        {
          headers: getAuthHeaders()
        }
      );

  } catch (e) {

    commonProcedures[tier.networkTierName] = {
      error: e.message
    };

  }
}

const coverageEntries = await Promise.all(

  CDT_CODES.map(async code => {

    try {

      return [
        `D${code}`,
        await getCoverage(memberId, benefitPlanId, code)
      ];

    } catch (e) {

      return [
        `D${code}`,
        { error: e.message }
      ];

    }
  })
);

const coverage = Object.fromEntries(coverageEntries);

const result = {
  memberId,
  benefitPlanId,
  benefitPlan,
  limitations,
  accumulators,
  history,
  commonProcedures,
  coverage
};

console.log(result);

const sanitize = (s) =>
  (s || "")
    .trim()
    .replace(/[^a-z0-9]+/gi, "_")
    .replace(/^_|_$/g, "")
    .toLowerCase();

const patientSlug = sanitize(benefitPlan.patientName) || sanitize(memberId) || "patient";
const filename = `${patientSlug}_dd_va.json`;

const blob = new Blob(
  [JSON.stringify(result, null, 2)],
  { type: "application/json" }
);

const url = URL.createObjectURL(blob);

const a = document.createElement("a");
a.href = url;
a.download = filename;
a.click();

URL.revokeObjectURL(url);
    }
window.scrapePatient = scrapePatient;

console.log(
  "Delta scraper loaded. Run: scrapePatient()"
);

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

    console.log("MESSAGE RECEIVED:", msg);

    if (msg.command === "START_CRAWL") {

        scrapePatient()
            .then(() => sendResponse({ success: true }))
            .catch(err => {
                console.error(err);
                sendResponse({
                    success: false,
                    error: err.message
                });
            });

        return true;
    }
});
