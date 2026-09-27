-- Pseudonymized analytics tables. Column choices are based on the real Synthea v4.0.0 CSVs
-- (see docs/DECISIONS.md, Milestone 2 and 3). Every CHECK below was verified against the full
-- generated dataset before being added, so it rejects bad data without rejecting real rows.

-- One row per load: the reference date every analysis uses instead of CURRENT_DATE.
CREATE TABLE IF NOT EXISTS analytics.dataset_info (
    id              smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),   -- exactly one row
    reference_date  date        NOT NULL,   -- latest encounter start date in the data
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    source          text        NOT NULL    -- e.g. the CSV directory name
);

CREATE TABLE IF NOT EXISTS analytics.patients (
    patient_id   uuid PRIMARY KEY,
    -- Age at the reference date (or at death). 90+ is one band, as HIPAA Safe Harbor requires.
    age_band     text NOT NULL CHECK (age_band IN
                     ('0-17', '18-44', '45-64', '65-74', '75-89', '90+')),
    gender       text NOT NULL CHECK (gender IN ('M', 'F')),
    race         text NOT NULL,
    ethnicity    text NOT NULL CHECK (ethnicity IN ('hispanic', 'nonhispanic')),
    state        text NOT NULL,
    county       text,
    -- First 3 ZIP digits; NULL when unknown (Synthea writes 00000) and '000' for the
    -- 3-digit areas HHS lists as having 20,000 or fewer people.
    zip3         char(3) CHECK (zip3 ~ '^[0-9]{3}$'),
    is_deceased  boolean NOT NULL,
    death_date   date,
    CHECK (is_deceased = (death_date IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS analytics.organizations (
    organization_id  uuid PRIMARY KEY,
    name             text NOT NULL,
    city             text NOT NULL,
    state            text
);

CREATE TABLE IF NOT EXISTS analytics.providers (
    provider_id      uuid PRIMARY KEY,
    organization_id  uuid NOT NULL REFERENCES analytics.organizations,
    gender           text NOT NULL CHECK (gender IN ('M', 'F')),
    speciality       text NOT NULL
    -- Provider names and addresses are not loaded: no analysis needs them (data minimization).
);

CREATE TABLE IF NOT EXISTS analytics.payers (
    payer_id   uuid PRIMARY KEY,
    name       text NOT NULL,
    ownership  text NOT NULL CHECK (ownership IN ('GOVERNMENT', 'PRIVATE', 'NO_INSURANCE'))
    -- Synthea's payer summary totals are not loaded: they differ between identical runs.
);

CREATE TABLE IF NOT EXISTS analytics.encounters (
    encounter_id        uuid PRIMARY KEY,
    patient_id          uuid NOT NULL REFERENCES analytics.patients,
    organization_id     uuid NOT NULL REFERENCES analytics.organizations,
    provider_id         uuid NOT NULL REFERENCES analytics.providers,
    payer_id            uuid NOT NULL REFERENCES analytics.payers,
    start_ts            timestamptz NOT NULL,
    stop_ts             timestamptz,
    encounter_class     text NOT NULL CHECK (encounter_class IN
                            ('ambulatory', 'emergency', 'home', 'hospice', 'inpatient',
                             'outpatient', 'snf', 'urgentcare', 'virtual', 'wellness')),
    code                text NOT NULL,       -- SNOMED-CT
    description         text NOT NULL,
    base_cost           numeric(12, 2) NOT NULL CHECK (base_cost >= 0),
    total_claim_cost    numeric(12, 2) NOT NULL CHECK (total_claim_cost >= 0),
    payer_coverage      numeric(12, 2) NOT NULL CHECK (payer_coverage >= 0),
    reason_code         text,
    reason_description  text,
    CHECK (stop_ts IS NULL OR stop_ts >= start_ts),
    CHECK (payer_coverage <= total_claim_cost)
);

-- The clinical event tables have no natural key in Synthea, so they get a generated one.

CREATE TABLE IF NOT EXISTS analytics.conditions (
    condition_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_id    uuid NOT NULL REFERENCES analytics.patients,
    encounter_id  uuid NOT NULL REFERENCES analytics.encounters,
    start_date    date NOT NULL,
    stop_date     date,
    code_system   text NOT NULL CHECK (code_system IN ('SNOMED-CT', 'ICD10')),
    code          text NOT NULL,
    description   text NOT NULL,
    CHECK (stop_date IS NULL OR stop_date >= start_date)
);

CREATE TABLE IF NOT EXISTS analytics.medications (
    medication_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_id          uuid NOT NULL REFERENCES analytics.patients,
    encounter_id        uuid NOT NULL REFERENCES analytics.encounters,
    payer_id            uuid NOT NULL REFERENCES analytics.payers,
    start_ts            timestamptz NOT NULL,
    stop_ts             timestamptz,  -- NULL = still active. No stop >= start check: 57 real
                                      -- Synthea rows stop a few days before they start.
    code                text NOT NULL,    -- RxNorm
    description         text NOT NULL,
    base_cost           numeric(12, 2) NOT NULL CHECK (base_cost >= 0),
    payer_coverage      numeric(12, 2) NOT NULL CHECK (payer_coverage >= 0),
    dispenses           integer NOT NULL CHECK (dispenses >= 0),
    total_cost          numeric(14, 2) NOT NULL CHECK (total_cost >= 0),
    reason_code         text,
    reason_description  text,
    CHECK (payer_coverage <= total_cost)
);

CREATE TABLE IF NOT EXISTS analytics.observations (
    observation_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_id      uuid NOT NULL REFERENCES analytics.patients,
    encounter_id    uuid REFERENCES analytics.encounters,  -- NULL for QALY/DALY-style rows
    observed_at     timestamptz NOT NULL,
    category        text,
    code            text NOT NULL,          -- LOINC (plus a few Synthea codes such as QALY)
    description     text NOT NULL,
    value           text NOT NULL,          -- as recorded
    value_numeric   numeric,                -- filled when value_type = 'numeric'
    units           text,
    value_type      text NOT NULL CHECK (value_type IN ('numeric', 'text')),
    CHECK (value_type = 'text' OR value_numeric IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS analytics.procedures (
    procedure_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_id          uuid NOT NULL REFERENCES analytics.patients,
    encounter_id        uuid NOT NULL REFERENCES analytics.encounters,
    start_ts            timestamptz NOT NULL,
    stop_ts             timestamptz,
    code_system         text NOT NULL CHECK (code_system IN ('SNOMED-CT', 'CDT')),
    code                text NOT NULL,
    description         text NOT NULL,
    base_cost           numeric(12, 2) NOT NULL CHECK (base_cost >= 0),
    reason_code         text,
    reason_description  text,
    CHECK (stop_ts IS NULL OR stop_ts >= start_ts)
);

CREATE TABLE IF NOT EXISTS analytics.immunizations (
    immunization_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_id       uuid NOT NULL REFERENCES analytics.patients,
    encounter_id     uuid NOT NULL REFERENCES analytics.encounters,
    administered_at  timestamptz NOT NULL,
    code             text NOT NULL,     -- CVX
    description      text NOT NULL,
    base_cost        numeric(12, 2) NOT NULL CHECK (base_cost >= 0)
);
