# SPDX-License-Identifier: Apache-2.0
import json

import pytest

import aicontrols
from aicontrols.cli import main
from aicontrols.engagement import Engagement, EngagementError, eval_when, load_spec, validate_engagement, when_questions
from aicontrols.scope import Scope, ScopeError
from aicontrols.workflow import verify_audit

FULL = {"j_countries": ["qatar", "eu"], "j_customer_locations": ["qatar"], "i_sector": "banking", "r_financial_entity": "no",
        "r_ict_provider_to_fe": "no", "r_essential_service": "no", "d_personal": "yes", "d_special": "no", "d_volume": "large",
        "a_role": ["develop", "deploy"], "a_eu_market": "yes", "t_cloud": "yes", "t_outsourcing": "yes", "c_needs_cert": "yes", "o_size": "large"}


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


@pytest.fixture
def eng(lib):
    s = Scope.new("Acme", lib)
    e = Engagement(s)
    e.set_client("pam", {"name": "Acme", "sector": "banking", "country": "Qatar", "size": "large", "contributor": "Dina"})
    e.onboard("pam")
    return e


def answered(eng, **over):
    for q, v in {**FULL, **over}.items():
        eng.answer("dina", q, v)
    return eng


def test_spec_is_consistent_and_rules_reference_real_questions(lib):
    spec = load_spec()
    qs = {q["id"]: q for q in spec["questionnaire"]["questions"]}
    assert {q["domain"] for q in qs.values()} == {d["id"] for d in spec["questionnaire"]["domains"]}      # the eight spec domains
    e = Engagement(Scope.new("x", lib))
    for r in spec["rules"]:
        if "from_answer" in r:
            assert qs[r["from_answer"]]["kind"] == "multi"
        else:
            e._check_when(r["when"])
    # every contract standard offered is a real framework
    assert set(qs["c_contract_standards"]["options"]) <= set(lib.frameworks)


def test_conditions_are_deterministic_and_unanswered_never_matches():
    c = {"all": [{"q": "a", "op": "is", "value": "yes"}, {"any": [{"q": "m", "op": "has", "value": "x"}, {"q": "m", "op": "in", "value": ["y"]}]}]}
    assert eval_when(c, {"a": "yes", "m": ["x"]}) and eval_when(c, {"a": "yes", "m": ["y", "z"]})
    assert not eval_when(c, {"a": "no", "m": ["x"]}) and not eval_when(c, {"m": ["x"]})
    assert eval_when({"not": {"q": "a", "op": "is", "value": "yes"}}, {"a": "no"})
    assert when_questions(c) == ["a", "m"]


def test_onboarding_gates_scoping(lib):
    e = Engagement(Scope.new("Acme", lib))
    with pytest.raises(EngagementError, match="not started"):
        e.answer("pam", "d_personal", "yes")
    e.set_client("pam", {"name": "Acme"})
    with pytest.raises(EngagementError, match="missing: sector"):
        e.onboard("pam")
    e.set_client("pam", {"sector": "banking", "country": "Qatar", "size": "large", "contributor": "Dina"})
    with pytest.raises(EngagementError, match="onboard the client"):
        e.answer("pam", "d_personal", "yes")
    e.onboard("pam")
    with pytest.raises(EngagementError, match="already"):
        e.onboard("pam")
    with pytest.raises(EngagementError, match="sector"):
        e.set_client("pam", {"sector": "mining"})


def test_answers_are_validated_and_submit_needs_every_required_one(eng):
    with pytest.raises(EngagementError, match="yes or no"):
        eng.answer("dina", "d_personal", "maybe")
    with pytest.raises(EngagementError, match="unknown option"):
        eng.answer("dina", "a_role", ["develop", "fly"])
    assert eng.answer("dina", "a_role", ["deploy", "develop", "deploy"]) == ["deploy", "develop"]    # sorted, deduplicated
    with pytest.raises(EngagementError, match="unanswered"):
        eng.submit_scoping("dina")
    answered(eng)
    p = eng.progress()
    assert p["missing"] == [] and p["required_answered"] == p["required"]
    eng.submit_scoping("dina")
    with pytest.raises(EngagementError, match="locked"):
        eng.answer("dina", "d_personal", "no")
    with pytest.raises(EngagementError, match="locked"):
        eng.delegate("dina", "t_apis", "IT")


def test_delegation_records_who_and_when(eng):
    d = eng.delegate("dina", "d_volume", "Data office", "2026-12-01")
    assert d == {"to": "Data office", "due": "2026-12-01"}
    assert [q for q in eng.questionnaire() if q["id"] == "d_volume"][0]["delegated_to"] == "Data office"
    with pytest.raises(EngagementError, match="due date"):
        eng.delegate("dina", "d_volume", "x", "1 Dec")


def test_recommendations_explain_themselves_and_skip_unknown_frameworks(eng):
    answered(eng, c_contract_standards=["iso-27701"])
    eng.submit_scoping("dina")
    rec = eng.recommend("pam")
    by = {i["framework"]: i for i in rec["items"]}
    assert {"gdpr", "eu-ai-act", "iso-42001", "iso-27001", "nist-ai-rmf", "iso-27701"} <= set(by)
    assert "dora" not in by                                           # not a financial entity or ICT provider
    assert by["gdpr"]["confidence"] == "high" and by["nist-ai-rmf"]["confidence"] == "medium"
    assert by["gdpr"]["triggers"] == ["d_personal", "j_countries", "j_customer_locations"] and by["gdpr"]["rationale"]
    assert {s["rule"] for s in rec["skipped"]} == {"R-DATAGOV", "R-PDPPL"}                       # frameworks the library lacks
    assert all(i["framework"] in eng.lib.frameworks for i in rec["items"])
    assert [i["confidence"] for i in rec["items"]] == sorted((i["confidence"] for i in rec["items"]), key=lambda c: -["low", "medium", "high"].index(c))


def test_same_answers_give_the_same_recommendations(lib):
    out = []
    for _ in range(2):
        s = Scope.new("A", lib)
        e = Engagement(s)
        e.set_client("p", {"name": "A", "sector": "banking", "country": "Q", "size": "large", "contributor": "D"})
        e.onboard("p")
        answered(e)
        e.submit_scoping("d")
        out.append(e.compute_recommendations())
    assert out[0] == out[1]


def test_financial_entity_triggers_dora(eng):
    answered(eng, r_financial_entity="yes")
    eng.submit_scoping("dina")
    assert "dora" in {i["framework"] for i in eng.recommend("pam")["items"]}


def test_review_needs_a_written_justification_to_override_and_is_audited(eng):
    answered(eng)
    eng.submit_scoping("dina")
    rec = eng.recommend("pam")
    with pytest.raises(EngagementError, match="justification"):
        eng.review("assessor", "nist-ai-rmf", "remove")
    with pytest.raises(EngagementError, match="justification"):
        eng.review("assessor", "dora", "add")
    with pytest.raises(EngagementError, match="not recommended"):
        eng.review("assessor", "dora", "accept")
    with pytest.raises(EngagementError, match="already recommended"):
        eng.review("assessor", "gdpr", "add", "x")
    eng.review("assessor", "nist-ai-rmf", "remove", "Client uses ISO 42001 instead")
    eng.review("assessor", "dora", "add", "Parent company is an EU bank")
    with pytest.raises(EngagementError, match="not yet reviewed"):
        eng.finalise("admin")
    for i in rec["items"]:
        if i["framework"] != "nist-ai-rmf":
            eng.review("assessor", i["framework"], "accept")
    ap = eng.finalise("admin", "Agreed with client")
    assert "dora" in ap["frameworks"] and "nist-ai-rmf" not in ap["frameworks"]
    actions = [(ev["action"], ev["target"]) for ev in eng.scope.data["audit"]]
    assert ("ENGAGEMENT_REVIEWED", "nist-ai-rmf") in actions and ("ENGAGEMENT_FINALISED", "applicable-frameworks") in actions
    assert verify_audit(eng.scope.data["audit"])[0]
    with pytest.raises(EngagementError, match="finalised"):
        eng.review("assessor", "gdpr", "accept")
    with pytest.raises(EngagementError, match="finalised"):
        eng.recommend("pam")
    eng.reopen_assignment("admin", "Scope changed")
    assert eng.overview()["stage"] == "review"


def test_reopening_scoping_clears_everything_downstream(eng):
    answered(eng)
    eng.submit_scoping("dina")
    eng.recommend("pam")
    with pytest.raises(EngagementError, match="reason"):
        eng.reopen_scoping("dina", " ")
    eng.reopen_scoping("dina", "New AI use case")
    o = eng.overview()
    assert o["stage"] == "scoping" and o["recommended"] == [] and o["reviewed"] == [] and o["applicable"] == []
    eng.answer("dina", "a_gpai", "yes")
    eng.submit_scoping("dina")
    assert eng.recommend("pam")["items"]


def test_custom_rules_override_and_can_be_disabled(eng):
    rule = {"id": "R-OUTSOURCE", "framework": "iso-27001", "confidence": "low", "weight": 10, "rationale": "Outsources ICT.",
            "when": {"q": "t_outsourcing", "op": "is", "value": "yes"}}
    eng.rule_set("pam", rule)
    assert eng.scope.data["engagement"]["rules"]["version"] == 2
    answered(eng)
    eng.submit_scoping("dina")
    by = {i["framework"]: i for i in eng.compute_recommendations()["items"]}
    assert "R-OUTSOURCE" in by["iso-27001"]["rules"] and by["iso-27001"]["confidence"] == "high"   # highest confidence wins
    eng.rule_disable("pam", "R-27001")
    by = {i["framework"]: i for i in eng.compute_recommendations()["items"]}
    assert by["iso-27001"]["confidence"] == "low"
    eng.rule_disable("pam", "R-27001", False)
    for bad in ({**rule, "id": "x"}, {**rule, "weight": 101}, {**rule, "when": {"q": "d_personal", "op": "has", "value": "yes"}},
                {**rule, "when": {"q": "zzz", "op": "is", "value": "yes"}}, {**rule, "rationale": ""}):
        with pytest.raises(EngagementError):
            eng.rule_set("pam", bad)
    with pytest.raises(EngagementError, match="unknown rule"):
        eng.rule_disable("pam", "R-NOPE")


def test_reads_do_not_create_keys(lib):
    s = Scope.new("A", lib)
    before = json.dumps(s.data, sort_keys=True)
    e = Engagement(s)
    e.overview(); e.questionnaire(); e.progress(); e.effective_rules(); e.applicable_frameworks()
    assert json.dumps(s.data, sort_keys=True) == before


def test_validation_catches_corruption_and_accepts_a_good_file(eng):
    answered(eng)
    eng.submit_scoping("dina")
    eng.recommend("pam")
    assert validate_engagement(eng.scope) == ([], [])
    assert eng.scope.validate()[0] == []
    d = eng.scope.data
    d["engagement"]["review"]["nope"] = {"action": "accept"}
    d["engagement"]["scoping"]["responses"]["d_personal"]["value"] = "maybe"
    errs = validate_engagement(eng.scope)[0]
    assert any("unknown framework 'nope'" in e for e in errs) and any("yes or no" in e for e in errs)


def test_cli_end_to_end(tmp_path, capsys, monkeypatch):
    f = str(tmp_path / "c.json")
    monkeypatch.setenv("AICONTROLS_ACTOR", "pam")

    def run(*a):
        rc = main(list(a))
        return rc, capsys.readouterr()

    assert run("scope", "init", "--org", "Acme", "--file", f)[0] == 0
    assert run("engagement", "status", "--file", f)[1].out.startswith("engagement not started")
    assert run("engagement", "client", "set", "--file", f, "--name", "Acme", "--sector", "banking", "--country", "Qatar",
               "--size", "large", "--contributor", "Dina")[0] == 0
    assert run("engagement", "client", "onboard", "--file", f)[0] == 0
    for q, v in FULL.items():
        assert run("engagement", "answer", q, *(v if isinstance(v, list) else [v]), "--file", f)[0] == 0
    rc, out = run("engagement", "recommend", "--file", f)
    assert rc == 2 and "submit the scoping answers" in out.err
    assert run("engagement", "submit", "--file", f)[0] == 0
    rc, out = run("engagement", "recommend", "--file", f)
    assert rc == 0 and "gdpr" in out.out and "skipped: rule R-PDPPL" in out.out
    rc, out = run("engagement", "review", "gdpr", "remove", "--file", f)
    assert rc == 2 and "justification" in out.err
    assert run("engagement", "questions", "--file", f, "--unanswered")[0] == 0
    st = json.loads(run("engagement", "status", "--json", "--file", f)[1].out)
    assert st["stage"] == "review"
    scope = Scope.load(f, aicontrols.load())
    assert scope.validate()[0] == [] and scope.data["schema_version"] == "1.3"


def test_old_files_still_load_and_schema_accepts_the_new_section(lib, eng):
    jsonschema = pytest.importorskip("jsonschema")
    from pathlib import Path
    schema = json.loads((Path(__file__).resolve().parent.parent / "schema" / "scope.schema.json").read_text(encoding="utf-8"))
    answered(eng)
    eng.submit_scoping("dina")
    eng.recommend("pam")
    jsonschema.Draft202012Validator(schema).validate(json.loads(json.dumps(eng.scope.data)))
