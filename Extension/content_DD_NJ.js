// content_delta_dental.js — Delta Dental crawler
// Runs on: https://www.deltadentalins.com/*

(function () {
    "use strict";

    // ── UTILITIES ────────────────────────────────────────────────────

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // Safe querySelector — never throws, just returns ""
    function safeGetText(selector) {
        try {
            const el = document.querySelector(selector);
            return el ? el.innerText.trim() : "";
        } catch (e) {
            return "";
        }
    }

    // Extract "Label: VALUE" or "Label  VALUE" from raw page text
    function extractAfterLabel(text, label) {
        try {
            const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            const regex   = new RegExp(escaped + "[:\\s]+([^\\n\\r]{1,80})", "i");
            const match   = text.match(regex);
            return match ? match[1].trim() : "";
        } catch (e) {
            return "";
        }
    }

    // Find text in ANY element matching a class/attr fragment — no jQuery needed
    function findTextByClassFragment(fragment) {
        try {
            const all = document.querySelectorAll(`[class*="${fragment}"]`);
            for (const el of all) {
                const t = el.innerText.trim();
                if (t) return t;
            }
        } catch (e) {}
        return "";
    }

    // Find a table cell's sibling value by header text
    // e.g. find "Member ID" header → get the next TD's text
    function findTableValue(headerText) {
        try {
            const headers = [...document.querySelectorAll("th, td, dt, label, span, div")];
            for (const h of headers) {
                if (h.innerText && h.innerText.trim().toLowerCase() === headerText.toLowerCase()) {
                    // Try: same-row next sibling cell
                    const nextTd = h.nextElementSibling;
                    if (nextTd && nextTd.innerText.trim()) return nextTd.innerText.trim();

                    // Try: parent row's next cell
                    const parentRow = h.closest("tr");
                    if (parentRow) {
                        const cells = [...parentRow.querySelectorAll("td")];
                        const idx   = cells.indexOf(h);
                        if (idx >= 0 && cells[idx + 1]) return cells[idx + 1].innerText.trim();
                    }

                    // Try: next sibling element (dl/dt/dd pattern)
                    const dd = h.parentElement && h.parentElement.nextElementSibling;
                    if (dd && dd.innerText.trim()) return dd.innerText.trim();
                }
            }
        } catch (e) {}
        return "";
    }

    // Click a tab/button/menu item by label with exact-match priority
    async function clickTabByLabel(label, waitMs = 2500) {
        try {
            const normalized = (label || "").trim().toLowerCase();
            if (!normalized) return false;

            const candidates = [...document.querySelectorAll("a[href], button, [role='tab'], [role='menuitem'], [onclick], li")];
            const visible = candidates.filter(el => {
                if (!(el instanceof HTMLElement)) return false;
                if (el.offsetParent === null && el.getClientRects().length === 0) return false;
                return true;
            });

            let exactMatch = null;
            let partialMatch = null;
            for (const el of visible) {
                const text = ((el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || "").trim()).toLowerCase();
                if (!text) continue;
                if (text === normalized) {
                    exactMatch = el;
                    break;
                }
                if (!partialMatch && text.includes(normalized)) {
                    partialMatch = el;
                }
            }

            const match = exactMatch || partialMatch;
            if (match) {
                console.log(`[DD] Clicking tab: "${(match.innerText || match.getAttribute('aria-label') || label).trim()}"`);
                match.click();
                await sleep(waitMs);
                return true;
            }
        } catch (e) {
            console.warn(`[DD] clickTabByLabel error for "${label}":`, e.message);
        }
        return false;
    }

    async function clickTabByLabels(labels, waitMs = 2500) {
        for (const label of labels) {
            if (await clickTabByLabel(label, waitMs)) return true;
        }
        return false;
    }

    function clickElement(el) {
        if (!el) return false;
        try {
            if (typeof el.scrollIntoView === 'function') {
                el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'auto' });
            }
            if (typeof el.click === 'function') {
                el.click();
            }
            if (typeof el.dispatchEvent === 'function') {
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            }
            return true;
        } catch (e) {
            console.warn('[DD] clickElement error:', e.message);
            return false;
        }
    }

    function buildProcedureCodeBatches(codes, batchSize = 10) {
        if (!Array.isArray(codes) || !codes.length) return [];
        const normalized = [...new Set(codes.filter(Boolean).map(code => String(code).trim().toUpperCase()))];
        const batches = [];
        for (let i = 0; i < normalized.length; i += batchSize) {
            batches.push(normalized.slice(i, i + batchSize));
        }
        return batches;
    }

    function findSearchTrigger(input, preferredBtn = null) {
        const candidates = [];
        if (preferredBtn) candidates.push(preferredBtn);
        if (input) {
            const form = input.closest('form');
            if (form) candidates.push(...form.querySelectorAll('button, input[type="button"], input[type="submit"], a, [role="button"]'));
            candidates.push(...input.parentElement ? input.parentElement.querySelectorAll('button, input[type="button"], input[type="submit"], a, [role="button"]') : []);
        }
        candidates.push(...document.querySelectorAll('button, input[type="button"], input[type="submit"], a, [role="button"]'));

        const isSearchCandidate = (el) => {
            if (!el || el.disabled) return false;
            const text = ((el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '') + '').trim().toLowerCase();
            return /search|find|go|submit|lookup/.test(text);
        };

        for (const candidate of candidates) {
            if (isSearchCandidate(candidate)) return candidate;
        }
        return null;
    }

    async function openTabAndCapture(labels, waitMs = 3000, usePagination = false) {
        const opened = await clickTabByLabels(labels, waitMs);
        if (!opened) return null;
        if (usePagination) return await scrapeAllPages();
        return document.body.innerText.trim();
    }

    // Save snapshot to chrome.storage
    function saveToStorage(data) {
        return new Promise(resolve => {
            chrome.storage.local.set({ audit_context: data }, resolve);
        });
    }

    // Scrape all paginated content on a tab (clicks Next until gone)
    async function scrapeAllPages() {
        let allText = document.body.innerText.trim();
        let safety  = 0;

        while (safety++ < 20) {
            // Find a Next button that is NOT disabled
            const nextBtn = [...document.querySelectorAll("a, button")]
                .find(el => {
                    const t = (el.innerText || el.textContent || "").trim();
                    return /^next$/i.test(t) && !el.disabled && !el.classList.contains("disabled");
                });

            if (!nextBtn) break;

            console.log(`[DD] Pagination: loading page ${safety + 1}`);
            nextBtn.click();
            await sleep(2500);
            allText += `\n\n--- PAGE ${safety + 1} ---\n\n` + document.body.innerText.trim();
        }

        return allText;
    }

    // ── MAIN CRAWL ───────────────────────────────────────────────────

    async function crawlDeltaDental() {
        console.log("[DD] ✅ Crawl starting on:", window.location.href);

        // Build the data structure
        const data = {
            _crawl_complete:  false,
            crawl_timestamp:  new Date().toISOString(),
            page_url:         window.location.href,
            delta_dental_data: {
                patient_name:       "",
                member_id:          "",
                group_number:       "",
                dob:                "",
                gender:             "",
                age:                "",
                member_type:        "",
                eligibility_start:  "",
                eligibility_end:    "",
                plan_name:          "",
                annual_maximum:     "",
                deductible:         "",
                deductible_met:     "",
                remaining_maximum:  "",
                subscriber_info: {
                    name:             "",
                    dob:              "",
                    gender:           "",
                    age:              "",
                    relation:         "",
                    member_id:        "",
                    group_number:     "",
                    eligibility_start:"",
                    eligibility_end:  ""
                },
                tabs: {
                    eligibility:       "",
                    overview:          "",
                    plan_provisions:   "",
                    waiting_periods:   "",
                    benefits_search:   "",
                    treatment_history: "",
                    family_members:    "",
                    plan_details:      ""
                }
            }
        };

        const dd = data.delta_dental_data;

        // Wait for page to settle
        await sleep(2000);

        // ── STEP 1: Scrape current page (eligibility / member info) ──
        console.log("[DD] Step 1: Scraping member info");

        const pageText = await scrapeAllPages();

        // Patient name — try selectors then header/text patterns
        dd.patient_name =
            safeGetText("h1.member-name")          ||
            safeGetText(".member-name")             ||
            safeGetText(".patient-name")            ||
            safeGetText("[class*='memberName']")    ||
            safeGetText("[class*='member-name']")   ||
            findTextByClassFragment("member-name")  ||
            findTextByClassFragment("patientName")  ||
            findTableValue("Member Name")           ||
            findTableValue("Subscriber Name")       ||
            findTableValue("Patient Name")          ||
            extractAfterLabel(pageText, "Member Name")     ||
            extractAfterLabel(pageText, "Subscriber Name") ||
            extractAfterLabel(pageText, "Patient Name")    ||
            extractAfterLabel(pageText, "Name")            ||
            extractAfterLabel(pageText, "Member:")        ||
            extractAfterLabel(pageText, "Subscriber:")    ||
            extractAfterLabel(pageText, "Patient:")       ||
            (function () {
                const lines = pageText.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
                if (lines.length >= 2 && /^Plan\s*[:]/i.test(lines[1])) return lines[0];
                return "";
            })() ||
            "";

        // Member ID
        dd.member_id =
            safeGetText("[class*='member-id']")     ||
            safeGetText("[class*='memberId']")      ||
            findTableValue("Member ID")             ||
            findTableValue("Member #")              ||
            findTableValue("ID Number")             ||
            extractAfterLabel(pageText, "Member ID")  ||
            extractAfterLabel(pageText, "Member #")   ||
            extractAfterLabel(pageText, "ID Number")  ||
            extractAfterLabel(pageText, "Member Id")  ||
            extractAfterLabel(pageText, "ID")         ||
            "";

        dd.group_number =
            safeGetText("[class*='group-number']")  ||
            safeGetText("[class*='groupNumber']")   ||
            findTableValue("Group Number")          ||
            findTableValue("Group #")               ||
            findTableValue("Group ID")              ||
            findTableValue("Group")                 ||
            extractAfterLabel(pageText, "Group Number") ||
            extractAfterLabel(pageText, "Group #")      ||
            extractAfterLabel(pageText, "Group ID")     ||
            extractAfterLabel(pageText, "Group:")      ||
            extractAfterLabel(pageText, "Group")        ||
            "";

        dd.dob =
            findTableValue("Date of Birth")     ||
            findTableValue("DOB")               ||
            findTableValue("Birth Date")        ||
            extractAfterLabel(pageText, "Date of Birth") ||
            extractAfterLabel(pageText, "DOB")           ||
            extractAfterLabel(pageText, "Birth Date")    ||
            extractAfterLabel(pageText, "Date of Birth:") ||
            "";

        dd.gender =
            findTableValue("Gender")            ||
            extractAfterLabel(pageText, "Gender") ||
            "";

        dd.age =
            findTableValue("Age")               ||
            extractAfterLabel(pageText, "Age")   ||
            "";

        dd.member_type =
            findTableValue("Member Type")       ||
            findTableValue("Relationship")      ||
            findTableValue("Relation")          ||
            extractAfterLabel(pageText, "Member Type")   ||
            extractAfterLabel(pageText, "Relationship")  ||
            extractAfterLabel(pageText, "Relation")      ||
            extractAfterLabel(pageText, "Member type")   ||
            "";

        dd.plan_name =
            safeGetText("[class*='plan-name']") ||
            safeGetText("[class*='planName']")  ||
            findTableValue("Plan Name")         ||
            findTableValue("Plan")              ||
            extractAfterLabel(pageText, "Plan Name") ||
            extractAfterLabel(pageText, "Plan:")     ||
            extractAfterLabel(pageText, "Plan")       ||
            (function () {
                const match = pageText.match(/Plan\s*[:]?\s*([^\n\r]+)/i);
                return match ? match[1].trim() : "";
            })() ||
            "";

        dd.annual_maximum =
            findTableValue("Annual Maximum")    ||
            findTableValue("Annual Max")        ||
            findTableValue("Calendar Year Maximum") ||
            extractAfterLabel(pageText, "Annual Maximum")        ||
            extractAfterLabel(pageText, "Annual Max")            ||
            extractAfterLabel(pageText, "Calendar Year Maximum") ||
            "";

        dd.deductible =
            findTableValue("Deductible")        ||
            findTableValue("Individual Deductible") ||
            extractAfterLabel(pageText, "Individual Deductible") ||
            extractAfterLabel(pageText, "Deductible")            ||
            "";

        dd.deductible_met =
            findTableValue("Deductible Met")    ||
            findTableValue("Deductible Used")   ||
            extractAfterLabel(pageText, "Deductible Met")  ||
            extractAfterLabel(pageText, "Deductible Used") ||
            "";

        dd.remaining_maximum =
            findTableValue("Remaining Maximum") ||
            findTableValue("Remaining Max")     ||
            extractAfterLabel(pageText, "Remaining Maximum") ||
            extractAfterLabel(pageText, "Remaining Max")     ||
            extractAfterLabel(pageText, "Balance Remaining") ||
            "";

        dd.eligibility_start =
            findTableValue("Effective Date")    ||
            findTableValue("Eligibility Start") ||
            extractAfterLabel(pageText, "Effective Date")    ||
            extractAfterLabel(pageText, "Eligibility Start") ||
            (function () {
                const match = pageText.match(/Member eligibility\s*[:]?\s*([0-9\/]+)\s*[-–]\s*([0-9\/present]+)/i);
                return match ? match[1].trim() : "";
            })() ||
            "";

        dd.eligibility_end =
            findTableValue("Termination Date")  ||
            findTableValue("Eligibility End")   ||
            findTableValue("End Date")          ||
            extractAfterLabel(pageText, "Termination Date")  ||
            extractAfterLabel(pageText, "Eligibility End")   ||
            extractAfterLabel(pageText, "End Date")          ||
            (function () {
                const match = pageText.match(/Member eligibility\s*[:]?\s*([0-9\/]+)\s*[-–]\s*([0-9\/present]+)/i);
                return match ? match[2].trim() : "";
            })() ||
            "";

        // Full page dump
        dd.tabs.eligibility = pageText;
        dd.subscriber_info = {
            name:           dd.patient_name || "",
            dob:            dd.dob || "",
            gender:         dd.gender || "",
            age:            dd.age || "",
            relation:       dd.member_type || "",
            member_id:      dd.member_id || "",
            group_number:   dd.group_number || "",
            eligibility_start: dd.eligibility_start || "",
            eligibility_end:   dd.eligibility_end || ""
        };

        await saveToStorage(data);
        console.log("[DD] Step 1 saved ✓");

        // ── STEP 2: Overview tab ─────────────────────────────────────
        console.log("[DD] Step 2: Overview tab");
        const overviewText = await openTabAndCapture([
            "Overview",
            "Overview & Benefits",
            "Eligibility & benefits",
            "Eligibility & Benefits"
        ], 3000);
        if (overviewText !== null) {
            dd.tabs.overview = overviewText;
            await saveToStorage(data);
            console.log("[DD] Overview saved ✓");
        } else {
            console.warn("[DD] Overview tab not found");
        }

        // ── STEP 3: Plan provisions tab ──────────────────────────────
        console.log("[DD] Step 3: Plan provisions tab");
        const provisionsText = await openTabAndCapture([
            "Plan provisions",
            "Plan Provisions",
            "Provisions",
            "Plan details"
        ], 3000);
        if (provisionsText !== null) {
            dd.tabs.plan_provisions = provisionsText;
            await saveToStorage(data);
            console.log("[DD] Plan provisions saved ✓");
        } else {
            console.warn("[DD] Plan provisions tab not found");
        }

        // ── STEP 4: Waiting periods tab ──────────────────────────────
        console.log("[DD] Step 4: Waiting periods tab");
        const waitingText = await openTabAndCapture([
            "Waiting periods",
            "Waiting Periods",
            "Waiting period",
            "Waiting Period"
        ], 3000);
        if (waitingText !== null) {
            dd.tabs.waiting_periods = waitingText;
            await saveToStorage(data);
            console.log("[DD] Waiting periods saved ✓");
        } else {
            console.warn("[DD] Waiting periods tab not found");
        }

        // ── STEP 5: Benefits Search tab ──────────────────────────────
        console.log("[DD] Step 5: Benefits Search tab");
        const benefitsText = await openTabAndCapture([
            "Benefits Search",
            "Benefits search",
            "Benefits",
            "Benefit Search",
            "Search by"
        ], 3000);
        const benefitsTabOpened = benefitsText !== null;
        if (benefitsTabOpened) {
            dd.tabs.benefits_search = benefitsText;
            await saveToStorage(data);
            console.log("[DD] Benefits Search tab opened ✓");
        } else {
            console.warn("[DD] Benefits Search tab not found");
        }

        // ── STEP 6: Benefits SEARCH — automatically search procedure codes ──
        console.log("[DD] Step 6: Benefits SEARCH and procedure code queries");

        // Requested procedure codes for Delta Dental benefits search, sent in 10-code batches
        const requestedProcedureCodes = [
            "D0120", "D0180", "D0140", "D0150", "D0274", "D0210", "D0330", "D0220", "D0364", "D0431",
            "D1110", "D1120", "D1206", "D1351", "D1510", "D2391", "D2740", "D2950", "D2962", "D6750",
            "D5110", "D9110", "D9222", "D9230", "D9243", "D9310", "D9944", "D4341", "D4355", "D4346",
            "D4910", "D4381", "D4260", "D4249", "D3310", "D3330", "D7140", "D7210", "D7240", "D7953",
            "D6010", "D6056"
        ];
        const PROCEDURE_CODE_BATCHES = buildProcedureCodeBatches(requestedProcedureCodes, 10);

        // Run the procedure code searches batch-wise
        try {
            await searchProcedureCodes(benefitsTabOpened, PROCEDURE_CODE_BATCHES);
        } catch (e) {
            console.warn('[DD] Error running procedure code searches:', e.message);
        }

        // ── STEP 7: Treatment History tab ────────────────────────────
        console.log("[DD] Step 7: Treatment History tab");

        const historyText = await openTabAndCapture([
            "Treatment History",
            "Claim History",
            "Claims"
        ], 3000, true);
        if (historyText !== null) {
            dd.tabs.treatment_history = historyText;
            await saveToStorage(data);
            console.log("[DD] Treatment history saved ✓");
        } else {
            console.warn("[DD] Treatment History tab not found");
        }

        // ── STEP 8: Family Members tab ───────────────────────────────
        console.log("[DD] Step 8: Family Members tab");

        const familyText = await openTabAndCapture([
            "Family Members",
            "Dependents"
        ], 3000, true);
        if (familyText !== null) {
            dd.tabs.family_members = familyText;
            await saveToStorage(data);
            console.log("[DD] Family members saved ✓");
        } else {
            console.warn("[DD] Family Members tab not found");
        }

        // ── STEP 9: Plan Details tab ─────────────────────────────────
        console.log("[DD] Step 9: Plan Details tab");

        const planText = await openTabAndCapture([
            "Plan Details",
            "Plan Summary",
            "Coverage Summary",
            "Coverage"
        ], 3000, true);

        if (planText !== null) {
            dd.tabs.plan_details = planText;

            // Try again for dates if we didn't get them on step 1
            if (!dd.eligibility_start)
                dd.eligibility_start = extractAfterLabel(planText, "Effective Date") || "";
            if (!dd.eligibility_end)
                dd.eligibility_end =
                    extractAfterLabel(planText, "Termination Date") ||
                    extractAfterLabel(planText, "End Date") || "";

            await saveToStorage(data);
            console.log("[DD] Plan details saved ✓");
        } else {
            console.warn("[DD] Plan Details tab not found");
        }

        // ── DONE ─────────────────────────────────────────────────────
        data._crawl_complete = true;

        async function findSearchInputAndButton() {
            const inputSelectors = [
                "input[type='search']",
                "input[placeholder*='Enter procedure code']",
                "input[placeholder*='procedure code']",
                "input[placeholder*='procedure']",
                "input[placeholder*='code']",
                "input[name*='procedure']",
                "input[name*='code']",
                "input[id*='procedure']",
                "input[id*='code']",
                "input[aria-label*='procedure']",
                "input[aria-label*='code']",
                "textarea[placeholder*='procedure']",
                "textarea[placeholder*='code']",
                "textarea[name*='procedure']",
                "textarea[id*='procedure']"
            ];

            let input = null;
            for (const sel of inputSelectors) {
                input = document.querySelector(sel);
                if (input) break;
            }

            if (!input) {
                const labels = [...document.querySelectorAll('label')];
                for (const label of labels) {
                    const text = (label.innerText || '').trim().toLowerCase();
                    if (/procedure|code|search/.test(text)) {
                        const target = label.control || document.querySelector(`#${label.getAttribute('for')}`);
                        if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
                            input = target;
                            break;
                        }
                    }
                }
            }

            if (!input) {
                const inputs = [...document.querySelectorAll('input, textarea')];
                input = inputs.find(el => {
                    const text = ((el.placeholder || '') + ' ' + (el.name || '') + ' ' + (el.id || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '')).toLowerCase();
                    return /procedure|code|search/.test(text);
                }) || null;
            }

            if (!input) {
                const contentEls = [...document.querySelectorAll('[contenteditable="true"]')];
                input = contentEls.find(el => /procedure|code|search/i.test((el.innerText || '').toLowerCase())) || null;
            }

            const buttons = [...document.querySelectorAll("button, input[type='button'], input[type='submit'], a, [role='button']")];
            let btn = buttons.find(el => {
                const t = ((el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '') + '').trim().toLowerCase();
                return /search|find|go|submit|lookup/.test(t) && !el.disabled;
            });
            if (!btn && input) {
                const form = input.closest('form');
                if (form) {
                    btn = [...form.querySelectorAll("button, input[type='submit'], input[type='button'], [role='button']")]
                        .find(el => {
                            const t = ((el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '') + '').trim().toLowerCase();
                            return /search|find|go|submit|lookup/.test(t) && !el.disabled;
                        });
                }
            }

            return { input, btn, searchControl: findSearchTrigger(input, btn) };
        }

        async function waitForSearchResults(resultArea, timeoutMs = 10000) {
            const start = Date.now();
            const baseline = normalizeText(resultArea.innerText || '');
            while (Date.now() - start < timeoutMs) {
                await sleep(500);
                const current = normalizeText(resultArea.innerText || '');
                if (current !== baseline && current.length > baseline.length) {
                    return true;
                }
                if (/\bD\d{4}\b/.test(current) && current.length > 20) {
                    return true;
                }
            }
            return false;
        }

        function scoreSearchResultElement(el) {
            if (!el || !el.innerText) return 0;
            const text = normalizeText(el.innerText || '');
            if (text.length < 20) return 0;
            let score = 0;
            if (/\bD\d{4}\b/.test(text)) score += 40;
            if (/(benefit|coverage|deductible|frequency|limit|procedure|service|network|coinsurance|copay|amount|percent)/i.test(text)) score += 20;
            if (/table|row|item|result/i.test(text)) score += 10;
            if (/search by procedure code/i.test(text)) score -= 20;
            score += Math.min(text.length / 40, 15);
            return score;
        }

        function findSearchResultsArea(input) {
            const root = input
                ? input.closest('section, form, .panel, .card, .content, [role="main"], [role="region"]') || document.body
                : document.body;

            const selectors = [
                '.results',
                '.search-results',
                '.result-table',
                '.benefits-results',
                '.results-table',
                '.benefits-table',
                '.data-table',
                '.table-responsive',
                '.search-results-container',
                '.results-panel',
                'table'
            ];

            let best = root;
            let bestScore = scoreSearchResultElement(root);

            for (const sel of selectors) {
                const el = root.querySelector(sel);
                const score = scoreSearchResultElement(el);
                if (score > bestScore) {
                    bestScore = score;
                    best = el;
                }
            }

            const tables = [...root.querySelectorAll('table')];
            for (const table of tables) {
                const score = scoreSearchResultElement(table);
                if (score > bestScore) {
                    bestScore = score;
                    best = table;
                }
            }

            const containers = [...root.querySelectorAll('section, .panel, .card, .content, [role="region"], div')];
            for (const container of containers) {
                const score = scoreSearchResultElement(container);
                if (score > bestScore) {
                    bestScore = score;
                    best = container;
                }
            }

            return best || root;
        }

        function escapeRegExp(value) {
            return (value || '').replace(/[.*+?^${}()|[\\]\\]/g, '\\$&');
        }

        function extractLabeledValue(text, labels) {
            if (!text || !labels || !labels.length) return "";
            const normalized = normalizeText(text);
            for (const label of labels) {
                try {
                    const pattern = new RegExp("\\b" + escapeRegExp(label) + "\\b[:\\-]?\\s*([A-Za-z0-9\\$%\\.\\-\\/ \\n]{1,120})", "i");
                    const match = normalized.match(pattern);
                    if (match && match[1]) {
                        return normalizeText(match[1]);
                    }
                } catch (e) {
                    continue;
                }
            }
            return "";
        }

        function isGenericUIText(text) {
            if (!text) return true;
            const normalized = normalizeText(text).toLowerCase();
            if (!normalized) return true;
            const genericPatterns = [
                /^search by procedure code/i,
                /^benefits search/i,
                /^search results/i,
                /^no results found/i,
                /^please enter/i,
                /^loading/i,
                /^search/i,
                /^member( information)?$/i,
                /^plan details?$/i,
                /^coverage details?$/i,
                /^(account|welcome|header|footer|nav|topnav|sidebar)$/i
            ];
            return genericPatterns.some(rx => rx.test(normalized));
        }

        function isValidSearchResultText(text) {
            if (!text) return false;
            const normalized = normalizeText(text).toLowerCase();
            if (normalized.length < 15) return false;
            return /\b(benefit|coverage|deductible|frequency|patient|network|age|service|limit|percent|%|\$)\b/i.test(text) && !isGenericUIText(text);
        }

        function parseProcedureFromText(code, text) {
            const escapedCode = escapeRegExp(code);
            // Flexible parsing heuristics using regex to extract fields
            const proc = {
                age_limit: "",
                benefit_level: "",
                deductible: "",
                description: "",
                frequency_limit: "",
                late_date_of_service: "",
                network_fee: "",
                patient_responsibility: "",
                procedure_code: code
            };

            try {
                // Normalize text before parsing
                text = normalizeText(text || "");
                const lines = text.split(/\r?\n/).map(l => normalizeText(l)).filter(Boolean);
                const codeRegex = new RegExp(`\\b${escapedCode}\\b`, "i");
                const codeIndex = lines.findIndex(line => codeRegex.test(line));
                const scanLines = codeIndex >= 0 ? lines.slice(Math.max(0, codeIndex - 1), codeIndex + 4) : lines.slice(0, 8);
                const combined = scanLines.join(" | ");

                if (codeIndex >= 0) {
                    const line = lines[codeIndex];
                    const descMatch = line.match(new RegExp(code + "[\\s\\-:|]{1,20}(.{3,180})", "i"));
                    if (descMatch && descMatch[1]) proc.description = normalizeText(descMatch[1]);
                }

                if (!proc.description && scanLines.length) {
                    const candidate = scanLines[0].replace(codeRegex, "").trim();
                    proc.description = normalizeText(candidate.split(/[|\-:]/)[0] || "");
                }

                // Benefit level (percent) - try multiple patterns
                const benPatterns = [
                    new RegExp(code + ".{0,120}?(\\d{1,3}%)(?:\\s*-\\s*\\d{1,3}%)*", "i"),
                    /(Benefit(?: level)?|Coverage)[:\s]*(\\d{1,3}%)/i,
                    /(\\d{1,3}%)(?:\\s*-\\s*\\d{1,3}%){0,1}/i
                ];
                for (const p of benPatterns) {
                    const m = combined.match(p);
                    if (m && m[1]) { proc.benefit_level = m[1].trim(); break; }
                }

                // Deductible: look for YES/NO near code or explicit "Deductible" labels
                const ded = combined.match(/(Deductible|Ded|Deductible applies)[:\s]*(Yes|No|YES|NO|Y|N)/i) || combined.match(/(Yes|No|YES|NO|Y|N)(?:\s*deductible)/i);
                if (ded && ded[2]) proc.deductible = /y/i.test(ded[2]) ? "YES" : /n/i.test(ded[2]) ? "NO" : ded[2];
                else if (ded && ded[1] && /yes|no/i.test(ded[1])) proc.deductible = /y/i.test(ded[1]) ? "YES" : "NO";

                // Frequency limit like 1 TIME IN 6 MONTHS or 1X12Months
                const freq = text.match(new RegExp(code + ".{0,200}?(\\d+\\s*(TIME|X)\\s*(IN|/)?\\s*\\d+\\s*(MONTHS|YEARS)?|Once per [A-Za-z0-9 \\\-/]+|Once per [A-Za-z0-9 \\\-]+)", "i")) ||
                             text.match(/(Once per [A-Za-z0-9 \-]+|1\s*(TIME|X)\s*(IN)?\s*\d+\s*(MONTHS|YEARS)?|\d+X\d+Months)/i);
                if (freq && freq[1]) proc.frequency_limit = freq[1].trim();

                // patient responsibility and network fee
                const patPct = combined.match(/(Patient Responsibility|Patient Resp|Patient).*?(\d{1,3}%)/i) || combined.match(/\b(\d{1,3}%)(?!(?:.*\$))/i);
                const patMoney = combined.match(/(Patient Responsibility|Network Fee|Network fee|Network).*?(\$\d{1,3},?\d{0,3}\.\d{2})/i) || combined.match(/\$\d{1,3},?\d{0,3}\.\d{2}/i);
                if (patPct && patPct[2]) proc.patient_responsibility = patPct[2].trim();
                if (patMoney && patMoney[2]) proc.network_fee = proc.network_fee || patMoney[2].trim();
                else if (patMoney && patMoney[0]) proc.network_fee = proc.network_fee || patMoney[0].trim();

                if (!proc.benefit_level) {
                    const explicitBenefit = extractLabeledValue(text, ["Benefit Level", "Benefit", "Coverage", "Coinsurance", "Copay"]);
                    if (explicitBenefit) proc.benefit_level = explicitBenefit.match(/\d{1,3}%/)?.[0] || explicitBenefit;
                }
                if (!proc.patient_responsibility) {
                    const explicitPatient = extractLabeledValue(text, ["Patient Responsibility", "Patient Resp", "Patient Share", "Your Share", "Your Portion"]);
                    if (explicitPatient) proc.patient_responsibility = explicitPatient.match(/\d{1,3}%/)?.[0] || explicitPatient;
                }
                if (!proc.network_fee) {
                    const explicitNetwork = extractLabeledValue(text, ["Network Fee", "Network Cost", "Allowed Amount", "Covered Amount", "Member Cost"]);
                    if (explicitNetwork) proc.network_fee = explicitNetwork.match(/\$\d{1,3},?\d{0,3}\.\d{2}/)?.[0] || explicitNetwork;
                }
                if (!proc.age_limit) {
                    const explicitAge = extractLabeledValue(text, ["Age Limit", "Age", "Max Age", "Age Range"]);
                    if (explicitAge) proc.age_limit = explicitAge.replace(/[^0-9\-to ]/gi, "").trim();
                }
                if (!proc.late_date_of_service) {
                    const explicitLate = extractLabeledValue(text, ["Late Date of Service", "Date of Service", "Late Date", "Service Date"]);
                    if (explicitLate) proc.late_date_of_service = explicitLate.match(/\d{1,2}\/\d{1,2}\/\d{2,4}/)?.[0] || explicitLate;
                }

                const lateMatch = combined.match(/(Late Date of Service|Date of Service|Late Date|Service Date)[:\s]*(\d{1,2}\/\d{1,2}\/\d{2,4})/i) || combined.match(/\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/);
                if (lateMatch) proc.late_date_of_service = proc.late_date_of_service || lateMatch[2] || lateMatch[0];

                const age = combined.match(/age limit[:\s]*([0-9\-to ]{1,20})/i) || combined.match(/age[:\s]*([0-9]{1,2}(?:\-| to | up to |\s)[0-9]{0,2})/i);
                if (age && age[1] && !proc.age_limit) proc.age_limit = age[1].replace(/[^0-9\-to ]/gi, "").trim();

                // If description still empty, take first non-empty line
                if (!proc.description) {
                    const lines = text.split(/\n/).map(l => l.trim()).filter(Boolean);
                    if (lines.length) proc.description = lines.slice(0,3).join(" ").slice(0,120);
                }
            } catch (e) {
                console.warn("[DD] parseProcedureFromText error:", e.message);
            }

            // Normalize some fields
            if (!proc.benefit_level) proc.benefit_level = "";
            if (!proc.patient_responsibility && proc.benefit_level) {
                // infer patient responsibility if benefit_level is percent
                const m = proc.benefit_level.match(/(\d{1,3})%/);
                if (m) proc.patient_responsibility = (100 - Number(m[1])) + "%";
            }

            return proc;
        }

        function normalizeText(text) {
            return (text || "").replace(/\u00A0/g, ' ').replace(/[\t\r]+/g, ' ').replace(/\s+/g, ' ').trim();
        }

        function findNearestCodeElement(code, root = document) {
            const regex = new RegExp(`\\b${code}\\b`, "i");
            const candidates = [...root.querySelectorAll('tr, li, div, p, span, td, th')];
            let best = null;
            let bestLen = Infinity;

            for (const el of candidates) {
                const text = normalizeText(el.innerText);
                if (!text || !regex.test(text)) continue;
                const len = text.length;
                if (len < bestLen) {
                    best = el;
                    bestLen = len;
                }
            }

            return best || null;
        }

        function extractNearbyText(el) {
            const texts = [];
            if (!el) return "";
            const add = node => {
                if (node && node.innerText) {
                    const text = normalizeText(node.innerText);
                    if (text) texts.push(text);
                }
            };

            add(el);
            add(el.parentElement);
            add(el.previousElementSibling);
            add(el.nextElementSibling);
            if (el.parentElement && el.parentElement.previousElementSibling) add(el.parentElement.previousElementSibling);
            if (el.parentElement && el.parentElement.nextElementSibling) add(el.parentElement.nextElementSibling);

            return [...new Set(texts)].join(" | ");
        }

        function parseProcedureFromDOM(code, container) {
            const target = container && container.querySelector ? (findNearestCodeElement(code, container) || container) : (findNearestCodeElement(code) || document.body);
            const html = (target && target.innerText) ? target.innerText : document.body.innerText;
            const normalized = normalizeText(html);
            const proc = parseProcedureFromText(code, normalized);

            if (target && target.querySelectorAll) {
                const rows = [...target.querySelectorAll('tr, li, div, p, td, th')];
                for (const row of rows) {
                    const rowText = normalizeText(row.innerText || "");
                    if (!rowText || !rowText.toUpperCase().includes(code.toUpperCase())) continue;
                    const nearby = extractNearbyText(row);
                    const proc2 = parseProcedureFromText(code, nearby);
                    if (proc2.description && proc2.description.length > proc.description.length) proc.description = proc2.description;
                    if (proc2.benefit_level) proc.benefit_level = proc2.benefit_level;
                    if (proc2.deductible) proc.deductible = proc2.deductible;
                    if (proc2.frequency_limit) proc.frequency_limit = proc2.frequency_limit;
                    if (proc2.age_limit) proc.age_limit = proc2.age_limit;
                    if (proc2.late_date_of_service) proc.late_date_of_service = proc2.late_date_of_service;
                    if (proc2.network_fee) proc.network_fee = proc2.network_fee;
                    if (proc2.patient_responsibility) proc.patient_responsibility = proc2.patient_responsibility;
                }
            }

            return proc;
        }

        function parseTableProcedures(table) {
            if (!table) return null;
            const allRows = [...table.querySelectorAll('tr')].filter(tr => normalizeText(tr.innerText).length > 10);
            if (!allRows.length) return null;

            let headerCells = [...table.querySelectorAll('thead tr th')];
            if (!headerCells.length && allRows.length) {
                const firstRowCells = [...allRows[0].querySelectorAll('th, td')];
                if (firstRowCells.length > 1) headerCells = firstRowCells;
            }

            const headers = headerCells.map(th => normalizeText(th.innerText).toLowerCase());
            const dataRows = headerCells.length && allRows.length ? allRows.slice(1) : allRows;
            const procedures = [];

            for (const row of dataRows) {
                const cells = [...row.querySelectorAll('td, th')];
                if (!cells.length) continue;
                const rowText = normalizeText(cells.map(td => td.innerText).join(' | '));
                const codeMatch = rowText.match(/\bD\d{4}\b/);
                if (!codeMatch) continue;
                const code = codeMatch[0].toUpperCase();
                const proc = buildProcedureSkeleton([code])[0];

                if (headers.length === cells.length && headers.length > 1) {
                    headers.forEach((header, idx) => {
                        const value = normalizeText(cells[idx].innerText);
                        if (!value) return;
                        if (/description|service|procedure|summary|benefit info/i.test(header)) {
                            if (!proc.description) proc.description = value;
                        }
                        if (/benefit|level|coverage.*%|percentage|copay|coinsurance/i.test(header)) {
                            proc.benefit_level = proc.benefit_level || value.match(/\d{1,3}%/)?.[0] || proc.benefit_level;
                        }
                        if (/deduct|deductible/i.test(header)) {
                            proc.deductible = proc.deductible || (/(yes|no)/i.exec(value)?.[0]?.toUpperCase() || value);
                        }
                        if (/frequency|limit|maximum|max|once per|per year|per month/i.test(header)) {
                            proc.frequency_limit = proc.frequency_limit || value;
                        }
                        if (/age/i.test(header)) {
                            proc.age_limit = proc.age_limit || value;
                        }
                        if (/late date|date of service|service date|late/i.test(header)) {
                            proc.late_date_of_service = proc.late_date_of_service || value.match(/\d{1,2}\/\d{1,2}\/\d{2,4}/)?.[0] || value;
                        }
                        if (/network|fee|allowed/i.test(header)) {
                            proc.network_fee = proc.network_fee || value.match(/\$\d{1,3},?\d{0,3}\.\d{2}/)?.[0] || value;
                        }
                        if (/patient responsibility|patient resp|member cost|your share|your portion/i.test(header)) {
                            proc.patient_responsibility = proc.patient_responsibility || value.match(/\d{1,3}%/)?.[0] || value;
                        }
                    });
                }

                const parsed = parseProcedureFromText(code, rowText);
                for (const key of Object.keys(parsed)) {
                    if (!proc[key] && parsed[key]) {
                        proc[key] = parsed[key];
                    }
                }
                if (!proc.description || isGenericUIText(proc.description)) {
                    proc.description = parsed.description;
                }
                procedures.push(proc);
            }
            return procedures.length ? procedures : null;
        }

        function extractCodeDataComprehensive(code, pageText) {
            // Extract procedure details by scanning the entire page text more aggressively
            const proc = buildProcedureSkeleton([code])[0];
            if (!pageText) {
                console.log(`[DD] No page text available for ${code}`);
                return proc;
            }

            const escapedCode = escapeRegExp(code);
            const lines = pageText.split(/\r?\n/).map(l => normalizeText(l)).filter(Boolean);
            const codeLineIndex = lines.findIndex(line => new RegExp(`\\b${escapedCode}\\b`, 'i').test(line));

            if (codeLineIndex < 0) {
                console.log(`[DD] Code ${code} not found in full page scan`);
                return proc; // Code not found
            }

            console.log(`[DD] Comprehensive extraction: Found ${code} at line index ${codeLineIndex}, scanning context...`);

            // Get surrounding context: 2 lines before, the code line, and 10 lines after
            const startIdx = Math.max(0, codeLineIndex - 2);
            const endIdx = Math.min(lines.length, codeLineIndex + 15);
            const contextLines = lines.slice(startIdx, endIdx);
            const contextText = contextLines.join(' | ');

            // Try to extract description from the code line or nearby
            const codeLine = lines[codeLineIndex];
            const descMatch = codeLine.match(new RegExp(code + '[\\s\\-:|]{1,30}(.{5,150})', 'i'));
            if (descMatch && descMatch[1]) {
                proc.description = normalizeText(descMatch[1]).trim();
                console.log(`[DD] ${code} desc from line: ${proc.description.substring(0, 50)}...`);
            } else if (!proc.description && contextLines.length > 1) {
                const candidate = contextLines.filter((l, i) => i !== codeLineIndex - startIdx)[0];
                if (candidate && candidate.length > 10) {
                    proc.description = normalizeText(candidate).slice(0, 150);
                    console.log(`[DD] ${code} desc from context: ${proc.description.substring(0, 50)}...`);
                }
            }

            // Extract benefit level - look for percentages near the code
            const benefitPatterns = [
                new RegExp(code + '.{0,200}?(\\d{1,3}%)(?:\\s*-\\s*\\d{1,3}%)*', 'i'),
                new RegExp(code + '.{0,300}?(\\d{1,3}%)', 'i'),
                /(\d{1,3}%)/
            ];
            for (const pattern of benefitPatterns) {
                const match = contextText.match(pattern);
                if (match && match[1]) {
                    proc.benefit_level = match[1].trim();
                    console.log(`[DD] ${code} benefit: ${proc.benefit_level}`);
                    break;
                } else if (match && match[0]) {
                    proc.benefit_level = match[0].trim();
                    console.log(`[DD] ${code} benefit: ${proc.benefit_level}`);
                    break;
                }
            }

            // Extract deductible (YES/NO)
            const dedMatch = contextText.match(/(deductible|ded)[:\s]*(yes|no|y|n)/i) ||
                            contextText.match(/(yes|no|y|n)\s+(deductible|ded)/i);
            if (dedMatch) {
                const answer = dedMatch[2] || dedMatch[1];
                proc.deductible = /^y/i.test(answer) ? 'YES' : /^n/i.test(answer) ? 'NO' : answer.toUpperCase();
                console.log(`[DD] ${code} deductible: ${proc.deductible}`);
            }

            // Extract frequency limit
            const freqPattern = /(\d+\s*(TIME|X|time)\s*(IN|in|\/)??\s*\d+\s*(MONTHS|months|YEARS|years|YEAR|year|MONTH|month)|once\s+per\s+[a-z0-9\s]+)/i;
            const freqMatch = contextText.match(freqPattern);
            if (freqMatch && freqMatch[0]) {
                proc.frequency_limit = freqMatch[0].trim();
                console.log(`[DD] ${code} frequency: ${proc.frequency_limit}`);
            }

            // Extract age limit
            const agePatterns = [
                /age\s*(?:limit)?\s*[:\s]*([0-9]{1,2}\s*(?:-|to|through)\s*[0-9]{0,2})/i,
                /([0-9]{1,2}\s*(?:-|to)\s*[0-9]{0,2})\s*(?:years|yrs|age)/i,
                /age\s*(?:limit)?\s*[:\s]*([0-9]+)/i
            ];
            for (const pattern of agePatterns) {
                const match = contextText.match(pattern);
                if (match && match[1]) {
                    proc.age_limit = match[1].replace(/[^0-9\-to ]/gi, '').trim();
                    console.log(`[DD] ${code} age_limit: ${proc.age_limit}`);
                    break;
                }
            }

            // Extract late date of service
            const datePattern = /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/;
            const dateMatch = contextText.match(datePattern);
            if (dateMatch) {
                proc.late_date_of_service = dateMatch[0];
                console.log(`[DD] ${code} late_date: ${proc.late_date_of_service}`);
            }

            // Extract network fee (dollar amount)
            const feePattern = /\$\d{1,3},?\d{0,3}\.\d{2}/;
            const feeMatch = contextText.match(feePattern);
            if (feeMatch) {
                proc.network_fee = feeMatch[0];
                console.log(`[DD] ${code} network_fee: ${proc.network_fee}`);
            }

            // Extract patient responsibility (percent or dollar)
            const patPatterns = [
                /(patient\s+responsibility|patient\s+resp|member\s+cost|your\s+share)\s*[:\s]*(\d{1,3}%|\$\d{1,3},?\d{0,3}\.\d{2})/i,
                /\d{1,3}%(?!(?:.*\d{1,3}%))/i
            ];
            for (const pattern of patPatterns) {
                const match = contextText.match(pattern);
                if (match) {
                    const value = match[2] || match[0];
                    if (!/benefit|coverage|coinsurance/.test(match[0])) {
                        proc.patient_responsibility = value.trim();
                        console.log(`[DD] ${code} patient_resp: ${proc.patient_responsibility}`);
                        break;
                    }
                }
            }

            return proc;
        }

        function parseProceduresFromTable(container) {
            if (!container) return null;
            const tables = [...container.querySelectorAll('table')];
            if (!tables.length) return null;
            const proceduresByCode = {};
            for (const table of tables) {
                const parsed = parseTableProcedures(table);
                if (!parsed) continue;
                for (const proc of parsed) {
                    const code = proc.procedure_code.toUpperCase();
                    if (!proceduresByCode[code]) proceduresByCode[code] = proc;
                    else proceduresByCode[code] = { ...proceduresByCode[code], ...proc };
                }
            }
            return Object.values(proceduresByCode).length ? Object.values(proceduresByCode) : null;
        }

        function parseProceduresFromResultArea(resultArea) {
            const procedures = [];
            const text = normalizeText(resultArea.innerText || '');
            const codes = [...new Set((text.match(/\bD\d{4}\b/g) || []).map(c => c.toUpperCase()))];
            const rows = [...resultArea.querySelectorAll('tr, li, div, p, span, td, th')]
                .map(el => normalizeText(el.innerText || ''))
                .filter(Boolean);

            for (const code of codes) {
                const escapedCode = escapeRegExp(code);
                const codeEl = findNearestCodeElement(code, resultArea);
                if (codeEl) {
                    procedures.push(parseProcedureFromDOM(code, codeEl));
                    continue;
                }

                const candidateLine = rows.find(line => new RegExp(`\\b${escapedCode}\\b`, 'i').test(line) && isValidSearchResultText(line));
                if (candidateLine) {
                    procedures.push(parseProcedureFromText(code, candidateLine));
                    continue;
                }

                const fallbackLine = text.split(/\r?\n/).map(line => normalizeText(line)).find(line => new RegExp(`\\b${escapedCode}\\b`, 'i').test(line) && !isGenericUIText(line));
                if (fallbackLine) {
                    procedures.push(parseProcedureFromText(code, fallbackLine));
                    continue;
                }

                procedures.push(buildProcedureSkeleton([code])[0]);
            }
            return procedures.length ? procedures : null;
        }

        function buildProcedureSkeleton(codes) {
            return codes.map(code => ({
                procedure_code: code,
                description: "",
                benefit_level: "",
                deductible: "",
                frequency_limit: "",
                age_limit: "",
                late_date_of_service: "",
                network_fee: "",
                patient_responsibility: ""
            }));
        }

        async function searchProcedureCodes(isBenefitsTabOpened = false, procedureCodeBatches = []) {
            const procedureCodes = procedureCodeBatches.flat();
            const bc = {
                codes_searched: procedureCodes.slice(),
                extra_codes: [],
                procedure_count: 0,
                procedures: [],
                source: "Delta Dental Portal - Benefit & Coverage Details",
                timestamp: new Date().toISOString()
            };

            if (!isBenefitsTabOpened) {
                await clickTabByLabels(["Benefits Search", "Benefits", "Benefit Search"], 2000);
            }

            let { input, btn, searchControl } = await findSearchInputAndButton();
            if (!input) {
                if (!isBenefitsTabOpened) {
                    await clickTabByLabels(["Benefits Search", "Benefits", "Benefit Search"], 2000);
                    const retry = await findSearchInputAndButton();
                    input = retry.input;
                    btn = retry.btn;
                    searchControl = retry.searchControl;
                }
                if (!input) {
                    console.warn('[DD] No search input found in Benefits Search tab');
                }
            }

            const resultsByCode = {};
            const codesSearched = [...procedureCodes];
            let fullResultText = '';
            procedureCodes.forEach(code => {
                resultsByCode[code] = buildProcedureSkeleton([code])[0];
            });

            const hasProcedureData = (proc) => Boolean(proc && (proc.description || proc.benefit_level || proc.deductible || proc.frequency_limit || proc.age_limit || proc.late_date_of_service || proc.network_fee || proc.patient_responsibility));

            const mergeResults = (procedures) => {
                if (!procedures || !procedures.length) return;
                for (const proc of procedures) {
                    const code = (proc.procedure_code || '').toUpperCase();
                    if (!code) continue;
                    if (!resultsByCode[code]) {
                        resultsByCode[code] = buildProcedureSkeleton([code])[0];
                        if (!codesSearched.includes(code)) codesSearched.push(code);
                    }
                    resultsByCode[code] = { ...resultsByCode[code], ...proc };
                }
            };

            const addExtraCodesFromArea = (areaText) => {
                if (!areaText) return;
                const foundCodes = [...new Set((areaText.match(/\bD\d{4}\b/gi) || []).map(c => c.toUpperCase()))];
                for (const code of foundCodes) {
                    if (!resultsByCode[code]) {
                        resultsByCode[code] = buildProcedureSkeleton([code])[0];
                        if (!codesSearched.includes(code)) codesSearched.push(code);
                    }
                }
            };

            if (!input) {
                console.warn('[DD] No dedicated search input found — scanning page content for codes');
                for (const code of procedureCodes) {
                    const codeEl = findNearestCodeElement(code, document);
                    if (codeEl) {
                        mergeResults([parseProcedureFromDOM(code, codeEl)]);
                    } else {
                        bc.extra_codes.push(code);
                    }
                }
            } else {
                const searchOnce = async (codes) => {
                    try {
                        if (!input) return { resultArea: document.body, extracted: [] };

                        const batchTextInput = codes.join(', ');
                        input.focus();
                        if (typeof input.select === 'function') input.select();
                        input.value = batchTextInput;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));

                        let attempt = 0;
                        let resultArea = null;
                        let batchText = '';

                        // Try the search trigger multiple times if results are not appearing
                        while (attempt < 3) {
                            const searchTrigger = findSearchTrigger(input, btn || searchControl);
                            if (searchTrigger) {
                                clickElement(searchTrigger);
                                console.log(`[DD] Clicked search trigger (attempt ${attempt + 1})`);
                            } else if (btn) {
                                clickElement(btn);
                                console.log(`[DD] Clicked identified button (attempt ${attempt + 1})`);
                            } else {
                                const form = input.closest('form');
                                if (form) {
                                    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"], button, input[type="button"]');
                                    if (submitBtn) {
                                        clickElement(submitBtn);
                                        console.log(`[DD] Clicked form submit button (attempt ${attempt + 1})`);
                                    } else {
                                        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                                        console.log(`[DD] Dispatched form submit (attempt ${attempt + 1})`);
                                    }
                                } else {
                                    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                                    input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                                    console.log(`[DD] Dispatched Enter key on input (attempt ${attempt + 1})`);
                                }
                            }

                            // Wait a bit for results to render
                            await sleep(800 + attempt * 400);
                            resultArea = findSearchResultsArea(input);
                            batchText = resultArea ? normalizeText(resultArea.innerText || '') : '';

                            // If we see codes or substantial text, stop retrying
                            if (/(\bD\d{4}\b)/i.test(batchText) || (batchText && batchText.length > 50)) {
                                break;
                            }

                            // Try stimulating the input and search control again
                            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                            input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                            await sleep(300);
                            attempt++;
                        }

                        // Final wait for any asynchronous content
                        await waitForSearchResults(resultArea || document.body, 15000);

                        resultArea = resultArea || findSearchResultsArea(input);
                        batchText = resultArea ? normalizeText(resultArea.innerText || '') : '';
                        let extracted = parseProceduresFromTable(resultArea) || parseProceduresFromResultArea(resultArea) || [];

                        // If the batch extracted nothing, attempt per-code aggressive extraction immediately
                        if ((!extracted || !extracted.length) && codes && codes.length) {
                            console.log('[DD] No batch extraction found — performing aggressive per-code extraction');
                            const pageText = normalizeText((resultArea && resultArea.innerText) || document.body.innerText || '');
                            const aggressive = [];
                            for (const code of codes) {
                                const codeEl = findNearestCodeElement(code, resultArea || document.body);
                                const fromDom = codeEl ? parseProcedureFromDOM(code, codeEl) : null;
                                const fromText = parseProcedureFromText(code, pageText);
                                const fromFull = extractCodeDataComprehensive(code, pageText);
                                const merged = { ...buildProcedureSkeleton([code])[0], ...(fromText || {}), ...(fromDom || {}), ...(fromFull || {}) };
                                aggressive.push(merged);
                            }
                            extracted = aggressive;
                        }

                        addExtraCodesFromArea(resultArea ? resultArea.innerText : '');
                        return { resultArea, extracted, fullResultText: batchText };
                    } catch (e) {
                        console.warn('[DD] searchProcedureCodes error:', e.message);
                        return { resultArea: document.body, extracted: [] };
                    }
                };

                for (let batchIndex = 0; batchIndex < procedureCodeBatches.length; batchIndex++) {
                    const batch = procedureCodeBatches[batchIndex] || [];
                    if (!batch.length) continue;

                    console.log(`[DD] Searching procedure batch ${batchIndex + 1}/${procedureCodeBatches.length}: ${batch.join(', ')}`);
                    const { resultArea, extracted, fullResultText: batchText } = await searchOnce(batch);
                    if (batchText) fullResultText += `\n\n--- BATCH ${batchIndex + 1} RESULTS ---\n${batchText}`;
                    mergeResults(extracted);

                    const pageText = normalizeText((resultArea && resultArea.innerText) || document.body.innerText || '');
                    for (const code of batch) {
                        const proc = resultsByCode[code];
                        if (hasProcedureData(proc)) continue;

                        const fromResultText = parseProcedureFromText(code, pageText);
                        const candidateContainer = resultArea || document.body;
                        const codeEl = findNearestCodeElement(code, candidateContainer);
                        const fromDom = codeEl ? parseProcedureFromDOM(code, codeEl) : null;
                        const fromPage = extractCodeDataComprehensive(code, normalizeText(document.body.innerText || ''));
                        const mergedProc = {
                            ...buildProcedureSkeleton([code])[0],
                            ...fromResultText,
                            ...(fromDom || {}),
                            ...fromPage
                        };

                        if (hasProcedureData(mergedProc)) {
                            resultsByCode[code] = { ...proc, ...mergedProc };
                        }
                    }

                    bc.procedures = Object.values(resultsByCode).map(proc => ({ ...buildProcedureSkeleton([proc.procedure_code])[0], ...proc }));
                    bc.procedure_count = bc.procedures.length;
                    data.delta_dental_data.benefit_coverage = bc;
                    await saveToStorage(data);
                    console.log(`[DD] Saved batch ${batchIndex + 1}/${procedureCodeBatches.length} results to storage`);

                    const batchFoundCount = batch.filter(code => hasProcedureData(resultsByCode[code])).length;
                    if (batchFoundCount < batch.length) {
                        console.log(`[DD] Batch ${batchIndex + 1} returned partial results; retrying each code individually`);
                        for (const code of batch) {
                            const { extracted: individualExtracted, fullResultText: individualText } = await searchOnce([code]);
                            mergeResults(individualExtracted);
                            if (individualText) fullResultText += `\n\n--- ${code} RETRY ---\n${individualText}`;
                            await sleep(600);
                        }
                    }
                }

                // ── STEP 6B: Fill missing procedure data from full page scan ──────
                console.log('[DD] Step 6B: Filling missing procedure data...');
                const pageFullText = normalizeText(document.body.innerText || '');
                console.log(`[DD] Page text length: ${pageFullText.length} characters`);

                let emptyCodesCount = 0;
                let filledCodesCount = 0;

                for (const code of procedureCodes) {
                    const proc = resultsByCode[code];
                    if (!hasProcedureData(proc)) {
                        emptyCodesCount++;
                        console.log(`[DD] Extracting missing data for ${code} from full page`);
                        const enhanced = extractCodeDataComprehensive(code, pageFullText);
                        resultsByCode[code] = { ...proc, ...enhanced };

                        const enhancedHasData = hasProcedureData(enhanced);
                        if (enhancedHasData) {
                            filledCodesCount++;
                            console.log(`[DD] ✓ Successfully filled data for ${code}`);
                        } else {
                            console.log(`[DD] ✗ Failed to fill data for ${code} from full page scan`);
                        }
                    }
                }

                console.log(`[DD] Step 6B complete: ${emptyCodesCount} empty codes, ${filledCodesCount} successfully filled`);

                for (const code of procedureCodes) {
                    const proc = resultsByCode[code];
                    if (proc && !hasProcedureData(proc)) {
                        const codeEl = findNearestCodeElement(code, document);
                        if (codeEl) mergeResults([parseProcedureFromDOM(code, codeEl)]);
                    }
                }
            }

            bc.codes_searched = codesSearched;
            const merged = Object.values(resultsByCode).map(proc => ({ ...buildProcedureSkeleton([proc.procedure_code])[0], ...proc }));

            bc.procedures = merged;
            bc.procedure_count = merged.length;
            data.delta_dental_data.benefit_coverage = bc;
            await saveToStorage(data);
            console.log('[DD] Procedure code search complete — saved to storage');
        }

        // ── DONE ─────────────────────────────────────────────────────
        data._crawl_complete = true;
        await saveToStorage(data);
        console.log("[DD] 🎉 Crawl complete!");
    }

    // ── MESSAGE LISTENER ─────────────────────────────────────────────
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        if (message.command === "START_CRAWL") {
            // Reply immediately so popup doesn't error out
            sendResponse({ status: "crawl_started" });

            crawlDeltaDental().catch((err) => {
                console.error("[DD] Crawl failed:", err);
                chrome.storage.local.set({
                    audit_context: {
                        _crawl_complete: true,
                        _crawl_error:    err.message,
                        crawl_timestamp: new Date().toISOString()
                    }
                });
            });
        }
        return true;
    });  

    console.log("[DD] Content script ready on:", window.location.href);

})();

