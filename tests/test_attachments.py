import io
import os

from app import config as app_config
from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 32
INVALID_BYTES = b"this is not a real image, just text pretending to be one" * 2


def _case_for(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url


def _upload(client, case_id, content, filename, file_type="X-ray", description=""):
    token = get_csrf(client, f"/cases/{case_id}")
    return client.post(
        f"/cases/{case_id}/attachments",
        data={
            "file": (io.BytesIO(content), filename),
            "file_type": file_type,
            "description": description,
            "csrf_token": token,
        },
        content_type="multipart/form-data",
    )


def test_valid_jpeg_upload_succeeds(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    resp = _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")
    assert resp.status_code == 302

    detail_resp = logged_in_client.get(case_url)
    assert b"xray.jpg" in detail_resp.data
    assert b"X-ray" in detail_resp.data


def test_valid_png_and_pdf_upload_succeed(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id)
    assert _upload(logged_in_client, case_id, PNG_BYTES, "photo.png", "Clinical Photo").status_code == 302
    assert _upload(logged_in_client, case_id, PDF_BYTES, "report.pdf", "Lab Report").status_code == 302


def test_spoofed_extension_with_invalid_content_rejected(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    resp = _upload(logged_in_client, case_id, INVALID_BYTES, "fake.jpg")
    assert resp.status_code == 302  # redirects back with a flash warning, not saved

    detail_resp = logged_in_client.get(case_url)
    assert b"Unsupported or corrupted file" in detail_resp.data
    assert db.list_attachments_for_case(case_id) == []


def test_file_stored_outside_static_with_uuid_name(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")

    attachments = db.list_attachments_for_case(case_id)
    assert len(attachments) == 1
    stored_filename = attachments[0]["filename"]
    assert stored_filename != "xray.jpg"  # UUID-based, not the original name
    assert os.path.exists(os.path.join(app_config.DATA_DIR, "clinical_uploads", stored_filename))


def test_serve_attachment_requires_login(app, logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")
    attachment_id = db.list_attachments_for_case(case_id)[0]["id"]

    # A genuinely separate, unauthenticated client — `client` and `logged_in_client` share the
    # same underlying fixture instance (logged_in_client is built by logging in on `client`),
    # so a fresh app.test_client() is needed here rather than the `client` fixture.
    unauth_client = app.test_client()
    resp = unauth_client.get(f"/attachments/{attachment_id}/file")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_serve_attachment_returns_correct_bytes(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")
    attachment_id = db.list_attachments_for_case(case_id)[0]["id"]

    resp = logged_in_client.get(f"/attachments/{attachment_id}/file")
    assert resp.status_code == 200
    assert resp.data == JPEG_BYTES
    assert resp.headers["Content-Type"] == "image/jpeg"


def test_delete_attachment_removes_file_and_row(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")
    attachment = db.list_attachments_for_case(case_id)[0]
    file_path = os.path.join(app_config.DATA_DIR, "clinical_uploads", attachment["filename"])
    assert os.path.exists(file_path)

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/attachments/{attachment['id']}/delete", data={"csrf_token": token}
    )
    assert resp.status_code == 302
    assert db.list_attachments_for_case(case_id) == []
    assert not os.path.exists(file_path)


def test_delete_attachment_writes_audit_entry(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")
    attachment = db.list_attachments_for_case(case_id)[0]

    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/attachments/{attachment['id']}/delete",
        data={"csrf_token": token, "reason": "Duplicate upload"},
    )
    entries = [e for e in db.list_audit_log() if e["action"] == "attachment_deleted"]
    assert len(entries) == 1
    assert "X-ray" in entries[0]["before_summary"]
    assert "Duplicate upload" in entries[0]["before_summary"]


def _make_receptionist(admin_client):
    token = get_csrf(admin_client, "/users/new")
    admin_client.post(
        "/users/new",
        data={
            "username": "recep_attach", "password": "testpass123", "confirm": "testpass123",
            "role": "receptionist", "security_question": "Q", "security_answer": "A",
            "csrf_token": token,
        },
    )
    token = get_csrf(admin_client, "/dashboard")
    admin_client.post("/logout", data={"csrf_token": token})
    token = get_csrf(admin_client, "/login")
    admin_client.post(
        "/login", data={"username": "recep_attach", "password": "testpass123", "csrf_token": token}
    )


def test_receptionist_cannot_delete_attachment(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")
    attachment = db.list_attachments_for_case(case_id)[0]

    token = get_csrf(logged_in_client, case_url)
    _make_receptionist(logged_in_client)

    resp = logged_in_client.post(f"/attachments/{attachment['id']}/delete", data={"csrf_token": token})
    assert resp.status_code == 403
    assert db.list_attachments_for_case(case_id) != []


def test_case_detail_hides_delete_controls_from_receptionist(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")

    _make_receptionist(logged_in_client)
    resp = logged_in_client.get(case_url)
    assert b"Clear All Clinical Documents" not in resp.data


def test_clear_attachments_requires_reason(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(f"/cases/{case_id}/attachments/clear", data={"csrf_token": token})
    assert resp.status_code == 302
    assert len(db.list_attachments_for_case(case_id)) == 1  # nothing deleted, no reason given


def test_clear_attachments_deletes_all_files_and_logs_one_audit_entry(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg", "X-ray")
    _upload(logged_in_client, case_id, PDF_BYTES, "report.pdf", "Lab Report")
    file_paths = [
        os.path.join(app_config.DATA_DIR, "clinical_uploads", a["filename"])
        for a in db.list_attachments_for_case(case_id)
    ]
    assert all(os.path.exists(p) for p in file_paths)

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/attachments/clear",
        data={"csrf_token": token, "reason": "Not required to be retained for this case"},
    )
    assert resp.status_code == 302
    assert db.list_attachments_for_case(case_id) == []
    assert not any(os.path.exists(p) for p in file_paths)

    entries = [e for e in db.list_audit_log() if e["action"] == "clinical_documents_cleared"]
    assert len(entries) == 1
    assert "X-ray:1" in entries[0]["before_summary"]
    assert "Lab Report:1" in entries[0]["before_summary"]
    assert "Not required to be retained" in entries[0]["after_summary"]


def test_receptionist_cannot_clear_attachments(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")

    token = get_csrf(logged_in_client, case_url)
    _make_receptionist(logged_in_client)

    resp = logged_in_client.post(
        f"/cases/{case_id}/attachments/clear",
        data={"csrf_token": token, "reason": "trying anyway"},
    )
    assert resp.status_code == 403
    assert len(db.list_attachments_for_case(case_id)) == 1


def test_clear_attachments_requires_fresh_reauth(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    _upload(logged_in_client, case_id, JPEG_BYTES, "xray.jpg")

    with logged_in_client.session_transaction() as sess:
        sess["reauth_at"] = "2020-01-01T00:00:00"

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/attachments/clear",
        data={"csrf_token": token, "reason": "stale session attempt"},
    )
    assert resp.status_code == 302
    assert "/reauth" in resp.headers["Location"]
    assert len(db.list_attachments_for_case(case_id)) == 1
