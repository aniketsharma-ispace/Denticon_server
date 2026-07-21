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
import zipfile
from datetime import datetime

import pandas as pd

# ── Persistent stores (simple JSON files next to the app) ──────────────────────
BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE     = os.path.join(BASE_DIR, "processed_history.json")
EXCLUSION_FILE   = os.path.join(BASE_DIR, "insurance_exclusion.json")
BLOCK_NAMES_FILE = os.path.join(BASE_DIR, "block_names.json")

DEFAULT_EXCLUSIONS = ["Dentrite", "Smile Alliance Care", "Cash"]

# Placeholder/operatory-block "patients" (Patient ID = 0) seen in real exports.
# These are not real patients and must never reach the allocation sheet.
# Operations can add to this list; matching is EXACT (case/whitespace-insensitive)
# on Patient Name — unlike the insurance exclusion list, this must NOT be a
# substring match, otherwise a real patient surnamed "Block" would be caught.
DEFAULT_BLOCK_NAMES = [
    "BLOCK, BLOCK",
    "14, Patient",
    "MANAGER BLOCK, Manager Block",
    "Block-, Block",
    "Adult 1st Chair, Adult Prophy 1st Chair",
    "Adult PATIENT 1st Chair, ADULT PATIENT 1ST CHAIR",
    "Adult PROPHY 1st Chair, Adult Prophy 1st Chair",
    "Adult 1st Chair, ADULT 1ST CHAIR",
]

# ── Canonical columns and the header aliases we accept for each ────────────────
COLUMN_ALIASES = {
    "patient_id":         ["patient id", "patientid", "pat id", "patid", "pid", "patient no", "patientno"],
    "patient_name":       ["patient name", "patientname", "name", "patient"],
    "insurance":          ["insurance", "insurance name", "insurancename", "carrier", "plan", "ins", "insurance plan"],
    "dental_primary_ins":   ["dental primary ins carr", "dental primary ins", "dental primary insurance",
                             "dental primary", "primary insurance", "primary ins", "dental primary ins carrier"],
    "dental_secondary_ins": ["dental secondary ins carr", "dental secondary ins", "dental secondary insurance",
                             "dental secondary", "secondary insurance", "secondary ins", "dental secondary ins carrier"],
    "appointment_notes":  ["appointment notes", "appt notes", "notes", "appointmentnotes", "apptnotes", "appointment note"],
    "appointment_date":   ["appointment date", "appt date", "date", "appointmentdate", "apptdate"],
    "appointment_time":   ["appointment time", "appt time", "time", "appointmenttime", "appttime"],
    "appointment_id":     ["appointment id", "appt id", "appointmentid", "apptid", "appointment no"],
    "appointment_status": ["appointment status", "status", "appt status", "appointmentstatus"],
    "office_name":        ["office name", "office", "officename", "location", "practice"],
}

# Office-wise Day Start Report columns (SOP Step 6), in exact output order.
# Each entry is (output header, canonical column key); "__pid" = cleaned Patient ID.
DAY_START_COLUMNS = [
    ("Office Name",               "office_name"),
    ("Appointment ID",            "appointment_id"),
    ("Appointment Date",          "appointment_date"),
    ("Appointment Time",          "appointment_time"),
    ("Appointment Status",        "appointment_status"),
    ("Patient ID",                "__pid"),
    ("Dental Primary Ins Carr",   "dental_primary_ins"),
    ("Dental Secondary Ins Carr", "dental_secondary_ins"),
]


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


def _alias_sets():
    """Flat lookup of every alias across all fields, plus the Patient-ID-only set."""
    all_exact, all_nospace = set(), set()
    for aliases in COLUMN_ALIASES.values():
        for a in aliases:
            all_exact.add(a)
            all_nospace.add(a.replace(" ", ""))
    pid_exact   = set(COLUMN_ALIASES["patient_id"])
    pid_nospace = {a.replace(" ", "") for a in COLUMN_ALIASES["patient_id"]}
    return all_exact, all_nospace, pid_exact, pid_nospace


def _cell_is_alias(cell, exact, nospace) -> bool:
    n = _norm_header(cell)
    return n in exact or n.replace(" ", "") in nospace


def _detect_header_row(raw: pd.DataFrame, max_scan: int = 20):
    """
    Find the real header row in a sheet that may have title/metadata rows above it.
    Returns the row index whose cells best match known column names AND contains a
    Patient ID header, or None if no such row is found in the first `max_scan` rows.
    """
    all_exact, all_nospace, pid_exact, pid_nospace = _alias_sets()
    best_idx, best_score = None, 0
    for i in range(min(max_scan, len(raw))):
        row = list(raw.iloc[i])
        if not any(_cell_is_alias(c, pid_exact, pid_nospace) for c in row):
            continue
        score = sum(_cell_is_alias(c, all_exact, all_nospace) for c in row)
        if score > best_score:
            best_score, best_idx = score, i
    return best_idx


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


def _norm_text(v) -> str:
    """Generic text canonicaliser for matching (trim, lower-case, collapse whitespace)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", " ", str(v).strip().lower())


def _norm_office(v) -> str:
    """Canonicalise an Office Name for matching (trim, lower-case, collapse whitespace)."""
    return _norm_text(v)


def _fmt_date(v) -> str:
    """Format a value to date only (MM/DD/YYYY); leave unparseable values as-is."""
    if _is_blank(v):
        return ""
    d = pd.to_datetime(str(v), errors="coerce")
    return d.strftime("%m/%d/%Y") if pd.notna(d) else str(v).strip()


def _fmt_time(v) -> str:
    """Format a value to time only (hh:MM AM/PM); leave unparseable values as-is."""
    if _is_blank(v):
        return ""
    d = pd.to_datetime(str(v), errors="coerce")
    return d.strftime("%I:%M %p") if pd.notna(d) else str(v).strip()


def _safe_filename(s) -> str:
    """Turn an office name into a filesystem-safe file stem."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(s).strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "Unknown_Office"


def _hist_key(pid: str, office: str, name: str = "") -> str:
    """
    Composite 'previously processed' key (SOP Step 2).

    Normal patients : Patient ID + Office Name — the same Patient ID can appear
    across different offices, so both are needed to form a unique key.
    Patient ID = 0  : these are placeholder rows, not unique patients, so the
    Patient Name is added to the key. Once such a row is processed it is
    remembered by name+office and won't reappear on later runs (tester #6/#14).
    """
    p = _norm_pid(pid)
    if p in ("", "0"):
        return f"{p}||{_norm_text(name)}||{_norm_office(office)}"
    return f"{p}||{_norm_office(office)}"


# ── Persistent-store accessors ─────────────────────────────────────────────────
# History is a list of {"patient_id", "office_name", "patient_name"} records.
# The unique key is Patient ID + Office Name (SOP Step 2 / Step 10); for
# Patient ID = 0 placeholder rows the Patient Name is part of the key too.
def load_history_records() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data.get("processed"), list):
        return [r for r in data["processed"] if isinstance(r, dict)]
    # Backward-compat: earlier format stored bare Patient IDs (no office).
    if isinstance(data.get("processed_ids"), list):
        return [{"patient_id": str(p), "office_name": "", "patient_name": ""} for p in data["processed_ids"]]
    return []


def load_history_keys() -> set:
    return {
        _hist_key(r.get("patient_id", ""), r.get("office_name", ""), r.get("patient_name", ""))
        for r in load_history_records()
    }


def _write_history(records: list) -> None:
    # De-duplicate by composite key; keep the original office/name text for audit.
    dedup = {}
    for r in records:
        pid    = _norm_pid(r.get("patient_id", ""))
        office = str(r.get("office_name", "") or "").strip()
        name   = str(r.get("patient_name", "") or "").strip()
        if pid in ("", "0") and not name:
            # A placeholder row with no name has no identity to match on later.
            continue
        key = _hist_key(pid, office, name)
        dedup[key] = {"patient_id": pid, "office_name": office, "patient_name": name}
    ordered = sorted(dedup.values(), key=lambda x: (x["patient_id"], x["office_name"], x["patient_name"]))
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"processed": ordered, "updated_at": datetime.now().isoformat(timespec="seconds")},
            f,
            indent=2,
        )


def history_info() -> dict:
    records = load_history_records()
    updated = None
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                updated = json.load(f).get("updated_at")
        except Exception:
            pass
    return {"count": len(records), "updated_at": updated}


def reset_history() -> dict:
    _write_history([])
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


def load_block_names() -> list:
    if not os.path.exists(BLOCK_NAMES_FILE):
        save_block_names(DEFAULT_BLOCK_NAMES)
        return list(DEFAULT_BLOCK_NAMES)
    try:
        with open(BLOCK_NAMES_FILE, "r", encoding="utf-8") as f:
            return list(json.load(f).get("block_names", DEFAULT_BLOCK_NAMES))
    except Exception:
        return list(DEFAULT_BLOCK_NAMES)


def save_block_names(block_names: list) -> list:
    cleaned = [str(x).strip() for x in block_names if str(x).strip()]
    with open(BLOCK_NAMES_FILE, "w", encoding="utf-8") as f:
        json.dump({"block_names": cleaned}, f, indent=2)
    return cleaned


# ── Core cleansing ─────────────────────────────────────────────────────────────
def _read_excel(name: str, data: bytes) -> pd.DataFrame:
    """
    Read a report, auto-detecting the header row so title/metadata rows above the
    real column headers (common in Denticon exports) don't break column matching.
    """
    bio = io.BytesIO(data)
    try:
        if name.lower().endswith(".csv"):
            raw = pd.read_csv(bio, header=None, dtype=object)
        else:
            raw = pd.read_excel(bio, header=None, dtype=object)
    except Exception as e:
        raise ValueError(f"Could not read '{name}': {e}")

    if raw.empty:
        raise ValueError(f"'{name}' is empty.")

    hdr = _detect_header_row(raw)
    if hdr is None:
        # No recognisable header found in the preamble — assume row 0 and let the
        # caller surface a clear "Patient ID column not found" error.
        hdr = 0

    header_vals = list(raw.iloc[hdr])
    df = raw.iloc[hdr + 1:].copy()
    df.columns = header_vals
    df = df.reset_index(drop=True)
    # Drop columns whose header is blank/NaN (empty spacer columns).
    df = df.loc[:, [c for c in df.columns if not _is_blank(c)]]
    # Drop rows that are entirely empty.
    df = df.dropna(how="all").reset_index(drop=True)
    df["__source_file"] = name
    return df


def _cleanse(files: list[tuple[str, bytes]]) -> dict:
    """
    Run the shared cleansing pipeline (SOP Steps 2–5 + Block Appointments) and
    return the cleaned rows BEFORE the primary/secondary split. Shared by the
    cleaned-dataset output and the office-wise Day Start reports.

    Returns: {df, colmap, steps, total_input, pid_col}. `df` keeps the internal
    helper columns (__pid/__office/__name/__key) for downstream callers.
    """
    if not files:
        raise ValueError("No files provided.")

    frames = [_read_excel(name, data) for name, data in files]
    raw = pd.concat(frames, ignore_index=True)

    # Locate columns
    colmap = _build_column_map(raw.columns)
    if "patient_id" not in colmap:
        found = [str(c) for c in raw.columns if c != "__source_file"]
        raise ValueError(
            "Could not find a 'Patient ID' column in the upload. "
            "Make sure the file has a header row containing a column named 'Patient ID' "
            "(or Pat ID / PatientID / PID). Detected column headers: "
            + (", ".join(found) if found else "(none)")
        )

    pid_col    = colmap["patient_id"]
    office_col = colmap.get("office_name")
    name_col   = colmap.get("patient_name")
    df = raw.copy()
    df["__pid"] = df[pid_col].map(_norm_pid)
    if office_col:
        df["__office"] = df[office_col].map(lambda v: "" if _is_blank(v) else str(v).strip())
    else:
        df["__office"] = ""
    if name_col:
        df["__name"] = df[name_col].map(lambda v: "" if _is_blank(v) else str(v).strip())
    else:
        df["__name"] = ""
    # Composite previously-processed key: Patient ID + Office (+ Name for ID = 0)
    df["__key"] = [_hist_key(p, o, n) for p, o, n in zip(df["__pid"], df["__office"], df["__name"])]

    total_input = len(df)
    steps = []

    # ── Step 2: Remove previously processed (Patient ID + Office Name) ───────────
    hist_keys = load_history_keys()
    before = len(df)
    if hist_keys:
        df = df[~df["__key"].isin(hist_keys)]
    removed_prev = before - len(df)
    steps.append({"step": "Removed previously processed (Patient ID + Office)", "removed": removed_prev})

    # ── Additional Requirement 8: Remove Block Appointments ──────────────────────
    # Operatory/schedule-block placeholder rows (Patient ID = 0) with a Patient Name
    # matching the configurable block-name list, e.g. "BLOCK, BLOCK" or
    # "Adult 1st Chair, Adult Prophy 1st Chair". This is an EXACT match (normalised
    # for case/whitespace) — never a substring match — so a real patient surnamed
    # "Block" is not caught. Runs before Step 3 so a block row is removed even if it
    # happens to carry notes/insurance that would otherwise save it from that rule.
    before = len(df)
    block_names = {_norm_text(b) for b in load_block_names()}
    if block_names:
        block_mask = df["__pid"].isin(["", "0"]) & df["__name"].map(_norm_text).isin(block_names)
        df = df[~block_mask]
    removed_block = before - len(df)
    steps.append({"step": "Removed block appointments", "removed": int(removed_block)})

    # ── Step 3: Remove invalid records ──────────────────────────────────────────
    # A record is invalid ONLY when ALL of the following hold together (AND):
    #   • Patient ID = 0 (or blank)
    #   • BOTH Dental Primary Ins and Dental Secondary Ins are blank
    #   • Appointment Notes are blank
    before = len(df)
    pid_zero = df["__pid"].isin(["", "0"])

    ins_cols = [colmap[k] for k in ("dental_primary_ins", "dental_secondary_ins") if k in colmap]
    if not ins_cols and "insurance" in colmap:
        ins_cols = [colmap["insurance"]]
    if ins_cols:
        ins_blank = pd.Series(True, index=df.index)
        for c in ins_cols:
            ins_blank &= df[c].map(_is_blank)
    else:
        # No insurance column detected → cannot confirm "blank", so don't flag on this.
        ins_blank = pd.Series(False, index=df.index)

    if "appointment_notes" in colmap:
        notes_blank = df[colmap["appointment_notes"]].map(_is_blank)
    else:
        notes_blank = pd.Series(False, index=df.index)

    invalid_mask = pid_zero & ins_blank & notes_blank
    df = df[~invalid_mask]
    removed_invalid = before - len(df)
    steps.append({"step": "Removed invalid records", "removed": int(removed_invalid)})

    # ── Step 4: Remove duplicate appointments (keep earliest time) ──────────────
    # Duplicate key = Patient ID + Patient Name + Insurance + Appointment Date,
    # scoped WITHIN an office (tester #2: the same patient at two different offices
    # on the same day is two distinct appointments, not a duplicate).
    #  • Insurance component = Dental Primary Ins Carr (falls back to a generic
    #    'insurance' column if that's what the report uses).
    #  • Appointment Date is normalised to the DATE ONLY (this export stores a full
    #    datetime in that column), so different times on the same day group together.
    #  • Within a duplicate group, keep the earliest Appointment Time; drop the rest.
    before = len(df)
    ins_key_col = colmap.get("dental_primary_ins") or colmap.get("insurance")

    df["__k_pid"]    = df["__pid"]
    df["__k_office"] = df["__office"].map(_norm_text)
    df["__k_name"]   = df["__name"].map(_norm_text)
    df["__k_ins"]    = df[ins_key_col].map(_norm_text) if ins_key_col else ""
    if "appointment_date" in colmap:
        _d = pd.to_datetime(df[colmap["appointment_date"]].astype(str), errors="coerce")
        df["__k_date"] = _d.dt.date.astype(str)
    else:
        df["__k_date"] = ""

    if "appointment_time" in colmap:
        df["__tkey"] = _time_sort_key(df[colmap["appointment_time"]])
        df = df.sort_values("__tkey", kind="stable")

    dup_subset = ["__k_office", "__k_pid", "__k_name", "__k_ins", "__k_date"]
    df = df.drop_duplicates(subset=dup_subset, keep="first")
    df = df.drop(columns=[c for c in ["__k_pid", "__k_office", "__k_name", "__k_ins", "__k_date", "__tkey"] if c in df.columns])
    removed_dupes = before - len(df)
    steps.append({"step": "Removed duplicate appointments", "removed": int(removed_dupes)})

    # ── Step 5: Exclude non-process insurance plans ─────────────────────────────
    # Case-insensitive CONTAINS match against the exclusion list, checking BOTH the
    # Dental Primary and Dental Secondary carriers. A row is excluded if EITHER
    # carrier text contains any exclusion entry. The operator controls breadth via
    # the entry: "Cash" catches "Cash - Self Pay Ph#:-", while a specific entry like
    # "Delta Dental INS" won't catch "Delta Dental WI".
    before = len(df)
    exclusions = [e.strip().lower() for e in load_exclusions() if e.strip()]
    excl_cols = [colmap[k] for k in ("dental_primary_ins", "dental_secondary_ins") if k in colmap]
    if not excl_cols and "insurance" in colmap:
        excl_cols = [colmap["insurance"]]
    if exclusions and excl_cols:
        excl_mask = pd.Series(False, index=df.index)
        for c in excl_cols:
            carrier = df[c].map(_norm_text)
            for term in exclusions:
                excl_mask |= carrier.str.contains(re.escape(term), na=False)
        df = df[~excl_mask]
    removed_excluded = before - len(df)
    steps.append({"step": "Excluded non-process insurance", "removed": int(removed_excluded)})

    return {"df": df, "colmap": colmap, "steps": steps,
            "total_input": total_input, "pid_col": pid_col}


def process_appointments(files: list[tuple[str, bytes]], commit: bool = True) -> dict:
    """
    files  : list of (filename, bytes) — one or more appointment reports to union.
    commit : if True, add the surviving Patient IDs to the processed-history store.

    Returns a dict with the per-step summary and the cleaned workbook bytes
    (one row per appointment split into Primary/Secondary rows).
    """
    c = _cleanse(files)
    df, colmap, steps = c["df"], c["colmap"], c["steps"]
    total_input, pid_col = c["total_input"], c["pid_col"]

    # ── Split Primary & Secondary insurance into separate rows (SOP Step 7) ─────
    # A patient with BOTH a Dental Primary and a Dental Secondary carrier gets two
    # rows — one marked "Primary", one "Secondary" — so each insurance can be
    # verified independently (tester #9). Single-insurance rows are marked with
    # whichever side they have.
    prim_col = colmap.get("dental_primary_ins")
    sec_col  = colmap.get("dental_secondary_ins")
    if prim_col and sec_col:
        has_prim = ~df[prim_col].map(_is_blank)
        has_sec  = ~df[sec_col].map(_is_blank)
        both = df[has_prim & has_sec]

        df = df.copy()
        df["Primary / Secondary"] = ""
        df.loc[has_prim, "Primary / Secondary"] = "Primary"
        df.loc[~has_prim & has_sec, "Primary / Secondary"] = "Secondary"

        sec_rows = both.copy()
        sec_rows["Primary / Secondary"] = "Secondary"
        added_split = len(sec_rows)
        if added_split:
            df = pd.concat([df, sec_rows], ignore_index=True)
            # Keep a stable order: office, then patient, then Primary before Secondary.
            df = df.sort_values(["__office", "__pid", "Primary / Secondary"], kind="stable").reset_index(drop=True)

        # SOP 6.5: once split, each row shows ONLY the insurance being verified in
        # that row — clear the Secondary carrier on Primary rows and the Primary
        # carrier on Secondary rows.
        df.loc[df["Primary / Secondary"] == "Primary",   sec_col]  = ""
        df.loc[df["Primary / Secondary"] == "Secondary", prim_col] = ""
    else:
        added_split = 0
    steps.append({"step": "Split primary & secondary insurance", "added": int(added_split)})

    # ── Output ──────────────────────────────────────────────────────────────────
    surviving_ids  = set(df["__pid"]) - {""}
    surviving_keys = set(df["__key"])
    # Write clean canonical Patient IDs back (avoids Excel's "1001.0" float display).
    df[pid_col] = df["__pid"]
    output_df = df.drop(columns=[c for c in ["__pid", "__office", "__name", "__key", "__source_file"] if c in df.columns])

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        output_df.to_excel(writer, index=False, sheet_name="Cleaned Appointments")
    out.seek(0)

    # ── Commit surviving Patient ID + Office to history (SOP Step 10) ────────────
    committed = False
    if commit and surviving_keys:
        survivors = df.drop_duplicates("__key")
        # Patient ID = 0 placeholder rows are remembered too, identified by their
        # Patient Name + Office (tester #6/#14: once processed they must not
        # reappear on the next run). Nameless ID-0 rows are skipped inside
        # _write_history since they have no identity to match on later.
        new_records = [
            {"patient_id": p, "office_name": o, "patient_name": n}
            for p, o, n in zip(survivors["__pid"], survivors["__office"], survivors["__name"])
        ]
        _write_history(load_history_records() + new_records)
        committed = True

    return {
        "summary": {
            "files": [name for name, _ in files],
            "total_input_rows": total_input,
            "steps": steps,
            "final_rows": len(output_df),
            "unique_patients": len(surviving_ids),
            "unique_patient_offices": len(surviving_keys),
            "committed_to_history": committed,
            "history_size": len(load_history_records()),
        },
        "xlsx_bytes": out.getvalue(),
    }


def generate_day_start_reports(files: list[tuple[str, bytes]]) -> dict:
    """
    SOP Step 6 — Generate an office-wise Day Start Report.

    Runs the shared cleansing pipeline (Steps 2–5 + block), then produces ONE
    Excel per office (one row per appointment, both carriers shown — no P/S split)
    containing only the Step-6 columns, and returns them bundled in a ZIP. Offices
    with no surviving appointments get no file (tester #18). Does NOT commit to
    history — this is a report view, not the processing action.
    """
    c = _cleanse(files)
    df, colmap = c["df"], c["colmap"]

    # Build the report frame with the Step-6 columns that exist in this upload.
    report = pd.DataFrame(index=df.index)
    present_headers = []
    for header, key in DAY_START_COLUMNS:
        if key == "__pid":
            report[header] = df["__pid"]
        elif key in colmap:
            src = df[colmap[key]]
            if key == "appointment_date":
                report[header] = src.map(_fmt_date)
            elif key == "appointment_time":
                report[header] = src.map(_fmt_time)
            else:
                report[header] = src
        else:
            continue
        present_headers.append(header)

    report["__office_group"] = df["__office"].values

    date_tag = datetime.now().strftime("%Y%m%d")
    offices = []
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for office, group in report.groupby("__office_group", sort=True):
            office_name = office or "Unknown Office"
            out_df = group[present_headers]
            xb = io.BytesIO()
            with pd.ExcelWriter(xb, engine="openpyxl") as writer:
                out_df.to_excel(writer, index=False, sheet_name="Day Start")
            fname = f"DayStart_{_safe_filename(office_name)}_{date_tag}.xlsx"
            zf.writestr(fname, xb.getvalue())
            offices.append({"office": office_name, "rows": int(len(out_df)), "file": fname})
    zip_buf.seek(0)

    return {
        "summary": {
            "files": [name for name, _ in files],
            "steps": c["steps"],
            "columns": present_headers,
            "office_count": len(offices),
            "total_report_rows": int(len(report)),
            "offices": offices,
        },
        "zip_bytes": zip_buf.getvalue(),
    }
