"""Shared database settings and connections for the scripts (not used by the web app).

Reads the same .env file as Docker Compose. Each role gets its own password:
  admin  -> POSTGRES_USER / POSTGRES_PASSWORD  (creates the database and roles)
  loader -> carelens_loader / LOADER_PASSWORD  (owns the tables, loads data)
  app    -> app_readonly / APP_DB_PASSWORD     (what the web app uses)
"""

import sys
from pathlib import Path

import psycopg
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "sql"

LOADER_ROLE = "carelens_loader"
APP_ROLE = "app_readonly"


class DbSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    db_host: str = "127.0.0.1"
    db_port: int = 5433
    postgres_db: str = "carelens"
    # "prefer" locally (Docker Postgres has no TLS); "verify-full" against RDS.
    db_sslmode: str = "prefer"
    postgres_user: str = "postgres"
    postgres_password: SecretStr | None = None
    loader_password: SecretStr | None = None
    app_db_password: SecretStr | None = None
    name_hash_salt: SecretStr | None = None


def settings() -> DbSettings:
    return DbSettings()


def connect(role: str, dbname: str | None = None, autocommit: bool = False) -> psycopg.Connection:
    """Open a connection as 'admin', 'loader' or 'app'. Exits with a clear message if the
    password for that role is missing."""
    s = settings()
    user, password = {
        "admin": (s.postgres_user, s.postgres_password),
        "loader": (LOADER_ROLE, s.loader_password),
        "app": (APP_ROLE, s.app_db_password),
    }[role]
    if password is None or not password.get_secret_value():
        sys.exit(f"Missing password for the {role} role. Set it in .env (see .env.example).")
    return psycopg.connect(
        host=s.db_host,
        port=s.db_port,
        dbname=dbname or s.postgres_db,
        user=user,
        password=password.get_secret_value(),
        sslmode=s.db_sslmode,
        autocommit=autocommit,
        connect_timeout=10,
    )
