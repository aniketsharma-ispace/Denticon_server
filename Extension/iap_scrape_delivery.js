// ============================================================================
// Sabrina prefill — hand a finished portal scrape to the server
//
// Loaded before a portal's content script (same isolated world). At the end
// of a crawl the portal script calls
//
//     iapDeliverScrape(payload, downloadFn)
//
// which sends the scrape to the Insurance Auditor server for the Sabrina Fill
// Form instead of downloading it. The note shown afterwards has a Download JSON
// button, so the file is still one click away for the comparison UI.
//
// `downloadFn(payload)` is the portal script's own download. It runs:
//   - when the user clicks Download JSON,
//   - right away when "Always download the JSON too" is set,
//   - instead of sending, when the extension is set to download only or the
//     server cannot take the scrape — so a scrape is never lost.
// ============================================================================

(function () {
  if (window.__iapDeliverScrape) return;

  const COLORS = { ok: "#067647", warn: "#b54708", error: "#b42318" };

  // A note in the corner of the portal page, with optional buttons.
  function toast(text, kind = "ok", actions = []) {
    try {
      const box = document.createElement("div");
      box.style.cssText = [
        "position:fixed", "right:16px", "bottom:16px", "z-index:2147483647",
        "max-width:400px", "padding:12px 14px", "border-radius:8px",
        "font:13px/1.45 system-ui,Segoe UI,Arial,sans-serif", "color:#fff",
        "box-shadow:0 4px 16px rgba(0,0,0,.25)", "background:" + (COLORS[kind] || COLORS.ok),
      ].join(";");

      const close = document.createElement("span");
      close.textContent = "✕";
      close.title = "Close";
      close.style.cssText = "float:right;margin-left:10px;cursor:pointer;opacity:.85";
      close.onclick = () => box.remove();
      box.appendChild(close);

      const msg = document.createElement("div");
      msg.textContent = text;
      box.appendChild(msg);

      if (actions.length) {
        const row = document.createElement("div");
        row.style.cssText = "margin-top:8px;display:flex;gap:8px";
        actions.forEach(({ label, onClick }) => {
          const b = document.createElement("button");
          b.textContent = label;
          b.style.cssText = "border:0;border-radius:6px;padding:6px 10px;background:#fff;" +
                            "color:#1d2939;font:600 12px system-ui,Segoe UI,Arial,sans-serif;cursor:pointer";
          b.onclick = () => {
            try { onClick(); } finally { b.disabled = true; b.textContent = label + " ✓"; }
          };
          row.appendChild(b);
        });
        box.appendChild(row);
      }

      (document.body || document.documentElement).appendChild(box);
      // Long enough to reach the button; errors stay longer still.
      setTimeout(() => box.remove(), actions.length ? 30000 : kind === "error" ? 12000 : 7000);
    } catch (_) { /* a page without a body: nothing to show */ }
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

  window.__iapDeliverScrape = async function (payload, downloadFn) {
    const canDownload = typeof downloadFn === "function";
    const download = () => { if (canDownload) downloadFn(payload); };
    const fallback = (why) => {
      download();
      if (why) toast("Not sent to the server (" + why + "). The JSON was downloaded instead.", "warn");
    };

    // No extension messaging here (a stripped popup window): keep the old way.
    if (typeof chrome === "undefined" || !chrome.runtime || !chrome.runtime.sendMessage) {
      return fallback("");
    }

    const s = await send({ type: "IAP_GET_SETTINGS" });
    const settings = (s.ok && s.settings) || {};
    if (settings.scrapeMode === "download") return fallback("");

    const r = await send({ type: "IAP_SAVE_SCRAPE", data: payload });
    if (!r.ok) return fallback(r.error || "server error");

    const sc = r.scrape || {};
    const who = sc.member_id ? "member " + sc.member_id : sc.dob ? "DOB " + sc.dob : "this patient";
    const text = "Sent for Sabrina: " + (sc.carrier || "portal") + " scrape for " + who +
                 ". Open this patient's Fill Form to fill it.";
    if (settings.alsoDownload) {
      download();
      toast(text + " (JSON downloaded too)");
    } else {
      toast(text, "ok", canDownload ? [{ label: "Download JSON", onClick: download }] : []);
    }
  };

  // The name portal scripts call.
  window.iapDeliverScrape = window.__iapDeliverScrape;
})();
