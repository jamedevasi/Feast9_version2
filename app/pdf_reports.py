"""All PDF generators (feast9_v2_agents.md §10). Every function returns bytes and
never writes to disk — callers stream it straight from a BytesIO via send_file."""
import io
import json
from xml.sax.saxutils import escape as _esc

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import db
from app.constants import DEFAULT_CLINIC_NAME
from app.validators import compute_age

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


def _build(story):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
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
    age = compute_age(patient.get("date_of_birth", ""))
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

def generate_prescription_pdf(prescription, case, patient):
    """With allergy alert banner if allergies recorded (feast9_v2_agents.md §10)."""
    story = _header("Prescription", _patient_line(patient))

    allergies = json.loads(patient.get("allergies_json") or "[]")
    if patient.get("allergies_other"):
        allergies = allergies + [patient["allergies_other"]]
    if allergies:
        story.append(P(f"ALLERGY ALERT: {', '.join(allergies)}", ALERT))
        story.append(Spacer(1, 10))

    story.append(P(f"Case: {case['title']}", BODY))
    story.append(Paragraph(f"Date: {prescription['prescribed_date']}", BODY))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Rx", HEADING))
    for line in prescription["rx_details"].splitlines() or [prescription["rx_details"]]:
        story.append(P(line, BODY) if line else Spacer(1, 4))

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


def generate_consent_pdf(case, patient, signature_bytes=None):
    """With embedded signature or 'Paper consent on file' (feast9_v2_agents.md §10)."""
    story = _header("Consent Form", _patient_line(patient))

    story.append(P(f"Case: {case['title']}", BODY))
    story.append(P(f"Procedures: {_procedures_for(case)}", BODY))
    story.append(Spacer(1, 10))

    if case.get("consent_recorded"):
        story.append(Paragraph(f"Consent recorded on {case['consent_recorded_at']}.", BODY))
        signature_flowable = _consent_signature_flowable(signature_bytes) if signature_bytes else None
        if signature_flowable is not None:
            story.append(Spacer(1, 6))
            story.append(Paragraph("Signature:", MUTED))
            story.append(signature_flowable)
        else:
            story.append(Paragraph("Paper consent on file.", MUTED))
        if case.get("consent_notes"):
            story.append(Spacer(1, 6))
            story.append(P(case["consent_notes"], BODY))
    else:
        story.append(Paragraph("No consent recorded for this case.", ALERT))

    return _build(story)


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
