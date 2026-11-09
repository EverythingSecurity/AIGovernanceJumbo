# SPDX-License-Identifier: Apache-2.0
"""The browser GRC engine (site/grc.js) must behave exactly like src/aicontrols/grc.py.

One long scenario (successes and deliberate errors) runs through both engines; every step's result and the
final scope file, audit hashes included, must be identical. Skipped when Node is not installed.
"""
import copy
import json
import subprocess
import sys

import pytest

import aicontrols
from aicontrols.scope import Scope
from parity_helpers import NODE, ROOT, node, norm, run_ops_py

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


def fresh_scope(lib):
    s = Scope.new("Parity Org", lib)
    s.add_system("bot", "Bot", ["iso-42001", "gdpr"])
    return s


def outputs():
    """Every computed view, in a fixed order."""
    return [{"op": k} for k in ("grc_matrix_summary", "grc_matrix", "grc_matrix_csv", "grc_coverage", "grc_kpis", "grc_streams",
                                "grc_lifecycle", "grc_artifacts", "grc_roles_list", "grc_settings", "grc_validate")]


def scenario():
    A, ARCH = "alice", "arch"
    o = []
    add = o.append
    add({"op": "clock", "iso": "2026-11-09T12:00:00Z"})
    add({"op": "grc_matrix_summary"})                                   # workflow not enabled: everything unmapped
    add({"op": "enable", "by": A})
    # -- common controls and decisions
    add({"op": "cc_add", "by": ARCH, "title": "Incident response"})
    add({"op": "cc_map", "by": ARCH, "cc": "CC-001", "controls": ["gdpr:Art.33", "gdpr:Art.34", "iso-42001:A.8.4"]})
    add({"op": "cc_add", "by": ARCH, "title": "AI governance"})
    add({"op": "cc_map", "by": ARCH, "cc": "CC-002", "controls": ["iso-42001:A.2.2", "iso-42001:A.2.3", "iso-42001:A.2.4"]})
    add({"op": "cc_add", "by": ARCH, "title": "Data quality"})
    add({"op": "cc_map", "by": ARCH, "cc": "CC-003", "controls": ["iso-42001:A.7.4", "iso-42001:A.7.5", "gdpr:Art.5(1)"]})
    add({"op": "cc_add", "by": ARCH, "title": "No members yet"})
    add({"op": "gap_accept", "by": ARCH, "controls": ["gdpr:Art.8"], "reason": "Covered by the processor DPA, \"see\" annex"})
    add({"op": "gap_accept", "by": ARCH, "controls": ["gdpr:Art.7"], "reason": "=risky, text"})
    add({"op": "decide", "controls": ["gdpr:Art.33"], "changes": {"status": "implemented", "owner": "Dana"}})
    add({"op": "decide", "controls": ["gdpr:Art.34"], "changes": {"status": "in_progress"}})
    add({"op": "decide", "controls": ["iso-42001:A.2.2"], "changes": {"status": "verified"}})
    add({"op": "decide", "controls": ["iso-42001:A.7.4"], "changes": {"status": "implemented", "owner": "Eli"}})
    add({"op": "decide", "controls": ["gdpr:Art.4"], "changes": {"applicable": False, "justification": "Definitions only"}})
    o += outputs()
    # -- documents: errors, then successes
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "memo", "title": "x", "owner": "o"}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "policy", "title": "x", "owner": "o", "approved": "1/2/2026"}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "policy", "title": "x", "owner": "o", "review_months": "0"}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "policy", "title": "x", "owner": "o", "colour": "red"}})
    add({"op": "grc_add", "register": "widgets", "by": A, "fields": {"title": "x"}})
    add({"op": "grc_add", "register": "documents", "by": "  ", "fields": {"type": "policy", "title": "x", "owner": "o"}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "policy", "title": "AI Governance Policy", "owner": "CISO", "status": "approved", "review_months": 6}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "policy", "title": "Draft policy", "owner": "CISO"}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "guideline", "title": "Secure ML guideline", "owner": "Architecture", "url": "https://x.example/g"}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "sop", "title": "Incident SOP", "owner": "SecOps", "status": "approved", "approved": "2025-01-31", "review_months": 1}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "sop", "title": "Old SOP", "owner": "SecOps", "status": "approved", "approved": "2024-01-31", "review_months": 12, "next_review": "2025-01-31"}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "sop", "title": "Leap SOP", "owner": "SecOps", "status": "approved", "approved": "2028-01-31", "review_months": 1}})
    add({"op": "grc_add", "register": "documents", "by": A, "fields": {"type": "guideline", "title": "Year-end", "owner": "A", "status": "approved", "approved": "2026-12-15", "review_months": 12}})
    add({"op": "grc_update", "register": "documents", "by": A, "id": "DOC-001", "fields": {"review_months": 3}})
    add({"op": "grc_update", "register": "documents", "by": A, "id": "DOC-001", "fields": {"next_review": "2031-01-01"}})
    add({"op": "grc_update", "register": "documents", "by": A, "id": "DOC-003", "fields": {"url": ""}})
    add({"op": "grc_update", "register": "documents", "by": A, "id": "DOC-003", "fields": {"owner": ""}})
    add({"op": "grc_update", "register": "documents", "by": A, "id": "DOC-999", "fields": {"title": "x"}})
    add({"op": "grc_update", "register": "documents", "by": A, "id": "DOC-002", "fields": {"status": "approved"}})
    add({"op": "grc_records", "register": "documents"})
    # -- risks, findings, audits, scope items
    add({"op": "grc_add", "register": "risks", "by": A, "fields": {"title": "Model leak", "business_unit": "Retail", "owner": "Fay", "residual": "high"}})
    add({"op": "grc_add", "register": "risks", "by": A, "fields": {"title": "Minor", "business_unit": "Retail", "department": "Support", "owner": "Fay", "residual": "medium", "inherent": "high"}})
    add({"op": "grc_add", "register": "risks", "by": A, "fields": {"title": "Treated", "business_unit": "Ops", "owner": "Gus", "residual": "critical", "treatment_plan": "Encrypt weights"}})
    add({"op": "grc_add", "register": "risks", "by": A, "fields": {"title": "Planned", "business_unit": "Ops", "owner": "Gus", "residual": "high", "treatment_status": "planned"}})
    add({"op": "grc_add", "register": "risks", "by": A, "fields": {"title": "Closed", "business_unit": "Ops", "owner": "Gus", "residual": "critical", "status": "closed"}})
    add({"op": "grc_add", "register": "risks", "by": A, "fields": {"title": "No residual", "business_unit": "Ops", "owner": "Gus"}})
    add({"op": "grc_add", "register": "findings", "by": A, "fields": {"title": "Critical finding", "severity": "critical", "source": "internal", "owner": "Hal", "raised": "2026-09-01", "due": "2026-10-01"}})
    add({"op": "grc_add", "register": "findings", "by": A, "fields": {"title": "Minor finding", "severity": "low", "source": "external", "owner": "Hal", "raised": "2026-09-01", "due": "2026-12-01"}})
    add({"op": "grc_add", "register": "findings", "by": A, "fields": {"title": "Bad dates", "severity": "low", "source": "external", "owner": "Hal", "raised": "2026-11-01", "due": "2026-10-01"}})
    add({"op": "grc_update", "register": "findings", "by": A, "id": "FND-002", "fields": {"status": "closed"}})
    add({"op": "grc_update", "register": "findings", "by": A, "id": "FND-002", "fields": {"status": "open"}})
    add({"op": "grc_add", "register": "audits", "by": A, "fields": {"title": "Internal audit Q3", "kind": "internal", "planned": "2026-10-01", "completed": "2026-10-20", "auditor": "Ivy"}})
    add({"op": "grc_add", "register": "audits", "by": A, "fields": {"title": "Management review", "kind": "management_review", "planned": "2026-10-25", "completed": "2026-10-26"}})
    add({"op": "grc_add", "register": "audits", "by": A, "fields": {"title": "Certification audit", "kind": "external", "planned": "2027-02-01"}})
    add({"op": "grc_add", "register": "audits", "by": A, "fields": {"title": "Backwards", "kind": "internal", "planned": "2026-11-05", "completed": "2026-11-01"}})
    add({"op": "grc_add", "register": "scope_items", "by": A, "fields": {"kind": "regulation", "name": "DORA"}})
    add({"op": "grc_add", "register": "scope_items", "by": A, "fields": {"kind": "business_unit", "name": "Retail", "owner": "Jo"}})
    add({"op": "grc_add", "register": "scope_items", "by": A, "fields": {"kind": "ai_system", "name": "Support bot"}})
    add({"op": "grc_add", "register": "scope_items", "by": A, "fields": {"kind": "data_set", "name": "Support transcripts"}})
    add({"op": "grc_add", "register": "scope_items", "by": A, "fields": {"kind": "exclusion", "name": "Legacy ERP"}})
    add({"op": "grc_add", "register": "scope_items", "by": A, "fields": {"kind": "exclusion", "name": "Legacy ERP", "justification": "Decommissioned in Q1"}})
    add({"op": "grc_seed", "by": A})
    add({"op": "grc_seed", "by": A})
    add({"op": "grc_add", "register": "evidence_sources", "by": A, "fields": {"type": "Model cards", "source": "Registry", "frequency": "per_release"}})
    add({"op": "grc_add", "register": "evidence_sources", "by": A, "fields": {"type": "x", "source": "y", "frequency": "hourly"}})
    # -- links, mapping reviews
    add({"op": "grc_link", "by": A, "cc": "CC-001", "policy": ["DOC-001"], "sop": ["DOC-004"], "evidence_sources": ["EVS-003"]})
    add({"op": "grc_link", "by": A, "cc": "CC-001", "sop": ["DOC-001"]})
    add({"op": "grc_link", "by": A, "cc": "CC-001", "policy": ["DOC-404"]})
    add({"op": "grc_link", "by": A, "cc": "CC-001", "evidence_sources": ["EVS-404"]})
    add({"op": "grc_link", "by": A, "cc": "CC-001"})
    add({"op": "grc_link", "by": A, "cc": "CC-404", "policy": ["DOC-001"]})
    add({"op": "grc_link", "by": A, "cc": "CC-002", "policy": ["DOC-001"], "guideline": ["DOC-003"], "sop": ["DOC-005"], "evidence_sources": ["EVS-001", "EVS-006"]})
    add({"op": "grc_link", "by": A, "cc": "CC-002", "evidence_sources": ["EVS-006"], "unlink": True})
    add({"op": "grc_mapping_review", "by": A, "cc": "CC-001", "owner": "Head of SecOps"})
    add({"op": "grc_mapping_review", "by": A, "cc": "CC-002", "owner": "GRC lead", "date": "2025-01-15"})
    add({"op": "grc_mapping_review", "by": A, "cc": "CC-001", "owner": " "})
    add({"op": "grc_mapping_review", "by": A, "cc": "CC-001", "owner": "x", "date": "9 Nov"})
    add({"op": "grc_mapping_review", "by": A, "cc": "CC-004", "owner": "x"})
    # -- settings, roles, scope statements
    for key, value in (("risk_appetite", "low"), ("coverage_target.gdpr", "70"), ("coverage_target.iso-42001", "90"), ("mapping_review_months", "6"),
                       ("anchor_framework", "iso-42001"), ("scope_review_months", "12"), ("coverage_target.gdpr", ""),
                       ("risk_appetite", "wild"), ("mapping_review_months", "0"), ("coverage_target.gdpr", "101"), ("coverage_target.nope", "5"),
                       ("anchor_framework", "nope"), ("colour", "x")):
        add({"op": "grc_setting", "by": A, "key": key, "value": value})
    add({"op": "grc_roles", "by": A, "role": "ciso_grc", "names": ["Dana", " Dana ", "Eli"]})
    add({"op": "grc_roles", "by": A, "role": "internal_audit", "names": ["Fay"]})
    add({"op": "grc_roles", "by": A, "role": "internal_audit", "names": []})
    add({"op": "grc_roles", "by": A, "role": "wizard", "names": ["x"]})
    add({"op": "grc_scope_statement", "by": A, "framework": "gdpr", "statement": "EU customers' data", "reviewed": "2026-10-01"})
    add({"op": "grc_scope_statement", "by": A, "framework": "nope", "statement": "x"})
    add({"op": "grc_scope_statement", "by": A, "framework": "gdpr", "statement": " "})
    add({"op": "grc_scope_review", "by": A})
    add({"op": "grc_scope_review", "by": A, "date": "tomorrow"})
    # -- boundaries: a review due exactly today is not overdue / not stale
    add({"op": "grc_mapping_review", "by": A, "cc": "CC-003", "owner": "Boundary", "date": "2026-05-09"})
    add({"op": "grc_scope_review", "by": A, "date": "2025-11-09"})
    add({"op": "grc_scope_statement", "by": A, "framework": "iso-42001", "statement": "AIMS scope", "reviewed": "2025-11-09"})
    # -- evidence, workflow markers, report
    add({"op": "ingest", "by": "engine", "source": "siem", "records": [
        {"control": "CC-001", "at": "2026-11-08T10:00:00Z", "result": "pass"}, {"control": "CC-002", "at": "2026-11-01T10:00:00Z", "result": "fail"}]})
    add({"op": "gap", "by": "auditor"})
    o += outputs()
    add({"op": "grc_report", "by": A})
    add({"op": "grc_report_md", "by": A})
    o += outputs()
    # -- removing documents and sources removes their links
    add({"op": "grc_remove", "register": "documents", "by": A, "id": "DOC-001"})
    add({"op": "grc_remove", "register": "evidence_sources", "by": A, "id": "EVS-003"})
    add({"op": "grc_remove", "register": "documents", "by": A, "id": "DOC-404"})
    add({"op": "grc_matrix"})
    # -- time passes: reviews fall overdue, evidence goes stale, documents lapse
    add({"op": "cc_set", "by": "owner1", "cc": "CC-001", "fields": {"frequency": "monthly"}})
    add({"op": "clock", "iso": "2027-12-20T12:00:00Z"})
    o += outputs()
    add({"op": "grc_report_md", "by": A})
    for reg in ("documents", "risks", "findings", "audits", "scope_items", "evidence_sources"):
        add({"op": "grc_records", "register": reg})
    return o


def test_python_and_browser_grc_engines_agree_on_a_long_scenario(tmp_path, lib, monkeypatch):
    ops = scenario()
    py_scope = fresh_scope(lib)
    py_results = norm(run_ops_py(py_scope, lib, ops, monkeypatch))
    js = node(tmp_path, {"mode": "wfops", "scope": fresh_scope(lib).data, "ops": ops})
    errors = sum(1 for r in py_results if "error" in r)
    assert errors >= 30 and sum(1 for r in py_results if "ok" in r) >= 120      # both outcomes are really exercised
    for i, (op, p, j) in enumerate(zip(ops, py_results, js["results"])):
        assert p == j, f"step {i} ({op['op']}) differs:\n python : {str(p)[:600]}\n browser: {str(j)[:600]}"
    assert js["scope"] == norm(py_scope.data)
    assert js["scope"]["audit"][-1]["hash"] == py_scope.data["audit"][-1]["hash"] and len(js["scope"]["audit"]) > 60
    assert js["scope"]["schema_version"] == "1.2"


def test_spec_files_are_in_step(tmp_path):
    spec = json.loads((ROOT / "src" / "aicontrols" / "grc_spec.json").read_text(encoding="utf-8"))
    js = node(tmp_path, {"mode": "sha", "strings": [], "objects": []})
    assert js["grc_spec"] == spec
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_site_spec.py"), "--check"], capture_output=True)
    assert r.returncode == 0, "site/grc-spec.js is stale: run python tools/build_site_spec.py"


def test_validation_of_corrupted_grc_data_matches_python(tmp_path, lib, monkeypatch):
    py_scope = fresh_scope(lib)
    setup = [op for op in scenario() if op["op"] in ("clock", "enable", "cc_add", "cc_map") or (op["op"] == "grc_add" and op["register"] in ("documents", "evidence_sources"))
             or op["op"] == "grc_link"]
    run_ops_py(py_scope, lib, setup, monkeypatch)
    data = copy.deepcopy(py_scope.data)
    cases = []
    bad = copy.deepcopy(data)
    bad["grc"]["documents"]["DOC-001"]["type"] = "memo"
    bad["grc"]["risks"] = {"RSK-009": {"id": "RSK-009", "title": "x"}}
    bad["grc"]["findings"] = {"FND-001": {"id": "FND-002", "title": "t", "severity": "low", "source": "internal", "owner": "o", "raised": "2026-10-02", "due": "2026-10-01"}}
    bad["workflow"]["bot"]["common_controls"]["CC-001"]["documents"]["sop"] = ["DOC-404"]
    bad["workflow"]["bot"]["common_controls"]["CC-001"]["evidence_sources"] = ["EVS-404"]
    bad["grc"]["framework_scopes"] = {"nope": {"statement": "x", "reviewed": "2026-01-01"}}
    bad["grc"]["roles"] = {"wizard": ["x"]}
    bad["grc"]["settings"] = {"anchor_framework": "nope"}
    cases.append(bad)
    cases.append(copy.deepcopy(data))
    for case in cases:
        want = dict(zip(("errors", "warnings"), __import__("aicontrols.grc", fromlist=["validate_grc"]).validate_grc(Scope(copy.deepcopy(case), lib))))
        js = node(tmp_path, {"mode": "wfops", "scope": copy.deepcopy(case), "ops": [{"op": "grc_validate"}]})
        assert sorted(js["results"][0]["ok"]["errors"]) == sorted(want["errors"]) and js["results"][0]["ok"]["warnings"] == want["warnings"]
    assert want["errors"] == [] and len(dict(zip(("e",), [[]]))["e"]) == 0
