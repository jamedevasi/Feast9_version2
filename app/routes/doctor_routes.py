from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db, doctor_colors
from app.auth import current_actor, login_required, role_required
from app.csrf import validate_csrf

bp = Blueprint("doctors", __name__, url_prefix="/doctors")


def _collect_doctor_form(form):
    return {
        field: form.get(field, "").strip()
        for field in ("name", "color", "qualifications", "registration_number", "registration_council")
    }


@bp.route("/")
@login_required
@role_required("admin")
def list_view():
    return render_template("doctors_list.html", doctors=db.list_doctors(active_only=False),
                           suggested_color=doctor_colors.suggest(db.list_doctors()))


def _warn_if_color_clashes(name, color, doctor_id=None):
    """Saved either way — but say so when the colour is hard to tell from another doctor's."""
    clashes = doctor_colors.similar_to(color, db.list_doctors(), exclude_id=doctor_id)
    if clashes:
        flash(f"{name}'s calendar colour looks very like {', '.join(clashes)}'s, so their appointments "
              f"will be hard to tell apart. Choose a different colour with Edit.", "warning")


@bp.route("/new", methods=["POST"])
@login_required
@role_required("admin")
def new():
    validate_csrf(request.form.get("csrf_token"))
    data = _collect_doctor_form(request.form)
    if not data["name"]:
        flash("Doctor name is required.", "warning")
        return redirect(url_for("doctors.list_view"))
    doctor_id = db.add_doctor(
        data["name"], data["color"], actor=current_actor(),
        qualifications=data["qualifications"], registration_number=data["registration_number"],
        registration_council=data["registration_council"],
    )
    flash(f"Doctor '{data['name']}' added.", "success")
    _warn_if_color_clashes(data["name"], data["color"], doctor_id)
    return redirect(url_for("doctors.list_view"))


@bp.route("/<int:doctor_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit(doctor_id):
    doctor = db.get_doctor(doctor_id)
    if not doctor:
        abort(404)
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        data = _collect_doctor_form(request.form)
        if data["name"]:
            db.update_doctor(doctor_id, data, actor=current_actor())
            flash(f"Doctor '{data['name']}' updated.", "success")
            _warn_if_color_clashes(data["name"], data["color"], doctor_id)
            return redirect(url_for("doctors.list_view"))
        flash("Doctor name is required.", "warning")
        doctor = {**doctor, **data}
    return render_template("doctor_form.html", doctor=doctor)


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
