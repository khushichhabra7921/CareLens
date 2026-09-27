-- Title: 30-day all-cause readmission rate
-- Question: How often are patients admitted to hospital again within 30 days of going home,
--   overall, by payer and by the primary reason for the first stay?
-- Method: Take every inpatient encounter and, with LEAD() over each patient's inpatient stays
--   ordered by admission time, find that patient's NEXT admission. An index stay counts as
--   readmitted when the next admission starts after its discharge and no more than 30 days
--   later. LEAD runs over ALL stays before filtering, so a readmission is found even if it
--   falls outside the reporting window. Index stays = discharges from 5 years before the
--   reference date to 30 days before it (so every stay has a full 30-day follow-up).
-- Assumptions: All-cause (any reason) readmission; one "next admission" per stay. Stays where
--   the patient died on or before the discharge date are excluded (no chance to return).
--   Primary reason = the index encounter's reason code; "No reason recorded" when empty.
-- Limitations: Simplified versus CMS's Hospital-Wide Readmission measure: no exclusion of
--   planned readmissions, no risk adjustment, no age limit. A next stay that starts BEFORE
--   the previous discharge (an overlap; 53 in the full data, likely a transfer) is not counted
--   as a readmission. The overall row is suppressed when the hidden payer or reason cells
--   beneath it add up to 1-10 (otherwise they could be recovered by subtraction).
WITH ref AS (
    SELECT reference_date AS r FROM analytics.dataset_info
),
stays AS (
    SELECT e.encounter_id, e.patient_id, e.payer_id, e.stop_ts,
           COALESCE(e.reason_description, 'No reason recorded') AS reason,
           LEAD(e.start_ts) OVER (PARTITION BY e.patient_id
                                  ORDER BY e.start_ts, e.encounter_id) AS next_admission
    FROM analytics.encounters e
    WHERE e.encounter_class = 'inpatient'
),
index_stays AS (
    SELECT s.*,
           COALESCE(s.next_admission > s.stop_ts
                    AND s.next_admission <= s.stop_ts + interval '30 days', false) AS readmitted
    FROM stays s
    JOIN analytics.patients p USING (patient_id)
    CROSS JOIN ref
    WHERE s.stop_ts::date BETWEEN (ref.r - interval '5 years')::date AND ref.r - 30
      AND (p.death_date IS NULL OR p.death_date > s.stop_ts::date)
),
cells AS (
    SELECT 'payer' AS dimension, y.name AS category,
           count(*) AS stays, count(*) FILTER (WHERE readmitted) AS readmits
    FROM index_stays i JOIN analytics.payers y USING (payer_id)
    GROUP BY 2
    UNION ALL
    SELECT 'primary_reason', reason, count(*), count(*) FILTER (WHERE readmitted)
    FROM index_stays
    GROUP BY 2
),
overall AS (
    SELECT count(*) AS stays, count(*) FILTER (WHERE readmitted) AS readmits
    FROM index_stays
),
-- For each breakdown: how much is hidden beneath the overall row?
hidden AS (
    SELECT dimension,
           (sum(stays) FILTER (WHERE analytics.is_small(stays)))::bigint AS hidden_stays,
           (sum(readmits) FILTER (WHERE analytics.is_small(readmits)))::bigint AS hidden_readmits
    FROM cells GROUP BY dimension
),
overall_row AS (
    SELECT 'overall' AS dimension, 'All inpatient stays' AS category, o.stays, o.readmits,
           COALESCE(bool_or(analytics.total_reveals_small(h.hidden_stays)), false) AS hide_stays,
           COALESCE(bool_or(analytics.total_reveals_small(h.hidden_readmits)), false)
               AS hide_readmits
    FROM overall o LEFT JOIN hidden h ON true
    GROUP BY o.stays, o.readmits
),
result AS (
    SELECT dimension, category,
           CASE WHEN hide_stays THEN NULL ELSE analytics.suppress(stays) END AS index_stays,
           CASE WHEN hide_readmits THEN NULL ELSE analytics.suppress(readmits) END AS readmissions,
           CASE WHEN hide_stays OR hide_readmits THEN NULL
                ELSE analytics.safe_pct(readmits, stays) END AS readmission_rate_pct,
           hide_stays OR hide_readmits OR analytics.is_small(stays)
               OR analytics.is_small(readmits) AS suppressed,
           stays AS true_stays   -- used only for ordering below, never output
    FROM overall_row
    UNION ALL
    SELECT dimension, category,
           analytics.suppress(stays),
           analytics.suppress(readmits),
           analytics.safe_pct(readmits, stays),
           analytics.is_small(stays) OR analytics.is_small(readmits),
           stays
    FROM cells
)
-- sort_order: overall first, then each breakdown by size. (Materialized views don't keep row
-- order, so readers ORDER BY this column.)
SELECT row_number() OVER (ORDER BY dimension = 'overall' DESC, dimension, true_stays DESC,
                                   category) AS sort_order,
       dimension, category, index_stays, readmissions, readmission_rate_pct, suppressed
FROM result
