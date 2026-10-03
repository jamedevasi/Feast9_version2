"""All PDF generators (feast9_v2_agents.md §10). Every function returns bytes and
never writes to disk — callers stream it straight from a BytesIO via send_file."""
import io
import json
from xml.sax.saxutils import escape as _esc

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Flowable, HRFlowable, Image, KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import db
from app.constants import DEFAULT_CLINIC_NAME
from app.validators import patient_age, today_iso

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle("Feast9Title", parent=_styles["Title"], fontSize=16, spaceAfter=2, alignment=0)
SUBTITLE = ParagraphStyle("Feast9Subtitle", parent=_styles["Normal"], fontSize=9,
                           textColor=colors.HexColor("#5b6672"), spaceAfter=10)
HEADING = ParagraphStyle("Feast9Heading", parent=_styles["Heading2"], fontSize=12,
                          spaceBefore=14, spaceAfter=4)
BODY = _styles["BodyText"]
MUTED = ParagraphStyle("Feast9Muted", parent=BODY, textColor=colors.HexColor("#5b6672"), fontSize=9)
ALERT = ParagraphStyle("Feast9Alert", parent=BODY, textColor=colors.HexColor("#b91c1c"),
                        fontName="Helvetica-Bold")
EMPTY = ParagraphStyle("Feast9Empty", parent=BODY, textColor=colors.HexColor("#5b6672"), fontSize=9,
                        spaceAfter=6)

_TABLE_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f7f8fa")),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#d8dee4")),
    ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#e5e9ee")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
])


def P(text, style=BODY):
    """A Paragraph with its text XML-escaped — every field here can hold free-form,
    user-typed text (rx_details, notes, reasons, names...), and ReportLab's Paragraph
    parses its content as mini-XML, so a raw '&' or '<' would otherwise break rendering."""
    return Paragraph(_esc(str(text)), style)


def _build(story, pagesize=letter, margin=0.75 * inch):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize,
        topMargin=margin, bottomMargin=margin,
        leftMargin=margin, rightMargin=margin,
        title="Feast9",
    )
    doc.build(story)
    return buf.getvalue()


def _clinic_letterhead():
    """(name, contact_line) from Settings > Clinic Details — falls back to the app name
    when unset, and simply omits the contact line rather than showing empty separators."""
    name = db.get_setting("clinic_name", "") or DEFAULT_CLINIC_NAME
    contact_bits = [
        b for b in (
            db.get_setting("clinic_address", ""),
            db.get_setting("clinic_phone", ""),
            db.get_setting("clinic_email", ""),
        ) if b
    ]
    return name, " · ".join(contact_bits)


def _header(title, subtitle=""):
    clinic_name, clinic_contact = _clinic_letterhead()
    story = [P(clinic_name, MUTED)]
    if clinic_contact:
        story.append(P(clinic_contact, MUTED))
    story.append(P(title, TITLE))
    if subtitle:
        story.append(P(subtitle, SUBTITLE))
    else:
        story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#d8dee4"), thickness=1))
    story.append(Spacer(1, 8))
    return story


def _table(headers, rows, col_widths=None):
    """Every cell is escaped — table cells can hold the same free-form text as a
    Paragraph (patient names, notes, reasons), so the same XML-escaping applies."""
    data = [[_esc(str(h)) for h in headers]] + [[_esc(str(cell)) for cell in row] for row in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(_TABLE_STYLE)
    return t


def _patient_line(patient):
    age = patient_age(patient)
    bits = [patient["name"]]
    if age is not None:
        bits.append(f"{age}y")
    if patient.get("sex"):
        bits.append(patient["sex"])
    if patient.get("mobile"):
        bits.append(patient["mobile"])
    return " · ".join(bits)


def _money(value):
    return f"Rs. {value:,.2f}"


def _procedures_for(case):
    try:
        procedures = json.loads(case.get("procedures_json") or "[]")
    except ValueError:
        procedures = []
    if case.get("custom_procedure"):
        procedures = procedures + [case["custom_procedure"]]
    return ", ".join(procedures) if procedures else "—"


# ── generate_prescription_pdf ───────────────────────────────────────────────

_RX_LABEL = ParagraphStyle("Feast9RxLabel", parent=MUTED, fontSize=8, spaceAfter=1)
_RX_NAME = ParagraphStyle("Feast9RxName", parent=BODY, fontName="Helvetica-Bold", fontSize=11)
_RX_CELL = ParagraphStyle("Feast9RxCell", parent=BODY, fontSize=9, leading=11)
_RX_HEAD = ParagraphStyle("Feast9RxHead", parent=_RX_CELL, fontName="Helvetica-Bold")
_NOT_RECORDED = "Not recorded"


def _prescription_parties(prescription, patient, doctor):
    """Two side-by-side blocks: the prescriber (name, qualifications, registration number) and
    the patient (name, age / date of birth, sex, address), with the date of issue."""
    doctor = doctor or {}
    reg = doctor.get("registration_number") or _NOT_RECORDED
    if doctor.get("registration_number") and doctor.get("registration_council"):
        reg = f"{reg} ({doctor['registration_council']})"
    left = [
        P("PRESCRIBED BY", _RX_LABEL),
        P(doctor.get("name") or _NOT_RECORDED, _RX_NAME),
        P(doctor.get("qualifications") or "Qualifications: " + _NOT_RECORDED, _RX_CELL),
        P(f"Reg. No.: {reg}", _RX_CELL),
    ]

    age = patient_age(patient)
    age_bits = []
    if age is not None:
        age_bits.append(f"Age: {age} years")
    if patient.get("date_of_birth"):
        age_bits.append(f"DOB: {patient['date_of_birth']}")
    age_bits.append(f"Sex: {patient.get('sex') or _NOT_RECORDED}")
    right = [
        P("PATIENT", _RX_LABEL),
        P(patient["name"], _RX_NAME),
        P(" · ".join(age_bits), _RX_CELL),
    ]
    if patient.get("address"):
        right.append(P(f"Address: {patient['address']}", _RX_CELL))
    right.append(P(f"Date of issue: {prescription['prescribed_date']}", _RX_CELL))

    t = Table([[left, right]], colWidths=[3.4 * inch, 3.4 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _medicines_table(medications):
    """Cells are Paragraphs so long names/instructions wrap inside their column."""
    rows = [[P(h, _RX_HEAD) for h in ("#", "Medicine (generic name)", "Dosage", "Frequency", "Route", "Duration", "Instructions")]]
    for n, m in enumerate(medications, start=1):
        name = f"<b>{_esc(str(m.get('generic', '')).upper())}</b>"
        if m.get("brand"):
            name += f" ({_esc(str(m['brand']))})"
        name += f" {_esc(str(m.get('strength', '')))}"
        rows.append([
            P(n, _RX_CELL), Paragraph(name, _RX_CELL), P(m.get("dose", ""), _RX_CELL),
            P(m.get("frequency", ""), _RX_CELL), P(m.get("route", ""), _RX_CELL),
            P(m.get("duration") or "—", _RX_CELL), P(m.get("instructions") or "—", _RX_CELL),
        ])
    t = Table(rows, colWidths=[w * inch for w in (0.3, 2.2, 0.85, 1.05, 0.8, 0.7, 0.9)], repeatRows=1)
    t.setStyle(_TABLE_STYLE)
    return t


def generate_prescription_pdf(prescription, case, patient, doctor=None):
    """The particulars a prescription must carry: the clinic's contact details (letterhead),
    the prescriber's name / qualifications / registration number, the patient's name, age or
    date of birth, sex and address, the date of issue, the diagnosis, and each medicine by
    generic name with strength, dosage, frequency and route. An allergy alert banner is shown
    if allergies are recorded (feast9_v2_agents.md §10). A prescription saved before the
    structured form existed prints its original free text under the same heading blocks."""
    story = _header("Prescription")
    story.append(_prescription_parties(prescription, patient, doctor))

    allergies = json.loads(patient.get("allergies_json") or "[]")
    if patient.get("allergies_other"):
        allergies = allergies + [patient["allergies_other"]]
    if allergies:
        story.append(P(f"ALLERGY ALERT: {', '.join(allergies)}", ALERT))
        story.append(Spacer(1, 6))

    medications = prescription.get("medications") or []
    if medications:
        story.append(Paragraph("Diagnosis", HEADING))
        story.append(P(prescription.get("diagnosis") or _NOT_RECORDED, BODY))
        story.append(Paragraph("Rx", HEADING))
        story.append(_medicines_table(medications))
        if prescription.get("advice"):
            story.append(Paragraph("Advice", HEADING))
            for line in prescription["advice"].splitlines():
                story.append(P(line, BODY) if line else Spacer(1, 4))
    else:
        story.append(P(f"Case: {case['title']}", BODY))
        story.append(Paragraph("Rx", HEADING))
        for line in prescription["rx_details"].splitlines() or [prescription["rx_details"]]:
            story.append(P(line, BODY) if line else Spacer(1, 4))

    doctor = doctor or {}
    story.append(Spacer(1, 48))
    signature = [P("_" * 32, _RX_CELL), P("Signature", _RX_LABEL), P(doctor.get("name") or "", _RX_CELL)]
    if doctor.get("registration_number"):
        signature.append(P(f"Reg. No.: {doctor['registration_number']}", _RX_CELL))
    sig = Table([["", signature]], colWidths=[4.2 * inch, 2.6 * inch])
    sig.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(sig)

    return _build(story)


# ── generate_case_summary_pdf ───────────────────────────────────────────────

def generate_case_summary_pdf(case, patient, payments, balance, cost_revisions, can_view_financial):
    """Cost, payments, consent status (feast9_v2_agents.md §10)."""
    story = _header(case["title"], _patient_line(patient))

    story.append(Paragraph("Case Details", HEADING))
    story.append(_table(
        ["Status", "Procedures", "Opened", "Closed"],
        [[case["status"], _procedures_for(case), case.get("created_at", ""), case.get("closed_at") or "—"]],
    ))

    story.append(Paragraph("Consent", HEADING))
    if case.get("consent_recorded"):
        story.append(Paragraph(f"Recorded on {case['consent_recorded_at']}.", BODY))
        if case.get("consent_notes"):
            story.append(P(case["consent_notes"], BODY))
    else:
        story.append(Paragraph("No consent recorded.", EMPTY))

    story.append(Paragraph("Financial Summary", HEADING))
    if can_view_financial:
        story.append(_table(
            ["Total Cost", "Paid", "Balance"],
            [[_money(case["total_cost"]), _money(case["total_cost"] - balance), _money(balance)]],
        ))
        if payments:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Payments", HEADING))
            story.append(_table(
                ["Date", "Amount", "Method", "Reference"],
                [[p["payment_date"], _money(p["amount"]), p["method"] or "—", p["reference"] or "—"] for p in payments],
            ))
        if cost_revisions:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Cost Revisions", HEADING))
            story.append(_table(
                ["Date", "Old Cost", "New Cost", "Reason"],
                [[r["changed_at"], _money(r["old_cost"]), _money(r["new_cost"]), r["reason"] or "—"] for r in cost_revisions],
            ))
    else:
        story.append(Paragraph("Restricted — financial data is not available to your role.", EMPTY))

    return _build(story)


# ── generate_patient_summary_pdf ────────────────────────────────────────────

def generate_patient_summary_pdf(patient, cases, prescriptions, appointments, can_view_financial):
    """All cases and history (feast9_v2_agents.md §10)."""
    story = _header(patient["name"], _patient_line(patient))

    story.append(Paragraph("Contact Details", HEADING))
    story.append(_table(
        ["Mobile", "Email", "Address"],
        [[patient.get("mobile") or "—", patient.get("email") or "—", patient.get("address") or "—"]],
    ))

    medical_conditions = json.loads(patient.get("medical_conditions_json") or "[]")
    if patient.get("medical_conditions_other"):
        medical_conditions = medical_conditions + [patient["medical_conditions_other"]]
    allergies = json.loads(patient.get("allergies_json") or "[]")
    if patient.get("allergies_other"):
        allergies = allergies + [patient["allergies_other"]]
    if medical_conditions or allergies or patient.get("is_pregnant") or patient.get("is_nursing"):
        story.append(Paragraph("Medical Alerts", HEADING))
        if allergies:
            story.append(P(f"ALLERGIES: {', '.join(allergies)}", ALERT))
        if medical_conditions:
            story.append(P(f"Conditions: {', '.join(medical_conditions)}", BODY))
        if patient.get("is_pregnant"):
            story.append(Paragraph("Currently pregnant.", BODY))
        if patient.get("is_nursing"):
            story.append(Paragraph("Currently nursing.", BODY))

    story.append(Paragraph("Treatment Cases", HEADING))
    if cases:
        if can_view_financial:
            rows = [[c["title"], c["status"], _procedures_for(c), _money(c["total_cost"])] for c in cases]
            story.append(_table(["Case", "Status", "Procedures", "Total Cost"], rows))
        else:
            rows = [[c["title"], c["status"], _procedures_for(c)] for c in cases]
            story.append(_table(["Case", "Status", "Procedures"], rows))
    else:
        story.append(Paragraph("No treatment cases yet.", EMPTY))

    story.append(Paragraph("Prescription History", HEADING))
    if prescriptions:
        story.append(_table(
            ["Date", "Case", "Prescription"],
            [[p["prescribed_date"], p["case_title"], p["rx_details"]] for p in prescriptions],
            col_widths=[0.9 * inch, 1.6 * inch, 3.5 * inch],
        ))
    else:
        story.append(Paragraph("No prescriptions recorded.", EMPTY))

    story.append(Paragraph("Appointment History", HEADING))
    if appointments:
        story.append(_table(
            ["Date", "Time", "Doctor", "Status"],
            [[a["appt_date"], a["start_time"], a.get("doctor_name") or "—", a["status"]] for a in appointments],
        ))
    else:
        story.append(Paragraph("No appointments recorded.", EMPTY))

    return _build(story)


# ── generate_report_pdf ─────────────────────────────────────────────────────

def generate_report_pdf(start, end, context):
    """Period stats + revenue + pending payments (feast9_v2_agents.md §10). `context`
    is the same dict reports_routes._report_context() builds for the on-screen page."""
    story = _header("Report", f"{start} to {end}")

    story.append(Paragraph("Period Summary", HEADING))
    story.append(_table(
        ["Revenue Collected", "Cases Closed", "New Cases", "New Patients"],
        [[
            _money(context["revenue_collected"]), str(context["cases_closed_count"]),
            str(context["new_cases_count"]), str(context["new_patients_count"]),
        ]],
    ))

    story.append(Paragraph("Revenue Overview — All Time", HEADING))
    ro = context["revenue_overview"]
    story.append(_table(
        ["Billed", "Collected", "Outstanding"],
        [[_money(ro["billed"]), _money(ro["collected"]), _money(ro["outstanding"])]],
    ))

    story.append(Paragraph("Pending Payments by Patient & Case", HEADING))
    pending = context["pending_payments"]
    if pending:
        story.append(_table(
            ["Patient", "Case", "Total Cost", "Paid", "Balance"],
            [[r["patient_name"], r["case_title"], _money(r["total_cost"]), _money(r["paid"]), _money(r["balance"])]
             for r in pending],
        ))
    else:
        story.append(Paragraph("No pending payments — every case is fully paid.", EMPTY))

    story.append(Paragraph("Doctor-wise Revenue by Period", HEADING))
    doctor_revenue = context["doctor_revenue"]
    if doctor_revenue:
        story.append(_table(
            ["Doctor", "Billed", "Collected", "Collection Rate"],
            [[d["doctor_name"], _money(d["billed"]), _money(d["collected"]), f"{d['collection_rate']:.0f}%"]
             for d in doctor_revenue],
        ))
    else:
        story.append(Paragraph("No doctors on file yet.", EMPTY))

    story.append(Paragraph("Patient Retention", HEADING))
    retention = context["retention"]
    story.append(Paragraph(
        f"{retention['total_patients']} patients on file · lapsed = no visit in the last "
        f"{retention['threshold_months']} months (since {retention['cutoff_date']})", BODY,
    ))
    if retention["lapsed"]:
        story.append(_table(
            ["Patient", "Mobile", "Last Visit"],
            [[p["name"], p.get("mobile") or "—", p.get("last_activity") or "—"] for p in retention["lapsed"]],
        ))
    else:
        story.append(Paragraph("All clear — no lapsed patients.", EMPTY))

    story.append(Paragraph("Payments Received in Period", HEADING))
    payments_in_period = context["payments_in_period"]
    if payments_in_period:
        story.append(_table(
            ["Date", "Patient", "Case", "Amount", "Method"],
            [[p["payment_date"], p["patient_name"], p["case_title"], _money(p["amount"]), p["method"] or "—"]
             for p in payments_in_period],
        ))
    else:
        story.append(Paragraph("No payments recorded in this period.", EMPTY))

    story.append(Paragraph("Cases Closed in Period", HEADING))
    cases_closed = context["cases_closed_in_period"]
    if cases_closed:
        story.append(_table(
            ["Closed", "Patient", "Case", "Total Cost"],
            [[c["closed_at"], c["patient_name"], c["title"], _money(c["total_cost"])] for c in cases_closed],
        ))
    else:
        story.append(Paragraph("No cases closed in this period.", EMPTY))

    return _build(story)


# ── generate_consent_pdf ────────────────────────────────────────────────────

def _consent_signature_flowable(signature_bytes, max_width=2.5 * inch, max_height=1.2 * inch):
    """A right-sized Image flowable for a captured signature — scaled to fit within
    max_width/max_height while preserving aspect ratio, never at the canvas's native
    pixel size (which can be far larger or smaller than makes sense on a printed page).
    Returns None if the stored bytes can't actually be decoded as an image — the file is
    validated with PIL before being saved (case_routes._save_consent_signature), but this
    stays defensive in case a file is later corrupted on disk."""
    try:
        with PILImage.open(io.BytesIO(signature_bytes)) as img:
            native_width, native_height = img.size
    except Exception:
        return None
    scale = min(max_width / native_width, max_height / native_height, 1)
    return Image(io.BytesIO(signature_bytes), width=native_width * scale, height=native_height * scale)


# The consent form's wording — the treating doctors should review it before use.
CONSENT_EXPLAINED = [
    "What the treatment involves and why it is recommended",
    "The expected benefits",
    "Possible risks and complications, including: " + "_" * 44,
    "Other options, including no treatment, and their risks",
    "Local anaesthesia may be used (numbness; rarely, an allergic reaction)",
    "X-rays and clinical photographs may be taken and kept in my record",
    "Results cannot be guaranteed; further treatment may be needed",
    "I must follow post-treatment instructions and attend follow-up visits",
]
CONSENT_DECLARATION = (
    "I have read this form, or it has been read to me in a language I understand "
    "(language: ____________). My questions have been answered. I agree to the treatment above, "
    "and I may withdraw consent at any stage before it is carried out. The medical history and "
    "allergies I declared are true to my knowledge: Yes / No"
)

_C_BODY = ParagraphStyle("Feast9ConsentBody", parent=BODY, fontSize=10, leading=13)
_C_BOLD = ParagraphStyle("Feast9ConsentBold", parent=_C_BODY, fontName="Helvetica-Bold")
_C_HEAD = ParagraphStyle("Feast9ConsentHead", parent=_C_BODY, fontName="Helvetica-Bold", fontSize=11,
                         spaceBefore=10, spaceAfter=4)
_C_SMALL = ParagraphStyle("Feast9ConsentSmall", parent=_C_BODY, fontSize=8.5, leading=10.5,
                          textColor=colors.HexColor("#5b6672"))
_C_TITLE = ParagraphStyle("Feast9ConsentTitle", parent=TITLE, fontSize=15, spaceBefore=6)
_C_LINE = colors.HexColor("#c9d1d9")
_C_GRID = TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.5, _C_LINE),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
])
_BLANK = "_" * 22


class _TickBox(Flowable):
    """An empty square to tick by hand (base-14 Helvetica has no ☐ character)."""
    size = 9

    def wrap(self, avail_width, avail_height):
        return self.size, self.size

    def draw(self):
        self.canv.setStrokeColor(colors.HexColor("#1f2933"))
        self.canv.setLineWidth(0.8)
        self.canv.rect(0, 0, self.size, self.size)


def _consent_field(label, value):
    """'Label: value' with the label bold and the value escaped (it's user-typed)."""
    return Paragraph(f"<b>{_esc(label)}:</b> {_esc(str(value))}", _C_BODY)


def generate_consent_pdf(case, patient, doctor=None, signature_bytes=None):
    """One A4 sheet per case, printed for the patient (or guardian, if under 18), the doctor
    and a witness to sign on paper — consent is collected offline only. Feast9 fills in what
    it knows; everything else is completed by hand. The estimated cost is deliberately blank:
    guest doctors can print this form but must not see costs. `signature_bytes` is only for
    cases recorded with the old on-screen signature pad."""
    doctor = doctor or {}
    width = A4[0] - inch  # 0.5in margins
    clinic_name, clinic_contact = _clinic_letterhead()
    story = [P(clinic_name, _C_BOLD)]
    if clinic_contact:
        story.append(P(clinic_contact, _C_SMALL))
    story.append(Paragraph("CONSENT FOR DENTAL TREATMENT", _C_TITLE))
    story.append(P(f"Case reference: #{case['id']} · Date printed: {today_iso()}", _C_SMALL))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#d8dee4"), thickness=1, spaceBefore=3))

    age = patient_age(patient)
    age_sex = " / ".join(x for x in (f"{age}y" if age is not None else "", patient.get("sex") or "") if x) or "—"
    story.append(P("Patient", _C_HEAD))
    t = Table([[_consent_field("Name", patient["name"]), _consent_field("Age / Sex", age_sex)],
               [_consent_field("Mobile", patient.get("mobile") or "—"), _consent_field("Patient ID", patient["id"])]],
              colWidths=[width * 0.6, width * 0.4])
    t.setStyle(_C_GRID)
    story.append(t)

    doctor_bits = [doctor.get("name") or "—"]
    if doctor.get("qualifications"):
        doctor_bits.append(doctor["qualifications"])
    if doctor.get("registration_number"):
        doctor_bits.append(f"Reg. No. {doctor['registration_number']}")
    story.append(P("Treatment proposed", _C_HEAD))
    t = Table([
        [_consent_field("Case", case["title"]), _consent_field("Tooth / area", _BLANK)],
        [_consent_field("Procedure(s)", _procedures_for(case)), _consent_field("Estimated visits", "______")],
        [_consent_field("Treating doctor", ", ".join(doctor_bits)),
         Paragraph("<b>Estimated cost:</b> Rs. ________ <font size=8>(estimate)</font>", _C_BODY)],
    ], colWidths=[width * 0.6, width * 0.4])
    t.setStyle(_C_GRID)
    story.append(t)

    story.append(P("The doctor has explained to me (tick each box)", _C_HEAD))
    t = Table([[_TickBox(), P(line, _C_BODY)] for line in CONSENT_EXPLAINED],
              colWidths=[0.3 * inch, width - 0.3 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)

    story.append(P("Declaration", _C_HEAD))
    story.append(P(CONSENT_DECLARATION, _C_BODY))

    story.append(P("Signatures", _C_HEAD))
    rows = [
        [P(h, _C_BOLD) for h in ("Patient", "Guardian (if under 18)", "Doctor", "Witness")],
        [P("Signature:", _C_SMALL)] * 4,
        [Spacer(1, 40)] * 4,
        [P(f"Name: {patient['name']}", _C_BODY), P("Name:", _C_BODY),
         P(f"Name: {doctor.get('name') or ''}", _C_BODY), P("Name:", _C_BODY)],
        [P("", _C_BODY), P("Relationship:", _C_BODY),
         P(f"Reg. No.: {doctor.get('registration_number') or ''}", _C_BODY), P("", _C_BODY)],
        [P("Date:", _C_BODY)] * 4,
    ]
    t = Table(rows, colWidths=[width / 4] * 4)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, _C_LINE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, _C_LINE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _C_LINE),
        ("LINEBELOW", (0, 2), (-1, 2), 0.5, _C_LINE),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f7f8fa")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    story.append(t)

    story.append(Spacer(1, 8))
    office = [Paragraph("<b>Office use</b> — Consent recorded in Feast9 by: ____________   "
                        "Date: __________   Filed in: ______________", _C_BODY)]
    if case.get("consent_recorded"):
        recorded = f"Recorded in Feast9 on {case['consent_recorded_at']}"
        if case.get("consent_notes"):
            recorded += f" — {case['consent_notes']}"
        office.append(P(recorded, _C_SMALL))
        signature_flowable = (
            _consent_signature_flowable(signature_bytes, max_width=1.8 * inch, max_height=0.5 * inch)
            if signature_bytes else None
        )
        if signature_flowable is not None:
            office.append(P("Signature captured on screen:", _C_SMALL))
            office.append(signature_flowable)
    t = Table([[office]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, _C_LINE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f8fa")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    # Always one sheet: unusually long names, titles or procedure lists shrink the whole form
    # slightly instead of spilling onto a second page (normal forms are left at full size).
    frame_padding = 12  # SimpleDocTemplate's frame pads 6pt on each side
    one_sheet = KeepInFrame(width - frame_padding, A4[1] - inch - frame_padding, story, mode="shrink")
    return _build([one_sheet], pagesize=A4, margin=0.5 * inch)


# ── generate_data_access_pdf ────────────────────────────────────────────────

def generate_data_access_pdf(patient, cases, visit_notes, dental_chart_entries, prescriptions, payments, appointments):
    """DPDP Phase 2 right-to-access export (feast9_v2_agents.md §10) — the patient's
    own data, handed back to them on an Access request, so clinical text (visit
    notes/prescriptions) is included in full here unlike the audit log's redaction.
    Dental chart history is the full append-only log, not just the derived current
    state, for the same reason — it's all personal data being processed."""
    story = _header("Data Access Export", _patient_line(patient))

    story.append(Paragraph("Contact Details", HEADING))
    story.append(_table(
        ["Date of Birth", "Sex", "Mobile", "Email", "Address"],
        [[patient.get("date_of_birth") or "—", patient.get("sex") or "—", patient.get("mobile") or "—",
          patient.get("email") or "—", patient.get("address") or "—"]],
    ))

    story.append(Paragraph("Treatment Cases", HEADING))
    if cases:
        story.append(_table(
            ["Case", "Status", "Procedures", "Total Cost"],
            [[c["title"], c["status"], _procedures_for(c), _money(c["total_cost"])] for c in cases],
        ))
    else:
        story.append(Paragraph("No treatment cases.", EMPTY))

    story.append(Paragraph("Visit Notes", HEADING))
    if visit_notes:
        story.append(_table(
            ["Date", "Case", "Note"],
            [[n["visit_date"], n["case_title"], n["note"]] for n in visit_notes],
            col_widths=[0.9 * inch, 1.6 * inch, 3.5 * inch],
        ))
    else:
        story.append(Paragraph("No visit notes recorded.", EMPTY))

    story.append(Paragraph("Dental Chart History", HEADING))
    if dental_chart_entries:
        story.append(_table(
            ["Recorded", "Tooth", "Surface", "Finding", "Status", "Notes"],
            [[e["recorded_at"], e["tooth_id"], e["surface"], e["finding"], e["status"], e["notes"] or "—"]
             for e in dental_chart_entries],
            col_widths=[1.1 * inch, 0.6 * inch, 1 * inch, 1 * inch, 0.9 * inch, 1.4 * inch],
        ))
    else:
        story.append(Paragraph("No dental chart entries recorded.", EMPTY))

    story.append(Paragraph("Prescriptions", HEADING))
    if prescriptions:
        story.append(_table(
            ["Date", "Case", "Prescription"],
            [[p["prescribed_date"], p["case_title"], p["rx_details"]] for p in prescriptions],
            col_widths=[0.9 * inch, 1.6 * inch, 3.5 * inch],
        ))
    else:
        story.append(Paragraph("No prescriptions recorded.", EMPTY))

    story.append(Paragraph("Payments", HEADING))
    if payments:
        story.append(_table(
            ["Date", "Case", "Amount", "Method"],
            [[p["payment_date"], p.get("case_title", ""), _money(p["amount"]), p["method"] or "—"] for p in payments],
        ))
    else:
        story.append(Paragraph("No payments recorded.", EMPTY))

    story.append(Paragraph("Appointments", HEADING))
    if appointments:
        story.append(_table(
            ["Date", "Time", "Doctor", "Status"],
            [[a["appt_date"], a["start_time"], a.get("doctor_name") or "—", a["status"]] for a in appointments],
        ))
    else:
        story.append(Paragraph("No appointments recorded.", EMPTY))

    return _build(story)


# ── generate_referral_pdf ───────────────────────────────────────────────────

def generate_referral_pdf(referral, case, patient):
    """Referral letter to specialist (feast9_v2_agents.md §10)."""
    story = _header("Referral Letter", _patient_line(patient))

    story.append(P(f"To: {referral['referred_to']}", BODY))
    if referral.get("speciality"):
        story.append(P(f"Speciality: {referral['speciality']}", BODY))
    story.append(Paragraph(f"Date: {referral['referral_date']}", BODY))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Reason for Referral", HEADING))
    story.append(P(referral["reason"], BODY))

    if referral.get("notes"):
        story.append(Paragraph("Additional Notes", HEADING))
        story.append(P(referral["notes"], BODY))

    story.append(Spacer(1, 16))
    story.append(P(f"Referring case: {case['title']}", MUTED))

    return _build(story)
