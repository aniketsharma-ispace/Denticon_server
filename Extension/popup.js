// popup.js - multi-carrier popup with Delta Dental Office Toolkit + Delta Dental MO state-safe support

document.addEventListener('DOMContentLoaded', async () => {
    const status      = document.getElementById('status');
    const btnCrawl    = document.getElementById('btnCrawl');
    const btnDownload = document.getElementById('btnDownload');
    const appTitle    = document.getElementById('appTitle');
    const divider     = document.querySelector('hr');

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = tab?.url || '';

    const isOverview   = url.toLowerCase().includes('advancedpatientoverview.aspx');
    const isInsurance  = url.toLowerCase().includes('advancededitpatientinsurance.aspx') || url.includes('c2.denticon.com');
    const isDenticon   = url.includes('denticon.com') || url.includes('planetdds.com');
    const isMetLife    = url.includes('metlife.com');
    const isCigna      = url.includes('cignaforhcp.cigna.com');
    const isDeltaINS   = url.includes('deltadentalins.com');
    const isDeltaVA    = url.includes('deltadentalva.com');
    const isAetna      = url.includes('claimconnect.dentalxchange.com');
    const isDeltaRI    = url.includes('deltadentalri.com');
    const isDeltaAR    = url.includes('my.deltadentalar.com');
    const isUCCI       = url.includes('unitedconcordia.com/');
    const isDeltaNJ    = url.includes('deltadentalnj.com/');
    const isDeltaWA    = url.includes('deltadentalwa.com/');
    const isDentaquest = url.includes('providers.dentaquest.com/');
    const isDeltaCO    = url.includes('deltadentalco.com/');
    const isDeltaIL    = url.includes('deltadentalil.com/');
    const isDeltaMA    = url.includes('deltadentalma.com/');
    const isDNOA       = url.includes('dnoaconnect.com/');
    const isDeltaToolkit = url.includes('dentalofficetoolkit.com');
    const isDeltaMO = url.includes('providers.deltadentalmo.com');
    const isGuardian   = url.includes('guardiananytime.com');
    // Must match the Toolkit entry in manifest.json's host_permissions.
    const TOOLKIT_ORIGINS = ['https://www.dentalofficetoolkit.com/dot-ui/member-benefits/*'];
    let toolkitSiteAccess = true;
    if (isDeltaToolkit && chrome.permissions?.contains) {
        try { toolkitSiteAccess = await chrome.permissions.contains({ origins: TOOLKIT_ORIGINS }); } catch (_) { toolkitSiteAccess = true; }
    }
    const toolkitNotLoadedText = toolkitSiteAccess
        ? 'Delta Toolkit extractor not loaded. Refresh this Toolkit tab, then retry. If it persists in Firefox, check the version is 128+ and the browser console for a script load error.'
        : 'This browser has not allowed the extension to access dentalofficetoolkit.com. Click Crawl to allow it; the page will reload.';
    async function diagnoseToolkitInjection() {
        const probe = async world => {
            try {
                const [result] = await chrome.scripting.executeScript({
                    target: { tabId: tab.id },
                    world,
                    func: () => ({
                        spec: Boolean(globalThis.__DELTA_TOOLKIT_REQUIREMENTS_SPEC__),
                        isolated: Boolean(globalThis.__DELTA_TOOLKIT_ISOLATED_INSTALLED__),
                        main: Boolean(globalThis.__DELTA_TOOLKIT_MAIN_INSTALLED__)
                    })
                });
                return result?.result || null;
            } catch (error) {
                return { error: error?.message || String(error) };
            }
        };
        const isolated = await probe('ISOLATED');
        const main = await probe('MAIN');
        console.warn('Delta Toolkit injection diagnosis', { isolated, main });
        if (isolated?.error) return `The browser will not let the extension run on this page: ${isolated.error}. Check site access for the extension and any company browser policy.`;
        if (!isolated?.spec && !isolated?.isolated) return 'Neither toolkit_requirements.generated.js nor content_dd_toolkit.js was injected. Reload this tab. If it repeats, the generated file is missing from the extension folder or a company policy blocks extensions on this site.';
        if (isolated?.spec && !isolated?.isolated) return 'content_dd_toolkit.js crashed while loading. Press F12 on this tab and send the red error from the Console.';
        if (!isolated?.spec) return 'toolkit_requirements.generated.js is missing or failed to load.';
        if (main?.error) return `The page-level extractor could not be checked: ${main.error}`;
        if (!main?.main) return 'The page-level extractor did not load. Firefox needs version 128+ for this. Reload the tab and retry.';
        return 'Extractor scripts are loaded but did not answer. Reload this tab and retry.';
    }

    const result = await chrome.storage.local.get([
        'audit_context',
        'crawl_progress',
        'delta_toolkit_progress',
        'delta_mo_progress'
    ]);
    const context = result.audit_context || {};
    const savedProgress = result.crawl_progress || null;
    const savedToolkitProgress = result.delta_toolkit_progress || null;
    const savedMOProgress = result.delta_mo_progress || null;


    if (isDeltaToolkit) {
        appTitle.textContent = 'Delta Toolkit Scraper';
        btnDownload.textContent = 'Download Stored Toolkit JSON';
    } else if (isDeltaMO) {
        appTitle.textContent = 'Delta Dental MO Scraper';
        btnDownload.textContent = 'Download Stored DD MO JSON';
    } else if (isGuardian) {
        appTitle.textContent = 'Guardian Scraper';
        btnCrawl.textContent = 'Crawl & Download';
        btnDownload.style.display = 'none';
        if (divider) divider.style.display = 'none';
        btnCrawl.id = 'btnGuardianCrawl';
    } else if (isAetna) {
        appTitle.textContent = 'ClaimConnect Scraper';
        btnDownload.textContent = 'Download Aetna Patient JSON';
    } else {
        appTitle.textContent = 'Insurance Scraper';
        btnDownload.textContent = 'Download Captured JSON';
    }

    function renderDDRIProgress(payload) {
        if (!payload || payload.carrier !== 'DDRI') return;
        const pct = Number.isFinite(Number(payload.progress))
            ? Math.max(0, Math.min(100, Math.round(Number(payload.progress))))
            : null;
        const lines = [pct === null ? 'DD_RI crawl running' : `DD_RI crawl: ${pct}%`];
        if (payload.title) lines.push(payload.title);
        if (payload.message) lines.push(payload.message);
        status.textContent = lines.join('\n');

        const done = payload.state === 'COMPLETE';
        const failed = payload.state === 'FAILED';
        btnCrawl.disabled = !done && !failed;
        btnCrawl.textContent = done ? 'Crawl Again' : (failed ? 'Retry Crawl' : 'Crawling...');
    }

    function renderToolkitStatus(payload) {
        if (!isDeltaToolkit || !payload) return;
        const text = payload.status || payload.message || 'Delta Toolkit: checking member/API context…';
        status.textContent = text;

        const state = payload.state || '';
        const running = state === 'RUNNING';
        const failed = state === 'FAILED';
        const complete = state === 'COMPLETE' || state === 'PARTIAL';

        if (running) {
            btnCrawl.disabled = true;
            btnCrawl.textContent = 'Crawling...';
            return;
        }

        btnCrawl.disabled = false;
        if (failed) {
            btnCrawl.textContent = 'Retry Crawl';
        } else if (complete) {
            btnCrawl.textContent = 'Crawl Again';
        } else if (payload.ready === false) {
            btnCrawl.textContent = 'Check / Crawl';
        } else {
            btnCrawl.textContent = 'Crawl Full Insurance Plan';
        }
    }

    function renderMOStatus(payload) {
        if (!isDeltaMO || !payload) return;
        status.textContent = payload.status || payload.message || 'DD MO: checking member/API context…';

        const state = payload.state || '';
        if (state === 'RUNNING') {
            btnCrawl.disabled = true;
            btnCrawl.textContent = 'Crawling...';
            return;
        }

        btnCrawl.disabled = false;
        if (state === 'FAILED') {
            btnCrawl.textContent = 'Retry Crawl';
        } else if (state === 'COMPLETE' || state === 'PARTIAL') {
            btnCrawl.textContent = 'Crawl Again';
        } else if (payload.ready === false) {
            btnCrawl.textContent = 'Check / Crawl';
        } else {
            btnCrawl.textContent = 'Crawl Full Insurance Plan';
        }
    }

    function renderGuardianStatus(payload) {
        if (!isGuardian || !payload) return;
        status.textContent = payload.status || 'Guardian: checking...';

        const state = String(payload.state || '').toUpperCase();
        const running = state === 'RUNNING';
        const done = state === 'DONE';
        const failed = state === 'FAILED';

        if (running) {
            btnCrawl.disabled = true;
            btnCrawl.textContent = `Crawling... (${payload.completed || 0}/${payload.total || 59})`;
            return;
        }

        btnCrawl.disabled = false;
        if (done) {
            btnCrawl.textContent = 'Download Again';
        } else if (failed) {
            btnCrawl.textContent = 'Retry Crawl';
        } else {
            btnCrawl.textContent = Number(payload.completed || 0) > 0
                ? 'Retry Crawl'
                : 'Crawl & Download';
        }
    }

    async function waitForDownloadCompletion(downloadId, timeoutMs = 20000) {
        const first = await chrome.downloads.search({ id: downloadId });
        const current = first && first[0];
        if (current?.state === 'complete') return current;
        if (current?.state === 'interrupted') {
            throw new Error(`Download interrupted${current.error ? ` (${current.error})` : ''}`);
        }

        return new Promise((resolve, reject) => {
            let settled = false;
            const timer = setTimeout(() => {
                cleanup();
                reject(new Error('Download started but did not complete within 20 seconds'));
            }, timeoutMs);

            const cleanup = () => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                try { chrome.downloads.onChanged.removeListener(onChanged); } catch (_) {}
            };

            const finish = (fn, value) => {
                if (settled) return;
                cleanup();
                fn(value);
            };

            const onChanged = async (delta) => {
                if (delta.id !== downloadId || !delta.state) return;
                if (delta.state.current === 'complete') {
                    try {
                        const items = await chrome.downloads.search({ id: downloadId });
                        finish(resolve, items?.[0] || { id: downloadId, state: 'complete' });
                    } catch (_) {
                        finish(resolve, { id: downloadId, state: 'complete' });
                    }
                } else if (delta.state.current === 'interrupted') {
                    try {
                        const items = await chrome.downloads.search({ id: downloadId });
                        const item = items?.[0];
                        finish(reject, new Error(`Download interrupted${item?.error ? ` (${item.error})` : ''}`));
                    } catch (_) {
                        finish(reject, new Error('Download interrupted'));
                    }
                }
            };

            chrome.downloads.onChanged.addListener(onChanged);

            // Close the race where the item completed between the first search
            // and listener registration.
            chrome.downloads.search({ id: downloadId }).then(items => {
                const item = items?.[0];
                if (item?.state === 'complete') finish(resolve, item);
                else if (item?.state === 'interrupted') finish(reject, new Error(`Download interrupted${item.error ? ` (${item.error})` : ''}`));
            }).catch(() => {});
        });
    }

    async function downloadObject(data, filename, clearAllContext = false, closeAfterDownload = false) {
        const json = JSON.stringify(data, null, 2);
        const encoded = encodeURIComponent(json);
        // Use a data: URL instead of a popup-owned blob: URL. A popup can be
        // destroyed immediately after a download starts; Firefox/Chrome may
        // then lose access to the blob URL before the download has consumed it.
        // Data URLs are self-contained and avoid that lifecycle race.
        const dataUrl = `data:application/json;charset=utf-8,${encoded}`;

        let downloadId = null;
        try {
            downloadId = await chrome.downloads.download({
                url: dataUrl,
                filename,
                saveAs: false,
                conflictAction: 'uniquify'
            });
            await waitForDownloadCompletion(downloadId);
        } catch (primaryErr) {
            console.warn('Primary Guardian download failed:', primaryErr);

            // Fallback for browsers that reject a data: URL from the downloads
            // API. Keep the object URL alive until the download itself completes.
            const blob = new Blob([json], { type: 'application/json;charset=utf-8' });
            const objectUrl = URL.createObjectURL(blob);
            try {
                downloadId = await chrome.downloads.download({
                    url: objectUrl,
                    filename,
                    saveAs: false,
                    conflictAction: 'uniquify'
                });
                await waitForDownloadCompletion(downloadId);
            } finally {
                URL.revokeObjectURL(objectUrl);
            }
        }

        if (clearAllContext) {
            await chrome.storage.local.remove('audit_context');
            status.textContent = 'Success: Data Exported & Cleared';
        } else {
            status.textContent = 'Guardian JSON downloaded successfully.';
        }

        if (closeAfterDownload) {
            setTimeout(() => window.close(), 450);
        }
        return downloadId;
    }

    // IMPORTANT: install Toolkit/Guardian listeners BEFORE requesting status or
    // starting a crawl. This prevents early STARTED/progress messages from being missed.
    if (isGuardian) {
        chrome.runtime.onMessage.addListener((msg) => {
            if (msg?.command === 'STATUS_UPDATE' && msg?.carrier === 'GUARDIAN') {
                renderGuardianStatus(msg);
            }
        });

        chrome.storage.onChanged.addListener((changes, areaName) => {
            if (areaName === 'local' && changes.guardian_progress?.newValue) {
                renderGuardianStatus(changes.guardian_progress.newValue);
            }
        });
    }

    if (isDeltaToolkit) {
        chrome.runtime.onMessage.addListener((msg) => {
            if (msg?.command === 'STATUS_UPDATE' && msg?.carrier === 'DELTA_TOOLKIT') {
                renderToolkitStatus(msg);
            }
        });

        chrome.storage.onChanged.addListener((changes, areaName) => {
            if (areaName === 'local' && changes.delta_toolkit_progress?.newValue) {
                renderToolkitStatus(changes.delta_toolkit_progress.newValue);
            }
        });
    }

    if (isDeltaMO) {
        chrome.runtime.onMessage.addListener((msg) => {
            if (msg?.command === 'STATUS_UPDATE' && msg?.carrier === 'DELTA_MO') {
                renderMOStatus(msg);
            }
        });

        chrome.storage.onChanged.addListener((changes, areaName) => {
            if (areaName === 'local' && changes.delta_mo_progress?.newValue) {
                renderMOStatus(changes.delta_mo_progress.newValue);
            }
        });
    }

    if (isDeltaRI) {
        chrome.runtime.onMessage.addListener((msg) => {
            if (msg?.type === 'PROGRESS_UPDATE' && msg.payload?.carrier === 'DDRI') {
                renderDDRIProgress(msg.payload);
            }
        });

        chrome.storage.onChanged.addListener((changes, areaName) => {
            if (areaName === 'local' && changes.crawl_progress?.newValue?.carrier === 'DDRI') {
                renderDDRIProgress(changes.crawl_progress.newValue);
            }
        });
    }

    if (isOverview) {
        status.textContent = 'Patient Overview detected. Click Download to capture patient data.';
    } else if (isInsurance) {
        status.textContent = 'Insurance tab detected. Click Crawl to scrape all plans.';
    } else if (isMetLife && context.metlife_data) {
        status.textContent = 'MetLife Data: Ready';
    } else if (isCigna && context.cigna_data) {
        status.textContent = 'Cigna Data: Ready';
    } else if (isDenticon && context.denticon_data) {
        status.textContent = `Denticon Ready: ${context.denticon_data.header?.patient_name || 'Active'}`;
    } else if (isDeltaINS) {
        status.textContent = 'DeltaDental_INS Data: Ready';
    } else if (isDeltaVA) {
        status.textContent = 'DD_VA: Ready';
    } else if (isAetna) {
        status.textContent = 'ClaimConnect detected. Click Crawl to scrape plan benefits.';
    } else if (isDeltaRI) {
        if (savedProgress && savedProgress.carrier === 'DDRI' && !['COMPLETE', 'FAILED'].includes(savedProgress.state)) {
            renderDDRIProgress(savedProgress);
        } else {
            status.textContent = 'DD_RI: Ready. Click Crawl to start.';
        }
    } else if (isDeltaAR) {
        status.textContent = 'DD_AR: Ready';
    } else if (isUCCI) {
        status.textContent = 'UCCI: Ready';
    } else if (isDeltaNJ) {
        status.textContent = 'DD_NJ: Ready';
    } else if (isDeltaWA) {
        status.textContent = 'DD_WA: Ready';
    } else if (isDentaquest) {
        status.textContent = 'DentaQuest: Ready';
    } else if (isDeltaCO) {
        status.textContent = 'DD_CO: Ready';
    } else if (isDeltaIL) {
        status.textContent = 'DD_IL: Ready';
    } else if (isDeltaMA) {
        status.textContent = 'DD_MA: Ready';
    } else if (isDNOA) {
        status.textContent = 'DNOA: Ready';
    } else if (isGuardian) {
        status.textContent = 'Guardian: checking VOB capture...';
    } else if (isDeltaToolkit) {
        status.textContent = 'Delta Toolkit: checking member/API context…';
        if (savedToolkitProgress && Date.now() - Number(savedToolkitProgress.updated_at || 0) < 10 * 60 * 1000) {
            renderToolkitStatus(savedToolkitProgress);
        }
    } else if (isDeltaMO) {
        status.textContent = 'DD MO: checking member/API context…';
        if (savedMOProgress && Date.now() - Number(savedMOProgress.updated_at || 0) < 10 * 60 * 1000) {
            renderMOStatus(savedMOProgress);
        }
    } else {
        status.textContent = 'Navigate to a supported patient/insurance page to begin.';
    }

    // Query the actual Toolkit state instead of assuming that being on the site means Ready.
    if (isDeltaToolkit) {
        chrome.tabs.sendMessage(tab.id, { command: 'GET_TOOLKIT_STATUS' }, (response) => {
            if (chrome.runtime.lastError) {
                status.textContent = toolkitNotLoadedText;
                if (toolkitSiteAccess) diagnoseToolkitInjection().then(text => { status.textContent = text; });
                btnCrawl.disabled = false;
                btnCrawl.textContent = 'Retry Crawl';
                return;
            }
            if (response) renderToolkitStatus(response);
        });
    }

    if (isDeltaMO) {
        chrome.tabs.sendMessage(tab.id, { command: 'GET_MO_STATUS' }, (response) => {
            if (chrome.runtime.lastError) {
                status.textContent = 'DD MO extractor not loaded. Refresh this portal tab, then retry.';
                btnCrawl.disabled = false;
                btnCrawl.textContent = 'Retry Crawl';
                return;
            }
            if (response) renderMOStatus(response);
        });
    }

    if (isGuardian) {
        chrome.tabs.sendMessage(tab.id, { command: 'GET_GUARDIAN_STATUS' }, (response) => {
            if (chrome.runtime.lastError) {
                status.textContent = 'Guardian extractor not loaded. Refresh the Dental Eligibility tab, then retry.';
                return;
            }
            if (response) renderGuardianStatus({ ...response, state: response.sweepState?.toUpperCase() });
        });
    }

    btnDownload.onclick = () => {
        if (isAetna) {
            chrome.scripting.executeScript({
                target: { tabId: tab.id },
                func: () => { window.__aetnaDownload?.(); }
            }).then(() => window.close());
            return;
        }

        if (isOverview) {
            chrome.tabs.sendMessage(tab.id, { command: 'DOWNLOAD_PATIENT' }, () => {
                if (chrome.runtime.lastError) {
                    status.textContent = 'Error: Refresh the page and try again.';
                } else {
                    status.textContent = 'Downloading patient data...';
                    setTimeout(() => window.close(), 1200);
                }
            });
            return;
        }

        if (isDeltaMO) {
            const moData = context.delta_mo_data;
            if (!moData) {
                alert('No DD MO extraction is stored yet. Run Crawl first.');
                return;
            }
            downloadObject(moData, `Delta_MO_${Date.now()}.json`, false);
            return;
        }

        if (isDeltaToolkit) {
            const toolkitData = context.delta_toolkit_export;
            if (!toolkitData) {
                alert('No Delta Toolkit extraction is stored yet. Run Crawl first.');
                return;
            }
            downloadObject(toolkitData, context.delta_toolkit_export_filename || `Delta_Toolkit_${Date.now()}.json`, false);
            return;
        }

        if (Object.keys(context).length === 0) {
            alert('No data captured yet.');
            return;
        }
        downloadObject(context, `Insurance_Audit_${Date.now()}.json`, true);
    };

    btnCrawl.onclick = () => {
        if (isAetna) {
            // content_aetna.js crawls and downloads through window.__aetnaDownload.
            chrome.scripting.executeScript({
                target: { tabId: tab.id },
                func: () => { window.__aetnaDownload?.(); }
            }).then(() => {
                status.textContent = 'Crawl started...';
                window.close();
            }).catch((err) => {
                status.textContent = 'Error: Refresh the ClaimConnect page and try again.';
                console.warn('Aetna crawl error:', err);
            });
            return;
        }

        if (isDeltaMO) {
            btnCrawl.disabled = true;
            btnCrawl.textContent = 'Crawling...';
            status.textContent = 'DD MO: validating member + auth context…';

            chrome.tabs.sendMessage(tab.id, { command: 'START_CRAWL' }, (response) => {
                if (chrome.runtime.lastError) {
                    status.textContent = 'DD MO extractor unavailable. Refresh the portal tab and retry.';
                    btnCrawl.disabled = false;
                    btnCrawl.textContent = 'Retry Crawl';
                    console.warn('DD MO crawl message error:', chrome.runtime.lastError.message);
                    return;
                }
                if (!response?.started) {
                    status.textContent = response?.status || 'DD MO could not start.';
                    btnCrawl.disabled = false;
                    btnCrawl.textContent = 'Retry Crawl';
                    return;
                }
                status.textContent = response.status || 'DD MO crawl started…';
            });
            return;
        }

        if (isDeltaToolkit) {
            if (!toolkitSiteAccess) {
                chrome.permissions.request({ origins: TOOLKIT_ORIGINS }).then(granted => {
                    if (!granted) {
                        status.textContent = 'Site access was not allowed, so the extension cannot run on the Toolkit page.';
                        return;
                    }
                    toolkitSiteAccess = true;
                    status.textContent = 'Site access allowed. The Toolkit page is reloading — open this popup and click Crawl once it finishes loading.';
                    chrome.tabs.reload(tab.id);
                }).catch(error => {
                    status.textContent = `Could not request site access: ${error.message}`;
                });
                return;
            }
            btnCrawl.disabled = true;
            btnCrawl.textContent = 'Crawling...';
            status.textContent = 'Delta Toolkit: extracting the global workbook code scope for the current portal member/plan…';

            chrome.tabs.sendMessage(tab.id, { command: 'START_CRAWL' }, (response) => {
                if (chrome.runtime.lastError) {
                    status.textContent = toolkitNotLoadedText;
                    if (toolkitSiteAccess) diagnoseToolkitInjection().then(text => { status.textContent = text; });
                    btnCrawl.disabled = false;
                    btnCrawl.textContent = 'Retry Crawl';
                    console.warn('Delta Toolkit crawl message error:', chrome.runtime.lastError.message);
                    return;
                }
                if (!response?.started) {
                    status.textContent = response?.status || 'Delta Toolkit could not start.';
                    btnCrawl.disabled = false;
                    btnCrawl.textContent = 'Retry Crawl';
                    return;
                }
                status.textContent = response.status || 'Delta Toolkit crawl started…';
            });
            return;
        }

        if (isGuardian) {
            // The content script owns the Guardian download, exactly like every
            // other portal: it saves <patient>_guardian_benefits.json, the name
            // the Sabrina audit asks offices to upload. The popup must not save
            // a second copy under a different name.
            //
            // Once a patient has completed a crawl, START_CRAWL does not hit
            // Guardian's CDT endpoint again - the content script just re-saves
            // the JSON. With a code search still missing it offers those
            // searches again. A new patient/VOB capture resets the state.
            chrome.tabs.sendMessage(tab.id, { command: 'GET_GUARDIAN_STATUS' }, (current) => {
                if (chrome.runtime.lastError) {
                    status.textContent = 'Guardian extractor not loaded. Refresh the Dental Eligibility tab, then retry.';
                    return;
                }

                if (current?.sweepState !== 'done') {
                    btnCrawl.disabled = true;
                    btnCrawl.textContent = 'Crawling...';
                    status.textContent = 'Guardian: building 59 procedure-code records from captured Plan Options...';
                }

                chrome.tabs.sendMessage(tab.id, { command: 'START_CRAWL' }, (response) => {
                    if (chrome.runtime.lastError) {
                        status.textContent = 'Guardian extractor not loaded. Refresh the tab and retry.';
                        btnCrawl.disabled = false;
                        btnCrawl.textContent = 'Retry Crawl';
                        return;
                    }
                    if (response?.ready) {
                        status.textContent = 'Guardian JSON saved to your Downloads folder.';
                        return;
                    }
                    if (response) status.textContent = response.status || status.textContent;
                    if (response?.started) {
                        // A finished patient with a code search still missing
                        // re-runs those searches, so show the running state.
                        btnCrawl.disabled = true;
                        btnCrawl.textContent = 'Crawling...';
                    } else if (response) {
                        btnCrawl.disabled = false;
                    }
                });
            });
            return;
        }

        chrome.tabs.sendMessage(tab.id, { command: 'START_CRAWL' }, () => {
            if (chrome.runtime.lastError) {
                status.textContent = 'Error: Refresh page and try again.';
                console.warn('Crawl message error:', chrome.runtime.lastError.message);
            } else if (isDeltaRI) {
                btnCrawl.disabled = true;
                btnCrawl.textContent = 'Crawling...';
                status.textContent = 'DD_RI crawl: 0%\nStarting RI crawler...';
            } else {
                status.textContent = 'Crawl started...';
                window.close();
            }
        });
    };
});
