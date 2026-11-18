"""Evaluate clause extraction against CUAD ground truth and judge explanation groundedness.

Metrics
  * per clause_type presence precision / recall / F1 (doc-level: did we extract a value where CUAD
    experts marked the clause?) -- booleans (auto_renewal, uncapped_liability) count as present
    only when the extracted value is true
  * value match for clause types with a CUAD answer: exact (normalized string / date / number
    equality) and fuzzy (rapidfuzz token_set_ratio >= 85, or equality)
  * LLM judge (mlflow.genai, make_judge): is each AI risk explanation supported by its source snippet?
  * cost per 1K docs from gold_cost_metrics (estimate, see pipeline config)

Outputs: MLflow experiment run (params, metrics, tables, judge assessments), ${catalog}.ml.eval_results,
${catalog}.ml.eval_details. Run as a member of legal_admins so the row filter does not hide documents.
"""
import argparse
import datetime
import json
import os
import re
import sys

os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", "1")  # parallel judge calls race on CLI OAuth token refresh
import mlflow
import pandas as pd
from rapidfuzz import fuzz

def _src_dir():
    # Serverless spark_python_task does not define __file__; the job passes --src_dir instead.
    if "--src_dir" in sys.argv:
        return sys.argv[sys.argv.index("--src_dir") + 1]
    return os.path.dirname(os.path.abspath(__file__))


sys.path.insert(0, _src_dir())
from build_eval_set import MAPPING  # noqa: E402
from common import Sql, lit  # noqa: E402

BOOL_TYPES = {"auto_renewal", "uncapped_liability"}
VALUE_TYPES = {"governing_law", "effective_date", "expiration_date", "renewal_term", "notice_period_days", "parties"}
KEY_CLAUSES = ["governing_law", "expiration_date", "auto_renewal", "notice_period_days", "liability_cap", "uncapped_liability"]
FUZZY_THRESHOLD = 85

GROUNDEDNESS_INSTRUCTIONS = """You are auditing an AI-written contract risk explanation.
The inputs contain the playbook rule, the clause type and the SOURCE SNIPPET copied from the contract.
The outputs contain the explanation written by the AI.

Inputs: {{ inputs }}
Explanation: {{ outputs }}

Answer true only if every factual statement the explanation makes about the contract is supported by the
SOURCE SNIPPET (paraphrase is fine; general legal reasoning about why the rule applies is fine). Answer false
if the explanation asserts contract facts that are not in the snippet, contradicts the snippet, or admits it
cannot confirm the rule from the snippet."""


# ------------------------------------------------------------------ value normalisation
def _norm_text(s):
    s = (s or "").lower()
    s = re.sub(r"\b(the|laws?|of|state|commonwealth|province|usa|united states|u\.s\.a?\.?)\b", " ", s)
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", s)).strip()


def _to_date(s):
    if not s or not isinstance(s, str):
        return None
    try:
        d = pd.to_datetime(s.strip(), errors="raise")
        return d.date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def _to_days(s):
    if s is None:
        return None
    m = re.search(r"(\d+)\s*(day|month|year|week)?", str(s).lower())
    if not m:
        return None
    n, unit = int(m.group(1)), (m.group(2) or "day")
    return n * {"day": 1, "week": 7, "month": 30, "year": 365}[unit]


def value_match(clause_type, pred, gt):
    """Return (exact, fuzzy) booleans, or (None, None) if the ground-truth answer is not comparable."""
    if gt is None or str(gt).strip() == "" or str(gt).lower() == "nan":
        return None, None
    if clause_type in ("effective_date", "expiration_date"):
        g, p = _to_date(gt), _to_date(pred)
        if g is None:
            return None, None
        return p == g, p == g
    if clause_type == "notice_period_days":
        g, p = _to_days(gt), _to_days(pred)
        if g is None:
            return None, None
        return p == g, p is not None and abs(p - g) <= 1
    p, g = _norm_text(pred), _norm_text(gt)
    exact = p == g
    return exact, exact or fuzz.token_set_ratio(p, g) >= FUZZY_THRESHOLD


def _flag_ids(rdf, data):
    """flag_id per result row, read from the row's inputs (result order is not guaranteed)."""
    for col in ("inputs", "request"):
        if col in rdf.columns:
            out = []
            for v in rdf[col]:
                if isinstance(v, str):
                    try:
                        v = json.loads(v)
                    except ValueError:
                        v = {}
                out.append(v.get("flag_id") if isinstance(v, dict) else None)
            if all(out):
                return out
    raise RuntimeError(f"cannot map judge results to flag_id; result columns: {list(rdf.columns)}")


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if (p is not None and r is not None) else None)
    return p, r, f


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--warehouse_id", required=True)
    ap.add_argument("--experiment", default=None, help="MLflow experiment path")
    ap.add_argument("--judge_model", default="databricks:/databricks-claude-sonnet-4-5")
    ap.add_argument("--src_dir", default=None)
    a = ap.parse_args(argv)
    sql = Sql(a.catalog, a.warehouse_id)
    c = a.catalog

    me = sql.w.current_user.me().user_name
    experiment = a.experiment or f"/Users/{me}/matter-intelligence-eval"
    mlflow.set_tracking_uri("databricks")
    exp = mlflow.set_experiment(experiment)

    gt = sql(f"SELECT doc_id, file_name, clause_type, basis, cast(gt_present AS STRING) gt_present, gt_answer FROM {c}.ml.eval_ground_truth")
    gt["gt_present"] = gt["gt_present"] == "true"
    pred = sql(f"SELECT doc_id, clause_type, normalized_value, extracted_value, model_name FROM {c}.curated.gold_clauses")
    df = gt.merge(pred, on=["doc_id", "clause_type"], how="left")
    df["pred_present"] = df["normalized_value"].notna() & (
        ~df["clause_type"].isin(BOOL_TYPES) | (df["normalized_value"].str.lower() == "true"))
    vm = df.apply(lambda r: value_match(r.clause_type, r.normalized_value, r.gt_answer)
                  if (r.clause_type in VALUE_TYPES and r.pred_present and r.gt_present) else (None, None), axis=1)
    df["exact_match"] = [x[0] for x in vm]
    df["fuzzy_match"] = [x[1] for x in vm]
    model_name = pred["model_name"].dropna().iloc[0] if not pred.empty else "unknown"
    n_docs = df["doc_id"].nunique()

    rows = []
    basis = {m[0]: m[3] for m in MAPPING}
    for ct, g in df.groupby("clause_type"):
        tp = int((g.gt_present & g.pred_present).sum()); fp = int((~g.gt_present & g.pred_present).sum())
        fn = int((g.gt_present & ~g.pred_present).sum()); tn = int((~g.gt_present & ~g.pred_present).sum())
        p, r, f = prf(tp, fp, fn)
        comp = g["exact_match"].dropna()
        rows.append(dict(clause_type=ct, basis=basis[ct], tp=tp, fp=fp, fn=fn, tn=tn, precision=p, recall=r, f1=f,
                         value_compared=int(len(comp)),
                         exact_match_rate=float(comp.mean()) if len(comp) else None,
                         fuzzy_match_rate=float(g["fuzzy_match"].dropna().mean()) if len(comp) else None))
    per = pd.DataFrame(rows).sort_values("clause_type")

    def micro(sub):
        tp, fp, fn = sub.tp.sum(), sub.fp.sum(), sub.fn.sum()
        return prf(int(tp), int(fp), int(fn))
    mp, mr, mf = micro(per)
    kp, kr, kf = micro(per[per.clause_type.isin(KEY_CLAUSES)])
    macro_f1 = float(per.f1.dropna().mean())

    cost = sql(f"SELECT cast(cost_per_1k_docs AS DOUBLE) v FROM {c}.curated.gold_cost_metrics WHERE stage = 'total' ORDER BY run_id DESC LIMIT 1")
    cost_per_1k = float(cost.v.iloc[0]) if not cost.empty else None

    # ------------------------------------------------ groundedness judge
    flags = sql(f"""SELECT g.flag_id, g.rule_id, g.severity, g.clause_type, g.reason, i.source_snippet, g.explanation
                    FROM {c}.curated.gold_risk_flags g JOIN {c}.curated.int_risk_flags i USING (flag_id)
                    WHERE g.explanation IS NOT NULL ORDER BY g.flag_id""")
    judge = __import__("mlflow.genai.judges", fromlist=["make_judge"]).make_judge(
        name="explanation_groundedness", instructions=GROUNDEDNESS_INSTRUCTIONS, model=a.judge_model,
        feedback_value_type=bool, inference_params={"temperature": 0.0})
    explanations = {r.flag_id: r.explanation for r in flags.itertuples()}
    data = [{"inputs": {"flag_id": r.flag_id, "rule": r.reason, "clause_type": r.clause_type,
                        "source_snippet": r.source_snippet or ""}} for r in flags.itertuples()]

    @mlflow.trace(name="risk_explanation_lookup")
    def predict_fn(flag_id, rule, clause_type, source_snippet):
        # The explanation was generated in the pipeline by ai_query; replay it so each row gets a trace.
        return explanations[flag_id]

    run_name = f"eval-{model_name}-{datetime.datetime.utcnow():%Y%m%d-%H%M%S}"
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.log_params({"extract_model": model_name, "docs": n_docs, "judge_model": a.judge_model,
                           "fuzzy_threshold": FUZZY_THRESHOLD, "ground_truth": "CUAD v1 master_clauses.csv"})
        for rr in per.itertuples():
            for k in ("precision", "recall", "f1", "exact_match_rate", "fuzzy_match_rate"):
                v = getattr(rr, k)
                if v is not None and v == v:
                    mlflow.log_metric(f"{k}.{rr.clause_type}", float(v))
        summary = {"micro_precision": mp, "micro_recall": mr, "micro_f1": mf, "macro_f1": macro_f1,
                   "key_clause_precision": kp, "key_clause_recall": kr, "key_clause_f1": kf,
                   "cost_per_1k_docs_usd": cost_per_1k}
        mlflow.log_metrics({k: float(v) for k, v in summary.items() if v is not None})
        mlflow.log_table(per, "per_clause_metrics.json")
        mlflow.log_table(df.drop(columns=["extracted_value"]), "doc_level_details.json")

        # Low parallelism avoids endpoint rate limits; rows whose judge call still fails are retried
        # one at a time below and any remaining failures are reported, never counted as grounded.
        os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = "1"
        res = mlflow.genai.evaluate(data=data, predict_fn=predict_fn, scorers=[judge])
        rdf = res.result_df
        vcol = next(x for x in rdf.columns if x.startswith("explanation_groundedness") and x.endswith("value"))
        rcol = vcol.replace("/value", "/rationale")
        judged = pd.DataFrame({
            "flag_id": _flag_ids(rdf, data),
            "value": rdf[vcol].values,
            "rationale": rdf[rcol].values if rcol in rdf.columns else None,
        })
        retried = 0
        for i, r in judged[judged["value"].isna()].iterrows():
            d = next(x for x in data if x["inputs"]["flag_id"] == r.flag_id)
            for _ in range(3):
                fb = judge(inputs=d["inputs"], outputs=explanations[r.flag_id])
                if fb.error is None and fb.value is not None:
                    judged.loc[i, ["value", "rationale"]] = [fb.value, fb.rationale]
                    retried += 1
                    break
        judged["grounded"] = judged["value"].map(lambda v: None if v is None or (isinstance(v, float) and v != v)
                                                 else str(v).lower() in ("true", "yes", "1"))
        print(f"judge rows: {len(judged)}, failed after retry: {int(judged['grounded'].isna().sum())}")
        ok = judged["grounded"].dropna()
        groundedness = float(ok.mean()) if len(ok) else None
        summary["judged_explanations"] = len(data)
        summary["judge_failures"] = int(judged["grounded"].isna().sum())
        summary["judge_retried_ok"] = retried
        mlflow.log_metrics({"judge_failures": summary["judge_failures"], "judged_explanations": len(data)})
        mlflow.log_table(judged.drop(columns=["value"]), "groundedness_judgements.json")
        if groundedness is not None:
            mlflow.log_metric("groundedness", groundedness)
        summary["groundedness"] = groundedness
        run_id = run.info.run_id

    # ------------------------------------------------ persist to UC
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    sql(f"""CREATE TABLE IF NOT EXISTS {c}.ml.eval_results (
      eval_ts TIMESTAMP, mlflow_experiment_id STRING, mlflow_run_id STRING, model_name STRING, docs INT,
      clause_type STRING, basis STRING, tp INT, fp INT, fn INT, tn INT, precision DOUBLE, recall DOUBLE, f1 DOUBLE,
      value_compared INT, exact_match_rate DOUBLE, fuzzy_match_rate DOUBLE, metric_name STRING, metric_value DOUBLE)
      COMMENT 'Extraction eval vs CUAD labels; one row per clause_type plus summary metric rows per eval run'""")
    vals = []
    for rr in per.itertuples():
        vals.append(f"(timestamp'{ts}', {lit(exp.experiment_id)}, {lit(run_id)}, {lit(model_name)}, {n_docs}, {lit(rr.clause_type)}, "
                    f"{lit(rr.basis)}, {rr.tp}, {rr.fp}, {rr.fn}, {rr.tn}, {lit(rr.precision)}, {lit(rr.recall)}, {lit(rr.f1)}, "
                    f"{rr.value_compared}, {lit(rr.exact_match_rate)}, {lit(rr.fuzzy_match_rate)}, NULL, NULL)")
    for k, v in summary.items():
        vals.append(f"(timestamp'{ts}', {lit(exp.experiment_id)}, {lit(run_id)}, {lit(model_name)}, {n_docs}, '__summary__', NULL, "
                    f"NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, {lit(k)}, {lit(None if v is None else float(v))})")
    sql(f"INSERT INTO {c}.ml.eval_results VALUES\n" + ",\n".join(vals))

    det = df[["doc_id", "file_name", "clause_type", "basis", "gt_present", "pred_present", "gt_answer",
              "normalized_value", "exact_match", "fuzzy_match"]]
    dvals = ",\n".join("(" + ", ".join([lit(run_id)] + [lit(None if (isinstance(x, float) and x != x) else x) for x in r]) + ")"
                       for r in det.itertuples(index=False))
    sql(f"""CREATE OR REPLACE TABLE {c}.ml.eval_details (mlflow_run_id STRING, doc_id STRING, file_name STRING,
      clause_type STRING, basis STRING, gt_present BOOLEAN, pred_present BOOLEAN, gt_answer STRING,
      predicted_value STRING, exact_match BOOLEAN, fuzzy_match BOOLEAN)
      COMMENT 'Doc-level eval rows for the latest eval run'""")
    sql(f"INSERT INTO {c}.ml.eval_details VALUES\n{dvals}")
    if not judged.empty:
        jvals = ",\n".join(f"({lit(run_id)}, {lit(r.flag_id)}, {lit(None if r.grounded is None else bool(r.grounded))}, {lit(r.rationale)})"
                           for r in judged.itertuples())
        sql(f"""CREATE OR REPLACE TABLE {c}.ml.eval_groundedness (mlflow_run_id STRING, flag_id STRING, grounded BOOLEAN, rationale STRING)
                COMMENT 'LLM-judge groundedness per AI risk explanation (latest eval run)'""")
        sql(f"INSERT INTO {c}.ml.eval_groundedness VALUES\n{jvals}")

    print(per.to_string(index=False))
    print(json.dumps({"experiment": experiment, "experiment_id": exp.experiment_id, "run_id": run_id, **summary}, indent=2, default=str))
    return {"per_clause": per, "summary": summary, "run_id": run_id, "experiment_id": exp.experiment_id,
            "experiment": experiment, "details": df, "judged": judged}


if __name__ == "__main__":
    main()
