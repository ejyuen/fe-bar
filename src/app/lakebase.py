"""Lakebase (Postgres) access + review actions, shared by the reviewer app (FastAPI) and the bundle jobs.

Auth: a short-lived Postgres credential is generated with the Databricks SDK for the *current
identity* (the app's service principal inside Databricks Apps, the job's run-as identity in jobs).
Nothing is hard-coded; credentials are refreshed before they expire.
"""
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg.rows import dict_row

_CRED_TTL_S = 45 * 60
# One connection per thread (FastAPI runs sync endpoints in a thread pool; psycopg connections
# must not be shared across threads concurrently).
_local = threading.local()

QUEUE_COLS = ["clause_id", "doc_id", "doc_title", "contract_type", "matter_id", "matter_team", "clause_type",
              "extracted_value", "normalized_value", "source_snippet", "confidence", "severity", "top_rule_id",
              "risk_explanation"]


def _settings(w: WorkspaceClient):
    instance = os.environ.get("LAKEBASE_INSTANCE", "matter-intel-lakebase")
    host = os.environ.get("PGHOST")
    if not host:
        host = w.database.get_database_instance(instance).read_write_dns
    user = os.environ.get("PGUSER") or os.environ.get("DATABRICKS_CLIENT_ID") or w.current_user.me().user_name
    return dict(instance=instance, host=host, user=user,
                dbname=os.environ.get("PGDATABASE", "databricks_postgres"),
                port=int(os.environ.get("PGPORT", "5432")))


def connect(w: WorkspaceClient | None = None) -> psycopg.Connection:
    """Return a cached autocommit connection, reconnecting with a fresh credential when old."""
    c = getattr(_local, "conn", None)
    if c is not None and not c.closed and time.time() - _local.born < _CRED_TTL_S:
        return c
    if c is not None and not c.closed:
        c.close()
    w = w or WorkspaceClient()
    s = _settings(w)
    cred = w.database.generate_database_credential(request_id=str(uuid.uuid4()), instance_names=[s["instance"]])
    c = psycopg.connect(host=s["host"], port=s["port"], dbname=s["dbname"], user=s["user"],
                        password=cred.token, sslmode="require", autocommit=True, row_factory=dict_row,
                        application_name="matter-intelligence")
    _local.conn, _local.born = c, time.time()
    return c


@contextmanager
def tx(conn):
    with conn.transaction():
        with conn.cursor() as cur:
            yield cur


def run_script(conn, sql_text: str):
    with conn.cursor() as cur:
        cur.execute(sql_text)


# ----------------------------------------------------------------------------- queue population
def refresh_queue_from_synced(conn, synced_table: str = "serving.review_queue_synced") -> dict:
    """Upsert the app queue from the synced table. Reviewer decisions (approved/overridden) are kept."""
    cols = ", ".join(QUEUE_COLS)
    upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in QUEUE_COLS if c != "clause_id")
    with tx(conn) as cur:
        cur.execute(f"""
            INSERT INTO review.review_queue ({cols}, status, current_value, assigned_to, updated_at)
            SELECT {cols}, initial_status, normalized_value,
                   CASE WHEN initial_status = 'pending' THEN matter_team || ' queue' END, now()
            FROM {synced_table}
            ON CONFLICT (clause_id) DO UPDATE SET {upd},
              status = CASE WHEN review.review_queue.status IN ('approved', 'overridden')
                            THEN review.review_queue.status ELSE EXCLUDED.status END,
              current_value = CASE WHEN review.review_queue.status IN ('approved', 'overridden')
                            THEN review.review_queue.current_value ELSE EXCLUDED.current_value END,
              updated_at = CASE WHEN review.review_queue.status IN ('approved', 'overridden')
                            THEN review.review_queue.updated_at ELSE now() END""")
        cur.execute("SELECT status, count(*) AS n FROM review.review_queue GROUP BY status ORDER BY status")
        return {r["status"]: r["n"] for r in cur.fetchall()}


# ----------------------------------------------------------------------------- reads
def list_queue(conn, status=None, severity=None, matter_team=None, limit=500):
    where, args = [], []
    for col, val in (("status", status), ("severity", severity), ("matter_team", matter_team)):
        if val:
            where.append(f"{col} = ANY(%s)")
            args.append(list(val) if isinstance(val, (list, tuple)) else [val])
    q = ("SELECT clause_id, doc_id, doc_title, contract_type, matter_team, clause_type, current_value, "
         "confidence, severity, status, assigned_to, updated_at FROM review.review_queue"
         + (" WHERE " + " AND ".join(where) if where else "")
         + " ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, "
           "confidence, clause_id LIMIT %s")
    with conn.cursor() as cur:
        cur.execute(q, args + [limit])
        return cur.fetchall()


def list_documents(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT doc_id, max(doc_title) AS doc_title, max(contract_type) AS contract_type,
                              max(matter_id) AS matter_id, max(matter_team) AS matter_team, count(*) AS clauses,
                              count(*) FILTER (WHERE status = 'pending') AS pending,
                              count(*) FILTER (WHERE status IN ('approved', 'overridden')) AS reviewed,
                              max(CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END) AS sev_rank,
                              max(updated_at) AS updated_at
                       FROM review.review_queue GROUP BY doc_id
                       ORDER BY sev_rank DESC, pending DESC, doc_title""")
        return cur.fetchall()


def doc_clauses(conn, doc_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM review.review_queue WHERE doc_id = %s ORDER BY clause_type", [doc_id])
        return cur.fetchall()


def get_clause(conn, clause_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM review.review_queue WHERE clause_id = %s", [clause_id])
        return cur.fetchone()


def reviews_for(conn, clause_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM review.clause_reviews WHERE clause_id = %s ORDER BY review_id", [clause_id])
        return cur.fetchall()


def queue_stats(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) AS clauses, count(*) FILTER (WHERE status = 'auto_accepted') AS auto_accepted,
                              count(*) FILTER (WHERE status = 'pending') AS pending,
                              count(*) FILTER (WHERE status IN ('approved', 'overridden')) AS reviewed
                       FROM review.review_queue""")
        return cur.fetchone()


# ----------------------------------------------------------------------------- writes
def log_action(conn, actor, action, entity=None, entity_id=None, details=None, duration_ms=None):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO review.audit_log (actor, action, entity, entity_id, details, duration_ms) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [actor, action, entity, entity_id, json.dumps(details) if details is not None else None, duration_ms])


def _review(conn, clause_id, reviewer, action, new_value, comment, dry_run=False):
    t0 = time.perf_counter()
    status = "approved" if action == "approve" else "overridden"
    result = None
    with conn.transaction() as t:
        with conn.cursor() as cur:
            cur.execute("SELECT current_value FROM review.review_queue WHERE clause_id = %s FOR UPDATE", [clause_id])
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"unknown clause_id {clause_id}")
            old = row["current_value"]
            new = old if action == "approve" else new_value
            cur.execute("INSERT INTO review.clause_reviews (clause_id, reviewer, action, old_value, new_value, comment) "
                        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING review_id, reviewed_at",
                        [clause_id, reviewer, action, old, new, comment])
            rev = cur.fetchone()
            cur.execute("UPDATE review.review_queue SET status = %s, current_value = %s, updated_at = now() "
                        "WHERE clause_id = %s", [status, new, clause_id])
            result = {"review_id": rev["review_id"], "reviewed_at": rev["reviewed_at"].isoformat(),
                      "old_value": old, "new_value": new, "status": status}
            if dry_run:
                raise psycopg.Rollback(t)  # exits the transaction block with a rollback
    ms = (time.perf_counter() - t0) * 1000
    if not dry_run:
        log_action(conn, reviewer, action, "clause", clause_id, {"new_value": result["new_value"], "comment": comment}, ms)
    return {**(result or {}), "duration_ms": round(ms, 2), "dry_run": dry_run}


def approve(conn, clause_id, reviewer, comment=None, dry_run=False):
    return _review(conn, clause_id, reviewer, "approve", None, comment, dry_run)


def override(conn, clause_id, reviewer, new_value, comment, dry_run=False):
    return _review(conn, clause_id, reviewer, "override", new_value, comment, dry_run)
