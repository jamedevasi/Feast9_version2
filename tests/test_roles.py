from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def _create_user(admin_client, username, role, password="testpass123"):
    token = get_csrf(admin_client, "/users/new")
    admin_client.post(
        "/users/new",
        data={
            "username": username,
            "password": password,
            "confirm": password,
            "role": role,
            "security_question": "City?",
            "security_answer": "Test",
            "csrf_token": token,
        },
    )


def _logout(client):
    token = get_csrf(client, "/dashboard")
    client.post("/logout", data={"csrf_token": token})


def _login(client, username, password="testpass123"):
    token = get_csrf(client, "/login")
    client.post("/login", data={"username": username, "password": password, "csrf_token": token})


def test_admin_can_create_list_and_deactivate_user(logged_in_client):
    _create_user(logged_in_client, "recep1", "receptionist")
    resp = logged_in_client.get("/users/")
    assert b"recep1" in resp.data

    recep = next(u for u in db.list_users() if u["username"] == "recep1")
    assert recep["role"] == "receptionist"
    assert recep["is_active"] == 1

    token = get_csrf(logged_in_client, "/users/")
    logged_in_client.post(f"/users/{recep['id']}/deactivate", data={"csrf_token": token})
    assert db.get_user_by_id(recep["id"])["is_active"] == 0


def test_duplicate_username_rejected(logged_in_client):
    _create_user(logged_in_client, "dup1", "doctor")
    token = get_csrf(logged_in_client, "/users/new")
    resp = logged_in_client.post(
        "/users/new",
        data={
            "username": "dup1",
            "password": "testpass123",
            "confirm": "testpass123",
            "role": "doctor",
            "security_question": "Q",
            "security_answer": "A",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 200
    assert b"already taken" in resp.data


def test_cannot_deactivate_only_admin(logged_in_client):
    admin = db.get_admin()
    token = get_csrf(logged_in_client, "/users/")
    logged_in_client.post(f"/users/{admin['id']}/deactivate", data={"csrf_token": token})
    assert db.get_user_by_id(admin["id"])["is_active"] == 1


def test_deactivated_user_cannot_login(logged_in_client):
    _create_user(logged_in_client, "recep2", "receptionist")
    recep = next(u for u in db.list_users() if u["username"] == "recep2")
    token = get_csrf(logged_in_client, "/users/")
    logged_in_client.post(f"/users/{recep['id']}/deactivate", data={"csrf_token": token})

    _logout(logged_in_client)
    token = get_csrf(logged_in_client, "/login")
    resp = logged_in_client.post(
        "/login",
        data={"username": "recep2", "password": "testpass123", "csrf_token": token},
    )
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


def test_non_admin_cannot_manage_users(logged_in_client):
    _create_user(logged_in_client, "recep3", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recep3")

    assert logged_in_client.get("/users/").status_code == 403
    assert logged_in_client.get("/users/new").status_code == 403


def test_receptionist_blocked_from_payment_and_cost_routes(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id, total_cost="5000")
    case_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    case_url = resp.headers["Location"]

    _create_user(logged_in_client, "recep4", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recep4")

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": "2026-01-10", "amount": "100", "csrf_token": token},
    )
    assert resp.status_code == 403

    resp = logged_in_client.post(
        f"/cases/{case_id}/revise-cost",
        data={"new_cost": "9999", "reason": "hack", "csrf_token": token},
    )
    assert resp.status_code == 403

    assert db.get_case(case_id)["total_cost"] == 5000
    assert db.list_payments_for_case(case_id) == []


def test_receptionist_case_detail_hides_financial_data(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id, total_cost="5000")
    case_url = resp.headers["Location"]

    _create_user(logged_in_client, "recep5", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recep5")

    detail_resp = logged_in_client.get(case_url)
    assert detail_resp.status_code == 200
    assert b"5000.00" not in detail_resp.data
    assert b"Estimated Cost" not in detail_resp.data
    assert b"Balance due" not in detail_resp.data
    assert b"Restricted" in detail_resp.data


def test_doctor_retains_financial_access(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id, total_cost="5000")
    case_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    case_url = resp.headers["Location"]

    _create_user(logged_in_client, "doc2", "doctor")
    _logout(logged_in_client)
    _login(logged_in_client, "doc2")

    detail_resp = logged_in_client.get(case_url)
    assert b"5000.00" in detail_resp.data

    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": "2026-01-10", "amount": "1000", "csrf_token": token},
    )
    assert resp.status_code == 302
    assert db.get_case_balance(case_id) == 4000


def test_receptionist_case_creation_ignores_spoofed_total_cost(logged_in_client, patient_id):
    _create_user(logged_in_client, "recep6", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recep6")

    doctor_id = db.add_doctor("Dr. Recep Test", "#111111")
    token = get_csrf(logged_in_client, f"/patients/{patient_id}/cases/new")
    resp = logged_in_client.post(
        f"/patients/{patient_id}/cases/new",
        data={
            "title": "Spoofed Case",
            "doctor_id": str(doctor_id),
            "total_cost": "99999",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 302
    case_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    assert db.get_case(case_id)["total_cost"] == 0
