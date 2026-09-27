"""/health without a database: the app still starts, and reports itself as not ready."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_is_503_when_database_is_unreachable(monkeypatch):
    monkeypatch.setenv("APP_DB_PASSWORD", "test-db-password")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key-0123456789")
    monkeypatch.setenv("NAME_HASH_SALT", "test-name-hash-salt-0123456789")
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "1")   # nothing listens on port 1
    # Using TestClient as a context manager runs the startup (lifespan) code.
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
