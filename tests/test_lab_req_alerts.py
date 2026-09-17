from datetime import date, timedelta

from app import db
from tests.conftest import get_csrf
from tests.test_appointments import _book_appointment
from tests.test_cases import _create_case

TODAY = date.today()


def _case_for(client, patient_id, **overrides):
    resp, doctor_id = _create_case(client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url, doctor_id


def _add_lab_req(client, case_id, case_url, **overrides):
    token = get_csrf(client, case_url)
    data = {
        "lab_name": "City Dental Lab",
        "work_description": "Crown fabrication",
        "sent_date": TODAY.isoformat(),
        "expected_return": "",
        "csrf_token": token,
    }
    data.update(overrides)
    client.post(f"/cases/{case_id}/lab-reqs", data=data)
    return db.list_lab_reqs_for_case(case_id)[0]["id"]


def test_no_highlight_without_upcoming_appointment(logged_in_client, patient_id):
    assert db.get_next_scheduled_appointment_within(patient_id) == ""
    assert db.get_open_lab_reqs_for_upcoming_appointments() == []


def test_open_lab_req_flagged_when_appointment_within_three_days(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    _add_lab_req(logged_in_client, case_id, case_url)
    appt_date = (TODAY + timedelta(days=2)).isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=appt_date)

    assert db.get_next_scheduled_appointment_within(patient_id) == appt_date

    due = db.get_open_lab_reqs_for_upcoming_appointments()
    assert len(due) == 1
    assert due[0]["case_id"] == case_id
    assert due[0]["next_appt_date"] == appt_date


def test_received_lab_req_not_flagged(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    req_id = _add_lab_req(logged_in_client, case_id, case_url)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/lab-reqs/{req_id}/update",
        data={"status": "Received", "received_date": TODAY.isoformat(), "notes": "", "csrf_token": token},
    )
    appt_date = (TODAY + timedelta(days=1)).isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=appt_date)

    assert db.get_open_lab_reqs_for_upcoming_appointments() == []


def test_appointment_beyond_three_days_not_flagged(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    _add_lab_req(logged_in_client, case_id, case_url)
    far_date = (TODAY + timedelta(days=10)).isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=far_date)

    assert db.get_next_scheduled_appointment_within(patient_id) == ""
    assert db.get_open_lab_reqs_for_upcoming_appointments() == []


def test_cancelled_appointment_not_flagged(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    _add_lab_req(logged_in_client, case_id, case_url)
    appt_date = (TODAY + timedelta(days=1)).isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=appt_date, status="Cancelled")

    assert db.get_next_scheduled_appointment_within(patient_id) == ""
    assert db.get_open_lab_reqs_for_upcoming_appointments() == []


def test_case_detail_shows_lab_req_alert(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    _add_lab_req(logged_in_client, case_id, case_url)
    appt_date = (TODAY + timedelta(days=1)).isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=appt_date)

    resp = logged_in_client.get(case_url)
    body = resp.data.decode()
    assert "lab-req-due-before-visit" in body
    assert "still sent, not yet received" in body
    assert appt_date in body


def test_case_detail_no_alert_without_upcoming_appointment(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    _add_lab_req(logged_in_client, case_id, case_url)

    resp = logged_in_client.get(case_url)
    assert b"lab-req-due-before-visit" not in resp.data


def test_dashboard_shows_lab_req_due_before_visit(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, title="Alert Case")
    _add_lab_req(logged_in_client, case_id, case_url, work_description="Root canal post")
    appt_date = (TODAY + timedelta(days=3)).isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=appt_date)

    resp = logged_in_client.get("/dashboard")
    body = resp.data.decode()
    assert "Root canal post" in body
    assert "lab-req-row-alert" in body
    assert appt_date in body


def test_dashboard_empty_state_for_lab_req_widget(logged_in_client):
    resp = logged_in_client.get("/dashboard")
    assert b"No open lab requisitions ahead of an upcoming visit" in resp.data
