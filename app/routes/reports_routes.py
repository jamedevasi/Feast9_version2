from datetime import date, timedelta
from io import BytesIO

from flask import Blueprint, render_template, request, send_file
from openpyxl import Workbook

from app import db
from app.auth import current_actor, financial_access_required, login_required
from app.validators import normalize_date, today_iso

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _default_start():
    return (date.today() - timedelta(days=30)).isoformat()


def _period_from_request():
    start = normalize_date(request.args.get("start", "")) or _default_start()
    end = normalize_date(request.args.get("end", "")) or today_iso()
    if start > end:
        start, end = end, start
    return start, end


def _report_context(start, end):
    """Shared by the on-screen report and the print view — same numbers either way."""
    return {
        "revenue_collected": db.get_revenue_collected(start, end),
        "cases_closed_count": db.get_cases_closed_count(start, end),
        "new_cases_count": db.get_new_cases_count(start, end),
        "new_patients_count": db.get_new_patients_count(start, end),
        "revenue_overview": db.get_revenue_overview(),
        "pending_payments": db.get_pending_payments(),
        "doctor_revenue": db.get_doctor_revenue_by_period(start, end),
        "retention": db.get_patient_retention(),
        "payments_in_period": db.get_payments_in_range(start, end),
        "cases_closed_in_period": db.get_cases_closed_in_range(start, end),
    }


@bp.route("/")
@login_required
@financial_access_required
def view_reports():
    start, end = _period_from_request()
    return render_template("reports.html", start=start, end=end, **_report_context(start, end))


@bp.route("/print")
@login_required
@financial_access_required
def print_view():
    start, end = _period_from_request()
    return render_template("reports_print.html", start=start, end=end, **_report_context(start, end))


@bp.route("/pending.xlsx")
@login_required
@financial_access_required
def download_pending_xlsx():
    pending = db.get_pending_payments()
    wb = Workbook()
    ws = wb.active
    ws.title = "Pending Payments"
    ws.append(["Patient", "Mobile", "Case", "Status", "Total Cost", "Paid", "Balance"])
    for row in pending:
        ws.append([
            row["patient_name"], row["mobile"], row["case_title"], row["status"],
            row["total_cost"], row["paid"], row["balance"],
        ])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    db.write_audit_now(
        current_actor(), "report_downloaded", "report", None,
        after_summary=f"pending_payments.xlsx, {len(pending)} rows",
    )
    return send_file(
        buf,
        as_attachment=True,
        download_name="pending_payments.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
