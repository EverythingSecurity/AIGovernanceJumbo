// SPDX-License-Identifier: Apache-2.0
// Governance workflow engine: a faithful port of src/aicontrols/workflow.py, working on the same
// scope file. Python and this file are run side by side on scripted scenarios by
// tests/test_site_parity.py, which compares the resulting files byte for byte (hash chain
// included), so change them together. Pure functions: no DOM, no network, no storage.
//
// Same honest limits as the Python side: roles and actor names are labels, the audit trail is
// tamper-evident not immutable, and results arrive through files (no live connectors).
(function (root) {
  "use strict";
  const S = typeof module !== "undefined" && module.exports ? require("./scope.js") : root.AIC.scope;

  // The stage model, identical to src/aicontrols/workflow_spec.json (a test keeps them in step).
  const SPEC = {
    title: "GRC_Scoping_and_Control_Management_Layer", version: "2.0.0",
    description: "Workflow layer specification for scoping, harmonizing, and managing controls across multiple pre-loaded frameworks.",
    workflow: { id: "control-scoping-management-layer-v2", initialStage: "FRAMEWORK_SCOPING", stages: [
      { id: "FRAMEWORK_SCOPING", name: "Framework Scoping & Profile Definition", assignedRole: "SCOPING_COMPLIANCE_LEAD",
        actions: ["DEFINE_ORGANIZATIONAL_PROFILE_BOUNDARIES", "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS", "ESTABLISH_CURRENT_VS_TARGET_PROFILES"],
        nextStage: "CONTROL_HARMONIZATION" },
      { id: "CONTROL_HARMONIZATION", name: "Control Harmonization & One-to-Many Mapping", assignedRole: "COMPLIANCE_ARCHITECT",
        actions: ["MAP_PLATFORM_FRAMEWORKS_TO_COMMON_CONTROLS", "DEDUPLICATE_OVERLAPPING_REQUIREMENTS", "IDENTIFY_UNMAPPED_FRAMEWORK_GAPS"],
        nextStage: "CONTROL_TAILORING" },
      { id: "CONTROL_TAILORING", name: "Control Tailoring & Ownership Assignment", assignedRole: "FIRST_LINE_CONTROL_OWNER",
        actions: ["CUSTOMIZE_CONTROL_IMPLEMENTATION_PARAMETERS", "ASSIGN_OPERATIONAL_OWNER_AND_REVIEW_FREQUENCY", "CONFIGURE_EVIDENCE_REQUIREMENTS_AND_TEST_RULES"],
        nextStage: "CONTINUOUS_MONITORING" },
      { id: "CONTINUOUS_MONITORING", name: "Continuous Monitoring & Evidence Ingestion", assignedRole: "AUTOMATED_CCM_ENGINE",
        actions: ["INGEST_AUTOMATED_EVIDENCE_FEEDS", "EVALUATE_KCI_KRI_THRESHOLDS", "CALCULATE_REALTIME_CONTROL_EFFECTIVENESS"],
        nextStage: "EXCEPTION_GOVERNANCE" },
      { id: "EXCEPTION_GOVERNANCE", name: "Exception & Deviation Governance", assignedRole: "SECOND_LINE_RISK_MANAGER",
        actions: ["PROCESS_CONTROL_EXCEPTION_REQUESTS", "ASSESS_RISK_EXPOSURE_AGAINST_TOLERANCE", "ENFORCE_EXECUTIVE_APPROVAL_AND_EXPIRATION_DATES"],
        nextStage: "TARGET_GAP_ANALYSIS" },
      { id: "TARGET_GAP_ANALYSIS", name: "Assurance & Target Gap Analysis", assignedRole: "THIRD_LINE_AUDITOR", isFinal: true,
        actions: ["MEASURE_PROGRESS_TOWARD_TARGET_PROFILE", "PRESERVE_IMMUTABLE_AUDIT_TRAIL_EVIDENCE", "GENERATE_REALTIME_REGULATORY_DASHBOARDS"] },
    ] },
  };
  const STAGES = Object.fromEntries(SPEC.workflow.stages.map((s) => [s.id, s]));
  const ORDER = SPEC.workflow.stages.map((s) => s.id);

  const ROLE_EXECUTIVE = "EXECUTIVE_APPROVER", ROLE_SECOND_LINE = "SECOND_LINE_RISK_MANAGER", ROLE_CCM = "AUTOMATED_CCM_ENGINE";
  const RATINGS = ["low", "medium", "high", "critical"];
  const RANK = { not_started: 0, in_progress: 1, implemented: 2, verified: 3 };
  const FREQUENCIES = { daily: 1, weekly: 7, monthly: 31, quarterly: 92, annual: 366 };
  const TEST_TYPES = ["manual", "automated", "rcsa"];
  const EXCEPTION_TYPES = ["waiver", "delayed_remediation", "deviation"];
  const RESULTS = ["pass", "fail", "error"];
  const RISK_APPETITES = ["low", "moderate", "high"];
  const OPS = [">", ">=", "<", "<="];
  const EXCEPTION_OPEN = ["requested", "assessed"];
  const ATTESTED = ["RATIONALIZE_NON_APPLICABLE_OBLIGATIONS", "DEDUPLICATE_OVERLAPPING_REQUIREMENTS"];
  const DEFAULT_POLICY = {
    separation_of_duties: true, executive_approval_from: "medium",
    exception_max_days: { low: 365, medium: 180, high: 90, critical: 30 },
    reassess_warning_days: 14, effectiveness_window: 5, effective_threshold: 0.9, partial_threshold: 0.6, stale_factor: 1.5,
  };
  const SCHEMA_VERSION = "1.1";
  const GENESIS = "0".repeat(64);

  class WorkflowError extends S.ScopeError {}

  // ---- clock (replaceable for tests) ---------------------------------------------------
  let clock = () => new Date();
  const setClock = (fn) => { clock = fn || (() => new Date()); };
  const nowDate = () => { const d = clock(); return new Date(Math.floor(d.getTime() / 1000) * 1000); };
  const stamp = () => nowDate().toISOString().replace(/\.\d{3}Z$/, "Z");
  const todayStr = () => nowDate().toISOString().slice(0, 10);
  const DAY = 86400000;
  const dateMs = (s) => Date.parse(s + "T00:00:00Z");
  const addDays = (s, n) => new Date(dateMs(s) + n * DAY).toISOString().slice(0, 10);
  const norm = (n) => String(n || "").trim().toLowerCase();
  function validDate(s) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
    const ms = dateMs(s);
    return !Number.isNaN(ms) && new Date(ms).toISOString().slice(0, 10) === s;
  }

  function parseDt(value) {
    const text = String(value === undefined || value === null ? "" : value).trim();
    const m = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$/.exec(text);
    const bad = () => new WorkflowError(`not a date/time: ${JSON.stringify(value)} (use 2026-10-27 or 2026-10-27T09:30:00Z)`.replace(/"/g, "'"));
    if (!m) throw bad();
    const time = m[2] ? (m[2].length === 5 ? m[2] + ":00" : m[2]) : "00:00:00";
    const ms = Date.parse(`${m[1]}T${time}${m[3] || "Z"}`);
    if (Number.isNaN(ms) || new Date(dateMs(m[1])).toISOString().slice(0, 10) !== m[1]) throw bad();
    return new Date(Math.floor(ms / 1000) * 1000);
  }
  const iso = (d) => d.toISOString().replace(/\.\d{3}Z$/, "Z");

  // ---- SHA-256 (synchronous, so verification works the same in the browser and in Node) ----
  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);
  function sha256(text) {
    const bytes = new TextEncoder().encode(text);
    const bitLen = bytes.length * 8;
    const padded = new Uint8Array(((bytes.length + 9 + 63) >> 6) << 6);
    padded.set(bytes); padded[bytes.length] = 0x80;
    const dv = new DataView(padded.buffer);
    dv.setUint32(padded.length - 8, Math.floor(bitLen / 0x100000000)); dv.setUint32(padded.length - 4, bitLen >>> 0);
    const h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    const w = new Uint32Array(64);
    const rotr = (x, n) => (x >>> n) | (x << (32 - n));
    for (let off = 0; off < padded.length; off += 64) {
      for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4);
      for (let i = 16; i < 64; i++) {
        const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
      }
      let [a, b, c, d, e, f, g, hh] = h;
      for (let i = 0; i < 64; i++) {
        const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
        const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
        hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }
    return Array.from(h, (x) => x.toString(16).padStart(8, "0")).join("");
  }

  // Canonical JSON identical to Python's json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":")).
  // Audit details never contain floats (5.0 would serialise differently in the two languages).
  function canon(v) {
    if (v === null) return "null";
    if (typeof v === "string") return JSON.stringify(v);
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "number") {
      if (!Number.isInteger(v)) throw new Error("audit details must not contain non-integer numbers");
      return String(v);
    }
    if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
    return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}";
  }
  const CHAIN_FIELDS = ["seq", "at", "actor", "role", "action", "system", "target", "details", "prev"];
  function eventHash(ev) {
    const body = {};
    for (const k of CHAIN_FIELDS) body[k] = ev[k] === undefined ? null : ev[k];
    return sha256(canon(body));
  }
  function verifyAudit(events) {
    const problems = [];
    let prev = GENESIS;
    events.forEach((ev, idx) => {
      const i = idx + 1;
      if (ev.seq !== i) problems.push(`event ${i}: sequence number is ${JSON.stringify(ev.seq)}`);
      if (ev.prev !== prev) problems.push(`event ${i}: does not link to the previous event (history edited or removed?)`);
      if (ev.hash !== eventHash(ev)) problems.push(`event ${i}: content does not match its hash (event edited)`);
      prev = ev.hash;
    });
    return { ok: problems.length === 0, problems };
  }

  // ---- state access ------------------------------------------------------------------------
  const all = (scope) => (scope.workflow = scope.workflow || {});
  const auditLog = (scope) => (scope.audit = scope.audit || []);
  const sidOf = (scope, systemId) => S.system(scope, systemId).id;
  const enabled = (scope, systemId) => sidOf(scope, systemId) in all(scope);
  function state(scope, systemId) {
    const sid = sidOf(scope, systemId);
    if (!(sid in all(scope))) throw new WorkflowError(`workflow is not enabled for '${sid}'; run: aicontrols workflow init`);
    return all(scope)[sid];
  }
  function policy(scope, systemId) {
    const merged = JSON.parse(JSON.stringify(DEFAULT_POLICY));
    const stored = state(scope, systemId).policy || {};
    for (const [k, v] of Object.entries(stored)) {
      if (v && typeof v === "object" && !Array.isArray(v) && merged[k] && typeof merged[k] === "object") Object.assign(merged[k], v);
      else merged[k] = v;
    }
    return merged;
  }

  function audit(scope, sid, actor, role, action, target, details) {
    const log = auditLog(scope);
    const ev = { seq: log.length + 1, at: stamp(), actor, role, action, system: sid, target, details: details || {},
      prev: log.length ? log[log.length - 1].hash : GENESIS };
    ev.hash = eventHash(ev);
    log.push(ev);
    return ev;
  }
  function checkActor(actor) {
    const a = String(actor || "").trim();
    if (!a) throw new WorkflowError("an actor name is required (--by)");
    return a;
  }
  function sod(scope, sid, first, second, what) {
    if (policy(scope, sid).separation_of_duties && first && norm(first) === norm(second)) {
      throw new WorkflowError(`separation of duties: ${what} must be different people (both are '${second}'). Disable with: workflow policy set separation_of_duties=false`);
    }
  }
  const applicable = (scope, data, sid) => S.rows(scope, data, sid).filter(([, d]) => d.applicable);
  function rec(scope, sid, controlId) {
    const table = (scope.decisions[sid] = scope.decisions[sid] || {});
    const r = (table[controlId] = table[controlId] || {});
    r.updated = todayStr();
    return r;
  }
  function pick(scope, data, sid, ids, domain, framework) {
    const base = S.inScope(scope, data, sid);
    const byId = Object.fromEntries(base.map((c) => [c.id, c]));
    const chosen = {};
    const ix = S.index(data);
    for (const cid of ids || []) {
      if (!byId[cid]) throw new WorkflowError(ix.ctl[cid] ? `${cid} is not in scope for this system (its framework is not selected)` : `unknown control id '${cid}'`);
      chosen[cid] = byId[cid];
    }
    if (domain || framework) {
      if (domain && !ix.dom[domain]) throw new WorkflowError(`unknown or ambiguous domain '${domain}'`);
      if (framework && !ix.fw[framework]) throw new WorkflowError(`unknown framework '${framework}'`);
      for (const c of base) if ((!domain || c.domain_id === domain) && (!framework || c.framework_id === framework)) chosen[c.id] = c;
    }
    if (!Object.keys(chosen).length) throw new WorkflowError("nothing selected: give control ids, --domain or --framework");
    return Object.values(chosen);
  }

  // ---- enable ---------------------------------------------------------------------------------
  function enable(scope, systemId, actor) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    if (sid in all(scope)) throw new WorkflowError(`workflow is already enabled for '${sid}'`);
    all(scope)[sid] = {
      spec_version: SPEC.version, cycle: 1, stage: SPEC.workflow.initialStage, entered: stamp(), stage_log: [],
      attestations: {}, profile: {}, common_controls: {}, measurements: [], escalations: [], exceptions: {}, policy: {},
      markers: { last_ingest_at: null, ccm_evaluated_at: null, gap_run_at: null, audit_verified_at: null, report_at: null },
      completed_cycles: [],
    };
    scope.schema_version = SCHEMA_VERSION;
    audit(scope, sid, actor, STAGES[ORDER[0]].assignedRole, "WORKFLOW_ENABLED", sid, { spec: SPEC.title, spec_version: SPEC.version });
    return all(scope)[sid];
  }

  // ---- stage 1 ------------------------------------------------------------------------------------
  function setProfile(scope, systemId, actor, fields) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const prof = state(scope, sid).profile;
    const before = JSON.parse(JSON.stringify(prof));
    for (const [key, raw] of Object.entries(fields)) {
      let value = raw;
      if (value === null || value === undefined) continue;
      if (key === "risk_appetite" && !RISK_APPETITES.includes(value)) throw new WorkflowError(`risk_appetite must be one of ${RISK_APPETITES.join(", ")}`);
      if (key === "target_default" && !["implemented", "verified"].includes(value)) throw new WorkflowError("target_default must be 'implemented' or 'verified'");
      if (key === "asset_classes") value = [...new Set(value.map((v) => String(v).trim()).filter(Boolean))].sort();
      else if (["business_unit", "environment", "boundary"].includes(key)) {
        value = String(value).trim();
        if (!value) throw new WorkflowError(`${key} cannot be empty`);
      } else if (!["risk_appetite", "target_default"].includes(key)) throw new WorkflowError(`unknown profile field '${key}'`);
      prof[key] = value;
    }
    if (JSON.stringify(sortKeys(prof)) !== JSON.stringify(sortKeys(before))) {
      audit(scope, sid, actor, "SCOPING_COMPLIANCE_LEAD", "PROFILE_UPDATED", sid, { before, after: JSON.parse(JSON.stringify(prof)) });
    }
    return prof;
  }
  function sortKeys(o) {
    if (Array.isArray(o)) return o.map(sortKeys);
    if (o && typeof o === "object") return Object.fromEntries(Object.keys(o).sort().map((k) => [k, sortKeys(o[k])]));
    return o;
  }
  function setTarget(scope, data, systemId, actor, status, byDate, controls, domain, framework) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    if (!["implemented", "verified"].includes(status)) throw new WorkflowError("a target must be 'implemented' or 'verified'");
    if (byDate && !validDate(byDate)) throw new WorkflowError(`by-date must be a date like 2026-12-31, got '${byDate}'`);
    const chosen = pick(scope, data, sid, controls, domain, framework);
    for (const c of chosen) { const r = rec(scope, sid, c.id); r.target = status; if (byDate) r.target_by = byDate; }
    audit(scope, sid, actor, "SCOPING_COMPLIANCE_LEAD", "TARGET_SET", `${chosen.length} control(s)`,
      { status, by: byDate || null, domain: domain || null, framework: framework || null, controls: chosen.map((c) => c.id).slice(0, 25) });
    return chosen.length;
  }
  function targetOf(scope, sid, controlId) {
    const r = (scope.decisions[sid] || {})[controlId] || {};
    return [r.target || state(scope, sid).profile.target_default || "implemented", r.target_by || null];
  }

  // ---- stage 2: common controls -----------------------------------------------------------------------
  const ccs = (scope, sid) => state(scope, sid).common_controls;
  function cc(scope, systemId, ccId) {
    const m = ccs(scope, sidOf(scope, systemId));
    if (!m[ccId]) throw new WorkflowError(`unknown common control '${ccId}'`);
    return m[ccId];
  }
  function members(scope, sid, ccId) {
    const table = scope.decisions[sid] || {};
    return Object.keys(table).filter((cid) => table[cid].common_control === ccId).sort();
  }
  function ccAdd(scope, data, systemId, actor, title, ccId, description, domain) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const m = ccs(scope, sid);
    if (!String(title).trim()) throw new WorkflowError("a common control needs a title");
    if (!ccId) {
      let n = Object.keys(m).length + 1;
      while (`CC-${String(n).padStart(3, "0")}` in m) n++;
      ccId = `CC-${String(n).padStart(3, "0")}`;
    } else if (!/^[A-Za-z][A-Za-z0-9_-]*$/.test(ccId)) {
      throw new WorkflowError("a common control id starts with a letter and uses letters, digits, '-' and '_'");
    }
    if (ccId in m) throw new WorkflowError(`common control '${ccId}' already exists`);
    let dom = null;
    if (domain) {
      if (!S.index(data).dom[domain]) throw new WorkflowError(`unknown or ambiguous domain '${domain}'`);
      dom = domain;
    }
    m[ccId] = { id: ccId, title: String(title).trim(), description: description || "", domain_id: dom, owner: null, reviewer: null,
      frequency: null, implementation: "", parameters: {}, evidence_required: [], test: { type: null, description: "" }, indicators: [], created: stamp() };
    audit(scope, sid, actor, "COMPLIANCE_ARCHITECT", "CC_ADDED", ccId, { title: String(title).trim(), domain: dom });
    return m[ccId];
  }
  function ccMap(scope, data, systemId, actor, ccId, controls, domain, framework, move) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    cc(scope, sid, ccId);
    const chosen = pick(scope, data, sid, controls, domain, framework);
    const table = scope.decisions[sid] || {};
    const mapped = [];
    for (const c of chosen) {
      if (!S.decision(scope, sid, c.id).applicable) continue;
      const current = (table[c.id] || {}).common_control;
      if (current && current !== ccId && !move) throw new WorkflowError(`${c.id} is already mapped to ${current}; use --move to remap it`);
      const r = rec(scope, sid, c.id);
      r.common_control = ccId;
      delete r.common_control_gap;
      mapped.push(c.id);
    }
    if (!mapped.length) throw new WorkflowError("no applicable controls selected (not-applicable controls are never mapped)");
    audit(scope, sid, actor, "COMPLIANCE_ARCHITECT", "CC_MAPPED", ccId, { count: mapped.length, controls: mapped.slice(0, 25), moved: Boolean(move) });
    return mapped.length;
  }
  function ccSuggest(scope, data, systemId, minFrameworks) {
    const sid = sidOf(scope, systemId);
    const ix = S.index(data);
    const groups = {};
    for (const [c, d] of applicable(scope, data, sid)) if (!d.common_control) (groups[c.domain_id] = groups[c.domain_id] || []).push(c);
    const out = [];
    for (const [did, items] of Object.entries(groups)) {
      const fws = new Set(items.map((c) => c.framework_id)).size;
      if (fws >= (minFrameworks || 1)) out.push({ title: ix.dom[did].name, domain_id: did, controls: items.map((c) => c.id), frameworks: fws });
    }
    return out.sort((a, b) => (b.frameworks - a.frameworks) || (b.controls.length - a.controls.length) || (a.title < b.title ? -1 : a.title > b.title ? 1 : 0));
  }
  function ccApplySuggestions(scope, data, systemId, actor, proposals) {
    const sid = sidOf(scope, systemId);
    for (const p of proposals) {
      const c = ccAdd(scope, data, sid, actor, p.title, null, "Proposed from the dataset's domain crosswalk; review before relying on it.", p.domain_id);
      ccMap(scope, data, sid, actor, c.id, p.controls);
    }
    return proposals.length;
  }
  function unmapped(scope, data, systemId) {
    const sid = sidOf(scope, systemId);
    const table = scope.decisions[sid] || {};
    return applicable(scope, data, sid).map(([c]) => c).filter((c) => { const r = table[c.id] || {}; return !r.common_control && !r.common_control_gap; });
  }
  function gapAccept(scope, data, systemId, actor, controls, reason, domain, framework) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    if (!String(reason || "").trim()) throw new WorkflowError("accepting an unmapped control needs a reason");
    const chosen = pick(scope, data, sid, controls, domain, framework).filter((c) => S.decision(scope, sid, c.id).applicable);
    for (const c of chosen) rec(scope, sid, c.id).common_control_gap = String(reason).trim();
    audit(scope, sid, actor, "COMPLIANCE_ARCHITECT", "UNMAPPED_GAP_ACCEPTED", `${chosen.length} control(s)`, { reason: String(reason).trim(), controls: chosen.map((c) => c.id).slice(0, 25) });
    return chosen.length;
  }

  // ---- stage 3: tailoring ----------------------------------------------------------------------------------
  function ccSet(scope, systemId, actor, ccId, fields) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const c = cc(scope, sid, ccId);
    const changed = {};
    for (const [key, value] of Object.entries(fields)) {
      if (value === null || value === undefined) continue;
      if (key === "frequency" && !(value in FREQUENCIES)) throw new WorkflowError(`frequency must be one of ${Object.keys(FREQUENCIES).join(", ")}`);
      if (key === "test_type") {
        if (!TEST_TYPES.includes(value)) throw new WorkflowError(`test type must be one of ${TEST_TYPES.join(", ")}`);
        c.test.type = value; changed[key] = value; continue;
      }
      if (key === "test_description") { c.test.description = String(value); changed[key] = "set"; continue; }
      if (key === "parameters") { Object.assign(c.parameters, value); changed[key] = { ...value }; continue; }
      if (key === "evidence_required") {
        for (const item of value) if (!c.evidence_required.includes(item)) c.evidence_required.push(item);
        changed[key] = [...value]; continue;
      }
      if (key === "owner" || key === "reviewer") {
        const other = key === "owner" ? c.reviewer : c.owner;
        sod(scope, sid, other, value, "the first-line owner and the second-line reviewer");
      }
      if (!["title", "description", "owner", "reviewer", "frequency", "implementation"].includes(key)) throw new WorkflowError(`unknown common-control field '${key}'`);
      c[key] = value;
      changed[key] = key === "implementation" ? "set" : value;
    }
    if (Object.keys(changed).length) {
      c.updated = stamp();
      audit(scope, sid, actor, "FIRST_LINE_CONTROL_OWNER", "CC_TAILORED", ccId, changed);
    }
    return c;
  }
  function tailor(scope, data, systemId, actor, controlId, implementation) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const chosen = pick(scope, data, sid, [controlId]);
    if (!String(implementation || "").trim()) throw new WorkflowError("an implementation statement cannot be empty");
    rec(scope, sid, chosen[0].id).implementation = String(implementation).trim();
    audit(scope, sid, actor, "FIRST_LINE_CONTROL_OWNER", "CONTROL_TAILORED", controlId, { implementation: "set" });
  }
  // Python's format(x, "g"): 6 significant digits, trailing zeros dropped, exponent form for very large or small values.
  function g(x) {
    if (x === 0) return "0";
    if (!Number.isFinite(x)) return String(x);
    const e = Number(x.toExponential(5).split("e")[1]);
    if (e < -4 || e >= 6) {
      const [mant, ex_] = x.toExponential(5).split("e");
      const m = mant.includes(".") ? mant.replace(/0+$/, "").replace(/\.$/, "") : mant;
      return `${m}e${ex_[0] === "-" ? "-" : "+"}${ex_.replace(/^[+-]/, "").padStart(2, "0")}`;
    }
    const fixed = x.toFixed(Math.max(0, 5 - e));
    return fixed.includes(".") ? fixed.replace(/0+$/, "").replace(/\.$/, "") : fixed;
  }
  function indicatorAdd(scope, systemId, actor, ccId, name, kind, metric, op, value) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const c = cc(scope, sid, ccId);
    if (!["KCI", "KRI"].includes(kind)) throw new WorkflowError("kind must be KCI (key control indicator) or KRI (key risk indicator)");
    if (!OPS.includes(op)) throw new WorkflowError(`breach operator must be one of ${OPS.join(" ")}`);
    if (!String(name).trim() || !String(metric).trim()) throw new WorkflowError("an indicator needs a name and a metric");
    const id = `${kind}-${c.indicators.length + 1}`;
    const ind = { id, name: String(name).trim(), kind, metric: String(metric).trim(), breach_if: { op, value: Number(value) } };
    c.indicators.push(ind);
    audit(scope, sid, actor, "SECOND_LINE_RISK_MANAGER", "INDICATOR_ADDED", `${ccId}/${id}`,
      { id, name: ind.name, kind, metric: ind.metric, breach_if: `${op} ${g(Number(value))}` });
    return ind;
  }

  // ---- stage 4: monitoring ---------------------------------------------------------------------------------
  function ingest(scope, systemId, actor, records, source) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const st = state(scope, sid), m = ccs(scope, sid);
    let accepted = 0, dupes = 0;
    const rejected = [];
    const seen = new Set(st.measurements.map((x) => `${x.cc}\u0000${x.at}\u0000${x.source || ""}`));
    records.forEach((r, idx) => {
      try {
        if (!r || typeof r !== "object" || Array.isArray(r)) throw new WorkflowError("record is not an object");
        const ccId = r.control || r.cc;
        if (!(ccId in m)) throw new WorkflowError(`unknown common control ${pyRepr(ccId)}`);
        if (!RESULTS.includes(r.result)) throw new WorkflowError(`result must be one of ${RESULTS.join(", ")}`);
        const at = iso(parseDt(r.at));
        const metrics = r.metrics || {};
        if (typeof metrics !== "object" || Array.isArray(metrics) || !Object.values(metrics).every((v) => typeof v === "number")) throw new WorkflowError("metrics must be an object of numbers");
        const src = String(r.source || source || "file");
        const key = `${ccId}\u0000${at}\u0000${src}`;
        if (seen.has(key)) { dupes++; return; }
        seen.add(key);
        st.measurements.push({ cc: ccId, at, result: r.result, metrics, source: src, evidence: String(r.evidence || "") });
        accepted++;
      } catch (e) {
        if (e instanceof WorkflowError) rejected.push([idx + 1, e.message]); else throw e;
      }
    });
    st.measurements.sort((a, b) => (a.cc < b.cc ? -1 : a.cc > b.cc ? 1 : a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
    for (const ccId of Object.keys(m)) {
      const own = st.measurements.filter((x) => x.cc === ccId);
      if (own.length > 200) { const drop = new Set(own.slice(0, -200)); st.measurements = st.measurements.filter((x) => !drop.has(x)); }
    }
    if (accepted) st.markers.last_ingest_at = stamp();
    audit(scope, sid, actor, ROLE_CCM, "EVIDENCE_INGESTED", source || "file", { accepted, duplicates: dupes, rejected: rejected.length });
    return { accepted, duplicates: dupes, rejected };
  }
  const pyRepr = (v) => (v === undefined || v === null ? "None" : typeof v === "string" ? `'${v}'` : String(v));
  const round = (x, n) => Math.round(x * 10 ** n) / 10 ** n;

  function effectiveness(scope, systemId, ccId, now) {
    const sid = sidOf(scope, systemId);
    const c = cc(scope, sid, ccId), pol = policy(scope, sid);
    now = now || nowDate();
    const ms = state(scope, sid).measurements.filter((x) => x.cc === ccId);
    if (!ms.length) return { state: "not_tested", rate: null, tested: 0, last_at: null, age_days: null };
    const last = ms[ms.length - 1];
    const win = ms.slice(-pol.effectiveness_window);
    const rate = win.filter((x) => x.result === "pass").length / win.length;
    const age = (now.getTime() - parseDt(last.at).getTime()) / 1000 / 86400;
    const limit = FREQUENCIES[c.frequency || ""];
    let st;
    if (limit !== undefined && age > limit * pol.stale_factor) st = "stale";
    else if (rate >= pol.effective_threshold) st = "effective";
    else if (rate >= pol.partial_threshold) st = "partially_effective";
    else st = "ineffective";
    return { state: st, rate: round(rate, 3), tested: win.length, last_at: last.at, age_days: round(age, 1) };
  }
  function evaluate(scope, systemId, actor, now) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const st = state(scope, sid);
    const scores = {};
    for (const id of Object.keys(ccs(scope, sid))) scores[id] = effectiveness(scope, sid, id, now);
    const known = new Set(st.escalations.map((e) => e.key));
    const breaches = [], fresh = [];
    for (const [ccId, c] of Object.entries(ccs(scope, sid))) {
      for (const ind of c.indicators) {
        const mine = st.measurements.filter((x) => x.cc === ccId);
        let reading = null;
        for (let i = mine.length - 1; i >= 0; i--) if (ind.metric in mine[i].metrics) { reading = mine[i]; break; }
        if (!reading) continue;
        const value = reading.metrics[ind.metric], op = ind.breach_if.op, limit = ind.breach_if.value;
        const breached = { ">": value > limit, ">=": value >= limit, "<": value < limit, "<=": value <= limit }[op];
        const row = { cc: ccId, indicator: ind.id, name: ind.name, kind: ind.kind, metric: ind.metric, value, at: reading.at, breached, rule: `breach if ${op} ${g(limit)}` };
        if (breached) {
          breaches.push(row);
          const key = `${ccId}:${ind.id}:${reading.at}`;
          if (!known.has(key)) {
            const esc = { key, cc: ccId, indicator: ind.id, kind: ind.kind, value, rule: row.rule, at: reading.at, status: "open", raised: stamp() };
            st.escalations.push(esc); fresh.push(esc); known.add(key);
            audit(scope, sid, actor, ROLE_CCM, `${ind.kind}_BREACH`, `${ccId}/${ind.id}`, { value: g(value), rule: row.rule, measured: reading.at });
          }
        }
      }
    }
    st.markers.ccm_evaluated_at = stamp();
    audit(scope, sid, actor, ROLE_CCM, "CCM_EVALUATED", sid, { controls: Object.keys(scores).length, breaches: breaches.length, new_escalations: fresh.length });
    return { effectiveness: scores, breaches, new_escalations: fresh };
  }
  function escalationAck(scope, systemId, actor, key, note) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const esc = state(scope, sid).escalations.find((e) => e.key === key);
    if (!esc) throw new WorkflowError(`unknown escalation '${key}'`);
    Object.assign(esc, { status: "acknowledged", ack_by: actor, ack_at: stamp(), ack_note: note || "" });
    audit(scope, sid, actor, ROLE_SECOND_LINE, "ESCALATION_ACKNOWLEDGED", key, { note: note || "" });
  }

  // ---- stage 5: exceptions --------------------------------------------------------------------------------------
  function ex(scope, sid, id) {
    const e = state(scope, sid).exceptions[id];
    if (!e) throw new WorkflowError(`unknown exception '${id}'`);
    return e;
  }
  function exceptionState(scope, sid, e, today) {
    if (e.status !== "approved") return e.status;
    today = today || todayStr();
    if (e.expires < today) return "expired";
    if (Math.round((dateMs(e.expires) - dateMs(today)) / DAY) <= policy(scope, sid).reassess_warning_days) return "expiring";
    return "active";
  }
  function exceptionCovers(scope, sid, e) {
    const covered = new Set(e.controls || []);
    if (e.cc) for (const m of members(scope, sid, e.cc)) covered.add(m);
    return covered;
  }
  function exceptionRequest(scope, data, systemId, actor, reason, kind, controls, ccId, compensating) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    kind = kind || "waiver";
    if (!EXCEPTION_TYPES.includes(kind)) throw new WorkflowError(`type must be one of ${EXCEPTION_TYPES.join(", ")}`);
    if (!String(reason || "").trim()) throw new WorkflowError("an exception needs a reason");
    let ids = [];
    if (controls && controls.length) {
      ids = pick(scope, data, sid, controls).map((c) => c.id);
      for (const cid of ids) if (!S.decision(scope, sid, cid).applicable) throw new WorkflowError(`${cid} is not applicable, so it needs no exception`);
    }
    if (ccId) cc(scope, sid, ccId);
    if (!ids.length && !ccId) throw new WorkflowError("name the controls (--control) or a common control (--cc) the exception covers");
    const exs = state(scope, sid).exceptions;
    let n = Object.keys(exs).length + 1;
    while (`EX-${String(n).padStart(3, "0")}` in exs) n++;
    const id = `EX-${String(n).padStart(3, "0")}`;
    exs[id] = { id, type: kind, controls: ids, cc: ccId || null, reason: String(reason).trim(), compensating_controls: compensating || "",
      requested_by: actor, requested_at: stamp(), status: "requested", assessment: null, approvals: [], expires: null, revision: 1,
      history: [{ at: stamp(), by: actor, action: "requested", note: String(reason).trim() }] };
    audit(scope, sid, actor, "FIRST_LINE_CONTROL_OWNER", "EXCEPTION_REQUESTED", id, { type: kind, controls: ids, cc: ccId || null });
    return exs[id];
  }
  function exceptionAssess(scope, systemId, actor, id, likelihood, impact, notes) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const e = ex(scope, sid, id);
    if (!EXCEPTION_OPEN.includes(e.status)) throw new WorkflowError(`${id} is ${e.status}; only requested or assessed exceptions can be assessed`);
    for (const [name, v] of [["likelihood", likelihood], ["impact", impact]]) {
      if (!Number.isInteger(v) || v < 1 || v > 5) throw new WorkflowError(`${name} must be a whole number from 1 to 5`);
    }
    sod(scope, sid, e.requested_by, actor, "the requester and the risk assessor");
    const score = likelihood * impact;
    const rating = score <= 4 ? "low" : score <= 9 ? "medium" : score <= 16 ? "high" : "critical";
    e.assessment = { likelihood, impact, score, rating, assessed_by: actor, assessed_at: stamp(), notes: notes || "" };
    e.status = "assessed";
    e.history.push({ at: stamp(), by: actor, action: "assessed", note: `${rating} (${score})` });
    audit(scope, sid, actor, ROLE_SECOND_LINE, "EXCEPTION_ASSESSED", id, { score, rating });
    return e;
  }
  function requiredApprover(scope, sid, e) {
    return RATINGS.indexOf(e.assessment.rating) >= RATINGS.indexOf(policy(scope, sid).executive_approval_from) ? ROLE_EXECUTIVE : ROLE_SECOND_LINE;
  }
  function exceptionApprove(scope, systemId, actor, role, id, days) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const e = ex(scope, sid, id);
    if (e.status !== "assessed") throw new WorkflowError(`${id} is ${e.status}; it must be assessed before approval`);
    const need = requiredApprover(scope, sid, e);
    const allowed = need === ROLE_EXECUTIVE ? [ROLE_EXECUTIVE] : [ROLE_SECOND_LINE, ROLE_EXECUTIVE];
    if (!allowed.includes(role)) throw new WorkflowError(`a ${e.assessment.rating} exception needs sign-off by ${need}, not ${role}`);
    sod(scope, sid, e.requested_by, actor, "the requester and the approver");
    sod(scope, sid, e.assessment.assessed_by, actor, "the risk assessor and the approver");
    const limit = policy(scope, sid).exception_max_days[e.assessment.rating];
    if (!Number.isInteger(days) || days < 1) throw new WorkflowError("an approval needs a duration in days (--days)");
    if (days > limit) throw new WorkflowError(`a ${e.assessment.rating} exception can be approved for at most ${limit} days`);
    e.approvals.push({ by: actor, role, at: stamp() });
    e.expires = addDays(todayStr(), days);
    e.status = "approved";
    e.history.push({ at: stamp(), by: actor, action: "approved", note: `until ${e.expires}` });
    audit(scope, sid, actor, role, "EXCEPTION_APPROVED", id, { expires: e.expires, days });
    return e;
  }
  function exceptionReject(scope, systemId, actor, role, id, reason) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const e = ex(scope, sid, id);
    if (!EXCEPTION_OPEN.includes(e.status)) throw new WorkflowError(`${id} is ${e.status}; only open exceptions can be rejected`);
    if (![ROLE_SECOND_LINE, ROLE_EXECUTIVE].includes(role)) throw new WorkflowError("only the second line or an executive can reject an exception");
    if (!String(reason || "").trim()) throw new WorkflowError("a rejection needs a reason");
    e.status = "rejected";
    e.history.push({ at: stamp(), by: actor, action: "rejected", note: String(reason).trim() });
    audit(scope, sid, actor, role, "EXCEPTION_REJECTED", id, { reason: String(reason).trim() });
    return e;
  }
  function exceptionReopen(scope, systemId, actor, id, reason) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const e = ex(scope, sid, id);
    if (!["approved", "rejected", "closed"].includes(e.status)) throw new WorkflowError(`${id} is ${e.status}; nothing to reopen`);
    Object.assign(e, { status: "requested", assessment: null, approvals: [], expires: null, revision: e.revision + 1, requested_by: actor });
    e.history.push({ at: stamp(), by: actor, action: "reopened", note: reason || "" });
    audit(scope, sid, actor, "FIRST_LINE_CONTROL_OWNER", "EXCEPTION_REOPENED", id, { reason: reason || "" });
    return e;
  }
  function exceptionClose(scope, systemId, actor, id, reason) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const e = ex(scope, sid, id);
    if (e.status === "closed") throw new WorkflowError(`${id} is already closed`);
    e.status = "closed";
    e.history.push({ at: stamp(), by: actor, action: "closed", note: reason || "" });
    audit(scope, sid, actor, ROLE_SECOND_LINE, "EXCEPTION_CLOSED", id, { reason: reason || "" });
    return e;
  }
  function exceptions(scope, systemId, today) {
    const sid = sidOf(scope, systemId);
    return Object.values(state(scope, sid).exceptions).map((e) => ({ ...e, state: exceptionState(scope, sid, e, today) }));
  }

  function policySet(scope, systemId, actor, key, value) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const stored = (state(scope, sid).policy = state(scope, sid).policy || {});
    const snapshot = JSON.parse(JSON.stringify(stored));
    const bad = () => new WorkflowError(`invalid value '${value}' for ${key}`);
    const asInt = () => { if (!/^[+-]?\d+$/.test(String(value).trim())) throw bad(); return parseInt(value, 10); };
    const asFloat = () => { const n = Number(String(value).trim()); if (String(value).trim() === "" || Number.isNaN(n)) throw bad(); return n; };
    const parts = key.split(".");
    if (key === "separation_of_duties") {
      if (!["true", "false"].includes(String(value).toLowerCase())) throw bad();
      stored[key] = String(value).toLowerCase() === "true";
    } else if (key === "executive_approval_from") {
      if (!RATINGS.includes(value)) throw bad();
      stored[key] = value;
    } else if (parts[0] === "exception_max_days" && parts.length === 2 && RATINGS.includes(parts[1])) {
      stored.exception_max_days = stored.exception_max_days || {};
      stored.exception_max_days[parts[1]] = asInt();
    } else if (key === "reassess_warning_days" || key === "effectiveness_window") {
      stored[key] = asInt();
    } else if (["effective_threshold", "partial_threshold", "stale_factor"].includes(key)) {
      stored[key] = asFloat();
    } else throw new WorkflowError(`unknown policy key '${key}'`);
    const pol = policy(scope, sid);
    if (!(0 <= pol.partial_threshold && pol.partial_threshold <= pol.effective_threshold && pol.effective_threshold <= 1)) {
      for (const k of Object.keys(stored)) delete stored[k];  // roll back: a rejected change must not stay stored
      Object.assign(stored, snapshot);
      throw new WorkflowError("thresholds must satisfy 0 <= partial <= effective <= 1");
    }
    audit(scope, sid, actor, "SECOND_LINE_RISK_MANAGER", "POLICY_CHANGED", key, { value: String(value) });
    return pol;
  }

  // ---- stage 6: gap analysis, POA&M, report ----------------------------------------------------------------------
  function gapAnalysis(scope, data, systemId, actor, today, record) {
    const sid = sidOf(scope, systemId);
    today = today || todayStr();
    const exs = exceptions(scope, sid, today);
    const cover = {};
    for (const e of exs) if (e.state === "active" || e.state === "expiring") for (const cid of exceptionCovers(scope, sid, e)) cover[cid] = [e.id, e.state];
    const expired = new Set();
    for (const e of exs) if (e.state === "expired") for (const cid of exceptionCovers(scope, sid, e)) expired.add(cid);
    const items = [];
    let met = 0, total = 0;
    const byFw = {}, byDom = {};
    for (const [c, d] of applicable(scope, data, sid)) {
      const [target, targetBy] = targetOf(scope, sid, c.id);
      total++;
      const atTarget = RANK[d.status] >= RANK[target];
      for (const [table, key] of [[byFw, c.framework_id], [byDom, c.domain_id]]) {
        const row = (table[key] = table[key] || [0, 0]);
        row[0]++; row[1] += Number(atTarget);
      }
      if (atTarget) { met++; continue; }
      const due = targetBy || d.due || null;
      const state_ = cover[c.id] ? "excepted" : due && due < today ? "overdue" : "open";
      items.push({ control_id: c.id, title: c.title, framework_id: c.framework_id, domain_id: c.domain_id, current: d.status, target, due,
        owner: d.owner || "", state: state_, exception: cover[c.id] ? cover[c.id][0] : null, exception_expired: expired.has(c.id),
        common_control: ((scope.decisions[sid] || {})[c.id] || {}).common_control || null });
    }
    const assurance = [];
    for (const ccId of Object.keys(ccs(scope, sid))) {
      const eff = effectiveness(scope, sid, ccId);
      if (["ineffective", "stale", "not_tested"].includes(eff.state)) {
        const done = members(scope, sid, ccId).filter((cid) => S.DONE.includes(S.decision(scope, sid, cid).status));
        if (done.length) assurance.push({ cc: ccId, title: ccs(scope, sid)[ccId].title, state: eff.state, controls_claiming_done: done.length });
      }
    }
    const order = { overdue: 0, open: 1, excepted: 2 };
    const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
    const out = {
      as_of: today, applicable: total, at_target: met, percent: total ? round((100 * met) / total, 1) : null,
      gaps: items.sort((a, b) => cmp(order[a.state], order[b.state]) || cmp(a.control_id, b.control_id)),
      assurance_gaps: assurance,
      by_framework: Object.fromEntries(Object.keys(byFw).sort().map((k) => [k, { applicable: byFw[k][0], at_target: byFw[k][1] }])),
      by_domain: Object.fromEntries(Object.keys(byDom).sort().map((k) => [k, { applicable: byDom[k][0], at_target: byDom[k][1] }])),
    };
    if (record) {
      state(scope, sid).markers.gap_run_at = stamp();
      audit(scope, sid, actor || "system", "THIRD_LINE_AUDITOR", "GAP_ANALYSIS_RUN", sid, { applicable: total, at_target: met, gaps: items.length });
    }
    return out;
  }
  function poam(scope, data, systemId, today) {
    return gapAnalysis(scope, data, systemId, null, today).gaps.map((g_) => ({
      control_id: g_.control_id, title: g_.title, current: g_.current, target: g_.target, milestone_due: g_.due || "", owner: g_.owner,
      state: g_.state, exception: g_.exception || "", common_control: g_.common_control || "" }));
  }
  function report(scope, data, systemId, actor, record, today) {
    const sid = sidOf(scope, systemId);
    today = today || todayStr();
    const st = state(scope, sid);
    const gap = gapAnalysis(scope, data, sid, null, today);
    const m = ccs(scope, sid);
    const dist = {};
    for (const id of Object.keys(m)) { const s = effectiveness(scope, sid, id).state; dist[s] = (dist[s] || 0) + 1; }
    const v = verifyAudit(auditLog(scope));
    const exs = exceptions(scope, sid, today);
    const n = applicable(scope, data, sid).length, un = unmapped(scope, data, sid).length;
    const exCount = {};
    for (const e of exs) exCount[e.state] = (exCount[e.state] || 0) + 1;
    const cnt = (s) => gap.gaps.filter((x) => x.state === s).length;
    const out = {
      system: sid, organisation: scope.organization, as_of: today, stage: st.stage, cycle: st.cycle, profile: st.profile,
      scope: { applicable_controls: n, mapped_to_common_controls: n - un, unmapped: un },
      common_controls: { count: Object.keys(m).length, effectiveness: dist, open_escalations: st.escalations.filter((e) => e.status === "open").length },
      exceptions: Object.fromEntries(Object.keys(exCount).sort().map((k) => [k, exCount[k]])),
      gap_analysis: { applicable: gap.applicable, at_target: gap.at_target, percent: gap.percent, open: cnt("open"), overdue: cnt("overdue"),
        excepted: cnt("excepted"), assurance_gaps: gap.assurance_gaps.length },
      audit: { events: auditLog(scope).length, chain_valid: v.ok, problems: v.problems.slice(0, 5) },
    };
    if (record) {
      st.markers.report_at = stamp();
      audit(scope, sid, actor || "system", "THIRD_LINE_AUDITOR", "REPORT_GENERATED", sid, { as_of: out.as_of });
    }
    return out;
  }
  function reportMarkdown(scope, data, systemId, actor, record) {
    const r = report(scope, data, systemId, actor, record !== false);
    const s = S.system(scope, systemId);
    const pct = (v) => (v === null ? "n/a" : `${v.toFixed(1)}%`);
    const lines = [`# Governance report: ${s.name}`, "", `Organisation: ${r.organisation}  `, `As of: ${r.as_of}  `,
      `Workflow stage: ${r.stage} (cycle ${r.cycle})`, "", "## Scope and harmonisation", "",
      `- Applicable controls: ${r.scope.applicable_controls}`,
      `- Mapped to common controls: ${r.scope.mapped_to_common_controls} (unmapped: ${r.scope.unmapped})`,
      `- Common controls: ${r.common_controls.count}`, "", "## Control effectiveness", ""];
    const eff = Object.keys(r.common_controls.effectiveness).sort();
    if (eff.length) for (const k of eff) lines.push(`- ${k.replace(/_/g, " ")}: ${r.common_controls.effectiveness[k]}`); else lines.push("- no common controls yet");
    lines.push(`- open KCI/KRI escalations: ${r.common_controls.open_escalations}`, "", "## Target profile gap", "",
      `- At or above target: ${r.gap_analysis.at_target} of ${r.gap_analysis.applicable} (${pct(r.gap_analysis.percent)})`,
      `- Open gaps: ${r.gap_analysis.open}, overdue: ${r.gap_analysis.overdue}, excepted: ${r.gap_analysis.excepted}`,
      `- Controls marked done whose common control is not demonstrably effective: ${r.gap_analysis.assurance_gaps}`, "", "## Exceptions", "");
    const exk = Object.keys(r.exceptions).sort();
    if (exk.length) for (const k of exk) lines.push(`- ${k}: ${r.exceptions[k]}`); else lines.push("- none");
    lines.push("", "## Audit trail", "", `- Events: ${r.audit.events}; hash chain ${r.audit.chain_valid ? "valid" : "BROKEN"}`, "",
      "_Planning aid and working record, not an attestation of compliance. The audit trail is tamper-evident, not immutable._", "");
    return lines.join("\n");
  }

  // ---- the stage machine -------------------------------------------------------------------------------------------------
  function check(scope, data, systemId, action) {
    const sid = sidOf(scope, systemId);
    const st = state(scope, sid), m = ccs(scope, sid);
    const prof = st.profile, mk = st.markers;
    const apps = applicable(scope, data, sid);
    const every = (pred) => { const bad = Object.values(m).filter((c) => !pred(c)).length; return [Object.keys(m).length > 0 && bad === 0, bad]; };
    const nCc = Object.keys(m).length;
    switch (action) {
      case "DEFINE_ORGANIZATIONAL_PROFILE_BOUNDARIES": {
        const missing = ["business_unit", "environment", "boundary"].filter((k) => !prof[k]);
        return [!missing.length, !missing.length ? "complete" : "missing: " + missing.join(", ")];
      }
      case "RATIONALIZE_NON_APPLICABLE_OBLIGATIONS":
        return [action in st.attestations, `${S.rows(scope, data, sid).length - apps.length} control(s) marked not applicable, each with a justification`];
      case "ESTABLISH_CURRENT_VS_TARGET_PROFILES": {
        const missing = ["risk_appetite", "target_default"].filter((k) => !prof[k]);
        return [!missing.length, !missing.length ? "complete" : "missing: " + missing.join(", ")];
      }
      case "MAP_PLATFORM_FRAMEWORKS_TO_COMMON_CONTROLS": {
        const n = Object.keys(m).filter((id) => members(scope, sid, id).length).length;
        return [n > 0, `${n} common control(s) with mapped controls`];
      }
      case "DEDUPLICATE_OVERLAPPING_REQUIREMENTS": return [action in st.attestations, `${nCc} common control(s) defined`];
      case "IDENTIFY_UNMAPPED_FRAMEWORK_GAPS": {
        const n = unmapped(scope, data, sid).length;
        return [n === 0, `${n} applicable control(s) neither mapped nor explicitly accepted as a gap`];
      }
      case "CUSTOMIZE_CONTROL_IMPLEMENTATION_PARAMETERS": {
        const [ok, bad] = every((c) => c.implementation.trim());
        return [ok, nCc ? `${bad} of ${nCc} common control(s) lack an implementation statement` : "no common controls"];
      }
      case "ASSIGN_OPERATIONAL_OWNER_AND_REVIEW_FREQUENCY": {
        const [ok, bad] = every((c) => c.owner && c.reviewer && c.frequency && norm(c.owner) !== norm(c.reviewer));
        return [ok, nCc ? `${bad} of ${nCc} lack owner, a different reviewer, or a frequency` : "no common controls"];
      }
      case "CONFIGURE_EVIDENCE_REQUIREMENTS_AND_TEST_RULES": {
        const [ok, bad] = every((c) => c.evidence_required.length && c.test.type && c.test.description.trim());
        return [ok, nCc ? `${bad} of ${nCc} lack evidence requirements or a test rule` : "no common controls"];
      }
      case "INGEST_AUTOMATED_EVIDENCE_FEEDS": {
        const have = new Set(st.measurements.map((x) => x.cc));
        const [ok, bad] = every((c) => have.has(c.id));
        return [ok, nCc ? `${bad} of ${nCc} common control(s) have no test results` : "no common controls"];
      }
      case "EVALUATE_KCI_KRI_THRESHOLDS":
      case "CALCULATE_REALTIME_CONTROL_EFFECTIVENESS": {
        const ran = mk.ccm_evaluated_at, ing = mk.last_ingest_at;
        const fresh = Boolean(ran) && (!ing || ran >= ing);
        if (action === "EVALUATE_KCI_KRI_THRESHOLDS" && !Object.values(m).some((c) => c.indicators.length)) return [false, "no KCI/KRI indicator defined"];
        return [fresh, fresh ? "evaluated since the last ingest" : "run: workflow ccm evaluate"];
      }
      case "PROCESS_CONTROL_EXCEPTION_REQUESTS": {
        const n = Object.values(st.exceptions).filter((e) => EXCEPTION_OPEN.includes(e.status)).length;
        return [n === 0, n ? `${n} exception(s) awaiting a decision` : "no exception awaiting a decision"];
      }
      case "ASSESS_RISK_EXPOSURE_AGAINST_TOLERANCE": {
        const n = Object.values(st.exceptions).filter((e) => e.status !== "requested" && !e.assessment && ["assessed", "approved"].includes(e.status)).length;
        const pending = Object.values(st.exceptions).filter((e) => e.status === "requested").length;
        return [n === 0 && pending === 0, `${pending} awaiting assessment`];
      }
      case "ENFORCE_EXECUTIVE_APPROVAL_AND_EXPIRATION_DATES": {
        let bad = 0;
        for (const e of Object.values(st.exceptions)) {
          if (e.status !== "approved") continue;
          const need = requiredApprover(scope, sid, e);
          const roles = new Set(e.approvals.map((a) => a.role));
          if (!e.expires || (need === ROLE_EXECUTIVE && !roles.has(ROLE_EXECUTIVE)) || exceptionState(scope, sid, e) === "expired") bad++;
        }
        return [bad === 0, bad ? `${bad} approved exception(s) expired or missing required sign-off` : "all approvals current"];
      }
      case "MEASURE_PROGRESS_TOWARD_TARGET_PROFILE": {
        const ok = Boolean(mk.gap_run_at) && mk.gap_run_at >= st.entered;
        return [ok, ok ? "gap analysis run in this stage" : "run: workflow gap"];
      }
      case "PRESERVE_IMMUTABLE_AUDIT_TRAIL_EVIDENCE": {
        const chain = verifyAudit(auditLog(scope)).ok;
        const ok = chain && Boolean(mk.audit_verified_at) && mk.audit_verified_at >= st.entered;
        return [ok, ok ? "audit chain verified in this stage" : "run: workflow audit verify"];
      }
      case "GENERATE_REALTIME_REGULATORY_DASHBOARDS": {
        const ok = Boolean(mk.report_at) && mk.report_at >= st.entered;
        return [ok, ok ? "report generated in this stage" : "run: workflow report"];
      }
      default: throw new WorkflowError(`unknown action '${action}'`);
    }
  }
  function actions(scope, data, systemId, stageId) {
    const st = state(scope, systemId);
    const stage = STAGES[stageId || st.stage];
    return stage.actions.map((action) => {
      const [ok, detail] = check(scope, data, systemId, action);
      const att = st.attestations[action];
      return { action, kind: ATTESTED.includes(action) ? "attest" : "evidence", satisfied: ok, detail, attested_by: att ? att.by : null };
    });
  }
  function attest(scope, data, systemId, actor, role, action, note) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const st = state(scope, sid);
    const stage = STAGES[st.stage];
    if (!stage.actions.includes(action)) throw new WorkflowError(`${action} is not an action of the current stage (${st.stage})`);
    if (!ATTESTED.includes(action)) throw new WorkflowError(`${action} is satisfied by evidence in the file, not by attestation; see: aicontrols workflow status`);
    role = role || stage.assignedRole;
    if (role !== stage.assignedRole) throw new WorkflowError(`${action} belongs to ${stage.assignedRole}, not ${role}`);
    st.attestations[action] = { by: actor, role, at: stamp(), note: note || "" };
    audit(scope, sid, actor, role, "ACTION_ATTESTED", action, { note: note || "" });
  }
  function advance(scope, data, systemId, actor, force, reason) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const st = state(scope, sid);
    const stage = STAGES[st.stage];
    const open = actions(scope, data, sid).filter((a) => !a.satisfied);
    if (open.length && !force) throw new WorkflowError("cannot leave this stage yet: " + open.map((a) => `${a.action} (${a.detail})`).join("; "));
    if (force && open.length && !String(reason || "").trim()) throw new WorkflowError("forcing past an open gate needs a reason (--reason)");
    const entry = { stage: st.stage, left: stamp(), by: actor, forced: open.length > 0, reason: String(reason || "").trim(), open_actions: open.map((a) => a.action) };
    st.stage_log.push(entry);
    if (stage.isFinal) {
      st.completed_cycles.push({ cycle: st.cycle, at: stamp(), by: actor });
      audit(scope, sid, actor, stage.assignedRole, "CYCLE_COMPLETED", sid, { cycle: st.cycle, forced: entry.forced, reason: entry.reason });
      return "cycle complete";
    }
    const nxt = stage.nextStage;
    st.stage = nxt; st.entered = stamp();
    audit(scope, sid, actor, stage.assignedRole, "STAGE_ADVANCED", `${entry.stage} -> ${nxt}`, { forced: entry.forced, reason: entry.reason, open_actions: entry.open_actions });
    return nxt;
  }
  function restartCycle(scope, systemId, actor, reason) {
    const sid = sidOf(scope, systemId);
    actor = checkActor(actor);
    const st = state(scope, sid);
    st.cycle += 1; st.stage = ORDER[0]; st.entered = stamp(); st.attestations = {};
    Object.assign(st.markers, { ccm_evaluated_at: null, gap_run_at: null, audit_verified_at: null, report_at: null });
    audit(scope, sid, actor, STAGES[ORDER[0]].assignedRole, "CYCLE_STARTED", sid, { cycle: st.cycle, reason: reason || "" });
    return st.cycle;
  }
  function verify(scope, systemId, actor) {
    const v = verifyAudit(auditLog(scope));
    if (v.ok && enabled(scope, systemId)) state(scope, systemId).markers.audit_verified_at = stamp();
    return v;
  }

  // ---- validation (called by the UI on import) --------------------------------------------------------------------------------
  function validate(scope, data) {
    const errors = [], warnings = [];
    const work = scope.workflow || {};
    if (!Object.keys(work).length && !(scope.audit || []).length) return { errors, warnings };
    const ix = S.index(data);
    const sysIds = new Set(scope.systems.map((s) => s.id));
    for (const p of verifyAudit(scope.audit || []).problems) errors.push(`audit: ${p}`);
    for (const [sid, st] of Object.entries(work)) {
      if (!sysIds.has(sid)) { errors.push(`workflow for unknown system '${sid}'`); continue; }
      if (!STAGES[st.stage]) errors.push(`${sid}: unknown workflow stage '${st.stage}'`);
      const m = st.common_controls || {};
      const scopeIds = new Set(S.inScope(scope, data, sid).map((c) => c.id));
      for (const [cid, r] of Object.entries((scope.decisions || {})[sid] || {})) {
        if (r.common_control && !(r.common_control in m)) errors.push(`${sid}/${cid}: mapped to unknown common control '${r.common_control}'`);
        if (r.target !== undefined && !["implemented", "verified"].includes(r.target)) errors.push(`${sid}/${cid}: invalid target '${r.target}'`);
      }
      for (const [id, c] of Object.entries(m)) {
        if (c.frequency !== null && c.frequency !== undefined && !(c.frequency in FREQUENCIES)) errors.push(`${sid}/${id}: invalid frequency '${c.frequency}'`);
        const tt = (c.test || {}).type;
        if (tt !== null && tt !== undefined && !TEST_TYPES.includes(tt)) errors.push(`${sid}/${id}: invalid test type`);
        if (c.owner && c.reviewer && norm(c.owner) === norm(c.reviewer) && ((st.policy || {}).separation_of_duties !== false)) {
          warnings.push(`${sid}/${id}: owner and reviewer are the same person`);
        }
      }
      for (const x of st.measurements || []) {
        if (!(x.cc in m)) errors.push(`${sid}: measurement for unknown common control '${x.cc}'`);
        if (!RESULTS.includes(x.result)) errors.push(`${sid}: measurement with invalid result '${x.result}'`);
      }
      for (const [id, e] of Object.entries(st.exceptions || {})) {
        for (const cid of e.controls || []) if (!scopeIds.has(cid)) errors.push(`${sid}/${id}: covers ${cid}, which is not in scope`);
        if (e.cc && !(e.cc in m)) errors.push(`${sid}/${id}: unknown common control '${e.cc}'`);
        if (e.status === "approved" && !(e.expires && e.assessment && (e.approvals || []).length)) errors.push(`${sid}/${id}: approved without an assessment, approval and expiry date`);
        if (!["requested", "assessed", "approved", "rejected", "closed"].includes(e.status)) errors.push(`${sid}/${id}: invalid status '${e.status}'`);
      }
    }
    return { errors, warnings };
  }

  const api = { SPEC, STAGES, ORDER, ROLE_EXECUTIVE, ROLE_SECOND_LINE, ROLE_CCM, RATINGS, FREQUENCIES, TEST_TYPES, EXCEPTION_TYPES, RISK_APPETITES,
    OPS, ATTESTED, DEFAULT_POLICY, WorkflowError, setClock, sha256, canon, eventHash, verifyAudit, enabled, state, policy, enable, setProfile,
    setTarget, targetOf, cc, members, ccAdd, ccMap, ccSuggest, ccApplySuggestions, unmapped, gapAccept, ccSet, tailor, indicatorAdd, ingest,
    effectiveness, evaluate, escalationAck, exceptionState, exceptionCovers, exceptionRequest, exceptionAssess, requiredApprover,
    exceptionApprove, exceptionReject, exceptionReopen, exceptionClose, exceptions, policySet, gapAnalysis, poam, report, reportMarkdown,
    check, actions, attest, advance, restartCycle, verify, validate, parseDt };
  root.AIC = root.AIC || {};
  root.AIC.workflow = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
