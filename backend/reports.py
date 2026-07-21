"""Beautiful PDF verification reports + ZIP of per-customer reports.

Produces an A4 PDF report for one customer (logo, status banner, stats,
documents reviewed, extracted information, per-rule result cards) and a
ZIP whose top-level layout is one folder per customer name with the
report inside.
"""
import io
import re
import zipfile
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether,
                                PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from .config import BASE_DIR

# ---------- Protiviti palette ----------
NAVY        = colors.HexColor("#0c2240")
BLUE        = colors.HexColor("#1c4d86")
BLUE_LT     = colors.HexColor("#e9eef6")
ORANGE      = colors.HexColor("#e87722")
TEAL        = colors.HexColor("#1aa6b0")
PASS        = colors.HexColor("#1a8a55")
PASS_BG     = colors.HexColor("#e6f4ec")
PASS_BORDER = colors.HexColor("#bce0cb")
FAIL        = colors.HexColor("#cf2f27")
FAIL_BG     = colors.HexColor("#fbeae9")
FAIL_BORDER = colors.HexColor("#f1c5c2")
NA          = colors.HexColor("#66738a")
NA_BG       = colors.HexColor("#eef0f3")
WARN        = colors.HexColor("#c06d0a")
WARN_BG     = colors.HexColor("#fbf0df")
TEXT        = colors.HexColor("#1f2d40")
MUTED       = colors.HexColor("#66738a")
FAINT       = colors.HexColor("#939cae")
BORDER      = colors.HexColor("#e3e6ec")
SURFACE_2   = colors.HexColor("#f6f7f9")
WHITE       = colors.white

LOGO_PATH = BASE_DIR / "frontend" / "logo.png"

try:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _CJK = "STSong-Light"
except Exception:
    _CJK = "Helvetica"


def _esc(s) -> str:
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _has_cjk(s: str) -> bool:
    return any("一" <= c <= "鿿" for c in s)


def _txt(s) -> str:
    """Escape and wrap in CJK font if the string contains Chinese chars."""
    esc = _esc(s)
    return f'<font name="{_CJK}">{esc}</font>' if _has_cjk(esc) else esc


def _safe_filename(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", str(s)).strip()
    return s or "Customer"


# ---------------------------------------------------------------
# Page chrome (header + footer drawn on every page)
# ---------------------------------------------------------------
def _page_decor(canvas, doc):
    w, h = A4
    # logo top-left
    try:
        if LOGO_PATH.exists():
            canvas.drawImage(str(LOGO_PATH), 18*mm, h - 24*mm,
                             width=42*mm, height=16*mm,
                             preserveAspectRatio=True, mask="auto")
    except Exception:
        pass
    # title right
    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawRightString(w - 18*mm, h - 17*mm, "KYC VERIFICATION REPORT")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(w - 18*mm, h - 22*mm,
                           "Protiviti  ·  Global Business Consulting")
    # orange/teal accent line under header
    y = h - 25*mm
    canvas.setLineWidth(1.3)
    canvas.setStrokeColor(ORANGE)
    canvas.line(18*mm, y, 18*mm + 28*mm, y)
    canvas.setStrokeColor(TEAL)
    canvas.line(18*mm + 28*mm, y, w - 18*mm, y)

    # footer
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(.5)
    canvas.line(18*mm, 17*mm, w - 18*mm, 17*mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18*mm, 11.5*mm, "Protiviti · Confidential")
    canvas.drawCentredString(w / 2, 11.5*mm,
        datetime.now().strftime("Generated %d %b %Y · %H:%M"))
    canvas.drawRightString(w - 18*mm, 11.5*mm, f"Page {canvas.getPageNumber()}")


# ---------------------------------------------------------------
# Paragraph styles
# ---------------------------------------------------------------
def _styles():
    return {
        "h1":        ParagraphStyle("h1", fontName="Helvetica-Bold",
                        fontSize=20, textColor=NAVY, leading=24),
        "sub":       ParagraphStyle("sub", fontName="Helvetica",
                        fontSize=9.5, textColor=MUTED, leading=12),
        "section":   ParagraphStyle("section", fontName="Helvetica-Bold",
                        fontSize=10, textColor=NAVY, leading=13,
                        spaceBefore=0, spaceAfter=4),
        "body":      ParagraphStyle("body", fontName="Helvetica",
                        fontSize=10, textColor=TEXT, leading=13.5),
        "evidence":  ParagraphStyle("evi", fontName="Helvetica",
                        fontSize=9.5, textColor=TEXT, leading=13.5),
        "flag_line": ParagraphStyle("flag", fontName="Helvetica-Bold",
                        fontSize=9.5, textColor=FAIL, leading=12),
        "chip":      ParagraphStyle("chip", fontName="Helvetica",
                        fontSize=8.5, textColor=MUTED, leading=11),
        "kv_key":    ParagraphStyle("kvk", fontName="Helvetica-Bold",
                        fontSize=8.5, textColor=MUTED, leading=11),
        "kv_val":    ParagraphStyle("kvv", fontName="Courier-Bold",
                        fontSize=9.5, textColor=NAVY, leading=12),
        "rule_code": ParagraphStyle("rc", fontName="Courier-Bold",
                        fontSize=8.5, textColor=MUTED, leading=11),
        "rule_name": ParagraphStyle("rn", fontName="Helvetica-Bold",
                        fontSize=11, textColor=NAVY, leading=14),
        "rule_step": ParagraphStyle("rs", fontName="Helvetica",
                        fontSize=8.5, textColor=FAINT, leading=11),
    }


# ---------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------
def _customer_header(entity, styles):
    name = _txt(entity["name"])
    cid = _esc(entity["id"][:12])
    return [
        Paragraph(name, styles["h1"]),
        Spacer(1, 3),
        Paragraph(
            f"{_esc(entity['entity_type'])}  &middot;  Customer ID: "
            f"<font face='Courier'>{cid}</font>", styles["sub"]),
        Spacer(1, 14),
    ]


def _banner(run, styles, doc_w):
    flagged = run.get("overall") == "FLAGGED"
    fc = run.get("fail_count", 0)
    title = (f"Flagged — {fc} issue{'s' if fc != 1 else ''} found"
             if flagged else "Clear — all checks passed")
    bg     = FAIL_BG     if flagged else PASS_BG
    border = FAIL_BORDER if flagged else PASS_BORDER
    fg     = FAIL        if flagged else PASS
    summary = _txt(run.get("summary") or "")

    inner = [
        Paragraph(
            f"<font color='#{fg.hexval()[2:]}' size='13'>"
            f"<b>{_esc(title)}</b></font>",
            styles["body"]),
        Spacer(1, 3),
        Paragraph(summary, styles["body"]),
    ]
    t = Table([[inner]], colWidths=[doc_w])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX",        (0, 0), (-1, -1), 0.7, border),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    return t


def _stats_strip(run, doc_w):
    try:
        when = datetime.fromisoformat(run["created_at"])\
            .strftime("%d %b %Y · %H:%M")
    except Exception:
        when = run.get("created_at", "")

    cells = [
        (str(run.get("pass_count", 0)), "PASSED",     PASS),
        (str(run.get("fail_count", 0)), "FLAGGED",    FAIL),
        (str(run.get("na_count", 0)),   "NOT APPL.",  NA),
        (when,                          "RUN DATE",   NAVY),
    ]
    row = []
    for num, lbl, c in cells:
        size = 18 if lbl != "RUN DATE" else 10
        cell = [
            Paragraph(
                f"<font color='#{c.hexval()[2:]}' size='{size}'><b>{_esc(num)}</b></font>",
                ParagraphStyle("n", fontName="Helvetica-Bold",
                               fontSize=size, leading=size + 2)),
            Spacer(1, 3),
            Paragraph(
                f"<font color='#{MUTED.hexval()[2:]}' size='7.5'>{lbl}</font>",
                ParagraphStyle("l", fontName="Helvetica",
                               fontSize=7.5, leading=10)),
        ]
        row.append(cell)
    col = doc_w / 4
    t = Table([row], colWidths=[col]*4)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), WHITE),
        ("BOX",          (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEAFTER",    (0, 0), (-2, -1), 0.4, BORDER),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _section_title(text):
    return Paragraph(
        f"<font color='#0c2240' size='10'><b>{_esc(text).upper()}</b></font>"
        f"  <font color='#e87722' size='10'><b>—</b></font>",
        ParagraphStyle("st", fontName="Helvetica-Bold",
                       fontSize=10, leading=13, spaceAfter=8))


def _docs_table(documents, styles, doc_w):
    head = [
        Paragraph("FILE",  styles["kv_key"]),
        Paragraph("TYPE",  styles["kv_key"]),
        Paragraph("PAGES", styles["kv_key"]),
    ]
    data = [head]
    for d in documents:
        dtype = "Application Form" if d["doc_type"] == "application_form" \
                else "Identity Document"
        data.append([
            Paragraph(_txt(d["original_name"]), styles["body"]),
            Paragraph(dtype, styles["body"]),
            Paragraph(str(d.get("page_count", 1)), styles["body"]),
        ])
    t = Table(data,
              colWidths=[doc_w * 0.56, doc_w * 0.30, doc_w * 0.14])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), WHITE),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 8.5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX",        (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW",  (0, 0), (-1, -2), 0.4, BORDER),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _extracted_rows(ex):
    ids = [s for s in (ex.get("names_on_identity_documents") or []) if s]
    exp = [s for s in (ex.get("expiry_dates") or []) if s]
    rows = []
    if ex.get("name_on_form"):
        rows.append(("Name on Form", ex["name_on_form"]))
    if ids:
        rows.append(("Name on ID(s)", " · ".join(ids)))
    if ex.get("dob_on_form"):
        rows.append(("Date of Birth", ex["dob_on_form"]))
    if exp:
        rows.append(("ID Expiry Date(s)", " · ".join(exp)))
    return rows


def _kv_table(rows, styles, doc_w):
    data = []
    for k, v in rows:
        data.append([
            Paragraph(_esc(k).upper(), styles["kv_key"]),
            Paragraph(_txt(v), styles["kv_val"]),
        ])
    t = Table(data, colWidths=[doc_w * 0.32, doc_w * 0.68])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BOX",        (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW",  (0, 0), (-1, -2), 0.4, BORDER),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _verdict_pill(status):
    if status == "PASS":
        bg, fg, label = PASS_BG, PASS, "PASS"
    elif status == "FAIL":
        bg, fg, label = FAIL_BG, FAIL, "FAIL"
    else:
        bg, fg, label = NA_BG, NA, "N/A"
    pill = Table([[label]], colWidths=[20*mm], rowHeights=[8.5*mm])
    pill.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("TEXTCOLOR",  (0, 0), (-1, -1), fg),
        ("FONTNAME",   (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9.5),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return pill


def _result_card(r, styles, doc_w):
    if   r["status"] == "PASS": edge = PASS
    elif r["status"] == "FAIL": edge = FAIL
    else:                       edge = NA

    code = Paragraph(_esc(r["rule_id"]), styles["rule_code"])
    title = Paragraph(
        f"{_esc(r['flag_name'])}<br/>"
        f"<font name='Helvetica' size='8.5' color='#939cae'>"
        f"{_esc(r['process_step'])}</font>",
        styles["rule_name"])
    verdict = _verdict_pill(r["status"])

    head_w = doc_w - 2 * 14   # subtract outer paddings
    code_w, pill_w = 22*mm, 22*mm
    title_w = head_w - code_w - pill_w - 12   # gaps
    head = Table([[code, title, verdict]],
                 colWidths=[code_w, title_w, pill_w])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    bits = [head]
    if r["status"] == "FAIL" and r.get("flag"):
        bits.append(Spacer(1, 6))
        bits.append(Paragraph(
            f"●  {_esc(r['flag'])}", styles["flag_line"]))
    bits.append(Spacer(1, 5))
    bits.append(Paragraph(_txt(r.get("evidence", "")), styles["evidence"]))

    docs = [d for d in (r.get("documents_examined") or []) if d]
    if docs:
        bits.append(Spacer(1, 5))
        bits.append(Paragraph(
            "Documents reviewed:  " + "  ·  ".join(_txt(d) for d in docs),
            styles["chip"]))

    card = Table([[bits]], colWidths=[doc_w])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BOX",        (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEBEFORE", (0, 0), (0, 0), 3.5, edge),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    return KeepTogether(card)


# ---------------------------------------------------------------
# Top-level renderer
# ---------------------------------------------------------------
def render_pdf(entity: dict, run: dict, documents: list) -> bytes:
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=30*mm, bottomMargin=22*mm,
        title=f"KYC Report - {entity['name']}",
        author="Protiviti",
    )
    doc_w = doc.width
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                       onPage=_page_decor)])

    styles = _styles()
    story = []
    story += _customer_header(entity, styles)
    story.append(_banner(run, styles, doc_w))
    story.append(Spacer(1, 10))
    story.append(_stats_strip(run, doc_w))

    story.append(Spacer(1, 22))
    story.append(_section_title("Documents Reviewed"))
    story.append(_docs_table(documents, styles, doc_w))

    ex_rows = _extracted_rows(run.get("extracted") or {})
    if ex_rows:
        story.append(Spacer(1, 22))
        story.append(_section_title("Extracted Information"))
        story.append(_kv_table(ex_rows, styles, doc_w))

    story.append(Spacer(1, 22))
    story.append(_section_title("Verification Results"))
    for r in (run.get("results") or []):
        story.append(_result_card(r, styles, doc_w))
        story.append(Spacer(1, 7))

    doc.build(story)
    return buf.getvalue()


def build_zip(items: list[tuple[dict, dict, list]]) -> bytes:
    """items: list of (entity, run, documents)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entity, run, docs in items:
            pdf = render_pdf(entity, run, docs)
            folder = _safe_filename(entity["name"])
            zf.writestr(f"{folder}/KYC Verification Report.pdf", pdf)
    return buf.getvalue()
