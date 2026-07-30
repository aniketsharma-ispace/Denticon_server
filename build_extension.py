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


def build(out_path: Path) -> None:
    manifest_path = SOURCE_DIR / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"manifest.json not found in {SOURCE_DIR}")

    # Fail fast on malformed JSON so we never ship a broken manifest.
    with manifest_path.open(encoding="utf-8") as fh:
        json.load(fh)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in SOURCE_DIR.rglob("*") if p.is_file() and should_include(p)
    )
    if out_path.exists():
        out_path.unlink()

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            # Store files at the archive root (manifest.json, content_*.js, ...)
            # to match the existing package layout.
            arcname = file_path.relative_to(SOURCE_DIR).as_posix()
            zf.write(file_path, arcname)

    print(f"Built {out_path}  ({len(files)} files, {out_path.stat().st_size:,} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output zip path (default: dist/InsuranceAuditorPro-<version>.zip)",
    )
    args = parser.parse_args()

    manifest = read_manifest(SOURCE_DIR / "manifest.json")
    version = manifest["version"]
    out_path = args.out or (DIST_DIR / f"InsuranceAuditorPro-{version}.zip")
    build(out_path)
    write_updates_json(manifest, out_path.parent / "updates.json")


if __name__ == "__main__":
    main()
