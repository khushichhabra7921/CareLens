-- Benchmark query for the index comparison in docs/ANALYSES.md (not one of the 8 analyses).
-- "How many hypertensive patients have no systolic blood pressure reading in the 12 months
--  before the reference date?" It probes the 870k-row observations table once per patient.
-- Codes from the data: essential hypertension SNOMED 59621000, systolic BP LOINC 8480-6.
WITH ref AS (
    SELECT reference_date FROM analytics.dataset_info
),
hypertensive AS (
    SELECT DISTINCT patient_id FROM analytics.conditions WHERE code = '59621000'
)
SELECT
    count(*) AS hypertensive_patients,
    count(*) FILTER (WHERE NOT EXISTS (
        SELECT 1
        FROM analytics.observations o, ref
        WHERE o.code = '8480-6'
          AND o.patient_id = h.patient_id
          AND o.observed_at >= ref.reference_date - interval '12 months'
          AND o.observed_at <  ref.reference_date + interval '1 day'
    )) AS without_bp_reading
FROM hypertensive h;
