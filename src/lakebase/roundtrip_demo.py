"""Scripted reviewer round trip (same code path as the app's Override button) + latency probe.

Default: picks a pending liability_cap clause on a document with a high-severity flag (or the
--clause_type clause on the document matching --doc_title_like), records the
review_queue row before, performs an override through lakebase.override(), records review_queue
and clause_reviews after, and measures review-action latency with 30 rolled-back (dry-run)
approve transactions. Everything is written to {catalog}.ml.roundtrip_evidence.
"""
import argparse
import datetime
import json
import os
import statistics
import sys

from pyspark.sql import SparkSession


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--src_dir", required=True)
    ap.add_argument("--pg_database", default="databricks_postgres")
    ap.add_argument("--new_value", default="USD 1,000,000 aggregate cap (reviewer override)")
    ap.add_argument("--clause_type", default="liability_cap")
    ap.add_argument("--doc_title_like", default="", help="pick the clause on a document whose title matches (ILIKE)")
    ap.add_argument("--comment", default="Round-trip demo: cap confirmed with counterparty at USD 1M")
    ap.add_argument("--skip_latency", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, f"{a.src_dir}/app")
    os.environ["LAKEBASE_INSTANCE"] = a.instance
    os.environ["PGDATABASE"] = a.pg_database
    import lakebase  # noqa: E402

    spark = SparkSession.builder.getOrCreate()
    conn = lakebase.connect()
    me = spark.sql("SELECT current_user()").first()[0]
    run_id = datetime.datetime.utcnow().strftime(f"rt-{a.clause_type}-%Y%m%d-%H%M%S")
    ev = []

    def rec(step, payload):
        payload = json.loads(json.dumps(payload, default=str))
        ev.append((run_id, len(ev) + 1, step, datetime.datetime.utcnow(), json.dumps(payload, indent=1)))
        print(f"== {step}\n{json.dumps(payload, indent=1)[:2000]}")

    with conn.cursor() as cur:
        if a.doc_title_like:
            cur.execute("SELECT clause_id FROM review.review_queue WHERE clause_type = %s AND doc_title ILIKE %s ORDER BY clause_id LIMIT 1",
                        [a.clause_type, a.doc_title_like])
            row = cur.fetchone()
        else:
            cur.execute("""SELECT q.clause_id FROM review.review_queue q
                           WHERE q.clause_type = %s AND q.status = 'pending'
                             AND EXISTS (SELECT 1 FROM review.review_queue h WHERE h.doc_id = q.doc_id AND h.severity = 'high')
                           ORDER BY q.clause_id LIMIT 1""", [a.clause_type])
            row = cur.fetchone()
            if row is None:
                cur.execute("SELECT clause_id FROM review.review_queue WHERE clause_type = %s ORDER BY status DESC, clause_id LIMIT 1",
                            [a.clause_type])
                row = cur.fetchone()
    cid = row["clause_id"]
    before = lakebase.get_clause(conn, cid)
    rec("1_review_queue_before", {k: before[k] for k in ("clause_id", "doc_id", "doc_title", "contract_type", "matter_team",
                                                        "clause_type", "current_value", "confidence", "severity",
                                                        "status", "updated_at")})
    req = {"function": "lakebase.override", "clause_id": cid, "reviewer": me, "new_value": a.new_value,
           "comment": a.comment}
    res = lakebase.override(conn, cid, me, a.new_value, req["comment"])
    rec("2_override_action", {"request": req, "response": res})
    after = lakebase.get_clause(conn, cid)
    rec("3_review_queue_after", {k: after[k] for k in ("clause_id", "current_value", "status", "updated_at")})
    rec("4_clause_reviews_after", lakebase.reviews_for(conn, cid))

    # latency probe: full approve transaction on auto-accepted clauses, rolled back (no data change)
    probe_ids = []
    if not a.skip_latency:
        with conn.cursor() as cur:
            cur.execute("SELECT clause_id FROM review.review_queue WHERE status = 'auto_accepted' ORDER BY clause_id LIMIT 30")
            probe_ids = [r["clause_id"] for r in cur.fetchall()]
    lat = [lakebase.approve(conn, p, me, "latency probe", dry_run=True)["duration_ms"] for p in probe_ids]
    lat_sorted = sorted(lat)
    p95 = lat_sorted[max(0, int(round(0.95 * len(lat_sorted))) - 1)] if lat_sorted else None
    if lat:
        rec("5_latency_probe", {"n": len(lat), "p50_ms": statistics.median(lat), "p95_ms": p95, "max_ms": max(lat),
                                "target_p95_ms": 300,
                                "method": "approve() transaction (SELECT FOR UPDATE, INSERT review, UPDATE queue) rolled back"})

    spark.sql(f"""CREATE TABLE IF NOT EXISTS `{a.catalog}`.ml.roundtrip_evidence
                  (run_id STRING, step_no INT, step STRING, ts TIMESTAMP, payload STRING)""")
    spark.createDataFrame(ev, "run_id string, step_no int, step string, ts timestamp, payload string") \
        .write.mode("append").saveAsTable(f"`{a.catalog}`.ml.roundtrip_evidence")
    print("round trip", run_id, "clause", cid)


if __name__ == "__main__":
    main()
