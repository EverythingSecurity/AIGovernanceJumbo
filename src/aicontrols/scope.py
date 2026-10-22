# SPDX-License-Identifier: Apache-2.0
"""Scope file: an organisation's own decisions layered on the read-only dataset.

The public dataset says what the frameworks ask for. A scope file records what *you*
decided: which AI systems exist, which frameworks apply to each, whether each control
applies (with a justification), who owns it, and how far along it is. It is plain JSON,
holds no dataset text, and should stay in your own private repository.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .library import Control, Library

DEFAULT_FILE = "aicontrols-scope.json"
SCHEMA_VERSION = "1.0"
STATUSES = ("not_started", "in_progress", "implemented", "verified")
DONE = ("implemented", "verified")
FIELDS = ("applicable", "justification", "owner", "status", "due", "reviewed", "notes")
SOA_COLUMNS = ["system", "control_id", "framework_id", "ref", "title", "domain", "c", "i", "a",
               "applicable", "justification", "status", "owner", "due", "reviewed", "updated",
               "evidence", "notes"]


class ScopeError(ValueError):
    """Raised for invalid scope operations; the message is safe to show to users."""


def _today() -> str:
    return _dt.date.today().isoformat()


def _check_date(value: Optional[str], name: str) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        _dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ScopeError(f"{name} must be a date like 2026-12-31, got {value!r}") from None
    return value


class Scope:
    def __init__(self, data: dict, lib: Library):
        self.data = data
        self.lib = lib

    # ---- creation / persistence -------------------------------------------
    @classmethod
    def new(cls, organization: str, lib: Library) -> "Scope":
        return cls({"schema_version": SCHEMA_VERSION, "dataset_version": lib.dataset_version,
                    "organization": organization, "created": _today(),
                    "systems": [], "decisions": {}}, lib)

    @classmethod
    def load(cls, path, lib: Library) -> "Scope":
        p = Path(path)
        if not p.is_file():
            raise ScopeError(f"no scope file at {p}; create one with: aicontrols scope init")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ScopeError(f"{p} is not valid JSON: {e}") from None
        for key in ("systems", "decisions"):
            data.setdefault(key, [] if key == "systems" else {})
        return cls(data, lib)

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")

    # ---- systems ---------------------------------------------------------
    def systems(self) -> List[dict]:
        return self.data["systems"]

    def system(self, system_id: Optional[str]) -> dict:
        systems = self.systems()
        if system_id is None:
            if len(systems) == 1:
                return systems[0]
            raise ScopeError("several systems exist; choose one with -s/--system")
        for s in systems:
            if s["id"] == system_id:
                return s
        known = ", ".join(s["id"] for s in systems) or "none yet"
        raise ScopeError(f"unknown system {system_id!r} (known: {known})")

    def add_system(self, system_id: str, name: str, frameworks: Iterable[str],
                   description: str = "") -> dict:
        if any(s["id"] == system_id for s in self.systems()):
            raise ScopeError(f"system {system_id!r} already exists")
        if not system_id or not all(ch.isalnum() or ch in "-_" for ch in system_id):
            raise ScopeError("system id may contain only letters, digits, '-' and '_'")
        fw_ids = []
        for key in frameworks:
            try:
                fid = self.lib.framework(key).id
            except KeyError as e:
                raise ScopeError(e.args[0]) from None
            if fid not in fw_ids:
                fw_ids.append(fid)
        if not fw_ids:
            raise ScopeError("a system needs at least one framework")
        system = {"id": system_id, "name": name, "description": description, "frameworks": fw_ids}
        self.systems().append(system)
        return system

    def in_scope(self, system_id: Optional[str]) -> List[Control]:
        """Baseline scope: every real control of the system's chosen frameworks."""
        fw = set(self.system(system_id)["frameworks"])
        return [c for c in self.lib.controls if c.framework_id in fw and c.kind == "control"]

    # ---- decisions -------------------------------------------------------
    def decision(self, system_id: str, control_id: str) -> dict:
        """Stored decision merged over defaults (applicable, not_started)."""
        stored = self.data["decisions"].get(system_id, {}).get(control_id, {})
        out = {"applicable": True, "justification": "", "owner": None, "status": "not_started",
               "due": None, "reviewed": None, "updated": None, "evidence": [], "notes": ""}
        out.update(stored)
        return out

    def select(self, system_id: Optional[str], control_ids: Iterable[str] = (),
               domain: Optional[str] = None, framework: Optional[str] = None) -> List[Control]:
        """Controls an update applies to: explicit ids and/or a domain/framework selector."""
        base = {c.id: c for c in self.in_scope(system_id)}
        chosen: Dict[str, Control] = {}
        for cid in control_ids:
            if cid not in base:
                if cid in {c.id for c in self.lib.controls}:
                    raise ScopeError(f"{cid} is not in scope for this system "
                                     "(its framework is not selected)")
                raise ScopeError(f"unknown control id {cid!r}")
            chosen[cid] = base[cid]
        if domain or framework:
            try:
                did = self.lib.domain(domain).id if domain else None
                fid = self.lib.framework(framework).id if framework else None
            except KeyError as e:
                raise ScopeError(e.args[0]) from None
            for c in base.values():
                if (did is None or c.domain_id == did) and (fid is None or c.framework_id == fid):
                    chosen[c.id] = c
        if not chosen:
            raise ScopeError("nothing selected: give control ids, --domain or --framework")
        return list(chosen.values())

    def set(self, system_id: Optional[str], controls: List[Control], **changes) -> int:
        """Apply changes to the chosen controls. `evidence` is appended, not replaced."""
        system = self.system(system_id)["id"]
        unknown = set(changes) - set(FIELDS) - {"evidence"}
        if unknown:
            raise ScopeError(f"unknown fields: {sorted(unknown)}")
        if changes.get("status") is not None and changes["status"] not in STATUSES:
            raise ScopeError(f"status must be one of {', '.join(STATUSES)}")
        for k in ("due", "reviewed"):
            if k in changes:
                changes[k] = _check_date(changes[k], k)
        if changes.get("applicable") is False and not (changes.get("justification") or "").strip():
            missing = [c.id for c in controls
                       if not self.decision(system, c.id)["justification"].strip()]
            if missing:
                raise ScopeError("marking a control not applicable needs --justification "
                                 f"(missing for {len(missing)} control(s), e.g. {missing[0]})")
        table = self.data["decisions"].setdefault(system, {})
        for c in controls:
            rec = table.setdefault(c.id, {})
            for k, v in changes.items():
                if k == "evidence":
                    ev = rec.setdefault("evidence", [])
                    for item in v or []:
                        if item not in ev:
                            ev.append(item)
                elif v is not None:
                    rec[k] = v
            rec["updated"] = _today()
        return len(controls)

    # ---- reporting -------------------------------------------------------
    def rows(self, system_id: Optional[str]) -> List[Tuple[Control, dict]]:
        sid = self.system(system_id)["id"]
        return [(c, self.decision(sid, c.id)) for c in self.in_scope(sid)]

    @staticmethod
    def _tally(items: List[Tuple[Control, dict]]) -> dict:
        t = {"total": len(items), "applicable": 0, "not_applicable": 0,
             **{s: 0 for s in STATUSES}}
        for _c, d in items:
            if not d["applicable"]:
                t["not_applicable"] += 1
                continue
            t["applicable"] += 1
            t[d["status"]] += 1
        done = t["implemented"] + t["verified"]
        t["percent"] = round(100 * done / t["applicable"], 1) if t["applicable"] else None
        return t

    def status(self, system_id: Optional[str], by: str = "framework") -> List[dict]:
        """Completion roll-up by 'framework' or 'domain' (done = implemented + verified)."""
        groups: Dict[str, List[Tuple[Control, dict]]] = {}
        for c, d in self.rows(system_id):
            groups.setdefault(c.framework_id if by == "framework" else c.domain_id, []).append((c, d))
        out = []
        for key, items in groups.items():
            label = (self.lib.frameworks[key].name if by == "framework" else self.lib.domains[key].name)
            out.append({"key": key, "label": label, **self._tally(items)})
        return sorted(out, key=lambda r: r["label"].lower())

    def overall(self, system_id: Optional[str]) -> dict:
        return self._tally(self.rows(system_id))

    def plan(self, system_id: Optional[str]) -> List[dict]:
        """Workstreams: one per domain, biggest and most-shared first."""
        groups: Dict[str, List[Tuple[Control, dict]]] = {}
        for c, d in self.rows(system_id):
            groups.setdefault(c.domain_id, []).append((c, d))
        out = []
        for did, items in groups.items():
            owners = sorted({d["owner"] for _c, d in items if d["owner"]})
            out.append({"domain_id": did, "domain": self.lib.domains[did].name,
                        "frameworks": len({c.framework_id for c, _d in items}),
                        "owners": owners, **self._tally(items)})
        return sorted(out, key=lambda r: (-r["frameworks"], -r["total"], r["domain"]))

    def related_open(self, system_id: Optional[str], control: Control) -> List[Control]:
        """In-scope controls elsewhere in the same domain that are applicable and not done.

        Used only to prompt a human review; nothing is ever updated automatically.
        """
        sid = self.system(system_id)["id"]
        scope_ids = {c.id for c in self.in_scope(sid)}
        out = []
        for c in self.lib.related(control.id):
            d = self.decision(sid, c.id)
            if c.id in scope_ids and d["applicable"] and d["status"] not in DONE:
                out.append(c)
        return out

    def soa_rows(self, system_id: Optional[str]) -> List[dict]:
        sid = self.system(system_id)["id"]
        out = []
        for c, d in self.rows(sid):
            out.append({
                "system": sid, "control_id": c.id, "framework_id": c.framework_id, "ref": c.ref,
                "title": c.title, "domain": self.lib.domains[c.domain_id].name,
                "c": int(c.c), "i": int(c.i), "a": int(c.a),
                "applicable": "yes" if d["applicable"] else "no",
                "justification": d["justification"], "status": d["status"], "owner": d["owner"] or "",
                "due": d["due"] or "", "reviewed": d["reviewed"] or "", "updated": d["updated"] or "",
                "evidence": "; ".join(d["evidence"]), "notes": d["notes"],
            })
        return out

    def write_soa(self, system_id: Optional[str], out) -> int:
        rows = self.soa_rows(system_id)
        w = csv.DictWriter(out, fieldnames=SOA_COLUMNS)
        w.writeheader()
        w.writerows(rows)
        return len(rows)

    # ---- validation ------------------------------------------------------
    def validate(self) -> Tuple[List[str], List[str]]:
        """Return (errors, warnings). Errors mean the file is inconsistent."""
        errors: List[str] = []
        warnings: List[str] = []
        d = self.data
        if d.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
        if d.get("dataset_version") != self.lib.dataset_version:
            warnings.append(f"scope was created against dataset {d.get('dataset_version')}, "
                            f"installed dataset is {self.lib.dataset_version}; re-check decisions")
        ids = [s.get("id") for s in d["systems"]]
        if len(ids) != len(set(ids)):
            errors.append("duplicate system ids")
        known_fw = set(self.lib.frameworks)
        for s in d["systems"]:
            for f in s.get("frameworks", []):
                if f not in known_fw:
                    errors.append(f"system {s.get('id')}: unknown framework {f!r}")
        all_ids = {c.id for c in self.lib.controls}
        for sid, table in d["decisions"].items():
            if sid not in ids:
                errors.append(f"decisions for unknown system {sid!r}")
                continue
            scope_ids = {c.id for c in self.in_scope(sid)}
            for cid, rec in table.items():
                where = f"{sid}/{cid}"
                if cid not in all_ids:
                    errors.append(f"{where}: unknown control id")
                    continue
                if cid not in scope_ids:
                    errors.append(f"{where}: control's framework is not selected for this system")
                if rec.get("status", "not_started") not in STATUSES:
                    errors.append(f"{where}: invalid status {rec.get('status')!r}")
                if rec.get("applicable") is False and not str(rec.get("justification", "")).strip():
                    errors.append(f"{where}: not applicable without a justification")
                for k in ("due", "reviewed", "updated"):
                    try:
                        _check_date(rec.get(k), k)
                    except ScopeError as e:
                        errors.append(f"{where}: {e}")
                if rec.get("applicable") is False and rec.get("status", "not_started") != "not_started":
                    warnings.append(f"{where}: marked not applicable but has status {rec['status']}")
        return errors, warnings
