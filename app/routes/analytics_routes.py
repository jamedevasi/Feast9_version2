from datetime import date

from flask import Blueprint, render_template, request

from app import db
from app.auth import financial_access_required, login_required

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


def _selected_year():
    raw = request.args.get("year", "")
    return int(raw) if raw.isdigit() else date.today().year


def _last_value(series):
    """Last non-None entry of a month-end series (None marks months not reached yet)."""
    values = [v for v in series if v is not None]
    return values[-1] if values else 0


def _pct_change(current, previous):
    """% change from previous to current; None when there's no base to compare against."""
    if not previous:
        return None
    return (current - previous) / previous * 100


@bp.route("/")
@login_required
@financial_access_required
def view_analytics():
    years = db.get_analytics_years()
    year = _selected_year()
    if year not in years:
        years = sorted(set(years) | {year}, reverse=True)

    chart_data = {
        "year": year,
        "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "monthly_revenue": db.get_monthly_revenue(year),
        "monthly_new_patients": db.get_monthly_new_patients(year),
        "monthly_new_cases": db.get_monthly_new_cases(year),
        "monthly_appointments": db.get_monthly_appointments(year),
        "case_status": db.get_case_status_breakdown(year),
        "appointment_status": db.get_appointment_status_breakdown(year),
        "doctor_revenue": db.get_doctor_revenue_share(year),
        "procedure_popularity": db.get_procedure_popularity(year),
        "monthly_total_patients": db.get_monthly_total_patients(year),
        "monthly_active_cases": db.get_monthly_active_cases(year),
        "weekday": db.get_weekday_activity(year),
        "demographics": db.get_patient_demographics(year),
        "revenue_by_procedure": db.get_monthly_revenue_by_procedure(year),
    }
    # The year-over-year line only means something once there are 2+ years of cases.
    yearly_active = db.get_yearly_active_cases()
    chart_data["yearly_active_cases"] = yearly_active if len(yearly_active) >= 2 else []

    # Year-end (or latest, for the current year) values of the two month-end series.
    kpis = db.get_analytics_kpis(year)
    kpis["total_patients"] = _last_value(chart_data["monthly_total_patients"])
    kpis["active_cases"] = _last_value(chart_data["monthly_active_cases"])

    # Year-on-year: only offered once the previous year has any data at all. When on, the
    # monthly charts get last year's series as a dashed overlay and each KPI a % change.
    prev_year = year - 1
    yoy_available = prev_year in db.get_years_with_activity()
    compare = yoy_available and request.args.get("compare") == "yoy"
    kpi_deltas = {}
    kpi_compare_label = str(prev_year)
    if compare:
        # A year still in progress is compared with the same stretch of last year (Jan 1 to
        # today's date), not the whole of it — otherwise every YTD total looks like a drop.
        # The monthly charts need no cut-off: each month already lines up with its twin.
        today = date.today()
        in_progress = year == today.year
        until = None
        month_idx = 11
        if in_progress:
            try:
                until = today.replace(year=prev_year).isoformat()
            except ValueError:  # 29 Feb, and last year wasn't a leap year
                until = today.replace(year=prev_year, day=28).isoformat()
            month_idx = today.month - 1
        chart_data["previous"] = {
            "year": prev_year,
            "monthly_revenue": db.get_monthly_revenue(prev_year),
            "monthly_new_patients": db.get_monthly_new_patients(prev_year),
            "monthly_new_cases": db.get_monthly_new_cases(prev_year),
            "monthly_appointments": db.get_monthly_appointments(prev_year),
            "weekday": db.get_weekday_activity(prev_year, until=until),
        }
        prev_kpis = db.get_analytics_kpis(prev_year, until=until)
        prev_kpis["total_patients"] = db.get_monthly_total_patients(prev_year)[month_idx] or 0
        prev_kpis["active_cases"] = db.get_monthly_active_cases(prev_year)[month_idx] or 0
        kpi_deltas = {key: _pct_change(kpis[key], prev_kpis[key]) for key in kpis}
        kpi_compare_label = f"same period {prev_year}" if in_progress else str(prev_year)

    return render_template(
        "analytics.html",
        years=years,
        year=year,
        kpis=kpis,
        kpi_deltas=kpi_deltas,
        kpi_compare_label=kpi_compare_label,
        compare=compare,
        yoy_available=yoy_available,
        prev_year=prev_year,
        chart_data=chart_data,
    )
