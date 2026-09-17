import pathlib

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for

from app import config as app_config
from app import db
from app.auth import (
    check_password,
    check_recovery_code,
    hash_password,
    is_rate_limited,
    login_required,
    mark_reauthenticated,
    verify_totp_code,
)
from app.constants import DEFAULT_LOGIN_HEADING, DEFAULT_LOGIN_TAGLINE
from app.csrf import validate_csrf

bp = Blueprint("auth", __name__)

_IMAGE_EXT_TO_MIMETYPE = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}


@bp.route("/login-image")
def login_image():
    """Public (no @login_required) — the login page needs this before the visitor has
    authenticated. Falls back to the bundled default if no custom image is configured
    or the configured file is missing (feast9_v2_agents.md §5.12)."""
    default = pathlib.Path(current_app.root_path) / "static" / "img" / "saint_apollonia.png"
    filename = db.get_setting("login_image_filename", "")
    if filename:
        custom = pathlib.Path(app_config.branding_dir()) / filename
        if custom.exists():
            ext = custom.suffix.lower().lstrip(".")
            mimetype = _IMAGE_EXT_TO_MIMETYPE.get(ext, "image/jpeg")
            return send_file(str(custom), mimetype=mimetype)
    return send_file(str(default), mimetype="image/png")


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
                next_url = request.args.get("next") or url_for("dashboard.index")
                if user["totp_enabled"]:
                    session.clear()
                    session["totp_pending_user_id"] = user["id"]
                    session["totp_pending_next"] = next_url
                    return redirect(url_for("auth.login_totp"))
                session.clear()
                session["admin_id"] = user["id"]
                session["username"] = user["username"]
                session["role"] = user["role"]
                mark_reauthenticated()
                return redirect(next_url)
            db.record_failed_login(ip)
            errors.append("Invalid username or password.")

    # No custom heading set -> fall back to the clinic's own name (Settings > Clinic
    # Details) before the generic app-name default, so a configured clinic shows its
    # own name here without needing to duplicate it into login_heading too.
    login_heading = db.get_setting("login_heading", "") or db.get_setting("clinic_name", "") or DEFAULT_LOGIN_HEADING
    return render_template(
        "login.html", errors=errors,
        login_heading=login_heading,
        login_tagline=db.get_setting("login_tagline", DEFAULT_LOGIN_TAGLINE),
    )


@bp.route("/login/totp", methods=["GET", "POST"])
def login_totp():
    pending_id = session.get("totp_pending_user_id")
    if not pending_id:
        return redirect(url_for("auth.login"))
    user = db.get_user_by_id(pending_id)
    if not user or not user["totp_enabled"]:
        session.clear()
        return redirect(url_for("auth.login"))

    errors = []
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        ip = request.remote_addr or "unknown"

        if is_rate_limited(ip):
            errors.append("Too many failed attempts. Please try again in 15 minutes.")
        else:
            code = request.form.get("code", "").strip()
            recovery_code = request.form.get("recovery_code", "").strip()
            verified = bool(code) and verify_totp_code(user["totp_secret"], code)
            if not verified and recovery_code:
                verified = db.consume_recovery_code(
                    user["id"], lambda h: check_recovery_code(h, recovery_code)
                )

            if verified:
                db.clear_failed_logins(ip)
                next_url = session.get("totp_pending_next") or url_for("dashboard.index")
                session.clear()
                session["admin_id"] = user["id"]
                session["username"] = user["username"]
                session["role"] = user["role"]
                mark_reauthenticated()
                return redirect(next_url)
            db.record_failed_login(ip)
            errors.append("Invalid authentication code or recovery code.")

    return render_template("login_totp.html", errors=errors)


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Step 1 of self-service password reset (§5.1: "no email needed") — enter a
    username, land on the security question for that account."""
    errors = []
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        ip = request.remote_addr or "unknown"

        if is_rate_limited(ip):
            errors.append("Too many attempts. Please try again in 15 minutes.")
        else:
            username = request.form.get("username", "").strip()
            user = db.get_user_by_username(username)
            if user:
                session["reset_pending_user_id"] = user["id"]
                return redirect(url_for("auth.forgot_password_verify"))
            db.record_failed_login(ip)
            errors.append("No account found with that username.")

    return render_template("forgot_password.html", errors=errors)


@bp.route("/forgot-password/verify", methods=["GET", "POST"])
def forgot_password_verify():
    pending_id = session.get("reset_pending_user_id")
    if not pending_id:
        return redirect(url_for("auth.forgot_password"))
    user = db.get_user_by_id(pending_id)
    if not user or not user["is_active"]:
        session.pop("reset_pending_user_id", None)
        return redirect(url_for("auth.forgot_password"))

    errors = []
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        ip = request.remote_addr or "unknown"

        if is_rate_limited(ip):
            errors.append("Too many attempts. Please try again in 15 minutes.")
        else:
            answer = request.form.get("security_answer", "").strip().lower()
            new_password = request.form.get("new_password", "")
            confirm = request.form.get("confirm_password", "")

            if not check_password(user["security_answer_hash"], answer):
                db.record_failed_login(ip)
                errors.append("Incorrect answer to the security question.")
            elif len(new_password) < 8:
                errors.append("Password must be at least 8 characters.")
            elif new_password != confirm:
                errors.append("Passwords do not match.")
            else:
                db.clear_failed_logins(ip)
                actor = {"user_id": user["id"], "role": user["role"], "ip": ip, "user_agent": ""}
                db.update_user_password(user["id"], hash_password(new_password), actor=actor)
                session.pop("reset_pending_user_id", None)
                flash("Password reset. Please log in with your new password.", "success")
                return redirect(url_for("auth.login"))

    return render_template(
        "forgot_password_verify.html", errors=errors, security_question=user["security_question"]
    )


@bp.route("/reauth", methods=["GET", "POST"])
@login_required
def reauth():
    user = db.get_user_by_id(session["admin_id"])
    errors = []
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        ip = request.remote_addr or "unknown"
        if is_rate_limited(ip):
            errors.append("Too many failed attempts. Please try again in 15 minutes.")
        else:
            password = request.form.get("password", "")
            code = request.form.get("code", "").strip()
            if not check_password(user["password_hash"], password):
                db.record_failed_login(ip)
                errors.append("Incorrect password.")
            elif user["totp_enabled"] and not verify_totp_code(user["totp_secret"], code):
                db.record_failed_login(ip)
                errors.append("Invalid authentication code.")
            else:
                db.clear_failed_logins(ip)
                mark_reauthenticated()
                next_url = session.pop("reauth_next", None) or url_for("dashboard.index")
                return redirect(next_url)

    return render_template("reauth.html", errors=errors, totp_enabled=bool(user["totp_enabled"]))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
