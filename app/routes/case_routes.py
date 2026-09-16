import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
from app.auth import can_view_financial_data, current_actor, financial_access_required, login_required
from app.constants import ATTACHMENT_TYPES, LAB_REQ_STATUSES
from app.csrf import validate_csrf
from app.validators import normalize_date, today_iso

bp = Blueprint("cases", __name__)


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


def _validate_case(data):
    errors = []
    if not data["title"]:
        errors.append("Case title is required.")
    if data["doctor_id"] is None:
        errors.append("A doctor must be selected.")
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
def new(patient_id):
    patient = _get_patient_or_404(patient_id)
    errors = []
    form_state = {"procedures": []}

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        data = _collect_case_form(request.form)
        if not can_view_financial_data():
            data["total_cost"] = 0  # receptionist has zero access to financial data — enforced here, not just hidden in the form
        form_state = data
        errors = _validate_case(data)
        if not errors:
            data["patient_id"] = patient_id
            case_id = db.add_case(data)
            flash("Case created.", "success")
            return redirect(url_for("cases.detail", case_id=case_id))

    return render_template(
        "case_form.html",
        patient=patient,
        case=form_state,
        errors=errors,
        doctors=db.list_doctors(),
        procedure_types=db.list_procedure_types(),
        editing=False,
    )


@bp.route("/cases/<int:case_id>")
@login_required
def detail(case_id):
    case = _get_case_or_404(case_id)
    patient = db.get_patient(case["patient_id"])
    patient["allergies"] = json.loads(patient.get("allergies_json") or "[]")
    case["procedures"] = json.loads(case.get("procedures_json") or "[]")
    doctor = db.get_doctor(case["doctor_id"]) if case.get("doctor_id") else None
    visit_notes = db.list_visit_notes_for_case(case_id)
    prescriptions = db.list_prescriptions_for_case(case_id)
    attachments = db.list_attachments_for_case(case_id)
    lab_reqs = db.list_lab_reqs_for_case(case_id)
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
        prescriptions=prescriptions,
        attachments=attachments,
        attachment_types=ATTACHMENT_TYPES,
        lab_reqs=lab_reqs,
        lab_req_statuses=LAB_REQ_STATUSES,
        referrals=referrals,
        payments=payments,
        balance=balance,
        cost_revisions=cost_revisions,
        can_view_financial=can_view_financial,
        today=today_iso(),
    )


@bp.route("/cases/<int:case_id>/edit", methods=["GET", "POST"])
@login_required
def edit(case_id):
    case = _get_case_or_404(case_id)
    patient = db.get_patient(case["patient_id"])
    errors = []

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        data = _collect_case_form(request.form)
        errors = _validate_case(data)
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
        doctors=db.list_doctors(),
        procedure_types=db.list_procedure_types(),
        editing=True,
    )


@bp.route("/cases/<int:case_id>/visit-notes", methods=["POST"])
@login_required
def add_visit_note(case_id):
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)
    note = request.form.get("note", "").strip()
    visit_date = normalize_date(request.form.get("visit_date", "")) or today_iso()
    if note:
        db.add_visit_note(case_id, case["patient_id"], note, visit_date, actor=current_actor())
        flash("Visit note added.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/cases/<int:case_id>/prescriptions", methods=["POST"])
@login_required
def add_prescription(case_id):
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)
    rx_details = request.form.get("rx_details", "").strip()
    prescribed_date = normalize_date(request.form.get("prescribed_date", "")) or today_iso()
    if rx_details:
        db.add_prescription(case_id, case["patient_id"], rx_details, prescribed_date, actor=current_actor())
        flash("Prescription added.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


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


@bp.route("/cases/<int:case_id>/consent", methods=["POST"])
@login_required
def record_consent(case_id):
    validate_csrf(request.form.get("csrf_token"))
    _get_case_or_404(case_id)
    notes = request.form.get("consent_notes", "").strip() or "Paper consent on file"
    db.record_case_consent(case_id, notes, actor=current_actor())
    flash("Consent recorded.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/cases/<int:case_id>/close", methods=["POST"])
@login_required
def close(case_id):
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)
    if case["status"] == "Active":
        db.close_case(case_id, actor=current_actor())
        flash("Case closed.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))
