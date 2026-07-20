// ─────────────────────────────────────────────
// FRAME IDENTITY
// ─────────────────────────────────────────────
const IS_C2_FRAME    = window.location.hostname === 'c2.denticon.com';
const IS_A2_OVERVIEW = window.location.href.toLowerCase().includes('advancedpatientoverview');
const IS_C2_OVERVIEW = IS_C2_FRAME && window.location.pathname.toLowerCase().includes('patientoverview');

console.log(`[V22] Loaded on: ${window.location.hostname}${window.location.pathname} | c2=${IS_C2_FRAME} | overview=${IS_A2_OVERVIEW}`);

// ─────────────────────────────────────────────
// 1. HELPERS
// ─────────────────────────────────────────────
const sleep = (ms) => new Promise(res => setTimeout(res, ms));
const clean = (s)  => (s || "").trim().replace(/\s+/g, ' ');

// Simulate cursor activity at a point — a content script can't move the real
// OS cursor, but dispatching mousemove/mouseover onto whatever element sits
// at (x, y) triggers the same hover/lazy-render logic the page wires up.
function simulateMouseAt(x, y) {
    const el = document.elementFromPoint(x, y) || document.body;
    ['mousemove', 'mouseover', 'mouseenter'].forEach(type => {
        el.dispatchEvent(new MouseEvent(type, {
            view: window, bubbles: type !== 'mouseenter', cancelable: true,
            clientX: x, clientY: y
        }));
    });
}

// Wait a random 10–13 s while continuously "moving the cursor" around the
// visible page so slow/lazy-rendered tab content has time (and hover events)
// to fully populate before we scrape it.
async function waitWithMouseMovement(minMs = 10000, maxMs = 13000) {
    const total = minMs + Math.random() * (maxMs - minMs);
    const start = Date.now();
    console.log(`[V22] Waiting ${(total / 1000).toFixed(1)}s with simulated mouse movement...`);
    let x = Math.floor(window.innerWidth / 2);
    let y = Math.floor(window.innerHeight / 2);
    while (Date.now() - start < total) {
        // Drift the cursor in small random steps, clamped to the viewport
        x = Math.min(Math.max(x + Math.floor(Math.random() * 200) - 100, 5), window.innerWidth - 5);
        y = Math.min(Math.max(y + Math.floor(Math.random() * 200) - 100, 5), window.innerHeight - 5);
        simulateMouseAt(x, y);
        await sleep(200 + Math.random() * 300);
    }
}

function findElementByText(text) {
    const tags = ['a', 'span', 'li', 'td', 'div', 'b', 'button'];
    for (let tag of tags) {
        const found = Array.from(document.querySelectorAll(tag))
            .find(el => clean(el.innerText) === text || clean(el.innerText).includes(text));
        if (found) return found;
    }
    return null;
}

function forceClick(el) {
    if (!el) return;
    ['mousedown', 'mouseup', 'click'].forEach(type => {
        el.dispatchEvent(new MouseEvent(type, { view: window, bubbles: true, cancelable: true, buttons: 1 }));
    });
    if (el.tagName?.toLowerCase() === 'a' && el.href?.includes('javascript:')) {
        const script = document.createElement('script');
        script.textContent = el.href.replace('javascript:', '');
        document.documentElement.appendChild(script);
        script.remove();
    } else {
        el.click();
    }
}

const extractBetween = (text, start, end) => {
    const match = text.match(new RegExp(`${start}\\s*(.*?)\\s*${end}`, "i"));
    return match ? clean(match[1]) : "N/A";
};

async function waitForElement(selector, timeout = 15000) {
    return new Promise((resolve, reject) => {
        const interval = setInterval(() => {
            const el = document.querySelector(selector);
            if (el) { clearInterval(interval); resolve(el); }
        }, 500);
        setTimeout(() => { clearInterval(interval); reject("Timeout: " + selector); }, timeout);
    });
}

// ─────────────────────────────────────────────
// 2. SCRAPERS
// ─────────────────────────────────────────────

function buildLabelMap() {
    const map = {};
    Array.from(document.querySelectorAll('.label-inner')).forEach(el => {
        const label = (el.innerText || '').trim();
        if (!label) return;
        const valueContainer = el.parentElement?.nextElementSibling;
        const valueEl = valueContainer?.querySelector('.label-inner-value, div, span');
        const value = (valueEl?.innerText || '').trim();
        if (!(label in map) || (!map[label] && value)) {
            map[label] = value || "";
        }
    });
    return map;
}

function lv(map, label) {
    const val = map[label];
    return (val && val.trim()) ? val.trim() : "N/A";
}

function cleanDuplicatedName(name, nameEl) {
    // Fixes an observed Denticon rendering bug where the last name gets
    // appended a second time at the end, e.g. "WAKEFIELD, KYLE WAKEFIELD"
    // instead of "WAKEFIELD, KYLE". Only strips the trailing word(s) if
    // they exactly match the last name (case-insensitive), so it can't
    // accidentally truncate a legitimate name.
    const m = name.match(/^([A-Za-z'\-]+(?:\s[A-Za-z'\-]+)*),\s*(.+)$/);
    if (!m) return name;
    const last = m[1].trim();
    let first = m[2].trim();
    const escapedLast = last.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const dupRe = new RegExp(`\\s+${escapedLast}$`, 'i');
    if (dupRe.test(first)) {
        // ROOT-CAUSE DIAGNOSTIC — this runs automatically inside whichever
        // frame actually holds the name (Chrome injects content scripts into
        // every matching frame per the manifest), so it captures the real
        // DOM here instead of relying on manually navigating DevTools to the
        // right iframe context. Next time this fires, check the console for
        // this exact tag and read the outerHTML to find what's actually
        // duplicating the text (nested child span, sort-key element, etc.)
        // instead of just patching the symptom going forward.
        console.warn(`[V22][NAME-DUP-DIAGNOSTIC] Frame: ${window.location.hostname} | Raw innerText: ${JSON.stringify(name)}`);
        console.warn(`[V22][NAME-DUP-DIAGNOSTIC] Element outerHTML:`, nameEl?.outerHTML);
        console.warn(`[V22][NAME-DUP-DIAGNOSTIC] Direct text nodes only (excluding nested children):`,
            JSON.stringify(
                Array.from(nameEl?.childNodes || [])
                    .filter(n => n.nodeType === Node.TEXT_NODE)
                    .map(n => n.textContent)
                    .join('')
            )
        );
        console.warn(`[V22][NAME-DUP-DIAGNOSTIC] Child element count:`, nameEl?.children?.length,
            '| Child tags:', Array.from(nameEl?.children || []).map(c => c.tagName));

        first = first.replace(dupRe, '').trim();
        console.warn(`[V22] Stripped duplicated last name from patient name: "${name}" -> "${last}, ${first}"`);
    }
    return `${last}, ${first}`;
}

function scrapePatientOverview() {
    const labels = buildLabelMap();

    const nameEl = Array.from(document.querySelectorAll('span.font-weight-600'))
        .find(el => /^[A-Za-z][A-Za-z'\-]*(\s[A-Za-z'\-]+)*,\s[A-Za-z]/.test((el.innerText || '').trim()));
    const patientName = nameEl ? cleanDuplicatedName(nameEl.innerText.trim(), nameEl) : "N/A";

    const dobEl = Array.from(document.querySelectorAll('span.font-weight-600'))
        .find(el => /^\d{2}\/\d{2}\/\d{4}$/.test((el.innerText || '').trim()));
    const dob = dobEl ? dobEl.innerText.trim() : "N/A";

    const ageSexEl = Array.from(document.querySelectorAll('div, span'))
        .find(el => /^\d+\s*\/\s*(Male|Female)/i.test((el.innerText || '').trim()));
    const ageSex = ageSexEl ? (ageSexEl.innerText || '').trim() : "N/A";

    const idLabelEl = Array.from(document.querySelectorAll('span'))
        .find(el => (el.innerText || '').trim() === 'ID');
    const patientId = idLabelEl?.nextElementSibling
        ? (idLabelEl.nextElementSibling.innerText || '').trim() : "N/A";

    const nextVisitLabelEl = Array.from(document.querySelectorAll('span'))
        .find(el => (el.innerText || '').trim() === 'Next Visit');
    const nextVisit = nextVisitLabelEl?.nextElementSibling
        ? (nextVisitLabelEl.nextElementSibling.innerText || '').trim() : "N/A";

    const phoneLinks = Array.from(document.querySelectorAll('a[href^="tel"]'));
    let patientCell = "N/A";
    for (let link of phoneLinks) {
        const parentText = (link.parentElement?.innerText || '');
        if (parentText.includes('(C)') || parentText.includes('Cell')) {
            patientCell = (link.innerText || '').trim();
            break;
        }
    }
    if (patientCell === "N/A") {
        const allEls = Array.from(document.querySelectorAll('span, div, a'));
        const cEl = allEls.find(el => (el.innerText || '').includes('(C)') && /\d{3}/.test(el.innerText));
        if (cEl) {
            const match = (cEl.innerText || '').match(/\(C\)\s*([\d\-().]+)/);
            if (match) patientCell = match[1].trim();
        }
    }

    const emailLinks = Array.from(document.querySelectorAll('a[href^="mailto"]'));
    const patientEmail = emailLinks.length > 0 ? (emailLinks[0].innerText || '').trim() : "N/A";

    // ── Medical alerts ──
    const alertsEl = Array.from(document.querySelectorAll('div, span'))
        .find(el => (el.className || '').includes('alert') ||
                    (el.id || '').toLowerCase().includes('alert') ||
                    ((el.innerText || '').includes('Amoxicillin') || (el.innerText || '').includes('Allergy')));
    let medAlerts = "N/A";
    if (alertsEl) {
        const alertText = (alertsEl.innerText || '').trim();
        if (alertText.length < 200) medAlerts = alertText;
    }

    const bodyText = document.body.innerText;

    const lastVisitLabelEl = Array.from(document.querySelectorAll('span, div'))
        .find(el => (el.innerText || '').trim() === 'Last Visit');
    const lastVisit = lastVisitLabelEl?.nextElementSibling
        ? (lastVisitLabelEl.nextElementSibling.innerText || '').trim() : "N/A";

    // ── Relation to subscriber: extract from "Subscriber (Rel.)" field ──
    // Value looks like "CORR, DANIEL (Child)" — pull out what's in parens
    const subscriberRel = lv(labels, 'Subscriber (Rel.)');
    const relMatch = subscriberRel.match(/\(([^)]+)\)\s*$/);
    const relationToSubscriber = relMatch ? relMatch[1].trim() : "N/A";
    // Subscriber name is everything before the parens
    const subscriberName = subscriberRel !== "N/A"
        ? subscriberRel.replace(/\s*\([^)]+\)\s*$/, '').trim()
        : "N/A";

    return {
        patient: {
            name:                 patientName,
            dob,
            age_sex:              ageSex,
            patient_id:           patientId,
            cell:                 patientCell,
            email:                patientEmail,
            provider:             lv(labels, 'Provider'),
            hygienist:            lv(labels, 'Hygienist'),
            home_office:          lv(labels, 'Home Office'),
            address:              lv(labels, 'Address'),
            city_state_zip:       lv(labels, 'City, State and Zip'),
            fee_schedule:         lv(labels, 'Fee Sched'),
            first_visit:          lv(labels, 'First Visit'),
            last_visit:           lastVisit,
            next_visit:           nextVisit,
            medical_alerts:       medAlerts
        },
        responsible_party: {
            name:        lv(labels, 'Name'),
            resp_id:     lv(labels, 'Resp ID'),
            type:        lv(labels, 'Type'),
            cell:        lv(labels, 'Cell'),
            home_office: lv(labels, 'Home Office')
        },
        primary_insurance: {
            carrier_name:          lv(labels, 'Carrier Name'),
            group_num:             lv(labels, 'Group #'),
            carrier_phone:         lv(labels, 'Carrier Phone'),
            subscriber_name:       subscriberName,
            relation_to_subscriber: relationToSubscriber,
            indi_max_rem:          lv(labels, 'Indi. Max (Rem.)'),
            indi_ded_rem:          lv(labels, 'Ind. Ded. (Rem.)')
            // sub_id and rp_dob are NOT scraped here — they live in the insurance tab
        }
    };
}

function scrapeHeader(text) {
    return { patient_name: text.split('\n').find(l => /^[A-Z]+,\s[A-Z]/.test(l.trim())) || "N/A" };
}

// ── Scrape SubID and RP BD from the c2 insurance tab header bar ──
// The header bar text looks like:
//   "Responsible  CORR, DANIEL  RP BD 05/18/1978  877-638-3379  SubID397842636"
function scrapeInsuranceHeader() {
    const bodyText = document.body.innerText || '';

    // SubID — immediately followed by digits, no space
    const subIdMatch = bodyText.match(/SubID\s*(\S+)/);
    const subId = subIdMatch ? subIdMatch[1] : "N/A";

    // RP BD — followed by date
    const rpBdMatch = bodyText.match(/RP\s*BD\s+(\d{2}\/\d{2}\/\d{4})/);
    const rpDob = rpBdMatch ? rpBdMatch[1] : "N/A";

    // Carrier phone from header (format: 877-638-3379 near SubID line)
    const carrierPhoneMatch = bodyText.match(/(\d{3}-\d{3}-\d{4})\s*SubID/);
    const carrierPhone = carrierPhoneMatch ? carrierPhoneMatch[1] : "N/A";

    // Responsible-party name — an INDEPENDENT identity signal read directly
    // from this Insurance tab's own header (not from storage/Overview page).
    // Used to auto-detect stale cross-patient storage below, replacing the
    // manual confirm() checkpoint.
    const respNameMatch = bodyText.match(/Responsible\s+([A-Z][A-Za-z'\-]+(?:\s[A-Za-z'\-]+)*,\s*[A-Za-z][A-Za-z'\-]*)/);
    const responsibleName = respNameMatch ? respNameMatch[1].trim() : "N/A";

    // Patient's OWN name, read directly from Denticon's dedicated header
    // span — independent of surrounding text format, which varies patient
    // to patient (nickname in parens sometimes present, sometimes not).
    const patientNameEl = document.querySelector('.patient-header-pat-name');
    const patientName = patientNameEl ? clean(patientNameEl.innerText) : "N/A";

    console.log(`[V22] Insurance header — SubID: ${subId}, RP BD: ${rpDob}, Phone: ${carrierPhone}, Responsible: ${responsibleName}, Patient: ${patientName}`);
    return { subId, rpDob, carrierPhone, responsibleName, patientName };
}

function scrapePlanTab() {
    const raw = buildLabelMap();
    const data = {};
    for (const [label, value] of Object.entries(raw)) {
        data[label] = value && value.trim() ? value.trim() : "N/A";
    }
    return data;
}

function scrapeBenTab() {
    const notesEl = document.querySelector('.plan-notes') || findElementByText("Plan Notes")?.parentElement;

    // Scope to the insurance details modal if present, else fall back to full body.
    const container = document.querySelector('.insurance-details-modal') || document.body;
    const containerText = clean(container.innerText);

    const deductibleMatch = containerText.match(
        /Deductible Information\s*Individual Deductible\s*Family Deductible\s*(\$[\d,]+\.\d{2})\s*(\$[\d,]+\.\d{2})/i
    );
    const maximumMatch = containerText.match(
        /Maximum Information\s*Individual Maximum\s*Family Maximum\s*(\$[\d,]+\.\d{2})\s*(\$[\d,]+\.\d{2})/i
    );
    const orthoMatch = containerText.match(
        /Ortho Max Information\s*Individual Ortho Maximum\s*Lifetime Ortho Benefits\s*(\$[\d,.]+|\S+)\s*(Yes|No)/i
    );

    return {
        notes: notesEl ? clean(notesEl.innerText) : "N/A",
        individual_deductible:    deductibleMatch ? deductibleMatch[1] : "N/A",
        family_deductible:        deductibleMatch ? deductibleMatch[2] : "N/A",
        individual_maximum:       maximumMatch    ? maximumMatch[1]    : "N/A",
        family_maximum:           maximumMatch    ? maximumMatch[2]    : "N/A",
        individual_ortho_maximum: orthoMatch      ? orthoMatch[1]      : "N/A",
        lifetime_ortho_benefits:  orthoMatch      ? orthoMatch[2]      : "N/A"
    };
}

function scrapeCoverageTab() {
    const table = document.querySelector('.coverage-table-content table');
    if (!table) return [];

    const mainRows = table.querySelectorAll('tbody > tr.main-row');

    return Array.from(mainRows).map(r => {
        const cells = Array.from(r.querySelectorAll(':scope > td'));

        const categorySpan = cells[0]?.querySelector('span');
        const category = categorySpan
            ? clean(categorySpan.innerText)
            : clean(cells[0]?.innerText || "");

        const frequencyLimitation = cells[3]?.querySelector('span')
            ? clean(cells[3].querySelector('span').innerText)
            : clean(cells[3]?.innerText || "");

        return {
            category:             category || "N/A",
            ded_waived:           clean(cells[1]?.innerText || "") || "N/A",
            coverage_pct:         clean(cells[2]?.innerText || "") || "N/A",
            frequency_limitation: frequencyLimitation || "N/A",
            age_min:              clean(cells[4]?.innerText || "") || "N/A",
            age_max:              clean(cells[5]?.innerText || "") || "N/A",
            waiting_period:       clean(cells[6]?.innerText || "") || "N/A"
        };
    });
}

function getPlanLinks() {
    const tbody = document.getElementById('searchInsurancePlanTableBody');
    if (!tbody) return [];
    return Array.from(tbody.querySelectorAll('a.show-ins-plan-details'));
}

// ─────────────────────────────────────────────
// 3. BUTTON 1 — DOWNLOAD PATIENT JSON
//    Still available but optional — passive background
//    scraper keeps storage up to date automatically.
// ─────────────────────────────────────────────
async function handleDownloadPatient() {
    if (!IS_C2_OVERVIEW) {
        alert("Please navigate to the Patient Overview page first.");
        return;
    }

    let attempts = 0;
    while (document.querySelectorAll('.label-inner').length < 5 && attempts < 20) {
        await sleep(500);
        attempts++;
    }

    const overview = scrapePatientOverview();
    const payload = {
        denticon_data: {
            ...overview,
            scraped_at: new Date().toISOString(),
            source_url: window.location.href
        }
    };

    chrome.storage.local.set({ audit_context: payload }, () => {
        console.log("[V22] Patient data saved to storage.");
    });

    triggerDownload(payload, `Denticon_Patient_${overview.patient.name}_${Date.now()}.json`, false);
    console.log("[V22] Patient JSON download triggered.");
}

// ─────────────────────────────────────────────
// 4. BUTTON 2 — CRAWL FULL INSURANCE PLAN
//    Runs on: c2.denticon.com insurance tab
//    Scrapes SubID + RP BD from the header here,
//    merges with patient overview from storage,
//    produces one complete JSON.
// ─────────────────────────────────────────────
async function deepCrawlInsurance() {
    if (!IS_C2_FRAME) {
        alert("Please open the Primary Dental insurance tab first, then click Crawl Full Insurance Plan.");
        return;
    }

    console.log("[V22] deepCrawlInsurance() starting...");

    // ── Step 1: Scrape SubID + RP BD from the insurance tab header NOW
    //    (before any modal opens and potentially overwrites the DOM)
    const headerData = scrapeInsuranceHeader();

    // ── Step 2: Get Group # ──
    let groupNum = "";
    const groupInput = document.getElementById('inputCarrierGroup');
    const groupSpan  = document.getElementById('showCarrierGroup');

    if (groupInput && clean(groupInput.value)) {
        groupNum = clean(groupInput.value);
    } else if (groupSpan && clean(groupSpan.innerText)) {
        groupNum = clean(groupSpan.innerText);
    }

    if (!groupNum) {
        groupNum = prompt("Group ID not detected. Please enter the Group # manually:");
    }
    if (!groupNum) {
        console.warn("[V22] No group number. Aborting.");
        return;
    }

    console.log(`[V22] Group # = ${groupNum}`);

    // ── Step 3: Click Q SEARCH ──
    const searchBtn = findElementByText("Q SEARCH") || findElementByText("SEARCH");
    if (!searchBtn) {
        alert("Cannot find the Q SEARCH button. Make sure you are on the Primary Dental insurance tab.");
        return;
    }

    console.log("[V22] Clicking Q SEARCH...");
    forceClick(searchBtn);

    let searchInput;
    try {
        searchInput = await waitForElement('#inpSearchText', 15000);
    } catch (e) {
        alert("Plan search modal did not open in time.");
        return;
    }

    searchInput.value = groupNum;
    searchInput.dispatchEvent(new Event('input',  { bubbles: true }));
    searchInput.dispatchEvent(new Event('change', { bubbles: true }));

    const searchForDdl = document.getElementById('ddlSearchFor') ||
                         document.querySelector('select[id*="SearchFor"]') ||
                         document.querySelector('select[id*="searchFor"]');
    if (searchForDdl) {
        const groupOpt = Array.from(searchForDdl.options).find(o => o.text.toLowerCase().includes('group'));
        if (groupOpt) {
            searchForDdl.value = groupOpt.value;
            searchForDdl.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    await sleep(300);

    let modalSearchClicked = false;
    for (let btn of Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"]'))) {
        const text = clean(btn.innerText || btn.value || "").toUpperCase();
        if (text.includes('SEARCH') && btn !== searchBtn && !text.includes('PATIENT') && !text.includes('BEGINNING')) {
            btn.click();
            modalSearchClicked = true;
            break;
        }
    }
    if (!modalSearchClicked) {
        searchInput.focus();
        searchInput.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, keyCode: 13, key: 'Enter' }));
    }

    // ── Step 4: Wait for plan list ──
    let planLinks = [];
    for (let i = 0; i < 8; i++) {
        await sleep(1500);
        planLinks = getPlanLinks();
        if (planLinks.length > 0) break;
        console.log(`[V22] Waiting for plans... (${i + 1}/8)`);
    }

    if (planLinks.length === 0) {
        alert("Plan list did not load.\n\nWorkaround: Click Q SEARCH manually, wait for the table, then click Crawl again.");
        return;
    }

    // ── Step 5: Loop through every plan ──
    const allPlanAudits = [];

    for (let i = 0; i < planLinks.length; i++) {
        const currentLinks = getPlanLinks();
        if (!currentLinks[i]) continue;

        const planId = clean(currentLinks[i].innerText);
        console.log(`[V22] Auditing plan ${i + 1}/${planLinks.length} — ID: ${planId}`);
        currentLinks[i].click();

        // Give each tab 10–13 s to fully render, jiggling the cursor the
        // whole time so hover/lazy-loaded content actually populates.
        await waitWithMouseMovement();

        const plan = scrapePlanTab();

        const benTab = findElementByText("BEN");
        if (benTab) { benTab.click(); await waitWithMouseMovement(); }
        const ben = scrapeBenTab();

        const covTab = findElementByText("COVERAGE AND LIMITATIONS");
        if (covTab) { covTab.click(); await waitWithMouseMovement(); }
        const cov = scrapeCoverageTab();

        allPlanAudits.push({ ins_plan_id: planId, plan_details: plan, benefits: ben, coverage: cov });

        const cancelBtn = document.getElementById('btnCancel') ||
                          findElementByText("CANCEL") ||
                          findElementByText("CLOSE");
        if (cancelBtn) { cancelBtn.click(); await sleep(2000); }
    }

    // ── Step 6: Merge everything and download ──
    chrome.storage.local.get("audit_context", (result) => {
        const store = result.audit_context || {};
        const existing = store.denticon_data || {};

        // AUTOMATIC IDENTITY CROSS-CHECK (no popup) — the plans we just
        // scraped can only be matched to WHOEVER's identity is currently
        // sitting in storage, since name/DOB/etc. only ever get scraped
        // from the separate Patient Overview page, not this Insurance tab.
        // If staff navigate quickly (Overview -> Insurance tab -> Crawl)
        // without the 3s background poller having a chance to refresh
        // storage for the NEW patient, this would silently staple the new
        // patient's plans onto the PREVIOUS patient's leftover identity.
        //
        // headerData.responsibleName was scraped directly from THIS
        // insurance tab's own header — an identity signal independent of
        // storage. Compare it (loosely, first+last token) against whatever
        // name is in storage. On mismatch, discard the stale identity
        // fields rather than silently attaching them to these plans; the
        // plans themselves are still saved either way.
        function normalizeNameForMatch(name) {
            name = (name || "").trim();
            if (name.includes(",")) {
                const [last, first] = name.split(",", 2);
                name = `${(first || "").trim()} ${last.trim()}`;
            }
            return name.replace(/\s+/g, " ").trim().toUpperCase();
        }
        function looseNameMatch(a, b) {
            const ta = normalizeNameForMatch(a).split(" ").filter(Boolean);
            const tb = normalizeNameForMatch(b).split(" ").filter(Boolean);
            if (!ta.length || !tb.length) return false;
            return ta[0] === tb[0] && ta[ta.length - 1] === tb[tb.length - 1];
        }

        // Compare against the RESPONSIBLE PARTY's stored name specifically —
        // NOT the patient's own name. headerData.responsibleName always comes
        // from the Insurance tab's "Responsible ..." line, which is the
        // subscriber/responsible party, not necessarily the patient (e.g. a
        // dependent child's insurance is under a parent's name). Comparing
        // against patient.name first would falsely flag every dependent
        // patient as a "mismatch" since a child's name never matches their
        // parent's. Fall back to patient.name only if responsible_party.name
        // isn't available (e.g. an adult who is their own subscriber and
        // storage never separately captured a responsible_party name).
        const storedName = existing.responsible_party?.name || existing.patient?.name || "";
        let identityStale = false;
        let identityMissing = false;
        if (!storedName) {
            identityMissing = true;
            console.warn(
            `No identity found in storage (Overview page likely never visited ` +`this session, or not enough time given).`);
        }
        else if (headerData.responsibleName !== "N/A" &&
            !looseNameMatch(headerData.responsibleName, storedName)) {
            identityStale = true;
            console.warn(
                `Identity mismatch — storage held "${storedName}" but this ` +
                `insurance tab's own header says "${headerData.responsibleName}". ` +
                `Discarding stale identity fields for this save; plans are still captured.`
            );
        }
        const identityIncomplete = identityStale || identityMissing;
        const identityBase = identityStale ? {} : existing;

        delete store.metlife_data;
        delete store.benefit_coverage;
        delete store.subscriber_info;

        // Inject SubID and RP DOB into primary_insurance and responsible_party
        // These come from the insurance tab header, not the patient overview
        const primaryIns = identityBase.primary_insurance || {};
        const respParty  = identityBase.responsible_party  || {};

        primaryIns.sub_id = headerData.subId;
        if (headerData.carrierPhone !== "N/A") {
            primaryIns.carrier_phone = headerData.carrierPhone;
        }
        if (!primaryIns.carrier_name && identityBase.primary_insurance?.carrier_name) {
            primaryIns.carrier_name = identityBase.primary_insurance.carrier_name;
        }
        respParty.dob = headerData.rpDob;
        // NOTE: respParty.name should hold the RESPONSIBLE PARTY's own name (e.g.
        // a parent/guardian), never the patient's — keep it untouched here.        
        const patient = identityBase.patient || {};
        if (!patient.name || identityIncomplete) {
            patient.name = headerData.patientName !== "N/A" ? headerData.patientName : (patient.name || "UNKNOWN");
        }   

        store.denticon_data = {
            ...identityBase,
            patient:            patient,
            primary_insurance:  primaryIns,
            responsible_party:  respParty,
            plans:              allPlanAudits,
            total_captured:     allPlanAudits.length,
            crawled_at:         new Date().toISOString(),
            identity_mismatch_warning: identityMissing
            ?   `No Patient Overview data was found for this crawl (page likely never ` +
                `visited this session). Fell back to the patient name read directly ` +
                `from this Insurance tab ("${headerData.patientName}"). Provider, DOB, ` +
                `cell, and email fields are missing — visit this patient's Overview ` +
                `page and re-crawl if those are needed.`
            :identityStale
            ?   `Storage held a different patient's identity at crawl time (stale from a ` +
                `previous patient). Discarded and fell back to the responsible-party name ` +
                `read directly from this Insurance tab ("${headerData.responsibleName}"). ` +
                `Some Patient Overview fields (full patient name, cell, email, provider, etc.) ` +
                `may be missing here — revisit this patient's Overview page and re-crawl if ` +
                `those fields are needed.`
            : undefined
        };

        chrome.storage.local.set({ audit_context: store }, () => {
            const patientName = (
                store.denticon_data?.patient?.name ||
                store.denticon_data?.responsible_party?.name ||
                store.denticon_data?.primary_insurance?.subscriber_name ||
                "Unknown"
            ).replace(/[^a-zA-Z0-9_,. -]/g, '');
            triggerDownload(store, `Denticon_DeepAudit_${patientName}_${Date.now()}.json`, false);
            const warningSuffix = identityMissing
                ? "\n\n⚠ This patient's Overview page hasn't been opened yet this session, so some details (like provider info) are missing. Open this patient's Overview page, wait a few seconds, then re-run the crawl to capture everything."
                : identityStale
                ? "\n\n⚠ Some Overview details (like provider info) couldn't be confirmed for this patient. Open this patient's Overview page, wait a few seconds, then re-run the crawl to capture everything."
                : "";
            alert(`Deep Scrape Complete! Captured ${allPlanAudits.length} plan(s).${warningSuffix}`);
        });
    });
}

// ─────────────────────────────────────────────
// 5. BACKGROUND SCRAPER
//    Passively keeps patient overview in storage
//    so Button 2 can merge with it even if
//    Button 1 was never clicked.
// ─────────────────────────────────────────────
if (IS_A2_OVERVIEW || IS_C2_OVERVIEW) {
    setInterval(() => {
        if (!chrome.runtime?.id) return;
        const text = document.body.innerText;
        if (!text.includes("Carrier Name") && !text.includes("PATIENT INFORMATION")) return;

        // Don't scrape until the name element itself has actually rendered —
        // "Carrier Name"/"PATIENT INFORMATION" text can appear in the page
        // template before patient data has populated, which was letting this
        // fire too early right after login and capture name as blank.
        const nameReady = document.querySelector('span.font-weight-600[title]');
        if (!nameReady) return;

        chrome.storage.local.get("audit_context", (result) => {
            const store = result.audit_context || {};
            const overview = scrapePatientOverview();

            // Never let a blank name overwrite a good name already in storage
            // (e.g. a stray early poll that still came back empty for some
            // other reason) — only update if this scrape actually found one.
            if (overview.patient.name === "N/A" && store.denticon_data?.patient?.name
                    && store.denticon_data.patient.name !== "N/A") {
                overview.patient.name = store.denticon_data.patient.name;
            }

            store.denticon_data = {
                ...store.denticon_data,
                patient:            overview.patient,
                responsible_party:  {
                    ...overview.responsible_party,
                    dob: store.denticon_data?.responsible_party?.dob || "N/A"
                },
                primary_insurance:  {
                    ...overview.primary_insurance,
                    sub_id: store.denticon_data?.primary_insurance?.sub_id || "N/A"
                },
                practice:           overview.practice
            };
            chrome.storage.local.set({ audit_context: store });
        });
    }, 3000);
}

// ─────────────────────────────────────────────
// 6. MESSAGE LISTENER
// ─────────────────────────────────────────────
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

    if (request.command === "DOWNLOAD_PATIENT") {
        handleDownloadPatient();
        sendResponse({ status: "Patient download triggered" });
        return true;
    }

    if (request.command === "START_CRAWL") {
        deepCrawlInsurance();
        sendResponse({ status: "Crawl started" });
        return true;
    }
});

// ─────────────────────────────────────────────
// 7. DOWNLOAD HELPER
// ─────────────────────────────────────────────
function triggerDownload(data, filename, purgeAfter) {
    filename = filename || `Denticon_Audit_${Date.now()}.json`;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url  = window.URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.style.display = 'none';
    a.href     = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);

    if (purgeAfter) {
        chrome.storage.local.remove("audit_context", () => {
            console.log("[V22] Storage purged after download.");
        });
    }
}
// ─────────────────────────────────────────────
// 8. INTERCEPT ECLAIMS MANAGEMENT
//    Forces ClaimConnect to open in normal tab
//    instead of stripped popup window
// ─────────────────────────────────────────────
document.addEventListener("click", function(e) {
    var el = e.target.closest("a.menuItem");
    if (!el) return;
    if (!el.innerText.includes("EClaims Management")) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    window.open("https://" + window.location.host + "/ASPX/Utilities/EClaims.aspx", "_blank");
}, true);