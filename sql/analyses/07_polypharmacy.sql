-- Title: Polypharmacy in older adults
-- Question: What share of living patients aged 65+ take 5 or more different medications at
--   the same time?
-- Method: A medication is active on the reference date when it started on or before that
--   date and has no stop date or stops after it. Count DISTINCT RxNorm codes per patient
--   (the data has the same code under different spellings, e.g. "Simvastatin" and
--   "simvastatin"). Polypharmacy = 5 or more. Shown per age band and for all 65+.
-- Assumptions: "Concurrently active" is measured on a single day, the reference date.
--   5+ is the most common polypharmacy threshold in the literature.
-- Limitations: 57 medication rows stop before they start; they can never be active on the
--   reference date, so they are left out automatically. Synthea's prescribing follows
--   clinical guidelines, not real adherence or over-the-counter use. The 65+ total row is
--   suppressed when the hidden age-band cells add up to 1-10 (they could be subtracted out).
WITH ref AS (
    SELECT reference_date AS r FROM analytics.dataset_info
),
older AS (
    SELECT patient_id, age_band FROM analytics.patients
    WHERE NOT is_deceased AND age_band IN ('65-74', '75-89', '90+')
),
active_counts AS (
    SELECT m.patient_id, count(DISTINCT m.code) AS active_meds
    FROM analytics.medications m CROSS JOIN ref
    WHERE m.start_ts::date <= ref.r
      AND (m.stop_ts IS NULL OR m.stop_ts::date > ref.r)
    GROUP BY 1
),
bands (age_band) AS (VALUES ('65-74'), ('75-89'), ('90+')),
cells AS (
    SELECT b.age_band,
           count(o.patient_id) AS eligible,
           count(*) FILTER (WHERE a.active_meds >= 5) AS poly
    FROM bands b
    LEFT JOIN older o USING (age_band)
    LEFT JOIN active_counts a USING (patient_id)
    GROUP BY 1
),
total AS (
    SELECT '65+ (all)' AS age_band, sum(eligible)::bigint AS eligible, sum(poly)::bigint AS poly,
           analytics.total_reveals_small(
               (sum(eligible) FILTER (WHERE analytics.is_small(eligible)))::bigint)
               AS hide_eligible,
           analytics.total_reveals_small(
               (sum(poly) FILTER (WHERE analytics.is_small(poly)))::bigint)
               AS hide_poly
    FROM cells
)
SELECT 1 AS sort_order, age_band,
       CASE WHEN hide_eligible THEN NULL ELSE analytics.suppress(eligible) END
           AS eligible_patients,
       CASE WHEN hide_poly THEN NULL ELSE analytics.suppress(poly) END
           AS patients_with_polypharmacy,
       CASE WHEN hide_eligible OR hide_poly THEN NULL
            ELSE analytics.safe_pct(poly, eligible) END AS polypharmacy_pct,
       hide_eligible OR hide_poly OR analytics.is_small(eligible)
           OR analytics.is_small(poly) AS suppressed
FROM total
UNION ALL
SELECT row_number() OVER (ORDER BY age_band) + 1, age_band,
       analytics.suppress(eligible),
       analytics.suppress(poly),
       analytics.safe_pct(poly, eligible),
       analytics.is_small(eligible) OR analytics.is_small(poly)
FROM cells
