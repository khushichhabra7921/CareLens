-- Indexes on foreign keys and on the date/code columns the analyses filter by.
-- Postgres indexes primary keys automatically, but NOT foreign keys.
-- scripts/benchmark_indexes.py drops and recreates these to measure their effect,
-- so every index here must have a name and use IF NOT EXISTS.

CREATE INDEX IF NOT EXISTS ix_providers_organization ON analytics.providers (organization_id);

CREATE INDEX IF NOT EXISTS ix_encounters_patient      ON analytics.encounters (patient_id);
CREATE INDEX IF NOT EXISTS ix_encounters_organization ON analytics.encounters (organization_id);
CREATE INDEX IF NOT EXISTS ix_encounters_provider     ON analytics.encounters (provider_id);
CREATE INDEX IF NOT EXISTS ix_encounters_payer        ON analytics.encounters (payer_id);
-- Readmissions and ED visits filter by class, then order each patient's visits by date.
CREATE INDEX IF NOT EXISTS ix_encounters_class_patient_start
    ON analytics.encounters (encounter_class, patient_id, start_ts);

CREATE INDEX IF NOT EXISTS ix_conditions_patient   ON analytics.conditions (patient_id);
CREATE INDEX IF NOT EXISTS ix_conditions_encounter ON analytics.conditions (encounter_id);
CREATE INDEX IF NOT EXISTS ix_conditions_code      ON analytics.conditions (code);

CREATE INDEX IF NOT EXISTS ix_medications_patient   ON analytics.medications (patient_id);
CREATE INDEX IF NOT EXISTS ix_medications_encounter ON analytics.medications (encounter_id);
CREATE INDEX IF NOT EXISTS ix_medications_payer     ON analytics.medications (payer_id);
CREATE INDEX IF NOT EXISTS ix_medications_start     ON analytics.medications (start_ts);

CREATE INDEX IF NOT EXISTS ix_observations_patient   ON analytics.observations (patient_id);
CREATE INDEX IF NOT EXISTS ix_observations_encounter ON analytics.observations (encounter_id);
-- Care-gap lookups: "this LOINC code, for this patient, in this date window".
CREATE INDEX IF NOT EXISTS ix_observations_code_patient_date
    ON analytics.observations (code, patient_id, observed_at);

CREATE INDEX IF NOT EXISTS ix_procedures_patient   ON analytics.procedures (patient_id);
CREATE INDEX IF NOT EXISTS ix_procedures_encounter ON analytics.procedures (encounter_id);

CREATE INDEX IF NOT EXISTS ix_immunizations_patient   ON analytics.immunizations (patient_id);
CREATE INDEX IF NOT EXISTS ix_immunizations_encounter ON analytics.immunizations (encounter_id);
CREATE INDEX IF NOT EXISTS ix_immunizations_code_date
    ON analytics.immunizations (code, administered_at);
