from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
from app.auth import current_actor, hash_password, login_required, reauth_required, role_required
from app.constants import ROLES
from app.csrf import validate_csrf

bp = Blueprint("users", __name__, url_prefix="/users")


@bp.route("/")
@login_required
@role_required("admin")
def list_view():
    return render_template("users_list.html", users=db.list_users())


@bp.route("/new", methods=["GET", "POST"])
@login_required
@role_required("admin")
@reauth_required
def new():
    errors = []
    form_state = {"username": "", "role": ""}

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        role = request.form.get("role", "")
        security_question = request.form.get("security_question", "").strip()
        security_answer = request.form.get("security_answer", "").strip()
        form_state = {"username": username, "role": role}

        if not username:
            errors.append("Username is required.")
        elif db.username_exists(username):
            errors.append("That username is already taken.")
        if role not in ROLES:
            errors.append("Select a valid role.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if not security_question:
            errors.append("Security question is required.")
        if not security_answer:
            errors.append("Security answer is required.")

        if not errors:
            db.create_user(
                username=username,
                password_hash=hash_password(password),
                role=role,
                security_question=security_question,
                security_answer_hash=hash_password(security_answer.lower()),
                actor=current_actor(),
            )
            flash(f"User '{username}' created.", "success")
            return redirect(url_for("users.list_view"))

    return render_template("user_form.html", errors=errors, user=form_state, roles=ROLES)


@bp.route("/<int:user_id>/deactivate", methods=["POST"])
@login_required
@role_required("admin")
@reauth_required
def deactivate(user_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    if target["role"] == "admin" and db.count_active_admins() <= 1:
        flash("Cannot deactivate the only active admin account.", "warning")
        return redirect(url_for("users.list_view"))
    db.set_user_active(user_id, False, actor=current_actor())
    flash(f"User '{target['username']}' deactivated.", "success")
    return redirect(url_for("users.list_view"))


@bp.route("/<int:user_id>/activate", methods=["POST"])
@login_required
@role_required("admin")
@reauth_required
def activate(user_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    db.set_user_active(user_id, True, actor=current_actor())
    flash(f"User '{target['username']}' reactivated.", "success")
    return redirect(url_for("users.list_view"))


@bp.route("/<int:user_id>/reset-totp", methods=["POST"])
@login_required
@role_required("admin")
@reauth_required
def reset_totp(user_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    db.reset_totp(user_id, actor=current_actor())
    flash(f"Two-factor authentication reset for '{target['username']}'.", "success")
    return redirect(url_for("users.list_view"))


@bp.route("/<int:user_id>/unlink-google", methods=["POST"])
@login_required
@role_required("admin")
@reauth_required
def unlink_google(user_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    db.unlink_google_account(user_id, actor=current_actor())
    flash(f"Google account unlinked for '{target['username']}'.", "success")
    return redirect(url_for("users.list_view"))
