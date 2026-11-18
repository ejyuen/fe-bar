-- Query-time view used by Genie and the ROI model: one row per contract with the CURRENT value of
-- each key term. Reviewed values from Lakebase (curated.gold_reviewed_clauses) always win over
-- AI-extracted values. Row filters / masks on the underlying gold tables apply to the querying user.
--
-- next_renewal_date: CUAD contracts are historical filings, so for auto-renewing (evergreen)
-- contracts the initial expiration is rolled forward by the renewal term (default 12 months)
-- to the next date on or after today. Non-renewing contracts keep their stated expiration.
CREATE OR REPLACE VIEW ${catalog}.curated.contract_terms_current
COMMENT 'One row per contract with current key terms (reviewed values preferred) and next_renewal_date'
AS
WITH cur AS (
  SELECT c.doc_id, c.clause_type,
         coalesce(r.reviewed_value, c.normalized_value) AS value,
         r.clause_id IS NOT NULL AS reviewed
  FROM ${catalog}.curated.gold_clauses c
  LEFT JOIN ${catalog}.curated.gold_reviewed_clauses r USING (clause_id)
),
p AS (
  SELECT doc_id,
    max(CASE WHEN clause_type = 'governing_law' THEN value END) AS governing_law,
    try_to_date(max(CASE WHEN clause_type = 'effective_date' THEN value END)) AS effective_date,
    try_to_date(max(CASE WHEN clause_type = 'expiration_date' THEN value END)) AS expiration_date,
    max(CASE WHEN clause_type = 'renewal_term' THEN value END) AS renewal_term,
    coalesce(lower(max(CASE WHEN clause_type = 'auto_renewal' THEN value END)) = 'true', false) AS auto_renewal,
    try_cast(max(CASE WHEN clause_type = 'notice_period_days' THEN value END) AS INT) AS notice_period_days,
    max(CASE WHEN clause_type = 'liability_cap' THEN value END) AS liability_cap,
    coalesce(lower(max(CASE WHEN clause_type = 'uncapped_liability' THEN value END)) = 'true', false) AS uncapped_liability,
    max(CASE WHEN clause_type = 'exclusivity' THEN value END) IS NOT NULL AS has_exclusivity,
    max(CASE WHEN clause_type = 'non_compete' THEN value END) IS NOT NULL AS has_non_compete,
    bool_or(reviewed) AS has_reviewed_values
  FROM cur GROUP BY doc_id
),
t AS (
  SELECT p.*,
    try_cast(regexp_replace(liability_cap, '[^0-9.]', '') AS DOUBLE) AS liability_cap_amount_usd_raw,
    CASE
      WHEN regexp_extract(lower(renewal_term), '(\\d+)\\)?\\s*-?\\s*(year|month)', 2) = 'year'
        THEN 12 * cast(regexp_extract(lower(renewal_term), '(\\d+)\\)?\\s*-?\\s*(year|month)', 1) AS INT)
      WHEN regexp_extract(lower(renewal_term), '(\\d+)\\)?\\s*-?\\s*(year|month)', 2) = 'month'
        THEN cast(regexp_extract(lower(renewal_term), '(\\d+)\\)?\\s*-?\\s*(year|month)', 1) AS INT)
      WHEN lower(renewal_term) RLIKE '\\btwo[- ](\\(2\\) )?years?' THEN 24
      WHEN lower(renewal_term) RLIKE '\\bthree[- ](\\(3\\) )?years?' THEN 36
      WHEN lower(renewal_term) RLIKE '\\bfive[- ](\\(5\\) )?years?' THEN 60
      ELSE 12 END AS renewal_term_months,
    coalesce(expiration_date, add_months(effective_date, 12)) AS initial_term_end
  FROM p
),
f AS (
SELECT
  d.doc_id, d.title, d.contract_type, d.matter_id, d.matter_team, d.party_name,
  t.governing_law, t.effective_date, t.expiration_date, t.renewal_term, t.renewal_term_months,
  t.auto_renewal, t.notice_period_days, t.liability_cap,
  CASE WHEN t.liability_cap_amount_usd_raw > 1000 THEN t.liability_cap_amount_usd_raw END AS liability_cap_amount_usd,
  t.uncapped_liability, t.has_exclusivity, t.has_non_compete, t.has_reviewed_values,
  CASE
    WHEN t.initial_term_end IS NULL THEN NULL
    WHEN t.auto_renewal AND t.initial_term_end < current_date() THEN
      add_months(t.initial_term_end,
                 t.renewal_term_months * cast(ceil(months_between(current_date(), t.initial_term_end) / t.renewal_term_months) AS INT))
    ELSE t.initial_term_end END AS next_renewal_date
FROM t JOIN ${catalog}.curated.gold_documents d USING (doc_id)
)
SELECT f.*,
  CASE WHEN f.auto_renewal THEN date_sub(f.next_renewal_date, coalesce(f.notice_period_days, 0)) END AS non_renewal_notice_deadline,
  datediff(f.next_renewal_date, current_date()) AS days_to_next_renewal
FROM f;
