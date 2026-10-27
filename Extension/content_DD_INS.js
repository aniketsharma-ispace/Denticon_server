// content_delta_dental.js - V2.0 (Complete Delta Dental Benefits Auditor)

(() => {
    // This one file runs twice on deltadentalins.com (see manifest.json):
    //   MAIN world, document_start   installPageHook: keeps a copy of the
    //                                portal's own benefit responses as the page
    //                                receives them.
    //   ISOLATED world               the scraper, popup messaging and storage.
    // Only the isolated copy can see the extension runtime. Everything sits in
    // this function so the page-world copy declares nothing in the page's globals.
    const HOOK_SOURCE = "dd-ins-hook";
    const SCRAPER_SOURCE = "dd-ins-scraper";

    const hasExtensionRuntime = Boolean(
        typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.id
    );
    if (!hasExtensionRuntime) {
        installPageHook();
        return;
    }

    // Benefits Search on deltadentalins.com never asks the server anything: the
    // search box only filters what the page fetched when the patient was opened.
    //
    //   benefits/benefits-package  every procedure of the plan, all three networks
    //   benefits/other-procedures  codes the plan does not pay for, with the reason
    //   treatment-history          the patient's claims, approved and denied
    //
    // This hook keeps the last copy of each response as the page receives it, so
    // the scraper can read every sheet code without typing a single search. It
    // never sends a request of its own and never alters what the page sees.
    function installPageHook() {
        if (window.__DD_INS_HOOK__) return;
        window.__DD_INS_HOOK__ = true;

        const WATCHED = /\/provider-tools\/v2\/api\/(?:benefits\/(benefits-package|other-procedures)|(treatment-history))(?:[?#]|$)/;

        const captured = {};

        const keyFor = (url) => {
            const m = String(url || "").match(WATCHED);
            return m ? (m[1] || m[2]) : null;
        };

        const keep = (url, text) => {
            const key = keyFor(url);
            if (!key || !text) return;
            try {
                captured[key] = { at: Date.now(), body: JSON.parse(text) };
            } catch (e) {
                // Not JSON: nothing the scraper could use.
            }
        };

        const nativeFetch = window.fetch;
        if (typeof nativeFetch === "function") {
            window.fetch = function (input, init) {
                const pending = nativeFetch.apply(this, arguments);
                const url = typeof input === "string" ? input : (input && input.url);
                if (keyFor(url)) {
                    pending.then(response => {
                        if (response.ok) response.clone().text().then(text => keep(url, text)).catch(() => {});
                    }).catch(() => {});
                }
                return pending;
            };
        }

        const nativeOpen = XMLHttpRequest.prototype.open;
        const nativeSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open = function (method, url) {
            this.__ddInsUrl = url;
            return nativeOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function () {
            if (keyFor(this.__ddInsUrl)) {
                this.addEventListener("load", () => {
                    if (this.status < 200 || this.status >= 300) return;
                    try {
                        if (this.responseType === "" || this.responseType === "text") keep(this.__ddInsUrl, this.responseText);
                        else if (this.responseType === "json") keep(this.__ddInsUrl, JSON.stringify(this.response));
                    } catch (e) {
                        // Unreadable response: the scraper falls back to the page.
                    }
                });
            }
            return nativeSend.apply(this, arguments);
        };

        window.addEventListener("message", event => {
            if (event.source !== window || event.origin !== window.location.origin) return;
            if (event.data?.source !== SCRAPER_SOURCE || event.data.type !== "GET_CAPTURED") return;
            window.postMessage({
                source: HOOK_SOURCE,
                type: "CAPTURED",
                requestId: event.data.requestId,
                captured
            }, window.location.origin);
        });
    }


    const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');
    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    // CDT codes to search for: every code any client's sheet in "Updated Sabrina
    // Codes & C Q's Data - All Clients" asks for, plus the Toolkit's supplemental
    // codes, read from the same bundled spec the Toolkit uses
    // (toolkit_requirements.generated.js). The list is never edited here: change
    // the workbook and regenerate the spec, and both scrapers follow.
    const REQUIREMENTS_SPEC = globalThis.__DELTA_TOOLKIT_REQUIREMENTS_SPEC__ || null;
    // The codes this scraper searched before it read the spec. Used only if the
    // spec failed to load, so a packaging mistake costs codes rather than the run.
    const LEGACY_CODES = [
        "D0120", "D0180", "D0140", "D0150", "D0274", "D0210", "D0330", "D0220", "D0230", "D0240",
        "D1110", "D1120", "D1206", "D1351", "D1510", "D2140", "D2331", "D2620", "D2740", "D2950",
        "D3310", "D3330", "D3347", "D4260", "D4341", "D4355", "D4381", "D4910", "D5110", "D7953",
        "D5740", "D6010", "D6056", "D6065", "D6194", "D6245", "D7140", "D7240", "D7210", "D6750",
        "D7259", "D8010", "D8080", "D8090", "D9110", "D9222", "D9230", "D9243", "D9310", "D4346",
        "D9944", "D0364", "D0431", "D2391", "D2962", "D4249",
        "D2160", "D2980", "D5212", "D5899", "D5995", "D1208"
    ];
    const SHEET_CODES = (() => {
        const universe = REQUIREMENTS_SPEC?.code_universe;
        const codes = [
            ...(Array.isArray(universe?.mandatory_codes) ? universe.mandatory_codes : []),
            ...(Array.isArray(universe?.supplemental_codes) ? universe.supplemental_codes : [])
        ].map(code => String(code).toUpperCase()).filter(code => /^D\d{4}$/.test(code));
        if (!codes.length) {
            console.error("Delta Dental: requirements spec missing; searching the legacy code list only.");
            return [...new Set(LEGACY_CODES)].sort();
        }
        return [...new Set(codes)].sort();
    })();
    // The search box takes ten codes at a time.
    const BATCHES = Array.from({ length: Math.ceil(SHEET_CODES.length / 10) },
        (_, i) => SHEET_CODES.slice(i * 10, i * 10 + 10));
    console.log(`Delta Dental scraper V2.0 initialized - ${SHEET_CODES.length} sheet codes - Ready to audit benefits`);

    // ══════════════════════════════════════════════════════════════════════════
    // HELPER: Extract all static fields from patient card
    // ══════════════════════════════════════════════════════════════════════════

    function extractStaticFields(cardElement) {
        /**
         * Extract all pt-staticfield label/value pairs from a patient card
         */
        const fields = {};
        const staticFieldElements = cardElement.querySelectorAll('.pt-staticfield');

        staticFieldElements.forEach(el => {
            const label = el.querySelector('.pt-staticfield-label')?.innerText || "";
            const value = el.querySelector('.pt-staticfield-text')?.innerText || "";
            if (label && value) {
                fields[clean(label)] = clean(value);
            }
        });

        return fields;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // HELPER: Scrape member / eligibility information
    // ══════════════════════════════════════════════════════════════════════════

    function scrapeEligibilityInfo() {
        // Collect all pt-staticfield label→value pairs from the entire visible page
        const raw = {};
        document.querySelectorAll('.pt-staticfield').forEach(el => {
            const label = clean(el.querySelector('.pt-staticfield-label')?.innerText || "");
            const value = clean(el.querySelector('.pt-staticfield-text')?.innerText || "");
            if (label) raw[label] = value || "N/A";
        });

        // Alias map: output key → list of possible label strings (case-insensitive)
        const aliases = {
            member_id:              ["Member ID", "Member Number", "Member #", "Subscriber ID"],
            relation_to_subscriber: ["Relation to Subscriber", "Relationship", "Relationship to Subscriber"],
            subscriber_name:        ["Subscriber Name", "Subscriber"],
            patient_dob:            ["Date of Birth", "Patient Date of Birth", "DOB", "Patient DOB"],
            subscriber_dob:         ["Subscriber Date of Birth", "Subscriber DOB"],
            ssn:                    ["SSN", "Social Security Number", "Social Security #"],
            group_name:             ["Group Name", "Employer", "Employer Name"],
            group_number:           ["Group Number", "Group #", "Group ID", "Group No"],
            effective_date:         ["Patient Effective Date", "Effective Date", "Coverage Begin Date", "Coverage Effective Date"],
            termination_date:       ["Patient Termination Date", "Termination Date", "Coverage End Date", "Coverage Termination Date"],
            network_status:         ["Provider Network Status", "Network Status", "Network", "Provider Status"],
        };

        const eligibility = {};
        for (const [key, labels] of Object.entries(aliases)) {
            for (const label of labels) {
                const found = Object.keys(raw).find(k => k.toLowerCase() === label.toLowerCase());
                if (found) { eligibility[key] = raw[found]; break; }
            }
            // Try data-testid fallbacks if still not found
            if (!eligibility[key]) {
                const testIds = [
                    key.replace(/_/g, ''),            // memberId
                    key.replace(/_([a-z])/g, (_, c) => c.toUpperCase()), // memberDob
                ];
                for (const tid of testIds) {
                    const el = document.querySelector(`[data-testid="${tid}"], [data-testid="${tid}Field"]`);
                    if (el) { eligibility[key] = clean(el.innerText) || "N/A"; break; }
                }
            }
            if (!eligibility[key]) eligibility[key] = "N/A";
        }

        // Preserve all raw fields so nothing is silently dropped
        eligibility.all_fields = raw;
        return eligibility;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STEP 1: PATIENT CARD SCRAPER
    // ══════════════════════════════════════════════════════════════════════════

    function scrapePatientCard(cardElement) {
        /**
         * Scrape a single patient card: name, plan, group, and all static fields
         */
        if (!cardElement) return null;

        const header = cardElement.querySelector('.patient-card-header');
        const body = cardElement.querySelector('.patient-card-body');

        // Extract name (MuiTypography-h3)
        const nameEl = header?.querySelector('.MuiTypography-h3');
        const name = nameEl ? clean(nameEl.innerText) : "N/A";

        // Extract plan (body2 under d-flex)
        const planEl = header?.querySelector('.d-flex .MuiTypography-body2');
        const plan = planEl ? clean(planEl.innerText).replace(/^Plan:\s*/i, '') : "N/A";

        // Extract group (body2 after d-flex)
        const groupEl = Array.from(header?.querySelectorAll('.MuiTypography-body2') || []).find(el => 
            clean(el.innerText).toLowerCase().includes('group:')
        );
        const group = groupEl ? clean(groupEl.innerText).replace(/^Group:\s*/i, '') : "N/A";

        // Extract all static fields
        const staticFields = extractStaticFields(body);

        return {
            name,
            plan,
            group,
            static_fields: staticFields
        };
    }

    function scrapeAllPatientCards() {
        /**
         * Scrape all patient cards on the page
         */
        const patientCards = [];
        const cardElements = document.querySelectorAll('[data-testid^="patientCard_"]');

        cardElements.forEach(el => {
            const card = scrapePatientCard(el);
            if (card) patientCards.push(card);
        });

        return patientCards;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STEP 3: OVERVIEW TAB SCRAPER
    // ══════════════════════════════════════════════════════════════════════════

    function scrapeOverviewTab() {
        /**
         * Scrape benefits overview, maximums, deductibles, package history, claims address
         */
        const overview = {};

        // ── Benefits Overview Table ──
        const benefitsTable = document.querySelector('[data-testid="benefitsOverviewTable"]');
        if (benefitsTable) {
            const rows = benefitsTable.querySelectorAll('tbody tr');
            const benefitsOverview = [];

            rows.forEach((row, index) => {
                // Skip header row (row with network names in cells instead of treatment type)
                if (index === 0 && row.innerText.includes("Delta Dental PPO Dentist")) {
                    return; // Skip this header row
                }

                const thCell = row.querySelector('th');
                const tdCells = row.querySelectorAll('td');

                if (thCell && tdCells.length >= 3) {
                    benefitsOverview.push({
                        treatment_type: clean(thCell.innerText) || "N/A",
                        contract_benefit_level: clean(tdCells[0]?.innerText) || "N/A",
                        delta_dental_premier: clean(tdCells[1]?.innerText) || "N/A",
                        non_delta_dental: clean(tdCells[2]?.innerText) || "N/A"
                    });
                }
            });
            overview.benefits_overview = benefitsOverview;
        }

        // ── Maximums Table ──
        const maximumsTable = document.querySelector('[data-testid="maximumsTable"]');
        if (maximumsTable) {
            const rows = maximumsTable.querySelectorAll('tbody tr');
            const maximums = [];

            rows.forEach((row, index) => {
                // Skip header row - contains "Type", "Treatment type", "Network", "Amount"
                if (index === 0 && row.innerText.includes("Treatment type") && row.innerText.includes("Amount")) {
                    return;
                }

                const thCell = row.querySelector('th');
                const tdCells = row.querySelectorAll('td');

                if (thCell && tdCells.length >= 5) {
                    // Extract type info from th
                    const typeText = clean(thCell.innerText) || "N/A";

                    // Extract treatment types from second cell (divs with links or text)
                    const treatmentTypesDiv = tdCells[0];
                    const treatmentTypes = [];
                    if (treatmentTypesDiv) {
                        treatmentTypesDiv.querySelectorAll('a, p').forEach(el => {
                            const text = clean(el.innerText);
                            if (text && !treatmentTypes.includes(text)) {
                                treatmentTypes.push(text);
                            }
                        });
                    }

                    // Extract networks from third cell
                    const networksDiv = tdCells[1];
                    const networks = [];
                    if (networksDiv) {
                        networksDiv.querySelectorAll('div').forEach(el => {
                            const text = clean(el.innerText);
                            if (text && !networks.includes(text)) {
                                networks.push(text);
                            }
                        });
                    }

                    maximums.push({
                        type: typeText,
                        treatment_types: treatmentTypes,
                        networks: networks,
                        amount: clean(tdCells[2]?.innerText) || "N/A",
                        used: clean(tdCells[3]?.innerText) || "N/A",
                        remaining: clean(tdCells[4]?.innerText) || "N/A"
                    });
                }
            });
            overview.maximums = maximums;
        }

        // ── Deductibles Table ──
        const deductiblesTable = document.querySelector('[data-testid="deductiblesTable"]');
        if (deductiblesTable) {
            const rows = deductiblesTable.querySelectorAll('tbody tr');
            const deductibles = [];

            rows.forEach((row, index) => {
                // Skip header row - contains "Type", "Treatment type", "Network", "Amount"
                if (index === 0 && row.innerText.includes("Treatment type") && row.innerText.includes("Amount")) {
                    return;
                }

                const thCell = row.querySelector('th');
                const tdCells = row.querySelectorAll('td');

                if (thCell && tdCells.length >= 5) {
                    const typeText = clean(thCell.innerText) || "N/A";

                    const treatmentTypesDiv = tdCells[0];
                    const treatmentTypes = [];
                    if (treatmentTypesDiv) {
                        treatmentTypesDiv.querySelectorAll('a, p').forEach(el => {
                            const text = clean(el.innerText);
                            if (text && !treatmentTypes.includes(text)) {
                                treatmentTypes.push(text);
                            }
                        });
                    }

                    const networksDiv = tdCells[1];
                    const networks = [];
                    if (networksDiv) {
                        networksDiv.querySelectorAll('div').forEach(el => {
                            const text = clean(el.innerText);
                            if (text && !networks.includes(text)) {
                                networks.push(text);
                            }
                        });
                    }

                    deductibles.push({
                        type: typeText,
                        treatment_types: treatmentTypes,
                        networks: networks,
                        amount: clean(tdCells[2]?.innerText) || "N/A",
                        used: clean(tdCells[3]?.innerText) || "N/A",
                        remaining: clean(tdCells[4]?.innerText) || "N/A"
                    });
                }
            });
            overview.deductibles = deductibles;
        }

        // ── Benefit Package History Table ──
        const historyTable = document.querySelector('[data-testid="benefitPackageHistoryTable"]');
        if (historyTable) {
            const rows = historyTable.querySelectorAll('tbody tr');
            const history = [];

            rows.forEach((row, index) => {
                // Skip header row if present
                if (index === 0 && (row.innerText.includes("Effective") || row.innerText.includes("Benefit Package"))) {
                    return;
                }

                const thCell = row.querySelector('th');
                const tdCells = row.querySelectorAll('td');

                if (thCell && tdCells.length >= 2) {
                    history.push({
                        effective_date: clean(thCell.innerText) || "N/A",
                        end_date: clean(tdCells[0]?.innerText) || "N/A",
                        benefit_package: clean(tdCells[1]?.innerText) || "N/A"
                    });
                }
            });
            overview.benefit_package_history = history;
        }

        // ── Claims Mailing Address ──
        const claimsAddress = document.querySelector('[data-testid="claimsMailingAddress"]');
        if (claimsAddress) {
            const addressLines = [];
            claimsAddress.querySelectorAll('p').forEach(p => {
                const text = clean(p.innerText);
                if (text) addressLines.push(text);
            });
            overview.claims_mailing_address = addressLines;
        }

        // ── Deductible Applicability (Preventive / Diagnostic) ──
        // Scan the full page text for these flags; they appear near the deductibles section
        const pageText = document.body.innerText || "";
        const deductibleApplicability = {};

        // Pattern: "Deductible Applies to Preventive: Yes/No" or adjacent labeled elements
        const deductibleEls = document.querySelectorAll('.pt-staticfield, [data-testid*="deductible"]');
        deductibleEls.forEach(el => {
            const label = clean(el.querySelector('.pt-staticfield-label')?.innerText || el.innerText || "").toLowerCase();
            const value = clean(el.querySelector('.pt-staticfield-text')?.innerText || "");
            if (label.includes("deductible") && label.includes("preventive")) {
                deductibleApplicability.applies_to_preventive = value || "N/A";
            }
            if (label.includes("deductible") && label.includes("diagnostic")) {
                deductibleApplicability.applies_to_diagnostic = value || "N/A";
            }
        });

        // Regex fallback on raw page text
        if (!deductibleApplicability.applies_to_preventive) {
            const m = pageText.match(/deductible\s+applies?\s+to\s+preventive[:\s]+(\w+)/i);
            deductibleApplicability.applies_to_preventive = m ? m[1] : "N/A";
        }
        if (!deductibleApplicability.applies_to_diagnostic) {
            const m = pageText.match(/deductible\s+applies?\s+to\s+diagnostic[:\s]+(\w+)/i);
            deductibleApplicability.applies_to_diagnostic = m ? m[1] : "N/A";
        }
        overview.deductible_applicability = deductibleApplicability;

        return overview;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STEP 4: PLAN PROVISIONS TAB SCRAPER
    // ══════════════════════════════════════════════════════════════════════════

    function scrapePlanProvisionsTab() {
        /**
         * Scrape plan provisions table (provision name + description)
         */
        const provisionsTable = document.querySelector('[data-testid="planProvisionsTable"]');
        if (!provisionsTable) return [];

        const rows = provisionsTable.querySelectorAll('tbody tr');
        const provisions = [];

        rows.forEach(row => {
            const cells = row.querySelectorAll('td, th');
            if (cells.length >= 2) {
                provisions.push({
                    provision_name: clean(cells[0]?.innerText) || "N/A",
                    description: clean(cells[1]?.innerText) || "N/A"
                });
            }
        });

        return provisions;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STEP 5: WAITING PERIODS TAB SCRAPER
    // ══════════════════════════════════════════════════════════════════════════

    function scrapeWaitingPeriodsTab() {
        const table =
            document.querySelector('[data-testid="waitingPeriodsTable"]') ||
            Array.from(document.querySelectorAll("table")).find(t =>
                /Waiting period begins/i.test(t.innerText) &&
                /Waiting period ends/i.test(t.innerText)
            );

        if (!table) {
            return {
                rows: [],
                note: "Waiting periods table not found"
            };
        }

        const results = [];

        table.querySelectorAll("tbody tr").forEach(row => {
            const headerCell = row.querySelector("th");
            const cells = row.querySelectorAll("td");

            if (!headerCell || cells.length < 2) return;

            const treatmentGroups = [];

            let current = null;

            Array.from(headerCell.children).forEach(el => {
                const text = clean(el.innerText);
                if (!text) return;

                if (/^D\d{4}/i.test(text)) {
                    if (current) {
                        current.procedure_codes = text;
                    }
                } else {
                    current = {
                        treatment_type: text,
                        procedure_codes: ""
                    };
                    treatmentGroups.push(current);
                }
            });

            // Fallback if there are no child elements
            if (treatmentGroups.length === 0) {
                const lines = headerCell.innerText
                    .split("\n")
                    .map(clean)
                    .filter(Boolean);

                for (let i = 0; i < lines.length; i++) {
                    if (/^D\d{4}/i.test(lines[i])) continue;

                    treatmentGroups.push({
                        treatment_type: lines[i],
                        procedure_codes:
                            i + 1 < lines.length &&
                            /^D\d{4}/i.test(lines[i + 1])
                                ? lines[++i]
                                : ""
                    });
                }
            }

            results.push({
                treatments_and_procedures: treatmentGroups,
                waiting_period_begins: clean(cells[0].innerText),
                waiting_period_ends: clean(cells[1].innerText)
            });
        });

        return {
            rows: results
        };
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STEP 5b: TREATMENT HISTORY TAB SCRAPER
    // ══════════════════════════════════════════════════════════════════════════

    const TREATMENT_HISTORY_HEADER_MAP = {
        "description": "description",
        "limitation": "limitation",
        "limitation may also apply to": "limitation_may_also_apply_to",
        "service date": "service_date",
        "tooth code": "tooth_code",
        "tooth description": "tooth_description",
        "tooth surface": "tooth_surface"
    };

    function isTreatmentHistoryTable(table) {
        const headerText = clean(
            Array.from(table.querySelectorAll('thead th, thead td'))
                .map(c => c.innerText)
                .join(' ')
        ).toLowerCase();
        return headerText.includes('description') &&
            headerText.includes('limitation') &&
            headerText.includes('service date');
    }

    function findTreatmentHistoryTables() {
        return Array.from(document.querySelectorAll('table')).filter(isTreatmentHistoryTable);
    }

    function findTreatmentHistoryCard(table) {
        let card = table;
        let parent = card.parentElement;
        while (parent) {
            const qualifyingInParent = Array.from(parent.querySelectorAll('table')).filter(isTreatmentHistoryTable);
            if (qualifyingInParent.length > 1) break;
            card = parent;
            parent = parent.parentElement;
        }
        return card;
    }

    function extractCardCode(card, table) {
        const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            if (table.contains(node)) continue;
            const match = clean(node.textContent).match(/\b(D\d{3,4})\b/);
            if (match) return match[1];
        }
        const fallback = clean(card.innerText).match(/\b(D\d{3,4})\b/);
        return fallback ? fallback[1] : "N/A";
    }

    async function waitForTreatmentHistoryTables(maxWaitMs = 8000) {
        let lastCount = -1;
        let stableTicks = 0;
        const start = Date.now();

        while (Date.now() - start < maxWaitMs) {
            const count = findTreatmentHistoryTables().length;
            if (count > 0 && count === lastCount) {
                stableTicks++;
                if (stableTicks >= 2) break;
            } else {
                stableTicks = 0;
            }
            lastCount = count;
            await sleep(400);
        }

        return findTreatmentHistoryTables();
    }

    async function scrapeTreatmentHistoryTab() {
        const tables = await waitForTreatmentHistoryTables();

        if (tables.length === 0) {
            return { procedures: [], note: "No treatment history cards found" };
        }

        const procedures = [];
        const seenCodes = new Set();

        tables.forEach(table => {
            const card = findTreatmentHistoryCard(table);
            const code = extractCardCode(card, table);

            if (seenCodes.has(code)) return;
            seenCodes.add(code);

            const { headers, rows } = parseTreatmentHistoryTable(table);
            procedures.push({ code, headers, rows });
        });

        return { procedures };
    }

    function parseTreatmentHistoryTable(table) {
        let headerCells = Array.from(table.querySelectorAll('thead th, thead td'));
        let bodyRows = Array.from(table.querySelectorAll('tbody tr'));

        if (headerCells.length === 0 && bodyRows.length) {
            const firstRowCells = Array.from(bodyRows[0].querySelectorAll('th, td'));
            const looksLikeHeader = firstRowCells.some(cell =>
                /description|limitation|service date|tooth/i.test(clean(cell.innerText))
            );
            if (looksLikeHeader) {
                headerCells = firstRowCells;
                bodyRows = bodyRows.slice(1);
            }
        }

        const headers = headerCells.map(cell => clean(cell.innerText));

        // rowspan/colspan-aware grid — a physical <tr> can be missing cells that a
        // previous row's rowspan is still covering, so positional cells.forEach()
        // silently shifts everything left. Expand into a virtual grid instead.
        const grid = [];
        bodyRows.forEach((row, rowIndex) => {
            if (!grid[rowIndex]) grid[rowIndex] = [];
            let colIndex = 0;
            Array.from(row.querySelectorAll('th, td')).forEach(cell => {
                while (grid[rowIndex][colIndex] !== undefined) colIndex++;
                const text = clean(cell.innerText);
                const rowSpan = cell.rowSpan || 1;
                const colSpan = cell.colSpan || 1;
                for (let r = 0; r < rowSpan; r++) {
                    if (!grid[rowIndex + r]) grid[rowIndex + r] = [];
                    for (let c = 0; c < colSpan; c++) {
                        grid[rowIndex + r][colIndex + c] = text;
                    }
                }
                colIndex += colSpan;
            });
        });

        const rows = grid.map(cellValues => {
            const entry = {};
            cellValues.forEach((value, index) => {
                const rawHeader = headers[index] ? clean(headers[index]).toLowerCase() : "";
                const key = TREATMENT_HISTORY_HEADER_MAP[rawHeader] ||
                    rawHeader.replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') ||
                    `col_${index}`;
                entry[key] = value || "N/A";
            });
            return entry;
        }).filter(row => Object.keys(row).length);

        return { headers, rows };
    }
    // ══════════════════════════════════════════════════════════════════════════
    // STEP 6: BENEFITS SEARCH TAB SCRAPER
    // ══════════════════════════════════════════════════════════════════════════

    async function searchBenefitCodes(codes) {
        const searchInput = document.querySelector('[data-testid="autocompleteSearchInput"]');
        const searchButton = document.querySelector('[data-testid="autocompleteSearchButton"]');

        if (!searchInput || !searchButton) {
            console.warn("Cannot find search input or button");
            return [];
        }

    // Activate the input first
    searchInput.focus();
    searchInput.click();
    await sleep(500);

    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;

    setter.call(searchInput, "");
    searchInput.dispatchEvent(new Event("input", { bubbles: true }));
    searchInput.dispatchEvent(new Event("change", { bubbles: true }));
    await sleep(800);

    const codeString = codes.join(",");
    console.log(`Searching batch: ${codeString}`);

    setter.call(searchInput, codeString);
    searchInput.dispatchEvent(new Event("input", { bubbles: true }));
    searchInput.dispatchEvent(new Event("change", { bubbles: true }));
    await sleep(800);

    // Guard: if React stomped the value, retry once
    if (searchInput.value !== codeString) {
        setter.call(searchInput, codeString);
        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
        searchInput.dispatchEvent(new Event("change", { bubbles: true }));
        await sleep(500);
    }

    searchButton.click();

        // Wait for all results to render (~500ms per code + 2s base)
        await sleep(2000 + codes.length * 500);

        const container = document.querySelector('.search-results-root');
        if (!container) return [];

        const footnotes = collectFootnoteDefinitions(container);
        const expanded = await expandLimitationLinks(container);

        return parseMultipleBenefitResults(container, footnotes, expanded);
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Footnotes
    //
    // Each result card prints "Contract benefit level percentage covered by Delta
    // Dental" followed by superscript numbers, and the numbers are footed out once
    // at the bottom of the page:
    //
    //     1 Amount does not apply to deductible
    //     2 Amount does not apply to maximum
    //
    // The card text alone never contains those sentences, so reading it always
    // concluded that both applied. Whether the deductible comes out of preventive
    // and diagnostic work, and whether preventive draws the annual maximum down,
    // are read off exactly these two footnotes.
    // ──────────────────────────────────────────────────────────────────────────

    function collectFootnoteDefinitions(container) {
        const definitions = {};
        const text = (container.innerText || "");
        const re = /(?:^|\n)\s*(\d)\s*(Amount does not apply to [^\n]+)/g;
        let m;
        while ((m = re.exec(text)) !== null) {
            definitions[m[1]] = clean(m[2]);
        }
        return definitions;
    }

    function cardFootnoteMarkers(cardEl) {
        if (!cardEl) return [];
        const sups = Array.from(cardEl.querySelectorAll("sup"))
            .map(el => clean(el.innerText))
            .filter(t => /^\d$/.test(t));
        if (sups.length) return Array.from(new Set(sups));
        // Some builds render the markers as plain text rather than <sup>.
        const m = (cardEl.innerText || "").match(/covered by Delta Dental\s*([\d\s]+)/);
        if (!m) return [];
        return Array.from(new Set(
            m[1].trim().split(/\s+/).filter(t => /^\d$/.test(t))));
    }

    // ──────────────────────────────────────────────────────────────────────────
    // "Limitations apply"
    //
    // Where a code carries more than one limitation Delta shows a link reading
    // "Limitations apply" instead of the sentence, and the sentences only appear
    // once it is opened. A cell that reads exactly that and nothing else is the
    // portal withholding the limit, so each one is opened and read.
    //
    // Anything unexpected leaves the page as it was and the code keeps whatever
    // the cell already said, so a change to the portal can only cost this detail —
    // never the scrape.
    // ──────────────────────────────────────────────────────────────────────────

    function codeForElement(el, container) {
        let node = el;
        while (node && node !== container) {
            const m = (node.innerText || "").match(/\b(D\d{3,4})\b/);
            if (m) return m[1];
            node = node.parentElement;
        }
        return null;
    }

    function readLimitationPanel(container) {
        // The opened panel repeats the code as a heading and lists the limitations
        // in a table whose first column is "Limitation".
        const tables = Array.from(document.querySelectorAll("table"))
            .filter(t => !container.contains(t));
        const sentences = [];
        tables.forEach(table => {
            const headers = Array.from(table.querySelectorAll("thead th, thead td"))
                .map(th => clean(th.innerText).toLowerCase());
            if (!headers.length || headers[0] !== "limitation") return;
            table.querySelectorAll("tbody tr").forEach(row => {
                const first = row.querySelector("th, td");
                const text = clean(first ? first.innerText : "");
                if (text && !/^limitations apply$/i.test(text)) sentences.push(text);
            });
        });
        return sentences;
    }

    function dismissLimitationPanel() {
        const close = document.querySelector(
            '[data-testid*="close"], [aria-label*="lose"], .modal-close, button.close');
        if (close) {
            close.click();
            return;
        }
        document.body.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    }

    async function expandLimitationLinks(container) {
        const expanded = new Map();
        let cells;
        try {
            cells = Array.from(container.querySelectorAll("td, th"))
                .filter(cell => /^limitations apply$/i.test(clean(cell.innerText)));
        } catch (e) {
            return expanded;
        }

        for (const cell of cells) {
            try {
                const code = codeForElement(cell, container);
                if (!code || expanded.has(code)) continue;
                const target = cell.querySelector("a, button") || cell;
                target.click();
                await sleep(1200);
                const sentences = readLimitationPanel(container);
                if (sentences.length) {
                    expanded.set(code, sentences.join(" "));
                    console.log(`Limitations for ${code}: ${sentences.join(" | ")}`);
                }
                dismissLimitationPanel();
                await sleep(600);
            } catch (e) {
                console.warn("Could not open a limitation link:", e);
                try { dismissLimitationPanel(); } catch (e2) { /* nothing to close */ }
            }
        }
        return expanded;
    }

    function parseMultipleBenefitResults(container, footnotes, expanded) {
        footnotes = footnotes || {};
        expanded = expanded || new Map();
        const resultsByCode = new Map();

        const addResult = (parsed) => {
            if (!parsed) return;

            if (resultsByCode.has(parsed.code)) {
                const existing = resultsByCode.get(parsed.code);

                // Merge rows for duplicate codes
                existing.rows.push(...parsed.rows);

                // Keep the first valid benefit level if current is N/A
                if (
                    existing.benefit_level === "N/A" &&
                    parsed.benefit_level !== "N/A"
                ) {
                    existing.benefit_level = parsed.benefit_level;
                }

                // Prefer "Does not apply" if any table reports it
                if (parsed.deductible === "Does not apply") {
                    existing.deductible = "Does not apply";
                }
                ["applies_to_deductible", "applies_to_maximum"].forEach(key => {
                    if (!existing[key] && parsed[key]) existing[key] = parsed[key];
                });
            } else {
                resultsByCode.set(parsed.code, parsed);
            }
        };

        // ───────────────────────────────────────────────────────────
        // Strategy 1: each direct child is one result card
        // ───────────────────────────────────────────────────────────
        const directChildren = Array.from(container.children)
            .filter(el => /\bD\d{3,4}\b/.test(el.innerText));

        if (directChildren.length > 0) {
            directChildren.forEach(card => {
                const match = (card.innerText || "").match(/\b(D\d{3,4})\b/);
                if (!match) return;

                const code = match[1];

                card.querySelectorAll("table").forEach(table => {
                    const parsed = parseTableContent(table, code, card, footnotes, expanded);
                    addResult(parsed);
                });
            });

            if (resultsByCode.size > 0) {
                return Array.from(resultsByCode.values());
            }
        }

        // ───────────────────────────────────────────────────────────
        // Strategy 2: find cards from tables
        // ───────────────────────────────────────────────────────────
        const seen = new Set();

        container.querySelectorAll("table").forEach(table => {
            let card = table;

            while (card.parentElement && card.parentElement !== container) {
                card = card.parentElement;
            }

            if (seen.has(card)) return;
            seen.add(card);

            const match = (card.innerText || "").match(/\b(D\d{3,4})\b/);
            if (!match) return;

            const code = match[1];

            card.querySelectorAll("table").forEach(t => {
                const parsed = parseTableContent(t, code, card, footnotes, expanded);
                addResult(parsed);
            });
        });

        return Array.from(resultsByCode.values());
    }

    function parseTableContent(table, code, cardEl, footnotes, expanded) {
        // cardEl is the isolated card element for this code — use it for metadata
        footnotes = footnotes || {};
        expanded = expanded || new Map();
        const contextText = (cardEl || table).innerText || "";

        const pctMatch = contextText.match(/(\d+)%/);
        const benefit_level = pctMatch ? pctMatch[1] + "%" : "N/A";

        // The card's superscripts, resolved against the page's footnote list.
        const notes = cardFootnoteMarkers(cardEl)
            .map(marker => (footnotes[marker] || "").toLowerCase());
        const footnotesRead = Object.keys(footnotes).length > 0;
        const notDeductible = notes.some(t => t.includes("deductible")) ||
            contextText.includes("Amount does not apply to deductible");
        const notMaximum = notes.some(t => t.includes("maximum"));

        const deductible = notDeductible ? "Does not apply" : "Applies";
        // Left empty where no footnote list was found at all, so that an export
        // made by an older build reads as "the portal did not say" rather than as
        // a confident "Yes".
        const applies_to_deductible = footnotesRead ? (notDeductible ? "No" : "Yes") : "";
        const applies_to_maximum = footnotesRead ? (notMaximum ? "No" : "Yes") : "";

        // The sentence behind the "Limitations apply" link, where one was read.
        const expandedLimitation = expanded.get(code) || "";
        const withLimitation = (stated) => {
            if (!expandedLimitation) return stated;
            if (!stated || stated === "None" || /^limitations apply$/i.test(stated)) {
                return expandedLimitation;
            }
            return stated;
        };

        const headers = [];
        table.querySelectorAll("thead th, thead td").forEach(th => {
            headers.push(clean(th.innerText).toLowerCase());
        });

        // Handle "Comments" tables (invalid procedure codes)
        if (headers.length === 1 && headers[0] === "comments") {
            const comment = clean(table.querySelector("tbody")?.innerText || "");
            return {
                code,
                benefit_level,
                deductible,
                applies_to_deductible,
                applies_to_maximum,
                rows: [{
                    description: comment || "None",
                    limitation: "None",
                    service_date: "None",
                    age_limits: "None",
                    pre_approval: "None"
                }]
            };
        }

        const rows = [];

        table.querySelectorAll("tbody tr").forEach(row => {
            const th = row.querySelector("th");
            const cells = row.querySelectorAll("td");

            if (!th && cells.length === 0) return;

            const description = th ? clean(th.innerText) : "None";

            const get = (i) =>
                cells[i] ? clean(cells[i].innerText) || "None" : "None";

            rows.push({
                description,
                limitation: withLimitation(get(0)),
                service_date: get(1),
                age_limits: get(2),
                pre_approval: get(3)
            });
        });

        if (rows.length === 0) return null;

        return {
            code,
            benefit_level,
            deductible,
            applies_to_deductible,
            applies_to_maximum,
            rows
        };
    }
    async function searchAllBatches(networkLabel, batches = BATCHES) {
        const allResults = [];

        for (let i = 0; i < batches.length; i++) {
            console.log(`Benefits search batch ${i + 1}/${batches.length} (${networkLabel || "default network"})...`);
            const batchResults = await searchBenefitCodes(batches[i]);
            allResults.push(...batchResults);
            if (i < batches.length - 1) await sleep(1500);
        }

        console.log(`Benefits search complete (${networkLabel || "default network"}): ${allResults.length} codes scraped`);
        return allResults;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Provider network
    //
    // Benefits Search answers for one network at a time, chosen in the "Search
    // the provider network" dropdown above the results. The same D0150 is 100%
    // for a Delta Dental PPO dentist and 50% for a non-Delta dentist, so the
    // network has to match the office's participation. The user chooses it
    // (PPO, Premier or Out of Network — see askProviderNetwork) and every code is
    // searched under that network alone.
    //
    // The portal remembers the last network chosen, so the choice is always set
    // explicitly rather than trusting whatever is showing.
    //
    // Anything unexpected leaves the dropdown alone and records why, so a change
    // to the portal can only cost the network choice — never the scrape.
    // ──────────────────────────────────────────────────────────────────────────

    const NETWORK_LABEL_RE = /^search the provider network$/i;
    const OUT_OF_NETWORK_RE = /non[-\s]?delta/i;
    // Most specific first: the search-result chips beside the dropdown are
    // buttons too, so a bare button is only taken when nothing better is there.
    const NETWORK_CONTROL_SELECTORS =
        ['select', '[role="combobox"]', '[aria-haspopup="listbox"]', '.MuiSelect-select', '[role="button"]'];
    const looksLikeNetwork = (el) => /delta|dentist|network/i.test(readNetwork(el));

    function findNetworkControl() {
        // The label's own text is exactly the caption; its ancestors also carry
        // the selected network's name, so an exact match finds the label itself.
        const label = Array.from(document.querySelectorAll("label, legend, p, span, div, h1, h2, h3, h4, h5, h6"))
            .find(el => NETWORK_LABEL_RE.test(clean(el.innerText)));
        let node = label;
        for (let depth = 0; node && depth < 5; depth++, node = node.parentElement) {
            for (const selector of NETWORK_CONTROL_SELECTORS) {
                const control = Array.from(node.querySelectorAll(selector)).find(looksLikeNetwork);
                if (control) return control;
            }
        }
        // No caption found: a native dropdown that offers a non-Delta network.
        return Array.from(document.querySelectorAll("select"))
            .find(sel => Array.from(sel.options).some(o => OUT_OF_NETWORK_RE.test(o.text))) || null;
    }

    function readNetwork(control) {
        if (!control) return "";
        if (control.tagName === "SELECT") return clean(control.selectedOptions[0]?.text || "");
        return clean(control.innerText || control.value || "");
    }

    function visibleNetworkOptions() {
        return Array.from(document.querySelectorAll('[role="option"], [role="listbox"] li'))
            .filter(el => el.offsetParent !== null);
    }

    // Choose the first option the predicate accepts. Returns the network now
    // showing, or "" when no option was accepted or the choice did not stick.
    async function chooseNetwork(predicate) {
        const control = findNetworkControl();
        if (!control) return "";

        if (control.tagName === "SELECT") {
            const option = Array.from(control.options).find(o => predicate(clean(o.text)));
            if (!option) return "";
            const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
            setter.call(control, option.value);
            control.dispatchEvent(new Event("input", { bubbles: true }));
            control.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
            // Material UI opens its menu on mousedown; a plain click covers the rest.
            control.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
            control.click();
            await sleep(800);
            const option = visibleNetworkOptions().find(el => predicate(clean(el.innerText)));
            if (!option) {
                document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
                await sleep(300);
                return "";
            }
            option.click();
        }
        await sleep(1500);

        // The control may have re-rendered; read the choice back from the page.
        const now = readNetwork(findNetworkControl());
        return predicate(now) ? now : "";
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Provider network choice
    //
    // Which network this office participates in is something the user knows and
    // the portal does not say. Before the procedure-code search the user is asked
    // — Delta Dental PPO, Delta Dental Premier, or Out of Network — and only that
    // network is searched. The export records the choice as
    // `benefits_search_selected`, and the audit reads the sheet against it.
    // ──────────────────────────────────────────────────────────────────────────

    const NETWORK_CHOICES = [
        { key: "ppo",     label: "PPO",            hint: "Delta Dental PPO Dentist" },
        { key: "premier", label: "Premier",        hint: "Delta Dental Premier Dentist" },
        { key: "oon",     label: "Out of Network", hint: "Non-Delta Dental Dentist" },
    ];

    function askProviderNetwork(patientName) {
        return new Promise(resolve => {
            document.getElementById("dd-ins-network-choice")?.remove();

            const overlay = document.createElement("div");
            overlay.id = "dd-ins-network-choice";
            overlay.style.cssText = [
                "position:fixed", "inset:0", "z-index:2147483647", "display:flex",
                "align-items:center", "justify-content:center", "background:rgba(15,23,42,.45)",
                "font:14px/1.45 Arial,sans-serif"
            ].join(";");

            const box = document.createElement("div");
            box.setAttribute("role", "dialog");
            box.setAttribute("aria-modal", "true");
            box.setAttribute("aria-labelledby", "dd-ins-network-choice-title");
            box.style.cssText = [
                "width:360px", "max-width:calc(100vw - 32px)", "background:#fff", "color:#172033",
                "border-radius:10px", "box-shadow:0 12px 36px rgba(0,0,0,.28)", "padding:18px"
            ].join(";");

            const title = document.createElement("div");
            title.id = "dd-ins-network-choice-title";
            title.textContent = "Provider network";
            title.style.cssText = "font-weight:700;font-size:16px;margin-bottom:6px;color:#075985";

            const text = document.createElement("div");
            text.textContent = "Which network does this office participate in" +
                (patientName ? ` for ${patientName}` : "") +
                "? Only that network's benefits are searched.";
            text.style.cssText = "margin-bottom:14px;color:#475569";

            box.append(title, text);
            const buttons = NETWORK_CHOICES.map(choice => {
                const button = document.createElement("button");
                button.type = "button";
                button.style.cssText = [
                    "display:block", "width:100%", "text-align:left", "margin:0 0 8px",
                    "padding:10px 12px", "border:1px solid #9db3c7", "border-radius:8px",
                    "background:#f8fafc", "color:#172033", "cursor:pointer", "font:inherit"
                ].join(";");
                const name = document.createElement("div");
                name.textContent = choice.label;
                name.style.cssText = "font-weight:700";
                const hint = document.createElement("div");
                hint.textContent = choice.hint;
                hint.style.cssText = "font-size:12px;color:#64748b";
                button.append(name, hint);
                button.addEventListener("click", () => {
                    overlay.remove();
                    resolve(choice.key);
                });
                box.appendChild(button);
                return button;
            });

            overlay.appendChild(box);
            document.body.appendChild(overlay);
            buttons[0].focus();
        });
    }

    async function scrapeBenefitsSearchTab(choice, batches = BATCHES) {
        const result = { answers: [], network: "", choice: "", error: "" };
        const isInNetwork = (text) => !!text && !OUT_OF_NETWORK_RE.test(text);
        const wanted = {
            ppo:     (text) => isInNetwork(text) && /\b(ppo|dpo)\b/i.test(text),
            premier: (text) => isInNetwork(text) && /\bpremier\b/i.test(text),
            oon:     (text) => OUT_OF_NETWORK_RE.test(text),
        }[choice] || isInNetwork;

        // The dropdown is drawn above a set of results, so before the first
        // search of a patient there is nothing to read or set. One search is run
        // to bring it up (its answers are not kept), and the chosen network is
        // then set explicitly — the portal remembers the last network picked,
        // which may be another patient's.
        try {
            if (!findNetworkControl()) {
                await searchBenefitCodes(batches[0]);
                await sleep(1000);
            }
            const showing = readNetwork(findNetworkControl());
            if (!findNetworkControl()) {
                result.error = "network dropdown not found";
            } else if (!wanted(showing)) {
                const chosen = await chooseNetwork(wanted);
                if (!chosen) result.error = `could not switch from "${showing}" to the chosen network (${choice})`;
            }
        } catch (e) {
            result.error = `network dropdown: ${e.message}`;
        }

        // The choice is only recorded if the dropdown really shows it; otherwise
        // the answers are labelled with the network they were read under and the
        // audit falls back to the sheet's own In Network and fee schedule.
        result.network = readNetwork(findNetworkControl());
        if (choice && wanted(result.network)) result.choice = choice;
        result.answers = await searchAllBatches(result.network, batches);

        if (result.error) console.warn(`Provider network not set: ${result.error}`);
        return result;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Benefits from the portal's own data
    //
    // Benefits Search filters data the page already holds; typing codes into it
    // asks the server nothing. installPageHook (top of this file) keeps those responses as the
    // page receives them, and every sheet code is answered from them in the same
    // shape the search cards are read into:
    //
    //   benefits-package   procedure → network[] (##PPO / ##PMR / ##NP) →
    //                      coverageDetail[] (level, deductible and maximum
    //                      exemption, age band) and limitation[] (the sentence
    //                      and its age band)
    //   other-procedures   codes the plan does not pay for, with the comment the
    //                      card shows ("not a benefit of most Delta Dental plans")
    //   treatment-history  claims per code; the card's service dates are the
    //                      approved ones (a denied claim is not shown)
    //
    // A code in neither list is one the search answers with "This procedure code
    // could not be recognized."
    //
    // Anything missing or belonging to another patient sends the run back to the
    // search box, so this path can only make a scrape faster, never thinner.
    // ──────────────────────────────────────────────────────────────────────────

    const NETWORK_CODES = { ppo: "##PPO", premier: "##PMR", oon: "##NP" };
    const UNRECOGNIZED_CODE = "This procedure code could not be recognized.";

    function readCapturedResponses(timeoutMs = 1000) {
        return new Promise(resolve => {
            const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const done = (captured) => {
                clearTimeout(timer);
                window.removeEventListener("message", onMessage);
                resolve(captured || {});
            };
            const onMessage = (event) => {
                if (event.source !== window || event.origin !== window.location.origin) return;
                const message = event.data;
                if (!message || message.source !== HOOK_SOURCE || message.type !== "CAPTURED") return;
                if (message.requestId === requestId) done(message.captured);
            };
            const timer = setTimeout(() => done({}), timeoutMs);
            window.addEventListener("message", onMessage);
            window.postMessage({ source: SCRAPER_SOURCE, type: "GET_CAPTURED", requestId }, window.location.origin);
        });
    }

    const nameTokens = (name) => clean(String(name || "")).toLowerCase()
        .replace(/[^a-z\s]/g, " ").split(/\s+/).filter(Boolean);

    // The package names its member; a different name means the page is still
    // showing (or has only fetched) another patient's plan.
    function samePatient(memberName, patientName) {
        const member = nameTokens(memberName);
        const patient = nameTokens(patientName);
        if (!member.length || !patient.length || /^n\/?a$/i.test(clean(patientName))) return true;
        const shorter = member.length <= patient.length ? member : patient;
        const longer = new Set(member.length <= patient.length ? patient : member);
        return shorter.every(token => longer.has(token));
    }

    // What the page has captured for this patient, waiting a little for responses
    // still in flight. Returns the reason instead when something is unusable.
    async function capturedBenefits(patientName, maxWaitMs = 10000) {
        const start = Date.now();
        let reason = "";
        while (true) {
            const captured = await readCapturedResponses();
            const pkg = captured["benefits-package"]?.body;
            const history = captured["treatment-history"]?.body;
            const other = captured["other-procedures"]?.body;
            const memberName = pkg?.member?.memberName;
            const enrollee = pkg?.member?.enrolleeId;
            const historyEnrollee = history?.criteria?.enrolleeId;

            if (!Array.isArray(pkg?.treatment)) reason = "benefits package not captured";
            else if (!samePatient(memberName, patientName)) reason = "benefits package is for another patient";
            else if (!Array.isArray(history?.procedures)) reason = "treatment history not captured";
            else if (enrollee && historyEnrollee && enrollee !== historyEnrollee) reason = "treatment history is for another patient";
            else if (!Array.isArray(other?.treatment) && Date.now() - start < maxWaitMs) reason = "other procedures not captured";
            else return { pkg, history, other: Array.isArray(other?.treatment) ? other : null };

            if (Date.now() - start >= maxWaitMs) return { reason };
            await sleep(500);
        }
    }

    function formatCoverage(detail) {
        if (!detail) return "N/A";
        if (String(detail.amountType || "PERCENT").toUpperCase() === "PERCENT") {
            const level = Number(detail.benefitCoverageLevel);
            return Number.isFinite(level) ? `${+level.toFixed(2)}%` : "N/A";
        }
        const copay = Number(detail.copayAmount);
        return Number.isFinite(copay) ? `$${copay.toFixed(2)}` : "N/A";
    }

    // "No" is the portal's word for "no age band"; the card prints "None".
    const ageBand = (description) => {
        const text = clean(description);
        return !text || /^no$/i.test(text) ? "None" : text;
    };

    function benefitsFromCaptured(codes, captured, choice) {
        const networkCode = NETWORK_CODES[choice] || captured.pkg.member?.defaultNetwork || "##PPO";
        const networkName = (captured.pkg.networksAllowed || []).find(n => n.code === networkCode)?.description ||
            NETWORK_CHOICES.find(c => NETWORK_CODES[c.key] === networkCode)?.hint || networkCode;

        const packaged = new Map();
        for (const treatment of captured.pkg.treatment || []) {
            for (const procedureClass of treatment.procedureClass || []) {
                for (const procedure of procedureClass.procedure || []) {
                    const code = String(procedure?.code || "").toUpperCase();
                    if (code && !packaged.has(code)) packaged.set(code, procedure);
                }
            }
        }
        const notPaid = new Map();
        for (const treatment of captured.other?.treatment || []) {
            for (const procedure of treatment.procedure || []) {
                const code = String(procedure?.code || "").toUpperCase();
                if (code && !notPaid.has(code)) notPaid.set(code, procedure);
            }
        }
        const approvedDates = new Map();
        for (const procedure of captured.history.procedures || []) {
            const code = String(procedure?.code || "").toUpperCase();
            if (!code) continue;
            const dates = approvedDates.get(code) || [];
            for (const service of procedure.services || []) {
                if (/denied/i.test(service?.statusCodeDescription || "")) continue;
                const date = clean(service?.serviceDate);
                if (date && !dates.includes(date)) dates.push(date);
            }
            approvedDates.set(code, dates);
        }
        const serviceDate = (code) => (approvedDates.get(code) || []).join(", ") || "None";

        const answers = [];
        const unanswered = [];
        for (const code of codes) {
            const procedure = packaged.get(code);
            if (procedure) {
                const network = (procedure.network || []).find(n => n.code === networkCode);
                const detail = network?.coverageDetail?.[0];
                // "##NP,##PMR,##PPO": the networks a limitation binds; blank binds all.
                const appliesHere = (applicable) => {
                    const list = String(applicable || "").split(",").map(s => s.trim()).filter(Boolean);
                    return !list.length || list.includes(networkCode);
                };
                const description = clean(procedure.description) || "None";
                const pre_approval = procedure.preApprovalRequired ? "Required" : "None";
                const date = serviceDate(code);

                // One card row per age band, its limitation sentences joined, as
                // the search prints them (D0274: one row for 18+, one for children).
                const bands = new Map();
                for (const limitation of procedure.limitation || []) {
                    if (!appliesHere(limitation?.networksApplicable)) continue;
                    const text = clean(limitation?.frequencyLimitationText);
                    if (!text) continue;
                    const band = ageBand((limitation.sexAgeToothCode || [])
                        .map(s => s?.sexAgeCodeDescription).find(d => ageBand(d) !== "None"));
                    if (!bands.has(band)) bands.set(band, []);
                    if (!bands.get(band).includes(text)) bands.get(band).push(text);
                }
                if (!bands.size) {
                    for (const coverage of network?.coverageDetail || [{}]) {
                        const band = ageBand(coverage?.sexAgeCodeDescription);
                        if (!bands.has(band)) bands.set(band, []);
                    }
                }
                const rows = [...bands].map(([band, texts]) => ({
                    description,
                    limitation: texts.join(" ") || "None",
                    service_date: date,
                    age_limits: band,
                    pre_approval
                }));

                answers.push({
                    code,
                    benefit_level: formatCoverage(detail),
                    deductible: detail ? (detail.deductibleExempted ? "Does not apply" : "Applies") : "",
                    applies_to_deductible: detail ? (detail.deductibleExempted ? "No" : "Yes") : "",
                    applies_to_maximum: detail ? (detail.maximumExempted ? "No" : "Yes") : "",
                    rows
                });
                continue;
            }

            const other = notPaid.get(code);
            if (other || captured.other) {
                if (!other) unanswered.push(code);
                answers.push({
                    code,
                    benefit_level: "N/A",
                    deductible: "",
                    applies_to_deductible: "",
                    applies_to_maximum: "",
                    rows: [{
                        description: other ? (clean(other.description) || "None") : UNRECOGNIZED_CODE,
                        limitation: other ? (clean(other.comments) || "None") : "None",
                        service_date: serviceDate(code),
                        age_limits: "None",
                        pre_approval: "None"
                    }]
                });
                continue;
            }
            // Not in the package and the not-paid list never arrived: only the
            // search box can say whether the code is unpaid or unknown.
            unanswered.push(code);
        }
        return { answers, network: networkName, unanswered, searchNeeded: !captured.other };
    }

    // Every sheet code, answered from the captured data where possible and from
    // the search box for whatever it cannot answer.
    async function scrapeBenefits(choice, patientName) {
        const codeOrder = new Map(SHEET_CODES.map((code, i) => [code, i]));
        const byCode = (a, b) => (codeOrder.get(a.code) ?? 1e9) - (codeOrder.get(b.code) ?? 1e9);
        const result = { answers: [], network: "", choice: "", method: "", missing: [], error: "" };

        const captured = await capturedBenefits(patientName);
        if (captured.reason) console.warn(`Benefits not read from the page's data (${captured.reason}); using the search box.`);

        let searchCodes = SHEET_CODES;
        if (!captured.reason) {
            const fromData = benefitsFromCaptured(SHEET_CODES, captured, choice);
            result.answers = fromData.answers;
            result.network = fromData.network;
            result.choice = choice || "";
            result.method = "api";
            searchCodes = fromData.searchNeeded ? fromData.unanswered : [];
            if (!fromData.searchNeeded) result.missing = fromData.unanswered;
            console.log(`Benefits read from the page's data (${result.network}): ${result.answers.length} codes`);
        }

        if (searchCodes.length) {
            const batches = Array.from({ length: Math.ceil(searchCodes.length / 10) },
                (_, i) => searchCodes.slice(i * 10, i * 10 + 10));
            const search = await scrapeBenefitsSearchTab(choice, batches);
            const wanted = new Set(searchCodes);
            const seen = new Set(result.answers.map(a => a.code));
            for (const answer of search.answers) {
                const code = String(answer?.code || "").toUpperCase();
                if (!wanted.has(code) || seen.has(code)) continue;
                seen.add(code);
                result.answers.push(answer);
            }
            result.missing.push(...searchCodes.filter(code => !seen.has(code)));
            result.method = result.method ? "mixed" : "dom";
            if (!result.network) result.network = search.network;
            if (!result.choice) result.choice = search.choice;
            result.error = search.error;
        }

        result.answers.sort(byCode);
        // The search box answers an unknown code with a card saying so.
        const unrecognized = result.answers.filter(answer => (answer.rows || [])
            .some(row => /could not be recognized/i.test(row?.description || ""))).map(answer => answer.code);
        result.missing = [...new Set([...result.missing, ...unrecognized])]
            .sort((a, b) => (codeOrder.get(a) ?? 1e9) - (codeOrder.get(b) ?? 1e9));
        return result;
    }

    function triggerDeltaDentalDownload(auditData) {
        const sanitize = (s) => (s || "").trim().replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "").toLowerCase();
        const patient = sanitize(
            auditData.primary_patient?.name ||
            auditData.eligibility?.subscriber_name ||
            auditData.eligibility?.member_id ||
            "patient"
        ) || "patient";
        const filename = `${patient}_Delta_Dental.json`;

        const blob = new Blob([JSON.stringify(auditData, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        URL.revokeObjectURL(url);
        document.body.removeChild(a);
        console.log(`✓ Downloaded: ${filename}`);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STEP 2: TAB NAVIGATION
    // ══════════════════════════════════════════════════════════════════════════

    async function clickTab(dataTestId) {
        /**
         * Click a tab and wait for content to load
         */
        const tab = document.querySelector(`[data-testid="${dataTestId}"]`);
        if (tab) {
            tab.click();
            await sleep(1000); // Wait 1 second after click
            console.log(`Clicked tab: ${dataTestId}`);
            return true;
        }
        console.warn(`Could not find tab: ${dataTestId}`);
        return false;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STEP 7: FAMILY MEMBERS TAB SCRAPER
    // ══════════════════════════════════════════════════════════════════════════

    function scrapeFamilyMembersTab() {
        /**
         * Scrape all family member patient cards
         */
        return scrapeAllPatientCards();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // MAIN CRAWLER - ORCHESTRATE ALL STEPS
    // ══════════════════════════════════════════════════════════════════════════

    async function runDeltaDentalCrawl() {
        if (!chrome.runtime?.id) return;

        console.log("=== DELTA DENTAL COMPLETE AUDIT STARTED ===");

        try {
            const auditData = {
                source: "Delta Dental",
                timestamp: new Date().toISOString(),
                primary_patient: scrapeAllPatientCards()[0] || null,
                tabs: {}
            };

            // OVERVIEW TAB
            console.log("Scraping Overview tab...");
            await clickTab("overviewTab");
            auditData.tabs.overview = scrapeOverviewTab();

            // Eligibility info is scraped from static fields visible on the overview tab
            console.log("Scraping eligibility/member info...");
            auditData.eligibility = scrapeEligibilityInfo();

            // PLAN PROVISIONS TAB
            console.log("Scraping Plan Provisions tab...");
            await clickTab("planProvisionsTab");
            auditData.tabs.plan_provisions = scrapePlanProvisionsTab();

            // WAITING PERIODS TAB
            console.log("Scraping Waiting Periods tab...");
            await clickTab("waitingPeriodsTab");
            auditData.tabs.waiting_periods = scrapeWaitingPeriodsTab();

            // BENEFITS SEARCH TAB
            console.log("Scraping Benefits Search tab...");
        await clickTab("benefitsSearchTab");
    // Wait until search UI is ready
        let input = null;
        let button = null;

        const start = Date.now();

        while (Date.now() - start < 10000) {
        input = document.querySelector('[data-testid="autocompleteSearchInput"]');
        button = document.querySelector('[data-testid="autocompleteSearchButton"]');

        if (
            input &&
            button &&
            !input.disabled &&
            input.offsetParent !== null
        ) {
            break;
        }

        await sleep(250);
    }
    // Small buffer for React rendering
    await sleep(1500);
    const choice = await askProviderNetwork(auditData.primary_patient?.name);
    const search = await scrapeBenefits(choice, auditData.primary_patient?.name);
    auditData.tabs.benefits_search = search.answers;
    auditData.tabs.benefits_search_network = search.network;
    // "ppo" | "premier" | "oon"; empty when the choice could not be applied.
    auditData.tabs.benefits_search_selected = search.choice;
    if (search.error) auditData.tabs.benefits_search_network_error = search.error;
    // "api" (the page's data), "dom" (the search box) or "mixed".
    auditData.tabs.benefits_search_method = search.method;
    auditData.tabs.benefits_search_codes_requested = SHEET_CODES.join(", ");
    // Codes the portal does not recognise at all.
    auditData.tabs.benefits_search_codes_not_in_portal = search.missing.join(", ");
    auditData.tabs.benefits_search_spec = {
        source_workbook_sha256: REQUIREMENTS_SPEC?.source_workbook_sha256 || "",
        generated_at_utc: REQUIREMENTS_SPEC?.generated_at_utc || ""
    };
            // TREATMENT HISTORY TAB
            console.log("Scraping Treatment History tab...");
            const historyTabClicked = await clickTab("treatmentHistoryTab");
            if (historyTabClicked) {
                auditData.tabs.treatment_history = await scrapeTreatmentHistoryTab();
            } else {
                console.warn("Treatment History tab not found — skipping");
                auditData.tabs.treatment_history = { rows: [], note: "Tab not found" };
            }

            // FAMILY MEMBERS TAB
            console.log("Scraping Family Members tab...");
            await clickTab("familyMembersTab");
            auditData.tabs.family_members = scrapeFamilyMembersTab();

            console.log("=== AUDIT COMPLETE ===");
            console.log("Full audit data:", auditData);

            // Store in Chrome storage
            chrome.storage.local.get("audit_context", (result) => {
                let context = result.audit_context || {};
                context.delta_dental_data = auditData;
                chrome.storage.local.set({ "audit_context": context }, () => {
                    console.log("✓ Delta Dental complete audit data stored successfully");
                    triggerDeltaDentalDownload(auditData);
                });
            });

        } catch (error) {
            console.error("❌ Delta Dental crawl error:", error);
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // MESSAGE LISTENER
    // ══════════════════════════════════════════════════════════════════════════

    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request.command === "START_CRAWL") {
            console.log("Received START_CRAWL command for Delta Dental");
            runDeltaDentalCrawl().then(() => {
                sendResponse({ status: "Delta Dental complete audit finished" });
            });
            return true;
        }
    });
})();
