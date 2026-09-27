"""Grounding check: every number the model states must exist in the data it was given.

For each finding we collect (a) its values_cited and (b) every number written in the
statement. Each must match a number from the payload, allowing for rounding to the precision
written ("16.63" may be written "16.6" or "17"), thousands separators ("4,274"), percent signs
and scale words ("$4.3 million"). Findings that fail, or that reference a table/column that
doesn't exist, are dropped. If more than half are dropped, grounding has failed "badly".
"""

import re
from dataclasses import dataclass

from app.report_schema import InsightReport

# 1,234.5 | 1234.5 | 16 ; optional % ; optional scale word. No minus sign: our data has no
# negative numbers, and "65-74" must read as 65 and 74, not 65 and -74.
NUMBER = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(%|percent|million|billion|thousand)?",
                    re.IGNORECASE)
SCALE = {"million": 1e6, "billion": 1e9, "thousand": 1e3}


@dataclass
class Mention:
    value: float      # after applying any scale word
    tolerance: float  # half a unit in the last written digit, e.g. 0.05 for "16.6"


def mentions_in(text: str) -> list[Mention]:
    found = []
    for whole, frac, suffix in NUMBER.findall(text):
        digits = whole.replace(",", "") + (frac or "")
        decimals = len(frac) - 1 if frac else 0
        scale = SCALE.get((suffix or "").lower(), 1.0)
        found.append(Mention(float(digits) * scale, 0.5 * 10 ** -decimals * scale))
    return found


def _cited(value: float) -> Mention:
    text = repr(float(value))
    decimals = len(text.split(".")[1]) if "." in text and not text.endswith(".0") else 0
    return Mention(float(value), 0.5 * 10 ** -decimals)


def allowed_numbers(payload: dict) -> list[float]:
    """Numbers in the rows, plus numbers written in the payload's text (e.g. '12 months',
    '65-74', '30-day', the year), which a statement may repeat."""
    values = []
    for table in payload["tables"]:
        for row in table["rows"]:
            values += [float(v) for v in row
                       if isinstance(v, int | float) and not isinstance(v, bool)]
            values += [m.value for v in row if isinstance(v, str) for m in mentions_in(v)]
        values += [m.value for m in mentions_in(table["title"])]
    for key in ("title", "question", "limitations", "notes", "data_through"):
        if isinstance(payload.get(key), str):
            values += [m.value for m in mentions_in(payload[key])]
    return values


def _matches(mention: Mention, values: list[float]) -> bool:
    return any(abs(v - mention.value) <= mention.tolerance + 1e-9 for v in values)


def valid_refs(payload: dict) -> set[str]:
    return {f"{t['name']}.{c}" for t in payload["tables"] for c in t["columns"]}


@dataclass
class GroundingResult:
    report: InsightReport       # with ungrounded findings removed
    status: str                 # passed | partial | failed
    dropped: int
    reasons: list[str]


def check(report: InsightReport, payload: dict) -> GroundingResult:
    values = allowed_numbers(payload)
    refs = valid_refs(payload)
    kept, reasons = [], []
    for finding in report.findings:
        mentions = [_cited(v) for v in finding.values_cited] + mentions_in(finding.statement)
        bad_numbers = [m.value for m in mentions if not _matches(m, values)]
        bad_refs = [r for r in finding.metric_refs if r not in refs]
        if not mentions:
            reasons.append(f"no number cited: {finding.statement[:60]!r}")
        elif bad_numbers:
            reasons.append(f"number(s) not in the data {bad_numbers}: {finding.statement[:60]!r}")
        elif bad_refs:
            reasons.append(f"unknown metric_refs {bad_refs}")
        else:
            kept.append(finding)
    dropped = len(report.findings) - len(kept)
    if not kept or dropped * 2 > len(report.findings):
        status = "failed"
    elif dropped:
        status = "partial"
    else:
        status = "passed"
    return GroundingResult(report.model_copy(update={"findings": kept}), status, dropped, reasons)
