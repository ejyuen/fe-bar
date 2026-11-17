"""Run one section of a SQL file statement-by-statement with spark.sql and log each outcome.

Statements are separated by ';' at end of line. A statement preceded by a line
`-- @allow_fail` is logged but does not fail the task (used for grants to principals that may
not exist in a given workspace). `${catalog}` is substituted. Results go to curated.governance_log.
"""
import argparse
import datetime
import os
import re
import sys

from pyspark.sql import SparkSession


def parse_sections(text):
    sections, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"--\s*@section\s+(\w+)", line.strip())
        if m:
            cur = m.group(1)
            sections[cur] = []
            continue
        if cur:
            sections[cur].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def split_statements(body):
    stmts, buf, allow_fail = [], [], False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("-- @allow_fail"):
            allow_fail = True
            continue
        if (s.startswith("--") or not s) and not buf:
            continue
        buf.append(line)
        if s.endswith(";"):
            stmts.append(("\n".join(buf).strip().rstrip(";"), allow_fail))
            buf, allow_fail = [], False
    return stmts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--section", required=True)
    a = ap.parse_args()
    spark = SparkSession.builder.getOrCreate()
    path = a.file if a.file.startswith("/") else os.path.join(os.getcwd(), a.file)
    text = open(path).read().replace("${catalog}", a.catalog)
    stmts = split_statements(parse_sections(text)[a.section])

    log, hard_fail = [], False
    for sql, allow_fail in stmts:
        first = " ".join(sql.split())[:160]
        try:
            spark.sql(sql)
            status, err = "ok", None
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0][:400]
            status, err = ("allowed_failure" if allow_fail else "failed"), msg
            hard_fail = hard_fail or not allow_fail
        print(f"[{status}] {first}" + (f"\n    -> {err}" if err else ""))
        log.append((datetime.datetime.utcnow(), os.path.basename(a.file), a.section, first, status, err))

    spark.createDataFrame(log, "ts timestamp, file string, section string, statement string, status string, error string") \
        .write.mode("append").saveAsTable(f"`{a.catalog}`.curated.governance_log")
    if hard_fail:
        sys.exit("One or more required statements failed")


if __name__ == "__main__":
    main()
