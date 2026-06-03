from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from app.services.github import fetch_github_evidence, parse_github_username
from app.services.job_search import discover_safe_jobs
from app.services.linkedin_cleaner import clean_linkedin_profile_text
from app.services.matching import analyze_resume
from app.services.parsing import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    UnsupportedUpload,
    UploadTooLarge,
    parse_resume_upload,
)
from app.services.target_jobs import resolve_target_input
from app.services.rate_limit import RateLimiter
from app.services.session import attach_session, get_session, install_session_middleware
from app.services.storage import (
    DEFAULT_DB_PATH,
    init_database,
    list_analyses,
    persist_analysis,
)
from app.services.tailoring import generate_tailored_rewrites
from app.services.exporters import analysis_to_markdown, tailored_cv_to_docx
from app.services.encryption import EncryptionService
from app.services.llm_client import describe_llm_status

log = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

app = FastAPI(title="CV-Job Match Agent")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

encryption = EncryptionService(DATA_DIR / ".fernet_key")
install_session_middleware(app, DATA_DIR / ".session_secret")
init_database(DEFAULT_DB_PATH)

analyze_limiter = RateLimiter(max_requests=12, window_seconds=60)


@app.get("/healthz", response_class=JSONResponse)
async def healthz() -> JSONResponse:
    """Cheap liveness probe. Does not touch external systems."""
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    session = attach_session(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "analysis": None,
            "history": list_analyses(session["user_id"], limit=20),
            "session": session,
        },
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    resume: Annotated[UploadFile | None, File()] = None,
    target_text: Annotated[str, Form()] = "",
    github_url: Annotated[str, Form()] = "",
    linkedin_url: Annotated[str, Form()] = "",
    linkedin_text: Annotated[str, Form()] = "",
    use_llm: Annotated[str, Form()] = "",
) -> HTMLResponse:
    session = attach_session(request)

    client_ip = request.client.host if request.client else "anonymous"
    rate_key = f"analyze:{session['user_id']}:{client_ip}"
    if not analyze_limiter.allow(rate_key):
        raise HTTPException(status_code=429, detail="Too many analyses. Wait a minute and retry.")

    try:
        parsed_resume = await parse_resume_upload(resume)
    except UploadTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail=f"CV upload is {exc.size:,} bytes; limit is {exc.limit:,} bytes.",
        ) from exc
    except UnsupportedUpload as exc:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported extension '.{exc.suffix}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}.",
        ) from exc

    target_resolution = resolve_target_input(target_text)
    job_discovery = discover_safe_jobs(target_text)
    cleaned_linkedin = clean_linkedin_profile_text(linkedin_text)

    github_username = parse_github_username(github_url)
    github_evidence = fetch_github_evidence(github_username) if github_username else None

    llm_enabled = use_llm.lower() in {"on", "true", "1", "yes"}
    llm_status = describe_llm_status()
    llm_tile = (f"LLM ({llm_status.provider})", llm_status.status, llm_status.detail)

    analysis = analyze_resume(
        resume_text=parsed_resume.text,
        target_text=target_resolution.text,
        github_evidence=github_evidence,
        linkedin_url=linkedin_url,
        linkedin_text=cleaned_linkedin.text,
        resume_uploaded=bool(parsed_resume.filename),
        resume_filename=parsed_resume.filename,
        parse_warnings=[*parsed_resume.warnings, *target_resolution.warnings, *job_discovery.warnings],
        target_statuses=[
            *[(status.name, status.status, status.detail)
              for status in [*target_resolution.statuses, *job_discovery.statuses]],
            llm_tile,
        ],
        linkedin_cleaning_detail=cleaned_linkedin.status_detail if linkedin_text.strip() else "",
        job_postings=job_discovery.jobs,
    )

    rewrites = (
        generate_tailored_rewrites(analysis, parsed_resume.text)
        if llm_enabled and parsed_resume.text
        else []
    )

    persisted_id = persist_analysis(
        user_id=session["user_id"],
        analysis=analysis,
        resume_text=parsed_resume.text,
        encryptor=encryption,
        rewrites=rewrites,
    )

    return templates.TemplateResponse(
        request,
        "_analysis.html",
        {
            "analysis": analysis,
            "rewrites": rewrites,
            "analysis_id": persisted_id,
            "llm_enabled": llm_enabled,
            "session": session,
        },
    )


@app.post("/applications", response_class=HTMLResponse)
async def queue_application(
    request: Request,
    analysis_id: Annotated[int, Form()],
    job_url: Annotated[str, Form()],
    company: Annotated[str, Form()],
    title: Annotated[str, Form()],
) -> HTMLResponse:
    from app.services.storage import create_application, list_applications

    session = attach_session(request)
    record = _load_owned_analysis(session, analysis_id)
    create_application(
        user_id=session["user_id"],
        analysis_id=record.id,
        job_url=job_url.strip(),
        company=company.strip(),
        title=title.strip(),
        status="manual_confirmation_required",
        note="Created via dashboard. Auto-apply remains off.",
    )
    return templates.TemplateResponse(
        request,
        "_applications.html",
        {"applications": list_applications(session["user_id"])},
    )


@app.post("/applications/{application_id}/status", response_class=HTMLResponse)
async def update_application(
    request: Request,
    application_id: int,
    status: Annotated[str, Form()],
    note: Annotated[str, Form()] = "",
) -> HTMLResponse:
    from app.services.storage import VALID_APPLICATION_STATUSES, list_applications, update_application_status

    session = attach_session(request)
    if status not in VALID_APPLICATION_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status.")

    update_application_status(application_id, status, note.strip())
    return templates.TemplateResponse(
        request,
        "_applications.html",
        {"applications": list_applications(session["user_id"])},
    )


@app.get("/applications", response_class=HTMLResponse)
async def get_applications(request: Request) -> HTMLResponse:
    from app.services.storage import list_applications

    session = attach_session(request)
    return templates.TemplateResponse(
        request,
        "_applications.html",
        {"applications": list_applications(session["user_id"])},
    )


@app.post("/account/delete", response_class=JSONResponse)
async def delete_account(request: Request) -> JSONResponse:
    """Hard-delete every analysis + application tied to this session.

    Required by Rule 14: right-to-delete must physically remove rows.
    """
    from app.services.storage import delete_user_data

    session = attach_session(request)
    deleted = delete_user_data(session["user_id"])
    session.clear()
    return JSONResponse({"deleted_analyses": deleted})


@app.get("/exports/{analysis_id}/markdown", response_class=PlainTextResponse)
async def export_markdown(request: Request, analysis_id: int) -> PlainTextResponse:
    session = attach_session(request)
    record = _load_owned_analysis(session, analysis_id)
    text = analysis_to_markdown(record)
    return PlainTextResponse(
        text,
        headers={
            "Content-Disposition": f'attachment; filename="cv-gap-report-{analysis_id}.md"',
            "Content-Type": "text/markdown; charset=utf-8",
        },
    )


@app.get("/exports/{analysis_id}/docx")
async def export_docx(request: Request, analysis_id: int) -> Response:
    session = attach_session(request)
    record = _load_owned_analysis(session, analysis_id)
    payload = tailored_cv_to_docx(record, encryption)
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="tailored-cv-{analysis_id}.docx"',
        },
    )


def _load_owned_analysis(session: dict, analysis_id: int):
    from app.services.storage import get_analysis  # local to avoid cycles

    record = get_analysis(analysis_id)
    owner = session.get("user_id") if isinstance(session, dict) else None
    if record is None or not owner or record.user_id != owner:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return record
