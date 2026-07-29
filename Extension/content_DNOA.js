(() => {
    "use strict";

    if (globalThis.__insuranceAuditorDnoaInstalled) return;
    globalThis.__insuranceAuditorDnoaInstalled = true;

    const SOURCE = "dnoaconnect";
    const SCHEMA_VERSION = "1.0.0";
    const DNOA_HOST = "www.dnoaconnect.com";
    const DEFAULT_PROCEDURE_CODES = [
        "D0120", "D0180", "D0140", "D0150", "D0274", "D0210", "D0330",
        "D0220", "D0364", "D0431", "D1110", "D1120", "D1206", "D1351",
        "D1510", "D2391", "D2740", "D2950", "D2962", "D6750", "D5110",
        "D9110", "D9222", "D9230", "D9243", "D9310", "D9944", "D4341",
        "D4355", "D4346", "D4910", "D4381", "D4260", "D4249", "D3310",
        "D3330", "D7140", "D7210", "D7240", "D7953", "D6010", "D6056"
    ];
    const KNOWN_LABELS = [
        "Member Status", "Member Name", "Date of Birth", "Subscriber ID",
        "Subscriber Name", "Alternative Benefit Provision", "Alternate Benefit Provision",
        "Missing Tooth Provision", "Coordination Of Benefits", "Assignment Of Benefits",
        "Filling Downgrade", "Benefit Period", "Enrolled", "Eligibility", "Payer",
        "Plan Name", "Group Number", "Group Name", "Employer / Group #",
        "Claims Address", "Address", "Payer ID", "Start Date", "End Date", "Network"
    ];
    const requestPromises = new Map();
    const observedResourceUrls = new Set();
    let observerInstalled = false;
    let lastContextKey = "";
    let extractionCache = null;
    let extractionPromise = null;
    let extractionPromiseKey = null;

    const hasValue = value => value !== undefined && value !== null;
    const firstValue = (...values) => values.find(hasValue) ?? null;

    function cleanText(value) {
        return String(value ?? "").replace(/\s+/g, " ").trim();
    }

    function normalizeLabel(value) {
        return cleanText(value).replace(/[\s:;.,#]+$/g, "").toLowerCase();
    }

    function normalizeProcedureCode(value) {
        const match = String(value ?? "").trim().toUpperCase().match(/(?:D\s*)?(\d{1,4})/);
        return match ? `D${match[1].padStart(4, "0")}` : null;
    }

    function isVisible(element) {
        if (!(element instanceof Element)) return false;
        const style = getComputedStyle(element);
        return style.display !== "none" && style.visibility !== "hidden" &&
            element.getAttribute("aria-hidden") !== "true";
    }

    function elementOwnText(element) {
        return cleanText(Array.from(element?.childNodes || [])
            .filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent).join(" "));
    }

    function valueNearLabel(element, label) {
        const target = normalizeLabel(label);
        const own = elementOwnText(element);
        const full = cleanText(element.textContent);
        const ownNormalized = normalizeLabel(own);
        if (ownNormalized === target) {
            const described = element.getAttribute?.("for");
            if (described) {
                const field = document.getElementById(described);
                const fieldValue = cleanText(field?.value ?? field?.textContent);
                if (fieldValue) return fieldValue;
            }
            let sibling = element.nextElementSibling;
            while (sibling) {
                const value = cleanText(sibling.value ?? sibling.textContent);
                if (value) return value;
                sibling = sibling.nextElementSibling;
            }
        }
        const prefix = new RegExp(`^${target.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*[:#-]?\\s*`, "i");
        if (prefix.test(normalizeLabel(full)) && full.length > own.length) {
            const value = cleanText(full.replace(new RegExp(`^\\s*${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*[:#-]?\\s*`, "i"), ""));
            if (value && normalizeLabel(value) !== target) return value;
        }
        const container = element.closest("tr, dl, .row, [class*='detail'], [class*='card'], [class*='field']") || element.parentElement;
        if (container) {
            const candidates = Array.from(container.querySelectorAll("td, th, dd, dt, p, span, div, input"));
            const index = candidates.indexOf(element);
            for (const candidate of candidates.slice(Math.max(0, index + 1))) {
                if (candidate === element || candidate.contains(element) || !isVisible(candidate)) continue;
                const value = cleanText(candidate.value ?? candidate.textContent);
                if (value && normalizeLabel(value) !== target) return value;
            }
        }
        return null;
    }

    function getLabelValue(labelText, root = document.body) {
        if (!root) return null;
        const target = normalizeLabel(labelText);
        const elements = root.querySelectorAll("label, th, td, dt, dd, p, span, div");
        for (const element of elements) {
            if (!isVisible(element)) continue;
            const own = normalizeLabel(elementOwnText(element));
            const full = normalizeLabel(element.textContent);
            if (own === target || (element.children.length === 0 && full === target)) {
                const value = valueNearLabel(element, labelText);
                if (value !== null) return value;
            }
        }
        return null;
    }

    function getMultilineLabelValue(labelText, root = document.body) {
        if (!root) return null;
        const target = normalizeLabel(labelText);
        for (const element of root.querySelectorAll("label, th, td, dt, p, span, div")) {
            if (!isVisible(element) || normalizeLabel(elementOwnText(element)) !== target) continue;
            const values = [];
            let sibling = element.nextElementSibling;
            while (sibling && values.length < 6) {
                const text = cleanText(sibling.value ?? sibling.textContent);
                if (!text) {
                    sibling = sibling.nextElementSibling;
                    continue;
                }
                if (KNOWN_LABELS.some(label => normalizeLabel(label) === normalizeLabel(text))) break;
                values.push(text);
                sibling = sibling.nextElementSibling;
            }
            if (values.length) return values.join(", ");
        }
        return getLabelValue(labelText, root);
    }

    function scrapeVisibleDetails() {
        const details = {};
        for (const label of KNOWN_LABELS) {
            const value = getLabelValue(label);
            if (value !== null) details[label] = value;
        }
        const claimsAddress = getMultilineLabelValue("Claims Address");
        if (claimsAddress) details["Claims Address"] = claimsAddress;
        const add = (label, value) => {
            const key = cleanText(label).replace(/:$/, "");
            const cleaned = cleanText(value);
            if (key && cleaned && key !== cleaned && key.length <= 100 && cleaned.length <= 1000 &&
                details[key] === undefined) details[key] = cleaned;
        };
        for (const row of document.querySelectorAll("tr")) {
            const cells = row.querySelectorAll(":scope > th, :scope > td");
            if (cells.length >= 2) add(cells[0].textContent, cells[1].textContent);
        }
        for (const dt of document.querySelectorAll("dt")) add(dt.textContent, dt.nextElementSibling?.textContent);
        for (const label of document.querySelectorAll("label")) {
            const field = label.htmlFor ? document.getElementById(label.htmlFor) : label.nextElementSibling;
            add(label.textContent, field?.value ?? field?.textContent);
        }
        for (const candidate of document.querySelectorAll("p, div, span")) {
            if (!isVisible(candidate) || candidate.children.length > 2) continue;
            const own = elementOwnText(candidate);
            if (!own || own.length > 100) continue;
            const sibling = candidate.nextElementSibling;
            if (sibling && sibling.parentElement === candidate.parentElement) {
                add(own, sibling.value ?? sibling.textContent);
            }
        }
        return details;
    }

    function isRelevantApiUrl(value) {
        try {
            const url = new URL(value, location.href);
            return url.origin === location.origin &&
                (/\/portalUser$/.test(url.pathname) ||
                 /\/members\/[^/]+\/(associatedMembers|planSummary|planAccumulators|benefits|procedureHistory)(?:\/)?$/.test(url.pathname) ||
                 /\/members\/[^/]+\/procedureBenefits\/[^/]+(?:\/)?$/.test(url.pathname));
        } catch {
            return false;
        }
    }

    function rememberResourceUrl(value) {
        if (isRelevantApiUrl(value)) observedResourceUrls.add(new URL(value, location.href).href);
    }

    function getResourceUrls() {
        for (const entry of performance.getEntriesByType("resource")) rememberResourceUrl(entry.name);
        return Array.from(observedResourceUrls);
    }

    function parseContextFromApiUrl(value) {
        try {
            const url = new URL(value, location.href);
            const match = url.pathname.match(/\/members\/([^/]+)\/(associatedMembers|planSummary|planAccumulators|benefits|procedureHistory|procedureBenefits)(?:\/([^/]+))?\/?$/);
            if (!match) return null;
            return {
                memberReferenceId: decodeURIComponent(match[1]),
                policyUuid: url.searchParams.get("uuid"),
                subscriberId: url.searchParams.get("subscriberId"),
                dateOfBirth: url.searchParams.get("dateOfBirth"),
                endpoint: match[2],
                procedureCode: normalizeProcedureCode(match[3])
            };
        } catch {
            return null;
        }
    }

    function findDomValue(details, labels) {
        const map = new Map(Object.entries(details).map(([key, value]) => [normalizeLabel(key), value]));
        for (const label of labels) if (map.has(normalizeLabel(label))) return map.get(normalizeLabel(label));
        return null;
    }

    /** Discovers request identifiers without reading private framework state. */
    function discoverContext() {
        const urls = getResourceUrls();
        const context = {
            memberReferenceId: null, policyUuid: null, subscriberId: null, dateOfBirth: null,
            selectedMember: null, selectedPolicy: null
        };
        const contextSources = {};
        const parsed = urls.map(parseContextFromApiUrl).filter(Boolean);
        const preferred = [...parsed].reverse().find(item =>
            item.memberReferenceId && item.policyUuid && item.subscriberId && item.dateOfBirth) ||
            [...parsed].reverse().find(item => item.memberReferenceId);
        if (preferred) {
            for (const key of ["memberReferenceId", "policyUuid", "subscriberId", "dateOfBirth"]) {
                if (preferred[key]) {
                    context[key] = preferred[key];
                    contextSources[key] = "performance-resource";
                }
            }
        }
        const domDetails = scrapeVisibleDetails();
        const domFallbacks = {
            subscriberId: ["Subscriber ID"],
            dateOfBirth: ["Date of Birth"],
            selectedMember: ["Member Name"],
            selectedPolicy: ["Plan Name", "Group Name", "Group Number"]
        };
        for (const [key, labels] of Object.entries(domFallbacks)) {
            const value = findDomValue(domDetails, labels);
            if (!context[key] && value) {
                context[key] = value;
                contextSources[key] = "dom";
            }
        }
        return { context, contextSources, domDetails, urls };
    }

    function makeHttpError(message, status, url) {
        const error = new Error(message);
        error.status = status;
        error.url = url;
        return error;
    }

    /** Fetches and validates JSON, with timeout, one transient retry, and deduplication. */
    async function fetchJson(url, options = {}) {
        const href = new URL(url, location.origin).href;
        if (new URL(href).origin !== location.origin) throw makeHttpError("Cross-origin request refused", 0, href);
        if (requestPromises.has(href)) return requestPromises.get(href);
        const promise = (async () => {
            const timeoutMs = options.timeoutMs ?? 15000;
            for (let attempt = 0; attempt < 2; attempt++) {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeoutMs);
                try {
                    const response = await fetch(href, {
                        method: "GET",
                        credentials: "include",
                        cache: "no-store",
                        headers: { Accept: "application/json" },
                        signal: controller.signal
                    });
                    if (response.status === 204 || response.status === 404) {
                        throw makeHttpError(`Endpoint unavailable (${response.status})`, response.status, href);
                    }
                    if (!response.ok) throw makeHttpError(`HTTP ${response.status}`, response.status, href);
                    const contentType = response.headers.get("content-type") || "";
                    if (!/json/i.test(contentType)) throw makeHttpError("Expected a JSON response", response.status, href);
                    return await response.json();
                } catch (error) {
                    const transient = error.name === "AbortError" || error instanceof TypeError ||
                        error.status === 408 || error.status === 429 || error.status >= 500;
                    if (attempt === 0 && transient) continue;
                    throw error;
                } finally {
                    clearTimeout(timer);
                }
            }
            return null;
        })();
        requestPromises.set(href, promise);
        try {
            return await promise;
        } finally {
            requestPromises.delete(href);
        }
    }

    async function mapWithConcurrency(items, limit, worker) {
        const results = new Array(items.length);
        let next = 0;
        async function run() {
            while (next < items.length) {
                const index = next++;
                try {
                    results[index] = { status: "fulfilled", value: await worker(items[index], index) };
                } catch (reason) {
                    results[index] = { status: "rejected", reason };
                }
            }
        }
        await Promise.all(Array.from({ length: Math.min(limit, items.length) }, run));
        return results;
    }

    function addDiagnosticError(diagnostics, endpoint, error) {
        diagnostics.errors.push({
            endpoint,
            code: error.name === "AbortError" ? "TIMEOUT" : `HTTP_${error.status || "ERROR"}`,
            message: cleanText(error.message) || "Request failed"
        });
    }

    function validateResponseContext(data, context, endpoint, diagnostics) {
        if (!data || Array.isArray(data) || typeof data !== "object") return true;
        const checks = [
            ["memberReferenceId", data.referenceId, context.memberReferenceId],
            ["subscriberId", data.subscriberId, context.subscriberId],
            ["dateOfBirth", data.dateOfBirth, context.dateOfBirth]
        ];
        const mismatches = checks.filter(([, actual, expected]) =>
            hasValue(actual) && hasValue(expected) && String(actual) !== String(expected));
        if (mismatches.length) {
            diagnostics.identifierMismatches.push({
                endpoint,
                fields: mismatches.map(([field]) => field)
            });
            return false;
        }
        return true;
    }

    function buildUrl(path, context, includePlanQuery) {
        const url = new URL(path, location.origin);
        if (includePlanQuery) {
            url.searchParams.set("dateOfBirth", context.dateOfBirth);
            url.searchParams.set("subscriberId", context.subscriberId);
            if (includePlanQuery === "policy") url.searchParams.set("uuid", context.policyUuid);
        }
        return url.href;
    }

    async function fetchBaseInsuranceData(context, diagnostics) {
        const memberPath = `/members/${encodeURIComponent(context.memberReferenceId)}`;
        const definitions = [
            ["planSummary", buildUrl(`${memberPath}/planSummary`, context, "policy")],
            ["planAccumulators", buildUrl(`${memberPath}/planAccumulators`, context, "policy")],
            ["benefits", buildUrl(`${memberPath}/benefits`, context, "policy")],
            ["procedureHistory", buildUrl(`${memberPath}/procedureHistory`, context, false)]
        ];
        definitions.forEach(([name]) => diagnostics.requestedEndpoints.push(name));
        const settled = await Promise.allSettled(definitions.map(([, url]) => fetchJson(url)));
        const output = {};
        settled.forEach((result, index) => {
            const [name] = definitions[index];
            if (result.status === "fulfilled" &&
                validateResponseContext(result.value, context, name, diagnostics)) {
                output[name] = result.value;
                diagnostics.successfulEndpoints.push(name);
            } else {
                output[name] = null;
                diagnostics.unavailableEndpoints.push(name);
                if (result.status === "rejected") addDiagnosticError(diagnostics, name, result.reason);
            }
        });
        if (!Array.isArray(output.procedureHistory)) output.procedureHistory = [];
        return output;
    }

    function discoverProcedureCodes() {
        return [...DEFAULT_PROCEDURE_CODES];
    }

    function normalizeProcedureBenefit(response, requestedCode) {
        const benefit = response?.benefit ?? {};
        return {
            procedure_code: normalizeProcedureCode(benefit.procedureCode) || requestedCode,
            original_procedure_code: benefit.procedureCode ?? null,
            procedure_status: response?.procedureStatus ?? null,
            description: benefit.description ?? null,
            coinsurance_in_network_pct: benefit.coinsuranceInNetwork ?? null,
            coinsurance_out_network_pct: benefit.coinsuranceOutNetwork ?? null,
            copay_amount: benefit.copayAmount ?? null,
            subject_to_review: benefit.subjectToReview ?? null,
            deductible_met_in_network: benefit.deductibleMetInNetwork ?? null,
            deductible_met_out_network: benefit.deductibleMetOutNetwork ?? null,
            alternate_benefit: benefit.alternateBenefit ?? null,
            waiting_period: benefit.waitingPeriod ?? null,
            limitations: benefit.limitations ?? null,
            accumulators: benefit.accumulators ?? []
        };
    }

    async function fetchProcedureBenefits(context, codes, diagnostics) {
        const output = {};
        diagnostics.procedureCodesRequested = [...codes];
        const memberPath = `/members/${encodeURIComponent(context.memberReferenceId)}/procedureBenefits`;
        const settled = await mapWithConcurrency(codes, 4, async code => {
            const numericCode = code.slice(1);
            const endpoint = `procedureBenefits/${code}`;
            diagnostics.requestedEndpoints.push(endpoint);
            const response = await fetchJson(buildUrl(`${memberPath}/${encodeURIComponent(numericCode)}`, context, false));
            if (!validateResponseContext(response, context, endpoint, diagnostics)) return null;
            diagnostics.successfulEndpoints.push(endpoint);
            return normalizeProcedureBenefit(response, code);
        });
        settled.forEach((result, index) => {
            const code = codes[index];
            if (result.status === "fulfilled" && result.value) output[code] = result.value;
            else {
                diagnostics.procedureCodesUnavailable.push(code);
                diagnostics.unavailableEndpoints.push(`procedureBenefits/${code}`);
                if (result.status === "rejected" && ![204, 404].includes(result.reason?.status)) {
                    addDiagnosticError(diagnostics, `procedureBenefits/${code}`, result.reason);
                }
            }
        });
        return output;
    }

    function normalizeHistory(history) {
        return (Array.isArray(history) ? history : []).map(item => ({
            ...item,
            original_procedure_code: item?.code ?? null,
            procedure_code: normalizeProcedureCode(item?.code)
        }));
    }

    function formatMoney(value) {
        if (value === null || value === undefined) return "N/A";
        if (typeof value === "number" && Number.isFinite(value)) {
            return value.toLocaleString("en-US", {
                style: "currency",
                currency: "USD",
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
        }
        return value;
    }

    function buildFinancialRecords(financialType, periods) {
        const records = [];
        const configurations = [
            { memberType: "individual", covers: "IND", network: "IN", suffix: "InNetwork" },
            { memberType: "individual", covers: "IND", network: "OUT", suffix: "OutNetwork" },
            { memberType: "family", covers: "FAM", network: "IN", suffix: "InNetwork" },
            { memberType: "family", covers: "FAM", network: "OUT", suffix: "OutNetwork" }
        ];
        for (const [period, periodData] of Object.entries(periods)) {
            for (const configuration of configurations) {
                const values = periodData?.[configuration.memberType];
                const limit = values?.[`amount${configuration.suffix}`] ?? null;
                const remaining = values?.[`remaining${configuration.suffix}`] ?? null;
                if (!hasValue(limit) && !hasValue(remaining)) continue;
                const used = typeof limit === "number" && typeof remaining === "number"
                    ? Math.max(0, Number((limit - remaining).toFixed(2)))
                    : null;
                const periodLabel = period === "benefit_period" ? "Benefit Period" : "Lifetime";
                const coversLabel = configuration.covers === "IND" ? "Individual" : "Family";
                records.push({
                    desc: `${coversLabel} ${periodLabel} ${financialType}`,
                    limit: formatMoney(limit),
                    used: formatMoney(used),
                    remaining: formatMoney(remaining),
                    covers: configuration.covers,
                    network_type: configuration.network,
                    period,
                    unit: "USD"
                });
            }
        }
        return records;
    }

    function normalizeBenefitAccumulator(accumulator) {
        return {
            id: accumulator?.id ?? null,
            code: accumulator?.code ?? null,
            type: accumulator?.type ?? null,
            unit: accumulator?.unit ?? null,
            amount: {
                in_network: {
                    individual: accumulator?.amount?.individual?.inNetwork ?? null,
                    family: accumulator?.amount?.family?.inNetwork ?? null
                },
                out_of_network: {
                    individual: accumulator?.amount?.individual?.outNetwork ?? null,
                    family: accumulator?.amount?.family?.outNetwork ?? null
                }
            },
            remaining: {
                in_network: {
                    individual: accumulator?.remaining?.individual?.inNetwork ?? null,
                    family: accumulator?.remaining?.family?.inNetwork ?? null
                },
                out_of_network: {
                    individual: accumulator?.remaining?.individual?.outNetwork ?? null,
                    family: accumulator?.remaining?.family?.outNetwork ?? null
                }
            }
        };
    }

    function accumulatorObject(accumulators) {
        const output = {};
        for (const accumulator of accumulators) {
            const base = cleanText(accumulator?.code || accumulator?.type || "accumulator")
                .toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "accumulator";
            let key = base;
            if (output[key]) key = `${base}_${accumulator?.id ?? Object.keys(output).length + 1}`;
            output[key] = normalizeBenefitAccumulator(accumulator);
        }
        return output;
    }

    function normalizeBenefitCategories(categories, benefitAccumulators) {
        const byId = new Map((benefitAccumulators || []).map(item => [String(item?.id), item]));
        return (categories || []).map(category => {
            const ids = Array.isArray(category?.accumulators?.id) ? category.accumulators.id : [];
            const linked = ids.map(id => byId.get(String(id))).filter(Boolean);
            return {
                ...category,
                financials: accumulatorObject(linked)
            };
        });
    }

    function normalizeFinancials(planAccumulators) {
        const maximum = planAccumulators?.maximum ?? {};
        const deductible = planAccumulators?.deductible ?? {};
        return {
            maximums: buildFinancialRecords("Maximum", {
                benefit_period: maximum.benefitPeriod,
                lifetime: maximum.lifetime
            }),
            deductibles: buildFinancialRecords("Deductible", {
                benefit_period: deductible.benefitPeriod,
                lifetime: deductible.lifetime
            })
        };
    }

    function normalizeInsuranceData(base, procedureBenefits, domDetails) {
        const summary = base.planSummary || {};
        const benefits = base.benefits || {};
        const accumulators = base.planAccumulators || {};
        return {
            member: {
                reference_id: firstValue(summary.referenceId, benefits.referenceId),
                first_name: firstValue(summary.firstName, benefits.firstName),
                last_name: firstValue(summary.lastName, benefits.lastName),
                date_of_birth: firstValue(summary.dateOfBirth, benefits.dateOfBirth),
                status: firstValue(summary.memberStatus, benefits.status),
                relationship: benefits.relationship ?? null
            },
            subscriber: {
                id: firstValue(summary.subscriberId, benefits.subscriberId),
                first_name: summary.subscriberFirstName ?? null,
                last_name: summary.subscriberLastName ?? null
            },
            eligibility: {
                enrollment_date: summary.enrollmentDate ?? null,
                begin_date: summary.eligibilityBeginDate ?? null,
                end_date: summary.eligibilityEndDate ?? null,
                effective_date: firstValue(benefits.effectiveDate, summary.planPeriodBeginDate),
                plan_period_begin: firstValue(summary.planPeriodBeginDate, benefits.planPeriodBeginDate),
                plan_period_end: firstValue(summary.planPeriodEndDate, benefits.planPeriodEndDate)
            },
            insurance: {
                plan_name: summary.planName ?? null,
                group_number: firstValue(summary.groupNumber, benefits.groupNumber, accumulators.groupNumber),
                group_name: summary.groupName ?? null,
                corporation_or_payer: summary.corpEntity ?? findDomValue(domDetails, ["Payer"]),
                section: firstValue(benefits.section, accumulators.section),
                dental_system: firstValue(summary.dentalSystem, benefits.dentalSystem, accumulators.dentalSystem),
                policy_type: firstValue(summary.policyType, benefits.policyType, accumulators.policyType),
                plan_type: firstValue(summary.planType, benefits.planType, accumulators.planType),
                claims_address: findDomValue(domDetails, ["Claims Address"]),
                payer_id: findDomValue(domDetails, ["Payer ID"])
            },
            provisions: {
                missing_tooth: summary.missingTooth ?? null,
                coordination_of_benefits: summary.coordinationOfBenefits ?? null,
                alternate_benefit: summary.alternateBenefit ?? null,
                carryover: summary.carryover ?? null,
                medicare_advantage: summary.medicareAdvantage ?? null
            },
            financials: normalizeFinancials(accumulators),
            benefitCategories: normalizeBenefitCategories(benefits.categories, benefits.accumulators),
            procedureHistory: normalizeHistory(base.procedureHistory),
            procedureBenefits
        };
    }

    function findDomConflicts(domDetails, normalized) {
        const comparisons = [
            ["Member Status", normalized.member.status],
            ["Date of Birth", normalized.member.date_of_birth],
            ["Subscriber ID", normalized.subscriber.id],
            ["Plan Name", normalized.insurance.plan_name],
            ["Group Number", normalized.insurance.group_number],
            ["Group Name", normalized.insurance.group_name]
        ];
        return comparisons.flatMap(([label, apiValue]) => {
            const domValue = findDomValue(domDetails, [label]);
            return hasValue(apiValue) && hasValue(domValue) &&
                cleanText(apiValue).toLowerCase() !== cleanText(domValue).toLowerCase()
                ? [{ label, apiValuePresent: true, domValuePresent: true }]
                : [];
        });
    }

    /** Extracts all available DNOA data while preserving complete API responses. */
    async function extractAllDnoaData() {
        const started = performance.now();
        const startedAt = new Date().toISOString();
        const discovered = discoverContext();
        const context = discovered.context;
        if (!context.memberReferenceId || !context.subscriberId || !context.dateOfBirth || !context.policyUuid) {
            const error = new Error("Open a DNOA member plan or benefits page before extracting.");
            error.code = "CONTEXT_NOT_FOUND";
            error.diagnostics = {
                discoveredResourceUrls: discovered.urls.map(value => new URL(value).pathname),
                contextSources: discovered.contextSources,
                sufficientContext: false,
                startedAt,
                completedAt: new Date().toISOString()
            };
            throw error;
        }
        const diagnostics = {
            discoveredResourceUrls: discovered.urls.map(value => {
                const url = new URL(value);
                return `${url.pathname}?${Array.from(url.searchParams.keys()).sort().join("&")}`.replace(/\?$/, "");
            }),
            contextSources: discovered.contextSources,
            requestedEndpoints: [], successfulEndpoints: [], unavailableEndpoints: [],
            errors: [], identifierMismatches: [], unresolvedAssociatedMembers: [],
            procedureCodesRequested: [], procedureCodesUnavailable: [],
            domApiConflicts: [], startedAt, completedAt: null, durationMs: 0
        };
        const base = await fetchBaseInsuranceData(context, diagnostics);
        const codes = discoverProcedureCodes();
        const procedureBenefits = await fetchProcedureBenefits(context, codes, diagnostics);
        const normalized = normalizeInsuranceData(base, procedureBenefits, discovered.domDetails);
        diagnostics.domApiConflicts = findDomConflicts(discovered.domDetails, normalized);
        diagnostics.completedAt = new Date().toISOString();
        diagnostics.durationMs = Math.round(performance.now() - started);
        return {
            source: SOURCE,
            schemaVersion: SCHEMA_VERSION,
            capturedAt: diagnostics.completedAt,
            ...normalized
        };
    }

    function contextKey(context) {
        return `${context.memberReferenceId ?? ""}\u001f${context.policyUuid ?? ""}`;
    }

    function invalidateIfContextChanged() {
        const discovered = discoverContext();
        const key = contextKey(discovered.context);
        if (lastContextKey && key && key !== lastContextKey) {
            extractionCache = null;
            extractionPromise = null;
            extractionPromiseKey = null;
            requestPromises.clear();
        }
        if (key) lastContextKey = key;
    }

    function installContextObservers() {
        if (observerInstalled) return;
        observerInstalled = true;
        if ("PerformanceObserver" in globalThis) {
            try {
                const performanceObserver = new PerformanceObserver(list => {
                    list.getEntries().forEach(entry => rememberResourceUrl(entry.name));
                    invalidateIfContextChanged();
                });
                performanceObserver.observe({ type: "resource", buffered: true });
            } catch (error) {
                console.warn("[DNOA] Resource observation unavailable:", error.message);
            }
        }
        let mutationTimer = null;
        const mutationObserver = new MutationObserver(() => {
            clearTimeout(mutationTimer);
            mutationTimer = setTimeout(invalidateIfContextChanged, 300);
        });
        const startMutationObserver = () => {
            if (document.documentElement) mutationObserver.observe(document.documentElement, {
                childList: true, subtree: true
            });
        };
        if (document.documentElement) startMutationObserver();
        else document.addEventListener("DOMContentLoaded", startMutationObserver, { once: true });
        addEventListener("popstate", invalidateIfContextChanged);
        const dispatchRouteChange = () => dispatchEvent(new Event("dnoa-route-change"));
        for (const method of ["pushState", "replaceState"]) {
            const original = history[method];
            history[method] = function (...args) {
                const result = original.apply(this, args);
                dispatchRouteChange();
                return result;
            };
        }
        addEventListener("dnoa-route-change", invalidateIfContextChanged);
    }

    function installMessageHandler() {
        chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
            if (message?.type === "DNOA_GET_STATUS") {
                const discovered = discoverContext();
                const sufficientContext = Boolean(
                    discovered.context.memberReferenceId && discovered.context.policyUuid &&
                    discovered.context.subscriberId && discovered.context.dateOfBirth
                );
                sendResponse({
                    ok: true,
                    status: {
                        supported: location.hostname === DNOA_HOST || location.hostname.endsWith(`.${DNOA_HOST}`),
                        sufficientContext,
                        hasMemberContext: Boolean(discovered.context.memberReferenceId),
                        hasPolicyContext: Boolean(discovered.context.policyUuid)
                    }
                });
                return false;
            }
            if (message?.type !== "DNOA_EXTRACT_ALL") return false;
            const cacheKey = JSON.stringify({
                context: contextKey(discoverContext().context)
            });
            const cacheIsFresh = extractionCache?.key === cacheKey &&
                Date.now() - extractionCache.at < 60000;
            if (!cacheIsFresh) {
                if (!extractionPromise || extractionPromiseKey !== cacheKey) {
                    extractionPromiseKey = cacheKey;
                    let currentPromise;
                    currentPromise = extractAllDnoaData().then(data => {
                        extractionCache = { key: cacheKey, data, at: Date.now() };
                        return data;
                    }).finally(() => {
                        if (extractionPromise === currentPromise) {
                            extractionPromise = null;
                            extractionPromiseKey = null;
                        }
                    });
                    extractionPromise = currentPromise;
                }
            }
            const pending = cacheIsFresh
                ? Promise.resolve(extractionCache.data)
                : extractionPromise;
            pending.then(data => sendResponse({ ok: true, data })).catch(error => {
                sendResponse({
                    ok: false,
                    error: {
                        code: error.code || "EXTRACTION_FAILED",
                        message: cleanText(error.message) || "DNOA extraction failed"
                    },
                    diagnostics: error.diagnostics || null
                });
            });
            return true;
        });
    }

    getResourceUrls();
    installContextObservers();
    installMessageHandler();
})();
