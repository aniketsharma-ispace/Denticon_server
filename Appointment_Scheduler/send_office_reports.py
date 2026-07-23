"""
Trial runner — email the per-office Day Start Reports via desktop Outlook.

WORKFLOW
  1. In the web UI, click "Generate Day Start Reports (ZIP)" and download the ZIP.
  2. Unzip it to a folder (one DayStart_*.xlsx per office).
  3. Run this script on the machine where Outlook is signed in:

        python send_office_reports.py "C:\\path\\to\\unzipped_folder"

     By default it runs in DRAFT mode — it opens each email in Outlook so you can
     review before sending. Add --send to actually send:

        python send_office_reports.py "C:\\path\\to\\folder" --send

     Optional shared-mailbox sender (send on behalf of):

        python send_office_reports.py "C:\\path\\to\\folder" --send --sender bpoispace@ispace.com

Recipients come from office_email_map.json (office → emails, with a default
fallback). For the trial the fallback is the three test addresses.
"""

import argparse
import glob
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import email_sender as es


def _office_from_file(path: str) -> str:
    """Read the Office Name from the report; fall back to the filename stem."""
    try:
        df = pd.read_excel(path, dtype=object)
        if "Office Name" in df.columns and len(df):
            val = str(df["Office Name"].iloc[0]).strip()
            if val:
                return val
    except Exception:
        pass
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem.replace("DayStart_", "").rsplit("_", 1)[0]


def main():
    ap = argparse.ArgumentParser(description="Email per-office Day Start reports via Outlook.")
    ap.add_argument("folder", help="Folder containing the per-office .xlsx files")
    ap.add_argument("--send", action="store_true", help="Actually send (default: open drafts for review)")
    ap.add_argument("--sender", default=None, help="Optional 'send on behalf of' address (shared mailbox)")
    ap.add_argument("--limit", type=int, default=0, help="Only process the first N files (0 = all). Use --limit 1 for a single trial email.")
    args = ap.parse_args()

    mode = "send" if args.send else "draft"
    files = sorted(glob.glob(os.path.join(args.folder, "*.xlsx")))
    if not files:
        print(f"No .xlsx files found in: {args.folder}")
        sys.exit(1)
    if args.limit > 0:
        files = files[:args.limit]

    mapping = es.load_email_map()
    print(f"Mode: {mode.upper()}  |  Files: {len(files)}  |  Default recipients: {mapping.get('default')}")
    print("-" * 70)

    ok, failed = 0, 0
    for path in files:
        office = _office_from_file(path)
        recipients = es.resolve_recipients(office, mapping)
        try:
            res = es.send_office_report(office, path, recipients, mode=mode, sender=args.sender)
            print(f"  {res['action'].upper():8} {office}  ->  {', '.join(recipients)}")
            ok += 1
        except Exception as e:
            print(f"  FAILED   {office}: {e}")
            failed += 1

    print("-" * 70)
    print(f"Done. {ok} {'drafted' if mode=='draft' else 'sent'}, {failed} failed.")
    if mode == "draft":
        print("Review the opened drafts in Outlook, then re-run with --send to send for real.")


if __name__ == "__main__":
    main()
