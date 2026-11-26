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
  // `more`: other names the server sends for this client's form (Star Dental's
  // "Diagnostic: XraysBitewings" row for D0274), tried last.
  const gridEl = (code, col, more = []) =>
    firstByEnding([code, ...(GRID_ALIASES[code] || []), ...more].map(c => `_${c}_${col}`));
  const questionEl = (q, more = []) =>
    firstByEnding([q, ...(QUESTION_ALIASES[q] || []), ...more].map(x => `_${x}_covered`));

  // Whose Fill Form this is: Sabrina's ClientID (19 Star Dental, 26 Smile
  // Partners), from the page address (…?clientId=19) or a field on the page.
  // The server fills the form by that client's rules. "" when the page
  // doesn't say: the client picked in Settings is used then.
  const CLIENT_NAMES = { "19": "Star Dental", "26": "Smile Partners" };
  function sabrinaClientId() {
    try {
      for (const q of [location.search || "", String(location.hash || "").split("?")[1] || ""]) {
        for (const [k, v] of new URLSearchParams(q)) {
          if (/^client_?id$/i.test(k) && /^\d+$/.test(String(v).trim())) return String(v).trim();
        }
      }
      const el = [...document.querySelectorAll("input[name], select[name]")]
        .find(e => /(^|\.)client_?id$/i.test(e.name) && /^\d+$/.test(String(e.value).trim()));
      return el ? String(el.value).trim() : "";
    } catch (_) {
      return "";       // never block a fill: the Settings client is used
    }
  }
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
    // Eligibility notes live here; nothing is filled in it, it is opened so
    // the Details list can see whether the notes are written. Not every form
    // has it, so a miss is not reported.
    { title: "NOTE INFO",         optional: true,
      probe: () => [...document.querySelectorAll("label, span, div, p, h4, h5, h6")].find(e =>
        e.children.length <= 2 && !e.closest("#iap-sabrina-panel") &&
        /^eligibility\s*notes?$/i.test((e.textContent || "").replace("*", "").trim())) },
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
      if (!targets.length) { if (!s.optional) failed.push(s.title); continue; }
      targets[0].scrollIntoView({ block: "center" });
      const order = targets.map((el, i) => i);
      if (workedAt < targets.length) order.unshift(...order.splice(workedAt, 1));
      let ok = false;
      for (const i of order) {
        realClick(targets[i]);
        ok = await waitFor(() => visible(s.probe()), 1200);
        if (ok) { workedAt = i; break; }
      }
      if (ok) opened.push(s.title);
      else if (!s.optional) failed.push(s.title);
    }
    return { opened, failed };
  }

  // Reloading or updating the extension cuts this copy of the panel off from
  // it: the page keeps running the old copy, but its chrome.runtime is gone
  // (Chrome then answers "Cannot read properties of undefined (reading
  // 'sendMessage')" or "Extension context invalidated"). Chrome does not put
  // the new copy into open tabs; only a page refresh does.
  const RELOADED = "The extension was reloaded or updated after this page opened, so this panel " +
                   "can no longer reach it. Save your work, then refresh this page (F5).";
  const disconnected = () => {
    try { return !globalThis.chrome?.runtime?.id; } catch (_) { return true; }
  };
  const cutOff = text => /context invalidated/i.test(String(text || ""));

  function send(message) {
    if (disconnected()) return Promise.resolve({ ok: false, error: RELOADED, reloaded: true });
    return new Promise(resolve => {
      try {
        chrome.runtime.sendMessage(message, reply => {
          const err = chrome.runtime.lastError;
          if (err) resolve(cutOff(err.message) ? { ok: false, error: RELOADED, reloaded: true }
                                               : { ok: false, error: err.message });
          else resolve(reply || { ok: false, error: "no answer from the extension" });
        });
      } catch (e) {
        const text = String(e && e.message || e);
        resolve(cutOff(text) || disconnected() ? { ok: false, error: RELOADED, reloaded: true }
                                               : { ok: false, error: text });
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
  // Empty: no value, or a dropdown still on its "--Select--" line, whatever
  // value Sabrina gives that line ("", "0", "-1"…).
  const isEmpty = el => {
    if (!el.value || el.value === "--Select--") return true;
    if (el.tagName === "SELECT") {
      const opt = el.options[el.selectedIndex];
      return !opt || /^[\s-]*select[\s-]*$/i.test(opt.text);
    }
    return false;
  };

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
      .forEach(q => fillOne(questionEl(q.question, q.aliases || []), q.value, "q:" + q.question,
                            q.label || q.question, false, log));
    (prefill.grid || []).filter(wanted)
      .forEach(g => fillOne(gridEl(g.code, g.column, g.aliases || []), g.value, `g:${g.code}:${g.column}`,
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
    // Sabrina ticks a moment after the click: the Details list looks again (el).
    log.push({ status: el.checked ? "filled" : "not ticked", label, value: "ticked", el });
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
        input[type=text], select { width: 100%; box-sizing: border-box; padding: 5px 7px; border: 1px solid #d0d5dd;
                                   border-radius: 6px; font: inherit; background: #fff; }
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
              <span class="muted">Client, when the Fill Form doesn't state its ClientID</span>
              <select id="clientPick">
                <option value="smile_partners">Smile Partners</option>
                <option value="star_dental">Star Dental</option>
              </select>
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
        client: $("clientPick").value,
      } });
      if (r.ok) { settingsClient = r.settings.client; showClient(); }
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
    if (!r.ok) {
      if (r.reloaded) { setButtons(false); return say(r.error, "err"); }
      return say("The extension's background is not answering: " + r.error, "err");
    }
    ui.$("server").value = r.settings.serverUrl || "";
    settingsClient = r.settings.client || "";
    if (settingsClient) ui.$("clientPick").value = settingsClient;
    showClient();
    showLastScrape(r.lastScrape || null);
  }

  // The client whose rules fill this form: the page's ClientID, else Settings.
  let settingsClient = "";
  function showClient() {
    if (!ui) return;
    const id = sabrinaClientId();
    const picked = ui.$("clientPick");
    const pickedName = picked.options[picked.selectedIndex]?.text || settingsClient || "—";
    ui.$("client").textContent = id
      ? `${CLIENT_NAMES[id] || "ClientID " + id} (ClientID ${id})`
      : `${pickedName} (from Settings)`;
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
      : "none from this browser · Fill checks your other browser";
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

  // ── what is still blank after a fill ──────────────────────────────────────
  // BPO feedback (11/2026): "Details (0 to check)" while COB, Relation, the
  // C questions… were still empty. Every visible, editable field left blank
  // is listed, by the label the operator sees on the form.
  const COLUMN_NAMES = { frequency: "Frequency", percentage: "Percentage", history: "History",
                         ageLimit: "Age Limit", quads: "Quads", amount: "Amount", covered: "" };
  const words = s => {
    const t = String(s).replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[._]+/g, " ").trim();
    return t.charAt(0).toUpperCase() + t.slice(1);
  };

  // Never listed as blank (BPO, 11/2026): not the verifier's job on this form.
  // Not required on the Fill Form, so never listed as "Still blank"
  // (Provider Specialty: BPO feedback, 11/25).
  const NOT_CHECKED = new Set(["demographic.providerNpi", "benefitsInfo.expirationDate",
                               "demographic.speciality"]);
  // Labels that don't say where the field is.
  const LABEL_FOR = { "noteInfo.eligibilityResult": "Eligibility (NOTE INFO section, bottom of the form)" };

  function labelOf(el) {
    if (LABEL_FOR[el.name]) return LABEL_FOR[el.name];
    const grid = el.name.match(/^[0-9a-f-]{20,}_(.+)_([A-Za-z]+)$/i);   // <GUID>_<CODE>_<column>
    if (grid) {
      // The row's own label (first line of the row: "D5995 …", "Does Missing Tooth Clause Apply?").
      let row = el.parentElement, rowText = "";
      for (let i = 0; i < 6 && row; i++, row = row.parentElement) {
        const first = (row.innerText || "").split("\n").map(t => t.trim()).find(Boolean) || "";
        if (first && !/^--select--$/i.test(first) && row.querySelectorAll("input,select").length <= 8) {
          rowText = first;
          break;
        }
      }
      const col = COLUMN_NAMES[grid[2]] ?? words(grid[2]);
      return [rowText || words(grid[1]), col].filter(Boolean).join(" · ");
    }
    const byFor = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (byFor) return byFor.textContent.replace("*", "").trim();
    const wrap = el.closest("label");
    if (wrap && wrap.textContent.trim()) return wrap.textContent.replace("*", "").trim();
    // The field's own box: the closest container holding this control only.
    let up = el.parentElement;
    for (let i = 0; i < 4 && up; i++, up = up.parentElement) {
      if (up.querySelectorAll("input,select,textarea").length > 1) break;
      const lab = up.querySelector("label");
      if (lab && lab.textContent.trim()) return lab.textContent.replace("*", "").trim();
    }
    return words(el.name.split(".").pop());
  }

  function stillBlank() {
    const seen = new Set();
    return [...document.querySelectorAll("input[name], select[name], textarea[name]")]
      .filter(el => !el.closest("#iap-sabrina-panel") && el.type !== "hidden" && el.type !== "checkbox"
                    && el.type !== "radio" && el.type !== "button" && el.type !== "submit"
                    && !el.disabled && !el.readOnly && el.offsetParent !== null && isEmpty(el)
                    && !NOT_CHECKED.has(el.name))
      .filter(el => !seen.has(el.name) && seen.add(el.name));
  }

  // What the portal suggests for a field the panel doesn't fill itself
  // ("Pick yourself"), shown next to that field while it is blank.
  const HINT_FIELDS = {
    "PMS Payer Name": ["PMSPayerName"],
    "INS E-Claim Payer ID": ["insuranceDetails.payerId"],
    "Insurance address": ["insuranceDetails.street1"],
  };
  // The server's "left for the user" reminders, by the form fields they are
  // about: shown only when that field can't be checked on this form (the
  // "Still blank" list covers it otherwise). Waiting period (the form asks
  // Yes/No itself) and Mode of verification (Online is ticked) are never shown.
  const LEFT_FIELDS = {
    "IN OR OON": ["insuranceDetails.network"],
    "INS Fee Schedule": ["feeschedulename"],
    "PMS Payer Name / INS E-Claim Payer ID": ["PMSPayerName", "insuranceDetails.payerId"],
    "Eligibility": ["noteInfo.eligibilityResult"],
    "Waiting period details (Period / Applies To)": null,
    "Mode of verification": null,
    "Eligibility notes": null,
  };
  // Boxes with no usable name (the notes editor): found by the label next to
  // them and listed while empty, gone once written in. Not found: not listed.
  const BLANK_BY_LABEL = { "Eligibility notes": /^eligibility\s*notes?\b/i };

  function fieldByLabel(re) {
    for (const lab of document.querySelectorAll("label, h4, h5, h6, span, div, p")) {
      if (lab.closest("#iap-sabrina-panel") || lab.children.length > 2) continue;
      const t = (lab.textContent || "").replace("*", "").trim();
      if (t.length > 40 || !re.test(t)) continue;
      // The label's own box: the closest container holding exactly one field.
      let box = lab;
      for (let i = 0; i < 5 && box; i++, box = box.parentElement) {
        const fields = box.querySelectorAll("textarea, [contenteditable='true'], select, " +
                                            "input:not([type=checkbox]):not([type=radio]):not([type=hidden])");
        if (fields.length === 1 && !fields[0].closest("#iap-sabrina-panel")) return fields[0];
        if (fields.length > 1) break;
      }
    }
    return null;
  }
  const boxEmpty = f => f.isContentEditable ? !(f.innerText || "").trim() : isEmpty(f);

  // The last fill's details, so the list can follow the operator's edits:
  // a field filled by hand drops off "Still blank" (and the count) at once.
  let lastDetails = null;
  let detailsTimer = null;
  const recheckDetails = () => {
    if (!lastDetails) return;
    clearTimeout(detailsTimer);
    detailsTimer = setTimeout(() => {
      const before = ui.$("dsum").textContent;
      const blank = showDetails(lastDetails.log, lastDetails.prefill);
      if (ui.$("dsum").textContent !== before) {
        say(blank ? `${blank} field${blank === 1 ? " is" : "s are"} still blank (see Details). Review, then Save or Submit.`
                  : "Nothing left blank. Review, then Save or Submit.", blank ? "warn" : "ok");
      }
    }, 300);
  };
  ["input", "change", "keyup"].forEach(type => document.addEventListener(type, e => {
    if (e.target && e.target.closest && !e.target.closest("#iap-sabrina-panel")) recheckDetails();
  }, true));

  function showDetails(log, prefill) {
    lastDetails = { log, prefill };
    const issues = log.filter(r => r.status !== "filled" && r.status !== "already same"
                                   && !(r.status === "not ticked" && r.el && r.el.checked));
    const blankEls = stillBlank();
    // A blank field the portal has a suggestion for: say it once, with the value.
    const hintFor = new Map();
    Object.entries(prefill.hints || {}).forEach(([label, value]) =>
      (HINT_FIELDS[label] || []).forEach(name => hintFor.set(name, value)));
    const blank = blankEls.map(el => labelOf(el) + (hintFor.has(el.name) ? ` (portal says: ${hintFor.get(el.name)})` : ""));
    const list = ui.$("list");
    list.innerHTML = "";
    issues.forEach(r => {
      const li = document.createElement("li");
      li.textContent = `${r.label}: ${r.status} (${r.value})`;
      list.appendChild(li);
    });
    // Click a "Still blank" line to go to that field.
    const goTo = el => () => {
      el.scrollIntoView({ block: "center" });
      const was = el.style.outline;
      el.style.outline = "3px solid #f79009";
      try { el.focus({ preventScroll: true }); } catch (_) { /* not focusable */ }
      setTimeout(() => { el.style.outline = was; }, 2500);
    };
    const blankLine = (label, el) => {
      const li = document.createElement("li");
      li.textContent = `Still blank: ${label}`;
      li.title = "Click to go to this field";
      li.style.cursor = "pointer";
      li.onclick = goTo(el);
      list.appendChild(li);
    };
    blank.forEach((label, i) => blankLine(label, blankEls[i]));
    let extraBlank = 0;
    Object.entries(BLANK_BY_LABEL).forEach(([label, re]) => {
      const box = fieldByLabel(re);
      if (box && boxEmpty(box)) { blankLine(label, box); extraBlank++; }
    });
    // Hints whose field isn't on this form at all: still worth showing.
    Object.entries(prefill.hints || {}).forEach(([k, v]) => {
      if ((HINT_FIELDS[k] || []).some(name => byName(name))) return;
      const li = document.createElement("li");
      li.textContent = `Pick yourself: ${k} = ${v}`;
      list.appendChild(li);
    });
    (prefill.left_for_user || []).forEach(t => {
      const fields = LEFT_FIELDS[t];
      if (fields === null) return;                                   // never shown
      if (fields && fields.some(name => byName(name))) return;       // "Still blank" covers it
      const li = document.createElement("li");
      li.textContent = `Left for you: ${t}`;
      list.appendChild(li);
    });
    ui.$("dsum").textContent = `Details (${issues.length + blank.length + extraBlank} to check)`;
    ui.$("details").hidden = !list.children.length;
    return blank.length + extraBlank;
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
    // No scrape of this patient in this browser: the server still looks for
    // one made in another browser (portal scraped in Firefox, Fill Form open
    // here in Edge) for the same MEMBER# and DOB in the last 60 minutes, and
    // answers 404/409 with the reason when there is none.

    setButtons(false);
    say("Fetching portal data…");
    showClient();
    const r = await send({ type: "IAP_GET_PREFILL", member_id: memberId, dob, network,
                           client_id: sabrinaClientId() });
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
    if (!r.ok) {
      if (r.reloaded) setButtons(false);
      return say(r.error, "err");
    }
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
    // ELIGIBILITY "New Plan" is set last (below): Sabrina clears it while the
    // rest of the form is being changed.
    const wantEligibility = mode === "new" && isEmpty(byName("noteInfo.eligibilityResult") || { value: "x" });
    applied = prefill;
    appliedNetwork = network;
    const n = s => log.filter(x => x.status === s).length;
    const notOnForm = n("not on this form");
    const whose = prefill.client_label ? `, ${prefill.client_label} form` : "";
    let text = `Filled ${n("filled")} from the ${prefill.carrier} portal (${network}-network, ${mode} plan${whose}).`;
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
    // Let the form settle (React re-renders, sections that grew) before
    // listing what is still blank.
    await new Promise(res => setTimeout(res, 400));
    // Set last, together, and again while Sabrina clears them as the form settles.
    const late = [relationFromForm(log), mode === "new" ? eligibilityNewPlan(log, wantEligibility) : null]
      .filter(Boolean);
    const kept = await setAllAndKeep(late);
    late.forEach(item => log.push({ status: kept.has(item.name) ? "filled" : "not kept by Sabrina",
                                    label: item.label, value: item.text }));
    const blank = showDetails(log, prefill);
    if (blank) text += ` ${blank} field${blank === 1 ? " is" : "s are"} still blank (see Details).`;
    text += " Review, then Save or Submit.";
    say(text, n("no matching option") || !memberSame || blank ? "warn" : "ok");
  }

  // Relation to Insured the portal didn't give: Self when this form's patient
  // is the insured (same first name, last name and DOB on the form).
  function relationFromForm(log) {
    const rel = byName("demographic.relationToInsured");
    if (!rel || !isEmpty(rel)) return null;
    const text = f => (f ? (f.isContentEditable ? f.innerText : f.value) : "").trim().toLowerCase();
    const pFirst = text(fieldByLabel(/^patient first name$/i)), pLast = text(fieldByLabel(/^patient last name$/i));
    const iFirst = pageVal("demographic.insuredFirstName").trim().toLowerCase()
                   || text(fieldByLabel(/^insured first name$/i));
    const iLast = pageVal("demographic.insuredLastName").trim().toLowerCase()
                  || text(fieldByLabel(/^insured last name$/i));
    const pDob = normDate(pageVal("demographic.patientDOB")), iDob = normDate(pageVal("demographic.insuredDob"));
    if (!pFirst || !pLast || !pDob || pFirst !== iFirst || pLast !== iLast || pDob !== iDob) return null;
    const v = pickOption(rel, "Self");
    if (v === undefined) return null;
    return { name: "demographic.relationToInsured", value: v, text: "Self",
             label: "Relation to Insured (patient is the insured)" };
  }

  // Set these dropdowns, wait, and set again any Sabrina cleared (it resets
  // some boxes as other fields change, including each other) until all stay.
  // Returns the names that stayed.
  async function setAllAndKeep(items) {
    const stayed = new Set();
    for (let round = 0; round < 6 && items.length; round++) {
      items.forEach(it => { const box = byName(it.name); if (box && box.value !== it.value) setVal(box, it.value); });
      await new Promise(res => setTimeout(res, 700));
      stayed.clear();
      items.forEach(it => { const box = byName(it.name); if (box && box.value === it.value) stayed.add(it.name); });
      if (stayed.size === items.length) break;
    }
    return stayed;
  }

  // Fill as New plan → ELIGIBILITY "New Plan" (BPO team, 11/2026), only when
  // it was empty before the fill (an operator's pick stays). Sabrina clears
  // this box when other fields change, so it is set after everything else and
  // set again if it was cleared a moment later.
  function eligibilityNewPlan(log, wanted) {
    const label = "Eligibility";
    const elig = byName("noteInfo.eligibilityResult");
    if (!elig) { log.push({ status: "not on this form", label, value: "New Plan" }); return null; }
    if (!wanted) { log.push({ status: "kept existing", label, value: "New Plan" }); return null; }
    const v = pickOption(elig, "New Plan");
    if (v === undefined) { log.push({ status: "no matching option", label, value: "New Plan" }); return null; }
    return { name: "noteInfo.eligibilityResult", value: v, text: "New Plan", label };
  }

  // ── keep the panel in step with the form ──────────────────────────────────
  // Sabrina's own pages only (the content script also matches other ispace.com sites).
  const onSabrina = () => /sabrina/i.test(location.hostname);
  let wasOnForm = null, cutOffShown = false;

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
    // The extension was reloaded or updated while this tab stayed open: say
    // so as soon as it happens, not on the next click.
    if (disconnected()) {
      if (!cutOffShown) { cutOffShown = true; setButtons(false); say(RELOADED, "err"); }
      return;
    }
    if (onForm !== wasOnForm) {
      wasOnForm = onForm;
      pendingFill = false;
      applied = null; lastDetails = null;
      written = {};
      matchState = null;
      scrapeLoaded = false;
      ui.$("details").hidden = true;
      setButtons(false);
      say("Checking the portal scrape…");
      loadSettings();
    }

    // Buttons stay on without a scrape of this patient in this browser: Fill
    // can still use one made in another browser (Firefox → Edge).
    if (!filling) {
      const state = scrapeMatch();
      if (state !== matchState) {
        matchState = state;
        setButtons(state !== "loading");
        if (state === "none") {
          say("No portal scrape from this browser. Fill uses this patient's scrape from your other " +
              "browser (e.g. Firefox) if it was made in the last 60 minutes.", "warn");
        } else if (state === "other") {
          say(otherPatientText() + " Fill can still use this patient's scrape from your other " +
              "browser (e.g. Firefox) if it was made in the last 60 minutes.", "warn");
          applied = null; lastDetails = null;
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
    send({ type: "IAP_MARK_USED", scrape_id: id }).then(r => {
      if (!r.ok) {
        // Sabrina saved; only our "used" mark failed. Never claim it was made.
        if (ui) say(r.reloaded ? r.error
                    : `Sabrina saved, but this portal scrape could not be marked used: ${r.error}`, "warn");
        return;
      }
      applied = null; lastDetails = null;
      written = {};
      if (ui) { say("Saved. This portal scrape is now marked used."); loadSettings(); }
    });
  }, true);

  // Sabrina is a single-page app: the Fill Form appears without a page load.
  setInterval(refresh, 1000);
  refresh();
})();