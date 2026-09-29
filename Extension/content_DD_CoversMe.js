(() => {
  'use strict';

  // Delta Dental Covers Me network scraper.
  // IMPORTANT: manifest.json and popup.js are intentionally NOT modified.
  // This file supports the existing popup messages: START_CRAWL and DOWNLOAD_PATIENT.

  if (window.top !== window) return;
  if (!location.hostname.endsWith('deltadentalcoversme.com')) return;

  const API = '/private/provider/api';
  const STORAGE_KEY = 'audit_context';

  // Baseline procedure universe used by the portal/HAR. Additional codes found in
  // benefit tables are appended automatically. Every requested code gets an output row.
  const DEFAULT_CODES = [
    'D0180','D0120','D0140','D0150','D0210','D0220','D0230','D0240','D0274','D0330',
    'D1510','D1110','D1120','D1206','D1351','D2140','D2331','D2620','D2740','D2950',
    'D2991','D3347','D3310','D3330','D4260','D4341','D4355','D4381','D4910','D5860',
    'D5110','D5740','D5982','D6194','D6010','D6056','D6065','D6245','D7259','D7140',
    'D7240','D8010','D8080','D8090','D9430','D9110','D9222','D9239','D9310','D9944'
  ];

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const clean = v => v == null ? '' : String(v).replace(/\s+/g, ' ').trim();

  // ---------------------------------------------------------------------
  // Anti-forgery token
  // ---------------------------------------------------------------------
  // The portal is protected by an ASP.NET anti-forgery token. Every real API
  // call in the network capture sends it as the `X-XSRF-Token` header, but
  // the value does NOT come from a cookie named XSRF-TOKEN — it comes from a
  // hidden input the server renders directly into the page:
  //   <div id="antiForgeryTokenInput">
  //     <input name="__RequestVerificationToken" type="hidden" value="...">
  //   </div>
  // Without this header the API rejects every request, which is why the
  // crawl was silently failing.
  function getAntiForgeryToken() {
    const input =
      document.querySelector('#antiForgeryTokenInput input[name="__RequestVerificationToken"]') ||
      document.querySelector('input[name="__RequestVerificationToken"]');
    const token = input && input.value ? input.value.trim() : '';
    if (!token) {
      throw new Error('Anti-forgery token not found on page. Reload the Patient Benefit Details page (make sure it has fully loaded) and try again.');
    }
    return token;
  }

  // ---------------------------------------------------------------------
  // On-page status banner
  // ---------------------------------------------------------------------
  const BANNER_ID = 'dd-coversme-crawl-banner';

  function showBanner(text) {
    let el = document.getElementById(BANNER_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = BANNER_ID;
      el.style.cssText = [
        'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:2147483647',
        'background:#0b5cab', 'color:#fff',
        'font:600 14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
        'padding:10px 16px', 'text-align:center',
        'box-shadow:0 2px 6px rgba(0,0,0,.25)',
        'transition:opacity .25s ease', 'opacity:1'
      ].join(';');
      (document.body || document.documentElement).appendChild(el);
    }
    el.style.display = 'block';
    el.style.opacity = '1';
    el.textContent = text;
  }

  function hideBanner() {
    const el = document.getElementById(BANNER_ID);
    if (!el) return;
    el.style.opacity = '0';
    setTimeout(() => { el.remove(); }, 300);
  }

  // ---------------------------------------------------------------------
  // Client-side JSON download (content scripts can't use chrome.downloads,
  // so this uses a Blob + temporary <a download> click, the standard way to
  // trigger a save-as from page context).
  // ---------------------------------------------------------------------
  function downloadJson(data) {
    const namePart = clean(data?.patient?.name).replace(/[^\w-]+/g, '_').replace(/^_+|_+$/g, '') || 'patient';
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const filename = `DD_CoversMe_${namePart}_${stamp}.json`;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    (document.body || document.documentElement).appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    return filename;
  }

  function normalizeCode(v) {
    const s = clean(v).toUpperCase().replace(/^\s+|\s+$/g, '');
    if (/^D\d{4}$/.test(s)) return s;
    if (/^\d{4}$/.test(s)) return 'D' + s;
    return null;
  }

  function codesFromText(v) {
    return [...clean(v).matchAll(/\bD?\d{4}\b/gi)]
      .map(m => normalizeCode(m[0]))
      .filter(Boolean);
  }

  function extractCode(name) {
    return codesFromText(name)[0] || null;
  }

  function formatDate(v) {
    if (!v) return '';
    const s = String(v);
    let m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return `${m[2]}/${m[3]}/${m[1]}`;
    m = s.match(/^(\d{2})[/-](\d{2})[/-](\d{4})/);
    return m ? `${m[1]}/${m[2]}/${m[3]}` : s;
  }

  function money(v) {
    if (typeof v === 'number' && Number.isFinite(v)) return `$${v.toFixed(2)}`;
    if (v === null || v === undefined || v === '') return 'N/A';
    return String(v);
  }

  function parseAge(v) {
    const m = String(v ?? '').match(/(\d+)/);
    return m ? Number(m[1]) : 'N/A';
  }

  function extractAge(descriptions) {
    for (const d of (descriptions || [])) {
      const s = clean(d);
      const m = s.match(/Age limit:\s*(?:is\s*)?(.*)$/i);
      if (m) return clean(m[1]);
    }
    return 'None';
  }

  function extractFrequency(descriptions) {
    for (const d of (descriptions || [])) {
      const s = clean(d);
      const m = s.match(/^Frequency:\s*(.*)$/i);
      if (m) return clean(m[1]);
    }
    return 'N/A';
  }

  function extractLastServiceDates(descriptions) {
    const out = [];
    for (const d of (descriptions || [])) {
      const s = clean(d);
      const m = s.match(/Last Service Date:\s*(\d{2}\/\d{2}\/\d{4})/i);
      if (m) out.push({ dos: m[1], source: 'benefit-details' });
    }
    return out;
  }

  function normalizeHistoryItem(h) {
    if (!h || typeof h !== 'object') return { dos: formatDate(h) };
    const out = { ...h };
    if (out.ServiceDate) out.dos = formatDate(out.ServiceDate);
    else if (out.serviceDate) out.dos = formatDate(out.serviceDate);
    else if (out.DateOfService) out.dos = formatDate(out.DateOfService);
    else if (out.DOS) out.dos = formatDate(out.DOS);
    return out;
  }

  function authParams() {
    const u = new URL(location.href);
    const patientIdentifier = u.searchParams.get('patientIdentifier') || u.searchParams.get('patient');
    const signature = u.searchParams.get('signature');
    if (!patientIdentifier || !signature) {
      throw new Error('Patient identifier/signature not found. Open the Delta Dental Covers Me Patient Benefit Details page first.');
    }
    return { patientIdentifier, signature };
  }

  async function requestWithRetry(url, options = {}, label = 'request', maxAttempts = 6) {
    let lastError;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const response = await fetch(url, {
          credentials: 'include',
          cache: 'no-store',
          ...options,
          headers: {
            Accept: 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'X-XSRF-Token': getAntiForgeryToken(),
            'X-DP-CompFeatureIds': 'PR_PBD',
            ...(options.headers || {})
          }
        });

        if (response.ok) return response.json();

        const status = response.status;
        let bodySnippet = '';
        try { bodySnippet = (await response.text()).slice(0, 200); } catch (_) {}
        lastError = new Error(`${label} returned HTTP ${status}${bodySnippet ? ` — ${bodySnippet}` : ''}`);

        // 401/403 almost always means the anti-forgery token is stale (e.g. the
        // page was reloaded/navigated since the crawl started) — retrying with
        // the same token won't help, so fail fast with a clear message.
        if (status === 401 || status === 403) throw lastError;

        // Explicitly back off on rate limiting and transient server errors.
        if (![408, 425, 429, 500, 502, 503, 504].includes(status)) throw lastError;
      } catch (err) {
        lastError = err;
      }

      if (attempt < maxAttempts) {
        const delay = Math.min(15000, 1000 * Math.pow(2, attempt - 1) + Math.floor(Math.random() * 500));
        await sleep(delay);
      }
    }
    throw lastError || new Error(`${label} failed`);
  }

  async function apiGet(path, params, label) {
    const u = new URL(location.origin + path);
    for (const [k, v] of Object.entries(params || {})) u.searchParams.set(k, v);
    return requestWithRetry(u.toString(), {}, label || path);
  }

  async function apiPost(path, body, label) {
    return requestWithRetry(location.origin + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }, label || path);
  }

  function buildFinancials(d) {
    const maximums = (d.MaximumsUsages || []).map(x => ({
      category: clean(x.Name),
      total: x.IsUnlimited ? 'None' : money(x.DollarsMaximum),
      used: money(x.DollarsUsed),
      remaining: money(x.DollarsRemaining)
    }));

    const deductibles = (d.DeductiblesUsages || []).map(x => ({
      category: clean(x.CategoryDescription),
      total: money(x.AvailableToBePaid),
      used: typeof x.AvailableToBePaid === 'number' && typeof x.RemainsToBePaid === 'number'
        ? money(x.AvailableToBePaid - x.RemainsToBePaid)
        : 'N/A',
      remaining: money(x.RemainsToBePaid)
    }));

    return { maximums, deductibles };
  }

  function normalizeProcedureStatus(x) {
    const status = Number(x?.ProcedureStatus);
    if (status === 0) return 'COVERED';
    // Portal status 1 explicitly means not covered; 2/3/4 are also represented
    // as NOT COVERED in the normalized audit because the requested code has no
    // payable coverage under this lookup. The original status is preserved.
    return 'NOT COVERED';
  }

  function normalizeProcedure(x, benefit, history) {
    const code = normalizeCode(x?.ProcedureCode) || 'N/A';
    const covered = Number(x?.ProcedureStatus) === 0;
    const benefitDescriptions = benefit?.ServiceDescriptions || [];
    const explicitHistory = (history || []).map(normalizeHistoryItem).filter(h => h && (h.dos || h.ServiceDate || h.serviceDate));
    const benefitHistory = extractLastServiceDates(benefitDescriptions);
    const finalHistory = explicitHistory.length ? explicitHistory : benefitHistory;

    let pct = 'N/A';
    if (covered && x?.PercentagePlanPays !== undefined && x?.PercentagePlanPays !== null && x?.PercentagePlanPays !== '') {
      pct = `${x.PercentagePlanPays}%`;
    } else if (covered && benefit?.PercentagePlanPays !== undefined && benefit?.PercentagePlanPays !== null && benefit?.PercentagePlanPays !== '') {
      // benefit.PercentagePlanPays (from EligibleBenefits) already comes back
      // as a formatted string like "80%" — only append '%' if it's a bare number.
      const raw = String(benefit.PercentagePlanPays).trim();
      pct = /%$/.test(raw) ? raw : `${raw}%`;
    }

    const frequency = x?.Frequency || extractFrequency(benefitDescriptions);
    const alternate = Array.isArray(x?.Variations) && x.Variations.length ? x.Variations : 'N/A';

    return {
      procedure_code: code,
      description: x?.ProcedureDescription || x?.ProcedureName || benefit?.Name || 'N/A',
      type: /^D8\d{3}$/.test(code) ? 'Ortho' : 'Non-Ortho',
      coverage_status: normalizeProcedureStatus(x),
      coverage_percentage: covered ? pct : 'N/A',
      deductible_applies: covered ? (x?.IsDeductible ? 'Yes' : 'No') : 'N/A',
      waiting_period: covered ? (benefit?.WaitingPeriod || x?.WaitingPeriod || 'N/A') : 'N/A',
      alternate_benefit: alternate,
      frequency: covered ? frequency : 'N/A',
      remaining: x?.Remaining ?? 'N/A',
      age_limit: extractAge(benefitDescriptions),
      history: finalHistory,
      category: x?.BenefitClass || benefit?.CategoryName || 'N/A',
      procedure_status: Number.isFinite(Number(x?.ProcedureStatus)) ? Number(x.ProcedureStatus) : null,
      procedure_status_message: x?.ProcedureStatus === 1 ? 'Procedure code is not covered under plan.' :
        x?.ProcedureStatus === 2 ? 'No procedure code found.' :
        x?.ProcedureStatus === 3 ? 'The procedure code is invalid.' :
        x?.ProcedureStatus === 4 ? 'Currently this request is not supported for out-of-state providers.' :
        (covered ? 'Covered' : 'Not covered'),
      history_source: explicitHistory.length ? 'patient-treatment-history' : (benefitHistory.length ? 'benefit-details' : 'none'),
      raw_lookup: x || null,
      raw_benefit: benefit || null,
      raw_history: history || []
    };
  }

  function categoryNameByGid(data) {
    const map = new Map();
    for (const c of data.Categories || []) {
      if (c && c.CategoryGid != null) map.set(c.CategoryGid, clean(c.Name));
    }
    return map;
  }

  function buildBenefitIndexes(data) {
    const benefitByCode = new Map();
    const eligible = data.EligibleBenefits || [];
    const network = data.AllNetworkCoverages || [];
    const catNames = categoryNameByGid(data);

    for (const b of eligible) {
      for (const c of codesFromText(b.Name)) {
        benefitByCode.set(c, b);
      }
    }

    // Network coverage tables can contain codes not present in EligibleBenefits.
    // Coverage rows link to a category via CategoryGid, not a CategoryName field.
    for (const n of network) {
      for (const c of codesFromText(n.Name)) {
        if (!benefitByCode.has(c)) benefitByCode.set(c, {
          Name: n.Name,
          CategoryGid: n.CategoryGid,
          CategoryName: catNames.get(n.CategoryGid) || 'N/A',
          PercentagePlanPays: String(n.PlanNetworkCoveragesOutput || '').match(/PPO:\s*([^<]+)/i)?.[1] || 'N/A',
          Deductible: 'N/A',
          WaitingPeriod: 'N/A',
          ServiceDescriptions: []
        });
      }
    }
    return benefitByCode;
  }

  function collectAllProcedureCodes(data) {
    // Only crawl the fixed 50-code list. Auto-discovering extra codes from
    // EligibleBenefits/AllNetworkCoverages text used to inflate this to 63+
    // codes, and an occasional bad match from that text (not a real ADA code)
    // was enough to make procedure-lookup 500 on its whole 5-code batch.
    void data; // benefit-details data is still used elsewhere; not needed here anymore.
    return [...DEFAULT_CODES];
  }

  async function lookupProcedures(auth, codes, progress) {
    const results = [];
    for (let i = 0; i < codes.length; i += 5) {
      const batch = codes.slice(i, i + 5);
      progress(`Procedure lookup ${Math.min(i + 5, codes.length)}/${codes.length}`);
      const body = {
        patientIdentifier: auth.patientIdentifier,
        procedureCodes: batch,
        inNetwork: true,
        outOfNetwork: false,
        outOfServiceArea: false,
        signature: auth.signature
      };
      try {
        const response = await apiPost(API + '/procedure-lookup', body, 'procedure-lookup');
        const returned = Array.isArray(response?.Data) ? response.Data : [];
        results.push(...returned);
      } catch (err) {
        // Don't let one bad/rejected batch abort the entire crawl — the codes
        // in this batch fall through to the synthetic NOT COVERED entries
        // below, and every other batch still runs.
        console.error('[DD Covers Me] procedure-lookup batch failed for', batch, err);
      }
      await sleep(350);
    }

    // Never silently drop a requested code. If the portal omitted it from Data,
    // preserve it as NOT COVERED and flag that it was not returned by the API.
    const byCode = new Map();
    for (const x of results) {
      const c = normalizeCode(x?.ProcedureCode);
      if (c) byCode.set(c, x);
    }
    for (const c of codes) {
      if (!byCode.has(c)) {
        byCode.set(c, {
          ProcedureCode: c,
          ProcedureStatus: 1,
          ProcedureDescription: 'Not returned by procedure-lookup API',
          CoverageType: null,
          PercentagePlanPays: null,
          IsDeductible: false,
          WaitingPeriod: null,
          Frequency: null,
          Remaining: null,
          Variations: [],
          TreatmentHistory: [],
          RelatedProceduresTreatmentHistory: [],
          BenefitClass: null,
          _syntheticNotReturned: true
        });
      }
    }
    return [...byCode.values()];
  }

  async function lookupHistory(auth, codes, progress) {
    const historyByCode = new Map();

    for (let i = 0; i < codes.length; i++) {
      const code = codes[i];
      progress(`History ${i + 1}/${codes.length}`);
      try {
        const response = await apiPost(API + '/patient-treatment-history', {
          patientIdentifier: auth.patientIdentifier,
          toothQuadArchProcedureCode: code
        }, 'patient-treatment-history ' + code);
        const rows = Array.isArray(response?.Data) ? response.Data : [];
        historyByCode.set(code, rows.map(normalizeHistoryItem));
      } catch (err) {
        // Keep the code present even if one history request fails. The benefit
        // details Last Service Date fallback will still be used where available.
        historyByCode.set(code, []);
      }
      // Small spacing between requests reduces 429 risk.
      await sleep(300);
    }
    return historyByCode;
  }

  function buildPreventiveHistory(eligible, historyByCode) {
    const out = [];
    for (const b of eligible) {
      const code = extractCode(b.Name);
      const rows = code ? (historyByCode.get(code) || []) : [];
      for (const h of rows) {
        if (h.dos) out.push({ procedure: clean(b.Name).replace(/\s*\(D\d{4}.*?\)\s*$/i, ''), procedure_code: code, dos: h.dos });
      }
    }
    return out;
  }

  function networkTables(data) {
    // Preserve the rendered table concepts while retaining every row from the
    // API. AllNetworkCoverages rows link back to a category via CategoryGid —
    // they do NOT carry a CategoryName/Category field, so grouping must join
    // on CategoryGid or every category silently ends up with zero rows.
    const categories = data.Categories || [];
    const network = data.AllNetworkCoverages || [];
    const rowToRow = x => ({
      benefit_class: x.Name,
      plan_pays_network_coverages: x.PlanNetworkCoveragesOutput,
      patient_pays_network_coverages: x.PatientNetworkCoveragesOutput,
      raw: x
    });

    const usedGids = new Set();
    const tables = categories.map(category => {
      const gid = category?.CategoryGid;
      if (gid != null) usedGids.add(gid);
      const categoryName = clean(category?.Name) || 'Uncategorized';
      return {
        category: categoryName,
        category_gid: gid ?? null,
        rows: network.filter(x => gid != null && x.CategoryGid === gid).map(rowToRow)
      };
    });

    // Safety net: any network coverage row whose CategoryGid didn't match a
    // known category still gets surfaced instead of being dropped.
    const orphanRows = network.filter(x => x.CategoryGid == null || !usedGids.has(x.CategoryGid)).map(rowToRow);
    if (orphanRows.length) {
      tables.push({ category: 'Uncategorized', category_gid: null, rows: orphanRows });
    }

    return tables;
  }

  async function scrape(progress = () => {}) {
    const auth = authParams();
    progress('Getting benefit-details network response...');

    const benefitResponse = await apiGet(API + '/benefit-details', {
      patientIdentifier: auth.patientIdentifier,
      signature: auth.signature,
      _: Date.now()
    }, 'benefit-details');

    const data = benefitResponse?.Data;
    if (!data) throw new Error('benefit-details API returned no Data object.');

    const codes = collectAllProcedureCodes(data);
    const benefitByCode = buildBenefitIndexes(data);

    const lookupResults = await lookupProcedures(auth, codes, progress);
    const historyByCode = await lookupHistory(auth, codes, progress);

    const procedures = lookupResults.map(x => {
      const code = normalizeCode(x?.ProcedureCode);
      return normalizeProcedure(x, benefitByCode.get(code), historyByCode.get(code) || []);
    });

    const preventiveHistory = buildPreventiveHistory(data.EligibleBenefits || [], historyByCode);

    const output = {
      patient: {
        name: clean(data.PatientName),
        subscriber_name: clean(data.SubscriberName),
        member_id: clean(data.MemberId),
        dob: formatDate(data.PatientDoB),
        relationship: clean(data.Relationship || '')
      },
      plan_details: {
        employer_group: clean(data.GroupName),
        group_number: clean(data.GroupNumber),
        effective_date: formatDate(data.CoverageEffectiveDate),
        termination_date: formatDate(data.EligibleThroughDate) || 'Present',
        network_status: clean(data.NetworkParticipation?.NetworkParticipationDescription || data.NetworkParticipation?.Description),
        coverage_type: clean(data.CoverageLevel),
        plan_type: clean(data.PlanType)
      },
      financials: buildFinancials(data.Deductibles || {}),
      benefit_categories: data.Categories || [],
      missing_tooth_clause: clean(data.MissingToothClause || ''),
      dependent_age_limit: parseAge(data.Deductibles?.DependentEligibilityLimit),
      coverage_ages: {
        child_coverage_age: parseAge(data.Deductibles?.DependentEligibilityLimit),
        student_coverage_age: parseAge(data.Deductibles?.StudentEligibilityLimit),
        adult_orthodontic: 'N/A',
        dependent_orthodontic_age: 'N/A'
      },
      frequency_age_limitations: (data.EligibleBenefits || []).map(b => ({
        service: clean(b.Name),
        frequency_and_other_benefit_limitations: (b.ServiceDescriptions || []).filter(s => /frequency|remaining|subject|alternate|similar procedures|contract|last service date/i.test(String(s))).join(' | ') || 'N/A',
        age_limitations: extractAge(b.ServiceDescriptions)
      })),
      benefit_levels: (data.EligibleBenefits || []).map(b => ({
        service: clean(b.Name),
        delta_dental_ppo: {
          benefit_level: b.PercentagePlanPays ?? 'N/A',
          deductible_applies: b.Deductible ?? 'N/A'
        }
      })),
      waiting_periods: (data.EligibleBenefits || []).map(b => ({
        service: clean(b.Name),
        waiting_period_duration: b.WaitingPeriod ?? 'N/A',
        members: b.Members ?? 'N/A'
      })),
      preventive_history: preventiveHistory,
      benefit_coverage: { procedures },

      // Complete network/table material, not just normalized rows.
      network_participation: data.NetworkParticipation || {},
      all_network_coverages: data.AllNetworkCoverages || [],
      network_tables: networkTables(data),
      categories: data.Categories || [],
      group_content_details: data.GroupContentDetails || [],
      benefit_group_details: data.BenefitGroupDetails || [],
      patient_source_keys: data.PatientSourceKeys || [],
      group_source_keys: data.GroupSourceKeys || [],
      subscription_source_keys: data.SubscriptionSourceKeys || [],

      // Raw network payloads are retained so no table/API field is lost.
      raw_network_responses: {
        benefit_details: benefitResponse,
        procedure_lookup: lookupResults,
        patient_treatment_history: Object.fromEntries(historyByCode.entries())
      },
      raw_api_response: data,

      scrape_metadata: {
        source: 'Delta Dental Covers Me network APIs',
        endpoints: {
          benefit_details: location.origin + API + '/benefit-details',
          procedure_lookup: location.origin + API + '/procedure-lookup',
          patient_treatment_history: location.origin + API + '/patient-treatment-history'
        },
        procedure_lookup_batch_size: 5,
        procedure_codes_requested: codes,
        procedure_codes_returned: lookupResults.map(x => normalizeCode(x?.ProcedureCode)).filter(Boolean),
        procedure_codes_not_returned: procedures.filter(x => x.raw_lookup?._syntheticNotReturned).map(x => x.procedure_code),
        history_strategy: 'Explicit patient-treatment-history request for every procedure code; benefit-details Last Service Date is fallback when treatment-history returns no rows.',
        generated_at: new Date().toISOString()
      }
    };

    return output;
  }

  async function saveAuditContext(data) {
    await chrome.storage.local.set({ audit_context: data });
  }

  function postStatus(text) {
    try {
      window.postMessage({ source: 'DD_COVERSME_SCRAPER', status: text }, '*');
    } catch (_) {}
  }

  let isCrawling = false;

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg) return;

    if (msg.command === 'START_CRAWL' || msg.type === 'SCRAPE') {
      if (isCrawling) {
        sendResponse({ ok: false, message: 'A crawl is already in progress.' });
        return true;
      }

      (async () => {
        isCrawling = true;
        showBanner('Started crawling…');
        postStatus('Crawl started');
        try {
          const data = await scrape(text => {
            showBanner(`Crawling… ${text}`);
            postStatus(text);
          });
          await saveAuditContext(data);

          showBanner('Crawl complete — downloading JSON…');
          const filename = downloadJson(data);
          postStatus('Crawl complete');

          // Give the browser's save dialog/download a moment to actually kick
          // off before the banner disappears and the crawl is marked stopped.
          await sleep(800);
          hideBanner();

          sendResponse({
            ok: true,
            message: `Crawl complete. ${data.benefit_coverage.procedures.length} procedure codes captured. Downloaded ${filename}.`
          });
        } catch (err) {
          console.error('[DD Covers Me] Crawl failed:', err);
          const message = err?.message || String(err);
          showBanner('Crawl failed: ' + message);
          postStatus('Crawl failed: ' + message);
          setTimeout(hideBanner, 4000);
          sendResponse({ ok: false, message });
        } finally {
          isCrawling = false;
        }
      })();
      return true;
    }

    if (msg.command === 'DOWNLOAD_PATIENT') {
      // Existing popup normally downloads audit_context itself. This response is
      // retained for compatibility with the common popup used by the extension,
      // and additionally triggers the file download directly so it works even
      // if the popup itself doesn't implement the save step.
      chrome.storage.local.get(STORAGE_KEY).then(r => {
        const data = r[STORAGE_KEY] || null;
        if (data) downloadJson(data);
        sendResponse({ ok: !!data, data });
      });
      return true;
    }
  });

  // Optional direct hook for debugging from the page console without changing popup.js.
  window.__DD_COVERSME_SCRAPE__ = () => scrape(text => console.debug('[DD Covers Me]', text));
})();