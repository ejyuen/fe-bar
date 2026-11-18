-- Lakebase (Postgres) schema for the reviewer workflow. Idempotent.
-- review_queue is the app-writable queue; it is (re)populated from the read-only synced table
-- serving.review_queue_synced (Delta serving.review_queue_source) without overwriting reviewer decisions.
CREATE SCHEMA IF NOT EXISTS review;

CREATE TABLE IF NOT EXISTS review.review_queue (
  clause_id        TEXT PRIMARY KEY,
  doc_id           TEXT NOT NULL,
  doc_title        TEXT,
  contract_type    TEXT,
  matter_id        TEXT,
  matter_team      TEXT,
  clause_type      TEXT NOT NULL,
  extracted_value  TEXT,
  normalized_value TEXT,
  source_snippet   TEXT,
  confidence       DOUBLE PRECISION,
  severity         TEXT,
  top_rule_id      TEXT,
  risk_explanation TEXT,
  status           TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'overridden', 'auto_accepted')),
  current_value    TEXT,
  assigned_to      TEXT,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS review_queue_status_idx ON review.review_queue (status, severity, matter_team);
CREATE INDEX IF NOT EXISTS review_queue_doc_idx ON review.review_queue (doc_id);

CREATE TABLE IF NOT EXISTS review.clause_reviews (
  review_id   BIGSERIAL PRIMARY KEY,
  clause_id   TEXT NOT NULL REFERENCES review.review_queue (clause_id),
  reviewer    TEXT NOT NULL,
  action      TEXT NOT NULL CHECK (action IN ('approve', 'override')),
  old_value   TEXT,
  new_value   TEXT,
  comment     TEXT,
  reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS clause_reviews_clause_idx ON review.clause_reviews (clause_id, review_id);

CREATE TABLE IF NOT EXISTS review.audit_log (
  id          BIGSERIAL PRIMARY KEY,
  actor       TEXT NOT NULL,
  action      TEXT NOT NULL,
  entity      TEXT,
  entity_id   TEXT,
  details     JSONB,
  duration_ms DOUBLE PRECISION,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON review.audit_log (ts);
