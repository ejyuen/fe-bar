"""Matter Intelligence reviewer workbench - FastAPI backend + React (Vite) frontend on Databricks Apps.

* Analytics reads (gold tables, parsed text) run on the SQL warehouse ON BEHALF OF the signed-in
  user (X-Forwarded-Access-Token from the Apps proxy), so UC row filters and column masks apply.
* The review queue and reviewer actions use Lakebase (Postgres) as the app service principal.
* Every page view, document open, review action and Genie question is written to review.audit_log.
* The compiled frontend lives in ./static (built from /frontend with `npm run build`).
"""
import os
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import genie_client
import lakebase

CATALOG = os.environ.get("CATALOG", "matter_intel")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "unset")
GENIE_SPACE_ID = "" if GENIE_SPACE_ID in ("", "unset") else GENIE_SPACE_ID
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Matter Intelligence")
_sp = None


def sp_client() -> WorkspaceClient:
    global _sp
    if _sp is None:
        _sp = WorkspaceClient()
    return _sp


def pg():
    return lakebase.connect(sp_client())


def email(req: Request) -> str:
    return req.headers.get("x-forwarded-email") or req.headers.get("x-forwarded-preferred-username") or "local-dev"


def user_client(req: Request) -> WorkspaceClient:
    token = req.headers.get("x-forwarded-access-token")
    if token:
        return WorkspaceClient(config=Config(host=os.environ.get("DATABRICKS_HOST"), token=token, auth_type="pat"))
    return sp_client()


def q(req: Request, sql: str) -> list[dict]:
    w = user_client(req)
    r = w.statement_execution.execute_statement(warehouse_id=WAREHOUSE_ID, statement=sql.replace("${catalog}", CATALOG),
                                                wait_timeout="50s")
    while r.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(0.5)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state.value != "SUCCEEDED":
        raise HTTPException(502, r.status.error.message if r.status.error else r.status.state.value)
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


def audit(req, action, entity=None, entity_id=None, details=None, duration_ms=None):
    try:
        lakebase.log_action(pg(), email(req), action, entity, entity_id, details, duration_ms)
    except Exception:  # noqa: BLE001 - auditing must never break the request
        pass


# ----------------------------------------------------------------------------- API
@app.get("/api/me")
def me(req: Request):
    return {"email": email(req), "genie_configured": bool(GENIE_SPACE_ID), "catalog": CATALOG}


class AuditIn(BaseModel):
    action: str
    entity: str | None = None
    entity_id: str | None = None


@app.post("/api/audit")
def post_audit(body: AuditIn, req: Request):
    audit(req, body.action, body.entity, body.entity_id)
    return {"ok": True}


@app.get("/api/overview")
def overview(req: Request):
    k = q(req, """SELECT (SELECT count(*) FROM ${catalog}.curated.gold_documents) AS docs,
                         (SELECT count(*) FROM ${catalog}.curated.gold_clauses) AS clauses,
                         (SELECT count(*) FROM ${catalog}.curated.gold_risk_flags WHERE severity = 'high') AS high_flags,
                         (SELECT max(cost_per_1k_docs) FROM ${catalog}.curated.gold_cost_metrics WHERE stage = 'total') AS cost_per_1k""")[0]
    by_type = q(req, "SELECT contract_type AS label, count(*) AS value FROM ${catalog}.curated.gold_documents GROUP BY 1 ORDER BY 2 DESC")
    by_sev = q(req, "SELECT severity AS label, count(*) AS value FROM ${catalog}.curated.gold_risk_flags GROUP BY 1")
    by_rule = q(req, """SELECT g.rule_id AS rule_id, g.severity, max(p.rule_text) AS rule_text, count(*) AS flags
                        FROM ${catalog}.curated.gold_risk_flags g JOIN ${catalog}.curated.risk_playbook p USING (rule_id)
                        GROUP BY 1, 2 ORDER BY flags DESC""")
    renewals = q(req, """SELECT d.doc_id, d.title, d.contract_type, d.matter_team, e.normalized_value AS expiration_date,
                                coalesce(u.normalized_value, 'false') AS uncapped_liability
                         FROM ${catalog}.curated.gold_documents d
                         JOIN ${catalog}.curated.gold_clauses e ON e.doc_id = d.doc_id AND e.clause_type = 'expiration_date'
                         JOIN ${catalog}.curated.gold_clauses a ON a.doc_id = d.doc_id AND a.clause_type = 'auto_renewal' AND a.normalized_value = 'true'
                         LEFT JOIN ${catalog}.curated.gold_clauses u ON u.doc_id = d.doc_id AND u.clause_type = 'uncapped_liability'
                         ORDER BY try_to_date(e.normalized_value) DESC NULLS LAST LIMIT 12""")
    s = lakebase.queue_stats(pg())
    return {"kpis": {**k, **{kk: s[kk] for kk in ("auto_accepted", "pending", "reviewed")}, "queue_clauses": s["clauses"]},
            "by_contract_type": by_type, "by_severity": by_sev, "by_rule": by_rule, "auto_renewals": renewals,
            "user": email(req)}


@app.get("/api/queue")
def queue(req: Request, status: str = "", severity: str = "", team: str = ""):
    t0 = time.perf_counter()
    split = lambda v: [x for x in v.split(",") if x] or None  # noqa: E731
    rows = lakebase.list_queue(pg(), split(status), split(severity), split(team))
    return {"rows": rows, "ms": round((time.perf_counter() - t0) * 1000, 1)}


@app.get("/api/documents")
def documents():
    return lakebase.list_documents(pg())


@app.get("/api/documents/{doc_id}")
def document(doc_id: str, req: Request):
    if not all(c in "0123456789abcdef" for c in doc_id):
        raise HTTPException(400, "bad doc_id")
    conn = pg()
    clauses = lakebase.doc_clauses(conn, doc_id)
    if not clauses:
        raise HTTPException(404, "document not in review queue")
    text = q(req, f"SELECT full_text, page_count FROM ${{catalog}}.curated.silver_parsed WHERE doc_id = '{doc_id}'")
    visible = q(req, f"SELECT party_name, matter_id FROM ${{catalog}}.curated.gold_documents WHERE doc_id = '{doc_id}'")
    audit(req, "open_document", "document", doc_id)
    for c in clauses:
        c["reviews"] = lakebase.reviews_for(conn, c["clause_id"])
    return {"doc_id": doc_id, "clauses": clauses,
            "full_text": text[0]["full_text"] if text else None,
            "page_count": text[0]["page_count"] if text else None,
            "party_name": visible[0]["party_name"] if visible else None,
            "row_filter_visible": bool(visible)}


class ApproveIn(BaseModel):
    comment: str | None = None


class OverrideIn(BaseModel):
    new_value: str
    comment: str


@app.post("/api/clauses/{clause_id}/approve")
def approve(clause_id: str, body: ApproveIn, req: Request):
    return lakebase.approve(pg(), clause_id, email(req), body.comment or "approved in app")


@app.post("/api/clauses/{clause_id}/override")
def override(clause_id: str, body: OverrideIn, req: Request):
    if not body.new_value.strip():
        raise HTTPException(400, "new_value required")
    return lakebase.override(pg(), clause_id, email(req), body.new_value.strip(), body.comment.strip() or "override in app")


class GenieIn(BaseModel):
    question: str
    conversation_id: str | None = None


@app.post("/api/genie")
def genie(body: GenieIn, req: Request):
    if not GENIE_SPACE_ID:
        raise HTTPException(400, "Genie space not configured")
    t0 = time.perf_counter()
    ans = genie_client.ask(user_client(req), GENIE_SPACE_ID, body.question, body.conversation_id)
    audit(req, "ask_genie", "genie_space", GENIE_SPACE_ID, {"question": body.question, "sql": ans.get("sql")},
          (time.perf_counter() - t0) * 1000)
    return ans


# ----------------------------------------------------------------------------- SPA
if os.path.isdir(os.path.join(STATIC, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC, "assets")), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    return FileResponse(os.path.join(STATIC, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
