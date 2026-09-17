from app import db
from tests.conftest import get_csrf
from tests.test_roles import _create_user, _login, _logout


def _add_doctor(client, name="Dr. New Hire", color="#123456"):
    token = get_csrf(client, "/doctors/")
    return client.post("/doctors/new", data={"name": name, "color": color, "csrf_token": token})


def _add_procedure_type(client, name="Whitening"):
    token = get_csrf(client, "/procedure-types/")
    return client.post("/procedure-types/new", data={"name": name, "csrf_token": token})


def test_admin_can_add_and_list_doctor(logged_in_client):
    resp = _add_doctor(logged_in_client, "Dr. Anjali Rao", "#2f9e44")
    assert resp.status_code == 302

    doctors = db.list_doctors(active_only=False)
    assert any(d["name"] == "Dr. Anjali Rao" and d["color"] == "#2f9e44" for d in doctors)

    list_resp = logged_in_client.get("/doctors/")
    assert b"Dr. Anjali Rao" in list_resp.data


def test_doctor_name_required(logged_in_client):
    resp = _add_doctor(logged_in_client, name="")
    assert resp.status_code == 302
    assert db.list_doctors(active_only=False) == []


def test_deactivate_and_reactivate_doctor(logged_in_client):
    _add_doctor(logged_in_client, "Dr. Temp")
    doctor = next(d for d in db.list_doctors(active_only=False) if d["name"] == "Dr. Temp")

    token = get_csrf(logged_in_client, "/doctors/")
    logged_in_client.post(f"/doctors/{doctor['id']}/deactivate", data={"csrf_token": token})
    assert db.get_doctor(doctor["id"])["is_active"] == 0
    assert doctor["id"] not in [d["id"] for d in db.list_doctors()]

    token = get_csrf(logged_in_client, "/doctors/")
    logged_in_client.post(f"/doctors/{doctor['id']}/activate", data={"csrf_token": token})
    assert db.get_doctor(doctor["id"])["is_active"] == 1


def test_deactivated_doctor_hidden_from_new_case_form(logged_in_client, patient_id):
    _add_doctor(logged_in_client, "Dr. Hideaway")
    doctor = next(d for d in db.list_doctors(active_only=False) if d["name"] == "Dr. Hideaway")

    resp = logged_in_client.get(f"/patients/{patient_id}/cases/new")
    assert b"Dr. Hideaway" in resp.data

    token = get_csrf(logged_in_client, "/doctors/")
    logged_in_client.post(f"/doctors/{doctor['id']}/deactivate", data={"csrf_token": token})
    logged_in_client.get("/dashboard")  # consume the flash message before re-checking the form

    resp2 = logged_in_client.get(f"/patients/{patient_id}/cases/new")
    assert b"Dr. Hideaway" not in resp2.data


def test_admin_can_add_and_list_procedure_type(logged_in_client):
    resp = _add_procedure_type(logged_in_client, "Whitening")
    assert resp.status_code == 302
    assert any(p["name"] == "Whitening" for p in db.list_procedure_types(active_only=False))

    list_resp = logged_in_client.get("/procedure-types/")
    assert b"Whitening" in list_resp.data


def test_procedure_type_name_required(logged_in_client):
    resp = _add_procedure_type(logged_in_client, name="")
    assert resp.status_code == 302
    assert db.list_procedure_types(active_only=False) == []


def test_deactivate_and_reactivate_procedure_type(logged_in_client):
    _add_procedure_type(logged_in_client, "Temp Procedure")
    pt = next(p for p in db.list_procedure_types(active_only=False) if p["name"] == "Temp Procedure")

    token = get_csrf(logged_in_client, "/procedure-types/")
    logged_in_client.post(f"/procedure-types/{pt['id']}/deactivate", data={"csrf_token": token})
    assert db.get_procedure_type(pt["id"])["is_active"] == 0
    assert pt["id"] not in [p["id"] for p in db.list_procedure_types()]

    token = get_csrf(logged_in_client, "/procedure-types/")
    logged_in_client.post(f"/procedure-types/{pt['id']}/activate", data={"csrf_token": token})
    assert db.get_procedure_type(pt["id"])["is_active"] == 1


def test_doctor_and_procedure_type_changes_are_audited(logged_in_client):
    _add_doctor(logged_in_client, "Dr. Audit Test")
    doctor = next(d for d in db.list_doctors(active_only=False) if d["name"] == "Dr. Audit Test")
    token = get_csrf(logged_in_client, "/doctors/")
    logged_in_client.post(f"/doctors/{doctor['id']}/deactivate", data={"csrf_token": token})

    _add_procedure_type(logged_in_client, "Audit Procedure")

    actions = [e["action"] for e in db.list_audit_log()]
    assert "doctor_created" in actions
    assert "doctor_deactivated" in actions
    assert "procedure_type_created" in actions


def test_settings_hub_links_to_doctors_and_case_types(logged_in_client):
    resp = logged_in_client.get("/settings/")
    assert resp.status_code == 200
    assert b'href="/doctors/"' in resp.data
    assert b'href="/procedure-types/"' in resp.data


def test_non_admin_blocked_from_doctor_and_settings_management(logged_in_client, patient_id):
    _create_user(logged_in_client, "docrole", "doctor")
    _logout(logged_in_client)
    _login(logged_in_client, "docrole")

    assert logged_in_client.get("/settings/").status_code == 403
    assert logged_in_client.get("/doctors/").status_code == 403
    assert logged_in_client.get("/procedure-types/").status_code == 403

    dash = logged_in_client.get("/dashboard")
    assert b'href="/settings/"' not in dash.data
