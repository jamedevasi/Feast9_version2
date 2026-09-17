from app import db
from tests.conftest import get_csrf
from tests.test_roles import _create_user, _login, _logout


def _save_login_screen(client, heading="Feast9", tagline="Welcome back."):
    token = get_csrf(client, "/settings/")
    data = {"form": "login_screen", "login_heading": heading, "login_tagline": tagline, "csrf_token": token}
    return client.post("/settings/", data=data)


def test_login_page_shows_defaults_verse_and_copyright(setup_admin):
    resp = setup_admin.get("/login")
    body = resp.data.decode()
    assert "Feast9" in body
    assert "for I am the LORD, who heals you" in body
    assert "Exodus 15:26" in body
    assert "©" in body  # copyright symbol
    assert "Jeremiah" not in body


def test_login_image_route_is_public_and_serves_default(client):
    resp = client.get("/login-image")
    assert resp.status_code == 200
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_admin_can_update_login_heading_and_tagline(logged_in_client):
    resp = _save_login_screen(logged_in_client, heading="Sunrise Dental", tagline="Smile brighter, every visit.")
    assert resp.status_code == 302

    assert db.get_setting("login_heading") == "Sunrise Dental"
    assert db.get_setting("login_tagline") == "Smile brighter, every visit."

    resp2 = logged_in_client.get("/settings/")
    body = resp2.data.decode()
    assert "Sunrise Dental" in body
    assert "Smile brighter, every visit." in body


def test_login_screen_changes_are_audited(logged_in_client):
    _save_login_screen(logged_in_client, heading="Audit Test Clinic")
    actions = [e["action"] for e in db.list_audit_log()]
    assert "setting_changed" in actions


def test_non_admin_cannot_update_login_screen(logged_in_client, patient_id):
    _create_user(logged_in_client, "brandrecep", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "brandrecep")

    resp = _save_login_screen(logged_in_client, heading="Should Not Apply")
    assert resp.status_code == 403
    assert db.get_setting("login_heading") != "Should Not Apply"
