-- Serving: one row per extracted clause with its worst risk flag and the routing decision.
-- Source of the Lakebase synced table (no row filter / masks: synced-table sources must be plain).
-- Routing rule: confidence >= 0.9 AND no high-severity flag -> auto_accepted, else pending.
CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.serving.review_queue_source
COMMENT 'Review queue source for the Lakebase synced table (routing rule applied).'
AS
WITH f AS (
  SELECT clause_id,
         max(CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END) AS sev_rank,
         count(*) AS flag_count,
         max_by(explanation_result.result, CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END) AS risk_explanation,
         max_by(rule_id, CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END) AS top_rule_id
  FROM int_risk_flags GROUP BY clause_id
)
SELECT
  c.clause_id,
  c.doc_id,
  coalesce(x.extraction:response.document_title.value::string, regexp_extract(s.path, '([^/]+)\\.(pdf|PDF)$', 1)) AS doc_title,
  k.classification:response[0].value::string AS contract_type,
  dm.matter_id,
  dm.matter_team,
  c.clause_type,
  c.extracted_value,
  c.normalized_value,
  c.source_snippet,
  c.confidence,
  CASE f.sev_rank WHEN 3 THEN 'high' WHEN 2 THEN 'medium' WHEN 1 THEN 'low' ELSE 'none' END AS severity,
  coalesce(f.flag_count, 0) AS flag_count,
  f.top_rule_id,
  f.risk_explanation,
  CASE WHEN c.confidence >= 0.9 AND coalesce(f.sev_rank, 0) < 3 THEN 'auto_accepted' ELSE 'pending' END AS initial_status,
  c.extracted_at
FROM int_clauses c
JOIN doc_matter dm USING (doc_id)
JOIN silver_parsed s USING (doc_id)
LEFT JOIN int_doc_extracted x USING (doc_id)
LEFT JOIN int_doc_classified k USING (doc_id)
LEFT JOIN f USING (clause_id);
