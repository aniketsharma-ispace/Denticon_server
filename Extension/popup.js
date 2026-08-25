// document.addEventListener('DOMContentLoaded', async () => {
//     const status      = document.getElementById('status');
//     const btnCrawl    = document.getElementById('btnCrawl');
//     const btnDownload = document.getElementById('btnDownload');

//     // ── Identify current tab ──
//     const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
//     const url   = tab.url || "";

//     const isOverview  = url.toLowerCase().includes('advancedpatientoverview.aspx');
//     const isInsurance = url.toLowerCase().includes('advancededitpatientinsurance.aspx') ||
//                         url.includes('c2.denticon.com');
//     const isDenticon  = url.includes('denticon.com') || url.includes('planetdds.com');
//     const isMetLife   = url.includes('metlife.com');
//     const isCigna     = url.includes('cignaforhcp.cigna.com');
//     const isDeltaINS  = url.includes('deltadentalins.com');
//     const isDeltaVA   = url.includes('deltadentalva.com');
//     const isAetna     = url.includes('claimconnect.dentalxchange.com');
//     const isDeltaRI   = url.includes('deltadentalri.com');
//     const isDeltaAR   = url.includes('my.deltadentalar.com');
//     const isUCCI      = url.includes('unitedconcordia.com/');
//     const isDeltaNJ   = url.includes('deltadentalnj.com/');
//     const isDeltaWA   = url.includes('deltadentalwa.com/');
//     const isDentaquest = url.includes('providers.dentaquest.com/');
//     const isDeltaCO = url.includes('deltadentalco.com/');
//     const isDeltaIL = url.includes('deltadentalil.com/');
//     const isDeltaMA = url.includes('deltadentalma.com/');    
//     const isDNOA = url.includes('dnoaconnect.com/');
//     // ── Load stored data ──
//     const result  = await chrome.storage.local.get("audit_context");
//     const context = result.audit_context || {};

//     // ── Status display ──
//     if (isOverview) {
//         status.innerText = "Patient Overview detected. Click Download to capture patient data.";
//     } else if (isInsurance) {
//         status.innerText = "Insurance tab detected. Click Crawl to scrape all plans.";
//     } else if (isMetLife && context.metlife_data) {
//         status.innerText = "MetLife Data: Ready to Crawl.";
//     } else if (isCigna && context.cigna_data) {
//         status.innerText = "Cigna Data: Ready to Crawl.";
//     } else if (isDenticon && context.denticon_data) {
//         status.innerText = `Denticon Ready: ${context.denticon_data.header?.patient_name || "Active"}`;
//     } else if (isDeltaINS) {
//         status.innerText = "DeltaDental_INS Data: Ready to Crawl.";
//     } else if (isDeltaVA) {
//         status.innerText = "DD_VA: Ready to Crawl.";
//     } else if (isAetna) {                                                 // ← NEW
//         status.innerText = "ClaimConnect detected. Ready to Crawl.";
//     } else if (isDeltaRI) {
//         status.innerText = "DD_RI Data: Ready to Crawl.";
//     } else if (isDeltaAR) {
//         status.innerText = "DD_AR Data: Ready to Crawl.";
//     } else if (isUCCI) {
//         status.innerText = "UCCI Data: Ready to Crawl.";
//     } else if (isDeltaNJ) {
//         status.innerText = "DD_NJ Data: Ready to Crawl.";
//     } else if (isDeltaWA) {
//         status.innerText = "DD_WA Data: Ready to Crawl.";
//     } else if (isDentaquest) {
//         status.innerText = "DentaQuest Data: Ready to Crawl.";
//     } else if (isDeltaCO) {
//         status.innerText = "DD_CO Data: Ready to Crawl.";
//     } else if (isDeltaIL) {
//         status.innerText = "DD_IL Data: Ready to Crawl.";
//     } else if (isDeltaMA) {
//         status.innerText = "DD_MA Data: Ready to Crawl.";
//     } else if (isDNOA) {
//         status.innerText = "DNOA Data: Ready to Crawl.";
//     }
//     else {
//         status.innerText = "Navigate to a Denticon patient page to begin.";
//     }

//     // ── Button 1: Download Patient JSON ──
//     btnDownload.onclick = () => {
//         if (isAetna) {
//             chrome.scripting.executeScript({
//                 target: { tabId: tab.id },
//                 func: () => {window.__aetnaDownload?.();}
//             }).then(() => {window.close();});
//             return;
//         }
//         if (isOverview) {
//             chrome.tabs.sendMessage(tab.id, { command: "DOWNLOAD_PATIENT" }, (response) => {
//                 if (chrome.runtime.lastError) {
//                     status.innerText = "Error: Refresh the page and try again.";
//                 } else {
//                     status.innerText = "Downloading patient data...";
//                     setTimeout(() => window.close(), 1200);
//                 }
//             });
//         } else if (Object.keys(context).length > 0) {
//             const blob = new Blob([JSON.stringify(context, null, 2)], { type: "application/json" });
//             const url2 = URL.createObjectURL(blob);
//             chrome.downloads.download({
//                 url: url2,
//                 filename: `Insurance_Audit_${Date.now()}.json`
//             }, (downloadId) => {
//                 if (downloadId) {
//                     chrome.storage.local.remove("audit_context", () => {
//                         status.innerText = "Success: Data Exported & Cleared";
//                         setTimeout(() => window.close(), 1000);
//                     });
//                 }
//             });
//         } else {
//             alert("No data captured yet. Navigate to a Patient Overview page first.");
//         }
//     };

//     // ── Button 2: Crawl ──
//     btnCrawl.onclick = () => {
//         // ── Aetna/ClaimConnect ──────────────────────────────────────────
//         if (isAetna) {                                                    // ← NEW
//             chrome.tabs.sendMessage(tab.id, { command: "START_AETNA_CRAWL" }, (response) => {
//                 if (chrome.runtime.lastError) {
//                     status.innerText = "Error: Refresh the ClaimConnect page and try again.";
//                     console.warn("Aetna crawl error:", chrome.runtime.lastError.message);
//                 } else {
//                     status.innerText = "Crawl started...";
//                     window.close();
//                 }
//             });
//             return;
//         }

//         // ── All other sites (existing behaviour) ────────────────────────
//         chrome.tabs.sendMessage(tab.id, { command: "START_CRAWL" }, (response) => {
//             if (chrome.runtime.lastError) {
//                 status.innerText = "Error: Refresh page and try again.";
//                 console.warn("Crawl message error:", chrome.runtime.lastError.message);
//             } else {
//                 status.innerText = "Crawl started...";
//                 window.close();
//             }
//         });
//     };
// });
document.addEventListener('DOMContentLoaded', async () => {
    const status      = document.getElementById('status');
    const btnCrawl    = document.getElementById('btnCrawl');

    // ── Identify current tab ──
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url   = tab.url || "";

    const isOverview  = url.toLowerCase().includes('advancedpatientoverview.aspx');
    const isInsurance = url.toLowerCase().includes('advancededitpatientinsurance.aspx') ||
                        url.includes('c2.denticon.com');
    const isDenticon  = url.includes('denticon.com') || url.includes('planetdds.com');
    const isMetLife   = url.includes('metlife.com');
    const isCigna     = url.includes('cignaforhcp.cigna.com');
    const isDeltaINS  = url.includes('deltadentalins.com');
    const isDeltaVA   = url.includes('deltadentalva.com');
    const isAetna     = url.includes('claimconnect.dentalxchange.com');
    const isDeltaRI   = url.includes('deltadentalri.com');
    const isDeltaAR   = url.includes('my.deltadentalar.com');
    const isUCCI      = url.includes('unitedconcordia.com/');
    const isDeltaNJ   = url.includes('deltadentalnj.com/');
    const isDeltaWA   = url.includes('deltadentalwa.com/');
    const isDentaquest = url.includes('providers.dentaquest.com/');
    const isDeltaCO = url.includes('deltadentalco.com/');
    const isDeltaIL = url.includes('deltadentalil.com/');
    const isDeltaMA = url.includes('deltadentalma.com/');
    const isDNOA = url.includes('dnoaconnect.com/');

    // ── Load stored data ──
    const result  = await chrome.storage.local.get("audit_context");
    const context = result.audit_context || {};

    // ── Status display ──
    if (isOverview) {
        status.innerText = "Patient Overview detected. Click Crawl to capture patient data.";
    } else if (isInsurance) {
        status.innerText = "Insurance tab detected. Click Crawl to scrape all plans.";
    } else if (isMetLife && context.metlife_data) {
        status.innerText = "MetLife Data: Ready to Crawl.";
    } else if (isCigna && context.cigna_data) {
        status.innerText = "Cigna Data: Ready to Crawl.";
    } else if (isDenticon && context.denticon_data) {
        status.innerText = `Denticon Ready: ${context.denticon_data.header?.patient_name || "Active"}`;
    } else if (isDeltaINS) {
        status.innerText = "DeltaDental_INS Data: Ready to Crawl.";
    } else if (isDeltaVA) {
        status.innerText = "DD_VA: Ready to Crawl.";
    } else if (isAetna) {
        status.innerText = "Aetna detected. Ready to Crawl.";
    } else if (isDeltaRI) {
        status.innerText = "DD_RI Data: Ready to Crawl.";
    } else if (isDeltaAR) {
        status.innerText = "DD_AR Data: Ready to Crawl.";
    } else if (isUCCI) {
        status.innerText = "UCCI Data: Ready to Crawl.";
    } else if (isDeltaNJ) {
        status.innerText = "DD_NJ Data: Ready to Crawl.";
    } else if (isDeltaWA) {
        status.innerText = "DD_WA Data: Ready to Crawl.";
    } else if (isDentaquest) {
        status.innerText = "DentaQuest Data: Ready to Crawl.";
    } else if (isDeltaCO) {
        status.innerText = "DD_CO Data: Ready to Crawl.";
    } else if (isDeltaIL) {
        status.innerText = "DD_IL Data: Ready to Crawl.";
    } else if (isDeltaMA) {
        status.innerText = "DD_MA Data: Ready to Crawl.";
    } else if (isDNOA) {
        status.innerText = "DNOA Data: Ready to Crawl.";
    } else {
        status.innerText = "Navigate to a patient page to begin.";
    }

    // ── Single button: Crawl (routes per-site) ──
    btnCrawl.onclick = () => {
        // ── Aetna/ClaimConnect → download flow ──
        if (isAetna) {
            chrome.scripting.executeScript({
                target: { tabId: tab.id },
                func: () => { window.__aetnaDownload?.(); }
            }).then(() => { window.close(); })
              .catch((err) => {
                  status.innerText = "Error: Refresh the ClaimConnect page and try again.";
                  console.warn("Aetna download error:", err);
              });
            return;
        }

        // ── Overview page → download patient data ──
        if (isOverview) {
            chrome.tabs.sendMessage(tab.id, { command: "DOWNLOAD_PATIENT" }, (response) => {
                if (chrome.runtime.lastError) {
                    status.innerText = "Error: Refresh the page and try again.";
                } else {
                    status.innerText = "Downloading patient data...";
                    setTimeout(() => window.close(), 1200);
                }
            });
            return;
        }

        // ── All other sites → standard crawl ──
        // ── All other sites → standard crawl ──
        let popupClosed = false;
        const autoCloseTimer = setTimeout(() => {
            if (!popupClosed) {
                popupClosed = true;
                status.innerText = "Crawl started...";
                window.close();
            }
        }, 1000);

        chrome.tabs.sendMessage(tab.id, { command: "START_CRAWL" }, (response) => {
            if (chrome.runtime.lastError) {
                clearTimeout(autoCloseTimer);
                popupClosed = true; // prevent the timer from also firing
                status.innerText = "Error: Refresh page and try again.";
                console.warn("Crawl message error:", chrome.runtime.lastError.message);
            }
    // If no error, do nothing here — the timer above already handles closing.
    // (If it happens to fire before the timer, that's fine too, no conflict.)
        });
    };
});