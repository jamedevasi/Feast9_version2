"""Appointments — confirmed calendar bookings, distinct from a case's Follow-up reminder."""
import calendar as calendar_module
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
from app.auth import login_required
from app.constants import APPOINTMENT_STATUSES, RECURRENCE_INTERVALS
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


def _validate_appointment(data, current_doctor_id=None):
    """current_doctor_id: the doctor an edited appointment already has — still allowed if
    since deactivated (a new booking can only get an active doctor)."""
    errors = []
    if not data["patient_id"] or not db.get_patient(data["patient_id"]):
        errors.append("A valid patient must be selected.")
    doctor_error = db.doctor_choice_error(data["doctor_id"], current_doctor_id)
    if doctor_error:
        errors.append(doctor_error)
    if not data["appt_date"]:
        errors.append("A valid appointment date is required.")
    if not data["start_time"]:
        errors.append("Start time is required.")
    return errors


def _collect_recurrence_form(form):
    return {
        "is_recurring": form.get("is_recurring") == "on",
        "recur_interval": form.get("recur_interval", ""),
        "recur_until": normalize_date(form.get("recur_until", "")),
        "skip_sundays": form.get("skip_sundays") == "on",
    }


def _validate_recurrence(recurrence, appt_date):
    errors = []
    if not recurrence["is_recurring"]:
        return errors
    if recurrence["recur_interval"] not in RECURRENCE_INTERVALS:
        errors.append("Select a valid recurrence interval.")
    if not recurrence["recur_until"]:
        errors.append("An end date is required for a recurring appointment.")
    elif appt_date and recurrence["recur_until"] <= appt_date:
        errors.append("The recurrence end date must be after the first appointment's date.")
    return errors


def _handle_noshow_followup(patient_id, appt_date, appt_id):
    """Set a follow-up reminder for the next day on the patient's most recent case — an active
    one if there is one, otherwise their latest closed case, so a no-show is never silently
    dropped. The reminder is tagged with the appointment (appt_id): it shows on the dashboard
    from the next day, and is withdrawn again if that appointment is cancelled or deleted."""
    next_day = (date.today() + timedelta(days=1)).isoformat()
    try:
        cases = sorted(db.list_cases_for_patient(patient_id), key=lambda c: c.get("updated_at", ""), reverse=True)
        target = next((c for c in cases if c.get("status") == "Active"), cases[0] if cases else None)
        if target:
            db.set_noshow_followup(
                target["id"], next_day,
                f"Patient did not attend appointment on {appt_date} — please reschedule", appt_id,
            )
            flash(f"Follow-up reminder set for {next_day}.", "warning")
        else:
            flash("This patient has no case yet, so no follow-up reminder could be created for the no-show.", "warning")
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
        # Legend: active doctors, plus any deactivated doctor with an appointment this month
        # (their dots are still on the calendar and need explaining).
        doctors=db.list_doctors_for_choice({a["doctor_id"] for a in appts}),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        clear_followup = request.form.get("clear_followup", "")
        patient_locked = request.form.get("patient_locked") == "1"
        data = _collect_appointment_form(request.form)
        recurrence = _collect_recurrence_form(request.form)
        errors = _validate_appointment(data) + _validate_recurrence(recurrence, data["appt_date"])

        if not errors:
            case_id = int(clear_followup) if clear_followup.isdigit() else None
            if recurrence["is_recurring"]:
                created_ids, conflicts, notices = db.add_recurring_appointments(
                    data["patient_id"], case_id, data["doctor_id"], data["appt_date"],
                    data["start_time"], data["end_time"], data["title"], data["notes"], data["status"],
                    recurrence["recur_interval"], recurrence["recur_until"], recurrence["skip_sundays"],
                )
                flash(f"{len(created_ids)} recurring appointments booked.", "success")
                for notice in notices:
                    flash(f"{notice}.", "warning")
                for warning in conflicts:
                    flash(f"Possible conflict: {warning}.", "warning")
                first_appt_id = created_ids[0]
            else:
                first_appt_id = db.add_appointment(
                    data["patient_id"], case_id, data["doctor_id"], data["appt_date"],
                    data["start_time"], data["end_time"], data["title"], data["notes"], data["status"],
                )
                flash("Appointment booked.", "success")
            if case_id:
                db.update_case_followup(case_id, "", "")
            if data["status"] in ("Scheduled", "Completed"):
                # Rebooking a patient who missed an earlier appointment is what their no-show
                # follow-up was asking for — it's done now.
                db.resolve_noshow_followups_for_patient(data["patient_id"], data["appt_date"])
            if data["status"] == "No-show":
                _handle_noshow_followup(data["patient_id"], data["appt_date"], first_appt_id)
            return _redirect_to_calendar_for(data["appt_date"])

        patient = db.get_patient(data["patient_id"]) if data["patient_id"] else None
        form_state = {
            **data,
            **recurrence,
            "id": None,
            "arrived_at": "",
            "seen_at": "",
            "series_id": None,
            "patient_name": patient["name"] if patient else "",
            "doctor_name": "",
        }
        return render_template(
            "appointment_form.html",
            appt=form_state,
            doctors=db.list_doctors(),
            statuses=APPOINTMENT_STATUSES,
            recurrence_intervals=RECURRENCE_INTERVALS,
            prefill_date=data["appt_date"],
            prefill_patient=patient if patient_locked else None,
            patients=[] if patient_locked else db.list_patients(),
            errors=errors,
            clear_followup=clear_followup,
            editing=False,
        )

    patient_id_arg = request.args.get("patient_id", "").strip()
    clear_followup = request.args.get("clear_followup", "")
    prefill_title = ""
    if clear_followup.isdigit():
        case = db.get_case(int(clear_followup))
        if case:
            if not patient_id_arg:
                patient_id_arg = str(case["patient_id"])
            # Booking from a follow-up: carry its Next Action Note over as the appointment
            # title — still just a prefill, editable before saving.
            prefill_title = case["next_action_note"] or ""

    prefill_patient = db.get_patient(int(patient_id_arg)) if patient_id_arg.isdigit() else None
    prefill_date = normalize_date(request.args.get("date", "")) or today_iso()

    form_state = {
        "id": None,
        "patient_id": prefill_patient["id"] if prefill_patient else None,
        "doctor_id": None,
        "appt_date": prefill_date,
        "start_time": "",
        "end_time": "",
        "title": prefill_title,
        "notes": "",
        "status": "Scheduled",
        "arrived_at": "",
        "seen_at": "",
        "series_id": None,
        "is_recurring": False,
        "recur_interval": "",
        "recur_until": "",
        "skip_sundays": True,
        "patient_name": prefill_patient["name"] if prefill_patient else "",
        "doctor_name": "",
    }

    return render_template(
        "appointment_form.html",
        appt=form_state,
        doctors=db.list_doctors(),
        statuses=APPOINTMENT_STATUSES,
        recurrence_intervals=RECURRENCE_INTERVALS,
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
        scope = request.form.get("scope", "this")
        data = _collect_appointment_form(request.form)
        data["patient_id"] = appt["patient_id"]  # patient is fixed once an appointment exists
        errors = _validate_appointment(data, appt.get("doctor_id"))
        if not errors:
            if scope == "series" and appt["series_id"]:
                # Shared fields only — each occurrence keeps its own date and status.
                db.update_appointment_series(
                    appt["series_id"], data["doctor_id"], data["start_time"], data["end_time"],
                    data["title"], data["notes"],
                )
                flash("Updated this and every other not-yet-completed occurrence in the series.", "success")
                return _redirect_to_calendar_for(appt["appt_date"])

            prev_status = appt["status"]
            db.update_appointment(
                appt_id, data["patient_id"], appt["case_id"], data["doctor_id"], data["appt_date"],
                data["start_time"], data["end_time"], data["title"], data["notes"], data["status"],
            )
            if data["status"] == "No-show" and prev_status != "No-show":
                _handle_noshow_followup(data["patient_id"], data["appt_date"], appt_id)
            elif prev_status == "No-show" and data["status"] != "No-show":
                # Cancelled, attended or rescheduled after all — the no-show reminder no longer applies.
                db.clear_noshow_followup_for_appointment(appt_id)
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
        # Keeps a since-deactivated doctor selectable on their own appointment, so marking an
        # old visit Completed/No-show doesn't force it onto someone else.
        doctors=db.list_doctors_for_choice([appt.get("doctor_id")]),
        statuses=APPOINTMENT_STATUSES,
        prefill_date=form_state["appt_date"],
        prefill_patient=patient,
        patients=[],
        errors=errors,
        clear_followup="",
        editing=True,
        linked_case=db.get_case(appt["case_id"]) if appt.get("case_id") else None,
        # Offered for linking when the appointment was booked for the patient, not a case.
        patient_cases=[] if appt.get("case_id") else db.list_cases_for_patient(appt["patient_id"]),
    )


@bp.route("/<int:appt_id>/link-case", methods=["POST"])
@login_required
def link_case(appt_id):
    """Ties an appointment that was booked for a patient to one of that patient's cases."""
    validate_csrf(request.form.get("csrf_token"))
    appt = _get_appointment_or_404(appt_id)
    case_id = request.form.get("case_id", "")
    case = db.get_case(int(case_id)) if case_id.isdigit() else None
    if not case or case["patient_id"] != appt["patient_id"]:
        flash("Choose one of this patient's cases.", "warning")
    else:
        db.set_appointment_case(appt_id, case["id"])
        flash(f"Appointment linked to the case '{case['title']}'.", "success")
    return redirect(url_for("appointments.edit", appt_id=appt_id))


@bp.route("/<int:appt_id>/delete", methods=["POST"])
@login_required
def delete(appt_id):
    validate_csrf(request.form.get("csrf_token"))
    appt = _get_appointment_or_404(appt_id)
    response = _redirect_to_calendar_for(appt["appt_date"])
    db.delete_appointment(appt_id)
    flash("Appointment deleted.", "success")
    return response


@bp.route("/<int:appt_id>/cancel-series", methods=["POST"])
@login_required
def cancel_series(appt_id):
    validate_csrf(request.form.get("csrf_token"))
    appt = _get_appointment_or_404(appt_id)
    response = _redirect_to_calendar_for(appt["appt_date"])
    if appt["series_id"]:
        db.cancel_appointment_series(appt["series_id"])
        flash("Cancelled every not-yet-completed occurrence in this series.", "success")
    return response
