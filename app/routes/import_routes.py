"""Bulk import and the Plan-B full-data export (feast9_v2_agents.md §5.13 Settings
"Import Data" card). Both are admin-only; the import POST and the export download are
reauth_required too, since §14 lists bulk import/export as high-risk actions. Their UI
lives on the Backup & Data page (backup_routes.render_backup_page)."""
import datetime
import io

from flask import Blueprint, flash, redirect, request, send_file, session, url_for

from app import db, excel_export, excel_import
from app.auth import current_actor, login_required, reauth_required, role_required
from app.csrf import validate_csrf
from app.routes.backup_routes import render_backup_page

bp = Blueprint("import_data", __name__, url_prefix="/import")

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _import_section():
    return redirect(url_for("backup.list_view", _anchor="import"))


@bp.route("/")
@login_required
@role_required("admin")
def index():
    """Old address of the Import & Export page — now a section of Backup & Data."""
    return _import_section()


@bp.route("/template.xlsx")
@login_required
@role_required("admin")
def template():
    return send_file(
        io.BytesIO(excel_import.build_template_xlsx()),
        as_attachment=True,
        download_name="feast9_capture_template.xlsx",
        mimetype=_XLSX,
    )


@bp.route("/export.xlsx")
@login_required
@role_required("admin")
@reauth_required
def export():
    content, snap = excel_export.build_export_xlsx(generated_by=session.get("username", ""))
    db.write_audit_now(
        current_actor(), "full_data_exported", "export", None,
        after_summary=f"{len(snap['patients'])} patients, {len(snap['cases'])} cases, "
                      f"{len(snap['payments'])} payments",
    )
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    return send_file(
        io.BytesIO(content),
        as_attachment=True,
        download_name=f"feast9_export_{stamp}.xlsx",
        mimetype=_XLSX,
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
        return _import_section()
    if not upload.filename.lower().endswith(".xlsx"):
        flash("Only .xlsx files are accepted.", "warning")
        return _import_section()

    result = excel_import.import_patients(upload.read(), actor=current_actor())

    if result.header_error:
        flash(result.header_error, "warning")
        return _import_section()

    if result.imported_count or result.cases_imported or result.payments_imported:
        flash(
            f"{result.imported_count} patient(s), {result.cases_imported} case(s) and "
            f"{result.payments_imported} payment(s) imported.",
            "success",
        )
    if result.skipped:
        flash(f"{len(result.skipped)} row(s) skipped — see details below.", "warning")
    if not (result.imported_count or result.cases_imported or result.payments_imported
            or result.skipped or result.unchanged_total):
        flash("No data rows found in the spreadsheet.", "warning")

    return render_backup_page(import_result=result)
