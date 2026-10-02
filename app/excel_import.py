"""Bulk import from an .xlsx workbook (feast9_v2_agents.md §2/§3 excel_import.py: "Bulk
8,000-row xlsx import"), laid out like the earlier Feast9 version's Excel export so its
data can be copied straight in: a "Patients & Cases" sheet whose first 22 columns are that
export's columns in the same order (one row per case, patient details repeated), followed by
the fields this version needs that the old one didn't record. The same layout doubles as a
Plan-B sheet while the system is down — app/excel_export.py writes it — and is imported
back once the system returns.

Every row is validated against the same rules the manual forms enforce — patient: name,
sex, mobile format, guardian-for-minors; case: title and a known doctor. The DPDP notice is
the one difference from the manual form: it is recorded exactly as the sheet says (user
decision, 2026-10-02). Yes imports the patient as having accepted; No or blank — the old
export never recorded it — imports the patient as NOT accepted, which Feast9 then shows on
the patient until acceptance is recorded. Import never turns a No into a Yes, and a patient
who has not accepted the notice is never given communications consent. Invalid rows are skipped and reported, never
partially written; all valid rows commit together (db.import_workbook).

Rows for the same patient are grouped — by Patient Ref label, else by name + mobile — and
become one patient. Patient Ref / Case Ref hold Feast9 ids in an export: such rows are
recognised and left unchanged (never updated) — except that a Paid figure higher than
Feast9's total records the difference as a new payment, which is how a payment taken
during an outage gets in. Any other ref is a label for a new record; labels must not be
plain numbers, so a typed "1" can never be read as someone else's record. A new patient
whose name and mobile match an existing one is refused rather than duplicated.
This module never touches the database directly except through db.py.
"""
import datetime
import io
import json
import re

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from app import db
from app.constants import MAX_IMPORT_ROWS, SEX_OPTIONS
from app.validators import compute_age, is_valid_mobile, normalize_date, now_iso, today_iso
from app.xlsx_safe import append_row

CASES_SHEET = "Patients & Cases"
NO_CASES_SHEET = "Patients (No Cases)"
CASE_STATUSES = ["Active", "Closed"]

# The earlier version's export, column for column — keep these first and in this order so a
# block copied from an old export pastes straight in.
OLD_PATIENT_HEADERS = [
    "Patient Name", "Age", "Sex", "Mobile", "Email", "Address", "Last Visited",
    "Emergency Contact", "EC Number", "Medical Conditions", "Allergies",
]
OLD_CASE_HEADERS = [
    "Case Title", "Status", "Doctor", "Procedures", "Total Cost (Rs.)", "Paid (Rs.)",
    "Balance (Rs.)", "Follow-up Date", "Next Action", "Case Opened", "Case Closed",
]
# Fields this version records that the old export didn't. DPDP first: it's the one worth
# filling for every patient, so it sits right next to the pasted block.
EXTRA_PATIENT_HEADERS = [
    "DPDP Notice Accepted", "DPDP Notice Accepted Date", "Date of Birth", "Communications Consent",
    "Is Pregnant", "Is Nursing", "Emergency Contact Relation",
    "Guardian Name", "Guardian Relation", "Guardian Mobile",
]
EXTRA_CASE_HEADERS = ["Other Procedure", "Payment Date", "Payment Method"]
REF_HEADERS = ["Patient Ref", "Case Ref"]

CASES_SHEET_HEADERS = (OLD_PATIENT_HEADERS + OLD_CASE_HEADERS
                       + EXTRA_PATIENT_HEADERS + EXTRA_CASE_HEADERS + REF_HEADERS)
NO_CASES_SHEET_HEADERS = OLD_PATIENT_HEADERS + EXTRA_PATIENT_HEADERS + ["Patient Ref"]

# The original one-sheet patient template's column names, still accepted.
TEMPLATE_HEADERS = [
    "Name", "Date of Birth", "Age", "Sex", "Mobile", "Email", "Address",
    "Medical Conditions", "Allergies", "Is Pregnant", "Is Nursing",
    "Emergency Contact Name", "Emergency Contact Relation", "Emergency Contact Number",
    "DPDP Notice Accepted", "DPDP Notice Accepted Date", "Communications Consent",
    "Guardian Name", "Guardian Relation", "Guardian Mobile",
]
_HEADER_ALIASES = {
    "name": "Patient Name",
    "emergency contact name": "Emergency Contact",
    "emergency contact number": "EC Number",
}

REQUIRED_HEADERS = ("Patient Name", "Sex")
CONDITIONAL_HEADERS = ("Doctor", "Guardian Name", "Guardian Mobile")
IGNORED_HEADERS = ("Balance (Rs.)",)

_HEADER_NOTES = {
    "Patient Name": "Required.",
    "Age": "Whole years — used when Date of Birth is blank.",
    "Sex": "Required: Male or Female.",
    "Mobile": "10-digit Indian mobile number (optionally prefixed 91).",
    "Last Visited": "YYYY-MM-DD.",
    "Case Title": "Leave blank for a patient with no case. Rows repeating the same patient add more cases.",
    "Status": "Active (default) or Closed.",
    "Doctor": "Required when the row has a case — a doctor from Settings > Doctors (pick from the list).",
    "Procedures": "Case types separated by commas; (Custom: ...) and names not in Settings > Case Types "
                  "are kept as Other Procedure.",
    "Total Cost (Rs.)": "Number, 0 or more. Blank = 0.",
    "Paid (Rs.)": "Total paid on this case so far — recorded as a payment. On a row exported from Feast9, "
                  "raise it to record a new payment.",
    "Balance (Rs.)": "Ignored on import — Feast9 works it out from Total Cost and payments.",
    "Follow-up Date": "YYYY-MM-DD — shows as a reminder on the dashboard.",
    "Case Opened": "YYYY-MM-DD. Defaults to the import date.",
    "Case Closed": "YYYY-MM-DD, for a Closed case. Defaults to the import date.",
    "DPDP Notice Accepted": "Yes / No — recorded as entered. Yes only once the patient has accepted the "
                            "data notice. No or blank: the patient is imported and shown as not yet accepted.",
    "DPDP Notice Accepted Date": "YYYY-MM-DD, when Yes. Defaults to the import date.",
    "Date of Birth": "YYYY-MM-DD. If given, age is worked out from it.",
    "Communications Consent": "Yes / No — consent to reminders by SMS/WhatsApp.",
    "Guardian Name": "Required when the patient is under 18.",
    "Guardian Mobile": "Required (valid mobile) when the patient is under 18.",
    "Other Procedure": "Free text, added to the case's procedures.",
    "Payment Date": "Date for the Paid amount. Defaults to Case Closed, then Case Opened.",
    "Patient Ref": "Leave blank for new patients. Filled in by a Feast9 export — don't change it.",
    "Case Ref": "Leave blank for new cases. Filled in by a Feast9 export — don't change it.",
}

_REQUIRED_FILL = PatternFill("solid", fgColor="F8D7DA")
_CONDITIONAL_FILL = PatternFill("solid", fgColor="FFF3CD")
_OPTIONAL_FILL = PatternFill("solid", fgColor="E2EFDA")
READ_ONLY_FILL = PatternFill("solid", fgColor="D9D9D9")
_HEADER_FONT = Font(bold=True)


# ── Template ──────────────────────────────────────────────────────────────

def style_header_row(ws, headers, capture=True, width=16):
    """Colour-codes a header row — red = required on every row, amber = required on some
    rows, grey = ignored on import, green = optional — puts each column's rule in a cell
    note, and freezes it. capture=False marks a read-only reference sheet: all grey."""
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col)
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[cell.column_letter].width = max(width, len(header) + 4)
        if not capture or header in IGNORED_HEADERS:
            cell.fill = READ_ONLY_FILL
        elif header in REQUIRED_HEADERS:
            cell.fill = _REQUIRED_FILL
        elif header in CONDITIONAL_HEADERS:
            cell.fill = _CONDITIONAL_FILL
        else:
            cell.fill = _OPTIONAL_FILL
        if capture and header in _HEADER_NOTES:
            cell.comment = Comment(_HEADER_NOTES[header], "Feast9")
    ws.freeze_panes = "B2"


def set_active_sheet(wb, title):
    """openpyxl leaves the first sheet's tab selected too, which opens in Excel as a
    grouped selection (typing then edits both sheets) — select exactly one."""
    for ws in wb.worksheets:
        ws.sheet_view.tabSelected = ws.title == title
    wb.active = wb.sheetnames.index(title)


def _add_list_validation(ws, headers, header, formula):
    if header not in headers:
        return
    letter = get_column_letter(headers.index(header) + 1)
    dv = DataValidation(type="list", formula1=formula, allow_blank=True)
    dv.error = "Pick a value from the list."
    dv.errorTitle = "Invalid value"
    ws.add_data_validation(dv)
    dv.add(f"{letter}2:{letter}{MAX_IMPORT_ROWS + 1}")


def add_dropdowns(wb, sheets):
    """Drop-down lists for the columns with a fixed set of values. Doctor names live on a
    hidden Lists sheet (a list of names can outgrow Excel's 255-character inline limit)."""
    doctor_names = [d["name"] for d in db.list_doctors()]
    lists = wb.create_sheet("Lists")
    lists.append(["Doctors"])
    for name in doctor_names:
        append_row(lists, [name])  # a doctor name is typed text — never a live formula
    lists.sheet_state = "hidden"

    for title, headers in sheets:
        ws = wb[title]
        _add_list_validation(ws, headers, "Sex", f'"{",".join(SEX_OPTIONS)}"')
        for header in ("DPDP Notice Accepted", "Communications Consent", "Is Pregnant", "Is Nursing"):
            _add_list_validation(ws, headers, header, '"Yes,No"')
        _add_list_validation(ws, headers, "Status", f'"{",".join(CASE_STATUSES)}"')
        if doctor_names:
            _add_list_validation(ws, headers, "Doctor", f"Lists!$A$2:$A${len(doctor_names) + 1}")


_OLD_COLS = f"A–{get_column_letter(len(OLD_PATIENT_HEADERS) + len(OLD_CASE_HEADERS))}"
_READ_ME = [
    ("Filling it in", None),
    ("One row per case", "Patient details on the left, the case on the right. A patient with several cases "
                         "gets one row per case, with their details repeated. A patient with no case: "
                         "leave the case columns blank."),
    ("From the old version", f"Columns {_OLD_COLS} are the earlier version's Excel export, in the same order: "
                             f"copy that block from its 'Patients & Cases' sheet and paste it into cell A2. Rows "
                             f"from its 'Patients (No Cases)' sheet paste into columns A–K below them."),
    ("Header colours", "RED = required on every row.  AMBER = required on some rows: Doctor when the row has a "
                       "case, Guardian Name and Mobile for a patient under 18.  GREEN = optional.  "
                       "GREY = ignored (worked out by Feast9). Hover over a header to see its rule."),
    ("DPDP Notice Accepted", "The old version didn't record this. Enter Yes only for patients who have accepted "
                             "the clinic's data notice. No or blank is imported too: the patient is shown in "
                             "Feast9 as not yet accepted, until that is recorded on their page."),
    ("Dates", "Type dates as YYYY-MM-DD (e.g. 2026-09-30), or as normal Excel dates."),
    ("Doctors", "Must match a doctor in Settings > Doctors — 'Dr' and capital letters don't matter."),
    ("Procedures", "Names that match Settings > Case Types are linked; anything else is kept on the case as "
                   "text. Add missing case types first if you want them linked."),
    ("Paid", "The total paid on the case so far. It's recorded as one payment."),
    ("Same patient", "Rows with the same name and mobile are one patient. A patient already in Feast9 with "
                     "that name and mobile is not added again — the row is reported instead."),
]


def write_read_me(ws, intro_rows=(), extra_rows=()):
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 110
    for label, text in list(intro_rows) + _READ_ME + list(extra_rows):
        ws.append([label, text])
        row = ws.max_row
        if text is None:
            ws.cell(row=row, column=1).font = Font(bold=True, size=12)
        else:
            ws.cell(row=row, column=1).font = _HEADER_FONT
            ws.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="top")


def build_template_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.title = CASES_SHEET
    ws.append(CASES_SHEET_HEADERS)
    style_header_row(ws, CASES_SHEET_HEADERS)
    write_read_me(wb.create_sheet("Read Me"), intro_rows=[("Feast9 data capture template", None), ("", "")])
    add_dropdowns(wb, [(CASES_SHEET, CASES_SHEET_HEADERS)])
    set_active_sheet(wb, CASES_SHEET)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Parsing helpers ───────────────────────────────────────────────────────

def _yes(value):
    return value.strip().lower() in ("yes", "y", "true", "1")


def _cell_text(value):
    """openpyxl hands back native types per cell format — a date column comes back as
    datetime.date/datetime, a numeric column (mobile numbers are all-digit) as int/float —
    normalize everything to the plain string the rest of validation expects."""
    if value is None:
        return ""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _norm_name(name):
    return " ".join(name.split()).casefold()


def _norm_mobile(mobile):
    digits = re.sub(r"\D", "", mobile)
    return digits[-10:]


def _doctor_key(name):
    """'DR JOSE JIMMY', 'Dr. Jose Jimmy' and 'jose jimmy' are the same doctor."""
    key = re.sub(r"[.\s]+", " ", name).strip().casefold()
    return re.sub(r"^dr ", "", key)


def _parse_amount(text):
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


_DATE_WITH_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]\d{1,2}:\d{2}(:\d{2})?$")


def _to_date(text):
    """YYYY-MM-DD, also accepting a date with a time after it — the earlier version wrote
    some Case Closed values as '2026-09-09 07:10:27'. '' if it isn't a date."""
    match = _DATE_WITH_TIME.match(text.strip())
    return normalize_date(match.group(1) if match else text)


def _parse_date(text, label, errors):
    if not text:
        return ""
    value = _to_date(text)
    if not value:
        errors.append(f"{label} '{text}' isn't a valid date — use YYYY-MM-DD.")
    return value


def _timestamp_for(date_text):
    """created_at / closed_at for a dated row: today keeps the real time, a past date gets
    midnight — reports DATE()-wrap these columns, so only the date part matters."""
    return now_iso() if date_text == today_iso() else f"{date_text} 00:00:00"


def _is_existing_id(ref):
    return ref.isdigit()


class ImportResult:
    def __init__(self):
        self.imported_count = 0   # patients — kept under its original name
        self.cases_imported = 0
        self.payments_imported = 0
        self.unchanged = {"Patients": 0, "Cases": 0}
        self.skipped = []  # [{"sheet": str, "row": int, "name": str, "errors": [str, ...]}, ...]
        self.header_error = ""

    @property
    def ok(self):
        return not self.header_error

    @property
    def unchanged_total(self):
        return sum(self.unchanged.values())


class _Sheet:
    """A worksheet's data rows, read by header name — column order doesn't matter, extra
    columns are ignored, and the original template's names are accepted as aliases."""

    def __init__(self, ws, title):
        self.title = title
        rows = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows)
        except StopIteration:
            header_row = ()
        self.index = {}
        for i, cell in enumerate(header_row):
            if cell is None:
                continue
            name = str(cell).strip()
            self.index.setdefault(_HEADER_ALIASES.get(name.casefold(), name), i)
        self.rows = rows

    def data_rows(self, result):
        row_number = 1
        for values in self.rows:
            row_number += 1
            if row_number - 1 > MAX_IMPORT_ROWS:
                result.skipped.append({
                    "sheet": self.title, "row": row_number, "name": "",
                    "errors": [f"Exceeds the {MAX_IMPORT_ROWS}-row limit — split the file and import the rest separately."],
                })
                return
            if values is None or all(v is None or str(v).strip() == "" for v in values):
                continue

            def get(col, _values=values):
                idx = self.index.get(col)
                if idx is None or idx >= len(_values):
                    return ""
                return _cell_text(_values[idx])

            yield _Row(self.title, row_number, get)


class _Row:
    def __init__(self, sheet, number, get):
        self.sheet, self.number, self.get = sheet, number, get
        self.errors = []
        self.patient = None  # ("id", patient_id) | ("new", index into new_patients), once resolved

    @property
    def label(self):
        return self.get("Patient Name")


def _parse_patient(get):
    dob = _to_date(get("Date of Birth"))
    age_computed = compute_age(dob) if dob else None
    manual_age_raw = get("Age")
    # The older version's export has ages typed as "34", "34 Y", "34 yrs" or "34.5" — take the
    # leading whole number rather than dropping the age when it isn't bare digits.
    age_match = re.match(r"\s*(\d{1,3})(?!\d)", manual_age_raw)
    manual_age = int(age_match.group(1)) if age_match else None
    age = age_computed if age_computed is not None else manual_age

    sex = get("Sex").capitalize()
    mobile = get("Mobile")
    dpdp_accepted = _yes(get("DPDP Notice Accepted"))
    dpdp_date = (_to_date(get("DPDP Notice Accepted Date")) or today_iso()) if dpdp_accepted else ""
    # No reminders consent without the data notice having been accepted first.
    comms_consent = dpdp_accepted and _yes(get("Communications Consent"))
    guardian_name = get("Guardian Name")
    guardian_mobile = get("Guardian Mobile")

    data = {
        "name": get("Patient Name"),
        "date_of_birth": dob,
        "age": age,
        "sex": sex,
        "mobile": mobile,
        "email": get("Email"),
        "address": get("Address"),
        "medical_conditions_json": "[]",
        "medical_conditions_other": get("Medical Conditions"),
        "is_pregnant": _yes(get("Is Pregnant")),
        "is_nursing": _yes(get("Is Nursing")),
        "allergies_json": "[]",
        "allergies_other": get("Allergies"),
        "emergency_contact_name": get("Emergency Contact"),
        "emergency_contact_relation": get("Emergency Contact Relation"),
        "emergency_contact_number": get("EC Number"),
        "dpdp_notice_accepted": dpdp_accepted,
        "dpdp_notice_accepted_at": dpdp_date,
        "comms_consent": comms_consent,
        "comms_consent_at": today_iso() if comms_consent else "",
        "guardian_name": guardian_name,
        "guardian_relation": get("Guardian Relation"),
        "guardian_mobile": guardian_mobile,
        "last_visited_date": _to_date(get("Last Visited")),
    }

    errors = []
    if not data["name"]:
        errors.append("Patient Name is required.")
    if sex not in SEX_OPTIONS:
        errors.append("Sex must be Male or Female.")
    if mobile and not is_valid_mobile(mobile):
        errors.append("Mobile number looks invalid — enter a 10-digit Indian mobile number.")
    if age is not None and age < 18:
        if not guardian_name:
            errors.append("Guardian name is required for patients under 18.")
        if not guardian_mobile or not is_valid_mobile(guardian_mobile):
            errors.append("A valid guardian mobile number is required for patients under 18.")

    return data, errors


_CUSTOM_PROCEDURE = re.compile(r"\(\s*Custom:\s*(.*?)\)", re.IGNORECASE)


def _split_procedures(text, procedure_types):
    """'Filling (GIC), (Custom: FILLING DONE IRT 16,26)' -> (["Filling (GIC)"] if it's a
    case type, [...rest as free text]). Custom text is pulled out first — it may contain
    commas of its own."""
    known = {name.casefold(): name for name in procedure_types}
    other = [m.strip() for m in _CUSTOM_PROCEDURE.findall(text) if m.strip()]
    procedures = []
    for name in (p.strip() for p in re.split(r"[,;\n]", _CUSTOM_PROCEDURE.sub("", text))):
        if not name:
            continue
        match = known.get(name.casefold())
        if match and match not in procedures:
            procedures.append(match)
        elif not match:
            other.append(name)
    return procedures, other


def _parse_case(get, lookups):
    errors = []
    doctor_name = get("Doctor")
    doctor_id = lookups["doctor_keys"].get(_doctor_key(doctor_name)) if doctor_name else None
    if not doctor_name:
        errors.append("Doctor is required for a case.")
    elif doctor_id is None:
        errors.append(f"Doctor '{doctor_name}' isn't an active doctor in Settings > Doctors.")

    procedures, other = _split_procedures(get("Procedures"), lookups["procedure_types"])
    if get("Other Procedure"):
        other.append(get("Other Procedure"))

    cost_text = get("Total Cost (Rs.)")
    total_cost = _parse_amount(cost_text) if cost_text else 0.0
    if total_cost is None or total_cost < 0:
        errors.append("Total Cost must be a number, 0 or more.")
        total_cost = 0.0

    status = (get("Status") or "Active").capitalize()
    if status not in CASE_STATUSES:
        errors.append("Status must be Active or Closed.")

    opened = _parse_date(get("Case Opened"), "Case Opened", errors) or today_iso()
    closed = _parse_date(get("Case Closed"), "Case Closed", errors)
    if status == "Closed":
        closed = closed or today_iso()
        if closed < opened:
            errors.append("Case Closed can't be before Case Opened.")
    elif closed:
        errors.append("Case Closed is set but Status isn't Closed.")
    follow_up = _parse_date(get("Follow-up Date"), "Follow-up Date", errors)

    case = {
        "title": get("Case Title"),
        "doctor_id": doctor_id,
        "procedures_json": json.dumps(procedures),
        "custom_procedure": ", ".join(other),
        "total_cost": total_cost,
        "status": status,
        "created_at": _timestamp_for(opened),
        "closed_at": _timestamp_for(closed) if status == "Closed" else "",
        "follow_up_date": follow_up,
        "next_action_note": get("Next Action"),
    }
    paid = _parse_paid(get, errors)
    payment_date = _parse_date(get("Payment Date"), "Payment Date", errors) or \
        (closed if status == "Closed" else "") or opened
    return case, paid, payment_date, errors


def _parse_paid(get, errors):
    text = get("Paid (Rs.)")
    if not text:
        return 0.0
    paid = _parse_amount(text)
    if paid is None or paid < 0:
        errors.append("Paid must be a number, 0 or more.")
        return 0.0
    return paid


def _payment(amount, date, get, note):
    return {
        "amount": round(amount, 2), "payment_date": date or today_iso(),
        "method": get("Payment Method"), "reference": "", "notes": note,
    }


# ── Import ────────────────────────────────────────────────────────────────

def import_patients(file_bytes, actor=None):
    """Imports the 'Patients & Cases' and 'Patients (No Cases)' sheets (or, for the original
    one-sheet template, the first sheet). Kept under its original name — the import route
    and the older tests call it."""
    result = ImportResult()
    try:
        wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception:
        result.header_error = "Could not read this file — make sure it's a valid .xlsx spreadsheet."
        return result

    titles = [t for t in (CASES_SHEET, NO_CASES_SHEET) if t in wb.sheetnames] or [wb.sheetnames[0]]
    sheets = [_Sheet(wb[t], t) for t in titles]
    if not any(s.index for s in sheets):
        result.header_error = "The spreadsheet is empty."
        return result
    for sheet in sheets:
        missing = [h for h in REQUIRED_HEADERS if h not in sheet.index]
        if missing:
            result.header_error = (
                f"Missing required column(s) on the '{sheet.title}' sheet: {', '.join(missing)}. "
                "Download the template and use its exact column headers."
            )
            return result

    raw = db.get_import_lookups()
    lookups = {
        "patients": {p["id"]: p for p in raw["patients"]},
        "patient_keys": {(_norm_name(p["name"]), _norm_mobile(p["mobile"] or "")): p["id"]
                         for p in raw["patients"] if p["mobile"]},
        "cases": raw["cases"],
        "doctor_keys": {_doctor_key(d["name"]): d["id"] for d in raw["doctors"]},
        "procedure_types": raw["procedure_types"],
    }
    rows = [row for sheet in sheets for row in sheet.data_rows(result)]

    # 1. Patients. Group rows by who they're about; each group is one patient.
    groups, order = {}, []
    for row in rows:
        ref = row.get("Patient Ref")
        if ref and _is_existing_id(ref):
            key = ("id", int(ref))
        elif ref:
            key = ("label", ref.casefold())
        elif row.label:
            key = ("auto", _norm_name(row.label), _norm_mobile(row.get("Mobile")))
        else:
            key = ("row", row.sheet, row.number)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    new_patients = []
    for key in order:
        group = groups[key]
        if key[0] == "id":
            existing = lookups["patients"].get(key[1])
            for row in group:
                if existing is None:
                    row.errors.append(f"Patient Ref {key[1]} isn't a Feast9 patient ID — leave it blank for a new patient.")
                elif row.label and _norm_name(row.label) != _norm_name(existing["name"]):
                    row.errors.append(f"Patient Ref {key[1]} is {existing['name']}, not {row.label}.")
                else:
                    row.patient = ("id", key[1])
            if existing is not None:
                result.unchanged["Patients"] += 1
            continue

        # A new patient: take each field from the first row that has it.
        def merged(col, _group=group):
            return next((r.get(col) for r in _group if r.get(col)), "")

        data, errors = _parse_patient(merged)
        visits = [_to_date(r.get("Last Visited")) for r in group]
        data["last_visited_date"] = max([v for v in visits if v], default="")
        existing_id = lookups["patient_keys"].get((_norm_name(data["name"]), _norm_mobile(data["mobile"])))
        if existing_id and data["mobile"]:
            errors.append(f"{data['name']} ({data['mobile']}) is already in Feast9 as patient {existing_id} — "
                          f"put {existing_id} in Patient Ref to add cases to them.")
        if errors:
            first = group[0]
            first.errors.extend(errors)
            for row in group[1:]:
                row.errors.append(f"Its patient was skipped (see {first.sheet} row {first.number}).")
            continue
        for row in group:
            row.patient = ("new", len(new_patients))
        new_patients.append(data)

    # 2. Cases (and the Paid column) — only on rows whose patient resolved.
    new_cases, new_payments = [], []
    for row in rows:
        if row.errors:
            continue
        case_ref = row.get("Case Ref")
        if case_ref and _is_existing_id(case_ref):
            existing = lookups["cases"].get(int(case_ref))
            if existing is None:
                row.errors.append(f"Case Ref {case_ref} isn't a Feast9 case ID — leave it blank for a new case.")
            elif row.patient != ("id", existing["patient_id"]):
                row.errors.append(f"Case {case_ref} belongs to patient {existing['patient_id']}, not this row's patient.")
            else:
                result.unchanged["Cases"] += 1
                paid = _parse_paid(row.get, row.errors)
                extra = round(paid - existing["paid"], 2)
                if row.get("Paid (Rs.)") and extra < 0:
                    row.errors.append(f"Paid ({paid:g}) is less than the {existing['paid']:g} already recorded in "
                                      f"Feast9 — payments can't be reduced, so nothing was changed.")
                elif row.get("Paid (Rs.)") and extra > 0:
                    date = _parse_date(row.get("Payment Date"), "Payment Date", row.errors) or today_iso()
                    if not row.errors:
                        new_payments.append(dict(_payment(extra, date, row.get, "Recorded in the Plan B spreadsheet"),
                                                 case=("id", int(case_ref))))
            continue

        if not row.get("Case Title"):
            has_case_data = any(row.get(h) for h in ("Doctor", "Procedures", "Total Cost (Rs.)", "Paid (Rs.)"))
            if has_case_data:
                row.errors.append("Case not imported: Case Title is required when the row has case details.")
            continue

        case, paid, payment_date, errors = _parse_case(row.get, lookups)
        if errors:
            # The row's patient (if new and valid) is still imported — say it's only the case.
            row.errors.extend(f"Case not imported: {e}" for e in errors)
            continue
        case["patient"] = row.patient
        new_cases.append(case)
        if paid > 0:
            new_payments.append(dict(_payment(paid, payment_date, row.get, "Total paid, imported from spreadsheet"),
                                     case=("new", len(new_cases) - 1)))

    for row in rows:
        if row.errors:
            result.skipped.append({
                "sheet": row.sheet, "row": row.number,
                "name": " — ".join(x for x in (row.label, row.get("Case Title")) if x),
                "errors": row.errors,
            })

    if new_patients or new_cases or new_payments:
        counts = db.import_workbook(new_patients, new_cases, new_payments, actor=actor)
        result.imported_count = counts["patients"]
        result.cases_imported = counts["cases"]
        result.payments_imported = counts["payments"]

    return result
