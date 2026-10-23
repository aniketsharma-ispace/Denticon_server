/*
 * content_dd_toolkit.js
 * Delta Dental Office Toolkit benefit extractor - PDF-integrated PPO revision
 *
 * No background/service worker is used.
 *
 * IMPORTANT — load this SAME file in both Chrome content-script worlds:
 *
 * "content_scripts": [
 *   {
 *     "matches": ["https://www.dentalofficetoolkit.com/*"],
 *     "js": ["content_dd_toolkit.js"],
 *     "run_at": "document_start",
 *     "world": "MAIN"
 *   },
 *   {
 *     "matches": ["https://www.dentalofficetoolkit.com/*"],
 *     "js": ["content_dd_toolkit.js"],
 *     "run_at": "document_start",
 *     "world": "ISOLATED"
 *   }
 * ]
 *
 * The MAIN-world copy captures the portal's authenticated API request and
 * performs the extraction. The ISOLATED-world copy keeps popup messaging and
 * chrome.storage.local working. Both copies are this one file.
 *
 * Client-independent export (one JSON for every client in the workbook):
 *   - Requests the generated global workbook code universe and captures portal/PDF evidence internally.
 *   - Downloads the legacy section-based schema consumed by downstream comparator code.
 *   - Preserves member_details, benefits, website maximums/deductibles, more_information
 *     and crawl_statistics without duplicate patient_and_plan/plan_provisions blocks.
 *   - The exported JSON has no faxback_pdf section; procedure_code_search has no endpoint/count/
 *     successful_count, lists codes_requested/failed_codes as single comma-separated lines, and its
 *     result rows carry no httpStatus/result_source/lookup_status or procedurePath level.
 *   - The richer internal result remains available to the existing extension storage integration.
 *
 * Usage:
 *   1. Open the member-benefits page.
 *   2. Wait for the member-benefits page and its authenticated API calls to finish loading.
 *      The script builds the procedure request automatically; no manual code lookup is required.
 *   3. Click Crawl in the extension popup. Keep the Toolkit tab open until download completes.
 */

(() => {
    "use strict";

    const EXT_SOURCE = "delta-toolkit-extension";
    const PAGE_SOURCE = "delta-toolkit-page";
    const RESULT_STORAGE_KEY = "delta_toolkit_data";
    const TARGET_ORIGIN = "https://www.dentalofficetoolkit.com";
    // Distinct endpoints observed in Toolkit traffic. Do not alias member-benefits to member-details.
    const MEMBER_SEARCH_PATH = "/api/dot-gateway/v02/memberdetail/search";
    const MEMBER_BENEFITS_PATH = "/api/dot-gateway/v1/benefit/memberbenefits/search";
    const ROUTINE_PROCEDURES_PATH = "/api/dot-gateway/v1/benefit/memberbenefits/routineprocedures/search";
    const CLIENT_SEARCH_PATH = "/api/dot-gateway/v1/benefit/client/search";
    const PROCEDURE_SEARCH_PATH = "/api/dot-gateway/v1/benefit/memberbenefits/procedures/search";
    const PROCEDURE_SEARCH_URL = `${TARGET_ORIGIN}${PROCEDURE_SEARCH_PATH}?type=codes`;
    // "Please click HERE to access a PDF copy of this member's faxback document".
    // The captured PDF is parsed into the exported benefit model; the binary document,
    // request metadata, endpoints, headers, hashes, and API transaction details are never exported.
    // The link POSTs here; the response body is the PDF itself (labelled application/json).
    const DOCUMENT_PATH = "/api/dot-gateway/v1/documents/memberbenefits/search";
    const PDF_CACHE_TTL_MS = 15 * 60 * 1000;   // reuse a captured PDF for the same member for 15 min
    const PDF_WAIT_MS = 12000;                  // hard timeout; successful PDF responses normally arrive much sooner
    const PDF_SETTLE_MS = 250;                  // short settle; the PDF response itself is the synchronization point
    const PROCEDURE_CONCURRENCY = 6;              // 3 was unnecessarily serial for this endpoint; 6 matches observed latency well
    const PROCEDURE_THROTTLE_MS = 25;              // tiny cooperative delay; avoid adding ~0.2s per request
    const RESULT_ACK_TIMEOUT_MS = 1500;            // fallback only if the isolated bridge genuinely fails

    // The source workbook is converted to a bundled, versioned specification at build time.
    // Never assume the browser extension can read an arbitrary workbook from the development machine.
    const TOOLKIT_REQUIREMENTS_SPEC = globalThis.__DELTA_TOOLKIT_REQUIREMENTS_SPEC__ || null;
    const SUPPLEMENTAL_PROCEDURE_CODES = Object.freeze(["D0431", "D2962", "D5213"]);
    const MANDATORY_PROCEDURE_CODES = Object.freeze(
        Array.isArray(TOOLKIT_REQUIREMENTS_SPEC?.code_universe?.mandatory_codes)
            ? [...new Set(TOOLKIT_REQUIREMENTS_SPEC.code_universe.mandatory_codes.map(code => String(code).toUpperCase()))].sort()
            : []
    );
    if (MANDATORY_PROCEDURE_CODES.length !== 236) {
        console.error("Delta Toolkit requirements configuration missing/invalid; expected 236 mandatory codes.");
    }
    const PROCEDURE_CODES = Object.freeze([...new Set([
        ...MANDATORY_PROCEDURE_CODES,
        ...SUPPLEMENTAL_PROCEDURE_CODES
    ])].sort());
    const LEGACY_CATEGORY_CODES = Object.freeze({
        EXAMS: ["D0180", "D0120", "D0140", "D0150"],
        DIAGNOSTIC: ["D0210", "D0220", "D0230", "D0240", "D0272", "D0274", "D0330", "D0364", "D0367", "D0431"],
        PREVENTATIVE: ["D1510", "D1516", "D1110", "D1120", "D1206", "D1208", "D1351"],
        "BASIC RESTORATIVE": ["D2140", "D2160", "D2331", "D2391", "D2620"],
        "MAJOR RESTORATIVE": ["D2610", "D2642", "D2740", "D2750", "D2950", "D2962", "D2980", "D2991"],
        ENDODONTICS: ["D3221", "D3347", "D3310", "D3330", "D3346", "D3348"],
        PERIODONTICS: ["D4249", "D4260", "D4341", "D4346", "D4355", "D4381", "D4910", "D4921"],
        "REMOVABLE PROSTHO": ["D5860", "D5110", "D5212", "D5213", "D5511", "D5650", "D5740", "D5810", "D5821", "D5912", "D5982", "D5899", "D5995"],
        IMPLANT: ["D6194", "D6010", "D6056", "D6057", "D6058", "D6065", "D6104", "D6190"],
        "FIXED PROSTHO": ["D6240", "D6245", "D6750"],
        "ORAL SURGERY": ["D7259", "D7140", "D7210", "D7230", "D7240", "D7310", "D7953"],
        ORTHODONTICS: ["D8010", "D8080", "D8090", "D8220", "D8680"],
        ADJUNCTIVE: ["D9430", "D9110", "D9222", "D9223", "D9230", "D9239", "D9243", "D9310", "D9612", "D9630", "D9944", "D9946", "D9947"]
    });
    const CATEGORY_CODES = Object.freeze({
        ...LEGACY_CATEGORY_CODES,
        OTHER_WORKBOOK_REQUIRED: MANDATORY_PROCEDURE_CODES.filter(code =>
            !Object.values(LEGACY_CATEGORY_CODES).some(codes => codes.includes(code))
        ),
        SUPPLEMENTAL: SUPPLEMENTAL_PROCEDURE_CODES
    });
    const CATEGORY_BY_CODE = Object.freeze(Object.fromEntries(
        Object.entries(CATEGORY_CODES).flatMap(([category, codes]) => codes.map(code => [code, category]))
    ));

    const PROCEDURE_LABELS = Object.freeze({
        D0180: "Perio Consult",
        D0120: "Periodic Exam",
        D0140: "Limited Exam",
        D0150: "Comprehensive Exam",
        D0210: "Full Mouth Xray",
        D0220: "PA",
        D0230: "PA Addtn",
        D0240: "Intraoral - Occlusal Image",
        D0272: "Bitewings",
        D0274: "Bitewings",
        D0330: "Panoramic Xray",
        D0364: "CBCT - Limited Field of View",
        D0367: "CBCT - Both Jaws",
        D0351: "3D Photographic Image",
        D0431: "Oral Cancer Screening (adjunctive test)",
        D1510: "Space Maintainer",
        D1516: "Space Maintainer - Fixed Bilateral Maxillary",
        D1110: "Prophylaxis",
        D1120: "Prophylaxis Child",
        D1206: "Fluoride Varnish",
        D1208: "Fluoride",
        D1351: "Sealants",
        D1352: "Preventive Resin Restoration",
        D2140: "Amalgam",
        D2160: "Amalgam",
        D2331: "Composite Filling",
        D2391: "Composite Filling - Posterior",
        D2610: "Inlay - Porcelain/Ceramic - One Surface",
        D2620: "Restorative Onlay/Inlay",
        D2642: "Onlay - Porcelain/Ceramic - Two Surfaces",
        D2740: "Porcelain Crown",
        D2750: "Restorative Crown",
        D2950: "Build up",
        D2962: "Porcelain Laminate Veneer",
        D2980: "Crown Repair",
        D2991: "D2991",
        D3221: "Pulpal Debridement - Primary and Permanent",
        D3346: "Retreatment of Previous Root Canal - Anterior",
        D3347: "Retreatment of previous root canal therapy - premolar",
        D3348: "Retreatment of Previous Root Canal - Molar",
        D3310: "Endo",
        D3330: "Root Canal",
        D4249: "Crown Lengthening",
        D4260: "Osseous Surgery",
        D4341: "Scaling & Root Planning",
        D4346: "Scaling in Gingival Inflammation",
        D4355: "Full Mouth Debridement",
        D4381: "Arestin",
        D4320: "Provisional Splinting - Intracoronal",
        D4321: "Provisional Splinting - Extracoronal",
        D4910: "Perio Maintenance",
        D4921: "Gingival Irrigation - Per Quadrant",
        D5860: "Over Denture Complete",
        D5110: "Dentures",
        D5212: "Mandibular Partial Denture - Resin Base",
        D5213: "Maxillary Partial Denture",
        D5510: "Repair Broken Complete Denture Base (retired code)",
        D5511: "Repair Broken Complete Denture Base",
        D5650: "Add Tooth to Existing Partial Denture",
        D5740: "Reline maxillary partial denture (direct)",
        D5810: "Interim Complete Denture",
        D5821: "Interim Partial Denture",
        D5912: "Facial Moulage (Complete)",
        D5899: "Prosth Removable",
        D5982: "Surgical stent",
        D5995: "Periodontal Medicament Carrier",
        D6194: "Implant",
        D6010: "Implant Body",
        D6056: "Implant Abutment",
        D6057: "D6057",
        D6058: "D6058",
        D6065: "Implant Crown",
        D6104: "Bone Graft at Time of Implant Placement",
        D6190: "Radiographic/Surgical Implant Index",
        D6240: "Pontic - Porcelain Fused to High Noble",
        D6245: "Pontic - porcelain/ceramic",
        D6750: "Retainer Crown - PFM High Noble",
        D7259: "Nerve dissection",
        D7140: "Simple Extraction",
        D7210: "Surgical Extraction",
        D7230: "Partially Bony Impacted Extraction",
        D7240: "Impacted Extraction",
        D7310: "Alveoloplasty",
        D7953: "Ridge Preservation Bone Graft",
        D7960: "Frenulectomy (retired code)",
        D8010: "Ortho",
        D8080: "Ortho",
        D8090: "Ortho",
        D8050: "Interceptive Orthodontic Treatment - Primary Dentition",
        D8060: "Interceptive Orthodontic Treatment - Transitional Dentition",
        D8220: "Fixed Appliance Therapy",
        D8680: "Orthodontic Retention",
        D9430: "Office visit for observation",
        D9110: "Palliative",
        D9222: "Gen Anesthesia",
        D9223: "Anesthesia",
        D9230: "Nitrous Oxide",
        D9239: "sedation/analgesia",
        D9243: "IV Sedation - Additional 15 min",
        D9310: "Consult",
        D9612: "Therapeutic Parenteral Drugs - Two or More Administrations",
        D9630: "Adjunct - Other Drugs/Medicaments",
        D9944: "Occlusal Guard",
        D9946: "Occlusal Guard - Hard Appliance",
        D9947: "Custom Sleep Apnea Appliance"
    });

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
        if (globalThis.__DELTA_TOOLKIT_ISOLATED_INSTALLED__) return;
        globalThis.__DELTA_TOOLKIT_ISOLATED_INSTALLED__ = true;
        console.info("Delta Toolkit popup bridge 1.35.28 installed.");

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
                    wait.sendResponse({
                        status: message.status || "[+] Delta Toolkit crawl started.",
                        started: true,
                        requestId: message.requestId
                    });
                }
                sendPopupStatus(message.status || "Delta Toolkit crawl started.", "working");
                return;
            }

            if (message.type === "TOOLKIT_STATUS") {
                const wait = pendingStatus.get(message.requestId);
                if (wait) {
                    clearTimeout(wait.timer);
                    pendingStatus.delete(message.requestId);
                    wait.sendResponse(message.payload || { ready: false, message: "Toolkit status unavailable." });
                }
                return;
            }

            if (message.type === "RESULT") {
                persistAndDownload(message.data).then(() => {
                    // Acknowledge only after storage and the download trigger succeed.
                    window.postMessage({
                        source: EXT_SOURCE,
                        type: "RESULT_ACK",
                        requestId: message.requestId
                    }, window.location.origin);

                    const stats = message.data?.crawl_statistics || {};
                    const successful = Number(stats.successful_codes || 0);
                    const requested = Number(stats.requested_codes || message.data?.procedures?.count || 0);
                    const failed = Array.isArray(stats.failed_codes) ? stats.failed_codes.length : Math.max(0, requested - successful);
                    const unavailable = Array.isArray(stats.unavailable_codes) ? stats.unavailable_codes.length : 0;
                    const notAttempted = Array.isArray(stats.not_attempted_codes) ? stats.not_attempted_codes.length : 0;
                    const incomplete = failed + unavailable + notAttempted;
                    const parts = [];
                    if (failed) parts.push(`${failed} failed`);
                    if (unavailable) parts.push(`${unavailable} unavailable`);
                    if (notAttempted) parts.push(`${notAttempted} not attempted`);
                    const finalText = incomplete
                        ? `[!] Partial — ${successful}/${requested} API code lookups succeeded; ${parts.join(', ')}. JSON downloaded.`
                        : `[+] Done — ${successful}/${requested} API code lookups succeeded. JSON downloaded.`;
                    sendPopupStatus(finalText, incomplete ? "warning" : "ready", { state: incomplete ? "PARTIAL" : "COMPLETE" });
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
                    wait.sendResponse({
                        status: `[!] ${message.error || "Delta Toolkit extraction failed."}`,
                        started: false
                    });
                }
                sendPopupStatus(`[!] ${message.error || "Delta Toolkit extraction failed."}`, "error", { state: "FAILED" });
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
                        status: "[!] Delta Toolkit page extractor is unavailable. Refresh the Toolkit tab and ensure content_dd_toolkit.js is loaded in both MAIN and ISOLATED worlds.",
                        started: false
                    });
                }, 4000);

                pendingStarts.set(requestId, { sendResponse, timer });
                window.postMessage({ source: EXT_SOURCE, type: "START_CRAWL", requestId }, window.location.origin);
                return true;
            }

            if (request?.command === "GET_TOOLKIT_STATUS") {
                const requestId = makeId();
                const timer = setTimeout(() => {
                    const wait = pendingStatus.get(requestId);
                    if (!wait) return;
                    pendingStatus.delete(requestId);
                    wait.sendResponse({
                        ready: false,
                        contextReady: false,
                        authReady: false,
                        message: "Toolkit extractor is loading. Refresh the page if this persists."
                    });
                }, 1500);
                pendingStatus.set(requestId, { sendResponse, timer });
                window.postMessage({ source: EXT_SOURCE, type: "GET_STATUS", requestId }, window.location.origin);
                return true;
            }

            return false;
        });

        function sendPopupStatus(status, mode = "working", extra = {}) {
            const payload = {
                carrier: "DELTA_TOOLKIT",
                status: String(status || ""),
                mode,
                state: extra.state || (mode === "error" ? "FAILED" : mode === "ready" ? "COMPLETE" : "RUNNING"),
                updated_at: Date.now(),
                ...extra
            };
            try {
                chrome.storage.local.set({ delta_toolkit_progress: payload }, () => { void chrome.runtime.lastError; });
            } catch (_) { /* storage may be unavailable */ }
            try {
                const maybePromise = chrome.runtime.sendMessage(
                    { command: "STATUS_UPDATE", ...payload },
                    () => { void chrome.runtime.lastError; }
                );
                if (maybePromise?.catch) maybePromise.catch(() => {});
            } catch (_) { /* popup may be closed */ }
        }

        async function persistAndDownload(data) {
            if (!data || typeof data !== "object") {
                throw new Error("No valid extraction result was returned.");
            }

            await new Promise((resolve, reject) => {
                chrome.storage.local.get("audit_context", result => {
                    if (chrome.runtime.lastError) {
                        reject(new Error(chrome.runtime.lastError.message));
                        return;
                    }
                    const context = result.audit_context || {};
                    // Remove only an old mis-keyed Toolkit result; never delete genuine DentaQuest data.
                    if (context.dentaquest_data?.source === "Delta Dental Office Toolkit") {
                        delete context.dentaquest_data;
                    }
                    context[RESULT_STORAGE_KEY] = data;
                    context.delta_toolkit_export = buildWorkbookOnlyOutput(data);
                    context.delta_toolkit_export_filename = toolkitDownloadFilename(data);
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
        if (globalThis.__DELTA_TOOLKIT_MAIN_INSTALLED__) return;
        globalThis.__DELTA_TOOLKIT_MAIN_INSTALLED__ = true;

        const nativeFetch = globalThis.fetch.bind(globalThis);
        const NativeXHR = globalThis.XMLHttpRequest;
        const state = {
            memberSearchRequest: null,
            memberSearchResponse: null,
            memberBenefitsRequest: null,
            memberBenefitsResponse: null,
            routineProceduresRequest: null,
            routineProceduresResponse: null,
            clientSearchRequest: null,
            clientSearchResponse: null,
            personKey: null,
            memberSearchCapturedAt: null,
            procedureTemplate: null,
            procedureTemplateSignature: null,
            procedureHeaders: {},
            procedureResponses: new Map(),
            supportingApiResponses: [],
            coreTransactions: {},
            faxbackPdf: null,
            pdfWaiters: [],
            activeRun: null,
            statusEl: null,
            buttonEl: null,
            hydrated: false,
            selectedClientProfile: null
        };

        hydrateNonSecretState(state);
        interceptFetch(state, nativeFetch);
        interceptXHR(state, NativeXHR);
        installPageMessageBridge(state, nativeFetch);
        // installFloatingUiWhenReady removed to avoid conflicting separate popup

        console.info("Delta Toolkit extractor 1.35.28 legacy-schema JSON installed. Open the member-benefits page and wait for authenticated plan data to finish loading.");
    }

    function interceptFetch(state, nativeFetch) {
        globalThis.fetch = async function deltaToolkitFetch(input, init = {}) {
            let capture = null;
            try {
                capture = await describeFetchRequest(input, init);
            } catch (error) {
                console.debug("Delta Toolkit: unable to inspect fetch request", error);
            }

            const response = await nativeFetch(input, init);
            if (capture && isToolkitApiUrl(capture.url)) {
                inspectFetchResponse(state, capture, response).catch(error => {
                    console.debug("Delta Toolkit: fetch response inspection skipped", error);
                });
            }
            return response;
        };
    }

    async function describeFetchRequest(input, init) {
        const request = input instanceof Request ? input : null;
        const url = request ? request.url : new URL(String(input), location.href).href;
        const method = String(init.method || request?.method || "GET").toUpperCase();
        const headers = mergeHeaders(request?.headers, init.headers);
        let bodyText = null;

        if (typeof init.body === "string") bodyText = init.body;
        else if (init.body instanceof URLSearchParams) bodyText = init.body.toString();
        else if (!init.body && request && !["GET", "HEAD"].includes(method)) {
            try { bodyText = await request.clone().text(); } catch (_) { /* ignored */ }
        }
        return { url, method, headers, bodyText };
    }

    async function inspectFetchResponse(state, request, response) {
        if (isFaxbackDocumentUrl(request.url)) {
            // Binary PDF body: never read it as text/JSON.
            const buffer = await response.clone().arrayBuffer();
            await acceptPdfBytes(state, new Uint8Array(buffer), response.status);
            return;
        }
        const clone = response.clone();
        const contentType = clone.headers.get("content-type") || "";
        if (!contentType.includes("json") && !looksLikeRelevantEndpoint(request.url)) return;
        const text = await clone.text();
        const data = safeJsonParse(text);
        if (data !== null) captureApiTransaction(state, request, data, response.status);
    }

    function interceptXHR(state, NativeXHR) {
        if (!NativeXHR?.prototype) return;
        const originalOpen = NativeXHR.prototype.open;
        const originalSetRequestHeader = NativeXHR.prototype.setRequestHeader;
        const originalSend = NativeXHR.prototype.send;

        NativeXHR.prototype.open = function(method, url, ...rest) {
            this.__deltaCapture = {
                method: String(method || "GET").toUpperCase(),
                url: new URL(String(url), location.href).href,
                headers: {},
                bodyText: null
            };
            return originalOpen.call(this, method, url, ...rest);
        };

        NativeXHR.prototype.setRequestHeader = function(name, value) {
            if (this.__deltaCapture) this.__deltaCapture.headers[String(name).toLowerCase()] = String(value);
            return originalSetRequestHeader.call(this, name, value);
        };

        NativeXHR.prototype.send = function(body) {
            const capture = this.__deltaCapture;
            if (capture) {
                if (typeof body === "string") capture.bodyText = body;
                else if (body instanceof URLSearchParams) capture.bodyText = body.toString();

                if (isFaxbackDocumentUrl(capture.url)) {
                    this.addEventListener("load", () => {
                        readXhrBinary(this)
                            .then(bytes => acceptPdfBytes(state, bytes, this.status))
                            .catch(error => console.debug("Delta Toolkit: faxback PDF capture skipped", error));
                    }, { once: true });
                } else if (isToolkitApiUrl(capture.url)) {
                    this.addEventListener("load", () => {
                        try {
                            let data = null;
                            if (this.responseType === "json") data = this.response;
                            else if (!this.responseType || this.responseType === "text") data = safeJsonParse(this.responseText);
                            if (data !== null) captureApiTransaction(state, capture, data, this.status);
                        } catch (error) {
                            console.debug("Delta Toolkit: XHR response inspection skipped", error);
                        }
                    }, { once: true });
                }
            }
            return originalSend.call(this, body);
        };
    }

    function captureApiTransaction(state, request, responseData, status) {
        const parsedUrl = new URL(request.url, location.href);
        const body = parseRequestBody(request.bodyText);
        const path = parsedUrl.pathname;

        // Any authenticated Toolkit API transaction can refresh replay headers.
        // Authorization remains memory-only and is stripped from persisted/exported data.
        const replayHeaders = safeReplayHeaders(request.headers);
        if (replayHeaders.authorization) {
            state.procedureHeaders = { ...state.procedureHeaders, ...replayHeaders };
        }

        if ([MEMBER_BENEFITS_PATH, ROUTINE_PROCEDURES_PATH, PROCEDURE_SEARCH_PATH].includes(path)) {
            ensurePersonScope(state, body);
        }

        if (path === MEMBER_SEARCH_PATH) {
            rememberCoreTransaction(state, "member_details", request, parsedUrl, body, responseData, status);
            // Member-details search is identity data, not plan/procedure state.
            // Preserve the raw successful response exactly as returned by this dedicated endpoint.
            // It must never be cleared merely because auth refreshed or a plan-context field changed.
            state.memberSearchRequest = body || state.memberSearchRequest;
            if (status >= 200 && status < 300 && responseData && typeof responseData === "object") {
                state.memberSearchResponse = responseData;
                state.memberSearchCapturedAt = new Date().toISOString();
            }
            rememberSupportingResponse(state, request, parsedUrl, body, responseData, status);
            persistNonSecretState(state);
            setStatus(state, "Member/subscriber details captured and preserved.", "ready", { state: "IDENTITY_CAPTURED" });
            return;
        }

        if (path === MEMBER_BENEFITS_PATH) {
            rememberCoreTransaction(state, "member_benefits", request, parsedUrl, body, responseData, status);
            state.memberBenefitsRequest = body || state.memberBenefitsRequest;
            state.memberBenefitsResponse = responseData;
            rememberSupportingResponse(state, request, parsedUrl, body, responseData, status);
            refreshProcedureTemplate(state);
            persistNonSecretState(state);
            setStatus(
                state,
                state.procedureTemplate && state.procedureHeaders?.authorization
                    ? "Member benefits captured. Ready to extract procedure codes."
                    : state.procedureTemplate
                        ? "Member benefits captured; waiting for authenticated API context."
                        : "Member benefits captured; waiting for remaining plan context.",
                state.procedureTemplate && state.procedureHeaders?.authorization ? "ready" : "working"
            );
            return;
        }

        if (path === ROUTINE_PROCEDURES_PATH) {
            rememberCoreTransaction(state, "routine_procedures", request, parsedUrl, body, responseData, status);
            state.routineProceduresRequest = body || state.routineProceduresRequest;
            state.routineProceduresResponse = responseData;
            rememberSupportingResponse(state, request, parsedUrl, body, responseData, status);
            refreshProcedureTemplate(state);
            persistNonSecretState(state);
            return;
        }

        if (path === CLIENT_SEARCH_PATH) {
            rememberCoreTransaction(state, "client_search", request, parsedUrl, body, responseData, status);
            state.clientSearchRequest = body || state.clientSearchRequest;
            state.clientSearchResponse = responseData;
            rememberSupportingResponse(state, request, parsedUrl, body, responseData, status);
            refreshProcedureTemplate(state);
            persistNonSecretState(state);
            return;
        }

        if (path === PROCEDURE_SEARCH_PATH) {
            if (body && typeof body === "object") {
                ensurePersonScope(state, body);
                const capturedTemplate = { ...body, procedureCodes: "" };
                const signature = procedureTemplateSignature(capturedTemplate);
                if (state.procedureTemplateSignature && signature !== state.procedureTemplateSignature) {
                    state.procedureResponses.clear();
                }
                state.procedureTemplate = capturedTemplate;
                state.procedureTemplateSignature = signature;
                if (replayHeaders.authorization) {
                    state.procedureHeaders = { ...state.procedureHeaders, ...replayHeaders };
                }
                const codes = extractCodes(body.procedureCodes);
                if (codes.length === 1) {
                    state.procedureResponses.set(codes[0], {
                        request: nativeRequestSnapshot(request, parsedUrl, body),
                        http_status: status,
                        captured_at: new Date().toISOString(),
                        response: sanitizeForOutput(responseData)
                    });
                }
                // Procedure results are crawl-local and do not need to be rewritten to sessionStorage.
                // Persisting the entire non-secret state here once per code made a 72-code crawl needlessly expensive.
                setStatus(state, "Authenticated procedure context captured. Member identity preserved.", "ready", { state: "READY" });
            }
            return;
        }

        rememberSupportingResponse(state, request, parsedUrl, body, responseData, status);
    }

    function nativeRequestSnapshot(request, parsedUrl, body) {
        return {
            method: String(request?.method || "GET").toUpperCase(),
            endpoint: parsedUrl.pathname,
            query: parsedUrl.search || "",
            headers: sanitizeForOutput(request?.headers || {}),
            body: sanitizeForOutput(body)
        };
    }

    function rememberCoreTransaction(state, key, request, parsedUrl, body, responseData, status) {
        state.coreTransactions[key] = {
            request: nativeRequestSnapshot(request, parsedUrl, body),
            http_status: Number.isFinite(Number(status)) ? Number(status) : null,
            captured_at: new Date().toISOString(),
            response: sanitizeForOutput(responseData)
        };
    }

    function rememberSupportingResponse(state, request, parsedUrl, body, responseData, status) {
        if (!isRelevantJson(responseData)) return;
        const sanitized = sanitizeForOutput(responseData);
        const approximateSize = safeStringify(sanitized).length;
        if (approximateSize > 1_500_000 || state.supportingApiResponses.length >= 80) return;

        // Native-first mode keeps each captured Toolkit transaction instead of silently
        // replacing an earlier call merely because endpoint/query are the same.
        state.supportingApiResponses.push({
            endpoint: parsedUrl.pathname,
            query: parsedUrl.search,
            captured_at: new Date().toISOString(),
            http_status: Number.isFinite(Number(status)) ? Number(status) : null,
            request: nativeRequestSnapshot(request, parsedUrl, body),
            response: sanitized
        });
    }

    function derivePersonKey(body) {
        if (!body || typeof body !== "object") return "";
        const memberPersonId = firstMeaningful([
            body.memberPersonId, body.personId, body.memberOid, body.memberPersonOid
        ]);
        const subscriberPersonId = firstMeaningful([
            body.subscriberPersonId, body.subscriberOid, body.subscriberPersonOid
        ]);
        if (!memberPersonId && !subscriberPersonId) return "";

        // IMPORTANT: this key is deliberately ONLY person identity.
        // Client, sub-client, plan acronym and benefit-program identifiers are coverage context,
        // and can legitimately be absent/different between Toolkit endpoints for the SAME patient.
        return `member:${cleanText(memberPersonId || "")}|subscriber:${cleanText(subscriberPersonId || "")}`;
    }

    function ensurePersonScope(state, body) {
        const nextKey = derivePersonKey(body);
        if (!nextKey) return;

        if (state.personKey && state.personKey !== nextKey) {
            if (state.activeRun && !state.activeRun.done) state.activeRun.cancelled = true;

            // Clear ONLY member-specific plan/procedure state.
            // Do NOT clear memberSearchRequest/memberSearchResponse here: that dedicated identity
            // snapshot may have been captured immediately before the new benefit request.
            // buildFinalOutput validates that snapshot against current API IDs / live DOM before use,
            // so stale member details cannot silently leak into a different patient.
            state.memberBenefitsRequest = null;
            state.memberBenefitsResponse = null;
            state.routineProceduresRequest = null;
            state.routineProceduresResponse = null;
            state.clientSearchRequest = null;
            state.clientSearchResponse = null;
            state.procedureTemplate = null;
            state.procedureTemplateSignature = null;
            state.procedureResponses.clear();
            state.supportingApiResponses = [];
            state.faxbackPdf = null;
            const preservedMemberTx = state.coreTransactions?.member_details || null;
            state.coreTransactions = preservedMemberTx ? { member_details: preservedMemberTx } : {};
            setStatus(state, "Actual member ID changed — plan/procedure cache reset; preserved member-details snapshot for validation.", "working", { state: "MEMBER_CHANGED" });
        }
        state.personKey = nextKey;
    }

    function procedureTemplateSignature(template) {
        if (!template || typeof template !== "object") return "";
        const stable = {
            benefitProgramOid: template.benefitProgramOid || "",
            benefitProgramOid2: template.benefitProgramOid2 || "",
            memberBirthDate: template.memberBirthDate || "",
            memberPersonId: template.memberPersonId || "",
            relationshipToSubscriber: template.relationshipToSubscriber || "",
            subClientOid: template.subClientOid || "",
            subscriberPersonId: template.subscriberPersonId || "",
            memberBenefitType: template.memberBenefitType ?? null,
            planAcronym: template.planAcronym || "",
            clientSpecifiedId: template.clientSpecifiedId || "",
            subClientSpecifiedId: template.subClientSpecifiedId || "",
            ehbrequest: Boolean(template.ehbrequest),
            priorAuthRequest: Boolean(template.priorAuthRequest)
        };
        return JSON.stringify(stable);
    }

    function refreshProcedureTemplate(state) {
        const benefitsRequest = state.memberBenefitsRequest || {};
        const benefitsResponse = state.memberBenefitsResponse || {};
        const routineRequest = state.routineProceduresRequest || {};
        const clientResponse = state.clientSearchResponse || {};
        const client = benefitsResponse.client || clientResponse.client || {};
        const existing = state.procedureTemplate || {};

        const memberBirthDate = firstMeaningful([
            benefitsRequest.memberDateOfBirth,
            routineRequest.memberBirthDate,
            existing.memberBirthDate
        ]);

        const candidate = {
            benefitProgramOid: firstMeaningful([
                benefitsResponse.benefitProgramOid,
                existing.benefitProgramOid
            ]),
            benefitProgramOid2: firstMeaningful([
                benefitsResponse.benefitProgramOid2,
                routineRequest.benefitProgramOid,
                existing.benefitProgramOid2
            ]),
            ehbrequest: Boolean(benefitsRequest.isEHBRequest ?? existing.ehbrequest ?? false),
            memberBirthDate: normalizeApiDate(memberBirthDate),
            memberPersonId: firstMeaningful([
                benefitsRequest.memberPersonId,
                routineRequest.memberPersonId,
                existing.memberPersonId
            ]),
            procedureCodes: "",
            relationshipToSubscriber: firstMeaningful([
                benefitsRequest.relationshipToSubscriber,
                routineRequest.relationshipToSubscriber,
                existing.relationshipToSubscriber
            ]),
            subClientOid: firstMeaningful([
                benefitsResponse.client?.subClientOid,
                client.subClientOid,
                client.subClient?.oid,
                existing.subClientOid
            ]),
            subscriberPersonId: firstMeaningful([
                benefitsRequest.subscriberPersonId,
                routineRequest.subscriberPersonId,
                existing.subscriberPersonId
            ]),
            memberBenefitType:
                benefitsRequest.memberBenefitType ??
                routineRequest.memberBenefitType ??
                existing.memberBenefitType ??
                null,
            utilizationIndicator: false,
            planAcronym: firstMeaningful([
                benefitsRequest.memberPlanAcronym,
                routineRequest.planAcronym,
                benefitsResponse.client?.planAcronym,
                client.planAcronym,
                existing.planAcronym
            ]),
            clientSpecifiedId: firstMeaningful([
                benefitsRequest.clientSpecifiedId,
                routineRequest.clientId,
                benefitsResponse.client?.clientSpecifiedId,
                existing.clientSpecifiedId
            ]),
            subClientSpecifiedId: firstMeaningful([
                benefitsRequest.subClientSpecifiedId,
                routineRequest.subClientId,
                benefitsResponse.client?.subClientSpecifiedId,
                existing.subClientSpecifiedId
            ]),
            priorAuthRequest: false
        };

        const required = [
            "benefitProgramOid", "benefitProgramOid2", "memberBirthDate",
            "memberPersonId", "relationshipToSubscriber", "subClientOid",
            "subscriberPersonId", "planAcronym", "clientSpecifiedId",
            "subClientSpecifiedId"
        ];

        if (required.every(key => !isNA(candidate[key]))) {
            ensurePersonScope(state, candidate);
            const signature = procedureTemplateSignature(candidate);
            if (state.procedureTemplateSignature && signature !== state.procedureTemplateSignature) {
                // Same person can have a changed plan/benefit program. Only procedure replay cache
                // is invalidated; member identity remains untouched.
                state.procedureResponses.clear();
            }
            state.procedureTemplate = candidate;
            state.procedureTemplateSignature = signature;
            return true;
        }
        return false;
    }

    function normalizeApiDate(value) {
        const text = cleanText(String(value || ""));
        if (!text) return "";

        // Preserve the calendar DOB while normalizing the time component to
        // midnight in the same offset used by the Toolkit request.
        const isoMatch = text.match(/^(\d{4}-\d{2}-\d{2})(?:T[^Z+-]*)?(Z|[+-]\d{2}:?\d{2})?$/i);
        if (isoMatch) {
            const zone = isoMatch[2]
                ? (isoMatch[2].toUpperCase() === "Z" ? "Z" : isoMatch[2].replace(/([+-]\d{2})(\d{2})$/, "$1:$2"))
                : "Z";
            const midnight = new Date(`${isoMatch[1]}T00:00:00${zone}`);
            if (!Number.isNaN(midnight.getTime())) return midnight.toISOString();
        }

        const date = new Date(text);
        return Number.isNaN(date.getTime()) ? text : date.toISOString();
    }

    function installPageMessageBridge(state, nativeFetch) {
        window.addEventListener("message", event => {
            if (event.source !== window || event.origin !== window.location.origin) return;
            const message = event.data;
            if (!message || message.source !== EXT_SOURCE) return;

            if (message.type === "RESULT_ACK" && state.activeRun?.requestId === message.requestId) {
                state.activeRun.acknowledged = true;
                const data = state.activeRun.resultData;
                const stats = data?.crawl_statistics || {};
                const failed = Array.isArray(stats.failed_codes) ? stats.failed_codes.length : 0;
                setStatus(
                    state,
                    failed
                        ? `Partial — ${stats.successful_codes ?? 0}/${stats.requested_codes ?? PROCEDURE_CODES.length} API code lookups succeeded. JSON downloaded.`
                        : `Done — ${stats.successful_codes ?? 0}/${stats.requested_codes ?? PROCEDURE_CODES.length} API code lookups succeeded. JSON downloaded.`,
                    failed ? "warning" : "ready",
                    { state: failed ? "PARTIAL" : "COMPLETE" }
                );
                return;
            }

            if (message.type === "GET_STATUS") {
                refreshProcedureTemplate(state);
                postPageMessage("TOOLKIT_STATUS", {
                    requestId: message.requestId,
                    payload: getToolkitStatus(state)
                });
                return;
            }

            if (message.type === "START_CRAWL") {
                postPageMessage("STARTED", {
                    requestId: message.requestId,
                    status: "[+] Delta Toolkit crawl requested. Validating member/API context…"
                });
                startCrawl(state, nativeFetch, message.requestId).catch(error => {
                    setStatus(state, error.message, "error", { state: "FAILED" });
                    postPageMessage("ERROR", { requestId: message.requestId, error: error.message });
                });
            }
        });
    }

    function getToolkitStatus(state) {
        refreshProcedureTemplate(state);
        const contextReady = Boolean(state.procedureTemplate);
        const authReady = Boolean(state.procedureHeaders?.authorization);
        const domMember = extractCurrentMemberFromDom();
        const memberApiContext = resolveMemberApiContext(state.memberSearchResponse || {}, state.procedureTemplate || {}, domMember);
        const memberIdentityReady = Boolean(memberApiContext.matched || domMember.name);
        const ready = contextReady && authReady;
        if (state.activeRun && !state.activeRun.done) {
            return {
                ready: false,
                contextReady,
                authReady,
                memberIdentityReady,
                personKey: state.personKey || "",
                state: "RUNNING",
                message: "Delta Toolkit crawl is running. Keep this tab open until the JSON downloads."
            };
        }
        if (state.activeRun?.resultData) {
            const stats = state.activeRun.resultData.crawl_statistics || {};
            const failed = Array.isArray(stats.failed_codes) ? stats.failed_codes.length : 0;
            return {
                ready: true,
                contextReady,
                authReady,
                memberIdentityReady,
                personKey: state.personKey || "",
                state: failed ? "PARTIAL" : "COMPLETE",
                message: failed
                    ? `Last crawl: ${stats.successful_codes}/${stats.requested_codes} codes succeeded; JSON contains failure details.`
                    : `Last crawl complete: ${stats.successful_codes ?? 0}/${stats.requested_codes ?? PROCEDURE_CODES.length} codes succeeded.`
            };
        }
        return {
            ready,
            contextReady,
            authReady,
            memberIdentityReady,
            personKey: state.personKey || "",
            state: ready ? "READY" : "WAITING",
            message: ready
                ? (memberIdentityReady
                    ? "Delta Toolkit: procedure API ready; current member identity is available."
                    : "Delta Toolkit: procedure API ready; member-details API was not captured, so the live selected-member DOM will be used if available.")
                : !contextReady
                    ? "Delta Toolkit: waiting for member-benefits/plan API context. Open the Member Details & Benefits page and let it finish loading."
                    : "Delta Toolkit: plan context ready; waiting for authenticated API traffic. Refresh the member-benefits page if needed."
        };
    }

    function installFloatingUiWhenReady(state, nativeFetch) {
        const install = () => {
            if (!document.documentElement || document.getElementById("delta-toolkit-extractor-ui")) return;

            const root = document.createElement("div");
            root.id = "delta-toolkit-extractor-ui";
            root.style.cssText = [
                "position:fixed", "right:18px", "bottom:18px", "z-index:2147483647",
                "width:300px", "font:13px/1.4 Arial,sans-serif", "background:#fff",
                "color:#172033", "border:1px solid #9db3c7", "border-radius:10px",
                "box-shadow:0 8px 28px rgba(0,0,0,.22)", "padding:12px"
            ].join(";");

            const title = document.createElement("div");
            title.textContent = "Delta Toolkit Extractor";
            title.style.cssText = "font-weight:700;margin-bottom:6px;color:#075985";

            const status = document.createElement("div");
            status.style.cssText = "min-height:36px;margin-bottom:9px;color:#475569";
            status.textContent = state.procedureTemplate
                ? "Authenticated member/plan context learned. Ready."
                : "Open Member Details & Benefits and let plan data load.";

            const button = document.createElement("button");
            button.type = "button";
            button.textContent = "Extract Delta Benefits";
            button.style.cssText = [
                "width:100%", "border:0", "border-radius:7px", "padding:9px 12px",
                "font-weight:700", "cursor:pointer", "background:#0e7490", "color:#fff"
            ].join(";");
            button.addEventListener("click", () => {
                const requestId = makeId();
                startCrawl(state, nativeFetch, requestId).catch(error => {
                    setStatus(state, error.message, "error");
                    postPageMessage("ERROR", { requestId, error: error.message });
                });
            });

            root.append(title, status, button);
            document.documentElement.appendChild(root);
            state.statusEl = status;
            state.buttonEl = button;
        };

        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", install, { once: true });
        } else install();
    }

    // =====================================================================
    // Faxback PDF capture (the "Please click HERE" link on Member Benefits)
    // =====================================================================

    function isFaxbackDocumentUrl(url) {
        try {
            const parsed = new URL(url, location.href);
            return parsed.origin === TARGET_ORIGIN && parsed.pathname === DOCUMENT_PATH;
        } catch (_) {
            return false;
        }
    }

    // The portal asks for a blob/arraybuffer even though the server labels the
    // body application/json. A text responseType would already have been
    // UTF-8 decoded (corrupting the PDF), so that case is deliberately ignored.
    async function readXhrBinary(xhr) {
        const type = xhr.responseType;
        if (type === "arraybuffer") return new Uint8Array(xhr.response);
        if (type === "blob") return new Uint8Array(await xhr.response.arrayBuffer());

        // The Toolkit's faxback endpoint can be labelled application/json while
        // returning the PDF bytes as a Latin-1 text XHR. Accept that representation
        // instead of silently timing out the PDF capture.
        if (!type || type === "text") {
            const text = xhr.responseText || "";
            if (/^%PDF-/.test(text)) {
                const bytes = new Uint8Array(text.length);
                for (let i = 0; i < text.length; i += 1) bytes[i] = text.charCodeAt(i) & 0xff;
                return bytes;
            }
        }
        if (type === "json" && typeof xhr.response === "string" && /^%PDF-/.test(xhr.response)) {
            const text = xhr.response;
            const bytes = new Uint8Array(text.length);
            for (let i = 0; i < text.length; i += 1) bytes[i] = text.charCodeAt(i) & 0xff;
            return bytes;
        }
        return null;
    }

    function bytesToBase64(bytes) {
        let binary = "";
        for (let i = 0; i < bytes.length; i += 0x8000) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        }
        return btoa(binary);
    }

    async function sha256Hex(bytes) {
        const digest = await crypto.subtle.digest("SHA-256", bytes);
        return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
    }

    async function acceptPdfBytes(state, bytes, status) {
        if (status !== 200 || !bytes || bytes.length < 100) return;
        const magic = String.fromCharCode(...bytes.subarray(0, 5));
        if (magic !== "%PDF-") return;
        const record = {
            personKey: state.personKey || null,
            capturedAt: new Date().toISOString(),
            bytes
        };
        state.faxbackPdf = record;
        for (const resolve of state.pdfWaiters.splice(0)) resolve(record);
    }

    // =====================================================================
    // Faxback PDF parsing
    // =====================================================================

    function pdfLatin1(bytes) {
        let text = "";
        for (let i = 0; i < bytes.length; i += 0x8000) {
            text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        }
        return text;
    }

    async function inflatePdfStream(bytes) {
        if (!bytes?.length) return new Uint8Array();
        // Do not manually drive the DecompressionStream writer/reader. Firefox
        // can stall on some Flate streams from the Toolkit PDF. Piping a Response
        // body through the decompressor lets the browser own the stream lifecycle.
        const body = new Response(bytes).body;
        if (!body) throw new Error("PDF stream body is unavailable.");
        const decompressed = body.pipeThrough(new DecompressionStream("deflate"));
        return new Uint8Array(await new Response(decompressed).arrayBuffer());
    }

    function readPdfLiteral(text, start) {
        let depth = 1;
        let raw = "";
        let i = start + 1;
        while (i < text.length) {
            const char = text[i];
            if (char === "\\") {
                if (i + 1 < text.length) {
                    raw += `\\${text[i + 1]}`;
                    i += 2;
                    continue;
                }
                break;
            }
            if (char === "(") {
                depth += 1;
                raw += char;
                i += 1;
                continue;
            }
            if (char === ")") {
                depth -= 1;
                if (depth === 0) return { value: decodePdfLiteral(raw), end: i + 1 };
                raw += char;
                i += 1;
                continue;
            }
            raw += char;
            i += 1;
        }
        return { value: decodePdfLiteral(raw), end: i };
    }

    function decodePdfLiteral(raw) {
        let output = "";
        for (let i = 0; i < raw.length; i += 1) {
            const char = raw[i];
            if (char !== "\\") {
                output += char;
                continue;
            }
            const next = raw[++i];
            if (next === undefined) break;
            if (next === "n") output += "\\n";
            else if (next === "r") output += "\\r";
            else if (next === "t") output += "\\t";
            else if (next === "b") output += "\\b";
            else if (next === "f") output += "\\f";
            else if (next === "(" || next === ")" || next === "\\") output += next;
            else if (/[0-7]/.test(next)) {
                let octal = next;
                for (let j = 0; j < 2 && i + 1 < raw.length && /[0-7]/.test(raw[i + 1]); j += 1) {
                    octal += raw[++i];
                }
                output += String.fromCharCode(parseInt(octal, 8));
            } else {
                output += next;
            }
        }
        return output;
    }

    function parsePdfArray(text, start) {
        const items = [];
        let i = start + 1;
        while (i < text.length) {
            while (i < text.length && /[\s\0]/.test(text[i])) i += 1;
            if (i >= text.length) break;
            if (text[i] === "]") return { value: items, end: i + 1 };
            const token = parsePdfValue(text, i);
            if (!token) break;
            items.push(token);
            i = token.end;
        }
        return { value: items, end: i };
    }

    function parsePdfValue(text, start) {
        const char = text[start];
        if (char === "(") {
            const literal = readPdfLiteral(text, start);
            return { type: "string", value: literal.value, end: literal.end };
        }
        if (char === "[") {
            const array = parsePdfArray(text, start);
            return { type: "array", value: array.value, end: array.end };
        }
        if (char === "<" && text[start + 1] !== "<") {
            const end = text.indexOf(">", start + 1);
            const hex = text.slice(start + 1, end < 0 ? text.length : end).replace(/\s+/g, "");
            const bytes = [];
            for (let i = 0; i + 1 < hex.length; i += 2) bytes.push(parseInt(hex.slice(i, i + 2), 16));
            const value = new TextDecoder("windows-1252").decode(new Uint8Array(bytes));
            return { type: "string", value, end: end < 0 ? text.length : end + 1 };
        }
        let end = start + 1;
        while (end < text.length && !/[\s\[\]()<>{}]/.test(text[end])) end += 1;
        const word = text.slice(start, end);
        return { type: "word", value: word, end };
    }

    function extractPdfTextChunks(decodedBytes) {
        const text = new TextDecoder("windows-1252").decode(decodedBytes || new Uint8Array());
        const chunks = [];
        let i = 0;
        const operands = [];
        let inText = false;
        while (i < text.length) {
            while (i < text.length && /[\s\0]/.test(text[i])) i += 1;
            if (i >= text.length) break;
            if (text[i] === "%") {
                while (i < text.length && text[i] !== "\n") i += 1;
                continue;
            }
            const parsed = parsePdfValue(text, i);
            if (!parsed) break;
            i = parsed.end;
            const token = parsed.value;
            if (parsed.type !== "word") {
                operands.push({ type: parsed.type, value: token });
                continue;
            }

            const op = token;
            if (op === "BT") {
                inText = true;
                operands.length = 0;
                continue;
            }
            if (op === "ET") {
                inText = false;
                operands.length = 0;
                continue;
            }
            if (op === "Tj" && inText) {
                const value = [...operands].reverse().find(item => item.type === "string")?.value;
                if (value) chunks.push(value);
                operands.length = 0;
                continue;
            }
            if (op === "TJ" && inText) {
                const arrayValue = [...operands].reverse().find(item => item.type === "array")?.value;
                if (Array.isArray(arrayValue)) {
                    const value = arrayValue
                        .filter(item => item?.type === "string")
                        .map(item => item.value)
                        .join("");
                    if (value) chunks.push(value);
                }
                operands.length = 0;
                continue;
            }

            // Every remaining PDF operator terminates its operands. This keeps text
            // commands independent while still allowing the following Tj/TJ to work.
            operands.length = 0;
        }
        return chunks
            .map(normalizePdfText)
            .filter(Boolean);
    }

    function normalizePdfText(value) {
        return cleanText(String(value || "")
            .replace(/\u0095/g, "•")
            .replace(/\u00a0/g, " "))
            .replace(/\s+/g, " ")
            .trim();
    }

    async function parsePdfObjects(bytes) {
        const source = pdfLatin1(bytes);
        const objectRegex = /\b(\d+)\s+(\d+)\s+obj\b/g;
        const objects = new Map();
        let match;
        while ((match = objectRegex.exec(source))) {
            const objectId = Number(match[1]);
            const endObject = source.indexOf("endobj", objectRegex.lastIndex);
            if (endObject < 0) break;
            const bodyStart = objectRegex.lastIndex;
            const body = source.slice(bodyStart, endObject);
            const streamIndex = body.indexOf("stream");
            let stream = null;
            let dictionary = body;
            if (streamIndex >= 0) {
                dictionary = body.slice(0, streamIndex);
                let dataStart = bodyStart + streamIndex + "stream".length;
                while (dataStart < source.length && (source[dataStart] === "\r" || source[dataStart] === "\n" || source[dataStart] === " ")) dataStart += 1;
                const dataEnd = source.indexOf("endstream", dataStart);
                if (dataEnd >= 0) {
                    let end = dataEnd;
                    while (end > dataStart && (source[end - 1] === "\r" || source[end - 1] === "\n")) end -= 1;
                    stream = Uint8Array.from(source.slice(dataStart, end), char => char.charCodeAt(0));
                }
            }
            objects.set(objectId, { dictionary, stream });
            objectRegex.lastIndex = endObject + "endobj".length;
        }
        return objects;
    }

    async function decodePdfObjectStream(object) {
        if (!object?.stream) return new Uint8Array();
        if (/FlateDecode/i.test(object.dictionary || "")) return inflatePdfStream(object.stream);
        return object.stream;
    }

    function extractPdfContentRefs(pageObject) {
        const body = pageObject?.dictionary || "";
        const match = body.match(/\/Contents\s+(?:\[([^\]]+)\]|(\d+)\s+\d+\s+R)/);
        if (!match) return [];
        const refs = [];
        if (match[1]) {
            for (const ref of match[1].matchAll(/(\d+)\s+\d+\s+R/g)) refs.push(Number(ref[1]));
        }
        if (match[2]) refs.push(Number(match[2]));
        return refs;
    }

    async function parseFaxbackPdfDocument(record) {
        if (!record?.bytes?.length) return { status: "NOT_CAPTURED", reason: "Faxback PDF bytes were not captured." };
        try {
            const bytes = record.bytes;
            const objects = await parsePdfObjects(bytes);
            const pageObjects = [...objects.entries()]
                .filter(([, object]) => /\/Type\s+\/Page\b/.test(object?.dictionary || ""))
                .sort(([a], [b]) => a - b);

            const pages = [];
            for (const [, pageObject] of pageObjects) {
                const refs = extractPdfContentRefs(pageObject);
                const chunks = [];
                for (const ref of refs) {
                    const decoded = await decodePdfObjectStream(objects.get(ref));
                    chunks.push(...extractPdfTextChunks(decoded));
                }
                pages.push({ lines: chunks.map(normalizePdfText).filter(Boolean) });
            }

            const fallbackStreams = [...objects.entries()]
                .filter(([, object]) => object?.stream && /BT\b/.test(object?.dictionary || "") === false)
                .sort(([a], [b]) => a - b);
            if (pages.length === 0) {
                for (const [, object] of fallbackStreams) {
                    const decoded = await decodePdfObjectStream(object);
                    const lines = extractPdfTextChunks(decoded);
                    if (lines.length) pages.push({ lines });
                }
            }

            if (!pages.length) return { status: "PARSE_FAILED", reason: "No readable text streams were found in the faxback PDF." };
            const structured = buildFaxbackDocumentModel(pages);
            return {
                status: structured.parse_warnings?.length ? "CAPTURED_WITH_WARNINGS" : "CAPTURED",
                page_count: pages.length,
                structured
            };
        } catch (error) {
            return { status: "PARSE_FAILED", reason: `Faxback PDF parsing failed: ${error.message}` };
        }
    }

    const PDF_BENEFIT_CATEGORIES = Object.freeze([
        "Diagnostic",
        "Preventive",
        "Bitewing Radiographs",
        "All Other Radiographs",
        "Sealants",
        "Minor Restorative",
        "Major Restorative",
        "Endodontics",
        "Periodontics",
        "Simple Extractions",
        "Other Oral Surgery",
        "Other Basic Services",
        "Prosthodontics",
        "Implants",
        "Orthodontic Services"
    ]);

    const PDF_OFFICE_VISIT_PROCEDURES = Object.freeze([
        "Exam",
        "Adult Cleaning",
        "Child Cleaning",
        "Perio Maintenance Cleaning",
        "Bitewings",
        "Full Mouth X-rays",
        "Fluoride",
        "Occlusal Guard"
    ]);

    function normalizePdfField(text) {
        return normalizePdfText(text)
            .replace(/issuedon/gi, "issued on")
            .replace(/thepatient/gi, "the patient")
            .replace(/coverageor/gi, "coverage or")
            .replace(/paymentsare/gi, "payments are")
            .replace(/determinedonly/gi, "determined only")
            .replace(/processingpolicies/gi, "processing policies")
            .replace(/witha/gi, "with a")
            .replace(/under theBenefits/gi, "under the Benefits")
            .trim();
    }

    function pdfValueAfterLabel(lines, label) {
        const index = lines.findIndex(line => line === label || line.startsWith(label));
        if (index < 0) return null;
        const inline = cleanText(lines[index].slice(label.length).replace(/^\s*[:\-]\s*/, ""));
        if (inline) return normalizePdfField(inline);
        for (let i = index + 1; i < lines.length; i += 1) {
            const next = normalizePdfField(lines[i]);
            if (next) return next;
        }
        return null;
    }

    function pdfLineIndex(lines, pattern, start = 0) {
        for (let i = start; i < lines.length; i += 1) {
            if (pattern.test(lines[i])) return i;
        }
        return -1;
    }

    function pdfMoneyNumber(value) {
        if (!value) return null;
        const normalized = String(value).replace(/[^0-9.]/g, "");
        const number = Number(normalized);
        return Number.isFinite(number) ? number : null;
    }

    function pdfParseEligibility(page1Lines) {
        const lines = toArray(page1Lines).map(normalizePdfText).filter(Boolean);
        const overview = lines.slice(0, 3).join(" ");
        const memberName = pdfValueAfterLabel(lines, "Member Name:");
        const patientName = pdfValueAfterLabel(lines, "Patient Name:");
        const relationship = pdfValueAfterLabel(lines, "Relationship:");
        const clientName = pdfValueAfterLabel(lines, "Client Name:");
        const clientNumber = pdfValueAfterLabel(lines, "Client Number:");
        const product = pdfValueAfterLabel(lines, "Product:");
        const currentlyEligible = pdfValueAfterLabel(lines, "Currently Eligible:");

        const claimsIndex = pdfLineIndex(lines, /^Claims Mailing Address$/i);
        const clientInfoIndex = pdfLineIndex(lines, /^Client Information:$/i, Math.max(0, claimsIndex));
        const claimsBlock = claimsIndex >= 0
            ? lines.slice(claimsIndex + 1, clientInfoIndex >= 0 ? clientInfoIndex : lines.length)
            : [];
        const deltaIndex = claimsBlock.findIndex(line => /^Delta Dental$/i.test(line));
        const payerIndex = claimsBlock.findIndex(line => /^Payer ID$/i.test(line));
        const streetIndex = claimsBlock.findIndex(line => /^P\.O\. Box/i.test(line));
        const street = streetIndex >= 0 ? claimsBlock[streetIndex] : null;
        const cityStateZip = streetIndex >= 0 ? claimsBlock[streetIndex + 1] : null;
        const payerIds = payerIndex >= 0 && claimsBlock[payerIndex + 1]
            ? claimsBlock[payerIndex + 1].split(/,\s*/).map(cleanText).filter(Boolean)
            : [];
        const payer_id_notice = payerIndex >= 0 && claimsBlock[payerIndex + 2]
            ? normalizePdfField(claimsBlock[payerIndex + 2])
            : null;

        const coordinationIndex = pdfLineIndex(lines, /^Coordination of Benefits$/i);
        const maxIndex = pdfLineIndex(lines, /^Maximum and Deductibles$/i);
        const cobBlock = coordinationIndex >= 0
            ? lines.slice(coordinationIndex + 1, maxIndex >= 0 ? maxIndex : lines.length)
            : [];
        const cobInternal = pdfValueAfterLabel(cobBlock, "Internal:");
        const cobExternal = pdfValueAfterLabel(cobBlock, "External:");
        const website = cobBlock.map(line => line.match(/\bwww\.[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b/i)?.[0]).find(Boolean) || null;
        const cobNarrative = cobBlock.find(line => /^Coordination of benefits information is based on/i.test(line)) || null;

        const clientInformation = clientInfoIndex >= 0
            ? lines.slice(clientInfoIndex + 1, coordinationIndex >= 0 ? coordinationIndex : lines.length).join(" ")
            : null;

        const officeVisitIndex = pdfLineIndex(lines, /^Office Visit$/i, Math.max(0, maxIndex));
        const maxBlock = maxIndex >= 0
            ? lines.slice(maxIndex + 1, officeVisitIndex >= 0 ? officeVisitIndex : lines.length)
            : [];
        const orthoAmountIndex = maxBlock.findIndex(line => /^Orthodontic\b/i.test(line));
        const generalAmountIndex = maxBlock.findIndex(line => /^General\b/i.test(line));
        const moneyPair = /\$?\s*[0-9][0-9,]*(?:\.\d+)?\s*\/\s*\$?\s*[0-9][0-9,]*(?:\.\d+)?/;
        const isMoneyLine = line => moneyPair.test(line) && !/\d{1,2}\/\d{1,2}\/\d{4}/.test(line);
        const orthoAmount = orthoAmountIndex >= 0 ? maxBlock.slice(orthoAmountIndex + 1).find(isMoneyLine) : null;
        const generalAmount = generalAmountIndex >= 0 ? maxBlock.slice(generalAmountIndex + 1).find(isMoneyLine) : null;
        const orthoNums = orthoAmount?.match(/\$?\s*([0-9,.]+)\s*\/\s*\$?\s*([0-9,.]+)/) || null;
        const generalNums = generalAmount?.match(/\$?\s*([0-9,.]+)\s*\/\s*\$?\s*([0-9,.]+)/) || null;
        const orthoPeriodIndex = maxBlock.findIndex((line, i) => /^Lifetime$/i.test(line) && i > orthoAmountIndex);
        const periodLine = /^\d{2}\/\d{2}\/\d{4}\s+to\s+\d{2}\/\d{2}\/\d{4}$/i;
        const maxDeductibleHeader = maxBlock.findIndex(line => /^Deductible$/i.test(line));
        const maximumOnly = maxDeductibleHeader >= 0 ? maxBlock.slice(0, maxDeductibleHeader) : maxBlock;
        const generalPeriod = maximumOnly.find(line => periodLine.test(line)) || null;
        const appliesOrthoIndex = maxBlock.findIndex(line => /^on orthodontic services\.?$/i.test(line));
        const appliesGeneralIndex = maxBlock.findIndex(line => /^on all services,/i.test(line));
        const collectUntilDate = (block, start) => {
            if (start < 0) return null;
            const parts = [];
            for (let i = start; i < block.length && !/^\d{2}\/\d{2}\/\d{4}\s+to\s+\d{2}\/\d{2}\/\d{4}$/i.test(block[i]); i += 1) {
                if (!/^(?:PPO Dentist|Premier Dentist|Nonparticipating Dentist|Benefit Periods|applies to)$/i.test(block[i])) parts.push(block[i]);
            }
            return normalizePdfField(parts.join(" ")) || null;
        };
        const deductibleStatement = lines.find(line => /no deductible for this contract/i.test(line)) || null;

        const deductibleIndex = lines.findIndex((line, index) => /^Deductible$/i.test(line) && index > maxIndex);
        const deductibleEnd = pdfLineIndex(lines, /^Office Visit$/i, Math.max(0, deductibleIndex));
        const deductibleBlock = deductibleIndex >= 0
            ? lines.slice(deductibleIndex + 1, deductibleEnd >= 0 ? deductibleEnd : lines.length)
            : [];
        const deductibleGeneralIndex = deductibleBlock.findIndex(line => /^General$/i.test(line));
        const deductibleValues = deductibleBlock.slice(Math.max(0, deductibleGeneralIndex + 1))
            .filter(isMoneyLine)
            .slice(0, 2)
            .map(line => line.match(/\$?\s*([0-9,.]+)\s*\/\s*\$?\s*([0-9,.]+)/));
        const deductiblePeriod = deductibleBlock.find(line => /^\d{2}\/\d{2}\/\d{4}\s+to\s+\d{2}\/\d{2}\/\d{4}$/i.test(line)) || null;
        const deductibleApplyIndex = deductibleBlock.findIndex(line => /^The Deductible does not apply/i.test(line));
        const deductibleApplies = collectUntilDate(deductibleBlock, deductibleApplyIndex);
        const generalPeriodIndex = maximumOnly.findIndex(line => periodLine.test(line));
        const generalDetails = generalPeriodIndex >= 0
            ? cleanSectionNotes(maximumOnly.slice(generalPeriodIndex + 1))
            : [];
        const accumulator = match => {
            const used = pdfMoneyNumber(match?.[1]);
            const amount = pdfMoneyNumber(match?.[2]);
            return { used, amount, remaining: used === null || amount === null ? null : Math.max(0, amount - used) };
        };

        return {
            overview_notice: normalizePdfField(overview),
            member_name: memberName || null,
            patient_name: patientName || null,
            relationship: relationship || null,
            client_name: clientName || null,
            client_number: clientNumber || null,
            product: product || null,
            currently_eligible: currentlyEligible || null,
            claims_mailing_address: {
                name: deltaIndex >= 0 ? claimsBlock[deltaIndex] : "Delta Dental",
                street,
                city_state_zip: cityStateZip,
                payer_ids: payerIds,
                payer_id_notice
            },
            client_information: clientInformation ? normalizePdfField(clientInformation) : null,
            coordination_of_benefits: {
                internal: cobInternal || null,
                external: cobExternal || null,
                website: website || null,
                narrative: cobNarrative ? normalizePdfField(cobNarrative) : null
            },
            maximum_and_deductibles: {
                networks: ["PPO Dentist", "Premier Dentist", "Nonparticipating Dentist"],
                table_networks: uniqueStrings(maxBlock.filter(line => /^(?:PPO|Premier|Nonparticipating|Non-PPO)\s+Dentist$/i.test(line))),
                maximums: {
                    orthodontic: {
                        individual_used: pdfMoneyNumber(orthoNums?.[1]),
                        individual_max: pdfMoneyNumber(orthoNums?.[2]),
                        family_used: null,
                        family_max: null
                    },
                    general: {
                        individual_used: pdfMoneyNumber(generalNums?.[1]),
                        individual_max: pdfMoneyNumber(generalNums?.[2]),
                        family_used: null,
                        family_max: null
                    }
                },
                applies_to: {
                    orthodontic: collectUntilDate(maxBlock, appliesOrthoIndex),
                    general: collectUntilDate(maxBlock, appliesGeneralIndex)
                },
                benefit_periods: {
                    orthodontic: orthoPeriodIndex >= 0 ? maxBlock[orthoPeriodIndex] : null,
                    general: generalPeriod
                },
                details: generalDetails,
                deductible: {
                    individual: accumulator(deductibleValues[0]),
                    family: accumulator(deductibleValues[1]),
                    applies_to: deductibleApplies ? normalizePdfField(deductibleApplies) : null,
                    benefit_period: deductiblePeriod,
                    statement: deductibleStatement
                }
            }
        };
    }

    function parsePdfDateList(text) {
        return [...String(text || "").matchAll(/\b\d{2}\/\d{2}\/\d{4}\b/g)].map(match => match[0]);
    }

    function isPpoNetworkLabel(network) {
        if (network === null || network === undefined || network === "") return true;
        return String(network).split(/\s*,\s*/).some(name => /^PPO Dentist$/i.test(cleanText(name)));
    }

    function parsePdfOfficeVisit(page1Lines) {
        const lines = toArray(page1Lines).map(normalizePdfText).filter(Boolean);
        const start = pdfLineIndex(lines, /^Office Visit$/i);
        const end = pdfLineIndex(lines, /^Benefit Breakdown$/i, start >= 0 ? start : 0);
        if (start < 0 || end < 0) return { procedures: [], notes: [] };

        const isProcedureLine = line => PDF_OFFICE_VISIT_PROCEDURES.some(item => String(line || "").toLowerCase() === item.toLowerCase());
        const isNetworkHeader = line => /^Networks?\s*:/i.test(String(line || ""));
        const notes = [];
        const procedures = [];
        let network = null;
        let cursor = start + 1;
        while (cursor < end) {
            const line = lines[cursor];
            if (isNetworkHeader(line)) {
                const inline = cleanText(line.replace(/^Networks?\s*:\s*/i, ""));
                if (inline) {
                    network = inline;
                    cursor += 1;
                } else {
                    network = cursor + 1 < end && !isProcedureLine(lines[cursor + 1]) ? cleanText(lines[cursor + 1]) : null;
                    cursor += network ? 2 : 1;
                }
                continue;
            }
            const procedure = PDF_OFFICE_VISIT_PROCEDURES.find(item => line.toLowerCase() === item.toLowerCase());
            if (!procedure) {
                if (!procedures.length && line !== "•") notes.push(line);
                cursor += 1;
                continue;
            }
            const statusText = cleanText(lines[cursor + 1] || "");
            if (!/^(yes|no)$/i.test(statusText)) { cursor += 1; continue; }
            const detailLines = [];
            let next = cursor + 2;
            while (next < end && !isProcedureLine(lines[next]) && !isNetworkHeader(lines[next])) {
                if (lines[next] !== "•") detailLines.push(lines[next]);
                next += 1;
            }
            const detail = normalizePdfField(detailLines.join(" "));
            procedures.push({
                procedure,
                network,
                eligible_now: statusText.toLowerCase() === "yes",
                status_detail: detail || null,
                service_dates: parsePdfDateList(detail)
            });
            cursor = next;
        }
        return { notes: cleanSectionNotes(notes.map(normalizePdfField).filter(Boolean)), procedures };
    }

    function pdfParseProcedureTokens(lines, startIndex) {
        const code = normalizePdfText(lines[startIndex] || "").match(/^D\d{4}$/i)?.[0]?.toUpperCase();
        if (!code) return null;
        const nextLine = normalizePdfText(lines[startIndex + 1] || "");
        if (PDF_BENEFIT_CATEGORIES.some(category => category.toLowerCase() === nextLine.toLowerCase())) return null;
        const percentPattern = /^(?:\d+(?:\.\d+)?%|Not Covered|Optional)$/i;
        const nextIsCoverage = percentPattern.test(nextLine);
        const description = nextIsCoverage ? "" : nextLine;
        let i = startIndex + (nextIsCoverage ? 1 : 2);
        const coverage = [];
        while (i < lines.length && coverage.length < 2) {
            const line = normalizePdfText(lines[i]);
            if (/^D\d{4}$/i.test(line) || PDF_BENEFIT_CATEGORIES.some(category => category.toLowerCase() === line.toLowerCase()) || line === "•") break;
            coverage.push(line);
            i += 1;
        }
        if (coverage.length < 2) return null;
        const firstPercent = coverage[0];
        const firstWait = coverage[1];
        if (!percentPattern.test(firstPercent)) return null;
        const rowCoverage = {
            "PPO Dentist": {
                percent: firstPercent,
                waiting_period: firstWait || null,
                met_date: null
            }
        };
        const isBoundary = line => /^D\d{4}$/i.test(line) || PDF_BENEFIT_CATEGORIES.some(category => category.toLowerCase() === line.toLowerCase()) || line === "•";
        const oonPercent = normalizePdfText(lines[i] || "");
        if (percentPattern.test(oonPercent)) {
            const oonWait = normalizePdfText(lines[i + 1] || "");
            const hasWait = Boolean(oonWait) && !isBoundary(oonWait) && !percentPattern.test(oonWait);
            rowCoverage["Premier Dentist, Nonparticipating Dentist"] = {
                percent: oonPercent,
                waiting_period: hasWait ? oonWait : null,
                met_date: null
            };
            i += hasWait ? 2 : 1;
        }

        return {
            nextIndex: i,
            row: {
                procedure_code: code,
                description,
                coverage: rowCoverage
            }
        };
    }

    function buildFaxbackBenefitGroups(pages) {
        const groups = [];
        let current = null;
        const firstPageLines = toArray(pages[0]?.lines);
        const breakdownStart = pdfLineIndex(firstPageLines, /^Benefit Breakdown$/i);
        const breakdownEnd = pdfLineIndex(firstPageLines, /^mbb_/i, Math.max(0, breakdownStart));
        const firstPageBreakdown = breakdownStart >= 0
            ? firstPageLines.slice(breakdownStart + 1, breakdownEnd >= 0 ? breakdownEnd : firstPageLines.length)
            : [];
        const lines = [...firstPageBreakdown, ...toArray(pages).slice(1).flatMap(page => toArray(page?.lines))]
            .map(normalizePdfText)
            .filter(Boolean);
        let i = 0;
        while (i < lines.length) {
            const line = lines[i];
            if (/^Patient Name:/i.test(line) || /^Client\/Sub-Client #:/i.test(line) || /^Relationship:/i.test(line) || /^mbb_/i.test(line)) {
                i += 1;
                continue;
            }
            const category = PDF_BENEFIT_CATEGORIES.find(item => item.toLowerCase() === line.toLowerCase());
            if (category) {
                current = { category, procedures: [], notes: [] };
                groups.push(current);
                i += 1;
                continue;
            }
            if (!current) { i += 1; continue; }
            if (line === "•") {
                const note = normalizePdfField(lines[i + 1] || "");
                if (note) current.notes.push(note);
                i += 2;
                continue;
            }
            const parsed = pdfParseProcedureTokens(lines, i);
            if (parsed) {
                current.procedures.push(parsed.row);
                i = parsed.nextIndex;
                continue;
            }
            i += 1;
        }

        for (const group of groups) {
            group.notes = uniqueStrings(group.notes);
            const deduped = new Map();
            for (const row of group.procedures) {
                if (!deduped.has(row.procedure_code)) deduped.set(row.procedure_code, row);
            }
            group.procedures = [...deduped.values()];
            group.procedure_codes = group.procedures.map(row => row.procedure_code);
        }
        return groups;
    }

    function buildFaxbackAdditionalNotes(pages) {
        const page3 = toArray(pages[2]?.lines).map(normalizePdfText).filter(Boolean);
        const orthoIndex = pdfLineIndex(page3, /^Orthodontic Services$/i);
        const page3Notes = orthoIndex >= 0 ? page3.slice(orthoIndex + 1) : [];
        const page4 = toArray(pages[3]?.lines).map(normalizePdfText).filter(Boolean);
        const sourceLines = [...page3Notes.map(text => ({ text, page: 3 })), ...page4.map(text => ({ text, page: 4 }))];
        const notes = [];
        const noteEvidence = [];
        for (let i = 0; i < sourceLines.length; i += 1) {
            const { text: line, page } = sourceLines[i];
            if (/^Patient Name:/i.test(line) || /^Client\/Sub-Client #:/i.test(line) || /^Relationship:/i.test(line) || /^mbb_/i.test(line) || /^Page$/i.test(line) || /^\d+$/i.test(line)) continue;

            // The PDF wraps this sentence over two text chunks. Reassemble it so
            // the JSON contains the complete source sentence exactly once.
            if (/^X-rays are required when submitting claims for fixed bridges/i.test(line)) {
                let combined = line;
                if (sourceLines[i + 1]?.page === page && /^with a self-addressed stamped envelope\.$/i.test(sourceLines[i + 1]?.text || "")) {
                    combined += ` ${sourceLines[i + 1].text}`;
                    i += 1;
                }
                const normalized = normalizePdfField(combined);
                notes.push(normalized);
                noteEvidence.push({ page, text: normalized });
                continue;
            }
            const normalized = normalizePdfField(line);
            notes.push(normalized);
            noteEvidence.push({ page, text: normalized });
        }
        const legacyNotes = cleanSectionNotes(notes.filter(Boolean));
        const dedupedEvidence = [];
        const seenEvidence = new Set();
        for (const item of noteEvidence.filter(item => item.text && legacyNotes.some(note => note.toLowerCase().includes(item.text.toLowerCase())))) {
            const key = `${item.page}|${item.text.toLowerCase()}`;
            if (!seenEvidence.has(key)) { seenEvidence.add(key); dedupedEvidence.push(item); }
        }
        return { notes: legacyNotes, evidence: dedupedEvidence };
    }

    function pdfBenefitBreakdownNoticeText(page1Lines) {
        const lines = toArray(page1Lines);
        const start = lines.findIndex(line => /^Benefit Breakdown$/i.test(line));
        if (start < 0) return "";
        const stop = lines.findIndex((line, idx) => {
            if (idx <= start) return false;
            const text = normalizePdfText(line);
            return /^mbb_/i.test(text) || /^(?:PPO Dentist|Premier Dentist|Nonparticipating Dentist)\b/i.test(text) ||
                /^D\d{4}$/i.test(text) || /^%$/.test(text) || /^Waiting Period$/i.test(text);
        });
        return lines.slice(start + 1, stop >= 0 ? stop : undefined).join(" ");
    }

    function buildFaxbackDocumentModel(pages) {
        const page1 = toArray(pages[0]?.lines);
        const page1Text = page1.join(" ");
        const eligibility = pdfParseEligibility(page1);
        const officeVisit = parsePdfOfficeVisit(page1);
        const groups = buildFaxbackBenefitGroups(pages);
        const additionalNoteData = buildFaxbackAdditionalNotes(pages);
        const additionalNotes = additionalNoteData.notes;
        const benefitPages = [...toArray(pages[0]?.lines).slice(pdfLineIndex(page1, /^Benefit Breakdown$/i) + 1), ...toArray(pages).slice(1).flatMap(page => toArray(page?.lines))];
        const sourceProcedureCodes = uniqueStrings(benefitPages.filter(line => /^D\d{4}$/i.test(normalizePdfText(line))).map(line => normalizePdfText(line).toUpperCase()));
        const parsedProcedureCodes = new Set(groups.flatMap(group => group.procedure_codes || []));
        const sourceProcedureOmissions = sourceProcedureCodes.filter(code => !parsedProcedureCodes.has(code)).map(code => ({
            procedure_code: code,
            reason: "SOURCE_CODE_NOT_PARSED_INTO_A_BENEFIT_ROW",
            source: "faxback_pdf"
        }));
        const sourceRoutineCount = toArray(officeVisit.procedures).filter(item => isPpoNetworkLabel(item?.network)).length;
        const sourceLimitationCount = toArray(pages).slice(1).flatMap(page => toArray(page?.lines)).filter(line => normalizePdfText(line) === "•").length;
        const allSourceLines = pages.flatMap(page => toArray(page?.lines)).map(normalizePdfText);
        const benefitBreakdownNotice = normalizePdfField(pdfBenefitBreakdownNoticeText(page1));
        return {
            eligibility,
            office_visit: officeVisit,
            benefit_breakdown: {
                networks: ["PPO Dentist", "Premier Dentist", "Nonparticipating Dentist"],
                notice: benefitBreakdownNotice || null,
                categories: groups
            },
            additional_information: {
                notes: additionalNotes
            },
            additional_note_evidence: additionalNoteData.evidence,
            source_inventory: {
                procedure_codes: sourceProcedureCodes,
                procedure_row_omission_reasons: sourceProcedureOmissions,
                office_visit_procedure_count: sourceRoutineCount,
                limitation_note_count: sourceLimitationCount,
                facts_present: {
                    member_name: allSourceLines.some(line => /^Member Name:$/i.test(line)),
                    patient_name: allSourceLines.some(line => /^Patient Name:$/i.test(line)),
                    relationship: allSourceLines.some(line => /^Relationship:$/i.test(line)),
                    eligibility: allSourceLines.some(line => /^Currently Eligible:$/i.test(line)),
                    client_name: allSourceLines.some(line => /^Client Name:$/i.test(line)),
                    client_number: allSourceLines.some(line => /^Client Number:$/i.test(line)),
                    product: allSourceLines.some(line => /^Product:$/i.test(line)),
                    claims_mailing_address: allSourceLines.some(line => /^Claims Mailing Address$/i.test(line)),
                    payer_id: allSourceLines.some(line => /^Payer ID$/i.test(line)),
                    cob: allSourceLines.some(line => /^Coordination of Benefits$/i.test(line)),
                    maximums: allSourceLines.some(line => /^Maximum and Deductibles$/i.test(line)),
                    deductibles: allSourceLines.some(line => /^Deductible$/i.test(line)),
                    benefit_periods: allSourceLines.some(line => /^\d{2}\/\d{2}\/\d{4}\s+to\s+\d{2}\/\d{2}\/\d{4}$/i.test(line)),
                    office_visit: allSourceLines.some(line => /^Office Visit$/i.test(line))
                }
            },
            parse_warnings: groups.length && sourceProcedureCodes.length ? [] : ["No benefit-breakdown procedure groups or procedure rows could be parsed from the Faxback PDF."]
        };
    }

    const PDF_ROUTINE_CODES = Object.freeze({
        "Exam": "D0120",
        "Adult Cleaning": "D1110",
        "Child Cleaning": "D1120",
        "Perio Maintenance Cleaning": "D4910",
        "Bitewings": "D0272",
        "Full Mouth X-rays": "D0210",
        "Fluoride": "D1208",
        "Occlusal Guard": "D9944"
    });

    function pdfProcedureRows(pdfModel) {
        const rows = [];
        for (const group of toArray(pdfModel?.benefit_breakdown?.categories)) {
            for (const item of toArray(group?.procedures)) {
                const coverage = item?.coverage?.["PPO Dentist"] || {};
                rows.push({
                    procedureCode: item.procedure_code,
                    description: item.description,
                    category: group.category,
                    percentCovered: coverage.percent || null,
                    waitingPeriod: coverage.waiting_period || null,
                    waitingPeriodMetDate: coverage.met_date || null,
                    medicallyNecessary: null,
                    radioGraphsRequired: null,
                    remarksRequired: null,
                    status: /^(not covered|0%)$/i.test(coverage.percent || "") ? "Not Covered" : (coverage.percent === "Optional" ? "Optional" : "Covered"),
                    limitations: [],
                    pdf_coverage_by_network: item?.coverage || {}
                });
            }
        }
        return rows;
    }

    function toolkitProcedureResult(code, rawByCode, procedureErrors) {
        const error = procedureErrors?.get?.(code) || rawByCode?.__errors?.get?.(code) || null;
        const errorDetail = rawByCode?.__errorDetails?.get?.(code) || null;
        const value = rawByCode?.get?.(code);
        const response = value?.response || value;
        const bucket = toArray(response).find(isExactPpoBucket);
        if (!bucket) {
            const failureKind = errorDetail?.failure_kind || (value && value.http_status >= 200 && value.http_status < 300 ? "NO_PPO_BUCKET" : error ? "REQUEST_FAILED" : null);
            const unavailableKinds = new Set(["NO_PPO_BUCKET", "INVALID_JSON"]);
            const notInCodeList = failureKind === "NOT_IN_PORTAL_CODE_LIST";
            const status = notInCodeList ? "NOT_IN_CODE_LIST"
                : unavailableKinds.has(failureKind) || (!error && value) ? "UNAVAILABLE" : error ? "FAILED" : "UNAVAILABLE";
            const historyStatus = status === "FAILED" ? "REQUEST_FAILED" : value ? "NOT_RETURNED" : "UNKNOWN";
            return {
                procedureCode: code,
                httpStatus: value?.http_status ?? errorDetail?.http_status ?? null,
                status,
                failure_kind: failureKind,
                procedurePath: [],
                percentCovered: null,
                waitingPeriod: null,
                waitingPeriodMetDate: null,
                medicallyNecessary: null,
                limitations: [],
                radioGraphsRequired: null,
                remarksRequired: null,
                utilization_history_status: historyStatus,
                utilization_source_present: false,
                error: notInCodeList
                    ? "Not in the Toolkit's procedure code list (HTTP 404)."
                    : error || (value ? "No usable PPO Dentist benefit bucket was returned for this code." : "Toolkit procedure response was unavailable.")
            };
        }

        const nodes = toArray(bucket.coverages);
        const leaf = nodes.find(node => normalizeCode(node?.procedureId || node?.procedure) === code)
            || [...nodes].sort((a, b) => Number(a?.level || 0) - Number(b?.level || 0)).at(-1)
            || {};
        const path = nodes.slice().sort((a, b) => Number(a?.level || 0) - Number(b?.level || 0));
        const percent = leaf?.coverage?.percent ?? null;
        // Service history (utilization) and the category-level rules that apply to this
        // code, so the audit checklist can read frequency / age / history per code.
        const utilizationPropertyPresent = nodes.some(node => Object.prototype.hasOwnProperty.call(node || {}, "utilizationBenefits"));
        const utilization = nodes.flatMap(node => toArray(node?.utilizationBenefits));
        const utilizationDates = collectDates(utilization);
        const utilizationHistoryStatus = utilizationDates.length
            ? "PRESENT_DATES"
            : !utilizationPropertyPresent
                ? "NOT_RETURNED"
                : utilization.length === 0
                    ? "EXPLICIT_EMPTY"
                    : "PARSE_FAILED";
        const applicableLimitations = selectApplicableRules(code, nodes, leaf);
        return {
            procedureCode: code,
            httpStatus: value?.http_status ?? null,
            status: error ? "FAILED" : "OK",
            procedurePath: path.map(node => ({
                level: node?.level ?? null,
                procedure: node?.procedure ?? null,
                procedureId: node?.procedureId ?? null
            })),
            percentCovered: percent === null || percent === undefined ? null : String(percent),
            waitingPeriod: leaf?.waitingPeriods ?? null,
            waitingPeriodMetDate: leaf?.waitingPeriodMetDate ?? null,
            medicallyNecessary: leaf?.coverage?.medicallyNecessary ?? null,
            limitations: path.filter(node => normalizeCode(node?.procedureId || node?.procedure) === code && toArray(node?.exclusionsAndLimitations).length).map(node => ({
                level: node?.level ?? null,
                procedure: node?.procedure ?? null,
                procedureId: node?.procedureId ?? null,
                exclusionsAndLimitations: toArray(node?.exclusionsAndLimitations)
            })),
            radioGraphsRequired: leaf?.radioGraphsRequired ?? null,
            remarksRequired: leaf?.remarksRequired ?? null,
            applicable_limitations: applicableLimitations,
            utilization_history: utilizationDates,
            utilization_history_status: error ? "REQUEST_FAILED" : utilizationHistoryStatus,
            utilization_source_present: utilizationPropertyPresent,
            ...(utilization.length ? { utilization_benefits: sanitizeForOutput(utilization) } : {}),
            error: error || null
        };
    }

    function pdfResultForProcedure(row) {
        return {
            procedureCode: row.procedureCode,
            description: row.description,
            httpStatus: null,
            status: row.status,
            api_status: "NOT_REQUESTED",
            result_source: "PDF_ONLY",
            procedurePath: [
                { level: 1, procedure: row.category, procedureId: null },
                { level: 2, procedure: row.procedureCode, procedureId: row.procedureCode }
            ],
            percentCovered: row.percentCovered,
            waitingPeriod: row.waitingPeriod,
            waitingPeriodMetDate: row.waitingPeriodMetDate,
            medicallyNecessary: null,
            limitations: row.limitations,
            radioGraphsRequired: null,
            remarksRequired: null,
            error: null
        };
    }

    function sameCoverageValue(first, second) {
        const normalize = value => {
            const text = cleanText(String(value ?? "")).toLowerCase();
            const number = text.match(/^(\d+(?:\.\d+)?)%?$/)?.[1];
            return number === undefined ? text : `${Number(number)}%`;
        };
        return normalize(first) === normalize(second);
    }

    function mergeProcedureResults(pdfModel, rawByCode, procedureErrors, toolkitResults = []) {
        const pdfRows = new Map(pdfProcedureRows(pdfModel).map(row => [row.procedureCode, row]));
        const toolkitCodes = [...PROCEDURE_CODES];
        const storedToolkit = new Map(toArray(toolkitResults).map(row => [row.procedureCode, row]));
        const allCodes = [...new Set([...toolkitCodes, ...pdfRows.keys()])];
        const conflicts = [];
        const results = allCodes.map(code => {
            const toolkit = toolkitCodes.includes(code)
                ? (rawByCode?.has?.(code) || procedureErrors?.has?.(code)
                    ? toolkitProcedureResult(code, rawByCode, procedureErrors)
                    : storedToolkit.get(code) || toolkitProcedureResult(code, rawByCode, procedureErrors))
                : null;
            const pdfRow = pdfRows.get(code);
            if (!pdfRow) return toolkit;
            const pdf = pdfResultForProcedure(pdfRow);
            if (toolkit?.percentCovered && pdf.percentCovered && !sameCoverageValue(toolkit.percentCovered, pdf.percentCovered)) {
                conflicts.push({
                    fact_key: `procedure:${code}:percentCovered`,
                    canonical_source: "Faxback PDF",
                    toolkit_value: toolkit.percentCovered,
                    pdf_value: pdf.percentCovered
                });
            }
            if (toolkit?.waitingPeriod && pdf.waitingPeriod && cleanText(toolkit.waitingPeriod) !== cleanText(pdf.waitingPeriod)) {
                conflicts.push({
                    fact_key: `procedure:${code}:waitingPeriod`,
                    canonical_source: "Faxback PDF",
                    toolkit_value: toolkit.waitingPeriod,
                    pdf_value: pdf.waitingPeriod
                });
            }
            if (toolkit?.waitingPeriodMetDate && pdf.waitingPeriodMetDate && cleanText(toolkit.waitingPeriodMetDate) !== cleanText(pdf.waitingPeriodMetDate)) {
                conflicts.push({
                    fact_key: `procedure:${code}:waitingPeriodMetDate`,
                    canonical_source: "Faxback PDF",
                    toolkit_value: toolkit.waitingPeriodMetDate,
                    pdf_value: pdf.waitingPeriodMetDate
                });
            }
            const limitationMap = new Map();
            for (const item of [...toArray(toolkit?.limitations), ...toArray(pdf.limitations)]) {
                const key = `${item.procedureId || item.procedure || ""}|${toArray(item.exclusionsAndLimitations).map(cleanText).join("|").toLowerCase()}`;
                if (!limitationMap.has(key)) limitationMap.set(key, item);
            }
            return {
                ...(toolkit || {}),
                ...pdf,
                httpStatus: toolkit?.httpStatus ?? pdf.httpStatus,
                procedurePath: toolkit?.procedurePath?.length ? toolkit.procedurePath : pdf.procedurePath,
                percentCovered: pdf.percentCovered ?? toolkit?.percentCovered ?? null,
                waitingPeriod: pdf.waitingPeriod ?? toolkit?.waitingPeriod ?? null,
                waitingPeriodMetDate: pdf.waitingPeriodMetDate ?? toolkit?.waitingPeriodMetDate ?? null,
                medicallyNecessary: pdf.medicallyNecessary ?? toolkit?.medicallyNecessary ?? null,
                radioGraphsRequired: pdf.radioGraphsRequired ?? toolkit?.radioGraphsRequired ?? null,
                remarksRequired: pdf.remarksRequired ?? toolkit?.remarksRequired ?? null,
                error: toolkit?.error || null,
                api_status: toolkit?.status || "NOT_REQUESTED",
                result_source: toolkit?.status === "OK" ? "API_AND_PDF" : (toolkit?.status === "FAILED" ? "PDF_WITH_API_FAILURE" : "PDF_WITH_API_UNAVAILABLE"),
                source_values: {
                    api: toolkit ? { percentCovered: toolkit.percentCovered ?? null, waitingPeriod: toolkit.waitingPeriod ?? null, waitingPeriodMetDate: toolkit.waitingPeriodMetDate ?? null, status: toolkit.status, httpStatus: toolkit.httpStatus ?? null } : null,
                    pdf: { percentCovered: pdf.percentCovered ?? null, waitingPeriod: pdf.waitingPeriod ?? null, waitingPeriodMetDate: pdf.waitingPeriodMetDate ?? null, description: pdf.description ?? null }
                },
                limitations: [...limitationMap.values()],
            };
        });
        return { results, conflicts, requestedCodes: toolkitCodes };
    }

    function limitationSubjectKey(value) {
        return cleanText(String(value || "").toLowerCase()
            .replace(/\b\d+(?:\.\d+)?\b/g, " ")
            .replace(/\b(?:once|twice|times?|per|each|every|calendar|consecutive|rolling|year|years|month|months|lifetime|age|and|under|within|any|for|are|is|the|a|an|of|to|on|in|at|be|payable|limited|limited\s+to)\b/g, " ")
            .replace(/[^a-z]+/g, " ")).trim();
    }

    function mergeCategoryRows(toolkitRows, pdfModel, fieldName, conflicts = []) {
        const output = new Map();
        const add = row => {
            const key = cleanText(row?.procedure || row?.procedureId || "").toLowerCase();
            if (key && !output.has(key)) output.set(key, row);
        };
        for (const row of toArray(toolkitRows)) add(row);
        if (fieldName === "exclusionsAndLimitations") {
            for (const group of toArray(pdfModel?.benefit_breakdown?.categories)) {
                const wording = uniqueStrings([
                    ...toArray(output.get(cleanText(group.category).toLowerCase())?.exclusionsAndLimitations),
                    ...toArray(group.notes)
                ]);
                if (wording.length) add({ procedure: group.category, procedureId: null, exclusionsAndLimitations: wording });
            }
        }
        return [...output.values()].map(row => {
            if (fieldName !== "exclusionsAndLimitations") return row;
            const group = toArray(pdfModel?.benefit_breakdown?.categories).find(item => cleanText(item.category).toLowerCase() === cleanText(row.procedure).toLowerCase());
            if (!group) return { ...row, exclusionsAndLimitations: mergeLimitationWording(row.exclusionsAndLimitations, [], conflicts, row.procedure) };
            return {
                ...row,
                exclusionsAndLimitations: mergeLimitationWording(row.exclusionsAndLimitations, group.notes, conflicts, group.category)
            };
        });
    }

    function pdfRoutineRows(pdfModel, procedureResults) {
        const resultByCode = new Map(toArray(procedureResults).map(row => [row.procedureCode, row]));
        return toArray(pdfModel?.office_visit?.procedures).filter(item => isPpoNetworkLabel(item?.network)).map(item => {
            const code = PDF_ROUTINE_CODES[item.procedure];
            const coverage = resultByCode.get(code)?.percentCovered;
            const dates = uniqueStrings(item.service_dates || []);
            return {
                procedureCode: code || null,
                description: item.procedure,
                percentCovered: coverage && /^\d+(?:\.\d+)?%?$/.test(coverage) ? Number(coverage.replace("%", "")) : null,
                eligibleNow: item.eligible_now,
                serviceDates: dates,
                numberOfRemainingRadiographs: null,
                statusDetail: item.status_detail || null
            };
        });
    }

    function toolkitRoutineRows(routineBuckets) {
        return toArray(routineBuckets).flatMap(bucket => toArray(bucket?.routineProcedures)).map(item => {
            const description = item?.description ?? item?.procedure ?? null;
            return {
                procedureCode: normalizeCode(item?.procedureCode || item?.procedureId) || PDF_ROUTINE_CODES[description] || null,
                description,
                percentCovered: item?.percentCovered ?? item?.coverage?.percent ?? null,
                eligibleNow: item?.eligibleNow ?? item?.isCovered ?? null,
                serviceDates: toArray(item?.serviceDates),
                numberOfRemainingRadiographs: item?.numberOfRemainingRadiographs ?? null,
                statusDetail: item?.statusDetail ?? null
            };
        }).filter(row => row.procedureCode || row.description);
    }

    function mergeRoutineRows(toolkitRows, pdfRows, conflicts) {
        const rows = new Map();
        for (const row of toArray(toolkitRows)) {
            const code = cleanText(row?.procedureCode || "").toUpperCase();
            if (code && !rows.has(code)) rows.set(code, row);
        }
        for (const row of toArray(pdfRows)) {
            const code = cleanText(row?.procedureCode || "").toUpperCase();
            if (!code) continue;
            const existing = rows.get(code);
            if (existing) {
                for (const key of ["eligibleNow", "percentCovered"]) {
                    const toolkitValue = existing[key];
                    const pdfValue = row[key];
                    if (toolkitValue !== null && toolkitValue !== undefined && pdfValue !== null && pdfValue !== undefined && !sameCoverageValue(toolkitValue, pdfValue)) {
                        conflicts.push({
                            fact_key: `routine_procedure:${code}:${key}`,
                            canonical_source: "Faxback PDF",
                            toolkit_value: toolkitValue,
                            pdf_value: pdfValue
                        });
                    }
                }
            }
            rows.set(code, {
                ...existing,
                ...row,
                description: row.description ?? existing?.description ?? null,
                percentCovered: row.percentCovered ?? existing?.percentCovered ?? null,
                eligibleNow: row.eligibleNow ?? existing?.eligibleNow ?? null,
                serviceDates: uniqueStrings([...toArray(existing?.serviceDates), ...toArray(row.serviceDates)]),
                numberOfRemainingRadiographs: row.numberOfRemainingRadiographs ?? existing?.numberOfRemainingRadiographs ?? null,
                statusDetail: row.statusDetail ?? existing?.statusDetail ?? null
            });
        }
        return [...rows.values()];
    }

    function pdfMaximumRows(pdfModel) {
        const values = pdfModel?.eligibility?.maximum_and_deductibles || {};
        const general = values.maximums?.general || {};
        const ortho = values.maximums?.orthodontic || {};
        const generalPeriod = values.benefit_periods?.general || null;
        const orthoPeriod = values.benefit_periods?.orthodontic || null;
        const parsePeriod = value => {
            const match = String(value || "").match(/(\d{2}\/\d{2}\/\d{4})\s+to\s+(\d{2}\/\d{2}\/\d{4})/i);
            return { from: match?.[1] || null, to: match?.[2] || null };
        };
        const makeMaximum = (category, data, period, description, isLifetime = false) => {
            if (data?.individual_max === null || data?.individual_max === undefined) return null;
            const dates = parsePeriod(period);
            return {
                type: "Maximum", category, name: category, categoryHistoryAccumulator: null,
                individual: { amount: data.individual_max, used: data.individual_used, remaining: data.individual_used === null ? null : Math.max(0, data.individual_max - data.individual_used) },
                family: { amount: data.family_max ?? null, used: data.family_used ?? null, remaining: data.family_max === null || data.family_used === null ? null : Math.max(0, data.family_max - data.family_used) },
                from: dates.from, to: dates.to, isLifetime, isMaximum: true, description: description || null
            };
        };
        const rows = [
            makeMaximum("Orthodontic", ortho, orthoPeriod, values.applies_to?.orthodontic, true),
            makeMaximum("General", general, generalPeriod, values.applies_to?.general)
        ].filter(Boolean);
        const deductible = values.deductible || {};
        const deductiblePeriod = parsePeriod(deductible.benefit_period);
        if (deductible.individual?.amount != null || deductible.family?.amount != null) {
            rows.push({
                type: "Deductible", category: "General", name: "General", categoryHistoryAccumulator: null,
                individual: { amount: deductible.individual?.amount ?? null, used: deductible.individual?.used ?? null, remaining: deductible.individual?.remaining ?? null },
                family: { amount: deductible.family?.amount ?? null, used: deductible.family?.used ?? null, remaining: deductible.family?.remaining ?? null },
                from: deductiblePeriod.from, to: deductiblePeriod.to, isLifetime: false, isMaximum: false,
                description: deductible.applies_to || null
            });
        }
        return rows;
    }

    function deduplicateAccumulatorRows(rows) {
        const stableValue = value => {
            if (Array.isArray(value)) return value.map(stableValue);
            if (!value || typeof value !== "object") return value;
            return Object.fromEntries(Object.keys(value).sort().map(key => [key, stableValue(value[key])]));
        };
        const seen = new Set();
        const output = [];
        for (const row of toArray(rows)) {
            if (!row || typeof row !== "object") continue;
            const key = JSON.stringify(stableValue(row));
            if (seen.has(key)) continue;
            seen.add(key);
            output.push(row);
        }
        return output;
    }

    function accumulatorComparisonKey(row) {
        return [row?.type, row?.category, row?.name, row?.from, row?.to, row?.isLifetime, row?.isMaximum]
            .map(value => cleanText(String(value ?? "")).toLowerCase())
            .join("|");
    }

    function mergeAccumulatorRows(toolkitRows, pdfRows, conflicts) {
        // Maximums/deductibles must come from the live Toolkit website, whose table is clearer
        // and exposes the family/individual values directly. The faxback PDF is comparison-only;
        // it must never add a row or fill a missing website value.
        const websiteRows = deduplicateAccumulatorRows(toolkitRows);
        const websiteByKey = new Map(websiteRows.map(row => [accumulatorComparisonKey(row), row]));
        for (const pdfRow of toArray(pdfRows)) {
            const websiteRow = websiteByKey.get(accumulatorComparisonKey(pdfRow));
            if (!websiteRow) continue;
            for (const memberType of ["individual", "family"]) {
                for (const amountKey of ["amount", "used", "remaining"]) {
                    const websiteValue = websiteRow?.[memberType]?.[amountKey];
                    const pdfValue = pdfRow?.[memberType]?.[amountKey];
                    if (websiteValue !== null && websiteValue !== undefined && pdfValue !== null && pdfValue !== undefined && Number(websiteValue) !== Number(pdfValue)) {
                        conflicts.push({
                            fact_key: `maximum_deductible:${pdfRow.type}:${pdfRow.category}:${memberType}.${amountKey}`,
                            canonical_source: "Toolkit Website",
                            toolkit_value: websiteValue,
                            pdf_value: pdfValue
                        });
                    }
                }
            }
        }
        return websiteRows;
    }

    function validateFaxbackCompleteness(pdfModel, canonical) {
        const missing = [];
        const eligibility = pdfModel?.eligibility || {};
        const factsPresent = pdfModel?.source_inventory?.facts_present || {};
        const selected = canonical?.member_details?.selectedMember || {};
        const memberNames = toArray(canonical?.member_details?.members).map(member => member.patientName);
        const client = canonical?.more_information?.client_benefit_information?.display_fields || {};
        const addresses = canonical?.more_information?.claim_and_inquiry_mailing_addresses || {};
        const cob = canonical?.more_information?.cob_information?.cobConfig || {};
        const maxRows = toArray(canonical?.maximums_and_deductibles?.rows);
        const routine = new Map(toArray(canonical?.routine_procedures?.rows).map(row => [row.procedureCode, row]));
        const procedures = new Map(toArray(canonical?.coverages?.procedure_code_search?.results).map(row => [row.procedureCode, row]));
        const has = (pathValue, expected) => expected === null || expected === undefined || expected === "" || String(pathValue ?? "").toLowerCase().includes(String(expected).toLowerCase());
        if (pdfModel && toArray(pdfModel.parse_warnings).length) missing.push(...toArray(pdfModel.parse_warnings));
        if (factsPresent.member_name && !eligibility.member_name) missing.push("member name");
        if (factsPresent.patient_name && !eligibility.patient_name) missing.push("patient name");
        if (factsPresent.relationship && !eligibility.relationship) missing.push("relationship");
        if (factsPresent.eligibility && !eligibility.currently_eligible) missing.push("eligibility");
        if (factsPresent.client_name && !eligibility.client_name) missing.push("client name");
        if (factsPresent.client_number && !eligibility.client_number) missing.push("client number");
        if (factsPresent.product && !eligibility.product) missing.push("product");
        if (factsPresent.claims_mailing_address && !eligibility.claims_mailing_address?.street) missing.push("claims mailing address");
        if (factsPresent.payer_id && !toArray(eligibility.claims_mailing_address?.payer_ids).length) missing.push("payer ID");
        if (factsPresent.cob && (!eligibility.coordination_of_benefits?.internal || !eligibility.coordination_of_benefits?.external)) missing.push("coordination of benefits");
        if (factsPresent.maximums && maxRows.length === 0) missing.push("maximum values");
        if (factsPresent.deductibles && !maxRows.some(row => row.type === "Deductible")) missing.push("deductible values");
        if (factsPresent.benefit_periods && !maxRows.some(row => row.from && row.to)) missing.push("benefit period");
        if (!has(selected.patientName, eligibility.patient_name)) missing.push("member/patient information: patient name");
        if (eligibility.member_name && !memberNames.some(name => cleanText(name).toLowerCase() === cleanText(eligibility.member_name).toLowerCase())) missing.push("member/patient information: member name");
        if (!has(selected.relationship, eligibility.relationship)) missing.push("member/patient information: relationship");
        const pdfEligibilityStatus = eligibility.currently_eligible?.match(/^(Yes|No)\b/i)?.[1];
        if (!has(selected.currentlyEligible, pdfEligibilityStatus)) missing.push("eligibility status");
        if (!has(selected.effectiveDate, eligibility.currently_eligible?.match(/\d{2}\/\d{2}\/\d{4}/)?.[0])) missing.push("eligibility effective date");
        if (!has(client.clientName || client.subGroupName, eligibility.client_name)) missing.push("client information: client name");
        if (!has(client.clientNumber, eligibility.client_number)) missing.push("client information: client number");
        if (!has(client.product, eligibility.product)) missing.push("client information: product");
        const payerIds = String(addresses.payorId || "").split(/,\s*/).filter(Boolean);
        if (toArray(eligibility.claims_mailing_address?.payer_ids).some(id => !payerIds.includes(id))) missing.push("payer ID");
        if (!has(addresses.claimMailingAddress?.street, eligibility.claims_mailing_address?.street)) missing.push("claims mailing address");
        if (eligibility.coordination_of_benefits?.internal && cob.internalCOBIndicator !== (eligibility.coordination_of_benefits.internal.toLowerCase() === "yes")) missing.push("internal COB");
        if (eligibility.coordination_of_benefits?.external && cob.externalCOBIndicator !== (eligibility.coordination_of_benefits.external.toLowerCase() === "yes")) missing.push("external COB");
        const max = eligibility.maximum_and_deductibles || {};
        if (max.maximums?.general?.individual_max != null && !maxRows.some(row => row.type === "Maximum" && row.category === "General" && row.individual?.amount === max.maximums.general.individual_max)) missing.push("general maximum");
        if (max.deductible?.individual?.amount != null && !maxRows.some(row => row.type === "Deductible" && row.individual?.amount === max.deductible.individual.amount)) missing.push("individual deductible");
        if (max.deductible?.family?.amount != null && !maxRows.some(row => row.type === "Deductible" && row.family?.amount === max.deductible.family.amount)) missing.push("family deductible");
        if (max.benefit_periods?.general && !maxRows.some(row => row.from && row.to && max.benefit_periods.general.includes(row.from) && max.benefit_periods.general.includes(row.to))) missing.push("general benefit period");
        const containsText = (list, text) => toArray(list).some(item => cleanText(item).toLowerCase().includes(cleanText(text).toLowerCase().replace(/[\s,;:.-]+$/, "")));
        for (const detail of toArray(max.details)) if (!containsText(canonical?.maximums_and_deductibles?.notes, detail)) missing.push(`maximum detail: ${detail}`);
        for (const item of toArray(pdfModel?.office_visit?.procedures).filter(entry => isPpoNetworkLabel(entry?.network))) {
            const code = PDF_ROUTINE_CODES[item.procedure];
            if (!routine.has(code)) missing.push(`routine procedure: ${item.procedure}`);
            else if (routine.get(code).eligibleNow !== item.eligible_now) missing.push(`routine status: ${item.procedure}`);
            else if (item.status_detail && !has(routine.get(code).statusDetail, item.status_detail)) missing.push(`routine detail: ${item.procedure}`);
        }
        for (const row of pdfProcedureRows(pdfModel)) {
            const present = procedures.get(row.procedureCode);
            if (!present) missing.push(`procedure ${row.procedureCode}: missing`);
            else {
                if (!has(present.description, row.description)) missing.push(`procedure ${row.procedureCode}: description`);
                if (!sameCoverageValue(present.percentCovered, row.percentCovered)) missing.push(`procedure ${row.procedureCode}: coverage percentage`);
                if (!has(present.waitingPeriod, row.waitingPeriod)) missing.push(`procedure ${row.procedureCode}: waiting period`);
                if (present.status !== row.status) missing.push(`procedure ${row.procedureCode}: coverage status`);
            }
        }
        const parsedCodes = new Set(pdfProcedureRows(pdfModel).map(row => row.procedureCode));
        for (const code of toArray(pdfModel?.source_inventory?.procedure_codes)) if (!parsedCodes.has(code)) missing.push(`PDF procedure row: ${code}`);
        if (Number.isFinite(pdfModel?.source_inventory?.office_visit_procedure_count) &&
            routine.size < pdfModel.source_inventory.office_visit_procedure_count) missing.push("PDF routine/office-visit procedure rows");
        const limitationCount = toArray(pdfModel?.benefit_breakdown?.categories).reduce((sum, group) => sum + toArray(group.notes).length, 0);
        if (Number.isFinite(pdfModel?.source_inventory?.limitation_note_count) && limitationCount < pdfModel.source_inventory.limitation_note_count) missing.push("PDF frequency/limitation notes");
        for (const group of toArray(pdfModel?.benefit_breakdown?.categories)) {
            const records = toArray(canonical?.exclusions_and_limitations?.records).filter(row => cleanText(row.procedure).toLowerCase() === cleanText(group.category).toLowerCase());
            for (const wording of toArray(group.notes)) if (!records.some(row => containsText(row.exclusionsAndLimitations, wording))) missing.push(`limitation/exclusion: ${group.category}: ${wording}`);
        }
        for (const note of toArray(pdfModel?.additional_information?.notes)) {
            const corpus = JSON.stringify(canonical?.ortho_information || {}) + JSON.stringify(canonical?.more_information || {});
            if (!corpus.toLowerCase().includes(cleanText(note).toLowerCase())) missing.push(`special plan information: ${note}`);
        }
        return uniqueStrings(missing);
    }

    function normalizePdfIntoCanonicalSections(pdfModel, toolkit = {}) {
        const procedures = mergeProcedureResults(pdfModel, toolkit.rawByCode, toolkit.procedureErrors, toolkit.procedureResults);
        const conflicts = [...procedures.conflicts];
        const toolkitRows = toArray(toolkit.coverageRows);
        const coverageRows = mergeCategoryRows(toolkitRows, pdfModel, "coverage");
        const exclusions = mergeCategoryRows(toolkit.exclusionRows, pdfModel, "exclusionsAndLimitations", conflicts);
        const maxRows = mergeAccumulatorRows(toolkit.maximumRows, pdfMaximumRows(pdfModel), conflicts);
        const routineRows = mergeRoutineRows(toolkit.routineRows, pdfRoutineRows(pdfModel, procedures.results), conflicts);
        const fields = pdfModel?.eligibility || {};
        const addFactConflict = (factKey, toolkitValue, pdfValue) => {
            if (toolkitValue === null || toolkitValue === undefined || toolkitValue === "" || pdfValue === null || pdfValue === undefined || pdfValue === "") return;
            if (isNA(toolkitValue) || isNA(pdfValue)) return;
            if (cleanText(String(toolkitValue)).toLowerCase() === cleanText(String(pdfValue)).toLowerCase()) return;
            conflicts.push({ fact_key: factKey, canonical_source: "Faxback PDF", toolkit_value: toolkitValue, pdf_value: pdfValue });
        };
        const selectedMember = toolkit.memberDetails?.selectedMember || {};
        addFactConflict("member:patientName", selectedMember.patientName, fields.patient_name);
        addFactConflict("member:relationship", selectedMember.relationship, fields.relationship);
        addFactConflict("member:effectiveDate", selectedMember.effectiveDate, fields.currently_eligible?.match(/\d{2}\/\d{2}\/\d{4}/)?.[0]);
        addFactConflict("client:clientName", toolkit.clientFields?.clientName, fields.client_name);
        addFactConflict("client:clientName", toolkit.clientFields?.subGroupName, fields.client_name);
        addFactConflict("client:clientNumber", toolkit.clientFields?.clientNumber, fields.client_number);
        addFactConflict("client:product", toolkit.clientFields?.product, fields.product);
        addFactConflict("claims:payerIds", toArray(toolkit.mailingAddresses?.payerIds).join(", "), toArray(fields.claims_mailing_address?.payer_ids).join(", "));
        addFactConflict("claims:mailingAddress", toolkit.mailingAddresses?.claimMailingAddress?.street, fields.claims_mailing_address?.street);
        for (const type of ["internal", "external"]) {
            const toolkitValue = toolkit.cobConfig?.[`${type}COBIndicator`];
            const pdfValue = fields.coordination_of_benefits?.[type];
            if (pdfValue) addFactConflict(`cob:${type}`, toolkitValue, pdfValue.toLowerCase() === "yes");
        }
        const websiteNoteValue = label => {
            const pattern = new RegExp(`^${label}:\\s*(.+)$`, "i");
            for (const note of toArray(toolkit.clientNotes)) {
                const match = cleanText(note).match(pattern);
                if (match && cleanText(match[1])) return cleanText(match[1]);
            }
            return null;
        };
        const websitePayorId = websiteNoteValue("Payor ID");
        const websiteGroupName = websiteNoteValue("Group Name");
        const pdfClientNameMatchesSubgroup = Boolean(fields.client_name && toolkit.clientFields?.subGroupName &&
            cleanText(fields.client_name).toLowerCase() === cleanText(toolkit.clientFields.subGroupName).toLowerCase());
        const client = {
            section_title: "Client Benefit Information",
            notes: uniqueStrings([...(toolkit.clientNotes || []), fields.client_information, fields.overview_notice]),
            display_fields: {
                ...(toolkit.clientFields || {}),
                clientName: websiteGroupName || (pdfClientNameMatchesSubgroup ? null : (fields.client_name || toolkit.clientFields?.clientName || null)),
                clientNumber: fields.client_number || toolkit.clientFields?.clientNumber || null,
                product: fields.product || toolkit.clientFields?.product || null,
                plan: toolkit.clientFields?.plan ?? null,
                payor_plan_id: toolkit.clientFields?.payor_plan_id ?? websitePayorId ?? (toArray(toolkit.mailingAddresses?.payerIds)[0] || toolkit.mailingAddresses?.payorId || toArray(fields.claims_mailing_address?.payer_ids)[0] || null),
                payor_id: toolkit.clientFields?.payor_id ?? websitePayorId ?? (toArray(toolkit.mailingAddresses?.payerIds)[0] || toolkit.mailingAddresses?.payorId || toArray(fields.claims_mailing_address?.payer_ids)[0] || null),
                subGroupNumber: toolkit.clientFields?.subGroupNumber ?? null,
                subGroupName: toolkit.clientFields?.subGroupName || (pdfClientNameMatchesSubgroup ? fields.client_name : null) || null
            }
        };
        const cobConfig = { ...(toolkit.cobConfig || {}) };
        if (fields.coordination_of_benefits?.internal) cobConfig.internalCOBIndicator = fields.coordination_of_benefits.internal.toLowerCase() === "yes";
        if (fields.coordination_of_benefits?.external) cobConfig.externalCOBIndicator = fields.coordination_of_benefits.external.toLowerCase() === "yes";
        const address = fields.claims_mailing_address || {};
        const pdfCrownsNote = toolkit.orthoInformation?.crowns_bridges_dentures_payment_note ||
            toArray(pdfModel?.additional_information?.notes).find(note => /seat\/delivery date/i.test(note)) || null;
        const websiteMaximumNotes = cleanSectionNotes(toArray(toolkit.maximumNotes));
        const websiteCrownsNote = pdfCrownsNote ? websiteMaximumNotes.find(note => notesNearlyDuplicate(note, pdfCrownsNote)) || null : null;
        const crownsNote = websiteCrownsNote || pdfCrownsNote;
        const maximumNotes = websiteCrownsNote ? websiteMaximumNotes.filter(note => note !== websiteCrownsNote) : websiteMaximumNotes;
        const memberDetails = toolkit.memberDetails || { section_title: "All Family Members", members: [], selectedMember: null };
        if (fields.member_name && !cleanText(fields.member_name).toLowerCase().includes(cleanText(fields.patient_name).toLowerCase()) &&
            !toArray(memberDetails.members).some(member => cleanText(member.patientName).toLowerCase() === cleanText(fields.member_name).toLowerCase())) {
            memberDetails.members = [...toArray(memberDetails.members), {
                patientName: fields.member_name,
                birthdate: null,
                relationship: null,
                eligibility: null,
                effectiveDate: null,
                selected: false
            }];
        }
        if (memberDetails.selectedMember) {
            memberDetails.selectedMember = {
                ...memberDetails.selectedMember,
                patientName: fields.patient_name || memberDetails.selectedMember.patientName,
                relationship: fields.relationship || memberDetails.selectedMember.relationship,
                effectiveDate: fields.currently_eligible?.match(/\d{2}\/\d{2}\/\d{4}/)?.[0] || memberDetails.selectedMember.effectiveDate,
                currentlyEligible: fields.currently_eligible?.match(/^(Yes|No)\b/i)?.[1] || memberDetails.selectedMember.currentlyEligible || null
            };
        } else if (fields.patient_name) {
            memberDetails.selectedMember = {
                patientName: fields.patient_name,
                birthdate: null,
                relationship: fields.relationship || null,
                eligibility: null,
                effectiveDate: fields.currently_eligible?.match(/\d{2}\/\d{2}\/\d{4}/)?.[0] || null,
                currentlyEligible: fields.currently_eligible?.match(/^(Yes|No)\b/i)?.[1] || null,
                selected: true
            };
        }
        const canonical = {
            member_details: memberDetails,
            routine_procedures: {
                section_title: "Routine Procedures",
                network: "PPO Dentist",
                notes: cleanSectionNotes([...(toolkit.routineNotes || []), ...(pdfModel?.office_visit?.notes || [])]),
                rows: routineRows
            },
            coverages: {
                section_title: "Coverages",
                network: "PPO Dentist",
                notes: cleanSectionNotes([...(toolkit.coverageNotes || []), pdfModel?.benefit_breakdown?.notice]),
                coverage_rows: coverageRows,
                procedure_code_search: {
                    endpoint: toolkit.procedureEndpoint || PROCEDURE_SEARCH_PATH,
                    codes_requested: procedures.requestedCodes,
                    count: procedures.results.length,
                    successful_count: procedures.results.filter(row => !row.error).length,
                    failed_codes: procedures.results.filter(row => row.error && row.failure_kind !== "NOT_IN_PORTAL_CODE_LIST" && procedures.requestedCodes.includes(row.procedureCode)).map(row => row.procedureCode),
                    codes_not_in_portal: procedures.results.filter(row => row.failure_kind === "NOT_IN_PORTAL_CODE_LIST" && procedures.requestedCodes.includes(row.procedureCode)).map(row => row.procedureCode),
                    results: procedures.results
                }
            },
            exclusions_and_limitations: {
                section_title: "Exclusions And Limitations",
                network: "PPO Dentist",
                notes: [],
                records: exclusions
            },
            maximums_and_deductibles: {
                section_title: "Maximums and Deductibles",
                network: "PPO Dentist",
                notes: maximumNotes,
                accumulationPeriodType: toolkit.accumulationPeriodType || null,
                rows: maxRows
            },
            more_information: {
                ...(toolkit.moreInformation || {}),
                client_benefit_information: client,
                cob_information: {
                    section_title: "COB Information",
                    notes: cleanSectionNotes([
                        ...(toolkit.cobNotes || []),
                        fields.coordination_of_benefits?.narrative,
                        fields.coordination_of_benefits?.website ? `Website: ${fields.coordination_of_benefits.website}` : null
                    ]),
                    cobConfig
                },
                claim_and_inquiry_mailing_addresses: {
                    ...(toolkit.mailingAddresses || {}),
                    section_title: "Claim & Inquiry Mailing Addresses",
                    messages: cleanSectionNotes([...(toolkit.mailingNotes || []), address.payer_id_notice]),
                    claimMailingAddress: address.street ? {
                        name: address.name || null,
                        street: address.street,
                        city_state_zip: address.city_state_zip || null
                    } : toolkit.mailingAddresses?.claimMailingAddress || null,
                    payorId: uniqueStrings([toolkit.mailingAddresses?.payorId, ...toArray(toolkit.mailingAddresses?.payerIds), ...toArray(address.payer_ids)]).join(", ") || null
                }
            },
            ortho_information: {
                ...(toolkit.orthoInformation || {}),
                crowns_bridges_dentures_payment_note: crownsNote,
                notes: cleanSectionNotes([...(toolkit.orthoNotes || []), ...toArray(pdfModel?.additional_information?.notes)])
                    .filter(note => note !== pdfModel?.additional_information?.notes?.find(item => /seat\/delivery date/i.test(item)))
            },
            // Generic evidence bucket keeps non-orthodontic PDF limitations available without
            // misclassifying them as orthodontic rules. Original PDF wording is preserved.
            limitations_evidence: {
                sources: toArray(pdfModel?.additional_note_evidence).map(item => ({ source: "faxback_pdf", page: item.page ?? null, text: item.text })),
                notes: uniqueStrings(toArray(pdfModel?.additional_information?.notes))
            },
            source_conflicts: conflicts
        };
        const completenessIssues = validateFaxbackCompleteness(pdfModel, canonical);
        canonical.faxback_pdf = {
            section_title: "Faxback PDF",
            status: !pdfModel ? "NOT_CAPTURED" : (completenessIssues.length ? "CAPTURED_WITH_WARNINGS" : "INTEGRATED"),
            page_count: null,
            reason: null,
            content_integration: !pdfModel ? "not_parsed" : (completenessIssues.length ? "incomplete" : "integrated"),
            completeness_issues: completenessIssues,
            source_inventory: pdfModel?.source_inventory || null,
            additional_note_evidence: toArray(pdfModel?.additional_note_evidence),
            parse_warnings: toArray(pdfModel?.parse_warnings)
        };
        return canonical;
    }

    // Angular renders `_ngcontent-ng-c<hash>` attributes that change per build,
    // so the selector uses only the stable parts: <a class="link" title="Pop-ups
    // must be allowed!"> whose text is HERE, inside app-memberdetails-benefits.
    function findFaxbackLink() {
        const root = document.querySelector("app-memberdetails-benefits") || document;
        const links = Array.from(root.querySelectorAll("a.link, a[role='link']"));
        const isHere = a => /^here$/i.test(cleanText(a.textContent));
        return links.find(a => isHere(a) && /pop-?ups/i.test(a.getAttribute("title") || ""))
            || links.find(a => isHere(a) && /faxback/i.test(a.parentElement?.textContent || ""))
            || null;
    }

    // The page opens the PDF in a new tab/window. Swallow that for the duration
    // of our own click; the bytes are taken from the network response instead.
    function suppressPdfWindow() {
        const nativeOpen = window.open;
        const nativeAnchorClick = HTMLAnchorElement.prototype.click;
        const fakeWindow = new Proxy(function () {}, {
            get: (_target, prop) => prop === "closed" ? false : (prop === Symbol.toPrimitive ? () => "" : fakeWindow),
            set: () => true,
            apply: () => fakeWindow
        });
        window.open = function () { return fakeWindow; };
        HTMLAnchorElement.prototype.click = function () {
            if (/^blob:/i.test(this.href || "")) return undefined;
            return nativeAnchorClick.apply(this, arguments);
        };
        return () => {
            window.open = nativeOpen;
            HTMLAnchorElement.prototype.click = nativeAnchorClick;
        };
    }

    async function captureFaxbackPdf(state, run) {
        const cached = state.faxbackPdf;
        if (cached && cached.personKey && cached.personKey === state.personKey &&
            Date.now() - Date.parse(cached.capturedAt) < PDF_CACHE_TTL_MS) {
            return { status: "REUSED", record: cached };
        }

        const link = findFaxbackLink();
        if (!link) {
            return { status: "NOT_CAPTURED", record: null, reason: "HERE (faxback) link was not found on the page." };
        }

        let resolveWaiter;
        const waiter = new Promise(resolve => { resolveWaiter = resolve; state.pdfWaiters.push(resolve); });
        const restore = suppressPdfWindow();
        try {
            link.click();
            const record = await Promise.race([waiter, sleep(PDF_WAIT_MS).then(() => null)]);
            if (run.cancelled) return { status: "NOT_CAPTURED", record: null, reason: "Run was superseded." };
            if (!record) {
                return { status: "NOT_CAPTURED", record: null, reason: `No PDF response within ${PDF_WAIT_MS / 1000}s of clicking HERE.` };
            }
            if (record.personKey && state.personKey && record.personKey !== state.personKey) {
                return { status: "NOT_CAPTURED", record: null, reason: "Selected member changed while the PDF was loading." };
            }
            return { status: "CAPTURED", record };
        } finally {
            state.pdfWaiters = state.pdfWaiters.filter(fn => fn !== resolveWaiter);
            await sleep(PDF_SETTLE_MS);
            restore();
        }
    }

    function buildFaxbackSection(outcome, parsedDocument, normalizedOutput) {
        const issues = toArray(normalizedOutput?.faxback_pdf?.completeness_issues);
        const integrated = normalizedOutput?.faxback_pdf?.content_integration === "integrated";
        return {
            section_title: "Faxback PDF",
            status: integrated ? "INTEGRATED" : (parsedDocument?.status || outcome?.status || "NOT_CAPTURED"),
            page_count: parsedDocument?.page_count ?? null,
            reason: parsedDocument?.reason || outcome?.reason || null,
            content_integration: integrated ? "integrated" : (parsedDocument?.structured ? "incomplete" : "not_parsed"),
            completeness_issues: issues,
            source_inventory: normalizedOutput?.faxback_pdf?.source_inventory || parsedDocument?.structured?.source_inventory || null,
            additional_note_evidence: toArray(normalizedOutput?.limitations_evidence?.sources),
            parse_warnings: toArray(parsedDocument?.structured?.parse_warnings)
        };
    }

    async function startCrawl(state, nativeFetch, requestId) {
        // Always extract the global workbook-wide scope. The portal's current
        // member/plan context is captured separately; no workbook client is selected.
        if (state.activeRun && !state.activeRun.done) {
            state.activeRun.cancelled = true;
        }

        const run = {
            id: makeId(), requestId, cancelled: false, done: false,
            acknowledged: false, startedAt: Date.now(), resultData: null,
            clientProfile: null
        };
        state.activeRun = run;

        refreshProcedureTemplate(state);

        if (!state.procedureTemplate) {
            throw new Error(
                "Member benefit context is incomplete. Open/select the Member Details & Benefits page, wait for it to finish loading, then click Crawl again. A manual procedure-code lookup is not required."
            );
        }
        if (!state.procedureHeaders?.authorization) {
            throw new Error(
                "Authenticated Toolkit API context was not captured. Refresh the Member Details & Benefits page, wait for plan data to load, and retry."
            );
        }

        setBusy(state, true);
        setStatus(state, `Starting ${PROCEDURE_CODES.length}-code extraction…`, "working", { state: "RUNNING", completed: 0, total: PROCEDURE_CODES.length });

        try {
            // Start PDF capture immediately. It is independent of the procedure
            // lookups, so waiting for all lookups first only adds avoidable latency.
            setStatus(state, "Capturing the selected member's faxback PDF (HERE link) while extracting procedures…", "working", { state: "RUNNING" });
            const pdfPromise = captureFaxbackPdf(state, run).catch(error => ({
                status: "NOT_CAPTURED", record: null, reason: `PDF capture error: ${error.message}`
            }));

            const rawByCode = await fetchAllProcedures(state, nativeFetch, run);
            if (run.cancelled) throw new Error("This extraction was superseded by a newer run or member selection.");
            const pdfOutcome = await pdfPromise;
            if (run.cancelled) throw new Error("This extraction was superseded by a newer run or member selection.");

            setStatus(state, "Parsing the captured faxback PDF and merging it without duplication…", "working", { state: "RUNNING" });
            let parsedPdfDocument;
            try {
                // A malformed browser-side PDF stream must never hold the crawl
                // forever. Normal Toolkit faxback PDFs parse in well under a second.
                parsedPdfDocument = await Promise.race([
                    parseFaxbackPdfDocument(pdfOutcome.record),
                    sleep(8000).then(() => ({
                        status: "PARSE_FAILED",
                        reason: "Faxback PDF parsing exceeded the 8-second safety limit."
                    }))
                ]);
            } catch (error) {
                parsedPdfDocument = { status: "PARSE_FAILED", reason: `Faxback PDF parsing failed: ${error.message}` };
            }
            if (run.cancelled) throw new Error("This extraction was superseded by a newer run or member selection.");
            if (parsedPdfDocument?.status === "PARSE_FAILED") {
                console.warn(`Delta Toolkit: faxback PDF parse did not complete: ${parsedPdfDocument.reason || "unknown reason"}`);
            }

            setStatus(state, "Organizing Member Details & Benefits page sections and procedure details…", "working", { state: "RUNNING" });
            const data = buildFinalOutput(state, rawByCode, run, parsedPdfDocument);
            console.info(`Delta Toolkit: faxback PDF ${parsedPdfDocument?.structured ? "parsed and merged" : `not merged (${parsedPdfDocument?.reason || pdfOutcome?.reason || pdfOutcome?.status || "unknown"})`}.`);
            const apiOutcomes = data?.extraction_metrics?.api_outcomes_by_code || {};
            const integrity = validateProcedureIntegrity(PROCEDURE_CODES.map(code => {
                const outcome = apiOutcomes[code];
                const error = !outcome
                    ? "API lookup was not attempted."
                    : outcome.status !== "SUCCESS"
                        ? (outcome.error || `API outcome: ${outcome.status}`)
                        : null;
                return { procedure_code: code, error };
            }));
            data.crawl_statistics.successful_codes = Number(data?.extraction_metrics?.api_success_count ?? integrity.successful);
            data.crawl_statistics.failed_codes = toArray(data?.extraction_metrics?.api_failed_codes);
            data.crawl_statistics.unavailable_codes = toArray(data?.extraction_metrics?.api_unavailable_codes);
            data.crawl_statistics.not_attempted_codes = toArray(data?.extraction_metrics?.mandatory_codes_not_attempted);
            data.crawl_statistics.not_in_code_list_codes = toArray(data?.extraction_metrics?.api_not_in_code_list_codes);
            const notInCodeListCount = notInCodeListLooksLikeOutage(data.crawl_statistics.not_in_code_list_codes) ? data.crawl_statistics.not_in_code_list_codes.length : 0;
            const incompleteCount = data.crawl_statistics.failed_codes.length + data.crawl_statistics.unavailable_codes.length + data.crawl_statistics.not_attempted_codes.length + notInCodeListCount;
            data.crawl_statistics.status = incompleteCount ? "PARTIAL" : "COMPLETE";

            run.resultData = data;
            run.done = true;
            postPageMessage("RESULT", { requestId, data });
            setStatus(
                state,
                incompleteCount
                    ? `Extraction finished with ${incompleteCount} failed code(s). Preparing partial JSON…`
                    : "Extraction complete. Preparing JSON download…",
                incompleteCount ? "warning" : "working",
                { state: incompleteCount ? "PARTIAL" : "RUNNING" }
            );

            // The ISOLATED-world bridge normally acknowledges almost immediately.
            // Keep only a short safety fallback instead of blocking every completed crawl for 5 seconds.
            await sleep(RESULT_ACK_TIMEOUT_MS);
            if (!run.acknowledged) {
                downloadJson(data);
                setStatus(
                    state,
                    incompleteCount
                        ? `Partial — ${data.crawl_statistics.successful_codes}/${PROCEDURE_CODES.length} API code lookups succeeded. JSON downloaded.`
                        : `Done — ${data.crawl_statistics.successful_codes}/${PROCEDURE_CODES.length} API code lookups succeeded. JSON downloaded.`,
                    incompleteCount ? "warning" : "ready",
                    { state: incompleteCount ? "PARTIAL" : "COMPLETE" }
                );
            }
            return data;
        } finally {
            run.done = true;
            setBusy(state, false);
        }
    }

    async function fetchAllProcedures(state, nativeFetch, run) {
        const results = new Map([...state.procedureResponses].filter(([, value]) => value !== null && value !== undefined));
        const errors = new Map();
        const errorDetails = new Map();
        let apiAttemptCount = 0;
        const queue = [...PROCEDURE_CODES]; // each code gets a fresh lookup for the current run/member/plan
        results.clear();
        let completed = PROCEDURE_CODES.length - queue.length;
        const concurrency = PROCEDURE_CONCURRENCY;

        const workers = Array.from({ length: Math.min(concurrency, Math.max(queue.length, 1)) }, async () => {
            while (queue.length && !run.cancelled) {
                const code = queue.shift();
                try {
                    const transaction = await fetchProcedureWithRetry(state, nativeFetch, code, run, 0, true, () => { apiAttemptCount += 1; });
                    results.set(code, transaction);
                } catch (error) {
                    errors.set(code, String(error.message || error));
                    errorDetails.set(code, {
                        failure_kind: error.failure_kind || "REQUEST_FAILED",
                        http_status: Number.isFinite(error.http_status) ? error.http_status : error.transaction?.http_status ?? null,
                        error: String(error.message || error)
                    });
                    results.set(code, error.transaction || null);
                }
                completed += 1;
                setStatus(state, `Extracting procedure benefits: ${completed}/${PROCEDURE_CODES.length}`, "working", {
                    state: "RUNNING", completed, total: PROCEDURE_CODES.length,
                    progress: Math.round((completed / PROCEDURE_CODES.length) * 100)
                });
                if (PROCEDURE_THROTTLE_MS > 0) await sleep(PROCEDURE_THROTTLE_MS);
            }
        });

        await Promise.all(workers);
        results.__errors = errors;
        results.__errorDetails = errorDetails;
        results.__attemptCount = apiAttemptCount;
        return results;
    }

    async function fetchProcedureWithRetry(state, nativeFetch, code, run, attempt = 0, withUtilization = true, onAttempt = null) {
        if (run.cancelled) throw new Error("Extraction cancelled.");
        if (typeof onAttempt === "function") onAttempt();

        // utilizationIndicator asks the portal to include the member's service history for the
        // code (needed for the checklist "History" column). If the portal rejects that flag the
        // request is repeated once with the original template value.
        const body = { ...state.procedureTemplate, procedureCodes: code, ...(withUtilization ? { utilizationIndicator: true } : {}) };
        const headers = { ...state.procedureHeaders };
        if (!headers.accept) headers.accept = "application/json, text/plain, */*";
        if (!headers["content-type"]) headers["content-type"] = "application/json";

        let response;
        try {
            response = await nativeFetch(PROCEDURE_SEARCH_URL, {
                method: "POST",
                headers,
                credentials: "include",
                body: JSON.stringify(body)
            });
        } catch (error) {
            if (attempt < 2) {
                await sleep(500 * (2 ** attempt));
                return fetchProcedureWithRetry(state, nativeFetch, code, run, attempt + 1, withUtilization, onAttempt);
            }
            const failure = new Error(`${code}: network request failed (${error.message})`);
            failure.failure_kind = "NETWORK_ERROR";
            failure.http_status = null;
            throw failure;
        }

        const text = await response.text();
        const data = safeJsonParse(text);
        // Crawl-local result: retain only what output construction actually needs.
        // Keep only fields consumed by the canonical procedure-result normalizer.
        const transaction = {
            http_status: response.status,
            captured_at: new Date().toISOString(),
            response: data !== null ? data : (text ? text.slice(0, 30000) : null)
        };

        if (response.ok && data !== null) {
            const hasPpoBucket = toArray(data).some(isExactPpoBucket);
            if (!hasPpoBucket) {
                const error = new Error(`${code}: HTTP ${response.status} returned JSON without a usable PPO Dentist benefit bucket.`);
                error.transaction = transaction;
                error.http_status = response.status;
                error.failure_kind = "NO_PPO_BUCKET";
                throw error;
            }
            return transaction;
        }
        if (withUtilization && [400, 404, 405, 422].includes(response.status)) {
            return fetchProcedureWithRetry(state, nativeFetch, code, run, attempt, false, onAttempt);
        }
        if ((response.status === 429 || response.status >= 500) && attempt < 3) {
            const retryAfter = Number(response.headers.get("retry-after"));
            await sleep(Number.isFinite(retryAfter) ? retryAfter * 1000 : 700 * (2 ** attempt));
            return fetchProcedureWithRetry(state, nativeFetch, code, run, attempt + 1, withUtilization, onAttempt);
        }

        let message;
        if (response.status === 401 || response.status === 403) {
            message = `${code}: Toolkit authorization expired. Refresh/reload the Member Details & Benefits page (or re-login if required) so normal authenticated API traffic refreshes the token, then retry.`;
        } else {
            message = `${code}: HTTP ${response.status}${text ? ` — ${text.slice(0, 180)}` : ""}`;
        }
        const err = new Error(message);
        err.transaction = transaction;
        err.http_status = response.status;
        err.failure_kind = response.status === 401 || response.status === 403 ? "AUTH_ERROR"
            : response.status === 404 ? "NOT_IN_PORTAL_CODE_LIST"
            : response.status === 429 ? "RATE_LIMIT"
                : response.status >= 500 ? "SERVER_ERROR"
                    : data === null ? "INVALID_JSON" : "HTTP_ERROR";
        throw err;
    }

    // =====================================================================
    // Output construction
    // =====================================================================

    function notInCodeListLooksLikeOutage(codes) {
        return toArray(codes).length > Math.max(25, Math.ceil(PROCEDURE_CODES.length * 0.25));
    }

    function benefitsRequestDob(request) {
        return firstMeaningful([request?.memberDateOfBirth, request?.memberBirthDate]);
    }

    function extractCurrentMemberFromDom() {
        const result = {
            name: "", dob: "", relationship: "", eligibility: "", effectiveDate: "", memberId: "", network: "", source: ""
        };
        try {
            // In Toolkit the .allfamily header and table.table2 are SIBLINGS inside
            // the same .dropdown-section; the old selector `.allfamily .table2` could never match.
            const allFamily = document.querySelector(".allfamily");
            const familyText = cleanText(allFamily?.textContent || "");
            const memberIdMatch = familyText.match(/Member\s+Alternate\s+ID\s*:?\s*([A-Za-z0-9-]+)/i);
            if (memberIdMatch) result.memberId = memberIdMatch[1];

            const familyContainer = allFamily?.closest(".dropdown-section") || document;
            const selectedRow = familyContainer.querySelector("table.table2 tr.highLight") ||
                familyContainer.querySelector("table.table2 tr.highlight") ||
                document.querySelector("table.table2 tr.highLight, table.table2 tr.highlight");
            const cells = selectedRow ? [...selectedRow.querySelectorAll("td")].map(cell => cleanText(cell.textContent || "")) : [];
            if (cells.length >= 5) {
                [result.name, result.dob, result.relationship, result.eligibility, result.effectiveDate] = cells.slice(0, 5);
                result.source = "family_selected_row";
            }

            // #detailHeader is often under a hidden Angular component. innerText becomes empty
            // for hidden nodes, so always use textContent and also read label/value cells directly.
            const header = document.querySelector("#detailHeader");
            if (header) {
                const headerText = cleanText(header.textContent || "");
                if (!result.name) {
                    result.name = headerText.match(/Patient\s+Name\s*:\s*(.+?)(?=Eligibility\s+and\s+Benefits|Network\s*:|Birthdate\s*:|$)/i)?.[1]?.trim() || "";
                }

                result.network = cleanText(headerText.match(/Network\s*:\s*(.+?)(?=Patient\s+Name\s*:|Birthdate\s*:|Relationship\s*:|Eligibility\s*:|Effective\s+Date\s*:|Member\s+Alternate|$)/i)?.[1] || "");
                const headerCells = [...header.querySelectorAll("td")].map(cell => cleanText(cell.textContent || ""));
                for (let i = 0; i < headerCells.length; i++) {
                    const cell = headerCells[i];
                    if (!result.name && /^Patient\s+Name\s*:/i.test(cell)) result.name = cleanText(cell.replace(/^Patient\s+Name\s*:\s*/i, ""));
                    if (/^Birthdate\s*:?$/i.test(cell) && !result.dob) result.dob = headerCells[i + 1] || "";
                    if (/^Relationship\s*:?$/i.test(cell) && !result.relationship) result.relationship = headerCells[i + 1] || "";
                    if (/^Eligibility\s*:?$/i.test(cell) && !result.eligibility) result.eligibility = headerCells[i + 1] || "";
                    if (/^Effective\s+Date\s*:?$/i.test(cell) && !result.effectiveDate) result.effectiveDate = headerCells[i + 1] || "";
                    if (/^Network\s*:?$/i.test(cell) && !result.network) result.network = headerCells[i + 1] || "";
                }
                if (!result.source && (result.name || result.dob)) result.source = "detail_header";
            }

            // Generic label-map fallback for small portal markup changes.
            const dom = buildDomLabelMap();
            if (!result.name) result.name = domValue(dom, ["Patient Name"]);
            if (!result.dob) result.dob = domValue(dom, ["Birthdate", "Date of Birth", "DOB"]);
            if (!result.relationship) result.relationship = domValue(dom, ["Relationship"]);
            if (!result.eligibility) result.eligibility = domValue(dom, ["Eligibility"]);
            if (!result.effectiveDate) result.effectiveDate = domValue(dom, ["Effective Date"]);
            if (!result.memberId) result.memberId = domValue(dom, ["Member Alternate ID", "Member ID"]);
        } catch (_) { /* DOM fallback is best-effort */ }
        return result;
    }


    function extractAllFamilyMembersForOutput(fallbackSelected) {
        const result = {
            section_title: "All Family Members",
            memberAlternateId: fallbackSelected?.member_id || "N/A",
            columns: ["Patient Name", "Birthdate", "Relationship", "Eligibility", "Effective Date"],
            members: [],
            selectedMember: null
        };
        try {
            const allFamily = document.querySelector(".allfamily");
            const section = allFamily?.closest(".dropdown-section");
            const familyText = cleanText(allFamily?.textContent || "");
            const memberId = familyText.match(/Member\s+Alternate\s+ID\s*:?\s*([A-Za-z0-9-]+)/i)?.[1];
            if (memberId) result.memberAlternateId = memberId;

            const table = section?.querySelector("table.table2");
            if (table) {
                const headers = [...table.querySelectorAll("th")]
                    .map(cell => cleanText(cell.textContent || ""))
                    .filter(Boolean);
                if (headers.length >= 5) result.columns = headers.slice(0, 5);

                const rows = [...table.querySelectorAll("tr")];
                for (const row of rows) {
                    const cells = [...row.querySelectorAll("td")]
                        .map(cell => cleanText(cell.textContent || ""))
                        .filter((_, index, arr) => arr.length >= 5 || Boolean(arr[index]));
                    if (cells.length < 5) continue;
                    const member = {
                        patientName: cells[0] || "",
                        birthdate: cells[1] || "",
                        relationship: cells[2] || "",
                        eligibility: cells[3] || "",
                        effectiveDate: cells[4] || "",
                        selected: row.classList.contains("highLight") || row.classList.contains("highlight")
                    };
                    result.members.push(member);
                    if (member.selected) result.selectedMember = member;
                }
            }
        } catch (_) { /* DOM page mirror is best-effort */ }

        if (!result.selectedMember && fallbackSelected) {
            result.selectedMember = {
                patientName: fallbackSelected.name || "N/A",
                birthdate: fallbackSelected.dob || "N/A",
                relationship: fallbackSelected.relationship || "N/A",
                eligibility: fallbackSelected.eligibility_status || "N/A",
                effectiveDate: fallbackSelected.effective_date || "N/A",
                selected: true
            };
        }
        if (!result.members.length && result.selectedMember) result.members = [result.selectedMember];
        return result;
    }

    function findToolkitPageSection(title) {
        try {
            const sections = [...document.querySelectorAll("app-memberdetails-benefits .dropdown-section")];
            return sections.find(section => {
                const heading = section.querySelector(":scope > .top p, :scope > div.top p, :scope .top > p");
                return cleanText(heading?.textContent || "").toLowerCase() === String(title).toLowerCase();
            }) || null;
        } catch (_) {
            return null;
        }
    }

    function extractToolkitSectionParagraphs(title) {
        const section = findToolkitPageSection(title);
        if (!section) return [];
        const values = [...section.querySelectorAll("p")]
            .map(p => cleanText(p.textContent || ""))
            .filter(Boolean)
            .filter(text => text.toLowerCase() !== String(title).toLowerCase())
            .filter(text => !/^(print section|expand|collapse)$/i.test(text));
        return uniqueStrings(values);
    }

    function extractToolkitNetworkTabs() {
        // User only wants the PPO Dentist level. We intentionally do not expose
        // Premier/Non-PPO tabs even though the page may render them.
        return ["PPO Dentist"];
    }

    function extractPpoRoutineBuckets(response) {
        return toArray(response)
            .filter(item => isExactPpoBucket(item))
            .map(item => sanitizePpoNetworkDataForOutput(item))
            .filter(Boolean);
    }

    function extractPpoNetworkBenefitBuckets(benefitRoot) {
        return toArray(benefitRoot?.networkBenefits)
            .filter(item => isExactPpoBucket(item))
            .map(item => sanitizePpoNetworkDataForOutput(item))
            .filter(Boolean);
    }

    function extractExclusionsAndLimitations(ppoNetworkBenefits) {
        const records = [];
        for (const bucket of ppoNetworkBenefits) {
            for (const item of toArray(bucket?.coverages)) {
                const limitations = toArray(item?.exclusionsAndLimitations).filter(Boolean);
                if (!limitations.length) continue;
                records.push(sanitizeForOutput({
                    procedure: item?.procedure ?? null,
                    procedureId: item?.procedureId ?? null,
                    exclusionsAndLimitations: limitations
                }));
            }
        }
        return records;
    }

    function ppoOrthoAgeLimits(benefitRoot) {
        return toArray(benefitRoot?.orthoAgeLimitConfig)
            .filter(item => toArray(item?.networks).some(name => /^PPO Dentist$/i.test(cleanText(name))))
            .map(item => sanitizePpoNetworkDataForOutput(item))
            .filter(Boolean);
    }

    function buildCoveragePageRows(ppoNetworkBenefits) {
        const rows = [];
        for (const bucket of toArray(ppoNetworkBenefits)) {
            for (const item of toArray(bucket?.coverages)) {
                rows.push({
                    procedure: item?.procedure ?? null,
                    procedureId: item?.procedureId ?? null,
                    percentCovered: item?.coverage?.percent ?? null,
                    childValuesDiffer: item?.coverage?.childValuesDiffer ?? null,
                    waitingPeriod: item?.waitingPeriods ?? null,
                    waitingPeriodMetDate: item?.waitingPeriodMetDate ?? null,
                    medicallyNecessary: item?.coverage?.medicallyNecessary ?? null,
                    radioGraphsRequired: item?.radioGraphsRequired ?? null,
                    remarksRequired: item?.remarksRequired ?? null
                });
            }
        }
        return sanitizeForOutput(rows);
    }

    function displayApiDate(value) {
        if (typeof value !== "string") return value ?? null;
        const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
        return match ? `${match[2]}/${match[3]}/${match[1]}` : value;
    }

    function parseDisplayedAccumulatorValue(text, label) {
        const source = cleanText(text || "");
        const match = source.match(new RegExp(`${label}\\s*:\\s*(?:\\u00a0*)?(Unlimited|N/A|\\$?\\s*[0-9,]+(?:\\.[0-9]{1,2})?)`, "i"));
        if (!match) return undefined;
        const value = cleanText(match[1]);
        if (/^(?:Unlimited|N\/A)$/i.test(value)) return undefined;
        const numeric = Number(value.replace(/[$,\s]/g, ""));
        return Number.isFinite(numeric) ? numeric : undefined;
    }

    // Mirror the values rendered by the live Toolkit table. The underlying
    // accumulator API can return null for family values while the website UI
    // deliberately renders those same values as $0. Read the rendered cells
    // when available, then keep the API representation as a fallback.
    function extractDisplayedAccumulatorValues(section) {
        if (!section) return [];
        try {
            const table = section.querySelector("app-maximums-deductibles table.table2")
                || section.querySelector("table.table2");
            if (!table) return [];
            const rowNodes = [...table.querySelectorAll("tbody tr")].filter(row => row.querySelectorAll("td").length >= 6);
            return rowNodes.map((row, index) => {
                const cells = [...row.querySelectorAll("td")].map(cell => cleanText(cell.textContent || ""));
                return {
                    index,
                    type: cells[0] || null,
                    category: cells[1] || null,
                    name: cells[2] || null,
                    individual: {
                        amount: parseDisplayedAccumulatorValue(cells[4], "Amount"),
                        used: parseDisplayedAccumulatorValue(cells[4], "Used"),
                        remaining: parseDisplayedAccumulatorValue(cells[4], "Remaining")
                    },
                    family: {
                        amount: parseDisplayedAccumulatorValue(cells[5], "Amount"),
                        used: parseDisplayedAccumulatorValue(cells[5], "Used"),
                        remaining: parseDisplayedAccumulatorValue(cells[5], "Remaining")
                    }
                };
            });
        } catch (_) {
            return [];
        }
    }

    function accumulatorDisplayMatchKey(row) {
        return `${cleanText(row?.type).toLowerCase()}|${cleanText(row?.category).toLowerCase()}|${cleanText(row?.name).toLowerCase()}`;
    }

    function buildAccumulatorPageRows(ppoAccumulatorBuckets, section = null) {
        const rows = [];
        const displayedRows = extractDisplayedAccumulatorValues(section);
        const displayedByKey = new Map(displayedRows.map(row => [accumulatorDisplayMatchKey(row), row]));
        const displayedByTypeCategory = new Map();
        for (const row of displayedRows) {
            const key = `${cleanText(row?.type).toLowerCase()}|${cleanText(row?.category).toLowerCase()}`;
            const list = displayedByTypeCategory.get(key) || [];
            list.push(row);
            displayedByTypeCategory.set(key, list);
        }
        const categoryOffsets = new Map();
        const usedDisplayedIndexes = new Set();

        for (const bucket of toArray(ppoAccumulatorBuckets)) {
            for (const acc of toArray(bucket?.accumulators)) {
                const base = {
                    type: acc?.accumulatorType ?? null,
                    category: acc?.categoryType ?? null,
                    name: acc?.name ?? null,
                    categoryHistoryAccumulator: acc?.claimHistoryAccumulatorId ?? null,
                    individual: {
                        amount: acc?.individualAmount ?? null,
                        used: acc?.individualAmountUsed ?? null,
                        remaining: acc?.individualAmountRemaining ?? null
                    },
                    family: {
                        amount: acc?.familyAmount ?? null,
                        used: acc?.familyAmountUsed ?? null,
                        remaining: acc?.familyAmountRemaining ?? null
                    },
                    from: displayApiDate(acc?.startDate),
                    to: displayApiDate(acc?.endDate),
                    isLifetime: acc?.isLifetime ?? null,
                    isMaximum: acc?.isMaximum ?? null,
                    description: acc?.description ?? null
                };
                const exact = displayedByKey.get(accumulatorDisplayMatchKey(base));
                const typeCategoryKey = `${cleanText(base.type).toLowerCase()}|${cleanText(base.category).toLowerCase()}`;
                const list = displayedByTypeCategory.get(typeCategoryKey) || [];
                const offset = categoryOffsets.get(typeCategoryKey) || 0;
                const displayed = exact || list[offset] || null;
                if (!exact && displayed) categoryOffsets.set(typeCategoryKey, offset + 1);
                if (displayed && Number.isInteger(displayed.index)) usedDisplayedIndexes.add(displayed.index);

                if (displayed) {
                    for (const memberType of ["individual", "family"]) {
                        for (const amountKey of ["amount", "used", "remaining"]) {
                            const visible = displayed?.[memberType]?.[amountKey];
                            if (visible !== undefined) base[memberType][amountKey] = visible;
                        }
                    }
                }
                rows.push(base);
            }
        }

        // If an accumulator is visible in the website table but absent from the API response,
        // keep the displayed website row instead of replacing it with a PDF-derived value.
        for (const displayed of displayedRows) {
            if (usedDisplayedIndexes.has(displayed.index)) continue;
            rows.push({
                type: displayed.type,
                category: displayed.category,
                name: displayed.name,
                categoryHistoryAccumulator: null,
                individual: {
                    amount: displayed.individual?.amount ?? null,
                    used: displayed.individual?.used ?? null,
                    remaining: displayed.individual?.remaining ?? null
                },
                family: {
                    amount: displayed.family?.amount ?? null,
                    used: displayed.family?.used ?? null,
                    remaining: displayed.family?.remaining ?? null
                },
                from: null,
                to: null,
                isLifetime: /lifetime/i.test(`${displayed.type || ""} ${displayed.name || ""}`),
                isMaximum: /maximum/i.test(String(displayed.type || "")),
                description: null
            });
        }
        return sanitizeForOutput(deduplicateAccumulatorRows(rows));
    }

    function buildFinalOutput(state, rawByCode, run, parsedPdfDocument) {
        const memberRoot = state.memberSearchResponse || {};
        const template = state.procedureTemplate || {};
        const memberSearchRequest = state.memberSearchRequest || {};
        const domMember = extractCurrentMemberFromDom();
        const memberApiContext = resolveMemberApiContext(memberRoot, template, domMember);
        const subscriber = memberApiContext.subscriber || {};
        const patient = memberApiContext.patient || { isSubscriber: false, record: {} };
        const procedureErrors = rawByCode.__errors || new Map();
        const pdf = parsedPdfDocument?.structured || null;

        const apiSubscriberName = joinName(subscriber.subscriberFirstName, subscriber.subscriberLastName);
        const apiPatientName = patient.isSubscriber
            ? apiSubscriberName
            : joinName(patient.record?.dependentFirstName, patient.record?.dependentLastName);
        const patientName = firstMeaningful([
            pdf?.eligibility?.patient_name,
            apiPatientName,
            domMember.name
        ]) || "N/A";
        const rawPatientDob = firstMeaningful([
            patient.isSubscriber ? subscriber.dateOfBirth : patient.record?.dateOfBirth,
            domMember.dob,
            benefitsRequestDob(state.memberBenefitsRequest),
            template.memberBirthDate
        ]);
        const patientDob = normalizeDobValue(rawPatientDob) || rawPatientDob;
        const patientEffective = firstMeaningful([
            patient.isSubscriber ? subscriber.effectiveDate : patient.record?.eligibilityEffectiveDate,
            domMember.effectiveDate
        ]);
        const patientStatus = firstMeaningful([
            patient.isSubscriber ? subscriber.eligibilityStatus : patient.record?.eligibilityStatus,
            domMember.eligibility
        ]);
        const relationship = firstMeaningful([
            pdf?.eligibility?.relationship,
            patient.isSubscriber ? template.relationshipToSubscriber : patient.record?.relationshipToSubscriber,
            domMember.relationship,
            template.relationshipToSubscriber,
            patient.isSubscriber ? "Subscriber" : "Dependent"
        ]);
        const memberId = firstMeaningful([
            memberSearchRequest.memberId,
            subscriber.alternateId,
            subscriber.memberId,
            domMember.memberId
        ]);

        const selectedMember = {
            name: patientName,
            dob: valueOrNA(patientDob),
            member_id: valueOrNA(memberId),
            relationship: valueOrNA(relationship),
            eligibility_status: valueOrNA(patientStatus),
            effective_date: valueOrNA(patientEffective),
            source: memberApiContext.matched ? "member_details" : (domMember.name ? "page" : "request_context")
        };

        const benefitRoot = state.memberBenefitsResponse || {};
        const benefitClient = benefitRoot.client || {};
        const contract = benefitRoot.contract || {};
        const clientRoot = state.clientSearchResponse?.client || state.clientSearchResponse || {};
        const subClientContract = clientRoot?.subClient?.contract || {};
        const ppoAccumulatorBuckets = toArray(benefitRoot.maximumsAndDeductions)
            .filter(isExactPpoBucket)
            .map(item => sanitizePpoNetworkDataForOutput(item))
            .filter(Boolean);
        const ppoRoutineBuckets = extractPpoRoutineBuckets(state.routineProceduresResponse);
        const ppoNetworkBenefits = extractPpoNetworkBenefitBuckets(benefitRoot);

        const toolkitResultsForRun = PROCEDURE_CODES.map(code => toolkitProcedureResult(code, rawByCode, procedureErrors));
        const apiSuccessfulCodes = toolkitResultsForRun.filter(result => result.status === "OK").map(result => result.procedureCode);
        const apiFailedCodes = toolkitResultsForRun.filter(result => result.status === "FAILED").map(result => result.procedureCode);
        const apiUnavailableCodes = toolkitResultsForRun.filter(result => result.status === "UNAVAILABLE").map(result => result.procedureCode);
        const apiNotInCodeListCodes = toolkitResultsForRun.filter(result => result.status === "NOT_IN_CODE_LIST").map(result => result.procedureCode);
        const notInCodeListIncomplete = notInCodeListLooksLikeOutage(apiNotInCodeListCodes);
        const successfulProcedureCount = apiSuccessfulCodes.length;
        const failedProcedureCodes = apiFailedCodes;
        const familySection = extractAllFamilyMembersForOutput(selectedMember);
        const pdfEligibility = pdf?.eligibility || {};
        const pdfGroups = pdf?.benefit_breakdown?.categories || [];
        const orthoPdfNotes = uniqueStrings([
            ...toArray(pdf?.additional_information?.notes).filter(line => /Orthodontic age limit|Enhanced Preventive Benefits|General anesthesia|X-rays are required/i.test(line)),
            ...extractToolkitSectionParagraphs("Ortho Information")
        ]);
        const orthoAgeLimitText = toArray(pdf?.additional_information?.notes).find(line => /Orthodontic age limit/i.test(line)) || null;
        const orthoAgeLimitMatch = orthoAgeLimitText?.match(/covered for age\s+(\d+) and under/i);
        const orthoAgeLimit = orthoAgeLimitMatch ? Number(orthoAgeLimitMatch[1]) : null;
        const page4PaymentNote = toArray(pdf?.additional_information?.notes).find(line => /seat\/delivery date/i.test(line)) || null;

        const toolkitDisplayFields = {
            plan: benefitClient.planAcronym ?? template.planAcronym ?? null,
            payor_plan_id: subscriber?.claimAddressInfo?.payorId ?? subscriber?.claimAddressInfo?.payerId ?? benefitClient.payorId ?? benefitClient.payorID ?? template.payorId ?? template.payorID ?? null,
            payor_id: subscriber?.claimAddressInfo?.payorId ?? subscriber?.claimAddressInfo?.payerId ?? benefitClient.payorId ?? benefitClient.payorID ?? template.payorId ?? template.payorID ?? null,
            subGroupNumber: benefitClient.subClientSpecifiedId ?? template.subClientSpecifiedId ?? null,
            subGroupName: benefitClient.subClientName ?? null
        };
        const canonical = normalizePdfIntoCanonicalSections(pdf, {
            memberDetails: familySection,
            rawByCode,
            procedureErrors,
            routineRows: toolkitRoutineRows(ppoRoutineBuckets),
            coverageRows: buildCoveragePageRows(ppoNetworkBenefits),
            exclusionRows: extractExclusionsAndLimitations(ppoNetworkBenefits),
            maximumRows: buildAccumulatorPageRows(ppoAccumulatorBuckets, findToolkitPageSection("Maximums and Deductibles")),
            maximumNotes: extractToolkitSectionParagraphs("Maximums and Deductibles"),
            routineNotes: extractToolkitSectionParagraphs("Routine Procedures"),
            coverageNotes: extractToolkitSectionParagraphs("Coverages"),
            clientNotes: extractToolkitSectionParagraphs("Client Benefit Information"),
            clientFields: toolkitDisplayFields,
            cobConfig: sanitizeForOutput(contract.cobConfig || {}),
            cobNotes: extractToolkitSectionParagraphs("COB Information"),
            mailingAddresses: {
                inquiryAddress: subscriber?.claimAddressInfo?.inquiryAddress ?? null,
                phoneNumber: subscriber?.claimAddressInfo?.phoneNumber ?? null,
                subscriberPhoneNumber: subscriber?.claimAddressInfo?.subscriberPhoneNumber ?? null,
                claimMailingAddress: subscriber?.claimAddressInfo?.claimMailingAddress ?? null,
                payorId: subscriber?.claimAddressInfo?.payorId ?? subscriber?.claimAddressInfo?.payerId ?? null,
                payerIds: subscriber?.claimAddressInfo?.payerIds ?? subscriber?.claimAddressInfo?.payer_ids ?? null
            },
            mailingNotes: extractToolkitSectionParagraphs("Claim & Inquiry Mailing Addresses"),
            orthoInformation: {
                section_title: "Ortho Information",
                network: "PPO Dentist",
                ortho_age_limit_under: orthoAgeLimit,
                ortho_age_limit_note: orthoAgeLimitText,
                crowns_bridges_dentures_payment_note: page4PaymentNote,
                orthoAgeLimitConfig: ppoOrthoAgeLimits(benefitRoot),
                orthoPaymentSchedule: sanitizeForOutput(subClientContract.orthoPaymentSchedule || null)
            },
            orthoNotes: orthoPdfNotes,
            accumulationPeriodType: contract.accumulationPeriodType ?? null
        });
        const coverages = canonical.coverages;
        const pdfRowsByCode = new Map(pdfProcedureRows(pdf).map(row => [row.procedureCode, row]));
        coverages.procedure_code_search.results = enrichProcedureResults(coverages.procedure_code_search.results, {
            outcomes: buildLookupOutcomeMap(toolkitResultsForRun, rawByCode),
            records: canonical.exclusions_and_limitations?.records,
            deductibleRow: findGeneralAccumulatorRow(canonical.maximums_and_deductibles?.rows, "deductible"),
            orthoSchedule: subClientContract.orthoPaymentSchedule || null,
            coverageRows: coverages.coverage_rows,
            routineDatesByCode: routineDatesByCode(canonical.routine_procedures?.rows),
            labels: PROCEDURE_LABELS
        }).map(row => {
            const code = normalizeCode(row?.procedureCode);
            return { ...row, out_of_network: outOfNetworkForCode(code, rawByCode?.get?.(code), pdfRowsByCode.get(code)?.pdf_coverage_by_network) };
        });
        const outOfNetwork = buildOutOfNetworkSection({
            benefitRoot,
            routineResponse: state.routineProceduresResponse,
            pdfModel: pdf,
            procedureResponses: PROCEDURE_CODES.map(code => rawByCode?.get?.(code)).filter(Boolean),
            pdfMaximumNetworks: pdfEligibility.maximum_and_deductibles?.table_networks,
            results: coverages.procedure_code_search.results,
            notes: coverages.notes
        });
        const termination = findTerminationDate(patient.record, subscriber, benefitRoot?.member, benefitRoot?.contract);
        const nonPpoEvidence = collectNonPpoEvidence(rawByCode);
        const routineFromPdf = canonical.routine_procedures;
        const maximumsAndDeductibles = canonical.maximums_and_deductibles;
        const moreInformation = {
            section_title: "More Information",
            ...canonical.more_information,
            age_limitations: {
                section_title: "Age Limitations",
                ageLimitations: sanitizeForOutput(contract.ageLimitations || null)
            }
        };
        const sourceConflicts = canonical.source_conflicts;
        const patientAndPlan = buildPatientAndPlanSection({
            selectedMember,
            pdfEligibility,
            apiSubscriberName,
            display: canonical.more_information?.client_benefit_information?.display_fields || {},
            mailing: canonical.more_information?.claim_and_inquiry_mailing_addresses || {},
            maxRows: maximumsAndDeductibles?.rows,
            accumulationPeriodType: contract.accumulationPeriodType ?? null,
            termination,
            familyMembers: familySection?.members,
            planAcronym: benefitClient.planAcronym ?? template.planAcronym ?? null,
            clientSpecifiedId: benefitClient.clientSpecifiedId ?? template.clientSpecifiedId ?? null,
            subClientSpecifiedId: benefitClient.subClientSpecifiedId ?? template.subClientSpecifiedId ?? null,
            subGroupName: benefitClient.subClientName ?? null,
            pagePhoneNumbers: collectContactPhoneNumbers(),
            providerNetworkOnPage: domMember.network || null,
            selectedNetwork: "PPO Dentist"
        });

        const outputBody = {
            source: "Delta Dental Office Toolkit",
            portal: location.hostname,
            page: "Member Details & Benefits",
            captured_at: new Date().toISOString(),
            selected_network: "PPO Dentist",
            patient_and_plan: patientAndPlan,
            run_context: {
                run_id: run.id,
                extension_build_id: "1.35.28",
                requirements_spec_version: TOOLKIT_REQUIREMENTS_SPEC?.source_workbook_sha256 || null,
                extraction_scope: "GLOBAL_WORKBOOK_REQUIREMENTS",
                selected_client_profile: { sheet_name: null, selection_method: null, status: "NOT_REQUIRED_GLOBAL_MODE" },
                portal_context: {
                    member_identity_status: memberApiContext.matched ? "VERIFIED" : (patientName !== "N/A" ? "UNVERIFIED" : "NOT_RETURNED"),
                    plan_context_status: state.procedureTemplate ? "CAPTURED" : "NOT_RETURNED",
                    member_name: patientName,
                    date_of_birth: valueOrNA(patientDob),
                    member_id: valueOrNA(memberId),
                    relationship: valueOrNA(relationship),
                    eligibility_status: valueOrNA(patientStatus),
                    member_effective_date: valueOrNA(patientEffective),
                    plan_acronym: benefitClient.planAcronym ?? template.planAcronym ?? null,
                    group_number: benefitClient.clientSpecifiedId ?? template.clientSpecifiedId ?? null,
                    subgroup_number: benefitClient.subClientSpecifiedId ?? template.subClientSpecifiedId ?? null,
                    subgroup_name: benefitClient.subClientName ?? null,
                    selected_network: "PPO Dentist",
                    captured_at: new Date().toISOString()
                }
            },

            member_details: canonical.member_details,

            networks: {
                section_title: "Networks",
                selected: "PPO Dentist",
                benefit_values_network: "PPO Dentist",
                out_of_network_networks: outOfNetwork.networks,
                available_in_output: uniqueStrings([
                    "PPO Dentist",
                    ...toArray(state.memberBenefitsResponse?.networks).map(item => typeof item === "string" ? item : item?.name || item?.network),
                    ...PROCEDURE_CODES.flatMap(code => {
                        const response = rawByCode.get(code)?.response;
                        return toArray(response).flatMap(bucket => toArray(bucket?.networks));
                    }),
                    ...toArray(pdf?.benefit_breakdown?.networks)
                ].map(cleanText).filter(Boolean)),
                network_benefit_evidence: uniqueStrings(PROCEDURE_CODES.flatMap(code => {
                    const response = rawByCode.get(code)?.response;
                    return toArray(response).filter(bucket => !isExactPpoBucket(bucket) && toArray(bucket?.coverages).some(node => node?.coverage?.percent !== null && node?.coverage?.percent !== undefined)).flatMap(bucket => toArray(bucket?.networks));
                }).map(cleanText).filter(Boolean)),
                network_scope_note: "Selected-network benefits remain PPO Dentist. Other listed networks are source metadata unless network-specific benefit evidence is present; this does not prove provider participation."
            },
            network_benefit_details: {
                source_api_networks: sanitizeNetworkEvidenceForOutput(toArray(state.memberBenefitsResponse?.networkBenefits).map(bucket => ({
                    networks: toArray(bucket?.networks),
                    benefits: toArray(bucket?.coverages).map(item => ({
                        procedure: item?.procedure ?? null,
                        procedureId: item?.procedureId ?? null,
                        percentCovered: item?.coverage?.percent ?? null,
                        waitingPeriod: item?.waitingPeriods ?? null,
                        waitingPeriodMetDate: item?.waitingPeriodMetDate ?? null,
                        limitations: toArray(item?.exclusionsAndLimitations)
                    }))
                }))),
                procedure_network_evidence: sanitizeNetworkEvidenceForOutput(PROCEDURE_CODES.flatMap(code => {
                    const response = rawByCode.get(code)?.response;
                    return toArray(response).filter(bucket => !isExactPpoBucket(bucket) && toArray(bucket?.coverages).some(node => node?.coverage?.percent !== null && node?.coverage?.percent !== undefined)).map(bucket => ({
                        procedure_code: code,
                        networks: toArray(bucket?.networks),
                        coverages: toArray(bucket?.coverages).map(item => ({
                            procedure: item?.procedure ?? null,
                            procedureId: item?.procedureId ?? null,
                            percentCovered: item?.coverage?.percent ?? null,
                            waitingPeriod: item?.waitingPeriods ?? null,
                            waitingPeriodMetDate: item?.waitingPeriodMetDate ?? null,
                            limitations: toArray(item?.exclusionsAndLimitations)
                        }))
                    }));
                }))
            },

            claim_reminders: {
                section_title: "Claim Reminders",
                messages: extractToolkitSectionParagraphs("Claim Reminders").filter(message => {
                    const text = normalizePdfText(message);
                    const pdfCorpus = [
                        pdfEligibility.overview_notice,
                        pdfEligibility.client_information,
                        pdf?.benefit_breakdown?.notice,
                        ...pdfGroups.flatMap(group => toArray(group.notes)),
                        ...toArray(pdf?.additional_information?.notes)
                    ].filter(Boolean).map(normalizePdfText);
                    return !pdfCorpus.some(item => item === text);
                })
            },

            routine_procedures: routineFromPdf,

            coverages,

            exclusions_and_limitations: canonical.exclusions_and_limitations,

            maximums_and_deductibles: maximumsAndDeductibles,

            ortho_information: canonical.ortho_information,

            more_information: moreInformation,

            out_of_network: outOfNetwork,

            crawl_statistics: {
                extraction_scope: `${PROCEDURE_CODES.length} requested procedure codes`,
                requested_codes: PROCEDURE_CODES.length,
                successful_codes: successfulProcedureCount,
                failed_codes: failedProcedureCodes,
                unavailable_codes: apiUnavailableCodes,
                not_in_code_list_codes: apiNotInCodeListCodes,
                status: (failedProcedureCodes.length || apiUnavailableCodes.length || notInCodeListIncomplete) ? "PARTIAL" : "COMPLETE",
                source_conflicts: sourceConflicts
            }
        };

        const mergedProcedureRows = toArray(coverages?.procedure_code_search?.results);
        const apiOutcomeByCode = Object.fromEntries(toolkitResultsForRun.map(result => {
            const errorDetail = rawByCode.__errorDetails?.get(result.procedureCode) || null;
            return [result.procedureCode, {
                status: result.status === "OK" ? "SUCCESS" : result.status === "FAILED" ? "FAILED" : result.status === "NOT_IN_CODE_LIST" ? "NOT_IN_CODE_LIST" : "UNAVAILABLE",
                http_status: result.httpStatus ?? errorDetail?.http_status ?? null,
                failure_kind: errorDetail?.failure_kind || (result.status === "UNAVAILABLE" ? "NO_USABLE_BENEFIT_BUCKET" : null),
                error: result.error || errorDetail?.error || null
            }];
        }));
        const returnedApiCodes = new Set(rawByCode.keys ? [...rawByCode.keys()] : []);
        const mandatoryCodesNotAttempted = MANDATORY_PROCEDURE_CODES.filter(code => !returnedApiCodes.has(code));
        const pdfOnlyCodes = mergedProcedureRows.filter(row => row?.result_source === "PDF_ONLY").map(row => normalizeCode(row.procedureCode));
        const pdfSupplementedApiFailureCodes = mergedProcedureRows
            .filter(row => /^PDF_WITH_API_(?:FAILURE|UNAVAILABLE)$/.test(String(row?.result_source || "")))
            .map(row => normalizeCode(row.procedureCode));
        const parsedPdfRows = toArray(parsedPdfDocument?.structured?.benefit_breakdown?.categories).reduce((count, group) => count + toArray(group?.procedures).length, 0);
        outputBody.extraction_metrics = {
            mandatory_code_count: MANDATORY_PROCEDURE_CODES.length,
            supplemental_code_count: SUPPLEMENTAL_PROCEDURE_CODES.length,
            configured_code_count: PROCEDURE_CODES.length,
            api_attempt_count: Number.isFinite(rawByCode.__attemptCount) ? rawByCode.__attemptCount : 0,
            api_success_count: successfulProcedureCount,
            api_failed_count: failedProcedureCodes.length,
            api_unavailable_count: apiUnavailableCodes.length,
            api_failed_codes: failedProcedureCodes,
            api_unavailable_codes: apiUnavailableCodes,
            api_not_in_code_list_codes: apiNotInCodeListCodes,
            api_outcomes_by_code: apiOutcomeByCode,
            pdf_rows_parsed: parsedPdfRows,
            pdf_only_code_count: new Set(pdfOnlyCodes).size,
            pdf_only_codes: uniqueStrings(pdfOnlyCodes),
            pdf_supplemented_api_failure_count: new Set(pdfSupplementedApiFailureCodes).size,
            pdf_supplemented_api_failure_codes: uniqueStrings(pdfSupplementedApiFailureCodes),
            merged_result_count: mergedProcedureRows.length,
            mandatory_codes_not_attempted: mandatoryCodesNotAttempted
        };

        // Backward-compatible per-row Star checklist. Downstream comparator/spec are unchanged.
        outputBody.checklist = buildChecklistOutput(outputBody, {
            nonPpo: nonPpoEvidence,
            termination
        });
        outputBody.plan_provisions = buildPlanProvisions(outputBody, {
            nonPpo: nonPpoEvidence,
            pdfNotes: [
                pdfEligibility.overview_notice,
                pdfEligibility.client_information,
                pdf?.benefit_breakdown?.notice,
                ...toArray(pdf?.additional_information?.notes)
            ],
            pdfFamilyDeductible: pdfEligibility.maximum_and_deductibles?.deductible?.family?.amount ?? null,
            pdfFamilyMaximum: pdfEligibility.maximum_and_deductibles?.maximums?.general?.family_max ?? null,
            planName: patientAndPlan?.plan?.plan_name || null
        });
        const resultCodes = new Set(toArray(coverages?.procedure_code_search?.results).map(item => normalizeCode(item?.procedureCode)).filter(Boolean));
        const profileRequirements = toArray(TOOLKIT_REQUIREMENTS_SPEC?.requirements).filter(item => item.is_marked_requirement);
        outputBody.requirements_assessment = {
            spec_schema_version: TOOLKIT_REQUIREMENTS_SPEC?.spec_schema_version || null,
            workbook_sha256: TOOLKIT_REQUIREMENTS_SPEC?.source_workbook_sha256 || null,
            scope: "all_workbook_profiles",
            global_code_scope: {
                mandatory_codes: MANDATORY_PROCEDURE_CODES.length,
                supplemental_codes: SUPPLEMENTAL_PROCEDURE_CODES.length,
                configured_codes: PROCEDURE_CODES.length,
                code_extraction_applies_only_to_current_portal_context: true
            },
            selected_profile: null,
            profile_status: "NOT_REQUIRED_GLOBAL_MODE",
            requirement_count: profileRequirements.length,
            code_requirement_count: profileRequirements.filter(item => item.codes.length > 0).length,
            non_code_requirement_count: profileRequirements.filter(item => item.codes.length === 0).length,
            live_client_plan_validation: "NOT_ESTABLISHED_BY_GLOBAL_CODE_EXTRACTION",
            fields: profileRequirements.map(item => ({
                requirement_id: `${item.sheet_name}::${item.excel_row}`,
                sheet_name: item.sheet_name,
                excel_row: item.excel_row,
                description: item.description,
                codes: item.codes,
                required_fields: item.required_fields,
                remarks_comments: item.remarks_comments,
                extraction_code_status: item.codes.length ? (item.codes.every(code => resultCodes.has(code)) ? "MERGED_RESULT_PRESENT" : "RESULT_MISSING") : "NON_CODE_REQUIREMENT",
                code_api_status: item.codes.length ? Object.fromEntries(item.codes.map(code => [code, outputBody.extraction_metrics.api_outcomes_by_code[code]?.status || "NOT_ATTEMPTED"])) : {},
                source_code_evidence: Object.fromEntries(item.codes.map(code => {
                    const row = mergedProcedureRows.find(candidate => normalizeCode(candidate?.procedureCode) === code) || null;
                    return [code, row ? {
                        api_status: outputBody.extraction_metrics.api_outcomes_by_code[code]?.status || "NOT_ATTEMPTED",
                        result_source: row.result_source || "API",
                        percentCovered: row.percentCovered ?? null,
                        waitingPeriod: row.waitingPeriod ?? null,
                        waitingPeriodMetDate: row.waitingPeriodMetDate ?? null,
                        applicable_limitations: toArray(row.applicable_limitations),
                        utilization_history_status: row.utilization_history_status || "NOT_RETURNED",
                        utilization_history: toArray(row.utilization_history),
                        source_values: row.source_values || null
                    } : { api_status: "NOT_ATTEMPTED", result_source: null }];
                })),
                required_field_results: item.required_fields.map(field => {
                    const codeOutcomes = item.codes.map(code => outputBody.extraction_metrics.api_outcomes_by_code[code]?.status || "NOT_ATTEMPTED");
                    const allApiSuccess = codeOutcomes.length > 0 && codeOutcomes.every(status => status === "SUCCESS");
                    const anyApiFailure = codeOutcomes.some(status => status === "FAILED");
                    const anyUnavailable = codeOutcomes.some(status => status === "UNAVAILABLE" || status === "NOT_ATTEMPTED");
                    let status = "REQUIRES_PLAN_LEVEL_EVIDENCE";
                    if (item.codes.length) {
                        status = anyApiFailure ? "API_FAILED" : anyUnavailable ? "SOURCE_RESULT_INCOMPLETE_OR_UNAVAILABLE" : allApiSuccess ? "EXTRACTION_ONLY_NOT_CLIENT_VALIDATION" : "SOURCE_RESULT_INCOMPLETE_OR_UNAVAILABLE";
                    }
                    return {
                        field,
                        status,
                        source_text: item.description,
                        remarks_comments: item.remarks_comments,
                        code_api_status: Object.fromEntries(item.codes.map((code, index) => [code, codeOutcomes[index]])),
                        client_plan_value_status: "NOT_VALIDATED_BY_GLOBAL_CODE_EXTRACTION",
                        note: field === "Confirmative Question (Yes/No)"
                            ? "Question answer requires explicit question-specific evaluation against the selected member/plan sources; successful code lookup alone is not a Yes/No answer."
                            : item.codes.length && allApiSuccess
                                ? "The API code lookup succeeded for this current portal context; this is not a client-profile or benefit-field validation."
                                : undefined
                    };
                }),
                validation_status: "NOT_CLIENT_VALIDATED_BY_EXTRACTION_ALONE"
            }))
        };
        outputBody.crawl_statistics.checklist = {
            total_rows: outputBody.checklist.summary.total_rows,
            FOUND: outputBody.checklist.summary.FOUND,
            PARTIAL: outputBody.checklist.summary.PARTIAL,
            NOT_STATED: outputBody.checklist.summary.NOT_STATED,
            NOT_FOUND: outputBody.checklist.summary.NOT_FOUND
        };
        return sanitizeForOutput(outputBody);
    }

    function coreTransactionForOutput(state, key, endpoint, requestBody, responseBody, ppoFilter = false) {
        const existing = state.coreTransactions?.[key];
        const response = responseBody === null || responseBody === undefined
            ? null
            : (ppoFilter ? sanitizePpoNetworkDataForOutput(responseBody) : sanitizeForOutput(responseBody));
        if (existing) {
            return {
                endpoint,
                request: sanitizeForOutput(existing.request || {
                    method: "POST", endpoint, query: "", body: requestBody
                }),
                http_status: existing.http_status ?? null,
                captured_at: existing.captured_at || null,
                response
            };
        }
        return {
            endpoint,
            request: requestBody ? {
                method: "POST",
                endpoint,
                query: "",
                headers: {},
                body: sanitizeForOutput(requestBody)
            } : null,
            http_status: null,
            captured_at: null,
            response
        };
    }

    function actualCapturedEndpoints(state, procedures) {
        const endpoints = [];
        if (state.memberSearchResponse) endpoints.push(MEMBER_SEARCH_PATH);
        if (state.memberBenefitsResponse) endpoints.push(MEMBER_BENEFITS_PATH);
        if (state.routineProceduresResponse) endpoints.push(ROUTINE_PROCEDURES_PATH);
        if (state.clientSearchResponse) endpoints.push(CLIENT_SEARCH_PATH);
        if (toArray(procedures).some(item => !item?.error)) endpoints.push(PROCEDURE_SEARCH_PATH);
        endpoints.push(...state.supportingApiResponses.map(item => item.endpoint));
        return uniqueStrings(endpoints);
    }

    function normalizeProcedure(code, raw, error) {
        if (!Array.isArray(raw)) {
            return {
                procedure_code: code,
                description: PROCEDURE_LABELS[code] || code,
                category: CATEGORY_BY_CODE[code] || "N/A",
                benefit_status: "Unknown",
                benefit_level: "N/A",
                oon_benefit_level: "N/A",
                deductible: "N/A",
                age_limit: "N/A",
                frequency_limit: "N/A",
                waiting_period: "N/A",
                late_date_of_service: "NH",
                history_dates: [],
                number_of_quads: "N/A",
                networks: [],
                error: error || "No API response returned."
            };
        }

        // Business requirement: use PPO Dentist only. "Premier Dentist" and
        // "Non-PPO Dentist" buckets are deliberately ignored, even when PPO is missing.
        const ppoBuckets = raw.filter(isExactPpoBucket);
        const networkRecords = ppoBuckets.map(bucket => normalizeNetworkBucket(code, bucket)).filter(Boolean);
        const preferred = networkRecords[0] || null;
        const allLimitations = uniqueStrings(networkRecords.flatMap(item => item.limitations));
        const allWaiting = uniqueStrings(networkRecords.flatMap(item => item.waiting_periods));
        const allHistory = uniqueStrings(networkRecords.flatMap(item => item.history_dates));
        const ageLimit = firstMeaningful(networkRecords.map(item => item.age_limit));
        const frequency = firstMeaningful(networkRecords.map(item => item.frequency_limit));
        const deductible = firstMeaningful(networkRecords.map(item => item.deductible));
        const latest = latestDate(allHistory);

        return {
            procedure_code: code,
            description: preferred?.description || PROCEDURE_LABELS[code] || code,
            category: CATEGORY_BY_CODE[code] || preferred?.category || "N/A",
            network: "PPO Dentist",
            benefit_status: preferred?.benefit_status || "Unknown",
            benefit_level: preferred?.benefit_level || "N/A",
            // Kept for backward compatibility; intentionally never populated.
            oon_benefit_level: "N/A",
            deductible: deductible || "N/A",
            age_limit: ageLimit || "N/A",
            frequency_limit: frequency || "N/A",
            waiting_period: allWaiting.length ? allWaiting.join(" | ") : "N/A",
            late_date_of_service: latest || "NH",
            history_dates: allHistory,
            number_of_quads: parseQuads(allLimitations.join(" ")) || "N/A",
            exclusions_and_limitations: allLimitations,
            networks: networkRecords,
            // Raw procedure diagnostics are also PPO-only so output does not contain
            // Premier/Non-PPO benefit levels by accident.
            raw_api_response: sanitizeForOutput(ppoBuckets),
            error: error || (ppoBuckets.length ? null : "No PPO Dentist benefit bucket returned for this code.")
        };
    }

    const PROCEDURE_LIMITATION_MATCHERS = Object.freeze({
        D0180: /oral\s+examin|examinations?\s+by\s+a\s+specialist/i,
        D0120: /oral\s+examin/i,
        D0140: /oral\s+examin/i,
        D0150: /oral\s+examin/i,
        D0210: /full\s+mouth\s+x-?rays?|panorex|panoramic/i,
        D0330: /full\s+mouth\s+x-?rays?|panorex|panoramic/i,
        D0364: /cbct|cone\s*beam|tomograph/i,
        D0431: /oral\s+cancer|screening|adjunctive\s+test/i,
        D0272: /bitewing/i,
        D0274: /bitewing/i,
        D1510: /space\s+maintain/i,
        D1110: /prophylaxis|cleanings?/i,
        D1120: /prophylaxis|cleanings?/i,
        D1206: /fluoride/i,
        D1208: /fluoride/i,
        D1351: /sealant/i,
        D2140: /amalgam|restoration/i,
        D2160: /amalgam|restoration/i,
        D2331: /posterior\s+composite|resin\s+restoration/i,
        D2391: /posterior\s+composite|resin\s+restoration/i,
        D2620: /inlays?|onlays?/i,
        D2740: /cast\s+restoration|crowns?/i,
        D2950: /cast\s+restoration|cores?|substructures?|crowns?/i,
        D2962: /porcelain|laminate|veneer/i,
        D2980: /repair|crown/i,
        D6750: /bridgework|bridges?|crowns?|cast\s+restoration/i,
        D4249: /crown\s+lengthening/i,
        D4341: /root\s+planing|scaling/i,
        D4346: /gingival|inflammation|scaling/i,
        D4355: /full\s+mouth\s+debridement/i,
        D4910: /periodontal|perio\s+maintenance/i,
        D5110: /full\s+and\s+partial\s+dentures?|dentures?/i,
        D5212: /full\s+and\s+partial\s+dentures?|partial\s+dentures?/i,
        D5213: /full\s+and\s+partial\s+dentures?|partial\s+dentures?/i,
        D5740: /full\s+and\s+partial\s+dentures?|reline/i,
        D5860: /full\s+and\s+partial\s+dentures?|over\s*denture/i,
        D5899: /prosthodontic|removable|denture/i,
        D5995: /periodontal|medicament/i,
        D6010: /implants?/i,
        D6056: /implants?|abutment/i,
        D6057: /implants?|abutment/i,
        D6058: /implants?|abutment|crown/i,
        D6065: /implants?/i,
        D6194: /implants?/i,
        D6245: /bridgework|bridges?/i,
        D6750: /bridgework|bridges?|crowns?/i,
        D7210: /extraction|surgical/i,
        D9230: /nitrous|anesthesia|sedation/i,
        D9243: /anesthesia|sedation/i,
        D9223: /anesthesia|sedation/i,
        D9944: /occlusal\s+guards?/i
    });

    function splitRuleText(value) {
        return toStringList(value)
            .flatMap(text => cleanText(text).split(/(?<=[.!?])\s+(?=[A-Z0-9])/))
            .map(cleanText)
            .filter(Boolean);
    }

    function selectRelevantProcedureLimitations(code, coverages, leaf) {
        const leafRules = splitRuleText(leaf?.exclusionsAndLimitations);
        const matcher = ruleMatcherFor(code);
        const parentRules = coverages
            .filter(item => item !== leaf)
            .flatMap(item => splitRuleText(item?.exclusionsAndLimitations));
        const matchedParent = matcher ? parentRules.filter(text => matcher.test(text)) : [];
        return uniqueStrings([...leafRules, ...matchedParent]);
    }

    function selectRelevantProcedureWaitingPeriods(code, coverages, leaf) {
        const leafRules = splitRuleText(leaf?.waitingPeriods);
        const matcher = ruleMatcherFor(code);
        const parentRules = coverages
            .filter(item => item !== leaf)
            .flatMap(item => splitRuleText(item?.waitingPeriods));
        const matchedParent = matcher ? parentRules.filter(text => matcher.test(text)) : [];
        return uniqueStrings([...leafRules, ...matchedParent]);
    }

    function normalizeNetworkBucket(code, bucket) {
        if (!bucket || typeof bucket !== "object") return null;
        const coverages = Array.isArray(bucket.coverages) ? bucket.coverages : [];
        const network = uniqueStrings(Array.isArray(bucket.networks) ? bucket.networks : [bucket.networks]).join(", ") || "N/A";
        const leaf = coverages.find(item => normalizeCode(item?.procedureId || item?.procedure) === code)
            || [...coverages].reverse().find(item => Number(item?.level) === Math.max(...coverages.map(x => Number(x?.level) || 0)))
            || coverages[coverages.length - 1]
            || {};
        const coverage = leaf.coverage || {};
        const percent = normalizePercent(coverage.percent);
        const limitations = selectRelevantProcedureLimitations(code, coverages, leaf);
        const waiting = selectRelevantProcedureWaitingPeriods(code, coverages, leaf);
        const utilization = coverages.flatMap(item => toArray(item?.utilizationBenefits));
        const historyDates = collectDates(utilization);
        const combinedText = uniqueStrings([...limitations, ...waiting, ...collectStrings(utilization)]).join(" ");
        const notCovered = coverage.childValuesNotCovered === true || /\bnot\s+covered\b/i.test(combinedText);
        const benefitStatus = notCovered || percent === "0%" ? "Not Covered" : (percent !== "N/A" ? "Covered" : "Unknown");

        return {
            network,
            description: PROCEDURE_LABELS[code] || (normalizeCode(leaf.procedure) === code ? code : String(leaf.procedure || code)),
            category: coverages[0]?.procedure || CATEGORY_BY_CODE[code] || "N/A",
            benefit_status: benefitStatus,
            benefit_level: percent,
            copay: coverage.hasCoPay ? moneyValue(coverage.coPayFee) : "N/A",
            medically_necessary: Boolean(coverage.medicallyNecessary || coverage.childValuesMedicallyNecessary),
            deductible: parseDeductible(combinedText),
            age_limit: parseAgeLimit(combinedText),
            frequency_limit: parseFrequency(limitations),
            waiting_periods: waiting,
            limitations,
            history_dates: historyDates,
            utilization_benefits: sanitizeForOutput(utilization),
            coverage_path: sanitizeForOutput(coverages.map(item => ({
                level: item.level,
                procedure: item.procedure,
                procedure_id: item.procedureId,
                coverage: item.coverage,
                exclusions_and_limitations: item.exclusionsAndLimitations,
                waiting_periods: item.waitingPeriods,
                radio_graphs_required: item.radioGraphsRequired,
                remarks_required: item.remarksRequired
            })))
        };
    }

    // =====================================================================
    // Requested field map and business questions
    // =====================================================================

    function buildRequestedFieldMap(procMap, provisions) {
        const map = {};
        for (const [category, codes] of Object.entries(CATEGORY_CODES)) {
            map[category] = {};
            for (const code of codes) {
                map[category][`${PROCEDURE_LABELS[code] || code} (${code})`] = procMap[code] || null;
            }
        }

        map.EXAMS["Do D0120,D0150 Share a frequency with D0140?"] = provisions.d0120_d0150_share_frequency_with_d0140;
        map.PREVENTATIVE["Permanent Un-restored Molars only?"] = provisions.permanent_unrestored_molars_only;
        map["BASIC RESTORATIVE"]["Posterior composites downgraded to amalgam?"] = provisions.posterior_composites_downgraded_to_amalgam;
        map["MAJOR RESTORATIVE"]["Porcelain crowns downgraded on posterior teeth"] = provisions.porcelain_crowns_downgraded_on_posterior_teeth;
        map["MAJOR RESTORATIVE"]["Can D2950 be done same day as crown?"] = provisions.d2950_same_day_as_crown;
        map.PERIODONTICS["Number of quads for the code D4341"] = provisions.d4341_number_of_quads;
        map.PERIODONTICS["Do D4910 and D1110 share a frequency?"] = provisions.d4910_d1110_share_frequency;
        map.ORTHODONTICS["Payment Frequency"] = provisions.ortho_payment_frequency;
        map.ORTHODONTICS["Ortho Age Limit"] = provisions.ortho_age_limit;
        return map;
    }

    function sameFrequency(procMap, codes) {
        const values = codes.map(code => canonicalFrequency(procMap[code]?.frequency_limit));
        if (values.some(value => !value)) return "N/A";
        return new Set(values).size === 1 ? "Yes" : "No";
    }

    function sealantMolarsOnly(proc) {
        const text = procedureText(proc);
        if (!text || text === "N/A") return "N/A";
        const molar = /\bmolars?\b/i.test(text);
        const permanent = /\bpermanent\b/i.test(text);
        const unrestored = /\bun[- ]?restored\b|\bcaries[- ]?free\b|\bnon[- ]?restored\b/i.test(text);
        return molar && permanent && unrestored ? "Yes" : (molar ? "No" : "N/A");
    }

    function posteriorCompositeDowngrade(procMap) {
        const text = `${procedureText(procMap.D2331)} ${procedureText(procMap.D2140)}`;
        if (!text.trim()) return "N/A";
        const alternate = /alternate\s+benefit|least\s+costly\s+alternative|downgrad/i.test(text);
        const amalgam = /amalgam/i.test(text);
        const posterior = /posterior|molar|premolar|back\s+tooth/i.test(text);
        if (alternate && (amalgam || posterior)) return "Yes";
        if (/no\s+alternate\s+benefit|not\s+downgrad/i.test(text)) return "No";
        return "N/A";
    }

    function porcelainCrownDowngrade(proc) {
        const text = procedureText(proc);
        if (!text.trim()) return "N/A";
        const alternate = /alternate\s+benefit|least\s+costly\s+alternative|downgrad/i.test(text);
        const posterior = /posterior|molar|premolar|back\s+tooth/i.test(text);
        const material = /porcelain|ceramic|metal|base\s+metal/i.test(text);
        if (alternate && (posterior || material)) return "Yes";
        if (/no\s+alternate\s+benefit|not\s+downgrad/i.test(text)) return "No";
        return "N/A";
    }

    function d2950SameDayCrown(procMap) {
        const buildUp = procMap.D2950;
        const crown = procMap.D2740;
        if (!buildUp || buildUp.benefit_status === "Not Covered") return "No";
        const text = `${procedureText(buildUp)} ${procedureText(crown)}`;
        if (/not\s+(?:payable|covered).*same\s+day|separate\s+date\s+of\s+service/i.test(text)) return "No";
        if (buildUp.benefit_status === "Covered" && crown?.benefit_status === "Covered") return "Yes";
        return "N/A";
    }

    function numberOfQuads(proc) {
        return parseQuads(procedureText(proc)) || "N/A";
    }

    function orthoPaymentFrequency(procMap) {
        const text = ["D8010", "D8080", "D8090"].map(code => procedureText(procMap[code])).join(" ");
        const sentence = sentenceContaining(text, /payment|installment|monthly|quarterly|frequency/i, /ortho|treatment|case|payment/i);
        return sentence || "N/A";
    }

    function orthoAgeLimit(procMap) {
        return firstMeaningful(["D8010", "D8080", "D8090"].map(code => procMap[code]?.age_limit)) || "N/A";
    }

    // =====================================================================
    // Checklist export — one record per row of the audit checklist workbook
    // (checklist_text_extracted.xlsx, SL NO 1-112). The Star client comparator
    // reads `checklist.rows[]` and matches on `sl_no` / `item` / `code`.
    // Every value is either taken from the portal/PDF data already captured or
    // derived from its wording; nothing is guessed. When the portal does not
    // state something the value is null and the row says why.
    // =====================================================================

    const CHECKLIST_SCHEMA_VERSION = "1.0";
    // flags: F=Frequency C=Coverage % A=Age restriction Q=Confirmative (Yes/No) H=History,
    // in the same column order as the workbook.
    const CHECKLIST_SPEC = Object.freeze([
        { sl: 1, item: "D0120 - Routine/Regular Exams", code: "D0120", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 2, item: "D1110 - Routine/Regular Cleaning (Adult)", code: "D1110", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 3, item: "D0220 - Diagnostic XraysPA", code: "D0220", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 4, item: "D0230 - Diagnostic Xray PA addtn", code: "D0230", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 5, item: "D0240 - Diagnostic Xray", code: "D0240", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 6, item: "D0150 comprehensive oral evaluation", code: "D0150", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 7, item: "D0150 fee per provider?", code: "D0150", kind: "procedure", flags: "F....", remarks: "Need to capture Frequency Limitation REP/WEBSITE/FAX" },
        { sl: 8, item: "D0140 Limited Exam", code: "D0140", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 9, item: "D0120 and D0140 share freq?", code: "D0120", kind: "question", key: "d0120_d0140_share_frequency", flags: "...Q.", remarks: "Need to confirm does D0120 and D0140 share freq? - yes/No" },
        { sl: 10, item: "D1110 - Routine/Regular Cleaning (Adult)", code: "D1110", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 11, item: "D1120 - Routine/Regular Cleaning (Child)", code: "D1120", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 12, item: "D0210 - complete series of radiographic images", code: "D0210", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 13, item: "D0330 - panoramic radiographic image", code: "D0330", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 14, item: "FMX and Pano share freq?", code: null, kind: "question", key: "fmx_pano_share_frequency", flags: "...Q.", remarks: "Need to confirm FMX and Pano share freq?" },
        { sl: 15, item: "D0274 XraysBitewings", code: "D0274", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 16, item: "D1351 Sealants", code: "D1351", kind: "procedure", flags: "FCA.H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 17, item: "D1206 topical application of fluoride va...", code: "D1206", kind: "procedure", flags: "FCA.H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 18, item: "D1208 topical application of fluoride - c...", code: "D1208", kind: "procedure", flags: "FCA.H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 19, item: "D0367 topical application of fluoride - c...", code: "D0367", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 20, item: "D1516 Space Maintainer", code: "D1516", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 21, item: "D2331 resin based composite - two surf...", code: "D2331", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 22, item: "D2140 amalgam - one surface, primary", code: "D2140", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 23, item: "D2391 resin based composite - one surf...", code: "D2391", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 24, item: "Posterior composite downgrade?", code: null, kind: "question", key: "posterior_composite_downgrade", flags: "...Q.", remarks: "Need to confirm Posterior composite downgrade?" },
        { sl: 25, item: "D2610 inlay - porcelain/ceramic - one s...", code: "D2610", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 26, item: "D2642 onlay - porcelain/ceramic - two s...", code: "D2642", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 27, item: "D4381 Arestin", code: "D4381", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 28, item: "D4355 Full Mouth Debridement", code: "D4355", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 29, item: "D4346 scaling in presence of generalized...", code: "D4346", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 30, item: "D4341 periodontal scaling and root planing", code: "D4341", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 31, item: "SRP Quads per day?", code: null, kind: "question", key: "srp_quads_per_day", flags: "...Q.", remarks: "Need to confirm SRP Quads per day?" },
        { sl: 32, item: "D4910 Perio Maintenance", code: "D4910", kind: "procedure", flags: "FC..H", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 33, item: "Prophy and Perio maintenance share freq?", code: null, kind: "question", key: "prophy_perio_share_frequency", flags: "...Q.", remarks: "Need to confirm if D4910 is sharing frequency with D1110 - Yes/No" },
        { sl: 34, item: "D2740 Crowns", code: "D2740", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 35, item: "Crown Downgrade based on material?", code: null, kind: "question", key: "crown_downgrade_by_material", flags: "...Q.", remarks: "Need to confirm Crown Downgrade based on material?" },
        { sl: 36, item: "D2750 Restorative Crowns", code: "D2750", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 37, item: "D2950 Core Build Up", code: "D2950", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 38, item: "D5110 complete denture - maxillary", code: "D5110", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 39, item: "D5212 mandibular partial denture - res...", code: "D5212", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 40, item: "D5511 repair broken complete denture", code: "D5511", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 41, item: "D5650 add tooth to existing partial denture", code: "D5650", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 42, item: "D5810 interim complete denture (maxi...)", code: "D5810", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 43, item: "D5821 interim partial denture (including...)", code: "D5821", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 44, item: "D5912 facial moulage (complete)", code: "D5912", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 45, item: "D6010 surgical placement of implant bo...", code: "D6010", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 46, item: "D6104 bone graft at time of implant pla...", code: "D6104", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 47, item: "D6190 radiographic/surgical implant ind...", code: "D6190", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 48, item: "D6056 prefabricated abutment - includ...", code: "D6056", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 49, item: "D6057 custom fabricated abutment - in...", code: "D6057", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 50, item: "D6058 abutment supported porcelain/...", code: "D6058", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 51, item: "D6240 pontic - porcelain fused to high...", code: "D6240", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 52, item: "D6245 pontic - porcelain/ceramic", code: "D6245", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 53, item: "D9110 palliative (emergency) treatment...", code: "D9110", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 54, item: "D9222 deep sedation/general anesthes...", code: "D9222", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 55, item: "D9230 inhalation of nitrous oxide/anal...", code: "D9230", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 56, item: "D9239 intravenous moderate (conscious...)", code: "D9239", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 57, item: "D9243 intravenous moderate (conscious...)", code: "D9243", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 58, item: "D9310 consultation - diagnostic service", code: "D9310", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 59, item: "D9612 therapeutic parenteral drugs, tw...", code: "D9612", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 60, item: "D9630 Adjunct", code: "D9630", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 61, item: "D9944 Adjunct Nightguards", code: "D9944", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 62, item: "D9944 Bruxism only?", code: "D9944", kind: "question", key: "d9944_bruxism_only", flags: "...Q.", remarks: "Need to confirm \"D9944 Bruxism only?\"" },
        { sl: 63, item: "D9946 occlusal guard - hard appliance, ...", code: "D9946", kind: "procedure", flags: "FC...", remarks: "Need to capture Frequency Limitation and Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 64, item: "D9947 Custom sleep apnea appliance f...", code: "D9947", kind: "procedure", flags: "FC...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 65, item: "D3221 pulpal debridement, primary s...", code: "D3221", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 66, item: "D3310 endodontic therapy, anterior to...", code: "D3310", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 67, item: "D3330 endodontic therapy, molar tooth", code: "D3330", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 68, item: "D3346 retreatment of previous root canal", code: "D3346", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 69, item: "D3348 retreatment of previous root canal", code: "D3348", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 70, item: "D4260 Osseous Surgery", code: "D4260", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 71, item: "D4921 gingival irrigation - per quadrant", code: "D4921", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 72, item: "D7140 extraction, erupted tooth or exposed...", code: "D7140", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 73, item: "D7210 extraction, erupted tooth requiring...", code: "D7210", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 74, item: "D7230 removal of impacted tooth - partially...", code: "D7230", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 75, item: "D7240 removal of impacted tooth - completely...", code: "D7240", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 76, item: "D7310 alveoloplasty in conjunction with...", code: "D7310", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 77, item: "D7953 bone replacement graft for ridge...", code: "D7953", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 78, item: "D8080 comprehensive orthodontic treatment...", code: "D8080", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 79, item: "D8090 comprehensive orthodontic treatment...", code: "D8090", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 80, item: "D8220 fixed appliance therapy", code: "D8220", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX" },
        { sl: 81, item: "D8680 orthodontic retention (removal of...)", code: "D8680", kind: "procedure", flags: ".C...", remarks: "Capture Co Insurance Percentage through REP/WEBSITE/FAX", clipped: true },
        { sl: 82, item: "Subscriber Age Limit?", code: null, kind: "field", key: "subscriber_age_limit", flags: ".CA..", remarks: "Need to confirm Subscriber Age Limit?" },
        { sl: 83, item: "Dependent Age Limit?", code: null, kind: "field", key: "dependent_age_limit", flags: ".CA..", remarks: "Need to confirm Dependent Age Limit?" },
        { sl: 84, item: "Insurance Name", code: null, kind: "field", key: "insurance_name", flags: "...Q.", remarks: "While selecting the insurance company name or carrier name automatically claims mailing address will be captured" },
        { sl: 85, item: "Group Name", code: null, kind: "field", key: "group_name", flags: "....H", remarks: "Need to confirm the Group Name/ Group Number through REP/WEBSITE/FAX" },
        { sl: 86, item: "Group Number", code: null, kind: "field", key: "group_number", flags: "....H", remarks: "Need to confirm the Group Name/ Group Number through REP/WEBSITE/FAX" },
        { sl: 87, item: "Fee Schedule", code: null, kind: "field", key: "fee_schedule", flags: "....H", remarks: "Need to confirm Fee Schedule" },
        { sl: 88, item: "Insurance Address", code: null, kind: "field", key: "insurance_address", flags: "....H", remarks: "Need to confirm Insurance Address" },
        { sl: 89, item: "Insurance Phone", code: null, kind: "field", key: "insurance_phone", flags: "....H", remarks: "Need to confirm Insurance Phone" },
        { sl: 90, item: "Payor ID", code: null, kind: "field", key: "payor_id", flags: "....H", remarks: "Need to confirm the Insurance E Claim payer id through REP/WEBSITE/FAX" },
        { sl: 91, item: "In Network", code: null, kind: "field", key: "in_network", flags: "....H", remarks: "Need to confirm In Network or Out of network" },
        { sl: 92, item: "Patient Eff Date", code: null, kind: "field", key: "patient_eff_date", flags: "....H", remarks: "Need to confirm Patient Eff Date" },
        { sl: 93, item: "Eligibility Term Date", code: null, kind: "field", key: "eligibility_term_date", flags: "....H", remarks: "Need to confirm Eligibility Term Date" },
        { sl: 94, item: "Does plan has OON Benefits?", code: null, kind: "field", key: "oon_benefits", flags: "....H", remarks: "Need to confirm Does plan has OON Benefits?" },
        { sl: 95, item: "Starting Month of Plan Year", code: null, kind: "field", key: "plan_year_start_month", flags: "....H", remarks: "Need to confirm Starting Month of Plan Year" },
        { sl: 96, item: "Yearly Max", code: null, kind: "field", key: "yearly_max", flags: "....H", remarks: "Need to confirm Yrly max" },
        { sl: 97, item: "Individual Deductible", code: null, kind: "field", key: "individual_deductible", flags: "....H", remarks: "Need to confirm Individual Deductible" },
        { sl: 98, item: "Family Deductible", code: null, kind: "field", key: "family_deductible", flags: "....H", remarks: "Need to confirm Family Deductible" },
        { sl: 99, item: "Yearly Max/ used amount", code: null, kind: "field", key: "yearly_max_used", flags: "....H", remarks: "Need to confirm Yrly max used amount" },
        { sl: 100, item: "Individual Deductible/ used amount", code: null, kind: "field", key: "individual_deductible_used", flags: "....H", remarks: "Need to confirm Individual Deductible used amount" },
        { sl: 101, item: "Family Deductible/ used amount", code: null, kind: "field", key: "family_deductible_used", flags: "....H", remarks: "Need to confirm Family Deductible used amount" },
        { sl: 102, item: "Deductible Applies to Preventative", code: null, kind: "field", key: "deductible_applies_preventive", flags: "....H", remarks: "Need to confirm Deductible applies to Preventative, Diagnostic services through REP/WEBSITE/FAX" },
        { sl: 103, item: "Deductible Applies to Diagnostic", code: null, kind: "field", key: "deductible_applies_diagnostic", flags: "....H", remarks: "Need to confirm Deductible applies to Preventative, Diagnostic services through REP/WEBSITE/FAX" },
        { sl: 104, item: "Ortho Maximum", code: null, kind: "field", key: "ortho_max", flags: "....H", remarks: "Need to confirm Ortho max" },
        { sl: 105, item: "Orthodontics Deductible Amount", code: null, kind: "field", key: "ortho_deductible_amount", flags: "....H", remarks: "Need to confirm Orthodontics Deductible Amount" },
        { sl: 106, item: "Orthodontics Deductible Met Amount", code: null, kind: "field", key: "ortho_deductible_met", flags: "....H", remarks: "Need to confirm Orthodontics Deductible met Amount" },
        { sl: 107, item: "Orthodontics Used Amount", code: null, kind: "field", key: "ortho_used", flags: "....H", remarks: "Need to confirm Orthodontics Used Amount" },
        { sl: 108, item: "Is there a Waiting Period", code: null, kind: "field", key: "waiting_period", flags: "....H", remarks: "Need to confirm Is there a Waiting Period" },
        { sl: 109, item: "Does Missing Tooth Clause Apply?", code: null, kind: "field", key: "missing_tooth_clause", flags: "....H", remarks: "Need to confirm Does Missing Tooth Clause Apply?" },
        { sl: 110, item: "Are Major Services Paid on Prep or Seat", code: null, kind: "field", key: "major_paid_on_prep_or_seat", flags: "....H", remarks: "Need to confirm Are Major Services Paid on Prep or Seat", clipped: true },
        { sl: 111, item: "PreAuthorize Over $", code: null, kind: "field", key: "preauth_over_amount", flags: "....H", remarks: "Need to confirm PreAuthorize Over $" },
        { sl: 112, item: "Coordination of Benefits", code: null, kind: "field", key: "coordination_of_benefits", flags: "....H", remarks: "Need to confirm Coordination of Benefits" }
    ]);

    // Rule matchers pick, out of the category-level "Exclusions And Limitations"
    // sentences, only the ones that talk about the given code.
    const CHECKLIST_RULE_MATCHERS = Object.freeze({
        D0120: /oral\s+examin/i, D0140: /oral\s+examin/i, D0150: /oral\s+examin/i,
        D0210: /full\s+mouth\s+x-?rays?|panorex|panoramic/i,
        D0330: /full\s+mouth\s+x-?rays?|panorex|panoramic/i,
        D0274: /bitewing/i, D0272: /bitewing/i,
        D0367: /cbct|cone\s*beam/i,
        D1110: /prophylax|cleanings?/i, D1120: /prophylax|cleanings?/i,
        D1206: /fluoride/i, D1208: /fluoride/i,
        D1351: /sealant/i,
        D1516: /space\s+maintain/i, D1510: /space\s+maintain/i,
        D2140: /\bamalgam\b/i, D2160: /\bamalgam\b/i,
        D2331: /\bcomposite|resin/i, D2391: /\bcomposite|resin/i,
        D2610: /\binlays?|onlays?/i, D2642: /\binlays?|onlays?/i,
        D2740: /cast\s+restoration/i, D2750: /cast\s+restoration/i, D2950: /cast\s+restoration|\bcores?\b|substructure/i,
        D3221: /endodon|root\s+canal|pulp/i, D3310: /endodon|root\s+canal/i, D3330: /endodon|root\s+canal/i,
        D3346: /retreat|endodon|root\s+canal/i, D3348: /retreat|endodon|root\s+canal/i,
        D4260: /osseous|periodontal\s+surgery/i,
        D4341: /root\s+planing|scaling/i,
        D4346: /gingival\s+inflammation|full\s+mouth\s+scaling/i,
        D4355: /full\s+mouth\s+debridement/i,
        D4381: /arestin|antimicrobial|chemotherapeutic/i,
        D4910: /periodontal\s+maint|perio\s*maint/i,
        D4921: /gingival\s+irrigation|irrigation/i,
        D5110: /\bdentures?/i, D5212: /\bdentures?/i, D5511: /\bdentures?/i, D5650: /\bdentures?/i,
        D5810: /interim/i, D5821: /interim/i,
        D5912: /moulage|maxillofacial/i,
        D6010: /\bimplants?/i, D6056: /\bimplants?|abutment/i, D6057: /\bimplants?|abutment/i, D6058: /\bimplants?|abutment/i,
        D6104: /\bimplants?|bone\s+graft/i, D6190: /\bimplants?/i,
        D6240: /bridgework|bridges?|pontic/i, D6245: /bridgework|bridges?|pontic/i,
        D7140: /extraction/i, D7210: /extraction|surgical/i, D7230: /impact|extraction/i, D7240: /impact|extraction/i,
        D7310: /alveolo/i, D7953: /bone\s+(?:replacement\s+)?graft|ridge/i,
        D8080: /orthodon/i, D8090: /orthodon/i, D8220: /orthodon/i, D8680: /orthodon|retention/i,
        D9110: /palliative|emergency/i,
        D9222: /anesthesia|sedation/i, D9230: /nitrous|anesthesia|sedation/i, D9239: /anesthesia|sedation/i, D9243: /anesthesia|sedation/i,
        D9310: /consult/i,
        D9612: /parenteral|\bdrugs?\b/i, D9630: /\bdrugs?\b|medicament/i,
        D9944: /occlusal\s+guards?/i, D9946: /occlusal\s+guards?/i, D9947: /sleep\s+apnea/i
    });

    function ruleMatcherFor(code) {
        return CHECKLIST_RULE_MATCHERS[code] || PROCEDURE_LIMITATION_MATCHERS[code] || null;
    }

    // One portal rule = one array entry. Entries are kept whole (not split at full stops)
    // because a statement such as "...for age 13 and under. Limited to once per tooth per
    // lifetime." carries its frequency in the sentence after the first full stop.
    function ruleEntries(value) {
        return toStringList(value).map(cleanText).filter(Boolean);
    }

    function selectApplicableRules(code, coverages, leaf) {
        const matcher = ruleMatcherFor(code);
        const leafRules = ruleEntries(leaf?.exclusionsAndLimitations);
        const parentRules = toArray(coverages)
            .filter(item => item !== leaf)
            .flatMap(item => ruleEntries(item?.exclusionsAndLimitations));
        return uniqueStrings([...leafRules, ...(matcher ? parentRules.filter(text => matcher.test(text)) : [])]);
    }

    const FREQUENCY_RULE_PATTERN = /\b(?:once|twice|\d+\s+times?|per\s+(?:calendar\s+|benefit\s+|contract\s+)?(?:year|quadrant|tooth|lifetime|area|visit|day|arch)|every\s+\d+|in\s+any\s+(?:\w+[- ])?(?:year|month)|\d+\s*(?:consecutive\s+)?months?|\w+[- ]year\s+period|lifetime)\b/i;

    function checklistFrequencySentences(rules) {
        return uniqueStrings(toArray(rules).map(cleanText).filter(text => text && FREQUENCY_RULE_PATTERN.test(text)));
    }

    function extractAgeRestrictions(rules) {
        const found = [];
        const patterns = [
            /\b(?:ages?|people|persons|patients|children)\s+(\d{1,2})(?:\s+years?(?:\s+of\s+age)?)?\s+(?:and|or)\s+(?:under|older|over|younger|above|below)\b/gi,
            /\bages?\s+(\d{1,2})\s*(?:-|–|to|through)\s*(\d{1,2})\b/gi
        ];
        for (const text of toArray(rules).map(cleanText)) {
            for (const pattern of patterns) {
                for (const match of text.matchAll(pattern)) found.push(cleanText(match[0]));
            }
        }
        return uniqueStrings(found);
    }

    // Collect the rule sentences that apply to one procedure code, from (1) the
    // code's own captured limitations and (2) the category records of every
    // ancestor in its procedurePath, filtered through the code's matcher.
    function checklistRulesForCode(code, result, exclusionRecords) {
        const rules = [];
        for (const item of toArray(result?.applicable_limitations)) rules.push(item);
        for (const item of toArray(result?.limitations)) {
            if (typeof item === "string") rules.push(item);
            else rules.push(...ruleEntries(item?.exclusionsAndLimitations));
        }
        const matcher = ruleMatcherFor(code);
        if (matcher) {
            const byId = new Map();
            const byName = new Map();
            for (const record of toArray(exclusionRecords)) {
                if (record?.procedureId !== null && record?.procedureId !== undefined) byId.set(String(record.procedureId), record);
                if (record?.procedure) byName.set(cleanText(record.procedure).toLowerCase(), record);
            }
            for (const node of toArray(result?.procedurePath)) {
                const record = byId.get(String(node?.procedureId)) || byName.get(cleanText(node?.procedure || "").toLowerCase());
                if (!record) continue;
                for (const rule of ruleEntries(record.exclusionsAndLimitations)) {
                    if (matcher.test(rule)) rules.push(rule);
                }
            }
        }
        return uniqueStrings(rules.map(cleanText).filter(Boolean));
    }

    function checklistPercent(value) {
        if (value === null || value === undefined || value === "") return null;
        const text = cleanText(String(value));
        if (/^\d+(?:\.\d+)?%?$/.test(text)) return text.endsWith("%") ? text : `${text}%`;
        return text || null;
    }

    function isRealWaitingPeriod(value) {
        if (value === null || value === undefined) return false;
        const text = cleanText(typeof value === "string" ? value : safeStringify(value));
        return Boolean(text) && !/^(?:n\/?a|none|no|not applicable|-+|0(?:\s*months?)?)$/i.test(text);
    }

    function monthName(value) {
        const parsed = parseDateLoose(value);
        if (!parsed) return null;
        return ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"][new Date(parsed.time).getUTCMonth()];
    }

    function findTerminationDate(...records) {
        const keyPattern = /termin|termDate|eligibilityEnd|coverageEnd|expir|endDate/i;
        const datePattern = /\d{4}-\d{2}-\d{2}|\d{1,2}\/\d{1,2}\/\d{2,4}/;
        for (const record of records) {
            const stack = [[record, 0]];
            while (stack.length) {
                const [node, depth] = stack.pop();
                if (!node || typeof node !== "object" || depth > 2) continue;
                for (const [key, value] of Object.entries(node)) {
                    if (typeof value === "string" && keyPattern.test(key) && datePattern.test(value)) return { value: normalizeApiDate(value) || value, key };
                    if (value && typeof value === "object") stack.push([value, depth + 1]);
                }
            }
        }
        return null;
    }

    function collectNonPpoEvidence(rawByCode) {
        const networks = new Set();
        let codesWithNonPpoBenefits = 0;
        for (const code of PROCEDURE_CODES) {
            const value = rawByCode?.get?.(code);
            const response = value?.response || value;
            for (const bucket of toArray(response)) {
                if (!bucket || typeof bucket !== "object" || isExactPpoBucket(bucket)) continue;
                const hasPercent = toArray(bucket.coverages).some(node => node?.coverage?.percent !== null && node?.coverage?.percent !== undefined);
                if (hasPercent) {
                    toArray(bucket.networks).forEach(name => networks.add(String(name)));
                    codesWithNonPpoBenefits += 1;
                    break;
                }
            }
        }
        // Only the fact that non-PPO benefits exist is exported; their percentages stay out
        // of the output on purpose (PPO-only business rule).
        return { codesWithNonPpoBenefits, networks: [...networks] };
    }

    function buildChecklistOutput(out, extras = {}) {
        const results = new Map(toArray(out?.coverages?.procedure_code_search?.results).map(row => [normalizeCode(row?.procedureCode), row]));
        const routineRows = new Map(toArray(out?.routine_procedures?.rows).map(row => [normalizeCode(row?.procedureCode), row]));
        const exclusionRecords = toArray(out?.exclusions_and_limitations?.records);
        const allRules = uniqueStrings([
            ...exclusionRecords.flatMap(record => ruleEntries(record?.exclusionsAndLimitations)),
            ...toArray(out?.limitations_evidence?.notes),
            ...toArray(out?.faxback_pdf?.notes)
        ]);
        const procedureCache = new Map();

        const procedureFacts = code => {
            if (!code) return null;
            if (procedureCache.has(code)) return procedureCache.get(code);
            const result = results.get(code) || null;
            const routine = routineRows.get(code) || null;
            const rules = result ? checklistRulesForCode(code, result, exclusionRecords) : [];
            const frequency = checklistFrequencySentences(rules);
            const ages = extractAgeRestrictions(rules);
            const percent = checklistPercent(result?.percentCovered) ?? checklistPercent(routine?.percentCovered);
            const dates = uniqueStrings([
                ...toArray(result?.utilization_history),
                ...toArray(routine?.serviceDates)
            ]);
            const historyStatus = result?.utilization_history_status || (routine ? "ROUTINE_HISTORY_SOURCE_PRESENT" : "UNKNOWN");
            const historyReported = Boolean(routine) || ["PRESENT_DATES", "EXPLICIT_EMPTY", "ROUTINE_HISTORY_SOURCE_PRESENT"].includes(historyStatus);
            const facts = {
                code, result, routine, rules, frequency, ages, percent,
                returned: Boolean(result && !["FAILED", "UNAVAILABLE", "NOT_IN_CODE_LIST"].includes(result.status)) || Boolean(routine),
                history: historyReported ? { service_dates: dates, detail: routine?.statusDetail || null, status: historyStatus } : null
            };
            procedureCache.set(code, facts);
            return facts;
        };

        const sameFrequencyAnswer = (codeA, codeB, sharedPattern) => {
            const a = procedureFacts(codeA);
            const b = procedureFacts(codeB);
            const shared = allRules.filter(text => sharedPattern.test(text) && FREQUENCY_RULE_PATTERN.test(text));
            if (shared.length) return { answer: "Yes", evidence: shared };
            if (a?.frequency.length && b?.frequency.length) {
                const same = canonicalFrequency(a.frequency.join(" ")) === canonicalFrequency(b.frequency.join(" "));
                return { answer: same ? "Yes" : "No", evidence: [...a.frequency, ...b.frequency] };
            }
            return { answer: null, evidence: [], note: `Portal states no separate frequency rule for ${!a?.frequency.length ? codeA : codeB}.` };
        };

        const textHit = (pattern, extraText = []) => uniqueStrings([...allRules, ...extraText.map(cleanText)]).filter(text => pattern.test(text));

        const answerQuestion = key => {
            switch (key) {
                case "d0120_d0140_share_frequency":
                    return sameFrequencyAnswer("D0120", "D0140", /oral\s+examin[^.]*|examinations?\s+by\s+a\s+specialist/i);
                case "fmx_pano_share_frequency":
                    return sameFrequencyAnswer("D0210", "D0330", /(?:full\s+mouth\s+x-?rays?)[^.]*(?:panorex|panoramic)|(?:panorex|panoramic)[^.]*full\s+mouth/i);
                case "prophy_perio_share_frequency":
                    return sameFrequencyAnswer("D1110", "D4910", /(?:prophylax|cleanings?)[^.]*(?:periodontal\s+maint|perio\s*maint)|(?:periodontal\s+maint|perio\s*maint)[^.]*(?:prophylax|cleanings?)/i);
                case "posterior_composite_downgrade": {
                    const hit = textHit(/(?:composite|resin)[^.]*posterior[^.]*(?:amalgam|not\s+covered|alternate|downgrad)|posterior[^.]*(?:composite|resin)[^.]*(?:amalgam|not\s+covered|alternate|downgrad)/i);
                    return hit.length ? { answer: "Yes", evidence: hit } : { answer: null, evidence: [], note: "No posterior composite downgrade wording in the portal data." };
                }
                case "crown_downgrade_by_material": {
                    const hit = textHit(/crowns?[^.]*(?:downgrad|alternate\s+benefit|least\s+costly|material|base\s+metal|porcelain)|(?:downgrad|alternate\s+benefit|least\s+costly)[^.]*crowns?/i);
                    return hit.length ? { answer: "Yes", evidence: hit } : { answer: null, evidence: [], note: "No crown downgrade/material wording in the portal data." };
                }
                case "srp_quads_per_day": {
                    const hit = textHit(/(?:limited\s+to\s+)?(?:one|two|three|four|[1-4])\s+(?:quadrants?|quads?)[^.]*\b(?:per\s+day|daily|same[- ]day|per\s+visit|per\s+appointment)\b|(?:quadrants?|quads?)[^.]*\b(?:per\s+day|daily|same[- ]day|per\s+visit|per\s+appointment)\b|\b(?:limited|limit|maximum|no more than|up to)[^.]*\b(?:one|two|three|four|[1-4])\s+(?:quadrants?|quads?)\b/i);
                    const quadRule = textHit(/root\s+planing|scaling/i);
                    if (hit.length) return { answer: parseQuads(hit.join(" ")) || hit[0], evidence: hit };
                    return { answer: null, evidence: quadRule, note: "Portal gives a quadrant frequency but no per-day quadrant limit." };
                }
                case "d9944_bruxism_only": {
                    const hit = textHit(/bruxism|grinding/i);
                    return hit.length ? { answer: /\bonly\b/i.test(hit.join(" ")) ? "Yes" : "No", evidence: hit } : { answer: null, evidence: [], note: "No bruxism wording in the portal data." };
                }
                default:
                    return { answer: null, evidence: [], note: "Unknown question key." };
            }
        };

        // ----- plan-level fields -----
        const maxRows = toArray(out?.maximums_and_deductibles?.rows);
        const maxNotes = toArray(out?.maximums_and_deductibles?.notes);
        // "All, except ... orthodontics" is a general row; only a category/name that IS orthodontic counts.
        const isOrthoAccumulator = row => /ortho/i.test(row?.category || "") || /^\s*orthodont/i.test(row?.name || "");
        const findAccumulator = (type, ortho) => maxRows.find(row =>
            String(row?.type || "").toLowerCase() === type && isOrthoAccumulator(row) === ortho);
        const generalMax = findAccumulator("maximum", false);
        const orthoMax = findAccumulator("maximum", true);
        const generalDeductible = findAccumulator("deductible", false);
        const client = out?.more_information?.client_benefit_information || {};
        const display = client.display_fields || {};
        const clientNotes = toArray(client.notes);
        const cob = out?.more_information?.cob_information || {};
        const mailing = out?.more_information?.claim_and_inquiry_mailing_addresses || {};
        const ageLimits = out?.more_information?.age_limitations?.ageLimitations || {};
        const orthoConfig = toArray(out?.ortho_information?.orthoAgeLimitConfig)[0] || {};
        const member = out?.member_details?.selectedMember || {};
        const exemptionText = uniqueStrings([
            ...toArray(generalDeductible ? [generalDeductible.description, generalDeductible.name] : []),
            ...maxNotes
        ]).filter(text => /deductible/i.test(text));
        const noteCorpus = uniqueStrings([
            ...maxNotes, ...clientNotes, ...toArray(cob.notes), ...toArray(out?.coverages?.notes),
            ...toArray(out?.ortho_information?.notes), out?.ortho_information?.crowns_bridges_dentures_payment_note
        ].filter(Boolean).map(cleanText));
        const money = value => (value === null || value === undefined ? null : Number(value));
        const found = (value, source, extra = {}) => ({ value, status: "FOUND", source, ...extra });
        const derived = (value, source, extra = {}) => ({ value, status: "DERIVED", source, ...extra });
        const missing = (note, extra = {}) => ({ value: null, status: "NOT_AVAILABLE", source: null, note, ...extra });
        const orthoPercent = procedureFacts("D8080")?.percent || procedureFacts("D8090")?.percent || null;

        const resolveField = key => {
            switch (key) {
                case "subscriber_age_limit": {
                    if (orthoConfig.subscriberMaxAge === undefined) return missing("No subscriber age limit returned.");
                    return derived(`Orthodontic: ${orthoConfig.subscriberMinAge ?? 0} to under ${orthoConfig.subscriberMaxAge} (${orthoConfig.subscriberRule || "rule not stated"})`,
                        "ortho_information.orthoAgeLimitConfig", { coverage_percent: orthoPercent, age_restriction: `Orthodontic age ${orthoConfig.subscriberMinAge ?? 0}-${orthoConfig.subscriberMaxAge}`, evidence: [out?.ortho_information?.ortho_age_limit_note].filter(Boolean) });
                }
                case "dependent_age_limit": {
                    if (ageLimits.childMaxAgeLimit === undefined || ageLimits.childMaxAgeLimit === null) return missing("No dependent age limit returned.");
                    const text = `Child max age ${ageLimits.childMaxAgeLimit}${ageLimits.childMaxAgeLimitType ? ` (${ageLimits.childMaxAgeLimitType})` : ""}; student max age ${ageLimits.studentMaxAgeLimit ?? "N/A"}`;
                    return found(text, "more_information.age_limitations", { coverage_percent: orthoPercent, age_restriction: text, evidence: [`Orthodontic dependent age ${orthoConfig.minorMinAge ?? 0}-${orthoConfig.minorMaxAge ?? "N/A"}`] });
                }
                case "insurance_name": {
                    const name = mailing.claimMailingAddress?.name || (display.product ? String(display.product).replace(/\s*PPO.*$/i, "") : null);
                    return name ? found(name, "more_information.claim_and_inquiry_mailing_addresses", { evidence: [display.product].filter(Boolean) }) : missing("Carrier name not returned.");
                }
                case "group_name": {
                    const name = display.clientName || display.subGroupName;
                    return name ? found(name, "more_information.client_benefit_information", { evidence: [display.subGroupName].filter(Boolean) }) : missing("Group name not returned.");
                }
                case "group_number": {
                    const fromNotes = clientNotes.map(text => text.match(/^Group Number:\s*(\S+)/i)?.[1]).find(Boolean);
                    const value = fromNotes || String(display.clientNumber || "").split("-")[0] || null;
                    return value ? found(value, "more_information.client_benefit_information", { evidence: [display.clientNumber].filter(Boolean) }) : missing("Group number not returned.");
                }
                case "fee_schedule": {
                    const text = noteCorpus.join(" ");
                    const schedule = text.match(/\b(PPO Dentist Fee Schedule|Premier Dentist Fee Schedule)\b/i)?.[1] || (display.product ? `${display.product} fee schedule` : null);
                    return schedule ? derived(schedule, "coverages.notes / client product") : missing("Fee schedule not named in the portal data.");
                }
                case "insurance_address": {
                    const addr = mailing.claimMailingAddress;
                    if (addr?.street) return found([addr.name, addr.street, addr.city_state_zip].filter(Boolean).join(", "), "claim_and_inquiry_mailing_addresses.claimMailingAddress");
                    return mailing.inquiryAddress ? found(typeof mailing.inquiryAddress === "string" ? mailing.inquiryAddress : safeStringify(mailing.inquiryAddress), "claim_and_inquiry_mailing_addresses.inquiryAddress") : missing("No claim/inquiry address returned.");
                }
                case "insurance_phone": {
                    const phone = mailing.phoneNumber || mailing.subscriberPhoneNumber;
                    return phone ? found(String(phone), "claim_and_inquiry_mailing_addresses") : missing("Portal returned no phone number (it points to the Contact Us page).");
                }
                case "payor_id": {
                    const payorId = mailing.payorId || display.payor_id || null;
                    return payorId ? found(payorId, "more_information.claim_and_inquiry_mailing_addresses.payorId", { evidence: [payorId] }) : missing("Payor ID not returned.");
                }
                case "in_network":
                    return derived(out?.selected_network || "PPO Dentist", "selected_network", { note: "Benefits were captured for the PPO Dentist network; the portal does not say whether the office is a participating provider." });
                case "patient_eff_date":
                    return member.effectiveDate ? found(member.effectiveDate, "member_details.selectedMember") : missing("Effective date not returned.");
                case "eligibility_term_date":
                    return extras.termination ? found(extras.termination.value, `member record field ${extras.termination.key}`) : missing("No termination date field in the member/benefit responses.");
                case "oon_benefits": {
                    const nonPpo = extras.nonPpo || { codesWithNonPpoBenefits: 0, networks: [] };
                    if (nonPpo.codesWithNonPpoBenefits > 0) return derived("Yes", "procedure responses", { evidence: [`${nonPpo.codesWithNonPpoBenefits} code(s) returned benefits for ${nonPpo.networks.join(", ") || "non-PPO networks"}`] });
                    const note = noteCorpus.find(text => /non-?participating|premier/i.test(text) && /percent|portion|paid/i.test(text));
                    return note ? derived("Yes", "coverages.notes", { evidence: [note] }) : missing("No out-of-network benefit information returned.");
                }
                case "plan_year_start_month": {
                    const month = monthName(generalMax?.from || generalDeductible?.from);
                    return month ? found(month, "maximums_and_deductibles.rows[].from", { evidence: [out?.maximums_and_deductibles?.accumulationPeriodType].filter(Boolean) }) : missing("Accumulation period start not returned.");
                }
                case "yearly_max":
                    return generalMax ? found(money(generalMax.individual?.amount), "maximums_and_deductibles", { evidence: [`Remaining ${generalMax.individual?.remaining}`] }) : missing("No annual maximum row.");
                case "yearly_max_used":
                    return generalMax ? found(money(generalMax.individual?.used), "maximums_and_deductibles") : missing("No annual maximum row.");
                case "individual_deductible":
                    return generalDeductible ? found(money(generalDeductible.individual?.amount), "maximums_and_deductibles") : missing("No deductible row.");
                case "family_deductible":
                    return generalDeductible ? found(money(generalDeductible.family?.amount), "maximums_and_deductibles") : missing("No deductible row.");
                case "individual_deductible_used":
                    return generalDeductible ? found(money(generalDeductible.individual?.used), "maximums_and_deductibles") : missing("No deductible row.");
                case "family_deductible_used":
                    return generalDeductible ? found(money(generalDeductible.family?.used), "maximums_and_deductibles") : missing("No deductible row.");
                case "deductible_applies_preventive":
                case "deductible_applies_diagnostic": {
                    if (!generalDeductible) return missing("No deductible row.");
                    const word = key.endsWith("preventive") ? /preventive/i : /diagnostic/i;
                    const exempt = exemptionText.filter(text => /(?:does\s+not\s+apply|except)/i.test(text) && word.test(text));
                    return exempt.length ? derived("No", "maximums_and_deductibles", { evidence: exempt }) : derived("Yes", "maximums_and_deductibles", { evidence: ["Deductible row lists no exemption for this category."] });
                }
                case "ortho_max":
                    return orthoMax ? found(money(orthoMax.individual?.amount), "maximums_and_deductibles", { evidence: [orthoMax.isLifetime ? "Lifetime maximum" : "Per accumulation period"] }) : missing("No orthodontic maximum row.");
                case "ortho_used":
                    return orthoMax ? found(money(orthoMax.individual?.used), "maximums_and_deductibles") : missing("No orthodontic maximum row.");
                case "ortho_deductible_amount":
                case "ortho_deductible_met": {
                    const orthoDeductible = findAccumulator("deductible", true);
                    if (orthoDeductible) return found(money(key.endsWith("amount") ? orthoDeductible.individual?.amount : orthoDeductible.individual?.used), "maximums_and_deductibles");
                    const exempt = exemptionText.filter(text => /orthodontic/i.test(text) && /(?:does\s+not\s+apply|except)/i.test(text));
                    return exempt.length ? derived("N/A", "maximums_and_deductibles", { evidence: exempt, note: "Deductible does not apply to orthodontic services." }) : missing("No orthodontic deductible row.");
                }
                case "waiting_period": {
                    const waits = [];
                    for (const row of toArray(out?.coverages?.coverage_rows)) if (isRealWaitingPeriod(row?.waitingPeriod)) waits.push(`${row.procedure}: ${row.waitingPeriod}`);
                    for (const row of results.values()) if (isRealWaitingPeriod(row?.waitingPeriod)) waits.push(`${row.procedureCode}: ${typeof row.waitingPeriod === "string" ? row.waitingPeriod : safeStringify(row.waitingPeriod)}`);
                    if (waits.length) return found("Yes", "coverages", { evidence: uniqueStrings(waits) });
                    return results.size ? derived("No", "coverages", { evidence: [`No waiting period on any of ${results.size} procedure results or ${toArray(out?.coverages?.coverage_rows).length} coverage rows.`] }) : missing("No coverage data to check.");
                }
                case "missing_tooth_clause": {
                    const payable = noteCorpus.concat(allRules).filter(text => /replace\s+a\s+tooth\s+that\s+has\s+been\s+missing\s+prior/i.test(text));
                    if (payable.length) return derived("No", "exclusions_and_limitations", { evidence: uniqueStrings(payable), note: "Portal says payment IS made to replace a tooth missing before the effective date." });
                    const clause = noteCorpus.concat(allRules).filter(text => /missing\s+tooth\s+(?:clause|limitation|exclusion)|not\s+(?:payable|covered)[^.]*missing\s+(?:prior|before)/i.test(text));
                    return clause.length ? derived("Yes", "exclusions_and_limitations", { evidence: uniqueStrings(clause) }) : missing("No missing-tooth wording in the portal data.");
                }
                case "major_paid_on_prep_or_seat": {
                    const seat = noteCorpus.filter(text => /seat(?:\/|\s+or\s+|\s+)?(?:delivery)?\s*date|delivery\s+date/i.test(text));
                    if (seat.length) return derived("Seat", "notes", { evidence: seat });
                    const prep = noteCorpus.filter(text => /prep(?:aration)?\s+date|date\s+of\s+preparation/i.test(text));
                    return prep.length ? derived("Prep", "notes", { evidence: prep }) : missing("Prep-vs-seat payment rule not stated.");
                }
                case "preauth_over_amount": {
                    const hit = noteCorpus.find(text => /(?:pre-?(?:authorization|auth|treatment|determination)|predetermination)[^.]*\$\s?[\d,]+/i.test(text));
                    const amount = hit?.match(/\$\s?([\d,]+(?:\.\d{2})?)/)?.[1];
                    return amount ? derived(`$${amount}`, "notes", { evidence: [hit] }) : missing("No pre-authorization dollar threshold in the portal data.");
                }
                case "coordination_of_benefits": {
                    const lines = toArray(cob.notes).filter(text => /^(?:Payment Order|Internal COB|External COB|Payment Option Type)/i.test(text));
                    return lines.length ? found(lines.join(" | "), "more_information.cob_information") : missing("No COB information returned.");
                }
                default:
                    return missing("Unknown field key.");
            }
        };

        // ----- build one record per checklist row -----
        const rows = CHECKLIST_SPEC.map(spec => {
            const row = {
                sl_no: spec.sl, item: spec.item, code: spec.code, kind: spec.kind,
                requested: [], frequency: null, coverage_percent: null, age_restriction: null,
                history: null, answer: null, value: null,
                status: "NOT_FOUND", missing: [], not_stated: [], source: null, evidence: [],
                remarks: spec.remarks, ...(spec.clipped ? { description_clipped_in_source: true } : {})
            };
            if (spec.kind === "procedure") {
                const facts = procedureFacts(spec.code);
                const wants = { frequency: spec.flags[0] === "F", coverage_percent: spec.flags[1] === "C", age_restriction: spec.flags[2] === "A", history: spec.flags[4] === "H" };
                row.requested = Object.keys(wants).filter(name => wants[name]);
                row.source = facts.result ? "coverages.procedure_code_search" : (facts.routine ? "routine_procedures" : null);
                if (!facts.returned) {
                    row.missing = [...row.requested];
                    row.status = "NOT_FOUND";
                    row.evidence.push(`${spec.code} was not returned by the portal.`);
                    return row;
                }
                if (wants.frequency) { row.frequency = facts.frequency.length ? facts.frequency.join(" | ") : null; if (!row.frequency) row.not_stated.push("frequency"); }
                if (wants.coverage_percent) { row.coverage_percent = facts.percent; if (!row.coverage_percent) row.missing.push("coverage_percent"); }
                if (wants.age_restriction) { row.age_restriction = facts.ages.length ? facts.ages.join(" | ") : null; if (!row.age_restriction) row.not_stated.push("age_restriction"); }
                if (wants.history) { row.history = facts.history; if (!row.history) row.missing.push("history"); }
                row.evidence.push(...facts.rules);
                if (facts.result?.status && facts.result.status !== "OK") row.coverage_status = facts.result.status;
            } else if (spec.kind === "question") {
                const answer = answerQuestion(spec.key);
                row.requested = ["answer"];
                row.answer = answer.answer;
                row.evidence.push(...toArray(answer.evidence));
                row.source = "exclusions_and_limitations";
                if (answer.note) row.note = answer.note;
                if (answer.answer === null || answer.answer === undefined) row.not_stated.push("answer");
            } else {
                const field = resolveField(spec.key);
                row.requested = ["value"];
                row.value = field.value;
                row.source = field.source;
                row.value_status = field.status;
                row.evidence.push(...toArray(field.evidence));
                if (field.note) row.note = field.note;
                if (field.coverage_percent !== undefined) row.coverage_percent = field.coverage_percent;
                if (field.age_restriction !== undefined) row.age_restriction = field.age_restriction;
                if (field.value === null || field.value === undefined) (field.status === "NOT_AVAILABLE" ? row.missing : row.not_stated).push("value");
            }
            const filled = row.requested.length - row.missing.length - row.not_stated.length;
            row.status = filled === row.requested.length ? "FOUND" : (filled > 0 ? "PARTIAL" : (row.missing.length ? "NOT_FOUND" : "NOT_STATED"));
            return row;
        });

        const counts = { FOUND: 0, PARTIAL: 0, NOT_STATED: 0, NOT_FOUND: 0 };
        for (const row of rows) counts[row.status] += 1;
        return {
            section_title: "Audit Checklist",
            schema_version: CHECKLIST_SCHEMA_VERSION,
            source_workbook: "checklist_text_extracted.xlsx",
            network: "PPO Dentist",
            legend: {
                FOUND: "Every requested field has a value.",
                PARTIAL: "Some requested fields have values, others are missing or not stated.",
                NOT_STATED: "The portal returned the data but never states the requested rule (value is null).",
                NOT_FOUND: "The portal did not return the code/field at all."
            },
            summary: { total_rows: rows.length, ...counts, codes_not_returned: uniqueStrings(rows.filter(row => row.kind === "procedure" && row.status === "NOT_FOUND").map(row => row.code)) },
            rows
        };
    }

    function limitationSubjectsForCode(code) {
        const match = String(code || "").toUpperCase().match(/^D(\d{4})$/);
        if (!match) return null;
        const n = Number(match[1]);
        const table = [
            [120, 180, /oral\s+exam|examinations?|evaluations?/i],
            [210, 210, /full\s+mouth\s+x-?\s?rays?|panorex|panoramic|complete\s+series/i],
            [330, 330, /full\s+mouth\s+x-?\s?rays?|panorex|panoramic|complete\s+series/i],
            [270, 277, /bitewing/i, /full\s+mouth/i],
            [364, 395, /cone\s*beam|cbct|tomograph/i],
            [431, 431, /oral\s+cancer|adjunctive|screening/i],
            [601, 603, /caries\s+risk/i],
            [1110, 1120, /prophylax|cleanings?/i],
            [1206, 1208, /fluoride/i, /silver\s+diamine/i],
            [1330, 1330, /oral\s+hygiene/i],
            [1351, 1353, /sealants?/i],
            [1354, 1355, /silver\s+diamine|caries\s+arrest/i],
            [1510, 1575, /space\s+maintain/i],
            [2140, 2161, /amalgam/i, /inlays?|optioned/i],
            [2330, 2335, /anterior/i],
            [2390, 2390, /anterior/i],
            [2391, 2394, /posterior\s+composite|composites?\s+(?:on|for)\s+posterior/i],
            [2510, 2530, /\binlays?\b/i],
            [2610, 2630, /\binlays?\b/i],
            [2650, 2652, /\binlays?\b/i],
            [2542, 2544, /\bonlays?\b|cast\s+restorations?/i],
            [2642, 2664, /\bonlays?\b|cast\s+restorations?/i],
            [2710, 2799, /cast\s+restorations?|\bcrowns?\b/i, /veneers?|prefabricated|stainless/i],
            [2920, 2921, /recement/i],
            [2929, 2934, /prefabricated|stainless\s+steel/i],
            [2940, 2941, /protective\s+restoration|interim\s+therapeutic/i],
            [2950, 2957, /cast\s+restorations?|\bcores?\b|substructures?|post\s+and\s+core/i],
            [2960, 2962, /veneers?/i],
            [2980, 2983, /crown\s+repair|restoration\s+repair/i],
            [3000, 3999, /endodon|root\s+canal|pulp|retreat|apico/i],
            [4210, 4286, /periodontal\s+surg|osseous|gingivectom|soft\s+tissue\s+graft|crown\s+lengthen/i],
            [4341, 4342, /root\s+planing|scaling\s+and\s+root/i],
            [4346, 4346, /gingival\s+inflammation|full\s+mouth\s+scaling/i],
            [4355, 4355, /debridement/i],
            [4381, 4381, /arestin|antimicrobial|chemotherapeutic|localized\s+delivery/i],
            [4910, 4910, /periodontal\s+maint|perio\s+maint/i],
            [4920, 4921, /irrigation/i],
            [5110, 5226, /dentures?/i, /overdenture/i],
            [5282, 5286, /dentures?/i],
            [5410, 5422, /adjust/i],
            [5511, 5671, /\brepairs?\b/i, /implant/i],
            [5710, 5761, /relines?|rebases?/i],
            [5810, 5821, /interim|dentures?/i],
            [5863, 5867, /overdentures?|dentures?/i],
            [5900, 5999, /maxillofacial|moulage/i],
            [6010, 6013, /implants?/i, /maintenance/i],
            [6040, 6077, /implants?|abutment/i, /maintenance/i],
            [6080, 6083, /implant\s+maintenance/i],
            [6090, 6099, /implant[^.]*repair|repair[^.]*implant/i],
            [6110, 6119, /implants?/i, /maintenance/i],
            [6190, 6199, /implants?|abutment/i, /maintenance/i],
            [6205, 6794, /bridgework|bridges?|fixed\s+partial|pontic/i],
            [7111, 7251, /extraction|impact/i],
            [7288, 7288, /brush\s+biopsy/i],
            [7310, 7321, /alveolo/i],
            [7953, 7953, /bone\s+(?:replacement\s+)?graft|ridge\s+preserv/i],
            [7961, 7963, /frenectomy|frenuloplasty|frenulectomy/i],
            [8000, 8999, /orthodon/i],
            [9110, 9110, /palliative|emergency/i],
            [9210, 9248, /anesthesia|sedation|analgesia|nitrous/i],
            [9310, 9311, /consult/i],
            [9420, 9420, /hospital|ambulatory/i],
            [9610, 9630, /\bdrugs?\b|medicament|parenteral/i],
            [9910, 9911, /desensitiz/i],
            [9920, 9920, /behavior/i],
            [9944, 9946, /occlusal\s+guards?/i],
            [9947, 9949, /sleep\s+apnea/i]
        ];
        const row = table.find(([min, max]) => n >= min && n <= max);
        if (!row) return null;
        const isImplantRestoration = (n >= 6010 && n <= 6083) || (n >= 6090 && n <= 6099) || (n >= 6110 && n <= 6119) || (n >= 6190 && n <= 6199);
        return {
            subject: { include: row[2], exclude: row[3] || null },
            crossCategories: isImplantRestoration ? ["Implants"] : [],
            related: n === 4910
                ? [{ category: "Preventive", include: /prophylax[^.]*periodontal|periodontal[^.]*prophylax/i }]
                : []
        };
    }

    function resolveCodeLimitations(result, exclusionRecords) {
        const code = normalizeCode(result?.procedureCode);
        const records = toArray(exclusionRecords).filter(record => record && typeof record === "object");
        const sameName = (a, b) => Boolean(cleanText(a)) && cleanText(a).toLowerCase() === cleanText(b).toLowerCase();
        const recordForNode = node => records.find(record =>
            (record.procedureId !== null && record.procedureId !== undefined && node?.procedureId !== null && node?.procedureId !== undefined && String(record.procedureId) === String(node.procedureId)) ||
            sameName(record.procedure, node?.procedure)) || null;
        const recordNamed = name => records.find(record => sameName(record.procedure, name)) || null;
        const leafRules = toArray(result?.limitations)
            .flatMap(item => typeof item === "string" ? [item] : toArray(item?.exclusionsAndLimitations))
            .map(cleanText)
            .filter(Boolean);
        const spec = limitationSubjectsForCode(code);
        if (!spec) return { applicable: uniqueStrings(leafRules), related: [] };
        const matches = (text, subject) => subject.include.test(text) && !(subject.exclude && subject.exclude.test(text));
        const categoryRecords = [
            ...toArray(result?.procedurePath).map(recordForNode),
            ...spec.crossCategories.map(recordNamed)
        ].filter(Boolean);
        const categoryRules = uniqueStrings(categoryRecords.flatMap(record => toArray(record.exclusionsAndLimitations)));
        const applicable = uniqueStrings([...leafRules, ...categoryRules.filter(text => matches(text, spec.subject))]);
        const related = uniqueStrings(spec.related.flatMap(link =>
            toArray(recordNamed(link.category)?.exclusionsAndLimitations).filter(text => link.include.test(text))
        )).filter(text => !applicable.includes(text));
        return { applicable, related };
    }

    function isFrequencyRule(text) {
        return /\b(?:once|twice|\d+\s+times?|per\s+(?:calendar\s+|benefit\s+|contract\s+)?(?:year|quadrant|tooth|lifetime|area|visit|day|arch)|every\s+\d+|in\s+any\s+(?:\w+[- ])?(?:year|month)|\d+\s*(?:consecutive\s+)?months?|\w+[- ]year\s+period|\d+[- ]month\s+period|lifetime|\d+\s+per\s+\d+\s+years?)\b/i.test(String(text || ""));
    }

    function deductibleAppliesForCode(result, deductibleRow) {
        if (!deductibleRow) return { value: null, basis: "No deductible row was returned." };
        const amount = deductibleRow?.individual?.amount;
        if (amount !== null && amount !== undefined && Number(amount) === 0) {
            return { value: "N/A", basis: "The plan has no individual deductible." };
        }
        const text = cleanText(String(deductibleRow?.description || "")).replace(/x-\s+rays/gi, "X-rays");
        const exemptPart = text.match(/(?:does\s+not\s+apply\s+to|doesn't\s+apply\s+to|except(?:\s+for)?|excluding|waived\s+(?:for|on))\s+(.*)$/i)?.[1] || "";
        if (!exemptPart) return { value: "Yes", basis: "The deductible wording lists no exempt services." };
        const code = normalizeCode(result?.procedureCode);
        if (!code) return { value: null, basis: "No procedure code." };
        const n = Number(code.slice(1));
        const path = toArray(result?.procedurePath);
        const level1 = cleanText(path[0]?.procedure || "").toLowerCase();
        const items = exemptPart
            .replace(/\.\s*$/, "")
            .split(/\s*,\s*(?:and\s+)?|\s+and\s+/i)
            .map(item => cleanText(item).toLowerCase())
            .filter(Boolean);
        const isRadiograph = /radiograph/.test(level1) || (n >= 210 && n <= 340);
        const rules = [
            [/^(?:oral\s+)?(?:exams?|examinations?|evaluations?)$/, () => n >= 120 && n <= 180],
            [/^diagnostic(?:\s+services)?$/, () => level1 === "diagnostic"],
            [/^prevent(?:at)?ive(?:\s+services)?$/, () => level1 === "preventive" || level1 === "preventative"],
            [/^(?:x-?rays?|radiographs?)$/, () => isRadiograph],
            [/bitewing/, () => level1 === "bitewing radiographs" || (n >= 270 && n <= 277)],
            [/^full\s+mouth(?:\s+(?:x-?rays?|series|radiographs?))?$/, () => n === 210],
            [/pano/, () => n === 330],
            [/^sealants?$/, () => level1 === "sealants" || (n >= 1351 && n <= 1353)],
            [/periodontal\s+maintenance|perio\s+maint/, () => n === 4910],
            [/full\s+mouth\s+debridement/, () => n === 4355],
            [/cephalometric/, () => n === 340],
            [/diagnostic\s+casts?|study\s+models?/, () => n === 470],
            [/photo/, () => n === 350 || n === 351],
            [/orthodon/, () => level1 === "orthodontic services" || (n >= 8000 && n <= 8999)],
            [/palliative|emergency/, () => n === 9110],
            [/brush\s+biopsy/, () => n === 7288 || level1 === "brush biopsy"],
            [/fluoride/, () => n === 1206 || n === 1208],
            [/space\s+maint/, () => n >= 1510 && n <= 1575]
        ];
        const singular = value => value.replace(/s\b/g, "");
        for (const item of items) {
            const rule = rules.find(([pattern]) => pattern.test(item));
            const applies = rule ? rule[1]() : Boolean(level1) && singular(item) === singular(level1);
            if (applies) return { value: "No", basis: `Exempt: the deductible wording excludes ${item}.` };
        }
        return { value: "Yes", basis: "Not named in the deductible exemption wording." };
    }

    function classifyLookupStatus(outcome) {
        if (!outcome) return "NOT_ATTEMPTED";
        if (outcome.status === "SUCCESS") return "FOUND";
        if (outcome.status === "NOT_IN_CODE_LIST") return "NOT_IN_PLAN_CODE_TREE";
        if (outcome.status === "UNAVAILABLE") return "NO_PPO_BENEFIT_RETURNED";
        if (Number(outcome.http_status) === 404) return "NOT_IN_PLAN_CODE_TREE";
        return "LOOKUP_FAILED";
    }

    function knownCodeNote(code) {
        const notes = {
            D2959: "D2959 is not a code the portal recognizes; the workbook row describes a core build-up, which is D2950.",
            D5510: "D5510 is a retired CDT code; complete denture base repairs are D5511 (mandibular) and D5512 (maxillary).",
            D7960: "D7960 is a retired CDT code; frenectomy is D7961 (buccal/labial) and D7962 (lingual)."
        };
        return notes[normalizeCode(code)] || null;
    }

    function inferOrthoCoverage(code, orthoSchedule, coverageRows) {
        const category = toArray(coverageRows).find(row => /^orthodontic/i.test(cleanText(row?.procedure || "")));
        if (!category || !/not\s+covered/i.test(String(category.percentCovered ?? ""))) return null;
        const config = toArray(orthoSchedule?.orthoTreatmentCategoryConfig)
            .find(item => toArray(item?.procedureCategory?.procedureCodes).map(normalizeCode).includes(normalizeCode(code)));
        if (!config) return null;
        const name = cleanText(config?.procedureCategory?.procedureName || "an orthodontic treatment category");
        return {
            percentCovered: "Not Covered",
            basis: `The Orthodontic Services category is Not Covered and ${normalizeCode(code)} is listed under "${name}" in the plan's ortho payment schedule.`
        };
    }

    function normalizePercentText(value) {
        if (value === null || value === undefined) return null;
        const text = cleanText(String(value));
        if (!text) return null;
        const number = text.match(/^(\d+(?:\.\d+)?)\s*%?$/)?.[1];
        return number !== undefined ? `${Number(number)}%` : text;
    }

    function normalizeDobValue(value) {
        const text = cleanText(String(value ?? ""));
        if (!text || /^n\/?a$/i.test(text) || text === "null") return null;
        let match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (match) return `${match[1]}-${match[2]}-${match[3]}`;
        match = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
        if (match) return `${match[3]}-${match[1].padStart(2, "0")}-${match[2].padStart(2, "0")}`;
        match = text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/i);
        if (match) {
            const [, year, month, day, hour, minute, zone] = match;
            if (!zone || zone.toUpperCase() !== "Z" || (hour === "00" && minute === "00")) return `${year}-${month}-${day}`;
            const shifted = new Date(Date.UTC(+year, +month - 1, +day, +hour, +minute) + 12 * 60 * 60 * 1000);
            return shifted.toISOString().slice(0, 10);
        }
        return null;
    }

    function displayDateValue(value) {
        const iso = normalizeDobValue(value);
        if (!iso) return null;
        const [year, month, day] = iso.split("-");
        return `${month}/${day}/${year}`;
    }

    function planTypeFromProduct(product) {
        const text = String(product || "");
        if (/\bD?HMO\b|managed\s+care|prepaid/i.test(text)) return "DHMO";
        if (/\bEPO\b/i.test(text)) return "EPO";
        if (/\bPPO\b/i.test(text)) return "PPO";
        if (/premier/i.test(text)) return "Premier";
        if (/indemnity|traditional/i.test(text)) return "Indemnity";
        if (/medicare|medicaid|chip\b/i.test(text)) return "Government";
        return null;
    }

    function stateNameForPlanAcronym(acronym) {
        const states = {
            AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado", CT: "Connecticut",
            DE: "Delaware", DC: "District of Columbia", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois",
            IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
            MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi", MO: "Missouri", MT: "Montana",
            NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
            NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania",
            RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah",
            VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming", PR: "Puerto Rico"
        };
        const code = String(acronym || "").toUpperCase().match(/^DDP([A-Z]{2})$/)?.[1];
        return code ? states[code] || null : null;
    }

    function extractPhoneNumbers(text) {
        const matches = String(text || "").match(/(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\b\d{3}[\s.-])\d{3}[\s.-]\d{4}\b/g) || [];
        return uniqueStrings(matches.map(cleanText));
    }

    function cleanSectionNotes(notes) {
        const fragmentPatterns = [
            /^networks?:?$/i,
            /^(?:PPO Dentist|Premier Dentist|Nonparticipating Dentist)(?:\s*,\s*(?:PPO Dentist|Premier Dentist|Nonparticipating Dentist))*$/i,
            /^\(?(?:met\/ded|used\/max)\)?$/i,
            /^(?:individual|family|general|deductible|deductibles|maximum|maximums|applies to|benefit periods?|orthodontic|orthodontic services|lifetime|ortho|not covered|optional|n\/a|yes|no|page|•)$/i,
            /^\d+$/,
            /^\$?\s*[0-9][0-9,]*(?:\.\d+)?\s*\/\s*\$?\s*[0-9][0-9,]*(?:\.\d+)?$/,
            /^\d{1,2}\/\d{1,2}\/\d{4}\s+to\s+\d{1,2}\/\d{1,2}\/\d{4}$/i,
            /^D\d{4}$/i,
            /^\d+(?:\.\d+)?%$/,
            /^(?:Amount|Used|Remaining):\s*(?:\$\s*[0-9][0-9,]*(?:\.\d+)?|Unlimited|N\/A)$/i,
            /^mbb_/i,
            /^procedure codes? (?:and descriptions|search)$/i,
            /^use commas to search for multiple procedures? codes\.?$/i,
            /^(?:print section|expand|collapse)$/i
        ];
        const lines = toArray(notes)
            .filter(value => typeof value === "string")
            .map(value => cleanText(value.replace(/\u00a0/g, " ")))
            .filter(Boolean)
            .filter(line => !fragmentPatterns.some(pattern => pattern.test(line)));
        const joined = [];
        for (const line of lines) {
            const previous = joined[joined.length - 1];
            if (previous && !/[.!?:]$/.test(previous) && /^[a-z(]/.test(line)) {
                joined[joined.length - 1] = /-$/.test(previous) ? `${previous}${line}` : `${previous} ${line}`;
            } else {
                joined.push(line);
            }
        }
        const isKeyValue = line => /^[A-Za-z][A-Za-z /&#-]{1,40}:\s*\S/.test(line);
        const kept = uniqueStrings(joined).filter(line => line.split(/\s+/).length >= 4 || isKeyValue(line));
        const contained = kept.filter((line, index) => !kept.some((other, otherIndex) =>
            otherIndex !== index && other.length > line.length && other.toLowerCase().includes(line.toLowerCase())));
        return contained.filter((line, index) => isKeyValue(line) ||
            !contained.slice(0, index).some(earlier => !isKeyValue(earlier) && notesNearlyDuplicate(earlier, line)));
    }

    function noteWordSet(text) {
        return new Set(String(text || "").toLowerCase().match(/[a-z]+/g) || []);
    }

    function notesNearlyDuplicate(first, second) {
        const a = noteWordSet(first);
        const b = noteWordSet(second);
        if (a.size < 8 || b.size < 8) return false;
        let shared = 0;
        for (const word of a) if (b.has(word)) shared += 1;
        return shared / (a.size + b.size - shared) >= 0.7;
    }

    function mergeLimitationWording(portalNotes, pdfNotes, conflicts = [], category = "") {
        const key = text => cleanText(text).toLowerCase().replace(/[\s,;:.-]+$/, "");
        const kept = [];
        const add = (text, source) => {
            const value = cleanText(text);
            if (!value) return;
            const valueKey = key(value);
            const prefixOf = kept.findIndex(item => item.key.startsWith(valueKey));
            if (prefixOf >= 0) return;
            const extends_ = kept.findIndex(item => valueKey.startsWith(item.key));
            if (extends_ >= 0) {
                kept[extends_] = { text: value, key: valueKey, source };
                return;
            }
            const subject = limitationSubjectKey(value);
            const sameSubject = kept.findIndex(item => subject && limitationSubjectKey(item.text) === subject);
            if (sameSubject >= 0 && source === "pdf" && kept[sameSubject].source === "portal") {
                conflicts.push({ fact_key: `exclusion:${category}:${subject}`, canonical_source: "Faxback PDF", toolkit_value: kept[sameSubject].text, pdf_value: value });
                kept[sameSubject] = { text: value, key: valueKey, source };
                return;
            }
            kept.push({ text: value, key: valueKey, source });
        };
        for (const text of toArray(portalNotes)) add(text, "portal");
        for (const text of toArray(pdfNotes)) add(text, "pdf");
        return kept.map(item => item.text);
    }

    function bucketNetworkNames(bucket) {
        return uniqueStrings(toArray(bucket?.networks).map(item => typeof item === "string" ? item : item?.name));
    }

    function nonPpoBuckets(value) {
        return toArray(value).filter(bucket => bucket && typeof bucket === "object" && Array.isArray(bucket.networks) && !isExactPpoBucket(bucket));
    }

    function outOfNetworkForCode(code, rawValue, pdfCoverage) {
        const response = rawValue?.response || rawValue;
        const fromApi = nonPpoBuckets(response).map(bucket => {
            const nodes = toArray(bucket?.coverages);
            if (!nodes.length) return null;
            const leaf = nodes.find(node => normalizeCode(node?.procedureId || node?.procedure) === code) ||
                [...nodes].sort((a, b) => Number(a?.level || 0) - Number(b?.level || 0)).at(-1);
            const percent = normalizePercentText(leaf?.coverage?.percent);
            if (!percent) return null;
            return {
                networks: bucketNetworkNames(bucket),
                percentCovered: percent,
                waitingPeriod: leaf?.waitingPeriods ?? "N/A",
                waitingPeriodMetDate: leaf?.waitingPeriodMetDate ?? null,
                source: "toolkit_api"
            };
        }).filter(Boolean);
        if (fromApi.length) return fromApi;
        return Object.entries(pdfCoverage || {})
            .filter(([network, value]) => !/^PPO Dentist$/i.test(network) && normalizePercentText(value?.percent))
            .map(([network, value]) => ({
                networks: network.split(/\s*,\s*/).filter(Boolean),
                percentCovered: normalizePercentText(value.percent),
                waitingPeriod: value?.waiting_period || "N/A",
                waitingPeriodMetDate: value?.met_date ?? null,
                source: "faxback_pdf"
            }));
    }

    function buildOutOfNetworkSection(inputs = {}) {
        const benefitRoot = inputs.benefitRoot || {};
        const results = toArray(inputs.results);
        const toCategoryRow = (bucket, item, source) => ({
            networks: bucketNetworkNames(bucket),
            procedure: item?.procedure ?? null,
            procedureId: item?.procedureId ?? null,
            percentCovered: normalizePercentText(item?.coverage?.percent),
            childValuesDiffer: item?.coverage?.childValuesDiffer ?? null,
            waitingPeriod: item?.waitingPeriods ?? "N/A",
            waitingPeriodMetDate: item?.waitingPeriodMetDate ?? null,
            source
        });
        let coverageRows = nonPpoBuckets(benefitRoot.networkBenefits).flatMap(bucket =>
            toArray(bucket?.coverages).map(item => toCategoryRow(bucket, item, "member_benefits")));
        if (!coverageRows.length) {
            const seen = new Set();
            for (const value of toArray(inputs.procedureResponses)) {
                for (const bucket of nonPpoBuckets(value?.response || value)) {
                    for (const item of toArray(bucket?.coverages).filter(node => Number(node?.level) === 1)) {
                        const key = `${bucketNetworkNames(bucket).join("|")}|${item?.procedureId ?? item?.procedure}`;
                        if (seen.has(key)) continue;
                        seen.add(key);
                        coverageRows.push(toCategoryRow(bucket, item, "procedure_lookups"));
                    }
                }
            }
        }
        const apiRoutine = nonPpoBuckets(inputs.routineResponse).flatMap(bucket =>
            toolkitRoutineRows([bucket]).map(row => ({ networks: bucketNetworkNames(bucket), ...row })));
        const pdfRoutine = toArray(inputs.pdfModel?.office_visit?.procedures)
            .filter(item => item?.network && !isPpoNetworkLabel(item.network))
            .map(item => ({
                networks: String(item.network).split(/\s*,\s*/).filter(Boolean),
                procedureCode: PDF_ROUTINE_CODES[item.procedure] || null,
                description: item.procedure,
                eligibleNow: item.eligible_now,
                serviceDates: uniqueStrings(item.service_dates || []),
                statusDetail: item.status_detail || null,
                source: "faxback_pdf"
            }));
        const maximums = nonPpoBuckets(benefitRoot.maximumsAndDeductions).flatMap(bucket =>
            toArray(buildAccumulatorPageRows([bucket], null)).map(row => ({ networks: bucketNetworkNames(bucket), ...row })));
        const codesWithOon = results.filter(row => toArray(row?.out_of_network).length);
        const networks = uniqueStrings([
            ...coverageRows.flatMap(row => row.networks),
            ...codesWithOon.flatMap(row => toArray(row.out_of_network).flatMap(item => toArray(item?.networks))),
            ...apiRoutine.flatMap(row => row.networks),
            ...pdfRoutine.flatMap(row => row.networks),
            ...maximums.flatMap(row => row.networks)
        ]);
        const pdfMaximumNetworks = toArray(inputs.pdfMaximumNetworks).map(cleanText);
        const sharedMaximums = !maximums.length && pdfMaximumNetworks.some(name => /^PPO Dentist$/i.test(name)) &&
            pdfMaximumNetworks.some(name => !/^PPO Dentist$/i.test(name));
        return {
            section_title: "Out-of-Network Benefits",
            networks,
            notes: cleanSectionNotes(toArray(inputs.notes).filter(text => /does\s+not\s+participate|non-?participating|premier/i.test(String(text || "")))),
            codes_with_out_of_network_benefits: codesWithOon.length,
            coverage_rows: coverageRows,
            routine_procedures: apiRoutine.length ? apiRoutine : pdfRoutine,
            maximums_and_deductibles: maximums,
            maximums_shared_with_ppo: sharedMaximums,
            ...(sharedMaximums ? { maximums_note: `The faxback PDF lists one maximum/deductible table for ${uniqueStrings(pdfMaximumNetworks).join(", ")}.` } : {})
        };
    }

    function buildLookupOutcomeMap(toolkitResults, rawByCode) {
        const outcomes = {};
        for (const result of toArray(toolkitResults)) {
            const code = normalizeCode(result?.procedureCode);
            if (!code) continue;
            const detail = rawByCode?.__errorDetails?.get?.(code) || null;
            if (!rawByCode?.has?.(code) && !rawByCode?.__errors?.has?.(code)) continue;
            outcomes[code] = {
                status: result.status === "OK" ? "SUCCESS" : result.status === "FAILED" ? "FAILED" : result.status === "NOT_IN_CODE_LIST" ? "NOT_IN_CODE_LIST" : "UNAVAILABLE",
                http_status: result.httpStatus ?? detail?.http_status ?? null
            };
        }
        return outcomes;
    }

    function findGeneralAccumulatorRow(rows, type) {
        const wanted = String(type || "").toLowerCase();
        return toArray(rows).find(row =>
            String(row?.type || "").toLowerCase() === wanted &&
            !/ortho/i.test(String(row?.category || "")) &&
            !/^\s*orthodont/i.test(String(row?.name || ""))) || null;
    }

    function collectContactPhoneNumbers() {
        const texts = [];
        for (const title of ["Claim & Inquiry Mailing Addresses", "Contact Us", "Claim Reminders"]) {
            texts.push(...extractToolkitSectionParagraphs(title));
            try {
                const section = findToolkitPageSection(title);
                if (section) texts.push(cleanText(section.textContent || ""));
            } catch (_) {
                continue;
            }
        }
        return extractPhoneNumbers(texts.join(" \n "));
    }

    function routineDatesByCode(rows) {
        const byCode = {};
        for (const row of toArray(rows)) {
            const code = normalizeCode(row?.procedureCode);
            const dates = toArray(row?.serviceDates).filter(Boolean);
            if (!code || !dates.length) continue;
            byCode[code] = uniqueStrings([...(byCode[code] || []), ...dates]);
        }
        return byCode;
    }

    function enrichProcedureResults(results, context = {}) {
        const outcomes = context.outcomes || {};
        return toArray(results).map(row => {
            if (!row || typeof row !== "object") return row;
            const code = normalizeCode(row.procedureCode);
            const lookupStatus = row.result_source === "PDF_ONLY" ? "PDF_ONLY" : classifyLookupStatus(outcomes[code]);
            const enriched = { ...row, lookup_status: lookupStatus };
            const routineDates = uniqueStrings(toArray(context.routineDatesByCode?.[code]));
            if (routineDates.length && !toArray(enriched.utilization_history).length && enriched.utilization_history_status !== "REQUEST_FAILED") {
                enriched.utilization_history = routineDates;
                enriched.utilization_history_status = "PRESENT_DATES";
            }
            const note = knownCodeNote(code);
            if (lookupStatus === "NOT_IN_PLAN_CODE_TREE") {
                enriched.lookup_note = note || "This code is not in the Toolkit's procedure code list (HTTP 404 on two attempts), so the portal returns no benefit for it. Verify by phone or with a pre-treatment estimate.";
                const inferred = inferOrthoCoverage(code, context.orthoSchedule, context.coverageRows);
                if (inferred && (enriched.percentCovered === null || enriched.percentCovered === undefined)) {
                    enriched.percentCovered = inferred.percentCovered;
                    enriched.coverage_inferred_from = inferred.basis;
                }
            } else if (lookupStatus === "LOOKUP_FAILED") {
                enriched.lookup_note = "The portal lookup failed; re-run the extraction or verify this code manually.";
            } else if (note) {
                enriched.lookup_note = note;
            }
            enriched.percentCovered = normalizePercentText(enriched.percentCovered);
            if ((enriched.waitingPeriod === null || enriched.waitingPeriod === undefined) && ["FOUND", "PDF_ONLY"].includes(lookupStatus)) {
                enriched.waitingPeriod = "N/A";
            }
            if (!enriched.description) {
                const path = toArray(enriched.procedurePath);
                const label = context.labels?.[code];
                enriched.description = (label && label !== code ? label : null) || cleanText(path[1]?.procedure || "") || label || null;
            }
            const historyStatus = {
                PRESENT_DATES: "HISTORY_RETURNED",
                EXPLICIT_EMPTY: "NO_HISTORY_ON_FILE",
                NOT_RETURNED: "NOT_RETURNED_BY_PORTAL",
                PARSE_FAILED: "HISTORY_UNREADABLE",
                REQUEST_FAILED: "LOOKUP_FAILED"
            }[enriched.utilization_history_status];
            enriched.history_status = historyStatus || (lookupStatus === "PDF_ONLY" ? "NOT_REQUESTED" : "NOT_RETURNED_BY_PORTAL");
            const { applicable, related } = resolveCodeLimitations(enriched, context.records);
            enriched.applicable_limitations = applicable;
            if (related.length) enriched.related_limitations = related;
            enriched.frequency = applicable.filter(isFrequencyRule);
            enriched.age_limits = typeof extractAgeRestrictions === "function" ? extractAgeRestrictions(applicable) : [];
            if ((lookupStatus === "FOUND" || lookupStatus === "PDF_ONLY") && /not\s+covered|^0+(?:\.0+)?%?$/i.test(cleanText(String(enriched.percentCovered || "")))) {
                enriched.deductible_applies = "N/A";
                enriched.deductible_basis = "The code is not covered.";
            } else if (lookupStatus === "FOUND" || lookupStatus === "PDF_ONLY") {
                const deductible = deductibleAppliesForCode(enriched, context.deductibleRow);
                enriched.deductible_applies = deductible.value;
                enriched.deductible_basis = deductible.basis;
            }
            return enriched;
        });
    }

    function buildPatientAndPlanSection(inputs = {}) {
        const pdf = inputs.pdfEligibility || {};
        const member = inputs.selectedMember || {};
        const display = inputs.display || {};
        const mailing = inputs.mailing || {};
        const meaningful = value => {
            const text = cleanText(String(value ?? ""));
            return text && !/^(?:n\/?a|null|undefined)$/i.test(text) ? text : null;
        };
        const first = (...values) => values.map(meaningful).find(Boolean) || null;
        const relationship = first(pdf.relationship, member.relationship);
        const patientName = first(pdf.patient_name, member.name);
        const subscriberFromSources = first(pdf.member_name, inputs.apiSubscriberName);
        const isSubscriber = relationship
            ? /^(?:self|subscriber|member|employee|insured)$/i.test(relationship)
            : Boolean(patientName && subscriberFromSources && patientName.toLowerCase() === subscriberFromSources.toLowerCase());
        const eligibleText = meaningful(pdf.currently_eligible);
        const currentlyEligible = eligibleText?.match(/^(Yes|No)\b/i)?.[1] || (meaningful(member.eligibility_status) && /^(?:active|eligible)/i.test(member.eligibility_status) ? "Yes" : null);
        const effectiveDate = displayDateValue(first(member.effective_date)) || first(member.effective_date) || eligibleText?.match(/\d{2}\/\d{2}\/\d{4}/)?.[0] || null;
        const maxRows = toArray(inputs.maxRows);
        const generalRow = maxRows.find(row => /maximum/i.test(String(row?.type || "")) && !/ortho/i.test(String(row?.category || ""))) ||
            maxRows.find(row => row?.from && row?.to) || null;
        const from = generalRow?.from || null;
        const to = generalRow?.to || null;
        const isCalendar = /^01\/01\//.test(String(from || "")) && /^12\/31\//.test(String(to || ""));
        const periodType = first(inputs.accumulationPeriodType) || (from ? (isCalendar ? "Calendar Year" : "Fiscal Year") : null);
        const planName = first(pdf.product, display.product);
        const groupNumber = first(pdf.client_number, display.clientNumber,
            inputs.clientSpecifiedId && inputs.subClientSpecifiedId ? `${inputs.clientSpecifiedId}-${inputs.subClientSpecifiedId}` : null,
            inputs.clientSpecifiedId);
        const groupParts = String(groupNumber || "").split("-");
        const pdfAddress = pdf.claims_mailing_address || {};
        const payerIds = uniqueStrings([
            ...toArray(pdfAddress.payer_ids),
            ...String(mailing.payorId || "").split(/\s*,\s*/),
            ...toArray(mailing.payerIds)
        ].map(value => cleanText(value)).filter(Boolean));
        const planAcronym = first(inputs.planAcronym);
        const apiPhone = first(mailing.phoneNumber, mailing.subscriberPhoneNumber);
        const pagePhone = first(...toArray(inputs.pagePhoneNumbers));
        const address = mailing.claimMailingAddress && typeof mailing.claimMailingAddress === "object" && mailing.claimMailingAddress.street
            ? mailing.claimMailingAddress
            : (pdfAddress.street ? { name: pdfAddress.name || null, street: pdfAddress.street, city_state_zip: pdfAddress.city_state_zip || null } : null);
        const termination = inputs.termination || null;
        const providerNetwork = first(inputs.providerNetworkOnPage);
        return {
            section_title: "Patient & Plan",
            patient: {
                name: patientName,
                date_of_birth: normalizeDobValue(member.dob),
                member_id: first(member.member_id),
                relationship_to_subscriber: relationship,
                is_subscriber: isSubscriber,
                currently_eligible: currentlyEligible,
                eligibility_status: first(member.eligibility_status) || (currentlyEligible === "Yes" ? "Eligible" : currentlyEligible === "No" ? "Not eligible" : null),
                effective_date: effectiveDate,
                termination_date: termination?.value ? (displayDateValue(termination.value) || termination.value) : null,
                termination_date_status: termination?.value ? "RETURNED" : "NONE_RETURNED"
            },
            subscriber: {
                name: isSubscriber ? patientName : subscriberFromSources
            },
            family_members: toArray(inputs.familyMembers).map(item => ({
                name: first(item?.patientName),
                date_of_birth: normalizeDobValue(item?.birthdate),
                relationship: first(item?.relationship),
                eligibility: first(item?.eligibility),
                effective_date: first(item?.effectiveDate),
                selected: Boolean(item?.selected)
            })).filter(item => item.name),
            carrier: {
                name: first(address?.name, pdfAddress.name) || "Delta Dental",
                plan_acronym: planAcronym,
                state: stateNameForPlanAcronym(planAcronym),
                website: first(pdf.coordination_of_benefits?.website)
            },
            plan: {
                plan_name: planName,
                plan_type: planTypeFromProduct(planName),
                group_name: first(pdf.client_name, display.clientName, display.subGroupName, inputs.subGroupName),
                group_number: groupNumber,
                client_number: first(inputs.clientSpecifiedId, groupParts[0]),
                subgroup_number: first(inputs.subClientSpecifiedId, groupParts[1]),
                subgroup_name: first(display.subGroupName, inputs.subGroupName),
                benefit_period_type: periodType,
                plan_year_start_month: from ? monthName(from) : null,
                benefit_period: { from, to },
                eligibility_notes: uniqueStrings([pdf.client_information])
            },
            claims: {
                payer_ids: payerIds,
                payer_id_matching_plan: planAcronym && payerIds.includes(planAcronym) ? planAcronym : null,
                mailing_address: address,
                inquiry_address: mailing.inquiryAddress || null,
                phone_number: apiPhone || pagePhone || null,
                phone_number_status: apiPhone ? "PROVIDED_BY_PORTAL_API" : pagePhone ? "FOUND_ON_PAGE" : "NOT_PROVIDED_BY_PORTAL"
            },
            network: {
                benefits_network: first(inputs.selectedNetwork) || "PPO Dentist",
                provider_network_on_page: providerNetwork,
                provider_participation: providerNetwork ? "SHOWN_ON_PAGE" : "NOT_STATED_BY_PORTAL",
                note: "Benefit values are the PPO Dentist level. The portal does not state whether the treating office participates in that network."
            }
        };
    }

    function provisionFound(value, evidence = [], source = null, extra = {}) {
        return { value, answer_status: "FOUND", evidence: uniqueStrings(toArray(evidence)), source, ...extra };
    }

    function provisionDerived(value, evidence = [], source = null, extra = {}) {
        return { value, answer_status: "DERIVED", evidence: uniqueStrings(toArray(evidence)), source, ...extra };
    }

    function provisionNotStated(note, evidence = [], extra = {}) {
        return { value: null, answer_status: "NOT_STATED", evidence: uniqueStrings(toArray(evidence)), source: null, note, ...extra };
    }

    function buildPlanProvisions(out, extras = {}) {
        const results = toArray(out?.coverages?.procedure_code_search?.results);
        const byCode = new Map(results.map(row => [normalizeCode(row?.procedureCode), row]));
        const coverageRows = toArray(out?.coverages?.coverage_rows);
        const records = toArray(out?.exclusions_and_limitations?.records);
        const rules = uniqueStrings(records.flatMap(record => toArray(record?.exclusionsAndLimitations)));
        const maxRows = toArray(out?.maximums_and_deductibles?.rows);
        const ortho = out?.ortho_information || {};
        const cob = out?.more_information?.cob_information || {};
        const cobConfig = cob.cobConfig || {};
        const ages = out?.more_information?.age_limitations?.ageLimitations || {};
        const notes = uniqueStrings([
            ...toArray(out?.coverages?.notes), ...toArray(out?.maximums_and_deductibles?.notes), ...toArray(ortho.notes),
            ortho.crowns_bridges_dentures_payment_note, ...toArray(cob.notes), ...toArray(out?.claim_reminders?.messages),
            ...toArray(extras.pdfNotes)
        ]);
        const corpus = uniqueStrings([...rules, ...notes]);
        const hits = pattern => corpus.filter(text => pattern.test(text));
        const notCovered = value => /not\s+covered/i.test(String(value ?? ""));
        const isRealWait = value => {
            if (value === null || value === undefined) return false;
            const text = cleanText(typeof value === "string" ? value : JSON.stringify(value));
            return Boolean(text) && !/^(?:n\/?a|none|no|not applicable|-+|0(?:\s*months?)?|null|\[\])$/i.test(text);
        };
        const isOrthoRow = row => /ortho/i.test(String(row?.category || "")) || /^\s*orthodont/i.test(String(row?.name || ""));
        const generalMax = maxRows.find(row => /maximum/i.test(String(row?.type || "")) && !isOrthoRow(row)) || null;
        const orthoMax = maxRows.find(row => /maximum/i.test(String(row?.type || "")) && isOrthoRow(row)) || null;
        const generalDeductible = maxRows.find(row => /deductible/i.test(String(row?.type || "")) && !isOrthoRow(row)) || null;
        const orthoDeductible = maxRows.find(row => /deductible/i.test(String(row?.type || "")) && isOrthoRow(row)) || null;
        const percentOf = code => byCode.get(code)?.percentCovered ?? null;
        const categoryCoverage = names => {
            const wanted = names.map(name => name.toLowerCase());
            const rows = coverageRows.filter(row => wanted.includes(cleanText(row?.procedure || "").toLowerCase()));
            const codeRows = results.filter(row => wanted.includes(cleanText(toArray(row?.procedurePath)[0]?.procedure || "").toLowerCase()) && row?.percentCovered !== null && row?.percentCovered !== undefined);
            const values = [...rows.map(row => row.percentCovered), ...codeRows.map(row => row.percentCovered)].filter(value => value !== null && value !== undefined);
            if (!values.length) return provisionNotStated(`No ${names.join("/")} coverage was returned.`);
            const covered = values.some(value => !notCovered(value));
            const evidence = [...rows.map(row => `${row.procedure}: ${normalizePercentText(row.percentCovered)}`), ...codeRows.slice(0, 6).map(row => `${row.procedureCode}: ${normalizePercentText(row.percentCovered)}`)];
            return provisionDerived(covered ? "Yes" : "No", evidence, "coverages");
        };
        const provisions = {};

        const waits = [];
        for (const row of coverageRows) if (isRealWait(row?.waitingPeriod)) waits.push({ name: row.procedure, value: row.waitingPeriod });
        for (const row of results) if (isRealWait(row?.waitingPeriod)) waits.push({ name: row.procedureCode, value: row.waitingPeriod });
        provisions.waiting_period = waits.length
            ? provisionFound("Yes", waits.map(item => `${item.name}: ${typeof item.value === "string" ? item.value : JSON.stringify(item.value)}`), "coverages", { applies_to: uniqueStrings(waits.map(item => item.name)) })
            : (results.length || coverageRows.length
                ? provisionDerived("No", [`No waiting period on ${coverageRows.length} coverage categories or ${results.length} procedure codes.`], "coverages", { applies_to: [] })
                : provisionNotStated("No coverage data was returned."));

        const replacePayable = hits(/replace\s+a\s+tooth\s+that\s+(?:has\s+been|was)\s+missing\s+prior/i);
        const missingClause = hits(/missing\s+tooth\s+(?:clause|limitation|exclusion|provision)|not\s+(?:payable|covered)[^.]*(?:tooth|teeth)[^.]*missing\s+(?:prior|before)/i);
        provisions.missing_tooth_clause = replacePayable.length
            ? provisionDerived("No", replacePayable, "exclusions_and_limitations", { note: "The plan pays to replace a tooth missing before the effective date." })
            : missingClause.length ? provisionDerived("Yes", missingClause, "exclusions_and_limitations") : provisionNotStated("No missing-tooth wording was returned.");

        const seat = hits(/seat(?:\/|\s+or\s+|\s+)?(?:delivery)?\s*date|delivery\s+date/i);
        const prep = hits(/prep(?:aration)?\s+date|date\s+of\s+preparation/i);
        provisions.major_services_paid_on = seat.length ? provisionDerived("Seat", seat, "notes")
            : prep.length ? provisionDerived("Prep", prep, "notes") : provisionNotStated("Prep-vs-seat payment rule was not stated.");

        const preauthRequired = hits(/pre-?(?:authorization|determination|treatment\s+estimate|estimate)s?\s+(?:is|are)\s+required|requires?\s+(?:a\s+)?pre-?(?:authorization|determination)/i);
        const preauthOptional = hits(/(?:can|may)\s+be\s+determined\s+by\s+(?:the\s+)?submission\s+of\s+a\s+pre-?treatment\s+estimate|pre-?treatment\s+estimates?\s+(?:is|are)\s+(?:optional|recommended)/i);
        provisions.preauth_required = preauthRequired.length ? provisionDerived("Yes", preauthRequired, "notes")
            : preauthOptional.length ? provisionDerived("No", preauthOptional, "notes", { note: "The portal describes a pre-treatment estimate as optional; it does not say one is required." })
                : provisionNotStated("Pre-authorization requirement was not stated.");
        const preauthAmountText = hits(/(?:pre-?(?:authorization|auth|treatment|determination)|predetermination)[^.]*\$\s?[\d,]+/i);
        const preauthAmount = preauthAmountText.join(" ").match(/\$\s?([\d,]+(?:\.\d{2})?)/)?.[1];
        provisions.preauth_over_amount = preauthAmount ? provisionDerived(`$${preauthAmount}`, preauthAmountText, "notes") : provisionNotStated("No pre-authorization dollar threshold was returned.");

        const paymentOption = cleanText(cobConfig.paymentOptionType || "");
        const cobLines = toArray(cob.notes).filter(text => /^(?:Payment Order|Internal COB|External COB|Payment Option Type)/i.test(text));
        provisions.coordination_of_benefits = paymentOption
            ? provisionFound(/non-?dup/i.test(paymentOption) ? "Non-duplication" : paymentOption, cobLines, "more_information.cob_information", {
                internal_cob_allowed: cobConfig.internalCOBIndicator === undefined ? null : Boolean(cobConfig.internalCOBIndicator),
                external_cob_allowed: cobConfig.externalCOBIndicator === undefined ? null : Boolean(cobConfig.externalCOBIndicator),
                payment_order: cobConfig.paymentOrdertype || null
            })
            : cobLines.length ? provisionFound(cobLines.join(" | "), cobLines, "more_information.cob_information") : provisionNotStated("No COB information was returned.");
        provisions.birthday_rule_applies = cobConfig.paymentOrdertype
            ? provisionFound(/birthday/i.test(cobConfig.paymentOrdertype) ? "Yes" : "No", [`Payment Order: ${cobConfig.paymentOrdertype}`], "more_information.cob_information")
            : provisionNotStated("COB payment order was not returned.");

        const deductibleText = cleanText(String(generalDeductible?.description || "")).replace(/x-\s+rays/gi, "X-rays");
        const exemptPart = deductibleText.match(/(?:does\s+not\s+apply\s+to|except(?:\s+for)?|excluding|waived\s+(?:for|on))\s+(.*)$/i)?.[1] || "";
        const deductibleApplies = (pattern, label) => {
            if (!generalDeductible) return provisionNotStated("No deductible row was returned.");
            if (Number(generalDeductible?.individual?.amount) === 0) return provisionDerived("N/A", ["Individual deductible is $0."], "maximums_and_deductibles");
            return pattern.test(exemptPart)
                ? provisionDerived("No", [deductibleText], "maximums_and_deductibles")
                : provisionDerived("Yes", [deductibleText || `Deductible wording does not exempt ${label}.`], "maximums_and_deductibles");
        };
        provisions.deductible_applies_to_preventive = deductibleApplies(/prevent(?:at)?ive/i, "preventive services");
        provisions.deductible_applies_to_diagnostic = deductibleApplies(/diagnostic/i, "diagnostic services");
        provisions.deductible_period = generalDeductible
            ? provisionDerived(generalDeductible.isLifetime ? "Lifetime" : (cleanText(out?.maximums_and_deductibles?.accumulationPeriodType || "") || "Per benefit period"), [`${generalDeductible.from || "?"} to ${generalDeductible.to || "?"}`], "maximums_and_deductibles")
            : provisionNotStated("No deductible row was returned.");

        const maxDescription = cleanText(String(generalMax?.description || generalMax?.name || ""));
        const maxExceptions = maxDescription.match(/except(?:\s+for)?\s+(.*)$/i)?.[1] || "";
        provisions.preventive_counts_toward_maximum = generalMax
            ? provisionDerived(/prevent(?:at)?ive|diagnostic/i.test(maxExceptions) ? "No" : "Yes", [maxDescription], "maximums_and_deductibles")
            : provisionNotStated("No annual maximum row was returned.");
        const familyValue = (row, pdfValue, label) => {
            if (!row) return provisionNotStated(`No ${label} row was returned.`);
            const amount = row?.family?.amount;
            if (amount !== null && amount !== undefined && Number(amount) > 0) {
                return provisionFound(Number(amount), [`Family ${label}: $${amount}; used $${row.family.used ?? "?"}`], "maximums_and_deductibles", { used: row.family.used ?? null, remaining: row.family.remaining ?? null });
            }
            if (pdfValue !== null && pdfValue !== undefined && Number(pdfValue) > 0) return provisionFound(Number(pdfValue), ["Family amount from the faxback PDF."], "faxback_pdf");
            return provisionDerived("Not applicable", [`The website shows a $${amount ?? 0} family ${label} and the faxback PDF shows none.`], "maximums_and_deductibles");
        };
        provisions.family_deductible = familyValue(generalDeductible, extras.pdfFamilyDeductible, "deductible");
        provisions.family_maximum = familyValue(generalMax, extras.pdfFamilyMaximum, "maximum");
        const rollover = hits(/roll\s?over|carry\s?over|carryover/i);
        provisions.rollover_maximum = rollover.length ? provisionFound(rollover[0], rollover, "notes") : provisionNotStated("No rollover/carry-over maximum was returned.");

        const nonPpo = extras.nonPpo || { codesWithNonPpoBenefits: 0, networks: [] };
        const oonNote = hits(/(?:does\s+not\s+participate|non-?participating)[^.]*(?:percent|responsible|paid)/i);
        provisions.out_of_network_benefits = nonPpo.codesWithNonPpoBenefits > 0
            ? provisionDerived("Yes", [`${nonPpo.codesWithNonPpoBenefits} procedure code(s) returned benefit percentages for ${toArray(nonPpo.networks).join(", ") || "non-PPO networks"}.`, ...oonNote], "procedure responses")
            : oonNote.length ? provisionDerived("Yes", oonNote, "coverages.notes") : provisionNotStated("No out-of-network benefit information was returned.");

        const from = generalMax?.from || generalDeductible?.from || null;
        const to = generalMax?.to || generalDeductible?.to || null;
        const periodType = cleanText(out?.maximums_and_deductibles?.accumulationPeriodType || "") ||
            (from ? (/^01\/01\//.test(from) && /^12\/31\//.test(String(to || "")) ? "Calendar Year" : "Fiscal Year") : "");
        provisions.plan_year_type = periodType ? provisionFound(periodType, [`${from || "?"} to ${to || "?"}`], "maximums_and_deductibles") : provisionNotStated("Benefit period was not returned.");
        provisions.plan_year_start_month = from && monthName(from) ? provisionFound(monthName(from), [`Benefit period starts ${from}`], "maximums_and_deductibles") : provisionNotStated("Benefit period start was not returned.");

        const rulesFor = code => toArray(byCode.get(code)?.applicable_limitations);
        const sharedRule = (codes, pattern) => {
            const shared = rules.filter(text => pattern.test(text) && isFrequencyRule(text));
            const covered = codes.filter(code => rulesFor(code).some(text => shared.includes(text)));
            return { shared, covered };
        };
        const exams = sharedRule(["D0120", "D0140", "D0150"], /oral\s+examin|examinations?/i);
        provisions.exams_share_frequency = exams.shared.length && exams.covered.length >= 2
            ? provisionDerived("Yes", exams.shared, "exclusions_and_limitations", { codes: exams.covered, note: "One oral-examination frequency rule covers these exam codes." })
            : provisionNotStated("The portal gives no shared exam frequency rule.", uniqueStrings(["D0120", "D0140", "D0150"].flatMap(rulesFor)));
        const fmx = rules.filter(text => /full\s+mouth/i.test(text) && /panorex|panoramic/i.test(text));
        provisions.fmx_and_pano_share_frequency = fmx.length ? provisionDerived("Yes", fmx, "exclusions_and_limitations") : provisionNotStated("No combined FMX/panoramic rule was returned.", uniqueStrings([...rulesFor("D0210"), ...rulesFor("D0330")]));
        const prophyPerio = hits(/(?:prophylax|cleaning)[^.]*periodontal\s+maint|periodontal\s+maint[^.]*(?:prophylax|cleaning)/i);
        provisions.prophy_and_perio_maintenance_share_frequency = prophyPerio.length
            ? provisionDerived(/separate|in\s+addition|do(?:es)?\s+not\s+count/i.test(prophyPerio.join(" ")) ? "No" : "Yes", prophyPerio, "exclusions_and_limitations")
            : provisionNotStated("The portal does not say whether D4910 shares the prophylaxis frequency; confirm with the carrier.", [...toArray(byCode.get("D4910")?.related_limitations), ...rulesFor("D1110")]);
        const quadsPerDay = hits(/(?:quadrants?|quads?)[^.]*\b(?:per\s+day|daily|same[- ]day|per\s+visit|per\s+appointment)\b|\b(?:limited|limit|maximum|no more than|up to)[^.]*\b(?:one|two|three|four|[1-4])\s+(?:quadrants?|quads?)\b/i);
        provisions.srp_quadrants_per_visit = quadsPerDay.length
            ? provisionDerived(quadsPerDay.join(" ").match(/\b([1-4]|one|two|three|four)\s+(?:quadrants?|quads?)/i)?.[1] || quadsPerDay[0], quadsPerDay, "exclusions_and_limitations")
            : provisionNotStated("The portal gives a per-quadrant frequency but no per-visit quadrant limit.", rulesFor("D4341"));
        provisions.srp_frequency = rulesFor("D4341").length ? provisionFound(rulesFor("D4341").join(" | "), rulesFor("D4341"), "coverages.procedure_code_search") : provisionNotStated("No SRP frequency was returned.");

        const posteriorCovered = hits(/posterior\s+composite[^.]*\bare\s+covered|composites?\s+(?:on|for)\s+posterior[^.]*\bcovered/i).filter(text => !/not\s+covered/i.test(text));
        const posteriorDowngrade = hits(/posterior\s+composite[^.]*(?:amalgam|alternate|optioned|downgrad|not\s+covered)|(?:amalgam|alternate|optioned|downgrad)[^.]*posterior\s+composite/i);
        provisions.posterior_composites_covered = posteriorDowngrade.some(text => /not\s+covered/i.test(text))
            ? provisionDerived("No", posteriorDowngrade, "exclusions_and_limitations")
            : posteriorCovered.length ? provisionDerived("Yes", posteriorCovered, "exclusions_and_limitations") : provisionNotStated("No posterior composite wording was returned.");
        provisions.posterior_composites_downgraded = posteriorDowngrade.length
            ? provisionDerived("Yes", posteriorDowngrade, "exclusions_and_limitations")
            : posteriorCovered.length ? provisionDerived("No", posteriorCovered, "exclusions_and_limitations") : provisionNotStated("No posterior composite downgrade wording was returned.");
        const crownDowngrade = hits(/crowns?[^.]*(?:downgrad|alternate\s+benefit|least\s+costly|base\s+metal|optioned)|(?:downgrad|alternate\s+benefit|least\s+costly)[^.]*crowns?/i);
        provisions.crown_downgrade = crownDowngrade.length ? provisionDerived("Yes", crownDowngrade, "exclusions_and_limitations")
            : provisionNotStated("The portal does not say whether porcelain/ceramic crowns are downgraded; confirm with the carrier.", rulesFor("D2740"));
        const inlay = hits(/inlays?[^.]*(?:optioned|alternate|downgrad|amalgam)/i);
        provisions.inlays_downgraded = inlay.length ? provisionDerived("Yes", inlay, "exclusions_and_limitations") : provisionNotStated("No inlay downgrade wording was returned.");

        const sealantRules = uniqueStrings([...rulesFor("D1351"), ...hits(/sealants?/i)]);
        provisions.sealants_premolars_covered = sealantRules.some(text => /premolar|bicuspid/i.test(text))
            ? provisionDerived("Yes", sealantRules, "exclusions_and_limitations")
            : sealantRules.some(text => /molars?/i.test(text)) ? provisionDerived("No", sealantRules, "exclusions_and_limitations", { note: "The sealant rule names molars only." })
                : provisionNotStated("No sealant tooth rule was returned.");
        provisions.sealant_limitations = sealantRules.length ? provisionFound(sealantRules.join(" | "), sealantRules, "exclusions_and_limitations") : provisionNotStated("No sealant rule was returned.");
        const fluorideRules = uniqueStrings([...rulesFor("D1206"), ...rulesFor("D1208"), ...hits(/fluoride\s+treatments?/i)]);
        provisions.fluoride_limitations = fluorideRules.length ? provisionFound(fluorideRules.join(" | "), fluorideRules, "exclusions_and_limitations") : provisionNotStated("No fluoride rule was returned.");
        const dentures = hits(/full\s+and\s+partial\s+dentures|partial\s+(?:and|or)\s+(?:full|complete)\s+dentures|(?:complete|full)\s+(?:and|or)\s+partial/i);
        provisions.partial_dentures_share_frequency_with_dentures = dentures.length
            ? provisionDerived("Yes", dentures, "exclusions_and_limitations", { note: "One rule covers full and partial dentures." })
            : provisionNotStated("No combined denture rule was returned.");

        provisions.endodontics_covered = categoryCoverage(["Endodontics"]);
        provisions.periodontics_covered = categoryCoverage(["Periodontics"]);
        provisions.oral_surgery_covered = categoryCoverage(["Simple Extractions", "Other Oral Surgery", "Oral Surgery"]);
        provisions.implants_covered = categoryCoverage(["Implants"]);
        provisions.prosthodontics_covered = categoryCoverage(["Prosthodontics"]);
        provisions.orthodontics_covered = categoryCoverage(["Orthodontic Services", "Orthodontics"]);
        const majorPercent = normalizePercentText(coverageRows.find(row => /^major\s+restorative$/i.test(cleanText(row?.procedure || "")))?.percentCovered ?? percentOf("D2740"));
        const perioSurgery = normalizePercentText(percentOf("D4260"));
        const perioNonSurgical = normalizePercentText(percentOf("D4341"));
        provisions.periodontics_coverage_level = perioSurgery || perioNonSurgical
            ? provisionDerived(`Non-surgical (D4341) ${perioNonSurgical || "n/a"}; surgical (D4260) ${perioSurgery || "n/a"}${majorPercent ? `; major restorative is ${majorPercent}` : ""}`,
                [perioNonSurgical ? `D4341: ${perioNonSurgical}` : null, perioSurgery ? `D4260: ${perioSurgery}` : null].filter(Boolean), "coverages.procedure_code_search",
                { surgical_paid_at_major_level: Boolean(perioSurgery && majorPercent && perioSurgery === majorPercent) })
            : provisionNotStated("No periodontic code coverage was returned.");

        const orthoCovered = provisions.orthodontics_covered.value;
        const adult = percentOf("D8090");
        provisions.adult_orthodontics_covered = adult !== null && adult !== undefined
            ? provisionDerived(notCovered(adult) ? "No" : "Yes", [`D8090: ${normalizePercentText(adult)}`], "coverages.procedure_code_search")
            : provisionNotStated("D8090 was not returned.");
        const orthoNA = note => provisionDerived("Not applicable", [note], "coverages");
        provisions.ortho_lifetime_maximum = orthoMax
            ? provisionFound(Number(orthoMax.individual?.amount ?? 0), [`Used $${orthoMax.individual?.used ?? "?"}`], "maximums_and_deductibles", { used: orthoMax.individual?.used ?? null, remaining: orthoMax.individual?.remaining ?? null })
            : orthoCovered === "No" ? orthoNA("Orthodontics is not covered.") : provisionNotStated("No orthodontic maximum row was returned.");
        provisions.ortho_deductible = orthoDeductible
            ? provisionFound(Number(orthoDeductible.individual?.amount ?? 0), [`Met $${orthoDeductible.individual?.used ?? "?"}`], "maximums_and_deductibles", { met: orthoDeductible.individual?.used ?? null })
            : orthoCovered === "No" ? orthoNA("Orthodontics is not covered.")
                : /orthodon/i.test(exemptPart) ? provisionDerived("Not applicable", [deductibleText], "maximums_and_deductibles") : provisionNotStated("No orthodontic deductible row was returned.");
        const orthoAge = toArray(ortho.orthoAgeLimitConfig)[0] || null;
        provisions.ortho_age_limit = orthoAge
            ? provisionFound(`Dependents ${orthoAge.minorMinAge ?? 0} to ${orthoAge.minorMaxAge ?? "n/a"}; subscribers ${orthoAge.subscriberMinAge ?? 0} to ${orthoAge.subscriberMaxAge ?? "n/a"}`, [ortho.ortho_age_limit_note].filter(Boolean), "ortho_information.orthoAgeLimitConfig")
            : ortho.ortho_age_limit_under ? provisionFound(`Under ${ortho.ortho_age_limit_under}`, [ortho.ortho_age_limit_note].filter(Boolean), "ortho_information")
                : orthoCovered === "No" ? orthoNA("Orthodontics is not covered.") : provisionNotStated("No orthodontic age limit was returned.");
        const schedule = ortho.orthoPaymentSchedule || null;
        provisions.ortho_payment_frequency = schedule?.paymentFrequencyType?.value
            ? provisionFound(schedule.paymentFrequencyType.value, [`Payment frequency: ${schedule.paymentFrequencyType.value}`], "ortho_information.orthoPaymentSchedule", orthoCovered === "No" ? { note: "Plan schedule setting; orthodontics is not covered for this plan." } : {})
            : provisionNotStated("No orthodontic payment schedule was returned.");
        const initialType = cleanText(schedule?.initialPayType?.value || "");
        const initialValue = /percent/i.test(initialType) && schedule?.initialPaymentPercent !== undefined
            ? `${schedule.initialPaymentPercent}%`
            : schedule?.initialPaymentAmount !== undefined && schedule?.initialPaymentAmount !== null ? `$${schedule.initialPaymentAmount}` : null;
        provisions.ortho_initial_payment = initialValue
            ? provisionFound(initialValue, [`Initial payment type: ${initialType || "n/a"}`], "ortho_information.orthoPaymentSchedule", orthoCovered === "No" ? { note: "Plan schedule setting; orthodontics is not covered for this plan." } : {})
            : provisionNotStated("No orthodontic initial payment was returned.");
        const wip = hits(/work\s+in\s+progress|treatment\s+in\s+progress|in-progress/i);
        provisions.ortho_work_in_progress_covered = wip.length ? provisionDerived(/not\s+covered/i.test(wip.join(" ")) ? "No" : "Yes", wip, "notes") : provisionNotStated("Work-in-progress coverage was not stated.");

        const ageText = (age, type) => age !== null && age !== undefined && age !== "" ? `${age}${type ? ` (${type})` : ""}` : null;
        const dependentAge = ageText(ages.childMaxAgeLimit, ages.childMaxAgeLimitType);
        provisions.dependent_age_limit = dependentAge ? provisionFound(dependentAge, [`childMaxAgeLimit: ${ages.childMaxAgeLimit}`], "more_information.age_limitations") : provisionNotStated("Dependent age limit was not returned.");
        const studentAge = ageText(ages.studentMaxAgeLimit, ages.studentMaxAgeLimitType);
        provisions.full_time_student_age_limit = studentAge ? provisionFound(studentAge, [`studentMaxAgeLimit: ${ages.studentMaxAgeLimit}`], "more_information.age_limitations") : provisionNotStated("Student age limit was not returned.");
        provisions.student_verification_required = typeof ages.studentDocumentRequired === "boolean"
            ? provisionFound(ages.studentDocumentRequired ? "Yes" : "No", [`studentDocumentRequired: ${ages.studentDocumentRequired}`], "more_information.age_limitations")
            : provisionNotStated("Student documentation requirement was not returned.");
        provisions.subscriber_age_limit = provisionNotStated("The portal returns no subscriber age limit outside orthodontics.");

        const bruxism = hits(/bruxism|grinding/i);
        provisions.occlusal_guard_bruxism_only = bruxism.length ? provisionDerived(/\bonly\b/i.test(bruxism.join(" ")) ? "Yes" : "No", bruxism, "exclusions_and_limitations") : provisionNotStated("No bruxism wording was returned.", rulesFor("D9944"));
        const medicalEob = hits(/medical\s+(?:eob|explanation\s+of\s+benefits|denial)|bill\s+(?:the\s+)?medical/i);
        provisions.medical_eob_required_for_oral_surgery = medicalEob.length ? provisionDerived("Yes", medicalEob, "notes") : provisionNotStated("Medical EOB requirement was not stated.");
        const timely = hits(/timely\s+filing|(?:submitted|filed)\s+within\s+\d+\s+(?:days|months)/i);
        provisions.timely_filing_limit = timely.length ? provisionFound(timely[0], timely, "notes") : provisionNotStated("Timely filing limit was not stated.");
        const sameDay = (key, subject, note) => {
            const found = hits(new RegExp(`(?:${subject})[^.]*same\\s+(?:day|date)|same\\s+(?:day|date)[^.]*(?:${subject})`, "i"));
            provisions[key] = found.length ? provisionDerived(/not|no\b/i.test(found.join(" ")) ? "No" : "Yes", found, "notes") : provisionNotStated(note);
        };
        sameDay("arestin_same_day_as_srp", "arestin|antimicrobial|D4381", "Same-day Arestin/SRP rule was not stated.");
        sameDay("consultation_same_day_as_other_services", "consult|D9310", "Same-day consultation rule was not stated.");
        sameDay("buildup_same_day_as_crown", "build-?up|core|D2950", "Same-day build-up/crown rule was not stated.");
        sameDay("limited_exam_same_day_as_treatment", "limited\\s+(?:exam|evaluation)|D0140", "Same-day limited exam rule was not stated.");
        sameDay("bone_graft_same_day_as_extraction", "bone\\s+graft|D7953|D6104", "Same-day bone graft/extraction rule was not stated.");
        const firstPerio = hits(/(?:periodontal\s+maint|D4910)[^.]*(?:after|following)[^.]*(?:scaling|root\s+planing|D434[12])/i);
        provisions.first_perio_maintenance_after_srp = firstPerio.length ? provisionFound(firstPerio[0], firstPerio, "notes") : provisionNotStated("Timing of the first D4910 after SRP was not stated.");

        const anesthesia = hits(/general\s+anesthesia|iv\s+sedation/i);
        provisions.general_anesthesia_rules = anesthesia.length ? provisionFound(anesthesia.join(" | "), anesthesia, "notes") : provisionNotStated("No anesthesia rule was returned.");
        const xrays = hits(/x-?rays?\s+are\s+required/i);
        provisions.xrays_required_with_claims = xrays.length ? provisionFound(xrays.join(" | "), xrays, "notes") : provisionNotStated("No X-ray submission rule was returned.");
        const enhanced = hits(/enhanced\s+preventive|high-?risk|special\s+health\s+care\s+needs/i);
        provisions.enhanced_preventive_benefits = enhanced.length ? provisionFound("Yes", enhanced, "notes") : provisionNotStated("No enhanced-benefit wording was returned.");
        provisions.plan_pays_to_patient = provisionNotStated("Assignment of benefits (plan pays patient vs. provider) was not stated.");
        const planType = planTypeFromProduct(extras.planName);
        provisions.hmo_copay_id = planType && planType !== "DHMO"
            ? provisionDerived("Not applicable", [`Plan: ${extras.planName}`], "patient_and_plan.plan", { note: "Copay IDs apply to DHMO plans only." })
            : provisionNotStated("No copay schedule ID was returned.");
        const referral = hits(/referral/i);
        provisions.referral_required = referral.length
            ? provisionDerived(/not\s+required|no\s+referral/i.test(referral.join(" ")) ? "No" : "Yes", referral, "notes")
            : provisionNotStated("Referral requirement was not stated.", extras.planName ? [`Plan: ${extras.planName}`] : []);

        return provisions;
    }

    // =====================================================================
    // Member, financial, and general-field helpers
    // =====================================================================

    function normalizeComparableDate(value) {
        const parsed = parseDateLoose(String(value || "").trim());
        if (parsed) return new Date(parsed.time).toISOString().slice(0, 10);
        const date = new Date(String(value || ""));
        return Number.isNaN(date.getTime()) ? cleanText(value || "").toLowerCase() : date.toISOString().slice(0, 10);
    }

    function recordPersonIds(record) {
        if (!record || typeof record !== "object") return [];
        return uniqueStrings([
            record.personId, record.memberPersonId, record.subscriberPersonId,
            record.personOid, record.memberOid, record.subscriberOid, record.oid
        ]).map(cleanText).filter(Boolean);
    }

    function recordName(record, isSubscriber = false) {
        if (!record || typeof record !== "object") return "";
        return firstMeaningful([
            record.fullName, record.memberName, record.name,
            joinName(record.firstName, record.lastName),
            joinName(record.memberFirstName, record.memberLastName),
            isSubscriber ? joinName(record.subscriberFirstName, record.subscriberLastName) : "",
            !isSubscriber ? joinName(record.dependentFirstName, record.dependentLastName) : ""
        ]);
    }

    function recordDob(record) {
        return firstMeaningful([record?.dateOfBirth, record?.dob, record?.birthDate, record?.memberDateOfBirth]);
    }

    function extractSubscriberRecords(root) {
        if (!root) return [];
        if (Array.isArray(root)) {
            const subscriberLike = root.filter(item => item && typeof item === "object");
            const nested = subscriberLike.flatMap(item => extractSubscriberRecords(item));
            return nested.length ? nested : subscriberLike;
        }
        if (typeof root !== "object") return [];
        for (const key of ["subscribers", "subscriberDetails", "members", "memberDetails", "results", "data"]) {
            if (Array.isArray(root[key])) {
                if (key === "subscribers" || root[key].some(item => item?.dependents || item?.subscriberFirstName || item?.subscriberPersonId)) {
                    return root[key];
                }
                const nested = root[key].flatMap(item => extractSubscriberRecords(item));
                if (nested.length) return nested;
            }
        }
        if (root.subscriber && typeof root.subscriber === "object") return [root.subscriber];
        return [];
    }

    function dependentRecords(subscriber) {
        return [
            ...toArray(subscriber?.dependents),
            ...toArray(subscriber?.dependentDetails),
            ...toArray(subscriber?.familyMembers).filter(item => !/subscriber/i.test(String(item?.relationshipToSubscriber || item?.relationship || "")))
        ].filter(item => item && typeof item === "object");
    }

    function matchesDomPerson(record, domMember, isSubscriber = false) {
        if (!record || !domMember?.name) return false;
        const a = cleanText(recordName(record, isSubscriber)).toLowerCase();
        const b = cleanText(domMember.name).toLowerCase();
        if (!a || !b || a !== b) return false;
        if (!domMember.dob || !recordDob(record)) return true;
        return normalizeComparableDate(recordDob(record)) === normalizeComparableDate(domMember.dob);
    }

    function resolveMemberApiContext(memberRoot, template, domMember) {
        const subscribers = extractSubscriberRecords(memberRoot);
        const memberPersonId = cleanText(template?.memberPersonId || "");
        const subscriberPersonId = cleanText(template?.subscriberPersonId || "");

        // Strongest match: current encrypted API person IDs.
        for (const subscriber of subscribers) {
            const subscriberIds = recordPersonIds(subscriber);
            if (subscriberPersonId && subscriberIds.includes(subscriberPersonId)) {
                if (!memberPersonId || subscriberIds.includes(memberPersonId)) {
                    return { matched: true, reason: "api_person_id_subscriber", subscriber, patient: { isSubscriber: true, record: subscriber } };
                }
                const dependent = dependentRecords(subscriber).find(item => recordPersonIds(item).includes(memberPersonId));
                if (dependent) return { matched: true, reason: "api_person_id_dependent", subscriber, patient: { isSubscriber: false, record: dependent } };
            }
        }

        // Some member-detail payloads do not expose the same encrypted IDs. Match the live
        // selected Toolkit row by name + DOB before trusting a stored identity snapshot.
        for (const subscriber of subscribers) {
            if (matchesDomPerson(subscriber, domMember, true)) {
                return { matched: true, reason: "dom_name_dob_subscriber", subscriber, patient: { isSubscriber: true, record: subscriber } };
            }
            const dependent = dependentRecords(subscriber).find(item => matchesDomPerson(item, domMember, false));
            if (dependent) return { matched: true, reason: "dom_name_dob_dependent", subscriber, patient: { isSubscriber: false, record: dependent } };
        }

        // Never fall back to subscribers[0]. If the snapshot cannot be tied to the current
        // selected person, ignore it and let current DOM/request context fill identity fields.
        return { matched: false, reason: subscribers.length ? "member_snapshot_not_current" : "member_details_api_not_captured", subscriber: {}, patient: { isSubscriber: /^subscriber$/i.test(domMember?.relationship || template?.relationshipToSubscriber || ""), record: {} } };
    }

    function sanitizePpoNetworkDataForOutput(value) {
        if (value === null) return null;
        if (value === undefined) return undefined;
        if (Array.isArray(value)) {
            const output = [];
            for (const item of value) {
                // Preserve literal nulls from the native API. A null returned by
                // recursive sanitization for a non-PPO network bucket is omitted.
                if (item === null) {
                    output.push(null);
                    continue;
                }
                const sanitized = sanitizePpoNetworkDataForOutput(item);
                if (sanitized !== null && sanitized !== undefined) output.push(sanitized);
            }
            return output;
        }
        if (typeof value !== "object") return value;

        // DOT uses network-scoped buckets for coverages, accumulators and
        // routine procedures. Discard a network-scoped bucket if PPO Dentist
        // is not one of its networks.
        if (Array.isArray(value.networks) &&
            (Array.isArray(value.accumulators) || Array.isArray(value.coverages) || Array.isArray(value.routineProcedures))) {
            if (!isExactPpoBucket(value)) return null;
        }

        const out = {};
        for (const [key, child] of Object.entries(value)) {
            if (key === "maximumsAndDeductions" && Array.isArray(child)) {
                out[key] = child
                    .filter(isExactPpoBucket)
                    .map(sanitizePpoNetworkDataForOutput)
                    .filter(Boolean);
                continue;
            }
            // Root/member-benefit network metadata is an array of objects such as
            // {name:"PPO Dentist"}, {name:"Premier Dentist"}, {name:"Non-PPO Dentist"}.
            // Network-scoped records also carry arrays of string names. In both cases,
            // retain only PPO Dentist in output while preserving the surrounding shape.
            if (key === "networks" && Array.isArray(child)) {
                if (child.some(item => item && typeof item === "object" && "name" in item)) {
                    out[key] = child
                        .filter(item => /^PPO Dentist$/i.test(cleanText(item?.name || "")))
                        .map(sanitizePpoNetworkDataForOutput)
                        .filter(Boolean);
                    continue;
                }
                if (child.some(item => typeof item === "string" && /^(PPO Dentist|Premier Dentist|Non-PPO Dentist|Nonparticipating Dentist)$/i.test(cleanText(item)))) {
                    out[key] = child
                        .filter(item => /^PPO Dentist$/i.test(cleanText(item)))
                        .map(sanitizePpoNetworkDataForOutput)
                        .filter(Boolean);
                    continue;
                }
            }
            if (child === null) {
                out[key] = null;
                continue;
            }
            const sanitized = sanitizePpoNetworkDataForOutput(child);
            if (sanitized !== null && sanitized !== undefined) out[key] = sanitized;
        }
        return out;
    }

    function buildPpoFinancialRecords(sources, dom) {
        const empty = () => ({ total: "N/A", used: "N/A", remaining: "N/A" });
        const result = {
            annualMax: empty(),
            indDed: empty(),
            famDed: empty(),
            orthoDed: empty(),
            orthoMax: empty()
        };

        const buckets = collectMaximumDeductionBuckets(sources)
            .filter(isExactPpoBucket);
        const accumulators = buckets.flatMap(bucket => toArray(bucket?.accumulators));

        const findAccumulator = (type, category) => accumulators.find(acc => {
            const accumulatorType = cleanText(acc?.accumulatorType).toLowerCase();
            const categoryType = cleanText(acc?.categoryType).toLowerCase();
            const name = cleanText(acc?.name).toLowerCase();
            const isType = accumulatorType === type;
            if (!isType) return false;
            if (category === "orthodontic") {
                return categoryType
                    ? categoryType.includes("orthodont")
                    : name.includes("orthodont");
            }
            if (category === "general") {
                return categoryType
                    ? categoryType.includes("general")
                    : !name.includes("orthodont");
            }
            return true;
        }) || null;

        const asRecord = (acc, family = false) => {
            if (!acc) return empty();
            const total = family ? acc.familyAmount : acc.individualAmount;
            const used = family ? acc.familyAmountUsed : acc.individualAmountUsed;
            const remaining = family ? acc.familyAmountRemaining : acc.individualAmountRemaining;
            return {
                total: moneyValue(total),
                used: moneyValue(used),
                remaining: moneyValue(remaining)
            };
        };

        const generalMax = findAccumulator("maximum", "general");
        const orthoMax = findAccumulator("maximum", "orthodontic");
        const generalDed = findAccumulator("deductible", "general");
        const orthoDed = findAccumulator("deductible", "orthodontic");

        result.annualMax = asRecord(generalMax, false);
        result.orthoMax = asRecord(orthoMax, false);
        result.indDed = asRecord(generalDed, false);
        result.famDed = asRecord(generalDed, true);
        result.orthoDed = asRecord(orthoDed, false);

        // DOM fallback is permitted only for a field absent from the PPO accumulator
        // bucket. It never borrows a value from another network's API bucket.
        const applyDomFallback = (record, labels) => {
            if (record.total === "N/A") record.total = moneyValue(domValue(dom, labels));
            if (record.used === "N/A") record.used = moneyValue(domValue(dom, labels.flatMap(label => [`${label} Paid to Date`, `${label} Used`, `${label} Met`])));
            if (record.remaining === "N/A") record.remaining = moneyValue(domValue(dom, labels.map(label => `${label} Remaining`)));
            return record;
        };
        applyDomFallback(result.annualMax, ["Yearly Maximum", "Annual Maximum"]);
        applyDomFallback(result.indDed, ["Individual Deductible"]);
        applyDomFallback(result.famDed, ["Family Deductible"]);
        applyDomFallback(result.orthoDed, ["Orthodontic Deductible", "Ortho Deductible"]);
        applyDomFallback(result.orthoMax, ["Orthodontic Maximum", "Ortho Maximum", "Ortho Lifetime Maximum"]);

        return result;
    }

    function collectMaximumDeductionBuckets(roots) {
        const found = [];
        const seen = new WeakSet();
        const visit = value => {
            if (!value || typeof value !== "object") return;
            if (seen.has(value)) return;
            seen.add(value);
            if (Array.isArray(value)) {
                for (const item of value) visit(item);
                return;
            }
            if (Array.isArray(value.maximumsAndDeductions)) {
                found.push(...value.maximumsAndDeductions.filter(item => item && typeof item === "object"));
            }
            for (const child of Object.values(value)) visit(child);
        };
        for (const root of toArray(roots)) visit(root);
        return found;
    }

    function buildFinancialRecord(leaves, dom, kind) {
        const specs = {
            annual_max: { scope: [["annual", "yearly"], ["maximum", "max"]], exclude: ["ortho", "orthodont"] },
            individual_deductible: { scope: [["individual", "member"], ["deductible", "ded"]], exclude: ["family", "ortho", "orthodont"] },
            family_deductible: { scope: [["family"], ["deductible", "ded"]], exclude: ["ortho", "orthodont"] },
            ortho_deductible: { scope: [["ortho", "orthodont"], ["deductible", "ded"]], exclude: [] },
            ortho_maximum: { scope: [["ortho", "orthodont"], ["maximum", "max", "lifetime"]], exclude: ["deductible"] }
        };
        const labels = {
            annual_max: ["Yearly Maximum", "Annual Maximum"],
            individual_deductible: ["Individual Deductible"],
            family_deductible: ["Family Deductible"],
            ortho_deductible: ["Orthodontic Deductible", "Ortho Deductible"],
            ortho_maximum: ["Orthodontic Maximum", "Ortho Maximum", "Ortho Lifetime Maximum"]
        };
        const spec = specs[kind];
        const totalRaw = pickFinancialLeaf(leaves, spec, "total") || domValue(dom, labels[kind]);
        const usedRaw = pickFinancialLeaf(leaves, spec, "used") || domValue(dom, labels[kind].flatMap(label => [`${label} Paid to Date`, `${label} Used`, `${label} Met`]));
        const remainingRaw = pickFinancialLeaf(leaves, spec, "remaining") || domValue(dom, labels[kind].map(label => `${label} Remaining`));
        return {
            total: moneyValue(totalRaw),
            used: moneyValue(usedRaw),
            remaining: moneyValue(remainingRaw)
        };
    }

    function pickFinancialLeaf(leaves, spec, measure) {
        const measures = {
            total: ["total", "amount", "maximum", "max", "limit", "benefit"],
            used: ["used", "paid", "met", "applied", "todate", "accumulated"],
            remaining: ["remaining", "balance", "available", "remain"]
        };
        let best = null;
        for (const leaf of leaves) {
            if (!isFinancialValue(leaf.value)) continue;
            const path = leaf.normalizedPath;
            if (spec.exclude.some(term => path.includes(term))) continue;
            if (!spec.scope.every(group => group.some(term => path.includes(term)))) continue;

            let score = 20;
            const measureMatches = measures[measure].filter(term => path.includes(term)).length;
            if (measure === "total") {
                if (/(remaining|balance|available|used|paid|met|applied)/.test(path)) continue;
                score += measureMatches * 3;
            } else {
                if (!measureMatches) continue;
                score += measureMatches * 5;
            }
            if (leaf.path.length <= 7) score += 2;
            if (!best || score > best.score) best = { score, value: leaf.value };
        }
        return best?.value;
    }

    function deriveDeductibleApplicability(procedures, leaves, categoryHint) {
        const explicit = procedures.map(item => item.deductible).filter(value => value && value !== "N/A");
        if (explicit.some(value => /^yes$/i.test(value))) return "Yes";
        if (explicit.length && explicit.every(value => /^no$/i.test(value))) return "No";

        const value = mineValue(leaves, ["deductible", categoryHint], ["applies", "applicable", "waived"]);
        if (typeof value === "boolean") return value ? "Yes" : "No";
        if (/^(yes|true|applies)$/i.test(String(value || ""))) return "Yes";
        if (/^(no|false|waived|does not apply)$/i.test(String(value || ""))) return "No";
        return "N/A";
    }

    function deriveWaitingPeriod(procedures, waitExempted, supportText) {
        if (waitExempted === true) return "No — member is exempt";
        const values = uniqueStrings(procedures.flatMap(item => item.networks?.flatMap(network => network.waiting_periods || []) || []));
        if (values.length) return values.join(" | ");
        const sentence = sentenceContaining(supportText, /waiting\s+period/i);
        return sentence || "N/A";
    }

    function deriveWaitingAppliesTo(procedures) {
        const affected = procedures.filter(item => item.waiting_period !== "N/A").map(item => item.procedure_code);
        return affected.length ? affected.join(", ") : "N/A";
    }

    function benefitSupportingResponses(state) {
        return toArray(state?.supportingApiResponses).filter(item => {
            const endpoint = String(item?.endpoint || "").toLowerCase();
            if (!endpoint) return false;
            if (endpoint.includes("announcements") || endpoint.includes("usercontext") ||
                endpoint.includes("providerdetail") || endpoint.includes("case-message") ||
                endpoint.includes("feature-toggle")) return false;
            return endpoint.includes("/benefit/") || endpoint.includes("memberdetail") ||
                endpoint.includes("accumulator") || endpoint.includes("memberbenefits");
        });
    }

    function collectEligibilityNotes(supporting, procedures) {
        const notes = [];
        for (const item of supporting) {
            const leaves = flattenLeaves([item.response]);
            for (const leaf of leaves) {
                if (typeof leaf.value !== "string") continue;
                if (/eligib|note|remark|message|restriction|exclusion|limitation|warning/i.test(leaf.normalizedPath)) {
                    const value = cleanText(leaf.value);
                    if (value.length > 2 && value.length < 1200) notes.push(value);
                }
            }
        }
        for (const proc of procedures) notes.push(...toArray(proc.exclusions_and_limitations));
        return uniqueStrings(notes).slice(0, 150);
    }

    function buildCoveredServices(procedures) {
        const grouped = new Map();
        for (const proc of procedures) {
            const category = proc.category || "N/A";
            if (!grouped.has(category)) grouped.set(category, []);
            grouped.get(category).push(proc);
        }
        return [...grouped.entries()].map(([category, items]) => ({
            category,
            procedure_codes: items.map(item => item.procedure_code),
            network: "PPO Dentist",
            ppo_benefit_level: modalValue(items.map(item => item.benefit_level).filter(value => value !== "N/A")) || "N/A"
        }));
    }

    function buildProcedureFrequencySummary(procedures) {
        return procedures
            .filter(item => !isNA(item.frequency_limit) || toArray(item.history_dates).length > 0)
            .map(item => ({
                network: "PPO Dentist",
                procedure_code: item.procedure_code,
                procedure: item.description,
                age_limitation: valueOrNA(item.age_limit),
                limit: valueOrNA(item.frequency_limit),
                history_dates: toArray(item.history_dates)
            }));
    }

    function buildProcedureAgeLimitSummary(procedures) {
        return procedures
            .filter(item => !isNA(item.age_limit))
            .map(item => ({
                network: "PPO Dentist",
                procedure_code: item.procedure_code,
                procedure: item.description,
                age: item.age_limit
            }));
    }

    function listMissingRequestedFields(data) {
        const paths = {
            "Patient Name": data.patientName,
            "Patient DOB": data.patientDob,
            "Member ID": data.memberId,
            "Relation to Subscriber": data.relationship,
            "Subscriber Name": data.subscriberName,
            "Subscriber DOB": data.subscriberDob,
            SSN: data.ssn,
            "Group Name": data.groupName,
            "Group Number": data.groupNumber,
            "Fee Schedule": data.feeSchedule,
            "Insurance Address": data.insuranceAddress,
            "Insurance Phone": data.insurancePhone,
            "Provider Network Status": data.providerNetworkStatus,
            "Patient Effective Date": data.patientEffective,
            "Patient Term Date": data.patientTermDate,
            "Starting Month of Plan Year": data.planYearStart,
            "Payor ID": data.payorId,
            "Yearly Maximum": data.annualMax?.total,
            "Individual Deductible": data.indDed?.total,
            "Family Deductible": data.famDed?.total,
            "Orthodontic Deductible": data.orthoDed?.total,
            "Orthodontic Maximum": data.orthoMax?.total
        };
        return Object.entries(paths).filter(([, value]) => isNA(value)).map(([label]) => label);
    }

    // =====================================================================
    // Parsing and normalization utilities
    // =====================================================================

    function parseRequestBody(text) {
        if (!text || typeof text !== "string") return null;
        const json = safeJsonParse(text);
        if (json !== null) return json;
        try {
            return Object.fromEntries(new URLSearchParams(text).entries());
        } catch (_) {
            return null;
        }
    }

    function extractCodes(value) {
        return uniqueStrings(String(value || "").toUpperCase().match(/D\d{4}/g) || []);
    }

    function safeReplayHeaders(headers) {
        const source = headersToObject(headers);
        const allowed = ["authorization", "accept", "content-type", "x-requested-with", "x-dtpc"];
        const output = {};
        for (const key of allowed) {
            if (source[key]) output[key] = source[key];
        }
        return output;
    }

    function mergeHeaders(...inputs) {
        const result = {};
        for (const input of inputs) Object.assign(result, headersToObject(input));
        return result;
    }

    function headersToObject(input) {
        const output = {};
        if (!input) return output;
        try {
            if (input instanceof Headers) {
                input.forEach((value, key) => { output[key.toLowerCase()] = value; });
            } else if (Array.isArray(input)) {
                for (const [key, value] of input) output[String(key).toLowerCase()] = String(value);
            } else {
                for (const [key, value] of Object.entries(input)) output[String(key).toLowerCase()] = String(value);
            }
        } catch (_) { /* ignored */ }
        return output;
    }

    function isToolkitApiUrl(url) {
        try {
            const parsed = new URL(url, location.href);
            return parsed.origin === TARGET_ORIGIN && parsed.pathname.startsWith("/api/dot-gateway/");
        } catch (_) {
            return false;
        }
    }

    function looksLikeRelevantEndpoint(url) {
        return String(url).includes("/api/dot-gateway/");
    }

    function isRelevantJson(value) {
        return value && (Array.isArray(value) || typeof value === "object");
    }

    function preferredNetworkName(procedures) {
        const values = procedures.flatMap(item => item.networks?.map(network => network.network) || []);
        return values.find(value => /^PPO Dentist$/i.test(cleanText(value))) || "PPO Dentist";
    }

    function choosePreferredNetwork(records) {
        return records.find(item => /^PPO Dentist$/i.test(cleanText(item.network))) || null;
    }

    function isExactPpoBucket(bucket) {
        const networks = uniqueStrings(toArray(bucket?.networks).map(cleanText));
        return networks.some(name => /^PPO Dentist$/i.test(name));
    }

    function normalizeCode(value) {
        return String(value || "").toUpperCase().match(/D\d{4}/)?.[0] || "";
    }

    function normalizePercent(value) {
        if (value === null || value === undefined || value === "") return "N/A";
        const text = String(value).trim();
        return text.endsWith("%") ? text : `${text}%`;
    }

    function parseFrequency(limitations) {
        const values = uniqueStrings(toArray(limitations).map(cleanText).filter(Boolean));
        const frequency = values.filter(text => /\b(per|every|calendar|rolling|consecutive|once|twice|times?|months?|years?|lifetime|frequency|payable)\b/i.test(text));
        return (frequency.length ? frequency : values).join(" | ") || "N/A";
    }

    function canonicalFrequency(value) {
        const text = String(value || "").trim();
        if (!text || /^N\/?A$/i.test(text)) return "";
        return text.toUpperCase()
            .replace(/D\d{4}/g, "")
            .replace(/[^A-Z0-9]+/g, " ")
            .replace(/\b(PROCEDURE|SERVICE|TREATMENT|ORAL|EXAMINATION|EXAMINATIONS)\b/g, "")
            .replace(/\s+/g, " ")
            .trim();
    }

    function parseAgeLimit(text) {
        const source = String(text || "");
        const patterns = [
            /ages?\s*(\d{1,2})\s*(?:-|–|to|through)\s*(\d{1,2})/i,
            /(?:from\s+)?age\s*(\d{1,2})\s*(?:-|–|to|through)\s*(\d{1,2})/i,
            /(?:through|up\s+to|under|before)\s+age\s*(\d{1,2})/i,
            /age\s*(\d{1,2})\s*(?:and\s+under|or\s+younger|and\s+younger|or\s+less)/i,
            /age\s*(\d{1,2})\s*(?:and\s+over|or\s+older|and\s+older|\+)/i,
            /(\d{1,2})\s*(?:years?\s+of\s+age)?\s*(?:and\s+under|or\s+younger)/i
        ];
        for (let i = 0; i < patterns.length; i++) {
            const match = source.match(patterns[i]);
            if (!match) continue;
            if (match[2]) return `${match[1]}-${match[2]}`;
            if (i === 4) return `${match[1]}+`;
            return `0-${match[1]}`;
        }
        return "N/A";
    }

    function parseDeductible(text) {
        const source = String(text || "");
        if (/deductible\s+(?:does\s+not|doesn't|not)\s+apply|deductible\s+waived|no\s+deductible/i.test(source)) return "No";
        if (/deductible\s+appl(?:y|ies|icable)|subject\s+to\s+(?:the\s+)?deductible/i.test(source)) return "Yes";
        return "N/A";
    }

    function parseQuads(text) {
        const source = String(text || "");
        let match = source.match(/\b([1-4])\s+(?:quadrants?|quads?)\b/i);
        if (match) return match[1];
        match = source.match(/\b(?:up\s+to|maximum\s+of|no\s+more\s+than)\s+([1-4])\s+(?:quadrants?|quads?)\b/i);
        if (match) return match[1];
        if (/four\s+(?:quadrants?|quads?)/i.test(source)) return "4";
        if (/three\s+(?:quadrants?|quads?)/i.test(source)) return "3";
        if (/two\s+(?:quadrants?|quads?)/i.test(source)) return "2";
        if (/one\s+(?:quadrant|quad)/i.test(source)) return "1";
        return "";
    }

    function collectDates(value) {
        const dates = [];
        const visit = item => {
            if (item === null || item === undefined) return;
            if (typeof item === "string") {
                const matches = item.match(/\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{1,2}-\d{1,2}-\d{4})\b/g) || [];
                dates.push(...matches);
            } else if (Array.isArray(item)) item.forEach(visit);
            else if (typeof item === "object") Object.values(item).forEach(visit);
        };
        visit(value);
        return uniqueStrings(dates);
    }

    function latestDate(values) {
        let best = null;
        for (const value of toArray(values)) {
            const parsed = parseDateLoose(value);
            if (parsed && (!best || parsed.time > best.time)) best = { time: parsed.time, value };
        }
        return best?.value || "";
    }

    function parseDateLoose(value) {
        const text = String(value || "").trim();
        let match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (match) return { time: Date.UTC(+match[1], +match[2] - 1, +match[3]) };
        match = text.match(/^(\d{1,2})[\/-](\d{1,2})[\/-](\d{2,4})$/);
        if (match) {
            let year = +match[3];
            if (year < 100) year += 2000;
            return { time: Date.UTC(year, +match[1] - 1, +match[2]) };
        }
        return null;
    }

    function sentenceContaining(text, primary, secondary = null) {
        const sentences = String(text || "").split(/(?<=[.!?])\s+|\n+/).map(cleanText).filter(Boolean);
        return sentences.find(sentence => primary.test(sentence) && (!secondary || secondary.test(sentence))) || "";
    }

    function findDependentAge(text) {
        const sentence = sentenceContaining(text, /dependent/i, /age|coverage\s+ends|eligible/i);
        if (!sentence) return "";
        return parseAgeLimit(sentence) !== "N/A" ? parseAgeLimit(sentence) : sentence;
    }

    function procedureText(proc) {
        if (!proc) return "";
        return uniqueStrings([
            proc.frequency_limit,
            proc.waiting_period,
            ...toArray(proc.exclusions_and_limitations),
            ...toArray(proc.networks).flatMap(item => [
                item.frequency_limit,
                ...toArray(item.limitations),
                ...toArray(item.waiting_periods)
            ])
        ]).join(" ");
    }

    function flattenLeaves(roots) {
        const output = [];
        const visit = (value, path, depth) => {
            if (depth > 18 || value === null || value === undefined) return;
            if (["string", "number", "boolean"].includes(typeof value)) {
                output.push({ path, normalizedPath: normalizePath(path), value });
                return;
            }
            if (Array.isArray(value)) {
                value.slice(0, 1000).forEach((item, index) => visit(item, [...path, String(index)], depth + 1));
                return;
            }
            if (typeof value === "object") {
                for (const [key, item] of Object.entries(value)) visit(item, [...path, key], depth + 1);
            }
        };
        toArray(roots).forEach((root, index) => visit(root, [String(index)], 0));
        return output;
    }

    function normalizePath(path) {
        return path.join(".").toLowerCase().replace(/[^a-z0-9]+/g, "");
    }

    function mineValue(leaves, requiredTerms, preferredTerms = []) {
        const required = toArray(requiredTerms).map(term => String(term).toLowerCase().replace(/[^a-z0-9]/g, ""));
        const preferred = toArray(preferredTerms).map(term => String(term).toLowerCase().replace(/[^a-z0-9]/g, ""));
        let best = null;
        for (const leaf of leaves) {
            if (leaf.value === null || leaf.value === undefined || leaf.value === "") continue;
            if (!required.every(term => leaf.normalizedPath.includes(term))) continue;
            let score = 10 + preferred.filter(term => leaf.normalizedPath.includes(term)).length * 4;
            if (typeof leaf.value === "string" && leaf.value.length < 300) score += 2;
            if (!best || score > best.score) best = { score, value: leaf.value };
        }
        return best?.value || "";
    }

    function mineObject(leaves, requiredTerms) {
        const value = mineValue(leaves, requiredTerms, []);
        return value && typeof value === "object" ? value : "";
    }

    function collectStrings(value) {
        const output = [];
        const visit = (item, depth) => {
            if (depth > 16 || item === null || item === undefined) return;
            if (typeof item === "string") {
                const text = cleanText(item);
                if (text) output.push(text);
            } else if (Array.isArray(item)) item.slice(0, 1500).forEach(x => visit(x, depth + 1));
            else if (typeof item === "object") Object.values(item).forEach(x => visit(x, depth + 1));
        };
        visit(value, 0);
        return output;
    }

    function buildDomLabelMap() {
        const map = new Map();
        const add = (label, value) => {
            const cleanLabel = cleanText(label).replace(/:$/, "");
            const cleanValue = cleanText(value);
            if (!cleanLabel || !cleanValue || cleanLabel.length > 100 || cleanValue === cleanLabel) return;
            const key = cleanLabel.toLowerCase();
            if (!map.has(key) || map.get(key).length < cleanValue.length) map.set(key, cleanValue);
        };

        document.querySelectorAll("tr").forEach(row => {
            const cells = [...row.querySelectorAll(":scope > th, :scope > td")];
            if (cells.length >= 2) add(cells[0].innerText, cells.slice(1).map(cell => cell.innerText).join(" "));
        });
        document.querySelectorAll("dt").forEach(dt => {
            const dd = dt.nextElementSibling;
            if (dd?.tagName?.toLowerCase() === "dd") add(dt.innerText, dd.innerText);
        });
        document.querySelectorAll("label, [class*='label' i]").forEach(label => {
            const sibling = label.nextElementSibling || label.parentElement?.nextElementSibling;
            if (sibling) add(label.innerText, sibling.innerText);
        });
        return map;
    }

    function domValue(map, labels) {
        for (const label of toArray(labels)) {
            const key = cleanText(label).replace(/:$/, "").toLowerCase();
            if (map.has(key)) return map.get(key);
            for (const [candidate, value] of map.entries()) {
                if (candidate === key || candidate.startsWith(`${key} `) || candidate.includes(key)) return value;
            }
        }
        return "";
    }

    function strictSsnFromText(text) {
        const match = String(text || "").match(/(?:SSN|Social\s+Security\s+Number)\s*:?\s*(\*{0,5}\d{3,4}|\d{3}-\d{2}-\d{4}|\d{9})\b/i);
        return match?.[1] || "";
    }

    function formatAddress(value) {
        if (!value) return "";
        if (typeof value === "string") return cleanText(value);
        if (typeof value !== "object") return String(value);
        return uniqueStrings([
            value.address1, value.addressLine1, value.line1, value.street,
            value.address2, value.addressLine2, value.line2,
            value.city, value.state, value.zip, value.zipCode, value.postalCode
        ]).join(", ");
    }

    function moneyValue(value) {
        if (value === null || value === undefined || value === "") return "N/A";
        if (typeof value === "number" && Number.isFinite(value)) {
            return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        }
        const text = cleanText(String(value));
        if (!text || /^N\/?A$/i.test(text)) return "N/A";
        const match = text.match(/-?\$?\s*[\d,]+(?:\.\d{1,2})?/);
        if (!match) return text;
        const number = Number(match[0].replace(/[$,\s]/g, ""));
        if (!Number.isFinite(number)) return text;
        return `$${number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    function isFinancialValue(value) {
        if (typeof value === "number") return Number.isFinite(value);
        return typeof value === "string" && /\d/.test(value) && value.length < 100;
    }

    function sanitizeNetworkEvidenceForOutput(value, depth = 0) {
        if (depth > 25) return "[depth limit]";
        if (value === null || value === undefined) return value;
        if (typeof value === "string") return value.length > 30000 ? `${value.slice(0, 30000)}…[truncated]` : value;
        if (["number", "boolean"].includes(typeof value)) return value;
        if (Array.isArray(value)) return value.slice(0, 3000).map(item => sanitizeNetworkEvidenceForOutput(item, depth + 1));
        if (typeof value === "object") {
            const output = {};
            for (const [key, item] of Object.entries(value)) {
                if (/authorization|access.?token|refresh.?token|id.?token|cookie|password|secret|bearer/i.test(key)) continue;
                output[key] = sanitizeNetworkEvidenceForOutput(item, depth + 1);
            }
            return output;
        }
        return String(value);
    }

    function sanitizeForOutput(value, depth = 0) {
        if (depth > 25) return "[depth limit]";
        if (value === null || value === undefined) return value;
        if (typeof value === "string") return value.length > 30000 ? `${value.slice(0, 30000)}…[truncated]` : value;
        if (["number", "boolean"].includes(typeof value)) return value;
        if (Array.isArray(value)) return value.slice(0, 3000).map(item => sanitizeForOutput(item, depth + 1));
        if (typeof value === "object") {
            const output = {};
            for (const [key, item] of Object.entries(value)) {
                if (/authorization|access.?token|refresh.?token|id.?token|cookie|password|secret|bearer/i.test(key)) continue;
                output[key] = sanitizeForOutput(item, depth + 1);
            }
            return output;
        }
        return String(value);
    }

    function persistNonSecretState(state) {
        try {
            const payload = {
                personKey: state.personKey || null,
                memberSearchCapturedAt: state.memberSearchCapturedAt || null,
                memberSearchRequest: sanitizeForOutput(state.memberSearchRequest),
                memberSearchResponse: sanitizeForOutput(state.memberSearchResponse),
                memberBenefitsRequest: sanitizeForOutput(state.memberBenefitsRequest),
                memberBenefitsResponse: sanitizeForOutput(state.memberBenefitsResponse),
                routineProceduresRequest: sanitizeForOutput(state.routineProceduresRequest),
                routineProceduresResponse: sanitizeForOutput(state.routineProceduresResponse),
                clientSearchRequest: sanitizeForOutput(state.clientSearchRequest),
                clientSearchResponse: sanitizeForOutput(state.clientSearchResponse),
                procedureTemplate: sanitizeForOutput(state.procedureTemplate),
                procedureTemplateSignature: state.procedureTemplateSignature || null,
                coreTransactions: sanitizeForOutput(state.coreTransactions || {}),
                capturedAt: new Date().toISOString()
            };
            sessionStorage.setItem("delta_toolkit_capture_v2", JSON.stringify(payload));
        } catch (_) { /* storage may be unavailable */ }
    }

    function hydrateNonSecretState(state) {
        if (state.hydrated) return;
        state.hydrated = true;
        try {
            const saved = safeJsonParse(
                sessionStorage.getItem("delta_toolkit_capture_v2") ||
                sessionStorage.getItem("delta_toolkit_capture_v1")
            );
            if (!saved) return;
            state.personKey = saved.personKey || saved.patientKey || null;
            state.memberSearchCapturedAt = saved.memberSearchCapturedAt || null;
            state.memberSearchRequest = saved.memberSearchRequest || null;
            state.memberSearchResponse = saved.memberSearchResponse && typeof saved.memberSearchResponse === "object"
                ? saved.memberSearchResponse
                : null;
            state.memberBenefitsRequest = saved.memberBenefitsRequest || null;
            state.memberBenefitsResponse = saved.memberBenefitsResponse || null;
            state.routineProceduresRequest = saved.routineProceduresRequest || null;
            state.routineProceduresResponse = saved.routineProceduresResponse || null;
            state.clientSearchRequest = saved.clientSearchRequest || null;
            state.clientSearchResponse = saved.clientSearchResponse || null;
            state.procedureTemplate = saved.procedureTemplate || null;
            state.procedureTemplateSignature = saved.procedureTemplateSignature || procedureTemplateSignature(state.procedureTemplate);
            state.coreTransactions = saved.coreTransactions && typeof saved.coreTransactions === "object" ? saved.coreTransactions : {};
            // Authorization is intentionally never persisted. Normal authenticated
            // page traffic refreshes it in memory after navigation/reload.
            refreshProcedureTemplate(state);
        } catch (_) { /* ignored */ }
    }

    function postPageMessage(type, payload) {
        window.postMessage({ source: PAGE_SOURCE, type, ...payload }, window.location.origin);
    }

    function setStatus(state, text, mode, extra = {}) {
        if (state.statusEl) {
            state.statusEl.textContent = text;
            state.statusEl.style.color = mode === "error" ? "#b91c1c" : mode === "ready" ? "#166534" : "#475569";
        }
        postPageMessage("STATUS", { status: text, mode, extra });
        console.info(`Delta Toolkit: ${text}`);
    }

    function setBusy(state, busy) {
        if (state.buttonEl) {
            state.buttonEl.disabled = busy;
            state.buttonEl.style.opacity = busy ? ".65" : "1";
            state.buttonEl.style.cursor = busy ? "wait" : "pointer";
        }
    }

    function validateProcedureIntegrity(procedures) {
        if (!Array.isArray(procedures) || procedures.length !== PROCEDURE_CODES.length) {
            throw new Error(`Expected ${PROCEDURE_CODES.length} procedure records, received ${procedures?.length || 0}.`);
        }
        for (let index = 0; index < PROCEDURE_CODES.length; index++) {
            if (procedures[index]?.procedure_code !== PROCEDURE_CODES[index]) {
                throw new Error(`Procedure order mismatch at ${index}: expected ${PROCEDURE_CODES[index]}.`);
            }
        }
        if (new Set(procedures.map(item => item.procedure_code)).size !== PROCEDURE_CODES.length) {
            throw new Error("Duplicate procedure codes found in final output.");
        }
        const failedCodes = procedures.filter(item => item?.error).map(item => item.procedure_code);
        const successful = procedures.length - failedCodes.length;
        // All API lookups may fail while member/plan or faxback evidence remains useful.
        // Return a fully accounted, partial result rather than hiding those source outcomes.
        return { successful, failedCodes };
    }



    // Export one client-independent JSON: patient/plan identity, plan-level provisions and the
    // established Karyn-style benefit sections. API transport diagnostics, run metadata and
    // workbook client grouping stay in the internal result only.
    function buildWorkbookOnlyOutput(data, requirementsSpec = null) {
        const spec = requirementsSpec ||
            (typeof TOOLKIT_REQUIREMENTS_SPEC !== "undefined" ? TOOLKIT_REQUIREMENTS_SPEC : null) ||
            {};
        const rawRequirements = Array.isArray(spec.requirements)
            ? spec.requirements
            : toArray(data?.requirements_assessment?.fields);
        const isValueRow = item => item && item.is_marked_requirement === false &&
            String(item.description ?? "").trim() !== "" &&
            !/leave\s+it\s+as\s+blank/i.test(String(item.remarks_comments ?? "")) &&
            (toArray(item.codes).length === 0 || String(item.remarks_comments ?? "").trim() !== "");
        const activeRequirements = rawRequirements.filter(item =>
            item && (((item.is_requirement ?? item.is_marked_requirement) !== false &&
                Array.isArray(item.required_fields) && item.required_fields.length > 0) || isValueRow(item))
        );
        const normalizeCode = value => {
            const match = String(value ?? "").toUpperCase().match(/D\d{4}/);
            return match ? match[0] : null;
        };
        const requiredCodes = new Set();
        for (const requirement of activeRequirements) {
            for (const rawCode of toArray(requirement.codes)) {
                const code = normalizeCode(rawCode);
                if (code) requiredCodes.add(code);
            }
        }
        for (const rawCode of toArray(spec?.code_universe?.supplemental_codes)) {
            const code = normalizeCode(rawCode);
            if (code) requiredCodes.add(code);
        }

        // The legacy output schema is consumed by the Star/comparator code. Keep its root keys
        // and section layout, while dropping duplicate projections (patient_and_plan/plan_provisions)
        // and nested provenance labels. The root-level source field remains as legacy metadata.
        const stripSourceFields = value => {
            if (Array.isArray(value)) return value.map(stripSourceFields);
            if (!value || typeof value !== "object") return value;
            const result = {};
            for (const [key, child] of Object.entries(value)) {
                if (/^(?:source|canonical_source|source_values)$/i.test(key)) continue;
                result[key] = stripSourceFields(child);
            }
            return result;
        };
        const mergeMissing = (existing, incoming) => {
            if (existing === null || existing === undefined || existing === "") return incoming;
            if (incoming === null || incoming === undefined || incoming === "") return existing;
            if (Array.isArray(existing) && Array.isArray(incoming)) {
                const result = [...existing];
                const seen = new Set(result.map(item => JSON.stringify(item)));
                for (const item of incoming) {
                    const key = JSON.stringify(item);
                    if (!seen.has(key)) { seen.add(key); result.push(item); }
                }
                return result;
            }
            if (existing && incoming && typeof existing === "object" && typeof incoming === "object" &&
                !Array.isArray(existing) && !Array.isArray(incoming)) {
                const result = { ...existing };
                for (const [key, value] of Object.entries(incoming)) {
                    result[key] = Object.prototype.hasOwnProperty.call(result, key)
                        ? mergeMissing(result[key], value)
                        : value;
                }
                return result;
            }
            // Keep the first value on conflicts: extraction has already resolved source precedence.
            return existing;
        };
        const filterCodeRows = (rows, keepUncoded = false) => {
            const byCode = new Map();
            const uncoded = [];
            for (const original of toArray(rows)) {
                const code = normalizeCode(original?.procedureCode ?? original?.procedure_code ?? original?.code);
                if (!code) {
                    if (keepUncoded && original && typeof original === "object") uncoded.push(stripSourceFields(original));
                    continue;
                }
                if (requiredCodes.size && !requiredCodes.has(code)) continue;
                const row = stripSourceFields(original);
                if (byCode.has(code)) byCode.set(code, mergeMissing(byCode.get(code), row));
                else byCode.set(code, row);
            }
            return [...byCode.values(), ...uncoded];
        };
        // Export-only trims for procedure_code_search.results rows: no per-row httpStatus,
        // result_source or lookup_status, and no "level" number on procedurePath nodes.
        const stripProcedureRowDiagnostics = row => {
            if (!row || typeof row !== "object") return row;
            const trimmed = { ...row };
            delete trimmed.httpStatus;
            delete trimmed.result_source;
            delete trimmed.lookup_status;
            delete trimmed.api_status;
            delete trimmed.utilization_history_status;
            trimmed.status = exportCoverageStatus(row);
            const withoutLevel = node => {
                if (!node || typeof node !== "object" || Array.isArray(node)) return node;
                const { level, ...rest } = node;
                return rest;
            };
            if (Array.isArray(trimmed.procedurePath)) trimmed.procedurePath = trimmed.procedurePath.map(withoutLevel);
            if (Array.isArray(trimmed.limitations)) trimmed.limitations = trimmed.limitations.map(withoutLevel);
            return trimmed;
        };
        const exportCoverageStatus = row => {
            if (row?.failure_kind === "NOT_IN_PORTAL_CODE_LIST" && (row?.percentCovered === null || row?.percentCovered === undefined)) return "Not In Portal Code List";
            const percent = cleanText(String(row?.percentCovered ?? ""));
            if (!percent) return row?.error ? "Lookup Failed" : "Not Available";
            if (/not\s+covered/i.test(percent) || /^0+(?:\.0+)?%?$/.test(percent)) return "Not Covered";
            if (/optional/i.test(percent)) return "Optional";
            return "Covered";
        };
        const sectionBase = (key, allowed) => {
            const input = data?.[key];
            if (!input || typeof input !== "object") return null;
            const output = {};
            for (const field of allowed) {
                if (input[field] !== undefined) output[field] = stripSourceFields(input[field]);
            }
            return output;
        };

        const output = {
            source: data?.source || "Delta Dental Office Toolkit",
            portal: data?.portal || "www.dentalofficetoolkit.com",
            page: data?.page || "Member Details & Benefits",
            captured_at: data?.captured_at || new Date().toISOString()
        };
        const selectedNetwork = data?.selected_network ?? data?.networks?.selected ??
            data?.routine_procedures?.network ?? data?.coverages?.network;
        if (selectedNetwork) output.selected_network = selectedNetwork;

        const memberDetails = sectionBase("member_details", ["section_title", "memberAlternateId", "columns", "members", "selectedMember"]);
        if (memberDetails) output.member_details = memberDetails;

        const networks = sectionBase("networks", ["section_title", "selected", "available_in_output"]);
        if (networks) output.networks = networks;

        if (data?.claim_reminders && typeof data.claim_reminders === "object") {
            output.claim_reminders = sectionBase("claim_reminders", ["section_title", "messages"]);
        }

        const routine = sectionBase("routine_procedures", ["section_title", "network", "notes"]);
        if (routine) {
            routine.rows = filterCodeRows(data?.routine_procedures?.rows, true);
            output.routine_procedures = routine;
        }

        const coverage = sectionBase("coverages", ["section_title", "network", "notes", "coverage_rows"]);
        if (coverage) {
            const search = data?.coverages?.procedure_code_search;
            if (search && typeof search === "object") {
                const projectedSearch = stripSourceFields(search);
                // Export trims: no endpoint, no count / successful_count.
                delete projectedSearch.endpoint;
                delete projectedSearch.count;
                delete projectedSearch.successful_count;
                projectedSearch.results = filterCodeRows(search.results).map(stripProcedureRowDiagnostics);
                // codes_requested and failed_codes are each exported as ONE line, comma-separated.
                const toCodeLine = list => list
                    .map(normalizeCode)
                    .filter(code => code && (!requiredCodes.size || requiredCodes.has(code)))
                    .join(", ");
                if (Array.isArray(search.codes_requested)) projectedSearch.codes_requested = toCodeLine(search.codes_requested);
                if (Array.isArray(search.failed_codes)) projectedSearch.failed_codes = toCodeLine(search.failed_codes);
                if (Array.isArray(search.codes_not_in_portal)) projectedSearch.codes_not_in_portal = toCodeLine(search.codes_not_in_portal);
                coverage.procedure_code_search = projectedSearch;
            }
            output.coverages = coverage;
        }

        const limitations = sectionBase("exclusions_and_limitations", ["section_title", "network", "notes", "records"]);
        if (limitations) output.exclusions_and_limitations = limitations;

        const maxima = sectionBase("maximums_and_deductibles", ["section_title", "network", "notes", "accumulationPeriodType"]);
        if (maxima) {
            maxima.rows = deduplicateAccumulatorRows(stripSourceFields(data?.maximums_and_deductibles?.rows));
            output.maximums_and_deductibles = maxima;
        }

        const ortho = sectionBase("ortho_information", [
            "section_title", "network", "ortho_age_limit_under", "ortho_age_limit_note",
            "crowns_bridges_dentures_payment_note", "orthoAgeLimitConfig", "orthoPaymentSchedule", "notes"
        ]);
        if (ortho) output.ortho_information = ortho;

        const moreSource = data?.more_information;
        if (moreSource && typeof moreSource === "object") {
            const more = { section_title: moreSource.section_title || "More Information" };
            for (const key of ["client_benefit_information", "cob_information", "claim_and_inquiry_mailing_addresses", "age_limitations"]) {
                if (moreSource[key] !== undefined) more[key] = stripSourceFields(moreSource[key]);
            }
            output.more_information = more;
        }

        const statistics = sectionBase("crawl_statistics", ["extraction_scope", "status"]);
        if (statistics) {
            if (typeof statistics.extraction_scope === "string") {
                statistics.extraction_scope = statistics.extraction_scope.replace(/\s*plus selected-member faxback PDF/i, "").trim();
            }
            output.crawl_statistics = statistics;
        }

        return output;
    }

    function toolkitDownloadFilename(data) {
        const rawName = cleanText(
            data?.patient_and_plan?.patient?.name ||
            data?.member_details?.selectedMember?.patientName ||
            data?.member_details?.selectedMember?.name ||
            data?.run_context?.portal_context?.member_name ||
            "Patient"
        );
        const displayName = rawName === rawName.toUpperCase() || rawName === rawName.toLowerCase()
            ? rawName.toLowerCase().replace(/(^|\s)([a-z])/g, (_, prefix, letter) => prefix + letter.toUpperCase())
            : rawName;
        const nameSlug = displayName.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "Patient";
        const timestamp = data?.captured_at ? new Date(data.captured_at) : new Date();
        const date = Number.isNaN(timestamp.getTime()) ? new Date().toISOString().slice(0, 10) : timestamp.toISOString().slice(0, 10);
        return `delta_toolkit_${nameSlug}_${date}.json`;
    }

    function downloadJson(data) {
        if (!data || typeof data !== "object") throw new Error("Cannot download an empty extraction result.");
        const cleanData = buildWorkbookOnlyOutput(data);
        const filename = toolkitDownloadFilename(data);
        const blob = new Blob([JSON.stringify(cleanData, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        anchor.style.display = "none";
        (document.body || document.documentElement).appendChild(anchor);
        anchor.click();
        setTimeout(() => {
            anchor.remove();
            URL.revokeObjectURL(url);
        }, 1500);
    }

    function modalValue(values) {
        const counts = new Map();
        for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
        return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || "";
    }

    function joinName(first, last) {
        return cleanText([first, last].filter(Boolean).join(" ")) || "N/A";
    }

    function firstMeaningful(values) {
        for (const value of toArray(values)) {
            if (value === null || value === undefined) continue;
            if (typeof value === "object") {
                const formatted = formatAddress(value);
                if (formatted) return formatted;
                continue;
            }
            const text = cleanText(String(value));
            if (text && !/^N\/?A$/i.test(text) && text !== "null" && text !== "undefined") return text;
        }
        return "";
    }

    function valueOrNA(value) {
        return firstMeaningful([value]) || "N/A";
    }

    function isNA(value) {
        if (value && typeof value === "object" && "total" in value) return isNA(value.total);
        const text = String(value ?? "").trim();
        return !text || /^N\/?A$/i.test(text) || text === "-";
    }

    function cleanText(value) {
        return String(value ?? "").replace(/\s+/g, " ").trim();
    }

    function uniqueStrings(values) {
        const output = [];
        const seen = new Set();
        for (const value of toArray(values)) {
            if (value === null || value === undefined) continue;
            const text = typeof value === "string" ? cleanText(value) : safeStringify(value);
            if (!text || text === "null" || text === "[]" || text === "{}" || /^N\/?A$/i.test(text)) continue;
            const key = text.toLowerCase();
            if (!seen.has(key)) {
                seen.add(key);
                output.push(text);
            }
        }
        return output;
    }

    function toArray(value) {
        if (value === null || value === undefined) return [];
        return Array.isArray(value) ? value : [value];
    }

    function toStringList(value) {
        return toArray(value).flatMap(item => {
            if (item === null || item === undefined) return [];
            if (typeof item === "string") return [item];
            if (typeof item === "object") return collectStrings(item);
            return [String(item)];
        });
    }

    function safeJsonParse(text) {
        if (text === null || text === undefined || text === "") return null;
        if (typeof text !== "string") return text;
        try { return JSON.parse(text); } catch (_) { return null; }
    }

    function safeStringify(value) {
        try { return JSON.stringify(value); } catch (_) { return String(value); }
    }

    function makeId() {
        return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
})();
