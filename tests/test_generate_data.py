"""Checks that the Synthea command is fully pinned (no Java needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_data  # noqa: E402


def command() -> list:
    return generate_data.build_command(
        Path("synthea.jar"), 1000, 42, "20250101", "Massachusetts", Path("out")
    )


def flag_value(cmd: list, flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_seeds_and_dates_are_fixed():
    cmd = command()
    assert flag_value(cmd, "-s") == "42"
    assert flag_value(cmd, "-cs") == "42"
    assert flag_value(cmd, "-r") == "20250101"
    # Without -e, Synthea simulates up to the real current date and output changes daily.
    assert flag_value(cmd, "-e") == "20250101"


def test_csv_on_and_all_fhir_off():
    cmd = command()
    assert "--exporter.csv.export=true" in cmd
    assert "--exporter.fhir.export=false" in cmd
    assert "--exporter.hospital.fhir.export=false" in cmd
    assert "--exporter.practitioner.fhir.export=false" in cmd


def test_jar_is_pinned_to_a_release_not_latest():
    assert "master-branch-latest" not in generate_data.JAR_URL
    assert len(generate_data.JAR_SHA256) == 64
