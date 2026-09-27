"""Database connection pool. The web app always connects as app_readonly."""

from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

from app.config import Settings


def create_pool(settings: Settings) -> ConnectionPool:
    """A small pool: opening a Postgres connection is slow (TLS + auth), reusing one is fast."""
    conninfo = make_conninfo(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.postgres_db,
        user=settings.app_db_user,
        password=settings.app_db_password.get_secret_value(),
        sslmode=settings.db_sslmode,
        **({"sslrootcert": settings.db_sslrootcert} if settings.db_sslrootcert else {}),
        connect_timeout=10,
        application_name="carelens-api",
    )
    # open=False: the app opens it at startup. wait=False there, so the app still starts
    # (and /health reports the problem) if the database is briefly unavailable.
    return ConnectionPool(conninfo, min_size=1, max_size=5, open=False,
                          kwargs={"autocommit": True})
