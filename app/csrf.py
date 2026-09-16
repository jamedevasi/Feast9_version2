import secrets

from flask import abort, session


def generate_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf(token):
    expected = session.get("csrf_token")
    if not expected or not token or not secrets.compare_digest(expected, token):
        abort(400, description="Invalid or missing CSRF token")
