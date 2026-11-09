// SPDX-License-Identifier: Apache-2.0
// "GRC" view inside the My scope tab: requirement-to-evidence mapping matrix, registers, coverage, KPIs/KRIs and the lifecycle.
// Runs locally on the same scope file as the command line (see site/grc.js).
"use strict";
(function () {
  const G = AIC.grc, W = AIC.workflow;
  const ACTOR_KEY = "aicontrols.actor.v1";
  const gui = { view: "dashboard", register: "documents", filter: { status: "", issue: "", framework: "", text: "" }, form: {}, open: null };
  let actor = "";
  try { actor = localStorage.getItem(ACTOR_KEY) || ""; } catch (e) { /* storage may be blocked */ }

  const ui = () => AIC.scopeUI;
  const scope = () => ui().scope, data = () => ui().data, sid = () => ui().sid;
  const human = (s) => String(s).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const val = (v) => (v === null || v === undefined ? "-" : String(v));
  const pctText = (v) => (v === null || v === undefined ? "-" : `${v}%`);
  const TABS = [["dashboard", "Dashboard"], ["matrix", "Mapping matrix"], ["registers", "Registers"], ["links", "Link & review"], ["settings", "Settings & roles"], ["open", "Open items"]];

  function act(fn, ok) {
    const a = actor.trim();
    if (!a) return ui().say("Enter who is acting (the “Acting as” field) before making a change.", "error");
    const out = ui().attempt(() => fn(a));
    if (out === false) return false;
    if (ok) ui().say(typeof ok === "function" ? ok(out) : ok, "ok");
    ui().render();
    return out;
  }
  function actorField() {
    return el("label", { class: "actor" }, "Acting as",
      el("input", { value: actor, placeholder: "your name", autocomplete: "name", "aria-describedby": "grc-actor-help",
        oninput: (e) => { actor = e.target.value; try { localStorage.setItem(ACTOR_KEY, actor); } catch (err) { /* ignore */ } } }),
      el("small", { id: "grc-actor-help", class: "muted" }, "Recorded with every change. Stored in this browser only."));
  }
  function tabs() {
    return el("div", { class: "subtabs", role: "group", "aria-label": "GRC views" }, TABS.map(([k, label]) =>
      el("button", { type: "button", "aria-pressed": String(gui.view === k), onclick: () => { gui.view = k; ui().render(); } }, label)));
  }
  const statusClass = (s) => ({ met: "effective", not_met: "ineffective", no_data: "stale", info: "requested", Implemented: "effective", Partial: "partially_effective",
    "Not started": "stale", Gap: "excepted", Unmapped: "ineffective" }[s] || "requested");
  const badge = (text, cls) => el("span", { class: `state ${cls || statusClass(text)}` }, human(text));
  const dl = (name, text, type) => ui().download(name, text, type);

  // ---- dashboard --------------------------------------------------------------------------------
  function dashboard() {
    const S = scope(), D = data(), id = sid();
    const life = G.lifecycle(S, D, id), kp = G.kpis(S, D, id), cov = G.coverage(S, D, id), st = G.streams(S, D, id), art = G.artifacts(S, D, id);
    const done = life.filter((l) => l.done).length;
    return [
      el("div", { class: "card" }, el("h3", {}, `Lifecycle: ${done} of ${life.length} steps in place`),
        el("p", { class: "muted" }, "Worked out from your data, never ticked by hand."),
        el("ol", { class: "grc-life" }, life.map((l) => el("li", {}, badge(l.done ? "Implemented" : "Not started"), " ", el("strong", {}, l.title), " ",
          el("span", { class: "muted" }, l.detail), !l.done && l.hint ? el("div", { class: "muted" }, `Next: ${l.hint}`) : null)))),
      el("div", { class: "card" }, el("h3", {}, "KPIs and KRIs"),
        el("div", { class: "scroll" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, ["Measure", "Type", "Value", "Target", "Status", "Detail"].map((h) => el("th", { scope: "col" }, h)))),
          el("tbody", {}, kp.map((k) => el("tr", {}, el("th", { scope: "row" }, k.name), el("td", {}, k.type), el("td", {}, k.value === null ? "-" : `${k.value}${k.unit === "%" ? "%" : ""}`),
            el("td", {}, k.target_text), el("td", {}, badge(k.status)), el("td", { class: "muted" }, k.detail))))))),
      el("div", { class: "card" }, el("h3", {}, "Coverage by framework"),
        el("p", { class: "muted" }, `Covered = requirement implemented and its control has current evidence. Anchor framework: ${cov.anchor || "none in this system"}.`),
        el("div", { class: "scroll" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, ["Framework", "Requirements", "Mapped", "Implemented", "Covered", "Coverage", "Target", "Reused from anchor"].map((h) => el("th", { scope: "col" }, h)))),
          el("tbody", {}, cov.frameworks.map((f) => el("tr", {}, el("th", { scope: "row" }, f.name), el("td", {}, f.required), el("td", {}, f.mapped), el("td", {}, f.implemented),
            el("td", {}, f.covered), el("td", {}, pctText(f.coverage_pct)), el("td", {}, f.target === null ? "-" : `${f.target}% ${f.meets_target ? "met" : "not met"}`),
            el("td", {}, f.incremental === null ? "-" : `${f.incremental} (${pctText(f.incremental_pct)})`))),
            el("tr", {}, el("th", { scope: "row" }, "All"), el("td", {}, cov.overall.required), el("td", {}), el("td", {}), el("td", {}, cov.overall.covered),
              el("td", {}, pctText(cov.overall.coverage_pct)), el("td", {}), el("td", {})))))),
      el("div", { class: "card" }, el("h3", {}, "ISO 42001 streams"),
        el("p", { class: "muted" }, "Every ISO 42001 requirement belongs to one of five streams, assigned by clause. The assignment is a documented judgement, not part of the standard."),
        st.some((s) => s.requirements) ? el("div", { class: "scroll" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, ["Stream", "Delivered through", "Requirements", "Mapped", "Implemented", "Covered"].map((h) => el("th", { scope: "col" }, h)))),
          el("tbody", {}, st.map((s) => el("tr", {}, el("th", { scope: "row" }, s.name), el("td", { class: "muted" }, s.delivered_through), el("td", {}, s.requirements),
            el("td", {}, s.mapped), el("td", {}, s.implemented), el("td", {}, s.covered)))))) : el("p", { class: "muted" }, "ISO 42001 is not in this system's frameworks.")),
      el("div", { class: "card" }, el("h3", {}, "Artifacts checklist"),
        el("ul", {}, art.map((a) => el("li", {}, badge(a.status), " ", el("strong", {}, a.title), " ", el("span", { class: "muted" }, a.detail))))),
      el("div", { class: "card" }, el("h3", {}, "Management report"),
        el("p", { class: "muted" }, "Generating the report records the date and a line in the audit trail."),
        el("div", { class: "row" }, el("button", { type: "button", class: "primary", onclick: () => act((a) => G.reportMarkdown(scope(), data(), sid(), a, true), "Report recorded.") }, "Record report"),
          el("button", { type: "button", onclick: () => dl(`${id}-grc-report.md`, G.reportMarkdown(S, D, id, "viewer", false), "text/markdown") }, "Download report (Markdown)")))];
  }

  // ---- matrix -----------------------------------------------------------------------------------
  function matrixView() {
    const S = scope(), D = data(), id = sid();
    const rows = G.matrix(S, D, id), sum = G.matrixSummary(rows), f = gui.filter;
    const fws = [...new Set(rows.map((r) => r.framework_id))];
    const shown = rows.filter((r) => (!f.status || r.status === f.status) && (!f.issue || r.issues.includes(f.issue)) && (!f.framework || r.framework_id === f.framework)
      && (!f.text || `${r.requirement_id} ${r.requirement} ${r.control_id} ${r.control_title}`.toLowerCase().includes(f.text.toLowerCase())));
    const sel = (label, key, opts) => el("label", {}, label, el("select", { onchange: (e) => { f[key] = e.target.value; ui().render(); } },
      el("option", { value: "" }, "All"), opts.map(([v, t]) => el("option", { value: v, selected: f[key] === v }, t))));
    const LIMIT = 200;
    return [
      el("div", { class: "card" }, el("h3", {}, "Requirement to control to evidence"),
        el("p", { class: "muted" }, "One row per applicable requirement. A requirement is Implemented only when its control has current evidence."),
        el("p", {}, Object.entries(sum.by_status).map(([k, n]) => el("span", { class: "tag" }, `${k}: ${n}`)), " ",
          Object.entries(sum.by_issue).map(([k, n]) => el("span", { class: "tag" }, `${G.ISSUE_TEXT[k]}: ${n}`))),
        el("div", { class: "row" },
          sel("Status", "status", ["Unmapped", "Gap", "Not started", "Partial", "Implemented"].map((x) => [x, x])),
          sel("Issue", "issue", Object.keys(G.ISSUE_TEXT).map((x) => [x, G.ISSUE_TEXT[x]])),
          sel("Framework", "framework", fws.map((x) => [x, x])),
          el("label", {}, "Search", el("input", { value: f.text, placeholder: "id, text or control", oninput: (e) => { f.text = e.target.value; clearTimeout(gui.t); gui.t = setTimeout(() => { ui().render(); const i = document.querySelector("#grc-search"); if (i) { i.focus(); i.setSelectionRange(f.text.length, f.text.length); } }, 250); }, id: "grc-search" }))),
        el("div", { class: "row" }, el("button", { type: "button", onclick: () => dl(`${id}-mapping-matrix.csv`, "﻿" + G.matrixCsv(S, D, id), "text/csv") }, "Download matrix (CSV)"))),
      el("div", { class: "scroll" }, el("table", { class: "grid ctl" },
        el("caption", { class: "muted" }, `${shown.length} of ${rows.length} requirements${shown.length > LIMIT ? `; showing the first ${LIMIT}. Filter, or download the CSV for all.` : ""}`),
        el("thead", {}, el("tr", {}, ["Requirement", "Clause", "Control", "Policy", "Guideline", "SOP", "Evidence", "Status", "Issues"].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", {}, shown.slice(0, LIMIT).map((r) => el("tr", {},
          el("th", { scope: "row" }, r.requirement_id, el("div", { class: "muted" }, r.requirement)), el("td", {}, r.clause),
          el("td", {}, r.control_id ? `${r.control_id} ${r.control_title}` : (r.gap_reason ? `Gap: ${r.gap_reason}` : "-")),
          el("td", {}, r.policy.join(", ") || "-"), el("td", {}, r.guideline.join(", ") || "-"), el("td", {}, r.sop.join(", ") || "-"),
          el("td", {}, r.evidence || "-"), el("td", {}, badge(r.status)),
          el("td", { class: "muted" }, r.issues.map((i) => G.ISSUE_TEXT[i]).join("; ") || "-"))))))];
  }

  // ---- registers --------------------------------------------------------------------------------
  function registersView() {
    const S = scope(), reg = gui.register, spec = G.SPEC.registers[reg];
    const recs = G.records(S, reg);
    const form = (gui.form[reg] = gui.form[reg] || {});
    const inputFor = (fld) => {
      const common = { id: `grc-${reg}-${fld.name}`, onchange: (e) => { form[fld.name] = e.target.value; }, oninput: (e) => { form[fld.name] = e.target.value; } };
      if (fld.kind === "enum") return el("select", common, el("option", { value: "" }, "Choose…"), fld.values.map((v) => el("option", { value: v, selected: form[fld.name] === v }, human(v))));
      return el("input", { ...common, value: form[fld.name] || "", type: fld.kind === "date" ? "date" : "text", inputmode: fld.kind === "int" ? "numeric" : null });
    };
    const cols = spec.fields.slice(0, 6);
    return [
      el("div", { class: "card" }, el("h3", {}, "Registers"),
        el("div", { class: "subtabs", role: "group", "aria-label": "Registers" }, Object.entries(G.SPEC.registers).map(([k, v]) =>
          el("button", { type: "button", "aria-pressed": String(reg === k), onclick: () => { gui.register = k; ui().render(); } }, `${v.title} (${G.records(S, k).length})`))),
        reg === "evidence_sources" ? el("div", { class: "row" }, el("button", { type: "button", onclick: () => act((a) => G.seedEvidenceSources(scope(), a), (n) => `${n} standard evidence source(s) added.`) }, "Add the standard evidence sources")) : null),
      el("div", { class: "card" }, el("h3", {}, `Add ${spec.singular}`),
        spec.fields.map((fld) => el("label", {}, fld.label + (fld.required ? " (required)" : ""), inputFor(fld))),
        el("div", { class: "row" }, el("button", { type: "button", class: "primary", onclick: () => {
          const fields = {}; for (const [k, v] of Object.entries(form)) if (v !== "" && v != null) fields[k] = v;
          if (act((a) => G.add(scope(), reg, a, fields), (r) => `Added ${r.id}.`) !== false && actor.trim()) gui.form[reg] = {};
          ui().render();
        } }, `Add ${spec.singular}`))),
      el("div", { class: "scroll" }, el("table", { class: "grid" },
        el("caption", { class: "muted" }, `${recs.length} ${spec.singular}${recs.length === 1 ? "" : "s"}`),
        el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "ID"), cols.map((c) => el("th", { scope: "col" }, c.label)), el("th", { scope: "col" }, "Actions"))),
        el("tbody", {}, recs.map((r) => el("tr", {}, el("th", { scope: "row" }, r.id), cols.map((c) => el("td", {}, val(r[c.name]))),
          el("td", {}, el("button", { type: "button", class: "ghost danger", "aria-label": `Remove ${r.id}`, onclick: () => {
            if (confirm(`Remove ${r.id}? It will also be unlinked from any control.`)) act((a) => G.remove(scope(), reg, a, r.id), `Removed ${r.id}.`);
          } }, "Remove")))))))];
  }

  // ---- link & review ----------------------------------------------------------------------------
  function linksView() {
    const S = scope(), D = data(), id = sid();
    if (!W.enabled(S, id)) return el("div", { class: "card" }, el("p", {}, "Controls are the common controls from the Workflow tab. Enable the workflow and group requirements into common controls first, then come back to link policies, SOPs and evidence."));
    const ccs = Object.values(W.state(S, id).common_controls);
    if (!ccs.length) return el("div", { class: "card" }, el("p", {}, "No common controls yet. Create them in the Workflow tab (Harmonise)."));
    const docs = G.records(S, "documents"), srcs = G.records(S, "evidence_sources");
    const rows = G.matrix(S, D, id);
    return ccs.map((cc) => {
      const mine = rows.filter((r) => r.control_id === cc.id);
      const picked = {};
      const picker = (cat, list) => el("label", {}, `${human(cat)} documents`, el("select", { multiple: true, "aria-label": `${cc.id} ${cat}`, size: Math.min(4, Math.max(2, list.length)), onchange: (e) => { picked[cat] = [...e.target.selectedOptions].map((o) => o.value); } },
        list.map((d) => el("option", { value: d.id, selected: (cc.documents && (cc.documents[cat] || []).includes(d.id)) || null }, `${d.id} ${d.title}`))));
      const picker2 = el("label", {}, "Evidence sources", el("select", { multiple: true, "aria-label": `${cc.id} evidence sources`, size: Math.min(4, Math.max(2, srcs.length)), onchange: (e) => { picked.ev = [...e.target.selectedOptions].map((o) => o.value); } },
        srcs.map((s) => el("option", { value: s.id, selected: (cc.evidence_sources || []).includes(s.id) || null }, `${s.id} ${s.type} (${s.source})`))));
      const reviewed = mine.find((r) => r.mapping_reviewed);
      return el("div", { class: "card", id: `grc-cc-${cc.id}` }, el("h3", {}, `${cc.id} ${cc.title}`),
        el("p", { class: "muted" }, `${mine.length} requirement(s) mapped. Mapping owner: ${(mine[0] && mine[0].mapping_owner) || "none"}. Last reviewed: ${reviewed ? reviewed.mapping_reviewed : "never"}.`),
        el("div", { class: "row" }, ["policy", "guideline", "sop"].map((c) => picker(c, docs.filter((d) => d.type === c))), picker2),
        el("div", { class: "row" },
          el("button", { type: "button", class: "primary", onclick: () => {
            // The picker shows what is linked now; saving sets the links to exactly the selection.
            const want = {}; for (const c of ["policy", "guideline", "sop"]) want[c] = picked[c] || (cc.documents ? [...(cc.documents[c] || [])] : []);
            const ev = picked.ev || [...(cc.evidence_sources || [])];
            act((a) => {
              const cur = W.cc(scope(), sid(), cc.id);
              const have = { policy: [...((cur.documents || {}).policy || [])], guideline: [...((cur.documents || {}).guideline || [])], sop: [...((cur.documents || {}).sop || [])] };
              const drop = {}, add = {};
              for (const c of ["policy", "guideline", "sop"]) { drop[c] = have[c].filter((x) => !want[c].includes(x)); add[c] = want[c].filter((x) => !have[c].includes(x)); }
              const haveEv = [...(cur.evidence_sources || [])];
              const dropEv = haveEv.filter((x) => !ev.includes(x)), addEv = ev.filter((x) => !haveEv.includes(x));
              if (drop.policy.length || drop.guideline.length || drop.sop.length || dropEv.length) G.link(scope(), sid(), a, cc.id, { ...drop, evidence_sources: dropEv, unlink: true });
              if (add.policy.length || add.guideline.length || add.sop.length || addEv.length) G.link(scope(), sid(), a, cc.id, { ...add, evidence_sources: addEv });
            }, `Links saved for ${cc.id}.`);
          } }, "Save links"),
          el("button", { type: "button", onclick: () => {
            const owner = document.getElementById(`grc-owner-${cc.id}`).value;
            act((a) => G.reviewMappings(scope(), sid(), a, cc.id, owner, null), `Mapping for ${cc.id} marked as reviewed today.`);
          } }, "Mark mapping reviewed today"),
          el("label", { class: "inline" }, "Mapping owner", el("input", { id: `grc-owner-${cc.id}`, value: (mine[0] && mine[0].mapping_owner) || "", placeholder: "name" }))));
    });
  }

  // ---- settings & roles -------------------------------------------------------------------------
  function settingsView() {
    const S = scope(), D = data(), id = sid();
    const st = G.settings(S), fws = S_system().frameworks;
    const apply = (key, input) => act((a) => G.setSetting(scope(), data(), a, key, document.getElementById(input).value), "Setting saved.");
    const row = (label, key, control, inputId) => el("div", { class: "row" }, el("label", {}, label, control), el("button", { type: "button", onclick: () => apply(key, inputId) }, "Save"));
    const fwName = (f) => (D.frameworks.find((x) => x.id === f) || { name: f }).name;
    return [
      el("div", { class: "card" }, el("h3", {}, "Settings"),
        row("Anchor framework", "anchor_framework", el("select", { id: "grc-anchor" }, fws.map((f) => el("option", { value: f, selected: st.anchor_framework === f }, fwName(f)))), "grc-anchor"),
        row("Risk appetite", "risk_appetite", el("select", { id: "grc-appetite" }, ["low", "moderate", "high"].map((v) => el("option", { value: v, selected: st.risk_appetite === v }, human(v)))), "grc-appetite"),
        row("Review mappings every (months)", "mapping_review_months", el("input", { id: "grc-mm", value: st.mapping_review_months, inputmode: "numeric" }), "grc-mm"),
        row("Review scope every (months)", "scope_review_months", el("input", { id: "grc-sm", value: st.scope_review_months, inputmode: "numeric" }), "grc-sm"),
        el("h4", {}, "Coverage targets (%)"),
        fws.map((f) => row(fwName(f), `coverage_target.${f}`, el("input", { id: `grc-t-${f}`, value: (st.coverage_targets || {})[f] ?? "", placeholder: "none", inputmode: "numeric" }), `grc-t-${f}`))),
      el("div", { class: "card" }, el("h3", {}, "Scope statements"),
        el("p", { class: "muted" }, "Say in a sentence what is in scope for each framework. Marking it reviewed today starts the review clock."),
        fws.map((f) => {
          const cur = ((S.grc || {}).framework_scopes || {})[f] || {};
          return el("div", {}, el("label", {}, `${fwName(f)} (last reviewed ${cur.reviewed || "never"})`, el("textarea", { id: `grc-ss-${f}`, rows: "2" }, cur.statement || "")),
            el("button", { type: "button", onclick: () => act((a) => G.setScopeStatement(scope(), data(), a, f, document.getElementById(`grc-ss-${f}`).value, null), "Scope statement saved.") }, "Save statement"));
        }),
        el("div", { class: "row" }, el("button", { type: "button", onclick: () => act((a) => G.reviewScope(scope(), a, null), "Scope marked as reviewed today.") }, "Mark the whole scope reviewed today"))),
      el("div", { class: "card" }, el("h3", {}, "Roles"),
        el("p", { class: "muted" }, "Who plays each GRC role. Names are labels only. Nothing authenticates them."),
        G.roles(S).map((r) => el("div", {}, el("label", {}, `${r.name}: ${r.responsibility}`, el("input", { id: `grc-r-${r.id}`, value: r.people.join(", "), placeholder: "names, comma separated" })),
          el("button", { type: "button", onclick: () => act((a) => G.setRoles(scope(), a, r.id, document.getElementById(`grc-r-${r.id}`).value.split(",").map((x) => x.trim()).filter(Boolean)), "Roles saved.") }, "Save"))))];
  }
  const S_system = () => scope().systems.find((s) => s.id === sid());

  function openItems() {
    return el("div", { class: "card" }, el("h3", {}, "Points in the source note that were unclear"),
      el("p", { class: "muted" }, "These were not guessed silently. Each says how this tool treats it, so you can confirm or change it."),
      el("ol", {}, G.SPEC.open_items.map((o) => el("li", {}, o.text, el("div", { class: "muted" }, `Handled: ${o.handled}`)))));
  }

  function panel() {
    const body = { dashboard, matrix: matrixView, registers: registersView, links: linksView, settings: settingsView, open: openItems }[gui.view]();
    return el("div", { class: "grc" },
      el("div", { class: "card actorbar" }, actorField(), el("p", { class: "muted" }, "Planning aid for your governance records. Not legal or audit advice.")),
      tabs(), body);
  }
  AIC.grcUI = { panel };
})();
