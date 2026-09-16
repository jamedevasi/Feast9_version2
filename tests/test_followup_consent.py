from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def _case_for(logged_in_client, patient_id, **overrides):
    resp, _ = _create_case(logged_in_client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url


def test_set_and_clear_followup(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/followup",
        data={"follow_up_date": "2026-03-01", "next_action_note": "Review healing", "csrf_token": token},
    )
    assert resp.status_code == 302
    case = db.get_case(case_id)
    assert case["follow_up_date"] == "2026-03-01"
    assert case["next_action_note"] == "Review healing"

    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/followup",
        data={"follow_up_date": "", "next_action_note": "", "csrf_token": token},
    )
    case = db.get_case(case_id)
    assert case["follow_up_date"] == ""
    assert case["next_action_note"] == ""


def test_active_case_without_consent_shows_warning(logged_in_client, patient_id):
    _case_id, case_url = _case_for(logged_in_client, patient_id)
    resp = logged_in_client.get(case_url)
    assert b"card-warning" in resp.data
    assert b"No consent recorded for this active case" in resp.data


def test_recording_consent_clears_warning(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/consent",
        data={"consent_notes": "Signed paper form on file", "csrf_token": token},
    )
    assert resp.status_code == 302

    detail_resp = logged_in_client.get(case_url)
    assert b"card-warning" not in detail_resp.data
    assert b"Signed paper form on file" in detail_resp.data

    case = db.get_case(case_id)
    assert case["consent_recorded"] == 1
    assert case["consent_recorded_at"] != ""


def test_closed_case_never_shows_consent_warning_even_without_consent(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(f"/cases/{case_id}/close", data={"csrf_token": token})

    resp = logged_in_client.get(case_url)
    assert b"card-warning" not in resp.data
