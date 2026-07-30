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

## Add-on identity (keep stable across releases)

- **Extension ID (gecko.id):** `insurance-auditor-pro@ispace.com`
- **AMO account:** `ispaceaniket` (the Mozilla account the add-on was submitted
  under). New versions MUST be uploaded under this same account + ID, or Firefox
  will treat them as a different extension instead of an update.
- **Data collection declared:** `none` (see `data_collection_permissions`). The
  extension reads patient data from the insurance portals and saves it locally;
  it does not transmit that data to our servers or third parties.

## Auto-update (self-hosted via GitHub Releases)

Installed copies update themselves by polling `update_url` (declared in the
manifest). We host the update manifest + signed `.xpi` in a **dedicated public
GitHub repo** so the private server code stays private:

- **Repo:** `https://github.com/aniketsharma-ispace/insurance-auditor-pro-mozilla` (public)
- **update_url:** `https://github.com/aniketsharma-ispace/insurance-auditor-pro-mozilla/releases/latest/download/updates.json`
- The `.xpi` asset in each release MUST be named exactly **`insurance_auditor_pro.xpi`**
  so the `releases/latest/download/` URL stays stable. AMO hands you a
  hash-named file — rename it before uploading.

One-time setup (only needed once, ever):
1. Create the public repo above (empty is fine).
2. Do a normal release (below). This is also the build that first carries
   `update_url`, so everyone must install THIS `.xpi` once (their current copy
   has no `update_url` and can't self-update). After that, updates are automatic.

## Release a new version

1. Bump `"version"` in `Extension/manifest.json` (e.g. `1.26` -> `1.27`).
2. Build:
   ```
   python build_extension.py
   ```
   Produces `dist/InsuranceAuditorPro-<version>.zip` **and** `dist/updates.json`
   (regenerated from the manifest each time).
3. Sign the zip on AMO (see below) and download the signed `.xpi`.
4. **Rename** the signed file to `insurance_auditor_pro.xpi`.
5. **Verify before uploading** (catches uploading the wrong/old file — a very
   easy mistake since every release uses the same filename):
   ```
   python build_extension.py --verify insurance_auditor_pro.xpi
   ```
   It must print `RESULT: PASS`. If it FAILs (wrong version / wrong update_url /
   not signed), you grabbed the wrong file — fix it before continuing.
6. On the public repo, create a **new GitHub Release** (tag e.g. `v1.28`) and
   attach TWO assets: `insurance_auditor_pro.xpi` and `dist/updates.json`.
   Tip: delete the freshly-signed download from your Downloads folder afterward
   so it can't be confused with next release's file.
7. Done. Within ~24h (or on next restart) every install auto-updates. No action
   for the offices.

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
