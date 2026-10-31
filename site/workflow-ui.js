// SPDX-License-Identifier: Apache-2.0
// "Workflow" view inside the My scope tab: the six-stage governance lifecycle, in the browser.
// Runs entirely locally on the same scope file the command line uses (see site/workflow.js).
"use strict";
(function () {
  const W = AIC.workflow, S = AIC.scope;
  const ACTOR_KEY = "aicontrols.actor.v1";
  const SHORT = { FRAMEWORK_SCOPING: "Scope", CONTROL_HARMONIZATION: "Harmonise", CONTROL_TAILORING: "Tailor",
    CONTINUOUS_MONITORING: "Monitor", EXCEPTION_GOVERNANCE: "Exceptions", TARGET_GAP_ANALYSIS: "Gap analysis" };
  const STATE_LABEL = { not_tested: "Not tested", effective: "Effective", partially_effective: "Partially effective", ineffective: "Ineffective",
    stale: "Stale", requested: "Requested", assessed: "Assessed", approved: "Approved", active: "Active", expiring: "Expiring", expired: "Expired",
    rejected: "Rejected", closed: "Closed", open: "Open", overdue: "Overdue", excepted: "Excepted" };
  const ROLE_LABEL = { SECOND_LINE_RISK_MANAGER: "Second-line risk manager", EXECUTIVE_APPROVER: "Executive approver" };

  const wui = { policyOpen: false, view: null, cc: null, ex: null, gap: null, proposals: null, ingestMsg: null, eval: null, picks: new Set(), auditN: 15, audit: null };
  let actor = "";
  try { actor = localStorage.getItem(ACTOR_KEY) || ""; } catch (e) { /* storage may be blocked */ }

  const ui = () => AIC.scopeUI;
  const scope = () => ui().scope, data = () => ui().data, sid = () => ui().sid;
  const st = () => W.state(scope(), sid());
  const humanize = (a) => a.toLowerCase().replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const chip = (t) => el("span", { class: "tag" }, t);
  const badge = (s) => el("span", { class: `state ${s}` }, STATE_LABEL[s] || s);
  const field = (label, ...kids) => el("label", {}, label, ...kids);
  const num = (v) => (v === null || v === undefined ? "-" : String(v));
  const sorted = (a) => a.slice().sort((x, y) => (x < y ? -1 : x > y ? 1 : 0));

  // Run a change as the acting person; show errors, re-render on success.
  function act(fn, ok) {
    const a = actor.trim();
    if (!a) return ui().say("Enter who is acting (the “Acting as” field) before making a change.", "error");
    const out = ui().attempt(() => fn(a));
    if (out === false) return false;
    if (ok) ui().say(typeof ok === "function" ? ok(out) : ok, "ok");
    ui().render();
    return out;
  }

  // ---- enable ------------------------------------------------------------------------------------
  function enableCard() {
    return el("div", { class: "card intro" },
      el("h2", {}, "Run the governance workflow for this system"),
      el("p", {}, "A six-stage lifecycle on top of your scoping decisions: define the profile, harmonise controls into common controls, tailor and assign them, monitor effectiveness, govern exceptions, and analyse gaps against a target. Every change is recorded in a hash-chained audit trail."),
      el("p", { class: "privacy" }, el("strong", {}, "Roles are labels. "), "You type who is acting; nothing authenticates it, so separation of duties is checked by name only. The audit trail is tamper-evident, not immutable. See the documentation for the full list of limits."),
      actorField(),
      el("div", { class: "row" }, el("button", { type: "button", class: "primary", onclick: () => act((a) => W.enable(scope(), sid(), a), "Workflow enabled. Start with the organisational profile.") }, "Enable workflow")));
  }
  function actorField() {
    return el("label", { class: "actor" }, "Acting as",
      el("input", { value: actor, placeholder: "your name", autocomplete: "name", "aria-describedby": "actor-help",
        oninput: (e) => { actor = e.target.value; try { localStorage.setItem(ACTOR_KEY, actor); } catch (err) { /* ignore */ } } }),
      el("small", { id: "actor-help", class: "muted" }, "Recorded with every change. Stored in this browser only."));
  }

  // ---- tracker and gate checklist ----------------------------------------------------------------------
  function tracker(view) {
    const cur = st().stage, idx = W.ORDER.indexOf(cur);
    return el("ol", { class: "stagebar", "aria-label": "Workflow stages" }, W.ORDER.map((id, i) => el("li", {},
      el("button", { type: "button", class: `stage-chip${id === view ? " viewing" : ""}${i < idx ? " done" : ""}${id === cur ? " current" : ""}`,
        "aria-pressed": String(id === view), "aria-current": id === cur ? "step" : false, onclick: () => { wui.view = id; ui().render(); } },
        el("span", { class: "n" }, String(i + 1)), " ", SHORT[id]))));
  }
  function gateCard() {
    const state = st(), stage = W.STAGES[state.stage];
    const acts = W.actions(scope(), data(), sid());
    const open = acts.filter((a) => !a.satisfied).length;
    const noteBox = {};
    const done = state.completed_cycles.some((c) => c.cycle === state.cycle);
    return el("div", { class: "card gate" },
      el("h3", {}, `Stage ${W.ORDER.indexOf(state.stage) + 1} of ${W.ORDER.length}: ${stage.name}`),
      el("p", { class: "muted" }, `Cycle ${state.cycle}. Role for this stage: ${stage.assignedRole}. Evidence actions are satisfied by your data; attestations are confirmed by a person.`),
      el("ul", { class: "checks" }, acts.map((a) => el("li", { class: a.satisfied ? "ok" : "open" },
        el("span", { class: "tick", "aria-hidden": "true" }, a.satisfied ? "✓" : "○"),
        el("span", { class: "sr-only" }, a.satisfied ? "Satisfied: " : "Open: "),
        el("div", {}, el("strong", {}, humanize(a.action)), " ", chip(a.kind), a.attested_by ? chip(`attested by ${a.attested_by}`) : null,
          el("div", { class: "muted" }, a.detail),
          a.kind === "attest" && !a.satisfied ? el("div", { class: "row" },
            noteBox[a.action] = el("input", { placeholder: "note (optional)", "aria-label": `Note for ${humanize(a.action)}` }),
            el("button", { type: "button", class: "ghost", onclick: () => act((who) => W.attest(scope(), data(), sid(), who, null, a.action, noteBox[a.action].value), "Attested.") }, "Attest")) : null)))),
      done ? el("div", { class: "row" },
        el("p", { class: "sum" }, "This cycle is complete."),
        el("button", { type: "button", class: "primary", onclick: () => { wui.view = null; act((who) => W.restartCycle(scope(), sid(), who, "Next assessment cycle"), "Next cycle started."); } }, "Start next cycle"))
        : advanceRow(stage, open));
  }
  function advanceRow(stage, open) {
    let force, reason;
    return el("div", { class: "row" },
      el("button", { type: "button", class: "primary", onclick: () => {
        const f = force.checked, r = reason.value;
        wui.view = null;
        act((who) => W.advance(scope(), data(), sid(), who, f, r), (res) => (res === "cycle complete" ? "Cycle complete." : `Advanced to ${W.STAGES[res].name}.`));
      } }, stage.isFinal ? "Complete this cycle" : "Advance to next stage"),
      el("label", { class: "inline" }, force = el("input", { type: "checkbox" }), " Force past open actions"),
      reason = el("input", { placeholder: "reason (required to force)", "aria-label": "Reason for forcing" }),
      open ? el("span", { class: "muted" }, `${open} action(s) open`) : el("span", { class: "muted" }, "ready"));
  }

  // ---- stage 1 --------------------------------------------------------------------------------------------
  function scopingPanel() {
    const p = st().profile, ix = S.index(data());
    const inScope = S.inScope(scope(), data(), sid());
    const domains = sorted([...new Set(inScope.map((c) => c.domain_id))]);
    let kindSel, valSel, statusSel, dateInp;
    const fillVals = () => {
      const opts = kindSel.value === "domain" ? domains.map((d) => [d, ix.dom[d].name]) : kindSel.value === "framework" ? sys().frameworks.map((f) => [f, ix.fw[f].name]) : [];
      fill(valSel, opts.map(([v, l]) => el("option", { value: v }, l)));
      valSel.hidden = kindSel.value === "all";
    };
    return el("div", {},
      el("form", { class: "card", onsubmit: (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const assets = String(fd.get("assets") || "").split(",").map((x) => x.trim()).filter(Boolean);
        act((who) => W.setProfile(scope(), sid(), who, { business_unit: fd.get("bu") || null, environment: fd.get("env") || null, boundary: fd.get("boundary") || null,
          asset_classes: assets.length ? assets : null, risk_appetite: fd.get("ra") || null, target_default: fd.get("td") || null }), "Profile saved.");
      } },
        el("h3", {}, "Organisational profile"),
        el("p", { class: "muted" }, "The boundary this system's governance covers, your risk appetite, and the state controls should reach by default."),
        el("div", { class: "grid2" },
          field("Business unit", el("input", { name: "bu", value: p.business_unit || "" })),
          field("Environment", el("input", { name: "env", value: p.environment || "", placeholder: "e.g. production, EU region" }))),
        field("Boundary", el("textarea", { name: "boundary", rows: "2" }, p.boundary || "")),
        el("div", { class: "grid2" },
          field("Asset classes (comma separated)", el("input", { name: "assets", value: (p.asset_classes || []).join(", ") })),
          field("Risk appetite", el("select", { name: "ra" }, [["", "(not set)"], ["low", "Low"], ["moderate", "Moderate"], ["high", "High"]].map(([v, l]) => el("option", { value: v, selected: (p.risk_appetite || "") === v }, l)))),
          field("Default target for controls", el("select", { name: "td" }, [["", "(not set)"], ["implemented", "Implemented"], ["verified", "Verified"]].map(([v, l]) => el("option", { value: v, selected: (p.target_default || "") === v }, l))))),
        el("button", { type: "submit", class: "primary" }, "Save profile")),
      el("div", { class: "card" },
        el("h3", {}, "Target profile"),
        el("p", { class: "muted" }, "The current profile is each control's status. The target is “implemented” unless you set “verified” or a date here."),
        el("div", { class: "filters-inline" },
          field("Apply to", kindSel = el("select", { onchange: fillVals }, [["all", "All in-scope controls"], ["domain", "A domain"], ["framework", "A framework"]].map(([v, l]) => el("option", { value: v }, l)))),
          field("", valSel = el("select", { "aria-label": "Domain or framework", hidden: true })),
          field("Target", statusSel = el("select", {}, ["implemented", "verified"].map((v) => el("option", { value: v }, v)))),
          field("By date", dateInp = el("input", { type: "date" })),
          el("button", { type: "button", class: "ghost", onclick: () => {
            const kind = kindSel.value;
            act((who) => W.setTarget(scope(), data(), sid(), who, statusSel.value, dateInp.value || null,
              kind === "all" ? inScope.map((c) => c.id) : [], kind === "domain" ? valSel.value : null, kind === "framework" ? valSel.value : null),
            (n) => `Target set on ${n} control(s).`);
          } }, "Set target")),
        el("p", { class: "muted" }, `${S.rows(scope(), data(), sid()).filter(([, d]) => !d.applicable).length} control(s) are marked not applicable (see the Controls tab; each needs a justification).`)));
  }
  const sys = () => S.system(scope(), sid());

  // ---- stage 2 -------------------------------------------------------------------------------------------------
  function ccTable(onSelect) {
    const m = st().common_controls, ix = S.index(data());
    const rows = Object.values(m);
    if (!rows.length) return el("p", { class: "muted" }, "No common controls yet. Propose them from the dataset's domains, or add one.");
    return el("div", { class: "scroll" }, el("table", { class: "grid" },
      el("thead", {}, el("tr", {}, ["Common control", "Controls", "Frameworks", "Owner", "Effectiveness", ""].map((h) => el("th", { scope: "col" }, h)))),
      el("tbody", {}, rows.map((c) => {
        const mem = W.members(scope(), sid(), c.id);
        return el("tr", { class: wui.cc === c.id ? "open" : "" },
          el("th", { scope: "row" }, el("button", { type: "button", class: "link", onclick: () => onSelect(c.id) }, c.title), el("div", { class: "r-id" }, c.id)),
          el("td", {}, mem.length), el("td", {}, new Set(mem.map((id) => ix.ctl[id].framework_id)).size), el("td", {}, c.owner || "-"),
          el("td", {}, badge(W.effectiveness(scope(), sid(), c.id).state)), el("td", {}));
      }))));
  }
  function harmonisationPanel() {
    const ix = S.index(data());
    const un = W.unmapped(scope(), data(), sid());
    const m = st().common_controls, ccIds = Object.keys(m);
    let ccSel, reasonInp, domSel, newTitle;
    const props = wui.proposals;
    const picked = [...wui.picks].filter((id) => un.some((c) => c.id === id));
    return el("div", {},
      el("div", { class: "card" },
        el("h3", {}, "Common controls"),
        el("p", { class: "muted" }, "One internal control, tested once, that satisfies many framework controls. Marking a common control effective never changes the status of the controls mapped to it."),
        ccTable((id) => { wui.cc = id; wui.view = "CONTROL_TAILORING"; ui().render(); }),
        el("div", { class: "filters-inline" },
          el("button", { type: "button", class: "ghost", onclick: () => { wui.proposals = W.ccSuggest(scope(), data(), sid(), 1).map((p) => ({ ...p, on: true })); ui().render(); } }, "Propose from the dataset's domains"),
          field("or add one", newTitle = el("input", { placeholder: "e.g. Incident response process", "aria-label": "Title of a new common control" })),
          el("button", { type: "button", class: "ghost", onclick: () => act((who) => W.ccAdd(scope(), data(), sid(), who, newTitle.value, null, "", null), "Common control added.") }, "Add")),
        props ? proposalsCard(props) : null),
      el("div", { class: "card" },
        el("h3", {}, `Unmapped controls (${un.length})`),
        el("p", { class: "muted" }, "Applicable controls with no common control. Map them, or accept them as deliberately unmapped with a reason."),
        ccIds.length ? el("div", { class: "filters-inline" },
          field("Map to", ccSel = el("select", {}, ccIds.map((id) => el("option", { value: id }, `${id}: ${m[id].title}`)))),
          el("button", { type: "button", class: "ghost", disabled: !picked.length, onclick: () => act((who) => W.ccMap(scope(), data(), sid(), who, ccSel.value, picked, null, null, false), (n) => { wui.picks.clear(); return `Mapped ${n} control(s).`; }) }, `Map ${picked.length} selected`),
          field("or all unmapped in domain", domSel = el("select", {}, sorted([...new Set(un.map((c) => c.domain_id))]).map((d) => el("option", { value: d }, ix.dom[d].name)))),
          el("button", { type: "button", class: "ghost", disabled: !un.length, onclick: () => {
            const ids = un.filter((c) => c.domain_id === domSel.value).map((c) => c.id);
            act((who) => W.ccMap(scope(), data(), sid(), who, ccSel.value, ids, null, null, false), (n) => `Mapped ${n} control(s).`);
          } }, "Map that domain")) : el("p", { class: "muted" }, "Create a common control first."),
        el("div", { class: "filters-inline" },
          field("Accept selected as unmapped: reason", reasonInp = el("input", { placeholder: "e.g. covered by the processor agreement" })),
          el("button", { type: "button", class: "ghost", disabled: !picked.length, onclick: () => act((who) => W.gapAccept(scope(), data(), sid(), who, picked, reasonInp.value, null, null), (n) => { wui.picks.clear(); return `${n} control(s) accepted as unmapped.`; }) }, `Accept ${picked.length} selected`)),
        un.length ? el("div", { class: "scroll", style: "max-height:320px" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, [el("th", { scope: "col" }, el("input", { type: "checkbox", "aria-label": "Select all shown", onchange: (e) => { un.slice(0, 150).forEach((c) => (e.target.checked ? wui.picks.add(c.id) : wui.picks.delete(c.id))); ui().render(); } })), el("th", { scope: "col" }, "Control"), el("th", { scope: "col" }, "Domain")])),
          el("tbody", {}, un.slice(0, 150).map((c) => el("tr", {},
            el("td", {}, el("input", { type: "checkbox", "aria-label": `Select ${c.title}`, checked: wui.picks.has(c.id), onchange: (e) => { e.target.checked ? wui.picks.add(c.id) : wui.picks.delete(c.id); ui().render(); } })),
            el("th", { scope: "row" }, c.title, el("div", { class: "r-id" }, c.id)), el("td", {}, ix.dom[c.domain_id].name)))))) : el("p", { class: "sum" }, "Every applicable control is mapped or accepted."),
        un.length > 150 ? el("p", { class: "muted" }, `Showing the first 150 of ${un.length}. Use “Map that domain” for the rest.`) : null));
  }
  function proposalsCard(props) {
    if (!props.length) return el("p", { class: "muted" }, "Nothing to propose: every applicable control is already mapped.");
    return el("div", { class: "card inner" },
      el("h4", {}, "Proposed common controls (one per domain)"),
      el("p", { class: "muted" }, "These mirror the dataset's domain crosswalk. They are a starting point for the architect, not a finding that the controls are equivalent."),
      el("ul", { class: "plain" }, props.map((p) => el("li", {}, el("label", { class: "inline" },
        el("input", { type: "checkbox", checked: p.on, onchange: (e) => { p.on = e.target.checked; } }), ` ${p.title} `, el("span", { class: "muted" }, `(${p.controls.length} controls, ${p.frameworks} framework(s))`))))),
      el("div", { class: "row" },
        el("button", { type: "button", class: "primary", onclick: () => { const chosen = props.filter((p) => p.on); wui.proposals = null; act((who) => W.ccApplySuggestions(scope(), data(), sid(), who, chosen), (n) => `Created ${n} common control(s).`); } }, "Create selected"),
        el("button", { type: "button", class: "ghost", onclick: () => { wui.proposals = null; ui().render(); } }, "Dismiss")));
  }

  // ---- stage 3 ----------------------------------------------------------------------------------------------------------
  function tailoringPanel() {
    const m = st().common_controls, ids = Object.keys(m);
    if (!ids.length) return el("div", { class: "card" }, el("p", { class: "muted" }, "Define common controls in the Harmonise stage first."));
    if (!wui.cc || !m[wui.cc]) wui.cc = ids[0];
    const c = m[wui.cc];
    const ok = (v) => (v ? "✓" : "–");
    return el("div", {},
      el("div", { class: "card" }, el("h3", {}, "Completeness"),
        el("div", { class: "scroll" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, ["Common control", "Implementation", "Owner", "Reviewer", "Frequency", "Evidence", "Test"].map((h) => el("th", { scope: "col" }, h)))),
          el("tbody", {}, ids.map((id) => { const x = m[id]; return el("tr", { class: id === wui.cc ? "open" : "" },
            el("th", { scope: "row" }, el("button", { type: "button", class: "link", onclick: () => { wui.cc = id; ui().render(); } }, x.title)),
            el("td", {}, ok(x.implementation.trim())), el("td", {}, ok(x.owner)), el("td", {}, ok(x.reviewer)), el("td", {}, ok(x.frequency)),
            el("td", {}, ok(x.evidence_required.length)), el("td", {}, ok(x.test.type && x.test.description.trim()))); }))))),
      el("form", { class: "card", onsubmit: (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const params = {};
        for (const line of String(fd.get("params") || "").split("\n")) { const i = line.indexOf("="); if (i > 0) params[line.slice(0, i).trim()] = line.slice(i + 1).trim(); }
        const evidence = String(fd.get("evidence") || "").split("\n").map((x) => x.trim()).filter(Boolean);
        act((who) => W.ccSet(scope(), sid(), who, wui.cc, { title: fd.get("title") || null, description: fd.get("description") || null, owner: fd.get("owner") || null,
          reviewer: fd.get("reviewer") || null, frequency: fd.get("frequency") || null, implementation: fd.get("implementation") || null,
          evidence_required: evidence.length ? evidence : null, test_type: fd.get("ttype") || null, test_description: fd.get("tdesc") || null,
          parameters: Object.keys(params).length ? params : null }), "Saved.");
      } },
        el("h3", {}, `Tailor ${c.id}`),
        el("p", { class: "muted" }, `${W.members(scope(), sid(), c.id).length} framework control(s) map to this common control. The owner and the reviewer must be different people.`),
        el("div", { class: "grid2" },
          field("Title", el("input", { name: "title", value: c.title })),
          field("First-line owner", el("input", { name: "owner", value: c.owner || "" })),
          field("Second-line reviewer", el("input", { name: "reviewer", value: c.reviewer || "" })),
          field("Review and test frequency", el("select", { name: "frequency" }, [["", "(not set)"], ...Object.keys(W.FREQUENCIES).map((f) => [f, f])].map(([v, l]) => el("option", { value: v, selected: (c.frequency || "") === v }, l))))),
        field("Implementation statement", el("textarea", { name: "implementation", rows: "3", placeholder: "How this control is actually implemented here" }, c.implementation)),
        field(`Evidence required (add one per line; existing: ${c.evidence_required.join("; ") || "none"})`, el("textarea", { name: "evidence", rows: "2" })),
        el("div", { class: "grid2" },
          field("Test type", el("select", { name: "ttype" }, [["", "(not set)"], ...W.TEST_TYPES.map((t) => [t, t === "rcsa" ? "rcsa (self-assessment)" : t])].map(([v, l]) => el("option", { value: v, selected: (c.test.type || "") === v }, l)))),
          field("Test rule", el("input", { name: "tdesc", value: c.test.description, placeholder: "query, script or questionnaire" }))),
        field(`Parameters (name=value per line${Object.keys(c.parameters).length ? "; existing: " + JSON.stringify(c.parameters) : ""})`, el("textarea", { name: "params", rows: "2" })),
        el("button", { type: "submit", class: "primary" }, "Save")));
  }

  // ---- stage 4 -------------------------------------------------------------------------------------------------------------
  function monitoringPanel() {
    const state = st(), m = state.common_controls, ids = Object.keys(m);
    if (!ids.length) return el("div", { class: "card" }, el("p", { class: "muted" }, "Define common controls first."));
    if (!wui.cc || !m[wui.cc]) wui.cc = ids[0];
    const c = m[wui.cc];
    let text, srcInp, fileInp;
    const runIngest = (raw, source) => {
      let records;
      try { const v = JSON.parse(raw); records = Array.isArray(v) ? v : [v]; }
      catch (e) {
        records = [];
        for (const [i, line] of raw.split("\n").entries()) if (line.trim()) { try { records.push(JSON.parse(line)); } catch (err) { return ui().say(`Line ${i + 1} is not valid JSON.`, "error"); } }
      }
      const r = act((who) => W.ingest(scope(), sid(), who, records, source || "pasted"), null);
      if (r) { wui.ingestMsg = `Ingested ${r.accepted} result(s); ${r.duplicates} duplicate(s); ${r.rejected.length} rejected.` + r.rejected.slice(0, 5).map(([i, w]) => ` Record ${i}: ${w}.`).join(""); ui().say(wui.ingestMsg, r.rejected.length ? "warn" : "ok"); ui().render(); }
    };
    return el("div", {},
      el("div", { class: "card" },
        el("h3", {}, "Effectiveness"),
        el("p", { class: "muted" }, "Pass rate over the last 5 results: effective at 90% or more, partially effective at 60% or more, otherwise ineffective. Stale if the latest result is older than 1.5 times the control's frequency."),
        el("div", { class: "scroll" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, ["Common control", "State", "Pass rate", "Results", "Last result", "Age (days)"].map((h) => el("th", { scope: "col" }, h)))),
          el("tbody", {}, ids.map((id) => { const e = W.effectiveness(scope(), sid(), id); return el("tr", {},
            el("th", { scope: "row" }, m[id].title, el("div", { class: "r-id" }, id)), el("td", {}, badge(e.state)),
            el("td", {}, e.rate === null ? "-" : `${Math.round(e.rate * 100)}%`), el("td", {}, e.tested), el("td", {}, e.last_at || "-"), el("td", {}, num(e.age_days))); })))),
        el("div", { class: "row" }, el("button", { type: "button", class: "primary", onclick: () => {
          const r = act((who) => W.evaluate(scope(), sid(), who), null);
          if (r) { wui.eval = r; ui().say(`Evaluated ${Object.keys(r.effectiveness).length} common control(s): ${r.breaches.length} threshold breach(es), ${r.new_escalations.length} new escalation(s).`, r.breaches.length ? "warn" : "ok"); ui().render(); }
        } }, "Evaluate now"))),
      el("div", { class: "card" },
        el("h3", {}, "Ingest results"),
        el("p", { class: "muted" }, "Paste results from your own scripts (a JSON array or one JSON object per line), or choose a file. Nothing is uploaded."),
        el("details", {}, el("summary", {}, "Record format"), el("pre", { class: "code" }, '{"control": "CC-001", "at": "2026-10-26T10:00:00Z", "result": "pass",\n "metrics": {"failed_logins": 3}, "source": "iam-export", "evidence": "ticket-123"}\n\nresult: pass | fail | error (errors count as failures). Duplicates are ignored.')),
        text = el("textarea", { rows: "4", "aria-label": "Results as JSON", placeholder: '[{"control":"CC-001","at":"2026-10-26T10:00:00Z","result":"pass"}]' }),
        el("div", { class: "filters-inline" },
          field("Source label", srcInp = el("input", { value: "pasted" })),
          el("button", { type: "button", class: "ghost", onclick: () => runIngest(text.value, srcInp.value) }, "Ingest pasted results"),
          field("or a file", fileInp = el("input", { type: "file", accept: ".json,.jsonl,.txt", onchange: async () => { if (fileInp.files[0]) runIngest(await fileInp.files[0].text(), fileInp.files[0].name); } })))),
      el("div", { class: "card" },
        el("h3", {}, "KCI and KRI indicators"),
        el("p", { class: "muted" }, "A breach is recorded once as an escalation and in the audit trail. Nothing is emailed or paged."),
        field("Common control", el("select", { onchange: (e) => { wui.cc = e.target.value; ui().render(); } }, ids.map((id) => el("option", { value: id, selected: id === wui.cc }, `${id}: ${m[id].title}`)))),
        c.indicators.length ? el("ul", { class: "plain" }, c.indicators.map((i) => el("li", {}, chip(i.kind), ` ${i.name}: breach if ${i.metric} ${i.breach_if.op} ${i.breach_if.value}`))) : el("p", { class: "muted" }, "No indicators on this control yet."),
        indicatorForm()),
      escalationsCard(state),
      wui.eval && wui.eval.breaches.length ? el("div", { class: "card" }, el("h4", {}, "Current breaches"), el("ul", { class: "plain" }, wui.eval.breaches.map((b) => el("li", {}, `${b.kind} ${b.cc}/${b.indicator} ${b.name}: ${b.metric} = ${b.value} (${b.rule})`)))) : null);
  }
  function indicatorForm() {
    return el("form", { class: "filters-inline", onsubmit: (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      act((who) => W.indicatorAdd(scope(), sid(), who, wui.cc, fd.get("name"), fd.get("kind"), fd.get("metric"), fd.get("op"), Number(fd.get("value"))), "Indicator added.");
    } },
      field("Name", el("input", { name: "name", required: true })),
      field("Kind", el("select", { name: "kind" }, ["KRI", "KCI"].map((k) => el("option", { value: k }, k))),),
      field("Metric", el("input", { name: "metric", required: true, placeholder: "name in your results" })),
      field("Breach when value is", el("select", { name: "op" }, W.OPS.map((o) => el("option", { value: o }, o)))),
      field("Threshold", el("input", { name: "value", type: "number", step: "any", required: true })),
      el("button", { type: "submit", class: "ghost" }, "Add indicator"));
  }
  function escalationsCard(state) {
    const list = state.escalations;
    return el("div", { class: "card" }, el("h3", {}, `Escalations (${list.filter((e) => e.status === "open").length} open)`),
      list.length ? el("div", { class: "scroll" }, el("table", { class: "grid" },
        el("thead", {}, el("tr", {}, ["Status", "Indicator", "Value", "Rule", "Measured", ""].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", {}, list.map((e) => { let note; return el("tr", {},
          el("td", {}, badge(e.status === "open" ? "open" : "closed")), el("td", {}, `${e.kind} ${e.cc}/${e.indicator}`), el("td", {}, e.value), el("td", {}, e.rule), el("td", {}, e.at),
          el("td", {}, e.status === "open" ? el("div", { class: "row" }, note = el("input", { class: "cell", placeholder: "note", "aria-label": "Acknowledgement note" }),
            el("button", { type: "button", class: "ghost", onclick: () => act((who) => W.escalationAck(scope(), sid(), who, e.key, note.value), "Acknowledged.") }, "Acknowledge")) : `by ${e.ack_by}`)); }))))
        : el("p", { class: "muted" }, "None recorded."));
  }

  // ---- stage 5 -----------------------------------------------------------------------------------------------------------------
  function exceptionsPanel() {
    const exs = W.exceptions(scope(), sid()), pol = W.policy(scope(), sid());
    if (wui.ex && !exs.some((e) => e.id === wui.ex)) wui.ex = null;
    const m = st().common_controls;
    return el("div", {},
      el("form", { class: "card", onsubmit: (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const ids = String(fd.get("controls") || "").split(/[\s,]+/).filter(Boolean);
        act((who) => W.exceptionRequest(scope(), data(), sid(), who, fd.get("reason"), fd.get("type"), ids, fd.get("cc") || null, fd.get("comp") || ""), (ex) => { wui.ex = ex.id; return `${ex.id} requested. A second-line assessor assesses it next.`; });
      } },
        el("h3", {}, "Request an exception"),
        el("p", { class: "muted" }, "A time-boxed deviation, waiver or delayed remediation. It is assessed, then signed off, and it expires."),
        field("Reason", el("textarea", { name: "reason", rows: "2", required: true })),
        el("div", { class: "grid2" },
          field("Type", el("select", { name: "type" }, W.EXCEPTION_TYPES.map((t) => el("option", { value: t }, t.replace(/_/g, " "))))),
          field("Covers a common control", el("select", { name: "cc" }, [["", "(none)"], ...Object.keys(m).map((id) => [id, `${id}: ${m[id].title}`])].map(([v, l]) => el("option", { value: v }, l)))),
          field("and/or these control ids (comma or space separated)", el("input", { name: "controls", placeholder: "gdpr:Art.33" })),
          field("Compensating controls", el("input", { name: "comp" }))),
        el("button", { type: "submit", class: "primary" }, "Request exception")),
      el("div", { class: "card" },
        el("h3", {}, `Exceptions (${exs.length})`),
        exs.length ? el("div", { class: "scroll" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, ["Id", "State", "Rating", "Until", "Reason"].map((h) => el("th", { scope: "col" }, h)))),
          el("tbody", {}, exs.map((e) => el("tr", { class: wui.ex === e.id ? "open" : "" },
            el("th", { scope: "row" }, el("button", { type: "button", class: "link", onclick: () => { wui.ex = e.id; ui().render(); } }, e.id)),
            el("td", {}, badge(e.state)), el("td", {}, e.assessment ? e.assessment.rating : "-"), el("td", {}, e.expires || "-"), el("td", {}, e.reason.slice(0, 70)))))))
          : el("p", { class: "muted" }, "No exceptions. That is a valid state: this stage's actions are satisfied."),
        el("p", { class: "muted" }, `Policy: ${pol.executive_approval_from} and above need executive sign-off; approval caps: ${W.RATINGS.map((r) => `${r} ${pol.exception_max_days[r]}d`).join(", ")}; re-assessment warning ${pol.reassess_warning_days} days before expiry.`)),
      wui.ex ? exceptionDetail(exs.find((e) => e.id === wui.ex)) : null);
  }
  function exceptionDetail(e) {
    const covers = [...W.exceptionCovers(scope(), sid(), e)];
    let l, i, n, roleA, roleR, days, reason;
    const forms = [];
    if (e.status === "requested" || e.status === "assessed") {
      forms.push(el("div", { class: "filters-inline" }, el("strong", {}, "Assess risk"),
        field("Likelihood (1-5)", l = el("input", { type: "number", min: "1", max: "5", value: e.assessment ? e.assessment.likelihood : "3" })),
        field("Impact (1-5)", i = el("input", { type: "number", min: "1", max: "5", value: e.assessment ? e.assessment.impact : "3" })),
        field("Notes", n = el("input", {})),
        el("button", { type: "button", class: "ghost", onclick: () => act((who) => W.exceptionAssess(scope(), sid(), who, e.id, Number(l.value), Number(i.value), n.value), () => "Assessed.") }, "Record assessment")));
    }
    if (e.status === "assessed") {
      const need = W.requiredApprover(scope(), sid(), e);
      forms.push(el("div", { class: "filters-inline" }, el("strong", {}, `Sign off (needs ${ROLE_LABEL[need]})`),
        field("Signing as", roleA = el("select", {}, [W.ROLE_SECOND_LINE, W.ROLE_EXECUTIVE].map((r) => el("option", { value: r, selected: r === need }, ROLE_LABEL[r])))),
        field("Days", days = el("input", { type: "number", min: "1", value: String(Math.min(30, W.policy(scope(), sid()).exception_max_days[e.assessment.rating])) })),
        el("button", { type: "button", class: "primary", onclick: () => act((who) => W.exceptionApprove(scope(), sid(), who, roleA.value, e.id, Number(days.value)), () => "Approved. It expires on the date shown.") }, "Approve")));
    }
    if (e.status === "requested" || e.status === "assessed") {
      forms.push(el("div", { class: "filters-inline" }, el("strong", {}, "Reject"),
        field("Rejecting as", roleR = el("select", {}, [W.ROLE_SECOND_LINE, W.ROLE_EXECUTIVE].map((r) => el("option", { value: r }, ROLE_LABEL[r])))),
        field("Reason", reason = el("input", {})),
        el("button", { type: "button", class: "ghost", onclick: () => act((who) => W.exceptionReject(scope(), sid(), who, roleR.value, e.id, reason.value), "Rejected.") }, "Reject")));
    }
    if (["approved", "rejected", "closed"].includes(e.status)) {
      forms.push(el("div", { class: "filters-inline" }, el("strong", {}, "Re-assess"),
        field("Reason", reason = el("input", { placeholder: "why it is still needed" })),
        el("button", { type: "button", class: "ghost", onclick: () => act((who) => W.exceptionReopen(scope(), sid(), who, e.id, reason.value), "Reopened for re-assessment.") }, "Reopen")));
    }
    if (e.status !== "closed") {
      let why;
      forms.push(el("div", { class: "filters-inline" }, el("strong", {}, "Close"), field("Reason", why = el("input", {})),
        el("button", { type: "button", class: "ghost", onclick: () => act((who) => W.exceptionClose(scope(), sid(), who, e.id, why.value), "Closed.") }, "Close exception")));
    }
    return el("div", { class: "card" },
      el("h3", {}, `${e.id}: ${e.type.replace(/_/g, " ")}`),
      el("p", {}, badge(e.state), " ", e.assessment ? chip(`${e.assessment.rating} (score ${e.assessment.score})`) : null, " ", e.expires ? chip(`until ${e.expires}`) : null, " ", chip(`revision ${e.revision}`)),
      el("p", {}, e.reason), e.compensating_controls ? el("p", { class: "muted" }, `Compensating controls: ${e.compensating_controls}`) : null,
      el("p", { class: "muted" }, `Covers ${covers.length} control(s)${e.cc ? ` (common control ${e.cc})` : ""}. Requested by ${e.requested_by}.`),
      ...forms,
      el("h4", {}, "History"), el("ul", { class: "plain" }, e.history.map((h) => el("li", {}, `${h.at}: ${h.action} by ${h.by}${h.note ? ` (${h.note})` : ""}`))));
  }

  // ---- stage 6 ------------------------------------------------------------------------------------------------------------------------
  function assurancePanel() {
    const ix = S.index(data());
    const g = wui.gap;
    return el("div", {},
      el("div", { class: "card" },
        el("h3", {}, "Gap analysis against the target profile"),
        el("p", { class: "muted" }, "Compares each applicable control's current status with its target. A gap is open, overdue (past its date) or excepted (covered by an active exception)."),
        el("div", { class: "row" },
          el("button", { type: "button", class: "primary", onclick: () => { const r = act((who) => W.gapAnalysis(scope(), data(), sid(), who, null, true), null); if (r) { wui.gap = r; ui().say("Gap analysis run.", "ok"); ui().render(); } } }, "Run gap analysis"),
          el("button", { type: "button", class: "ghost", onclick: () => {
            const rows = W.poam(scope(), data(), sid());
            const cols = ["control_id", "title", "current", "target", "milestone_due", "owner", "state", "exception", "common_control"];
            ui().download(`${sid()}-poam.csv`, [cols.join(","), ...rows.map((r) => cols.map((c) => S.csvCell(r[c])).join(","))].join("\r\n") + "\r\n", "text/csv");
          } }, "Download POA&M (CSV)")),
        g ? gapResult(g, ix) : null),
      el("div", { class: "card" },
        el("h3", {}, "Governance report"),
        el("p", { class: "muted" }, "A snapshot of scope, harmonisation, effectiveness, gaps, exceptions and audit integrity. Generating it is recorded in the audit trail."),
        el("div", { class: "row" },
          el("button", { type: "button", class: "ghost", onclick: () => { const t = act((who) => W.reportMarkdown(scope(), data(), sid(), who, true), null); if (t) { ui().download(`${sid()}-governance-report.md`, t, "text/markdown"); ui().say("Report downloaded.", "ok"); ui().render(); } } }, "Download report (Markdown)"),
          el("button", { type: "button", class: "ghost", onclick: () => { const r = act((who) => W.report(scope(), data(), sid(), who, true), null); if (r) { ui().download(`${sid()}-governance-report.json`, JSON.stringify(r, null, 2) + "\n", "application/json"); ui().say("Report downloaded.", "ok"); ui().render(); } } }, "Download report (JSON)"))),
      auditCard());
  }
  function gapResult(g, ix) {
    const by = (s) => g.gaps.filter((x) => x.state === s).length;
    return el("div", {},
      el("p", { class: "sum" }, `${g.at_target} of ${g.applicable} applicable controls are at or above target (${g.percent === null ? "n/a" : g.percent.toFixed(1) + "%"}). Gaps: ${by("overdue")} overdue, ${by("open")} open, ${by("excepted")} excepted.`),
      g.assurance_gaps.length ? el("ul", { class: "plain" }, g.assurance_gaps.map((a) => el("li", {}, el("strong", {}, "Assurance gap: "), `${a.title} is ${STATE_LABEL[a.state].toLowerCase()}, yet ${a.controls_claiming_done} mapped control(s) are marked done.`))) : null,
      el("div", { class: "scroll", style: "max-height:360px" }, el("table", { class: "grid" },
        el("thead", {}, el("tr", {}, ["State", "Control", "Now", "Target", "Due", "Owner"].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", {}, g.gaps.slice(0, 100).map((x) => el("tr", {}, el("td", {}, badge(x.state)),
          el("th", { scope: "row" }, x.title, el("div", { class: "r-id" }, x.control_id)), el("td", {}, x.current), el("td", {}, x.target), el("td", {}, x.due || "-"), el("td", {}, x.owner || "-")))))),
      g.gaps.length > 100 ? el("p", { class: "muted" }, `Showing 100 of ${g.gaps.length}. Download the POA&M for all of them.`) : null);
  }
  function auditCard() {
    const log = scope().audit || [];
    const v = wui.audit;
    return el("div", { class: "card" },
      el("h3", {}, `Audit trail (${log.length} events)`),
      el("p", { class: "muted" }, "Each event includes the hash of the one before it. This makes edits detectable; it does not make them impossible. Record the head hash outside this browser to make rewriting the whole history detectable too."),
      el("div", { class: "row" },
        el("button", { type: "button", class: "primary", onclick: () => {
          const r = act((who) => W.verify(scope(), sid(), who), null);
          if (r) { wui.audit = r; ui().say(r.ok ? "Audit chain verified." : "Audit chain is BROKEN.", r.ok ? "ok" : "error"); ui().render(); }
        } }, "Verify chain"),
        el("button", { type: "button", class: "ghost", onclick: () => ui().download(`${sid()}-audit.jsonl`, log.map((e) => JSON.stringify(e)).join("\n") + "\n", "application/x-ndjson") }, "Export (JSON lines)")),
      v ? el("p", { class: v.ok ? "sum" : "caveat" }, v.ok ? `Chain OK: ${log.length} events. Head hash: ${log.length ? log[log.length - 1].hash : "-"}` : "BROKEN: " + v.problems.slice(0, 3).join("; ")) : null,
      el("div", { class: "scroll", style: "max-height:300px" }, el("table", { class: "grid" },
        el("thead", {}, el("tr", {}, ["#", "When", "Who", "Role", "Action", "Target"].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", {}, log.slice(-wui.auditN).reverse().map((e) => el("tr", {}, el("td", {}, e.seq), el("td", {}, e.at), el("td", {}, e.actor), el("td", {}, e.role), el("td", {}, e.action), el("td", {}, e.target)))))),
      log.length > wui.auditN ? el("button", { type: "button", class: "ghost", onclick: () => { wui.auditN += 30; ui().render(); } }, "Show more") : null);
  }
  // ---- workflow rules (policy) -----------------------------------------------------------------------------------------------------
  // The same settings as `aicontrols workflow policy`, in plain language. Each rule saves when you change it.
  const RULES = [
    { group: "Who must sign off", rows: [
      { key: "separation_of_duties", kind: "bool", label: "Require different people for each role",
        help: "The person who requests an exception cannot also assess or approve it, and a control's owner and reviewer must be different people. Checked by the name in “Acting as”. A one-person team can switch this off; the change is recorded." },
      { key: "executive_approval_from", kind: "rating", label: "Executive sign-off needed from this risk rating",
        help: "Exceptions rated this or higher need an executive approver. Lower-rated ones can be signed off by the second-line risk manager. Ratings: low 1–4, medium 5–9, high 10–16, critical 17–25 (likelihood × impact)." },
    ] },
    { group: "How long an exception can last", rows: [
      { key: "exception_max_days.low", kind: "days", label: "Low risk: longest approval (days)", help: "An approval cannot run longer than this. Afterwards the exception expires and must be re-assessed." },
      { key: "exception_max_days.medium", kind: "days", label: "Medium risk: longest approval (days)", help: "" },
      { key: "exception_max_days.high", kind: "days", label: "High risk: longest approval (days)", help: "" },
      { key: "exception_max_days.critical", kind: "days", label: "Critical risk: longest approval (days)", help: "" },
      { key: "reassess_warning_days", kind: "days", label: "Warn before an exception expires (days)", help: "An approved exception shows as “Expiring” this many days before its end date." },
    ] },
    { group: "How control effectiveness is scored", rows: [
      { key: "effectiveness_window", kind: "count", label: "Test results considered", help: "A common control is judged on its most recent results only. 5 means the last five." },
      { key: "effective_threshold", kind: "pct", label: "Pass rate for “Effective” (%)", help: "At or above this share of passes, the control is Effective." },
      { key: "partial_threshold", kind: "pct", label: "Pass rate for “Partially effective” (%)", help: "At or above this (but below Effective) it is Partially effective; below it, Ineffective. Cannot be higher than the Effective rate." },
      { key: "stale_factor", kind: "factor", label: "Mark as stale after (× its test interval)", help: "A control is Stale when its latest result is older than this many times its frequency. At 1.5, a monthly control goes stale after about 46 days." },
    ] },
  ];
  const ALL_RULES = RULES.flatMap((g) => g.rows);
  const polGet = (pol, key) => key.split(".").reduce((o, k) => o[k], pol);
  const polShow = (rule, v) => (rule.kind === "pct" ? String(Math.round(v * 100)) : String(v));
  const changedCount = () => { const pol = W.policy(scope(), sid()); return ALL_RULES.filter((r) => polGet(pol, r.key) !== polGet(W.DEFAULT_POLICY, r.key)).length; };
  const summaryText = () => { const n = changedCount(); return n ? `${n} changed from the defaults` : "defaults in use (suits most teams)"; };

  function ruleRow(rule) {
    const def = polGet(W.DEFAULT_POLICY, rule.key);
    let input, saved, reset;
    const current = () => polGet(W.policy(scope(), sid()), rule.key);
    const row = el("div", { class: "rule" });
    const sync = () => {
      const changed = current() !== def;
      input.value = rule.kind === "bool" ? String(current()) : polShow(rule, current());
      reset.hidden = !changed; row.classList.toggle("changed", changed);
      const sum = document.getElementById("policy-summary"); if (sum) sum.textContent = summaryText();
      const all = document.getElementById("policy-reset-all"); if (all) all.disabled = changedCount() === 0;
    };
    const save = (raw) => {
      const who = actor.trim();
      if (!who) { ui().say("Enter who is acting (the “Acting as” field) before changing a rule.", "error"); return sync(); }
      const value = rule.kind === "pct" ? String(Number(raw) / 100) : String(raw);
      const ok = ui().attempt(() => W.policySet(scope(), sid(), who, rule.key, value));
      if (ok === false) return sync();                      // refused (e.g. thresholds out of order): show the real value again
      saved.textContent = "✓ Saved"; setTimeout(() => { saved.textContent = ""; }, 3000);
      ui().say(`Rule changed: ${rule.label.replace(/ \(.*\)$/, "")}. Recorded in the audit trail.`, "ok");
      sync();
    };
    const attrs = { id: `rule-${rule.key}`, "aria-describedby": `rule-help-${rule.key}`, onchange: (e) => save(e.target.value) };
    const control = rule.kind === "bool"
      ? el("select", attrs, [["true", "Yes, require it"], ["false", "No, allow the same person"]].map(([v, l]) => el("option", { value: v }, l)))
      : rule.kind === "rating"
        ? el("select", attrs, W.RATINGS.map((r) => el("option", { value: r }, r)))
        : el("input", { ...attrs, type: "number", min: rule.kind === "factor" ? "0.1" : rule.kind === "pct" ? "0" : "1", max: rule.kind === "pct" ? "100" : null,
          step: rule.kind === "factor" ? "0.1" : "1", class: "num" });
    input = control;
    row.append(
      el("div", { class: "rule-text" }, el("label", { for: `rule-${rule.key}` }, rule.label), rule.help ? el("p", { class: "muted", id: `rule-help-${rule.key}` }, rule.help) : null),
      el("div", { class: "rule-ctl" }, input,
        reset = el("button", { type: "button", class: "ghost small", title: `Back to the default (${polShow(rule, def)})`, onclick: () => save(rule.kind === "pct" ? String(Math.round(def * 100)) : def) }, "Reset"),
        saved = el("span", { class: "saved inline", role: "status" }),
        el("span", { class: "muted default" }, `default ${rule.kind === "bool" ? (def ? "yes" : "no") : polShow(rule, def)}`)));
    sync();
    return row;
  }

  function policyCard() {
    return el("details", { class: "card policy", open: wui.policyOpen ? true : false, ontoggle: (e) => { wui.policyOpen = e.target.open; } },
      el("summary", {}, "Workflow rules (policy) ", el("span", { class: "tag", id: "policy-summary" }, summaryText())),
      el("p", { class: "muted" }, "These rules decide how strict the exceptions process is and how control effectiveness is scored. The defaults suit most teams, so you can leave this alone. A change applies to this system only, takes effect immediately, and is recorded in the audit trail."),
      RULES.map((g) => el("fieldset", { class: "rules" }, el("legend", {}, g.group), g.rows.map(ruleRow))),
      el("div", { class: "row" },
        el("button", { type: "button", class: "ghost", id: "policy-reset-all", disabled: changedCount() === 0, onclick: () => {
          const who = actor.trim();
          if (!who) return ui().say("Enter who is acting (the “Acting as” field) before changing a rule.", "error");
          const pol = W.policy(scope(), sid());
          const todo = ALL_RULES.filter((r) => polGet(pol, r.key) !== polGet(W.DEFAULT_POLICY, r.key));
          // "partial <= effective" must hold after every step. Resetting partial first is safe when its default fits under the
          // current effective rate; otherwise resetting effective first is (one of the two always works, since partial <= effective).
          const partialFirst = polGet(W.DEFAULT_POLICY, "partial_threshold") <= pol.effective_threshold;
          const rank = (k) => (k === "partial_threshold" ? (partialFirst ? 0 : 2) : k === "effective_threshold" ? (partialFirst ? 2 : 0) : 1);
          todo.sort((x, y) => rank(x.key) - rank(y.key));
          wui.policyOpen = true;
          const ok = ui().attempt(() => { for (const r of todo) W.policySet(scope(), sid(), who, r.key, String(polGet(W.DEFAULT_POLICY, r.key))); });
          if (ok !== false) { ui().say(`${todo.length} rule(s) reset to the defaults.`, "ok"); ui().render(); }
        } }, "Reset all to defaults")),
      el("details", {}, el("summary", {}, "Show the raw settings"), el("pre", { class: "code" }, JSON.stringify(W.policy(scope(), sid()), null, 2))));
  }

  // ---- the view ---------------------------------------------------------------------------------------------------------------------------
  function panel() {
    if (!W.enabled(scope(), sid())) return enableCard();
    const state = st();
    const view = wui.view && W.STAGES[wui.view] ? wui.view : state.stage;
    const body = { FRAMEWORK_SCOPING: scopingPanel, CONTROL_HARMONIZATION: harmonisationPanel, CONTROL_TAILORING: tailoringPanel,
      CONTINUOUS_MONITORING: monitoringPanel, EXCEPTION_GOVERNANCE: exceptionsPanel, TARGET_GAP_ANALYSIS: assurancePanel }[view];
    return el("div", { class: "wf" },
      el("div", { class: "card actorbar" }, actorField(), el("p", { class: "muted" }, "Names are labels you enter. Nothing authenticates them.")),
      tracker(view), gateCard(),
      view !== state.stage ? el("p", { class: "muted" }, `Viewing ${W.STAGES[view].name}. The current stage is ${W.STAGES[state.stage].name}.`) : null,
      body(), policyCard());
  }

  AIC.workflowUI = { panel };
})();
