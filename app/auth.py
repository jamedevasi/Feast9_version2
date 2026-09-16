import functools

from flask import redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import db

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
