import re

import pyotp

from app import db
from tests.conftest import get_csrf

SECRET_RE = re.compile(r"<code>([A-Z2-7]+)</code>")
RECOVERY_CODE_RE = re.compile(r"<code>([A-Z0-9-]{9})</code>")


def _extract_secret(html):
    return SECRET_RE.search(html).group(1)


def _enable_totp(client):
    """Walks the logged-in client through TOTP setup, returns (secret, recovery_codes)."""
    resp = client.get("/totp/setup")
    secret = _extract_secret(resp.data.decode())
    token = get_csrf(client, "/totp/setup")
    code = pyotp.TOTP(secret).now()
    resp = client.post("/totp/setup", data={"code": code, "csrf_token": token})
    assert resp.status_code == 302

    codes_resp = client.get("/totp/recovery-codes")
    codes = RECOVERY_CODE_RE.findall(codes_resp.data.decode())
    return secret, codes


def _logout(client):
    token = get_csrf(client, "/dashboard")
    client.post("/logout", data={"csrf_token": token})


def _login_password_step(client, username, password="testpass123"):
    token = get_csrf(client, "/login")
    return client.post("/login", data={"username": username, "password": password, "csrf_token": token})


def test_setup_page_shows_qr_and_secret(logged_in_client):
    resp = logged_in_client.get("/totp/setup")
    assert resp.status_code == 200
    assert b"<svg" in resp.data
    assert SECRET_RE.search(resp.data.decode())


def test_enable_with_invalid_code_rejected(logged_in_client):
    logged_in_client.get("/totp/setup")
    token = get_csrf(logged_in_client, "/totp/setup")
    resp = logged_in_client.post("/totp/setup", data={"code": "000000", "csrf_token": token})
    assert resp.status_code == 200
    assert b"didn" in resp.data
    admin = db.get_admin()
    assert db.get_user_by_id(admin["id"])["totp_enabled"] == 0


def test_enable_with_valid_code_shows_recovery_codes_and_persists(logged_in_client):
    secret, codes = _enable_totp(logged_in_client)
    assert len(codes) == 8
    admin = db.get_admin()
    user = db.get_user_by_id(admin["id"])
    assert user["totp_enabled"] == 1
    assert user["totp_secret"] == secret


def test_login_with_totp_enabled_requires_second_step(logged_in_client):
    secret, _codes = _enable_totp(logged_in_client)
    admin = db.get_admin()
    username = admin["username"]

    _logout(logged_in_client)
    resp = _login_password_step(logged_in_client, username)
    assert resp.status_code == 302
    assert "/login/totp" in resp.headers["Location"]

    # Dashboard is not accessible yet — the second factor hasn't been verified.
    dash_resp = logged_in_client.get("/dashboard")
    assert dash_resp.status_code == 302
    assert "/login" in dash_resp.headers["Location"]

    token = get_csrf(logged_in_client, "/login/totp")
    code = pyotp.TOTP(secret).now()
    resp = logged_in_client.post("/login/totp", data={"code": code, "csrf_token": token})
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]

    dash_resp = logged_in_client.get("/dashboard")
    assert dash_resp.status_code == 200


def test_login_with_wrong_totp_code_rejected(logged_in_client):
    _enable_totp(logged_in_client)
    admin = db.get_admin()
    _logout(logged_in_client)
    _login_password_step(logged_in_client, admin["username"])

    token = get_csrf(logged_in_client, "/login/totp")
    resp = logged_in_client.post("/login/totp", data={"code": "000000", "csrf_token": token})
    assert resp.status_code == 200
    assert b"Invalid" in resp.data


def test_login_with_recovery_code_succeeds_once(logged_in_client):
    _secret, codes = _enable_totp(logged_in_client)
    admin = db.get_admin()
    _logout(logged_in_client)
    _login_password_step(logged_in_client, admin["username"])

    token = get_csrf(logged_in_client, "/login/totp")
    resp = logged_in_client.post(
        "/login/totp", data={"recovery_code": codes[0], "csrf_token": token}
    )
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]

    # Reusing the same recovery code must fail — one-time use.
    _logout(logged_in_client)
    _login_password_step(logged_in_client, admin["username"])
    token = get_csrf(logged_in_client, "/login/totp")
    resp = logged_in_client.post(
        "/login/totp", data={"recovery_code": codes[0], "csrf_token": token}
    )
    assert resp.status_code == 200
    assert b"Invalid" in resp.data


def test_disable_totp_self_service(logged_in_client):
    _enable_totp(logged_in_client)
    admin = db.get_admin()
    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post("/totp/disable", data={"csrf_token": token})
    assert resp.status_code == 302
    assert db.get_user_by_id(admin["id"])["totp_enabled"] == 0


def test_admin_can_reset_another_users_totp(logged_in_client):
    token = get_csrf(logged_in_client, "/users/new")
    logged_in_client.post(
        "/users/new",
        data={
            "username": "doc_totp",
            "password": "testpass123",
            "confirm": "testpass123",
            "role": "doctor",
            "security_question": "Q",
            "security_answer": "A",
            "csrf_token": token,
        },
    )
    doc = next(u for u in db.list_users() if u["username"] == "doc_totp")

    _logout(logged_in_client)
    _login_password_step(logged_in_client, "doc_totp")
    _enable_totp(logged_in_client)
    assert db.get_user_by_id(doc["id"])["totp_enabled"] == 1

    _logout(logged_in_client)
    admin = db.get_admin()
    _login_password_step(logged_in_client, admin["username"])

    token = get_csrf(logged_in_client, "/users/")
    resp = logged_in_client.post(f"/users/{doc['id']}/reset-totp", data={"csrf_token": token})
    assert resp.status_code == 302
    assert db.get_user_by_id(doc["id"])["totp_enabled"] == 0


def test_stale_session_must_reauthenticate_before_creating_user(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        sess["reauth_at"] = "2020-01-01T00:00:00"

    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post(
        "/users/new",
        data={
            "username": "shouldnotexist",
            "password": "testpass123",
            "confirm": "testpass123",
            "role": "doctor",
            "security_question": "Q",
            "security_answer": "A",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 302
    assert "/reauth" in resp.headers["Location"]
    assert not db.username_exists("shouldnotexist")


def test_reauth_with_correct_password_restores_access(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        sess["reauth_at"] = "2020-01-01T00:00:00"

    logged_in_client.get("/users/new")  # trips reauth_required's redirect, sets reauth_next
    token = get_csrf(logged_in_client, "/reauth")
    resp = logged_in_client.post("/reauth", data={"password": "testpass123", "csrf_token": token})
    assert resp.status_code == 302

    token = get_csrf(logged_in_client, "/users/new")
    resp = logged_in_client.post(
        "/users/new",
        data={
            "username": "afterreauth",
            "password": "testpass123",
            "confirm": "testpass123",
            "role": "doctor",
            "security_question": "Q",
            "security_answer": "A",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 302
    assert db.username_exists("afterreauth")


def test_reauth_with_wrong_password_rejected(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        sess["reauth_at"] = "2020-01-01T00:00:00"

    token = get_csrf(logged_in_client, "/reauth")
    resp = logged_in_client.post("/reauth", data={"password": "wrongpassword", "csrf_token": token})
    assert resp.status_code == 200
    assert b"Incorrect password" in resp.data
