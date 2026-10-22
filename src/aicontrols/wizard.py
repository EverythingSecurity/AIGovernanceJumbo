# SPDX-License-Identifier: Apache-2.0
"""Scoping wizard: turn plain answers about an AI system into suggested frameworks.

This is a transparent rules engine, not legal advice. Every suggestion carries the reasons
that triggered it. Regulations are only ever described as "indicated by your answers";
whether a law applies to you is for you and your counsel to decide.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .library import Library

LEVELS = ("recommended", "consider", "background", "not_indicated")
LEVEL_TEXT = {
    "recommended": "Your answers point to these",
    "consider": "Worth considering (may apply, or voluntary good practice)",
    "background": "Background reference (rarely a scoping driver)",
    "not_indicated": "No trigger indicated by your answers",
}
REGULATION_CAVEAT = ("Whether this applies depends on your facts and the law; confirm with "
                     "qualified counsel.")

YN = ("yes", "no", "unsure")


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    choices: tuple = YN
    help: str = ""


QUESTIONS: List[Question] = [
    Question("role", "What is your role for this AI system?",
             ("provider", "deployer", "both", "unsure"),
             "Provider: you develop it or put it on the market under your name. "
             "Deployer: you use a system built by someone else. Both: you do each for parts of it."),
    Question("eu", "Is the system offered or used in the EU/EEA, or are its outputs used there?",
             help="Also answer yes if your organisation is established in the EU/EEA."),
    Question("personal_data", "Does it process personal data (including in prompts, logs or training data)?",
             help="Many AI systems do, even if that is not their purpose."),
    Question("sensitive_use", "Does it operate in a sensitive area such as employment, education, "
             "credit or insurance, essential services, law enforcement, migration, justice, "
             "biometrics or critical infrastructure?",
             help="These areas are the ones the EU AI Act treats as potentially high-risk. "
                  "Classification needs care; this is only a signal."),
    Question("genai", "Does it use a large language model or other generative AI?"),
    Question("consumer", "Is it part of a product or service offered directly to consumers?"),
    Question("financial", "Are you a financial entity in the EU (bank, insurer, payment or investment "
             "firm, etc.) or an ICT service provider to one?"),
    Question("certification", "Are you aiming for a certification?",
             ("iso42001", "iso27001", "both", "none", "unsure")),
    Question("isms", "Do you already run an ISO/IEC 27001 information security management system?"),
    Question("trains_own", "Do you train or fine-tune models on data you collect or hold?"),
    Question("adversarial_testing", "Do you plan adversarial testing, red-teaming or AI threat modelling?"),
    Question("quant_risk", "Do you want to quantify AI risk in financial terms (for example with FAIR)?"),
]
QUESTION_IDS = [q.id for q in QUESTIONS]
_BY_ID = {q.id: q for q in QUESTIONS}


class WizardError(ValueError):
    """Raised for invalid answers; the message is safe to show to users."""


def normalize(raw: Dict[str, str]) -> Dict[str, str]:
    """Validate answers; unanswered questions default to 'unsure'. Returns a complete dict."""
    out = {}
    for key, value in raw.items():
        if key not in _BY_ID:
            raise WizardError(f"unknown question {key!r}; valid: {', '.join(QUESTION_IDS)}")
        q = _BY_ID[key]
        v = str(value).strip().lower()
        short = {c[0]: c for c in q.choices if len({d[0] for d in q.choices}) == len(q.choices)}
        v = short.get(v, v)
        if v not in q.choices:
            raise WizardError(f"{key}: {value!r} is not one of {', '.join(q.choices)}")
        out[key] = v
    for q in QUESTIONS:
        out.setdefault(q.id, "unsure")
    return out


@dataclass
class Recommendation:
    framework_id: str
    name: str
    kind: str
    level: str
    reasons: List[str] = field(default_factory=list)
    controls: int = 0
    caveat: Optional[str] = None

    def to_dict(self) -> dict:
        return {"framework_id": self.framework_id, "name": self.name, "kind": self.kind,
                "level": self.level, "reasons": list(self.reasons), "controls": self.controls,
                "caveat": self.caveat}


def recommend(answers: Dict[str, str], lib: Library) -> List[Recommendation]:
    """Suggest frameworks for the answers. Pure function: same answers, same output."""
    a = normalize(answers)
    yes = lambda k: a[k] == "yes"  # noqa: E731
    unsure = lambda k: a[k] == "unsure"  # noqa: E731
    out: Dict[str, Recommendation] = {}

    def put(fid: str, level: str, *reasons: str) -> None:
        fw = lib.frameworks[fid]
        out[fid] = Recommendation(
            fid, fw.name, fw.kind, level, list(reasons), fw.control_count,
            REGULATION_CAVEAT if fw.kind == "regulation" and level in ("recommended", "consider") else None)

    # --- regulations ---------------------------------------------------
    if yes("eu"):
        why = ["You indicated an EU/EEA link."]
        if a["role"] in ("provider", "both"):
            why.append("As a provider you carry the Act's heaviest obligations.")
        elif a["role"] == "deployer":
            why.append("As a deployer you have obligations too, mainly around use, oversight and transparency.")
        if yes("sensitive_use"):
            why.append("A sensitive use area may make the system high-risk; classify it carefully.")
        put("eu-ai-act", "recommended", *why)
    elif unsure("eu"):
        put("eu-ai-act", "consider", "You were unsure about an EU/EEA link; check before ruling it out.")
    else:
        put("eu-ai-act", "not_indicated", "You indicated no EU/EEA link.")

    if yes("personal_data") and yes("eu"):
        put("gdpr", "recommended", "You process personal data and have an EU/EEA link.")
    elif yes("personal_data"):
        put("gdpr", "consider", "You process personal data; GDPR also reaches some organisations "
            "outside the EU by territorial rules, so check your position.")
    elif unsure("personal_data"):
        put("gdpr", "consider", "You were unsure whether personal data is processed. Prompts, logs "
            "and training data often contain some.")
    else:
        put("gdpr", "not_indicated", "You indicated no personal data. Re-check prompts, logs and "
            "training data before relying on this.")

    if yes("financial"):
        put("dora", "recommended", "You indicated a financial entity (or its ICT provider) in the EU.")
    elif unsure("financial"):
        put("dora", "consider", "You were unsure whether DORA's financial-sector scope covers you.")
    else:
        put("dora", "not_indicated", "You indicated you are not a financial entity or its ICT provider.")

    # --- management-system and security baselines ----------------------
    if a["certification"] in ("iso42001", "both"):
        put("iso-42001", "recommended", "You are aiming for ISO/IEC 42001 certification.")
    else:
        put("iso-42001", "consider", "A widely used structure for AI governance, even without certification.")

    if a["certification"] in ("iso27001", "both") or yes("isms"):
        put("iso-27001", "recommended", "You hold or are aiming for an ISO/IEC 27001 management system, "
            "which most AI security controls build on.")
    else:
        put("iso-27001", "consider", "The security baseline most AI controls build on.")

    if yes("personal_data"):
        put("iso-27701", "consider", "Privacy extension to ISO/IEC 27001, relevant because you process "
            "personal data.")
    else:
        put("iso-27701", "background", "Privacy extension to ISO/IEC 27001; relevant if personal data "
            "is processed.")

    if a["certification"] in ("iso42001", "both") or yes("sensitive_use") or yes("eu"):
        put("iso-42005", "consider", "Guidance for AI system impact assessments, which ISO/IEC 42001 and "
            "the EU AI Act's rights-impact work both lean on.")
    else:
        put("iso-42005", "background", "Guidance for AI system impact assessments.")

    if a["certification"] != "none":
        put("iso-17021-1", "consider" if a["certification"] != "unsure" else "background",
            "Explains what certification bodies expect of an audit client.")
    else:
        put("iso-17021-1", "background", "Requirements for certification bodies; useful only if you "
            "pursue certification.")

    # --- AI-specific security ------------------------------------------
    if yes("genai"):
        put("owasp-llm", "recommended", "You use an LLM or generative AI.")
    elif unsure("genai"):
        put("owasp-llm", "consider", "You were unsure whether generative AI is involved.")
    else:
        put("owasp-llm", "not_indicated", "You indicated no LLM or generative AI.")

    threat_why = []
    if yes("genai"):
        threat_why.append("You use generative AI.")
    if yes("adversarial_testing"):
        threat_why.append("You plan adversarial testing or threat modelling.")
    for fid, text in (("mitre-atlas", "Adversary tactics against AI systems."),
                      ("iso-27090", "AI threat catalogue (a developing standard; check its current status).")):
        put(fid, "consider" if threat_why else "background", *(threat_why or []), text)
    if yes("adversarial_testing"):
        put("nist-aria", "consider", "You plan adversarial testing; ARIA is an evaluation programme "
            "(research input, not a compliance record).")
    else:
        put("nist-aria", "background", "NIST evaluation programme for AI risks and impacts.")

    # --- privacy design ------------------------------------------------
    if yes("consumer") and yes("personal_data"):
        put("iso-31700", "consider", "Consumer product that processes personal data: privacy by design "
            "for consumer goods and services.")
        put("pbd", "consider", "Consumer product that processes personal data.")
    else:
        put("iso-31700", "background", "Privacy by design for consumer products and services.")
        put("pbd", "consider" if yes("personal_data") else "background",
            *(["You process personal data."] if yes("personal_data") else []),
            "Principles for building privacy into systems.")

    # --- data and risk methods -----------------------------------------
    put("iso-5181", "consider" if yes("trains_own") else "background",
        *(["You train or fine-tune on data you hold; provenance matters (developing standard)."]
          if yes("trains_own") else ["Data provenance; relevant if you train on your own data."]))
    put("fair", "consider" if yes("quant_risk") else "background",
        *(["You want financial quantification of AI risk."] if yes("quant_risk")
          else ["Risk quantification method; useful if you need financial terms."]))
    put("nist-ai-rmf", "consider", "Voluntary, widely used structure for managing AI risk.")
    put("oecd-ai", "background", "High-level policy principles; context more than a scoping driver.")

    order = {lvl: i for i, lvl in enumerate(LEVELS)}
    kinds = {"regulation": 0, "standard": 1, "framework": 2, "threat-catalogue": 3, "methodology": 4}
    return sorted(out.values(), key=lambda r: (order[r.level], kinds.get(r.kind, 9), r.name))


def selection(recs: List[Recommendation], include: str = "recommended") -> List[str]:
    """Framework ids to put in scope: 'recommended', or 'consider' to include both tiers."""
    keep = {"recommended"} | ({"consider"} if include == "consider" else set())
    return [r.framework_id for r in recs if r.level in keep]
