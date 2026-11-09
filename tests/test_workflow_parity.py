# SPDX-License-Identifier: Apache-2.0
"""The browser workflow engine (site/workflow.js) must behave exactly like src/aicontrols/workflow.py.

The same scripted scenario, successes and deliberate errors alike, runs through both engines. The
results of every step and the final scope file, audit hashes included, must be identical.
Skipped when Node is not installed.
"""
import datetime as dt
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import aicontrols
from aicontrols.scope import Scope
from parity_helpers import NODE, ROOT, node, norm, run_ops_py

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
EXEC, SECOND = "EXECUTIVE_APPROVER", "SECOND_LINE_RISK_MANAGER"
INCIDENT = "incident-management-breach-notification"


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


# ---- the scenario ---------------------------------------------------------------------------------------
def scenario():
    A, ARCH, OWN, RISK, ENG, AUD = "alice", "arch", "owner1", "risk", "engine", "auditor"
    o = []
    add = o.append
    add({"op": "clock", "iso": "2026-10-27T12:00:00Z"})
    add({"op": "actions"})  # workflow not enabled yet -> error
    add({"op": "enable", "by": A})
    add({"op": "enable", "by": A})
    add({"op": "profile", "by": A, "fields": {"risk_appetite": "reckless"}})
    add({"op": "profile", "by": A, "fields": {"boundary": "  "}})
    add({"op": "profile", "by": A, "fields": {"colour": "red"}})
    add({"op": "profile", "by": A, "fields": {"business_unit": "Retail", "environment": "Production, EU", "boundary": "Chatbot + order API",
                                              "asset_classes": ["models", "customer-data", " models "], "risk_appetite": "moderate", "target_default": "implemented"}})
    add({"op": "profile", "by": A, "fields": {"business_unit": "Retail"}})  # no change -> no audit event
    add({"op": "attest", "by": A, "action": "DEFINE_ORGANIZATIONAL_PROFILE_BOUNDARIES"})
    add({"op": "attest", "by": A, "action": "DEDUPLICATE_OVERLAPPING_REQUIREMENTS"})
    add({"op": "attest", "by": A, "role": "THIRD_LINE_AUDITOR", "action": "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS"})
    add({"op": "advance", "by": A})
    add({"op": "attest", "by": A, "action": "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS", "note": "reviewed with legal"})
    add({"op": "decide", "controls": ["gdpr:Art.4"], "changes": {"applicable": False, "justification": "Definitions only"}})
    add({"op": "decide", "controls": ["gdpr:Art.5(1)", "gdpr:Art.6"], "changes": {"status": "implemented", "owner": "Dana"}})
    add({"op": "decide", "controls": ["gdpr:Art.7"], "changes": {"status": "in_progress", "due": "2026-01-01"}})
    add({"op": "target", "by": A, "status": "verified", "by_date": "2026-12-31", "domain": INCIDENT})
    add({"op": "target", "by": A, "status": "verified", "by_date": "soon", "controls": ["gdpr:Art.33"]})
    add({"op": "target", "by": A, "status": "in_progress", "controls": ["gdpr:Art.33"]})
    add({"op": "target", "by": A, "status": "verified", "controls": ["eu-ai-act:Art.5"]})
    add({"op": "actions"})
    add({"op": "advance", "by": A})
    # stage 2
    add({"op": "cc_suggest", "min_frameworks": 2})
    add({"op": "cc_add", "by": ARCH, "title": "Manual process", "id": "CC-001"})
    add({"op": "cc_add", "by": ARCH, "title": "Dup", "id": "CC-001"})
    add({"op": "cc_add", "by": ARCH, "title": "Bad id", "id": "9bad"})
    add({"op": "cc_add", "by": ARCH, "title": " "})
    add({"op": "cc_map", "by": ARCH, "cc": "CC-001", "controls": ["gdpr:Art.34"]})
    add({"op": "cc_add", "by": ARCH, "title": "Second"})
    add({"op": "cc_map", "by": ARCH, "cc": "CC-002", "controls": ["gdpr:Art.34"]})
    add({"op": "cc_map", "by": ARCH, "cc": "CC-002", "controls": ["gdpr:Art.34"], "move": True})
    add({"op": "cc_map", "by": ARCH, "cc": "CC-002", "controls": ["gdpr:Art.4"]})
    add({"op": "cc_add", "by": ARCH, "title": "Custom id", "id": "SEC_1"})
    add({"op": "cc_map", "by": ARCH, "cc": "CC-404", "controls": ["gdpr:Art.34"]})
    add({"op": "cc_map", "by": ARCH, "cc": "CC-002", "controls": ["eu-ai-act:Art.5"]})
    add({"op": "gap_accept", "by": ARCH, "controls": ["gdpr:Art.8"], "reason": " "})
    add({"op": "gap_accept", "by": ARCH, "controls": ["gdpr:Art.8"], "reason": "Covered by processor DPA"})
    add({"op": "cc_apply", "by": ARCH})
    add({"op": "unmapped"})
    add({"op": "actions"})
    add({"op": "attest", "by": ARCH, "action": "DEDUPLICATE_OVERLAPPING_REQUIREMENTS"})
    add({"op": "actions"})
    add({"op": "advance", "by": ARCH})
    # stage 3
    add({"op": "actions"})
    add({"op": "cc_set", "by": OWN, "cc": "CC-001", "fields": {"owner": "Dana"}})
    add({"op": "cc_set", "by": OWN, "cc": "CC-001", "fields": {"reviewer": " dana "}})
    add({"op": "cc_set", "by": OWN, "cc": "CC-001", "fields": {"frequency": "hourly"}})
    add({"op": "cc_set", "by": OWN, "cc": "CC-001", "fields": {"test_type": "magic"}})
    add({"op": "cc_set", "by": OWN, "cc": "CC-001", "fields": {"colour": "red"}})
    add({"op": "cc_set", "by": OWN, "cc": "CC-404", "fields": {"owner": "x"}})
    add({"op": "cc_set_all", "by": OWN, "fields": {"owner": "owner1", "reviewer": "reviewer1", "frequency": "monthly", "implementation": "Documented procedure",
                                                   "evidence_required": ["evidence file", "log extract"], "test_type": "automated", "test_description": "nightly query",
                                                   "parameters": {"window": "72h"}}})
    add({"op": "cc_set", "by": OWN, "cc": "CC-001", "fields": {"frequency": "weekly", "evidence_required": ["log extract", "screenshot"]}})
    add({"op": "tailor", "by": OWN, "control": "gdpr:Art.33", "implementation": "Notify within 72 hours via the DPO"})
    add({"op": "tailor", "by": OWN, "control": "gdpr:Art.33", "implementation": " "})
    add({"op": "tailor", "by": OWN, "control": "eu-ai-act:Art.5", "implementation": "x"})
    add({"op": "actions"})
    add({"op": "advance", "by": OWN})
    # stage 4
    add({"op": "indicator", "by": RISK, "cc": "CC-001", "name": "Failed logins", "kind": "KRI", "metric": "failed_logins", "breach_op": ">", "value": 5})
    add({"op": "indicator", "by": RISK, "cc": "CC-001", "name": "Coverage", "kind": "KCI", "metric": "coverage", "breach_op": "<", "value": 95.5})
    add({"op": "indicator", "by": RISK, "cc": "CC-001", "name": "Big", "kind": "KRI", "metric": "records", "breach_op": ">=", "value": 2500000})
    add({"op": "indicator", "by": RISK, "cc": "CC-001", "name": "x", "kind": "KPI", "metric": "m", "breach_op": ">", "value": 1})
    add({"op": "indicator", "by": RISK, "cc": "CC-001", "name": "x", "kind": "KRI", "metric": "m", "breach_op": "==", "value": 1})
    add({"op": "ingest", "by": ENG, "source": "iam", "records": [
        {"control": "CC-001", "at": "2026-10-20T10:00:00Z", "result": "pass", "metrics": {"failed_logins": 2, "coverage": 99.9}},
        {"control": "CC-001", "at": "2026-10-20T10:00:00Z", "result": "pass", "metrics": {"failed_logins": 2}},
        {"control": "CC-001", "at": "2026-10-21", "result": "fail", "metrics": {"failed_logins": 9, "coverage": 90.25, "records": 3000000}},
        {"control": "CC-001", "at": "2026-10-22T10:00:00+02:00", "result": "pass", "metrics": {}},
        {"control": "CC-001", "at": "2026-10-23T10:00:00.789Z", "result": "error"},
        {"control": "CC-001", "at": "2026-10-24 08:30", "result": "pass", "evidence": "s3://run-1"},
        {"control": "CC-999", "at": "2026-10-20T10:00:00Z", "result": "pass"},
        {"control": "CC-001", "at": "2026-10-20T10:00:00Z", "result": "maybe"},
        {"control": "CC-001", "at": "yesterday", "result": "pass"},
        {"control": "CC-001", "at": "2026-13-45", "result": "pass"},
        {"control": "CC-001", "at": "2026-10-25", "result": "pass", "metrics": {"x": "high"}},
        {"control": "CC-001", "at": "2026-10-25", "result": "pass", "metrics": {"x": True}},
        "not an object", {"at": "2026-10-25", "result": "pass"}]})
    add({"op": "ingest_all", "by": ENG, "at": "2026-10-26T10:00:00Z", "result": "pass", "metrics": {"failed_logins": 1}})
    add({"op": "eff", "cc": "CC-001"})
    add({"op": "eff", "cc": "CC-002"})
    add({"op": "actions"})
    add({"op": "evaluate", "by": ENG})
    add({"op": "evaluate", "by": ENG})
    add({"op": "ack", "by": RISK, "key": "nope"})
    add({"op": "actions"})
    add({"op": "advance", "by": ENG})
    # stage 5
    add({"op": "actions"})
    add({"op": "ex_request", "by": A, "reason": " ", "controls": ["gdpr:Art.33"]})
    add({"op": "ex_request", "by": A, "reason": "x"})
    add({"op": "ex_request", "by": A, "reason": "x", "kind": "whim", "controls": ["gdpr:Art.33"]})
    add({"op": "ex_request", "by": A, "reason": "x", "controls": ["gdpr:Art.4"]})
    add({"op": "ex_request", "by": A, "reason": "Legacy system", "controls": ["gdpr:Art.33"], "compensating": "Weekly manual review"})
    add({"op": "ex_request", "by": A, "reason": "Vendor outage", "cc": "CC-001"})
    add({"op": "actions"})
    add({"op": "ex_assess", "by": "Alice", "id": "EX-001", "likelihood": 3, "impact": 3})
    add({"op": "ex_assess", "by": "bob", "id": "EX-001", "likelihood": 6, "impact": 3})
    add({"op": "ex_assess", "by": "bob", "id": "EX-001", "likelihood": 3, "impact": 3, "notes": "medium"})
    add({"op": "ex_assess", "by": "bob", "id": "EX-002", "likelihood": 1, "impact": 2})
    add({"op": "ex_approve", "by": "dana", "role": SECOND, "id": "EX-001", "days": 30})
    add({"op": "ex_approve", "by": "carol", "role": EXEC, "id": "EX-001", "days": 365})
    add({"op": "ex_approve", "by": "alice", "role": EXEC, "id": "EX-001", "days": 30})
    add({"op": "ex_approve", "by": "bob", "role": EXEC, "id": "EX-001", "days": 30})
    add({"op": "ex_approve", "by": "carol", "role": EXEC, "id": "EX-001", "days": 0})
    add({"op": "ex_approve", "by": "carol", "role": EXEC, "id": "EX-001", "days": 90})
    add({"op": "ex_approve", "by": "dana", "role": SECOND, "id": "EX-002", "days": 365})
    add({"op": "ex_reject", "by": "carol", "role": EXEC, "id": "EX-001", "reason": "late"})
    add({"op": "ex_reject", "by": "x", "role": "FIRST_LINE_CONTROL_OWNER", "id": "EX-001", "reason": "late"})
    add({"op": "policy", "by": RISK, "key": "colour", "value": "red"})
    add({"op": "policy", "by": RISK, "key": "reassess_warning_days", "value": "soon"})
    add({"op": "policy", "by": RISK, "key": "partial_threshold", "value": "0.95"})
    add({"op": "policy", "by": RISK, "key": "stale_factor", "value": "nan"})
    add({"op": "policy", "by": RISK, "key": "exception_max_days.high", "value": "60"})
    add({"op": "policy", "by": RISK, "key": "reassess_warning_days", "value": "30"})
    add({"op": "exceptions"})
    add({"op": "actions"})
    add({"op": "advance", "by": RISK})
    # time passes
    add({"op": "clock", "iso": "2026-12-20T12:00:00Z"})
    add({"op": "exceptions"})
    add({"op": "eff", "cc": "CC-001"})
    add({"op": "actions"})
    add({"op": "ex_reopen", "by": A, "id": "EX-001", "reason": "Still needed"})
    add({"op": "ex_reopen", "by": A, "id": "EX-001", "reason": "again"})
    add({"op": "ex_close", "by": RISK, "id": "EX-002", "reason": "no longer needed"})
    add({"op": "ex_close", "by": RISK, "id": "EX-002", "reason": "again"})
    add({"op": "clock", "iso": "2027-02-15T12:00:00Z"})
    add({"op": "exceptions"})
    add({"op": "evaluate", "by": ENG})
    add({"op": "gap", "by": AUD})
    add({"op": "poam"})
    add({"op": "actions"})
    add({"op": "advance", "by": AUD})
    add({"op": "report", "by": AUD})
    add({"op": "verify", "by": AUD})
    add({"op": "report_md", "by": AUD})
    add({"op": "actions"})
    add({"op": "validate"})
    add({"op": "advance", "by": AUD})
    add({"op": "restart", "by": A, "reason": "Quarterly review"})
    add({"op": "actions"})
    add({"op": "advance", "by": A, "force": True})
    add({"op": "advance", "by": A, "force": True, "reason": "Board deadline"})
    add({"op": "report", "by": AUD})
    add({"op": "verify", "by": AUD})
    return o


def fresh_scope(lib):
    s = Scope.new("Diff Org", lib)
    s.add_system("bot", "Bot", ["gdpr", "iso-27001"])
    return s


def test_python_and_browser_engines_agree_on_a_long_scenario(tmp_path, lib, monkeypatch):
    ops = scenario()
    py_scope = fresh_scope(lib)
    py_results = norm(run_ops_py(py_scope, lib, ops, monkeypatch))
    js = node(tmp_path, {"mode": "wfops", "scope": fresh_scope(lib).data, "ops": ops})
    # the scenario must actually exercise both outcomes, or the comparison would prove little
    assert sum(1 for r in py_results if "error" in r) >= 45 and sum(1 for r in py_results if "ok" in r) >= 75
    for i, (op, p, j) in enumerate(zip(ops, py_results, js["results"])):
        assert p == j, f"step {i} ({op['op']}) differs:\n python : {p}\n browser: {j}"
    assert js["scope"] == norm(py_scope.data)
    assert js["scope"]["audit"][-1]["hash"] == py_scope.data["audit"][-1]["hash"]
    assert len(js["scope"]["audit"]) > 80


# ---- hashing and canonical JSON -----------------------------------------------------------------------------
def test_sha256_and_canonical_json_match_python(tmp_path):
    strings = ["", "abc", "a" * 55, "a" * 56, "a" * 63, "a" * 64, "a" * 65, "a" * 1000, "é", "日本語", "emoji 😀 test", "line\nbreak\ttab", '{"k":"v"}']
    objects = [{"b": 1, "a": [True, False, None, "é\"\\/"]}, {}, [], {"z": {"y": {"x": [1, 2, {"w": None}]}}}, {"n": -5, "big": 12345678901},
               {"sp ace": "日本 ", "ctl": "\u0001\u001f\u007f"}, {"é": 1, "e": 2, "Z": 3, "a": 4}]
    js = node(tmp_path, {"mode": "sha", "strings": strings, "objects": objects})
    assert js["sha"] == [hashlib.sha256(s.encode("utf-8")).hexdigest() for s in strings]
    assert js["canon"] == [json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for o in objects]


def test_embedded_spec_equals_the_json_file(tmp_path):
    js = node(tmp_path, {"mode": "sha", "strings": [], "objects": []})
    assert js["spec"] == json.loads((ROOT / "src" / "aicontrols" / "workflow_spec.json").read_text())
