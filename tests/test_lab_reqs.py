from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def _case_for(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url


def test_add_lab_req_defaults_to_sent(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/lab-reqs",
        data={
            "lab_name": "City Dental Lab",
            "work_description": "Crown fabrication",
            "sent_date": "2026-01-10",
            "expected_return": "2026-01-20",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 302

    reqs = db.list_lab_reqs_for_case(case_id)
    assert len(reqs) == 1
    assert reqs[0]["status"] == "Sent"
    assert reqs[0]["lab_name"] == "City Dental Lab"

    detail_resp = logged_in_client.get(case_url)
    assert b"Crown fabrication" in detail_resp.data
    assert b"City Dental Lab" in detail_resp.data


def test_work_description_required(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/lab-reqs",
        data={"work_description": "", "sent_date": "2026-01-10", "csrf_token": token},
    )
    assert db.list_lab_reqs_for_case(case_id) == []


def test_update_lab_req_status_and_received_date(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/lab-reqs",
        data={"work_description": "Bridge", "sent_date": "2026-01-10", "csrf_token": token},
    )
    req_id = db.list_lab_reqs_for_case(case_id)[0]["id"]

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/lab-reqs/{req_id}/update",
        data={"status": "Received", "received_date": "2026-01-18", "notes": "Good fit", "csrf_token": token},
    )
    assert resp.status_code == 302

    updated = db.get_lab_req(req_id)
    assert updated["status"] == "Received"
    assert updated["received_date"] == "2026-01-18"
    assert updated["notes"] == "Good fit"


def test_delete_lab_req(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/lab-reqs",
        data={"work_description": "Bridge", "sent_date": "2026-01-10", "csrf_token": token},
    )
    req_id = db.list_lab_reqs_for_case(case_id)[0]["id"]

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(f"/lab-reqs/{req_id}/delete", data={"csrf_token": token})
    assert resp.status_code == 302
    assert db.list_lab_reqs_for_case(case_id) == []
