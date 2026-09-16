from app import db
from tests.conftest import get_csrf


def _seed_doctor():
    return db.add_doctor("Dr. Test Doctor", "#000000")


def _create_case(client, patient_id, **overrides):
    doctor_id = _seed_doctor()
    token = get_csrf(client, f"/patients/{patient_id}/cases/new")
    data = {
        "title": "Root Canal — Tooth 36",
        "doctor_id": str(doctor_id),
        "total_cost": "5000",
        "csrf_token": token,
    }
    data.update(overrides)
    resp = client.post(f"/patients/{patient_id}/cases/new", data=data)
    return resp, doctor_id


def test_create_case_and_redirect(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    assert resp.status_code == 302
    assert "/cases/" in resp.headers["Location"]


def test_case_requires_title_and_doctor(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id, title="", doctor_id="")
    assert resp.status_code == 200
    assert b"Case title is required" in resp.data
    assert b"doctor must be selected" in resp.data


def test_case_appears_on_patient_page(logged_in_client, patient_id):
    _create_case(logged_in_client, patient_id, title="Scaling Case")
    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert b"Scaling Case" in resp.data
    assert b"No treatment cases yet" not in resp.data


def test_case_detail_section_order(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id, title="Order Test Case")
    case_url = resp.headers["Location"]
    detail_resp = logged_in_client.get(case_url)
    body = detail_resp.data.decode()
    order = [
        "Consent Forms", "Visit Notes", "Prescriptions", "Clinical Attachments",
        "Lab Requisitions", "Referral Notes", "Payment Log",
        "Follow-up &amp; Next Action", "Cost History &amp; Revisions",
    ]
    positions = [body.index(s) for s in order]
    assert positions == sorted(positions)


def test_closed_at_only_set_on_explicit_close(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])

    case = db.get_case(case_id)
    assert case["status"] == "Active"
    assert case["closed_at"] == ""

    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(f"/cases/{case_id}/close", data={"csrf_token": token})

    case = db.get_case(case_id)
    assert case["status"] == "Closed"
    assert case["closed_at"] != ""


def test_edit_case_does_not_touch_status(logged_in_client, patient_id):
    resp, doctor_id = _create_case(logged_in_client, patient_id, title="Original Title")
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])

    token = get_csrf(logged_in_client, f"/cases/{case_id}/edit")
    edit_resp = logged_in_client.post(
        f"/cases/{case_id}/edit",
        data={"title": "Updated Title", "doctor_id": str(doctor_id), "csrf_token": token},
    )
    assert edit_resp.status_code == 302

    case = db.get_case(case_id)
    assert case["title"] == "Updated Title"
    assert case["status"] == "Active"


def test_case_detail_requires_login(client):
    resp = client.get("/cases/1")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_unknown_case_returns_404(logged_in_client):
    resp = logged_in_client.get("/cases/999")
    assert resp.status_code == 404
