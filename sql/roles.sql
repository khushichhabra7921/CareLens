-- Roles and database-level privileges. Run by the admin/superuser (scripts/db_setup.py).
-- Safe to re-run. Passwords are NOT here: db_setup.py sets them from environment variables.
--
--   carelens_loader : owns all schemas and tables, loads data. Never used by the web app.
--   app_readonly    : the web app. Reads analytics only; no access to phi. (Grants are in
--                     sql/schema/005_grants.sql, run by the owner.)

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'carelens_loader') THEN
        CREATE ROLE carelens_loader LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_readonly') THEN
        CREATE ROLE app_readonly LOGIN;
    END IF;
END
$$;

-- By default every role can connect to every database (via PUBLIC). Turn that off,
-- then allow only our two roles. The loader creates the schemas, so it also needs CREATE
-- on the database; the app does not. (format(%I) quotes the database name safely.)
DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO carelens_loader, app_readonly',
                   current_database());
    EXECUTE format('GRANT CREATE ON DATABASE %I TO carelens_loader', current_database());
    -- REVOKE ALL above also removed TEMPORARY. The loader stages CSVs in temp tables.
    EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO carelens_loader', current_database());
    -- Synthea timestamps are UTC. Pin the database to UTC so "::date" and date windows
    -- give the same answer on every machine (otherwise it depends on the server's zone).
    EXECUTE format('ALTER DATABASE %I SET timezone = %L', current_database(), 'UTC');
END
$$;

-- Belt and braces: nobody may create objects in the public schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- A read-only app role should never hold a long transaction open or run away with the CPU.
ALTER ROLE app_readonly SET statement_timeout = '15s';
ALTER ROLE app_readonly SET idle_in_transaction_session_timeout = '30s';
