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
def backup_key(app, monkeypatch):
    # Depends on `app` so it runs after conftest clears any backup key.
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


# ── Configurable backups: set up from the page, settings, copy folder, pruning, schedule ──

def _post(client, path, **data):
    token = get_csrf(client, "/backup/")
    return client.post(path, data={"csrf_token": token, **data})


def _settings(client, **overrides):
    data = {"auto_enabled": "1", "backup_time": "21:00", "copy_folder": "", "keep_count": "30"}
    data.update(overrides)
    return _post(client, "/backup/settings", **data)


def _read_key_file():
    with open(app_config.BACKUP_KEY_FILE, encoding="utf-8") as f:
        return f.read().strip()


def test_page_offers_setup_when_not_configured(logged_in_client):
    body = logged_in_client.get("/backup/").data.decode()
    assert "Set Up Backups" in body and "Not set up" in body
    assert "Back Up Now" not in body


def test_setup_creates_key_file_first_backup_and_shows_key_once(logged_in_client, patient_id):
    body = _post(logged_in_client, "/backup/setup").data.decode()
    key = _read_key_file()
    assert key in body and "The first backup has been made" in body
    assert os.path.commonpath([app_config.BACKUP_KEY_FILE, app_config.DATA_DIR]) != app_config.DATA_DIR
    [entry] = db.list_backup_log()
    assert entry["status"] == "success"
    with open(entry["file_path"], "rb") as f:
        Fernet(key.encode()).decrypt(f.read())  # the key shown opens the backup
    assert "Back Up Now" in logged_in_client.get("/backup/").data.decode()

    # Setting up again must never replace the key — that would orphan every existing backup.
    _post(logged_in_client, "/backup/setup")
    assert _read_key_file() == key
    assert [e["action"] for e in db.list_audit_log()].count("backup_key_created") == 1


def test_setup_requires_admin(logged_in_client):
    from tests.test_roles import _create_user, _login, _logout
    _create_user(logged_in_client, "setupdoc", "doctor")
    _logout(logged_in_client)
    _login(logged_in_client, "setupdoc")
    token = get_csrf(logged_in_client, "/dashboard")
    assert logged_in_client.post("/backup/setup", data={"csrf_token": token}).status_code == 403
    assert logged_in_client.get("/backup/key").status_code == 403
    assert not os.path.exists(app_config.BACKUP_KEY_FILE)


def test_show_key_needs_reauth_and_is_audited(logged_in_client):
    key = backup_module.create_key()
    assert key in logged_in_client.get("/backup/key").data.decode()
    assert "backup_key_viewed" in [e["action"] for e in db.list_audit_log()]
    with logged_in_client.session_transaction() as sess:
        sess["reauth_at"] = "2020-01-01T00:00:00"
    assert "/reauth" in logged_in_client.get("/backup/key").headers["Location"]


def test_settings_saved_and_validated(logged_in_client, tmp_path):
    backup_module.create_key()
    folder = tmp_path / "usb"
    _settings(logged_in_client, auto_enabled="", backup_time="13:30", copy_folder=str(folder), keep_count="5")
    assert backup_module.get_settings() == {
        "auto_enabled": False, "time": "13:30", "copy_folder": str(folder), "keep_count": 5,
    }
    assert folder.is_dir()
    assert "backup_settings_updated" in [e["action"] for e in db.list_audit_log()]

    body = _settings(logged_in_client, backup_time="25:99", keep_count="0",
                     copy_folder=os.path.join(app_config.DATA_DIR, "inside")).data.decode()
    assert "Choose a time" in body and "from 1 to 365" in body and "inside Feast9" in body
    body = _settings(logged_in_client, copy_folder=os.path.join("relative", "folder")).data.decode()
    assert "must be a full path" in body
    assert backup_module.get_settings()["time"] == "13:30"  # nothing saved on error


def test_copy_folder_gets_each_backup_and_old_ones_are_pruned(backup_key, tmp_path, monkeypatch):
    from datetime import datetime as real_datetime
    folder = tmp_path / "usb"
    backup_module.save_settings({"auto_enabled": True, "time": "21:00", "copy_folder": str(folder), "keep_count": 2})
    stamps = iter(["20260101-010101", "20260102-010101", "20260103-010101"])

    class FakeDatetime:
        @staticmethod
        def now():
            return real_datetime.strptime(next(stamps), "%Y%m%d-%H%M%S")
    monkeypatch.setattr(backup_module, "datetime", FakeDatetime)

    rows = [backup_module.create_backup() for _ in range(3)]
    assert all(r["offsite_status"] == "success" for r in rows)
    assert [e["status"] for e in db.list_backup_log()] == ["success", "success", "removed"]  # newest first
    assert not os.path.exists(rows[0]["file_path"]) and os.path.exists(rows[2]["file_path"])
    assert sorted(os.listdir(folder)) == [
        "feast9-backup-20260102-010101.tar.enc", "feast9-backup-20260103-010101.tar.enc",
    ]


def test_copy_folder_failure_keeps_the_backup(backup_key, tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")
    backup_module.save_settings({"auto_enabled": True, "time": "21:00", "copy_folder": str(blocker), "keep_count": 30})
    row = backup_module.create_backup()
    assert row["status"] == "success" and row["offsite_status"].startswith("failed")


def test_scheduled_backup_runs_once_per_day_and_catches_up(backup_key):
    from datetime import datetime
    backup_module.save_settings({"auto_enabled": True, "time": "21:00", "copy_folder": "", "keep_count": 30})
    assert backup_module.last_scheduled_time(datetime(2026, 9, 30, 20, 59), "21:00") == datetime(2026, 9, 29, 21, 0)
    assert backup_module.last_scheduled_time(datetime(2026, 9, 30, 21, 0), "21:00") == datetime(2026, 9, 30, 21, 0)

    # Nothing since the last scheduled time -> due now (catches up after the computer was off).
    assert backup_module.run_scheduled_backup_if_due()["status"] == "success"
    # Already made since then -> not due again until the next scheduled time.
    assert backup_module.run_scheduled_backup_if_due() is None
    assert len(db.list_backup_log()) == 1


def test_scheduled_backup_respects_off_switch_and_missing_key(app, monkeypatch):
    assert backup_module.run_scheduled_backup_if_due() is None  # not set up
    monkeypatch.setattr(app_config, "BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    backup_module.save_settings({"auto_enabled": False, "time": "21:00", "copy_folder": "", "keep_count": 30})
    assert backup_module.run_scheduled_backup_if_due() is None
    assert db.list_backup_log() == []


def test_claim_is_exclusive(app):
    assert db.claim_backup_run("2000-01-01 00:00:00") is not None
    assert db.claim_backup_run("2000-01-01 00:00:00") is None  # a second scheduler loses the race


