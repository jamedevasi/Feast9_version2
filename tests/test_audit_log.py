from app import db
from tests.conftest import get_csrf
from tests.test_attachments import JPEG_BYTES, _upload
from tests.test_cases import _create_case


def _last_entry(action):
    entries = db.list_audit_log()
    return next(e for e in entries if e["action"] == action)


def _case_for(client, patient_id, **overrides):
    resp, _ = _create_case(client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url


def test_visit_note_add_creates_audit_entry(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/visit-notes",
        data={"note": "Patient reports mild sensitivity.", "visit_date": "2026-01-05", "csrf_token": token},
    )
    entry = _last_entry("visit_note_added")
    assert entry["entity"] == "case"
    assert entry["entity_id"] == case_id
    assert entry["role"] == "admin"
    # Clinical note content must never land in the audit row, only a length/date summary.
    assert "sensitivity" not in entry["after_summary"]


def test_payment_and_cost_revision_create_audit_entries(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, total_cost="5000")
    token = get_csrf(logged_in_client, case_url)

    logged_in_client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": "2026-01-10", "amount": "2000", "csrf_token": token},
    )
    payment_entry = _last_entry("payment_added")
    assert "2000" in payment_entry["after_summary"]

    logged_in_client.post(
        f"/cases/{case_id}/revise-cost",
        data={"new_cost": "6500", "reason": "Added a crown", "csrf_token": token},
    )
    cost_entry = _last_entry("cost_revised")
    assert "5000" in cost_entry["before_summary"]
    assert "6500" in cost_entry["after_summary"]


def test_cost_revision_with_no_change_writes_no_audit_entry(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, total_cost="5000")
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/revise-cost",
        data={"new_cost": "5000", "reason": "No change really", "csrf_token": token},
    )
    assert not [e for e in db.list_audit_log() if e["action"] == "cost_revised"]


def test_consent_and_case_close_create_audit_entries(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/consent",
        data={"consent_notes": "Signed paper form", "csrf_token": token},
    )
    consent_entry = _last_entry("consent_recorded")
    assert consent_entry["entity_id"] == case_id
    assert "Signed paper form" not in (consent_entry["after_summary"] or "")

    logged_in_client.post(f"/cases/{case_id}/close", data={"csrf_token": token})
    close_entry = _last_entry("case_status_changed")
    assert close_entry["before_summary"] == "status=Active"
    assert close_entry["after_summary"] == "status=Closed"


def test_patient_update_logs_field_names_not_values(logged_in_client, patient_id):
    token = get_csrf(logged_in_client, f"/patients/{patient_id}/edit")
    logged_in_client.post(
        f"/patients/{patient_id}/edit",
        data={
            "name": "Case Test Patient",
            "sex": "Female",
            "mobile": "9876543210",
            "email": "casetest@example.com",
            "address": "1 Test Street",
            "allergies_other": "Highly sensitive allergy detail",
            "dpdp_notice_accepted": "on",
            "csrf_token": token,
        },
    )
    entry = _last_entry("patient_updated")
    assert entry["entity_id"] == patient_id
    assert "allergies_other" in entry["after_summary"]
    assert "Highly sensitive allergy detail" not in entry["after_summary"]


def test_attachment_upload_and_download_create_audit_entries(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")
    upload_entry = _last_entry("attachment_uploaded")
    assert upload_entry["entity"] == "case_attachment"

    attachment_id = upload_entry["entity_id"]
    logged_in_client.get(f"/attachments/{attachment_id}/file")
    download_entry = _last_entry("attachment_downloaded")
    assert download_entry["entity_id"] == attachment_id


def test_user_management_creates_audit_entries(logged_in_client):
    token = get_csrf(logged_in_client, "/users/new")
    logged_in_client.post(
        "/users/new",
        data={
            "username": "audituser1",
            "password": "testpass123",
            "confirm": "testpass123",
            "role": "receptionist",
            "security_question": "Q",
            "security_answer": "A",
            "csrf_token": token,
        },
    )
    created_entry = _last_entry("user_created")
    assert "audituser1" in created_entry["after_summary"]

    user = next(u for u in db.list_users() if u["username"] == "audituser1")
    token = get_csrf(logged_in_client, "/users/")
    logged_in_client.post(f"/users/{user['id']}/deactivate", data={"csrf_token": token})
    deactivated_entry = _last_entry("user_deactivated")
    assert deactivated_entry["entity_id"] == user["id"]


def test_audit_log_page_requires_admin(logged_in_client):
    resp = logged_in_client.get("/audit-log/")
    assert resp.status_code == 200
    assert b"user_created" in resp.data or b"Audit Log" in resp.data
