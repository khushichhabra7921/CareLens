"""Loader tests against the fixture (tests/fixtures/synthea_mini)."""

import csv
import shutil
from datetime import date

import pytest
from conftest import FIXTURE_CSV, TEST_DB

import build_fixture
import load_data

# Rows per table in the fixture, straight from the builder.
EXPECTED_ROWS = {table: len(rows) for table, rows in build_fixture.build().rows.items()}
HAND_WRITTEN = {"Will", "Robert", "Mary", "Mark", "Hope", "José", "Grace", "Ava"}


def by_first_name(conn) -> dict:
    # Only the 8 hand-written patients (cohort patients share first names with each other).
    rows = conn.execute("""
        SELECT i.first_name, p.age_band, p.zip3, p.is_deceased
        FROM analytics.patients p JOIN phi.patient_identifiers i USING (patient_id)""")
    return {name: rest for name, *rest in rows if name in HAND_WRITTEN}


def test_every_row_loaded_and_reconciled(test_db):
    report = load_data.load(FIXTURE_CSV, TEST_DB)
    for table, n in EXPECTED_ROWS.items():
        assert report[table] == {"csv": n, "loaded": n, "rejected": 0}, table


def test_reload_is_idempotent(test_db, loader_conn):
    load_data.load(FIXTURE_CSV, TEST_DB)
    load_data.load(FIXTURE_CSV, TEST_DB)
    assert loader_conn.execute("SELECT count(*) FROM analytics.encounters").fetchone()[0] == (
        EXPECTED_ROWS["encounters"])
    # RESTART IDENTITY: generated ids start at 1 again on each load.
    assert loader_conn.execute("SELECT min(observation_id) FROM analytics.observations"
                               ).fetchone()[0] == 1


def test_reference_date_is_latest_encounter_not_today(loader_conn):
    ref = loader_conn.execute("SELECT reference_date FROM analytics.dataset_info").fetchone()[0]
    assert ref == date(2024, 12, 2)  # the fixture's latest encounter (infant well-child visit)


def test_age_bands_computed_at_reference_date(loader_conn):
    # Worked out by hand from the fixture birth dates and the 2024-12-02 reference date.
    bands = {name: band for name, (band, _, _) in by_first_name(loader_conn).items()}
    assert bands == {
        "Will": "90+",       # born 1932-06-01 -> 92
        "Robert": "75-89",   # born 1940-01-10, died 2023-08-20 -> 83 at death
        "Mary": "65-74",     # born 1950-03-15 -> 74
        "Mark": "65-74",     # born 1958-04-04 -> 66
        "Hope": "45-64",     # born 1972-09-09 -> 52
        "José": "18-44",     # born 1985-07-22 -> 39
        "Grace": "18-44",    # born 1990-12-31 -> 33 (birthday not yet reached)
        "Ava": "0-17",       # born 2024-11-02 -> 0
    }


def test_deceased_flag_and_observation_without_encounter(loader_conn):
    assert by_first_name(loader_conn)["Robert"][2] is True
    assert loader_conn.execute(
        "SELECT count(*) FROM analytics.observations WHERE encounter_id IS NULL").fetchone()[0] == 1


def edited_fixture(tmp_path, table, edit):
    """Copy the fixture and change one table's rows with edit(rows)."""
    target = tmp_path / "csv"
    shutil.copytree(FIXTURE_CSV, target)
    path = target / f"{table}.csv"
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header, rows = reader.fieldnames, list(reader)
    edit(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return target


def test_bad_rows_are_rejected_with_reasons_and_counts_still_reconcile(tmp_path, loader_conn):
    def break_encounters(rows):
        rows[0]["PATIENT"] = "11111111-1111-1111-1111-111111111111"   # patient doesn't exist
        rows[1]["START"] = "not-a-date"
        rows[2]["TOTAL_CLAIM_COST"] = "-5.00"
        rows[3]["PAYER_COVERAGE"] = "999999.00"                         # more than the cost
        rows[4]["PROVIDER"] = "not-a-uuid"

    csv_dir = edited_fixture(tmp_path, "encounters", break_encounters)
    report = load_data.load(csv_dir, TEST_DB)
    n = EXPECTED_ROWS["encounters"]
    assert report["encounters"] == {"csv": n, "loaded": n - 5, "rejected": 5}
    reasons = {r for t, r, _ in report["_rejected_by_reason"] if t == "encounters"}
    assert reasons == {"unknown patient", "invalid timestamp", "negative cost",
                       "coverage exceeds cost", "invalid provider id"}
    # Children of rejected encounters are rejected too, and still add up.
    for table, r in report.items():
        if not table.startswith("_"):
            assert r["loaded"] + r["rejected"] == r["csv"], table
    load_data.load(FIXTURE_CSV, TEST_DB)  # restore the clean fixture for other tests


def test_wrong_header_fails_and_leaves_previous_data_untouched(tmp_path, loader_conn):
    target = tmp_path / "csv"
    shutil.copytree(FIXTURE_CSV, target)
    text = (target / "payers.csv").read_text(encoding="utf-8")
    (target / "payers.csv").write_text(text.replace("OWNERSHIP", "OWNER_TYPE", 1),
                                       encoding="utf-8")
    with pytest.raises(load_data.LoadError, match="header differs"):
        load_data.load(target, TEST_DB)
    assert loader_conn.execute("SELECT count(*) FROM analytics.patients").fetchone()[0] == (
        EXPECTED_ROWS["patients"])
