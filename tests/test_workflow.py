# SPDX-License-Identifier: Apache-2.0
import copy
import csv
import datetime as dt
import io
import json
from pathlib import Path

import pytest

import aicontrols
from aicontrols import workflow as wfmod
from aicontrols.cli import main
from aicontrols.scope import Scope
from aicontrols.workflow import ROLE_EXECUTIVE, ROLE_SECOND_LINE, Workflow, WorkflowError, verify_audit

ROOT = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2026, 10, 27, 12, 0, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


@pytest.fixture
def clock(monkeypatch):
    state = {"now": NOW}
    monkeypatch.setattr(wfmod, "_now", lambda: state["now"])
    return state


@pytest.fixture
def wf(lib, clock):
    s = Scope.new("Test Org", lib)
    s.add_system("bot", "Bot", ["iso-27001", "gdpr"])
    w = Workflow(s)
    w.enable("bot", "alice")
    return w


def set_profile(w):
    w.set_profile("bot", "alice", business_unit="Retail", environment="production", boundary="EU region",
                  risk_appetite="moderate", target_default="implemented")


def tailor_all(w):
    for cc_id in w.state("bot")["common_controls"]:
        w.cc_set("bot", "owner1", cc_id, owner="owner1", reviewer="reviewer1", frequency="monthly",
                 implementation="Documented procedure", evidence_required=["evidence file"],
                 test_type="automated", test_description="nightly query")


def ingest_all(w, result="pass", at="2026-10-26T10:00:00Z", metrics=None):
    recs = [{"control": cc, "at": at, "result": result, "metrics": metrics or {}} for cc in w.state("bot")["common_controls"]]
    return w.ingest("bot", "engine", recs, "test-feed")


# ---- enabling, audit chain ------------------------------------------------------------
def test_enable_creates_state_and_genesis_audit_event(wf):
    st = wf.state("bot")
    assert st["stage"] == "FRAMEWORK_SCOPING" and st["cycle"] == 1
    assert wf.scope.data["schema_version"] == "1.1"
    assert wf.audit_log[0]["action"] == "WORKFLOW_ENABLED" and wf.audit_log[0]["prev"] == "0" * 64
    with pytest.raises(WorkflowError, match="already enabled"):
        wf.enable("bot", "alice")


def test_workflow_must_be_enabled_first(lib):
    s = Scope.new("O", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    with pytest.raises(WorkflowError, match="not enabled"):
        Workflow(s).state("bot")


def test_audit_chain_detects_edits_and_removals(wf):
    set_profile(wf)
    assert verify_audit(wf.audit_log)[0]
    edited = copy.deepcopy(wf.audit_log)
    edited[1]["details"]["after"] = {"business_unit": "Hacked"}
    ok, problems = verify_audit(edited)
    assert not ok and any("edited" in p for p in problems)
    removed = copy.deepcopy(wf.audit_log)
    del removed[0]
    assert not verify_audit(removed)[0]


def test_every_mutation_is_audited_with_actor_and_role(wf):
    set_profile(wf)
    wf.cc_add("bot", "arch", "Incident process", domain="incident")
    actions = [e["action"] for e in wf.audit_log]
    assert actions[:3] == ["WORKFLOW_ENABLED", "PROFILE_UPDATED", "CC_ADDED"]
    assert wf.audit_log[2]["actor"] == "arch" and wf.audit_log[2]["role"] == "COMPLIANCE_ARCHITECT"


def test_an_actor_name_is_required(wf):
    with pytest.raises(WorkflowError, match="actor"):
        wf.cc_add("bot", "  ", "X")


# ---- stage 1 ----------------------------------------------------------------------------------
def test_profile_validation(wf):
    with pytest.raises(WorkflowError, match="risk_appetite"):
        wf.set_profile("bot", "a", risk_appetite="reckless")
    with pytest.raises(WorkflowError, match="target_default"):
        wf.set_profile("bot", "a", target_default="not_started")
    with pytest.raises(WorkflowError, match="empty"):
        wf.set_profile("bot", "a", boundary="  ")
    wf.set_profile("bot", "a", asset_classes=["customer-data", " customer-data ", "models"])
    assert wf.state("bot")["profile"]["asset_classes"] == ["customer-data", "models"]


def test_stage_one_actions_follow_the_data(wf):
    by = {a["action"]: a for a in wf.actions("bot")}
    assert not any(a["satisfied"] for a in by.values())
    set_profile(wf)
    by = {a["action"]: a for a in wf.actions("bot")}
    assert by["DEFINE_ORGANIZATIONAL_PROFILE_BOUNDARIES"]["satisfied"]
    assert by["ESTABLISH_CURRENT_VS_TARGET_PROFILES"]["satisfied"]
    assert not by["RATIONALIZE_NON_APPLICABLE_OBLIGATIONS"]["satisfied"]  # needs an attestation


def test_attestation_rules(wf):
    with pytest.raises(WorkflowError, match="evidence"):
        wf.attest("bot", "alice", None, "DEFINE_ORGANIZATIONAL_PROFILE_BOUNDARIES")
    with pytest.raises(WorkflowError, match="not an action of the current stage"):
        wf.attest("bot", "alice", None, "DEDUPLICATE_OVERLAPPING_REQUIREMENTS")
    with pytest.raises(WorkflowError, match="belongs to SCOPING_COMPLIANCE_LEAD"):
        wf.attest("bot", "alice", "THIRD_LINE_AUDITOR", "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS")
    wf.attest("bot", "alice", None, "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS", "reviewed")
    assert wf.state("bot")["attestations"]["RATIONALIZE_NON_APPLICABLE_OBLIGATIONS"]["by"] == "alice"


def test_target_setting_and_default(wf):
    set_profile(wf)
    assert wf.target_of("bot", "gdpr:Art.33") == ("implemented", None)
    n = wf.set_target("bot", "alice", "verified", "2026-12-31", domain="incident")
    assert n > 3
    assert wf.target_of("bot", "gdpr:Art.33") == ("verified", "2026-12-31")
    with pytest.raises(WorkflowError, match="target"):
        wf.set_target("bot", "alice", "in_progress", controls=["gdpr:Art.33"])
    with pytest.raises(WorkflowError, match="date"):
        wf.set_target("bot", "alice", "verified", "soon", controls=["gdpr:Art.33"])


# ---- gates ---------------------------------------------------------------------------------------
def test_advance_is_blocked_until_the_stage_is_satisfied(wf):
    with pytest.raises(WorkflowError, match="cannot leave this stage yet.*DEFINE_ORGANIZATIONAL_PROFILE_BOUNDARIES"):
        wf.advance("bot", "alice")
    set_profile(wf)
    wf.attest("bot", "alice", None, "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS")
    assert wf.advance("bot", "alice") == "CONTROL_HARMONIZATION"
    assert wf.state("bot")["stage"] == "CONTROL_HARMONIZATION"


def test_forcing_a_gate_needs_a_reason_and_is_recorded(wf):
    with pytest.raises(WorkflowError, match="reason"):
        wf.advance("bot", "alice", force=True)
    wf.advance("bot", "alice", force=True, reason="Board deadline")
    ev = wf.audit_log[-1]
    assert ev["action"] == "STAGE_ADVANCED" and ev["details"]["forced"] is True
    assert ev["details"]["reason"] == "Board deadline" and "DEFINE_ORGANIZATIONAL_PROFILE_BOUNDARIES" in ev["details"]["open_actions"]
    assert wf.state("bot")["stage_log"][0]["forced"] is True


# ---- stage 2: common controls -------------------------------------------------------------------------
def test_suggest_proposes_one_common_control_per_domain_and_apply_maps_everything(wf):
    props = wf.cc_suggest("bot")
    domains = {c.domain_id for c, _d in wf.scope.rows("bot")}
    assert {p["domain_id"] for p in props} == domains and len(props) == len(domains)
    assert wf.cc_suggest("bot", min_frameworks=2) == [p for p in props if p["frameworks"] >= 2]
    assert len(wf.unmapped("bot")) == len(wf.scope.in_scope("bot"))
    assert wf.cc_apply_suggestions("bot", "arch", props) == len(props)
    assert wf.unmapped("bot") == [] and wf.cc_suggest("bot") == []
    cc = next(iter(wf.state("bot")["common_controls"]))
    assert wf.members("bot", cc)


def test_not_applicable_controls_are_never_mapped(wf):
    wf.scope.set("bot", wf.scope.select("bot", ["gdpr:Art.33"]), applicable=False, justification="n/a")
    wf.cc_add("bot", "arch", "One")
    wf.cc_map("bot", "arch", "CC-001", ["gdpr:Art.34"])
    with pytest.raises(WorkflowError, match="not-applicable"):
        wf.cc_map("bot", "arch", "CC-001", ["gdpr:Art.33"])
    assert "gdpr:Art.33" not in {c.id for c in wf.unmapped("bot")}


def test_remapping_needs_move_and_one_control_has_one_common_control(wf):
    wf.cc_add("bot", "arch", "One")
    wf.cc_add("bot", "arch", "Two")
    wf.cc_map("bot", "arch", "CC-001", ["gdpr:Art.34"])
    with pytest.raises(WorkflowError, match="already mapped to CC-001"):
        wf.cc_map("bot", "arch", "CC-002", ["gdpr:Art.34"])
    wf.cc_map("bot", "arch", "CC-002", ["gdpr:Art.34"], move=True)
    assert wf.members("bot", "CC-001") == [] and wf.members("bot", "CC-002") == ["gdpr:Art.34"]


def test_cc_ids_and_validation(wf):
    assert wf.cc_add("bot", "arch", "A")["id"] == "CC-001"
    assert wf.cc_add("bot", "arch", "B", cc_id="X-9")["id"] == "X-9"
    with pytest.raises(WorkflowError, match="exists"):
        wf.cc_add("bot", "arch", "C", cc_id="X-9")
    with pytest.raises(WorkflowError, match="title"):
        wf.cc_add("bot", "arch", " ")
    with pytest.raises(WorkflowError, match="unknown common control"):
        wf.cc_map("bot", "arch", "CC-404", ["gdpr:Art.34"])


def test_accepting_unmapped_gaps_needs_a_reason_and_clears_them(wf):
    before = len(wf.unmapped("bot"))
    with pytest.raises(WorkflowError, match="reason"):
        wf.gap_accept("bot", "arch", ["gdpr:Art.34"], "")
    wf.gap_accept("bot", "arch", ["gdpr:Art.34"], "Covered by the DPA with our processor")
    assert len(wf.unmapped("bot")) == before - 1


def test_stage_two_actions(wf):
    wf.cc_apply_suggestions("bot", "arch", wf.cc_suggest("bot"))
    wf.state("bot")["stage"] = "CONTROL_HARMONIZATION"
    by = {a["action"]: a for a in wf.actions("bot")}
    assert by["MAP_PLATFORM_FRAMEWORKS_TO_COMMON_CONTROLS"]["satisfied"]
    assert by["IDENTIFY_UNMAPPED_FRAMEWORK_GAPS"]["satisfied"]
    assert not by["DEDUPLICATE_OVERLAPPING_REQUIREMENTS"]["satisfied"]


# ---- stage 3: tailoring ----------------------------------------------------------------------------------
def test_owner_and_reviewer_must_be_different_people(wf):
    wf.cc_add("bot", "arch", "One")
    wf.cc_set("bot", "o", "CC-001", owner="Dana")
    with pytest.raises(WorkflowError, match="separation of duties"):
        wf.cc_set("bot", "o", "CC-001", reviewer=" dana ")
    wf.policy_set("bot", "alice", "separation_of_duties", "false")
    wf.cc_set("bot", "o", "CC-001", reviewer="Dana")  # allowed once the policy is relaxed (and audited)
    assert wf.audit_log[-2]["action"] == "POLICY_CHANGED"


def test_cc_field_validation(wf):
    wf.cc_add("bot", "arch", "One")
    with pytest.raises(WorkflowError, match="frequency"):
        wf.cc_set("bot", "o", "CC-001", frequency="hourly")
    with pytest.raises(WorkflowError, match="test type"):
        wf.cc_set("bot", "o", "CC-001", test_type="magic")
    wf.cc_set("bot", "o", "CC-001", evidence_required=["a", "b"], parameters={"retention_days": "90"})
    wf.cc_set("bot", "o", "CC-001", evidence_required=["b", "c"])
    cc = wf.cc("bot", "CC-001")
    assert cc["evidence_required"] == ["a", "b", "c"] and cc["parameters"] == {"retention_days": "90"}


def test_tailoring_a_control_and_actions(wf):
    wf.tailor("bot", "owner1", "gdpr:Art.33", "Notify within 72 hours via the DPO")
    assert wf.scope.data["decisions"]["bot"]["gdpr:Art.33"]["implementation"].startswith("Notify")
    with pytest.raises(WorkflowError, match="empty"):
        wf.tailor("bot", "owner1", "gdpr:Art.33", " ")
    wf.cc_apply_suggestions("bot", "arch", wf.cc_suggest("bot"))
    wf.state("bot")["stage"] = "CONTROL_TAILORING"
    assert not any(a["satisfied"] for a in wf.actions("bot"))
    tailor_all(wf)
    assert all(a["satisfied"] for a in wf.actions("bot"))


# ---- stage 4: monitoring -------------------------------------------------------------------------------------
def test_ingest_accepts_dedupes_and_rejects(wf):
    wf.cc_add("bot", "arch", "One")
    recs = [{"control": "CC-001", "at": "2026-10-26T10:00:00Z", "result": "pass", "metrics": {"x": 1}},
            {"control": "CC-001", "at": "2026-10-26T10:00:00Z", "result": "pass", "metrics": {"x": 1}},
            {"control": "CC-999", "at": "2026-10-26T10:00:00Z", "result": "pass"},
            {"control": "CC-001", "at": "2026-10-26T10:00:00Z", "result": "maybe"},
            {"control": "CC-001", "at": "yesterday", "result": "pass"},
            {"control": "CC-001", "at": "2026-10-27", "result": "fail", "metrics": {"x": "high"}},
            "not an object"]
    out = wf.ingest("bot", "engine", recs, "feed")
    assert out["accepted"] == 1 and out["duplicates"] == 1 and len(out["rejected"]) == 5
    assert wf.state("bot")["measurements"][0]["at"] == "2026-10-26T10:00:00Z"


def test_effectiveness_states(wf, clock):
    wf.cc_add("bot", "arch", "One")
    wf.cc_set("bot", "o", "CC-001", frequency="monthly")
    assert wf.effectiveness("bot", "CC-001")["state"] == "not_tested"

    def feed(results):
        wf.state("bot")["measurements"].clear()
        wf.ingest("bot", "e", [{"control": "CC-001", "at": f"2026-10-2{i + 1}T00:00:00Z", "result": r}
                               for i, r in enumerate(results)], f"s{results}")

    feed(["pass"] * 5)
    assert wf.effectiveness("bot", "CC-001")["state"] == "effective"
    feed(["pass", "pass", "pass", "pass", "fail"])  # 80%: below 90%, above 60%
    assert wf.effectiveness("bot", "CC-001")["state"] == "partially_effective"
    feed(["fail", "fail", "fail", "fail", "pass"])
    assert wf.effectiveness("bot", "CC-001")["state"] == "ineffective"
    feed(["pass"] * 5)
    clock["now"] = NOW + dt.timedelta(days=60)  # a monthly control last tested ~60 days ago
    assert wf.effectiveness("bot", "CC-001")["state"] == "stale"


def test_indicators_breach_is_recorded_once_and_can_be_acknowledged(wf):
    wf.cc_add("bot", "arch", "Access reviews")
    with pytest.raises(WorkflowError, match="kind"):
        wf.indicator_add("bot", "risk", "CC-001", "x", "KPI", "m", ">", 1)
    with pytest.raises(WorkflowError, match="operator"):
        wf.indicator_add("bot", "risk", "CC-001", "x", "KRI", "m", "==", 1)
    wf.indicator_add("bot", "risk", "CC-001", "Failed logins", "KRI", "failed_logins", ">", 5)
    wf.ingest("bot", "engine", [{"control": "CC-001", "at": "2026-10-26T10:00:00Z", "result": "pass",
                                 "metrics": {"failed_logins": 9}}], "iam")
    first = wf.evaluate("bot", "engine")
    assert len(first["breaches"]) == 1 and len(first["new_escalations"]) == 1
    second = wf.evaluate("bot", "engine")
    assert len(second["breaches"]) == 1 and second["new_escalations"] == []  # idempotent
    assert sum(1 for e in wf.audit_log if e["action"] == "KRI_BREACH") == 1
    key = wf.state("bot")["escalations"][0]["key"]
    wf.escalation_ack("bot", "risk", key, "investigating")
    assert wf.state("bot")["escalations"][0]["status"] == "acknowledged"
    with pytest.raises(WorkflowError, match="unknown escalation"):
        wf.escalation_ack("bot", "risk", "nope")


def test_a_healthy_metric_raises_no_escalation(wf):
    wf.cc_add("bot", "arch", "One")
    wf.indicator_add("bot", "risk", "CC-001", "Coverage", "KCI", "coverage", "<", 95)
    wf.ingest("bot", "e", [{"control": "CC-001", "at": "2026-10-26T10:00:00Z", "result": "pass", "metrics": {"coverage": 99.5}}], "s")
    assert wf.evaluate("bot", "e")["breaches"] == []


def test_stage_four_actions_need_results_indicators_and_a_fresh_evaluation(wf):
    wf.cc_apply_suggestions("bot", "arch", wf.cc_suggest("bot"))
    tailor_all(wf)
    wf.state("bot")["stage"] = "CONTINUOUS_MONITORING"
    assert not any(a["satisfied"] for a in wf.actions("bot"))
    ingest_all(wf)
    first_cc = next(iter(wf.state("bot")["common_controls"]))
    wf.indicator_add("bot", "risk", first_cc, "Cov", "KCI", "coverage", "<", 90)
    wf.evaluate("bot", "engine")
    assert all(a["satisfied"] for a in wf.actions("bot"))
    wf.state("bot")["markers"]["last_ingest_at"] = "2099-01-01T00:00:00Z"  # new results arrived after the evaluation
    stale = {a["action"]: a["satisfied"] for a in wf.actions("bot")}
    assert stale["INGEST_AUTOMATED_EVIDENCE_FEEDS"] and not stale["CALCULATE_REALTIME_CONTROL_EFFECTIVENESS"]


# ---- stage 5: exceptions ---------------------------------------------------------------------------------------
def make_exception(wf, likelihood=3, impact=3, assessor="bob"):
    ex = wf.exception_request("bot", "alice", "Legacy system cannot support the control yet",
                              controls=["gdpr:Art.33"], compensating="Manual review weekly")
    wf.exception_assess("bot", assessor, ex["id"], likelihood, impact, "assessed")
    return ex["id"]


def test_exception_request_validation(wf):
    with pytest.raises(WorkflowError, match="reason"):
        wf.exception_request("bot", "alice", " ", controls=["gdpr:Art.33"])
    with pytest.raises(WorkflowError, match="name the controls"):
        wf.exception_request("bot", "alice", "why")
    with pytest.raises(WorkflowError, match="type"):
        wf.exception_request("bot", "alice", "why", kind="whim", controls=["gdpr:Art.33"])
    wf.scope.set("bot", wf.scope.select("bot", ["gdpr:Art.34"]), applicable=False, justification="n/a")
    with pytest.raises(WorkflowError, match="not applicable"):
        wf.exception_request("bot", "alice", "why", controls=["gdpr:Art.34"])


def test_assessment_scores_and_separation_of_duties(wf):
    ex = wf.exception_request("bot", "alice", "why", controls=["gdpr:Art.33"])
    with pytest.raises(WorkflowError, match="separation of duties"):
        wf.exception_assess("bot", "Alice", ex["id"], 2, 2)
    with pytest.raises(WorkflowError, match="1 to 5"):
        wf.exception_assess("bot", "bob", ex["id"], 6, 2)
    for (l, i), rating in {(1, 2): "low", (3, 3): "medium", (4, 4): "high", (5, 5): "critical"}.items():
        wf.exception_assess("bot", "bob", ex["id"], l, i)
        assert wf.state("bot")["exceptions"][ex["id"]]["assessment"]["rating"] == rating


def test_a_medium_exception_needs_executive_signoff_and_has_a_duration_cap(wf):
    ex_id = make_exception(wf, 3, 3)
    with pytest.raises(WorkflowError, match="needs sign-off by EXECUTIVE_APPROVER"):
        wf.exception_approve("bot", "dana", ROLE_SECOND_LINE, ex_id, 30)
    with pytest.raises(WorkflowError, match="at most 180 days"):
        wf.exception_approve("bot", "carol", ROLE_EXECUTIVE, ex_id, 365)
    with pytest.raises(WorkflowError, match="separation of duties.*requester"):
        wf.exception_approve("bot", "alice", ROLE_EXECUTIVE, ex_id, 30)
    with pytest.raises(WorkflowError, match="separation of duties.*assessor"):
        wf.exception_approve("bot", "bob", ROLE_EXECUTIVE, ex_id, 30)
    ex = wf.exception_approve("bot", "carol", ROLE_EXECUTIVE, ex_id, 90)
    assert ex["status"] == "approved" and ex["expires"] == "2027-01-25"


def test_a_low_exception_can_be_signed_off_by_the_second_line(wf):
    ex_id = make_exception(wf, 1, 2)
    ex = wf.exception_approve("bot", "dana", ROLE_SECOND_LINE, ex_id, 365)
    assert ex["status"] == "approved"


def test_exception_must_be_assessed_before_approval_and_rejection_rules(wf):
    ex = wf.exception_request("bot", "alice", "why", controls=["gdpr:Art.33"])
    with pytest.raises(WorkflowError, match="must be assessed"):
        wf.exception_approve("bot", "carol", ROLE_EXECUTIVE, ex["id"], 30)
    with pytest.raises(WorkflowError, match="second line or an executive"):
        wf.exception_reject("bot", "alice", "FIRST_LINE_CONTROL_OWNER", ex["id"], "no")
    with pytest.raises(WorkflowError, match="reason"):
        wf.exception_reject("bot", "carol", ROLE_EXECUTIVE, ex["id"], " ")
    wf.exception_reject("bot", "carol", ROLE_EXECUTIVE, ex["id"], "Compensating control is not sufficient")
    assert wf.state("bot")["exceptions"][ex["id"]]["status"] == "rejected"


def test_approved_exceptions_become_expiring_then_expired_and_can_be_reopened(wf, clock):
    ex_id = make_exception(wf, 3, 3)
    wf.exception_approve("bot", "carol", ROLE_EXECUTIVE, ex_id, 90)
    state = lambda: next(e["state"] for e in wf.exceptions("bot") if e["id"] == ex_id)  # noqa: E731
    assert state() == "active"
    clock["now"] = NOW + dt.timedelta(days=80)  # 10 days left, inside the 14-day warning
    assert state() == "expiring"
    clock["now"] = NOW + dt.timedelta(days=100)
    assert state() == "expired"
    ex = wf.exception_reopen("bot", "alice", ex_id, "Still needed")
    assert ex["status"] == "requested" and ex["revision"] == 2 and ex["approvals"] == [] and ex["assessment"] is None
    assert [h["action"] for h in ex["history"]] == ["requested", "assessed", "approved", "reopened"]


def test_exception_can_cover_a_common_control(wf):
    wf.cc_add("bot", "arch", "Incident process")
    wf.cc_map("bot", "arch", "CC-001", ["gdpr:Art.33", "gdpr:Art.34"])
    ex = wf.exception_request("bot", "alice", "why", cc="CC-001")
    assert wf.exception_covers("bot", ex) == {"gdpr:Art.33", "gdpr:Art.34"}


def test_stage_five_actions(wf, clock):
    wf.state("bot")["stage"] = "EXCEPTION_GOVERNANCE"
    assert all(a["satisfied"] for a in wf.actions("bot"))  # nothing pending
    ex_id = make_exception(wf, 3, 3)
    assert not {a["action"]: a["satisfied"] for a in wf.actions("bot")}["PROCESS_CONTROL_EXCEPTION_REQUESTS"]
    wf.exception_approve("bot", "carol", ROLE_EXECUTIVE, ex_id, 30)
    assert all(a["satisfied"] for a in wf.actions("bot"))
    clock["now"] = NOW + dt.timedelta(days=45)
    by = {a["action"]: a["satisfied"] for a in wf.actions("bot")}
    assert not by["ENFORCE_EXECUTIVE_APPROVAL_AND_EXPIRATION_DATES"]  # expired: needs re-assessment


def test_policy_changes_are_validated_and_audited(wf):
    with pytest.raises(WorkflowError, match="unknown policy"):
        wf.policy_set("bot", "a", "colour", "red")
    with pytest.raises(WorkflowError, match="invalid value"):
        wf.policy_set("bot", "a", "reassess_warning_days", "soon")
    with pytest.raises(WorkflowError, match="thresholds"):
        wf.policy_set("bot", "a", "partial_threshold", "0.95")
    wf.state("bot")["policy"].pop("partial_threshold", None)
    pol = wf.policy_set("bot", "a", "exception_max_days.high", "60")
    assert pol["exception_max_days"]["high"] == 60 and pol["exception_max_days"]["low"] == 365
    assert wf.audit_log[-1]["action"] == "POLICY_CHANGED"


# ---- stage 6: gap analysis, POA&M, report ------------------------------------------------------------------------
def test_gap_analysis_classifies_open_overdue_and_excepted(wf, clock):
    set_profile(wf)
    ctrl = lambda ids: wf.scope.select("bot", ids)  # noqa: E731
    wf.scope.set("bot", ctrl(["gdpr:Art.5(1)", "gdpr:Art.6"]), status="implemented")
    wf.scope.set("bot", ctrl(["gdpr:Art.7"]), status="in_progress", due="2026-01-01", owner="Dana")
    ex_id = make_exception(wf, 3, 3)  # covers gdpr:Art.33
    wf.exception_approve("bot", "carol", ROLE_EXECUTIVE, ex_id, 30)
    res = wf.gap_analysis("bot")
    states = {g["control_id"]: g for g in res["gaps"]}
    assert res["at_target"] == 2 and res["applicable"] == len(wf.scope.in_scope("bot"))
    assert states["gdpr:Art.7"]["state"] == "overdue" and states["gdpr:Art.7"]["owner"] == "Dana"
    assert states["gdpr:Art.33"]["state"] == "excepted" and states["gdpr:Art.33"]["exception"] == ex_id
    assert states["gdpr:Art.8"]["state"] == "open"
    assert "gdpr:Art.5(1)" not in states
    clock["now"] = NOW + dt.timedelta(days=45)  # exception expired: the gap comes back, flagged
    again = {g["control_id"]: g for g in wf.gap_analysis("bot")["gaps"]}
    assert again["gdpr:Art.33"]["state"] != "excepted" and again["gdpr:Art.33"]["exception_expired"] is True


def test_per_control_targets_change_the_gap(wf):
    set_profile(wf)
    ids = ["gdpr:Art.5(1)"]
    wf.scope.set("bot", wf.scope.select("bot", ids), status="implemented")
    assert "gdpr:Art.5(1)" not in {g["control_id"] for g in wf.gap_analysis("bot")["gaps"]}
    wf.set_target("bot", "alice", "verified", controls=ids)
    assert "gdpr:Art.5(1)" in {g["control_id"] for g in wf.gap_analysis("bot")["gaps"]}


def test_assurance_gap_when_done_controls_sit_under_an_ineffective_common_control(wf):
    set_profile(wf)
    wf.cc_add("bot", "arch", "Incident process")
    wf.cc_map("bot", "arch", "CC-001", ["gdpr:Art.33", "gdpr:Art.34"])
    wf.scope.set("bot", wf.scope.select("bot", ["gdpr:Art.33"]), status="implemented")
    wf.ingest("bot", "e", [{"control": "CC-001", "at": "2026-10-26T10:00:00Z", "result": "fail"}], "s")
    gaps = wf.gap_analysis("bot")["assurance_gaps"]
    assert gaps and gaps[0]["cc"] == "CC-001" and gaps[0]["state"] == "ineffective" and gaps[0]["controls_claiming_done"] == 1


def test_poam_rows_are_csv_safe_and_match_the_gaps(wf):
    set_profile(wf)
    wf.scope.set("bot", wf.scope.select("bot", ["gdpr:Art.7"]), status="in_progress", owner="=cmd|' /C calc'!A0")
    rows = wf.poam("bot")
    assert len(rows) == len(wf.gap_analysis("bot")["gaps"])
    from aicontrols.scope import csv_safe
    assert csv_safe(next(r for r in rows if r["control_id"] == "gdpr:Art.7")["owner"]).startswith("'=")


def test_report_contents_and_markers(wf):
    set_profile(wf)
    wf.cc_apply_suggestions("bot", "arch", wf.cc_suggest("bot"))
    rep = wf.report("bot", "auditor", record=True)
    assert rep["scope"]["unmapped"] == 0 and rep["audit"]["chain_valid"] is True
    assert rep["common_controls"]["effectiveness"] == {"not_tested": rep["common_controls"]["count"]}
    assert wf.state("bot")["markers"]["report_at"] is not None
    md = wf.report_markdown("bot", "auditor")
    assert md.startswith("# Governance report: Bot") and "hash chain valid" in md and "not an attestation" in md


# ---- the whole lifecycle ------------------------------------------------------------------------------------------
def run_lifecycle(w):
    set_profile(w)
    w.attest("bot", "alice", None, "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS")
    assert w.advance("bot", "alice") == "CONTROL_HARMONIZATION"
    w.cc_apply_suggestions("bot", "arch", w.cc_suggest("bot"))
    w.attest("bot", "arch", None, "DEDUPLICATE_OVERLAPPING_REQUIREMENTS")
    assert w.advance("bot", "arch") == "CONTROL_TAILORING"
    tailor_all(w)
    assert w.advance("bot", "owner1") == "CONTINUOUS_MONITORING"
    ingest_all(w, metrics={"coverage": 99})
    first = next(iter(w.state("bot")["common_controls"]))
    w.indicator_add("bot", "risk", first, "Coverage", "KCI", "coverage", "<", 90)
    w.evaluate("bot", "engine")
    assert w.advance("bot", "engine") == "EXCEPTION_GOVERNANCE"
    assert w.advance("bot", "risk") == "TARGET_GAP_ANALYSIS"
    w.gap_analysis("bot", "auditor", record=True)
    ok, _ = w.verify("bot", "auditor")
    assert ok
    w.report("bot", "auditor", record=True)
    assert w.advance("bot", "auditor") == "cycle complete"


def test_full_lifecycle_through_all_six_stages(wf):
    run_lifecycle(wf)
    st = wf.state("bot")
    assert [e["stage"] for e in st["stage_log"]] == wf.order
    assert not any(e["forced"] for e in st["stage_log"]) and st["completed_cycles"][0]["cycle"] == 1
    assert wf.audit_log[-1]["action"] == "CYCLE_COMPLETED" and verify_audit(wf.audit_log)[0]
    assert wf.scope.validate() == ([], [])


def test_restart_keeps_mappings_and_results_but_resets_the_checklist(wf):
    run_lifecycle(wf)
    ccs = len(wf.state("bot")["common_controls"])
    assert wf.restart_cycle("bot", "alice", "Quarterly review") == 2
    st = wf.state("bot")
    assert st["stage"] == "FRAMEWORK_SCOPING" and st["attestations"] == {} and st["markers"]["report_at"] is None
    assert len(st["common_controls"]) == ccs and st["measurements"]
    assert not {a["action"]: a["satisfied"] for a in wf.actions("bot")}["RATIONALIZE_NON_APPLICABLE_OBLIGATIONS"]


def test_file_round_trip_and_schema(wf, tmp_path):
    run_lifecycle(wf)
    wf.exception_request("bot", "alice", "why", controls=["gdpr:Art.33"])
    p = tmp_path / "scope.json"
    wf.scope.save(p)
    again = Scope.load(p, wf.lib)
    assert again.validate() == ([], []) and Workflow(again).state("bot")["cycle"] == 1
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schema" / "scope.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(json.loads(p.read_text()))


def test_validation_catches_corrupted_workflow_state(wf):
    run_lifecycle(wf)
    data = wf.scope.data
    st = data["workflow"]["bot"]
    first = next(iter(st["common_controls"]))
    cid = wf.members("bot", first)[0]
    data["decisions"]["bot"][cid]["common_control"] = "CC-404"
    st["measurements"].append({"cc": "CC-404", "at": "2026-10-26T00:00:00Z", "result": "pass", "metrics": {}, "source": "x"})
    st["stage"] = "NOPE"
    data["audit"][2]["actor"] = "mallory"
    text = "\n".join(wf.scope.validate()[0])
    assert "unknown common control 'CC-404'" in text and "unknown workflow stage" in text and "audit:" in text


# ---- CLI --------------------------------------------------------------------------------------------------------------
def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_workflow_scenario(capsys, tmp_path):
    f = str(tmp_path / "scope.json")
    r = lambda *a: run(capsys, *a, "--file", f)  # noqa: E731
    assert r("scope", "init", "--org", "T")[0] == 0
    assert r("scope", "add-system", "bot", "--frameworks", "gdpr")[0] == 0
    assert r("workflow", "init", "--by", "alice")[0] == 0
    code, out, _ = r("workflow", "status")
    assert code == 0 and "FRAMEWORK_SCOPING" in out and "[ ] DEFINE_ORGANIZATIONAL_PROFILE_BOUNDARIES" in out
    code, _, err = r("workflow", "advance", "--by", "alice")
    assert code == 2 and "cannot leave this stage yet" in err
    assert r("workflow", "profile", "--business-unit", "Retail", "--environment", "prod", "--boundary", "EU",
             "--risk-appetite", "moderate", "--target-default", "implemented", "--by", "alice")[0] == 0
    assert r("workflow", "attest", "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS", "--by", "alice")[0] == 0
    code, out, _ = r("workflow", "advance", "--by", "alice")
    assert code == 0 and "CONTROL_HARMONIZATION" in out
    assert r("workflow", "cc", "add", "Incident process", "--by", "arch")[0] == 0
    assert r("workflow", "cc", "map", "CC-001", "gdpr:Art.33", "gdpr:Art.34", "--by", "arch")[0] == 0
    code, out, _ = r("workflow", "cc", "suggest")
    assert code == 0 and "proposed common control" in out
    assert r("workflow", "cc", "set", "CC-001", "--owner", "Dana", "--reviewer", "Eli", "--frequency", "monthly",
             "--test-type", "automated", "--test-description", "query", "--evidence", "log extract",
             "--implementation", "Runbook v2", "--param", "window=72h", "--by", "dana")[0] == 0
    code, _, err = r("workflow", "cc", "set", "CC-001", "--reviewer", "dana", "--by", "x")
    assert code == 2 and "separation of duties" in err
    code, out, _ = r("workflow", "cc", "show", "CC-001")
    assert code == 0 and "Runbook v2" in out and "gdpr:Art.33" in out
    assert r("workflow", "indicator", "add", "CC-001", "--name", "Late notices", "--kind", "KRI", "--metric", "late",
             "--op", ">", "--value", "2", "--by", "risk")[0] == 0
    feed = tmp_path / "results.jsonl"
    feed.write_text('{"control":"CC-001","at":"2026-10-20T10:00:00Z","result":"pass","metrics":{"late":0}}\n'
                    '{"control":"CC-001","at":"2026-10-21T10:00:00Z","result":"fail","metrics":{"late":4}}\n')
    code, out, _ = r("workflow", "ingest", str(feed), "--by", "engine")
    assert code == 0 and "ingested 2 result(s)" in out
    code, out, _ = r("workflow", "ccm", "evaluate", "--by", "engine")
    assert code == 0 and "BREACH KRI CC-001/KRI-1" in out and "1 new escalation" in out
    assert r("workflow", "ccm", "escalations")[0] == 0
    # exceptions: request -> assess -> approve with the right role
    assert r("workflow", "exception", "request", "--control", "gdpr:Art.33", "--reason", "legacy", "--by", "alice")[0] == 0
    code, out, _ = r("workflow", "exception", "assess", "EX-001", "--likelihood", "4", "--impact", "4", "--by", "bob")
    assert code == 0 and "high" in out and "EXECUTIVE_APPROVER" in out
    code, _, err = r("workflow", "exception", "approve", "EX-001", "--role", "SECOND_LINE_RISK_MANAGER", "--days", "30", "--by", "dana")
    assert code == 2 and "needs sign-off by EXECUTIVE_APPROVER" in err
    code, out, _ = r("workflow", "exception", "approve", "EX-001", "--role", "EXECUTIVE_APPROVER", "--days", "30", "--by", "carol")
    assert code == 0 and "approved until" in out
    assert r("workflow", "exception", "list")[0] == 0
    assert r("workflow", "exception", "review")[0] == 0
    code, out, _ = r("workflow", "gap", "--by", "auditor")
    assert code == 0 and "applicable controls at or above target" in out
    poam = tmp_path / "poam.csv"
    assert r("workflow", "poam", "-o", str(poam))[0] == 0
    assert list(csv.DictReader(poam.open()))[0]["control_id"].startswith("gdpr:")
    code, out, _ = r("workflow", "audit", "verify", "--by", "auditor")
    assert code == 0 and "audit chain OK" in out
    assert r("workflow", "audit", "show", "-n", "3")[0] == 0
    rep = tmp_path / "report.md"
    assert r("workflow", "report", "-o", str(rep), "--by", "auditor")[0] == 0 and rep.read_text().startswith("# Governance report")
    code, out, _ = r("workflow", "report", "--format", "json", "--by", "auditor")
    assert code == 0 and json.loads(out)["audit"]["chain_valid"] is True
    assert r("scope", "validate")[0] == 0
    code, _, _ = r("workflow", "advance", "--force", "--reason", "demo", "--by", "alice")
    assert code == 0


def test_cli_audit_verify_fails_on_a_tampered_file(capsys, tmp_path):
    f = str(tmp_path / "scope.json")
    run(capsys, "scope", "init", "--org", "T", "--file", f)
    run(capsys, "scope", "add-system", "bot", "--frameworks", "gdpr", "--file", f)
    run(capsys, "workflow", "init", "--by", "alice", "--file", f)
    run(capsys, "workflow", "profile", "--business-unit", "BU", "--by", "alice", "--file", f)
    data = json.loads(Path(f).read_text())
    data["audit"][1]["actor"] = "mallory"
    Path(f).write_text(json.dumps(data))
    code, out, _ = run(capsys, "workflow", "audit", "verify", "--by", "auditor", "--file", f)
    assert code == 1 and "BROKEN" in out and "edited" in out
    assert run(capsys, "scope", "validate", "--file", f)[0] == 1


def test_cli_requires_workflow_to_be_enabled(capsys, tmp_path):
    f = str(tmp_path / "scope.json")
    run(capsys, "scope", "init", "--org", "T", "--file", f)
    run(capsys, "scope", "add-system", "bot", "--frameworks", "gdpr", "--file", f)
    code, _, err = run(capsys, "workflow", "status", "--file", f)
    assert code == 2 and "not enabled" in err
