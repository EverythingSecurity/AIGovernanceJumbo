// SPDX-License-Identifier: Apache-2.0
// Scope model: an organisation's own decisions layered on the read-only dataset. A port of
// src/aicontrols/scope.py and file-compatible with it (see schema/scope.schema.json); the two
// are compared by tests/test_site_parity.py. Pure functions: no DOM, no network, no storage.
(function (root) {
  "use strict";

  const SCHEMA_VERSION = "1.0";
  const STATUSES = ["not_started", "in_progress", "implemented", "verified"];
  const DONE = ["implemented", "verified"];
  const FIELDS = ["applicable", "justification", "owner", "status", "due", "reviewed", "notes"];
  const SOA_COLUMNS = ["system", "control_id", "framework_id", "ref", "title", "domain", "c", "i", "a",
    "applicable", "justification", "status", "owner", "due", "reviewed", "updated", "evidence", "notes"];

  class ScopeError extends Error {}

  const today = () => {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  };

  function checkDate(value, name) {
    if (value === null || value === undefined || value === "") return null;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(value + "T00:00:00Z")) ||
        new Date(value + "T00:00:00Z").toISOString().slice(0, 10) !== value) {
      throw new ScopeError(`${name} must be a date like 2026-12-31, got '${value}'`);
    }
    return value;
  }

  // data: {controls, frameworks, domains, dataset_version} as loaded from data/*.json
  function index(data) {
    if (!data._ix) {
      data._ix = {
        fw: Object.fromEntries(data.frameworks.map((f) => [f.id, f])),
        dom: Object.fromEntries(data.domains.map((d) => [d.id, d])),
        ctl: Object.fromEntries(data.controls.map((c) => [c.id, c])),
      };
    }
    return data._ix;
  }

  function newScope(organization, data) {
    return { schema_version: SCHEMA_VERSION, dataset_version: data.dataset_version, organization,
      created: today(), systems: [], decisions: {} };
  }

  function system(scope, systemId) {
    const list = scope.systems;
    if (systemId === null || systemId === undefined) {
      if (list.length === 1) return list[0];
      throw new ScopeError("several systems exist; choose one");
    }
    const s = list.find((x) => x.id === systemId);
    if (!s) throw new ScopeError(`unknown system '${systemId}'`);
    return s;
  }

  function addSystem(scope, data, { id, name, description, frameworks, scoping }) {
    if (scope.systems.some((s) => s.id === id)) throw new ScopeError(`system '${id}' already exists`);
    if (!id || !/^[A-Za-z0-9_-]+$/.test(id)) throw new ScopeError("system id may contain only letters, digits, '-' and '_'");
    const ix = index(data);
    const fw = [];
    for (const f of frameworks || []) {
      if (!ix.fw[f]) throw new ScopeError(`unknown framework '${f}'`);
      if (!fw.includes(f)) fw.push(f);
    }
    if (!fw.length) throw new ScopeError("a system needs at least one framework");
    const s = { id, name: name || id, description: description || "", frameworks: fw };
    if (scoping) s.scoping = scoping;
    scope.systems.push(s);
    return s;
  }

  // Replace a system's frameworks. Decisions for controls that leave scope are dropped.
  // Returns the number of decisions dropped (call with dryRun to count first).
  function setFrameworks(scope, data, systemId, frameworks, dryRun) {
    const ix = index(data);
    const s = system(scope, systemId);
    const next = [];
    for (const f of frameworks) {
      if (!ix.fw[f]) throw new ScopeError(`unknown framework '${f}'`);
      if (!next.includes(f)) next.push(f);
    }
    if (!next.length) throw new ScopeError("a system needs at least one framework");
    const table = scope.decisions[s.id] || {};
    const drop = Object.keys(table).filter((cid) => !next.includes(ix.ctl[cid]?.framework_id));
    if (!dryRun) {
      for (const cid of drop) delete table[cid];
      s.frameworks = next;
    }
    return drop.length;
  }

  function removeSystem(scope, systemId) {
    const s = system(scope, systemId);
    scope.systems = scope.systems.filter((x) => x !== s);
    delete scope.decisions[s.id];
    if (scope.workflow) delete scope.workflow[s.id];  // workflow state (aicontrols workflow) belongs to the system
  }

  function inScope(scope, data, systemId) {
    const fw = new Set(system(scope, systemId).frameworks);
    return data.controls.filter((c) => fw.has(c.framework_id) && c.kind === "control");
  }

  function decision(scope, systemId, controlId) {
    const stored = (scope.decisions[systemId] || {})[controlId] || {};
    return Object.assign({ applicable: true, justification: "", owner: null, status: "not_started",
      due: null, reviewed: null, updated: null, evidence: [], notes: "" }, stored);
  }

  // Apply changes to the given control ids. `evidence` is appended, not replaced, unless
  // options.replaceEvidence is set (the browser editor shows the whole list).
  function setDecisions(scope, data, systemId, controlIds, changes, options) {
    const opts = options || {};
    const sid = system(scope, systemId).id;
    const scopeIds = new Set(inScope(scope, data, sid).map((c) => c.id));
    for (const cid of controlIds) if (!scopeIds.has(cid)) throw new ScopeError(`${cid} is not in scope for this system`);
    if (!controlIds.length) throw new ScopeError("nothing selected");
    const ch = Object.assign({}, changes);
    const unknown = Object.keys(ch).filter((k) => !FIELDS.includes(k) && k !== "evidence");
    if (unknown.length) throw new ScopeError(`unknown fields: ${unknown.sort().join(", ")}`);
    if (ch.status !== undefined && ch.status !== null && !STATUSES.includes(ch.status)) {
      throw new ScopeError(`status must be one of ${STATUSES.join(", ")}`);
    }
    for (const k of ["due", "reviewed"]) if (k in ch) ch[k] = checkDate(ch[k], k);
    if (ch.applicable === false && !String(ch.justification || "").trim()) {
      const missing = controlIds.filter((cid) => !String(decision(scope, sid, cid).justification).trim());
      if (missing.length) throw new ScopeError(`marking a control not applicable needs a justification (missing for ${missing.length} control(s), e.g. ${missing[0]})`);
    }
    const table = (scope.decisions[sid] = scope.decisions[sid] || {});
    for (const cid of controlIds) {
      const rec = (table[cid] = table[cid] || {});
      for (const [k, v] of Object.entries(ch)) {
        if (k === "evidence") {
          if (opts.replaceEvidence) rec.evidence = (v || []).slice();
          else { rec.evidence = rec.evidence || []; for (const item of v || []) if (!rec.evidence.includes(item)) rec.evidence.push(item); }
        } else if (v !== null && v !== undefined) rec[k] = v;
        else if (opts.allowClear) rec[k] = k === "owner" || k === "due" || k === "reviewed" ? null : rec[k];
      }
      rec.updated = today();
    }
    return controlIds.length;
  }

  const round1 = (x) => Math.round(x * 10) / 10;

  function tally(items) {
    const t = { total: items.length, applicable: 0, not_applicable: 0, not_started: 0, in_progress: 0, implemented: 0, verified: 0 };
    for (const [, d] of items) {
      if (!d.applicable) { t.not_applicable++; continue; }
      t.applicable++;
      t[d.status]++;
    }
    const done = t.implemented + t.verified;
    t.percent = t.applicable ? round1((100 * done) / t.applicable) : null;
    return t;
  }

  function rows(scope, data, systemId) {
    const sid = system(scope, systemId).id;
    return inScope(scope, data, sid).map((c) => [c, decision(scope, sid, c.id)]);
  }

  function status(scope, data, systemId, by) {
    const ix = index(data);
    const groups = {};
    for (const [c, d] of rows(scope, data, systemId)) {
      const key = by === "domain" ? c.domain_id : c.framework_id;
      (groups[key] = groups[key] || []).push([c, d]);
    }
    return Object.entries(groups).map(([key, items]) => ({
      key, label: by === "domain" ? ix.dom[key].name : ix.fw[key].name, ...tally(items),
    })).sort((a, b) => (a.label.toLowerCase() < b.label.toLowerCase() ? -1 : 1));
  }

  const overall = (scope, data, systemId) => tally(rows(scope, data, systemId));

  function plan(scope, data, systemId, todayStr) {
    const ix = index(data);
    const now = todayStr || today();
    const groups = {};
    for (const [c, d] of rows(scope, data, systemId)) (groups[c.domain_id] = groups[c.domain_id] || []).push([c, d]);
    const out = Object.entries(groups).map(([did, items]) => {
      const owners = [...new Set(items.map(([, d]) => d.owner).filter(Boolean))].sort();
      const dues = items.filter(([, d]) => d.applicable && !DONE.includes(d.status) && d.due).map(([, d]) => d.due).sort();
      return { domain_id: did, domain: ix.dom[did].name,
        frameworks: new Set(items.map(([c]) => c.framework_id)).size, owners,
        next_due: dues[0] || null, overdue: dues.filter((x) => x < now).length, ...tally(items) };
    });
    return out.sort((a, b) => (b.frameworks - a.frameworks) || (b.total - a.total) || (a.domain < b.domain ? -1 : a.domain > b.domain ? 1 : 0));
  }

  // In-scope controls in other frameworks, same domain, applicable and not done. Prompts a
  // human review only; nothing is ever updated automatically.
  function relatedOpen(scope, data, systemId, controlId) {
    const ix = index(data);
    const sid = system(scope, systemId).id;
    const c = ix.ctl[controlId];
    const ids = new Set(inScope(scope, data, sid).map((x) => x.id));
    return ix.dom[c.domain_id].control_ids.map((id) => ix.ctl[id]).filter((r) => {
      if (r.framework_id === c.framework_id || !ids.has(r.id)) return false;
      const d = decision(scope, sid, r.id);
      return d.applicable && !DONE.includes(d.status);
    });
  }

  function soaRows(scope, data, systemId) {
    const ix = index(data);
    const sid = system(scope, systemId).id;
    return rows(scope, data, sid).map(([c, d]) => ({
      system: sid, control_id: c.id, framework_id: c.framework_id, ref: c.ref, title: c.title,
      domain: ix.dom[c.domain_id].name, c: Number(c.cia.c), i: Number(c.cia.i), a: Number(c.cia.a),
      applicable: d.applicable ? "yes" : "no", justification: d.justification, status: d.status,
      owner: d.owner || "", due: d.due || "", reviewed: d.reviewed || "", updated: d.updated || "",
      evidence: d.evidence.join("; "), notes: d.notes,
    }));
  }

  // Neutralise spreadsheet formulas in cells that start with = + - @ (CSV injection).
  const csvSafe = (v) => { const s = String(v); return /^[=+\-@\t\r]/.test(s) ? "'" + s : s; };
  const csvCell = (v) => { const s = csvSafe(v); return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };

  function soaCsv(scope, data, systemId) {
    const lines = [SOA_COLUMNS.join(",")];
    for (const r of soaRows(scope, data, systemId)) lines.push(SOA_COLUMNS.map((k) => csvCell(r[k])).join(","));
    return lines.join("\r\n") + "\r\n";
  }

  const md = (v) => String(v === null || v === undefined ? "" : v).replace(/\|/g, "\\|").replace(/\n/g, " ").trim();

  function planMarkdown(scope, data, systemId, rowsIn, total) {
    const ix = index(data);
    const s = system(scope, systemId);
    const lines = [`# Governance plan: ${md(s.name)}`, "",
      `Organisation: ${md(scope.organization)}  `,
      `Frameworks: ${s.frameworks.map((f) => ix.fw[f].name).join(", ")}  `,
      `Workstreams shown: ${rowsIn.length} of ${total} (one per domain, most-shared first)`, "",
      "| Workstream (domain) | Frameworks | Controls | Done | Next due | Overdue | Owner |",
      "|---|---:|---:|---:|---|---:|---|"];
    for (const p of rowsIn) {
      const done = p.percent === null ? "n/a" : `${p.percent.toFixed(1)}%`;
      lines.push(`| ${md(p.domain)} | ${p.frameworks} | ${p.total} | ${done} | ${p.next_due || ""} | ${p.overdue || ""} | ${md(p.owners.join(", ") || "-")} |`);
    }
    lines.push("", "_Done = implemented + verified, as a share of applicable controls. Planning aid, not a compliance verdict._", "");
    return lines.join("\n");
  }

  function soaMarkdown(scope, data, systemId) {
    const s = system(scope, systemId);
    const lines = [`# Statement of applicability (draft): ${md(s.name)}`, "", `Organisation: ${md(scope.organization)}`, "",
      "| Control | Title | Domain | CIA | Applicable | Status | Owner | Due | Evidence | Justification / notes |",
      "|---|---|---|---|---|---|---|---|---|---|"];
    for (const r of soaRows(scope, data, systemId)) {
      const cia = (r.c ? "C" : "-") + (r.i ? "I" : "-") + (r.a ? "A" : "-");
      const note = [r.justification, r.notes].filter(Boolean).join("; ");
      lines.push("| " + [r.control_id, r.title, r.domain, cia, r.applicable, r.status, r.owner, r.due, r.evidence, note].map(md).join(" | ") + " |");
    }
    lines.push("", "_Draft for review and approval; not a compliance verdict._", "");
    return lines.join("\n");
  }

  // Returns {errors, warnings}; errors mean the file is inconsistent.
  function validate(scope, data) {
    const errors = [], warnings = [];
    const ix = index(data);
    if (!scope || typeof scope !== "object" || Array.isArray(scope)) return { errors: ["not a scope file (expected a JSON object)"], warnings };
    // "1.1" files carry the workflow layer (aicontrols workflow); the browser keeps those sections intact.
    if (scope.schema_version !== SCHEMA_VERSION && scope.schema_version !== "1.1") {
      errors.push(`schema_version must be '${SCHEMA_VERSION}' (or '1.1' when the workflow layer is used)`);
    }
    if (!Array.isArray(scope.systems)) errors.push("systems must be a list");
    if (!scope.decisions || typeof scope.decisions !== "object" || Array.isArray(scope.decisions)) errors.push("decisions must be an object");
    if (errors.length) return { errors, warnings };
    if (scope.dataset_version !== data.dataset_version) {
      warnings.push(`scope was created against dataset ${scope.dataset_version}, this site has ${data.dataset_version}; re-check decisions`);
    }
    const ids = scope.systems.map((s) => s.id);
    if (new Set(ids).size !== ids.length) errors.push("duplicate system ids");
    for (const s of scope.systems) for (const f of s.frameworks || []) if (!ix.fw[f]) errors.push(`system ${s.id}: unknown framework '${f}'`);
    for (const [sid, table] of Object.entries(scope.decisions)) {
      if (!ids.includes(sid)) { errors.push(`decisions for unknown system '${sid}'`); continue; }
      const sys = scope.systems.find((s) => s.id === sid);
      const fw = new Set(sys.frameworks || []);
      for (const [cid, rec] of Object.entries(table)) {
        const where = `${sid}/${cid}`;
        const c = ix.ctl[cid];
        if (!c) { errors.push(`${where}: unknown control id`); continue; }
        if (!fw.has(c.framework_id) || c.kind !== "control") errors.push(`${where}: control's framework is not selected for this system`);
        const st = rec.status === undefined ? "not_started" : rec.status;
        if (!STATUSES.includes(st)) errors.push(`${where}: invalid status '${rec.status}'`);
        if (rec.applicable === false && !String(rec.justification || "").trim()) errors.push(`${where}: not applicable without a justification`);
        for (const k of ["due", "reviewed", "updated"]) {
          try { checkDate(rec[k], k); } catch (e) { errors.push(`${where}: ${e.message}`); }
        }
        if (rec.applicable === false && st !== "not_started") warnings.push(`${where}: marked not applicable but has status ${st}`);
      }
    }
    return { errors, warnings };
  }

  const api = { SCHEMA_VERSION, STATUSES, DONE, FIELDS, SOA_COLUMNS, ScopeError, today, index, newScope, system, addSystem,
    setFrameworks, removeSystem, inScope, decision, setDecisions, tally, rows, status, overall, plan, relatedOpen,
    soaRows, soaCsv, planMarkdown, soaMarkdown, validate };
  root.AIC = root.AIC || {};
  root.AIC.scope = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
