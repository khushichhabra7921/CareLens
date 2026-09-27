"""A report built from the minimised payload with plain rules, no AI.

Used when no LLM is configured and as the fallback whenever the LLM path fails. It reads the
same allowlisted, aggregate-only payload the LLM would get, and every number it cites is copied
straight from that payload, so it passes the grounding check by construction.
"""

from app.report_schema import Finding, InsightReport


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _metric_column(columns: list[str], rows: list[list]) -> str | None:
    """Pick the column a reader cares most about: a rate if there is one, else a count."""
    numeric = [c for i, c in enumerate(columns)
               if c != "suppressed" and any(_is_number(r[i]) for r in rows)]
    for suffix in ("_pct", "_per_1000"):
        rates = [c for c in numeric if c.endswith(suffix)]
        if rates:
            return rates[0]
    counts = [c for c in numeric if c not in ("period", "cost_rank")]
    return counts[-1] if counts else None


def _label(row: list, columns: list[str]) -> str:
    parts = [str(v) for c, v in zip(columns, row, strict=True)
             if isinstance(v, str) and c != "suppressed"]
    return ", ".join(parts) or "all"


def _nice(column: str) -> str:
    return column.replace("_pct", " (%)").replace("_per_1000", " per 1,000").replace("_", " ")


def table_findings(table: dict) -> list[Finding]:
    columns, rows, name = table["columns"], table["rows"], table["name"]
    metric = _metric_column(columns, rows)
    findings = []
    if metric:
        i = columns.index(metric)
        shown = [r for r in rows if _is_number(r[i])]
        top = max(shown, key=lambda r: r[i])
        low = min(shown, key=lambda r: r[i])
        findings.append(Finding(
            statement=f"{table['title']}: the highest {_nice(metric)} is {top[i]} "
                      f"({_label(top, columns)}).",
            metric_refs=[f"{name}.{metric}"], values_cited=[float(top[i])]))
        if low[i] != top[i]:
            findings.append(Finding(
                statement=f"{table['title']}: the lowest {_nice(metric)} is {low[i]} "
                          f"({_label(low, columns)}).",
                metric_refs=[f"{name}.{metric}"], values_cited=[float(low[i])]))
    if "suppressed" in columns:
        s = columns.index("suppressed")
        hidden = sum(1 for r in rows if r[s])
        if hidden:
            findings.append(Finding(
                statement=f"{table['title']}: some rows are suppressed because they involve "
                          "1-10 patients or events; treat them as unknown.",
                metric_refs=[f"{name}.suppressed"], values_cited=[10.0]))
    return findings


def build_template_report(payload: dict) -> InsightReport:
    findings = [f for t in payload["tables"] for f in table_findings(t)][:12]
    return InsightReport(
        title=f"{payload['title']}: automated summary",
        summary=(f"{payload['question']} This summary lists the highest and lowest values in "
                 f"each result table, using data up to {payload['data_through']}."),
        findings=findings,
        recommended_actions=[
            "Review these figures with a clinical or quality-improvement team before acting.",
            "Treat suppressed cells as unknown, not as zero.",
        ],
        limitations=[payload["limitations"],
                     "Generated from fixed rules, not by an AI model."],
    )
