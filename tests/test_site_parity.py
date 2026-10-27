# SPDX-License-Identifier: Apache-2.0
"""The browser logic (site/*.js) must behave exactly like the Python package.

Runs site/wizard.js and site/scope.js under Node and compares their output with
src/aicontrols/wizard.py and scope.py. Skipped when Node is not installed.
"""
import copy
import csv
import io
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

import aicontrols
from aicontrols import wizard as pywizard
from aicontrols.scope import Scope

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


def node(tmp_path, job):
    p = tmp_path / "job.json"
    p.write_text(json.dumps(job), encoding="utf-8")
    r = subprocess.run([NODE, str(ROOT / "tests" / "site_harness.js"), str(p)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def answer_sets():
    rng = random.Random(20261022)
    sets = [{}, {"eu": "yes", "personal_data": "yes"},
            json.loads((ROOT / "examples" / "wizard-answers.json").read_text())]
    for _ in range(250):
        sets.append({q.id: rng.choice(q.choices) for q in pywizard.QUESTIONS if rng.random() < 0.85})
    return sets


def test_wizard_recommendations_match_python(tmp_path, lib):
    sets = answer_sets()
    js = node(tmp_path, {"mode": "wizard", "answers_list": sets})
    for answers, got in zip(sets, js):
        want = [r.to_dict() for r in pywizard.recommend(answers, lib)]
        assert got == want, f"mismatch for {answers}"


def test_wizard_validation_errors_match_python(tmp_path):
    bad = [{"eu": "maybe"}, {"colour": "x"}, {"role": "p"}, {"certification": "i"}, {"eu": "Y"}]
    js = node(tmp_path, {"mode": "errors", "answers_list": bad})
    for answers, got in zip(bad, js):
        try:
            pywizard.normalize(answers)
            want = None
        except pywizard.WizardError as e:
            want = str(e)
        assert got == want


def scope_with_decisions(lib):
    s = Scope.load(ROOT / "examples" / "chatbot-scope.json", lib)
    sid = "support-chatbot"
    pick = lambda ids: s.select(sid, ids)  # noqa: E731
    s.set(sid, pick(["gdpr:Art.34"]), status="verified", owner="DPO", due="2026-01-05")
    s.set(sid, pick(["iso-42001:A.2.2"]), status="in_progress", due="2026-03-01", evidence=["policy v1", "policy v2"])
    s.set(sid, pick(["gdpr:Art.4"]), applicable=False, justification="Definitions only; no action", notes="a | b\nc")
    s.set(sid, pick(["gdpr:Art.5(1)"]), owner="=SUM(A1)", notes="-starts with dash")
    return s


def test_scope_calculations_and_exports_match_python(tmp_path, lib):
    s = scope_with_decisions(lib)
    sid, today = "support-chatbot", "2026-06-01"
    js = node(tmp_path, {"mode": "scope", "scope": s.data, "system": sid, "today": today})
    assert js["overall"] == s.overall(sid)
    assert js["status_framework"] == s.status(sid, "framework")
    assert js["status_domain"] == s.status(sid, "domain")
    py_plan = s.plan(sid, today=today)
    assert js["plan"] == py_plan
    assert js["soa_rows"] == s.soa_rows(sid)
    assert js["plan_md"] == s.plan_markdown(sid, py_plan[:5], len(py_plan))
    assert js["soa_md"] == s.soa_markdown(sid)
    py_csv = io.StringIO()
    s.write_soa(sid, py_csv)
    parse = lambda text: list(csv.DictReader(io.StringIO(text, newline="")))  # noqa: E731
    assert parse(js["soa_csv"]) == parse(py_csv.getvalue())
    assert js["validate"] == {"errors": [], "warnings": []} or js["validate"]["errors"] == []


def test_csv_neutralises_formulas_in_both_implementations(tmp_path, lib):
    s = scope_with_decisions(lib)
    js = node(tmp_path, {"mode": "scope", "scope": s.data, "system": "support-chatbot", "today": "2026-06-01"})
    py_csv = io.StringIO()
    s.write_soa("support-chatbot", py_csv)
    for text in (js["soa_csv"], py_csv.getvalue()):
        rows = list(csv.DictReader(io.StringIO(text, newline="")))
        row = next(r for r in rows if r["control_id"] == "gdpr:Art.5(1)")
        assert row["owner"] == "'=SUM(A1)" and row["notes"] == "'-starts with dash"


def test_validation_matches_python_on_a_corrupted_file(tmp_path, lib):
    s = scope_with_decisions(lib)
    bad = copy.deepcopy(s.data)
    sid = "support-chatbot"
    bad["decisions"][sid]["gdpr:Art.33"]["status"] = "bogus"
    bad["decisions"][sid]["gdpr:Art.34"] = {"applicable": False}
    bad["decisions"][sid]["dora:Art.5"] = {}
    bad["decisions"][sid]["gdpr:Art.35"] = {"due": "31/12/2026"}
    bad["decisions"]["ghost"] = {}
    bad["dataset_version"] = "0.0.1"
    js = node(tmp_path, {"mode": "scope", "scope": bad, "system": sid, "today": "2026-06-01"})
    errors, warnings = Scope(bad, lib).validate()
    assert sorted(js["validate"]["errors"]) == sorted(errors)
    # the only intentional difference: the browser says "this site" where the CLI says "installed dataset"
    site_warnings = [w.replace("this site has", "installed dataset is") for w in js["validate"]["warnings"]]
    assert sorted(site_warnings) == sorted(warnings)


def test_browser_accepts_a_workflow_enabled_scope_file_and_keeps_it_intact(tmp_path, lib):
    from aicontrols.workflow import Workflow
    s = Scope.load(ROOT / "examples" / "chatbot-scope.json", lib)
    w = Workflow(s)
    w.enable("support-chatbot", "alice")
    w.cc_add("support-chatbot", "arch", "Incident response", domain="incident")
    w.cc_map("support-chatbot", "arch", "CC-001", ["gdpr:Art.33"])
    assert s.data["schema_version"] == "1.1" and s.validate()[0] == []
    js = node(tmp_path, {"mode": "scope", "scope": s.data, "system": "support-chatbot", "today": "2026-06-01"})
    assert js["validate"]["errors"] == []  # a 1.1 file is not rejected by the browser
    assert js["overall"] == s.overall("support-chatbot")  # decisions with workflow fields still count the same


def test_files_built_by_the_browser_logic_pass_python_validation_and_schema(tmp_path, lib):
    answers = json.loads((ROOT / "examples" / "wizard-answers.json").read_text())
    built = node(tmp_path, {"mode": "build", "answers": answers})
    assert Scope(built, lib).validate() == ([], [])
    p = tmp_path / "from-browser.json"
    p.write_text(json.dumps(built), encoding="utf-8")
    again = Scope.load(p, lib)  # loads and round-trips through the Python implementation
    assert again.overall("bot")["total"] > 200
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schema" / "scope.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(built)
    assert built["systems"][0]["scoping"]["include_level"] == "consider"
    assert built["decisions"]["bot"][next(iter(built["decisions"]["bot"]))]["evidence"] == ["a", "b"]
