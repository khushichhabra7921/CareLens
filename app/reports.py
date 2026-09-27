"""The privacy-safe report pipeline, plus storage and the audit log.

aggregates -> minimise (allowlist) -> redact + fail closed -> prompt -> LLM (JSON mode)
           -> validate (Pydantic) -> redact response -> injection check -> grounding
           -> store report + audit row

If the LLM isn't configured, times out, returns invalid JSON, looks injected or fails grounding
badly, it is retried at most once, and then the rule-based template report is used instead.
If a direct identifier is found in the outbound payload, the request is BLOCKED: nothing is sent
and no report is created.
"""

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import ValidationError

from app.llm import grounding
from app.llm.client import LLMError, LLMTimeout
from app.llm.prompt import build_messages, find_injection
from app.privacy import minimize
from app.privacy.redactor import Redactor, direct_identifiers
from app.report_schema import Grounding, InsightReport, ReportRecord
from app.template_report import build_template_report

log = logging.getLogger("carelens.reports")
MAX_ATTEMPTS = 2   # the first call plus at most one retry


class BlockedError(Exception):
    """A direct identifier was found in data about to leave the system."""


@dataclass
class Outcome:
    report: InsightReport
    source: str                      # "llm" or "template"
    grounding: grounding.GroundingResult
    fallback_reason: str | None = None
    attempts: int = 0
    redactions_response: Counter = field(default_factory=Counter)
    tokens: Counter = field(default_factory=Counter)


def _json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _try_llm(client, payload: dict, redactor: Redactor):
    """Call the LLM, retrying at most once.
    Returns (outcome, None, attempts, tokens) on success, or (None, reason, attempts, tokens)
    when every attempt failed; `reason` says why the last one failed."""
    allowed = minimize.numbers_in(payload)
    tokens, reason, attempts = Counter(), None, 0
    for _ in range(MAX_ATTEMPTS):
        attempts += 1
        try:
            result = client.complete(build_messages(payload))
        except LLMTimeout:
            reason = "timeout"
            continue
        except LLMError as err:
            reason = f"llm_error: {err}"
            continue
        tokens.update(prompt=result.prompt_tokens, completion=result.completion_tokens,
                      total=result.total_tokens)
        try:
            report = InsightReport.model_validate(json.loads(result.content))
        except (json.JSONDecodeError, ValidationError):
            reason = "invalid_json_or_schema"
            continue
        # Defence in depth on the way back in: mask anything identifying the model wrote.
        cleaned, found = redactor.redact_strings(report.model_dump(), allowed)
        second_pass, leftover = redactor.redact_strings(cleaned, allowed)
        if direct_identifiers(leftover):   # the redactor must leave nothing behind
            reason = "identifier_left_after_redaction"
            continue
        report = InsightReport.model_validate(second_pass)
        if find_injection(report.model_dump()):
            reason = "suspected_prompt_injection_in_response"
            continue
        checked = grounding.check(report, payload)
        if checked.status == "failed":
            reason = "grounding_failed"
            log.info("grounding failed: %s", checked.reasons)
            continue
        outcome = Outcome(checked.report, "llm", checked, attempts=attempts,
                          redactions_response=found, tokens=tokens)
        return outcome, None, attempts, tokens
    return None, reason, attempts, tokens


def generate(analysis: dict, redactor: Redactor, client) -> tuple[Outcome, dict, Counter, str]:
    """Run the pipeline. Returns (outcome, payload sent, outbound redaction counts, sha256)."""
    payload = minimize.build_payload(analysis)
    payload, outbound = redactor.redact_strings(payload, minimize.numbers_in(payload))
    payload_hash = hashlib.sha256(_json(payload).encode()).hexdigest()
    if direct_identifiers(outbound):
        # Fail closed: identifiers in the aggregates mean something upstream is wrong.
        raise BlockedError(payload_hash, outbound)

    outcome, attempts, tokens = None, 0, Counter()
    if client is None:
        reason = "llm_not_configured"
    elif find_injection(payload):
        reason = "suspected_prompt_injection_in_data"   # don't send it to the model at all
    else:
        outcome, reason, attempts, tokens = _try_llm(client, payload, redactor)
    if outcome is None:
        template = build_template_report(payload)
        outcome = Outcome(template, "template", grounding.check(template, payload),
                          fallback_reason=reason, attempts=attempts, tokens=tokens)
    return outcome, payload, outbound, payload_hash


def _audit(conn, *, analysis_id, outcome, payload_hash, outbound, report_id=None,
           result: Outcome | None = None, model=None):
    conn.execute(
        "INSERT INTO app.audit_log (report_id, analysis_id, outcome, fallback_reason, model, "
        "payload_sha256, redactions_outbound, redactions_response, grounding_passed, "
        "findings_dropped, attempts, prompt_tokens, completion_tokens, total_tokens) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [report_id, analysis_id, outcome,
         result.fallback_reason if result else "direct_identifier_in_payload",
         model if result and result.attempts else None, payload_hash,
         Jsonb(dict(outbound)), Jsonb(dict(result.redactions_response) if result else {}),
         result.grounding.status == "passed" if result else None,
         result.grounding.dropped if result else 0,
         result.attempts if result else 0,
         result.tokens["prompt"] if result else 0, result.tokens["completion"] if result else 0,
         result.tokens["total"] if result else 0])


def create_report(pool: ConnectionPool, analysis: dict, redactor: Redactor, client,
                  model: str | None) -> ReportRecord:
    try:
        result, _payload, outbound, payload_hash = generate(analysis, redactor, client)
    except BlockedError as err:
        payload_hash, outbound = err.args
        with pool.connection() as conn:
            _audit(conn, analysis_id=analysis["id"], outcome="blocked",
                   payload_hash=payload_hash, outbound=outbound)
        log.warning("report blocked for %s: direct identifiers %s", analysis["id"],
                    direct_identifiers(outbound))
        raise

    redactions = Counter(outbound) + result.redactions_response
    body = {
        "reference_date": analysis["reference_date"],
        "source": result.source,
        "model": model if result.source == "llm" else None,
        "report": result.report.model_dump(),
        "redactions": dict(redactions),
        "grounding": Grounding(status=result.grounding.status,
                               dropped_findings=result.grounding.dropped).model_dump(),
    }
    with pool.connection() as conn, conn.transaction():   # report and audit row together
        report_id, created_at = conn.execute(
            "INSERT INTO app.reports (analysis_id, source, report) VALUES (%s, %s, %s) "
            "RETURNING report_id, created_at",
            [analysis["id"], result.source, Jsonb(body, dumps=_json)],
        ).fetchone()
        _audit(conn, analysis_id=analysis["id"],
               outcome="llm" if result.source == "llm" else "fallback",
               payload_hash=payload_hash, outbound=outbound, report_id=report_id,
               result=result, model=model)
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


def load_name_hashes(pool: ConnectionPool) -> set[str]:
    with pool.connection() as conn:
        return {h for (h,) in conn.execute("SELECT token_hash FROM app.name_token_hashes")}
