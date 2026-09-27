"""Load Synthea CSVs into Postgres. Safe to re-run: each run fully replaces the data.

Steps, all inside ONE transaction (so a failed run leaves the previous data untouched):
  1. Check each CSV has exactly the expected Synthea v4.0.0 header.
  2. COPY each CSV into a temporary all-text staging table (fast bulk load).
  3. Check the staged row count equals the CSV row count.
  4. Empty the target tables, then run sql/load/transform.sql, which validates every row,
     inserts the good ones and records the bad ones (with a reason) in loader.rejected_rows.
  5. Check loaded + rejected = CSV rows for every table, then commit.

Usage (PowerShell, repo root):
    py -3.12 scripts/load_data.py                                   # data/raw/csv
    py -3.12 scripts/load_data.py --csv-dir tests/fixtures/synthea_mini
"""

import argparse
import csv
import time
from pathlib import Path

import psycopg
from psycopg import sql

from common import REPO_ROOT, SQL_DIR, connect, settings
from synthea_columns import HEADERS

# CSV file -> target table. Order matters: parents before children (foreign keys).
TARGETS = {
    "patients": "analytics.patients",
    "organizations": "analytics.organizations",
    "providers": "analytics.providers",
    "payers": "analytics.payers",
    "encounters": "analytics.encounters",
    "conditions": "analytics.conditions",
    "medications": "analytics.medications",
    "observations": "analytics.observations",
    "procedures": "analytics.procedures",
    "immunizations": "analytics.immunizations",
}


class LoadError(Exception):
    pass


def count_csv_rows(path: Path) -> int:
    # csv-aware count (a quoted field could contain a newline), minus the header.
    with open(path, encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def check_header(path: Path, table: str) -> list[str]:
    with open(path, encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    expected = HEADERS[table].split(",")
    if header != expected:
        raise LoadError(f"{path.name}: header differs from Synthea v4.0.0.\n"
                        f"  expected: {expected}\n  found:    {header}")
    return header


def stage(conn: psycopg.Connection, path: Path, table: str, header: list[str]) -> int:
    """COPY one CSV into temp table stg_<table> (every column text, lower-case names)."""
    staging = sql.Identifier(f"stg_{table}")
    columns = sql.SQL(", ").join(
        sql.SQL("{} text").format(sql.Identifier(c.lower())) for c in header
    )
    conn.execute(sql.SQL("CREATE TEMP TABLE {} ({}) ON COMMIT DROP").format(staging, columns))
    # In CSV mode COPY turns empty fields into NULL. FORCE_NOT_NULL keeps them as '' so the
    # transform SQL can treat "empty" one way everywhere (NULLIF(x, '') where NULL is wanted).
    names = sql.SQL(", ").join(sql.Identifier(c.lower()) for c in header)
    with conn.cursor() as cur:
        copy_sql = sql.SQL(
            "COPY {} FROM STDIN (FORMAT csv, HEADER true, FORCE_NOT_NULL ({}))"
        ).format(staging, names)
        with cur.copy(copy_sql) as copy, open(path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                copy.write(chunk)
    return conn.execute(sql.SQL("SELECT count(*) FROM {}").format(staging)).fetchone()[0]


def load(csv_dir: Path, dbname: str | None = None) -> dict:
    """Load every table; returns {table: {"csv": n, "loaded": n, "rejected": n}}."""
    report = {}
    with connect("loader", dbname=dbname) as conn:  # commits on success, rolls back on error
        conn.execute("SET LOCAL timezone = 'UTC'")
        for table in TARGETS:
            path = csv_dir / f"{table}.csv"
            if not path.exists():
                raise LoadError(f"Missing {path}")
            header = check_header(path, table)
            csv_rows = count_csv_rows(path)
            staged = stage(conn, path, table, header)
            if staged != csv_rows:
                raise LoadError(f"{table}: CSV has {csv_rows} rows but {staged} were staged")
            report[table] = {"csv": csv_rows}
            print(f"  staged {table:<14} {staged:>9,} rows")

        # TRUNCATE ... CASCADE also empties phi.patient_identifiers (it references patients).
        # RESTART IDENTITY makes generated ids start from 1 again, so reloads are identical.
        conn.execute("TRUNCATE " + ", ".join(TARGETS.values()) + ", loader.rejected_rows "
                     "RESTART IDENTITY CASCADE")
        conn.execute("SELECT set_config('carelens.source', %s, true)", [csv_dir.name])
        conn.execute((SQL_DIR / "load" / "transform.sql").read_text(encoding="utf-8"))

        rejected_by_reason = conn.execute(
            "SELECT table_name, reason, count(*) FROM loader.rejected_rows "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall()
        for table, target in TARGETS.items():
            loaded = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(
                sql.Identifier(*target.split(".")))).fetchone()[0]
            rejected = sum(n for t, _, n in rejected_by_reason if t == table)
            report[table].update(loaded=loaded, rejected=rejected)
            if loaded + rejected != report[table]["csv"]:
                raise LoadError(f"{table}: {report[table]['csv']} CSV rows but "
                                f"{loaded} loaded + {rejected} rejected")

        # Safety net: the reference date must be the latest *loaded* encounter date.
        ref, latest = conn.execute(
            "SELECT d.reference_date, (SELECT max(start_ts)::date FROM analytics.encounters) "
            "FROM analytics.dataset_info d"
        ).fetchone()
        if ref != latest:
            raise LoadError(f"reference date {ref} != latest loaded encounter {latest}")
        report["_reference_date"] = ref
        report["_rejected_by_reason"] = rejected_by_reason
        conn.execute("ANALYZE")  # fresh statistics so the query planner makes good choices
    return report


def print_report(report: dict) -> None:
    print(f"\n{'table':<15}{'csv rows':>11}{'loaded':>11}{'rejected':>10}")
    for table in TARGETS:
        r = report[table]
        print(f"{table:<15}{r['csv']:>11,}{r['loaded']:>11,}{r['rejected']:>10,}")
    print(f"\nReference date (latest encounter): {report['_reference_date']}")
    if report["_rejected_by_reason"]:
        print("Rejected rows by reason (details in loader.rejected_rows, loader role only):")
        for table, reason, n in report["_rejected_by_reason"]:
            print(f"  {table:<14} {reason:<30} {n:>7,}")
    else:
        print("No rows rejected.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Synthea CSVs into Postgres.")
    parser.add_argument("--csv-dir", type=Path, default=REPO_ROOT / "data" / "raw" / "csv")
    parser.add_argument("--database", default=settings().postgres_db)
    args = parser.parse_args()

    started = time.perf_counter()
    print(f"Loading {args.csv_dir} into database {args.database} ...")
    try:
        report = load(args.csv_dir.resolve(), args.database)
    except LoadError as err:
        raise SystemExit(f"Load failed, nothing was changed: {err}") from None
    print_report(report)
    print(f"\nFinished in {time.perf_counter() - started:.1f}s.")


if __name__ == "__main__":
    main()
