/* ─────────────────────────────────────────────────────────────
   match.js  —  AI Insurance Plan Matcher  (UI Logic)
   Handles: file loading, API calls, renderMatch, renderNotes
───────────────────────────────────────────────────────────── */

const CRITICAL_FIELDS = [
    'individual_annual_max', 'ortho_lifetime_max',
    'major_D2740_pct', 'ortho_D8080_pct', 'ortho_D8080_age',
    'basic_D2331_D2140_pct', 'preventative_D0120_pct'
];

let portalData   = null;
let denticonData = null;
let lastNotesText = '';

/* Same origin — the page is always served by the FastAPI backend. */
const API_BASE = '';

/* ── DOM refs ── */
const filePortal    = document.getElementById('filePortal');
const fileDenticon  = document.getElementById('fileDenticon');
const btnMatch      = document.getElementById('btnMatch');
const btnNotes      = document.getElementById('btnNotes');
const matchOutput   = document.getElementById('matchOutput');
const matchLoader   = document.getElementById('matchLoader');
const notesLoader   = document.getElementById('notesLoader');
const notesPanel    = document.getElementById('notesPanel');

/* ══════════════════════════════════════════════════════════
   FILE LOADING
══════════════════════════════════════════════════════════ */
function handleFile(event, type) {
    const file = event.target.files[0];
    if (!file) return;

    const isPdf = file.type === 'application/pdf'
        || file.name.toLowerCase().trim().endsWith('.pdf');
    if (type === 'portal' && isPdf) {
        handlePdfUpload(file);
        return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const parsed = JSON.parse(e.target.result);
            if (type === 'portal') {
                portalData = parsed;
                document.getElementById('statusPortal').innerText = '✅ Loaded successfully';
                document.getElementById('statusPortal').style.color = '#00e676';
                document.getElementById('boxPortal').classList.add('ready');
            } else {
                denticonData = parsed;
                const count = parsed.denticon_data?.total_captured
                    || parsed.total_captured || parsed.length || '?';
                document.getElementById('statusDenticon').innerText = `✅ Loaded (${count} plans)`;
                document.getElementById('statusDenticon').style.color = '#00e676';
                document.getElementById('boxDenticon').classList.add('ready');
            }
            refreshButtons();
        } catch {
            alert(`Error parsing ${type} JSON. Make sure it is a valid JSON file.`);
        }
    };
    reader.readAsText(file);
}

async function handlePdfUpload(file) {
    document.getElementById('statusPortal').innerText = '⏳ Parsing PDF with AI...';
    document.getElementById('statusPortal').style.color = '#ffab40';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/api/parse-pdf`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            // Try to get the server's detailed error message
            let detail = 'Failed to parse PDF.';
            try {
                const errBody = await response.json();
                detail = errBody.detail || detail;
            } catch (_) {}
            throw new Error(`Server error ${response.status}: ${detail}`);
        }
        
        const parsed = await response.json();
        portalData = parsed;
        document.getElementById('statusPortal').innerText = '✅ PDF Parsed successfully';
        document.getElementById('statusPortal').style.color = '#00e676';
        document.getElementById('boxPortal').classList.add('ready');
        refreshButtons();
    } catch (err) {
        console.error(err);
        document.getElementById('statusPortal').innerText = '❌ Error parsing PDF';
        document.getElementById('statusPortal').style.color = '#ff5252';
        alert(`Error parsing PDF:\n\n${err.message}`);
    }
}

function refreshButtons() {
    const both = !!(portalData && denticonData);
    btnMatch.disabled = !both;
    btnNotes.disabled = !both;
}

filePortal.addEventListener('change',   e => handleFile(e, 'portal'));
fileDenticon.addEventListener('change', e => handleFile(e, 'denticon'));

/* ══════════════════════════════════════════════════════════
   AI PLAN MATCHING
══════════════════════════════════════════════════════════ */
btnMatch.addEventListener('click', async () => {
    matchOutput.innerHTML = '';
    matchLoader.classList.add('visible');
    btnMatch.disabled = true;

    /* Send the FULL raw portal JSON — backend unwraps metlife_data / cigna_data internally */
    const payload = {
        portal_data:   portalData,
        denticon_data: denticonData.denticon_data || denticonData,
    };

    try {
        const response = await fetch(`${API_BASE}/api/match`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok)
            throw new Error('Backend error. Is FastAPI running on port 8000?');
        const result = await response.json();
        console.log('[match result]', result);   // handy for debugging
        renderMatch(result);
    } catch (err) {
        console.error(err);
        matchOutput.innerHTML =
            `<div class="result-card match-fail" style="color:#ff5252;font-weight:bold;">
                Connection Error: ${err.message}
             </div>`;
    } finally {
        matchLoader.classList.remove('visible');
        refreshButtons();
    }
});

/* ══════════════════════════════════════════════════════════
   HELPERS — build ranked plan rows
══════════════════════════════════════════════════════════ */
function scoreColor(score) {
    if (score >= 80) return '#00e676';
    if (score >= 50) return '#ffab40';
    return '#ff5252';
}

function buildMismatchLines(mismatches) {
    if (!mismatches || mismatches.length === 0)
        return '<div class="plan-no-mismatch">✓ No mismatches detected</div>';

    const lines = mismatches.map(raw => {
        // mismatches can be strings (Python path) OR objects (AI path) — normalise both
        const m      = typeof raw === 'string' ? raw : JSON.stringify(raw);
        const isCrit = CRITICAL_FIELDS.some(f => m.includes(f));
        const dot    = isCrit
            ? `<span style="color:#ff7043;">▸</span>`
            : `<span style="color:#ffcc80;">▸</span>`;
        return `${dot} ${m}`;
    }).join('<br>');

    return `<div class="plan-mismatches">${lines}</div>`;
}

function buildRankedTable(plans) {
    if (!plans || plans.length === 0) return '';

    // Group plans by confidence_score to detect ties
    const scoreGroups = {};
    plans.forEach(p => {
        const s = p.confidence_score;
        if (!scoreGroups[s]) scoreGroups[s] = [];
        scoreGroups[s].push(p.plan_id);
    });

    const tiedGroups = Object.entries(scoreGroups)
        .filter(([, ids]) => ids.length > 1);

    const tiedPlanIds = new Set(tiedGroups.flatMap(([, ids]) => ids));

    // Build tie warning banner
    let tieWarningHtml = '';
    if (tiedGroups.length > 0) {
        const tieItems = tiedGroups.map(([score, ids]) => {
            const idList = ids.map(id => `<strong>#${id}</strong>`).join(', ');
            return `<div class="tie-item">Plans ${idList} share <span class="tie-score">${score}%</span> — check these manually</div>`;
        }).join('');
        tieWarningHtml = `
        <div class="tie-warning">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="flex-shrink:0;color:#ff9800;">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <div>
                <div class="tie-warning-title">Tied Probabilities — Manual Review Required</div>
                ${tieItems}
            </div>
        </div>`;
    }

    const rows = plans.map((p, i) => {
        const color  = scoreColor(p.confidence_score);
        const badge  = i === 0
            ? `<span class="rank-badge-best">BEST</span>`
            : `<span class="rank-badge-num">#${i + 1}</span>`;
        const crit   = p.critical_mismatches > 0
            ? `<span class="crit-badge">${p.critical_mismatches} critical</span>`
            : '';
        const tieBadge = tiedPlanIds.has(p.plan_id)
            ? `<span class="tie-badge">TIE</span>`
            : '';

        return `
        <div class="plan-row${tiedPlanIds.has(p.plan_id) ? ' plan-row-tied' : ''}">
            <div class="plan-row-top">
                ${badge}
                <span class="plan-row-name">Plan #${p.plan_id}</span>
                ${crit}
                ${tieBadge}
                <div class="score-bar-wrap">
                    <div class="score-bar-track">
                        <div class="score-bar-fill" style="width:${p.confidence_score}%;background:${color};"></div>
                    </div>
                </div>
                <span class="score-label" style="color:${color};">${p.confidence_score}%</span>
            </div>
            ${buildMismatchLines(p.mismatches)}
        </div>`;
    }).join('');

    return `
    <div class="ranked-plans">
        <div class="ranked-plans-header">
            All Plans Evaluated
            <span class="divider"></span>
            <span>${plans.length} plan${plans.length !== 1 ? 's' : ''}</span>
        </div>
        ${tieWarningHtml}
        ${rows}
    </div>`;
}

/* ══════════════════════════════════════════════════════════
   RENDER MATCH — 3 states: match / closest / fail
══════════════════════════════════════════════════════════ */
function renderMatch(result) {
    const allPlans = result.all_plans_ranked || [];

    /* ── 1. CONFIDENT MATCH ── */
    if (result.match_found) {
        matchOutput.innerHTML = `
        <div class="result-card match-success">
            <h2 style="color:#00e676;margin-top:0;display:flex;align-items:center;gap:10px;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                Direct Match Identified
            </h2>
            <div class="plan-id">Matched Plan ID: #${result.matching_id}</div>
            <div class="confidence">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                AI Confidence Score: ${result.confidence_score}%
            </div>
            <div class="reason-box">
                <strong style="color:#fff;">ID Comparison &amp; Reasoning:</strong><br>${result.reason}
            </div>
            ${buildRankedTable(allPlans)}
        </div>`;
        return;
    }

    /* ── 2. CLOSEST / PARTIAL MATCH ── */
    if (result.closest_plan_id) {
        const conf      = result.closest_confidence || 0;
        const barColor  = scoreColor(conf);
        const closeMismatches = result.closest_mismatches || [];

        const mismatchListHtml = closeMismatches.length
            ? closeMismatches.map(raw => {
                // normalise: AI can return objects, Python returns strings
                const m      = typeof raw === 'string' ? raw : JSON.stringify(raw);
                const isCrit = CRITICAL_FIELDS.some(f => m.includes(f));
                return `<li style="color:${isCrit ? '#ff7043' : '#ffcc80'};margin-bottom:4px;">
                            ${isCrit ? '🔴' : '🟡'} ${m}
                        </li>`;
              }).join('')
            : '<li style="color:#a0aabf;">No specific mismatches listed.</li>';

        matchOutput.innerHTML = `
        <div class="result-card match-warn">

            <!-- Banner -->
            <div class="warn-banner">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ffab40" stroke-width="2.5">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                    <line x1="12" y1="9" x2="12" y2="13"/>
                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                <span>Review Required — No Confident Match Found</span>
            </div>

            <h2 style="color:#ffab40;margin-top:0;display:flex;align-items:center;gap:10px;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                Closest Match Found
            </h2>

            <!-- Stat chips -->
            <div class="stat-chips">
                <div class="stat-chip" style="background:rgba(255,171,64,0.12);border:1px solid rgba(255,171,64,0.3);">
                    <div class="stat-chip-label" style="color:#ffab40;">Closest Plan ID</div>
                    <div class="stat-chip-value" style="color:#fff;">#${result.closest_plan_id}</div>
                </div>
                <div class="stat-chip" style="background:rgba(255,171,64,0.08);border:1px solid rgba(255,171,64,0.2);">
                    <div class="stat-chip-label" style="color:#ffab40;">Similarity Score</div>
                    <div class="stat-chip-value" style="color:#ffab40;">${conf}%</div>
                </div>
                <div class="stat-chip-bar-wrap">
                    <div class="stat-chip-bar-label">Match confidence</div>
                    <div class="stat-chip-bar-track">
                        <div class="stat-chip-bar-fill"
                             style="width:${conf}%;background:linear-gradient(90deg,#ff6f00,#ffab40);">
                        </div>
                    </div>
                </div>
            </div>

            <!-- Explanation -->
            <div style="background:rgba(0,0,0,0.25);border-radius:10px;padding:14px 16px;margin-bottom:16px;font-size:13px;line-height:1.6;color:#c0c8dc;">
                <strong style="color:#ffab40;">What this means:</strong>
                Plan <strong style="color:#fff;">#${result.closest_plan_id}</strong> is the
                most similar plan in Denticon but does <em>not</em> fully match the insurance portal.
                The fields listed below differ and should be manually reviewed before confirming this plan.
            </div>

            <!-- Mismatch list -->
            <div class="mismatch-section-label">Fields That Differ</div>
            <ul class="mismatch-list">${mismatchListHtml}</ul>

            <!-- Reason -->
            <div class="reason-box" style="border-color:rgba(255,171,64,0.2);background:rgba(255,171,64,0.05);">
                <strong style="color:#ffab40;">AI Reasoning:</strong><br>${result.reason}
            </div>

            ${buildRankedTable(allPlans)}
        </div>`;
        return;
    }

    /* ── 3. COMPLETE FAILURE ── */
    matchOutput.innerHTML = `
    <div class="result-card match-fail">
        <h2 style="color:#ff5252;margin-top:0;display:flex;align-items:center;gap:10px;">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            No Match Found
        </h2>
        <div class="reason-box">
            <strong style="color:#fff;">AI Reasoning:</strong><br>${result.reason}
        </div>
        ${buildRankedTable(allPlans)}
    </div>`;
}

/* ══════════════════════════════════════════════════════════
   PATIENT NOTES
══════════════════════════════════════════════════════════ */
btnNotes.addEventListener('click', async () => {
    notesPanel.classList.remove('visible');
    notesLoader.classList.add('visible');
    btnNotes.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/patient-notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                denticon_data: denticonData.denticon_data || denticonData,
                insurance_data: portalData,
            }),
        });
        if (!res.ok)
            throw new Error('Server error ' + res.status + '. Is FastAPI running on port 8000?');
        renderNotes(await res.json());
    } catch (err) {
        console.error(err);
        const errDiv = document.createElement('div');
        errDiv.className = 'result-card match-fail';
        errDiv.style.cssText = 'color:#ff5252;font-weight:bold;margin-top:16px;';
        errDiv.textContent = '❌ ' + err.message;
        document.querySelector('.card').appendChild(errDiv);
    } finally {
        notesLoader.classList.remove('visible');
        refreshButtons();
    }
});

function renderNotes(d) {
    const h = d.history;
    const rows = [
        { section: 'BASIC INFORMATION' },
        { label: 'Appointment Date',          value: d.appointment_date,       type: 'date' },
        { label: 'Verified By',                value: '',                        type: 'blank' },
        { label: 'Verification Date',          value: d.verification_date,      type: 'date' },
        { label: 'Eligibility Status',         value: d.eligibility_status },
        { label: 'Carrier',                    value: d.carrier },
        { label: 'Primary or Secondary',       value: d.primary_secondary },
        { label: 'Plan Type',                  value: d.plan_type },
        { label: 'Patient Assigned to Office', value: d.patient_assigned_to_office },
        { section: 'FINANCIALS' },
        { label: 'Individual Maximum (Used) $',    value: d.individual_maximum_used,    type: 'money' },
        { label: 'Individual Deductible (Used) $', value: d.individual_deductible_used, type: 'money' },
        { label: 'Ortho Maximum (Used) $',         value: d.ortho_maximum_used,         type: 'money' },
        { section: 'PROCEDURE HISTORY' },
        { label: 'History: Periodic Exam D0120',     value: h.periodic_exam_d0120,    type: 'date' },
        { label: 'History: Comp Exam D0150',         value: h.comp_exam_d0150,        type: 'date' },
        { label: 'History: Prophy D1110',            value: h.prophy_d1110,           type: 'date' },
        { label: 'History: Perio Maint D4910',       value: h.perio_maint_d4910,      type: 'date' },
        { label: 'History: FMD D4355',               value: h.fmd_d4355,              type: 'date' },
        { label: 'History: Fluoride D1206, D1208',   value: h.fluoride_d1206_d1208,   type: 'date' },
        { label: 'History: X-ray D0274',             value: h.xray_d0274,             type: 'date' },
        { label: 'History: X-ray D0210',             value: h.xray_d0210,             type: 'date' },
    ];

    const table = document.getElementById('notesTable');
    table.innerHTML = '';
    rows.forEach(row => {
        const tr = document.createElement('tr');
        if (row.section) {
            tr.className = 'tbl-section';
            tr.innerHTML = `<td colspan="2">${row.section}</td>`;
        } else {
            const isBlank   = row.type === 'blank';
            const isNH      = !isBlank && (row.value === 'NH' || !row.value);
            const cls       = isBlank ? '' : isNH ? 'nh' : (row.type || '');
            const display   = isBlank ? '' : (row.value || 'NH');
            tr.innerHTML = `<td class="label">${row.label} —</td><td class="value ${cls}">${display}</td>`;
        }
        table.appendChild(tr);
    });

    document.getElementById('toolbarName').textContent = d.patient_name || 'Patient Notes';
    document.getElementById('toolbarDate').textContent = 'Generated ' + new Date().toLocaleDateString('en-US');
    lastNotesText = buildPlainText(d);
    notesPanel.classList.add('visible');
    notesPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function buildPlainText(d) {
    const h   = d.history;
    const pad = (l, v) => l.padEnd(44) + (v || '');
    return [
        pad('Appointment Date -',              d.appointment_date),
        pad('Verified By -',                   ''),
        pad('Verification Date -',             d.verification_date),
        pad('Eligibility Status -',            d.eligibility_status),
        pad('Carrier -',                       d.carrier),
        pad('Primary or Secondary -',          d.primary_secondary),
        pad('Plan Type -',                     d.plan_type),
        pad('Patient Assigned to Office -',    d.patient_assigned_to_office),
        pad('Individual Maximum (Used) $',     d.individual_maximum_used),
        pad('Individual Deductible (Used) $',  d.individual_deductible_used),
        pad('Ortho Maximum (Used) $',          d.ortho_maximum_used),
        pad('History: Periodic Exam D0120 -',  h.periodic_exam_d0120),
        pad('History: Comp Exam D0150 -',      h.comp_exam_d0150),
        pad('History: Prophy D1110 -',         h.prophy_d1110),
        pad('History: Perio Maint D4910 -',    h.perio_maint_d4910),
        pad('History: FMD D4355 -',            h.fmd_d4355),
        pad('History: Fluoride D1206, D1208 -', h.fluoride_d1206_d1208),
        pad('History: X-ray D0274 -',          h.xray_d0274),
        pad('History: X-ray D0210 -',          h.xray_d0210),
    ].join('\n');
}

/* ── copy & download ── */
document.getElementById('btnCopy').addEventListener('click', () => {
    navigator.clipboard.writeText(lastNotesText).then(() => {
        const btn = document.getElementById('btnCopy');
        btn.textContent = '✔ Copied!';
        setTimeout(() => btn.textContent = '⎘ Copy', 2000);
    });
});

document.getElementById('btnDownload').addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([lastNotesText], { type: 'text/plain' }));
    a.download = 'patient_notes.txt';
    a.click();
});
