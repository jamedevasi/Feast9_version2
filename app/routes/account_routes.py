"""Self-service account management — Change Password and Security Question, available
to every logged-in role. feast9_v2_agents.md §5.13 lists these as Settings sections, but
/settings is admin-only for clinic-wide configuration (Doctors, Clinic Details, Backups,
...) — that page predates multi-user roles (§14), and a doctor/receptionist still needs
to manage their own credentials, so this lives on its own page rather than behind
Settings' admin gate."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import db
from app.auth import check_password, current_actor, hash_password, login_required
from app.csrf import validate_csrf

bp = Blueprint("account", __name__, url_prefix="/account")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    user = db.get_user_by_id(session["admin_id"])
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        form = request.form.get("form")
        if form == "change_password":
            _change_password(user)
        elif form == "security_question":
            _change_security_question(user)
        return redirect(url_for("account.index"))

    return render_template("account.html", user=user)


def _change_password(user):
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not check_password(user["password_hash"], current_password):
        flash("Current password is incorrect.", "warning")
    elif len(new_password) < 8:
        flash("New password must be at least 8 characters.", "warning")
    elif new_password != confirm:
        flash("New passwords do not match.", "warning")
    else:
        db.update_user_password(user["id"], hash_password(new_password), actor=current_actor())
        flash("Password changed.", "success")


def _change_security_question(user):
    current_password = request.form.get("current_password", "")
    question = request.form.get("security_question", "").strip()
    answer = request.form.get("security_answer", "").strip()

    if not check_password(user["password_hash"], current_password):
        flash("Current password is incorrect.", "warning")
    elif not question:
        flash("Security question is required.", "warning")
    elif not answer:
        flash("Security answer is required.", "warning")
    else:
        db.update_security_question(user["id"], question, hash_password(answer.lower()), actor=current_actor())
        flash("Security question updated.", "success")
