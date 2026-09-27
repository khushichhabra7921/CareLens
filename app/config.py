"""App settings, read from environment variables (or a local .env file).

If a required secret is missing, or still set to a placeholder from
.env.example, creating Settings raises an error and the app refuses to start.
"""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_PREFIX = "change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database: the web app always connects as the read-only role.
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    postgres_db: str = "carelens"
    app_db_user: str = "app_readonly"
    app_db_password: SecretStr  # required, no default

    # Protects POST /api/reports.
    admin_api_key: SecretStr  # required, no default

    # Optional: without a key, reports use the template fallback.
    groq_api_key: SecretStr | None = None
    llm_model: str | None = None

    @field_validator("app_db_password", "admin_api_key")
    @classmethod
    def reject_placeholders(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if not secret or secret.startswith(PLACEHOLDER_PREFIX):
            raise ValueError("is empty or still a placeholder from .env.example")
        return value


def get_settings() -> Settings:
    return Settings()
