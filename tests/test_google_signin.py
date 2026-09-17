"""Google sign-in (§14). Authlib's own OAuth2/OIDC internals (state, nonce, signature,
issuer/audience validation) aren't re-tested here — that's Authlib's job, and it's why
this app uses Authlib rather than hand-rolled JWT handling. These tests cover this
app's own integration: linking never creates a new account, a Google identity can only
sign in once explicitly linked from an authenticated session, unlink/relink behavior,
role gating, and the "feature simply doesn't exist" behavior when unconfigured.
"""
from unittest.mock import patch

import pytest

from app import config as app_config
from app import create_app, db
from tests.conftest import get_csrf
from tests.test_roles import _create_user, _login, _logout


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """Overrides conftest.py's app fixture for this module only — same DATA_DIR setup,
    plus Google sign-in enabled so these routes aren't 404 by default."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(app_config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(app_config, "DB_PATH", str(data_dir / "feast9.db"))
    monkeypatch.setattr(app_config, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(app_config, "GOOGLE_CLIENT_SECRET", "test-client-secret")

    application = create_app()
    application.testing = True
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def setup_admin(client):
    token = get_csrf(client, "/setup")
    client.post(
        "/setup",
        data={
            "username": "admin", "password": "testpass123", "confirm": "testpass123",
            "security_question": "City?", "security_answer": "Test", "csrf_token": token,
        },
    )
    return client


@pytest.fixture()
def logged_in_client(setup_admin):
    token = get_csrf(setup_admin, "/login")
    setup_admin.post("/login", data={"username": "admin", "password": "testpass123", "csrf_token": token})
    return setup_admin


def _fake_redirect(_redirect_uri=None, **_kwargs):
    from flask import redirect
    return redirect("https://accounts.google.com/fake-auth-url")


def _fake_token(sub="google-sub-123", email="user@example.com", email_verified=True):
    return {"userinfo": {"sub": sub, "email": email, "email_verified": email_verified}}


# ── Disabled by default ──────────────────────────────────────────────────────

def test_routes_404_when_not_configured():
    application = create_app()
    application.testing = True
    with application.test_client() as c:
        assert c.get("/login/google").status_code == 404
        assert c.get("/login/google/callback").status_code == 404


def test_login_page_hides_google_button_when_not_configured():
    application = create_app()
    application.testing = True
    with application.test_client() as c:
        resp = c.get("/login")
        assert b"Sign in with Google" not in resp.data


# ── Enabled ───────────────────────────────────────────────────────────────────

def test_login_page_shows_google_button_when_configured(setup_admin):
    resp = setup_admin.get("/login")
    assert b"Sign in with Google" in resp.data


def test_link_requires_login(client):
    resp = client.get("/account/link-google")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_link_google_account(logged_in_client):
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        start = logged_in_client.get("/account/link-google")
        assert start.status_code == 302

    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        callback = logged_in_client.get("/login/google/callback")
    assert callback.status_code == 302
    assert callback.headers["Location"].endswith("/account/")

    admin = db.get_user_by_username("admin")
    assert admin["google_sub"] == "google-sub-123"
    assert admin["google_email"] == "user@example.com"
    assert admin["google_linked_at"]

    account_page = logged_in_client.get("/account/")
    assert b"user@example.com" in account_page.data


def test_link_is_audited(logged_in_client):
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        logged_in_client.get("/login/google/callback")

    actions = [e["action"] for e in db.list_audit_log()]
    assert "google_account_linked" in actions


def test_unverified_email_rejected(logged_in_client):
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch(
        "app.google_oauth.oauth.google.authorize_access_token",
        return_value=_fake_token(email_verified=False),
    ):
        callback = logged_in_client.get("/login/google/callback")
    assert callback.status_code == 302
    assert callback.headers["Location"].endswith("/login")

    admin = db.get_user_by_username("admin")
    assert admin["google_sub"] == ""


def test_link_conflict_when_sub_already_linked_to_another_user(logged_in_client):
    _create_user(logged_in_client, "doctor1", "doctor")

    # Link the Google sub to 'admin' first.
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        logged_in_client.get("/login/google/callback")

    _logout(logged_in_client)
    _login(logged_in_client, "doctor1")

    # doctor1 tries to link the SAME Google sub.
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        callback = logged_in_client.get("/login/google/callback")
    assert callback.status_code == 302

    doctor = db.get_user_by_username("doctor1")
    assert doctor["google_sub"] == ""

    account_page = logged_in_client.get("/account/")
    assert b"already linked to a different Feast9 user" in account_page.data


def test_signin_with_linked_google_account(logged_in_client):
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        logged_in_client.get("/login/google/callback")
    _logout(logged_in_client)

    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/login/google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        resp = logged_in_client.get("/login/google/callback")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")
    dash = logged_in_client.get("/dashboard")
    assert dash.status_code == 200


def test_signin_is_audited(logged_in_client):
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        logged_in_client.get("/login/google/callback")
    _logout(logged_in_client)

    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/login/google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        logged_in_client.get("/login/google/callback")

    actions = [e["action"] for e in db.list_audit_log()]
    assert "google_sign_in" in actions


def test_signin_with_unlinked_google_account_rejected_and_creates_no_account(setup_admin):
    before_count = len(db.list_users())
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        setup_admin.get("/login/google")
    with patch(
        "app.google_oauth.oauth.google.authorize_access_token",
        return_value=_fake_token(sub="never-linked-sub"),
    ):
        resp = setup_admin.get("/login/google/callback")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert len(db.list_users()) == before_count

    follow = setup_admin.get("/login")
    assert b"linked to a Feast9 user yet" in follow.data


def test_self_service_unlink(logged_in_client):
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        logged_in_client.get("/login/google/callback")

    token = get_csrf(logged_in_client, "/account/")
    resp = logged_in_client.post("/account/unlink-google", data={"csrf_token": token})
    assert resp.status_code == 302

    admin = db.get_user_by_username("admin")
    assert admin["google_sub"] == ""
    assert admin["google_email"] == ""

    actions = [e["action"] for e in db.list_audit_log()]
    assert "google_account_unlinked" in actions


def test_admin_can_unlink_another_users_google_account(logged_in_client):
    _create_user(logged_in_client, "doctor2", "doctor")
    _logout(logged_in_client)
    _login(logged_in_client, "doctor2")
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        logged_in_client.get("/login/google/callback")
    _logout(logged_in_client)
    _login(logged_in_client, "admin")

    doctor = db.get_user_by_username("doctor2")
    assert doctor["google_sub"] != ""

    token = get_csrf(logged_in_client, "/users/")
    resp = logged_in_client.post(f"/users/{doctor['id']}/unlink-google", data={"csrf_token": token})
    assert resp.status_code == 302

    doctor_after = db.get_user_by_username("doctor2")
    assert doctor_after["google_sub"] == ""


def test_non_admin_cannot_unlink_another_users_google_account(logged_in_client):
    _create_user(logged_in_client, "recepgoogle", "receptionist")
    _create_user(logged_in_client, "doctor3", "doctor")

    _logout(logged_in_client)
    _login(logged_in_client, "doctor3")
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        logged_in_client.get("/login/google/callback")
    _logout(logged_in_client)

    _login(logged_in_client, "recepgoogle")
    doctor = db.get_user_by_username("doctor3")
    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post(f"/users/{doctor['id']}/unlink-google", data={"csrf_token": token})
    assert resp.status_code == 403


def test_users_list_shows_google_link_status(logged_in_client):
    with patch("app.google_oauth.oauth.google.authorize_redirect", side_effect=_fake_redirect):
        logged_in_client.get("/account/link-google")
    with patch("app.google_oauth.oauth.google.authorize_access_token", return_value=_fake_token()):
        logged_in_client.get("/login/google/callback")

    resp = logged_in_client.get("/users/")
    assert b"user@example.com" in resp.data
