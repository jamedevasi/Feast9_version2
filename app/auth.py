import functools

from flask import abort, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.constants import NON_FINANCIAL_ROLES

PBKDF2_METHOD = "pbkdf2:sha256"
MAX_FAILED_ATTEMPTS = 8
LOCKOUT_WINDOW_MINUTES = 15


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
