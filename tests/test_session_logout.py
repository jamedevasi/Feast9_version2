"""Session logout: idle timeout (admin-configurable), a fixed maximum login length, and
revocation — deactivating an account or changing its password / 2FA / Google link signs it
out everywhere (THREAT_MODEL.md's two session gaps)."""
from datetime import datetime, timedelta, timezone

from app import db
from app.auth import ABSOLUTE_SESSION_HOURS
from tests.conftest import get_csrf
from tests.test_roles import _create_user, _login


def _ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _flash_after(client, resp):
    return client.get(resp.headers["Location"]).data.decode()


def _second_client(app, username, password="testpass123"):
    other = app.test_client()
    _login(other, username, password)
    assert other.get("/dashboard").status_code == 200
    return other


# ── Idle and maximum-length limits ─────────────────────────────────────────

def test_idle_session_is_signed_out_with_a_reason(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        sess["last_seen"] = _ago(minutes=31)
    resp = logged_in_client.get("/dashboard")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    assert "logged out after 30 minutes without activity" in _flash_after(logged_in_client, resp)
    assert logged_in_client.get("/dashboard").status_code == 302  # really gone, not just redirected once


def test_activity_keeps_the_session_alive(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        sess["last_seen"] = _ago(minutes=29)
    assert logged_in_client.get("/dashboard").status_code == 200
    with logged_in_client.session_transaction() as sess:
        refreshed = datetime.fromisoformat(sess["last_seen"])
    assert datetime.now(timezone.utc) - refreshed < timedelta(minutes=1)


def test_ping_counts_as_activity(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        sess["last_seen"] = _ago(minutes=29)
    assert logged_in_client.get("/session/ping").status_code == 204
    with logged_in_client.session_transaction() as sess:
        assert datetime.now(timezone.utc) - datetime.fromisoformat(sess["last_seen"]) < timedelta(minutes=1)


def test_idle_limit_is_configurable_and_validated(logged_in_client):
    token = get_csrf(logged_in_client, "/settings/")
    logged_in_client.post("/settings/", data={"form": "session_timeout", "session_idle_minutes": "10", "csrf_token": token})
    assert db.get_setting("session_idle_minutes") == "10"
    body = logged_in_client.get("/settings/").data.decode()
    assert 'name="session_idle_minutes" value="10"' in body
    assert 'data-idle-timeout="600"' in body  # the browser timer gets the same limit

    for bad in ("0", "4", "241", "abc"):
        token = get_csrf(logged_in_client, "/settings/")
        logged_in_client.post("/settings/", data={"form": "session_timeout", "session_idle_minutes": bad, "csrf_token": token})
        assert db.get_setting("session_idle_minutes") == "10"

    with logged_in_client.session_transaction() as sess:
        sess["last_seen"] = _ago(minutes=11)
    assert "logged out after 10 minutes" in _flash_after(logged_in_client, logged_in_client.get("/dashboard"))


def test_idle_limit_setting_is_admin_only(logged_in_client):
    _create_user(logged_in_client, "idledoc", "doctor")
    token = get_csrf(logged_in_client, "/dashboard")
    logged_in_client.post("/logout", data={"csrf_token": token})
    _login(logged_in_client, "idledoc")
    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post("/settings/", data={"form": "session_timeout", "session_idle_minutes": "240", "csrf_token": token})
    assert resp.status_code == 403
    assert db.get_setting("session_idle_minutes", "") == ""


def test_login_has_a_maximum_length_even_when_busy(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        sess["login_at"] = _ago(hours=ABSOLUTE_SESSION_HOURS, minutes=1)
    resp = logged_in_client.get("/dashboard")
    assert f"a login lasts at most {ABSOLUTE_SESSION_HOURS} hours" in _flash_after(logged_in_client, resp)


def test_session_from_before_this_change_must_log_in_again(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        del sess["login_at"]
    assert logged_in_client.get("/dashboard").status_code == 302


def test_idle_logout_form_explains_why(logged_in_client):
    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post("/logout", data={"csrf_token": token, "reason": "idle"})
    assert "without activity" in _flash_after(logged_in_client, resp)


def test_logout_requires_csrf(logged_in_client):
    assert logged_in_client.post("/logout", data={}).status_code == 400
    assert logged_in_client.get("/dashboard").status_code == 200


# ── Revocation ─────────────────────────────────────────────────────────────

def test_deactivating_a_user_signs_them_out_everywhere(app, logged_in_client):
    _create_user(logged_in_client, "leaver", "doctor")
    other = _second_client(app, "leaver")
    user_id = db.get_user_by_username("leaver")["id"]

    token = get_csrf(logged_in_client, "/users/")
    logged_in_client.post(f"/users/{user_id}/deactivate", data={"csrf_token": token})
    resp = other.get("/dashboard")
    assert "no longer active" in _flash_after(other, resp)
    assert logged_in_client.get("/users/").status_code == 200  # the admin who did it is unaffected


def test_changing_own_password_keeps_this_session_and_ends_others(app, logged_in_client):
    other = _second_client(app, "admin")
    token = get_csrf(logged_in_client, "/account/")
    logged_in_client.post("/account/", data={
        "form": "change_password", "current_password": "testpass123",
        "new_password": "newpass456", "confirm_password": "newpass456", "csrf_token": token,
    })
    assert logged_in_client.get("/dashboard").status_code == 200
    resp = other.get("/dashboard")
    assert "password or sign-in settings changed" in _flash_after(other, resp)


def test_admin_totp_reset_signs_the_user_out(app, logged_in_client):
    _create_user(logged_in_client, "totpuser", "receptionist")
    other = _second_client(app, "totpuser")
    user_id = db.get_user_by_username("totpuser")["id"]
    token = get_csrf(logged_in_client, "/users/")
    logged_in_client.post(f"/users/{user_id}/reset-totp", data={"csrf_token": token})
    assert other.get("/dashboard").status_code == 302
    assert logged_in_client.get("/users/").status_code == 200


def test_forgot_password_reset_ends_existing_sessions(app, logged_in_client):
    """Someone who reset the password via the security question ends any session a thief had."""
    thief = _second_client(app, "admin")
    user = db.get_user_by_username("admin")
    from app.auth import hash_password
    db.update_user_password(user["id"], hash_password("brandnew789"))
    assert thief.get("/dashboard").status_code == 302


def test_sign_in_starts_a_clean_session(client, setup_admin):
    """No pre-login session keys survive into the logged-in session."""
    with client.session_transaction() as sess:
        sess["reset_pending_user_id"] = 99
    _login(client, "admin")
    with client.session_transaction() as sess:
        assert "reset_pending_user_id" not in sess
        assert {"admin_id", "role", "session_version", "login_at", "last_seen", "reauth_at"} <= set(sess.keys())
