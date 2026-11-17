"""Unit tests for pure-Python helpers (no workspace needed): .venv/bin/python -m pytest tests"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The setup scripts import pyspark at module level; stub it so helpers can be tested locally.
sys.modules.setdefault("pyspark", types.ModuleType("pyspark"))
_sql = types.ModuleType("pyspark.sql")
_sql.SparkSession = object
sys.modules.setdefault("pyspark.sql", _sql)


def load(rel):
    spec = importlib.util.spec_from_file_location(rel.replace("/", "_"), os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


dl = load("src/setup/00_download_cuad.py")
runner = load("src/setup/run_sql_file.py")


def _members():
    p = dl.PDF_PREFIX
    return [f"{p}Part_I/A/a{i}.pdf" for i in range(5)] + [f"{p}Part_II/B/b{i}.pdf" for i in range(2)] + \
           [f"{p}Part_III/C/c{i}.pdf" for i in range(3)]


def test_subset_round_robins_categories():
    picked = dl.select_subset(_members(), 6)
    cats = [c for c, _ in picked]
    assert cats[:3] == ["A", "B", "C"] and len(picked) == 6


def test_subset_is_prefix_stable():
    small = dl.select_subset(_members(), 4)
    big = dl.select_subset(_members(), 8)
    assert big[: len(small)] == small


def test_subset_caps_at_available():
    assert len(dl.select_subset(_members(), 100)) == 10


def test_sql_sections_and_allow_fail():
    text = """-- @section pre
CREATE A;
-- comment
CREATE B
  MULTI;
-- @section post
-- @allow_fail
GRANT X;
ALTER Y;"""
    secs = runner.parse_sections(text)
    pre = runner.split_statements(secs["pre"])
    post = runner.split_statements(secs["post"])
    assert [s for s, _ in pre] == ["CREATE A", "CREATE B\n  MULTI"]
    assert post == [("GRANT X", True), ("ALTER Y", False)]


def test_governance_sql_parses():
    secs = runner.parse_sections(open(os.path.join(ROOT, "src/setup/02_uc_governance.sql")).read())
    assert set(secs) == {"pre", "post"}
    assert len(runner.split_statements(secs["pre"])) == 7
