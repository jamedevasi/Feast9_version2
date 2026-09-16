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
