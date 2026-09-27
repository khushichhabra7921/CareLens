"""The settings used on AWS behind CloudFront (no database needed)."""

from fastapi.testclient import TestClient

from app.main import app

SECRET = "ci-only-origin-verify-secret-0123"


def client_with(monkeypatch, **env):
    monkeypatch.setenv("APP_DB_PASSWORD", "test-db-password")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key-0123456789")
    monkeypatch.setenv("NAME_HASH_SALT", "test-name-hash-salt-0123456789")
    monkeypatch.setenv("DB_PORT", "1")   # no database: these tests don't need one
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TestClient(app)


def test_requests_without_cloudfronts_secret_header_are_rejected(monkeypatch):
    with client_with(monkeypatch, ORIGIN_VERIFY_SECRET=SECRET) as client:
        assert client.get("/health").status_code == 403
        assert client.get("/health", headers={"X-Origin-Verify": "wrong"}).status_code == 403
        # With the right header the request reaches the app (503: no database in this test).
        assert client.get("/health", headers={"X-Origin-Verify": SECRET}).status_code == 503


def test_without_the_setting_no_header_is_needed(monkeypatch):
    monkeypatch.delenv("ORIGIN_VERIFY_SECRET", raising=False)
    with client_with(monkeypatch) as client:
        assert client.get("/health").status_code == 503


def test_rate_limit_uses_the_ip_cloudfront_appended(monkeypatch):
    from app.security import client_ip

    class FakeRequest:
        def __init__(self, forwarded):
            self.app = app
            self.headers = {"X-Forwarded-For": forwarded}
            self.client = type("C", (), {"host": "10.0.0.5"})()   # the CloudFront edge

    with client_with(monkeypatch, TRUST_PROXY_HEADERS="true"):
        # A client can put anything at the START; CloudFront appends the real IP at the END.
        assert client_ip(FakeRequest("6.6.6.6, 203.0.113.9")) == "203.0.113.9"
        assert client_ip(FakeRequest("")) == "10.0.0.5"
    with client_with(monkeypatch, TRUST_PROXY_HEADERS="false"):
        assert client_ip(FakeRequest("203.0.113.9")) == "10.0.0.5"   # header ignored locally
