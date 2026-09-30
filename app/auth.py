import functools
import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from flask import abort, flash, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.constants import NON_FINANCIAL_ROLES

PBKDF2_METHOD = "pbkdf2:sha256"
MAX_FAILED_ATTEMPTS = 8
LOCKOUT_WINDOW_MINUTES = 15

# "Require re-authentication (not just an active session) before high-risk actions"
# (feast9_v2_agents.md §14). A fresh login already counts — reauth_at is set at
# login — so only a session that has been idle past this window must step up again.
REAUTH_WINDOW_MINUTES = 10
RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I — avoids transcription errors

# Session lifetime (THREAT_MODEL.md's "no idle/absolute session timeout" gap). The idle limit
# is an admin setting (Settings > Automatic Logout); the absolute limit is fixed — even a
# session kept busy all day must sign in again after this long.
DEFAULT_IDLE_MINUTES = 30
MIN_IDLE_MINUTES = 5
MAX_IDLE_MINUTES = 240
ABSOLUTE_SESSION_HOURS = 12


def hash_password(password):
    return generate_password_hash(password, method=PBKDF2_METHOD)


def check_password(password_hash, password):
    return check_password_hash(password_hash, password)


def is_rate_limited(ip):
    return db.count_recent_failed_logins(ip, minutes=LOCKOUT_WINDOW_MINUTES) >= MAX_FAILED_ATTEMPTS


def _utcnow():
    return datetime.now(timezone.utc)


def _parse_ts(value):
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def idle_timeout_minutes():
    raw = db.get_setting("session_idle_minutes", str(DEFAULT_IDLE_MINUTES))
    minutes = int(raw) if raw.isdigit() else DEFAULT_IDLE_MINUTES
    return min(max(minutes, MIN_IDLE_MINUTES), MAX_IDLE_MINUTES)


def start_session(user):
    """The one place a login becomes a session — password, 2FA and Google sign-in all call
    it. Starts from an empty session (no pre-login keys carried over), and records when it
    started, when it was last used and the user's session_version (see login_required)."""
    session.clear()
    now = _utcnow().isoformat()
    session["admin_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["session_version"] = user["session_version"]
    session["login_at"] = now
    session["last_seen"] = now
    mark_reauthenticated()


def refresh_session_version():
    """After a user changes their own password / 2FA / Google link, keep *this* session
    signed in — the change bumped session_version, which ends every other session."""
    user = db.get_user_by_id(session.get("admin_id"))
    if user:
        session["session_version"] = user["session_version"]


def _session_end_reason():
    """Why the current session must end, or None if it's still valid."""
    user = db.get_user_by_id(session.get("admin_id"))
    if not user or not user["is_active"]:
        return "Your account is no longer active. Contact the clinic's administrator."
    if session.get("session_version") != user["session_version"]:
        return "You've been signed out because the account's password or sign-in settings changed. Please log in again."
    now = _utcnow()
    login_at = _parse_ts(session.get("login_at"))
    if login_at is None:
        return "Please log in again."
    if now - login_at > timedelta(hours=ABSOLUTE_SESSION_HOURS):
        return f"For security, a login lasts at most {ABSOLUTE_SESSION_HOURS} hours. Please log in again."
    last_seen = _parse_ts(session.get("last_seen")) or login_at
    idle = idle_timeout_minutes()
    if now - last_seen > timedelta(minutes=idle):
        return f"You were logged out after {idle} minutes without activity."
    return None


def login_required(view):
    """A valid session is: an existing, active user; the user's current session_version
    (bumped by deactivation or a password / 2FA / Google-link change); not older than
    ABSOLUTE_SESSION_HOURS; used within the idle timeout. Anything else is signed out here,
    server-side, with a message saying why."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("auth.login", next=request.path))
        reason = _session_end_reason()
        if reason:
            session.clear()
            flash(reason, "warning")
            return redirect(url_for("auth.login", next=request.path))
        session["last_seen"] = _utcnow().isoformat()
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    """Must be applied after (below) @login_required so a session already exists."""
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def financial_access_required(view):
    """Blocks the receptionist role from every payment/cost route — never UI-only."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") in NON_FINANCIAL_ROLES:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def can_view_financial_data():
    return session.get("role") not in NON_FINANCIAL_ROLES


def current_actor():
    """Actor dict for db.py's audit-log writers — never store more than id/role/ip/UA."""
    return {
        "user_id": session.get("admin_id"),
        "role": session.get("role", ""),
        "ip": request.remote_addr or "",
        "user_agent": (request.headers.get("User-Agent") or "")[:255],
    }


# ── TOTP 2FA ─────────────────────────────────────────────────────────────

def generate_totp_secret():
    return pyotp.random_base32()


def totp_provisioning_uri(secret, username):
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name="Feast9")


def verify_totp_code(secret, code):
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def generate_recovery_codes(count=8):
    return [
        "-".join("".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(4)) for _ in range(2))
        for _ in range(count)
    ]


def hash_recovery_code(code):
    return hash_password(code.strip().upper())


def check_recovery_code(code_hash, code):
    return check_password(code_hash, code.strip().upper())


# ── Step-up re-authentication ───────────────────────────────────────────

def mark_reauthenticated():
    session["reauth_at"] = datetime.now(timezone.utc).isoformat()


def is_reauthenticated():
    # _parse_ts tolerates the pre-fix naive-UTC format written by old sessions/tests.
    ts = _parse_ts(session.get("reauth_at"))
    if ts is None:
        return False
    return _utcnow() - ts <= timedelta(minutes=REAUTH_WINDOW_MINUTES)


def reauth_required(view):
    """Must be applied after (below) @login_required. Redirects to a password
    (+ TOTP, if enabled) re-entry challenge when the session's last authentication
    event is older than REAUTH_WINDOW_MINUTES — a long-idle session is not enough
    on its own for user management / TOTP reset, per §14."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not is_reauthenticated():
            session["reauth_next"] = request.full_path if request.method == "GET" else request.referrer
            return redirect(url_for("auth.reauth"))
        return view(*args, **kwargs)

    return wrapped
