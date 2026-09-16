"""Backup creation and restore (§14 "Automated off-server backup"). See BACKUP.md for the
operational picture — scheduling, off-site destinations, and the restore-testing procedure
that is the acceptance bar for calling any backup "valid"."""
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken

from app import config as app_config
from app import db


class BackupError(Exception):
    pass


def _require_fernet():
    if not app_config.BACKUP_ENCRYPTION_KEY:
        raise BackupError(
            "BACKUP_ENCRYPTION_KEY is not set — refusing to create or read an unencrypted "
            'backup. Generate one with: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(app_config.BACKUP_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as exc:
        raise BackupError(f"BACKUP_ENCRYPTION_KEY is not a valid Fernet key: {exc}") from exc


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
    if not app_config.BACKUP_OFFSITE_COMMAND:
        return "not_configured"
    command = app_config.BACKUP_OFFSITE_COMMAND.replace("{file}", file_path)
    try:
        subprocess.run(command, shell=True, check=True, capture_output=True, timeout=600)
        return "success"
    except Exception as exc:
        return f"failed: {exc}"


def create_backup(actor=None):
    """Creates an encrypted, timestamped archive (DB + clinical_uploads) under
    DATA_DIR/backups/, records it in backup_log, and optionally pushes it off-site via
    BACKUP_OFFSITE_COMMAND. Returns the finished backup_log row on success; raises
    BackupError on failure (the row is still recorded as failed first)."""
    fernet = _require_fernet()  # fail fast, before creating a backup_log row at all
    backup_id = db.start_backup_log()

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
        return db.get_backup_log(backup_id)
    except Exception as exc:
        db.finish_backup_log(backup_id, "failed", error_message=str(exc))
        db.write_audit_now(actor, "backup_created", "backup", backup_id, outcome="failure", after_summary=str(exc))
        raise BackupError(f"Backup failed: {exc}") from exc


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
        raise BackupError("Could not decrypt backup — wrong BACKUP_ENCRYPTION_KEY or a corrupted file.") from exc

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
