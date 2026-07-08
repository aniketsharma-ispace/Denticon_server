"""
Appointment report cleansing engine.

Implements Steps 2–5 of the Eligibility-Verification SOP as an automated,
uploadable workflow:

    Step 2  Remove previously processed patients   (by Patient ID, server memory)
    Step 3  Remove invalid records                 (Patient ID = 0 / blank insurance / blank notes)
    Step 4  Remove duplicate appointments          (keep earliest appointment time)
    Step 5  Exclude non-process insurance plans     (configurable exclusion list)

The operator uploads one or more Denticon appointment reports (e.g. Same-Day +
Next-Day). Their rows are UNIONed, cleansed, and returned as a single Excel file
of the fresh patients to work today. Processed Patient IDs are remembered in a
JSON store so they are automatically filtered out on subsequent days.
"""

from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime

import pandas as pd

# ── Persistent stores (simple JSON files next to the app) ──────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE   = os.path.join(BASE_DIR, "processed_history.json")
EXCLUSION_FILE = os.path.join(BASE_DIR, "insurance_exclusion.json")

DEFAULT_EXCLUSIONS = ["Dentrite", "Smile Alliance Care", "Cash"]

# ── Canonical columns and the header aliases we accept for each ────────────────
COLUMN_ALIASES = {
    "patient_id":         ["patient id", "patientid", "pat id", "patid", "pid", "patient no", "patientno"],
    "patient_name":       ["patient name", "patientname", "name", "patient"],
    "insurance":          ["insurance", "insurance name", "insurancename", "carrier", "plan", "ins", "insurance plan"],
    "appointment_notes":  ["appointment notes", "appt notes", "notes", "appointmentnotes", "apptnotes", "appointment note"],
    "appointment_date":   ["appointment date", "appt date", "date", "appointmentdate", "apptdate"],
    "appointment_time":   ["appointment time", "appt time", "time", "appointmenttime", "appttime"],
    "appointment_id":     ["appointment id", "appt id", "appointmentid", "apptid", "appointment no"],
    "appointment_status": ["appointment status", "status", "appt status", "appointmentstatus"],
    "office_name":        ["office name", "office", "officename", "location", "practice"],
}

# The four fields the SOP uses to detect duplicate appointments.
DUP_KEYS = ["patient_id", "patient_name", "insurance", "appointment_date"]


# ── Header helpers ─────────────────────────────────────────────────────────────
def _norm_header(h) -> str:
    """Lower-case, strip, collapse internal whitespace for fuzzy header matching."""
    return re.sub(r"\s+", " ", str(h).strip().lower())


def _build_column_map(columns) -> dict:
    """
    Map each canonical field → the real column name found in the DataFrame.
    Matches on normalised header text (exact, then alias, then no-space alias).
    """
    normalized = {c: _norm_header(c) for c in columns}
    mapping = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        alias_set     = {a for a in aliases}
        alias_nospace = {a.replace(" ", "") for a in aliases}
        for real, norm in normalized.items():
            if norm in alias_set or norm.replace(" ", "") in alias_nospace:
                mapping[canonical] = real
                break
    return mapping


# ── Value helpers ──────────────────────────────────────────────────────────────
def _norm_pid(v) -> str:
    """Canonicalise a Patient ID: 12345.0 / '12345 ' / 12345 → '12345'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v).strip()
    if s.lower() in ("", "nan", "none"):
        return ""
    # numeric string that is really an int written as a float, e.g. "12345.0"
    m = re.fullmatch(r"(\d+)\.0+", s)
    if m:
        return m.group(1)
    return s


def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    return str(v).strip() == "" or str(v).strip().lower() in ("nan", "none")


def _time_sort_key(series: pd.Series) -> pd.Series:
    """Best-effort parse of appointment time to a sortable value (earliest first)."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(series.astype(str), errors="coerce")
    # Fall back to a max value where parsing failed so rows still sort deterministically.
    return parsed.fillna(pd.Timestamp.max)


# ── Persistent-store accessors ─────────────────────────────────────────────────
def load_history() -> set:
    if not os.path.exists(HISTORY_FILE):
        return set()
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("processed_ids", []))
    except Exception:
        return set()


def _write_history(ids: set) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"processed_ids": sorted(ids), "updated_at": datetime.now().isoformat(timespec="seconds")},
            f,
            indent=2,
        )


def history_info() -> dict:
    ids = load_history()
    updated = None
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                updated = json.load(f).get("updated_at")
        except Exception:
            pass
    return {"count": len(ids), "updated_at": updated}


def reset_history() -> dict:
    _write_history(set())
    return history_info()


def load_exclusions() -> list:
    if not os.path.exists(EXCLUSION_FILE):
        save_exclusions(DEFAULT_EXCLUSIONS)
        return list(DEFAULT_EXCLUSIONS)
    try:
        with open(EXCLUSION_FILE, "r", encoding="utf-8") as f:
            return list(json.load(f).get("exclusions", DEFAULT_EXCLUSIONS))
    except Exception:
        return list(DEFAULT_EXCLUSIONS)


def save_exclusions(exclusions: list) -> list:
    cleaned = [str(x).strip() for x in exclusions if str(x).strip()]
    with open(EXCLUSION_FILE, "w", encoding="utf-8") as f:
        json.dump({"exclusions": cleaned}, f, indent=2)
    return cleaned


# ── Core cleansing ─────────────────────────────────────────────────────────────
def _read_excel(name: str, data: bytes) -> pd.DataFrame:
    bio = io.BytesIO(data)
    try:
        if name.lower().endswith(".csv"):
            df = pd.read_csv(bio, dtype=object)
        else:
            df = pd.read_excel(bio, dtype=object)
    except Exception as e:
        raise ValueError(f"Could not read '{name}': {e}")
    df["__source_file"] = name
    return df


def process_appointments(files: list[tuple[str, bytes]], commit: bool = True) -> dict:
    """
    files  : list of (filename, bytes) — one or more appointment reports to union.
    commit : if True, add the surviving Patient IDs to the processed-history store.

    Returns a dict with the per-step summary and the cleaned workbook bytes.
    """
    if not files:
        raise ValueError("No files provided.")

    frames = [_read_excel(name, data) for name, data in files]
    raw = pd.concat(frames, ignore_index=True)

    # Locate columns
    colmap = _build_column_map(raw.columns)
    if "patient_id" not in colmap:
        raise ValueError(
            "Could not find a 'Patient ID' column. Columns found: "
            + ", ".join(str(c) for c in raw.columns if c != "__source_file")
        )

    pid_col = colmap["patient_id"]
    df = raw.copy()
    df["__pid"] = df[pid_col].map(_norm_pid)

    total_input = len(df)
    steps = []

    # ── Step 2: Remove previously processed (Patient ID in history) ─────────────
    history = load_history()
    before = len(df)
    if history:
        df = df[~df["__pid"].isin(history)]
    removed_prev = before - len(df)
    steps.append({"step": "Removed previously processed", "removed": removed_prev})

    # ── Step 3: Remove invalid records ──────────────────────────────────────────
    before = len(df)
    invalid_mask = df["__pid"].isin(["", "0"])
    if "insurance" in colmap:
        invalid_mask |= df[colmap["insurance"]].map(_is_blank)
    if "appointment_notes" in colmap:
        invalid_mask |= df[colmap["appointment_notes"]].map(_is_blank)
    df = df[~invalid_mask]
    removed_invalid = before - len(df)
    steps.append({"step": "Removed invalid records", "removed": removed_invalid})

    # ── Step 4: Remove duplicate appointments (keep earliest time) ──────────────
    before = len(df)
    dup_subset = [colmap[k] for k in DUP_KEYS if k in colmap]
    if not dup_subset:
        dup_subset = ["__pid"]
    if "appointment_time" in colmap:
        df = df.assign(__tkey=_time_sort_key(df[colmap["appointment_time"]]))
        df = df.sort_values("__tkey", kind="stable")
    df = df.drop_duplicates(subset=dup_subset, keep="first")
    df = df.drop(columns=[c for c in ["__tkey"] if c in df.columns])
    removed_dupes = before - len(df)
    steps.append({"step": "Removed duplicate appointments", "removed": removed_dupes})

    # ── Step 5: Exclude non-process insurance plans ─────────────────────────────
    before = len(df)
    exclusions = load_exclusions()
    if exclusions and "insurance" in colmap:
        excl_lower = {e.strip().lower() for e in exclusions}
        ins_series = df[colmap["insurance"]].map(lambda v: str(v).strip().lower())
        df = df[~ins_series.isin(excl_lower)]
    removed_excluded = before - len(df)
    steps.append({"step": "Excluded non-process insurance", "removed": removed_excluded})

    # ── Output ──────────────────────────────────────────────────────────────────
    surviving_ids = set(df["__pid"]) - {""}
    # Write clean canonical Patient IDs back (avoids Excel's "1001.0" float display).
    df[pid_col] = df["__pid"]
    output_df = df.drop(columns=[c for c in ["__pid", "__source_file"] if c in df.columns])

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        output_df.to_excel(writer, index=False, sheet_name="Cleaned Appointments")
    out.seek(0)

    committed = False
    if commit and surviving_ids:
        history |= surviving_ids
        _write_history(history)
        committed = True

    return {
        "summary": {
            "files": [name for name, _ in files],
            "total_input_rows": total_input,
            "steps": steps,
            "final_rows": len(output_df),
            "unique_patients": len(surviving_ids),
            "committed_to_history": committed,
            "history_size": len(history),
        },
        "xlsx_bytes": out.getvalue(),
    }
