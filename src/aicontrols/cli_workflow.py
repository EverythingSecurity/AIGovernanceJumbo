# SPDX-License-Identifier: Apache-2.0
"""`aicontrols workflow ...`: the six-stage governance lifecycle on top of a scope file."""
from __future__ import annotations

import csv
import getpass
import json
import os
import sys
from pathlib import Path

from .library import Library
from .scope import DEFAULT_FILE, Scope, ScopeError, csv_safe
from .workflow import (EXCEPTION_TYPES, FREQUENCIES, RATINGS, RISK_APPETITES, ROLE_EXECUTIVE, ROLE_SECOND_LINE,
                       TEST_TYPES, Workflow, WorkflowError, parse_dt)


STAGE_SHORT = {"FRAMEWORK_SCOPING": "Scope", "CONTROL_HARMONIZATION": "Harmonise", "CONTROL_TAILORING": "Tailor",
               "CONTINUOUS_MONITORING": "Monitor", "EXCEPTION_GOVERNANCE": "Exceptions",
               "TARGET_GAP_ANALYSIS": "Gap analysis"}


def _actor(a) -> str:
    return (getattr(a, "by", None) or os.environ.get("AICONTROLS_ACTOR") or getpass.getuser() or "").strip()


def _open(lib: Library, a):
    scope = Scope.load(a.file, lib)
    return scope, Workflow(scope)


def _save(scope: Scope, a) -> None:
    scope.save(a.file)


def _line(c) -> str:
    return f"{c.id:<34} {c.title[:64]}"


# ---- lifecycle -----------------------------------------------------------------------
def cmd_init(lib, a) -> int:
    scope, wf = _open(lib, a)
    wf.enable(a.system, _actor(a))
    _save(scope, a)
    first = wf.stages[wf.order[0]]
    print(f"workflow enabled for {wf.sid(a.system)}; stage 1 of {len(wf.order)}: {first['name']}")
    print(f"next: set the profile with `aicontrols workflow profile ...` (role: {first['assignedRole']})")
    return 0


def cmd_status(lib, a) -> int:
    scope, wf = _open(lib, a)
    sid = wf.sid(a.system)
    st = wf.state(sid)
    idx = wf.order.index(st["stage"]) + 1
    stage = wf.stages[st["stage"]]
    print(f"{scope.data['organization']} / {scope.system(sid)['name']}")
    print(f"cycle {st['cycle']}, stage {idx} of {len(wf.order)}: {st['stage']} ({stage['name']})")
    print("   " + "  ".join(("[*]" if s == st["stage"] else "[x]" if wf.order.index(s) < idx - 1 else "[ ]") + STAGE_SHORT.get(s, s)
                            for s in wf.order))
    print(f"\nrole for this stage: {stage['assignedRole']}\n")
    acts = wf.actions(sid)
    for x in acts:
        print(f"  [{'x' if x['satisfied'] else ' '}] {x['action']:<48} {x['kind']:<8} {x['detail']}")
    open_n = sum(1 for x in acts if not x["satisfied"])
    if not open_n:
        print("\nall actions satisfied: `aicontrols workflow advance` moves to the next stage"
              if not stage.get("isFinal") else "\nall actions satisfied: `aicontrols workflow advance` completes this cycle")
    else:
        print(f"\n{open_n} action(s) open. Attestations: `aicontrols workflow attest <ACTION>`; the rest come from your data.")
    done = st["completed_cycles"]
    if done:
        print(f"completed cycles: {', '.join(str(c['cycle']) for c in done)}")
    return 0


def cmd_profile(lib, a) -> int:
    scope, wf = _open(lib, a)
    fields = {"business_unit": a.business_unit, "environment": a.environment, "boundary": a.boundary,
              "asset_classes": a.asset_class or None, "risk_appetite": a.risk_appetite, "target_default": a.target_default}
    if all(v is None for v in fields.values()):
        for k, v in wf.state(a.system)["profile"].items():
            print(f"{k:<16} {v}")
        return 0
    wf.set_profile(a.system, _actor(a), **fields)
    _save(scope, a)
    print("profile updated")
    return 0


def cmd_attest(lib, a) -> int:
    scope, wf = _open(lib, a)
    wf.attest(a.system, _actor(a), a.role, a.action, a.note or "")
    _save(scope, a)
    print(f"attested: {a.action}")
    return 0


def cmd_advance(lib, a) -> int:
    scope, wf = _open(lib, a)
    nxt = wf.advance(a.system, _actor(a), force=a.force, reason=a.reason or "")
    _save(scope, a)
    print(nxt if nxt == "cycle complete" else f"advanced to {nxt}: {wf.stages[nxt]['name']}")
    return 0


def cmd_restart(lib, a) -> int:
    scope, wf = _open(lib, a)
    n = wf.restart_cycle(a.system, _actor(a), a.reason or "")
    _save(scope, a)
    print(f"cycle {n} started at stage 1")
    return 0


def cmd_target(lib, a) -> int:
    scope, wf = _open(lib, a)
    n = wf.set_target(a.system, _actor(a), a.status, a.by_date, a.controls, a.domain, a.framework)
    _save(scope, a)
    print(f"target '{a.status}' set on {n} control(s)")
    return 0


# ---- common controls -----------------------------------------------------------------
def cmd_cc_add(lib, a) -> int:
    scope, wf = _open(lib, a)
    cc = wf.cc_add(a.system, _actor(a), a.title, a.id, a.description or "", a.domain)
    _save(scope, a)
    print(f"added {cc['id']}: {cc['title']}")
    return 0


def cmd_cc_list(lib, a) -> int:
    scope, wf = _open(lib, a)
    sid = wf.sid(a.system)
    ccs = wf.state(sid)["common_controls"]
    if not ccs:
        print("no common controls yet; try: aicontrols workflow cc suggest")
        return 0
    print(f"{'id':<8} {'controls':>8} {'frameworks':>10}  {'owner':<18} {'freq':<10} {'effectiveness':<20} title")
    for cc_id, cc in ccs.items():
        members = wf.members(sid, cc_id)
        fws = len({lib.get(m).framework_id for m in members})
        eff = wf.effectiveness(sid, cc_id)["state"]
        print(f"{cc_id:<8} {len(members):>8} {fws:>10}  {(cc['owner'] or '-')[:18]:<18} {(cc['frequency'] or '-'):<10} {eff:<20} {cc['title'][:50]}")
    return 0


def cmd_cc_show(lib, a) -> int:
    scope, wf = _open(lib, a)
    sid = wf.sid(a.system)
    cc = wf.cc(sid, a.cc)
    print(f"{cc['id']}: {cc['title']}")
    for k in ("description", "owner", "reviewer", "frequency", "implementation"):
        print(f"  {k:<15} {cc[k] or '-'}")
    print(f"  {'test':<15} {cc['test']['type'] or '-'}: {cc['test']['description'] or '-'}")
    print(f"  {'evidence':<15} {'; '.join(cc['evidence_required']) or '-'}")
    if cc["parameters"]:
        print(f"  {'parameters':<15} {json.dumps(cc['parameters'])}")
    for ind in cc["indicators"]:
        print(f"  {ind['id']:<15} {ind['name']} [{ind['metric']}] breach if {ind['breach_if']['op']} {ind['breach_if']['value']:g}")
    eff = wf.effectiveness(sid, a.cc)
    print(f"  {'effectiveness':<15} {eff['state']} (pass rate {eff['rate']}, last result {eff['last_at']})")
    members = wf.members(sid, a.cc)
    print(f"\nmaps {len(members)} control(s):")
    for m in members:
        print("  " + _line(lib.get(m)))
    return 0


def cmd_cc_map(lib, a) -> int:
    scope, wf = _open(lib, a)
    n = wf.cc_map(a.system, _actor(a), a.cc, a.controls, a.domain, a.framework, a.move)
    _save(scope, a)
    print(f"mapped {n} control(s) to {a.cc}")
    return 0


def cmd_cc_suggest(lib, a) -> int:
    scope, wf = _open(lib, a)
    props = wf.cc_suggest(a.system, a.min_frameworks)
    if not props:
        print("nothing to propose: every applicable control is already mapped")
        return 0
    print(f"{len(props)} proposed common control(s), one per domain (mirrors the dataset's crosswalk; review before relying on it):\n")
    for p in props:
        print(f"  {p['title'][:56]:<56} {len(p['controls']):>3} controls from {p['frameworks']} framework(s)")
    if a.apply:
        n = wf.cc_apply_suggestions(a.system, _actor(a), props)
        _save(scope, a)
        print(f"\ncreated {n} common control(s) and mapped their controls")
    else:
        print("\nadd --apply to create them")
    return 0


def cmd_cc_gaps(lib, a) -> int:
    scope, wf = _open(lib, a)
    rows = wf.unmapped(a.system)
    for c in rows:
        print(_line(c))
    print(f"-- {len(rows)} applicable control(s) not mapped to a common control", file=sys.stderr)
    return 0


def cmd_cc_gap_accept(lib, a) -> int:
    scope, wf = _open(lib, a)
    n = wf.gap_accept(a.system, _actor(a), a.controls, a.reason or "", a.domain, a.framework)
    _save(scope, a)
    print(f"{n} control(s) accepted as unmapped")
    return 0


def cmd_cc_set(lib, a) -> int:
    scope, wf = _open(lib, a)
    params = {}
    for item in a.param or []:
        if "=" not in item:
            raise WorkflowError(f"--param expects name=value, got {item!r}")
        k, v = item.split("=", 1)
        params[k.strip()] = v.strip()
    wf.cc_set(a.system, _actor(a), a.cc, title=a.title, owner=a.owner, reviewer=a.reviewer, frequency=a.frequency,
              implementation=a.implementation, evidence_required=a.evidence or None, test_type=a.test_type,
              test_description=a.test_description, parameters=params or None)
    _save(scope, a)
    print(f"updated {a.cc}")
    return 0


def cmd_tailor(lib, a) -> int:
    scope, wf = _open(lib, a)
    wf.tailor(a.system, _actor(a), a.control, a.implementation)
    _save(scope, a)
    print(f"tailored {a.control}")
    return 0


def cmd_indicator_add(lib, a) -> int:
    scope, wf = _open(lib, a)
    ind = wf.indicator_add(a.system, _actor(a), a.cc, a.name, a.kind, a.metric, a.op, a.value)
    _save(scope, a)
    print(f"added {ind['kind']} {ind['id']} to {a.cc}: breach if {a.metric} {a.op} {a.value:g}")
    return 0


# ---- monitoring -----------------------------------------------------------------------
def cmd_ingest(lib, a) -> int:
    scope, wf = _open(lib, a)
    text = Path(a.path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        records = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        records = []
        for n, line in enumerate(text.splitlines(), 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    raise WorkflowError(f"{a.path} line {n} is not valid JSON") from None
    out = wf.ingest(a.system, _actor(a), records, a.source or Path(a.path).name)
    _save(scope, a)
    print(f"ingested {out['accepted']} result(s); {out['duplicates']} duplicate(s); {len(out['rejected'])} rejected")
    for i, why in out["rejected"][:10]:
        print(f"  record {i}: {why}")
    return 1 if out["rejected"] and not out["accepted"] else 0


def cmd_ccm_evaluate(lib, a) -> int:
    scope, wf = _open(lib, a)
    res = wf.evaluate(a.system, _actor(a))
    _save(scope, a)
    print(f"{'common control':<10} {'state':<20} {'pass rate':>9} {'tested':>6}  last result")
    for cc_id, e in res["effectiveness"].items():
        rate = "-" if e["rate"] is None else f"{e['rate']:.0%}"
        print(f"{cc_id:<10} {e['state']:<20} {rate:>9} {e['tested']:>6}  {e['last_at'] or '-'}")
    for b in res["breaches"]:
        print(f"BREACH {b['kind']} {b['cc']}/{b['indicator']} {b['name']}: {b['metric']}={b['value']:g} ({b['rule']})")
    if res["new_escalations"]:
        print(f"\n{len(res['new_escalations'])} new escalation(s) recorded; acknowledge with: aicontrols workflow ccm ack <key>")
    return 0


def cmd_ccm_list(lib, a) -> int:
    scope, wf = _open(lib, a)
    rows = wf.state(a.system)["escalations"]
    for e in rows:
        print(f"{e['status']:<13} {e['kind']} {e['cc']}/{e['indicator']} value {e['value']:g} ({e['rule']}) at {e['at']}\n    key: {e['key']}")
    print(f"-- {len(rows)} escalation(s)", file=sys.stderr)
    return 0


def cmd_ccm_ack(lib, a) -> int:
    scope, wf = _open(lib, a)
    wf.escalation_ack(a.system, _actor(a), a.key, a.note or "")
    _save(scope, a)
    print("acknowledged")
    return 0


# ---- exceptions -------------------------------------------------------------------------
def _ex_line(e) -> str:
    rating = (e["assessment"] or {}).get("rating", "-")
    until = e["expires"] or "-"
    return f"{e['id']:<7} {e['state']:<10} {rating:<9} until {until:<11} {e['type']:<20} {e['reason'][:50]}"


def cmd_ex_request(lib, a) -> int:
    scope, wf = _open(lib, a)
    ex = wf.exception_request(a.system, _actor(a), a.reason, a.type, a.control or [], a.cc, a.compensating or "")
    _save(scope, a)
    print(f"{ex['id']} requested. Next: a second-line assessor runs `workflow exception assess {ex['id']} ...`")
    return 0


def cmd_ex_assess(lib, a) -> int:
    scope, wf = _open(lib, a)
    ex = wf.exception_assess(a.system, _actor(a), a.id, a.likelihood, a.impact, a.notes or "")
    _save(scope, a)
    need = wf.required_approver(wf.sid(a.system), ex)
    print(f"{a.id} assessed: {ex['assessment']['rating']} (score {ex['assessment']['score']}). Sign-off needed from {need}.")
    return 0


def cmd_ex_approve(lib, a) -> int:
    scope, wf = _open(lib, a)
    ex = wf.exception_approve(a.system, _actor(a), a.role, a.id, a.days)
    _save(scope, a)
    print(f"{a.id} approved until {ex['expires']}. It will need re-assessment when it expires.")
    return 0


def cmd_ex_reject(lib, a) -> int:
    scope, wf = _open(lib, a)
    wf.exception_reject(a.system, _actor(a), a.role, a.id, a.reason or "")
    _save(scope, a)
    print(f"{a.id} rejected")
    return 0


def cmd_ex_reopen(lib, a) -> int:
    scope, wf = _open(lib, a)
    wf.exception_reopen(a.system, _actor(a), a.id, a.reason or "")
    _save(scope, a)
    print(f"{a.id} reopened for re-assessment")
    return 0


def cmd_ex_close(lib, a) -> int:
    scope, wf = _open(lib, a)
    wf.exception_close(a.system, _actor(a), a.id, a.reason or "")
    _save(scope, a)
    print(f"{a.id} closed")
    return 0


def cmd_ex_list(lib, a) -> int:
    scope, wf = _open(lib, a)
    rows = wf.exceptions(a.system)
    for e in rows:
        print(_ex_line(e))
    print(f"-- {len(rows)} exception(s)", file=sys.stderr)
    return 0


def cmd_ex_review(lib, a) -> int:
    scope, wf = _open(lib, a)
    sid = wf.sid(a.system)
    import datetime as dt
    horizon = a.within if a.within is not None else wf.policy(sid)["reassess_warning_days"]
    today = dt.datetime.now(dt.timezone.utc).date()
    hits = []
    for e in wf.exceptions(sid):
        if e["state"] == "expired":
            hits.append(("EXPIRED", e))
        elif e["state"] in ("active", "expiring") and (dt.date.fromisoformat(e["expires"]) - today).days <= horizon:
            hits.append(("EXPIRING", e))
        elif e["state"] in ("requested", "assessed"):
            hits.append(("PENDING", e))
    for tag, e in hits:
        print(f"{tag:<9} {_ex_line(e)}")
    print(f"-- {len(hits)} exception(s) need attention (horizon {horizon} days)", file=sys.stderr)
    return 1 if any(t == "EXPIRED" for t, _e in hits) else 0


# ---- policy, gap, POA&M, audit, report ------------------------------------------------
def cmd_policy(lib, a) -> int:
    scope, wf = _open(lib, a)
    if a.assignment:
        if "=" not in a.assignment:
            raise WorkflowError("use KEY=VALUE, e.g. separation_of_duties=false")
        k, v = a.assignment.split("=", 1)
        wf.policy_set(a.system, _actor(a), k.strip(), v.strip())
        _save(scope, a)
        print(f"policy {k.strip()} set (recorded in the audit trail)")
    print(json.dumps(wf.policy(a.system), indent=2))
    return 0


def cmd_gap(lib, a) -> int:
    scope, wf = _open(lib, a)
    res = wf.gap_analysis(a.system, _actor(a), record=True)
    _save(scope, a)
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    pct = "n/a" if res["percent"] is None else f"{res['percent']}%"
    print(f"as of {res['as_of']}: {res['at_target']} of {res['applicable']} applicable controls at or above target ({pct})")
    for label, table in (("framework", res["by_framework"]), ("domain", res["by_domain"])):
        if label == "framework":
            for k, v in table.items():
                print(f"  {lib.frameworks[k].name:<28} {v['at_target']:>4} / {v['applicable']:<4}")
    gaps = res["gaps"]
    by_state = {s: sum(1 for g in gaps if g["state"] == s) for s in ("overdue", "open", "excepted")}
    print(f"\ngaps: {by_state['overdue']} overdue, {by_state['open']} open, {by_state['excepted']} covered by an active exception")
    for g in gaps[:a.top]:
        print(f"  {g['state']:<8} {g['control_id']:<32} {g['current']} -> {g['target']}  due {g['due'] or '-'}  {g['owner'] or '(no owner)'}")
    if len(gaps) > a.top:
        print(f"  ... {len(gaps) - a.top} more (see: aicontrols workflow poam)")
    for g in res["assurance_gaps"]:
        print(f"ASSURANCE {g['cc']} {g['title']}: {g['state']}, yet {g['controls_claiming_done']} mapped control(s) are marked done")
    return 0


def cmd_poam(lib, a) -> int:
    scope, wf = _open(lib, a)
    rows = wf.poam(a.system)
    cols = ["control_id", "title", "current", "target", "milestone_due", "owner", "state", "exception", "common_control"]
    out = open(a.output, "w", encoding="utf-8", newline="") if a.output else sys.stdout
    try:
        w = csv.DictWriter(out, fieldnames=cols)
        w.writeheader()
        w.writerows({k: csv_safe(v) for k, v in r.items()} for r in rows)
    finally:
        if a.output:
            out.close()
    print(f"-- {len(rows)} POA&M row(s)", file=sys.stderr)
    return 0


def cmd_audit_show(lib, a) -> int:
    scope, wf = _open(lib, a)
    log = wf.audit_log
    for ev in log[-a.n:]:
        print(f"#{ev['seq']:<4} {ev['at']}  {ev['actor']:<14} {ev['role'][:24]:<24} {ev['action']:<26} {ev['target']}")
    print(f"-- {len(log)} event(s); head hash {log[-1]['hash'][:16] if log else '-'}", file=sys.stderr)
    return 0


def cmd_audit_verify(lib, a) -> int:
    scope, wf = _open(lib, a)
    ok, problems = wf.verify(a.system, _actor(a))
    _save(scope, a)
    for p in problems:
        print("FAIL", p)
    head = wf.audit_log[-1]["hash"] if wf.audit_log else "-"
    print(f"audit chain {'OK' if ok else 'BROKEN'}: {len(wf.audit_log)} event(s); head {head}")
    if ok:
        print("tip: record the head hash somewhere outside this file to make later edits detectable")
    return 0 if ok else 1


def cmd_audit_export(lib, a) -> int:
    scope, wf = _open(lib, a)
    text = "".join(json.dumps(ev, sort_keys=True, ensure_ascii=False) + "\n" for ev in wf.audit_log)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print(f"-- wrote {len(wf.audit_log)} event(s) to {a.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def cmd_report(lib, a) -> int:
    scope, wf = _open(lib, a)
    if a.format == "json":
        text = json.dumps(wf.report(a.system, _actor(a), record=True), indent=2) + "\n"
    else:
        text = wf.report_markdown(a.system, _actor(a), record=True)
    _save(scope, a)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print(f"-- wrote {a.output}", file=sys.stderr)
    else:
        print(text)
    return 0


# ---- parser -----------------------------------------------------------------------------
def add_parser(sub) -> None:
    wp = sub.add_parser("workflow", help="six-stage governance lifecycle: profile, harmonise, tailor, monitor, "
                                         "manage exceptions, analyse gaps")
    w = wp.add_subparsers(dest="workflow_command", required=True)

    def common(p, system=True, actor=True):
        p.add_argument("--file", default=DEFAULT_FILE, help=f"scope file (default: {DEFAULT_FILE})")
        if system:
            p.add_argument("-s", "--system", help="system id (optional if there is only one)")
        if actor:
            p.add_argument("--by", help="who is acting (default: $AICONTROLS_ACTOR or your login name)")

    def add(parent, name, fn, help_, **kw):
        p = parent.add_parser(name, help=help_)
        common(p, **kw)
        p.set_defaults(fn=fn)
        return p

    add(w, "init", cmd_init, "enable the workflow for a system")
    add(w, "status", cmd_status, "current stage, its actions and what is open")
    p = add(w, "profile", cmd_profile, "set or show the organisational profile (boundaries, risk appetite, target)")
    p.add_argument("--business-unit"); p.add_argument("--environment"); p.add_argument("--boundary")
    p.add_argument("--asset-class", action="append", help="repeatable, e.g. customer-data")
    p.add_argument("--risk-appetite", choices=RISK_APPETITES)
    p.add_argument("--target-default", choices=["implemented", "verified"],
                   help="the target profile for every control unless set otherwise")
    p = add(w, "attest", cmd_attest, "confirm an attestation action of the current stage")
    p.add_argument("action"); p.add_argument("--note"); p.add_argument("--role")
    p = add(w, "advance", cmd_advance, "move to the next stage once its actions are satisfied")
    p.add_argument("--force", action="store_true", help="advance with open actions (needs --reason; recorded)")
    p.add_argument("--reason")
    p = add(w, "restart", cmd_restart, "start the next assessment cycle")
    p.add_argument("--reason")
    p = add(w, "target", cmd_target, "set the target profile for controls")
    p.add_argument("controls", nargs="*"); p.add_argument("--domain"); p.add_argument("--framework")
    p.add_argument("--status", choices=["implemented", "verified"], required=True)
    p.add_argument("--by-date", help="YYYY-MM-DD")
    p = add(w, "tailor", cmd_tailor, "write the implementation statement for one control")
    p.add_argument("control"); p.add_argument("--implementation", required=True)

    cc = w.add_parser("cc", help="common controls: map many framework controls to one tested control")
    ccs = cc.add_subparsers(dest="cc_command", required=True)
    p = add(ccs, "add", cmd_cc_add, "create a common control")
    p.add_argument("title"); p.add_argument("--id"); p.add_argument("--description"); p.add_argument("--domain")
    add(ccs, "list", cmd_cc_list, "list common controls", actor=False)
    p = add(ccs, "show", cmd_cc_show, "show one common control", actor=False); p.add_argument("cc")
    p = add(ccs, "map", cmd_cc_map, "map controls to a common control")
    p.add_argument("cc"); p.add_argument("controls", nargs="*"); p.add_argument("--domain"); p.add_argument("--framework")
    p.add_argument("--move", action="store_true", help="remap controls already mapped elsewhere")
    p = add(ccs, "suggest", cmd_cc_suggest, "propose common controls from the dataset's domains")
    p.add_argument("--min-frameworks", type=int, default=1); p.add_argument("--apply", action="store_true")
    add(ccs, "gaps", cmd_cc_gaps, "applicable controls with no common control", actor=False)
    p = add(ccs, "gap-accept", cmd_cc_gap_accept, "accept controls as deliberately unmapped (with a reason)")
    p.add_argument("controls", nargs="*"); p.add_argument("--domain"); p.add_argument("--framework")
    p.add_argument("--reason", required=True)
    p = add(ccs, "set", cmd_cc_set, "tailor a common control: owner, reviewer, frequency, evidence, test")
    p.add_argument("cc"); p.add_argument("--title"); p.add_argument("--owner"); p.add_argument("--reviewer")
    p.add_argument("--frequency", choices=list(FREQUENCIES)); p.add_argument("--implementation")
    p.add_argument("--evidence", action="append", help="required evidence artifact (repeatable)")
    p.add_argument("--test-type", choices=TEST_TYPES); p.add_argument("--test-description")
    p.add_argument("--param", action="append", help="implementation parameter name=value (repeatable)")

    ind = w.add_parser("indicator", help="KCI/KRI thresholds on a common control")
    inds = ind.add_subparsers(dest="indicator_command", required=True)
    p = add(inds, "add", cmd_indicator_add, "add a key control or key risk indicator")
    p.add_argument("cc"); p.add_argument("--name", required=True); p.add_argument("--kind", choices=["KCI", "KRI"], required=True)
    p.add_argument("--metric", required=True, help="metric name found in ingested results")
    p.add_argument("--op", choices=[">", ">=", "<", "<="], required=True, help="breach when the value is <op> the threshold")
    p.add_argument("--value", type=float, required=True, help="threshold")

    p = add(w, "ingest", cmd_ingest, "ingest test results and metrics from a JSON or JSONL file")
    p.add_argument("path"); p.add_argument("--source")
    ccm = w.add_parser("ccm", help="continuous monitoring: effectiveness and threshold alerts")
    ccms = ccm.add_subparsers(dest="ccm_command", required=True)
    add(ccms, "evaluate", cmd_ccm_evaluate, "score effectiveness and check KCI/KRI thresholds")
    add(ccms, "escalations", cmd_ccm_list, "list recorded escalations", actor=False)
    p = add(ccms, "ack", cmd_ccm_ack, "acknowledge an escalation"); p.add_argument("key"); p.add_argument("--note")

    ex = w.add_parser("exception", help="waivers and deviations with assessment, sign-off and expiry")
    exs = ex.add_subparsers(dest="exception_command", required=True)
    p = add(exs, "request", cmd_ex_request, "request an exception")
    p.add_argument("--reason", required=True); p.add_argument("--type", choices=EXCEPTION_TYPES, default="waiver")
    p.add_argument("--control", action="append", help="control id (repeatable)"); p.add_argument("--cc")
    p.add_argument("--compensating", help="compensating controls in place")
    p = add(exs, "assess", cmd_ex_assess, "second-line risk assessment (likelihood and impact, 1-5)")
    p.add_argument("id"); p.add_argument("--likelihood", type=int, required=True); p.add_argument("--impact", type=int, required=True)
    p.add_argument("--notes")
    p = add(exs, "approve", cmd_ex_approve, "sign off for a limited number of days")
    p.add_argument("id"); p.add_argument("--role", choices=[ROLE_SECOND_LINE, ROLE_EXECUTIVE], required=True)
    p.add_argument("--days", type=int, required=True)
    p = add(exs, "reject", cmd_ex_reject, "reject an open exception")
    p.add_argument("id"); p.add_argument("--role", choices=[ROLE_SECOND_LINE, ROLE_EXECUTIVE], required=True)
    p.add_argument("--reason", required=True)
    p = add(exs, "reopen", cmd_ex_reopen, "send back for re-assessment (e.g. at expiry)")
    p.add_argument("id"); p.add_argument("--reason", required=True)
    p = add(exs, "close", cmd_ex_close, "close an exception"); p.add_argument("id"); p.add_argument("--reason", required=True)
    add(exs, "list", cmd_ex_list, "list exceptions", actor=False)
    p = add(exs, "review", cmd_ex_review, "exceptions that are expired, expiring or waiting", actor=False)
    p.add_argument("--within", type=int, help="days ahead to look (default: policy reassess_warning_days)")

    p = add(w, "policy", cmd_policy, "show or change workflow policy (recorded in the audit trail)")
    p.add_argument("assignment", nargs="?", help="KEY=VALUE, e.g. exception_max_days.high=60")
    p = add(w, "gap", cmd_gap, "compare current status with the target profile")
    p.add_argument("--json", action="store_true"); p.add_argument("--top", type=int, default=15)
    p = add(w, "poam", cmd_poam, "plan of action and milestones as CSV", actor=False)
    p.add_argument("-o", "--output")
    au = w.add_parser("audit", help="the hash-chained audit trail")
    aus = au.add_subparsers(dest="audit_command", required=True)
    p = add(aus, "show", cmd_audit_show, "show recent events", actor=False); p.add_argument("-n", type=int, default=20)
    add(aus, "verify", cmd_audit_verify, "recompute the hash chain")
    p = add(aus, "export", cmd_audit_export, "export events as JSON lines", actor=False); p.add_argument("-o", "--output")
    p = add(w, "report", cmd_report, "governance report (Markdown or JSON)")
    p.add_argument("--format", choices=["md", "json"], default="md"); p.add_argument("-o", "--output")
