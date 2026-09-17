import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
from app.auth import current_actor, login_required
from app.constants import ALLERGY_DRUGS, MEDICAL_CONDITIONS, SEX_OPTIONS
from app.csrf import validate_csrf
from app.validators import compute_age, is_valid_mobile, normalize_date, now_iso, today_iso

bp = Blueprint("patients", __name__, url_prefix="/patients")


def _collect_form(form):
    dob = normalize_date(form.get("date_of_birth", ""))
    age_computed = compute_age(dob) if dob else None
    manual_age_raw = form.get("age", "").strip()
    manual_age = int(manual_age_raw) if manual_age_raw.isdigit() else None

    return {
        "name": form.get("name", "").strip(),
        "date_of_birth": dob,
        "age": age_computed if age_computed is not None else manual_age,
        "sex": form.get("sex", ""),
        "mobile": form.get("mobile", "").strip(),
        "email": form.get("email", "").strip(),
        "address": form.get("address", "").strip(),
        "medical_conditions": form.getlist("medical_conditions"),
        "medical_conditions_json": json.dumps(form.getlist("medical_conditions")),
        "medical_conditions_other": form.get("medical_conditions_other", "").strip(),
        "is_pregnant": form.get("is_pregnant") == "on",
        "is_nursing": form.get("is_nursing") == "on",
        "allergies": form.getlist("allergies"),
        "allergies_json": json.dumps(form.getlist("allergies")),
        "allergies_other": form.get("allergies_other", "").strip(),
        "emergency_contact_name": form.get("emergency_contact_name", "").strip(),
        "emergency_contact_relation": form.get("emergency_contact_relation", "").strip(),
        "emergency_contact_number": form.get("emergency_contact_number", "").strip(),
        "dpdp_notice_accepted": form.get("dpdp_notice_accepted") == "on",
        "comms_consent": form.get("comms_consent") == "on",
        "guardian_name": form.get("guardian_name", "").strip(),
        "guardian_relation": form.get("guardian_relation", "").strip(),
        "guardian_mobile": form.get("guardian_mobile", "").strip(),
    }


def _validate_patient(data):
    errors = []
    if not data["name"]:
        errors.append("Name is required.")
    if data["sex"] not in SEX_OPTIONS:
        errors.append("Sex must be Male or Female.")
    if not data["dpdp_notice_accepted"]:
        errors.append("The Data Processing Notice must be accepted to register a patient.")
    if data["mobile"] and not is_valid_mobile(data["mobile"]):
        errors.append("Mobile number looks invalid — enter a 10-digit Indian mobile number.")

    is_minor = data["age"] is not None and data["age"] < 18
    if is_minor:
        if not data["guardian_name"]:
            errors.append("Guardian name is required for patients under 18.")
        if not data["guardian_mobile"] or not is_valid_mobile(data["guardian_mobile"]):
            errors.append("A valid guardian mobile number is required for patients under 18.")
    return errors


@bp.route("/")
@login_required
def list_view():
    search = request.args.get("q", "").strip()
    patients = db.list_patients(search=search)
    return render_template("patients_list.html", patients=patients, search=search)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    errors = []
    form_state = {"medical_conditions": [], "allergies": []}

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        data = _collect_form(request.form)
        form_state = data
        errors = _validate_patient(data)
        if not errors:
            now = now_iso()
            if data["dpdp_notice_accepted"]:
                data["dpdp_notice_accepted_at"] = now
            if data["comms_consent"]:
                data["comms_consent_at"] = now
            patient_id = db.add_patient(data)
            flash("Patient registered.", "success")
            return redirect(url_for("patients.detail", patient_id=patient_id))

    return render_template(
        "patient_form.html",
        patient=form_state,
        errors=errors,
        sex_options=SEX_OPTIONS,
        medical_conditions=MEDICAL_CONDITIONS,
        allergy_drugs=ALLERGY_DRUGS,
        today=today_iso(),
        editing=False,
    )


@bp.route("/<int:patient_id>")
@login_required
def detail(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    patient["medical_conditions"] = json.loads(patient.get("medical_conditions_json") or "[]")
    patient["allergies"] = json.loads(patient.get("allergies_json") or "[]")
    cases = db.list_cases_for_patient(patient_id)
    appointments = db.list_appointments_for_patient(patient_id)
    data_requests = db.list_data_requests_for_patient(patient_id)
    prescriptions = db.list_prescriptions_for_patient(patient_id)
    return render_template(
        "patient_detail.html", patient=patient, cases=cases, appointments=appointments,
        data_requests=data_requests, prescriptions=prescriptions,
    )


@bp.route("/<int:patient_id>/edit", methods=["GET", "POST"])
@login_required
def edit(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)

    errors = []
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        data = _collect_form(request.form)
        errors = _validate_patient(data)
        if not errors:
            now = now_iso()
            if data["dpdp_notice_accepted"] and not patient.get("dpdp_notice_accepted"):
                data["dpdp_notice_accepted_at"] = now
            if data["comms_consent"] and not patient.get("comms_consent"):
                data["comms_consent_at"] = now
            db.update_patient(patient_id, data, actor=current_actor())
            flash("Patient updated.", "success")
            return redirect(url_for("patients.detail", patient_id=patient_id))
        patient = {**patient, **data}

    patient["medical_conditions"] = json.loads(patient.get("medical_conditions_json") or "[]") \
        if "medical_conditions" not in patient else patient["medical_conditions"]
    patient["allergies"] = json.loads(patient.get("allergies_json") or "[]") \
        if "allergies" not in patient else patient["allergies"]

    return render_template(
        "patient_form.html",
        patient=patient,
        errors=errors,
        sex_options=SEX_OPTIONS,
        medical_conditions=MEDICAL_CONDITIONS,
        allergy_drugs=ALLERGY_DRUGS,
        today=today_iso(),
        editing=True,
    )
