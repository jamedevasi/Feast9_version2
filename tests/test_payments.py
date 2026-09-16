from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def _case_for(logged_in_client, patient_id, **overrides):
    resp, _ = _create_case(logged_in_client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url


def test_balance_starts_at_full_cost(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id, total_cost="5000")
    assert db.get_case_balance(case_id) == 5000


def test_add_payment_reduces_balance(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, total_cost="5000")
    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": "2026-01-10", "amount": "2000", "method": "UPI", "csrf_token": token},
    )
    assert resp.status_code == 302
    assert db.get_case_balance(case_id) == 3000

    detail_resp = logged_in_client.get(case_url)
    assert b"3000.00" in detail_resp.data


def test_zero_or_negative_payment_rejected(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, total_cost="5000")
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": "2026-01-10", "amount": "0", "csrf_token": token},
    )
    assert db.list_payments_for_case(case_id) == []
    assert db.get_case_balance(case_id) == 5000


def test_revise_cost_creates_revision_and_updates_balance(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, total_cost="5000")
    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/revise-cost",
        data={"new_cost": "6500", "reason": "Added a crown", "csrf_token": token},
    )
    assert resp.status_code == 302

    revisions = db.list_cost_revisions_for_case(case_id)
    assert len(revisions) == 1
    assert revisions[0]["old_cost"] == 5000
    assert revisions[0]["new_cost"] == 6500
    assert revisions[0]["reason"] == "Added a crown"
    assert db.get_case_balance(case_id) == 6500

    case = db.get_case(case_id)
    assert case["total_cost"] == 6500


def test_revise_cost_with_same_value_creates_no_revision(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, total_cost="5000")
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/revise-cost",
        data={"new_cost": "5000", "reason": "No change really", "csrf_token": token},
    )
    assert db.list_cost_revisions_for_case(case_id) == []


def test_revise_cost_requires_reason(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, total_cost="5000")
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/revise-cost",
        data={"new_cost": "6000", "reason": "", "csrf_token": token},
    )
    assert db.list_cost_revisions_for_case(case_id) == []
    assert db.get_case(case_id)["total_cost"] == 5000
