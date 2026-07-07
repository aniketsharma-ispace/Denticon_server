# # from fastapi import FastAPI, HTTPException
# # from fastapi.middleware.cors import CORSMiddleware
# # from pydantic import BaseModel
# # import uvicorn

# # from compare_patients import trim_patient_data, ask_ollama

# # app = FastAPI(title="AI Insurance Matcher")

# # # Allow the HTML UI to talk to this API
# # app.add_middleware(
# #     CORSMiddleware,
# #     allow_origins=["*"],

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from new_plan import generate_new_plan_pdf
import uvicorn

from compare_patients import trim_patient_data, ask_ollama
from patient_notes import build_patient_notes

from fastapi.responses import Response
from fastapi import FastAPI, HTTPException, UploadFile, File
from pdf_extractor import parse_insurance_pdf

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

class NotesRequest(BaseModel):
    denticon_data: dict
    insurance_data: dict

class PDFRequest(BaseModel):
    portal_data: dict
    denticon_data: dict

class InsOverride(BaseModel):
    insName:      Optional[str] = None
    feeSchedule:  Optional[str] = None
    relationship: Optional[str] = None

class NewPlanRequest(BaseModel):
    portal_data:   dict
    denticon_data: dict
    ins_override:  Optional[InsOverride] = None   # ← carries modal values


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/match")
async def match_patient_plan(req: MatchRequest):
    if not req.portal_data or not req.denticon_data:
        raise HTTPException(status_code=400, detail="Missing portal or denticon data")

    print("Trimming data for AI analysis...")
    portal, denticon_list = trim_patient_data(req.portal_data, req.denticon_data)

    print(f"Comparing 1 Portal record against {len(denticon_list)} Denticon records...")
    result = ask_ollama(portal, denticon_list)
    return result


@app.post("/api/patient-notes")
def generate_notes(req: NotesRequest):
    if not req.denticon_data or not req.insurance_data:
        raise HTTPException(status_code=400, detail="Missing denticon or insurance data")

    result = build_patient_notes(req.denticon_data, req.insurance_data)
    return result

@app.post("/api/generate-new-plan-pdf")
async def generate_new_plan_pdf_api(req: PDFRequest):

    if not req.portal_data or not req.denticon_data:
        raise HTTPException(
            status_code=400,
            detail="Missing portal or denticon data"
        )

    pdf_bytes = generate_new_plan_pdf(
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
    
@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/new-plan")
def generate_new_plan(req: NewPlanRequest):
    """
    Generate and return an Insurance Plan Breakdown PDF.
    Accepts the full raw JSONs from both portals + optional UI overrides.
    """
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

    pdf_bytes = generate_new_plan_pdf(
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
    # Run server on port 8000
    uvicorn.run(app, host="127.0.0.1", port=8000)