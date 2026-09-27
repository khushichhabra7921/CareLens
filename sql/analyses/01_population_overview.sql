-- Title: Population overview
-- Question: Who is in the dataset, by age band, gender, race, ethnicity and vital status?
-- Method: Count all patients (living and deceased) in each category of each dimension.
-- Assumptions: Age band = age at the reference date, or at death for deceased patients.
--   Race and ethnicity are Synthea's single primary values.
-- Limitations: Counts 1-10 are suppressed, but every dimension adds up to the same total, so
--   a dimension with exactly ONE suppressed cell can be worked out from another dimension's
--   total. Accepted for this project (simple suppression, see docs/DECISIONS.md M4);
--   complementary suppression would close it. Synthea's demographics follow Massachusetts
--   census data, not a real patient population.
WITH counts AS (
    SELECT 'age_band' AS dimension, age_band AS category, count(*) AS n FROM analytics.patients GROUP BY 2
    UNION ALL
    SELECT 'gender', gender, count(*) FROM analytics.patients GROUP BY 2
    UNION ALL
    SELECT 'race', race, count(*) FROM analytics.patients GROUP BY 2
    UNION ALL
    SELECT 'ethnicity', ethnicity, count(*) FROM analytics.patients GROUP BY 2
    UNION ALL
    SELECT 'vital_status', CASE WHEN is_deceased THEN 'deceased' ELSE 'living' END, count(*)
    FROM analytics.patients GROUP BY 2
)
-- sort_order: a materialized view does not keep row order, so readers ORDER BY this column.
SELECT row_number() OVER (ORDER BY dimension, n DESC, category) AS sort_order,
       dimension,
       category,
       analytics.suppress(n) AS patients,
       analytics.is_small(n) AS suppressed
FROM counts
