# SPDX-License-Identifier: Apache-2.0
"""`aicontrols scope ...` commands: record and report an organisation's own decisions."""
from __future__ import annotations

import datetime
import json
import sys
import textwrap
from pathlib import Path

from .library import Library
from .scope import DEFAULT_FILE, DONE, STATUSES, Scope, ScopeError
from . import spreadsheet
from .wizard import LEVEL_TEXT, LEVELS, QUESTIONS, REGULATION_CAVEAT, WizardError, normalize, recommend, selection

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


def cmd_template(lib: Library, a) -> int:
    path = Path(a.file)
    scope = Scope.load(path, lib) if path.is_file() else None
    sid = a.system
    if not sid and scope and len(scope.systems()) == 1:
        sid = scope.systems()[0]["id"]
    if not sid:
        raise ScopeError("name the system with -s/--system (it becomes the system column)")
    known = next((s for s in (scope.systems() if scope else []) if s["id"] == sid), None)
    frameworks = [f.strip() for f in a.frameworks.split(",") if f.strip()] if a.frameworks else (known["frameworks"] if known else [])
    if not frameworks:
        raise ScopeError("choose the frameworks with --frameworks, e.g. iso-42001,gdpr")
    org = a.org or (scope.data["organization"] if scope else None) or "My organisation"
    text = spreadsheet.template_csv(lib, frameworks, org, sid, a.name or (known["name"] if known else sid), scope)
    if a.output:
        with open(a.output, "w", encoding="utf-8-sig", newline="") as fh:  # BOM: Excel then reads UTF-8
            fh.write(text)
        print(f"-- wrote {a.output} ({max(0, len(text.splitlines()) - 6)} controls); fill it in and import with: aicontrols scope import-csv", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def cmd_import_csv(lib: Library, a) -> int:
    text = Path(a.path).read_bytes().decode("utf-8-sig", errors="replace")
    path = Path(a.file)
    scope = Scope.load(path, lib) if path.is_file() else Scope.new(a.org or "", lib)  # a blank name is filled from the template
    res = spreadsheet.import_decisions(scope, text, a.system, a.org, create_system=True)
    for w in res["warnings"]:
        print("warning:", w)
    if res["errors"]:
        for e in res["errors"][:25]:
            print(f"error: row {e['row']}: {e['message']}" if e["row"] else f"error: {e['message']}")
        if len(res["errors"]) > 25:
            print(f"... and {len(res['errors']) - 25} more")
        print(f"nothing imported: fix the {len(res['errors'])} problem(s) and try again", file=sys.stderr)
        return 1
    scope.save(path)
    print(f"imported into {res['system']}{' (new system)' if res['created_system'] else ''}: "
          f"{res['applied']} control(s) updated, {res['skipped']} unchanged")
    return 0


def _is_tty() -> bool:
    return sys.stdin.isatty()


def _ask(q, index: int, total: int) -> str:
    letters = {}
    if len({c[0] for c in q.choices}) == len(q.choices):
        letters = {c[0]: c for c in q.choices}
    print(f"\n[{index}/{total}] {q.text}")
    while True:
        try:
            raw = input(f"      {' / '.join(q.choices)} [unsure, ? for help]: ").strip().lower()
        except EOFError:
            raise WizardError("input ended before all questions were answered") from None
        if raw == "?":
            print(textwrap.fill(q.help or "No extra help for this question.", 90,
                                initial_indent="      ", subsequent_indent="      "))
            continue
        if raw == "":
            return "unsure"
        raw = letters.get(raw, raw)
        if raw in q.choices:
            return raw
        print("      please answer one of: " + ", ".join(q.choices))


def _confirm(text: str) -> bool:
    try:
        return input(f"\n{text} [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _gather(a) -> tuple:
    """Return (answers, interactive). Non-interactive runs treat unanswered questions as unsure."""
    raw = {}
    if a.answers:
        try:
            data = json.loads(Path(a.answers).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise WizardError(f"cannot read answers file {a.answers}: {e}") from None
        if not isinstance(data, dict):
            raise WizardError("answers file must be a JSON object of question id -> answer")
        raw.update(data)
    for item in a.answer or []:
        if "=" not in item:
            raise WizardError(f"--answer expects question=value, got {item!r}")
        key, value = item.split("=", 1)
        raw[key.strip()] = value
    if raw:
        return raw, False
    if not _is_tty():
        raise WizardError("no answers given and input is not interactive; use --answers FILE "
                          "or --answer question=value")
    print("Answer a few questions about the AI system. Press Enter for 'unsure'. "
          "This is a planning aid, not legal advice.")
    return {q.id: _ask(q, i, len(QUESTIONS)) for i, q in enumerate(QUESTIONS, 1)}, True


def _print_recs(recs, name: str) -> None:
    print(f"\nSuggested frameworks for {name}")
    print("(planning aid based on your answers, not legal advice)")
    for level in LEVELS:
        group = [r for r in recs if r.level == level]
        if not group:
            continue
        print(f"\n{LEVEL_TEXT[level].upper()} ({len(group)})")
        for r in group:
            print(f"  {r.name:<30} {r.controls:>4} controls   [{r.kind}]")
            for reason in r.reasons:
                print(textwrap.fill(reason, 96, initial_indent="      - ", subsequent_indent="        "))
    if any(r.caveat for r in recs):
        print("\n! " + REGULATION_CAVEAT)


def cmd_wizard(lib: Library, a) -> int:
    raw, interactive = _gather(a)
    answers = normalize(raw)
    skipped = [q.id for q in QUESTIONS if q.id not in raw]
    recs = recommend(answers, lib)
    chosen = selection(recs, a.include)

    if a.json:
        print(json.dumps({"answers": answers, "selected": chosen,
                          "recommendations": [r.to_dict() for r in recs]}, indent=2))
    else:
        _print_recs(recs, a.name or a.create or "this system")
        if skipped and not interactive:
            print(f"\nNot answered (treated as unsure): {', '.join(skipped)}")
        n_controls = sum(r.controls for r in recs if r.framework_id in chosen)
        print(f"\nSelected for scope ({a.include}): {', '.join(chosen) or 'none'} "
              f"- {n_controls} controls")

    create, name = a.create, a.name
    if not create and interactive and not a.json and _confirm("Create a system in your scope file from these?"):
        create = input("System id (letters, digits, - or _): ").strip()
        name = input("Display name: ").strip() or create
        if a.include == "recommended" and _confirm("Also include the 'worth considering' frameworks?"):
            a.include = "consider"
            chosen = selection(recs, "consider")
    if create:
        scope = _load(lib, a)
        scoping = {"date": datetime.date.today().isoformat(), "answers": answers,
                   "include_level": a.include, "included": chosen,
                   "note": "Suggested by aicontrols scope wizard; a planning aid, not a legal determination."}
        system = scope.add_system(create, name or create, chosen, a.description or "", scoping=scoping)
        scope.save(a.file)
        print(f"\nadded system {system['id']} with {len(chosen)} frameworks "
              f"({len(scope.in_scope(create))} controls); the answers are recorded in the scope file")
    elif not a.json:
        print("\nTo create the system from these:  aicontrols scope wizard --answers <file> "
              "--create <system-id> --name \"<name>\"")
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

    p = ssub.add_parser("wizard", help="answer questions; get suggested frameworks for a system")
    common(p, system=False)
    p.add_argument("--answers", metavar="FILE", help="JSON file of question id -> answer")
    p.add_argument("--answer", action="append", metavar="Q=VALUE", help="a single answer (repeatable)")
    p.add_argument("--create", metavar="SYSTEM_ID", help="add a system with the suggested frameworks")
    p.add_argument("--name", help="display name for the system")
    p.add_argument("--description")
    p.add_argument("--include", choices=["recommended", "consider"], default="recommended",
                   help="which tiers go into scope (default: recommended only)")
    p.add_argument("--json", action="store_true", help="print machine-readable output")
    p.set_defaults(fn=cmd_wizard)

    p = ssub.add_parser("template", help="write a fill-in spreadsheet (CSV) of controls and decisions")
    common(p)
    p.add_argument("--frameworks", help="comma-separated; default: the system's own frameworks")
    p.add_argument("--org"); p.add_argument("--name", help="display name for the system")
    p.add_argument("-o", "--output")
    p.set_defaults(fn=cmd_template)

    p = ssub.add_parser("import-csv", help="import a filled-in spreadsheet (all or nothing)")
    common(p)
    p.add_argument("path"); p.add_argument("--org", help="organisation name (only used when creating a new scope file)")
    p.set_defaults(fn=cmd_import_csv)

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
