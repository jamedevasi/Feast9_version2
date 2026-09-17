"""Bulk patient import (feast9_v2_agents.md §5.13 Settings "Import Data" card)."""
import io

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from app import excel_import
from app.auth import current_actor, login_required, reauth_required, role_required
from app.csrf import validate_csrf

bp = Blueprint("import_data", __name__, url_prefix="/import")


@bp.route("/")
@login_required
@role_required("admin")
def index():
    return render_template("import_data.html", result=None)


@bp.route("/template.xlsx")
@login_required
@role_required("admin")
def template():
    return send_file(
        io.BytesIO(excel_import.build_template_xlsx()),
        as_attachment=True,
        download_name="patient_import_template.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/patients", methods=["POST"])
@login_required
@role_required("admin")
@reauth_required
def import_patients():
    validate_csrf(request.form.get("csrf_token"))

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        flash("Choose a .xlsx file to import.", "warning")
        return redirect(url_for("import_data.index"))
    if not upload.filename.lower().endswith(".xlsx"):
        flash("Only .xlsx files are accepted.", "warning")
        return redirect(url_for("import_data.index"))

    result = excel_import.import_patients(upload.read(), actor=current_actor())

    if result.header_error:
        flash(result.header_error, "warning")
        return redirect(url_for("import_data.index"))

    if result.imported_count:
        flash(f"{result.imported_count} patient(s) imported.", "success")
    if result.skipped:
        flash(f"{len(result.skipped)} row(s) skipped — see details below.", "warning")
    if not result.imported_count and not result.skipped:
        flash("No data rows found in the spreadsheet.", "warning")

    return render_template("import_data.html", result=result)
