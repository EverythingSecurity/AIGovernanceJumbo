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


  // ---- spreadsheet template and import (twin of src/aicontrols/spreadsheet.py) ------------------------
  const TEMPLATE_VERSION = "1";
  const ALIASES = {
    control_id: ["control_id", "control", "id", "control_id"], system: ["system", "system_id"],
    applicable: ["applicable", "applies", "applicable_(soa)"], justification: ["justification", "reason"], status: ["status"],
    owner: ["owner"], due: ["due", "due_date"], reviewed: ["reviewed", "last_reviewed"], evidence: ["evidence"],
    notes: ["notes", "note", "notes_/_gap"],
  };
  const YES = ["yes", "y", "true", "1"], NO = ["no", "n", "false", "0"];

  function firstDataLine(text) {
    for (const line of text.split(/\r\n|\r|\n/)) {
      const t = line.trim();
      if (t && !t.startsWith("#") && !t.startsWith('"#')) return line;
    }
    return "";
  }
  function detectDelimiter(text) {
    let commas = 0, semis = 0, quoted = false;
    for (const ch of firstDataLine(text)) {
      if (ch === '"') quoted = !quoted;
      else if (!quoted && ch === ",") commas++;
      else if (!quoted && ch === ";") semis++;
    }
    return semis > commas ? ";" : ",";
  }
  // CSV into records: a BOM, quoted fields with embedded newlines and "" escapes are handled.
  function parseCsv(text, delimiter) {
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    const delim = delimiter || detectDelimiter(text);
    const rows = [];
    let row = [], field = [], quoted = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (quoted) {
        if (ch === '"') {
          if (text[i + 1] === '"') { field.push('"'); i++; } else quoted = false;
        } else field.push(ch);
      } else if (ch === '"' && !field.length) quoted = true;
      else if (ch === delim) { row.push(field.join("")); field = []; }
      else if (ch === "\r" || ch === "\n") {
        if (ch === "\r" && text[i + 1] === "\n") i++;
        row.push(field.join("")); rows.push(row); row = []; field = [];
      } else field.push(ch);
    }
    if (field.length || row.length) { row.push(field.join("")); rows.push(row); }
    return rows.filter((r) => r.some((c) => c.trim()));
  }
  const csvLine = (cells) => Array.from(cells, csvCell).join(",");
  const unsafe = (cell) => (cell.length > 1 && cell[0] === "'" && "=+-@".includes(cell[1]) ? cell.slice(1) : cell);

  function templateComments(organisation, systemName) {
    return [
      `# aicontrols decisions template v${TEMPLATE_VERSION}. Fill in the decision columns, save as CSV (UTF-8) and import it on the My scope tab, or run: aicontrols scope import-csv`,
      `# organisation: ${organisation}`, `# system-name: ${systemName}`,
      "# applicable: yes or no (a no needs a justification). status: not_started, in_progress, implemented or verified. due and reviewed: YYYY-MM-DD (format those columns as text so Excel keeps the format).",
      "# evidence: separate several references with a semicolon. A blank cell leaves that value unchanged. Do not edit the first columns (system to domain, c, i, a).",
    ];
  }
  // A fill-in spreadsheet for the chosen frameworks; with a scope that has this system, current decisions are pre-filled.
  function templateCsv(data, frameworks, organisation, systemId, systemName, scope) {
    const ix = index(data);
    const fw = [];
    for (const f of frameworks) {
      if (!ix.fw[f]) throw new ScopeError(`unknown framework '${f}'`);
      if (!fw.includes(f)) fw.push(f);
    }
    if (!fw.length) throw new ScopeError("choose at least one framework for the template");
    if (!/^[A-Za-z0-9_-]+$/.test(systemId || "")) throw new ScopeError("system id may contain only letters, digits, '-' and '_'");
    const lines = [templateComments(organisation, systemName).map((c) => csvLine([c])).join("\r\n"), csvLine(SOA_COLUMNS)];
    const known = Boolean(scope) && scope.systems.some((s) => s.id === systemId);
    for (const c of data.controls) {
      if (!fw.includes(c.framework_id) || c.kind !== "control") continue;
      const d = known ? decision(scope, systemId, c.id) : { applicable: true, justification: "", owner: null, status: "not_started", due: null, reviewed: null, updated: null, evidence: [], notes: "" };
      const row = { system: systemId, control_id: c.id, framework_id: c.framework_id, ref: c.ref, title: c.title, domain: ix.dom[c.domain_id].name,
        c: Number(c.cia.c), i: Number(c.cia.i), a: Number(c.cia.a), applicable: d.applicable ? "yes" : "no", justification: d.justification,
        status: d.status, owner: d.owner || "", due: d.due || "", reviewed: d.reviewed || "", updated: d.updated || "",
        evidence: d.evidence.join("; "), notes: d.notes };
      lines.push(csvLine(SOA_COLUMNS.map((k) => row[k])));
    }
    return lines.join("\r\n") + "\r\n";
  }

  const normHeader = (c) => c.trim().toLowerCase().replace(/\s+/g, "_");
  function validDateStr(v) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
    const ms = Date.parse(v + "T00:00:00Z");
    return !Number.isNaN(ms) && new Date(ms).toISOString().slice(0, 10) === v;
  }
  function csvMeta(rows) {
    const meta = {};
    for (const r of rows) {
      const m = /^#\s*([a-z][a-z-]*)\s*:\s*(.*)$/.exec(r[0].trim());
      if (m && !(m[1] in meta)) meta[m[1]] = m[2].trim();
    }
    return meta;
  }
  // Apply a decisions spreadsheet. All or nothing: on any error the input scope is returned untouched
  // and `errors` lists every problem with its row. On success `scope` is the updated copy to keep.
  function applyDecisionsCsv(scope, data, text, options) {
    const opts = options || {};
    const ix = index(data);
    const records = parseCsv(text);
    const meta = csvMeta(records);
    const dataRows = records.filter((r) => !r[0].trimStart().startsWith("#"));
    const result = { applied: 0, skipped: 0, errors: [], warnings: [], system: null, created_system: false, scope };
    const err = result.errors;
    if (!dataRows.length) { err.push({ row: 0, message: "the file has no header row" }); return result; }
    const header = dataRows[0].map(normHeader);
    const col = {};
    for (const [name, aliases] of Object.entries(ALIASES)) for (const a of aliases) if (header.includes(a)) { col[name] = header.indexOf(a); break; }
    if (!("control_id" in col)) { err.push({ row: 1, message: "no control_id column (found: " + header.filter(Boolean).join(", ") + ")" }); return result; }
    const cell = (r, name) => (name in col && col[name] < r.length ? unsafe(r[col[name]].trim()) : "");

    const inFile = [...new Set(dataRows.slice(1).map((r) => cell(r, "system")).filter(Boolean))].sort();
    if (inFile.length > 1) { err.push({ row: 0, message: "the file mixes several systems: " + inFile.join(", ") }); return result; }
    let sid = opts.systemId || (inFile.length ? inFile[0] : null);
    if (!sid && scope && scope.systems.length === 1) sid = scope.systems[0].id;
    if (!sid) { err.push({ row: 0, message: "cannot tell which system to import into: fill the system column or name one" }); return result; }
    if (!/^[A-Za-z0-9_-]+$/.test(sid)) { err.push({ row: 0, message: "system id may contain only letters, digits, '-' and '_'" }); return result; }
    result.system = sid;
    const existing = scope ? scope.systems.find((s) => s.id === sid) : undefined;
    if (!existing && opts.createSystem === false) { err.push({ row: 0, message: `unknown system '${sid}'` }); return result; }
    const allowed = existing ? new Set(existing.frameworks) : null;

    const changesBy = new Map(), seenRows = {};
    const stored0 = scope ? (scope.decisions[sid] || {}) : {};
    dataRows.slice(1).forEach((r, idx) => {
      const n = idx + 2;
      const cid = cell(r, "control_id");
      if (!cid) return;
      const c = ix.ctl[cid];
      if (!c) { err.push({ row: n, message: `unknown control id '${cid}'` }); return; }
      if (c.kind !== "control") { err.push({ row: n, message: `${cid} is not a control` }); return; }
      if (allowed && !allowed.has(c.framework_id)) { err.push({ row: n, message: `${cid}: its framework is not selected for system '${sid}'` }); return; }
      const changes = {};
      const rawApp = cell(r, "applicable").toLowerCase();
      if (rawApp) {
        if (YES.includes(rawApp)) changes.applicable = true;
        else if (NO.includes(rawApp)) changes.applicable = false;
        else err.push({ row: n, message: `${cid}: applicable must be yes or no, got '${cell(r, "applicable")}'` });
      }
      const rawStatus = cell(r, "status").toLowerCase().replace(/\s+/g, "_");
      if (rawStatus) {
        if (STATUSES.includes(rawStatus)) changes.status = rawStatus;
        else err.push({ row: n, message: `${cid}: status must be one of ${STATUSES.join(", ")}, got '${cell(r, "status")}'` });
      }
      for (const name of ["due", "reviewed"]) {
        const v = cell(r, name);
        if (v) {
          if (validDateStr(v)) changes[name] = v;
          else err.push({ row: n, message: `${cid}: ${name} must be a date like 2026-12-31, got '${v}' (format the column as text so the spreadsheet keeps it)` });
        }
      }
      for (const name of ["justification", "owner", "notes"]) { const v = cell(r, name); if (v) changes[name] = v; }
      const ev = cell(r, "evidence");
      if (ev) changes.evidence = ev.split(";").map((x) => x.trim()).filter(Boolean);
      const justification = changes.justification || String((stored0[cid] || {}).justification || "").trim();
      if (changes.applicable === false && !justification) err.push({ row: n, message: `${cid}: not applicable needs a justification` });
      if (changesBy.has(cid)) result.warnings.push(`row ${n}: ${cid} appears more than once; the last row wins (first seen in row ${seenRows[cid]})`);
      changesBy.set(cid, changes);
      seenRows[cid] = n;
    });
    if (err.length) return result;

    const work = scope ? JSON.parse(JSON.stringify(scope)) : newScope("", data);
    if (!existing) {
      const fws = [];
      for (const cid of changesBy.keys()) if (!fws.includes(ix.ctl[cid].framework_id)) fws.push(ix.ctl[cid].framework_id);
      if (!fws.length) { err.push({ row: 0, message: "no control rows to import" }); return result; }
      if (!work.systems.length) work.organization = opts.organisation || work.organization || meta.organisation || "My organisation";
      addSystem(work, data, { id: sid, name: meta["system-name"] || sid, description: "", frameworks: fws });
      result.created_system = true;
    }
    const stored = work.decisions[sid] || {};
    const defaults = { applicable: true, status: "not_started" };
    for (const [cid, changes] of changesBy) {
      const plain = Object.fromEntries(Object.entries(changes).filter(([k]) => k !== "evidence"));
      const allDefault = Object.entries(plain).every(([k, v]) => defaults[k] === v);
      if (!(cid in stored) && allDefault && !("evidence" in changes)) { result.skipped++; continue; }
      if (!Object.keys(plain).length && !("evidence" in changes)) { result.skipped++; continue; }
      setDecisions(work, data, sid, [cid], plain);
      if ("evidence" in changes) work.decisions[sid][cid].evidence = changes.evidence;
      result.applied++;
    }
    result.scope = work;
    return result;
  }

  const api = { SCHEMA_VERSION, STATUSES, DONE, FIELDS, SOA_COLUMNS, ScopeError, today, index, newScope, system, addSystem,
    setFrameworks, removeSystem, inScope, decision, setDecisions, tally, rows, status, overall, plan, relatedOpen,
    soaRows, soaCsv, csvCell, planMarkdown, soaMarkdown, validate,
    parseCsv, detectDelimiter, csvLine, templateCsv, applyDecisionsCsv };
  root.AIC = root.AIC || {};
  root.AIC.scope = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
