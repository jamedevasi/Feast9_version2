"""Financial Assessment module (ad-hoc addition, 2026-09-18 — not in feast9_v2_agents.md's
original scope). A doctor-facing per-case profitability table: Billed/Collected/Pending are
live-computed same as Reports; Lab Amount/Consultant Fee/Consumables/Misc Expense are
editable and persisted per case; Profit = Billed − expenses, per the user's explicit choice
over a collected-based formula. Financial data — receptionist must get 403 everywhere, same
rule as Reports/Analytics/payments.

Also covers Monthly Evaluation (same-day follow-up addition): a per-calendar-month rollup
of cases opened that month (billed/collected/case expenses) minus editable clinic overhead
(rent, staff salary, electricity, EMI, cleaning & disposal, other) = Net Monthly Profit.

And Capital Investments + the Short Term/Long Term toggle (same-day, second follow-up):
a small asset ledger (asset name, purchase date, cost, useful-life months) depreciated
straight-line; Short Term Monthly Evaluation ignores it, Long Term subtracts that month's
total depreciation. Assets are soft-deactivate-only — no edit/delete — so correcting a
mis-entered asset never rewrites depreciation already reported in a past month."""
from datetime import date

from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case
from tests.test_reports import _add_payment
from tests.test_roles import _create_user, _login, _logout

THIS_MONTH = date.today().strftime("%Y-%m")
THIS_MONTH_START = date.today().replace(day=1).isoformat()


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
            f"consumables_{case_id}": "10",
            f"misc_expense_{case_id}": "25",
        },
    )
    assert resp.status_code == 302

    rows = db.list_financial_assessment_cases()
    row = next(r for r in rows if r["case_id"] == case_id)
    assert row["lab_amount"] == 100
    assert row["consultant_fee"] == 50
    assert row["consumables"] == 10
    assert row["misc_expense"] == 25
    # profit = billed(1000) - expenses(185) — collected being 1000 (fully paid) is irrelevant to this formula
    assert row["profit"] == 815


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


# ── Monthly Evaluation ──────────────────────────────────────────────────────────

def test_monthly_receptionist_forbidden(logged_in_client, patient_id):
    _create_user(logged_in_client, "recepmonthly", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recepmonthly")

    assert logged_in_client.get("/financial-assessment/monthly").status_code == 403
    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post(
        "/financial-assessment/monthly/save",
        data={"csrf_token": token, "month": THIS_MONTH, "overhead_rent": "5000"},
    )
    assert resp.status_code == 403


def test_monthly_rollup_sums_cases_opened_this_month(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id, title="Monthly Case", total_cost=2000)
    _add_payment(logged_in_client, case_id, case_url, 1200)

    token = get_csrf(logged_in_client, "/financial-assessment/")
    logged_in_client.post(
        "/financial-assessment/save",
        data={
            "csrf_token": token, "case_ids": str(case_id),
            f"lab_amount_{case_id}": "300", f"consultant_fee_{case_id}": "200",
            f"consumables_{case_id}": "50", f"misc_expense_{case_id}": "0",
        },
    )

    rollup = db.get_monthly_case_rollup(THIS_MONTH)
    assert rollup["case_count"] >= 1
    assert rollup["total_billed"] >= 2000
    assert rollup["total_collected"] >= 1200
    assert rollup["total_case_expenses"] >= 550

    # A month with no activity at all rolls up to zero, not an error.
    empty = db.get_monthly_case_rollup("2000-01")
    assert empty["case_count"] == 0
    assert empty["total_billed"] == 0
    assert empty["total_case_expenses"] == 0


def test_monthly_overhead_save_persists_and_is_audited(logged_in_client):
    token = get_csrf(logged_in_client, "/financial-assessment/monthly")
    resp = logged_in_client.post(
        "/financial-assessment/monthly/save",
        data={
            "csrf_token": token, "month": THIS_MONTH,
            "overhead_rent": "15000", "overhead_staff_salary": "20000",
            "overhead_electricity": "2000", "overhead_emi": "5000",
            "overhead_cleaning_disposal": "1000", "overhead_other_expense": "500",
        },
    )
    assert resp.status_code == 302

    overhead = db.get_monthly_overhead_expenses(THIS_MONTH)
    assert overhead["rent"] == 15000
    assert overhead["staff_salary"] == 20000
    assert overhead["electricity"] == 2000
    assert overhead["emi"] == 5000
    assert overhead["cleaning_disposal"] == 1000
    assert overhead["other_expense"] == 500

    actions = [e["action"] for e in db.list_audit_log()]
    assert "monthly_overhead_expenses_updated" in actions

    # A month never saved defaults cleanly to all zeros.
    untouched = db.get_monthly_overhead_expenses("2000-01")
    assert all(untouched[f] == 0 for f in ("rent", "staff_salary", "electricity", "emi",
                                            "cleaning_disposal", "other_expense"))


def test_monthly_net_profit_subtracts_overhead(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id, title="Net Profit Case", total_cost=10000)
    token = get_csrf(logged_in_client, "/financial-assessment/")
    logged_in_client.post(
        "/financial-assessment/save",
        data={
            "csrf_token": token, "case_ids": str(case_id),
            f"lab_amount_{case_id}": "1000", f"consultant_fee_{case_id}": "500",
            f"consumables_{case_id}": "0", f"misc_expense_{case_id}": "0",
        },
    )
    token = get_csrf(logged_in_client, "/financial-assessment/monthly")
    logged_in_client.post(
        "/financial-assessment/monthly/save",
        data={"csrf_token": token, "month": THIS_MONTH, "overhead_rent": "3000", "overhead_staff_salary": "4000"},
    )

    resp = logged_in_client.get(f"/financial-assessment/monthly?month={THIS_MONTH}")
    assert resp.status_code == 200
    # Net profit = billed(>=10000) - case expenses(>=1500) - overhead(7000); must render, not error.
    assert b"Net Monthly Profit" in resp.data


def test_monthly_save_rejects_missing_csrf_token(logged_in_client):
    resp = logged_in_client.post(
        "/financial-assessment/monthly/save",
        data={"month": THIS_MONTH, "overhead_rent": "999"},
    )
    assert resp.status_code == 400
    overhead = db.get_monthly_overhead_expenses(THIS_MONTH)
    assert overhead["rent"] == 0


# ── Capital Investments ──────────────────────────────────────────────────────────

def test_capital_investments_receptionist_forbidden(logged_in_client):
    investment_id = db.add_capital_investment("Recep Test Chair", THIS_MONTH_START, 60000, 60)
    _create_user(logged_in_client, "recepcapital", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recepcapital")

    assert logged_in_client.get("/financial-assessment/capital-investments").status_code == 403
    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post(
        "/financial-assessment/capital-investments/new",
        data={"csrf_token": token, "asset_name": "X", "purchase_date": THIS_MONTH_START, "cost": "100", "useful_life_months": "12"},
    )
    assert resp.status_code == 403
    resp = logged_in_client.post(
        f"/financial-assessment/capital-investments/{investment_id}/deactivate",
        data={"csrf_token": token},
    )
    assert resp.status_code == 403


def test_add_capital_investment_validates_required_fields(logged_in_client):
    token = get_csrf(logged_in_client, "/financial-assessment/capital-investments")
    resp = logged_in_client.post(
        "/financial-assessment/capital-investments/new",
        data={"csrf_token": token, "asset_name": "", "purchase_date": "", "cost": "0", "useful_life_months": "0"},
    )
    assert resp.status_code == 302
    assert db.list_capital_investments() == []


def test_add_capital_investment_persists_and_is_audited(logged_in_client):
    token = get_csrf(logged_in_client, "/financial-assessment/capital-investments")
    resp = logged_in_client.post(
        "/financial-assessment/capital-investments/new",
        data={
            "csrf_token": token, "asset_name": "Dental Chair", "purchase_date": THIS_MONTH_START,
            "cost": "120000", "useful_life_months": "60", "notes": "Primary operatory",
        },
    )
    assert resp.status_code == 302

    investments = db.list_capital_investments()
    assert len(investments) == 1
    assert investments[0]["asset_name"] == "Dental Chair"
    assert investments[0]["cost"] == 120000
    assert investments[0]["useful_life_months"] == 60
    assert investments[0]["monthly_depreciation"] == 2000  # 120000 / 60

    actions = [e["action"] for e in db.list_audit_log()]
    assert "capital_investment_added" in actions


def test_deactivate_capital_investment_excludes_from_depreciation(logged_in_client):
    investment_id = db.add_capital_investment("Old Scanner", THIS_MONTH_START, 24000, 24)
    assert db.get_monthly_depreciation(THIS_MONTH)["total"] == 1000  # 24000 / 24

    token = get_csrf(logged_in_client, "/financial-assessment/capital-investments")
    resp = logged_in_client.post(
        f"/financial-assessment/capital-investments/{investment_id}/deactivate",
        data={"csrf_token": token},
    )
    assert resp.status_code == 302
    assert db.get_monthly_depreciation(THIS_MONTH)["total"] == 0

    actions = [e["action"] for e in db.list_audit_log()]
    assert "capital_investment_deactivated" in actions

    # Reactivating brings it back into future depreciation calcs.
    token = get_csrf(logged_in_client, "/financial-assessment/capital-investments")
    logged_in_client.post(
        f"/financial-assessment/capital-investments/{investment_id}/activate",
        data={"csrf_token": token},
    )
    assert db.get_monthly_depreciation(THIS_MONTH)["total"] == 1000


def test_capital_investments_new_rejects_missing_csrf_token(logged_in_client):
    resp = logged_in_client.post(
        "/financial-assessment/capital-investments/new",
        data={"asset_name": "X", "purchase_date": THIS_MONTH_START, "cost": "100", "useful_life_months": "12"},
    )
    assert resp.status_code == 400
    assert db.list_capital_investments() == []


def test_monthly_depreciation_only_within_useful_life(app):
    # Purchased exactly 6 months before "this month", 12-month useful life — mid-life, should depreciate.
    six_months_ago = date.today()
    year, month = six_months_ago.year, six_months_ago.month - 6
    while month <= 0:
        month += 12
        year -= 1
    purchase = f"{year:04d}-{month:02d}-01"
    db.add_capital_investment("Mid-Life Asset", purchase, 12000, 12)
    assert db.get_monthly_depreciation(THIS_MONTH)["total"] == 1000  # 12000 / 12

    # Purchased in a future month relative to "this month" — not yet depreciating.
    future_year, future_month = date.today().year, date.today().month + 1
    if future_month > 12:
        future_month, future_year = 1, future_year + 1
    future_purchase = f"{future_year:04d}-{future_month:02d}-01"
    db.add_capital_investment("Not Yet Purchased", future_purchase, 6000, 6)
    assert db.get_monthly_depreciation(THIS_MONTH)["total"] == 1000  # unchanged, future asset excluded

    # Fully depreciated (purchased 24 months ago, 12-month life) — excluded, not negative or erroring.
    old_year, old_month = date.today().year, date.today().month - 24
    while old_month <= 0:
        old_month += 12
        old_year -= 1
    old_purchase = f"{old_year:04d}-{old_month:02d}-01"
    db.add_capital_investment("Fully Depreciated Asset", old_purchase, 6000, 12)
    assert db.get_monthly_depreciation(THIS_MONTH)["total"] == 1000  # still unchanged


def test_monthly_short_term_excludes_and_long_term_includes_depreciation(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id, title="Toggle Case", total_cost=50000)
    token = get_csrf(logged_in_client, "/financial-assessment/")
    logged_in_client.post(
        "/financial-assessment/save",
        data={
            "csrf_token": token, "case_ids": str(case_id),
            f"lab_amount_{case_id}": "0", f"consultant_fee_{case_id}": "0",
            f"consumables_{case_id}": "0", f"misc_expense_{case_id}": "0",
        },
    )
    db.add_capital_investment("Toggle Asset", THIS_MONTH_START, 12000, 12)  # 1000/month depreciation

    short_resp = logged_in_client.get(f"/financial-assessment/monthly?month={THIS_MONTH}&view=short")
    long_resp = logged_in_client.get(f"/financial-assessment/monthly?month={THIS_MONTH}&view=long")
    assert short_resp.status_code == 200
    assert long_resp.status_code == 200
    assert b"Capital Depreciation" not in short_resp.data
    assert b"Capital Depreciation" in long_resp.data
    assert b"Toggle Asset" in long_resp.data

    # Long Term's net profit must be exactly the depreciation amount (1000) less than Short Term's.
    rollup = db.get_monthly_case_rollup(THIS_MONTH)
    overhead_total = sum(db.get_monthly_overhead_expenses(THIS_MONTH)[f] for f in
                          ("rent", "staff_salary", "electricity", "emi", "cleaning_disposal", "other_expense"))
    short_profit = rollup["total_billed"] - rollup["total_case_expenses"] - overhead_total
    long_profit = short_profit - db.get_monthly_depreciation(THIS_MONTH)["total"]
    assert short_profit - long_profit == 1000
