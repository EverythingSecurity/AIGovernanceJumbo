# SPDX-License-Identifier: Apache-2.0
"""Spreadsheet template and import: behaviour, CLI, and agreement with the browser implementation."""
import copy
import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import aicontrols
from aicontrols import spreadsheet as sp
from aicontrols.cli import main
from aicontrols.scope import Scope, ScopeError

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


def sheet(lib, edits=None, frameworks=("gdpr",), system="bot", name="Support bot", org="Acme", scope=None):
    """A template with cells filled in: edits is {control_id: {column: value}}."""
    rows = sp.parse_csv(sp.template_csv(lib, list(frameworks), org, system, name, scope))
    head = [r for r in rows if r[0].startswith("#")]
    data = [r for r in rows if not r[0].startswith("#")]
    ix = {c: i for i, c in enumerate(data[0])}
    for cid, cells in (edits or {}).items():
        row = next(r for r in data[1:] if r[ix["control_id"]] == cid)
        for k, v in cells.items():
            row[ix[k]] = v
    return "\r\n".join([sp.csv_line(h) for h in head] + [sp.csv_line(r) for r in data]) + "\r\n"


def new_scope(lib):
    return Scope.new("", lib)


# ---- parser ---------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("a,b\r\n1,2\r\n", [["a", "b"], ["1", "2"]]),
    ("a,b\n1,2", [["a", "b"], ["1", "2"]]),
    ('a,"b,c",d\n"x""y",2,3\n', [["a", "b,c", "d"], ['x"y', "2", "3"]]),
    ('a,b\n"line1\nline2",2\n', [["a", "b"], ["line1\nline2", "2"]]),
    ("﻿a;b;c\n1;2;3\n", [["a", "b", "c"], ["1", "2", "3"]]),
    ("a,b\n\n,\n1,2\n", [["a", "b"], ["1", "2"]]),
    ('"# note, with comma"\na,b\n', [["# note, with comma"], ["a", "b"]]),
    ("a,b\r1,2\r", [["a", "b"], ["1", "2"]]),
    ("", []),
])
def test_csv_parser(text, expected):
    assert sp.parse_csv(text) == expected


def test_delimiter_detection_ignores_quoted_separators_and_comments():
    assert sp.detect_delimiter('# a;b;c\nx;y;"1,2,3"\n') == ";"
    assert sp.detect_delimiter('"# a;b;c"\nx,y,"1;2;3"\n') == ","


def test_cells_are_neutralised_on_write_and_restored_on_read():
    assert sp.csv_cell("=SUM(1)") == "'=SUM(1)" and sp.unsafe("'=SUM(1)") == "=SUM(1)"
    assert sp.unsafe("'normal") == "'normal" and sp.unsafe("plain") == "plain"


# ---- template ----------------------------------------------------------------------------------
def test_template_lists_controls_with_blank_decision_columns(lib):
    text = sp.template_csv(lib, ["gdpr", "eu-ai-act"], "Acme", "bot", "Bot")
    rows = sp.parse_csv(text)
    comments = [r for r in rows if r[0].startswith("#")]
    data = [r for r in rows if not r[0].startswith("#")]
    assert len(comments) == 5 and "organisation: Acme" in comments[1][0] and "system-name: Bot" in comments[2][0]
    assert data[0] == ["system", "control_id", "framework_id", "ref", "title", "domain", "c", "i", "a", "applicable", "justification",
                       "status", "owner", "due", "reviewed", "updated", "evidence", "notes"]
    assert len(data) - 1 == len(lib.filter(framework="gdpr")) + len(lib.filter(framework="eu-ai-act"))
    row = dict(zip(data[0], data[1]))
    assert row["system"] == "bot" and row["applicable"] == "yes" and row["status"] == "not_started" and row["owner"] == ""


def test_template_validates_input(lib):
    with pytest.raises(ScopeError):
        sp.template_csv(lib, [], "A", "bot", "Bot")
    with pytest.raises(ScopeError):
        sp.template_csv(lib, ["nope"], "A", "bot", "Bot")
    with pytest.raises(ScopeError, match="system id"):
        sp.template_csv(lib, ["gdpr"], "A", "bad id!", "Bot")


def test_template_prefills_current_decisions_for_a_known_system(lib):
    s = Scope.new("Acme", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), status="implemented", owner="Dana", evidence=["IR plan"])
    rows = sp.parse_csv(sp.template_csv(lib, ["gdpr"], "Acme", "bot", "Bot", s))
    data = [r for r in rows if not r[0].startswith("#")]
    row = dict(zip(data[0], next(r for r in data if r[1] == "gdpr:Art.33")))
    assert row["status"] == "implemented" and row["owner"] == "Dana" and row["evidence"] == "IR plan"


# ---- import -------------------------------------------------------------------------------------------
def test_untouched_template_creates_the_system_and_changes_nothing(lib):
    s = new_scope(lib)
    r = sp.import_decisions(s, sheet(lib))
    assert r["errors"] == [] and r["created_system"] and r["applied"] == 0 and r["skipped"] == 39
    assert s.data["organization"] == "Acme" and s.data["systems"][0]["name"] == "Support bot"
    assert s.data["systems"][0]["frameworks"] == ["gdpr"] and s.data["decisions"] == {}


def test_filled_template_applies_decisions(lib):
    s = new_scope(lib)
    r = sp.import_decisions(s, sheet(lib, {
        "gdpr:Art.33": {"status": "In progress", "owner": "Dana", "due": "2026-12-31", "evidence": "IR plan; runbook", "notes": "draft"},
        "gdpr:Art.4": {"applicable": "No", "justification": "Definitions only"},
        "gdpr:Art.34": {"status": "implemented", "applicable": "y"}}))
    assert r["errors"] == [] and r["applied"] == 3
    d = s.data["decisions"]["bot"]
    assert d["gdpr:Art.33"]["status"] == "in_progress" and d["gdpr:Art.33"]["evidence"] == ["IR plan", "runbook"]
    assert d["gdpr:Art.4"]["applicable"] is False and d["gdpr:Art.34"]["status"] == "implemented"
    assert s.validate() == ([], [])


def test_import_is_all_or_nothing_and_reports_every_problem_with_its_row(lib):
    s = new_scope(lib)
    before = copy.deepcopy(s.data)
    text = sheet(lib, {"gdpr:Art.33": {"status": "finished"}, "gdpr:Art.34": {"due": "31/12/2026"},
                       "gdpr:Art.4": {"applicable": "no"}, "gdpr:Art.5(1)": {"applicable": "maybe"}})
    r = sp.import_decisions(s, text)
    msgs = "\n".join(f"{e['row']}: {e['message']}" for e in r["errors"])
    assert len(r["errors"]) == 4 and r["applied"] == 0
    assert "status must be one of" in msgs and "must be a date like 2026-12-31" in msgs
    assert "not applicable needs a justification" in msgs and "applicable must be yes or no" in msgs
    assert all(e["row"] >= 2 for e in r["errors"]) and s.data == before


def test_unknown_controls_missing_columns_and_system_problems(lib):
    s = new_scope(lib)
    assert sp.import_decisions(s, "")["errors"][0]["message"] == "the file has no header row"
    assert "no control_id column" in sp.import_decisions(s, "a,b\n1,2\n")["errors"][0]["message"]
    r = sp.import_decisions(s, "control_id,status\nnope:1,implemented\ngdpr:Art.33,verified\n")
    assert "cannot tell which system" in r["errors"][0]["message"]
    r = sp.import_decisions(s, "system,control_id\na,gdpr:Art.33\nb,gdpr:Art.34\n")
    assert "mixes several systems" in r["errors"][0]["message"]
    r = sp.import_decisions(s, "system,control_id\nbot,nope:1\n")
    assert r["errors"][0] == {"row": 2, "message": "unknown control id 'nope:1'"}
    r = sp.import_decisions(s, "system,control_id\nbot,iso-5181:ID\n")
    assert "is not a control" in r["errors"][0]["message"]


def test_importing_into_an_existing_system_respects_its_frameworks(lib):
    s = Scope.new("Acme", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    r = sp.import_decisions(s, "system,control_id,status\nbot,eu-ai-act:Art.5,implemented\n")
    assert "framework is not selected" in r["errors"][0]["message"]
    r = sp.import_decisions(s, "control_id,status\ngdpr:Art.33,implemented\n")  # a single system: no system column needed
    assert r["errors"] == [] and s.decision("bot", "gdpr:Art.33")["status"] == "implemented"


def test_defaults_on_untouched_rows_do_not_create_records_but_do_update_existing_ones(lib):
    s = Scope.new("Acme", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), status="implemented")
    r = sp.import_decisions(s, "control_id,applicable,status\ngdpr:Art.33,yes,not_started\ngdpr:Art.34,yes,not_started\n")
    assert r["applied"] == 1 and r["skipped"] == 1
    assert s.decision("bot", "gdpr:Art.33")["status"] == "not_started" and "gdpr:Art.34" not in s.data["decisions"]["bot"]


def test_blank_cells_leave_values_unchanged_and_evidence_is_replaced(lib):
    s = Scope.new("Acme", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), status="in_progress", owner="Dana", evidence=["old"])
    sp.import_decisions(s, "control_id,owner,evidence,notes\ngdpr:Art.33,,new1; new2,hello\n")
    d = s.decision("bot", "gdpr:Art.33")
    assert d["owner"] == "Dana" and d["status"] == "in_progress" and d["evidence"] == ["new1", "new2"] and d["notes"] == "hello"


def test_duplicate_rows_warn_and_the_last_wins(lib):
    s = Scope.new("Acme", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    r = sp.import_decisions(s, "control_id,status\ngdpr:Art.33,in_progress\ngdpr:Art.33,verified\n")
    assert r["warnings"] and "last row wins" in r["warnings"][0] and s.decision("bot", "gdpr:Art.33")["status"] == "verified"


def test_header_aliases_semicolons_bom_and_quoted_multiline_cells(lib):
    s = Scope.new("Acme", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    text = '﻿"Control ID";"Applicable (SoA)";Status;"Notes / Gap"\r\ngdpr:Art.33;yes;"In Progress";"line one\nline two"\r\n'
    r = sp.import_decisions(s, text)
    assert r["errors"] == [] and s.decision("bot", "gdpr:Art.33")["notes"] == "line one\nline two"


def test_an_exported_soa_round_trips(lib):
    s = Scope.new("Acme", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), status="verified", owner="=SUM(1)", notes="-dash", evidence=["a", "b"])
    s.set("bot", s.select("bot", ["gdpr:Art.4"]), applicable=False, justification="n/a")
    out = io.StringIO()
    s.write_soa("bot", out)
    twin = Scope.new("Acme", lib)
    twin.add_system("bot", "Bot", ["gdpr"])
    r = sp.import_decisions(twin, out.getvalue())
    assert r["errors"] == []
    for cid in ("gdpr:Art.33", "gdpr:Art.4"):
        a, b = s.decision("bot", cid), twin.decision("bot", cid)
        assert {k: a[k] for k in ("applicable", "justification", "status", "owner", "notes", "evidence")} == \
               {k: b[k] for k in ("applicable", "justification", "status", "owner", "notes", "evidence")}
    assert twin.decision("bot", "gdpr:Art.33")["owner"] == "=SUM(1)"  # the export's apostrophe is not kept


# ---- CLI ------------------------------------------------------------------------------------------------------
def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_template_then_import(capsys, tmp_path):
    f, t = str(tmp_path / "scope.json"), tmp_path / "t.csv"
    code, _, err = run(capsys, "scope", "template", "-s", "bot", "--frameworks", "gdpr", "--org", "Acme", "--name", "Support bot", "-o", str(t), "--file", f)
    assert code == 0 and "fill it in" in err
    t.write_text(sheet(aicontrols.load(), {"gdpr:Art.33": {"status": "implemented", "owner": "Dana"}}), encoding="utf-8")
    code, out, _ = run(capsys, "scope", "import-csv", str(t), "--file", f)
    assert code == 0 and "new system" in out and "1 control(s) updated" in out
    data = json.loads(Path(f).read_text())
    assert data["organization"] == "Acme" and data["decisions"]["bot"]["gdpr:Art.33"]["owner"] == "Dana"
    assert run(capsys, "scope", "validate", "--file", f)[0] == 0
    # a pre-filled template for an existing system
    code, out, _ = run(capsys, "scope", "template", "--file", f)
    assert code == 0 and "implemented" in out


def test_cli_import_failure_writes_nothing(capsys, tmp_path):
    f, t = str(tmp_path / "scope.json"), tmp_path / "t.csv"
    t.write_text(sheet(aicontrols.load(), {"gdpr:Art.33": {"due": "soon"}}), encoding="utf-8")
    code, out, err = run(capsys, "scope", "import-csv", str(t), "--file", f)
    assert code == 1 and "row" in out and "nothing imported" in err and not Path(f).exists()


def test_cli_template_needs_a_system_and_frameworks(capsys, tmp_path):
    f = str(tmp_path / "scope.json")
    assert run(capsys, "scope", "template", "--file", f)[0] == 2
    assert run(capsys, "scope", "template", "-s", "bot", "--file", f)[0] == 2


# ---- agreement with the browser implementation ----------------------------------------------------------------
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def node(tmp_path, job):
    p = tmp_path / "job.json"
    p.write_text(json.dumps(job), encoding="utf-8")
    r = subprocess.run([NODE, str(ROOT / "tests" / "site_harness.js"), str(p)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_browser_template_and_parser_match_python_exactly(tmp_path, lib):
    s = Scope.new("Acme", lib)
    s.add_system("bot", "Bot", ["gdpr"])
    s.set("bot", s.select("bot", ["gdpr:Art.33"]), status="implemented", owner="=x", evidence=["a", "b"], notes='say "hi", ok')
    templates = [dict(frameworks=["gdpr"], organisation="Acme", system_id="bot", system_name="Bot"),
                 dict(frameworks=["iso-42001", "eu-ai-act", "gdpr"], organisation="O, Inc.", system_id="x-1", system_name='The "big" one'),
                 dict(frameworks=["gdpr"], organisation="Acme", system_id="bot", system_name="Bot", scope=s.data)]
    parses = ["a,b\r\n1,2\r\n", 'a,"b,c",d\n"x""y",2,3\n', "a,b\n\"l1\nl2\",2\n", "﻿a;b\n1;2\n", "a,b\n\n,\n1,2\n", '"# n, c"\na,b\n', "a,b\r1,2\r", "",
              'a,b\n"unterminated,2\n', 'a,"b"c,d\n1,2,3\n']
    js = node(tmp_path, {"mode": "csv", "templates": templates, "parses": parses})
    for t, got in zip(templates, js["templates"]):
        want = sp.template_csv(lib, t["frameworks"], t["organisation"], t["system_id"], t["system_name"],
                               Scope(copy.deepcopy(t["scope"]), lib) if t.get("scope") else None)
        assert got == want
    assert js["parses"] == [sp.parse_csv(t) for t in parses]


@needs_node
def test_browser_import_matches_python_on_valid_and_broken_files(tmp_path, lib):
    existing = Scope.new("Acme", lib)
    existing.add_system("bot", "Bot", ["gdpr"])
    existing.set("bot", existing.select("bot", ["gdpr:Art.33"]), status="implemented", owner="Dana", evidence=["old"])
    cases = [  # (starting scope or None, csv text, system override)
        (None, sheet(lib), None),
        (None, sheet(lib, {"gdpr:Art.33": {"status": "In progress", "owner": "Dana", "due": "2026-12-31", "evidence": "IR plan; runbook", "notes": "draft"},
                           "gdpr:Art.4": {"applicable": "No", "justification": "Definitions only"}, "gdpr:Art.34": {"status": "implemented", "applicable": "y"}}), None),
        (None, sheet(lib, {"gdpr:Art.33": {"status": "finished"}, "gdpr:Art.34": {"due": "31/12/2026"}, "gdpr:Art.4": {"applicable": "no"},
                           "gdpr:Art.5(1)": {"applicable": "maybe"}}), None),
        (None, sheet(lib, {"gdpr:Art.33": {"owner": "'=SUM(1)", "notes": "a\nb"}}, frameworks=("gdpr", "eu-ai-act"), system="chat", name="Chat", org="Zed, Ltd"), None),
        (None, "", None),
        (None, "a,b\n1,2\n", None),
        (None, "control_id,status\ngdpr:Art.33,verified\n", None),
        (None, "system,control_id\na,gdpr:Art.33\nb,gdpr:Art.34\n", None),
        (None, "system,control_id\nbot,nope:1\nbot,iso-5181:ID\n", None),
        (None, "system,control_id\nbad id,gdpr:Art.33\n", None),
        (None, "control_id,status\ngdpr:Art.33,in_progress\ngdpr:Art.33,verified\n", "viasystem"),
        (None, '﻿"Control ID";"Applicable (SoA)";Status;"Notes / Gap"\r\ngdpr:Art.33;yes;"In Progress";"line one\nline two"\r\n', "semi"),
        (existing.data, "control_id,applicable,status\ngdpr:Art.33,yes,not_started\ngdpr:Art.34,yes,not_started\n", None),
        (existing.data, "control_id,owner,evidence,notes\ngdpr:Art.33,,new1; new2,hello\n", None),
        (existing.data, "system,control_id,status\nbot,eu-ai-act:Art.5,implemented\n", None),
        (existing.data, "system,control_id,status\nother,gdpr:Art.33,implemented\n", None),
        (existing.data, "control_id\n", None),
    ]
    imports = [{"scope": sc, "text": text, "system": sysid} for sc, text, sysid in cases]
    js = node(tmp_path, {"mode": "csv", "imports": imports})
    messages = 0
    for (sc, text, sysid), got in zip(cases, js["imports"]):
        scope = Scope(copy.deepcopy(sc), lib) if sc else new_scope(lib)
        want = sp.import_decisions(scope, text, sysid)
        assert got["result"] == json.loads(json.dumps(want)), f"result differs for {text[:60]!r}"
        # a failed import into a brand-new workspace creates nothing: the browser answers "no scope"
        expected = None if (sc is None and want["errors"]) else json.loads(json.dumps(scope.data))
        assert got["scope"] == expected, f"scope differs for {text[:60]!r}"
        messages += len(want["errors"]) + len(want["warnings"])
    assert messages >= 12  # the cases really do exercise error and warning paths
