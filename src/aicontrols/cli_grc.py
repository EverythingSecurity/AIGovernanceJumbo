# SPDX-License-Identifier: Apache-2.0
"""`aicontrols grc ...`: the GRC management layer (registers, mapping matrix, coverage, KPIs, lifecycle)."""
from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path

from .grc import Grc, GrcError, ISSUE_TEXT, load_spec
from .library import Library
from .scope import DEFAULT_FILE, Scope


def _actor(a) -> str:
    return (getattr(a, "by", None) or os.environ.get("AICONTROLS_ACTOR") or getpass.getuser() or "").strip()


def _open(lib: Library, a):
    scope = Scope.load(a.file, lib)
    return scope, Grc(scope)


def _flag(name: str) -> str:
    return "--" + name.replace("_", "-")


def _fmt(v, unit: str = "") -> str:
    return "no data" if v is None else f"{v}{unit}"


# ---- registers ---------------------------------------------------------------------------------------
def _field_values(spec: dict, a) -> dict:
    return {f["name"]: getattr(a, f["name"]) for f in spec["fields"] if getattr(a, f["name"], None) is not None}


def cmd_init(lib, a) -> int:
    scope, g = _open(lib, a)
    n = g.seed_evidence_sources(_actor(a))
    scope.save(a.file)
    print(f"GRC layer enabled; {n} evidence source(s) added from the framework notes "
          "(access reviews, scanners, SIEM, CI/CD, policy attestations). Edit them with: aicontrols grc evidence-sources")
    return 0


def make_register_commands(reg: str, spec: dict):
    def add(lib, a):
        scope, g = _open(lib, a)
        rec = g.add(reg, _actor(a), **_field_values(spec, a))
        scope.save(a.file)
        print(f"added {rec['id']}")
        return 0

    def lst(lib, a):
        scope, g = _open(lib, a)
        rows = g.records(reg)
        cols = [f["name"] for f in spec["fields"]][:5]
        for r in rows:
            print(f"{r['id']:<9} " + " | ".join(str(r.get(c, "")) for c in cols))
        print(f"-- {len(rows)} {spec['singular']}(s)", file=sys.stderr)
        return 0

    def setf(lib, a):
        scope, g = _open(lib, a)
        values = _field_values(spec, a)
        if not values:
            raise GrcError("nothing to change: give at least one field option")
        g.update(reg, _actor(a), a.id, **values)
        scope.save(a.file)
        print(f"updated {a.id}")
        return 0

    def rm(lib, a):
        scope, g = _open(lib, a)
        g.remove(reg, _actor(a), a.id)
        scope.save(a.file)
        print(f"removed {a.id}")
        return 0

    return add, lst, setf, rm


# ---- links, statements, reviews, roles, settings ---------------------------------------------------------
def cmd_link(lib, a) -> int:
    scope, g = _open(lib, a)
    g.link(a.system, _actor(a), a.cc, a.policy or [], a.guideline or [], a.sop or [], a.evidence_source or [], a.unlink)
    scope.save(a.file)
    print(f"{'unlinked from' if a.unlink else 'linked to'} {a.cc}")
    return 0


def cmd_scope_statement(lib, a) -> int:
    scope, g = _open(lib, a)
    g.set_scope_statement(_actor(a), a.framework, a.statement, a.reviewed)
    scope.save(a.file)
    print(f"scope statement recorded for {a.framework}")
    return 0


def cmd_scope_review(lib, a) -> int:
    scope, g = _open(lib, a)
    d = g.review_scope(_actor(a), a.date)
    scope.save(a.file)
    print(f"scope marked as reviewed on {d}")
    return 0


def cmd_mapping_review(lib, a) -> int:
    scope, g = _open(lib, a)
    n = g.review_mappings(a.system, _actor(a), a.cc, a.owner, a.date)
    scope.save(a.file)
    print(f"{n} mapping(s) of {a.cc} reviewed, owner {a.owner}")
    return 0


def cmd_roles(lib, a) -> int:
    scope, g = _open(lib, a)
    if a.role:
        people = g.set_roles(_actor(a), a.role, a.name or [])
        scope.save(a.file)
        print(f"{a.role}: {', '.join(people) or '(nobody)'}")
        return 0
    for r in g.roles():
        print(f"{r['id']:<22} {r['name']:<24} {', '.join(r['people']) or '-':<28} {r['responsibility']}")
    return 0


def cmd_settings(lib, a) -> int:
    scope, g = _open(lib, a)
    if a.assignment:
        if "=" not in a.assignment:
            raise GrcError("use KEY=VALUE, e.g. anchor_framework=iso-42001 or coverage_target.dora=70")
        k, v = a.assignment.split("=", 1)
        g.set_setting(_actor(a), k.strip(), v.strip())
        scope.save(a.file)
        print(f"{k.strip()} set (recorded in the audit trail)")
    print(json.dumps(g.settings(), indent=2))
    return 0


# ---- computed views --------------------------------------------------------------------------------------------
def cmd_matrix(lib, a) -> int:
    scope, g = _open(lib, a)
    if a.format == "csv":
        text = g.matrix_csv(a.system)
        if a.output:
            with open(a.output, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write(text)
            print(f"-- wrote {a.output}", file=sys.stderr)
        else:
            sys.stdout.write(text)
        return 0
    rows = g.matrix(a.system)
    summary = g.matrix_summary(rows)
    print(f"{summary['requirements']} requirements: " + ", ".join(f"{k} {v}" for k, v in summary["by_status"].items()))
    if summary["by_issue"]:
        print("issues: " + "; ".join(f"{ISSUE_TEXT[k]} ({v})" for k, v in summary["by_issue"].items()))
    print()
    for r in rows[:a.limit]:
        ctl = r["control_id"] or ("GAP" if r["gap_reason"] else "-")
        docs = f"policy {','.join(r['policy']) or '-'} | sop {','.join(r['sop']) or '-'} | evidence {r['evidence'] or '-'}"
        print(f"{r['status']:<12} {ctl:<8} {r['requirement_id']:<30} {r['requirement'][:44]:<44} {docs}")
    if len(rows) > a.limit:
        print(f"... {len(rows) - a.limit} more rows; use --format csv for all")
    return 0


def cmd_coverage(lib, a) -> int:
    scope, g = _open(lib, a)
    cov = g.coverage(a.system)
    if a.json:
        print(json.dumps(cov, indent=2))
        return 0
    print("coverage % = requirements implemented AND evidenced / applicable requirements\n"
          f"incremental % = covered through a control that also serves the anchor framework ({cov['anchor'] or 'none set'})\n")
    print(f"{'framework':<26} {'reqs':>5} {'mapped':>6} {'impl.':>5} {'covered':>7} {'coverage':>9} {'increm.':>8} {'target':>7}")
    for f in cov["frameworks"]:
        inc = "n/a" if f["incremental_pct"] is None else _fmt(f["incremental_pct"], "%")
        tgt = "-" if f["target"] is None else f"{f['target']}%" + ("" if f["meets_target"] else " (below)")
        print(f"{f['name'][:26]:<26} {f['required']:>5} {f['mapped']:>6} {f['implemented']:>5} {f['covered']:>7} {_fmt(f['coverage_pct'], '%'):>9} {inc:>8} {tgt:>7}")
    o = cov["overall"]
    print(f"{'OVERALL':<26} {o['required']:>5} {'':>6} {'':>5} {o['covered']:>7} {_fmt(o['coverage_pct'], '%'):>9}")
    return 0


def cmd_kpis(lib, a) -> int:
    scope, g = _open(lib, a)
    ks = g.kpis(a.system)
    if a.json:
        print(json.dumps(ks, indent=2))
        return 0
    mark = {"met": "OK  ", "not_met": "MISS", "no_data": "n/a ", "info": "info"}
    for k in ks:
        print(f"[{mark[k['status']]}] {k['type']}  {k['name']:<48} {_fmt(k['value'], k['unit']):>9}  target {k['target_text']}")
        print(f"         {k['detail']}")
    return 0


def cmd_streams(lib, a) -> int:
    scope, g = _open(lib, a)
    rows = g.streams(a.system)
    if not any(r["requirements"] for r in rows):
        print("no ISO/IEC 42001 requirements in scope for this system")
        return 0
    print(f"{'stream':<20} {'reqs':>5} {'mapped':>8} {'implemented':>12} {'covered':>8}  delivered through")
    for r in rows:
        print(f"{r['name']:<20} {r['requirements']:>5} {_fmt(r['mapped_pct'], '%'):>8} {_fmt(r['implemented_pct'], '%'):>12} {_fmt(r['coverage_pct'], '%'):>8}  {r['delivered_through']}")
    return 0


def cmd_lifecycle(lib, a) -> int:
    scope, g = _open(lib, a)
    steps = g.lifecycle(a.system)
    nxt = next((s for s in steps if not s["done"]), None)
    for s in steps:
        print(f"{s['n']:>2}. [{'x' if s['done'] else ' '}] {s['title']}\n        {s['detail']}")
    if nxt:
        print(f"\nnext: step {nxt['n']}. {nxt['hint']}")
    return 0


def cmd_artifacts(lib, a) -> int:
    scope, g = _open(lib, a)
    for x in g.artifacts(a.system):
        print(f"{x['status']:<8} {x['title']:<46} {x['detail']}")
    return 0


def cmd_report(lib, a) -> int:
    scope, g = _open(lib, a)
    text = json.dumps(g.report(a.system, _actor(a), record=True), indent=2) + "\n" if a.format == "json" \
        else g.report_markdown(a.system, _actor(a), record=True)
    scope.save(a.file)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print(f"-- wrote {a.output}", file=sys.stderr)
    else:
        print(text)
    return 0


def cmd_spec_items(lib, a) -> int:
    for it in load_spec()["open_items"]:
        print(f"{it['n']}. {it['text']}\n   handled: {it['handled']}")
    return 0


# ---- parser -------------------------------------------------------------------------------------------------------
def add_parser(sub) -> None:
    spec = load_spec()
    gp = sub.add_parser("grc", help="GRC management: registers, mapping matrix, coverage, KPIs/KRIs, lifecycle")
    g = gp.add_subparsers(dest="grc_command", required=True)

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

    add(g, "init", cmd_init, "enable the GRC layer and seed the evidence sources", system=False)

    for reg, rspec in spec["registers"].items():
        rp = g.add_parser(reg.replace("_", "-"), help=rspec["title"].lower())
        rs = rp.add_subparsers(dest="register_command", required=True)
        fn_add, fn_list, fn_set, fn_rm = make_register_commands(reg, rspec)
        for verb, fn, help_ in (("add", fn_add, f"add a {rspec['singular']}"), ("set", fn_set, f"change a {rspec['singular']}")):
            p = add(rs, verb, fn, help_, system=False)
            if verb == "set":
                p.add_argument("id")
            for f in rspec["fields"]:
                kw = {"help": f["label"] + (" (required)" if f.get("required") and verb == "add" else "")}
                if f["kind"] == "enum":
                    kw["choices"] = f["values"]
                    kw["help"] += ": " + ", ".join(f["values"])
                p.add_argument(_flag(f["name"]), dest=f["name"], **kw)
        add(rs, "list", fn_list, f"list {rspec['singular']}s", system=False, actor=False)
        p = add(rs, "remove", fn_rm, f"remove a {rspec['singular']}", system=False)
        p.add_argument("id")

    p = add(g, "link", cmd_link, "attach policies, guidelines, SOPs and evidence sources to a common control")
    p.add_argument("cc")
    p.add_argument("--policy", action="append"); p.add_argument("--guideline", action="append"); p.add_argument("--sop", action="append")
    p.add_argument("--evidence-source", action="append"); p.add_argument("--unlink", action="store_true")
    p = add(g, "scope-statement", cmd_scope_statement, "record the scope statement for a framework", system=False)
    p.add_argument("framework"); p.add_argument("--statement", required=True); p.add_argument("--reviewed", help="YYYY-MM-DD (default: today)")
    p = add(g, "scope-review", cmd_scope_review, "mark the scope register as reviewed", system=False)
    p.add_argument("--date", help="YYYY-MM-DD (default: today)")
    p = add(g, "mapping-review", cmd_mapping_review, "record the owner and review date of a control's mappings")
    p.add_argument("cc"); p.add_argument("--owner", required=True); p.add_argument("--date")
    p = add(g, "roles", cmd_roles, "list roles, or assign people to one", system=False)
    p.add_argument("role", nargs="?"); p.add_argument("--name", action="append", help="person (repeatable); none clears the role")
    p = add(g, "settings", cmd_settings, "show or change GRC settings", system=False)
    p.add_argument("assignment", nargs="?", help="KEY=VALUE, e.g. anchor_framework=iso-42001, coverage_target.dora=70")
    p = add(g, "matrix", cmd_matrix, "requirement-to-control mapping matrix", actor=False)
    p.add_argument("--format", choices=["text", "csv"], default="text"); p.add_argument("-o", "--output"); p.add_argument("-n", "--limit", type=int, default=40)
    p = add(g, "coverage", cmd_coverage, "coverage per framework and overall", actor=False); p.add_argument("--json", action="store_true")
    p = add(g, "kpis", cmd_kpis, "KPIs and KRIs against their targets", actor=False); p.add_argument("--json", action="store_true")
    add(g, "streams", cmd_streams, "ISO/IEC 42001 streams", actor=False)
    add(g, "lifecycle", cmd_lifecycle, "the ten lifecycle steps, judged from your data", actor=False)
    add(g, "artifacts", cmd_artifacts, "the artifacts checklist", actor=False)
    p = add(g, "report", cmd_report, "GRC report (Markdown or JSON)")
    p.add_argument("--format", choices=["md", "json"], default="md"); p.add_argument("-o", "--output")
    add(g, "open-items", cmd_spec_items, "items from the source notes that were unconfirmed, and how they are handled", system=False, actor=False)
