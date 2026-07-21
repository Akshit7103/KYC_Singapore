"""KYC verification engine — feeds customer documents to an OpenAI vision
model together with the rule set and parses a structured verdict back."""
import base64
import json
from datetime import date
from pathlib import Path

import pymupdf
from openai import OpenAI

from .config import settings
from .rules import RULES, RULES_BY_ID, rules_prompt_block

_client: OpenAI | None = None
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not configured in .env")
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _render_document(path: Path) -> list[bytes]:
    """Return a list of PNG byte blobs — one per page (PDF) or the image itself."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return [path.read_bytes()]
    pages: list[bytes] = []
    with pymupdf.open(path) as pdf:
        zoom = settings.RENDER_DPI / 72.0
        matrix = pymupdf.Matrix(zoom, zoom)
        for i, page in enumerate(pdf):
            if i >= settings.MAX_PAGES_PER_DOC:
                break
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pages.append(pix.tobytes("png"))
    return pages


def _image_part(png_bytes: bytes) -> dict:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
    }


SYSTEM_PROMPT = """You are a senior KYC (Know Your Customer) compliance analyst \
performing document verification for a bank's customer onboarding pipeline.

You will be shown EVERY document currently on file for ONE customer / entity. \
Each document is announced with a line stating its file name and its TYPE, \
which is one of:
  - application_form  : the KYC application / onboarding form
  - identity_document : a passport, national ID or other identity proof

Today's date is {today}. Use it for any date comparison.

Work in TWO steps.

STEP 1 — EXTRACT (do this first, before any verdict).
Transcribe the following values EXACTLY as printed — letter by letter and digit
by digit. Do NOT auto-correct, normalise, or "fix" spelling. If a name looks
unusual, transcribe what you actually see:
  - the customer's full name on the application form
  - the customer's full name on EACH identity document
  - the date of birth on the application form
  - the expiry date on each identity document
Record these in the "extracted" object of your response.

STEP 2 — VERIFY.
Apply EXACTLY the following {count} rules — no more, no fewer:

{rules}

For every rule return a verdict:
  - "PASS"           : the FAIL condition is NOT met.
  - "FAIL"           : the FAIL condition IS met. Raise the rule's flag.
  - "NOT_APPLICABLE" : a document type the rule needs was not supplied.

Critical guidance:
- For KYC_05, compare the names you transcribed in STEP 1 character by
  character. A different spelling (e.g. "Bennett" vs "Barnett"), a different
  surname, transposed names, a missing/added middle name, or different
  initials ARE a mismatch and MUST be FAIL. Only pure differences in letter
  case or surrounding whitespace are NOT a mismatch.
- Read all small print, ID fields and handwriting carefully.
- Documents may be in English or Chinese — handle both.
- Base every verdict only on what is actually visible.
- In "evidence" be specific: name the field, quote the values seen, give the
  date, or state exactly which two name strings differed. One or two sentences.
- "documents_examined" must list the file names you used for that rule.

Respond with ONLY a JSON object in this exact shape:
{{
  "overall_status": "CLEAR" | "FLAGGED",
  "entity_summary": "<2-3 sentence overall assessment of this customer>",
  "extracted": {{
    "name_on_form": "<verbatim, or null if no form>",
    "names_on_identity_documents": ["<verbatim per ID>", ...],
    "dob_on_form": "<verbatim, or null>",
    "expiry_dates": ["<verbatim per ID>", ...]
  }},
  "results": [
    {{
      "rule_id": "KYC_01",
      "status": "PASS" | "FAIL" | "NOT_APPLICABLE",
      "flag": "<the rule flag if FAIL, otherwise null>",
      "evidence": "<specific explanation>",
      "documents_examined": ["<file name>", ...]
    }}
    // ... one object for every rule above
  ]
}}
overall_status is "FLAGGED" if any rule is FAIL, otherwise "CLEAR"."""


def _build_messages(documents: list[dict]) -> list[dict]:
    system = SYSTEM_PROMPT.format(
        today=date.today().isoformat(),
        count=len(RULES),
        rules=rules_prompt_block(),
    )
    content: list[dict] = [{
        "type": "text",
        "text": (
            f"Here are all {len(documents)} document(s) on file for this "
            f"customer. Verify them against the rules and return the JSON verdict."
        ),
    }]
    for doc in documents:
        content.append({
            "type": "text",
            "text": (
                f"\n===== DOCUMENT: {doc['original_name']} "
                f"| TYPE: {doc['doc_type']} ====="
            ),
        })
        for png in _render_document(Path(doc["path"])):
            content.append(_image_part(png))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def _normalise(raw: dict, documents: list[dict]) -> dict:
    """Force every rule to be present and stamp authoritative severity/flag."""
    have_form = any(d["doc_type"] == "application_form" for d in documents)
    have_id = any(d["doc_type"] == "identity_document" for d in documents)
    by_id = {r.get("rule_id"): r for r in raw.get("results", []) if isinstance(r, dict)}

    results = []
    for rule in RULES:
        r = by_id.get(rule["id"], {})
        status = str(r.get("status", "")).upper()
        if status not in ("PASS", "FAIL", "NOT_APPLICABLE"):
            status = "NOT_APPLICABLE"
        # guard: rule cannot pass/fail without the document types it needs
        needs_form = "application_form" in rule["applies_to"]
        needs_id = "identity_document" in rule["applies_to"]
        if (needs_form and not have_form) or (needs_id and not have_id):
            status = "NOT_APPLICABLE"
        results.append({
            "rule_id": rule["id"],
            "flag_name": rule["flag"],
            "process_step": rule["process_step"],
            "severity": rule["severity"],
            "description": rule["description"],
            "status": status,
            "flag": rule["flag"] if status == "FAIL" else None,
            "evidence": str(r.get("evidence", "")).strip()
            or ("Required document type not supplied."
                if status == "NOT_APPLICABLE" else "No evidence returned."),
            "documents_examined": r.get("documents_examined") or [],
        })

    fail = sum(1 for r in results if r["status"] == "FAIL")
    passed = sum(1 for r in results if r["status"] == "PASS")
    na = sum(1 for r in results if r["status"] == "NOT_APPLICABLE")
    extracted = raw.get("extracted") if isinstance(raw.get("extracted"), dict) else {}
    return {
        "overall_status": "FLAGGED" if fail else "CLEAR",
        "entity_summary": str(raw.get("entity_summary", "")).strip(),
        "extracted": extracted,
        "results": results,
        "counts": {"pass": passed, "fail": fail, "na": na},
    }


def verify_documents(documents: list[dict]) -> dict:
    """Run the KYC checks for one customer.

    `documents` is a list of dicts with keys: original_name, doc_type, path.
    Returns the normalised verdict dict.
    """
    if not documents:
        raise ValueError("No documents to verify")

    client = get_client()
    response = client.chat.completions.create(
        model=settings.OPENAI_VISION_MODEL,
        messages=_build_messages(documents),
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=3000,
    )
    raw_text = response.choices[0].message.content or "{}"
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model returned invalid JSON: {exc}") from exc
    return _normalise(raw, documents)
