"""Shapes of an insight report. InsightReport is also what the LLM must return in M6
(validated with Pydantic), so the template and the LLM produce the same structure."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

DISCLAIMER = "Synthetic data. Not clinical advice."


class Finding(BaseModel):
    statement: str = Field(min_length=1, max_length=500)
    metric_refs: list[str] = Field(default_factory=list, max_length=10)   # e.g. "care_gaps.gap_pct"
    values_cited: list[float] = Field(default_factory=list, max_length=10)


class InsightReport(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1500)
    findings: list[Finding] = Field(max_length=12)
    recommended_actions: list[str] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)


class Grounding(BaseModel):
    # not_checked: M5 template reports. M6 adds the check for LLM reports.
    status: Literal["passed", "partial", "failed", "not_checked"]
    dropped_findings: int = 0


class ReportRecord(BaseModel):
    """What the API returns and what is stored in app.reports."""
    report_id: UUID
    analysis_id: str
    created_at: datetime
    reference_date: date | None
    source: Literal["llm", "template"]
    model: str | None = None
    disclaimer: str = DISCLAIMER
    report: InsightReport
    redactions: dict[str, int] = Field(default_factory=dict)   # counts by type (M6)
    grounding: Grounding
