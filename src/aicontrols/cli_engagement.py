# SPDX-License-Identifier: Apache-2.0
"""`aicontrols engagement ...`: client onboarding, scoping questionnaire, recommendations, review and assignment."""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

from .engagement import Engagement, EngagementError, load_spec
from .library import Library
from .scope import DEFAULT_FILE, Scope


def _actor(a) -> str:
    return (getattr(a, "by", None) or os.environ.get("AICONTROLS_ACTOR") or getpass.getuser() or "").strip()


def _open(lib: Library, a):
    scope = Scope.load(a.file, lib)
    return scope, Engagement(scope)


def _show(v) -> str:
    return "-" if v is None or v == [] else (", ".join(v) if isinstance(v, list) else str(v))


def cmd_client_set(lib, a) -> int:
    scope, e = _open(lib, a)
    fields = {k: getattr(a, k) for k in ("name", "sector", "country", "size", "contributor") if getattr(a, k, None) is not None}
    c = e.set_client(_actor(a), fields)
    scope.save(a.file)
    print(f"client {c['name']}: sector {_show(c['sector'])}, country {_show(c['country'])}, size {_show(c['size'])}, "
          f"contributor {_show(c['contributor'])}, status {c['status']}")
    return 0


def cmd_client_onboard(lib, a) -> int:
    scope, e = _open(lib, a)
    c = e.onboard(_actor(a))
    scope.save(a.file)
    print(f"{c['name']} is onboarded; contributor {c['contributor']}. Next: engagement questions")
    return 0


def cmd_questions(lib, a) -> int:
    scope, e = _open(lib, a)
    doms = {d["id"]: d["name"] for d in load_spec()["questionnaire"]["domains"]}
    last = None
    for q in e.questionnaire():
        if a.unanswered and q["answer"] is not None:
            continue
        if q["domain"] != last:
            print(f"\n{doms[q['domain']]}")
            last = q["domain"]
        mark = " *" if q["required"] else ""
        opts = f"  [{', '.join(q['options'])}]" if q.get("options") else ("  [yes, no]" if q["kind"] == "yes_no" else "")
        print(f"  {q['id']}{mark}: {q['text']}{opts}")
        if q["answer"] is not None:
            print(f"      answer: {_show(q['answer'])}  (by {q['answered_by']})")
        if q["delegated_to"]:
            print(f"      delegated to {q['delegated_to']}" + (f", due {q['due']}" if q["due"] else ""))
    p = e.progress()
    print(f"\n{p['required_answered']} of {p['required']} required answered (* = required); status {p['status']}")
    return 0


def cmd_answer(lib, a) -> int:
    scope, e = _open(lib, a)
    q = e.questions.get(a.question)
    value = a.value if q is not None and q["kind"] == "multi" else (" ".join(a.value) if a.value else "")
    v = e.answer(_actor(a), a.question, value)
    scope.save(a.file)
    print(f"{a.question} = {_show(v)}")
    return 0


def cmd_delegate(lib, a) -> int:
    scope, e = _open(lib, a)
    d = e.delegate(_actor(a), a.question, a.to, a.due)
    scope.save(a.file)
    print(f"{a.question} delegated to {d['to']}" + (f", due {d['due']}" if d["due"] else ""))
    return 0


def cmd_submit(lib, a) -> int:
    scope, e = _open(lib, a)
    e.submit_scoping(_actor(a))
    scope.save(a.file)
    print("scoping answers submitted and locked. Next: engagement recommend")
    return 0


def cmd_reopen(lib, a) -> int:
    scope, e = _open(lib, a)
    e.reopen_scoping(_actor(a), a.reason)
    scope.save(a.file)
    print("scoping answers reopened; any recommendation and review were cleared")
    return 0


def cmd_recommend(lib, a) -> int:
    scope, e = _open(lib, a)
    rec = e.recommend(_actor(a))
    scope.save(a.file)
    if a.json:
        print(json.dumps(rec, indent=2))
        return 0
    for i in rec["items"]:
        print(f"{i['framework']:<14} {i['confidence']:<7} rules {', '.join(i['rules'])}")
        for t in i["rationale"]:
            print(f"    - {t}")
        print(f"    triggered by: {', '.join(i['triggers'])}")
    for s in rec["skipped"]:
        print(f"skipped: rule {s['rule']} points at {s['framework']}, which {s['reason']}")
    print(f"{len(rec['items'])} framework(s) recommended (rules version {rec['rules_version']}). Next: engagement review")
    return 0


def cmd_review(lib, a) -> int:
    scope, e = _open(lib, a)
    r = e.review(_actor(a), a.framework, a.action, a.reason or "")
    scope.save(a.file)
    print(f"{a.framework}: {r['action']}" + (f" ({r['justification']})" if r["justification"] else ""))
    return 0


def cmd_finalise(lib, a) -> int:
    scope, e = _open(lib, a)
    ap = e.finalise(_actor(a), a.reason or "")
    scope.save(a.file)
    print(f"applicable frameworks finalised: {', '.join(ap['frameworks'])}")
    return 0


def cmd_reopen_assignment(lib, a) -> int:
    scope, e = _open(lib, a)
    e.reopen_assignment(_actor(a), a.reason)
    scope.save(a.file)
    print("assignment reopened")
    return 0


def cmd_status(lib, a) -> int:
    scope, e = _open(lib, a)
    o = e.overview()
    if a.json:
        print(json.dumps(o, indent=2))
        return 0
    if not o["enabled"]:
        print("engagement not started. Begin with: engagement client set --name ... --sector ... --country ... --size ... --contributor ...")
        return 0
    c, p = o["client"], o["scoping"]
    print(f"client {c['name']} ({c['status']}); stage: {o['stage']}")
    print(f"scoping: {p['required_answered']} of {p['required']} required answered ({p['status']})")
    print(f"recommended: {_show(o['recommended'])}; reviewed: {_show(o['reviewed'])}; applicable: {_show(o['applicable'])}")
    return 0


def cmd_rules(lib, a) -> int:
    scope, e = _open(lib, a)
    for r in e.effective_rules():
        tgt = r.get("framework") or f"(from answer {r['from_answer']})"
        print(f"{r['id']:<14} {tgt:<18} {r['confidence']:<7} w{r['weight']:<3} {r['source']:<6}{' DISABLED' if r['disabled'] else ''}")
        print(f"    {r['rationale']}")
    return 0


def cmd_rule_set(lib, a) -> int:
    scope, e = _open(lib, a)
    try:
        rule = json.loads(Path(a.rule_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise EngagementError(f"cannot read the rule file: {ex}") from None
    r = e.rule_set(_actor(a), rule)
    scope.save(a.file)
    print(f"rule {r['id']} saved")
    return 0


def cmd_rule_toggle(disable: bool):
    def run(lib, a) -> int:
        scope, e = _open(lib, a)
        e.rule_disable(_actor(a), a.rule, disable)
        scope.save(a.file)
        print(f"rule {a.rule} {'disabled' if disable else 'enabled'}")
        return 0
    return run


def add_parser(sub) -> None:
    spec = load_spec()
    ep = sub.add_parser("engagement", help="client engagement: onboarding, scoping questionnaire, framework recommendations, review")
    g = ep.add_subparsers(dest="engagement_command", required=True)

    def add(parent, name, fn, help_):
        p = parent.add_parser(name, help=help_)
        p.add_argument("--file", default=DEFAULT_FILE, help=f"scope file (default: {DEFAULT_FILE})")
        p.add_argument("--by", help="who is acting (default: $AICONTROLS_ACTOR or your login name)")
        p.set_defaults(fn=fn)
        return p

    cp = g.add_parser("client", help="the client profile")
    cs = cp.add_subparsers(dest="client_command", required=True)
    p = add(cs, "set", cmd_client_set, "create or update the client profile")
    p.add_argument("--name"); p.add_argument("--country"); p.add_argument("--contributor", help="the client's single point of contact")
    p.add_argument("--sector", choices=spec["sectors"]); p.add_argument("--size", choices=spec["sizes"])
    add(cs, "onboard", cmd_client_onboard, "mark the client onboarded (profile must be complete)")

    p = add(g, "questions", cmd_questions, "show the scoping questionnaire and answers")
    p.add_argument("--unanswered", action="store_true")
    p = add(g, "answer", cmd_answer, "answer a scoping question (several values for multi-choice)")
    p.add_argument("question"); p.add_argument("value", nargs="+")
    p = add(g, "delegate", cmd_delegate, "delegate a question to a department or person")
    p.add_argument("question"); p.add_argument("--to", required=True); p.add_argument("--due")
    add(g, "submit", cmd_submit, "submit and lock the scoping answers")
    p = add(g, "reopen", cmd_reopen, "reopen submitted scoping answers (clears recommendations)")
    p.add_argument("--reason", required=True)
    p = add(g, "recommend", cmd_recommend, "run the rules engine and record the recommendations")
    p.add_argument("--json", action="store_true")
    p = add(g, "review", cmd_review, "accept, add or remove a framework (add/remove need --reason)")
    p.add_argument("framework"); p.add_argument("action", choices=["accept", "add", "remove"]); p.add_argument("--reason")
    p = add(g, "finalise", cmd_finalise, "finalise the applicable framework set")
    p.add_argument("--reason")
    p = add(g, "reopen-assignment", cmd_reopen_assignment, "reopen a finalised framework set")
    p.add_argument("--reason", required=True)
    p = add(g, "status", cmd_status, "where the engagement stands")
    p.add_argument("--json", action="store_true")

    rp = g.add_parser("rules", help="applicability rules")
    rs = rp.add_subparsers(dest="rules_command", required=True)
    add(rs, "list", cmd_rules, "list effective rules")
    p = add(rs, "set", cmd_rule_set, "add or replace a custom rule from a JSON file")
    p.add_argument("rule_file")
    p = add(rs, "disable", cmd_rule_toggle(True), "disable a rule"); p.add_argument("rule")
    p = add(rs, "enable", cmd_rule_toggle(False), "enable a rule"); p.add_argument("rule")
