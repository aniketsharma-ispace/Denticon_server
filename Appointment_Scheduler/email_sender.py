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
