import re
from datetime import datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_money(raw: str) -> str:
    m = re.search(r"\$?\s*([\d,]+\.?\d*)", str(raw))
    return m.group(1).replace(",", "") if m else raw


def parse_dollars(val: str) -> float:
    try:
        return float(re.sub(r'[^\d.]', '', str(val)))
    except Exception:
        return 0.0


def calc_used(total_str: str, remaining_str: str) -> str:
    total     = parse_dollars(total_str)
    remaining = parse_dollars(remaining_str)
    used      = total - remaining
    return f"{used:.2f}" if total > 0 else "0.00"


def late_dos_metlife(procedures: list, code: str) -> str:
    for p in procedures:
        if p.get("procedure_code", "").upper() == code.upper():
            dos = p.get("late_date_of_service", "").strip()
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
    for p in procedures:
        if p.get("procedure_code", "").upper() == code.upper():
            dos = p.get("history_date", "").strip()
            if not dos or dos in ("N/A", "No history on file", "—", ""):
                return "NH"
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
                try:
                    return datetime.strptime(dos, fmt).strftime("%m/%d/%Y")
                except ValueError:
                    continue
            return dos
    return "NH"

def late_dos_dd_ins_scraper(benefits_search: list, code: str) -> str:
    for entry in benefits_search:
        if entry.get("code", "").upper() == code.upper():
            for row in entry.get("rows", []):
                # The extension's row field for this was renamed from
                # "coverage_details" to "service_date" at some point; read
                # whichever is present so older scraped files still work.
                val = (row.get("service_date") or row.get("coverage_details") or "").strip()
                if not val or val in ("None", "N/A", ""):
                    return "NH"
                first = val.split(",")[0].strip()
                if not re.match(r"\d{1,2}/\d{1,2}/\d{2,4}", first):
                    return "NH"
                for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                    try:
                        return datetime.strptime(first, fmt).strftime("%m/%d/%Y")
                    except ValueError:
                        continue
    return "NH"

def late_dos_ddva(history: list, code: str) -> str:
    """
    DD Virginia (content_delta_dental_va.js) — flat history list, newest first,
    each entry: {"dateOfService": "06-24-2026", "code": "D1110", ...}.
    """
    for h in history:
        if h.get("code", "").upper() == code.upper():
            raw = (h.get("dateOfService") or "").strip()
            if not raw:
                return "NH"
            for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%m/%d/%y"):
                try:
                    return datetime.strptime(raw, fmt).strftime("%m/%d/%Y")
                except ValueError:
                    continue
            return raw
    return "NH"

def _normalize_name_for_match(name: str) -> str:
    """
    Normalize a name to 'FIRST LAST' uppercase, regardless of whether
    it came in as 'LAST, FIRST' (Denticon) or 'FIRST LAST' (PDF).
    """
    name = (name or "").strip()
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    return re.sub(r"\s+", " ", name).strip().upper()


def _name_match_loose(name_a: str, name_b: str) -> bool:
    """
    Compare two names ignoring middle initials/middle names — Denticon
    often omits middle initials/names that PDFs include (e.g. Denticon
    "DE LA ROSA, JULIANNA" vs PDF "JULIANNA G DE LA ROSA"). Matches on
    first token + last token only, after normalizing to 'FIRST ... LAST'.
    """
    a = _normalize_name_for_match(name_a).split()
    b = _normalize_name_for_match(name_b).split()
    if not a or not b:
        return False
    return a[0] == b[0] and a[-1] == b[-1]


def _extract_carrier(carrier_raw: str) -> str:
    if not carrier_raw:
        return ""

    cleaned = re.sub(r"\(IN\)\s*|\(OUT\)\s*", "", carrier_raw, flags=re.IGNORECASE).strip()

    if re.search(r"\bDELTA\b", cleaned, re.IGNORECASE):
        # Keep the full plan name as Denticon wrote it; just cut off the
        # "PPO" plan-type marker and anything trailing it (e.g. "PID 39069").
        m = re.search(r"\s*\(?\bPPO\b\)?", cleaned, re.IGNORECASE)
        if m:
            cleaned = cleaned[:m.start()]
        return re.sub(r"[\s\-–.]+$", "", cleaned).strip()

    cleaned = cleaned.upper()
    tokens = cleaned.split()
    meaningful = []
    for w in tokens:
        if w.isalpha() and len(w) > 3:
            meaningful.append(w)
        else:
            break
    return " ".join(meaningful) if meaningful else (tokens[0] if tokens else "")


def build_patient_notes(denticon_data: dict, insurance_data: dict) -> dict:
    dent = denticon_data.get("denticon_data", denticon_data)
    ins  = insurance_data

    header      = dent.get("header", {})
    plans       = dent.get("plans", [])
    plan        = plans[-1] if plans else {}
    ins_summary = header.get("insurance_summary", {})
    dent_pi     = dent.get("primary_insurance", {})

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

    notes_text      = plan.get("benefits", {}).get("notes", "")
    plan_type_match = re.search(r"PPO/HMO/INDEMNITY\s*:(\w+)", notes_text)
    plan_type       = plan_type_match.group(1).strip() if plan_type_match else "PPO"

    verification_date = datetime.now().strftime("%m/%d/%Y")

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

    aetna_data = ins if (ins.get("service_level_benefits") and ins.get("maximums")) else {}
    is_aetna   = bool(aetna_data) and not is_metlife and not is_cigna

    dd_ins_data = ins if (ins.get("source") == "Delta Dental" and ins.get("tabs")) else {}
    is_dd_scraper   = bool(dd_ins_data) and not is_metlife and not is_cigna and not is_aetna

    dd_wi_pdf_data = ins if (ins.get("financials_by_patient") and ins.get("history_by_patient")) else {}
    is_dd_wi_pdf   = bool(dd_wi_pdf_data)
    
    ddri_data = ins if ins.get("ddri_data") else {}
    is_ddri   = bool(ddri_data) and not is_metlife and not is_cigna and not is_aetna and not is_dd_scraper and not is_dd_wi_pdf
    
    ddva_data = ins if (ins.get("benefitPlan") and ins.get("accumulators")) else {}
    is_ddva   = bool(ddva_data) and not is_metlife and not is_cigna and not is_aetna and not is_dd_scraper and not is_dd_wi_pdf
    
    ucci_data = ins if ins.get("source") == "UCCI" else {}
    is_ucci   = bool(ucci_data) and not is_metlife and not is_cigna and not is_aetna and not is_dd_scraper and not is_dd_wi_pdf and not is_ddri and not is_ddva

    pdf_data = ins if (ins.get("benefit_coverage") and not is_metlife and not is_cigna
                    and not is_aetna and not is_dd_wi_pdf) else {}
    is_pdf   = bool(pdf_data)

    patient_name = (
        metlife_data.get("patient", {}).get("name") or
        cigna_data.get("patient", {}).get("name")   or
        aetna_data.get("patient", {}).get("name")   or
        header.get("patient_name")                   or
        dent.get("patient", {}).get("name")          or
        "UNKNOWN"
    )

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
        ind_max_used = calc_used(annual_max.get("total", ""), annual_max.get("remaining", ""))
        ind_ded_used = calc_used(deductible.get("total", ""), deductible.get("remaining", ""))
        ortho_used   = calc_used(ortho.get("total", ""),      ortho.get("remaining", ""))
        if not carrier:
            carrier = "CIGNA"

    elif is_aetna:
        def _aetna_max(type_str: str):
            for mx in aetna_data.get("maximums", []):
                if mx.get("type", "").lower() == type_str.lower() and mx.get("coverage", "").lower() == "individual":
                    return mx.get("amount", ""), mx.get("remaining", "")
            return "", ""
        dental_total, dental_rem = _aetna_max("DENTAL")
        ortho_total,  ortho_rem  = _aetna_max("Orthodontics")
        ind_max_used = calc_used(dental_total, dental_rem)
        ind_ded_used = "0.00"
        ortho_used   = calc_used(ortho_total, ortho_rem)
        if not carrier:
            carrier = aetna_data.get("payer", {}).get("name", "AETNA").upper()
            carrier = re.sub(r"\s+DENTAL.*", "", carrier).strip()

    elif is_dd_scraper:
        overview = dd_ins_data.get("tabs", {}).get("overview", {})
        for mx in overview.get("maximums", []):
            if "calendar individual maximum" in mx.get("type", "").lower():
                ind_max_used = fmt_money(mx.get("used", ""))
                break
        for ded in overview.get("deductibles", []):
            if "calendar individual deductible" in ded.get("type", "").lower():
                ind_ded_used = fmt_money(ded.get("used", ""))
                break
        ortho_used = "0.00"
        for mx in overview.get("maximums", []):
            treatment_types = [t.lower() for t in mx.get("treatment_types", [])]
            if any("ortho" in t for t in treatment_types):
                ortho_used = fmt_money(mx.get("used", ""))
                break
        if not carrier:
            carrier = "DELTA DENTAL"

    elif is_dd_wi_pdf:
        fin_by_patient = dd_wi_pdf_data.get("financials_by_patient", {})
        matched_fin = None
        for name, fin in fin_by_patient.items():
            if _name_match_loose(patient_name, name):
                matched_fin = fin
                break
        if matched_fin:
            ind_max_used = fmt_money(matched_fin.get("individual_max_used", ""))
            ind_ded_used = fmt_money(matched_fin.get("individual_deductible_used", ""))
            ortho_used   = fmt_money(matched_fin.get("ortho_max_used", ""))
        else:
            ind_max_used = ind_ded_used = ortho_used = "0.00"
        if not carrier:
            carrier = "DELTA DENTAL"
            
    elif is_ddva:
        accs = ddva_data.get("accumulators", {}).get("accumulators", [])
 
        def _ddva_pick(predicate, tier_pref="In Network PPO"):
            candidates = [a for a in accs if predicate(a)]
            if not candidates:
                return None
            return next((a for a in candidates if a.get("tierName") == tier_pref), candidates[0])
 
        max_acc = _ddva_pick(lambda a: a.get("isMaximum") and
                              "ortho" not in a.get("name", "").lower() and
                              "tmj" not in a.get("name", "").lower() and
                              "family" not in a.get("name", "").lower())
        ded_acc = _ddva_pick(lambda a: not a.get("isMaximum") and
                              "individual" in a.get("name", "").lower() and
                              "deductible" in a.get("name", "").lower())
        ortho_acc = _ddva_pick(lambda a: a.get("isMaximum") and
                                "ortho" in a.get("name", "").lower())
 
        ind_max_used = f"{float(max_acc.get('usedAmount', 0)):.2f}"   if max_acc   else "0.00"
        ind_ded_used = f"{float(ded_acc.get('usedAmount', 0)):.2f}"   if ded_acc   else "0.00"
        ortho_used   = f"{float(ortho_acc.get('usedAmount', 0)):.2f}" if ortho_acc else "0.00"
        if not carrier:
            carrier = "DELTA DENTAL"

    elif is_pdf:
        fin = pdf_data.get("financials", {})
        def _pdf_fin(key: str) -> str:
            block = fin.get(key, {})
            return fmt_money(block.get("used") or block.get("total", ""))
        ind_max_used = _pdf_fin("annual_max")
        ind_ded_used = _pdf_fin("individual_deductible")
        ortho_used   = _pdf_fin("ortho_lifetime")
        if not carrier:
            insurer = pdf_data.get("summary", {}).get("insurer", "")
            carrier = "DELTA DENTAL" if "delta" in insurer else "GUARDIAN" if "guardian" in insurer else ""

    if is_cigna:
        procedures = cigna_data.get("procedures", {}).get("results", [])
        dos_fn     = late_dos_cigna
    elif is_aetna:
        def dos_fn_aetna(_, code: str) -> str:
            for svc in aetna_data.get("service_level_benefits", []):
                if svc.get("procedure_code", "").upper() == code.upper():
                    hist_str = svc.get("history", "")
                    m = re.search(r"Last paid date:\s*(\d{2}/\d{2}/\d{2,4})", hist_str, re.IGNORECASE)
                    if m:
                        raw = m.group(1).strip()
                        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                            try:
                                return datetime.strptime(raw, fmt).strftime("%m/%d/%Y")
                            except ValueError:
                                continue
                    return "NH"
            return "NH"
        procedures = []
        dos_fn = dos_fn_aetna
    elif is_dd_scraper:
        procedures = dd_ins_data.get("tabs", {}).get("benefits_search", [])
        dos_fn = lambda procs, code: late_dos_dd_ins_scraper(procs, code)
    elif is_dd_wi_pdf:
        hist_by_patient = dd_wi_pdf_data.get("history_by_patient", {})
        matched_hist = {}
        for name, hist in hist_by_patient.items():
            if _name_match_loose(patient_name, name):
                matched_hist = hist
                break
        def dos_fn_dd_wi(_, code: str) -> str:
            return matched_hist.get(code.upper(), "NH")
        procedures = []
        dos_fn = dos_fn_dd_wi
    elif is_ddva:
        procedures = ddva_data.get("history", [])
        dos_fn = late_dos_ddva
    elif is_pdf:
        raw_history = pdf_data.get("history", {})
        def dos_fn_pdf(_, code: str) -> str:
            val = raw_history.get(code.upper(), "")
            if not val or val.strip() in ("Date Not Found", "NH", ""):
                return "NH"
            for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    from datetime import datetime as _dt
                    return _dt.strptime(val.strip(), fmt).strftime("%m/%d/%Y")
                except ValueError:
                    continue
            return val.strip()
        procedures = []
        dos_fn = dos_fn_pdf
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