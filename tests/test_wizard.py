# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path

import pytest

import aicontrols
from aicontrols import cli_scope
from aicontrols.cli import main
from aicontrols.wizard import QUESTION_IDS, WizardError, normalize, recommend, selection

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


def level(recs, fid):
    return next(r for r in recs if r.framework_id == fid).level


def test_unanswered_questions_default_to_unsure():
    full = normalize({})
    assert set(full) == set(QUESTION_IDS) and set(full.values()) == {"unsure"}


def test_normalize_accepts_shorthand_and_rejects_bad_input():
    assert normalize({"eu": "Y", "role": "d"})["eu"] == "yes"
    assert normalize({"role": "d"})["role"] == "deployer"
    with pytest.raises(WizardError, match="unknown question"):
        normalize({"colour": "blue"})
    with pytest.raises(WizardError, match="not one of"):
        normalize({"eu": "maybe"})


def test_every_framework_gets_exactly_one_recommendation(lib):
    recs = recommend({}, lib)
    assert sorted(r.framework_id for r in recs) == sorted(lib.frameworks)


def test_recommend_is_deterministic(lib):
    a = {"eu": "yes", "personal_data": "yes", "genai": "yes"}
    assert [r.to_dict() for r in recommend(a, lib)] == [r.to_dict() for r in recommend(dict(a), lib)]


def test_eu_exposure_drives_ai_act_and_gdpr(lib):
    yes = recommend({"eu": "yes", "personal_data": "yes"}, lib)
    assert level(yes, "eu-ai-act") == "recommended" and level(yes, "gdpr") == "recommended"
    no = recommend({"eu": "no", "personal_data": "no"}, lib)
    assert level(no, "eu-ai-act") == "not_indicated" and level(no, "gdpr") == "not_indicated"
    unsure = recommend({}, lib)
    assert level(unsure, "eu-ai-act") == "consider" and level(unsure, "gdpr") == "consider"


def test_personal_data_without_eu_link_is_consider_not_ruled_out(lib):
    recs = recommend({"eu": "no", "personal_data": "yes"}, lib)
    assert level(recs, "gdpr") == "consider"


def test_dora_only_for_financial_entities(lib):
    assert level(recommend({"financial": "yes"}, lib), "dora") == "recommended"
    assert level(recommend({"financial": "no"}, lib), "dora") == "not_indicated"
    assert level(recommend({}, lib), "dora") == "consider"


def test_certification_goal_makes_iso_standards_recommended(lib):
    assert level(recommend({"certification": "iso42001"}, lib), "iso-42001") == "recommended"
    both = recommend({"certification": "both"}, lib)
    assert level(both, "iso-42001") == level(both, "iso-27001") == "recommended"
    assert level(recommend({"isms": "yes"}, lib), "iso-27001") == "recommended"


def test_genai_and_threat_frameworks(lib):
    recs = recommend({"genai": "yes", "adversarial_testing": "yes"}, lib)
    assert level(recs, "owasp-llm") == "recommended"
    assert {level(recs, f) for f in ("mitre-atlas", "iso-27090", "nist-aria")} == {"consider"}
    assert level(recommend({"genai": "no"}, lib), "owasp-llm") == "not_indicated"


def test_role_changes_the_ai_act_reasoning(lib):
    provider = next(r for r in recommend({"eu": "yes", "role": "provider"}, lib) if r.framework_id == "eu-ai-act")
    deployer = next(r for r in recommend({"eu": "yes", "role": "deployer"}, lib) if r.framework_id == "eu-ai-act")
    assert any("provider" in x for x in provider.reasons) and any("deployer" in x for x in deployer.reasons)


def test_regulations_carry_the_counsel_caveat_and_standards_do_not(lib):
    recs = recommend({"eu": "yes", "personal_data": "yes", "certification": "iso42001"}, lib)
    assert next(r for r in recs if r.framework_id == "eu-ai-act").caveat
    assert next(r for r in recs if r.framework_id == "iso-42001").caveat is None
    assert all(r.reasons for r in recs)  # no suggestion without a stated reason


def test_selection_tiers(lib):
    recs = recommend({"eu": "yes", "personal_data": "yes", "genai": "yes", "certification": "iso42001"}, lib)
    rec_only = selection(recs)
    both = selection(recs, "consider")
    assert set(rec_only) < set(both)
    assert all(level(recs, f) == "recommended" for f in rec_only)


# ---- CLI ----------------------------------------------------------------
def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_prints_recommendations_from_answers_file(capsys):
    code, out, _ = run(capsys, "scope", "wizard", "--answers", str(ROOT / "examples" / "wizard-answers.json"))
    assert code == 0 and "YOUR ANSWERS POINT TO THESE" in out and "EU AI Act" in out
    assert "not legal advice" in out and "confirm with qualified counsel" in out
    assert "aicontrols scope wizard" in out  # tells you how to create the system


def test_cli_single_answers_and_unanswered_note(capsys):
    code, out, _ = run(capsys, "scope", "wizard", "--answer", "eu=yes", "--answer", "genai=yes")
    assert code == 0 and "Not answered (treated as unsure)" in out


def test_cli_json_output(capsys):
    code, out, _ = run(capsys, "scope", "wizard", "--answer", "eu=yes", "--json")
    data = json.loads(out)
    assert code == 0 and data["answers"]["eu"] == "yes" and "eu-ai-act" in data["selected"]


def test_cli_bad_answers(capsys):
    assert run(capsys, "scope", "wizard", "--answer", "eu=maybe")[0] == 2
    assert run(capsys, "scope", "wizard", "--answer", "nonsense")[0] == 2
    code, _, err = run(capsys, "scope", "wizard", "--answers", "/no/such/file.json")
    assert code == 2 and "cannot read" in err


def test_cli_requires_answers_when_not_interactive(capsys, monkeypatch):
    monkeypatch.setattr(cli_scope, "_is_tty", lambda: False)
    code, _, err = run(capsys, "scope", "wizard")
    assert code == 2 and "not interactive" in err


def test_cli_create_records_the_scoping_basis_and_validates(capsys, tmp_path):
    f = str(tmp_path / "scope.json")
    run(capsys, "scope", "init", "--org", "T", "--file", f)
    code, out, _ = run(capsys, "scope", "wizard", "--answers", str(ROOT / "examples" / "wizard-answers.json"),
                       "--create", "bot", "--name", "Bot", "--file", f)
    assert code == 0 and "added system bot" in out
    system = json.loads(Path(f).read_text())["systems"][0]
    assert system["frameworks"] == ["eu-ai-act", "gdpr", "iso-27001", "iso-42001", "owasp-llm"]
    assert system["scoping"]["answers"]["eu"] == "yes" and system["scoping"]["include_level"] == "recommended"
    assert run(capsys, "scope", "validate", "--file", f)[0] == 0
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schema" / "scope.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(json.loads(Path(f).read_text()))


def test_cli_create_can_include_consider_tier(capsys, tmp_path):
    f = str(tmp_path / "scope.json")
    run(capsys, "scope", "init", "--org", "T", "--file", f)
    run(capsys, "scope", "wizard", "--answers", str(ROOT / "examples" / "wizard-answers.json"),
        "--create", "bot", "--include", "consider", "--file", f)
    fw = json.loads(Path(f).read_text())["systems"][0]["frameworks"]
    assert "nist-ai-rmf" in fw and "dora" not in fw


def test_cli_create_requires_an_existing_scope_file(capsys, tmp_path):
    code, _, err = run(capsys, "scope", "wizard", "--answer", "eu=yes", "--create", "bot",
                       "--file", str(tmp_path / "missing.json"))
    assert code == 2 and "no scope file" in err


def test_cli_interactive_flow(capsys, tmp_path, monkeypatch):
    f = str(tmp_path / "scope.json")
    run(capsys, "scope", "init", "--org", "T", "--file", f)
    monkeypatch.setattr(cli_scope, "_is_tty", lambda: True)
    replies = iter(["?", "d", "y", "y", "n", "y", "n", "n", "iso42001", "", "n", "n", "n",   # 12 answers (+ help)
                    "y", "chat", "Chat", "n"])                                               # create system
    monkeypatch.setattr("builtins.input", lambda *_: next(replies))
    code, out, _ = run(capsys, "scope", "wizard", "--file", f)
    assert code == 0 and "added system chat" in out
    system = json.loads(Path(f).read_text())["systems"][0]
    assert system["scoping"]["answers"]["role"] == "deployer"
    assert system["scoping"]["answers"]["isms"] == "unsure"  # blank answer
