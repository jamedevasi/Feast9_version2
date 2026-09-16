from tests.conftest import get_csrf


def test_setup_redirects_to_login(client):
    token = get_csrf(client, "/setup")
    resp = client.post(
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
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_setup_blocked_once_admin_exists(setup_admin):
    resp = setup_admin.get("/setup")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_with_correct_credentials(setup_admin):
    token = get_csrf(setup_admin, "/login")
    resp = setup_admin.post(
        "/login",
        data={"username": "admin", "password": "testpass123", "csrf_token": token},
    )
    assert resp.status_code == 302


def test_login_with_wrong_password_shows_error(setup_admin):
    token = get_csrf(setup_admin, "/login")
    resp = setup_admin.post(
        "/login",
        data={"username": "admin", "password": "wrongpass", "csrf_token": token},
    )
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


def test_rate_limiting_after_8_failed_logins(setup_admin):
    client = setup_admin
    for _ in range(8):
        token = get_csrf(client, "/login")
        client.post("/login", data={"username": "admin", "password": "wrong", "csrf_token": token})

    token = get_csrf(client, "/login")
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "testpass123", "csrf_token": token},
    )
    assert b"Too many failed login attempts" in resp.data


def test_dashboard_requires_login(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_security_headers_present(client):
    resp = client.get("/login")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in resp.headers
