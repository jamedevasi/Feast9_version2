from app import db
from app.constants import DEFAULT_THEME_BACKGROUND_COLOR, DEFAULT_THEME_PRIMARY_COLOR
from tests.conftest import get_csrf
from tests.test_roles import _create_user, _login, _logout


def _save_theme(client, primary="#123456", background="#abcdef"):
    token = get_csrf(client, "/settings/")
    data = {
        "form": "theme",
        "theme_primary_color": primary,
        "theme_background_color": background,
        "csrf_token": token,
    }
    return client.post("/settings/", data=data)


def _reset_theme(client):
    token = get_csrf(client, "/settings/")
    data = {"form": "theme_reset", "csrf_token": token}
    return client.post("/settings/", data=data)


def test_theme_css_route_is_public_and_serves_default(client):
    resp = client.get("/theme.css")
    assert resp.status_code == 200
    assert resp.mimetype == "text/css"
    body = resp.data.decode()
    assert f"--brand: {DEFAULT_THEME_PRIMARY_COLOR};" in body
    assert f"--bg: {DEFAULT_THEME_BACKGROUND_COLOR};" in body
    assert "--accent:" in body
    assert "--border:" in body


def test_login_page_links_theme_stylesheet(setup_admin):
    resp = setup_admin.get("/login")
    assert "/theme.css" in resp.data.decode()


def test_admin_can_update_theme_colors(logged_in_client):
    resp = _save_theme(logged_in_client, primary="#123456", background="#abcdef")
    assert resp.status_code == 302

    assert db.get_setting("theme_primary_color") == "#123456"
    assert db.get_setting("theme_background_color") == "#abcdef"

    css = logged_in_client.get("/theme.css").data.decode()
    assert "--brand: #123456;" in css
    assert "--bg: #abcdef;" in css


def test_theme_changes_are_audited(logged_in_client):
    _save_theme(logged_in_client)
    actions = [e["action"] for e in db.list_audit_log()]
    assert "setting_changed" in actions


def test_invalid_hex_color_is_rejected(logged_in_client):
    resp = _save_theme(logged_in_client, primary="not-a-color", background="#abcdef")
    assert resp.status_code == 302
    assert db.get_setting("theme_primary_color", "") != "not-a-color"


def test_reset_theme_restores_default(logged_in_client):
    _save_theme(logged_in_client, primary="#123456", background="#abcdef")
    _reset_theme(logged_in_client)

    assert db.get_setting("theme_primary_color") == DEFAULT_THEME_PRIMARY_COLOR
    assert db.get_setting("theme_background_color") == DEFAULT_THEME_BACKGROUND_COLOR


def test_non_admin_cannot_update_theme(logged_in_client, patient_id):
    _create_user(logged_in_client, "themerecep", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "themerecep")

    resp = _save_theme(logged_in_client, primary="#111111", background="#222222")
    assert resp.status_code == 403
    assert db.get_setting("theme_primary_color", "") != "#111111"
