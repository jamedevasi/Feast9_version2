"""Backup & Data page: the encrypted system backup (app/backup.py) — set up and configured
right here — plus the Plan-B Excel export and the Excel import (both served by
import_routes.py, rendered here so all the ways of getting data out of / into Feast9 live on
one admin page). Page wording is for clinic staff: no file names, settings keys or jargon."""
import datetime
import os

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for

from app import backup as backup_module
from app import config as app_config
from app import db
from app.auth import current_actor, login_required, reauth_required, role_required
from app.backup import BackupError, create_backup
from app.csrf import validate_csrf

bp = Blueprint("backup", __name__, url_prefix="/backup")

# A daily backup plus a couple of hours' slack.
BACKUP_STALE_HOURS = 26


def _age_text(timestamp):
    try:
        then = datetime.datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return ""
    hours = (datetime.datetime.now() - then).total_seconds() / 3600
    if hours < 1:
        return "less than an hour ago"
    if hours < 48:
        return f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"
    return f"{int(hours // 24)} days ago"


def _time_label(hhmm):
    """'21:00' -> '9:00 PM'."""
    try:
        return datetime.datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return hhmm


def _backup_status(entries, settings):
    configured = backup_module.is_configured()
    last_ok = next((e for e in entries if e["status"] == "success"), None)
    latest = next((e for e in entries if e["status"] != "removed"), None)
    stale = False
    if last_ok:
        try:
            stale = (datetime.datetime.now() - datetime.datetime.fromisoformat(last_ok["started_at"])
                     ).total_seconds() > BACKUP_STALE_HOURS * 3600
        except (TypeError, ValueError):
            stale = False

    if not configured:
        level, message = "danger", "Backups aren't set up yet. Click Set Up Backups below — it takes a few seconds."
    elif latest and latest["status"] == "failed":
        level, message = "danger", ("The last backup didn't finish. Click Back Up Now to try again. If a second "
                                    "copy folder is set, check that drive is connected.")
    elif not last_ok:
        level, message = "warning", "No backup has been made yet. Click Back Up Now to make the first one."
    elif stale and settings["auto_enabled"]:
        level, message = "warning", (f"The last backup is more than {BACKUP_STALE_HOURS} hours old. Automatic "
                                     "backups only run while Feast9 is running — click Back Up Now.")
    elif stale:
        level, message = "warning", ("The last backup is more than a day old and automatic backups are off. "
                                     "Turn them on below, or click Back Up Now.")
    else:
        level, message = "ok", "Backups are up to date."
    return {
        "configured": configured,
        "level": level,
        "message": message,
        "last_ok": last_ok,
        "last_ok_age": _age_text(last_ok["started_at"]) if last_ok else "",
        "offsite_configured": backup_module.has_second_copy(),
    }


def render_backup_page(import_result=None, settings_form=None, settings_errors=None):
    entries = db.list_backup_log()
    settings = backup_module.get_settings()
    last_export = db.get_last_audit_event("full_data_exported")
    return render_template(
        "backup_list.html",
        entries=entries,
        status=_backup_status(entries, settings),
        settings=settings_form or settings,
        settings_errors=settings_errors or [],
        backup_time_label=_time_label(settings["time"]),
        max_keep=backup_module.MAX_KEEP_COUNT,
        last_export=last_export,
        last_export_age=_age_text(last_export["ts_utc"]) if last_export else "",
        result=import_result,
    )


@bp.route("/")
@login_required
@role_required("admin")
def list_view():
    return render_backup_page()


@bp.route("/setup", methods=["POST"])
@login_required
@role_required("admin")
@reauth_required
def setup():
    """One click: create the key, keep the default schedule, make the first backup, and
    show the key once so the admin can store it safely."""
    validate_csrf(request.form.get("csrf_token"))
    try:
        key = backup_module.create_key()
    except (BackupError, OSError) as exc:
        current_app.logger.warning("Backup setup failed: %s", exc)
        flash("Backups couldn't be set up — they may already be set up. Reload this page to check.", "warning")
        return redirect(url_for("backup.list_view"))
    db.write_audit_now(current_actor(), "backup_key_created", "backup", None)
    try:
        create_backup(actor=current_actor())
        first_backup_ok = True
    except BackupError as exc:
        current_app.logger.warning("First backup after setup failed: %s", exc)
        first_backup_ok = False
    return render_template("backup_key.html", key=key, just_created=True, first_backup_ok=first_backup_ok)


@bp.route("/key")
@login_required
@role_required("admin")
@reauth_required
def show_key():
    if not backup_module.is_configured():
        return redirect(url_for("backup.list_view"))
    db.write_audit_now(current_actor(), "backup_key_viewed", "backup", None)
    return render_template("backup_key.html", key=app_config.backup_key(), just_created=False)


@bp.route("/settings", methods=["POST"])
@login_required
@role_required("admin")
@reauth_required
def save_settings():
    validate_csrf(request.form.get("csrf_token"))
    settings, errors = backup_module.validate_settings(
        request.form.get("auto_enabled"), request.form.get("backup_time"),
        request.form.get("copy_folder"), request.form.get("keep_count"),
    )
    if errors:
        return render_backup_page(settings_form=settings, settings_errors=errors)
    backup_module.save_settings(settings, actor=current_actor())
    flash("Backup settings saved.", "success")
    return redirect(url_for("backup.list_view", _anchor="system-backup"))


@bp.route("/run", methods=["POST"])
@login_required
@role_required("admin")
@reauth_required
def run():
    validate_csrf(request.form.get("csrf_token"))
    try:
        row = create_backup(actor=current_actor())
        if row["offsite_status"].startswith("failed"):
            flash("Backup made, but the copy to the second folder didn't work — check that drive is connected.",
                  "warning")
        else:
            flash("Backup completed.", "success")
    except BackupError as exc:
        # The technical reason goes to the server log; the person at the desk needs to know
        # what to do next, not which setting is missing.
        current_app.logger.warning("Backup failed: %s", exc)
        flash("The backup couldn't be made. Try again in a minute; if it keeps failing, check the "
              "computer has free disk space.", "warning")
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
