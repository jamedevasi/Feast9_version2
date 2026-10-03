"""Receptionist (coordination only, no medical records) vs guest doctor (clinical, but no
settings / privacy requests / financials / reports / analytics) — enforced server-side."""
from datetime import date, timedelta

import pytest

from app import auth, db
from tests.conftest import get_csrf, register_patient
from tests.test_cases import _create_case
from tests.test_roles import _create_user, _login, _logout


@pytest.fixture()
def clinic(logged_in_client):
    """As admin: a patient with an allergy, a case with a visit note, a follow-up and lab work."""
    client = logged_in_client
    patient_id = register_patient(client, allergies_other="Penicillin-XYZ", medical_conditions_other="Asthma-XYZ")
    resp, doctor_id = _create_case(client, patient_id, title="Crown upper left")
    case_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    token = get_csrf(client, f"/cases/{case_id}")
    client.post(f"/cases/{case_id}/visit-notes", data={"note": "Secret-clinical-note", "csrf_token": token})
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    db.update_case_followup(case_id, tomorrow, "Call about crown fit")
    db.add_lab_req(case_id, patient_id, "Smile Lab", "PFM crown 26", date.today().isoformat(), "", "")
    return {"patient_id": patient_id, "case_id": case_id, "doctor_id": doctor_id,
            "lab_req_id": db.list_lab_reqs_for_case(case_id)[0]["id"]}


def _as(client, role):
    _create_user(client, f"user_{role}", role)
    _logout(client)
    _login(client, f"user_{role}")
    return client


# ── Receptionist ──────────────────────────────────────────────────────────

def test_receptionist_cannot_open_any_medical_record(logged_in_client, clinic):
    client = _as(logged_in_client, "receptionist")
    c, p = clinic["case_id"], clinic["patient_id"]
    for url in (f"/cases/{c}", f"/cases/{c}/edit", f"/cases/{c}/summary.pdf", f"/cases/{c}/consent.pdf",
                f"/cases/{c}/consent-signature", f"/patients/{p}/cases/new", f"/patients/{p}/dental-chart",
                f"/patients/{p}/summary.pdf"):
        assert client.get(url).status_code == 403, url

    token = get_csrf(client, "/dashboard")
    for url, data in (
        (f"/cases/{c}/visit-notes", {"note": "x"}),
        (f"/cases/{c}/prescriptions", {}),
        (f"/cases/{c}/lab-reqs", {"work_description": "x"}),
        (f"/lab-reqs/{clinic['lab_req_id']}/delete", {}),
        (f"/cases/{c}/referrals", {}),
        (f"/cases/{c}/close", {}),
        (f"/patients/{p}/cases/new", {"title": "x", "doctor_id": str(clinic["doctor_id"])}),
    ):
        assert client.post(url, data={**data, "csrf_token": token}).status_code == 403, url
    assert len(db.list_lab_reqs_for_case(c)) == 1
    assert db.get_case(c)["status"] == "Active"


def test_receptionist_patient_page_has_no_medical_details(logged_in_client, clinic):
    client = _as(logged_in_client, "receptionist")
    body = client.get(f"/patients/{clinic['patient_id']}").data.decode()
    assert "Penicillin-XYZ" not in body and "Asthma-XYZ" not in body
    assert "Secret-clinical-note" not in body
    assert "Restricted" in body
    assert "Crown upper left" in body  # the case is listed by title...
    assert f"/cases/{clinic['case_id']}\"" not in body  # ...but not linked
    assert "Dental Chart" not in body and "Patient Summary" not in body and "+ New Case" not in body


def test_receptionist_edits_contact_details_without_touching_medical_history(logged_in_client, clinic):
    client = _as(logged_in_client, "receptionist")
    p = clinic["patient_id"]
    form = client.get(f"/patients/{p}/edit").data.decode()
    assert "Penicillin-XYZ" not in form and "Medical History" not in form

    token = get_csrf(client, f"/patients/{p}/edit")
    resp = client.post(f"/patients/{p}/edit", data={
        "name": "Case Test Patient", "sex": "Female", "date_of_birth": "1990-01-01", "mobile": "9876500077",
        "dpdp_notice_accepted": "on", "allergies_other": "", "csrf_token": token,
    })
    assert resp.status_code == 302
    patient = db.get_patient(p)
    assert patient["mobile"] == "9876500077"
    assert patient["allergies_other"] == "Penicillin-XYZ"
    assert patient["medical_conditions_other"] == "Asthma-XYZ"


def test_receptionist_registration_ignores_posted_medical_history(logged_in_client):
    client = _as(logged_in_client, "receptionist")
    p = register_patient(client, name="Front Desk Patient", mobile="9876500088",
                         allergies_other="Smuggled", medical_conditions="Diabetes", is_pregnant="on")
    patient = db.get_patient(p)
    assert patient["allergies_other"] == ""
    assert patient["medical_conditions_json"] == "[]"
    assert patient["is_pregnant"] == 0


def test_receptionist_dashboard_lists_followups_without_case_links_and_can_mark_done(logged_in_client, clinic):
    client = _as(logged_in_client, "receptionist")
    body = client.get("/dashboard").data.decode()
    assert "Crown upper left" in body and "Call about crown fit" in body
    assert f"/cases/{clinic['case_id']}\"" not in body

    token = get_csrf(client, "/dashboard")
    resp = client.post(f"/cases/{clinic['case_id']}/followup/done", data={"next": "dashboard", "csrf_token": token})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/dashboard")
    assert db.get_case(clinic["case_id"])["follow_up_date"] == ""


def test_receptionist_tracks_lab_work(logged_in_client, clinic):
    client = _as(logged_in_client, "receptionist")
    body = client.get("/lab-work").data.decode()
    assert "PFM crown 26" in body and "Smile Lab" in body and "Crown upper left" in body
    assert "Lab Work" in client.get("/dashboard").data.decode()  # in the menu

    token = get_csrf(client, "/lab-work")
    resp = client.post(f"/lab-reqs/{clinic['lab_req_id']}/update", data={
        "status": "Delayed", "expected_return": "2030-01-15", "received_date": "", "notes": "Lab called",
        "next": "lab_work", "csrf_token": token,
    })
    assert resp.status_code == 302 and "/lab-work" in resp.headers["Location"]
    req = db.get_lab_req(clinic["lab_req_id"])
    assert (req["status"], req["expected_return"], req["notes"]) == ("Delayed", "2030-01-15", "Lab called")

    # Received work drops off the default view but stays under "All".
    client.post(f"/lab-reqs/{clinic['lab_req_id']}/update", data={
        "status": "Received", "received_date": date.today().isoformat(), "notes": "", "next": "lab_work",
        "csrf_token": token,
    })
    assert "PFM crown 26" not in client.get("/lab-work").data.decode()
    assert "PFM crown 26" in client.get("/lab-work?view=all").data.decode()


def test_case_page_lab_update_keeps_expected_return(logged_in_client, clinic):
    db.update_lab_req(clinic["lab_req_id"], "Sent", "", "", expected_return="2030-02-01")
    token = get_csrf(logged_in_client, f"/cases/{clinic['case_id']}")
    logged_in_client.post(f"/lab-reqs/{clinic['lab_req_id']}/update",
                          data={"status": "Delayed", "received_date": "", "notes": "", "csrf_token": token})
    assert db.get_lab_req(clinic["lab_req_id"])["expected_return"] == "2030-02-01"


def test_receptionist_appointment_page_offers_no_case_buttons(logged_in_client, clinic):
    from tests.test_appointments import _book_appointment
    _book_appointment(logged_in_client, clinic["patient_id"])
    appt_id = db.list_appointments_for_patient(clinic["patient_id"])[0]["id"]
    client = _as(logged_in_client, "receptionist")
    body = client.get(f"/appointments/{appt_id}/edit").data.decode()
    assert "New Case for this Appointment" not in body
    assert client.get("/appointments/").status_code in (200, 302)


def test_receptionist_keeps_privacy_requests(logged_in_client, clinic):
    client = _as(logged_in_client, "receptionist")
    assert client.get("/data-requests").status_code == 200
    assert client.get(f"/patients/{clinic['patient_id']}/data-requests/new").status_code == 200


# ── Guest doctor ──────────────────────────────────────────────────────────

def test_guest_doctor_works_on_patients_and_cases(logged_in_client, clinic):
    client = _as(logged_in_client, "guest_doctor")
    c = clinic["case_id"]
    body = client.get(f"/cases/{c}").data.decode()
    assert "Secret-clinical-note" in body
    assert "Penicillin-XYZ" in client.get(f"/patients/{clinic['patient_id']}").data.decode()
    assert client.get(f"/patients/{clinic['patient_id']}/dental-chart").status_code == 200

    token = get_csrf(client, f"/cases/{c}")
    assert client.post(f"/cases/{c}/visit-notes", data={"note": "Guest note", "csrf_token": token}).status_code == 302
    assert any(n["note"].startswith("Guest note") for n in db.list_visit_notes_for_case(c))


def test_guest_doctor_blocked_from_settings_privacy_financials_reports_analytics(logged_in_client, clinic):
    client = _as(logged_in_client, "guest_doctor")
    for url in ("/settings/", "/users/", "/backup/", "/audit-log/", "/doctors/", "/procedure-types/",
                "/data-requests", f"/patients/{clinic['patient_id']}/data-requests/new",
                "/reports/", "/reports/report.pdf", "/analytics/", "/financial-assessment/",
                "/financial-assessment/monthly"):
        assert client.get(url).status_code == 403, url

    token = get_csrf(client, "/dashboard")
    assert client.post("/attachments/1/delete", data={"csrf_token": token}).status_code == 403
    assert client.post(f"/cases/{clinic['case_id']}/attachments/clear",
                       data={"reason": "x", "csrf_token": token}).status_code == 403


def test_guest_doctor_menu_and_patient_page_hide_restricted_areas(logged_in_client, clinic):
    db.create_data_request(clinic["patient_id"], "Access", "copy please")
    client = _as(logged_in_client, "guest_doctor")
    dash = client.get("/dashboard").data.decode()
    for path in ("/data-requests", "/reports/", "/analytics/", "/financial-assessment/", "/settings/"):
        assert f'href="{path}"' not in dash, path
    assert "Restricted" in dash  # outstanding-balance tile
    patient = client.get(f"/patients/{clinic['patient_id']}").data.decode()
    assert "New Privacy Request" not in patient
    assert "Lab Work" in dash


def test_guest_doctor_needs_two_step_when_required_for_doctors(app):
    with app.app_context():
        db.set_setting("require_two_factor", "1")
        assert auth.two_factor_required_for("guest_doctor")
        assert not auth.two_factor_required_for("receptionist")


def test_users_page_offers_guest_doctor(logged_in_client):
    assert "Guest doctor" in logged_in_client.get("/users/new").data.decode()
    _create_user(logged_in_client, "visiting1", "guest_doctor")
    assert next(u for u in db.list_users() if u["username"] == "visiting1")["role"] == "guest_doctor"
    assert "Guest doctor" in logged_in_client.get("/users/").data.decode()
