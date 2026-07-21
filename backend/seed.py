"""Pre-populate the app with the demo customers and their KYC documents.

Runs once, on startup, only when the database has no customers yet. The
documents are taken from the bundled `kyc-test-docs` synthetic test set.
"""
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymupdf

from .config import BASE_DIR, settings
from .db import get_conn, new_id, now_iso

# where the synthetic test PDFs may live (bundled inside the app, or alongside)
_CANDIDATES = [
    BASE_DIR / "kyc-test-docs" / "output" / "digital",
    BASE_DIR.parent / "kyc-test-docs" / "output" / "digital",
]

# code -> display name. Each customer has one form + one ID in the test set.
SEED_CUSTOMERS = [
    ("C001-EN", "John Edward Carter"),
    ("C002-EN", "Michael Anthony Brooks"),
    ("C003-EN", "David William Hughes"),
    ("C004-EN", "Robert James Sullivan"),
    ("C005-EN", "Thomas Henry Walker"),
    ("C006-EN", "Christopher Paul Bennett"),
    ("C001-ZH", "Chen Weiming  (陈伟明)"),
    ("C002-ZH", "Li Jianguo  (李建国)"),
    ("C003-ZH", "Wang Zhiqiang  (王志强)"),
    ("C004-ZH", "Zhang Haiyan  (张海燕)"),
    ("C005-ZH", "Liu Wenbin  (刘文斌)"),
    ("C006-ZH", "Huang Junjie  (黄俊杰)"),
]


def _docs_root() -> Path | None:
    for c in _CANDIDATES:
        if c.exists():
            return c
    return None


def _page_count(path: Path) -> int:
    try:
        with pymupdf.open(path) as pdf:
            return len(pdf)
    except Exception:
        return 1


def seed_if_empty() -> None:
    conn = get_conn()
    try:
        if conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()["c"]:
            return  # already has customers — never overwrite
        root = _docs_root()
        if root is None:
            return  # test documents not bundled — start empty

        base = datetime.now(timezone.utc)
        for i, (code, name) in enumerate(SEED_CUSTOMERS):
            lang = code.split("-")[1].lower()
            form_src = root / "forms" / f"{code}_form_{lang}.pdf"
            id_src = root / "ids" / f"{code}_id_{lang}.pdf"
            if not (form_src.exists() and id_src.exists()):
                continue

            eid = new_id()
            # first customer gets the newest timestamp so the list reads C001..C006
            created = (base - timedelta(seconds=i)).isoformat()
            conn.execute(
                "INSERT INTO entities (id, name, entity_type, created_at) "
                "VALUES (?, ?, ?, ?)",
                (eid, name, "Individual", created),
            )
            folder = settings.storage_dir / eid
            folder.mkdir(parents=True, exist_ok=True)

            for src, dtype in ((form_src, "application_form"),
                               (id_src, "identity_document")):
                did = new_id()
                stored = f"{did}.pdf"
                dest = folder / stored
                shutil.copy2(src, dest)
                conn.execute(
                    "INSERT INTO documents (id, entity_id, doc_type, "
                    "original_name, stored_name, content_type, page_count, "
                    "size_bytes, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (did, eid, dtype, src.name, stored, "application/pdf",
                     _page_count(dest), dest.stat().st_size, now_iso()),
                )
        conn.commit()
    finally:
        conn.close()
