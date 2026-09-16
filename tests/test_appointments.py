from datetime import date, timedelta

from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case, _seed_doctor


def _case_for(client, patient_id, **overrides):
    resp, _doctor_id = _create_case(client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url


def _book_appointment(client, patient_id, doctor_id=None, **overrides):
    if doctor_id is None:
        doctor_id = _seed_doctor()
    url = f"/appointments/new?patient_id={patient_id}"
    token = get_csrf(client, url)
    data = {
        "doctor_id": str(doctor_id),
        "appt_date": "2026-10-01",
        "start_time": "10:00",
        "end_time": "10:30",
        "title": "Scaling",
        "notes": "",
        "status": "Scheduled",
        "clear_followup": "",
        "patient_locked": "1",
        "patient_id": str(patient_id),
        "csrf_token": token,
    }
    data.update(overrides)
    return client.post("/appointments/new", data=data), doctor_id


def test_book_appointment_and_redirect_to_calendar(logged_in_client, patient_id):
    resp, _ = _book_appointment(logged_in_client, patient_id)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/appointments/2026/10")

    appts = db.list_appointments_for_patient(patient_id)
    assert len(appts) == 1
    assert appts[0]["status"] == "Scheduled"
    assert appts[0]["title"] == "Scaling"


def test_appointment_requires_doctor_and_date(logged_in_client, patient_id):
    resp, _ = _book_appointment(logged_in_client, patient_id, doctor_id="", appt_date="")
    assert resp.status_code == 200
    assert b"doctor must be selected" in resp.data
    assert b"valid appointment date is required" in resp.data
    assert db.list_appointments_for_patient(patient_id) == []


def test_appointment_appears_on_patient_page(logged_in_client, patient_id):
    _book_appointment(logged_in_client, patient_id)
    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert b"Scaling" in resp.data
    assert b"Scheduled" in resp.data


def test_delete_appointment_redirects_to_appointments_month_year(logged_in_client, patient_id):
    _book_appointment(logged_in_client, patient_id)
    appt_id = db.list_appointments_for_patient(patient_id)[0]["id"]

    edit_url = f"/appointments/{appt_id}/edit"
    token = get_csrf(logged_in_client, edit_url)
    resp = logged_in_client.post(f"/appointments/{appt_id}/delete", data={"csrf_token": token})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/appointments/2026/10")
    assert db.get_appointment(appt_id) is None


def test_noshow_via_edit_sets_followup_next_day(logged_in_client, patient_id):
    case_id, _case_url = _case_for(logged_in_client, patient_id)
    _book_appointment(logged_in_client, patient_id)
    appt_id = db.list_appointments_for_patient(patient_id)[0]["id"]

    edit_url = f"/appointments/{appt_id}/edit"
    token = get_csrf(logged_in_client, edit_url)
    resp = logged_in_client.post(
        edit_url,
        data={
            "doctor_id": str(db.get_appointment(appt_id)["doctor_id"]),
            "appt_date": "2026-10-01",
            "start_time": "10:00",
            "end_time": "10:30",
            "title": "Scaling",
            "notes": "",
            "status": "No-show",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 302

    case = db.get_case(case_id)
    next_day = (date.today() + timedelta(days=1)).isoformat()
    assert case["follow_up_date"] == next_day
    assert "did not attend appointment" in case["next_action_note"]


def test_clear_followup_flow_clears_case_followup_after_booking(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/followup",
        data={"follow_up_date": "2026-09-20", "next_action_note": "Call patient", "csrf_token": token},
    )
    assert db.get_case(case_id)["follow_up_date"] == "2026-09-20"

    new_url = f"/appointments/new?clear_followup={case_id}"
    token = get_csrf(logged_in_client, new_url)
    resp = logged_in_client.post(
        "/appointments/new",
        data={
            "doctor_id": str(_seed_doctor()),
            "appt_date": "2026-09-25",
            "start_time": "09:00",
            "end_time": "",
            "title": "Booked from follow-up",
            "notes": "",
            "status": "Scheduled",
            "clear_followup": str(case_id),
            "patient_locked": "1",
            "patient_id": str(patient_id),
            "csrf_token": token,
        },
    )
    assert resp.status_code == 302

    case = db.get_case(case_id)
    assert case["follow_up_date"] == ""
    assert case["next_action_note"] == ""


def test_new_appointment_form_prefills_patient_from_clear_followup(logged_in_client, patient_id):
    case_id, _case_url = _case_for(logged_in_client, patient_id)
    resp = logged_in_client.get(f"/appointments/new?clear_followup={case_id}")
    assert resp.status_code == 200
    assert f'value="{patient_id}"'.encode() in resp.data


def test_calendar_shows_booked_appointment(logged_in_client, patient_id):
    _book_appointment(logged_in_client, patient_id)
    resp = logged_in_client.get("/appointments/2026/10")
    assert resp.status_code == 200
    assert b"Case Test Patient" in resp.data
