/*
 * content_dd_toolkit.js
 * Delta Dental Office Toolkit benefit extractor - native-first PPO revision
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

    const CATEGORY_CODES = Object.freeze({
        EXAMS: ["D0180", "D0120", "D0140", "D0150"],
        DIAGNOSTIC: ["D0210", "D0220", "D0230", "D0240", "D0274", "D0330"],
        PREVENTATIVE: ["D1510", "D1110", "D1120", "D1206", "D1351"],
        "BASIC RESTORATIVE": ["D2140", "D2331", "D2620"],
        "MAJOR RESTORATIVE": ["D2740", "D2950", "D2991"],
        ENDODONTICS: ["D3347", "D3310", "D3330"],
        PERIODONTICS: ["D4260", "D4341", "D4355", "D4381", "D4910"],
        "REMOVABLE PROSTHO": ["D5860", "D5110", "D5740", "D5982"],
        IMPLANT: ["D6194", "D6010", "D6056", "D6065"],
        "FIXED PROSTHO": ["D6245"],
        "ORAL SURGERY": ["D7259", "D7140", "D7240"],
        ORTHODONTICS: ["D8010", "D8080", "D8090"],
        ADJUNCTIVE: ["D9430", "D9110", "D9222", "D9239", "D9310", "D9944"]
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
        D1510: "Space Maintainer",
        D1110: "Prophylaxis",
        D1120: "Prophylaxis Child",
        D1206: "Fluoride",
        D1351: "Sealants",
        D2140: "Amalgam",
        D2331: "Composite Filling",
        D2620: "Restorative Onlay/Inlay",
        D2740: "Porcelain Crown",
        D2950: "Build up",
        D2991: "D2991",
        D3347: "Retreatment of previous root canal therapy - premolar",
        D3310: "Endo",
        D3330: "Root Canal",
        D4260: "Osseous Surgery",
        D4341: "Scaling & Root Planning",
        D4355: "Full Mouth Debridement",
        D4381: "Arestin",
        D4910: "Perio Maintenance",
        D5860: "Over Denture Complete",
        D5110: "Dentures",
        D5740: "Reline maxillary partial denture (direct)",
        D5982: "Surgical stent",
        D6194: "Implant",
        D6010: "Implant Body",
        D6056: "Implant Abutment",
        D6065: "Implant Crown",
        D6245: "Pontic - porcelain/ceramic",
        D7259: "Nerve dissection",
        D7140: "Simple Extraction",
        D7240: "Impacted Extraction",
        D8010: "Ortho",
        D8080: "Ortho",
        D8090: "Ortho",
        D9430: "Office visit for observation",
        D9110: "Palliative",
        D9222: "Gen Anesthesia",
        D9239: "sedation/analgesia",
        D9310: "Consult",
        D9944: "Occlusal Guard"
    });

    const PROCEDURE_CODES = Object.freeze(Object.values(CATEGORY_CODES).flat());
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
        if (globalThis.__DELTA_TOOLKIT_ISOLATED_INSTALLED__) return;
        globalThis.__DELTA_TOOLKIT_ISOLATED_INSTALLED__ = true;

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
                    const finalText = failed
                        ? `[!] Partial — ${successful}/${requested} codes succeeded; ${failed} failed. JSON downloaded with failure details.`
                        : `[+] Done — ${successful || requested}/${requested} codes extracted. JSON downloaded.`;
                    sendPopupStatus(finalText, failed ? "warning" : "ready", { state: failed ? "PARTIAL" : "COMPLETE" });
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
            activeRun: null,
            statusEl: null,
            buttonEl: null,
            hydrated: false
        };

        hydrateNonSecretState(state);
        interceptFetch(state, nativeFetch);
        interceptXHR(state, NativeXHR);
        installPageMessageBridge(state, nativeFetch);
        // installFloatingUiWhenReady removed to avoid conflicting separate popup

        console.info("Delta Toolkit extractor installed. Open the member-benefits page and wait for authenticated plan data to finish loading.");
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

                if (isToolkitApiUrl(capture.url)) {
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
                persistNonSecretState(state);
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
                        ? `Partial — ${stats.successful_codes}/${stats.requested_codes} codes succeeded. JSON downloaded.`
                        : `Done — ${stats.successful_codes || PROCEDURE_CODES.length}/${stats.requested_codes || PROCEDURE_CODES.length} codes extracted. JSON downloaded.`,
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
                    : `Last crawl complete: ${stats.successful_codes || PROCEDURE_CODES.length}/${stats.requested_codes || PROCEDURE_CODES.length} codes succeeded.`
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

    async function startCrawl(state, nativeFetch, requestId) {
        if (state.activeRun && !state.activeRun.done) {
            state.activeRun.cancelled = true;
        }

        const run = {
            id: makeId(), requestId, cancelled: false, done: false,
            acknowledged: false, startedAt: Date.now(), resultData: null
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
            const rawByCode = await fetchAllProcedures(state, nativeFetch, run);
            if (run.cancelled) throw new Error("This extraction was superseded by a newer run or member selection.");

            setStatus(state, "Organizing Member Details & Benefits page sections and procedure details…", "working", { state: "RUNNING" });
            const data = buildFinalOutput(state, rawByCode, run);
            const integrity = validateProcedureIntegrity(
                data?.coverages?.procedure_code_search?.results?.map(item => ({
                    procedure_code: item?.procedureCode,
                    error: item?.error
                }))
            );
            data.crawl_statistics.successful_codes = integrity.successful;
            data.crawl_statistics.failed_codes = integrity.failedCodes;
            data.crawl_statistics.status = integrity.failedCodes.length ? "PARTIAL" : "COMPLETE";

            run.resultData = data;
            run.done = true;
            postPageMessage("RESULT", { requestId, data });
            setStatus(
                state,
                integrity.failedCodes.length
                    ? `Extraction finished with ${integrity.failedCodes.length} failed code(s). Preparing partial JSON…`
                    : "Extraction complete. Preparing JSON download…",
                integrity.failedCodes.length ? "warning" : "working",
                { state: integrity.failedCodes.length ? "PARTIAL" : "RUNNING" }
            );

            // The ISOLATED-world bridge persists and triggers the download. If it
            // cannot acknowledge within 5 seconds, MAIN triggers a safe fallback.
            await sleep(5000);
            if (!run.acknowledged) {
                downloadJson(data);
                setStatus(
                    state,
                    integrity.failedCodes.length
                        ? `Partial — ${integrity.successful}/${PROCEDURE_CODES.length} codes succeeded. JSON downloaded.`
                        : `Done — ${integrity.successful}/${PROCEDURE_CODES.length} codes extracted. JSON downloaded.`,
                    integrity.failedCodes.length ? "warning" : "ready",
                    { state: integrity.failedCodes.length ? "PARTIAL" : "COMPLETE" }
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
        const queue = PROCEDURE_CODES.filter(code => !results.has(code));
        let completed = PROCEDURE_CODES.length - queue.length;
        const concurrency = 3;

        const workers = Array.from({ length: Math.min(concurrency, Math.max(queue.length, 1)) }, async () => {
            while (queue.length && !run.cancelled) {
                const code = queue.shift();
                try {
                    const transaction = await fetchProcedureWithRetry(state, nativeFetch, code, run);
                    results.set(code, transaction);
                } catch (error) {
                    errors.set(code, String(error.message || error));
                    results.set(code, error.transaction || null);
                }
                completed += 1;
                setStatus(state, `Extracting procedure benefits: ${completed}/${PROCEDURE_CODES.length}`, "working", {
                    state: "RUNNING", completed, total: PROCEDURE_CODES.length,
                    progress: Math.round((completed / PROCEDURE_CODES.length) * 100)
                });
                await sleep(120 + Math.floor(Math.random() * 140));
            }
        });

        await Promise.all(workers);
        results.__errors = errors;
        return results;
    }

    async function fetchProcedureWithRetry(state, nativeFetch, code, run, attempt = 0) {
        if (run.cancelled) throw new Error("Extraction cancelled.");

        const body = { ...state.procedureTemplate, procedureCodes: code };
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
                return fetchProcedureWithRetry(state, nativeFetch, code, run, attempt + 1);
            }
            throw new Error(`${code}: network request failed (${error.message})`);
        }

        const text = await response.text();
        const data = safeJsonParse(text);
        const transaction = {
            request: {
                method: "POST",
                endpoint: PROCEDURE_SEARCH_PATH,
                query: "?type=codes",
                headers: sanitizeForOutput(headers),
                body: sanitizeForOutput(body)
            },
            http_status: response.status,
            captured_at: new Date().toISOString(),
            response: data !== null ? sanitizeForOutput(data) : (text ? text.slice(0, 30000) : null)
        };

        if (response.ok && data !== null) return transaction;
        if ((response.status === 429 || response.status >= 500) && attempt < 3) {
            const retryAfter = Number(response.headers.get("retry-after"));
            await sleep(Number.isFinite(retryAfter) ? retryAfter * 1000 : 700 * (2 ** attempt));
            return fetchProcedureWithRetry(state, nativeFetch, code, run, attempt + 1);
        }

        let message;
        if (response.status === 401 || response.status === 403) {
            message = `${code}: Toolkit authorization expired. Refresh/reload the Member Details & Benefits page (or re-login if required) so normal authenticated API traffic refreshes the token, then retry.`;
        } else {
            message = `${code}: HTTP ${response.status}${text ? ` — ${text.slice(0, 180)}` : ""}`;
        }
        const err = new Error(message);
        err.transaction = transaction;
        throw err;
    }

    // =====================================================================
    // Output construction
    // =====================================================================

    function benefitsRequestDob(request) {
        return firstMeaningful([request?.memberDateOfBirth, request?.memberBirthDate]);
    }

    function extractCurrentMemberFromDom() {
        const result = {
            name: "", dob: "", relationship: "", eligibility: "", effectiveDate: "", memberId: "", source: ""
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

                const headerCells = [...header.querySelectorAll("td")].map(cell => cleanText(cell.textContent || ""));
                for (let i = 0; i < headerCells.length; i++) {
                    const cell = headerCells[i];
                    if (!result.name && /^Patient\s+Name\s*:/i.test(cell)) result.name = cleanText(cell.replace(/^Patient\s+Name\s*:\s*/i, ""));
                    if (/^Birthdate\s*:?$/i.test(cell) && !result.dob) result.dob = headerCells[i + 1] || "";
                    if (/^Relationship\s*:?$/i.test(cell) && !result.relationship) result.relationship = headerCells[i + 1] || "";
                    if (/^Eligibility\s*:?$/i.test(cell) && !result.eligibility) result.eligibility = headerCells[i + 1] || "";
                    if (/^Effective\s+Date\s*:?$/i.test(cell) && !result.effectiveDate) result.effectiveDate = headerCells[i + 1] || "";
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

    function buildAccumulatorPageRows(ppoAccumulatorBuckets) {
        const rows = [];
        for (const bucket of toArray(ppoAccumulatorBuckets)) {
            for (const acc of toArray(bucket?.accumulators)) {
                rows.push({
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
                });
            }
        }
        return sanitizeForOutput(rows);
    }

    function buildProcedurePageRow(item) {
        const bucket = toArray(item?.response).find(isExactPpoBucket) || null;
        const path = toArray(bucket?.coverages);
        const leaf = path.find(node => cleanText(node?.procedureId).toUpperCase() === cleanText(item?.procedure_code).toUpperCase())
            || [...path].sort((a, b) => Number(b?.level || 0) - Number(a?.level || 0))[0]
            || null;
        const parentContext = path
            .filter(node => node !== leaf && toArray(node?.exclusionsAndLimitations).length)
            .map(node => ({
                level: node?.level ?? null,
                procedure: node?.procedure ?? null,
                procedureId: node?.procedureId ?? null,
                exclusionsAndLimitations: node?.exclusionsAndLimitations ?? null
            }));
        return sanitizeForOutput({
            procedureCode: item?.procedure_code ?? null,
            procedurePath: path.map(node => ({
                level: node?.level ?? null,
                procedure: node?.procedure ?? null,
                procedureId: node?.procedureId ?? null
            })),
            percentCovered: leaf?.coverage?.percent ?? null,
            waitingPeriod: leaf?.waitingPeriods ?? null,
            waitingPeriodMetDate: leaf?.waitingPeriodMetDate ?? null,
            medicallyNecessary: leaf?.coverage?.medicallyNecessary ?? null,
            exclusionsAndLimitations: leaf?.exclusionsAndLimitations ?? null,
            parentContext,
            radioGraphsRequired: leaf?.radioGraphsRequired ?? null,
            remarksRequired: leaf?.remarksRequired ?? null
        });
    }

    function buildPageProcedureResults(procedureResults) {
        return procedureResults.map(item => {
            const row = buildProcedurePageRow(item);
            return sanitizeForOutput({
                procedureCode: item.procedure_code,
                httpStatus: item.http_status ?? null,
                status: item.error ? "FAILED" : "OK",
                procedurePath: row?.procedurePath ?? [],
                percentCovered: row?.percentCovered ?? null,
                waitingPeriod: row?.waitingPeriod ?? null,
                waitingPeriodMetDate: row?.waitingPeriodMetDate ?? null,
                medicallyNecessary: row?.medicallyNecessary ?? null,
                limitations: [
                    ...(toArray(row?.exclusionsAndLimitations).length ? [{
                        level: "procedure",
                        procedure: item.procedure_code,
                        exclusionsAndLimitations: row.exclusionsAndLimitations
                    }] : []),
                    ...toArray(row?.parentContext)
                ],
                radioGraphsRequired: row?.radioGraphsRequired ?? null,
                remarksRequired: row?.remarksRequired ?? null,
                error: item.error ?? null
            });
        });
    }

    function buildFinalOutput(state, rawByCode, run) {
        const memberRoot = state.memberSearchResponse || {};
        const template = state.procedureTemplate || {};
        const memberSearchRequest = state.memberSearchRequest || {};
        const domMember = extractCurrentMemberFromDom();
        const memberApiContext = resolveMemberApiContext(memberRoot, template, domMember);
        const subscriber = memberApiContext.subscriber || {};
        const patient = memberApiContext.patient || { isSubscriber: false, record: {} };
        const procedureErrors = rawByCode.__errors || new Map();

        const apiSubscriberName = joinName(subscriber.subscriberFirstName, subscriber.subscriberLastName);
        const apiPatientName = patient.isSubscriber
            ? apiSubscriberName
            : joinName(patient.record?.dependentFirstName, patient.record?.dependentLastName);
        const patientName = firstMeaningful([apiPatientName, domMember.name]) || "N/A";
        const patientDob = firstMeaningful([
            patient.isSubscriber ? subscriber.dateOfBirth : patient.record?.dateOfBirth,
            domMember.dob,
            benefitsRequestDob(state.memberBenefitsRequest)
        ]);
        const patientEffective = firstMeaningful([
            patient.isSubscriber ? subscriber.effectiveDate : patient.record?.eligibilityEffectiveDate,
            domMember.effectiveDate
        ]);
        const patientStatus = firstMeaningful([
            patient.isSubscriber ? subscriber.eligibilityStatus : patient.record?.eligibilityStatus,
            domMember.eligibility
        ]);
        const relationship = firstMeaningful([
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
            source: memberApiContext.matched ? "member_details_api" : (domMember.name ? "page_dom" : "request_context")
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
        const exclusionsAndLimitations = extractExclusionsAndLimitations(ppoNetworkBenefits);

        const procedureResults = PROCEDURE_CODES.map(code => {
            const value = rawByCode.get(code);
            const error = procedureErrors.get(code) || null;
            const tx = value && typeof value === "object" && !Array.isArray(value) && Object.prototype.hasOwnProperty.call(value, "response")
                ? value
                : {
                    request: {
                        method: "POST",
                        endpoint: PROCEDURE_SEARCH_PATH,
                        query: "?type=codes",
                        body: sanitizeForOutput({ ...template, procedureCodes: code })
                    },
                    http_status: value ? 200 : null,
                    captured_at: null,
                    response: value
                };
            return {
                procedure_code: code,
                request: sanitizeForOutput(tx.request || {
                    method: "POST",
                    endpoint: PROCEDURE_SEARCH_PATH,
                    query: "?type=codes",
                    body: { ...template, procedureCodes: code }
                }),
                http_status: tx.http_status ?? null,
                captured_at: tx.captured_at || null,
                response: tx.response === null || tx.response === undefined
                    ? null
                    : sanitizePpoNetworkDataForOutput(tx.response),
                error
            };
        });

        const successfulProcedureCount = procedureResults.filter(item => !item.error).length;
        const failedProcedureCodes = procedureResults.filter(item => item.error).map(item => item.procedure_code);

        const familySection = extractAllFamilyMembersForOutput(selectedMember);
        const pageProcedureResults = buildPageProcedureResults(procedureResults);

        return sanitizeForOutput({
            source: "Delta Dental Office Toolkit",
            portal: location.hostname,
            page: "Member Details & Benefits",
            captured_at: new Date().toISOString(),
            selected_network: "PPO Dentist",

            // Main JSON mirrors the actual Toolkit page order.
            member_details: familySection,

            networks: {
                section_title: "Networks",
                selected: "PPO Dentist",
                available_in_output: extractToolkitNetworkTabs()
            },

            claim_reminders: {
                section_title: "Claim Reminders",
                messages: extractToolkitSectionParagraphs("Claim Reminders")
            },

            routine_procedures: {
                section_title: "Routine Procedures",
                network: "PPO Dentist",
                notes: extractToolkitSectionParagraphs("Routine Procedures"),
                rows: toArray(ppoRoutineBuckets).flatMap(bucket => toArray(bucket?.routineProcedures)).map(item => sanitizeForOutput({
                    procedureCode: item?.procedureCode ?? null,
                    description: item?.description ?? null,
                    percentCovered: item?.benefitPercentage ?? null,
                    eligibleNow: item?.isCovered ?? null,
                    serviceDates: item?.serviceDates ?? [],
                    numberOfRemainingRadiographs: item?.numberOfRemainingRadiographs ?? null
                }))
            },

            coverages: {
                section_title: "Coverages",
                network: "PPO Dentist",
                notes: extractToolkitSectionParagraphs("Coverages"),
                coverage_rows: buildCoveragePageRows(ppoNetworkBenefits),
                procedure_code_search: {
                    endpoint: `${PROCEDURE_SEARCH_PATH}?type=codes`,
                    codes_requested: [...PROCEDURE_CODES],
                    count: pageProcedureResults.length,
                    successful_count: successfulProcedureCount,
                    failed_codes: failedProcedureCodes,
                    results: pageProcedureResults
                }
            },

            exclusions_and_limitations: {
                section_title: "Exclusions And Limitations",
                network: "PPO Dentist",
                notes: extractToolkitSectionParagraphs("Exclusions And Limitations"),
                records: exclusionsAndLimitations
            },

            maximums_and_deductibles: {
                section_title: "Maximums and Deductibles",
                network: "PPO Dentist",
                notes: extractToolkitSectionParagraphs("Maximums and Deductibles"),
                accumulationPeriodType: contract.accumulationPeriodType ?? null,
                rows: buildAccumulatorPageRows(ppoAccumulatorBuckets)
            },

            ortho_information: {
                section_title: "Ortho Information",
                network: "PPO Dentist",
                notes: extractToolkitSectionParagraphs("Ortho Information"),
                orthoAgeLimitConfig: ppoOrthoAgeLimits(benefitRoot),
                orthoPaymentSchedule: sanitizeForOutput(subClientContract.orthoPaymentSchedule || null)
            },

            more_information: {
                section_title: "More Information",

                client_benefit_information: {
                    section_title: "Client Benefit Information",
                    notes: extractToolkitSectionParagraphs("Client Benefit Information"),
                    display_fields: {
                        plan: benefitClient.planAcronym ?? template.planAcronym ?? null,
                        product: benefitRoot.productName ?? null,
                        payorId: benefitClient.planAcronym ?? template.planAcronym ?? null,
                        groupNumber: benefitClient.clientSpecifiedId ?? template.clientSpecifiedId ?? null,
                        subGroupNumber: benefitClient.subClientSpecifiedId ?? template.subClientSpecifiedId ?? null,
                        groupName: benefitClient.clientName ?? null,
                        subGroupName: benefitClient.subClientName ?? null
                    }
                },

                cob_information: {
                    section_title: "COB Information",
                    notes: extractToolkitSectionParagraphs("COB Information"),
                    cobConfig: sanitizeForOutput(contract.cobConfig || null)
                },

                age_limitations: {
                    section_title: "Age Limitations",
                    notes: extractToolkitSectionParagraphs("Age Limitations"),
                    ageLimitations: sanitizeForOutput(contract.ageLimitations || null)
                },

                claim_and_inquiry_mailing_addresses: {
                    section_title: "Claim & Inquiry Mailing Addresses",
                    messages: extractToolkitSectionParagraphs("Claim & Inquiry Mailing Addresses"),
                    claimMailingAddress: subscriber?.claimAddressInfo?.claimMailingAddress ?? null,
                    inquiryAddress: subscriber?.claimAddressInfo?.inquiryAddress ?? null,
                    payorId: subscriber?.claimAddressInfo?.payorId ?? null,
                    phoneNumber: subscriber?.claimAddressInfo?.phoneNumber ?? null,
                    subscriberPhoneNumber: subscriber?.claimAddressInfo?.subscriberPhoneNumber ?? null
                }
            },

            crawl_statistics: {
                requested_codes: PROCEDURE_CODES.length,
                successful_codes: successfulProcedureCount,
                failed_codes: failedProcedureCodes,
                status: failedProcedureCodes.length ? "PARTIAL" : "COMPLETE"
            }
        });
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
        D0274: /bitewing/i,
        D1510: /space\s+maintain/i,
        D1110: /prophylaxis|cleanings?/i,
        D1120: /prophylaxis|cleanings?/i,
        D1206: /fluoride/i,
        D1351: /sealant/i,
        D2140: /amalgam|restoration/i,
        D2331: /posterior\s+composite|resin\s+restoration/i,
        D2620: /inlays?|onlays?/i,
        D2740: /cast\s+restoration|crowns?/i,
        D2950: /cast\s+restoration|cores?|substructures?|crowns?/i,
        D4341: /root\s+planing|scaling/i,
        D4355: /full\s+mouth\s+debridement/i,
        D4910: /periodontal|perio\s+maintenance/i,
        D5110: /full\s+and\s+partial\s+dentures?|dentures?/i,
        D5740: /full\s+and\s+partial\s+dentures?|reline/i,
        D5860: /full\s+and\s+partial\s+dentures?|over\s*denture/i,
        D6010: /implants?/i,
        D6056: /implants?/i,
        D6065: /implants?/i,
        D6194: /implants?/i,
        D6245: /bridgework|bridges?/i,
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
        const matcher = PROCEDURE_LIMITATION_MATCHERS[code];
        const parentRules = coverages
            .filter(item => item !== leaf)
            .flatMap(item => splitRuleText(item?.exclusionsAndLimitations));
        const matchedParent = matcher ? parentRules.filter(text => matcher.test(text)) : [];
        return uniqueStrings([...leafRules, ...matchedParent]);
    }

    function selectRelevantProcedureWaitingPeriods(code, coverages, leaf) {
        const leafRules = splitRuleText(leaf?.waitingPeriods);
        const matcher = PROCEDURE_LIMITATION_MATCHERS[code];
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
        if (successful === 0) {
            throw new Error("All procedure benefit lookups failed. No result was downloaded; refresh the authenticated member-benefits page and retry.");
        }
        return { successful, failedCodes };
    }


    function downloadJson(data) {
        if (!data || typeof data !== "object") throw new Error("Cannot download an empty extraction result.");
        const patient = String(data?.member_details?.selectedMember?.patientName || "patient").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "patient";
        const date = new Date().toISOString().slice(0, 10);
        const filename = `delta_toolkit_${patient}_${date}.json`;
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
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
