# import fitz  # PyMuPDF
# import re
# import logging
# from datetime import datetime

# logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
# log = logging.getLogger(__name__)


# # ──────────────────────────────────────────────────────────────────
# # HELPERS
# # ──────────────────────────────────────────────────────────────────

# def _money(val: str | None) -> str | None:
#     if not val or val.strip().lower() == "none":
#         return None
#     cleaned = val.replace(",", "").replace("$", "").strip()
#     try:
#         return f"$ {float(cleaned):.2f}"
#     except ValueError:
#         return None


# def _money_str(val: float) -> str:
#     return f"$ {val:.2f}"


# def _parse_dollars(val: str) -> float:
#     try:
#         return float(re.sub(r"[^\d.]", "", str(val)))
#     except Exception:
#         return 0.0


# def _table_value(text: str, label: str) -> str | None:
#     """Extract first dollar-amount from an inline label row (legacy DD layout)."""
#     pattern = rf"{re.escape(label)}\s+(\$[\d,]+\.\d+|None)"
#     m = re.search(pattern, text, re.IGNORECASE)
#     return m.group(1).strip() if m else None


# def _benefit_level(text: str, service_re: str) -> str | None:
#     m = re.search(rf"{service_re}\s+([0-9]+%|None)\s+(?:Yes|No)", text, re.IGNORECASE)
#     if m:
#         v = m.group(1).strip()
#         return None if v.lower() == "none" else v
#     return None


# def _age_range(text: str, keyword_re: str) -> str | None:
#     m = re.search(rf"{keyword_re}[^\n]*?Ages?\s+(\d+)\s*[-–]\s*(\d+)", text, re.IGNORECASE)
#     if m:
#         return f"{m.group(1)}-{m.group(2)}"
#     m = re.search(rf"{keyword_re}[^\n]*?Ages?\s+(\d+)\s+and\s+up", text, re.IGNORECASE)
#     if m:
#         return f"{m.group(1)}-99"
#     return None


# def _normalize_date(raw: str) -> str | None:
#     """Normalize any supported date string to MM/DD/YYYY."""
#     if not raw:
#         return None
#     raw = raw.strip()
#     # Already MM/DD/YYYY
#     if re.match(r"^\d{2}/\d{2}/\d{4}$", raw):
#         return raw
#     # Month DD, YYYY  e.g. "Jan 08, 2026"
#     import datetime
#     for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%y"):
#         try:
#             return datetime.datetime.strptime(raw, fmt).strftime("%m/%d/%Y")
#         except ValueError:
#             continue
#     return raw


# def _normalize_name_for_match(name: str) -> str:
#     """
#     Normalize a name to 'FIRST LAST' uppercase, regardless of whether
#     it came in as 'LAST, FIRST' (Denticon) or 'FIRST LAST' (PDF).
#     """
#     name = (name or "").strip()
#     if "," in name:
#         last, first = name.split(",", 1)
#         name = f"{first.strip()} {last.strip()}"
#     return re.sub(r"\s+", " ", name).strip().upper()


# # ──────────────────────────────────────────────────────────────────
# # SHARED: TEXT EXTRACTION
# # ──────────────────────────────────────────────────────────────────

# # Some PDF fonts substitute ligature glyphs ("fi", "fl", "ff", etc.) for a
# # single Unicode codepoint (U+FB01 "ﬁ", U+FB02 "ﬂ", U+FB00 "ﬀ", ...) instead
# # of the two/three separate letters. PyMuPDF extracts these as that single
# # character, which silently breaks every literal-string regex match containing
# # "fi"/"fl"/"ff" (e.g. "Satisfied" comes out as "Satisﬁed", "Benefit" as
# # "Beneﬁt"). This is a document/font-level quirk that can affect ANY parser,
# # not just one carrier, so it's normalized once here at the shared extraction
# # point rather than patched per-parser.
# _LIGATURE_MAP = {
#     "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
#     "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "ft", "\ufb06": "st",
# }


# def _normalize_ligatures(text: str) -> str:
#     for lig, expansion in _LIGATURE_MAP.items():
#         text = text.replace(lig, expansion)
#     return text


# def _extract_text(pdf_bytes: bytes) -> str:
#     log.info("Extracting text from PDF...")
#     try:
#         doc = fitz.open(stream=pdf_bytes, filetype="pdf")
#         text = "".join(page.get_text() + "\n" for page in doc)
#         doc.close()
#     except Exception as e:
#         log.error(f"Failed to read PDF: {e}")
#         raise ValueError(f"Failed to read PDF: {e}")
#     text = _normalize_ligatures(text)
#     log.info(f"Extracted {len(text)} characters from PDF.")
#     return text


# # ──────────────────────────────────────────────────────────────────
# # FORMAT DETECTION
# # ──────────────────────────────────────────────────────────────────

# def detect_format(text: str) -> str:
#     """
#     Returns one of: 'guardian', 'delta_dental_mo', 'delta_dental_wi',
#     'delta_dental_toolkit', 'delta_dental_legacy'
#     """
#     t = text.lower()

#     if "guardiananytime" in t or "dentalguard" in t or "guardian plan" in t:
#         return "guardian"

#     # dentalofficetoolkit.com portal export (has its own distinct layout —
#     # Routine Procedures/Coverages/Maximums tables, no CDT-code history log)
#     if "dentalofficetoolkit.com" in t:
#         return "delta_dental_toolkit"

#     # "Benefits Detail" portal export (Non-Par/PPO/Premier Maximum bars +
#     # per-procedure "Benefit Class (Sample Code)" rows with inline
#     # "Last Service Date:" fields). IMPORTANT: this format's own footer
#     # links to deltadentalwi.com and uses "Last Service Date:" as a field
#     # label, so it MUST be checked before the WI heuristics below or it
#     # gets misdetected as delta_dental_wi and silently returns empty data.
#     if "benefit class (sample code)" in t or ("non-par maximum" in t and "premier maximum" in t):
#         return "delta_dental_benefits_detail"

#     # DentaQuest's "Member Details" export (providers.dentaquest.com), printed
#     # to PDF — has its own line-oriented layout entirely distinct from Delta
#     # Dental's, so it must be checked before falling through to the generic
#     # "delta dental" text match below (DentaQuest PDFs don't contain that
#     # phrase, but keeping this as its own explicit branch avoids relying on
#     # that coincidence).
#     if "dentaquest" in t:
#         return "dentaquest"

#     if "delta dental" in t or "deltadental" in t:
#         # Wisconsin layout: has the "Eligibility and Accumulations" +
#         # "Preventive History - Last Date of Service" sections
#         if ("deltadentalwi.com" in t or "delta dental of wisconsin" in t
#                 or "preventive history - last date of service" in t
#                 or "last service date:" in t or "coversme" in t):
#             return "delta_dental_wi"
#         # Missouri layout: has "Used $X | Rem $X" table structure
#         if "delta dental of missouri" in t or ("used $" in t and "rem $" in t):
#             return "delta_dental_mo"
#         # Legacy layout: inline "Group Name:" colon labels
#         if re.search(r"Group Name:", text) and re.search(r"Annual Maximums", text):
#             return "delta_dental_legacy"
#         # Fallback for any other DD PDF
#         return "delta_dental_legacy"

#     return "unknown"


# # ──────────────────────────────────────────────────────────────────
# # DISPATCHER
# # ──────────────────────────────────────────────────────────────────

# def _build_registry() -> dict:
#     return {
#         "delta_dental_mo":              _parse_delta_dental_mo,
#         "delta_dental_wi":              _parse_delta_dental_wi,
#         "delta_dental_legacy":          _parse_delta_dental_legacy,
#         "delta_dental_toolkit":         _parse_delta_dental_toolkit,
#         "delta_dental_benefits_detail": _parse_delta_dental_benefits_detail,
#         "guardian":                     _parse_guardian,
#         "dentaquest":                   _parse_dentaquest,
#     }


# async def parse_insurance_pdf(pdf_bytes: bytes) -> dict:
#     text = _extract_text(pdf_bytes)
#     fmt = detect_format(text)
#     log.info(f"Detected insurance format: '{fmt}'")

#     if len(text.strip()) < 100:
#         raise ValueError(
#             "This PDF has no readable text layer (it appears to be scanned or "
#             "image-based), so it can't be parsed. Use a text-based PDF export, "
#             "or capture the data with the browser extension."
#         )
    
#     parser = _build_registry().get(fmt)
#     if parser is None:
#         raise ValueError(
#             "Unrecognized insurance PDF format. "
#             "Supported: Delta Dental (MO / WI / CoversMe / Toolkit / legacy) and Guardian."
#         )

#     result = parser(text)
#     result.setdefault("summary", {})["insurer"] = fmt
#     return result


# # Backwards-compatible wrapper
# async def parse_delta_dental_pdf(pdf_bytes: bytes) -> dict:
#     text = _extract_text(pdf_bytes)
#     fmt = detect_format(text)
#     parser = _build_registry().get(fmt, _parse_delta_dental_legacy)
#     return parser(text)


# # ──────────────────────────────────────────────────────────────────
# # PARSER: DELTA DENTAL — MISSOURI
# # Layout: "Used $X | Rem $X  Total $X" table + "Patient history" section
# # ──────────────────────────────────────────────────────────────────

# def _parse_dd_mo_history(text: str) -> dict:
#     """
#     Extract most-recent date of service per CDT code from the
#     'Patient history' table at the end of DD Missouri PDFs.
#     Table rows: MM/DD/YYYY  <tooth>  <code>  <description>
#     Table is newest-first so first hit per code = most recent.
#     """
#     history = {}
#     m = re.search(r"Patient history", text, re.IGNORECASE)
#     if not m:
#         return history

#     history_text = text[m.start():]
#     for match in re.finditer(
#         r"(\d{2}/\d{2}/\d{4})\s+\S+\s+(?:\S+\s+)?(D\d{4})", history_text
#     ):
#         date_str = match.group(1)
#         code = match.group(2).upper()
#         if code not in history:
#             history[code] = date_str

#     return history


# def _parse_delta_dental_mo(text: str) -> dict:
#     """
#     Parse Delta Dental of Missouri benefit PDF.
#     Financial table format:
#       Used $0 | Rem $2000   Total $2000   (PPO column = first occurrence)
#     """
#     # ── Group info ────────────────────────────────────────────────
#     group_name = ""
#     m = re.search(r"Group name:\s*\n?(.+)", text)
#     if m:
#         # May span multiple lines before "Group number"
#         raw = m.group(1).strip()
#         # Grab up to 3 continuation lines for multi-line names
#         after = text[m.end():]
#         extras = []
#         for ln in after.splitlines():
#             s = ln.strip()
#             if not s or re.match(r"Group number|Program type|Benefit cycle|COB", s, re.I):
#                 break
#             extras.append(s)
#             if len(extras) >= 3:
#                 break
#         group_name = " ".join([raw] + extras).strip()

#     group_number = ""
#     m = re.search(r"Group number:\s*([\w]+)", text)
#     if m:
#         group_number = m.group(1).strip()

#     patient_name = ""
#     m = re.search(r"^([A-Z][A-Z ]+)$", text, re.MULTILINE)
#     if m:
#         patient_name = m.group(1).strip()

#     # ── Annual Max (PPO = first "Used $X | Rem $X" line after "Maximum") ──
#     # PyMuPDF layout: "Used $0 | Rem $2000" — no Total column; total = used + rem
#     annual_max_total = annual_max_used = annual_max_rem = "$ 0.00"
#     m = re.search(r"Used\s+\$([\d,]+\.?\d*)\s*\|\s*Rem\s+\$([\d,]+\.?\d*)", text)
#     if m:
#         used  = _parse_dollars(m.group(1))
#         rem   = _parse_dollars(m.group(2))
#         total = used + rem
#         annual_max_used  = _money_str(used)
#         annual_max_rem   = _money_str(rem)
#         annual_max_total = _money_str(total)

#     # ── Deductible (PPO = first "Met $X | Rem $X" line) ──
#     ded_total = ded_used = ded_rem = "$ 0.00"
#     m = re.search(r"Met\s+\$([\d,]+\.?\d*)\s*\|\s*Rem\s+\$([\d,]+\.?\d*)", text)
#     if m:
#         met   = _parse_dollars(m.group(1))
#         rem   = _parse_dollars(m.group(2))
#         total = met + rem
#         ded_used  = _money_str(met)
#         ded_rem   = _money_str(rem)
#         ded_total = _money_str(total)

#     # ── Benefit levels (from benefit breakdown table) ──────────────
#     prev_pct  = "100%"
#     basic_pct = "80%"
#     major_pct = "50%"
#     m = re.search(r"Preventative\s+(\d+)%", text)
#     if m:
#         prev_pct = f"{m.group(1)}%"
#     m = re.search(r"Basic\s+(\d+)%", text)
#     if m:
#         basic_pct = f"{m.group(1)}%"
#     m = re.search(r"Major\s+(\d+)%", text)
#     if m:
#         major_pct = f"{m.group(1)}%"

#     # ── History ───────────────────────────────────────────────────
#     history = _parse_dd_mo_history(text)

#     result = {
#         "summary": {
#             "group_name":   group_name,
#             "group_number": group_number,
#             "patient_name": patient_name,
#         },
#         "financials": {
#             "annual_max": {
#                 "total":     annual_max_total,
#                 "used":      annual_max_used,
#                 "remaining": annual_max_rem,
#             },
#             "individual_deductible": {
#                 "total":     ded_total,
#                 "used":      ded_used,
#                 "remaining": ded_rem,
#             },
#             "family_deductible": {"total": "$ 0.00"},
#             "ortho_lifetime":    {"total": "$ 0.00"},
#         },
#         "patient":   {"relationship": "Self"},
#         "benefit_coverage": {
#             "procedures": [
#                 {"procedure_code": "D0120", "benefit_level": prev_pct},
#                 {"procedure_code": "D1110", "benefit_level": prev_pct},
#                 {"procedure_code": "D1206", "benefit_level": prev_pct},
#                 {"procedure_code": "D2140", "benefit_level": basic_pct},
#                 {"procedure_code": "D2331", "benefit_level": basic_pct},
#                 {"procedure_code": "D2740", "benefit_level": major_pct},
#                 {"procedure_code": "D4910", "benefit_level": basic_pct},
#                 {"procedure_code": "D4355", "benefit_level": prev_pct},
#                 {"procedure_code": "D8080", "benefit_level": "0%"},
#             ]
#         },
#         "history": history,
#     }

#     if not group_name and not group_number:
#         raise ValueError("Could not extract plan info — DD Missouri PDF layout may have changed.")

#     log.info(f"[MO] group='{group_name}', max={annual_max_total}, used={annual_max_used}")
#     return result


# # ──────────────────────────────────────────────────────────────────
# # PARSER: DELTA DENTAL — WISCONSIN
# # ──────────────────────────────────────────────────────────────────

# def _wi_find_all_patient_names(text: str) -> list[str]:
#     names = []
#     for m in re.finditer(
#         r"^([A-Z][A-Z'\-]*(?:[ \n][A-Z][A-Z'\-]*){1,6})\n\s*Start\s+\d{2}/\d{2}/\d{4}",
#         text, re.MULTILINE
#     ):
#         name = re.sub(r"\s+", " ", m.group(1).strip())
#         if name not in names:
#             names.append(name)
#     return names


# def _parse_dd_wi_financials_all_patients(text: str) -> dict:
#     result = {}
#     names = _wi_find_all_patient_names(text)

#     for name in names:
#         name_flex = r"[ \n]+".join(re.escape(w) for w in name.split(" "))

#         pattern = re.compile(
#             rf"{name_flex}\s*\n\s*Start[^\n]*\n\s*End[^\n]*\n?"
#             r"\s*\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)",
#             re.IGNORECASE
#         )
#         m = pattern.search(text)
#         if not m:
#             continue

#         ded_satisfied, reg_max_used, ortho_annual_used, ortho_lifetime_used, custom_used, oop_satisfied = (
#             _parse_dollars(g) for g in m.groups()
#         )

#         result[name] = {
#             "individual_deductible_used": _money_str(ded_satisfied),
#             "individual_max_used":        _money_str(reg_max_used),
#             "ortho_max_used":             _money_str(ortho_lifetime_used),
#         }

#     return result


# def _parse_dd_wi_history_all_patients(text: str) -> dict:
#     result = {}

#     m = re.search(r"Preventive History.*?Last Date of Service", text, re.IGNORECASE)
#     if not m:
#         return result

#     section = text[m.end():]

#     claims_m = re.search(r"\bCla historyims\b", section)
#     if claims_m:
#         section = section[:claims_m.start()]

#     name_pattern = re.compile(r"^([A-Z][A-Z'\-]*(?:\s[A-Z][A-Z'\-]*)+)$", re.MULTILINE)
#     name_matches = list(name_pattern.finditer(section))

#     date_re = r"(\d{2}/\d{2}/\d{4})"

#     for i, nm in enumerate(name_matches):
#         name = re.sub(r"\s+", " ", nm.group(1).strip())
#         start = nm.end()
#         end = name_matches[i + 1].start() if i + 1 < len(name_matches) else len(section)
#         block = section[start:end]

#         def _find(label_re: str) -> str | None:
#             mm = re.search(rf"{label_re}\s*{date_re}", block, re.IGNORECASE)
#             return mm.group(1) if mm else None

#         exam_date     = _find(r"Exam")
#         cleaning_date = _find(r"Cleaning")
#         fluoride_date = _find(r"Fluoride")
#         bw_date       = _find(r"Bitewing X-?rays")
#         fmx_date      = _find(r"Full Mouth or Panoramic X-?rays")

#         history = {}
#         if exam_date:
#             history["D0120"] = exam_date
#             history["D0150"] = exam_date
#         if cleaning_date:
#             history["D1110"] = cleaning_date
#             history["D4910"] = cleaning_date
#         if fluoride_date:
#             history["D1206"] = fluoride_date
#             history["D1208"] = fluoride_date
#         if bw_date:
#             history["D0274"] = bw_date
#         if fmx_date:
#             history["D0210"] = fmx_date
#             history["D0330"] = fmx_date

#         if name in result and not history:
#             continue
#         result[name] = history

#     return result


# def _parse_delta_dental_wi(text: str) -> dict:
#     subscriber_name = ""
#     m = re.search(r"Subscriber Name:\s*([A-Z][A-Z ]+?)(?:\s{2,}|\n|Group Number)", text, re.IGNORECASE)
#     if m:
#         subscriber_name = re.sub(r"\s+", " ", m.group(1).strip())

#     group_name = ""
#     m = re.search(r"Group Name:\s*(.+)", text, re.IGNORECASE)
#     if m:
#         group_name = m.group(1).strip()

#     group_number = ""
#     m = re.search(r"Group Number:\s*([\w\-]+)", text, re.IGNORECASE)
#     if m:
#         group_number = m.group(1).strip()

#     annual_max_plan_total = "$ 0.00"
#     m = re.search(r"Annual Maximums\s+\$([\d,]+\.?\d*)", text, re.IGNORECASE)
#     if m:
#         annual_max_plan_total = _money_str(_parse_dollars(m.group(1)))

#     financials_by_patient = _parse_dd_wi_financials_all_patients(text)
#     history_by_patient    = _parse_dd_wi_history_all_patients(text)

#     def _wi_pct(service_re: str, default: str) -> str:
#         m = re.search(rf"{service_re}\s*\(\d+\)\s+(\d+)%", text, re.IGNORECASE)
#         return f"{m.group(1)}%" if m else default

#     prev_pct  = _wi_pct(r"Preventive", "100%")
#     basic_pct = _wi_pct(r"Basic Restor", "80%")
#     major_pct = _wi_pct(r"Major Restor", "50%")
#     perio_pct = _wi_pct(r"Perio Maint", basic_pct)

#     result = {
#         "summary": {
#             "group_name":      group_name,
#             "group_number":    group_number,
#             "subscriber_name": subscriber_name,
#         },
#         "financials": {
#             "annual_max": {"total": annual_max_plan_total},
#         },
#         "financials_by_patient": financials_by_patient,
#         "history_by_patient":    history_by_patient,
#         "patient":   {"relationship": "Self"},
#         "benefit_coverage": {
#             "procedures": [
#                 {"procedure_code": "D0120", "benefit_level": prev_pct},
#                 {"procedure_code": "D1110", "benefit_level": prev_pct},
#                 {"procedure_code": "D1206", "benefit_level": "N/A"},
#                 {"procedure_code": "D2140", "benefit_level": basic_pct},
#                 {"procedure_code": "D2331", "benefit_level": basic_pct},
#                 {"procedure_code": "D2740", "benefit_level": major_pct},
#                 {"procedure_code": "D4910", "benefit_level": perio_pct},
#                 {"procedure_code": "D4355", "benefit_level": perio_pct},
#                 {"procedure_code": "D8080", "benefit_level": "0%"},
#             ]
#         },
#         "history": {},
#     }

#     if not group_name and not group_number and not financials_by_patient:
#         raise ValueError("Could not extract plan info — DD Wisconsin layout may have changed.")

#     log.info(f"[WI] subscriber='{subscriber_name}', patients_found={list(financials_by_patient.keys())}, "
#              f"group='{group_name}'")
#     return result


# # ──────────────────────────────────────────────────────────────────
# # PARSER: DELTA DENTAL — TOOLKIT (dentalofficetoolkit.com portal)
# # ──────────────────────────────────────────────────────────────────

# _TOOLKIT_PROC_LABELS = [
#     "Exam", "Adult Cleaning", "Child Cleaning", "Perio Maintenance Cleaning",
#     "Bitewings", "Full Mouth X-rays", "Fluoride", "Occlusal Guard",
# ]

# _TOOLKIT_PROC_TO_CODES = {
#     "Exam":                       ["D0120", "D0150"],
#     "Adult Cleaning":             ["D1110"],
#     "Child Cleaning":             ["D1120"],
#     "Perio Maintenance Cleaning": ["D4910"],
#     "Bitewings":                  ["D0274"],
#     "Full Mouth X-rays":          ["D0210", "D0330"],
#     "Fluoride":                   ["D1206", "D1208"],
#     "Occlusal Guard":             ["D9944"],
# }

# _TOOLKIT_CATEGORIES = [
#     "Diagnostic", "Preventive", "Bitewing Radiographs", "All Other Radiographs",
#     "Brush Biopsy", "Sealants", "Minor Restorative", "Major Restorative",
#     "Endodontics", "Periodontics", "Relines and Repairs", "Simple Extractions",
#     "Other Oral Surgery", "TMD", "Other Basic Services", "Prosthodontics",
#     "Implants", "Orthodontic Services",
# ]


# def _toolkit_multiline_field(text: str, label: str, next_label_alt: str) -> str:
#     m = re.search(rf"{label}:\s*(.+?)\n(?:{next_label_alt})", text, re.DOTALL)
#     return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# def _toolkit_max_block(text: str, type_label: str, category_label: str) -> dict:
#     r"""
#     Pull the first Amount/Used/Remaining triplet following a Maximums-table
#     row's Type + Category cells (e.g. Type="Maximum", Category="General").
#     """
#     m = re.search(
#         rf"{re.escape(type_label)}\s+{re.escape(category_label)}.*?Amount:\s*\$([\d,]+\.?\d*)\s*\n?"
#         r"Used:\s*\$([\d,]+\.?\d*)\s*\n?Remaining:\s*\$([\d,]+\.?\d*)",
#         text, re.DOTALL,
#     )
#     if not m:
#         return None
#     return {
#         "total":     _money_str(_parse_dollars(m.group(1))),
#         "used":      _money_str(_parse_dollars(m.group(2))),
#         "remaining": _money_str(_parse_dollars(m.group(3))),
#     }


# def _parse_delta_dental_toolkit(text: str) -> dict:
#     """Parse a Delta Dental 'dentalofficetoolkit.com' member-benefits export."""

#     patient_name = ""
#     m = re.search(r"Patient Name:\s*(.+)", text)
#     if m:
#         patient_name = m.group(1).strip()

#     relationship = "Self"
#     m = re.search(r"Relationship:\s*(\w+)", text)
#     if m:
#         relationship = m.group(1).strip()

#     group_number = ""
#     m = re.search(r"Group Number:\s*([\w\-]+)", text)
#     if m:
#         group_number = m.group(1).strip()

#     sub_group_number = ""
#     m = re.search(r"Sub Group Number:\s*([\w\-]+)", text)
#     if m:
#         sub_group_number = m.group(1).strip()

#     group_name = _toolkit_multiline_field(
#         text, "Group Name", "Sub Group Number|Sub Group Name"
#     )
#     sub_group_name = _toolkit_multiline_field(
#         text, "Sub Group Name", "Patient Name|Age Limitations"
#     )

#     history = {}
#     proc_section_m = re.search(r"Service Dates\n(.*?)\nCoverages", text, re.DOTALL)
#     if proc_section_m:
#         section = proc_section_m.group(1)
#         date_pat = r"\d{2}/\d{2}/\d{4}"
#         for label in _TOOLKIT_PROC_LABELS:
#             m = re.search(
#                 rf"{re.escape(label)}\s*(?:Yes|No)\s*((?:{date_pat}\s*,?\s*)*)",
#                 section
#             )
#             if not m:
#                 continue
#             dates = re.findall(date_pat, m.group(1))
#             if not dates:
#                 continue
#             joined = ", ".join(dates)
#             for code in _TOOLKIT_PROC_TO_CODES.get(label, []):
#                 history[code] = joined

#     coverages = {}
#     for cat in _TOOLKIT_CATEGORIES:
#         m = re.search(rf"{re.escape(cat)}\n(\d+|Not Covered)\n", text)
#         if m:
#             coverages[cat] = m.group(1)

#     def _pct(cat: str, default: str) -> str:
#         val = coverages.get(cat)
#         if val is None:
#             return default
#         return "0%" if val == "Not Covered" else f"{val}%"

#     annual_max     = _toolkit_max_block(text, "Maximum", "General")     or {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
#     ortho_lifetime = _toolkit_max_block(text, "Maximum", "Orthodontic") or {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
#     implant_max    = _toolkit_max_block(text, "Maximum", "Implants")    or {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
#     ind_ded        = _toolkit_max_block(text, "Deductible", "General")  or {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}

#     result = {
#         "summary": {
#             "group_name":       group_name,
#             "group_number":     group_number,
#             "sub_group_name":   sub_group_name,
#             "sub_group_number": sub_group_number,
#             "patient_name":     patient_name,
#         },
#         "financials": {
#             "annual_max":            annual_max,
#             "individual_deductible": ind_ded,
#             "family_deductible":     {"total": "$ 0.00"},
#             "ortho_lifetime":        ortho_lifetime,
#             "implant_lifetime":      implant_max,
#         },
#         "patient": {"relationship": relationship},
#         "benefit_coverage": {
#             "procedures": [
#                 {"procedure_code": "D0120", "benefit_level": _pct("Diagnostic", "100%")},
#                 {"procedure_code": "D0150", "benefit_level": _pct("Diagnostic", "100%")},
#                 {"procedure_code": "D1110", "benefit_level": _pct("Preventive", "100%")},
#                 {"procedure_code": "D1120", "benefit_level": _pct("Preventive", "100%")},
#                 {"procedure_code": "D1206", "benefit_level": _pct("Preventive", "100%")},
#                 {"procedure_code": "D0274", "benefit_level": _pct("Bitewing Radiographs", "100%")},
#                 {"procedure_code": "D0210", "benefit_level": _pct("All Other Radiographs", "100%")},
#                 {"procedure_code": "D1351", "benefit_level": _pct("Sealants", "0%")},
#                 {"procedure_code": "D2140", "benefit_level": _pct("Minor Restorative", "80%")},
#                 {"procedure_code": "D2331", "benefit_level": _pct("Minor Restorative", "80%")},
#                 {"procedure_code": "D2740", "benefit_level": _pct("Major Restorative", "50%")},
#                 {"procedure_code": "D4910", "benefit_level": _pct("Periodontics", "100%")},
#                 {"procedure_code": "D4355", "benefit_level": _pct("Periodontics", "100%")},
#                 {"procedure_code": "D6010", "benefit_level": _pct("Implants", "100%")},
#                 {"procedure_code": "D5110", "benefit_level": _pct("Prosthodontics", "50%")},
#                 {"procedure_code": "D8080", "benefit_level": _pct("Orthodontic Services", "50%")},
#             ]
#         },
#         "history": history,
#     }

#     if not group_number and not patient_name:
#         raise ValueError("Could not extract plan info — DD Toolkit PDF layout may have changed.")

#     log.info(
#         f"[Toolkit] patient='{patient_name}', relationship='{relationship}', "
#         f"group='{group_number}', annual_max={annual_max['total']} "
#         f"(used={annual_max['used']}), history_codes={list(history.keys())}"
#     )
#     return result


# # ──────────────────────────────────────────────────────────────────
# # PARSER: DELTA DENTAL — BENEFITS DETAIL (third-party portal export)
# # ──────────────────────────────────────────────────────────────────

# _BENEFITS_DETAIL_PROC_ROW = re.compile(
#     r"([A-Za-z][A-Za-z0-9 /&\-]+?)\s*\((D\d{4}(?:\s+or\s+D\d{4})?)\)\n"
#     r"(?:(?!\(D\d{4}(?:\s+or\s+D\d{4})?\)).*?\n)*?"
#     r"(\d+%|N/A|\$[\d,]+\.\d{2})\n"
#     r"(?:Remaining balance\s*\n\s*up to dentist'?s\s*\n\s*approved amount\s*\n)?"
#     r"(Yes|No|N/A)\n(N/A|Satisfied)\n"
# )

# _BENEFITS_DETAIL_NAME_TO_HISTORY_CODES = [
#     (r"bitewing",                          ["D0274"]),
#     (r"full mouth or panoramic",           ["D0210", "D0330"]),
#     (r"comprehensive and periodic exam",   ["D0120", "D0150"]),
#     (r"prophylaxis",                       ["D1110"]),
#     (r"perio maintenance",                 ["D4910"]),
#     (r"full mouth debridement",            ["D4355"]),
#     (r"fluoride",                          ["D1206", "D1208"]),
# ]


# def _benefits_detail_tier_max(text: str, tier: str) -> dict:
#     m = re.search(
#         rf"{tier} Maximum\n\d+% used - \d+% max\n\$([\d,]+\.\d+) used - \$([\d,]+\.\d+) max",
#         text,
#     )
#     if not m:
#         return {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
#     used  = _parse_dollars(m.group(1))
#     total = _parse_dollars(m.group(2))
#     return {
#         "total":     _money_str(total),
#         "used":      _money_str(used),
#         "remaining": _money_str(total - used),
#     }


# def _benefits_detail_tier_deductible(text: str, label: str, tier: str) -> dict:
#     m = re.search(
#         rf"{label} \({tier} Deductible\):\n\$([\d,]+\.\d+) per year, \$([\d,]+\.\d+) remains to be paid",
#         text,
#     )
#     if not m:
#         return {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
#     total     = _parse_dollars(m.group(1))
#     remaining = _parse_dollars(m.group(2))
#     return {
#         "total":     _money_str(total),
#         "used":      _money_str(total - remaining),
#         "remaining": _money_str(remaining),
#     }


# def _parse_delta_dental_benefits_detail(text: str) -> dict:
#     """Parse a Delta Dental 'Benefits Detail' third-party portal export."""

#     subscriber_name = ""
#     m = re.search(r"Subscriber name:\n(.+)", text)
#     if m:
#         subscriber_name = m.group(1).strip()

#     patient_name = subscriber_name
#     m = re.search(r"Benefits for (.+)", text)
#     if m:
#         patient_name = m.group(1).strip()

#     group_number = ""
#     m = re.search(r"Group #:\n([\w]+)", text)
#     if m:
#         group_number = m.group(1).strip()

#     group_name = ""
#     m = re.search(r"Group name:\n(.+)", text)
#     if m:
#         group_name = m.group(1).strip()

#     annual_max = _benefits_detail_tier_max(text, "PPO")
#     ind_ded    = _benefits_detail_tier_deductible(text, "Individual deductible", "PPO")
#     fam_ded    = _benefits_detail_tier_deductible(text, "Family deductible", "PPO")

#     ortho_lifetime = {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}

#     matches = list(_BENEFITS_DETAIL_PROC_ROW.finditer(text))
#     procedures = []
#     history = {}
#     code_shares = {}

#     for i, m in enumerate(matches):
#         name = m.group(1).strip()
#         codes_raw = re.sub(r"\s+", " ", m.group(2)).replace(" or ", ",")
#         codes = [c.strip() for c in codes_raw.split(",")]
#         pct = m.group(3)
#         benefit_level = "0%" if pct == "N/A" else pct

#         if re.search(r"bitewing", name.lower()):
#             codes = ["D0274"]

#         for code in codes:
#             procedures.append({"procedure_code": code, "benefit_level": benefit_level})

#         start = m.end()
#         end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
#         block = text[start:end]

#         name_lower = name.lower()
#         output_codes = codes
#         for pat, hist_codes in _BENEFITS_DETAIL_NAME_TO_HISTORY_CODES:
#             if re.search(pat, name_lower):
#                 output_codes = hist_codes
#                 break

#         shares_m = re.search(
#             r"Similar procedures performed impact frequency\s*\n"
#             r"limitations\s*-\s*([^\n]+)",
#             block
#         )
#         if shares_m:
#             shared_codes = re.findall(r"D\d{4}", shares_m.group(1))
#             if shared_codes:
#                 for oc in output_codes:
#                     code_shares.setdefault(oc, set()).update(shared_codes)

#         lsd_m = re.search(r"Last Service Date:\s*(\d{2}/\d{2}/\d{4})", block)
#         if not lsd_m:
#             continue
#         lsd = lsd_m.group(1)

#         for oc in output_codes:
#             history[oc] = lsd

#     def _parse_lsd(d):
#         return datetime.strptime(d, "%m/%d/%Y")

#     visited = set()
#     for code in list(history.keys()):
#         if code in visited:
#             continue
#         group = {code}
#         frontier = [code]
#         while frontier:
#             c = frontier.pop()
#             for peer in code_shares.get(c, ()):
#                 if peer in history and peer not in group:
#                     group.add(peer)
#                     frontier.append(peer)
#         if len(group) > 1:
#             dates = {history[c] for c in group}
#             merged = ", ".join(sorted(dates, key=_parse_lsd, reverse=True))
#             for c in group:
#                 history[c] = merged
#         visited |= group

#     result = {
#         "summary": {
#             "group_name":      group_name,
#             "group_number":    group_number,
#             "subscriber_name": subscriber_name,
#             "patient_name":    patient_name,
#         },
#         "financials": {
#             "annual_max":            annual_max,
#             "individual_deductible": ind_ded,
#             "family_deductible":     fam_ded,
#             "ortho_lifetime":        ortho_lifetime,
#         },
#         "patient": {"relationship": "Self"},
#         "benefit_coverage": {"procedures": procedures},
#         "history": history,
#     }

#     if not group_number and not subscriber_name:
#         raise ValueError("Could not extract plan info — DD Benefits Detail PDF layout may have changed.")

#     log.info(
#         f"[BenefitsDetail] subscriber='{subscriber_name}', group='{group_number}', "
#         f"annual_max={annual_max['total']} (used={annual_max['used']}), "
#         f"history_codes={list(history.keys())}"
#     )
#     return result


# # ──────────────────────────────────────────────────────────────────
# # PARSER: DELTA DENTAL — LEGACY (original inline-label layout)
# # ──────────────────────────────────────────────────────────────────

# def _parse_delta_dental_legacy(text: str) -> dict:
#     group_name, group_number = "", ""

#     m = re.search(r"Group Name:\s*(.+)", text)
#     if m:
#         group_name = m.group(1).strip()

#     m = re.search(r"Group Number:\s*([\w\-]+)", text)
#     if m:
#         raw = m.group(1).strip()
#         parts = raw.split("-")
#         while len(parts) > 2 and parts[-1] == "00000":
#             parts.pop()
#         group_number = "-".join(parts)

#     annual_max     = _money(_table_value(text, "Annual Maximums"))
#     annual_ded     = _money(_table_value(text, "Annual Deductibles"))
#     fam_ded        = _money(_table_value(text, "Annual Family Deductibles"))
#     ortho_lifetime = _money(_table_value(text, "Ortho Lifetime Maximums"))
#     ortho_ded      = _money(_table_value(text, "Ortho Annual Deductibles"))
#     ind_ded        = annual_ded or ortho_ded or "$ 0.00"

#     diag_pct    = _benefit_level(text, r"Diagnostic\(\d+\)")
#     prev_pct    = _benefit_level(text, r"Preventive\(\d+\)")
#     sealant_pct = _benefit_level(text, r"Sealants\(\d+\)")
#     basic_pct   = _benefit_level(text, r"Basic\s+Restor\(\d+\)")
#     major_pct   = _benefit_level(text, r"Major\s+Restor\(\d+\)")
#     ortho_pct   = _benefit_level(text, r"Orthodontics\(\d+\)")

#     d0120_pct = diag_pct or prev_pct or "100%"
#     d1206_pct = prev_pct or "100%"
#     d1351_pct = sealant_pct or "100%"
#     d1510_pct = prev_pct or "100%"
#     d2331_pct = basic_pct or "80%"
#     d2140_pct = basic_pct or "80%"
#     d2740_pct = major_pct or "50%"
#     d8080_pct = ortho_pct or "50%"

#     sealant_age  = _age_range(text, "Sealants")
#     fluoride_age = _age_range(text, r"Fluoride\s+Varnish") or _age_range(text, "Fluoride")

#     ortho_age = None
#     m = re.search(r"Dependent Orthodontic Age:\s*(\d+)", text)
#     if m:
#         ortho_age = f"0-{m.group(1)}"
#     if not ortho_age:
#         m = re.search(r"Child Coverage Age:\s*(\d+)", text)
#         if m:
#             ortho_age = f"0-{m.group(1)}"

#     space_maint_age = None
#     m = re.search(r"Child Coverage Age:\s*(\d+)", text)
#     if m:
#         space_maint_age = f"0-{m.group(1)}"

#     result = {
#         "summary": {"group_name": group_name, "group_number": group_number},
#         "financials": {
#             "individual_deductible": {"total": ind_ded},
#             "family_deductible":     {"total": fam_ded or "$ 0.00"},
#             "annual_max":            {"total": annual_max or "$ 0.00"},
#             "ortho_lifetime":        {"total": ortho_lifetime or "$ 0.00"},
#         },
#         "patient": {"relationship": "Self"},
#         "benefit_coverage": {
#             "procedures": [
#                 {"procedure_code": "D0120", "benefit_level": d0120_pct, "age_limit": "0-99"},
#                 {"procedure_code": "D1206", "benefit_level": d1206_pct, "age_limit": fluoride_age or "0-18"},
#                 {"procedure_code": "D1351", "benefit_level": d1351_pct, "age_limit": sealant_age or "0-18"},
#                 {"procedure_code": "D1510", "benefit_level": d1510_pct, "age_limit": space_maint_age or "0-14"},
#                 {"procedure_code": "D2331", "benefit_level": d2331_pct},
#                 {"procedure_code": "D2140", "benefit_level": d2140_pct},
#                 {"procedure_code": "D2740", "benefit_level": d2740_pct},
#                 {"procedure_code": "D8080", "benefit_level": d8080_pct, "age_limit": ortho_age or "0-26"},
#             ]
#         },
#         "history": {},
#     }

#     if not group_name and not group_number:
#         raise ValueError("Could not extract plan info — PDF format may not be supported.")

#     log.info(f"[Legacy] group='{group_name}', number='{group_number}', annual_max={annual_max}")
#     return result


# # ──────────────────────────────────────────────────────────────────
# # PARSER: GUARDIAN
# # ──────────────────────────────────────────────────────────────────

# def _lines_between(lines: list[str], start_label: str, end_label: str) -> str:
#     capturing, out = False, []
#     for ln in lines:
#         s = ln.strip()
#         if not capturing:
#             if s.lower() == start_label.lower():
#                 capturing = True
#             continue
#         if s.lower() == end_label.lower():
#             break
#         if s:
#             out.append(s)
#     return " ".join(out).strip()


# def _line_after(lines: list[str], label: str) -> str | None:
#     for i, ln in enumerate(lines):
#         if ln.strip().lower() == label.lower():
#             for nxt in lines[i + 1:]:
#                 if nxt.strip():
#                     return nxt.strip()
#     return None


# def _parse_guardian_history(text: str) -> dict:
#     lines = text.splitlines()
#     reassembled = []
#     i = 0
#     while i < len(lines):
#         ln = lines[i].rstrip()
#         if re.search(r"\d{2}/\d{2}/\d{3}$", ln) and i + 1 < len(lines):
#             nxt = lines[i + 1].strip()
#             if re.match(r"^\d", nxt):
#                 reassembled.append(ln + nxt[0])
#                 if len(nxt) > 1:
#                     reassembled.append(nxt[1:])
#                 i += 2
#                 continue
#         reassembled.append(ln)
#         i += 1
#     full_text = "\n".join(reassembled)
#     flat = re.sub(r"\s+", " ", full_text)

#     history = {}

#     service_map = [
#         (r"Cleanings|Prophylaxis",     ["D1110"]),
#         (r"Exams|Oral\s+Evaluations",  ["D0120", "D0150"]),
#         (r"Fluoride",                  ["D1206"]),
#         (r"Periodontal\s+Maintenance", ["D4910"]),
#         (r"Periodontics",              ["D4355"]),
#     ]
#     for pattern, codes in service_map:
#         m = re.search(pattern, flat, re.IGNORECASE)
#         if not m:
#             continue
#         snippet = flat[m.start(): m.start() + 500]
#         date_m = re.search(r"\d{2}/\d{2}/\d{4}", snippet)
#         if date_m:
#             for code in codes:
#                 if code not in history:
#                     history[code] = date_m.group(0)

#     xray_m = re.search(r"X-Rays", flat, re.IGNORECASE)
#     if xray_m:
#         xray_snippet = flat[xray_m.start(): xray_m.start() + 1500]
#         bw_m = re.search(r"Bitewings?[^\d]{0,10}(\d{2}/\d{2}/\d{4})", xray_snippet, re.IGNORECASE)
#         fm_m = re.search(r"FullMouth[^\d]{0,30}(\d{2}/\d{2}/\d{4})", xray_snippet, re.IGNORECASE)
#         if bw_m:
#             history["D0274"] = bw_m.group(1)
#         if fm_m:
#             history["D0210"] = fm_m.group(1)

#     return history


# def _parse_guardian(text: str) -> dict:
#     lines   = text.splitlines()
#     flat    = re.sub(r"\s+", " ", text)
#     nospace = re.sub(r"\s+", "", text)

#     group_name   = _lines_between(lines, "Group name", "Group number")
#     group_number = ""
#     raw_num = _line_after(lines, "Group number")
#     if raw_num:
#         m = re.match(r"[\w\-]+", raw_num)
#         group_number = m.group(0) if m else raw_num.strip()

#     plan_name = ""
#     m = re.search(r"plan is ([A-Z0-9][A-Z0-9 /&\-]+?)\.", flat)
#     if m:
#         plan_name = m.group(1).strip()

#     annual_max_total = annual_max_used = annual_max_rem = "$ 0.00"
#     m = re.search(r"(?:DG\s*Preferred|In\s*network)\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})", flat)
#     if m:
#         total = _parse_dollars(m.group(1))
#         rem   = _parse_dollars(m.group(2))
#         used  = max(0.0, total - rem)
#         annual_max_total = _money_str(total)
#         annual_max_rem   = _money_str(rem)
#         annual_max_used  = _money_str(used)

#     ind_ded_total = ind_ded_used = ind_ded_rem = "$ 0.00"
#     m = re.search(
#         r"(?:DG\s*Preferred|In\s*network)\s+\$([\d,]+\.\d{2})\s+(?:Yes|No)\s+\$([\d,]+\.\d{2})",
#         flat, re.IGNORECASE
#     )
#     if m:
#         ded_total = _parse_dollars(m.group(1))
#         ded_rem   = _parse_dollars(m.group(2))
#         ind_ded_total = _money_str(ded_total)
#         ind_ded_rem   = _money_str(ded_rem)
#         ind_ded_used  = _money_str(max(0.0, ded_total - ded_rem))

#     ortho_total = ortho_used = "$ 0.00"
#     ortho_section_m = re.search(r"Orthodon\s*tic\b", flat, re.IGNORECASE)
#     if ortho_section_m:
#         m = re.search(
#             r"(?:DG\s*Preferred|In\s*network)\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})",
#             flat[ortho_section_m.end(): ortho_section_m.end() + 300],
#             re.IGNORECASE
#         )
#         if m:
#             lifetime_total = _parse_dollars(m.group(2))
#             lifetime_rem   = _parse_dollars(m.group(3))
#             ortho_total = _money_str(lifetime_total)
#             ortho_used  = _money_str(max(0.0, lifetime_total - lifetime_rem))

#     def _cat_pct(category: str) -> str | None:
#         mm = re.search(category + category + r"(\d+)%", nospace)
#         return mm.group(1) if mm else None

#     prev_pct  = _cat_pct("Preventive")
#     basic_pct = _cat_pct("Basic")
#     major_pct = _cat_pct("Major")
#     ortho_pct = _cat_pct("Ortho")
#     ortho_not_covered = bool(re.search(r"OrthodonticsNotCovered", nospace))

#     def _pct(val: str | None, default: str) -> str:
#         return f"{val}%" if val else default

#     def _age(pattern: str) -> str | None:
#         mm = re.search(pattern, flat, re.IGNORECASE)
#         return mm.group(1) if mm else None

#     fluoride_age = _age(r"Fluoride \(D1206[^)]*\)[^.]*?up to age (\d+)")
#     sealant_age  = _age(r"Sealant \(D1351\)[^.]*?up to age (\d+)")
#     space_age    = _age(r"Space maintainers[^.]*?under the age of (\d+)")

#     history = _parse_guardian_history(text)

#     procedures = [
#         {"procedure_code": "D0120", "benefit_level": _pct(prev_pct, "100%"), "age_limit": "0-99"},
#         {"procedure_code": "D1206", "benefit_level": _pct(prev_pct, "100%"),
#          "age_limit": f"0-{fluoride_age}" if fluoride_age else "0-14"},
#         {"procedure_code": "D1351", "benefit_level": _pct(prev_pct, "100%"),
#          "age_limit": f"0-{sealant_age}" if sealant_age else "0-16"},
#         {"procedure_code": "D1510", "benefit_level": _pct(prev_pct, "100%"),
#          "age_limit": f"0-{space_age}" if space_age else "0-16"},
#         {"procedure_code": "D2331", "benefit_level": _pct(basic_pct, "80%")},
#         {"procedure_code": "D2140", "benefit_level": _pct(basic_pct, "80%")},
#         {"procedure_code": "D2740", "benefit_level": _pct(major_pct, "50%")},
#     ]
#     if ortho_not_covered:
#         procedures.append({"procedure_code": "D8080", "benefit_level": "0%",
#                            "age_limit": "0-26", "frequency_limit": "Not Covered"})
#     else:
#         procedures.append({"procedure_code": "D8080",
#                            "benefit_level": _pct(ortho_pct, "50%"), "age_limit": "0-26"})

#     result = {
#         "summary": {
#             "group_name":   group_name,
#             "group_number": group_number,
#             "plan_name":    plan_name,
#         },
#         "financials": {
#             "individual_deductible": {
#                 "total":     ind_ded_total,
#                 "used":      ind_ded_used,
#                 "remaining": ind_ded_rem,
#             },
#             "family_deductible": {"total": "$ 0.00"},
#             "annual_max": {
#                 "total":     annual_max_total,
#                 "used":      annual_max_used,
#                 "remaining": annual_max_rem,
#             },
#             "ortho_lifetime": {
#                 "total": ortho_total,
#                 "used":  ortho_used,
#             },
#         },
#         "patient":   {"relationship": "Self"},
#         "benefit_coverage": {"procedures": procedures},
#         "history":   history,
#     }

#     if not group_name and not group_number:
#         raise ValueError("Could not extract plan info — Guardian PDF layout may have changed.")

#     log.info(f"[Guardian] group='{group_name}', number='{group_number}', "
#              f"annual_max={annual_max_total}, used={annual_max_used}, prev={prev_pct}, basic={basic_pct}")
#     return result


# # ──────────────────────────────────────────────────────────────────
# # PARSER: DENTAQUEST  (providers.dentaquest.com "Member Details" export)
# # ──────────────────────────────────────────────────────────────────
# #
# # Confirmed against a real "Member Details" PDF export (DANIELLA PLASENCIA /
# # group 972599). The page has three sections we actually use:
# #
# #   • "Main information" / "Member's information" — labels sit on their own
# #     line, value on the next non-empty line, e.g.:
# #       Plan/Group number:
# #       972599
# #
# #   • "Benefits at a glance" gives plan THRESHOLDS only (no usage):
# #       Deductible:  →  $50.0 Individual / $150.0 Family
# #       Maximum:     →  $2000.0 Individual annual
# #       Orthodontia max.:  →  $1000.0 Individual lifetime
# #
# #   • "Deductibles & maximums" (further down the page) gives the REAL applied
# #     usage per category, as "$USED out of $TOTAL", e.g.:
# #       Individual annual maximum (All Networks)
# #       <long list of covered service categories>
# #       $250.00 out of $2,000.00   $1,750.00 before ... is met
# #     This is the section that actually answers "how much has this patient
# #     used" — "Benefits at a glance" alone cannot.
# #
# #   • "Member History" is a flat claims-style log:
# #       01/27/2026
# #       D1208
# #       topical application of fluoride – excluding varnish
# #       -- / -- / -- / --
# #       Office
# #     (repeating for every billed line item). This is what feeds the 8
# #     tracked procedure-history fields — NOT a per-code coverage-percentage
# #     lookup table (that's an interactive search tool on the live page with
# #     no static data in the exported PDF).

# def _dq_label(lines: list[str], label: str) -> str | None:
#     """
#     Value for a 'Label:' field — inline ('Label: value') or on the next
#     non-empty line. Case-insensitive; the first match wins.
#     """
#     want = label.lower().rstrip(":").strip() + ":"
#     for i, ln in enumerate(lines):
#         s = ln.strip()
#         m = re.match(rf"{re.escape(label)}\s*:\s*(.+)$", s, re.IGNORECASE)
#         if m and m.group(1).strip():
#             return m.group(1).strip()
#         if s.lower() == want:
#             for nxt in lines[i + 1:]:
#                 if nxt.strip():
#                     return nxt.strip()
#     return None


# def _dq_used_out_of(text: str, label_pattern: str):
#     r"""
#     Pull "$USED out of $TOTAL" for a "Deductibles & maximums" category —
#     e.g. label_pattern=r"Individual deductible \(All Networks\)" matches
#     the block naming that category (skipping over its long list of covered
#     service types via DOTALL) and returns (used, total) as plain numeric
#     strings, or (None, None) if that category isn't present on this plan.
#     """
#     m = re.search(
#         rf"{label_pattern}.*?\$([\d,]+\.\d{{2}}) out of \$([\d,]+\.\d{{2}})",
#         text, re.DOTALL
#     )
#     if not m:
#         return None, None
#     return m.group(1).replace(",", ""), m.group(2).replace(",", "")


# def _dq_claims_history(text: str) -> dict:
#     """
#     Parse the "Member History" claims table into {CDT_CODE: [dates...]}.
#     Each row is:
#         MM/DD/YYYY
#         Dxxxx
#         <description text>
#         <tooth/arch/quad/surface, e.g. "-- / -- / -- / --" or "15 / UA / UL / O">
#         Office
#     Stops before the trailing small plan-status table at the very end of the
#     page (its "023542103 ... Active 01/01/2025 -" line would otherwise be
#     misread as more claim rows).
#     """
#     history: dict[str, list[str]] = {}

#     m = re.search(r"Billed submitted\s*\nStatus\s*\n", text)
#     if not m:
#         return history
#     section = text[m.end():]

#     end_m = re.search(r"\n\d{6,}\s*\n[A-Za-z].*Network", section)
#     if end_m:
#         section = section[:end_m.start()]

#     row_re = re.compile(
#         r"(\d{2}/\d{2}/\d{4})\s*\n"
#         r"(D\d{4})\s*\n"
#         r"(.*?)\n"
#         r"(?:[A-Za-z0-9\-]+(?:\s*/\s*[A-Za-z0-9\-]+){3}\s*\n)?"
#         r"Office\s*\n?"
#     )
#     for row_m in row_re.finditer(section):
#         date, code = row_m.group(1), row_m.group(2).upper()
#         history.setdefault(code, []).append(date)

#     return history


# def _parse_dentaquest(text: str) -> dict:
#     """Parse a DentaQuest (Sun Life) 'Member Details' PDF into the common schema."""
#     lines = text.splitlines()

#     # ── 1. Patient ─────────────────────────────────────────────────
#     name = None
#     m = re.search(r"Member information for\s+([A-Z][A-Za-z .'\-]+)", text)
#     if m:
#         name = m.group(1).strip()
#     name = name or _dq_label(lines, "Name")

#     level = _dq_label(lines, "Level of coverage") or "N/A"
#     relationship = (level if level != "N/A"
#                     and not re.search(r"employee only|self|subscriber|member", level, re.I)
#                     else "Self")

#     patient = {
#         "name":              name or "N/A",
#         "dob":               _dq_label(lines, "Date of birth") or "N/A",
#         "age":               _dq_label(lines, "Age") or "N/A",
#         "member_id":         _dq_label(lines, "ID number") or "N/A",
#         "relationship":      relationship,
#         "level_of_coverage": level,
#     }

#     # ── 2. Plan details ────────────────────────────────────────────
#     plan_name    = _dq_label(lines, "Plan") or "N/A"
#     group_number = _dq_label(lines, "Plan/Group number") or _dq_label(lines, "Group number") or "N/A"
#     if group_number != "N/A":
#         gm = re.match(r"[\w\-]+", group_number)
#         group_number = gm.group(0) if gm else group_number
#     network = _dq_label(lines, "Network") or "N/A"

#     plan_details = {
#         "plan_name":         plan_name,
#         "group_number":      group_number,
#         "employer_group":    plan_name,
#         "network":           network,
#         "level_of_coverage": level,
#     }

#     # ── 3. Financials ───────────────────────────────────────────────
#     # Totals come from "Benefits at a glance"; actual USED amounts come from
#     # the separate "Deductibles & maximums" section (see module docstring —
#     # "Benefits at a glance" alone never carries usage).
#     ind_ded_total = fam_ded_total = annual_max_total = ortho_total = None
#     ded_line = _dq_label(lines, "Deductible")
#     if ded_line:
#         dms = re.findall(r"\$[\d,]+\.?\d*", ded_line)
#         if dms:
#             ind_ded_total = _money(dms[0])
#         if len(dms) > 1:
#             fam_ded_total = _money(dms[1])
#     max_line = _dq_label(lines, "Maximum")
#     if max_line:
#         mm = re.search(r"\$[\d,]+\.?\d*", max_line)
#         if mm:
#             annual_max_total = _money(mm.group(0))
#     ortho_line = _dq_label(lines, "Orthodontia max.") or _dq_label(lines, "Orthodontia max")
#     if ortho_line:
#         om = re.search(r"\$[\d,]+\.?\d*", ortho_line)
#         if om:
#             ortho_total = _money(om.group(0))

#     # \s+ between words (not a literal space) — "Individual annual maximum
#     # (All Networks)" can wrap mid-label as "(All\nNetworks)" when a
#     # right-column heading like "Preventive Rewards account" sits alongside
#     # it and pushes the line break to a different spot than usual.
#     ind_max_used, ind_max_total_confirmed = _dq_used_out_of(text, r"Individual\s+annual\s+maximum\s+\(All\s+Networks\)")
#     ind_ded_used, ind_ded_total_confirmed = _dq_used_out_of(text, r"Individual\s+deductible\s+\(All\s+Networks\)")
#     fam_ded_used, fam_ded_total_confirmed = _dq_used_out_of(text, r"Family\s+deductible\s+\(All\s+Networks\)")
#     ortho_used,   ortho_total_confirmed   = _dq_used_out_of(text, r"Orthodontics\s+individual\s+lifetime\s+maximum\s+\(All\s+Networks\)")

#     # Financials dict uses the SAME key names build_patient_notes.py's
#     # generic is_pdf branch already reads for every other PDF carrier
#     # ("annual_max" / "individual_deductible" / "ortho_lifetime", each with
#     # "total"/"used") — this is what lets DentaQuest's real usage actually
#     # flow through instead of needing a DentaQuest-specific key name or a
#     # special-cased blanket blank-out.
#     # Financials dict uses the SAME key names build_patient_notes.py's
#     # generic is_pdf branch already reads for every other PDF carrier
#     # ("annual_max" / "individual_deductible" / "ortho_lifetime", each with
#     # "total"/"used") — this is what lets DentaQuest's real usage actually
#     # flow through instead of needing a DentaQuest-specific key name or a
#     # special-cased blanket blank-out.
#     #
#     # "used" defaults to "$ 0.00" (not blank) whenever a category's
#     # "Deductibles & maximums" block is absent entirely — e.g. a plan with
#     # no orthodontic benefit at all won't have an "Orthodontics individual
#     # lifetime maximum" section. Leaving it blank would let the generic
#     # is_pdf fallback in build_patient_notes.py (`used or total`) silently
#     # report that category's plan CEILING as if it were confirmed usage —
#     # the same bug already found and fixed for UCCI. Setting it explicitly
#     # here avoids depending on that fallback behaving correctly by luck.
#     financials = {
#         "annual_max": {
#             "total": f"$ {ind_max_total_confirmed}" if ind_max_total_confirmed else (annual_max_total or "$ 0.00"),
#             "used":  f"$ {ind_max_used}" if ind_max_used is not None else "$ 0.00",
#         },
#         "individual_deductible": {
#             "total": f"$ {ind_ded_total_confirmed}" if ind_ded_total_confirmed else (ind_ded_total or "$ 0.00"),
#             "used":  f"$ {ind_ded_used}" if ind_ded_used is not None else "$ 0.00",
#         },
#         "family_deductible": {
#             "total": f"$ {fam_ded_total_confirmed}" if fam_ded_total_confirmed else (fam_ded_total or "$ 0.00"),
#             "used":  f"$ {fam_ded_used}" if fam_ded_used is not None else "$ 0.00",
#         },
#         "ortho_lifetime": {
#             "total": f"$ {ortho_total_confirmed}" if ortho_total_confirmed else (ortho_total or "$ 0.00"),
#             "used":  f"$ {ortho_used}" if ortho_used is not None else "$ 0.00",
#         },
#     }

#     # ── 4. Claims history (per-code service dates) ──────────────────
#     claims_history = _dq_claims_history(text)
#     if "D0120" in claims_history and "D0150" not in claims_history:
#         claims_history["D0150"] = list(claims_history["D0120"])
#     elif "D0150" in claims_history and "D0120" not in claims_history:
#         claims_history["D0120"] = list(claims_history["D0150"])
#     history = {code: ", ".join(dates) for code, dates in claims_history.items()}

#     result = {
#         "source": "DentaQuest PDF - Member Details",
#         "summary": {
#             "group_name":   plan_name,
#             "group_number": group_number,
#             "plan_name":    plan_name,
#         },
#         "plan_details": plan_details,
#         "patient":      patient,
#         "financials":   financials,
#         "history":      history,
#         "benefit_coverage": {"procedures": []},
#     }

#     if group_number in (None, "N/A") and not claims_history:
#         raise ValueError("Could not extract plan info — DentaQuest PDF layout may have changed.")

#     log.info(f"Parsed DentaQuest PDF: group='{group_number}', plan='{plan_name}', "
#              f"ind_ded_used={ind_ded_used}, ind_max_used={ind_max_used}, ortho_used={ortho_used}, "
#              f"history_codes={list(history.keys())}")
#     return result
import fitz  # PyMuPDF
import re
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────

def _money(val: str | None) -> str | None:
    if not val or val.strip().lower() == "none":
        return None
    cleaned = val.replace(",", "").replace("$", "").strip()
    try:
        return f"$ {float(cleaned):.2f}"
    except ValueError:
        return None


def _money_str(val: float) -> str:
    return f"$ {val:.2f}"


def _parse_dollars(val: str) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", str(val)))
    except Exception:
        return 0.0


def _table_value(text: str, label: str) -> str | None:
    """Extract first dollar-amount from an inline label row (legacy DD layout)."""
    pattern = rf"{re.escape(label)}\s+(\$[\d,]+\.\d+|None)"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _benefit_level(text: str, service_re: str) -> str | None:
    m = re.search(rf"{service_re}\s+([0-9]+%|None)\s+(?:Yes|No)", text, re.IGNORECASE)
    if m:
        v = m.group(1).strip()
        return None if v.lower() == "none" else v
    return None


def _age_range(text: str, keyword_re: str) -> str | None:
    m = re.search(rf"{keyword_re}[^\n]*?Ages?\s+(\d+)\s*[-–]\s*(\d+)", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.search(rf"{keyword_re}[^\n]*?Ages?\s+(\d+)\s+and\s+up", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-99"
    return None


def _normalize_date(raw: str) -> str | None:
    """Normalize any supported date string to MM/DD/YYYY."""
    if not raw:
        return None
    raw = raw.strip()
    # Already MM/DD/YYYY
    if re.match(r"^\d{2}/\d{2}/\d{4}$", raw):
        return raw
    # Month DD, YYYY  e.g. "Jan 08, 2026"
    import datetime
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%y"):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return raw


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


# ──────────────────────────────────────────────────────────────────
# SHARED: TEXT EXTRACTION
# ──────────────────────────────────────────────────────────────────

# Some PDF fonts substitute ligature glyphs ("fi", "fl", "ff", etc.) for a
# single Unicode codepoint (U+FB01 "ﬁ", U+FB02 "ﬂ", U+FB00 "ﬀ", ...) instead
# of the two/three separate letters. PyMuPDF extracts these as that single
# character, which silently breaks every literal-string regex match containing
# "fi"/"fl"/"ff" (e.g. "Satisfied" comes out as "Satisﬁed", "Benefit" as
# "Beneﬁt"). This is a document/font-level quirk that can affect ANY parser,
# not just one carrier, so it's normalized once here at the shared extraction
# point rather than patched per-parser.
_LIGATURE_MAP = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "ft", "\ufb06": "st",
}


def _normalize_ligatures(text: str) -> str:
    for lig, expansion in _LIGATURE_MAP.items():
        text = text.replace(lig, expansion)
    return text


def _extract_text(pdf_bytes: bytes) -> str:
    log.info("Extracting text from PDF...")
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(page.get_text() + "\n" for page in doc)
        doc.close()
    except Exception as e:
        log.error(f"Failed to read PDF: {e}")
        raise ValueError(f"Failed to read PDF: {e}")
    text = _normalize_ligatures(text)
    log.info(f"Extracted {len(text)} characters from PDF.")
    return text


# ──────────────────────────────────────────────────────────────────
# FORMAT DETECTION
# ──────────────────────────────────────────────────────────────────

def detect_format(text: str) -> str:
    """
    Returns one of: 'guardian', 'delta_dental_mo', 'delta_dental_wi',
    'delta_dental_toolkit', 'delta_dental_legacy'
    """
    t = text.lower()

    if "guardiananytime" in t or "dentalguard" in t or "guardian plan" in t:
        return "guardian"

    # dentalofficetoolkit.com portal export (has its own distinct layout —
    # Routine Procedures/Coverages/Maximums tables, no CDT-code history log)
    if "dentalofficetoolkit.com" in t:
        return "delta_dental_toolkit"

    # "Benefits Detail" portal export (Non-Par/PPO/Premier Maximum bars +
    # per-procedure "Benefit Class (Sample Code)" rows with inline
    # "Last Service Date:" fields). IMPORTANT: this format's own footer
    # links to deltadentalwi.com and uses "Last Service Date:" as a field
    # label, so it MUST be checked before the WI heuristics below or it
    # gets misdetected as delta_dental_wi and silently returns empty data.
    if "benefit class (sample code)" in t or ("non-par maximum" in t and "premier maximum" in t):
        return "delta_dental_benefits_detail"

    # DentaQuest's "Member Details" export (providers.dentaquest.com), printed
    # to PDF — has its own line-oriented layout entirely distinct from Delta
    # Dental's, so it must be checked before falling through to the generic
    # "delta dental" text match below (DentaQuest PDFs don't contain that
    # phrase, but keeping this as its own explicit branch avoids relying on
    # that coincidence).
    if "dentaquest" in t:
        return "dentaquest"

    if "delta dental" in t or "deltadental" in t:
        # Wisconsin layout: has the "Eligibility and Accumulations" +
        # "Preventive History - Last Date of Service" sections
        if ("deltadentalwi.com" in t or "delta dental of wisconsin" in t
                or "preventive history - last date of service" in t
                or "last service date:" in t or "coversme" in t):
            return "delta_dental_wi"
        # Missouri layout: has "Used $X | Rem $X" table structure
        if "delta dental of missouri" in t or ("used $" in t and "rem $" in t):
            return "delta_dental_mo"
        # Legacy layout: inline "Group Name:" colon labels
        if re.search(r"Group Name:", text) and re.search(r"Annual Maximums", text):
            return "delta_dental_legacy"
        # Fallback for any other DD PDF
        return "delta_dental_legacy"

    return "unknown"


# ──────────────────────────────────────────────────────────────────
# DISPATCHER
# ──────────────────────────────────────────────────────────────────

def _build_registry() -> dict:
    return {
        "delta_dental_mo":              _parse_delta_dental_mo,
        "delta_dental_wi":              _parse_delta_dental_wi,
        "delta_dental_legacy":          _parse_delta_dental_legacy,
        "delta_dental_toolkit":         _parse_delta_dental_toolkit,
        "delta_dental_benefits_detail": _parse_delta_dental_benefits_detail,
        "guardian":                     _parse_guardian,
        "dentaquest":                   _parse_dentaquest,
    }


async def parse_insurance_pdf(pdf_bytes: bytes) -> dict:
    text = _extract_text(pdf_bytes)
    fmt = detect_format(text)
    log.info(f"Detected insurance format: '{fmt}'")

    if len(text.strip()) < 100:
        raise ValueError(
            "This PDF has no readable text layer (it appears to be scanned or "
            "image-based), so it can't be parsed. Use a text-based PDF export, "
            "or capture the data with the browser extension."
        )
    
    parser = _build_registry().get(fmt)
    if parser is None:
        raise ValueError(
            "Unrecognized insurance PDF format. "
            "Supported: Delta Dental (MO / WI / CoversMe / Toolkit / legacy) and Guardian."
        )

    result = parser(text)
    result.setdefault("summary", {})["insurer"] = fmt
    return result


# Backwards-compatible wrapper
async def parse_delta_dental_pdf(pdf_bytes: bytes) -> dict:
    text = _extract_text(pdf_bytes)
    fmt = detect_format(text)
    parser = _build_registry().get(fmt, _parse_delta_dental_legacy)
    return parser(text)


# ──────────────────────────────────────────────────────────────────
# PARSER: DELTA DENTAL — MISSOURI
# Layout: "Used $X | Rem $X  Total $X" table + "Patient history" section
# ──────────────────────────────────────────────────────────────────

def _parse_dd_mo_history(text: str) -> dict:
    """
    Extract ALL dates of service per CDT code from the 'Patient history'
    table at the end of DD Missouri PDFs -- not just the most recent one.
    Table rows: MM/DD/YYYY  <tooth>  <code>  <description>

    Returns {code: "MM/DD/YYYY, MM/DD/YYYY, ..."} newest-first, matching the
    multi-date comma-joined convention every other multi-visit carrier in
    this pipeline uses (DDVA, UCCI). No cap on how many dates are kept, and
    NO cross-code merging here -- D0120 and D0150 (and D0145, which has no
    output field at all) each only ever get their own literal matches. Any
    alias-level merging (D1110<->D1120, D1206<->D1208, etc.) happens exactly
    once, downstream, in patient_notes.py's CODE_ALIASES -- not here.
    """
    dates_by_code: dict[str, list[str]] = {}
    m = re.search(r"Patient history", text, re.IGNORECASE)
    if not m:
        return {}

    history_text = text[m.start():]
    for match in re.finditer(
        r"(\d{2}/\d{2}/\d{4})\s+\S+\s+(?:\S+\s+)?(D\d{4})", history_text
    ):
        date_str = match.group(1)
        code = match.group(2).upper()
        bucket = dates_by_code.setdefault(code, [])
        if date_str not in bucket:
            bucket.append(date_str)

    history = {}
    for code, dates in dates_by_code.items():
        # Defensive re-sort newest-first -- the source table is already in
        # that order, but don't silently rely on that holding for every
        # future export tweak.
        sorted_dates = sorted(
            dates, key=lambda d: datetime.strptime(d, "%m/%d/%Y"), reverse=True
        )
        history[code] = ", ".join(sorted_dates)

    return history


def _parse_delta_dental_mo(text: str) -> dict:
    """
    Parse Delta Dental of Missouri benefit PDF.
    Financial table format:
      Used $0 | Rem $2000   (PPO column = first occurrence)

    PPO-only by design (Premier / Out-of-Network columns are present in the
    source but intentionally never parsed, per instruction). The FIRST
    "Used $X | Rem $Y" / "Met $X | Rem $Y" match in the whole document is
    always the PPO column for whichever row it belongs to, since PPO is the
    left-most of the three network columns in this layout.
    """
    # ── Group info ────────────────────────────────────────────────
    group_name = ""
    m = re.search(r"Group name:\s*\n?(.+)", text)
    if m:
        # May span multiple lines before "Group number"
        raw = m.group(1).strip()
        # Grab up to 3 continuation lines for multi-line names
        after = text[m.end():]
        extras = []
        for ln in after.splitlines():
            s = ln.strip()
            if not s or re.match(r"Group number|Program type|Benefit cycle|COB", s, re.I):
                break
            extras.append(s)
            if len(extras) >= 3:
                break
        group_name = " ".join([raw] + extras).strip()

    group_number = ""
    m = re.search(r"Group number:\s*([\w]+)", text)
    if m:
        group_number = m.group(1).strip()

    # Patient name: prefer the "Member dependent" name over the subscriber's.
    # The financial/history data in this export belongs to whichever member
    # was selected for benefits verification -- in every real example seen,
    # that's the dependent (a child), not the subscriber (parent) whose name
    # happens to appear first on the page. Falls back to the subscriber name
    # only when there's no dependent listed (e.g. relationship: Self, adult
    # verifying their own benefits, "Member dependent" section reads "None").
    patient_name = ""
    m = re.search(r"Member dependent\s*\n\s*([A-Z][A-Z '\-]+)", text)
    if m and m.group(1).strip().upper() != "NONE":
        patient_name = m.group(1).strip()
    else:
        m2 = re.search(r"Subcriber\s*:\s*\n\s*([A-Z][A-Z '\-]+)", text)
        if m2:
            patient_name = m2.group(1).strip()
        else:
            m3 = re.search(r"^([A-Z][A-Z ]+)$", text, re.MULTILINE)
            if m3:
                patient_name = m3.group(1).strip()

    # ── Annual Max (PPO = first "Regular Used ..." line within the
    # "Maximum" section) ──
    # Anchored specifically to the "Maximum" section and the "Regular" row
    # within it -- NOT a bare global "Used $X | Rem $Y" search. That matters
    # because "Rem" can read "Unlimited" instead of a dollar figure (this is
    # a real, confirmed case: "Regular Used $163 | Rem Unlimited"). A bare
    # search requiring a literal "$" after "Rem" simply fails to match that
    # row at all, then keeps scanning and incorrectly latches onto the NEXT
    # "Used $X | Rem $Y" match in the document -- which is the Orthodontic
    # lifetime row -- silently reporting ortho's $0 as if it were the
    # annual max usage, and losing the real $163 entirely.
    annual_max_total = annual_max_used = annual_max_rem = "$ 0.00"
    max_section_idx = text.find("Maximum")
    max_section_text = text[max_section_idx:] if max_section_idx != -1 else text
    m = re.search(
        r"Regular\s+Used\s+\$([\d,]+\.?\d*)\s*\|\s*Rem\s+(\$[\d,]+\.?\d*|Unlimited)",
        max_section_text
    )
    if m:
        used = _parse_dollars(m.group(1))
        rem_raw = m.group(2).strip()
        annual_max_used = _money_str(used)
        if rem_raw.lower() == "unlimited":
            annual_max_rem   = "Unlimited"
            annual_max_total = "Unlimited"
        else:
            rem   = _parse_dollars(rem_raw)
            total = used + rem
            annual_max_rem   = _money_str(rem)
            annual_max_total = _money_str(total)

    # ── Deductible (PPO = first "Met $X | Rem $X" line) ──
    ded_total = ded_used = ded_rem = "$ 0.00"
    m = re.search(r"Met\s+\$([\d,]+\.?\d*)\s*\|\s*Rem\s+\$([\d,]+\.?\d*)", text)
    if m:
        met   = _parse_dollars(m.group(1))
        rem   = _parse_dollars(m.group(2))
        total = met + rem
        ded_used  = _money_str(met)
        ded_rem   = _money_str(rem)
        ded_total = _money_str(total)

    # ── Ortho lifetime (PPO) ── anchored on "Orthodontic" immediately
    # preceding "Used", since a bare "Used $X | Rem $Y" search would just
    # re-match the Regular annual-max row above it. Without this anchor,
    # ortho used/remaining would stay hardcoded at $0.00 regardless of the
    # patient's actual plan data -- and build_patient_notes.py's generic
    # is_pdf branch falls back to "used or total" when "used" is missing
    # entirely, which would then silently report the ortho CEILING as if
    # it were confirmed usage (the same failure mode already caught and
    # guarded against for UCCI/DentaQuest).
    ortho_total = ortho_used = ortho_rem = "$ 0.00"
    m = re.search(r"Orthodontic\s+Used\s+\$([\d,]+\.?\d*)\s*\|\s*Rem\s+\$([\d,]+\.?\d*)", text)
    if m:
        used  = _parse_dollars(m.group(1))
        rem   = _parse_dollars(m.group(2))
        total = used + rem
        ortho_used  = _money_str(used)
        ortho_rem   = _money_str(rem)
        ortho_total = _money_str(total)

    # ── Family deductible (PPO) ── anchored after the "Family" section
    # header, since a bare "Met $X | Rem $Y" search would just re-match the
    # Individual deductible row found above. Not currently read by
    # build_patient_notes.py's generic is_pdf branch (which only pulls
    # annual_max / individual_deductible / ortho_lifetime), but extracted
    # correctly anyway rather than left as a hardcoded placeholder, in case
    # a future field starts reading it.
    fam_ded_total = fam_ded_used = fam_ded_rem = "$ 0.00"
    fam_idx = text.find("Family")
    if fam_idx != -1:
        fam_m = re.search(
            r"Met\s+\$([\d,]+\.?\d*)\s*\|\s*Rem\s+\$([\d,]+\.?\d*)", text[fam_idx:]
        )
        if fam_m:
            met   = _parse_dollars(fam_m.group(1))
            rem   = _parse_dollars(fam_m.group(2))
            total = met + rem
            fam_ded_used  = _money_str(met)
            fam_ded_rem   = _money_str(rem)
            fam_ded_total = _money_str(total)

    # ── Benefit levels (from benefit breakdown table) ──────────────
    prev_pct  = "100%"
    basic_pct = "80%"
    major_pct = "50%"
    m = re.search(r"Preventative\s+(\d+)%", text)
    if m:
        prev_pct = f"{m.group(1)}%"
    m = re.search(r"Basic\s+(\d+)%", text)
    if m:
        basic_pct = f"{m.group(1)}%"
    m = re.search(r"Major\s+(\d+)%", text)
    if m:
        major_pct = f"{m.group(1)}%"

    # ── History ───────────────────────────────────────────────────
    history = _parse_dd_mo_history(text)

    result = {
        "summary": {
            "group_name":   group_name,
            "group_number": group_number,
            "patient_name": patient_name,
        },
        "financials": {
            "annual_max": {
                "total":     annual_max_total,
                "used":      annual_max_used,
                "remaining": annual_max_rem,
            },
            "individual_deductible": {
                "total":     ded_total,
                "used":      ded_used,
                "remaining": ded_rem,
            },
            "family_deductible": {
                "total":     fam_ded_total,
                "used":      fam_ded_used,
                "remaining": fam_ded_rem,
            },
            "ortho_lifetime": {
                "total":     ortho_total,
                "used":      ortho_used,
                "remaining": ortho_rem,
            },
        },
        "patient":   {"relationship": "Self"},
        "benefit_coverage": {
            "procedures": [
                {"procedure_code": "D0120", "benefit_level": prev_pct},
                {"procedure_code": "D0150", "benefit_level": prev_pct},
                {"procedure_code": "D1110", "benefit_level": prev_pct},
                {"procedure_code": "D1206", "benefit_level": prev_pct},
                {"procedure_code": "D1208", "benefit_level": prev_pct},
                {"procedure_code": "D0210", "benefit_level": prev_pct},
                {"procedure_code": "D0274", "benefit_level": prev_pct},
                {"procedure_code": "D2140", "benefit_level": basic_pct},
                {"procedure_code": "D2331", "benefit_level": basic_pct},
                {"procedure_code": "D2740", "benefit_level": major_pct},
                {"procedure_code": "D4910", "benefit_level": prev_pct},
                {"procedure_code": "D4355", "benefit_level": prev_pct},
                {"procedure_code": "D8080", "benefit_level": "0%"},
            ]
        },
        "history": history,
    }

    if not group_name and not group_number:
        raise ValueError("Could not extract plan info — DD Missouri PDF layout may have changed.")

    log.info(f"[MO] group='{group_name}', max={annual_max_total}, used={annual_max_used}, "
             f"ortho_used={ortho_used}, history_codes={list(history.keys())}")
    return result


# ──────────────────────────────────────────────────────────────────
# PARSER: DELTA DENTAL — WISCONSIN
# ──────────────────────────────────────────────────────────────────

def _wi_find_all_patient_names(text: str) -> list[str]:
    names = []
    for m in re.finditer(
        r"^([A-Z][A-Z'\-]*(?:[ \n][A-Z][A-Z'\-]*){1,6})\n\s*Start\s+\d{2}/\d{2}/\d{4}",
        text, re.MULTILINE
    ):
        name = re.sub(r"\s+", " ", m.group(1).strip())
        if name not in names:
            names.append(name)
    return names


def _parse_dd_wi_financials_all_patients(text: str) -> dict:
    result = {}
    names = _wi_find_all_patient_names(text)

    for name in names:
        name_flex = r"[ \n]+".join(re.escape(w) for w in name.split(" "))

        pattern = re.compile(
            rf"{name_flex}\s*\n\s*Start[^\n]*\n\s*End[^\n]*\n?"
            r"\s*\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)\s+\$([\d,]*\.?\d*)",
            re.IGNORECASE
        )
        m = pattern.search(text)
        if not m:
            continue

        ded_satisfied, reg_max_used, ortho_annual_used, ortho_lifetime_used, custom_used, oop_satisfied = (
            _parse_dollars(g) for g in m.groups()
        )

        result[name] = {
            "individual_deductible_used": _money_str(ded_satisfied),
            "individual_max_used":        _money_str(reg_max_used),
            "ortho_max_used":             _money_str(ortho_lifetime_used),
        }

    return result


def _parse_dd_wi_history_all_patients(text: str) -> dict:
    result = {}

    m = re.search(r"Preventive History.*?Last Date of Service", text, re.IGNORECASE)
    if not m:
        return result

    section = text[m.end():]

    claims_m = re.search(r"\bCla historyims\b", section)
    if claims_m:
        section = section[:claims_m.start()]

    name_pattern = re.compile(r"^([A-Z][A-Z'\-]*(?:\s[A-Z][A-Z'\-]*)+)$", re.MULTILINE)
    name_matches = list(name_pattern.finditer(section))

    date_re = r"(\d{2}/\d{2}/\d{4})"

    for i, nm in enumerate(name_matches):
        name = re.sub(r"\s+", " ", nm.group(1).strip())
        start = nm.end()
        end = name_matches[i + 1].start() if i + 1 < len(name_matches) else len(section)
        block = section[start:end]

        def _find(label_re: str) -> str | None:
            mm = re.search(rf"{label_re}\s*{date_re}", block, re.IGNORECASE)
            return mm.group(1) if mm else None

        exam_date     = _find(r"Exam")
        cleaning_date = _find(r"Cleaning")
        fluoride_date = _find(r"Fluoride")
        bw_date       = _find(r"Bitewing X-?rays")
        fmx_date      = _find(r"Full Mouth or Panoramic X-?rays")

        history = {}
        if exam_date:
            history["D0120"] = exam_date
            history["D0150"] = exam_date
        if cleaning_date:
            history["D1110"] = cleaning_date
            history["D4910"] = cleaning_date
        if fluoride_date:
            history["D1206"] = fluoride_date
            history["D1208"] = fluoride_date
        if bw_date:
            history["D0274"] = bw_date
        if fmx_date:
            history["D0210"] = fmx_date
            history["D0330"] = fmx_date

        if name in result and not history:
            continue
        result[name] = history

    return result


def _parse_delta_dental_wi(text: str) -> dict:
    subscriber_name = ""
    m = re.search(r"Subscriber Name:\s*([A-Z][A-Z ]+?)(?:\s{2,}|\n|Group Number)", text, re.IGNORECASE)
    if m:
        subscriber_name = re.sub(r"\s+", " ", m.group(1).strip())

    group_name = ""
    m = re.search(r"Group Name:\s*(.+)", text, re.IGNORECASE)
    if m:
        group_name = m.group(1).strip()

    group_number = ""
    m = re.search(r"Group Number:\s*([\w\-]+)", text, re.IGNORECASE)
    if m:
        group_number = m.group(1).strip()

    annual_max_plan_total = "$ 0.00"
    m = re.search(r"Annual Maximums\s+\$([\d,]+\.?\d*)", text, re.IGNORECASE)
    if m:
        annual_max_plan_total = _money_str(_parse_dollars(m.group(1)))

    financials_by_patient = _parse_dd_wi_financials_all_patients(text)
    history_by_patient    = _parse_dd_wi_history_all_patients(text)

    def _wi_pct(service_re: str, default: str) -> str:
        # A coverage line reads "Service(code)  50%" OR "Service(code)  None".
        # "None" means the service is explicitly NOT covered → 0% (a real value,
        # not missing data). Only fall back to `default` when the line is absent
        # entirely — never invent a percentage over an explicit "None".
        m = re.search(rf"{service_re}\s*\(\d+\)\s+(\d+%|None)", text, re.IGNORECASE)
        if not m:
            return default
        return "0%" if m.group(1).lower() == "none" else m.group(1)

    prev_pct  = _wi_pct(r"Preventive", "100%")
    basic_pct = _wi_pct(r"Basic Restor", "80%")
    major_pct = _wi_pct(r"Major Restor", "50%")
    perio_pct = _wi_pct(r"Perio Maint", basic_pct)
    # Orthodontics % is stated on the coverage line ("Orthodontics(8010) 50%").
    # Default to 0% when the plan has no ortho row (so ortho-less plans behave
    # as before), but read the real percentage when it is present.
    ortho_pct = _wi_pct(r"Orthodontics", "0%")

    result = {
        "summary": {
            "group_name":      group_name,
            "group_number":    group_number,
            "subscriber_name": subscriber_name,
        },
        "financials": {
            "annual_max": {"total": annual_max_plan_total},
        },
        "financials_by_patient": financials_by_patient,
        "history_by_patient":    history_by_patient,
        "patient":   {"relationship": "Self"},
        "benefit_coverage": {
            "procedures": [
                {"procedure_code": "D0120", "benefit_level": prev_pct},
                {"procedure_code": "D1110", "benefit_level": prev_pct},
                {"procedure_code": "D1206", "benefit_level": "N/A"},
                {"procedure_code": "D2140", "benefit_level": basic_pct},
                {"procedure_code": "D2331", "benefit_level": basic_pct},
                {"procedure_code": "D2740", "benefit_level": major_pct},
                {"procedure_code": "D4910", "benefit_level": perio_pct},
                {"procedure_code": "D4355", "benefit_level": perio_pct},
                {"procedure_code": "D8080", "benefit_level": ortho_pct},
            ]
        },
        "history": {},
    }

    if not group_name and not group_number and not financials_by_patient:
        raise ValueError("Could not extract plan info — DD Wisconsin layout may have changed.")

    log.info(f"[WI] subscriber='{subscriber_name}', patients_found={list(financials_by_patient.keys())}, "
             f"group='{group_name}'")
    return result


# ──────────────────────────────────────────────────────────────────
# PARSER: DELTA DENTAL — TOOLKIT (dentalofficetoolkit.com portal)
# ──────────────────────────────────────────────────────────────────

_TOOLKIT_PROC_LABELS = [
    "Exam", "Adult Cleaning", "Child Cleaning", "Perio Maintenance Cleaning",
    "Bitewings", "Full Mouth X-rays", "Fluoride", "Occlusal Guard",
]

_TOOLKIT_PROC_TO_CODES = {
    "Exam":                       ["D0120", "D0150"],
    "Adult Cleaning":             ["D1110"],
    "Child Cleaning":             ["D1120"],
    "Perio Maintenance Cleaning": ["D4910"],
    "Bitewings":                  ["D0274"],
    "Full Mouth X-rays":          ["D0210", "D0330"],
    "Fluoride":                   ["D1206", "D1208"],
    "Occlusal Guard":             ["D9944"],
}

_TOOLKIT_CATEGORIES = [
    "Diagnostic", "Preventive", "Bitewing Radiographs", "All Other Radiographs",
    "Brush Biopsy", "Sealants", "Minor Restorative", "Major Restorative",
    "Endodontics", "Periodontics", "Relines and Repairs", "Simple Extractions",
    "Other Oral Surgery", "TMD", "Other Basic Services", "Prosthodontics",
    "Implants", "Orthodontic Services",
]


def _toolkit_multiline_field(text: str, label: str, next_label_alt: str) -> str:
    m = re.search(rf"{label}:\s*(.+?)\n(?:{next_label_alt})", text, re.DOTALL)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _toolkit_max_block(text: str, type_label: str, category_label: str) -> dict:
    r"""
    Pull the first Amount/Used/Remaining triplet following a Maximums-table
    row's Type + Category cells (e.g. Type="Maximum", Category="General").
    """
    m = re.search(
        rf"{re.escape(type_label)}\s+{re.escape(category_label)}.*?Amount:\s*\$([\d,]+\.?\d*)\s*\n?"
        r"Used:\s*\$([\d,]+\.?\d*)\s*\n?Remaining:\s*\$([\d,]+\.?\d*)",
        text, re.DOTALL,
    )
    if not m:
        return None
    return {
        "total":     _money_str(_parse_dollars(m.group(1))),
        "used":      _money_str(_parse_dollars(m.group(2))),
        "remaining": _money_str(_parse_dollars(m.group(3))),
    }


def _parse_delta_dental_toolkit(text: str) -> dict:
    """Parse a Delta Dental 'dentalofficetoolkit.com' member-benefits export."""

    patient_name = ""
    m = re.search(r"Patient Name:\s*(.+)", text)
    if m:
        patient_name = m.group(1).strip()

    relationship = "Self"
    m = re.search(r"Relationship:\s*(\w+)", text)
    if m:
        relationship = m.group(1).strip()

    group_number = ""
    m = re.search(r"Group Number:\s*([\w\-]+)", text)
    if m:
        group_number = m.group(1).strip()

    sub_group_number = ""
    m = re.search(r"Sub Group Number:\s*([\w\-]+)", text)
    if m:
        sub_group_number = m.group(1).strip()

    group_name = _toolkit_multiline_field(
        text, "Group Name", "Sub Group Number|Sub Group Name"
    )
    sub_group_name = _toolkit_multiline_field(
        text, "Sub Group Name", "Patient Name|Age Limitations"
    )

    history = {}
    proc_section_m = re.search(r"Service Dates\n(.*?)\nCoverages", text, re.DOTALL)
    if proc_section_m:
        section = proc_section_m.group(1)
        date_pat = r"\d{2}/\d{2}/\d{4}"
        for label in _TOOLKIT_PROC_LABELS:
            m = re.search(
                rf"{re.escape(label)}\s*(?:Yes|No)\s*((?:{date_pat}\s*,?\s*)*)",
                section
            )
            if not m:
                continue
            dates = re.findall(date_pat, m.group(1))
            if not dates:
                continue
            joined = ", ".join(dates)
            for code in _TOOLKIT_PROC_TO_CODES.get(label, []):
                history[code] = joined

    coverages = {}
    for cat in _TOOLKIT_CATEGORIES:
        m = re.search(rf"{re.escape(cat)}\n(\d+|Not Covered)\n", text)
        if m:
            coverages[cat] = m.group(1)

    def _pct(cat: str, default: str) -> str:
        val = coverages.get(cat)
        if val is None:
            return default
        return "0%" if val == "Not Covered" else f"{val}%"

    annual_max     = _toolkit_max_block(text, "Maximum", "General")     or {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
    ortho_lifetime = _toolkit_max_block(text, "Maximum", "Orthodontic") or {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
    implant_max    = _toolkit_max_block(text, "Maximum", "Implants")    or {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
    ind_ded        = _toolkit_max_block(text, "Deductible", "General")  or {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}

    result = {
        "summary": {
            "group_name":       group_name,
            "group_number":     group_number,
            "sub_group_name":   sub_group_name,
            "sub_group_number": sub_group_number,
            "patient_name":     patient_name,
        },
        "financials": {
            "annual_max":            annual_max,
            "individual_deductible": ind_ded,
            "family_deductible":     {"total": "$ 0.00"},
            "ortho_lifetime":        ortho_lifetime,
            "implant_lifetime":      implant_max,
        },
        "patient": {"relationship": relationship},
        "benefit_coverage": {
            "procedures": [
                {"procedure_code": "D0120", "benefit_level": _pct("Diagnostic", "100%")},
                {"procedure_code": "D0150", "benefit_level": _pct("Diagnostic", "100%")},
                {"procedure_code": "D1110", "benefit_level": _pct("Preventive", "100%")},
                {"procedure_code": "D1120", "benefit_level": _pct("Preventive", "100%")},
                {"procedure_code": "D1206", "benefit_level": _pct("Preventive", "100%")},
                {"procedure_code": "D0274", "benefit_level": _pct("Bitewing Radiographs", "100%")},
                {"procedure_code": "D0210", "benefit_level": _pct("All Other Radiographs", "100%")},
                {"procedure_code": "D1351", "benefit_level": _pct("Sealants", "0%")},
                {"procedure_code": "D2140", "benefit_level": _pct("Minor Restorative", "80%")},
                {"procedure_code": "D2331", "benefit_level": _pct("Minor Restorative", "80%")},
                {"procedure_code": "D2740", "benefit_level": _pct("Major Restorative", "50%")},
                {"procedure_code": "D4910", "benefit_level": _pct("Periodontics", "100%")},
                {"procedure_code": "D4355", "benefit_level": _pct("Periodontics", "100%")},
                {"procedure_code": "D6010", "benefit_level": _pct("Implants", "100%")},
                {"procedure_code": "D5110", "benefit_level": _pct("Prosthodontics", "50%")},
                {"procedure_code": "D8080", "benefit_level": _pct("Orthodontic Services", "50%")},
            ]
        },
        "history": history,
    }

    if not group_number and not patient_name:
        raise ValueError("Could not extract plan info — DD Toolkit PDF layout may have changed.")

    log.info(
        f"[Toolkit] patient='{patient_name}', relationship='{relationship}', "
        f"group='{group_number}', annual_max={annual_max['total']} "
        f"(used={annual_max['used']}), history_codes={list(history.keys())}"
    )
    return result


# ──────────────────────────────────────────────────────────────────
# PARSER: DELTA DENTAL — BENEFITS DETAIL (third-party portal export)
# ──────────────────────────────────────────────────────────────────

_BENEFITS_DETAIL_PROC_ROW = re.compile(
    r"([A-Za-z][A-Za-z0-9 /&\-]+?)\s*\((D\d{4}(?:\s+or\s+D\d{4})?)\)\n"
    r"(?:(?!\(D\d{4}(?:\s+or\s+D\d{4})?\)).*?\n)*?"
    r"(\d+%|N/A|\$[\d,]+\.\d{2})\n"
    r"(?:Remaining balance\s*\n\s*up to dentist'?s\s*\n\s*approved amount\s*\n)?"
    r"(Yes|No|N/A)\n(N/A|Satisfied)\n"
)

_BENEFITS_DETAIL_NAME_TO_HISTORY_CODES = [
    (r"bitewing",                          ["D0274"]),
    (r"full mouth or panoramic",           ["D0210", "D0330"]),
    (r"comprehensive and periodic exam",   ["D0120", "D0150"]),
    (r"prophylaxis",                       ["D1110"]),
    (r"perio maintenance",                 ["D4910"]),
    (r"full mouth debridement",            ["D4355"]),
    (r"fluoride",                          ["D1206", "D1208"]),
]


def _benefits_detail_tier_max(text: str, tier: str) -> dict:
    m = re.search(
        rf"{tier} Maximum\n\d+% used - \d+% max\n\$([\d,]+\.\d+) used - \$([\d,]+\.\d+) max",
        text,
    )
    if not m:
        return {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
    used  = _parse_dollars(m.group(1))
    total = _parse_dollars(m.group(2))
    return {
        "total":     _money_str(total),
        "used":      _money_str(used),
        "remaining": _money_str(total - used),
    }


def _benefits_detail_tier_deductible(text: str, label: str, tier: str) -> dict:
    m = re.search(
        rf"{label} \({tier} Deductible\):\n\$([\d,]+\.\d+) per year, \$([\d,]+\.\d+) remains to be paid",
        text,
    )
    if not m:
        return {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}
    total     = _parse_dollars(m.group(1))
    remaining = _parse_dollars(m.group(2))
    return {
        "total":     _money_str(total),
        "used":      _money_str(total - remaining),
        "remaining": _money_str(remaining),
    }


def _parse_delta_dental_benefits_detail(text: str) -> dict:
    """Parse a Delta Dental 'Benefits Detail' third-party portal export."""

    subscriber_name = ""
    m = re.search(r"Subscriber name:\n(.+)", text)
    if m:
        subscriber_name = m.group(1).strip()

    patient_name = subscriber_name
    m = re.search(r"Benefits for (.+)", text)
    if m:
        patient_name = m.group(1).strip()

    group_number = ""
    m = re.search(r"Group #:\n([\w]+)", text)
    if m:
        group_number = m.group(1).strip()

    group_name = ""
    m = re.search(r"Group name:\n(.+)", text)
    if m:
        group_name = m.group(1).strip()

    annual_max = _benefits_detail_tier_max(text, "PPO")
    ind_ded    = _benefits_detail_tier_deductible(text, "Individual deductible", "PPO")
    fam_ded    = _benefits_detail_tier_deductible(text, "Family deductible", "PPO")

    ortho_lifetime = {"total": "$ 0.00", "used": "$ 0.00", "remaining": "$ 0.00"}

    matches = list(_BENEFITS_DETAIL_PROC_ROW.finditer(text))
    procedures = []
    history = {}
    code_shares = {}

    for i, m in enumerate(matches):
        name = m.group(1).strip()
        codes_raw = re.sub(r"\s+", " ", m.group(2)).replace(" or ", ",")
        codes = [c.strip() for c in codes_raw.split(",")]
        pct = m.group(3)
        benefit_level = "0%" if pct == "N/A" else pct

        if re.search(r"bitewing", name.lower()):
            codes = ["D0274"]

        for code in codes:
            procedures.append({"procedure_code": code, "benefit_level": benefit_level})

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]

        name_lower = name.lower()
        output_codes = codes
        for pat, hist_codes in _BENEFITS_DETAIL_NAME_TO_HISTORY_CODES:
            if re.search(pat, name_lower):
                output_codes = hist_codes
                break

        shares_m = re.search(
            r"Similar procedures performed impact frequency\s*\n"
            r"limitations\s*-\s*([^\n]+)",
            block
        )
        if shares_m:
            shared_codes = re.findall(r"D\d{4}", shares_m.group(1))
            if shared_codes:
                for oc in output_codes:
                    code_shares.setdefault(oc, set()).update(shared_codes)

        lsd_m = re.search(r"Last Service Date:\s*(\d{2}/\d{2}/\d{4})", block)
        if not lsd_m:
            continue
        lsd = lsd_m.group(1)

        for oc in output_codes:
            history[oc] = lsd

    def _parse_lsd(d):
        return datetime.strptime(d, "%m/%d/%Y")

    visited = set()
    for code in list(history.keys()):
        if code in visited:
            continue
        group = {code}
        frontier = [code]
        while frontier:
            c = frontier.pop()
            for peer in code_shares.get(c, ()):
                if peer in history and peer not in group:
                    group.add(peer)
                    frontier.append(peer)
        if len(group) > 1:
            dates = {history[c] for c in group}
            merged = ", ".join(sorted(dates, key=_parse_lsd, reverse=True))
            for c in group:
                history[c] = merged
        visited |= group

    result = {
        "summary": {
            "group_name":      group_name,
            "group_number":    group_number,
            "subscriber_name": subscriber_name,
            "patient_name":    patient_name,
        },
        "financials": {
            "annual_max":            annual_max,
            "individual_deductible": ind_ded,
            "family_deductible":     fam_ded,
            "ortho_lifetime":        ortho_lifetime,
        },
        "patient": {"relationship": "Self"},
        "benefit_coverage": {"procedures": procedures},
        "history": history,
    }

    if not group_number and not subscriber_name:
        raise ValueError("Could not extract plan info — DD Benefits Detail PDF layout may have changed.")

    log.info(
        f"[BenefitsDetail] subscriber='{subscriber_name}', group='{group_number}', "
        f"annual_max={annual_max['total']} (used={annual_max['used']}), "
        f"history_codes={list(history.keys())}"
    )
    return result


# ──────────────────────────────────────────────────────────────────
# PARSER: DELTA DENTAL — LEGACY (original inline-label layout)
# ──────────────────────────────────────────────────────────────────

def _parse_delta_dental_legacy(text: str) -> dict:
    group_name, group_number = "", ""

    m = re.search(r"Group Name:\s*(.+)", text)
    if m:
        group_name = m.group(1).strip()

    m = re.search(r"Group Number:\s*([\w\-]+)", text)
    if m:
        raw = m.group(1).strip()
        parts = raw.split("-")
        while len(parts) > 2 and parts[-1] == "00000":
            parts.pop()
        group_number = "-".join(parts)

    annual_max     = _money(_table_value(text, "Annual Maximums"))
    annual_ded     = _money(_table_value(text, "Annual Deductibles"))
    fam_ded        = _money(_table_value(text, "Annual Family Deductibles"))
    ortho_lifetime = _money(_table_value(text, "Ortho Lifetime Maximums"))
    ortho_ded      = _money(_table_value(text, "Ortho Annual Deductibles"))
    ind_ded        = annual_ded or ortho_ded or "$ 0.00"

    diag_pct    = _benefit_level(text, r"Diagnostic\(\d+\)")
    prev_pct    = _benefit_level(text, r"Preventive\(\d+\)")
    sealant_pct = _benefit_level(text, r"Sealants\(\d+\)")
    basic_pct   = _benefit_level(text, r"Basic\s+Restor\(\d+\)")
    major_pct   = _benefit_level(text, r"Major\s+Restor\(\d+\)")
    ortho_pct   = _benefit_level(text, r"Orthodontics\(\d+\)")

    d0120_pct = diag_pct or prev_pct or "100%"
    d1206_pct = prev_pct or "100%"
    d1351_pct = sealant_pct or "100%"
    d1510_pct = prev_pct or "100%"
    d2331_pct = basic_pct or "80%"
    d2140_pct = basic_pct or "80%"
    d2740_pct = major_pct or "50%"
    d8080_pct = ortho_pct or "50%"

    sealant_age  = _age_range(text, "Sealants")
    fluoride_age = _age_range(text, r"Fluoride\s+Varnish") or _age_range(text, "Fluoride")

    ortho_age = None
    m = re.search(r"Dependent Orthodontic Age:\s*(\d+)", text)
    if m:
        ortho_age = f"0-{m.group(1)}"
    if not ortho_age:
        m = re.search(r"Child Coverage Age:\s*(\d+)", text)
        if m:
            ortho_age = f"0-{m.group(1)}"

    space_maint_age = None
    m = re.search(r"Child Coverage Age:\s*(\d+)", text)
    if m:
        space_maint_age = f"0-{m.group(1)}"

    result = {
        "summary": {"group_name": group_name, "group_number": group_number},
        "financials": {
            "individual_deductible": {"total": ind_ded},
            "family_deductible":     {"total": fam_ded or "$ 0.00"},
            "annual_max":            {"total": annual_max or "$ 0.00"},
            "ortho_lifetime":        {"total": ortho_lifetime or "$ 0.00"},
        },
        "patient": {"relationship": "Self"},
        "benefit_coverage": {
            "procedures": [
                {"procedure_code": "D0120", "benefit_level": d0120_pct, "age_limit": "0-99"},
                {"procedure_code": "D1206", "benefit_level": d1206_pct, "age_limit": fluoride_age or "0-18"},
                {"procedure_code": "D1351", "benefit_level": d1351_pct, "age_limit": sealant_age or "0-18"},
                {"procedure_code": "D1510", "benefit_level": d1510_pct, "age_limit": space_maint_age or "0-14"},
                {"procedure_code": "D2331", "benefit_level": d2331_pct},
                {"procedure_code": "D2140", "benefit_level": d2140_pct},
                {"procedure_code": "D2740", "benefit_level": d2740_pct},
                {"procedure_code": "D8080", "benefit_level": d8080_pct, "age_limit": ortho_age or "0-26"},
            ]
        },
        "history": {},
    }

    if not group_name and not group_number:
        raise ValueError("Could not extract plan info — PDF format may not be supported.")

    log.info(f"[Legacy] group='{group_name}', number='{group_number}', annual_max={annual_max}")
    return result


# ──────────────────────────────────────────────────────────────────
# PARSER: GUARDIAN
# ──────────────────────────────────────────────────────────────────

def _lines_between(lines: list[str], start_label: str, end_label: str) -> str:
    capturing, out = False, []
    for ln in lines:
        s = ln.strip()
        if not capturing:
            if s.lower() == start_label.lower():
                capturing = True
            continue
        if s.lower() == end_label.lower():
            break
        if s:
            out.append(s)
    return " ".join(out).strip()


def _line_after(lines: list[str], label: str) -> str | None:
    for i, ln in enumerate(lines):
        if ln.strip().lower() == label.lower():
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
    return None


def _parse_guardian_history(text: str) -> dict:
    lines = text.splitlines()
    reassembled = []
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if re.search(r"\d{2}/\d{2}/\d{3}$", ln) and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if re.match(r"^\d", nxt):
                reassembled.append(ln + nxt[0])
                if len(nxt) > 1:
                    reassembled.append(nxt[1:])
                i += 2
                continue
        reassembled.append(ln)
        i += 1
    full_text = "\n".join(reassembled)
    flat = re.sub(r"\s+", " ", full_text)

    history = {}

    service_map = [
        (r"Cleanings|Prophylaxis",     ["D1110"]),
        (r"Exams|Oral\s+Evaluations",  ["D0120", "D0150"]),
        (r"Fluoride",                  ["D1206"]),
        (r"Periodontal\s+Maintenance", ["D4910"]),
        (r"Periodontics",              ["D4355"]),
    ]
    for pattern, codes in service_map:
        m = re.search(pattern, flat, re.IGNORECASE)
        if not m:
            continue
        snippet = flat[m.start(): m.start() + 500]
        date_m = re.search(r"\d{2}/\d{2}/\d{4}", snippet)
        if date_m:
            for code in codes:
                if code not in history:
                    history[code] = date_m.group(0)

    xray_m = re.search(r"X-Rays", flat, re.IGNORECASE)
    if xray_m:
        xray_snippet = flat[xray_m.start(): xray_m.start() + 1500]
        bw_m = re.search(r"Bitewings?[^\d]{0,10}(\d{2}/\d{2}/\d{4})", xray_snippet, re.IGNORECASE)
        fm_m = re.search(r"FullMouth[^\d]{0,30}(\d{2}/\d{2}/\d{4})", xray_snippet, re.IGNORECASE)
        if bw_m:
            history["D0274"] = bw_m.group(1)
        if fm_m:
            history["D0210"] = fm_m.group(1)

    return history


def _parse_guardian(text: str) -> dict:
    lines   = text.splitlines()
    flat    = re.sub(r"\s+", " ", text)
    nospace = re.sub(r"\s+", "", text)

    group_name   = _lines_between(lines, "Group name", "Group number")
    group_number = ""
    raw_num = _line_after(lines, "Group number")
    if raw_num:
        m = re.match(r"[\w\-]+", raw_num)
        group_number = m.group(0) if m else raw_num.strip()

    plan_name = ""
    m = re.search(r"plan is ([A-Z0-9][A-Z0-9 /&\-]+?)\.", flat)
    if m:
        plan_name = m.group(1).strip()

    annual_max_total = annual_max_used = annual_max_rem = None
    m = re.search(r"(?:DG\s*Preferred|In\s*network)\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})", flat)
    if m:
        total = _parse_dollars(m.group(1))
        rem   = _parse_dollars(m.group(2))
        used  = max(0.0, total - rem)
        annual_max_total = _money_str(total)
        annual_max_rem   = _money_str(rem)
        annual_max_used  = _money_str(used)

    ind_ded_total = ind_ded_used = ind_ded_rem = None
    m = re.search(
        r"(?:DG\s*Preferred|In\s*network)\s+\$([\d,]+\.\d{2})\s+(?:Yes|No)\s+\$([\d,]+\.\d{2})",
        flat, re.IGNORECASE
    )
    if m:
        ded_total = _parse_dollars(m.group(1))
        ded_rem   = _parse_dollars(m.group(2))
        ind_ded_total = _money_str(ded_total)
        ind_ded_rem   = _money_str(ded_rem)
        ind_ded_used  = _money_str(max(0.0, ded_total - ded_rem))

    ortho_total = ortho_used = None
    ortho_section_m = re.search(r"Orthodon\s*tic\b", flat, re.IGNORECASE)
    if ortho_section_m:
        m = re.search(
            r"(?:DG\s*Preferred|In\s*network)\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})",
            flat[ortho_section_m.end(): ortho_section_m.end() + 300],
            re.IGNORECASE
        )
        if m:
            lifetime_total = _parse_dollars(m.group(2))
            lifetime_rem   = _parse_dollars(m.group(3))
            ortho_total = _money_str(lifetime_total)
            ortho_used  = _money_str(max(0.0, lifetime_total - lifetime_rem))

    def _cat_pct(category: str) -> str | None:
        mm = re.search(category + category + r"(\d+)%", nospace)
        return mm.group(1) if mm else None

    prev_pct  = _cat_pct("Preventive")
    basic_pct = _cat_pct("Basic")
    major_pct = _cat_pct("Major")
    ortho_pct = _cat_pct("Ortho")
    ortho_not_covered = bool(re.search(r"OrthodonticsNotCovered", nospace))

    def _age(pattern: str) -> str | None:
        mm = re.search(pattern, flat, re.IGNORECASE)
        return mm.group(1) if mm else None

    fluoride_age = _age(r"Fluoride \(D1206[^)]*\)[^.]*?up to age (\d+)")
    sealant_age  = _age(r"Sealant \(D1351\)[^.]*?up to age (\d+)")
    space_age    = _age(r"Space maintainers[^.]*?under the age of (\d+)")
    # Eligibility pages state the plan's ortho age limit as its own labelled
    # field ("Orthodontics age limit  19"). Do NOT confuse it with the
    # "Dependent age limit" / "Student age limit" fields next to it.
    ortho_age    = _age(r"Orthodontics?\s+age\s+limit\s+(\d+)")

    history = _parse_guardian_history(text)

    # IMPORTANT: only emit values the PDF actually states. Eligibility pages
    # are often printed with the Deductibles / Plan maximums / Plan options
    # accordions COLLAPSED — no financials or percentages in the text at all.
    # Fabricated defaults ($0.00, 100/80/50%) create false mismatches against
    # every correct Denticon plan downstream.
    procedures = []

    def _add_proc(code: str, pct: str | None, age: str | None, **extra):
        row = {"procedure_code": code}
        if pct is not None:
            row["benefit_level"] = f"{pct}%"
        if age is not None:
            row["age_limit"] = f"0-{age}"
        row.update(extra)
        if len(row) > 1:                 # skip rows with no actual data
            procedures.append(row)

    _add_proc("D0120", prev_pct, None)
    # No pct inheritance for D1206/D1351/D1510 — Guardian only states
    # category percentages; assigning the preventive pct to them fabricates
    # portal values the page never showed.
    _add_proc("D1206", None, fluoride_age)
    _add_proc("D1351", None, sealant_age)
    _add_proc("D1510", None, space_age)
    _add_proc("D2331", basic_pct, None)
    _add_proc("D2140", basic_pct, None)
    _add_proc("D2740", major_pct, None)
    if ortho_not_covered:
        _add_proc("D8080", "0", ortho_age, frequency_limit="Not Covered")
    else:
        _add_proc("D8080", ortho_pct, ortho_age)

    financials = {}
    if ind_ded_total is not None:
        financials["individual_deductible"] = {
            "total":     ind_ded_total,
            "used":      ind_ded_used,
            "remaining": ind_ded_rem,
        }
    if annual_max_total is not None:
        financials["annual_max"] = {
            "total":     annual_max_total,
            "used":      annual_max_used,
            "remaining": annual_max_rem,
        }
    if ortho_total is not None:
        financials["ortho_lifetime"] = {
            "total": ortho_total,
            "used":  ortho_used,
        }
    # family_deductible intentionally absent — Guardian pages don't state it.

    result = {
        "summary": {
            "group_name":   group_name,
            "group_number": group_number,
            "plan_name":    plan_name,
        },
        "financials": financials,
        "patient":   {"relationship": "Self"},
        "benefit_coverage": {"procedures": procedures},
        "history":   history,
    }

    if not group_name and not group_number:
        raise ValueError("Could not extract plan info — Guardian PDF layout may have changed.")

    log.info(f"[Guardian] group='{group_name}', number='{group_number}', "
             f"annual_max={annual_max_total}, used={annual_max_used}, prev={prev_pct}, basic={basic_pct}")
    return result


# ──────────────────────────────────────────────────────────────────
# PARSER: DENTAQUEST  (providers.dentaquest.com "Member Details" export)
# ──────────────────────────────────────────────────────────────────

def _dq_label(lines: list[str], label: str) -> str | None:
    want = label.lower().rstrip(":").strip() + ":"
    for i, ln in enumerate(lines):
        s = ln.strip()
        m = re.match(rf"{re.escape(label)}\s*:\s*(.+)$", s, re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip()
        if s.lower() == want:
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
    return None


def _dq_used_out_of(text: str, label_pattern: str, window: int = 1500):
    r"""
    Pull "$USED out of $TOTAL" for a "Deductibles & maximums" category --
    e.g. label_pattern=r"Individual deductible \(All Networks\)" matches
    the block naming that category and returns (used, total) as plain
    numeric strings, or (None, None) if that category isn't present /
    has no dollar ceiling on this plan.

    Bounded to a fixed character `window` after the label match -- NOT an
    unbounded DOTALL scan to end-of-document. This matters because a
    category with an Unlimited maximum has no "$X out of $Y" line of its
    own; an unbounded search would keep scanning forward past it and
    latch onto the NEXT category's dollar figures instead. This is a
    real, confirmed bug: an Unlimited "Individual annual maximum" block
    had no numeric line, so the old unbounded regex kept going and
    grabbed the Orthodontics lifetime maximum's numbers -- reporting
    ortho usage ($1,976.38) as if it were the annual maximum usage.

    If "Unlimited" appears in the window before any dollar pattern is
    found, we bail out with (None, None) rather than let the dollar
    search below wander into a different category's block.
    """
    m = re.search(label_pattern, text)
    if not m:
        return None, None

    snippet = text[m.end(): m.end() + window]

    if re.search(r"\bUnlimited\b", snippet, re.IGNORECASE):
        return None, None

    m2 = re.search(r"\$([\d,]+\.\d{2}) out of \$([\d,]+\.\d{2})", snippet)
    if not m2:
        return None, None
    return m2.group(1).replace(",", ""), m2.group(2).replace(",", "")


def _dq_claims_history(text: str) -> dict:
    history: dict[str, list[str]] = {}

    m = re.search(r"Billed submitted\s*\nStatus\s*\n", text)
    if not m:
        return history
    section = text[m.end():]

    end_m = re.search(r"\n\d{6,}\s*\n[A-Za-z].*Network", section)
    if end_m:
        section = section[:end_m.start()]

    row_re = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s*\n"
        r"(D\d{4})\s*\n"
        r"(.*?)\n"
        r"(?:[A-Za-z0-9\-]+(?:\s*/\s*[A-Za-z0-9\-]+){3}\s*\n)?"
        r"Office\s*\n?"
    )
    for row_m in row_re.finditer(section):
        date, code = row_m.group(1), row_m.group(2).upper()
        history.setdefault(code, []).append(date)

    return history


def _parse_dentaquest(text: str) -> dict:
    """Parse a DentaQuest (Sun Life) 'Member Details' PDF into the common schema."""
    lines = text.splitlines()

    name = None
    m = re.search(r"Member information for\s+([A-Z][A-Za-z .'\-]+)", text)
    if m:
        name = m.group(1).strip()
    name = name or _dq_label(lines, "Name")

    level = _dq_label(lines, "Level of coverage") or "N/A"
    relationship = (level if level != "N/A"
                    and not re.search(r"employee only|self|subscriber|member", level, re.I)
                    else "Self")

    patient = {
        "name":              name or "N/A",
        "dob":               _dq_label(lines, "Date of birth") or "N/A",
        "age":               _dq_label(lines, "Age") or "N/A",
        "member_id":         _dq_label(lines, "ID number") or "N/A",
        "relationship":      relationship,
        "level_of_coverage": level,
    }

    plan_name    = _dq_label(lines, "Plan") or "N/A"
    group_number = _dq_label(lines, "Plan/Group number") or _dq_label(lines, "Group number") or "N/A"
    if group_number != "N/A":
        gm = re.match(r"[\w\-]+", group_number)
        group_number = gm.group(0) if gm else group_number
    network = _dq_label(lines, "Network") or "N/A"

    plan_details = {
        "plan_name":         plan_name,
        "group_number":      group_number,
        "employer_group":    plan_name,
        "network":           network,
        "level_of_coverage": level,
    }

    ind_ded_total = fam_ded_total = annual_max_total = ortho_total = None
    ded_line = _dq_label(lines, "Deductible")
    if ded_line:
        dms = re.findall(r"\$[\d,]+\.?\d*", ded_line)
        if dms:
            ind_ded_total = _money(dms[0])
        if len(dms) > 1:
            fam_ded_total = _money(dms[1])
    max_line = _dq_label(lines, "Maximum")
    if max_line:
        mm = re.search(r"\$[\d,]+\.?\d*", max_line)
        if mm:
            annual_max_total = _money(mm.group(0))
    ortho_line = _dq_label(lines, "Orthodontia max.") or _dq_label(lines, "Orthodontia max")
    if ortho_line:
        om = re.search(r"\$[\d,]+\.?\d*", ortho_line)
        if om:
            ortho_total = _money(om.group(0))

    ind_max_used, ind_max_total_confirmed = _dq_used_out_of(text,r"Individual\s+annual\s+maximum\s+\((?:All\s+Networks|In\s+Network\s*\+\s*Out\s+of\s+Network)\)")
    ind_ded_used, ind_ded_total_confirmed = _dq_used_out_of(text, r"Individual\s+deductible\s+\(All\s+Networks\)")
    fam_ded_used, fam_ded_total_confirmed = _dq_used_out_of(text, r"Family\s+deductible\s+\(All\s+Networks\)")
    ortho_used,   ortho_total_confirmed   = _dq_used_out_of(text, r"Orthodontics\s+individual\s+lifetime\s+maximum\s+\(All\s+Networks\)")

    financials = {
        "annual_max": {
            "total": f"$ {ind_max_total_confirmed}" if ind_max_total_confirmed else (annual_max_total or "$ 0.00"),
            "used":  f"$ {ind_max_used}" if ind_max_used is not None else "$ 0.00",
        },
        "individual_deductible": {
            "total": f"$ {ind_ded_total_confirmed}" if ind_ded_total_confirmed else (ind_ded_total or "$ 0.00"),
            "used":  f"$ {ind_ded_used}" if ind_ded_used is not None else "$ 0.00",
        },
        "family_deductible": {
            "total": f"$ {fam_ded_total_confirmed}" if fam_ded_total_confirmed else (fam_ded_total or "$ 0.00"),
            "used":  f"$ {fam_ded_used}" if fam_ded_used is not None else "$ 0.00",
        },
        "ortho_lifetime": {
            "total": f"$ {ortho_total_confirmed}" if ortho_total_confirmed else (ortho_total or "$ 0.00"),
            "used":  f"$ {ortho_used}" if ortho_used is not None else "$ 0.00",
        },
    }

    claims_history = _dq_claims_history(text)
    if "D0120" in claims_history and "D0150" not in claims_history:
        claims_history["D0150"] = list(claims_history["D0120"])
    elif "D0150" in claims_history and "D0120" not in claims_history:
        claims_history["D0120"] = list(claims_history["D0150"])
    history = {code: ", ".join(dates) for code, dates in claims_history.items()}

    result = {
        "source": "DentaQuest PDF - Member Details",
        "summary": {
            "group_name":   plan_name,
            "group_number": group_number,
            "plan_name":    plan_name,
        },
        "plan_details": plan_details,
        "patient":      patient,
        "financials":   financials,
        "history":      history,
        "benefit_coverage": {"procedures": []},
    }

    if group_number in (None, "N/A") and not claims_history:
        raise ValueError("Could not extract plan info — DentaQuest PDF layout may have changed.")

    log.info(f"Parsed DentaQuest PDF: group='{group_number}', plan='{plan_name}', "
             f"ind_ded_used={ind_ded_used}, ind_max_used={ind_max_used}, ortho_used={ortho_used}, "
             f"history_codes={list(history.keys())}")
    return result