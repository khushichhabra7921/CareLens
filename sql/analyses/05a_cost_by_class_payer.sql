-- Title: Cost and coverage by encounter class and payer
-- Question: In the last 12 months, how much did encounters cost, how much did payers cover,
--   and how much was left for patients, by encounter class and payer?
-- Method: Sum total_claim_cost and payer_coverage over encounters starting in the 12 months
--   ending on the reference date, grouped by encounter class and payer.
--   Patient out-of-pocket = total claim cost - payer coverage.
-- Assumptions: Costs are Synthea's simulated US-dollar amounts at encounter level (they
--   include the encounter's line items). All money is rounded to cents.
-- Limitations: "Out-of-pocket" is approximated as the amount the encounter's payer did not
--   cover; Synthea does not model secondary insurance paying part of it. Medication costs are
--   billed separately (medications table) and are not included here. When a cell has 1-10
--   encounters, its money columns are hidden too, because a cost from very few encounters
--   is close to an individual patient's bill.
WITH ref AS (
    SELECT reference_date AS r FROM analytics.dataset_info
),
cells AS (
    SELECT e.encounter_class,
           y.name AS payer,
           y.ownership AS payer_type,
           count(*) AS encounters,
           sum(e.total_claim_cost) AS total_cost,
           sum(e.payer_coverage) AS payer_paid
    FROM analytics.encounters e
    JOIN analytics.payers y USING (payer_id)
    CROSS JOIN ref
    WHERE e.start_ts::date > (ref.r - interval '12 months')::date
      AND e.start_ts::date <= ref.r
    GROUP BY 1, 2, 3
)
SELECT row_number() OVER (ORDER BY total_cost DESC, encounter_class, payer) AS sort_order,
       encounter_class,
       payer,
       payer_type,
       analytics.suppress(encounters) AS encounters,
       CASE WHEN analytics.is_small(encounters) THEN NULL ELSE total_cost END AS total_claim_cost,
       CASE WHEN analytics.is_small(encounters) THEN NULL ELSE payer_paid END AS payer_coverage,
       CASE WHEN analytics.is_small(encounters) THEN NULL ELSE total_cost - payer_paid END
           AS patient_out_of_pocket,
       CASE WHEN analytics.is_small(encounters) OR total_cost = 0 THEN NULL
            ELSE round(100.0 * payer_paid / total_cost, 1) END AS coverage_pct,
       analytics.is_small(encounters) AS suppressed
FROM cells
