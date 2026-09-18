from calendar import monthrange
from datetime import date
from io import BytesIO

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook

from app import db
from app.auth import current_actor, financial_access_required, login_required
from app.csrf import validate_csrf
from app.validators import normalize_date

bp = Blueprint("financial", __name__, url_prefix="/financial-assessment")

CASE_EXPENSE_FIELDS = ("lab_amount", "consultant_fee", "consumables", "misc_expense")
OVERHEAD_FIELDS = ("rent", "staff_salary", "electricity", "emi", "cleaning_disposal", "other_expense")


def _filter_from_request():
    date_from = normalize_date(request.args.get("from", "")) or ""
    date_to = normalize_date(request.args.get("to", "")) or ""
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to


def _form_amount(form, name):
    raw = form.get(name, "0").strip()
    try:
        return max(float(raw), 0) if raw else 0.0
    except ValueError:
        return 0.0


@bp.route("/")
@login_required
@financial_access_required
def index():
    date_from, date_to = _filter_from_request()
    cases = db.list_financial_assessment_cases(date_from, date_to)
    totals = {
        "total_cost": sum(c["total_cost"] for c in cases),
        "collected": sum(c["collected"] for c in cases),
        "pending": sum(c["pending"] for c in cases),
        "expenses": sum(c["expenses"] for c in cases),
        "profit": sum(c["profit"] for c in cases),
    }
    return render_template(
        "financial_assessment.html", cases=cases, totals=totals, date_from=date_from, date_to=date_to,
    )


@bp.route("/save", methods=["POST"])
@login_required
@financial_access_required
def save():
    validate_csrf(request.form.get("csrf_token"))
    date_from = request.form.get("date_from", "")
    date_to = request.form.get("date_to", "")
    actor = current_actor()
    for case_id in request.form.getlist("case_ids"):
        try:
            case_id = int(case_id)
        except ValueError:
            continue
        amounts = [_form_amount(request.form, f"{field}_{case_id}") for field in CASE_EXPENSE_FIELDS]
        db.upsert_case_financial_expenses(case_id, *amounts, actor=actor)
    return redirect(url_for("financial.index", **({"from": date_from, "to": date_to} if date_from and date_to else {})))


@bp.route("/export.xlsx")
@login_required
@financial_access_required
def export_xlsx():
    date_from, date_to = _filter_from_request()
    cases = db.list_financial_assessment_cases(date_from, date_to)

    wb = Workbook()
    ws = wb.active
    ws.title = "Financial Assessment"
    ws.append([
        "Date", "Patient", "Case", "Billed", "Collected", "Pending",
        "Lab Amount", "Consultant Fee", "Consumables", "Misc Expense", "Profit",
    ])
    for c in cases:
        ws.append([
            c["created_at"][:10], c["patient_name"], c["case_title"], c["total_cost"],
            c["collected"], c["pending"], c["lab_amount"], c["consultant_fee"],
            c["consumables"], c["misc_expense"], c["profit"],
        ])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    db.write_audit_now(
        current_actor(), "financial_assessment_exported", "report", None,
        after_summary=f"financial_assessment.xlsx, {len(cases)} rows",
    )
    return send_file(
        buf,
        as_attachment=True,
        download_name="financial_assessment.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _current_month():
    return date.today().strftime("%Y-%m")


def _valid_month(raw):
    # HTML5 <input type="month"> posts YYYY-MM; anything else falls back to the current month.
    raw = (raw or "").strip()
    if len(raw) == 7 and raw[4] == "-" and raw[:4].isdigit() and raw[5:].isdigit():
        return raw
    return _current_month()


@bp.route("/monthly")
@login_required
@financial_access_required
def monthly():
    month = _valid_month(request.args.get("month"))
    view = "long" if request.args.get("view") == "long" else "short"
    rollup = db.get_monthly_case_rollup(month)
    overhead = db.get_monthly_overhead_expenses(month)
    overhead_total = sum(overhead[f] for f in OVERHEAD_FIELDS)
    depreciation = db.get_monthly_depreciation(month) if view == "long" else {"total": 0.0, "breakdown": []}
    net_profit = rollup["total_billed"] - rollup["total_case_expenses"] - overhead_total - depreciation["total"]
    year, mon = int(month[:4]), int(month[5:7])
    month_start = f"{month}-01"
    month_end = f"{month}-{monthrange(year, mon)[1]:02d}"
    return render_template(
        "financial_monthly.html", month=month, view=view, rollup=rollup, overhead=overhead,
        overhead_total=overhead_total, depreciation=depreciation, net_profit=net_profit,
        month_start=month_start, month_end=month_end,
    )


@bp.route("/monthly/save", methods=["POST"])
@login_required
@financial_access_required
def monthly_save():
    validate_csrf(request.form.get("csrf_token"))
    month = _valid_month(request.form.get("month"))
    amounts = [_form_amount(request.form, f"overhead_{field}") for field in OVERHEAD_FIELDS]
    db.upsert_monthly_overhead_expenses(month, *amounts, actor=current_actor())
    return redirect(url_for("financial.monthly", month=month, view=request.form.get("view", "short")))


@bp.route("/capital-investments")
@login_required
@financial_access_required
def capital_investments():
    return render_template(
        "capital_investments.html", investments=db.list_capital_investments(active_only=False),
    )


@bp.route("/capital-investments/new", methods=["POST"])
@login_required
@financial_access_required
def capital_investments_new():
    validate_csrf(request.form.get("csrf_token"))
    asset_name = request.form.get("asset_name", "").strip()
    purchase_date = normalize_date(request.form.get("purchase_date", ""))
    cost_raw = request.form.get("cost", "").strip()
    life_raw = request.form.get("useful_life_months", "").strip()
    notes = request.form.get("notes", "").strip()

    errors = []
    if not asset_name:
        errors.append("Asset name is required.")
    if not purchase_date:
        errors.append("A valid purchase date is required.")
    try:
        cost = float(cost_raw)
        if cost <= 0:
            errors.append("Cost must be greater than zero.")
    except ValueError:
        errors.append("Cost must be a number.")
        cost = 0
    try:
        useful_life_months = int(life_raw)
        if useful_life_months <= 0:
            errors.append("Useful life (months) must be a positive whole number.")
    except ValueError:
        errors.append("Useful life (months) must be a whole number.")
        useful_life_months = 0

    if errors:
        for e in errors:
            flash(e, "warning")
        return redirect(url_for("financial.capital_investments"))

    db.add_capital_investment(asset_name, purchase_date, cost, useful_life_months, notes, actor=current_actor())
    flash(f"Asset '{asset_name}' added.", "success")
    return redirect(url_for("financial.capital_investments"))


@bp.route("/capital-investments/<int:investment_id>/deactivate", methods=["POST"])
@login_required
@financial_access_required
def capital_investments_deactivate(investment_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_capital_investment(investment_id)
    if not target:
        return redirect(url_for("financial.capital_investments"))
    db.set_capital_investment_active(investment_id, False, actor=current_actor())
    flash(f"'{target['asset_name']}' deactivated — excluded from future depreciation.", "success")
    return redirect(url_for("financial.capital_investments"))


@bp.route("/capital-investments/<int:investment_id>/activate", methods=["POST"])
@login_required
@financial_access_required
def capital_investments_activate(investment_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_capital_investment(investment_id)
    if not target:
        return redirect(url_for("financial.capital_investments"))
    db.set_capital_investment_active(investment_id, True, actor=current_actor())
    flash(f"'{target['asset_name']}' reactivated.", "success")
    return redirect(url_for("financial.capital_investments"))
