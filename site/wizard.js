// SPDX-License-Identifier: Apache-2.0
// Scoping wizard rules. A faithful port of src/aicontrols/wizard.py: the two are compared by
// tests/test_site_parity.py, so change them together. Planning aid, not legal advice.
(function (root) {
  "use strict";

  const LEVELS = ["recommended", "consider", "background", "not_indicated"];
  const LEVEL_TEXT = {
    recommended: "Your answers point to these",
    consider: "Worth considering (may apply, or voluntary good practice)",
    background: "Background reference (rarely a scoping driver)",
    not_indicated: "No trigger indicated by your answers",
  };
  const REGULATION_CAVEAT = "Whether this applies depends on your facts and the law; confirm with qualified counsel.";
  const YN = ["yes", "no", "unsure"];

  const QUESTIONS = [
    { id: "role", text: "What is your role for this AI system?", choices: ["provider", "deployer", "both", "unsure"],
      help: "Provider: you develop it or put it on the market under your name. Deployer: you use a system built by someone else. Both: you do each for parts of it." },
    { id: "eu", text: "Is the system offered or used in the EU/EEA, or are its outputs used there?", choices: YN,
      help: "Also answer yes if your organisation is established in the EU/EEA." },
    { id: "personal_data", text: "Does it process personal data (including in prompts, logs or training data)?", choices: YN,
      help: "Many AI systems do, even if that is not their purpose." },
    { id: "sensitive_use", choices: YN,
      text: "Does it operate in a sensitive area such as employment, education, credit or insurance, essential services, law enforcement, migration, justice, biometrics or critical infrastructure?",
      help: "These areas are the ones the EU AI Act treats as potentially high-risk. Classification needs care; this is only a signal." },
    { id: "genai", text: "Does it use a large language model or other generative AI?", choices: YN, help: "" },
    { id: "consumer", text: "Is it part of a product or service offered directly to consumers?", choices: YN, help: "" },
    { id: "financial", choices: YN, help: "",
      text: "Are you a financial entity in the EU (bank, insurer, payment or investment firm, etc.) or an ICT service provider to one?" },
    { id: "certification", text: "Are you aiming for a certification?", choices: ["iso42001", "iso27001", "both", "none", "unsure"], help: "" },
    { id: "isms", text: "Do you already run an ISO/IEC 27001 information security management system?", choices: YN, help: "" },
    { id: "trains_own", text: "Do you train or fine-tune models on data you collect or hold?", choices: YN, help: "" },
    { id: "adversarial_testing", text: "Do you plan adversarial testing, red-teaming or AI threat modelling?", choices: YN, help: "" },
    { id: "quant_risk", text: "Do you want to quantify AI risk in financial terms (for example with FAIR)?", choices: YN, help: "" },
  ];
  const QUESTION_IDS = QUESTIONS.map((q) => q.id);
  const BY_ID = Object.fromEntries(QUESTIONS.map((q) => [q.id, q]));

  class WizardError extends Error {}

  function normalize(raw) {
    const out = {};
    for (const [key, value] of Object.entries(raw || {})) {
      const q = BY_ID[key];
      if (!q) throw new WizardError(`unknown question '${key}'; valid: ${QUESTION_IDS.join(", ")}`);
      let v = String(value).trim().toLowerCase();
      const firsts = new Set(q.choices.map((c) => c[0]));
      if (firsts.size === q.choices.length) {
        const hit = q.choices.find((c) => c[0] === v);
        if (hit) v = hit;
      }
      if (!q.choices.includes(v)) throw new WizardError(`${key}: '${value}' is not one of ${q.choices.join(", ")}`);
      out[key] = v;
    }
    for (const q of QUESTIONS) if (!(q.id in out)) out[q.id] = "unsure";
    return out;
  }

  // frameworks: array of {id, name, kind, control_count}
  function recommend(answers, frameworks) {
    const a = normalize(answers);
    const fws = Object.fromEntries(frameworks.map((f) => [f.id, f]));
    const yes = (k) => a[k] === "yes";
    const unsure = (k) => a[k] === "unsure";
    const out = {};

    function put(fid, level, ...reasons) {
      const fw = fws[fid];
      out[fid] = {
        framework_id: fid, name: fw.name, kind: fw.kind, level, reasons, controls: fw.control_count,
        caveat: fw.kind === "regulation" && (level === "recommended" || level === "consider") ? REGULATION_CAVEAT : null,
      };
    }

    // regulations
    if (yes("eu")) {
      const why = ["You indicated an EU/EEA link."];
      if (a.role === "provider" || a.role === "both") why.push("As a provider you carry the Act's heaviest obligations.");
      else if (a.role === "deployer") why.push("As a deployer you have obligations too, mainly around use, oversight and transparency.");
      if (yes("sensitive_use")) why.push("A sensitive use area may make the system high-risk; classify it carefully.");
      put("eu-ai-act", "recommended", ...why);
    } else if (unsure("eu")) {
      put("eu-ai-act", "consider", "You were unsure about an EU/EEA link; check before ruling it out.");
    } else {
      put("eu-ai-act", "not_indicated", "You indicated no EU/EEA link.");
    }

    if (yes("personal_data") && yes("eu")) {
      put("gdpr", "recommended", "You process personal data and have an EU/EEA link.");
    } else if (yes("personal_data")) {
      put("gdpr", "consider", "You process personal data; GDPR also reaches some organisations outside the EU by territorial rules, so check your position.");
    } else if (unsure("personal_data")) {
      put("gdpr", "consider", "You were unsure whether personal data is processed. Prompts, logs and training data often contain some.");
    } else {
      put("gdpr", "not_indicated", "You indicated no personal data. Re-check prompts, logs and training data before relying on this.");
    }

    if (yes("financial")) put("dora", "recommended", "You indicated a financial entity (or its ICT provider) in the EU.");
    else if (unsure("financial")) put("dora", "consider", "You were unsure whether DORA's financial-sector scope covers you.");
    else put("dora", "not_indicated", "You indicated you are not a financial entity or its ICT provider.");

    // management-system and security baselines
    if (a.certification === "iso42001" || a.certification === "both") {
      put("iso-42001", "recommended", "You are aiming for ISO/IEC 42001 certification.");
    } else {
      put("iso-42001", "consider", "A widely used structure for AI governance, even without certification.");
    }

    if (a.certification === "iso27001" || a.certification === "both" || yes("isms")) {
      put("iso-27001", "recommended", "You hold or are aiming for an ISO/IEC 27001 management system, which most AI security controls build on.");
    } else {
      put("iso-27001", "consider", "The security baseline most AI controls build on.");
    }

    if (yes("personal_data")) put("iso-27701", "consider", "Privacy extension to ISO/IEC 27001, relevant because you process personal data.");
    else put("iso-27701", "background", "Privacy extension to ISO/IEC 27001; relevant if personal data is processed.");

    if (a.certification === "iso42001" || a.certification === "both" || yes("sensitive_use") || yes("eu")) {
      put("iso-42005", "consider", "Guidance for AI system impact assessments, which ISO/IEC 42001 and the EU AI Act's rights-impact work both lean on.");
    } else {
      put("iso-42005", "background", "Guidance for AI system impact assessments.");
    }

    if (a.certification !== "none") {
      put("iso-17021-1", a.certification !== "unsure" ? "consider" : "background",
        "Explains what certification bodies expect of an audit client.");
    } else {
      put("iso-17021-1", "background", "Requirements for certification bodies; useful only if you pursue certification.");
    }

    // AI-specific security
    if (yes("genai")) put("owasp-llm", "recommended", "You use an LLM or generative AI.");
    else if (unsure("genai")) put("owasp-llm", "consider", "You were unsure whether generative AI is involved.");
    else put("owasp-llm", "not_indicated", "You indicated no LLM or generative AI.");

    const threatWhy = [];
    if (yes("genai")) threatWhy.push("You use generative AI.");
    if (yes("adversarial_testing")) threatWhy.push("You plan adversarial testing or threat modelling.");
    for (const [fid, text] of [["mitre-atlas", "Adversary tactics against AI systems."],
      ["iso-27090", "AI threat catalogue (a developing standard; check its current status)."]]) {
      put(fid, threatWhy.length ? "consider" : "background", ...threatWhy, text);
    }
    if (yes("adversarial_testing")) {
      put("nist-aria", "consider", "You plan adversarial testing; ARIA is an evaluation programme (research input, not a compliance record).");
    } else {
      put("nist-aria", "background", "NIST evaluation programme for AI risks and impacts.");
    }

    // privacy design
    if (yes("consumer") && yes("personal_data")) {
      put("iso-31700", "consider", "Consumer product that processes personal data: privacy by design for consumer goods and services.");
      put("pbd", "consider", "Consumer product that processes personal data.");
    } else {
      put("iso-31700", "background", "Privacy by design for consumer products and services.");
      put("pbd", yes("personal_data") ? "consider" : "background",
        ...(yes("personal_data") ? ["You process personal data."] : []), "Principles for building privacy into systems.");
    }

    // data and risk methods
    put("iso-5181", yes("trains_own") ? "consider" : "background",
      ...(yes("trains_own") ? ["You train or fine-tune on data you hold; provenance matters (developing standard)."]
        : ["Data provenance; relevant if you train on your own data."]));
    put("fair", yes("quant_risk") ? "consider" : "background",
      ...(yes("quant_risk") ? ["You want financial quantification of AI risk."]
        : ["Risk quantification method; useful if you need financial terms."]));
    put("nist-ai-rmf", "consider", "Voluntary, widely used structure for managing AI risk.");
    put("oecd-ai", "background", "High-level policy principles; context more than a scoping driver.");

    const order = Object.fromEntries(LEVELS.map((l, i) => [l, i]));
    const kinds = { regulation: 0, standard: 1, framework: 2, "threat-catalogue": 3, methodology: 4 };
    const cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
    return Object.values(out).sort((p, q) =>
      cmp(order[p.level], order[q.level]) || cmp(kinds[p.kind] ?? 9, kinds[q.kind] ?? 9) || cmp(p.name, q.name));
  }

  function selection(recs, include) {
    const keep = new Set(["recommended"]);
    if (include === "consider") keep.add("consider");
    return recs.filter((r) => keep.has(r.level)).map((r) => r.framework_id);
  }

  const api = { LEVELS, LEVEL_TEXT, REGULATION_CAVEAT, QUESTIONS, QUESTION_IDS, WizardError, normalize, recommend, selection };
  root.AIC = root.AIC || {};
  root.AIC.wizard = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
