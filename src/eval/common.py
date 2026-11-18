"""SQL-warehouse helper for the eval scripts (works locally with a CLI profile and inside a job)."""
import os
import time

import pandas as pd
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementState


class Sql:
    def __init__(self, catalog: str, warehouse_id: str, profile: str | None = None):
        self.catalog = catalog
        self.warehouse_id = warehouse_id
        profile = profile or os.environ.get("DATABRICKS_CONFIG_PROFILE")
        self.w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()

    def __call__(self, statement: str) -> pd.DataFrame:
        statement = statement.replace("${catalog}", self.catalog)
        r = self.w.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id, statement=statement, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            r = self.w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''}\n{statement[:500]}")
        cols = [c.name for c in r.manifest.schema.columns] if r.manifest and r.manifest.schema else []
        rows = list(r.result.data_array or []) if r.result else []
        chunk = r.result.next_chunk_index if r.result else None
        while chunk is not None:
            c = self.w.statement_execution.get_statement_result_chunk_n(r.statement_id, chunk)
            rows.extend(c.data_array or [])
            chunk = c.next_chunk_index
        return pd.DataFrame(rows, columns=cols)


def lit(v) -> str:
    """SQL literal for a python value."""
    if v is None or (isinstance(v, float) and v != v):
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"
