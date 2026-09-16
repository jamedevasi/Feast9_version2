import os

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

from app import db
from app.auth import current_actor, login_required, reauth_required, role_required
from app.backup import BackupError, create_backup
from app.csrf import validate_csrf

bp = Blueprint("backup", __name__, url_prefix="/backup")


@bp.route("/")
@login_required
@role_required("admin")
def list_view():
    return render_template("backup_list.html", entries=db.list_backup_log())


@bp.route("/run", methods=["POST"])
@login_required
@role_required("admin")
@reauth_required
def run():
    validate_csrf(request.form.get("csrf_token"))
    try:
        row = create_backup(actor=current_actor())
        flash(f"Backup completed ({row['file_size']} bytes).", "success")
    except BackupError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("backup.list_view"))


@bp.route("/<int:backup_id>/download")
@login_required
@role_required("admin")
@reauth_required
def download(backup_id):
    entry = db.get_backup_log(backup_id)
    if not entry or entry["status"] != "success" or not os.path.exists(entry["file_path"]):
        abort(404)
    db.write_audit_now(
        current_actor(), "backup_downloaded", "backup", backup_id,
        after_summary=f"size={entry['file_size']} bytes",
    )
    return send_file(entry["file_path"], as_attachment=True, download_name=os.path.basename(entry["file_path"]))
