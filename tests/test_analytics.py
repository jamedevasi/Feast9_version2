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
    for chart in ("patients-total-new", "cases-active-new", "weekday-appointments", "weekday-revenue",
                  "demographics"):
        assert f'id="chart-{chart}"' in body
    assert "Revenue by Procedure Type" in body  # empty state here — no payments recorded yet
    assert 'id="chart-monthly-patients"' not in body  # folded into Total vs New, not duplicated
    assert 'id="chart-monthly-cases"' not in body  # folded into Cases - Active vs New
    for group in ("Revenue", "Patients", "Cases", "Appointments"):
        assert f'<h2 class="chart-group-title">{group}</h2>' in body
    assert "Total Patients" in body and "Active Cases" in body
    assert "vendor/chart.umd.min.js" in body
    assert "analytics.js" in body


def test_receptionist_blocked_from_analytics(logged_in_client, patient_id):
    _create_user(logged_in_client, "anarecep", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "anarecep")

    assert logged_in_client.get("/analytics/").status_code == 403
    dash = logged_in_client.get("/dashboard")
    assert b'href="/analytics/"' not in dash.data


def test_total_patients_and_active_cases_month_end(logged_in_client, patient_id):
    _create_case(logged_in_client, patient_id, title="Open Case")
    totals = db.get_monthly_total_patients(YEAR)
    active = db.get_monthly_active_cases(YEAR)
    assert totals[MONTH_INDEX] >= 1 and active[MONTH_INDEX] >= 1
    # Months that haven't happened yet stop the line rather than drawing a flat future.
    assert all(v is None for v in totals[MONTH_INDEX + 1:])
    assert all(v is None for v in active[MONTH_INDEX + 1:])
    # A past year ends with nothing open if no case existed then.
    assert db.get_monthly_active_cases(2000) == [0] * 12


def test_active_cases_excludes_closed_and_yearly_trend_needs_two_years(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, title="Soon Closed")
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(f"/cases/{case_id}/close", data={"csrf_token": token})
    assert db.get_monthly_active_cases(YEAR)[MONTH_INDEX] == 0
    assert len(db.get_yearly_active_cases()) == 1
    resp = logged_in_client.get("/analytics/")
    assert b'id="chart-active-cases-yearly"' not in resp.data
    assert b"more than one year of cases" in resp.data


def test_weekday_activity_monday_first_and_skips_cancelled(logged_in_client, patient_id):
    conn = db.get_db()
    # 2026-09-21 is a Monday, 2026-09-27 a Sunday.
    for appt_date, status in [("2026-09-21", "Scheduled"), ("2026-09-21", "Cancelled"), ("2026-09-27", "Completed")]:
        conn.execute(
            "INSERT INTO appointments (patient_id, appt_date, start_time, status, created_at) VALUES (?, ?, '10:00', ?, ?)",
            (patient_id, appt_date, status, "2026-09-01 10:00:00"),
        )
    conn.commit()
    conn.close()
    weekday = db.get_weekday_activity(2026)
    assert weekday["labels"][0] == "Mon" and weekday["labels"][6] == "Sun"
    assert weekday["appointments"][0] == 1  # the cancelled Monday booking isn't counted
    assert weekday["appointments"][6] == 1


def test_patient_demographics_children_override_sex(logged_in_client, patient_id):
    from tests.conftest import register_patient

    register_patient(logged_in_client, name="Adult Man", sex="Male", date_of_birth="1980-05-05")
    register_patient(
        logged_in_client, name="Young Girl", sex="Female", date_of_birth=f"{YEAR - 8}-01-01",
        guardian_name="Parent", guardian_relation="Mother", guardian_mobile="9812345678",
    )
    demo = db.get_patient_demographics(YEAR)
    assert demo["Men"] == 1
    assert demo["Women"] == 1  # the fixture patient (born 1990, Female)
    assert demo["Children"] == 1


def test_revenue_by_procedure_splits_payment_across_procedures(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(
        logged_in_client, patient_id, title="Two Procedures", procedures=["Scaling", "Filling"], total_cost="1000",
    )
    _add_payment(logged_in_client, case_id, case_url, 600)
    series = {s["name"]: s for s in db.get_monthly_revenue_by_procedure(YEAR)}
    assert series["Scaling"]["values"][MONTH_INDEX] == 300
    assert series["Filling"]["values"][MONTH_INDEX] == 300
    assert not any(s["is_other"] for s in series.values())


def test_revenue_by_procedure_folds_tail_into_other(logged_in_client, patient_id):
    names = ["P1", "P2", "P3", "P4", "P5", "P6", "P7"]
    conn = db.get_db()
    for i, name in enumerate(names):
        conn.execute("INSERT INTO procedure_types (name, is_active) VALUES (?, 1)", (name,))
    conn.commit()
    conn.close()
    for i, name in enumerate(names):
        case_id, case_url, _ = _case_for(logged_in_client, patient_id, title=f"Case {name}", procedures=[name], total_cost="10000")
        _add_payment(logged_in_client, case_id, case_url, 1000 - i * 100)  # P1 earns most
    series = db.get_monthly_revenue_by_procedure(YEAR)
    assert [s["name"] for s in series[:5]] == ["P1", "P2", "P3", "P4", "P5"]
    assert series[-1]["is_other"] and series[-1]["name"] == "Other (2 types)"
    assert series[-1]["values"][MONTH_INDEX] == 500 + 400


def test_yoy_unavailable_without_previous_year_data(logged_in_client, patient_id):
    body = logged_in_client.get(f"/analytics/?year={YEAR}&compare=yoy").data.decode()
    assert "becomes available once" in body
    assert 'id="compare-toggle"' in body and "disabled" in body
    assert '"previous"' not in body  # the request's compare=yoy is ignored — nothing to compare
    assert "stat-delta" not in body


def test_yoy_compare_overlays_previous_year(logged_in_client, patient_id):
    prev = YEAR - 1
    conn = db.get_db()
    conn.execute(
        "INSERT INTO patients (name, sex, created_at) VALUES ('Last Year Patient', 'Male', ?)",
        (f"{prev}-03-10 10:00:00",),
    )
    conn.commit()
    conn.close()

    body = logged_in_client.get(f"/analytics/?year={YEAR}").data.decode()
    assert f"Compare with {prev}" in body and "becomes available once" not in body
    assert "stat-delta" not in body  # available, but off until ticked

    body = logged_in_client.get(f"/analytics/?year={YEAR}&compare=yoy").data.decode()
    assert f"Comparing {YEAR} with {prev}" in body
    assert f'"previous": {{' in body or '"previous":{' in body
    assert f"vs same period {prev}" in body  # current year: like-for-like with last year so far


def test_kpis_and_weekdays_can_stop_at_a_cutoff_date(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, title="Cutoff Case", total_cost="5000")
    conn = db.get_db()
    for day, amount in [("2025-01-06", 100), ("2025-12-29", 900)]:  # both Mondays
        conn.execute(
            "INSERT INTO payments (case_id, patient_id, amount, payment_date, method, created_at) VALUES (?, ?, ?, ?, 'Cash', ?)",
            (case_id, patient_id, amount, day, day + " 10:00:00"),
        )
    conn.commit()
    conn.close()
    assert db.get_analytics_kpis(2025)["revenue_collected"] == 1000
    # Like-for-like: "2025 up to 23 Sep" leaves out the December payment.
    assert db.get_analytics_kpis(2025, until="2025-09-23")["revenue_collected"] == 100
    assert db.get_weekday_activity(2025, until="2025-09-23")["revenue"][0] == 100
    assert db.get_weekday_activity(2025)["revenue"][0] == 1000
