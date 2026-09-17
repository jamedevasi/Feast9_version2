from app import db
from tests.conftest import get_csrf
from tests.test_roles import _create_user, _login, _logout


# ── Change Password (self-service, /account) ────────────────────────────────

def test_change_password_with_correct_current_password(logged_in_client):
    token = get_csrf(logged_in_client, "/account/")
    resp = logged_in_client.post(
        "/account/",
        data={
            "form": "change_password", "current_password": "testpass123",
            "new_password": "newpass456", "confirm_password": "newpass456", "csrf_token": token,
        },
    )
    assert resp.status_code == 302

    _logout(logged_in_client)
    token = get_csrf(logged_in_client, "/login")
    resp2 = logged_in_client.post(
        "/login", data={"username": "admin", "password": "newpass456", "csrf_token": token}
    )
    assert resp2.status_code == 302
    assert resp2.headers["Location"].endswith("/dashboard") or "dashboard" in resp2.headers["Location"]


def test_change_password_rejects_wrong_current_password(logged_in_client):
    token = get_csrf(logged_in_client, "/account/")
    logged_in_client.post(
        "/account/",
        data={
            "form": "change_password", "current_password": "wrongpass",
            "new_password": "newpass456", "confirm_password": "newpass456", "csrf_token": token,
        },
    )
    follow = logged_in_client.get("/account/")
    assert b"Current password is incorrect" in follow.data

    _logout(logged_in_client)
    token = get_csrf(logged_in_client, "/login")
    resp = logged_in_client.post(
        "/login", data={"username": "admin", "password": "testpass123", "csrf_token": token}
    )
    assert resp.status_code == 302  # old password still works


def test_change_password_rejects_mismatched_confirmation(logged_in_client):
    token = get_csrf(logged_in_client, "/account/")
    logged_in_client.post(
        "/account/",
        data={
            "form": "change_password", "current_password": "testpass123",
            "new_password": "newpass456", "confirm_password": "different789", "csrf_token": token,
        },
    )
    follow = logged_in_client.get("/account/")
    assert b"do not match" in follow.data


def test_change_password_rejects_short_password(logged_in_client):
    token = get_csrf(logged_in_client, "/account/")
    logged_in_client.post(
        "/account/",
        data={
            "form": "change_password", "current_password": "testpass123",
            "new_password": "short", "confirm_password": "short", "csrf_token": token,
        },
    )
    follow = logged_in_client.get("/account/")
    assert b"at least 8 characters" in follow.data


def test_change_password_is_audited(logged_in_client):
    token = get_csrf(logged_in_client, "/account/")
    logged_in_client.post(
        "/account/",
        data={
            "form": "change_password", "current_password": "testpass123",
            "new_password": "newpass456", "confirm_password": "newpass456", "csrf_token": token,
        },
    )
    actions = [e["action"] for e in db.list_audit_log()]
    assert "password_changed" in actions


# ── Security Question (self-service, /account) ──────────────────────────────

def test_update_security_question(logged_in_client):
    token = get_csrf(logged_in_client, "/account/")
    resp = logged_in_client.post(
        "/account/",
        data={
            "form": "security_question", "current_password": "testpass123",
            "security_question": "Favourite color?", "security_answer": "Blue", "csrf_token": token,
        },
    )
    assert resp.status_code == 302
    follow = logged_in_client.get("/account/")
    assert b"Favourite color?" in follow.data


def test_update_security_question_requires_correct_password(logged_in_client):
    token = get_csrf(logged_in_client, "/account/")
    logged_in_client.post(
        "/account/",
        data={
            "form": "security_question", "current_password": "wrongpass",
            "security_question": "Favourite color?", "security_answer": "Blue", "csrf_token": token,
        },
    )
    follow = logged_in_client.get("/account/")
    assert b"Current password is incorrect" in follow.data
    assert b"Favourite color?" not in follow.data


def test_security_question_change_is_audited(logged_in_client):
    token = get_csrf(logged_in_client, "/account/")
    logged_in_client.post(
        "/account/",
        data={
            "form": "security_question", "current_password": "testpass123",
            "security_question": "Favourite color?", "security_answer": "Blue", "csrf_token": token,
        },
    )
    actions = [e["action"] for e in db.list_audit_log()]
    assert "security_question_changed" in actions


# ── Any role can manage their own account (not admin-gated like /settings) ──

def test_receptionist_can_access_my_account_and_change_own_password(logged_in_client, patient_id):
    _create_user(logged_in_client, "recepacct", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recepacct")

    assert logged_in_client.get("/account/").status_code == 200
    assert logged_in_client.get("/settings/").status_code == 403  # still admin-only

    token = get_csrf(logged_in_client, "/account/")
    resp = logged_in_client.post(
        "/account/",
        data={
            "form": "change_password", "current_password": "testpass123",
            "new_password": "receppass456", "confirm_password": "receppass456", "csrf_token": token,
        },
    )
    assert resp.status_code == 302

    _logout(logged_in_client)
    token = get_csrf(logged_in_client, "/login")
    resp2 = logged_in_client.post(
        "/login", data={"username": "recepacct", "password": "receppass456", "csrf_token": token}
    )
    assert resp2.status_code == 302


def test_my_account_link_visible_to_all_roles(logged_in_client, patient_id):
    _create_user(logged_in_client, "recepnav", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recepnav")

    resp = logged_in_client.get("/dashboard")
    assert b'href="/account/"' in resp.data


# ── Forgot Password (public, unauthenticated) ────────────────────────────────

def test_forgot_password_shows_security_question(setup_admin):
    token = get_csrf(setup_admin, "/forgot-password")
    resp = setup_admin.post(
        "/forgot-password", data={"username": "admin", "csrf_token": token}
    )
    assert resp.status_code == 302
    assert "/forgot-password/verify" in resp.headers["Location"]

    follow = setup_admin.get("/forgot-password/verify")
    assert b"City?" in follow.data


def test_forgot_password_unknown_username_rejected(setup_admin):
    token = get_csrf(setup_admin, "/forgot-password")
    resp = setup_admin.post(
        "/forgot-password", data={"username": "nosuchuser", "csrf_token": token}
    )
    assert b"No account found" in resp.data


def test_forgot_password_verify_blocked_without_step_one(setup_admin):
    resp = setup_admin.get("/forgot-password/verify")
    assert resp.status_code == 302
    assert "/forgot-password" in resp.headers["Location"]


def test_forgot_password_full_reset_flow(setup_admin):
    token = get_csrf(setup_admin, "/forgot-password")
    setup_admin.post("/forgot-password", data={"username": "admin", "csrf_token": token})

    token = get_csrf(setup_admin, "/forgot-password/verify")
    resp = setup_admin.post(
        "/forgot-password/verify",
        data={
            "security_answer": "Test", "new_password": "resetpass456",
            "confirm_password": "resetpass456", "csrf_token": token,
        },
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    token = get_csrf(setup_admin, "/login")
    login_resp = setup_admin.post(
        "/login", data={"username": "admin", "password": "resetpass456", "csrf_token": token}
    )
    assert login_resp.status_code == 302
    assert "dashboard" in login_resp.headers["Location"]


def test_forgot_password_verify_rejects_wrong_answer(setup_admin):
    token = get_csrf(setup_admin, "/forgot-password")
    setup_admin.post("/forgot-password", data={"username": "admin", "csrf_token": token})

    token = get_csrf(setup_admin, "/forgot-password/verify")
    resp = setup_admin.post(
        "/forgot-password/verify",
        data={
            "security_answer": "WrongAnswer", "new_password": "resetpass456",
            "confirm_password": "resetpass456", "csrf_token": token,
        },
    )
    assert b"Incorrect answer" in resp.data

    token = get_csrf(setup_admin, "/login")
    login_resp = setup_admin.post(
        "/login", data={"username": "admin", "password": "testpass123", "csrf_token": token}
    )
    assert login_resp.status_code == 302  # original password still works


def test_forgot_password_answer_is_case_insensitive(setup_admin):
    token = get_csrf(setup_admin, "/forgot-password")
    setup_admin.post("/forgot-password", data={"username": "admin", "csrf_token": token})

    token = get_csrf(setup_admin, "/forgot-password/verify")
    resp = setup_admin.post(
        "/forgot-password/verify",
        data={
            "security_answer": "TEST", "new_password": "resetpass456",
            "confirm_password": "resetpass456", "csrf_token": token,
        },
    )
    assert resp.status_code == 302


def test_forgot_password_reset_is_audited(setup_admin):
    token = get_csrf(setup_admin, "/forgot-password")
    setup_admin.post("/forgot-password", data={"username": "admin", "csrf_token": token})
    token = get_csrf(setup_admin, "/forgot-password/verify")
    setup_admin.post(
        "/forgot-password/verify",
        data={
            "security_answer": "Test", "new_password": "resetpass456",
            "confirm_password": "resetpass456", "csrf_token": token,
        },
    )
    actions = [e["action"] for e in db.list_audit_log()]
    assert "password_changed" in actions


def test_forgot_password_rate_limited_after_8_failed_usernames(setup_admin):
    client = setup_admin
    for _ in range(8):
        token = get_csrf(client, "/forgot-password")
        client.post("/forgot-password", data={"username": "nosuchuser", "csrf_token": token})

    token = get_csrf(client, "/forgot-password")
    resp = client.post("/forgot-password", data={"username": "admin", "csrf_token": token})
    assert b"Too many attempts" in resp.data
