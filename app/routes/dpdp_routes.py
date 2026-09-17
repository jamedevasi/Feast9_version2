"""DPDP Phase 2 — data-rights requests (feast9_v2_agents.md §5.11)."""
import io

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

from app import db, pdf_reports
from app.auth import current_actor, login_required, reauth_required, role_required
from app.constants import DATA_REQUEST_STATUSES, DATA_REQUEST_TYPES
from app.csrf import validate_csrf
from app.validators import today_iso

bp = Blueprint("dpdp", __name__)


def _get_patient_or_404(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    return patient


def _get_request_or_404(request_id):
    row = db.get_data_request(request_id)
    if not row:
        abort(404)
    return row


@bp.route("/patients/<int:patient_id>/data-requests/new", methods=["GET", "POST"])
@login_required
def new_data_request(patient_id):
    patient = _get_patient_or_404(patient_id)
    errors = []
    form_state = {"request_type": "", "description": ""}

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        request_type = request.form.get("request_type", "")
        description = request.form.get("description", "").strip()
        form_state = {"request_type": request_type, "description": description}

        if request_type not in DATA_REQUEST_TYPES:
            errors.append("Select a valid request type.")
        if not description:
            errors.append("A description of the request is required.")

        if not errors:
            db.create_data_request(patient_id, request_type, description, actor=current_actor())
            flash("Data-rights request logged.", "success")
            return redirect(url_for("patients.detail", patient_id=patient_id))

    return render_template(
        "data_request_form.html", patient=patient, errors=errors,
        request_state=form_state, request_types=DATA_REQUEST_TYPES,
    )


@bp.route("/data-requests")
@login_required
def list_view():
    status = request.args.get("status", "")
    entries = db.list_data_requests(status=status or None)
    return render_template(
        "data_requests_list.html", entries=entries, statuses=DATA_REQUEST_STATUSES,
        current_status=status, today=today_iso(),
    )


@bp.route("/data-requests/<int:request_id>")
@login_required
def detail(request_id):
    entry = _get_request_or_404(request_id)
    patient = db.get_patient(entry["patient_id"])
    return render_template("data_request_detail.html", entry=entry, patient=patient, statuses=DATA_REQUEST_STATUSES)


@bp.route("/data-requests/<int:request_id>/access.pdf")
@login_required
@role_required("admin", "doctor")
def access_pdf(request_id):
    """DPDP Phase 2 right-to-access export (feast9_v2_agents.md §10) — only meaningful
    for an Access request, but any request's patient can still be exported this way."""
    entry = _get_request_or_404(request_id)
    patient = db.get_patient(entry["patient_id"])
    cases = db.list_cases_for_patient(entry["patient_id"])
    prescriptions = db.list_prescriptions_for_patient(entry["patient_id"])
    appointments = db.list_appointments_for_patient(entry["patient_id"])
    payments = [p for c in cases for p in db.list_payments_for_case(c["id"])]
    for p in payments:
        p["case_title"] = next(c["title"] for c in cases if c["id"] == p["case_id"])
    pdf_bytes = pdf_reports.generate_data_access_pdf(patient, cases, prescriptions, payments, appointments)
    db.write_audit_now(
        current_actor(), "data_access_pdf_downloaded", "patient", entry["patient_id"],
        after_summary=f"data_request_id={request_id}",
    )
    return send_file(
        io.BytesIO(pdf_bytes), mimetype="application/pdf",
        download_name=f"data-access-{entry['patient_id']}.pdf",
    )


@bp.route("/data-requests/<int:request_id>/resolve", methods=["POST"])
@login_required
@role_required("admin", "doctor")
@reauth_required
def resolve(request_id):
    validate_csrf(request.form.get("csrf_token"))
    _get_request_or_404(request_id)

    new_status = request.form.get("status", "")
    resolution_note = request.form.get("resolution_note", "").strip()
    confirm_name = request.form.get("confirm_name", "")

    if new_status not in DATA_REQUEST_STATUSES:
        flash("Select a valid status.", "warning")
        return redirect(url_for("dpdp.detail", request_id=request_id))

    try:
        db.resolve_data_request(
            request_id, new_status, resolution_note, confirm_name=confirm_name, actor=current_actor()
        )
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("dpdp.detail", request_id=request_id))

    flash("Request updated.", "success")
    return redirect(url_for("dpdp.detail", request_id=request_id))
