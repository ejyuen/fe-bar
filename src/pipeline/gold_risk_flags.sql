-- Rule-based risk flags from the firm playbook; ai_query writes a grounded 1-2 sentence explanation
-- for each high/medium flag (once per flag, streaming).

CREATE OR REFRESH STREAMING TABLE int_risk_flags
COMMENT 'Intermediate: playbook matches + AI explanations (ai_query, failOnError=false).'
AS
WITH m AS (
  SELECT
    sha2(concat(c.clause_id, ':', p.rule_id), 256) AS flag_id,
    c.clause_id, c.doc_id, c.clause_type, c.normalized_value, c.source_snippet, c.source_context,
    p.rule_id, p.severity, p.rule_text,
    concat(p.rule_text, ' Extracted value: ', substr(c.normalized_value, 1, 200)) AS reason
  FROM STREAM(int_clauses) c
  JOIN ${catalog}.curated.risk_playbook p
    ON p.clause_type = c.clause_type
   AND (   (p.rule_type = 'is_true' AND lower(c.normalized_value) = 'true')
        OR (p.rule_type = 'present' AND lower(trim(c.normalized_value)) NOT IN ('none', 'n/a', 'false', 'no'))
        OR (p.rule_type = 'gte' AND try_cast(c.normalized_value AS DOUBLE) >= cast(p.match_value AS DOUBLE))
        OR (p.rule_type = 'not_in' AND NOT array_contains(split(p.match_value, ','), lower(trim(c.normalized_value)))))
),
e AS (
  SELECT m.*,
    CASE WHEN severity IN ('high', 'medium') THEN concat(
      'You are a contract risk analyst writing for an in-house lawyer. Using ONLY the contract excerpt below, ',
      'write 1-2 sentences explaining why this clause triggers the playbook rule, quoting the decisive words. ',
      'Do not state any number, party, section or obligation that is not in the excerpt. If the excerpt does not ',
      'support the rule, reply exactly: "Not supported by the cited text - needs reviewer check."\n',
      'Rule: ', rule_text, '\nClause type: ', clause_type, '\nExtracted value: ', coalesce(normalized_value, ''),
      '\nContract excerpt: """', coalesce(source_context, source_snippet, '(no excerpt)'), '"""') END AS prompt
  FROM m
)
SELECT
  flag_id, clause_id, doc_id, rule_id, severity, reason, clause_type, source_snippet, source_context, prompt,
  CASE WHEN prompt IS NOT NULL THEN
    ai_query('${explain_model}', prompt,
             modelParameters => named_struct('max_tokens', 200, 'temperature', 0.0),
             failOnError => false) END AS explanation_result,
  '${explain_model}' AS explain_model,
  current_timestamp() AS flagged_at
FROM e;

CREATE OR REFRESH MATERIALIZED VIEW gold_risk_flags (
  flag_id STRING,
  clause_id STRING,
  doc_id STRING,
  rule_id STRING,
  severity STRING,
  reason STRING,
  clause_type STRING,
  explanation STRING,
  explanation_error STRING,
  explain_model STRING,
  flagged_at TIMESTAMP,
  matter_id STRING,
  matter_team STRING
)
WITH ROW FILTER ${catalog}.curated.matter_team_filter ON (matter_team)
COMMENT 'Playbook risk flags with AI-written explanations. Row-filtered by matter team.'
AS SELECT
  f.flag_id, f.clause_id, f.doc_id, f.rule_id, f.severity, f.reason, f.clause_type,
  f.explanation_result.result     AS explanation,
  f.explanation_result.errorMessage AS explanation_error,
  f.explain_model, f.flagged_at, dm.matter_id, dm.matter_team
FROM int_risk_flags f
JOIN doc_matter dm USING (doc_id);
