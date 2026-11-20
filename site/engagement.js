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
    if (!scope.schema_version || ["1.0", "1.1", "1.2"].includes(scope.schema_version)) scope.schema_version = SCHEMA_VERSION;
    return e;
  }
  const audit = (scope, actor, action, target, details) => W.audit(scope, ORG, actor, ROLE, action, target, details || {});
  const actorOf = (a) => W.checkActor(a);
  function need(scope) {
    if (!enabled(scope)) fail("the engagement is not started; set the client first (engagement client set)");
    return e0(scope);
  }

  // ---- client and onboarding ------------------------------------------------------------------------------------
  function setClient(scope, actor, fields) {
    actor = actorOf(actor);
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
  function finalise(scope, actor, justification) {
    actor = actorOf(actor);
    const e = need(scope);
    const rec = e.recommendation;
    if (!rec) fail("run the recommendation first (engagement recommend)");
    if (e.applicable) fail("the framework set is already finalised");
    const pending = rec.items.filter((i) => !(i.framework in e.review)).map((i) => i.framework);
    if (pending.length) fail(`review every recommendation first (accept or remove); not yet reviewed: ${pending.join(", ")}`);
    const fws = applicableFrameworks(scope);
    if (!fws.length) fail("the applicable framework set is empty; add at least one framework");
    e.applicable = { frameworks: fws, approver: actor, at: W.stamp(), justification: (justification || "").trim(), rules_version: rec.rules_version };
    audit(scope, actor, "ENGAGEMENT_FINALISED", "applicable-frameworks", { frameworks: fws });
    return e.applicable;
  }
  function reopenAssignment(scope, actor, reason) {
    actor = actorOf(actor);
    const e = need(scope);
    reason = (reason || "").trim();
    if (!reason) fail("a reason is required to reopen the assignment");
    if (!e.applicable) fail("the framework set is not finalised");
    e.applicable = null;
    audit(scope, actor, "ENGAGEMENT_ASSIGNMENT_REOPENED", "applicable-frameworks", { reason });
    return { reopened: true };
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
    return { errors: errs, warnings: warns };
  }
  // Python's repr() of a string or null, so messages match the Python engine.
  function pyRepr(v) {
    if (v === null || v === undefined) return "None";
    return typeof v === "string" ? `'${v}'` : String(v);
  }

  const api = { SPEC, EngagementError, ORG, evalWhen, whenQuestions, enabled, setClient, onboard, questionnaire, progress, answer, delegate,
    submitScoping, reopenScoping, effectiveRules, ruleSet, ruleDisable, computeRecommendations, recommend, review, applicableFrameworks,
    finalise, reopenAssignment, overview, validate };
  root.AIC = root.AIC || {};
  root.AIC.engagement = api;
  if (isNode) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
