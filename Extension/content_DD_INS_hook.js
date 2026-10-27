// content_DD_INS_hook.js - runs in the page's own world at document_start.
//
// Benefits Search on deltadentalins.com never asks the server anything: the
// search box only filters what the page fetched when the patient was opened.
//
//   benefits/benefits-package  every procedure of the plan, all three networks
//   benefits/other-procedures  codes the plan does not pay for, with the reason
//   treatment-history          the patient's claims, approved and denied
//
// This hook keeps the last copy of each response as the page receives it, so
// content_DD_INS.js can read every sheet code without typing a single search.
// It never sends a request of its own and never alters what the page sees.
(() => {
    if (window.__DD_INS_HOOK__) return;
    window.__DD_INS_HOOK__ = true;

    const PAGE_SOURCE = "dd-ins-hook";
    const EXT_SOURCE = "dd-ins-scraper";
    const WATCHED = /\/provider-tools\/v2\/api\/(?:benefits\/(benefits-package|other-procedures)|(treatment-history))(?:[?#]|$)/;

    const captured = {};

    const keyFor = (url) => {
        const m = String(url || "").match(WATCHED);
        return m ? (m[1] || m[2]) : null;
    };

    const keep = (url, text) => {
        const key = keyFor(url);
        if (!key || !text) return;
        try {
            captured[key] = { at: Date.now(), body: JSON.parse(text) };
        } catch (e) {
            // Not JSON: nothing the scraper could use.
        }
    };

    const nativeFetch = window.fetch;
    if (typeof nativeFetch === "function") {
        window.fetch = function (input, init) {
            const pending = nativeFetch.apply(this, arguments);
            const url = typeof input === "string" ? input : (input && input.url);
            if (keyFor(url)) {
                pending.then(response => {
                    if (response.ok) response.clone().text().then(text => keep(url, text)).catch(() => {});
                }).catch(() => {});
            }
            return pending;
        };
    }

    const nativeOpen = XMLHttpRequest.prototype.open;
    const nativeSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
        this.__ddInsUrl = url;
        return nativeOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function () {
        if (keyFor(this.__ddInsUrl)) {
            this.addEventListener("load", () => {
                if (this.status < 200 || this.status >= 300) return;
                try {
                    if (this.responseType === "" || this.responseType === "text") keep(this.__ddInsUrl, this.responseText);
                    else if (this.responseType === "json") keep(this.__ddInsUrl, JSON.stringify(this.response));
                } catch (e) {
                    // Unreadable response: the scraper falls back to the page.
                }
            });
        }
        return nativeSend.apply(this, arguments);
    };

    window.addEventListener("message", event => {
        if (event.source !== window || event.origin !== window.location.origin) return;
        if (event.data?.source !== EXT_SOURCE || event.data.type !== "GET_CAPTURED") return;
        window.postMessage({
            source: PAGE_SOURCE,
            type: "CAPTURED",
            requestId: event.data.requestId,
            captured
        }, window.location.origin);
    });
})();
