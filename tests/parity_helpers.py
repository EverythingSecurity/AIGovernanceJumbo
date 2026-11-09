# SPDX-License-Identifier: Apache-2.0
"""Shared by the Python-versus-browser parity tests: run the browser engines under Node, and a Python twin of
the operation runner in tests/site_harness.js (workflow and GRC operations)."""
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

from aicontrols import grc as grcmod
from aicontrols import workflow as wfmod
from aicontrols.grc import Grc
from aicontrols.scope import ScopeError
from aicontrols.workflow import Workflow

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def node(tmp_path, job):
    p = tmp_path / "job.json"
    p.write_text(json.dumps(job), encoding="utf-8")
    r = subprocess.run([NODE, str(ROOT / "tests" / "site_harness.js"), str(p)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ---- Python twin of the runner in tests/site_harness.js ------------------------------------------
def run_ops_py(scope, lib, ops, monkeypatch):
    sid = "bot"
    w = Workflow(scope)
    g = Grc(scope)
    now = {"t": dt.datetime(2026, 10, 27, 12, 0, 0, tzinfo=dt.timezone.utc)}
    monkeypatch.setattr(wfmod, "_now", lambda: now["t"])
    ccs = lambda: list(w.state(sid)["common_controls"])  # noqa: E731

    def clock(o):
        now["t"] = dt.datetime.fromisoformat(o["iso"].replace("Z", "+00:00"))

    h = {
        "clock": clock,
        "enable": lambda o: (w.enable(sid, o["by"]), "ok")[1],
        "profile": lambda o: w.set_profile(sid, o["by"], **o["fields"]),
        "target": lambda o: w.set_target(sid, o["by"], o["status"], o.get("by_date"), o.get("controls", []), o.get("domain"), o.get("framework")),
        "cc_add": lambda o: w.cc_add(sid, o["by"], o["title"], o.get("id"), o.get("description", ""), o.get("domain")),
        "cc_map": lambda o: w.cc_map(sid, o["by"], o["cc"], o.get("controls", []), o.get("domain"), o.get("framework"), bool(o.get("move"))),
        "cc_suggest": lambda o: w.cc_suggest(sid, o.get("min_frameworks", 1)),
        "cc_apply": lambda o: w.cc_apply_suggestions(sid, o["by"], w.cc_suggest(sid, 1)),
        "gap_accept": lambda o: w.gap_accept(sid, o["by"], o.get("controls", []), o["reason"], o.get("domain"), o.get("framework")),
        "unmapped": lambda o: [c.id for c in w.unmapped(sid)],
        "cc_set": lambda o: w.cc_set(sid, o["by"], o["cc"], **o["fields"]),
        "cc_set_all": lambda o: len([w.cc_set(sid, o["by"], i, **o["fields"]) for i in ccs()]),
        "tailor": lambda o: w.tailor(sid, o["by"], o["control"], o["implementation"]),
        "indicator": lambda o: w.indicator_add(sid, o["by"], o["cc"], o["name"], o["kind"], o["metric"], o["breach_op"], o["value"]),
        "ingest": lambda o: _ingest(w, sid, o),
        "ingest_all": lambda o: _ingest(w, sid, {"by": o["by"], "source": o.get("source", "feed"), "records": [
            {"control": i, "at": o["at"], "result": o["result"], "metrics": o.get("metrics", {})} for i in ccs()]}),
        "evaluate": lambda o: w.evaluate(sid, o["by"]),
        "ack": lambda o: w.escalation_ack(sid, o["by"], o["key"], o.get("note", "")),
        "ex_request": lambda o: w.exception_request(sid, o["by"], o["reason"], o.get("kind", "waiver"), o.get("controls", []), o.get("cc"), o.get("compensating", "")),
        "ex_assess": lambda o: w.exception_assess(sid, o["by"], o["id"], o["likelihood"], o["impact"], o.get("notes", "")),
        "ex_approve": lambda o: w.exception_approve(sid, o["by"], o["role"], o["id"], o["days"]),
        "ex_reject": lambda o: w.exception_reject(sid, o["by"], o["role"], o["id"], o["reason"]),
        "ex_reopen": lambda o: w.exception_reopen(sid, o["by"], o["id"], o["reason"]),
        "ex_close": lambda o: w.exception_close(sid, o["by"], o["id"], o["reason"]),
        "policy": lambda o: w.policy_set(sid, o["by"], o["key"], o["value"]),
        "attest": lambda o: w.attest(sid, o["by"], o.get("role"), o["action"], o.get("note", "")),
        "advance": lambda o: w.advance(sid, o["by"], bool(o.get("force")), o.get("reason", "")),
        "restart": lambda o: w.restart_cycle(sid, o["by"], o.get("reason", "")),
        "decide": lambda o: scope.set(sid, scope.select(sid, o["controls"]), **o["changes"]),
        "gap": lambda o: w.gap_analysis(sid, o["by"], record=True),
        "poam": lambda o: w.poam(sid),
        "verify": lambda o: _verify(w, sid, o),
        "report": lambda o: w.report(sid, o["by"], record=True),
        "report_md": lambda o: w.report_markdown(sid, o["by"], record=True),
        "actions": lambda o: w.actions(sid),
        "eff": lambda o: w.effectiveness(sid, o["cc"]),
        "exceptions": lambda o: w.exceptions(sid),
        "validate": lambda o: dict(zip(("errors", "warnings"), wfmod.validate_workflow(scope))),
        # ---- GRC layer
        "grc_add": lambda o: g.add(o["register"], o["by"], **o["fields"]),
        "grc_update": lambda o: g.update(o["register"], o["by"], o["id"], **o["fields"]),
        "grc_remove": lambda o: g.remove(o["register"], o["by"], o["id"]),
        "grc_link": lambda o: g.link(sid, o["by"], o["cc"], o.get("policy", []), o.get("guideline", []), o.get("sop", []),
                                     o.get("evidence_sources", []), bool(o.get("unlink"))),
        "grc_scope_statement": lambda o: g.set_scope_statement(o["by"], o["framework"], o["statement"], o.get("reviewed")),
        "grc_scope_review": lambda o: g.review_scope(o["by"], o.get("date")),
        "grc_mapping_review": lambda o: g.review_mappings(sid, o["by"], o["cc"], o["owner"], o.get("date")),
        "grc_roles": lambda o: g.set_roles(o["by"], o["role"], o["names"]),
        "grc_setting": lambda o: g.set_setting(o["by"], o["key"], o["value"]),
        "grc_seed": lambda o: g.seed_evidence_sources(o["by"]),
        "grc_records": lambda o: g.records(o["register"]),
        "grc_matrix": lambda o: g.matrix(sid),
        "grc_matrix_summary": lambda o: g.matrix_summary(g.matrix(sid)),
        "grc_matrix_csv": lambda o: g.matrix_csv(sid),
        "grc_coverage": lambda o: g.coverage(sid),
        "grc_kpis": lambda o: g.kpis(sid),
        "grc_streams": lambda o: g.streams(sid),
        "grc_lifecycle": lambda o: g.lifecycle(sid),
        "grc_artifacts": lambda o: g.artifacts(sid),
        "grc_roles_list": lambda o: g.roles(),
        "grc_settings": lambda o: g.settings(),
        "grc_report": lambda o: g.report(sid, o["by"], record=True),
        "grc_report_md": lambda o: g.report_markdown(sid, o["by"], record=True),
        "grc_validate": lambda o: dict(zip(("errors", "warnings"), grcmod.validate_grc(scope))),
    }
    results = []
    for o in ops:
        try:
            results.append({"ok": h[o["op"]](o)})
        except ScopeError as e:
            results.append({"error": str(e)})
    return results


def _ingest(w, sid, o):
    out = w.ingest(sid, o["by"], o["records"], o.get("source", "file"))
    return {"accepted": out["accepted"], "duplicates": out["duplicates"], "rejected": [list(x) for x in out["rejected"]]}


def _verify(w, sid, o):
    ok, problems = w.verify(sid, o["by"])
    return {"ok": ok, "problems": problems}


def norm(value):
    """JSON round trip: tuples become lists, so Python and JavaScript results compare equal."""
    return json.loads(json.dumps(value))


