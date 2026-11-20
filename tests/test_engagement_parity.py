# SPDX-License-Identifier: Apache-2.0
"""The browser engagement engine (site/engagement.js) must behave exactly like src/aicontrols/engagement.py.

One long scenario (successes and deliberate errors) runs through both engines; every step's result and the
final scope file, audit hashes included, must be identical. Skipped when Node is not installed.
"""
import copy
import json
import subprocess
import sys

import pytest

import aicontrols
from aicontrols.engagement import validate_engagement
from aicontrols.scope import Scope
from parity_helpers import NODE, ROOT, node, norm, run_ops_py

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

P = "pam"
FULL = {"j_countries": ["qatar", "eu"], "j_customer_locations": ["qatar"], "i_sector": "banking", "r_financial_entity": "no",
        "r_ict_provider_to_fe": "no", "r_essential_service": "no", "d_personal": "yes", "d_special": "no", "d_volume": "large",
        "a_role": ["develop", "deploy"], "a_eu_market": "yes", "t_cloud": "yes", "t_outsourcing": "yes", "c_needs_cert": "yes", "o_size": "large"}
CUSTOM = {"id": "R-OUTSOURCE", "framework": "iso-27001", "confidence": "low", "weight": 10, "rationale": "Outsources ICT.",
          "when": {"all": [{"q": "t_outsourcing", "op": "is", "value": "yes"}, {"not": {"q": "o_size", "op": "in", "value": ["micro"]}}]}}


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


def fresh(lib):
    return Scope.new("Acme Bank", lib)


def answers(by=P):
    return [{"op": "eng_answer", "by": by, "q": q, "value": v} for q, v in FULL.items()]


def nested(n):
    cond = {"q": "d_personal", "op": "is", "value": "yes"}
    for _ in range(n):
        cond = {"not": cond}
    return cond


def scenario():
    o, add = [], None
    add = o.append
    add({"op": "clock", "iso": "2026-11-20T09:00:00Z"})
    add({"op": "eng_overview"})
    add({"op": "eng_answer", "by": P, "q": "j_countries", "value": ["eu"]})            # not started
    add({"op": "eng_client", "by": P, "fields": {"name": "Acme Bank", "sector": "banking", "country": "Qatar"}})
    add({"op": "eng_client", "by": P, "fields": {"sector": "mining"}})
    add({"op": "eng_client", "by": P, "fields": {"size": "huge"}})
    add({"op": "eng_client", "by": P, "fields": {"colour": "red"}})
    add({"op": "eng_client", "by": P, "fields": {"country": "  "}})
    add({"op": "eng_client", "by": " ", "fields": {"country": "Qatar"}})
    add({"op": "eng_onboard", "by": P})                                              # profile incomplete
    add({"op": "eng_answer", "by": P, "q": "j_countries", "value": ["eu"]})            # not onboarded
    add({"op": "eng_client", "by": P, "fields": {"size": "large", "contributor": "Dina"}})
    add({"op": "eng_onboard", "by": P})
    add({"op": "eng_onboard", "by": P})
    add({"op": "eng_overview"})
    add({"op": "eng_progress"})
    # answers: valid and invalid
    add({"op": "eng_answer", "by": "dina", "q": "nope", "value": "x"})
    add({"op": "eng_answer", "by": "dina", "q": "d_personal", "value": "maybe"})
    add({"op": "eng_answer", "by": "dina", "q": "i_sector", "value": "mining"})
    add({"op": "eng_answer", "by": "dina", "q": "j_countries", "value": []})
    add({"op": "eng_answer", "by": "dina", "q": "j_countries", "value": ["mars"]})
    add({"op": "eng_answer", "by": "dina", "q": "j_countries", "value": "eu"})
    add({"op": "eng_delegate", "by": "dina", "q": "d_volume", "to": "Data office", "due": "2026-12-01"})
    add({"op": "eng_delegate", "by": "dina", "q": "d_volume", "to": "Data office", "due": "01/12/2026"})
    add({"op": "eng_delegate", "by": "dina", "q": "d_volume", "to": " "})
    add({"op": "eng_delegate", "by": "dina", "q": "nope", "to": "x"})
    add({"op": "eng_submit", "by": "dina"})                                           # unanswered
    o.extend(answers("dina"))
    add({"op": "eng_answer", "by": "dina", "q": "c_contract_standards", "value": ["iso-27701", "iso-27001"]})
    add({"op": "eng_progress"})
    add({"op": "eng_questionnaire"})
    add({"op": "eng_recommend", "by": P})                                             # not submitted
    add({"op": "eng_submit", "by": "dina"})
    add({"op": "eng_submit", "by": "dina"})
    add({"op": "eng_answer", "by": "dina", "q": "d_personal", "value": "no"})        # locked
    add({"op": "eng_delegate", "by": "dina", "q": "t_apis", "to": "x"})               # locked
    add({"op": "eng_review", "by": P, "framework": "gdpr", "action": "accept"})        # no recommendation yet
    add({"op": "eng_finalise", "by": P})
    # rules
    add({"op": "eng_rules"})
    add({"op": "eng_compute"})
    add({"op": "eng_rule_set", "by": P, "rule": CUSTOM})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "id": "bad"}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "confidence": "certain"}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "weight": 0}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "weight": True}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "rationale": " "}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "framework": "Bad Id"}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "colour": 1}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "when": {"q": "nope", "op": "is", "value": "x"}}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "when": {"q": "j_countries", "op": "is", "value": "eu"}}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "when": {"q": "d_personal", "op": "has", "value": "yes"}}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "when": {"q": "d_personal", "op": "like", "value": "yes"}}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "when": {"q": "d_personal", "op": "in", "value": []}}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "when": {"all": []}}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "when": {"q": "d_personal"}}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "when": "yes"}})
    add({"op": "eng_rule_set", "by": P, "rule": "text"})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "id": "R-DEEP-OK", "when": nested(8)}})
    add({"op": "eng_rule_set", "by": P, "rule": {**CUSTOM, "id": "R-DEEP-BAD", "when": nested(9)}})
    add({"op": "eng_rule_disable", "by": P, "rule": "R-DEEP-OK"})
    add({"op": "eng_rule_set", "by": P, "rule": {"id": "R-GDPR", "framework": "gdpr", "confidence": "medium", "weight": 5, "rationale": "Overridden.",
                                                 "when": {"q": "d_special", "op": "is", "value": "yes"}}})
    add({"op": "eng_rule_disable", "by": P, "rule": "R-AI-NIST"})
    add({"op": "eng_rule_disable", "by": P, "rule": "R-AI-NIST"})
    add({"op": "eng_rule_disable", "by": P, "rule": "R-NOPE"})
    add({"op": "eng_rule_disable", "by": P, "rule": "R-AI-NIST", "disabled": False})
    add({"op": "eng_rule_disable", "by": P, "rule": "R-AI-NIST", "disabled": False})
    add({"op": "eng_rule_set", "by": P, "rule": {"id": "R-GDPR", "framework": "gdpr", "confidence": "high", "weight": 85, "rationale": "Restored.",
                                                 "when": {"all": [{"q": "d_personal", "op": "is", "value": "yes"},
                                                                  {"any": [{"q": "j_countries", "op": "has", "value": "eu"}]}]}}})
    add({"op": "eng_rules"})
    add({"op": "eng_compute"})
    # recommend, review, finalise
    add({"op": "eng_recommend", "by": P})
    add({"op": "eng_review", "by": "assessor", "framework": "nope", "action": "accept"})
    add({"op": "eng_review", "by": "assessor", "framework": "gdpr", "action": "ignore"})
    add({"op": "eng_review", "by": "assessor", "framework": "dora", "action": "accept"})         # not recommended
    add({"op": "eng_review", "by": "assessor", "framework": "dora", "action": "remove", "reason": "x"})
    add({"op": "eng_review", "by": "assessor", "framework": "dora", "action": "add"})            # no justification
    add({"op": "eng_review", "by": "assessor", "framework": "gdpr", "action": "add", "reason": "x"})
    add({"op": "eng_review", "by": "assessor", "framework": "gdpr", "action": "remove"})        # no justification
    add({"op": "eng_finalise", "by": "admin"})                                                    # unreviewed
    for fw in ("eu-ai-act", "gdpr", "iso-27701", "iso-42001", "iso-27001"):
        add({"op": "eng_review", "by": "assessor", "framework": fw, "action": "accept"})
    add({"op": "eng_review", "by": "assessor", "framework": "nist-ai-rmf", "action": "remove", "reason": "Client uses ISO 42001 instead"})
    add({"op": "eng_review", "by": "assessor", "framework": "dora", "action": "add", "reason": "Group parent is an EU bank"})
    add({"op": "eng_applicable"})
    add({"op": "eng_overview"})
    add({"op": "eng_finalise", "by": "admin", "reason": "Agreed with client"})
    add({"op": "eng_finalise", "by": "admin"})
    add({"op": "eng_review", "by": "assessor", "framework": "gdpr", "action": "accept"})        # finalised
    add({"op": "eng_recommend", "by": P})                                                       # finalised
    add({"op": "eng_reopen_assignment", "by": "admin", "reason": " "})
    add({"op": "eng_reopen_assignment", "by": "admin", "reason": "Scope changed"})
    add({"op": "eng_reopen_assignment", "by": "admin", "reason": "again"})
    add({"op": "eng_overview"})
    add({"op": "eng_validate"})
    # reopen scoping clears recommendations
    add({"op": "eng_reopen", "by": "dina", "reason": " "})
    add({"op": "eng_reopen", "by": "dina", "reason": "New AI use case"})
    add({"op": "eng_reopen", "by": "dina", "reason": "again"})
    add({"op": "eng_overview"})
    add({"op": "eng_answer", "by": "dina", "q": "a_gpai", "value": "yes"})
    add({"op": "eng_answer", "by": "dina", "q": "o_maturity", "value": "initial"})
    add({"op": "eng_submit", "by": "dina"})
    add({"op": "eng_rule_disable", "by": P, "rule": "R-EUAI"})
    add({"op": "eng_recommend", "by": P})
    add({"op": "eng_overview"})
    add({"op": "eng_validate"})
    return o


def test_python_and_browser_engagement_engines_agree_on_a_long_scenario(tmp_path, lib, monkeypatch):
    ops = scenario()
    py_scope = fresh(lib)
    py_results = norm(run_ops_py(py_scope, lib, ops, monkeypatch))
    js = node(tmp_path, {"mode": "wfops", "scope": fresh(lib).data, "ops": ops})
    errors = sum(1 for r in py_results if "error" in r)
    assert errors >= 45 and sum(1 for r in py_results if "ok" in r) >= 60      # both outcomes are really exercised
    for i, (op, p, j) in enumerate(zip(ops, py_results, js["results"])):
        assert p == j, f"step {i} ({op['op']}) differs:\n python : {str(p)[:600]}\n browser: {str(j)[:600]}"
    assert len(js["results"]) == len(py_results)
    assert js["scope"] == norm(py_scope.data)
    assert js["scope"]["audit"][-1]["hash"] == py_scope.data["audit"][-1]["hash"] and len(js["scope"]["audit"]) > 35
    assert js["scope"]["schema_version"] == "1.3"


def test_spec_files_are_in_step(tmp_path):
    spec = json.loads((ROOT / "src" / "aicontrols" / "engagement_spec.json").read_text(encoding="utf-8"))
    assert node(tmp_path, {"mode": "sha", "strings": [], "objects": []})["engagement_spec"] == spec
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_site_spec.py"), "--check"], capture_output=True)
    assert r.returncode == 0, "a site/*-spec.js file is stale: run python tools/build_site_spec.py"


def test_validation_of_corrupted_engagement_data_matches_python(tmp_path, lib, monkeypatch):
    good = fresh(lib)
    setup = [op for op in scenario()[:112] if op["op"].startswith("eng_") and op["op"] not in ("eng_validate", "eng_reopen")] 
    run_ops_py(good, lib, [{"op": "clock", "iso": "2026-11-20T09:00:00Z"}] + setup, monkeypatch)
    base = copy.deepcopy(good.data)
    cases = []
    c = copy.deepcopy(base); e = c["engagement"]
    e["client"].update(status="gone", sector="mining", size="huge"); e["scoping"]["status"] = "weird"
    e["scoping"]["responses"]["nope"] = {"value": "x", "by": "a", "at": "t"}
    e["scoping"]["responses"]["d_personal"] = {"value": "maybe", "by": "a", "at": "t"}
    e["scoping"]["delegations"]["nope"] = {"to": "x", "due": None}
    e["rules"]["custom"]["R-BAD"] = {"id": "R-OTHER", "confidence": "high", "when": {"q": "x", "op": "is", "value": "y"}}
    e["recommendation"] = {"items": [{"framework": "nope"}], "skipped": []}
    e["review"] = {"nope": {"action": "accept"}, "gdpr": {"action": "wipe"}, "dora": {"action": "add", "justification": " "}}
    e["applicable"] = {"frameworks": ["nope"]}
    cases.append(c)
    c = copy.deepcopy(base); c["engagement"]["scoping"]["status"] = "submitted"; c["engagement"]["scoping"]["responses"] = {}
    c["engagement"]["applicable"] = {"frameworks": []}
    cases.append(c)
    cases.append(copy.deepcopy(base))
    for case in cases:
        errs, warns = validate_engagement(Scope(copy.deepcopy(case), lib))
        got = node(tmp_path, {"mode": "wfops", "scope": copy.deepcopy(case), "ops": [{"op": "eng_validate"}]})["results"][0]["ok"]
        assert sorted(got["errors"]) == sorted(errs) and got["warnings"] == warns
    assert errs == []


# ---- roles and framework questionnaires ----------------------------------------------------------------------------
def roles_scenario(lib):
    A, SAM, ANN, CLEO, CARL, DINA = "ada", "sam", "ann", "cleo", "carl", "dina"
    nist = [c for c in lib.filter(framework="nist-ai-rmf")]
    owasp = [c for c in lib.filter(framework="owasp-llm")]
    dom_gov = "governance-policy-leadership"
    dom_tp = "third-party-supplier-ai-supply-chain"
    gov = [c.id for c in nist if c.domain_id == dom_gov]
    tp_nist = [c.id for c in nist if c.domain_id == dom_tp]
    o = []
    add = o.append
    add({"op": "clock", "iso": "2026-11-20T09:00:00Z"})
    add({"op": "eng_roles_set", "by": "pam", "role": "admin", "names": [A]})                  # engagement not started
    add({"op": "eng_client", "by": "pam", "fields": {"name": "Acme Bank", "sector": "banking", "country": "Qatar", "size": "large", "contributor": "Dina"}})
    add({"op": "eng_onboard", "by": "pam"})
    add({"op": "eng_roles_set", "by": "pam", "role": "wizard", "names": ["x"]})
    add({"op": "eng_roles_set", "by": "pam", "role": "admin", "names": [" "]})
    add({"op": "eng_roles_set", "by": "pam", "role": "scoping_lead", "names": [SAM]})        # an admin must come first
    add({"op": "eng_roles_set", "by": "pam", "role": "admin", "names": [A, " ADA ", "Bo"]})
    add({"op": "eng_roles_set", "by": A, "role": "scoping_lead", "names": [SAM]})
    add({"op": "eng_roles_set", "by": A, "role": "assessor", "names": [ANN]})
    add({"op": "eng_roles_set", "by": A, "role": "collaborator", "names": [CLEO, CARL]})
    add({"op": "eng_roles_set", "by": SAM, "role": "assessor", "names": ["x"]})              # only an admin
    add({"op": "eng_roles_set", "by": A, "role": "admin", "names": []})                      # last admin
    add({"op": "eng_roles_list"})
    # permissions on the engagement
    add({"op": "eng_client", "by": "stranger", "fields": {"country": "Qatar"}})
    add({"op": "eng_client", "by": SAM, "fields": {"country": "Qatar"}})
    add({"op": "eng_client", "by": A, "fields": {"country": "Qatar"}})
    add({"op": "eng_rule_disable", "by": SAM, "rule": "R-DATAGOV"})
    add({"op": "eng_rule_disable", "by": A, "rule": "R-DATAGOV"})
    add({"op": "eng_delegate", "by": CLEO, "q": "d_volume", "to": CLEO})                      # collaborators cannot delegate
    add({"op": "eng_delegate", "by": DINA, "q": "d_volume", "to": CLEO, "due": "2026-12-01"})
    add({"op": "eng_answer", "by": CARL, "q": "d_volume", "value": "large"})                  # not assigned to carl
    add({"op": "eng_answer", "by": CLEO, "q": "o_size", "value": "large"})                    # not assigned to cleo
    add({"op": "eng_answer", "by": CLEO, "q": "d_volume", "value": "large"})
    add({"op": "eng_answer", "by": ANN, "q": "o_size", "value": "large"})                     # assessors do not answer scoping
    rest = {k: v for k, v in FULL.items() if k != "d_volume"}
    for q, v in rest.items():
        add({"op": "eng_answer", "by": DINA, "q": q, "value": v})
    add({"op": "eng_submit", "by": CLEO})
    add({"op": "eng_submit", "by": SAM})
    add({"op": "eng_recommend", "by": DINA})
    add({"op": "eng_recommend", "by": SAM})
    add({"op": "eng_review", "by": DINA, "framework": "gdpr", "action": "accept"})
    add({"op": "eng_review", "by": ANN, "framework": "nist-ai-rmf", "action": "accept"})
    for fw in ("eu-ai-act", "gdpr", "iso-42001", "iso-27001"):
        add({"op": "eng_review", "by": SAM, "framework": fw, "action": "remove", "reason": "Out of scope for this engagement"})
    add({"op": "eng_review", "by": SAM, "framework": "owasp-llm", "action": "add", "reason": "Client ships an LLM chatbot"})
    add({"op": "eng_finalise", "by": ANN})
    add({"op": "eng_pkg_overview"})
    add({"op": "eng_finalise", "by": SAM, "reason": "Agreed with client"})
    add({"op": "eng_pkg_overview"})
    # handing questionnaires to collaborators
    add({"op": "eng_pkg_assign", "by": ANN, "fw": "nist-ai-rmf", "to": CLEO})
    add({"op": "eng_pkg_assign", "by": SAM, "fw": "gdpr", "to": CLEO})                        # no such questionnaire
    add({"op": "eng_pkg_assign", "by": SAM, "fw": "nist-ai-rmf", "to": CLEO, "domain": "nope"})
    add({"op": "eng_pkg_assign", "by": SAM, "fw": "nist-ai-rmf", "to": " "})
    add({"op": "eng_pkg_assign", "by": SAM, "fw": "nist-ai-rmf", "to": CLEO, "due": "1 Dec"})
    add({"op": "eng_pkg_assign", "by": SAM, "fw": "nist-ai-rmf", "to": CARL})
    add({"op": "eng_pkg_assign", "by": SAM, "fw": "nist-ai-rmf", "to": CLEO, "due": "2026-12-01", "domain": dom_gov})
    add({"op": "eng_pkg_assign", "by": DINA, "fw": "owasp-llm", "to": CLEO, "due": "2026-11-01"})
    add({"op": "eng_pkg_questions", "fw": "nist-ai-rmf", "domain": dom_gov})
    add({"op": "eng_pkg_questions", "fw": "nist-ai-rmf"})
    add({"op": "eng_pkg_progress", "fw": "nist-ai-rmf"})
    # answering
    c0 = gov[0]
    add({"op": "eng_respond", "by": CARL, "fw": "nist-ai-rmf", "control": c0, "answer": "implemented"})       # not carl's domain
    add({"op": "eng_respond", "by": SAM, "fw": "nist-ai-rmf", "control": c0, "answer": "implemented"})        # scoping lead cannot answer
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": "nope", "answer": "implemented"})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": owasp[0].id, "answer": "implemented"})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": c0, "answer": "maybe"})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": c0, "answer": "not_applicable"})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": c0, "answer": "implemented", "evidence": [""]})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": c0, "answer": "implemented", "evidence": "policy.pdf"})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": c0, "answer": "implemented", "comment": "x" * 1001})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": c0, "answer": "implemented", "evidence": ["AI policy v2", "https://x.example/p"]})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": gov[1], "answer": "not_applicable", "comment": "No in-house model"})
    add({"op": "eng_submit_items", "by": CLEO, "fw": "nist-ai-rmf", "domain": dom_gov})                          # one unanswered
    add({"op": "eng_submit_items", "by": CLEO, "fw": "nist-ai-rmf", "domain": "nope"})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": gov[2], "answer": "partially_implemented", "comment": "Draft only"})
    add({"op": "eng_submit_items", "by": CARL, "fw": "nist-ai-rmf", "domain": dom_gov})                          # not carl's
    add({"op": "eng_submit_items", "by": CLEO, "fw": "nist-ai-rmf", "domain": dom_gov})
    add({"op": "eng_submit_items", "by": CLEO, "fw": "nist-ai-rmf", "domain": dom_gov})                          # nothing to submit
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": c0, "answer": "not_implemented"})      # submitted
    # shared answers: only where the answerer may answer in the other questionnaire
    add({"op": "eng_respond", "by": CARL, "fw": "nist-ai-rmf", "control": tp_nist[0], "answer": "implemented", "shared": True})
    add({"op": "eng_respond", "by": DINA, "fw": "nist-ai-rmf", "control": tp_nist[1], "answer": "implemented", "comment": "Supplier register", "shared": True})
    # reviewing
    add({"op": "eng_review_items", "by": CLEO, "fw": "nist-ai-rmf", "domain": dom_gov, "action": "approve"})
    add({"op": "eng_review_items", "by": SAM, "fw": "nist-ai-rmf", "domain": dom_gov, "action": "return"})
    add({"op": "eng_review_items", "by": SAM, "fw": "nist-ai-rmf", "domain": dom_gov, "action": "bounce"})
    add({"op": "eng_review_items", "by": SAM, "fw": "nist-ai-rmf", "domain": dom_tp, "action": "approve"})        # nothing submitted
    add({"op": "eng_review_items", "by": SAM, "fw": "nist-ai-rmf", "domain": dom_gov, "action": "return", "note": "Attach the policy"})
    add({"op": "eng_respond", "by": CLEO, "fw": "nist-ai-rmf", "control": c0, "answer": "implemented", "evidence": ["AI policy v3"]})
    add({"op": "eng_submit_items", "by": CLEO, "fw": "nist-ai-rmf", "domain": dom_gov})
    add({"op": "eng_review_items", "by": ANN, "fw": "nist-ai-rmf", "domain": dom_gov, "action": "approve"})
    add({"op": "eng_submit_pkg", "by": DINA, "fw": "nist-ai-rmf"})                                             # not all approved
    add({"op": "eng_pkg_progress", "fw": "nist-ai-rmf"})
    # a whole questionnaire, start to lock
    for c in owasp:
        add({"op": "eng_respond", "by": CLEO, "fw": "owasp-llm", "control": c.id, "answer": "implemented", "evidence": ["Scan report"]})
    for d in sorted({c.domain_id for c in owasp}):
        add({"op": "eng_submit_items", "by": CLEO, "fw": "owasp-llm", "domain": d})
        add({"op": "eng_review_items", "by": DINA, "fw": "owasp-llm", "domain": d, "action": "approve"})
    add({"op": "eng_submit_pkg", "by": CLEO, "fw": "owasp-llm"})                                               # collaborators cannot submit
    add({"op": "eng_submit_pkg", "by": DINA, "fw": "owasp-llm"})
    add({"op": "eng_submit_pkg", "by": DINA, "fw": "owasp-llm"})
    add({"op": "eng_respond", "by": CLEO, "fw": "owasp-llm", "control": owasp[0].id, "answer": "not_implemented"})
    add({"op": "eng_pkg_assign", "by": SAM, "fw": "owasp-llm", "to": CARL})
    add({"op": "eng_return_pkg", "by": SAM, "fw": "owasp-llm", "reason": "x"})                                  # scoping lead cannot return
    add({"op": "eng_return_pkg", "by": ANN, "fw": "owasp-llm", "reason": " "})
    add({"op": "eng_return_pkg", "by": ANN, "fw": "owasp-llm", "reason": "Evidence is out of date"})
    add({"op": "eng_return_pkg", "by": ANN, "fw": "owasp-llm", "reason": "again"})
    add({"op": "eng_reopen_assignment", "by": SAM, "reason": "Scope changed"})                                  # answers exist
    # who has what to do
    add({"op": "eng_tasks", "name": CLEO})
    add({"op": "eng_tasks", "name": " carl "})
    add({"op": "eng_tasks", "name": "nobody"})
    add({"op": "eng_pkg_overview"})
    add({"op": "eng_pkg_progress", "fw": "owasp-llm"})
    add({"op": "eng_validate"})
    # a later date: assignments become overdue
    add({"op": "clock", "iso": "2027-01-05T09:00:00Z"})
    add({"op": "eng_pkg_progress", "fw": "nist-ai-rmf"})
    add({"op": "eng_tasks", "name": CLEO})
    return o


def test_python_and_browser_agree_on_roles_and_questionnaires(tmp_path, lib, monkeypatch):
    ops = roles_scenario(lib)
    py_scope = fresh(lib)
    py_results = norm(run_ops_py(py_scope, lib, ops, monkeypatch))
    js = node(tmp_path, {"mode": "wfops", "scope": fresh(lib).data, "ops": ops})
    errors = sum(1 for r in py_results if "error" in r)
    assert errors >= 40 and sum(1 for r in py_results if "ok" in r) >= 80
    for i, (op, p, j) in enumerate(zip(ops, py_results, js["results"])):
        assert p == j, f"step {i} ({op['op']}) differs:\n python : {str(p)[:600]}\n browser: {str(j)[:600]}"
    assert len(js["results"]) == len(py_results)
    assert js["scope"] == norm(py_scope.data)
    assert js["scope"]["audit"][-1]["hash"] == py_scope.data["audit"][-1]["hash"]
    e = py_scope.data["engagement"]
    assert e["packages"]["owasp-llm"]["status"] == "open" and e["roles"]["admin"] == ["ada", "Bo"]
    shared = [r["ok"]["shared_to"] for op, r in zip(ops, py_results) if op.get("shared") and "ok" in r]
    assert shared == [0, 1]       # carl may not answer in the other questionnaire, dina may


def test_validation_of_corrupted_roles_and_questionnaires_matches_python(tmp_path, lib, monkeypatch):
    good = fresh(lib)
    run_ops_py(good, lib, roles_scenario(lib)[:112], monkeypatch)
    base = copy.deepcopy(good.data)
    assert "packages" in base["engagement"] and base["engagement"]["packages"]
    cases = []
    c = copy.deepcopy(base)
    e = c["engagement"]
    e["roles"] = {"wizard": ["x"], "scoping_lead": ["sam", " "]}
    p = e["packages"]["nist-ai-rmf"]
    p["status"] = "weird"
    p["controls"].append("owasp-llm:LLM01")
    p["assignments"]["nope"] = {"to": "x", "due": None}
    first = next(iter(p["responses"]))
    p["responses"][first]["answer"] = "maybe"
    p["responses"]["nope"] = {"answer": "implemented", "status": "approved"}
    e["packages"]["gdpr"] = {"framework": "gdpr", "status": "open", "controls": [], "assignments": {}, "responses": {}}
    cases.append(c)
    c = copy.deepcopy(base)
    c["engagement"]["packages"]["nist-ai-rmf"]["status"] = "submitted"
    c["engagement"]["applicable"] = None
    cases.append(c)
    c = copy.deepcopy(base)
    c["engagement"]["roles"] = {"scoping_lead": ["sam"]}
    cases.append(c)
    cases.append(copy.deepcopy(base))
    for case in cases:
        errs, warns = validate_engagement(Scope(copy.deepcopy(case), lib))
        got = node(tmp_path, {"mode": "wfops", "scope": copy.deepcopy(case), "ops": [{"op": "eng_validate"}]})["results"][0]["ok"]
        assert sorted(got["errors"]) == sorted(errs) and got["warnings"] == warns
    assert errs == []
