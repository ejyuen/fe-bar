"""ROI model: MEASURED values from the live build combined with clearly labelled ASSUMPTIONS.

compute() queries the workspace (via dbx.sql) and returns measured inputs, assumptions and outputs;
to_markdown() renders evidence/roi_model.md. Used by notebooks/06_roi_model.ipynb and export_evidence.py.
"""
import datetime

import pandas as pd

from dbx import CATALOG, md, sql

# name -> (value, unit, source)
ASSUMPTIONS = {
    "contracts_in_portfolio": (5000, "contracts", "illustrative (mid-size corporate legal team vendor portfolio)"),
    "manual_review_minutes": (45, "min / contract", "illustrative (spec default; first-pass review of a commercial contract)"),
    "ai_assisted_review_minutes": (8, "min / contract", "illustrative (spec default; reviewer verifies extracted terms)"),
    "legal_cost_per_hour": (150, "USD / hour", "illustrative (spec default; fully loaded in-house cost)"),
    "unwanted_auto_renewal_share": (0.10, "share of auto-renewals", "illustrative (spec default)"),
    "unwanted_renewal_annual_value": (25000, "USD / renewal", "illustrative (spec default)"),
    "platform_run_cost_per_year": (36000, "USD / year", "illustrative (app + Lakebase CU_1 + serverless SQL, ~USD 3K/month)"),
}


def measured():
    q = lambda s: sql(s).iloc[0, 0]  # noqa: E731
    run = sql(f"SELECT mlflow_run_id FROM {CATALOG}.ml.eval_results GROUP BY 1 ORDER BY max(eval_ts) DESC LIMIT 1").iloc[0, 0]
    ev = sql(f"""SELECT metric_name, metric_value FROM {CATALOG}.ml.eval_results
                 WHERE mlflow_run_id = '{run}' AND clause_type = '__summary__'""").set_index("metric_name")["metric_value"]
    ar = sql(f"""SELECT recall FROM {CATALOG}.ml.eval_results WHERE mlflow_run_id = '{run}' AND clause_type = 'auto_renewal'""")
    m = {
        "docs_processed": int(q(f"SELECT count(*) FROM {CATALOG}.curated.gold_documents")),
        "key_clause_f1": float(ev["key_clause_f1"]),
        "micro_f1": float(ev["micro_f1"]),
        "auto_renewal_recall": float(ar.iloc[0, 0]) if not ar.empty else None,
        "pct_auto_accepted": float(q(f"SELECT avg(CASE WHEN status = 'auto_accepted' THEN 1.0 ELSE 0 END) FROM {CATALOG}.serving.pg_review_queue")),
        "cost_per_1k_docs_usd": float(q(f"SELECT max(cost_per_1k_docs) FROM {CATALOG}.curated.gold_cost_metrics WHERE stage = 'total'")),
        "high_risk_flags": int(q(f"SELECT count(*) FROM {CATALOG}.curated.gold_risk_flags WHERE severity = 'high'")),
        "auto_renewing_contracts": int(q(f"SELECT count_if(auto_renewal) FROM {CATALOG}.curated.contract_terms_current")),
        "auto_renewing_within_90_days": int(q(f"""SELECT count(*) FROM {CATALOG}.curated.contract_terms_current
            WHERE auto_renewal AND next_renewal_date BETWEEN current_date() AND date_add(current_date(), 90)""")),
        "uncapped_liability_contracts": int(q(f"SELECT count_if(uncapped_liability) FROM {CATALOG}.curated.contract_terms_current")),
        "eval_mlflow_run_id": run,
    }
    m["auto_renewing_share"] = m["auto_renewing_contracts"] / max(1, m["docs_processed"])
    m["uncapped_share"] = m["uncapped_liability_contracts"] / max(1, m["docs_processed"])
    return m


def compute():
    m = measured()
    a = {k: v[0] for k, v in ASSUMPTIONS.items()}
    n = a["contracts_in_portfolio"]
    hours_saved = n * (a["manual_review_minutes"] - a["ai_assisted_review_minutes"]) / 60
    review_saved = hours_saved * a["legal_cost_per_hour"]
    renewals = n * m["auto_renewing_share"]
    unwanted_caught = renewals * a["unwanted_auto_renewal_share"] * (m["auto_renewal_recall"] or 0)
    renewals_avoided = unwanted_caught * a["unwanted_renewal_annual_value"]
    processing = m["cost_per_1k_docs_usd"] * n / 1000
    platform = processing + a["platform_run_cost_per_year"]
    gross = review_saved + renewals_avoided
    net = gross - platform
    out = {
        "reviewer_hours_saved_per_year": hours_saved,
        "review_cost_saved_usd": review_saved,
        "auto_renewing_contracts_in_portfolio": renewals,
        "unwanted_renewals_caught": unwanted_caught,
        "unwanted_renewals_avoided_usd": renewals_avoided,
        "ai_processing_cost_usd": processing,
        "platform_cost_usd": platform,
        "gross_value_usd": gross,
        "net_value_usd": net,
        "roi_multiple": gross / platform if platform else None,
        "payback_months": 12 * platform / gross if gross else None,
    }
    return m, a, out


def to_markdown(m, a, out):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    meas = pd.DataFrame([
        ("Docs processed", m["docs_processed"], "gold_documents"),
        ("Extraction F1, key clauses", round(m["key_clause_f1"], 3), f"ml.eval_results (MLflow run {m['eval_mlflow_run_id']})"),
        ("Extraction F1, all mapped clauses (micro)", round(m["micro_f1"], 3), "ml.eval_results"),
        ("Auto-renewal detection recall", round(m["auto_renewal_recall"] or 0, 3), "ml.eval_results (CUAD Renewal Term proxy)"),
        ("% clauses auto-accepted", f"{100 * m['pct_auto_accepted']:.1f}%", "Lakebase review_queue (mirror)"),
        ("Cost per 1K docs (USD, estimate)", round(m["cost_per_1k_docs_usd"], 2), "gold_cost_metrics (chars/4 tokens, illustrative prices)"),
        ("High-risk flags", m["high_risk_flags"], "gold_risk_flags"),
        ("Auto-renewing contracts", f"{m['auto_renewing_contracts']} ({100 * m['auto_renewing_share']:.0f}%)", "contract_terms_current"),
        ("Auto-renewing within 90 days", m["auto_renewing_within_90_days"], "contract_terms_current.next_renewal_date"),
        ("Uncapped-liability contracts", f"{m['uncapped_liability_contracts']} ({100 * m['uncapped_share']:.0f}%)", "contract_terms_current"),
    ], columns=["measured value", "value", "source"])
    assum = pd.DataFrame([(k, v[0], v[1], v[2]) for k, v in ASSUMPTIONS.items()], columns=["assumption", "value", "unit", "source"])
    o = out
    outs = pd.DataFrame([
        ("Reviewer hours saved / yr", f"{o['reviewer_hours_saved_per_year']:,.0f} h", "portfolio x (manual - assisted minutes) / 60"),
        ("Review cost saved / yr", f"${o['review_cost_saved_usd']:,.0f}", "hours saved x cost per hour"),
        ("Unwanted renewals caught / yr", f"{o['unwanted_renewals_caught']:,.1f}", "portfolio x measured auto-renewing share x unwanted share x measured auto-renewal recall"),
        ("Unwanted renewals avoided / yr", f"${o['unwanted_renewals_avoided_usd']:,.0f}", "renewals caught x annual value"),
        ("AI processing cost (portfolio)", f"${o['ai_processing_cost_usd']:,.0f}", "measured cost per 1K docs x portfolio / 1000"),
        ("Platform cost / yr", f"${o['platform_cost_usd']:,.0f}", "AI processing + platform run cost assumption"),
        ("Gross value / yr", f"${o['gross_value_usd']:,.0f}", "review savings + renewals avoided"),
        ("**Net value / yr**", f"**${o['net_value_usd']:,.0f}**", "gross value - platform cost"),
        ("ROI multiple", f"{o['roi_multiple']:.1f}x", "gross value / platform cost"),
        ("**Payback**", f"**{o['payback_months']:.1f} months**", "12 x platform cost / gross value"),
    ], columns=["output", "value", "formula"])
    return (f"# ROI model - Northwind Legal Cloud (illustrative)\n\n_Computed {ts} by `scripts/roi_model.py` "
            f"(notebook `notebooks/06_roi_model.ipynb`) from the live workspace, catalog `{CATALOG}`._\n\n"
            "## Measured in this build\n\n" + md(meas) + "\n\n## Assumptions (not measured)\n\n" + md(assum) +
            "\n\n## Outputs\n\n" + md(outs) +
            "\n\n_Measured values come from the build's tables; every assumption is labelled 'illustrative' and should be "
            "replaced with the customer's own figures. Renewal value uses the measured auto-renewal recall so missed "
            "detections are not credited._\n")
