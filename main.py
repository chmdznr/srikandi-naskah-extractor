"""FastAPI app — async job pattern.

POST /jobs       → upload file, enqueue, return {job_id, status}
GET  /jobs/{id}  → poll status + result
GET  /health     → check Redis + worker availability
GET  /           → demo UI (drag-drop + poll)
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader

import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("extractor-app")

# --- API-key auth -------------------------------------------------------------
# Protect the public job endpoints. The key is read from the API_KEY env var at
# request time. When API_KEY is unset/empty, auth is DISABLED — convenient for
# local dev + the demo UI on MacBook, but it MUST be set on any public deploy.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

if not os.getenv("API_KEY", "").strip():
    log.warning("API_KEY not set — endpoint auth is DISABLED. Set API_KEY before exposing publicly.")


def require_api_key(provided: str | None = Security(_api_key_header)) -> None:
    expected = os.getenv("API_KEY", "").strip()
    if not expected:
        return  # auth disabled when no key configured
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

app = FastAPI(
    title="Srikandi Naskah Extractor",
    description="PoC: async extract DOCX/PDF naskah dinas via local Ollama LLM (RQ + Redis queue)",
    version="0.2.0",
)
# Restrict to the calling FE origin in production via ALLOWED_ORIGINS (comma-separated).
# Defaults to "*" so local dev / the demo UI keep working out of the box.
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    try:
        ping_ok = jobs.get_redis().ping()
    except Exception as e:
        return JSONResponse({"status": "degraded", "redis": False, "error": str(e)}, status_code=503)
    # Count workers listening on our queue
    from rq import Worker
    workers = Worker.all(connection=jobs.get_redis())
    worker_count = sum(1 for w in workers if jobs.QUEUE_NAME in [q.name for q in w.queues])
    queue = jobs.get_queue()
    return {
        "status": "ok" if (ping_ok and worker_count > 0) else "degraded",
        "redis": ping_ok,
        "workers_listening": worker_count,
        "queue_depth": queue.count,
        "queue": jobs.QUEUE_NAME,
    }


def _job_to_dict(job) -> dict:
    status = job.get_status(refresh=True)
    out = {
        "id": job.id,
        "status": status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        "result": None,
        "error": None,
    }
    if status == "finished":
        out["result"] = job.result
    elif status == "failed":
        # exc_info is full traceback string
        out["error"] = (job.exc_info or "").splitlines()[-1] if job.exc_info else "unknown failure"
    return out


@app.post("/jobs", status_code=202, dependencies=[Depends(require_api_key)])
async def enqueue_job(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Hanya .pdf / .docx didukung.")

    body = await file.read()
    if not body:
        raise HTTPException(400, "Empty upload")

    job = jobs.enqueue_extraction(body, file.filename or f"upload{suffix}")
    log.info(f"Enqueued job {job.id} for {file.filename} ({len(body)} bytes)")
    return _job_to_dict(job)


@app.get("/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def get_job(job_id: str):
    job = jobs.fetch_job(job_id)
    if job is None:
        # Job either never existed or expired past result_ttl
        raise HTTPException(404, f"Job {job_id} not found (mungkin sudah expired — default TTL 1h)")
    return _job_to_dict(job)
