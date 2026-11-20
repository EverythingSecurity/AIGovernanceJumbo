# SPDX-License-Identifier: Apache-2.0
"""Client engagement layer, phase 2: scoping, applicability rules, recommendations, review and assignment.

A consulting team ("principal") onboards a client, sends a scoping questionnaire, gets framework
recommendations from a rules engine, reviews them and finalises the applicable framework set.

This is an *offline* layer: everything lives in the same private scope file under `engagement`, with
no accounts, no server and no uploads. Names and roles are labels you type, not authenticated
identities, and the audit trail is tamper-evident, not immutable. The browser twin is
`site/engagement.js`; tests keep the two identical.

Rules and the questionnaire are data (`engagement_spec.json`); a scope file can add or override rules.
Only frameworks that exist in the library are recommended; a rule that points at one that does not is
reported as skipped, never silently dropped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from .grc import GrcError, parse_date
from .scope import Scope
from .workflow import Workflow, WorkflowError, _stamp

SPEC_FILE = Path(__file__).with_name("engagement_spec.json")
SCHEMA_VERSION = "1.3"
ORG = "(organisation)"
ROLE = "ENGAGEMENT_OFFICE"
RANK = {"low": 0, "medium": 1, "high": 2}
RULE_ID = re.compile(r"^R-[A-Z0-9-]{1,24}$")
FRAMEWORK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
CLIENT_FIELDS = ("name", "sector", "country", "size", "contributor")


class EngagementError(WorkflowError):
    """Raised for invalid engagement operations; the message is safe to show to users."""


def load_spec() -> dict:
    return json.loads(SPEC_FILE.read_text(encoding="utf-8"))


# ---- rule conditions: pure functions, deterministic ---------------------------------------------
def eval_when(cond: dict, answers: Dict[str, object]) -> bool:
    """Evaluate a condition tree against {question id: value}. An unanswered question never matches."""
    if "all" in cond:
        return all(eval_when(c, answers) for c in cond["all"])
    if "any" in cond:
        return any(eval_when(c, answers) for c in cond["any"])
    if "not" in cond:
        return not eval_when(cond["not"], answers)
    ans = answers.get(cond["q"])
    if ans is None:
        return False
    op, want = cond["op"], cond["value"]
    if op == "is":
        return isinstance(ans, str) and ans == want
    if op == "has":
        return isinstance(ans, list) and want in ans
    if isinstance(ans, list):                      # op == "in"
        return any(x in want for x in ans)
    return ans in want


def when_questions(cond: dict) -> List[str]:
    if "all" in cond:
        out = [q for c in cond["all"] for q in when_questions(c)]
    elif "any" in cond:
        out = [q for c in cond["any"] for q in when_questions(c)]
    elif "not" in cond:
        out = when_questions(cond["not"])
    else:
        out = [cond["q"]]
    return sorted(set(out))


class Engagement:
    """Engagement operations over a loaded `Scope`. Callers save the scope afterwards."""

    def __init__(self, scope: Scope):
        self.scope = scope
        self.lib = scope.lib
        self.wf = Workflow(scope)
        self.spec = load_spec()
        self.questions = {q["id"]: q for q in self.spec["questionnaire"]["questions"]}

    # ---- state -------------------------------------------------------------------------------
    def enabled(self) -> bool:
        return bool(self.scope.data.get("engagement"))

    def _e(self) -> dict:
        return self.scope.data.get("engagement") or {}

    def _ensure(self) -> dict:
        e = self.scope.data.setdefault("engagement", {})
        e.setdefault("client", {"name": self.scope.data.get("organization", ""), "sector": None, "country": None, "size": None,
                                "contributor": None, "status": "invited"})
        e.setdefault("scoping", {"questionnaire_version": self.spec["questionnaire"]["version"], "status": "not_started",
                                 "responses": {}, "delegations": {}, "submitted_at": None, "submitted_by": None})
        e.setdefault("rules", {"version": 1, "custom": {}, "disabled": []})
        e.setdefault("recommendation", None)
        e.setdefault("review", {})
        e.setdefault("applicable", None)
        if self.scope.data.get("schema_version") in (None, "1.0", "1.1", "1.2"):
            self.scope.data["schema_version"] = SCHEMA_VERSION
        return e

    def _audit(self, actor: str, action: str, target: str, details: Optional[dict] = None) -> None:
        self.wf.audit(ORG, actor, ROLE, action, target, details or {})

    def _actor(self, actor: str) -> str:
        return self.wf._check_actor(actor)

    def _need(self) -> dict:
        if not self.enabled():
            raise EngagementError("the engagement is not started; set the client first (engagement client set)")
        return self._e()

    # ---- client and onboarding ---------------------------------------------------------------
    def set_client(self, actor: str, fields: Dict[str, str]) -> dict:
        actor = self._actor(actor)
        bad = [k for k in fields if k not in CLIENT_FIELDS]
        if bad:
            raise EngagementError(f"unknown client field(s): {', '.join(sorted(bad))}; use {', '.join(CLIENT_FIELDS)}")
        new = {}
        for k, v in fields.items():
            v = (v or "").strip() if isinstance(v, str) else v
            if not v:
                raise EngagementError(f"client {k} cannot be empty")
            if k == "sector" and v not in self.spec["sectors"]:
                raise EngagementError(f"unknown sector {v!r}; choose from {', '.join(self.spec['sectors'])}")
            if k == "size" and v not in self.spec["sizes"]:
                raise EngagementError(f"unknown size {v!r}; choose from {', '.join(self.spec['sizes'])}")
            new[k] = v
        e = self._ensure()
        e["client"].update(new)
        self._audit(actor, "ENGAGEMENT_CLIENT_SET", e["client"]["name"] or "client", {"fields": sorted(new)})
        return e["client"]

    def onboard(self, actor: str) -> dict:
        actor = self._actor(actor)
        e = self._need()
        c = e["client"]
        missing = [k for k in CLIENT_FIELDS if not c.get(k)]
        if missing:
            raise EngagementError(f"complete the client profile first; missing: {', '.join(missing)}")
        if c["status"] == "onboarded":
            raise EngagementError("the client is already onboarded")
        c["status"] = "onboarded"
        self._audit(actor, "ENGAGEMENT_ONBOARDED", c["name"], {"contributor": c["contributor"]})
        return c

    # ---- scoping questionnaire ---------------------------------------------------------------
    def questionnaire(self) -> List[dict]:
        sc = self._e().get("scoping") or {}
        resp, dele = sc.get("responses", {}), sc.get("delegations", {})
        out = []
        for q in self.spec["questionnaire"]["questions"]:
            r = resp.get(q["id"])
            d = dele.get(q["id"])
            out.append({**q, "answer": r["value"] if r else None, "answered_by": r["by"] if r else None,
                        "answered_at": r["at"] if r else None, "delegated_to": d["to"] if d else None,
                        "due": d["due"] if d else None})
        return out

    def progress(self) -> dict:
        qs = self.questionnaire()
        req = [q for q in qs if q["required"]]
        done = [q for q in req if q["answer"] is not None]
        status = (self._e().get("scoping") or {}).get("status", "not_started")
        return {"status": status, "questions": len(qs), "answered": sum(1 for q in qs if q["answer"] is not None),
                "required": len(req), "required_answered": len(done),
                "missing": [q["id"] for q in req if q["answer"] is None]}

    def _unlocked(self, e: dict) -> None:
        if e["client"]["status"] != "onboarded":
            raise EngagementError("onboard the client before scoping (engagement client onboard)")
        if e["scoping"]["status"] == "submitted":
            raise EngagementError("the scoping answers are submitted and locked; reopen them first (engagement reopen --reason ...)")

    def _normalise(self, q: dict, value) -> object:
        kind = q["kind"]
        if kind == "yes_no":
            if value not in ("yes", "no"):
                raise EngagementError(f"{q['id']}: answer yes or no")
            return value
        if kind == "single":
            if value not in q["options"]:
                raise EngagementError(f"{q['id']}: choose one of {', '.join(q['options'])}")
            return value
        if kind == "multi":
            vals = [value] if isinstance(value, str) else value
            if not isinstance(vals, list) or not vals:
                raise EngagementError(f"{q['id']}: choose at least one of {', '.join(q['options'])}")
            bad = [v for v in vals if v not in q["options"]]
            if bad:
                raise EngagementError(f"{q['id']}: unknown option(s) {', '.join(map(str, bad))}; choose from {', '.join(q['options'])}")
            return sorted(set(vals))
        text = (value or "").strip() if isinstance(value, str) else ""
        if not text or len(text) > 500:
            raise EngagementError(f"{q['id']}: enter text of 1 to 500 characters")
        return text

    def answer(self, actor: str, qid: str, value) -> object:
        actor = self._actor(actor)
        e = self._need()
        q = self.questions.get(qid)
        if q is None:
            raise EngagementError(f"unknown question {qid!r}")
        self._unlocked(e)
        v = self._normalise(q, value)
        e["scoping"]["responses"][qid] = {"value": v, "by": actor, "at": _stamp()}
        e["scoping"]["status"] = "in_progress"
        self._audit(actor, "ENGAGEMENT_ANSWERED", qid, {"answer": v if isinstance(v, str) else list(v)})
        return v

    def delegate(self, actor: str, qid: str, to: str, due: Optional[str] = None) -> dict:
        actor = self._actor(actor)
        e = self._need()
        if qid not in self.questions:
            raise EngagementError(f"unknown question {qid!r}")
        self._unlocked(e)
        to = (to or "").strip()
        if not to:
            raise EngagementError("say who the question is delegated to")
        if due is not None:
            try:
                parse_date(due, "due date")
            except GrcError as ex:
                raise EngagementError(str(ex)) from None
        e["scoping"]["delegations"][qid] = {"to": to, "due": due}
        self._audit(actor, "ENGAGEMENT_DELEGATED", qid, {"to": to, "due": due})
        return e["scoping"]["delegations"][qid]

    def submit_scoping(self, actor: str) -> dict:
        actor = self._actor(actor)
        e = self._need()
        self._unlocked(e)
        miss = self.progress()["missing"]
        if miss:
            raise EngagementError(f"{len(miss)} required question(s) are unanswered: {', '.join(miss)}")
        s = e["scoping"]
        s["status"], s["submitted_at"], s["submitted_by"] = "submitted", _stamp(), actor
        self._audit(actor, "ENGAGEMENT_SCOPING_SUBMITTED", "scoping", {"answers": len(s["responses"])})
        return s

    def reopen_scoping(self, actor: str, reason: str) -> dict:
        actor = self._actor(actor)
        e = self._need()
        reason = (reason or "").strip()
        if not reason:
            raise EngagementError("a reason is required to reopen the scoping answers")
        if e["scoping"]["status"] != "submitted":
            raise EngagementError("the scoping answers are not submitted")
        s = e["scoping"]
        s["status"], s["submitted_at"], s["submitted_by"] = "in_progress", None, None
        dropped = bool(e["recommendation"] or e["review"] or e["applicable"])
        e["recommendation"], e["review"], e["applicable"] = None, {}, None
        self._audit(actor, "ENGAGEMENT_SCOPING_REOPENED", "scoping", {"reason": reason, "cleared_recommendations": dropped})
        return s

    # ---- rules -------------------------------------------------------------------------------
    def _check_when(self, cond, depth: int = 0) -> None:
        if not isinstance(cond, dict) or depth > 8:
            raise EngagementError("a rule condition must be an object (at most 8 levels deep)")
        keys = set(cond)
        if keys in ({"all"}, {"any"}):
            k = next(iter(keys))
            if not isinstance(cond[k], list) or not cond[k]:
                raise EngagementError(f"'{k}' needs a non-empty list of conditions")
            for c in cond[k]:
                self._check_when(c, depth + 1)
        elif keys == {"not"}:
            self._check_when(cond["not"], depth + 1)
        elif keys == {"q", "op", "value"}:
            q = self.questions.get(cond["q"])
            if q is None:
                raise EngagementError(f"condition refers to unknown question {cond['q']!r}")
            if cond["op"] not in ("is", "has", "in"):
                raise EngagementError(f"unknown operator {cond['op']!r}; use is, has or in")
            if cond["op"] == "has" and q["kind"] != "multi":
                raise EngagementError(f"'has' needs a multi-choice question; {q['id']} is {q['kind']}")
            if cond["op"] == "is" and q["kind"] == "multi":
                raise EngagementError(f"'is' needs a single-answer question; use has or in for {q['id']}")
            if cond["op"] == "in" and (not isinstance(cond["value"], list) or not cond["value"]):
                raise EngagementError("'in' needs a non-empty list of values")
        else:
            raise EngagementError("a condition is {all: [...]}, {any: [...]}, {not: ...} or {q, op, value}")

    def effective_rules(self) -> List[dict]:
        r = (self._e().get("rules") or {"custom": {}, "disabled": []})
        seed = {x["id"]: x for x in self.spec["rules"]}
        merged = {**{k: {**v, "source": "seed"} for k, v in seed.items()},
                  **{k: {**v, "source": "custom"} for k, v in r.get("custom", {}).items()}}
        off = set(r.get("disabled", []))
        return [{**merged[k], "disabled": k in off} for k in sorted(merged)]

    def rule_set(self, actor: str, rule: dict) -> dict:
        actor = self._actor(actor)
        if not isinstance(rule, dict):
            raise EngagementError("a rule must be an object")
        rid = rule.get("id")
        if not isinstance(rid, str) or not RULE_ID.match(rid):
            raise EngagementError("rule id must look like R-MY-RULE (capitals, digits, dashes)")
        if set(rule) - {"id", "framework", "confidence", "weight", "rationale", "when"}:
            raise EngagementError("a rule has: id, framework, when, confidence, weight, rationale")
        fw = rule.get("framework")
        if not isinstance(fw, str) or not FRAMEWORK_ID.match(fw):
            raise EngagementError("rule framework must be a framework id such as iso-42001")
        if rule.get("confidence") not in RANK:
            raise EngagementError(f"rule confidence must be one of {', '.join(RANK)}")
        w = rule.get("weight")
        if not isinstance(w, int) or isinstance(w, bool) or not 1 <= w <= 100:
            raise EngagementError("rule weight must be a whole number from 1 to 100")
        why = rule.get("rationale")
        if not isinstance(why, str) or not why.strip():
            raise EngagementError("a rule needs a rationale")
        self._check_when(rule.get("when"))
        e = self._ensure()
        clean = {"id": rid, "framework": fw, "confidence": rule["confidence"], "weight": w, "rationale": why.strip(), "when": rule["when"]}
        e["rules"]["custom"][rid] = clean
        e["rules"]["version"] += 1
        self._audit(actor, "ENGAGEMENT_RULE_SET", rid, {"framework": fw, "rules_version": e["rules"]["version"]})
        return clean

    def rule_disable(self, actor: str, rid: str, disabled: bool = True) -> dict:
        actor = self._actor(actor)
        if rid not in {r["id"] for r in self.effective_rules()}:
            raise EngagementError(f"unknown rule {rid!r}")
        e = self._ensure()
        off = set(e["rules"]["disabled"])
        if disabled == (rid in off):
            raise EngagementError(f"rule {rid} is already {'disabled' if disabled else 'enabled'}")
        (off.add if disabled else off.discard)(rid)
        e["rules"]["disabled"] = sorted(off)
        e["rules"]["version"] += 1
        self._audit(actor, "ENGAGEMENT_RULE_DISABLED" if disabled else "ENGAGEMENT_RULE_ENABLED", rid, {"rules_version": e["rules"]["version"]})
        return {"id": rid, "disabled": disabled}

    # ---- recommendations ---------------------------------------------------------------------
    def compute_recommendations(self) -> dict:
        """Pure: evaluate the effective rules against the answers. Same answers and rules give the same result."""
        e = self._e()
        answers = {k: v["value"] for k, v in (e.get("scoping") or {}).get("responses", {}).items()}
        found: Dict[str, dict] = {}
        skipped: List[dict] = []

        def hit(fw: str, rule: dict, triggers: List[str]) -> None:
            if fw not in self.lib.frameworks:
                skipped.append({"rule": rule["id"], "framework": fw, "reason": "is not in the library"})
                return
            it = found.setdefault(fw, {"framework": fw, "confidence": "low", "weight": 0, "rules": [], "triggers": [], "rationale": []})
            if RANK[rule["confidence"]] > RANK[it["confidence"]]:
                it["confidence"] = rule["confidence"]
            it["weight"] += rule["weight"]
            it["rules"].append(rule["id"])
            it["triggers"] = sorted(set(it["triggers"]) | set(triggers))
            it["rationale"].append(rule["rationale"])

        for rule in self.effective_rules():
            if rule["disabled"]:
                continue
            if "from_answer" in rule:
                for fw in answers.get(rule["from_answer"]) or []:
                    hit(fw, rule, [rule["from_answer"]])
            elif eval_when(rule["when"], answers):
                hit(rule["framework"], rule, [q for q in when_questions(rule["when"]) if q in answers])
        items = sorted(found.values(), key=lambda i: (-RANK[i["confidence"]], -i["weight"], i["framework"]))
        skipped.sort(key=lambda s: (s["rule"], s["framework"]))
        return {"items": items, "skipped": skipped}

    def recommend(self, actor: str) -> dict:
        actor = self._actor(actor)
        e = self._need()
        if e["scoping"]["status"] != "submitted":
            raise EngagementError("submit the scoping answers before recommending frameworks")
        if e["applicable"]:
            raise EngagementError("the framework set is already finalised; reopen the assignment first (engagement reopen-assignment --reason ...)")
        out = self.compute_recommendations()
        e["recommendation"] = {"at": _stamp(), "by": actor, "rules_version": e["rules"]["version"], **out}
        e["review"] = {}
        self._audit(actor, "ENGAGEMENT_RECOMMENDED", "recommendation",
                    {"frameworks": [i["framework"] for i in out["items"]], "skipped": len(out["skipped"]), "rules_version": e["rules"]["version"]})
        return e["recommendation"]

    # ---- principal review and assignment -----------------------------------------------------
    def review(self, actor: str, framework: str, action: str, justification: str = "") -> dict:
        actor = self._actor(actor)
        e = self._need()
        rec = e["recommendation"]
        if not rec:
            raise EngagementError("run the recommendation first (engagement recommend)")
        if e["applicable"]:
            raise EngagementError("the framework set is finalised; reopen the assignment first")
        if action not in ("accept", "add", "remove"):
            raise EngagementError("action must be accept, add or remove")
        if framework not in self.lib.frameworks:
            raise EngagementError(f"unknown framework {framework!r}")
        recommended = {i["framework"] for i in rec["items"]}
        why = (justification or "").strip()
        if action == "accept" and framework not in recommended:
            raise EngagementError(f"{framework} was not recommended; use 'add' with a justification")
        if action == "remove" and framework not in recommended:
            raise EngagementError(f"{framework} was not recommended, so there is nothing to remove")
        if action == "add" and framework in recommended:
            raise EngagementError(f"{framework} is already recommended; use 'accept'")
        if action != "accept" and not why:
            raise EngagementError(f"a written justification is required to {action} a framework")
        e["review"][framework] = {"action": action, "justification": why, "by": actor, "at": _stamp()}
        self._audit(actor, "ENGAGEMENT_REVIEWED", framework, {"action": action, "justification": why})
        return e["review"][framework]

    def applicable_frameworks(self) -> List[str]:
        e = self._e()
        rec, rev = e.get("recommendation"), e.get("review") or {}
        if not rec:
            return []
        out = [i["framework"] for i in rec["items"] if (rev.get(i["framework"]) or {}).get("action") != "remove"]
        out += [f for f, r in rev.items() if r["action"] == "add"]
        return sorted(set(out))

    def finalise(self, actor: str, justification: str = "") -> dict:
        actor = self._actor(actor)
        e = self._need()
        rec = e["recommendation"]
        if not rec:
            raise EngagementError("run the recommendation first (engagement recommend)")
        if e["applicable"]:
            raise EngagementError("the framework set is already finalised")
        pending = [i["framework"] for i in rec["items"] if i["framework"] not in e["review"]]
        if pending:
            raise EngagementError(f"review every recommendation first (accept or remove); not yet reviewed: {', '.join(pending)}")
        fws = self.applicable_frameworks()
        if not fws:
            raise EngagementError("the applicable framework set is empty; add at least one framework")
        e["applicable"] = {"frameworks": fws, "approver": actor, "at": _stamp(), "justification": (justification or "").strip(),
                           "rules_version": rec["rules_version"]}
        self._audit(actor, "ENGAGEMENT_FINALISED", "applicable-frameworks", {"frameworks": fws})
        return e["applicable"]

    def reopen_assignment(self, actor: str, reason: str) -> dict:
        actor = self._actor(actor)
        e = self._need()
        reason = (reason or "").strip()
        if not reason:
            raise EngagementError("a reason is required to reopen the assignment")
        if not e["applicable"]:
            raise EngagementError("the framework set is not finalised")
        e["applicable"] = None
        self._audit(actor, "ENGAGEMENT_ASSIGNMENT_REOPENED", "applicable-frameworks", {"reason": reason})
        return {"reopened": True}

    # ---- overview ----------------------------------------------------------------------------
    def overview(self) -> dict:
        e = self._e()
        if not e:
            return {"enabled": False, "stage": "not_started"}
        p = self.progress()
        rec = e.get("recommendation")
        if e["client"]["status"] != "onboarded":
            stage = "onboarding"
        elif e["scoping"]["status"] != "submitted":
            stage = "scoping"
        elif not rec:
            stage = "recommendation"
        elif not e.get("applicable"):
            stage = "review"
        else:
            stage = "assigned"
        return {"enabled": True, "stage": stage, "client": e["client"], "scoping": p,
                "recommended": [i["framework"] for i in rec["items"]] if rec else [],
                "reviewed": sorted(e["review"]), "applicable": (e.get("applicable") or {}).get("frameworks", []),
                "rules_version": e["rules"]["version"]}


def validate_engagement(scope: Scope):
    """Structural checks used by Scope.validate: returns (errors, warnings)."""
    e = scope.data.get("engagement")
    errs: List[str] = []
    warns: List[str] = []
    if e is None:
        return errs, warns
    spec = load_spec()
    eng = Engagement(scope)
    if not isinstance(e, dict):
        return ["engagement must be an object"], warns
    c = e.get("client") or {}
    if c.get("status") not in spec["client_statuses"]:
        errs.append(f"engagement client status {c.get('status')!r} is not valid")
    if c.get("sector") is not None and c["sector"] not in spec["sectors"]:
        errs.append(f"engagement client sector {c['sector']!r} is not valid")
    if c.get("size") is not None and c["size"] not in spec["sizes"]:
        errs.append(f"engagement client size {c['size']!r} is not valid")
    s = e.get("scoping") or {}
    if s.get("status") not in ("not_started", "in_progress", "submitted"):
        errs.append(f"engagement scoping status {s.get('status')!r} is not valid")
    for qid, r in (s.get("responses") or {}).items():
        q = eng.questions.get(qid)
        if q is None:
            errs.append(f"engagement answer for unknown question {qid!r}")
            continue
        try:
            eng._normalise(q, r.get("value"))
        except EngagementError as ex:
            errs.append(f"engagement answer invalid: {ex}")
    for qid in (s.get("delegations") or {}):
        if qid not in eng.questions:
            errs.append(f"engagement delegation for unknown question {qid!r}")
    if s.get("status") == "submitted" and eng.progress()["missing"]:
        errs.append("engagement scoping is submitted but required questions are unanswered")
    for rid, rule in ((e.get("rules") or {}).get("custom") or {}).items():
        try:
            if rule.get("id") != rid or not RULE_ID.match(rid) or rule.get("confidence") not in RANK:
                raise EngagementError(f"custom rule {rid!r} is malformed")
            eng._check_when(rule.get("when"))
        except EngagementError as ex:
            errs.append(str(ex))
    rec = e.get("recommendation")
    if rec:
        for it in rec.get("items", []):
            if it.get("framework") not in scope.lib.frameworks:
                errs.append(f"engagement recommendation names unknown framework {it.get('framework')!r}")
    for fw, r in (e.get("review") or {}).items():
        if fw not in scope.lib.frameworks:
            errs.append(f"engagement review names unknown framework {fw!r}")
        elif r.get("action") not in ("accept", "add", "remove"):
            errs.append(f"engagement review of {fw} has an invalid action")
        elif r.get("action") != "accept" and not (r.get("justification") or "").strip():
            errs.append(f"engagement review of {fw} ({r.get('action')}) has no justification")
    ap = e.get("applicable")
    if ap:
        for fw in ap.get("frameworks", []):
            if fw not in scope.lib.frameworks:
                errs.append(f"engagement applicable set names unknown framework {fw!r}")
        if not ap.get("frameworks"):
            errs.append("engagement applicable framework set is empty")
    return errs, warns
