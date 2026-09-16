import re

from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def _case_for(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url


def _details_tag(body):
    match = re.search(r'<details id="referrals-details"[^>]*>', body)
    return match.group(0)


def test_referrals_collapsed_by_default(logged_in_client, patient_id):
    _case_id, case_url = _case_for(logged_in_client, patient_id)
    resp = logged_in_client.get(case_url)
    tag = _details_tag(resp.data.decode())
    assert " open" not in tag
    assert b"\xe2\x96\xb6 Show" in resp.data  # ▶ Show


def test_referrals_auto_open_when_referrals_exist(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/referrals",
        data={
            "referral_date": "2026-02-01",
            "referred_to": "Dr. Endo Specialist",
            "speciality": "Endodontics",
            "reason": "Complex root canal",
            "csrf_token": token,
        },
    )

    resp = logged_in_client.get(case_url)
    tag = _details_tag(resp.data.decode())
    assert " open" in tag
    assert b"\xe2\x96\xbc Hide" in resp.data  # ▼ Hide
    assert b"Dr. Endo Specialist" in resp.data
    assert b"Endodontics" in resp.data


def test_referral_requires_referred_to_and_reason(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/referrals",
        data={"referral_date": "2026-02-01", "referred_to": "", "reason": "", "csrf_token": token},
    )
    assert db.list_referrals_for_case(case_id) == []


def test_delete_referral(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/referrals",
        data={
            "referral_date": "2026-02-01",
            "referred_to": "Dr. Endo Specialist",
            "reason": "Complex root canal",
            "csrf_token": token,
        },
    )
    ref_id = db.list_referrals_for_case(case_id)[0]["id"]

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(f"/referrals/{ref_id}/delete", data={"csrf_token": token})
    assert resp.status_code == 302
    assert db.list_referrals_for_case(case_id) == []
