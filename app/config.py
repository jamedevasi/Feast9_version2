import os

DEFAULT_SECRET_KEY = "dev-insecure-default-change-me"

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
DB_PATH = os.path.join(DATA_DIR, "feast9.db")
SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)

# Backups (§14 "Automated off-server backup") — a Fernet key, independent of SECRET_KEY so
# losing/rotating one doesn't compromise the other. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
BACKUP_ENCRYPTION_KEY = os.environ.get("BACKUP_ENCRYPTION_KEY", "")

# Optional shell command to push the encrypted backup off-site (rclone/rsync to S3, Backblaze
# B2, or a second server — see BACKUP.md). "{file}" is replaced with the backup's local path.
# The provider is an intentionally deferred operational decision (feast9_v2_agents.md §15) —
# unset means the backup stays local-only.
BACKUP_OFFSITE_COMMAND = os.environ.get("BACKUP_OFFSITE_COMMAND", "")


def backups_dir():
    """A function, not a module-level constant, so it follows DATA_DIR when tests monkeypatch it."""
    return os.path.join(DATA_DIR, "backups")


def branding_dir():
    """Uploaded login-screen images (§5.12) — same DATA_DIR-follows-monkeypatch reasoning as backups_dir()."""
    return os.path.join(DATA_DIR, "branding")


def uploads_dir():
    """Consent signatures — feast9_v2_agents.md's directory layout names this 'uploads/',
    distinct from clinical_uploads/ (X-rays/photos/lab reports) and branding/."""
    return os.path.join(DATA_DIR, "uploads")
