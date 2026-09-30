"""Backup creation and restore (§14 "Automated off-server backup"). See BACKUP.md for the
operational picture — scheduling, off-site destinations, and the restore-testing procedure
that is the acceptance bar for calling any backup "valid".

Everything a clinic needs is configurable from the Backup & Data page (admin-only): the key
is created there ("Set Up Backups", stored in app_config.BACKUP_KEY_FILE, outside DATA_DIR),
and the daily time, a second-copy folder and how many backups to keep live in the settings
table. The env vars (BACKUP_ENCRYPTION_KEY, BACKUP_OFFSITE_COMMAND) still work and win.
"""
import glob
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken

from app import config as app_config
from app import db

log = logging.getLogger(__name__)

BACKUP_FILE_PATTERN = "feast9-backup-*.tar.enc"
DEFAULT_BACKUP_TIME = "21:00"
DEFAULT_KEEP_COUNT = 30
MAX_KEEP_COUNT = 365
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class BackupError(Exception):
    pass


def _require_fernet():
    key = app_config.backup_key()
    if not key:
        raise BackupError(
            "No backup key — set one up from the Backup & Data page (or set BACKUP_ENCRYPTION_KEY). "
            "Refusing to create or read an unencrypted backup."
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise BackupError(f"The backup key is not a valid Fernet key: {exc}") from exc


def is_configured():
    return bool(app_config.backup_key())


def create_key():
    """Generates the backup key and writes it to BACKUP_KEY_FILE. Refuses if any key is
    already configured — replacing it would make every existing backup unreadable."""
    if is_configured():
        raise BackupError("Backups are already set up.")
    key = Fernet.generate_key().decode()
    path = app_config.BACKUP_KEY_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:  # "x": never overwrite an existing key file
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # best effort — Windows ignores POSIX modes
    return key


# ── Settings (settings table) ──────────────────────────────────────────────

def get_settings():
    auto = db.get_setting("backup_auto_enabled", "1")
    keep = db.get_setting("backup_keep_count", str(DEFAULT_KEEP_COUNT))
    return {
        "auto_enabled": auto == "1",
        "time": db.get_setting("backup_time", DEFAULT_BACKUP_TIME) or DEFAULT_BACKUP_TIME,
        "copy_folder": db.get_setting("backup_copy_folder", ""),
        "keep_count": int(keep) if keep.isdigit() else DEFAULT_KEEP_COUNT,
    }


def validate_settings(auto_enabled, time_text, copy_folder, keep_text):
    """Returns (settings, errors) — errors are plain-language, shown on the page."""
    errors = []
    time_text = (time_text or "").strip()
    if not _TIME_RE.match(time_text):
        errors.append("Choose a time for the daily backup.")
    keep_text = (keep_text or "").strip()
    if not keep_text.isdigit() or not 1 <= int(keep_text) <= MAX_KEEP_COUNT:
        errors.append(f"Number of backups to keep must be from 1 to {MAX_KEEP_COUNT}.")
    folder = (copy_folder or "").strip().strip('"')
    if folder:
        folder_error = _check_copy_folder(folder)
        if folder_error:
            errors.append(folder_error)
    settings = {
        "auto_enabled": bool(auto_enabled), "time": time_text, "copy_folder": folder,
        "keep_count": int(keep_text) if keep_text.isdigit() else DEFAULT_KEEP_COUNT,
    }
    return settings, errors


def _check_copy_folder(folder):
    if not os.path.isabs(folder):
        return "The copy folder must be a full path, for example E:\\Feast9 Backups."
    data_dir = os.path.abspath(app_config.DATA_DIR)
    if os.path.commonpath([os.path.abspath(folder), data_dir]) == data_dir:
        return "The copy folder can't be inside Feast9's own data folder — pick a different drive or folder."
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".feast9-write-test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError:
        return (f"Feast9 can't save files in {folder}. Check the drive is connected and the folder "
                "isn't read-only.")
    return ""


def save_settings(settings, actor=None):
    db.set_setting("backup_auto_enabled", "1" if settings["auto_enabled"] else "0", actor=actor)
    db.set_setting("backup_time", settings["time"], actor=actor)
    db.set_setting("backup_copy_folder", settings["copy_folder"], actor=actor)
    db.set_setting("backup_keep_count", str(settings["keep_count"]), actor=actor)
    db.write_audit_now(
        actor, "backup_settings_updated", "backup", None,
        after_summary=(f"auto={'on' if settings['auto_enabled'] else 'off'}, time={settings['time']}, "
                       f"keep={settings['keep_count']}, copy_folder={settings['copy_folder'] or '—'}"),
    )


def has_second_copy():
    return bool(get_settings()["copy_folder"] or app_config.BACKUP_OFFSITE_COMMAND)


def _snapshot_db(dest_path):
    """A consistent copy of the live DB via sqlite3's own backup API — safe to run
    concurrently with WAL writers, unlike a plain file copy."""
    source = sqlite3.connect(app_config.DB_PATH)
    dest = sqlite3.connect(dest_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()


def _push_offsite(file_path):
    """Second copy: the folder chosen on the Backup & Data page if any, else the
    BACKUP_OFFSITE_COMMAND env var (a shell command — deliberately never settable from
    the web page), else none."""
    folder = get_settings()["copy_folder"]
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
            shutil.copy2(file_path, os.path.join(folder, os.path.basename(file_path)))
            return "success"
        except OSError as exc:
            return f"failed: {exc}"
    if not app_config.BACKUP_OFFSITE_COMMAND:
        return "not_configured"
    command = app_config.BACKUP_OFFSITE_COMMAND.replace("{file}", file_path)
    try:
        subprocess.run(command, shell=True, check=True, capture_output=True, timeout=600)
        return "success"
    except Exception as exc:
        return f"failed: {exc}"


def _prune_old_backups(keep):
    """Keeps the newest `keep` successful backups on this computer (older files deleted,
    their history rows marked 'removed') and the newest `keep` backup files in the copy
    folder — there, only files named like ours are ever touched."""
    backups_dir = os.path.abspath(app_config.backups_dir())
    successful = [e for e in db.list_backup_log(limit=10000) if e["status"] == "success"]
    for entry in successful[keep:]:
        path = os.path.abspath(entry["file_path"] or "")
        if path and os.path.dirname(path) == backups_dir and os.path.exists(path):
            try:
                os.remove(path)
            except OSError as exc:
                log.warning("Could not remove old backup %s: %s", path, exc)
                continue
        db.mark_backup_removed(entry["id"])

    folder = get_settings()["copy_folder"]
    if folder and os.path.isdir(folder):
        copies = sorted(glob.glob(os.path.join(folder, BACKUP_FILE_PATTERN)), reverse=True)  # names sort by time
        for path in copies[keep:]:
            try:
                os.remove(path)
            except OSError as exc:
                log.warning("Could not remove old backup copy %s: %s", path, exc)


def create_backup(actor=None, backup_id=None):
    """Creates an encrypted, timestamped archive (DB + clinical_uploads) under
    DATA_DIR/backups/, records it in backup_log, copies it to the second location if one is
    set, and prunes old backups. Returns the finished backup_log row on success; raises
    BackupError on failure (the row is still recorded as failed first). `backup_id` is a
    row the scheduler already claimed (db.claim_backup_run)."""
    try:
        fernet = _require_fernet()  # fail fast, before creating a backup_log row at all
    except BackupError as exc:
        if backup_id:
            db.finish_backup_log(backup_id, "failed", error_message=str(exc))
        raise
    backup_id = backup_id or db.start_backup_log()

    try:
        backups_dir = app_config.backups_dir()
        os.makedirs(backups_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        final_path = os.path.join(backups_dir, f"feast9-backup-{timestamp}.tar.enc")

        with tempfile.TemporaryDirectory() as tmp:
            db_copy_path = os.path.join(tmp, "feast9.db")
            _snapshot_db(db_copy_path)

            tar_path = os.path.join(tmp, "backup.tar")
            with tarfile.open(tar_path, "w") as tar:
                tar.add(db_copy_path, arcname="feast9.db")
                uploads_dir = os.path.join(app_config.DATA_DIR, "clinical_uploads")
                if os.path.isdir(uploads_dir):
                    tar.add(uploads_dir, arcname="clinical_uploads")

            with open(tar_path, "rb") as f:
                encrypted = fernet.encrypt(f.read())
            with open(final_path, "wb") as f:
                f.write(encrypted)

        file_size = os.path.getsize(final_path)
        offsite_status = _push_offsite(final_path)
        db.finish_backup_log(
            backup_id, "success", file_path=final_path, file_size=file_size, offsite_status=offsite_status
        )
        db.write_audit_now(
            actor, "backup_created", "backup", backup_id,
            after_summary=f"size={file_size} bytes, offsite={offsite_status}",
        )
    except Exception as exc:
        db.finish_backup_log(backup_id, "failed", error_message=str(exc))
        db.write_audit_now(actor, "backup_created", "backup", backup_id, outcome="failure", after_summary=str(exc))
        raise BackupError(f"Backup failed: {exc}") from exc

    try:
        _prune_old_backups(get_settings()["keep_count"])
    except Exception as exc:  # a pruning problem must never turn a good backup into a failure
        log.warning("Pruning old backups failed: %s", exc)
    return db.get_backup_log(backup_id)


# ── Daily automatic backup ─────────────────────────────────────────────────

def last_scheduled_time(now, time_text):
    """The most recent daily occurrence of HH:MM at or before `now`."""
    hour, minute = (int(x) for x in time_text.split(":"))
    today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return today if now >= today else today - timedelta(days=1)


def run_scheduled_backup_if_due(now=None):
    """Runs the daily backup if one is due: automatic backups on, a key set up, and no
    backup (manual or automatic) started since the most recent scheduled time. Catches up
    after a missed run — if the computer was off at 9 PM, the backup runs when Feast9 next
    starts. Returns the backup_log row, or None when nothing was due."""
    settings = get_settings()
    if not settings["auto_enabled"] or not is_configured():
        return None
    since = last_scheduled_time(now or datetime.now(), settings["time"]).strftime("%Y-%m-%d %H:%M:%S")
    backup_id = db.claim_backup_run(since)
    if not backup_id:
        return None
    try:
        return create_backup(backup_id=backup_id)
    except BackupError as exc:
        log.warning("Scheduled backup failed: %s", exc)
        return db.get_backup_log(backup_id)


def start_backup_scheduler(interval_seconds=60):
    """A daemon thread that checks once a minute whether the daily backup is due. Started
    by the real entry points (run.py, wsgi.py) — never by create_app(), so tests don't
    run backups. Several processes each starting one is fine: db.claim_backup_run lets
    only one of them run a given day's backup."""
    def loop():
        while True:
            try:
                run_scheduled_backup_if_due()
            except Exception:
                log.exception("Backup scheduler check failed")
            time.sleep(interval_seconds)

    thread = threading.Thread(target=loop, name="feast9-backup-scheduler", daemon=True)
    thread.start()
    return thread


def restore_backup(backup_file_path, force=False):
    """Restores a backup IN PLACE over the current DATA_DIR — intended to be run via
    restore_backup.py against a clean/staging DATA_DIR, never blindly against production.
    Makes a timestamped safety copy of the existing DB before overwriting it."""
    fernet = _require_fernet()
    if not os.path.exists(backup_file_path):
        raise BackupError(f"No such backup file: {backup_file_path}")

    with open(backup_file_path, "rb") as f:
        encrypted = f.read()
    try:
        plaintext = fernet.decrypt(encrypted)
    except InvalidToken as exc:
        raise BackupError("Could not decrypt backup — wrong backup key or a corrupted file.") from exc

    if os.path.exists(app_config.DB_PATH) and not force:
        raise BackupError(
            f"{app_config.DB_PATH} already exists — pass force=True (--force on the CLI) to "
            "overwrite it. A safety copy of the current database is made first either way."
        )

    os.makedirs(app_config.DATA_DIR, exist_ok=True)
    if os.path.exists(app_config.DB_PATH):
        safety_copy = f"{app_config.DB_PATH}.before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(app_config.DB_PATH, safety_copy)

    with tempfile.TemporaryDirectory() as tmp:
        tar_path = os.path.join(tmp, "backup.tar")
        with open(tar_path, "wb") as f:
            f.write(plaintext)

        with tarfile.open(tar_path, "r") as tar:
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name.split("/"):
                    raise BackupError(f"Unsafe path in backup archive, refusing to extract: {member.name}")
            tar.extractall(tmp)

        # Drop any stale WAL/SHM sidecar files first — otherwise the next connection could try
        # to replay a WAL journal that doesn't match the database file we're about to drop in.
        for suffix in ("-wal", "-shm"):
            sidecar = app_config.DB_PATH + suffix
            if os.path.exists(sidecar):
                os.remove(sidecar)
        shutil.copy2(os.path.join(tmp, "feast9.db"), app_config.DB_PATH)
        extracted_uploads = os.path.join(tmp, "clinical_uploads")
        if os.path.isdir(extracted_uploads):
            target_uploads = os.path.join(app_config.DATA_DIR, "clinical_uploads")
            if os.path.isdir(target_uploads):
                shutil.rmtree(target_uploads)
            shutil.copytree(extracted_uploads, target_uploads)
