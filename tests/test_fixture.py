"""Checks on the committed test fixture (tests/fixtures/synthea_mini)."""

import csv
import filecmp
import sys
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(FIXTURE_DIR))
import build_fixture  # noqa: E402

MINI = build_fixture.OUT_DIR
RAW_CSV = Path(__file__).resolve().parent.parent / "data" / "raw" / "csv"


def read(table: str) -> list[dict]:
    with open(MINI / f"{table}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_committed_fixture_matches_builder(tmp_path):
    # If this fails, someone edited build_fixture.py without re-running it (or vice versa).
    build_fixture.build().write(tmp_path)
    for table in build_fixture.HEADERS:
        assert filecmp.cmp(tmp_path / f"{table}.csv", MINI / f"{table}.csv", shallow=False), table


def test_fixture_has_every_table_and_is_under_1_mb():
    files = [MINI / f"{table}.csv" for table in build_fixture.HEADERS]
    assert all(f.exists() for f in files)
    assert sum(f.stat().st_size for f in files) < 1_000_000


def test_fixture_ssns_are_never_issued_numbers():
    # SSNs starting with 9 are never issued, so the fixture can't hold a real person's SSN.
    assert all(p["SSN"].startswith("999-") for p in read("patients"))


def test_every_foreign_key_points_to_an_existing_row():
    patients = {p["Id"] for p in read("patients")}
    encounters = {e["Id"] for e in read("encounters")}
    for e in read("encounters"):
        assert e["PATIENT"] in patients
    for table in ["conditions", "medications", "observations", "procedures", "immunizations"]:
        for row in read(table):
            assert row["PATIENT"] in patients, table
            assert row["ENCOUNTER"] == "" or row["ENCOUNTER"] in encounters, table


@pytest.mark.skipif(not RAW_CSV.exists(), reason="no generated Synthea data on this machine")
def test_fixture_headers_match_generated_synthea_data():
    # Catches a Synthea version change that renames or adds columns.
    for table, header in build_fixture.HEADERS.items():
        with open(RAW_CSV / f"{table}.csv", encoding="utf-8") as f:
            assert f.readline().strip() == header, table
