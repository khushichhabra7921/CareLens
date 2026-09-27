"""Proves what the web app's database role (app_readonly) can and cannot do."""

import psycopg
import pytest

# Every row-level table: identifiers, pseudonymized clinical rows, and rejected load rows.
ROW_LEVEL_TABLES = ["phi.patient_identifiers", "loader.rejected_rows", "analytics.patients",
                    "analytics.encounters", "analytics.observations", "analytics.conditions"]


@pytest.mark.parametrize("table", ROW_LEVEL_TABLES)
def test_app_role_cannot_read_any_row_level_table(app_conn, table):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(f"SELECT * FROM {table} LIMIT 1")


def test_app_role_has_no_privileges_at_all_on_row_level_schemas(app_conn):
    # Checked in the catalog as well, so a future GRANT on any such table is caught too.
    row = app_conn.execute("""
        SELECT has_schema_privilege('app_readonly', 'phi', 'USAGE'),
               has_schema_privilege('app_readonly', 'analytics', 'USAGE'),
               has_schema_privilege('app_readonly', 'loader', 'USAGE'),
               EXISTS (SELECT 1 FROM information_schema.role_table_grants
                       WHERE grantee = 'app_readonly'
                         AND table_schema IN ('phi', 'analytics', 'loader'))
    """).fetchone()
    assert row == (False, False, False, False)


def test_app_role_can_read_the_aggregate_views(app_conn):
    count = app_conn.execute("SELECT count(*) FROM reporting.population_overview").fetchone()[0]
    assert count > 0


@pytest.mark.parametrize("statement", [
    "INSERT INTO analytics.payers VALUES (gen_random_uuid(), 'x', 'PRIVATE')",
    "UPDATE analytics.patients SET gender = 'F'",
    "DELETE FROM analytics.encounters",
    "TRUNCATE analytics.observations",
    "CREATE TABLE reporting.sneaky (id int)",
    "CREATE TEMP TABLE sneaky (id int)",
    "REFRESH MATERIALIZED VIEW reporting.population_overview",
])
def test_app_role_cannot_change_anything(app_conn, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(statement)


def test_analytics_tables_hold_no_direct_identifiers(loader_conn):
    # Column names that would mean an identifier leaked into a schema outside phi.
    forbidden = {"first_name", "last_name", "middle_name", "maiden_name", "ssn", "drivers",
                 "passport", "address", "birth_date", "birthdate", "lat", "lon", "zip", "phone"}
    columns = {c for (c,) in loader_conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema IN ('analytics', 'reporting')")}
    assert not columns & forbidden
