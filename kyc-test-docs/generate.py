# -*- coding: utf-8 -*-
"""
KYC bulk-upload test document generator.

Produces matched, deliberately-flawed test documents for these checks:
  KYC_01  Incomplete KYC      -> blank mandatory form fields
  KYC_02  Poor Documentation  -> "NA"/"Same"/short write-up text
  KYC_09  Incomplete Profile  -> missing industry / source of wealth / business activity
  KYC_04  Invalid Document    -> expired ID
  KYC_05  Data Mismatch       -> ID name differs from the application form

Outputs digital PDFs and scan-simulated PDFs, in English and Chinese,
plus manifest.csv (the answer key).
"""
import os, random
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import fitz  # PyMuPDF
from PIL import Image, ImageEnhance, ImageFilter

random.seed(42)
np.random.seed(42)

BASE = os.path.dirname(os.path.abspath(__file__))
DIRS = {
    ("digital", "form"): os.path.join(BASE, "output", "digital", "forms"),
    ("digital", "id"):   os.path.join(BASE, "output", "digital", "ids"),
    ("scanned", "form"): os.path.join(BASE, "output", "scanned", "forms"),
    ("scanned", "id"):   os.path.join(BASE, "output", "scanned", "ids"),
}
for d in DIRS.values():
    os.makedirs(d, exist_ok=True)

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
CJK = "STSong-Light"
TODAY = "2026-05-19"

# --------------------------------------------------------------------------
# Field labels per language
# --------------------------------------------------------------------------
LABELS = {
    "en": {
        "form_title": "KYC APPLICATION FORM",
        "form_sub":   "Customer Onboarding & Due Diligence Record",
        "cid": "Customer ID", "name": "Full Name", "dob": "Date of Birth",
        "pan": "PAN / Tax ID", "addr": "Residential Address",
        "risk": "Risk Category", "ind": "Industry",
        "sow": "Source of Wealth", "biz": "Business Activity",
        "writeup": "CUSTOMER WRITE-UP",
        "purpose": "Purpose of Account", "bg": "Customer Background",
        "id_title": "PASSPORT", "id_sub": "Identity Document",
        "docno": "Document No.", "nat": "Nationality",
        "issue": "Date of Issue", "expiry": "Date of Expiry",
        "auth": "Issuing Authority", "photo": "PHOTO",
    },
    "zh": {
        "form_title": "客户身份识别申请表",
        "form_sub":   "客户开户及尽职调查记录",
        "cid": "客户编号", "name": "姓名", "dob": "出生日期",
        "pan": "税务登记号", "addr": "居住地址",
        "risk": "风险等级", "ind": "所属行业",
        "sow": "财富来源", "biz": "业务活动",
        "writeup": "客户背景说明",
        "purpose": "开户目的", "bg": "客户背景",
        "id_title": "护照", "id_sub": "身份证件",
        "docno": "证件号码", "nat": "国籍",
        "issue": "签发日期", "expiry": "有效期至",
        "auth": "签发机关", "photo": "照片",
    },
}

# --------------------------------------------------------------------------
# Customer records. Each has a clean baseline; defects are applied per scenario.
# form_scn / id_scn drive which check the document is meant to trip.
# --------------------------------------------------------------------------
CUSTOMERS = {
    "en": [
        dict(cid="C001-EN", form_scn="clean", id_scn="clean",
             name="John Edward Carter", dob="1985-03-12", pan="ABCPC1234D",
             addr="47 Maple Avenue, Springfield, IL 62704, USA",
             risk="Low", ind="Information Technology",
             sow="Salaried employment and listed equity investments",
             biz="Software consulting services",
             purpose="Account opened for routine salary deposits and personal "
                     "savings; expected monthly inflow approximately USD 6,000.",
             bg="Customer is a long-tenured IT professional at a listed "
                "technology firm with a stable income profile and no adverse media.",
             docno="P1234567A", nat="United States",
             issue="2019-06-01", expiry="2029-06-01",
             auth="U.S. Department of State", id_name=None),
        dict(cid="C002-EN", form_scn="kyc01", id_scn="clean",
             name="Michael Anthony Brooks", dob="1981-09-04", pan="BXYPB9087K",
             addr="12 Oak Street, Manchester M14 5TR, United Kingdom",
             risk="Medium", ind="Retail Trade",
             sow="Business income from retail operations",
             biz="Retail clothing store",
             purpose="Business current account for daily retail settlement "
                     "and supplier payments.",
             bg="Customer owns an established high-street retail outlet "
                "operating for over twelve years.",
             docno="P7781234B", nat="United Kingdom",
             issue="2021-02-10", expiry="2031-02-10",
             auth="HM Passport Office", id_name=None),
        dict(cid="C003-EN", form_scn="kyc02", id_scn="clean",
             name="David William Hughes", dob="1979-11-22", pan="CDEPH5566L",
             addr="88 Birch Road, Leeds LS6 2QP, United Kingdom",
             risk="Medium", ind="Construction",
             sow="Business income", biz="Building contractor",
             purpose="", bg="",  # filled by defect
             docno="P9912340C", nat="United Kingdom",
             issue="2020-05-18", expiry="2030-05-18",
             auth="HM Passport Office", id_name=None),
        dict(cid="C004-EN", form_scn="kyc09", id_scn="clean",
             name="Robert James Sullivan", dob="1990-07-08", pan="DEFPS7788M",
             addr="5 Cedar Close, Bristol BS8 1QU, United Kingdom",
             risk="Low", ind="Information Technology",
             sow="Salaried employment", biz="Import of consumer goods",
             purpose="Personal account for salary and household expenses.",
             bg="Customer is employed in a mid-sized trading company with a "
                "regular income.",
             docno="P5567812D", nat="United Kingdom",
             issue="2018-10-30", expiry="2028-10-30",
             auth="HM Passport Office", id_name=None),
        dict(cid="C005-EN", form_scn="clean", id_scn="kyc04",
             name="Thomas Henry Walker", dob="1975-01-19", pan="EFGPW3344N",
             addr="201 Elm Drive, Edinburgh EH3 9DR, United Kingdom",
             risk="High", ind="Real Estate",
             sow="Property rental income and prior business sale proceeds",
             biz="Commercial property leasing",
             purpose="Investment account for property rental receipts and "
                     "reinvestment.",
             bg="High-net-worth customer with diversified real estate holdings; "
                "enhanced due diligence applied.",
             docno="P3340012E", nat="United Kingdom",
             issue="2013-08-14", expiry="2023-08-14",  # expired
             auth="HM Passport Office", id_name=None),
        dict(cid="C006-EN", form_scn="clean", id_scn="kyc05",
             name="Christopher Paul Bennett", dob="1988-04-27", pan="FGHPB2211P",
             addr="9 Willow Lane, Cardiff CF10 3AT, United Kingdom",
             risk="Medium", ind="Professional Services",
             sow="Salaried employment and consultancy fees",
             biz="Management consultancy",
             purpose="Account for consultancy fee receipts and personal use.",
             bg="Customer is a self-employed management consultant with "
                "multiple corporate clients.",
             docno="P2210098F", nat="United Kingdom",
             issue="2022-03-15", expiry="2032-03-15",
             auth="HM Passport Office",
             id_name="Christopher Paul Barnett"),  # mismatch vs form
    ],
    "zh": [
        dict(cid="C001-ZH", form_scn="clean", id_scn="clean",
             name="陈伟明", dob="1984-05-20", pan="91310115MA1K2X3Y4Z",
             addr="上海市浦东新区世纪大道100号环球金融中心18层",
             risk="低", ind="信息技术",
             sow="工资收入及上市股票投资",
             biz="软件咨询服务",
             purpose="开立账户用于日常工资发放及个人储蓄，预计每月流入约六万元人民币。",
             bg="客户为某上市科技公司资深技术人员，收入稳定，无不利媒体记录。",
             docno="E12345678", nat="中国",
             issue="2019-06-01", expiry="2029-06-01",
             auth="中华人民共和国国家移民管理局", id_name=None),
        dict(cid="C002-ZH", form_scn="kyc01", id_scn="clean",
             name="李建国", dob="1980-02-11", pan="91320105MA2L3Y4Z5A",
             addr="江苏省南京市鼓楼区中山北路200号",
             risk="中", ind="批发零售",
             sow="零售经营收入", biz="服装零售店",
             purpose="开立对公结算账户用于日常零售收款及供应商付款。",
             bg="客户经营一家成立超过十年的服装零售门店。",
             docno="E22345678", nat="中国",
             issue="2021-02-10", expiry="2031-02-10",
             auth="中华人民共和国国家移民管理局", id_name=None),
        dict(cid="C003-ZH", form_scn="kyc02", id_scn="clean",
             name="王志强", dob="1978-08-30", pan="91330106MA3M4Z5A6B",
             addr="浙江省杭州市西湖区文三路300号",
             risk="中", ind="建筑业",
             sow="经营收入", biz="建筑承包",
             purpose="", bg="",
             docno="E32345678", nat="中国",
             issue="2020-05-18", expiry="2030-05-18",
             auth="中华人民共和国国家移民管理局", id_name=None),
        dict(cid="C004-ZH", form_scn="kyc09", id_scn="clean",
             name="张海燕", dob="1991-12-03", pan="91440300MA4N5A6B7C",
             addr="广东省深圳市福田区福华路400号",
             risk="低", ind="信息技术",
             sow="工资收入", biz="消费品进口",
             purpose="开立个人账户用于工资发放及家庭日常支出。",
             bg="客户就职于一家中型贸易公司，收入稳定。",
             docno="E42345678", nat="中国",
             issue="2018-10-30", expiry="2028-10-30",
             auth="中华人民共和国国家移民管理局", id_name=None),
        dict(cid="C005-ZH", form_scn="clean", id_scn="kyc04",
             name="刘文斌", dob="1974-06-15", pan="91500105MA5P6B7C8D",
             addr="重庆市渝中区解放碑步行街500号",
             risk="高", ind="房地产",
             sow="房产租金收入及原有企业出售所得",
             biz="商业地产租赁",
             purpose="开立投资账户用于房产租金收取及再投资。",
             bg="客户为高净值人士，持有多处房地产，已实施强化尽职调查。",
             docno="E52345678", nat="中国",
             issue="2013-08-14", expiry="2023-08-14",  # expired
             auth="中华人民共和国国家移民管理局", id_name=None),
        dict(cid="C006-ZH", form_scn="clean", id_scn="kyc05",
             name="黄俊杰", dob="1987-03-09", pan="91110108MA6Q7C8D9E",
             addr="北京市海淀区中关村大街600号",
             risk="中", ind="专业服务",
             sow="工资收入及咨询费",
             biz="管理咨询",
             purpose="开立账户用于收取咨询费及个人使用。",
             bg="客户为自雇管理咨询顾问，拥有多家企业客户。",
             docno="E62345678", nat="中国",
             issue="2022-03-15", expiry="2032-03-15",
             auth="中华人民共和国国家移民管理局",
             id_name="黄俊豪"),  # mismatch vs form
    ],
}

# --------------------------------------------------------------------------
# Defect application
# --------------------------------------------------------------------------
def form_data(cust, lang):
    """Return the field values to print on the application form."""
    d = dict(cust)
    if lang == "zh":
        d["purpose"] = d["purpose"] or "开立账户用于日常资金往来。"
        d["bg"] = d["bg"] or "客户背景信息已核实。"
    else:
        d["purpose"] = d["purpose"] or "Account for routine transactions."
        d["bg"] = d["bg"] or "Customer background verified."

    scn = cust["form_scn"]
    if scn == "kyc01":          # blank mandatory fields
        d["dob"] = ""
        d["risk"] = ""
    elif scn == "kyc02":        # poor / generic write-up
        if lang == "zh":
            d["purpose"], d["bg"] = "无", "同上"
        else:
            d["purpose"], d["bg"] = "NA", "Same"
    elif scn == "kyc09":        # missing key attributes
        d["ind"] = ""
        d["sow"] = ""
    return d

def id_name_for(cust):
    """Name to print on the ID document (mismatch for KYC_05)."""
    return cust["id_name"] or cust["name"]

# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------
NAVY = (0.067, 0.20, 0.36)

def wrap(c, text, font, size, max_w):
    words, lines, cur = list(text), [], ""
    # character-wrap (works for both Latin and CJK)
    for ch in text:
        trial = cur + ch
        if pdfmetrics.stringWidth(trial, font, size) > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines

def draw_form(path, cust, lang):
    L = LABELS[lang]
    d = form_data(cust, lang)
    font = CJK if lang == "zh" else "Helvetica"
    bold = CJK if lang == "zh" else "Helvetica-Bold"
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4

    # header band
    c.setFillColorRGB(*NAVY)
    c.rect(0, h - 78, w, 78, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(bold, 19)
    c.drawString(42, h - 44, L["form_title"])
    c.setFont(font, 9.5)
    c.drawString(42, h - 62, L["form_sub"])
    c.setFont(font, 8)
    c.drawRightString(w - 42, h - 44, "Ref: KYC-BULK-TEST")
    c.drawRightString(w - 42, h - 58, "Date: " + TODAY)

    c.setFillColorRGB(0, 0, 0)
    y = h - 110
    rows = [
        ("cid", d["cid"]), ("name", d["name"]), ("dob", d["dob"]),
        ("pan", d["pan"]), ("addr", d["addr"]), ("risk", d["risk"]),
        ("ind", d["ind"]), ("sow", d["sow"]), ("biz", d["biz"]),
    ]
    label_x, value_x, row_h = 52, 215, 30
    for key, val in rows:
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(48, y - 8, w - 48, y - 8)
        c.setFont(bold, 10)
        c.setFillColorRGB(*NAVY)
        c.drawString(label_x, y, L[key])
        c.setFont(font, 10)
        c.setFillColorRGB(0, 0, 0)
        for i, ln in enumerate(wrap(c, str(val), font, 10, w - value_x - 52)):
            c.drawString(value_x, y - i * 12, ln)
        y -= row_h

    # write-up section
    y -= 6
    c.setFillColorRGB(*NAVY)
    c.rect(48, y - 4, w - 96, 20, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(bold, 10)
    c.drawString(54, y + 2, L["writeup"])
    y -= 30
    c.setFillColorRGB(0, 0, 0)
    for key in ("purpose", "bg"):
        c.setFont(bold, 10)
        c.setFillColorRGB(*NAVY)
        c.drawString(label_x, y, L[key])
        c.setFont(font, 10)
        c.setFillColorRGB(0, 0, 0)
        y -= 16
        for ln in wrap(c, str(d[key]), font, 10, w - 104):
            c.drawString(label_x, y, ln)
            y -= 14
        y -= 12

    c.setFont(font, 7.5)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(48, 40, "Synthetic test document - generated for KYC bulk-upload "
                         "validation. Not a real customer record.")
    c.showPage()
    c.save()

def draw_id(path, cust, lang):
    L = LABELS[lang]
    font = CJK if lang == "zh" else "Helvetica"
    bold = CJK if lang == "zh" else "Helvetica-Bold"
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    name = id_name_for(cust)

    # card
    cw, ch = 470, 360
    cx, cy = (w - cw) / 2, h - 120 - ch
    HEADER, MRZ = 46, 44
    c.setFillColorRGB(0.93, 0.95, 0.98)
    c.roundRect(cx, cy, cw, ch, 10, fill=1, stroke=0)
    c.setFillColorRGB(*NAVY)
    c.roundRect(cx, cy + ch - HEADER, cw, HEADER, 10, fill=1, stroke=0)
    c.rect(cx, cy + ch - HEADER, cw, 24, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(bold, 16)
    c.drawString(cx + 18, cy + ch - 30, L["id_title"])
    c.setFont(font, 8.5)
    c.drawRightString(cx + cw - 18, cy + ch - 30, L["id_sub"])

    # photo box
    px, pw, ph = cx + 18, 112, 150
    py = cy + MRZ + ((ch - HEADER - MRZ) - ph) / 2
    c.setFillColorRGB(0.82, 0.85, 0.89)
    c.rect(px, py, pw, ph, fill=1, stroke=0)
    c.setFillColorRGB(0.45, 0.48, 0.52)
    c.setFont(font, 9)
    c.drawCentredString(px + pw / 2, py + ph / 2, L["photo"])

    # fields
    fx = px + pw + 26
    fy = cy + ch - HEADER - 26
    pairs = [
        ("docno", cust["docno"]), ("name", name),
        ("dob", cust["dob"]), ("nat", cust["nat"]),
        ("issue", cust["issue"]), ("expiry", cust["expiry"]),
        ("auth", cust["auth"]),
    ]
    for key, val in pairs:
        c.setFillColorRGB(*NAVY)
        c.setFont(bold, 8)
        c.drawString(fx, fy, L[key].upper() if lang == "en" else L[key])
        c.setFillColorRGB(0, 0, 0)
        c.setFont(font, 10.5 if key != "auth" else 9)
        c.drawString(fx, fy - 13, str(val))
        fy -= 35

    # MRZ-style strip
    c.setFillColorRGB(0.88, 0.90, 0.93)
    c.rect(cx, cy, cw, MRZ, fill=1, stroke=0)
    # MRZ is ASCII-only; CJK names are not romanized here, so zh uses filler
    surname = name.split()[-1].upper() if lang == "en" else ""
    given = " ".join(name.split()[:-1]).upper() if lang == "en" else ""
    mrz1 = ("P<{}{}<<{}".format(cust["nat"][:3].upper(), surname,
            given.replace(" ", "<")))[:44].ljust(44, "<")
    mrz2 = (cust["docno"].replace("-", "") + "<" * 6 +
            cust["dob"].replace("-", "") + cust["expiry"].replace("-", ""))[:44].ljust(44, "<")
    c.setFont("Courier", 10)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.drawString(cx + 12, cy + 26, mrz1)
    c.drawString(cx + 12, cy + 10, mrz2)

    c.setFont(font, 7.5)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(w / 2, 40, "Synthetic test document - generated for KYC "
                                   "bulk-upload validation. Not a real identity document.")
    c.showPage()
    c.save()

# --------------------------------------------------------------------------
# Scan simulation
# --------------------------------------------------------------------------
def make_scanned(src_pdf, dst_pdf):
    doc = fitz.open(src_pdf)
    page = doc[0]
    pix = page.get_pixmap(dpi=150)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()

    img = img.rotate(random.uniform(-1.6, 1.6), expand=True,
                     fillcolor=(255, 255, 255), resample=Image.BICUBIC)
    img = img.convert("L").convert("RGB")
    img = ImageEnhance.Brightness(img).enhance(random.uniform(0.93, 1.03))
    img = ImageEnhance.Contrast(img).enhance(random.uniform(0.88, 1.04))
    arr = np.asarray(img).astype(np.int16)
    arr = np.clip(arr + np.random.normal(0, 6, arr.shape), 0, 255).astype(np.uint8)
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.4))
    img.save(dst_pdf, "PDF", resolution=150.0)

# --------------------------------------------------------------------------
# Manifest answer-key
# --------------------------------------------------------------------------
FLAGS = {
    "clean": ("-", "(should pass - no flag expected)"),
    "kyc01": ("Incomplete KYC", "KYC_01: DOB and Risk Category left blank"),
    "kyc02": ("Poor Documentation", "KYC_02: write-up fields contain 'NA' / 'Same'"),
    "kyc09": ("Incomplete Profile", "KYC_09: Industry and Source of Wealth left blank"),
    "kyc04": ("Invalid Document", "KYC_04: passport expiry date 2023-08-14 (expired)"),
    "kyc05": ("Data Mismatch", "KYC_05: ID name differs from application form name"),
}

def main():
    rows = [("file", "customer_id", "language", "doc_type", "format",
             "scenario", "target_check", "expected_flag", "notes")]
    for lang, custs in CUSTOMERS.items():
        for cust in custs:
            cid = cust["cid"]
            # ---- form ----
            scn = cust["form_scn"]
            check = "-" if scn == "clean" else scn.upper()
            flag, note = FLAGS[scn]
            fn = "{}_form_{}.pdf".format(cid, lang)
            dfm = os.path.join(DIRS[("digital", "form")], fn)
            draw_form(dfm, cust, lang)
            sfm = os.path.join(DIRS[("scanned", "form")], fn)
            make_scanned(dfm, sfm)
            rows.append((fn, cid, lang, "application_form", "digital",
                         scn, check, flag, note))
            rows.append((fn, cid, lang, "application_form", "scanned",
                         scn, check, flag, note))
            # ---- id ----
            scn = cust["id_scn"]
            check = "-" if scn == "clean" else scn.upper()
            flag, note = FLAGS[scn]
            if scn == "kyc05":
                note += " (form='{}', ID='{}')".format(cust["name"], cust["id_name"])
            fn = "{}_id_{}.pdf".format(cid, lang)
            did = os.path.join(DIRS[("digital", "id")], fn)
            draw_id(did, cust, lang)
            sid = os.path.join(DIRS[("scanned", "id")], fn)
            make_scanned(did, sid)
            rows.append((fn, cid, lang, "identity_document", "digital",
                         scn, check, flag, note))
            rows.append((fn, cid, lang, "identity_document", "scanned",
                         scn, check, flag, note))

    import csv
    with open(os.path.join(BASE, "manifest.csv"), "w", newline="",
              encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)

    print("Generated {} document rows.".format(len(rows) - 1))
    print("Output folder:", os.path.join(BASE, "output"))
    print("Answer key   :", os.path.join(BASE, "manifest.csv"))

if __name__ == "__main__":
    main()
