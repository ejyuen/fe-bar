"""Validate Genie answers against hand-written SQL and record a transcript in ml.genie_validation.

For each question: ask Genie (Conversation API, as the caller), capture the generated SQL and result
rows, run the hand-written SQL, and compare result sets. PASS = same number of rows and every
hand-written row's values appear in a Genie row (Genie may add extra columns; order ignored;
numbers compared to 2 decimals, strings case-insensitively).

Run: python src/genie/validate.py --catalog <cat> --warehouse_id <id> --space_id <id> --tag before
"""
import argparse
import datetime
import json
import os
import sys
import time

from databricks.sdk import WorkspaceClient

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import genie_client  # noqa: E402

# (question asked to Genie, hand-written SQL). Q1 is the demo question whose answer changes after
# the Lakebase override; Q5-Q7 are phrased differently from the space's curated examples.
QUESTIONS = [
    ("Which contracts auto-renew in the next 90 days with uncapped liability?",
     """SELECT title FROM ${catalog}.curated.contract_terms_current
        WHERE auto_renewal AND uncapped_liability AND next_renewal_date BETWEEN current_date() AND date_add(current_date(), 90)"""),
    ("Count of high-severity flags by contract type",
     """SELECT d.contract_type, count(*) FROM ${catalog}.curated.gold_risk_flags f JOIN ${catalog}.curated.gold_documents d USING (doc_id)
        WHERE f.severity = 'high' GROUP BY 1"""),
    ("What is the most common governing law?",
     """SELECT governing_law FROM ${catalog}.curated.contract_terms_current WHERE governing_law IS NOT NULL
        GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"""),
    ("Documents pending review by matter team",
     """SELECT matter_team, count(DISTINCT doc_id) FROM ${catalog}.serving.pg_review_queue WHERE status = 'pending' GROUP BY 1"""),
    ("For each clause type that reviewers have touched, what share of decisions were overrides?",
     """SELECT clause_type, round(count_if(review_action = 'override') / count(*), 2) FROM ${catalog}.curated.gold_reviewed_clauses GROUP BY 1"""),
    ("How many contracts does each matter team own?",
     """SELECT matter_team, count(*) FROM ${catalog}.curated.gold_documents GROUP BY 1"""),
    ("List the auto-renewing contracts and their next renewal date",
     """SELECT title, next_renewal_date FROM ${catalog}.curated.contract_terms_current WHERE auto_renewal"""),
]


def run_sql(w, wh, stmt):
    r = w.statement_execution.execute_statement(warehouse_id=wh, statement=stmt, wait_timeout="50s")
    while r.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(r.status.error.message if r.status.error else r.status.state.value)
    cols = [c.name for c in r.manifest.schema.columns]
    return cols, [list(x) for x in (r.result.data_array or [])]


def norm(v):
    if v is None:
        return ""
    s = str(v).strip()
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return s.lower()


def compare(hand_rows, genie_rows):
    if len(hand_rows) != len(genie_rows):
        return False, f"row count differs (hand {len(hand_rows)} vs genie {len(genie_rows)})"
    pool = [[norm(v) for v in r] for r in genie_rows]
    for hr in hand_rows:
        want = [norm(v) for v in hr]
        hit = next((i for i, g in enumerate(pool) if all(g.count(x) >= want.count(x) for x in want)), None)
        if hit is None:
            return False, f"no Genie row contains {want}"
        pool.pop(hit)
    return True, "same rows"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--warehouse_id", required=True)
    ap.add_argument("--space_id", required=True)
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--only", type=int, nargs="*", help="1-based question numbers")
    a = ap.parse_args()
    w = WorkspaceClient(profile=os.environ.get("DATABRICKS_CONFIG_PROFILE"))
    run_id = datetime.datetime.utcnow().strftime(f"genie-{a.tag}-%Y%m%d-%H%M%S")
    rows = []
    for i, (question, hand) in enumerate(QUESTIONS, 1):
        if a.only and i not in a.only:
            continue
        hand_sql = " ".join(hand.replace("${catalog}", a.catalog).split())
        t0 = time.time()
        try:
            ans = genie_client.ask(w, a.space_id, question)
        except Exception as e:  # noqa: BLE001
            ans = {"sql": None, "columns": [], "rows": [], "text": None, "error": str(e)[:500], "status": "ERROR",
                   "conversation_id": None, "message_id": None}
        secs = round(time.time() - t0, 1)
        hcols, hrows = run_sql(w, a.warehouse_id, hand_sql)
        ok, why = compare(hrows, ans.get("rows") or []) if ans.get("sql") else (False, f"Genie returned no SQL: {ans.get('error') or ans.get('text')}")
        print(f"[{'PASS' if ok else 'FAIL'}] Q{i} {question} ({secs}s) - {why}")
        rows.append((run_id, a.tag, i, question, ans.get("status"), ans.get("conversation_id"), ans.get("message_id"),
                     ans.get("sql"), json.dumps(ans.get("columns")), json.dumps(ans.get("rows"), default=str),
                     ans.get("text"), hand_sql, json.dumps(hcols), json.dumps(hrows, default=str), ok, why, secs,
                     datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    lit = lambda v: "NULL" if v is None else ("true" if v is True else "false" if v is False else (repr(v) if isinstance(v, (int, float)) else "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"))  # noqa: E731
    run_sql(w, a.warehouse_id, f"""CREATE TABLE IF NOT EXISTS {a.catalog}.ml.genie_validation (
        run_id STRING, tag STRING, q_no INT, question STRING, genie_status STRING, conversation_id STRING, message_id STRING,
        genie_sql STRING, genie_columns STRING, genie_rows STRING, genie_text STRING, hand_sql STRING, hand_columns STRING,
        hand_rows STRING, pass BOOLEAN, reason STRING, genie_seconds DOUBLE, ts TIMESTAMP)""")
    vals = ",\n".join("(" + ", ".join(lit(v) for v in r[:-1]) + f", timestamp'{r[-1]}')" for r in rows)
    run_sql(w, a.warehouse_id, f"INSERT INTO {a.catalog}.ml.genie_validation VALUES\n{vals}")
    print(f"run {run_id}: {sum(r[14] for r in rows)}/{len(rows)} pass")


if __name__ == "__main__":
    main()
