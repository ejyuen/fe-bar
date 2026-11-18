"""Nightly: land reviewer decisions from Lakebase into Delta. Idempotent (MERGE on clause_id).

* {catalog}.curated.gold_reviewed_clauses  -- latest review per clause (row filter by matter team)
* {catalog}.serving.pg_review_queue / pg_clause_reviews / pg_audit_log  -- Delta mirrors of the
  Postgres tables (overwritten each run) for analytics and evidence
"""
import argparse
import datetime
import os
import sys

import pandas as pd
from pyspark.sql import SparkSession


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--src_dir", required=True)
    ap.add_argument("--pg_database", default="databricks_postgres")
    a, _ = ap.parse_known_args()  # tolerate extra args when a job overrides python params for all tasks
    sys.path.insert(0, f"{a.src_dir}/app")
    os.environ["LAKEBASE_INSTANCE"] = a.instance
    os.environ["PGDATABASE"] = a.pg_database
    import lakebase  # noqa: E402

    spark = SparkSession.builder.getOrCreate()
    conn = lakebase.connect()
    synced_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    def pg(q):
        with conn.cursor() as cur:
            cur.execute(q)
            rows = cur.fetchall()
        df = pd.DataFrame(rows)
        for c in df.columns:
            if pd.api.types.is_datetime64tz_dtype(df[c]):
                df[c] = df[c].dt.tz_convert("UTC").dt.tz_localize(None)
        return df

    mirrors = {
        "pg_review_queue": "SELECT clause_id, doc_id, doc_title, contract_type, matter_id, matter_team, clause_type, extracted_value, current_value, confidence, severity, top_rule_id, status, assigned_to, updated_at FROM review.review_queue",
        "pg_clause_reviews": "SELECT review_id, clause_id, reviewer, action, old_value, new_value, comment, reviewed_at FROM review.clause_reviews",
        "pg_audit_log": "SELECT id, actor, action, entity, entity_id, details::text AS details, duration_ms, ts FROM review.audit_log",
    }
    for name, q in mirrors.items():
        df = pg(q)
        sdf = spark.createDataFrame(df.astype(object).where(df.notna(), None)) if not df.empty else None
        if sdf is not None:
            sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"`{a.catalog}`.serving.{name}")
        print(f"{name}: {len(df)} rows mirrored")

    latest = pg("""SELECT DISTINCT ON (r.clause_id) r.review_id, r.clause_id, q.doc_id, q.clause_type, q.extracted_value,
                          r.new_value AS reviewed_value, r.action AS review_action, r.reviewer, r.comment AS review_comment,
                          r.reviewed_at, q.matter_team
                   FROM review.clause_reviews r JOIN review.review_queue q USING (clause_id)
                   ORDER BY r.clause_id, r.review_id DESC""")
    spark.sql(f"""CREATE TABLE IF NOT EXISTS `{a.catalog}`.curated.gold_reviewed_clauses (
        clause_id STRING, doc_id STRING, clause_type STRING, extracted_value STRING, reviewed_value STRING,
        review_action STRING, reviewer STRING, review_comment STRING, reviewed_at TIMESTAMP, review_id BIGINT,
        matter_team STRING, synced_at TIMESTAMP)
        COMMENT 'Reviewer decisions from Lakebase (latest per clause); prefer reviewed_value over extracted_value'""")
    if not latest.empty:
        latest["synced_at"] = synced_at
        spark.createDataFrame(latest.astype(object).where(latest.notna(), None)).createOrReplaceTempView("latest_reviews")
        spark.sql(f"""MERGE INTO `{a.catalog}`.curated.gold_reviewed_clauses t
            USING latest_reviews s ON t.clause_id = s.clause_id
            WHEN MATCHED AND s.review_id > t.review_id THEN UPDATE SET *
            WHEN NOT MATCHED THEN INSERT *""")
    spark.sql(f"ALTER TABLE `{a.catalog}`.curated.gold_reviewed_clauses SET ROW FILTER `{a.catalog}`.curated.matter_team_filter ON (matter_team)")
    n = spark.sql(f"SELECT count(*) FROM `{a.catalog}`.curated.gold_reviewed_clauses").first()[0]
    print(f"gold_reviewed_clauses rows: {n} (latest reviews in Lakebase: {len(latest)}) synced_at={synced_at}")


if __name__ == "__main__":
    main()
