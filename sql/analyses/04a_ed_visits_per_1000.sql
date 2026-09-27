-- Title: Emergency department visits per 1,000 patients
-- Question: How many emergency department (ED) visits happen per 1,000 patients each year?
-- Method: Five consecutive 12-month periods ending on the reference date (period 1 is the
--   most recent year). Visits = encounters of class 'emergency' starting in the period.
--   Denominator = "active patients": distinct patients with ANY encounter in the period.
--   Rate = visits / active patients x 1,000.
-- Assumptions: 12-month periods rather than calendar years, so the latest period is always a
--   full year whatever the reference date. A period covers dates after its start and up to and
--   including its end.
-- Limitations: Active patients approximate the population at risk; the data has no birth date
--   or enrolment outside phi, so people with no visit in a year are not in that year's
--   denominator (this overstates the rate slightly). Counts 1-10 are suppressed and rates built
--   on them are hidden.
WITH ref AS (
    SELECT reference_date AS r FROM analytics.dataset_info
),
periods AS (
    SELECT k + 1 AS period,
           (ref.r - make_interval(years => k + 1))::date AS period_start,  -- exclusive
           (ref.r - make_interval(years => k))::date AS period_end          -- inclusive
    FROM ref, generate_series(0, 4) AS k
),
cells AS (
    SELECT p.period, p.period_start, p.period_end,
           count(e.encounter_id) FILTER (WHERE e.encounter_class = 'emergency') AS ed_visits,
           count(DISTINCT e.patient_id) AS active_patients
    FROM periods p
    LEFT JOIN analytics.encounters e
           ON e.start_ts::date > p.period_start AND e.start_ts::date <= p.period_end
    GROUP BY 1, 2, 3
)
SELECT row_number() OVER (ORDER BY period) AS sort_order,
       period,
       period_start,
       period_end,
       analytics.suppress(ed_visits) AS ed_visits,
       analytics.suppress(active_patients) AS active_patients,
       CASE WHEN analytics.is_small(ed_visits) OR analytics.is_small(active_patients)
                 OR active_patients = 0 THEN NULL
            ELSE round(1000.0 * ed_visits / active_patients, 1)
       END AS visits_per_1000,
       analytics.is_small(ed_visits) OR analytics.is_small(active_patients) AS suppressed
FROM cells
