# SPDX-License-Identifier: Apache-2.0
import csv
import datetime as dt
import io
import json
from pathlib import Path

import pytest

import aicontrols
from aicontrols import workflow as wfmod
from aicontrols.cli import main
from aicontrols.grc import Grc, GrcError, add_months, load_spec
from aicontrols.scope import Scope
from aicontrols.workflow import Workflow, WorkflowError, verify_audit

NOW = dt.datetime(2026, 11, 9, 12, 0, 0, tzinfo=dt.timezone.utc)
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


@pytest.fixture
def clock(monkeypatch):
    state = {"now": NOW}
    monkeypatch.setattr(wfmod, "_now", lambda: state["now"])
    return state


@pytest.fixture
def world(lib, clock):
    """A system with iso-42001 + gdpr, two common controls with mappings, and workflow enabled."""
    s = Scope.new("Org", lib)
    s.add_system("bot", "Bot", ["iso-42001", "gdpr"])
    w = Workflow(s)
    w.enable("bot", "alice")
    w.cc_add("bot", "arch", "Incident response")
    w.cc_map("bot", "arch", "CC-001", ["gdpr:Art.33", "gdpr:Art.34", "iso-42001:A.8.4"])
    w.cc_add("bot", "arch", "AI governance")
    w.cc_map("bot", "arch", "CC-002", ["iso-42001:A.2.2", "iso-42001:A.2.3"])
    return s, w, Grc(s)


def feed(w, cc="CC-001", result="pass", at="2026-11-08T10:00:00Z"):
    w.ingest("bot", "engine", [{"control": cc, "at": at, "result": result}], f"feed-{cc}-{at}")


# ---- spec ------------------------------------------------------------------------------------------
def test_spec_covers_the_source_notes():
    spec = load_spec()
    assert [s["name"] for s in spec["streams"]] == ["Leadership", "Technology", "Policy", "Requirements", "Data quality (DQ)"]
    assert len(spec["lifecycle"]) == 10 and len(spec["artifacts"]) == 10 and len(spec["roles"]) == 6 and len(spec["kpis"]) == 6
    assert {e["source"] for e in spec["evidence_defaults"]} == {"IAM / PAM", "Scanners / CSPM", "SIEM", "CI/CD", "GRC platform"}
    assert len(spec["open_items"]) == 6


def test_every_iso_42001_requirement_belongs_to_exactly_one_stream(lib, world):
    s, w, g = world
    streams = g.streams("bot")
    assert sum(x["requirements"] for x in streams) == len(lib.filter(framework="iso-42001")) and not any(x["id"] == "unassigned" for x in streams)
    # specificity: an exact rule beats a prefix rule
    spec = load_spec()
    from aicontrols.grc import _matches
    best = lambda ref: max(((_matches(p, ref) or -1, st["id"]) for st in spec["streams"] for p in st["refs"]))[1]  # noqa: E731
    assert best("A.4.3") == "data_quality" and best("A.4.4") == "technology" and best("4.2") == "requirements"
    assert best("6.2") == "leadership" and best("6.1.2") == "technology" and best("A.7.5") == "data_quality" and best("A.2.2") == "policy"


# ---- registers -------------------------------------------------------------------------------------------
def test_adding_records_validates_fields(world):
    s, w, g = world
    with pytest.raises(GrcError, match="Type is required|Title is required"):
        g.add("documents", "alice")
    with pytest.raises(GrcError, match="Type must be one of"):
        g.add("documents", "alice", type="memo", title="x", owner="o")
    with pytest.raises(GrcError, match="date like"):
        g.add("documents", "alice", type="policy", title="x", owner="o", approved="1/2/2026")
    with pytest.raises(GrcError, match="whole number"):
        g.add("documents", "alice", type="policy", title="x", owner="o", review_months="0")
    with pytest.raises(GrcError, match="unknown field"):
        g.add("documents", "alice", type="policy", title="x", owner="o", colour="red")
    with pytest.raises(GrcError, match="unknown register"):
        g.add("widgets", "alice", title="x")
    with pytest.raises(WorkflowError, match="actor"):
        g.add("documents", "  ", type="policy", title="x", owner="o")
    assert g.records("documents") == []


def test_ids_defaults_and_audit(world):
    s, w, g = world
    a = g.add("documents", "alice", type="policy", title="AI policy", owner="CISO")
    b = g.add("documents", "alice", type="sop", title="IR SOP", owner="SecOps")
    assert (a["id"], b["id"]) == ("DOC-001", "DOC-002") and a["status"] == "draft" and a["review_months"] == 12
    assert s.data["schema_version"] == "1.2"
    assert [e["action"] for e in s.data["audit"][-2:]] == ["GRC_DOCUMENTS_ADDED"] * 2 and s.data["audit"][-1]["system"] == "(organisation)"
    assert verify_audit(s.data["audit"])[0] and s.validate() == ([], [])


def test_approved_documents_get_a_review_date(world, clock):
    s, w, g = world
    d = g.add("documents", "alice", type="policy", title="P", owner="o", status="approved", review_months=6)
    assert d["approved"] == "2026-11-09" and d["next_review"] == "2027-05-09"
    d = g.update("documents", "alice", d["id"], review_months=3)
    assert d["next_review"] == "2027-02-09"
    d = g.update("documents", "alice", d["id"], next_review="2030-01-01")
    assert d["next_review"] == "2030-01-01"


def test_add_months_clamps_the_day():
    assert add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28) and add_months(dt.date(2028, 1, 31), 1) == dt.date(2028, 2, 29)
    assert add_months(dt.date(2026, 11, 30), 3) == dt.date(2027, 2, 28) and add_months(dt.date(2026, 12, 15), 12) == dt.date(2027, 12, 15)


def test_register_specific_rules(world, clock):
    s, w, g = world
    with pytest.raises(GrcError, match="exclusion needs a justification"):
        g.add("scope_items", "alice", kind="exclusion", name="Legacy ERP")
    g.add("scope_items", "alice", kind="exclusion", name="Legacy ERP", justification="Decommissioned in Q1")
    with pytest.raises(GrcError, match="Due cannot be before"):
        g.add("findings", "alice", title="f", severity="high", source="internal", owner="o", raised="2026-11-01", due="2026-10-01")
    f = g.add("findings", "alice", title="f", severity="high", source="internal", owner="o", raised="2026-10-01", due="2026-12-01")
    assert f["status"] == "open" and "closed" not in f
    f = g.update("findings", "alice", f["id"], status="closed")
    assert f["closed"] == "2026-11-09"
    f = g.update("findings", "alice", f["id"], status="open")
    assert "closed" not in f
    with pytest.raises(GrcError, match="Completed on cannot be before"):
        g.add("audits", "alice", title="a", kind="internal", planned="2026-11-05", completed="2026-11-01")


def test_update_clears_optional_fields_but_not_required_ones(world):
    s, w, g = world
    d = g.add("documents", "alice", type="policy", title="P", owner="o", url="http://x")
    assert "url" not in g.update("documents", "alice", d["id"], url="")
    with pytest.raises(GrcError, match="Owner is required"):
        g.update("documents", "alice", d["id"], owner="")
    with pytest.raises(GrcError, match="unknown document"):
        g.update("documents", "alice", "DOC-999", title="x")


def test_removing_a_document_or_source_removes_its_links(world):
    s, w, g = world
    p = g.add("documents", "alice", type="policy", title="P", owner="o")
    e = g.add("evidence_sources", "alice", type="Logs", source="SIEM", frequency="continuous")
    g.link("bot", "alice", "CC-001", policy=[p["id"]], evidence_sources=[e["id"]])
    g.remove("documents", "alice", p["id"])
    g.remove("evidence_sources", "alice", e["id"])
    cc = w.cc("bot", "CC-001")
    assert cc["documents"]["policy"] == [] and cc["evidence_sources"] == []
    assert s.validate() == ([], [])


def test_seeded_evidence_sources_come_from_the_notes(world):
    s, w, g = world
    assert g.seed_evidence_sources("alice") == 5 and g.seed_evidence_sources("alice") == 0
    assert {r["source"] for r in g.records("evidence_sources")} == {"IAM / PAM", "Scanners / CSPM", "SIEM", "CI/CD", "GRC platform"}


# ---- links, reviews, settings, roles ---------------------------------------------------------------------------
def test_links_check_document_types_and_existence(world):
    s, w, g = world
    p = g.add("documents", "alice", type="policy", title="P", owner="o")
    sop = g.add("documents", "alice", type="sop", title="S", owner="o")
    with pytest.raises(GrcError, match="is a policy, not a sop"):
        g.link("bot", "alice", "CC-001", sop=[p["id"]])
    with pytest.raises(GrcError, match="unknown document"):
        g.link("bot", "alice", "CC-001", policy=["DOC-404"])
    with pytest.raises(GrcError, match="unknown evidence source"):
        g.link("bot", "alice", "CC-001", evidence_sources=["EVS-404"])
    with pytest.raises(GrcError, match="nothing to link"):
        g.link("bot", "alice", "CC-001")
    with pytest.raises(WorkflowError, match="unknown common control"):
        g.link("bot", "alice", "CC-404", policy=[p["id"]])
    g.link("bot", "alice", "CC-001", policy=[p["id"]], sop=[sop["id"]])
    g.link("bot", "alice", "CC-001", policy=[p["id"]])  # idempotent
    assert w.cc("bot", "CC-001")["documents"] == {"policy": [p["id"]], "guideline": [], "sop": [sop["id"]]}
    g.link("bot", "alice", "CC-001", policy=[p["id"]], unlink=True)
    assert w.cc("bot", "CC-001")["documents"]["policy"] == []


def test_mapping_review_sets_owner_and_date_on_every_mapped_requirement(world, clock):
    s, w, g = world
    assert g.review_mappings("bot", "alice", "CC-001", "Head of SecOps") == 3
    rec = s.data["decisions"]["bot"]["gdpr:Art.33"]
    assert rec["mapping_owner"] == "Head of SecOps" and rec["mapping_reviewed"] == "2026-11-09"
    with pytest.raises(GrcError, match="needs an owner"):
        g.review_mappings("bot", "alice", "CC-001", " ")
    with pytest.raises(GrcError, match="date like"):
        g.review_mappings("bot", "alice", "CC-001", "x", "9 Nov")
    w.cc_add("bot", "arch", "Empty")
    with pytest.raises(GrcError, match="no mapped requirements"):
        g.review_mappings("bot", "alice", "CC-003", "x")


def test_settings_roles_scope_statements(world, lib):
    s, w, g = world
    assert g.settings()["anchor_framework"] == "iso-42001" and g.settings()["risk_appetite"] == "moderate"
    g.set_setting("alice", "risk_appetite", "low")
    g.set_setting("alice", "coverage_target.gdpr", "70")
    g.set_setting("alice", "mapping_review_months", "6")
    assert g.settings()["coverage_targets"] == {"gdpr": 70} and g.settings()["mapping_review_months"] == 6
    g.set_setting("alice", "coverage_target.gdpr", "")
    assert g.settings()["coverage_targets"] == {}
    for key, value in (("risk_appetite", "wild"), ("mapping_review_months", "0"), ("coverage_target.gdpr", "101"), ("anchor_framework", "nope"), ("colour", "x")):
        with pytest.raises(GrcError):
            g.set_setting("alice", key, value)
    assert g.set_roles("alice", "ciso_grc", ["Dana", " Dana ", "Eli"]) == ["Dana", "Eli"]
    with pytest.raises(GrcError, match="unknown role"):
        g.set_roles("alice", "wizard", ["x"])
    assert next(r for r in g.roles() if r["id"] == "ciso_grc")["people"] == ["Dana", "Eli"]
    with pytest.raises(GrcError, match="unknown framework"):
        g.set_scope_statement("alice", "nope", "x")
    with pytest.raises(GrcError, match="cannot be empty"):
        g.set_scope_statement("alice", "gdpr", " ")
    assert g.set_scope_statement("alice", "gdpr", "EU customers' data", "2026-10-01")["reviewed"] == "2026-10-01"


# ---- matrix --------------------------------------------------------------------------------------------------------------
def row(g, cid):
    return next(r for r in g.matrix("bot") if r["requirement_id"] == cid)


def test_matrix_statuses(world):
    s, w, g = world
    assert row(g, "gdpr:Art.8")["status"] == "Unmapped" and "unmapped" in row(g, "gdpr:Art.8")["issues"]
    w.gap_accept("bot", "arch", ["gdpr:Art.8"], "Covered by the DPA")
    assert row(g, "gdpr:Art.8")["status"] == "Gap" and row(g, "gdpr:Art.8")["gap_reason"] == "Covered by the DPA" and row(g, "gdpr:Art.8")["issues"] == []
    assert row(g, "gdpr:Art.33")["status"] == "Not started"
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), status="in_progress")
    assert row(g, "gdpr:Art.33")["status"] == "Partial"
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), status="implemented")
    assert row(g, "gdpr:Art.33")["status"] == "Partial"        # implemented, but no current evidence yet
    feed(w)
    assert row(g, "gdpr:Art.33")["status"] == "Implemented" and row(g, "gdpr:Art.33")["evidence_state"] == "effective"


def test_matrix_flags_the_principles(world, clock):
    s, w, g = world
    assert set(row(g, "gdpr:Art.33")["issues"]) == {"no_policy", "no_sop", "no_evidence_source", "no_mapping_owner", "no_review_date"}
    p = g.add("documents", "alice", type="policy", title="P", owner="o")
    sop = g.add("documents", "alice", type="sop", title="S", owner="o")
    src = g.add("evidence_sources", "alice", type="Security events", source="SIEM", frequency="continuous")
    g.link("bot", "alice", "CC-001", policy=[p["id"]], sop=[sop["id"]], evidence_sources=[src["id"]])
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), owner="Dana")
    g.review_mappings("bot", "alice", "CC-001", "Head of SecOps")
    r = row(g, "gdpr:Art.33")
    assert r["issues"] == [] and r["policy"] == [p["id"]] and r["sop"] == [sop["id"]] and r["evidence"] == "Security events" and r["mapping_owner"] == "Head of SecOps"
    clock["now"] = NOW + dt.timedelta(days=400)
    assert row(g, "gdpr:Art.33")["issues"] == ["review_overdue"]
    g.set_setting("alice", "mapping_review_months", "24")
    assert row(g, "gdpr:Art.33")["issues"] == []


def test_not_applicable_requirements_are_left_out_of_the_matrix(world):
    s, w, g = world
    before = len(g.matrix("bot"))
    s.set("bot", s.select("bot", ["gdpr:Art.4"]), applicable=False, justification="Definitions")
    assert len(g.matrix("bot")) == before - 1


def test_matrix_csv_and_summary(world):
    s, w, g = world
    w.gap_accept("bot", "arch", ["gdpr:Art.8"], "=risky, text")
    text = g.matrix_csv("bot")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows[0].keys() >= {"requirement_id", "control_id", "policy", "guideline", "sop", "evidence", "status"}
    gap = next(r for r in rows if r["requirement_id"] == "gdpr:Art.8")
    assert gap["control_id"] == "'GAP: =risky, text" or gap["control_id"].startswith("GAP:")
    summary = g.matrix_summary(g.matrix("bot"))
    assert summary["requirements"] == len(rows) and summary["by_status"]["Gap"] == 1


# ---- coverage ----------------------------------------------------------------------------------------------------------------
def test_coverage_follows_the_stated_method(world):
    s, w, g = world
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), status="implemented")
    s.set("bot", s.select("bot", ["gdpr:Art.34"]), status="implemented")   # implemented but its control has no evidence yet
    feed(w, "CC-001")
    cov = g.coverage("bot")
    by = {f["framework_id"]: f for f in cov["frameworks"]}
    assert cov["anchor"] == "iso-42001"
    assert (by["gdpr"]["required"], by["gdpr"]["mapped"], by["gdpr"]["implemented"], by["gdpr"]["covered"]) == (39, 2, 2, 2)
    assert by["gdpr"]["coverage_pct"] == 5.1 and by["gdpr"]["incremental"] == 2 and by["gdpr"]["incremental_pct"] == 5.1  # CC-001 also serves ISO 42001
    assert by["iso-42001"]["covered"] == 0 and by["iso-42001"]["incremental"] is None
    assert cov["overall"] == {"required": 109, "covered": 2, "coverage_pct": 1.8}


def test_coverage_requires_current_evidence_not_just_a_done_status(world, clock):
    s, w, g = world
    w.cc_set("bot", "owner1", "CC-001", frequency="monthly")
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), status="verified")
    assert g.coverage("bot")["overall"]["covered"] == 0              # no results at all
    feed(w, at="2026-11-08T10:00:00Z")
    assert g.coverage("bot")["overall"]["covered"] == 1
    clock["now"] = NOW + dt.timedelta(days=60)                         # a monthly control with a 60-day-old result is stale
    assert g.coverage("bot")["overall"]["covered"] == 0


def test_coverage_targets_and_a_missing_anchor(world):
    s, w, g = world
    g.set_setting("alice", "coverage_target.gdpr", "70")
    g.set_setting("alice", "anchor_framework", "dora")                 # not in this system's frameworks
    cov = g.coverage("bot")
    gd = next(f for f in cov["frameworks"] if f["framework_id"] == "gdpr")
    assert cov["anchor"] is None and gd["incremental"] is None and gd["target"] == 70 and gd["meets_target"] is False


# ---- KPIs -------------------------------------------------------------------------------------------------------------------------
def kpi(g, kid):
    return next(k for k in g.kpis("bot") if k["id"] == kid)


def test_requirements_mapped_and_current_evidence_kpis(world):
    s, w, g = world
    k = kpi(g, "requirements_mapped")
    assert k["value"] == round(100 * 5 / 109 + 1e-9, 1) and k["status"] == "not_met" and k["target_text"] == "100%"
    assert kpi(g, "controls_current_evidence")["value"] == 0.0 and kpi(g, "controls_current_evidence")["status"] == "not_met"
    feed(w, "CC-001"); feed(w, "CC-002")
    assert kpi(g, "controls_current_evidence")["value"] == 100.0 and kpi(g, "controls_current_evidence")["status"] == "met"


def test_krs_are_no_data_until_their_registers_have_content(world, clock):
    s, w, g = world
    assert kpi(g, "findings_past_due_critical")["status"] == "no_data" and kpi(g, "risks_above_appetite")["status"] == "no_data"
    assert kpi(g, "policy_review_currency")["status"] == "no_data"
    g.add("findings", "a", title="Critical", severity="critical", source="internal", owner="o", raised="2026-09-01", due="2026-10-01")
    g.add("findings", "a", title="Minor", severity="low", source="internal", owner="o", raised="2026-09-01", due="2026-10-01")
    k = kpi(g, "findings_past_due_critical")
    assert k["value"] == 1 and k["status"] == "not_met" and "2 open finding(s) past due" in k["detail"]
    g.update("findings", "a", "FND-001", status="closed")
    assert kpi(g, "findings_past_due_critical")["value"] == 0 and kpi(g, "findings_past_due_critical")["status"] == "met"


def test_risks_above_appetite_need_a_treatment_plan(world):
    s, w, g = world
    g.add("risks", "a", title="Model leak", business_unit="Retail", owner="o", residual="high")          # above 'moderate' appetite, untreated
    g.add("risks", "a", title="Minor", business_unit="Retail", owner="o", residual="medium")               # inside appetite
    g.add("risks", "a", title="Treated", business_unit="Retail", owner="o", residual="critical", treatment_plan="Encrypt")
    g.add("risks", "a", title="Planned", business_unit="Retail", owner="o", residual="high", treatment_status="planned")
    g.add("risks", "a", title="Closed", business_unit="Retail", owner="o", residual="critical", status="closed")
    assert kpi(g, "risks_above_appetite")["value"] == 1
    g.set_setting("alice", "risk_appetite", "high")
    assert kpi(g, "risks_above_appetite")["value"] == 0 and kpi(g, "risks_above_appetite")["status"] == "met"
    g.set_setting("alice", "risk_appetite", "low")
    assert kpi(g, "risks_above_appetite")["value"] == 2


def test_policy_review_currency(world, clock):
    s, w, g = world
    g.add("documents", "a", type="policy", title="P1", owner="o", status="approved")                    # reviewed within the year
    g.add("documents", "a", type="sop", title="S1", owner="o", status="approved", approved="2025-01-01", next_review="2026-01-01")  # overdue
    g.add("documents", "a", type="guideline", title="G1", owner="o")                                      # draft: not counted
    k = kpi(g, "policy_review_currency")
    assert k["value"] == 50.0 and k["status"] == "not_met"
    clock["now"] = NOW + dt.timedelta(days=400)
    assert kpi(g, "policy_review_currency")["value"] == 0.0


def test_cross_framework_coverage_is_informational(world):
    s, w, g = world
    k = kpi(g, "cross_framework_coverage")
    assert k["status"] == "info" and k["value"] == 0.0


# ---- lifecycle and artifacts ---------------------------------------------------------------------------------------------------------
def step(g, n):
    return next(x for x in g.lifecycle("bot") if x["n"] == n)


def test_lifecycle_steps_follow_the_data(world, clock):
    s, w, g = world
    assert [x["done"] for x in g.lifecycle("bot")] == [False, False, True, False, False, False, False, False, False, False]
    g.add("scope_items", "a", kind="regulation", name="DORA")
    assert step(g, 1)["done"]
    g.add("scope_items", "a", kind="business_unit", name="Retail")
    g.add("scope_items", "a", kind="ai_system", name="Support bot")
    assert not step(g, 2)["done"]                       # not yet reviewed
    g.review_scope("a")
    assert step(g, 2)["done"]
    clock["now"] = NOW + dt.timedelta(days=400)
    assert not step(g, 2)["done"]                       # scope review is older than a year
    clock["now"] = NOW
    g.add("audits", "a", title="Internal audit", kind="internal", planned="2026-10-01", completed="2026-10-20")
    assert step(g, 8)["done"] and not step(g, 10)["done"]
    g.add("audits", "a", title="Management review", kind="management_review", planned="2026-10-25", completed="2026-10-26")
    assert step(g, 10)["done"]
    g.add("findings", "a", title="Late", severity="low", source="internal", owner="o", raised="2026-09-01", due="2026-10-01")
    assert not step(g, 10)["done"]                       # an overdue finding is still open
    assert not step(g, 9)["done"]
    g.report_markdown("bot", "a")
    assert step(g, 9)["done"]


def test_mapping_step_needs_policy_and_sop_on_every_used_control(world):
    s, w, g = world
    for cid in [r["requirement_id"] for r in g.matrix("bot") if not r["control_id"]]:
        w.gap_accept("bot", "arch", [cid], "Deliberately unmapped")
    assert not step(g, 4)["done"] and "lack a policy or SOP" in step(g, 4)["detail"]
    p = g.add("documents", "a", type="policy", title="P", owner="o")
    sop = g.add("documents", "a", type="sop", title="S", owner="o")
    for cc in ("CC-001", "CC-002"):
        g.link("bot", "a", cc, policy=[p["id"]], sop=[sop["id"]])
    assert step(g, 4)["done"]


def test_artifacts_checklist(world):
    s, w, g = world
    art = lambda i: next(x for x in g.artifacts("bot") if x["id"] == i)  # noqa: E731
    assert art("requirements")["status"] == "ready" and art("controls")["status"] == "ready"
    assert art("matrix")["status"] == "partial" and art("library")["status"] == "missing" and art("risks")["status"] == "missing"
    g.add("documents", "a", type="policy", title="P", owner="o")
    assert art("library")["status"] == "partial"
    for t in ("guideline", "sop"):
        g.add("documents", "a", type=t, title=t, owner="o")
    assert art("library")["status"] == "ready"
    assert art("scopes")["status"] == "missing"
    g.set_scope_statement("a", "gdpr", "EU data")
    assert art("scopes")["status"] == "partial"
    g.set_scope_statement("a", "iso-42001", "AI systems")
    assert art("scopes")["status"] == "ready"
    g.add("evidence_sources", "a", type="Logs", source="SIEM", frequency="continuous")
    assert art("evidence")["status"] == "partial"
    feed(w)
    assert art("evidence")["status"] == "ready"


# ---- streams / report / hygiene ----------------------------------------------------------------------------------------------------------------
def test_streams_report_their_own_numbers(world):
    s, w, g = world
    leadership = next(x for x in g.streams("bot") if x["id"] == "leadership")
    policy = next(x for x in g.streams("bot") if x["id"] == "policy")
    assert policy["mapped"] == 2 and policy["requirements"] == 6                     # A.2.2 and A.2.3 are mapped to CC-002
    assert leadership["mapped"] == 0


def test_report_markdown_and_marker(world):
    s, w, g = world
    md = g.report_markdown("bot", "alice")
    assert md.startswith("# GRC report: Bot") and "## KPIs and KRIs" in md and "## Coverage by framework" in md and "ISO/IEC 42001 streams" in md
    assert "not an attestation of compliance" in md
    assert s.data["grc"]["markers"]["report_at"] and s.data["audit"][-1]["action"] == "GRC_REPORT_GENERATED"
    assert g.report("bot")["matrix"]["requirements"] == 109


def test_reading_never_changes_the_scope_file(lib, clock):
    s = Scope.new("Org", lib)
    s.add_system("bot", "Bot", ["iso-42001", "gdpr"])
    before = json.dumps(s.data, sort_keys=True)
    g = Grc(s)
    for call in (g.matrix, g.coverage, g.kpis, g.lifecycle, g.artifacts, g.streams, g.report):
        call("bot")
    g.matrix_csv("bot"); g.roles(); g.settings(); g.records("risks")
    assert json.dumps(s.data, sort_keys=True) == before


def test_without_the_workflow_every_requirement_is_unmapped(lib, clock):
    s = Scope.new("Org", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    g = Grc(s)
    assert {r["status"] for r in g.matrix("bot")} == {"Unmapped"} and kpi_value(g, "requirements_mapped") == 0.0


def kpi_value(g, kid):
    return next(k for k in g.kpis("bot") if k["id"] == kid)["value"]


def test_validation_catches_corrupted_grc_data(world):
    s, w, g = world
    p = g.add("documents", "a", type="policy", title="P", owner="o")
    g.link("bot", "a", "CC-001", policy=[p["id"]])
    assert s.validate() == ([], [])
    s.data["grc"]["documents"]["DOC-001"]["type"] = "memo"
    s.data["grc"]["risks"]["RSK-009"] = {"id": "RSK-009", "title": "x"}
    s.data["workflow"]["bot"]["common_controls"]["CC-001"]["documents"]["sop"] = ["DOC-404"]
    s.data["grc"]["framework_scopes"]["nope"] = {"statement": "x", "reviewed": "2026-01-01"}
    s.data["grc"]["roles"]["wizard"] = ["x"]
    text = "\n".join(s.validate()[0])
    assert "Type must be one of" in text and "grc/risks/RSK-009" in text and "unknown document 'DOC-404'" in text
    assert "unknown framework 'nope'" in text and "unknown role 'wizard'" in text


def test_file_round_trip_and_schema(world, tmp_path):
    s, w, g = world
    g.seed_evidence_sources("a")
    g.add("risks", "a", title="r", business_unit="BU", owner="o", residual="low")
    g.set_scope_statement("a", "gdpr", "EU")
    g.set_roles("a", "internal_audit", ["Fay"])
    g.review_scope("a")
    p = tmp_path / "scope.json"
    s.save(p)
    again = Scope.load(p, s.lib)
    assert again.validate() == ([], []) and Grc(again).roles()[-1]["people"] == ["Fay"]
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schema" / "scope.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(json.loads(p.read_text()))


# ---- CLI ------------------------------------------------------------------------------------------------------------------------------------------
def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_scenario(capsys, tmp_path, clock):
    f = str(tmp_path / "scope.json")
    r = lambda *a: run(capsys, *a, "--file", f)  # noqa: E731
    assert r("scope", "init", "--org", "T")[0] == 0 and r("scope", "add-system", "bot", "--frameworks", "iso-42001,gdpr")[0] == 0
    assert r("workflow", "init", "--by", "alice")[0] == 0
    assert r("workflow", "cc", "add", "Incident response", "--by", "arch")[0] == 0
    assert r("workflow", "cc", "map", "CC-001", "gdpr:Art.33", "iso-42001:A.8.4", "--by", "arch")[0] == 0
    code, out, _ = r("grc", "init", "--by", "alice")
    assert code == 0 and "5 evidence source(s)" in out
    assert r("grc", "documents", "add", "--type", "policy", "--title", "AI policy", "--owner", "CISO", "--status", "approved", "--by", "alice")[0] == 0
    assert r("grc", "documents", "add", "--type", "sop", "--title", "IR SOP", "--owner", "SecOps", "--by", "alice")[0] == 0
    with pytest.raises(SystemExit):                      # argparse rejects a bad choice before any code runs
        r("grc", "documents", "add", "--type", "memo", "--title", "x", "--owner", "o", "--by", "alice")
    capsys.readouterr()
    code, _, err = r("grc", "documents", "add", "--title", "x", "--by", "alice")
    assert code == 2 and "required" in err
    code, out, _ = r("grc", "documents", "list")
    assert code == 0 and "DOC-001" in out and "DOC-002" in out
    assert r("grc", "documents", "set", "DOC-002", "--status", "approved", "--by", "alice")[0] == 0
    assert r("grc", "link", "CC-001", "--policy", "DOC-001", "--sop", "DOC-002", "--evidence-source", "EVS-003", "--by", "alice")[0] == 0
    code, _, err = r("grc", "link", "CC-001", "--sop", "DOC-001", "--by", "alice")
    assert code == 2 and "not a sop" in err
    assert r("grc", "mapping-review", "CC-001", "--owner", "Head of SecOps", "--by", "alice")[0] == 0
    code, out, _ = r("grc", "matrix", "-n", "5")
    assert code == 0 and "requirements:" in out and "Not started" in out
    code, out, _ = r("grc", "matrix", "--format", "csv")
    assert code == 0 and out.startswith("requirement_id,framework") and "IR SOP" not in out and "DOC-002" in out
    for cmd in ("coverage", "kpis", "streams", "lifecycle", "artifacts"):
        assert r("grc", cmd)[0] == 0, cmd
    code, out, _ = r("grc", "kpis", "--json")
    assert json.loads(out)[0]["id"] == "requirements_mapped"
    assert r("grc", "settings", "risk_appetite=low", "--by", "alice")[0] == 0
    assert r("grc", "settings", "bogus=1", "--by", "alice")[0] == 2
    assert r("grc", "roles", "internal_audit", "--name", "Fay", "--by", "alice")[0] == 0
    assert "Fay" in r("grc", "roles")[1]
    assert r("grc", "scope-statement", "gdpr", "--statement", "EU data", "--by", "alice")[0] == 0
    assert r("grc", "scope-review", "--by", "alice")[0] == 0
    rep = tmp_path / "grc.md"
    assert r("grc", "report", "-o", str(rep), "--by", "alice")[0] == 0 and rep.read_text().startswith("# GRC report")
    assert "unconfirmed" in r("grc", "open-items")[1]
    assert r("grc", "documents", "remove", "DOC-001", "--by", "alice")[0] == 0
    assert r("scope", "validate")[0] == 0
    assert r("workflow", "audit", "verify", "--by", "auditor")[0] == 0
