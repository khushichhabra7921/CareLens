"""Generate synthetic patients with Synthea, reproducibly.

Downloads a pinned Synthea release into tools/ (checking its SHA-256), then runs it
with fixed seeds and a fixed reference date, writing CSVs to data/raw/csv/.

Usage (PowerShell, from the repo root):
    py -3.12 scripts/generate_data.py                 # 1,000 patients
    py -3.12 scripts/generate_data.py -p 200          # smaller population
    py -3.12 scripts/generate_data.py --force         # replace existing data/raw
"""

import argparse
import csv
import hashlib
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
OUTPUT_DIR = REPO_ROOT / "data" / "raw"

# Pinned release, so the same seed always produces the same patients.
# "master-branch-latest" would change over time and break reproducibility.
SYNTHEA_VERSION = "v4.0.0"
JAR_NAME = "synthea-with-dependencies.jar"
JAR_URL = (
    f"https://github.com/synthetichealth/synthea/releases/download/{SYNTHEA_VERSION}/{JAR_NAME}"
)
# Published by GitHub for this release asset.
JAR_SHA256 = "ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1"
JAR_PATH = TOOLS_DIR / JAR_NAME


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_jar() -> Path:
    """Download the Synthea jar if missing, and always verify its checksum."""
    if not JAR_PATH.exists():
        TOOLS_DIR.mkdir(exist_ok=True)
        partial = JAR_PATH.with_suffix(".part")
        print(f"Downloading Synthea {SYNTHEA_VERSION} (about 190 MB) from GitHub...")
        with urllib.request.urlopen(JAR_URL) as response, open(partial, "wb") as out:
            shutil.copyfileobj(response, out)
        partial.replace(JAR_PATH)  # only a complete download gets the real name

    actual = sha256_of(JAR_PATH)
    if actual != JAR_SHA256:
        JAR_PATH.unlink()  # never run a jar we can't verify
        sys.exit(f"Checksum mismatch for {JAR_NAME} (got {actual}). Deleted it; re-run to retry.")
    print(f"Synthea jar OK ({SYNTHEA_VERSION}, sha256 verified).")
    return JAR_PATH


def build_command(
    jar: Path, population: int, seed: int, reference_date: str, state: str, output_dir: Path
) -> list:
    """The exact Synthea command line. Every setting that affects the output is fixed here."""
    return [
        "java", "-jar", str(jar),
        "-s", str(seed),             # patient generation seed
        "-cs", str(seed),            # clinician seed
        "-r", reference_date,        # date used to compute ages (YYYYMMDD)
        # End of the simulated timeline. Without -e, Synthea simulates up to the real
        # current date, so the same seed gives different data on different days.
        "-e", reference_date,
        "-p", str(population),       # number of living patients (deceased ones are extra)
        "--exporter.baseDirectory=" + str(output_dir),
        "--exporter.csv.export=true",
        # FHIR is on by default, including separate hospital/practitioner files. Turn it all off.
        "--exporter.fhir.export=false",
        "--exporter.hospital.fhir.export=false",
        "--exporter.practitioner.fhir.export=false",
        # Real-looking names ("Jose Ortiz", not "Jose871 Ortiz") so the name redactor is
        # tested against realistic data, not an easy digit pattern.
        "--generate.append_numbers_to_person_names=false",
        state,
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-p", "--population", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reference-date", default="20250101", help="YYYYMMDD")
    parser.add_argument("--state", default="Massachusetts")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--force", action="store_true", help="delete existing output first")
    args = parser.parse_args()

    if shutil.which("java") is None:
        sys.exit("Java not found. Synthea needs JDK 17 or newer on PATH.")

    # Refuse to mix a new run with old files unless explicitly asked.
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        if not args.force:
            sys.exit(f"{output_dir} already exists. Re-run with --force to replace it.")
        shutil.rmtree(output_dir)

    jar = ensure_jar()
    command = build_command(
        jar, args.population, args.seed, args.reference_date, args.state, output_dir
    )
    print("Running:", " ".join(command))
    subprocess.run(command, check=True, cwd=REPO_ROOT)

    print(f"\nCSV files written to {output_dir / 'csv'}:")
    for csv_file in sorted((output_dir / "csv").glob("*.csv")):
        with open(csv_file, encoding="utf-8", newline="") as f:
            rows = sum(1 for _ in csv.reader(f)) - 1  # csv-aware; minus header
        print(f"  {csv_file.name:<28} {rows:>10,} rows")


if __name__ == "__main__":
    main()
