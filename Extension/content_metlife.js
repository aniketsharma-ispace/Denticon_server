(() => {
    "use strict";

    // MetLife auditor v1.31 — one ordinary isolated-world content script.
    // All MetLife logic lives in this file. No page-world bridge is required.

    // Protect against accidental duplicate isolated-world registration.
    if (globalThis.__IAP_METLIFE_ISOLATED_SCRIPT_LOADED__) return;
    globalThis.__IAP_METLIFE_ISOLATED_SCRIPT_LOADED__ = true;
    console.log("[Audit] MetLife content script v1.31 loaded:", location.href);

    const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');
    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    async function waitForElement(selector, timeout = 8000) {
        const deadline = Date.now() + timeout;
        while (Date.now() < deadline) {
            const el = document.querySelector(selector);
            if (el) return el;
            await sleep(400);
        }
        return null;
    }

    function findByText(text, root = document.body) {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while ((node = walker.nextNode())) {
            if (node.textContent.trim() === text) return node.parentElement;
        }
        return null;
    }

    function setReactInputValue(input, value) {
        const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeSetter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }


    // ══════════════════════════════════════════════════════════════════════════
    // PROCEDURE SEARCH — DOM-ONLY CROSS-BROWSER MODE
    //
    // No MAIN-world script, inline injection, fetch/XHR monkey-patching, or CSP
    // dependency. The auditor drives MetLife's own UI and reads the rendered
    // results table. This is intentionally slower but much more portable across
    // Chrome, Edge (including stricter managed setups), and Firefox.
    // ══════════════════════════════════════════════════════════════════════════

    // 66 codes across 8 batches — chunked into groups of 10 at runtime (site hard limit)
    const BATCH_1 = ["D1110", "D4910", "D4355", "D1206", "D1208", "D0274", "D0210", "D0120", "D0150"];
    const BATCH_2 = ["D2331", "D2140", "D2740", "D1351", "D1510", "D8080", "D0180", "D0140", "D0240"];
    const BATCH_3 = ["D0330", "D0220", "D0230", "D0364", "D0431", "D1120", "D2991", "D2950", "D2620"];
    const BATCH_4 = ["D2962", "D6750", "D5110", "D9110", "D9222", "D9243", "D9310", "D9944", "D4341"];
    const BATCH_5 = ["D4346", "D4381", "D4260", "D4249", "D3310", "D3330", "D7140", "D7210", "D7240"];
    const BATCH_6 = ["D7953", "D6010", "D6056", "D2332", "D6245", "D5860", "D5740", "D5982", "D9430"];
    const BATCH_7 = ["D9239", "D3347", "D7259", "D6065", "D6194", "D8010", "D8090", "D9230"];
    // Codes the Sabrina breakdown sheet audits that no other batch requests.
    // Without them the portal is never asked, so rows the sheet fills in can
    // only be reported as "not stated" — the site does carry them (D5212
    // "1 TIME IN 10 CALENDAR YEARS" at 50%, D2980 "1 TIME IN 12 MONTHS" at
    // 50%, D5899 and D5995 as uncovered).
    const BATCH_8 = ["D2160", "D2980", "D5212", "D5899", "D5995"];

    async function scrapeSubscriberFromDropdown() {
        try {
            // Click the patient name h3 to open dropdown
            const h3 = document.querySelector("h3.patient-name");
            if (!h3) {
                console.warn("[Audit] h3.patient-name not found — skipping");
                return null;
            }

            h3.click();
            await sleep(1200);

            // Find the li containing the Subscriber relation span
            let subscriberEntry = null;
            const spans = document.querySelectorAll(".dropdown-patient-relation");
            for (const span of spans) {
                if (span.innerText.trim() === "Subscriber") {
                    subscriberEntry = span.closest("li");
                    break;
                }
            }

            if (!subscriberEntry) {
                console.warn("[Audit] Subscriber li not found — closing dropdown");
                document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
                await sleep(400);
                return null;
            }

            // Parse the 3 lines: name / relation / "48 | DOB: 05/18/1978 | Male"
            const lines = subscriberEntry.innerText.split("\n").map(l => l.trim()).filter(Boolean);
            const name     = lines[0] || "N/A";
            const relation = lines[1] || "Subscriber";
            const detail   = lines[2] || "";
            const age      = detail.match(/^(\d+)/)?.[1] || "N/A";
            const dob      = detail.match(/DOB:\s*([\d\/]+)/)?.[1] || "N/A";
            const gender   = detail.match(/\|\s*(Male|Female)/i)?.[1]?.trim() || "N/A";

            // Close dropdown without switching patient
            document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
            await sleep(600);

            const result = { name, relation, age, dob, gender };
            console.log("[Audit] Subscriber scraped:", result);
            return result;

        } catch (err) {
            console.error("[Audit] scrapeSubscriberFromDropdown error (non-fatal):", err);
            return null;
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // PATIENT INFO
    // ══════════════════════════════════════════════════════════════════════════

    function scrapePatientInfo() {
        const name = document.querySelector(".patient-name")?.innerText?.trim() ||
            document.querySelector("[class*='patient'] [class*='name']")?.innerText?.trim() || "N/A";
        const cardText = document.querySelector(".card-details, [class*='card-detail'], [class*='member-info']")?.innerText || "";
        return {
            name,
            dob: cardText.match(/DOB:\s*(\d{2}\/\d{2}\/\d{4})/)?.[1] || "N/A",
            relationship: cardText.match(/^([^\|]+)/)?.[1]?.trim() || "N/A",
            gender: cardText.match(/\|\s*(Male|Female)\s*/i)?.[1]?.trim() || "N/A"
        };
    }


    // ══════════════════════════════════════════════════════════════════════════
    // PLAN DETAILS
    // ══════════════════════════════════════════════════════════════════════════

    function scrapePlanDetails() {
        function getLabelValues(labelText) {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            let node;

            while ((node = walker.nextNode())) {
                if (clean(node.textContent) !== labelText) continue;

                const labelEl = node.parentElement;
                const detailsColumn = labelEl.closest(".details-column") || labelEl.parentElement;

                // MetLife can place multiple values under one title, for example:
                // Employer / Group # -> CITY OF RACINE, 148620
                const columnValues = Array.from(detailsColumn?.querySelectorAll(".details-value") || [])
                    .map(el => clean(el.innerText || el.textContent))
                    .filter(Boolean);

                if (columnValues.length) return columnValues;

                // Generic fallback for labels whose values are ordinary sibling elements.
                const siblingValues = [];
                let sibling = labelEl.nextElementSibling;
                while (sibling && !sibling.matches(".details-title")) {
                    const value = clean(sibling.innerText || sibling.textContent);
                    if (value) siblingValues.push(value);
                    sibling = sibling.nextElementSibling;
                }
                if (siblingValues.length) return siblingValues;

                const parentSibling = labelEl.parentElement?.nextElementSibling;
                const fallbackValue = clean(parentSibling?.innerText || parentSibling?.textContent);
                if (fallbackValue) return [fallbackValue];
            }

            return [];
        }

        function getLabelValue(labelText) {
            return getLabelValues(labelText)[0] || "N/A";
        }

        const employerGroupValues = getLabelValues("Employer / Group #");

        return {
            start_date: getLabelValue("Start Date"),
            end_date: getLabelValue("End Date"),
            subscriber_id: getLabelValue("Subscriber SSN or ID"),
            employer_group: employerGroupValues[0] || "N/A",
            group_number: employerGroupValues[1] || "N/A",
            network: getLabelValue("Network"),
            address: getLabelValue("Address")
        };
    }

    // The selected provider's network status. The Benefit & Coverage tab states
    // it twice — the sticker beside the provider dropdown and the badge above
    // the procedure results — and both are read by their own selectors. The
    // sticker's aria-label says "In-network" even for an out-of-network
    // provider, so only its visible text is trusted.
    //
    // A plain "text is exactly In-Network" search is NOT safe: the category
    // cards title their two columns "IN-NETWORK" / "OUT-OF-NETWORK", and the
    // coverage table heads its columns the same way, so that search reported
    // whichever heading came first as the provider's status.
    function normalizeNetworkStatus(text) {
        const t = clean(text).toLowerCase();
        if (/^out[\s-]*of[\s-]*network$/.test(t)) return "Out-of-Network";
        if (/^in[\s-]*network$/.test(t)) return "In-Network";
        return "";
    }

    function scrapeProviderInfo() {
        const stated = [
            "#in-network-status-stickers .content",
            ".table-network-status",
        ].map(sel => normalizeNetworkStatus(document.querySelector(sel)?.textContent))
         .find(Boolean);
        if (stated) return { provider_network_status: stated };

        // Fallback for a page without either badge: an exact-text element that
        // is not a column heading, a category-card title, or the Maximums tab's
        // "Show Benefit Maximums & Deductibles for" filter (which names the
        // network the amounts are shown for, not the provider's).
        const badge = Array.from(document.querySelectorAll("span,div,p")).find(el =>
            !el.closest("th, thead, [id^='donut-chart-title'], .network-filter") &&
            el.children.length === 0 &&
            normalizeNetworkStatus(el.textContent) &&
            // Headings are rendered in capitals; the status badge is not.
            clean(el.textContent) !== clean(el.textContent).toUpperCase()
        );
        return {
            provider_network_status: badge ? normalizeNetworkStatus(badge.textContent) : "N/A"
        };
    }

    // ══════════════════════════════════════════════════════════════════════════
    // FINANCIALS
    // ══════════════════════════════════════════════════════════════════════════

    function findCardByLabel(labelText) {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while ((node = walker.nextNode())) {
            if (node.textContent.trim() !== labelText) continue;
            let el = node.parentElement;
            for (let i = 0; i < 10; i++) {  // bleed protection is content-based (siblingLabels check below), not depth — safe to search deeper
                if (!el) break;
                const dollars = (el.innerText || "").match(/\$\s*[\d,]+/g) || [];
                const text = el.innerText || "";
                // Stop if we've absorbed text from a SIBLING card label (Annual/Lifetime/Individual)
                const siblingLabels = ["Annual", "Lifetime", "Individual", "Family"].filter(l => l !== labelText);
                if (siblingLabels.some(l => text.includes(l)) && dollars.length >= 2) break;
                if (dollars.length >= 2) return el;
                el = el.parentElement;
            }
        }
        return null;
    }

    function parseCardAmounts(container) {
        if (!container) return { remaining: "N/A", used: "N/A", total: "N/A" };
        const text = container.innerText || "";
        return {
            remaining: text.match(/\$\s*[\d,]+\.?\d*\s*remaining/i)?.[0]?.replace(/\s+/g, ' ').trim() || "N/A",
            used: text.match(/\$\s*[\d,]+\.?\d*\s*(?:used|paid)\s*to\s*date/i)?.[0]?.replace(/\s+/g, ' ').trim() || "N/A",
            total: text.match(/\$\s*[\d,]+\.?\d*\s*total/i)?.[0]?.replace(/\s+/g, ' ').trim() || "N/A"
        };
    }

    function parseCardDescription(card) {
        if (!card) return "";
        const descEl = card.querySelector('[id^="section-description-"]');
        return descEl ? descEl.innerText.trim() : "";
    }

    function scrapeFinancials() {
        const annualCard = findCardByLabel("Annual");

        // ── Lifetime maximum ──
        // The Lifetime card carries a Category selector, and the category is
        // NOT always orthodontics — on some plans the only lifetime maximum
        // belongs to TMJ, a separate class that Eligibility & Benefits
        // verification does not cover. Reading the card blindly reported a TMJ
        // maximum as the orthodontic lifetime max ($1000 against a sheet that
        // correctly said 0). The amounts are only taken when the category is
        // orthodontic, or when no category is named at all; the category is
        // recorded either way so downstream can see what the figure belongs to.
        const lifetimeCard = findCardByLabel("Lifetime");
        let ortho_lifetime;

        if (!lifetimeCard) {
            ortho_lifetime = { remaining: "0.0", used: "0.0", total: "0.0", category: "N/A" };
        } else {
            const lifetimeText = lifetimeCard.innerText || "";
            const flatLifetime = lifetimeText.replace(/\s+/g, ' ');
            const categoryMatch = flatLifetime.match(/Category\s+([A-Za-z][A-Za-z0-9 /&()-]{1,40}?)\s*(?:[$]|$)/i);
            const category = categoryMatch ? categoryMatch[1].trim() : "";
            const isOrtho = /orthodont/i.test(category) || /^ortho\b/i.test(category);
            const otherClass = category
                ? !isOrtho
                : /\bTMJ\b|temporomandibular/i.test(flatLifetime);

            if (/no lifetime benefit maximum/i.test(lifetimeText) || otherClass) {
                ortho_lifetime = {
                    remaining: "0.0", used: "0.0", total: "0.0",
                    category: category || "N/A"
                };
            } else {
                ortho_lifetime = Object.assign(parseCardAmounts(lifetimeCard),
                                               { category: category || "N/A" });
            }
        }
        // ── Family deductible (may not exist for all plans) ──
        const famCard = findCardByLabel("Family");
        const deductible_fam = famCard
            ? parseCardAmounts(famCard)
            : { remaining: "N/A", used: "N/A", total: "N/A" };

        return {
            annual_max: {
                ...parseCardAmounts(annualCard),
                description: parseCardDescription(annualCard),
            },
            ortho_lifetime,
            deductible_ind: parseCardAmounts(findCardByLabel("Individual")),
            deductible_fam,
        };
    }


    // ══════════════════════════════════════════════════════════════════════════
    // COVERED SERVICES
    // ══════════════════════════════════════════════════════════════════════════

    function scrapeCoveredServices() {
        const heading = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6"))
            .find(h => h.textContent.trim() === "Covered Services") || findByText("Covered Services");
        let table = null;
        if (heading) {
            const section = heading.closest("section,[class*='section']") || heading.parentElement;
            table = section?.querySelector("table") || heading.parentElement?.nextElementSibling?.querySelector("table");
        }
        if (!table) table = Array.from(document.querySelectorAll("table")).find(t => t.innerText.includes("Procedure Category"));
        if (!table) return [];

        return Array.from(table.querySelectorAll("tr")).slice(1).map(row => {
            const cells = row.querySelectorAll("td");
            if (cells.length < 2) return null;
            const categoryName = cells[0].querySelector("strong,b")?.innerText?.trim() || cells[0].innerText.split('\n')[0].trim();
            return {
                category: categoryName,
                services: clean(cells[0].innerText).replace(categoryName, "").trim() || "N/A",
                in_network: clean(cells[1]?.innerText) || "N/A",
                out_of_network: clean(cells[2]?.innerText) || "N/A"
            };
        }).filter(r => r && r.category);
    }


    // ══════════════════════════════════════════════════════════════════════════
    // PLAN PROVISIONS
    // ══════════════════════════════════════════════════════════════════════════

    function scrapeProvisions() {
        // ── 1. Try heading-anchored search (existing logic) ──────────────────
        const heading = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6"))
            .find(h => h.textContent.trim().includes("Plan Provisions"))
            || findByText("Plan Provisions");

        let section = null;
        if (heading) {
            let el = heading.nextElementSibling;
            while (el) {
                if ((el.innerText || "").trim().length > 50) { section = el; break; }
                el = el.nextElementSibling;
            }
            if (!section)
                section = heading.closest("[class*='provision'],section") || heading.parentElement;
        }
        if (!section) section = document.querySelector("[class*='provision'],[class*='Provision']");

        // ── 2. If we have a section, try to parse its table ──────────────────
        if (section) {
            const tableRows = section.querySelectorAll("table tr, tbody tr");
            if (tableRows.length) {
                const results = Array.from(tableRows).map(tr => {
                    const c = tr.querySelectorAll("td");
                    if (c.length < 2) return null;
                    return { rule: clean(c[0]?.innerText), value: clean(c[1]?.innerText) };
                }).filter(r => r && r.rule && r.value);
                if (results.length) return results;
            }
        }

        // ── 3. Fallback: scan ALL tables on page for a provisions-like table ──
        //    Identified by known first-column labels from MetLife's Plan Provisions table
        const PROVISION_ANCHORS = [
            "Coverage is selected for",
            "Basis of payment",
            "Waiting Period",
            "Maximum child age",
            "Coordination of Benefits Rule",
            "Alternate Benefits",
            "Orthodontic Coverage",
            "Ortho payment method",
            "Cleanings and Periodontal Maintenance"
        ];

        for (const table of document.querySelectorAll("table")) {
            const rows = Array.from(table.querySelectorAll("tr"));
            const cellTexts = rows.flatMap(r =>
                Array.from(r.querySelectorAll("td")).map(td => clean(td.innerText))
            );
            const matchCount = PROVISION_ANCHORS.filter(a =>
                cellTexts.some(t => t.includes(a))
            ).length;

            if (matchCount >= 3) {
                // This is the provisions table — parse all rows
                return rows.map(tr => {
                    const cells = tr.querySelectorAll("td");
                    if (cells.length < 2) return null;
                    return {
                        rule: clean(cells[0]?.innerText),
                        value: clean(cells[1]?.innerText)
                    };
                }).filter(r => r && r.rule && r.value);
            }
        }

        // ── 4. Last-resort: bold-label pairs inside heading's parent ─────────
        if (section) {
            const dts = section.querySelectorAll("dt");
            if (dts.length) return Array.from(dts).map(dt => ({
                rule: clean(dt.innerText),
                value: clean(dt.nextElementSibling?.innerText)
            })).filter(r => r.rule);

            const boldEls = section.querySelectorAll("strong,b,[class*='label'],[class*='key']");
            if (boldEls.length >= 3) {
                const results = Array.from(boldEls).map(el => ({
                    rule: clean(el.innerText),
                    value: clean((el.parentElement?.innerText || "").replace(el.innerText, "").trim())
                        || clean(el.nextElementSibling?.innerText) || "N/A"
                })).filter(r => r.rule && r.value && r.rule !== r.value);
                if (results.length >= 3) return results;
            }
        }

        return [];
    }


    // ══════════════════════════════════════════════════════════════════════════
    // BUILD PLAN OVERVIEW PAYLOAD
    // ══════════════════════════════════════════════════════════════════════════

    function buildPlanOverviewPayload() {
        return {
            source: "MetLife Portal - Plan Overview",
            timestamp: new Date().toISOString(),
            patient: scrapePatientInfo(),
            plan_details: scrapePlanDetails(),
            provider_info: scrapeProviderInfo(),
            // The network the maximums and deductibles below are shown for.
            financials_network: financialsNetwork(),
            financials: scrapeFinancials(),
            covered_services: scrapeCoveredServices(),
            provisions: scrapeProvisions()
        };
    }


    // ══════════════════════════════════════════════════════════════════════════
    // CRAWL — PLAN OVERVIEW
    // ══════════════════════════════════════════════════════════════════════════

    async function waitForText(substring, timeout = 5000) {
        const deadline = Date.now() + timeout;
        while (Date.now() < deadline) {
            if ((document.body.innerText || "").includes(substring)) return true;
            await sleep(300);
        }
        return false;
    }

    // The provider picked in the Benefit & Coverage dropdown, and the tab
    // currently shown. Benefit Level / Patient Responsibility depend on the
    // provider's network, so a crawl must run against the provider the user
    // chose — and leaving that tab can reset the dropdown to its default.
    function selectedProviderName() {
        // The name is the trigger's own <span>; the whole button's text also
        // carries the chevron icon's <title> ("Carolyn LeungChevron Down").
        const trigger = document.querySelector(".benefits__provider-list .pop-dropdown-trigger");
        return clean(trigger?.querySelector(":scope > span")?.textContent || trigger?.textContent) || "N/A";
    }

    function isTabActive(label) {
        return Array.from(document.querySelectorAll("[role='tab']")).some(tab =>
            clean(tab.textContent) === label &&
            (tab.getAttribute("aria-selected") === "true" || tab.classList.contains("active"))
        );
    }

    // ── Maximums & deductibles network filter ──
    // The Maximums tab shows its amounts for ONE network at a time, chosen in
    // "Show Benefit Maximums & Deductibles for: [In-Network | Out-of-Network]".
    // Deductibles differ by network (Nicole Green: $50/$100 in, $75/$150 out),
    // so reading whatever the filter happened to show gave an out-of-network
    // office the in-network deductible.
    function financialsNetwork() {
        return normalizeNetworkStatus(
            document.querySelector("#network-filter-dropdown-combo-label")?.textContent
        ) || "N/A";
    }

    // An option's text may carry more than the name (an icon title, a check
    // mark), so options are matched on the network they mention.
    function networkMentioned(text) {
        const t = clean(text).toLowerCase();
        if (/out[\s-]*of[\s-]*network/.test(t)) return "Out-of-Network";
        if (/\bin[\s-]*network/.test(t)) return "In-Network";
        return "";
    }

    function financialsSignature() {
        return [".plan-coverage-details", ".plan-deductible-details"]
            .map(sel => clean(document.querySelector(sel)?.textContent)).join("|");
    }

    // Switch the filter to `wanted`; true once it shows that network.
    async function selectFinancialsNetwork(wanted) {
        if (financialsNetwork() === wanted) return true;
        const combobox = document.querySelector("#network-filter-dropdown-combobox");
        if (!combobox) return false;
        const before = financialsSignature();

        const findOption = () => {
            const listbox = document.getElementById(
                combobox.getAttribute("aria-controls") || "network-filter-dropdown-listbox");
            const candidates = listbox
                ? listbox.querySelectorAll("[role='option'], li")
                : document.querySelectorAll("[role='option']");
            return Array.from(candidates).find(el => networkMentioned(el.textContent) === wanted);
        };
        const waitForOption = async (tries) => {
            for (let i = 0; i < tries; i++) {
                await sleep(250);
                const option = findOption();
                if (option) return option;
            }
            return null;
        };
        const press = (el) => ["mousedown", "mouseup", "click"].forEach(type =>
            el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true })));

        // The dropdown may open on click, on mousedown, or from the keyboard.
        combobox.click();
        let option = await waitForOption(8);
        if (!option) { press(combobox); option = await waitForOption(8); }
        if (!option) {
            combobox.focus();
            combobox.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
            option = await waitForOption(8);
        }
        if (!option) {
            console.warn(`[Audit] Maximums network filter: no "${wanted}" option found.`);
            document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
            return false;
        }
        press(option);

        const deadline = Date.now() + 5000;
        while (Date.now() < deadline && financialsNetwork() !== wanted) await sleep(250);
        if (financialsNetwork() !== wanted) return false;

        // The amounts can re-render after the label. Networks with equal
        // amounts never change, so this waits a bounded time, not for a change.
        const settle = Date.now() + 3000;
        while (Date.now() < settle && financialsSignature() === before) await sleep(250);
        await sleep(500);
        return true;
    }

    // `reset` starts a fresh audit context (a new patient). When the Benefit &
    // Coverage crawl has already run, its provider network status is kept — the
    // Plan Overview tab does not show which provider is selected — and the
    // maximums & deductibles filter is set to that network before reading.
    async function crawlPlanOverview(reset = true) {
        const tabEl = findByText("Maximums, Deductibles & Provisions");
        if (tabEl && !isTabActive("Maximums, Deductibles & Provisions")) {
            tabEl.click();
            await waitForText("Benefit Maximums", 5000);
        }

        const ctx = reset ? {} : await new Promise(resolve =>
            chrome.storage.local.get("audit_context", res => resolve(res.audit_context || {})));
        const benefitStatus = ctx.benefit_coverage?.provider_network_status;
        const providerKnown = Boolean(benefitStatus) && benefitStatus !== "N/A";
        if (providerKnown && !(await selectFinancialsNetwork(benefitStatus))) {
            console.warn(`[Audit] Could not switch maximums & deductibles to ${benefitStatus}; ` +
                         `they are shown for ${financialsNetwork()}.`);
        }

        const data = buildPlanOverviewPayload();
        if (providerKnown) {
            data.provider_info = { ...data.provider_info, provider_network_status: benefitStatus };
        }
        ctx.metlife_data = data;
        const networkMismatch = providerKnown && data.financials_network !== benefitStatus;

        return new Promise((resolve) => {
            chrome.storage.local.set({ audit_context: ctx }, () => {
                const got = Object.values(data.financials).some(f => Object.values(f).some(v => v !== "N/A"));
                let status = got ? `[+] Plan Overview saved (${data.provisions.length} provisions).` : `[!] Saved but financials N/A — stay on Plan Overview and retry.`;
                if (networkMismatch) {
                    status += ` [!] Maximums & deductibles are for ${data.financials_network}, provider is ${benefitStatus} — ` +
                              `set "Show Benefit Maximums & Deductibles for" to ${benefitStatus} and re-run.`;
                }
                resolve({ status });
            });
        });
    }


    // ══════════════════════════════════════════════════════════════════════════
    // LOW-LEVEL: run one batch of codes, click Search, scrape table
    // ══════════════════════════════════════════════════════════════════════════

    // `expectedNetwork` is the selected provider's status; results showing a
    // different network are a table left over from another provider.
    async function runOneBatch(codes, expectedNetwork = "") {
        let codeInput = document.querySelector("input[aria-label='Procedure Code(s)']") ||
            document.querySelector("input[placeholder*='rocedure']") ||
            document.querySelector("input[placeholder*='ode']") ||
            document.querySelector("input[aria-label*='rocedure']") ||
            findInputNearSearchButton();

        if (!codeInput) codeInput = await waitForElement("input[type='text']:not([readonly])", 8000);
        if (!codeInput) {
            console.error("[Audit] Procedure-code input not found.");
            return [];
        }

        const resetBtn = document.querySelector("#search-procedure-form-reset-link") ||
            Array.from(document.querySelectorAll("button,a")).find(el => clean(el.textContent) === "Reset");
        if (resetBtn) {
            resetBtn.click();
            await sleep(500);
        }

        codeInput.focus();
        setReactInputValue(codeInput, "");
        await sleep(200);
        setReactInputValue(codeInput, codes.join(","));
        await sleep(500);

        const searchBtn = document.querySelector(".search-procedure-form__search-btn") ||
            Array.from(document.querySelectorAll("button")).find(
                b => clean(b.textContent) === "Search" && !b.disabled
            );

        if (!searchBtn) {
            console.error("[Audit] Procedure Search button not found/enabled.");
            return [];
        }

        const beforeSignature = procedureTableSignature();
        console.log(`[Audit] Searching ${codes.join(",")}`);
        searchBtn.click();

        const results = await waitForProcedureBatch(codes, beforeSignature, 22000, expectedNetwork);
        console.log(`[Audit] DOM batch: ${codes.join(",")} -> ${results.length} row(s)`);
        return results;
    }

    function procedureTableSignature() {
        const table = document.querySelector("#procedure-code-data-table table");
        if (!table) return "";
        return Array.from(table.querySelectorAll("tbody tr"))
            .map(row => Array.from(row.querySelectorAll("td")).map(td => clean(td.textContent)).join("|")).join("\n");
    }

    function tableNetworkMatches(expectedNetwork) {
        if (!expectedNetwork || expectedNetwork === "N/A") return true;
        const shown = normalizeNetworkStatus(document.querySelector(".table-network-status")?.textContent);
        return !shown || shown === expectedNetwork;
    }

    async function waitForProcedureBatch(codes, beforeSignature = "", timeout = 18000, expectedNetwork = "") {
        const wanted = new Set(codes.map(code => code.toUpperCase()));
        const deadline = Date.now() + timeout;
        const started = Date.now();
        let lastSignature = "";
        let stableSince = 0;
        let bestRows = [];

        while (Date.now() < deadline) {
            const table = document.querySelector("#procedure-code-data-table table");
            const rows = table ? Array.from(table.querySelectorAll("tbody tr")) : [];

            if (rows.length) {
                const parsed = scrapeProcedureTable();
                const rowCodes = parsed.map(r => r.procedure_code.toUpperCase()).filter(Boolean);
                const belongsToCurrentBatch = rowCodes.length > 0 && rowCodes.every(code => wanted.has(code));
                const signature = procedureTableSignature();
                const tableChanged = !beforeSignature || signature !== beforeSignature;

                // "showing N of N results" gives us the rendered result count when available.
                const resultHeader = clean(document.querySelector(".procedure-code-data-table__header-text")?.textContent);
                const countMatch = resultHeader.match(/showing\s+(\d+)\s+of\s+(\d+)\s+results?/i);
                const expectedRenderedRows = countMatch ? Number(countMatch[1]) : null;
                const rowCountReady = expectedRenderedRows == null || parsed.length >= expectedRenderedRows;

                // MetLife answers every code that was asked for, so a table
                // missing one is a table still being painted rather than a
                // plan without that procedure.
                const haveEveryCode = Array.from(wanted).every(code => rowCodes.includes(code));

                // The results carry their own network badge. One that disagrees
                // with the selected provider is from a previous provider.
                const networkMatches = tableNetworkMatches(expectedNetwork);

                if (belongsToCurrentBatch && tableChanged && rowCountReady && networkMatches) {
                    // Keep the best observed value for each row. A real date always beats an empty/dash value.
                    const previousByCode = new Map(bestRows.map(r => [r.procedure_code, r]));
                    bestRows = parsed.map(row => {
                        const previous = previousByCode.get(row.procedure_code);
                        const currentDate = normalizeLateDate(row.late_date_of_service);
                        const previousDate = normalizeLateDate(previous?.late_date_of_service);
                        if (!currentDate && previousDate) {
                            return { ...row, late_date_of_service: previousDate };
                        }
                        return { ...row, late_date_of_service: currentDate || "—" };
                    });

                    if (signature !== lastSignature) {
                        lastSignature = signature;
                        stableSince = Date.now();
                    } else if (!stableSince) {
                        stableSince = Date.now();
                    }

                    // React can paint the row first and populate Late Date Of Service afterwards.
                    // Require the CURRENT result table to remain unchanged for 4 seconds and never
                    // return earlier than 5 seconds after Search. This prevents the all-"—" capture.
                    const stableFor = Date.now() - stableSince;
                    const elapsed = Date.now() - started;
                    // A complete table settles as quickly as it always has; one
                    // still short of a code is given longer before being taken
                    // as final, since a row arriving late looks exactly like a
                    // table that has stopped changing.
                    const settleAfter = haveEveryCode ? 5000 : 9000;
                    if (elapsed >= settleAfter && stableFor >= 4000) {
                        return bestRows;
                    }
                } else {
                    // We are still looking at the previous batch or a partially replaced table.
                    stableSince = 0;
                }
            }

            await sleep(250);
        }

        // Timeout fallback: return only rows that actually belong to this batch,
        // and never rows priced for a different provider's network.
        if (!tableNetworkMatches(expectedNetwork)) {
            console.warn(`[Audit] Results still show a different network than ${expectedNetwork} — discarding.`);
            return [];
        }
        const fallback = scrapeProcedureTable().filter(r => wanted.has(r.procedure_code.toUpperCase()));
        return fallback.length ? fallback : bestRows;
    }


    // ══════════════════════════════════════════════════════════════════════════
    // CRAWL — BENEFIT & COVERAGE  (all batches merged, chunked by 10)
    // ══════════════════════════════════════════════════════════════════════════

    async function crawlBenefitCoverage(extraCodes = "") {
        // Clicking the tab when it is already shown can remount it and drop the
        // provider the user picked, so it is only clicked when needed.
        const tabEl = findByText("Benefit & Coverage Details");
        if (tabEl && !isTabActive("Benefit & Coverage Details")) { tabEl.click(); await sleep(2500); }

        // The provider — and so the network — every search below is priced for.
        // Read from the sticker beside the dropdown, which follows the
        // selection; the results badge only changes after the next search.
        const providerName = selectedProviderName();
        const providerNetworkStatus =
            normalizeNetworkStatus(document.querySelector("#in-network-status-stickers .content")?.textContent)
            || scrapeProviderInfo().provider_network_status;
        console.log(`[Audit] Crawling for provider ${providerName} (${providerNetworkStatus})`);

        // Scrape subscriber — non-fatal, cannot block procedure scraping
        let subscriberInfo = null;
        try {
            subscriberInfo = await scrapeSubscriberFromDropdown();
            console.log("[Audit] Subscriber info:", subscriberInfo);
        } catch (e) {
            console.error("[Audit] Subscriber scrape failed (non-fatal):", e);
        }

        // Save subscriber immediately before batches start
        if (subscriberInfo) {
            await new Promise(resolve => {
                chrome.storage.local.get("audit_context", (res) => {
                    const ctx = res.audit_context || {};
                    ctx.subscriber_info = subscriberInfo;
                    chrome.storage.local.set({ audit_context: ctx }, resolve);
                });
            });
        }

        const extraList = extraCodes
            ? extraCodes.split(",").map(c => c.trim().toUpperCase()).filter(Boolean)
            : [];

        const allCodes = [...new Set([
            ...BATCH_1, ...BATCH_2, ...BATCH_3,
            ...BATCH_4, ...BATCH_5, ...BATCH_6,
            ...BATCH_7, ...BATCH_8, ...extraList
        ])];

        const CHUNK_SIZE = 10;
        const chunks = [];
        for (let i = 0; i < allCodes.length; i += CHUNK_SIZE) {
            chunks.push(allCodes.slice(i, i + CHUNK_SIZE));
        }

        const seen = new Set();
        const allProcedures = [];

        for (let i = 0; i < chunks.length; i++) {
            console.log(`[Audit] Chunk ${i + 1}/${chunks.length}: ${chunks[i].join(",")}`);
            try {
                const batchResults = await runOneBatch(chunks[i], providerNetworkStatus);
                for (const proc of batchResults) {
                    if (!seen.has(proc.procedure_code)) {
                        seen.add(proc.procedure_code);
                        allProcedures.push(proc);
                    }
                }
            } catch (e) {
                console.error(`[Audit] Chunk ${i + 1} failed:`, e);
            }
            if (i < chunks.length - 1) await sleep(1000);
        }

        // Anything the batches did not answer is asked for on its own. The
        // portal returns a row for every code it knows, so a gap here is
        // almost always a row that painted too late to be seen; where the plan
        // genuinely has no such row this search simply comes back empty.
        let unanswered = allCodes.filter(code => !seen.has(code));
        if (unanswered.length) {
            console.warn(`[Audit] ${unanswered.length} code(s) unanswered, retrying one at a time: ${unanswered.join(",")}`);
            for (const code of unanswered) {
                await sleep(800);
                try {
                    for (const proc of await runOneBatch([code], providerNetworkStatus)) {
                        if (!seen.has(proc.procedure_code)) {
                            seen.add(proc.procedure_code);
                            allProcedures.push(proc);
                        }
                    }
                } catch (e) {
                    console.error(`[Audit] Retry for ${code} failed:`, e);
                }
            }
            unanswered = allCodes.filter(code => !seen.has(code));
            if (unanswered.length) {
                console.warn(`[Audit] still unanswered after retry: ${unanswered.join(",")}`);
            }
        }

        const procedureCategories = scrapeProcedureCategories();

        // A provider switched mid-crawl leaves results priced for two networks.
        const providerAtEnd = selectedProviderName();
        const providerChanged = providerAtEnd !== providerName;
        if (providerChanged) {
            console.warn(`[Audit] Provider changed during crawl: ${providerName} -> ${providerAtEnd}. Re-run the crawl.`);
        }

        return new Promise((resolve) => {
            chrome.storage.local.get("audit_context", (res) => {
                const ctx = res.audit_context || {};
                ctx.subscriber_info = subscriberInfo;
                // Only this tab states the selected provider's network, so it
                // replaces whatever the Plan Overview scrape recorded.
                if (providerNetworkStatus !== "N/A" && ctx.metlife_data) {
                    ctx.metlife_data.provider_info = {
                        ...(ctx.metlife_data.provider_info || {}),
                        provider_network_status: providerNetworkStatus,
                    };
                }
                ctx.benefit_coverage = {
                    source: "MetLife Portal - Benefit & Coverage Details",
                    timestamp: new Date().toISOString(),
                    // The Benefit Level / Patient Responsibility columns are for
                    // this network; an out-of-network table has no Network Fee.
                    provider_name: providerName,
                    provider_network_status: providerNetworkStatus,
                    provider_changed_during_crawl: providerChanged,
                    procedure_categories: procedureCategories,
                    codes_searched: allCodes,
                    extra_codes: extraList,
                    // Named rather than left to be noticed by their absence.
                    codes_not_returned: unanswered,
                    procedure_count: allProcedures.length,
                    procedures: allProcedures
                };
                chrome.storage.local.set({ audit_context: ctx }, () => {
                    resolve({ status: providerChanged
                        ? `[!] Provider changed during crawl (${providerName} -> ${providerAtEnd}) — re-run.`
                        : `[+] Scraped ${allProcedures.length} procedures for ${providerName} (${providerNetworkStatus}) across ${chunks.length} chunk(s).` });
                });
            });
        });
    }


    // ══════════════════════════════════════════════════════════════════════════
    // TABLE & INPUT HELPERS
    // ══════════════════════════════════════════════════════════════════════════

    function normalizeLateDate(value) {
        const text = clean(value);
        if (!text || /^(?:—|-|N\/?A|NOT AVAILABLE)$/i.test(text)) return "";

        // Portal currently returns MM/DD/YY (for example 02/02/26).
        // Preserve the portal value instead of letting Date() reinterpret it.
        const match = text.match(/\b(\d{1,2}\/\d{1,2}\/(?:\d{2}|\d{4}))\b/);
        return match ? match[1] : text;
    }

    function getProcedureCell(row, headerId, fallbackIndex) {
        // The MetLife table explicitly links each <td> to its column using headers="...".
        // Prefer that semantic contract; numeric index is only a fallback.
        const semanticCell = row.querySelector(`td[headers="${headerId}"]`);
        if (semanticCell) return clean(semanticCell.textContent || semanticCell.innerText);

        // A row that uses the contract but has no such cell does not have the
        // column. For an out-of-network provider the table drops Network Fee,
        // and falling back by position read Benefit Level in its place.
        if (row.querySelector("td[headers]")) return "";

        const cells = row.querySelectorAll("td");
        return clean(cells[fallbackIndex]?.textContent || cells[fallbackIndex]?.innerText);
    }

    function scrapeProcedureTable() {
        // Scope strictly to the Search Procedures result table. The page contains other tables.
        const table = document.querySelector("#procedure-code-data-table table");
        if (!table) return [];

        const rows = table.querySelectorAll("tbody tr");
        if (!rows.length) return [];

        return Array.from(rows).map(row => {
            // Codes can carry a footnote marker ("D0140*" — limited exams do
            // not share frequency with comprehensive ones). Left on, the row
            // never matched the code that was searched and was discarded.
            const codeText = getProcedureCell(row, "header-procedurecode", 0).toUpperCase();
            const procedureCode = codeText.match(/[A-Z]\d{4}/)?.[0] || codeText;
            if (!procedureCode) return null;
            // The marker's meaning is printed under the table; keep it with the row.
            const footnote = codeText.includes("*")
                ? clean(document.querySelector("#procedure-search-frequency-note")?.textContent) || "*"
                : "";

            const lateDate = normalizeLateDate(
                getProcedureCell(row, "header-latedateofservice", 4)
            );

            return {
                procedure_code: procedureCode,
                description: getProcedureCell(row, "header-description", 1),
                frequency_limit: getProcedureCell(row, "header-frequencylimit", 2),
                age_limit: getProcedureCell(row, "header-agelimit", 3),
                late_date_of_service: lateDate || "—",
                deductible: getProcedureCell(row, "header-deductible", 5) || "N/A",
                network_fee: getProcedureCell(row, "header-networkfee", 6) || "N/A",
                benefit_level: getProcedureCell(row, "header-benefitlevel", 7) || "N/A",
                patient_responsibility: getProcedureCell(row, "header-patientobligation", 8) || "N/A",
                ...(footnote ? { footnote } : {})
            };
        }).filter(Boolean);
    }

    // "Browse by Procedure Categories" cards on the Benefit & Coverage tab. Each
    // card states the in-network and out-of-network benefit separately
    // (MetLife pays / Patient pays / Deductible), which the Covered Services
    // table only gives as one run-on string per network.
    function scrapeProcedureCategories() {
        const cards = document.querySelectorAll(".category-card");
        return Array.from(cards).map(card => {
            const name = clean(card.querySelector("[id='procedure-category__title']")?.textContent);
            if (!name) return null;

            // Label/value spans share one id, so they are paired by order.
            const coverage = {};
            const spans = Array.from(card.querySelectorAll("[id='procedure-category__coverage']"));
            for (let i = 0; i + 1 < spans.length; i += 2) {
                const label = clean(spans[i].textContent).replace(/:\s*$/, "").toLowerCase();
                coverage[label] = clean(spans[i + 1].textContent);
            }

            const network = (title) => {
                const col = card.querySelector(`[id='donut-chart-title-${title}']`)?.closest(".col");
                if (!col) return { metlife_pays: "N/A", patient_pays: "N/A", deductible: "N/A" };
                return {
                    metlife_pays: clean(col.querySelector("[id='donut-chart-percent-0']")?.textContent) || "N/A",
                    patient_pays: clean(col.querySelector("[id='donut-chart-percent-1']")?.textContent) || "N/A",
                    deductible: clean(col.querySelector("[id='donut-chart-deductible-value']")?.textContent) || "N/A",
                };
            };

            return {
                category: name,
                class: clean(card.querySelector("[id='procedure-category__description']")?.textContent) || "N/A",
                frequency_limit: coverage["frequency limit"] || "N/A",
                age_limit: coverage["age limit"] || "N/A",
                in_network: network("IN-NETWORK"),
                out_of_network: network("OUT-OF-NETWORK"),
            };
        }).filter(Boolean);
    }

    function findInputNearSearchButton() {
        const btn = Array.from(document.querySelectorAll("button")).find(b => b.textContent.trim() === "Search");
        if (!btn) return null;
        let parent = btn.parentElement;
        for (let i = 0; i < 5; i++) {
            if (!parent) break;
            const input = parent.querySelector("input[type='text'],input:not([type])");
            if (input) return input;
            parent = parent.parentElement;
        }
        return null;
    }


    // ══════════════════════════════════════════════════════════════════════════
    // PASSIVE BACKGROUND SYNC
    // ══════════════════════════════════════════════════════════════════════════

    // Set while a crawl drives the page. A tick mid-crawl could read the
    // maximums before the network filter is switched and store them after the
    // crawl's own write, just before the JSON is downloaded.
    let crawlInProgress = false;

    async function exclusiveCrawl(run) {
        crawlInProgress = true;
        try {
            return await run();
        } finally {
            crawlInProgress = false;
        }
    }

    setInterval(() => {
        if (!chrome.runtime?.id) return;
        if (crawlInProgress) return;
        if (!(document.body?.innerText || "").includes("Benefit Maximums")) return;
        const data = buildPlanOverviewPayload();
        chrome.storage.local.get("audit_context", (res) => {
            const ctx = res.audit_context || {};
            // The Plan Overview tab does not state the provider's network. The
            // status that belongs in the export is the one the captured
            // procedures were priced for; failing that, one already read for
            // this patient is kept rather than overwritten with N/A.
            const prev = ctx.metlife_data;
            const benefitStatus = ctx.benefit_coverage?.provider_network_status;
            if (benefitStatus && benefitStatus !== "N/A") {
                data.provider_info = { ...data.provider_info, provider_network_status: benefitStatus };
            } else if (data.provider_info.provider_network_status === "N/A" &&
                data.patient.name !== "N/A" &&
                prev?.patient?.name === data.patient.name &&
                prev?.provider_info?.provider_network_status) {
                data.provider_info = prev.provider_info;
            }
            ctx.metlife_data = data;
            chrome.storage.local.set({ audit_context: ctx });
        });
    }, 5000);


    // ══════════════════════════════════════════════════════════════════════════
    // DOWNLOAD HELPER
    // ══════════════════════════════════════════════════════════════════════════

    function downloadAuditJSON() {
        chrome.storage.local.get("audit_context", (res) => {
            const data = res.audit_context || {};
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            const patient = data?.metlife_data?.patient?.name
                ?.replace(/[^a-z0-9]/gi, "_")?.toLowerCase() || "patient";
            a.download = `${patient}_metlife_audit.json`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        });
    }


    // ══════════════════════════════════════════════════════════════════════════
    // MESSAGE LISTENER
    // ══════════════════════════════════════════════════════════════════════════

    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

        if (request.command === "START_CRAWL") {
            exclusiveCrawl(async () => {
                // Benefit & Coverage first, while the provider the user picked
                // is still selected — leaving that tab can reset the dropdown,
                // which priced every procedure for the default provider's
                // network. Plan Overview then merges into the same context and
                // reads maximums & deductibles for that provider's network.
                await new Promise(resolve => chrome.storage.local.set({ audit_context: {} }, resolve));
                const res = await crawlBenefitCoverage("");
                const plan = await crawlPlanOverview(false);
                downloadAuditJSON();
                // Plan Overview's own message only when it has a warning.
                const planNote = plan.status.includes("[!]") ? " " + plan.status : "";
                sendResponse({ status: res.status + planNote + " JSON downloaded." });
            });
            return true;
        }

        if (request.command === "CRAWL_PLAN_OVERVIEW") {
            exclusiveCrawl(() => crawlPlanOverview()).then(sendResponse).catch(() => sendResponse({ status: "[!] Error." }));
            return true;
        }

        if (request.command === "CRAWL_BENEFIT_COVERAGE") {
            exclusiveCrawl(() => crawlBenefitCoverage(request.extraCodes || "")).then(sendResponse).catch(() => sendResponse({ status: "[!] Error." }));
            return true;
        }
    });
})();
