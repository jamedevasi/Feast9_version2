"""Financial Assessment module (ad-hoc addition, 2026-09-18 — not in feast9_v2_agents.md's
original scope). A doctor-facing per-case profitability table: Billed/Collected/Pending are
live-computed same as Reports; Lab Amount/Consultant Fee/Misc Expense are editable and
persisted per case; Profit = Billed − expenses, per the user's explicit choice over a
collected-based formula. Financial data — receptionist must get 403 everywhere, same rule
as Reports/Analytics/payments."""
from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case
from tests.test_reports import _add_payment
from tests.test_roles import _create_user, _login, _logout


def _case_for(client, patient_id, **overrides):
    resp, doctor_id = _create_case(client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url


def test_receptionist_forbidden_everywhere(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id, title="Recep Blocked", total_cost=1000)
    _create_user(logged_in_client, "recepfin", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recepfin")

    assert logged_in_client.get("/financial-assessment/").status_code == 403
    assert logged_in_client.get("/financial-assessment/export.xlsx").status_code == 403

    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post(
        "/financial-assessment/save",
        data={"csrf_token": token, "case_ids": str(case_id), "lab_amount_" + str(case_id): "50"},
    )
    assert resp.status_code == 403


def test_admin_and_doctor_can_view(logged_in_client, patient_id):
    _case_for(logged_in_client, patient_id, title="Visible Case", total_cost=500)
    resp = logged_in_client.get("/financial-assessment/")
    assert resp.status_code == 200
    assert b"Visible Case" in resp.data

    _create_user(logged_in_client, "docfin", "doctor")
    _logout(logged_in_client)
    _login(logged_in_client, "docfin")
    resp = logged_in_client.get("/financial-assessment/")
    assert resp.status_code == 200


def test_billed_collected_pending_and_profit_computed(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, title="Profit Case", total_cost=1000)
    _add_payment(logged_in_client, case_id, case_url, 400)

    rows = db.list_financial_assessment_cases()
    row = next(r for r in rows if r["case_id"] == case_id)
    assert row["total_cost"] == 1000
    assert row["collected"] == 400
    assert row["pending"] == 600
    # No expenses entered yet — profit = billed - 0
    assert row["profit"] == 1000


def test_save_expenses_persists_and_recomputes_profit(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, title="Expense Case", total_cost=1000)
    _add_payment(logged_in_client, case_id, case_url, 1000)

    token = get_csrf(logged_in_client, "/financial-assessment/")
    resp = logged_in_client.post(
        "/financial-assessment/save",
        data={
            "csrf_token": token,
            "case_ids": str(case_id),
            f"lab_amount_{case_id}": "100",
            f"consultant_fee_{case_id}": "50",
            f"misc_expense_{case_id}": "25",
        },
    )
    assert resp.status_code == 302

    rows = db.list_financial_assessment_cases()
    row = next(r for r in rows if r["case_id"] == case_id)
    assert row["lab_amount"] == 100
    assert row["consultant_fee"] == 50
    assert row["misc_expense"] == 25
    # profit = billed(1000) - expenses(175) — collected being 1000 (fully paid) is irrelevant to this formula
    assert row["profit"] == 825


def test_loss_case_flagged_in_html(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id, title="Loss Case", total_cost=100)

    token = get_csrf(logged_in_client, "/financial-assessment/")
    logged_in_client.post(
        "/financial-assessment/save",
        data={
            "csrf_token": token,
            "case_ids": str(case_id),
            f"lab_amount_{case_id}": "80",
            f"consultant_fee_{case_id}": "50",
            f"misc_expense_{case_id}": "0",
        },
    )
    resp = logged_in_client.get("/financial-assessment/")
    assert b"profit-loss" in resp.data
    row = next(r for r in db.list_financial_assessment_cases() if r["case_id"] == case_id)
    assert row["profit"] == -30


def test_save_rejects_missing_csrf_token(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id, title="CSRF Case", total_cost=100)
    resp = logged_in_client.post(
        "/financial-assessment/save",
        data={"case_ids": str(case_id), f"lab_amount_{case_id}": "999"},
    )
    assert resp.status_code == 400
    row = next(r for r in db.list_financial_assessment_cases() if r["case_id"] == case_id)
    assert row["lab_amount"] == 0


def test_save_is_audited(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id, title="Audited Case", total_cost=200)
    token = get_csrf(logged_in_client, "/financial-assessment/")
    logged_in_client.post(
        "/financial-assessment/save",
        data={"csrf_token": token, "case_ids": str(case_id), f"lab_amount_{case_id}": "20"},
    )
    actions = [e["action"] for e in db.list_audit_log()]
    assert "case_financial_expenses_updated" in actions


def test_date_filter(logged_in_client, patient_id):
    _case_for(logged_in_client, patient_id, title="Any Date Case", total_cost=100)
    resp = logged_in_client.get("/financial-assessment/?from=2000-01-01&to=2000-01-02")
    assert resp.status_code == 200
    assert b"Any Date Case" not in resp.data

    resp_all = logged_in_client.get("/financial-assessment/")
    assert b"Any Date Case" in resp_all.data


def test_excel_export_returns_xlsx(logged_in_client, patient_id):
    _case_for(logged_in_client, patient_id, title="Export Case", total_cost=100)
    resp = logged_in_client.get("/financial-assessment/export.xlsx")
    assert resp.status_code == 200
    assert resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
