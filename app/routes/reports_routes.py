from datetime import date, timedelta
from io import BytesIO

from flask import Blueprint, render_template, request, send_file
from openpyxl import Workbook
from openpyxl.styles import Font

from app import db, pdf_reports
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
        "financial_summary": db.get_financial_assessment_summary(),
    }


# Merged Case/Payment ledger — one filterable, groupable table in place of the separate
# 'Pending Payments by Patient & Case', 'Payments Received in Period' and 'Cases Closed in
# Period' sections (user decision 2026-09-23; the PDF report still prints those three as-is).
# Two views because the grains differ: a case can have many payments. Every option is a
# whitelist — anything else in the query string falls back to the default.
LEDGER_VIEWS = {"cases", "payments"}
LEDGER_GROUPS = {
    "cases": {
        "": "No grouping",
        "patient": "Patient",
        "doctor": "Doctor",
        "status": "Status",
        "month": "Month opened",
    },
    "payments": {
        "": "No grouping",
        "patient": "Patient",
        "doctor": "Doctor",
        "method": "Method",
        "month": "Month",
    },
}
LEDGER_SUM_FIELDS = {"cases": ("total_cost", "paid", "balance"), "payments": ("amount",)}
LEDGER_STATUSES = {"", "Active", "Closed"}
LEDGER_BALANCES = {"": "Any balance", "outstanding": "Outstanding only", "paid": "Fully paid"}
LEDGER_PERIOD_ON = {"": "All time", "opened": "Opened in period", "closed": "Closed in period"}


def _group_key(view, group, row):
    if group == "patient":
        return row["patient_name"]
    if group == "doctor":
        return row["doctor_name"] or "—"
    if group == "status":
        return row["status"]
    if group == "method":
        return (row["method"] or "").strip() or "—"
    if group == "month":
        return (row["created_at"] if view == "cases" else row["payment_date"])[:7]
    return ""


def _ledger_from_request(start, end):
    """Reads the ledger options from the query string (defaults = the old Pending Payments
    list: cases with an outstanding balance, all time) and returns the rows grouped with
    per-group subtotals and grand totals. Shared by the page and its Excel export."""
    args = request.args
    view = args.get("view", "cases")
    if view not in LEDGER_VIEWS:
        view = "cases"
    group = args.get("group", "")
    if group not in LEDGER_GROUPS[view]:
        group = ""
    status = args.get("status", "")
    if status not in LEDGER_STATUSES:
        status = ""
    # Absent entirely → the default; present-but-empty ("Any balance") is a real choice.
    balance = args.get("balance", "outstanding")
    if balance not in LEDGER_BALANCES:
        balance = "outstanding"
    period_on = args.get("period_on", "")
    if period_on not in LEDGER_PERIOD_ON:
        period_on = ""
    method = args.get("method", "").strip()

    if view == "cases":
        rows = db.get_case_ledger(start, end, status=status, balance=balance, period_on=period_on)
    else:
        rows = db.get_payment_ledger(start, end, method=method)

    sum_fields = LEDGER_SUM_FIELDS[view]
    groups = []
    if group:
        by_key = {}
        for row in rows:
            by_key.setdefault(_group_key(view, group, row), []).append(row)
        # Months newest-first (like the ungrouped list); everything else alphabetical.
        keys = sorted(by_key, reverse=(group == "month"), key=lambda k: k.lower())
        for key in keys:
            members = by_key[key]
            groups.append({
                "label": key,
                "rows": members,
                "totals": {f: sum(r[f] for r in members) for f in sum_fields},
            })
    else:
        groups.append({"label": "", "rows": rows, "totals": {}})

    return {
        "view": view,
        "group": group,
        # The active options as query params — carried by the period filter, the view
        # toggle and the Excel link so none of them silently resets the others.
        "params": {
            "view": view, "group": group, "status": status,
            "balance": balance, "period_on": period_on, "method": method,
        },
        "row_count": len(rows),
        "groups": groups,
        "totals": {f: sum(r[f] for r in rows) for f in sum_fields},
    }


def _ledger_options():
    return {
        "ledger_groups": LEDGER_GROUPS,
        "ledger_balances": LEDGER_BALANCES,
        "ledger_period_on": LEDGER_PERIOD_ON,
        "payment_methods": db.list_payment_methods(),
    }


@bp.route("/")
@login_required
@financial_access_required
def view_reports():
    start, end = _period_from_request()
    return render_template(
        "reports.html", start=start, end=end,
        ledger=_ledger_from_request(start, end), **_ledger_options(),
        **_report_context(start, end),
    )


@bp.route("/report.pdf")
@login_required
@financial_access_required
def report_pdf():
    start, end = _period_from_request()
    pdf_bytes = pdf_reports.generate_report_pdf(start, end, _report_context(start, end))
    db.write_audit_now(
        current_actor(), "report_downloaded", "report", None, after_summary=f"report.pdf, {start} to {end}",
    )
    return send_file(BytesIO(pdf_bytes), mimetype="application/pdf", download_name=f"report-{start}-to-{end}.pdf")


LEDGER_COLUMNS = {
    "cases": [
        ("Patient", "patient_name"), ("Mobile", "mobile"), ("Case", "case_title"),
        ("Doctor", "doctor_name"), ("Status", "status"), ("Opened", "created_at"),
        ("Closed", "closed_at"), ("Total Cost", "total_cost"), ("Paid", "paid"),
        ("Balance", "balance"),
    ],
    "payments": [
        ("Date", "payment_date"), ("Patient", "patient_name"), ("Case", "case_title"),
        ("Doctor", "doctor_name"), ("Amount", "amount"), ("Method", "method"),
        ("Reference", "reference"),
    ],
}


@bp.route("/ledger.xlsx")
@login_required
@financial_access_required
def download_ledger_xlsx():
    """Excel of exactly what the ledger shows on screen — same view, filters and grouping,
    with a bold subtotal row per group and a grand total row."""
    start, end = _period_from_request()
    ledger = _ledger_from_request(start, end)
    view = ledger["view"]
    columns = LEDGER_COLUMNS[view]

    wb = Workbook()
    ws = wb.active
    ws.title = "Cases" if view == "cases" else "Payments"
    ws.append([label for label, _ in columns])
    for cell in ws[1]:
        cell.font = Font(bold=True)

    def total_row(label, totals):
        values = [totals[key] if key in totals else "" for _, key in columns]
        values[0] = label
        ws.append(values)
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)

    for grp in ledger["groups"]:
        for row in grp["rows"]:
            ws.append([row[key] for _, key in columns])
        if ledger["group"]:
            total_row(f"Subtotal — {grp['label']} ({len(grp['rows'])})", grp["totals"])
    total_row(f"Total ({ledger['row_count']})", ledger["totals"])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    db.write_audit_now(
        current_actor(), "report_downloaded", "report", None,
        after_summary=(
            f"ledger.xlsx, view={view} group={ledger['group'] or 'none'} "
            f"{start} to {end}, {ledger['row_count']} rows"
        ),
    )
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{view}-ledger-{start}-to-{end}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
