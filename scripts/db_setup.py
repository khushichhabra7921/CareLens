"""Create the database, roles, schemas, tables, indexes and grants. Safe to re-run.

Usage (PowerShell, repo root, Docker Postgres running):
    py -3.12 scripts/db_setup.py                 # set up the 'carelens' database
    py -3.12 scripts/db_setup.py --recreate      # DROP all CareLens schemas first (deletes data)
"""

import argparse

from psycopg import sql

import refresh_views
from common import APP_ROLE, LOADER_ROLE, SQL_DIR, connect, settings

SCHEMAS = ["phi", "analytics", "reporting", "app", "loader"]


def create_database(dbname: str) -> None:
    # CREATE DATABASE can't run inside a transaction, hence autocommit. Connect to the
    # built-in "postgres" database to do it.
    with connect("admin", dbname="postgres", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [dbname]).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
            print(f"Created database {dbname}.")


def create_roles(dbname: str) -> None:
    s = settings()
    with connect("admin", dbname=dbname) as conn:
        conn.execute((SQL_DIR / "roles.sql").read_text(encoding="utf-8"))
        # Passwords come from the environment, never from a committed file. sql.Literal
        # quotes the value safely (ALTER ROLE can't take a normal %s query parameter).
        for role, password in [(LOADER_ROLE, s.loader_password), (APP_ROLE, s.app_db_password)]:
            if password is None:
                raise SystemExit(f"Set the password for {role} in .env first.")
            conn.execute(
                sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password.get_secret_value())
                )
            )
    print("Roles ready: carelens_loader, app_readonly.")


def create_schema(dbname: str, recreate: bool) -> None:
    # Run as the loader, so the loader owns every object it creates.
    with connect("loader", dbname=dbname) as conn:  # one transaction: all or nothing
        if recreate:
            for schema in SCHEMAS:
                drop = sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE")
                conn.execute(drop.format(sql.Identifier(schema)))
            print("Dropped existing CareLens schemas.")
        for path in sorted((SQL_DIR / "schema").glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
            print(f"Applied {path.name}")
        refresh_views.rebuild(conn)  # the analysis views (empty until data is loaded)
        print("Built the analysis views.")


def setup(dbname: str, recreate: bool = False) -> None:
    create_database(dbname)
    create_roles(dbname)
    create_schema(dbname, recreate)


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up the CareLens database.")
    parser.add_argument("--database", default=settings().postgres_db)
    parser.add_argument("--recreate", action="store_true",
                        help="drop and recreate all CareLens schemas (deletes loaded data)")
    args = parser.parse_args()
    setup(args.database, args.recreate)
    print("Done.")


if __name__ == "__main__":
    main()
