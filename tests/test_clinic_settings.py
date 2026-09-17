import io

from app import db
from tests.conftest import get_csrf
from tests.test_roles import _create_user, _login, _logout

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
GIF_BYTES = b"GIF89a" + b"\x00" * 32
NOT_AN_IMAGE = b"not an image at all, just text"


def _save_clinic_details(client, name="Sunrise Dental Clinic", address="1 MG Road", phone="080-1234", email="hi@sunrise.example"):
    token = get_csrf(client, "/settings/")
    data = {
        "form": "clinic_details", "clinic_name": name, "clinic_address": address,
        "clinic_phone": phone, "clinic_email": email, "csrf_token": token,
    }
    return client.post("/settings/", data=data)


def _upload_clinic_logo(client, image, image_name="logo.png"):
    token = get_csrf(client, "/settings/")
    data = {"form": "clinic_logo", "clinic_logo": (io.BytesIO(image), image_name), "csrf_token": token}
    return client.post("/settings/", data=data, content_type="multipart/form-data")


def test_admin_can_save_clinic_details(logged_in_client):
    resp = _save_clinic_details(logged_in_client)
    assert resp.status_code == 302
    assert db.get_setting("clinic_name") == "Sunrise Dental Clinic"
    assert db.get_setting("clinic_address") == "1 MG Road"
    assert db.get_setting("clinic_phone") == "080-1234"
    assert db.get_setting("clinic_email") == "hi@sunrise.example"

    settings_page = logged_in_client.get("/settings/")
    body = settings_page.data.decode()
    assert "Sunrise Dental Clinic" in body
    assert "1 MG Road" in body


def test_clinic_name_appears_in_nav_bar(logged_in_client):
    _save_clinic_details(logged_in_client, name="Sunrise Dental Clinic")
    resp = logged_in_client.get("/dashboard")
    assert b"Sunrise Dental Clinic" in resp.data


def test_clinic_name_falls_back_to_default_when_unset(logged_in_client):
    resp = logged_in_client.get("/dashboard")
    assert b"Feast9" in resp.data


def test_clinic_name_used_as_login_heading_when_no_custom_heading(logged_in_client):
    _save_clinic_details(logged_in_client, name="Sunrise Dental Clinic")
    _logout(logged_in_client)
    resp = logged_in_client.get("/login")
    assert b"Sunrise Dental Clinic" in resp.data


def test_custom_login_heading_overrides_clinic_name(logged_in_client):
    _save_clinic_details(logged_in_client, name="Sunrise Dental Clinic")
    token = get_csrf(logged_in_client, "/settings/")
    logged_in_client.post(
        "/settings/",
        data={"form": "login_screen", "login_heading": "Custom Heading", "login_tagline": "", "csrf_token": token},
    )
    _logout(logged_in_client)
    resp = logged_in_client.get("/login")
    body = resp.data.decode()
    assert "Custom Heading" in body
    assert "Sunrise Dental Clinic" not in body


def test_admin_can_upload_clinic_logo(logged_in_client):
    resp = _upload_clinic_logo(logged_in_client, PNG_BYTES, "clinic-logo.png")
    assert resp.status_code == 302

    filename = db.get_setting("login_image_filename")
    assert filename.endswith(".png")

    img_resp = logged_in_client.get("/login-image")
    assert img_resp.status_code == 200
    assert img_resp.data == PNG_BYTES


def test_gif_logo_accepted(logged_in_client):
    _upload_clinic_logo(logged_in_client, GIF_BYTES, "logo.gif")
    assert db.get_setting("login_image_filename").endswith(".gif")
    resp = logged_in_client.get("/login-image")
    assert resp.headers["Content-Type"] == "image/gif"


def test_corrupt_logo_rejected(logged_in_client):
    resp = _upload_clinic_logo(logged_in_client, NOT_AN_IMAGE, "fake.png")
    assert resp.status_code == 302
    assert db.get_setting("login_image_filename") == ""

    settings_page = logged_in_client.get("/settings/")
    assert b"Unsupported or corrupted image" in settings_page.data


def test_clinic_logo_appears_in_nav_bar(logged_in_client):
    _upload_clinic_logo(logged_in_client, PNG_BYTES)
    resp = logged_in_client.get("/dashboard")
    assert b'class="brand-logo"' in resp.data


def test_clinic_details_and_logo_changes_are_audited(logged_in_client):
    _save_clinic_details(logged_in_client)
    _upload_clinic_logo(logged_in_client, PNG_BYTES)
    actions = [e["action"] for e in db.list_audit_log()]
    assert "setting_changed" in actions


def test_non_admin_cannot_save_clinic_details_or_logo(logged_in_client, patient_id):
    _create_user(logged_in_client, "cliniclogorecep", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "cliniclogorecep")

    resp = _save_clinic_details(logged_in_client, name="Should Not Apply")
    assert resp.status_code == 403
    assert db.get_setting("clinic_name") != "Should Not Apply"

    resp2 = _upload_clinic_logo(logged_in_client, PNG_BYTES)
    assert resp2.status_code == 403
