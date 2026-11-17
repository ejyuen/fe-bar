"""Seeded synthetic overlay: matters, users -> matter_team mapping, and the firm risk playbook.

All names are generated with Faker (seed 42) and are fictional. Documents are assigned to
matters deterministically in the pipeline: matter_seq = pmod(xxhash64(doc_id), n_matters).
Idempotent: every table is overwritten.
"""
import argparse

from faker import Faker
from pyspark.sql import SparkSession

TEAMS = ["Team Atlas", "Team Borealis", "Team Cascade", "Team Denali"]
PRACTICE_AREAS = ["Commercial Contracts", "Technology Transactions", "IP Licensing",
                  "Supply Chain", "Real Estate", "Employment"]
N_MATTERS = 12

# (rule_id, clause_type, rule_type, match_value, severity, rule_text)
PLAYBOOK = [
    ("R01", "uncapped_liability", "is_true", None, "high",
     "Liability is uncapped or unlimited for at least one party."),
    ("R02", "non_compete", "present", None, "high",
     "Contract restricts a party from competing; requires partner sign-off."),
    ("R03", "auto_renewal", "is_true", None, "medium",
     "Contract renews automatically unless notice is given; calendar the notice date."),
    ("R04", "notice_period_days", "gte", "90", "medium",
     "Notice period to stop renewal is 90 days or longer."),
    ("R05", "exclusivity", "present", None, "medium",
     "Contract grants or requires exclusivity."),
    ("R06", "governing_law", "not_in", "delaware,new york,california", "low",
     "Governing law is outside the firm's preferred jurisdictions (DE, NY, CA)."),
    ("R07", "termination_for_convenience", "present", None, "low",
     "A party may terminate for convenience (without cause)."),
    ("R08", "assignment_restriction", "present", None, "low",
     "Assignment requires consent or is restricted (change-of-control risk)."),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    a = ap.parse_args()
    spark = SparkSession.builder.getOrCreate()
    fake = Faker()
    Faker.seed(42)

    matters = []
    for i in range(N_MATTERS):
        matters.append((i, f"M-{1001 + i}", f"{fake.company()} (fictional)",
                        PRACTICE_AREAS[i % len(PRACTICE_AREAS)], TEAMS[i % len(TEAMS)]))

    runner = spark.sql("SELECT current_user()").first()[0]
    users = [(runner, "Team Atlas"), (runner, "Team Borealis")]
    for i in range(8):
        users.append((f"{fake.user_name()}@example.com", TEAMS[i % len(TEAMS)]))

    def save(rows, schema, name):
        (spark.createDataFrame(rows, schema).write.mode("overwrite")
         .option("overwriteSchema", "true").saveAsTable(f"`{a.catalog}`.curated.{name}"))
        print(f"{name}: {len(rows)} rows")

    save(matters, "matter_seq int, matter_id string, client string, practice_area string, matter_team string", "matters")
    save(users, "user_email string, matter_team string", "user_team_mapping")
    save(PLAYBOOK, "rule_id string, clause_type string, rule_type string, match_value string, severity string, rule_text string", "risk_playbook")


if __name__ == "__main__":
    main()
