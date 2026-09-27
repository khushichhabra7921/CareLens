-- Title: Chronic disease prevalence
-- Question: What share of living patients currently has diabetes, hypertension, COPD, asthma,
--   chronic kidney disease or heart failure, by age band and gender?
-- Method: Numerator = living patients with an ACTIVE condition from the group on the reference
--   date (diagnosed on or before it, and not resolved before it). Denominator = all living
--   patients in the same age band and gender. Code groups: analytics.condition_groups.
-- Assumptions: A condition without a stop date is still active. Diabetes includes patients who
--   only have a "due to diabetes" complication code (their diagnosis predates the data).
-- Limitations: Synthea exports 10 years of history, so conditions resolved long ago or
--   diagnosed and never re-coded may be missing. Prevalence reflects Synthea's disease models,
--   not measured real-world rates. Counts and percentages built on 1-10 patients are suppressed.
WITH ref AS (
    SELECT reference_date AS r FROM analytics.dataset_info
),
living AS (
    SELECT patient_id, age_band, gender FROM analytics.patients WHERE NOT is_deceased
),
active AS (   -- one row per (patient, condition group) with an active condition
    SELECT DISTINCT c.patient_id, g.group_name
    FROM analytics.conditions c
    JOIN analytics.condition_groups g ON g.code = c.code AND c.code_system = 'SNOMED-CT'
    CROSS JOIN ref
    WHERE c.start_date <= ref.r
      AND (c.stop_date IS NULL OR c.stop_date > ref.r)
),
groups AS (SELECT DISTINCT group_name FROM analytics.condition_groups),
cells AS (
    SELECT g.group_name AS condition,
           l.age_band,
           l.gender,
           count(*) AS living_patients,
           count(a.patient_id) AS with_condition
    FROM groups g
    CROSS JOIN living l
    LEFT JOIN active a ON a.patient_id = l.patient_id AND a.group_name = g.group_name
    GROUP BY 1, 2, 3
)
SELECT row_number() OVER (ORDER BY condition, age_band, gender) AS sort_order,
       condition,
       age_band,
       gender,
       analytics.suppress(with_condition) AS patients_with_condition,
       analytics.suppress(living_patients) AS living_patients,
       analytics.safe_pct(with_condition, living_patients) AS prevalence_pct,
       analytics.is_small(with_condition) OR analytics.is_small(living_patients) AS suppressed
FROM cells
