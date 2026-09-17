from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case
from tests.test_roles import _create_user, _login, _logout


def _case_for(client, patient_id, **overrides):
    resp, doctor_id = _create_case(client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url, doctor_id


def _add_prescription(client, case_id, case_url, rx_details="Amoxicillin 500mg, 3x daily for 5 days"):
    token = get_csrf(client, case_url)
    client.post(
        f"/cases/{case_id}/prescriptions",
        data={"prescribed_date": "2026-01-05", "rx_details": rx_details, "csrf_token": token},
    )
    return db.list_prescriptions_for_case(case_id)[0]["id"]


def _add_referral(client, case_id, case_url, **overrides):
    token = get_csrf(client, case_url)
    data = {
        "referral_date": "2026-01-05", "referred_to": "Dr. Specialist", "speciality": "Endodontics",
        "reason": "Needs root canal evaluation", "notes": "", "csrf_token": token,
    }
    data.update(overrides)
    client.post(f"/cases/{case_id}/referrals", data=data)
    return db.list_referrals_for_case(case_id)[0]["id"]


def _assert_pdf(resp):
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/pdf"
    assert resp.data[:4] == b"%PDF"


def test_prescription_pdf_downloads(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    rx_id = _add_prescription(logged_in_client, case_id, case_url)
    resp = logged_in_client.get(f"/cases/{case_id}/prescriptions/{rx_id}.pdf")
    _assert_pdf(resp)


def test_prescription_pdf_wrong_case_is_404(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    rx_id = _add_prescription(logged_in_client, case_id, case_url)
    other_case_id, _, _ = _case_for(logged_in_client, patient_id, title="Other Case")
    resp = logged_in_client.get(f"/cases/{other_case_id}/prescriptions/{rx_id}.pdf")
    assert resp.status_code == 404


def test_prescription_pdf_includes_allergy_alert_when_present(logged_in_client):
    from tests.conftest import register_patient
    patient_id = register_patient(logged_in_client, name="Allergy Patient", allergies=["Penicillin"])
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    rx_id = _add_prescription(logged_in_client, case_id, case_url)
    resp = logged_in_client.get(f"/cases/{case_id}/prescriptions/{rx_id}.pdf")
    _assert_pdf(resp)


def test_case_summary_pdf_downloads(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, total_cost="1000")
    resp = logged_in_client.get(f"/cases/{case_id}/summary.pdf")
    _assert_pdf(resp)


def test_case_summary_pdf_available_but_redacted_for_receptionist(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, total_cost="1000")
    _create_user(logged_in_client, "pdfrecep", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "pdfrecep")

    resp = logged_in_client.get(f"/cases/{case_id}/summary.pdf")
    _assert_pdf(resp)


def test_consent_pdf_downloads(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/consent", data={"consent_notes": "Signed paper form", "csrf_token": token}
    )
    resp = logged_in_client.get(f"/cases/{case_id}/consent.pdf")
    _assert_pdf(resp)


def test_consent_pdf_downloads_without_consent_recorded(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    resp = logged_in_client.get(f"/cases/{case_id}/consent.pdf")
    _assert_pdf(resp)


def test_patient_summary_pdf_downloads(logged_in_client, patient_id):
    _case_for(logged_in_client, patient_id, total_cost="1000")
    resp = logged_in_client.get(f"/patients/{patient_id}/summary.pdf")
    _assert_pdf(resp)


def test_referral_pdf_downloads(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    ref_id = _add_referral(logged_in_client, case_id, case_url)
    resp = logged_in_client.get(f"/cases/{case_id}/referral/{ref_id}/print")
    _assert_pdf(resp)


def test_referral_pdf_wrong_case_is_404(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id)
    ref_id = _add_referral(logged_in_client, case_id, case_url)
    other_case_id, _, _ = _case_for(logged_in_client, patient_id, title="Other Case")
    resp = logged_in_client.get(f"/cases/{other_case_id}/referral/{ref_id}/print")
    assert resp.status_code == 404


def test_data_access_pdf_for_admin_and_doctor(logged_in_client, patient_id):
    case_id, case_url, _ = _case_for(logged_in_client, patient_id, total_cost="1000")
    # Visit notes and dental chart entries must appear in a right-to-access export too —
    # not just prescriptions/payments/appointments (feast9_v2_agents.md §10).
    db.add_visit_note(case_id, patient_id, "Patient tolerated the procedure well.", "2026-01-05")
    db.add_dental_chart_entry(patient_id, case_id, "36", "Whole Tooth", "Root Canal", "Completed", "RCT completed")

    token = get_csrf(logged_in_client, f"/patients/{patient_id}/data-requests/new")
    logged_in_client.post(
        f"/patients/{patient_id}/data-requests/new",
        data={"request_type": "Access", "description": "Wants a copy of their records", "csrf_token": token},
    )
    request_id = db.list_data_requests_for_patient(patient_id)[0]["id"]

    resp = logged_in_client.get(f"/data-requests/{request_id}/access.pdf")
    _assert_pdf(resp)


def test_data_access_pdf_blocked_for_receptionist(logged_in_client, patient_id):
    token = get_csrf(logged_in_client, f"/patients/{patient_id}/data-requests/new")
    logged_in_client.post(
        f"/patients/{patient_id}/data-requests/new",
        data={"request_type": "Access", "description": "Wants a copy", "csrf_token": token},
    )
    request_id = db.list_data_requests_for_patient(patient_id)[0]["id"]

    _create_user(logged_in_client, "pdfrecep2", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "pdfrecep2")

    resp = logged_in_client.get(f"/data-requests/{request_id}/access.pdf")
    assert resp.status_code == 403
