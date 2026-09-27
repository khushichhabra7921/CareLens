-- Title: Frequent emergency department users
-- Question: In the last 12 months, what share of ED users were "frequent users" (4 or more
--   ED visits), and what share of all ED visits did they account for?
-- Method: Count each patient's 'emergency' encounters in the 12 months ending on the reference
--   date. ED users = patients with at least 1 visit; frequent users = 4 or more.
-- Assumptions: The 4-visit threshold is a common definition in ED-utilization research; there
--   is no single standard. Every ED encounter counts as a visit.
-- Limitations: Synthea's ED visits come from its disease models, not real care-seeking
--   behaviour, so the frequent-user share is illustrative only. Counts 1-10 are suppressed.
WITH ref AS (
    SELECT reference_date AS r FROM analytics.dataset_info
),
per_patient AS (
    SELECT e.patient_id, count(*) AS visits
    FROM analytics.encounters e CROSS JOIN ref
    WHERE e.encounter_class = 'emergency'
      AND e.start_ts::date > (ref.r - interval '12 months')::date
      AND e.start_ts::date <= ref.r
    GROUP BY 1
),
totals AS (
    SELECT count(*) AS ed_users,
           count(*) FILTER (WHERE visits >= 4) AS frequent_users,
           -- sum() returns numeric; the suppression helpers take bigint.
           COALESCE(sum(visits), 0)::bigint AS ed_visits,
           COALESCE(sum(visits) FILTER (WHERE visits >= 4), 0)::bigint AS frequent_user_visits
    FROM per_patient
)
SELECT 1 AS sort_order,
       analytics.suppress(ed_users) AS ed_users,
       analytics.suppress(frequent_users) AS frequent_users,
       analytics.safe_pct(frequent_users, ed_users) AS frequent_user_pct,
       analytics.suppress(ed_visits) AS ed_visits,
       analytics.suppress(frequent_user_visits) AS frequent_user_visits,
       analytics.safe_pct(frequent_user_visits, ed_visits) AS frequent_user_visit_pct,
       analytics.is_small(ed_users) OR analytics.is_small(frequent_users)
           OR analytics.is_small(ed_visits) OR analytics.is_small(frequent_user_visits)
           AS suppressed
FROM totals
