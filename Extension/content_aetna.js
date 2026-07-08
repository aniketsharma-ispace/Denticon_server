// content_aetna.js
// Scrapes ClaimConnect Extended Plan Benefits page
// Floating button approach — no chrome.runtime needed (blocked by CSP)

window.__content_aetna_loaded = true;
console.log("[Aetna] content script loaded on: " + window.location.href);

const clean = (s) => (s || "").trim().replace(/\s+/g, ' ');

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
// MAIN TABLE SCRAPER
// Single pass through all rows, categorizing by section
// ══════════════════════════════════════════════════════════════════════════

function scrapeTables() {
    var allRows = document.querySelectorAll("tr");
    var remarks = [];
    var maxRows = [];
    var dedRows = [];
    var coRows  = [];
    var svcRows = [];

    // State machine
    var section = "none";
    var maxHeaderCount = 0; // count how many times we've seen the max/ded header

    for (var i = 0; i < allRows.length; i++) {
        var text = allRows[i].innerText.trim();
        var cols = allRows[i].querySelectorAll("td");

        // ── Section headers ──────────────────────────────────────────────

        // 4-column service level table (the real one with percentages)
        if (text.includes("Procedure Code") &&
            text.includes("Percentage") &&
            text.includes("Frequency") &&
            text.includes("Message")) {
            section = "svc";
            continue;
        }

        // Stop service section at "PAYMENT IS BASED"
        if (section === "svc" && text.includes("PAYMENT IS BASED")) {
            section = "done";
            continue;
        }

        // Co-insurance header
        if (text.includes("Type") && text.includes("Pat%") && !text.includes("Procedure")) {
            section = "co";
            continue;
        }

        // Maximums/Deductibles share the same header — count occurrences
        if (text === "Type\tCoverage\tAmount\tRemaining\tMessage" ||
            (text.includes("Type") && text.includes("Coverage") && text.includes("Amount") &&
             text.includes("Remaining") && text.includes("Message") &&
             !text.includes("Procedure"))) {
            maxHeaderCount++;
            section = maxHeaderCount === 1 ? "max" : "ded";
            continue;
        }

        // Plan remarks — simple text rows before maximums
        if (section === "none" && cols.length <= 1 && text.length > 3 &&
            !text.includes("Patient") && !text.includes("Payer") &&
            !text.includes("Dates") && !text.includes("Plan Begin") &&
            !text.includes("Information Type") && !text.includes("Related Entity") &&
            !text.includes("Name:") && !text.includes("Address:") &&
            !text.includes("Type") && text !== "Plan Level Remarks") {
            remarks.push(text);
            continue;
        }

        // ── Data rows ────────────────────────────────────────────────────

        if (section === "max" && cols.length >= 4) {
            var t = clean(cols[0].innerText);
            if (t && !t.match(/^D\d{4}/)) { // skip if looks like procedure code
                maxRows.push({
                    type:      t,
                    coverage:  clean(cols[1].innerText),
                    amount:    clean(cols[2].innerText),
                    remaining: clean(cols[3].innerText),
                    message:   clean(cols[4] ? cols[4].innerText : "")
                });
            }
        }

        if (section === "ded" && cols.length >= 4) {
            var t2 = clean(cols[0].innerText);
            if (t2 && !t2.match(/^D\d{4}/)) {
                dedRows.push({
                    type:      t2,
                    coverage:  clean(cols[1].innerText),
                    amount:    clean(cols[2].innerText),
                    remaining: clean(cols[3].innerText),
                    message:   clean(cols[4] ? cols[4].innerText : "")
                });
            }
        }

        if (section === "co" && cols.length >= 2) {
            var ct = clean(cols[0].innerText);
            if (ct && !ct.includes("Type")) {
                coRows.push({
                    type:       ct,
                    percentage: clean(cols[1].innerText)
                });
            }
        }

        if (section === "svc" && cols.length >= 2) {
            var code = clean(cols[0].innerText);
            if (!code) continue;
            var freqText = cols[2] ? cols[2].innerText : "";
            svcRows.push({
                procedure_code:   code,
                percentage_copay: clean(cols[1].innerText),
                frequency:  (freqText.match(/Frequency:\s*([^\n]+)/) || [])[1] || "N/A",
                history:    (freqText.match(/History:\s*([^\n]+)/)   || [])[1] || "N/A",
                age_limit:  (freqText.match(/Age Limitation:\s*([^\n]+)/) || [])[1] || "N/A",
                message:    clean(cols[3] ? cols[3].innerText : "")
            });
        }
    }

    return { remarks, maxRows, dedRows, coRows, svcRows };
}

// ══════════════════════════════════════════════════════════════════════════
// BUILD FULL PAYLOAD
// ══════════════════════════════════════════════════════════════════════════

function buildAetnaPayload() {
    var t = scrapeTables();
    return {
        source:    "ClaimConnect - Extended Plan Benefits",
        timestamp: new Date().toISOString(),
        patient:   getMultiTabValues("Member ID or SSN:"),
        payer:     getMultiTabValues("Coverage:"),
        dates:     getMultiTabValues("Plan Begin:"),
        plan_level_remarks:     t.remarks,
        maximums:               t.maxRows,
        deductibles:            t.dedRows,
        co_insurance:           t.coRows,
        service_level_benefits: t.svcRows
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
    const data = buildAetnaPayload();
    downloadAetnaJSON(data);
};