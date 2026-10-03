"""TRUSTED_PROXY_COUNT: behind a reverse proxy the client's real address and scheme come from
X-Forwarded-* headers; without it those headers are ignored so nobody can fake an address."""
from flask import request, url_for

from app import config as app_config
from app import create_app, db
from app.auth import MAX_FAILED_ATTEMPTS, is_rate_limited
from tests.conftest import get_csrf


def _failed_login(client, forwarded_for):
    token = get_csrf(client, "/login")
    client.post("/login", data={"username": "admin", "password": "wrong-password", "csrf_token": token},
                headers={"X-Forwarded-For": forwarded_for})


def _app_with(monkeypatch, value):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", value)
    application = create_app()
    application.testing = True
    return application


def test_without_a_trusted_proxy_forwarded_headers_are_ignored(setup_admin, monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
    _failed_login(setup_admin, "10.0.0.7")
    failures = [e for e in db.list_audit_log() if e["action"] == "login_failed"]
    assert failures[0]["ip"] == "127.0.0.1"
    # Faking a new address on every attempt doesn't escape the per-IP limit.
    for n in range(MAX_FAILED_ATTEMPTS):
        _failed_login(setup_admin, f"10.0.1.{n}")
    assert is_rate_limited("127.0.0.1")


def test_behind_one_proxy_each_device_is_counted_separately(app, setup_admin, monkeypatch):
    proxied = _app_with(monkeypatch, "1").test_client()
    for _ in range(MAX_FAILED_ATTEMPTS):
        _failed_login(proxied, "192.168.1.20")
    assert is_rate_limited("192.168.1.20")
    assert not is_rate_limited("127.0.0.1")     # the proxy itself, i.e. everyone else
    assert not is_rate_limited("192.168.1.21")  # another front-desk PC
    failures = [e for e in db.list_audit_log() if e["action"] == "login_failed"]
    assert {f["ip"] for f in failures} == {"192.168.1.20"}


def test_behind_one_proxy_links_use_the_original_scheme_and_host(app, monkeypatch):
    proxied = _app_with(monkeypatch, "1")

    @proxied.route("/_test_whoami")
    def whoami():
        return f"{request.remote_addr} {url_for('auth.login', _external=True)}"

    headers = {"X-Forwarded-For": "192.168.1.20", "X-Forwarded-Proto": "https",
               "X-Forwarded-Host": "feast9.clinic.lan"}
    body = proxied.test_client().get("/_test_whoami", headers=headers).data.decode()
    assert body == "192.168.1.20 https://feast9.clinic.lan/login"


def test_trusted_proxy_count_parsing(monkeypatch):
    for raw, expected in (("", 0), ("0", 0), ("1", 1), ("2", 2), ("99", 5), ("yes", 0), ("-1", 0)):
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", raw)
        assert app_config.trusted_proxy_count() == expected, raw
