// SPDX-License-Identifier: Apache-2.0
// Runs the browser logic (site/wizard.js, site/scope.js) under Node for tests/test_site_parity.py.
const fs = require("fs");
const path = require("path");
const root = path.resolve(__dirname, "..");
const W = require(path.join(root, "site", "wizard.js"));
const S = require(path.join(root, "site", "scope.js"));
// (workflow.js is required below, after the dataset is loaded)
const load = (n) => JSON.parse(fs.readFileSync(path.join(root, "data", n + ".json"), "utf8"));
const controls = load("controls");
const data = { controls: controls.controls, frameworks: load("frameworks").frameworks, domains: load("domains").domains,
  dataset_version: controls.dataset_version };

const WF = require(path.join(root, "site", "workflow.js"));

// Runs a list of workflow operations against a scope file; the Python twin lives in tests/test_workflow_parity.py.
function runOps(scope, ops) {
  const sid = "bot";
  const results = [];
  const forCcs = (fn) => Object.keys(WF.state(scope, sid).common_controls).map(fn);
  const handlers = {
    clock: (o) => { WF.setClock(() => new Date(o.iso)); return null; },
    enable: (o) => { WF.enable(scope, sid, o.by); return "ok"; },
    profile: (o) => WF.setProfile(scope, sid, o.by, o.fields),
    target: (o) => WF.setTarget(scope, data, sid, o.by, o.status, o.by_date || null, o.controls || [], o.domain || null, o.framework || null),
    cc_add: (o) => WF.ccAdd(scope, data, sid, o.by, o.title, o.id || null, o.description || "", o.domain || null),
    cc_map: (o) => WF.ccMap(scope, data, sid, o.by, o.cc, o.controls || [], o.domain || null, o.framework || null, Boolean(o.move)),
    cc_suggest: (o) => WF.ccSuggest(scope, data, sid, o.min_frameworks || 1),
    cc_apply: (o) => WF.ccApplySuggestions(scope, data, sid, o.by, WF.ccSuggest(scope, data, sid, 1)),
    gap_accept: (o) => WF.gapAccept(scope, data, sid, o.by, o.controls || [], o.reason, o.domain || null, o.framework || null),
    unmapped: () => WF.unmapped(scope, data, sid).map((c) => c.id),
    cc_set: (o) => WF.ccSet(scope, sid, o.by, o.cc, o.fields),
    cc_set_all: (o) => forCcs((id) => WF.ccSet(scope, sid, o.by, id, o.fields)).length,
    tailor: (o) => { WF.tailor(scope, data, sid, o.by, o.control, o.implementation); return null; },
    indicator: (o) => WF.indicatorAdd(scope, sid, o.by, o.cc, o.name, o.kind, o.metric, o.breach_op, o.value),
    ingest: (o) => WF.ingest(scope, sid, o.by, o.records, o.source || "file"),
    ingest_all: (o) => WF.ingest(scope, sid, o.by, Object.keys(WF.state(scope, sid).common_controls).map((id) => ({ control: id, at: o.at, result: o.result, metrics: o.metrics || {} })), o.source || "feed"),
    evaluate: (o) => WF.evaluate(scope, sid, o.by),
    ack: (o) => { WF.escalationAck(scope, sid, o.by, o.key, o.note || ""); return null; },
    ex_request: (o) => WF.exceptionRequest(scope, data, sid, o.by, o.reason, o.kind || "waiver", o.controls || [], o.cc || null, o.compensating || ""),
    ex_assess: (o) => WF.exceptionAssess(scope, sid, o.by, o.id, o.likelihood, o.impact, o.notes || ""),
    ex_approve: (o) => WF.exceptionApprove(scope, sid, o.by, o.role, o.id, o.days),
    ex_reject: (o) => WF.exceptionReject(scope, sid, o.by, o.role, o.id, o.reason),
    ex_reopen: (o) => WF.exceptionReopen(scope, sid, o.by, o.id, o.reason),
    ex_close: (o) => WF.exceptionClose(scope, sid, o.by, o.id, o.reason),
    policy: (o) => WF.policySet(scope, sid, o.by, o.key, o.value),
    attest: (o) => { WF.attest(scope, data, sid, o.by, o.role || null, o.action, o.note || ""); return null; },
    advance: (o) => WF.advance(scope, data, sid, o.by, Boolean(o.force), o.reason || ""),
    restart: (o) => WF.restartCycle(scope, sid, o.by, o.reason || ""),
    decide: (o) => S.setDecisions(scope, data, sid, o.controls, o.changes),
    gap: (o) => WF.gapAnalysis(scope, data, sid, o.by, null, true),
    poam: () => WF.poam(scope, data, sid),
    verify: (o) => { WF.verify(scope, sid, o.by); return WF.verifyAudit(scope.audit); },
    report: (o) => WF.report(scope, data, sid, o.by, true),
    report_md: (o) => WF.reportMarkdown(scope, data, sid, o.by, true),
    actions: () => WF.actions(scope, data, sid),
    eff: (o) => WF.effectiveness(scope, sid, o.cc),
    exceptions: () => WF.exceptions(scope, sid),
    validate: () => WF.validate(scope, data),
  };
  for (const o of ops) {
    try { results.push({ ok: handlers[o.op](o) }); }
    catch (e) {
      if (e instanceof S.ScopeError) results.push({ error: e.message });
      else throw e;
    }
  }
  return results;
}

const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
let out;
if (job.mode === "wizard") {
  out = job.answers_list.map((a) => W.recommend(a, data.frameworks));
} else if (job.mode === "scope") {
  const sid = job.system;
  const full = S.plan(job.scope, data, sid, job.today);
  out = {
    overall: S.overall(job.scope, data, sid),
    status_framework: S.status(job.scope, data, sid, "framework"),
    status_domain: S.status(job.scope, data, sid, "domain"),
    plan: full,
    soa_rows: S.soaRows(job.scope, data, sid),
    soa_csv: S.soaCsv(job.scope, data, sid),
    plan_md: S.planMarkdown(job.scope, data, sid, full.slice(0, 5), full.length),
    soa_md: S.soaMarkdown(job.scope, data, sid),
    validate: S.validate(job.scope, data),
  };
} else if (job.mode === "build") {
  // Build a scope file the way the browser UI does, so Python and the JSON Schema can check it.
  const recs = W.recommend(job.answers, data.frameworks);
  const chosen = W.selection(recs, "consider");
  const scope = S.newScope("Browser Test Org", data);
  S.addSystem(scope, data, { id: "bot", name: "Bot", description: "d", frameworks: chosen,
    scoping: { date: S.today(), answers: W.normalize(job.answers), include_level: "consider", included: chosen, note: "n" } });
  const ids = S.inScope(scope, data, "bot").map((c) => c.id);
  S.setDecisions(scope, data, "bot", ids.slice(0, 3), { status: "implemented", owner: "Ops", due: "2026-12-31", evidence: ["a", "b"] });
  S.setDecisions(scope, data, "bot", ids.slice(3, 4), { applicable: false, justification: "not relevant" });
  S.setDecisions(scope, data, "bot", ids.slice(4, 6), { owner: "X" });
  S.setDecisions(scope, data, "bot", ids.slice(4, 5), { owner: null }, { allowClear: true });
  out = scope;
} else if (job.mode === "wfops") {
  const results = runOps(job.scope, job.ops);
  out = { results, scope: job.scope };
} else if (job.mode === "sha") {
  out = { sha: job.strings.map((s) => WF.sha256(s)), canon: job.objects.map((o) => WF.canon(o)), spec: WF.SPEC };
} else if (job.mode === "errors") {
  out = job.answers_list.map((a) => { try { W.normalize(a); return null; } catch (e) { return e.message; } });
}
process.stdout.write(JSON.stringify(out));
