"""
Holding area for portal scrapes waiting to be filled into Sabrina.

The extension posts each portal export here instead of downloading it. When
the user opens that patient's Fill Form, the extension asks for the latest
pending scrape for the member, fills the form from it, and marks it used so a
later appointment for the same member never picks up stale data.

A plain SQLite file next to the server — no extra service to run. Rows are
patient data, so they are kept only as long as they are useful: anything
older than RETENTION_DAYS is deleted on every save.

    SCRAPE_DB              path of the database file (default data/scrapes.db)
    SCRAPE_RETENTION_DAYS  how long a scrape is kept (default 7)
    SCRAPE_MAX_AGE_HOURS   how old a pending scrape may be and still fill a
                           form (default 48)
    SCRAPE_OTHER_BROWSER_MINUTES
                           how old a scrape made in another browser (scraped
                           in Firefox, filled in Edge) may be (default 60)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("SCRAPE_DB") or os.path.join(_HERE, "data", "scrapes.db")
RETENTION_DAYS = int(os.environ.get("SCRAPE_RETENTION_DAYS", "7"))
MAX_AGE_HOURS = int(os.environ.get("SCRAPE_MAX_AGE_HOURS", "48"))
OTHER_BROWSER_MINUTES = int(os.environ.get("SCRAPE_OTHER_BROWSER_MINUTES", "60"))

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scrapes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            client      TEXT NOT NULL,
            carrier     TEXT,
            member_id   TEXT NOT NULL,      -- normalized: letters and digits, upper case
            dob         TEXT,               -- MM/DD/YYYY
            scraped_at  TEXT NOT NULL,      -- UTC ISO timestamp
            status      TEXT NOT NULL DEFAULT 'pending',   -- pending | used
            used_at     TEXT,
            data        TEXT NOT NULL       -- the portal export, as JSON
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scrapes_member "
                 "ON scrapes (client, member_id, status)")
    return conn


def norm_member(member_id) -> str:
    """'w503-349 657' → 'W503349657', so the page and the portal agree on format."""
    return re.sub(r"[^A-Za-z0-9]", "", str(member_id or "")).upper()


def norm_dob(dob) -> str | None:
    """'1/9/03', '01/09/2003' or '2003-01-09' → '01/09/2003'."""
    text = str(dob or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", text)
    if m:
        year = m.group(3)
        if len(year) == 2:
            year = ("20" if int(year) <= datetime.now().year % 100 else "19") + year
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{year}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(2)}/{m.group(3)}/{m.group(1)}"
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def save(client: str, carrier: str | None, member_id: str, dob: str | None, data: dict) -> int:
    """Store a scrape as pending; returns its id. Also purges expired rows."""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM scrapes WHERE scraped_at < ?",
                     ((_now() - timedelta(days=RETENTION_DAYS)).isoformat(),))
        cur = conn.execute(
            "INSERT INTO scrapes (client, carrier, member_id, dob, scraped_at, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (client, carrier, norm_member(member_id), norm_dob(dob),
             _now().isoformat(), json.dumps(data)))
        return int(cur.lastrowid)


def find_pending(client: str, member_id: str, dob: str | None = None,
                 max_age_minutes: int | None = None) -> dict | None:
    """
    The latest pending scrape for this member, or None.

    When both the form and the scrape state a DOB they must agree, so two
    family members sharing a subscriber ID cannot be mixed up.
    `max_age_minutes` narrows the default MAX_AGE_HOURS window.
    """
    age = timedelta(minutes=max_age_minutes) if max_age_minutes is not None else timedelta(hours=MAX_AGE_HOURS)
    since = (_now() - age).isoformat()
    want_dob = norm_dob(dob)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM scrapes WHERE client = ? AND member_id = ? AND status = 'pending' "
            "AND scraped_at >= ? ORDER BY scraped_at DESC",
            (client, norm_member(member_id), since)).fetchall()
    for row in rows:
        if want_dob and row["dob"] and row["dob"] != want_dob:
            continue
        return _as_dict(row)
    return None


def get_pending(client: str, scrape_id: int) -> dict | None:
    """One pending scrape by its id (the user's own last scrape), or None."""
    since = (_now() - timedelta(hours=MAX_AGE_HOURS)).isoformat()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM scrapes WHERE id = ? AND client = ? AND status = 'pending' "
            "AND scraped_at >= ?", (int(scrape_id), client, since)).fetchone()
    return _as_dict(row) if row else None


def _as_dict(row) -> dict:
    return {
        "id": row["id"],
        "carrier": row["carrier"],
        "member_id": row["member_id"],
        "dob": row["dob"],
        "scraped_at": row["scraped_at"],
        "data": json.loads(row["data"]),
    }


def mark_used(scrape_id: int) -> bool:
    """Mark a scrape used; False when there is no such scrape."""
    with _lock, _connect() as conn:
        cur = conn.execute("UPDATE scrapes SET status = 'used', used_at = ? WHERE id = ?",
                           (_now().isoformat(), int(scrape_id)))
        return cur.rowcount > 0
