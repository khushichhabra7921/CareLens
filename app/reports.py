"""Create, store and fetch insight reports.

M5: every report comes from the template (no LLM). M6 adds the privacy-safe LLM pipeline in
front of it, keeping the template as the fallback.
"""

import json
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.report_schema import Grounding, ReportRecord
from app.template_report import build_template_report


def create_report(pool: ConnectionPool, analysis: dict) -> ReportRecord:
    report = build_template_report(analysis)
    body = {
        "reference_date": analysis["reference_date"],
        "source": "template",
        "model": None,
        "report": report.model_dump(),
        "redactions": {},
        "grounding": Grounding(status="not_checked").model_dump(),
    }
    with pool.connection() as conn:
        report_id, created_at = conn.execute(
            "INSERT INTO app.reports (analysis_id, source, report) VALUES (%s, %s, %s) "
            "RETURNING report_id, created_at",
            [analysis["id"], "template", Jsonb(body, dumps=_json_dumps)],
        ).fetchone()
    return ReportRecord(report_id=report_id, analysis_id=analysis["id"], created_at=created_at,
                        **body)


def get_report(pool: ConnectionPool, report_id: UUID) -> ReportRecord | None:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT report_id, analysis_id, created_at, report FROM app.reports "
            "WHERE report_id = %s", [report_id]).fetchone()
    if row is None:
        return None
    report_id, analysis_id, created_at, body = row
    return ReportRecord(report_id=report_id, analysis_id=analysis_id, created_at=created_at,
                        **body)


def _json_dumps(obj) -> str:
    return json.dumps(obj, default=str)  # dates -> "2024-12-31"
