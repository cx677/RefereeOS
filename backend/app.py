from __future__ import annotations

from typing import Annotated

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
    load_dotenv(".env.local", override=True)
    load_dotenv(".local.env", override=True)
except Exception:
    pass

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from backend.agents.orchestrator import analyze_fixture, analyze_text
from backend.parsing.paper_parser import extract_pdf_text, list_fixtures, load_fixture_text
from backend.storage.evidence_board import run_store


async def _get_paper_text(
    file: UploadFile | None,
    fixture_id: str,
    field_domain: str | None,
    custom_artifact: dict | None,
) -> tuple[str, str, dict]:
    """Extract paper text, source label, and fixture_meta from request inputs."""
    if file and file.filename:
        if file.content_type == "application/pdf" or file.filename.lower().endswith(".pdf"):
            text = extract_pdf_text(file.file)
        else:
            text = (await file.read()).decode("utf-8", errors="ignore")
        _, fixture_meta = load_fixture_text("clean")
        fixture_meta["fixture_id"] = "uploaded"
        source = f"uploaded_file:{file.filename}"
    elif custom_artifact:
        text, fixture_meta = load_fixture_text(fixture_id)
        fixture_meta.update(custom_artifact)
        source = f"sample_fixture:{fixture_meta['fixture_id']}:custom_repro_artifact"
    else:
        text, fixture_meta = load_fixture_text(fixture_id)
        source = f"sample_fixture:{fixture_meta['fixture_id']}"

    if custom_artifact:
        fixture_meta.update(custom_artifact)
    return text, source, fixture_meta


app = FastAPI(
    title="RefereeOS API",
    description="AG2 + Daytona multi-agent preprint triage and reproducibility assistant.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "RefereeOS"}


@app.get("/api/fixtures")
def fixtures() -> dict:
    return {"fixtures": list_fixtures()}


@app.post("/api/analyze")
async def analyze(
    fixture_id: Annotated[str, Form()] = "clean",
    field_domain: Annotated[str | None, Form()] = None,
    reported_result: Annotated[float | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
    artifact_file: Annotated[UploadFile | None, File()] = None,
    script_file: Annotated[UploadFile | None, File()] = None,
) -> dict:
    custom_artifact = await _read_custom_artifact(artifact_file, script_file, reported_result)
    text, source, fixture_meta = await _get_paper_text(file, fixture_id, field_domain, custom_artifact)
    board = analyze_text(text, source=source, fixture_meta=fixture_meta, field_domain=field_domain)
    run = run_store.create(board)
    return run


@app.post("/api/analyze/beta")
async def analyze_beta(
    fixture_id: Annotated[str, Form()] = "clean",
    field_domain: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> dict:
    """Run the full 3-agent AG2 Beta pipeline (claim_extractor + method_critic + area_chair)."""
    import asyncio

    try:
        from ag2_reviewer import review_paper
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="ag2_reviewer module not available. Ensure ag2[openai] is installed.",
        )

    text, source, fixture_meta = await _get_paper_text(file, fixture_id, field_domain, None)
    try:
        board = await review_paper(text, source=source, fixture_meta=fixture_meta)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Beta pipeline failed: {exc}")

    run = run_store.create(board)
    return run


async def _read_custom_artifact(
    artifact_file: UploadFile | None,
    script_file: UploadFile | None,
    reported_result: float | None,
) -> dict | None:
    provided = [bool(artifact_file and artifact_file.filename), bool(script_file and script_file.filename), reported_result is not None]
    if not any(provided):
        return None
    if not all(provided):
        raise HTTPException(
            status_code=400,
            detail="Custom reproducibility needs a CSV artifact, Python script, and reported result.",
        )

    assert artifact_file is not None
    assert script_file is not None
    artifact_text = (await artifact_file.read()).decode("utf-8", errors="ignore")
    script_text = (await script_file.read()).decode("utf-8", errors="ignore")
    if "macro_f1" not in script_text and "metric" not in script_text and "observed_result" not in script_text:
        raise HTTPException(
            status_code=400,
            detail="Metric script should print macro_f1=<number>, metric=<number>, or observed_result=<number>.",
        )

    return {
        "fixture_id": "uploaded_custom",
        "reported_result": reported_result,
        "results_csv_text": artifact_text,
        "metric_script_text": script_text,
        "custom_artifact": True,
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = run_store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/api/runs/{run_id}/evidence-board")
def get_evidence_board(run_id: str) -> dict:
    run = run_store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run["board"]


@app.get("/api/runs/{run_id}/packet", response_class=PlainTextResponse)
def get_packet(run_id: str) -> str:
    run = run_store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run["packet"]
