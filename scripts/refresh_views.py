"""Build or refresh the analysis materialized views in the `reporting` schema.

Each file in sql/analyses/ becomes one materialized view, named after the file without its
number prefix: 04a_ed_visits_per_1000.sql -> reporting.ed_visits_per_1000.

Why materialized views: the analyses scan up to ~1 million rows, but their results are a few
dozen aggregate rows. Computing them once per data load makes the API instant, and it means
the web app only ever reads finished, suppressed aggregates (it has no access to the raw tables).

Usage (PowerShell, repo root):
    py -3.12 scripts/refresh_views.py            # re-run the queries (data changed)
    py -3.12 scripts/refresh_views.py --rebuild  # drop and recreate (SQL files changed)
load_data.py rebuilds automatically at the end of every load.
"""

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from common import SQL_DIR, connect

ANALYSES_DIR = SQL_DIR / "analyses"
HEADER_FIELDS = ["Title", "Question", "Method", "Assumptions", "Limitations"]


@dataclass
class Analysis:
    view: str      # name of the materialized view in the reporting schema
    path: Path
    header: dict   # Title / Question / Method / Assumptions / Limitations


def parse_header(text: str) -> dict:
    """Read the '-- Field: ...' comment block at the top of an analysis file."""
    header, current = {}, None
    for line in text.splitlines():
        if not line.startswith("--"):
            break
        body = line[2:].strip()
        match = re.match(r"(\w+):\s*(.*)", body)
        if match and match.group(1) in HEADER_FIELDS:
            current = match.group(1)
            header[current] = match.group(2)
        elif current and body:
            header[current] += " " + body
    missing = [f for f in HEADER_FIELDS if f not in header]
    if missing:
        raise ValueError(f"header is missing: {', '.join(missing)}")
    return header


def list_analyses() -> list[Analysis]:
    analyses = []
    for path in sorted(ANALYSES_DIR.glob("*.sql")):
        view = re.sub(r"^\d+[a-z]?_", "", path.stem)
        try:
            header = parse_header(path.read_text(encoding="utf-8"))
        except ValueError as err:
            raise SystemExit(f"{path.name}: {err}") from None
        analyses.append(Analysis(view, path, header))
    return analyses


def rebuild(conn: psycopg.Connection) -> None:
    """Drop and recreate every view from its SQL file (inside the caller's transaction)."""
    for a in list_analyses():
        name = sql.Identifier("reporting", a.view)
        conn.execute(sql.SQL("DROP MATERIALIZED VIEW IF EXISTS {}").format(name))
        query = a.path.read_text(encoding="utf-8")
        conn.execute(sql.SQL("CREATE MATERIALIZED VIEW {} AS {}").format(name, sql.SQL(query)))
    # Default privileges already cover new views; granting explicitly as well keeps it obvious.
    conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO app_readonly")


def refresh(conn: psycopg.Connection) -> None:
    for a in list_analyses():
        conn.execute(sql.SQL("REFRESH MATERIALIZED VIEW {}").format(
            sql.Identifier("reporting", a.view)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or refresh the analysis views.")
    parser.add_argument("--rebuild", action="store_true",
                        help="drop and recreate from sql/analyses (after editing the SQL)")
    parser.add_argument("--database", default=None)
    args = parser.parse_args()
    with connect("loader", dbname=args.database) as conn:
        conn.execute("SET LOCAL timezone = 'UTC'")
        (rebuild if args.rebuild else refresh)(conn)
    print(f"{'Rebuilt' if args.rebuild else 'Refreshed'} {len(list_analyses())} views.")


if __name__ == "__main__":
    main()
