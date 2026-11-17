-- Cost per stage. Token counts are ESTIMATES (chars / 4) because AI Functions do not return
-- usage; unit prices are illustrative pipeline configuration values (see resources/pipeline.yml).
-- run_id = processing date of the batch.

CREATE OR REFRESH MATERIALIZED VIEW gold_cost_metrics
COMMENT 'Estimated AI cost per stage and per 1K documents (chars/4 token estimate, illustrative prices).'
AS
WITH stages AS (
  SELECT date_format(parsed_at, 'yyyyMMdd') AS run_id, 'parse' AS stage, count(*) AS docs,
         sum(page_count) AS pages, CAST(NULL AS BIGINT) AS input_tokens, CAST(NULL AS BIGINT) AS output_tokens,
         sum(page_count) * CAST('${price_parse_per_page}' AS DOUBLE) AS est_cost_usd
  FROM silver_parsed GROUP BY 1
  UNION ALL
  SELECT date_format(classified_at, 'yyyyMMdd'), 'classify', count(*), NULL,
         CAST(sum(classify_input_chars) / 4 AS BIGINT), CAST(count(*) * 30 AS BIGINT),
         sum(classify_input_chars) / 4 / 1e6 * CAST('${price_ai_fn_input_per_1m}' AS DOUBLE)
           + count(*) * 30 / 1e6 * CAST('${price_ai_fn_output_per_1m}' AS DOUBLE)
  FROM int_doc_classified GROUP BY 1
  UNION ALL
  SELECT date_format(extracted_at, 'yyyyMMdd'), 'extract', count(*), NULL,
         CAST(sum(length(extract_input)) / 4 AS BIGINT), CAST(sum(length(to_json(extraction))) / 4 AS BIGINT),
         sum(length(extract_input)) / 4 / 1e6 * CAST('${price_ai_fn_input_per_1m}' AS DOUBLE)
           + sum(length(to_json(extraction))) / 4 / 1e6 * CAST('${price_ai_fn_output_per_1m}' AS DOUBLE)
  FROM int_doc_extracted GROUP BY 1
  UNION ALL
  SELECT date_format(flagged_at, 'yyyyMMdd'), 'explain', count(DISTINCT doc_id), NULL,
         CAST(sum(length(prompt)) / 4 AS BIGINT), CAST(sum(length(explanation_result.result)) / 4 AS BIGINT),
         coalesce(sum(length(prompt)), 0) / 4 / 1e6 * CAST('${price_explain_input_per_1m}' AS DOUBLE)
           + coalesce(sum(length(explanation_result.result)), 0) / 4 / 1e6 * CAST('${price_explain_output_per_1m}' AS DOUBLE)
  FROM int_risk_flags WHERE prompt IS NOT NULL GROUP BY 1
),
total AS (
  SELECT run_id, 'total' AS stage,
         max(CASE WHEN stage = 'parse' THEN docs END) AS docs,
         max(CASE WHEN stage = 'parse' THEN pages END) AS pages,
         sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens,
         sum(est_cost_usd) AS est_cost_usd
  FROM stages GROUP BY run_id
),
all_rows AS (
  SELECT s.run_id, s.stage, s.docs, s.pages, s.input_tokens, s.output_tokens, s.est_cost_usd,
         t.docs AS parsed_docs
  FROM stages s JOIN total t USING (run_id)
  UNION ALL
  SELECT run_id, stage, docs, pages, input_tokens, output_tokens, est_cost_usd, docs FROM total
)
SELECT run_id, stage, docs, pages, input_tokens, output_tokens,
       round(est_cost_usd, 4) AS est_cost_usd,
       -- normalise every stage by parsed documents so stage rows sum to the total
       round(est_cost_usd / nullif(parsed_docs, 0) * 1000, 2) AS cost_per_1k_docs
FROM all_rows;
