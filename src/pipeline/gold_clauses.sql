-- Clause extraction: ONE ai_extract (v2.1, confidence + citations) call per document covering all
-- clause types. Long documents (> 80k chars) are truncated to the first 50k + last 30k chars
-- (governing law, notices and liability sections are usually at the end) and flagged.

CREATE OR REFRESH STREAMING TABLE int_doc_extracted
COMMENT 'Intermediate: one ai_extract v2.1 call per document; extract_input is the exact text sent.'
AS
WITH t AS (
  SELECT doc_id, full_text, length(full_text) AS text_len
  FROM STREAM(silver_parsed)
),
inp AS (
  SELECT doc_id, text_len,
         text_len > 80000 AS truncated,
         CASE WHEN text_len > 80000
              THEN concat(substr(full_text, 1, 50000), '\n\n[... middle of document omitted ...]\n\n',
                          substr(full_text, text_len - 29999, 30000))
              ELSE full_text END AS extract_input
  FROM t
)
SELECT
  doc_id, text_len, truncated, extract_input,
  ai_extract(
    extract_input,
    '{
      "document_title": {"type": "string", "description": "Title of the agreement as written on the document"},
      "parties": {"type": "string", "description": "Legal names of the contracting parties, separated by semicolons"},
      "governing_law": {"type": "string", "description": "State or country whose law governs the agreement, e.g. Delaware, New York, England and Wales"},
      "effective_date": {"type": "string", "description": "Effective or commencement date as YYYY-MM-DD; null if not stated"},
      "expiration_date": {"type": "string", "description": "Date the initial term ends as YYYY-MM-DD. If only a duration is given, compute it from the effective date. Null if perpetual or not determinable"},
      "renewal_term": {"type": "string", "description": "Length of any renewal term, e.g. successive one-year terms; null if no renewal"},
      "auto_renewal": {"type": "boolean", "description": "true ONLY if the term renews or extends automatically (evergreen) unless a party gives notice of non-renewal. false if renewal requires mutual agreement, an amendment, or an affirmative election or notice to renew"},
      "notice_period_days": {"type": "integer", "description": "Days of advance notice required to prevent automatic renewal or to terminate at the end of the term (non-renewal notice), converting months to days (1 month = 30). Do NOT use cure periods, notice of breach, or termination-for-cause notice. Null if none"},
      "liability_cap": {"type": "string", "description": "Short description of any cap or limit on liability, e.g. fees paid in prior 12 months; null if none"},
      "liability_cap_amount_usd": {"type": "number", "description": "Cap amount in US dollars only if a fixed dollar figure is stated; null otherwise"},
      "uncapped_liability": {"type": "boolean", "description": "true if liability is uncapped or unlimited for any party or for certain breaches (e.g. carve-outs from the cap); false otherwise"},
      "indemnification": {"type": "string", "description": "Short summary of indemnification obligations; null if none"},
      "termination_for_convenience": {"type": "string", "description": "Short summary of any right to terminate without cause; null if none"},
      "exclusivity": {"type": "string", "description": "Short summary of any exclusivity obligation; null if none"},
      "non_compete": {"type": "string", "description": "Short summary of any non-compete restriction; null if none"},
      "assignment_restriction": {"type": "string", "description": "Short summary of restrictions on assignment (consent required, change of control); null if none"}
    }',
    map('version', '2.1', 'enableConfidenceScores', 'true', 'enableCitations', 'true',
        'instructions', 'You are a contract analyst. Extract the requested terms from this commercial contract. Return null for anything not stated.')
  ) AS extraction,
  current_timestamp() AS extracted_at
FROM inp;

-- One row per (document, clause_type) where the model returned a value.
CREATE OR REFRESH STREAMING TABLE int_clauses (
  CONSTRAINT confidence_not_null EXPECT (confidence IS NOT NULL) ON VIOLATION DROP ROW
)
COMMENT 'Intermediate: exploded clauses with confidence and source snippet from citations.'
AS
WITH x AS (
  SELECT doc_id, extract_input, extraction, extracted_at,
         from_json(to_json(extraction:metadata.citations), 'array<struct<id:int,start:int,stop:int>>') AS cits,
         extraction:response.liability_cap_amount_usd.value::double AS cap_amount,
         extraction:response.parties.value::string AS party_name,
         explode(array(
           named_struct('t', 'governing_law',               'v', extraction:response.governing_law.value::string,               'c', extraction:response.governing_law.confidence_score::double,               'cid', extraction:response.governing_law.citation_ids[0]::int),
           named_struct('t', 'effective_date',              'v', extraction:response.effective_date.value::string,              'c', extraction:response.effective_date.confidence_score::double,              'cid', extraction:response.effective_date.citation_ids[0]::int),
           named_struct('t', 'expiration_date',             'v', extraction:response.expiration_date.value::string,             'c', extraction:response.expiration_date.confidence_score::double,             'cid', extraction:response.expiration_date.citation_ids[0]::int),
           named_struct('t', 'renewal_term',                'v', extraction:response.renewal_term.value::string,                'c', extraction:response.renewal_term.confidence_score::double,                'cid', extraction:response.renewal_term.citation_ids[0]::int),
           named_struct('t', 'auto_renewal',                'v', extraction:response.auto_renewal.value::string,                'c', extraction:response.auto_renewal.confidence_score::double,                'cid', extraction:response.auto_renewal.citation_ids[0]::int),
           named_struct('t', 'notice_period_days',          'v', extraction:response.notice_period_days.value::string,          'c', extraction:response.notice_period_days.confidence_score::double,          'cid', extraction:response.notice_period_days.citation_ids[0]::int),
           named_struct('t', 'liability_cap',               'v', extraction:response.liability_cap.value::string,               'c', extraction:response.liability_cap.confidence_score::double,               'cid', extraction:response.liability_cap.citation_ids[0]::int),
           named_struct('t', 'uncapped_liability',          'v', extraction:response.uncapped_liability.value::string,          'c', extraction:response.uncapped_liability.confidence_score::double,          'cid', extraction:response.uncapped_liability.citation_ids[0]::int),
           named_struct('t', 'indemnification',             'v', extraction:response.indemnification.value::string,             'c', extraction:response.indemnification.confidence_score::double,             'cid', extraction:response.indemnification.citation_ids[0]::int),
           named_struct('t', 'termination_for_convenience', 'v', extraction:response.termination_for_convenience.value::string, 'c', extraction:response.termination_for_convenience.confidence_score::double, 'cid', extraction:response.termination_for_convenience.citation_ids[0]::int),
           named_struct('t', 'exclusivity',                 'v', extraction:response.exclusivity.value::string,                 'c', extraction:response.exclusivity.confidence_score::double,                 'cid', extraction:response.exclusivity.citation_ids[0]::int),
           named_struct('t', 'non_compete',                 'v', extraction:response.non_compete.value::string,                 'c', extraction:response.non_compete.confidence_score::double,                 'cid', extraction:response.non_compete.citation_ids[0]::int),
           named_struct('t', 'assignment_restriction',      'v', extraction:response.assignment_restriction.value::string,      'c', extraction:response.assignment_restriction.confidence_score::double,      'cid', extraction:response.assignment_restriction.citation_ids[0]::int),
           named_struct('t', 'parties',                     'v', extraction:response.parties.value::string,                     'c', extraction:response.parties.confidence_score::double,                     'cid', extraction:response.parties.citation_ids[0]::int)
         )) AS f
  FROM STREAM(int_doc_extracted)
),
s AS (
  SELECT x.*, filter(cits, c -> c.id = f.cid)[0] AS cit FROM x
)
SELECT
  sha2(concat(doc_id, ':', f.t), 256) AS clause_id,
  doc_id,
  f.t AS clause_type,
  f.v AS extracted_value,
  CASE f.t
    WHEN 'governing_law' THEN initcap(trim(regexp_replace(f.v, '(?i)^(the\\s+)?(laws?\\s+of\\s+)?(the\\s+)?(state|commonwealth)\\s+of\\s+', '')))
    WHEN 'effective_date' THEN cast(try_to_date(f.v) AS STRING)
    WHEN 'expiration_date' THEN cast(try_to_date(f.v) AS STRING)
    WHEN 'auto_renewal' THEN lower(f.v)
    WHEN 'uncapped_liability' THEN lower(f.v)
    WHEN 'liability_cap' THEN coalesce(cast(cap_amount AS STRING), f.v)
    ELSE f.v
  END AS normalized_value,
  CASE WHEN cit IS NOT NULL THEN substr(extract_input, cit.start + 1, least(cit.stop - cit.start, 600)) END AS source_snippet,
  f.c AS confidence,
  '${extract_model_label}' AS model_name,
  party_name,
  extracted_at
FROM s
WHERE f.v IS NOT NULL AND trim(f.v) <> '';

CREATE OR REFRESH MATERIALIZED VIEW gold_clauses (
  clause_id STRING,
  doc_id STRING,
  clause_type STRING,
  extracted_value STRING MASK ${catalog}.curated.mask_parties_clause USING COLUMNS (clause_type),
  normalized_value STRING MASK ${catalog}.curated.mask_parties_clause USING COLUMNS (clause_type),
  source_snippet STRING MASK ${catalog}.curated.mask_parties_clause USING COLUMNS (clause_type),
  confidence DOUBLE,
  model_name STRING,
  extracted_at TIMESTAMP,
  party_name STRING MASK ${catalog}.curated.mask_party,
  matter_id STRING,
  matter_team STRING
)
WITH ROW FILTER ${catalog}.curated.matter_team_filter ON (matter_team)
COMMENT 'One row per extracted clause. Row-filtered by matter team; party names masked.'
AS SELECT
  c.clause_id, c.doc_id, c.clause_type, c.extracted_value, c.normalized_value, c.source_snippet,
  c.confidence, c.model_name, c.extracted_at, c.party_name, dm.matter_id, dm.matter_team
FROM int_clauses c
JOIN doc_matter dm USING (doc_id);
