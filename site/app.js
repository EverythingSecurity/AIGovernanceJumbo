// SPDX-License-Identifier: Apache-2.0
"use strict";

// Data lives in ../data in a checkout and in ./data when deployed to GitHub Pages.
const DATA_BASES = ["data/", "../data/"];
const PAGE = 40;
const state = { q: "", fw: "", dom: "", cia: "", id: "", tab: "", shown: PAGE };
let controls = [], frameworks = [], domains = [], byId = new Map(), fwById = new Map(), domById = new Map();

const $ = (id) => document.getElementById(id);

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) node.append(kid.nodeType ? kid : document.createTextNode(kid));
  return node;
}

// Replace a node's children; accepts nested arrays and skips null/false.
function fill(node, ...kids) {
  node.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
}

async function loadJSON(name) {
  let lastErr;
  for (const base of DATA_BASES) {
    try {
      const r = await fetch(base + name);
      if (r.ok) return await r.json();
      lastErr = new Error(`${base}${name}: HTTP ${r.status}`);
    } catch (e) { lastErr = e; }
  }
  throw lastErr;
}

const stem = (w) => (w.length > 3 && w.endsWith("s") && !w.endsWith("ss") ? w.slice(0, -1) : w);
const tokens = (s) => (s.toLowerCase().match(/[a-z0-9]+/g) || []).map(stem);
const shortName = (f) => f.name.replace("ISO/IEC ", "ISO ").replace(" (Cavoukian)", "")
  .replace(" Risk Methodology", "").replace(" AI Principles", "").replace(" Top 10", "");

function score(c, words) {
  if (!c._title) {
    c._title = new Set(tokens(`${c.title} ${c.ref}`));
    c._body = new Set(tokens([c.requirement, c.security_note, c.evidence, ...Object.values(c.extras || {})].filter(Boolean).join(" ")));
  }
  let s = 0;
  for (const w of words) {
    if (c._title.has(w)) s += 3;
    else if (c._body.has(w)) s += 1;
    else if ([...c._title].some((t) => t.startsWith(w))) s += 2;
    else if ([...c._body].some((t) => t.startsWith(w))) s += 0.5;
  }
  return s;
}

function matches() {
  const words = tokens(state.q);
  const out = [];
  for (const c of controls) {
    if (c.kind === "info") continue;
    if (state.fw && c.framework_id !== state.fw) continue;
    if (state.dom && c.domain_id !== state.dom) continue;
    if (state.cia.includes("c") && !c.cia.c) continue;
    if (state.cia.includes("i") && !c.cia.i) continue;
    if (state.cia.includes("a") && !c.cia.a) continue;
    if (words.length) {
      const s = score(c, words);
      if (!s) continue;
      out.push([-s, c]);
    } else out.push([0, c]);
  }
  if (words.length) out.sort((a, b) => a[0] - b[0]);
  return out.map((x) => x[1]);
}

function badges(c) {
  return el("span", { class: "badges", "aria-label": `Protects: ${["c", "i", "a"].filter((k) => c.cia[k]).map((k) => ({ c: "confidentiality", i: "integrity", a: "availability" })[k]).join(", ") || "not marked"}` },
    ["c", "i", "a"].map((k) => el("span", { class: `badge ${k}${c.cia[k] ? " on" : ""}`, "aria-hidden": "true" }, k.toUpperCase())));
}

function renderResults() {
  const rows = matches();
  const list = $("results");
  fill(list, rows.slice(0, state.shown).map((c) => el("li", {},
    el("button", { type: "button", "aria-current": c.id === state.id ? "true" : false, onclick: () => select(c.id) },
      el("span", { class: "r-top" }, el("span", { class: "r-title" }, c.title), badges(c)),
      el("span", { class: "r-id" }, c.id),
      el("span", { class: "r-fw" }, fwById.get(c.framework_id).name)))));
  $("count").textContent = `${rows.length} control${rows.length === 1 ? "" : "s"}`;
  $("more").hidden = rows.length <= state.shown;
  $("more").textContent = `Show more (${rows.length - state.shown} left)`;
}

function field(label, text) {
  return text ? [el("h3", {}, label), el("p", {}, text)] : [];
}

function renderDetail() {
  const box = $("detail");
  const c = byId.get(state.id);
  if (!c) {
    fill(box, el("p", { class: "muted" }, "Select a control to see its requirement, evidence to collect, and related controls in other frameworks."));
    return;
  }
  const dom = domById.get(c.domain_id), fw = fwById.get(c.framework_id);
  const related = new Map();
  for (const id of dom.control_ids) {
    const r = byId.get(id);
    if (r.framework_id === c.framework_id || r.kind === "info") continue;
    if (!related.has(r.framework_id)) related.set(r.framework_id, []);
    related.get(r.framework_id).push(r);
  }
  const extras = Object.entries(c.extras || {}).flatMap(([k, v]) => field(k.replace(/_/g, " ").replace(/^./, (m) => m.toUpperCase()), v));
  const relCount = [...related.values()].reduce((n, a) => n + a.length, 0);
  fill(box,
    el("h2", {}, c.title),
    el("p", { class: "r-id" }, c.id), 
    el("span", { class: "tag" }, fw.full_name),
    c.section ? el("span", { class: "tag" }, c.section) : null,
    el("span", { class: "tag" }, el("button", { type: "button", class: "link", onclick: () => setFilter({ dom: c.domain_id }) }, dom.name)),
    el("p", {}, badges(c)),
    ...field("Requirement (paraphrased)", c.requirement),
    ...field("Security note", c.security_note),
    ...field("Evidence to verify", c.evidence),
    ...extras,
    dom.consolidation_guidance ? [el("h3", {}, "Consolidation guidance"), el("p", {}, dom.consolidation_guidance)] : [],
    el("h3", {}, relCount ? `Also in this domain (${relCount} controls in ${related.size} other frameworks)` : "Also in this domain"),
    relCount ? null : el("p", { class: "muted" }, "No other framework in this dataset maps to this domain."),
    [...related].map(([fid, list]) => el("div", { class: "rel-group" },
      el("strong", {}, fwById.get(fid).name),
      el("ul", {}, list.map((r) => el("li", {}, el("button", { type: "button", class: "link", onclick: () => select(r.id) }, `${r.ref} ${r.title}`)))))));
}

function renderHeatmap() {
  const counts = new Map(); let max = 1;
  for (const c of controls) {
    if (c.kind === "info") continue;
    const k = `${c.domain_id}|${c.framework_id}`;
    const n = (counts.get(k) || 0) + 1; counts.set(k, n); max = Math.max(max, n);
  }
  const table = $("heat");
  fill(table,
    el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Domain"),
      frameworks.map((f) => el("th", { scope: "col", title: f.full_name }, shortName(f))))),
    el("tbody", {}, domains.map((d) => el("tr", {}, el("th", { scope: "row" }, d.name),
      frameworks.map((f) => {
        const n = counts.get(`${d.id}|${f.id}`) || 0;
        if (!n) return el("td", { class: "zero" }, "·");
        return el("td", { style: `background:rgba(var(--heat), ${(0.08 + 0.5 * n / max).toFixed(2)})` },
          el("button", { type: "button", "aria-label": `${n} ${f.name} controls in ${d.name}`, onclick: () => { setFilter({ fw: f.id, dom: d.id }); showTab("explore"); } }, String(n)));
      })))));
}

// ---- state <-> URL hash -------------------------------------------------
function writeHash() {
  const p = new URLSearchParams();
  for (const k of ["q", "fw", "dom", "cia", "id", "tab"]) if (state[k]) p.set(k, state[k]);
  const h = p.toString();
  history.replaceState(null, "", h ? `#${h}` : location.pathname + location.search);
}
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k of ["q", "fw", "dom", "cia", "id", "tab"]) state[k] = p.get(k) || "";
  if (state.tab !== "heatmap") state.tab = "";
  if (state.fw && !fwById.has(state.fw)) state.fw = "";
  if (state.dom && !domById.has(state.dom)) state.dom = "";
  if (state.id && !byId.has(state.id)) state.id = "";
}
function syncInputs() {
  $("q").value = state.q; $("fw").value = state.fw; $("dom").value = state.dom;
  for (const k of ["c", "i", "a"]) $(`cia-${k}`).checked = state.cia.includes(k);
}
function refresh() { state.shown = PAGE; writeHash(); renderResults(); renderDetail(); }
function setFilter(patch) { Object.assign(state, patch); syncInputs(); refresh(); }
function select(id) { state.id = id; writeHash(); renderResults(); renderDetail(); $("detail").focus({ preventScroll: false }); }

function showTab(name) {
  state.tab = name === "heatmap" ? "heatmap" : "";
  writeHash();
  for (const t of ["explore", "heatmap"]) {
    $(`tab-${t}`).setAttribute("aria-selected", String(t === name));
    $(`view-${t}`).hidden = t !== name;
  }
}

async function init() {
  try {
    const [c, f, d] = await Promise.all([loadJSON("controls.json"), loadJSON("frameworks.json"), loadJSON("domains.json")]);
    controls = c.controls; frameworks = f.frameworks; domains = d.domains;
    $("meta").textContent = `Dataset v${c.dataset_version} · ${controls.filter((x) => x.kind !== "info").length} controls · ${frameworks.length} frameworks · ${domains.length} domains`;
  } catch (e) {
    $("status").textContent = `Could not load the dataset (${e.message}). If you opened this file directly, serve the repository root instead: python3 -m http.server, then open /site/.`;
    return;
  }
  byId = new Map(controls.map((x) => [x.id, x]));
  fwById = new Map(frameworks.map((x) => [x.id, x]));
  domById = new Map(domains.map((x) => [x.id, x]));
  $("fw").append(...frameworks.map((x) => el("option", { value: x.id }, `${x.name} (${x.control_count})`)));
  $("dom").append(...domains.map((x) => el("option", { value: x.id }, `${x.name} (${x.control_ids.length})`)));

  let t;
  $("q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value; refresh(); }, 120); });
  $("fw").addEventListener("change", (e) => { state.fw = e.target.value; refresh(); });
  $("dom").addEventListener("change", (e) => { state.dom = e.target.value; refresh(); });
  for (const k of ["c", "i", "a"]) $(`cia-${k}`).addEventListener("change", () => {
    state.cia = ["c", "i", "a"].filter((x) => $(`cia-${x}`).checked).join(""); refresh();
  });
  $("reset").addEventListener("click", () => { Object.assign(state, { q: "", fw: "", dom: "", cia: "", id: "" }); syncInputs(); refresh(); });
  $("more").addEventListener("click", () => { state.shown += PAGE; renderResults(); });
  $("tab-explore").addEventListener("click", () => showTab("explore"));
  $("tab-heatmap").addEventListener("click", () => showTab("heatmap"));
  window.addEventListener("hashchange", () => { readHash(); syncInputs(); renderResults(); renderDetail(); showTab(state.tab || "explore"); });

  readHash(); syncInputs(); renderHeatmap(); renderResults(); renderDetail();
  $("status").hidden = true;
  showTab(state.tab || "explore");
}
init();
