# SPDX-License-Identifier: Apache-2.0
"""Governance workflow layer: a six-stage control-management lifecycle on top of a scope file.

Implements the stage model in `workflow_spec.json` (see governance-workflow-v2.md):

    FRAMEWORK_SCOPING -> CONTROL_HARMONIZATION -> CONTROL_TAILORING ->
    CONTINUOUS_MONITORING -> EXCEPTION_GOVERNANCE -> TARGET_GAP_ANALYSIS

State lives in the same private scope file as the scoping decisions, under `workflow` (per
system) and `audit` (one hash-chained event log). Everything here is local and file-based.

Honest limits, stated once:
  * Roles and actor names are labels you supply. Nothing authenticates them, so segregation
    of duties is checked by name, not enforced by identity.
  * The audit trail is tamper-EVIDENT (a hash chain you can verify), not immutable: whoever
    holds the file can rewrite all of it. Keep the file in version control or anchor the
    latest hash elsewhere if you need stronger guarantees.
  * "Continuous monitoring" ingests test results and metrics from a file you (or a script)
    produce. There are no connectors to cloud, IAM or ERP systems.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .library import Control, Library
from .scope import DONE, STATUSES, Scope, ScopeError

SPEC_FILE = Path(__file__).with_name("workflow_spec.json")
WORKFLOW_SCHEMA_VERSION = "1.1"

ROLE_EXECUTIVE = "EXECUTIVE_APPROVER"
ROLE_SECOND_LINE = "SECOND_LINE_RISK_MANAGER"
ROLE_CCM = "AUTOMATED_CCM_ENGINE"
RATINGS = ("low", "medium", "high", "critical")
RANK = {s: i for i, s in enumerate(STATUSES)}
FREQUENCIES = {"daily": 1, "weekly": 7, "monthly": 31, "quarterly": 92, "annual": 366}
TEST_TYPES = ("manual", "automated", "rcsa")
EXCEPTION_TYPES = ("waiver", "delayed_remediation", "deviation")
RESULTS = ("pass", "fail", "error")
RISK_APPETITES = ("low", "moderate", "high")
OPS = (">", ">=", "<", "<=")
EXCEPTION_OPEN = ("requested", "assessed")

DEFAULT_POLICY = {
    "separation_of_duties": True,
    "executive_approval_from": "medium",
    "exception_max_days": {"low": 365, "medium": 180, "high": 90, "critical": 30},
    "reassess_warning_days": 14,
    "effectiveness_window": 5,
    "effective_threshold": 0.9,
    "partial_threshold": 0.6,
    "stale_factor": 1.5,
}

# Actions that are attestations (a person confirms they did the work). Every other action is
# satisfied by evidence in the file and cannot be ticked by hand.
ATTESTED = ("RATIONALIZE_NON_APPLICABLE_OBLIGATIONS", "DEDUPLICATE_OVERLAPPING_REQUIREMENTS")


class WorkflowError(ScopeError):
    """Raised for invalid workflow operations; the message is safe to show to users."""


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def _stamp() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _today() -> _dt.date:
    return _now().date()


def parse_dt(value: str) -> _dt.datetime:
    """Parse an ISO date or datetime (a trailing Z is accepted) as timezone-aware UTC."""
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(text)
    except ValueError:
        raise WorkflowError(f"not a date/time: {value!r} (use 2026-10-27 or 2026-10-27T09:30:00Z)") from None
    return dt if dt.tzinfo else dt.replace(tzinfo=_dt.timezone.utc)


def load_spec() -> dict:
    return json.loads(SPEC_FILE.read_text(encoding="utf-8"))


def _norm(name: Optional[str]) -> str:
    return (name or "").strip().lower()


# ---- audit chain ----------------------------------------------------------------
_CHAIN_FIELDS = ("seq", "at", "actor", "role", "action", "system", "target", "details", "prev")
GENESIS = "0" * 64


def _event_hash(event: dict) -> str:
    body = {k: event.get(k) for k in _CHAIN_FIELDS}
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_audit(events: List[dict]) -> Tuple[bool, List[str]]:
    """Recompute the hash chain. Returns (ok, problems)."""
    problems, prev = [], GENESIS
    for i, ev in enumerate(events, 1):
        if ev.get("seq") != i:
            problems.append(f"event {i}: sequence number is {ev.get('seq')!r}")
        if ev.get("prev") != prev:
            problems.append(f"event {i}: does not link to the previous event (history edited or removed?)")
        if ev.get("hash") != _event_hash(ev):
            problems.append(f"event {i}: content does not match its hash (event edited)")
        prev = ev.get("hash")
    return (not problems), problems


class Workflow:
    """Workflow operations over a loaded `Scope`. Callers save the scope afterwards."""

    def __init__(self, scope: Scope):
        self.scope = scope
        self.lib: Library = scope.lib
        self.spec = load_spec()
        self.stages = {s["id"]: s for s in self.spec["workflow"]["stages"]}
        self.order = [s["id"] for s in self.spec["workflow"]["stages"]]

    # ---- state -------------------------------------------------------------------
    @property
    def _all(self) -> dict:
        return self.scope.data.setdefault("workflow", {})

    @property
    def audit_log(self) -> List[dict]:
        return self.scope.data.setdefault("audit", [])

    def sid(self, system_id: Optional[str]) -> str:
        return self.scope.system(system_id)["id"]

    def enabled(self, system_id: Optional[str]) -> bool:
        return self.sid(system_id) in self._all

    def state(self, system_id: Optional[str]) -> dict:
        sid = self.sid(system_id)
        if sid not in self._all:
            raise WorkflowError(f"workflow is not enabled for {sid!r}; run: aicontrols workflow init")
        return self._all[sid]

    def policy(self, system_id: Optional[str]) -> dict:
        merged = json.loads(json.dumps(DEFAULT_POLICY))
        stored = self.state(system_id).get("policy", {})
        for k, v in stored.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        return merged

    def enable(self, system_id: Optional[str], actor: str) -> dict:
        sid = self.sid(system_id)
        if sid in self._all:
            raise WorkflowError(f"workflow is already enabled for {sid!r}")
        now = _stamp()
        self._all[sid] = {
            "spec_version": self.spec["version"], "cycle": 1,
            "stage": self.spec["workflow"]["initialStage"], "entered": now, "stage_log": [],
            "attestations": {}, "profile": {}, "common_controls": {}, "measurements": [],
            "escalations": [], "exceptions": {}, "policy": {},
            "markers": {"last_ingest_at": None, "ccm_evaluated_at": None, "gap_run_at": None,
                        "audit_verified_at": None, "report_at": None},
            "completed_cycles": [],
        }
        self.scope.data["schema_version"] = WORKFLOW_SCHEMA_VERSION
        self.audit(sid, actor, self.stages[self.order[0]]["assignedRole"], "WORKFLOW_ENABLED", sid,
                   {"spec": self.spec["title"], "spec_version": self.spec["version"]})
        return self._all[sid]

    # ---- audit -----------------------------------------------------------------------
    def audit(self, system_id: str, actor: str, role: str, action: str, target: str, details: Optional[dict] = None) -> dict:
        log = self.audit_log
        event = {"seq": len(log) + 1, "at": _stamp(), "actor": actor, "role": role, "action": action,
                 "system": system_id, "target": target, "details": details or {},
                 "prev": log[-1]["hash"] if log else GENESIS}
        event["hash"] = _event_hash(event)
        log.append(event)
        return event

    def verify(self, system_id: Optional[str], actor: str) -> Tuple[bool, List[str]]:
        ok, problems = verify_audit(self.audit_log)
        if ok and self.enabled(system_id):
            self.state(system_id)["markers"]["audit_verified_at"] = _stamp()
        return ok, problems

    # ---- helpers -----------------------------------------------------------------
    def _check_actor(self, actor: str) -> str:
        actor = (actor or "").strip()
        if not actor:
            raise WorkflowError("an actor name is required (--by)")
        return actor

    def _sod(self, system_id: str, first: Optional[str], second: str, what: str) -> None:
        if self.policy(system_id)["separation_of_duties"] and first and _norm(first) == _norm(second):
            raise WorkflowError(f"separation of duties: {what} must be different people "
                                f"(both are {second!r}). Disable with: workflow policy set separation_of_duties=false")

    def _applicable(self, sid: str) -> List[Tuple[Control, dict]]:
        return [(c, d) for c, d in self.scope.rows(sid) if d["applicable"]]

    def _rec(self, sid: str, control_id: str) -> dict:
        table = self.scope.data["decisions"].setdefault(sid, {})
        rec = table.setdefault(control_id, {})
        rec["updated"] = _today().isoformat()
        return rec

    def _pick(self, sid: str, ids: Iterable[str], domain: Optional[str], framework: Optional[str]) -> List[Control]:
        try:
            return self.scope.select(sid, list(ids), domain=domain, framework=framework)
        except KeyError as e:
            raise WorkflowError(e.args[0]) from None

    # ---- stage 1: profile and targets ----------------------------------------------
    def set_profile(self, system_id: Optional[str], actor: str, **fields) -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        prof = self.state(sid)["profile"]
        before = dict(prof)
        for key, value in fields.items():
            if value is None:
                continue
            if key == "risk_appetite" and value not in RISK_APPETITES:
                raise WorkflowError(f"risk_appetite must be one of {', '.join(RISK_APPETITES)}")
            if key == "target_default" and value not in ("implemented", "verified"):
                raise WorkflowError("target_default must be 'implemented' or 'verified'")
            if key == "asset_classes":
                value = sorted({v.strip() for v in value if v.strip()})
            elif key in ("business_unit", "environment", "boundary"):
                value = str(value).strip()
                if not value:
                    raise WorkflowError(f"{key} cannot be empty")
            elif key not in ("risk_appetite", "target_default"):
                raise WorkflowError(f"unknown profile field {key!r}")
            prof[key] = value
        if prof != before:
            self.audit(sid, actor, "SCOPING_COMPLIANCE_LEAD", "PROFILE_UPDATED", sid,
                       {"before": before, "after": dict(prof)})
        return prof

    def set_target(self, system_id: Optional[str], actor: str, status: str, by_date: Optional[str] = None,
                   controls: Iterable[str] = (), domain: Optional[str] = None, framework: Optional[str] = None) -> int:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        if status not in ("implemented", "verified"):
            raise WorkflowError("a target must be 'implemented' or 'verified'")
        if by_date:
            try:
                _dt.date.fromisoformat(by_date)
            except ValueError:
                raise WorkflowError(f"by-date must be a date like 2026-12-31, got {by_date!r}") from None
        chosen = self._pick(sid, controls, domain, framework)
        for c in chosen:
            rec = self._rec(sid, c.id)
            rec["target"] = status
            if by_date:
                rec["target_by"] = by_date
        self.audit(sid, actor, "SCOPING_COMPLIANCE_LEAD", "TARGET_SET", f"{len(chosen)} control(s)",
                   {"status": status, "by": by_date, "domain": domain, "framework": framework,
                    "controls": [c.id for c in chosen][:25]})
        return len(chosen)

    def target_of(self, sid: str, control_id: str) -> Tuple[str, Optional[str]]:
        rec = self.scope.data["decisions"].get(sid, {}).get(control_id, {})
        default = self.state(sid)["profile"].get("target_default", "implemented")
        return rec.get("target", default), rec.get("target_by")

    # ---- stage 2: common controls ----------------------------------------------------
    def _ccs(self, sid: str) -> Dict[str, dict]:
        return self.state(sid)["common_controls"]

    def cc(self, system_id: Optional[str], cc_id: str) -> dict:
        ccs = self._ccs(self.sid(system_id))
        if cc_id not in ccs:
            raise WorkflowError(f"unknown common control {cc_id!r}")
        return ccs[cc_id]

    def members(self, sid: str, cc_id: str) -> List[str]:
        table = self.scope.data["decisions"].get(sid, {})
        return sorted(cid for cid, rec in table.items() if rec.get("common_control") == cc_id)

    def cc_add(self, system_id: Optional[str], actor: str, title: str, cc_id: Optional[str] = None,
               description: str = "", domain: Optional[str] = None) -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        ccs = self._ccs(sid)
        if not title.strip():
            raise WorkflowError("a common control needs a title")
        if cc_id is None:
            n = len(ccs) + 1
            while f"CC-{n:03d}" in ccs:
                n += 1
            cc_id = f"CC-{n:03d}"
        elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", cc_id):
            raise WorkflowError("a common control id starts with a letter and uses letters, digits, '-' and '_'")
        if cc_id in ccs:
            raise WorkflowError(f"common control {cc_id!r} already exists")
        dom = None
        if domain:
            try:
                dom = self.lib.domain(domain).id
            except KeyError as e:
                raise WorkflowError(e.args[0]) from None
        ccs[cc_id] = {"id": cc_id, "title": title.strip(), "description": description, "domain_id": dom,
                      "owner": None, "reviewer": None, "frequency": None, "implementation": "",
                      "parameters": {}, "evidence_required": [], "test": {"type": None, "description": ""},
                      "indicators": [], "created": _stamp()}
        self.audit(sid, actor, "COMPLIANCE_ARCHITECT", "CC_ADDED", cc_id, {"title": title.strip(), "domain": dom})
        return ccs[cc_id]

    def cc_map(self, system_id: Optional[str], actor: str, cc_id: str, controls: Iterable[str] = (),
               domain: Optional[str] = None, framework: Optional[str] = None, move: bool = False) -> int:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        self.cc(sid, cc_id)
        chosen = self._pick(sid, controls, domain, framework)
        table = self.scope.data["decisions"].get(sid, {})
        mapped = []
        for c in chosen:
            d = self.scope.decision(sid, c.id)
            if not d["applicable"]:
                continue  # out-of-scope controls are never mapped
            current = table.get(c.id, {}).get("common_control")
            if current and current != cc_id and not move:
                raise WorkflowError(f"{c.id} is already mapped to {current}; use --move to remap it")
            rec = self._rec(sid, c.id)
            rec["common_control"] = cc_id
            rec.pop("common_control_gap", None)
            mapped.append(c.id)
        if not mapped:
            raise WorkflowError("no applicable controls selected (not-applicable controls are never mapped)")
        self.audit(sid, actor, "COMPLIANCE_ARCHITECT", "CC_MAPPED", cc_id,
                   {"count": len(mapped), "controls": mapped[:25], "moved": move})
        return len(mapped)

    def cc_suggest(self, system_id: Optional[str], min_frameworks: int = 1) -> List[dict]:
        """Propose one common control per domain from still-unmapped applicable controls.

        The proposals mirror the dataset's domain crosswalk. They are a starting point for the
        architect, not a finding that the controls are equivalent.
        """
        sid = self.sid(system_id)
        groups: Dict[str, List[Control]] = {}
        for c, d in self._applicable(sid):
            if not d.get("common_control"):
                groups.setdefault(c.domain_id, []).append(c)
        out = []
        for did, items in groups.items():
            fws = {c.framework_id for c in items}
            if len(fws) >= min_frameworks:
                out.append({"title": self.lib.domains[did].name, "domain_id": did,
                            "controls": [c.id for c in items], "frameworks": len(fws)})
        return sorted(out, key=lambda p: (-p["frameworks"], -len(p["controls"]), p["title"]))

    def cc_apply_suggestions(self, system_id: Optional[str], actor: str, proposals: List[dict]) -> int:
        sid = self.sid(system_id)
        made = 0
        for p in proposals:
            cc = self.cc_add(sid, actor, p["title"], domain=p["domain_id"],
                             description="Proposed from the dataset's domain crosswalk; review before relying on it.")
            self.cc_map(sid, actor, cc["id"], controls=p["controls"])
            made += 1
        return made

    def unmapped(self, system_id: Optional[str]) -> List[Control]:
        sid = self.sid(system_id)
        table = self.scope.data["decisions"].get(sid, {})
        out = []
        for c, d in self._applicable(sid):
            rec = table.get(c.id, {})
            if not rec.get("common_control") and not rec.get("common_control_gap"):
                out.append(c)
        return out

    def gap_accept(self, system_id: Optional[str], actor: str, controls: Iterable[str], reason: str,
                   domain: Optional[str] = None, framework: Optional[str] = None) -> int:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        if not reason.strip():
            raise WorkflowError("accepting an unmapped control needs a reason")
        chosen = [c for c in self._pick(sid, controls, domain, framework)
                  if self.scope.decision(sid, c.id)["applicable"]]
        for c in chosen:
            self._rec(sid, c.id)["common_control_gap"] = reason.strip()
        self.audit(sid, actor, "COMPLIANCE_ARCHITECT", "UNMAPPED_GAP_ACCEPTED", f"{len(chosen)} control(s)",
                   {"reason": reason.strip(), "controls": [c.id for c in chosen][:25]})
        return len(chosen)

    # ---- stage 3: tailoring ---------------------------------------------------------
    def cc_set(self, system_id: Optional[str], actor: str, cc_id: str, **fields) -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        cc = self.cc(sid, cc_id)
        changed = {}
        for key, value in fields.items():
            if value is None:
                continue
            if key == "frequency" and value not in FREQUENCIES:
                raise WorkflowError(f"frequency must be one of {', '.join(FREQUENCIES)}")
            if key == "test_type":
                if value not in TEST_TYPES:
                    raise WorkflowError(f"test type must be one of {', '.join(TEST_TYPES)}")
                cc["test"]["type"] = value
                changed[key] = value
                continue
            if key == "test_description":
                cc["test"]["description"] = str(value)
                changed[key] = "set"
                continue
            if key == "parameters":
                cc["parameters"].update(value)
                changed[key] = dict(value)
                continue
            if key == "evidence_required":
                for item in value:
                    if item not in cc["evidence_required"]:
                        cc["evidence_required"].append(item)
                changed[key] = list(value)
                continue
            if key in ("owner", "reviewer"):
                other = cc["reviewer"] if key == "owner" else cc["owner"]
                self._sod(sid, other, value, "the first-line owner and the second-line reviewer")
            if key not in ("title", "description", "owner", "reviewer", "frequency", "implementation"):
                raise WorkflowError(f"unknown common-control field {key!r}")
            cc[key] = value
            changed[key] = "set" if key == "implementation" else value
        if changed:
            cc["updated"] = _stamp()
            self.audit(sid, actor, "FIRST_LINE_CONTROL_OWNER", "CC_TAILORED", cc_id, changed)
        return cc

    def tailor(self, system_id: Optional[str], actor: str, control_id: str, implementation: str) -> None:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        chosen = self._pick(sid, [control_id], None, None)
        if not implementation.strip():
            raise WorkflowError("an implementation statement cannot be empty")
        self._rec(sid, chosen[0].id)["implementation"] = implementation.strip()
        self.audit(sid, actor, "FIRST_LINE_CONTROL_OWNER", "CONTROL_TAILORED", control_id, {"implementation": "set"})

    def indicator_add(self, system_id: Optional[str], actor: str, cc_id: str, name: str, kind: str,
                      metric: str, op: str, value: float) -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        cc = self.cc(sid, cc_id)
        if kind not in ("KCI", "KRI"):
            raise WorkflowError("kind must be KCI (key control indicator) or KRI (key risk indicator)")
        if op not in OPS:
            raise WorkflowError(f"breach operator must be one of {' '.join(OPS)}")
        if not name.strip() or not metric.strip():
            raise WorkflowError("an indicator needs a name and a metric")
        ind_id = f"{kind}-{len(cc['indicators']) + 1}"
        ind = {"id": ind_id, "name": name.strip(), "kind": kind, "metric": metric.strip(),
               "breach_if": {"op": op, "value": float(value)}}
        cc["indicators"].append(ind)
        # Audit details carry no floats: 5.0 would serialise differently in Python and in the browser,
        # which would break cross-implementation verification of the hash chain.
        self.audit(sid, actor, "SECOND_LINE_RISK_MANAGER", "INDICATOR_ADDED", f"{cc_id}/{ind_id}",
                   {"id": ind_id, "name": ind["name"], "kind": kind, "metric": ind["metric"],
                    "breach_if": f"{op} {float(value):g}"})
        return ind

    # ---- stage 4: continuous monitoring -----------------------------------------------
    def ingest(self, system_id: Optional[str], actor: str, records: List[dict], source: str = "file") -> dict:
        """Accept test results and metrics. Each record: control (common control id), at, result, ..."""
        sid, actor = self.sid(system_id), self._check_actor(actor)
        st = self.state(sid)
        ccs, accepted, dupes, rejected = self._ccs(sid), 0, 0, []
        seen = {(m["cc"], m["at"], m.get("source", "")) for m in st["measurements"]}
        for i, r in enumerate(records, 1):
            try:
                if not isinstance(r, dict):
                    raise WorkflowError("record is not an object")
                cc_id = r.get("control") or r.get("cc")
                if cc_id not in ccs:
                    raise WorkflowError(f"unknown common control {cc_id!r}")
                if r.get("result") not in RESULTS:
                    raise WorkflowError(f"result must be one of {', '.join(RESULTS)}")
                at = parse_dt(r.get("at")).astimezone(_dt.timezone.utc).replace(microsecond=0) \
                    .isoformat().replace("+00:00", "Z")
                metrics = r.get("metrics") or {}
                if not isinstance(metrics, dict) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in metrics.values()):
                    raise WorkflowError("metrics must be an object of numbers")
                src = str(r.get("source") or source)
                key = (cc_id, at, src)
                if key in seen:
                    dupes += 1
                    continue
                seen.add(key)
                st["measurements"].append({"cc": cc_id, "at": at, "result": r["result"], "metrics": metrics,
                                           "source": src, "evidence": str(r.get("evidence") or "")})
                accepted += 1
            except WorkflowError as e:
                rejected.append((i, str(e)))
        st["measurements"].sort(key=lambda m: (m["cc"], m["at"]))
        for cc_id in ccs:  # keep the most recent 200 per common control
            own = [m for m in st["measurements"] if m["cc"] == cc_id]
            if len(own) > 200:
                drop = own[:-200]
                st["measurements"] = [m for m in st["measurements"] if m not in drop]
        if accepted:
            st["markers"]["last_ingest_at"] = _stamp()
        self.audit(sid, actor, ROLE_CCM, "EVIDENCE_INGESTED", source,
                   {"accepted": accepted, "duplicates": dupes, "rejected": len(rejected)})
        return {"accepted": accepted, "duplicates": dupes, "rejected": rejected}

    def effectiveness(self, system_id: Optional[str], cc_id: str, now: Optional[_dt.datetime] = None) -> dict:
        sid = self.sid(system_id)
        cc, pol = self.cc(sid, cc_id), self.policy(sid)
        now = now or _now()
        ms = [m for m in self.state(sid)["measurements"] if m["cc"] == cc_id]
        if not ms:
            return {"state": "not_tested", "rate": None, "tested": 0, "last_at": None, "age_days": None}
        last = ms[-1]
        window = ms[-pol["effectiveness_window"]:]
        rate = sum(1 for m in window if m["result"] == "pass") / len(window)
        age = (now - parse_dt(last["at"])).total_seconds() / 86400
        limit = FREQUENCIES.get(cc.get("frequency") or "", None)
        if limit is not None and age > limit * pol["stale_factor"]:
            state = "stale"
        elif rate >= pol["effective_threshold"]:
            state = "effective"
        elif rate >= pol["partial_threshold"]:
            state = "partially_effective"
        else:
            state = "ineffective"
        return {"state": state, "rate": round(rate, 3), "tested": len(window), "last_at": last["at"],
                "age_days": round(age, 1)}

    def evaluate(self, system_id: Optional[str], actor: str, now: Optional[_dt.datetime] = None) -> dict:
        """Score every common control and check every indicator; record new threshold breaches."""
        sid, actor = self.sid(system_id), self._check_actor(actor)
        st = self.state(sid)
        scores = {cc_id: self.effectiveness(sid, cc_id, now) for cc_id in self._ccs(sid)}
        known = {e["key"] for e in st["escalations"]}
        breaches, new = [], []
        for cc_id, cc in self._ccs(sid).items():
            for ind in cc["indicators"]:
                reading = next((m for m in reversed([m for m in st["measurements"] if m["cc"] == cc_id])
                                if ind["metric"] in m["metrics"]), None)
                if reading is None:
                    continue
                value, op, limit = reading["metrics"][ind["metric"]], ind["breach_if"]["op"], ind["breach_if"]["value"]
                breached = {">": value > limit, ">=": value >= limit, "<": value < limit, "<=": value <= limit}[op]
                row = {"cc": cc_id, "indicator": ind["id"], "name": ind["name"], "kind": ind["kind"],
                       "metric": ind["metric"], "value": value, "at": reading["at"], "breached": breached,
                       "rule": f"breach if {op} {limit:g}"}
                if breached:
                    breaches.append(row)
                    key = f"{cc_id}:{ind['id']}:{reading['at']}"
                    if key not in known:
                        esc = {"key": key, "cc": cc_id, "indicator": ind["id"], "kind": ind["kind"],
                               "value": value, "rule": row["rule"], "at": reading["at"], "status": "open",
                               "raised": _stamp()}
                        st["escalations"].append(esc)
                        new.append(esc)
                        self.audit(sid, actor, ROLE_CCM, f"{ind['kind']}_BREACH", f"{cc_id}/{ind['id']}",
                                   {"value": f"{value:g}", "rule": row["rule"], "measured": reading["at"]})
        st["markers"]["ccm_evaluated_at"] = _stamp()
        self.audit(sid, actor, ROLE_CCM, "CCM_EVALUATED", sid,
                   {"controls": len(scores), "breaches": len(breaches), "new_escalations": len(new)})
        return {"effectiveness": scores, "breaches": breaches, "new_escalations": new}

    def escalation_ack(self, system_id: Optional[str], actor: str, key: str, note: str = "") -> None:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        esc = next((e for e in self.state(sid)["escalations"] if e["key"] == key), None)
        if esc is None:
            raise WorkflowError(f"unknown escalation {key!r}")
        esc.update({"status": "acknowledged", "ack_by": actor, "ack_at": _stamp(), "ack_note": note})
        self.audit(sid, actor, ROLE_SECOND_LINE, "ESCALATION_ACKNOWLEDGED", key, {"note": note})

    # ---- stage 5: exceptions ---------------------------------------------------------------
    def _ex(self, sid: str, ex_id: str) -> dict:
        exs = self.state(sid)["exceptions"]
        if ex_id not in exs:
            raise WorkflowError(f"unknown exception {ex_id!r}")
        return exs[ex_id]

    def exception_state(self, sid: str, ex: dict, today: Optional[_dt.date] = None) -> str:
        """Stored status, refined by the clock: an approved exception is active, expiring or expired."""
        if ex["status"] != "approved":
            return ex["status"]
        today = today or _today()
        expires = _dt.date.fromisoformat(ex["expires"])
        if expires < today:
            return "expired"
        if (expires - today).days <= self.policy(sid)["reassess_warning_days"]:
            return "expiring"
        return "active"

    def exception_covers(self, sid: str, ex: dict) -> set:
        covered = set(ex.get("controls", []))
        if ex.get("cc"):
            covered |= set(self.members(sid, ex["cc"]))
        return covered

    def exception_request(self, system_id: Optional[str], actor: str, reason: str, kind: str = "waiver",
                          controls: Iterable[str] = (), cc: Optional[str] = None, compensating: str = "") -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        if kind not in EXCEPTION_TYPES:
            raise WorkflowError(f"type must be one of {', '.join(EXCEPTION_TYPES)}")
        if not reason.strip():
            raise WorkflowError("an exception needs a reason")
        ids = []
        if controls:
            ids = [c.id for c in self._pick(sid, controls, None, None)]
            for cid in ids:
                if not self.scope.decision(sid, cid)["applicable"]:
                    raise WorkflowError(f"{cid} is not applicable, so it needs no exception")
        if cc:
            self.cc(sid, cc)
        if not ids and not cc:
            raise WorkflowError("name the controls (--control) or a common control (--cc) the exception covers")
        exs = self.state(sid)["exceptions"]
        n = len(exs) + 1
        while f"EX-{n:03d}" in exs:
            n += 1
        ex_id = f"EX-{n:03d}"
        exs[ex_id] = {"id": ex_id, "type": kind, "controls": ids, "cc": cc, "reason": reason.strip(),
                      "compensating_controls": compensating, "requested_by": actor, "requested_at": _stamp(),
                      "status": "requested", "assessment": None, "approvals": [], "expires": None,
                      "revision": 1, "history": [{"at": _stamp(), "by": actor, "action": "requested", "note": reason.strip()}]}
        self.audit(sid, actor, "FIRST_LINE_CONTROL_OWNER", "EXCEPTION_REQUESTED", ex_id,
                   {"type": kind, "controls": ids, "cc": cc})
        return exs[ex_id]

    def exception_assess(self, system_id: Optional[str], actor: str, ex_id: str, likelihood: int, impact: int,
                         notes: str = "") -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        ex = self._ex(sid, ex_id)
        if ex["status"] not in EXCEPTION_OPEN:
            raise WorkflowError(f"{ex_id} is {ex['status']}; only requested or assessed exceptions can be assessed")
        for name, v in (("likelihood", likelihood), ("impact", impact)):
            if not isinstance(v, int) or not 1 <= v <= 5:
                raise WorkflowError(f"{name} must be a whole number from 1 to 5")
        self._sod(sid, ex["requested_by"], actor, "the requester and the risk assessor")
        score = likelihood * impact
        rating = "low" if score <= 4 else "medium" if score <= 9 else "high" if score <= 16 else "critical"
        ex["assessment"] = {"likelihood": likelihood, "impact": impact, "score": score, "rating": rating,
                            "assessed_by": actor, "assessed_at": _stamp(), "notes": notes}
        ex["status"] = "assessed"
        ex["history"].append({"at": _stamp(), "by": actor, "action": "assessed", "note": f"{rating} ({score})"})
        self.audit(sid, actor, ROLE_SECOND_LINE, "EXCEPTION_ASSESSED", ex_id, {"score": score, "rating": rating})
        return ex

    def required_approver(self, sid: str, ex: dict) -> str:
        rating = ex["assessment"]["rating"]
        threshold = self.policy(sid)["executive_approval_from"]
        return ROLE_EXECUTIVE if RATINGS.index(rating) >= RATINGS.index(threshold) else ROLE_SECOND_LINE

    def exception_approve(self, system_id: Optional[str], actor: str, role: str, ex_id: str, days: int) -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        ex = self._ex(sid, ex_id)
        if ex["status"] != "assessed":
            raise WorkflowError(f"{ex_id} is {ex['status']}; it must be assessed before approval")
        need = self.required_approver(sid, ex)
        allowed = (ROLE_EXECUTIVE,) if need == ROLE_EXECUTIVE else (ROLE_SECOND_LINE, ROLE_EXECUTIVE)
        if role not in allowed:
            raise WorkflowError(f"a {ex['assessment']['rating']} exception needs sign-off by {need}, not {role}")
        self._sod(sid, ex["requested_by"], actor, "the requester and the approver")
        self._sod(sid, ex["assessment"]["assessed_by"], actor, "the risk assessor and the approver")
        limit = self.policy(sid)["exception_max_days"][ex["assessment"]["rating"]]
        if not isinstance(days, int) or days < 1:
            raise WorkflowError("an approval needs a duration in days (--days)")
        if days > limit:
            raise WorkflowError(f"a {ex['assessment']['rating']} exception can be approved for at most {limit} days")
        ex["approvals"].append({"by": actor, "role": role, "at": _stamp()})
        ex["expires"] = (_today() + _dt.timedelta(days=days)).isoformat()
        ex["status"] = "approved"
        ex["history"].append({"at": _stamp(), "by": actor, "action": "approved", "note": f"until {ex['expires']}"})
        self.audit(sid, actor, role, "EXCEPTION_APPROVED", ex_id, {"expires": ex["expires"], "days": days})
        return ex

    def exception_reject(self, system_id: Optional[str], actor: str, role: str, ex_id: str, reason: str) -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        ex = self._ex(sid, ex_id)
        if ex["status"] not in EXCEPTION_OPEN:
            raise WorkflowError(f"{ex_id} is {ex['status']}; only open exceptions can be rejected")
        if role not in (ROLE_SECOND_LINE, ROLE_EXECUTIVE):
            raise WorkflowError("only the second line or an executive can reject an exception")
        if not reason.strip():
            raise WorkflowError("a rejection needs a reason")
        ex["status"] = "rejected"
        ex["history"].append({"at": _stamp(), "by": actor, "action": "rejected", "note": reason.strip()})
        self.audit(sid, actor, role, "EXCEPTION_REJECTED", ex_id, {"reason": reason.strip()})
        return ex

    def exception_reopen(self, system_id: Optional[str], actor: str, ex_id: str, reason: str) -> dict:
        """Start re-assessment (typically at expiry). Prior approvals are cleared; history is kept."""
        sid, actor = self.sid(system_id), self._check_actor(actor)
        ex = self._ex(sid, ex_id)
        if ex["status"] not in ("approved", "rejected", "closed"):
            raise WorkflowError(f"{ex_id} is {ex['status']}; nothing to reopen")
        ex.update({"status": "requested", "assessment": None, "approvals": [], "expires": None,
                   "revision": ex["revision"] + 1, "requested_by": actor})
        ex["history"].append({"at": _stamp(), "by": actor, "action": "reopened", "note": reason})
        self.audit(sid, actor, "FIRST_LINE_CONTROL_OWNER", "EXCEPTION_REOPENED", ex_id, {"reason": reason})
        return ex

    def exception_close(self, system_id: Optional[str], actor: str, ex_id: str, reason: str) -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        ex = self._ex(sid, ex_id)
        if ex["status"] == "closed":
            raise WorkflowError(f"{ex_id} is already closed")
        ex["status"] = "closed"
        ex["history"].append({"at": _stamp(), "by": actor, "action": "closed", "note": reason})
        self.audit(sid, actor, ROLE_SECOND_LINE, "EXCEPTION_CLOSED", ex_id, {"reason": reason})
        return ex

    def exceptions(self, system_id: Optional[str], today: Optional[_dt.date] = None) -> List[dict]:
        sid = self.sid(system_id)
        return [{**ex, "state": self.exception_state(sid, ex, today)} for ex in self.state(sid)["exceptions"].values()]

    # ---- policy ---------------------------------------------------------------------------
    def policy_set(self, system_id: Optional[str], actor: str, key: str, value: str) -> dict:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        stored = self.state(sid).setdefault("policy", {})
        snapshot = json.loads(json.dumps(stored))
        base = key.split(".", 1)
        try:
            if key == "separation_of_duties":
                if value.lower() not in ("true", "false"):
                    raise ValueError
                new = value.lower() == "true"
                stored[key] = new
            elif key == "executive_approval_from":
                if value not in RATINGS:
                    raise ValueError
                stored[key] = value
            elif base[0] == "exception_max_days" and len(base) == 2 and base[1] in RATINGS:
                stored.setdefault("exception_max_days", {})[base[1]] = int(value)
                new = int(value)
            elif key in ("reassess_warning_days", "effectiveness_window"):
                stored[key] = int(value)
                new = int(value)
            elif key in ("effective_threshold", "partial_threshold", "stale_factor"):
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError
                stored[key] = number
                new = number
            else:
                raise WorkflowError(f"unknown policy key {key!r}")
        except WorkflowError:
            raise  # a WorkflowError is also a ValueError: keep our own message
        except ValueError:
            raise WorkflowError(f"invalid value {value!r} for {key}") from None
        pol = self.policy(sid)
        if not 0 <= pol["partial_threshold"] <= pol["effective_threshold"] <= 1:
            stored.clear()  # roll back: a rejected change must not stay stored
            stored.update(snapshot)
            raise WorkflowError("thresholds must satisfy 0 <= partial <= effective <= 1")
        self.audit(sid, actor, "SECOND_LINE_RISK_MANAGER", "POLICY_CHANGED", key, {"value": value})
        return pol

    # ---- stage 6: gap analysis, POA&M, report ---------------------------------------------
    def gap_analysis(self, system_id: Optional[str], actor: Optional[str] = None, today: Optional[_dt.date] = None,
                     record: bool = False) -> dict:
        """Compare current status with the target profile; classify each gap as open/overdue/excepted."""
        sid = self.sid(system_id)
        today = today or _today()
        exs = [e for e in self.exceptions(sid, today)]
        cover: Dict[str, Tuple[str, str]] = {}
        for ex in exs:
            if ex["state"] in ("active", "expiring"):
                for cid in self.exception_covers(sid, ex):
                    cover[cid] = (ex["id"], ex["state"])
        expired = {cid for ex in exs if ex["state"] == "expired" for cid in self.exception_covers(sid, ex)}
        items, met, total = [], 0, 0
        by_fw: Dict[str, List[int]] = {}
        by_dom: Dict[str, List[int]] = {}
        for c, d in self._applicable(sid):
            target, target_by = self.target_of(sid, c.id)
            total += 1
            at_target = RANK[d["status"]] >= RANK[target]
            for table, key in ((by_fw, c.framework_id), (by_dom, c.domain_id)):
                row = table.setdefault(key, [0, 0])
                row[0] += 1
                row[1] += int(at_target)
            if at_target:
                met += 1
                continue
            due = target_by or d.get("due")
            if c.id in cover:
                state = "excepted"
            elif due and due < today.isoformat():
                state = "overdue"
            else:
                state = "open"
            items.append({"control_id": c.id, "title": c.title, "framework_id": c.framework_id,
                          "domain_id": c.domain_id, "current": d["status"], "target": target, "due": due,
                          "owner": d["owner"] or "", "state": state, "exception": cover.get(c.id, (None, None))[0],
                          "exception_expired": c.id in expired,
                          "common_control": self.scope.data["decisions"].get(sid, {}).get(c.id, {}).get("common_control")})
        assurance = []
        for cc_id in self._ccs(sid):
            eff = self.effectiveness(sid, cc_id)
            if eff["state"] in ("ineffective", "stale", "not_tested"):
                done = [cid for cid in self.members(sid, cc_id) if self.scope.decision(sid, cid)["status"] in DONE]
                if done:
                    assurance.append({"cc": cc_id, "title": self._ccs(sid)[cc_id]["title"], "state": eff["state"],
                                      "controls_claiming_done": len(done)})
        result = {
            "as_of": today.isoformat(), "applicable": total, "at_target": met,
            "percent": round(100 * met / total, 1) if total else None,
            "gaps": sorted(items, key=lambda i: ({"overdue": 0, "open": 1, "excepted": 2}[i["state"]], i["control_id"])),
            "assurance_gaps": assurance,
            "by_framework": {k: {"applicable": v[0], "at_target": v[1]} for k, v in sorted(by_fw.items())},
            "by_domain": {k: {"applicable": v[0], "at_target": v[1]} for k, v in sorted(by_dom.items())},
        }
        if record:
            self.state(sid)["markers"]["gap_run_at"] = _stamp()
            self.audit(sid, actor or "system", "THIRD_LINE_AUDITOR", "GAP_ANALYSIS_RUN", sid,
                       {"applicable": total, "at_target": met, "gaps": len(items)})
        return result

    def poam(self, system_id: Optional[str], today: Optional[_dt.date] = None) -> List[dict]:
        """Plan of Action and Milestones: one row per open, overdue or excepted gap."""
        rows = []
        for g in self.gap_analysis(system_id, today=today)["gaps"]:
            rows.append({"control_id": g["control_id"], "title": g["title"], "current": g["current"],
                         "target": g["target"], "milestone_due": g["due"] or "", "owner": g["owner"],
                         "state": g["state"], "exception": g["exception"] or "",
                         "common_control": g["common_control"] or ""})
        return rows

    def report(self, system_id: Optional[str], actor: Optional[str] = None, record: bool = False,
               today: Optional[_dt.date] = None) -> dict:
        sid = self.sid(system_id)
        today = today or _today()
        st = self.state(sid)
        gap = self.gap_analysis(sid, today=today)
        ccs = self._ccs(sid)
        eff = {cc_id: self.effectiveness(sid, cc_id) for cc_id in ccs}
        dist: Dict[str, int] = {}
        for v in eff.values():
            dist[v["state"]] = dist.get(v["state"], 0) + 1
        ok, problems = verify_audit(self.audit_log)
        exs = self.exceptions(sid, today)
        applicable = len(self._applicable(sid))
        unmapped = len(self.unmapped(sid))
        out = {
            "system": sid, "organisation": self.scope.data["organization"], "as_of": today.isoformat(),
            "stage": st["stage"], "cycle": st["cycle"], "profile": st["profile"],
            "scope": {"applicable_controls": applicable, "mapped_to_common_controls": applicable - unmapped,
                      "unmapped": unmapped},
            "common_controls": {"count": len(ccs), "effectiveness": dist,
                                "open_escalations": sum(1 for e in st["escalations"] if e["status"] == "open")},
            "exceptions": {s: sum(1 for e in exs if e["state"] == s)
                           for s in sorted({e["state"] for e in exs})},
            "gap_analysis": {k: gap[k] for k in ("applicable", "at_target", "percent")} | {
                "open": sum(1 for g in gap["gaps"] if g["state"] == "open"),
                "overdue": sum(1 for g in gap["gaps"] if g["state"] == "overdue"),
                "excepted": sum(1 for g in gap["gaps"] if g["state"] == "excepted"),
                "assurance_gaps": len(gap["assurance_gaps"])},
            "audit": {"events": len(self.audit_log), "chain_valid": ok, "problems": problems[:5]},
        }
        if record:
            st["markers"]["report_at"] = _stamp()
            self.audit(sid, actor or "system", "THIRD_LINE_AUDITOR", "REPORT_GENERATED", sid, {"as_of": out["as_of"]})
        return out

    def report_markdown(self, system_id: Optional[str], actor: Optional[str] = None, record: bool = True) -> str:
        r = self.report(system_id, actor, record=record)
        s = self.scope.system(system_id)
        pct = lambda v: "n/a" if v is None else f"{v}%"  # noqa: E731
        lines = [f"# Governance report: {s['name']}", "",
                 f"Organisation: {r['organisation']}  ", f"As of: {r['as_of']}  ",
                 f"Workflow stage: {r['stage']} (cycle {r['cycle']})", "",
                 "## Scope and harmonisation", "",
                 f"- Applicable controls: {r['scope']['applicable_controls']}",
                 f"- Mapped to common controls: {r['scope']['mapped_to_common_controls']} "
                 f"(unmapped: {r['scope']['unmapped']})",
                 f"- Common controls: {r['common_controls']['count']}", "",
                 "## Control effectiveness", ""]
        eff = r["common_controls"]["effectiveness"]
        lines += [f"- {k.replace('_', ' ')}: {v}" for k, v in sorted(eff.items())] or ["- no common controls yet"]
        lines += [f"- open KCI/KRI escalations: {r['common_controls']['open_escalations']}", "",
                  "## Target profile gap", "",
                  f"- At or above target: {r['gap_analysis']['at_target']} of {r['gap_analysis']['applicable']} "
                  f"({pct(r['gap_analysis']['percent'])})",
                  f"- Open gaps: {r['gap_analysis']['open']}, overdue: {r['gap_analysis']['overdue']}, "
                  f"excepted: {r['gap_analysis']['excepted']}",
                  f"- Controls marked done whose common control is not demonstrably effective: "
                  f"{r['gap_analysis']['assurance_gaps']}", "", "## Exceptions", ""]
        lines += [f"- {k}: {v}" for k, v in sorted(r["exceptions"].items())] or ["- none"]
        lines += ["", "## Audit trail", "",
                  f"- Events: {r['audit']['events']}; hash chain {'valid' if r['audit']['chain_valid'] else 'BROKEN'}",
                  "", "_Planning aid and working record, not an attestation of compliance. The audit trail is "
                  "tamper-evident, not immutable._", ""]
        return "\n".join(lines)

    # ---- the stage machine ------------------------------------------------------------------
    def check(self, system_id: Optional[str], action: str) -> Tuple[bool, str]:
        """Is this action satisfied right now? Returns (satisfied, one-line detail)."""
        sid = self.sid(system_id)
        st, ccs = self.state(sid), self._ccs(sid)
        prof, mk = st["profile"], st["markers"]
        table = self.scope.data["decisions"].get(sid, {})
        applicable = self._applicable(sid)

        def every(pred) -> Tuple[bool, int]:
            bad = sum(1 for cc in ccs.values() if not pred(cc))
            return bool(ccs) and bad == 0, bad

        if action == "DEFINE_ORGANIZATIONAL_PROFILE_BOUNDARIES":
            missing = [k for k in ("business_unit", "environment", "boundary") if not prof.get(k)]
            return not missing, "complete" if not missing else "missing: " + ", ".join(missing)
        if action == "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS":
            n = len(self.scope.rows(sid)) - len(applicable)
            return action in st["attestations"], f"{n} control(s) marked not applicable, each with a justification"
        if action == "ESTABLISH_CURRENT_VS_TARGET_PROFILES":
            missing = [k for k in ("risk_appetite", "target_default") if not prof.get(k)]
            return not missing, "complete" if not missing else "missing: " + ", ".join(missing)
        if action == "MAP_PLATFORM_FRAMEWORKS_TO_COMMON_CONTROLS":
            n_cc = sum(1 for cc_id in ccs if self.members(sid, cc_id))
            return n_cc > 0, f"{n_cc} common control(s) with mapped controls"
        if action == "DEDUPLICATE_OVERLAPPING_REQUIREMENTS":
            return action in st["attestations"], f"{len(ccs)} common control(s) defined"
        if action == "IDENTIFY_UNMAPPED_FRAMEWORK_GAPS":
            n = len(self.unmapped(sid))
            return n == 0, f"{n} applicable control(s) neither mapped nor explicitly accepted as a gap"
        if action == "CUSTOMIZE_CONTROL_IMPLEMENTATION_PARAMETERS":
            ok, bad = every(lambda cc: cc["implementation"].strip())
            return ok, f"{bad} of {len(ccs)} common control(s) lack an implementation statement" if ccs else "no common controls"
        if action == "ASSIGN_OPERATIONAL_OWNER_AND_REVIEW_FREQUENCY":
            ok, bad = every(lambda cc: cc["owner"] and cc["reviewer"] and cc["frequency"]
                            and _norm(cc["owner"]) != _norm(cc["reviewer"]))
            return ok, f"{bad} of {len(ccs)} lack owner, a different reviewer, or a frequency" if ccs else "no common controls"
        if action == "CONFIGURE_EVIDENCE_REQUIREMENTS_AND_TEST_RULES":
            ok, bad = every(lambda cc: cc["evidence_required"] and cc["test"]["type"] and cc["test"]["description"].strip())
            return ok, f"{bad} of {len(ccs)} lack evidence requirements or a test rule" if ccs else "no common controls"
        if action == "INGEST_AUTOMATED_EVIDENCE_FEEDS":
            have = {m["cc"] for m in st["measurements"]}
            ok, bad = every(lambda cc: cc["id"] in have)
            return ok, f"{bad} of {len(ccs)} common control(s) have no test results" if ccs else "no common controls"
        if action in ("EVALUATE_KCI_KRI_THRESHOLDS", "CALCULATE_REALTIME_CONTROL_EFFECTIVENESS"):
            ran, ingest = mk["ccm_evaluated_at"], mk["last_ingest_at"]
            fresh = bool(ran) and (not ingest or ran >= ingest)
            if action == "EVALUATE_KCI_KRI_THRESHOLDS" and not any(cc["indicators"] for cc in ccs.values()):
                return False, "no KCI/KRI indicator defined"
            return fresh, "evaluated since the last ingest" if fresh else "run: workflow ccm evaluate"
        if action == "PROCESS_CONTROL_EXCEPTION_REQUESTS":
            n = sum(1 for e in st["exceptions"].values() if e["status"] in EXCEPTION_OPEN)
            return n == 0, f"{n} exception(s) awaiting a decision" if n else "no exception awaiting a decision"
        if action == "ASSESS_RISK_EXPOSURE_AGAINST_TOLERANCE":
            n = sum(1 for e in st["exceptions"].values() if e["status"] != "requested" and not e["assessment"]
                    and e["status"] in ("assessed", "approved"))
            pending = sum(1 for e in st["exceptions"].values() if e["status"] == "requested")
            return n == 0 and pending == 0, f"{pending} awaiting assessment"
        if action == "ENFORCE_EXECUTIVE_APPROVAL_AND_EXPIRATION_DATES":
            bad = 0
            for ex in st["exceptions"].values():
                if ex["status"] != "approved":
                    continue
                need = self.required_approver(sid, ex)
                roles = {a["role"] for a in ex["approvals"]}
                if not ex["expires"] or (need == ROLE_EXECUTIVE and ROLE_EXECUTIVE not in roles) \
                        or self.exception_state(sid, ex) == "expired":
                    bad += 1
            return bad == 0, f"{bad} approved exception(s) expired or missing required sign-off" if bad else "all approvals current"
        if action == "MEASURE_PROGRESS_TOWARD_TARGET_PROFILE":
            ok = bool(mk["gap_run_at"]) and mk["gap_run_at"] >= st["entered"]
            return ok, "gap analysis run in this stage" if ok else "run: workflow gap"
        if action == "PRESERVE_IMMUTABLE_AUDIT_TRAIL_EVIDENCE":
            chain_ok, _p = verify_audit(self.audit_log)
            ok = chain_ok and bool(mk["audit_verified_at"]) and mk["audit_verified_at"] >= st["entered"]
            return ok, "audit chain verified in this stage" if ok else "run: workflow audit verify"
        if action == "GENERATE_REALTIME_REGULATORY_DASHBOARDS":
            ok = bool(mk["report_at"]) and mk["report_at"] >= st["entered"]
            return ok, "report generated in this stage" if ok else "run: workflow report"
        raise WorkflowError(f"unknown action {action!r}")

    def actions(self, system_id: Optional[str], stage_id: Optional[str] = None) -> List[dict]:
        st = self.state(system_id)
        stage = self.stages[stage_id or st["stage"]]
        out = []
        for action in stage["actions"]:
            ok, detail = self.check(system_id, action)
            out.append({"action": action, "kind": "attest" if action in ATTESTED else "evidence",
                        "satisfied": ok, "detail": detail,
                        "attested_by": st["attestations"].get(action, {}).get("by")})
        return out

    def attest(self, system_id: Optional[str], actor: str, role: Optional[str], action: str, note: str = "") -> None:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        st = self.state(sid)
        stage = self.stages[st["stage"]]
        if action not in stage["actions"]:
            raise WorkflowError(f"{action} is not an action of the current stage ({st['stage']})")
        if action not in ATTESTED:
            raise WorkflowError(f"{action} is satisfied by evidence in the file, not by attestation; "
                                f"see: aicontrols workflow status")
        role = role or stage["assignedRole"]
        if role != stage["assignedRole"]:
            raise WorkflowError(f"{action} belongs to {stage['assignedRole']}, not {role}")
        st["attestations"][action] = {"by": actor, "role": role, "at": _stamp(), "note": note}
        self.audit(sid, actor, role, "ACTION_ATTESTED", action, {"note": note})

    def advance(self, system_id: Optional[str], actor: str, force: bool = False, reason: str = "") -> str:
        sid, actor = self.sid(system_id), self._check_actor(actor)
        st = self.state(sid)
        stage = self.stages[st["stage"]]
        open_actions = [a for a in self.actions(sid) if not a["satisfied"]]
        if open_actions and not force:
            raise WorkflowError("cannot leave this stage yet: " + "; ".join(
                f"{a['action']} ({a['detail']})" for a in open_actions))
        if force and open_actions and not reason.strip():
            raise WorkflowError("forcing past an open gate needs a reason (--reason)")
        entry = {"stage": st["stage"], "left": _stamp(), "by": actor, "forced": bool(open_actions),
                 "reason": reason.strip(), "open_actions": [a["action"] for a in open_actions]}
        st["stage_log"].append(entry)
        if stage.get("isFinal"):
            st["completed_cycles"].append({"cycle": st["cycle"], "at": _stamp(), "by": actor})
            self.audit(sid, actor, stage["assignedRole"], "CYCLE_COMPLETED", sid,
                       {"cycle": st["cycle"], "forced": entry["forced"], "reason": entry["reason"]})
            return "cycle complete"
        nxt = stage["nextStage"]
        st["stage"], st["entered"] = nxt, _stamp()
        self.audit(sid, actor, stage["assignedRole"], "STAGE_ADVANCED", f"{entry['stage']} -> {nxt}",
                   {"forced": entry["forced"], "reason": entry["reason"], "open_actions": entry["open_actions"]})
        return nxt

    def restart_cycle(self, system_id: Optional[str], actor: str, reason: str = "") -> int:
        """Begin the next assessment cycle. Mappings, tailoring, results and exceptions carry over."""
        sid, actor = self.sid(system_id), self._check_actor(actor)
        st = self.state(sid)
        st["cycle"] += 1
        st["stage"], st["entered"] = self.order[0], _stamp()
        st["attestations"] = {}
        st["markers"].update({"ccm_evaluated_at": None, "gap_run_at": None, "audit_verified_at": None, "report_at": None})
        self.audit(sid, actor, self.stages[self.order[0]]["assignedRole"], "CYCLE_STARTED", sid,
                   {"cycle": st["cycle"], "reason": reason})
        return st["cycle"]


# ---- validation (called from Scope.validate) ---------------------------------------------
def validate_workflow(scope: Scope) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    data = scope.data
    work = data.get("workflow") or {}
    if not work and not data.get("audit"):
        return errors, warnings
    wf = Workflow(scope)
    sys_ids = {s["id"] for s in data["systems"]}
    ok, problems = verify_audit(data.get("audit") or [])
    errors += [f"audit: {p}" for p in problems]
    for sid, st in work.items():
        if sid not in sys_ids:
            errors.append(f"workflow for unknown system {sid!r}")
            continue
        if st.get("stage") not in wf.stages:
            errors.append(f"{sid}: unknown workflow stage {st.get('stage')!r}")
        ccs = st.get("common_controls", {})
        scope_ids = {c.id for c in scope.in_scope(sid)}
        for cid, rec in data["decisions"].get(sid, {}).items():
            if rec.get("common_control") and rec["common_control"] not in ccs:
                errors.append(f"{sid}/{cid}: mapped to unknown common control {rec['common_control']!r}")
            if rec.get("target") not in (None, "implemented", "verified"):
                errors.append(f"{sid}/{cid}: invalid target {rec.get('target')!r}")
        for cc_id, cc in ccs.items():
            if cc.get("frequency") not in (None, *FREQUENCIES):
                errors.append(f"{sid}/{cc_id}: invalid frequency {cc.get('frequency')!r}")
            if cc.get("test", {}).get("type") not in (None, *TEST_TYPES):
                errors.append(f"{sid}/{cc_id}: invalid test type")
            if cc.get("owner") and cc.get("reviewer") and _norm(cc["owner"]) == _norm(cc["reviewer"]) \
                    and st.get("policy", {}).get("separation_of_duties", True):
                warnings.append(f"{sid}/{cc_id}: owner and reviewer are the same person")
        for m in st.get("measurements", []):
            if m.get("cc") not in ccs:
                errors.append(f"{sid}: measurement for unknown common control {m.get('cc')!r}")
            if m.get("result") not in RESULTS:
                errors.append(f"{sid}: measurement with invalid result {m.get('result')!r}")
        for ex_id, ex in st.get("exceptions", {}).items():
            for cid in ex.get("controls", []):
                if cid not in scope_ids:
                    errors.append(f"{sid}/{ex_id}: covers {cid}, which is not in scope")
            if ex.get("cc") and ex["cc"] not in ccs:
                errors.append(f"{sid}/{ex_id}: unknown common control {ex['cc']!r}")
            if ex.get("status") == "approved" and not (ex.get("expires") and ex.get("assessment") and ex.get("approvals")):
                errors.append(f"{sid}/{ex_id}: approved without an assessment, approval and expiry date")
            if ex.get("status") not in ("requested", "assessed", "approved", "rejected", "closed"):
                errors.append(f"{sid}/{ex_id}: invalid status {ex.get('status')!r}")
    return errors, warnings
