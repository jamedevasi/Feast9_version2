"""Appointments — confirmed calendar bookings, distinct from a case's Follow-up reminder."""
import calendar as calendar_module
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
from app.auth import login_required
from app.constants import APPOINTMENT_STATUSES
from app.csrf import validate_csrf
from app.validators import normalize_date, today_iso

bp = Blueprint("appointments", __name__, url_prefix="/appointments")


def _get_appointment_or_404(appt_id):
    appt = db.get_appointment(appt_id)
    if not appt:
        abort(404)
    return appt


def _collect_appointment_form(form):
    doctor_id = form.get("doctor_id", "").strip()
    patient_id = form.get("patient_id", "").strip()
    status = form.get("status", "Scheduled")
    if status not in APPOINTMENT_STATUSES:
        status = "Scheduled"
    return {
        "patient_id": int(patient_id) if patient_id.isdigit() else None,
        "doctor_id": int(doctor_id) if doctor_id.isdigit() else None,
        "appt_date": normalize_date(form.get("appt_date", "")),
        "start_time": form.get("start_time", "").strip(),
        "end_time": form.get("end_time", "").strip(),
        "title": form.get("title", "").strip(),
        "notes": form.get("notes", "").strip(),
        "status": status,
    }


def _validate_appointment(data):
    errors = []
    if not data["patient_id"] or not db.get_patient(data["patient_id"]):
        errors.append("A valid patient must be selected.")
    if not data["doctor_id"]:
        errors.append("A doctor must be selected.")
    if not data["appt_date"]:
        errors.append("A valid appointment date is required.")
    if not data["start_time"]:
        errors.append("Start time is required.")
    return errors


def _handle_noshow_followup(patient_id, appt_date):
    """Set follow-up reminder for next day on patient's most recent active case."""
    next_day = (date.today() + timedelta(days=1)).isoformat()
    try:
        cases = db.list_cases_for_patient(patient_id)
        active = sorted(
            [c for c in cases if c.get("status") == "Active"],
            key=lambda c: c.get("updated_at", ""), reverse=True,
        )
        if active:
            db.update_case_followup(
                active[0]["id"], next_day,
                f"Patient did not attend appointment on {appt_date} — please reschedule",
            )
            flash(f"Follow-up reminder set for {next_day}.", "warning")
    except Exception:
        pass  # follow-up is best-effort; don't block the save


def _redirect_to_calendar_for(appt_date_str):
    d = date.fromisoformat(appt_date_str)
    return redirect(url_for("appointments.view_calendar", year=d.year, month=d.month))


@bp.route("/")
@login_required
def index():
    today = date.today()
    return redirect(url_for("appointments.view_calendar", year=today.year, month=today.month))


@bp.route("/<int:year>/<int:month>")
@login_required
def view_calendar(year, month):
    if month < 1 or month > 12:
        abort(404)

    appts = db.list_appointments_for_month(year, month)
    appts_by_day = {}
    for a in appts:
        appts_by_day.setdefault(a["appt_date"], []).append(a)

    first_weekday, days_in_month = calendar_module.monthrange(year, month)
    weeks = []
    week = [None] * first_weekday
    for day in range(1, days_in_month + 1):
        week.append(day)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        weeks.append(week + [None] * (7 - len(week)))

    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    return render_template(
        "appointment_calendar.html",
        year=year,
        month=month,
        month_name=calendar_module.month_name[month],
        weeks=weeks,
        appts_by_day=appts_by_day,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        today=today_iso(),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        clear_followup = request.form.get("clear_followup", "")
        patient_locked = request.form.get("patient_locked") == "1"
        data = _collect_appointment_form(request.form)
        errors = _validate_appointment(data)

        if not errors:
            case_id = int(clear_followup) if clear_followup.isdigit() else None
            db.add_appointment(
                data["patient_id"], case_id, data["doctor_id"], data["appt_date"],
                data["start_time"], data["end_time"], data["title"], data["notes"], data["status"],
            )
            if case_id:
                db.update_case_followup(case_id, "", "")
            if data["status"] == "No-show":
                _handle_noshow_followup(data["patient_id"], data["appt_date"])
            flash("Appointment booked.", "success")
            return _redirect_to_calendar_for(data["appt_date"])

        patient = db.get_patient(data["patient_id"]) if data["patient_id"] else None
        form_state = {
            **data,
            "id": None,
            "arrived_at": "",
            "seen_at": "",
            "patient_name": patient["name"] if patient else "",
            "doctor_name": "",
        }
        return render_template(
            "appointment_form.html",
            appt=form_state,
            doctors=db.list_doctors(),
            statuses=APPOINTMENT_STATUSES,
            prefill_date=data["appt_date"],
            prefill_patient=patient if patient_locked else None,
            patients=[] if patient_locked else db.list_patients(),
            errors=errors,
            clear_followup=clear_followup,
            editing=False,
        )

    patient_id_arg = request.args.get("patient_id", "").strip()
    clear_followup = request.args.get("clear_followup", "")
    if clear_followup.isdigit() and not patient_id_arg:
        case = db.get_case(int(clear_followup))
        if case:
            patient_id_arg = str(case["patient_id"])

    prefill_patient = db.get_patient(int(patient_id_arg)) if patient_id_arg.isdigit() else None
    prefill_date = normalize_date(request.args.get("date", "")) or today_iso()

    form_state = {
        "id": None,
        "patient_id": prefill_patient["id"] if prefill_patient else None,
        "doctor_id": None,
        "appt_date": prefill_date,
        "start_time": "",
        "end_time": "",
        "title": "",
        "notes": "",
        "status": "Scheduled",
        "arrived_at": "",
        "seen_at": "",
        "patient_name": prefill_patient["name"] if prefill_patient else "",
        "doctor_name": "",
    }

    return render_template(
        "appointment_form.html",
        appt=form_state,
        doctors=db.list_doctors(),
        statuses=APPOINTMENT_STATUSES,
        prefill_date=prefill_date,
        prefill_patient=prefill_patient,
        patients=[] if prefill_patient else db.list_patients(),
        errors=[],
        clear_followup=clear_followup,
        editing=False,
    )


@bp.route("/<int:appt_id>/edit", methods=["GET", "POST"])
@login_required
def edit(appt_id):
    appt = _get_appointment_or_404(appt_id)
    patient = db.get_patient(appt["patient_id"])
    doctor = db.get_doctor(appt["doctor_id"]) if appt.get("doctor_id") else None

    form_state = {
        **appt,
        "patient_name": patient["name"] if patient else "",
        "doctor_name": doctor["name"] if doctor else "",
    }
    errors = []

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        data = _collect_appointment_form(request.form)
        data["patient_id"] = appt["patient_id"]  # patient is fixed once an appointment exists
        errors = _validate_appointment(data)
        if not errors:
            prev_status = appt["status"]
            db.update_appointment(
                appt_id, data["patient_id"], appt["case_id"], data["doctor_id"], data["appt_date"],
                data["start_time"], data["end_time"], data["title"], data["notes"], data["status"],
            )
            if data["status"] == "No-show" and prev_status != "No-show":
                _handle_noshow_followup(data["patient_id"], data["appt_date"])
            flash("Appointment updated.", "success")
            return _redirect_to_calendar_for(data["appt_date"])
        form_state = {
            **form_state,
            **data,
            "patient_name": patient["name"] if patient else "",
            "doctor_name": doctor["name"] if doctor else "",
        }

    return render_template(
        "appointment_form.html",
        appt=form_state,
        doctors=db.list_doctors(),
        statuses=APPOINTMENT_STATUSES,
        prefill_date=form_state["appt_date"],
        prefill_patient=patient,
        patients=[],
        errors=errors,
        clear_followup="",
        editing=True,
    )


@bp.route("/<int:appt_id>/delete", methods=["POST"])
@login_required
def delete(appt_id):
    validate_csrf(request.form.get("csrf_token"))
    appt = _get_appointment_or_404(appt_id)
    response = _redirect_to_calendar_for(appt["appt_date"])
    db.delete_appointment(appt_id)
    flash("Appointment deleted.", "success")
    return response
