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
from shared import scrape_store
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
        "package":  "sabrina.smile_partners",
        "hint":     "Portal export + Sabrina breakdown PDF",
        # sabrina_prefill: its Fill Form's field names are mapped in
        # sabrina/smile_partners/prefill.py. Other Sabrina clients get it once
        # their own form is mapped.
        "supports": {"sabrina_audit", "parse_pdf", "sabrina_prefill"},
        "sabrina_client_id": 26,
    },
    "star_dental": {
        "label":    "Star Dental",
        "system":   "Sabrina",
        "package":  "sabrina.star_dental",
        "hint":     "Portal export + Sabrina breakdown PDF",
        # sabrina_prefill: sabrina/star_dental/prefill.py (11/26).
        "supports": {"sabrina_audit", "parse_pdf", "sabrina_prefill"},
        "sabrina_client_id": 19,
    },
    "jefferson": {
        "label":    "Jefferson",
        "system":   "Sabrina",
        "package":  "sabrina.jefferson",
        "hint":     "Portal export + Sabrina breakdown PDF",
        "supports": {"sabrina_audit", "parse_pdf"},
    },
    "park_dental": {
        "label":    "Park Dental",
        "system":   "Sabrina",
        "package":  "sabrina.park_dental",
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
    "sabrina_prefill": "Sabrina Fill Form prefill",
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


# Sabrina's own client numbers (ClientID), as the business team listed them
# 11/26. A Fill Form states its ClientID; the client entry above with that
# `sabrina_client_id` fills it. The rest are named here only so the panel can
# say whose form it is when that client is not set up for filling yet.
SABRINA_CLIENT_NAMES = {
    2: "Absolute Dental", 3: "Kidscare Dental", 7: "Affinity", 10: "Plum Dental",
    11: "Jefferson Dental & Orthodontics", 12: "Marquee Dental", 15: "Beacon Dental",
    16: "Pearl Street Dental Partners", 17: "Riccobene Brush and Floss", 18: "Dentologie",
    19: "Star Dental", 20: "Chord SDP", 21: "Henritze Dental Group", 23: "Eastern Dental",
    24: "Willis Dentistry", 26: "Smile Partners", 27: "Park Place Dental",
}


def client_for_sabrina_id(sabrina_client_id):
    """
    Our client key for a Fill Form's Sabrina ClientID (19 → star_dental).
    Raises 400 for a ClientID no client here fills.
    """
    try:
        cid = int(str(sabrina_client_id).strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown Sabrina ClientID {sabrina_client_id!r}.")
    for key, spec in CLIENTS.items():
        if spec.get("sabrina_client_id") == cid:
            return key
    name = SABRINA_CLIENT_NAMES.get(cid)
    raise HTTPException(
        status_code=400,
        detail=(f"Fill from portal is not set up for {name} (Sabrina ClientID {cid}) yet."
                if name else f"Unknown Sabrina ClientID {cid}."))


def client_module(spec, dotted=""):
    """
    A module inside a client's package, imported by name; the package itself
    when `dotted` is empty. Sabrina clients' packages are sabrina/<client>/.
    """
    from importlib import import_module
    return import_module(f"{spec['package']}.{dotted}" if dotted else spec["package"])


def client_portal_pdf(client, pdf_bytes):
    """
    A carrier PDF read by the client's own reader (`read_portal_pdf` in its
    sabrina/<client>/ package), or None to leave it to the shared parser — no
    client named, a client without a reader (DCA is not a Sabrina client), or
    a PDF its reader does not take.
    """
    if not client:
        return None
    try:
        _key, spec = resolve_client(client, "parse_pdf")
        if spec["system"] != "Sabrina":
            return None
        reader = getattr(client_module(spec), "read_portal_pdf", None)
    except (HTTPException, ImportError):
        return None
    if reader is None:
        return None
    try:
        return reader(pdf_bytes)
    except Exception as e:      # an unreadable PDF falls back to the shared parser
        print(f"[parse-pdf] {spec['label']} reader failed, using the shared parser: {e}")
        return None


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
async def parse_pdf_endpoint(file: UploadFile = File(...), client: Optional[str] = Form(None)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF")
    pdf_bytes = await file.read()

    # A client may read some carriers' PDFs itself (Smile Partners: Guardian).
    own = await run_in_threadpool(client_portal_pdf, client, pdf_bytes)
    if own:
        return own

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
    audit = client_module(spec)

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
    (`sabrina/<client>/carriers/<carrier>/`), named in the result as `carrier`; an
    export from a portal with no folder is refused with a 422.
    """
    _key, spec = resolve_client(client, "sabrina_audit")
    audit = client_module(spec)

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
        portal_pdf = await portal_file.read()
        portal_raw = await run_in_threadpool(client_portal_pdf, _key, portal_pdf)
        if not portal_raw:
            try:
                portal_raw = await parse_insurance_pdf(portal_pdf)
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


# ── Sabrina Fill Form prefill ─────────────────────────────────────────────────
#
# The extension posts each portal scrape here instead of downloading it
# (/api/scrapes). On the patient's Fill Form, once the user picks IN OR OON, it
# asks for that member's scrape (/api/prefill), fills the form, and marks the
# scrape used. The values come from the same portal readers as the audit
# (`<client>/sabrina/prefill.py`), so every audit rule applies to the fill too.

class ScrapeRequest(BaseModel):
    client:      str
    portal_data: dict

class PrefillRequest(BaseModel):
    client:      str
    network:     str = ""       # "In" / "Out" as picked on the Fill Form; "" for a Cigna scrape
    portal_data: dict


def _prefill_module(client):
    """(key, the client's prefill module), refusing a client without one."""
    key, spec = resolve_client(client, "sabrina_prefill")
    return key, client_module(spec, "prefill")


@app.post("/api/scrapes")
def save_scrape(req: ScrapeRequest):
    """
    Store a portal scrape until the user opens that patient's Fill Form.

    Refused (422) for a portal with no Sabrina rules, or an export that states
    neither the member ID nor the patient's DOB the Fill Form is matched on.
    Some portals give no usable member ID (Guardian has none, the Toolkit not
    always, MetLife masks it); those are matched on the DOB.
    """
    key, prefill = _prefill_module(req.client)
    try:
        carrier, _values, _spec = prefill.portal_values(req.portal_data, "In")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    member_id, dob = prefill.member_key(req.portal_data)
    if not member_id and not dob:
        raise HTTPException(
            status_code=422,
            detail="This portal export states neither a member ID nor a DOB, so it cannot be "
                   "matched to a Fill Form.")
    scrape_id = scrape_store.save(key, carrier, member_id, dob, req.portal_data)
    return {"id": scrape_id, "client": key, "carrier": carrier,
            "member_id": scrape_store.norm_member(member_id), "dob": dob}


def _other_browser_scrape(key: Optional[str], member_id: str, dob: Optional[str]) -> Optional[dict]:
    """
    A scrape made in another browser for this patient: the portal scraped in
    Firefox, the Fill Form open in Edge. Strict, because nothing ties it to
    this user: the member ID and the DOB must both be stated and agree (family
    members share a member ID), and it must be recent and still pending.
    """
    form_dob = scrape_store.norm_dob(dob)
    if not scrape_store.norm_member(member_id) or not form_dob:
        return None
    found = scrape_store.find_pending(key, member_id, form_dob,
                                      max_age_minutes=scrape_store.OTHER_BROWSER_MINUTES)
    return found if found and found["dob"] == form_dob else None


@app.get("/api/prefill")
def get_prefill(member_id: str, client: str = "", network: str = "", dob: Optional[str] = None,
                scrape_id: Optional[int] = None, only_own: bool = False,
                sabrina_client_id: Optional[str] = None):
    """
    What to fill on the Fill Form for this member and network.

    Whose form it is: `sabrina_client_id`, the ClientID the Fill Form states
    (19 Star Dental, 26 Smile Partners), when the extension found one;
    otherwise `client`, the extension's setting. That client's prefill module
    turns the scrape into its form's fields. A scrape is not tied to a client:
    it is taken on the carrier portal before anyone knows which client's form
    it will fill, so any client's form may use it.

    `member_id` and `dob` are read off the Fill Form (MEMBER#, PATIENT DOB);
    `network` is the user's IN OR OON pick; it may be empty for a portal whose
    scrape states its own network (Cigna). `scrape_id` is the scrape this
    user's extension made last: used first, when it is for the same member, so
    a portal that words the member ID differently still finds it.

    `only_own` (what the extension sends): fill from that scrape — never from
    an older scrape of the same member left on the server, which could be
    hours old and was not what the user just looked at. One exception: the
    portal scraped in another browser (Firefox) while the Fill Form is open in
    this one (Edge). This browser then has no matching scrape of its own, and
    the newest pending scrape with the same member ID and DOB made in the last
    SCRAPE_OTHER_BROWSER_MINUTES (60) fills the form.

    404 when there is nothing to fill from, 409 when the user's own last scrape
    is for someone else (including a family member on the same member ID with
    another DOB), 422 when the network is missing or the scrape cannot be read.
    """
    if sabrina_client_id not in (None, ""):
        client = client_for_sabrina_id(sabrina_client_id)
    key, prefill = _prefill_module(client)
    # Scrapes are looked up for any client (see above): ANY_CLIENT.
    store = scrape_store.ANY_CLIENT
    scrape = None
    own = scrape_store.get_pending(store, scrape_id) if scrape_id else None
    family_member = False
    if own:
        # A portal with no member ID (Guardian, some Toolkit and MetLife
        # exports) is matched on the DOB alone: two blanks are not a match.
        same_member = bool(own["member_id"]) and own["member_id"] == scrape_store.norm_member(member_id)
        form_dob = scrape_store.norm_dob(dob)
        dob_known = bool(form_dob and own["dob"])
        same_dob = dob_known and own["dob"] == form_dob
        # Family members often share the subscriber's member ID (Delta, Cigna,
        # MetLife): when the form and the scrape both state a DOB, it decides.
        family_member = same_member and dob_known and not same_dob
        if same_dob or (same_member and not dob_known):
            # A member ID worded differently (SSN vs W-number) is allowed when
            # the DOB agrees; the extension still shows the patient check.
            scrape = own
    if not scrape and not only_own:
        scrape = scrape_store.find_pending(store, member_id, dob)
    if not scrape and only_own:
        scrape = _other_browser_scrape(store, member_id, dob)
    if not scrape and own:
        detail = (f"Your last portal scrape is for member {own['member_id']} "
                  f"(DOB {own['dob'] or 'not stated'}), not this patient.")
        if family_member:
            detail = (f"Your last portal scrape is for member {own['member_id']} born "
                      f"{own['dob']}, but this form's patient was born {form_dob}: another "
                      f"family member on the same member ID.")
        raise HTTPException(status_code=409,
                            detail=detail + " Scrape this patient on the portal first.")
    if not scrape and only_own:
        raise HTTPException(
            status_code=404,
            detail="No portal scrape for this patient from this browser, nor from another "
                   f"browser in the last {scrape_store.OTHER_BROWSER_MINUTES} minutes (same "
                   "MEMBER# and PATIENT DOB). Run the extension on the carrier portal for "
                   "this patient first.")
    if not scrape:
        raise HTTPException(
            status_code=404,
            detail="No portal data for this member yet. Run the extension on the "
                   "carrier portal for this patient first.")
    try:
        result = prefill.build_prefill(scrape["data"], network)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result.update({"client": key, "client_label": CLIENTS[key]["label"],
                   "sabrina_client_id": CLIENTS[key].get("sabrina_client_id"),
                   "scrape_id": scrape["id"], "scraped_at": scrape["scraped_at"]})
    return result


@app.post("/api/scrapes/{scrape_id}/used")
def mark_scrape_used(scrape_id: int):
    """Mark a scrape filled, so a later appointment never reuses it."""
    if not scrape_store.mark_used(scrape_id):
        raise HTTPException(status_code=404, detail=f"No scrape {scrape_id}")
    return {"id": scrape_id, "status": "used"}


@app.post("/api/sabrina-prefill")
def sabrina_prefill(req: PrefillRequest):
    """
    The same prefill for a portal export sent directly, without storing it.
    For testing a carrier's mapping from /docs.
    """
    _key, prefill = _prefill_module(req.client)
    try:
        return prefill.build_prefill(req.portal_data, req.network)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


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