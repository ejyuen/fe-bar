"""Small helpers shared by notebooks and scripts/export_evidence.py.

Runs SQL on the configured SQL warehouse through the Databricks SDK (statement execution API)
and renders results as pandas DataFrames / markdown. Auth comes from the Databricks CLI profile
(env DATABRICKS_CONFIG_PROFILE, default fe-vm-oj7eie) -- no tokens in code.
"""
import os
import time

import pandas as pd
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementState

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "fe-vm-oj7eie")
CATALOG = os.environ.get("MI_CATALOG", "serverless_stable_oj7eie_catalog")
WAREHOUSE_ID = os.environ.get("MI_WAREHOUSE_ID", "8232b6cb7d06e103")

_w = None


def ws() -> WorkspaceClient:
    global _w
    if _w is None:
        _w = WorkspaceClient(profile=PROFILE)
    return _w


def sql(statement: str, max_rows: int = 10000) -> pd.DataFrame:
    """Execute SQL and return a DataFrame. Raises RuntimeError with the server message on failure."""
    statement = statement.replace("${catalog}", CATALOG)
    w = ws()
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=statement, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY, row_limit=max_rows)
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''}")
    cols = [c.name for c in r.manifest.schema.columns] if r.manifest and r.manifest.schema else []
    rows = list(r.result.data_array or []) if r.result else []
    chunk = r.result.next_chunk_index if r.result else None
    while chunk is not None:
        c = w.statement_execution.get_statement_result_chunk_n(r.statement_id, chunk)
        rows.extend(c.data_array or [])
        chunk = c.next_chunk_index
    return pd.DataFrame(rows, columns=cols)


def md(df: pd.DataFrame, max_col_chars: int = 160) -> str:
    """Markdown table with long cells truncated and pipes/newlines escaped."""
    if df.empty:
        return "_(no rows)_"

    def clean(v):
        if v is None or (isinstance(v, float) and v != v):
            return ""
        s = str(v).replace("\n", " ").replace("|", "\\|")
        return s if len(s) <= max_col_chars else s[: max_col_chars - 1] + "…"

    return df.apply(lambda col: col.map(clean)).to_markdown(index=False)


def section(title: str, statement: str, note: str = "", **kw) -> str:
    """Run SQL and return a markdown block with the SQL shown and its real output."""
    s = statement.replace("${catalog}", CATALOG).strip()
    try:
        body = md(sql(s), **kw)
    except Exception as e:  # noqa: BLE001
        body = f"**ERROR:** `{str(e)[:500]}`"
    out = f"### {title}\n\n"
    if note:
        out += note + "\n\n"
    return out + f"```sql\n{s}\n```\n\n{body}\n\n"
