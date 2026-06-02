"""
generate_claim_docs.py
Generates 5 realistic fake insurance claim PDFs for demo/testing purposes.

Claim scenario: Ahmed Al-Rashidi, 34, had an appendectomy on 14 March 2025.
Intentional inconsistencies baked in:
  1. DOB mismatch — invoice says 1990-07-22, patient record says 1988-07-22 (2-year gap)
  2. Invoice date (12 March) is 2 days BEFORE the treatment date (14 March) — billing fraud pattern
  3. Referring physician on invoice is NOT listed on the insurance network

These should cause the Prosecutor to fire 2 MEDIUM flags and 1 HIGH flag,
and the Judge to return MANUAL_REVIEW.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
import os

OUT_DIR = "sample_claim_docs"
os.makedirs(OUT_DIR, exist_ok=True)

styles = getSampleStyleSheet()

def h1(text):
    return ParagraphStyle('h1', fontSize=16, fontName='Helvetica-Bold',
                          spaceAfter=4, textColor=colors.HexColor('#1a1a2e'))

def h2(text):
    return ParagraphStyle('h2', fontSize=12, fontName='Helvetica-Bold',
                          spaceAfter=2, textColor=colors.HexColor('#16213e'))

def body():
    return ParagraphStyle('body', fontSize=10, fontName='Helvetica',
                          leading=14, textColor=colors.HexColor('#2c2c2c'))

def small():
    return ParagraphStyle('small', fontSize=8, fontName='Helvetica',
                          textColor=colors.HexColor('#666666'))

def label():
    return ParagraphStyle('label', fontSize=8, fontName='Helvetica-Bold',
                          textColor=colors.HexColor('#888888'), spaceAfter=1)

def field_table(rows, col_widths=None):
    if col_widths is None:
        col_widths = [60*mm, 100*mm]
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#555555')),
        ('TEXTCOLOR', (1,0), (1,-1), colors.HexColor('#111111')),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('LINEBELOW', (0,0), (-1,-2), 0.3, colors.HexColor('#e8e8e8')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    return t

# ─────────────────────────────────────────────
# DOC 1: INSURANCE CLAIM FORM
# ─────────────────────────────────────────────
def make_insurance_form():
    path = os.path.join(OUT_DIR, "01_insurance_claim_form.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    story = []

    # Header
    story.append(Paragraph("MERIDIAN HEALTH INSURANCE", ParagraphStyle(
        'hdr', fontSize=18, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#003366'), alignment=TA_CENTER)))
    story.append(Paragraph("Medical Claim Submission Form", ParagraphStyle(
        'sub', fontSize=11, fontName='Helvetica',
        textColor=colors.HexColor('#666666'), alignment=TA_CENTER, spaceAfter=2)))
    story.append(Paragraph("Form MHI-CLM-2025 | Internal Use Only", ParagraphStyle(
        'ref', fontSize=8, fontName='Helvetica',
        textColor=colors.HexColor('#aaaaaa'), alignment=TA_CENTER, spaceAfter=8)))
    story.append(HRFlowable(width="100%", thickness=1.5,
                             color=colors.HexColor('#003366'), spaceAfter=10))

    # Section A
    story.append(Paragraph("SECTION A — POLICY INFORMATION", ParagraphStyle(
        'sec', fontSize=10, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#003366'), spaceAfter=6,
        borderPad=4, backColor=colors.HexColor('#f0f4f8'))))
    story.append(Spacer(1, 4))

    story.append(field_table([
        ["Policy Number:",       "MHI-2024-ARA-00847"],
        ["Policy Holder Name:",  "Ahmed Ali Al-Rashidi"],
        ["Coverage Start Date:", "01 January 2024"],
        ["Coverage End Date:",   "31 December 2025"],
        ["Plan Type:",           "Comprehensive Inpatient & Outpatient"],
        ["Maximum Annual Benefit:", "USD 100,000"],
        ["Co-payment:",          "20% after deductible"],
        ["Deductible:",          "USD 500 per annum"],
    ]))

    story.append(Spacer(1, 10))

    # Section B
    story.append(Paragraph("SECTION B — CLAIMANT DETAILS", ParagraphStyle(
        'sec', fontSize=10, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#003366'), spaceAfter=6,
        borderPad=4, backColor=colors.HexColor('#f0f4f8'))))
    story.append(Spacer(1, 4))

    story.append(field_table([
        ["Full Name:",           "Ahmed Ali Al-Rashidi"],
        ["Date of Birth:",       "22 July 1990"],         # <-- will conflict with patient record
        ["National ID:",         "784-1990-1234567-1"],
        ["Contact Number:",      "+971 50 234 8812"],
        ["Email Address:",       "a.alrashidi@email.ae"],
        ["Address:",             "Villa 14, Al Nahda 2, Dubai, UAE"],
    ]))

    story.append(Spacer(1, 10))

    # Section C
    story.append(Paragraph("SECTION C — CLAIM DETAILS", ParagraphStyle(
        'sec', fontSize=10, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#003366'), spaceAfter=6)))
    story.append(Spacer(1, 4))

    story.append(field_table([
        ["Claim Reference:",     "CLM-2025-03-00291"],
        ["Date of Submission:",  "18 March 2025"],
        ["Nature of Claim:",     "Surgical — Emergency Appendectomy"],
        ["Hospital / Facility:", "City Medical Centre, Dubai"],
        ["Admission Date:",      "14 March 2025"],
        ["Discharge Date:",      "16 March 2025"],
        ["Total Amount Claimed:", "USD 8,450.00"],
    ]))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "I hereby declare that the information provided in this form is true, accurate, and complete "
        "to the best of my knowledge. I authorise Meridian Health Insurance to obtain any medical "
        "records relevant to this claim.",
        ParagraphStyle('decl', fontSize=9, fontName='Helvetica-Oblique',
                       textColor=colors.HexColor('#555555'), leading=13)))
    story.append(Spacer(1, 12))

    sig_table = Table([
        ["Claimant Signature: ___________________________", "Date: 18 March 2025"]
    ], colWidths=[110*mm, 60*mm])
    sig_table.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#333333')),
    ]))
    story.append(sig_table)

    doc.build(story)
    return path


# ─────────────────────────────────────────────
# DOC 2: HOSPITAL INVOICE
# ─────────────────────────────────────────────
def make_invoice():
    path = os.path.join(OUT_DIR, "02_hospital_invoice.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    story = []

    # Hospital header
    story.append(Paragraph("CITY MEDICAL CENTRE", ParagraphStyle(
        'h', fontSize=20, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0d3b66'), alignment=TA_LEFT)))
    story.append(Paragraph("Al Nahda Road, Dubai, UAE | Tel: +971 4 345 9900 | www.citymedical.ae", ParagraphStyle(
        'sh', fontSize=8, fontName='Helvetica',
        textColor=colors.HexColor('#888888'), spaceAfter=2)))
    story.append(Paragraph("License No: DHA-HF-00234 | Tax Registration: 100234876500003", ParagraphStyle(
        'sh2', fontSize=8, fontName='Helvetica',
        textColor=colors.HexColor('#aaaaaa'), spaceAfter=8)))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor('#cccccc'), spaceAfter=10))

    # Invoice title + meta
    meta = Table([
        [Paragraph("TAX INVOICE", ParagraphStyle('inv', fontSize=16,
                   fontName='Helvetica-Bold', textColor=colors.HexColor('#0d3b66'))),
         Paragraph("Invoice No: CMC-INV-2025-04821<br/>Invoice Date: 12 March 2025<br/>Due Date: 12 April 2025",
                   ParagraphStyle('meta', fontSize=9, fontName='Helvetica',
                                  textColor=colors.HexColor('#333333'), alignment=TA_RIGHT))]
    ], colWidths=[90*mm, 80*mm])
    meta.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(meta)
    story.append(Spacer(1, 10))

    # Bill to
    story.append(Paragraph("BILLED TO", ParagraphStyle(
        'bt', fontSize=8, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#888888'), spaceAfter=3)))
    story.append(field_table([
        ["Patient Name:",    "Ahmed Ali Al-Rashidi"],
        ["Date of Birth:",   "22 July 1990"],          # <-- intentional mismatch with patient record
        ["National ID:",     "784-1990-1234567-1"],
        ["Insurance Policy:","MHI-2024-ARA-00847"],
        ["Admission Date:",  "14 March 2025"],
        ["Discharge Date:",  "16 March 2025"],
    ]))

    story.append(Spacer(1, 10))

    # Line items
    story.append(Paragraph("SERVICES RENDERED", ParagraphStyle(
        'sr', fontSize=8, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#888888'), spaceAfter=4)))

    items = [
        ["Description", "Code", "Qty", "Unit Price (USD)", "Total (USD)"],
        ["Emergency Appendectomy (Laparoscopic)", "CPT-44950", "1", "5,500.00", "5,500.00"],
        ["General Anaesthesia", "CPT-00840", "1", "1,200.00", "1,200.00"],
        ["Inpatient Bed (2 nights — standard ward)", "IPD-STD-2N", "2", "400.00", "800.00"],
        ["Surgical Consumables & Medication", "SURG-CONS", "1", "650.00", "650.00"],
        ["Laboratory — Complete Blood Count", "LAB-CBC", "1", "120.00", "120.00"],
        ["Radiology — CT Abdomen", "RAD-CT-ABD", "1", "180.00", "180.00"],
        ["", "", "", "", ""],
        ["", "", "", "Subtotal:", "8,450.00"],
        ["", "", "", "VAT (5%):", "422.50"],
        ["", "", "", "TOTAL DUE:", "8,872.50"],
    ]
    item_table = Table(items, colWidths=[75*mm, 22*mm, 12*mm, 30*mm, 28*mm])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0d3b66')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('ROWBACKGROUNDS', (0,1), (-1,-4), [colors.white, colors.HexColor('#f7f9fc')]),
        ('GRID', (0,0), (-1,-4), 0.3, colors.HexColor('#dddddd')),
        ('ALIGN', (2,0), (-1,-1), 'RIGHT'),
        ('FONTNAME', (3,-3), (-1,-1), 'Helvetica-Bold'),
        ('LINEABOVE', (3,-3), (-1,-3), 0.8, colors.HexColor('#0d3b66')),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 10))

    # Attending physician — NOT on insurance network (intentional flag)
    story.append(Paragraph("ATTENDING PHYSICIAN", ParagraphStyle(
        'ap', fontSize=8, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#888888'), spaceAfter=3)))
    story.append(field_table([
        ["Physician Name:",  "Dr. Khalid Mansour Al-Farsi"],   # <-- not on network
        ["Specialisation:", "General Surgery"],
        ["License No:",     "DHA-PHY-08821"],
        ["Signature:",      "___________________________"],
    ]))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Payment should be made to City Medical Centre. For insurance claims, "
        "please submit this invoice along with all supporting documents to your insurer. "
        "For queries: billing@citymedical.ae",
        ParagraphStyle('note', fontSize=8, fontName='Helvetica-Oblique',
                       textColor=colors.HexColor('#888888'), leading=12)))

    doc.build(story)
    return path


# ─────────────────────────────────────────────
# DOC 3: PATIENT RECORD
# ─────────────────────────────────────────────
def make_patient_record():
    path = os.path.join(OUT_DIR, "03_patient_record.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    story = []

    story.append(Paragraph("CITY MEDICAL CENTRE", ParagraphStyle(
        'h', fontSize=16, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0d3b66'))))
    story.append(Paragraph("PATIENT MEDICAL RECORD — CONFIDENTIAL", ParagraphStyle(
        'sh', fontSize=10, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#cc0000'), spaceAfter=6)))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor('#cccccc'), spaceAfter=8))

    story.append(Paragraph("PATIENT DEMOGRAPHICS", ParagraphStyle(
        'sec', fontSize=10, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#003366'), spaceAfter=6)))

    story.append(field_table([
        ["Patient Name:",    "Ahmed Ali Al-Rashidi"],
        ["Date of Birth:",   "22 July 1988"],       # <-- DIFFERENT from insurance form + invoice (1988 vs 1990)
        ["Gender:",          "Male"],
        ["National ID:",     "784-1990-1234567-1"],
        ["Blood Group:",     "B+"],
        ["Allergies:",       "Penicillin (documented 2019)"],
        ["MRN:",             "CMC-MRN-008821"],
        ["Registration Date:", "09 February 2020"],
    ]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("ADMISSION RECORD — MARCH 2025", ParagraphStyle(
        'sec', fontSize=10, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#003366'), spaceAfter=6)))

    story.append(field_table([
        ["Admission Date:",    "14 March 2025"],
        ["Admission Time:",    "02:34 AM"],
        ["Admission Type:",    "Emergency"],
        ["Presenting Complaint:", "Severe right lower quadrant abdominal pain, fever, nausea"],
        ["Admitting Physician:", "Dr. Khalid Mansour Al-Farsi"],
        ["Ward:",              "Surgical Ward B, Bed 12"],
        ["Discharge Date:",    "16 March 2025"],
        ["Discharge Time:",    "11:00 AM"],
        ["Discharge Status:",  "Recovered — stable condition"],
    ]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("CLINICAL NOTES", ParagraphStyle(
        'sec', fontSize=10, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#003366'), spaceAfter=6)))

    notes = """
Patient presented to the Emergency Department at 02:34 AM on 14 March 2025 with a 6-hour history
of progressive right lower quadrant pain, associated with fever (38.9°C), nausea, and anorexia.
Physical examination revealed rebound tenderness at McBurney's point. Rovsing's sign positive.

Investigations performed: Complete Blood Count revealed leucocytosis (WBC 14.2 x10³/µL).
CT Abdomen confirmed acute appendicitis with no evidence of perforation.

Patient was prepared for emergency laparoscopic appendectomy under general anaesthesia.
Surgery performed by Dr. Khalid Mansour Al-Farsi on 14 March 2025. Procedure uneventful.
Estimated operative time: 47 minutes. No intraoperative complications.

Post-operative recovery was unremarkable. Patient was ambulatory by post-operative day 1.
Discharged on 16 March 2025 with oral antibiotics (Augmentin 625mg BD x 5 days) and
analgesia (Ibuprofen 400mg TDS PRN). Follow-up scheduled for 21 March 2025.
    """.strip()
    story.append(Paragraph(notes, ParagraphStyle(
        'notes', fontSize=9, fontName='Helvetica',
        leading=14, textColor=colors.HexColor('#2c2c2c'))))

    story.append(Spacer(1, 8))
    story.append(field_table([
        ["Attending Physician:", "Dr. Khalid Mansour Al-Farsi"],
        ["Signature:",           "___________________________"],
        ["Record Date:",         "16 March 2025"],
    ]))

    doc.build(story)
    return path


# ─────────────────────────────────────────────
# DOC 4: TREATMENT SUMMARY
# ─────────────────────────────────────────────
def make_treatment_summary():
    path = os.path.join(OUT_DIR, "04_treatment_summary.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    story = []

    story.append(Paragraph("CITY MEDICAL CENTRE", ParagraphStyle(
        'h', fontSize=16, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0d3b66'))))
    story.append(Paragraph("SURGICAL TREATMENT SUMMARY", ParagraphStyle(
        'sh', fontSize=11, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#333333'), spaceAfter=2)))
    story.append(Paragraph("For Insurance & Medico-Legal Purposes", ParagraphStyle(
        'sub', fontSize=8, fontName='Helvetica-Oblique',
        textColor=colors.HexColor('#888888'), spaceAfter=6)))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor('#cccccc'), spaceAfter=8))

    story.append(field_table([
        ["Patient Name:",          "Ahmed Ali Al-Rashidi"],
        ["Medical Record No:",     "CMC-MRN-008821"],
        ["Insurance Policy No:",   "MHI-2024-ARA-00847"],
        ["Procedure:",             "Laparoscopic Appendectomy"],
        ["Procedure Code (CPT):",  "CPT-44950"],
        ["ICD-10 Diagnosis Code:", "K37 — Unspecified appendicitis"],
        ["Date of Procedure:",     "14 March 2025"],
        ["Procedure Duration:",    "47 minutes"],
        ["Anaesthesia Type:",      "General (CPT-00840)"],
        ["Surgeon:",               "Dr. Khalid Mansour Al-Farsi, FRCS"],
        ["Anaesthesiologist:",     "Dr. Priya Nair"],
        ["Facility:",              "City Medical Centre, Dubai"],
        ["Outcome:",               "Successful — no complications"],
    ]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("POST-OPERATIVE INSTRUCTIONS", ParagraphStyle(
        'sec', fontSize=10, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#003366'), spaceAfter=6)))

    story.append(Paragraph(
        "1. Rest for 2 weeks. Avoid strenuous activity and heavy lifting.\n"
        "2. Augmentin 625mg twice daily for 5 days.\n"
        "3. Ibuprofen 400mg three times daily as needed for pain.\n"
        "4. Wound care: keep laparoscopic port sites clean and dry. Remove dressing after 48 hours.\n"
        "5. Follow-up appointment: 21 March 2025 with Dr. Al-Farsi.\n"
        "6. Return to emergency immediately if fever exceeds 38.5°C, wound discharge, or severe pain.",
        ParagraphStyle('instr', fontSize=9, fontName='Helvetica',
                       leading=15, textColor=colors.HexColor('#2c2c2c'))))

    story.append(Spacer(1, 10))
    story.append(Paragraph("CERTIFICATION", ParagraphStyle(
        'sec', fontSize=10, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#003366'), spaceAfter=4)))
    story.append(Paragraph(
        "I certify that the above information is a true and accurate summary of the treatment "
        "provided to the named patient at City Medical Centre, Dubai.",
        ParagraphStyle('cert', fontSize=9, fontName='Helvetica-Oblique',
                       textColor=colors.HexColor('#555555'), leading=13)))
    story.append(Spacer(1, 10))
    story.append(field_table([
        ["Surgeon Signature:", "___________________________"],
        ["Date Issued:",       "17 March 2025"],
        ["Hospital Stamp:",    "[CITY MEDICAL CENTRE — OFFICIAL]"],
    ]))

    doc.build(story)
    return path


# ─────────────────────────────────────────────
# DOC 5: PAYSLIP
# ─────────────────────────────────────────────
def make_payslip():
    path = os.path.join(OUT_DIR, "05_payslip.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    story = []

    story.append(Paragraph("NEXACORE TECHNOLOGIES LLC", ParagraphStyle(
        'h', fontSize=16, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#1a3a5c'))))
    story.append(Paragraph("P.O. Box 44821, Dubai Internet City, Dubai, UAE", ParagraphStyle(
        'sh', fontSize=8, fontName='Helvetica',
        textColor=colors.HexColor('#888888'), spaceAfter=2)))
    story.append(Paragraph("Trade License: DED-2018-LLC-088741", ParagraphStyle(
        'sh2', fontSize=8, fontName='Helvetica',
        textColor=colors.HexColor('#aaaaaa'), spaceAfter=6)))
    story.append(HRFlowable(width="100%", thickness=1,
                             color=colors.HexColor('#1a3a5c'), spaceAfter=8))

    story.append(Paragraph("SALARY STATEMENT — FEBRUARY 2025", ParagraphStyle(
        'title', fontSize=13, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#1a3a5c'), alignment=TA_CENTER, spaceAfter=8)))

    story.append(field_table([
        ["Employee Name:",     "Ahmed Ali Al-Rashidi"],
        ["Employee ID:",       "NXT-EMP-00412"],
        ["Designation:",       "Senior Software Engineer"],
        ["Department:",        "Product Engineering"],
        ["Pay Period:",        "01 February 2025 — 28 February 2025"],
        ["Payment Date:",      "28 February 2025"],
        ["Bank:",              "Emirates NBD"],
        ["Account No:",        "****8821"],
    ]))

    story.append(Spacer(1, 10))

    earnings = [
        ["EARNINGS", "Amount (AED)"],
        ["Basic Salary", "12,000.00"],
        ["Housing Allowance", "3,500.00"],
        ["Transport Allowance", "1,000.00"],
        ["Performance Bonus", "1,200.00"],
        ["GROSS EARNINGS", "17,700.00"],
    ]
    deductions = [
        ["DEDUCTIONS", "Amount (AED)"],
        ["Social Insurance (Employee)", "550.00"],
        ["Health Insurance Premium", "180.00"],
        ["NET SALARY", "16,970.00"],
    ]



    def make_pay_subtable(data):
        t = Table(data, colWidths=[65*mm, 30*mm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a3a5c')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME', (0,1), (-1,-2), 'Helvetica'),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, colors.HexColor('#f7f9fc')]),
            ('LINEABOVE', (0,-1), (-1,-1), 0.8, colors.HexColor('#1a3a5c')),
            ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#dddddd')),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
        ]))
        return t

    story.append(make_pay_subtable(earnings))
    story.append(Spacer(1, 6))
    story.append(make_pay_subtable(deductions))

    story.append(Spacer(1, 10))
    story.append(Paragraph("EMPLOYER CERTIFICATION", ParagraphStyle(
        'sec', fontSize=9, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#333333'), spaceAfter=4)))
    story.append(Paragraph(
        "This is a computer-generated payslip. It certifies that the above named employee "
        "is currently employed with NexaCore Technologies LLC on a full-time basis and "
        "that the stated salary was credited to the employee's bank account on the payment date above.",
        ParagraphStyle('cert', fontSize=8, fontName='Helvetica-Oblique',
                       textColor=colors.HexColor('#555555'), leading=12)))

    story.append(Spacer(1, 10))
    story.append(field_table([
        ["HR Manager Signature:", "___________________________"],
        ["Company Stamp:",        "[NEXACORE TECHNOLOGIES LLC — OFFICIAL]"],
        ["Generated Date:",       "28 February 2025"],
    ]))

    doc.build(story)
    return path


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    files = [
        make_insurance_form(),
        make_invoice(),
        make_patient_record(),
        make_treatment_summary(),
        make_payslip(),
    ]
    print("\n✅ Generated sample claim documents:\n")
    for f in files:
        size = os.path.getsize(f)
        print(f"  {f}  ({size:,} bytes)")

    print("\n📋 Intentional inconsistencies baked in:")
    print("  [MEDIUM] DOB mismatch — insurance form + invoice say 22 July 1990,")
    print("                          patient record says 22 July 1988 (2-year gap)")
    print("  [MEDIUM] Invoice date (12 March) is 2 days BEFORE treatment date (14 March)")
    print("           — known billing fraud pattern")
    print("  [LOW]    Attending physician 'Dr. Khalid Mansour Al-Farsi' is not listed")
    print("           in the insurance network (not checkable from docs alone — needs lookup)")
    print("\n  Expected agent verdict: MANUAL_REVIEW")
    print("  Expected flags: 2 MEDIUM, 1 LOW")
    print("  Expected confidence: MEDIUM\n")
