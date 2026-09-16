"""Idempotent demo data seeding. Cases, etc. will be added here once those features
exist (see feast9_v2_agents.md §13)."""
from datetime import date, timedelta

from app import db
from app.validators import now_iso

DEMO_DOCTORS = [
    {"name": "Dr. Anjali Rao", "color": "#2f9e44"},
    {"name": "Dr. Vivek Menon", "color": "#1c7ed6"},
]

DEMO_PROCEDURE_TYPES = [
    "Consultation",
    "Scaling",
    "Filling",
    "Root Canal Treatment",
    "Crown",
    "Extraction",
]

DEMO_PATIENTS = [
    {
        "name": "Ananya Sharma",
        "date_of_birth": "1990-04-12",
        "sex": "Female",
        "mobile": "9876543210",
        "email": "ananya.sharma@example.com",
        "address": "12 MG Road, Bengaluru",
        "medical_conditions_json": '["Hypertension"]',
        "allergies_json": '["Penicillin"]',
        "dpdp_notice_accepted": True,
        "dpdp_notice_accepted_at": now_iso(),
        "comms_consent": True,
        "comms_consent_at": now_iso(),
        "emergency_contact_name": "Rohit Sharma",
        "emergency_contact_relation": "Spouse",
        "emergency_contact_number": "9876500000",
    },
    {
        "name": "Kabir Mehta",
        "date_of_birth": "2012-08-01",
        "sex": "Male",
        "dpdp_notice_accepted": True,
        "dpdp_notice_accepted_at": now_iso(),
        "address": "45 Park Street, Kolkata",
        "guardian_name": "Nisha Mehta",
        "guardian_relation": "Mother",
        "guardian_mobile": "9812345678",
    },
    {
        "name": "Rakesh Iyer",
        "date_of_birth": "1975-11-23",
        "sex": "Male",
        "mobile": "9900112233",
        "email": "rakesh.iyer@example.com",
        "address": "8 Anna Salai, Chennai",
        "medical_conditions_json": '["Diabetes", "Cardiac Condition"]',
        "dpdp_notice_accepted": True,
        "dpdp_notice_accepted_at": now_iso(),
        "comms_consent": False,
    },
]


DEMO_APPOINTMENTS = [
    {"patient": "Ananya Sharma", "doctor": "Dr. Anjali Rao", "days_ahead": 1,
     "start_time": "10:00", "title": "Scaling follow-up"},
    {"patient": "Kabir Mehta", "doctor": "Dr. Vivek Menon", "days_ahead": 3,
     "start_time": "11:30", "title": "Filling review"},
    {"patient": "Rakesh Iyer", "doctor": "Dr. Anjali Rao", "days_ahead": 5,
     "start_time": "16:00", "title": "Consultation"},
]


def _seed_appointments():
    patients = {p["name"]: p for p in db.list_patients()}
    doctors = {d["name"]: d for d in db.list_doctors(active_only=False)}
    existing = {
        (a["patient_id"], a["appt_date"], a["start_time"])
        for p in patients.values()
        for a in db.list_appointments_for_patient(p["id"])
    }
    created = 0
    for appt in DEMO_APPOINTMENTS:
        patient = patients.get(appt["patient"])
        doctor = doctors.get(appt["doctor"])
        if not patient or not doctor:
            continue
        appt_date = (date.today() + timedelta(days=appt["days_ahead"])).isoformat()
        if (patient["id"], appt_date, appt["start_time"]) in existing:
            continue
        db.add_appointment(
            patient["id"], None, doctor["id"], appt_date, appt["start_time"],
            "", appt["title"], "", "Scheduled",
        )
        created += 1
    return created


def run():
    db.init_db()

    existing_doctors = {d["name"] for d in db.list_doctors(active_only=False)}
    doctors_created = 0
    for doc in DEMO_DOCTORS:
        if doc["name"] in existing_doctors:
            continue
        db.add_doctor(doc["name"], doc["color"])
        doctors_created += 1

    existing_procs = {p["name"] for p in db.list_procedure_types(active_only=False)}
    procs_created = 0
    for name in DEMO_PROCEDURE_TYPES:
        if name in existing_procs:
            continue
        db.add_procedure_type(name)
        procs_created += 1

    existing_patients = {p["name"] for p in db.list_patients()}
    patients_created = 0
    for data in DEMO_PATIENTS:
        if data["name"] in existing_patients:
            continue
        db.add_patient(data)
        patients_created += 1

    appts_created = _seed_appointments()

    print(f"Seeded {doctors_created} new doctor(s), {procs_created} new procedure type(s), "
          f"{patients_created} new patient(s), {appts_created} new appointment(s).")


if __name__ == "__main__":
    run()
