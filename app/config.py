import os
import secrets

DEFAULT_SECRET_KEY = "dev-insecure-default-change-me"
# Values published in this repo's own docs/scripts (start.bat, README, the spec). Anyone who
# knows the key signing the session cookie can forge an admin login, so these are never used.
KNOWN_PUBLIC_SECRET_KEYS = {DEFAULT_SECRET_KEY, "local-dev-key"}

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
DB_PATH = os.path.join(DATA_DIR, "feast9.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "")


def secret_key_file():
    """A function so it follows DATA_DIR when tests monkeypatch it (same as backups_dir())."""
    return os.path.join(DATA_DIR, "secret_key")


def secret_key():
    """The key that signs session cookies: SECRET_KEY from the environment if it's set and
    not a publicly known value; otherwise a random key generated once and kept in
    DATA_DIR/secret_key (never in the repo, and not part of backups — a restored install
    just generates a new one and everyone signs in again). Called by create_app()."""
    if SECRET_KEY and SECRET_KEY not in KNOWN_PUBLIC_SECRET_KEYS:
        return SECRET_KEY
    path = secret_key_file()
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        # O_EXCL: when several worker processes start together, exactly one creates the key
        # and the rest read it.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
        raise RuntimeError(f"{path} is empty — delete it and restart to generate a new key.")
    key = secrets.token_hex(32)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key)
    return key

# Backups (§14 "Automated off-server backup") — a Fernet key, independent of SECRET_KEY so
# losing/rotating one doesn't compromise the other. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
BACKUP_ENCRYPTION_KEY = os.environ.get("BACKUP_ENCRYPTION_KEY", "")

# Where the key lives when an admin creates it from the Backup & Data page ("Set Up
# Backups") instead of setting the env var above. Deliberately outside DATA_DIR: a copy of
# the data folder (a synced folder, a stolen USB stick) must not carry the key with it.
BACKUP_KEY_FILE = os.environ.get(
    "BACKUP_KEY_FILE", os.path.join(os.path.expanduser("~"), ".feast9", "backup.key")
)


def backup_key():
    """The backup encryption key: the env var if set, else the key file, else ''. A function,
    read fresh each time, so a key created from the web page takes effect without a restart
    (and tests can monkeypatch both sources)."""
    if BACKUP_ENCRYPTION_KEY:
        return BACKUP_ENCRYPTION_KEY
    try:
        with open(BACKUP_KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""

# Optional shell command to push the encrypted backup off-site (rclone/rsync to S3, Backblaze
# B2, or a second server — see BACKUP.md). "{file}" is replaced with the backup's local path.
# The provider is an intentionally deferred operational decision (feast9_v2_agents.md §15) —
# unset means the backup stays local-only.
BACKUP_OFFSITE_COMMAND = os.environ.get("BACKUP_OFFSITE_COMMAND", "")

# Google sign-in (§14) — optional/secondary alternate login path, never the only one.
# Unset (the default) means the feature is simply absent: no button on the login page,
# no routes exposed. Get these from a Google Cloud Console OAuth 2.0 Client ID (Web
# application type) — the redirect URI registered there must exactly match this app's
# /login/google/callback URL for the deployed domain.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")


def trusted_proxy_count():
    """How many reverse proxies (Caddy, nginx, IIS…) sit in front of Feast9, from
    TRUSTED_PROXY_COUNT. 0 (the default) means none: X-Forwarded-For/-Proto/-Host are ignored,
    because without a proxy anyone could send them to fake their address and slip past the
    per-IP sign-in limit. Set it to 1 behind a single proxy so the client's real address
    reaches the sign-in limit and the audit log, and Google sign-in builds https:// links.
    Read fresh, like the other settings here."""
    raw = os.environ.get("TRUSTED_PROXY_COUNT", "").strip()
    if not raw.isdigit():
        return 0
    return min(int(raw), 5)


def google_signin_enabled():
    """A function, not a module-level constant, for the same DATA_DIR-staleness reason
    as backups_dir() — read fresh so tests can monkeypatch it after import."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


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
