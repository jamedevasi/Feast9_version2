import io
import json
import pathlib

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for

from app import config as app_config
from app import allergy_check, db, pdf_reports
from app.auth import can_view_financial_data, clinical_access_required, current_actor, financial_access_required, login_required, logs_view
from app.constants import (
    ATTACHMENT_TYPES, LAB_REQ_STATUSES, MAX_PRESCRIPTION_MEDICINES, PRESCRIPTION_FREQUENCIES,
    PRESCRIPTION_ROUTES,
)
from app.csrf import validate_csrf
from app.validators import normalize_date, today_iso

bp = Blueprint("cases", __name__)


def _send_pdf(pdf_bytes, download_name):
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", download_name=download_name)


def _collect_case_form(form):
    doctor_id = form.get("doctor_id", "").strip()
    total_cost_raw = form.get("total_cost", "").strip()
    return {
        "title": form.get("title", "").strip(),
        "procedures": form.getlist("procedures"),
        "procedures_json": json.dumps(form.getlist("procedures")),
        "custom_procedure": form.get("custom_procedure", "").strip(),
        "doctor_id": int(doctor_id) if doctor_id.isdigit() else None,
        "total_cost": float(total_cost_raw) if total_cost_raw else 0,
    }


def _validate_case(data, current_doctor_id=None):
    """current_doctor_id: the doctor an edited case already has — still allowed if since
    deactivated (a new case can only get an active doctor)."""
    errors = []
    if not data["title"]:
        errors.append("Case title is required.")
    doctor_error = db.doctor_choice_error(data["doctor_id"], current_doctor_id)
    if doctor_error:
        errors.append(doctor_error)
    return errors


def _get_patient_or_404(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    return patient


def _get_case_or_404(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    return case


@bp.route("/patients/<int:patient_id>/cases/new", methods=["GET", "POST"])
@login_required
@clinical_access_required
def new(patient_id):
    patient = _get_patient_or_404(patient_id)
    errors = []
    form_state = {"procedures": []}

    # "New Case" from an appointment that was booked for the patient without a case: the case
    # starts from the appointment's title and doctor, and the appointment is linked to it.
    appt_arg = request.values.get("appointment_id", "")
    appointment = db.get_appointment(int(appt_arg)) if appt_arg.isdigit() else None
    if appointment and (appointment["patient_id"] != patient_id or appointment["case_id"]):
        appointment = None
    if appointment and request.method == "GET":
        doctor = db.get_doctor(appointment["doctor_id"]) if appointment["doctor_id"] else None
        form_state.update(
            title=appointment["title"] or "",
            doctor_id=doctor["id"] if doctor and doctor["is_active"] else None,
        )

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        data = _collect_case_form(request.form)
        if not can_view_financial_data():
            data["total_cost"] = 0  # receptionist / guest doctor: no financial data — enforced here, not just hidden in the form
        form_state = data
        errors = _validate_case(data)
        if not errors:
            data["patient_id"] = patient_id
            case_id = db.add_case(data)
            flash("Case created.", "success")
            if appointment:
                db.set_appointment_case(appointment["id"], case_id)
                flash(f"The appointment on {appointment['appt_date']} is linked to this case.", "success")
            return redirect(url_for("cases.detail", case_id=case_id))

    return render_template(
        "case_form.html",
        patient=patient,
        case=form_state,
        errors=errors,
        doctors=db.list_doctors(),
        procedure_types=db.list_procedure_types(),
        editing=False,
        appointment=appointment,
    )


@bp.route("/cases/<int:case_id>")
@login_required
@clinical_access_required
@logs_view("case_viewed", "case", "case_id")
def detail(case_id):
    case = _get_case_or_404(case_id)
    patient = db.get_patient(case["patient_id"])
    patient["allergies"] = json.loads(patient.get("allergies_json") or "[]")
    case["procedures"] = json.loads(case.get("procedures_json") or "[]")
    doctor = db.get_doctor(case["doctor_id"]) if case.get("doctor_id") else None
    visit_notes = db.list_visit_notes_for_case(case_id)
    prescriptions = db.list_prescriptions_for_case(case_id)
    rx_doctors = db.list_doctors()
    # A prescription that failed validation comes back once, so nothing typed is lost.
    draft = session.pop("rx_draft", None)
    if draft and draft.get("case_id") == case_id:
        rx_form = draft
    else:
        rx_form = {"prescribed_date": today_iso(), "doctor_id": case.get("doctor_id"),
                   "diagnosis": "", "medications": [], "advice": ""}
    attachments = db.list_attachments_for_case(case_id)
    lab_reqs = db.list_lab_reqs_for_case(case_id)
    upcoming_appt_date = db.get_next_scheduled_appointment_within(case["patient_id"])
    referrals = db.list_referrals_for_case(case_id)

    can_view_financial = can_view_financial_data()
    if can_view_financial:
        payments = db.list_payments_for_case(case_id)
        balance = db.get_case_balance(case_id)
        cost_revisions = db.list_cost_revisions_for_case(case_id)
    else:
        # Receptionist: zero access to financial data — never sent to the client, not just hidden.
        case["total_cost"] = None
        payments, balance, cost_revisions = [], None, []

    return render_template(
        "case_detail.html",
        case=case,
        patient=patient,
        doctor=doctor,
        visit_notes=visit_notes,
        note_doctors=db.list_doctors_for_choice([case.get("doctor_id")]),
        note_doctor_default=db.get_visit_doctor_id(case_id, today_iso()),
        prescriptions=prescriptions,
        rx_form=rx_form,
        rx_doctors=rx_doctors,
        rx_clinic_gaps=_clinic_print_gaps(),
        rx_doctor_gaps=_doctor_print_gaps(rx_doctors),
        rx_routes=PRESCRIPTION_ROUTES,
        rx_frequencies=PRESCRIPTION_FREQUENCIES,
        rx_max_medicines=MAX_PRESCRIPTION_MEDICINES,
        attachments=attachments,
        attachment_types=ATTACHMENT_TYPES,
        lab_reqs=lab_reqs,
        lab_req_statuses=LAB_REQ_STATUSES,
        upcoming_appt_date=upcoming_appt_date,
        referrals=referrals,
        payments=payments,
        balance=balance,
        cost_revisions=cost_revisions,
        can_view_financial=can_view_financial,
        today=today_iso(),
    )


@bp.route("/cases/<int:case_id>/summary.pdf")
@login_required
@clinical_access_required
@logs_view("case_summary_pdf_viewed", "case", "case_id")
def summary_pdf(case_id):
    case = _get_case_or_404(case_id)
    patient = db.get_patient(case["patient_id"])
    can_view_financial = can_view_financial_data()
    if can_view_financial:
        payments = db.list_payments_for_case(case_id)
        balance = db.get_case_balance(case_id)
        cost_revisions = db.list_cost_revisions_for_case(case_id)
    else:
        payments, balance, cost_revisions = [], None, []
    pdf_bytes = pdf_reports.generate_case_summary_pdf(case, patient, payments, balance, cost_revisions, can_view_financial)
    return _send_pdf(pdf_bytes, f"case-summary-{case_id}.pdf")


@bp.route("/cases/<int:case_id>/edit", methods=["GET", "POST"])
@login_required
@clinical_access_required
def edit(case_id):
    case = _get_case_or_404(case_id)
    patient = db.get_patient(case["patient_id"])
    current_doctor_id = case.get("doctor_id")
    errors = []

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        data = _collect_case_form(request.form)
        errors = _validate_case(data, current_doctor_id)
        if not errors:
            db.update_case(case_id, data)
            flash("Case updated.", "success")
            return redirect(url_for("cases.detail", case_id=case_id))
        case = {**case, **data}

    case["procedures"] = case.get("procedures", json.loads(case.get("procedures_json") or "[]"))

    return render_template(
        "case_form.html",
        patient=patient,
        case=case,
        errors=errors,
        # Keeps a since-deactivated doctor selectable on their own case, so an unrelated edit
        # (a title fix) doesn't force the case onto someone else.
        doctors=db.list_doctors_for_choice([current_doctor_id]),
        procedure_types=db.list_procedure_types(),
        editing=True,
    )


@bp.route("/cases/<int:case_id>/visit-notes", methods=["POST"])
@login_required
@clinical_access_required
def add_visit_note(case_id):
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)
    note = request.form.get("note", "").strip()
    visit_date = normalize_date(request.form.get("visit_date", "")) or today_iso()
    if note:
        # "Attended by" is prefilled (today's appointment doctor, else the case's doctor). Only
        # a choice the user changed counts as explicit; an untouched one leaves the attending
        # doctor to be read from the appointment on the note's own visit date.
        attended = request.form.get("attended_by", "")
        attended_id = int(attended) if attended.isdigit() else None
        if attended == request.form.get("attended_default", "") or not attended_id or db.doctor_choice_error(
            attended_id, case.get("doctor_id")
        ):
            attended_id = None
        completed = db.add_visit_note(
            case_id, case["patient_id"], note, visit_date, actor=current_actor(),
            attended_by_doctor_id=attended_id,
        )
        flash("Visit note added.", "success")
        if completed:
            flash(
                f"The {completed['start_time']} appointment on {completed['appt_date']} was marked Completed.",
                "success",
            )
            # Same rule as marking it Completed by hand: attending a later appointment settles
            # an earlier no-show's "please reschedule" follow-up.
            db.resolve_noshow_followups_for_patient(case["patient_id"], completed["appt_date"])
    return redirect(url_for("cases.detail", case_id=case_id))


_MEDICINE_FIELDS = ["generic", "brand", "strength", "dose", "frequency", "route", "duration", "instructions"]
# What every medicine line must state; brand, duration and instructions are optional.
_MEDICINE_REQUIRED = {
    "generic": "generic name", "strength": "strength", "dose": "dosage",
    "frequency": "frequency", "route": "route",
}


def _collect_prescription_form(form):
    """Medicine rows arrive as parallel med_<field> lists; a row left entirely blank is
    dropped (`row_numbers` keeps each kept row's on-screen number for error messages)."""
    columns = [form.getlist(f"med_{f}") for f in _MEDICINE_FIELDS]
    medications, row_numbers = [], []
    for i in range(min(max((len(c) for c in columns), default=0), MAX_PRESCRIPTION_MEDICINES)):
        med = {f: (col[i].strip() if i < len(col) else "") for f, col in zip(_MEDICINE_FIELDS, columns)}
        # The route drop-down always submits a value, so it alone doesn't make a row "filled".
        if any(v for f, v in med.items() if f != "route"):
            medications.append(med)
            row_numbers.append(i + 1)
    doctor_id = form.get("prescriber_id", "").strip()
    return {
        "prescribed_date": normalize_date(form.get("prescribed_date", "")) or today_iso(),
        "doctor_id": int(doctor_id) if doctor_id.isdigit() else None,
        "diagnosis": form.get("diagnosis", "").strip(),
        "medications": medications,
        "row_numbers": row_numbers,
        "advice": form.get("advice", "").strip(),
    }


def _validate_prescription(data):
    errors = []
    doctor = db.get_doctor(data["doctor_id"]) if data["doctor_id"] else None
    if not doctor or not doctor["is_active"]:
        errors.append("Choose the prescribing doctor.")
    if not data["diagnosis"]:
        errors.append("Enter the diagnosis the medicines are prescribed for.")
    if not data["medications"]:
        errors.append("Enter at least one medicine.")
    for number, med in zip(data["row_numbers"], data["medications"]):
        missing = [label for field, label in _MEDICINE_REQUIRED.items() if not med[field]]
        if med["route"] and med["route"] not in PRESCRIPTION_ROUTES:
            missing.append("route")
        if missing:
            errors.append(f"Medicine {number}: enter the {', '.join(missing)}.")
    return errors


def prescription_text(diagnosis, medications, advice):
    """The whole prescription as plain text — stored in rx_details, so every place that only
    shows text (patient summary / data-access PDFs, the Excel copy) carries the same content."""
    lines = [f"Diagnosis: {diagnosis}"]
    for n, med in enumerate(medications, start=1):
        name = med["generic"].upper() + (f" ({med['brand']})" if med["brand"] else "")
        parts = [f"{name} {med['strength']}", med["dose"], med["frequency"], med["route"]]
        if med["duration"]:
            parts.append(f"for {med['duration']}")
        line = f"{n}. " + ", ".join(parts)
        if med["instructions"]:
            line += f" - {med['instructions']}"
        lines.append(line)
    if advice:
        lines.append(f"Advice: {advice}")
    return "\n".join(lines)


@bp.route("/cases/<int:case_id>/prescriptions", methods=["POST"])
@login_required
@clinical_access_required
def add_prescription(case_id):
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)
    data = _collect_prescription_form(request.form)
    errors = _validate_prescription(data)
    if errors:
        for message in errors:
            flash(message, "warning")
        # Nothing typed is lost: the case page refills the form from this once.
        session["rx_draft"] = {"case_id": case_id, **{k: v for k, v in data.items() if k != "row_numbers"}}
        return redirect(url_for("cases.detail", case_id=case_id) + "#prescriptions")
    # A medicine that may conflict with a recorded allergy is held back until the doctor
    # confirms they've checked — and the confirmation covers exactly the medicines it was
    # shown for, so adding another conflicting one asks again.
    conflicts = allergy_check.conflicts(db.get_patient(case["patient_id"]), data["medications"],
                                        data["row_numbers"])
    allergy_key = _allergy_key(conflicts)
    if conflicts and request.form.get("allergy_checked") != allergy_key:
        flash("Check the patient's allergies before prescribing — see the warning on the form.", "warning")
        session["rx_draft"] = {"case_id": case_id, **{k: v for k, v in data.items() if k != "row_numbers"},
                               "allergy_conflicts": conflicts, "allergy_key": allergy_key}
        return redirect(url_for("cases.detail", case_id=case_id) + "#prescriptions")
    session.pop("rx_draft", None)
    db.add_prescription(
        case_id, case["patient_id"],
        prescription_text(data["diagnosis"], data["medications"], data["advice"]),
        data["prescribed_date"], actor=current_actor(),
        diagnosis=data["diagnosis"], medications=data["medications"], advice=data["advice"],
        doctor_id=data["doctor_id"], allergy_override=bool(conflicts),
    )
    flash("Prescription added.", "success")
    return redirect(url_for("cases.detail", case_id=case_id) + "#prescriptions")


def _allergy_key(conflicts):
    """Identifies the set of medicines an allergy confirmation was given for."""
    return "|".join(sorted({name.lower() for _number, name, _label in conflicts}))


def _clinic_print_gaps():
    """What a printed prescription would lack from the clinic's own details right now."""
    if db.get_setting("clinic_address", "") and db.get_setting("clinic_phone", ""):
        return []
    return ["the clinic's address and phone number (Settings, Clinic Details)"]


def _doctor_print_gaps(doctors):
    """{doctor id: what a prescription from that doctor would lack} — only doctors missing
    their qualifications or registration number. The form shows the chosen doctor's only."""
    gaps = {}
    for d in doctors:
        missing = [label for field, label in (("qualifications", "qualifications"),
                                              ("registration_number", "registration number")) if not d.get(field)]
        if missing:
            gaps[d["id"]] = f"{d['name']}'s {' and '.join(missing)} (Settings, Doctors)"
    return gaps


@bp.route("/cases/<int:case_id>/prescriptions/<int:rx_id>.pdf")
@login_required
@clinical_access_required
@logs_view("prescription_pdf_viewed", "prescription", "rx_id")
def prescription_pdf(case_id, rx_id):
    case = _get_case_or_404(case_id)
    prescription = db.get_prescription(rx_id)
    if not prescription or prescription["case_id"] != case_id:
        abort(404)
    patient = db.get_patient(case["patient_id"])
    # The prescriber recorded on the prescription; one written before that was recorded
    # falls back to the case's doctor.
    doctor_id = prescription.get("doctor_id") or case.get("doctor_id")
    doctor = db.get_doctor(doctor_id) if doctor_id else None
    pdf_bytes = pdf_reports.generate_prescription_pdf(prescription, case, patient, doctor)
    return _send_pdf(pdf_bytes, f"prescription-{rx_id}.pdf")


@bp.route("/cases/<int:case_id>/payments", methods=["POST"])
@login_required
@financial_access_required
def add_payment(case_id):
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)

    amount_raw = request.form.get("amount", "").strip()
    try:
        amount = float(amount_raw)
    except ValueError:
        amount = 0

    if amount <= 0:
        flash("Payment amount must be greater than zero.", "warning")
        return redirect(url_for("cases.detail", case_id=case_id))

    payment_date = normalize_date(request.form.get("payment_date", "")) or today_iso()
    method = request.form.get("method", "").strip()
    reference = request.form.get("reference", "").strip()
    notes = request.form.get("notes", "").strip()

    db.add_payment(case_id, case["patient_id"], payment_date, amount, method, reference, notes, actor=current_actor())
    flash("Payment recorded.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/cases/<int:case_id>/revise-cost", methods=["POST"])
@login_required
@financial_access_required
def revise_cost(case_id):
    validate_csrf(request.form.get("csrf_token"))
    _get_case_or_404(case_id)

    new_cost_raw = request.form.get("new_cost", "").strip()
    reason = request.form.get("reason", "").strip()
    try:
        new_cost = float(new_cost_raw)
    except ValueError:
        flash("Enter a valid cost.", "warning")
        return redirect(url_for("cases.detail", case_id=case_id))

    if new_cost < 0:
        flash("Cost cannot be negative.", "warning")
        return redirect(url_for("cases.detail", case_id=case_id))
    if not reason:
        flash("A reason is required when changing the case cost.", "warning")
        return redirect(url_for("cases.detail", case_id=case_id))

    db.update_case_cost(case_id, new_cost, reason, actor=current_actor())
    flash("Cost updated.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/cases/<int:case_id>/followup", methods=["POST"])
@login_required
def update_followup(case_id):
    validate_csrf(request.form.get("csrf_token"))
    _get_case_or_404(case_id)
    follow_up_date = normalize_date(request.form.get("follow_up_date", ""))
    next_action_note = request.form.get("next_action_note", "").strip()
    db.update_case_followup(case_id, follow_up_date, next_action_note)
    flash("Follow-up cleared." if not follow_up_date else "Follow-up saved.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/cases/<int:case_id>/followup/done", methods=["POST"])
@login_required
def complete_followup(case_id):
    """Marks a follow-up as done so it drops off the dashboard. `next=dashboard` (the dashboard's
    own button) returns there; anything else goes back to the case."""
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)
    if case["follow_up_date"]:
        db.complete_case_followup(case_id, actor=current_actor())
        flash("Follow-up marked done.", "success")
    if request.form.get("next") == "dashboard":
        return redirect(url_for("dashboard.index"))
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/cases/<int:case_id>/consent", methods=["POST"])
@login_required
@clinical_access_required
def record_consent(case_id):
    validate_csrf(request.form.get("csrf_token"))
    _get_case_or_404(case_id)
    # Consent is signed on paper (the printed consent form) — this only records that it was.
    notes = request.form.get("consent_notes", "").strip() or "Paper consent on file"
    db.record_case_consent(case_id, notes, actor=current_actor())
    flash("Consent recorded.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/cases/<int:case_id>/consent-signature")
@login_required
@clinical_access_required
@logs_view("consent_signature_viewed", "case", "case_id")
def consent_signature(case_id):
    case = _get_case_or_404(case_id)
    filename = case.get("consent_signature_filename") or ""
    if not filename:
        abort(404)
    path = pathlib.Path(app_config.uploads_dir()) / filename
    if not path.exists():
        abort(404)
    ext = path.suffix.lower().lstrip(".")
    mimetype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "application/octet-stream")
    return send_file(str(path), mimetype=mimetype)


@bp.route("/cases/<int:case_id>/consent.pdf")
@login_required
@clinical_access_required
@logs_view("consent_pdf_viewed", "case", "case_id")
def consent_pdf(case_id):
    case = _get_case_or_404(case_id)
    patient = db.get_patient(case["patient_id"])
    signature_bytes = None
    filename = case.get("consent_signature_filename") or ""
    if filename:
        path = pathlib.Path(app_config.uploads_dir()) / filename
        if path.exists():
            signature_bytes = path.read_bytes()
    doctor = db.get_doctor(case["doctor_id"]) if case.get("doctor_id") else None
    pdf_bytes = pdf_reports.generate_consent_pdf(case, patient, doctor=doctor, signature_bytes=signature_bytes)
    return _send_pdf(pdf_bytes, f"consent-{case_id}.pdf")


@bp.route("/cases/<int:case_id>/close", methods=["POST"])
@login_required
@clinical_access_required
def close(case_id):
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)
    if case["status"] == "Active":
        db.close_case(case_id, actor=current_actor())
        flash("Case closed.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))
