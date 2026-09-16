import io
import os
import sys
import tarfile

import pytest
from cryptography.fernet import Fernet

from app import backup as backup_module
from app import config as app_config
from app import db
from tests.conftest import get_csrf


@pytest.fixture()
def backup_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(app_config, "BACKUP_ENCRYPTION_KEY", key)
    return key


def test_create_backup_without_key_raises_and_logs_nothing(app):
    with pytest.raises(backup_module.BackupError):
        backup_module.create_backup()
    assert db.list_backup_log() == []


def test_create_backup_produces_encrypted_file_and_log_row(backup_key, patient_id):
    row = backup_module.create_backup()
    assert row["status"] == "success"
    assert os.path.exists(row["file_path"])
    assert row["file_size"] > 0

    fernet = Fernet(backup_key.encode())
    with open(row["file_path"], "rb") as f:
        plaintext = fernet.decrypt(f.read())  # raises InvalidToken if not encrypted with this key
    with tarfile.open(fileobj=io.BytesIO(plaintext)) as tar:
        assert "feast9.db" in tar.getnames()


def test_offsite_command_success_recorded(backup_key, monkeypatch, patient_id):
    monkeypatch.setattr(app_config, "BACKUP_OFFSITE_COMMAND", f'"{sys.executable}" -c "pass"')
    row = backup_module.create_backup()
    assert row["offsite_status"] == "success"


def test_offsite_command_failure_recorded(backup_key, monkeypatch, patient_id):
    monkeypatch.setattr(app_config, "BACKUP_OFFSITE_COMMAND", f'"{sys.executable}" -c "exit(1)"')
    row = backup_module.create_backup()
    assert row["status"] == "success"  # the local backup itself still succeeded
    assert row["offsite_status"].startswith("failed")


def test_offsite_not_configured_by_default(backup_key, patient_id):
    row = backup_module.create_backup()
    assert row["offsite_status"] == "not_configured"


def test_restore_recovers_patient_data(backup_key, patient_id):
    row = backup_module.create_backup()

    os.remove(app_config.DB_PATH)
    backup_module.restore_backup(row["file_path"], force=True)

    restored = db.get_patient(patient_id)
    assert restored is not None
    assert restored["name"] == "Case Test Patient"


def test_restore_refuses_without_force_when_db_exists(backup_key, patient_id):
    row = backup_module.create_backup()
    with pytest.raises(backup_module.BackupError):
        backup_module.restore_backup(row["file_path"], force=False)


def test_restore_with_wrong_key_fails_cleanly(backup_key, monkeypatch, patient_id):
    row = backup_module.create_backup()
    monkeypatch.setattr(app_config, "BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(backup_module.BackupError):
        backup_module.restore_backup(row["file_path"], force=True)


def test_backup_created_writes_audit_entry(backup_key, patient_id):
    backup_module.create_backup()
    entries = [e for e in db.list_audit_log() if e["action"] == "backup_created"]
    assert len(entries) == 1
    assert entries[0]["outcome"] == "success"


def test_backup_list_page_admin_only(logged_in_client):
    resp = logged_in_client.get("/backup/")
    assert resp.status_code == 200


def test_non_admin_cannot_access_backup_routes(logged_in_client):
    token = get_csrf(logged_in_client, "/users/new")
    logged_in_client.post(
        "/users/new",
        data={
            "username": "recep_backup", "password": "testpass123", "confirm": "testpass123",
            "role": "receptionist", "security_question": "Q", "security_answer": "A",
            "csrf_token": token,
        },
    )
    token = get_csrf(logged_in_client, "/dashboard")
    logged_in_client.post("/logout", data={"csrf_token": token})
    token = get_csrf(logged_in_client, "/login")
    logged_in_client.post(
        "/login", data={"username": "recep_backup", "password": "testpass123", "csrf_token": token}
    )

    assert logged_in_client.get("/backup/").status_code == 403


def test_run_backup_route_requires_reauth_then_succeeds(logged_in_client, backup_key):
    with logged_in_client.session_transaction() as sess:
        sess["reauth_at"] = "2020-01-01T00:00:00"

    token = get_csrf(logged_in_client, "/dashboard")
    resp = logged_in_client.post("/backup/run", data={"csrf_token": token})
    assert resp.status_code == 302
    assert "/reauth" in resp.headers["Location"]
    assert db.list_backup_log() == []

    reauth_token = get_csrf(logged_in_client, "/reauth")
    logged_in_client.post("/reauth", data={"password": "testpass123", "csrf_token": reauth_token})

    token = get_csrf(logged_in_client, "/backup/")
    resp = logged_in_client.post("/backup/run", data={"csrf_token": token})
    assert resp.status_code == 302
    assert len(db.list_backup_log()) == 1


def test_download_requires_admin_and_is_audited(logged_in_client, backup_key):
    token = get_csrf(logged_in_client, "/backup/")
    logged_in_client.post("/backup/run", data={"csrf_token": token})
    backup_id = db.list_backup_log()[0]["id"]

    resp = logged_in_client.get(f"/backup/{backup_id}/download")
    assert resp.status_code == 200
    entries = [e for e in db.list_audit_log() if e["action"] == "backup_downloaded"]
    assert len(entries) == 1


def test_dashboard_warns_when_no_backup_yet(logged_in_client):
    resp = logged_in_client.get("/dashboard")
    assert b"No backup has ever been run" in resp.data


def test_dashboard_clear_after_successful_backup(logged_in_client, backup_key):
    token = get_csrf(logged_in_client, "/backup/")
    logged_in_client.post("/backup/run", data={"csrf_token": token})
    resp = logged_in_client.get("/dashboard")
    assert b"No backup has ever been run" not in resp.data
