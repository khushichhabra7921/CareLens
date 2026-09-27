-- Move staged CSV rows (all text, in temp tables stg_*) into the typed tables.
-- Run by scripts/load_data.py inside ONE transaction, after the targets were truncated.
--
-- Same pattern for every table:
--   1. chk_<table>: each staged row plus a reject_reason (NULL = row is valid). The CASE
--      stops at the first problem, so later branches can safely cast earlier-checked values.
--   2. rejected rows -> loader.rejected_rows (loader-only; may contain PHI).
--   3. valid rows    -> the target table.
-- pg_input_is_valid(text, type) (Postgres 16+) tests a cast without raising an error.
-- Parents load before children, so foreign keys are checked against rows already loaded.

-- ---------------------------------------------------------------- reference date
-- The latest encounter start date. Ages are computed at this date, never CURRENT_DATE.
DELETE FROM analytics.dataset_info;
INSERT INTO analytics.dataset_info (reference_date, source)
SELECT max(start::timestamptz)::date, current_setting('carelens.source')
FROM stg_encounters
WHERE pg_input_is_valid(start, 'timestamptz');

-- ---------------------------------------------------------------- patients
CREATE TEMP TABLE chk_patients ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.id, 'uuid')              THEN 'invalid patient id'
        WHEN count(*) OVER (PARTITION BY s.id) > 1            THEN 'duplicate patient id'
        WHEN NOT pg_input_is_valid(s.birthdate, 'date')       THEN 'invalid birth date'
        WHEN s.deathdate <> '' AND NOT pg_input_is_valid(s.deathdate, 'date')
                                                              THEN 'invalid death date'
        WHEN NULLIF(s.deathdate, '')::date < s.birthdate::date
                                                              THEN 'death before birth'
        WHEN s.gender NOT IN ('M', 'F')                       THEN 'unknown gender'
        WHEN s.ethnicity NOT IN ('hispanic', 'nonhispanic')   THEN 'unknown ethnicity'
        WHEN s.first = '' OR s.last = ''                      THEN 'missing name'
        WHEN s.ssn !~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$'          THEN 'invalid SSN format'
        WHEN s.race = '' OR s.state = '' OR s.address = '' OR s.city = '' OR s.birthplace = ''
                                                              THEN 'missing required field'
    END AS reject_reason
FROM stg_patients s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'patients', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_patients c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.patients
    (patient_id, age_band, gender, race, ethnicity, state, county, zip3, is_deceased, death_date)
SELECT
    c.id::uuid,
    CASE
        WHEN a.age < 18 THEN '0-17'
        WHEN a.age < 45 THEN '18-44'
        WHEN a.age < 65 THEN '45-64'
        WHEN a.age < 75 THEN '65-74'
        WHEN a.age < 90 THEN '75-89'
        ELSE '90+'
    END,
    c.gender, c.race, c.ethnicity, c.state, NULLIF(c.county, ''),
    CASE
        WHEN c.zip !~ '^[0-9]{5}' OR c.zip = '00000' THEN NULL   -- 00000 = Synthea "unknown"
        -- 3-digit ZIP areas with 20,000 or fewer people (HHS de-identification guidance,
        -- based on the 2000 Census) must be reported as 000.
        WHEN left(c.zip, 3) IN ('036', '059', '063', '102', '203', '556', '692', '790', '821',
                                '823', '830', '831', '878', '879', '884', '890', '893')
            THEN '000'
        ELSE left(c.zip, 3)
    END,
    c.deathdate <> '',
    NULLIF(c.deathdate, '')::date
FROM chk_patients c
CROSS JOIN analytics.dataset_info d
-- Age at the reference date, or at death for deceased patients.
CROSS JOIN LATERAL (
    SELECT extract(year FROM age(
        LEAST(COALESCE(NULLIF(c.deathdate, '')::date, d.reference_date), d.reference_date),
        c.birthdate::date))::int AS age
) a
WHERE c.reject_reason IS NULL;

INSERT INTO phi.patient_identifiers
    (patient_id, prefix, first_name, middle_name, last_name, suffix, maiden_name, ssn,
     drivers, passport, birth_date, birthplace, address, city, county_fips, zip, lat, lon)
SELECT
    c.id::uuid, NULLIF(c.prefix, ''), c.first, NULLIF(c.middle, ''), c.last,
    NULLIF(c.suffix, ''), NULLIF(c.maiden, ''), c.ssn, NULLIF(c.drivers, ''),
    NULLIF(c.passport, ''), c.birthdate::date, c.birthplace, c.address, c.city,
    NULLIF(c.fips, ''), NULLIF(c.zip, ''),
    CASE WHEN pg_input_is_valid(c.lat, 'float8') THEN c.lat::float8 END,
    CASE WHEN pg_input_is_valid(c.lon, 'float8') THEN c.lon::float8 END
FROM chk_patients c
WHERE c.reject_reason IS NULL;

-- ---------------------------------------------------------------- organizations
CREATE TEMP TABLE chk_organizations ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.id, 'uuid')    THEN 'invalid organization id'
        WHEN count(*) OVER (PARTITION BY s.id) > 1  THEN 'duplicate organization id'
        WHEN s.name = '' OR s.city = ''             THEN 'missing required field'
    END AS reject_reason
FROM stg_organizations s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'organizations', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_organizations c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.organizations (organization_id, name, city, state)
SELECT id::uuid, name, city, NULLIF(state, '')
FROM chk_organizations WHERE reject_reason IS NULL;

-- ---------------------------------------------------------------- providers
CREATE TEMP TABLE chk_providers ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.id, 'uuid')    THEN 'invalid provider id'
        WHEN count(*) OVER (PARTITION BY s.id) > 1  THEN 'duplicate provider id'
        WHEN NOT pg_input_is_valid(s.organization, 'uuid')    THEN 'invalid organization id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.organizations o
                         WHERE o.organization_id = s.organization::uuid)
                                                    THEN 'unknown organization'
        WHEN s.gender NOT IN ('M', 'F')             THEN 'unknown gender'
        WHEN s.speciality = ''                      THEN 'missing required field'
    END AS reject_reason
FROM stg_providers s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'providers', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_providers c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.providers (provider_id, organization_id, gender, speciality)
SELECT id::uuid, organization::uuid, gender, speciality
FROM chk_providers WHERE reject_reason IS NULL;

-- ---------------------------------------------------------------- payers
CREATE TEMP TABLE chk_payers ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.id, 'uuid')    THEN 'invalid payer id'
        WHEN count(*) OVER (PARTITION BY s.id) > 1  THEN 'duplicate payer id'
        WHEN s.name = ''                            THEN 'missing required field'
        WHEN s.ownership NOT IN ('GOVERNMENT', 'PRIVATE', 'NO_INSURANCE')
                                                    THEN 'unknown ownership'
    END AS reject_reason
FROM stg_payers s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'payers', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_payers c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.payers (payer_id, name, ownership)
SELECT id::uuid, name, ownership
FROM chk_payers WHERE reject_reason IS NULL;

-- ---------------------------------------------------------------- encounters
CREATE TEMP TABLE chk_encounters ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.id, 'uuid')    THEN 'invalid encounter id'
        WHEN count(*) OVER (PARTITION BY s.id) > 1  THEN 'duplicate encounter id'
        WHEN NOT pg_input_is_valid(s.patient, 'uuid')         THEN 'invalid patient id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.patients p WHERE p.patient_id = s.patient::uuid)
                                                    THEN 'unknown patient'
        WHEN NOT pg_input_is_valid(s.organization, 'uuid')    THEN 'invalid organization id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.organizations o
                         WHERE o.organization_id = s.organization::uuid)
                                                    THEN 'unknown organization'
        WHEN NOT pg_input_is_valid(s.provider, 'uuid')        THEN 'invalid provider id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.providers v WHERE v.provider_id = s.provider::uuid)
                                                    THEN 'unknown provider'
        WHEN NOT pg_input_is_valid(s.payer, 'uuid')           THEN 'invalid payer id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.payers y WHERE y.payer_id = s.payer::uuid)
                                                    THEN 'unknown payer'
        WHEN NOT pg_input_is_valid(s.start, 'timestamptz')
          OR (s.stop <> '' AND NOT pg_input_is_valid(s.stop, 'timestamptz'))
                                                    THEN 'invalid timestamp'
        WHEN NULLIF(s.stop, '')::timestamptz < s.start::timestamptz
                                                    THEN 'stop before start'
        WHEN s.encounterclass NOT IN ('ambulatory', 'emergency', 'home', 'hospice', 'inpatient',
                                      'outpatient', 'snf', 'urgentcare', 'virtual', 'wellness')
                                                    THEN 'unknown encounter class'
        WHEN s.code = '' OR s.description = ''      THEN 'missing required field'
        WHEN NOT pg_input_is_valid(s.base_encounter_cost, 'numeric(12,2)')
          OR NOT pg_input_is_valid(s.total_claim_cost, 'numeric(12,2)')
          OR NOT pg_input_is_valid(s.payer_coverage, 'numeric(12,2)')
                                                    THEN 'invalid cost'
        WHEN s.base_encounter_cost::numeric < 0 OR s.total_claim_cost::numeric < 0
          OR s.payer_coverage::numeric < 0          THEN 'negative cost'
        WHEN s.payer_coverage::numeric > s.total_claim_cost::numeric
                                                    THEN 'coverage exceeds cost'
    END AS reject_reason
FROM stg_encounters s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'encounters', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_encounters c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.encounters
    (encounter_id, patient_id, organization_id, provider_id, payer_id, start_ts, stop_ts,
     encounter_class, code, description, base_cost, total_claim_cost, payer_coverage,
     reason_code, reason_description)
SELECT id::uuid, patient::uuid, organization::uuid, provider::uuid, payer::uuid,
    start::timestamptz, NULLIF(stop, '')::timestamptz, encounterclass, code, description,
    base_encounter_cost::numeric, total_claim_cost::numeric, payer_coverage::numeric,
    NULLIF(reasoncode, ''), NULLIF(reasondescription, '')
FROM chk_encounters WHERE reject_reason IS NULL;

-- ---------------------------------------------------------------- conditions
CREATE TEMP TABLE chk_conditions ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.patient, 'uuid')         THEN 'invalid patient id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.patients p WHERE p.patient_id = s.patient::uuid)
                                                    THEN 'unknown patient'
        WHEN NOT pg_input_is_valid(s.encounter, 'uuid')       THEN 'invalid encounter id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.encounters e
                         WHERE e.encounter_id = s.encounter::uuid)
                                                    THEN 'unknown encounter'
        WHEN NOT pg_input_is_valid(s.start, 'date')
          OR (s.stop <> '' AND NOT pg_input_is_valid(s.stop, 'date'))
                                                    THEN 'invalid date'
        WHEN NULLIF(s.stop, '')::date < s.start::date
                                                    THEN 'stop before start'
        WHEN s.system NOT IN ('SNOMED-CT', 'ICD10') THEN 'unknown code system'
        WHEN s.code = '' OR s.description = ''      THEN 'missing required field'
    END AS reject_reason
FROM stg_conditions s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'conditions', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_conditions c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.conditions
    (patient_id, encounter_id, start_date, stop_date, code_system, code, description)
SELECT patient::uuid, encounter::uuid, start::date, NULLIF(stop, '')::date, system, code,
    description
FROM chk_conditions WHERE reject_reason IS NULL;

-- ---------------------------------------------------------------- medications
CREATE TEMP TABLE chk_medications ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.patient, 'uuid')         THEN 'invalid patient id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.patients p WHERE p.patient_id = s.patient::uuid)
                                                    THEN 'unknown patient'
        WHEN NOT pg_input_is_valid(s.encounter, 'uuid')       THEN 'invalid encounter id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.encounters e
                         WHERE e.encounter_id = s.encounter::uuid)
                                                    THEN 'unknown encounter'
        WHEN NOT pg_input_is_valid(s.payer, 'uuid')           THEN 'invalid payer id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.payers y WHERE y.payer_id = s.payer::uuid)
                                                    THEN 'unknown payer'
        WHEN NOT pg_input_is_valid(s.start, 'timestamptz')
          OR (s.stop <> '' AND NOT pg_input_is_valid(s.stop, 'timestamptz'))
                                                    THEN 'invalid timestamp'
        WHEN s.code = '' OR s.description = ''      THEN 'missing required field'
        WHEN NOT pg_input_is_valid(s.base_cost, 'numeric(12,2)')
          OR NOT pg_input_is_valid(s.payer_coverage, 'numeric(12,2)')
          OR NOT pg_input_is_valid(s.totalcost, 'numeric(14,2)')
                                                    THEN 'invalid cost'
        WHEN NOT pg_input_is_valid(s.dispenses, 'integer')
                                                    THEN 'invalid dispenses'
        WHEN s.base_cost::numeric < 0 OR s.payer_coverage::numeric < 0
          OR s.totalcost::numeric < 0 OR s.dispenses::int < 0
                                                    THEN 'negative value'
        WHEN s.payer_coverage::numeric > s.totalcost::numeric
                                                    THEN 'coverage exceeds cost'
    END AS reject_reason
FROM stg_medications s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'medications', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_medications c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.medications
    (patient_id, encounter_id, payer_id, start_ts, stop_ts, code, description, base_cost,
     payer_coverage, dispenses, total_cost, reason_code, reason_description)
SELECT patient::uuid, encounter::uuid, payer::uuid, start::timestamptz,
    NULLIF(stop, '')::timestamptz, code, description, base_cost::numeric,
    payer_coverage::numeric, dispenses::int, totalcost::numeric, NULLIF(reasoncode, ''),
    NULLIF(reasondescription, '')
FROM chk_medications WHERE reject_reason IS NULL;

-- ---------------------------------------------------------------- observations
CREATE TEMP TABLE chk_observations ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.patient, 'uuid')         THEN 'invalid patient id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.patients p WHERE p.patient_id = s.patient::uuid)
                                                    THEN 'unknown patient'
        -- An empty encounter is allowed (Synthea writes QALY/DALY rows without one).
        WHEN s.encounter <> '' AND NOT pg_input_is_valid(s.encounter, 'uuid')
                                                    THEN 'invalid encounter id'
        WHEN NULLIF(s.encounter, '') IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM analytics.encounters e
                WHERE e.encounter_id = NULLIF(s.encounter, '')::uuid)
                                                    THEN 'unknown encounter'
        WHEN NOT pg_input_is_valid(s.date, 'timestamptz')
                                                    THEN 'invalid timestamp'
        WHEN s.type NOT IN ('numeric', 'text')      THEN 'unknown value type'
        WHEN s.type = 'numeric' AND NOT pg_input_is_valid(s.value, 'numeric')
                                                    THEN 'numeric value not a number'
        WHEN s.code = '' OR s.description = ''      THEN 'missing required field'
    END AS reject_reason
FROM stg_observations s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'observations', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_observations c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.observations
    (patient_id, encounter_id, observed_at, category, code, description, value, value_numeric,
     units, value_type)
SELECT patient::uuid, NULLIF(encounter, '')::uuid, date::timestamptz, NULLIF(category, ''),
    code, description, value,
    CASE WHEN type = 'numeric' THEN value::numeric END,
    NULLIF(units, ''), type
FROM chk_observations WHERE reject_reason IS NULL;

-- ---------------------------------------------------------------- procedures
CREATE TEMP TABLE chk_procedures ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.patient, 'uuid')         THEN 'invalid patient id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.patients p WHERE p.patient_id = s.patient::uuid)
                                                    THEN 'unknown patient'
        WHEN NOT pg_input_is_valid(s.encounter, 'uuid')       THEN 'invalid encounter id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.encounters e
                         WHERE e.encounter_id = s.encounter::uuid)
                                                    THEN 'unknown encounter'
        WHEN NOT pg_input_is_valid(s.start, 'timestamptz')
          OR (s.stop <> '' AND NOT pg_input_is_valid(s.stop, 'timestamptz'))
                                                    THEN 'invalid timestamp'
        WHEN NULLIF(s.stop, '')::timestamptz < s.start::timestamptz
                                                    THEN 'stop before start'
        WHEN s.system NOT IN ('SNOMED-CT', 'CDT')   THEN 'unknown code system'
        WHEN s.code = '' OR s.description = ''      THEN 'missing required field'
        WHEN NOT pg_input_is_valid(s.base_cost, 'numeric(12,2)')
                                                    THEN 'invalid cost'
        WHEN s.base_cost::numeric < 0               THEN 'negative cost'
    END AS reject_reason
FROM stg_procedures s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'procedures', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_procedures c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.procedures
    (patient_id, encounter_id, start_ts, stop_ts, code_system, code, description, base_cost,
     reason_code, reason_description)
SELECT patient::uuid, encounter::uuid, start::timestamptz, NULLIF(stop, '')::timestamptz,
    system, code, description, base_cost::numeric, NULLIF(reasoncode, ''),
    NULLIF(reasondescription, '')
FROM chk_procedures WHERE reject_reason IS NULL;

-- ---------------------------------------------------------------- immunizations
CREATE TEMP TABLE chk_immunizations ON COMMIT DROP AS
SELECT s.*,
    CASE
        WHEN NOT pg_input_is_valid(s.patient, 'uuid')         THEN 'invalid patient id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.patients p WHERE p.patient_id = s.patient::uuid)
                                                    THEN 'unknown patient'
        WHEN NOT pg_input_is_valid(s.encounter, 'uuid')       THEN 'invalid encounter id'
        WHEN NOT EXISTS (SELECT 1 FROM analytics.encounters e
                         WHERE e.encounter_id = s.encounter::uuid)
                                                    THEN 'unknown encounter'
        WHEN NOT pg_input_is_valid(s.date, 'timestamptz')
                                                    THEN 'invalid timestamp'
        WHEN s.code = '' OR s.description = ''      THEN 'missing required field'
        WHEN NOT pg_input_is_valid(s.base_cost, 'numeric(12,2)')
                                                    THEN 'invalid cost'
        WHEN s.base_cost::numeric < 0               THEN 'negative cost'
    END AS reject_reason
FROM stg_immunizations s;

INSERT INTO loader.rejected_rows (table_name, reason, row_data)
SELECT 'immunizations', reject_reason, to_jsonb(c) - 'reject_reason'
FROM chk_immunizations c WHERE reject_reason IS NOT NULL;

INSERT INTO analytics.immunizations
    (patient_id, encounter_id, administered_at, code, description, base_cost)
SELECT patient::uuid, encounter::uuid, date::timestamptz, code, description,
    base_cost::numeric
FROM chk_immunizations WHERE reject_reason IS NULL;
