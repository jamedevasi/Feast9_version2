from datetime import date, timedelta

from app import db
from tests.conftest import get_csrf
from tests.test_appointments import _book_appointment
from tests.test_cases import _create_case
from tests.test_roles import _create_user, _login, _logout


def _case_for(client, patient_id, **overrides):
    resp, doctor_id = _create_case(client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url, doctor_id


def _set_followup(client, case_id, case_url, follow_up_date, note="Review"):
    token = get_csrf(client, case_url)
    client.post(
        f"/cases/{case_id}/followup",
        data={"follow_up_date": follow_up_date, "next_action_note": note, "csrf_token": token},
    )


def test_dashboard_empty_states(logged_in_client):
    resp = logged_in_client.get("/dashboard")
    assert resp.status_code == 200
    assert b"No follow-ups requiring attention" in resp.data
    assert b"No appointments scheduled for today" in resp.data


def test_overdue_and_upcoming_followups_appear_in_dashboard(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, title="Overdue Case")
    overdue_date = (date.today() - timedelta(days=2)).isoformat()
    _set_followup(logged_in_client, case_id, case_url, overdue_date, note="Call about swelling")

    patient2 = patient_id  # same patient, second case
    case_id2, case_url2, _ = _case_for(logged_in_client, patient2, title="Upcoming Case")
    upcoming_date = (date.today() + timedelta(days=2)).isoformat()
    _set_followup(logged_in_client, case_id2, case_url2, upcoming_date, note="Recall for review")

    resp = logged_in_client.get("/dashboard")
    body = resp.data.decode()
    assert "Overdue Case" in body
    assert "Upcoming Case" in body
    assert "Call about swelling" in body
    assert "Recall for review" in body
    # overdue row rendered before the upcoming row
    assert body.index("Overdue Case") < body.index("Upcoming Case")
    assert "followup-row-overdue" in body
    assert "followup-row-upcoming" in body


def test_followup_beyond_three_days_is_not_shown(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, title="Far Future Case")
    far_date = (date.today() + timedelta(days=10)).isoformat()
    _set_followup(logged_in_client, case_id, case_url, far_date)

    resp = logged_in_client.get("/dashboard")
    assert b"Far Future Case" not in resp.data
    assert b"No follow-ups requiring attention" in resp.data


def test_closed_case_followup_is_not_shown(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, title="Closed Case Follow-up")
    overdue_date = (date.today() - timedelta(days=1)).isoformat()
    _set_followup(logged_in_client, case_id, case_url, overdue_date)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(f"/cases/{case_id}/close", data={"csrf_token": token})

    resp = logged_in_client.get("/dashboard")
    assert b"Closed Case Follow-up" not in resp.data


def test_active_cases_count_tile(logged_in_client, patient_id):
    _case_for(logged_in_client, patient_id, title="Active Case A")
    case_id_b, case_url_b, _ = _case_for(logged_in_client, patient_id, title="Active Case B")
    resp = logged_in_client.get("/dashboard")
    assert db.get_active_cases_count() == 2
    assert resp.status_code == 200

    token = get_csrf(logged_in_client, case_url_b)
    logged_in_client.post(f"/cases/{case_id_b}/close", data={"csrf_token": token})
    assert db.get_active_cases_count() == 1


def test_outstanding_balance_tile_reflects_payments(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, total_cost="4000")
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": date.today().isoformat(), "amount": "1500", "method": "Cash",
              "reference": "", "notes": "", "csrf_token": token},
    )
    assert db.get_outstanding_balance() == 2500
    resp = logged_in_client.get("/dashboard")
    assert b"2500.00" in resp.data


def test_receptionist_sees_restricted_balance_not_the_figure(logged_in_client, patient_id):
    _create_user(logged_in_client, "dashrecep", "receptionist")
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, total_cost="9999")

    _logout(logged_in_client)
    _login(logged_in_client, "dashrecep")
    resp = logged_in_client.get("/dashboard")
    body = resp.data.decode()
    assert "Restricted" in body
    assert "9999" not in body


def test_todays_appointment_appears_with_status_badge(logged_in_client, patient_id):
    today = date.today().isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=today)
    resp = logged_in_client.get("/dashboard")
    body = resp.data.decode()
    assert "badge-status-scheduled" in body
    assert "Scheduled" in body
