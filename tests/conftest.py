import re

import pytest

from app import config as app_config
from app import create_app


@pytest.fixture()
def app(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(app_config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(app_config, "DB_PATH", str(data_dir / "feast9.db"))

    application = create_app()
    application.testing = True
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def get_csrf(client, path):
    resp = client.get(path)
    match = re.search(r'name="csrf_token" value="([a-f0-9]+)"', resp.data.decode())
    return match.group(1) if match else ""


@pytest.fixture()
def setup_admin(client):
    token = get_csrf(client, "/setup")
    client.post(
        "/setup",
        data={
            "username": "admin",
            "password": "testpass123",
            "confirm": "testpass123",
            "security_question": "City?",
            "security_answer": "Test",
            "csrf_token": token,
        },
    )
    return client


@pytest.fixture()
def logged_in_client(setup_admin):
    token = get_csrf(setup_admin, "/login")
    setup_admin.post(
        "/login",
        data={"username": "admin", "password": "testpass123", "csrf_token": token},
    )
    return setup_admin


def register_patient(client, **overrides):
    """Register a patient and return their id. Reused by case/appointment tests."""
    token = get_csrf(client, "/patients/new")
    data = {
        "name": "Case Test Patient",
        "date_of_birth": "1990-01-01",
        "sex": "Female",
        "mobile": "9876543210",
        "email": "casetest@example.com",
        "address": "1 Test Street",
        "dpdp_notice_accepted": "on",
        "csrf_token": token,
    }
    data.update(overrides)
    resp = client.post("/patients/new", data=data)
    patient_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    return patient_id


@pytest.fixture()
def patient_id(logged_in_client):
    return register_patient(logged_in_client)
