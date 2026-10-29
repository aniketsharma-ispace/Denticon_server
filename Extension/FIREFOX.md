# Firefox build & distribution

The extension ships from a **single shared manifest**. `manifest.json` carries a
`browser_specific_settings.gecko` block that Chrome ignores and Firefox uses, so
the *same* package installs on both browsers. No separate Firefox source tree.

Why it works on Firefox:

- `background` declares both `scripts` (Firefox) and `service_worker` (Chrome) —
  the recommended cross-browser pattern (Chrome 121+ / Firefox 121+).
- `content_cigna.js` detects Firefox via the `moz-extension:` protocol and omits
  the Chrome-only `extraHeaders` option on `webRequest`.
- Content scripts and the popup use the `chrome.*` namespace, which Firefox
  aliases automatically.
- `strict_min_version` is `121.0` because Firefox only starts the background page
  reliably alongside a `service_worker` key from 121 onward.

**Heads-up:** pushing Chrome changes tends to overwrite `manifest.json` with a
Chrome-only copy that drops the `browser_specific_settings` block. You don't have
to fix that by hand — `tools/build_extension.py` owns the block (`GECKO_SETTINGS`),
re-injects it into every package, and restores it on disk (prints
`NOTE: restored...`). Just always run the build before signing.

## Add-on identity (keep stable across releases)

- **Extension ID (gecko.id):** `insurance-auditor-pro@ispace.com`
- **AMO account:** `ispaceaniket` (the Mozilla account the add-on was submitted
  under). New versions MUST be uploaded under this same account + ID, or Firefox
  will treat them as a different extension instead of an update.
- **Data collection declared:** `none` (see `data_collection_permissions`). The
  extension reads patient data from the insurance portals and saves it locally;
  it does not transmit that data to our servers or third parties.

## Auto-update (SUSPENDED since 2026-10-29)

The manifest still carries `gecko.update_url` pointing at a public GitHub repo,
and the build still emits `dist/updates.json`, but **we stopped publishing GitHub
releases**. What that means:

- Installed copies still poll that URL and keep seeing the last release published
  there (**v1.45**), so they report "up to date" and never upgrade. Nothing
  breaks and nobody is downgraded - updates simply stop arriving.
- Every release from 1.48 on must be installed by hand on every machine.

To turn auto-update back on, either resume publishing both assets to GitHub
Releases (the `.xpi` renamed to `insurance_auditor_pro.xpi`, plus
`updates.json`), or point `GECKO_SETTINGS["gecko"]["update_url"]` in
`tools/build_extension.py` at a host the offices can actually reach and ship one
new signed build carrying the new URL. (Suspect reachability is why updates were
unreliable: one machine sat on 1.39 and never moved, even on a forced check.)

Historical setup, kept because the `update_url` is still baked into every copy:

- **Repo:** `https://github.com/aniketsharma-ispace/insurance-auditor-pro-mozilla` (public)
- **update_url:** `.../releases/latest/download/updates.json`
- The `.xpi` asset had to be named exactly **`insurance_auditor_pro.xpi`** to keep
  the `releases/latest/download/` URL stable.

## Release a new version

Distribution is **direct**: since 2026-10-29 the signed `.xpi` is handed to the
team (email / Teams / shared drive). No GitHub release, and therefore no
automatic rollout - see Auto-update above.

1. Bump `"version"` in `Extension/manifest.json` (e.g. `1.47` -> `1.48`).
2. Build:
   ```
   python tools/build_extension.py
   ```
   Produces `dist/InsuranceAuditorPro-<version>.zip`.
3. Sign the zip on AMO (see below) and download the signed `.xpi`.
4. **Rename** the signed file to `InsuranceAuditorPro-<version>.xpi`. AMO hands
   you a hash-named file, and with nothing auto-updating, the version in the
   filename is how an office knows which build it has.
5. **Verify before sending it out** - this catches handing round a stale or wrong
   file, which has happened more than once:
   ```
   python tools/build_extension.py --verify dist/InsuranceAuditorPro-<version>.xpi
   ```
   It must print `RESULT: PASS`. If it FAILs (wrong version / not signed), you
   grabbed the wrong file - fix it before sending.
6. Send that one file to the offices with the install steps below. Every machine
   needs a manual install; nothing arrives on its own.

## Signing (self-hosted / "unlisted")

Firefox refuses to permanently install an unsigned extension, so every build must
be signed by Mozilla. We distribute privately (not in the public directory), so
use the **unlisted** channel.

Web flow (what we used, no tooling needed):

1. https://addons.mozilla.org/developers/ -> **Submit a New Add-on**.
2. Distribution: choose **"On your own"** (unlisted / self-distribution).
3. Upload `dist/InsuranceAuditorPro-<version>.zip`.
4. Validation runs. **Warnings are fine** (e.g. "Unsafe assignment to innerHTML",
   permission warnings). Only a red **Error** blocks signing.
5. Compatibility: check **Firefox** only (not Firefox for Android).
6. Source code: answer **No** (scripts are hand-written, not minified/bundled).
7. Submit. Unlisted add-ons are auto-signed within a few minutes.
8. Download the signed `.xpi`: **My Add-ons -> Insurance Auditor Pro ->
   Manage Status & Versions -> version -> the `...-<version>.xpi` file link.**

CLI alternative (needs Node + web-ext and an AMO API key/secret from
https://addons.mozilla.org/developers/addon/api/key/):

```
npx web-ext lint  --source-dir Extension
npx web-ext sign  --source-dir Extension --channel unlisted \
    --api-key <JWT_ISSUER> --api-secret <JWT_SECRET>
```

The signed `.xpi` lands in `web-ext-artifacts/`.

## Install the signed .xpi (for the dental offices)

Give the office the `.xpi` file, plus these steps:

1. Open **Firefox**.
2. Drag the `.xpi` file onto the Firefox window
   *(or: menu -> Add-ons and themes -> gear icon -> Install Add-on From File...)*.
3. When Firefox asks, click **Add**, then **Okay**.
4. The "Insurance Auditor Pro" icon appears in the toolbar. Pin it if needed:
   click the puzzle-piece icon -> gear next to the extension -> Pin to Toolbar.

The extension is signed, so it stays installed across Firefox restarts.

## Temporary load (dev testing only, no signing)

`about:debugging#/runtime/this-firefox` -> **Load Temporary Add-on...** -> select
`Extension/manifest.json`. Removed when Firefox restarts.
