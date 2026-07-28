"""
Office-wise Day Start Report emailing via desktop Outlook (SOP Step 6, Part B).

Uses Outlook COM automation (pywin32), so it MUST run on the Windows machine where
Outlook is installed and signed in. Each office's Excel is attached to a mail
addressed to that office's mapped recipients.

Two safety modes:
  • "draft" — build the mail and .Display() it (opens in Outlook for review, does
    NOT send). Recommended for trials.
  • "send"  — build the mail and .Send() it immediately.

The office → email mapping lives in office_email_map.json:
    {
      "default": ["fallback@ispace.com"],          # used when an office isn't mapped
      "mappings": { "Some Office Name": ["a@x.com", "b@x.com"] }
    }
Office names are matched case/whitespace-insensitively.
"""

from __future__ import annotations

import io
import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EMAIL_MAP_FILE = os.path.join(BASE_DIR, "office_email_map.json")

# Trial default: any office with no explicit mapping goes to these recipients.
DEFAULT_MAP = {
    "default": [
        "raheemuddin.mohammed@ispace.com",
        "damhoi.hiyang@ispace.com",
        "mahesh.dammu@ispace.com",
    ],
    "mappings": {},
}


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


# ── Mapping store ───────────────────────────────────────────────────────────────
def load_email_map() -> dict:
    if not os.path.exists(EMAIL_MAP_FILE):
        save_email_map(DEFAULT_MAP)
        return dict(DEFAULT_MAP)
    try:
        with open(EMAIL_MAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("default", [])
        data.setdefault("mappings", {})
        return data
    except Exception:
        return dict(DEFAULT_MAP)


def save_email_map(mapping: dict) -> dict:
    clean = {
        "default": [str(e).strip() for e in mapping.get("default", []) if str(e).strip()],
        "mappings": {
            str(k).strip(): [str(e).strip() for e in v if str(e).strip()]
            for k, v in mapping.get("mappings", {}).items()
        },
    }
    with open(EMAIL_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)
    return clean


def resolve_recipients(office_name: str, mapping: dict | None = None) -> list:
    """Return the recipient list for an office (explicit mapping, else default)."""
    mapping = mapping or load_email_map()
    norm_lookup = {_norm(k): v for k, v in mapping.get("mappings", {}).items()}
    return norm_lookup.get(_norm(office_name), list(mapping.get("default", [])))


def _split_emails(cell) -> list:
    """Split an email cell on ; , / whitespace into a clean list."""
    if cell is None:
        return []
    return [e.strip() for e in re.split(r"[;,/\s]+", str(cell)) if e.strip() and "@" in e]


def parse_email_map_upload(name: str, data: bytes, keep_default: bool = True) -> dict:
    """
    Parse an uploaded Office → Email mapping file (.xlsx/.xls/.csv) and save it.
    Recognises an office-name column (contains 'office') and an email column
    (contains 'email'/'mail'/'recipient'). A row whose office is 'default', '*' or
    'fallback' sets the fallback recipients. Emails may be ;/,-separated.
    """
    import pandas as pd  # local import keeps module load light

    bio = io.BytesIO(data)
    if name.lower().endswith(".csv"):
        raw = pd.read_csv(bio, header=None, dtype=object)
    else:
        raw = pd.read_excel(bio, header=None, dtype=object)

    # Detect the header row (files often have a title row above it): the first row
    # with an 'office' cell and an 'email'/'mail'/'recipient' cell in DIFFERENT
    # columns (so a one-cell title like "DCA Offices with Email IDs" is not matched).
    def _cols_with(cells, keys):
        return [j for j, c in enumerate(cells)
                if not pd.isna(c) and any(k in str(c).lower() for k in keys)]

    hdr = None
    for i in range(min(15, len(raw))):
        cells = list(raw.iloc[i])
        office_cols = _cols_with(cells, ("office",))
        email_cols_i = _cols_with(cells, ("email", "mail", "recipient"))
        if office_cols and email_cols_i and any(o != e for o in office_cols for e in email_cols_i):
            hdr = i
            break
    if hdr is None:
        raise ValueError(
            "Mapping file needs a row with an office-name column and an email column. "
            "Expected headers like 'Office Name' and 'Email IDs'."
        )

    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr]]
    df = df.reset_index(drop=True)

    office_col = next((c for c in df.columns if "office" in c.lower()), None)
    # Prefer the plain email column over a 'manager' one for the primary recipient.
    email_cols = [c for c in df.columns if any(k in c.lower() for k in ("email", "mail", "recipient"))]
    email_col = next((c for c in email_cols if "manager" not in c.lower()), None) or (email_cols[0] if email_cols else None)
    if not office_col or not email_col:
        raise ValueError(
            "Mapping file needs an office-name column and an email column. "
            f"Found columns: {', '.join(df.columns)}"
        )

    existing = load_email_map()
    default = list(existing.get("default", [])) if keep_default else []
    mappings = {}
    for _, r in df.iterrows():
        office = "" if pd.isna(r[office_col]) else str(r[office_col]).strip()
        emails = _split_emails(r[email_col])
        if not office or not emails:
            continue
        if _norm(office) in ("default", "*", "fallback"):
            default = emails
        else:
            mappings[office] = emails

    return save_email_map({"default": default, "mappings": mappings})


def email_office_reports(reports: list, *, mode: str = "draft",
                         sender: str | None = None, mapping: dict | None = None) -> list:
    """
    Email a batch of per-office reports via desktop Outlook (one mail per office).

    reports : [{office, filename, xlsx_bytes}, ...] (from build_office_reports)
    mode    : "draft" (Display, not sent) or "send" (Send)
    sender  : optional 'send on behalf of' address (shared mailbox)

    Runs Outlook COM on the calling thread (CoInitialize per thread, required when
    invoked from a web-request worker). Returns a per-office result list.
    """
    import tempfile
    import pythoncom
    import win32com.client

    mapping = mapping or load_email_map()
    tmp_dir = os.path.join(tempfile.gettempdir(), "denticon_day_start")
    os.makedirs(tmp_dir, exist_ok=True)

    results = []
    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        for rep in reports:
            office = rep["office"]
            recipients = resolve_recipients(office, mapping)
            try:
                if not recipients:
                    raise ValueError("no recipients mapped for this office")
                tmp_path = os.path.join(tmp_dir, rep["filename"])
                with open(tmp_path, "wb") as f:
                    f.write(rep["xlsx_bytes"])

                mail = outlook.CreateItem(0)  # olMailItem
                mail.To = ";".join(recipients)
                mail.Subject = f"Day Start Report — {office}"
                mail.Body = (
                    f"Hello,\n\nPlease find attached the Day Start eligibility report "
                    f"for {office}.\n\nThank you,\nEligibility Verification Team"
                )
                mail.Attachments.Add(os.path.abspath(tmp_path))
                if sender:
                    mail.SentOnBehalfOfName = sender

                if mode == "send":
                    mail.Send()
                    action = "sent"
                    try:
                        os.remove(tmp_path)  # attachment already transmitted
                    except OSError:
                        pass
                else:
                    mail.Display(False)  # open draft for review; keep temp file
                    action = "drafted"

                results.append({"office": office, "recipients": recipients,
                                "rows": rep.get("rows"), "action": action, "ok": True})
            except Exception as e:
                results.append({"office": office, "recipients": recipients,
                                "rows": rep.get("rows"), "action": "failed",
                                "ok": False, "error": str(e)})
    finally:
        pythoncom.CoUninitialize()
    return results


# ── Outlook COM sending ───────────────────────────────────────────────────────
def send_office_report(
    office_name: str,
    attachment_path: str,
    recipients: list,
    *,
    mode: str = "draft",
    sender: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> dict:
    """
    Create one Outlook mail for a single office report.

    mode="draft" -> .Display() (opens for review, not sent)
    mode="send"  -> .Send()
    sender       -> optional 'send on behalf of' address (e.g. a shared mailbox);
                    None uses the default Outlook account.
    """
    import win32com.client  # imported lazily so the module loads on non-Windows too

    if not recipients:
        raise ValueError(f"No recipients resolved for office '{office_name}'.")
    if not os.path.isfile(attachment_path):
        raise ValueError(f"Attachment not found: {attachment_path}")

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # 0 = olMailItem

    mail.To = ";".join(recipients)
    mail.Subject = subject or f"Day Start Report — {office_name}"
    mail.Body = body or (
        f"Hello,\n\nPlease find attached the Day Start eligibility report for "
        f"{office_name}.\n\nThank you,\nEligibility Verification Team"
    )
    mail.Attachments.Add(os.path.abspath(attachment_path))
    if sender:
        mail.SentOnBehalfOfName = sender

    if mode == "send":
        mail.Send()
        action = "sent"
    else:
        mail.Display(False)  # open the draft for review; does not send
        action = "drafted"

    return {"office": office_name, "recipients": recipients, "action": action,
            "attachment": os.path.basename(attachment_path)}
