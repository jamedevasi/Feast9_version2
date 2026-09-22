"""Idempotent demo data seeding: doctors, case types, patients, cases (with visit notes,
payments, consents, follow-ups and lab requisitions) and appointments. Safe to re-run —
anything already present is skipped, never modified (see feast9_v2_agents.md §13)."""
import json
from datetime import date, datetime, timedelta

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


def _adult(name, dob, sex, mobile, address, conditions="[]", allergies="[]"):
    return {
        "name": name, "date_of_birth": dob, "sex": sex, "mobile": mobile,
        "email": name.lower().replace(" ", ".") + "@example.com", "address": address,
        "medical_conditions_json": conditions, "allergies_json": allergies,
        "dpdp_notice_accepted": True, "dpdp_notice_accepted_at": now_iso(),
        "comms_consent": True, "comms_consent_at": now_iso(),
    }


DEMO_PATIENTS_EXTRA = [
    _adult("Priya Nair", "1988-02-14", "Female", "9845012345", "22 Marine Drive, Kochi"),
    _adult("Arjun Reddy", "1995-07-30", "Male", "9700123456", "5 Jubilee Hills, Hyderabad"),
    _adult("Meera Kulkarni", "1982-11-05", "Female", "9822334455", "31 FC Road, Pune",
           allergies='["Penicillin"]'),
    _adult("Sanjay Gupta", "1968-03-19", "Male", "9811223344", "14 Connaught Place, Delhi",
           conditions='["Hypertension", "Diabetes"]'),
    _adult("Fatima Sheikh", "1999-09-09", "Female", "9930112233", "9 Colaba Causeway, Mumbai"),
    _adult("Vikram Singh", "1979-12-01", "Male", "9876123450", "60 Sector 17, Chandigarh"),
    _adult("Lakshmi Venkatesh", "1955-06-25", "Female", "9444123456", "18 T Nagar, Chennai",
           conditions='["Diabetes", "Hypertension"]'),
    {
        "name": "Rohan Desai", "date_of_birth": "2014-05-17", "sex": "Male",
        "address": "3 Satellite Road, Ahmedabad",
        "dpdp_notice_accepted": True, "dpdp_notice_accepted_at": now_iso(),
        "guardian_name": "Sunita Desai", "guardian_relation": "Mother", "guardian_mobile": "9867001122",
    },
    _adult("Deepa Menon", "1992-01-28", "Female", "9895011223", "7 Race Course Road, Coimbatore"),
    _adult("Imran Qureshi", "1986-08-14", "Male", "9848099887", "40 Banjara Hills, Hyderabad"),
]


DEMO_APPOINTMENTS = [
    # days_ahead is relative to today (negative = past); status defaults to Scheduled.
    {"patient": "Ananya Sharma", "doctor": "Dr. Anjali Rao", "days_ahead": 1,
     "start_time": "10:00", "title": "Scaling follow-up"},
    {"patient": "Kabir Mehta", "doctor": "Dr. Vivek Menon", "days_ahead": 3,
     "start_time": "11:30", "title": "Filling review"},
    {"patient": "Rakesh Iyer", "doctor": "Dr. Anjali Rao", "days_ahead": 5,
     "start_time": "16:00", "title": "Consultation"},
    # past
    {"patient": "Priya Nair", "doctor": "Dr. Vivek Menon", "days_ahead": -14, "start_time": "10:00",
     "title": "Whitening consultation", "status": "Completed"},
    {"patient": "Arjun Reddy", "doctor": "Dr. Anjali Rao", "days_ahead": -10, "start_time": "11:00",
     "title": "Scaling & polishing", "status": "Completed"},
    {"patient": "Meera Kulkarni", "doctor": "Dr. Vivek Menon", "days_ahead": -8, "start_time": "15:00",
     "title": "Root canal — session 2", "status": "Completed"},
    {"patient": "Sanjay Gupta", "doctor": "Dr. Anjali Rao", "days_ahead": -6, "start_time": "09:30",
     "title": "Extraction", "status": "Completed"},
    {"patient": "Vikram Singh", "doctor": "Dr. Anjali Rao", "days_ahead": -5, "start_time": "12:00",
     "title": "Crown preparation", "status": "Completed"},
    {"patient": "Fatima Sheikh", "doctor": "Dr. Vivek Menon", "days_ahead": -3, "start_time": "14:00",
     "title": "Sensitivity review", "status": "No-show"},
    {"patient": "Imran Qureshi", "doctor": "Dr. Anjali Rao", "days_ahead": -2, "start_time": "17:00",
     "title": "Bridge consultation", "status": "Cancelled"},
    {"patient": "Lakshmi Venkatesh", "doctor": "Dr. Vivek Menon", "days_ahead": -1, "start_time": "10:30",
     "title": "Denture fitting", "status": "Completed"},
    # today
    {"patient": "Rakesh Iyer", "doctor": "Dr. Anjali Rao", "days_ahead": 0, "start_time": "09:00",
     "title": "Crown try-in"},
    {"patient": "Deepa Menon", "doctor": "Dr. Vivek Menon", "days_ahead": 0, "start_time": "11:00",
     "title": "Suture removal check"},
    {"patient": "Rohan Desai", "doctor": "Dr. Anjali Rao", "days_ahead": 0, "start_time": "15:30",
     "title": "Cavity filling", "status": "Completed"},
    {"patient": "Kabir Mehta", "doctor": "Dr. Vivek Menon", "days_ahead": 0, "start_time": "16:30",
     "title": "Sealant check"},
    # upcoming
    {"patient": "Priya Nair", "doctor": "Dr. Vivek Menon", "days_ahead": 1, "start_time": "12:00",
     "title": "Post-extraction check"},
    {"patient": "Meera Kulkarni", "doctor": "Dr. Anjali Rao", "days_ahead": 2, "start_time": "11:00",
     "title": "Crown cementation"},
    {"patient": "Arjun Reddy", "doctor": "Dr. Vivek Menon", "days_ahead": 2, "start_time": "14:30",
     "title": "Second filling"},
    {"patient": "Sanjay Gupta", "doctor": "Dr. Anjali Rao", "days_ahead": 4, "start_time": "10:00",
     "title": "Treatment planning"},
    {"patient": "Vikram Singh", "doctor": "Dr. Vivek Menon", "days_ahead": 6, "start_time": "13:00",
     "title": "Crown fitting"},
    {"patient": "Fatima Sheikh", "doctor": "Dr. Anjali Rao", "days_ahead": 7, "start_time": "09:30",
     "title": "Filling review"},
    {"patient": "Lakshmi Venkatesh", "doctor": "Dr. Vivek Menon", "days_ahead": 9, "start_time": "16:00",
     "title": "Gum care"},
    {"patient": "Imran Qureshi", "doctor": "Dr. Anjali Rao", "days_ahead": 12, "start_time": "10:30",
     "title": "Bridge preparation"},
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
            "", appt["title"], "", appt.get("status", "Scheduled"),
        )
        created += 1
    return created


# (patient, title, procedures, doctor index, total cost, age in days, status, fraction paid,
#  follow-up as (days from today, next-action note) or None). Closed cases carry no follow-up —
#  the dashboard only surfaces Active ones.
DEMO_CASES = [
    ("Ananya Sharma", "Full-mouth scaling & polishing", ["Scaling"], 0, 3500, 75, "Closed", 1.0, None),
    ("Kabir Mehta", "Pediatric consultation & sealants", ["Consultation"], 1, 1500, 60, "Closed", 1.0, None),
    ("Priya Nair", "Whitening consultation", ["Consultation"], 1, 1000, 50, "Closed", 1.0, None),
    ("Arjun Reddy", "Scaling & polishing", ["Scaling"], 0, 2500, 45, "Closed", 1.0, None),
    ("Meera Kulkarni", "Root canal — upper front", ["Root Canal Treatment"], 1, 8500, 70, "Closed", 1.0, None),
    ("Sanjay Gupta", "Extraction — lower molar", ["Extraction"], 0, 3500, 35, "Closed", 1.0, None),
    ("Vikram Singh", "Root canal — upper premolar", ["Root Canal Treatment"], 0, 9000, 55, "Closed", 1.0, None),
    ("Lakshmi Venkatesh", "Denture consultation", ["Consultation"], 1, 1200, 28, "Closed", 1.0, None),
    ("Ananya Sharma", "Upper molar composite filling", ["Filling"], 0, 4500, 12, "Active", 0.5,
     (-4, "Call to schedule filling review")),
    ("Kabir Mehta", "Lower molar filling", ["Filling"], 1, 3000, 9, "Active", 0.4,
     (1, "Recall for filling check")),
    ("Rakesh Iyer", "Root canal — lower right molar", ["Root Canal Treatment"], 0, 9500, 30, "Active", 0.6,
     (-1, "Confirm crown fitting date")),
    ("Rakesh Iyer", "Crown after root canal", ["Crown"], 0, 14000, 5, "Active", 0.25,
     (3, "Crown try-in appointment")),
    ("Priya Nair", "Wisdom tooth extraction", ["Extraction"], 1, 6000, 7, "Active", 0.5,
     (2, "Post-extraction check")),
    ("Arjun Reddy", "Cavity fillings (two teeth)", ["Filling"], 0, 5000, 10, "Active", 0.4,
     (-6, "Remind about second filling")),
    ("Meera Kulkarni", "Ceramic crown", ["Crown"], 1, 15000, 15, "Active", 0.5,
     (0, "Crown cementation")),
    ("Sanjay Gupta", "Full-mouth evaluation", ["Consultation", "Scaling"], 0, 4000, 3, "Active", 0.0,
     (5, "Discuss treatment plan")),
    ("Fatima Sheikh", "Consultation — tooth sensitivity", ["Consultation"], 1, 800, 25, "Active", 1.0,
     (-3, "Ask about sensitivity after treatment")),
    ("Fatima Sheikh", "Filling — premolar", ["Filling"], 1, 2800, 6, "Active", 0.5,
     (7, "Review after filling")),
    ("Vikram Singh", "Crown — upper premolar", ["Crown"], 0, 13500, 18, "Active", 0.7,
     (-9, "Follow up on pending payment")),
    ("Lakshmi Venkatesh", "Scaling — gum care", ["Scaling"], 1, 3000, 8, "Active", 0.33,
     (10, "Gum health review")),
    ("Rohan Desai", "Pediatric check-up", ["Consultation"], 0, 900, 22, "Active", 1.0,
     (0, "Six-monthly recall")),
    ("Rohan Desai", "Cavity filling", ["Filling"], 0, 2600, 4, "Active", 0.5,
     (14, "Recall in two weeks")),
    ("Deepa Menon", "Scaling & polishing", ["Scaling"], 1, 2800, 32, "Active", 1.0,
     (30, "Six-month scaling recall")),
    ("Deepa Menon", "Wisdom tooth removal", ["Extraction"], 1, 7000, 2, "Active", 0.3,
     (2, "Suture removal check")),
    ("Imran Qureshi", "Bridge consultation", ["Consultation"], 0, 1000, 14, "Active", 1.0,
     (45, "Discuss bridge options")),
    ("Imran Qureshi", "Bridge — lower left", ["Crown"], 0, 22000, 1, "Active", 0.2,
     (21, "Impression follow-up")),
]

# Open lab requisitions on a few crown cases — those whose patient has a visit inside the next
# 3 days appear in the dashboard's "Lab Requisitions Due Before Visit" section.
DEMO_LAB_REQS = {
    "Crown after root canal": ("Precision Dental Lab", "PFM crown — lower right molar"),
    "Ceramic crown": ("Precision Dental Lab", "Zirconia crown — upper right first molar"),
    "Crown — upper premolar": ("SmileWorks Lab", "Ceramic crown — upper premolar"),
}

_PAYMENT_METHODS = ["Cash", "UPI", "Card"]


def _days_ago_iso(days, with_time=True):
    moment = datetime.now() - timedelta(days=days)
    return moment.strftime("%Y-%m-%d %H:%M:%S") if with_time else moment.date().isoformat()


def _seed_cases():
    """Idempotent: a case already present for (patient, title) is left exactly as it is — its
    notes/payments/follow-up are only written for cases created by this run."""
    patients = {p["name"]: p for p in db.list_patients()}
    doctors = db.list_doctors(active_only=False)
    created = followups = 0
    for n, (pname, title, procs, doc_idx, cost, age, status, paid, followup) in enumerate(DEMO_CASES):
        patient = patients.get(pname)
        if not patient or not doctors:
            continue
        if any(c["title"] == title for c in db.list_cases_for_patient(patient["id"])):
            continue
        case_id = db.add_case({
            "patient_id": patient["id"], "title": title, "procedures_json": json.dumps(procs),
            "doctor_id": doctors[doc_idx % len(doctors)]["id"], "total_cost": cost,
            "created_at": _days_ago_iso(age),
        })
        created += 1

        db.add_visit_note(case_id, patient["id"],
                          f"Initial examination and treatment planning for {title.lower()}.",
                          _days_ago_iso(age, with_time=False))
        if age >= 10:
            db.add_visit_note(case_id, patient["id"],
                              "Treatment progressing as planned; patient tolerating well.",
                              _days_ago_iso(age // 2, with_time=False))
            db.record_case_consent(case_id, "Paper consent signed at first visit")

        amount_paid = round(cost * paid)
        if amount_paid:
            if age >= 8:
                first = round(amount_paid * 0.6)
                db.add_payment(case_id, patient["id"], _days_ago_iso(age, with_time=False), first,
                               _PAYMENT_METHODS[n % 3], "", "Advance")
                if amount_paid - first:
                    db.add_payment(case_id, patient["id"], _days_ago_iso(max(age - 7, 0), with_time=False),
                                   amount_paid - first, _PAYMENT_METHODS[(n + 1) % 3], "", "Balance payment")
            else:
                db.add_payment(case_id, patient["id"], _days_ago_iso(age, with_time=False), amount_paid,
                               _PAYMENT_METHODS[n % 3], "", "")

        if title in DEMO_LAB_REQS:
            lab, work = DEMO_LAB_REQS[title]
            db.add_lab_req(case_id, patient["id"], lab, work, _days_ago_iso(max(age - 1, 0), with_time=False),
                           (date.today() + timedelta(days=5)).isoformat(), "")

        if status == "Closed":
            db.close_case(case_id)
        if followup:
            offset, note = followup
            db.update_case_followup(case_id, (date.today() + timedelta(days=offset)).isoformat(), note)
            followups += 1
    return created, followups


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
    for data in DEMO_PATIENTS + DEMO_PATIENTS_EXTRA:
        if data["name"] in existing_patients:
            continue
        db.add_patient(data)
        patients_created += 1

    cases_created, followups_created = _seed_cases()
    appts_created = _seed_appointments()

    print(f"Seeded {doctors_created} new doctor(s), {procs_created} new procedure type(s), "
          f"{patients_created} new patient(s), {cases_created} new case(s) "
          f"({followups_created} with a follow-up), {appts_created} new appointment(s).")


if __name__ == "__main__":
    run()
