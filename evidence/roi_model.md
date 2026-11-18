# ROI model - Northwind Legal Cloud (illustrative)

_Computed 2026-11-18 03:27 UTC by `scripts/roi_model.py` (notebook `notebooks/06_roi_model.ipynb`) from the live workspace, catalog `serverless_stable_oj7eie_catalog`._

## Measured in this build

| measured value                            | value    | source                                                        |
|:------------------------------------------|:---------|:--------------------------------------------------------------|
| Docs processed                            | 100      | gold_documents                                                |
| Extraction F1, key clauses                | 0.764    | ml.eval_results (MLflow run c3d5551824c7460e8f811c5691c0154e) |
| Extraction F1, all mapped clauses (micro) | 0.827    | ml.eval_results                                               |
| Auto-renewal detection recall             | 0.483    | ml.eval_results (CUAD Renewal Term proxy)                     |
| % clauses auto-accepted                   | 86.5%    | Lakebase review_queue (mirror)                                |
| Cost per 1K docs (USD, estimate)          | 108.64   | gold_cost_metrics (chars/4 tokens, illustrative prices)       |
| High-risk flags                           | 62       | gold_risk_flags                                               |
| Auto-renewing contracts                   | 17 (17%) | contract_terms_current                                        |
| Auto-renewing within 90 days              | 4        | contract_terms_current.next_renewal_date                      |
| Uncapped-liability contracts              | 25 (25%) | contract_terms_current                                        |

## Assumptions (not measured)

| assumption                    |   value | unit                   | source                                                                  |
|:------------------------------|--------:|:-----------------------|:------------------------------------------------------------------------|
| contracts_in_portfolio        |  5000   | contracts              | illustrative (mid-size corporate legal team vendor portfolio)           |
| manual_review_minutes         |    45   | min / contract         | illustrative (spec default; first-pass review of a commercial contract) |
| ai_assisted_review_minutes    |     8   | min / contract         | illustrative (spec default; reviewer verifies extracted terms)          |
| legal_cost_per_hour           |   150   | USD / hour             | illustrative (spec default; fully loaded in-house cost)                 |
| unwanted_auto_renewal_share   |     0.1 | share of auto-renewals | illustrative (spec default)                                             |
| unwanted_renewal_annual_value | 25000   | USD / renewal          | illustrative (spec default)                                             |
| platform_run_cost_per_year    | 36000   | USD / year             | illustrative (app + Lakebase CU_1 + serverless SQL, ~USD 3K/month)      |

## Outputs

| output                         | value          | formula                                                                                  |
|:-------------------------------|:---------------|:-----------------------------------------------------------------------------------------|
| Reviewer hours saved / yr      | 3,083 h        | portfolio x (manual - assisted minutes) / 60                                             |
| Review cost saved / yr         | $462,500       | hours saved x cost per hour                                                              |
| Unwanted renewals caught / yr  | 41.0           | portfolio x measured auto-renewing share x unwanted share x measured auto-renewal recall |
| Unwanted renewals avoided / yr | $1,025,862     | renewals caught x annual value                                                           |
| AI processing cost (portfolio) | $543           | measured cost per 1K docs x portfolio / 1000                                             |
| Platform cost / yr             | $36,543        | AI processing + platform run cost assumption                                             |
| Gross value / yr               | $1,488,362     | review savings + renewals avoided                                                        |
| **Net value / yr**             | **$1,451,819** | gross value - platform cost                                                              |
| ROI multiple                   | 40.7x          | gross value / platform cost                                                              |
| **Payback**                    | **0.3 months** | 12 x platform cost / gross value                                                         |

_Measured values come from the build's tables; every assumption is labelled 'illustrative' and should be replaced with the customer's own figures. Renewal value uses the measured auto-renewal recall so missed detections are not credited._
