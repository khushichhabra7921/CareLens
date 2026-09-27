import pytest
from pydantic import ValidationError

from app.config import Settings

TEST_KEY = "test-admin-key-0123456789"   # 25 characters


@pytest.fixture
def valid_env(monkeypatch):
    monkeypatch.setenv("APP_DB_PASSWORD", "test-db-password")
    monkeypatch.setenv("ADMIN_API_KEY", TEST_KEY)


def load_settings() -> Settings:
    # _env_file=None: ignore any local .env so tests only see what we set here.
    return Settings(_env_file=None)


def test_loads_when_required_secrets_present(valid_env):
    settings = load_settings()
    assert settings.admin_api_key.get_secret_value() == TEST_KEY
    assert settings.groq_api_key is None  # the LLM key is optional


@pytest.mark.parametrize("missing", ["APP_DB_PASSWORD", "ADMIN_API_KEY"])
def test_refuses_to_start_without_required_secret(valid_env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError):
        load_settings()


@pytest.mark.parametrize("value", ["", "change-me-admin-key", "short-key-19-chars!"])
def test_rejects_empty_placeholder_or_short_admin_key(valid_env, monkeypatch, value):
    monkeypatch.setenv("ADMIN_API_KEY", value)
    with pytest.raises(ValidationError):
        load_settings()


def test_secrets_are_hidden_when_printed(valid_env):
    assert TEST_KEY not in repr(load_settings())
