"""DPDP Phase 2 — data-rights requests (feast9_v2_agents.md §5.11)."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
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
