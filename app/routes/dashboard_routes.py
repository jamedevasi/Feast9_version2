from datetime import datetime, timedelta

from flask import Blueprint, render_template, session

from app import db
from app.auth import can_view_financial_data, login_required

bp = Blueprint("dashboard", __name__)

BACKUP_STALE_HOURS = 26  # a nightly job with some slack — flag it if a day's run was missed


@bp.route("/dashboard")
@login_required
def index():
    backup_warning = None
    if session.get("role") == "admin":
        latest = db.latest_backup_log()
        if latest is None:
            backup_warning = "No backup has ever been run."
        elif latest["status"] != "success":
            backup_warning = f"The last backup attempt failed: {latest['error_message'] or 'unknown error'}."
        else:
            finished = datetime.strptime(latest["finished_at"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - finished > timedelta(hours=BACKUP_STALE_HOURS):
                backup_warning = f"The last successful backup was at {latest['finished_at']} — that's more than {BACKUP_STALE_HOURS} hours ago."

    overdue_followups, upcoming_followups = db.get_followup_alerts()
    can_view_financial = can_view_financial_data()
    return render_template(
        "dashboard.html",
        backup_warning=backup_warning,
        overdue_followups=overdue_followups,
        upcoming_followups=upcoming_followups,
        active_cases_count=db.get_active_cases_count(),
        outstanding_balance=db.get_outstanding_balance() if can_view_financial else None,
        can_view_financial=can_view_financial,
        todays_appointments=db.get_todays_appointments(),
    )
