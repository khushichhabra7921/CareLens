-- Title: Care gaps (HEDIS-inspired, simplified)
-- Question: How many living patients with diabetes had no HbA1c result, and how many with
--   hypertension had no blood pressure reading, in the 12 months before the reference date?
-- Method: Eligible = living patients with an active condition from the group on the reference
--   date. Gap = no qualifying observation dated in the 12 months ending on the reference date.
--   HbA1c = LOINC 4548-4. Blood pressure = LOINC 8480-6 (systolic) or 8462-4 (diastolic).
--   All three codes were found in the data.
-- Assumptions: Any recorded result counts (no check of the value or of how well controlled
--   the patient is). No continuous-enrolment requirement.
-- Limitations: Real HEDIS measures (e.g. Glycemic Status Assessment, Controlling High Blood
--   Pressure) have age limits, enrolment rules, exclusions and value thresholds that are not
--   applied here, so these are not HEDIS rates. Counts 1-10 are suppressed.
WITH ref AS (
    SELECT reference_date AS r FROM analytics.dataset_info
),
measures (measure, condition_group, loinc_codes) AS (
    VALUES ('Diabetes without HbA1c test', 'diabetes', ARRAY['4548-4']),
           ('Hypertension without blood pressure reading', 'hypertension',
            ARRAY['8480-6', '8462-4'])
),
eligible AS (
    SELECT DISTINCT m.measure, m.loinc_codes, c.patient_id
    FROM measures m
    JOIN analytics.condition_groups g ON g.group_name = m.condition_group
    JOIN analytics.conditions c ON c.code = g.code AND c.code_system = 'SNOMED-CT'
    JOIN analytics.patients p ON p.patient_id = c.patient_id AND NOT p.is_deceased
    CROSS JOIN ref
    WHERE c.start_date <= ref.r
      AND (c.stop_date IS NULL OR c.stop_date > ref.r)
),
flagged AS (
    SELECT e.measure,
           NOT EXISTS (
               SELECT 1 FROM analytics.observations o CROSS JOIN ref
               WHERE o.patient_id = e.patient_id
                 AND o.code = ANY (e.loinc_codes)
                 AND o.observed_at::date > (ref.r - interval '12 months')::date
                 AND o.observed_at::date <= ref.r
           ) AS has_gap
    FROM eligible e
),
cells AS (
    SELECT m.measure,
           count(f.measure) AS eligible_patients,
           count(*) FILTER (WHERE f.has_gap) AS patients_with_gap
    FROM measures m LEFT JOIN flagged f USING (measure)
    GROUP BY 1
)
SELECT row_number() OVER (ORDER BY measure) AS sort_order,
       measure,
       analytics.suppress(eligible_patients) AS eligible_patients,
       analytics.suppress(patients_with_gap) AS patients_with_gap,
       analytics.safe_pct(patients_with_gap, eligible_patients) AS gap_pct,
       analytics.is_small(eligible_patients) OR analytics.is_small(patients_with_gap)
           AS suppressed
FROM cells
