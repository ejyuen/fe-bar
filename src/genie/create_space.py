"""Create or update the Matter Intelligence Genie space (idempotent, matched by title).

1. (Re)create the query-time view curated.contract_terms_current (views.sql)
2. Build the serialized space: tables, text instructions (instructions.md), curated example
   question/SQL pairs (example_queries.sql) and sample questions
3. create_space / update_space via the Genie API; prints the space id. Set the bundle variable
   genie_space_id to it and redeploy the app.

Run: python src/genie/create_space.py --catalog <cat> --warehouse_id <id>   (CLI profile auth)
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

from databricks.sdk import WorkspaceClient

HERE = os.path.dirname(os.path.abspath(__file__))
TITLE = "Matter Intelligence - Contract Portfolio"

TABLES = {
    "curated.contract_terms_current": "One row per contract with current key terms; reviewed values preferred; next_renewal_date rolls evergreen terms forward.",
    "curated.gold_clauses": "One row per AI-extracted clause (ai_extract v2.1) with confidence and source snippet.",
    "curated.gold_documents": "One row per contract: title, contract_type (ai_classify), matter assignment.",
    "curated.gold_reviewed_clauses": "Reviewer approve/override decisions synced from Lakebase (latest per clause).",
    "curated.gold_risk_flags": "Firm playbook risk flags with AI-written explanations.",
    "curated.matters": "Synthetic matters (client, practice area, matter team).",
    "curated.risk_playbook": "Firm risk playbook rules (rule_id, clause_type, severity, rule_text).",
    "serving.pg_review_queue": "Snapshot of the Lakebase review queue (status pending / auto_accepted / approved / overridden).",
}
SAMPLE_QUESTIONS = [
    "Which contracts auto-renew in the next 90 days with uncapped liability?",
    "Count of high-severity flags by contract type",
    "What is the most common governing law?",
    "Documents pending review by matter team",
    "Override rate by clause type",
]


def hid(*parts):
    return hashlib.md5("|".join(parts).encode()).hexdigest()  # 32 lowercase hex chars


def parse_examples(path, catalog):
    text = open(path).read().replace("${catalog}", catalog)
    out = []
    for m in re.finditer(r"--\s*Q:\s*(.+?)\n(.*?;)", text, re.S):
        sql = m.group(2).strip().rstrip(";")
        out.append((m.group(1).strip(), sql))
    return out


def run_sql(w, warehouse_id, stmt):
    r = w.statement_execution.execute_statement(warehouse_id=warehouse_id, statement=stmt, wait_timeout="50s")
    while r.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(r.status.error.message if r.status.error else r.status.state.value)


def build_space(catalog):
    ex = parse_examples(os.path.join(HERE, "example_queries.sql"), catalog)
    lines = [ln + "\n" for ln in open(os.path.join(HERE, "instructions.md")).read().splitlines()]
    space = {
        "version": 2,
        "config": {"sample_questions": sorted(
            [{"id": hid("sample", q), "question": [q]} for q in SAMPLE_QUESTIONS], key=lambda x: x["id"])},
        "data_sources": {"tables": sorted(
            [{"identifier": f"{catalog}.{t}", "description": [d]} for t, d in TABLES.items()], key=lambda x: x["identifier"])},
        "instructions": {
            "text_instructions": [{"id": hid("instructions"), "content": lines}],
            "example_question_sqls": sorted(
                [{"id": hid("example", q), "question": [q], "sql": [ln + "\n" for ln in s.splitlines()]} for q, s in ex],
                key=lambda x: x["id"]),
        },
    }
    return space, ex


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--warehouse_id", required=True)
    a = ap.parse_args()
    w = WorkspaceClient(profile=os.environ.get("DATABRICKS_CONFIG_PROFILE"))
    run_sql(w, a.warehouse_id, open(os.path.join(HERE, "views.sql")).read().replace("${catalog}", a.catalog))
    print("view curated.contract_terms_current created")

    space, ex = build_space(a.catalog)
    payload = json.dumps(space)
    me = w.current_user.me().user_name
    existing = None
    token = None
    while True:
        resp = w.genie.list_spaces(page_token=token)
        for s in resp.spaces or []:
            if s.title == TITLE:
                existing = s
        token = resp.next_page_token
        if not token or existing:
            break
    desc = ("Contract portfolio Q&A over AI-extracted clauses, risk flags and reviewer decisions "
            "(CUAD v1 public contracts, CC BY 4.0, with a synthetic matter overlay).")
    if existing:
        sp = w.genie.update_space(existing.space_id, serialized_space=payload, title=TITLE, description=desc,
                                  warehouse_id=a.warehouse_id)
        print("updated Genie space", sp.space_id)
    else:
        sp = w.genie.create_space(a.warehouse_id, payload, title=TITLE, description=desc, parent_path=f"/Users/{me}")
        print("created Genie space", sp.space_id)
    print(f"tables={len(space['data_sources']['tables'])} examples={len(ex)} sample_questions={len(SAMPLE_QUESTIONS)}")
    print(f"GENIE_SPACE_ID={sp.space_id}")
    return sp.space_id


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
