"""The 8 analyses the API serves, and how to read them from the `reporting` views.

The list below is the allowlist: an analysis id from a URL is only ever looked up here, and
view names reach SQL only through psycopg's sql.Identifier (safe quoting), never from user
input. Titles, questions and limitations come from each view's comment, which
scripts/refresh_views.py copies from the SQL file's header.
"""

import json
import threading
import time
from dataclasses import dataclass

from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


@dataclass(frozen=True)
class AnalysisDef:
    id: str
    views: tuple[str, ...]   # one or more result tables, in display order


ANALYSES = [
    AnalysisDef("population-overview", ("population_overview",)),
    AnalysisDef("chronic-disease", ("chronic_disease_prevalence",)),
    AnalysisDef("readmissions", ("readmissions_30day",)),
    AnalysisDef("ed-utilization", ("ed_visits_per_1000", "ed_frequent_users")),
    AnalysisDef("cost-coverage", ("cost_by_class_payer", "top_conditions_by_cost")),
    AnalysisDef("care-gaps", ("care_gaps",)),
    AnalysisDef("polypharmacy", ("polypharmacy",)),
    AnalysisDef("flu-vaccination", ("flu_vaccination",)),
]
BY_ID = {a.id: a for a in ANALYSES}


def view_metadata(pool: ConnectionPool) -> dict[str, dict]:
    """{view name: header dict} for every materialized view in `reporting`."""
    with pool.connection() as conn:
        rows = conn.execute("""
            SELECT c.relname, obj_description(c.oid, 'pg_class')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'reporting' AND c.relkind = 'm'""").fetchall()
    return {name: json.loads(comment) if comment else {} for name, comment in rows}


def reference_date(pool: ConnectionPool):
    with pool.connection() as conn:
        row = conn.execute("SELECT reference_date FROM reporting.dataset_info").fetchone()
    return row[0] if row else None


def read_view(pool: ConnectionPool, view: str) -> tuple[list[str], list[dict]]:
    query = sql.SQL("SELECT * FROM {} ORDER BY sort_order").format(
        sql.Identifier("reporting", view))
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query)
        columns = [d.name for d in cur.description if d.name != "sort_order"]
        rows = [{c: r[c] for c in columns} for r in cur.fetchall()]
    return columns, rows


def load_analysis(pool: ConnectionPool, analysis: AnalysisDef) -> dict:
    meta = view_metadata(pool)
    tables = []
    for view in analysis.views:
        header = meta.get(view, {})
        columns, rows = read_view(pool, view)
        tables.append({
            "name": view,
            "title": header.get("Title", view),
            "question": header.get("Question", ""),
            "columns": columns,
            "rows": rows,
            "suppressed_rows": sum(1 for r in rows if r.get("suppressed")),
        })
    first = meta.get(analysis.views[0], {})
    return {
        "id": analysis.id,
        "title": first.get("Title", analysis.id),
        "question": first.get("Question", ""),
        "method": first.get("Method", ""),
        "assumptions": first.get("Assumptions", ""),
        "limitations": first.get("Limitations", ""),
        "reference_date": reference_date(pool),
        "tables": tables,
    }


class TTLCache:
    """A tiny in-memory cache. Results only change when data is reloaded, so a few minutes of
    caching makes repeat requests instant. Per process; fine for a single small server."""

    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._items: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, compute):
        now = time.monotonic()
        with self._lock:
            hit = self._items.get(key)
            if hit and hit[0] > now:
                return hit[1]
        value = compute()  # outside the lock, so one slow query doesn't block other keys
        with self._lock:
            self._items[key] = (now + self.ttl, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
