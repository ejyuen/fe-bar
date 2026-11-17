-- Contract-type classification (ai_classify v2.1 with confidence) and the gold_documents view.

CREATE OR REFRESH STREAMING TABLE int_doc_classified
COMMENT 'Intermediate: one ai_classify call per document (first 20k chars).'
AS SELECT
  doc_id,
  ai_classify(
    substr(full_text, 1, 20000),
    '{"MSA": "Master services / services / consulting / outsourcing / maintenance agreement",
      "NDA": "Non-disclosure or confidentiality agreement",
      "SOW": "Statement of work or work order under another agreement",
      "License": "License, IP, trademark, software or content license agreement",
      "Supply": "Supply, manufacturing or purchase agreement for goods",
      "Distribution": "Distribution, reseller, dealer, franchise, agency or marketing/affiliate agreement",
      "Employment": "Employment, consulting-individual, non-compete or severance agreement",
      "Lease": "Real estate or equipment lease",
      "Other": "Joint venture, collaboration, sponsorship, hosting, transportation or anything else"}',
    map('version', '2.1', 'enableConfidenceScores', 'true',
        'instructions', 'Classify this commercial contract by its primary agreement type.')
  ) AS classification,
  least(length(full_text), 20000) AS classify_input_chars,
  current_timestamp() AS classified_at
FROM STREAM(silver_parsed);

-- Deterministic synthetic document -> matter assignment.
CREATE OR REFRESH PRIVATE MATERIALIZED VIEW doc_matter AS
SELECT s.doc_id, m.matter_id, m.matter_team
FROM silver_parsed s
CROSS JOIN (SELECT count(*) AS n FROM ${catalog}.curated.matters) c
JOIN ${catalog}.curated.matters m
  ON m.matter_seq = pmod(xxhash64(s.doc_id), c.n);

CREATE OR REFRESH MATERIALIZED VIEW gold_documents (
  doc_id STRING,
  path STRING,
  title STRING,
  party_name STRING MASK ${catalog}.curated.mask_party,
  contract_type STRING,
  contract_type_confidence DOUBLE,
  page_count INT,
  truncated BOOLEAN,
  matter_id STRING,
  matter_team STRING
)
WITH ROW FILTER ${catalog}.curated.matter_team_filter ON (matter_team)
COMMENT 'One row per contract: type, matter assignment. Row-filtered by matter team; party_name masked.'
AS SELECT
  s.doc_id,
  s.path,
  coalesce(x.extraction:response.document_title.value::string,
           regexp_extract(s.path, '([^/]+)\\.(pdf|PDF)$', 1)) AS title,
  x.extraction:response.parties.value::string                 AS party_name,
  c.classification:response[0].value::string                  AS contract_type,
  c.classification:response[0].confidence_score::double       AS contract_type_confidence,
  s.page_count,
  x.truncated,
  dm.matter_id,
  dm.matter_team
FROM silver_parsed s
JOIN int_doc_classified c USING (doc_id)
LEFT JOIN int_doc_extracted x USING (doc_id)
JOIN doc_matter dm USING (doc_id);
