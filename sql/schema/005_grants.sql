-- What app_readonly (the web app) may do. Run as the owner, carelens_loader. Safe to re-run.
-- Summary: read analytics; nothing at all in phi or loader. (App-table grants come in M6.)

GRANT USAGE ON SCHEMA analytics TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO app_readonly;
-- Tables and materialized views the loader creates LATER in analytics are readable too.
ALTER DEFAULT PRIVILEGES FOR ROLE carelens_loader IN SCHEMA analytics
    GRANT SELECT ON TABLES TO app_readonly;

GRANT USAGE ON SCHEMA app TO app_readonly;

-- Explicitly none on phi and loader. REVOKE is a no-op if nothing was granted, but it
-- documents the intent and undoes any accidental earlier grant.
REVOKE ALL ON ALL TABLES IN SCHEMA phi FROM app_readonly;
REVOKE ALL ON SCHEMA phi FROM app_readonly;
REVOKE ALL ON ALL TABLES IN SCHEMA loader FROM app_readonly;
REVOKE ALL ON SCHEMA loader FROM app_readonly;
