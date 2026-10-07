# # from fastapi import FastAPI, HTTPException
# # from fastapi.middleware.cors import CORSMiddleware
# # from pydantic import BaseModel
# # import uvicorn

# # from DCA.compare_patients import trim_patient_data, ask_ollama

# # app = FastAPI(title="AI Insurance Matcher")

# # # Allow the HTML UI to talk to this API
# # app.add_middleware(
# #     CORSMiddleware,
# #     allow_origins=["*"],

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

from DCA.compare_patients import match_insurance_plan

from DCA.patient_notes import build_patient_notes

from fastapi.responses import Response, FileResponse
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from typing import List
from datetime import datetime
from starlette.concurrency import run_in_threadpool
import functools
import base64
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from shared.pdf_extractor import parse_insurance_pdf
from Appointment_Scheduler.appointment_processor import (
    process_appointments,
    generate_day_start_reports,
    build_office_reports,
    load_exclusions,
    save_exclusions,
    load_block_names,
    save_block_names,
    history_info,
    reset_history,
)
from Appointment_Scheduler.email_sender import (
    email_office_reports,
    load_email_map,
    parse_email_map_upload,
)

app = FastAPI(title="AI Insurance Matcher")

# Allow the HTML UI to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request models ────────────────────────────────────────────────────────────

class MatchRequest(BaseModel):
    portal_data: dict
    denticon_data: dict
    client: Optional[str] = None

class NotesRequest(BaseModel):
    denticon_data: dict
    insurance_data: dict
    client: Optional[str] = None

class PDFRequest(BaseModel):
    portal_data: dict
    denticon_data: dict
    client: Optional[str] = None

class InsOverride(BaseModel):
    insName:      Optional[str] = None
    feeSchedule:  Optional[str] = None
    relationship: Optional[str] = None

class NewPlanRequest(BaseModel):
    portal_data:   dict
    denticon_data: dict
    client:        Optional[str] = None
    ins_override:  Optional[InsOverride] = None   # ← carries modal values

# ── Clients ───────────────────────────────────────────────────────────────────
#
# Each client's code lives in a package of its own — its portal readers, its
# breakdown builder, and whatever else it needs. Nothing here guesses which one
# a request means: the caller names the client, and an unnamed or unknown one
# is refused rather than defaulted, because running DCA's rules on a Smile
# Partners sheet would produce a confident wrong answer instead of an error.

CLIENTS = {
    "dca": {
        "label":    "DCA",
        "system":   "Denticon",
        "package":  "DCA",
        "hint":     "Portal export + Denticon deep-audit JSON",
        # What this client's folder actually provides.
        "supports": {"match", "notes", "new_plan", "parse_pdf"},
    },
    "smile_partners": {
        "label":    "Smile Partners",
        "system":   "Sabrina",
        "package":  "smile_partners",
        "hint":     "Portal export + Sabrina breakdown PDF",
        "supports": {"sabrina_audit", "parse_pdf"},
    },
}

# What each capability is called in an error the user will read.
_CAPABILITY_NAMES = {
    "match":         "AI plan matching",
    "notes":         "patient notes",
    "new_plan":      "the Insurance Plan Breakdown PDF",
    "sabrina_audit": "the Sabrina sheet audit",
    "parse_pdf":     "portal PDF parsing",
}


def resolve_client(name, capability):
    """
    The client a request names, refusing anything that cannot be run as asked.

    Returns (key, spec). Raises 400 when no client was named, when the name is
    not one we have, or when that client's folder has nothing for the job.
    """
    key = str(name or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Choose a client first — this decides whose rules are applied.")
    if key not in CLIENTS:
        known = ", ".join(sorted(CLIENTS))
        raise HTTPException(status_code=400, detail=f"Unknown client {name!r}. Known: {known}")
    spec = CLIENTS[key]
    if capability not in spec["supports"]:
        job = _CAPABILITY_NAMES.get(capability, capability)
        raise HTTPException(
            status_code=400,
            detail=f"{spec['label']} does not use {job}.")
    return key, spec


def client_module(spec, dotted):
    """A module inside a client's package, imported by name."""
    from importlib import import_module
    return import_module(f"{spec['package']}.{dotted}")


class ExclusionRequest(BaseModel):
    exclusions: list

class BlockNamesRequest(BaseModel):
    block_names: list


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def serve_ui():
    """Serve the web UI (index.html) so it can be opened directly from the server."""
    return FileResponse(os.path.join(BASE_DIR, "web", "index.html"))


@app.get("/api/clients")
def list_clients():
    """
    The clients this server can run, for the UI's picker.

    Served rather than hard-coded in the page so that adding a client is one
    entry in `CLIENTS` and the dropdown follows.
    """
    return {
        "clients": [
            {
                "key":      key,
                "label":    spec["label"],
                "system":   spec["system"],
                "hint":     spec["hint"],
                "supports": sorted(spec["supports"]),
            }
            for key, spec in CLIENTS.items()
        ]
    }


@app.post("/api/match")
async def match_patient_plan(req: MatchRequest):
    resolve_client(req.client, "match")
    if not req.portal_data or not req.denticon_data:
        raise HTTPException(status_code=400, detail="Missing portal or denticon data")

    print("Matching portal data against Denticon plans...")
    result = await match_insurance_plan(req.portal_data, req.denticon_data)
    return result


@app.post("/api/patient-notes")
def generate_notes(req: NotesRequest):
    resolve_client(req.client, "notes")
    if not req.denticon_data or not req.insurance_data:
        raise HTTPException(status_code=400, detail="Missing denticon or insurance data")

    result = build_patient_notes(req.denticon_data, req.insurance_data)
    return result

@app.post("/api/generate-new-plan-pdf")
async def generate_new_plan_pdf_api(req: PDFRequest):
    _key, spec = resolve_client(req.client, "new_plan")
    build_pdf = client_module(spec, "plan_pdf").generate_new_plan_pdf

    if not req.portal_data or not req.denticon_data:
        raise HTTPException(
            status_code=400,
            detail="Missing portal or denticon data"
        )

    pdf_bytes = build_pdf(
        req.portal_data,
        req.denticon_data
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
            "attachment; filename=insurance_breakdown.pdf"
        }
    )

@app.post("/api/parse-pdf")
async def parse_pdf_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF")
    pdf_bytes = await file.read()
    
    try:
        result = await parse_insurance_pdf(pdf_bytes)
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF parsing failed: {str(e)}")
    
# ── Sabrina flow (clients that don't use Denticon) ────────────────────────────
#
# These teams export a patient breakdown PDF from Sabrina instead of a Denticon
# JSON. There are no candidate plans to rank, so /api/match does not apply — the
# job is a straight field-by-field audit against the insurance portal.
#
# The sheet is the client's own, so the audit that reads it is too: both
# endpoints below run the `sabrina` package of whichever client the request
# names, and refuse a client that has none.

@app.post("/api/sabrina-parse")
async def sabrina_parse_endpoint(
    file: UploadFile = File(...),
    client: Optional[str] = Form(None),
):
    """
    Confirm an uploaded PDF is a Sabrina breakdown and return the fields read
    off it. The UI calls this on upload so it can acknowledge the file (and
    reject a wrong one) before the portal export is even loaded.
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF")

    _key, spec = resolve_client(client, "sabrina_audit")
    audit = client_module(spec, "sabrina")

    pdf_bytes = await file.read()
    try:
        parsed = await run_in_threadpool(audit.parse_sabrina_pdf, pdf_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sabrina PDF parsing failed: {e}")

    fields = parsed["fields"]
    # Counted over the labelled fields only — the generated Frequency/Age/History
    # rows are not "fields on the sheet" and most are legitimately empty.
    core = audit.core_fields(fields)
    return {
        "client":            _key,
        "is_sabrina":        audit.is_sabrina_pdf(parsed["text"]),
        "marker_count":      parsed["marker_count"],
        "fields_found":      sum(1 for v in core.values() if v not in (None, "")),
        "fields_total":      len(core),
        "benefit_rows_read": len(parsed.get("benefit_rows") or {}),
        "patient_name":      fields.get("patient_name"),
        "insurance_name":    fields.get("ins_name"),
        "fields":            fields,
        "labels_not_found":  parsed["labels_not_found"],
    }


@app.post("/api/sabrina-compare")
async def sabrina_compare_endpoint(
    file: UploadFile = File(...),
    client: Optional[str] = Form(None),
    portal_data: Optional[str] = Form(None),
    portal_file: Optional[UploadFile] = File(None),
):
    """
    Audit a Sabrina breakdown PDF against the insurance portal.

    The portal side may arrive either as `portal_data` (a JSON string — the
    portal export, or the output of /api/parse-pdf) or as `portal_file` (a
    carrier PDF, parsed here). Returns per-field statuses plus a mismatch list.

    The audit is run by the folder of the carrier whose export this is
    (`sabrina/carriers/<carrier>/`), named in the result as `carrier`; an
    export from a portal with no folder is refused with a 422.
    """
    _key, spec = resolve_client(client, "sabrina_audit")
    audit = client_module(spec, "sabrina")

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="The Sabrina file must be a PDF")

    portal_raw = None
    if portal_data:
        try:
            portal_raw = json.loads(portal_data)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"portal_data is not valid JSON: {e}")
    elif portal_file is not None:
        if not (portal_file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="portal_file must be a PDF")
        try:
            portal_raw = await parse_insurance_pdf(await portal_file.read())
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if not portal_raw:
        raise HTTPException(
            status_code=400,
            detail="Provide the insurance portal export as portal_data (JSON) or portal_file (PDF).",
        )

    try:
        result = await audit.audit_sabrina_pdf(await file.read(), portal_raw)
        result["client"] = _key
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sabrina comparison failed: {e}")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Appointment cleansing (SOP Steps 2–5) ──────────────────────────────────────

@app.post("/api/appointments/process")
async def process_appointments_api(
    files: List[UploadFile] = File(...),
    commit: bool = Form(True),
):
    """
    Union one or more Denticon appointment reports, run the SOP cleansing steps
    (remove previously processed / invalid / duplicate / excluded-insurance),
    and return a per-step summary plus the cleaned workbook (base64).
    """
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one appointment report.")

    payload = []
    for f in files:
        name = f.filename or "report.xlsx"
        if not name.lower().endswith((".xlsx", ".xls", ".csv")):
            raise HTTPException(status_code=400, detail=f"'{name}' must be an .xlsx, .xls or .csv file.")
        payload.append((name, await f.read()))

    try:
        result = process_appointments(payload, commit=commit)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")

    return {
        "summary": result["summary"],
        "filename": f"cleaned_appointments_{datetime.now():%Y%m%d}.xlsx",
        "file_base64": base64.b64encode(result["xlsx_bytes"]).decode("ascii"),
    }


@app.post("/api/appointments/day-start-reports")
async def day_start_reports_api(files: List[UploadFile] = File(...)):
    """
    SOP Step 6 — Generate an office-wise Day Start Report from the cleaned data
    and return them bundled as a ZIP (one Excel per office). Read-only: does not
    commit to history.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one appointment report.")

    payload = []
    for f in files:
        name = f.filename or "report.xlsx"
        if not name.lower().endswith((".xlsx", ".xls", ".csv")):
            raise HTTPException(status_code=400, detail=f"'{name}' must be an .xlsx, .xls or .csv file.")
        payload.append((name, await f.read()))

    try:
        result = generate_day_start_reports(payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")

    return {
        "summary": result["summary"],
        "filename": f"day_start_reports_{datetime.now():%Y%m%d}.zip",
        "file_base64": base64.b64encode(result["zip_bytes"]).decode("ascii"),
    }


@app.get("/api/appointments/exclusions")
def get_exclusions():
    return {"exclusions": load_exclusions()}


@app.post("/api/appointments/exclusions")
def update_exclusions(req: ExclusionRequest):
    return {"exclusions": save_exclusions(req.exclusions)}


@app.get("/api/appointments/block-names")
def get_block_names():
    return {"block_names": load_block_names()}


@app.post("/api/appointments/block-names")
def update_block_names(req: BlockNamesRequest):
    return {"block_names": save_block_names(req.block_names)}


@app.get("/api/appointments/history")
def get_history():
    return history_info()


@app.post("/api/appointments/history/reset")
def clear_history():
    return reset_history()


# ── Step 6 Part B: email office reports via Outlook ─────────────────────────────

@app.get("/api/appointments/email-map")
def get_email_map():
    return load_email_map()


@app.post("/api/appointments/email-map/upload")
async def upload_email_map(file: UploadFile = File(...)):
    name = file.filename or "mapping.xlsx"
    if not name.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail=f"'{name}' must be an .xlsx, .xls or .csv file.")
    try:
        mapping = parse_email_map_upload(name, await file.read())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not parse mapping file: {e}")
    return {"office_count": len(mapping.get("mappings", {})), "default": mapping.get("default", [])}


@app.post("/api/appointments/email-reports")
async def email_reports_api(
    files: List[UploadFile] = File(...),
    mode: str = Form("draft"),
    sender: str = Form(""),
):
    """
    SOP Step 6 (Part B) — cleanse the uploaded report(s), build one Day Start Excel
    per office, and email each to its mapped recipients via desktop Outlook.
    mode='draft' opens drafts for review; mode='send' sends immediately.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one appointment report.")
    if mode not in ("draft", "send"):
        raise HTTPException(status_code=400, detail="mode must be 'draft' or 'send'.")

    payload = []
    for f in files:
        name = f.filename or "report.xlsx"
        if not name.lower().endswith((".xlsx", ".xls", ".csv")):
            raise HTTPException(status_code=400, detail=f"'{name}' must be an .xlsx, .xls or .csv file.")
        payload.append((name, await f.read()))

    try:
        built = build_office_reports(payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")

    try:
        # Outlook COM must run in a worker thread (its own CoInitialize), not on the
        # async event loop — offload it there.
        results = await run_in_threadpool(
            functools.partial(email_office_reports, built["reports"], mode=mode, sender=(sender or None))
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Outlook emailing failed: {e}. Make sure classic Outlook is open and signed in "
                   f"on the machine running the server.",
        )

    sent = sum(1 for r in results if r["ok"])
    return {
        "mode": mode,
        "office_count": len(results),
        "succeeded": sent,
        "failed": len(results) - sent,
        "results": results,
    }


@app.post("/api/new-plan")
def generate_new_plan(req: NewPlanRequest):
    """
    Generate and return an Insurance Plan Breakdown PDF.
    Accepts the full raw JSONs from both portals + optional UI overrides.
    """
    _key, spec = resolve_client(req.client, "new_plan")
    build_pdf = client_module(spec, "plan_pdf").generate_new_plan_pdf
    if not req.portal_data or not req.denticon_data:
        raise HTTPException(status_code=400, detail="Missing portal or denticon data")

    # Convert InsOverride pydantic model → plain dict (or None)
    override_dict = req.ins_override.dict() if req.ins_override else None

    # Derive a safe filename from the patient name
    patient_name = (
        req.portal_data
           .get('metlife_data', {})
           .get('patient', {})
           .get('name', 'NewPlan')
           .replace(' ', '_')
    )

    pdf_bytes = build_pdf(
        req.portal_data,
        req.denticon_data,
        ins_override=override_dict,   # ← insName, feeSchedule, relationship applied inside
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="Insurance_Plan_{patient_name}.pdf"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        }
    )

if __name__ == "__main__":
    # host="0.0.0.0" makes the server reachable from other machines on the LAN
    # (e.g. http://10.30.10.67:8000). Use 127.0.0.1 to restrict to this machine only.
    uvicorn.run(app, host="0.0.0.0", port=8000)