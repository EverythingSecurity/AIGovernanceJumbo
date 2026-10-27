# SPDX-License-Identifier: Apache-2.0
"""Command-line interface: `aicontrols --help`."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import textwrap
from typing import List, Optional

from . import __version__
from . import cli_scope, cli_workflow
from .library import Control, Library, load
from .scope import ScopeError
from .wizard import WizardError

CSV_FIELDS = ["id", "framework_id", "ref", "title", "domain_id", "section", "c", "i", "a",
              "requirement", "security_note", "evidence"]


def _wrap(text: Optional[str], indent: str = "    ") -> str:
    return textwrap.fill(text or "-", width=96, initial_indent=indent, subsequent_indent=indent)


def _line(c: Control) -> str:
    return f"{c.id:<34} {c.cia}  {c.title[:70]}"


def _print_control(c: Control, lib: Library) -> None:
    fw, dom = lib.frameworks[c.framework_id], lib.domains[c.domain_id]
    print(f"{c.id}  [{fw.full_name}]")
    print(f"  {c.title}")
    print(f"  domain : {dom.name}")
    if c.section:
        print(f"  section: {c.section}")
    print(f"  CIA    : {c.cia}")
    print("  requirement:\n" + _wrap(c.requirement))
    if c.security_note:
        print("  security note:\n" + _wrap(c.security_note))
    if c.evidence:
        print("  evidence to verify:\n" + _wrap(c.evidence))
    for k, v in c.extras.items():
        print(f"  {k.replace('_', ' ')}:\n" + _wrap(v))


def cmd_frameworks(lib: Library, a) -> int:
    for f in lib.frameworks.values():
        print(f"{f.id:<14} {f.control_count:>4}  {f.full_name}")
    return 0


def cmd_domains(lib: Library, a) -> int:
    for d in sorted(lib.domains.values(), key=lambda d: d.name):
        print(f"{d.id[:48]:<48} {len(d.control_ids):>4}  {d.name}")
    return 0


def cmd_list(lib: Library, a) -> int:
    rows = lib.filter(framework=a.framework, domain=a.domain, cia=a.cia)
    for c in rows:
        print(_line(c))
    print(f"-- {len(rows)} controls", file=sys.stderr)
    return 0


def cmd_search(lib: Library, a) -> int:
    rows = lib.search(" ".join(a.query), framework=a.framework, limit=a.limit)
    for c in rows:
        print(_line(c))
    if not rows:
        print("no matches", file=sys.stderr)
        return 1
    return 0


def cmd_show(lib: Library, a) -> int:
    _print_control(lib.get(a.id), lib)
    return 0


def cmd_crosswalk(lib: Library, a) -> int:
    key = a.key
    if ":" in key and key in {c.id for c in lib.controls}:
        c = lib.get(key)
        dom = lib.domains[c.domain_id]
        print(f"{c.id}  {c.title}\ndomain: {dom.name}\n")
        if dom.consolidation_guidance:
            print("consolidation guidance:\n" + _wrap(dom.consolidation_guidance) + "\n")
        rows = lib.related(key)
    else:
        dom = lib.domain(key)
        print(f"domain: {dom.name}\n")
        if dom.description:
            print(_wrap(dom.description) + "\n")
        if dom.consolidation_guidance:
            print("consolidation guidance:\n" + _wrap(dom.consolidation_guidance) + "\n")
        rows = [lib.get(i) for i in dom.control_ids]
    for c in rows:
        print(_line(c))
    return 0


def cmd_export(lib: Library, a) -> int:
    rows = lib.filter(framework=a.framework, domain=a.domain, cia=a.cia, include_info=True)
    out = open(a.output, "w", encoding="utf-8", newline="") if a.output else sys.stdout
    try:
        if a.format == "json":
            json.dump([c.to_dict() for c in rows], out, indent=2, ensure_ascii=False)
            out.write("\n")
        else:
            w = csv.DictWriter(out, fieldnames=CSV_FIELDS)
            w.writeheader()
            for c in rows:
                d = c.to_dict()
                w.writerow({**{k: d.get(k) for k in CSV_FIELDS},
                            "c": int(c.c), "i": int(c.i), "a": int(c.a)})
    finally:
        if a.output:
            out.close()
    print(f"-- exported {len(rows)} rows", file=sys.stderr)
    return 0


def cmd_stats(lib: Library, a) -> int:
    s = lib.stats()
    print(f"dataset {s['dataset_version']}: {s['controls']} controls, "
          f"{len(s['frameworks'])} frameworks, {s['domains']} domains")
    print(f"CIA-marked: C={s['cia']['c']} I={s['cia']['i']} A={s['cia']['a']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aicontrols",
        description="Query cross-mapped AI governance and security controls.",
        epilog="Planning aid only; not legal or audit advice. Verify against the source standards.")
    p.add_argument("--version", action="version", version=f"aicontrols {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("frameworks", help="list frameworks").set_defaults(fn=cmd_frameworks)
    sub.add_parser("domains", help="list crosswalk domains").set_defaults(fn=cmd_domains)
    sub.add_parser("stats", help="dataset summary").set_defaults(fn=cmd_stats)

    def filters(sp):
        sp.add_argument("-f", "--framework", help="framework id or name, e.g. eu-ai-act")
        sp.add_argument("-d", "--domain", help="domain id or name (substring ok)")
        sp.add_argument("--cia", default="", metavar="CIA",
                        help="only controls marked for all of these, e.g. 'ci'")

    sp = sub.add_parser("list", help="list controls"); filters(sp); sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("search", help="search titles and text")
    sp.add_argument("query", nargs="+")
    sp.add_argument("-f", "--framework")
    sp.add_argument("-n", "--limit", type=int, default=20)
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("show", help="show one control by id, e.g. iso-27001:A.5.1")
    sp.add_argument("id"); sp.set_defaults(fn=cmd_show)

    sp = sub.add_parser("crosswalk", help="controls in other frameworks that cover the same ground")
    sp.add_argument("key", help="a control id or a domain id/name")
    sp.set_defaults(fn=cmd_crosswalk)

    sp = sub.add_parser("export", help="export controls as csv or json"); filters(sp)
    sp.add_argument("--format", choices=["csv", "json"], default="csv")
    sp.add_argument("-o", "--output", help="file to write (default: stdout)")
    sp.set_defaults(fn=cmd_export)

    cli_scope.add_parser(sub)
    cli_workflow.add_parser(sub)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(load(), args)
    except (KeyError, ScopeError, WizardError) as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
