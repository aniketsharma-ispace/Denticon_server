const DEBUG_MODE = true;
const dLog = (step, data) => {
    if (!DEBUG_MODE) return;
    console.log(`%c[DELTA AUDIT] ${step}`, 'color: #00ff00; font-weight: bold;', data || '');
};

const getTransactionId = () => crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
});

function getJwtToken() {
    let token = null;
    const stores = [window.sessionStorage, window.localStorage];
    let storeIndex = 0;
    
    // Explicit token checks for debug
    const hasProviderAccessToken = !!window.localStorage.getItem("provider_accesstoken");
    const hasProviderToken = !!window.localStorage.getItem("provider_token");
    dLog("Auth Artifact Search", { provider_accesstoken_found: hasProviderAccessToken, provider_token_found: hasProviderToken });

    for (const store of stores) {
        let storeName = storeIndex === 0 ? "SessionStorage" : "LocalStorage";
        storeIndex++;
        for (let i = 0; i < store.length; i++) {
            const key = store.key(i);
            const val = store.getItem(key);
            if (val && typeof val === 'string') {
                const match = val.match(/(eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)/);
                if (match) {
                    dLog("Auth Token Discovered", { store: storeName, key: key, prefix: match[0].substring(0, 15) + "..." });
                    token = match[0];
                }
            }
        }
    }
    return token;
}

async function apiFetch(endpoint, method = "GET", body = null) {
    const token = getJwtToken();
    const tid = getTransactionId();
    dLog("Transaction context generated", { transactionId: tid, transactionId_found: true });
    
    const headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "healthCareCompanyId": "1",
        "subcompanyId": "1",
        "transactionId": tid
    };
    
    if (token) {
        headers["Authorization"] = token;
    } else {
        dLog("Missing Authorization Token", "Proceeding with cookies only");
    }
    
    const opts = { method, headers, credentials: "include" };
    if (body) {
        opts.body = JSON.stringify(body);
    }
    
    dLog(`API Request: ${method} ${endpoint}`, { headers: headers });
    
    try {
        const response = await fetch(endpoint, opts);
        const text = await response.text();
        dLog(`API Response: ${method} ${endpoint}`, { status: response.status, size: text.length });
        if (!response.ok) return null;
        return text ? JSON.parse(text) : null;
    } catch (e) {
        dLog(`API Fetch Error: ${endpoint}`, e);
        return null;
    }
}

async function fetchMember(patientId) {
    dLog("Stage: Member Retrieval", { patientId });
    const url = `/provider/api/provider-experience/member?memberHccId=${patientId}`;
    const data = await apiFetch(url);
    if (!data) return null;
    
    return {
        patient_name: `${data.firstName || ""} ${data.lastName || ""}`.trim(),
        group_number: data.groupNumber,
        employer_group: data.accountInformation?.accountName,
        relationship: data.relationshipToSubscriber,
        plan_id: data.planInformation?.planId
    };
}

async function fetchFinancials(patientId, planId) {
    dLog("Stage: Accumulators Retrieval", { patientId, planId });
    const url = `/provider/api/provider-experience/member/accumulators?benefitPlanId=${planId}&memberHccId=${patientId}`;
    const data = await apiFetch(url);
    
    const financials = {};
    if (data && data.accumulators) {
        data.accumulators.forEach(acc => {
            const name = (acc.name || "").toLowerCase();
            const total = acc.definedAmount;
            
            if (name.includes("individual") && name.includes("deductible")) {
                financials.deductible_ind = { total };
            } else if (name.includes("family") && name.includes("deductible")) {
                financials.deductible_fam = { total };
            } else if (name.includes("individual") && name.includes("maximum") && !name.includes("orthodontic") && !name.includes("tmj")) {
                financials.annual_max = { total };
            } else if (name.includes("orthodontic") && name.includes("lifetime maximum")) {
                financials.ortho_lifetime = { total };
            }
        });
    }
    return financials;
}

async function fetchClaims(patientId) {
    dLog("Stage: Claims Retrieval", { patientId });
    const claimsUrl = `/provider/api/provider-experience/claim/memberClaims`;
    let allClaims = [];
    let pagination = 0;
    
    const start = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const end = new Date().toISOString().split('T')[0];
    
    const payload = {
        claimStatus: "All",
        dateRangeStart: start,
        dateRangeEnd: end,
        pagination: 0,
        memberHccId: patientId
    };
    
    while (true) {
        payload.pagination = pagination;
        dLog("Stage: Claims Pagination", { pagination, current_total: allClaims.length });
        const res = await apiFetch(claimsUrl, "POST", payload);
        if (!res || !res.claims || res.claims.length === 0) break;
        
        allClaims = allClaims.concat(res.claims);
        
        if (allClaims.length >= (res.count || 0)) break;
        pagination++;
    }
    dLog("Claims Retrieval Complete", { total_fetched: allClaims.length });
    return allClaims;
}

async function fetchHistory(patientId) {
    dLog("Stage: History Retrieval", { patientId });
    const historyUrl = `/provider/api/provider-experience/member/${patientId}/claimHistory/procedureLines`;
    const res = await apiFetch(historyUrl);
    dLog("History Retrieval Complete", { lines: res ? res.length : 0 });
    return res || [];
}

async function fetchCoverage(patientId, planId) {
    dLog("Stage: Coverage Retrieval", { patientId, planId });
    const coverageUrl = `/provider/api/provider-experience/member/coverage?benefitPlanId=${planId}&memberHccId=${patientId}`;
    const res = await apiFetch(coverageUrl);
    
    const procedures = [];
    if (res && Array.isArray(res)) {
        res.forEach(network => {
            if (network.benefitClassDetails) {
                network.benefitClassDetails.forEach(cls => {
                    if (cls.serviceCodeList) {
                        cls.serviceCodeList.forEach(codeObj => {
                            procedures.push({
                                procedure_code: codeObj.code,
                                benefit_level: cls.copay || "0%",
                                age_limit: cls.waitingPeriod || "N/A"
                            });
                        });
                    }
                });
            }
        });
    }
    dLog("Coverage Retrieval Complete", { parsed_procedures: procedures.length });
    return procedures;
}

async function crawlDeltaPatient() {
    dLog("Starting Delta Patient Crawl", { url: window.location.href });
    const urlParts = window.location.pathname.split('/');
    const patientId = urlParts[urlParts.length - 1];
    if (!patientId || patientId === "find-a-patient") {
        dLog("Error", "Could not detect patient ID in URL.");
        return { status: "[!] Could not detect patient ID in URL." };
    }

    const planDetails = await fetchMember(patientId);
    if (!planDetails || !planDetails.plan_id) {
        dLog("Error", "Failed to retrieve member demographics or plan_id.");
        return { status: "[!] Failed to retrieve member." };
    }

    const financials = await fetchFinancials(patientId, planDetails.plan_id);
    const claims = await fetchClaims(patientId);
    const history = await fetchHistory(patientId);
    const coverageProcs = await fetchCoverage(patientId, planDetails.plan_id);

    const payload = {
        source: "Delta Dental API",
        timestamp: new Date().toISOString(),
        plan_details: planDetails,
        patient: { relationship: planDetails.relationship },
        financials: financials,
        claims: claims,
        history: history
    };

    return new Promise((resolve) => {
        dLog("Stage: Storage Write", "Reading audit_context from chrome.storage");
        chrome.storage.local.get("audit_context", (res) => {
            const ctx = res.audit_context || {};
            ctx.delta_dental_data = payload;
            ctx.benefit_coverage = { procedures: coverageProcs };
            
            chrome.storage.local.set({ audit_context: ctx }, () => {
                dLog("Stage: Storage Write Complete", "Payload committed to storage");
                resolve({ status: `[+] Delta Dental payload built.` });
            });
        });
    });
}

function downloadAuditJSON() {
    dLog("Stage: Download Generation", "Initiating download");
    chrome.storage.local.get("audit_context", (res) => {
        const data = res.audit_context || {};
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement("a");
        a.href = url;
        
        const patientName = data?.delta_dental_data?.plan_details?.patient_name || "patient";
        const filename = `${patientName.replace(/[^a-z0-9]/gi, "_").toLowerCase()}_delta_audit.json`;
        a.download = filename;
        
        dLog("Stage: Download Triggered", { filename });
        document.body.appendChild(a);
        a.click();
        a.remove();
        
        URL.revokeObjectURL(url);
    });
}

function showLoader() {
    let loader = document.getElementById("delta-audit-loader");
    if (!loader) {
        loader = document.createElement("div");
        loader.id = "delta-audit-loader";
        loader.style.cssText = "position:fixed; top:20px; right:20px; background:#276299; color:white; padding:15px 25px; border-radius:8px; z-index:999999; font-family:sans-serif; font-weight:bold; box-shadow:0 4px 12px rgba(0,0,0,0.3); transition: opacity 0.3s;";
        document.body.appendChild(loader);
    }
    loader.innerText = "🔍 Scraping Delta Dental APIs... Please wait";
    loader.style.opacity = "1";
}

function hideLoader() {
    const loader = document.getElementById("delta-audit-loader");
    if (loader) {
        loader.innerText = "✅ Extraction Complete!";
        loader.style.background = "#00e676";
        setTimeout(() => {
            loader.style.opacity = "0";
            setTimeout(() => loader.remove(), 300);
        }, 2000);
    }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.command === "START_CRAWL") {
        dLog("Command Received", request.command);
        showLoader();
        (async () => {
            const res = await crawlDeltaPatient();
            downloadAuditJSON();
            hideLoader();
            sendResponse({ status: res.status + " JSON downloaded." });
        })();
        return true;
    }
});
