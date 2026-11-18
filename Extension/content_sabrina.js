// ============================================================================
// Sabrina Fill Form — "Fill from portal" panel (Insurance Auditor Pro)
//
// On Sabrina's Fill Form this adds a small panel. The user picks IN OR OON,
// clicks Fill from portal, and the form is filled from the portal scrape the
// extension sent to the server (scrape_delivery.js). Nothing is saved:
// the user reviews and clicks Save / Submit as always, which marks the scrape
// used so a later appointment never picks it up.
//
// All server calls go through the background (scrape_delivery.js).
// ============================================================================

(function () {
  if (window.__iapSabrinaPanel) return;
  window.__iapSabrinaPanel = true;

  // ── page helpers ──────────────────────────────────────────────────────────
  const byName = n => document.querySelector(`[name="${CSS.escape(n)}"]`);
  // Other names the same row or question has on another version of the Fill
  // Form (production vs UAT, 11/2026). Tried in order; a question whose
  // options lack the portal's answer is reported, never forced.
  const GRID_ALIASES = {
    D8080: ["Orthocoverage"],                                   // Ortho Coverage row
  };
  const QUESTION_ALIASES = {
    "ArePosteriorCrownsDowngraded?": ["PosteriorCrownsDowngradedTo"],
  };
  const firstByEnding = endings => {
    for (const end of endings) {
      const el = document.querySelector(`[name$="${CSS.escape(end)}" i]`);
      if (el) return el;
    }
    return null;
  };
  const gridEl = (code, col) =>
    firstByEnding([code, ...(GRID_ALIASES[code] || [])].map(c => `_${c}_${col}`));
  const questionEl = q =>
    firstByEnding([q, ...(QUESTION_ALIASES[q] || [])].map(x => `_${x}_covered`));
  const pageVal = n => (byName(n)?.value || "").trim();
  const normId = s => String(s || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  // A DOB as MM/DD/YYYY. A DOB is in the past, so '02/03/90' is 1990 (the same
  // rule as the server's scrape_store.norm_dob).
  const normDate = s => {
    const text = String(s || "").trim();
    const iso = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (iso) return `${iso[2]}/${iso[3]}/${iso[1]}`;
    const m = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
    if (!m) return "";
    const y = m[3].length === 2
      ? (+m[3] <= new Date().getFullYear() % 100 ? "20" : "19") + m[3]
      : m[3];
    return `${m[1].padStart(2, "0")}/${m[2].padStart(2, "0")}/${y}`;
  };
  // The Fill Form page itself, whether or not its sections are open yet.
  const onFillForm = () => /fillform/i.test(location.pathname);

  // ── opening collapsed sections ────────────────────────────────────────────
  // Sabrina leaves a collapsed section's inputs off the page, so they cannot
  // be filled until it is opened. Each section is found by its title and opened
  // only when one of its own fields is missing: a section that is already
  // open is never clicked (that would close it).
  const SECTIONS = [
    { title: "DEMOGRAPHIC",       probe: () => byName("demographic.memberId") },
    { title: "INSURANCE DETAILS", probe: () => byName("insuranceDetails.network") },
    { title: "BENEFIT INFO",      probe: () => byName("benefitsInfo.yearlyMaxUsed") },
    { title: "SPECIALITIES",      probe: () => document.querySelector('[name$="_D0120_percentage"],[name$="_frequency"]') },
  ];
  const visible = el => !!el && el.getClientRects().length > 0;
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function sectionHeader(title) {
    // The smallest element whose own text is the title, outside our panel.
    const want = title.toUpperCase();
    let best = null;
    for (const el of document.body.querySelectorAll("*")) {
      if (el.closest("#iap-sabrina-panel")) continue;
      const text = (el.innerText || "").trim().toUpperCase();
      if (text !== want) continue;
      if (!best || best.contains(el)) best = el;
    }
    return best;
  }

  // A full mouse click, as a user's would be: some pages listen for the
  // pointer/mouse events rather than for `click` alone.
  function realClick(el) {
    const r = el.getBoundingClientRect();
    const at = { bubbles: true, cancelable: true, view: window,
                 clientX: r.left + Math.min(10, r.width / 2), clientY: r.top + r.height / 2 };
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
      const E = type.startsWith("pointer") && window.PointerEvent ? PointerEvent : MouseEvent;
      el.dispatchEvent(new E(type, at));
    }
  }

  // What to try clicking for one section, most likely first: the title, the
  // header row around it, and any arrow / toggle icon in that row.
  function clickTargets(title) {
    const t = sectionHeader(title);
    if (!t) return [];
    const out = [t];
    let p = t.parentElement;
    for (let i = 0; i < 3 && p && p !== document.body; i++, p = p.parentElement) {
      out.push(p);
      // Icons by name first, then every other small element in the row (an
      // unnamed ▶ span counts) — but never a form field.
      const named = [...p.querySelectorAll('svg, i, img, [class*="arrow"], [class*="toggle"], [class*="icon"], [class*="caret"], [class*="chevron"]')];
      const rest = [...p.querySelectorAll("*")].filter(x => x.children.length === 0);
      [...named, ...rest].slice(0, 12)
        .forEach(x => { if (!out.includes(x) && !x.closest("input,select,textarea,button[type=submit]")) out.push(x); });
      // Stop at the section box: past it are other sections' headers.
      if (/card|panel|accordion|section/i.test(p.className || "")) break;
    }
    return out;
  }

  async function waitFor(check, ms) {
    for (let waited = 0; waited < ms; waited += 100) {
      if (check()) return true;
      await sleep(100);
    }
    return check();
  }

  // Which of the click targets opened a section last time; the sections share
  // one layout, so it is tried first on the next.
  let workedAt = 0;

  async function openSections() {
    const opened = [], failed = [];
    for (const s of SECTIONS) {
      if (visible(s.probe())) continue;
      const targets = clickTargets(s.title);
      if (!targets.length) { failed.push(s.title); continue; }
      targets[0].scrollIntoView({ block: "center" });
      const order = targets.map((el, i) => i);
      if (workedAt < targets.length) order.unshift(...order.splice(workedAt, 1));
      let ok = false;
      for (const i of order) {
        realClick(targets[i]);
        ok = await waitFor(() => visible(s.probe()), 1200);
        if (ok) { workedAt = i; break; }
      }
      (ok ? opened : failed).push(s.title);
    }
    return { opened, failed };
  }

  function send(message) {
    return new Promise(resolve => {
      try {
        chrome.runtime.sendMessage(message, reply => {
          if (chrome.runtime.lastError) resolve({ ok: false, error: chrome.runtime.lastError.message });
          else resolve(reply || { ok: false, error: "no answer from the extension" });
        });
      } catch (e) {
        resolve({ ok: false, error: String(e && e.message || e) });
      }
    });
  }

  // ── filling (same rules as tools/sabrina_fill_console.js) ─────────────────
  // Set a value the way a user's typing would: focus, keys, input, change,
  // leaving the field. Sabrina (React) keeps its own copy of each field and
  // works out others from it (INS PLAN NAME from the deductibles, max and %),
  // so a value it doesn't "see" being typed counts as missing on Save.
  const setVal = (el, v) => {
    const value = String(v);
    const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype
                : el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype
                : HTMLInputElement.prototype;
    const fire = (type, init = {}) => {
      const E = type.startsWith("key") ? KeyboardEvent
              : type.startsWith("focus") || type === "blur" ? FocusEvent
              : type === "input" ? InputEvent : Event;
      el.dispatchEvent(new E(type, Object.assign({ bubbles: type !== "focus" && type !== "blur", cancelable: true }, init)));
    };
    try { el.focus({ preventScroll: true }); } catch (_) { /* not focusable */ }
    fire("focus"); fire("focusin");
    // React compares against the last value it saw: make it see a change.
    const tracker = el._valueTracker;
    if (tracker) tracker.setValue(el.tagName === "SELECT" ? "" : "\u0000");
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    if (el.tagName !== "SELECT") fire("keydown", { key: value.slice(-1) || "Unidentified" });
    fire("input", { inputType: "insertText", data: value });
    if (el.tagName !== "SELECT") fire("keyup", { key: value.slice(-1) || "Unidentified" });
    fire("change");
    fire("blur"); fire("focusout");
    try { el.blur(); } catch (_) { /* nothing focused */ }
  };
  // Frequencies Sabrina may spell differently from the portal: Year / Years,
  // and the same span in months or years ("1X3Year" ↔ "1X3Years" ↔ "1X36Months").
  // Same wording first, then the equivalent.
  function frequencyForms(want) {
    const m = String(want).replace(/\s+/g, "").match(/^(\d+)X(\d+)(years?|months?|days?)$/i);
    if (!m) return [];
    const n = m[1], span = +m[2], unit = m[3].toLowerCase().replace(/s$/, "");
    const forms = [`${n}X${span}${unit}`];
    if (unit === "year") forms.push(`${n}X${span * 12}month`);
    if (unit === "month" && span % 12 === 0) forms.push(`${n}X${span / 12}year`);
    return forms;
  }

  const pickOption = (sel, want) => {
    const norm = s => String(s).toLowerCase().replace(/[\s%]/g, "");
    const opts = [...sel.options];
    const exact = opts.find(o => o.value === String(want))
               || opts.find(o => norm(o.value) === norm(want))
               || opts.find(o => norm(o.text) === norm(want));
    if (exact) return exact.value;
    // "1x3 years" and "1X3Year" read the same: drop spaces, case and a trailing s.
    const freqKey = s => norm(s).replace(/s$/, "");
    for (const form of frequencyForms(want)) {
      const hit = opts.find(o => freqKey(o.text) === freqKey(form) || freqKey(o.value) === freqKey(form));
      if (hit) return hit.value;
    }
    return undefined;
  };
  const isEmpty = el => !el.value || el.value === "--Select--";

  // What this panel wrote, per field, so switching In ↔ Out may overwrite our
  // own values but never one the user (or the PMS) entered.
  let written = {};

  function fillOne(el, value, key, label, overwrite, log) {
    if (!el) return log.push({ status: "not on this form", label, value });
    if (el.disabled || el.readOnly) return log.push({ status: "read-only", label, value });
    const ours = written[key] !== undefined && el.value === written[key];
    if (!isEmpty(el) && !overwrite && !ours) {
      if (normId(el.value) === normId(value)) return log.push({ status: "already same", label, value });
      return log.push({ status: "kept existing", label, value: `${el.value} (portal: ${value})` });
    }
    if (el.tagName === "SELECT") {
      const v = pickOption(el, value);
      if (v === undefined) return log.push({ status: "no matching option", label, value });
      setVal(el, v);
    } else {
      setVal(el, value);
    }
    written[key] = el.value;
    log.push({ status: "filled", label, value: el.value });
  }

  function applyPrefill(prefill, mode) {
    const existing = mode === "existing";
    const wanted = x => !existing || x.level === "appointment";
    const log = [];
    const isSelect = n => byName(n)?.tagName === "SELECT";
    // Dropdowns first: changing one can reset the amounts after it.
    (prefill.fields || []).filter(wanted)
      .sort((a, b) => (isSelect(a.name) ? 0 : 1) - (isSelect(b.name) ? 0 : 1))
      .forEach(f => fillOne(byName(f.name), f.value, f.name, f.label || f.name, existing && f.level === "appointment", log));
    (prefill.questions || []).filter(wanted)
      .forEach(q => fillOne(questionEl(q.question), q.value, "q:" + q.question, q.label || q.question, false, log));
    (prefill.grid || []).filter(wanted)
      .forEach(g => fillOne(gridEl(g.code, g.column), g.value, `g:${g.code}:${g.column}`,
                            `${g.code} ${g.column}`, existing && g.level === "appointment", log));
    // Boxes always ticked on a filled form (business team, 11/2026).
    ALWAYS_TICK.forEach(([name, label]) => tick(byName(name), label, log));
    return log;
  }

  const ALWAYS_TICK = [
    ["demographic.appointmentNote", "Appointment Note"],
    ["noteInfo.isOnline", "Mode of verification: Online"],   // the data came from a portal
  ];

  // A checkbox is ticked with a real click (only when it is not ticked yet):
  // React ignores a checkbox whose `checked` is changed silently.
  function tick(el, label, log) {
    if (!el) return log.push({ status: "not on this form", label, value: "ticked" });
    if (el.disabled) return log.push({ status: "read-only", label, value: "ticked" });
    if (el.checked) return log.push({ status: "already same", label, value: "ticked" });
    el.click();
    log.push({ status: el.checked ? "filled" : "not ticked", label, value: "ticked" });
  }

  // ── waiting period rows (Period · Months/Years · Applies To) ─────────────
  // The first row is on the form; "+ Add" makes more, whose field names we
  // don't rely on: each row's three dropdowns are recognized by their options.
  const optionTexts = s => [...s.options].map(o => o.text.trim().toLowerCase());
  const isPeriodSel = s => { const t = optionTexts(s); return t.includes("6") && t.includes("12"); };
  const isUnitSel = s => { const t = optionTexts(s).filter(x => x && x !== "--select--");
                           return t.length > 0 && t.every(x => x === "months" || x === "years"); };
  const isAppliesSel = s => { const t = optionTexts(s); return t.includes("basic") && t.includes("major"); };

  function waitingRows() {
    const rows = [];
    let cur = null;
    for (const s of document.querySelectorAll("select")) {
      if (s.closest("#iap-sabrina-panel")) continue;
      if (isPeriodSel(s)) cur = { period: s };
      else if (cur && !cur.unit && isUnitSel(s)) cur.unit = s;
      else if (cur && cur.unit && isAppliesSel(s)) { cur.applies = s; rows.push(cur); cur = null; }
    }
    return rows;
  }

  function addRowButton(after) {
    const buttons = [...document.querySelectorAll("button")]
      .filter(b => !b.closest("#iap-sabrina-panel") && /^\+?\s*add$/i.test((b.textContent || "").trim()));
    // The Add button that follows the waiting period rows.
    return buttons.find(b => after && (after.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING))
        || buttons[0] || null;
  }

  async function fillWaitingPeriods(wanted, log) {
    if (!wanted || !wanted.length) return;
    await waitFor(() => waitingRows().length && !waitingRows()[0].period.disabled, 1500);
    for (const w of wanted) {
      const label = `Waiting period ${w.applies_to}`;
      let rows = waitingRows();
      if (!rows.length) { log.push({ status: "not on this form", label, value: `${w.period} ${w.unit}` }); continue; }
      // A row already for this category, else an empty row, else a new one.
      let row = rows.find(r => (r.applies.value || "").toLowerCase() === w.applies_to.toLowerCase())
             || rows.find(r => isEmpty(r.applies) && isEmpty(r.period));
      if (!row) {
        const add = addRowButton(rows[rows.length - 1].applies);
        if (!add) { log.push({ status: "no Add button", label, value: `${w.period} ${w.unit}` }); continue; }
        add.click();
        const before = rows.length;
        if (!(await waitFor(() => waitingRows().length > before, 2000))) {
          log.push({ status: "row not added", label, value: `${w.period} ${w.unit}` });
          continue;
        }
        rows = waitingRows();
        row = rows[rows.length - 1];
      }
      fillOne(row.period, w.period, `wp:${w.applies_to}:period`, `${label}: period`, false, log);
      fillOne(row.unit, w.unit, `wp:${w.applies_to}:unit`, `${label}: months/years`, false, log);
      fillOne(row.applies, w.applies_to, `wp:${w.applies_to}:applies`, `${label}: applies to`, false, log);
    }
  }

  // ── panel ─────────────────────────────────────────────────────────────────
  let host, ui, applied = null, appliedNetwork = null;

  function buildPanel() {
    host = document.createElement("div");
    host.id = "iap-sabrina-panel";
    host.style.cssText = "position:fixed;left:16px;bottom:16px;z-index:2147483646";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { all: initial; }
        .box { width: 330px; font: 13px/1.45 system-ui, "Segoe UI", Arial, sans-serif; color: #1d2939;
               background: #fff; border: 1px solid #d0d5dd; border-radius: 10px;
               box-shadow: 0 8px 24px rgba(16,24,40,.18); overflow: hidden; }
        .head { display: flex; align-items: center; gap: 8px; padding: 9px 12px; background: #1f4e79; color: #fff;
                cursor: pointer; user-select: none; }
        .head b { flex: 1; font-size: 13px; }
        .body { padding: 10px 12px; display: grid; gap: 8px; }
        .collapsed .body { display: none; }
        .row { display: flex; justify-content: space-between; gap: 8px; }
        .muted { color: #667085; }
        .seg { display: flex; border: 1px solid #d0d5dd; border-radius: 6px; overflow: hidden; }
        .seg button { flex: 1; border: 0; padding: 5px 6px; background: #fff; cursor: pointer; font: inherit; }
        .seg button.on { background: #e8f0fb; color: #1f4e79; font-weight: 600; }
        .go { border: 0; border-radius: 6px; padding: 8px; background: #1f4e79; color: #fff; font: 600 13px system-ui;
              cursor: pointer; }
        .go:disabled { background: #98a2b3; cursor: not-allowed; }
        .msg { padding: 7px 9px; border-radius: 6px; background: #f2f4f7; }
        .msg.ok { background: #ecfdf3; color: #067647; }
        .msg.warn { background: #fffaeb; color: #b54708; }
        .msg.err { background: #fef3f2; color: #b42318; }
        details summary { cursor: pointer; color: #1f4e79; }
        ul { margin: 6px 0 0; padding-left: 18px; max-height: 160px; overflow: auto; }
        li { margin: 2px 0; }
        input[type=text] { width: 100%; box-sizing: border-box; padding: 5px 7px; border: 1px solid #d0d5dd;
                           border-radius: 6px; font: inherit; }
        label.chk { display: flex; gap: 6px; align-items: center; }
        .acts { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
        .acts .go { display: grid; gap: 1px; background: #fff; color: #1f4e79; border: 1px solid #1f4e79; }
        .acts .go small { font: 400 11px system-ui; color: #667085; }
        .acts .go.suggested { background: #1f4e79; color: #fff; }
        .acts .go.suggested small { color: #d1e0f2; }
        .acts .go.suggested::after { content: "suggested"; font: 600 10px system-ui; color: #d1e0f2; }
        .acts .go:disabled { background: #f2f4f7; color: #98a2b3; border-color: #d0d5dd; }
      </style>
      <div class="box">
        <div class="head" id="head"><b>Insurance Auditor · Fill from portal</b><span id="caret">▾</span></div>
        <div class="body">
          <div class="row"><span class="muted">Client</span><span id="client">—</span></div>
          <div class="row"><span class="muted">Patient</span><span id="patient">—</span></div>
          <div class="row"><span class="muted">Portal scrape</span><span id="scrape">—</span></div>
          <div class="row"><span class="muted">IN OR OON</span><span id="network">—</span></div>
          <div class="acts" id="mode">
            <button class="go" data-mode="new">Fill as New plan<small>all fields</small></button>
            <button class="go" data-mode="existing">Fill as Existing plan<small>visit fields only</small></button>
          </div>
          <div class="msg" id="msg">Open a patient's Fill Form to fill it from the portal.</div>
          <details id="details" hidden><summary id="dsum">Details</summary><ul id="list"></ul></details>
          <details><summary>Settings</summary>
            <div style="display:grid;gap:6px;margin-top:6px">
              <span class="muted">Server</span>
              <input type="text" id="server" spellcheck="false">
              <button class="go" id="saveSettings" style="padding:5px">Save settings</button>
            </div>
          </details>
        </div>
      </div>`;
    document.documentElement.appendChild(host);
    const $ = id => root.getElementById(id);
    ui = { root, $, box: root.querySelector(".box") };

    $("head").onclick = () => {
      ui.box.classList.toggle("collapsed");
      $("caret").textContent = ui.box.classList.contains("collapsed") ? "▸" : "▾";
    };
    // One click does it all: open the sections, then fill as that plan type.
    root.querySelectorAll("#mode button").forEach(b => b.onclick = () => { setMode(b.dataset.mode); onFill(); });
    $("saveSettings").onclick = async () => {
      const r = await send({ type: "IAP_SET_SETTINGS", settings: {
        serverUrl: $("server").value.trim(),
      } });
      say(r.ok ? "Settings saved." : r.error, r.ok ? "ok" : "err");
    };
    setMode(detectMode());
    loadSettings();
  }

  function detectMode() {
    // planId is the plan ticked in Search Plan: 0 = none (a new plan), any
    // other number = an existing plan. Sabrina's planType says "newplan" in
    // both cases, so it is not used.
    const id = new URLSearchParams(location.search).get("planId");
    return !id || id === "0" ? "new" : "existing";
  }

  let mode = "new";
  function setMode(m) {
    mode = m;
  }

  // Mark the plan type the URL suggests, so the user sees which to click.
  function markSuggested() {
    const s = detectMode();
    ui.root.querySelectorAll("#mode button").forEach(b => b.classList.toggle("suggested", b.dataset.mode === s));
  }

  function setButtons(enabled) {
    ui.root.querySelectorAll("#mode button").forEach(b => { b.disabled = !enabled; });
  }

  async function loadSettings() {
    const r = await send({ type: "IAP_GET_SETTINGS" });
    if (!r.ok) return say("The extension's background is not answering: " + r.error, "err");
    ui.$("server").value = r.settings.serverUrl || "";
    showLastScrape(r.lastScrape || null);
  }

  // ── is the last scrape this patient? ──────────────────────────────────────
  // The panel fills only from the scrape this browser made last, and only when
  // that scrape is the patient on this form. When the form and the scrape both
  // state a DOB, the DOB decides: family members often share the subscriber's
  // member ID (Delta, Cigna, MetLife), and a portal may word the ID differently.
  // Without both DOBs, the member ID decides.
  let lastScrape = null, scrapeLoaded = false, matchState = null;

  function showLastScrape(last) {
    lastScrape = last;
    scrapeLoaded = true;
    matchState = null;                               // re-evaluate on the next refresh
    if (!ui) return;
    ui.$("scrape").textContent = last
      ? `${last.carrier || "portal"} · ${scrapeWho(last)} · ${new Date(last.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
      : "none from this browser";
  }

  function scrapeMatch() {
    if (!scrapeLoaded) return "loading";
    if (!lastScrape) return "none";
    const formMember = normId(pageVal("demographic.memberId"));
    const formDob = normDate(pageVal("demographic.patientDOB"));
    if (!formMember && !formDob) return "unknown";   // Demographic closed: checked again on Fill
    const scrapeDob = normDate(lastScrape.dob);
    if (formDob && scrapeDob) return formDob === scrapeDob ? "match" : "other";
    if (formMember && normId(lastScrape.member_id) === formMember) return "match";
    return "other";
  }

  // Some portals give no member ID (Guardian, some Toolkit and MetLife
  // exports): the scrape is then known by the patient's DOB.
  function scrapeWho(s) {
    return s.member_id ? `member ${s.member_id}` : s.dob ? `DOB ${s.dob}` : "unknown patient";
  }

  function otherPatientText() {
    const formMember = pageVal("demographic.memberId");
    const formDob = normDate(pageVal("demographic.patientDOB"));
    if (formMember && normId(formMember) === normId(lastScrape.member_id) && formDob && lastScrape.dob) {
      return `Your last portal scrape is for member ${lastScrape.member_id} born ${lastScrape.dob}, ` +
             `but this form's patient was born ${formDob}: another family member on the same ` +
             `member ID. Run the extension on this patient's portal page first.`;
    }
    return `Your last portal scrape is for ${scrapeWho(lastScrape)}, not this patient ` +
           `(${pageVal("demographic.memberId") || "this form"}). Run the extension on this patient's ` +
           `portal page first.`;
  }

  // A scrape made in another tab while this form is open updates the panel.
  try {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === "local" && changes.iapLastScrape) showLastScrape(changes.iapLastScrape.newValue || null);
    });
  } catch (_) { /* no storage events here */ }

  function say(text, kind) {
    const m = ui.$("msg");
    m.textContent = text;
    m.className = "msg" + (kind ? " " + kind : "");
  }

  function showDetails(log, prefill) {
    const issues = log.filter(r => r.status !== "filled" && r.status !== "already same");
    const list = ui.$("list");
    list.innerHTML = "";
    issues.forEach(r => {
      const li = document.createElement("li");
      li.textContent = `${r.label}: ${r.status} (${r.value})`;
      list.appendChild(li);
    });
    const hints = Object.entries(prefill.hints || {});
    hints.forEach(([k, v]) => {
      const li = document.createElement("li");
      li.textContent = `Pick yourself: ${k} = ${v}`;
      list.appendChild(li);
    });
    (prefill.left_for_user || []).forEach(t => {
      const li = document.createElement("li");
      li.textContent = `Left for you: ${t}`;
      list.appendChild(li);
    });
    ui.$("dsum").textContent = `Details (${issues.length} to check)`;
    ui.$("details").hidden = !list.children.length;
  }

  // ── fill ──────────────────────────────────────────────────────────────────
  let pendingFill = false, filling = false;

  async function onFill() {
    if (filling) return;
    filling = true;
    try { await fillNow(); } finally { filling = false; }
  }

  async function fillNow() {
    if (!onFillForm()) return say("Open a patient's Fill Form first.", "warn");
    setButtons(false);
    say("Opening the form's sections…");
    const sections = await openSections();
    setButtons(true);
    if (sections.failed.includes("INSURANCE DETAILS") || !byName("insuranceDetails.network")) {
      return say("Could not open INSURANCE DETAILS. Open it, pick IN OR OON, and click Fill again.", "warn");
    }
    // Empty IN OR OON is fine here: a Cigna scrape states its own network
    // (picked on Cigna's Plan View dropdown) and the server answers with it.
    let network = pageVal("insuranceDetails.network");
    if (network !== "In" && network !== "Out") network = "";
    pendingFill = false;
    byName("insuranceDetails.network").style.outline = "";
    const memberId = pageVal("demographic.memberId");
    const dob = normDate(pageVal("demographic.patientDOB"));
    if (!memberId) return say("MEMBER# is empty on this form.", "warn");
    // Demographic is open now: the last scrape must be this patient.
    const state = scrapeMatch();
    if (state === "none") {
      matchState = state; setButtons(false);
      return say("No portal scrape from this browser yet. Run the extension on this patient's portal page first.", "warn");
    }
    if (state === "other") {
      matchState = state; setButtons(false);
      return say(otherPatientText(), "err");
    }

    setButtons(false);
    say("Fetching portal data…");
    // Whose Fill Form this is: Sabrina keeps the client picked at the top of
    // the app in sessionStorage ("26" = Smile Partners). Read on every click,
    // since one user can switch clients.
    let sabrinaClient = "";
    try { sabrinaClient = sessionStorage.getItem("selectedClient") || ""; } catch (_) { /* blocked */ }
    if (!sabrinaClient) {
      setButtons(true);
      return say("Cannot tell which client this Fill Form is for. Pick the client in Sabrina (or reload the page) and try again.", "err");
    }
    const r = await send({ type: "IAP_GET_PREFILL", sabrina_client: sabrinaClient, member_id: memberId, dob, network });
    setButtons(true);
    if (!r.ok && !network && /Choose In or Out/i.test(r.error || "")) {
      // This scrape holds both networks (Aetna, …): the user picks.
      // Point at the field and carry on by ourselves once it is picked.
      const f = byName("insuranceDetails.network");
      f.scrollIntoView({ block: "center" });
      f.style.outline = "3px solid #f79009";
      f.focus();
      pendingFill = true;
      return say("Pick IN OR OON (highlighted). Filling starts as soon as you pick it.", "warn");
    }
    if (!r.ok) return say(r.error, "err");
    const prefill = r.prefill;

    // Patient check. A DOB that differs is another patient even when the
    // member ID agrees (family members share it); a member ID that differs
    // needs the DOB to agree.
    const c = prefill.checks || {};
    const memberSame = !c.member_id || normId(c.member_id) === normId(memberId);
    const portalDob = normDate(c.patient_dob);
    const dobKnown = !!(portalDob && dob);
    const dobSame = dobKnown && portalDob === dob;
    if ((dobKnown && !dobSame) || (!memberSame && !dobSame)) {
      const family = memberSame && dobKnown
        ? ` (born ${dob}): another family member on the same member ID. Scrape this patient on the portal first.`
        : ".";
      return say(`Stopped: the portal data is for ${c.patient_name || "another patient"} ` +
                 `(member ${c.member_id || "not stated"}, DOB ${c.patient_dob || "not stated"}), ` +
                 `not this form's patient${family}`, "err");
    }

    // The scrape's own network (Cigna): set IN OR OON before anything else,
    // since changing that dropdown can reset the fields after it.
    let netNote = "";
    if (prefill.network_from_scrape) {
      const nf = byName("insuranceDetails.network");
      if (!network && nf) {
        const v = pickOption(nf, prefill.network);
        if (v !== undefined) {
          setVal(nf, v);
          await new Promise(res => setTimeout(res, 300));
          netNote = ` IN OR OON set to ${prefill.network} from the portal's network.`;
        }
      }
      network = prefill.network;
    }
    const log = applyPrefill(prefill, mode);
    // Plan-level rows: new plans only (an existing plan already has its own).
    if (mode !== "existing") await fillWaitingPeriods(prefill.waiting_periods, log);
    applied = prefill;
    appliedNetwork = network;
    const n = s => log.filter(x => x.status === s).length;
    const notOnForm = n("not on this form");
    let text = `Filled ${n("filled")} from the ${prefill.carrier} portal (${network}-network, ${mode} plan).`;
    const extra = [];
    if (n("kept existing")) extra.push(`${n("kept existing")} kept as entered`);
    if (n("no matching option")) extra.push(`${n("no matching option")} with no matching option`);
    if (notOnForm) extra.push(`${notOnForm} not on this form`);
    if (extra.length) text += " " + extra.join(", ") + ".";
    text += netNote;
    if (!memberSame) text += ` Note: member ID differs (portal ${c.member_id}), DOB matches.`;
    if (sections.failed.length) {
      text += ` Could not open: ${sections.failed.join(", ")}. Open it and click Fill again.`;
    }
    text += " Review, then Save or Submit.";
    say(text, n("no matching option") || !memberSame ? "warn" : "ok");
    showDetails(log, prefill);
  }

  // ── keep the panel in step with the form ──────────────────────────────────
  // Sabrina's own pages only (the content script also matches other ispace.com sites).
  const onSabrina = () => /sabrina/i.test(location.hostname);
  let wasOnForm = null;

  // Whose Fill Form this is (Sabrina's selectedClient), shown on the panel.
  // Read every second: one user can switch clients without reloading.
  let clientShown = null;
  function showClient() {
    let id = "";
    try { id = sessionStorage.getItem("selectedClient") || ""; } catch (_) { /* blocked */ }
    if (id === clientShown) return;
    clientShown = id;
    const el = ui.$("client");
    el.style.color = "";
    if (!id) { el.textContent = "not picked in Sabrina"; el.style.color = "#b42318"; return; }
    el.textContent = "#" + id;
    send({ type: "IAP_GET_CLIENT", sabrina_client: id }).then(r => {
      if (clientShown !== id) return;               // switched again meanwhile
      if (!r.ok) return;                            // server down: the id is all we can show
      const c = r.client;
      el.textContent = c.ready ? c.name : `${c.name} · not set up yet`;
      el.style.color = c.ready ? "" : "#b54708";
    });
  }

  function refresh() {
    if (!onSabrina()) return;
    const onForm = onFillForm();
    // The panel lives on the Fill Form only; other Sabrina pages stay clean.
    if (!onForm) {
      if (host) host.style.display = "none";
      wasOnForm = false;
      pendingFill = false;
      return;
    }
    if (!host) buildPanel();
    host.style.display = "";
    showClient();
    if (onForm !== wasOnForm) {
      wasOnForm = onForm;
      pendingFill = false;
      applied = null;
      written = {};
      matchState = null;
      scrapeLoaded = false;
      ui.$("details").hidden = true;
      setButtons(false);
      say("Checking the portal scrape…");
      loadSettings();
    }

    // Buttons only when the last scrape is this patient.
    if (!filling) {
      const state = scrapeMatch();
      if (state !== matchState) {
        matchState = state;
        setButtons(state === "match" || state === "unknown");
        if (state === "none") {
          say("No portal scrape from this browser yet. Run the extension on this patient's portal page first.", "warn");
        } else if (state === "other") {
          say(otherPatientText(), "err");
          applied = null;
        } else if ((state === "match" || state === "unknown") && !applied) {
          say("Ready. Pick New or Existing below. Sections are opened and filled for you.");
        }
      }
    }
    if (!onForm) {
      ui.$("network").textContent = "—";
      ui.$("patient").textContent = "—";
      return;
    }
    markSuggested();
    const networkField = byName("insuranceDetails.network");
    const network = pageVal("insuranceDetails.network");
    const picked = network === "In" || network === "Out";
    ui.$("network").textContent = picked ? network : networkField ? "not picked" : "section closed";
    ui.$("patient").textContent = pageVal("demographic.memberId") || ui.$("patient").textContent || "—";
    if (pendingFill && picked && !filling) {
      pendingFill = false;
      onFill();
      return;
    }
    if (applied && picked && network !== appliedNetwork) {
      if (applied.network_from_scrape) {
        // Cigna: the scrape holds one network only; there is nothing to switch to.
        say(`IN OR OON changed to ${network}, but this ${applied.carrier} scrape is ${applied.network}-network ` +
            `only. Set it back to ${applied.network}, or re-scrape with ${network === "Out" ? "Out-of-Network" : "an in-network option"} ` +
            `picked on the portal.`, "err");
      } else {
        say(`IN OR OON changed to ${network}. Click the same Fill button again to switch the benefits.`, "warn");
      }
      appliedNetwork = network;
    }
  }

  // Sabrina's own Save / Submit: the scrape has been used.
  document.addEventListener("click", e => {
    const b = e.target && e.target.closest && e.target.closest("button");
    if (!b || !applied || !applied.scrape_id) return;
    if (!/^\s*(save|submit)\s*$/i.test(b.textContent || "")) return;
    const id = applied.scrape_id;
    send({ type: "IAP_MARK_USED", scrape_id: id }).then(() => {
      applied = null;
      written = {};
      if (ui) { say("Saved. This portal scrape is now marked used."); loadSettings(); }
    });
  }, true);

  // Sabrina is a single-page app: the Fill Form appears without a page load.
  setInterval(refresh, 1000);
  refresh();
})();