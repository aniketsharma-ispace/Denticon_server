// // // content_denticon.js - V21 (Two-Button Clean Build)

// // // ─────────────────────────────────────────────
// // // FRAME IDENTITY
// // // ─────────────────────────────────────────────
// // const IS_C2_FRAME     = window.location.hostname === 'c2.denticon.com';
// // const IS_A2_OVERVIEW  = window.location.href.toLowerCase().includes('advancedpatientoverview.aspx');
// // // c2 loads the overview at /PatientOverview/Index
// // const IS_C2_OVERVIEW  = IS_C2_FRAME && window.location.pathname.toLowerCase().includes('patientoverview');

// // console.log(`[V21] Loaded on: ${window.location.hostname}${window.location.pathname} | c2=${IS_C2_FRAME} | overview=${IS_A2_OVERVIEW}`);

// // // ─────────────────────────────────────────────
// // // 1. HELPERS
// // // ─────────────────────────────────────────────
// // const sleep = (ms) => new Promise(res => setTimeout(res, ms));
// // const clean = (s)  => (s || "").trim().replace(/\s+/g, ' ');

// // function findElementByText(text) {
// //     const tags = ['a', 'span', 'li', 'td', 'div', 'b', 'button'];
// //     for (let tag of tags) {
// //         const found = Array.from(document.querySelectorAll(tag))
// //             .find(el => clean(el.innerText) === text || clean(el.innerText).includes(text));
// //         if (found) return found;
// //     }
// //     return null;
// // }

// // function forceClick(el) {
// //     if (!el) return;
// //     ['mousedown', 'mouseup', 'click'].forEach(type => {
// //         el.dispatchEvent(new MouseEvent(type, { view: window, bubbles: true, cancelable: true, buttons: 1 }));
// //     });
// //     if (el.tagName?.toLowerCase() === 'a' && el.href?.includes('javascript:')) {
// //         const script = document.createElement('script');
// //         script.textContent = el.href.replace('javascript:', '');
// //         document.documentElement.appendChild(script);
// //         script.remove();
// //     } else {
// //         el.click();
// //     }
// // }

// // const extractBetween = (text, start, end) => {
// //     const match = text.match(new RegExp(`${start}\\s*(.*?)\\s*${end}`, "i"));
// //     return match ? clean(match[1]) : "N/A";
// // };

// // async function waitForElement(selector, timeout = 15000) {
// //     return new Promise((resolve, reject) => {
// //         const interval = setInterval(() => {
// //             const el = document.querySelector(selector);
// //             if (el) { clearInterval(interval); resolve(el); }
// //         }, 500);
// //         setTimeout(() => { clearInterval(interval); reject("Timeout: " + selector); }, timeout);
// //     });
// // }

// // // ─────────────────────────────────────────────
// // // 2. SCRAPERS
// // // ─────────────────────────────────────────────

// // // Core helper: build a label→value map from all .label-inner elements on the page.
// // // Returns first non-empty value for each label (avoids duplicates from secondary/tertiary insurance).
// // function buildLabelMap() {
// //     const map = {};
// //     Array.from(document.querySelectorAll('.label-inner')).forEach(el => {
// //         const label = (el.innerText || '').trim();
// //         if (!label) return;
// //         // Value is in parent's next sibling, inside .label-inner-value or any div/span
// //         const valueContainer = el.parentElement?.nextElementSibling;
// //         const valueEl = valueContainer?.querySelector('.label-inner-value, div, span');
// //         const value = (valueEl?.innerText || '').trim();
// //         // Only store first non-empty hit per label
// //         if (!(label in map) || (!map[label] && value)) {
// //             map[label] = value || "";
// //         }
// //     });
// //     return map;
// // }

// // // Get a value from the label map, return "N/A" if missing/empty
// // function lv(map, label) {
// //     const val = map[label];
// //     return (val && val.trim()) ? val.trim() : "N/A";
// // }

// // function scrapePatientOverview() {
// //     const labels = buildLabelMap();

// //     // ── Patient name: find LAST, FIRST A pattern in page ──
// //     const nameEl = Array.from(document.querySelectorAll('div, span'))
// //         .find(el => el.children.length === 0 && /^[A-Z]{2,},\s[A-Z]/.test((el.innerText || '').trim()));
// //     const patientName = nameEl ? (nameEl.innerText || '').trim() : "N/A";

// //     // ── DOB: span.font-weight-600 with birthday cake icon sibling ──
// //     const dobEl = Array.from(document.querySelectorAll('span.font-weight-600'))
// //         .find(el => /^\d{2}\/\d{2}\/\d{4}$/.test((el.innerText || '').trim()));
// //     const dob = dobEl ? dobEl.innerText.trim() : "N/A";

// //     // ── Age/Sex: div containing "/ Female" or "/ Male" ──
// //     const ageSexEl = Array.from(document.querySelectorAll('div, span'))
// //         .find(el => /^\d+\s*\/\s*(Male|Female)/i.test((el.innerText || '').trim()));
// //     const ageSex = ageSexEl ? (ageSexEl.innerText || '').trim() : "N/A";

// //     // ── Patient ID: span after "ID" label ──
// //     const idLabelEl = Array.from(document.querySelectorAll('span'))
// //         .find(el => (el.innerText || '').trim() === 'ID');
// //     const patientId = idLabelEl?.nextElementSibling
// //         ? (idLabelEl.nextElementSibling.innerText || '').trim()
// //         : "N/A";

// //     // ── Next Visit: span after "Next Visit" label ──
// //     const nextVisitLabelEl = Array.from(document.querySelectorAll('span'))
// //         .find(el => (el.innerText || '').trim() === 'Next Visit');
// //     const nextVisit = nextVisitLabelEl?.nextElementSibling
// //         ? (nextVisitLabelEl.nextElementSibling.innerText || '').trim()
// //         : "N/A";

// //     // ── Cell phone: find phone link near "(C)" text ──
// //     const phoneLinks = Array.from(document.querySelectorAll('a[href^="tel"]'));
// //     let patientCell = "N/A";
// //     for (let link of phoneLinks) {
// //         const parentText = (link.parentElement?.innerText || '');
// //         if (parentText.includes('(C)') || parentText.includes('Cell')) {
// //             patientCell = (link.innerText || '').trim();
// //             break;
// //         }
// //     }
// //     // Fallback: any phone number near "(C)" text node
// //     if (patientCell === "N/A") {
// //         const allEls = Array.from(document.querySelectorAll('span, div, a'));
// //         const cEl = allEls.find(el => (el.innerText || '').includes('(C)') && /\d{3}/.test(el.innerText));
// //         if (cEl) {
// //             const match = (cEl.innerText || '').match(/\(C\)\s*([\d\-().]+)/);
// //             if (match) patientCell = match[1].trim();
// //         }
// //     }

// //     // ── Email: mailto link ──
// //     const emailLinks = Array.from(document.querySelectorAll('a[href^="mailto"]'));
// //     const patientEmail = emailLinks.length > 0 ? (emailLinks[0].innerText || '').trim() : "N/A";

// //     // ── Medical alerts: find the alerts container ──
// //     const alertsEl = Array.from(document.querySelectorAll('div, span'))
// //         .find(el => (el.className || '').includes('alert') ||
// //                     (el.id || '').toLowerCase().includes('alert') ||
// //                     ((el.innerText || '').includes('Amoxicillin') || (el.innerText || '').includes('Allergy')));
// //     let medAlerts = "N/A";
// //     if (alertsEl) {
// //         // Get just the alert names, not surrounding UI text
// //         const alertText = (alertsEl.innerText || '').trim();
// //         if (alertText.length < 200) medAlerts = alertText;
// //     }

// //     // ── PGID / OID from page text ──
// //     const bodyText = document.body.innerText;
// //     const pgid = bodyText.match(/PGID\s*:\s*(\d+)/)?.[1] || "N/A";
// //     const oid  = bodyText.match(/OID\s*:\s*(\d+)/)?.[1]  || "N/A";

// //     // ── Last Visit: look for it in the page ──
// //     const lastVisitLabelEl = Array.from(document.querySelectorAll('span, div'))
// //         .find(el => (el.innerText || '').trim() === 'Last Visit');
// //     const lastVisit = lastVisitLabelEl?.nextElementSibling
// //         ? (lastVisitLabelEl.nextElementSibling.innerText || '').trim()
// //         : "N/A";

// //     // ── RP Birth Date: "RP BD" label followed by date ──
// //     // ── RP Birth Date ──
// //     const rpBdMatch = (document.body.innerText || '').match(/RP\s*BD\s*(\d{2}\/\d{2}\/\d{4})/);
// //     const rpBirthDate = rpBdMatch ? rpBdMatch[1] : "N/A";

// //     // ── SubID: no space between label and digits ──
// //     const subIdMatch = (document.body.innerText || '').match(/SubID(\d+)/);
// //     const subId = subIdMatch ? subIdMatch[1] : "N/A";

// //     return {
// //         patient: {
// //             name:           patientName,
// //             dob,
// //             age_sex:        ageSex,
// //             patient_id:     patientId,
// //             cell:           patientCell,
// //             email:          patientEmail,
// //             provider:       lv(labels, 'Provider'),
// //             hygienist:      lv(labels, 'Hygienist'),
// //             home_office:    lv(labels, 'Home Office'),
// //             address:        lv(labels, 'Address'),
// //             city_state_zip: lv(labels, 'City, State and Zip'),
// //             fee_schedule:   lv(labels, 'Fee Sched'),
// //             first_visit:    lv(labels, 'First Visit'),
// //             last_visit:     lastVisit,
// //             next_visit:     nextVisit,
// //             medical_alerts: medAlerts
// //         },
// //         responsible_party: {
// //             name:        lv(labels, 'Name'),
// //             resp_id:     lv(labels, 'Resp ID'),
// //             type:        lv(labels, 'Type'),
// //             cell:        lv(labels, 'Cell'),
// //             home_office: lv(labels, 'Home Office'),
// //             dob:         rpBirthDate   // ← ADD THIS
// //         },
// //         primary_insurance: {
// //             carrier_name:  lv(labels, 'Carrier Name'),
// //             group_num:     lv(labels, 'Group #'),
// //             carrier_phone: lv(labels, 'Carrier Phone'),
// //             subscriber:    lv(labels, 'Subscriber (Rel.)'),
// //             sub_id:        subId,       // ← ADD THIS
// //             indi_max_rem:  lv(labels, 'Indi. Max (Rem.)'),
// //             indi_ded_rem:  lv(labels, 'Ind. Ded. (Rem.)')
// //         },
// //         practice: { pgid, oid }
// //     };
// // }

// // // Keep legacy alias
// // function scrapeHeader(text) {
// //     return { patient_name: text.split('\n').find(l => /^[A-Z]+,\s[A-Z]/.test(l.trim())) || "N/A" };
// // }


// // function scrapePlanTab() {
// //     const data = {};
// //     Array.from(document.querySelectorAll('.insurance-details-modal tr, .row')).forEach(r => {
// //         const cells = r.querySelectorAll('td, div');
// //         if (cells.length >= 2) {
// //             const label = clean(cells[0].innerText);
// //             const val   = clean(cells[1].innerText);
// //             if (label && val && label.length < 50) data[label] = val;
// //         }
// //     });
// //     return data;
// // }

// // function scrapeBenTab() {
// //     const notesEl = document.querySelector('.plan-notes') || findElementByText("Plan Notes")?.parentElement;
// //     return {
// //         notes:     notesEl ? clean(notesEl.innerText) : "N/A",
// //         full_text: clean(document.body.innerText).substring(0, 3000)
// //     };
// // }

// // function scrapeCoverageTab() {
// //     return Array.from(document.querySelectorAll('table tr'))
// //         .filter(r => r.innerText.includes('%') || r.innerText.match(/\d+/))
// //         .map(r => {
// //             const cells = Array.from(r.querySelectorAll('td')).map(c => clean(c.innerText));
// //             return {
// //                 category:    cells[0] || "N/A",
// //                 ded_waived:  cells[1] || "N/A",
// //                 coverage_pct:cells[2] || "N/A",
// //                 limitation:  cells[3] || "N/A"
// //             };
// //         });
// // }

// // function getPlanLinks() {
// //     const tbody = document.getElementById('searchInsurancePlanTableBody');
// //     if (!tbody) return [];
// //     return Array.from(tbody.querySelectorAll('a.show-ins-plan-details'));
// // }

// // // ─────────────────────────────────────────────
// // // 3. BUTTON 1 — DOWNLOAD PATIENT JSON
// // //    Runs on: a2 Patient Overview page
// // // ─────────────────────────────────────────────
// // async function handleDownloadPatient() {
// //     // Runs in the c2 overview frame (IS_C2_OVERVIEW) — not the a2 wrapper
// //     if (!IS_C2_OVERVIEW) {
// //         alert("Please navigate to the Patient Overview page first, then click Download Patient JSON.");
// //         return;
// //     }

// //     console.log("[V21] Waiting for page to fully render...");
// //     // Poll until .label-inner elements are present (SPA async render)
// //     let attempts = 0;
// //     while (document.querySelectorAll('.label-inner').length < 5 && attempts < 20) {
// //         await sleep(500);
// //         attempts++;
// //     }
// //     console.log(`[V21] Page ready after ${attempts} polls. label-inner count: ${document.querySelectorAll('.label-inner').length}`);

// //     console.log("[V21] Scraping patient overview via DOM...");

// //      // ── Also wait for SubID to appear in the DOM ──
// //     let subIdAttempts = 0;
// //     while (!/SubID\d+/.test(document.body.innerText) && subIdAttempts < 10) {
// //         await sleep(500);
// //         subIdAttempts++;
// //     }
// //     const overview = scrapePatientOverview();

// //     const payload = {
// //         denticon_data: {
// //             ...overview,
// //             scraped_at: new Date().toISOString(),
// //             source_url: window.location.href
// //         }
// //     };

// //     // Save to storage so popup download button also works
// //     chrome.storage.local.set({ audit_context: payload }, () => {
// //         console.log("[V21] Patient data saved to storage.");
// //     });

// //     // Trigger immediate download
// //     triggerDownload(payload, `Denticon_Patient_${Date.now()}.json`, false); // false = don't purge yet
// //     console.log("[V21] Patient JSON download triggered.");
// // }

// // // ─────────────────────────────────────────────
// // // 4. BUTTON 2 — CRAWL FULL INSURANCE PLAN
// // //    Runs on: c2.denticon.com (inside EditPatientInsuranceIframe)
// // // ─────────────────────────────────────────────
// // async function deepCrawlInsurance() {
// //     if (!IS_C2_FRAME) {
// //         alert("Please open the Primary Dental insurance tab first, then click Crawl Full Insurance Plan.");
// //         return;
// //     }

// //     console.log("[V21] deepCrawlInsurance() starting in c2 frame...");

// //     // ── Get Group # ──
// //     let groupNum = "";
// //     const groupInput = document.getElementById('inputCarrierGroup');
// //     const groupSpan  = document.getElementById('showCarrierGroup');

// //     if (groupInput && clean(groupInput.value)) {
// //         groupNum = clean(groupInput.value);
// //     } else if (groupSpan && clean(groupSpan.innerText)) {
// //         groupNum = clean(groupSpan.innerText);
// //     }

// //     if (!groupNum) {
// //         groupNum = prompt("Group ID not detected. Please enter the Group # manually:");
// //     }
// //     if (!groupNum) {
// //         console.warn("[V21] No group number. Aborting.");
// //         return;
// //     }

// //     console.log(`[V21] Group # = ${groupNum}`);

// //     // ── Click Q SEARCH to open modal ──
// //     const searchBtn = findElementByText("Q SEARCH") || findElementByText("SEARCH");
// //     if (!searchBtn) {
// //         alert("Cannot find the Q SEARCH button. Make sure you are on the Primary Dental insurance tab.");
// //         return;
// //     }

// //     console.log("[V21] Clicking Q SEARCH...");
// //     forceClick(searchBtn);

// //     // ── Wait for modal search input ──
// //     let searchInput;
// //     try {
// //         searchInput = await waitForElement('#inpSearchText', 15000);
// //         console.log("[V21] Modal opened, #inpSearchText found.");
// //     } catch (e) {
// //         alert("Plan search modal did not open in time. Try clicking Q SEARCH manually first, then run Crawl again.");
// //         return;
// //     }

// //     // ── Fill group # and trigger search ──
// //     searchInput.value = groupNum;
// //     searchInput.dispatchEvent(new Event('input',  { bubbles: true }));
// //     searchInput.dispatchEvent(new Event('change', { bubbles: true }));

// //     // Set "Search For" to Group # if dropdown exists
// //     const searchForDdl = document.getElementById('ddlSearchFor') ||
// //                          document.querySelector('select[id*="SearchFor"]') ||
// //                          document.querySelector('select[id*="searchFor"]');
// //     if (searchForDdl) {
// //         const groupOpt = Array.from(searchForDdl.options).find(o => o.text.toLowerCase().includes('group'));
// //         if (groupOpt) {
// //             searchForDdl.value = groupOpt.value;
// //             searchForDdl.dispatchEvent(new Event('change', { bubbles: true }));
// //         }
// //     }

// //     await sleep(300);

// //     // Click the modal's internal search button (not the same Q SEARCH we already clicked)
// //     let modalSearchClicked = false;
// //     for (let btn of Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"]'))) {
// //         const text = clean(btn.innerText || btn.value || "").toUpperCase();
// //         if (text.includes('SEARCH') && btn !== searchBtn && !text.includes('PATIENT') && !text.includes('BEGINNING')) {
// //             btn.click();
// //             modalSearchClicked = true;
// //             console.log("[V21] Modal search button clicked:", text);
// //             break;
// //         }
// //     }
// //     if (!modalSearchClicked) {
// //         searchInput.focus();
// //         searchInput.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, keyCode: 13, key: 'Enter' }));
// //         console.log("[V21] Fallback: Enter key dispatched on search input.");
// //     }

// //     // ── Wait for plan list ──
// //     let planLinks = [];
// //     for (let i = 0; i < 8; i++) {
// //         await sleep(1500);
// //         planLinks = getPlanLinks();
// //         if (planLinks.length > 0) {
// //             console.log(`[V21] Found ${planLinks.length} plans.`);
// //             break;
// //         }
// //         console.log(`[V21] Waiting for plans... (${i + 1}/8)`);
// //     }

// //     if (planLinks.length === 0) {
// //         alert("Plan list did not load.\n\nWorkaround: Click Q SEARCH manually, wait for the table to appear, then click Crawl again.");
// //         return;
// //     }

// //     // ── Loop through every plan ──
// //     const allPlanAudits = [];

// //     for (let i = 0; i < planLinks.length; i++) {
// //         const currentLinks = getPlanLinks();
// //         if (!currentLinks[i]) continue;

// //         const planId = clean(currentLinks[i].innerText);
// //         console.log(`[V21] Auditing plan ${i + 1}/${planLinks.length} — ID: ${planId}`);
// //         currentLinks[i].click();

// //         await sleep(3500);

// //         const plan = scrapePlanTab();

// //         const benTab = findElementByText("BEN");
// //         if (benTab) { benTab.click(); await sleep(2000); }
// //         const ben = scrapeBenTab();

// //         const covTab = findElementByText("COVERAGE AND LIMITATIONS");
// //         if (covTab) { covTab.click(); await sleep(2000); }
// //         const cov = scrapeCoverageTab();

// //         allPlanAudits.push({ ins_plan_id: planId, plan_details: plan, benefits: ben, coverage: cov });

// //         const cancelBtn = document.getElementById('btnCancel') ||
// //                           findElementByText("CANCEL") ||
// //                           findElementByText("CLOSE");
// //         if (cancelBtn) { cancelBtn.click(); await sleep(2000); }
// //     }

// //     // ── Save + export ──
// //     chrome.storage.local.get("audit_context", (result) => {
// //         const store = result.audit_context || {};
// //         store.denticon_data = {
// //             ...(store.denticon_data || {}),
// //             plans:           allPlanAudits,
// //             total_captured:  allPlanAudits.length,
// //             crawled_at:      new Date().toISOString()
// //         };
// //         chrome.storage.local.set({ audit_context: store }, () => {
// //             triggerDownload(store, `Denticon_DeepAudit_${Date.now()}.json`, true);
// //             alert(`Deep Scrape Complete! Captured ${allPlanAudits.length} plans.`);
// //         });
// //     });
// // }

// // // ─────────────────────────────────────────────
// // // 5. BACKGROUND SCRAPER (passive, overview only)
// // // ─────────────────────────────────────────────
// // if (IS_A2_OVERVIEW || IS_C2_OVERVIEW) {
// //     setInterval(() => {
// //         if (!chrome.runtime?.id) return;
// //         const text = document.body.innerText;
// //         if (text.includes("Carrier Name") || text.includes("PATIENT INFORMATION")) {
// //             chrome.storage.local.get("audit_context", (result) => {
// //                 const store = result.audit_context || {};
// //                 const overview = scrapePatientOverview();
// //                 store.denticon_data = { ...store.denticon_data, ...overview };
// //                 chrome.storage.local.set({ audit_context: store });
// //             });
// //         }
// //     }, 3000);
// // }

// // // ─────────────────────────────────────────────
// // // 6. MESSAGE LISTENER
// // // ─────────────────────────────────────────────
// // chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

// //     // Button 1: Download Patient JSON
// //     if (request.command === "DOWNLOAD_PATIENT") {
// //         handleDownloadPatient();
// //         sendResponse({ status: "Patient download triggered" });
// //         return true;
// //     }

// //     // Button 2: Crawl Full Insurance Plan
// //     if (request.command === "START_CRAWL") {
// //         deepCrawlInsurance();
// //         sendResponse({ status: "Crawl started" });
// //         return true;
// //     }
// // });

// // // ─────────────────────────────────────────────
// // // 7. DOWNLOAD HELPER
// // // ─────────────────────────────────────────────
// // function triggerDownload(data, filename, purgeAfter) {
// //     filename = filename || `Denticon_Audit_${Date.now()}.json`;
// //     const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
// //     const url  = window.URL.createObjectURL(blob);
// //     const a    = document.createElement('a');
// //     a.style.display = 'none';
// //     a.href     = url;
// //     a.download = filename;
// //     document.body.appendChild(a);
// //     a.click();
// //     window.URL.revokeObjectURL(url);
// //     document.body.removeChild(a);

// //     if (purgeAfter) {
// //         chrome.storage.local.remove("audit_context", () => {
// //             console.log("[V21] Storage purged after download.");
// //         });
// //     }
// // }
// // content_denticon.js - V22 (Single-Button Flow)
// // FLOW: Only one button needed — "Crawl Full Insurance Plan"
// // It scrapes the c2 insurance frame (SubID, RP BD from header),
// // pulls patient overview from storage if already saved,
// // and merges everything into one final JSON download.

// // ─────────────────────────────────────────────
// // FRAME IDENTITY
// // ─────────────────────────────────────────────
// const IS_C2_FRAME    = window.location.hostname === 'c2.denticon.com';
// const IS_A2_OVERVIEW = window.location.href.toLowerCase().includes('advancedpatientoverview.aspx');
// const IS_C2_OVERVIEW = IS_C2_FRAME && window.location.pathname.toLowerCase().includes('patientoverview');

// console.log(`[V22] Loaded on: ${window.location.hostname}${window.location.pathname} | c2=${IS_C2_FRAME} | overview=${IS_A2_OVERVIEW}`);

// // ─────────────────────────────────────────────
// // 1. HELPERS
// // ─────────────────────────────────────────────
// const sleep = (ms) => new Promise(res => setTimeout(res, ms));
// const clean = (s)  => (s || "").trim().replace(/\s+/g, ' ');

// function findElementByText(text) {
//     const tags = ['a', 'span', 'li', 'td', 'div', 'b', 'button'];
//     for (let tag of tags) {
//         const found = Array.from(document.querySelectorAll(tag))
//             .find(el => clean(el.innerText) === text || clean(el.innerText).includes(text));
//         if (found) return found;
//     }
//     return null;
// }

// function forceClick(el) {
//     if (!el) return;
//     ['mousedown', 'mouseup', 'click'].forEach(type => {
//         el.dispatchEvent(new MouseEvent(type, { view: window, bubbles: true, cancelable: true, buttons: 1 }));
//     });
//     if (el.tagName?.toLowerCase() === 'a' && el.href?.includes('javascript:')) {
//         const script = document.createElement('script');
//         script.textContent = el.href.replace('javascript:', '');
//         document.documentElement.appendChild(script);
//         script.remove();
//     } else {
//         el.click();
//     }
// }

// const extractBetween = (text, start, end) => {
//     const match = text.match(new RegExp(`${start}\\s*(.*?)\\s*${end}`, "i"));
//     return match ? clean(match[1]) : "N/A";
// };

// async function waitForElement(selector, timeout = 15000) {
//     return new Promise((resolve, reject) => {
//         const interval = setInterval(() => {
//             const el = document.querySelector(selector);
//             if (el) { clearInterval(interval); resolve(el); }
//         }, 500);
//         setTimeout(() => { clearInterval(interval); reject("Timeout: " + selector); }, timeout);
//     });
// }

// // ─────────────────────────────────────────────
// // 2. SCRAPERS
// // ─────────────────────────────────────────────

// function buildLabelMap() {
//     const map = {};
//     Array.from(document.querySelectorAll('.label-inner')).forEach(el => {
//         const label = (el.innerText || '').trim();
//         if (!label) return;
//         const valueContainer = el.parentElement?.nextElementSibling;
//         const valueEl = valueContainer?.querySelector('.label-inner-value, div, span');
//         const value = (valueEl?.innerText || '').trim();
//         if (!(label in map) || (!map[label] && value)) {
//             map[label] = value || "";
//         }
//     });
//     return map;
// }

// function lv(map, label) {
//     const val = map[label];
//     return (val && val.trim()) ? val.trim() : "N/A";
// }

// function scrapePatientOverview() {
//     const labels = buildLabelMap();

//     const nameEl = Array.from(document.querySelectorAll('div, span'))
//         .find(el => el.children.length === 0 && /^[A-Z]{2,},\s[A-Z]/.test((el.innerText || '').trim()));
//     const patientName = nameEl ? (nameEl.innerText || '').trim() : "N/A";

//     const dobEl = Array.from(document.querySelectorAll('span.font-weight-600'))
//         .find(el => /^\d{2}\/\d{2}\/\d{4}$/.test((el.innerText || '').trim()));
//     const dob = dobEl ? dobEl.innerText.trim() : "N/A";

//     const ageSexEl = Array.from(document.querySelectorAll('div, span'))
//         .find(el => /^\d+\s*\/\s*(Male|Female)/i.test((el.innerText || '').trim()));
//     const ageSex = ageSexEl ? (ageSexEl.innerText || '').trim() : "N/A";

//     const idLabelEl = Array.from(document.querySelectorAll('span'))
//         .find(el => (el.innerText || '').trim() === 'ID');
//     const patientId = idLabelEl?.nextElementSibling
//         ? (idLabelEl.nextElementSibling.innerText || '').trim() : "N/A";

//     const nextVisitLabelEl = Array.from(document.querySelectorAll('span'))
//         .find(el => (el.innerText || '').trim() === 'Next Visit');
//     const nextVisit = nextVisitLabelEl?.nextElementSibling
//         ? (nextVisitLabelEl.nextElementSibling.innerText || '').trim() : "N/A";

//     const phoneLinks = Array.from(document.querySelectorAll('a[href^="tel"]'));
//     let patientCell = "N/A";
//     for (let link of phoneLinks) {
//         const parentText = (link.parentElement?.innerText || '');
//         if (parentText.includes('(C)') || parentText.includes('Cell')) {
//             patientCell = (link.innerText || '').trim();
//             break;
//         }
//     }
//     if (patientCell === "N/A") {
//         const allEls = Array.from(document.querySelectorAll('span, div, a'));
//         const cEl = allEls.find(el => (el.innerText || '').includes('(C)') && /\d{3}/.test(el.innerText));
//         if (cEl) {
//             const match = (cEl.innerText || '').match(/\(C\)\s*([\d\-().]+)/);
//             if (match) patientCell = match[1].trim();
//         }
//     }

//     const emailLinks = Array.from(document.querySelectorAll('a[href^="mailto"]'));
//     const patientEmail = emailLinks.length > 0 ? (emailLinks[0].innerText || '').trim() : "N/A";

//     // ── Medical alerts ──
//     const alertsEl = Array.from(document.querySelectorAll('div, span'))
//         .find(el => (el.className || '').includes('alert') ||
//                     (el.id || '').toLowerCase().includes('alert') ||
//                     ((el.innerText || '').includes('Amoxicillin') || (el.innerText || '').includes('Allergy')));
//     let medAlerts = "N/A";
//     if (alertsEl) {
//         const alertText = (alertsEl.innerText || '').trim();
//         if (alertText.length < 200) medAlerts = alertText;
//     }

//     const bodyText = document.body.innerText;
//     const pgid = bodyText.match(/PGID\s*:\s*(\d+)/)?.[1] || "N/A";
//     const oid  = bodyText.match(/OID\s*:\s*(\d+)/)?.[1]  || "N/A";

//     const lastVisitLabelEl = Array.from(document.querySelectorAll('span, div'))
//         .find(el => (el.innerText || '').trim() === 'Last Visit');
//     const lastVisit = lastVisitLabelEl?.nextElementSibling
//         ? (lastVisitLabelEl.nextElementSibling.innerText || '').trim() : "N/A";

//     // ── Relation to subscriber: extract from "Subscriber (Rel.)" field ──
//     // Value looks like "CORR, DANIEL (Child)" — pull out what's in parens
//     const subscriberRel = lv(labels, 'Subscriber (Rel.)');
//     const relMatch = subscriberRel.match(/\(([^)]+)\)\s*$/);
//     const relationToSubscriber = relMatch ? relMatch[1].trim() : "N/A";
//     // Subscriber name is everything before the parens
//     const subscriberName = subscriberRel !== "N/A"
//         ? subscriberRel.replace(/\s*\([^)]+\)\s*$/, '').trim()
//         : "N/A";

//     return {
//         patient: {
//             name:                 patientName,
//             dob,
//             age_sex:              ageSex,
//             patient_id:           patientId,
//             cell:                 patientCell,
//             email:                patientEmail,
//             provider:             lv(labels, 'Provider'),
//             hygienist:            lv(labels, 'Hygienist'),
//             home_office:          lv(labels, 'Home Office'),
//             address:              lv(labels, 'Address'),
//             city_state_zip:       lv(labels, 'City, State and Zip'),
//             fee_schedule:         lv(labels, 'Fee Sched'),
//             first_visit:          lv(labels, 'First Visit'),
//             last_visit:           lastVisit,
//             next_visit:           nextVisit,
//             medical_alerts:       medAlerts
//         },
//         responsible_party: {
//             name:        lv(labels, 'Name'),
//             resp_id:     lv(labels, 'Resp ID'),
//             type:        lv(labels, 'Type'),
//             cell:        lv(labels, 'Cell'),
//             home_office: lv(labels, 'Home Office')
//         },
//         primary_insurance: {
//             carrier_name:          lv(labels, 'Carrier Name'),
//             group_num:             lv(labels, 'Group #'),
//             carrier_phone:         lv(labels, 'Carrier Phone'),
//             subscriber_name:       subscriberName,
//             relation_to_subscriber: relationToSubscriber,
//             indi_max_rem:          lv(labels, 'Indi. Max (Rem.)'),
//             indi_ded_rem:          lv(labels, 'Ind. Ded. (Rem.)')
//             // sub_id and rp_dob are NOT scraped here — they live in the insurance tab
//         },
//         practice: { pgid, oid }
//     };
// }

// function scrapeHeader(text) {
//     return { patient_name: text.split('\n').find(l => /^[A-Z]+,\s[A-Z]/.test(l.trim())) || "N/A" };
// }

// // ── Scrape SubID and RP BD from the c2 insurance tab header bar ──
// // The header bar text looks like:
// //   "Responsible  CORR, DANIEL  RP BD 05/18/1978  877-638-3379  SubID397842636"
// function scrapeInsuranceHeader() {
//     const bodyText = document.body.innerText || '';

//     // SubID — immediately followed by digits, no space
//     const subIdMatch = bodyText.match(/SubID\s*(\S+)/);
//     const subId = subIdMatch ? subIdMatch[1] : "N/A";

//     // RP BD — followed by date
//     const rpBdMatch = bodyText.match(/RP\s*BD\s+(\d{2}\/\d{2}\/\d{4})/);
//     const rpDob = rpBdMatch ? rpBdMatch[1] : "N/A";

//     // Carrier phone from header (format: 877-638-3379 near SubID line)
//     const carrierPhoneMatch = bodyText.match(/(\d{3}-\d{3}-\d{4})\s*SubID/);
//     const carrierPhone = carrierPhoneMatch ? carrierPhoneMatch[1] : "N/A";

//     console.log(`[V22] Insurance header — SubID: ${subId}, RP BD: ${rpDob}, Phone: ${carrierPhone}`);
//     return { subId, rpDob, carrierPhone };
// }

// function scrapePlanTab() {
//     const data = {};
//     Array.from(document.querySelectorAll('.insurance-details-modal tr, .row')).forEach(r => {
//         const cells = r.querySelectorAll('td, div');
//         if (cells.length >= 2) {
//             const label = clean(cells[0].innerText);
//             const val   = clean(cells[1].innerText);
//             if (label && val && label.length < 50) data[label] = val;
//         }
//     });
//     return data;
// }

// function scrapeBenTab() {
//     const notesEl = document.querySelector('.plan-notes') || findElementByText("Plan Notes")?.parentElement;
//     return {
//         notes:     notesEl ? clean(notesEl.innerText) : "N/A",
//         full_text: clean(document.body.innerText).substring(0, 3000)
//     };
// }

// function scrapeCoverageTab() {
//     return Array.from(document.querySelectorAll('table tr'))
//         .filter(r => r.innerText.includes('%') || r.innerText.match(/\d+/))
//         .map(r => {
//             const cells = Array.from(r.querySelectorAll('td')).map(c => clean(c.innerText));
//             return {
//                 category:     cells[0] || "N/A",
//                 ded_waived:   cells[1] || "N/A",
//                 coverage_pct: cells[2] || "N/A",
//                 limitation:   cells[3] || "N/A"
//             };
//         });
// }

// function getPlanLinks() {
//     const tbody = document.getElementById('searchInsurancePlanTableBody');
//     if (!tbody) return [];
//     return Array.from(tbody.querySelectorAll('a.show-ins-plan-details'));
// }

// // ─────────────────────────────────────────────
// // 3. BUTTON 1 — DOWNLOAD PATIENT JSON
// //    Still available but optional — passive background
// //    scraper keeps storage up to date automatically.
// // ─────────────────────────────────────────────
// async function handleDownloadPatient() {
//     if (!IS_C2_OVERVIEW) {
//         alert("Please navigate to the Patient Overview page first.");
//         return;
//     }

//     let attempts = 0;
//     while (document.querySelectorAll('.label-inner').length < 5 && attempts < 20) {
//         await sleep(500);
//         attempts++;
//     }

//     const overview = scrapePatientOverview();
//     const payload = {
//         denticon_data: {
//             ...overview,
//             scraped_at: new Date().toISOString(),
//             source_url: window.location.href
//         }
//     };

//     chrome.storage.local.set({ audit_context: payload }, () => {
//         console.log("[V22] Patient data saved to storage.");
//     });

//     triggerDownload(payload, `Denticon_Patient_${overview.patient.name}_${Date.now()}.json`, false);
//     console.log("[V22] Patient JSON download triggered.");
// }

// // ─────────────────────────────────────────────
// // 4. BUTTON 2 — CRAWL FULL INSURANCE PLAN
// //    Runs on: c2.denticon.com insurance tab
// //    Scrapes SubID + RP BD from the header here,
// //    merges with patient overview from storage,
// //    produces one complete JSON.
// // ─────────────────────────────────────────────
// async function deepCrawlInsurance() {
//     if (!IS_C2_FRAME) {
//         alert("Please open the Primary Dental insurance tab first, then click Crawl Full Insurance Plan.");
//         return;
//     }

//     console.log("[V22] deepCrawlInsurance() starting...");

//     // ── Step 1: Scrape SubID + RP BD from the insurance tab header NOW
//     //    (before any modal opens and potentially overwrites the DOM)
//     const headerData = scrapeInsuranceHeader();

//     // ── Step 2: Get Group # ──
//     let groupNum = "";
//     const groupInput = document.getElementById('inputCarrierGroup');
//     const groupSpan  = document.getElementById('showCarrierGroup');

//     if (groupInput && clean(groupInput.value)) {
//         groupNum = clean(groupInput.value);
//     } else if (groupSpan && clean(groupSpan.innerText)) {
//         groupNum = clean(groupSpan.innerText);
//     }

//     if (!groupNum) {
//         groupNum = prompt("Group ID not detected. Please enter the Group # manually:");
//     }
//     if (!groupNum) {
//         console.warn("[V22] No group number. Aborting.");
//         return;
//     }

//     console.log(`[V22] Group # = ${groupNum}`);

//     // ── Step 3: Click Q SEARCH ──
//     const searchBtn = findElementByText("Q SEARCH") || findElementByText("SEARCH");
//     if (!searchBtn) {
//         alert("Cannot find the Q SEARCH button. Make sure you are on the Primary Dental insurance tab.");
//         return;
//     }

//     console.log("[V22] Clicking Q SEARCH...");
//     forceClick(searchBtn);

//     let searchInput;
//     try {
//         searchInput = await waitForElement('#inpSearchText', 15000);
//     } catch (e) {
//         alert("Plan search modal did not open in time.");
//         return;
//     }

//     searchInput.value = groupNum;
//     searchInput.dispatchEvent(new Event('input',  { bubbles: true }));
//     searchInput.dispatchEvent(new Event('change', { bubbles: true }));

//     const searchForDdl = document.getElementById('ddlSearchFor') ||
//                          document.querySelector('select[id*="SearchFor"]') ||
//                          document.querySelector('select[id*="searchFor"]');
//     if (searchForDdl) {
//         const groupOpt = Array.from(searchForDdl.options).find(o => o.text.toLowerCase().includes('group'));
//         if (groupOpt) {
//             searchForDdl.value = groupOpt.value;
//             searchForDdl.dispatchEvent(new Event('change', { bubbles: true }));
//         }
//     }

//     await sleep(300);

//     let modalSearchClicked = false;
//     for (let btn of Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"]'))) {
//         const text = clean(btn.innerText || btn.value || "").toUpperCase();
//         if (text.includes('SEARCH') && btn !== searchBtn && !text.includes('PATIENT') && !text.includes('BEGINNING')) {
//             btn.click();
//             modalSearchClicked = true;
//             break;
//         }
//     }
//     if (!modalSearchClicked) {
//         searchInput.focus();
//         searchInput.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, keyCode: 13, key: 'Enter' }));
//     }

//     // ── Step 4: Wait for plan list ──
//     let planLinks = [];
//     for (let i = 0; i < 8; i++) {
//         await sleep(1500);
//         planLinks = getPlanLinks();
//         if (planLinks.length > 0) break;
//         console.log(`[V22] Waiting for plans... (${i + 1}/8)`);
//     }

//     if (planLinks.length === 0) {
//         alert("Plan list did not load.\n\nWorkaround: Click Q SEARCH manually, wait for the table, then click Crawl again.");
//         return;
//     }

//     // ── Step 5: Loop through every plan ──
//     const allPlanAudits = [];

//     for (let i = 0; i < planLinks.length; i++) {
//         const currentLinks = getPlanLinks();
//         if (!currentLinks[i]) continue;

//         const planId = clean(currentLinks[i].innerText);
//         console.log(`[V22] Auditing plan ${i + 1}/${planLinks.length} — ID: ${planId}`);
//         currentLinks[i].click();

//         await sleep(3500);

//         const plan = scrapePlanTab();

//         const benTab = findElementByText("BEN");
//         if (benTab) { benTab.click(); await sleep(2000); }
//         const ben = scrapeBenTab();

//         const covTab = findElementByText("COVERAGE AND LIMITATIONS");
//         if (covTab) { covTab.click(); await sleep(2000); }
//         const cov = scrapeCoverageTab();

//         allPlanAudits.push({ ins_plan_id: planId, plan_details: plan, benefits: ben, coverage: cov });

//         const cancelBtn = document.getElementById('btnCancel') ||
//                           findElementByText("CANCEL") ||
//                           findElementByText("CLOSE");
//         if (cancelBtn) { cancelBtn.click(); await sleep(2000); }
//     }

//     // ── Step 6: Merge everything and download ──
//     chrome.storage.local.get("audit_context", (result) => {
//         const store = result.audit_context || {};
//         const existing = store.denticon_data || {};

//         // Inject SubID and RP DOB into primary_insurance and responsible_party
//         // These come from the insurance tab header, not the patient overview
//         const primaryIns = existing.primary_insurance || {};
//         const respParty  = existing.responsible_party  || {};

//         primaryIns.sub_id = headerData.subId;
//         if (headerData.carrierPhone !== "N/A") {
//             primaryIns.carrier_phone = headerData.carrierPhone;
//         }
//         if (!primaryIns.carrier_name && existing.primary_insurance?.carrier_name) {
//             primaryIns.carrier_name = existing.primary_insurance.carrier_name;
//         }
//         respParty.dob = headerData.rpDob;

//         store.denticon_data = {
//             ...existing,
//             primary_insurance:  primaryIns,
//             responsible_party:  respParty,
//             plans:              allPlanAudits,
//             total_captured:     allPlanAudits.length,
//             crawled_at:         new Date().toISOString()
//         };

//         chrome.storage.local.set({ audit_context: store }, () => {
//             const patientName = (store.denticon_data?.patient?.name || "Unknown").replace(/[^a-zA-Z0-9_,. -]/g, '');
//             triggerDownload(store, `Denticon_DeepAudit_${patientName}_${Date.now()}.json`, true);
//             alert(`Deep Scrape Complete! Captured ${allPlanAudits.length} plans.\nSubID: ${headerData.subId} | RP BD: ${headerData.rpDob}`);
//         });
//     });
// }

// // ─────────────────────────────────────────────
// // 5. BACKGROUND SCRAPER
// //    Passively keeps patient overview in storage
// //    so Button 2 can merge with it even if
// //    Button 1 was never clicked.
// // ─────────────────────────────────────────────
// if (IS_A2_OVERVIEW || IS_C2_OVERVIEW) {
//     setInterval(() => {
//         if (!chrome.runtime?.id) return;
//         const text = document.body.innerText;
//         if (text.includes("Carrier Name") || text.includes("PATIENT INFORMATION")) {
//             chrome.storage.local.get("audit_context", (result) => {
//                 const store = result.audit_context || {};
//                 const overview = scrapePatientOverview();
//                 // Only update patient/responsible_party/primary_insurance fields
//                 // Don't overwrite sub_id or rp_dob if already set by insurance tab
//                 store.denticon_data = {
//                     ...store.denticon_data,
//                     patient:            overview.patient,
//                     responsible_party:  {
//                         ...overview.responsible_party,
//                         // Preserve dob if already scraped from insurance tab
//                         dob: store.denticon_data?.responsible_party?.dob || "N/A"
//                     },
//                     primary_insurance:  {
//                         ...overview.primary_insurance,
//                         // Preserve sub_id if already scraped from insurance tab
//                         sub_id: store.denticon_data?.primary_insurance?.sub_id || "N/A"
//                     },
//                     practice:           overview.practice
//                 };
//                 chrome.storage.local.set({ audit_context: store });
//             });
//         }
//     }, 3000);
// }

// // ─────────────────────────────────────────────
// // 6. MESSAGE LISTENER
// // ─────────────────────────────────────────────
// chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

//     if (request.command === "DOWNLOAD_PATIENT") {
//         handleDownloadPatient();
//         sendResponse({ status: "Patient download triggered" });
//         return true;
//     }

//     if (request.command === "START_CRAWL") {
//         deepCrawlInsurance();
//         sendResponse({ status: "Crawl started" });
//         return true;
//     }
// });

// // ─────────────────────────────────────────────
// // 7. DOWNLOAD HELPER
// // ─────────────────────────────────────────────
// function triggerDownload(data, filename, purgeAfter) {
//     filename = filename || `Denticon_Audit_${Date.now()}.json`;
//     const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
//     const url  = window.URL.createObjectURL(blob);
//     const a    = document.createElement('a');
//     a.style.display = 'none';
//     a.href     = url;
//     a.download = filename;
//     document.body.appendChild(a);
//     a.click();
//     window.URL.revokeObjectURL(url);
//     document.body.removeChild(a);

//     if (purgeAfter) {
//         chrome.storage.local.remove("audit_context", () => {
//             console.log("[V22] Storage purged after download.");
//         });
//     }
// }
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

function scrapePatientOverview() {
    const labels = buildLabelMap();

    const nameEl = Array.from(document.querySelectorAll('div, span'))
        .find(el => el.children.length === 0 && /^[A-Z]{2,},\s[A-Z]/.test((el.innerText || '').trim()));
    const patientName = nameEl ? (nameEl.innerText || '').trim() : "N/A";

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
    const pgid = bodyText.match(/PGID\s*:\s*(\d+)/)?.[1] || "N/A";
    const oid  = bodyText.match(/OID\s*:\s*(\d+)/)?.[1]  || "N/A";

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
        },
        practice: { pgid, oid }
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

    console.log(`[V22] Insurance header — SubID: ${subId}, RP BD: ${rpDob}, Phone: ${carrierPhone}`);
    return { subId, rpDob, carrierPhone };
}

function scrapePlanTab() {
    const data = {};
    Array.from(document.querySelectorAll('.insurance-details-modal tr, .row')).forEach(r => {
        const cells = r.querySelectorAll('td, div');
        if (cells.length >= 2) {
            const label = clean(cells[0].innerText);
            const val   = clean(cells[1].innerText);
            if (label && val && label.length < 50) data[label] = val;
        }
    });
    return data;
}

function scrapeBenTab() {
    const notesEl = document.querySelector('.plan-notes') || findElementByText("Plan Notes")?.parentElement;
    return {
        notes:     notesEl ? clean(notesEl.innerText) : "N/A",
        full_text: clean(document.body.innerText).substring(0, 3000)
    };
}

function scrapeCoverageTab() {
    return Array.from(document.querySelectorAll('table tr'))
        .filter(r => r.innerText.includes('%') || r.innerText.match(/\d+/))
        .map(r => {
            const cells = Array.from(r.querySelectorAll('td')).map(c => clean(c.innerText));
            return {
                category:     cells[0] || "N/A",
                ded_waived:   cells[1] || "N/A",
                coverage_pct: cells[2] || "N/A",
                limitation:   cells[3] || "N/A"
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

        await sleep(3500);

        const plan = scrapePlanTab();

        const benTab = findElementByText("BEN");
        if (benTab) { benTab.click(); await sleep(2000); }
        const ben = scrapeBenTab();

        const covTab = findElementByText("COVERAGE AND LIMITATIONS");
        if (covTab) { covTab.click(); await sleep(2000); }
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

        // Inject SubID and RP DOB into primary_insurance and responsible_party
        // These come from the insurance tab header, not the patient overview
        const primaryIns = existing.primary_insurance || {};
        const respParty  = existing.responsible_party  || {};

        primaryIns.sub_id = headerData.subId;
        if (headerData.carrierPhone !== "N/A") {
            primaryIns.carrier_phone = headerData.carrierPhone;
        }
        if (!primaryIns.carrier_name && existing.primary_insurance?.carrier_name) {
            primaryIns.carrier_name = existing.primary_insurance.carrier_name;
        }
        respParty.dob = headerData.rpDob;

        store.denticon_data = {
            ...existing,
            primary_insurance:  primaryIns,
            responsible_party:  respParty,
            plans:              allPlanAudits,
            total_captured:     allPlanAudits.length,
            crawled_at:         new Date().toISOString()
        };

        chrome.storage.local.set({ audit_context: store }, () => {
            const patientName = (store.denticon_data?.patient?.name || "Unknown").replace(/[^a-zA-Z0-9_,. -]/g, '');
            triggerDownload(store, `Denticon_DeepAudit_${patientName}_${Date.now()}.json`, false);
            alert(`Deep Scrape Complete! Captured ${allPlanAudits.length} plans.`);
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
        if (text.includes("Carrier Name") || text.includes("PATIENT INFORMATION")) {
            chrome.storage.local.get("audit_context", (result) => {
                const store = result.audit_context || {};
                const overview = scrapePatientOverview();
                // Only update patient/responsible_party/primary_insurance fields
                // Don't overwrite sub_id or rp_dob if already set by insurance tab
                store.denticon_data = {
                    ...store.denticon_data,
                    patient:            overview.patient,
                    responsible_party:  {
                        ...overview.responsible_party,
                        // Preserve dob if already scraped from insurance tab
                        dob: store.denticon_data?.responsible_party?.dob || "N/A"
                    },
                    primary_insurance:  {
                        ...overview.primary_insurance,
                        // Preserve sub_id if already scraped from insurance tab
                        sub_id: store.denticon_data?.primary_insurance?.sub_id || "N/A"
                    },
                    practice:           overview.practice
                };
                chrome.storage.local.set({ audit_context: store });
            });
        }
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