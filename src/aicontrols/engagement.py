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
from .workflow import Workflow, WorkflowError, _norm, _stamp, _today

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
        e.setdefault("roles", {})
        e.setdefault("packages", {})
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

    # ---- roles -------------------------------------------------------------------------------
    def role_register(self) -> Dict[str, List[str]]:
        return {k: list(v) for k, v in (self._e().get("roles") or {}).items() if v}

    def enforced(self) -> bool:
        """Roles are checked once at least one person holds one. Until then anyone may do anything."""
        return bool(self.role_register())

    def roles_of(self, actor: str) -> List[str]:
        n = _norm(actor)
        known = {r["id"] for r in self.spec["roles"]}
        out = {r for r, names in self.role_register().items() if r in known and any(_norm(x) == n for x in names)}
        contributor = (self._e().get("client") or {}).get("contributor")
        if contributor and _norm(contributor) == n:
            out.add("contributor")
        return sorted(out)

    def _allowed(self, actor: str, action: str, assignee: Optional[str] = None) -> bool:
        if not self.enforced():
            return True
        table = {r["id"]: r for r in self.spec["roles"]}
        roles = self.roles_of(actor)
        if any(action in table[r]["can"] for r in roles):
            return True
        return assignee is not None and _norm(assignee) == _norm(actor) and any(action in table[r]["own"] for r in roles)

    def _require(self, actor: str, action: str, assignee: Optional[str] = None) -> None:
        if self._allowed(actor, action, assignee):
            return
        what = self.spec["actions"][action]
        table = {r["id"]: r for r in self.spec["roles"]}
        if any(action in table[r]["own"] for r in self.roles_of(actor)):
            raise EngagementError(f"{actor} may only {what} for items assigned to them")
        who = ", ".join(r["id"] for r in self.spec["roles"] if action in r["can"])
        raise EngagementError(f"{actor} may not {what}; roles that can: {who}")

    def set_roles(self, actor: str, role: str, names: List[str]) -> dict:
        actor = self._actor(actor)
        e = self._need()
        if role not in {r["id"] for r in self.spec["roles"]}:
            raise EngagementError(f"unknown role {role!r}; choose from {', '.join(r['id'] for r in self.spec['roles'])}")
        if self.enforced():
            self._require(actor, "roles_set")
        clean: List[str] = []
        for n in names:
            n = (n or "").strip() if isinstance(n, str) else ""
            if not n:
                raise EngagementError("a role holder's name cannot be empty")
            if _norm(n) not in {_norm(x) for x in clean}:
                clean.append(n)
        new = {**self.role_register(), role: clean}
        new = {k: v for k, v in new.items() if v}
        if new and not new.get("admin"):
            raise EngagementError("assign at least one engagement admin (role admin) first: once roles are set, only an admin can change them")
        e["roles"] = new
        self._audit(actor, "ENGAGEMENT_ROLES_SET", role, {"names": clean})
        return {"role": role, "names": clean, "enforced": self.enforced()}

    def roles(self) -> List[dict]:
        reg = self.role_register()
        return [{**r, "people": list(reg.get(r["id"], []))} for r in self.spec["roles"]]

    # ---- client and onboarding ---------------------------------------------------------------
    def set_client(self, actor: str, fields: Dict[str, str]) -> dict:
        actor = self._actor(actor)
        self._require(actor, "client_set")
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
        self._require(actor, "onboard")
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
        self._require(actor, "scoping_answer", (e["scoping"]["delegations"].get(qid) or {}).get("to"))
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
        self._require(actor, "scoping_delegate")
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
        self._require(actor, "scoping_submit")
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
        self._require(actor, "scoping_reopen")
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
        self._require(actor, "rules_edit")
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
        self._require(actor, "rules_edit")
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
        self._require(actor, "recommend")
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
        self._require(actor, "review")
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
        self._require(actor, "finalise")
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
        self._make_packages(actor, fws)
        return e["applicable"]

    def reopen_assignment(self, actor: str, reason: str) -> dict:
        actor = self._actor(actor)
        e = self._need()
        self._require(actor, "reopen_assignment")
        reason = (reason or "").strip()
        if not reason:
            raise EngagementError("a reason is required to reopen the assignment")
        if not e["applicable"]:
            raise EngagementError("the framework set is not finalised")
        if any(p["responses"] for p in (e.get("packages") or {}).values()):
            raise EngagementError("framework answers already exist, so the framework set cannot be reopened")
        e["packages"] = {}
        e["applicable"] = None
        self._audit(actor, "ENGAGEMENT_ASSIGNMENT_REOPENED", "applicable-frameworks", {"reason": reason})
        return {"reopened": True}

    # ---- framework questionnaires ("packages") -----------------------------------------------
    def _pk(self) -> dict:
        return self._e().get("packages") or {}

    def _package(self, framework: str) -> dict:
        p = self._pk().get(framework)
        if p is None:
            raise EngagementError(f"no questionnaire for {framework!r}; it exists once the framework set is finalised")
        return p

    def _domain_of(self, control_id: str) -> str:
        return self.lib.get(control_id).domain_id

    def _make_packages(self, actor: str, fws: List[str]) -> None:
        e = self._e()
        pk = e.setdefault("packages", {})
        created = []
        for fw in fws:
            if fw not in pk:
                pk[fw] = {"framework": fw, "status": "open", "created_at": _stamp(),
                          "controls": [c.id for c in self.lib.filter(framework=fw)], "assignments": {}, "responses": {},
                          "submitted_at": None, "submitted_by": None}
                created.append(fw)
        if created:
            self._audit(actor, "ENGAGEMENT_PACKAGES_CREATED", "packages", {"frameworks": created})

    def package_domains(self, framework: str) -> List[str]:
        return sorted({self._domain_of(c) for c in self._package(framework)["controls"]})

    def _open(self, p: dict) -> None:
        if p["status"] == "submitted":
            raise EngagementError(f"the {p['framework']} questionnaire is submitted and locked; an assessor or admin must return it first")

    def package_assign(self, actor: str, framework: str, to: str, due: Optional[str] = None, domain: Optional[str] = None) -> dict:
        actor = self._actor(actor)
        e = self._need()
        p = self._package(framework)
        self._require(actor, "package_assign")
        self._open(p)
        to = (to or "").strip()
        if not to:
            raise EngagementError("say who the questionnaire is assigned to")
        if due is not None:
            try:
                parse_date(due, "due date")
            except GrcError as ex:
                raise EngagementError(str(ex)) from None
        domains = self.package_domains(framework)
        if domain is not None and domain not in domains:
            raise EngagementError(f"{framework} has no questions in domain {domain!r}")
        targets = [domain] if domain else domains
        for d in targets:
            p["assignments"][d] = {"to": to, "due": due, "by": actor, "at": _stamp()}
        self._audit(actor, "ENGAGEMENT_PACKAGE_ASSIGNED", framework, {"to": to, "due": due, "domains": targets})
        return {"framework": framework, "domains": targets, "to": to, "due": due}

    def package_questions(self, framework: str, domain: Optional[str] = None) -> List[dict]:
        p = self._package(framework)
        out = []
        for cid in p["controls"]:
            c = self.lib.get(cid)
            if domain is not None and c.domain_id != domain:
                continue
            out.append({"control_id": cid, "ref": c.ref, "title": c.title, "requirement": c.requirement, "domain": c.domain_id,
                        "response": p["responses"].get(cid)})
        return out

    def _evidence(self, evidence) -> List[str]:
        if evidence is None:
            return []
        if not isinstance(evidence, list) or len(evidence) > 20:
            raise EngagementError("evidence is a list of at most 20 references")
        out = []
        for x in evidence:
            x = x.strip() if isinstance(x, str) else ""
            if not x or len(x) > 200:
                raise EngagementError("each evidence reference is 1 to 200 characters (a document title or link)")
            out.append(x)
        return out

    def respond(self, actor: str, framework: str, control_id: str, answer: str, comment: str = "", evidence=None, shared: bool = False) -> dict:
        actor = self._actor(actor)
        self._need()
        p = self._package(framework)
        if control_id not in p["controls"]:
            raise EngagementError(f"{control_id!r} is not in the {framework} questionnaire")
        dom = self._domain_of(control_id)
        self._require(actor, "package_respond", (p["assignments"].get(dom) or {}).get("to"))
        self._open(p)
        if answer not in self.spec["answers"]:
            raise EngagementError(f"answer must be one of {', '.join(self.spec['answers'])}")
        comment = (comment or "").strip() if isinstance(comment, str) else ""
        if answer == "not_applicable" and not comment:
            raise EngagementError("a justification is required for not_applicable")
        if len(comment) > 1000:
            raise EngagementError("the comment is at most 1000 characters")
        ev = self._evidence(evidence)
        cur = p["responses"].get(control_id)
        if cur and cur["status"] in ("submitted", "approved"):
            raise EngagementError(f"{control_id} is already {cur['status']}; ask for it to be returned before changing it")
        base = {"answer": answer, "comment": comment, "evidence": ev, "status": "in_progress", "by": actor, "at": _stamp()}
        p["responses"][control_id] = dict(base)
        n = 0
        if shared:
            for ofw in sorted(self._pk()):
                op = self._pk()[ofw]
                if ofw == framework or op["status"] != "open":
                    continue
                for cid in op["controls"]:
                    if self._domain_of(cid) != dom:
                        continue
                    if not self._allowed(actor, "package_respond", (op["assignments"].get(dom) or {}).get("to")):
                        continue
                    existing = op["responses"].get(cid)
                    if existing and existing["status"] in ("submitted", "approved"):
                        continue
                    op["responses"][cid] = {**base, "shared_from": f"{framework}:{control_id}"}
                    n += 1
        self._audit(actor, "ENGAGEMENT_ITEM_ANSWERED", f"{framework}:{control_id}", {"answer": answer, "shared_to": n})
        return {"framework": framework, "control_id": control_id, "answer": answer, "shared_to": n}

    def _domain_items(self, p: dict, domain: str) -> List[str]:
        ids = [c for c in p["controls"] if self._domain_of(c) == domain]
        if not ids:
            raise EngagementError(f"{p['framework']} has no questions in domain {domain!r}")
        return ids

    def submit_items(self, actor: str, framework: str, domain: str) -> dict:
        actor = self._actor(actor)
        self._need()
        p = self._package(framework)
        self._require(actor, "package_submit_items", (p["assignments"].get(domain) or {}).get("to"))
        self._open(p)
        ids = self._domain_items(p, domain)
        missing = [c for c in ids if c not in p["responses"]]
        if missing:
            raise EngagementError(f"{len(missing)} question(s) in this domain are unanswered, for example {missing[0]}")
        todo = [c for c in ids if p["responses"][c]["status"] in ("in_progress", "returned")]
        if not todo:
            raise EngagementError("nothing to submit: every answer in this domain is already submitted or approved")
        for c in todo:
            p["responses"][c]["status"] = "submitted"
        self._audit(actor, "ENGAGEMENT_ITEMS_SUBMITTED", f"{framework}:{domain}", {"count": len(todo)})
        return {"framework": framework, "domain": domain, "submitted": len(todo)}

    def review_items(self, actor: str, framework: str, domain: str, action: str, note: str = "") -> dict:
        actor = self._actor(actor)
        self._need()
        p = self._package(framework)
        self._require(actor, "package_review")
        self._open(p)
        if action not in ("approve", "return"):
            raise EngagementError("action must be approve or return")
        note = (note or "").strip()
        if action == "return" and not note:
            raise EngagementError("say what needs correcting when returning answers")
        ids = [c for c in self._domain_items(p, domain) if c in p["responses"] and p["responses"][c]["status"] == "submitted"]
        if not ids:
            raise EngagementError("no submitted answers in this domain to review")
        for c in ids:
            r = p["responses"][c]
            r["status"] = "approved" if action == "approve" else "returned"
            r["review"] = {"by": actor, "at": _stamp(), "note": note}
        self._audit(actor, "ENGAGEMENT_ITEMS_APPROVED" if action == "approve" else "ENGAGEMENT_ITEMS_RETURNED", f"{framework}:{domain}",
                    {"count": len(ids), "note": note})
        return {"framework": framework, "domain": domain, "action": action, "count": len(ids)}

    def submit_package(self, actor: str, framework: str) -> dict:
        actor = self._actor(actor)
        self._need()
        p = self._package(framework)
        self._require(actor, "package_submit")
        self._open(p)
        open_ = [c for c in p["controls"] if c not in p["responses"] or p["responses"][c]["status"] != "approved"]
        if open_:
            raise EngagementError(f"{len(open_)} of {len(p['controls'])} question(s) are not yet approved")
        p["status"], p["submitted_at"], p["submitted_by"] = "submitted", _stamp(), actor
        self._audit(actor, "ENGAGEMENT_PACKAGE_SUBMITTED", framework, {"questions": len(p["controls"])})
        return {"framework": framework, "status": "submitted"}

    def return_package(self, actor: str, framework: str, reason: str) -> dict:
        actor = self._actor(actor)
        self._need()
        p = self._package(framework)
        self._require(actor, "package_return")
        reason = (reason or "").strip()
        if not reason:
            raise EngagementError("a reason is required to return a questionnaire")
        if p["status"] != "submitted":
            raise EngagementError(f"the {framework} questionnaire is not submitted")
        p["status"], p["submitted_at"], p["submitted_by"] = "open", None, None
        self._audit(actor, "ENGAGEMENT_PACKAGE_RETURNED", framework, {"reason": reason})
        return {"framework": framework, "status": "open"}

    def package_progress(self, framework: str) -> dict:
        p = self._package(framework)
        today = _today()
        rows = []
        for d in self.package_domains(framework):
            ids = [c for c in p["controls"] if self._domain_of(c) == d]
            rs = [p["responses"].get(c) for c in ids]
            st = lambda name: sum(1 for r in rs if r and r["status"] == name)  # noqa: E731
            a = p["assignments"].get(d)
            approved = st("approved")
            rows.append({"domain": d, "assigned_to": a["to"] if a else None, "due": a["due"] if a else None, "total": len(ids),
                         "answered": sum(1 for r in rs if r), "submitted": st("submitted"), "approved": approved,
                         "overdue": bool(a and a["due"] and parse_date(a["due"]) < today and approved < len(ids))})
        return {"framework": framework, "status": p["status"], "total": len(p["controls"]), "answered": len(p["responses"]),
                "approved": sum(1 for r in p["responses"].values() if r["status"] == "approved"), "domains": rows}

    def packages_overview(self) -> List[dict]:
        out = []
        for fw in sorted(self._pk()):
            pr = self.package_progress(fw)
            out.append({k: pr[k] for k in ("framework", "status", "total", "answered", "approved")})
        return out

    def my_tasks(self, name: str) -> List[dict]:
        n = _norm(name)
        out = []
        sc = self._e().get("scoping") or {}
        for qid in sorted((sc.get("delegations") or {})):
            d = sc["delegations"][qid]
            if _norm(d["to"]) == n and qid not in sc.get("responses", {}):
                out.append({"kind": "scoping", "framework": None, "domain": None, "question": qid, "due": d["due"], "remaining": 1})
        for fw in sorted(self._pk()):
            if self._pk()[fw]["status"] == "submitted":
                continue
            for row in self.package_progress(fw)["domains"]:
                if row["assigned_to"] and _norm(row["assigned_to"]) == n and row["approved"] < row["total"]:
                    out.append({"kind": "package", "framework": fw, "domain": row["domain"], "question": None, "due": row["due"],
                                "remaining": row["total"] - row["answered"]})
        return out

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
    reg = e.get("roles") or {}
    known = {r["id"] for r in spec["roles"]}
    for role, names in reg.items():
        if role not in known:
            errs.append(f"engagement roles name unknown role {role!r}")
        elif not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() for n in names):
            errs.append(f"engagement role {role!r} has an invalid list of names")
    if any(reg.values()) and not reg.get("admin"):
        errs.append("engagement roles are set but nobody holds the admin role")
    pk = e.get("packages") or {}
    if pk and not ap:
        errs.append("engagement questionnaires exist but the framework set is not finalised")
    elif ap and sorted(pk) != sorted(ap.get("frameworks", [])):
        errs.append("engagement questionnaires do not match the finalised framework set")
    for fw in sorted(pk):
        p = pk[fw]
        if fw not in scope.lib.frameworks:
            errs.append(f"engagement questionnaire names unknown framework {fw!r}")
            continue
        if p.get("status") not in ("open", "submitted"):
            errs.append(f"engagement {fw} questionnaire status {p.get('status')!r} is not valid")
        ctrl = list(p.get("controls", []))
        doms = set()
        for c in ctrl:
            try:
                ctl = scope.lib.get(c)
            except KeyError:
                ctl = None
            if ctl is None or ctl.framework_id != fw:
                errs.append(f"engagement {fw} questionnaire lists {c!r}, which is not a {fw} control")
            else:
                doms.add(ctl.domain_id)
        for d in sorted(p.get("assignments") or {}):
            if d not in doms:
                errs.append(f"engagement {fw} questionnaire assigns unknown domain {d!r}")
        resp = p.get("responses") or {}
        for c in sorted(resp):
            r = resp[c]
            if c not in ctrl:
                errs.append(f"engagement {fw} answer for {c!r}, which is not in its questionnaire")
            elif r.get("answer") not in spec["answers"]:
                errs.append(f"engagement {fw} answer for {c!r} has an invalid answer")
            elif r.get("status") not in spec["item_statuses"]:
                errs.append(f"engagement {fw} answer for {c!r} has an invalid status")
        if p.get("status") == "submitted" and any(c not in resp or resp[c].get("status") != "approved" for c in ctrl):
            errs.append(f"engagement {fw} questionnaire is submitted but not every answer is approved")
    return errs, warns
