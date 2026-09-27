-- Audit log and name-token hashes for the privacy-safe report pipeline (M6).
-- Run as carelens_loader (owner).

-- One row per report request, including blocked ones. Append-only for the app: it may
-- INSERT but not read, change or delete rows, so the log can't be rewritten through the app.
CREATE TABLE IF NOT EXISTS app.audit_log (
    audit_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at            timestamptz NOT NULL DEFAULT now(),
    report_id             uuid REFERENCES app.reports,   -- NULL when the request was blocked
    analysis_id           text NOT NULL,
    outcome               text NOT NULL CHECK (outcome IN ('llm', 'fallback', 'blocked')),
    fallback_reason       text,          -- why the LLM result wasn't used (NULL for 'llm')
    model                 text,          -- NULL when no LLM was called
    payload_sha256        char(64) NOT NULL,   -- hash of exactly what was (or would be) sent
    redactions_outbound   jsonb NOT NULL DEFAULT '{}',  -- counts by type, e.g. {"date": 2}
    redactions_response   jsonb NOT NULL DEFAULT '{}',
    grounding_passed      boolean,
    findings_dropped      integer NOT NULL DEFAULT 0,
    attempts              integer NOT NULL DEFAULT 0,  -- LLM calls made (max 2)
    prompt_tokens         integer NOT NULL DEFAULT 0,
    completion_tokens     integer NOT NULL DEFAULT 0,
    total_tokens          integer NOT NULL DEFAULT 0,
    CHECK ((outcome = 'blocked') = (report_id IS NULL))
);
GRANT INSERT ON app.audit_log TO app_readonly;

-- HMAC-SHA256 of each patient name token, keyed with NAME_HASH_SALT (a secret kept outside
-- the database). Built by scripts/build_name_hashes.py from phi, which the app cannot read.
-- The redactor hashes each word it sees and masks matches, so the app never needs raw names.
CREATE TABLE IF NOT EXISTS app.name_token_hashes (
    token_hash char(64) PRIMARY KEY
);
GRANT SELECT ON app.name_token_hashes TO app_readonly;
