"""
main.py
=======

FastAPI application exposing the File-to-Markdown conversion service.

Endpoints
---------
POST   /convert               Accept a multipart file upload OR JSON ``{"url": ...}``.
                              Returns a job id immediately; conversion runs in
                              a background thread.
GET    /convert/{id}/stream   Server-Sent Events stream of progress + final result.
GET    /convert/{id}          Fetch a completed job's result (for history reload).
GET    /convert/{id}/download Download the generated ``.md`` file.
GET    /health                Liveness probe.

The conversion engine (``converter.py``) is fully synchronous and CPU-bound, so
each job runs on its own daemon thread. Progress is pushed onto a thread-safe
queue that the SSE endpoint drains.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from converter import (
    MAX_FILE_SIZE_BYTES,
    ConversionError,
    FileKind,
    detect_kind,
    get_converter,
    output_filename,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Keep all transient files — including the intermediate images that pytesseract
# hands to the tesseract subprocess during PDF OCR — inside an app-owned
# directory. This guarantees child processes can always read them back,
# regardless of how the host configures TMPDIR (some sandboxes/containers point
# it at a location subprocesses cannot access).
import os  # noqa: E402
import tempfile  # noqa: E402

_TMP_DIR = BASE_DIR / ".tmp"
_TMP_DIR.mkdir(exist_ok=True)
os.environ["TMPDIR"] = str(_TMP_DIR)
tempfile.tempdir = str(_TMP_DIR)

# Stream uploads to disk in chunks so we never hold a huge file in memory.
_CHUNK_SIZE = 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# Pydantic API models
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class ConvertUrlRequest(BaseModel):
    url: str = Field(..., description="http(s) URL or YouTube link to convert")


class JobCreatedResponse(BaseModel):
    id: str
    source_name: str
    kind: str
    status: JobStatus


class ConversionResultResponse(BaseModel):
    id: str
    status: JobStatus
    source_name: str
    output_name: str
    kind: str
    markdown: str
    char_count: int


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str = "ok"
    max_file_size_mb: int = MAX_FILE_SIZE_BYTES // (1024 * 1024)


# ---------------------------------------------------------------------------
# Job registry (in-memory, per process)
# ---------------------------------------------------------------------------


@dataclass
class Job:
    id: str
    source_name: str
    kind: FileKind
    status: JobStatus = JobStatus.PENDING
    events: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    markdown: Optional[str] = None
    output_name: Optional[str] = None
    output_path: Optional[Path] = None
    char_count: int = 0
    error: Optional[str] = None


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _register_job(source_name: str, kind: FileKind) -> Job:
    job = Job(id=uuid.uuid4().hex, source_name=source_name, kind=kind)
    with _jobs_lock:
        _jobs[job.id] = job
    return job


def _get_job(job_id: str) -> Optional[Job]:
    with _jobs_lock:
        return _jobs.get(job_id)


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------


def _make_progress(job: Job):
    def progress(percent: int, message: str) -> None:
        job.events.put(
            {"event": "progress", "percent": max(0, min(100, percent)), "message": message}
        )

    return progress


def _finalize_success(job: Job, result) -> None:
    out_path = OUTPUT_DIR / f"{job.id}-{result.output_name}"
    out_path.write_text(result.markdown, encoding="utf-8")

    job.markdown = result.markdown
    job.output_name = result.output_name
    job.output_path = out_path
    job.char_count = result.char_count
    job.status = JobStatus.DONE

    job.events.put(
        {
            "event": "result",
            "id": job.id,
            "source_name": result.source_name,
            "output_name": result.output_name,
            "kind": result.kind.value,
            "markdown": result.markdown,
            "char_count": result.char_count,
        }
    )
    job.events.put({"event": "done"})


def _finalize_error(job: Job, message: str) -> None:
    job.status = JobStatus.ERROR
    job.error = message
    job.events.put({"event": "error", "message": message})
    job.events.put({"event": "done"})


def _run_file_job(job: Job, file_path: Path) -> None:
    job.status = JobStatus.RUNNING
    progress = _make_progress(job)
    try:
        converter = get_converter()
        result = converter.convert_path(
            file_path, original_name=job.source_name, progress=progress
        )
        _finalize_success(job, result)
    except ConversionError as exc:
        _finalize_error(job, exc.message)
    except Exception as exc:  # noqa: BLE001 - never leak a raw traceback to SSE
        _finalize_error(job, f"Unexpected error: {exc}")
    finally:
        # Clean up the temporary upload regardless of outcome.
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass


def _run_url_job(job: Job, url: str) -> None:
    job.status = JobStatus.RUNNING
    progress = _make_progress(job)
    try:
        converter = get_converter()
        result = converter.convert_url(url, progress=progress)
        _finalize_success(job, result)
    except ConversionError as exc:
        _finalize_error(job, exc.message)
    except Exception as exc:  # noqa: BLE001
        _finalize_error(job, f"Unexpected error: {exc}")


def _spawn(target, *args) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="File-to-Markdown Converter",
    description="Convert any file or URL into clean Markdown using MarkItDown.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev convenience; tighten for production deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post(
    "/convert",
    response_model=JobCreatedResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
)
async def convert(request: Request):
    """Create a conversion job from a file upload or a URL.

    Branches on ``Content-Type``: JSON bodies are treated as URL conversions,
    everything else is parsed as multipart form data carrying a ``file`` (and/or
    an optional ``url`` field).
    """

    content_type = request.headers.get("content-type", "")

    # ---- URL via JSON -------------------------------------------------
    if content_type.startswith("application/json"):
        try:
            payload = ConvertUrlRequest(**await request.json())
        except Exception:
            return _error(400, "Invalid JSON body. Expected {\"url\": \"...\"}.")
        return _start_url_job(payload.url)

    # ---- multipart form ----------------------------------------------
    try:
        form = await request.form()
    except Exception:
        return _error(400, "Could not parse multipart form data.")

    url_field = form.get("url")
    if isinstance(url_field, str) and url_field.strip():
        return _start_url_job(url_field.strip())

    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename"):
        return _error(400, "No file or url provided.")

    filename = upload.filename or "upload"
    if detect_kind(filename) == FileKind.UNKNOWN:
        return _error(400, f"Unsupported file type: {Path(filename).suffix or 'none'}")

    # Stream to disk, enforcing the size limit as we go.
    job = _register_job(source_name=filename, kind=detect_kind(filename))
    dest = UPLOAD_DIR / f"{job.id}-{Path(filename).name}"
    written = 0
    try:
        with dest.open("wb") as buffer:
            while chunk := await upload.read(_CHUNK_SIZE):
                written += len(chunk)
                if written > MAX_FILE_SIZE_BYTES:
                    buffer.close()
                    dest.unlink(missing_ok=True)
                    with _jobs_lock:
                        _jobs.pop(job.id, None)
                    return _error(
                        413,
                        f"File exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB limit.",
                    )
                buffer.write(chunk)
    finally:
        await upload.close()

    if written == 0:
        dest.unlink(missing_ok=True)
        with _jobs_lock:
            _jobs.pop(job.id, None)
        return _error(400, "Uploaded file is empty.")

    _spawn(_run_file_job, job, dest)
    return JobCreatedResponse(
        id=job.id, source_name=job.source_name, kind=job.kind.value, status=job.status
    )


def _start_url_job(url: str) -> JSONResponse | JobCreatedResponse:
    if not url.lower().startswith(("http://", "https://")):
        return _error(400, "URL must start with http:// or https://")
    job = _register_job(source_name=url, kind=FileKind.URL)
    _spawn(_run_url_job, job, url)
    return JobCreatedResponse(
        id=job.id, source_name=job.source_name, kind=job.kind.value, status=job.status
    )


@app.get("/convert/{job_id}/stream")
async def stream(job_id: str):
    """Stream conversion progress for a job as Server-Sent Events."""

    job = _get_job(job_id)
    if job is None:
        return _error(404, "Job not found.")

    async def event_generator():
        # Replay any events already queued, then keep draining until "done".
        while True:
            try:
                event = job.events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.15)
                continue
            yield _sse(event)
            if event.get("event") == "done":
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )


@app.get(
    "/convert/{job_id}",
    response_model=ConversionResultResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def get_result(job_id: str):
    """Return a completed job's result (used to reload from history)."""

    job = _get_job(job_id)
    if job is None:
        return _error(404, "Job not found.")
    if job.status == JobStatus.ERROR:
        return _error(409, job.error or "Conversion failed.")
    if job.status != JobStatus.DONE or job.markdown is None:
        return _error(409, "Conversion is still in progress.")
    return ConversionResultResponse(
        id=job.id,
        status=job.status,
        source_name=job.source_name,
        output_name=job.output_name or output_filename(job.source_name),
        kind=job.kind.value,
        markdown=job.markdown,
        char_count=job.char_count,
    )


@app.get("/convert/{job_id}/download")
async def download(job_id: str):
    """Download the generated markdown file, named after the original."""

    job = _get_job(job_id)
    if job is None:
        return _error(404, "Job not found.")
    if job.status != JobStatus.DONE or job.output_path is None:
        return _error(409, "Result is not ready for download.")
    if not job.output_path.exists():
        return _error(410, "Output file is no longer available.")
    return FileResponse(
        path=job.output_path,
        media_type="text/markdown",
        filename=job.output_name or "converted.md",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse(data: dict[str, Any]) -> str:
    """Serialize a dict as a single SSE message."""

    return f"data: {json.dumps(data)}\n\n"


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
