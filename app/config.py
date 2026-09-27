"""App settings, read from environment variables (or a local .env file).

If a required secret is missing, or still set to a placeholder from
.env.example, creating Settings raises an error and the app refuses to start.
"""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_PREFIX = "change-me"
MIN_API_KEY_LENGTH = 20  # a short admin key could be guessed despite the rate limit


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database: the web app always connects as the read-only role.
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    postgres_db: str = "carelens"
    db_sslmode: str = "prefer"   # "verify-full" against RDS
    app_db_user: str = "app_readonly"
    app_db_password: SecretStr  # required, no default

    # Protects POST /api/reports.
    admin_api_key: SecretStr  # required, no default
    # Per client IP: at most this many report requests per window (protects the LLM quota).
    reports_rate_limit: int = 5
    reports_rate_window_seconds: int = 600

    # How long analysis results are cached in memory. They only change when data is loaded.
    cache_ttl_seconds: int = 300

    # Secret key for the name-token hashes (must match the one used by build_name_hashes.py).
    name_hash_salt: SecretStr  # required, no default

    # Optional: without a key and model, reports use the template fallback.
    groq_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 20
    llm_max_completion_tokens: int = 1500

    @field_validator("app_db_password", "admin_api_key", "name_hash_salt")
    @classmethod
    def reject_placeholders(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if not secret or secret.startswith(PLACEHOLDER_PREFIX):
            raise ValueError("is empty or still a placeholder from .env.example")
        return value

    @field_validator("admin_api_key", "name_hash_salt")
    @classmethod
    def require_long_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_API_KEY_LENGTH:
            raise ValueError(f"must be at least {MIN_API_KEY_LENGTH} characters")
        return value

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key.get_secret_value() and self.llm_model)


def get_settings() -> Settings:
    return Settings()
