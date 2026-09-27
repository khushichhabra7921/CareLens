-- Five schemas, split by how sensitive the data is. Run as carelens_loader (the owner).
--
--   phi       : direct identifiers only (names, SSN, address, exact birth date...). App: no access.
--   analytics : pseudonymized row-level clinical data (no names/SSNs/addresses/birth dates),
--               keyed by the same patient_id. Still has service dates and county, so it is NOT
--               Safe Harbor de-identified on its own. App: no access.
--   reporting : the 8 analyses as materialized views: aggregates only, small cells suppressed.
--               The ONLY clinical data the web app can read.
--   app       : what the web app writes (reports, audit log) and name-token hashes.
--   loader    : load bookkeeping, including rejected rows (which may contain PHI). App: no access.

CREATE SCHEMA IF NOT EXISTS phi;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS reporting;
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS loader;

-- Schemas are private by default, but make it explicit for the sensitive ones.
REVOKE ALL ON SCHEMA phi FROM PUBLIC;
REVOKE ALL ON SCHEMA analytics FROM PUBLIC;
REVOKE ALL ON SCHEMA loader FROM PUBLIC;
