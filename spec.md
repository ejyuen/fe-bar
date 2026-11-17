# SPEC: Matter Intelligence — Legal Document Intelligence on Databricks

## Goal
Build an end-to-end demo on Databricks that ingests public legal contracts, extracts
structured clause data with AI Functions, governs it in Unity Catalog, serves a human
review workflow from Lakebase, exposes it via a Genie space, and surfaces it in a
Databricks App. Everything deploys via a Databricks Asset Bundle (DAB).

Business problem: corporate legal teams miss auto-renewal deadlines and can't see
uncapped-liability exposure across hundreds of vendor contracts.
Fictional customer: "Northwind Legal Cloud".
Time budget: ~6-7 hours total. Prefer the simplest working option; anything marked
STRETCH is optional and must not block the core build.

## Constraints
- Public or synthetic data ONLY. No customer data, no real customer names anywhere
  (code, comments, README, commit messages).
- The evaluator reads TEXT ONLY. Every phase must commit text execution evidence
  (see "Execution Evidence"). Source code alone fails.
- Python 3.11, Databricks SDK for Python, Databricks CLI (bundles).
- All Databricks resources parameterized by bundle variables: catalog, schema, warehouse_id,
  lakebase_instance, genie_space_id.
- Before using any AI Function (ai_parse_document, ai_classify, ai_extract, ai_query),
  check the current Databricks docs for signature/options; do not guess.
- Idempotent: rerunning any job must not duplicate data.
- Secrets via Databricks secret scopes / app resources only — never hardcode tokens.

## Data
- Primary: CUAD v1 (Contract Understanding Atticus Dataset) — ~510 commercial contracts
  (PDF + text) with 41 expert-labeled clause categories. Download from the Atticus Project
  (Zenodo / Hugging Face `theatticusproject/cuad`). Use the PDFs for ingestion and the labels
  (CUAD_v1.json / master_clauses.csv) as eval ground truth. Check the dataset license and
  credit it in the README.
- Use a 100-contract subset by default (var `doc_limit`, default 100; dev runs use 20).
- Synthetic overlay (generate with Faker, seeded): matters (matter_id, client, practice_area,
  matter_team), document→matter assignment, users→matter_team mapping, firm risk playbook
  (clause_type, rule, severity).

## Repo layout
```
matter-intelligence/
  databricks.yml                # bundle, targets: dev, demo
  resources/
    pipeline.yml                # Lakeflow declarative pipeline
    jobs.yml                    # setup, eval, sync jobs
    app.yml                     # Databricks App
  src/
    setup/
      00_download_cuad.py       # pulls CUAD into UC Volume /Volumes/{catalog}/raw/contracts
      01_generate_synthetic.py  # matters, users, playbook
      02_uc_governance.sql      # tags, masks, row filters, grants
    pipeline/
      bronze_documents.sql      # Auto Loader binaryFile from Volume
      silver_parsed.sql         # ai_parse_document
      gold_classified.sql       # ai_classify contract_type
      gold_clauses.sql          # ai_extract / ai_query structured JSON -> exploded clauses
      gold_risk_flags.sql       # join clauses to playbook
      gold_cost_metrics.sql     # tokens/pages per stage -> est. cost per 1K docs
    eval/
      build_eval_set.py         # CUAD labels -> eval table
      run_eval.py               # mlflow.genai.evaluate: per-clause precision/recall + judges
    lakebase/
      schema.sql                # review_queue, clause_reviews, audit_log
      setup_synced_tables.py    # gold_clauses -> Lakebase synced table
      sync_reviews_back.py      # Lakebase reviews -> Delta gold_reviewed_clauses
    genie/
      create_space.py           # create/update Genie space via API
      instructions.md           # curated instructions + clause definitions
      example_queries.sql       # 8-10 example SQL Q&A pairs
    app/
      app.yaml
      app.py                    # Streamlit reviewer workbench
      lakebase.py               # psycopg connection + review actions
      genie_client.py           # Genie Conversation API wrapper
  notebooks/                    # .ipynb committed WITH outputs (one per phase)
    01_setup_and_governance.ipynb
    02_pipeline_validation.ipynb
    03_eval.ipynb
    04_lakebase_roundtrip.ipynb
    05_genie_validation.ipynb
  scripts/
    export_evidence.py          # regenerates everything in /evidence from live workspace
  evidence/                     # TEXT execution evidence (see Execution Evidence section)
  tests/
  README.md                     # architecture diagram (mermaid), setup, demo script,
                                # trade-offs, results table linking to /evidence
```

## Unity Catalog design
Catalog: {catalog} (default `matter_intel`)
Schemas: raw (Volume + bronze), curated (silver/gold), serving (review tables), ml (models, eval)
Governance (02_uc_governance.sql):
- Tag `gold_clauses.party_name` and `silver_parsed.text` as `pii`; tag `privileged` on curated.
- Column mask: party_name shown as "Party ***" unless user in group `legal_reviewers_full`.
- Row filter on gold tables: user sees rows where matter_team IN their teams (via mapping table)
  OR is member of `legal_admins`.
- Grants: `legal_reviewers` SELECT curated; app service principal SELECT curated + USE on serving.

## Tables (key columns)
- bronze_documents: doc_id (sha256 of path), path, content (binary), size, ingested_at
- silver_parsed: doc_id, parsed (VARIANT from ai_parse_document), full_text, page_count,
  parse_status, parse_error
- gold_documents: doc_id, title, contract_type, contract_type_confidence, matter_id, matter_team
- gold_clauses: clause_id, doc_id, clause_type, extracted_value, normalized_value,
  source_snippet, confidence, model_name, extracted_at
  clause_type in: governing_law, effective_date, expiration_date, renewal_term,
  auto_renewal (bool), notice_period_days, liability_cap, uncapped_liability (bool),
  indemnification, termination_for_convenience, exclusivity, non_compete,
  assignment_restriction, parties
- gold_risk_flags: flag_id, clause_id, doc_id, rule_id, severity (high/med/low), reason
- gold_cost_metrics: run_id, stage, docs, pages, input_tokens, output_tokens, est_cost_usd,
  cost_per_1k_docs
- gold_reviewed_clauses (synced back from Lakebase)

Pipeline expectations: parse_status = 'ok'; full_text length > 200; clause confidence not null.
Process a configurable subset first (var `doc_limit`, default 50) to control cost.

## Gen AI
1. Parsing: ai_parse_document over bronze content.
2. Classification: ai_classify(full_text, ARRAY('MSA','NDA','SOW','License','Supply',
   'Distribution','Employment','Lease','Other')).
3. Extraction: single structured-output call per doc (ai_extract or ai_query with
   responseFormat JSON schema) covering all clause types; truncate/chunk long docs
   (first + key sections) and record truncation flag.
4. Risk explanations (gold_risk_flags.sql): rule-based flags from the playbook join, then
   ai_query writes a 1-2 sentence explanation citing the source_snippet for each
   high/medium flag. No separate serving endpoint.
   STRETCH: wrap this as an MLflow-traced agent served via Agent Framework.
5. Evaluation (run_eval.py):
   - Ground truth from CUAD labels mapped to our clause_types (write the mapping explicitly).
   - Metrics: per-clause precision/recall/F1 (presence), exact/fuzzy match on values.
   - LLM judge: explanation groundedness (is explanation supported by snippet?).
   - Evaluate ONE model fully and log cost per 1K docs alongside F1.
     STRETCH: compare a second, smaller model.
   - Output results to ml.eval_results, an MLflow experiment, AND evidence/04_eval_results.md
     + evidence/eval_results.json.

## Lakebase
schema.sql (Postgres):
- review_queue(clause_id PK, doc_id, clause_type, extracted_value, confidence, severity,
  status TEXT CHECK in ('pending','approved','overridden','auto_accepted'), assigned_to,
  updated_at)
- clause_reviews(review_id PK, clause_id, reviewer, action, old_value, new_value, comment,
  reviewed_at)
- audit_log(id, actor, action, entity, entity_id, ts)
Routing rule: confidence >= 0.9 AND no high-severity flag -> auto_accepted; else pending.
Use a synced table from gold_clauses + gold_risk_flags to populate review_queue; reviewer
writes go to clause_reviews; nightly job syncs clause_reviews back to Delta.

## Genie space
- Tables: gold_documents, gold_clauses, gold_risk_flags, gold_reviewed_clauses, matters.
- Instructions: clause_type definitions, "uncapped liability" = uncapped_liability = true,
  "upcoming renewals" = expiration_date within next N days AND auto_renewal = true,
  always prefer reviewed values over extracted when available.
- Example questions (with SQL): contracts auto-renewing next 90 days with uncapped liability;
  count of high-severity flags by contract_type; most common governing law; avg liability cap
  by contract type; documents pending review by matter team; override rate by clause_type
  (proxy for model weakness).

## Databricks App (reviewer workbench)
Streamlit on Databricks Apps; Lakebase and SQL Warehouse declared as app resources;
auth via app service principal (+ on-behalf-of user where supported).
Pages:
1. Portfolio overview — KPI cards (docs processed, clauses extracted, high-risk flags,
   % auto-accepted, cost per 1K docs), charts by contract type and severity.
2. Review queue — filterable table from Lakebase (status, severity, matter team).
3. Document detail — left: parsed text with highlighted source snippets; right: extracted
   clauses with confidence + risk explanation; Approve / Override (edit value + comment)
   buttons writing to Lakebase clause_reviews + updating review_queue.
4. Ask Genie — chat panel calling the Genie Conversation API for the configured space.
Non-functional: p95 review action < 300 ms; no secrets in code; respects UC row filters
for SQL-backed reads.

## Execution Evidence (REQUIRED — evaluator reads text only; screenshots do NOT count)
Commit text evidence at the end of every phase. scripts/export_evidence.py must be able to
regenerate all of it from the live workspace.
- Notebooks in /notebooks committed as .ipynb WITH outputs visible (run, then export;
  never strip outputs; no clearing via nbstripout or pre-commit hooks).
- evidence/run_log.txt — console output of `databricks bundle validate`, `bundle deploy`,
  and each `bundle run` (append per phase, with timestamps).
- evidence/01_uc_governance.md — SHOW GRANTS output; DESCRIBE TABLE EXTENDED showing tags,
  column mask and row filter; the same SELECT run as admin vs restricted test user
  (unmasked vs masked rows, row counts differ).
- evidence/02_pipeline_run.md — pipeline update ID + state, event-log excerpt
  (expectation pass/fail counts per table), row counts for every bronze/silver/gold table.
- evidence/03_sample_outputs.md — 10 real rows each of gold_documents, gold_clauses,
  gold_risk_flags (markdown tables, including AI-written explanations).
- evidence/04_eval_results.md + eval_results.json — per-clause precision/recall/F1,
  groundedness score, cost per 1K docs, MLflow experiment + run IDs.
- evidence/05_lakebase_roundtrip.md — review_queue row before override, POST/override
  action, review_queue + clause_reviews after, then the synced-back Delta row in
  gold_reviewed_clauses (timestamps showing the round trip).
- evidence/06_genie_transcript.md — 5+ real Genie questions with the generated SQL, the
  result rows, and the matching hand-written SQL result (pass/fail per question), including
  one question whose answer changed after the Lakebase override.
- evidence/07_app.md — `databricks apps get` output (status, URL redacted if needed) and
  logged app actions (from audit_log) proving the app was used end to end.
- evidence/roi_model.md — see ROI Model.

## ROI Model (evidence/roi_model.md)
Combine MEASURED values from the build with clearly labeled ASSUMPTIONS:
- Measured: docs processed, extraction F1 on key clauses, % auto-accepted, cost per 1K docs,
  # high-risk flags, # auto-renewing contracts within 90 days, # uncapped-liability contracts.
- Assumptions (table, each with a source or "illustrative"): contracts in portfolio (e.g.
  5,000), manual review minutes per contract (e.g. 45), AI-assisted review minutes (e.g. 8),
  fully loaded legal cost per hour (e.g. $150), % of auto-renewals that are unwanted (e.g. 10%),
  avg annual value of an unwanted renewal (e.g. $25K).
- Outputs: reviewer hours saved/yr, $ review cost saved, $ unwanted renewals avoided,
  platform cost (cost per 1K docs x volume), net value and payback.
Compute in a notebook (committed with outputs) and write the table to roi_model.md.

## Phases & acceptance criteria (stop for review after each; commit evidence each time)
- Phase 1 — Scaffold, data, UC, pipeline (~2.5h): bundle validates and deploys; CUAD subset in
  Volume; synthetic tables; governance applied; pipeline bronze→gold runs on doc_limit with
  expectations passing; cost metrics populated.
  Evidence: run_log.txt, 01_uc_governance.md, 02_pipeline_run.md, 03_sample_outputs.md.
- Phase 2 — Eval (~1h): eval logged to MLflow; per-clause F1 + groundedness computed.
  Evidence: 04_eval_results.md, eval_results.json, notebooks/03_eval.ipynb with outputs.
- Phase 3 — Lakebase + App (~2h): synced table populates review_queue; routing rule applied;
  Streamlit app deployed; approve/override writes to Lakebase; sync job lands it in Delta.
  Evidence: 05_lakebase_roundtrip.md, 07_app.md.
- Phase 4 — Genie, ROI, README (~1h): Genie space created; example questions validated against
  hand-written SQL; ROI model computed; README with mermaid diagram, setup, trade-offs, results
  table linking to /evidence, and dataset credit.
  Evidence: 06_genie_transcript.md, roi_model.md.
- Final check: run scripts/export_evidence.py, confirm every /evidence file is non-empty and
  every notebook has outputs, and grep the repo for real customer names before pushing.

## Demo script (for README)
1. Drop 10 new PDFs into the Volume → show pipeline pick-up.
2. Show lineage PDF → clause in Catalog Explorer; show masked view as a restricted user.
3. Show eval results: per-clause F1 and cost per 1K docs.
4. App: open a high-risk MSA, read the risk explanation, override a liability cap.
5. Genie: "Which contracts auto-renew in the next 90 days with uncapped liability?" — then
   show the answer reflects the override from step 4.

## Tips for using the spec
- Go one phase at a time and stop for review; it keeps cost and scope under control.
- Develop with doc_limit=20, then do the final run at 100. Skip the STRETCH items unless ahead of schedule.
- Check /evidence after every phase before moving on. If a file is empty or only describes what
  would happen, re-run and re-export. Real output is what passes the Build domain.
- Paste the measured numbers from 04_eval_results.md and roi_model.md over the outcome targets
  in Part 1 and into the deck.
- Keep the Claude Code session ID in case the build is flagged for review.
