"""
Standalone generator for Feast9's end-user documentation:
  - Feast9_User_Manual.pdf            (multi-page reference, ReportLab Platypus)
  - Feast9_Quick_Reference_Card.pdf   (single-page, colourful cheat sheet, ReportLab canvas)

Not part of the running app (no Flask/db import) so it can be run standalone against
a checkout without a live DATA_DIR. Re-run any time the feature set changes.

Usage:
    python generate_manuals.py [output_dir]
"""
import sys
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    PageBreak, KeepTogether, Image,
)

# ── Palette (matches app/static/style.css custom properties) ───────────────
BRAND       = HexColor("#2b6cb0")
BRAND_DARK  = HexColor("#1e4e8c")
BRAND_LIGHT = HexColor("#eaf1fa")
PURPLE      = HexColor("#6d28d9")
TEAL        = HexColor("#0f766e")
DANGER      = HexColor("#b91c1c")
DANGER_BG   = HexColor("#fef2f2")
SUCCESS     = HexColor("#065f46")
SUCCESS_BG  = HexColor("#ecfdf5")
WARNING     = HexColor("#92400e")
WARNING_BG  = HexColor("#fffbeb")
MUTED       = HexColor("#5b6672")
BORDER      = HexColor("#d8dee4")
BG          = HexColor("#f7f8fa")
WHITE       = HexColor("#ffffff")
INK         = HexColor("#1f2933")

TODAY = date.today().strftime("%d %B %Y")


def _blend(c1, c2, t):
    return (
        c1.red + (c2.red - c1.red) * t,
        c1.green + (c2.green - c1.green) * t,
        c1.blue + (c2.blue - c1.blue) * t,
    )


def gradient_rect(c, x, y, w, h, c1, c2, horizontal=True, steps=120):
    """Fills a rect with a smooth linear gradient by drawing thin slivers."""
    for i in range(steps):
        t = i / (steps - 1)
        r, g, b = _blend(c1, c2, t)
        c.setFillColorRGB(r, g, b)
        if horizontal:
            sx = x + (w / steps) * i
            c.rect(sx, y, (w / steps) + 0.6, h, fill=1, stroke=0)
        else:
            sy = y + (h / steps) * i
            c.rect(x, sy, w, (h / steps) + 0.6, fill=1, stroke=0)


def rounded_box(c, x, y, w, h, radius=6, fill=None, stroke=None, stroke_width=1):
    if fill is not None:
        c.setFillColor(fill)
    if stroke is not None:
        c.setStrokeColor(stroke)
        c.setLineWidth(stroke_width)
    c.roundRect(x, y, w, h, radius, fill=1 if fill is not None else 0,
                stroke=1 if stroke is not None else 0)


def badge_dot(c, cx, cy, r, color, letter="", text_color=WHITE):
    c.setFillColor(color)
    c.circle(cx, cy, r, fill=1, stroke=0)
    if letter:
        c.setFillColor(text_color)
        c.setFont("Helvetica-Bold", r * 0.95)
        c.drawCentredString(cx, cy - r * 0.35, letter)


# ═════════════════════════════════════════════════════════════════════════
# USER MANUAL
# ═════════════════════════════════════════════════════════════════════════

_styles = getSampleStyleSheet()

COVER_TITLE = ParagraphStyle("CoverTitle", parent=_styles["Title"], fontSize=30,
                              textColor=WHITE, alignment=TA_CENTER, leading=34)
COVER_SUB = ParagraphStyle("CoverSub", parent=_styles["Normal"], fontSize=13,
                            textColor=BRAND_LIGHT, alignment=TA_CENTER, spaceBefore=10)
COVER_FOOT = ParagraphStyle("CoverFoot", parent=_styles["Normal"], fontSize=10,
                             textColor=WHITE, alignment=TA_CENTER)

H1 = ParagraphStyle("H1", parent=_styles["Heading1"], fontSize=17, textColor=BRAND_DARK,
                     spaceBefore=6, spaceAfter=6, fontName="Helvetica-Bold")
H2 = ParagraphStyle("H2", parent=_styles["Heading2"], fontSize=12.5, textColor=BRAND,
                     spaceBefore=14, spaceAfter=5, fontName="Helvetica-Bold")
H3 = ParagraphStyle("H3", parent=_styles["Heading3"], fontSize=10.5, textColor=INK,
                     spaceBefore=8, spaceAfter=3, fontName="Helvetica-Bold")
BODY = ParagraphStyle("Body", parent=_styles["BodyText"], fontSize=9.6, leading=13.5,
                       textColor=INK, spaceAfter=4)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=14, bulletIndent=4, spaceAfter=3)
NOTE = ParagraphStyle("Note", parent=BODY, textColor=WARNING, backColor=WARNING_BG,
                       borderPadding=6, spaceAfter=8, spaceBefore=4)
TIP = ParagraphStyle("Tip", parent=BODY, textColor=SUCCESS, backColor=SUCCESS_BG,
                      borderPadding=6, spaceAfter=8, spaceBefore=4)
LOCK = ParagraphStyle("Lock", parent=BODY, textColor=DANGER, backColor=DANGER_BG,
                       borderPadding=6, spaceAfter=8, spaceBefore=4)
TOC_ENTRY = ParagraphStyle("TocEntry", parent=BODY, fontSize=10.5, textColor=BRAND_DARK,
                            spaceAfter=6, fontName="Helvetica-Bold")

TABLE_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
    ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG]),
    ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
])


def bullets(items, style=BULLET):
    return [Paragraph(f"&bull;&nbsp;&nbsp;{t}", style) for t in items]


def section(number, title, intro, blocks, roles=""):
    story = [Paragraph(f"{number}. {title}", H1)]
    if roles:
        story.append(role_pill(roles))
    if intro:
        story.append(Paragraph(intro, BODY))
    for block in blocks:
        if isinstance(block, (list, tuple)):
            story.extend(block)
        else:
            story.append(block)
    return story


def role_pill(text):
    t = Table([[Paragraph(f"<b>Who can do this:</b> {text}", ParagraphStyle(
        "Pill", parent=BODY, textColor=BRAND_DARK, fontSize=8.5))]], colWidths=[6.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def manual_first_page(c, doc):
    c.saveState()
    gradient_rect(c, 0, 0, letter[0], letter[1], BRAND_DARK, PURPLE, horizontal=False)
    # decorative circles
    c.setFillColorRGB(1, 1, 1)
    c.setFillAlpha(0.06)
    c.circle(letter[0] * 0.85, letter[1] * 0.82, 160, fill=1, stroke=0)
    c.circle(letter[0] * 0.12, letter[1] * 0.18, 120, fill=1, stroke=0)
    c.setFillAlpha(1)
    c.restoreState()


def manual_later_pages(c, doc):
    c.saveState()
    # top brand bar
    c.setFillColor(BRAND)
    c.rect(0, letter[1] - 0.22 * inch, letter[0], 0.22 * inch, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(0.6 * inch, letter[1] - 0.16 * inch, "FEAST9 — USER MANUAL")
    c.drawRightString(letter[0] - 0.6 * inch, letter[1] - 0.16 * inch, TODAY)
    # footer
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawCentredString(letter[0] / 2, 0.4 * inch, f"Page {doc.page}")
    c.setStrokeColor(BORDER)
    c.line(0.75 * inch, 0.55 * inch, letter[0] - 0.75 * inch, 0.55 * inch)
    c.restoreState()


def build_user_manual(path):
    doc = SimpleDocTemplate(
        path, pagesize=letter,
        topMargin=0.55 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        title="Feast9 User Manual",
    )
    story = []

    # ── Cover page ──
    story.append(Spacer(1, 2.2 * inch))
    story.append(Paragraph("FEAST9", ParagraphStyle(
        "Wordmark", parent=COVER_TITLE, fontSize=52, leading=56)))
    story.append(Paragraph("Dental Clinic Management System", COVER_SUB))
    story.append(Spacer(1, 0.35 * inch))
    story.append(Paragraph("USER MANUAL", ParagraphStyle(
        "CoverBand", parent=COVER_TITLE, fontSize=20, leading=24)))
    story.append(Spacer(1, 2.6 * inch))
    story.append(Paragraph(f"For Receptionists · Doctors · Administrators", COVER_FOOT))
    story.append(Paragraph(f"Version dated {TODAY}", COVER_FOOT))
    story.append(PageBreak())

    # ── Table of contents ──
    story.append(Paragraph("Contents", H1))
    story.append(HRFlowable(width="100%", color=BRAND, thickness=2, spaceAfter=10))
    toc = [
        "1. Welcome & Roles",
        "2. Signing In & Securing Your Account",
        "3. Patients",
        "4. Treatment Cases",
        "5. Dental Chart",
        "6. Appointments & the Calendar",
        "7. The Dashboard",
        "8. Reports & Analytics",
        "9. Financial Assessment",
        "10. DPDP Data-Rights Requests",
        "11. Settings & Administration",
        "12. Security Do's and Don'ts",
        "13. Troubleshooting & FAQ",
    ]
    for entry in toc:
        story.append(Paragraph(entry, TOC_ENTRY))
    story.append(PageBreak())

    # ── 1. Welcome & Roles ──
    story += section("1", "Welcome & Roles", (
        "Feast9 covers the full patient journey for a single-practitioner dental clinic: "
        "registration, treatment cases, clinical records, billing, appointments, reports, "
        "and India's DPDP Act 2023 data-protection requirements. Every staff member signs "
        "in with their own account, and what you can see and do depends on your assigned role."
    ), [[
        Table(
            [[Paragraph("Role", ParagraphStyle("RH", parent=BODY, textColor=WHITE, fontName="Helvetica-Bold")),
              Paragraph("Can do", ParagraphStyle("RH2", parent=BODY, textColor=WHITE, fontName="Helvetica-Bold"))],
             [Paragraph("Receptionist", BODY), Paragraph(
              "Register/search patients, book appointments, add clinical notes, log DPDP "
              "requests, use the calendar. No access to payments, costs, balances, reports, "
              "analytics, financial exports, or backups — this is enforced by the system, "
              "not just hidden from view.", BODY)],
             [Paragraph("Doctor", BODY), Paragraph(
              "Everything a Receptionist can do, plus full financial access (payments, cost "
              "revisions, Reports, Analytics, Financial Assessment), dental charting, consent "
              "recording, clinical-attachment deletion, and resolving DPDP requests.", BODY)],
             [Paragraph("Administrator", BODY), Paragraph(
              "Everything a Doctor can do, plus user management, Doctors/Case Types setup, "
              "Clinic Details, Login Screen branding, backups, and the audit log.", BODY)]],
            colWidths=[1.3 * inch, 5.2 * inch],
        ),
    ]])
    story[-1].setStyle(TABLE_STYLE)
    story.append(Paragraph(
        "If a screen or button you expect isn't there, it is almost always because your "
        "role doesn't include it — this is by design, not a bug.", NOTE))

    story.append(PageBreak())

    # ── 2. Signing In ──
    story += section("2", "Signing In & Securing Your Account", "", [
        [Paragraph("First-time setup", H2)],
        bullets([
            "The very first person to open Feast9 sees a one-time Setup page and creates the "
            "founding Administrator account, including a security question for password recovery.",
            "Every account after that is created by an Administrator from <b>Users</b>.",
        ]),
        [Paragraph("Logging in", H2)],
        bullets([
            "Enter your username and password on the login page.",
            "If your account has Two-Factor Authentication (2FA) turned on, you'll be asked for "
            "a 6-digit code from your authenticator app (or a one-time recovery code) on a "
            "second screen before you're let in.",
            "Forgotten your password? Use <b>Forgot Password</b> on the login page and answer "
            "your security question to set a new one — no email required.",
        ]),
        [Paragraph("Turning on Two-Factor Authentication (recommended for everyone)", H2)],
        bullets([
            "Go to <b>2FA</b> in the top navigation bar.",
            "Scan the QR code with an authenticator app (Google Authenticator, Authy, etc.) or "
            "type the key in manually.",
            "Enter the 6-digit code it shows you to confirm setup.",
            "You will then see a set of one-time <b>recovery codes</b> — write these down and "
            "store them somewhere safe. Each one can be used once if you ever lose your phone. "
            "They are shown only this one time.",
        ]),
        [Paragraph(
            "Lost your phone and your recovery codes? Only an Administrator can reset your 2FA "
            "from the Users page. Don't share recovery codes with anyone, and never photograph "
            "the QR code for someone else's phone.", LOCK)],
        [Paragraph("Signing in with Google (if enabled by your clinic)", H2)],
        bullets([
            "Go to <b>My Account</b> and choose <b>Link Google Account</b> while already signed "
            "in — this is a one-time step that ties your Google identity to your existing Feast9 "
            "account.",
            "Google sign-in can never create a brand-new account and never bypasses your "
            "clinic's normal password/2FA setup on its own — it is only an alternate way in "
            "for an account you have already linked.",
        ]),
        [Paragraph("\"Please sign in again\" prompts", H2)],
        [Paragraph(
            "A handful of sensitive actions — creating or deactivating a user, resetting someone's "
            "2FA, deleting a clinical document, running or downloading a backup — ask you to "
            "confirm your password again if it has been more than 10 minutes since you last "
            "authenticated. This is intentional: it stops someone from misusing a screen you "
            "left open and unattended.", BODY)],
    ])
    story.append(PageBreak())

    # ── 3. Patients ──
    story += section("3", "Patients", "", [
        [Paragraph("Registering a new patient", H2)],
        bullets([
            "Go to <b>Patients -&gt; New Patient</b>.",
            "Name and Sex (Male/Female) are required; enter Date of Birth and the age field "
            "fills in automatically.",
            "Record any medical conditions, allergies, and — for a patient under 18 — a "
            "guardian's name, relation, and a valid mobile number (mandatory for minors).",
            "You must tick the <b>Data Processing Notice</b> checkbox after reading it — "
            "registration cannot be completed without it. This is a legal requirement under "
            "India's DPDP Act and cannot be skipped for any patient.",
            "Communications consent (for reminder messages) is a separate, optional tick-box, "
            "off by default.",
        ]),
        [Paragraph("Finding a patient", H2)],
        bullets([
            "The search box on the Patients page matches name, mobile number, email, address, "
            "and even text inside past visit notes and prescriptions — so you can find a patient "
            "by symptom or medicine name too.",
            "A <b>Historic Import</b> badge marks patients that were bulk-loaded from an old "
            "spreadsheet rather than registered through the app.",
        ]),
        [Paragraph("Reading the patient list's colour dots", H2)],
        bullets([
            '<font color="#b91c1c"><b>Red dot</b></font> — this patient has an overdue follow-up.',
            '<font color="#92400e"><b>Amber dot</b></font> — a follow-up is due within the next 3 days.',
            "No dot — nothing needs attention right now.",
        ]),
        [Paragraph("The patient detail page", H2)],
        [Paragraph(
            "Always shown in this order: <b>Medical Alerts</b> (allergies/conditions at a "
            "glance), <b>Active Treatment Cases</b>, <b>Appointments</b>, and "
            "<b>Contact Details &amp; DPDP Status</b> (which also lists any data-rights requests "
            "for this patient). A cross-case <b>Prescription History</b> is shown further down.",
            BODY)],
        [Paragraph(
            "If a patient's record shows an \"Erased\" banner, an Erasure request has been "
            "completed for them — their personal details are anonymised, but their clinical "
            "and billing history is preserved exactly as required by law.", NOTE)],
    ])
    story.append(PageBreak())

    # ── 4. Treatment Cases ──
    story += section("4", "Treatment Cases", (
        "A Case is one course of treatment for a patient (e.g. \"Root Canal — upper left "
        "molar\"). Open one from the patient's page with <b>New Case</b>. Every case page "
        "always shows the same nine sections, in the same order, so the layout never surprises you:"
    ), [
        bullets([
            "<b>1. Consent Forms</b> — record that the patient consented to treatment. A red "
            "border appears around this section on an Active case until consent is recorded. "
            "You can type notes, or capture a hand-drawn signature directly on screen.",
            "<b>2. Visit Notes</b> — a running, permanent log of what happened at each visit. "
            "Notes can only be added, never edited or deleted — if something needs correcting, "
            "add a new note explaining the correction. This protects the clinical record.",
            "<b>3. Prescriptions</b> — same append-only rule as visit notes. An allergy banner "
            "appears automatically if the patient has any recorded allergy.",
            "<b>4. Clinical Attachments</b> — X-rays, photos, and lab reports. Only a Doctor or "
            "Administrator can delete a file (with a reason), and a bulk \"clear all\" option "
            "for a case that no longer needs its files requires a reason too. Receptionists "
            "cannot delete clinical files, by design.",
            "<b>5. Lab Requisitions</b> — track work sent to an external lab (Sent / Received / "
            "Delayed). If the patient has an appointment coming up in the next 3 days and a "
            "requisition is still open, it's flagged here so nothing gets missed.",
            "<b>6. Referral Notes</b> — collapsed by default; click to expand. A printable "
            "referral letter is available from here.",
            "<b>7. Payment Log</b> — every payment received against this case (financial data — "
            "see §1 for who can see this).",
            "<b>8. Follow-up &amp; Next Action</b> — a reminder note and date for the practice, "
            "shown on the Dashboard and the patient list. This is <i>not</i> the same as an "
            "appointment (see §6) — booking an appointment from here automatically clears the "
            "reminder.",
            "<b>9. Cost History &amp; Revisions</b> — every time the case's total cost is "
            "changed, the old and new amounts are recorded here automatically, with a reason.",
        ]),
        [Paragraph(
            "A case's balance (total cost minus payments received) is always calculated live — "
            "it is never something you edit directly.", BODY)],
        [Paragraph(
            "Close a case only when treatment is genuinely finished, using the "
            "<b>Mark as Closed</b> action — this timestamps the closure for reporting and cannot "
            "be triggered automatically.", TIP)],
    ])
    story.append(PageBreak())

    # ── 5. Dental Chart ──
    story += section("5", "Dental Chart", (
        "A visual, whole-mouth chart reachable from a patient's page via <b>Dental Chart</b>. "
        "It uses standard international (FDI) tooth numbering and shows both adult and baby "
        "teeth, since many patients have a mix of both."
    ), [
        bullets([
            "Click any tooth in the diagram to add a new finding for it — Sound, Caries, "
            "Restoration, Crown, Root Canal, Implant, Missing/Extracted, Fracture, or Other — "
            "and mark it as Existing, Planned, or Completed treatment.",
            "The chart always shows the <i>current</i> state per tooth. Every entry you add is "
            "kept permanently in the tooth's history underneath — nothing is ever overwritten "
            "or deleted. A correction is simply a new entry.",
            "Marking a tooth Missing/Extracted replaces its display with that single fact, since "
            "a missing tooth has no surface left to chart findings on.",
        ]),
    ])
    story.append(PageBreak())

    # ── 6. Appointments ──
    story += section("6", "Appointments & the Calendar", "", [
        bullets([
            "The Calendar (top navigation) shows a month view colour-coded by doctor.",
            "Click any day, or <b>New Appointment</b>, to book — choose patient, doctor, date, "
            "time, and an optional title/notes.",
            "<b>Recurring appointments</b>: choose a recurrence pattern (Weekly / Biweekly / "
            "Monthly) and Feast9 creates every occurrence up front (up to 52), marked with a "
            "small recurring-series badge on the calendar. When editing one, you choose "
            "<b>this occurrence only</b> "
            "or <b>the whole series</b> — a series-wide edit never touches an occurrence that's "
            "already Completed, Cancelled, or a No-show, so its history is never rewritten.",
            "Marking a visit <b>No-show</b> automatically creates a follow-up reminder for the "
            "next day on that patient's active case, so it doesn't get forgotten.",
            "The appointment edit page has ready-made reminder text you can click to copy "
            "straight into WhatsApp or an SMS.",
        ]),
        [Paragraph(
            "Booking an appointment from a case's Follow-up section (the "
            "\"Book Appointment\" link) automatically clears that follow-up reminder — you "
            "never have to clear it by hand.", TIP)],
    ])
    story.append(PageBreak())

    # ── 7. Dashboard ──
    story += section("7", "The Dashboard", (
        "Your homepage after login. Four tiles summarise the practice at a glance:"
    ), [
        bullets([
            '<b>Follow-ups Needing Attention</b> — <font color="#b91c1c">overdue</font> shown '
            'before <font color="#92400e">upcoming</font>; a green celebration message when '
            "there's nothing to chase.",
            "<b>Total Outstanding Balance</b> — hidden from Receptionists (shows \"Restricted\" "
            "instead), since it's financial data.",
            "<b>Active Cases</b> and <b>Today's Appointments</b> — with status colour coding "
            "matching the calendar.",
        ]),
        [Paragraph(
            "A fifth section lists any open lab requisitions for patients with a visit coming "
            "up in the next 3 days, so a delayed lab job doesn't surprise anyone at chairside.",
            BODY)],
    ])
    story.append(PageBreak())

    # ── 8. Reports & Analytics ──
    story += section("8", "Reports & Analytics", "", [
        role_pill("Doctor, Administrator only — Receptionists cannot open these pages."),
        [Paragraph("Reports", H2)],
        bullets([
            "Set a date range and see revenue collected, cases closed, new cases, and new "
            "patients for that period, alongside pending balances by patient, doctor-wise "
            "revenue, and a patient-retention check.",
            "Download the pending-payments list as an Excel file, or print the whole report "
            "as a PDF.",
        ]),
        [Paragraph("Analytics", H2)],
        [Paragraph(
            "A separate tab with a year selector and 8 charts — monthly revenue, new patients, "
            "case and appointment status breakdowns, doctor-wise revenue share, and the "
            "clinic's most-performed procedures.", BODY)],
    ])
    story.append(PageBreak())

    # ── 9. Financial Assessment ──
    story += section("9", "Financial Assessment", "", [
        role_pill("Doctor, Administrator only."),
        bullets([
            "A per-case profitability table: enter each case's Lab Amount, Consultant Fee, "
            "Consumables, and Misc Expense, and Feast9 works out the Profit "
            "(Billed - all four expenses) next to the balance still pending.",
            "A loss on any case is highlighted in amber so it can't be missed.",
            "<b>Monthly Evaluation</b> rolls this up for a whole calendar month and adds clinic "
            "overhead (rent, salaries, electricity, EMI, cleaning, other) that isn't tied to a "
            "single case. A <b>Short Term / Long Term</b> switch additionally subtracts monthly "
            "depreciation on clinic equipment in Long Term view.",
            "<b>Capital Investments</b> is a simple asset register (equipment name, purchase "
            "date, cost, useful life) that feeds that depreciation figure. Assets are never "
            "edited once entered — a correction means deactivating the wrong entry and adding "
            "a fresh one, so past months' figures are never silently rewritten.",
        ]),
    ])
    story.append(PageBreak())

    # ── 10. DPDP ──
    story += section("10", "DPDP Data-Rights Requests", "", [
        bullets([
            "Any staff member can log a request from a patient's page — the four types are "
            "<b>Access</b>, <b>Correction</b>, <b>Erasure</b>, and <b>Withdraw Consent</b>. "
            "Every request gets a 90-day resolution deadline automatically.",
            "A pending-requests count appears as a badge next to <b>DPDP Requests</b> in the "
            "navigation bar for every signed-in user.",
        ]),
        role_pill("Resolving a request — Doctor, Administrator only."),
        bullets([
            "<b>Access</b> — hand the patient a full export of their own data "
            "(a ready-made PDF is generated for this).",
            "<b>Correction</b> — make the actual correction through the normal patient-edit "
            "form, then mark the request Completed.",
            "<b>Erasure</b> — you must type the patient's name exactly as it's currently "
            "recorded to confirm. This anonymises their personal details permanently but "
            "keeps their clinical and financial history intact, exactly as the law requires.",
            "<b>Withdraw Consent</b> — turns off communications consent for that patient.",
        ]),
    ])
    story.append(PageBreak())

    # ── 11. Settings ──
    story += section("11", "Settings & Administration", "", [
        role_pill("Administrator only, unless noted."),
        bullets([
            "<b>Users</b> — create staff accounts, assign a role, deactivate/reactivate an "
            "account (the very last active Administrator can never be deactivated), and force-"
            "reset a user's 2FA if they've lost their device.",
            "<b>Doctors</b> and <b>Case Types</b> — add the doctors and treatment types your "
            "clinic offers. Deactivating one just stops it being offered on new cases — it "
            "never deletes or breaks existing records that reference it.",
            "<b>Clinic Details</b> — name, address, phone, email — these appear on every "
            "generated PDF and in the navigation bar.",
            "<b>Clinic Logo &amp; Login Screen</b> — upload a logo/login image and customise "
            "the heading and tagline shown on the sign-in page.",
            "<b>Import Data</b> — bulk-load historic patients from an Excel spreadsheet using "
            "the provided template. Every row still has to pass the same DPDP-notice and "
            "validation checks as manual registration, or it's skipped and reported — nothing "
            "invalid is ever partially imported. This always creates new patients; it never "
            "matches or updates existing ones.",
            "<b>Backups</b> — a nightly encrypted backup runs automatically; from here an "
            "Administrator can also trigger one on demand or download a past one. A warning "
            "banner appears on the Dashboard if a backup ever fails or goes stale.",
            "<b>Audit Log</b> — a complete, tamper-evident record of every sensitive action "
            "taken in the system, with who did it and when.",
            "<b>My Account</b> (every role) — change your own password, security question, "
            "2FA, and Google account link.",
        ]),
    ])
    story.append(PageBreak())

    # ── 12. Security ──
    story += section("12", "Security Do's and Don'ts", "", [
        [Paragraph("Do", H2)],
        bullets([
            "Turn on Two-Factor Authentication.",
            "Log out (or lock the workstation) whenever you step away from a shared front-desk "
            "computer.",
            "Store your 2FA recovery codes somewhere safe and private, separate from the device "
            "itself.",
            "Report a lost or stolen device to an Administrator immediately, so your account "
            "can be secured.",
        ], style=ParagraphStyle("DoBullet", parent=BULLET, textColor=SUCCESS)),
        [Paragraph("Don't", H2)],
        bullets([
            "Share your username, password, or 2FA codes with anyone — including colleagues.",
            "Leave a patient record or the Reports/Financial pages open and unattended on a "
            "shared screen.",
            "Photograph or forward a 2FA QR code — it is the same as sharing your password.",
            "Try to work around a \"403 / Access Denied\" screen — it means your role "
            "genuinely doesn't include that action; ask an Administrator if you believe it's wrong.",
        ], style=ParagraphStyle("DontBullet", parent=BULLET, textColor=DANGER)),
    ])
    story.append(PageBreak())

    # ── 13. FAQ ──
    story += section("13", "Troubleshooting & FAQ", "", [
        [Paragraph("I can't see Reports/Analytics/Financial Assessment/Backups.", H3)],
        [Paragraph(
            "These are only available to Doctor and Administrator accounts. This is "
            "enforced deliberately and is not something a Receptionist account can be given "
            "access to individually — a role change would need to come from an Administrator.",
            BODY)],
        [Paragraph("A patient's follow-up reminder won't go away.", H3)],
        [Paragraph(
            "Either clear it directly from the case's Follow-up section, or book an "
            "appointment using the \"Book Appointment\" link on that section — booking "
            "clears the reminder automatically.", BODY)],
        [Paragraph("I'm stuck on a \"Please confirm your password\" screen.", H3)],
        [Paragraph(
            "That's the step-up re-authentication check for a sensitive action (see §2). "
            "Simply enter your password (and 2FA code, if enabled) again to continue.", BODY)],
        [Paragraph("I lost my phone and can't get my 2FA codes.", H3)],
        [Paragraph(
            "Use a recovery code if you saved one. Otherwise, ask an Administrator to reset "
            "your 2FA from the Users page — you'll set it up again from scratch.", BODY)],
        [Paragraph("Can I edit a visit note, prescription, or payment I entered by mistake?", H3)],
        [Paragraph(
            "No — these are permanent, append-only clinical and financial records by design. "
            "Add a new entry noting the correction instead. This keeps the record trustworthy.",
            BODY)],
        [Paragraph("Who do I contact for help?", H3)],
        [Paragraph(
            "Your clinic's Feast9 Administrator is your first point of contact for account "
            "and access issues.", BODY)],
    ])

    doc.build(story, onFirstPage=manual_first_page, onLaterPages=manual_later_pages)


# ═════════════════════════════════════════════════════════════════════════
# QUICK REFERENCE CARD — flashy, single page, drawn largely by hand on canvas
# ═════════════════════════════════════════════════════════════════════════

def wrap_text(c, text, font, size, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if c.stringWidth(trial, font, size) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_wrapped(c, text, x, y, font, size, max_width, color, leading=None, align="left"):
    leading = leading or size * 1.25
    c.setFont(font, size)
    c.setFillColor(color)
    lines = wrap_text(c, text, font, size, max_width)
    for line in lines:
        if align == "left":
            c.drawString(x, y, line)
        elif align == "center":
            c.drawCentredString(x, y, line)
        y -= leading
    return y


def section_card(c, x, y, w, h, accent, title, badge_letter, items, item_font=7.6):
    rounded_box(c, x, y, w, h, radius=8, fill=WHITE, stroke=BORDER, stroke_width=0.75)
    # accent header strip
    rounded_box(c, x, y + h - 0.30 * inch, w, 0.30 * inch, radius=8, fill=accent)
    c.setFillColor(accent)
    c.rect(x, y + h - 0.30 * inch, w, 0.15 * inch, fill=1, stroke=0)  # square off bottom of strip
    badge_dot(c, x + 0.20 * inch, y + h - 0.15 * inch, 0.10 * inch, WHITE, badge_letter, accent)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 9.3)
    c.drawString(x + 0.38 * inch, y + h - 0.185 * inch, title)

    ty = y + h - 0.55 * inch
    for it in items:
        c.setFillColor(accent)
        c.circle(x + 0.16 * inch, ty + 0.03 * inch, 1.8, fill=1, stroke=0)
        ty = draw_wrapped(c, it, x + 0.24 * inch, ty, "Helvetica", item_font,
                           w - 0.40 * inch, INK, leading=item_font + 4.2)
        ty -= 5.5
    return ty


def build_qrc(path):
    W, H = letter
    c = pdfcanvas.Canvas(path, pagesize=letter)
    c.setTitle("Feast9 Quick Reference Card")

    # full-bleed gradient background
    gradient_rect(c, 0, 0, W, H, HexColor("#0f2a52"), PURPLE, horizontal=False)

    # header banner
    header_h = 1.05 * inch
    c.setFillColorRGB(1, 1, 1)
    c.setFillAlpha(0.08)
    c.circle(W - 0.6 * inch, H - 0.35 * inch, 90, fill=1, stroke=0)
    c.circle(0.5 * inch, H - 0.75 * inch, 60, fill=1, stroke=0)
    c.setFillAlpha(1)

    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 30)
    c.drawString(0.55 * inch, H - 0.62 * inch, "FEAST9")
    c.setFont("Helvetica-Bold", 12.5)
    c.setFillColor(HexColor("#dbe8ff"))
    c.drawString(0.58 * inch, H - 0.85 * inch, "QUICK REFERENCE CARD")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(HexColor("#c9d9f7"))
    c.drawRightString(W - 0.55 * inch, H - 0.62 * inch, "Dental Clinic Management System")
    c.drawRightString(W - 0.55 * inch, H - 0.78 * inch, TODAY)

    top = H - header_h - 0.18 * inch

    # ── Daily workflow strip ──
    wf_h = 0.62 * inch
    rounded_box(c, 0.4 * inch, top - wf_h, W - 0.8 * inch, wf_h, radius=8, fill=WHITE)
    steps = ["1  Register\nPatient", "2  Open/Create\nCase", "3  Record\nConsent",
             "4  Book\nAppointment", "5  Log Visit/\nRx/Payment", "6  Set\nFollow-up"]
    step_colors = [BRAND, TEAL, PURPLE, HexColor("#c2410c"), SUCCESS, HexColor("#b45309")]
    n = len(steps)
    cell_w = (W - 0.8 * inch) / n
    c.setFont("Helvetica-Bold", 7.6)
    for i, (s, col) in enumerate(zip(steps, step_colors)):
        cx = 0.4 * inch + i * cell_w
        if i > 0:
            c.setFillColor(BORDER)
            c.line(cx, top - wf_h + 6, cx, top - 6)
        badge_dot(c, cx + 0.24 * inch, top - wf_h / 2 + 0.03 * inch, 0.13 * inch,
                  col, str(i + 1))
        text_lines = steps[i].split("\n")
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 7.3)
        yy = top - wf_h / 2 + 0.12 * inch
        for ln in [text_lines[0].split(" ", 1)[1], text_lines[1] if len(text_lines) > 1 else ""]:
            if ln:
                c.drawString(cx + 0.44 * inch, yy, ln)
                yy -= 9.5
    top -= wf_h + 0.18 * inch

    # ── 3-column grid of section cards ──
    gap = 0.14 * inch
    col_w = (W - 0.8 * inch - 2 * gap) / 3
    row_h = 1.92 * inch
    x0 = 0.4 * inch

    section_card(c, x0, top - row_h, col_w, row_h, BRAND, "PATIENTS", "P", [
        "New Patient: DPDP notice tick is mandatory",
        "DOB auto-fills age",
        "Guardian required if under 18",
        "Search matches name/mobile/notes",
        "Red/amber dot on the list = follow-up due",
    ])
    section_card(c, x0 + col_w + gap, top - row_h, col_w, row_h, TEAL, "CASES (9 SECTIONS)", "C", [
        "Consent -> Visit Notes -> Rx -> Files",
        "-> Lab Req -> Referral -> Payments",
        "-> Follow-up -> Cost History",
        "Notes/Rx/Payments: add-only, never edited",
        "Balance = Total Cost - Payments (live)",
    ])
    section_card(c, x0 + 2 * (col_w + gap), top - row_h, col_w, row_h, PURPLE, "APPOINTMENTS", "A", [
        "Calendar colour = doctor",
        "Recurring: edit ONE or WHOLE series",
        "No-show auto-sets next-day follow-up",
        "Click reminder text to copy for SMS/WhatsApp",
        "Booking clears the case's follow-up",
    ])
    top -= row_h + gap

    section_card(c, x0, top - row_h, col_w, row_h, HexColor("#c2410c"), "DASHBOARD", "D", [
        "Red = overdue follow-up",
        "Amber = due within 3 days",
        "Balance tile hidden for Receptionists",
        "Lab reqs due before a visit flagged here",
        "Homepage after every login",
    ])
    section_card(c, x0 + col_w + gap, top - row_h, col_w, row_h, SUCCESS, "FINANCE (DR/ADMIN)", "$", [
        "Reports, Analytics, Financial Assessment",
        "Profit = Billed - Lab - Consultant -",
        "Consumables - Misc Expense",
        "Monthly Eval: Short vs Long Term (deprec.)",
        "Capital Investments: deactivate, don't edit",
    ])
    section_card(c, x0 + 2 * (col_w + gap), top - row_h, col_w, row_h, HexColor("#b45309"), "DPDP REQUESTS", "!", [
        "Anyone logs a request; 90-day deadline auto-set",
        "Only Doctor/Admin resolve",
        "Erasure needs exact name typed to confirm",
        "Access -> hand patient the PDF export",
        "Pending count badge in top nav",
    ])
    top -= row_h + 0.18 * inch

    # ── Role matrix ──
    matrix_h = 1.15 * inch
    rounded_box(c, 0.4 * inch, top - matrix_h, W - 0.8 * inch, matrix_h, radius=8, fill=WHITE)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(0.55 * inch, top - 0.26 * inch, "WHO CAN DO WHAT")
    rows = [
        ("Receptionist", "Patients / Appointments / Cases (non-financial)", DANGER, "NO financial access"),
        ("Doctor", "Everything Receptionist can + Payments / Reports / Financial / Dental Chart", SUCCESS, "Full clinical + financial"),
        ("Administrator", "Everything Doctor can + Users / Settings / Backups / Audit Log", BRAND, "Full system control"),
    ]
    ry = top - 0.53 * inch
    for name, desc, col, tag in rows:
        badge_dot(c, 0.65 * inch, ry, 0.09 * inch, col)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 8.6)
        c.drawString(0.84 * inch, ry - 0.035 * inch, name)
        c.setFont("Helvetica", 8.1)
        c.setFillColor(MUTED)
        c.drawString(1.85 * inch, ry - 0.035 * inch, desc)
        c.setFillColor(col)
        c.setFont("Helvetica-Bold", 8.1)
        c.drawRightString(W - 0.55 * inch, ry - 0.035 * inch, tag)
        ry -= 0.28 * inch
    top -= matrix_h + 0.16 * inch

    # ── footer: legend + nav + security, fills whatever space remains ──
    footer_h = min(top - 0.32 * inch, 3.1 * inch)
    fy0 = 0.32 * inch
    rounded_box(c, 0.4 * inch, fy0, W - 0.8 * inch, footer_h, radius=8,
                fill=HexColor("#111827"))
    # faint watermark badge for extra flash
    c.saveState()
    c.setFillColorRGB(1, 1, 1)
    c.setFillAlpha(0.05)
    c.circle(W - 1.1 * inch, fy0 + footer_h * 0.5, footer_h * 0.62, fill=1, stroke=0)
    c.restoreState()

    col_x = [0.6 * inch, W * 0.40, W * 0.70]
    col_end = [W * 0.40, W * 0.70, W - 0.55 * inch]
    fy_top = fy0 + footer_h - 0.34 * inch

    # Column 1 — status legend (3 rows) + the one rule that's easy to get wrong
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(col_x[0], fy_top, "STATUS LEGEND")
    legend_rows = [
        [("Overdue", DANGER), ("Due soon", HexColor("#f59e0b"))],
        [("On track", SUCCESS), ("Scheduled", HexColor("#93c5fd"))],
        [("No-show", DANGER), ("Completed", SUCCESS)],
    ]
    ly = fy_top - 0.36 * inch
    for row in legend_rows:
        lx = col_x[0]
        for label, col in row:
            badge_dot(c, lx + 0.07 * inch, ly + 0.025 * inch, 0.075 * inch, col)
            c.setFillColor(WHITE)
            c.setFont("Helvetica", 8.6)
            c.drawString(lx + 0.20 * inch, ly - 0.02 * inch, label)
            lx += 0.20 * inch + c.stringWidth(label, "Helvetica", 8.6) + 0.30 * inch
        ly -= 0.32 * inch
    ly -= 0.14 * inch
    c.setFillColor(HexColor("#9ca3af"))
    ly = draw_wrapped(c, "Follow-up is NOT an Appointment: a follow-up is a dashboard "
                          "reminder on a case; an appointment is a confirmed calendar "
                          "booking. Booking one from a follow-up clears it.",
                       col_x[0], ly, "Helvetica-Oblique", 7.6, col_end[0] - col_x[0] - 0.1 * inch,
                       HexColor("#9ca3af"), leading=10.5)

    # Column 2 — quick nav map
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(col_x[1], fy_top, "TOP NAVIGATION")
    nav_items = ["Dashboard", "Patients", "Appointments", "Reports*", "Analytics*",
                 "Financial Assessment*", "DPDP Requests", "2FA / My Account",
                 "Users / Settings†"]
    ny = fy_top - 0.34 * inch
    for item in nav_items:
        c.setFillColor(HexColor("#93c5fd"))
        c.setFont("Helvetica", 8.2)
        c.drawString(col_x[1], ny, "•  " + item)
        ny -= 0.205 * inch
    ny -= 0.06 * inch
    c.setFillColor(HexColor("#9ca3af"))
    c.setFont("Helvetica-Oblique", 7.4)
    c.drawString(col_x[1], ny, "*Doctor/Admin only    †Admin only")

    # Column 3 — security reminders
    c.setFillColor(HexColor("#fca5a5"))
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(col_x[2], fy_top, "SECURITY REMINDERS")
    tips = [
        ("Never share your password, 2FA code, or QR", False),
        ("Lock or log out on shared front-desk devices", False),
        ("Keep 2FA recovery codes private & offline", False),
        ("Report a lost device to your Administrator", False),
        ("“403 Access Denied” = your role doesn't", False),
        ("include that action — it isn't a bug", True),
        ("Verified backups run nightly — ask an", False),
        ("Admin if you see a stale-backup banner", True),
    ]
    ty = fy_top - 0.34 * inch
    for tp, is_continuation in tips:
        c.setFillColor(WHITE)
        c.setFont("Helvetica", 8.0)
        prefix = "   " if is_continuation else "-  "
        c.drawString(col_x[2], ty, prefix + tp)
        ty -= 0.205 * inch

    c.setStrokeColor(HexColor("#374151"))
    for divider_x in (col_end[0] - 0.05 * inch, col_end[1] - 0.05 * inch):
        c.line(divider_x, fy0 + 0.16 * inch, divider_x, fy_top + 0.10 * inch)

    c.setFillColor(HexColor("#6b7280"))
    c.setFont("Helvetica-Oblique", 6.8)
    c.drawCentredString(W / 2, fy0 - 0.18 * inch,
                         "Full detail in the Feast9 User Manual  ·  Ask your Administrator for help")

    c.showPage()
    c.save()


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)
    manual_path = os.path.join(out_dir, "Feast9_User_Manual.pdf")
    qrc_path = os.path.join(out_dir, "Feast9_Quick_Reference_Card.pdf")
    build_user_manual(manual_path)
    build_qrc(qrc_path)
    print(f"Wrote {manual_path}")
    print(f"Wrote {qrc_path}")


if __name__ == "__main__":
    main()
