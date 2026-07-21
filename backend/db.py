"""SQLite persistence layer — plain stdlib sqlite3, one connection per call."""
import sqlite3
import uuid
from datetime import datetime, timezone

from .config import settings


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'Individual',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    entity_id     TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    doc_type      TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_name   TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    page_count    INTEGER NOT NULL DEFAULT 1,
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    uploaded_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    entity_id     TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    status        TEXT NOT NULL,
    overall       TEXT,
    summary       TEXT,
    results_json  TEXT,
    error         TEXT,
    pass_count    INTEGER NOT NULL DEFAULT 0,
    fail_count    INTEGER NOT NULL DEFAULT 0,
    na_count      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_entity ON documents(entity_id);
CREATE INDEX IF NOT EXISTS idx_runs_entity ON runs(entity_id);
"""


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
