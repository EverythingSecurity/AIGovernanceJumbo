# SPDX-License-Identifier: Apache-2.0
"""GRC management layer: the requirement -> control -> evidence -> audit chain, made traceable.

Implements the model in `grc_spec.json` (see docs/GRC.md) on top of the scope file and the workflow
layer. A framework requirement is one of the dataset's controls; a *control* in the GRC sense is a
workflow **common control**. This module adds what links them to the rest of the chain:

    requirement (clause) -> common control -> policy / guideline / SOP -> evidence -> audit

plus the registers that surround it (policy library, risks, audit findings and plan, scope register,
evidence sources), a mapping matrix, one stated coverage method, KPI/KRI targets, the ten-step
lifecycle, the artifacts checklist and ISO/IEC 42001 streams.

State lives in the same private scope file under `grc` (organisation level), with links stored on
common controls and on decisions. Every change is recorded in the hash-chained audit trail. The
browser twin is `site/grc.js`; tests keep the two identical.

Honest limits: percentages are only as good as the data entered; the stream grouping of ISO/IEC 42001
is a documented judgement; actor names and roles are labels, not authenticated identities.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .library import Library
from .scope import DONE, Scope, round_half_up
from .workflow import RATINGS, Workflow, WorkflowError, _stamp, _today

SPEC_FILE = Path(__file__).with_name("grc_spec.json")
GRC_SCHEMA_VERSION = "1.2"
ORG = "(organisation)"          # the "system" recorded on organisation-level audit events
ROLE_GRC = "GRC_OFFICE"
APPETITE_ALLOWED = {"low": 0, "moderate": 1, "high": 2}   # highest residual rating inside appetite (index in RATINGS)
DOC_CATEGORIES = ("policy", "guideline", "sop")
MATRIX_COLUMNS = ["requirement_id", "framework", "clause", "requirement", "control_id", "policy", "guideline", "sop",
                  "evidence", "status", "mapping_owner", "mapping_reviewed", "issues"]
ISSUE_TEXT = {
    "unmapped": "no control and not recorded as a gap",
    "no_policy": "control has no policy",
    "no_sop": "control has no SOP",
    "no_evidence_source": "control has no evidence source",
    "no_mapping_owner": "mapping has no owner",
    "no_review_date": "mapping has no review date",
    "review_overdue": "mapping review is overdue",
}


class GrcError(WorkflowError):
    """Raised for invalid GRC operations; the message is safe to show to users."""


def load_spec() -> dict:
    return json.loads(SPEC_FILE.read_text(encoding="utf-8"))


# ---- dates ------------------------------------------------------------------------------------
def parse_date(value: str, name: str = "date") -> _dt.date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise GrcError(f"{name} must be a date like 2026-12-31, got {value!r}")
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        raise GrcError(f"{name} must be a date like 2026-12-31, got {value!r}") from None


def add_months(d: _dt.date, n: int) -> _dt.date:
    """Calendar months, clamping the day (31 Jan + 1 month = 28/29 Feb)."""
    y, m = divmod(d.year * 12 + (d.month - 1) + n, 12)
    last = (_dt.date(y + (m + 1) // 12, (m + 1) % 12 + 1, 1) - _dt.timedelta(days=1)).day
    return _dt.date(y, m + 1, min(d.day, last))


def _pct(num: int, den: int) -> Optional[float]:
    return round_half_up(100 * num / den, 1) if den else None


def _matches(pattern: str, ref: str) -> Optional[int]:
    """Specificity of a stream pattern ('4.2' exact, '8.*' prefix) against a clause reference, or None."""
    if pattern.endswith(".*"):
        prefix = pattern[:-1]
        return len(prefix) if ref.startswith(prefix) else None
    return 1000 + len(pattern) if ref == pattern else None


class Grc:
    """GRC operations over a loaded `Scope`. Callers save the scope afterwards."""

    def __init__(self, scope: Scope):
        self.scope = scope
        self.lib: Library = scope.lib
        self.wf = Workflow(scope)
        self.spec = load_spec()

    # ---- state -----------------------------------------------------------------------------
    def _g(self) -> dict:
        return self.scope.data.get("grc") or {}

    def _ensure(self) -> dict:
        g = self.scope.data.setdefault("grc", {})
        for name in self.spec["registers"]:
            g.setdefault(name, {})
        g.setdefault("settings", {})
        g.setdefault("framework_scopes", {})
        g.setdefault("roles", {})
        g.setdefault("scope_reviewed", None)
        g.setdefault("markers", {"report_at": None})
        if self.scope.data.get("schema_version") in (None, "1.0", "1.1"):
            self.scope.data["schema_version"] = GRC_SCHEMA_VERSION
        return g

    def records(self, register: str) -> List[dict]:
        self._spec(register)
        return list(self._g().get(register, {}).values())

    def get(self, register: str, rec_id: str) -> dict:
        rec = self._g().get(register, {}).get(rec_id)
        if rec is None:
            raise GrcError(f"unknown {self._spec(register)['singular']} {rec_id!r}")
        return rec

    def _spec(self, register: str) -> dict:
        if register not in self.spec["registers"]:
            raise GrcError(f"unknown register {register!r}; choose from {', '.join(self.spec['registers'])}")
        return self.spec["registers"][register]

    def _audit(self, actor: str, action: str, target: str, details: Optional[dict] = None) -> None:
        self.wf.audit(ORG, actor, ROLE_GRC, action, target, details or {})

    def _actor(self, actor: str) -> str:
        return self.wf._check_actor(actor)

    # ---- settings -----------------------------------------------------------------------------
    def settings(self) -> dict:
        s = dict(self.spec["settings_defaults"])
        stored = self._g().get("settings", {})
        for k, v in stored.items():
            s[k] = dict(v) if isinstance(v, dict) else v
        s.setdefault("coverage_targets", {})
        return s

    def set_setting(self, actor: str, key: str, value: str) -> dict:
        actor = self._actor(actor)
        g = self._ensure()
        st = g["settings"]
        bad = GrcError(f"invalid value {value!r} for {key}")
        if key == "anchor_framework":
            if value not in self.lib.frameworks:
                raise GrcError(f"unknown framework {value!r}")
            st[key] = value
        elif key == "risk_appetite":
            if value not in APPETITE_ALLOWED:
                raise bad
            st[key] = value
        elif key in ("mapping_review_months", "scope_review_months"):
            if not re.fullmatch(r"\d+", value.strip()) or int(value) < 1:
                raise bad
            st[key] = int(value)
        elif key.startswith("coverage_target."):
            fw = key.split(".", 1)[1]
            if fw not in self.lib.frameworks:
                raise GrcError(f"unknown framework {fw!r}")
            targets = st.setdefault("coverage_targets", {})
            if value.strip() == "":
                targets.pop(fw, None)
            else:
                if not re.fullmatch(r"\d+", value.strip()) or not 0 <= int(value) <= 100:
                    raise bad
                targets[fw] = int(value)
        else:
            raise GrcError(f"unknown setting {key!r}")
        self._audit(actor, "GRC_SETTING_CHANGED", key, {"value": value})
        return self.settings()

    # ---- registers ------------------------------------------------------------------------------
    def _check_field(self, f: dict, value) -> object:
        label, kind = f["label"], f["kind"]
        if kind == "text":
            return str(value).strip()
        if kind == "enum":
            v = str(value).strip().lower()
            if v not in f["values"]:
                raise GrcError(f"{label} must be one of {', '.join(f['values'])}, got {value!r}")
            return v
        if kind == "date":
            parse_date(str(value).strip(), label)
            return str(value).strip()
        if kind == "int":
            if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value).strip()) or int(str(value).strip()) < f.get("min", 0):
                raise GrcError(f"{label} must be a whole number of at least {f.get('min', 0)}, got {value!r}")
            return int(str(value).strip())
        raise GrcError(f"unsupported field kind {kind!r}")

    def _merge(self, register: str, existing: Optional[dict], fields: dict) -> dict:
        spec = self._spec(register)
        by_name = {f["name"]: f for f in spec["fields"]}
        unknown = sorted(set(fields) - set(by_name))
        if unknown:
            raise GrcError(f"unknown field(s) for {spec['singular']}: {', '.join(unknown)}")
        rec = dict(existing or {})
        for name, value in fields.items():
            if value is None:
                continue
            if str(value).strip() == "":
                rec.pop(name, None)       # an empty value clears an optional field
                continue
            rec[name] = self._check_field(by_name[name], value)
        for f in spec["fields"]:
            if f["name"] not in rec and "default" in f:
                rec[f["name"]] = f["default"]
        for f in spec["fields"]:
            if f.get("required") and not rec.get(f["name"]):
                raise GrcError(f"{f['label']} is required")
        # register-specific rules
        if register == "scope_items" and rec["kind"] == "exclusion" and not rec.get("justification"):
            raise GrcError("an exclusion needs a justification")
        if register == "findings":
            if rec["status"] == "closed":
                rec.setdefault("closed", _today().isoformat())
            else:
                rec.pop("closed", None)
            if parse_date(rec["due"], "Due") < parse_date(rec["raised"], "Raised on"):
                raise GrcError("Due cannot be before the raised date")
        if register == "documents":
            if rec["status"] == "approved":
                rec.setdefault("approved", _today().isoformat())
                if not rec.get("next_review") or (existing is not None and "review_months" in fields and "next_review" not in fields):
                    rec["next_review"] = add_months(parse_date(rec["approved"]), rec["review_months"]).isoformat()
        if register == "audits" and rec.get("completed") and parse_date(rec["completed"], "Completed on") < parse_date(rec["planned"], "Planned for"):
            raise GrcError("Completed on cannot be before the planned date")
        return rec

    def add(self, register: str, actor: str, **fields) -> dict:
        actor = self._actor(actor)
        spec = self._spec(register)
        rec = self._merge(register, None, fields)
        g = self._ensure()
        table = g[register]
        n = len(table) + 1
        while f"{spec['id_prefix']}-{n:03d}" in table:
            n += 1
        rec_id = f"{spec['id_prefix']}-{n:03d}"
        out = {"id": rec_id, **rec}
        table[rec_id] = out
        label = out.get("title") or out.get("name") or out.get("type") or rec_id
        self._audit(actor, f"GRC_{register.upper()}_ADDED", rec_id, {"summary": label})
        return out

    def update(self, register: str, actor: str, rec_id: str, **fields) -> dict:
        actor = self._actor(actor)
        existing = self.get(register, rec_id)
        merged = self._merge(register, existing, fields)
        merged["id"] = rec_id
        changed = sorted(k for k in set(merged) | set(existing) if merged.get(k) != existing.get(k))
        self._g()[register][rec_id] = merged
        if changed:
            self._audit(actor, f"GRC_{register.upper()}_UPDATED", rec_id, {"changed": changed})
        return merged

    def remove(self, register: str, actor: str, rec_id: str) -> None:
        actor = self._actor(actor)
        self.get(register, rec_id)
        del self._g()[register][rec_id]
        # links to a removed document or evidence source go with it
        for st in (self.scope.data.get("workflow") or {}).values():
            for cc in st.get("common_controls", {}).values():
                if register == "documents":
                    for cat in DOC_CATEGORIES:
                        if rec_id in cc.get("documents", {}).get(cat, []):
                            cc["documents"][cat].remove(rec_id)
                if register == "evidence_sources" and rec_id in cc.get("evidence_sources", []):
                    cc["evidence_sources"].remove(rec_id)
        self._audit(actor, f"GRC_{register.upper()}_REMOVED", rec_id, {})

    # ---- links, scope statements, mapping review, roles ----------------------------------------------
    def link(self, system_id: Optional[str], actor: str, cc_id: str, policy: Iterable[str] = (),
             guideline: Iterable[str] = (), sop: Iterable[str] = (), evidence_sources: Iterable[str] = (),
             unlink: bool = False) -> dict:
        """Attach (or detach) policies, guidelines, SOPs and evidence sources to a common control."""
        sid, actor = self.wf.sid(system_id), self._actor(actor)
        cc = self.wf.cc(sid, cc_id)
        docs = cc.setdefault("documents", {c: [] for c in DOC_CATEGORIES})
        for cat in DOC_CATEGORIES:
            docs.setdefault(cat, [])
        changed = {}
        for cat, ids in (("policy", policy), ("guideline", guideline), ("sop", sop)):
            for doc_id in ids:
                doc = self.get("documents", doc_id)
                if doc["type"] != cat:
                    raise GrcError(f"{doc_id} is a {doc['type']}, not a {cat}")
                if unlink:
                    if doc_id in docs[cat]:
                        docs[cat].remove(doc_id)
                elif doc_id not in docs[cat]:
                    docs[cat].append(doc_id)
                changed.setdefault(cat, []).append(doc_id)
        srcs = cc.setdefault("evidence_sources", [])
        for src_id in evidence_sources:
            self.get("evidence_sources", src_id)
            if unlink:
                if src_id in srcs:
                    srcs.remove(src_id)
            elif src_id not in srcs:
                srcs.append(src_id)
            changed.setdefault("evidence_sources", []).append(src_id)
        if not changed:
            raise GrcError("nothing to link: give --policy, --guideline, --sop or --evidence-source")
        self._audit(actor, "GRC_LINKS_REMOVED" if unlink else "GRC_LINKS_ADDED", f"{sid}/{cc_id}", changed)
        return cc

    def set_scope_statement(self, actor: str, framework_id: str, statement: str, reviewed: Optional[str] = None) -> dict:
        actor = self._actor(actor)
        if framework_id not in self.lib.frameworks:
            raise GrcError(f"unknown framework {framework_id!r}")
        if not statement.strip():
            raise GrcError("a scope statement cannot be empty")
        reviewed = reviewed or _today().isoformat()
        parse_date(reviewed, "reviewed")
        g = self._ensure()
        g["framework_scopes"][framework_id] = {"statement": statement.strip(), "reviewed": reviewed}
        self._audit(actor, "GRC_SCOPE_STATEMENT_SET", framework_id, {"reviewed": reviewed})
        return g["framework_scopes"][framework_id]

    def review_scope(self, actor: str, date: Optional[str] = None) -> str:
        actor = self._actor(actor)
        date = date or _today().isoformat()
        parse_date(date, "date")
        self._ensure()["scope_reviewed"] = date
        self._audit(actor, "GRC_SCOPE_REVIEWED", ORG, {"date": date})
        return date

    def review_mappings(self, system_id: Optional[str], actor: str, cc_id: str, owner: str, date: Optional[str] = None) -> int:
        """Record the owner and review date of every requirement mapped to a common control."""
        sid, actor = self.wf.sid(system_id), self._actor(actor)
        self.wf.cc(sid, cc_id)
        if not owner.strip():
            raise GrcError("a mapping review needs an owner")
        date = date or _today().isoformat()
        parse_date(date, "date")
        members = self.wf.members(sid, cc_id)
        if not members:
            raise GrcError(f"{cc_id} has no mapped requirements")
        for cid in members:
            rec = self.wf._rec(sid, cid)
            rec["mapping_owner"] = owner.strip()
            rec["mapping_reviewed"] = date
        self._ensure()
        self._audit(actor, "GRC_MAPPINGS_REVIEWED", f"{sid}/{cc_id}", {"count": len(members), "date": date})
        return len(members)

    def set_roles(self, actor: str, role_id: str, names: Iterable[str]) -> List[str]:
        actor = self._actor(actor)
        if role_id not in {r["id"] for r in self.spec["roles"]}:
            raise GrcError(f"unknown role {role_id!r}; choose from {', '.join(r['id'] for r in self.spec['roles'])}")
        clean = []
        for n in names:
            n = str(n).strip()
            if n and n not in clean:
                clean.append(n)
        g = self._ensure()
        if clean:
            g["roles"][role_id] = clean
        else:
            g["roles"].pop(role_id, None)
        self._audit(actor, "GRC_ROLE_ASSIGNED", role_id, {"people": len(clean)})
        return clean

    def seed_evidence_sources(self, actor: str) -> int:
        """Add the evidence types from the framework notes (access reviews, scanners, SIEM, CI/CD, attestations)."""
        have = {(r["type"], r["source"]) for r in self.records("evidence_sources")}
        n = 0
        for d in self.spec["evidence_defaults"]:
            if (d["type"], d["source"]) not in have:
                self.add("evidence_sources", actor, **d)
                n += 1
        self._ensure()
        return n

    # ---- computed views ---------------------------------------------------------------------------------
    def _context(self, system_id: Optional[str]):
        sid = self.wf.sid(system_id)
        ccs = self.wf.state(sid)["common_controls"] if self.wf.enabled(sid) else {}
        eff = {cc_id: self.wf.effectiveness(sid, cc_id) for cc_id in ccs}
        current = {cc_id: e["state"] not in ("not_tested", "stale") for cc_id, e in eff.items()}
        return sid, ccs, eff, current

    def _at_target(self, sid: str, control_id: str, status: str) -> bool:
        target = self.wf.target_of(sid, control_id)[0] if self.wf.enabled(sid) else "implemented"
        order = ("not_started", "in_progress", "implemented", "verified")
        return order.index(status) >= order.index(target)

    def matrix(self, system_id: Optional[str]) -> List[dict]:
        """One row per applicable requirement: its control, policy, guideline, SOP, evidence, status and any issue."""
        sid, ccs, eff, current = self._context(system_id)
        st = self.settings()
        sources = {r["id"]: r for r in self.records("evidence_sources")}
        table = self.scope.data["decisions"].get(sid, {})
        today = _today()
        rows = []
        for c, d in self.scope.rows(sid):
            if not d["applicable"]:
                continue
            rec = table.get(c.id, {})
            cc_id = rec.get("common_control")
            cc = ccs.get(cc_id) if cc_id else None
            gap = rec.get("common_control_gap")
            docs = (cc or {}).get("documents") or {}
            policy, guideline, sop = (list(docs.get(k, [])) for k in DOC_CATEGORIES)
            src_ids = [s for s in (cc or {}).get("evidence_sources", []) if s in sources]
            state = eff[cc_id]["state"] if cc else None
            if not cc:
                status = "Gap" if gap else "Unmapped"
            elif d["status"] in DONE:
                status = "Implemented" if current[cc_id] else "Partial"
            elif d["status"] == "in_progress":
                status = "Partial"
            else:
                status = "Not started"
            owner = rec.get("mapping_owner") or d["owner"] or (cc or {}).get("owner") or ""
            reviewed = rec.get("mapping_reviewed")
            issues = []
            if not cc and not gap:
                issues.append("unmapped")
            if cc:
                if not policy:
                    issues.append("no_policy")
                if not sop:
                    issues.append("no_sop")
                if not src_ids:
                    issues.append("no_evidence_source")
                if not owner:
                    issues.append("no_mapping_owner")
                if not reviewed:
                    issues.append("no_review_date")
                elif add_months(parse_date(reviewed), st["mapping_review_months"]) < today:
                    issues.append("review_overdue")
            rows.append({
                "requirement_id": c.id, "framework_id": c.framework_id, "framework": self.lib.frameworks[c.framework_id].name,
                "ref": c.ref, "clause": c.ref, "requirement": c.title, "domain": self.lib.domains[c.domain_id].name,
                "requirement_status": d["status"], "control_id": cc_id if cc else "", "control_title": cc["title"] if cc else "",
                "gap_reason": gap or "", "policy": policy, "guideline": guideline, "sop": sop,
                "evidence_sources": src_ids, "evidence": ", ".join(sources[s]["type"] for s in src_ids),
                "evidence_state": state, "status": status, "mapping_owner": owner, "mapping_reviewed": reviewed or "",
                "issues": issues})
        return rows

    @staticmethod
    def matrix_summary(rows: List[dict]) -> dict:
        by_status: Dict[str, int] = {}
        by_issue: Dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            for i in r["issues"]:
                by_issue[i] = by_issue.get(i, 0) + 1
        return {"requirements": len(rows), "by_status": dict(sorted(by_status.items())), "by_issue": dict(sorted(by_issue.items()))}

    def matrix_csv(self, system_id: Optional[str]) -> str:
        from .spreadsheet import csv_line
        lines = [csv_line(MATRIX_COLUMNS)]
        for r in self.matrix(system_id):
            cells = {"requirement_id": r["requirement_id"], "framework": r["framework"], "clause": r["ref"], "requirement": r["requirement"],
                     "control_id": r["control_id"] or ("GAP: " + r["gap_reason"] if r["gap_reason"] else ""),
                     "policy": "; ".join(r["policy"]), "guideline": "; ".join(r["guideline"]), "sop": "; ".join(r["sop"]),
                     "evidence": r["evidence"], "status": r["status"], "mapping_owner": r["mapping_owner"],
                     "mapping_reviewed": r["mapping_reviewed"], "issues": "; ".join(ISSUE_TEXT[i] for i in r["issues"])}
            lines.append(csv_line(cells[k] for k in MATRIX_COLUMNS))
        return "\r\n".join(lines) + "\r\n"

    def coverage(self, system_id: Optional[str]) -> dict:
        """Coverage per framework, by one stated method (docs/GRC.md).

        coverage %    = requirements implemented AND evidenced / requirements applicable, x 100
        incremental % = requirements of the framework covered through a control that also serves the anchor
                        framework / requirements applicable, x 100 (how much existing work is reused)
        """
        sid, ccs, eff, current = self._context(system_id)
        st = self.settings()
        rows = self.matrix(sid)
        fws = self.scope.system(sid)["frameworks"]
        anchor = st["anchor_framework"] if st["anchor_framework"] in fws else None
        cc_fws: Dict[str, set] = {}
        for r in rows:
            if r["control_id"]:
                cc_fws.setdefault(r["control_id"], set()).add(r["framework_id"])

        def is_covered(r: dict) -> bool:
            return bool(r["control_id"]) and r["requirement_status"] in DONE and current.get(r["control_id"], False)

        out, req_t, cov_t = [], 0, 0
        for fid in fws:
            mine = [r for r in rows if r["framework_id"] == fid]
            required = len(mine)
            mapped = sum(1 for r in mine if r["control_id"])
            implemented = sum(1 for r in mine if r["requirement_status"] in DONE)
            covered = sum(1 for r in mine if is_covered(r))
            reused = None
            if anchor and fid != anchor:
                reused = sum(1 for r in mine if is_covered(r) and anchor in cc_fws.get(r["control_id"], set()))
            target = st["coverage_targets"].get(fid)
            pct = _pct(covered, required)
            out.append({"framework_id": fid, "name": self.lib.frameworks[fid].name, "required": required, "mapped": mapped,
                        "implemented": implemented, "covered": covered, "coverage_pct": pct, "mapped_pct": _pct(mapped, required),
                        "incremental": reused, "incremental_pct": _pct(reused, required) if reused is not None else None,
                        "target": target, "meets_target": (None if target is None or pct is None else pct >= target)})
            req_t += required
            cov_t += covered
        return {"anchor": anchor, "frameworks": out, "overall": {"required": req_t, "covered": cov_t, "coverage_pct": _pct(cov_t, req_t)}}

    def kpis(self, system_id: Optional[str]) -> List[dict]:
        sid, ccs, eff, current = self._context(system_id)
        st = self.settings()
        today = _today()
        rows = self.matrix(sid)
        mapped = sum(1 for r in rows if r["control_id"])
        gaps = sum(1 for r in rows if r["status"] == "Gap")
        findings = self.records("findings")
        open_f = [f for f in findings if f.get("status") == "open"]
        past_due = [f for f in open_f if parse_date(f["due"]) < today]
        crit = [f for f in past_due if f["severity"] == "critical"]
        docs = [d for d in self.records("documents") if d.get("status") == "approved"]
        cur_docs = [d for d in docs if d.get("next_review") and parse_date(d["next_review"]) >= today]
        allowed = APPETITE_ALLOWED[st["risk_appetite"]]
        risky = [r for r in self.records("risks") if r.get("status") == "open" and RATINGS.index(r["residual"]) > allowed
                 and not r.get("treatment_plan") and r.get("treatment_status", "none") == "none"]
        cov = self.coverage(sid)
        values = {
            "requirements_mapped": (_pct(mapped, len(rows)), f"{mapped} of {len(rows)} requirements mapped; {gaps} recorded as gaps"),
            "controls_current_evidence": (_pct(sum(current.values()), len(ccs)),
                                          f"{sum(current.values())} of {len(ccs)} controls have current evidence"),
            "findings_past_due_critical": ((len(crit) if findings or self.records("audits") else None),
                                          f"{len(past_due)} open finding(s) past due in total; {len(open_f)} open" if findings or self.records("audits")
                                          else "no audits or findings recorded yet"),
            "policy_review_currency": (_pct(len(cur_docs), len(docs)), f"{len(cur_docs)} of {len(docs)} approved documents are within their review cycle"),
            "risks_above_appetite": ((len(risky) if self.records("risks") else None),
                                     f"appetite is {st['risk_appetite']}; {len(risky)} open risk(s) above it have no treatment plan" if self.records("risks")
                                     else "no risks recorded yet"),
            "cross_framework_coverage": (cov["overall"]["coverage_pct"], f"{cov['overall']['covered']} of {cov['overall']['required']} requirements implemented and evidenced"),
        }
        out = []
        for k in self.spec["kpis"]:
            value, detail = values[k["id"]]
            if value is None:
                status = "no_data"
            elif k["op"] is None:
                status = "info"
            else:
                met = value >= k["target"] if k["op"] == ">=" else value == k["target"]
                status = "met" if met else "not_met"
            out.append({"id": k["id"], "name": k["name"], "type": k["type"], "value": value, "unit": k["unit"],
                        "target_text": k["target_text"], "status": status, "detail": detail})
        return out

    def streams(self, system_id: Optional[str]) -> List[dict]:
        """ISO/IEC 42001 requirements grouped into streams by the rule set in grc_spec.json (a documented judgement)."""
        sid, ccs, eff, current = self._context(system_id)
        rows = [r for r in self.matrix(sid) if r["framework_id"] == "iso-42001"]
        assign: Dict[str, str] = {}
        for r in rows:
            best, best_stream = -1, None
            for s in self.spec["streams"]:
                for pat in s["refs"]:
                    spec_ = _matches(pat, r["ref"])
                    if spec_ is not None and spec_ > best:
                        best, best_stream = spec_, s["id"]
            assign[r["requirement_id"]] = best_stream or "unassigned"
        out = []
        for s in self.spec["streams"]:
            mine = [r for r in rows if assign[r["requirement_id"]] == s["id"]]
            mapped = sum(1 for r in mine if r["control_id"])
            impl = sum(1 for r in mine if r["requirement_status"] in DONE)
            cov = sum(1 for r in mine if r["control_id"] and r["requirement_status"] in DONE and current.get(r["control_id"], False))
            out.append({"id": s["id"], "name": s["name"], "focus": s["focus"], "delivered_through": s["delivered_through"],
                        "requirements": len(mine), "mapped": mapped, "implemented": impl, "covered": cov,
                        "mapped_pct": _pct(mapped, len(mine)), "implemented_pct": _pct(impl, len(mine)), "coverage_pct": _pct(cov, len(mine))})
        stray = [r["requirement_id"] for r in rows if assign[r["requirement_id"]] == "unassigned"]
        if stray:
            out.append({"id": "unassigned", "name": "Unassigned", "focus": "", "delivered_through": "", "requirements": len(stray),
                        "mapped": 0, "implemented": 0, "covered": 0, "mapped_pct": None, "implemented_pct": None, "coverage_pct": None})
        return out

    def _wf_marker(self, sid: str, key: str):
        return self.wf.state(sid)["markers"].get(key) if self.wf.enabled(sid) else None

    def lifecycle(self, system_id: Optional[str]) -> List[dict]:
        """The ten lifecycle steps, each judged from the data (never ticked by hand)."""
        sid, ccs, eff, current = self._context(system_id)
        st = self.settings()
        today = _today()
        s = self.scope.system(sid)
        rows = self.matrix(sid)
        items = self.records("scope_items")
        kinds = lambda *ks: sum(1 for i in items if i["kind"] in ks)  # noqa: E731
        regs = kinds("regulation")
        reviewed = self._g().get("scope_reviewed")
        scope_fresh = bool(reviewed) and add_months(parse_date(reviewed), st["scope_review_months"]) >= today
        mapped = sum(1 for r in rows if r["control_id"])
        unmapped = sum(1 for r in rows if r["status"] == "Unmapped")
        used = {r["control_id"] for r in rows if r["control_id"]}
        incomplete = sum(1 for cid in used if not (ccs[cid].get("documents") or {}).get("policy")
                         or not (ccs[cid].get("documents") or {}).get("sop"))
        risks = self.records("risks")
        gap_run = self._wf_marker(sid, "gap_run_at")
        at_target = sum(1 for r in rows if self._at_target(sid, r["requirement_id"], r["requirement_status"]))
        kp = {k["id"]: k for k in self.kpis(sid)}
        audits = self.records("audits")
        done_internal = [a for a in audits if a["kind"] == "internal" and a.get("completed")]
        done_external = [a for a in audits if a["kind"] == "external" and a.get("completed")]
        done_review = [a for a in audits if a["kind"] == "management_review" and a.get("completed")]
        open_past = sum(1 for f in self.records("findings") if f.get("status") == "open" and parse_date(f["due"]) < today)
        report_at = self._wf_marker(sid, "report_at") or self._g().get("markers", {}).get("report_at")
        steps = [
            (len(s["frameworks"]) >= 1 and regs >= 1, f"{len(s['frameworks'])} framework(s) selected; {regs} regulation(s) recorded",
             "Record the regulations that apply in the scope register."),
            (kinds("business_unit", "department") >= 1 and kinds("system", "ai_system", "data_set") >= 1 and scope_fresh,
             f"{kinds('business_unit', 'department')} business unit(s)/department(s), {kinds('system', 'ai_system', 'data_set')} system(s)/data set(s); "
             + ("scope reviewed " + reviewed if reviewed else "scope not yet reviewed"),
             "Fill the scope register and mark the scope reviewed."),
            (len(rows) > 0, f"{len(rows)} requirements from {len(s['frameworks'])} framework(s)", "Select frameworks for the system."),
            (len(rows) > 0 and unmapped == 0 and incomplete == 0,
             f"{mapped} of {len(rows)} requirements mapped; {unmapped} unmapped; {incomplete} control(s) lack a policy or SOP",
             "Map every requirement to a control (or record a gap) and link a policy and SOP to each control."),
            (gap_run is not None and len(risks) >= 1, f"gap analysis {'run' if gap_run else 'not run'}; {len(risks)} risk(s) registered",
             "Run the gap analysis and record risks with owners."),
            (len(rows) > 0 and at_target == len(rows) and (kp["risks_above_appetite"]["value"] or 0) == 0,
             f"{at_target} of {len(rows)} requirements at target; {kp['risks_above_appetite']['value'] or 0} untreated risk(s) above appetite",
             "Implement the open requirements and treat risks above appetite."),
            (kp["controls_current_evidence"]["value"] is not None and kp["controls_current_evidence"]["value"] >= 95,
             kp["controls_current_evidence"]["detail"], "Ingest test results so each control has current evidence."),
            (len(done_internal) >= 1, f"{len(done_internal)} internal and {len(done_external)} external audit(s) completed",
             "Plan and complete an internal audit, then an external one."),
            (report_at is not None, "a report has been generated" if report_at else "no report generated yet",
             "Generate the GRC report for leadership."),
            (len(done_review) >= 1 and open_past == 0, f"{len(done_review)} management review(s) completed; {open_past} finding(s) past due",
             "Hold a management review and close overdue findings."),
        ]
        return [{"n": l["n"], "id": l["id"], "title": l["title"], "done": bool(done), "detail": detail, "hint": hint}
                for l, (done, detail, hint) in zip(self.spec["lifecycle"], steps)]

    def artifacts(self, system_id: Optional[str]) -> List[dict]:
        """The artifacts checklist, judged from the data: ready, partial or missing."""
        sid, ccs, eff, current = self._context(system_id)
        s = self.scope.system(sid)
        rows = self.matrix(sid)
        items = self.records("scope_items")
        docs = self.records("documents")
        types = {d["type"] for d in docs}
        sources = self.records("evidence_sources")
        with_results = sum(1 for e in eff.values() if e["state"] != "not_tested")
        kvals = sum(1 for k in self.kpis(sid) if k["value"] is not None)
        audits, findings = self.records("audits"), self.records("findings")
        fscopes = self._g().get("framework_scopes", {})
        mapped = sum(1 for r in rows if r["control_id"])
        regs = sum(1 for i in items if i["kind"] == "regulation")

        def grade(full: bool, some: bool) -> str:
            return "ready" if full else "partial" if some else "missing"

        vals = [
            (grade(bool(s["frameworks"]) and regs >= 1, bool(s["frameworks"])), f"{len(s['frameworks'])} framework(s), {regs} regulation(s)"),
            (grade(all(f in fscopes for f in s["frameworks"]), any(f in fscopes for f in s["frameworks"])),
             f"{sum(1 for f in s['frameworks'] if f in fscopes)} of {len(s['frameworks'])} framework(s) have a scope statement"),
            ("ready", f"{len(rows)} requirements (from the dataset)"),
            (grade(len(ccs) >= 1, False), f"{len(ccs)} common control(s)"),
            (grade(len(rows) > 0 and mapped == len(rows), mapped > 0), f"{mapped} of {len(rows)} requirements mapped"),
            (grade(types >= set(DOC_CATEGORIES), bool(types)), f"{len(docs)} document(s): {', '.join(sorted(types)) or 'none'}"),
            (grade(any(r.get("business_unit") for r in self.records("risks")), False), f"{len(self.records('risks'))} risk(s)"),
            (grade(len(sources) >= 1 and with_results >= 1, len(sources) >= 1 or with_results >= 1),
             f"{len(sources)} evidence source(s); {with_results} control(s) with results"),
            (grade(kvals >= 3, kvals >= 1), f"{kvals} of {len(self.spec['kpis'])} KPIs/KRIs have data"),
            (grade(len(audits) >= 1 and (len(findings) >= 1 or any(a.get("completed") for a in audits)), len(audits) >= 1 or len(findings) >= 1),
             f"{len(audits)} audit(s), {len(findings)} finding(s)"),
        ]
        return [{"id": a["id"], "title": a["title"], "status": g, "detail": d} for a, (g, d) in zip(self.spec["artifacts"], vals)]

    def roles(self) -> List[dict]:
        assigned = self._g().get("roles", {})
        return [{**r, "people": list(assigned.get(r["id"], []))} for r in self.spec["roles"]]

    def report(self, system_id: Optional[str], actor: Optional[str] = None, record: bool = False) -> dict:
        sid = self.wf.sid(system_id)
        rows = self.matrix(sid)
        out = {"system": sid, "organisation": self.scope.data["organization"], "as_of": _today().isoformat(),
               "lifecycle": self.lifecycle(sid), "kpis": self.kpis(sid), "coverage": self.coverage(sid),
               "matrix": self.matrix_summary(rows), "artifacts": self.artifacts(sid), "streams": self.streams(sid)}
        if record:
            self._ensure()["markers"]["report_at"] = _stamp()
            self._audit(self._actor(actor or "system"), "GRC_REPORT_GENERATED", sid, {"as_of": out["as_of"]})
        return out

    def report_markdown(self, system_id: Optional[str], actor: Optional[str] = None, record: bool = True) -> str:
        r = self.report(system_id, actor, record=record)
        s = self.scope.system(system_id)
        fmt = lambda v, u: "no data" if v is None else f"{v}{u}"  # noqa: E731
        lines = [f"# GRC report: {s['name']}", "", f"Organisation: {r['organisation']}  ", f"As of: {r['as_of']}", "",
                 "## KPIs and KRIs", "", "| Metric | Type | Value | Target | Status |", "|---|---|---:|---|---|"]
        label = {"met": "met", "not_met": "not met", "no_data": "no data", "info": "for information"}
        for k in r["kpis"]:
            lines.append(f"| {k['name']} | {k['type']} | {fmt(k['value'], k['unit'])} | {k['target_text']} | {label[k['status']]} |")
        lines += ["", "## Coverage by framework", "",
                  f"Method: coverage = requirements implemented and evidenced / applicable requirements. Incremental = covered through a control that also serves the anchor framework ({r['coverage']['anchor'] or 'none'}).",
                  "", "| Framework | Requirements | Mapped | Implemented | Covered | Coverage | Incremental | Target |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for f in r["coverage"]["frameworks"]:
            lines.append(f"| {f['name']} | {f['required']} | {f['mapped']} | {f['implemented']} | {f['covered']} | {fmt(f['coverage_pct'], '%')} | "
                         f"{fmt(f['incremental_pct'], '%') if f['incremental'] is not None else 'n/a'} | {fmt(f['target'], '%') if f['target'] is not None else '-'} |")
        o = r["coverage"]["overall"]
        lines += [f"| **Overall** | {o['required']} |  |  | {o['covered']} | {fmt(o['coverage_pct'], '%')} |  |  |", "",
                  "## Lifecycle", ""]
        lines += [f"{i['n']}. [{'x' if i['done'] else ' '}] {i['title']}: {i['detail']}" for i in r["lifecycle"]]
        lines += ["", "## Mapping matrix", "", f"{r['matrix']['requirements']} requirements. "
                  + ", ".join(f"{k}: {v}" for k, v in r["matrix"]["by_status"].items()) + ".", ""]
        if r["matrix"]["by_issue"]:
            lines += ["Issues: " + "; ".join(f"{ISSUE_TEXT[k]}: {v}" for k, v in r["matrix"]["by_issue"].items()), ""]
        lines += ["## Artifacts", ""] + [f"- {a['title']}: {a['status']} ({a['detail']})" for a in r["artifacts"]]
        if any(x["requirements"] for x in r["streams"]):
            lines += ["", "## ISO/IEC 42001 streams", "", "| Stream | Requirements | Mapped | Implemented | Covered |", "|---|---:|---:|---:|---:|"]
            for x in r["streams"]:
                lines.append(f"| {x['name']} | {x['requirements']} | {fmt(x['mapped_pct'], '%')} | {fmt(x['implemented_pct'], '%')} | {fmt(x['coverage_pct'], '%')} |")
        lines += ["", "_Planning aid and working record, not an attestation of compliance. Percentages are only as good as the data entered._", ""]
        return "\n".join(lines)


# ---- validation (called from Scope.validate) -----------------------------------------------------------------
def validate_grc(scope: Scope) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    g = scope.data.get("grc")
    if not g:
        return errors, warnings
    grc = Grc(scope)
    for name, spec in grc.spec["registers"].items():
        table = g.get(name, {})
        if not isinstance(table, dict):
            errors.append(f"grc/{name}: must be an object keyed by id")
            continue
        for rid, rec in table.items():
            if rec.get("id") != rid:
                errors.append(f"grc/{name}/{rid}: id does not match its key")
            try:
                tmp = {k: v for k, v in rec.items() if k != "id"}
                grc._merge(name, None, tmp)
            except GrcError as e:
                errors.append(f"grc/{name}/{rid}: {e}")
    docs = g.get("documents", {})
    sources = g.get("evidence_sources", {})
    for sid, st in (scope.data.get("workflow") or {}).items():
        for cc_id, cc in st.get("common_controls", {}).items():
            for cat in DOC_CATEGORIES:
                for doc_id in (cc.get("documents") or {}).get(cat, []):
                    if doc_id not in docs:
                        errors.append(f"{sid}/{cc_id}: links unknown document {doc_id!r}")
                    elif docs[doc_id]["type"] != cat:
                        errors.append(f"{sid}/{cc_id}: {doc_id} is linked as a {cat} but is a {docs[doc_id]['type']}")
            for src in cc.get("evidence_sources", []):
                if src not in sources:
                    errors.append(f"{sid}/{cc_id}: links unknown evidence source {src!r}")
    for fw in g.get("framework_scopes", {}):
        if fw not in grc.lib.frameworks:
            errors.append(f"grc/framework_scopes: unknown framework {fw!r}")
    known_roles = {r["id"] for r in grc.spec["roles"]}
    for role in g.get("roles", {}):
        if role not in known_roles:
            errors.append(f"grc/roles: unknown role {role!r}")
    anchor = g.get("settings", {}).get("anchor_framework")
    if anchor and anchor not in grc.lib.frameworks:
        errors.append(f"grc/settings: unknown anchor framework {anchor!r}")
    return errors, warnings
