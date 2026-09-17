"""Dental charting (§14 item) — structured data is the source of truth; the chart below is
just a presentation layer built from it. Append-only, like visit notes/prescriptions: a
correction is a new entry, never an edit of an old one."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
from app.auth import current_actor, login_required
from app.constants import (
    ALL_TEETH,
    CHART_FINDING_COLORS,
    CHART_FINDINGS,
    CHART_STATUSES,
    PERMANENT_TEETH_LOWER,
    PERMANENT_TEETH_UPPER,
    PRIMARY_TEETH_LOWER,
    PRIMARY_TEETH_UPPER,
    TOOTH_SURFACES,
    WHOLE_TOOTH_FINDINGS,
)
from app.csrf import validate_csrf

bp = Blueprint("dental", __name__)


def _get_patient_or_404(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    return patient


@bp.route("/patients/<int:patient_id>/dental-chart", methods=["GET", "POST"])
@login_required
def chart(patient_id):
    patient = _get_patient_or_404(patient_id)
    errors = []
    form_state = {
        "tooth_id": request.args.get("tooth", ""), "surface": "Whole Tooth",
        "finding": "", "status": "Existing", "notes": "", "case_id": "",
    }

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        tooth_id = request.form.get("tooth_id", "")
        surface = request.form.get("surface", "Whole Tooth")
        finding = request.form.get("finding", "")
        status = request.form.get("status", "Existing")
        notes = request.form.get("notes", "").strip()
        case_id_raw = request.form.get("case_id", "")
        case_id = int(case_id_raw) if case_id_raw.isdigit() else None
        form_state = {
            "tooth_id": tooth_id, "surface": surface, "finding": finding,
            "status": status, "notes": notes, "case_id": case_id_raw,
        }

        if tooth_id not in ALL_TEETH:
            errors.append("Select a valid tooth.")
        if finding not in CHART_FINDINGS:
            errors.append("Select a valid finding.")
        if status not in CHART_STATUSES:
            errors.append("Select a valid status.")
        if surface not in TOOTH_SURFACES:
            errors.append("Select a valid surface.")

        if not errors:
            if finding in WHOLE_TOOTH_FINDINGS:
                surface = "Whole Tooth"
            db.add_dental_chart_entry(
                patient_id, case_id, tooth_id, surface, finding, status, notes, actor=current_actor()
            )
            flash(f"Chart entry added for tooth {tooth_id}.", "success")
            return redirect(url_for("dental.chart", patient_id=patient_id))

    return render_template(
        "dental_chart.html",
        patient=patient,
        errors=errors,
        form_state=form_state,
        current_chart=db.get_current_dental_chart(patient_id),
        history=db.list_dental_chart_entries(patient_id),
        cases=db.list_cases_for_patient(patient_id),
        teeth_upper_permanent=PERMANENT_TEETH_UPPER,
        teeth_lower_permanent=PERMANENT_TEETH_LOWER,
        teeth_upper_primary=PRIMARY_TEETH_UPPER,
        teeth_lower_primary=PRIMARY_TEETH_LOWER,
        surfaces=TOOTH_SURFACES,
        findings=CHART_FINDINGS,
        statuses=CHART_STATUSES,
        finding_colors=CHART_FINDING_COLORS,
    )
