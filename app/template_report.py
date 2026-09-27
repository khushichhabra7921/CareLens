"""A report built from the aggregates with plain rules, no AI.

Used when no LLM is configured, and (in M6) as the fallback when the LLM fails. Every
number it cites is copied straight from the analysis results, so it can't hallucinate.
"""

from datetime import date
from decimal import Decimal

from app.report_schema import Finding, InsightReport

LABEL_TYPES = (str, date)


def _is_number(value) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def _metric_column(columns: list[str], rows: list[dict]) -> str | None:
    """Pick the column a reader cares most about: a rate if there is one, else a count."""
    numeric = [c for c in columns if c != "suppressed"
               and any(_is_number(r[c]) for r in rows)]
    for suffix in ("_pct", "_per_1000"):
        rates = [c for c in numeric if c.endswith(suffix)]
        if rates:
            return rates[0]
    counts = [c for c in numeric if c not in ("period", "cost_rank")]
    return counts[-1] if counts else None


def _label(row: dict, columns: list[str]) -> str:
    parts = [str(row[c]) for c in columns if isinstance(row[c], LABEL_TYPES)]
    return ", ".join(parts) or "all"


def _nice(column: str) -> str:
    return column.replace("_pct", " (%)").replace("_per_1000", " per 1,000").replace("_", " ")


def table_findings(table: dict) -> list[Finding]:
    columns, rows, name = table["columns"], table["rows"], table["name"]
    metric = _metric_column(columns, rows)
    findings = []
    shown = [r for r in rows if metric and _is_number(r[metric])]
    if shown:
        top = max(shown, key=lambda r: r[metric])
        low = min(shown, key=lambda r: r[metric])
        findings.append(Finding(
            statement=f"{table['title']}: the highest {_nice(metric)} is {top[metric]} "
                      f"({_label(top, columns)}).",
            metric_refs=[f"{name}.{metric}"], values_cited=[float(top[metric])]))
        if low is not top and low[metric] != top[metric]:
            findings.append(Finding(
                statement=f"{table['title']}: the lowest {_nice(metric)} is {low[metric]} "
                          f"({_label(low, columns)}).",
                metric_refs=[f"{name}.{metric}"], values_cited=[float(low[metric])]))
    hidden = table["suppressed_rows"]
    if hidden:
        findings.append(Finding(
            statement=f"{table['title']}: {hidden} of {len(rows)} rows are suppressed because "
                      "they involve 1-10 patients or events.",
            metric_refs=[f"{name}.suppressed"], values_cited=[float(hidden), float(len(rows))]))
    return findings


def build_template_report(analysis: dict) -> InsightReport:
    findings = [f for t in analysis["tables"] for f in table_findings(t)][:12]
    return InsightReport(
        title=f"{analysis['title']}: automated summary",
        summary=(f"{analysis['question']} This summary lists the highest and lowest values in "
                 f"each result table, using data up to {analysis['reference_date']}."),
        findings=findings,
        recommended_actions=[
            "Review these figures with a clinical or quality-improvement team before acting.",
            "Treat suppressed cells as unknown, not as zero.",
        ],
        limitations=[analysis["limitations"],
                     "Generated from fixed rules, not by an AI model."],
    )
