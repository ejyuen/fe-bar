"""Create/refresh the Lakebase synced table and populate the app review queue. Idempotent.

1. Postgres schema (schema.sql) on the Lakebase instance
2. Synced table  {catalog}.serving.review_queue_synced  <-  Delta {catalog}.serving.review_queue_source
   (SNAPSHOT policy; created once, refreshed on later runs) and wait until it is online
3. Upsert review.review_queue from the synced table (routing rule applied upstream, reviewer
   decisions preserved)
4. Grants: app service principal -> Postgres tables, and UC USE/SELECT on curated + serving
"""
import argparse
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.database import (SyncedDatabaseTable, SyncedTableSchedulingPolicy,
                                             SyncedTableSpec)


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--app_name", default="")
    ap.add_argument("--src_dir", required=True, help="bundle src/ directory in the workspace")
    ap.add_argument("--pg_database", default="databricks_postgres")
    return ap.parse_args()


def wait_synced(w, name, timeout_s=1800):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        t = w.database.get_synced_database_table(name)
        st = t.data_synchronization_status
        state = st.detailed_state.value if st and st.detailed_state else None
        print(f"  synced table state: {state} ({st.message if st else ''})")
        if state and ("ONLINE" in state and "PROVISIONING" not in state and "UPDATING" not in state.replace("ONLINE_", "")):
            return t
        if state and "FAILED" in state:
            raise RuntimeError(f"synced table failed: {st.message}")
        time.sleep(20)
    raise TimeoutError("synced table did not come online")


def main():
    a = parse()
    sys.path.insert(0, f"{a.src_dir}/app")
    import os
    os.environ["LAKEBASE_INSTANCE"] = a.instance
    os.environ["PGDATABASE"] = a.pg_database
    import lakebase  # noqa: E402

    w = WorkspaceClient()
    inst = w.database.get_database_instance(a.instance)
    print(f"Lakebase instance {inst.name}: state={inst.state}, capacity={inst.capacity}")

    conn = lakebase.connect(w)
    lakebase.run_script(conn, open(f"{a.src_dir}/lakebase/schema.sql").read())
    print("schema.sql applied")

    name = f"{a.catalog}.serving.review_queue_synced"
    try:
        t = w.database.get_synced_database_table(name)
        pid = t.data_synchronization_status.pipeline_id
        print(f"synced table exists (pipeline {pid}); triggering snapshot refresh")
        w.pipelines.start_update(pid)
        time.sleep(30)
    except Exception as e:  # noqa: BLE001
        if "does not exist" not in str(e).lower() and "not found" not in str(e).lower():
            raise
        print("creating synced table", name)
        w.database.create_synced_database_table(SyncedDatabaseTable(
            name=name, database_instance_name=a.instance, logical_database_name=a.pg_database,
            spec=SyncedTableSpec(source_table_full_name=f"{a.catalog}.serving.review_queue_source",
                                 primary_key_columns=["clause_id"],
                                 scheduling_policy=SyncedTableSchedulingPolicy.SNAPSHOT,
                                 create_database_objects_if_missing=True)))
    wait_synced(w, name)
    # wait for the triggered snapshot update to finish
    pid = w.database.get_synced_database_table(name).data_synchronization_status.pipeline_id
    for _ in range(90):
        ups = w.pipelines.list_updates(pid, max_results=1).updates or []
        if ups and ups[0].state and ups[0].state.value in ("COMPLETED", "FAILED", "CANCELED"):
            print(f"  sync pipeline update {ups[0].update_id}: {ups[0].state.value}")
            break
        time.sleep(10)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM serving.review_queue_synced")
        print("rows in Postgres serving.review_queue_synced:", cur.fetchone()["n"])
    print("review_queue status counts after refresh:", lakebase.refresh_queue_from_synced(conn))

    if a.app_name:
        app = w.apps.get(a.app_name)
        sp = app.service_principal_client_id
        print(f"app {app.name}: service principal {sp}")
        with conn.cursor() as cur:
            for stmt in [f'GRANT USAGE ON SCHEMA review TO "{sp}"',
                         f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA review TO "{sp}"',
                         f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA review TO "{sp}"',
                         f'GRANT USAGE ON SCHEMA serving TO "{sp}"',
                         f'GRANT SELECT ON ALL TABLES IN SCHEMA serving TO "{sp}"']:
                try:
                    cur.execute(stmt)
                    print("  [ok]", stmt)
                except Exception as e:  # noqa: BLE001
                    print("  [failed]", stmt, "->", str(e).splitlines()[0])
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        for stmt in [f"GRANT USE CATALOG ON CATALOG `{a.catalog}` TO `{sp}`",
                     f"GRANT USE SCHEMA, SELECT ON SCHEMA `{a.catalog}`.curated TO `{sp}`",
                     f"GRANT USE SCHEMA ON SCHEMA `{a.catalog}`.serving TO `{sp}`"]:
            spark.sql(stmt)
            print("  [ok]", stmt)


if __name__ == "__main__":
    main()
