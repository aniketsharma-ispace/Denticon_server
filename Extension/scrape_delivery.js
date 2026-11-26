// ============================================================================
// scrape_delivery.js — the extension's one link to the Insurance Auditor server
//
// Runs in the extension background (never on a page):
//   - Chrome: content_cigna.js's service worker loads it with importScripts.
//   - Firefox: listed in manifest.background.scripts.
//
// 1. A payer script finishes its crawl and hands the JSON over with ONE line:
//
//        chrome.runtime.sendMessage({ type: "SCRAPE_DONE", carrier: "cigna", data: output });
//
//    This file keeps it as that payer's last scrape (for the popup's Download
//    button) and sends it to the server for the Sabrina Fill Form. Nothing is
//    downloaded automatically.
//
// 2. The popup's first button downloads that last scrape when clicked
//    (it reads chrome.storage.local "iapScrapes" — see popup.js).
//
// 3. The Sabrina panel (content_sabrina.js) asks for the Fill Form values here.
//
// All server calls are made from here because Sabrina is HTTPS and the server
// is plain HTTP on the LAN: a call from the page itself would be blocked.
//
// Messages (chrome.runtime.sendMessage({ type, ... })):
//   SCRAPE_DONE       { carrier, data }                → { ok, scrape }
//   IAP_GET_PREFILL   { member_id, dob, network, client_id } → { ok, prefill }
//   IAP_MARK_USED     { scrape_id }                    → { ok }
//   IAP_GET_SETTINGS  {}                               → { ok, settings, lastScrape }
//   IAP_SET_SETTINGS  { settings }                     → { ok, settings }
// ============================================================================

(function () {
  if (!(typeof document === "undefined" || globalThis.location?.protocol === "moz-extension:")) return;
  if (globalThis.__iapScrapeDelivery) return;          // loaded twice (Firefox lists it, Chrome imports it)
  globalThis.__iapScrapeDelivery = true;

  const DEFAULTS = {
    serverUrl: "http://10.30.10.67:8000",   // the shared server; change in the Sabrina panel's Settings
    client: "smile_partners",
  };

  async function settings() {
    const got = await chrome.storage.local.get(["iapSettings"]);
    return Object.assign({}, DEFAULTS, got.iapSettings || {});
  }

  async function call(path, options = {}) {
    const s = await settings();
    const base = String(s.serverUrl || "").replace(/\/+$/, "");
    let res;
    try {
      res = await fetch(base + path, Object.assign({ headers: { "Content-Type": "application/json" } }, options));
    } catch (e) {
      throw new Error(`Cannot reach the Insurance Auditor server at ${base}. Is it running?`);
    }
    let body = null;
    try { body = await res.json(); } catch (_) { /* no JSON body */ }
    if (!res.ok) {
      const detail = body && body.detail;
      throw new Error(typeof detail === "string" ? detail
                      : `Server answered ${res.status}` + (detail ? `: ${JSON.stringify(detail)}` : ""));
    }
    return body;
  }

  // A file name for the popup's Download button: <carrier>_<patient>_<date>.json
  function fileName(carrier, data) {
    const d = data || {};
    const name = d.patient?.name || d.patient_info?.patient_name || d.primary_patient?.name ||
                 d.member_details?.patient_name || d.metlife_data?.patient?.name ||
                 d.patient_information?.name || "patient";
    const slug = String(name).trim().replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "").toLowerCase() || "patient";
    return `${carrier}_${slug}_${new Date().toISOString().slice(0, 10)}.json`;
  }

  // A short note in the corner of the portal tab the scrape came from.
  async function notify(sender, text, kind) {
    if (!sender || !sender.tab || sender.tab.id == null) return;
    try {
      await chrome.scripting.executeScript({
        target: { tabId: sender.tab.id, frameIds: [sender.frameId || 0] },
        args: [text, kind],
        func: (text, kind) => {
          const colors = { ok: "#067647", error: "#b42318" };
          const box = document.createElement("div");
          box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:400px;" +
            "padding:12px 14px;border-radius:8px;font:13px/1.45 system-ui,Segoe UI,Arial,sans-serif;" +
            "color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.25);background:" + (colors[kind] || colors.ok);
          box.textContent = text;
          box.title = "Click to close";
          box.onclick = () => box.remove();
          (document.body || document.documentElement).appendChild(box);
          setTimeout(() => box.remove(), kind === "error" ? 15000 : 8000);
        },
      });
    } catch (_) { /* tab closed or navigated away: nothing to show */ }
  }

  const handlers = {
    async SCRAPE_DONE(msg, sender) {
      const carrier = String(msg.carrier || "portal");
      // Keep it first, so the popup can download it even if the server is down.
      const kept = (await chrome.storage.local.get(["iapScrapes"])).iapScrapes || {};
      kept[carrier] = { data: msg.data, filename: fileName(carrier, msg.data), at: Date.now() };
      await chrome.storage.local.set({ iapScrapes: kept });

      const s = await settings();
      let scrape;
      try {
        scrape = await call("/api/scrapes", {
          method: "POST",
          body: JSON.stringify({ client: s.client, portal_data: msg.data }),
        });
      } catch (e) {
        await notify(sender, `Scrape finished but was NOT sent to the server: ${e.message} ` +
                             `Use the extension popup's Download button to save the JSON.`, "error");
        throw e;
      }
      // This browser's own last scrape: the Fill Form fills from it.
      await chrome.storage.local.set({ iapLastScrape: Object.assign({ at: Date.now() }, scrape) });
      const who = scrape.member_id ? "member " + scrape.member_id : scrape.dob ? "DOB " + scrape.dob : "this patient";
      await notify(sender, `Sent to the server: ${scrape.carrier || carrier} scrape for ${who}. ` +
                           `Open this patient's Fill Form in Sabrina to fill it. ` +
                           `(The popup's Download button saves the JSON.)`, "ok");
      return { scrape };
    },

    async IAP_GET_PREFILL(msg) {
      const s = await settings();
      const last = (await chrome.storage.local.get(["iapLastScrape"])).iapLastScrape;
      const q = new URLSearchParams({
        client: s.client,
        member_id: msg.member_id || "",
        network: msg.network || "",
      });
      if (msg.dob) q.set("dob", msg.dob);
      // The Fill Form's own ClientID decides whose rules fill it (19 Star
      // Dental, 26 Smile Partners); `client` above is the Settings fallback.
      if (msg.client_id) q.set("sabrina_client_id", String(msg.client_id));
      if (last && last.id) q.set("scrape_id", String(last.id));
      // Only this browser's last scrape, never an older one left on the server.
      q.set("only_own", "true");
      const prefill = await call("/api/prefill?" + q.toString());
      return { prefill };
    },

    async IAP_MARK_USED(msg) {
      await call(`/api/scrapes/${encodeURIComponent(msg.scrape_id)}/used`, { method: "POST" });
      const last = (await chrome.storage.local.get(["iapLastScrape"])).iapLastScrape;
      if (last && String(last.id) === String(msg.scrape_id)) await chrome.storage.local.remove("iapLastScrape");
      return {};
    },

    async IAP_GET_SETTINGS() {
      const last = (await chrome.storage.local.get(["iapLastScrape"])).iapLastScrape || null;
      return { settings: await settings(), lastScrape: last };
    },

    async IAP_SET_SETTINGS(msg) {
      const merged = Object.assign(await settings(), msg.settings || {});
      await chrome.storage.local.set({ iapSettings: merged });
      return { settings: merged };
    },
  };

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    const handler = msg && handlers[msg.type];
    if (!handler) return false;                     // not ours: leave it to the other listeners
    handler(msg, sender)
      .then(result => sendResponse(Object.assign({ ok: true }, result)))
      .catch(err => sendResponse({ ok: false, error: String(err && err.message || err) }));
    return true;                                    // answer asynchronously
  });
})();
