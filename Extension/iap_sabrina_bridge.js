// ============================================================================
// Sabrina prefill — background bridge (Insurance Auditor Pro)
//
// Every call to the Insurance Auditor server goes through here, from the
// extension's background, never from a page. Sabrina is served over HTTPS and
// the server is plain HTTP on the LAN, so a call made from the Sabrina page
// itself would be blocked by the browser as mixed content.
//
// Loaded by content_cigna.js (Chrome: importScripts in the service worker) and
// listed in manifest.background.scripts (Firefox). Does nothing on a page.
//
// Messages (chrome.runtime.sendMessage({ type, ... })):
//   IAP_SAVE_SCRAPE   { data }                         → { ok, scrape }
//   IAP_GET_PREFILL   { member_id, dob, network }      → { ok, prefill }
//   IAP_MARK_USED     { scrape_id }                    → { ok }
//   IAP_GET_SETTINGS  {}                               → { ok, settings }
//   IAP_SET_SETTINGS  { settings }                     → { ok, settings }
// ============================================================================

(function () {
  if (!(typeof document === "undefined" || globalThis.location?.protocol === "moz-extension:")) return;
  if (globalThis.__iapSabrinaBridge) return;          // loaded twice (Firefox lists it, Chrome imports it)
  globalThis.__iapSabrinaBridge = true;

  const DEFAULTS = {
    serverUrl: "http://10.30.10.67:8000",   // the shared server; change in the Sabrina panel's Settings
    client: "smile_partners",
    scrapeMode: "server",                  // "server" = send instead of download, "download" = old behaviour
    alsoDownload: false,                   // true = always download too; otherwise the note offers a Download JSON button
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

  const handlers = {
    async IAP_SAVE_SCRAPE(msg) {
      const s = await settings();
      const scrape = await call("/api/scrapes", {
        method: "POST",
        body: JSON.stringify({ client: s.client, portal_data: msg.data }),
      });
      // This browser's own last scrape: the Fill Form asks for it first.
      await chrome.storage.local.set({ iapLastScrape: Object.assign({ at: Date.now() }, scrape) });
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

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    const handler = msg && handlers[msg.type];
    if (!handler) return false;                     // not ours: leave it to the other listeners
    handler(msg)
      .then(result => sendResponse(Object.assign({ ok: true }, result)))
      .catch(err => sendResponse({ ok: false, error: String(err && err.message || err) }));
    return true;                                    // answer asynchronously
  });
})();
