-- Direct identifiers, kept apart from the clinical data. The web app has no access here.
CREATE TABLE IF NOT EXISTS phi.patient_identifiers (
    patient_id   uuid PRIMARY KEY REFERENCES analytics.patients ON DELETE CASCADE,
    prefix       text,
    first_name   text NOT NULL,
    middle_name  text,
    last_name    text NOT NULL,
    suffix       text,
    maiden_name  text,
    ssn          text NOT NULL CHECK (ssn ~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$'),
    drivers      text,
    passport     text,
    birth_date   date NOT NULL,
    birthplace   text NOT NULL,
    address      text NOT NULL,
    city         text NOT NULL,
    county_fips  text,
    zip          text,
    lat          double precision,
    lon          double precision
    -- Not loaded anywhere (not needed for any analysis): marital status, income,
    -- lifetime healthcare expenses/coverage.
);

-- Rows the loader refused, with the reason. Loader-only: a rejected patient row holds PHI.
CREATE TABLE IF NOT EXISTS loader.rejected_rows (
    rejected_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name   text NOT NULL,
    reason       text NOT NULL,
    row_data     jsonb NOT NULL,
    rejected_at  timestamptz NOT NULL DEFAULT now()
);
