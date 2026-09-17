from datetime import date

import pytest

from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case
from tests.test_roles import _create_user, _login, _logout

TODAY = date.today()
YEAR = TODAY.year
MONTH_INDEX = TODAY.month - 1  # 0-based into the 12-value monthly arrays


def _case_for(client, patient_id, **overrides):
    resp, doctor_id = _create_case(client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url, doctor_id


def _add_payment(client, case_id, case_url, amount):
    token = get_csrf(client, case_url)
    client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": TODAY.isoformat(), "amount": str(amount), "method": "Cash", "csrf_token": token},
    )


def test_monthly_revenue_and_new_case_series(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, total_cost="1000")
    _add_payment(logged_in_client, case_id, case_url, 600)

    revenue = db.get_monthly_revenue(YEAR)
    assert len(revenue) == 12
    assert revenue[MONTH_INDEX] >= 600
    assert sum(revenue) == pytest.approx(revenue[MONTH_INDEX])

    new_cases = db.get_monthly_new_cases(YEAR)
    assert new_cases[MONTH_INDEX] >= 1

    new_patients = db.get_monthly_new_patients(YEAR)
    assert new_patients[MONTH_INDEX] >= 1


def test_case_status_breakdown(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, title="Close This")
    _case_for(logged_in_client, patient_id, title="Stay Active")
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(f"/cases/{case_id}/close", data={"csrf_token": token})

    breakdown = db.get_case_status_breakdown(YEAR)
    assert breakdown["Active"] >= 1
    assert breakdown["Closed"] >= 1


def test_appointment_status_breakdown_and_monthly_series(logged_in_client, patient_id):
    doctor_id = db.add_doctor("Dr. Analytics Test", "#123456")
    token = get_csrf(logged_in_client, f"/appointments/new?patient_id={patient_id}")
    logged_in_client.post(
        "/appointments/new",
        data={
            "doctor_id": str(doctor_id), "appt_date": TODAY.isoformat(), "start_time": "09:00",
            "end_time": "09:30", "title": "Checkup", "notes": "", "status": "Scheduled",
            "clear_followup": "", "patient_locked": "1", "patient_id": str(patient_id),
            "csrf_token": token,
        },
    )

    breakdown = db.get_appointment_status_breakdown(YEAR)
    assert breakdown["Scheduled"] >= 1
    assert set(breakdown.keys()) == {"Scheduled", "Completed", "Cancelled", "No-show"}

    monthly_appts = db.get_monthly_appointments(YEAR)
    assert monthly_appts[MONTH_INDEX] >= 1


def test_doctor_revenue_share_excludes_zero_collected_doctors(logged_in_client, patient_id):
    paid_case_id, paid_case_url, paid_doctor_id = _case_for(logged_in_client, patient_id, total_cost="500")
    _add_payment(logged_in_client, paid_case_id, paid_case_url, 500)
    _unpaid_case_id, _unpaid_url, unpaid_doctor_id = _case_for(logged_in_client, patient_id, total_cost="500")

    share = db.get_doctor_revenue_share(YEAR)
    doctor_ids = [row["doctor_id"] for row in share]
    assert paid_doctor_id in doctor_ids
    assert unpaid_doctor_id not in doctor_ids


def test_procedure_popularity_tally(logged_in_client, patient_id):
    _create_case(
        logged_in_client, patient_id, title="Procedures Case",
        procedures=["Scaling", "Filling"],
    )
    _create_case(logged_in_client, patient_id, title="Second Case", procedures=["Scaling"])

    popularity = db.get_procedure_popularity(YEAR)
    by_name = {p["name"]: p["count"] for p in popularity}
    assert by_name.get("Scaling") == 2
    assert by_name.get("Filling") == 1


def test_analytics_kpis(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, total_cost="2000")
    _add_payment(logged_in_client, case_id, case_url, 800)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(f"/cases/{case_id}/close", data={"csrf_token": token})

    kpis = db.get_analytics_kpis(YEAR)
    assert kpis["revenue_collected"] >= 800
    assert kpis["new_patients"] >= 1
    assert kpis["new_cases"] >= 1
    assert kpis["cases_closed"] >= 1
    assert kpis["avg_case_value"] > 0
    assert 0 <= kpis["no_show_rate"] <= 100


def test_analytics_years_always_includes_current_year(logged_in_client):
    years = db.get_analytics_years()
    assert YEAR in years


def test_analytics_page_renders_charts_and_kpis(logged_in_client, patient_id):
    _create_case(logged_in_client, patient_id, title="Analytics Render Case")
    resp = logged_in_client.get("/analytics/")
    body = resp.data.decode()
    assert resp.status_code == 200
    assert "Revenue Collected" in body
    assert "No-show Rate" in body
    assert 'id="chart-monthly-revenue"' in body
    assert 'id="chart-appointment-status"' in body
    assert "vendor/chart.umd.min.js" in body
    assert "analytics.js" in body


def test_receptionist_blocked_from_analytics(logged_in_client, patient_id):
    _create_user(logged_in_client, "anarecep", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "anarecep")

    assert logged_in_client.get("/analytics/").status_code == 403
    dash = logged_in_client.get("/dashboard")
    assert b'href="/analytics/"' not in dash.data
