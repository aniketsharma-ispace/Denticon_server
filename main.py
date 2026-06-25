import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from compare_patients import match_insurance_plan, close_http_client
from patient_notes import build_patient_notes
from pdf_extractor import parse_insurance_pdf

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# Serve the static UI files relative to THIS file, not the current working
# directory — so the server works no matter where it is launched from.
BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("AI Insurance Matcher starting up.")
    yield
    # Cleanly release the shared Ollama HTTP connection pool on shutdown.
    await close_http_client()
    log.info("AI Insurance Matcher shut down.")


app = FastAPI(title="AI Insurance Matcher", lifespan=lifespan)

# Allow the HTML UI / browser extension to talk to this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def serve_frontend() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/styles.css")
async def serve_css() -> FileResponse:
    return FileResponse(BASE_DIR / "styles.css", media_type="text/css")


@app.get("/match.js")
async def serve_js() -> FileResponse:
    return FileResponse(BASE_DIR / "match.js", media_type="application/javascript")


class MatchRequest(BaseModel):
    portal_data: dict
    denticon_data: dict


class NotesRequest(BaseModel):
    insurance_data: dict
    denticon_data: dict


@app.post("/api/match")
async def match_patient_plan(req: MatchRequest) -> dict:
    if not req.portal_data or not req.denticon_data:
        raise HTTPException(status_code=400, detail="Missing portal or denticon data")

    log.info("Step 1: Running Python pre-filter to shortlist candidates...")
    log.info("Step 2: Sending shortlisted plans to AI for deep matching...")

    result = await match_insurance_plan(req.portal_data, req.denticon_data)

    if not result.get("match_found"):
        log.info("No match found. Reason: %s", result.get("reason"))
    else:
        log.info(
            "Match found: %s (confidence: %s%%)",
            result.get("matching_id"),
            result.get("confidence_score"),
        )

    return result


@app.post("/api/patient-notes")
async def generate_patient_notes(req: NotesRequest) -> dict:
    if not req.insurance_data or not req.denticon_data:
        raise HTTPException(status_code=400, detail="Missing insurance or denticon data")

    return build_patient_notes(req.denticon_data, req.insurance_data)


@app.post("/api/parse-pdf")
async def parse_pdf(file: UploadFile = File(...)) -> dict:
    try:
        content = await file.read()
        return await parse_insurance_pdf(content)
    except Exception as e:
        # Log the full error server-side; surface a clean message to the client.
        log.exception("Failed to parse uploaded PDF '%s'", file.filename)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
