// SPDX-License-Identifier: Apache-2.0
// "Client engagement" view: onboarding, scoping questionnaire, framework recommendations, review and assignment.
// Runs locally on the same scope file the command line uses (see site/engagement.js). Names are labels; nothing authenticates them.
"use strict";
(function () {
  const E = AIC.engagement;
  const ACTOR_KEY = "aicontrols.actor.v1";
  const eui = { view: "client", reason: {}, addFw: "", addReason: "", finReason: "", ruleText: "", ruleMsg: null, draft: {}, open: new Set(), mine: false, assign: {} };
  let actor = "";
  try { actor = localStorage.getItem(ACTOR_KEY) || ""; } catch (e) { /* storage may be blocked */ }

  const ui = () => AIC.scopeUI;
  const scope = () => ui().scope, data = () => ui().data;
  const human = (s) => String(s).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const fwName = (id) => { const f = data().frameworks.find((x) => x.id === id); return f ? f.name : id; };
  const TABS = [["client", "Client"], ["scoping", "Scoping questionnaire"], ["recs", "Recommendations & review"], ["packages", "Framework questionnaires"], ["roles", "Roles"], ["rules", "Applicability rules"]];
  const STAGES = [["onboarding", "Onboard the client"], ["scoping", "Complete scoping"], ["recommendation", "Run recommendations"], ["review", "Review and finalise"], ["assigned", "Frameworks assigned"]];
  const domName = (id) => { const d = data().domains.find((x) => x.id === id); return d ? d.name : id; };
  const ANSWER_LABEL = { implemented: "Implemented", partially_implemented: "Partially implemented", not_implemented: "Not implemented", not_applicable: "Not applicable" };

  function act(fn, ok) {
    const a = actor.trim();
    if (!a) return ui().say("Enter who is acting (the “Acting as” field) before making a change.", "error");
    const out = ui().attempt(() => fn(a));
    if (out === false) return false;
    if (ok) ui().say(typeof ok === "function" ? ok(out) : ok, "ok");
    ui().render();
    return out;
  }
  // Everyone who holds a role (plus the client contributor), with their roles, so you can pick who you are acting as.
  function people() {
    const S = scope(), out = new Map();
    if (E.enabled(S)) {
      for (const r of E.roles(S)) for (const n of r.people) { const k = n.trim().toLowerCase(); out.set(k, { name: n, roles: [...((out.get(k) || {}).roles || []), r.name] }); }
      const c = S.engagement.client.contributor;
      if (c) { const k = c.trim().toLowerCase(); const cur = out.get(k) || { name: c, roles: [] }; if (!cur.roles.includes("Client contributor")) cur.roles.push("Client contributor"); out.set(k, cur); }
    }
    return [...out.values()].sort((x, y) => (x.name.toLowerCase() < y.name.toLowerCase() ? -1 : 1));
  }
  // "My role": choose a role and add the name in "Acting as" to it. This is how the first person becomes admin.
  function myRole() {
    const S = scope(), name = actor.trim();
    const mine = E.enabled(S) && name ? E.rolesOf(S, name) : [];
    let sel;
    return el("div", { class: "myrole" },
      el("label", {}, "My role", sel = el("select", { "aria-label": "Role to take" }, el("option", { value: "" }, "Choose a role…"),
        E.SPEC.roles.map((r) => el("option", { value: r.id }, r.name)))),
      el("button", { type: "button", onclick: () => {
        const who = actor.trim();
        if (!sel.value) return ui().say("Choose a role first.", "error");
        if (!who) return ui().say("Type your name in “or type a name” first, then choose your role.", "error");
        if (!E.enabled(scope())) return ui().say("Save the client profile first (Client tab), then take a role.", "error");
        const holders = E.roles(scope()).find((r) => r.id === sel.value).people;
        act((a) => E.setRoles(scope(), a, sel.value, holders.some((h) => h.trim().toLowerCase() === who.toLowerCase()) ? holders : [...holders, who]), `${who} is now ${E.SPEC.roles.find((r) => r.id === sel.value).name}.`);
      } }, "Take this role"),
      el("small", { class: "muted" }, name ? (mine.length ? `${name} holds: ${mine.map((r) => E.SPEC.roles.find((x) => x.id === r).name).join(", ")}.` : `${name} holds no role yet.`) : "Enter your name first."));
  }
  function actorField() {
    const list = people(), now = actor.trim().toLowerCase();
    const known = list.find((p) => p.name.trim().toLowerCase() === now);
    return el("div", { class: "actor" },
      list.length ? el("label", {}, "Act as (pick a person and role)", el("select", { "aria-describedby": "eng-actor-help", onchange: (e) => {
        if (!e.target.value) return;
        actor = e.target.value; try { localStorage.setItem(ACTOR_KEY, actor); } catch (err) { /* ignore */ }
        ui().render();
      } }, el("option", { value: "" }, "Choose…"), list.map((p) => el("option", { value: p.name, selected: known && known.name === p.name ? "" : null }, `${p.name} (${p.roles.join(", ")})`)))) : null,
      el("label", {}, list.length ? "or type a name" : "Acting as",
        el("input", { value: actor, placeholder: "your name", autocomplete: "name", "aria-describedby": "eng-actor-help",
          oninput: (e) => { actor = e.target.value; try { localStorage.setItem(ACTOR_KEY, actor); } catch (err) { /* ignore */ } } })),
      myRole(),
      el("small", { id: "eng-actor-help", class: "muted" }, list.length
        ? "Roles are checked against this name. Recorded with every change; stored in this browser only."
        : "Recorded with every change. Stored in this browser only. Assign people to roles on the Roles tab and they will appear here to pick."));
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
      el("button", { type: "button", class: "primary", onclick: () => act((a) => E.finalise(scope(), data(), a, eui.finReason), "Framework set finalised. The framework questionnaires are ready to assign.") }, "Finalise applicable frameworks"))];
  }

  // ---- roles ----------------------------------------------------------------------------------
  function rolesView() {
    const S = scope();
    if (!E.enabled(S)) return el("div", { class: "card" }, el("p", {}, "Save the client profile first (Client tab), then assign roles."));
    const on = E.enforced(S), mine = actor.trim() ? E.rolesOf(S, actor.trim()) : [];
    return [el("div", { class: "card" }, el("h3", {}, on ? "Roles are enforced" : "Roles are not set yet"),
      el("p", { class: "muted" }, on
        ? "An action is refused unless the person named in “Acting as” holds a role that allows it. This checks the name you type; nothing proves who you are, so it guards against mistakes, not against someone typing another name."
        : "Until someone holds a role, anyone can do anything. Start by naming an engagement admin: from then on roles are enforced and only an admin can change them."),
      actor.trim() ? el("p", {}, `Acting as ${actor.trim()}: ${mine.length ? mine.map(human).join(", ") : "no role"}.`) : null),
    ...E.roles(S).map((r) => {
      let box;
      return el("div", { class: "card" }, el("h3", {}, r.name), el("p", { class: "muted" }, r.description),
        el("label", {}, "People (comma separated)", box = el("input", { value: r.people.join(", "), placeholder: "names" })),
        el("button", { type: "button", class: "primary", onclick: () => act((a) => E.setRoles(scope(), a, r.id, box.value.split(",").map((x) => x.trim()).filter(Boolean)), `${r.name}: saved.`) }, "Save"));
    })];
  }

  // ---- framework questionnaires ---------------------------------------------------------------
  function draftOf(fw, q) {
    const k = `${fw}:${q.control_id}`;
    if (!eui.draft[k]) {
      const r = q.response;
      eui.draft[k] = { answer: r ? r.answer : "", comment: r ? r.comment : "", evidence: r ? r.evidence.join(", ") : "", shared: false };
    }
    return eui.draft[k];
  }
  function questionRow(fw, q, locked) {
    const r = q.response, d = draftOf(fw, q);
    const frozen = locked || (r && (r.status === "submitted" || r.status === "approved"));
    return el("div", { class: "question" },
      el("p", {}, el("strong", {}, `${q.ref} `), q.title, " ", r ? el("span", { class: `state ${r.status === "approved" ? "approved" : r.status === "returned" ? "rejected" : r.status === "submitted" ? "assessed" : "requested"}` }, human(r.status)) : null),
      el("details", {}, el("summary", {}, "Requirement"), el("p", { class: "muted" }, q.requirement || "")),
      r && r.review && r.review.note ? el("p", { class: "muted" }, `Reviewer (${r.review.by}): ${r.review.note}`) : null,
      r && r.shared_from ? el("p", { class: "muted" }, `Copied from ${r.shared_from}`) : null,
      el("div", { class: "row" },
        el("label", {}, "Answer", el("select", { disabled: frozen ? "" : null, "aria-label": `Answer for ${q.ref}`, onchange: (e) => { d.answer = e.target.value; } },
          el("option", { value: "" }, "Choose…"), E.SPEC.answers.map((a) => el("option", { value: a, selected: d.answer === a }, ANSWER_LABEL[a])))),
        el("label", {}, "Comment", el("input", { value: d.comment, disabled: frozen ? "" : null, "aria-label": `Comment for ${q.ref}`, oninput: (e) => { d.comment = e.target.value; } })),
        el("label", {}, "Evidence (titles or links, comma separated)", el("input", { value: d.evidence, disabled: frozen ? "" : null, "aria-label": `Evidence for ${q.ref}`, oninput: (e) => { d.evidence = e.target.value; } }))),
      frozen ? null : el("div", { class: "row" },
        el("label", { class: "inline" }, el("input", { type: "checkbox", onchange: (e) => { d.shared = e.target.checked; } }), "Also apply to the same domain in other frameworks"),
        el("button", { type: "button", onclick: () => {
          const ev = d.evidence.split(",").map((x) => x.trim()).filter(Boolean);
          act((a) => E.respond(scope(), data(), a, fw, q.control_id, d.answer, d.comment, ev, d.shared), (o) => `${q.ref}: saved${o.shared_to ? `, also applied to ${o.shared_to} related question(s)` : ""}.`);
        } }, "Save answer")));
  }
  function domainBlock(fw, p, row) {
    const S = scope(), D = data();
    const key = `${fw}|${row.domain}`;
    const qs = E.packageQuestions(S, D, fw, row.domain);
    const locked = p.status === "submitted";
    const status = `${row.answered}/${row.total} answered, ${row.submitted} awaiting review, ${row.approved} approved`;
    let to, due;
    return el("details", { class: "card", open: eui.open.has(key) ? "" : null, ontoggle: (e) => { if (e.target.open) eui.open.add(key); else eui.open.delete(key); } },
      el("summary", {}, el("strong", {}, domName(row.domain)), ` — ${status}`, row.assigned_to ? ` — ${row.assigned_to}${row.due ? `, due ${row.due}` : ""}` : " — not assigned",
        row.overdue ? el("span", { class: "state overdue" }, "Overdue") : null),
      locked ? null : el("div", { class: "row" },
        el("label", {}, "Assign to", to = el("input", { value: row.assigned_to || "", placeholder: "collaborator name" })),
        el("label", {}, "Due", due = el("input", { type: "date", value: row.due || "" })),
        el("button", { type: "button", onclick: () => act((a) => E.packageAssign(scope(), data(), a, fw, to.value, due.value || null, row.domain), "Domain assigned.") }, "Assign domain"),
        el("button", { type: "button", onclick: () => act((a) => E.submitItems(scope(), data(), a, fw, row.domain), (o) => `${o.submitted} answer(s) submitted for review.`) }, "Submit answers for review"),
        el("button", { type: "button", onclick: () => act((a) => E.reviewItems(scope(), data(), a, fw, row.domain, "approve", ""), (o) => `${o.count} answer(s) approved.`) }, "Approve submitted"),
        el("button", { type: "button", class: "ghost", onclick: () => {
          const note = prompt("What needs correcting?");
          if (note !== null) act((a) => E.reviewItems(scope(), data(), a, fw, row.domain, "return", note), (o) => `${o.count} answer(s) returned.`);
        } }, "Return submitted")),
      qs.map((q) => questionRow(fw, q, locked)));
  }
  function packagesView() {
    const S = scope();
    const e = S.engagement;
    if (!E.enabled(S) || !e.applicable) return el("div", { class: "card" }, el("p", {}, "Finalise the framework set first (Recommendations & review). Each finalised framework then gets a questionnaire with one question per control."));
    const D = data();
    const fws = Object.keys(e.packages).sort();
    const tasks = actor.trim() ? E.myTasks(S, D, actor.trim()).filter((t) => t.kind === "package") : [];
    const mineSet = new Set(tasks.map((t) => `${t.framework}|${t.domain}`));
    const head = el("div", { class: "card" }, el("h3", {}, "Framework questionnaires"),
      el("p", { class: "muted" }, "One question per control of each finalised framework, grouped by domain. Hand a whole questionnaire, or one domain at a time, to a client collaborator. They answer with evidence references, submit for review, and a reviewer approves or returns. When every answer is approved the contributor submits the questionnaire, which locks it."),
      el("label", { class: "inline" }, el("input", { type: "checkbox", checked: eui.mine ? "" : null, onchange: (ev) => { eui.mine = ev.target.checked; ui().render(); } }),
        actor.trim() ? `Show only what is assigned to ${actor.trim()}` : "Show only what is assigned to me (enter your name above)"),
      eui.mine ? el("p", { class: "muted" }, `${tasks.length} task(s) for ${actor.trim() || "you"}.`) : null);
    return [head, ...fws.map((fw) => {
      const p = e.packages[fw], pr = E.packageProgress(S, D, fw);
      const a = eui.assign[fw] || (eui.assign[fw] = { to: "", due: "" });
      const rows = pr.domains.filter((r) => !eui.mine || mineSet.has(`${fw}|${r.domain}`));
      return el("div", {}, el("div", { class: "card" }, el("h3", {}, fwName(fw), " ", el("span", { class: `state ${p.status === "submitted" ? "approved" : "requested"}` }, p.status === "submitted" ? "Submitted and locked" : "Open")),
        el("p", { class: "muted" }, `${pr.approved} of ${pr.total} approved, ${pr.answered} answered, across ${pr.domains.length} domain(s).`),
        p.status === "submitted" ? el("div", { class: "row" }, el("button", { type: "button", class: "ghost", onclick: () => {
          const why = prompt("Reason for returning this questionnaire:");
          if (why !== null) act((x) => E.returnPackage(scope(), x, fw, why), "Questionnaire returned for correction.");
        } }, "Return for correction")) : el("div", { class: "row" },
          el("label", {}, "Assign the whole questionnaire to", el("input", { value: a.to, placeholder: "collaborator name", oninput: (ev) => { a.to = ev.target.value; } })),
          el("label", {}, "Due", el("input", { type: "date", value: a.due, oninput: (ev) => { a.due = ev.target.value; } })),
          el("button", { type: "button", onclick: () => act((x) => E.packageAssign(scope(), data(), x, fw, a.to, a.due || null, null), `Every domain of ${fwName(fw)} assigned.`) }, "Assign all domains"),
          el("button", { type: "button", class: "primary", onclick: () => act((x) => E.submitPackage(scope(), x, fw), "Questionnaire submitted and locked.") }, "Submit questionnaire"))),
        rows.map((r) => domainBlock(fw, p, r)));
    })];
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
    const body = { client: clientView, scoping: scopingView, recs: recsView, packages: packagesView, roles: rolesView, rules: rulesView }[eui.view]();
    return el("div", { class: "eng" },
      el("div", { class: "card actorbar" }, actorField(), el("p", { class: "muted" }, "Offline engagement file: names are labels you type and nothing authenticates them. A planning aid, not legal advice.")),
      stageBar(), tabs(), body);
  }
  AIC.engagementUI = { panel };
})();
