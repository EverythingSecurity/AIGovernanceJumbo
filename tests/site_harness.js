// SPDX-License-Identifier: Apache-2.0
// Runs the browser logic (site/wizard.js, site/scope.js) under Node for tests/test_site_parity.py.
const fs = require("fs");
const path = require("path");
const root = path.resolve(__dirname, "..");
const W = require(path.join(root, "site", "wizard.js"));
const S = require(path.join(root, "site", "scope.js"));
const load = (n) => JSON.parse(fs.readFileSync(path.join(root, "data", n + ".json"), "utf8"));
const controls = load("controls");
const data = { controls: controls.controls, frameworks: load("frameworks").frameworks, domains: load("domains").domains,
  dataset_version: controls.dataset_version };

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
} else if (job.mode === "errors") {
  out = job.answers_list.map((a) => { try { W.normalize(a); return null; } catch (e) { return e.message; } });
}
process.stdout.write(JSON.stringify(out));
