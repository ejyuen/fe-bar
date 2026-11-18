-- Curated example question / SQL pairs for the Genie space (parsed by create_space.py).
-- Format: a "-- Q:" line with the question, then the SQL ending with ";".

-- Q: Which contracts auto-renew in the next 90 days with uncapped liability?
SELECT title, contract_type, matter_team, next_renewal_date, non_renewal_notice_deadline
FROM ${catalog}.curated.contract_terms_current
WHERE auto_renewal AND uncapped_liability
  AND next_renewal_date BETWEEN current_date() AND date_add(current_date(), 90)
ORDER BY next_renewal_date;

-- Q: Count of high-severity flags by contract type
SELECT d.contract_type, count(*) AS high_severity_flags
FROM ${catalog}.curated.gold_risk_flags f
JOIN ${catalog}.curated.gold_documents d USING (doc_id)
WHERE f.severity = 'high'
GROUP BY d.contract_type
ORDER BY high_severity_flags DESC;

-- Q: Most common governing law
SELECT governing_law, count(*) AS contracts
FROM ${catalog}.curated.contract_terms_current
WHERE governing_law IS NOT NULL
GROUP BY governing_law
ORDER BY contracts DESC
LIMIT 1;

-- Q: Average liability cap by contract type
SELECT contract_type, round(avg(liability_cap_amount_usd), 0) AS avg_liability_cap_usd,
       count(liability_cap_amount_usd) AS contracts_with_dollar_cap
FROM ${catalog}.curated.contract_terms_current
GROUP BY contract_type
ORDER BY avg_liability_cap_usd DESC NULLS LAST;

-- Q: Documents pending review by matter team
SELECT matter_team, count(DISTINCT doc_id) AS documents_pending_review, count(*) AS clauses_pending
FROM ${catalog}.serving.pg_review_queue
WHERE status = 'pending'
GROUP BY matter_team
ORDER BY documents_pending_review DESC;

-- Q: Override rate by clause type
SELECT clause_type, count(*) AS reviewer_decisions,
       count_if(review_action = 'override') AS overrides,
       round(count_if(review_action = 'override') / count(*), 2) AS override_rate
FROM ${catalog}.curated.gold_reviewed_clauses
GROUP BY clause_type
ORDER BY override_rate DESC, reviewer_decisions DESC;

-- Q: Which auto-renewing contracts have a notice deadline in the next 180 days?
SELECT title, contract_type, matter_team, notice_period_days, non_renewal_notice_deadline, next_renewal_date
FROM ${catalog}.curated.contract_terms_current
WHERE auto_renewal
  AND non_renewal_notice_deadline BETWEEN current_date() AND date_add(current_date(), 180)
ORDER BY non_renewal_notice_deadline;

-- Q: Contracts with a non-compete by matter team
SELECT matter_team, count(*) AS contracts_with_non_compete
FROM ${catalog}.curated.contract_terms_current
WHERE has_non_compete
GROUP BY matter_team
ORDER BY contracts_with_non_compete DESC;

-- Q: Number of risk flags by playbook rule and severity
SELECT f.rule_id, p.rule_text, f.severity, count(*) AS flags
FROM ${catalog}.curated.gold_risk_flags f
JOIN ${catalog}.curated.risk_playbook p USING (rule_id)
GROUP BY f.rule_id, p.rule_text, f.severity
ORDER BY flags DESC;
