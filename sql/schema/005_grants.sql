-- What app_readonly (the web app) may do. Run as the owner, carelens_loader. Safe to re-run.
-- Summary: read the aggregate views in `reporting`; nothing at all in phi, analytics or loader.
-- So even a bug or SQL injection in the web app cannot return row-level patient data: the
-- database refuses. (App-table grants come in M6.)

GRANT USAGE ON SCHEMA reporting TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO app_readonly;
-- Views the loader (re)creates LATER in reporting are readable too.
ALTER DEFAULT PRIVILEGES FOR ROLE carelens_loader IN SCHEMA reporting
    GRANT SELECT ON TABLES TO app_readonly;

GRANT USAGE ON SCHEMA app TO app_readonly;

-- Explicitly none on the row-level schemas. REVOKE is a no-op if nothing was granted, but it
-- documents the intent and undoes earlier grants (Milestone 3 let the app read analytics).
ALTER DEFAULT PRIVILEGES FOR ROLE carelens_loader IN SCHEMA analytics
    REVOKE SELECT ON TABLES FROM app_readonly;
REVOKE ALL ON ALL TABLES IN SCHEMA analytics FROM app_readonly;
REVOKE ALL ON SCHEMA analytics FROM app_readonly;
REVOKE ALL ON ALL TABLES IN SCHEMA phi FROM app_readonly;
REVOKE ALL ON SCHEMA phi FROM app_readonly;
REVOKE ALL ON ALL TABLES IN SCHEMA loader FROM app_readonly;
REVOKE ALL ON SCHEMA loader FROM app_readonly;
