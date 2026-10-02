"""Access logging (record views, sign-ins), per-account lockout, required two-step sign-in,
password rules."""
import pytest

from app import auth, db
from tests.conftest import enable_two_step, get_csrf
from tests.test_cases import _create_case
from tests.test_roles import _create_user, _login, _logout


def _audit(action):
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id", (action,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _try_login(client, username, password):
    token = get_csrf(client, "/login")
    return client.post("/login", data={"username": username, "password": password, "csrf_token": token})


# ── record views ────────────────────────────────────────────────────────────

def test_opening_a_patient_and_a_case_is_logged_with_the_user(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rsplit("/", 1)[-1])
    logged_in_client.get(f"/patients/{patient_id}")
    logged_in_client.get(case_url)

    admin_id = db.get_user_by_username("admin")["id"]
    patient_views, case_views = _audit("patient_viewed"), _audit("case_viewed")
    assert [(v["actor_user_id"], v["entity_id"]) for v in patient_views] == [(admin_id, patient_id)]
    assert [(v["actor_user_id"], v["entity_id"]) for v in case_views] == [(admin_id, case_id)]


def test_reopening_the_same_record_shortly_after_is_one_entry_but_another_user_is_logged(logged_in_client, patient_id):
    for _ in range(3):
        logged_in_client.get(f"/patients/{patient_id}")
    assert len(_audit("patient_viewed")) == 1

    _create_user(logged_in_client, "frontdesk1", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "frontdesk1")
    logged_in_client.get(f"/patients/{patient_id}")
    views = _audit("patient_viewed")
    assert len(views) == 2 and views[1]["role"] == "receptionist"


def test_a_record_that_does_not_exist_is_not_logged_as_viewed(logged_in_client):
    assert logged_in_client.get("/patients/9999").status_code == 404
    assert _audit("patient_viewed") == []


def test_printing_a_patient_summary_is_logged(logged_in_client, patient_id):
    assert logged_in_client.get(f"/patients/{patient_id}/summary.pdf").status_code == 200
    assert len(_audit("patient_summary_pdf_viewed")) == 1


def test_audit_page_filters_views_signins_and_changes(logged_in_client, patient_id):
    logged_in_client.get(f"/patients/{patient_id}")
    views = logged_in_client.get("/audit-log/?show=views").data.decode()
    assert "patient viewed" in views and "login success" not in views
    signins = logged_in_client.get("/audit-log/?show=signins").data.decode()
    assert "login success" in signins and "patient viewed" not in signins
    assert ">admin<" in signins  # the username, not a bare id
    changes = logged_in_client.get("/audit-log/?show=changes").data.decode()
    assert "patient viewed" not in changes and "login success" not in changes


# ── sign-ins ────────────────────────────────────────────────────────────────

def test_sign_in_sign_out_and_failures_are_logged(logged_in_client):
    assert [r["after_summary"] for r in _audit("login_success")] == ["method=password"]
    _logout(logged_in_client)
    assert len(_audit("logout")) == 1

    _try_login(logged_in_client, "admin", "wrong-password-1")
    _try_login(logged_in_client, "typed-my-password-here", "x")
    failures = _audit("login_failed")
    admin_id = db.get_user_by_username("admin")["id"]
    assert [(f["entity_id"], f["after_summary"], f["outcome"]) for f in failures] == [
        (admin_id, "wrong password", "failure"), (None, "unknown username", "failure"),
    ]
    # what was typed into the username box is never stored
    conn = db.get_db()
    everything = " ".join(str(dict(r)) for r in conn.execute("SELECT * FROM audit_log"))
    conn.close()
    assert "typed-my-password-here" not in everything and "wrong-password-1" not in everything


# ── per-account lockout ─────────────────────────────────────────────────────

def _lock_out(client, username="locktarget"):
    for _ in range(auth.ACCOUNT_MAX_FAILED):
        _try_login(client, username, "not-the-password")
        db.clear_failed_logins("127.0.0.1")  # keep the separate per-IP limit out of this test


def test_account_locks_after_repeated_wrong_passwords_even_for_the_right_one(logged_in_client):
    _create_user(logged_in_client, "locktarget", "doctor")
    _logout(logged_in_client)
    _lock_out(logged_in_client)

    assert auth.account_locked(db.get_user_by_username("locktarget"))
    assert len(_audit("account_locked")) == 1
    resp = _try_login(logged_in_client, "locktarget", "testpass123")
    assert resp.status_code == 200 and b"This account is locked" in resp.data
    # other accounts are unaffected
    assert _try_login(logged_in_client, "admin", "testpass123").status_code == 302


def test_lock_lifts_by_itself_and_a_successful_login_resets_the_count(logged_in_client):
    _create_user(logged_in_client, "locktarget", "doctor")
    _logout(logged_in_client)
    _lock_out(logged_in_client)
    conn = db.get_db()
    conn.execute("UPDATE admin SET locked_until = '2020-01-01 00:00:00' WHERE username = 'locktarget'")
    conn.commit()
    conn.close()
    assert _try_login(logged_in_client, "locktarget", "testpass123").status_code == 302
    assert db.get_user_by_username("locktarget")["failed_login_count"] == 0

    _logout(logged_in_client)
    for _ in range(auth.ACCOUNT_MAX_FAILED - 1):
        _try_login(logged_in_client, "locktarget", "nope-nope-nope")
        db.clear_failed_logins("127.0.0.1")
    assert _try_login(logged_in_client, "locktarget", "testpass123").status_code == 302  # one short of the limit


def test_admin_can_unlock_an_account(logged_in_client):
    _create_user(logged_in_client, "locktarget", "doctor")
    target_id = db.get_user_by_username("locktarget")["id"]
    _logout(logged_in_client)
    _lock_out(logged_in_client)
    _login(logged_in_client, "admin")
    page = logged_in_client.get("/users/").data.decode()
    assert "Locked" in page and f"/users/{target_id}/unlock" in page

    token = get_csrf(logged_in_client, "/users/")
    logged_in_client.post(f"/users/{target_id}/unlock", data={"csrf_token": token})
    assert not auth.account_locked(db.get_user_by_id(target_id))
    assert len(_audit("account_unlocked")) == 1
    assert "Locked" not in logged_in_client.get("/users/").data.decode()


def test_wrong_security_answers_also_lock_the_account(logged_in_client):
    _create_user(logged_in_client, "locktarget", "doctor")
    enable_two_step("locktarget")  # without it there is no self-service reset to guess at
    _logout(logged_in_client)
    token = get_csrf(logged_in_client, "/forgot-password")
    logged_in_client.post("/forgot-password", data={"username": "locktarget", "csrf_token": token})
    for _ in range(auth.ACCOUNT_MAX_FAILED):
        token = get_csrf(logged_in_client, "/forgot-password/verify")
        logged_in_client.post("/forgot-password/verify", data={
            "security_answer": "wrong", "new_password": "a-fresh-passphrase", "confirm_password": "a-fresh-passphrase",
            "csrf_token": token,
        })
        db.clear_failed_logins("127.0.0.1")
    assert auth.account_locked(db.get_user_by_username("locktarget"))


# ── password rules ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("password, ok", [
    ("testpass123", True), ("correct horse battery", True), ("short1!", False), ("password123", False),
    ("aaaaaaaaaaaa", False), ("abcabcabcabc", False), ("drsmith-2026!", False),
])
def test_password_rules(password, ok):
    assert (auth.password_errors(password, "drsmith") == []) is ok


def test_new_user_and_password_change_enforce_the_rules(logged_in_client):
    token = get_csrf(logged_in_client, "/users/new")
    resp = logged_in_client.post("/users/new", data={
        "username": "weakling", "password": "password123", "confirm": "password123", "role": "receptionist",
        "security_question": "City?", "security_answer": "Test", "csrf_token": token,
    })
    assert b"too easy to guess" in resp.data and not db.username_exists("weakling")

    token = get_csrf(logged_in_client, "/account/")
    resp = logged_in_client.post("/account/", data={
        "form": "change_password", "current_password": "testpass123", "new_password": "short",
        "confirm_password": "short", "csrf_token": token,
    }, follow_redirects=True)
    assert b"at least 10 characters" in resp.data
    assert auth.check_password(db.get_user_by_username("admin")["password_hash"], "testpass123")


# ── required two-step sign-in ───────────────────────────────────────────────

def _require_two_factor(client, on=True):
    token = get_csrf(client, "/settings/")
    data = {"form": "signin_security", "csrf_token": token}
    if on:
        data["require_two_factor"] = "on"
    return client.post("/settings/", data=data)


def test_required_two_step_sends_admins_and_doctors_to_setup_but_not_receptionists(logged_in_client, patient_id):
    _create_user(logged_in_client, "recep2fa", "receptionist")
    assert logged_in_client.get("/dashboard").status_code == 200
    _require_two_factor(logged_in_client)
    assert db.get_setting("require_two_factor") == "1"

    resp = logged_in_client.get("/dashboard")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/totp/setup")
    assert logged_in_client.get(f"/patients/{patient_id}").status_code == 302
    assert logged_in_client.get("/totp/setup").status_code == 200       # the way out stays open
    assert logged_in_client.get("/session/ping").status_code == 204     # never answered by a redirect

    _logout(logged_in_client)
    _login(logged_in_client, "recep2fa")
    assert logged_in_client.get("/dashboard").status_code == 200


def test_user_with_two_step_enabled_is_not_interrupted_and_cannot_turn_it_off(logged_in_client):
    _require_two_factor(logged_in_client)
    conn = db.get_db()
    conn.execute("UPDATE admin SET totp_enabled = 1, totp_secret = 'JBSWY3DPEHPK3PXP' WHERE username = 'admin'")
    conn.commit()
    conn.close()
    assert logged_in_client.get("/dashboard").status_code == 200

    token = get_csrf(logged_in_client, "/account/")
    resp = logged_in_client.post("/totp/disable", data={"csrf_token": token}, follow_redirects=True)
    assert b"can&#39;t be turned off" in resp.data or b"can't be turned off" in resp.data
    assert db.get_user_by_username("admin")["totp_enabled"] == 1


def test_two_step_requirement_can_be_switched_off_again(logged_in_client):
    _require_two_factor(logged_in_client)
    # the admin has no two-step set up, so the settings page itself is now behind the setup step:
    # turn it off the way a locked-out clinic would have to — which must still be possible.
    assert logged_in_client.get("/settings/").status_code == 302
    db.set_setting("require_two_factor", "0")
    assert logged_in_client.get("/dashboard").status_code == 200


def test_two_step_can_be_required_for_receptionists_too(logged_in_client):
    _create_user(logged_in_client, "recepall", "receptionist")
    enable_two_step("admin")  # so the admin isn't sent to setup while changing the setting
    token = get_csrf(logged_in_client, "/settings/")
    logged_in_client.post("/settings/", data={
        "form": "signin_security", "require_two_factor": "on", "require_two_factor_all": "on", "csrf_token": token,
    })
    assert db.get_setting("require_two_factor") == "all"
    assert auth.two_factor_required_for("receptionist") and auth.two_factor_required_for("doctor")

    # the second box means nothing without the first
    token = get_csrf(logged_in_client, "/settings/")
    logged_in_client.post("/settings/", data={
        "form": "signin_security", "require_two_factor_all": "on", "csrf_token": token,
    })
    assert db.get_setting("require_two_factor") == "0"


# ── deletes leave a trace; more record views are logged ─────────────────────

def test_deleting_a_lab_requisition_a_referral_and_an_appointment_is_audited(logged_in_client, patient_id):
    from tests.test_appointments import _book_appointment
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rsplit("/", 1)[-1])
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(f"/cases/{case_id}/lab-reqs", data={
        "work_description": "Secret bridge work", "sent_date": "2026-01-10", "csrf_token": token,
    })
    logged_in_client.post(f"/cases/{case_id}/referrals", data={
        "referral_date": "2026-02-01", "referred_to": "Dr. Endo Specialist", "reason": "Complex root canal",
        "csrf_token": token,
    })
    _book_appointment(logged_in_client, patient_id)
    req_id = db.list_lab_reqs_for_case(case_id)[0]["id"]
    ref_id = db.list_referrals_for_case(case_id)[0]["id"]
    appt_id = db.list_appointments_for_patient(patient_id)[0]["id"]

    logged_in_client.post(f"/lab-reqs/{req_id}/delete", data={"csrf_token": token})
    logged_in_client.post(f"/referrals/{ref_id}/delete", data={"csrf_token": token})
    logged_in_client.post(f"/appointments/{appt_id}/delete", data={"csrf_token": token})

    admin_id = db.get_user_by_username("admin")["id"]
    for action, entity_id in (("lab_requisition_deleted", req_id), ("referral_deleted", ref_id),
                              ("appointment_deleted", appt_id)):
        rows = _audit(action)
        assert [(r["actor_user_id"], r["entity_id"]) for r in rows] == [(admin_id, entity_id)], action
    logged = " ".join(r["before_summary"] for a in ("lab_requisition_deleted", "referral_deleted") for r in _audit(a))
    assert f"case_id={case_id}" in logged
    assert "Secret" not in logged and "Endo" not in logged and "root canal" not in logged  # no free text
    assert f"patient_id={patient_id}" in _audit("appointment_deleted")[0]["before_summary"]


def test_opening_an_appointment_an_edit_form_and_a_data_request_is_logged(logged_in_client, patient_id):
    from tests.test_appointments import _book_appointment
    _book_appointment(logged_in_client, patient_id)
    appt_id = db.list_appointments_for_patient(patient_id)[0]["id"]
    assert logged_in_client.get(f"/appointments/{appt_id}/edit").status_code == 200
    assert logged_in_client.get(f"/patients/{patient_id}/edit").status_code == 200
    request_id = db.create_data_request(patient_id, "Access", "wants a copy")
    assert logged_in_client.get(f"/data-requests/{request_id}").status_code == 200

    assert [r["entity_id"] for r in _audit("appointment_viewed")] == [appt_id]
    assert [r["entity_id"] for r in _audit("patient_edit_form_viewed")] == [patient_id]
    assert [r["entity_id"] for r in _audit("data_request_viewed")] == [request_id]
