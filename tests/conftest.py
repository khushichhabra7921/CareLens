"""Shared test setup: a throwaway 'carelens_test' database loaded with the fixture.

Database tests are skipped when Postgres isn't reachable (e.g. Docker not running), unless
REQUIRE_DB=1 is set. CI sets it, so there a missing database is a failure, not a skip.
"""

import os
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import common  # noqa: E402
import db_setup  # noqa: E402
import load_data  # noqa: E402

TEST_DB = "carelens_test"
FIXTURE_CSV = Path(__file__).parent / "fixtures" / "synthea_mini"


def _recreate_test_database() -> None:
    with common.connect("admin", dbname="postgres", autocommit=True) as conn:
        # WITH (FORCE) disconnects leftover sessions from an earlier, interrupted test run.
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
            sql.Identifier(TEST_DB)))


@pytest.fixture(scope="session")
def test_db() -> str:
    """Fresh database, schema applied and fixture loaded once per test session."""
    try:
        _recreate_test_database()
    except (psycopg.OperationalError, SystemExit) as err:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"Postgres not available ({err}). Start it with: docker compose up -d db")
    db_setup.setup(TEST_DB)
    load_data.load(FIXTURE_CSV, TEST_DB)
    return TEST_DB


@pytest.fixture
def loader_conn(test_db):
    with common.connect("loader", dbname=test_db) as conn:
        yield conn


@pytest.fixture
def app_conn(test_db):
    # autocommit: a permission error then doesn't leave the connection in a failed transaction.
    with common.connect("app", dbname=test_db, autocommit=True) as conn:
        yield conn
