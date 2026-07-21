"""KYC Verifier — FastAPI backend.

Serves a single-page frontend and a JSON API for managing customers/entities,
their documents, and OpenAI-vision KYC verification runs.
"""
import json
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pymupdf
from fastapi import (FastAPI, File, Form, HTTPException, Request, Response,
                     UploadFile)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth
from .config import BASE_DIR, check_required, settings
from .db import get_conn, init_db, new_id, now_iso
from .reports import build_zip, render_pdf
from .rules import RULES
from .seed import seed_if_empty
from .verifier import verify_documents

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
DOC_TYPES = {"application_form", "identity_document"}
ENTITY_TYPES = {"Individual", "Corporate"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_required()   # refuse to boot without credentials configured
    init_db()
    seed_if_empty()
    yield


app = FastAPI(title="KYC Document AI", version="1.1.0", lifespan=lifespan)

# No CORS middleware: the frontend is served by this same app and calls /api
# relative, so every request is same-origin. A wildcard origin policy would
# only weaken the cookie-based session auth below.

PUBLIC_API = {"/api/login", "/api/health"}


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """Every /api/* route (except login + health) needs a valid session."""
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API:
        if not auth.is_valid(request.cookies.get(auth.COOKIE_NAME)):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _entity_row(conn, entity_id: str):
    row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Entity not found")
    return row


def _entity_payload(conn, row) -> dict:
    docs = conn.execute(
        "SELECT doc_type FROM documents WHERE entity_id = ?", (row["id"],)
    ).fetchall()
    last = conn.execute(
        "SELECT status, overall, created_at, fail_count, pass_count, na_count "
        "FROM runs WHERE entity_id = ? ORDER BY created_at DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    return {
        "id": row["id"],
        "name": row["name"],
        "entity_type": row["entity_type"],
        "created_at": row["created_at"],
        "doc_count": len(docs),
        "form_count": sum(1 for d in docs if d["doc_type"] == "application_form"),
        "id_count": sum(1 for d in docs if d["doc_type"] == "identity_document"),
        "last_run": dict(last) if last else None,
    }


# --------------------------------------------------------------------------
# Meta
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    """Render's health check target. Also surfaces whether this instance has
    persistent storage, which is the usual thing to check after a deploy."""
    return {"status": "ok", "model": settings.OPENAI_VISION_MODEL,
            "openai_configured": bool(settings.OPENAI_API_KEY),
            "persistent_storage": bool(settings.DATA_DIR)}


@app.get("/api/rules")
def get_rules() -> list:
    return RULES


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
@app.post("/api/login")
def login(response: Response,
          username: str = Form(...), password: str = Form(...)) -> dict:
    if not auth.verify_credentials(username.strip(), password):
        raise HTTPException(401, "Invalid username or password")
    token = auth.create_session()
    response.set_cookie(auth.COOKIE_NAME, token, httponly=True, samesite="lax",
                        secure=settings.COOKIE_SECURE)
    return {"ok": True, "username": settings.AUTH_USERNAME}


@app.post("/api/logout")
def logout(request: Request, response: Response) -> dict:
    auth.drop_session(request.cookies.get(auth.COOKIE_NAME))
    # Attributes must match the ones used at login or the browser keeps it.
    response.delete_cookie(auth.COOKIE_NAME, httponly=True, samesite="lax",
                           secure=settings.COOKIE_SECURE)
    return {"ok": True}


@app.get("/api/me")
def me() -> dict:
    return {"username": settings.AUTH_USERNAME}


@app.get("/api/dashboard")
def dashboard() -> list:
    """Every customer with their documents and latest verification run —
    one call powers the whole single-page dashboard."""
    conn = get_conn()
    try:
        out = []
        rows = conn.execute(
            "SELECT * FROM entities ORDER BY created_at DESC"
        ).fetchall()
        for row in rows:
            payload = _entity_payload(conn, row)
            docs = conn.execute(
                "SELECT id, doc_type, original_name, content_type, page_count, "
                "size_bytes, uploaded_at FROM documents WHERE entity_id = ? "
                "ORDER BY doc_type, uploaded_at",
                (row["id"],),
            ).fetchall()
            payload["documents"] = [dict(d) for d in docs]
            last = conn.execute(
                "SELECT * FROM runs WHERE entity_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            payload["run"] = _run_payload(last) if last else None
            out.append(payload)
        return out
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------
@app.get("/api/entities")
def list_entities() -> list:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM entities ORDER BY created_at DESC"
        ).fetchall()
        return [_entity_payload(conn, r) for r in rows]
    finally:
        conn.close()


@app.post("/api/entities")
def create_entity(name: str = Form(...),
                  entity_type: str = Form("Individual")) -> dict:
    name = name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if entity_type not in ENTITY_TYPES:
        entity_type = "Individual"
    conn = get_conn()
    try:
        eid = new_id()
        conn.execute(
            "INSERT INTO entities (id, name, entity_type, created_at) "
            "VALUES (?, ?, ?, ?)",
            (eid, name, entity_type, now_iso()),
        )
        conn.commit()
        return _entity_payload(conn, _entity_row(conn, eid))
    finally:
        conn.close()


@app.get("/api/entities/{entity_id}")
def get_entity(entity_id: str) -> dict:
    conn = get_conn()
    try:
        return _entity_payload(conn, _entity_row(conn, entity_id))
    finally:
        conn.close()


@app.delete("/api/entities/{entity_id}")
def delete_entity(entity_id: str) -> dict:
    conn = get_conn()
    try:
        _entity_row(conn, entity_id)
        conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        conn.commit()
    finally:
        conn.close()
    folder = settings.storage_dir / entity_id
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return {"deleted": entity_id}


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
@app.get("/api/entities/{entity_id}/documents")
def list_documents(entity_id: str) -> list:
    conn = get_conn()
    try:
        _entity_row(conn, entity_id)
        rows = conn.execute(
            "SELECT id, entity_id, doc_type, original_name, content_type, "
            "page_count, size_bytes, uploaded_at FROM documents "
            "WHERE entity_id = ? ORDER BY uploaded_at",
            (entity_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/entities/{entity_id}/documents")
def upload_documents(entity_id: str,
                     doc_type: str = Form(...),
                     files: list[UploadFile] = File(...)) -> list:
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, "doc_type must be application_form or identity_document")
    conn = get_conn()
    try:
        _entity_row(conn, entity_id)
        folder = settings.storage_dir / entity_id
        folder.mkdir(parents=True, exist_ok=True)
        saved = []
        for up in files:
            ext = Path(up.filename or "").suffix.lower()
            if ext not in ALLOWED_EXT:
                raise HTTPException(400, f"Unsupported file type: {ext or 'unknown'}")
            doc_id = new_id()
            stored = f"{doc_id}{ext}"
            dest = folder / stored
            data = up.file.read()
            dest.write_bytes(data)

            page_count = 1
            if ext == ".pdf":
                try:
                    with pymupdf.open(dest) as pdf:
                        page_count = len(pdf)
                except Exception:
                    page_count = 1
            conn.execute(
                "INSERT INTO documents (id, entity_id, doc_type, original_name, "
                "stored_name, content_type, page_count, size_bytes, uploaded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, entity_id, doc_type, up.filename or stored, stored,
                 up.content_type or "application/octet-stream",
                 page_count, len(data), now_iso()),
            )
            saved.append(doc_id)
        conn.commit()
        rows = conn.execute(
            "SELECT id, entity_id, doc_type, original_name, content_type, "
            "page_count, size_bytes, uploaded_at FROM documents "
            "WHERE id IN (%s)" % ",".join("?" * len(saved)),
            saved,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str) -> dict:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Document not found")
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
        path = settings.storage_dir / row["entity_id"] / row["stored_name"]
    finally:
        conn.close()
    if path.exists():
        path.unlink(missing_ok=True)
    return {"deleted": doc_id}


@app.get("/api/documents/{doc_id}/file")
def get_document_file(doc_id: str):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Document not found")
        path = settings.storage_dir / row["entity_id"] / row["stored_name"]
        media = row["content_type"]
        name = row["original_name"]
    finally:
        conn.close()
    if not path.exists():
        raise HTTPException(404, "File missing on disk")
    return FileResponse(path, media_type=media, filename=name,
                        content_disposition_type="inline")


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------
def _run_payload(row) -> dict:
    blob = json.loads(row["results_json"]) if row["results_json"] else {}
    if isinstance(blob, list):  # legacy shape
        results, extracted = blob, {}
    else:
        results, extracted = blob.get("results", []), blob.get("extracted", {})
    return {
        "id": row["id"],
        "entity_id": row["entity_id"],
        "status": row["status"],
        "overall": row["overall"],
        "summary": row["summary"],
        "error": row["error"],
        "pass_count": row["pass_count"],
        "fail_count": row["fail_count"],
        "na_count": row["na_count"],
        "created_at": row["created_at"],
        "results": results,
        "extracted": extracted,
    }


@app.get("/api/entities/{entity_id}/runs")
def list_runs(entity_id: str) -> list:
    conn = get_conn()
    try:
        _entity_row(conn, entity_id)
        rows = conn.execute(
            "SELECT * FROM runs WHERE entity_id = ? ORDER BY created_at DESC",
            (entity_id,),
        ).fetchall()
        return [_run_payload(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/entities/{entity_id}/verify")
def verify_entity(entity_id: str) -> dict:
    conn = get_conn()
    try:
        _entity_row(conn, entity_id)
        docs = conn.execute(
            "SELECT * FROM documents WHERE entity_id = ? ORDER BY doc_type, uploaded_at",
            (entity_id,),
        ).fetchall()
        if not docs:
            raise HTTPException(400, "No documents uploaded for this entity")
        doc_inputs = [{
            "original_name": d["original_name"],
            "doc_type": d["doc_type"],
            "path": str(settings.storage_dir / entity_id / d["stored_name"]),
        } for d in docs]
    finally:
        conn.close()

    run_id = new_id()
    created = now_iso()
    try:
        verdict = verify_documents(doc_inputs)
        status, error = "completed", None
        overall = verdict["overall_status"]
        summary = verdict["entity_summary"]
        results = verdict["results"]
        extracted = verdict["extracted"]
        counts = verdict["counts"]
    except Exception as exc:  # surface the failure to the UI rather than 500
        status, error = "failed", str(exc)
        overall, summary, results, extracted = None, None, [], {}
        counts = {"pass": 0, "fail": 0, "na": 0}

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO runs (id, entity_id, status, overall, summary, "
            "results_json, error, pass_count, fail_count, na_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, entity_id, status, overall, summary,
             json.dumps({"results": results, "extracted": extracted}), error,
             counts["pass"], counts["fail"], counts["na"], created),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_payload(row)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Report export — per-customer PDF, batch ZIP
# --------------------------------------------------------------------------
def _ascii_only(name: str) -> str:
    return "".join(c if ord(c) < 128 else "_" for c in name)


def _attachment_header(filename: str) -> str:
    return (f'attachment; filename="{_ascii_only(filename)}"; '
            f"filename*=UTF-8''{quote(filename)}")


@app.get("/api/entities/{entity_id}/report.pdf")
def entity_report(entity_id: str):
    conn = get_conn()
    try:
        row = _entity_row(conn, entity_id)
        run_row = conn.execute(
            "SELECT * FROM runs WHERE entity_id = ? AND status = 'completed' "
            "ORDER BY created_at DESC LIMIT 1", (entity_id,)).fetchone()
        if run_row is None:
            raise HTTPException(400, "No completed verification run for this customer")
        doc_rows = conn.execute(
            "SELECT * FROM documents WHERE entity_id = ? "
            "ORDER BY doc_type, uploaded_at", (entity_id,)).fetchall()
    finally:
        conn.close()
    pdf_bytes = render_pdf(dict(row), _run_payload(run_row),
                           [dict(d) for d in doc_rows])
    fn = f"{row['name']} - KYC Verification Report.pdf"
    return Response(pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": _attachment_header(fn)})


@app.get("/api/reports.zip")
def all_reports():
    conn = get_conn()
    try:
        entities = conn.execute(
            "SELECT * FROM entities ORDER BY created_at").fetchall()
        items = []
        for e in entities:
            run_row = conn.execute(
                "SELECT * FROM runs WHERE entity_id = ? "
                "AND status = 'completed' "
                "ORDER BY created_at DESC LIMIT 1", (e["id"],)).fetchone()
            if run_row is None:
                continue
            doc_rows = conn.execute(
                "SELECT * FROM documents WHERE entity_id = ? "
                "ORDER BY doc_type, uploaded_at", (e["id"],)).fetchall()
            items.append((dict(e), _run_payload(run_row),
                          [dict(d) for d in doc_rows]))
    finally:
        conn.close()
    if not items:
        raise HTTPException(400, "No completed verifications available to export")
    zip_bytes = build_zip(items)
    ts = datetime.now().strftime("%Y-%m-%d %H%M")
    fn = f"KYC Verification Reports - {ts}.zip"
    return Response(zip_bytes, media_type="application/zip",
                    headers={"Content-Disposition": _attachment_header(fn)})


# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def root():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
