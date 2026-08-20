"""Package the browser extension into a distributable zip.

The same package installs on Chrome (Chrome Web Store) and Firefox: the shared
manifest carries `browser_specific_settings.gecko.*`, which Chrome ignores and
Firefox uses. For Firefox you upload the resulting zip to AMO
(addons.mozilla.org) as an "unlisted" add-on to get a Mozilla-signed .xpi.

Usage:
    python build_extension.py            # builds dist/InsuranceAuditorPro-<version>.zip
    python build_extension.py --out foo.zip
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SOURCE_DIR = REPO_ROOT / "Extension"
DIST_DIR = REPO_ROOT / "dist"

# Files/patterns that should never end up in a shipped package.
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
EXCLUDE_SUFFIXES = {".map", ".zip", ".log", ".bak", ".md"}


def read_manifest(manifest_path: Path) -> dict:
    with manifest_path.open(encoding="utf-8") as fh:
        return json.load(fh)


# Constant filename the signed .xpi must be renamed to before uploading it to a
# GitHub release, so the "releases/latest/download/<name>" URL is stable.
XPI_ASSET_NAME = "insurance_auditor_pro.xpi"

# ── Firefox config, source of truth ──────────────────────────────────────────
# Chrome ignores `browser_specific_settings`; Firefox requires it. Pushing Chrome
# changes tends to overwrite manifest.json with a Chrome-only copy that drops this
# block. So the build OWNS it: it re-injects this into the package (and heals the
# on-disk manifest) every run, no matter what state manifest.json is in.
GECKO_SETTINGS = {
    "gecko": {
        "id": "insurance-auditor-pro@ispace.com",
        "strict_min_version": "121.0",
        "update_url": "https://github.com/aniketsharma-ispace/insurance-auditor-pro-mozilla/releases/latest/download/updates.json",
        "data_collection_permissions": {"required": ["none"]},
    }
}


def ensure_firefox_config(manifest: dict) -> bool:
    """Force the Firefox block into `manifest`. Returns True if it changed."""
    if manifest.get("browser_specific_settings") == GECKO_SETTINGS:
        return False
    manifest["browser_specific_settings"] = GECKO_SETTINGS
    return True


def write_updates_json(manifest: dict, out_path: Path) -> None:
    """Emit the Firefox self-hosted update manifest (updates.json).

    Firefox polls `update_url` (declared in the manifest) and installs the
    version listed here when it is newer than what's installed. `update_link`
    points at the .xpi asset in the same GitHub release.
    """
    gecko = manifest["browser_specific_settings"]["gecko"]
    addon_id = gecko["id"]
    update_url = gecko.get("update_url")
    if not update_url:
        return  # auto-update not configured; nothing to emit

    # Derive the .xpi URL from the update_url (same release, sibling asset).
    base = update_url.rsplit("/", 1)[0]
    update_link = f"{base}/{XPI_ASSET_NAME}"

    updates = {
        "addons": {
            addon_id: {
                "updates": [
                    {
                        "version": manifest["version"],
                        "update_link": update_link,
                    }
                ]
            }
        }
    }
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(updates, fh, indent=2)
    print(f"Built {out_path}  (version {manifest['version']} -> {update_link})")


def should_include(path: Path) -> bool:
    if path.name in EXCLUDE_NAMES:
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    return True


def build(manifest: dict, out_path: Path) -> None:
    """Zip the extension. `manifest` (with the Firefox block already ensured) is
    written into the package instead of the on-disk file, so the .xpi is correct
    even if manifest.json on disk is momentarily missing the Firefox block."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in SOURCE_DIR.rglob("*") if p.is_file() and should_include(p)
    )
    if out_path.exists():
        out_path.unlink()

    manifest_bytes = json.dumps(manifest, indent=4).encode("utf-8")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            # Store files at the archive root (manifest.json, content_*.js, ...)
            # to match the existing package layout.
            arcname = file_path.relative_to(SOURCE_DIR).as_posix()
            if arcname == "manifest.json":
                zf.writestr(arcname, manifest_bytes)  # the ensured version
            else:
                zf.write(file_path, arcname)

    print(f"Built {out_path}  ({len(files)} files, {out_path.stat().st_size:,} bytes)")


def verify_xpi(xpi_path: Path) -> int:
    """Sanity-check a signed .xpi before you upload it to a GitHub release.

    Confirms the packaged version + update_url match the current source manifest
    and that Mozilla actually signed it. Returns a process exit code.
    """
    manifest = read_manifest(SOURCE_DIR / "manifest.json")
    want_version = manifest["version"]
    want_url = manifest["browser_specific_settings"]["gecko"].get("update_url")

    with zipfile.ZipFile(xpi_path) as zf:
        names = zf.namelist()
        packaged = json.loads(zf.read("manifest.json"))
    got_version = packaged["version"]
    got_url = packaged["browser_specific_settings"]["gecko"].get("update_url")
    signed = any(n.lower() == "meta-inf/mozilla.rsa" for n in names)

    checks = [
        (f"version == {want_version}", got_version == want_version, got_version),
        ("update_url matches source", got_url == want_url, got_url),
        ("Mozilla-signed", signed, "META-INF/mozilla.rsa present" if signed else "NOT SIGNED"),
    ]
    print(f"Verifying {xpi_path}")
    ok = True
    for label, passed, detail in checks:
        print(f"  [{'OK ' if passed else 'FAIL'}] {label}  ({detail})")
        ok = ok and passed
    print("RESULT:", "PASS - safe to upload" if ok else "FAIL - do NOT upload this file")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output zip path (default: dist/InsuranceAuditorPro-<version>.zip)",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        default=None,
        metavar="XPI",
        help="Verify a signed .xpi matches the source manifest, then exit (no build).",
    )
    args = parser.parse_args()

    if args.verify is not None:
        sys.exit(verify_xpi(args.verify))

    manifest_path = SOURCE_DIR / "manifest.json"
    manifest = read_manifest(manifest_path)

    # Self-heal: if a Chrome push wiped the Firefox block, restore it on disk so
    # the source, the package, and updates.json all stay consistent.
    if ensure_firefox_config(manifest):
        with manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=4)
            fh.write("\n")
        print("NOTE: restored missing/outdated browser_specific_settings in manifest.json")

    version = manifest["version"]
    out_path = args.out or (DIST_DIR / f"InsuranceAuditorPro-{version}.zip")
    build(manifest, out_path)
    write_updates_json(manifest, out_path.parent / "updates.json")


if __name__ == "__main__":
    main()
