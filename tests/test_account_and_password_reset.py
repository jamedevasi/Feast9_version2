import pyotp

from app import db
from tests.conftest import enable_two_step, get_csrf
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
    assert b"at least 10 characters" in follow.data


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
    secret = enable_two_step("admin")
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
    secret = enable_two_step("admin")
    token = get_csrf(setup_admin, "/forgot-password")
    setup_admin.post("/forgot-password", data={"username": "admin", "csrf_token": token})

    token = get_csrf(setup_admin, "/forgot-password/verify")
    resp = setup_admin.post(
        "/forgot-password/verify",
        data={
            "security_answer": "Test", "new_password": "resetpass456",
            "confirm_password": "resetpass456", "code": pyotp.TOTP(secret).now(), "csrf_token": token,
        },
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    token = get_csrf(setup_admin, "/login")
    login_resp = setup_admin.post(
        "/login", data={"username": "admin", "password": "resetpass456", "csrf_token": token}
    )
    assert login_resp.status_code == 302
    assert "/login/totp" in login_resp.headers["Location"]  # the new password works; the code is still asked for


def test_forgot_password_verify_rejects_wrong_answer(setup_admin):
    secret = enable_two_step("admin")
    token = get_csrf(setup_admin, "/forgot-password")
    setup_admin.post("/forgot-password", data={"username": "admin", "csrf_token": token})

    token = get_csrf(setup_admin, "/forgot-password/verify")
    resp = setup_admin.post(
        "/forgot-password/verify",
        data={
            "security_answer": "WrongAnswer", "new_password": "resetpass456",
            "confirm_password": "resetpass456", "code": pyotp.TOTP(secret).now(), "csrf_token": token,
        },
    )
    assert b"Incorrect answer" in resp.data

    token = get_csrf(setup_admin, "/login")
    login_resp = setup_admin.post(
        "/login", data={"username": "admin", "password": "testpass123", "csrf_token": token}
    )
    assert login_resp.status_code == 302  # original password still works


def test_forgot_password_answer_is_case_insensitive(setup_admin):
    secret = enable_two_step("admin")
    token = get_csrf(setup_admin, "/forgot-password")
    setup_admin.post("/forgot-password", data={"username": "admin", "csrf_token": token})

    token = get_csrf(setup_admin, "/forgot-password/verify")
    resp = setup_admin.post(
        "/forgot-password/verify",
        data={
            "security_answer": "TEST", "new_password": "resetpass456",
            "confirm_password": "resetpass456", "code": pyotp.TOTP(secret).now(), "csrf_token": token,
        },
    )
    assert resp.status_code == 302


def test_forgot_password_reset_is_audited(setup_admin):
    secret = enable_two_step("admin")
    token = get_csrf(setup_admin, "/forgot-password")
    setup_admin.post("/forgot-password", data={"username": "admin", "csrf_token": token})
    token = get_csrf(setup_admin, "/forgot-password/verify")
    setup_admin.post(
        "/forgot-password/verify",
        data={
            "security_answer": "Test", "new_password": "resetpass456",
            "confirm_password": "resetpass456", "code": pyotp.TOTP(secret).now(), "csrf_token": token,
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


# ── A security answer alone never resets a password ─────────────────────────

def _start_reset(client, username="admin"):
    token = get_csrf(client, "/forgot-password")
    client.post("/forgot-password", data={"username": username, "csrf_token": token})


def test_account_without_two_step_cannot_reset_its_own_password(setup_admin):
    _start_reset(setup_admin)
    page = setup_admin.get("/forgot-password/verify")
    assert b"administrator" in page.data
    assert b"City?" not in page.data and b'name="security_answer"' not in page.data

    # even a hand-made request with the right answer changes nothing
    token = get_csrf(setup_admin, "/login")
    setup_admin.post("/forgot-password/verify", data={
        "security_answer": "Test", "new_password": "resetpass456", "confirm_password": "resetpass456",
        "csrf_token": token,
    })
    from app.auth import check_password
    assert check_password(db.get_user_by_username("admin")["password_hash"], "testpass123")


def test_reset_needs_the_two_step_code_as_well_as_the_answer(setup_admin):
    from app.auth import check_password
    enable_two_step("admin")
    _start_reset(setup_admin)
    for extra in ({}, {"code": "000000"}):
        token = get_csrf(setup_admin, "/forgot-password/verify")
        resp = setup_admin.post("/forgot-password/verify", data={
            "security_answer": "Test", "new_password": "resetpass456", "confirm_password": "resetpass456",
            "csrf_token": token, **extra,
        })
        assert b"Invalid authentication code" in resp.data
    assert check_password(db.get_user_by_username("admin")["password_hash"], "testpass123")


def test_reset_accepts_a_recovery_code_once(setup_admin):
    from app.auth import hash_recovery_code
    enable_two_step("admin", [hash_recovery_code("ABCD-EFGH")])
    _start_reset(setup_admin)
    token = get_csrf(setup_admin, "/forgot-password/verify")
    resp = setup_admin.post("/forgot-password/verify", data={
        "security_answer": "Test", "new_password": "resetpass456", "confirm_password": "resetpass456",
        "recovery_code": "abcd-efgh", "csrf_token": token,
    })
    assert resp.status_code == 302
    assert db.get_user_by_username("admin")["totp_recovery_codes_json"] == "[]"


def test_a_password_typo_does_not_use_up_a_recovery_code(setup_admin):
    from app.auth import hash_recovery_code
    enable_two_step("admin", [hash_recovery_code("ABCD-EFGH")])
    _start_reset(setup_admin)
    token = get_csrf(setup_admin, "/forgot-password/verify")
    resp = setup_admin.post("/forgot-password/verify", data={
        "security_answer": "Test", "new_password": "resetpass456", "confirm_password": "different789",
        "recovery_code": "ABCD-EFGH", "csrf_token": token,
    })
    assert b"do not match" in resp.data
    assert db.get_user_by_username("admin")["totp_recovery_codes_json"] != "[]"


# ── Admin sets a new password for someone (Users > Set Password) ─────────────

def test_admin_sets_a_new_password_for_a_user(app, logged_in_client):
    _create_user(logged_in_client, "forgetful", "receptionist")
    user_id = db.get_user_by_username("forgetful")["id"]
    other = app.test_client()
    _login(other, "forgetful")
    assert other.get("/dashboard").status_code == 200
    db.register_failed_sign_in(user_id, 1, 15, actor=None, reason="wrong password")  # locked out

    assert b"Set Password" in logged_in_client.get("/users/").data
    token = get_csrf(logged_in_client, f"/users/{user_id}/password")
    resp = logged_in_client.post(f"/users/{user_id}/password", data={
        "password": "brand-new-pass-1", "confirm": "brand-new-pass-1", "csrf_token": token,
    })
    assert resp.status_code == 302

    user = db.get_user_by_username("forgetful")
    assert user["failed_login_count"] == 0 and not user["locked_until"]
    assert other.get("/dashboard").status_code == 302  # signed out everywhere
    token = get_csrf(other, "/login")
    resp = other.post("/login", data={"username": "forgetful", "password": "brand-new-pass-1", "csrf_token": token})
    assert "dashboard" in resp.headers["Location"]

    row = [e for e in db.list_audit_log() if e["action"] == "password_changed"][0]
    assert row["entity_id"] == user_id and row["after_summary"] == "set by an administrator"
    assert row["actor_user_id"] == db.get_user_by_username("admin")["id"]


def test_set_password_applies_the_password_rules_and_is_admin_only(logged_in_client):
    from app.auth import check_password
    _create_user(logged_in_client, "target1", "doctor")
    user_id = db.get_user_by_username("target1")["id"]
    before = db.get_user_by_username("target1")["password_hash"]
    token = get_csrf(logged_in_client, f"/users/{user_id}/password")
    resp = logged_in_client.post(f"/users/{user_id}/password", data={
        "password": "password123", "confirm": "password123", "csrf_token": token,
    })
    assert b"too easy to guess" in resp.data
    assert db.get_user_by_username("target1")["password_hash"] == before

    # an admin's own password is changed under My Account, which asks for the current one
    admin_id = db.get_user_by_username("admin")["id"]
    assert logged_in_client.get(f"/users/{admin_id}/password").headers["Location"].endswith("/account/")

    _logout(logged_in_client)
    _login(logged_in_client, "target1")
    assert logged_in_client.get(f"/users/{admin_id}/password").status_code == 403
    assert check_password(db.get_user_by_username("admin")["password_hash"], "testpass123")


def test_emergency_reset_script_uses_the_rules_audits_and_signs_out(app, logged_in_client, monkeypatch, capsys):
    import pytest
    import reset_admin_password
    from app.auth import check_password

    monkeypatch.setattr(reset_admin_password.getpass, "getpass", lambda prompt="": "short1")
    with pytest.raises(SystemExit):
        reset_admin_password.main()
    assert "at least 10 characters" in capsys.readouterr().out

    monkeypatch.setattr(reset_admin_password.getpass, "getpass", lambda prompt="": "a-long-new-passphrase")
    reset_admin_password.main()
    assert check_password(db.get_user_by_username("admin")["password_hash"], "a-long-new-passphrase")
    assert logged_in_client.get("/dashboard").status_code == 302  # the old session is over
    row = [e for e in db.list_audit_log() if e["action"] == "password_changed"][0]
    assert row["after_summary"] == "reset on the Feast9 computer" and row["actor_user_id"] is None
