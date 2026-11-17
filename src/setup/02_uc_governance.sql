-- Unity Catalog governance for Matter Intelligence.
-- Executed by run_sql_file.py: section "pre" runs before the pipeline (functions the pipeline
-- tables reference), section "post" runs after (tags and grants on pipeline-managed tables).
--
-- Groups: legal_admins, legal_reviewers, legal_reviewers_full. In this workspace they are
-- workspace-local groups, which is_member() can evaluate inside masks / row filters but which
-- Unity Catalog GRANT cannot target; grants to them are therefore marked @allow_fail and their
-- outcome is recorded in curated.governance_log.

-- @section pre
CREATE SCHEMA IF NOT EXISTS ${catalog}.raw;
CREATE SCHEMA IF NOT EXISTS ${catalog}.curated;
CREATE SCHEMA IF NOT EXISTS ${catalog}.serving;
CREATE SCHEMA IF NOT EXISTS ${catalog}.ml;

-- Column mask: party names are visible only to legal_reviewers_full.
CREATE OR REPLACE FUNCTION ${catalog}.curated.mask_party(party_name STRING)
  RETURNS STRING
  COMMENT 'Column mask: shows party names only to members of legal_reviewers_full'
  RETURN CASE WHEN is_member('legal_reviewers_full') THEN party_name ELSE 'Party ***' END;

-- Same rule applied to gold_clauses.extracted_value / normalized_value when the clause is the parties clause.
CREATE OR REPLACE FUNCTION ${catalog}.curated.mask_parties_clause(value STRING, clause_type STRING)
  RETURNS STRING
  COMMENT 'Column mask: hides the value of parties clauses unless member of legal_reviewers_full'
  RETURN CASE WHEN clause_type <> 'parties' OR is_member('legal_reviewers_full') THEN value ELSE 'Party ***' END;

-- Row filter: a user sees rows for matter teams they belong to, or everything if legal_admins.
CREATE OR REPLACE FUNCTION ${catalog}.curated.matter_team_filter(team STRING)
  RETURNS BOOLEAN
  COMMENT 'Row filter: matter_team must be one of the caller''s teams (user_team_mapping) unless legal_admins'
  RETURN is_member('legal_admins')
      OR EXISTS (SELECT 1 FROM ${catalog}.curated.user_team_mapping m
                 WHERE m.user_email = current_user() AND m.matter_team = team);

-- @section post
ALTER SCHEMA ${catalog}.curated SET TAGS ('privileged' = 'true');
-- `pii` is an account-level governed tag here whose allowed values are only [ssn, address], so the
-- attempt below is expected to be rejected (recorded in governance_log); the ungoverned key
-- data_classification = 'pii' carries the classification instead.
-- @allow_fail
ALTER MATERIALIZED VIEW ${catalog}.curated.gold_clauses ALTER COLUMN party_name SET TAGS ('pii' = 'true');
ALTER MATERIALIZED VIEW ${catalog}.curated.gold_clauses ALTER COLUMN party_name SET TAGS ('data_classification' = 'pii');
ALTER MATERIALIZED VIEW ${catalog}.curated.gold_documents ALTER COLUMN party_name SET TAGS ('data_classification' = 'pii');
ALTER STREAMING TABLE ${catalog}.curated.silver_parsed ALTER COLUMN full_text SET TAGS ('data_classification' = 'pii');
ALTER MATERIALIZED VIEW ${catalog}.curated.gold_clauses SET TAGS ('privileged' = 'true');
ALTER MATERIALIZED VIEW ${catalog}.curated.gold_documents SET TAGS ('privileged' = 'true');
ALTER MATERIALIZED VIEW ${catalog}.curated.gold_risk_flags SET TAGS ('privileged' = 'true');

-- @allow_fail
GRANT USE CATALOG ON CATALOG ${catalog} TO `legal_reviewers`;
-- @allow_fail
GRANT USE SCHEMA, SELECT ON SCHEMA ${catalog}.curated TO `legal_reviewers`;
-- @allow_fail
GRANT USE CATALOG ON CATALOG ${catalog} TO `legal_reviewers_full`;
-- @allow_fail
GRANT USE SCHEMA, SELECT ON SCHEMA ${catalog}.curated TO `legal_reviewers_full`;
