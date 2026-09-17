from datetime import date

from flask import Blueprint, render_template, request

from app import db
from app.auth import financial_access_required, login_required

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


def _selected_year():
    raw = request.args.get("year", "")
    return int(raw) if raw.isdigit() else date.today().year


@bp.route("/")
@login_required
@financial_access_required
def view_analytics():
    years = db.get_analytics_years()
    year = _selected_year()
    if year not in years:
        years = sorted(set(years) | {year}, reverse=True)

    chart_data = {
        "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "monthly_revenue": db.get_monthly_revenue(year),
        "monthly_new_patients": db.get_monthly_new_patients(year),
        "monthly_new_cases": db.get_monthly_new_cases(year),
        "monthly_appointments": db.get_monthly_appointments(year),
        "case_status": db.get_case_status_breakdown(year),
        "appointment_status": db.get_appointment_status_breakdown(year),
        "doctor_revenue": db.get_doctor_revenue_share(year),
        "procedure_popularity": db.get_procedure_popularity(year),
    }

    return render_template(
        "analytics.html",
        years=years,
        year=year,
        kpis=db.get_analytics_kpis(year),
        chart_data=chart_data,
    )
