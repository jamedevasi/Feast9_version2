from datetime import date, timedelta

import pytest

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


def test_followup_rows_carry_distinct_overdue_and_due_soon_indicators(logged_in_client, patient_id):
    for title, offset in [("Late Case", -3), ("Today Case", 0), ("Tomorrow Case", 1), ("Soon Case", 3)]:
        case_id, case_url, _ = _case_for(logged_in_client, patient_id, title=title)
        _set_followup(logged_in_client, case_id, case_url, (date.today() + timedelta(days=offset)).isoformat())

    body = logged_in_client.get("/dashboard").data.decode()
    # each state is spelled out in words (not colour alone), and the two states use different badge classes
    assert "Overdue · 3 days" in body
    assert "Due today" in body
    assert "Due tomorrow" in body
    assert "Due in 3 days" in body
    late_row = body[body.index("Late Case") - 400:body.index("Late Case")]
    soon_row = body[body.index("Soon Case") - 400:body.index("Soon Case")]
    assert "badge-overdue" in late_row and "badge-due-soon" not in late_row
    assert "badge-due-soon" in soon_row and "badge-overdue" not in soon_row
    # the summary tile breaks the count down the same way
    assert "1 overdue" in body and "3 due soon" in body


def test_overdue_singular_day_wording(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, title="Yesterday Case")
    _set_followup(logged_in_client, case_id, case_url, (date.today() - timedelta(days=1)).isoformat())
    body = logged_in_client.get("/dashboard").data.decode()
    assert "Overdue · 1 day<" in body


def test_dashboard_has_no_backup_indication(logged_in_client):
    body = logged_in_client.get("/dashboard").data.decode()
    assert "View backups" not in body
    assert "No backup has ever been run." not in body
    assert "backup attempt failed" not in body
    assert "successful backup was at" not in body


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


# ── Follow-up lifecycle: done / no-show / cancelled ─────────────────────────

def _appt_id_for(patient_id):
    return db.list_appointments_for_patient(patient_id)[0]["id"]


def _set_appt_status(client, appt_id, status):
    appt = db.get_appointment(appt_id)
    token = get_csrf(client, f"/appointments/{appt_id}/edit")
    return client.post(
        f"/appointments/{appt_id}/edit",
        data={
            "doctor_id": str(appt["doctor_id"]), "appt_date": appt["appt_date"],
            "start_time": appt["start_time"], "end_time": appt["end_time"], "title": appt["title"],
            "notes": "", "status": status, "scope": "this", "csrf_token": token,
        },
    )


@pytest.fixture()
def next_day(monkeypatch):
    """Runs the dashboard query as if it were tomorrow: a no-show only surfaces from the day after."""
    class _Tomorrow(date):
        @classmethod
        def today(cls):
            return date.today() + timedelta(days=1)

    monkeypatch.setattr(db, "date", _Tomorrow)


def _noshow_setup(client, patient_id, title="No-show Case"):
    case_id, _url, _ = _case_for(client, patient_id, title=title)
    _book_appointment(client, patient_id)
    appt_id = _appt_id_for(patient_id)
    _set_appt_status(client, appt_id, "No-show")
    return case_id, appt_id


def test_mark_done_removes_followup_from_dashboard(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, title="Done Case")
    _set_followup(logged_in_client, case_id, case_url, (date.today() - timedelta(days=2)).isoformat())
    page = logged_in_client.get("/dashboard").data.decode()
    assert "Done Case" in page and f"/cases/{case_id}/followup/done" in page

    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post(f"/cases/{case_id}/followup/done", data={"csrf_token": token, "next": "dashboard"})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/dashboard")

    case = db.get_case(case_id)
    assert case["follow_up_date"] == "" and case["next_action_note"] == ""
    assert b"Done Case" not in logged_in_client.get("/dashboard").data


def test_mark_done_from_case_page_returns_to_case_and_is_audited(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    _set_followup(logged_in_client, case_id, case_url, "2026-09-01")
    assert b"Mark Follow-up Done" in logged_in_client.get(case_url).data

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(f"/cases/{case_id}/followup/done", data={"csrf_token": token})
    assert resp.headers["Location"].endswith(f"/cases/{case_id}")
    assert db.get_case(case_id)["follow_up_date"] == ""

    conn = db.get_db()
    row = conn.execute("SELECT before_summary FROM audit_log WHERE action = 'case_followup_completed'").fetchone()
    conn.close()
    assert row and "2026-09-01" in row["before_summary"]


def test_mark_done_requires_csrf(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    _set_followup(logged_in_client, case_id, case_url, "2026-09-01")
    resp = logged_in_client.post(f"/cases/{case_id}/followup/done", data={})
    assert resp.status_code in (400, 403)
    assert db.get_case(case_id)["follow_up_date"] == "2026-09-01"


def test_noshow_appears_on_followups_the_next_day_not_the_same_day(logged_in_client, patient_id):
    case_id, _appt_id = _noshow_setup(logged_in_client, patient_id)
    assert db.get_case(case_id)["follow_up_date"] == (date.today() + timedelta(days=1)).isoformat()
    # marked today, so it is not on today's follow-up list yet
    assert b"No-show Case" not in logged_in_client.get("/dashboard").data


def test_noshow_appears_on_followups_once_the_next_day_arrives(logged_in_client, patient_id, next_day):
    _noshow_setup(logged_in_client, patient_id)
    body = logged_in_client.get("/dashboard").data.decode()
    assert "No-show Case" in body
    assert "Due today" in body and "did not attend appointment" in body


def test_cancelled_appointment_never_creates_a_followup(logged_in_client, patient_id, next_day):
    case_id, _url, _ = _case_for(logged_in_client, patient_id, title="Cancel Case")
    _book_appointment(logged_in_client, patient_id, status="Cancelled")
    assert db.get_case(case_id)["follow_up_date"] == ""
    assert b"Cancel Case" not in logged_in_client.get("/dashboard").data


def test_noshow_then_cancelled_drops_off_followups(logged_in_client, patient_id, next_day):
    case_id, appt_id = _noshow_setup(logged_in_client, patient_id)
    assert b"No-show Case" in logged_in_client.get("/dashboard").data

    _set_appt_status(logged_in_client, appt_id, "Cancelled")
    case = db.get_case(case_id)
    assert case["follow_up_date"] == "" and case["follow_up_appointment_id"] is None
    assert b"No-show Case" not in logged_in_client.get("/dashboard").data


def test_noshow_then_deleted_drops_off_followups(logged_in_client, patient_id, next_day):
    case_id, appt_id = _noshow_setup(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, f"/appointments/{appt_id}/edit")
    logged_in_client.post(f"/appointments/{appt_id}/delete", data={"csrf_token": token})
    assert db.get_case(case_id)["follow_up_date"] == ""
    assert b"No-show Case" not in logged_in_client.get("/dashboard").data


def test_noshow_then_attended_drops_off_followups(logged_in_client, patient_id, next_day):
    case_id, appt_id = _noshow_setup(logged_in_client, patient_id)
    _set_appt_status(logged_in_client, appt_id, "Completed")
    assert db.get_case(case_id)["follow_up_date"] == ""
    assert b"No-show Case" not in logged_in_client.get("/dashboard").data


def test_rebooking_after_a_noshow_resolves_its_followup(logged_in_client, patient_id, next_day):
    case_id, _appt_id = _noshow_setup(logged_in_client, patient_id)  # missed 2026-10-01
    assert b"No-show Case" in logged_in_client.get("/dashboard").data

    _book_appointment(logged_in_client, patient_id, appt_date="2026-10-15")
    assert db.get_case(case_id)["follow_up_date"] == ""
    assert b"No-show Case" not in logged_in_client.get("/dashboard").data


def test_entering_an_older_visit_does_not_resolve_a_noshow_followup(logged_in_client, patient_id):
    case_id, _appt_id = _noshow_setup(logged_in_client, patient_id)  # missed 2026-10-01
    _book_appointment(logged_in_client, patient_id, appt_date="2026-09-01", status="Completed")
    assert db.get_case(case_id)["follow_up_date"] != ""


def test_manually_set_followup_survives_the_noshow_being_cancelled(logged_in_client, patient_id):
    case_id, appt_id = _noshow_setup(logged_in_client, patient_id)
    _set_followup(logged_in_client, case_id, f"/cases/{case_id}", "2026-09-25", note="Hand-written reminder")
    assert db.get_case(case_id)["follow_up_appointment_id"] is None

    _set_appt_status(logged_in_client, appt_id, "Cancelled")
    assert db.get_case(case_id)["follow_up_date"] == "2026-09-25"


def test_noshow_on_a_patient_with_only_a_closed_case_still_surfaces(logged_in_client, patient_id, next_day):
    case_id, _url, _ = _case_for(logged_in_client, patient_id, title="Closed Case")
    db.close_case(case_id)
    _book_appointment(logged_in_client, patient_id)
    _set_appt_status(logged_in_client, _appt_id_for(patient_id), "No-show")
    assert b"Closed Case" in logged_in_client.get("/dashboard").data


def test_noshow_for_a_patient_with_no_case_says_nothing_was_created(logged_in_client, patient_id):
    _book_appointment(logged_in_client, patient_id)
    resp = _set_appt_status(logged_in_client, _appt_id_for(patient_id), "No-show")
    page = logged_in_client.get(resp.headers["Location"]).data.decode()
    assert "no case yet" in page


# ── Patient detail flags the same cases the dashboard lists ─────────────────

def test_patient_detail_flags_the_case_with_an_overdue_followup(logged_in_client, patient_id):
    _case_for(logged_in_client, patient_id, title="Quiet Case")
    late_id, late_url, _ = _case_for(logged_in_client, patient_id, title="Late Case")
    _set_followup(logged_in_client, late_id, late_url, (date.today() - timedelta(days=2)).isoformat(), note="Call back")
    soon_id, soon_url, _ = _case_for(logged_in_client, patient_id, title="Soon Case")
    _set_followup(logged_in_client, soon_id, soon_url, (date.today() + timedelta(days=1)).isoformat())
    far_id, far_url, _ = _case_for(logged_in_client, patient_id, title="Far Case")
    _set_followup(logged_in_client, far_id, far_url, (date.today() + timedelta(days=30)).isoformat())

    body = logged_in_client.get(f"/patients/{patient_id}").data.decode()
    assert body.count("case-row-followup-overdue") == 1 and body.count("case-row-followup-upcoming") == 1
    assert "Follow-up overdue · 2 days" in body and "Follow-up due tomorrow" in body
    # cases are listed newest-opened first, flagged or not
    assert body.index("Far Case") < body.index("Soon Case") < body.index("Late Case") < body.index("Quiet Case")


def test_patient_detail_case_row_shows_the_latest_update_not_the_opening_date(logged_in_client, patient_id):
    case_id, _url, _ = _case_for(logged_in_client, patient_id)
    conn = db.get_db()
    conn.execute("UPDATE cases SET created_at = '2026-01-05 10:00:00', updated_at = '2026-02-01 10:00:00' WHERE id = ?", (case_id,))
    conn.commit()
    conn.close()
    body = logged_in_client.get(f"/patients/{patient_id}").data.decode()
    assert "Updated 2026-02-01" in body and "Opened 2026-01-05" not in body

    # a visit note doesn't touch cases.updated_at, but it is the latest thing done on the case
    conn = db.get_db()
    conn.execute(
        "INSERT INTO case_visit_notes (case_id, patient_id, note, visit_date, created_at)"
        " VALUES (?, ?, 'x', '2026-03-10', '2026-03-10 09:00:00')",
        (case_id, patient_id),
    )
    conn.commit()
    conn.close()
    assert "Updated 2026-03-10" in logged_in_client.get(f"/patients/{patient_id}").data.decode()


def test_patient_detail_has_no_followup_flag_once_marked_done(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    _set_followup(logged_in_client, case_id, case_url, (date.today() - timedelta(days=1)).isoformat())
    assert b"Follow-up overdue" in logged_in_client.get(f"/patients/{patient_id}").data
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(f"/cases/{case_id}/followup/done", data={"csrf_token": token})
    assert b"Follow-up overdue" not in logged_in_client.get(f"/patients/{patient_id}").data


def test_patient_detail_shows_a_closed_case_whose_noshow_followup_is_due(logged_in_client, patient_id, next_day):
    case_id, _url, _ = _case_for(logged_in_client, patient_id, title="Closed Case")
    db.close_case(case_id)
    _book_appointment(logged_in_client, patient_id)
    _set_appt_status(logged_in_client, _appt_id_for(patient_id), "No-show")
    body = logged_in_client.get(f"/patients/{patient_id}").data.decode()
    assert "Follow-up due today" in body
    assert "case-row-closed" not in body  # not hidden behind "Show all cases"


# ── A visit note on the appointment's day marks that appointment Completed ───

def _add_note(client, case_id, visit_date, note="Seen, scaling done"):
    token = get_csrf(client, f"/cases/{case_id}")
    return client.post(
        f"/cases/{case_id}/visit-notes",
        data={"note": note, "visit_date": visit_date, "csrf_token": token}, follow_redirects=True,
    )


def test_visit_note_today_completes_todays_scheduled_appointment(logged_in_client, patient_id):
    case_id, _url, _ = _case_for(logged_in_client, patient_id)
    today = date.today().isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=today)
    appt_id = _appt_id_for(patient_id)

    resp = _add_note(logged_in_client, case_id, today)
    assert b"was marked Completed" in resp.data
    assert db.get_appointment(appt_id)["status"] == "Completed"
    body = logged_in_client.get("/dashboard").data.decode()
    assert "appt-row-completed" in body and "badge-status-completed" in body

    conn = db.get_db()
    row = conn.execute(
        "SELECT entity_id FROM audit_log WHERE action = 'appointment_completed_by_visit_note'"
    ).fetchone()
    conn.close()
    assert row and row["entity_id"] == appt_id


def test_visit_note_for_another_day_leaves_the_appointment_scheduled(logged_in_client, patient_id):
    case_id, _url, _ = _case_for(logged_in_client, patient_id)
    today = date.today().isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=today)
    resp = _add_note(logged_in_client, case_id, (date.today() - timedelta(days=1)).isoformat())
    assert b"was marked Completed" not in resp.data
    assert db.get_appointment(_appt_id_for(patient_id))["status"] == "Scheduled"


@pytest.mark.parametrize("status", ["Cancelled", "No-show"])
def test_visit_note_never_changes_a_cancelled_or_noshow_appointment(logged_in_client, patient_id, status):
    case_id, _url, _ = _case_for(logged_in_client, patient_id)
    today = date.today().isoformat()
    _book_appointment(logged_in_client, patient_id, appt_date=today, status=status)
    _add_note(logged_in_client, case_id, today)
    assert db.get_appointment(_appt_id_for(patient_id))["status"] == status


def test_visit_note_completes_only_one_of_two_appointments_that_day(logged_in_client, patient_id):
    case_id, _url, doctor_id = _case_for(logged_in_client, patient_id)
    today = date.today().isoformat()
    _book_appointment(logged_in_client, patient_id, doctor_id=doctor_id, appt_date=today, start_time="09:00", end_time="09:30")
    _book_appointment(logged_in_client, patient_id, doctor_id=doctor_id, appt_date=today, start_time="15:00", end_time="15:30")
    _add_note(logged_in_client, case_id, today)
    by_time = {a["start_time"]: a["status"] for a in db.list_appointments_for_patient(patient_id)}
    assert by_time == {"09:00": "Completed", "15:00": "Scheduled"}


def test_visit_note_does_not_complete_another_patients_appointment(logged_in_client, patient_id):
    case_id, _url, _ = _case_for(logged_in_client, patient_id)
    other = db.add_patient({**db.get_patient(patient_id), "name": "Other Person", "mobile": "9000000009"})
    today = date.today().isoformat()
    _book_appointment(logged_in_client, other, appt_date=today)
    _add_note(logged_in_client, case_id, today)
    assert db.get_appointment(_appt_id_for(other))["status"] == "Scheduled"
