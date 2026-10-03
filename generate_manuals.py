"""
Standalone generator for Feast9's end-user documentation:
  - Feast9_User_Manual.pdf            (multi-page reference, ReportLab Platypus)
  - Feast9_Quick_Reference_Card.pdf   (single-page, colourful cheat sheet, ReportLab canvas)
  - Feast9_User_Journeys.pdf          (one landscape journey map per role)

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


def _role_table(rows):
    head = ParagraphStyle("RH", parent=BODY, textColor=WHITE, fontName="Helvetica-Bold")
    t = Table([[Paragraph("Role", head), Paragraph("What they use Feast9 for", head)]]
              + [[Paragraph(f"<b>{r}</b>", BODY), Paragraph(d, BODY)] for r, d in rows],
              colWidths=[1.3 * inch, 5.2 * inch])
    t.setStyle(TABLE_STYLE)
    return t


def steps(items):
    """Numbered steps for a task."""
    return [Paragraph(f"<b>{n}.</b>&nbsp;&nbsp;{t}", BULLET) for n, t in enumerate(items, start=1)]


MANUAL_CONTENTS = [
    "Who can do what",
    "Signing in and keeping your account safe",
    "Finding your way around",
    "Patients",
    "Treatment cases",
    "Dental chart",
    "Appointments",
    "Lab Work",
    "Reports and Analytics",
    "Financial Assessment",
    "Privacy Requests",
    "Settings (administrators)",
    "Backup & Data (administrators)",
    "Good habits",
    "Common questions",
]


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
    story.append(Paragraph("For Receptionists · Doctors · Guest Doctors · Administrators", COVER_FOOT))
    story.append(Paragraph(f"Version dated {TODAY}", COVER_FOOT))
    story.append(PageBreak())

    # ── Contents ──
    story.append(Paragraph("Contents", H1))
    story.append(HRFlowable(width="100%", color=BRAND, thickness=2, spaceAfter=10))
    for n, entry in enumerate(MANUAL_CONTENTS, start=1):
        story.append(Paragraph(f"{n}. {entry}", TOC_ENTRY))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "<b>How to use this manual:</b> you don't need to read it all. Find the task you want to "
        "do in the contents and follow the steps. Words in <b>bold</b> are the names of buttons, "
        "menu items and boxes exactly as they appear on screen.", TIP))
    story.append(PageBreak())

    # ── 1. Who can do what ──
    story += section("1", "Who can do what", (
        "Everyone signs in with their own username. What you see depends on your role, which "
        "the administrator sets when creating your account."
    ), [[
        _role_table([
            ("Receptionist",
             "Patients' contact details, appointments, follow-up reminders on the Dashboard, the "
             "Lab Work list, and Privacy Requests. <b>No</b> medical history, treatment cases, "
             "notes, prescriptions, dental chart or clinical files, and <b>no</b> money figures "
             "(costs, payments, balances, reports)."),
            ("Doctor",
             "Everything clinical (cases, notes, prescriptions, dental chart, files), payments and "
             "costs, Reports, Analytics, Financial Assessment, and completing Privacy Requests."),
            ("Guest doctor",
             "A visiting doctor. The same clinical work as a doctor, but <b>no</b> money figures, "
             "<b>no</b> Privacy Requests, <b>no</b> Settings, and cannot delete clinical files."),
            ("Administrator",
             "Everything a doctor can do, plus Settings: staff accounts, doctors, case types, "
             "clinic details, backups and the activity log."),
        ]),
    ], [Paragraph(
        "If a button or page you expect isn't there, your role doesn't include it. That is "
        "deliberate, not a fault. Ask the administrator if you think your role is wrong.", NOTE)]])
    story.append(PageBreak())

    # ── 2. Signing in ──
    story += section("2", "Signing in and keeping your account safe", "", [
        [Paragraph("Signing in", H2)],
        steps([
            "Open Feast9 in the browser and type your <b>username</b> and <b>password</b>.",
            "If you use two-step sign-in, type the 6-digit code from the authenticator app on "
            "your phone (or one of your recovery codes).",
            "You arrive on the <b>Dashboard</b>.",
        ]),
        [Paragraph("Passwords", H2)],
        bullets([
            "A password must be at least 10 characters and not a common or easy-to-guess one. "
            "A short sentence you can remember works well, e.g. <i>blue kettle on Tuesday</i>.",
            "Change your own password from <b>My Account &gt; Change Password</b>.",
            "<b>Forgot your password?</b> If you use two-step sign-in, click <b>Forgot "
            "Password</b> on the sign-in page: answer your security question and enter a code "
            "from your phone. If you don't use two-step sign-in, ask the administrator to set a "
            "new password for you.",
        ]),
        [Paragraph("Two-step sign-in (2FA)", H2)],
        [Paragraph(
            "Two-step sign-in asks for a code from your phone as well as your password, so a "
            "stolen password alone isn't enough. Your clinic may make it compulsory.", BODY)],
        steps([
            "Install an authenticator app on your phone (Google Authenticator, Microsoft "
            "Authenticator, Authy or similar).",
            "In Feast9 go to <b>My Account &gt; Set Up 2FA</b> and scan the square code with the app.",
            "Type the 6-digit code the app shows to confirm.",
            "Write down the <b>recovery codes</b> shown next and keep them somewhere safe, away "
            "from your phone. Each works once if you lose your phone. They are shown only once.",
        ]),
        [Paragraph("Things Feast9 does to protect you", H2)],
        bullets([
            "<b>Automatic logout:</b> if Feast9 is left untouched for a while (30 minutes unless "
            "your clinic changed it) you are signed out, and everyone is signed out 12 hours "
            "after signing in. Typing counts as activity, so a long note won't be cut off.",
            "<b>Account lock:</b> after 5 wrong passwords in a row your account locks for 15 "
            "minutes, even for the right password. The administrator can unlock it sooner.",
            "<b>\"Confirm your password\":</b> before a sensitive action (adding staff, "
            "deleting a clinical file, running a backup, completing a privacy request…) Feast9 "
            "asks for your password again if you signed in more than 10 minutes ago.",
        ]),
        [Paragraph(
            "Lost your phone and your recovery codes? The administrator can reset your two-step "
            "sign-in from <b>Users</b>, and you set it up again.", LOCK)],
    ])
    story.append(PageBreak())

    # ── 3. Finding your way around ──
    story += section("3", "Finding your way around", (
        "The menu along the top of every page takes you to each part of Feast9. You only see "
        "the items your role can use."
    ), [
        bullets([
            "<b>Dashboard</b> — your starting page (see below).",
            "<b>Patients</b> — find, register and open patients.",
            "<b>Appointments</b> — the monthly calendar.",
            "<b>Lab Work</b> — every job sent to an outside lab.",
            "<b>Reports</b>, <b>Analytics</b>, <b>Financial Assessment</b> — money and practice "
            "figures (doctors and administrators).",
            "<b>Privacy Requests</b> — patients' requests about their data; the number in "
            "brackets is how many are waiting.",
            "<b>My Account</b> — your password, security question and two-step sign-in.",
            "<b>Settings</b> — clinic setup (administrators).",
            "<b>Logout</b> — always sign out when you leave a shared computer.",
        ]),
        [Paragraph("The Dashboard", H2)],
        bullets([
            "<b>Four tiles</b> at the top: follow-ups needing attention, total outstanding "
            "balance (shows <i>Restricted</i> for roles that can't see money), active cases, "
            "and today's appointments.",
            "<b>Follow-ups Needing Attention</b> — red rows are overdue, amber rows are due in "
            "the next 3 days. Click <b>Book Appointment</b> to book the visit, or <b>Done</b> "
            "once the patient has been contacted.",
            "<b>Today's Appointments</b> — the day's list, with the case each visit is for.",
            "<b>Lab Requisitions Due Before Visit</b> — lab work that hasn't come back for a "
            "patient who is booked in the next 3 days.",
        ]),
    ])
    story.append(PageBreak())

    # ── 4. Patients ──
    story += section("4", "Patients", "", [
        [Paragraph("Registering a new patient", H2)],
        steps([
            "Go to <b>Patients &gt; + New Patient</b>.",
            "Fill in the name, sex, date of birth (or age) and mobile number. For a patient "
            "under 18, a guardian's name and mobile number are required.",
            "Doctors also fill in medical history and allergies here. (Receptionists don't see "
            "these boxes; a doctor adds them later.)",
            "Give the patient the privacy notice, then tick <b>Patient (or guardian, if under "
            "18) has received and accepted the privacy notice</b>. Registration can't be saved "
            "without it.",
            "Tick the reminders box only if the patient agrees to receive appointment reminders.",
            "Click <b>Register Patient</b>. The patient's page opens.",
        ]),
        [Paragraph("Finding a patient", H2)],
        bullets([
            "The Patients page normally lists only patients with an active case (or money "
            "owing). Use the buttons above the list to switch to <b>All patients</b>, or to "
            "<b>Privacy notice pending</b> to see who still needs to be given the notice.",
            "Type a name, mobile number, email or address in the search box and click "
            "<b>Search</b>. Click <b>Clear search</b> to see the full list again.",
            "A newly registered patient with no case yet appears under <b>All patients</b>.",
        ]),
        [Paragraph("The patient's page", H2)],
        bullets([
            "<b>Medical Alerts</b> — allergies and conditions at a glance (doctors only).",
            "<b>Active Treatment Cases</b> — red or amber badges mean a follow-up is overdue or "
            "due soon. Click a case to open it (not available to receptionists).",
            "<b>Appointments</b> — past and upcoming, with <b>+ New Appointment</b>.",
            "<b>Contact Details &amp; Privacy Status</b> — contact details, whether the privacy "
            "notice was accepted, reminder consent, and any privacy requests.",
            "Buttons at the top: <b>Edit</b>, <b>Dental Chart</b> and <b>Patient Summary "
            "(PDF)</b>.",
        ]),
        [Paragraph(
            "An amber <b>Privacy notice not accepted</b> badge means the patient hasn't been "
            "given the notice yet (common for patients brought over from the old system). Give "
            "it to them at their next visit, then tick it on the <b>Edit</b> form.", NOTE)],
    ])
    story.append(PageBreak())

    # ── 5. Treatment cases ──
    story += section("5", "Treatment cases", (
        "A case is one course of treatment, for example <i>Root canal and crown, upper right</i>. "
        "A patient can have several. Everything about that treatment is recorded on the case's page."
    ), [
        role_pill("Doctors, guest doctors and administrators. Receptionists cannot open cases."),
        [Paragraph("Opening a new case", H2)],
        steps([
            "On the patient's page click <b>+ New Case</b>.",
            "Enter a short title, choose the doctor, and tick the procedures from the "
            "<b>Procedures</b> list (type in its search box to find one quickly). Use "
            "<b>Other procedure</b> for anything not listed.",
            "Enter the estimated cost (doctors and administrators) and click <b>Create Case</b>.",
        ]),
        [Paragraph("Consent (on paper)", H2)],
        steps([
            "On the case page, click <b>Print Consent Form</b>. It prints on one sheet, filled "
            "in with the patient, case, procedures and doctor.",
            "Fill in the blanks by hand (tooth, estimated cost and visits, specific risks), tick "
            "each box as you explain it, and have the patient (or guardian), the doctor and a "
            "witness sign.",
            "File the signed form (or scan it into <b>Clinical Attachments</b>), then click "
            "<b>Mark Consent Recorded</b>, adding where it is filed. The red warning border "
            "disappears.",
        ]),
        [Paragraph("Visit notes", H2)],
        bullets([
            "Write what happened at the visit and click <b>Add Visit Note</b>. <b>Attended by</b> "
            "shows which doctor saw the patient; change it if someone else did.",
            "Adding a note marks the patient's appointment for that day as Completed.",
            "Notes can't be changed or deleted afterwards. To correct one, add a new note "
            "explaining the correction.",
        ]),
        [Paragraph("Prescriptions", H2)],
        steps([
            "Choose the prescribing doctor and type the diagnosis.",
            "For each medicine enter the <b>generic name</b> (the brand is optional), strength, "
            "dosage, how often, and how it is taken. Use <b>+ Add another medicine</b> for more.",
            "Click <b>Add Prescription</b>, then <b>Print</b> to hand it to the patient.",
        ]),
        [Paragraph(
            "<b>Allergy check:</b> if a medicine may clash with an allergy recorded for the "
            "patient (for example amoxicillin for a penicillin allergy), Feast9 stops and shows "
            "a red warning. Change the medicine, or — only if you have checked and it is safe — "
            "tick <b>I have checked the patient's allergy</b> and save again. The check can miss "
            "a drug, so always read the allergy alert at the top too.", LOCK)],
        [Paragraph("The other sections of a case", H2)],
        bullets([
            "<b>Clinical Attachments</b> — upload X-rays, photos and lab reports (JPG, PNG or "
            "PDF). Only doctors and administrators can delete a file, and must give a reason.",
            "<b>Lab Requisitions</b> — record work sent to a lab and update it when it comes "
            "back.",
            "<b>Referral Notes</b> — write a referral to a specialist and print it as a letter.",
            "<b>Payment Log</b> — record each payment received; the balance updates "
            "automatically (doctors and administrators).",
            "<b>Follow-up &amp; Next Action</b> — set a reminder date and note. It appears on "
            "the Dashboard on that date. <b>Book Appointment</b> turns it into a booking; "
            "<b>Mark Follow-up Done</b> clears it once dealt with.",
            "<b>Cost History &amp; Revisions</b> — every change to the case's cost, with the "
            "reason.",
        ]),
        [Paragraph(
            "Click <b>Close Case</b> when the treatment is finished. A closed case stays on "
            "record and can still be viewed.", TIP)],
    ])
    story.append(PageBreak())

    # ── 6. Dental chart ──
    story += section("6", "Dental chart", (
        "Open it from the patient's page with <b>Dental Chart</b>. Teeth use the standard "
        "international (FDI) numbers. Use <b>Adult (Permanent)</b> or <b>Mixed / "
        "Paediatric</b> to choose which teeth are shown."
    ), [
        role_pill("Doctors, guest doctors and administrators."),
        steps([
            "Click a tooth on the chart.",
            "Choose the surface, the finding (Sound, Caries, Restoration, Crown, Root Canal, "
            "Implant, Missing/Extracted, Fracture or Other) and its status: <b>Existing</b> "
            "(already there), <b>Planned</b>, <b>Ongoing</b> or <b>Completed</b>.",
            "For planned work you can give a target date and set it as the case's follow-up.",
            "Save. The tooth's colour updates and the entry is added to its history.",
        ]),
        bullets([
            "Colours: <font color=\"#b91c1c\"><b>red</b></font> needs attention, "
            "<font color=\"#1c7ed6\"><b>blue</b></font> scheduled or in progress, "
            "<font color=\"#2f9e44\"><b>green</b></font> stable.",
            "Nothing is ever overwritten: a correction is simply a new entry, and the full "
            "history stays below the chart.",
        ]),
    ])
    story.append(PageBreak())

    # ── 7. Appointments ──
    story += section("7", "Appointments", (
        "<b>Appointments</b> shows the month. Each appointment shows a coloured dot for the "
        "doctor and a coloured badge for its status (blue Scheduled, green Completed, grey "
        "Cancelled, red No-show)."
    ), [
        [Paragraph("Booking", H2)],
        steps([
            "Click <b>+ New Appointment</b>, or the <b>+</b> on a day.",
            "Choose the patient and doctor, then the date, start and end time, and a short title.",
            "Click <b>Book Appointment</b>.",
        ]),
        bullets([
            "<b>Repeating visits</b> (e.g. braces adjustments): tick <b>Repeat this "
            "appointment</b>, choose how often and until when. Each visit gets its own entry. "
            "When editing one you choose <b>this occurrence only</b> or <b>the whole series</b>.",
            "<b>From a follow-up:</b> <b>Book Appointment</b> on the Dashboard or a case fills "
            "in the patient, doctor and title for you, and clears the follow-up once booked.",
        ]),
        [Paragraph("On the day", H2)],
        bullets([
            "A visit note added on the day marks the appointment <b>Completed</b> "
            "automatically. You can also change the status on the appointment itself.",
            "Mark a missed visit <b>No-show</b>. Feast9 adds a follow-up for the next day so "
            "someone calls the patient to rebook.",
            "If the patient agreed to reminders, the appointment page has a ready-made "
            "reminder message: click it to copy, then paste into WhatsApp or SMS.",
        ]),
    ])
    story.append(PageBreak())

    # ── 8. Lab Work ──
    story += section("8", "Lab Work", (
        "<b>Lab Work</b> lists every job sent to an outside lab, for all patients, so nothing is "
        "forgotten. It shows jobs not yet received unless you choose <b>All</b>."
    ), [
        bullets([
            "Each row shows the patient, the work, the lab, when it was sent, and the patient's "
            "next visit. A <b>Before visit</b> badge warns that the patient is coming in before "
            "the work is due back.",
            "Update the expected date, status (Sent, Received, Delayed), received date or notes "
            "on the row and click <b>Save</b>.",
            "Doctors add new lab work and delete entries from the case page. Receptionists can "
            "view and update this list.",
        ]),
    ])
    story.append(PageBreak())

    # ── 9. Reports and Analytics ──
    story += section("9", "Reports and Analytics", "", [
        role_pill("Doctors and administrators."),
        [Paragraph("Reports", H2)],
        bullets([
            "Choose a period with the quick buttons (this month, last month, this year, this "
            "financial year…) or pick your own dates.",
            "The page shows revenue collected, cases opened and closed, new patients, revenue "
            "by doctor, and patients who haven't visited in a while.",
            "The <b>Cases / Payments</b> table can be filtered and grouped (by patient, doctor, "
            "month…). <b>Download (Excel)</b> saves exactly what is shown; <b>Print Report "
            "(PDF)</b> prints the report.",
        ]),
        [Paragraph("Analytics", H2)],
        [Paragraph(
            "Charts for a chosen year: revenue, patients, cases and appointments month by month, "
            "busiest days, patient mix, and the most common procedures. Tick <b>Compare with</b> "
            "the previous year to see the change.", BODY)],
    ])
    story.append(PageBreak())

    # ── 10. Financial Assessment ──
    story += section("10", "Financial Assessment", "", [
        role_pill("Doctors and administrators."),
        bullets([
            "Lists every case with what was billed, collected and still pending. Enter each "
            "case's lab cost, consultant fee, consumables and other expenses, then <b>Save "
            "Expenses</b>. Feast9 works out the profit; a loss is shown in amber.",
            "<b>Monthly Evaluation</b> adds the clinic's running costs for a month (rent, "
            "salaries, electricity, loan EMI, cleaning, other). Use <b>Clone this month's expenses into "
            "future months</b> so you don't retype costs that don't change.",
            "<b>Capital Investments</b> records equipment purchases; the <b>Long Term</b> view "
            "spreads their cost over their useful life.",
        ]),
    ])
    story.append(PageBreak())

    # ── 11. Privacy Requests ──
    story += section("11", "Privacy Requests", (
        "Under India's Digital Personal Data Protection Act, 2023, a patient may ask to see "
        "their data, correct it, have it erased, or withdraw consent. The clinic must respond "
        "within 90 days, so every request must be recorded in Feast9 as soon as it is made."
    ), [
        [Paragraph("Recording a request", H2)],
        role_pill("Receptionists, doctors and administrators."),
        steps([
            "Open the patient's page and click <b>+ New Privacy Request</b> (in Contact Details "
            "&amp; Privacy Status).",
            "Choose the type — <b>Access</b>, <b>Correction</b>, <b>Erasure</b> or <b>Withdraw "
            "Consent</b> — write what the patient asked for, and save. The 90-day deadline is "
            "set automatically.",
        ]),
        [Paragraph("Completing a request", H2)],
        role_pill("Doctors and administrators."),
        bullets([
            "<b>Access</b> — click <b>Download Patient Data (PDF)</b> on the request, give it "
            "to them, then mark the request Completed.",
            "<b>Correction</b> — fix the details with the patient's <b>Edit</b> form, then "
            "mark it Completed.",
            "<b>Withdraw Consent</b> — marking it Completed stops reminders to the patient.",
            "<b>Erasure</b> — removes the patient's name and contact details for good (their "
            "treatment and payment records are kept, as the law allows). You must type the "
            "patient's exact name to confirm.",
        ]),
        [Paragraph(
            "An Erasure <b>cannot be completed while the patient still owes money or has an "
            "active case</b> — afterwards nobody could tell who owes it. Settle the balance and "
            "close the cases first; the request page tells you what is outstanding.", NOTE)],
    ])
    story.append(PageBreak())

    # ── 12. Settings ──
    story += section("12", "Settings (administrators)", (
        "Click <b>Settings</b> in the top menu. Each card opens one area."
    ), [
        role_pill("Administrators only."),
        bullets([
            "<b>Users</b> — add staff accounts and choose their role; deactivate someone who "
            "leaves; <b>Set Password</b> for someone who forgot theirs; reset two-step sign-in "
            "for a lost phone; unlock a locked account.",
            "<b>Doctors</b> — add doctors with their qualifications and registration number "
            "(these print on prescriptions) and a calendar colour. Feast9 suggests a colour "
            "that differs from the other doctors' and warns if two look alike. Deactivating a "
            "doctor keeps all their past records.",
            "<b>Case Types</b> — the procedures offered on new cases. Renaming one updates "
            "existing cases too.",
            "<b>Clinic Details</b> — name, address, phone and email; these appear on every "
            "printout.",
            "<b>Clinic Logo</b>, <b>Login Screen</b> and <b>Theme</b> — the logo, sign-in page "
            "wording and colours.",
            "<b>Automatic Logout</b> — how many idle minutes before Feast9 signs people out.",
            "<b>Sign-in Security</b> — make two-step sign-in compulsory for doctors and "
            "administrators, or for everyone.",
            "<b>Audit Log</b> — who opened or changed what, and every sign-in.",
        ]),
    ])
    story.append(PageBreak())

    # ── 13. Backup & Data ──
    story += section("13", "Backup & Data (administrators)", (
        "Open <b>Settings &gt; Backup &amp; Data</b>. Three tiles at the top show whether backups, "
        "the off-site copy and the Excel copy are up to date."
    ), [
        role_pill("Administrators only."),
        [Paragraph("Setting up backups (once)", H2)],
        steps([
            "Click <b>Set Up Backups</b>. Feast9 makes the first backup and shows a "
            "<b>backup key</b>.",
            "Copy the key and keep it somewhere safe <b>away from this computer</b> (for "
            "example printed and locked away). Without it a backup can't be restored.",
            "Under <b>Backup settings</b>, choose the daily time and, ideally, a <b>copy "
            "folder</b> on a USB drive or another computer, so a copy survives if this PC fails.",
        ]),
        bullets([
            "Backups then run every day by themselves. <b>Back Up Now</b> makes one "
            "immediately, for example before a big change.",
            "The <b>Excel Copy</b> is a spreadsheet of everything, readable without Feast9 — "
            "a \"Plan B\" if the computer is ever unavailable.",
            "<b>Import from Excel</b> brings in patients from the old system using the "
            "template provided.",
        ]),
    ])
    story.append(PageBreak())

    # ── 14. Good habits ──
    story += section("14", "Good habits", "", [
        [Paragraph("Do", H2)],
        bullets([
            "Use two-step sign-in, and keep your recovery codes somewhere safe.",
            "Click <b>Logout</b> whenever you leave a shared computer.",
            "Record a privacy request on the day the patient asks.",
            "Tell the administrator at once if your phone is lost or you think someone knows "
            "your password.",
        ], style=ParagraphStyle("DoBullet", parent=BULLET, textColor=SUCCESS)),
        [Paragraph("Don't", H2)],
        bullets([
            "Share your username, password or codes — not even with colleagues. Everything "
            "you do is recorded under your name.",
            "Leave a patient's record open on a screen patients can see.",
            "Write passwords on notes stuck to the screen.",
        ], style=ParagraphStyle("DontBullet", parent=BULLET, textColor=DANGER)),
    ])
    story.append(PageBreak())

    # ── 15. Common questions ──
    faq = [
        ("I was signed out while working.",
         "Feast9 signs you out after a period without activity, and always after 12 hours. "
         "Sign in again; anything already saved is safe."),
        ("It says my account is locked.",
         "Too many wrong passwords. Wait 15 minutes, or ask the administrator to unlock it."),
        ("Feast9 asks for my password again.",
         "You are doing something sensitive and signed in more than 10 minutes ago. Type your "
         "password (and code, if asked) to carry on."),
        ("I can't find a patient.",
         "Click <b>All patients</b> — the normal list only shows patients with an active case "
         "or money owing — and check the spelling or try the mobile number."),
        ("I made a mistake in a visit note, prescription or payment.",
         "These can't be edited, to keep the record trustworthy. Add a new entry that "
         "explains the correction."),
        ("A follow-up won't leave the Dashboard.",
         "Click <b>Done</b> once the patient has been contacted, or <b>Book Appointment</b>."),
        ("I can't complete an Erasure request.",
         "The patient still owes money or has an active case. The request page says which."),
        ("Who do I ask for help?",
         "Your clinic's Feast9 administrator."),
    ]
    blocks = []
    for q, a in faq:
        blocks.append([Paragraph(q, H3), Paragraph(a, BODY)])
    story += section("15", "Common questions", "", blocks)

    doc.build(story, onFirstPage=manual_first_page, onLaterPages=manual_later_pages)


# ═════════════════════════════════════════════════════════════════════════
# USER JOURNEY MAPS — one landscape page per role
# ═════════════════════════════════════════════════════════════════════════

# Each journey: (role, colour, who they are, their goal, stages). A stage is
# (name, what they do, where in Feast9, what helps, watch-outs).
JOURNEYS = [
    ("Receptionist", TEAL,
     "Runs the front desk: greets patients, registers them, keeps the diary full and chases "
     "follow-ups. Never sees medical records or money figures.",
     "Every patient is booked, reminded and followed up — and nobody slips through.",
     [
         ("Start the day",
          "Signs in; checks today's list and follow-ups due.",
          "Dashboard",
          "Overdue (red) and due-soon (amber) follow-ups listed first; today's appointments "
          "with their case.",
          "Shared PC: must log out when stepping away."),
         ("Patient arrives",
          "Finds the patient, or registers a new one; gives the privacy notice.",
          "Patients > Search / + New Patient",
          "Search by name or mobile; privacy-notice tick enforced; 'Privacy notice pending' "
          "list for older records.",
          "New patient with no case only shows under 'All patients'."),
         ("Book & remind",
          "Books the visit or a repeating series; copies the reminder text.",
          "Appointments > + New Appointment",
          "Doctor-coloured calendar; repeat bookings; ready-made WhatsApp/SMS text if the "
          "patient agreed to reminders.",
          "No reminder text for patients who didn't agree to reminders."),
         ("Follow-ups & no-shows",
          "Calls patients whose follow-up is due; books them or marks Done; records no-shows.",
          "Dashboard > Book Appointment / Done",
          "A no-show automatically creates a next-day follow-up.",
          "Doctor sets follow-up dates; front desk can't add them on a case."),
         ("Lab work",
          "Tracks jobs at the lab; updates status when work comes back.",
          "Lab Work",
          "'Before visit' badge when the patient is booked before the work is due back.",
          "Can update, but adding/deleting lab work is the doctor's job."),
         ("Privacy request",
          "Records a patient's request about their data the same day.",
          "Patient page > + New Privacy Request",
          "90-day deadline set automatically; the menu shows how many are waiting.",
          "Can't complete requests — passes them to a doctor or admin."),
     ]),
    ("Doctor", BRAND,
     "The clinic's dentist: examines, plans and treats, records everything clinically, and "
     "keeps an eye on the practice's finances.",
     "Treat safely, keep a complete record, and get paid for the work done.",
     [
         ("Prepare",
          "Signs in with two-step code; reviews today's patients and their alerts.",
          "Dashboard > Patient page",
          "Medical Alerts (allergies, conditions) first on the patient page; lab work due "
          "before visit flagged.",
          "Two-step sign-in may be compulsory for doctors."),
         ("Plan the case",
          "Opens a case: title, procedures, estimated cost.",
          "Patient > + New Case",
          "Searchable procedure list; cost history kept automatically.",
          "Cost changes are recorded with a reason, never silently overwritten."),
         ("Consent",
          "Prints the one-page consent form; patient, doctor and witness sign; marks it recorded.",
          "Case > Print Consent Form / Mark Consent Recorded",
          "Form pre-filled from the case; red border until consent is recorded.",
          "Consent is per case — a new case needs a new form."),
         ("Treat & record",
          "Charts teeth; writes the visit note; uploads X-rays.",
          "Dental Chart; Case > Visit Notes, Attachments",
          "Note marks today's appointment Completed; chart keeps full history.",
          "Notes can't be edited — corrections are new notes."),
         ("Prescribe",
          "Writes a structured prescription by generic name and prints it.",
          "Case > Prescriptions",
          "Allergy check stops a clashing medicine until confirmed; printout carries "
          "registration details.",
          "The allergy check can miss a drug — still read the alert."),
         ("Bill & follow up",
          "Records payment; sets the next follow-up or books it; closes finished cases.",
          "Case > Payment Log, Follow-up; Close Case",
          "Balance updates live; follow-up appears on the Dashboard on its date.",
          "An erasure request can't complete while money is owed."),
         ("Review the practice",
          "Checks revenue, pending payments and profitability.",
          "Reports, Analytics, Financial Assessment",
          "Quick period buttons, Excel export, year-on-year comparison.",
          "Enter case expenses for profit figures to mean anything."),
     ]),
    ("Guest doctor", PURPLE,
     "A visiting specialist who treats some of the clinic's patients on set days. Full clinical "
     "access, but no money figures, no Settings and no privacy requests.",
     "Pick up the patient's history quickly, treat, and hand over cleanly.",
     [
         ("Sign in",
          "Signs in with own account and two-step code.",
          "Sign-in page",
          "Own account means every note is recorded under their name.",
          "Never borrow a resident doctor's login."),
         ("Today's patients",
          "Sees the day's appointments and opens each patient.",
          "Dashboard; Appointments",
          "Appointments show which case each visit is for.",
          "Balance tile shows 'Restricted' — by design."),
         ("Catch up",
          "Reads alerts, previous notes, chart and X-rays.",
          "Patient page; Case; Dental Chart",
          "Complete clinical history in one place.",
          "Payments and costs are hidden."),
         ("Treat & record",
          "Adds visit notes ('Attended by' themselves), charts teeth, prescribes, uploads images.",
          "Case sections; Dental Chart",
          "Same tools as the resident doctor, including the allergy check.",
          "Cannot delete clinical files."),
         ("Hand over",
          "Sets a follow-up, records lab work, writes a referral if needed.",
          "Case > Follow-up, Lab Requisitions, Referral Notes",
          "Front desk sees the follow-up on the Dashboard and the lab job on Lab Work.",
          "A new case they open is created without a cost — the clinic adds it."),
         ("Leave",
          "Signs out.",
          "Logout",
          "Automatic logout after inactivity as a safety net.",
          "Clinic deactivates the account when the visiting arrangement ends."),
     ]),
    ("Administrator", DANGER,
     "Usually the senior doctor or practice manager: sets Feast9 up, manages staff access, "
     "watches backups and compliance, and oversees the money.",
     "A secure, well-run system the clinic can rely on — and evidence that it is.",
     [
         ("Set up",
          "Completes Setup; enters clinic details, doctors, case types; sets sign-in rules.",
          "Settings",
          "Doctor colours suggested so the calendar stays readable.",
          "Doctors' registration details are needed for valid prescriptions."),
         ("Staff & access",
          "Adds each person with the right role; handles leavers, lockouts, lost phones.",
          "Settings > Users",
          "Set Password, Unlock, Reset 2FA, Deactivate (ends sessions at once).",
          "One account per person — never shared."),
         ("Protect the data",
          "Sets up backups once; stores the backup key off the PC; sets a copy folder.",
          "Settings > Backup & Data",
          "Daily automatic backups; tiles turn red if one fails or is stale.",
          "Without the key, backups can't be restored."),
         ("Daily check",
          "Glances at the Dashboard and backup tiles.",
          "Dashboard; Backup & Data",
          "Warning banner on the Dashboard if backups need attention.",
          "Ask the support firm to test a restore each quarter."),
         ("Money",
          "Reviews reports, enters case expenses and monthly overheads.",
          "Reports; Financial Assessment; Monthly Evaluation",
          "Clone overheads into future months; Excel exports.",
          "Exports contain patient names — store them safely."),
         ("Privacy & audit",
          "Completes privacy requests; checks who opened or changed records.",
          "Privacy Requests; Settings > Audit Log",
          "Erasure blocked while money is owed or a case is active; access PDF ready-made.",
          "90-day deadline for every request."),
     ]),
]


def build_journey_maps(path):
    page = landscape(letter)
    doc = SimpleDocTemplate(
        path, pagesize=page,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        title="Feast9 User Journeys",
    )
    width = page[0] - inch
    cell = ParagraphStyle("JCell", parent=BODY, fontSize=9.4, leading=12, spaceAfter=0)
    stage_head = ParagraphStyle("JStage", parent=cell, fontName="Helvetica-Bold", textColor=WHITE,
                                fontSize=10, leading=12.5)
    row_head = ParagraphStyle("JRow", parent=cell, fontName="Helvetica-Bold", textColor=BRAND_DARK)
    intro = ParagraphStyle("JIntro", parent=BODY, fontSize=9.5, leading=12.5)

    story = [
        Paragraph("Feast9 — User Journey Maps", ParagraphStyle(
            "JTitle", parent=H1, fontSize=22, leading=26)),
        Paragraph(f"Version dated {TODAY}", ParagraphStyle("JDate", parent=BODY, textColor=MUTED)),
        Spacer(1, 10),
        Paragraph(
            "One page per role. Each page follows a typical working day from left to right. "
            "For every stage it shows what the person does, where in Feast9 they do it, what "
            "Feast9 does to help, and what to watch out for. Use it for training, for "
            "explaining Feast9 to new staff, and for spotting where the workflow can improve.",
            intro),
        Spacer(1, 10),
    ]
    legend = [
        ("Doing", "what the person does at this stage"),
        ("In Feast9", "the page or button they use"),
        ("Helps", "what Feast9 does for them"),
        ("Watch out", "limits, risks and common mistakes"),
    ]
    t = Table([[Paragraph(f"<b>{a}</b>", BODY), Paragraph(b, BODY)] for a, b in legend],
              colWidths=[1.3 * inch, 5 * inch], hAlign="LEFT")
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                           ("BACKGROUND", (0, 0), (0, -1), BRAND_LIGHT),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [t, Spacer(1, 12)]
    roles = Table([[Paragraph(f'<font color="{c.hexval().replace("0x", "#")}"><b>{r}</b></font>', BODY),
                    Paragraph(who, BODY)] for r, c, who, _goal, _stages in JOURNEYS],
                  colWidths=[1.3 * inch, 8.7 * inch])
    roles.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDER),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [roles, PageBreak()]

    for role, colour, who, goal, stages in JOURNEYS:
        story.append(Paragraph(role, ParagraphStyle("JRole", parent=H1, textColor=colour, fontSize=20,
                                                    leading=24, spaceAfter=2)))
        story.append(Paragraph(f"<b>Who:</b> {who}", intro))
        story.append(Paragraph(f"<b>Goal:</b> {goal}", intro))
        story.append(Spacer(1, 8))

        label_w = 0.85 * inch
        col_w = (width - label_w) / len(stages)
        header = [Paragraph("", cell)] + [
            Paragraph(f"{n}. {s[0]}", stage_head) for n, s in enumerate(stages, start=1)]
        rows = [header]
        for i, label in enumerate(("Doing", "In Feast9", "Helps", "Watch out"), start=1):
            rows.append([Paragraph(label, row_head)] + [Paragraph(s[i], cell) for s in stages])
        t = Table(rows, colWidths=[label_w] + [col_w] * len(stages))
        t.setStyle(TableStyle([
            ("BACKGROUND", (1, 0), (-1, 0), colour),
            ("BACKGROUND", (0, 1), (0, -1), BRAND_LIGHT),
            ("BACKGROUND", (1, 3), (-1, 3), SUCCESS_BG),
            ("BACKGROUND", (1, 4), (-1, 4), WARNING_BG),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("LINEAFTER", (1, 0), (-2, 0), 1.5, WHITE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
        story.append(t)
        story.append(PageBreak())
    story.pop()  # no blank page at the end

    def footer(c, d):
        c.saveState()
        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawString(0.5 * inch, 0.3 * inch, "FEAST9 — USER JOURNEY MAPS")
        c.drawRightString(page[0] - 0.5 * inch, 0.3 * inch, f"Page {d.page}")
        c.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


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
        "New Patient: privacy notice tick is mandatory",
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
    section_card(c, x0 + 2 * (col_w + gap), top - row_h, col_w, row_h, HexColor("#b45309"), "PRIVACY REQUESTS", "!", [
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
                 "Financial Assessment*", "Privacy Requests", "2FA / My Account",
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
    journeys_path = os.path.join(out_dir, "Feast9_User_Journeys.pdf")
    build_user_manual(manual_path)
    build_qrc(qrc_path)
    build_journey_maps(journeys_path)
    print(f"Wrote {manual_path}")
    print(f"Wrote {qrc_path}")
    print(f"Wrote {journeys_path}")


if __name__ == "__main__":
    main()
