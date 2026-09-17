from tests.conftest import get_csrf, register_patient
from tests.test_cases import _create_case


def test_allergy_banner_shown_for_allergic_patient(logged_in_client):
    patient_id = register_patient(logged_in_client, name="Allergic Patient", allergies="Penicillin")

    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    detail_resp = logged_in_client.get(case_url)
    assert b"Allergy alert" in detail_resp.data
    assert b"Penicillin" in detail_resp.data


def test_no_allergy_banner_for_patient_without_allergies(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    detail_resp = logged_in_client.get(case_url)
    assert b"Allergy alert" not in detail_resp.data


def test_add_prescription(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])

    token = get_csrf(logged_in_client, case_url)
    add_resp = logged_in_client.post(
        f"/cases/{case_id}/prescriptions",
        data={"rx_details": "Amoxicillin 500mg TID x5d", "prescribed_date": "2026-01-20", "csrf_token": token},
    )
    assert add_resp.status_code == 302

    detail_resp = logged_in_client.get(case_url)
    assert b"Amoxicillin 500mg TID x5d" in detail_resp.data


def test_prescription_appears_in_patient_history(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])

    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/prescriptions",
        data={"rx_details": "Amoxicillin 500mg TID x5d", "prescribed_date": "2026-01-20", "csrf_token": token},
    )

    patient_resp = logged_in_client.get(f"/patients/{patient_id}")
    assert b"Prescription History" in patient_resp.data
    assert b"Amoxicillin 500mg TID x5d" in patient_resp.data
    assert b"Root Canal" in patient_resp.data  # linked back to the originating case


def test_patient_with_no_prescriptions_shows_empty_state(logged_in_client, patient_id):
    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert b"No prescriptions recorded yet." in resp.data
