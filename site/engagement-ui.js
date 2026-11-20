// SPDX-License-Identifier: Apache-2.0
// "Client engagement" view: onboarding, scoping questionnaire, framework recommendations, review and assignment.
// Runs locally on the same scope file the command line uses (see site/engagement.js). Names are labels; nothing authenticates them.
"use strict";
(function () {
  const E = AIC.engagement;
  const ACTOR_KEY = "aicontrols.actor.v1";
  const eui = { view: "client", reason: {}, addFw: "", addReason: "", finReason: "", ruleText: "", ruleMsg: null };
  let actor = "";
  try { actor = localStorage.getItem(ACTOR_KEY) || ""; } catch (e) { /* storage may be blocked */ }

  const ui = () => AIC.scopeUI;
  const scope = () => ui().scope, data = () => ui().data;
  const human = (s) => String(s).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const fwName = (id) => { const f = data().frameworks.find((x) => x.id === id); return f ? f.name : id; };
  const TABS = [["client", "Client"], ["scoping", "Scoping questionnaire"], ["recs", "Recommendations & review"], ["rules", "Applicability rules"]];
  const STAGES = [["onboarding", "Onboard the client"], ["scoping", "Complete scoping"], ["recommendation", "Run recommendations"], ["review", "Review and finalise"], ["assigned", "Frameworks assigned"]];

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
      el("input", { value: actor, placeholder: "your name", autocomplete: "name", "aria-describedby": "eng-actor-help",
        oninput: (e) => { actor = e.target.value; try { localStorage.setItem(ACTOR_KEY, actor); } catch (err) { /* ignore */ } } }),
      el("small", { id: "eng-actor-help", class: "muted" }, "Recorded with every change. Stored in this browser only."));
  }
  function tabs() {
    return el("div", { class: "subtabs", role: "group", "aria-label": "Engagement views" }, TABS.map(([k, label]) =>
      el("button", { type: "button", "aria-pressed": String(eui.view === k), onclick: () => { eui.view = k; ui().render(); } }, label)));
  }
  function stageBar() {
    const o = E.overview(scope());
    const cur = o.enabled ? o.stage : "onboarding";
    const idx = STAGES.findIndex((s) => s[0] === cur);
    return el("ol", { class: "stagebar", "aria-label": "Engagement stages" }, STAGES.map(([id, label], i) =>
      el("li", {}, el("span", { class: `stage-chip${i < idx ? " done" : ""}${i === idx ? " current" : ""}`, "aria-current": i === idx ? "step" : null }, `${i + 1}. ${label}`))));
  }

  // ---- client ---------------------------------------------------------------------------------
  function clientView() {
    const S = scope(), started = E.enabled(S);
    const c = started ? S.engagement.client : { name: S.organization || "", sector: "", country: "", size: "", contributor: "", status: "invited" };
    const val = {};
    const input = (k, label) => el("label", {}, label, el("input", { value: c[k] || "", oninput: (e) => { val[k] = e.target.value; } }));
    const select = (k, label, opts) => el("label", {}, label, el("select", { onchange: (e) => { val[k] = e.target.value; } },
      el("option", { value: "" }, "Choose…"), opts.map((o) => el("option", { value: o, selected: c[k] === o }, human(o)))));
    return [el("div", { class: "card" }, el("h3", {}, "Client profile"),
      el("p", { class: "muted" }, "The consulting team (principal) records the client here, then names one contributor at the client who completes scoping."),
      input("name", "Client name"), select("sector", "Sector", E.SPEC.sectors), input("country", "Country"), select("size", "Size", E.SPEC.sizes),
      input("contributor", "Client contributor (single point of contact)"),
      el("div", { class: "row" },
        el("button", { type: "button", class: "primary", onclick: () => {
          const fields = {}; for (const k of ["name", "sector", "country", "size", "contributor"]) { const v = k in val ? val[k] : c[k]; if (v) fields[k] = v; }
          act((a) => E.setClient(scope(), a, fields), "Client profile saved.");
        } }, "Save profile"),
        el("button", { type: "button", disabled: !started || c.status === "onboarded", onclick: () => act((a) => E.onboard(scope(), a), "Client onboarded. Next: the scoping questionnaire.") },
          c.status === "onboarded" ? "Onboarded" : "Mark onboarded")),
      started ? el("p", { class: "muted" }, `Status: ${human(c.status)}.`) : null)];
  }

  // ---- scoping --------------------------------------------------------------------------------
  function questionInput(q, locked) {
    const set = (v) => act((a) => E.answer(scope(), a, q.id, v));
    if (q.kind === "yes_no" || q.kind === "single") {
      const opts = q.kind === "yes_no" ? ["yes", "no"] : q.options;
      return el("select", { "aria-label": q.text, disabled: locked, onchange: (e) => { if (e.target.value) set(e.target.value); } },
        el("option", { value: "" }, "Choose…"), opts.map((o) => el("option", { value: o, selected: q.answer === o }, human(o))));
    }
    return el("div", { class: "row", role: "group", "aria-label": q.text }, q.options.map((o) =>
      el("label", { class: "inline" }, el("input", { type: "checkbox", disabled: locked, checked: (q.answer || []).includes(o) ? "" : null, onchange: (e) => {
        const cur = new Set(q.answer || []);
        if (e.target.checked) cur.add(o); else cur.delete(o);
        if (!cur.size) { ui().say("Choose at least one option. To change the answer, tick another one first.", "error"); ui().render(); return; }
        set([...cur]);
      } }), human(o))));
  }
  function delegateRow(q, locked) {
    if (locked) return q.delegated_to ? el("small", { class: "muted" }, `Delegated to ${q.delegated_to}${q.due ? `, due ${q.due}` : ""}`) : null;
    let to, due;
    return el("details", {}, el("summary", {}, q.delegated_to ? `Delegated to ${q.delegated_to}${q.due ? `, due ${q.due}` : ""}` : "Delegate"),
      el("div", { class: "row" },
        el("label", {}, "To (department or person)", to = el("input", { value: q.delegated_to || "" })),
        el("label", {}, "Due", due = el("input", { type: "date", value: q.due || "" })),
        el("button", { type: "button", onclick: () => act((a) => E.delegate(scope(), a, q.id, to.value, due.value || null), "Question delegated.") }, "Delegate")));
  }
  function scopingView() {
    const S = scope();
    if (!E.enabled(S) || S.engagement.client.status !== "onboarded") return el("div", { class: "card" }, el("p", {}, "Onboard the client first (Client tab). Scoping opens once the client is onboarded."));
    const p = E.progress(S), locked = p.status === "submitted";
    const qs = E.questionnaire(S);
    return [el("div", { class: "card" }, el("h3", {}, `Scoping: ${p.required_answered} of ${p.required} required questions answered`),
      el("p", { class: "muted" }, "Questions marked * are required. Each answer is saved as you make it. The contributor may delegate questions, then submits the final set, which locks it."),
      locked ? el("p", {}, el("strong", {}, `Submitted by ${S.engagement.scoping.submitted_by}. `), "Answers are locked.") : null,
      el("div", { class: "row" },
        el("button", { type: "button", class: "primary", disabled: locked || p.missing.length > 0, onclick: () => act((a) => E.submitScoping(scope(), a), "Scoping submitted and locked. Next: Recommendations.") }, "Submit scoping"),
        locked ? el("button", { type: "button", class: "ghost", onclick: () => {
          const why = prompt("Reason for reopening (this clears any recommendations and review):");
          if (why !== null) act((a) => E.reopenScoping(scope(), a, why), "Scoping reopened.");
        } }, "Reopen") : null)),
    ...E.SPEC.questionnaire.domains.map((d) => el("div", { class: "card" }, el("h3", {}, d.name),
      qs.filter((q) => q.domain === d.id).map((q) => el("div", { class: "question" },
        el("p", {}, q.text, q.required ? " *" : ""), questionInput(q, locked), delegateRow(q, locked)))))];
  }

  // ---- recommendations and review -------------------------------------------------------------
  function recsView() {
    const S = scope();
    if (!E.enabled(S) || S.engagement.scoping.status !== "submitted") return el("div", { class: "card" }, el("p", {}, "Submit the scoping answers first. Recommendations are worked out from the submitted answers."));
    const e = S.engagement, rec = e.recommendation, fin = e.applicable;
    if (!rec) return el("div", { class: "card" }, el("h3", {}, "Recommend frameworks"),
      el("p", {}, "The rules (see Applicability rules) are applied to the submitted answers. The result is advisory: a reviewer confirms or changes it."),
      el("button", { type: "button", class: "primary", onclick: () => act((a) => E.recommend(scope(), data(), a), (r) => `${r.items.length} framework(s) recommended.`) }, "Run recommendations"));
    const reviewBtn = (fw, action, label, needsReason) => el("button", { type: "button", class: needsReason ? "ghost danger" : "ghost", disabled: Boolean(fin), onclick: () => {
      const why = needsReason ? (eui.reason[fw] || "").trim() : "";
      act((a) => E.review(scope(), data(), a, fw, action, why), `${fwName(fw)}: ${action}.`);
    } }, label);
    const cards = rec.items.map((i) => {
      const r = e.review[i.framework];
      return el("div", { class: "card" }, el("h3", {}, fwName(i.framework), " ", el("span", { class: "tag" }, `${i.confidence} confidence`), " ",
        r ? el("span", { class: `state ${r.action === "remove" ? "rejected" : "approved"}` }, r.action === "remove" ? "Removed" : "Accepted") : el("span", { class: "state requested" }, "To review")),
        el("ul", {}, i.rationale.map((t) => el("li", {}, t))),
        el("p", { class: "muted" }, `Rules: ${i.rules.join(", ")}. Triggered by: ${i.triggers.join(", ")}.`),
        r && r.justification ? el("p", {}, `Justification: ${r.justification} (${r.by})`) : null,
        fin ? null : el("div", { class: "row" }, reviewBtn(i.framework, "accept", "Accept", false),
          el("label", {}, "Reason (required to remove)", el("input", { value: eui.reason[i.framework] || "", oninput: (ev) => { eui.reason[i.framework] = ev.target.value; } })),
          reviewBtn(i.framework, "remove", "Remove", true)));
    });
    const recommended = new Set(rec.items.map((i) => i.framework));
    const addable = data().frameworks.filter((f) => !recommended.has(f.id));
    const added = Object.entries(e.review).filter(([, r]) => r.action === "add");
    return [el("div", { class: "card" }, el("h3", {}, "Recommendations"),
      el("p", { class: "muted" }, `Worked out ${rec.at.slice(0, 10)} by ${rec.by} with rules version ${rec.rules_version}. Removing or adding a framework needs a written reason, recorded in the audit trail.`),
      fin ? el("p", {}, el("strong", {}, `Finalised by ${fin.approver}: `), fin.frameworks.map(fwName).join(", ")) : null,
      rec.skipped.length ? el("details", {}, el("summary", {}, `${rec.skipped.length} rule(s) matched but point at a framework this library does not have`),
        el("ul", {}, rec.skipped.map((s) => el("li", {}, `${s.rule}: ${s.framework} ${s.reason}`)))) : null,
      el("div", { class: "row" }, fin ? el("button", { type: "button", class: "ghost", onclick: () => {
        const why = prompt("Reason for reopening the framework set:");
        if (why !== null) act((a) => E.reopenAssignment(scope(), a, why), "Assignment reopened.");
      } }, "Reopen assignment") : null)),
    ...cards,
    fin ? null : el("div", { class: "card" }, el("h3", {}, "Add a framework the rules did not recommend"),
      added.length ? el("p", { class: "muted" }, `Added so far: ${added.map(([f]) => fwName(f)).join(", ")}`) : null,
      el("div", { class: "row" },
        el("label", {}, "Framework", el("select", { onchange: (ev) => { eui.addFw = ev.target.value; } }, el("option", { value: "" }, "Choose…"),
          addable.map((f) => el("option", { value: f.id, selected: eui.addFw === f.id }, f.name)))),
        el("label", {}, "Reason (required)", el("input", { value: eui.addReason, oninput: (ev) => { eui.addReason = ev.target.value; } })),
        el("button", { type: "button", onclick: () => { if (!eui.addFw) return ui().say("Choose a framework to add.", "error"); if (act((a) => E.review(scope(), data(), a, eui.addFw, "add", eui.addReason), `${fwName(eui.addFw)} added.`) !== false) { eui.addFw = ""; eui.addReason = ""; } } }, "Add"))),
    fin ? null : el("div", { class: "card" }, el("h3", {}, "Finalise"),
      el("p", { class: "muted" }, `Every recommendation must be accepted or removed first. The applicable set would be: ${E.applicableFrameworks(S).map(fwName).join(", ") || "none"}.`),
      el("label", {}, "Note (optional)", el("input", { value: eui.finReason, oninput: (ev) => { eui.finReason = ev.target.value; } })),
      el("button", { type: "button", class: "primary", onclick: () => act((a) => E.finalise(scope(), a, eui.finReason), "Framework set finalised.") }, "Finalise applicable frameworks"))];
  }

  // ---- rules ----------------------------------------------------------------------------------
  const EXAMPLE = { id: "R-MY-RULE", framework: "iso-27001", confidence: "medium", weight: 20, rationale: "Why this framework fits.",
    when: { q: "t_outsourcing", op: "is", value: "yes" } };
  function rulesView() {
    const S = scope();
    const rules = E.effectiveRules(S);
    return [el("div", { class: "card" }, el("h3", {}, "Applicability rules"),
      el("p", { class: "muted" }, "Rules decide which frameworks are recommended from the scoping answers. They are data: switch one off, or add your own below. Changing a rule raises the rules version recorded with each recommendation."),
      el("div", { class: "scroll" }, el("table", { class: "grid" },
        el("thead", {}, el("tr", {}, ["Rule", "Framework", "Confidence", "Weight", "Source", "Why", "Active"].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", {}, rules.map((r) => el("tr", {}, el("th", { scope: "row" }, r.id), el("td", {}, r.framework ? r.framework : `from answer ${r.from_answer}`),
          el("td", {}, r.confidence), el("td", {}, r.weight), el("td", {}, r.source), el("td", { class: "muted" }, r.rationale),
          el("td", {}, el("label", { class: "inline" }, el("input", { type: "checkbox", checked: r.disabled ? null : "", "aria-label": `${r.id} active`,
            onchange: (ev) => act((a) => E.ruleDisable(scope(), a, r.id, !ev.target.checked), `${r.id} ${ev.target.checked ? "enabled" : "disabled"}.`) }))))))))),
    el("div", { class: "card" }, el("h3", {}, "Add or replace a custom rule"),
      el("p", { class: "muted" }, "A rule is JSON: an id (R-…), a framework id, a confidence (low, medium, high), a weight (1 to 100), a rationale, and a condition built from {all}, {any}, {not} and {q, op, value} (op is, has or in). Using an existing id replaces that rule."),
      el("label", {}, "Rule (JSON)", el("textarea", { rows: "12", spellcheck: "false", oninput: (ev) => { eui.ruleText = ev.target.value; } }, eui.ruleText || JSON.stringify(EXAMPLE, null, 2))),
      eui.ruleMsg ? el("p", { class: "muted", role: "status" }, eui.ruleMsg) : null,
      el("div", { class: "row" }, el("button", { type: "button", class: "primary", onclick: () => {
        let rule;
        try { rule = JSON.parse(eui.ruleText || JSON.stringify(EXAMPLE)); } catch (ex) { eui.ruleMsg = `That is not valid JSON: ${ex.message}`; return ui().render(); }
        eui.ruleMsg = null;
        if (act((a) => E.ruleSet(scope(), a, rule), (r) => `Rule ${r.id} saved.`) !== false) { eui.ruleText = ""; ui().render(); }
      } }, "Save rule")))];
  }

  function panel() {
    const body = { client: clientView, scoping: scopingView, recs: recsView, rules: rulesView }[eui.view]();
    return el("div", { class: "eng" },
      el("div", { class: "card actorbar" }, actorField(), el("p", { class: "muted" }, "Offline engagement file: names are labels you type and nothing authenticates them. A planning aid, not legal advice.")),
      stageBar(), tabs(), body);
  }
  AIC.engagementUI = { panel };
})();
