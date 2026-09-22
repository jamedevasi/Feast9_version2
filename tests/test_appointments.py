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


def test_calendar_shows_doctor_colour_legend(logged_in_client, patient_id):
    _book_appointment(logged_in_client, patient_id)
    resp = logged_in_client.get("/appointments/2026/10")
    body = resp.data.decode()
    assert "doctor-legend" in body
    assert "Dr. Test Doctor" in body
    assert "color-swatch" in body


def _book_recurring(client, patient_id, doctor_id=None, **overrides):
    data = {"is_recurring": "on", "recur_interval": "Weekly", "recur_until": "2026-10-22"}
    data.update(overrides)
    return _book_appointment(client, patient_id, doctor_id, **data)


def test_recurring_creates_bounded_set_sharing_a_series_id(logged_in_client, patient_id):
    resp, _ = _book_recurring(logged_in_client, patient_id)
    assert resp.status_code == 302

    appts = sorted(db.list_appointments_for_patient(patient_id), key=lambda a: a["appt_date"])
    assert [a["appt_date"] for a in appts] == ["2026-10-01", "2026-10-08", "2026-10-15", "2026-10-22"]
    series_ids = {a["series_id"] for a in appts}
    assert len(series_ids) == 1 and None not in series_ids
    assert all(a["is_recurring"] == 1 and a["recur_interval"] == "Weekly" for a in appts)


def test_recurring_requires_interval_and_end_date(logged_in_client, patient_id):
    resp, _ = _book_appointment(logged_in_client, patient_id, is_recurring="on", recur_interval="", recur_until="")
    assert resp.status_code == 200
    assert b"Select a valid recurrence interval" in resp.data
    assert db.list_appointments_for_patient(patient_id) == []


def test_recurring_capped_at_max_occurrences(logged_in_client, patient_id):
    resp, _ = _book_recurring(logged_in_client, patient_id, recur_until="2099-01-01")
    assert resp.status_code == 302
    assert len(db.list_appointments_for_patient(patient_id)) == 52


def test_sunday_occurrences_move_to_monday_instead_of_being_dropped(logged_in_client, patient_id):
    # 2026-10-04 is a Sunday. Every occurrence must still get a calendar entry — a series that
    # starts on a Sunday used to end up with none at all.
    resp, _ = _book_recurring(
        logged_in_client, patient_id, appt_date="2026-10-04", recur_until="2026-10-25", skip_sundays="on",
    )
    assert resp.status_code == 302
    dates = sorted(a["appt_date"] for a in db.list_appointments_for_patient(patient_id))
    assert dates == ["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"]
    assert all(date.fromisoformat(d).weekday() == 0 for d in dates)  # all Mondays

    flashed = logged_in_client.get(resp.headers["Location"]).data.decode()
    assert "4 occurrences fell on a Sunday and were moved to the following Monday" in flashed
    assert "2026-10-04 → 2026-10-05" in flashed


def test_monthly_recurrence_does_not_drift_after_a_short_month(logged_in_client, patient_id):
    _book_recurring(
        logged_in_client, patient_id, appt_date="2027-01-31", recur_interval="Monthly",
        recur_until="2027-06-30", skip_sundays="",
    )
    dates = sorted(a["appt_date"] for a in db.list_appointments_for_patient(patient_id))
    assert dates == ["2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30", "2027-05-31", "2027-06-30"]


def test_every_occurrence_has_its_own_calendar_entry_across_months(logged_in_client, patient_id):
    _book_recurring(logged_in_client, patient_id, appt_date="2026-10-22", recur_until="2026-11-12")
    assert len(db.list_appointments_for_patient(patient_id)) == 4  # Oct 22, Oct 29, Nov 5, Nov 12

    october = logged_in_client.get("/appointments/2026/10").data.decode()
    november = logged_in_client.get("/appointments/2026/11").data.decode()
    assert october.count("calendar-appt") == 2 and october.count("🔁") == 2
    assert november.count("calendar-appt") == 2 and november.count("🔁") == 2


def test_recurring_series_cut_short_by_the_cap_says_so(logged_in_client, patient_id):
    resp, _ = _book_recurring(logged_in_client, patient_id, recur_until="2099-01-01")
    flashed = logged_in_client.get(resp.headers["Location"]).data.decode()
    assert "Only the first 52 occurrences were booked" in flashed


def test_recurring_series_within_the_cap_shows_no_cap_notice(logged_in_client, patient_id):
    resp, _ = _book_recurring(logged_in_client, patient_id)
    flashed = logged_in_client.get(resp.headers["Location"]).data.decode()
    assert "Only the first" not in flashed


def test_skip_sundays_unchecked_includes_sunday_occurrences(logged_in_client, patient_id):
    resp, _ = _book_recurring(
        logged_in_client, patient_id, appt_date="2026-10-04", recur_until="2026-10-25", skip_sundays="",
    )
    assert resp.status_code == 302
    assert len(db.list_appointments_for_patient(patient_id)) == 4


def test_recurring_conflict_with_existing_appointment_flashes_warning(logged_in_client, patient_id):
    doctor_id = _seed_doctor()
    _book_appointment(logged_in_client, patient_id, doctor_id=doctor_id, appt_date="2026-10-08")

    resp, _ = _book_recurring(logged_in_client, patient_id, doctor_id=doctor_id)
    assert resp.status_code == 302
    follow = logged_in_client.get(resp.headers["Location"])
    assert b"Possible conflict" in follow.data
    assert b"2026-10-08" in follow.data


def test_edit_this_occurrence_only_leaves_others_unchanged(logged_in_client, patient_id):
    _book_recurring(logged_in_client, patient_id)
    appts = sorted(db.list_appointments_for_patient(patient_id), key=lambda a: a["appt_date"])
    target = appts[1]

    token = get_csrf(logged_in_client, f"/appointments/{target['id']}/edit")
    resp = logged_in_client.post(
        f"/appointments/{target['id']}/edit",
        data={
            "doctor_id": str(target["doctor_id"]), "appt_date": target["appt_date"],
            "start_time": "14:00", "end_time": "14:30", "title": "Changed just this one",
            "notes": "", "status": "Scheduled", "scope": "this", "csrf_token": token,
        },
    )
    assert resp.status_code == 302

    updated = db.get_appointment(target["id"])
    assert updated["title"] == "Changed just this one"
    others = [a for a in db.list_appointments_for_patient(patient_id) if a["id"] != target["id"]]
    assert all(a["title"] == "Scaling" for a in others)


def test_edit_entire_series_updates_scheduled_but_not_completed(logged_in_client, patient_id):
    _book_recurring(logged_in_client, patient_id)
    appts = sorted(db.list_appointments_for_patient(patient_id), key=lambda a: a["appt_date"])
    completed, target = appts[0], appts[1]

    token = get_csrf(logged_in_client, f"/appointments/{completed['id']}/edit")
    logged_in_client.post(
        f"/appointments/{completed['id']}/edit",
        data={
            "doctor_id": str(completed["doctor_id"]), "appt_date": completed["appt_date"],
            "start_time": completed["start_time"], "end_time": completed["end_time"],
            "title": completed["title"], "notes": "", "status": "Completed",
            "scope": "this", "csrf_token": token,
        },
    )

    token = get_csrf(logged_in_client, f"/appointments/{target['id']}/edit")
    resp = logged_in_client.post(
        f"/appointments/{target['id']}/edit",
        data={
            "doctor_id": str(target["doctor_id"]), "appt_date": target["appt_date"],
            "start_time": "15:00", "end_time": "15:30", "title": "Whole series retitled",
            "notes": "", "status": "Scheduled", "scope": "series", "csrf_token": token,
        },
    )
    assert resp.status_code == 302

    refreshed = {a["id"]: a for a in db.list_appointments_for_patient(patient_id)}
    assert refreshed[completed["id"]]["title"] == "Scaling"  # untouched — already Completed
    assert refreshed[completed["id"]]["start_time"] != "15:00"
    for a in appts[1:]:
        assert refreshed[a["id"]]["title"] == "Whole series retitled"
        assert refreshed[a["id"]]["start_time"] == "15:00"


def test_cancel_series_cancels_scheduled_but_not_completed(logged_in_client, patient_id):
    _book_recurring(logged_in_client, patient_id)
    appts = sorted(db.list_appointments_for_patient(patient_id), key=lambda a: a["appt_date"])
    completed, other = appts[0], appts[1]

    token = get_csrf(logged_in_client, f"/appointments/{completed['id']}/edit")
    logged_in_client.post(
        f"/appointments/{completed['id']}/edit",
        data={
            "doctor_id": str(completed["doctor_id"]), "appt_date": completed["appt_date"],
            "start_time": completed["start_time"], "end_time": completed["end_time"],
            "title": completed["title"], "notes": "", "status": "Completed",
            "scope": "this", "csrf_token": token,
        },
    )

    token = get_csrf(logged_in_client, f"/appointments/{other['id']}/edit")
    resp = logged_in_client.post(f"/appointments/{other['id']}/cancel-series", data={"csrf_token": token})
    assert resp.status_code == 302

    refreshed = {a["id"]: a for a in db.list_appointments_for_patient(patient_id)}
    assert refreshed[completed["id"]]["status"] == "Completed"
    for a in appts[1:]:
        assert refreshed[a["id"]]["status"] == "Cancelled"


def test_noshow_on_one_series_occurrence_does_not_affect_others(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id)
    _book_recurring(logged_in_client, patient_id)
    appts = sorted(db.list_appointments_for_patient(patient_id), key=lambda a: a["appt_date"])
    target = appts[2]

    token = get_csrf(logged_in_client, f"/appointments/{target['id']}/edit")
    logged_in_client.post(
        f"/appointments/{target['id']}/edit",
        data={
            "doctor_id": str(target["doctor_id"]), "appt_date": target["appt_date"],
            "start_time": target["start_time"], "end_time": target["end_time"],
            "title": target["title"], "notes": "", "status": "No-show",
            "scope": "this", "csrf_token": token,
        },
    )

    from datetime import date, timedelta
    next_day = (date.today() + timedelta(days=1)).isoformat()
    assert db.get_case(case_id)["follow_up_date"] == next_day

    others = [a for a in db.list_appointments_for_patient(patient_id) if a["id"] != target["id"]]
    assert all(a["status"] == "Scheduled" for a in others)


def test_calendar_shows_recurrence_icon(logged_in_client, patient_id):
    _book_recurring(logged_in_client, patient_id)
    resp = logged_in_client.get("/appointments/2026/10")
    assert "🔁".encode() in resp.data
