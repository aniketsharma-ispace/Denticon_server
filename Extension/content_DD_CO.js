(function () {
  const ALLOWED_HOSTS = ['deltadentalco.com', 'deltadental.com', 'deltadentalins.com'];
  if (!ALLOWED_HOSTS.some(h => window.location.hostname.includes(h))) return;

  const WAIT_MS = 20000;

  const PROCEDURE_TARGETS = {
    D0120: 'Periodic Exam',
    D0180: 'Perio Consult',
    D0140: 'Limited Exam',
    D0150: 'Comprehensive Exam',
    D0274: 'Bitewings',
    D0210: 'Full Mouth X-Ray',
    D0330: 'Panoramic X-Ray',
    D0220: 'PA X-Ray',
    D0364: 'Cone Beam',
    D0431: 'Oral Cancer Screening',
    D1110: 'Prophylaxis Adult',
    D1120: 'Prophylaxis Child',
    D1206: 'Fluoride',
    D1351: 'Sealants',
    D1510: 'Space Maintainer',
    D2391: 'Composite Filling',
    D2740: 'Porcelain Crown',
    D2950: 'Build-Up',
    D2962: 'Veneers',
    D6750: 'Bridge',
    D5110: 'Dentures',
    D9110: 'Palliative Treatment',
    D9222: 'General Anesthesia',
    D9230: 'Nitrous Oxide',
    D9243: 'General Sedation / IV Sedation',
    D9310: 'Consultation',
    D9944: 'Occlusal Guard',
    D4341: 'Scaling & Root Planing',
    D4355: 'Full Mouth Debridement',
    D4346: 'Gingivitis Treatment',
    D4910: 'Periodontal Maintenance',
    D4381: 'Arestin',
    D4260: 'Osseous Surgery',
    D4249: 'Crown Lengthening',
    D3310: 'Root Canal Anterior',
    D3330: 'Root Canal Molar',
    D7140: 'Simple Extraction',
    D7210: 'Surgical Extraction',
    D7240: 'Impacted Extraction',
    D7953: 'Bone Graft with Extraction',
    D6010: 'Implant',
    D6056: 'Implant Abutment'
  };

  const GENERAL_BENEFIT_CATEGORY_HINTS = {
    preventiveBenefits: ['diagnostic', 'preventive'],
    basicBenefits: ['basic', 'restorative', 'endo', 'perio'],
    majorBenefits: ['major', 'crown', 'prosthodontic', 'bridge', 'denture']
  };

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function text(v) {
    return (v || '').replace(/\s+/g, ' ').trim();
  }

  function q(selector, root = document) {
    try {
      return root?.querySelector?.(selector) || null;
    } catch {
      return null;
    }
  }

  function qa(selector, root = document) {
    try {
      return Array.from(root?.querySelectorAll?.(selector) || []);
    } catch {
      return [];
    }
  }

  function safeText(selector, root = document) {
    return text(q(selector, root)?.textContent || '');
  }

  function normalizeKey(key) {
    return text(key)
      .replace(/[:]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+(.)/g, (_, c) => c.toUpperCase());
  }

  function parseMoneySummary(raw) {
    const s = text(raw);
    return {
      used: s.match(/Used:\s*\$?([\d,]+(?:\.\d{2})?)/i)?.[1] || null,
      remaining: s.match(/Remaining:\s*\$?([\d,]+(?:\.\d{2})?)/i)?.[1] || null,
      totalAvailable: s.match(/Total Available:\s*\$?([\d,]+(?:\.\d{2})?)/i)?.[1] || null
    };
  }

  function getCurrentPathTab() {
    const href = window.location.href;
    if (href.includes('/dental-benefits/')) return 'Dental Benefits';
    if (href.includes('/limitations/')) return 'Limitations';
    if (href.includes('/coverage/')) return 'Coverage';
    if (href.includes('/claims/')) return 'Claims';
    if (href.includes('/treatment-plans/')) return 'Treatment Plans';
    if (href.includes('/history/')) return 'Patient History';
    return null;
  }

  async function waitForContent(selector, timeout = WAIT_MS, root = document) {
    if (q(selector, root)) return true;

    return new Promise((resolve, reject) => {
      const observer = new MutationObserver(() => {
        if (q(selector, root)) {
          observer.disconnect();
          resolve(true);
        }
      });

      const observeRoot = root === document ? (document.body || document.documentElement) : root;
      if (!observeRoot) {
        reject(new Error(`No root available while waiting for ${selector}`));
        return;
      }

      observer.observe(observeRoot, { childList: true, subtree: true });

      setTimeout(() => {
        observer.disconnect();
        reject(new Error(`Timeout waiting for ${selector}`));
      }, timeout);
    });
  }

  function scrapePatientInfo(root = document) {
    const name = safeText('mat-card-content .header h1', root) || safeText('.header h1', root);
    const urlMatch = window.location.pathname.match(
      /(?:dental-benefits|limitations|coverage|claims|treatment-plans|history)\/([^/]+)/
    );

    return {
      patientName: name || null,
      subscriberIdFromUrl: urlMatch?.[1] || null,
      pageTitle: document.title || null
    };
  }

  function getPatientRoot() {
    const patientInfo = scrapePatientInfo(document);
    const patientName = patientInfo?.patientName;
    const candidates = qa('mat-card, .mat-mdc-card, .patient-card, .member-card, .content-container, section, div');

    const scored = candidates
      .map(el => {
        const t = text(el.textContent || '');
        let score = 0;
        if (patientName && t.includes(patientName)) score += 5;
        if (t.includes('Dental Benefits')) score += 2;
        if (t.includes('Limitations')) score += 2;
        if (t.includes('Coverage')) score += 2;
        if (t.includes('Claims')) score += 2;
        if (t.includes('Treatment Plans')) score += 2;
        if (t.includes('Patient History')) score += 2;
        if (q('ks-patient-dental-benefits, ks-patient-limitations, ks-patient-coverage, ks-patient-claims, ks-treatment-plans, app-history', el)) score += 4;
        return { el, score };
      })
      .filter(x => x.score >= 6)
      .sort((a, b) => b.score - a.score);

    return scored[0]?.el || document;
  }

  async function clickMainTab(tabName, root = document) {
    const candidates = qa('a, button, [role="tab"], .mdc-tab', root);
    const target = candidates.find(el => text(el.textContent).toLowerCase() === tabName.toLowerCase());
    if (!target) return false;
    target.click();
    await sleep(1500);
    return true;
  }

  async function clickCoverageSubTab(tabName, root) {
    const candidates = qa('[role="tab"], .mdc-tab', root);
    const target = candidates.find(el => text(el.textContent).toLowerCase() === tabName.toLowerCase());
    if (!target) return false;
    target.click();
    await sleep(1200);
    return true;
  }

  function scrapePolicyInfo(root = document) {
    const info = {};
    qa('.policy-info .table-info--row', root).forEach(row => {
      const label = text(row.querySelector('.table-info--label')?.textContent || '');
      const value = text(row.querySelector('.table-info--value')?.textContent || '');
      if (label) info[normalizeKey(label)] = value || null;
    });
    return info;
  }

  function scrapeCleanings(root = document) {
    const c = q('.cleanings-container', root);
    if (!c) return null;

    const topText = qa(':scope > span, :scope > div', c)
      .map(el => text(el.textContent))
      .filter(Boolean);

    return {
      label: topText[0] || null,
      remaining: text(c.querySelector('.circle')?.textContent || '') || null,
      nextAvailable: text(c.querySelector('.date')?.textContent || '') || null
    };
  }

  function scrapeBenefits(root = document) {
    return qa('.benefits-indicator', root).map(el => {
      const title = text(el.querySelector('span:first-child')?.textContent || '');
      const left = text(el.querySelector('.benefits-info.left')?.textContent || '');
      const right = text(el.querySelector('.benefits-info.right')?.textContent || '');
      const parsed = parseMoneySummary(`${left} ${right}`);

      return {
        title: title || null,
        used: parsed.used,
        remaining: parsed.remaining,
        totalAvailable: parsed.totalAvailable,
        leftText: left || null,
        rightText: right || null
      };
    }).filter(Boolean);
  }

  function scrapeProceduresTable(root = document) {
    const scope = q('ks-common-procedures', root) || root;
    return qa('table tbody tr', scope).map(row => {
      const cols = row.querySelectorAll('td');
      if (!cols.length) return null;
      return {
        additionalLimits: !!cols[1]?.querySelector('.addition-limit-req'),
        type: text(cols[2]?.textContent || '') || null,
        howMany: text(cols[3]?.textContent || '') || null,
        ageLimit: text(cols[4]?.textContent || '') || null,
        nextAvailable: text(cols[5]?.textContent || '') || null,
        remaining: text(cols[6]?.textContent || '') || null
      };
    }).filter(r => r && r.type);
  }

  function scrapeDentalBenefitsTab(root = document) {
    const scope = q('ks-patient-dental-benefits', root);
    if (!scope) return { error: 'Dental Benefits tab not found' };

    return {
      benefitPeriod: safeText('.dental-benefits > div h3', scope) || null,
      policyInfo: scrapePolicyInfo(scope),
      cleanings: scrapeCleanings(scope),
      benefits: scrapeBenefits(scope),
      commonProcedures: scrapeProceduresTable(scope),
      maximumsApplyText: safeText('.max-apply-text', scope) || null,
      fullBenefitsLinkText: safeText('.tooltip-text a', scope) || null,
      frequenciesAndLimitsLinkText: safeText('.procedures ks-link-with-icon .link-copy', scope) || null
    };
  }

  function scrapeLimitationsTab(root = document) {
    const scope = q('ks-patient-limitations', root);
    if (!scope) return { error: 'Limitations tab not found' };

    return {
      note: safeText('.additional-info', scope) || null,
      procedures: scrapeProceduresTable(scope)
    };
  }

  function extractCoverageRows(scope, networkName) {
    return qa('table tbody tr', scope).map(row => {
      const cols = row.querySelectorAll('td');
      if (cols.length < 6) return null;
      return {
        network: networkName,
        benefitClass: text(cols[1]?.textContent || '') || null,
        coveragePercentage: text(cols[2]?.textContent || '') || null,
        deductibleWaived: text(cols[3]?.textContent || '') || null,
        waitingPeriod: text(cols[4]?.textContent || '') || null,
        eligibleForBenefitClass: text(cols[5]?.textContent || '') || null
      };
    }).filter(Boolean);
  }

  async function scrapeCoverageTab(root = document) {
    const scope = q('ks-patient-coverage', root);
    if (!scope) return { error: 'Coverage tab not found' };

    const result = {
      providerSelection: safeText('[id^="mat-select-value-"]', scope) || null,
      helpText: safeText('.info-block .message', scope) || null,
      alertText: safeText('.copy-container', scope) || null,
      networks: []
    };

    const subTabs = ['PPO', 'Premier', 'Out of Network'];
    for (const sub of subTabs) {
      const clicked = await clickCoverageSubTab(sub, scope);
      if (!clicked) continue;
      const activePanel = q('.mat-mdc-tab-body-active', scope) || q('mat-tab-body.mat-mdc-tab-body-active', scope) || scope;
      const rows = extractCoverageRows(activePanel, sub);
      result.networks.push({ network: sub, rows });
    }

    if (!result.networks.length) {
      const fallbackRows = extractCoverageRows(scope, 'Unknown');
      result.networks.push({ network: 'Unknown', rows: fallbackRows });
    }

    return result;
  }

  function scrapeClaimsTab(root = document) {
    const scope = q('ks-patient-claims', root);
    if (!scope) return { error: 'Patient Claims tab not found' };

    const claims = qa('ks-claim-detail', scope).map(card => {
      const infoRows = qa('.claim-info .info-row', card);
      const lineOne = infoRows[0];
      const lineTwo = infoRows[1];

      const providerValues = qa('.info-value', lineTwo || card)
        .map(el => text(el.textContent))
        .filter(Boolean);

      const claimNumberText = text(lineOne?.querySelector('.claim-number')?.textContent || '');
      const claimStatus = text(lineOne?.querySelector('.status')?.textContent || '');

      const lineItems = qa('.claim-line-items tbody tr', card).map(tr => {
        if (tr.classList.contains('total')) {
          const tds = tr.querySelectorAll('td');
          return {
            rowType: 'total',
            totalWePay: text(tds[1]?.textContent || '') || null,
            totalPatientPays: text(tds[2]?.textContent || '') || null
          };
        }

        const tds = tr.querySelectorAll('td');
        if (tds.length < 5) return null;
        return {
          rowType: 'item',
          date: text(tds[0]?.textContent || '') || null,
          code: text(tds[1]?.textContent || '') || null,
          procedure: text(tds[2]?.textContent || '') || null,
          wePay: text(tds[3]?.textContent || '') || null,
          patientPays: text(tds[4]?.textContent || '') || null
        };
      }).filter(Boolean);

      return {
        claimNumber: claimNumberText || null,
        claimStatus: claimStatus || null,
        providerName: providerValues[0] || null,
        providerAddressLine1: providerValues[1] || null,
        providerAddressLine2: providerValues[2] || null,
        lineItems
      };
    });

    return {
      dateInputs: qa('input.dateInput', scope).map(el => ({ id: el.id || null, value: el.value || null })),
      claims,
      paginatorText: safeText('.mat-mdc-paginator-range-label', scope) || null
    };
  }

  function scrapeTreatmentPlansTab(root = document) {
    const scope = q('ks-treatment-plans', root);
    if (!scope) return { error: 'Treatment Plans tab not found' };

    const emptyMessage = safeText('.no-claims-found.error-container', scope) || null;
    const rows = qa('table tbody tr', scope).map(tr => {
      const tds = qa('td', tr).map(td => text(td.textContent));
      return tds.length ? tds : null;
    }).filter(Boolean);

    return { emptyMessage, rows };
  }

  function scrapePatientHistoryTab(root = document) {
    const scope = q('app-history', root);
    if (!scope) return { error: 'Patient History tab not found' };

    const rows = qa('.patient-history-content mat-row, .patient-history-content .mat-mdc-row', scope).map(row => {
      const cells = qa('mat-cell, .mat-mdc-cell', row);
      if (cells.length < 6) return null;
      return {
        dateOfService: text(cells[0]?.textContent || '') || null,
        code: text(cells[1]?.textContent || '') || null,
        procedureDesc: text(cells[2]?.textContent || '') || null,
        tooth: text(cells[3]?.textContent || '') || null,
        surface: text(cells[4]?.textContent || '') || null,
        area: text(cells[5]?.textContent || '') || null
      };
    }).filter(Boolean);

    return {
      dateInputs: qa('input.dateInput', scope).map(el => ({ id: el.id || null, value: el.value || null })),
      rows,
      paginatorText: safeText('.mat-mdc-paginator-range-label', scope) || null
    };
  }

  function deriveCoverageAndMaximums(dentalBenefits, coverage) {
    const indicators = dentalBenefits?.benefits || [];
    const findIndicator = parts => indicators.find(item => parts.every(p => (item.title || '').toLowerCase().includes(p.toLowerCase())));
    const individualAnnualDed = findIndicator(['individual', 'annual', 'deductible']);
    const familyAnnualDed = findIndicator(['family', 'annual', 'deductible']);
    const ortho = findIndicator(['orthodontic']);

    const generalBenefitCategories = { preventiveBenefits: null, basicBenefits: null, majorBenefits: null };
    (coverage?.networks || []).forEach(net => {
      (net.rows || []).forEach(row => {
        const t = (row.benefitClass || '').toLowerCase();
        Object.entries(GENERAL_BENEFIT_CATEGORY_HINTS).forEach(([key, hints]) => {
          if (!generalBenefitCategories[key] && hints.some(h => t.includes(h))) {
            generalBenefitCategories[key] = {
              network: net.network,
              benefitClass: row.benefitClass,
              coveragePercentage: row.coveragePercentage
            };
          }
        });
      });
    });

    return {
      yearlyMaximum: null,
      yearlyMaximumRemaining: null,
      individualDeductiblePaidToDate: individualAnnualDed?.used || null,
      individualDeductibleRemaining: individualAnnualDed?.remaining || null,
      familyDeductible: familyAnnualDed?.totalAvailable || null,
      familyDeductiblePaidToDate: familyAnnualDed?.used || null,
      familyDeductibleRemaining: familyAnnualDed?.remaining || null,
      deductibleAppliesToPreventive: null,
      deductibleAppliesToDiagnostic: null,
      orthodonticDeductible: null,
      orthodonticDeductiblePaidToDate: null,
      orthodonticMaximum: ortho?.totalAvailable || null,
      orthodonticMaximumPaidToDate: ortho?.used || null,
      generalBenefitCategories
    };
  }

  function buildProcedureMap(limitations, coverage, claims, history) {
    const out = {};
    Object.entries(PROCEDURE_TARGETS).forEach(([code, label]) => {
      const limitation = (limitations?.procedures || []).find(row =>
        (row.type || '').toLowerCase().includes(label.toLowerCase()) ||
        (row.type || '').toLowerCase().includes(code.toLowerCase())
      );

      const coverageMatches = [];
      (coverage?.networks || []).forEach(net => {
        (net.rows || []).forEach(row => {
          const hay = `${row.benefitClass || ''}`.toLowerCase();
          if (hay.includes(code.toLowerCase()) || hay.includes(label.toLowerCase())) {
            coverageMatches.push({
              network: net.network,
              benefitClass: row.benefitClass,
              coveragePercentage: row.coveragePercentage,
              deductible: row.deductibleWaived,
              coverageDetails: row.eligibleForBenefitClass,
              waitingPeriod: row.waitingPeriod
            });
          }
        });
      });

      const claimHistory = [];
      (claims?.claims || []).forEach(claim => {
        (claim.lineItems || []).forEach(item => {
          if (item.rowType === 'item' && item.code === code) {
            claimHistory.push({
              claimNumber: claim.claimNumber,
              claimStatus: claim.claimStatus,
              date: item.date,
              procedure: item.procedure,
              wePay: item.wePay,
              patientPays: item.patientPays
            });
          }
        });
      });

      const patientHistoryRows = (history?.rows || []).filter(r => r.code === code);
      out[code] = {
        label,
        frequency: limitation?.howMany || null,
        coveragePercentage: coverageMatches[0]?.coveragePercentage || null,
        deductible: coverageMatches[0]?.deductible || null,
        coverageDetails: coverageMatches,
        ageLimit: limitation?.ageLimit || null,
        nextAvailable: limitation?.nextAvailable || null,
        remaining: limitation?.remaining || null,
        history: [...patientHistoryRows, ...claimHistory]
      };
    });
    return out;
  }

  async function scrapeAllTabs() {
    const warnings = [];
    await waitForContent('body', WAIT_MS);

    const patientRoot = getPatientRoot();
    if (!patientRoot) {
      throw new Error('Patient container not found');
    }

    const patientInfo = scrapePatientInfo(patientRoot);
    const result = {
      pageUrl: window.location.href,
      scrapedAt: new Date().toISOString(),
      startedFromTab: getCurrentPathTab(),
      patientInfo,
      dentalBenefits: null,
      limitations: null,
      coverage: null,
      claims: null,
      treatmentPlans: null,
      patientHistory: null,
      coverageAndMaximums: null,
      orthodontics: null,
      completePlanProvisionsInfo: null,
      procedures: {},
      extractionMeta: {
        warnings,
        hostname: window.location.hostname,
        title: document.title
      }
    };

    const tabs = [
      { name: 'Dental Benefits', key: 'dentalBenefits', selector: 'ks-patient-dental-benefits', scrape: scrapeDentalBenefitsTab },
      { name: 'Limitations', key: 'limitations', selector: 'ks-patient-limitations', scrape: scrapeLimitationsTab },
      { name: 'Coverage', key: 'coverage', selector: 'ks-patient-coverage', scrape: scrapeCoverageTab },
      { name: 'Claims', key: 'claims', selector: 'ks-patient-claims', scrape: scrapeClaimsTab },
      { name: 'Treatment Plans', key: 'treatmentPlans', selector: 'ks-treatment-plans', scrape: scrapeTreatmentPlansTab },
      { name: 'Patient History', key: 'patientHistory', selector: 'app-history', scrape: scrapePatientHistoryTab }
    ];

    for (const tab of tabs) {
      const clicked = await clickMainTab(tab.name, patientRoot);
      if (!clicked) {
        warnings.push(`Could not click patient tab: ${tab.name}`);
        result[tab.key] = { error: `${tab.name} tab not clickable in patient panel` };
        continue;
      }

      try {
        await waitForContent(tab.selector, WAIT_MS, patientRoot);
      } catch (err) {
        warnings.push(`Timed out waiting for ${tab.name}: ${err.message}`);
      }

      try {
        result[tab.key] = await tab.scrape(patientRoot);
      } catch (err) {
        result[tab.key] = { error: err.message };
        warnings.push(`Failed scraping ${tab.name}: ${err.message}`);
      }
    }

    result.coverageAndMaximums = deriveCoverageAndMaximums(result.dentalBenefits, result.coverage);
    result.orthodontics = {
      orthodonticDeductible: result.coverageAndMaximums.orthodonticDeductible,
      orthodonticDeductiblePaidToDate: result.coverageAndMaximums.orthodonticDeductiblePaidToDate,
      orthodonticMaximum: result.coverageAndMaximums.orthodonticMaximum,
      orthodonticMaximumPaidToDate: result.coverageAndMaximums.orthodonticMaximumPaidToDate
    };
    result.completePlanProvisionsInfo = result.dentalBenefits?.fullBenefitsLinkText || null;
    result.procedures = buildProcedureMap(result.limitations, result.coverage, result.claims, result.patientHistory);
    return result;
  }

  function scrapeVisibleOnly() {
    const patientRoot = getPatientRoot();
    return {
      pageUrl: window.location.href,
      scrapedAt: new Date().toISOString(),
      activeTab: getCurrentPathTab(),
      patientInfo: scrapePatientInfo(patientRoot),
      dentalBenefits: scrapeDentalBenefitsTab(patientRoot),
      limitations: scrapeLimitationsTab(patientRoot),
      claims: scrapeClaimsTab(patientRoot),
      treatmentPlans: scrapeTreatmentPlansTab(patientRoot),
      patientHistory: scrapePatientHistoryTab(patientRoot)
    };
  }

  function triggerDeltaCODownload(data) {
    const sanitize = (s) => (s || "").trim().replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "").toLowerCase();
    const patient = sanitize(data?.patientInfo?.patientName) || "patient";
    const filename = `${patient}_Delta_Dental_CO.json`;

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(url);
    document.body.removeChild(a);
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.command === 'START_CRAWL') {
    scrapeAllTabs()
      .then(async (data) => {
        const result = await chrome.storage.local.get("audit_context");
        const context = result.audit_context || {};
        context.delta_co_data = data;
        await chrome.storage.local.set({ audit_context: context });

        triggerDeltaCODownload(data);

        sendResponse({ success: true });
      })
      .catch(err => sendResponse({ success: false, error: err.message }));
    return true;
  }
});


  window.__deltaDentalScraper = {
    getPatientRoot,
    scrapeAllTabs,
    scrapeVisibleOnly,
    scrapeDentalBenefitsTab,
    scrapeLimitationsTab,
    scrapeCoverageTab,
    scrapeClaimsTab,
    scrapeTreatmentPlansTab,
    scrapePatientHistoryTab
  }
})();