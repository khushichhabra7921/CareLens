-- Title: Flu vaccination in older adults
-- Question: What share of living patients aged 65+ had a seasonal flu vaccine in the last
--   12 months?
-- Method: Eligible = living patients in the 65-74, 75-89 and 90+ bands. Vaccinated = at least
--   one immunization with a seasonal influenza CVX code (analytics.vaccine_groups, from CDC's
--   CVX table) dated in the 12 months ending on the reference date. Shown per age band and
--   for all 65+.
-- Assumptions: A 12-month look-back rather than a flu season (e.g. Aug-Mar), so the window
--   is the same as the other analyses.
-- Limitations: Only vaccines recorded in this dataset count (no pharmacy or registry data).
--   The 65+ total row is suppressed when hidden age-band cells add up to 1-10.
WITH ref AS (
    SELECT reference_date AS r FROM analytics.dataset_info
),
older AS (
    SELECT patient_id, age_band FROM analytics.patients
    WHERE NOT is_deceased AND age_band IN ('65-74', '75-89', '90+')
),
vaccinated AS (
    SELECT DISTINCT i.patient_id
    FROM analytics.immunizations i
    JOIN analytics.vaccine_groups v
      ON v.cvx_code = i.code AND v.group_name = 'influenza_seasonal'
    CROSS JOIN ref
    WHERE i.administered_at::date > (ref.r - interval '12 months')::date
      AND i.administered_at::date <= ref.r
),
bands (age_band) AS (VALUES ('65-74'), ('75-89'), ('90+')),
cells AS (
    SELECT b.age_band,
           count(o.patient_id) AS eligible,
           count(v.patient_id) AS vacc
    FROM bands b
    LEFT JOIN older o USING (age_band)
    LEFT JOIN vaccinated v USING (patient_id)
    GROUP BY 1
),
total AS (
    SELECT '65+ (all)' AS age_band, sum(eligible)::bigint AS eligible, sum(vacc)::bigint AS vacc,
           analytics.total_reveals_small(
               (sum(eligible) FILTER (WHERE analytics.is_small(eligible)))::bigint)
               AS hide_eligible,
           analytics.total_reveals_small(
               (sum(vacc) FILTER (WHERE analytics.is_small(vacc)))::bigint)
               AS hide_vacc
    FROM cells
)
SELECT 1 AS sort_order, age_band,
       CASE WHEN hide_eligible THEN NULL ELSE analytics.suppress(eligible) END
           AS eligible_patients,
       CASE WHEN hide_vacc THEN NULL ELSE analytics.suppress(vacc) END
           AS vaccinated_patients,
       CASE WHEN hide_eligible OR hide_vacc THEN NULL
            ELSE analytics.safe_pct(vacc, eligible) END AS vaccination_pct,
       hide_eligible OR hide_vacc OR analytics.is_small(eligible)
           OR analytics.is_small(vacc) AS suppressed
FROM total
UNION ALL
SELECT row_number() OVER (ORDER BY age_band) + 1, age_band,
       analytics.suppress(eligible),
       analytics.suppress(vacc),
       analytics.safe_pct(vacc, eligible),
       analytics.is_small(eligible) OR analytics.is_small(vacc)
FROM cells
