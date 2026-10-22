# SPDX-License-Identifier: Apache-2.0
"""`aicontrols scope ...` commands: record and report an organisation's own decisions."""
from __future__ import annotations

import sys
from pathlib import Path

from .library import Library
from .scope import DEFAULT_FILE, DONE, STATUSES, Scope, ScopeError

PRIVACY_NOTE = ("note: this file describes your real systems and gaps. Keep it in a private "
                "repository; it is listed in .gitignore here by default.")


def _load(lib: Library, a) -> Scope:
    return Scope.load(a.file, lib)


def _pct(row: dict) -> str:
    return "  n/a" if row["percent"] is None else f"{row['percent']:>5.1f}%"


def cmd_init(lib: Library, a) -> int:
    path = Path(a.file)
    if path.exists() and not a.force:
        raise ScopeError(f"{path} already exists (use --force to overwrite)")
    Scope.new(a.org, lib).save(path)
    print(f"created {path}")
    print(PRIVACY_NOTE)
    return 0


def cmd_add_system(lib: Library, a) -> int:
    scope = _load(lib, a)
    frameworks = [f.strip() for f in a.frameworks.split(",") if f.strip()]
    system = scope.add_system(a.id, a.name or a.id, frameworks, a.description or "")
    scope.save(a.file)
    n = len(scope.in_scope(a.id))
    print(f"added system {system['id']}: {n} controls in scope from {len(system['frameworks'])} frameworks")
    return 0


def cmd_set(lib: Library, a) -> int:
    scope = _load(lib, a)
    controls = scope.select(a.system, a.controls, domain=a.domain, framework=a.framework)
    changes = {"status": a.status, "owner": a.owner, "due": a.due, "reviewed": a.reviewed,
               "justification": a.justification, "notes": a.notes, "evidence": a.evidence}
    if a.applicable is not None:
        changes["applicable"] = a.applicable == "yes"
    changes = {k: v for k, v in changes.items() if v not in (None, [])}
    if not changes:
        raise ScopeError("nothing to change: give --status, --owner, --applicable, --due, ...")
    n = scope.set(a.system, controls, **changes)
    scope.save(a.file)
    print(f"updated {n} control(s)")
    if a.status in DONE:
        seen = {}
        for c in controls:
            for r in scope.related_open(a.system, c):
                seen[r.id] = r
        if seen:
            print(f"review: {len(seen)} other in-scope control(s) share a domain with what you just "
                  "marked done and are still open. They are NOT updated automatically; check "
                  "whether the same work satisfies them:")
            for r in list(seen.values())[:8]:
                print(f"  {r.id}  {r.title[:70]}")
            if len(seen) > 8:
                print(f"  ... and {len(seen) - 8} more")
    return 0


def _table(rows, label_width=44) -> None:
    head = f"{'':<{label_width}} {'total':>5} {'appl.':>5} {'n/a':>4} {'todo':>5} {'wip':>4} {'done':>5} {'done%':>7}"
    print(head)
    for r in rows:
        done = r["implemented"] + r["verified"]
        print(f"{r['label'][:label_width]:<{label_width}} {r['total']:>5} {r['applicable']:>5} "
              f"{r['not_applicable']:>4} {r['not_started']:>5} {r['in_progress']:>4} {done:>5} {_pct(r):>7}")


def cmd_status(lib: Library, a) -> int:
    scope = _load(lib, a)
    system = scope.system(a.system)
    print(f"{scope.data['organization']} / {system['name']} ({system['id']})\n")
    rows = scope.status(a.system, by=a.by)
    _table(rows)
    total = scope.overall(a.system)
    print()
    _table([{**total, "label": "OVERALL"}])
    print("\ndone = implemented + verified, as a share of applicable controls")
    return 0


def cmd_plan(lib: Library, a) -> int:
    scope = _load(lib, a)
    system = scope.system(a.system)
    every = scope.plan(a.system)
    plan = [p for p in every if p["frameworks"] >= a.min_frameworks]
    if a.top:
        plan = plan[:a.top]
    if a.format == "md":
        text = scope.plan_markdown(a.system, plan, len(every))
        if a.output:
            Path(a.output).write_text(text, encoding="utf-8")
            print(f"-- wrote {a.output}", file=sys.stderr)
        else:
            print(text)
        return 0
    shown = f"showing {len(plan)} of {len(every)}" if len(plan) != len(every) else f"{len(every)}"
    print(f"{scope.data['organization']} / {system['name']}: {shown} workstreams "
          "(domains), most-shared first\n")
    print(f"{'domain':<46} {'fw':>3} {'ctrls':>5} {'done%':>7} {'next due':>10} {'late':>4}  owners")
    for p in plan:
        owners = ", ".join(p["owners"]) or "-"
        print(f"{p['domain'][:46]:<46} {p['frameworks']:>3} {p['total']:>5} {_pct(p):>7} "
              f"{(p['next_due'] or '-'):>10} {(p['overdue'] or ''):>4}  {owners}")
    unowned = sum(1 for p in plan if not p["owners"])
    late = sum(p["overdue"] for p in plan)
    if late:
        print(f"\n{late} open control(s) are past their due date.")
    print(f"{unowned} of the workstreams shown have no owner. Assign with: "
          "aicontrols scope set --domain <domain> --owner <name>")
    return 0


def cmd_export(lib: Library, a) -> int:
    scope = _load(lib, a)
    if a.format == "md":
        text = scope.soa_markdown(a.system)
        if a.output:
            Path(a.output).write_text(text, encoding="utf-8")
        else:
            print(text)
        print(f"-- exported {len(scope.rows(a.system))} rows", file=sys.stderr)
        return 0
    out = open(a.output, "w", encoding="utf-8", newline="") if a.output else sys.stdout
    try:
        n = scope.write_soa(a.system, out)
    finally:
        if a.output:
            out.close()
    print(f"-- exported {n} rows", file=sys.stderr)
    return 0


def cmd_validate(lib: Library, a) -> int:
    scope = _load(lib, a)
    errors, warnings = scope.validate()
    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("error:", e)
    if errors:
        print(f"{len(errors)} error(s)")
        return 1
    print("ok" + (f" ({len(warnings)} warning(s))" if warnings else ""))
    return 0


def add_parser(sub) -> None:
    sp = sub.add_parser("scope", help="record scoping decisions, owners and status for your AI systems")
    ssub = sp.add_subparsers(dest="scope_command", required=True)

    def common(p, system=True):
        p.add_argument("--file", default=DEFAULT_FILE, help=f"scope file (default: {DEFAULT_FILE})")
        if system:
            p.add_argument("-s", "--system", help="system id (optional if there is only one)")

    p = ssub.add_parser("init", help="create a scope file"); common(p, system=False)
    p.add_argument("--org", required=True, help="organisation name")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = ssub.add_parser("add-system", help="add an AI system and choose its frameworks")
    common(p, system=False)
    p.add_argument("id"); p.add_argument("--name"); p.add_argument("--description")
    p.add_argument("--frameworks", required=True, help="comma-separated, e.g. iso-42001,eu-ai-act")
    p.set_defaults(fn=cmd_add_system)

    p = ssub.add_parser("set", help="record decisions, owner, status or evidence")
    common(p)
    p.add_argument("controls", nargs="*", help="control ids, e.g. gdpr:Art.33")
    p.add_argument("--domain", help="apply to every in-scope control in this domain")
    p.add_argument("--framework", help="apply to every in-scope control of this framework")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--owner")
    p.add_argument("--applicable", choices=["yes", "no"])
    p.add_argument("--justification", help="required when marking a control not applicable")
    p.add_argument("--due", help="YYYY-MM-DD")
    p.add_argument("--reviewed", help="YYYY-MM-DD")
    p.add_argument("--notes")
    p.add_argument("--evidence", action="append", help="evidence reference (repeatable; appended)")
    p.set_defaults(fn=cmd_set)

    p = ssub.add_parser("status", help="completion roll-up"); common(p)
    p.add_argument("--by", choices=["framework", "domain"], default="framework")
    p.set_defaults(fn=cmd_status)

    p = ssub.add_parser("plan", help="workstreams by domain, most-shared first"); common(p)
    p.add_argument("--top", type=int, metavar="N", help="show only the first N workstreams")
    p.add_argument("--min-frameworks", type=int, default=1, metavar="N",
                   help="only domains touched by at least N of the system's frameworks")
    p.add_argument("--format", choices=["text", "md"], default="text")
    p.add_argument("-o", "--output", help="write Markdown to this file (with --format md)")
    p.set_defaults(fn=cmd_plan)

    p = ssub.add_parser("export", help="Statement-of-Applicability style CSV or Markdown"); common(p)
    p.add_argument("--format", choices=["csv", "md"], default="csv")
    p.add_argument("-o", "--output")
    p.set_defaults(fn=cmd_export)

    p = ssub.add_parser("validate", help="check the scope file for problems"); common(p, system=False)
    p.set_defaults(fn=cmd_validate)
