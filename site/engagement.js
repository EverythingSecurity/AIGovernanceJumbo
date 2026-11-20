// SPDX-License-Identifier: Apache-2.0
// Client engagement layer, phase 2: a faithful port of src/aicontrols/engagement.py working on the same scope file.
// Python and this file are run side by side on scripted scenarios by tests/test_engagement_parity.py, which compares
// every result and the resulting file (audit hash chain included), so change them together.
// Pure functions: no DOM, no network, no storage. The model is in engagement-spec.js, generated from
// src/aicontrols/engagement_spec.json.
(function (root) {
  "use strict";
  const isNode = typeof module !== "undefined" && module.exports;
  const S = isNode ? require("./scope.js") : root.AIC.scope;
  const W = isNode ? require("./workflow.js") : root.AIC.workflow;
  const G = isNode ? require("./grc.js") : root.AIC.grc;
  const SPEC = isNode ? require("./engagement-spec.js") : root.AIC.engagementSpec;

  const SCHEMA_VERSION = "1.3";
  const ORG = "(organisation)", ROLE = "ENGAGEMENT_OFFICE";
  const RANK = { low: 0, medium: 1, high: 2 };
  const RULE_ID = /^R-[A-Z0-9-]{1,24}$/;
  const FRAMEWORK_ID = /^[a-z0-9][a-z0-9-]{0,40}$/;
  const CLIENT_FIELDS = ["name", "sector", "country", "size", "contributor"];
  const QUESTIONS = Object.fromEntries(SPEC.questionnaire.questions.map((q) => [q.id, q]));

  class EngagementError extends W.WorkflowError {}
  const fail = (m) => { throw new EngagementError(m); };
  const uniqSorted = (a) => [...new Set(a)].sort();
  const norm = (n) => String(n || "").trim().toLowerCase();
  const isObj = (x) => x !== null && typeof x === "object" && !Array.isArray(x);

  // ---- rule conditions ------------------------------------------------------------------------------------------
  function evalWhen(cond, answers) {
    if ("all" in cond) return cond.all.every((c) => evalWhen(c, answers));
    if ("any" in cond) return cond.any.some((c) => evalWhen(c, answers));
    if ("not" in cond) return !evalWhen(cond.not, answers);
    const ans = answers[cond.q];
    if (ans === undefined || ans === null) return false;
    const op = cond.op, want = cond.value;
    if (op === "is") return typeof ans === "string" && ans === want;
    if (op === "has") return Array.isArray(ans) && ans.includes(want);
    if (Array.isArray(ans)) return ans.some((x) => want.includes(x));
    return want.includes(ans);
  }
  function whenQuestions(cond) {
    let out;
    if ("all" in cond) out = cond.all.flatMap(whenQuestions);
    else if ("any" in cond) out = cond.any.flatMap(whenQuestions);
    else if ("not" in cond) out = whenQuestions(cond.not);
    else out = [cond.q];
    return uniqSorted(out);
  }

  // ---- state ----------------------------------------------------------------------------------------------------
  const e0 = (scope) => scope.engagement || {};
  const enabled = (scope) => Boolean(scope.engagement && Object.keys(scope.engagement).length);
  function ensure(scope) {
    const e = (scope.engagement = scope.engagement || {});
    if (!e.client) e.client = { name: scope.organization || "", sector: null, country: null, size: null, contributor: null, status: "invited" };
    if (!e.scoping) e.scoping = { questionnaire_version: SPEC.questionnaire.version, status: "not_started", responses: {}, delegations: {}, submitted_at: null, submitted_by: null };
    if (!e.rules) e.rules = { version: 1, custom: {}, disabled: [] };
    if (!("recommendation" in e)) e.recommendation = null;
    if (!e.review) e.review = {};
    if (!("applicable" in e)) e.applicable = null;
    if (!e.roles) e.roles = {};
    if (!e.packages) e.packages = {};
    if (!scope.schema_version || ["1.0", "1.1", "1.2"].includes(scope.schema_version)) scope.schema_version = SCHEMA_VERSION;
    return e;
  }
  const audit = (scope, actor, action, target, details) => W.audit(scope, ORG, actor, ROLE, action, target, details || {});
  const actorOf = (a) => W.checkActor(a);
  function need(scope) {
    if (!enabled(scope)) fail("the engagement is not started; set the client first (engagement client set)");
    return e0(scope);
  }

  // ---- roles ----------------------------------------------------------------------------------------------------
  function roleRegister(scope) {
    const out = {};
    for (const [k, v] of Object.entries(e0(scope).roles || {})) if (v && v.length) out[k] = [...v];
    return out;
  }
  const enforced = (scope) => Object.keys(roleRegister(scope)).length > 0;
  function rolesOf(scope, actor) {
    const n = norm(actor);
    const known = new Set(SPEC.roles.map((r) => r.id));
    const out = new Set(Object.entries(roleRegister(scope)).filter(([r, names]) => known.has(r) && names.some((x) => norm(x) === n)).map(([r]) => r));
    const contributor = (e0(scope).client || {}).contributor;
    if (contributor && norm(contributor) === n) out.add("contributor");
    return [...out].sort();
  }
  function allowed(scope, actor, action, assignee) {
    if (!enforced(scope)) return true;
    const table = Object.fromEntries(SPEC.roles.map((r) => [r.id, r]));
    const roles = rolesOf(scope, actor);
    if (roles.some((r) => table[r].can.includes(action))) return true;
    return assignee !== undefined && assignee !== null && norm(assignee) === norm(actor) && roles.some((r) => table[r].own.includes(action));
  }
  function require_(scope, actor, action, assignee) {
    if (allowed(scope, actor, action, assignee)) return;
    const what = SPEC.actions[action];
    const table = Object.fromEntries(SPEC.roles.map((r) => [r.id, r]));
    if (rolesOf(scope, actor).some((r) => table[r].own.includes(action))) fail(`${actor} may only ${what} for items assigned to them`);
    fail(`${actor} may not ${what}; roles that can: ${SPEC.roles.filter((r) => r.can.includes(action)).map((r) => r.id).join(", ")}`);
  }
  function setRoles(scope, actor, role, names) {
    actor = actorOf(actor);
    const e = need(scope);
    if (!SPEC.roles.some((r) => r.id === role)) fail(`unknown role '${role}'; choose from ${SPEC.roles.map((r) => r.id).join(", ")}`);
    if (enforced(scope)) require_(scope, actor, "roles_set");
    const clean = [];
    for (const raw of names) {
      const n = typeof raw === "string" ? raw.trim() : "";
      if (!n) fail("a role holder's name cannot be empty");
      if (!clean.some((x) => norm(x) === norm(n))) clean.push(n);
    }
    const nw = {};
    for (const [k, v] of Object.entries({ ...roleRegister(scope), [role]: clean })) if (v.length) nw[k] = v;
    if (Object.keys(nw).length && !(nw.admin && nw.admin.length)) fail("assign at least one engagement admin (role admin) first: once roles are set, only an admin can change them");
    e.roles = nw;
    audit(scope, actor, "ENGAGEMENT_ROLES_SET", role, { names: clean });
    return { role, names: clean, enforced: enforced(scope) };
  }
  function roles(scope) {
    const reg = roleRegister(scope);
    return SPEC.roles.map((r) => ({ ...r, people: [...(reg[r.id] || [])] }));
  }

  // ---- client and onboarding ------------------------------------------------------------------------------------
  function setClient(scope, actor, fields) {
    actor = actorOf(actor);
    require_(scope, actor, "client_set");
    const bad = Object.keys(fields).filter((k) => !CLIENT_FIELDS.includes(k));
    if (bad.length) fail(`unknown client field(s): ${bad.sort().join(", ")}; use ${CLIENT_FIELDS.join(", ")}`);
    const nw = {};
    for (const [k, raw] of Object.entries(fields)) {
      const v = typeof raw === "string" ? raw.trim() : raw;
      if (!v) fail(`client ${k} cannot be empty`);
      if (k === "sector" && !SPEC.sectors.includes(v)) fail(`unknown sector '${v}'; choose from ${SPEC.sectors.join(", ")}`);
      if (k === "size" && !SPEC.sizes.includes(v)) fail(`unknown size '${v}'; choose from ${SPEC.sizes.join(", ")}`);
      nw[k] = v;
    }
    const e = ensure(scope);
    Object.assign(e.client, nw);
    audit(scope, actor, "ENGAGEMENT_CLIENT_SET", e.client.name || "client", { fields: Object.keys(nw).sort() });
    return e.client;
  }
  function onboard(scope, actor) {
    actor = actorOf(actor);
    const e = need(scope);
    require_(scope, actor, "onboard");
    const c = e.client;
    const missing = CLIENT_FIELDS.filter((k) => !c[k]);
    if (missing.length) fail(`complete the client profile first; missing: ${missing.join(", ")}`);
    if (c.status === "onboarded") fail("the client is already onboarded");
    c.status = "onboarded";
    audit(scope, actor, "ENGAGEMENT_ONBOARDED", c.name, { contributor: c.contributor });
    return c;
  }

  // ---- scoping questionnaire ------------------------------------------------------------------------------------
  function questionnaire(scope) {
    const sc = e0(scope).scoping || {};
    const resp = sc.responses || {}, dele = sc.delegations || {};
    return SPEC.questionnaire.questions.map((q) => {
      const r = resp[q.id], d = dele[q.id];
      return { ...q, answer: r ? r.value : null, answered_by: r ? r.by : null, answered_at: r ? r.at : null,
        delegated_to: d ? d.to : null, due: d ? d.due : null };
    });
  }
  function progress(scope) {
    const qs = questionnaire(scope);
    const req = qs.filter((q) => q.required);
    const done = req.filter((q) => q.answer !== null);
    const status = (e0(scope).scoping || {}).status || "not_started";
    return { status, questions: qs.length, answered: qs.filter((q) => q.answer !== null).length, required: req.length,
      required_answered: done.length, missing: req.filter((q) => q.answer === null).map((q) => q.id) };
  }
  function unlocked(e) {
    if (e.client.status !== "onboarded") fail("onboard the client before scoping (engagement client onboard)");
    if (e.scoping.status === "submitted") fail("the scoping answers are submitted and locked; reopen them first (engagement reopen --reason ...)");
  }
  function normalise(q, value) {
    const kind = q.kind;
    if (kind === "yes_no") {
      if (value !== "yes" && value !== "no") fail(`${q.id}: answer yes or no`);
      return value;
    }
    if (kind === "single") {
      if (!q.options.includes(value)) fail(`${q.id}: choose one of ${q.options.join(", ")}`);
      return value;
    }
    if (kind === "multi") {
      const vals = typeof value === "string" ? [value] : value;
      if (!Array.isArray(vals) || !vals.length) fail(`${q.id}: choose at least one of ${q.options.join(", ")}`);
      const bad = vals.filter((v) => !q.options.includes(v));
      if (bad.length) fail(`${q.id}: unknown option(s) ${bad.map(String).join(", ")}; choose from ${q.options.join(", ")}`);
      return uniqSorted(vals);
    }
    const text = typeof value === "string" ? value.trim() : "";
    if (!text || text.length > 500) fail(`${q.id}: enter text of 1 to 500 characters`);
    return text;
  }
  function answer(scope, actor, qid, value) {
    actor = actorOf(actor);
    const e = need(scope);
    const q = QUESTIONS[qid];
    if (!q) fail(`unknown question '${qid}'`);
    require_(scope, actor, "scoping_answer", (e.scoping.delegations[qid] || {}).to);
    unlocked(e);
    const v = normalise(q, value);
    e.scoping.responses[qid] = { value: v, by: actor, at: W.stamp() };
    e.scoping.status = "in_progress";
    audit(scope, actor, "ENGAGEMENT_ANSWERED", qid, { answer: typeof v === "string" ? v : [...v] });
    return v;
  }
  function delegate(scope, actor, qid, to, due) {
    actor = actorOf(actor);
    const e = need(scope);
    if (!QUESTIONS[qid]) fail(`unknown question '${qid}'`);
    require_(scope, actor, "scoping_delegate");
    unlocked(e);
    to = (to || "").trim();
    if (!to) fail("say who the question is delegated to");
    const dueV = due === undefined ? null : due;
    if (dueV !== null) {
      try { G.parseDate(dueV, "due date"); } catch (ex) { if (ex instanceof G.GrcError) fail(ex.message); throw ex; }
    }
    e.scoping.delegations[qid] = { to, due: dueV };
    audit(scope, actor, "ENGAGEMENT_DELEGATED", qid, { to, due: dueV });
    return e.scoping.delegations[qid];
  }
  function submitScoping(scope, actor) {
    actor = actorOf(actor);
    const e = need(scope);
    require_(scope, actor, "scoping_submit");
    unlocked(e);
    const miss = progress(scope).missing;
    if (miss.length) fail(`${miss.length} required question(s) are unanswered: ${miss.join(", ")}`);
    const s = e.scoping;
    s.status = "submitted"; s.submitted_at = W.stamp(); s.submitted_by = actor;
    audit(scope, actor, "ENGAGEMENT_SCOPING_SUBMITTED", "scoping", { answers: Object.keys(s.responses).length });
    return s;
  }
  function reopenScoping(scope, actor, reason) {
    actor = actorOf(actor);
    const e = need(scope);
    require_(scope, actor, "scoping_reopen");
    reason = (reason || "").trim();
    if (!reason) fail("a reason is required to reopen the scoping answers");
    if (e.scoping.status !== "submitted") fail("the scoping answers are not submitted");
    const s = e.scoping;
    s.status = "in_progress"; s.submitted_at = null; s.submitted_by = null;
    const dropped = Boolean(e.recommendation || Object.keys(e.review).length || e.applicable);
    e.recommendation = null; e.review = {}; e.applicable = null;
    audit(scope, actor, "ENGAGEMENT_SCOPING_REOPENED", "scoping", { reason, cleared_recommendations: dropped });
    return s;
  }

  // ---- rules ----------------------------------------------------------------------------------------------------
  function checkWhen(cond, depth) {
    depth = depth || 0;
    if (!isObj(cond) || depth > 8) fail("a rule condition must be an object (at most 8 levels deep)");
    const keys = Object.keys(cond).sort().join(",");
    if (keys === "all" || keys === "any") {
      if (!Array.isArray(cond[keys]) || !cond[keys].length) fail(`'${keys}' needs a non-empty list of conditions`);
      for (const c of cond[keys]) checkWhen(c, depth + 1);
    } else if (keys === "not") {
      checkWhen(cond.not, depth + 1);
    } else if (keys === "op,q,value") {
      const q = QUESTIONS[cond.q];
      if (!q) fail(`condition refers to unknown question '${cond.q}'`);
      if (!["is", "has", "in"].includes(cond.op)) fail(`unknown operator '${cond.op}'; use is, has or in`);
      if (cond.op === "has" && q.kind !== "multi") fail(`'has' needs a multi-choice question; ${q.id} is ${q.kind}`);
      if (cond.op === "is" && q.kind === "multi") fail(`'is' needs a single-answer question; use has or in for ${q.id}`);
      if (cond.op === "in" && (!Array.isArray(cond.value) || !cond.value.length)) fail("'in' needs a non-empty list of values");
    } else fail("a condition is {all: [...]}, {any: [...]}, {not: ...} or {q, op, value}");
  }
  function effectiveRules(scope) {
    const r = e0(scope).rules || { custom: {}, disabled: [] };
    const merged = {};
    for (const x of SPEC.rules) merged[x.id] = { ...x, source: "seed" };
    for (const [k, v] of Object.entries(r.custom || {})) merged[k] = { ...v, source: "custom" };
    const off = new Set(r.disabled || []);
    return Object.keys(merged).sort().map((k) => ({ ...merged[k], disabled: off.has(k) }));
  }
  function ruleSet(scope, actor, rule) {
    actor = actorOf(actor);
    require_(scope, actor, "rules_edit");
    if (!isObj(rule)) fail("a rule must be an object");
    const rid = rule.id;
    if (typeof rid !== "string" || !RULE_ID.test(rid)) fail("rule id must look like R-MY-RULE (capitals, digits, dashes)");
    const allowed = ["id", "framework", "confidence", "weight", "rationale", "when"];
    if (Object.keys(rule).some((k) => !allowed.includes(k))) fail("a rule has: id, framework, when, confidence, weight, rationale");
    const fw = rule.framework;
    if (typeof fw !== "string" || !FRAMEWORK_ID.test(fw)) fail("rule framework must be a framework id such as iso-42001");
    if (!(rule.confidence in RANK) || typeof rule.confidence !== "string") fail(`rule confidence must be one of ${Object.keys(RANK).join(", ")}`);
    const w = rule.weight;
    if (typeof w !== "number" || !Number.isInteger(w) || w < 1 || w > 100) fail("rule weight must be a whole number from 1 to 100");
    const why = rule.rationale;
    if (typeof why !== "string" || !why.trim()) fail("a rule needs a rationale");
    checkWhen(rule.when);
    const e = ensure(scope);
    const clean = { id: rid, framework: fw, confidence: rule.confidence, weight: w, rationale: why.trim(), when: rule.when };
    e.rules.custom[rid] = clean;
    e.rules.version += 1;
    audit(scope, actor, "ENGAGEMENT_RULE_SET", rid, { framework: fw, rules_version: e.rules.version });
    return clean;
  }
  function ruleDisable(scope, actor, rid, disabled) {
    actor = actorOf(actor);
    require_(scope, actor, "rules_edit");
    disabled = disabled === undefined ? true : Boolean(disabled);
    if (!effectiveRules(scope).some((r) => r.id === rid)) fail(`unknown rule '${rid}'`);
    const e = ensure(scope);
    const off = new Set(e.rules.disabled);
    if (disabled === off.has(rid)) fail(`rule ${rid} is already ${disabled ? "disabled" : "enabled"}`);
    if (disabled) off.add(rid); else off.delete(rid);
    e.rules.disabled = [...off].sort();
    e.rules.version += 1;
    audit(scope, actor, disabled ? "ENGAGEMENT_RULE_DISABLED" : "ENGAGEMENT_RULE_ENABLED", rid, { rules_version: e.rules.version });
    return { id: rid, disabled };
  }

  // ---- recommendations ------------------------------------------------------------------------------------------
  function computeRecommendations(scope, data) {
    const e = e0(scope);
    const fwIds = new Set(data.frameworks.map((f) => f.id));
    const answers = {};
    for (const [k, v] of Object.entries((e.scoping || {}).responses || {})) answers[k] = v.value;
    const found = {};
    const skipped = [];
    const hit = (fw, rule, triggers) => {
      if (!fwIds.has(fw)) { skipped.push({ rule: rule.id, framework: fw, reason: "is not in the library" }); return; }
      const it = (found[fw] = found[fw] || { framework: fw, confidence: "low", weight: 0, rules: [], triggers: [], rationale: [] });
      if (RANK[rule.confidence] > RANK[it.confidence]) it.confidence = rule.confidence;
      it.weight += rule.weight;
      it.rules.push(rule.id);
      it.triggers = uniqSorted([...it.triggers, ...triggers]);
      it.rationale.push(rule.rationale);
    };
    for (const rule of effectiveRules(scope)) {
      if (rule.disabled) continue;
      if ("from_answer" in rule) for (const fw of answers[rule.from_answer] || []) hit(fw, rule, [rule.from_answer]);
      else if (evalWhen(rule.when, answers)) hit(rule.framework, rule, whenQuestions(rule.when).filter((q) => q in answers));
    }
    const items = Object.values(found).sort((a, b) => (RANK[b.confidence] - RANK[a.confidence]) || (b.weight - a.weight) || (a.framework < b.framework ? -1 : a.framework > b.framework ? 1 : 0));
    skipped.sort((a, b) => (a.rule < b.rule ? -1 : a.rule > b.rule ? 1 : a.framework < b.framework ? -1 : a.framework > b.framework ? 1 : 0));
    return { items, skipped };
  }
  function recommend(scope, data, actor) {
    actor = actorOf(actor);
    const e = need(scope);
    require_(scope, actor, "recommend");
    if (e.scoping.status !== "submitted") fail("submit the scoping answers before recommending frameworks");
    if (e.applicable) fail("the framework set is already finalised; reopen the assignment first (engagement reopen-assignment --reason ...)");
    const out = computeRecommendations(scope, data);
    e.recommendation = { at: W.stamp(), by: actor, rules_version: e.rules.version, ...out };
    e.review = {};
    audit(scope, actor, "ENGAGEMENT_RECOMMENDED", "recommendation",
      { frameworks: out.items.map((i) => i.framework), skipped: out.skipped.length, rules_version: e.rules.version });
    return e.recommendation;
  }

  // ---- principal review and assignment --------------------------------------------------------------------------
  function review(scope, data, actor, framework, action, justification) {
    actor = actorOf(actor);
    const e = need(scope);
    require_(scope, actor, "review");
    const rec = e.recommendation;
    if (!rec) fail("run the recommendation first (engagement recommend)");
    if (e.applicable) fail("the framework set is finalised; reopen the assignment first");
    if (!["accept", "add", "remove"].includes(action)) fail("action must be accept, add or remove");
    if (!data.frameworks.some((f) => f.id === framework)) fail(`unknown framework '${framework}'`);
    const recommended = new Set(rec.items.map((i) => i.framework));
    const why = (justification || "").trim();
    if (action === "accept" && !recommended.has(framework)) fail(`${framework} was not recommended; use 'add' with a justification`);
    if (action === "remove" && !recommended.has(framework)) fail(`${framework} was not recommended, so there is nothing to remove`);
    if (action === "add" && recommended.has(framework)) fail(`${framework} is already recommended; use 'accept'`);
    if (action !== "accept" && !why) fail(`a written justification is required to ${action} a framework`);
    e.review[framework] = { action, justification: why, by: actor, at: W.stamp() };
    audit(scope, actor, "ENGAGEMENT_REVIEWED", framework, { action, justification: why });
    return e.review[framework];
  }
  function applicableFrameworks(scope) {
    const e = e0(scope);
    const rec = e.recommendation, rev = e.review || {};
    if (!rec) return [];
    const out = rec.items.filter((i) => (rev[i.framework] || {}).action !== "remove").map((i) => i.framework);
    for (const [f, r] of Object.entries(rev)) if (r.action === "add") out.push(f);
    return uniqSorted(out);
  }
  function finalise(scope, data, actor, justification) {
    actor = actorOf(actor);
    const e = need(scope);
    require_(scope, actor, "finalise");
    const rec = e.recommendation;
    if (!rec) fail("run the recommendation first (engagement recommend)");
    if (e.applicable) fail("the framework set is already finalised");
    const pending = rec.items.filter((i) => !(i.framework in e.review)).map((i) => i.framework);
    if (pending.length) fail(`review every recommendation first (accept or remove); not yet reviewed: ${pending.join(", ")}`);
    const fws = applicableFrameworks(scope);
    if (!fws.length) fail("the applicable framework set is empty; add at least one framework");
    e.applicable = { frameworks: fws, approver: actor, at: W.stamp(), justification: (justification || "").trim(), rules_version: rec.rules_version };
    audit(scope, actor, "ENGAGEMENT_FINALISED", "applicable-frameworks", { frameworks: fws });
    makePackages(scope, data, actor, fws);
    return e.applicable;
  }
  function reopenAssignment(scope, actor, reason) {
    actor = actorOf(actor);
    const e = need(scope);
    require_(scope, actor, "reopen_assignment");
    reason = (reason || "").trim();
    if (!reason) fail("a reason is required to reopen the assignment");
    if (!e.applicable) fail("the framework set is not finalised");
    if (Object.values(e.packages || {}).some((p) => Object.keys(p.responses).length)) fail("framework answers already exist, so the framework set cannot be reopened");
    e.packages = {};
    e.applicable = null;
    audit(scope, actor, "ENGAGEMENT_ASSIGNMENT_REOPENED", "applicable-frameworks", { reason });
    return { reopened: true };
  }

  // ---- framework questionnaires ("packages") --------------------------------------------------------------------
  const ctlCache = new WeakMap();
  function ctlIndex(data) {
    let m = ctlCache.get(data);
    if (!m) { m = new Map(data.controls.map((c) => [c.id, c])); ctlCache.set(data, m); }
    return m;
  }
  const domainOf = (data, id) => ctlIndex(data).get(id).domain_id;
  const pk = (scope) => e0(scope).packages || {};
  function pkg(scope, framework) {
    const p = pk(scope)[framework];
    if (!p) fail(`no questionnaire for '${framework}'; it exists once the framework set is finalised`);
    return p;
  }
  function makePackages(scope, data, actor, fws) {
    const e = e0(scope);
    e.packages = e.packages || {};
    const created = [];
    for (const fw of fws) {
      if (!(fw in e.packages)) {
        e.packages[fw] = { framework: fw, status: "open", created_at: W.stamp(),
          controls: data.controls.filter((c) => c.framework_id === fw && c.kind !== "info").map((c) => c.id), assignments: {}, responses: {},
          submitted_at: null, submitted_by: null };
        created.push(fw);
      }
    }
    if (created.length) audit(scope, actor, "ENGAGEMENT_PACKAGES_CREATED", "packages", { frameworks: created });
  }
  function packageDomains(scope, data, framework) { return uniqSorted(pkg(scope, framework).controls.map((c) => domainOf(data, c))); }
  function openOnly(p) {
    if (p.status === "submitted") fail(`the ${p.framework} questionnaire is submitted and locked; an assessor or admin must return it first`);
  }
  function packageAssign(scope, data, actor, framework, to, due, domain) {
    actor = actorOf(actor);
    need(scope);
    const p = pkg(scope, framework);
    require_(scope, actor, "package_assign");
    openOnly(p);
    to = (to || "").trim();
    if (!to) fail("say who the questionnaire is assigned to");
    const dueV = due === undefined ? null : due;
    if (dueV !== null) {
      try { G.parseDate(dueV, "due date"); } catch (ex) { if (ex instanceof G.GrcError) fail(ex.message); throw ex; }
    }
    const domains = packageDomains(scope, data, framework);
    const dom = domain === undefined ? null : domain;
    if (dom !== null && !domains.includes(dom)) fail(`${framework} has no questions in domain '${dom}'`);
    const targets = dom ? [dom] : domains;
    for (const d of targets) p.assignments[d] = { to, due: dueV, by: actor, at: W.stamp() };
    audit(scope, actor, "ENGAGEMENT_PACKAGE_ASSIGNED", framework, { to, due: dueV, domains: targets });
    return { framework, domains: targets, to, due: dueV };
  }
  function packageQuestions(scope, data, framework, domain) {
    const p = pkg(scope, framework);
    const out = [];
    for (const cid of p.controls) {
      const c = ctlIndex(data).get(cid);
      if (domain !== undefined && domain !== null && c.domain_id !== domain) continue;
      out.push({ control_id: cid, ref: c.ref, title: c.title, requirement: c.requirement, domain: c.domain_id, response: p.responses[cid] || null });
    }
    return out;
  }
  function evidenceList(evidence) {
    if (evidence === undefined || evidence === null) return [];
    if (!Array.isArray(evidence) || evidence.length > 20) fail("evidence is a list of at most 20 references");
    return evidence.map((x) => {
      const t = typeof x === "string" ? x.trim() : "";
      if (!t || t.length > 200) fail("each evidence reference is 1 to 200 characters (a document title or link)");
      return t;
    });
  }
  function respond(scope, data, actor, framework, controlId, answer, comment, evidence, shared) {
    actor = actorOf(actor);
    need(scope);
    const p = pkg(scope, framework);
    if (!p.controls.includes(controlId)) fail(`'${controlId}' is not in the ${framework} questionnaire`);
    const dom = domainOf(data, controlId);
    require_(scope, actor, "package_respond", (p.assignments[dom] || {}).to);
    openOnly(p);
    if (!SPEC.answers.includes(answer)) fail(`answer must be one of ${SPEC.answers.join(", ")}`);
    comment = typeof comment === "string" ? comment.trim() : "";
    if (answer === "not_applicable" && !comment) fail("a justification is required for not_applicable");
    if (comment.length > 1000) fail("the comment is at most 1000 characters");
    const ev = evidenceList(evidence);
    const cur = p.responses[controlId];
    if (cur && (cur.status === "submitted" || cur.status === "approved")) fail(`${controlId} is already ${cur.status}; ask for it to be returned before changing it`);
    const base = { answer, comment, evidence: ev, status: "in_progress", by: actor, at: W.stamp() };
    p.responses[controlId] = { ...base };
    let n = 0;
    if (shared) {
      for (const ofw of Object.keys(pk(scope)).sort()) {
        const op = pk(scope)[ofw];
        if (ofw === framework || op.status !== "open") continue;
        for (const cid of op.controls) {
          if (domainOf(data, cid) !== dom) continue;
          if (!allowed(scope, actor, "package_respond", (op.assignments[dom] || {}).to)) continue;
          const existing = op.responses[cid];
          if (existing && (existing.status === "submitted" || existing.status === "approved")) continue;
          op.responses[cid] = { ...base, shared_from: `${framework}:${controlId}` };
          n++;
        }
      }
    }
    audit(scope, actor, "ENGAGEMENT_ITEM_ANSWERED", `${framework}:${controlId}`, { answer, shared_to: n });
    return { framework, control_id: controlId, answer, shared_to: n };
  }
  function domainItems(data, p, domain) {
    const ids = p.controls.filter((c) => domainOf(data, c) === domain);
    if (!ids.length) fail(`${p.framework} has no questions in domain '${domain}'`);
    return ids;
  }
  function submitItems(scope, data, actor, framework, domain) {
    actor = actorOf(actor);
    need(scope);
    const p = pkg(scope, framework);
    require_(scope, actor, "package_submit_items", (p.assignments[domain] || {}).to);
    openOnly(p);
    const ids = domainItems(data, p, domain);
    const missing = ids.filter((c) => !(c in p.responses));
    if (missing.length) fail(`${missing.length} question(s) in this domain are unanswered, for example ${missing[0]}`);
    const todo = ids.filter((c) => p.responses[c].status === "in_progress" || p.responses[c].status === "returned");
    if (!todo.length) fail("nothing to submit: every answer in this domain is already submitted or approved");
    for (const c of todo) p.responses[c].status = "submitted";
    audit(scope, actor, "ENGAGEMENT_ITEMS_SUBMITTED", `${framework}:${domain}`, { count: todo.length });
    return { framework, domain, submitted: todo.length };
  }
  function reviewItems(scope, data, actor, framework, domain, action, note) {
    actor = actorOf(actor);
    need(scope);
    const p = pkg(scope, framework);
    require_(scope, actor, "package_review");
    openOnly(p);
    if (action !== "approve" && action !== "return") fail("action must be approve or return");
    note = typeof note === "string" ? note.trim() : "";
    if (action === "return" && !note) fail("say what needs correcting when returning answers");
    const ids = domainItems(data, p, domain).filter((c) => c in p.responses && p.responses[c].status === "submitted");
    if (!ids.length) fail("no submitted answers in this domain to review");
    for (const c of ids) {
      const r = p.responses[c];
      r.status = action === "approve" ? "approved" : "returned";
      r.review = { by: actor, at: W.stamp(), note };
    }
    audit(scope, actor, action === "approve" ? "ENGAGEMENT_ITEMS_APPROVED" : "ENGAGEMENT_ITEMS_RETURNED", `${framework}:${domain}`, { count: ids.length, note });
    return { framework, domain, action, count: ids.length };
  }
  function submitPackage(scope, actor, framework) {
    actor = actorOf(actor);
    need(scope);
    const p = pkg(scope, framework);
    require_(scope, actor, "package_submit");
    openOnly(p);
    const open_ = p.controls.filter((c) => !(c in p.responses) || p.responses[c].status !== "approved");
    if (open_.length) fail(`${open_.length} of ${p.controls.length} question(s) are not yet approved`);
    p.status = "submitted"; p.submitted_at = W.stamp(); p.submitted_by = actor;
    audit(scope, actor, "ENGAGEMENT_PACKAGE_SUBMITTED", framework, { questions: p.controls.length });
    return { framework, status: "submitted" };
  }
  function returnPackage(scope, actor, framework, reason) {
    actor = actorOf(actor);
    need(scope);
    const p = pkg(scope, framework);
    require_(scope, actor, "package_return");
    reason = (reason || "").trim();
    if (!reason) fail("a reason is required to return a questionnaire");
    if (p.status !== "submitted") fail(`the ${framework} questionnaire is not submitted`);
    p.status = "open"; p.submitted_at = null; p.submitted_by = null;
    audit(scope, actor, "ENGAGEMENT_PACKAGE_RETURNED", framework, { reason });
    return { framework, status: "open" };
  }
  function packageProgress(scope, data, framework) {
    const p = pkg(scope, framework);
    const today = W.todayStr();
    const rows = packageDomains(scope, data, framework).map((d) => {
      const ids = p.controls.filter((c) => domainOf(data, c) === d);
      const rs = ids.map((c) => p.responses[c]);
      const st = (name) => rs.filter((r) => r && r.status === name).length;
      const a = p.assignments[d];
      const approved = st("approved");
      return { domain: d, assigned_to: a ? a.to : null, due: a ? a.due : null, total: ids.length, answered: rs.filter(Boolean).length,
        submitted: st("submitted"), approved, overdue: Boolean(a && a.due && a.due < today && approved < ids.length) };
    });
    return { framework, status: p.status, total: p.controls.length, answered: Object.keys(p.responses).length,
      approved: Object.values(p.responses).filter((r) => r.status === "approved").length, domains: rows };
  }
  function packagesOverview(scope, data) {
    return Object.keys(pk(scope)).sort().map((fw) => {
      const pr = packageProgress(scope, data, fw);
      return { framework: pr.framework, status: pr.status, total: pr.total, answered: pr.answered, approved: pr.approved };
    });
  }
  function myTasks(scope, data, name) {
    const n = norm(name);
    const out = [];
    const sc = e0(scope).scoping || {};
    for (const qid of Object.keys(sc.delegations || {}).sort()) {
      const d = sc.delegations[qid];
      if (norm(d.to) === n && !(qid in (sc.responses || {}))) out.push({ kind: "scoping", framework: null, domain: null, question: qid, due: d.due, remaining: 1 });
    }
    for (const fw of Object.keys(pk(scope)).sort()) {
      if (pk(scope)[fw].status === "submitted") continue;
      for (const row of packageProgress(scope, data, fw).domains) {
        if (row.assigned_to && norm(row.assigned_to) === n && row.approved < row.total) {
          out.push({ kind: "package", framework: fw, domain: row.domain, question: null, due: row.due, remaining: row.total - row.answered });
        }
      }
    }
    return out;
  }

  function overview(scope) {
    const e = e0(scope);
    if (!enabled(scope)) return { enabled: false, stage: "not_started" };
    const p = progress(scope);
    const rec = e.recommendation;
    let stage;
    if (e.client.status !== "onboarded") stage = "onboarding";
    else if (e.scoping.status !== "submitted") stage = "scoping";
    else if (!rec) stage = "recommendation";
    else if (!e.applicable) stage = "review";
    else stage = "assigned";
    return { enabled: true, stage, client: e.client, scoping: p, recommended: rec ? rec.items.map((i) => i.framework) : [],
      reviewed: Object.keys(e.review).sort(), applicable: (e.applicable || {}).frameworks || [], rules_version: e.rules.version };
  }

  function validate(scope, data) {
    const errs = [], warns = [];
    const e = scope.engagement;
    if (e === undefined || e === null) return { errors: errs, warnings: warns };
    if (!isObj(e)) return { errors: ["engagement must be an object"], warnings: warns };
    const fwIds = new Set(data.frameworks.map((f) => f.id));
    const c = e.client || {};
    if (!SPEC.client_statuses.includes(c.status)) errs.push(`engagement client status ${pyRepr(c.status)} is not valid`);
    if (c.sector !== undefined && c.sector !== null && !SPEC.sectors.includes(c.sector)) errs.push(`engagement client sector ${pyRepr(c.sector)} is not valid`);
    if (c.size !== undefined && c.size !== null && !SPEC.sizes.includes(c.size)) errs.push(`engagement client size ${pyRepr(c.size)} is not valid`);
    const s = e.scoping || {};
    if (!["not_started", "in_progress", "submitted"].includes(s.status)) errs.push(`engagement scoping status ${pyRepr(s.status)} is not valid`);
    for (const [qid, r] of Object.entries(s.responses || {})) {
      const q = QUESTIONS[qid];
      if (!q) { errs.push(`engagement answer for unknown question ${pyRepr(qid)}`); continue; }
      try { normalise(q, r.value); } catch (ex) { if (ex instanceof EngagementError) errs.push(`engagement answer invalid: ${ex.message}`); else throw ex; }
    }
    for (const qid of Object.keys(s.delegations || {})) if (!QUESTIONS[qid]) errs.push(`engagement delegation for unknown question ${pyRepr(qid)}`);
    if (s.status === "submitted" && progress(scope).missing.length) errs.push("engagement scoping is submitted but required questions are unanswered");
    for (const [rid, rule] of Object.entries((e.rules || {}).custom || {})) {
      try {
        if (rule.id !== rid || !RULE_ID.test(rid) || !(rule.confidence in RANK)) fail(`custom rule ${pyRepr(rid)} is malformed`);
        checkWhen(rule.when);
      } catch (ex) { if (ex instanceof EngagementError) errs.push(ex.message); else throw ex; }
    }
    const rec = e.recommendation;
    if (rec) for (const it of rec.items || []) if (!fwIds.has(it.framework)) errs.push(`engagement recommendation names unknown framework ${pyRepr(it.framework)}`);
    for (const [fw, r] of Object.entries(e.review || {})) {
      if (!fwIds.has(fw)) errs.push(`engagement review names unknown framework ${pyRepr(fw)}`);
      else if (!["accept", "add", "remove"].includes(r.action)) errs.push(`engagement review of ${fw} has an invalid action`);
      else if (r.action !== "accept" && !(r.justification || "").trim()) errs.push(`engagement review of ${fw} (${r.action}) has no justification`);
    }
    const ap = e.applicable;
    if (ap) {
      for (const fw of ap.frameworks || []) if (!fwIds.has(fw)) errs.push(`engagement applicable set names unknown framework ${pyRepr(fw)}`);
      if (!(ap.frameworks || []).length) errs.push("engagement applicable framework set is empty");
    }
    const reg = e.roles || {};
    const knownRoles = new Set(SPEC.roles.map((r) => r.id));
    for (const [role, names] of Object.entries(reg)) {
      if (!knownRoles.has(role)) errs.push(`engagement roles name unknown role ${pyRepr(role)}`);
      else if (!Array.isArray(names) || names.some((n) => typeof n !== "string" || !n.trim())) errs.push(`engagement role ${pyRepr(role)} has an invalid list of names`);
    }
    if (Object.values(reg).some((v) => v && v.length) && !(reg.admin && reg.admin.length)) errs.push("engagement roles are set but nobody holds the admin role");
    const pkgs = e.packages || {};
    const pkNames = Object.keys(pkgs).sort();
    if (pkNames.length && !ap) errs.push("engagement questionnaires exist but the framework set is not finalised");
    else if (ap && JSON.stringify(pkNames) !== JSON.stringify([...(ap.frameworks || [])].sort())) errs.push("engagement questionnaires do not match the finalised framework set");
    const idx = ctlIndex(data);
    for (const fw of pkNames) {
      const p = pkgs[fw];
      if (!fwIds.has(fw)) { errs.push(`engagement questionnaire names unknown framework ${pyRepr(fw)}`); continue; }
      if (!["open", "submitted"].includes(p.status)) errs.push(`engagement ${fw} questionnaire status ${pyRepr(p.status)} is not valid`);
      const ctrl = [...(p.controls || [])];
      const doms = new Set();
      for (const c of ctrl) {
        const ctl = idx.get(c);
        if (!ctl || ctl.framework_id !== fw) errs.push(`engagement ${fw} questionnaire lists ${pyRepr(c)}, which is not a ${fw} control`);
        else doms.add(ctl.domain_id);
      }
      for (const d of Object.keys(p.assignments || {}).sort()) if (!doms.has(d)) errs.push(`engagement ${fw} questionnaire assigns unknown domain ${pyRepr(d)}`);
      const resp = p.responses || {};
      for (const c of Object.keys(resp).sort()) {
        const r = resp[c];
        if (!ctrl.includes(c)) errs.push(`engagement ${fw} answer for ${pyRepr(c)}, which is not in its questionnaire`);
        else if (!SPEC.answers.includes(r.answer)) errs.push(`engagement ${fw} answer for ${pyRepr(c)} has an invalid answer`);
        else if (!SPEC.item_statuses.includes(r.status)) errs.push(`engagement ${fw} answer for ${pyRepr(c)} has an invalid status`);
      }
      if (p.status === "submitted" && ctrl.some((c) => !(c in resp) || resp[c].status !== "approved")) errs.push(`engagement ${fw} questionnaire is submitted but not every answer is approved`);
    }
    return { errors: errs, warnings: warns };
  }
  // Python's repr() of a string or null, so messages match the Python engine.
  function pyRepr(v) {
    if (v === null || v === undefined) return "None";
    return typeof v === "string" ? `'${v}'` : String(v);
  }

  const api = { SPEC, EngagementError, ORG, evalWhen, whenQuestions, enabled, setClient, onboard, questionnaire, progress, answer, delegate,
    submitScoping, reopenScoping, effectiveRules, ruleSet, ruleDisable, computeRecommendations, recommend, review, applicableFrameworks,
    finalise, reopenAssignment, overview, validate, roleRegister, enforced, rolesOf, allowed, setRoles, roles, packageDomains, packageAssign,
    packageQuestions, respond, submitItems, reviewItems, submitPackage, returnPackage, packageProgress, packagesOverview, myTasks };
  root.AIC = root.AIC || {};
  root.AIC.engagement = api;
  if (isNode) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
