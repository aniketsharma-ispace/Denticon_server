// popup.js - Multi-Portal Build with Auto-Purge

document.addEventListener('DOMContentLoaded', async () => {
    const status = document.getElementById('status');
    const btnCrawl = document.getElementById('btnCrawl');
    const btnDownload = document.getElementById('btnDownload');

    // 1. Check current tab to see where we are
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const isMetLife = tab.url.includes("metlife.com");
    const isCigna = tab.url.includes("cignaforhcp.cigna.com");
    const isDenticon = tab.url.includes("denticon.com") || tab.url.includes("planetdds.com");
    const isDentaQuest = tab.url.includes("dentaquest.com");

    // 2. Load Data from Storage
    const result = await chrome.storage.local.get("audit_context");
    let context = result.audit_context || {};

    // 3. Update Status Display
    if (isMetLife && context.metlife_data) {
        status.innerText = "MetLife Data: Ready";
    } else if (isCigna && context.cigna_data) {
        status.innerText = "Cigna Data: Ready";
    } else if (isDenticon && context.denticon_data) {
        status.innerText = `Denticon Ready: ${context.denticon_data.header?.patient_name || "Active"}`;
    } else if (isDentaQuest && context.dentaquest_data) {
        status.innerText = `DentaQuest Ready: ${context.dentaquest_data.patient?.name || "Active"}`;
    } else {
        status.innerText = "Waiting for page data...";
    }

    // 4. Handle Crawl Button
    btnCrawl.onclick = () => {
        chrome.tabs.sendMessage(tab.id, { command: "START_CRAWL" }, (response) => {
            if (chrome.runtime.lastError) {
                console.warn("Could not connect to content script. Try refreshing the page.");
                status.innerText = "Error: Refresh page and try again.";
            } else {
                window.close();
            }
        });
    };

    // 5. Updated Download Button with Auto-Purge
    btnDownload.onclick = () => {
        if (Object.keys(context).length === 0) {
            alert("No data captured yet.");
            return;
        }

        const blob = new Blob([JSON.stringify(context, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);

        chrome.downloads.download({
            url: url,
            filename: `Insurance_Audit_${Date.now()}.json`
        }, (downloadId) => {
            // Callback: Runs once the download starts
            if (downloadId) {
                chrome.storage.local.remove("audit_context", () => {
                    console.log("Audit context cleared successfully.");
                    status.innerText = "Success: Data Exported & Cleared";

                    // Optional: Provide a visual cue before closing
                    setTimeout(() => {
                        window.close();
                    }, 1000);
                });
            }
        });
    };
});