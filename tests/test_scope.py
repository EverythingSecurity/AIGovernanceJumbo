# SPDX-License-Identifier: Apache-2.0
import csv
import io
import json
from pathlib import Path

import pytest

import aicontrols
from aicontrols.cli import main
from aicontrols.scope import Scope, ScopeError

ROOT = Path(__file__).resolve().parent.parent
FRAMEWORKS = ["iso-27001", "gdpr"]


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


@pytest.fixture
def scope(lib):
    s = Scope.new("Test Org", lib)
    s.add_system("bot", "Bot", FRAMEWORKS)
    return s


def pick(scope, ids):
    return scope.select("bot", ids)


def test_baseline_scope_is_real_controls_of_chosen_frameworks(scope, lib):
    ids = {c.framework_id for c in scope.in_scope("bot")}
    assert ids == set(FRAMEWORKS)
    assert len(scope.in_scope("bot")) == len(lib.filter(framework="iso-27001")) + len(lib.filter(framework="gdpr"))


def test_add_system_rejects_duplicates_bad_ids_and_unknown_frameworks(scope):
    with pytest.raises(ScopeError):
        scope.add_system("bot", "x", ["gdpr"])
    with pytest.raises(ScopeError):
        scope.add_system("bad id!", "x", ["gdpr"])
    with pytest.raises(ScopeError):
        scope.add_system("other", "x", ["nope"])
    with pytest.raises(ScopeError):
        scope.add_system("other", "x", [])


def test_defaults_are_applicable_and_not_started(scope):
    d = scope.decision("bot", "gdpr:Art.33")
    assert d["applicable"] is True and d["status"] == "not_started"


def test_not_applicable_requires_justification(scope):
    with pytest.raises(ScopeError, match="justification"):
        scope.set("bot", pick(scope, ["gdpr:Art.33"]), applicable=False)
    scope.set("bot", pick(scope, ["gdpr:Art.33"]), applicable=False, justification="Out of scope: reason")
    assert scope.decision("bot", "gdpr:Art.33")["applicable"] is False


def test_cannot_select_controls_outside_the_systems_frameworks(scope):
    with pytest.raises(ScopeError, match="not in scope"):
        pick(scope, ["eu-ai-act:Art.5"])
    with pytest.raises(ScopeError, match="unknown control"):
        pick(scope, ["nope:1"])
    with pytest.raises(ScopeError, match="nothing selected"):
        scope.select("bot", [])


def test_status_and_date_validation(scope):
    c = pick(scope, ["gdpr:Art.33"])
    with pytest.raises(ScopeError, match="status"):
        scope.set("bot", c, status="finished")
    with pytest.raises(ScopeError, match="date"):
        scope.set("bot", c, due="31/12/2026")


def test_evidence_is_appended_without_duplicates(scope):
    c = pick(scope, ["gdpr:Art.33"])
    scope.set("bot", c, evidence=["a", "b"])
    scope.set("bot", c, evidence=["b", "c"])
    assert scope.decision("bot", "gdpr:Art.33")["evidence"] == ["a", "b", "c"]


def test_domain_selector_hits_every_control_in_that_domain(scope):
    chosen = scope.select("bot", domain="incident")
    assert len(chosen) > 3 and {c.domain_id for c in chosen} == {"incident-management-breach-notification"}
    scope.set("bot", chosen, owner="SecOps")
    assert all(scope.decision("bot", c.id)["owner"] == "SecOps" for c in chosen)


def test_percent_complete_counts_implemented_and_verified_of_applicable(scope):
    ids = [c.id for c in scope.in_scope("bot")]
    scope.set("bot", pick(scope, ids[:2]), status="implemented")
    scope.set("bot", pick(scope, ids[2:3]), status="verified")
    scope.set("bot", pick(scope, ids[3:4]), status="in_progress")
    scope.set("bot", pick(scope, ids[4:5]), applicable=False, justification="n/a")
    t = scope.overall("bot")
    assert t["applicable"] == len(ids) - 1 and t["not_applicable"] == 1
    assert t["implemented"] == 2 and t["verified"] == 1 and t["in_progress"] == 1
    assert t["percent"] == round(100 * 3 / (len(ids) - 1), 1)


def test_marking_done_never_auto_completes_related_controls(scope):
    c = scope.lib.get("iso-27001:A.5.24")
    before = {x.id: scope.decision("bot", x.id)["status"] for x in scope.in_scope("bot")}
    scope.set("bot", [c], status="implemented")
    after = {x.id: scope.decision("bot", x.id)["status"] for x in scope.in_scope("bot")}
    changed = [k for k in before if before[k] != after[k]]
    assert changed == ["iso-27001:A.5.24"]
    related = scope.related_open("bot", c)
    assert related and all(r.framework_id == "gdpr" for r in related)  # related() spans other frameworks


def test_plan_is_one_workstream_per_domain_most_shared_first(scope):
    plan = scope.plan("bot")
    assert len({p["domain_id"] for p in plan}) == len(plan)
    assert [p["frameworks"] for p in plan] == sorted((p["frameworks"] for p in plan), reverse=True)


def test_validate_flags_corruption(scope):
    scope.set("bot", pick(scope, ["gdpr:Art.33"]), status="in_progress")
    assert scope.validate() == ([], [])
    scope.data["decisions"]["bot"]["gdpr:Art.33"]["status"] = "bogus"
    scope.data["decisions"]["bot"]["gdpr:Art.34"] = {"applicable": False}
    scope.data["decisions"]["bot"]["eu-ai-act:Art.5"] = {}
    scope.data["decisions"]["ghost"] = {}
    errors, _ = scope.validate()
    text = "\n".join(errors)
    assert "invalid status" in text and "without a justification" in text
    assert "framework is not selected" in text and "unknown system" in text


def test_validate_warns_when_dataset_version_differs(scope):
    scope.data["dataset_version"] = "0.0.1"
    errors, warnings = scope.validate()
    assert not errors and any("dataset" in w for w in warnings)


def test_save_load_round_trip(scope, tmp_path):
    scope.set("bot", pick(scope, ["gdpr:Art.33"]), owner="DPO", status="in_progress")
    p = tmp_path / "s.json"
    scope.save(p)
    again = Scope.load(p, scope.lib)
    assert again.decision("bot", "gdpr:Art.33")["owner"] == "DPO"
    with pytest.raises(ScopeError, match="no scope file"):
        Scope.load(tmp_path / "missing.json", scope.lib)


def test_soa_export_has_one_row_per_in_scope_control(scope):
    scope.set("bot", pick(scope, ["gdpr:Art.33"]), applicable=False, justification="why")
    out = io.StringIO()
    n = scope.write_soa("bot", out)
    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert n == len(rows) == len(scope.in_scope("bot"))
    row = next(r for r in rows if r["control_id"] == "gdpr:Art.33")
    assert row["applicable"] == "no" and row["justification"] == "why"


def test_example_scope_file_is_valid_against_schema_and_loader(lib):
    jsonschema = pytest.importorskip("jsonschema")
    data = json.loads((ROOT / "examples" / "chatbot-scope.json").read_text())
    schema = json.loads((ROOT / "schema" / "scope.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(data)
    errors, _ = Scope(data, lib).validate()
    assert errors == []


def test_schema_rejects_not_applicable_without_justification():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schema" / "scope.schema.json").read_text())
    bad = {"schema_version": "1.0", "dataset_version": "0.1.0", "organization": "x", "systems": [],
           "decisions": {"s": {"gdpr:Art.33": {"applicable": False}}}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(bad)


# ---- CLI ----------------------------------------------------------------
def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_workflow(capsys, tmp_path):
    f = str(tmp_path / "scope.json")
    assert run(capsys, "scope", "init", "--org", "T", "--file", f)[0] == 0
    code, _, err = run(capsys, "scope", "init", "--org", "T", "--file", f)
    assert code == 2 and "already exists" in err
    assert run(capsys, "scope", "add-system", "bot", "--frameworks", "gdpr,iso-27001", "--file", f)[0] == 0
    code, out, _ = run(capsys, "scope", "set", "iso-27001:A.5.24", "--status", "implemented", "--file", f)
    assert code == 0 and "NOT updated automatically" in out
    code, _, err = run(capsys, "scope", "set", "gdpr:Art.33", "--applicable", "no", "--file", f)
    assert code == 2 and "justification" in err
    code, out, _ = run(capsys, "scope", "status", "--file", f)
    assert code == 0 and "OVERALL" in out and "GDPR" in out
    code, out, _ = run(capsys, "scope", "plan", "--file", f)
    assert code == 0 and "workstreams" in out
    code, out, _ = run(capsys, "scope", "export", "--file", f)
    assert code == 0 and out.startswith("system,control_id")
    assert run(capsys, "scope", "validate", "--file", f)[0] == 0


def test_cli_requires_system_when_ambiguous(capsys, tmp_path):
    f = str(tmp_path / "scope.json")
    run(capsys, "scope", "init", "--org", "T", "--file", f)
    run(capsys, "scope", "add-system", "a", "--frameworks", "gdpr", "--file", f)
    run(capsys, "scope", "add-system", "b", "--frameworks", "gdpr", "--file", f)
    code, _, err = run(capsys, "scope", "status", "--file", f)
    assert code == 2 and "choose one" in err
