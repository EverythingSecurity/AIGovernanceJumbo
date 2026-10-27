// SPDX-License-Identifier: Apache-2.0
// "My scope" tab: the scoping layer in the browser. Everything runs locally: the scope lives in
// this browser's localStorage and in files you download or import. Nothing is sent anywhere.
"use strict";
(function () {
  const W = AIC.wizard, S = AIC.scope;
  const KEY = "aicontrols.scope.v1";
  const CHOICE_LABEL = { yes: "Yes", no: "No", unsure: "Not sure", provider: "Provider", deployer: "Deployer", both: "Both",
    iso42001: "ISO/IEC 42001", iso27001: "ISO/IEC 27001", none: "None" };
  const STATUS_LABEL = { not_started: "Not started", in_progress: "In progress", implemented: "Implemented", verified: "Verified" };
  const PAGE_ROWS = 60;

  let data = null, scope = null, root = null;
  let storageOk = true, dirty = false;
  const ui = { screen: "intro", sid: null, sub: "overview", planTop: 10, planMin: 1, open: null, wiz: null,
    f: { q: "", fw: "", dom: "", st: "", owner: "", late: false, shown: PAGE_ROWS }, msg: null };

  // ---- persistence -------------------------------------------------------
  function loadSaved() {
    try { const t = localStorage.getItem(KEY); return t ? JSON.parse(t) : null; } catch (e) { storageOk = false; return null; }
  }
  function persist() {
    dirty = true;
    try { localStorage.setItem(KEY, JSON.stringify(scope)); storageOk = true; } catch (e) { storageOk = false; }
  }
  function say(text, kind, report) { ui.msg = text ? { text, kind: kind || "info" } : null; ui.report = text && report && report.length ? report : null; const m = document.getElementById("scope-msg"); if (m) paintMsg(m); }
  function paintMsg(node) {
    node.className = "scope-msg" + (ui.msg ? " " + ui.msg.kind : "");
    node.textContent = ui.msg ? ui.msg.text : "";
  }
  // Run a change; report validation problems instead of throwing into the console.
  function attempt(fn) {
    try { const out = fn(); persist(); return out === undefined ? true : out; }
    catch (e) {
      if (e instanceof S.ScopeError || e instanceof W.WizardError) { say(e.message, "error"); return false; }
      throw e;
    }
  }

  const slug = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "system";
  const fwName = (id) => S.index(data).fw[id].name;
  const sys = () => S.system(scope, ui.sid);

  // ---- download / import -------------------------------------------------
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = el("a", { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function importFile(file) {
    const text = await file.text();
    const looksJson = text.trimStart().startsWith("{");
    if (/\.csv$/i.test(file.name) || (!looksJson && text.includes(","))) return importCsv(text);
    let parsed;
    try { parsed = JSON.parse(text); } catch (e) { return say("That file is neither a valid JSON scope file nor a CSV spreadsheet.", "error"); }
    const { errors, warnings } = S.validate(parsed, data);
    if (!errors.length && AIC.workflow) {  // also check the workflow layer (hash chain, mappings, exceptions)
      const wv = AIC.workflow.validate(parsed, data);
      errors.push(...wv.errors); warnings.push(...wv.warnings);
    }
    if (errors.length) {
      return say(`Cannot import: ${errors.length} problem(s). First: ${errors.slice(0, 3).join("; ")}`, "error");
    }
    if (scope && scope.systems.length && !confirm("Replace the scope currently in this browser with the imported file?")) return;
    scope = parsed; ui.sid = scope.systems[0] ? scope.systems[0].id : null;
    ui.screen = ui.sid ? "workspace" : "intro"; ui.sub = "overview"; ui.open = null;
    persist(); dirty = false;
    say(`Imported ${scope.systems.length} system(s).` + (warnings.length ? " Warning: " + warnings[0] : ""), warnings.length ? "warn" : "ok");
    render();
  }
  // A filled-in decisions spreadsheet (see "Download template"). All or nothing: a problem in any row means no change.
  function importCsv(text) {
    const rows = S.parseCsv(text);
    const head = (rows.find((r) => !r[0].trimStart().startsWith("#")) || []).map((c) => c.trim().toLowerCase().replace(/\s+/g, "_"));
    const hasSystemColumn = head.includes("system") || head.includes("system_id");
    const res = S.applyDecisionsCsv(scope, data, text, { systemId: hasSystemColumn ? null : ui.sid });
    if (res.errors.length) {
      const lines = res.errors.slice(0, 25).map((e) => (e.row ? `Row ${e.row}: ${e.message}` : e.message));
      if (res.errors.length > 25) lines.push(`... and ${res.errors.length - 25} more`);
      say(`Cannot import this spreadsheet: ${res.errors.length} problem(s). Nothing was changed. Fix the cells below and import it again.`, "error", lines);
      return render();
    }
    scope = res.scope; ui.sid = res.system; ui.screen = "workspace"; ui.sub = "overview"; ui.open = null;
    persist();
    const name = S.system(scope, res.system).name;
    say(`Imported into “${name}”${res.created_system ? " (new system)" : ""}: ${res.applied} control(s) updated, ${res.skipped} unchanged.`, res.warnings.length ? "warn" : "ok", res.warnings);
    render();
  }
  function pickFile() {
    const input = el("input", { type: "file", accept: ".json,.csv,application/json,text/csv", class: "sr-only", onchange: (e) => { if (e.target.files[0]) importFile(e.target.files[0]); input.remove(); } });
    document.body.append(input); input.click();
  }

  // ---- shared bits ---------------------------------------------------------
  function bar(pct) {
    return el("span", { class: "meter", role: "img", "aria-label": pct === null ? "no applicable controls" : `${pct}% done` },
      el("span", { class: "meter-fill", style: `width:${pct || 0}%` }));
  }
  const pctText = (p) => (p === null ? "n/a" : `${p.toFixed(1)}%`);
  const chip = (t) => el("span", { class: "tag" }, t);

  // ---- intro -----------------------------------------------------------------
  function introScreen() {
    return el("div", { class: "card intro" },
      el("h2", {}, "Scope your own governance work"),
      el("p", {}, "Answer a few questions about an AI system to get suggested frameworks, then track which controls apply, who owns them, and how far along they are. You get a plan by workstream and a Statement of Applicability draft."),
      el("p", { class: "privacy" }, el("strong", {}, "Private by design. "), "Everything stays in this browser. Nothing is uploaded. Download your scope file to keep or share it; it also works with the aicontrols command line."),
      el("div", { class: "row" },
        el("button", { type: "button", class: "primary", onclick: () => startWizard() }, "Start the wizard"),
        el("button", { type: "button", class: "ghost", onclick: pickFile }, "Import a scope file or spreadsheet")),
      templateBuilder(),
      el("p", { class: "muted" }, "A planning aid, not legal advice or a compliance verdict."));
  }
  // A fill-in spreadsheet for people who would rather work in Excel or Sheets than answer the wizard.
  function templateBuilder() {
    const chosen = new Set();
    let org, name;
    const make = () => {
      if (!chosen.size) return say("Tick at least one framework for the template.", "error");
      const sysName = name.value.trim() || "My AI system";
      const csv = attempt(() => S.templateCsv(data, [...chosen], org.value.trim() || "My organisation", slug(sysName), sysName, null));
      if (csv === false || csv === true) return;
      download("aicontrols-decisions-template.csv", "\ufeff" + csv, "text/csv");  // BOM: Excel then reads it as UTF-8
      say("Template downloaded. Fill in the decision columns, save as CSV, then import it here.", "ok");
    };
    return el("details", { class: "template-box" },
      el("summary", {}, "Prefer a spreadsheet? Download a template to fill in"),
      el("p", { class: "muted" }, "Pick the frameworks that apply. You get a CSV with one row per control and blank columns for the decision (yes or no, with a justification for no), status, owner, due date and evidence. Fill it in with Excel or Sheets, save it as CSV, then use “Import a scope file or spreadsheet”. A wrong cell is reported by row, and nothing is imported until the file is clean."),
      el("div", { class: "grid2" },
        el("label", {}, "Organisation", org = el("input", { placeholder: "e.g. Acme Retail" })),
        el("label", {}, "AI system name", name = el("input", { placeholder: "e.g. Customer support chatbot" }))),
      el("div", { class: "fwgrid" }, data.frameworks.map((f) => el("label", { class: "fwbox" },
        el("input", { type: "checkbox", onchange: (e) => { e.target.checked ? chosen.add(f.id) : chosen.delete(f.id); if (ui.msg && ui.msg.kind === "error") say(null); } }), ` ${f.name} (${f.control_count})`))),
      el("button", { type: "button", class: "ghost", onclick: make }, "Download template (CSV)"));
  }

  // ---- wizard ------------------------------------------------------------------
  function startWizard(prefill) {
    ui.wiz = { phase: "form", answers: Object.assign({}, prefill || {}), recs: null, included: new Set(), name: "", desc: "",
      org: scope ? scope.organization : "" };
    ui.screen = "wizard"; ui.open = null; say(null); render();
  }
  function wizardForm() {
    const w = ui.wiz;
    return el("form", { class: "card wizard", onsubmit: (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const org = String(fd.get("org") || "").trim();
      if (!org) return say("Please enter an organisation name.", "error");
      for (const q of W.QUESTIONS) w.answers[q.id] = fd.get(q.id) || "unsure";
      w.org = org; w.name = String(fd.get("name") || "").trim(); w.desc = String(fd.get("desc") || "").trim();
      if (!w.name) return say("Please name the AI system.", "error");
      w.recs = W.recommend(w.answers, data.frameworks);
      w.included = new Set(W.selection(w.recs, "recommended"));
      w.phase = "results"; say(null); render(); window.scrollTo({ top: 0 });
    } },
      el("h2", {}, "Describe the AI system"),
      el("p", { class: "muted" }, "Not sure? Leave it on “Not sure”. The wizard then keeps the framework in view instead of ruling it out."),
      el("div", { class: "grid2" },
        el("label", {}, "Organisation", el("input", { name: "org", value: w.org, required: true, autocomplete: "organization" })),
        el("label", {}, "AI system name", el("input", { name: "name", value: w.name, required: true, placeholder: "e.g. Customer support chatbot" }))),
      el("label", {}, "Short description (optional)", el("input", { name: "desc", value: w.desc })),
      W.QUESTIONS.map((q, i) => el("fieldset", { class: "q" },
        el("legend", {}, `${i + 1}. ${q.text}`),
        el("div", { class: "choices" }, q.choices.map((c) => el("label", { class: "choice" },
          el("input", { type: "radio", name: q.id, value: c, checked: (w.answers[q.id] || "unsure") === c }), " ", CHOICE_LABEL[c] || c))),
        q.help ? el("p", { class: "help" }, q.help) : null)),
      el("div", { class: "row" },
        el("button", { type: "submit", class: "primary" }, "Suggest frameworks"),
        scope && scope.systems.length ? el("button", { type: "button", class: "ghost", onclick: () => { ui.screen = "workspace"; say(null); render(); } }, "Cancel") : null));
  }
  function wizardResults() {
    const w = ui.wiz;
    const summary = el("p", { class: "sum", "aria-live": "polite" });
    const ix = S.index(data);
    const paint = () => {
      const n = [...w.included].reduce((a, id) => a + ix.fw[id].control_count, 0);
      summary.textContent = `${w.included.size} framework(s) selected, about ${n} controls in scope.`;
    };
    paint();
    const groups = W.LEVELS.map((lvl) => {
      const list = w.recs.filter((r) => r.level === lvl);
      if (!list.length) return null;
      return el("section", { class: "tier " + lvl },
        el("h3", {}, `${W.LEVEL_TEXT[lvl]} (${list.length})`),
        list.map((r) => el("label", { class: "rec" },
          el("input", { type: "checkbox", checked: w.included.has(r.framework_id), onchange: (e) => { e.target.checked ? w.included.add(r.framework_id) : w.included.delete(r.framework_id); paint(); } }),
          el("span", { class: "rec-body" },
            el("span", { class: "rec-head" }, el("strong", {}, r.name), " ", chip(r.kind), " ", el("span", { class: "muted" }, `${r.controls} controls`)),
            el("ul", {}, r.reasons.map((t) => el("li", {}, t)))))));
    });
    const any = w.recs.some((r) => r.caveat);
    return el("div", { class: "card wizard" },
      el("h2", {}, `Suggested frameworks for ${w.name}`),
      el("p", { class: "muted" }, "Based on your answers; a planning aid, not legal advice. Tick or untick to adjust before creating the system."),
      groups,
      any ? el("p", { class: "caveat" }, "! " + W.REGULATION_CAVEAT) : null,
      summary,
      el("div", { class: "row" },
        el("button", { type: "button", class: "primary", onclick: createFromWizard }, "Create system"),
        el("button", { type: "button", class: "ghost", onclick: () => { w.phase = "form"; render(); } }, "Back to questions")));
  }
  function createFromWizard() {
    const w = ui.wiz;
    if (!w.included.size) return say("Select at least one framework.", "error");
    if (!scope) scope = S.newScope(w.org, data);
    else if (!scope.systems.length) scope.organization = w.org;
    let id = slug(w.name), n = 2;
    while (scope.systems.some((s) => s.id === id)) id = `${slug(w.name)}-${n++}`;
    const chosen = [...w.included];
    const level = sameSet(chosen, W.selection(w.recs, "recommended")) ? "recommended"
      : sameSet(chosen, W.selection(w.recs, "consider")) ? "consider" : "custom";
    const ok = attempt(() => S.addSystem(scope, data, { id, name: w.name, description: w.desc, frameworks: chosen,
      scoping: { date: S.today(), answers: W.normalize(w.answers), include_level: level, included: chosen,
        note: "Suggested by the aicontrols scoping wizard; a planning aid, not a legal determination." } }));
    if (!ok) return;
    ui.sid = id; ui.screen = "workspace"; ui.sub = "overview"; ui.wiz = null;
    say(`Created “${w.name}”. Next: give each workstream an owner.`, "ok"); render();
  }
  const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

  // ---- workspace chrome ------------------------------------------------------------
  function workspaceBar() {
    return el("div", { class: "card wsbar" },
      el("label", {}, "Organisation", el("input", { value: scope.organization, onchange: (e) => { scope.organization = e.target.value.trim() || scope.organization; persist(); } })),
      el("label", {}, "System", el("select", { onchange: (e) => { ui.sid = e.target.value; ui.open = null; ui.f = { q: "", fw: "", dom: "", st: "", owner: "", late: false, shown: PAGE_ROWS }; render(); } },
        scope.systems.map((s) => el("option", { value: s.id, selected: s.id === ui.sid }, s.name)))),
      el("div", { class: "row" },
        el("button", { type: "button", class: "ghost", onclick: () => startWizard() }, "New system"),
        el("button", { type: "button", class: "ghost", onclick: pickFile }, "Import"),
        el("button", { type: "button", class: "ghost danger", onclick: () => {
          if (!confirm("Remove ALL scope data from this browser? Download your scope file first if you want to keep it.")) return;
          try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
          scope = null; ui.sid = null; ui.screen = "intro"; dirty = false; say("Scope data removed from this browser.", "ok"); render();
        } }, "Reset")),
      el("p", { class: "muted save" }, storageOk
        ? (dirty ? "Saved in this browser. You have changes not yet downloaded." : "Saved in this browser.")
        : "Your browser blocked local storage: changes are kept only until you close this tab. Download your scope file."));
  }
  function subTabs() {
    return el("div", { class: "subtabs", role: "group", "aria-label": "Scope views" },
      ["overview", "controls", "workflow", "export"].map((k) => el("button", { type: "button", "aria-pressed": String(ui.sub === k), onclick: () => { ui.sub = k; ui.open = null; render(); } },
        { overview: "Overview & plan", controls: "Controls", workflow: "Workflow", export: "Export" }[k])));
  }

  // ---- overview --------------------------------------------------------------------------
  function overviewPanel() {
    const s = sys(), ix = S.index(data);
    const o = S.overall(scope, data, s.id);
    const plan = S.plan(scope, data, s.id);
    const late = plan.reduce((a, p) => a + p.overdue, 0);
    const unowned = plan.filter((p) => !p.owners.length).length;
    const kpi = (v, l) => el("div", { class: "kpi" }, el("div", { class: "kpi-v" }, v), el("div", { class: "kpi-l" }, l));
    const shown = plan.filter((p) => p.frameworks >= ui.planMin).slice(0, ui.planTop || plan.length);
    return el("div", {},
      el("div", { class: "kpis" }, kpi(String(o.total), "controls in scope"), kpi(String(o.applicable), "applicable"),
        kpi(pctText(o.percent), "done"), kpi(String(late), "overdue"), kpi(`${unowned} of ${plan.length}`, "workstreams without owner")),
      el("div", { class: "card" }, el("h3", {}, "By framework"),
        el("div", { class: "scroll" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, ["Framework", "Controls", "Applicable", "Not applicable", "Done", ""].map((h) => el("th", { scope: "col" }, h)))),
          el("tbody", {}, S.status(scope, data, s.id, "framework").map((r) => el("tr", {},
            el("th", { scope: "row" }, r.label), el("td", {}, r.total), el("td", {}, r.applicable), el("td", {}, r.not_applicable),
            el("td", {}, pctText(r.percent)), el("td", {}, bar(r.percent)))))))),
      el("div", { class: "card" },
        el("h3", {}, "Workstreams (one per domain, most-shared first)"),
        el("p", { class: "muted" }, "A domain groups controls from different frameworks that one programme can usually satisfy. Give each workstream one owner; the owner is applied to every control in it. Marking one control done never completes related ones: review them."),
        el("div", { class: "row filters-inline" },
          el("label", {}, "Show", el("select", { onchange: (e) => { ui.planTop = Number(e.target.value); render(); } },
            [[5, "top 5"], [10, "top 10"], [0, "all"]].map(([v, l]) => el("option", { value: v, selected: ui.planTop === v }, l)))),
          el("label", {}, "Shared by at least", el("select", { onchange: (e) => { ui.planMin = Number(e.target.value); render(); } },
            [1, 2, 3, 4].map((v) => el("option", { value: v, selected: ui.planMin === v }, `${v} framework${v > 1 ? "s" : ""}`))))),
        el("div", { class: "scroll" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, ["Workstream", "Frameworks", "Controls", "Done", "", "Owner", "Next due", "Late"].map((h) => el("th", { scope: "col" }, h)))),
          el("tbody", {}, shown.map((p) => el("tr", {},
            el("th", { scope: "row" }, el("button", { type: "button", class: "link", onclick: () => { ui.sub = "controls"; ui.f = { q: "", fw: "", dom: p.domain_id, st: "", owner: "", late: false, shown: PAGE_ROWS }; render(); } }, p.domain)),
            el("td", {}, p.frameworks), el("td", {}, p.total), el("td", {}, pctText(p.percent)), el("td", {}, bar(p.percent)),
            el("td", {}, el("input", { class: "cell", "aria-label": `Owner for ${p.domain}`, value: p.owners.length === 1 ? p.owners[0] : "", placeholder: p.owners.length > 1 ? "several: " + p.owners.join(", ") : "assign owner",
              onchange: (e) => {
                const ids = S.inScope(scope, data, s.id).filter((c) => c.domain_id === p.domain_id).map((c) => c.id);
                const v = e.target.value.trim();
                if (attempt(() => S.setDecisions(scope, data, s.id, ids, { owner: v || null }, { allowClear: true }))) { say(`Owner ${v ? "set to " + v : "cleared"} for ${ids.length} control(s) in “${p.domain}”.`, "ok"); render(); }
              } })),
            el("td", {}, p.next_due || ""), el("td", {}, p.overdue ? el("strong", {}, String(p.overdue)) : ""))))))),
      frameworksEditor());
  }
  function frameworksEditor() {
    const s = sys(), ix = S.index(data);
    const sc = s.scoping;
    const boxes = data.frameworks.map((f) => el("label", { class: "fwbox" }, el("input", { type: "checkbox", value: f.id, checked: s.frameworks.includes(f.id) }), ` ${f.name} (${f.control_count})`));
    return el("details", { class: "card" },
      el("summary", {}, "Frameworks and scoping basis for this system"),
      el("div", { class: "fwgrid" }, boxes),
      el("div", { class: "row" },
        el("button", { type: "button", class: "ghost", onclick: (e) => {
          const next = [...e.target.closest("details").querySelectorAll("input[type=checkbox]")].filter((b) => b.checked).map((b) => b.value);
          let drop = 0; try { drop = S.setFrameworks(scope, data, s.id, next, true); } catch (err) { return say(err.message, "error"); }
          if (drop && !confirm(`${drop} saved decision(s) belong to frameworks you removed and will be deleted. Continue?`)) return;
          if (attempt(() => S.setFrameworks(scope, data, s.id, next))) { say("Frameworks updated.", "ok"); render(); }
        } }, "Apply framework changes"),
        el("button", { type: "button", class: "ghost", onclick: () => startWizard(sc ? sc.answers : null) }, "Re-run the wizard as a new system"),
        el("button", { type: "button", class: "ghost danger", onclick: () => {
          if (!confirm(`Delete “${s.name}” and all its decisions?`)) return;
          S.removeSystem(scope, s.id); persist();
          ui.sid = scope.systems[0] ? scope.systems[0].id : null; ui.screen = ui.sid ? "workspace" : "intro"; render();
        } }, "Delete this system")),
      sc ? el("div", {}, el("h4", {}, `Scoping basis (${sc.date || "undated"}; ${sc.include_level || "custom"} tier)`),
        el("p", { class: "muted" }, sc.note || ""),
        el("dl", { class: "answers" }, Object.entries(sc.answers || {}).flatMap(([k, v]) => [el("dt", {}, (W.QUESTIONS.find((q) => q.id === k) || { text: k }).text), el("dd", {}, CHOICE_LABEL[v] || v)])))
        : el("p", { class: "muted" }, "No wizard answers recorded for this system."));
  }

  // ---- controls --------------------------------------------------------------------------
  function filteredRows() {
    const s = sys(), f = ui.f, words = f.q.trim().toLowerCase().split(/\s+/).filter(Boolean), t = S.today();
    return S.rows(scope, data, s.id).filter(([c, d]) => {
      if (f.fw && c.framework_id !== f.fw) return false;
      if (f.dom && c.domain_id !== f.dom) return false;
      if (f.st === "na" ? d.applicable : (f.st && (!d.applicable || d.status !== f.st))) return false;
      if (f.owner === "none" ? d.owner : (f.owner && (d.owner || "") !== f.owner)) return false;
      if (f.late && !(d.applicable && !S.DONE.includes(d.status) && d.due && d.due < t)) return false;
      if (words.length) { const hay = `${c.id} ${c.title} ${c.requirement}`.toLowerCase(); if (!words.every((w) => hay.includes(w))) return false; }
      return true;
    });
  }
  function controlsPanel() {
    const s = sys(), ix = S.index(data), f = ui.f;
    const all = filteredRows();
    const owners = [...new Set(S.rows(scope, data, s.id).map(([, d]) => d.owner).filter(Boolean))].sort();
    const sel = (key, opts, label) => el("label", {}, label, el("select", { onchange: (e) => { f[key] = e.target.value; f.shown = PAGE_ROWS; render(); } },
      opts.map(([v, l]) => el("option", { value: v, selected: f[key] === v }, l))));
    const domainsInScope = [...new Set(S.inScope(scope, data, s.id).map((c) => c.domain_id))];
    const counter = el("p", { class: "muted", "aria-live": "polite" }, `${all.length} control(s) match`);
    const tbody = el("tbody", {}, all.slice(0, f.shown).map(([c, d]) => rowFor(c, d, counter)));
    return el("div", { class: "split controls" },
      el("div", {},
        el("div", { class: "card filters-inline" },
          el("label", { class: "grow" }, "Search", el("input", { type: "search", value: f.q, placeholder: "title, id or requirement", oninput: (e) => { clearTimeout(ui._t); ui._t = setTimeout(() => { f.q = e.target.value; f.shown = PAGE_ROWS; render(); const i = document.querySelector("#scope-root input[type=search]"); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }, 250); } })),
          sel("fw", [["", "All frameworks"], ...s.frameworks.map((id) => [id, fwName(id)])], "Framework"),
          sel("dom", [["", "All domains"], ...domainsInScope.map((id) => [id, ix.dom[id].name]).sort((a, b) => (a[1] < b[1] ? -1 : 1))], "Domain"),
          sel("st", [["", "Any status"], ...S.STATUSES.map((k) => [k, STATUS_LABEL[k]]), ["na", "Not applicable"]], "Status"),
          sel("owner", [["", "Any owner"], ["none", "No owner"], ...owners.map((o) => [o, o])], "Owner"),
          el("label", { class: "inline" }, el("input", { type: "checkbox", checked: f.late, onchange: (e) => { f.late = e.target.checked; render(); } }), " Overdue only"),
          el("button", { type: "button", class: "ghost", onclick: () => { ui.f = { q: "", fw: "", dom: "", st: "", owner: "", late: false, shown: PAGE_ROWS }; render(); } }, "Clear filters")),
        bulkBar(all),
        counter,
        el("div", { class: "scroll" }, el("table", { class: "grid ctl" },
          el("thead", {}, el("tr", {}, ["Control", "Applies", "Status", "Owner", "Due"].map((h) => el("th", { scope: "col" }, h)))), tbody)),
        all.length > f.shown ? el("button", { type: "button", class: "ghost", onclick: () => { f.shown += PAGE_ROWS; render(); } }, `Show more (${all.length - f.shown} left)`) : null),
      drawer());
  }
  function rowFor(c, d, counter) {
    const s = sys(), id = c.id;
    const upd = (changes, opts) => { if (attempt(() => S.setDecisions(scope, data, s.id, [id], changes, opts))) { if (ui.f.st || ui.f.late || ui.f.owner) render(); return true; } render(); return false; };
    return el("tr", { class: ui.open === id ? "open" : "" },
      el("th", { scope: "row" }, el("button", { type: "button", class: "link", onclick: () => { ui.open = id; ui.na = false; render(); focusDrawer(); } }, c.title), el("div", { class: "r-id" }, id)),
      el("td", {}, el("input", { type: "checkbox", "aria-label": `Applicable: ${c.title}`, checked: d.applicable, onchange: (e) => {
        if (e.target.checked) return upd({ applicable: true });
        e.target.checked = true; ui.open = id; ui.na = true; say("Add a justification and save to mark this control not applicable.", "info"); render(); focusDrawer();
      } })),
      el("td", {}, el("select", { "aria-label": `Status: ${c.title}`, disabled: !d.applicable, onchange: (e) => {
        if (upd({ status: e.target.value }) && S.DONE.includes(e.target.value)) {
          const rel = S.relatedOpen(scope, data, s.id, id);
          if (rel.length) say(`${rel.length} related control(s) in this domain are still open. They are not updated automatically; check whether the same work covers them.`, "info");
        }
      } }, S.STATUSES.map((k) => el("option", { value: k, selected: d.status === k }, STATUS_LABEL[k])))),
      el("td", {}, el("input", { class: "cell", "aria-label": `Owner: ${c.title}`, value: d.owner || "", placeholder: "owner", onchange: (e) => upd({ owner: e.target.value.trim() || null }, { allowClear: true }) })),
      el("td", {}, el("input", { class: "cell", type: "date", "aria-label": `Due date: ${c.title}`, value: d.due || "", onchange: (e) => upd({ due: e.target.value || null }, { allowClear: true }) })));
  }
  function bulkBar(rowsAll) {
    const n = rowsAll.length;
    const fields = { status: "", owner: "", due: "", just: "" };
    const input = (k, attrs) => el("input", Object.assign({ oninput: (e) => { fields[k] = e.target.value; } }, attrs));
    return el("details", { class: "card" },
      el("summary", {}, `Bulk edit the ${n} control(s) shown`),
      el("div", { class: "grid2" },
        el("label", {}, "Status", el("select", { onchange: (e) => { fields.status = e.target.value; } }, [["", "(leave)"], ...S.STATUSES.map((k) => [k, STATUS_LABEL[k]])].map(([v, l]) => el("option", { value: v }, l)))),
        el("label", {}, "Owner", input("owner", { placeholder: "(leave)" })),
        el("label", {}, "Due date", input("due", { type: "date" })),
        el("label", {}, "Mark not applicable: justification", input("just", { placeholder: "(leave)" }))),
      el("button", { type: "button", class: "ghost", disabled: !n, onclick: () => {
        const changes = {};
        if (fields.status) changes.status = fields.status;
        if (fields.owner.trim()) changes.owner = fields.owner.trim();
        if (fields.due) changes.due = fields.due;
        if (fields.just.trim()) { changes.applicable = false; changes.justification = fields.just.trim(); }
        if (!Object.keys(changes).length) return say("Choose at least one change to apply.", "error");
        if (changes.applicable === false && !confirm(`Mark ${n} control(s) not applicable with this justification?`)) return;
        if (n > 25 && !confirm(`Apply to all ${n} controls shown?`)) return;
        if (attempt(() => S.setDecisions(scope, data, sys().id, rowsAll.map(([c]) => c.id), changes))) { say(`Updated ${n} control(s).`, "ok"); render(); }
      } }, `Apply to ${n} control(s)`));
  }
  function focusDrawer() { setTimeout(() => { const d = document.getElementById("scope-drawer"); if (d) d.focus(); }, 0); }
  function drawer() {
    const box = el("aside", { class: "detail", id: "scope-drawer", tabindex: "-1", "aria-live": "polite" });
    const c = ui.open && S.index(data).ctl[ui.open];
    if (!c) { fill(box, el("p", { class: "muted" }, "Select a control to edit its decision, owner, evidence and notes.")); return box; }
    const s = sys(), d = S.decision(scope, s.id, c.id), ix = S.index(data);
    const f = { applicable: ui.na ? false : d.applicable };
    const form = el("form", { onsubmit: (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const changes = { applicable: fd.get("applicable") === "on", justification: String(fd.get("justification") || "").trim(), status: String(fd.get("status")),
        owner: String(fd.get("owner") || "").trim() || null, due: String(fd.get("due") || "") || null, reviewed: String(fd.get("reviewed") || "") || null,
        notes: String(fd.get("notes") || ""), evidence: String(fd.get("evidence") || "").split("\n").map((x) => x.trim()).filter(Boolean) };
      if (attempt(() => S.setDecisions(scope, data, s.id, [c.id], changes, { replaceEvidence: true, allowClear: true }))) {
        ui.na = false;
        const rel = S.DONE.includes(changes.status) ? S.relatedOpen(scope, data, s.id, c.id) : [];
        say("Saved." + (rel.length ? ` ${rel.length} related control(s) in this domain are still open; check whether the same work covers them.` : ""), "ok"); render(); focusDrawer();
      }
    } },
      el("label", { class: "inline" }, el("input", { type: "checkbox", name: "applicable", checked: f.applicable }), " This control applies to this system"),
      el("label", {}, "Justification (required if it does not apply)", el("textarea", { name: "justification", rows: "2" }, d.justification)),
      el("div", { class: "grid2" },
        el("label", {}, "Status", el("select", { name: "status" }, S.STATUSES.map((k) => el("option", { value: k, selected: d.status === k }, STATUS_LABEL[k])))),
        el("label", {}, "Owner", el("input", { name: "owner", value: d.owner || "" })),
        el("label", {}, "Due", el("input", { name: "due", type: "date", value: d.due || "" })),
        el("label", {}, "Last reviewed", el("input", { name: "reviewed", type: "date", value: d.reviewed || "" }))),
      el("label", {}, "Evidence (one reference per line)", el("textarea", { name: "evidence", rows: "3" }, d.evidence.join("\n"))),
      el("label", {}, "Notes", el("textarea", { name: "notes", rows: "2" }, d.notes)),
      el("div", { class: "row" }, el("button", { type: "submit", class: "primary" }, "Save"),
        el("button", { type: "button", class: "ghost", onclick: () => { ui.open = null; ui.na = false; render(); } }, "Close")));
    const rel = S.relatedOpen(scope, data, s.id, c.id);
    fill(box,
      el("h2", {}, c.title), el("p", { class: "r-id" }, c.id), chip(fwName(c.framework_id)), " ", chip(ix.dom[c.domain_id].name),
      el("h3", {}, "Requirement (paraphrased)"), el("p", {}, c.requirement),
      c.evidence ? [el("h3", {}, "Evidence to verify"), el("p", {}, c.evidence)] : null,
      el("h3", {}, "Your decision"), form,
      el("h3", {}, `Related controls still open in your scope (${rel.length})`),
      rel.length ? [el("p", { class: "muted" }, "Same domain, other frameworks. Review each one; none is updated automatically."),
        el("ul", { class: "rel" }, rel.slice(0, 12).map((r) => el("li", {}, el("button", { type: "button", class: "link", onclick: () => { ui.open = r.id; ui.na = false; render(); focusDrawer(); } }, `${fwName(r.framework_id)} ${r.ref}: ${r.title}`)))),
        rel.length > 12 ? el("p", { class: "muted" }, `... and ${rel.length - 12} more`) : null] : el("p", { class: "muted" }, "None."));
    return box;
  }

  // ---- export --------------------------------------------------------------------------------
  function exportPanel() {
    const s = sys();
    const top = { v: 0 };
    const full = S.plan(scope, data, s.id);
    const btn = (label, hint, fn) => el("div", { class: "export-item" }, el("button", { type: "button", class: "ghost", onclick: fn }, label), el("p", { class: "muted" }, hint));
    return el("div", { class: "card" },
      el("h3", {}, "Export"),
      el("p", { class: "muted" }, "Files are generated in your browser and downloaded directly. Cells that start with = + - or @ are prefixed with an apostrophe so spreadsheets do not run them as formulas."),
      btn("Download scope file (JSON)", "Your full scope: systems, decisions and scoping basis. Re-import it here later, share it with a colleague, or use it with the aicontrols command line. Keep it private.", () => { download("aicontrols-scope.json", JSON.stringify(scope, null, 2) + "\n", "application/json"); dirty = false; say("Scope file downloaded.", "ok"); render(); }),
      btn("Spreadsheet to fill in and re-import (CSV)", "Every control of this system with its current decision, ready to edit in Excel or Sheets and import back with “Import”. A blank cell leaves a value unchanged.", () => download(`${s.id}-decisions.csv`, "\ufeff" + S.templateCsv(data, s.frameworks, scope.organization, s.id, s.name, scope), "text/csv")),
      btn("Statement of applicability (CSV)", `One row per control (${S.inScope(scope, data, s.id).length}) with decision, justification, status, owner, due date and evidence.`, () => download(`${s.id}-soa.csv`, S.soaCsv(scope, data, s.id), "text/csv")),
      btn("Statement of applicability (Markdown)", "The same as a table you can paste into a document. A draft for review and approval.", () => download(`${s.id}-soa.md`, S.soaMarkdown(scope, data, s.id), "text/markdown")),
      btn("Governance plan (Markdown)", "Workstreams by domain, most-shared first, as shown on the Overview.", () => download(`${s.id}-plan.md`, S.planMarkdown(scope, data, s.id, full, full.length), "text/markdown")),
      el("p", { class: "muted" }, "Planning aid, not a compliance verdict."));
  }

  // ---- render -------------------------------------------------------------------------------------
  function render() {
    if (!root) return;
    const msg = el("div", { id: "scope-msg", role: "status" }); paintMsg(msg);
    let body;
    if (ui.screen === "wizard" && ui.wiz) body = ui.wiz.phase === "form" ? wizardForm() : wizardResults();
    else if (ui.screen === "workspace" && scope && ui.sid) {
      body = [workspaceBar(), subTabs(), ui.sub === "overview" ? overviewPanel() : ui.sub === "controls" ? controlsPanel()
        : ui.sub === "workflow" ? (AIC.workflowUI ? AIC.workflowUI.panel() : el("p", { class: "muted" }, "The workflow module did not load.")) : exportPanel()];
    } else body = introScreen();
    fill(root, msg, ui.report ? el("ul", { class: "report" }, ui.report.map((t) => el("li", {}, t))) : null, body);
  }

  // What the workflow screens (workflow-ui.js) may use. Reads current state through getters.
  AIC.scopeUI = {
    get scope() { return scope; }, get data() { return data; }, get sid() { return ui.sid; },
    persist, say, render, attempt, download, slug, fwName,
  };

  AIC.onData = function (d) {
    data = d; root = document.getElementById("scope-root");
    const saved = loadSaved();
    if (saved) {
      const { errors } = S.validate(saved, data);
      if (!errors.length && saved.systems.length) { scope = saved; ui.sid = saved.systems[0].id; ui.screen = "workspace"; }
    }
    render();
  };
})();
