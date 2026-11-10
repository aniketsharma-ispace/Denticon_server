/*
 * content_DD_MO.js
 * Delta Dental of Missouri Provider Portal (providers.deltadentalmo.com) benefit extractor.
 *
 * Same architecture as content_dd_toolkit.js — load this SAME file in BOTH content-script worlds:
 *   { matches: ["https://providers.deltadentalmo.com/*"], js: ["content_DD_MO.js"], run_at: "document_start", world: "MAIN" }
 *   { matches: ["https://providers.deltadentalmo.com/*"], js: ["content_DD_MO.js"], run_at: "document_start", world: "ISOLATED" }
 *
 * MAIN world    : hooks fetch/XHR to learn the Bearer token + the enrollee/product/subscriber ids the
 *                 portal itself sends, then replays the four benefit endpoints.
 * ISOLATED world: popup messaging, chrome.storage.local and the JSON download.
 *
 * Usage: open a member on /member-benefits, wait for the page to finish loading, click Crawl in the popup.
 * If the extension was just installed/reloaded, refresh the portal tab first so the hook sees the page's calls.
 * The Bearer token is kept in memory only — it is never written to storage or to the output JSON.
 *
 * Endpoints (all POST, base https://api.deltadentalmo.com/dw-benefits-api/api/benefits/ — previously
 * https://ddmo-dw.ddmoapis.com/dw/benefits/api/benefits/; the base is learned from the page's own calls), in website order:
 *   summary-general            -> member / group / plan details
 *   summary-coveragelevel      -> every CDT code: % by network, deductible, frequency, age, limitations (paged)
 *   summary-maxanddeductible   -> annual maximum + deductible (max / met / remaining)
 *   summary-patienthistory     -> procedure history
 */

(() => {
    "use strict";

    const EXT_SOURCE = "delta-mo-extension";
    const PAGE_SOURCE = "delta-mo-page";
    const RESULT_STORAGE_KEY = "delta_mo_data";
    const PROGRESS_STORAGE_KEY = "delta_mo_progress";
    const CARRIER = "DELTA_MO";
    const DEFAULT_BENEFITS_BASE = "https://api.deltadentalmo.com/dw-benefits-api/api/benefits/";
    const BENEFITS_PATH = "/api/benefits/";
    const API_HOST_SUFFIXES = ["deltadentalmo.com", "ddmoapis.com"];
    const COVERAGE_PAGE_SIZE = 1000; // same size the portal uses
    const HISTORY_PAGE_SIZE = 200;   // portal's default response size
    const MAX_PAGES = 20;

    // Website order.
    const ENDPOINTS = Object.freeze([
        { key: "general", path: "summary-general", label: "member summary" },
        { key: "coverage", path: "summary-coveragelevel", label: "coverage levels" },
        { key: "maxDeductible", path: "summary-maxanddeductible", label: "maximum & deductible" },
        { key: "history", path: "summary-patienthistory", label: "patient history" }
    ]);

    // The ONLY procedure codes this scraper keeps (order preserved). Everything else
    // returned by the portal API is dropped from the normalized coverage output.
    // Codes are passed through normalizeCode() so "5212" and "D5212" both resolve to "D5212".
    const PROCEDURE_CODES = Object.freeze([...new Set([
        "D0180", "D0120", "D0140", "D0150", "D1208",
        "D0210", "D0220", "D0230", "D0240", "D0274", "D0330", "D0364", "D0431",
        "D1510", "D1110", "D1120", "D1206", "D1351",
        "D2140", "D2331", "D2391", "D2620", "D2740", "D2950", "D2962", "D2991",
        "D3347", "D3310", "D3330",
        "D4260", "D4249", "D4341", "D4355", "D4381", "D4346", "D4910",
        "D5860", "D5110", "D5740", "D5982",
        "D6194", "D6010", "D6056", "D6065",
        "D6245", "D6750", "5212", "5995", "2980",
        "D7259", "D7140", "D7210", "D7240", "D7953",
        "D8010", "D8080", "D8090",
        "D9430", "D9110", "D9222", "D9230", "D9239", "D9243", "D9310", "D9944",
        // Smile Partner Dental sheet codes, appended so existing coverage_levels positions are unchanged.
        "D1516", "D2160", "D5899", "D6057", "D6058"
    ].map(normalizeCode))]);
    const PROCEDURE_CODE_SET = new Set(PROCEDURE_CODES);

    // Retained category/label metadata for the requested procedure-code set.
    const CATEGORY_CODES = Object.freeze({
        EXAMS: ["D0180", "D0120", "D0140", "D0150"],
        DIAGNOSTIC: ["D0210", "D0220", "D0230", "D0240", "D0274", "D0330", "D0364", "D0431"],
        PREVENTATIVE: ["D1510", "D1516", "D1110", "D1120", "D1206", "D1208", "D1351"],
        "BASIC RESTORATIVE": ["D2140", "D2160", "D2331", "D2391", "D2620"],
        "MAJOR RESTORATIVE": ["D2740", "D2950", "D2962", "D2980", "D2991"],
        ENDODONTICS: ["D3347", "D3310", "D3330"],
        PERIODONTICS: ["D4260", "D4249", "D4341", "D4355", "D4381", "D4346", "D4910"],
        "REMOVABLE PROSTHO": ["D5860", "D5110", "D5212", "D5740", "D5899", "D5982", "D5995"],
        IMPLANT: ["D6194", "D6010", "D6056", "D6057", "D6058", "D6065"],
        "FIXED PROSTHO": ["D6245", "D6750"],
        "ORAL SURGERY": ["D7259", "D7140", "D7210", "D7240", "D7953"],
        ORTHODONTICS: ["D8010", "D8080", "D8090"],
        ADJUNCTIVE: ["D9430", "D9110", "D9222", "D9230", "D9239", "D9243", "D9310", "D9944"]
    });

    const PROCEDURE_LABELS = Object.freeze({
        D0180: "Perio Consult",
        D0120: "Periodic Exam",
        D0140: "Limited Exam",
        D0150: "Comprehensive Exam",
        D0210: "Full Mouth Xray",
        D0220: "PA",
        D0230: "PA Addtn",
        D0240: "Intraoral - Occlusal Image",
        D0274: "Bitewings",
        D0330: "Panoramic Xray",
        D0364: "CBCT - Limited Field of View",
        D0431: "Oral Cancer Screening (adjunctive test)",
        D1510: "Space Maintainer",
        D1516: "Space Maintainer - Bilateral",
        D1110: "Prophylaxis",
        D1120: "Prophylaxis Child",
        D1206: "Fluoride Varnish",
        D1208: "Fluoride",
        D1351: "Sealants",
        D2140: "Amalgam",
        D2160: "Amalgam - Three Surfaces",
        D2331: "Composite Filling",
        D2391: "Composite Filling - Posterior",
        D2620: "Restorative Onlay/Inlay",
        D2740: "Porcelain Crown",
        D2950: "Build up",
        D2962: "Porcelain Laminate Veneer",
        D2980: "Crown Repair",
        D2991: "D2991",
        D3347: "Retreatment of previous root canal therapy - premolar",
        D3310: "Endo",
        D3330: "Root Canal",
        D4260: "Osseous Surgery",
        D4249: "Crown Lengthening",
        D4341: "Scaling & Root Planning",
        D4346: "Scaling in Gingival Inflammation",
        D4355: "Full Mouth Debridement",
        D4381: "Arestin",
        D4910: "Perio Maintenance",
        D5860: "Over Denture Complete",
        D5110: "Dentures",
        D5212: "Mandibular Partial Denture - Resin Base",
        D5740: "Reline maxillary partial denture (direct)",
        D5899: "Prosth Removable",
        D5982: "Surgical stent",
        D5995: "Periodontal Medicament Carrier",
        D6194: "Implant",
        D6010: "Implant Body",
        D6056: "Implant Abutment",
        D6057: "Custom Implant Abutment",
        D6058: "Abutment Supported Porcelain Crown",
        D6065: "Implant Crown",
        D6245: "Pontic - porcelain/ceramic",
        D6750: "Retainer Crown - PFM High Noble",
        D7259: "Nerve dissection",
        D7140: "Simple Extraction",
        D7210: "Surgical Extraction",
        D7240: "Impacted Extraction",
        D7953: "Ridge Preservation Bone Graft",
        D8010: "Ortho",
        D8080: "Ortho",
        D8090: "Ortho",
        D9430: "Office visit for observation",
        D9110: "Palliative",
        D9222: "Gen Anesthesia",
        D9230: "Nitrous Oxide",
        D9239: "sedation/analgesia",
        D9243: "IV Sedation - Additional 15 min",
        D9310: "Consult",
        D9944: "Occlusal Guard"
    });

    const CATEGORY_BY_CODE = Object.freeze(Object.fromEntries(
        Object.entries(CATEGORY_CODES).flatMap(([category, codes]) => codes.map(code => [code, category]))
    ));

    const hasExtensionRuntime = Boolean(
        typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.id
    );

    if (hasExtensionRuntime) {
        installIsolatedBridge();
    } else {
        installMainWorldExtractor();
    }

    // =====================================================================
    // ISOLATED WORLD: popup bridge, storage, and download
    // =====================================================================

    function installIsolatedBridge() {
        if (globalThis.__DELTA_MO_ISOLATED_INSTALLED__) return;
        globalThis.__DELTA_MO_ISOLATED_INSTALLED__ = true;

        const pendingStarts = new Map();
        const pendingStatus = new Map();

        window.addEventListener("message", event => {
            if (event.source !== window || event.origin !== window.location.origin) return;
            const message = event.data;
            if (!message || message.source !== PAGE_SOURCE) return;

            if (message.type === "STARTED") {
                const wait = pendingStarts.get(message.requestId);
                if (wait) {
                    clearTimeout(wait.timer);
                    pendingStarts.delete(message.requestId);
                    wait.sendResponse({ status: message.status || "[+] DD MO crawl started.", started: true, requestId: message.requestId });
                }
                sendPopupStatus(message.status || "DD MO crawl started.", "working");
                return;
            }

            if (message.type === "MO_STATUS") {
                const wait = pendingStatus.get(message.requestId);
                if (wait) {
                    clearTimeout(wait.timer);
                    pendingStatus.delete(message.requestId);
                    wait.sendResponse(message.payload || { ready: false, message: "DD MO status unavailable." });
                }
                return;
            }

            if (message.type === "RESULT") {
                persistAndDownload(message.data).then(() => {
                    window.postMessage({ source: EXT_SOURCE, type: "RESULT_ACK", requestId: message.requestId }, window.location.origin);
                    const coverageRows = Number(message.data?.coverage_rows || 0);
                    const text = `[+] Done — ${coverageRows} coverage rows. JSON downloaded.`;
                    sendPopupStatus(text, "ready", { state: "COMPLETE" });
                }).catch(error => {
                    sendPopupStatus(`[!] Extraction finished, but save/download failed: ${error.message}`, "error", { state: "FAILED" });
                });
                return;
            }

            if (message.type === "STATUS") {
                sendPopupStatus(message.status, message.mode || "working", message.extra || {});
                return;
            }

            if (message.type === "ERROR") {
                const wait = pendingStarts.get(message.requestId);
                if (wait) {
                    clearTimeout(wait.timer);
                    pendingStarts.delete(message.requestId);
                    wait.sendResponse({ status: `[!] ${message.error || "DD MO extraction failed."}`, started: false });
                }
                sendPopupStatus(`[!] ${message.error || "DD MO extraction failed."}`, "error", { state: "FAILED" });
            }
        });

        chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
            if (request?.command === "START_CRAWL") {
                const requestId = makeId();
                const timer = setTimeout(() => {
                    const wait = pendingStarts.get(requestId);
                    if (!wait) return;
                    pendingStarts.delete(requestId);
                    wait.sendResponse({
                        status: "[!] DD MO page extractor is unavailable. Refresh the portal tab and ensure content_DD_MO.js is loaded in both MAIN and ISOLATED worlds.",
                        started: false
                    });
                }, 4000);
                pendingStarts.set(requestId, { sendResponse, timer });
                window.postMessage({ source: EXT_SOURCE, type: "START_CRAWL", requestId }, window.location.origin);
                return true;
            }

            if (request?.command === "GET_MO_STATUS") {
                const requestId = makeId();
                const timer = setTimeout(() => {
                    const wait = pendingStatus.get(requestId);
                    if (!wait) return;
                    pendingStatus.delete(requestId);
                    wait.sendResponse({ ready: false, message: "DD MO extractor is loading. Refresh the page if this persists." });
                }, 1500);
                pendingStatus.set(requestId, { sendResponse, timer });
                window.postMessage({ source: EXT_SOURCE, type: "GET_STATUS", requestId }, window.location.origin);
                return true;
            }

            return false;
        });

        function sendPopupStatus(status, mode = "working", extra = {}) {
            const payload = {
                carrier: CARRIER,
                status: String(status || ""),
                mode,
                state: extra.state || (mode === "error" ? "FAILED" : mode === "ready" ? "COMPLETE" : "RUNNING"),
                updated_at: Date.now(),
                ...extra
            };
            try {
                chrome.storage.local.set({ [PROGRESS_STORAGE_KEY]: payload }, () => { void chrome.runtime.lastError; });
            } catch (_) { /* storage may be unavailable */ }
            try {
                const maybePromise = chrome.runtime.sendMessage({ command: "STATUS_UPDATE", ...payload }, () => { void chrome.runtime.lastError; });
                if (maybePromise?.catch) maybePromise.catch(() => {});
            } catch (_) { /* popup may be closed */ }
        }

        async function persistAndDownload(data) {
            if (!data || typeof data !== "object") throw new Error("No valid extraction result was returned.");
            await new Promise((resolve, reject) => {
                chrome.storage.local.get("audit_context", result => {
                    if (chrome.runtime.lastError) { reject(new Error(chrome.runtime.lastError.message)); return; }
                    const context = result.audit_context || {};
                    context[RESULT_STORAGE_KEY] = data;
                    chrome.storage.local.set({ audit_context: context }, () => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve();
                    });
                });
            });
            downloadJson(data);
        }
    }

    // =====================================================================
    // MAIN WORLD: API interception and extraction
    // =====================================================================

    function installMainWorldExtractor() {
        if (globalThis.__DELTA_MO_MAIN_INSTALLED__) return;
        globalThis.__DELTA_MO_MAIN_INSTALLED__ = true;

        const nativeFetch = globalThis.fetch.bind(globalThis);
        const state = {
            benefitsBase: DEFAULT_BENEFITS_BASE,
            auth: null,               // in memory only
            callerService: "ProviderPortal",
            ctx: { enrolleeId: null, productId: null, subscriberId: null },
            general: null,            // last summary-general response seen from the page
            bodies: [],               // recent API request bodies that carried an enrolleeId
            directory: new Map(),     // enrolleeId -> { enrolleeId, productId, subscriberId, firstName, lastName }
            capturedAt: null,
            activeRun: null
        };

        interceptFetch(state, nativeFetch);
        interceptXHR(state);
        installPageMessageBridge(state, nativeFetch);
        globalThis.__DDMO_DEBUG__ = () => ({
            ctx: state.ctx,
            bodies: state.bodies.map(b => ({ benefits: b.isBenefits, label: b.label, body: b.body })),
            directory: [...state.directory.values()]
        });
        console.info("DD MO extractor installed. Open a member on member-benefits and wait for the page to finish loading.");
    }

    // ---- interception ---------------------------------------------------

    function isApiUrl(url) {
        try {
            // The portal itself (providers.deltadentalmo.com) also loads assets over XHR; only its API hosts count.
            const host = new URL(url, location.href).hostname;
            return host !== location.hostname && API_HOST_SUFFIXES.some(suffix => host === suffix || host.endsWith("." + suffix));
        } catch (_) { return false; }
    }

    function benefitsEndpointKey(url) {
        try {
            const u = new URL(url, location.href);
            if (!u.pathname.includes(BENEFITS_PATH)) return null;
            return ENDPOINTS.find(e => u.pathname.endsWith(e.path))?.key || null;
        } catch (_) { return null; }
    }

    function observeRequest(state, url, method, headers, bodyText) {
        if (!isApiUrl(url)) return;
        if (benefitsEndpointKey(url)) {
            try {
                const u = new URL(url, location.href);
                state.benefitsBase = u.origin + u.pathname.slice(0, u.pathname.lastIndexOf("/") + 1);
            } catch (_) { /* keep default */ }
        }

        const auth = headers.authorization;
        if (auth && /^bearer\s+\S+/i.test(auth)) state.auth = auth;
        if (headers["x-caller-service"]) state.callerService = headers["x-caller-service"];

        if (String(method || "GET").toUpperCase() !== "POST" || !bodyText) return;
        const body = parseJson(bodyText);
        if (!body || typeof body !== "object" || Array.isArray(body) || body.enrolleeId == null) return;

        const isBenefits = Boolean(benefitsEndpointKey(url));
        state.bodies.push({ body, isBenefits, label: currentDependentLabel() });
        if (state.bodies.length > 80) state.bodies.shift();
        rememberMember(state, { enrolleeId: body.enrolleeId, productId: body.productId, subscriberId: body.subscriberId });
        if (!isBenefits) return;
        if (state.ctx.enrolleeId != null && String(state.ctx.enrolleeId) !== String(body.enrolleeId)) {
            // Keep the directory when switching among members of the same family, but do not
            // leak members from a different subscriber into the next patient's family_members.
            if (state.ctx.subscriberId && body.subscriberId && String(state.ctx.subscriberId) !== String(body.subscriberId)) {
                state.directory.clear();
                state.bodies = [];
            }
            state.ctx = { enrolleeId: null, productId: null, subscriberId: null };
            state.general = null;
        }
        state.ctx.enrolleeId = body.enrolleeId;
        if (body.productId != null) state.ctx.productId = body.productId;
        if (body.subscriberId) state.ctx.subscriberId = body.subscriberId;
        state.capturedAt = Date.now();
    }

    function observeResponse(state, url, data) {
        harvestMembers(state, data);
        if (benefitsEndpointKey(url) === "general" && Array.isArray(data)) state.general = data;
    }

    function rememberMember(state, info) {
        if (info.enrolleeId == null) return;
        const key = String(info.enrolleeId);
        const prev = state.directory.get(key) || {};
        const patientName = info.patientName || [info.firstName, info.middleName, info.lastName].filter(Boolean).join(" ").trim();
        state.directory.set(key, {
            enrolleeId: info.enrolleeId,
            productId: info.productId ?? prev.productId ?? null,
            subscriberId: info.subscriberId ?? prev.subscriberId ?? null,
            firstName: info.firstName ?? prev.firstName ?? "",
            middleName: info.middleName ?? prev.middleName ?? "",
            lastName: info.lastName ?? prev.lastName ?? "",
            patientName: patientName || prev.patientName || null,
            relationship: info.relationship ?? prev.relationship ?? null,
            eligible: info.eligible ?? prev.eligible ?? null
        });
    }

    function pickKey(obj, re) {
        for (const k of Object.keys(obj)) if (re.test(k)) return obj[k];
        return undefined;
    }

    function harvestMembers(state, data, depth = 0) {
        if (!data || typeof data !== "object" || depth > 6) return;
        if (Array.isArray(data)) { for (const item of data) harvestMembers(state, item, depth + 1); return; }
        const id = pickKey(data, /^enrollee_?id$/i);
        const first = pickKey(data, /^(member_?|enrollee_?|dependent_?)?first_?name$/i);
        const middle = pickKey(data, /^(member_?|enrollee_?|dependent_?)?middle_?name$/i);
        const last = pickKey(data, /^(member_?|enrollee_?|dependent_?)?last_?name$/i);
        const relationship = pickKey(data, /^(relationship_?description|relationship)$/i);
        const eligible = pickKey(data, /^eligible$/i);
        if (id != null && (first || last)) {
            rememberMember(state, {
                enrolleeId: id,
                productId: pickKey(data, /^product_?id$/i),
                subscriberId: pickKey(data, /^subscriber_?id$/i),
                firstName: first,
                middleName: middle,
                lastName: last,
                patientName: [first, middle, last].filter(Boolean).join(" ").trim(),
                relationship,
                eligible
            });
        }
        for (const value of Object.values(data)) if (value && typeof value === "object") harvestMembers(state, value, depth + 1);
    }

    function currentDependentLabel() {
        try { return selectedDependentLabel(); } catch (_) { return null; }
    }

    function harvestPortalMemberOptions(state) {
        try {
            const nodes = document.querySelectorAll("option, [role='option'], mat-option, li");
            for (const node of nodes) {
                const label = String(node.textContent || "").replace(/\s+/g, " ").trim();
                if (!/^[A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z][A-Za-z'.-]*){1,2}$/.test(label)) continue;
                const values = [
                    node.value,
                    node.getAttribute?.("value"),
                    node.getAttribute?.("data-value"),
                    node.getAttribute?.("data-enrollee-id"),
                    ...Array.from(node.attributes || []).map(a => a.value)
                ];
                const enrolleeId = values
                    .map(v => String(v ?? "").trim())
                    .find(v => /^\d{6,12}$/.test(v));
                if (!enrolleeId) continue;
                const parts = label.split(/\s+/);
                rememberMember(state, {
                    enrolleeId: Number(enrolleeId),
                    firstName: parts[0] || "",
                    middleName: parts.length === 3 ? parts[1] : "",
                    lastName: parts.length >= 2 ? parts[parts.length - 1] : "",
                    patientName: label
                });
            }
        } catch (_) { /* DOM harvesting is best-effort */ }
    }

    // Find the enrollee the portal is showing by replaying summary-general for every identity the portal
    // itself used in this session and keeping the one whose returned name equals the dropdown selection.
    async function resolveSelectedMember(state, nativeFetch, label) {
        const url = `${state.benefitsBase}summary-general`;
        const getAuth = () => state.auth;
        const candidates = [];
        const seen = new Set();
        const add = rec => {
            if (!rec || rec.enrolleeId == null) return;
            const c = {
                enrolleeId: rec.enrolleeId,
                productId: rec.productId ?? state.ctx.productId,
                subscriberId: rec.subscriberId ?? state.ctx.subscriberId,
                extra: rec.extra || {}
            };
            const sig = JSON.stringify(c);
            if (seen.has(sig)) return;
            seen.add(sig);
            candidates.push(c);
        };
        const fromBody = b => {
            const { enrolleeId, productId, subscriberId, pageNumber, pageSize, ...rest } = b.body;
            return { enrolleeId, productId, subscriberId, extra: b.isBenefits ? rest : {} };
        };

        add(findInDirectory(state, label));
        const bodies = [...state.bodies].reverse();
        bodies.filter(b => b.label === label).forEach(b => add(fromBody(b)));
        bodies.forEach(b => add(fromBody(b)));
        [...state.directory.values()].reverse().forEach(add);
        try {
            document.querySelectorAll("option, [role='option'], mat-option, li").forEach(el => {
                if (!sameName(label, el.textContent)) return;
                const values = [el.value, ...Array.from(el.attributes || []).map(a => a.value)];
                for (const v of values) if (/^\d{6,12}$/.test(String(v ?? "").trim())) add({ enrolleeId: Number(v) });
            });
        } catch (_) { /* DOM lookup is best-effort */ }

        const tried = [];
        for (const c of candidates.slice(0, 12)) {
            const base = { ...c.extra, enrolleeId: c.enrolleeId, productId: c.productId, subscriberId: c.subscriberId };
            let resp;
            try { resp = await postJson(state, nativeFetch, url, base, getAuth); }
            catch (error) { if (error.authFailed) throw error; tried.push(`${c.enrolleeId}: ${error.message}`); continue; }
            harvestMembers(state, resp);
            const row = selectedGeneralRow(Array.isArray(resp) ? resp : [], c.enrolleeId);
            const returned = row ? buildPatientName(row) : "(none)";
            tried.push(`${c.enrolleeId} -> ${returned}`);
            if (row && sameName(label, returned)) return c;
        }
        console.warn("DD MO: no captured identity matched the dropdown selection. Tried:", tried, "Selected:", label);
        return null;
    }

    function nameTokens(text) {
        return String(text ?? "").toUpperCase().replace(/[^A-Z' -]/g, " ").split(/[\s]+/).filter(Boolean);
    }

    function sameName(a, b) {
        const x = nameTokens(a), y = nameTokens(b);
        return x.length > 0 && y.length > 0 && x[0] === y[0] && x[x.length - 1] === y[y.length - 1];
    }

    // Name shown in the portal's dependent dropdown, or null when Subscriber is selected / markup not found.
    function selectedDependentLabel() {
        const radios = [...document.querySelectorAll("input[type='radio'], [role='radio']")];
        const text = r => (r.labels?.[0]?.textContent || r.closest("label")?.textContent || r.parentElement?.textContent || r.getAttribute("aria-label") || "").trim();
        const isOn = r => r.checked === true || r.getAttribute("aria-checked") === "true";
        const dep = radios.find(r => /^dependent$/i.test(text(r)));
        if (!dep || !isOn(dep)) return null;
        const nodes = document.querySelectorAll("select, [role='combobox'], [aria-haspopup='listbox'], mat-select, [class*='select'], [class*='dropdown']");
        for (const node of nodes) {
            if (!(dep.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
            const label = (node.tagName === "SELECT" ? node.selectedOptions?.[0]?.textContent : node.textContent || "").trim();
            if (/^[A-Za-z][A-Za-z'.-]*(\s+[A-Za-z][A-Za-z'.-]*){1,2}$/.test(label)) return label;
        }
        return null;
    }

    function findInDirectory(state, label) {
        return [...state.directory.values()].find(m => (m.firstName || m.lastName) && sameName(label, `${m.firstName} ${m.lastName}`)) || null;
    }

    function interceptFetch(state, nativeFetch) {
        globalThis.fetch = function deltaMoFetch(input, init) {
            let capture = null;
            try {
                const url = typeof input === "string" ? input : input?.url || String(input);
                if (isApiUrl(url)) {
                    const method = init?.method || input?.method || "GET";
                    const headers = headersToObject(init?.headers || (typeof input === "object" ? input.headers : null));
                    const bodyText = typeof init?.body === "string" ? init.body : null;
                    if (bodyText != null || typeof input !== "object" || !input.clone) {
                        observeRequest(state, url, method, headers, bodyText);
                    } else {
                        input.clone().text().then(text => observeRequest(state, url, method, headers, text)).catch(() => {});
                    }
                    capture = url;
                }
            } catch (_) { /* never break the page */ }

            const promise = nativeFetch(input, init);
            if (capture) {
                promise.then(response => {
                    if (!response.ok) return;
                    response.clone().json().then(data => observeResponse(state, capture, data)).catch(() => {});
                }).catch(() => {});
            }
            return promise;
        };
    }

    function interceptXHR(state) {
        const proto = globalThis.XMLHttpRequest?.prototype;
        if (!proto) return;
        const nativeOpen = proto.open;
        const nativeSetHeader = proto.setRequestHeader;
        const nativeSend = proto.send;

        proto.open = function (method, url) {
            this.__deltaMo = { method, url: String(url), headers: {} };
            return nativeOpen.apply(this, arguments);
        };
        proto.setRequestHeader = function (name, value) {
            if (this.__deltaMo) this.__deltaMo.headers[String(name).toLowerCase()] = String(value);
            return nativeSetHeader.apply(this, arguments);
        };
        proto.send = function (body) {
            const meta = this.__deltaMo;
            if (meta && isApiUrl(meta.url)) {
                try { observeRequest(state, meta.url, meta.method, meta.headers, typeof body === "string" ? body : null); } catch (_) { /* ignore */ }
                this.addEventListener("load", () => {
                    try {
                        if (this.status < 200 || this.status >= 300) return;
                        const data = this.responseType === "json" ? this.response : parseJson(this.responseText);
                        observeResponse(state, meta.url, data);
                    } catch (_) { /* ignore */ }
                });
            }
            return nativeSend.apply(this, arguments);
        };
    }

    // ---- page <-> isolated bridge --------------------------------------

    function installPageMessageBridge(state, nativeFetch) {
        window.addEventListener("message", event => {
            if (event.source !== window || event.origin !== window.location.origin) return;
            const message = event.data;
            if (!message || message.source !== EXT_SOURCE) return;

            if (message.type === "RESULT_ACK") {
                if (state.activeRun?.requestId === message.requestId) state.activeRun.acknowledged = true;
                return;
            }

            if (message.type === "GET_STATUS") {
                postPageMessage("MO_STATUS", { requestId: message.requestId, payload: getStatus(state) });
                return;
            }

            if (message.type === "START_CRAWL") {
                const problem = readinessProblem(state);
                if (problem) {
                    postPageMessage("ERROR", { requestId: message.requestId, error: problem });
                    return;
                }
                postPageMessage("STARTED", { requestId: message.requestId, status: "[+] DD MO crawl requested. Fetching member benefits…" });
                startCrawl(state, nativeFetch, message.requestId).catch(error => {
                    state.activeRun = null;
                    setStatus("[!] " + error.message, "error", { state: "FAILED" });
                    postPageMessage("ERROR", { requestId: message.requestId, error: error.message });
                });
            }
        });
    }

    function readinessProblem(state) {
        if (state.activeRun) return "A DD MO crawl is already running.";
        if (!state.auth) return "Portal login token not captured yet. Refresh the Member Benefits page (with a member open), wait for it to load, then retry.";
        if (state.ctx.enrolleeId == null || state.ctx.productId == null) return "Member not captured yet. Open a member on the Member Benefits page and wait for it to finish loading, then retry.";
        if (!state.ctx.subscriberId) return "Subscriber ID not captured yet. Refresh the Member Benefits page and retry.";
        return null;
    }

    function getStatus(state) {
        const problem = state.activeRun ? null : readinessProblem(state);
        const row = selectedGeneralRow(state.general, state.ctx.enrolleeId);
        if (state.activeRun) return { ready: false, state: "RUNNING", message: "DD MO crawl in progress…" };
        if (problem) return { ready: false, message: `DD MO: ${problem}` };
        return { ready: true, message: "DD MO: Ready. Click Crawl to extract benefits." };
    }

    // ---- crawl ----------------------------------------------------------

    async function startCrawl(state, nativeFetch, requestId) {
        const problem = readinessProblem(state);
        if (problem) throw new Error(problem);

        // Capture every family member exposed by the portal selector before building the output.
        // This is intentionally additive: API responses still remain the source of truth for
        // relationship/eligibility details when those fields are available.
        harvestPortalMemberOptions(state);

        const portalLabel = selectedDependentLabel();
        const run = { requestId, startedAt: Date.now(), acknowledged: false };
        state.activeRun = run;
        let ctx = { ...state.ctx };
        if (portalLabel) {
            setStatus("Matching the selected dependent…", "working", { state: "RUNNING" });
            const match = await resolveSelectedMember(state, nativeFetch, portalLabel);
            if (!match) {
                throw new Error("Could not match the dependent selected in the portal. Select the dependent again, wait for the page to finish loading, then retry.");
            }
            ctx = match;
        }
        const authSnapshot = () => state.auth; // pick up a refreshed token if the page renews it mid-run
        const raw = {};
        const failed = [];
        const warnings = [];

        for (let i = 0; i < ENDPOINTS.length; i++) {
            const ep = ENDPOINTS[i];
            setStatus(`Fetching ${ep.label} (${i + 1}/${ENDPOINTS.length})…`, "working", { state: "RUNNING" });
            try {
                raw[ep.key] = await fetchEndpoint(state, nativeFetch, ep, ctx, authSnapshot, warnings);
            } catch (error) {
                failed.push({ endpoint: ep.path, section: ep.label, error: error.message });
                if (error.authFailed) break; // remaining calls would fail the same way
            }
            const shownNow = portalLabel ? selectedDependentLabel() : null;
            const switched = portalLabel
                ? Boolean(shownNow && shownNow !== portalLabel)
                : (state.ctx.enrolleeId != null && String(state.ctx.enrolleeId) !== String(ctx.enrolleeId));
            if (switched) {
                throw new Error("Patient changed in the portal during the crawl. Wait for the page to settle and run Crawl again.");
            }
        }

        if (failed.length && failed.some(f => /token|401|403|unauthor/i.test(f.error)) && Object.keys(raw).length === 0) {
            throw new Error(failed[0].error);
        }
        if (Object.keys(raw).length === 0) {
            throw new Error(`All DD MO requests failed: ${failed.map(f => f.error).join("; ")}`);
        }
        // Anything not fetched (e.g. after an auth failure) is reported as failed as well.
        for (const ep of ENDPOINTS) {
            if (!(ep.key in raw) && !failed.some(f => f.endpoint === ep.path)) {
                failed.push({ endpoint: ep.path, section: ep.label, error: "Skipped after an earlier authentication failure." });
            }
        }

        if (portalLabel && Array.isArray(raw.general)) {
            const row = raw.general.find(r => String(r.enrolleeId) === String(ctx.enrolleeId));
            const returned = row ? `${row.firstName || ""} ${row.lastName || ""}`.trim() : "";
            if (!row || !sameName(portalLabel, returned)) {
                throw new Error("The member returned by the portal does not match the dependent selected on screen. Nothing was saved. Select the dependent again and retry.");
            }
        }

        await ensureSubscriberKnown(state, nativeFetch, ctx, raw.general, warnings);

        const data = buildFinalOutput(state, ctx, raw, failed, warnings, run);
        run.resultData = data;
        postPageMessage("RESULT", { requestId, data });
        setTimeout(() => { if (state.activeRun === run) state.activeRun = null; }, 20000);
        // Release immediately once the isolated world acknowledges (polled cheaply).
        const poll = setInterval(() => {
            if (state.activeRun !== run || run.acknowledged) { clearInterval(poll); if (state.activeRun === run) state.activeRun = null; }
        }, 250);
        setTimeout(() => clearInterval(poll), 21000);
    }

    // A dependent's summary does not name the subscriber, and the sheet's Subscriber Name is the family
    // member the portal lists as Self. Replay summary-general for the other members of this subscriber
    // the page already used this session until the Self row is found, so family_members carries it.
    async function ensureSubscriberKnown(state, nativeFetch, ctx, generalRows, warnings) {
        const selected = selectedGeneralRow(Array.isArray(generalRows) ? generalRows : [], ctx.enrolleeId);
        if (!selected || /^self$/i.test(String(selected.relationshipDescription || "").trim())) return;
        const subscriberId = String(selected.subscriberId ?? ctx.subscriberId ?? "");
        if (!subscriberId) return;
        const isSelf = m => /^self$/i.test(String(m.relationship || "").trim()) && String(m.subscriberId ?? "") === subscriberId;
        const hasSelf = () => [...state.directory.values()].some(isSelf);
        if (hasSelf()) return;

        const candidates = [];
        const seen = new Set([String(ctx.enrolleeId)]);
        const add = (enrolleeId, productId, memberSubscriberId) => {
            if (enrolleeId == null || seen.has(String(enrolleeId))) return;
            if (memberSubscriberId != null && String(memberSubscriberId) !== subscriberId) return;
            const known = state.directory.get(String(enrolleeId));
            if (known?.relationship && !isSelf(known)) return; // already known to be another dependent
            seen.add(String(enrolleeId));
            candidates.push({ enrolleeId, productId: productId ?? ctx.productId });
        };
        [...state.bodies].reverse().forEach(b => add(b.body.enrolleeId, b.body.productId, b.body.subscriberId));
        [...state.directory.values()].reverse().forEach(m => add(m.enrolleeId, m.productId, m.subscriberId));
        if (!candidates.length) {
            warnings.push("Subscriber (Self) not seen in this session; open the subscriber once before crawling a dependent to capture the subscriber name.");
            return;
        }

        setStatus("Looking up the subscriber…", "working", { state: "RUNNING" });
        const url = `${state.benefitsBase}summary-general`;
        for (const c of candidates.slice(0, 6)) {
            try {
                const resp = await postJson(state, nativeFetch, url, { enrolleeId: c.enrolleeId, productId: c.productId, subscriberId }, () => state.auth);
                harvestMembers(state, resp);
            } catch (error) {
                warnings.push(`Subscriber lookup ${c.enrolleeId}: ${error.message}`);
                if (error.authFailed) return;
            }
            if (hasSelf()) return;
        }
        warnings.push("Subscriber (Self) not found among the members seen in this session.");
    }

    async function fetchEndpoint(state, nativeFetch, ep, ctx, getAuth, warnings) {
        const url = `${state.benefitsBase}${ep.path}`;
        const base = { ...(ctx.extra || {}), enrolleeId: ctx.enrolleeId, productId: ctx.productId };
        if (ep.key !== "history") base.subscriberId = ctx.subscriberId;

        if (ep.key === "general" || ep.key === "maxDeductible") {
            return postJson(state, nativeFetch, url, base, getAuth);
        }

        // Paged endpoints: coverage (portal sends pageNumber/pageSize) and history (portal sends only ids).
        const isCoverage = ep.key === "coverage";
        const pageSize = isCoverage ? COVERAGE_PAGE_SIZE : HISTORY_PAGE_SIZE;
        const first = await postJson(state, nativeFetch, url, isCoverage ? { ...base, pageNumber: 1, pageSize } : base, getAuth);
        const rows = Array.isArray(first?.results) ? [...first.results] : [];
        const totalPages = Number(first?.totalPages || 1);
        const totalRecords = Number(first?.totalRecords ?? rows.length);
        const seen = new Set(rows.map(r => String(r.rowCount)));

        for (let page = 2; page <= Math.min(totalPages, MAX_PAGES); page++) {
            setStatus(`Fetching ${ep.label} — page ${page}/${totalPages}…`, "working", { state: "RUNNING" });
            const next = await postJson(state, nativeFetch, url, { ...base, pageNumber: page, pageSize }, getAuth);
            let added = 0;
            for (const row of next?.results || []) {
                const id = String(row.rowCount);
                if (seen.has(id)) continue;
                seen.add(id);
                rows.push(row);
                added++;
            }
            if (!added) { warnings.push(`${ep.path}: page ${page} returned no new rows; stopped paging.`); break; }
        }
        if (rows.length !== totalRecords) warnings.push(`${ep.path}: expected ${totalRecords} rows but received ${rows.length}.`);
        if (!Array.isArray(first?.results)) warnings.push(`${ep.path}: response had no "results" array.`);
        return { totalRecords, totalPages, rows };
    }

    async function postJson(state, nativeFetch, url, body, getAuth, attempt = 0) {
        let response;
        try {
            response = await nativeFetch(url, {
                method: "POST",
                headers: {
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "Authorization": getAuth(),
                    "x-caller-service": state.callerService
                },
                body: JSON.stringify(body)
            });
        } catch (error) {
            if (attempt < 2) { await sleep(600 * (attempt + 1)); return postJson(state, nativeFetch, url, body, getAuth, attempt + 1); }
            throw new Error(`Network error: ${error.message}`);
        }

        if (response.status === 401 || response.status === 403) {
            const error = new Error(`Portal rejected the login token (HTTP ${response.status}). Reload the Member Benefits page to refresh it, then retry.`);
            error.authFailed = true;
            throw error;
        }
        if (response.status >= 500 && attempt < 2) {
            await sleep(800 * (attempt + 1));
            return postJson(state, nativeFetch, url, body, getAuth, attempt + 1);
        }
        if (!response.ok) throw new Error(`HTTP ${response.status} from ${url.split("/").pop()}`);
        try { return await response.json(); } catch (_) { throw new Error(`Invalid JSON from ${url.split("/").pop()}`); }
    }

    // ---- output ---------------------------------------------------------

    function buildFinalOutput(state, ctx, raw, failed, warnings, run) {
        const generalRows = Array.isArray(raw.general) ? raw.general : [];
        const selected = selectedGeneralRow(generalRows, ctx.enrolleeId);
        const coverageRows = raw.coverage?.rows || [];
        const historyRows = raw.history?.rows || [];

        // Keep only the required codes (PROCEDURE_CODES). The count below reflects the actual
        // portal coverage rows, while coverage_levels includes all required codes.
        const coverage = coverageRows.map(normalizeCoverageRow).filter(r => PROCEDURE_CODE_SET.has(r.code));
        const history = historyRows.map(normalizeHistoryRow);
        const maximumAndDeductible = Array.isArray(raw.maxDeductible)
            ? buildCleanMaximumAndDeductible(raw.maxDeductible.map(normalizeAccumulatorRow))
            : null;

        return {
            source: "Delta Dental of Missouri Provider Portal",
            carrier: CARRIER,
            extracted_at: new Date().toISOString(),
            coverage_rows: coverage.length,
            member_details: buildMemberDetails(selected, generalRows, ctx, state),
            maximum_and_deductible: maximumAndDeductible,
            coverage_levels: buildRequiredCoverageLevels(coverage),
            patient_history: history
        };
    }

    function buildMemberDetails(row, allRows, ctx, state) {
        if (!row) {
            return {
                patient_name: null,
                enrollee_id: ctx.enrolleeId,
                product_id: ctx.productId,
                subscriber_id: ctx.subscriberId,
                family_members: buildFamilyMembers(state, allRows, ctx)
            };
        }
        const name = buildPatientName(row);
        return {
            patient_name: name,
            relationship: row.relationshipDescription ?? null,
            dob: row.dob ?? null,
            age: row.enrolleeAge ?? null,
            eligible: row.eligible ?? null,
            effective_date: displayApiDate(row.effectiveDate),
            termination_date: displayApiDate(row.terminationDate),
            enrollee_id: row.enrolleeId ?? ctx.enrolleeId,
            subscriber_id: row.subscriberId ?? ctx.subscriberId,
            product_id: row.productId ?? ctx.productId,
            address: formatAddress(row),
            insurer: row.insurerName ?? null,
            group_name: row.groupName ?? null,
            group_number: row.groupNumber ?? null,
            group_effective_date: displayApiDate(row.groupEffectiveDate),
            plan_name: row.planName ?? null,
            program_type: row.programType ?? null,
            benefit_cycle: row.benefitCycle ?? null,
            cob_type: row.COBType ?? null,
            waiting_period: trimOrNull(row.waitingPeriod),
            has_ortho: trimOrNull(row.hasOrtho),
            ortho_age: row.orthoAge ?? null,
            ortho_pay_cycle: row.orthoPayCycle ?? null,
            ortho_treatment_rule: trimOrNull(row.orthoTreatmentRule),
            existing_tooth_clause: trimOrNull(row.existingToothClause),
            is_max_advantage: trimOrNull(row.isMaxAdvantage),
            max_advantage_description: row.maxAdvDescription ?? null,
            is_hshl: trimOrNull(row.isHSHL),
            hshl_description: row.HSHLDescription ?? null,
            dependent_age_cutoff: row.dependentAgeCutOff ?? null,
            dependent_age_covered: row.dependentAgeCovered ?? null,
            full_time_student_covered: row.fullTimeStudentCovered ?? null,
            qualify_children_covered: row.qualifyChildrenCovered ?? null,
            visit_copay: row.visitCopay ?? null,
            escalating_benefit_message: row.escalatingBenefitMsg ?? null,
            group_notes: row.groupNotes ?? null,
            handicap_flag: row.handicapFlag ?? null,
            plan_year_start: row.planYearStart ?? null,
            waiting_period_credit: row.waitingPeriodCredit ?? null,
            family_members: buildFamilyMembers(state, allRows, ctx)
        };
    }

    function buildPatientName(row) {
        return [row?.firstName, row?.middleName, row?.lastName].filter(Boolean).join(" ").trim() || null;
    }

    function buildFamilyMembers(state, allRows, ctx) {
        const members = new Map();
        const selectedId = String(ctx.enrolleeId);
        const subscriberId = ctx.subscriberId == null ? null : String(ctx.subscriberId);
        const productId = ctx.productId == null ? null : String(ctx.productId);

        const add = (member) => {
            if (!member || member.enrolleeId == null) return;
            const id = String(member.enrolleeId);
            const memberSubscriberId = member.subscriberId == null ? null : String(member.subscriberId);
            const memberProductId = member.productId == null ? null : String(member.productId);
            const sameSubscriber = !subscriberId || !memberSubscriberId || subscriberId === memberSubscriberId;
            const sameProduct = !productId || !memberProductId || productId === memberProductId;
            if (!sameSubscriber || !sameProduct) return;

            const previous = members.get(id) || {};
            members.set(id, {
                ...previous,
                enrolleeId: member.enrolleeId,
                subscriberId: memberSubscriberId ?? previous.subscriberId ?? null,
                productId: memberProductId ?? previous.productId ?? null,
                patientName: member.patientName || previous.patientName || null,
                relationship: member.relationship ?? previous.relationship ?? null,
                eligible: member.eligible ?? previous.eligible ?? null
            });
        };

        for (const r of allRows || []) {
            add({
                enrolleeId: r.enrolleeId,
                subscriberId: r.subscriberId ?? ctx.subscriberId,
                productId: r.productId ?? ctx.productId,
                patientName: buildPatientName(r),
                relationship: r.relationshipDescription ?? null,
                eligible: r.eligible ?? null
            });
        }
        for (const member of state?.directory?.values?.() || []) add(member);

        // Keep the selected member in the output even if the directory only has partial metadata.
        if (!members.has(selectedId) && ctx.enrolleeId != null) {
            const selectedRow = (allRows || []).find(r => String(r.enrolleeId) === selectedId);
            add({
                enrolleeId: ctx.enrolleeId,
                subscriberId: ctx.subscriberId,
                productId: ctx.productId,
                patientName: selectedRow ? buildPatientName(selectedRow) : null,
                relationship: selectedRow?.relationshipDescription ?? null,
                eligible: selectedRow?.eligible ?? null
            });
        }

        const result = [...members.values()]
            .filter(m => m.patientName)
            .map(m => ({
                enrollee_id: m.enrolleeId,
                patient_name: m.patientName,
                relationship: m.relationship,
                eligible: m.eligible,
                selected: String(m.enrolleeId) === selectedId
            }));

        // Match the portal's family presentation: subscriber first, then dependents.
        result.sort((a, b) => {
            const aSelf = /^self$/i.test(String(a.relationship || ""));
            const bSelf = /^self$/i.test(String(b.relationship || ""));
            return Number(bSelf) - Number(aSelf);
        });
        return result;
    }

    function normalizeCoverageRow(r) {
        return {
            code: normalizeCode(r.procedureCode),
            benefit_group: r.benefitGroup ?? null,
            description: r.procedureDescr ?? null,
            ppo_pct: pct(r.benefitLevelPPO),
            ppo_deductible_applies: r.deductibleAppliesPPO ?? null,
            premier_pct: pct(r.benefitLevelPremier),
            premier_deductible_applies: r.deductibleAppliesPremier ?? null,
            oon_pct: pct(r.benefitLevelOON),
            oon_deductible_applies: r.deductibleAppliesOON ?? null,
            last_service_dates: r.lastServiceDates ?? null,
            waiting_period: r.waitingPeriod ?? null,
            frequency: emptyToNull(r.frequency),
            age_limit: emptyToNull(r.ageLimit),
            other_limitations: emptyToNull(r.otherBenefitLimitions),
            max_advantage: emptyToNull(r.maxAdvantage)
        };
    }

    // Return all required codes in the requested order. Codes not present in the
    // portal coverage table are represented without fabricated benefit details.
    function buildRequiredCoverageLevels(coverage) {
        const byCode = new Map();
        for (const row of coverage) if (!byCode.has(row.code)) byCode.set(row.code, row);
        return PROCEDURE_CODES.map(code => {
            const row = byCode.get(code);
            return row
                ? { code: row.code, listed: true, ...Object.fromEntries(Object.entries(row).filter(([key]) => key !== "code")) }
                : { code, listed: false };
        });
    }

    function normalizeAccumulatorRow(r) {
        const net = (max, met, rem, note) => ({
            max: max ?? null,
            met: met ?? 0,
            remaining: rem ?? null,
            note: note ?? null
        });
        return {
            plan_type: r.planType ?? null,
            sub_type: r.planSubType ?? null,
            period: r.category ?? null,
            category: r.categoryType ?? null,
            ppo: net(r.ppoMax, r.ppoMet, r.ppoRem, r.ppoOverRideText),
            premier: net(r.premierMax, r.premierMet, r.premierRem, r.premierOverRideText),
            out_of_network: net(r.outOfNetworkMax, r.outOfNetworkMet, r.outOfNetworkRem, r.outOfNetworkOverRideText),
            max_rollover: r.isMaxRollover ?? null,
            period_benefit_level: r.PeriodBenefitLevelDescription ?? null,
            age_min: r.ageMin ?? null,
            age_max: r.ageMax ?? null
        };
    }

    // Public JSON uses only the values shown in the member-benefits PDF, plus the amounts and the
    // family/ortho deductibles the client sheets ask for (PPO network values, like the rest).
    // Internal API dimensions (network, max code, rollover flags, etc.) are not emitted.
    function buildCleanMaximumAndDeductible(rows) {
        const find = (planType, subType, category, period) => rows.find(r =>
            r.plan_type === planType &&
            r.sub_type === subType &&
            r.category === category &&
            (period == null || r.period === period)
        ) || null;

        const regularDeductible = find("Individual", "Deductible", "Regular", "Annual");
        const regularMaximum = find("Individual", "Maximum", "Regular", "Annual");
        const orthoLifetimeMaximum = find("Individual", "Maximum", "Orthodontic", "Lifetime");
        const familyRegularDeductible = find("Family", "Deductible", "Regular", "Annual");
        const orthoDeductible = find("Individual", "Deductible", "Orthodontic", null);

        const readMet = row => Number.isFinite(Number(row?.ppo?.met)) ? Number(row.ppo.met) : 0;
        const readRemaining = row => Number.isFinite(Number(row?.ppo?.remaining)) ? Number(row.ppo.remaining) : null;
        const unlimited = value => value != null && value >= 99999 ? "Unlimited" : value;
        // "SHARED" rows carry 0 placeholders; the portal shows the text instead of amounts.
        const isShared = row => /^shared$/i.test(String(row?.ppo?.note ?? "").trim());
        const readAmount = row => {
            if (!row) return null;
            if (isShared(row)) return "SHARED";
            return row.ppo?.max != null && Number.isFinite(Number(row.ppo.max)) ? Number(row.ppo.max) : null;
        };
        // Null throughout when the portal returned no such accumulator for this member.
        const optionalDeductible = row => !row || isShared(row)
            ? { amount: readAmount(row), met: null, remaining: null }
            : { amount: readAmount(row), met: readMet(row), remaining: readRemaining(row) };

        return {
            individual_regular_deductible: {
                amount: readAmount(regularDeductible),
                met: readMet(regularDeductible),
                remaining: readRemaining(regularDeductible)
            },
            individual_regular_annual_maximum: {
                amount: unlimited(readAmount(regularMaximum)),
                used: readMet(regularMaximum),
                remaining: unlimited(readRemaining(regularMaximum))
            },
            individual_orthodontic_lifetime_maximum: {
                amount: readAmount(orthoLifetimeMaximum),
                used: readMet(orthoLifetimeMaximum),
                remaining: readRemaining(orthoLifetimeMaximum)
            },
            family_regular_deductible: optionalDeductible(familyRegularDeductible),
            individual_orthodontic_deductible: optionalDeductible(orthoDeductible)
        };
    }

    function normalizeHistoryRow(r) {
        return {
            date_of_service: displayApiDate(r.dateOfService),
            date_of_service_iso: isoDateOnly(r.dateOfService),
            provider: r.provider ?? null,
            tooth: r.Tooth === "00" ? "" : (r.Tooth ?? ""),
            surface: r.Surface ?? "",
            code: normalizeCode(r.cdtCode),
            description: r.cdtCodeDescription ?? null
        };
    }

    // ---- helpers ----------------------------------------------------------

    function selectedGeneralRow(rows, enrolleeId) {
        if (!Array.isArray(rows) || !rows.length) return null;
        return rows.find(r => String(r.enrolleeId) === String(enrolleeId)) || rows[0];
    }

    function normalizeCode(value) {
        const text = String(value ?? "").trim().toUpperCase();
        return /^\d{4}$/.test(text) ? `D${text}` : text;
    }

    function pct(value) {
        const n = Number(value);
        return Number.isFinite(n) ? Math.round(n * 1000) / 10 : null;
    }

    function emptyToNull(value) {
        const text = value == null ? "" : String(value).trim();
        return text ? text : null;
    }

    function trimOrNull(value) {
        return emptyToNull(value);
    }

    function isoDateOnly(value) {
        const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ""));
        return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
    }

    function displayApiDate(value) {
        const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ""));
        return m ? `${m[2]}/${m[3]}/${m[1]}` : null; // no timezone conversion: the API sends date-only values as midnight Z
    }

    function formatAddress(row) {
        const line = [row.address1, row.address2].filter(Boolean).join(" ");
        const zip = [row.zip, row.zip4].filter(Boolean).join("-");
        const tail = [row.city, [row.state, zip].filter(Boolean).join(" ")].filter(Boolean).join(", ");
        return [line, tail].filter(Boolean).join(", ") || null;
    }

    function headersToObject(input) {
        const out = {};
        if (!input) return out;
        try {
            if (typeof Headers !== "undefined" && input instanceof Headers) input.forEach((v, k) => { out[k.toLowerCase()] = v; });
            else if (Array.isArray(input)) input.forEach(([k, v]) => { out[String(k).toLowerCase()] = String(v); });
            else Object.entries(input).forEach(([k, v]) => { out[k.toLowerCase()] = String(v); });
        } catch (_) { /* ignore */ }
        return out;
    }

    function parseJson(text) {
        try { return JSON.parse(text); } catch (_) { return null; }
    }

    function postPageMessage(type, payload) {
        window.postMessage({ source: PAGE_SOURCE, type, ...payload }, window.location.origin);
    }

    function setStatus(text, mode, extra = {}) {
        postPageMessage("STATUS", { status: text, mode, extra });
        console.info(`DD MO: ${text}`);
    }

    function makeId() {
        return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function downloadJson(data) {
        if (!data || typeof data !== "object") throw new Error("Cannot download an empty extraction result.");
        const patient = String(data?.member_details?.patient_name || "patient").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "patient";
        const date = new Date().toISOString().slice(0, 10);
        const filename = `delta_mo_${patient}_${date}.json`;
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        anchor.style.display = "none";
        (document.body || document.documentElement).appendChild(anchor);
        anchor.click();
        setTimeout(() => { anchor.remove(); URL.revokeObjectURL(url); }, 1500);
    }
})();
