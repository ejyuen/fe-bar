"""Build and EXECUTE the phase notebooks so they are committed with real outputs.

Usage: .venv/bin/python scripts/build_notebooks.py 01 02
Each notebook talks to the live workspace through scripts/dbx.py (SQL warehouse + SDK).
"""
import os
import sys

import nbformat
from nbclient import NotebookClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRELUDE = """import sys, os
sys.path.insert(0, os.path.abspath('../scripts'))
import pandas as pd
pd.set_option('display.max_colwidth', 120); pd.set_option('display.width', 200)
from dbx import sql, ws, CATALOG
print('workspace:', ws().config.host, '| catalog:', CATALOG, '| user:', ws().current_user.me().user_name)"""

NOTEBOOKS = {
    "01": ("01_setup_and_governance.ipynb", "# 01 - Setup and governance\nValidates the CUAD staging, synthetic overlay and Unity Catalog governance (masks, row filter, tags) against the live workspace.", [
        "sql(\"SELECT file_name, cuad_category FROM ${catalog}.raw.cuad_manifest ORDER BY cuad_category, file_name\")",
        "sql(\"LIST '/Volumes/${catalog}/raw/contracts/pdfs/'\")[['name','size']].head(25)",
        "sql(\"LIST '/Volumes/${catalog}/raw/contracts/labels/'\")[['name','size']]",
        "sql(\"SELECT * FROM ${catalog}.curated.matters ORDER BY matter_seq\")",
        "sql(\"SELECT * FROM ${catalog}.curated.user_team_mapping ORDER BY matter_team\")",
        "sql(\"SELECT * FROM ${catalog}.curated.risk_playbook ORDER BY rule_id\")",
        "sql(\"SELECT section, status, statement, error FROM ${catalog}.curated.governance_log ORDER BY ts DESC LIMIT 20\")",
        "sql(\"SHOW USER FUNCTIONS IN ${catalog}.curated\")",
        "d = sql(\"DESCRIBE TABLE EXTENDED ${catalog}.curated.gold_clauses\")\nd[d['col_name'].str.contains('Mask|Row Filter|party_name|extracted_value|Tags', case=False, regex=True)]",
        "sql(\"SELECT schema_name, table_name, column_name, tag_name, tag_value FROM ${catalog}.information_schema.column_tags\")",
        "sql(\"SELECT schema_name, tag_name, tag_value FROM ${catalog}.information_schema.schema_tags\")",
        "# As the current (admin) user: all matter teams visible, party names unmasked\nsql(\"SELECT current_user() u, is_member('legal_admins') admin, is_member('legal_reviewers_full') full_reviewer\")",
        "sql(\"SELECT matter_team, count(*) docs, min(party_name) sample_party FROM ${catalog}.curated.gold_documents GROUP BY 1 ORDER BY 1\")",
    ]),
    "02": ("02_pipeline_validation.ipynb", "# 02 - Pipeline validation\nRow counts, expectations and sample gold output from the Lakeflow declarative pipeline.", [
        "from export_evidence import pipeline_id\npid, name = pipeline_id(); print(pid, name)\nups = ws().pipelines.list_updates(pid, max_results=5).updates\npd.DataFrame([{'update_id': u.update_id, 'state': u.state.value, 'full_refresh': u.full_refresh} for u in ups])",
        "from export_evidence import TABLES\nsql(' UNION ALL '.join(\"SELECT '%s' t, count(*) n FROM ${catalog}.%s\" % (t, t) for t in TABLES))",
        "sql(f\"\"\"WITH ev AS (SELECT origin.update_id, explode(from_json(details:flow_progress.data_quality.expectations::string,\n 'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>')) e\n FROM event_log('{pid}') WHERE event_type='flow_progress' AND details:flow_progress.data_quality.expectations IS NOT NULL)\nSELECT update_id, e.dataset, e.name, sum(e.passed_records) passed, sum(e.failed_records) failed FROM ev GROUP BY ALL ORDER BY 1,2,3\"\"\")",
        "sql(\"SELECT doc_id, page_count, parse_status, length(full_text) chars, parse_error FROM ${catalog}.curated.silver_parsed ORDER BY doc_id\")",
        "sql(\"SELECT contract_type, count(*) docs, round(avg(contract_type_confidence),3) conf FROM ${catalog}.curated.gold_documents GROUP BY 1 ORDER BY 2 DESC\")",
        "sql(\"SELECT clause_type, count(*) n, round(avg(confidence),3) conf FROM ${catalog}.curated.gold_clauses GROUP BY 1 ORDER BY 1\")",
        "sql(\"SELECT clause_type, normalized_value, round(confidence,2) conf, left(source_snippet, 150) snippet FROM ${catalog}.curated.gold_clauses WHERE clause_type IN ('governing_law','auto_renewal','uncapped_liability','notice_period_days') ORDER BY doc_id, clause_type LIMIT 12\")",
        "sql(\"SELECT severity, rule_id, count(*) flags, count(explanation) explained FROM ${catalog}.curated.gold_risk_flags GROUP BY ALL ORDER BY 1,2\")",
        "sql(\"SELECT rule_id, severity, left(explanation, 300) explanation FROM ${catalog}.curated.gold_risk_flags WHERE explanation IS NOT NULL LIMIT 5\")",
        "sql(\"SELECT * FROM ${catalog}.curated.gold_cost_metrics ORDER BY run_id, stage\")",
    ]),
    "03": ("03_eval.ipynb", "# 03 - Evaluation\nExtraction quality vs CUAD v1 expert labels and LLM-judged groundedness of risk explanations. The eval itself runs as the bundle job `eval_job` (serverless); this notebook reads the logged results from Unity Catalog and the MLflow run.", [
        "sql(\"SELECT clause_type, basis, count(*) docs, count_if(gt_present) gt_present FROM ${catalog}.ml.eval_ground_truth GROUP BY ALL ORDER BY 1\")",
        "from export_evidence import latest_eval_run\nrun_id, exp_id, ts = latest_eval_run(); print('MLflow experiment', exp_id, '| run', run_id, '| at', ts)\nrun = ws().experiments.get_run(run_id).run\nprint(run.info.run_name, run.info.status)\npd.DataFrame([(m.key, m.value) for m in run.data.metrics if '.' not in m.key], columns=['metric','value']).sort_values('metric')",
        "sql(f\"SELECT clause_type, tp, fp, fn, round(precision,3) p, round(recall,3) r, round(f1,3) f1, value_compared, round(exact_match_rate,3) exact, round(fuzzy_match_rate,3) fuzzy FROM {CATALOG}.ml.eval_results WHERE mlflow_run_id = '{run_id}' AND clause_type <> '__summary__' ORDER BY f1\")",
        "sql(f\"SELECT metric_name, round(metric_value,4) value FROM {CATALOG}.ml.eval_results WHERE mlflow_run_id = '{run_id}' AND clause_type = '__summary__' ORDER BY 1\")",
        "sql(\"SELECT clause_type, gt_answer, predicted_value, exact_match, fuzzy_match FROM ${catalog}.ml.eval_details WHERE clause_type IN ('governing_law','expiration_date','notice_period_days') AND exact_match IS NOT NULL ORDER BY clause_type LIMIT 15\")",
        "sql(\"SELECT grounded, count(*) n FROM ${catalog}.ml.eval_groundedness GROUP BY 1\")",
        "sql(\"SELECT g.rule_id, left(g.explanation, 200) explanation, left(e.rationale, 220) rationale FROM ${catalog}.ml.eval_groundedness e JOIN ${catalog}.curated.gold_risk_flags g USING (flag_id) WHERE NOT e.grounded LIMIT 5\")",
        "sql(\"SELECT stage, docs, pages, input_tokens, output_tokens, est_cost_usd, cost_per_1k_docs FROM ${catalog}.curated.gold_cost_metrics ORDER BY stage\")",
    ]),
}


def build(key):
    fname, intro, cells = NOTEBOOKS[key]
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "fe-bar", "display_name": "fe-bar (3.11)", "language": "python"}
    nb.cells = [nbformat.v4.new_markdown_cell(intro), nbformat.v4.new_code_cell(PRELUDE)] + \
               [nbformat.v4.new_code_cell(c) for c in cells]
    path = os.path.join(ROOT, "notebooks", fname)
    NotebookClient(nb, timeout=900, kernel_name="fe-bar", allow_errors=True,
                   resources={"metadata": {"path": os.path.join(ROOT, "notebooks")}}).execute()
    nbformat.write(nb, path)
    errs = [o for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", []) if o.output_type == "error"]
    print(f"{path}: {len(nb.cells)} cells, {len(errs)} error outputs")
    for e in errs:
        print("   ", e.ename, str(e.evalue)[:200])


if __name__ == "__main__":
    for k in sys.argv[1:]:
        build(k)
