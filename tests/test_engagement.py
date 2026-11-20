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


# ---- roles and framework questionnaires ----------------------------------------------------------------------------
def with_roles(eng):
    eng.set_roles("pam", "admin", ["ada"])
    eng.set_roles("ada", "scoping_lead", ["sam"])
    eng.set_roles("ada", "assessor", ["ann"])
    eng.set_roles("ada", "collaborator", ["cleo", "carl"])
    return eng


def finalised(eng):
    """Scoped, recommended, reduced to NIST AI RMF + OWASP LLM, finalised. Roles are set."""
    answered(eng)
    eng.submit_scoping("dina")
    rec = eng.recommend("pam")
    for i in rec["items"]:
        if i["framework"] == "nist-ai-rmf":
            eng.review("pam", "nist-ai-rmf", "accept")
        else:
            eng.review("pam", i["framework"], "remove", "Out of scope")
    eng.review("pam", "owasp-llm", "add", "Ships an LLM chatbot")
    eng.finalise("pam")
    return with_roles(eng)


def test_roles_are_not_enforced_until_set_and_an_admin_must_come_first(eng):
    assert not eng.enforced()
    eng.set_client("anyone", {"country": "Qatar"})                           # nobody holds a role yet, so anything goes
    with pytest.raises(EngagementError, match="engagement admin"):
        eng.set_roles("pam", "scoping_lead", ["sam"])
    eng.set_roles("pam", "admin", ["ada", " ADA ", "Bo"])
    assert eng.role_register()["admin"] == ["ada", "Bo"] and eng.enforced()
    with pytest.raises(EngagementError, match="may not assign engagement roles"):
        eng.set_roles("sam", "assessor", ["x"])
    eng.set_roles("ada", "scoping_lead", ["sam"])
    with pytest.raises(EngagementError, match="engagement admin"):
        eng.set_roles("ada", "admin", [])                                     # would leave nobody able to change roles
    with pytest.raises(EngagementError, match="unknown role"):
        eng.set_roles("ada", "wizard", ["x"])


def test_the_scoping_lead_runs_scoping_and_assigns_frameworks_but_nothing_else(eng):
    with_roles(eng)
    eng.set_roles("ada", "scoping_lead", ["sam"])
    answered(eng)                                                             # dina is the client contributor
    with pytest.raises(EngagementError, match="may not submit the scoping answers"):
        eng.submit_scoping("stranger")
    eng.submit_scoping("sam")
    eng.recommend("sam")
    with pytest.raises(EngagementError, match="may not edit the client profile"):
        eng.set_client("sam", {"country": "UAE"})
    with pytest.raises(EngagementError, match="may not change applicability rules"):
        eng.rule_disable("sam", "R-27001")
    with pytest.raises(EngagementError, match="may not assign engagement roles"):
        eng.set_roles("sam", "collaborator", ["x"])
    with pytest.raises(EngagementError, match="roles that can: admin, scoping_lead"):
        eng.finalise("ann")
    eng.rule_disable("ada", "R-27001")                                        # an admin can


def test_collaborators_only_touch_what_is_assigned_to_them(eng):
    with_roles(eng)
    eng.delegate("dina", "d_volume", "Cleo")                                  # the client contributor needs no role entry
    with pytest.raises(EngagementError, match="only answer scoping questions for items assigned"):
        eng.answer("carl", "d_volume", "large")
    with pytest.raises(EngagementError, match="only answer scoping questions for items assigned"):
        eng.answer("cleo", "o_size", "large")
    assert eng.answer("CLEO", "d_volume", "large") == "large"                 # names match regardless of case
    with pytest.raises(EngagementError, match="may not delegate"):
        eng.delegate("cleo", "d_volume", "Carl")
    with pytest.raises(EngagementError, match="may not answer scoping"):
        eng.answer("ann", "o_size", "large")                                  # an assessor does not answer scoping


def test_each_finalised_framework_gets_one_question_per_library_control(eng):
    finalised(eng)
    pk = eng.scope.data["engagement"]["packages"]
    assert sorted(pk) == ["nist-ai-rmf", "owasp-llm"]
    for fw, p in pk.items():
        assert p["controls"] == [c.id for c in eng.lib.filter(framework=fw)] and p["status"] == "open"
    qs = eng.package_questions("owasp-llm")
    assert len(qs) == 10 and qs[0]["requirement"] and qs[0]["response"] is None
    assert eng.packages_overview()[0]["framework"] == "nist-ai-rmf"


def test_assign_answer_review_submit_lock_and_return(eng):
    finalised(eng)
    dom = eng.package_domains("owasp-llm")[0]
    ids = [q["control_id"] for q in eng.package_questions("owasp-llm", dom)]
    with pytest.raises(EngagementError, match="may not assign a framework questionnaire"):
        eng.package_assign("ann", "owasp-llm", "Cleo")
    eng.package_assign("sam", "owasp-llm", "Cleo", "2026-12-01", dom)
    with pytest.raises(EngagementError, match="only answer framework questions for items assigned"):
        eng.respond("carl", "owasp-llm", ids[0], "implemented")
    with pytest.raises(EngagementError, match="justification"):
        eng.respond("cleo", "owasp-llm", ids[0], "not_applicable")
    for cid in ids:
        eng.respond("cleo", "owasp-llm", cid, "implemented", "", ["Scan report"])
    eng.submit_items("cleo", "owasp-llm", dom)
    with pytest.raises(EngagementError, match="already submitted"):
        eng.respond("cleo", "owasp-llm", ids[0], "not_implemented")
    with pytest.raises(EngagementError, match="may not approve"):
        eng.review_items("cleo", "owasp-llm", dom, "approve")
    with pytest.raises(EngagementError, match="what needs correcting"):
        eng.review_items("sam", "owasp-llm", dom, "return")
    eng.review_items("sam", "owasp-llm", dom, "return", "Attach evidence")
    eng.respond("cleo", "owasp-llm", ids[0], "implemented", "", ["Scan report v2"])                      # returned answers can change
    eng.submit_items("cleo", "owasp-llm", dom)
    eng.review_items("sam", "owasp-llm", dom, "approve")
    with pytest.raises(EngagementError, match="not yet approved"):
        eng.submit_package("dina", "owasp-llm")
    for d in eng.package_domains("owasp-llm")[1:]:
        for q in eng.package_questions("owasp-llm", d):
            eng.respond("dina", "owasp-llm", q["control_id"], "implemented")
    assert eng.package_progress("owasp-llm")["approved"] == len(ids)
    with pytest.raises(EngagementError, match="framework answers already exist"):
        eng.reopen_assignment("sam", "Scope changed")


def test_a_submitted_questionnaire_is_locked_until_an_assessor_returns_it(eng):
    finalised(eng)
    for d in eng.package_domains("owasp-llm"):
        for q in eng.package_questions("owasp-llm", d):
            eng.respond("dina", "owasp-llm", q["control_id"], "implemented")
        eng.submit_items("dina", "owasp-llm", d)
        eng.review_items("sam", "owasp-llm", d, "approve")
    eng.submit_package("dina", "owasp-llm")
    first = eng.package_questions("owasp-llm")[0]["control_id"]
    with pytest.raises(EngagementError, match="locked"):
        eng.respond("dina", "owasp-llm", first, "not_implemented")
    with pytest.raises(EngagementError, match="may not return"):
        eng.return_package("sam", "owasp-llm", "x")
    eng.return_package("ann", "owasp-llm", "Evidence is out of date")
    assert eng.package_progress("owasp-llm")["status"] == "open"
    actions = [ev["action"] for ev in eng.scope.data["audit"]]
    assert "ENGAGEMENT_PACKAGE_SUBMITTED" in actions and "ENGAGEMENT_PACKAGE_RETURNED" in actions
    assert verify_audit(eng.scope.data["audit"])[0]


def test_one_answer_can_be_shared_across_frameworks_where_the_answerer_may_answer(eng):
    finalised(eng)
    dom = "third-party-supplier-ai-supply-chain"
    nist = [q["control_id"] for q in eng.package_questions("nist-ai-rmf", dom)]
    owasp = [q["control_id"] for q in eng.package_questions("owasp-llm", dom)]
    eng.package_assign("sam", "owasp-llm", "Cleo", None, dom)
    eng.package_assign("sam", "nist-ai-rmf", "Carl", None, dom)
    assert eng.respond("carl", "nist-ai-rmf", nist[0], "implemented", "", None, True)["shared_to"] == 0   # carl has no access to the other one
    out = eng.respond("dina", "nist-ai-rmf", nist[1], "implemented", "Supplier register", None, True)
    assert out["shared_to"] == len(owasp)
    r = eng.package_questions("owasp-llm", dom)[0]["response"]
    assert r["shared_from"] == f"nist-ai-rmf:{nist[1]}" and r["comment"] == "Supplier register"


def test_tasks_and_overdue(eng):
    finalised(eng)
    dom = eng.package_domains("nist-ai-rmf")[0]
    eng.package_assign("sam", "nist-ai-rmf", "Cleo", "2020-01-01", dom)
    tasks = eng.my_tasks(" cleo ")
    assert len(tasks) == 1 and tasks[0]["framework"] == "nist-ai-rmf" and tasks[0]["domain"] == dom
    row = [r for r in eng.package_progress("nist-ai-rmf")["domains"] if r["domain"] == dom][0]
    assert row["overdue"] is True and row["assigned_to"] == "Cleo"
    assert eng.my_tasks("nobody") == []


def test_role_and_questionnaire_validation_catches_corruption(eng):
    finalised(eng)
    assert validate_engagement(eng.scope) == ([], [])
    d = eng.scope.data["engagement"]
    d["roles"] = {"wizard": ["x"]}
    d["packages"]["nist-ai-rmf"]["controls"].append("gdpr:Art.5(1)")
    d["packages"]["owasp-llm"]["responses"]["owasp-llm:nope"] = {"answer": "implemented", "status": "approved"}
    errs = validate_engagement(eng.scope)[0]
    assert any("unknown role 'wizard'" in e for e in errs) and any("not a nist-ai-rmf control" in e for e in errs)
    assert any("not in its questionnaire" in e for e in errs)


def test_cli_roles_and_questionnaires(tmp_path, capsys, monkeypatch):
    f = str(tmp_path / "c.json")

    def run(*a, by="pam"):
        monkeypatch.setenv("AICONTROLS_ACTOR", by)
        rc = main(list(a))
        return rc, capsys.readouterr()

    run("scope", "init", "--org", "Acme", "--file", f)
    run("engagement", "client", "set", "--file", f, "--name", "Acme", "--sector", "banking", "--country", "Qatar", "--size", "large", "--contributor", "Dina")
    run("engagement", "client", "onboard", "--file", f)
    assert "not set" in run("engagement", "roles", "list", "--file", f)[1].out
    rc, out = run("engagement", "roles", "set", "scoping_lead", "Sam", "--file", f)
    assert rc == 2 and "engagement admin" in out.err
    assert run("engagement", "roles", "set", "admin", "Ada", "--file", f)[0] == 0
    run("engagement", "roles", "set", "scoping_lead", "Sam", "--file", f, by="Ada")
    run("engagement", "roles", "set", "collaborator", "Cleo", "--file", f, by="Ada")
    rc, out = run("engagement", "client", "set", "--file", f, "--country", "UAE", by="Sam")
    assert rc == 2 and "may not edit the client profile" in out.err
    for q, v in FULL.items():
        run("engagement", "answer", q, *(v if isinstance(v, list) else [v]), "--file", f, by="Dina")
    run("engagement", "submit", "--file", f, by="Sam")
    run("engagement", "recommend", "--file", f, by="Sam")
    for fw in ("eu-ai-act", "gdpr", "iso-42001", "iso-27001"):
        run("engagement", "review", fw, "remove", "--reason", "Out of scope", "--file", f, by="Sam")
    run("engagement", "review", "nist-ai-rmf", "accept", "--file", f, by="Sam")
    run("engagement", "review", "owasp-llm", "add", "--reason", "LLM chatbot", "--file", f, by="Sam")
    assert run("engagement", "finalise", "--file", f, by="Sam")[0] == 0
    assert "owasp-llm" in run("engagement", "packages", "--file", f)[1].out
    rc, out = run("engagement", "package", "assign", "owasp-llm", "--to", "Cleo", "--due", "2026-12-01", "--file", f, by="Sam")
    assert rc == 0 and "assigned to Cleo" in out.out
    ctl = aicontrols.load().filter(framework="owasp-llm")[0].id
    rc, out = run("engagement", "package", "answer", "owasp-llm", ctl, "implemented", "--evidence", "Scan report", "--file", f, by="Cleo")
    assert rc == 0
    rc, out = run("engagement", "package", "answer", "owasp-llm", ctl, "implemented", "--file", f, by="Carl")
    assert rc == 2 and "may not" in out.err or "only" in out.err
    assert "owasp-llm" in run("engagement", "tasks", "Cleo", "--file", f)[1].out
    assert run("engagement", "package", "questions", "owasp-llm", "--unanswered", "--file", f)[0] == 0
    scope = Scope.load(f, aicontrols.load())
    assert scope.validate()[0] == [] and scope.data["engagement"]["roles"]["admin"] == ["Ada"]
