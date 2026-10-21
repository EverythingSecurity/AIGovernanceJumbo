#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate data/*.json against schema/*.schema.json and check cross-file integrity.

Usage:  python tools/validate.py          (needs: pip install jsonschema)
Exit status is non-zero if anything fails, so it can gate CI.
"""
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit("jsonschema is required: pip install jsonschema")

ROOT = Path(__file__).resolve().parent.parent
FILES = ("controls", "frameworks", "domains")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def schema_errors(name, doc):
    validator = Draft202012Validator(load(ROOT / "schema" / f"{name}.schema.json"))
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        yield f"{name}.json: {where}: {err.message[:200]}"


def integrity_errors(docs):
    controls = docs["controls"]["controls"]
    fw_ids = {f["id"] for f in docs["frameworks"]["frameworks"]}
    dom_ids = {d["id"] for d in docs["domains"]["domains"]}
    ids = [c["id"] for c in controls]
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        yield f"duplicate control ids: {dup}"
    id_set = set(ids)
    for c in controls:
        if c["framework_id"] not in fw_ids:
            yield f"{c['id']}: unknown framework_id {c['framework_id']!r}"
        if c["domain_id"] not in dom_ids:
            yield f"{c['id']}: unknown domain_id {c['domain_id']!r}"
        if c["id"] != f"{c['framework_id']}:{c['ref'].replace(' ', '-')}":
            yield f"{c['id']}: id does not match framework_id + ref"
    by_domain = {}
    for c in controls:
        by_domain.setdefault(c["domain_id"], set()).add(c["id"])
    for d in docs["domains"]["domains"]:
        missing = set(d["control_ids"]) - id_set
        if missing:
            yield f"domain {d['id']}: unknown control ids {sorted(missing)[:3]}"
        if set(d["control_ids"]) != by_domain.get(d["id"], set()):
            yield f"domain {d['id']}: control_ids disagree with controls.json"
    counts = {}
    for c in controls:
        counts[c["framework_id"]] = counts.get(c["framework_id"], 0) + 1
    for f in docs["frameworks"]["frameworks"]:
        if f["control_count"] != counts.get(f["id"], 0):
            yield (f"framework {f['id']}: control_count {f['control_count']} "
                   f"!= actual {counts.get(f['id'], 0)}")
    versions = {d["dataset_version"] for d in docs.values()}
    if len(versions) != 1:
        yield f"dataset_version differs between files: {sorted(versions)}"


def main():
    docs = {n: load(ROOT / "data" / f"{n}.json") for n in FILES}
    problems = [e for n in FILES for e in schema_errors(n, docs[n])]
    if not problems:  # integrity checks assume the shape is valid
        problems = list(integrity_errors(docs))
    for p in problems:
        print("FAIL", p)
    if problems:
        print(f"{len(problems)} problem(s)")
        return 1
    n = len(docs["controls"]["controls"])
    print(f"OK: {n} controls, {len(docs['frameworks']['frameworks'])} frameworks, "
          f"{len(docs['domains']['domains'])} domains")
    return 0


if __name__ == "__main__":
    sys.exit(main())
