from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
from app.auth import current_actor, login_required, role_required
from app.csrf import validate_csrf

bp = Blueprint("procedure_types", __name__, url_prefix="/procedure-types")


@bp.route("/")
@login_required
@role_required("admin")
def list_view():
    return render_template("procedure_types_list.html", procedure_types=db.list_procedure_types(active_only=False))


@bp.route("/new", methods=["POST"])
@login_required
@role_required("admin")
def new():
    validate_csrf(request.form.get("csrf_token"))
    name = request.form.get("name", "").strip()
    if not name:
        flash("Case type name is required.", "warning")
        return redirect(url_for("procedure_types.list_view"))
    db.add_procedure_type(name, actor=current_actor())
    flash(f"Case type '{name}' added.", "success")
    return redirect(url_for("procedure_types.list_view"))


@bp.route("/<int:procedure_type_id>/deactivate", methods=["POST"])
@login_required
@role_required("admin")
def deactivate(procedure_type_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_procedure_type(procedure_type_id)
    if not target:
        abort(404)
    db.set_procedure_type_active(procedure_type_id, False, actor=current_actor())
    flash(f"Case type '{target['name']}' deactivated — hidden from new cases, existing records unaffected.", "success")
    return redirect(url_for("procedure_types.list_view"))


@bp.route("/<int:procedure_type_id>/activate", methods=["POST"])
@login_required
@role_required("admin")
def activate(procedure_type_id):
    validate_csrf(request.form.get("csrf_token"))
    target = db.get_procedure_type(procedure_type_id)
    if not target:
        abort(404)
    db.set_procedure_type_active(procedure_type_id, True, actor=current_actor())
    flash(f"Case type '{target['name']}' reactivated.", "success")
    return redirect(url_for("procedure_types.list_view"))
