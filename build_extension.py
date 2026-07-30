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


def read_version(manifest_path: Path) -> str:
    with manifest_path.open(encoding="utf-8") as fh:
        return json.load(fh)["version"]


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

    version = read_version(SOURCE_DIR / "manifest.json")
    out_path = args.out or (DIST_DIR / f"InsuranceAuditorPro-{version}.zip")
    build(out_path)


if __name__ == "__main__":
    main()
