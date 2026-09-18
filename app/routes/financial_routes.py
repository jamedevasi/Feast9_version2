from io import BytesIO

from flask import Blueprint, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook

from app import db
from app.auth import current_actor, financial_access_required, login_required
from app.csrf import validate_csrf
from app.validators import normalize_date

bp = Blueprint("financial", __name__, url_prefix="/financial-assessment")


def _filter_from_request():
    date_from = normalize_date(request.args.get("from", "")) or ""
    date_to = normalize_date(request.args.get("to", "")) or ""
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to


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

        def _amount(field):
            raw = request.form.get(f"{field}_{case_id}", "0").strip()
            try:
                return max(float(raw), 0) if raw else 0.0
            except ValueError:
                return 0.0

        db.upsert_case_financial_expenses(
            case_id, _amount("lab_amount"), _amount("consultant_fee"), _amount("misc_expense"),
            actor=actor,
        )
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
        "Lab Amount", "Consultant Fee", "Misc Expense", "Profit",
    ])
    for c in cases:
        ws.append([
            c["created_at"][:10], c["patient_name"], c["case_title"], c["total_cost"],
            c["collected"], c["pending"], c["lab_amount"], c["consultant_fee"], c["misc_expense"],
            c["profit"],
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
