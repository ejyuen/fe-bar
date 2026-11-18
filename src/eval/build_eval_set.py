"""Build the eval ground truth: CUAD v1 expert labels (master_clauses.csv) -> our clause_types.

Writes ${catalog}.ml.eval_ground_truth with one row per (document in the pipeline, clause_type).

CUAD -> Matter Intelligence mapping (explicit; `basis` says how presence is decided):
  clause_type                  CUAD category                          basis
  parties                      Parties                                span present
  governing_law                Governing Law                          span present  (+ value: Governing Law-Answer)
  effective_date               Effective Date                         span present  (+ value: Effective Date-Answer)
  expiration_date              Expiration Date                        span present  (+ value: Expiration Date-Answer)
  renewal_term                 Renewal Term                           span present  (+ value: Renewal Term-Answer)
  auto_renewal                 Renewal Term                           span present  (PROXY: CUAD has no auto-renewal label)
  notice_period_days           Notice Period To Terminate Renewal     span present  (+ value: days in the Answer)
  liability_cap                Cap On Liability                       Answer = Yes
  uncapped_liability           Uncapped Liability                     Answer = Yes
  termination_for_convenience  Termination For Convenience            Answer = Yes
  exclusivity                  Exclusivity                            Answer = Yes
  non_compete                  Non-Compete                            Answer = Yes
  assignment_restriction       Anti-Assignment                        Answer = Yes
  indemnification              (no CUAD category)                     not evaluated
"""
import argparse
import os
import sys

def _src_dir():
    # Serverless spark_python_task does not define __file__; the job passes --src_dir instead.
    if "--src_dir" in sys.argv:
        return sys.argv[sys.argv.index("--src_dir") + 1]
    return os.path.dirname(os.path.abspath(__file__))


sys.path.insert(0, _src_dir())
from common import Sql  # noqa: E402

# (clause_type, cuad span column, cuad answer column, basis)
MAPPING = [
    ("parties", "Parties", "Parties-Answer", "span"),
    ("governing_law", "Governing Law", "Governing Law-Answer", "span"),
    ("effective_date", "Effective Date", "Effective Date-Answer", "span"),
    ("expiration_date", "Expiration Date", "Expiration Date-Answer", "span"),
    ("renewal_term", "Renewal Term", "Renewal Term-Answer", "span"),
    ("auto_renewal", "Renewal Term", "Renewal Term-Answer", "span_proxy"),
    ("notice_period_days", "Notice Period To Terminate Renewal", "Notice Period To Terminate Renewal- Answer", "span"),
    ("liability_cap", "Cap On Liability", "Cap On Liability-Answer", "yes_no"),
    ("uncapped_liability", "Uncapped Liability", "Uncapped Liability-Answer", "yes_no"),
    ("termination_for_convenience", "Termination For Convenience", "Termination For Convenience-Answer", "yes_no"),
    ("exclusivity", "Exclusivity", "Exclusivity-Answer", "yes_no"),
    ("non_compete", "Non-Compete", "Non-Compete-Answer", "yes_no"),
    ("assignment_restriction", "Anti-Assignment", "Anti-Assignment-Answer", "yes_no"),
]


def build_sql(catalog: str) -> str:
    parts = []
    for ct, span, ans, basis in MAPPING:
        present = (f"(trim(l.`{span}`) NOT IN ('[]', '') AND l.`{span}` IS NOT NULL)" if basis.startswith("span")
                   else f"(lower(trim(l.`{ans}`)) = 'yes')")
        parts.append(f"""SELECT d.doc_id, l.Filename AS file_name, '{ct}' AS clause_type, '{span}' AS cuad_category,
       '{basis}' AS basis, {present} AS gt_present, l.`{ans}` AS gt_answer, l.`{span}` AS gt_spans
FROM labels l JOIN docs d ON d.file_name = l.Filename""")
    union = "\nUNION ALL\n".join(parts)
    return f"""CREATE OR REPLACE TABLE {catalog}.ml.eval_ground_truth
COMMENT 'CUAD v1 expert labels (CC BY 4.0) mapped to Matter Intelligence clause types; one row per (doc, clause_type)'
AS WITH labels AS (
  SELECT * FROM read_files('/Volumes/{catalog}/raw/contracts/labels/master_clauses.csv',
                           format => 'csv', header => true, multiLine => true, escape => '"')
), docs AS (
  SELECT doc_id, regexp_extract(path, '([^/]+)$', 1) AS file_name FROM {catalog}.raw.bronze_documents
)
{union}"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--warehouse_id", required=True)
    ap.add_argument("--src_dir", default=None)
    a = ap.parse_args(argv)
    sql = Sql(a.catalog, a.warehouse_id)
    sql(build_sql(a.catalog))
    df = sql(f"""SELECT clause_type, basis, count(*) AS docs, count_if(gt_present) AS gt_present
                 FROM {a.catalog}.ml.eval_ground_truth GROUP BY ALL ORDER BY clause_type""")
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    main()
