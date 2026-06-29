import re
from datetime import datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_money(raw: str) -> str:
    m = re.search(r"\$?\s*([\d,]+\.?\d*)", str(raw))
    return m.group(1).replace(",", "") if m else raw


def parse_dollars(val: str) -> float:
    try:
        return float(re.sub(r'[^\d.]', '', str(val)))
    except (ValueError, TypeError):
        return 0.0


def calc_used(total_str: str, remaining_str: str) -> str:
    total     = parse_dollars(total_str)
    remaining = parse_dollars(remaining_str)
    used      = total - remaining
    return f"{used:.2f}" if total > 0 else "0.00"


def late_dos_metlife(procedures: list, code: str) -> str:
    """Extract last date of service from MetLife procedure list (MM/DD/YY or MM/DD/YYYY)."""
    for p in procedures:
        if (p.get("procedure_code") or "").upper() == code.upper():
            dos = (p.get("late_date_of_service") or "").strip()
            if not dos or dos == "—":
                return "NH"
            for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    return datetime.strptime(dos, fmt).strftime("%m/%d/%Y")
                except ValueError:
                    continue
            return dos
    return "NH"


def late_dos_cigna(procedures: list, code: str) -> str:
    """Extract last date of service from Cigna procedure list (YYYY-MM-DD)."""
    for p in procedures:
        if (p.get("procedure_code") or "").upper() == code.upper():
            dos = (p.get("history_date") or "").strip()
            if not dos or dos in ("N/A", "No history on file", "—", ""):
                return "NH"
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
                try:
                    return datetime.strptime(dos, fmt).strftime("%m/%d/%Y")
                except ValueError:
                    continue
            return dos
    return "NH"


def _extract_carrier(carrier_raw: str) -> str:
    """
    Normalize carrier name from Denticon's raw field.
    Strips (IN)/(OUT) prefixes, then keeps only consecutive
    meaningful alpha words before noise like PPO, PID, digits.

    Examples:
      "(IN) MetLife PPO PID 65978"  → "METLIFE"
      "(IN) Delta Dental PPO"       → "DELTA DENTAL"
      "CIGNA PPO"                   → "CIGNA"
    """
    cleaned = re.sub(r"\(IN\)\s*|\(OUT\)\s*", "", carrier_raw).strip().upper()
    tokens  = cleaned.split()
    meaningful = []
    for w in tokens:
        if w.isalpha() and len(w) > 3:
            meaningful.append(w)
        else:
            break  # stop at PPO, PID, numbers etc.
    return " ".join(meaningful) if meaningful else (tokens[0] if tokens else "")


# ── Main logic ────────────────────────────────────────────────────────────────

def build_patient_notes(denticon_data: dict, insurance_data: dict) -> dict:
    """
    Build the patient notes dict from Denticon + portal insurance JSON.

    Parameters
    ----------
    denticon_data  : Denticon deep audit JSON  (contains denticon_data key)
    insurance_data : Portal JSON (MetLife or Cigna export)
    """
    dent = denticon_data.get("denticon_data", denticon_data)
    ins  = insurance_data

    # ── Denticon fields ───────────────────────────────────────────────────────
    header      = dent.get("header", {})
    plans       = dent.get("plans", [])
    plan        = plans[-1] if plans else {}
    ins_summary = header.get("insurance_summary", {})
    dent_pi     = dent.get("primary_insurance", {})

    # Carrier: from Denticon first, then portal source string as fallback
    carrier_raw = (
        ins_summary.get("provider", "") or
        dent_pi.get("carrier_name", "")
    )
    carrier = _extract_carrier(carrier_raw)

    if not carrier:
        _src = (
            ins.get("metlife_data", {}).get("source", "") or
            ins.get("benefit_coverage", {}).get("source", "") or
            ins.get("source", "") or
            ""
        )
        _m = re.search(r'^([A-Za-z]+)\s+Portal', str(_src))
        if _m:
            carrier = _m.group(1).upper()

    # Plan type from Denticon notes blob
    notes_text      = plan.get("benefits", {}).get("notes", "")
    plan_type_match = re.search(r"PPO/HMO/INDEMNITY\s*:(\w+)", notes_text)
    plan_type       = plan_type_match.group(1).strip() if plan_type_match else "PPO"

    verification_date = datetime.now().strftime("%m/%d/%Y")

    # ── Portal detection ──────────────────────────────────────────────────────
    metlife_data = (
        ins.get("metlife_data") or
        (ins if "MetLife" in str(ins.get("source", "")) else None) or
        {}
    )
    cigna_data = (
        ins.get("cigna_data") or
        (ins if ins.get("source") == "Cigna Portal" else None) or
        {}
    )

    is_cigna   = bool(cigna_data)
    is_metlife = bool(metlife_data) and not is_cigna

    patient_name = (
        metlife_data.get("patient", {}).get("name") or
        cigna_data.get("patient", {}).get("name")   or
        ins.get("dentaquest_data", {}).get("patient", {}).get("name") or
        ins.get("patient", {}).get("name")           or
        header.get("patient_name")                   or
        dent.get("patient", {}).get("name")          or
        "UNKNOWN"
    )

    # ── Financials ────────────────────────────────────────────────────────────
    ind_max_used = ind_ded_used = ortho_used = ""

    if is_metlife:
        fin          = metlife_data.get("financials", {})
        ind_max_used = fmt_money(fin.get("annual_max",     {}).get("used", ""))
        ind_ded_used = fmt_money(fin.get("deductible_ind", {}).get("used", ""))
        ortho_used   = fmt_money(fin.get("ortho_lifetime", {}).get("used", ""))

    elif is_cigna:
        fin        = cigna_data.get("financials", {})
        annual_max = fin.get("annual_max",     {})
        deductible = fin.get("deductible_ind", {})
        ortho      = fin.get("ortho_lifetime", {})

        # Cigna gives remaining + total; used = total - remaining
        ind_max_used = calc_used(annual_max.get("total", ""), annual_max.get("remaining", ""))
        ind_ded_used = calc_used(deductible.get("total", ""), deductible.get("remaining", ""))
        ortho_used   = calc_used(ortho.get("total", ""),      ortho.get("remaining", ""))

        if not carrier:
            carrier = "CIGNA"

    # ── Procedure history ─────────────────────────────────────────────────────
    if is_cigna:
        procedures = cigna_data.get("procedures", {}).get("results", [])
        dos_fn     = late_dos_cigna
    else:
        procedures = ins.get("benefit_coverage", {}).get("procedures", [])
        dos_fn     = late_dos_metlife

    return {
        "patient_name":               patient_name,
        "appointment_date":           "",
        "verified_by":                "",
        "verification_date":          verification_date,
        "eligibility_status":         "Currently Eligible",
        "carrier":                    carrier,
        "primary_secondary":          "Primary",
        "plan_type":                  plan_type,
        "patient_assigned_to_office": "NA",
        "individual_maximum_used":    ind_max_used,
        "individual_deductible_used": ind_ded_used,
        "ortho_maximum_used":         ortho_used,
        "history": {
            "periodic_exam_d0120":  dos_fn(procedures, "D0120"),
            "comp_exam_d0150":      dos_fn(procedures, "D0150"),
            "prophy_d1110":         dos_fn(procedures, "D1110"),
            "perio_maint_d4910":    dos_fn(procedures, "D4910"),
            "fmd_d4355":            dos_fn(procedures, "D4355"),
            "fluoride_d1206_d1208": dos_fn(procedures, "D1206"),
            "xray_d0274":           dos_fn(procedures, "D0274"),
            "xray_d0210":           dos_fn(procedures, "D0210"),
        },
    }