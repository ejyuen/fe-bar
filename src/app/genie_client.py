"""Thin wrapper over the Genie Conversation API (databricks-sdk WorkspaceClient.genie)."""
import pandas as pd
from databricks.sdk import WorkspaceClient


def ask(w: WorkspaceClient, space_id: str, question: str, conversation_id: str | None = None) -> dict:
    """Send a question; return {conversation_id, message_id, status, text, sql, columns, rows}."""
    if conversation_id:
        msg = w.genie.create_message_and_wait(space_id, conversation_id, question)
    else:
        msg = w.genie.start_conversation_and_wait(space_id, question)
    out = {"conversation_id": msg.conversation_id, "message_id": msg.id or msg.message_id,
           "status": msg.status.value if msg.status else None, "text": None, "sql": None,
           "description": None, "columns": [], "rows": [], "error": msg.error.error if msg.error else None}
    for att in msg.attachments or []:
        if att.text and att.text.content:
            out["text"] = att.text.content
        if att.query:
            out["sql"] = att.query.query
            out["description"] = att.query.description
            res = w.genie.get_message_attachment_query_result(space_id, msg.conversation_id, out["message_id"],
                                                                att.attachment_id)
            sr = res.statement_response
            if sr and sr.manifest and sr.manifest.schema:
                out["columns"] = [c.name for c in sr.manifest.schema.columns]
            if sr and sr.result and sr.result.data_array:
                out["rows"] = sr.result.data_array
    return out


def to_frame(ans: dict) -> pd.DataFrame:
    return pd.DataFrame(ans.get("rows") or [], columns=ans.get("columns") or None)
