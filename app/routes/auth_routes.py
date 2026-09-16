from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import db
from app.auth import check_password, hash_password, is_rate_limited, login_required
from app.csrf import validate_csrf

bp = Blueprint("auth", __name__)


@bp.route("/")
def index():
    if db.get_admin() is None:
        return redirect(url_for("auth.setup"))
    if session.get("admin_id"):
        return redirect(url_for("dashboard.index"))
    return redirect(url_for("auth.login"))


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if db.get_admin() is not None:
        return redirect(url_for("auth.login"))

    errors = []
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        security_question = request.form.get("security_question", "").strip()
        security_answer = request.form.get("security_answer", "").strip()

        if not username:
            errors.append("Username is required.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if not security_question:
            errors.append("Security question is required.")
        if not security_answer:
            errors.append("Security answer is required.")

        if not errors:
            db.create_admin(
                username=username,
                password_hash=hash_password(password),
                security_question=security_question,
                security_answer_hash=hash_password(security_answer.lower()),
            )
            flash("Setup complete. Please log in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("setup.html", errors=errors)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if db.get_admin() is None:
        return redirect(url_for("auth.setup"))

    errors = []
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        ip = request.remote_addr or "unknown"

        if is_rate_limited(ip):
            errors.append("Too many failed login attempts. Please try again in 15 minutes.")
        else:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = db.get_user_by_username(username)
            if user and check_password(user["password_hash"], password):
                db.clear_failed_logins(ip)
                session.clear()
                session["admin_id"] = user["id"]
                session["username"] = user["username"]
                session["role"] = user["role"]
                next_url = request.args.get("next") or url_for("dashboard.index")
                return redirect(next_url)
            db.record_failed_login(ip)
            errors.append("Invalid username or password.")

    return render_template("login.html", errors=errors)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
