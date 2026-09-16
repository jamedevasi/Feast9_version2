import functools
import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from flask import abort, redirect, request, session, url_for
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


def hash_password(password):
    return generate_password_hash(password, method=PBKDF2_METHOD)


def check_password(password_hash, password):
    return check_password_hash(password_hash, password)


def is_rate_limited(ip):
    return db.count_recent_failed_logins(ip, minutes=LOCKOUT_WINDOW_MINUTES) >= MAX_FAILED_ATTEMPTS


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("auth.login", next=request.path))
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
    reauth_at = session.get("reauth_at")
    if not reauth_at:
        return False
    try:
        ts = datetime.fromisoformat(reauth_at)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)  # tolerate the pre-fix naive-UTC format written by old sessions/tests
    return datetime.now(timezone.utc) - ts <= timedelta(minutes=REAUTH_WINDOW_MINUTES)


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
