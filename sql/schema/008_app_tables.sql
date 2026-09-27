-- Tables the web app writes to. Run as carelens_loader (owner).
-- app_readonly may SELECT and INSERT here, and nothing else: no UPDATE or DELETE, so a stored
-- report can't be changed or removed through the app. (The audit log is added in M6.)

CREATE TABLE IF NOT EXISTS app.reports (
    report_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id  text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    source       text NOT NULL CHECK (source IN ('llm', 'template')),
    report       jsonb NOT NULL    -- the full report exactly as the API returns it
);

GRANT SELECT, INSERT ON app.reports TO app_readonly;
