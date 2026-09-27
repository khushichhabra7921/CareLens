-- Clinical code sets and small-cell helper functions used by sql/analyses/*.sql.
-- Every code below was found in the generated Synthea data or in an official list (sources
-- noted). Safe to re-run: the code tables are emptied and refilled.

-- ---------------------------------------------------------------- condition groups (SNOMED CT)
CREATE TABLE IF NOT EXISTS analytics.condition_groups (
    group_name   text NOT NULL,
    code         text NOT NULL,
    description  text NOT NULL,
    PRIMARY KEY (group_name, code)
);
DELETE FROM analytics.condition_groups;
INSERT INTO analytics.condition_groups (group_name, code, description) VALUES
    -- Diabetes = the diagnosis code OR a "due to diabetes" complication. In this data 78 of 164
    -- patients have a complication code but no diagnosis code (the diagnosis predates Synthea's
    -- 10-year history window), so the diagnosis code alone would miss almost half.
    ('diabetes', '44054006',        'Diabetes mellitus type 2 (disorder)'),
    ('diabetes', '127013003',       'Disorder of kidney due to diabetes mellitus (disorder)'),
    ('diabetes', '90781000119102',  'Microalbuminuria due to type 2 diabetes mellitus (disorder)'),
    ('diabetes', '157141000119108', 'Proteinuria due to type 2 diabetes mellitus (disorder)'),
    ('diabetes', '368581000119106', 'Neuropathy due to type 2 diabetes mellitus (disorder)'),
    ('diabetes', '1551000119108',   'Nonproliferative diabetic retinopathy due to type II diabetes mellitus'),
    ('diabetes', '1501000119109',   'Proliferative diabetic retinopathy due to type II diabetes mellitus'),
    ('diabetes', '97331000119101',  'Macular edema and retinopathy due to type 2 diabetes mellitus (disorder)'),
    ('hypertension', '59621000',    'Essential hypertension (disorder)'),
    ('copd', '185086009',           'Chronic obstructive bronchitis (disorder)'),
    ('copd', '87433001',            'Pulmonary emphysema (disorder)'),
    ('asthma', '195967001',         'Asthma (disorder)'),
    ('asthma', '233678006',         'Childhood asthma (disorder)'),
    ('chronic_kidney_disease', '431855005', 'Chronic kidney disease stage 1 (disorder)'),
    ('chronic_kidney_disease', '431856006', 'Chronic kidney disease stage 2 (disorder)'),
    ('chronic_kidney_disease', '433144002', 'Chronic kidney disease stage 3 (disorder)'),
    ('chronic_kidney_disease', '431857002', 'Chronic kidney disease stage 4 (disorder)'),
    ('chronic_kidney_disease', '46177005',  'End-stage renal disease (disorder)'),
    ('heart_failure', '88805009',   'Chronic congestive heart failure (disorder)'),
    ('heart_failure', '84114007',   'Heart failure (disorder)');

-- ---------------------------------------------------------------- vaccine groups (CVX)
CREATE TABLE IF NOT EXISTS analytics.vaccine_groups (
    group_name   text NOT NULL,
    cvx_code     text NOT NULL,
    description  text NOT NULL,
    PRIMARY KEY (group_name, cvx_code)
);
DELETE FROM analytics.vaccine_groups;
-- Seasonal influenza vaccines from CDC's CVX code table (www2a.cdc.gov, rpt=cvx, read
-- 2026-09-27). Deliberately NOT matched on the word "influenza": that would also catch Hib
-- vaccines (Haemophilus influenzae type b, a bacterium). Avian H5N1/H5N8 and 2009 pandemic
-- H1N1 vaccines are excluded because they are not the seasonal flu shot. The data only
-- contains code 140, but the full list keeps the analysis correct for other data.
INSERT INTO analytics.vaccine_groups (group_name, cvx_code, description) VALUES
    ('influenza_seasonal', '15',  'influenza, split (incl. purified surface antigen)'),
    ('influenza_seasonal', '16',  'influenza, whole'),
    ('influenza_seasonal', '88',  'influenza, unspecified formulation'),
    ('influenza_seasonal', '111', 'Influenza, live, trivalent, intranasal, PF'),
    ('influenza_seasonal', '135', 'Influenza, high-dose, trivalent, PF'),
    ('influenza_seasonal', '140', 'Influenza, split virus, trivalent, PF'),
    ('influenza_seasonal', '141', 'Influenza, split virus, trivalent, preservative'),
    ('influenza_seasonal', '144', 'influenza, seasonal, intradermal, preservative free'),
    ('influenza_seasonal', '149', 'Influenza, live, quadrivalent, intranasal'),
    ('influenza_seasonal', '150', 'Influenza, split virus, quadrivalent, PF'),
    ('influenza_seasonal', '151', 'influenza nasal, unspecified formulation'),
    ('influenza_seasonal', '153', 'Influenza, MDCK, trivalent, PF'),
    ('influenza_seasonal', '155', 'Influenza, recombinant, trivalent, PF'),
    ('influenza_seasonal', '158', 'Influenza, split virus, quadrivalent, preservative'),
    ('influenza_seasonal', '161', 'Influenza, injectable, quadrivalent, preservative free, pediatric'),
    ('influenza_seasonal', '166', 'influenza, intradermal, quadrivalent, preservative free'),
    ('influenza_seasonal', '168', 'Influenza, adjuvanted, trivalent, PF'),
    ('influenza_seasonal', '171', 'Influenza, MDCK, quadrivalent, PF'),
    ('influenza_seasonal', '185', 'Influenza, recombinant, quadrivalent, PF'),
    ('influenza_seasonal', '186', 'Influenza, MDCK, quadrivalent, preservative'),
    ('influenza_seasonal', '194', 'Influenza, Southern Hemisphere'),
    ('influenza_seasonal', '197', 'Influenza, high-dose, quadrivalent, PF'),
    ('influenza_seasonal', '200', 'influenza, Southern Hemisphere, pediatric, preservative free'),
    ('influenza_seasonal', '201', 'Influenza, Southern Hemisphere, quadrivalent, PF'),
    ('influenza_seasonal', '202', 'influenza, Southern Hemisphere, quadrivalent, with preservative'),
    ('influenza_seasonal', '205', 'Influenza, adjuvanted, quadrivalent, PF'),
    ('influenza_seasonal', '231', 'influenza, Southern Hemisphere, high-dose, quadrivalent'),
    ('influenza_seasonal', '320', 'Influenza, MDCK, trivalent, preservative'),
    ('influenza_seasonal', '331', 'Influenza, Southern Hemisphere, trivalent, PF'),
    ('influenza_seasonal', '333', 'Influenza, live, trivalent, intranasal, self/caregiver admin, PF'),
    ('influenza_seasonal', '337', 'Influenza, Southern Hemisphere, high-dose, trivalent, PF'),
    ('influenza_seasonal', '338', 'Influenza, mRNA, trivalent, PF');

-- ---------------------------------------------------------------- small-cell suppression
-- CMS cell-size suppression policy: no cell with a value from 1 to 10 may be shown, and no
-- figure may be shown that lets someone work such a value out (e.g. a percentage).
-- Zero is allowed. These helpers make that rule one function call in every analysis.

-- TRUE when n must not be shown.
CREATE OR REPLACE FUNCTION analytics.is_small(n bigint) RETURNS boolean
    LANGUAGE sql IMMUTABLE AS $$ SELECT n BETWEEN 1 AND 10 $$;

-- The count itself, or NULL if it must be hidden.
CREATE OR REPLACE FUNCTION analytics.suppress(n bigint) RETURNS bigint
    LANGUAGE sql IMMUTABLE AS $$ SELECT CASE WHEN n BETWEEN 1 AND 10 THEN NULL ELSE n END $$;

-- A percentage (1 decimal), NULL if numerator or denominator is small (either would reveal
-- a small count) or the denominator is 0.
CREATE OR REPLACE FUNCTION analytics.safe_pct(numerator bigint, denominator bigint)
    RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN numerator BETWEEN 1 AND 10 OR denominator BETWEEN 1 AND 10 OR denominator = 0
            THEN NULL
        ELSE round(100.0 * numerator / denominator, 1)
    END
$$;

-- For a TOTAL row: TRUE if the cells hidden beneath it add up to 1-10. Showing the total then
-- would let someone subtract the visible cells and recover a small number. (If the hidden
-- cells add up to 11+, only their combined sum is revealed, which the policy allows.)
CREATE OR REPLACE FUNCTION analytics.total_reveals_small(hidden_sum bigint) RETURNS boolean
    LANGUAGE sql IMMUTABLE AS $$ SELECT COALESCE(hidden_sum, 0) BETWEEN 1 AND 10 $$;
