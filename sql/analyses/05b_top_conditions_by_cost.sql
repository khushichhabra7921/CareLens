-- Title: Top 10 conditions by total encounter cost
-- Question: Which conditions drove the most encounter cost in the last 12 months?
-- Method: Group encounters from the 12 months ending on the reference date by their reason
--   (the condition the visit was for), sum total_claim_cost, and rank. Only reasons that are
--   real diagnoses (the code appears in the conditions table) are ranked: encounter reasons
--   also include procedures and situations, e.g. "Screening for malignant neoplasm of colon".
--   Only conditions seen in at least 11 distinct patients are ranked.
-- Assumptions: An encounter's cost belongs entirely to its recorded reason. Encounters with
--   no reason (routine visits, check-ups) are left out.
-- Limitations: Leaves out medication and procedure costs that are billed separately, and the
--   cost of encounters without a reason code. Conditions with 1-10 patients are left out of
--   the ranking completely rather than shown as suppressed rows: a suppressed row would still
--   reveal, by its rank, roughly how much those few patients cost.
WITH ref AS (
    SELECT reference_date AS r FROM analytics.dataset_info
),
by_reason AS (
    SELECT e.reason_code,
           e.reason_description AS condition,
           count(*) AS encounters,
           count(DISTINCT e.patient_id) AS patients,
           sum(e.total_claim_cost) AS total_cost,
           sum(e.total_claim_cost - e.payer_coverage) AS out_of_pocket
    FROM analytics.encounters e CROSS JOIN ref
    WHERE e.reason_code IN (SELECT code FROM analytics.conditions)
      AND e.start_ts::date > (ref.r - interval '12 months')::date
      AND e.start_ts::date <= ref.r
    GROUP BY 1, 2
),
ranked AS (
    SELECT *, row_number() OVER (ORDER BY total_cost DESC, condition) AS cost_rank
    FROM by_reason
    WHERE patients >= 11
)
SELECT cost_rank AS sort_order,
       cost_rank,
       reason_code,
       condition,
       encounters,
       patients,
       total_cost AS total_claim_cost,
       out_of_pocket AS patient_out_of_pocket,
       false AS suppressed   -- conditions with 1-10 patients are excluded above
FROM ranked
WHERE cost_rank <= 10
