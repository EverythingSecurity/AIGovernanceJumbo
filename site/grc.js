// SPDX-License-Identifier: Apache-2.0
// GRC management layer: a faithful port of src/aicontrols/grc.py, working on the same scope file.
// Python and this file are run side by side on scripted scenarios by tests/test_grc_parity.py, which
// compares every result and the resulting file (audit hash chain included), so change them together.
// Pure functions: no DOM, no network, no storage. The model itself is in grc-spec.js, generated from
// src/aicontrols/grc_spec.json.
(function (root) {
  "use strict";
  const isNode = typeof module !== "undefined" && module.exports;
  const S = isNode ? require("./scope.js") : root.AIC.scope;
  const W = isNode ? require("./workflow.js") : root.AIC.workflow;
  const SPEC = isNode ? require("./grc-spec.js") : root.AIC.grcSpec;

  const GRC_SCHEMA_VERSION = "1.2";
  const ORG = "(organisation)", ROLE_GRC = "GRC_OFFICE";
  const APPETITE_ALLOWED = { low: 0, moderate: 1, high: 2 };
  const DOC_CATEGORIES = ["policy", "guideline", "sop"];
  const RATINGS = W.RATINGS;
  const MATRIX_COLUMNS = ["requirement_id", "framework", "clause", "requirement", "control_id", "policy", "guideline", "sop",
    "evidence", "status", "mapping_owner", "mapping_reviewed", "issues"];
  const ISSUE_TEXT = {
    unmapped: "no control and not recorded as a gap", no_policy: "control has no policy", no_sop: "control has no SOP",
    no_evidence_source: "control has no evidence source", no_mapping_owner: "mapping has no owner",
    no_review_date: "mapping has no review date", review_overdue: "mapping review is overdue",
  };

  class GrcError extends W.WorkflowError {}

  // ---- dates and numbers ----------------------------------------------------------------------------------------
  const DAYMS = 86400000;
  function parseDate(value, name) {
    const bad = () => new GrcError(`${name || "date"} must be a date like 2026-12-31, got '${value}'`);
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw bad();
    const ms = Date.parse(value + "T00:00:00Z");
    if (Number.isNaN(ms) || new Date(ms).toISOString().slice(0, 10) !== value) throw bad();
    return value;
  }
  const dms = (s) => Date.parse(s + "T00:00:00Z");
  function addMonths(dateStr, n) {
    const [y0, m0, d0] = dateStr.split("-").map(Number);
    const total = y0 * 12 + (m0 - 1) + n;
    const y = Math.floor(total / 12), m = total % 12;
    const last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    const p = (v, w) => String(v).padStart(w, "0");
    return `${p(y, 4)}-${p(m + 1, 2)}-${p(Math.min(d0, last), 2)}`;
  }
  const round1 = (x) => Math.round(x * 10) / 10;
  const pct = (num, den) => (den ? round1((100 * num) / den) : null);
  function matches(pattern, ref) {
    if (pattern.endsWith(".*")) { const prefix = pattern.slice(0, -1); return ref.startsWith(prefix) ? prefix.length : null; }
    return ref === pattern ? 1000 + pattern.length : null;
  }
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  // ---- state ----------------------------------------------------------------------------------------------------------
  const g = (scope) => scope.grc || {};
  function ensure(scope) {
    const gr = (scope.grc = scope.grc || {});
    for (const name of Object.keys(SPEC.registers)) gr[name] = gr[name] || {};
    gr.settings = gr.settings || {}; gr.framework_scopes = gr.framework_scopes || {}; gr.roles = gr.roles || {};
    if (!("scope_reviewed" in gr)) gr.scope_reviewed = null;
    gr.markers = gr.markers || { report_at: null };
    if (!scope.schema_version || scope.schema_version === "1.0" || scope.schema_version === "1.1") scope.schema_version = GRC_SCHEMA_VERSION;
    return gr;
  }
  function regSpec(register) {
    if (!SPEC.registers[register]) throw new GrcError(`unknown register '${register}'; choose from ${Object.keys(SPEC.registers).join(", ")}`);
    return SPEC.registers[register];
  }
  const records = (scope, register) => { regSpec(register); return Object.values(g(scope)[register] || {}); };
  function get(scope, register, id) {
    const rec = (g(scope)[register] || {})[id];
    if (!rec) throw new GrcError(`unknown ${regSpec(register).singular} '${id}'`);
    return rec;
  }
  const audit = (scope, actor, action, target, details) => W.audit(scope, ORG, actor, ROLE_GRC, action, target, details || {});
  const actorOf = (actor) => W.checkActor(actor);

  // ---- settings ---------------------------------------------------------------------------------------------------------------
  function settings(scope) {
    const s = JSON.parse(JSON.stringify(SPEC.settings_defaults));
    for (const [k, v] of Object.entries(g(scope).settings || {})) s[k] = v && typeof v === "object" ? { ...v } : v;
    if (!s.coverage_targets) s.coverage_targets = {};
    return s;
  }
  function setSetting(scope, data, actor, key, value) {
    actor = actorOf(actor);
    const ix = S.index(data);
    const st = ensure(scope).settings;
    const bad = () => new GrcError(`invalid value '${value}' for ${key}`);
    const v = String(value);
    if (key === "anchor_framework") {
      if (!ix.fw[v]) throw new GrcError(`unknown framework '${v}'`);
      st[key] = v;
    } else if (key === "risk_appetite") {
      if (!(v in APPETITE_ALLOWED)) throw bad();
      st[key] = v;
    } else if (key === "mapping_review_months" || key === "scope_review_months") {
      if (!/^\d+$/.test(v.trim()) || parseInt(v, 10) < 1) throw bad();
      st[key] = parseInt(v, 10);
    } else if (key.startsWith("coverage_target.")) {
      const fw = key.split(".").slice(1).join(".");
      if (!ix.fw[fw]) throw new GrcError(`unknown framework '${fw}'`);
      const targets = (st.coverage_targets = st.coverage_targets || {});
      if (v.trim() === "") delete targets[fw];
      else {
        if (!/^\d+$/.test(v.trim()) || parseInt(v, 10) < 0 || parseInt(v, 10) > 100) throw bad();
        targets[fw] = parseInt(v, 10);
      }
    } else throw new GrcError(`unknown setting '${key}'`);
    audit(scope, actor, "GRC_SETTING_CHANGED", key, { value: v });
    return settings(scope);
  }

  // ---- registers ----------------------------------------------------------------------------------------------------------------
  function checkField(f, value) {
    const { label, kind } = f;
    if (kind === "text") return String(value).trim();
    if (kind === "enum") {
      const v = String(value).trim().toLowerCase();
      if (!f.values.includes(v)) throw new GrcError(`${label} must be one of ${f.values.join(", ")}, got '${value}'`);
      return v;
    }
    if (kind === "date") { parseDate(String(value).trim(), label); return String(value).trim(); }
    if (kind === "int") {
      const t = String(value).trim();
      if (typeof value === "boolean" || !/^\d+$/.test(t) || parseInt(t, 10) < (f.min || 0)) throw new GrcError(`${label} must be a whole number of at least ${f.min || 0}, got '${value}'`);
      return parseInt(t, 10);
    }
    throw new GrcError(`unsupported field kind '${kind}'`);
  }
  function merge(register, existing, fields) {
    const spec = regSpec(register);
    const byName = Object.fromEntries(spec.fields.map((f) => [f.name, f]));
    const unknown = Object.keys(fields).filter((k) => !(k in byName)).sort();
    if (unknown.length) throw new GrcError(`unknown field(s) for ${spec.singular}: ${unknown.join(", ")}`);
    const rec = { ...(existing || {}) };
    for (const [name, value] of Object.entries(fields)) {
      if (value === null || value === undefined) continue;
      if (String(value).trim() === "") { delete rec[name]; continue; }
      rec[name] = checkField(byName[name], value);
    }
    for (const f of spec.fields) if (!(f.name in rec) && "default" in f) rec[f.name] = f.default;
    for (const f of spec.fields) if (f.required && !rec[f.name]) throw new GrcError(`${f.label} is required`);
    const today = W.todayStr();
    if (register === "scope_items" && rec.kind === "exclusion" && !rec.justification) throw new GrcError("an exclusion needs a justification");
    if (register === "findings") {
      if (rec.status === "closed") { if (!rec.closed) rec.closed = today; } else delete rec.closed;
      if (dms(parseDate(rec.due, "Due")) < dms(parseDate(rec.raised, "Raised on"))) throw new GrcError("Due cannot be before the raised date");
    }
    if (register === "documents" && rec.status === "approved") {
      if (!rec.approved) rec.approved = today;
      if (!rec.next_review || (existing && "review_months" in fields && !("next_review" in fields))) rec.next_review = addMonths(parseDate(rec.approved), rec.review_months);
    }
    if (register === "audits" && rec.completed && dms(parseDate(rec.completed, "Completed on")) < dms(parseDate(rec.planned, "Planned for"))) {
      throw new GrcError("Completed on cannot be before the planned date");
    }
    return rec;
  }
  function add(scope, register, actor, fields) {
    actor = actorOf(actor);
    const spec = regSpec(register);
    const rec = merge(register, null, fields);
    const table = ensure(scope)[register];
    let n = Object.keys(table).length + 1;
    while (`${spec.id_prefix}-${String(n).padStart(3, "0")}` in table) n++;
    const id = `${spec.id_prefix}-${String(n).padStart(3, "0")}`;
    const out = { id, ...rec };
    table[id] = out;
    audit(scope, actor, `GRC_${register.toUpperCase()}_ADDED`, id, { summary: out.title || out.name || out.type || id });
    return out;
  }
  function update(scope, register, actor, id, fields) {
    actor = actorOf(actor);
    const existing = get(scope, register, id);
    const merged = merge(register, existing, fields);
    merged.id = id;
    const changed = [...new Set([...Object.keys(merged), ...Object.keys(existing)])].filter((k) => !same(merged[k], existing[k])).sort();
    g(scope)[register][id] = merged;
    if (changed.length) audit(scope, actor, `GRC_${register.toUpperCase()}_UPDATED`, id, { changed });
    return merged;
  }
  function remove(scope, register, actor, id) {
    actor = actorOf(actor);
    get(scope, register, id);
    delete g(scope)[register][id];
    for (const st of Object.values(scope.workflow || {})) {
      for (const cc of Object.values(st.common_controls || {})) {
        if (register === "documents") for (const cat of DOC_CATEGORIES) {
          const list = (cc.documents || {})[cat] || [];
          const i = list.indexOf(id); if (i >= 0) list.splice(i, 1);
        }
        if (register === "evidence_sources") { const i = (cc.evidence_sources || []).indexOf(id); if (i >= 0) cc.evidence_sources.splice(i, 1); }
      }
    }
    audit(scope, actor, `GRC_${register.toUpperCase()}_REMOVED`, id, {});
  }

  // ---- links, statements, reviews, roles ---------------------------------------------------------------------------------------
  function link(scope, systemId, actor, ccId, opts) {
    const o = opts || {};
    const sid = S.system(scope, systemId).id;
    actor = actorOf(actor);
    const cc = W.cc(scope, sid, ccId);
    cc.documents = cc.documents || { policy: [], guideline: [], sop: [] };
    for (const cat of DOC_CATEGORIES) cc.documents[cat] = cc.documents[cat] || [];
    const changed = {};
    for (const [cat, ids] of [["policy", o.policy || []], ["guideline", o.guideline || []], ["sop", o.sop || []]]) {
      for (const docId of ids) {
        const doc = get(scope, "documents", docId);
        if (doc.type !== cat) throw new GrcError(`${docId} is a ${doc.type}, not a ${cat}`);
        const list = cc.documents[cat];
        if (o.unlink) { const i = list.indexOf(docId); if (i >= 0) list.splice(i, 1); }
        else if (!list.includes(docId)) list.push(docId);
        (changed[cat] = changed[cat] || []).push(docId);
      }
    }
    cc.evidence_sources = cc.evidence_sources || [];
    for (const srcId of o.evidence_sources || []) {
      get(scope, "evidence_sources", srcId);
      if (o.unlink) { const i = cc.evidence_sources.indexOf(srcId); if (i >= 0) cc.evidence_sources.splice(i, 1); }
      else if (!cc.evidence_sources.includes(srcId)) cc.evidence_sources.push(srcId);
      (changed.evidence_sources = changed.evidence_sources || []).push(srcId);
    }
    if (!Object.keys(changed).length) throw new GrcError("nothing to link: give --policy, --guideline, --sop or --evidence-source");
    audit(scope, actor, o.unlink ? "GRC_LINKS_REMOVED" : "GRC_LINKS_ADDED", `${sid}/${ccId}`, changed);
    return cc;
  }
  function setScopeStatement(scope, data, actor, frameworkId, statement, reviewed) {
    actor = actorOf(actor);
    if (!S.index(data).fw[frameworkId]) throw new GrcError(`unknown framework '${frameworkId}'`);
    if (!String(statement).trim()) throw new GrcError("a scope statement cannot be empty");
    reviewed = reviewed || W.todayStr();
    parseDate(reviewed, "reviewed");
    const gr = ensure(scope);
    gr.framework_scopes[frameworkId] = { statement: String(statement).trim(), reviewed };
    audit(scope, actor, "GRC_SCOPE_STATEMENT_SET", frameworkId, { reviewed });
    return gr.framework_scopes[frameworkId];
  }
  function reviewScope(scope, actor, date) {
    actor = actorOf(actor);
    date = date || W.todayStr();
    parseDate(date, "date");
    ensure(scope).scope_reviewed = date;
    audit(scope, actor, "GRC_SCOPE_REVIEWED", ORG, { date });
    return date;
  }
  function reviewMappings(scope, systemId, actor, ccId, owner, date) {
    const sid = S.system(scope, systemId).id;
    actor = actorOf(actor);
    W.cc(scope, sid, ccId);
    if (!String(owner).trim()) throw new GrcError("a mapping review needs an owner");
    date = date || W.todayStr();
    parseDate(date, "date");
    const members = W.members(scope, sid, ccId);
    if (!members.length) throw new GrcError(`${ccId} has no mapped requirements`);
    for (const cid of members) { const r = W.rec(scope, sid, cid); r.mapping_owner = String(owner).trim(); r.mapping_reviewed = date; }
    ensure(scope);
    audit(scope, actor, "GRC_MAPPINGS_REVIEWED", `${sid}/${ccId}`, { count: members.length, date });
    return members.length;
  }
  function setRoles(scope, actor, roleId, names) {
    actor = actorOf(actor);
    if (!SPEC.roles.some((r) => r.id === roleId)) throw new GrcError(`unknown role '${roleId}'; choose from ${SPEC.roles.map((r) => r.id).join(", ")}`);
    const clean = [];
    for (const n of names) { const t = String(n).trim(); if (t && !clean.includes(t)) clean.push(t); }
    const gr = ensure(scope);
    if (clean.length) gr.roles[roleId] = clean; else delete gr.roles[roleId];
    audit(scope, actor, "GRC_ROLE_ASSIGNED", roleId, { people: clean.length });
    return clean;
  }
  function seedEvidenceSources(scope, actor) {
    const have = new Set(records(scope, "evidence_sources").map((r) => `${r.type}\u0000${r.source}`));
    let n = 0;
    for (const d of SPEC.evidence_defaults) if (!have.has(`${d.type}\u0000${d.source}`)) { add(scope, "evidence_sources", actor, { ...d }); n++; }
    ensure(scope);
    return n;
  }

  // ---- computed views ---------------------------------------------------------------------------------------------------------------
  function context(scope, systemId) {
    const sid = S.system(scope, systemId).id;
    const ccs = W.enabled(scope, sid) ? W.state(scope, sid).common_controls : {};
    const eff = {}, current = {};
    for (const id of Object.keys(ccs)) { eff[id] = W.effectiveness(scope, sid, id); current[id] = !["not_tested", "stale"].includes(eff[id].state); }
    return { sid, ccs, eff, current };
  }
  function atTarget(scope, sid, controlId, status) {
    const target = W.enabled(scope, sid) ? W.targetOf(scope, sid, controlId)[0] : "implemented";
    const order = ["not_started", "in_progress", "implemented", "verified"];
    return order.indexOf(status) >= order.indexOf(target);
  }

  function matrix(scope, data, systemId) {
    const { sid, ccs, eff, current } = context(scope, systemId);
    const ix = S.index(data);
    const st = settings(scope);
    const sources = Object.fromEntries(records(scope, "evidence_sources").map((r) => [r.id, r]));
    const table = (scope.decisions || {})[sid] || {};
    const today = W.todayStr();
    const rows = [];
    for (const [c, d] of S.rows(scope, data, sid)) {
      if (!d.applicable) continue;
      const rec = table[c.id] || {};
      const ccId = rec.common_control;
      const cc = ccId ? ccs[ccId] : undefined;
      const gap = rec.common_control_gap;
      const docs = (cc && cc.documents) || {};
      const [policy, guideline, sop] = DOC_CATEGORIES.map((k) => [...(docs[k] || [])]);
      const srcIds = ((cc && cc.evidence_sources) || []).filter((x) => x in sources);
      const state = cc ? eff[ccId].state : null;
      let status;
      if (!cc) status = gap ? "Gap" : "Unmapped";
      else if (S.DONE.includes(d.status)) status = current[ccId] ? "Implemented" : "Partial";
      else if (d.status === "in_progress") status = "Partial";
      else status = "Not started";
      const owner = rec.mapping_owner || d.owner || (cc && cc.owner) || "";
      const reviewed = rec.mapping_reviewed;
      const issues = [];
      if (!cc && !gap) issues.push("unmapped");
      if (cc) {
        if (!policy.length) issues.push("no_policy");
        if (!sop.length) issues.push("no_sop");
        if (!srcIds.length) issues.push("no_evidence_source");
        if (!owner) issues.push("no_mapping_owner");
        if (!reviewed) issues.push("no_review_date");
        else if (addMonths(parseDate(reviewed), st.mapping_review_months) < today) issues.push("review_overdue");
      }
      rows.push({
        requirement_id: c.id, framework_id: c.framework_id, framework: ix.fw[c.framework_id].name, ref: c.ref, clause: c.ref,
        requirement: c.title, domain: ix.dom[c.domain_id].name, requirement_status: d.status, control_id: cc ? ccId : "",
        control_title: cc ? cc.title : "", gap_reason: gap || "", policy, guideline, sop, evidence_sources: srcIds,
        evidence: srcIds.map((x) => sources[x].type).join(", "), evidence_state: state, status, mapping_owner: owner,
        mapping_reviewed: reviewed || "", issues,
      });
    }
    return rows;
  }
  function matrixSummary(rows) {
    const byStatus = {}, byIssue = {};
    for (const r of rows) { byStatus[r.status] = (byStatus[r.status] || 0) + 1; for (const i of r.issues) byIssue[i] = (byIssue[i] || 0) + 1; }
    const sortObj = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));
    return { requirements: rows.length, by_status: sortObj(byStatus), by_issue: sortObj(byIssue) };
  }
  function matrixCsv(scope, data, systemId) {
    const lines = [S.csvLine(MATRIX_COLUMNS)];
    for (const r of matrix(scope, data, systemId)) {
      const cells = { requirement_id: r.requirement_id, framework: r.framework, clause: r.ref, requirement: r.requirement,
        control_id: r.control_id || (r.gap_reason ? "GAP: " + r.gap_reason : ""), policy: r.policy.join("; "), guideline: r.guideline.join("; "),
        sop: r.sop.join("; "), evidence: r.evidence, status: r.status, mapping_owner: r.mapping_owner, mapping_reviewed: r.mapping_reviewed,
        issues: r.issues.map((i) => ISSUE_TEXT[i]).join("; ") };
      lines.push(S.csvLine(MATRIX_COLUMNS.map((k) => cells[k])));
    }
    return lines.join("\r\n") + "\r\n";
  }

  function coverage(scope, data, systemId) {
    const { sid, current } = context(scope, systemId);
    const ix = S.index(data);
    const st = settings(scope);
    const rows = matrix(scope, data, sid);
    const fws = S.system(scope, sid).frameworks;
    const anchor = fws.includes(st.anchor_framework) ? st.anchor_framework : null;
    const ccFws = {};
    for (const r of rows) if (r.control_id) (ccFws[r.control_id] = ccFws[r.control_id] || new Set()).add(r.framework_id);
    const covered = (r) => Boolean(r.control_id) && S.DONE.includes(r.requirement_status) && Boolean(current[r.control_id]);
    const out = [];
    let reqT = 0, covT = 0;
    for (const fid of fws) {
      const mine = rows.filter((r) => r.framework_id === fid);
      const required = mine.length;
      const mapped = mine.filter((r) => r.control_id).length;
      const implemented = mine.filter((r) => S.DONE.includes(r.requirement_status)).length;
      const cov = mine.filter(covered).length;
      let reused = null;
      if (anchor && fid !== anchor) reused = mine.filter((r) => covered(r) && (ccFws[r.control_id] || new Set()).has(anchor)).length;
      const target = (st.coverage_targets || {})[fid];
      const p = pct(cov, required);
      out.push({ framework_id: fid, name: ix.fw[fid].name, required, mapped, implemented, covered: cov, coverage_pct: p, mapped_pct: pct(mapped, required),
        incremental: reused, incremental_pct: reused !== null ? pct(reused, required) : null, target: target === undefined ? null : target,
        meets_target: target === undefined || p === null ? null : p >= target });
      reqT += required; covT += cov;
    }
    return { anchor, frameworks: out, overall: { required: reqT, covered: covT, coverage_pct: pct(covT, reqT) } };
  }

  function kpis(scope, data, systemId) {
    const { sid, ccs, current } = context(scope, systemId);
    const st = settings(scope);
    const today = W.todayStr();
    const rows = matrix(scope, data, sid);
    const mapped = rows.filter((r) => r.control_id).length;
    const gaps = rows.filter((r) => r.status === "Gap").length;
    const findings = records(scope, "findings");
    const audits = records(scope, "audits");
    const openF = findings.filter((f) => f.status === "open");
    const pastDue = openF.filter((f) => parseDate(f.due) < today);
    const crit = pastDue.filter((f) => f.severity === "critical");
    const docs = records(scope, "documents").filter((d) => d.status === "approved");
    const curDocs = docs.filter((d) => d.next_review && parseDate(d.next_review) >= today);
    const allowed = APPETITE_ALLOWED[st.risk_appetite];
    const risks = records(scope, "risks");
    const risky = risks.filter((r) => r.status === "open" && RATINGS.indexOf(r.residual) > allowed && !r.treatment_plan && (r.treatment_status || "none") === "none");
    const cov = coverage(scope, data, sid);
    const nCur = Object.values(current).filter(Boolean).length;
    const nCc = Object.keys(ccs).length;
    const hasFA = findings.length > 0 || audits.length > 0;
    const values = {
      requirements_mapped: [pct(mapped, rows.length), `${mapped} of ${rows.length} requirements mapped; ${gaps} recorded as gaps`],
      controls_current_evidence: [pct(nCur, nCc), `${nCur} of ${nCc} controls have current evidence`],
      findings_past_due_critical: [hasFA ? crit.length : null, hasFA ? `${pastDue.length} open finding(s) past due in total; ${openF.length} open` : "no audits or findings recorded yet"],
      policy_review_currency: [pct(curDocs.length, docs.length), `${curDocs.length} of ${docs.length} approved documents are within their review cycle`],
      risks_above_appetite: [risks.length ? risky.length : null, risks.length ? `appetite is ${st.risk_appetite}; ${risky.length} open risk(s) above it have no treatment plan` : "no risks recorded yet"],
      cross_framework_coverage: [cov.overall.coverage_pct, `${cov.overall.covered} of ${cov.overall.required} requirements implemented and evidenced`],
    };
    return SPEC.kpis.map((k) => {
      const [value, detail] = values[k.id];
      let status;
      if (value === null) status = "no_data";
      else if (k.op === null) status = "info";
      else status = (k.op === ">=" ? value >= k.target : value === k.target) ? "met" : "not_met";
      return { id: k.id, name: k.name, type: k.type, value, unit: k.unit, target_text: k.target_text, status, detail };
    });
  }

  function streams(scope, data, systemId) {
    const { sid, current } = context(scope, systemId);
    const rows = matrix(scope, data, sid).filter((r) => r.framework_id === "iso-42001");
    const assign = {};
    for (const r of rows) {
      let best = -1, bestStream = null;
      for (const s of SPEC.streams) for (const pat of s.refs) { const m = matches(pat, r.ref); if (m !== null && m > best) { best = m; bestStream = s.id; } }
      assign[r.requirement_id] = bestStream || "unassigned";
    }
    const out = [];
    for (const s of SPEC.streams) {
      const mine = rows.filter((r) => assign[r.requirement_id] === s.id);
      const mapped = mine.filter((r) => r.control_id).length;
      const impl = mine.filter((r) => S.DONE.includes(r.requirement_status)).length;
      const cov = mine.filter((r) => r.control_id && S.DONE.includes(r.requirement_status) && current[r.control_id]).length;
      out.push({ id: s.id, name: s.name, focus: s.focus, delivered_through: s.delivered_through, requirements: mine.length, mapped, implemented: impl,
        covered: cov, mapped_pct: pct(mapped, mine.length), implemented_pct: pct(impl, mine.length), coverage_pct: pct(cov, mine.length) });
    }
    const stray = rows.filter((r) => assign[r.requirement_id] === "unassigned").map((r) => r.requirement_id);
    if (stray.length) out.push({ id: "unassigned", name: "Unassigned", focus: "", delivered_through: "", requirements: stray.length, mapped: 0, implemented: 0, covered: 0,
      mapped_pct: null, implemented_pct: null, coverage_pct: null });
    return out;
  }

  const wfMarker = (scope, sid, key) => (W.enabled(scope, sid) ? W.state(scope, sid).markers[key] : null);

  function lifecycle(scope, data, systemId) {
    const { sid, ccs } = context(scope, systemId);
    const st = settings(scope);
    const today = W.todayStr();
    const s = S.system(scope, sid);
    const rows = matrix(scope, data, sid);
    const items = records(scope, "scope_items");
    const kinds = (...ks) => items.filter((i) => ks.includes(i.kind)).length;
    const regs = kinds("regulation");
    const reviewed = g(scope).scope_reviewed;
    const scopeFresh = Boolean(reviewed) && addMonths(parseDate(reviewed), st.scope_review_months) >= today;
    const mapped = rows.filter((r) => r.control_id).length;
    const unmapped = rows.filter((r) => r.status === "Unmapped").length;
    const used = [...new Set(rows.filter((r) => r.control_id).map((r) => r.control_id))];
    const incomplete = used.filter((cid) => !((ccs[cid].documents || {}).policy || []).length || !((ccs[cid].documents || {}).sop || []).length).length;
    const risks = records(scope, "risks");
    const gapRun = wfMarker(scope, sid, "gap_run_at");
    const atT = rows.filter((r) => atTarget(scope, sid, r.requirement_id, r.requirement_status)).length;
    const kp = Object.fromEntries(kpis(scope, data, sid).map((k) => [k.id, k]));
    const audits = records(scope, "audits");
    const doneInternal = audits.filter((a) => a.kind === "internal" && a.completed);
    const doneExternal = audits.filter((a) => a.kind === "external" && a.completed);
    const doneReview = audits.filter((a) => a.kind === "management_review" && a.completed);
    const openPast = records(scope, "findings").filter((f) => f.status === "open" && parseDate(f.due) < today).length;
    const reportAt = wfMarker(scope, sid, "report_at") || (g(scope).markers || {}).report_at || null;
    const risksAbove = kp.risks_above_appetite.value || 0;
    const ev = kp.controls_current_evidence;
    const steps = [
      [s.frameworks.length >= 1 && regs >= 1, `${s.frameworks.length} framework(s) selected; ${regs} regulation(s) recorded`, "Record the regulations that apply in the scope register."],
      [kinds("business_unit", "department") >= 1 && kinds("system", "ai_system", "data_set") >= 1 && scopeFresh,
        `${kinds("business_unit", "department")} business unit(s)/department(s), ${kinds("system", "ai_system", "data_set")} system(s)/data set(s); ` + (reviewed ? "scope reviewed " + reviewed : "scope not yet reviewed"),
        "Fill the scope register and mark the scope reviewed."],
      [rows.length > 0, `${rows.length} requirements from ${s.frameworks.length} framework(s)`, "Select frameworks for the system."],
      [rows.length > 0 && unmapped === 0 && incomplete === 0, `${mapped} of ${rows.length} requirements mapped; ${unmapped} unmapped; ${incomplete} control(s) lack a policy or SOP`,
        "Map every requirement to a control (or record a gap) and link a policy and SOP to each control."],
      [gapRun !== null && risks.length >= 1, `gap analysis ${gapRun ? "run" : "not run"}; ${risks.length} risk(s) registered`, "Run the gap analysis and record risks with owners."],
      [rows.length > 0 && atT === rows.length && risksAbove === 0, `${atT} of ${rows.length} requirements at target; ${risksAbove} untreated risk(s) above appetite`,
        "Implement the open requirements and treat risks above appetite."],
      [ev.value !== null && ev.value >= 95, ev.detail, "Ingest test results so each control has current evidence."],
      [doneInternal.length >= 1, `${doneInternal.length} internal and ${doneExternal.length} external audit(s) completed`, "Plan and complete an internal audit, then an external one."],
      [reportAt !== null, reportAt ? "a report has been generated" : "no report generated yet", "Generate the GRC report for leadership."],
      [doneReview.length >= 1 && openPast === 0, `${doneReview.length} management review(s) completed; ${openPast} finding(s) past due`, "Hold a management review and close overdue findings."],
    ];
    return SPEC.lifecycle.map((l, i) => ({ n: l.n, id: l.id, title: l.title, done: Boolean(steps[i][0]), detail: steps[i][1], hint: steps[i][2] }));
  }

  function artifacts(scope, data, systemId) {
    const { sid, ccs, eff } = context(scope, systemId);
    const s = S.system(scope, sid);
    const rows = matrix(scope, data, sid);
    const items = records(scope, "scope_items");
    const docs = records(scope, "documents");
    const types = new Set(docs.map((d) => d.type));
    const sources = records(scope, "evidence_sources");
    const withResults = Object.values(eff).filter((e) => e.state !== "not_tested").length;
    const kvals = kpis(scope, data, sid).filter((k) => k.value !== null).length;
    const audits = records(scope, "audits"), findings = records(scope, "findings");
    const fscopes = g(scope).framework_scopes || {};
    const mapped = rows.filter((r) => r.control_id).length;
    const regs = items.filter((i) => i.kind === "regulation").length;
    const grade = (full, some) => (full ? "ready" : some ? "partial" : "missing");
    const nFs = s.frameworks.filter((f) => f in fscopes).length;
    const vals = [
      [grade(s.frameworks.length > 0 && regs >= 1, s.frameworks.length > 0), `${s.frameworks.length} framework(s), ${regs} regulation(s)`],
      [grade(s.frameworks.every((f) => f in fscopes), nFs > 0), `${nFs} of ${s.frameworks.length} framework(s) have a scope statement`],
      ["ready", `${rows.length} requirements (from the dataset)`],
      [grade(Object.keys(ccs).length >= 1, false), `${Object.keys(ccs).length} common control(s)`],
      [grade(rows.length > 0 && mapped === rows.length, mapped > 0), `${mapped} of ${rows.length} requirements mapped`],
      [grade(DOC_CATEGORIES.every((c) => types.has(c)), types.size > 0), `${docs.length} document(s): ${[...types].sort().join(", ") || "none"}`],
      [grade(records(scope, "risks").some((r) => r.business_unit), false), `${records(scope, "risks").length} risk(s)`],
      [grade(sources.length >= 1 && withResults >= 1, sources.length >= 1 || withResults >= 1), `${sources.length} evidence source(s); ${withResults} control(s) with results`],
      [grade(kvals >= 3, kvals >= 1), `${kvals} of ${SPEC.kpis.length} KPIs/KRIs have data`],
      [grade(audits.length >= 1 && (findings.length >= 1 || audits.some((a) => a.completed)), audits.length >= 1 || findings.length >= 1), `${audits.length} audit(s), ${findings.length} finding(s)`],
    ];
    return SPEC.artifacts.map((a, i) => ({ id: a.id, title: a.title, status: vals[i][0], detail: vals[i][1] }));
  }

  function roles(scope) {
    const assigned = g(scope).roles || {};
    return SPEC.roles.map((r) => ({ ...r, people: [...(assigned[r.id] || [])] }));
  }

  function report(scope, data, systemId, actor, record) {
    const sid = S.system(scope, systemId).id;
    const rows = matrix(scope, data, sid);
    const out = { system: sid, organisation: scope.organization, as_of: W.todayStr(), lifecycle: lifecycle(scope, data, sid), kpis: kpis(scope, data, sid),
      coverage: coverage(scope, data, sid), matrix: matrixSummary(rows), artifacts: artifacts(scope, data, sid), streams: streams(scope, data, sid) };
    if (record) {
      ensure(scope).markers.report_at = W.stamp();
      audit(scope, actorOf(actor || "system"), "GRC_REPORT_GENERATED", sid, { as_of: out.as_of });
    }
    return out;
  }
  function reportMarkdown(scope, data, systemId, actor, record) {
    const r = report(scope, data, systemId, actor, record !== false);
    const s = S.system(scope, systemId);
    const fmt = (v, u) => (v === null || v === undefined ? "no data" : `${v}${u}`);
    const num1 = (v) => (v === null ? null : Number.isInteger(v) ? v.toFixed(1) : String(v));   // Python prints 100.0, not 100
    const fv = (v, u) => (v === null || v === undefined ? "no data" : `${num1(v)}${u}`);
    const label = { met: "met", not_met: "not met", no_data: "no data", info: "for information" };
    const lines = [`# GRC report: ${s.name}`, "", `Organisation: ${r.organisation}  `, `As of: ${r.as_of}`, "", "## KPIs and KRIs", "",
      "| Metric | Type | Value | Target | Status |", "|---|---|---:|---|---|"];
    const kv = (k) => (k.unit === "%" ? fv(k.value, k.unit) : (k.value === null ? "no data" : `${k.value}${k.unit}`));
    for (const k of r.kpis) lines.push(`| ${k.name} | ${k.type} | ${kv(k)} | ${k.target_text} | ${label[k.status]} |`);
    lines.push("", "## Coverage by framework", "",
      `Method: coverage = requirements implemented and evidenced / applicable requirements. Incremental = covered through a control that also serves the anchor framework (${r.coverage.anchor || "none"}).`,
      "", "| Framework | Requirements | Mapped | Implemented | Covered | Coverage | Incremental | Target |", "|---|---:|---:|---:|---:|---:|---:|---:|");
    for (const f of r.coverage.frameworks) {
      lines.push(`| ${f.name} | ${f.required} | ${f.mapped} | ${f.implemented} | ${f.covered} | ${fv(f.coverage_pct, "%")} | ${f.incremental !== null ? fv(f.incremental_pct, "%") : "n/a"} | ${f.target !== null ? fmt(f.target, "%") : "-"} |`);
    }
    const o = r.coverage.overall;
    lines.push(`| **Overall** | ${o.required} |  |  | ${o.covered} | ${fv(o.coverage_pct, "%")} |  |  |`, "", "## Lifecycle", "");
    for (const i of r.lifecycle) lines.push(`${i.n}. [${i.done ? "x" : " "}] ${i.title}: ${i.detail}`);
    lines.push("", "## Mapping matrix", "", `${r.matrix.requirements} requirements. ` + Object.entries(r.matrix.by_status).map(([k, v]) => `${k}: ${v}`).join(", ") + ".", "");
    if (Object.keys(r.matrix.by_issue).length) lines.push("Issues: " + Object.entries(r.matrix.by_issue).map(([k, v]) => `${ISSUE_TEXT[k]}: ${v}`).join("; "), "");
    lines.push("## Artifacts", "");
    for (const a of r.artifacts) lines.push(`- ${a.title}: ${a.status} (${a.detail})`);
    if (r.streams.some((x) => x.requirements)) {
      lines.push("", "## ISO/IEC 42001 streams", "", "| Stream | Requirements | Mapped | Implemented | Covered |", "|---|---:|---:|---:|---:|");
      for (const x of r.streams) lines.push(`| ${x.name} | ${x.requirements} | ${fv(x.mapped_pct, "%")} | ${fv(x.implemented_pct, "%")} | ${fv(x.coverage_pct, "%")} |`);
    }
    lines.push("", "_Planning aid and working record, not an attestation of compliance. Percentages are only as good as the data entered._", "");
    return lines.join("\n");
  }

  // ---- validation --------------------------------------------------------------------------------------------------------------------------
  function validate(scope, data) {
    const errors = [], warnings = [];
    const gr = scope.grc;
    if (!gr || !Object.keys(gr).length) return { errors, warnings };
    const ix = S.index(data);
    for (const name of Object.keys(SPEC.registers)) {
      const table = gr[name] || {};
      if (typeof table !== "object" || Array.isArray(table)) { errors.push(`grc/${name}: must be an object keyed by id`); continue; }
      for (const [rid, rec] of Object.entries(table)) {
        if (rec.id !== rid) errors.push(`grc/${name}/${rid}: id does not match its key`);
        try { const tmp = { ...rec }; delete tmp.id; merge(name, null, tmp); } catch (e) { if (e instanceof GrcError) errors.push(`grc/${name}/${rid}: ${e.message}`); else throw e; }
      }
    }
    const docs = gr.documents || {}, sources = gr.evidence_sources || {};
    for (const [sid, st] of Object.entries(scope.workflow || {})) {
      for (const [ccId, cc] of Object.entries(st.common_controls || {})) {
        for (const cat of DOC_CATEGORIES) for (const docId of (cc.documents || {})[cat] || []) {
          if (!(docId in docs)) errors.push(`${sid}/${ccId}: links unknown document '${docId}'`);
          else if (docs[docId].type !== cat) errors.push(`${sid}/${ccId}: ${docId} is linked as a ${cat} but is a ${docs[docId].type}`);
        }
        for (const src of cc.evidence_sources || []) if (!(src in sources)) errors.push(`${sid}/${ccId}: links unknown evidence source '${src}'`);
      }
    }
    for (const fw of Object.keys(gr.framework_scopes || {})) if (!ix.fw[fw]) errors.push(`grc/framework_scopes: unknown framework '${fw}'`);
    const knownRoles = new Set(SPEC.roles.map((r) => r.id));
    for (const role of Object.keys(gr.roles || {})) if (!knownRoles.has(role)) errors.push(`grc/roles: unknown role '${role}'`);
    const anchor = (gr.settings || {}).anchor_framework;
    if (anchor && !ix.fw[anchor]) errors.push(`grc/settings: unknown anchor framework '${anchor}'`);
    return { errors, warnings };
  }

  const api = { SPEC, GrcError, ORG, DOC_CATEGORIES, MATRIX_COLUMNS, ISSUE_TEXT, addMonths, parseDate, settings, setSetting, records, get, add, update, remove, link,
    setScopeStatement, reviewScope, reviewMappings, setRoles, seedEvidenceSources, matrix, matrixSummary, matrixCsv, coverage, kpis, streams, lifecycle,
    artifacts, roles, report, reportMarkdown, validate };
  root.AIC = root.AIC || {};
  root.AIC.grc = api;
  if (isNode) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
