import re

from tests.conftest import get_csrf


def _register_patient(client, **overrides):
    token = get_csrf(client, "/patients/new")
    data = {
        "name": "Test Patient",
        "date_of_birth": "1990-01-01",
        "sex": "Female",
        "mobile": "9876543210",
        "email": "test@example.com",
        "address": "1 Test Street",
        "dpdp_notice_accepted": "on",
        "csrf_token": token,
    }
    data.update(overrides)
    return client.post("/patients/new", data=data)


def test_pages_return_200_after_login(logged_in_client):
    for path in ["/dashboard", "/patients/"]:
        resp = logged_in_client.get(path)
        assert resp.status_code == 200


def test_dpdp_notice_required(logged_in_client):
    resp = _register_patient(logged_in_client, dpdp_notice_accepted="")
    assert resp.status_code == 200
    assert b"Data Processing Notice must be accepted" in resp.data


def test_register_patient_and_appears_in_list(logged_in_client):
    resp = _register_patient(logged_in_client)
    assert resp.status_code == 302

    list_resp = logged_in_client.get("/patients/")
    assert b"Test Patient" in list_resp.data


def test_patient_search_matches_mobile(logged_in_client):
    _register_patient(logged_in_client, name="Findable Patient", mobile="9998887776")
    resp = logged_in_client.get("/patients/?q=9998887776")
    assert b"Findable Patient" in resp.data


def test_guardian_required_for_minor(logged_in_client):
    resp = _register_patient(
        logged_in_client,
        name="Minor Patient",
        date_of_birth="2015-01-01",
        guardian_name="",
        guardian_mobile="",
    )
    assert resp.status_code == 200
    assert b"Guardian" in resp.data


def test_guardian_accepted_for_minor(logged_in_client):
    resp = _register_patient(
        logged_in_client,
        name="Minor Patient Two",
        date_of_birth="2015-01-01",
        guardian_name="Parent Name",
        guardian_relation="Mother",
        guardian_mobile="9812345678",
    )
    assert resp.status_code == 302


def test_invalid_mobile_rejected(logged_in_client):
    resp = _register_patient(logged_in_client, name="Bad Mobile Patient", mobile="12345")
    assert resp.status_code == 200
    assert b"Mobile number looks invalid" in resp.data


def test_patient_detail_section_order(logged_in_client):
    _register_patient(logged_in_client, name="Order Patient")
    list_resp = logged_in_client.get("/patients/?q=Order Patient")
    match = re.search(rb'/patients/(\d+)"', list_resp.data)
    assert match
    patient_id = match.group(1).decode()

    detail_resp = logged_in_client.get(f"/patients/{patient_id}")
    body = detail_resp.data.decode()
    # Match section headings specifically (<h2>...</h2>), not the top nav bar, which also
    # contains an "Appointments" link that appears earlier in the raw HTML than the sections.
    assert (
        body.index("<h2>Medical Alerts</h2>")
        < body.index("<h2>Active Treatment Cases</h2>")
        < body.index("<h2>Appointments</h2>")
        < body.index("Contact Details")
    )
