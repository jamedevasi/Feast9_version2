from flask import Blueprint, render_template

from app import db
from app.auth import can_view_financial_data, login_required

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
@login_required
def index():
    overdue_followups, upcoming_followups = db.get_followup_alerts()
    can_view_financial = can_view_financial_data()
    return render_template(
        "dashboard.html",
        overdue_followups=overdue_followups,
        upcoming_followups=upcoming_followups,
        active_cases_count=db.get_active_cases_count(),
        outstanding_balance=db.get_outstanding_balance() if can_view_financial else None,
        can_view_financial=can_view_financial,
        todays_appointments=db.get_todays_appointments(),
        open_lab_reqs_due=db.get_open_lab_reqs_for_upcoming_appointments(),
    )
