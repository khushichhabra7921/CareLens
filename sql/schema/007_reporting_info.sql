-- The one piece of load metadata the web app may read: which reference date the analyses
-- use. A plain (not materialized) view, so it is always current. The view runs with its
-- owner's privileges, so app_readonly can read it without any access to analytics.
CREATE OR REPLACE VIEW reporting.dataset_info AS
SELECT reference_date, loaded_at FROM analytics.dataset_info;

GRANT SELECT ON reporting.dataset_info TO app_readonly;
