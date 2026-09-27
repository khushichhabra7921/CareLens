"""Proves what the web app's database role (app_readonly) can and cannot do."""

import psycopg
import pytest

PHI_AND_LOADER_TABLES = ["phi.patient_identifiers", "loader.rejected_rows"]


@pytest.mark.parametrize("table", PHI_AND_LOADER_TABLES)
def test_app_role_cannot_read_phi_or_loader_tables(app_conn, table):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(f"SELECT * FROM {table} LIMIT 1")


def test_app_role_has_no_privileges_at_all_on_phi(app_conn):
    # Checked in the catalog as well, so a future GRANT on any phi table is caught too.
    row = app_conn.execute("""
        SELECT has_schema_privilege('app_readonly', 'phi', 'USAGE'),
               has_schema_privilege('app_readonly', 'loader', 'USAGE'),
               EXISTS (SELECT 1 FROM information_schema.role_table_grants
                       WHERE grantee = 'app_readonly' AND table_schema IN ('phi', 'loader'))
    """).fetchone()
    assert row == (False, False, False)


def test_app_role_can_read_analytics(app_conn):
    assert app_conn.execute("SELECT count(*) FROM analytics.patients").fetchone()[0] == 8


@pytest.mark.parametrize("statement", [
    "INSERT INTO analytics.payers VALUES (gen_random_uuid(), 'x', 'PRIVATE')",
    "UPDATE analytics.patients SET gender = 'F'",
    "DELETE FROM analytics.encounters",
    "TRUNCATE analytics.observations",
    "CREATE TABLE analytics.sneaky (id int)",
    "CREATE TEMP TABLE sneaky (id int)",
])
def test_app_role_cannot_change_anything(app_conn, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(statement)


def test_analytics_tables_hold_no_direct_identifiers(loader_conn):
    # Column names that would mean an identifier leaked into the schema the app can read.
    forbidden = {"first_name", "last_name", "middle_name", "maiden_name", "ssn", "drivers",
                 "passport", "address", "birth_date", "birthdate", "lat", "lon", "zip", "phone"}
    columns = {c for (c,) in loader_conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics'")}
    assert not columns & forbidden
