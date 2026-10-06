window.__content_aetna_loaded = true;
console.log("[Aetna] content script loaded on: " + window.location.href);

const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');

// ══════════════════════════════════════════════════════════════════════════
// CLAIMCONNECT CRAWL FLOW — manual member selection -> procedure search -> results
// Existing extraction/output behavior below is intentionally kept intact.
// ══════════════════════════════════════════════════════════════════════════

const PROCEDURE_CODES = [
    "D0220","D0120","D0140","D0150","D0210","D0330","D0274","D1110","D1206",
    "D1208","D1351","D1510","D2160","D2391","D2740","D2950","D2980","D3310",
    "D4260","D4341","D4346","D4355","D4381","D4910","D5110","D5212","D5899",
    "D6010","D6750","D7140","D7210","D9110","D9230","D9243","D9944","D5995",
    "D6057","D6058","D9310","D8080","D8090"
];

const CLAIMCONNECT_CRAWL_KEY = "__claimconnect_aetna_crawl_state_v1";

function _getCrawlState() {
    try {
        return JSON.parse(sessionStorage.getItem(CLAIMCONNECT_CRAWL_KEY) || "{}") || {};
    } catch (e) {
        console.warn("[Aetna] Could not read crawl state", e);
        return {};
    }
}

function _saveCrawlState(state) {
    sessionStorage.setItem(CLAIMCONNECT_CRAWL_KEY, JSON.stringify(state || {}));
}

function _clearCrawlState() {
    sessionStorage.removeItem(CLAIMCONNECT_CRAWL_KEY);
}

function _waitFor(selector, timeoutMs) {
    timeoutMs = timeoutMs || 15000;
    return new Promise(function(resolve, reject) {
        var existing = document.querySelector(selector);
        if (existing) return resolve(existing);

        var done = false;
        var observer = new MutationObserver(function() {
            var el = document.querySelector(selector);
            if (el && !done) {
                done = true;
                observer.disconnect();
                clearTimeout(timer);
                resolve(el);
            }
        });

        observer.observe(document.documentElement, { childList: true, subtree: true });
        var timer = setTimeout(function() {
            if (done) return;
            done = true;
            observer.disconnect();
            reject(new Error("Timed out waiting for " + selector));
        }, timeoutMs);
    });
}

function _legendByText(text) {
    var legends = document.querySelectorAll("legend");
    for (var i = 0; i < legends.length; i++) {
        if (clean(legends[i].textContent).toLowerCase() === text.toLowerCase()) return legends[i];
    }
    return null;
}

function _tableBelowLegend(text) {
    var legend = _legendByText(text);
    if (!legend) return null;
    var container = legend.parentElement;
    return container ? container.querySelector("table") : null;
}

function _keyFromLabel(label) {
    return clean(label).replace(/:$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}

function _extractLabeledTable(legendText) {
    var table = _tableBelowLegend(legendText);
    var result = {};
    if (!table) return result;

    var rows = table.querySelectorAll("tr");
    rows.forEach(function(row) {
        var cells = Array.from(row.querySelectorAll(":scope > td"));
        for (var i = 0; i < cells.length; i++) {
            var bolds = cells[i].querySelectorAll("b");
            if (!bolds.length) continue;

            bolds.forEach(function(bold) {
                var label = clean(bold.textContent);
                if (!label) return;
                var value = "";

                // Standard ClaimConnect layout: label is in one cell and its
                // value is in the immediately following cell.
                if (bolds.length === 1 && clean(cells[i].textContent) === label && cells[i + 1]) {
                    value = clean(cells[i + 1].textContent);
                } else {
                    // Coverage Details nests Plan Number / Network Type as
                    // adjacent divs inside the same table cell.
                    var labelContainer = bold.parentElement;
                    if (labelContainer && labelContainer.nextElementSibling) {
                        value = clean(labelContainer.nextElementSibling.textContent);
                    }
                }

                if (value) result[_keyFromLabel(label)] = value;
            });
        }
    });

    return result;
}

function _extractStartPage() {
    var subscriber = {};
    var members = [];

    var summaryTables = document.querySelectorAll("table");
    summaryTables.forEach(function(table) {
        var text = clean(table.textContent);
        if (!text.includes("Employee Name:") || !text.includes("Subscriber Member ID or SSN:")) return;
        var cells = table.querySelectorAll("td");
        cells.forEach(function(cell) {
            var cellText = clean(cell.textContent);
            if (cellText.startsWith("Employee Name:")) {
                subscriber.name = clean(cellText.replace(/^Employee Name:\s*/i, ""));
            }
            if (cellText.startsWith("Subscriber Member ID or SSN:")) {
                subscriber.member_id_or_ssn = clean(cellText.replace(/^Subscriber Member ID or SSN:\s*/i, ""));
            }
        });
    });

    var memberTable = null;
    document.querySelectorAll("table").forEach(function(table) {
        var header = clean((table.querySelector("thead") || {}).textContent || "");
        if (header.includes("Name") && header.includes("Relationship") && header.includes("Group/Policy")) {
            memberTable = table;
        }
    });

    if (memberTable) {
        memberTable.querySelectorAll("tbody tr").forEach(function(row) {
            var cells = row.querySelectorAll(":scope > td");
            if (cells.length < 5) return;
            var link = cells[0].querySelector("a");
            members.push({
                name: clean(cells[0].textContent),
                relationship: clean(cells[1].textContent),
                date_of_birth: clean(cells[2].textContent),
                group_policy_number: clean(cells[3].textContent),
                status: clean(cells[4].textContent),
                _link: link || null
            });
        });
    }

    return { subscriber: subscriber, members: members };
}

function _attachManualMemberSelection(members) {
    var selectable = members.filter(function(member) { return !!member._link; });
    if (!selectable.length) throw new Error("No selectable patient was found");

    selectable.forEach(function(member) {
        if (member._link.dataset.claimConnectCrawlerBound === "1") return;
        member._link.dataset.claimConnectCrawlerBound = "1";

        // The operator chooses the member. Capture that exact row before
        // ClaimConnect's existing Wicket click handler navigates away.
        member._link.addEventListener("click", function() {
            var state = _getCrawlState();
            state.running = true;
            state.stage = "selected_patient";
            state.selected_member = _publicMember(member);
            state.target_patient_name = member.name;
            state.selected_at = new Date().toISOString();
            _saveCrawlState(state);
        }, true);
    });
}

function _publicMember(member) {
    if (!member) return null;
    return {
        name: member.name,
        relationship: member.relationship,
        date_of_birth: member.date_of_birth,
        group_policy_number: member.group_policy_number,
        status: member.status
    };
}

function _isEligibilityResultsPage() {
    var text = document.body ? document.body.innerText : "";
    return text.includes("Click on a patient's name to view detailed information") &&
           text.includes("Relationship") && text.includes("Group/Policy #");
}

function _isPatientDetailsPage() {
    return !!_legendByText("Patient Information") && !!_legendByText("Benefits Search");
}

function _capturePatientDetails() {
    return {
        patient_information: _extractLabeledTable("Patient Information"),
        provider_details: _extractLabeledTable("Provider Details"),
        coverage_details: _extractLabeledTable("Coverage Details")
    };
}

function _setNativeValue(input, value) {
    var descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    if (descriptor && descriptor.set) descriptor.set.call(input, value);
    else input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
}

function _sleep(ms) {
    return new Promise(function(resolve) { setTimeout(resolve, ms); });
}

async function _activateProcedureInput(input) {
    // Match the working manual action: after the CSV is inserted, focus and
    // click the populated entry box once. This fires ClaimConnect's own
    // Wicket onclick handler without changing the entered procedure codes.
    try {
        input.scrollIntoView({ block: "center", inline: "nearest" });
    } catch (e) {
        // Older browsers may not support the options object.
        input.scrollIntoView();
    }

    input.focus();
    if (typeof input.setSelectionRange === "function") {
        var end = input.value.length;
        input.setSelectionRange(end, end);
    }

    input.click();

    // Give the Wicket click callback time to finish before submitting the
    // benefits form, just as a user naturally pauses between the two clicks.
    await _sleep(800);
}

async function _submitProcedureCodeSearch() {
    var radio = document.querySelector('input[name="selectContainer:searchOptionRadioGroup"][value="radio14"]');
    if (!radio) {
        var labels = Array.from(document.querySelectorAll("label"));
        var label = labels.find(function(el) { return clean(el.textContent) === "Procedure Code"; });
        if (label && label.htmlFor) radio = document.getElementById(label.htmlFor);
    }
    if (!radio) throw new Error("Procedure Code radio button was not found");

    if (!radio.checked) radio.click();

    var input = await _waitFor('input[name="selectContainer:procedureSelect:procedureCode"]', 15000);
    _setNativeValue(input, PROCEDURE_CODES.join(", "));
    await _activateProcedureInput(input);

    var form = input.closest("form");
    var viewButton = form ? Array.from(form.querySelectorAll("a,button,input[type=submit]")).find(function(el) {
        return clean(el.textContent || el.value) === "View Benefits";
    }) : null;

    if (!viewButton) throw new Error("View Benefits button was not found");

    var state = _getCrawlState();
    state.requested_procedure_codes = PROCEDURE_CODES.slice();
    state.stage = "submitted_procedure_codes";
    _saveCrawlState(state);

    viewButton.click();
}

async function continueAetnaCrawl() {
    if (window.__aetnaCrawlBusy) return;
    window.__aetnaCrawlBusy = true;

    try {
        if (_isEligibilityResultsPage()) {
            var start = _extractStartPage();
            var existingState = _getCrawlState();
            var state = {
                running: true,
                stage: "awaiting_manual_patient_selection",
                started_at: existingState.started_at || new Date().toISOString(),
                subscriber: start.subscriber,
                eligibility_members: start.members.map(_publicMember),
                selected_member: null,
                target_patient_name: null
            };
            _saveCrawlState(state);
            _attachManualMemberSelection(start.members);

            // Show a native browser message at the manual patient-selection step.
            // The operator closes the message and then clicks the required patient.
            window.alert("Select the patient you want to crawl.");

            console.log("[Aetna] Crawl ready. Select the required member manually.");
            return;
        }

        if (_isPatientDetailsPage()) {
            var detailsState = _getCrawlState();
            detailsState.running = true;
            detailsState.stage = "patient_details";
            Object.assign(detailsState, _capturePatientDetails());
            _saveCrawlState(detailsState);
            await _submitProcedureCodeSearch();
            return;
        }

        if (isBenefitsPage()) {
            var data = buildAetnaPayload();
            downloadAetnaJSON(data);
            _clearCrawlState();
            return;
        }

        throw new Error("This is not a supported ClaimConnect crawl page");
    } finally {
        // Navigation normally destroys this page. Resetting also allows a
        // manual retry when ClaimConnect rejects or does not navigate.
        setTimeout(function() { window.__aetnaCrawlBusy = false; }, 1000);
    }
}

// ══════════════════════════════════════════════════════════════════════════
// GUARD
// ══════════════════════════════════════════════════════════════════════════

function isBenefitsPage() {
    return document.body?.innerText?.includes("Service Level Benefits");
}

// ══════════════════════════════════════════════════════════════════════════
// PATIENT / PAYER / DATES
// ══════════════════════════════════════════════════════════════════════════

function getMultiTabValues(labelText) {
    var rows = document.querySelectorAll("tr");
    for (var i = 0; i < rows.length; i++) {
        var cells = rows[i].querySelectorAll("td");
        for (var j = 0; j < cells.length; j++) {
            var text = cells[j].innerText;
            if (text.includes(labelText)) {
                var parts = text.split("\t");
                var labels = parts[0].split("\n").map(function(s) { return s.trim(); });
                var values = parts[1] ? parts[1].split("\n").map(function(s) { return s.trim(); }) : [];
                var result = {};
                labels.forEach(function(l, idx) {
                    if (l) result[l.replace(":", "").toLowerCase().replace(/ /g, "_")] = values[idx] || "N/A";
                });
                return result;
            }
        }
    }
    return {};
}

// ══════════════════════════════════════════════════════════════════════════
// BENEFIT TABLES — legend-anchored, split by network
// ══════════════════════════════════════════════════════════════════════════
// Every benefit table sits under a legend that names its type and network:
//   <div class="well ...">
//     <legend class="legend">Co-Insurance - In Network</legend>
//     <div><table>...rows...</table></div>
//   </div>
//
// Types:    Maximums, Deductibles, Co-Insurance, Service Level Benefits
// Networks: "In Network", "In and Out of Network", "Out of Network"
//
// Output has two buckets, in_network and out_of_network. A row from an
// "In and Out of Network" table applies to both, so it goes into BOTH
// buckets. Each row keeps a "source" field ("in", "in_and_out", "out")
// so you can still tell which table it came from.
//
// A legend with a type but no network wording is treated as applying to
// both networks, with source "unlabeled".

function _legendKind(text) {
    if (/service\s+level\s+benefits/i.test(text)) return "service_level_benefits";
    if (/co-?\s*insurance/i.test(text))           return "co_insurance";
    if (/maximums?/i.test(text))                  return "maximums";
    if (/deductibles?/i.test(text))               return "deductibles";
    return null;
}

function _legendNetwork(text) {
    // "in and out of network" is checked FIRST, because "out of network"
    // is a plain substring of it.
    if (/in\s+and\s+out\s+of\s+network/i.test(text)) return "in_and_out";
    if (/out\s*of\s*network/i.test(text))            return "out";
    if (/in\s*network/i.test(text))                  return "in";
    return "unlabeled";
}

function _tableRowsUnderLegend(legendEl) {
    var container = legendEl.parentElement;
    var table = container ? container.querySelector("table") : null;
    return table ? Array.from(table.querySelectorAll("tr")) : [];
}

// Maximums / Deductibles: Type | Coverage | Amount | Remaining | Message
function _parseAmountRows(rows) {
    var out = [];
    rows.forEach(function(r) {
        var cells = r.querySelectorAll("td");
        if (cells.length < 4) return;
        var t = clean(cells[0].innerText);
        if (!t || t === "Type" || /^D\d{4}/.test(t)) return;
        out.push({
            type:      t,
            coverage:  clean(cells[1].innerText),
            amount:    clean(cells[2].innerText),
            remaining: clean(cells[3].innerText),
            message:   clean(cells[4] ? cells[4].innerText : "")
        });
    });
    return out;
}

// Co-Insurance: Type | Percentage (Pat% / Ins%)
function _parseCoInsuranceRows(rows) {
    var out = [];
    rows.forEach(function(r) {
        var cells = r.querySelectorAll("td");
        if (cells.length < 2) return;
        var t = clean(cells[0].innerText);
        if (!t || t === "Type") return;
        out.push({
            type:       t,
            percentage: clean(cells[1].innerText)
        });
    });
    return out;
}

// Service Level Benefits: Procedure Code | Percentage | Frequency & Limitations | Message
function _parseServiceRows(rows) {
    var out = [];
    for (var i = 0; i < rows.length; i++) {
        var text = rows[i].innerText.trim();
        var cols = rows[i].querySelectorAll("td");

        if (text.includes("Procedure Code") && text.includes("Percentage")) continue; // header
        if (text.includes("PAYMENT IS BASED")) break;                                // footer
        if (cols.length < 2) continue;

        var code = clean(cols[0].innerText);
        if (!code) continue;

        var freqText = cols[2] ? cols[2].innerText : "";
        var col3Text = cols[3] ? cols[3].innerText : "";
        var sharesMatch = col3Text.match(/Shares frequency with\s*([^\n]+)/i);
        out.push({
            procedure_code:         code,
            percentage_copay:       clean(cols[1].innerText),
            frequency:              (freqText.match(/Frequency:\s*([^\n]+)/) || [])[1] || "N/A",
            history:                (freqText.match(/History:\s*([^\n]+)/)   || [])[1] || "N/A",
            age_limit:              (freqText.match(/Age Limitation:\s*([^\n]+)/) || [])[1] || "N/A",
            shares_frequency_with:  sharesMatch ? clean(sharesMatch[1]) : "",
            message:                clean(col3Text)
        });
    }
    return out;
}

function _emptyBucket() {
    return { maximums: [], deductibles: [], co_insurance: [], service_level_benefits: [] };
}

function scrapeBenefitTables() {
    var inNet  = _emptyBucket();
    var outNet = _emptyBucket();
    var sectionsFound = [];

    document.querySelectorAll("legend").forEach(function(lg) {
        var text = clean(lg.textContent);
        var kind = _legendKind(text);
        if (!kind) return;

        var network = _legendNetwork(text);
        var rows = _tableRowsUnderLegend(lg);
        var parsed;
        if (kind === "service_level_benefits") parsed = _parseServiceRows(rows);
        else if (kind === "co_insurance")      parsed = _parseCoInsuranceRows(rows);
        else                                   parsed = _parseAmountRows(rows);

        parsed.forEach(function(row) { row.source = network; });
        sectionsFound.push({ legend: text, kind: kind, network: network, rows: parsed.length });

        var goesIn  = network !== "out";
        var goesOut = network !== "in";
        if (goesIn)  inNet[kind]  = inNet[kind].concat(parsed.map(function(r) { return Object.assign({}, r); }));
        if (goesOut) outNet[kind] = outNet[kind].concat(parsed.map(function(r) { return Object.assign({}, r); }));
    });

    return { in_network: inNet, out_of_network: outNet, sections_found: sectionsFound };
}

// ══════════════════════════════════════════════════════════════════════════
// PLAN LEVEL REMARKS
// Simple text rows that appear before the first benefit table header.
// ══════════════════════════════════════════════════════════════════════════

function scrapeRemarks() {
    var allRows = document.querySelectorAll("tr");
    var remarks = [];

    for (var i = 0; i < allRows.length; i++) {
        var text = allRows[i].innerText.trim();
        var cols = allRows[i].querySelectorAll("td");

        // Stop at the first benefit table header of any kind
        var isSvcHeader = text.includes("Procedure Code") && text.includes("Percentage") &&
                          text.includes("Frequency") && text.includes("Message");
        var isCoHeader  = text.includes("Type") && text.includes("Pat%") && !text.includes("Procedure");
        var isAmtHeader = text.includes("Type") && text.includes("Coverage") && text.includes("Amount") &&
                          text.includes("Remaining") && text.includes("Message");
        if (isSvcHeader || isCoHeader || isAmtHeader) break;

        if (cols.length <= 1 && text.length > 3 &&
            !text.includes("Patient") && !text.includes("Payer") &&
            !text.includes("Dates") && !text.includes("Plan Begin") &&
            !text.includes("Information Type") && !text.includes("Related Entity") &&
            !text.includes("Name:") && !text.includes("Address:") &&
            !text.includes("Type") && text !== "Plan Level Remarks") {
            remarks.push(text);
        }
    }

    return remarks;
}

// ══════════════════════════════════════════════════════════════════════════
// BUILD FULL PAYLOAD
// ══════════════════════════════════════════════════════════════════════════

function buildAetnaPayload() {
    var bt = scrapeBenefitTables();
    var st = _getCrawlState();
    return {
        source:    "ClaimConnect - Extended Plan Benefits",
        timestamp: new Date().toISOString(),
        patient:   getMultiTabValues("Member ID or SSN:"),
        payer:     getMultiTabValues("Coverage:"),
        dates:     getMultiTabValues("Plan Begin:"),
        subscriber:              st.subscriber || {},
        eligibility_members:     st.eligibility_members || [],
        selected_member:         st.selected_member || null,
        patient_information:     st.patient_information || {},
        provider_details:        st.provider_details || {},
        coverage_details:        st.coverage_details || {},
        requested_procedure_codes: st.requested_procedure_codes || PROCEDURE_CODES.slice(),
        plan_level_remarks:      scrapeRemarks(),
        in_network:              bt.in_network,      // In Network + In and Out of Network tables
        out_of_network:          bt.out_of_network,  // Out of Network + In and Out of Network tables
        sections_found:          bt.sections_found   // which legends were read, for checking
    };
}

// ══════════════════════════════════════════════════════════════════════════
// DOWNLOAD
// ══════════════════════════════════════════════════════════════════════════

function downloadAetnaJSON(data) {
    var patientName = (data.patient && data.patient.name
        ? data.patient.name : "patient")
        .replace(/[^a-z0-9]/gi, "_").toLowerCase();
    var blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = patientName + "_aetna_benefits.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

// ══════════════════════════════════════════════════════════════════════════
// INIT — expose scrape+download function for popup to trigger
// ══════════════════════════════════════════════════════════════════════════

window.__aetnaDownload = function() {
    return continueAetnaCrawl().catch(function(error) {
        console.error("[Aetna] Crawl failed:", error);
        window.__aetnaCrawlBusy = false;
        throw error;
    });
};

// Optional clearer alias; the existing popup can continue using
// window.__aetnaDownload() without any changes.
window.__claimConnectCrawl = window.__aetnaDownload;
window.__claimConnectProcedureCodes = PROCEDURE_CODES.slice();

// Continue automatically after Wicket navigates to the next crawl page.
setTimeout(function() {
    var state = _getCrawlState();
    if (state.running && !_isEligibilityResultsPage()) {
        continueAetnaCrawl().catch(function(error) {
            console.error("[Aetna] Automatic crawl continuation failed:", error);
            window.__aetnaCrawlBusy = false;
        });
    }
}, 500);