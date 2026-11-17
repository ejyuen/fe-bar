"""Stage a deterministic subset of CUAD v1 contract PDFs (plus label files) into a UC Volume.

Source: Contract Understanding Atticus Dataset (CUAD) v1, The Atticus Project,
https://zenodo.org/records/4595826 , licensed CC BY 4.0.

Idempotent: the zip is cached in the Volume, files that already exist are skipped, and the
subset order is deterministic, so raising --doc_limit only adds files (a superset).
"""
import argparse
import csv
import io
import os
import shutil
import urllib.request
import zipfile
from collections import OrderedDict

from pyspark.sql import SparkSession

CUAD_URL = "https://zenodo.org/api/records/4595826/files/CUAD_v1.zip/content"
PDF_PREFIX = "CUAD_v1/full_contract_pdf/"
LABEL_FILES = ["CUAD_v1/master_clauses.csv", "CUAD_v1/CUAD_v1.json", "CUAD_v1/CUAD_v1_README.txt"]


def select_subset(pdf_members, limit):
    """Round-robin across CUAD contract-category folders so the subset mixes contract types."""
    by_cat = OrderedDict()
    for m in sorted(pdf_members):
        cat = m[len(PDF_PREFIX):].split("/")[1]  # Part_X/<Category>/<file>.pdf
        by_cat.setdefault(cat, []).append(m)
    picked, i = [], 0
    while len(picked) < limit and any(by_cat.values()):
        for cat in list(by_cat):
            if i < len(by_cat[cat]) and len(picked) < limit:
                picked.append((cat, by_cat[cat][i]))
        i += 1
        if all(i >= len(v) for v in by_cat.values()):
            break
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--doc_limit", type=int, default=100)
    a = ap.parse_args()
    spark = SparkSession.builder.getOrCreate()

    for s in ["raw", "curated", "serving", "ml"]:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{a.catalog}`.`{s}`")
    spark.sql(f"CREATE VOLUME IF NOT EXISTS `{a.catalog}`.raw.contracts COMMENT 'CUAD v1 contract PDFs (CC BY 4.0) and labels'")

    vol = f"/Volumes/{a.catalog}/raw/contracts"
    for d in ["pdfs", "labels", "_cache"]:
        os.makedirs(f"{vol}/{d}", exist_ok=True)

    cache = f"{vol}/_cache/CUAD_v1.zip"
    if not os.path.exists(cache):
        tmp = "/tmp/CUAD_v1.zip"
        print(f"Downloading {CUAD_URL}")
        with urllib.request.urlopen(CUAD_URL, timeout=600) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        shutil.copy(tmp, cache)
    print(f"zip size: {os.path.getsize(cache):,} bytes")

    with zipfile.ZipFile(cache) as z:
        names = z.namelist()
        pdfs = [n for n in names if n.startswith(PDF_PREFIX) and n.lower().endswith(".pdf")]
        print(f"CUAD PDFs in archive: {len(pdfs)}")
        picked = select_subset(pdfs, a.doc_limit)

        copied = skipped = 0
        manifest = []
        for cat, member in picked:
            base = os.path.basename(member)
            dest = f"{vol}/pdfs/{base}"
            if os.path.exists(dest):
                skipped += 1
            else:
                with z.open(member) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                copied += 1
            manifest.append((base, cat, member, f"dbfs:{dest}"))

        for lf in LABEL_FILES:
            dest = f"{vol}/labels/{os.path.basename(lf)}"
            if not os.path.exists(dest):
                with z.open(lf) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)

    df = spark.createDataFrame(manifest, "file_name string, cuad_category string, archive_member string, volume_path string")
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"`{a.catalog}`.raw.cuad_manifest")
    print(f"doc_limit={a.doc_limit} selected={len(picked)} copied={copied} already_present={skipped}")
    print(f"Files now in {vol}/pdfs: {len(os.listdir(vol + '/pdfs'))}")


if __name__ == "__main__":
    main()
