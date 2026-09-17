from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
from app.auth import current_actor, login_required, role_required
from app.csrf import validate_csrf

bp = Blueprint("doctors", __name__, url_prefix="/doctors")


@bp.route("/")
@login_required
@role_required("admin")
def list_view():
    return render_template("doctors_list.html", doctors=db.list_doctors(active_only=False))


@bp.route("/new", methods=["POST"])
@login_required
@role_required("admin")
def new():
    validate_csrf(request.form.get("csrf_token"))
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "").strip()
    if not name:
        flash("Doctor name is required.", "warning")
        return redirect(url_for("doctors.list_view"))
    db.add_doctor(name, color, actor=current_actor())
    flash(f"Doctor '{name}' added.", "success")
    return redirect(url_for("doctors.list_view"))


@bp.route("/<int:doctor_id>/deactivate", methods=["POST"])
@login_required
@role_required("admin")
def deactivate(doctor_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_doctor(doctor_id)
    if not target:
        abort(404)
    db.set_doctor_active(doctor_id, False, actor=current_actor())
    flash(f"Doctor '{target['name']}' deactivated — hidden from new cases/appointments, existing records unaffected.", "success")
    return redirect(url_for("doctors.list_view"))


@bp.route("/<int:doctor_id>/activate", methods=["POST"])
@login_required
@role_required("admin")
def activate(doctor_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_doctor(doctor_id)
    if not target:
        abort(404)
    db.set_doctor_active(doctor_id, True, actor=current_actor())
    flash(f"Doctor '{target['name']}' reactivated.", "success")
    return redirect(url_for("doctors.list_view"))
